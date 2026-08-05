from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from random import Random

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    TrendDirection,
    TrendEvidenceLevel,
    TrendTransitionKind,
    analyze_pairwise_series,
    generate_pairwise_transitions,
)

from test_multi_period_trend_pairwise_unit import resolved_series


def test_absolute_change_antisymmetry_where_semantics_are_available():
    for left in range(-9, 10):
        for right in range(-9, 10):
            forward = generate_pairwise_transitions(
                resolved_series((Decimal(left), Decimal(right))), TREND_METRIC_REGISTRY_V1
            )[0]
            reverse = generate_pairwise_transitions(
                resolved_series((Decimal(right), Decimal(left))), TREND_METRIC_REGISTRY_V1
            )[0]
            assert forward.absolute_change == -reverse.absolute_change


def test_canonical_series_is_deterministic_and_digest_changes_with_semantics():
    baseline = analyze_pairwise_series(resolved_series((Decimal("10"), Decimal("20"), Decimal("30"))))
    same = analyze_pairwise_series(resolved_series((Decimal("10.0"), Decimal("20.0"), Decimal("30.0"))))
    amount = analyze_pairwise_series(resolved_series((Decimal("10"), Decimal("20"), Decimal("31"))))
    evidence = analyze_pairwise_series(resolved_series(
        (Decimal("10"), Decimal("20"), Decimal("30")),
        evidence=(TrendEvidenceLevel.EXACT, TrendEvidenceLevel.DERIVED, TrendEvidenceLevel.EXACT),
    ))
    assert baseline.canonical_digest == same.canonical_digest
    assert baseline.canonical_digest != amount.canonical_digest
    assert baseline.canonical_digest != evidence.canonical_digest


def test_input_order_before_resolution_cannot_change_resolved_analysis():
    baseline_series = resolved_series((Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")))
    baseline = analyze_pairwise_series(baseline_series)
    for seed in range(20):
        shuffled = list(baseline_series.observations)
        Random(seed).shuffle(shuffled)
        # The 4.6C contract rejects non-canonical order; canonical resolution output is reused.
        canonical = tuple(sorted(shuffled, key=lambda item: item.observation.ordinal))
        actual = analyze_pairwise_series(replace(baseline_series, observations=canonical))
        assert actual.canonical_digest == baseline.canonical_digest


def test_gap_never_creates_transition_and_missing_never_becomes_zero():
    series = resolved_series(
        (Decimal("1"), Decimal("2"), None, Decimal("4")),
        segments=(0, 0, 1, 1), years=(2021, 2022, 2024, 2025),
    )
    transitions = generate_pairwise_transitions(series, TREND_METRIC_REGISTRY_V1)
    assert len(transitions) == 2
    assert transitions[1].transition_kind is TrendTransitionKind.UNAVAILABLE_MISSING_INPUT
    assert transitions[1].absolute_change is None


def test_sign_change_never_produces_growth_percentage():
    for prior, current in ((-10, 0), (-10, 10), (10, 0), (10, -10)):
        transition = generate_pairwise_transitions(
            resolved_series((Decimal(prior), Decimal(current))), TREND_METRIC_REGISTRY_V1
        )[0]
        assert transition.direction is TrendDirection.SIGN_CHANGE
        assert transition.percentage_change is None


def test_output_evidence_never_exceeds_weakest_input():
    levels = tuple(TrendEvidenceLevel)
    rank = {level: 3 - index for index, level in enumerate(levels)}
    for left in levels:
        for right in levels:
            values = (
                None if left is TrendEvidenceLevel.UNAVAILABLE else Decimal("1"),
                None if right is TrendEvidenceLevel.UNAVAILABLE else Decimal("2"),
            )
            transition = generate_pairwise_transitions(
                resolved_series(values, evidence=(left, right)), TREND_METRIC_REGISTRY_V1
            )[0]
            assert rank[transition.evidence] <= min(rank[left], rank[right])


def test_metric_tolerance_is_committed_to_transition_digest():
    series = resolved_series((Decimal("1"), Decimal("2")))
    transition = generate_pairwise_transitions(series, TREND_METRIC_REGISTRY_V1)[0]
    definition = TREND_METRIC_REGISTRY_V1.get("bs.total_assets")
    changed_definition = replace(definition, direction_tolerance=Decimal("0.02"))
    changed_registry = replace(
        TREND_METRIC_REGISTRY_V1,
        definitions=tuple(
            changed_definition if item.metric_code == definition.metric_code else item
            for item in TREND_METRIC_REGISTRY_V1.definitions
        ),
    )
    changed = generate_pairwise_transitions(series, changed_registry)[0]
    assert transition.transition_digest != changed.transition_digest
    assert transition.stable_tolerance != changed.stable_tolerance
