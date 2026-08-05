from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from itertools import permutations
from pathlib import Path
from uuid import UUID

import pytest

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1,
    TREND_METRIC_REGISTRY_V1,
    MultiPeriodTrendResult,
    TrendBreakResult,
    TrendComparabilityProfile,
    TrendComparabilityStatus,
    TrendCompleteness,
    TrendComputationStatus,
    TrendContractError,
    TrendContractVersion,
    TrendCoverageKind,
    TrendDataQuality,
    TrendDirection,
    TrendDuplicatePolicy,
    TrendEngineFailure,
    TrendError,
    TrendErrorCode,
    TrendEvidenceLevel,
    TrendEvidenceSummary,
    TrendGapPolicy,
    TrendLineageReference,
    TrendMeasurementBasis,
    TrendMetricAvailability,
    TrendMetricResult,
    TrendNegativeBaseDirection,
    TrendNominalAnalysisProfile,
    TrendNominalDisclosure,
    TrendObservation,
    TrendOneOffStatus,
    TrendOverlapPolicy,
    TrendPeriodFamily,
    TrendPolicyVersion,
    TrendRestatementProfile,
    TrendSeries,
    TrendSourceEngineType,
    TrendSourceReference,
    TrendTransition,
    TrendTransitionKind,
    TrendWarning,
    TrendWarningCode,
    canonical_trend_digest,
    canonical_trend_reference,
)


COMPANY = UUID("11111111-1111-4111-8111-111111111111")
TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PERIODS = tuple(UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(1, 8))
SOURCES = tuple(UUID(f"10000000-0000-4000-8000-{index:012d}") for index in range(1, 8))
DIGESTS = tuple(f"{index:x}" * 64 for index in range(1, 8))


ENUM_SNAPSHOTS = {
    TrendPeriodFamily: (
        ("ANNUAL", "annual"),
        ("MONTHLY_DISCRETE", "monthly_discrete"),
        ("QUARTERLY_DISCRETE", "quarterly_discrete"),
        ("QUARTERLY_CUMULATIVE_YOY", "quarterly_cumulative_yoy"),
        ("TEMPORARY_TAX_CUMULATIVE_YOY", "temporary_tax_cumulative_yoy"),
        ("CUSTOM_DISCRETE", "custom_discrete"),
    ),
    TrendMeasurementBasis: (
        ("STOCK_AS_OF", "stock_as_of"),
        ("DISCRETE_FLOW", "discrete_flow"),
        ("CUMULATIVE_FLOW", "cumulative_flow"),
        ("RATIO_RATE", "ratio_rate"),
    ),
    TrendEvidenceLevel: (
        ("EXACT", "exact"),
        ("DERIVED", "derived"),
        ("ESTIMATED", "estimated"),
        ("UNAVAILABLE", "unavailable"),
    ),
    TrendComputationStatus: (
        ("COMPLETE", "complete"),
        ("PARTIAL", "partial"),
        ("INSUFFICIENT_FOR_TREND", "insufficient_for_trend"),
        ("INSUFFICIENT_DATA", "insufficient_data"),
        ("INVALID_INPUT", "invalid_input"),
        ("INTEGRITY_FAILURE", "integrity_failure"),
    ),
    TrendDirection: (
        ("INCREASING", "increasing"),
        ("DECREASING", "decreasing"),
        ("STABLE", "stable"),
        ("MIXED", "mixed"),
        ("SIGN_CHANGE", "sign_change"),
        ("INSUFFICIENT_DATA", "insufficient_data"),
    ),
}


def _warning(code: TrendWarningCode = TrendWarningCode.NOMINAL_NOT_INFLATION_ADJUSTED) -> TrendWarning:
    return TrendWarning(code)


