"""Deterministic coherent-split trend-break analysis for Milestone 4.6E."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .canonical import normalize_decimal
from .contracts import TrendBreakResult, TrendMetricResult, TrendWarning
from .policy import TREND_ACCOUNTING_POLICY_V1, TrendAccountingPolicy
from .registry import TrendMetricDefinition, TrendMetricUnit
from .types import TrendDirection, TrendEvidenceLevel, TrendOneOffStatus, TrendWarningCode, weakest_evidence


def _coherent(values: tuple[Decimal, ...], tolerance: Decimal) -> str | None:
    if all(item > tolerance for item in values):
        return "positive"
    if all(item < -tolerance for item in values):
        return "negative"
    if all(abs(item) <= tolerance for item in values):
        return "stable"
    return None


def select_break_candidate(
    normalized_transitions: tuple[Decimal, ...],
    *,
    coherence_tolerance: Decimal,
    score_threshold: Decimal,
) -> tuple[Decimal, int, Decimal, Decimal] | None:
    """Select highest score, then earliest right-segment ordinal on exact ties."""

    if (
        type(normalized_transitions) is not tuple
        or any(type(item) is not Decimal or not item.is_finite() for item in normalized_transitions)
        or type(coherence_tolerance) is not Decimal
        or type(score_threshold) is not Decimal
        or not coherence_tolerance.is_finite()
        or not score_threshold.is_finite()
        or coherence_tolerance < 0
        or score_threshold < 0
    ):
        raise ValueError("break candidate inputs are invalid")
    candidates = []
    for split in range(2, len(normalized_transitions) - 1):
        left = normalized_transitions[:split]
        right = normalized_transitions[split:]
        if _coherent(left, coherence_tolerance) is None or _coherent(right, coherence_tolerance) is None:
            continue
        left_mean = sum(left, Decimal(0)) / Decimal(len(left))
        right_mean = sum(right, Decimal(0)) / Decimal(len(right))
        score = abs(right_mean - left_mean)
        if score >= score_threshold:
            candidates.append((score, split, left_mean, right_mean))
    return sorted(candidates, key=lambda item: (-item[0], item[1]))[0] if candidates else None


def calculate_trend_break(
    metric: TrendMetricResult,
    definition: TrendMetricDefinition,
    *,
    eligible: bool | None = None,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> TrendBreakResult:
    if type(metric) is not TrendMetricResult or type(definition) is not TrendMetricDefinition:
        raise TypeError("break analysis requires exact metric contracts")
    enabled = definition.break_enabled if eligible is None else eligible
    if type(enabled) is not bool:
        raise TypeError("break eligibility must be bool")
    unknown_one_off = any(item.one_off_status is TrendOneOffStatus.UNKNOWN for item in metric.series.observations)
    one_off_warnings = (
        (TrendWarning(TrendWarningCode.ONE_OFF_STATUS_UNKNOWN),) if unknown_one_off else ()
    )
    unavailable_warnings = tuple(sorted(
        (*one_off_warnings, TrendWarning(TrendWarningCode.BREAK_NOT_ELIGIBLE)),
        key=lambda item: item.code.value,
    ))
    observations = metric.series.observations
    if (
        not enabled
        or len(observations) < policy.thresholds.break_minimum_observations
        or metric.series.gaps
        or metric.series.segment_boundaries
        or any(item.value is None for item in observations)
    ):
        return TrendBreakResult(
            None, None, TrendDirection.INSUFFICIENT_DATA, None,
            TrendEvidenceLevel.UNAVAILABLE, unavailable_warnings,
            coherence_tolerance=definition.normalized_direction_tolerance,
            score_threshold=definition.break_score_minimum,
        )
    scale_unit = (
        Decimal("0.01")
        if definition.unit in {TrendMetricUnit.TRY, TrendMetricUnit.DAYS}
        else Decimal("0.0001")
    )
    with localcontext() as context:
        context.prec = policy.numeric.decimal_precision
        normalized = tuple(
            (current.value - prior.value) / max(abs(prior.value), abs(current.value), scale_unit)  # type: ignore[operator,arg-type]
            for prior, current in zip(observations, observations[1:])
        )
        tolerance = definition.normalized_direction_tolerance
        candidate = select_break_candidate(
            normalized,
            coherence_tolerance=tolerance,
            score_threshold=definition.break_score_minimum,
        )
    evidence = weakest_evidence(
        *(item.evidence for item in observations), TrendEvidenceLevel.DERIVED
    )
    if candidate is None:
        return TrendBreakResult(
            False, None, TrendDirection.INSUFFICIENT_DATA, None, evidence, one_off_warnings,
            coherence_tolerance=definition.normalized_direction_tolerance,
            score_threshold=definition.break_score_minimum,
        )
    score, split, left_mean, right_mean = candidate
    prior_value = observations[split - 1].value
    breakpoint_value = observations[split].value
    sign_changed = (prior_value < 0 <= breakpoint_value) or (prior_value > 0 >= breakpoint_value)  # type: ignore[operator]
    direction = (
        TrendDirection.SIGN_CHANGE
        if sign_changed
        else TrendDirection.INCREASING
        if right_mean > left_mean
        else TrendDirection.DECREASING
    )
    score = normalize_decimal(score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))
    return TrendBreakResult(
        True, observations[split].period_id, direction, score, evidence, one_off_warnings,
        coherence_tolerance=definition.normalized_direction_tolerance,
        score_threshold=definition.break_score_minimum,
    )
