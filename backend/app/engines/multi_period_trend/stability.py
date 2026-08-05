"""Closed stability classification for Milestone 4.6E."""

from __future__ import annotations

from .contracts import TrendMetricResult, TrendStabilityResult, TrendWarning
from .types import (
    TrendAggregateAvailability,
    TrendDirection,
    TrendEvidenceLevel,
    TrendWarningCode,
)


def calculate_stability(
    metric: TrendMetricResult,
    *,
    eligible: bool,
    stable_tolerance=None,
) -> TrendStabilityResult:
    if type(metric) is not TrendMetricResult or type(eligible) is not bool:
        raise TypeError("stability requires exact metric contract and eligibility")
    unavailable = TrendStabilityResult(
        None,
        TrendAggregateAvailability.UNAVAILABLE,
        TrendEvidenceLevel.UNAVAILABLE,
        (TrendWarning(TrendWarningCode.MINIMUM_TREND_DATA_INCOMPLETE),),
    )
    if (
        not eligible
        or metric.series.gaps
        or metric.series.segment_boundaries
        or metric.transition_completeness is None
        or metric.transition_completeness.valid_count < 2
        or metric.series.completeness.available_observation_count < 3
        or metric.direction in {TrendDirection.SIGN_CHANGE, TrendDirection.INSUFFICIENT_DATA}
    ):
        return unavailable
    return TrendStabilityResult(
        metric.direction is TrendDirection.STABLE,
        TrendAggregateAvailability.CALCULATED,
        metric.direction_evidence,
        (),
        stable_tolerance,
    )