def _observation(
    ordinal: int,
    *,
    year: int | None = None,
    company: UUID = COMPANY,
    currency: str = "TRY",
    basis: TrendMeasurementBasis = TrendMeasurementBasis.STOCK_AS_OF,
    value: Decimal | None = Decimal("100.00"),
    evidence: TrendEvidenceLevel = TrendEvidenceLevel.EXACT,
    segment: int = 0,
    restatement: TrendRestatementProfile = TrendRestatementProfile.ORIGINAL,
    revision: int = 0,
    period_id: UUID | None = None,
    source_id: UUID | None = None,
    digest: str | None = None,
    start: date | None = None,
    end: date | None = None,
    one_off: TrendOneOffStatus = TrendOneOffStatus.UNKNOWN,
) -> TrendObservation:
    year = year or 2022 + ordinal
    return TrendObservation(
        ordinal=ordinal,
        segment_ordinal=segment,
        company_id=company,
        period_id=period_id or PERIODS[ordinal],
        period_start_date=start or date(year, 1, 1),
        period_end_date=end or date(year, 12, 31),
        period_family=TrendPeriodFamily.ANNUAL,
        coverage_kind=TrendCoverageKind.CUMULATIVE,
        measurement_basis=basis,
        value=value,
        currency=currency,
        monetary_unit_multiplier=Decimal("1"),
        scale=2,
        evidence=evidence,
        source_result_id=source_id or SOURCES[ordinal],
        source_engine_type=TrendSourceEngineType.BALANCE_SHEET,
        source_schema_version=None,
        source_model_version="1.0.0",
        canonical_source_digest=digest or DIGESTS[ordinal],
        restatement_profile=restatement,
        restatement_revision=revision,
        one_off_status=one_off,
        warnings=(),
    )


def _completeness(observations: tuple[TrendObservation, ...]) -> TrendCompleteness:
    available = sum(item.value is not None for item in observations)
    return TrendCompleteness(
        expected_observation_count=len(observations),
        available_observation_count=available,
        unavailable_observation_count=len(observations) - available,
        available_ratio=(Decimal(available) / Decimal(len(observations))).quantize(Decimal("0.0001")),
    )


def _evidence(observations: tuple[TrendObservation, ...]) -> TrendEvidenceSummary:
    counts = {level: sum(item.evidence is level for item in observations) for level in TrendEvidenceLevel}
    weakest = next(level for level in reversed(tuple(TrendEvidenceLevel)) if counts[level])
    return TrendEvidenceSummary(
        exact_count=counts[TrendEvidenceLevel.EXACT],
        derived_count=counts[TrendEvidenceLevel.DERIVED],
        estimated_count=counts[TrendEvidenceLevel.ESTIMATED],
        unavailable_count=counts[TrendEvidenceLevel.UNAVAILABLE],
        weakest_evidence=weakest,
    )


def _series(observations: tuple[TrendObservation, ...], transitions: tuple[TrendTransition, ...] = ()) -> TrendSeries:
    return TrendSeries(
        metric_code="bs.total_assets",
        company_id=COMPANY,
        anchor_period_id=max(observations, key=lambda item: item.period_end_date).period_id,
        period_family=TrendPeriodFamily.ANNUAL,
        measurement_basis=TrendMeasurementBasis.STOCK_AS_OF,
        observations=observations,
        transitions=transitions,
        currency="TRY",
        monetary_unit_multiplier=Decimal("1"),
        scale=2,
        policy_version=TrendPolicyVersion.V1,
        metric_registry_version_reference=TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1,
        completeness=_completeness(observations),
        evidence_summary=_evidence(observations),
        gaps=(),
        segment_boundaries=(),
        warnings=(),
        errors=(),
    )


def _break_none() -> TrendBreakResult:
    return TrendBreakResult(
        detected=None,
        breakpoint_period_id=None,
        direction=TrendDirection.INSUFFICIENT_DATA,
        score=None,
        evidence=TrendEvidenceLevel.UNAVAILABLE,
    )


def _profile() -> TrendComparabilityProfile:
    return TrendComparabilityProfile(
        tenant_id=TENANT,
        company_id=COMPANY,
        currency="TRY",
        accounting_basis="tr_tdhp_accrual",
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        fiscal_calendar_reference="calendar-year",
        period_family=TrendPeriodFamily.ANNUAL,
        coverage_kind=TrendCoverageKind.CUMULATIVE,
        source_schema_version=None,
        source_model_version="1.0.0",
        require_source_digest=True,
        restatement_profile=TrendRestatementProfile.ORIGINAL,
        nominal_analysis_profile=TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT,
        gap_policy=TrendGapPolicy.SEGMENT_WITHOUT_FILL,
        overlap_policy=TrendOverlapPolicy.REJECT,
        duplicate_policy=TrendDuplicatePolicy.REJECT,
    )


@pytest.mark.parametrize(("enum_type", "expected"), ENUM_SNAPSHOTS.items())
def test_exact_enum_snapshots_and_no_aliases(enum_type: type[Enum], expected: tuple[tuple[str, str], ...]) -> None:
    assert tuple((item.name, item.value) for item in enum_type) == expected
    assert len(enum_type.__members__) == len(tuple(enum_type))
    with pytest.raises(ValueError):
        enum_type("unknown")


