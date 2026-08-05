"""Deterministic normalized Decimal volatility for Milestone 4.6E."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .canonical import normalize_decimal
from .contracts import TrendMetricResult, TrendVolatilityResult, TrendWarning
from .policy import TREND_ACCOUNTING_POLICY_V1, TrendAccountingPolicy
from .registry import TrendMetricDefinition, TrendMetricUnit
from .types import (
    TrendAggregateAvailability,
    TrendEvidenceLevel,
    TrendVolatilityCategory,
    TrendWarningCode,
    weakest_evidence,
)


def decimal_square_root(value: Decimal) -> Decimal | None:
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise ValueError("square-root value must be non-negative finite Decimal")
    if value == 0:
        return Decimal(0)
    convergence_scale = Decimal("0.000000000001")
    with localcontext() as context:
        context.prec = TREND_ACCOUNTING_POLICY_V1.numeric.decimal_precision
        current = Decimal(1)
        previous_quantized = current.quantize(convergence_scale, rounding=ROUND_HALF_EVEN)
        for _ in range(128):
            next_value = (current + value / current) / Decimal(2)
            next_quantized = next_value.quantize(convergence_scale, rounding=ROUND_HALF_EVEN)
            if next_quantized == previous_quantized:
                return normalize_decimal(next_value)
            current = next_value
            previous_quantized = next_quantized
    return None


def calculate_volatility(
    metric: TrendMetricResult,
    definition: TrendMetricDefinition,
    *,
    eligible: bool | None = None,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> TrendVolatilityResult:
    if type(metric) is not TrendMetricResult or type(definition) is not TrendMetricDefinition:
        raise TypeError("volatility requires exact metric contracts")
    enabled = definition.volatility_enabled if eligible is None else eligible
    if type(enabled) is not bool:
        raise TypeError("volatility eligibility must be bool")
    unavailable = TrendVolatilityResult(
        None,
        TrendVolatilityCategory.UNAVAILABLE,
        TrendAggregateAvailability.UNAVAILABLE,
        TrendEvidenceLevel.UNAVAILABLE,
        (TrendWarning(TrendWarningCode.VOLATILITY_NOT_ELIGIBLE),),
    )
    observations = metric.series.observations
    if (
        not enabled
        or len(observations) < policy.thresholds.volatility_minimum_observations
        or metric.series.gaps
        or metric.series.segment_boundaries
        or any(item.value is None for item in observations)
    ):
        return unavailable
    scale_unit = (
        Decimal("0.01")
        if definition.unit in {TrendMetricUnit.TRY, TrendMetricUnit.DAYS}
        else Decimal("0.0001")
    )
    with localcontext() as context:
        context.prec = policy.numeric.decimal_precision
        normalized = []
        for prior, current in zip(observations, observations[1:]):
            denominator = max(abs(prior.value), abs(current.value), scale_unit)  # type: ignore[arg-type]
            normalized.append(abs(current.value - prior.value) / denominator)  # type: ignore[operator]
        mean = sum(normalized, Decimal(0)) / Decimal(len(normalized))
        variance = sum(((item - mean) ** 2 for item in normalized), Decimal(0)) / Decimal(len(normalized))
        root = decimal_square_root(variance)
        if root is None:
            return unavailable
        value = normalize_decimal(root.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))
    category = (
        TrendVolatilityCategory.LOW
        if value <= definition.volatility_low_maximum
        else TrendVolatilityCategory.MEDIUM
        if value <= definition.volatility_medium_maximum
        else TrendVolatilityCategory.HIGH
    )
    evidence = weakest_evidence(
        *(item.evidence for item in observations), TrendEvidenceLevel.DERIVED
    )
    return TrendVolatilityResult(
        value, category, TrendAggregateAvailability.CALCULATED, evidence, (),
        definition.volatility_low_maximum, definition.volatility_medium_maximum,
    )
