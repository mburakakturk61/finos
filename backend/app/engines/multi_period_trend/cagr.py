"""Deterministic Decimal CAGR calculation for Milestone 4.6E."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .canonical import normalize_decimal
from .contracts import TrendCagrResult, TrendMetricResult, TrendWarning
from .policy import TREND_ACCOUNTING_POLICY_V1, TrendAccountingPolicy
from .registry import TrendMetricDefinition
from .types import (
    TrendCagrEligibility,
    TrendCagrStatus,
    TrendEvidenceLevel,
    TrendPeriodFamily,
    TrendSegmentBoundaryKind,
    TrendWarningCode,
    weakest_evidence,
)


def decimal_nth_root(value: Decimal, degree: int) -> Decimal | None:
    """Return the v1 Newton root or None after the bounded convergence budget."""

    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise ValueError("root value must be a positive finite Decimal")
    if type(degree) is not int or degree <= 0:
        raise ValueError("root degree must be positive integer")
    if degree == 1:
        return normalize_decimal(value)
    convergence_scale = Decimal("0.000000000001")
    with localcontext() as context:
        context.prec = TREND_ACCOUNTING_POLICY_V1.numeric.decimal_precision
        current = Decimal(1)
        previous_quantized = current.quantize(convergence_scale, rounding=ROUND_HALF_EVEN)
        for _ in range(128):
            next_value = (
                (Decimal(degree - 1) * current) + value / (current ** (degree - 1))
            ) / Decimal(degree)
            next_quantized = next_value.quantize(convergence_scale, rounding=ROUND_HALF_EVEN)
            if next_quantized == previous_quantized:
                return normalize_decimal(next_value)
            current = next_value
            previous_quantized = next_quantized
    return None


def calculate_cagr(
    metric: TrendMetricResult,
    definition: TrendMetricDefinition,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> TrendCagrResult:
    if type(metric) is not TrendMetricResult or type(definition) is not TrendMetricDefinition:
        raise TypeError("CAGR requires exact metric contracts")
    observations = metric.series.observations
    warning = (TrendWarning(TrendWarningCode.CAGR_NOT_ELIGIBLE),)
    if not definition.cagr_enabled:
        return TrendCagrResult(None, TrendCagrStatus.DISABLED, TrendEvidenceLevel.UNAVAILABLE, warning)
    if metric.series.period_family is not TrendPeriodFamily.ANNUAL:
        return TrendCagrResult(None, TrendCagrStatus.NON_ANNUAL, TrendEvidenceLevel.UNAVAILABLE, warning)
    if metric.series.gaps:
        return TrendCagrResult(None, TrendCagrStatus.GAP_PRESENT, TrendEvidenceLevel.UNAVAILABLE, warning)
    if any(item.kind is TrendSegmentBoundaryKind.RESTATEMENT_CHANGE for item in metric.series.segment_boundaries):
        return TrendCagrResult(None, TrendCagrStatus.RESTATEMENT_BOUNDARY, TrendEvidenceLevel.UNAVAILABLE, warning)
    first = observations[0]
    last = observations[-1]
    if first.value is not None and last.value is not None and first.value * last.value < 0:
        return TrendCagrResult(None, TrendCagrStatus.SIGN_CHANGE, TrendEvidenceLevel.UNAVAILABLE, warning)
    eligibility = policy.percentage_sign.cagr_eligibility(
        period_family=metric.series.period_family,
        measurement_basis=metric.series.measurement_basis,
        gap_free=not metric.series.gaps and not metric.series.segment_boundaries,
        endpoint_count=len(observations),
        first_value=first.value,
        last_value=last.value,
    )
    status_by_eligibility = {
        TrendCagrEligibility.DISABLED_FOR_MEASUREMENT_BASIS: TrendCagrStatus.DISABLED,
        TrendCagrEligibility.NON_ANNUAL_SERIES: TrendCagrStatus.NON_ANNUAL,
        TrendCagrEligibility.GAP_PRESENT: TrendCagrStatus.GAP_PRESENT,
        TrendCagrEligibility.INSUFFICIENT_ENDPOINTS: TrendCagrStatus.INSUFFICIENT_DATA,
        TrendCagrEligibility.NON_POSITIVE_ENDPOINT: TrendCagrStatus.NON_POSITIVE_ENDPOINT,
        TrendCagrEligibility.MISSING_ENDPOINT: TrendCagrStatus.INSUFFICIENT_DATA,
    }
    if eligibility is not TrendCagrEligibility.ELIGIBLE:
        return TrendCagrResult(
            None, status_by_eligibility[eligibility], TrendEvidenceLevel.UNAVAILABLE, warning
        )
    year_interval = last.period_end_date.year - first.period_end_date.year
    if year_interval <= 0:
        return TrendCagrResult(None, TrendCagrStatus.INSUFFICIENT_DATA, TrendEvidenceLevel.UNAVAILABLE, warning)
    with localcontext() as context:
        context.prec = policy.numeric.decimal_precision
        root = decimal_nth_root(last.value / first.value, year_interval)  # type: ignore[operator]
        if root is None:
            return TrendCagrResult(
                None,
                TrendCagrStatus.NUMERIC_NON_CONVERGENCE,
                TrendEvidenceLevel.UNAVAILABLE,
                (TrendWarning(TrendWarningCode.CAGR_NUMERIC_NON_CONVERGENCE),),
            )
        value = ((root - Decimal(1)) * Decimal(100)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_EVEN
        )
    evidence = weakest_evidence(first.evidence, last.evidence, TrendEvidenceLevel.DERIVED)
    return TrendCagrResult(
        normalize_decimal(value), TrendCagrStatus.CALCULATED, evidence, (), year_interval
    )
