from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    TREND_SERIES_RESOLUTION_CONTRACT_VERSION,
    ResolvedTrendObservation,
    ResolvedTrendSegment,
    ResolvedTrendSeries,
    TrendComputationStatus,
    TrendCoverageKind,
    TrendDirection,
    TrendEvidenceLevel,
    TrendNegativeBaseDirection,
    TrendObservation,
    TrendOneOffStatus,
    TrendPairwiseCalculationError,
    TrendPeriodFamily,
    TrendRestatementProfile,
    TrendSegmentBoundary,
    TrendSegmentBoundaryKind,
    TrendTransitionKind,
    TrendWarningCode,
    analyze_pairwise_series,
    canonical_trend_digest,
    canonical_trend_reference,
    generate_pairwise_transitions,
)


COMPANY = UUID("11111111-1111-4111-8111-111111111111")
TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _uuid(prefix: int, ordinal: int) -> UUID:
    return UUID(f"{prefix:08x}-0000-4000-8000-{ordinal:012d}")


def resolved_series(
    values: tuple[Decimal | None, ...],
    *,
    metric_code: str = "bs.total_assets",
    evidence: tuple[TrendEvidenceLevel, ...] | None = None,
    segments: tuple[int, ...] | None = None,
    years: tuple[int, ...] | None = None,
    restatements: tuple[TrendRestatementProfile, ...] | None = None,
    one_offs: tuple[TrendOneOffStatus, ...] | None = None,
) -> ResolvedTrendSeries:
    definition = TREND_METRIC_REGISTRY_V1.get(metric_code)
    evidence = evidence or tuple(
        TrendEvidenceLevel.EXACT if value is not None else TrendEvidenceLevel.UNAVAILABLE
        for value in values
    )
    segments = segments or tuple(0 for _ in values)
    years = years or tuple(2020 + index for index in range(len(values)))
    restatements = restatements or tuple(TrendRestatementProfile.ORIGINAL for _ in values)
    one_offs = one_offs or tuple(TrendOneOffStatus.INCLUDED_UNADJUSTED for _ in values)
    resolved = []
    for ordinal, (value, level, segment, year, restatement, one_off) in enumerate(
        zip(values, evidence, segments, years, restatements, one_offs)
    ):
        version = definition.accepted_source_versions[0]
        observation = TrendObservation(
            ordinal=ordinal,
            segment_ordinal=segment,
            company_id=COMPANY,
            period_id=_uuid(1, ordinal + 1),
            period_start_date=date(year, 1, 1),
            period_end_date=date(year, 12, 31),
            period_family=TrendPeriodFamily.ANNUAL,
            coverage_kind=TrendCoverageKind.CUMULATIVE,
            measurement_basis=definition.measurement_basis_for(TrendPeriodFamily.ANNUAL),
            value=value,
            currency="TRY",
            monetary_unit_multiplier=Decimal("1"),
            scale=definition.scale,
            evidence=level,
            source_result_id=_uuid(2, ordinal + 1),
            source_engine_type=definition.source_engine_type,
            source_schema_version=version.schema_version,
            source_model_version=version.model_version,
            canonical_source_digest=f"{ordinal + 1:x}" * 64,
            restatement_profile=restatement,
            restatement_revision=1 if restatement is TrendRestatementProfile.RESTATED else 0,
            one_off_status=one_off,
            warnings=(),
        )
        digest = canonical_trend_digest((4, definition.source_field_path, observation))
        resolved.append(ResolvedTrendObservation(4, definition.source_field_path, observation, digest))
    segment_rows = tuple(
        ResolvedTrendSegment(
            segment,
            tuple(item.observation.ordinal for item in resolved if item.observation.segment_ordinal == segment),
            canonical_trend_digest(("segment", segment)),
        )
        for segment in sorted(set(segments))
    )
    gaps = []
    boundaries = []
    for left, right in zip(resolved, resolved[1:]):
        if left.observation.segment_ordinal != right.observation.segment_ordinal:
            kind = (
                TrendSegmentBoundaryKind.RESTATEMENT_CHANGE
                if left.observation.restatement_profile is not right.observation.restatement_profile
                else TrendSegmentBoundaryKind.PERIOD_GAP
            )
            boundaries.append(TrendSegmentBoundary(left.observation.period_id, right.observation.period_id, kind))
            if kind is TrendSegmentBoundaryKind.PERIOD_GAP:
                from app.engines.multi_period_trend import TrendGap
                gaps.append(TrendGap(
                    left.observation.period_id,
                    right.observation.period_id,
                    date(left.observation.period_end_date.year + 1, 1, 1),
                    date(right.observation.period_start_date.year - 1, 12, 31),
                ))
    resolution_digest = canonical_trend_digest((metric_code, tuple(item.observation_digest for item in resolved)))
    candidate_digest = canonical_trend_digest(("candidate", metric_code, len(values)))
    return ResolvedTrendSeries(
        tenant_id=TENANT,
        company_id=COMPANY,
        anchor_period_id=resolved[-1].observation.period_id,
        metric_code=metric_code,
        period_family=TrendPeriodFamily.ANNUAL,
        currency="TRY",
        monetary_unit_multiplier=Decimal("1"),
        observations=tuple(resolved),
        gaps=tuple(gaps),
        segment_boundaries=tuple(boundaries),
        segments=segment_rows,
        candidate_set_digest=candidate_digest,
        resolution_digest=resolution_digest,
        resolution_reference=canonical_trend_reference(resolution_digest),
        nominal_values=True,
        inflation_adjusted=False,
        contract_version=TREND_SERIES_RESOLUTION_CONTRACT_VERSION,
    )


