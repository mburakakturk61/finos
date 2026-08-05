from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    TrendEvidenceLevel,
    analyze_pairwise_series,
    analyze_trend_aggregates,
    calculate_trend_break,
    calculate_volatility,
)

from test_multi_period_trend_pairwise_unit import resolved_series


def test_same_semantic_series_always_has_same_aggregate_digest():
    first = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133.1"), Decimal("146.41"))
    ))
    second = analyze_trend_aggregates(resolved_series(
        (Decimal("100.0"), Decimal("110.0"), Decimal("121.0"), Decimal("133.10"), Decimal("146.410"))
    ))
    assert first.canonical_digest == second.canonical_digest


def test_amount_evidence_and_breakpoint_changes_change_digest():
    baseline = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("120"), Decimal("144"), Decimal("100"), Decimal("60"))
    ))
    amount = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("120"), Decimal("144"), Decimal("90"), Decimal("50"))
    ))
    evidence = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("120"), Decimal("144"), Decimal("100"), Decimal("60")),
        evidence=(TrendEvidenceLevel.EXACT, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.ESTIMATED, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.EXACT),
    ))
    assert baseline.canonical_digest != amount.canonical_digest
    assert baseline.canonical_digest != evidence.canonical_digest


def test_volatility_threshold_change_changes_aggregate_semantics():
    metric = analyze_pairwise_series(resolved_series((Decimal("100"), Decimal("150"), Decimal("130"), Decimal("200"))))
    definition = TREND_METRIC_REGISTRY_V1.get(metric.metric_code)
    baseline = calculate_volatility(metric, definition)
    changed = calculate_volatility(metric, replace(
        definition,
        volatility_low_maximum=baseline.value,
        volatility_medium_maximum=baseline.value + Decimal("0.1"),
    ))
    assert baseline.canonical_digest != changed.canonical_digest


def test_break_threshold_and_candidate_change_digest():
    metric = analyze_pairwise_series(resolved_series(
        (Decimal("100"), Decimal("120"), Decimal("144"), Decimal("100"), Decimal("60"))
    ))
    definition = TREND_METRIC_REGISTRY_V1.get(metric.metric_code)
    detected = calculate_trend_break(metric, definition)
    unavailable = calculate_trend_break(metric, replace(definition, break_score_minimum=Decimal("10")))
    assert detected.canonical_digest != unavailable.canonical_digest


def test_4_6d_pairwise_and_direction_are_byte_equivalent_after_aggregate_analysis():
    resolved = resolved_series((Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133.1"), Decimal("146.41")))
    pairwise = analyze_pairwise_series(resolved)
    aggregate = analyze_trend_aggregates(resolved)
    assert pairwise.series.canonical_digest == aggregate.series.canonical_digest
    assert pairwise.direction == aggregate.direction
    assert pairwise.direction_evidence == aggregate.direction_evidence
