"""Evidence propagation and closed data-quality classification for 4.6F."""

from __future__ import annotations

from .contracts import TrendMetricQuality, TrendMetricResult
from .registry import TrendMetricDefinition
from .types import (
    TrendAggregateAvailability,
    TrendCagrStatus,
    TrendComputationStatus,
    TrendDataQualityFlag,
    TrendEvidenceLevel,
    TrendFinalMetricAvailability,
    TrendOneOffDisclosureStatus,
    TrendOneOffStatus,
    TrendRestatementDisclosureStatus,
    TrendRestatementProfile,
    TrendSegmentBoundaryKind,
    weakest_evidence,
)


def metric_effective_evidence(metric: TrendMetricResult) -> TrendEvidenceLevel:
    """Derived output can never be stronger than its weakest contributing input."""

    available = tuple(
        observation.evidence
        for observation in metric.series.observations
        if observation.value is not None
    )
    if len(available) < 3:
        return TrendEvidenceLevel.UNAVAILABLE
    return weakest_evidence(*available, TrendEvidenceLevel.DERIVED)


def classify_metric_quality(
    metric: TrendMetricResult,
    definition: TrendMetricDefinition,
) -> TrendMetricQuality:
    available = metric.series.completeness.available_observation_count
    missing_periods = tuple(
        item.period_id for item in metric.series.observations if item.value is None
    )
    if metric.status is TrendComputationStatus.INVALID_INPUT:
        availability = TrendFinalMetricAvailability.INVALID
    elif metric.status is TrendComputationStatus.INTEGRITY_FAILURE:
        availability = TrendFinalMetricAvailability.INTEGRITY_FAILURE
    elif not definition.direction_enabled:
        availability = TrendFinalMetricAvailability.NOT_ELIGIBLE
    elif available == 0:
        availability = TrendFinalMetricAvailability.UNAVAILABLE_MISSING_INPUT
    elif available < 3:
        availability = TrendFinalMetricAvailability.INSUFFICIENT_OBSERVATIONS
    else:
        aggregate_incomplete = (
            metric.volatility_result.availability is not TrendAggregateAvailability.CALCULATED
            or metric.break_result.detected is None
            or (
                definition.cagr_enabled
                and metric.cagr_result.status not in {
                    TrendCagrStatus.CALCULATED,
                    TrendCagrStatus.NON_ANNUAL,
                    TrendCagrStatus.NON_POSITIVE_ENDPOINT,
                    TrendCagrStatus.SIGN_CHANGE,
                }
            )
        )
        availability = (
            TrendFinalMetricAvailability.PARTIAL
            if metric.status is TrendComputationStatus.PARTIAL or aggregate_incomplete
            else TrendFinalMetricAvailability.AVAILABLE
        )
    return TrendMetricQuality(
        metric_code=metric.metric_code,
        availability=availability,
        evidence=metric_effective_evidence(metric),
        usable_observation_count=available,
        segment_ordinals=tuple(sorted({item.segment_ordinal for item in metric.series.observations})),
        missing_period_ids=missing_periods,
        warning_codes=tuple(item.code for item in metric.warnings),
        error_codes=tuple(item.code for item in metric.errors),
    )


def restatement_disclosure(metrics: tuple[TrendMetricResult, ...]) -> TrendRestatementDisclosureStatus:
    profiles = {
        observation.restatement_profile
        for metric in metrics
        for observation in metric.series.observations
    }
    if TrendRestatementProfile.UNDECLARED_LEGACY in profiles:
        return TrendRestatementDisclosureStatus.UNKNOWN_PRESENT
    if profiles == {TrendRestatementProfile.RESTATED}:
        return TrendRestatementDisclosureStatus.RESTATED_DISCLOSED
    if TrendRestatementProfile.RESTATED in profiles:
        return TrendRestatementDisclosureStatus.MIXED_SEGMENTED
    return TrendRestatementDisclosureStatus.ORIGINAL_ONLY


def one_off_disclosure(metrics: tuple[TrendMetricResult, ...]) -> TrendOneOffDisclosureStatus:
    if any(
        observation.one_off_status is TrendOneOffStatus.UNKNOWN
        for metric in metrics
        for observation in metric.series.observations
    ):
        return TrendOneOffDisclosureStatus.UNKNOWN_PRESENT
    return TrendOneOffDisclosureStatus.INCLUDED_UNADJUSTED


def quality_flags(
    metrics: tuple[TrendMetricResult, ...],
    *,
    missing_metric_codes: tuple[str, ...],
) -> tuple[TrendDataQualityFlag, ...]:
    flags = {TrendDataQualityFlag.NOMINAL_ONLY}
    if any(metric.series.gaps for metric in metrics):
        flags.add(TrendDataQualityFlag.MISSING_PERIOD)
    if any(
        boundary.kind is TrendSegmentBoundaryKind.RESTATEMENT_CHANGE
        for metric in metrics
        for boundary in metric.series.segment_boundaries
    ):
        flags.add(TrendDataQualityFlag.RESTATEMENT_BOUNDARY)
    if any(
        observation.restatement_profile is TrendRestatementProfile.UNDECLARED_LEGACY
        for metric in metrics
        for observation in metric.series.observations
    ):
        flags.add(TrendDataQualityFlag.RESTATEMENT_UNKNOWN)
    if any(
        observation.one_off_status is TrendOneOffStatus.UNKNOWN
        for metric in metrics
        for observation in metric.series.observations
    ):
        flags.add(TrendDataQualityFlag.ONE_OFF_UNADJUSTED)
    if missing_metric_codes:
        flags.add(TrendDataQualityFlag.METRIC_MISSING)
    return tuple(item for item in TrendDataQualityFlag if item in flags)