def test_contracts_are_frozen_and_collections_require_tuple() -> None:
    observation = _observation(0)
    with pytest.raises(FrozenInstanceError):
        observation.value = Decimal("1")  # type: ignore[misc]
    with pytest.raises(TrendContractError):
        replace(observation, warnings=[_warning()])  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [1, 1.0, "1", Decimal("NaN"), Decimal("Infinity")])
def test_observation_enforces_decimal_only(value: object) -> None:
    with pytest.raises(TrendContractError):
        _observation(0, value=value)  # type: ignore[arg-type]


def test_missing_value_remains_none_and_requires_unavailable_evidence() -> None:
    observation = _observation(0, value=None, evidence=TrendEvidenceLevel.UNAVAILABLE)
    assert observation.value is None
    with pytest.raises(TrendContractError):
        _observation(0, value=None, evidence=TrendEvidenceLevel.EXACT)
    with pytest.raises(TrendContractError):
        _observation(0, value=Decimal("0"), evidence=TrendEvidenceLevel.UNAVAILABLE)


def test_negative_zero_is_normalized() -> None:
    observation = _observation(0, value=Decimal("-0.00"))
    assert observation.value == Decimal(0)
    assert not observation.value.is_signed()


@pytest.mark.parametrize(("field", "value"), [("scale", -1), ("scale", 9), ("monetary_unit_multiplier", Decimal("10"))])
def test_invalid_scale_and_multiplier_are_rejected(field: str, value: object) -> None:
    with pytest.raises(TrendContractError):
        replace(_observation(0), **{field: value})


def test_nonchronological_input_is_canonicalized_independently_of_tuple_order() -> None:
    observations = (_observation(0), _observation(1), _observation(2))
    digests = set()
    for order in permutations(observations):
        series = _series(order)
        assert tuple(item.ordinal for item in series.observations) == (0, 1, 2)
        digests.add(series.canonical_digest)
    assert len(digests) == 1


@pytest.mark.parametrize("attribute", ["period_id", "source_result_id", "canonical_source_digest"])
def test_duplicate_observation_identity_is_rejected(attribute: str) -> None:
    first = _observation(0)
    second = _observation(1)
    second = replace(second, **{attribute: getattr(first, attribute)})
    with pytest.raises(TrendContractError):
        _series((first, second))


def test_duplicate_ordinal_is_rejected() -> None:
    with pytest.raises(TrendContractError):
        _series((_observation(0), replace(_observation(1), ordinal=0)))


def test_period_overlap_is_rejected() -> None:
    first = _observation(0, start=date(2023, 1, 1), end=date(2023, 12, 31))
    second = _observation(1, start=date(2023, 12, 1), end=date(2024, 12, 31))
    with pytest.raises(TrendContractError):
        _series((first, second))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", UUID("22222222-2222-4222-8222-222222222222")),
        ("currency", "USD"),
        ("measurement_basis", TrendMeasurementBasis.DISCRETE_FLOW),
    ],
)
def test_mixed_scope_currency_or_basis_is_rejected(field: str, value: object) -> None:
    with pytest.raises(TrendContractError):
        _series((_observation(0), replace(_observation(1), **{field: value})))


def test_gap_is_disclosed_and_not_filled_with_zero() -> None:
    first = _observation(0, year=2022)
    second = _observation(1, year=2024, segment=1)
    series = _series((second, first))
    assert len(series.observations) == 2
    assert len(series.gaps) == 1
    assert series.gaps[0].first_missing_date == date(2023, 1, 1)
    assert len(series.segment_boundaries) == 1
    with pytest.raises(TrendContractError):
        _series((first, replace(second, segment_ordinal=0)))


def test_restatement_change_requires_explicit_new_segment() -> None:
    original = _observation(0)
    restated = _observation(1, restatement=TrendRestatementProfile.RESTATED, revision=1, segment=1)
    series = _series((original, restated))
    assert series.segment_boundaries[0].kind.value == "restatement_change"
    with pytest.raises(TrendContractError):
        _series((original, replace(restated, segment_ordinal=0)))


def test_one_off_absence_is_unknown_not_none() -> None:
    assert _observation(0).one_off_status is TrendOneOffStatus.UNKNOWN
    with pytest.raises(TrendContractError):
        replace(_observation(0), one_off_status=None)  # type: ignore[arg-type]