@pytest.mark.parametrize(
    ("prior", "current", "absolute", "kind", "percentage", "direction", "negative_direction"),
    [
        ("100", "125", "25.00", "percentage_available", "25.0000", "increasing", "not_applicable"),
        ("125", "100", "-25.00", "percentage_available", "-20.0000", "decreasing", "not_applicable"),
        ("-100", "-80", "20.00", "absolute_only_negative_base", None, "increasing", "improving"),
        ("-80", "-100", "-20.00", "absolute_only_negative_base", None, "decreasing", "worsening"),
        ("-80", "-80", "0", "absolute_only_negative_base", None, "stable", "unchanged"),
        ("0", "10", "10.00", "absolute_only_zero_base", None, "increasing", "not_applicable"),
        ("10", "0", "-10.00", "absolute_only_sign_change", None, "sign_change", "not_applicable"),
        ("10", "-1", "-11.00", "absolute_only_sign_change", None, "sign_change", "not_applicable"),
        ("-1", "10", "11.00", "absolute_only_sign_change", None, "sign_change", "not_applicable"),
    ],
)
def test_pairwise_absolute_percentage_and_sign_matrix(
    prior, current, absolute, kind, percentage, direction, negative_direction
):
    transition = generate_pairwise_transitions(
        resolved_series((Decimal(prior), Decimal(current))), TREND_METRIC_REGISTRY_V1
    )[0]
    assert transition.absolute_change == Decimal(absolute)
    assert transition.transition_kind.value == kind
    assert transition.percentage_change == (Decimal(percentage) if percentage is not None else None)
    assert transition.direction.value == direction
    assert transition.negative_base_direction.value == negative_direction


@pytest.mark.parametrize("missing", (0, 1))
def test_missing_endpoint_is_never_zero_and_yields_unavailable_transition(missing):
    values = [Decimal("10"), Decimal("20")]
    values[missing] = None
    transition = generate_pairwise_transitions(resolved_series(tuple(values)), TREND_METRIC_REGISTRY_V1)[0]
    assert transition.transition_kind is TrendTransitionKind.UNAVAILABLE_MISSING_INPUT
    assert transition.absolute_change is None
    assert transition.percentage_change is None
    assert transition.evidence is TrendEvidenceLevel.UNAVAILABLE


@pytest.mark.parametrize("invalid", (1, 1.0, "1", Decimal("NaN")))
def test_observation_contract_rejects_non_decimal_or_non_finite(invalid):
    with pytest.raises(Exception):
        resolved_series((invalid, Decimal("2")))  # type: ignore[arg-type]


