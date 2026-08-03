"""Framework-free, immutable Analysis Orchestrator V3 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Protocol
from uuid import UUID
import unicodedata

from app.engines.cash_flow.contracts import CashFlowPreResolvedContext, CashFlowResult
from app.engines.cash_flow.types import CashFlowErrorCode

ORCHESTRATION_SCHEMA_VERSION_V3 = "3.0.0"
ORCHESTRATION_MODEL_VERSION_V3 = "3.0.0"
EXECUTION_PLAN_VERSION_V3 = "3.0.0"
FINGERPRINT_SCHEMA_VERSION_V3 = "1.0.0"
ORCHESTRATION_CONTRACT_VERSION_V3 = "3.0.0"


class OrchestrationEngineCodeV3(str, Enum):
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


ORCHESTRATION_V3_ENGINE_CODE_MANIFEST = tuple(OrchestrationEngineCodeV3)

ORCHESTRATION_V3_ENGINE_VERSION_MANIFEST = {
    OrchestrationEngineCodeV3.FS_BALANCE_SHEET: (None, "1.0.0"),
    OrchestrationEngineCodeV3.FS_INCOME_STATEMENT: (None, "1.0.0"),
    OrchestrationEngineCodeV3.CASH_FLOW: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV3.RATIO: ("1.0", "1.1.0"),
    OrchestrationEngineCodeV3.BENCHMARK: (None, "1.0.0"),
    OrchestrationEngineCodeV3.HEALTH_SCORE: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV3.CREDIT_SCORE: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV3.RECOMMENDATION: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV3.EXECUTIVE_REPORT: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV3.DASHBOARD: ("1.0.0", "1.0.0"),
    OrchestrationEngineCodeV3.RENDER_CONTRACT: ("1.0.0", None),
}


class EngineExecutionStatusV3(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"


class RunStatusV3(str, Enum):
    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OrchestrationErrorCategoryV3(str, Enum):
    ENGINE_CONTRACT_VIOLATION = "engine_contract_violation"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VERSION_INCOMPATIBLE_ON_REUSE = "version_incompatible_on_reuse"
    FINGERPRINT_MISMATCH_ON_REUSE = "fingerprint_mismatch_on_reuse"
    INVALID_RUN_REQUEST = "invalid_run_request"
    CANCELLED = "cancelled"


class DependencyFailureBehaviorV3(str, Enum):
    SKIP = "skip"
    INVOKE_DIAGNOSTIC_ONLY = "invoke_diagnostic_only"


class FinancialAnalysisStatusV3(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class FinancialSourceModeV3(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"


@dataclass(frozen=True)
class OrchestrationJsonObjectV3:
    items: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        if type(self.items) is not tuple:
            raise TypeError("V3 object items must be tuple")
        keys = []
        for item in self.items:
            if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str:
                raise TypeError("V3 object entry must be (str,value)")
            if not item[0] or unicodedata.normalize("NFC", item[0]) != item[0]:
                raise ValueError("V3 object key must be non-empty NFC")
            _validate_json_value(item[1])
            keys.append(item[0])
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("V3 object keys must be sorted and unique")


def _validate_json_value(value: object) -> None:
    if value is None or type(value) in {bool, str, int, UUID, date}:
        return
    if type(value) is Decimal and value.is_finite():
        return
    if type(value) is tuple:
        for item in value:
            _validate_json_value(item)
        return
    if type(value) is OrchestrationJsonObjectV3:
        return
    raise TypeError("unsupported mutable/non-canonical V3 value")


EMPTY_JSON_OBJECT_V3 = OrchestrationJsonObjectV3(())


@dataclass(frozen=True)
class DependencyRequirementV3:
    all_of: tuple[OrchestrationEngineCodeV3, ...] = ()
    any_of: tuple[OrchestrationEngineCodeV3, ...] = ()
    optional: tuple[OrchestrationEngineCodeV3, ...] = ()


@dataclass(frozen=True)
class EngineInvocationSpecV3:
    engine_code: OrchestrationEngineCodeV3
    dependency: DependencyRequirementV3
    produces: str
    is_critical: bool
    dependency_failure_behavior: DependencyFailureBehaviorV3 = DependencyFailureBehaviorV3.SKIP


@dataclass(frozen=True)
class StructuredErrorV3:
    category: OrchestrationErrorCategoryV3
    engine_code: OrchestrationEngineCodeV3 | None
    message_tr: str
    cash_flow_error_code: CashFlowErrorCode | None
    safe_metadata: OrchestrationJsonObjectV3
    retryable: bool
    original_exception_type: str | None = None


@dataclass(frozen=True)
class BalanceSheetAnalysisOutcomeV3:
    status: FinancialAnalysisStatusV3
    source_mode: FinancialSourceModeV3 | None
    result_json: OrchestrationJsonObjectV3 | None
    error_message: str | None
    trial_balance_usage: str | None


@dataclass(frozen=True)
class IncomeStatementAnalysisOutcomeV3:
    status: FinancialAnalysisStatusV3
    source_mode: FinancialSourceModeV3 | None
    result_json: OrchestrationJsonObjectV3 | None
    error_message: str | None
    trial_balance_usage: str | None


@dataclass(frozen=True)
class EngineResultEnvelopeV3:
    engine_code: OrchestrationEngineCodeV3
    result_kind: str
    result: object


@dataclass(frozen=True)
class PerEngineExecutionRecordV3:
    engine_code: OrchestrationEngineCodeV3
    status: EngineExecutionStatusV3
    result: EngineResultEnvelopeV3 | None
    inner_status_value: str | None
    error: StructuredErrorV3 | None
    dependency_engine_codes: tuple[OrchestrationEngineCodeV3, ...]
    engine_schema_version_used: str | None
    engine_model_version_used: str | None
    input_fingerprint: str
    fingerprint_schema_version: str


@dataclass(frozen=True)
class ExecutionProvenanceV3:
    execution_plan_version: str
    engine_call_sequence: tuple[OrchestrationEngineCodeV3, ...]
    reused_engine_codes: tuple[OrchestrationEngineCodeV3, ...]
    skipped_engine_codes: tuple[OrchestrationEngineCodeV3, ...]


@dataclass(frozen=True)
class PreviousEngineSnapshotV3:
    engine_code: OrchestrationEngineCodeV3
    execution_status: EngineExecutionStatusV3
    engine_schema_version_used: str | None
    engine_model_version_used: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    result: EngineResultEnvelopeV3 | None = None


@dataclass(frozen=True)
class PreviousExecutionSnapshotV3:
    previous_run_id: str
    request_fingerprint: str
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    engine_snapshots: tuple[PreviousEngineSnapshotV3, ...]


@dataclass(frozen=True)
class EngineRawInputsV3:
    balance_sheet_content: bytes | None = None
    balance_sheet_filename: str | None = None
    income_statement_content: bytes | None = None
    income_statement_filename: str | None = None
    trial_balance_result: OrchestrationJsonObjectV3 | None = None
    prior_period_balance_sheet_facts: object | None = None
    prior_period_income_statement_facts: object | None = None
    prior_period_balance_sheet_result: OrchestrationJsonObjectV3 | None = None
    prior_period_income_statement_result: OrchestrationJsonObjectV3 | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    period_months_covered: int | None = None
    cash_flow_pre_resolved_context: CashFlowPreResolvedContext | None = None


@dataclass(frozen=True)
class OrchestrationRunOptionsV3:
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
class OrchestrationRunRequestV3:
    run_id: str
    correlation_id: str | None
    generated_at: str | None
    requested_outputs: tuple[OrchestrationEngineCodeV3, ...]
    engine_inputs: EngineRawInputsV3
    run_options: OrchestrationRunOptionsV3
    previous_execution_snapshot: PreviousExecutionSnapshotV3 | None = None
    contract_version: str = ORCHESTRATION_CONTRACT_VERSION_V3

    def __post_init__(self) -> None:
        if self.contract_version != ORCHESTRATION_CONTRACT_VERSION_V3:
            raise ValueError("unknown orchestration contract version")
        if type(self.requested_outputs) is not tuple or len(set(self.requested_outputs)) != len(self.requested_outputs):
            raise ValueError("requested outputs must be unique tuple")
        if any(type(item) is not OrchestrationEngineCodeV3 for item in self.requested_outputs):
            raise TypeError("V3 request cannot accept legacy engine codes")
        wants_cash_flow = OrchestrationEngineCodeV3.CASH_FLOW in self.requested_outputs
        if wants_cash_flow != (self.engine_inputs.cash_flow_pre_resolved_context is not None):
            raise ValueError("Cash Flow request requires exact trusted pre-resolved context presence")
        if self.previous_execution_snapshot is not None and type(self.previous_execution_snapshot) is not PreviousExecutionSnapshotV3:
            raise TypeError("V3 request rejects legacy or duck-typed snapshots")


@dataclass(frozen=True)
class OrchestrationRunResultV3:
    run_id: str
    correlation_id: str | None
    generated_at: str | None
    status: RunStatusV3
    engine_records: tuple[PerEngineExecutionRecordV3, ...]
    warnings: tuple[OrchestrationJsonObjectV3, ...]
    structured_errors: tuple[StructuredErrorV3, ...]
    execution_provenance: ExecutionProvenanceV3
    input_version_inventory: OrchestrationJsonObjectV3
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    request_fingerprint: str


@dataclass(frozen=True)
class PerEngineTelemetryV3:
    engine_code: OrchestrationEngineCodeV3
    started_at_offset_ms: float | None
    duration_ms: float | None


@dataclass(frozen=True)
class ExecutionTelemetryV3:
    per_engine: tuple[PerEngineTelemetryV3, ...]
    total_duration_ms: float | None


class TimingProbeV3(Protocol):
    def now(self) -> float: ...


class OrchestratorV3ResultAccessError(TypeError):
    pass


def get_cash_flow_result_v3(result: OrchestrationRunResultV3) -> CashFlowResult | None:
    matches = tuple(r for r in result.engine_records if r.engine_code is OrchestrationEngineCodeV3.CASH_FLOW)
    if len(matches) != 1:
        raise OrchestratorV3ResultAccessError("Cash Flow execution record is missing or duplicated")
    envelope = matches[0].result
    if envelope is None:
        return None
    if envelope.result_kind != "CashFlowResult" or type(envelope.result) is not CashFlowResult:
        raise OrchestratorV3ResultAccessError("Cash Flow result kind/type mismatch")
    return envelope.result
