from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    TrendAggregateAvailability,
    TrendCagrStatus,
    TrendDirection,
    TrendEvidenceLevel,
    TrendOneOffStatus,
    TrendRestatementProfile,
    TrendVolatilityCategory,
    TrendWarningCode,
    analyze_pairwise_series,
    analyze_trend_aggregates,
    calculate_cagr,
    calculate_stability,
    calculate_trend_break,
    calculate_volatility,
    decimal_nth_root,
    select_break_candidate,
)

from test_multi_period_trend_pairwise_unit import resolved_series


def _metric(values, **kwargs):
    return analyze_pairwise_series(resolved_series(tuple(Decimal(str(item)) if item is not None else None for item in values), **kwargs))


def test_cagr_valid_two_endpoint_and_multi_year_vectors():
    two = analyze_trend_aggregates(resolved_series((Decimal("100"), Decimal("121"))))
    multi = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("110"), Decimal("121")), years=(2020, 2021, 2022)
    ))
    assert two.cagr_result.status is TrendCagrStatus.CALCULATED
    assert two.cagr_result.value_percent == Decimal("21.0000")
    assert multi.cagr_result.value_percent == Decimal("10.0000")
    assert decimal_nth_root(Decimal("1.21"), 2).quantize(Decimal("0.0001")) == Decimal("1.1000")


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (("0", "10", "20"), TrendCagrStatus.NON_POSITIVE_ENDPOINT),
        (("-10", "10", "20"), TrendCagrStatus.SIGN_CHANGE),
        (("10", "20", "-30"), TrendCagrStatus.SIGN_CHANGE),
        ((None, "10", "20"), TrendCagrStatus.INSUFFICIENT_DATA),
        (("10", "20", None), TrendCagrStatus.INSUFFICIENT_DATA),
    ],
)
def test_cagr_fail_closed_endpoint_matrix(values, expected):
    result = analyze_trend_aggregates(resolved_series(tuple(
        Decimal(value) if value is not None else None for value in values
    )))
    assert result.cagr_result.status is expected
    assert result.cagr_result.value_percent is None
    assert result.cagr_result.evidence is TrendEvidenceLevel.UNAVAILABLE


def test_cagr_gap_restatement_ratio_and_estimated_evidence():
    gap = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("110"), Decimal("121")),
        segments=(0, 0, 1), years=(2020, 2021, 2023),
    ))
    restated = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("110"), Decimal("121")),
        segments=(0, 1, 1),
        restatements=(TrendRestatementProfile.ORIGINAL, TrendRestatementProfile.RESTATED, TrendRestatementProfile.RESTATED),
    ))
    ratio = analyze_trend_aggregates(resolved_series(
        (Decimal("1"), Decimal("2"), Decimal("3")), metric_code="ratio.current_ratio"
    ))
    estimated = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("110"), Decimal("121")),
        evidence=(TrendEvidenceLevel.EXACT, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.ESTIMATED),
    ))
    assert gap.cagr_result.status is TrendCagrStatus.GAP_PRESENT
    assert restated.cagr_result.status is TrendCagrStatus.RESTATEMENT_BOUNDARY
    assert ratio.cagr_result.status is TrendCagrStatus.DISABLED
    assert estimated.cagr_result.evidence is TrendEvidenceLevel.ESTIMATED


def test_registry_cagr_disable_is_typed_unavailable():
    metric = _metric((100, 110, 121))
    definition = TREND_METRIC_REGISTRY_V1.get(metric.metric_code)
    disabled = replace(definition, cagr_enabled=False)
    result = calculate_cagr(metric, disabled)
    assert result.status is TrendCagrStatus.DISABLED
    assert result.value_percent is None


@pytest.mark.parametrize(
    ("values", "stable"),
    [
        (("100", "100.01", "100.02"), True),
        (("100", "100.011", "100.022"), False),
        (("100", "110", "120"), False),
    ],
)
def test_stability_exact_tolerance_and_unstable(values, stable):
    result = analyze_trend_aggregates(resolved_series(tuple(Decimal(item) for item in values)))
    assert result.stability_result.availability is TrendAggregateAvailability.CALCULATED
    assert result.stability_result.stable is stable