def test_half_even_scale_and_negative_zero_are_canonical():
    result = generate_pairwise_transitions(
        resolved_series((Decimal("1.005"), Decimal("1.010"))), TREND_METRIC_REGISTRY_V1
    )[0]
    assert result.absolute_change == Decimal("0.00")
    assert not result.absolute_change.is_signed()
    zero = generate_pairwise_transitions(
        resolved_series((Decimal("0.00"), Decimal("-0.00"))), TREND_METRIC_REGISTRY_V1
    )[0]
    assert zero.absolute_change == 0 and not zero.absolute_change.is_signed()


@pytest.mark.parametrize("metric_code", ("ratio.current_ratio", "ratio.cash_conversion_cycle"))
def test_ratio_rate_percentage_is_disabled_without_changing_ratio_engine(metric_code):
    transition = generate_pairwise_transitions(
        resolved_series((Decimal("1"), Decimal("2")), metric_code=metric_code),
        TREND_METRIC_REGISTRY_V1,
    )[0]
    assert transition.transition_kind is TrendTransitionKind.ABSOLUTE_ONLY_RATIO_RATE
    assert transition.percentage_change is None


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ((TrendEvidenceLevel.EXACT, TrendEvidenceLevel.EXACT), TrendEvidenceLevel.DERIVED),
        ((TrendEvidenceLevel.EXACT, TrendEvidenceLevel.DERIVED), TrendEvidenceLevel.DERIVED),
        ((TrendEvidenceLevel.DERIVED, TrendEvidenceLevel.ESTIMATED), TrendEvidenceLevel.ESTIMATED),
        ((TrendEvidenceLevel.EXACT, TrendEvidenceLevel.UNAVAILABLE), TrendEvidenceLevel.UNAVAILABLE),
    ],
)
def test_transition_evidence_never_upgrades(evidence, expected):
    values = (Decimal("1"), None) if expected is TrendEvidenceLevel.UNAVAILABLE else (Decimal("1"), Decimal("2"))
    transition = generate_pairwise_transitions(
        resolved_series(values, evidence=evidence), TREND_METRIC_REGISTRY_V1
    )[0]
    assert transition.evidence is expected


def test_metric_specific_tolerance_has_exact_boundaries_and_no_global_fallback():
    money_at = generate_pairwise_transitions(
        resolved_series((Decimal("1"), Decimal("1.01"))), TREND_METRIC_REGISTRY_V1
    )[0]
    money_above = generate_pairwise_transitions(
        resolved_series((Decimal("1"), Decimal("1.011"))), TREND_METRIC_REGISTRY_V1
    )[0]
    ratio_at = generate_pairwise_transitions(
        resolved_series((Decimal("1"), Decimal("1.0001")), metric_code="ratio.current_ratio"),
        TREND_METRIC_REGISTRY_V1,
    )[0]
    assert money_at.direction is TrendDirection.STABLE
    assert money_above.direction is TrendDirection.INCREASING
    assert ratio_at.direction is TrendDirection.STABLE
    assert money_at.stable_tolerance == Decimal("0.01")
    assert ratio_at.stable_tolerance == Decimal("0.0001")


