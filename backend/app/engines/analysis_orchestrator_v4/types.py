"""Framework-free, version-isolated Analysis Orchestrator V4 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Protocol, final
from uuid import UUID

from app.engines.cash_flow.contracts import CashFlowPreResolvedContext
from app.engines.common.report_types import ExecutiveReportResult
from app.engines.multi_period_trend import (
    TREND_ACCOUNTING_POLICY_V1,
    TREND_LINEAGE_SCHEMA_VERSION,
    TREND_METRIC_REGISTRY_V1,
    MultiPeriodTrendResult,
    ResolvedTrendSeries,
    TrendComparabilityProfile,
    TrendContractVersion,
    TrendEvidenceLevel,
    TrendLineageEdge,
    TrendLineageSourceAnalysisType,
    TrendLineageSourceEngineCode,
    TrendLineageSourceRole,
    TrendPolicyVersion,
    TrendSourceEngineType,
    TrendUnavailableMetric,
    canonical_trend_digest,
    canonical_trend_lineage_set_digest,
    canonical_trend_reference,
    validate_sha256,
)


ORCHESTRATION_SCHEMA_VERSION_V4 = "4.0.0"
ORCHESTRATION_MODEL_VERSION_V4 = "4.0.0"
EXECUTION_PLAN_VERSION_V4 = "4.0.0"
FINGERPRINT_SCHEMA_VERSION_V4 = "4.0.0"
ORCHESTRATION_CONTRACT_VERSION_V4 = "4.0.0"
TREND_RESULT_SCHEMA_VERSION = "1.0.0"
TREND_RESULT_MODEL_VERSION = "1.0.0"


class OrchestrationEngineCodeV4(str, Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    CASH_FLOW = "cash_flow"
    RATIO = "ratio"
    BENCHMARK = "benchmark"
    HEALTH_SCORE = "health_score"
    CREDIT_SCORE = "credit_score"
    RECOMMENDATION = "recommendation"
    EXECUTIVE_REPORT = "executive_report"
    DASHBOARD = "dashboard"
    RENDER_CONTRACT = "render_contract"
    MULTI_PERIOD_TREND = "multi_period_trend"


ORCHESTRATION_V4_ENGINE_VERSION_MANIFEST = {
    OrchestrationEngineCodeV4.FS_BALANCE_SHEET: (None, "1.0.0"),
    OrchestrationEngineCodeV4.FS_INCOME_STATEMENT: (None, "1.0.0"),
    OrchestrationEngineCodeV4.CASH_FLOW: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV4.RATIO: ("1.0", "1.1.0"),
    OrchestrationEngineCodeV4.BENCHMARK: (None, "1.0.0"),
    OrchestrationEngineCodeV4.HEALTH_SCORE: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV4.CREDIT_SCORE: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV4.RECOMMENDATION: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV4.EXECUTIVE_REPORT: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV4.DASHBOARD: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV4.RENDER_CONTRACT: ("1.0.0", None),
    OrchestrationEngineCodeV4.MULTI_PERIOD_TREND: (
        TREND_RESULT_SCHEMA_VERSION,
        TREND_RESULT_MODEL_VERSION,
    ),
}


class EngineExecutionStatusV4(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"


class RunStatusV4(str, Enum):
    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OrchestrationErrorCategoryV4(str, Enum):
    ENGINE_CONTRACT_VIOLATION = "engine_contract_violation"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VERSION_INCOMPATIBLE_ON_REUSE = "version_incompatible_on_reuse"
    FINGERPRINT_MISMATCH_ON_REUSE = "fingerprint_mismatch_on_reuse"
    RESUME_LINEAGE_INTEGRITY_FAILURE = "resume_lineage_integrity_failure"
    INVALID_RUN_REQUEST = "invalid_run_request"
    CANCELLED = "cancelled"


class DependencyFailureBehaviorV4(str, Enum):
    SKIP = "skip"
    INVOKE_DIAGNOSTIC_ONLY = "invoke_diagnostic_only"


@final
@dataclass(frozen=True, repr=False)
class TrendPreResolvedContextV1:
    resolved_series: tuple[ResolvedTrendSeries, ...]
    comparability_profile: TrendComparabilityProfile
    expected_metric_codes: tuple[str, ...]
    unavailable_metrics: tuple[TrendUnavailableMetric, ...]
    resolution_digest: str
    source_set_digest: str
    lineage: tuple[TrendLineageEdge, ...]
    metric_registry_version: str = TREND_METRIC_REGISTRY_V1.registry_version
    metric_registry_digest: str = TREND_METRIC_REGISTRY_V1.digest
    policy_version: TrendPolicyVersion = TrendPolicyVersion.V1
    contract_version: TrendContractVersion = TrendContractVersion.V1
    lineage_schema_version: str = TREND_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.resolved_series) is not tuple
            or not self.resolved_series
            or any(type(item) is not ResolvedTrendSeries for item in self.resolved_series)
            or type(self.comparability_profile) is not TrendComparabilityProfile
            or type(self.expected_metric_codes) is not tuple
            or any(type(item) is not str for item in self.expected_metric_codes)
            or len(set(self.expected_metric_codes)) != len(self.expected_metric_codes)
            or type(self.unavailable_metrics) is not tuple
            or any(type(item) is not TrendUnavailableMetric for item in self.unavailable_metrics)
        ):
            raise TypeError("trusted trend context has invalid immutable inputs")
        if self.metric_registry_version != TREND_METRIC_REGISTRY_V1.registry_version:
            raise ValueError("trend registry version is unsupported")
        if self.metric_registry_digest != TREND_METRIC_REGISTRY_V1.digest:
            raise ValueError("trend registry digest mismatch")
        if self.policy_version is not TrendPolicyVersion.V1 or self.contract_version is not TrendContractVersion.V1:
            raise ValueError("trend policy/contract version is unsupported")
        if self.lineage_schema_version != TREND_LINEAGE_SCHEMA_VERSION:
            raise ValueError("trend lineage schema version is unsupported")
        if type(self.lineage) is not tuple or any(type(item) is not TrendLineageEdge for item in self.lineage):
            raise TypeError("trusted trend context requires exact immutable lineage")
        expected_resolution, expected_sources, expected_lineage = trend_context_digests(
            self.resolved_series,
            self.expected_metric_codes,
            self.metric_registry_version,
            self.metric_registry_digest,
            self.policy_version,
            self.contract_version,
            self.lineage_schema_version,
        )
        validate_sha256(self.resolution_digest, "resolution_digest")
        validate_sha256(self.source_set_digest, "source_set_digest")
        if self.resolution_digest != expected_resolution or self.source_set_digest != expected_sources:
            raise ValueError("trusted trend context digest mismatch")
        if self.lineage != expected_lineage:
            raise ValueError("trusted trend context lineage mismatch")

    def __repr__(self) -> str:
        return "TrendPreResolvedContextV1()"


def trend_context_digests(
    resolved_series: tuple[ResolvedTrendSeries, ...],
    expected_metric_codes: tuple[str, ...],
    registry_version: str,
    registry_digest: str,
    policy_version: TrendPolicyVersion,
    contract_version: TrendContractVersion,
    lineage_schema_version: str,
) -> tuple[str, str, tuple[TrendLineageEdge, ...]]:
    ordered = tuple(sorted(resolved_series, key=lambda item: item.metric_code))
    resolution_digest = canonical_trend_digest(tuple(
        (item.metric_code, item.resolution_digest, item.candidate_set_digest)
        for item in ordered
    ))
    role_map = {
        TrendSourceEngineType.BALANCE_SHEET: (TrendLineageSourceRole.BALANCE_SHEET, TrendLineageSourceEngineCode.FS_BALANCE_SHEET, TrendLineageSourceAnalysisType.BALANCE_SHEET),
        TrendSourceEngineType.INCOME_STATEMENT: (TrendLineageSourceRole.INCOME_STATEMENT, TrendLineageSourceEngineCode.FS_INCOME_STATEMENT, TrendLineageSourceAnalysisType.INCOME_STATEMENT),
        TrendSourceEngineType.CASH_FLOW: (TrendLineageSourceRole.CASH_FLOW, TrendLineageSourceEngineCode.CASH_FLOW, TrendLineageSourceAnalysisType.CASH_FLOW),
        TrendSourceEngineType.FINANCIAL_RATIOS: (TrendLineageSourceRole.FINANCIAL_RATIOS, TrendLineageSourceEngineCode.RATIO, TrendLineageSourceAnalysisType.FINANCIAL_RATIOS),
    }
    grouped: dict[UUID, list[tuple[ResolvedTrendSeries, object]]] = {}
    for item in ordered:
        for observation in item.observations:
            grouped.setdefault(observation.observation.source_result_id, []).append((item, observation))
    lineage = []
    for source_id, matches in grouped.items():
        observations = tuple(item[1].observation for item in matches)
        first = observations[0]
        if any((item.period_id, item.source_engine_type, item.canonical_source_digest, item.source_schema_version, item.source_model_version) != (first.period_id, first.source_engine_type, first.canonical_source_digest, first.source_schema_version, first.source_model_version) for item in observations[1:]):
            raise ValueError("one trusted trend source has inconsistent semantics")
        segment_digests = {
            segment.comparability_proof_digest
            for series, resolved in matches
            for segment in series.segments
            if resolved.observation.ordinal in segment.observation_ordinals
        }
        if len(segment_digests) != 1:
            raise ValueError("one trusted trend source has inconsistent comparability proof")
        role, engine, analysis = role_map[first.source_engine_type]
        evidence = max((item.evidence for item in observations), key=lambda item: tuple(TrendEvidenceLevel).index(item))
        lineage.append(TrendLineageEdge(
            first.ordinal, first.period_id, source_id, role, engine, analysis,
            first.canonical_source_digest, first.source_schema_version, first.source_model_version,
            evidence, next(iter(segment_digests)),
            canonical_trend_reference(tuple(sorted({series.resolution_reference for series, _ in matches}))),
        ))
    canonical_lineage = tuple(sorted(lineage, key=lambda item: (item.ordinal, item.source_role.value)))
    company_id = ordered[0].company_id
    anchor_period_id = ordered[0].anchor_period_id
    source_set_digest = canonical_trend_lineage_set_digest(
        company_id=company_id, anchor_period_id=anchor_period_id,
        metric_registry_version=registry_version, metric_registry_digest=registry_digest,
        policy_version=policy_version, contract_version=contract_version,
        lineage=canonical_lineage,
    )
    return resolution_digest, source_set_digest, canonical_lineage


def build_trend_pre_resolved_context_v1(
    *,
    resolved_series: tuple[ResolvedTrendSeries, ...],
    comparability_profile: TrendComparabilityProfile,
    expected_metric_codes: tuple[str, ...],
    unavailable_metrics: tuple[TrendUnavailableMetric, ...] = (),
) -> TrendPreResolvedContextV1:
    resolution, sources, lineage = trend_context_digests(
        resolved_series,
        expected_metric_codes,
        TREND_METRIC_REGISTRY_V1.registry_version,
        TREND_METRIC_REGISTRY_V1.digest,
        TREND_ACCOUNTING_POLICY_V1.policy_version,
        TREND_ACCOUNTING_POLICY_V1.contract_version,
        TREND_LINEAGE_SCHEMA_VERSION,
    )
    return TrendPreResolvedContextV1(
        resolved_series,
        comparability_profile,
        expected_metric_codes,
        unavailable_metrics,
        resolution,
        sources,
        lineage,
    )


@dataclass(frozen=True)
class DependencyRequirementV4:
    all_of: tuple[OrchestrationEngineCodeV4, ...] = ()
    any_of: tuple[OrchestrationEngineCodeV4, ...] = ()
    optional: tuple[OrchestrationEngineCodeV4, ...] = ()


@dataclass(frozen=True)
class EngineInvocationSpecV4:
    engine_code: OrchestrationEngineCodeV4
    dependency: DependencyRequirementV4
    produces: str
    is_critical: bool
    dependency_failure_behavior: DependencyFailureBehaviorV4 = DependencyFailureBehaviorV4.SKIP


@dataclass(frozen=True)
class StructuredErrorV4:
    category: OrchestrationErrorCategoryV4
    engine_code: OrchestrationEngineCodeV4 | None
    message_tr: str
    safe_code: str | None
    retryable: bool


@dataclass(frozen=True)
class EngineResultEnvelopeV4:
    engine_code: OrchestrationEngineCodeV4
    result_kind: str
    result: object

    def __post_init__(self) -> None:
        if self.engine_code is OrchestrationEngineCodeV4.MULTI_PERIOD_TREND:
            if self.result_kind != "TrendAnalysisResult" or type(self.result) is not MultiPeriodTrendResult:
                raise TypeError("trend envelope requires exact TrendAnalysisResult")
        if self.engine_code is OrchestrationEngineCodeV4.EXECUTIVE_REPORT:
            if self.result_kind != "ExecutiveReportResult" or type(self.result) is not ExecutiveReportResult:
                raise TypeError("report envelope requires exact ExecutiveReportResult")


@dataclass(frozen=True)
class PerEngineExecutionRecordV4:
    engine_code: OrchestrationEngineCodeV4
    status: EngineExecutionStatusV4
    result: EngineResultEnvelopeV4 | None
    inner_status_value: str | None
    error: StructuredErrorV4 | None
    dependency_engine_codes: tuple[OrchestrationEngineCodeV4, ...]
    engine_schema_version_used: str | None
    engine_model_version_used: str | None
    input_fingerprint: str
    fingerprint_schema_version: str


@dataclass(frozen=True)
class ExecutionProvenanceV4:
    execution_plan_version: str
    engine_call_sequence: tuple[OrchestrationEngineCodeV4, ...]
    reused_engine_codes: tuple[OrchestrationEngineCodeV4, ...]
    skipped_engine_codes: tuple[OrchestrationEngineCodeV4, ...]


@dataclass(frozen=True)
class PreviousEngineSnapshotV4:
    engine_code: OrchestrationEngineCodeV4
    execution_status: EngineExecutionStatusV4
    engine_schema_version_used: str | None
    engine_model_version_used: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    result: EngineResultEnvelopeV4 | None = None
    financial_analysis_result_id: UUID | None = None
    owner_content_digest: str | None = None
    trend_source_set_digest: str | None = None
    trend_resolution_digest: str | None = None
    trend_registry_digest: str | None = None
    trend_policy_version: str | None = None
    trend_lineage_verified: bool | None = None

    def __post_init__(self) -> None:
        is_trend = self.engine_code is OrchestrationEngineCodeV4.MULTI_PERIOD_TREND
        proof = (
            self.trend_source_set_digest,
            self.trend_resolution_digest,
            self.trend_registry_digest,
            self.trend_policy_version,
            self.trend_lineage_verified,
        )
        if is_trend:
            if any(item is None for item in proof) or self.trend_lineage_verified is not True or self.financial_analysis_result_id is None or self.owner_content_digest is None:
                raise ValueError("trend snapshot requires verified source and lineage proofs")
            validate_sha256(self.owner_content_digest, "owner_content_digest")
            for value in proof[:3]:
                validate_sha256(value)
        elif any(item is not None for item in proof) or self.financial_analysis_result_id is not None or self.owner_content_digest is not None:
            raise ValueError("legacy V4 engine snapshot cannot carry trend proof")


@dataclass(frozen=True)
class PreviousExecutionSnapshotV4:
    previous_run_id: str
    request_fingerprint: str
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    engine_snapshots: tuple[PreviousEngineSnapshotV4, ...]

    def __post_init__(self) -> None:
        if (
            self.orchestration_schema_version,
            self.orchestration_model_version,
            self.execution_plan_version,
        ) != ("4.0.0", "4.0.0", "4.0.0"):
            raise ValueError("cross-major snapshot is forbidden")
        if type(self.engine_snapshots) is not tuple or len({item.engine_code for item in self.engine_snapshots}) != len(self.engine_snapshots):
            raise ValueError("V4 snapshot engines must be unique")


@dataclass(frozen=True)
class EngineRawInputsV4:
    balance_sheet_content: bytes | None = None
    balance_sheet_filename: str | None = None
    income_statement_content: bytes | None = None
    income_statement_filename: str | None = None
    trial_balance_result: object | None = None
    prior_period_balance_sheet_facts: object | None = None
    prior_period_income_statement_facts: object | None = None
    prior_period_balance_sheet_result: object | None = None
    prior_period_income_statement_result: object | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    period_months_covered: int | None = None
    cash_flow_pre_resolved_context: CashFlowPreResolvedContext | None = None
    trend_pre_resolved_context: TrendPreResolvedContextV1 | None = None


@dataclass(frozen=True)
class OrchestrationRunOptionsV4:
    industry_code: str | None = None
    company_size_bucket: str | None = None
    tenant_id: str | None = None
    report_type: object | None = None
    dashboard_type: object | None = None
    company_metadata: object | None = None
    reporting_period_label_tr: str | None = None
    optional_sections: tuple[object, ...] | None = None
    currency_display_policy: str | None = None
    locale: str = "tr-TR"
    render_contract: object | None = None


@dataclass(frozen=True)
class OrchestrationRunRequestV4:
    run_id: str
    correlation_id: str | None
    generated_at: str | None
    requested_outputs: tuple[OrchestrationEngineCodeV4, ...]
    engine_inputs: EngineRawInputsV4
    run_options: OrchestrationRunOptionsV4
    previous_execution_snapshot: PreviousExecutionSnapshotV4 | None = None
    contract_version: str = ORCHESTRATION_CONTRACT_VERSION_V4

    def __post_init__(self) -> None:
        if self.contract_version != ORCHESTRATION_CONTRACT_VERSION_V4:
            raise ValueError("unknown V4 orchestration contract version")
        if type(self.engine_inputs) is not EngineRawInputsV4 or type(self.run_options) is not OrchestrationRunOptionsV4:
            raise TypeError("V4 request requires exact V4 inputs/options")
        if type(self.requested_outputs) is not tuple or len(set(self.requested_outputs)) != len(self.requested_outputs):
            raise ValueError("requested outputs must be a unique tuple")
        if any(type(item) is not OrchestrationEngineCodeV4 for item in self.requested_outputs):
            raise TypeError("V4 request rejects cross-major engine codes")
        wants_cash = OrchestrationEngineCodeV4.CASH_FLOW in self.requested_outputs
        wants_trend = OrchestrationEngineCodeV4.MULTI_PERIOD_TREND in self.requested_outputs
        if wants_cash != (self.engine_inputs.cash_flow_pre_resolved_context is not None):
            raise ValueError("Cash Flow output requires exact trusted context presence")
        if wants_trend != (self.engine_inputs.trend_pre_resolved_context is not None):
            raise ValueError("Trend output requires exact trusted context presence")
        if self.previous_execution_snapshot is not None and type(self.previous_execution_snapshot) is not PreviousExecutionSnapshotV4:
            raise TypeError("V4 request rejects cross-major snapshots")


@dataclass(frozen=True)
class OrchestrationRunResultV4:
    run_id: str
    correlation_id: str | None
    generated_at: str | None
    status: RunStatusV4
    engine_records: tuple[PerEngineExecutionRecordV4, ...]
    warnings: tuple[object, ...]
    structured_errors: tuple[StructuredErrorV4, ...]
    execution_provenance: ExecutionProvenanceV4
    input_version_inventory: tuple[tuple[str, str], ...]
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    request_fingerprint: str


@dataclass(frozen=True)
class PerEngineTelemetryV4:
    engine_code: OrchestrationEngineCodeV4
    started_at_offset_ms: float | None
    duration_ms: float | None


@dataclass(frozen=True)
class ExecutionTelemetryV4:
    per_engine: tuple[PerEngineTelemetryV4, ...]
    total_duration_ms: float | None


class TimingProbeV4(Protocol):
    def now(self) -> float: ...


def get_trend_result_v4(result: OrchestrationRunResultV4) -> MultiPeriodTrendResult | None:
    if type(result) is not OrchestrationRunResultV4:
        raise TypeError("trend result access requires exact V4 run result")
    matches = tuple(item for item in result.engine_records if item.engine_code is OrchestrationEngineCodeV4.MULTI_PERIOD_TREND)
    if len(matches) != 1:
        raise ValueError("Trend execution record is missing or duplicated")
    envelope = matches[0].result
    if envelope is None:
        return None
    if envelope.result_kind != "TrendAnalysisResult" or type(envelope.result) is not MultiPeriodTrendResult:
        raise TypeError("Trend result envelope kind/type mismatch")
    return envelope.result