def test_stability_sign_change_insufficient_gap_and_registry_ineligible():
    sign = analyze_trend_aggregates(resolved_series((Decimal("1"), Decimal("-1"), Decimal("2"))))
    insufficient = analyze_trend_aggregates(resolved_series((Decimal("1"), Decimal("2"))))
    gap_metric = _metric((1, 2, 3, 4), segments=(0, 0, 1, 1), years=(2020, 2021, 2023, 2024))
    disabled = calculate_stability(_metric((1, 2, 3)), eligible=False)
    assert sign.stability_result.stable is None
    assert insufficient.stability_result.stable is None
    assert calculate_stability(gap_metric, eligible=True).stable is None
    assert disabled.availability is TrendAggregateAvailability.UNAVAILABLE


def test_metric_specific_stability_tolerance_has_no_global_fallback():
    money = analyze_trend_aggregates(resolved_series((Decimal("1"), Decimal("1.005"), Decimal("1.010"))))
    ratio = analyze_trend_aggregates(resolved_series(
        (Decimal("1"), Decimal("1.005"), Decimal("1.010")), metric_code="ratio.current_ratio"
    ))
    assert money.stability_result.stable is True
    assert ratio.stability_result.stable is False


@pytest.mark.parametrize(
    ("values", "category"),
    [
        (("100", "100", "100", "100"), TrendVolatilityCategory.LOW),
        (("100", "101", "1000", "1001"), TrendVolatilityCategory.HIGH),
        (("-100", "-90", "-80", "-70"), TrendVolatilityCategory.LOW),
        (("0", "0", "0", "0"), TrendVolatilityCategory.LOW),
        (("100", "-100", "100", "-100"), TrendVolatilityCategory.LOW),
    ],
)
def test_volatility_decimal_negative_zero_and_sign_change_vectors(values, category):
    result = analyze_trend_aggregates(resolved_series(tuple(Decimal(item) for item in values)))
    assert result.volatility_result.category is category
    assert result.volatility_result.value is not None


def test_volatility_threshold_equality_and_medium_boundary():
    metric = _metric((100, 150, 130, 200))
    definition = TREND_METRIC_REGISTRY_V1.get(metric.metric_code)
    baseline = calculate_volatility(metric, definition)
    at_low = calculate_volatility(metric, replace(
        definition,
        volatility_low_maximum=baseline.value,
        volatility_medium_maximum=baseline.value + Decimal("0.1"),
    ))
    at_medium = calculate_volatility(metric, replace(
        definition,
        volatility_low_maximum=max(Decimal("0"), baseline.value - Decimal("0.0001")),
        volatility_medium_maximum=baseline.value,
    ))
    assert at_low.category is TrendVolatilityCategory.LOW
    assert at_medium.category is TrendVolatilityCategory.MEDIUM


def test_volatility_insufficient_missing_gap_and_registry_ineligible():
    definition = TREND_METRIC_REGISTRY_V1.get("bs.total_assets")
    insufficient = calculate_volatility(_metric((1, 2, 3)), definition)
    missing = calculate_volatility(_metric((1, 2, None, 4)), definition)
    gap = calculate_volatility(
        _metric((1, 2, 3, 4), segments=(0, 0, 1, 1), years=(2020, 2021, 2023, 2024)), definition
    )
    disabled = calculate_volatility(_metric((1, 2, 3, 4)), definition, eligible=False)
    assert {item.category for item in (insufficient, missing, gap, disabled)} == {TrendVolatilityCategory.UNAVAILABLE}


@pytest.mark.parametrize(
    ("values", "detected", "direction"),
    [
        (("100", "110", "121", "133.1", "146.41"), False, TrendDirection.INSUFFICIENT_DATA),
        (("100", "120", "144", "100", "60"), True, TrendDirection.DECREASING),
        (("100", "80", "60", "80", "120"), True, TrendDirection.INCREASING),
        (("100", "100", "100", "120", "150"), True, TrendDirection.INCREASING),
    ],
)
def test_trend_break_core_vectors(values, detected, direction):
    result = analyze_trend_aggregates(resolved_series(tuple(Decimal(item) for item in values)))
    assert result.break_result.detected is detected
    assert result.break_result.direction is direction
    assert not hasattr(result, "forecast")


