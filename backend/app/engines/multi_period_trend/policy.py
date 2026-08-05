"""Immutable accounting and numeric policy for Milestone 4.6A.

The policy only classifies eligibility and fixes invariants.  It does not
calculate percentage changes, CAGR, volatility, or trend breaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from uuid import UUID

from .canonical import normalize_decimal
from .types import (
    TrendCagrEligibility,
    TrendContractVersion,
    TrendCoverageKind,
    TrendDuplicatePolicy,
    TrendGapPolicy,
    TrendMeasurementBasis,
    TrendNegativeBaseDirection,
    TrendNominalAnalysisProfile,
    TrendOverlapPolicy,
    TrendPercentageBaseCase,
    TrendPercentageDecision,
    TrendPeriodFamily,
    TrendPolicyVersion,
    TrendRestatementProfile,
    TrendRoundingMode,
)


class TrendPolicyError(ValueError):
    __slots__ = ()


class _SafePolicyValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise TrendPolicyError(f"{name} must be a positive integer")
    return value


def _bounded_text(value: object, name: str, maximum: int = 128) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise TrendPolicyError(f"{name} must be bounded non-empty text")
    return value


@dataclass(frozen=True, repr=False)
class TrendNumericPolicy(_SafePolicyValue):
    rounding_mode: TrendRoundingMode
    decimal_precision: int
    monetary_scale: int
    analytical_scale: int
    days_scale: int
    normalize_negative_zero: bool

    def __post_init__(self) -> None:
        if self.rounding_mode is not TrendRoundingMode.HALF_EVEN:
            raise TrendPolicyError("v1 requires HALF_EVEN rounding")
        if self.decimal_precision != 50:
            raise TrendPolicyError("v1 decimal precision must be 50")
        if (self.monetary_scale, self.analytical_scale, self.days_scale) != (2, 4, 2):
            raise TrendPolicyError("v1 numeric scales are fixed")
        if self.normalize_negative_zero is not True:
            raise TrendPolicyError("v1 must normalize negative zero")

    def quantize(self, value: Decimal, scale: int) -> Decimal:
        if type(scale) is not int or scale < 0 or scale > 12:
            raise TrendPolicyError("scale is outside the supported range")
        value = normalize_decimal(value)
        quantum = Decimal(1).scaleb(-scale)
        with localcontext() as context:
            context.prec = self.decimal_precision
            rounded = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
        return normalize_decimal(rounded)


@dataclass(frozen=True, repr=False)
class TrendThresholdPolicy(_SafePolicyValue):
    pairwise_minimum_observations: int
    direction_minimum_observations: int
    volatility_minimum_observations: int
    break_minimum_observations: int
    cagr_minimum_endpoints: int
    normalized_direction_tolerance: Decimal
    volatility_low_maximum: Decimal
    volatility_medium_maximum: Decimal
    break_score_minimum: Decimal

    def __post_init__(self) -> None:
        values = (
            self.pairwise_minimum_observations,
            self.direction_minimum_observations,
            self.volatility_minimum_observations,
            self.break_minimum_observations,
            self.cagr_minimum_endpoints,
        )
        if values != (2, 3, 4, 5, 2):
            raise TrendPolicyError("v1 observation thresholds are fixed at 2/3/4/5/2")
        for name in (
            "normalized_direction_tolerance",
            "volatility_low_maximum",
            "volatility_medium_maximum",
            "break_score_minimum",
        ):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise TrendPolicyError(f"{name} must be a non-negative finite Decimal")
        if (
            self.normalized_direction_tolerance != Decimal("0.0001")
            or self.volatility_low_maximum != Decimal("0.0500")
            or self.volatility_medium_maximum != Decimal("0.1500")
            or self.break_score_minimum != Decimal("0.1000")
        ):
            raise TrendPolicyError("v1 analytical thresholds are fixed")


@dataclass(frozen=True, repr=False)
class TrendCadencePolicy(_SafePolicyValue):
    period_family: TrendPeriodFamily
    coverage_kind: TrendCoverageKind
    minimum_months_covered: int
    maximum_months_covered: int
    same_period_number_across_years: bool
    consecutive_periods_required: bool
    cagr_allowed: bool

    def __post_init__(self) -> None:
        if type(self.period_family) is not TrendPeriodFamily:
            raise TrendPolicyError("period_family must be exact enum")
        if type(self.coverage_kind) is not TrendCoverageKind:
            raise TrendPolicyError("coverage_kind must be exact enum")
        _positive_int(self.minimum_months_covered, "minimum_months_covered")
        _positive_int(self.maximum_months_covered, "maximum_months_covered")
        if self.minimum_months_covered > self.maximum_months_covered:
            raise TrendPolicyError("cadence month bounds are reversed")
        for name in (
            "same_period_number_across_years",
            "consecutive_periods_required",
            "cagr_allowed",
        ):
            if type(getattr(self, name)) is not bool:
                raise TrendPolicyError(f"{name} must be bool")


@dataclass(frozen=True, repr=False)
class TrendPercentageSignDecision(_SafePolicyValue):
    base_case: TrendPercentageBaseCase
    decision: TrendPercentageDecision
    negative_base_direction: TrendNegativeBaseDirection

    def __post_init__(self) -> None:
        if type(self.base_case) is not TrendPercentageBaseCase:
            raise TrendPolicyError("invalid percentage base case")
        if type(self.decision) is not TrendPercentageDecision:
            raise TrendPolicyError("invalid percentage decision")
        if type(self.negative_base_direction) is not TrendNegativeBaseDirection:
            raise TrendPolicyError("invalid negative-base direction")
        if self.base_case is TrendPercentageBaseCase.NEGATIVE_TO_NEGATIVE:
            if self.decision is not TrendPercentageDecision.SEMANTIC_ONLY_NEGATIVE_BASE:
                raise TrendPolicyError("negative base requires semantic-only decision")
            if self.negative_base_direction is TrendNegativeBaseDirection.NOT_APPLICABLE:
                raise TrendPolicyError("negative base requires a semantic direction")
        elif self.negative_base_direction is not TrendNegativeBaseDirection.NOT_APPLICABLE:
            raise TrendPolicyError("negative-base direction is not applicable")


@dataclass(frozen=True, repr=False)
class TrendPercentageSignPolicy(_SafePolicyValue):
    policy_version: TrendPolicyVersion
    ratio_rate_percentage_enabled: bool

    def __post_init__(self) -> None:
        if self.policy_version is not TrendPolicyVersion.V1:
            raise TrendPolicyError("unsupported percentage/sign policy")
        if self.ratio_rate_percentage_enabled is not False:
            raise TrendPolicyError("v1 ratio/rate percentage change is disabled")

    def decide(
        self,
        *,
        prior: Decimal | None,
        current: Decimal | None,
        measurement_basis: TrendMeasurementBasis,
    ) -> TrendPercentageSignDecision:
        if type(measurement_basis) is not TrendMeasurementBasis:
            raise TrendPolicyError("measurement_basis must be exact enum")
        for value in (prior, current):
            if value is not None and (type(value) is not Decimal or not value.is_finite()):
                raise TrendPolicyError("percentage decision accepts finite Decimal or None")
        if prior is None or current is None:
            return TrendPercentageSignDecision(
                TrendPercentageBaseCase.MISSING_INPUT,
                TrendPercentageDecision.UNAVAILABLE_MISSING_INPUT,
                TrendNegativeBaseDirection.NOT_APPLICABLE,
            )
        if measurement_basis is TrendMeasurementBasis.RATIO_RATE:
            return TrendPercentageSignDecision(
                TrendPercentageBaseCase.RATIO_RATE_SERIES,
                TrendPercentageDecision.ABSOLUTE_DELTA_ONLY_RATIO_RATE,
                TrendNegativeBaseDirection.NOT_APPLICABLE,
            )
        prior = normalize_decimal(prior)
        current = normalize_decimal(current)
        if prior == 0:
            return TrendPercentageSignDecision(
                TrendPercentageBaseCase.ZERO_BASE,
                TrendPercentageDecision.UNAVAILABLE_ZERO_BASE,
                TrendNegativeBaseDirection.NOT_APPLICABLE,
            )
        if (prior < 0 <= current) or (prior > 0 >= current):
            return TrendPercentageSignDecision(
                TrendPercentageBaseCase.SIGN_CHANGE,
                TrendPercentageDecision.UNAVAILABLE_SIGN_CHANGE,
                TrendNegativeBaseDirection.NOT_APPLICABLE,
            )
        if prior < 0 and current < 0:
            direction = (
                TrendNegativeBaseDirection.IMPROVING
                if current > prior
                else TrendNegativeBaseDirection.WORSENING
                if current < prior
                else TrendNegativeBaseDirection.UNCHANGED
            )
            return TrendPercentageSignDecision(
                TrendPercentageBaseCase.NEGATIVE_TO_NEGATIVE,
                TrendPercentageDecision.SEMANTIC_ONLY_NEGATIVE_BASE,
                direction,
            )
        return TrendPercentageSignDecision(
            TrendPercentageBaseCase.POSITIVE_TO_POSITIVE,
            TrendPercentageDecision.CALCULATE,
            TrendNegativeBaseDirection.NOT_APPLICABLE,
        )

    def cagr_eligibility(
        self,
        *,
        period_family: TrendPeriodFamily,
        measurement_basis: TrendMeasurementBasis,
        gap_free: bool,
        endpoint_count: int,
        first_value: Decimal | None,
        last_value: Decimal | None,
    ) -> TrendCagrEligibility:
        if type(period_family) is not TrendPeriodFamily or type(measurement_basis) is not TrendMeasurementBasis:
            raise TrendPolicyError("CAGR policy requires exact period/basis enums")
        if type(gap_free) is not bool or type(endpoint_count) is not int:
            raise TrendPolicyError("CAGR gap/endpoint inputs are invalid")
        for value in (first_value, last_value):
            if value is not None and (type(value) is not Decimal or not value.is_finite()):
                raise TrendPolicyError("CAGR endpoints must be finite Decimal or None")
        if measurement_basis is TrendMeasurementBasis.RATIO_RATE:
            return TrendCagrEligibility.DISABLED_FOR_MEASUREMENT_BASIS
        if period_family is not TrendPeriodFamily.ANNUAL:
            return TrendCagrEligibility.NON_ANNUAL_SERIES
        if not gap_free:
            return TrendCagrEligibility.GAP_PRESENT
        if endpoint_count < 2:
            return TrendCagrEligibility.INSUFFICIENT_ENDPOINTS
        if first_value is None or last_value is None:
            return TrendCagrEligibility.MISSING_ENDPOINT
        if first_value <= 0 or last_value <= 0:
            return TrendCagrEligibility.NON_POSITIVE_ENDPOINT
        return TrendCagrEligibility.ELIGIBLE


@dataclass(frozen=True, repr=False)
class TrendComparabilityProfile(_SafePolicyValue):
    tenant_id: UUID
    company_id: UUID
    currency: str
    accounting_basis: str
    accounting_policy_version: str
    fiscal_calendar_reference: str
    period_family: TrendPeriodFamily
    coverage_kind: TrendCoverageKind
    source_schema_version: str | None
    source_model_version: str
    require_source_digest: bool
    restatement_profile: TrendRestatementProfile
    nominal_analysis_profile: TrendNominalAnalysisProfile
    gap_policy: TrendGapPolicy
    overlap_policy: TrendOverlapPolicy
    duplicate_policy: TrendDuplicatePolicy

    def __post_init__(self) -> None:
        if type(self.tenant_id) is not UUID or type(self.company_id) is not UUID:
            raise TrendPolicyError("tenant/company comparability scope must use UUID")
        for name in (
            "currency",
            "accounting_basis",
            "accounting_policy_version",
            "fiscal_calendar_reference",
            "source_model_version",
        ):
            _bounded_text(getattr(self, name), name)
        if len(self.currency) != 3 or self.currency != self.currency.upper():
            raise TrendPolicyError("currency must be uppercase three-letter code")
        if self.source_schema_version is not None:
            _bounded_text(self.source_schema_version, "source_schema_version")
        exact_types = (
            (self.period_family, TrendPeriodFamily),
            (self.coverage_kind, TrendCoverageKind),
            (self.restatement_profile, TrendRestatementProfile),
            (self.nominal_analysis_profile, TrendNominalAnalysisProfile),
            (self.gap_policy, TrendGapPolicy),
            (self.overlap_policy, TrendOverlapPolicy),
            (self.duplicate_policy, TrendDuplicatePolicy),
        )
        if any(type(value) is not expected for value, expected in exact_types):
            raise TrendPolicyError("comparability profile contains an invalid enum")
        if self.require_source_digest is not True:
            raise TrendPolicyError("v1 comparability requires source digests")
        if self.nominal_analysis_profile is not TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT:
            raise TrendPolicyError("v1 supports nominal analysis only")


@dataclass(frozen=True, repr=False)
class TrendAccountingPolicy(_SafePolicyValue):
    policy_version: TrendPolicyVersion
    contract_version: TrendContractVersion
    numeric: TrendNumericPolicy
    thresholds: TrendThresholdPolicy
    cadence_policies: tuple[TrendCadencePolicy, ...]
    percentage_sign: TrendPercentageSignPolicy
    maximum_observations: int

    def __post_init__(self) -> None:
        if self.policy_version is not TrendPolicyVersion.V1 or self.contract_version is not TrendContractVersion.V1:
            raise TrendPolicyError("unsupported trend accounting policy version")
        if type(self.numeric) is not TrendNumericPolicy or type(self.thresholds) is not TrendThresholdPolicy:
            raise TrendPolicyError("trend accounting policy requires exact subcontracts")
        if type(self.cadence_policies) is not tuple or any(type(item) is not TrendCadencePolicy for item in self.cadence_policies):
            raise TrendPolicyError("cadence policies must be an immutable exact tuple")
        if tuple(item.period_family for item in self.cadence_policies) != tuple(TrendPeriodFamily):
            raise TrendPolicyError("cadence policies must cover every family in declaration order")
        if type(self.percentage_sign) is not TrendPercentageSignPolicy:
            raise TrendPolicyError("percentage/sign policy type is invalid")
        if self.maximum_observations != 60:
            raise TrendPolicyError("v1 maximum observation count is 60")


TREND_NUMERIC_POLICY_V1 = TrendNumericPolicy(
    rounding_mode=TrendRoundingMode.HALF_EVEN,
    decimal_precision=50,
    monetary_scale=2,
    analytical_scale=4,
    days_scale=2,
    normalize_negative_zero=True,
)

TREND_THRESHOLD_POLICY_V1 = TrendThresholdPolicy(
    pairwise_minimum_observations=2,
    direction_minimum_observations=3,
    volatility_minimum_observations=4,
    break_minimum_observations=5,
    cagr_minimum_endpoints=2,
    normalized_direction_tolerance=Decimal("0.0001"),
    volatility_low_maximum=Decimal("0.0500"),
    volatility_medium_maximum=Decimal("0.1500"),
    break_score_minimum=Decimal("0.1000"),
)

TREND_CADENCE_POLICIES_V1 = (
    TrendCadencePolicy(TrendPeriodFamily.ANNUAL, TrendCoverageKind.CUMULATIVE, 12, 12, False, True, True),
    TrendCadencePolicy(TrendPeriodFamily.MONTHLY_DISCRETE, TrendCoverageKind.DISCRETE, 1, 1, False, True, False),
    TrendCadencePolicy(TrendPeriodFamily.QUARTERLY_DISCRETE, TrendCoverageKind.DISCRETE, 3, 3, False, True, False),
    TrendCadencePolicy(TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY, TrendCoverageKind.CUMULATIVE, 3, 12, True, True, False),
    TrendCadencePolicy(TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY, TrendCoverageKind.CUMULATIVE, 1, 12, True, True, False),
    TrendCadencePolicy(TrendPeriodFamily.CUSTOM_DISCRETE, TrendCoverageKind.DISCRETE, 1, 12, False, True, False),
)

TREND_PERCENTAGE_SIGN_POLICY_V1 = TrendPercentageSignPolicy(
    policy_version=TrendPolicyVersion.V1,
    ratio_rate_percentage_enabled=False,
)

TREND_ACCOUNTING_POLICY_V1 = TrendAccountingPolicy(
    policy_version=TrendPolicyVersion.V1,
    contract_version=TrendContractVersion.V1,
    numeric=TREND_NUMERIC_POLICY_V1,
    thresholds=TREND_THRESHOLD_POLICY_V1,
    cadence_policies=TREND_CADENCE_POLICIES_V1,
    percentage_sign=TREND_PERCENTAGE_SIGN_POLICY_V1,
    maximum_observations=60,
)