def test_gap_and_restatement_boundaries_never_create_transition():
    gap = resolved_series(
        (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")),
        segments=(0, 0, 1, 1),
        years=(2021, 2022, 2024, 2025),
    )
    assert [(item.from_period_id, item.to_period_id) for item in generate_pairwise_transitions(gap, TREND_METRIC_REGISTRY_V1)] == [
        (_uuid(1, 1), _uuid(1, 2)), (_uuid(1, 3), _uuid(1, 4))
    ]
    restated = resolved_series(
        (Decimal("1"), Decimal("2"), Decimal("3")),
        segments=(0, 1, 1),
        restatements=(TrendRestatementProfile.ORIGINAL, TrendRestatementProfile.RESTATED, TrendRestatementProfile.RESTATED),
    )
    assert len(generate_pairwise_transitions(restated, TREND_METRIC_REGISTRY_V1)) == 1


def test_two_independent_segments_do_not_claim_aggregate_direction():
    result = analyze_pairwise_series(resolved_series(
        (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")),
        segments=(0, 0, 1, 1), years=(2021, 2022, 2024, 2025),
    ))
    assert result.direction is TrendDirection.INSUFFICIENT_DATA
    assert result.status is TrendComputationStatus.PARTIAL


def test_wrong_scale_or_segment_manifest_fails_closed():
    series = resolved_series((Decimal("1"), Decimal("2"), Decimal("3")))
    bad_observation = replace(series.observations[1].observation, scale=3)
    bad_resolved = replace(
        series.observations[1],
        observation=bad_observation,
        observation_digest=canonical_trend_digest((4, series.observations[1].source_field_path, bad_observation)),
    )
    with pytest.raises(TrendPairwiseCalculationError):
        generate_pairwise_transitions(replace(series, observations=(series.observations[0], bad_resolved, series.observations[2])), TREND_METRIC_REGISTRY_V1)
    bad_segment = replace(series.segments[0], observation_ordinals=(0, 2))
    with pytest.raises(TrendPairwiseCalculationError):
        generate_pairwise_transitions(replace(series, segments=(bad_segment,)), TREND_METRIC_REGISTRY_V1)


def test_safe_representation_and_no_raw_payload_fields():
    transition = generate_pairwise_transitions(
        resolved_series((Decimal("1"), Decimal("2"))), TREND_METRIC_REGISTRY_V1
    )[0]
    assert repr(transition) == "TrendTransition()"
    assert repr(TrendPairwiseCalculationError.__new__(TrendPairwiseCalculationError)) == "TrendPairwiseCalculationError()"
    assert not hasattr(transition, "payload")
    assert transition.transition_reference == canonical_trend_reference((
        transition.metric_code, transition.from_period_id, transition.to_period_id,
        transition.from_value, transition.to_value, transition.absolute_change,
        transition.percentage_change, transition.transition_kind, transition.direction,
        transition.negative_base_direction, transition.evidence, transition.stable_tolerance,
        transition.registry_digest, transition.policy_version,
        transition.observation_reference_digests, transition.source_reference_digests,
        transition.warnings, transition.errors,
    ))


def test_result_status_and_4_6e_fields_remain_unevaluated():
    one_missing = analyze_pairwise_series(resolved_series((Decimal("1"), None)))
    two = analyze_pairwise_series(resolved_series((Decimal("1"), Decimal("2"))))
    three = analyze_pairwise_series(resolved_series((Decimal("1"), Decimal("2"), Decimal("3"))))
    partial = analyze_pairwise_series(resolved_series((Decimal("1"), Decimal("2"), Decimal("3"), None)))
    assert one_missing.status is TrendComputationStatus.INSUFFICIENT_DATA
    assert two.status is TrendComputationStatus.INSUFFICIENT_FOR_TREND
    assert three.status is TrendComputationStatus.COMPLETE
    assert three.direction is TrendDirection.INCREASING
    assert partial.status is TrendComputationStatus.PARTIAL
    for result in (one_missing, two, three, partial):
        assert result.break_result.detected is None
        assert result.break_result.score is None
        assert not hasattr(result, "cagr")
        assert not hasattr(result, "volatility")
        assert not hasattr(result, "forecast")


def test_zero_base_sign_change_and_negative_semantic_warnings_are_typed():
    transitions = generate_pairwise_transitions(
        resolved_series((Decimal("0"), Decimal("1"), Decimal("-1"), Decimal("-2"))),
        TREND_METRIC_REGISTRY_V1,
    )
    assert [warning.code for transition in transitions for warning in transition.warnings] == [
        TrendWarningCode.PERCENTAGE_ZERO_BASE,
        TrendWarningCode.SIGN_CHANGE_PERCENTAGE_SUPPRESSED,
        TrendWarningCode.NEGATIVE_BASE_SEMANTIC_ONLY,
    ]
    assert transitions[-1].negative_base_direction is TrendNegativeBaseDirection.WORSENING