def test_transition_evidence_cannot_be_upgraded() -> None:
    observations = (
        _observation(0, evidence=TrendEvidenceLevel.DERIVED),
        _observation(1, evidence=TrendEvidenceLevel.EXACT),
    )
    projection = (
        "bs.total_assets", PERIODS[0], PERIODS[1], Decimal("100"), Decimal("101"),
        Decimal("1"), None, TrendTransitionKind.ABSOLUTE_ONLY_RATIO_RATE,
        TrendDirection.INCREASING, TrendNegativeBaseDirection.NOT_APPLICABLE,
        TrendEvidenceLevel.EXACT, Decimal("0.01"), TREND_METRIC_REGISTRY_V1.digest,
        TrendPolicyVersion.V1, ("a" * 64, "b" * 64), (DIGESTS[0], DIGESTS[1]), (), (),
    )
    with pytest.raises(TrendContractError):
        TrendTransition(
            metric_code="bs.total_assets", from_period_id=PERIODS[0], to_period_id=PERIODS[1],
            from_value=Decimal("100"), to_value=Decimal("101"), absolute_change=Decimal("1"),
            percentage_change=None, transition_kind=TrendTransitionKind.ABSOLUTE_ONLY_RATIO_RATE,
            direction=TrendDirection.INCREASING,
            negative_base_direction=TrendNegativeBaseDirection.NOT_APPLICABLE,
            evidence=TrendEvidenceLevel.EXACT, stable_tolerance=Decimal("0.01"),
            registry_digest=TREND_METRIC_REGISTRY_V1.digest, policy_version=TrendPolicyVersion.V1,
            observation_reference_digests=("a" * 64, "b" * 64),
            source_reference_digests=(DIGESTS[0], DIGESTS[1]),
            transition_digest=canonical_trend_digest(projection),
            transition_reference=canonical_trend_reference(projection),
        )
    weakened_projection = projection[:10] + (TrendEvidenceLevel.ESTIMATED,) + projection[11:]
    weakened = TrendTransition(
        metric_code="bs.total_assets", from_period_id=PERIODS[0], to_period_id=PERIODS[1],
        from_value=Decimal("100"), to_value=Decimal("101"), absolute_change=Decimal("1"),
        percentage_change=None, transition_kind=TrendTransitionKind.ABSOLUTE_ONLY_RATIO_RATE,
        direction=TrendDirection.INCREASING,
        negative_base_direction=TrendNegativeBaseDirection.NOT_APPLICABLE,
        evidence=TrendEvidenceLevel.ESTIMATED, stable_tolerance=Decimal("0.01"),
        registry_digest=TREND_METRIC_REGISTRY_V1.digest, policy_version=TrendPolicyVersion.V1,
        observation_reference_digests=("a" * 64, "b" * 64),
        source_reference_digests=(DIGESTS[0], DIGESTS[1]),
        transition_digest=canonical_trend_digest(weakened_projection),
        transition_reference=canonical_trend_reference(weakened_projection),
    )
    assert _series(observations, (weakened,)).transitions[0].evidence is TrendEvidenceLevel.ESTIMATED


def test_two_observations_cannot_claim_complete_trend() -> None:
    series = _series((_observation(0), _observation(1)))
    with pytest.raises(TrendContractError):
        TrendMetricResult(
            metric_code=series.metric_code,
            status=TrendComputationStatus.COMPLETE,
            availability=TrendMetricAvailability.AVAILABLE,
            series=series,
            direction=TrendDirection.INCREASING,
            break_result=_break_none(),
        )
    result = TrendMetricResult(
        metric_code=series.metric_code,
        status=TrendComputationStatus.INSUFFICIENT_FOR_TREND,
        availability=TrendMetricAvailability.AVAILABLE,
        series=series,
        direction=TrendDirection.INSUFFICIENT_DATA,
        break_result=_break_none(),
    )
    assert result.status is TrendComputationStatus.INSUFFICIENT_FOR_TREND


def test_complete_partial_and_insufficient_status_matrix() -> None:
    complete_series = _series((_observation(0), _observation(1), _observation(2)))
    complete = TrendMetricResult(
        complete_series.metric_code,
        TrendComputationStatus.COMPLETE,
        TrendMetricAvailability.AVAILABLE,
        complete_series,
        TrendDirection.INCREASING,
        _break_none(),
        direction_evidence=TrendEvidenceLevel.DERIVED,
    )
    assert complete.status is TrendComputationStatus.COMPLETE

    partial_observations = (
        _observation(0),
        _observation(1),
        _observation(2),
        _observation(3, value=None, evidence=TrendEvidenceLevel.UNAVAILABLE),
    )
    partial_series = _series(partial_observations)
    partial = TrendMetricResult(
        partial_series.metric_code,
        TrendComputationStatus.PARTIAL,
        TrendMetricAvailability.PARTIAL,
        partial_series,
        TrendDirection.INCREASING,
        _break_none(),
        direction_evidence=TrendEvidenceLevel.ESTIMATED,
    )
    assert partial.status is TrendComputationStatus.PARTIAL

    insufficient_series = _series((_observation(0), _observation(1, value=None, evidence=TrendEvidenceLevel.UNAVAILABLE)))
    insufficient = TrendMetricResult(
        insufficient_series.metric_code,
        TrendComputationStatus.INSUFFICIENT_DATA,
        TrendMetricAvailability.PARTIAL,
        insufficient_series,
        TrendDirection.INSUFFICIENT_DATA,
        _break_none(),
    )
    assert insufficient.status is TrendComputationStatus.INSUFFICIENT_DATA


