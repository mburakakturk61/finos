"""Pure adjacent pair calculation for Milestone 4.6D."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .canonical import canonical_trend_digest, canonical_trend_reference, normalize_decimal
from .contracts import TrendError, TrendObservation, TrendTransition, TrendWarning
from .direction import classify_pair_direction
from .policy import TREND_ACCOUNTING_POLICY_V1, TrendAccountingPolicy
from .registry import TrendMetricDefinition, TrendMetricRegistry
from .resolution_contracts import ResolvedTrendObservation, ResolvedTrendSeries
from .types import (
    TrendErrorCode,
    TrendEvidenceLevel,
    TrendNegativeBaseDirection,
    TrendPercentageDecision,
    TrendPolicyVersion,
    TrendTransitionKind,
    TrendWarningCode,
    weakest_evidence,
)


class TrendPairwiseCalculationError(ValueError):
    """Safe fail-closed error; raw input and upstream exception text are never retained."""

    __slots__ = ("code",)

    def __init__(self, code: TrendErrorCode) -> None:
        if type(code) is not TrendErrorCode:
            raise TypeError("pairwise error code must be exact enum")
        self.code = code
        super().__init__("trend pairwise calculation failed")

    def __repr__(self) -> str:
        return "TrendPairwiseCalculationError()"

    __str__ = __repr__


def _quantize(value: Decimal, scale: int) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or type(scale) is not int or scale < 0:
        raise TrendPairwiseCalculationError(TrendErrorCode.DECIMAL_NON_FINITE_OR_SCALE_INVALID)
    with localcontext() as context:
        context.prec = TREND_ACCOUNTING_POLICY_V1.numeric.decimal_precision
        result = value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)
    return normalize_decimal(result)


def _transition_projection(
    *,
    metric_code: str,
    prior: TrendObservation,
    current: TrendObservation,
    absolute_change: Decimal | None,
    percentage_change: Decimal | None,
    transition_kind: TrendTransitionKind,
    direction,
    negative_base_direction: TrendNegativeBaseDirection,
    evidence: TrendEvidenceLevel,
    stable_tolerance: Decimal,
    registry_digest: str,
    observation_reference_digests: tuple[str, str],
    source_reference_digests: tuple[str, str],
    warnings: tuple[TrendWarning, ...],
    errors: tuple[TrendError, ...],
) -> tuple:
    return (
        metric_code,
        prior.period_id,
        current.period_id,
        prior.value,
        current.value,
        absolute_change,
        percentage_change,
        transition_kind,
        direction,
        negative_base_direction,
        evidence,
        stable_tolerance,
        registry_digest,
        TrendPolicyVersion.V1,
        observation_reference_digests,
        source_reference_digests,
        warnings,
        errors,
    )


def calculate_transition(
    metric_code: str,
    prior_resolved: ResolvedTrendObservation,
    current_resolved: ResolvedTrendObservation,
    definition: TrendMetricDefinition,
    registry: TrendMetricRegistry,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> TrendTransition:
    """Calculate one canonical adjacent transition from verified observations."""

    if (
        type(prior_resolved) is not ResolvedTrendObservation
        or type(current_resolved) is not ResolvedTrendObservation
        or type(definition) is not TrendMetricDefinition
        or type(registry) is not TrendMetricRegistry
        or type(policy) is not TrendAccountingPolicy
    ):
        raise TrendPairwiseCalculationError(TrendErrorCode.INVALID_CONTRACT)
    prior = prior_resolved.observation
    current = current_resolved.observation
    if (
        metric_code != definition.metric_code
        or prior.segment_ordinal != current.segment_ordinal
        or current.ordinal != prior.ordinal + 1
        or prior.company_id != current.company_id
        or prior.period_family is not current.period_family
        or prior.measurement_basis is not current.measurement_basis
        or prior.measurement_basis is not definition.measurement_basis_for(prior.period_family)
        or prior.currency != current.currency
        or prior.monetary_unit_multiplier != current.monetary_unit_multiplier
        or prior.scale != current.scale
        or prior.scale != definition.scale
    ):
        raise TrendPairwiseCalculationError(TrendErrorCode.CONTRACT_INTEGRITY_FAILURE)

    decision = policy.percentage_sign.decide(
        prior=prior.value,
        current=current.value,
        measurement_basis=prior.measurement_basis,
    )
    absolute_change: Decimal | None = None
    raw_absolute_change: Decimal | None = None
    percentage_change: Decimal | None = None
    warnings: list[TrendWarning] = []
    negative_direction = decision.negative_base_direction

    if prior.value is None or current.value is None:
        transition_kind = TrendTransitionKind.UNAVAILABLE_MISSING_INPUT
        evidence = TrendEvidenceLevel.UNAVAILABLE
    else:
        raw_absolute_change = current.value - prior.value
        absolute_change = _quantize(raw_absolute_change, definition.scale)
        evidence = weakest_evidence(prior.evidence, current.evidence, TrendEvidenceLevel.DERIVED)
        if not definition.percentage_change_enabled:
            transition_kind = TrendTransitionKind.ABSOLUTE_ONLY_RATIO_RATE
            negative_direction = TrendNegativeBaseDirection.NOT_APPLICABLE
        elif decision.decision is TrendPercentageDecision.CALCULATE:
            with localcontext() as context:
                context.prec = policy.numeric.decimal_precision
                percentage_change = _quantize(
                    ((current.value - prior.value) / abs(prior.value)) * Decimal("100"),
                    policy.numeric.analytical_scale,
                )
            transition_kind = TrendTransitionKind.PERCENTAGE_AVAILABLE
        elif decision.decision is TrendPercentageDecision.UNAVAILABLE_ZERO_BASE:
            transition_kind = TrendTransitionKind.ABSOLUTE_ONLY_ZERO_BASE
            warnings.append(TrendWarning(TrendWarningCode.PERCENTAGE_ZERO_BASE))
        elif decision.decision is TrendPercentageDecision.SEMANTIC_ONLY_NEGATIVE_BASE:
            transition_kind = TrendTransitionKind.ABSOLUTE_ONLY_NEGATIVE_BASE
            warnings.append(TrendWarning(TrendWarningCode.NEGATIVE_BASE_SEMANTIC_ONLY))
        elif decision.decision is TrendPercentageDecision.UNAVAILABLE_SIGN_CHANGE:
            transition_kind = TrendTransitionKind.ABSOLUTE_ONLY_SIGN_CHANGE
            warnings.append(TrendWarning(TrendWarningCode.SIGN_CHANGE_PERCENTAGE_SUPPRESSED))
        elif decision.decision is TrendPercentageDecision.ABSOLUTE_DELTA_ONLY_RATIO_RATE:
            transition_kind = TrendTransitionKind.ABSOLUTE_ONLY_RATIO_RATE
        else:
            raise TrendPairwiseCalculationError(TrendErrorCode.CONTRACT_INTEGRITY_FAILURE)

    stable_tolerance = definition.direction_tolerance
    direction = classify_pair_direction(raw_absolute_change, stable_tolerance, transition_kind)
    warning_tuple = tuple(warnings)
    error_tuple: tuple[TrendError, ...] = ()
    observation_digests = (prior_resolved.observation_digest, current_resolved.observation_digest)
    source_digests = (prior.canonical_source_digest, current.canonical_source_digest)
    projection = _transition_projection(
        metric_code=metric_code,
        prior=prior,
        current=current,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        transition_kind=transition_kind,
        direction=direction,
        negative_base_direction=negative_direction,
        evidence=evidence,
        stable_tolerance=stable_tolerance,
        registry_digest=registry.digest,
        observation_reference_digests=observation_digests,
        source_reference_digests=source_digests,
        warnings=warning_tuple,
        errors=error_tuple,
    )
    digest = canonical_trend_digest(projection)
    return TrendTransition(
        metric_code=metric_code,
        from_period_id=prior.period_id,
        to_period_id=current.period_id,
        from_value=prior.value,
        to_value=current.value,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        transition_kind=transition_kind,
        direction=direction,
        negative_base_direction=negative_direction,
        evidence=evidence,
        stable_tolerance=stable_tolerance,
        registry_digest=registry.digest,
        policy_version=TrendPolicyVersion.V1,
        observation_reference_digests=observation_digests,
        source_reference_digests=source_digests,
        transition_digest=digest,
        transition_reference=canonical_trend_reference(projection),
        warnings=warning_tuple,
        errors=error_tuple,
    )


def generate_pairwise_transitions(
    series: ResolvedTrendSeries,
    registry: TrendMetricRegistry,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> tuple[TrendTransition, ...]:
    """Generate only adjacent transitions inside declared contiguous segments."""

    if type(series) is not ResolvedTrendSeries or type(registry) is not TrendMetricRegistry:
        raise TrendPairwiseCalculationError(TrendErrorCode.INVALID_CONTRACT)
    try:
        definition = registry.get(series.metric_code)
    except ValueError:
        raise TrendPairwiseCalculationError(TrendErrorCode.REGISTRY_INTEGRITY_FAILURE) from None
    resolved_by_ordinal = {item.observation.ordinal: item for item in series.observations}
    transitions: list[TrendTransition] = []
    seen_pairs: set[tuple] = set()
    for segment in series.segments:
        expected = tuple(
            item.observation.ordinal
            for item in series.observations
            if item.observation.segment_ordinal == segment.segment_ordinal
        )
        if segment.observation_ordinals != expected:
            raise TrendPairwiseCalculationError(TrendErrorCode.CONTRACT_INTEGRITY_FAILURE)
        for prior_ordinal, current_ordinal in zip(expected, expected[1:]):
            if current_ordinal != prior_ordinal + 1:
                raise TrendPairwiseCalculationError(TrendErrorCode.CONTRACT_INTEGRITY_FAILURE)
            pair = (prior_ordinal, current_ordinal)
            if pair in seen_pairs:
                raise TrendPairwiseCalculationError(TrendErrorCode.DUPLICATE_OBSERVATION)
            seen_pairs.add(pair)
            transitions.append(calculate_transition(
                series.metric_code,
                resolved_by_ordinal[prior_ordinal],
                resolved_by_ordinal[current_ordinal],
                definition,
                registry,
                policy,
            ))
    return tuple(transitions)
