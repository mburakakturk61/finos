"""Deterministic final completeness accounting for Milestone 4.6F."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN

from .contracts import TrendMetricResult, TrendResultCompleteness
from .types import TrendAggregateAvailability, TrendCagrStatus, TrendEvidenceLevel


def build_result_completeness(
    metrics: tuple[TrendMetricResult, ...],
    *,
    expected_period_count: int,
    expected_metric_count: int,
    gap_count: int,
    restatement_boundary_count: int,
) -> TrendResultCompleteness:
    """Count only canonical result contracts; missing metrics remain unavailable."""

    expected_observations = expected_period_count * expected_metric_count
    available = sum(item.series.completeness.available_observation_count for item in metrics)
    if available > expected_observations:
        raise ValueError("available observations exceed expected result shape")
    evidence = {
        level: sum(
            getattr(item.series.evidence_summary, f"{level.value}_count")
            for item in metrics
        )
        for level in TrendEvidenceLevel
    }
    missing_metric_observations = max(expected_metric_count - len(metrics), 0) * expected_period_count
    evidence[TrendEvidenceLevel.UNAVAILABLE] += missing_metric_observations
    eligible_transitions = sum(item.transition_completeness.eligible_within_segment_count for item in metrics)
    calculated_transitions = sum(item.transition_completeness.valid_count for item in metrics)
    eligible_cagr = sum(
        item.cagr_result.status in {TrendCagrStatus.CALCULATED, TrendCagrStatus.NUMERIC_NON_CONVERGENCE}
        for item in metrics
    )
    calculated_cagr = sum(item.cagr_result.status is TrendCagrStatus.CALCULATED for item in metrics)
    eligible_volatility = sum(
        item.volatility_result.availability is TrendAggregateAvailability.CALCULATED
        for item in metrics
    )
    calculated_volatility = eligible_volatility
    eligible_break = sum(item.break_result.detected is not None for item in metrics)
    calculated_break = eligible_break
    ratio = (
        Decimal(0)
        if expected_observations == 0
        else (Decimal(available) / Decimal(expected_observations)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_EVEN
        )
    )
    return TrendResultCompleteness(
        expected_period_count=expected_period_count,
        resolved_period_count=expected_period_count if metrics else 0,
        expected_metric_observation_count=expected_observations,
        available_observation_count=available,
        unavailable_observation_count=expected_observations - available,
        exact_count=evidence[TrendEvidenceLevel.EXACT],
        derived_count=evidence[TrendEvidenceLevel.DERIVED],
        estimated_count=evidence[TrendEvidenceLevel.ESTIMATED],
        unavailable_count=evidence[TrendEvidenceLevel.UNAVAILABLE],
        eligible_transition_count=eligible_transitions,
        calculated_transition_count=calculated_transitions,
        eligible_cagr_count=eligible_cagr,
        calculated_cagr_count=calculated_cagr,
        eligible_volatility_count=eligible_volatility,
        calculated_volatility_count=calculated_volatility,
        eligible_break_count=eligible_break,
        calculated_break_count=calculated_break,
        gap_count=gap_count,
        restatement_boundary_count=restatement_boundary_count,
        available_ratio=ratio,
    )