def test_result_requires_nominal_disclosure_and_canonicalizes_series_order() -> None:
    observations = (_observation(0), _observation(1), _observation(2))
    series = _series(observations)
    metric = TrendMetricResult(
        series.metric_code,
        TrendComputationStatus.COMPLETE,
        TrendMetricAvailability.AVAILABLE,
        series,
        TrendDirection.INCREASING,
        _break_none(),
        direction_evidence=TrendEvidenceLevel.DERIVED,
    )
    sources = tuple(
        TrendSourceReference(
            company_id=COMPANY,
            period_id=PERIODS[index],
            source_result_id=SOURCES[index],
            source_engine_type=TrendSourceEngineType.BALANCE_SHEET,
            source_schema_version=None,
            source_model_version="1.0.0",
            canonical_source_digest=DIGESTS[index],
            evidence=TrendEvidenceLevel.EXACT,
        )
        for index in range(3)
    )
    lineage = tuple(
        TrendLineageReference(index, PERIODS[index], SOURCES[index], DIGESTS[index], "f" * 64, "1.0.0")
        for index in range(3)
    )
    quality = TrendDataQuality(
        comparability_status=TrendComparabilityStatus.COMPARABLE,
        profile=_profile(),
        completeness=_completeness(observations),
        evidence_summary=_evidence(observations),
        gap_count=0,
        restatement_boundary_count=0,
        one_off_unknown_count=3,
    )
    result = MultiPeriodTrendResult(
        company_id=COMPANY,
        anchor_period_id=PERIODS[2],
        status=TrendComputationStatus.COMPLETE,
        nominal_analysis_disclosure=TrendNominalDisclosure(
            TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT,
            "TRY",
            True,
            False,
        ),
        series=(metric,),
        data_quality=quality,
        source_references=sources,
        lineage_references=lineage,
        policy_version=TrendPolicyVersion.V1,
        contract_version=TrendContractVersion.V1,
    )
    assert result.canonical_reference.startswith("trend:v1:sha256:")
    with pytest.raises(TrendContractError):
        replace(result.nominal_analysis_disclosure, inflation_adjusted=True)


def test_safe_repr_never_exposes_ids_digests_or_amounts() -> None:
    observation = _observation(0)
    rendered = repr(observation)
    assert str(COMPANY) not in rendered
    assert DIGESTS[0] not in rendered
    assert "100" not in rendered
    assert rendered == "TrendObservation()"


def test_failure_is_final_immutable_and_safe() -> None:
    failure = TrendEngineFailure(TrendErrorCode.SOURCE_DIGEST_MISMATCH)
    assert failure.args == ()
    assert DIGESTS[0] not in repr(failure)
    assert "source_digest_mismatch" in str(failure)
    with pytest.raises(AttributeError):
        failure._code = TrendErrorCode.INVALID_CONTRACT  # type: ignore[misc]
    with pytest.raises(TypeError):
        class BadFailure(TrendEngineFailure):
            pass
    with pytest.raises(TrendContractError):
        TrendEngineFailure("source_digest_mismatch")  # type: ignore[arg-type]


def test_package_has_no_forbidden_or_out_of_scope_imports() -> None:
    package = Path(__file__).parents[1] / "app" / "engines" / "multi_period_trend"
    forbidden_roots = {"sqlalchemy", "fastapi", "pydantic"}
    forbidden_app_prefixes = (
        "app.models",
        "app.analysis_application",
        "app.orchestration_persistence",
        "app.integrations",
    )
    for source_file in package.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
                    assert not alias.name.startswith(forbidden_app_prefixes)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots
                assert not node.module.startswith(forbidden_app_prefixes)


def test_4_6b_registry_addition_does_not_introduce_calculation_or_resolution() -> None:
    package = Path(__file__).parents[1] / "app" / "engines" / "multi_period_trend"
    assert (package / "registry.py").is_file()
    assert (package / "evidence_mapping.py").is_file()
    assert not (package / "calculation.py").exists()
    assert not (package / "resolver.py").exists()
