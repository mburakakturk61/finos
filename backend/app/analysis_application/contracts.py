"""Immutable, API-independent application contracts for analysis use cases."""

from __future__ import annotations

import enum
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeAlias, TypeVar

APPLICATION_DTO_SCHEMA_VERSION = "1.0.0"


class ApplicationEngineCode(str, enum.Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    RATIO = "ratio"
    BENCHMARK = "benchmark"
    HEALTH_SCORE = "health_score"
    CREDIT_SCORE = "credit_score"
    RECOMMENDATION = "recommendation"
    EXECUTIVE_REPORT = "executive_report"
    DASHBOARD = "dashboard"
    RENDER_CONTRACT = "render_contract"


class ApplicationOperationKind(str, enum.Enum):
    START = "START"
    RESUME = "RESUME"
    RETRY = "RETRY"


class ApplicationOriginalOperation(str, enum.Enum):
    START = "START"
    RESUME = "RESUME"


class ApplicationStatus(str, enum.Enum):
    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApplicationExecutionStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"


class CancellationStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    NOT_ACTIVE = "NOT_ACTIVE"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    NOT_FOUND = "NOT_FOUND"


class PayloadOwnerType(str, enum.Enum):
    FINANCIAL_ANALYSIS_RESULT = "FINANCIAL_ANALYSIS_RESULT"
    ORCHESTRATION_ARTIFACT = "ORCHESTRATION_ARTIFACT"


class FinancialSourceMode(str, enum.Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"


class FinancialSourceRole(str, enum.Enum):
    PRIMARY_DOCUMENT = "primary_document"
    SUPPORTING_DOCUMENT = "supporting_document"
    PRIMARY_ANALYSIS = "primary_analysis"
    SUPPORTING_ANALYSIS = "supporting_analysis"
    TRIAL_BALANCE_FALLBACK = "trial_balance_fallback"
    PRIOR_PERIOD_REFERENCE = "prior_period_reference"


class FinancialStatementKind(str, enum.Enum):
    BALANCE_SHEET = "BALANCE_SHEET"
    INCOME_STATEMENT = "INCOME_STATEMENT"


class ApplicationReportType(str, enum.Enum):
    CFO_EXECUTIVE_REPORT = "cfo_executive_report"
    BANK_CREDIT_ALLOCATION_REPORT = "bank_credit_allocation_report"
    BOARD_OF_DIRECTORS_REPORT = "board_of_directors_report"
    INVESTOR_REPORT = "investor_report"
    MANAGEMENT_SUMMARY = "management_summary"
    SWOT_REPORT = "swot_report"
    PERIOD_COMPARISON_REPORT = "period_comparison_report"


class ApplicationReportSectionCode(str, enum.Enum):
    SEC_COVER_PAGE = "SEC_COVER_PAGE"
    SEC_FINANCIAL_STATEMENTS_SUMMARY = "SEC_FINANCIAL_STATEMENTS_SUMMARY"
    SEC_RATIO_ANALYSIS_TABLE = "SEC_RATIO_ANALYSIS_TABLE"
    SEC_BENCHMARK_COMPARISON = "SEC_BENCHMARK_COMPARISON"
    SEC_HEALTH_SCORE_BREAKDOWN = "SEC_HEALTH_SCORE_BREAKDOWN"
    SEC_CREDIT_SCORE_BREAKDOWN = "SEC_CREDIT_SCORE_BREAKDOWN"
    SEC_BANKING_READINESS = "SEC_BANKING_READINESS"
    SEC_BANK_COLLATERAL_AND_DATA_GAPS = "SEC_BANK_COLLATERAL_AND_DATA_GAPS"
    SEC_RECOMMENDATIONS = "SEC_RECOMMENDATIONS"
    SEC_BOARD_DECISION_ITEMS = "SEC_BOARD_DECISION_ITEMS"
    SEC_RISK_FLAGS = "SEC_RISK_FLAGS"
    SEC_INVESTOR_KPI_SUMMARY = "SEC_INVESTOR_KPI_SUMMARY"
    SEC_PERIOD_COMPARISON_ANALYSIS = "SEC_PERIOD_COMPARISON_ANALYSIS"
    SEC_EXECUTIVE_SUMMARY = "SEC_EXECUTIVE_SUMMARY"
    SEC_SWOT = "SEC_SWOT"
    SEC_METHODOLOGY_APPENDIX = "SEC_METHODOLOGY_APPENDIX"
    SEC_DISCLAIMER_BLOCK = "SEC_DISCLAIMER_BLOCK"
    SEC_CONFIDENCE_AND_DATA_QUALITY = "SEC_CONFIDENCE_AND_DATA_QUALITY"


class ApplicationDashboardType(str, enum.Enum):
    EXECUTIVE_DASHBOARD = "executive_dashboard"
    RISK_DASHBOARD = "risk_dashboard"


class ApplicationRenderMedium(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"


class ApplicationReportBlockType(str, enum.Enum):
    KPI_CARD = "kpi_card"
    TABLE = "table"
    BULLET_LIST = "bullet_list"
    PARAGRAPH = "paragraph"
    CHART_DATA = "chart_data"
    BADGE = "badge"


class ExecutionCategory(str, enum.Enum):
    ENGINE_CONTRACT_VIOLATION = "engine_contract_violation"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VERSION_INCOMPATIBLE_ON_REUSE = "version_incompatible_on_reuse"
    FINGERPRINT_MISMATCH_ON_REUSE = "fingerprint_mismatch_on_reuse"
    INVALID_RUN_REQUEST = "invalid_run_request"
    CANCELLED = "cancelled"


class FinancialComputationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisErrorCode(str, enum.Enum):
    INVALID_COMMAND = "INVALID_COMMAND"
    INVALID_QUERY = "INVALID_QUERY"
    UNAUTHORIZED = "UNAUTHORIZED"
    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"
    AUTHORIZATION_PROVIDER_UNAVAILABLE = "AUTHORIZATION_PROVIDER_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    RUN_ID_CONFLICT = "RUN_ID_CONFLICT"
    FINGERPRINT_CONFLICT = "FINGERPRINT_CONFLICT"
    SCOPE_CLAIM_CONFLICT = "SCOPE_CLAIM_CONFLICT"
    SCOPE_CLAIM_UNAVAILABLE = "SCOPE_CLAIM_UNAVAILABLE"
    SCOPE_FINALIZATION_FAILED = "SCOPE_FINALIZATION_FAILED"
    RESUME_SOURCE_INVALID = "RESUME_SOURCE_INVALID"
    RESUME_SOURCE_CORRUPTED = "RESUME_SOURCE_CORRUPTED"
    RESUME_SOURCE_UNAUTHORIZED = "RESUME_SOURCE_UNAUTHORIZED"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"
    PERSISTENCE_INTEGRITY_ERROR = "PERSISTENCE_INTEGRITY_ERROR"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    DTO_PROJECTION_FAILED = "DTO_PROJECTION_FAILED"
    SECURITY_AUDIT_FAILED = "SECURITY_AUDIT_FAILED"
    INTERNAL_INVARIANT_BREACH = "INTERNAL_INVARIANT_BREACH"


class ApplicationErrorCategory(str, enum.Enum):
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INTEGRITY = "integrity"
    DEPENDENCY = "dependency"
    EXECUTION = "execution"
    RECOVERY = "recovery"
    SECURITY_DEPENDENCY = "security_dependency"
    INTERNAL = "internal"


class ApplicationWarningCode(str, enum.Enum):
    SECURITY_AUDIT_POST_COMMIT_FAILED = "SECURITY_AUDIT_POST_COMMIT_FAILED"


class RunScopeClaimStatus(str, enum.Enum):
    CLAIMED = "CLAIMED"
    FINALIZED = "FINALIZED"


class ApplicationEventType(str, enum.Enum):
    START_REQUESTED = "START_REQUESTED"
    RESUME_REQUESTED = "RESUME_REQUESTED"
    RETRY_REQUESTED = "RETRY_REQUESTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    AUTHORIZATION_GRANTED = "AUTHORIZATION_GRANTED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    SCOPE_MISMATCH_DETECTED = "SCOPE_MISMATCH_DETECTED"
    RUN_ID_CONFLICT_DETECTED = "RUN_ID_CONFLICT_DETECTED"
    RESUME_SOURCE_ACCEPTED = "RESUME_SOURCE_ACCEPTED"
    RESUME_SOURCE_REJECTED = "RESUME_SOURCE_REJECTED"
    TERMINAL_RUN_PERSISTED = "TERMINAL_RUN_PERSISTED"
    RESULT_READ = "RESULT_READ"
    HISTORY_READ = "HISTORY_READ"


ApplicationJsonScalar: TypeAlias = None | bool | str | int | Decimal | float
ApplicationJsonValue: TypeAlias = ApplicationJsonScalar | tuple["ApplicationJsonValue", ...] | dict[str, "ApplicationJsonValue"]


def validate_application_json(value: object) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite decimals are not allowed.")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite floats are not allowed.")
        return
    if isinstance(value, tuple):
        for item in value:
            validate_application_json(item)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Application map keys must be strings.")
        if "$application_type" in value:
            if set(value) != {"$application_type", "value"}:
                raise ValueError("Tagged date/time maps have an exact field set.")
            tag, encoded = value["$application_type"], value["value"]
            if tag == "date":
                if not isinstance(encoded, str):
                    raise ValueError("Tagged date value must be a string.")
                date.fromisoformat(encoded)
            elif tag == "datetime":
                if not isinstance(encoded, str):
                    raise ValueError("Tagged datetime value must be a string.")
                parsed = datetime.fromisoformat(encoded)
                if not _aware(parsed):
                    raise ValueError("Tagged datetime must include an offset.")
            else:
                raise ValueError("Unknown application value tag.")
        for item in value.values():
            validate_application_json(item)
        return
    raise ValueError("Unsupported application JSON value.")


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class ApplicationScopeDTO:
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    tenant_id: str | None
    operation_kind: ApplicationOperationKind
    original_operation: ApplicationOriginalOperation
    previous_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.operation_kind is ApplicationOperationKind.START and (
            self.original_operation is not ApplicationOriginalOperation.START or self.previous_run_id
        ):
            raise ValueError("Start scope is invalid.")
        if self.operation_kind is not ApplicationOperationKind.START and not self.previous_run_id:
            raise ValueError("Resume and retry scopes require previous_run_id.")
        if self.operation_kind is ApplicationOperationKind.RESUME and self.original_operation is not ApplicationOriginalOperation.RESUME:
            raise ValueError("Resume scope original operation is invalid.")


@dataclass(frozen=True)
class ApplicationAuditContextDTO:
    actor_id: str
    caller_type: str
    request_source: str
    purpose: str
    client_request_id: str | None = None
    ip_hash: str | None = None
    user_agent_hash: str | None = None
    attributes: dict[str, ApplicationJsonValue] | None = None

    def __post_init__(self) -> None:
        if not all((self.actor_id, self.caller_type, self.request_source, self.purpose)):
            raise ValueError("Audit identity fields are required.")
        validate_application_json(self.attributes or {})


@dataclass(frozen=True)
class FinancialSourceReferenceDTO:
    role: FinancialSourceRole
    source_document_id: uuid.UUID | None = None
    source_analysis_result_id: uuid.UUID | None = None
    source_engine_code: ApplicationEngineCode | None = None

    def __post_init__(self) -> None:
        if sum(value is not None for value in (self.source_document_id, self.source_analysis_result_id, self.source_engine_code)) != 1:
            raise ValueError("Exactly one financial source reference is required.")
        if self.role in (FinancialSourceRole.PRIMARY_DOCUMENT, FinancialSourceRole.SUPPORTING_DOCUMENT):
            if self.source_document_id is None:
                raise ValueError("Document roles require a document source.")
        elif self.role is not FinancialSourceRole.PRIOR_PERIOD_REFERENCE and self.source_document_id is not None:
            raise ValueError("Analysis roles require an analysis-result or same-run engine source.")


@dataclass(frozen=True)
class FinancialSourceIntentDTO:
    engine_code: ApplicationEngineCode
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    primary_document_id: uuid.UUID | None
    source_bindings: tuple[FinancialSourceReferenceDTO, ...]
    requested_source_mode: FinancialSourceMode
    allow_existing_canonical_owner: bool
    expected_existing_owner_id: uuid.UUID | None
    provenance_metadata: dict[str, ApplicationJsonValue]
    caller_supplied_business_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.engine_code not in FINANCIAL_OWNER_ENGINE_CODES:
            raise ValueError("Engine does not own a financial result.")
        if self.expected_existing_owner_id is not None and not self.allow_existing_canonical_owner:
            raise ValueError("Existing-owner intent is invalid.")
        if self.caller_supplied_business_timestamp and not _aware(self.caller_supplied_business_timestamp):
            raise ValueError("Business timestamp must be timezone-aware.")
        validate_application_json(self.provenance_metadata)
        keys = tuple(
            (item.role, item.source_document_id, item.source_analysis_result_id, item.source_engine_code)
            for item in self.source_bindings
        )
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate financial source binding.")
        primary = tuple(item for item in self.source_bindings if item.role is FinancialSourceRole.PRIMARY_DOCUMENT)
        if (self.primary_document_id is None and primary) or (
            self.primary_document_id is not None and (len(primary) != 1 or primary[0].source_document_id != self.primary_document_id)
        ):
            raise ValueError("Primary document intent is inconsistent.")


FINANCIAL_OWNER_ENGINE_CODES = frozenset({
    ApplicationEngineCode.FS_BALANCE_SHEET,
    ApplicationEngineCode.FS_INCOME_STATEMENT,
    ApplicationEngineCode.RATIO,
})


@dataclass(frozen=True)
class AnalysisInputsDTO:
    balance_sheet_content: bytes | None = None
    balance_sheet_filename: str | None = None
    income_statement_content: bytes | None = None
    income_statement_filename: str | None = None
    trial_balance_result: dict[str, ApplicationJsonValue] | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    period_months_covered: int | None = None


@dataclass(frozen=True)
class AnalysisRunOptionsDTO:
    industry_code: str | None = None
    company_size_bucket: str | None = None
    engine_segmentation_tenant_id: str | None = None
    reporting_period_label_tr: str | None = None
    optional_report_sections: tuple[str, ...] | None = None
    currency_display_policy: str | None = None
    locale: str = "tr-TR"


BALANCE_SHEET_FACT_KEYS = frozenset({
    "current_assets", "non_current_assets", "total_assets",
    "short_term_liabilities", "long_term_liabilities", "equity",
    "total_liabilities_and_equity", "cash_and_equivalents", "inventory",
    "trade_receivables", "trade_payables",
})
INCOME_STATEMENT_FACT_KEYS = frozenset({
    "gross_sales", "sales_deductions", "net_sales", "cost_of_sales",
    "gross_profit", "operating_expenses", "other_operating_income",
    "other_operating_expenses", "operating_profit",
    "depreciation_and_amortization", "ebit", "ebitda",
    "financing_expenses", "extraordinary_income", "extraordinary_expenses",
    "profit_before_tax", "net_profit",
})


@dataclass(frozen=True)
class PriorPeriodFactsDTO:
    statement_kind: FinancialStatementKind
    values: dict[str, Decimal | None]
    schema_version: str = APPLICATION_DTO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        allowed = (
            BALANCE_SHEET_FACT_KEYS
            if self.statement_kind is FinancialStatementKind.BALANCE_SHEET
            else INCOME_STATEMENT_FACT_KEYS
        )
        if frozenset(self.values) != allowed:
            raise ValueError("Prior-period facts must contain the exact closed key set.")


@dataclass(frozen=True)
class PriorPeriodProjectionDTO:
    balance_sheet_facts: PriorPeriodFactsDTO | None = None
    income_statement_facts: PriorPeriodFactsDTO | None = None
    balance_sheet_result: dict[str, ApplicationJsonValue] | None = None
    income_statement_result: dict[str, ApplicationJsonValue] | None = None


@dataclass(frozen=True)
class CompanyMetadataDTO:
    company_name: str
    industry_label_tr: str | None = None
    company_size_label_tr: str | None = None
    fiscal_year_label_tr: str | None = None
    tax_id_masked: str | None = None
    schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class ReportRequestDTO:
    report_type: ApplicationReportType
    optional_section_codes: tuple[ApplicationReportSectionCode, ...] | None = None
    reporting_period_label_tr: str | None = None
    schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class DashboardRequestDTO:
    dashboard_type: ApplicationDashboardType
    schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class RenderContractRequestDTO:
    render_medium: ApplicationRenderMedium
    supported_block_types: tuple[ApplicationReportBlockType, ...]
    supports_landscape: bool
    supports_page_break_hints: bool
    supports_chart_placeholders: bool
    max_table_columns_before_overflow_risk: int | None
    schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class _ExecutionCommand:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCode, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTO, ...]
    prior_period_projection: PriorPeriodProjectionDTO | None = None
    company_metadata: CompanyMetadataDTO | None = None
    report_request: ReportRequestDTO | None = None
    dashboard_request: DashboardRequestDTO | None = None
    render_contract_request: RenderContractRequestDTO | None = None
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.run_id or not self.correlation_id or not _aware(self.generated_at):
            raise ValueError("Command identity/time is invalid.")
        if self.application_contract_version != APPLICATION_DTO_SCHEMA_VERSION or not self.requested_outputs:
            raise ValueError("Command contract is invalid.")
        if len(set(self.requested_outputs)) != len(self.requested_outputs):
            raise ValueError("Requested outputs must be unique.")
        intents = {item.engine_code: item for item in self.source_intents}
        if len(intents) != len(self.source_intents):
            raise ValueError("Financial source intents must be unique by engine.")
        for item in self.source_intents:
            if (item.company_id, item.financial_period_id) != (self.scope.company_id, self.scope.financial_period_id):
                raise ValueError("Financial source intent scope mismatch.")


@dataclass(frozen=True)
class StartAnalysisCommand(_ExecutionCommand):
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.scope.operation_kind is not ApplicationOperationKind.START:
            raise ValueError("Start command requires START scope.")


@dataclass(frozen=True)
class ResumeAnalysisCommand(_ExecutionCommand):
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.scope.operation_kind is not ApplicationOperationKind.RESUME or self.scope.previous_run_id == self.run_id:
            raise ValueError("Resume command scope is invalid.")


@dataclass(frozen=True)
class RetryAnalysisCommand(_ExecutionCommand):
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.scope.operation_kind is not ApplicationOperationKind.RETRY or self.scope.previous_run_id == self.run_id:
            raise ValueError("Retry command scope is invalid.")


@dataclass(frozen=True)
class CancelAnalysisCommand:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.run_id or not self.correlation_id or not _aware(self.generated_at):
            raise ValueError("Cancel command identity/time is invalid.")
        if not self.authorization_context_reference or self.application_contract_version != APPLICATION_DTO_SCHEMA_VERSION:
            raise ValueError("Cancel command contract is invalid.")


@dataclass(frozen=True)
class _RunQuery:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.run_id or not self.correlation_id or not _aware(self.generated_at):
            raise ValueError("Query identity/time is invalid.")
        if not self.authorization_context_reference or self.application_contract_version != APPLICATION_DTO_SCHEMA_VERSION:
            raise ValueError("Query contract is invalid.")


@dataclass(frozen=True)
class GetAnalysisStatusQuery(_RunQuery):
    pass


@dataclass(frozen=True)
class GetAnalysisResultQuery(_RunQuery):
    include_payloads: bool = False


@dataclass(frozen=True)
class GetExecutionDetailQuery(_RunQuery):
    engine_code: ApplicationEngineCode = ApplicationEngineCode.FS_BALANCE_SHEET
    include_payload: bool = False


@dataclass(frozen=True)
class ListAnalysisHistoryQuery:
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    cursor: str | None = None
    limit: int = 50
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.correlation_id or not _aware(self.generated_at):
            raise ValueError("History query identity/time is invalid.")
        if not self.authorization_context_reference or self.application_contract_version != APPLICATION_DTO_SCHEMA_VERSION:
            raise ValueError("History query contract is invalid.")
        if self.limit < 1 or self.limit > 200:
            raise ValueError("History limit must be between 1 and 200.")


@dataclass(frozen=True)
class ApplicationPayloadReferenceDTO:
    owner_type: PayloadOwnerType
    result_kind: str
    canonical_digest: str
    financial_analysis_result_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    artifact_serializer_schema_version: str | None = None

    def __post_init__(self) -> None:
        if self.owner_type is PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT:
            if self.financial_analysis_result_id is None or self.artifact_id is not None or self.artifact_serializer_schema_version is not None:
                raise ValueError("Invalid financial payload reference.")
        elif self.artifact_id is None or self.financial_analysis_result_id is not None or not self.artifact_serializer_schema_version:
            raise ValueError("Invalid artifact payload reference.")


@dataclass(frozen=True)
class ApplicationProjectedErrorDTO:
    category: ExecutionCategory
    engine_code: ApplicationEngineCode | None
    message: str


@dataclass(frozen=True)
class ApplicationPayloadEnvelopeDTO:
    payload_reference: ApplicationPayloadReferenceDTO
    computation_status: FinancialComputationStatus
    source_mode: FinancialSourceMode | None
    result_payload: ApplicationJsonValue | None
    structured_error: ApplicationProjectedErrorDTO | None
    message: str | None
    inner_status: str | None
    trial_balance_usage: ApplicationJsonValue | None
    provenance_source_references: tuple[str, ...]
    engine_schema_version: str | None
    engine_model_version: str | None
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_application_json(self.result_payload)
        validate_application_json(self.trial_balance_usage)


@dataclass(frozen=True)
class AnalysisErrorDTO:
    code: AnalysisErrorCode
    category: ApplicationErrorCategory
    message: str
    retryable: bool
    correlation_id: str
    safe_metadata: dict[str, ApplicationJsonValue]
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class AnalysisWarningDTO:
    code: ApplicationWarningCode
    message: str
    retryable: bool


@dataclass(frozen=True)
class AnalysisExecutionDTO:
    engine_code: ApplicationEngineCode
    status: ApplicationExecutionStatus
    inner_status: str | None
    engine_schema_version: str | None
    engine_model_version: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    error: ApplicationProjectedErrorDTO | None = None
    dependency_engine_codes: tuple[ApplicationEngineCode, ...] = ()
    payload: ApplicationPayloadEnvelopeDTO | None = None
    reused_from_run_id: str | None = None
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class AnalysisCommandResultDTO:
    run_id: str
    status: ApplicationStatus
    request_fingerprint: str
    terminal_content_digest: str
    scope: ApplicationScopeDTO
    executions: tuple[AnalysisExecutionDTO, ...]
    persisted_at: datetime
    idempotent_replay: bool
    recovery_query_run_id: str
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class AnalysisRunSummaryDTO:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    requested_outputs: tuple[ApplicationEngineCode, ...]
    finalized_at: datetime
    previous_run_id: str | None
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class AnalysisRunStatusDTO:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    finalized_at: datetime
    engine_statuses: tuple[tuple[ApplicationEngineCode, ApplicationExecutionStatus], ...]
    terminal: bool = True
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class AnalysisResultDTO:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    request_fingerprint: str
    executions: tuple[AnalysisExecutionDTO, ...]
    warnings: tuple[ApplicationJsonValue, ...]
    structured_errors: tuple[ApplicationProjectedErrorDTO, ...]
    execution_plan_version: str
    orchestration_schema_version: str
    orchestration_model_version: str
    finalized_at: datetime
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class AnalysisHistoryPageDTO:
    items: tuple[AnalysisRunSummaryDTO, ...]
    next_cursor: str | None
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


@dataclass(frozen=True)
class CancellationResultDTO:
    run_id: str
    status: CancellationStatus
    scope: ApplicationScopeDTO
    requested_at: datetime
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION


T = TypeVar("T")


@dataclass(frozen=True)
class ApplicationOutcome(Generic[T]):
    success: bool
    value: T | None
    error: AnalysisErrorDTO | None
    warnings: tuple[AnalysisWarningDTO, ...]
    correlation_id: str
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.success != (self.value is not None and self.error is None):
            raise ValueError("ApplicationOutcome success/value/error invariant failed.")
        if not self.success and (self.value is not None or self.error is None):
            raise ValueError("ApplicationOutcome failure invariant failed.")
