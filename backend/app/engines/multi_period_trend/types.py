"""Closed vocabularies for Milestone 4.6A multi-period trend contracts.

This module is framework independent and intentionally contains no metric
registry, source resolution, persistence, or trend calculations.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


TREND_SCHEMA_VERSION: Final = "1.0.0"
TREND_MODEL_VERSION: Final = "1.0.0"
TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1: Final = "trend-metric-registry/1.0.0"
TREND_CANONICAL_REFERENCE_PREFIX_V1: Final = "trend:v1:sha256:"


class TrendPeriodFamily(str, Enum):
    ANNUAL = "annual"
    MONTHLY_DISCRETE = "monthly_discrete"
    QUARTERLY_DISCRETE = "quarterly_discrete"
    QUARTERLY_CUMULATIVE_YOY = "quarterly_cumulative_yoy"
    TEMPORARY_TAX_CUMULATIVE_YOY = "temporary_tax_cumulative_yoy"
    CUSTOM_DISCRETE = "custom_discrete"


class TrendCoverageKind(str, Enum):
    DISCRETE = "discrete"
    CUMULATIVE = "cumulative"


class TrendMeasurementBasis(str, Enum):
    STOCK_AS_OF = "stock_as_of"
    DISCRETE_FLOW = "discrete_flow"
    CUMULATIVE_FLOW = "cumulative_flow"
    RATIO_RATE = "ratio_rate"


class TrendEvidenceLevel(str, Enum):
    EXACT = "exact"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class TrendComputationStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT_FOR_TREND = "insufficient_for_trend"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"


class TrendComparabilityStatus(str, Enum):
    COMPARABLE = "comparable"
    SEGMENTED = "segmented"
    NON_COMPARABLE = "non_comparable"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"


class TrendDirection(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    MIXED = "mixed"
    SIGN_CHANGE = "sign_change"
    INSUFFICIENT_DATA = "insufficient_data"


class TrendTransitionKind(str, Enum):
    PERCENTAGE_AVAILABLE = "percentage_available"
    ABSOLUTE_ONLY_ZERO_BASE = "absolute_only_zero_base"
    ABSOLUTE_ONLY_NEGATIVE_BASE = "absolute_only_negative_base"
    ABSOLUTE_ONLY_SIGN_CHANGE = "absolute_only_sign_change"
    ABSOLUTE_ONLY_RATIO_RATE = "absolute_only_ratio_rate"
    UNAVAILABLE_MISSING_INPUT = "unavailable_missing_input"


class TrendMetricAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class TrendFinalMetricAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    NOT_ELIGIBLE = "not_eligible"
    UNAVAILABLE_MISSING_INPUT = "unavailable_missing_input"
    UNAVAILABLE_INCOMPATIBLE_SOURCE = "unavailable_incompatible_source"
    INVALID = "invalid"
    INTEGRITY_FAILURE = "integrity_failure"


class TrendRestatementDisclosureStatus(str, Enum):
    ORIGINAL_ONLY = "original_only"
    RESTATED_DISCLOSED = "restated_disclosed"
    MIXED_SEGMENTED = "mixed_segmented"
    UNKNOWN_PRESENT = "unknown_present"


class TrendOneOffDisclosureStatus(str, Enum):
    INCLUDED_UNADJUSTED = "included_unadjusted"
    UNKNOWN_PRESENT = "unknown_present"


class TrendDataQualityFlag(str, Enum):
    MISSING_PERIOD = "missing_period"
    PERIOD_OVERLAP = "period_overlap"
    CADENCE_MISMATCH = "cadence_mismatch"
    DISCRETE_CUMULATIVE_MIX = "discrete_cumulative_mix"
    CURRENCY_MISMATCH = "currency_mismatch"
    ACCOUNTING_BASIS_MISMATCH = "accounting_basis_mismatch"
    ACCOUNTING_POLICY_BOUNDARY = "accounting_policy_boundary"
    IFRS18_POLICY_BOUNDARY = "ifrs18_policy_boundary"
    SOURCE_MISSING = "source_missing"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_DIGEST_INVALID = "source_digest_invalid"
    SOURCE_VERSION_INVALID = "source_version_invalid"
    RESTATEMENT_BOUNDARY = "restatement_boundary"
    RESTATEMENT_UNKNOWN = "restatement_unknown"
    ONE_OFF_UNADJUSTED = "one_off_unadjusted"
    METRIC_MISSING = "metric_missing"
    ZERO_BASE = "zero_base"
    NEGATIVE_BASE = "negative_base"
    SIGN_CHANGE = "sign_change"
    NOMINAL_ONLY = "nominal_only"


class TrendSourceEngineType(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    FINANCIAL_RATIOS = "financial_ratios"


class TrendRestatementProfile(str, Enum):
    ORIGINAL = "original"
    RESTATED = "restated"
    UNDECLARED_LEGACY = "undeclared_legacy"


class TrendOneOffStatus(str, Enum):
    UNKNOWN = "unknown"
    INCLUDED_UNADJUSTED = "included_unadjusted"


class TrendSegmentBoundaryKind(str, Enum):
    PERIOD_GAP = "period_gap"
    RESTATEMENT_CHANGE = "restatement_change"


class TrendPercentageBaseCase(str, Enum):
    POSITIVE_TO_POSITIVE = "positive_to_positive"
    ZERO_BASE = "zero_base"
    NEGATIVE_TO_NEGATIVE = "negative_to_negative"
    SIGN_CHANGE = "sign_change"
    MISSING_INPUT = "missing_input"
    RATIO_RATE_SERIES = "ratio_rate_series"


class TrendPercentageDecision(str, Enum):
    CALCULATE = "calculate"
    UNAVAILABLE_ZERO_BASE = "unavailable_zero_base"
    SEMANTIC_ONLY_NEGATIVE_BASE = "semantic_only_negative_base"
    UNAVAILABLE_SIGN_CHANGE = "unavailable_sign_change"
    UNAVAILABLE_MISSING_INPUT = "unavailable_missing_input"
    ABSOLUTE_DELTA_ONLY_RATIO_RATE = "absolute_delta_only_ratio_rate"


class TrendNegativeBaseDirection(str, Enum):
    IMPROVING = "improving"
    WORSENING = "worsening"
    UNCHANGED = "unchanged"
    NOT_APPLICABLE = "not_applicable"


class TrendCagrEligibility(str, Enum):
    ELIGIBLE = "eligible"
    DISABLED_FOR_MEASUREMENT_BASIS = "disabled_for_measurement_basis"
    NON_ANNUAL_SERIES = "non_annual_series"
    GAP_PRESENT = "gap_present"
    INSUFFICIENT_ENDPOINTS = "insufficient_endpoints"
    NON_POSITIVE_ENDPOINT = "non_positive_endpoint"
    MISSING_ENDPOINT = "missing_endpoint"


class TrendCagrStatus(str, Enum):
    CALCULATED = "calculated"
    DISABLED = "disabled"
    INSUFFICIENT_DATA = "insufficient_data"
    NON_ANNUAL = "non_annual"
    GAP_PRESENT = "gap_present"
    NON_POSITIVE_ENDPOINT = "non_positive_endpoint"
    SIGN_CHANGE = "sign_change"
    RESTATEMENT_BOUNDARY = "restatement_boundary"
    NUMERIC_NON_CONVERGENCE = "numeric_non_convergence"


class TrendAggregateAvailability(str, Enum):
    CALCULATED = "calculated"
    NOT_DETECTED = "not_detected"
    UNAVAILABLE = "unavailable"


class TrendVolatilityCategory(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNAVAILABLE = "unavailable"


class TrendGapPolicy(str, Enum):
    SEGMENT_WITHOUT_FILL = "segment_without_fill"


class TrendOverlapPolicy(str, Enum):
    REJECT = "reject"


class TrendDuplicatePolicy(str, Enum):
    REJECT = "reject"


class TrendNominalAnalysisProfile(str, Enum):
    NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT = "nominal_only_no_inflation_adjustment"


class TrendRoundingMode(str, Enum):
    HALF_EVEN = "half_even"


class TrendPolicyVersion(str, Enum):
    V1 = "trend-accounting-policy/1.0.0"


class TrendContractVersion(str, Enum):
    V1 = "1.0.0"


class TrendWarningCode(str, Enum):
    MINIMUM_TREND_DATA_INCOMPLETE = "minimum_trend_data_incomplete"
    PERIOD_GAP_SEGMENTED = "period_gap_segmented"
    METRIC_OBSERVATION_UNAVAILABLE = "metric_observation_unavailable"
    PERCENTAGE_ZERO_BASE = "percentage_zero_base"
    NEGATIVE_BASE_SEMANTIC_ONLY = "negative_base_semantic_only"
    SIGN_CHANGE_PERCENTAGE_SUPPRESSED = "sign_change_percentage_suppressed"
    CAGR_NOT_ELIGIBLE = "cagr_not_eligible"
    CAGR_NUMERIC_NON_CONVERGENCE = "cagr_numeric_non_convergence"
    VOLATILITY_NOT_ELIGIBLE = "volatility_not_eligible"
    BREAK_NOT_ELIGIBLE = "break_not_eligible"
    RESTATEMENT_BOUNDARY_SEGMENTED = "restatement_boundary_segmented"
    LEGACY_RESTATEMENT_STATUS_UNDECLARED = "legacy_restatement_status_undeclared"
    ONE_OFF_STATUS_UNKNOWN = "one_off_status_unknown"
    ONE_OFF_INCLUDED_UNADJUSTED = "one_off_included_unadjusted"
    NOMINAL_NOT_INFLATION_ADJUSTED = "nominal_not_inflation_adjusted"
    SOURCE_EVIDENCE_ESTIMATED = "source_evidence_estimated"


class TrendErrorCode(str, Enum):
    INVALID_CONTRACT = "invalid_contract"
    INVALID_PERIOD_SET = "invalid_period_set"
    PERIOD_OVERLAP = "period_overlap"
    DUPLICATE_OBSERVATION = "duplicate_observation"
    MIXED_COMPANY = "mixed_company"
    MIXED_CURRENCY = "mixed_currency"
    MIXED_MEASUREMENT_BASIS = "mixed_measurement_basis"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_SCOPE_MISMATCH = "source_scope_mismatch"
    SOURCE_STATUS_INVALID = "source_status_invalid"
    SOURCE_VERSION_UNSUPPORTED = "source_version_unsupported"
    SOURCE_DIGEST_MISMATCH = "source_digest_mismatch"
    PERIOD_NOT_COMPARABLE = "period_not_comparable"
    POLICY_VERSION_UNSUPPORTED = "policy_version_unsupported"
    DECIMAL_NON_FINITE_OR_SCALE_INVALID = "decimal_non_finite_or_scale_invalid"
    CANONICAL_REFERENCE_INVALID = "canonical_reference_invalid"
    CONTRACT_INTEGRITY_FAILURE = "contract_integrity_failure"


TREND_EVIDENCE_RANK: Final = {
    TrendEvidenceLevel.EXACT: 3,
    TrendEvidenceLevel.DERIVED: 2,
    TrendEvidenceLevel.ESTIMATED: 1,
    TrendEvidenceLevel.UNAVAILABLE: 0,
}


def weakest_evidence(*levels: TrendEvidenceLevel) -> TrendEvidenceLevel:
    if not levels or any(type(level) is not TrendEvidenceLevel for level in levels):
        raise ValueError("evidence levels must be non-empty exact enum values")
    return min(levels, key=TREND_EVIDENCE_RANK.__getitem__)
