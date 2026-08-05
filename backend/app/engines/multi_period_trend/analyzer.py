"""4.6D pairwise and direction result assembly; no 4.6E aggregates."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_EVEN

from .contracts import (
    TrendBreakResult,
    TrendCompleteness,
    TrendEvidenceSummary,
    TrendMetricResult,
    TrendSeries,
    TrendWarning,
)
from .direction import aggregate_direction
from .break_analysis import calculate_trend_break
from .cagr import calculate_cagr
from .pairwise import TrendPairwiseCalculationError, generate_pairwise_transitions
from .policy import TREND_ACCOUNTING_POLICY_V1, TrendAccountingPolicy
from .registry import TREND_METRIC_REGISTRY_V1, TrendMetricRegistry
from .resolution_contracts import ResolvedTrendSeries
from .stability import calculate_stability
from .volatility import calculate_volatility
from .types import (
    TrendComputationStatus,
    TrendDirection,
    TrendErrorCode,
    TrendEvidenceLevel,
    TrendMetricAvailability,
    TrendPolicyVersion,
    TrendSegmentBoundaryKind,
    TrendWarningCode,
    weakest_evidence,
)


def _evidence_summary(series: ResolvedTrendSeries) -> TrendEvidenceSummary:
    counts = {
        level: sum(item.observation.evidence is level for item in series.observations)
        for level in TrendEvidenceLevel
    }
    populated = tuple(level for level in TrendEvidenceLevel if counts[level])
    return TrendEvidenceSummary(
        exact_count=counts[TrendEvidenceLevel.EXACT],
        derived_count=counts[TrendEvidenceLevel.DERIVED],
        estimated_count=counts[TrendEvidenceLevel.ESTIMATED],
        unavailable_count=counts[TrendEvidenceLevel.UNAVAILABLE],
        weakest_evidence=weakest_evidence(*populated),
    )


def _canonical_warnings(series: ResolvedTrendSeries, transitions) -> tuple[TrendWarning, ...]:
    warnings = {
        (warning.code, warning.safe_reference): warning
        for item in series.observations
        for warning in item.observation.warnings
    }
    for transition in transitions:
        for warning in transition.warnings:
            warnings[(warning.code, warning.safe_reference)] = warning
    if series.gaps:
        warning = TrendWarning(TrendWarningCode.PERIOD_GAP_SEGMENTED)
        warnings[(warning.code, warning.safe_reference)] = warning
    if any(item.kind is TrendSegmentBoundaryKind.RESTATEMENT_CHANGE for item in series.segment_boundaries):
        warning = TrendWarning(TrendWarningCode.RESTATEMENT_BOUNDARY_SEGMENTED)
        warnings[(warning.code, warning.safe_reference)] = warning
    available = sum(item.observation.value is not None for item in series.observations)
    if available < 3:
        warning = TrendWarning(TrendWarningCode.MINIMUM_TREND_DATA_INCOMPLETE)
        warnings[(warning.code, warning.safe_reference)] = warning
    return tuple(sorted(warnings.values(), key=lambda item: (item.code.value, item.safe_reference or "")))


def analyze_pairwise_series(
    resolved: ResolvedTrendSeries,
    registry: TrendMetricRegistry = TREND_METRIC_REGISTRY_V1,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> TrendMetricResult:
    """Assemble the 4.6D slice of a metric result from one resolved series."""

    if type(resolved) is not ResolvedTrendSeries:
        raise TrendPairwiseCalculationError(TrendErrorCode.INVALID_CONTRACT)
    if type(registry) is not TrendMetricRegistry or type(policy) is not TrendAccountingPolicy:
        raise TrendPairwiseCalculationError(TrendErrorCode.INVALID_CONTRACT)
    try:
        definition = registry.get(resolved.metric_code)
    except ValueError:
        raise TrendPairwiseCalculationError(TrendErrorCode.REGISTRY_INTEGRITY_FAILURE) from None
    observations = tuple(item.observation for item in resolved.observations)
    transitions = generate_pairwise_transitions(resolved, registry, policy)
    available = sum(item.value is not None for item in observations)
    completeness = TrendCompleteness(
        expected_observation_count=len(observations),
        available_observation_count=available,
        unavailable_observation_count=len(observations) - available,
        available_ratio=(Decimal(available) / Decimal(len(observations))).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_EVEN
        ),
    )
    evidence_summary = _evidence_summary(resolved)
    warnings = _canonical_warnings(resolved, transitions)
    series = TrendSeries(
        metric_code=resolved.metric_code,
        company_id=resolved.company_id,
        anchor_period_id=resolved.anchor_period_id,
        period_family=resolved.period_family,
        measurement_basis=definition.measurement_basis_for(resolved.period_family),
        observations=observations,
        transitions=transitions,
        currency=resolved.currency,
        monetary_unit_multiplier=resolved.monetary_unit_multiplier,
        scale=definition.scale,
        policy_version=TrendPolicyVersion.V1,
        metric_registry_version_reference=registry.registry_version,
        completeness=completeness,
        evidence_summary=evidence_summary,
        gaps=resolved.gaps,
        segment_boundaries=resolved.segment_boundaries,
        warnings=warnings,
        errors=(),
    )
    anchor_segment = observations[-1].segment_ordinal
    anchor_transitions = tuple(
        item for item in transitions
        if next(obs.segment_ordinal for obs in observations if obs.period_id == item.from_period_id) == anchor_segment
    )
    direction = aggregate_direction(anchor_transitions)
    direction_evidence = (
        weakest_evidence(*(item.evidence for item in anchor_transitions if item.absolute_change is not None))
        if direction is not TrendDirection.INSUFFICIENT_DATA
        else TrendEvidenceLevel.UNAVAILABLE
    )
    availability = (
        TrendMetricAvailability.UNAVAILABLE
        if available == 0
        else TrendMetricAvailability.AVAILABLE
        if available == len(observations)
        else TrendMetricAvailability.PARTIAL
    )
    degraded = bool(
        availability is not TrendMetricAvailability.AVAILABLE
        or resolved.gaps
        or resolved.segment_boundaries
        or evidence_summary.estimated_count
        or evidence_summary.unavailable_count
        or warnings
    )
    status = (
        TrendComputationStatus.INSUFFICIENT_DATA
        if available < 2
        else TrendComputationStatus.INSUFFICIENT_FOR_TREND
        if available == 2
        else TrendComputationStatus.PARTIAL
        if degraded
        else TrendComputationStatus.COMPLETE
    )
    if status in {TrendComputationStatus.INSUFFICIENT_DATA, TrendComputationStatus.INSUFFICIENT_FOR_TREND}:
        direction = TrendDirection.INSUFFICIENT_DATA
        direction_evidence = TrendEvidenceLevel.UNAVAILABLE
    # 4.6E fields remain explicitly unevaluated through the existing break contract;
    # CAGR, volatility, stability score, break detection and forecasting are not computed here.
    break_result = TrendBreakResult(
        detected=None,
        breakpoint_period_id=None,
        direction=TrendDirection.INSUFFICIENT_DATA,
        score=None,
        evidence=TrendEvidenceLevel.UNAVAILABLE,
    )
    return TrendMetricResult(
        metric_code=resolved.metric_code,
        status=status,
        availability=availability,
        series=series,
        direction=direction,
        break_result=break_result,
        direction_evidence=direction_evidence,
        warnings=warnings,
        errors=(),
    )


def analyze_trend_aggregates(
    resolved: ResolvedTrendSeries,
    registry: TrendMetricRegistry = TREND_METRIC_REGISTRY_V1,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> TrendMetricResult:
    """Fill only the 4.6E aggregate slice; final quality assembly remains 4.6F."""

    pairwise_result = analyze_pairwise_series(resolved, registry, policy)
    definition = registry.get(resolved.metric_code)
    cagr_result = calculate_cagr(pairwise_result, definition, policy)
    stability_result = calculate_stability(
        pairwise_result,
        eligible=definition.direction_enabled,
        stable_tolerance=definition.direction_tolerance,
    )
    volatility_result = calculate_volatility(
        pairwise_result, definition, policy=policy
    )
    break_result = calculate_trend_break(pairwise_result, definition, policy=policy)
    warnings = {
        (item.code, item.safe_reference): item
        for item in (
            *pairwise_result.warnings,
            *cagr_result.warnings,
            *stability_result.warnings,
            *volatility_result.warnings,
            *break_result.warnings,
        )
    }
    return replace(
        pairwise_result,
        cagr_result=cagr_result,
        stability_result=stability_result,
        volatility_result=volatility_result,
        break_result=break_result,
        warnings=tuple(sorted(warnings.values(), key=lambda item: (item.code.value, item.safe_reference or ""))),
    )
