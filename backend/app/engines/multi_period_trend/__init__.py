"""Milestone 4.6A multi-period trend contract package."""

from .canonical import (
    TrendCanonicalError,
    canonical_trend_bytes,
    canonical_trend_digest,
    canonical_trend_reference,
    normalize_decimal,
    validate_sha256,
    validate_trend_reference,
)
from .contracts import (
    MultiPeriodTrendResult,
    TrendCagrResult,
    TrendBreakResult,
    TrendCompleteness,
    TrendContractError,
    TrendDataQuality,
    TrendError,
    TrendEvidenceSummary,
    TrendGap,
    TrendLineageReference,
    TrendMetricResult,
    TrendMetricQuality,
    TrendNominalDisclosure,
    TrendObservation,
    TrendSegmentBoundary,
    TrendSeries,
    TrendStabilityResult,
    TrendSourceReference,
    TrendTransition,
    TrendTransitionCompleteness,
    TrendResultCompleteness,
    TrendUnavailableMetric,
    TrendVolatilityResult,
    TrendWarning,
)
from .errors import TrendEngineFailure, TrendResultAssemblyError
from .compatibility import (
    TrendSourceCompatibilityDecision,
    TrendSourceCompatibilityStatus,
    TrendSourceVersion,
    decide_source_compatibility,
)
from .evidence_mapping import (
    TrendEvidenceMappingOutcome,
    TrendEvidenceMappingReason,
    TrendRatioComputationStatus,
    TrendRatioReliability,
    TrendSourceMetricProjection,
    TrendSourceMetricStatus,
    TrendSourceMode,
    map_source_metric_evidence,
)
from .policy import (
    TREND_ACCOUNTING_POLICY_V1,
    TREND_CADENCE_POLICIES_V1,
    TREND_NUMERIC_POLICY_V1,
    TREND_PERCENTAGE_SIGN_POLICY_V1,
    TREND_THRESHOLD_POLICY_V1,
    TrendAccountingPolicy,
    TrendCadencePolicy,
    TrendComparabilityProfile,
    TrendNumericPolicy,
    TrendPercentageSignDecision,
    TrendPercentageSignPolicy,
    TrendPolicyError,
    TrendThresholdPolicy,
)
from .types import *  # noqa: F403 - the module is the closed enum surface
from .registry import (
    TREND_METRIC_DEFINITIONS_V1,
    TREND_METRIC_REGISTRY_REFERENCE_PREFIX_V1,
    TREND_METRIC_REGISTRY_V1,
    TREND_METRIC_REGISTRY_VERSION,
    TrendCurrencyBehavior,
    TrendEvidenceMappingProfile,
    TrendMetricDefinition,
    TrendMetricRegistry,
    TrendMetricRegistryError,
    TrendMetricRoundingSemantics,
    TrendMetricSignPolicy,
    TrendMetricTombstone,
    TrendMetricUnit,
    TrendSourceAnalysisType,
    UnknownTrendMetricCode,
    registry_with_version,
)
from .resolution_contracts import (
    TREND_COMPARABILITY_PROFILE_VERSION_V1,
    TREND_SERIES_RESOLUTION_CONTRACT_VERSION,
    ResolvedTrendObservation,
    ResolvedTrendSegment,
    ResolvedTrendSeries,
    TrendResolvedPeriod,
    TrendResolvedPeriodStatus,
    TrendResolvedPeriodType,
    TrendResolvedSourceCandidate,
    TrendResolvedSourceStatus,
    TrendSeriesRepositoryError,
    TrendSeriesRepositoryPort,
    TrendSeriesResolutionContractError,
    TrendSeriesResolutionErrorCode,
    TrendSeriesResolutionRequest,
    TrendSeriesResolutionResult,
    TrendSeriesResolutionSnapshot,
    TrendSeriesResolutionStatus,
    TrendSourceSelectionIntent,
    TrendSourceSelectionRole,
    canonical_candidate_set_digest,
)
from .series_resolution import TrendMultiPeriodSeriesResolver, resolve_series_snapshot
from .direction import aggregate_direction, classify_pair_direction
from .pairwise import (
    TrendPairwiseCalculationError,
    calculate_transition,
    generate_pairwise_transitions,
)
from .analyzer import analyze_pairwise_series
from .cagr import calculate_cagr, decimal_nth_root
from .stability import calculate_stability
from .volatility import calculate_volatility, decimal_square_root
from .break_analysis import calculate_trend_break, select_break_candidate
from .analyzer import analyze_trend_aggregates
from .completeness import build_result_completeness
from .quality import (
    classify_metric_quality,
    metric_effective_evidence,
    one_off_disclosure,
    quality_flags,
    restatement_disclosure,
)
from .result_assembly import assemble_multi_period_trend_result
from .lineage import (
    TREND_LINEAGE_REFERENCE_PREFIX,
    TREND_LINEAGE_SCHEMA_VERSION,
    TrendLineageEdge,
    TrendLineagePortError,
    TrendLineagePortErrorCode,
    TrendLineageRepositoryPort,
    TrendLineageSet,
    TrendLineageSourceAnalysisType,
    TrendLineageSourceEngineCode,
    TrendLineageSourceRole,
    VerifiedTrendLineage,
    build_trend_lineage_set,
    canonical_trend_lineage_set_digest,
)


__all__ = [name for name in globals() if name.startswith("Trend") or name.startswith("TREND_") or name.startswith("MultiPeriod") or name.startswith("VerifiedTrend") or name.startswith("canonical_") or name in {"normalize_decimal", "validate_sha256", "validate_trend_reference", "aggregate_direction", "classify_pair_direction", "calculate_transition", "generate_pairwise_transitions", "analyze_pairwise_series", "calculate_cagr", "decimal_nth_root", "calculate_stability", "calculate_volatility", "decimal_square_root", "calculate_trend_break", "select_break_candidate", "analyze_trend_aggregates", "build_result_completeness", "classify_metric_quality", "metric_effective_evidence", "one_off_disclosure", "quality_flags", "restatement_disclosure", "assemble_multi_period_trend_result", "build_trend_lineage_set"}]
