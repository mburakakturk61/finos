from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from itertools import permutations

from app.engines.multi_period_trend import (
    TrendComputationStatus,
    TrendEvidenceLevel,
    TrendOneOffStatus,
    assemble_multi_period_trend_result,
)

from test_multi_period_trend_pairwise_unit import resolved_series
from test_multi_period_trend_quality_unit import _profile


def _assemble(series, expected):
    return assemble_multi_period_trend_result(tuple(series), _profile(), expected_metric_codes=expected)


def test_input_order_does_not_change_semantic_result_or_digest():
    first = resolved_series((Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133"), Decimal("146")))
    second = resolved_series(
        (Decimal("10"), Decimal("11"), Decimal("12"), Decimal("13"), Decimal("14")),
        metric_code="bs.cash_and_equivalents",
    )
    expected = (first.metric_code, second.metric_code)
    results = tuple(_assemble(order, expected) for order in permutations((first, second)))
    assert len({item.canonical_digest for item in results}) == 1
    assert results[0] == results[1]


def test_same_semantic_input_always_has_same_digest():
    series = resolved_series((Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")))
    first = _assemble((series,), (series.metric_code,))
    second = _assemble((series,), (series.metric_code,))
    assert first.canonical_digest == second.canonical_digest
    assert first.canonical_reference == second.canonical_reference


def test_evidence_change_changes_final_digest_and_never_upgrades():
    values = (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5"))
    exact = resolved_series(values)
    estimated = resolved_series(
        values,
        evidence=(
            TrendEvidenceLevel.EXACT,
            TrendEvidenceLevel.EXACT,
            TrendEvidenceLevel.ESTIMATED,
            TrendEvidenceLevel.EXACT,
            TrendEvidenceLevel.EXACT,
        ),
    )
    exact_result = _assemble((exact,), (exact.metric_code,))
    estimated_result = _assemble((estimated,), (estimated.metric_code,))
    assert exact_result.canonical_digest != estimated_result.canonical_digest
    assert estimated_result.data_quality.metric_quality[0].evidence is TrendEvidenceLevel.ESTIMATED


def test_gap_segment_change_changes_digest_and_suppresses_bridge():
    values = (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5"))
    contiguous = resolved_series(values)
    segmented = resolved_series(values, segments=(0, 0, 1, 1, 1), years=(2020, 2021, 2023, 2024, 2025))
    left = _assemble((contiguous,), (contiguous.metric_code,))
    right = _assemble((segmented,), (segmented.metric_code,))
    assert left.canonical_digest != right.canonical_digest
    assert len(right.series[0].series.transitions) < len(left.series[0].series.transitions)


def test_warning_and_one_off_disclosure_change_digest():
    values = (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5"))
    known = resolved_series(values)
    unknown = resolved_series(values, one_offs=(TrendOneOffStatus.UNKNOWN,) * 5)
    known_result = _assemble((known,), (known.metric_code,))
    unknown_result = _assemble((unknown,), (unknown.metric_code,))
    assert known_result.canonical_digest != unknown_result.canonical_digest
    assert known_result.warnings != unknown_result.warnings


def test_metric_availability_and_status_change_are_digest_sensitive():
    complete = resolved_series((Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")))
    partial = resolved_series((Decimal("1"), Decimal("2"), Decimal("3")))
    complete_result = _assemble((complete,), (complete.metric_code,))
    partial_result = _assemble((partial,), (partial.metric_code,))
    assert complete_result.status is TrendComputationStatus.COMPLETE
    assert partial_result.status is TrendComputationStatus.PARTIAL
    assert complete_result.canonical_digest != partial_result.canonical_digest


def test_default_registry_shape_counts_all_45_metrics_without_fabrication():
    series = resolved_series((Decimal("1"), Decimal("2"), Decimal("3")))
    result = assemble_multi_period_trend_result((series,), _profile())
    completeness = result.data_quality.result_completeness
    assert completeness.expected_metric_observation_count == 3 * 45
    assert completeness.available_observation_count == 3
    assert completeness.unavailable_observation_count == 132
    assert len(result.data_quality.missing_metric_codes) == 44
    assert len(result.series) == 1
