"""Milestone 4.5 cash-flow contracts, policy, and account registry."""

from .account_codes import normalize_account_code, require_canonical_account_pattern

from .contracts import (
    CashFlowAccountEvidence,
    CashFlowActivityAllocation,
    CashFlowCashAvailabilityDisclosure,
    CashFlowCashAvailabilityObservation,
    CashFlowCompleteness,
    CashFlowComputationDraft,
    CashFlowEndpointReconciliation,
    CashFlowEngineOutcome,
    CashFlowEvidence,
    CashFlowEvidenceReference,
    CashFlowIssue,
    CashFlowLineItem,
    CashFlowNonCashBridgeComponent,
    CashFlowPeriodDescriptor,
    CashFlowPreResolvedContext,
    CashFlowReconciliation,
    CashFlowResult,
    CashFlowSourceLineageReference,
    CashFlowSourceSnapshot,
    IndirectCashFlowInput,
    canonical_cash_flow_bytes,
    canonical_cash_flow_digest,
)
from .errors import (
    CASH_FLOW_ERROR_SAFE_MESSAGE_V1,
    CASH_FLOW_INTEGRITY_ERROR_CODES_V1,
    CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1,
    CASH_FLOW_RETRYABLE_ERROR_CODES_V1,
    CashFlowContractError,
    CashFlowEngineFailure,
)
from .policy import (
    CASH_AND_CASH_EQUIVALENTS_POLICY_V1,
    CASH_EQUIVALENT_POLICY_VERSION,
    CASH_FLOW_ACCOUNTING_POLICY_VERSION,
    CASH_FLOW_MAPPING_REGISTRY_VERSION,
    CASH_FLOW_PRESENTATION_POLICY_MANIFEST_V1,
    CASH_FLOW_RECONCILIATION_POLICY_VERSION,
    CashAndCashEquivalentsPolicy,
    CashEquivalentPolicy,
    CashFlowPolicyVersion,
    CashFlowPresentationPolicy,
    CashFlowPresentationProfile,
    CashFlowPresentationRule,
    canonical_policy_bundle_digest,
    presentation_policy_for,
    quantize_completeness_ratio,
    quantize_money,
    reconciliation_thresholds,
    require_canonical_money,
    require_input_decimal,
)
from .mapping import (
    CashFlowAccountFamilyDefinition,
    CashFlowAccountMapping,
    CashFlowBankAccountClassification,
    CashFlowBankAccountEvidence,
    CashFlowMappingEntry,
    CashFlowMappingResolution,
    CashFlowRoleBehavior,
)
from .registry import (
    CASH_FLOW_ACCOUNT_FAMILY_MANIFEST_V1,
    CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1,
    CASH_FLOW_CODE_MAPPING_MANIFEST_V1,
    CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1,
    CASH_FLOW_MAPPING_REGISTRY_DIGEST_V1,
    CASH_FLOW_ROLE_BEHAVIOR_MANIFEST_V1,
    CashFlowAccountMappingRegistry,
    classify_bank_account_evidence,
)
from .resolution_contracts import (
    CASH_FLOW_PERIOD_RESOLUTION_POLICY_VERSION,
    CashFlowComparabilityRow,
    CashFlowInputResolutionOutcome,
    CashFlowInputResolutionResult,
    CashFlowInputResolutionStatus,
    CashFlowPeriodResolutionRequest,
    CashFlowResolutionRepositoryError,
    CashFlowResolutionSnapshot,
    CashFlowResolvedPeriod,
    CashFlowResolvedSource,
    ComparablePeriodRepositoryPort,
    canonical_resolution_bytes,
    canonical_resolution_digest,
)
from .period_resolution import (
    CASH_FLOW_REQUIRED_SOURCE_ROLES_V1,
    CashFlowMultiPeriodInputResolver,
    resolve_snapshot,
    select_comparable_period,
)
from .analyzer import analyze_indirect_cash_flow
from .calculation import (
    canonical_evidence_bundle_bytes,
    canonical_evidence_bundle_digest,
    computation_draft_digest,
)
from .service import CashFlowCoreOutcome, IndirectCashFlowCoreService
from .quality import (
    CASH_FLOW_COMPLETENESS_MANIFEST_VERSION,
    CashFlowDataQualitySummary,
    assess_data_quality,
    build_completeness,
)
from .reconciliation import (
    CashFlowFinalizationIntegrityError,
    cash_flow_result_digest,
    evaluate_reconciliation,
    finalize_cash_flow_result,
)
from .service import CashFlowEngineService
from .lineage import (
    CASH_FLOW_LINEAGE_POLICY_VERSION,
    CASH_FLOW_LINEAGE_SCHEMA_VERSION,
    CashFlowLineageRepositoryPort,
    CashFlowPortError,
    ResolvedCashFlowLineageEdge,
    VerifiedCashFlowLineage,
    canonical_cash_flow_lineage_set_digest,
    validate_cash_flow_lineage_role_set,
)
from .types import *  # noqa: F401,F403 - the enum module is the public vocabulary