def test_trend_break_minimum_gap_restatement_and_disabled():
    definition = TREND_METRIC_REGISTRY_V1.get("bs.total_assets")
    insufficient = calculate_trend_break(_metric((1, 2, 3, 4)), definition)
    gap = calculate_trend_break(
        _metric((1, 2, 3, 4, 5), segments=(0, 0, 1, 1, 1), years=(2020, 2021, 2023, 2024, 2025)), definition
    )
    restated = calculate_trend_break(_metric(
        (1, 2, 3, 4, 5), segments=(0, 1, 1, 1, 1),
        restatements=(TrendRestatementProfile.ORIGINAL, TrendRestatementProfile.RESTATED, TrendRestatementProfile.RESTATED, TrendRestatementProfile.RESTATED, TrendRestatementProfile.RESTATED),
    ), definition)
    disabled = calculate_trend_break(_metric((1, 2, 3, 4, 5)), definition, eligible=False)
    assert all(item.detected is None for item in (insufficient, gap, restated, disabled))


def test_break_exact_threshold_and_earliest_tie_break_are_deterministic():
    metric = _metric((100, 100, 100, 200, 400))
    definition = TREND_METRIC_REGISTRY_V1.get(metric.metric_code)
    exact = calculate_trend_break(metric, replace(definition, break_score_minimum=Decimal("0.5")))
    assert exact.detected is True
    assert exact.score == Decimal("0.5000")
    six = _metric((100, 100, 100, 200, 400, 800))
    first = calculate_trend_break(six, replace(definition, break_score_minimum=Decimal("0.1")))
    second = calculate_trend_break(six, replace(definition, break_score_minimum=Decimal("0.1")))
    assert first.canonical_digest == second.canonical_digest
    assert first.breakpoint_period_id == second.breakpoint_period_id

    tied = select_break_candidate(
        (Decimal("0.1"), Decimal("0.1"), Decimal("0.2"), Decimal("0.3"), Decimal("0.3")),
        coherence_tolerance=Decimal("0.0001"),
        score_threshold=Decimal("0.1"),
    )
    assert tied is not None
    assert tied[0] == Decimal("0.1666666666666666666666666667")
    assert tied[1] == 2


def test_one_off_unknown_is_disclosed_and_not_removed():
    result = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("120"), Decimal("144"), Decimal("100"), Decimal("60")),
        one_offs=tuple(TrendOneOffStatus.UNKNOWN for _ in range(5)),
    ))
    assert result.break_result.detected is True
    assert TrendWarningCode.ONE_OFF_STATUS_UNKNOWN in {item.code for item in result.break_result.warnings}
    assert len(result.series.observations) == 5


def test_aggregate_evidence_never_upgrades():
    result = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133.1"), Decimal("146.41")),
        evidence=(TrendEvidenceLevel.EXACT, TrendEvidenceLevel.DERIVED, TrendEvidenceLevel.ESTIMATED, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.EXACT),
    ))
    assert result.cagr_result.evidence is TrendEvidenceLevel.DERIVED
    assert result.volatility_result.evidence is TrendEvidenceLevel.ESTIMATED
    assert result.break_result.evidence is TrendEvidenceLevel.ESTIMATED
    assert result.stability_result.evidence is TrendEvidenceLevel.ESTIMATED


def test_aggregate_safe_repr_references_and_no_raw_payload():
    result = analyze_trend_aggregates(resolved_series(
        (Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133.1"), Decimal("146.41"))
    ))
    assert repr(result.cagr_result) == "TrendCagrResult()"
    assert repr(result.volatility_result) == "TrendVolatilityResult()"
    assert result.cagr_result.canonical_reference.startswith("trend:v1:sha256:")
    assert result.canonical_reference.startswith("trend:v1:sha256:")
    assert not hasattr(result, "payload")
