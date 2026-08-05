"""Framework-free additive Application-v3 contracts for Trend analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar
from uuid import UUID

from app.analysis_application.contracts import (
    AnalysisInputsDTO, AnalysisRunOptionsDTO, ApplicationAuditContextDTO,
    AnalysisErrorCode, ApplicationErrorCategory,
    ApplicationWarningCode,
    ApplicationExecutionStatus, ApplicationScopeDTO, ApplicationStatus,
    CancellationStatus, CompanyMetadataDTO, DashboardRequestDTO,
    ApplicationReportType, ApplicationReportSectionCode,
    PriorPeriodProjectionDTO, RenderContractRequestDTO, ReportRequestDTO,
)


APPLICATION_DTO_SCHEMA_VERSION_V3 = "3.0.0"


class ApplicationEngineCodeV3(str, Enum):
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


class ApplicationTrendSourceRoleV3(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    FINANCIAL_RATIOS = "financial_ratios"


class ApplicationTrendPeriodFamilyV3(str, Enum):
    ANNUAL = "annual"
    MONTHLY_DISCRETE = "monthly_discrete"
    QUARTERLY_DISCRETE = "quarterly_discrete"
    QUARTERLY_CUMULATIVE_YOY = "quarterly_cumulative_yoy"
    TEMPORARY_TAX_CUMULATIVE_YOY = "temporary_tax_cumulative_yoy"
    CUSTOM_DISCRETE = "custom_discrete"


class ApplicationTrendStatusV3(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT_FOR_TREND = "insufficient_for_trend"
    INSUFFICIENT_DATA = "insufficient_data"


class ApplicationFinancialSourceModeV3(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"


class ApplicationFinancialSourceRoleV3(str, Enum):
    PRIMARY_DOCUMENT = "primary_document"
    SUPPORTING_DOCUMENT = "supporting_document"
    PRIMARY_ANALYSIS = "primary_analysis"
    SUPPORTING_ANALYSIS = "supporting_analysis"
    TRIAL_BALANCE_FALLBACK = "trial_balance_fallback"
    PRIOR_PERIOD_REFERENCE = "prior_period_reference"


class ApplicationCashFlowMethodV3(str, Enum):
    INDIRECT = "indirect"


class ApplicationCashFlowPresentationProfileV3(str, Enum):
    TMS_TFRS_2024_INDIRECT_V1 = "tms_tfrs_2024_indirect_v1"
    BANK_CREDIT_V1 = "bank_credit_v1"
    MANAGEMENT_V1 = "management_v1"


@dataclass(frozen=True, repr=False)
class TrendSourceSelectionIntentDTOV3:
    period_id: UUID
    source_role: ApplicationTrendSourceRoleV3
    source_analysis_result_id: UUID

    def __post_init__(self) -> None:
        if type(self.period_id) is not UUID or type(self.source_analysis_result_id) is not UUID:
            raise TypeError("Trend source identifiers must be UUID")
        if type(self.source_role) is not ApplicationTrendSourceRoleV3:
            raise TypeError("Trend source role must be exact enum")


@dataclass(frozen=True, repr=False)
class TrendRequestDTOV3:
    expected_anchor_period_id: UUID
    period_ids: tuple[UUID, ...]
    source_selections: tuple[TrendSourceSelectionIntentDTOV3, ...]
    period_family: ApplicationTrendPeriodFamilyV3
    expected_currency: str
    expected_accounting_basis: str
    expected_accounting_policy_version: str
    expected_metric_registry_version: str
    expected_trend_policy_version: str
    trend_contract_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if type(self.period_ids) is not tuple or len(self.period_ids) < 2 or len(set(self.period_ids)) != len(self.period_ids):
            raise ValueError("Trend request requires a unique immutable multi-period set")
        if self.period_ids[-1] != self.expected_anchor_period_id:
            raise ValueError("Trend anchor must be the final requested period")
        if type(self.source_selections) is not tuple or not self.source_selections:
            raise ValueError("Trend source selections are required")
        if any(type(item) is not TrendSourceSelectionIntentDTOV3 for item in self.source_selections):
            raise TypeError("Trend source selections require exact DTOs")
        keys = tuple((item.period_id, item.source_role) for item in self.source_selections)
        if len(set(keys)) != len(keys) or any(item.period_id not in self.period_ids for item in self.source_selections):
            raise ValueError("Trend source selections are duplicate or outside period set")
        if type(self.period_family) is not ApplicationTrendPeriodFamilyV3:
            raise TypeError("Trend period family must be exact enum")
        if self.trend_contract_version != "1.0.0" or any(not item for item in (
            self.expected_currency, self.expected_accounting_basis,
            self.expected_accounting_policy_version, self.expected_metric_registry_version,
            self.expected_trend_policy_version,
        )):
            raise ValueError("Trend request versions and comparability expectations are required")


@dataclass(frozen=True)
class FinancialSourceReferenceDTOV3:
    role: ApplicationFinancialSourceRoleV3
    source_document_id: UUID | None
    source_analysis_result_id: UUID | None
    source_engine_code: ApplicationEngineCodeV3 | None

    def __post_init__(self):
        if sum(item is not None for item in (self.source_document_id, self.source_analysis_result_id, self.source_engine_code)) != 1:
            raise ValueError("financial source locator must be exact XOR")


# V3 financial/cash/report intents are exact additive copies represented as
# separate immutable types, never aliases to V2 public classes.
@dataclass(frozen=True)
class FinancialSourceIntentDTOV3:
    engine_code: ApplicationEngineCodeV3
    company_id: UUID
    financial_period_id: UUID
    primary_document_id: UUID | None
    source_bindings: tuple[FinancialSourceReferenceDTOV3, ...]
    requested_source_mode: ApplicationFinancialSourceModeV3
    allow_existing_canonical_owner: bool
    expected_existing_owner_id: UUID | None
    provenance_metadata: object
    caller_supplied_business_timestamp: datetime | None

    def __post_init__(self):
        if self.engine_code not in {ApplicationEngineCodeV3.FS_BALANCE_SHEET, ApplicationEngineCodeV3.FS_INCOME_STATEMENT, ApplicationEngineCodeV3.RATIO}:
            raise ValueError("caller cannot assemble this financial owner")
        if self.expected_existing_owner_id is not None and not self.allow_existing_canonical_owner:
            raise ValueError("existing owner assertion requires reuse permission")
        if type(self.source_bindings) is not tuple or any(type(item) is not FinancialSourceReferenceDTOV3 for item in self.source_bindings):
            raise TypeError("financial source bindings require exact DTOs")


@dataclass(frozen=True)
class CashFlowRequestDTOV3:
    method: ApplicationCashFlowMethodV3
    current_period_id: UUID
    expected_prior_period_id: UUID | None
    presentation_profile: ApplicationCashFlowPresentationProfileV3
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    mapping_registry_version: str
    reconciliation_policy_version: str
    cash_flow_contract_version: str = "1.0.0"

    def __post_init__(self):
        if self.method is not ApplicationCashFlowMethodV3.INDIRECT or self.cash_flow_contract_version != "1.0.0":
            raise ValueError("unsupported Cash Flow V3 request")
        if any(not item for item in (self.accounting_policy_version, self.cash_equivalent_policy_version, self.mapping_registry_version, self.reconciliation_policy_version)):
            raise ValueError("Cash Flow V3 policy versions are required")


@dataclass(frozen=True)
class ReportRequestDTOV3:
    report_type: ApplicationReportType
    optional_section_codes: tuple[ApplicationReportSectionCode, ...] | None
    reporting_period_label_tr: str | None
    schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


def _validate_command(command: object, *, previous: bool = False) -> None:
    if getattr(command, "application_contract_version") != APPLICATION_DTO_SCHEMA_VERSION_V3:
        raise ValueError("unknown Application-v3 contract version")
    outputs = getattr(command, "requested_outputs")
    if type(outputs) is not tuple or not outputs or len(set(outputs)) != len(outputs) or any(type(item) is not ApplicationEngineCodeV3 for item in outputs):
        raise ValueError("requested outputs require a unique exact V3 tuple")
    trend_request = getattr(command, "trend_request")
    if (ApplicationEngineCodeV3.MULTI_PERIOD_TREND in outputs) != (trend_request is not None):
        raise ValueError("Trend output and request must be exact iff")
    if trend_request is not None and trend_request.expected_anchor_period_id != getattr(command, "scope").financial_period_id:
        raise ValueError("Trend anchor differs from application scope")
    if previous and (not getattr(command, "scope").previous_run_id or getattr(command, "scope").previous_run_id == getattr(command, "run_id")):
        raise ValueError("resume/retry requires a distinct previous run")


@dataclass(frozen=True, repr=False)
class StartAnalysisCommandV3:
    run_id: str; correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV3, ...]; inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO; source_intents: tuple[FinancialSourceIntentDTOV3, ...]
    cash_flow_request: CashFlowRequestDTOV3 | None; trend_request: TrendRequestDTOV3 | None
    prior_period_projection: PriorPeriodProjectionDTO | None; company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTOV3 | None; dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3
    def __post_init__(self): _validate_command(self)


@dataclass(frozen=True, repr=False)
class ResumeAnalysisCommandV3:
    run_id: str; correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV3, ...]; inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO; source_intents: tuple[FinancialSourceIntentDTOV3, ...]
    cash_flow_request: CashFlowRequestDTOV3 | None; trend_request: TrendRequestDTOV3 | None
    prior_period_projection: PriorPeriodProjectionDTO | None; company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTOV3 | None; dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3
    def __post_init__(self): _validate_command(self, previous=True)


@dataclass(frozen=True, repr=False)
class RetryAnalysisCommandV3:
    run_id: str; correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV3, ...]; inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO; source_intents: tuple[FinancialSourceIntentDTOV3, ...]
    cash_flow_request: CashFlowRequestDTOV3 | None; trend_request: TrendRequestDTOV3 | None
    prior_period_projection: PriorPeriodProjectionDTO | None; company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTOV3 | None; dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3
    def __post_init__(self): _validate_command(self, previous=True)


@dataclass(frozen=True, repr=False)
class CancelAnalysisCommandV3:
    run_id: str; correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True, repr=False)
class GetAnalysisStatusQueryV3:
    run_id: str; correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True, repr=False)
class GetAnalysisResultQueryV3:
    run_id: str; correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str; include_payloads: bool
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True, repr=False)
class GetExecutionDetailQueryV3:
    run_id: str; correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str
    engine_code: ApplicationEngineCodeV3; include_payload: bool
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True, repr=False)
class ListAnalysisHistoryQueryV3:
    correlation_id: str; generated_at: datetime; scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO; authorization_context_reference: str
    cursor: str | None; limit: int
    application_contract_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class ApplicationTrendFieldDTOV3:
    name: str
    value: object


@dataclass(frozen=True)
class ApplicationTrendIssueDTOV3:
    issue_type: str
    fields: tuple[ApplicationTrendFieldDTOV3, ...]


@dataclass(frozen=True)
class ApplicationTrendObservationDTOV3:
    fields: tuple[ApplicationTrendFieldDTOV3, ...]


@dataclass(frozen=True)
class ApplicationTrendTransitionDTOV3:
    fields: tuple[ApplicationTrendFieldDTOV3, ...]


@dataclass(frozen=True)
class ApplicationTrendSegmentSummaryDTOV3:
    fields: tuple[ApplicationTrendFieldDTOV3, ...]


@dataclass(frozen=True)
class ApplicationTrendMetricResultDTOV3:
    metric_code: str
    status: ApplicationTrendStatusV3
    observations: tuple[ApplicationTrendObservationDTOV3, ...]
    transitions: tuple[ApplicationTrendTransitionDTOV3, ...]
    fields: tuple[ApplicationTrendFieldDTOV3, ...]


@dataclass(frozen=True)
class ApplicationTrendCompletenessDTOV3:
    fields: tuple[ApplicationTrendFieldDTOV3, ...]


@dataclass(frozen=True)
class ApplicationTrendResultDTOV3:
    company_id: UUID
    anchor_period_id: UUID
    status: ApplicationTrendStatusV3
    nominal_analysis_disclosure: tuple[ApplicationTrendFieldDTOV3, ...]
    metrics: tuple[ApplicationTrendMetricResultDTOV3, ...]
    completeness: ApplicationTrendCompletenessDTOV3
    data_quality: tuple[ApplicationTrendFieldDTOV3, ...]
    source_references: tuple[tuple[ApplicationTrendFieldDTOV3, ...], ...]
    lineage_references: tuple[tuple[ApplicationTrendFieldDTOV3, ...], ...]
    warnings: tuple[ApplicationTrendIssueDTOV3, ...]
    errors: tuple[ApplicationTrendIssueDTOV3, ...]
    canonical_digest: str
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class AnalysisExecutionDTOV3:
    engine_code: ApplicationEngineCodeV3
    status: ApplicationExecutionStatus
    inner_status: str | None
    engine_schema_version: str | None
    engine_model_version: str | None
    input_fingerprint: str
    trend_projection: ApplicationTrendResultDTOV3 | None


@dataclass(frozen=True)
class AnalysisCommandResultDTOV3:
    run_id: str; status: ApplicationStatus; request_fingerprint: str
    terminal_content_digest: str; scope: ApplicationScopeDTO
    executions: tuple[AnalysisExecutionDTOV3, ...]; persisted_at: datetime
    idempotent_replay: bool; recovery_query_run_id: str
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class AnalysisRunSummaryDTOV3:
    run_id: str; status: ApplicationStatus; scope: ApplicationScopeDTO
    requested_outputs: tuple[ApplicationEngineCodeV3, ...]; finalized_at: datetime
    previous_run_id: str | None; application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class AnalysisRunStatusDTOV3:
    run_id: str; status: ApplicationStatus; scope: ApplicationScopeDTO; finalized_at: datetime
    engine_statuses: tuple[tuple[ApplicationEngineCodeV3, ApplicationExecutionStatus], ...]
    terminal: bool; application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class AnalysisResultDTOV3:
    run_id: str; status: ApplicationStatus; scope: ApplicationScopeDTO; request_fingerprint: str
    executions: tuple[AnalysisExecutionDTOV3, ...]; warnings: tuple[object, ...]
    structured_errors: tuple[object, ...]; execution_plan_version: str
    orchestration_schema_version: str; orchestration_model_version: str; finalized_at: datetime
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class AnalysisHistoryPageDTOV3:
    items: tuple[AnalysisRunSummaryDTOV3, ...]; next_cursor: str | None
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class CancellationResultDTOV3:
    run_id: str; status: CancellationStatus; scope: ApplicationScopeDTO; requested_at: datetime
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class AnalysisErrorDTOV3:
    code: AnalysisErrorCode; category: ApplicationErrorCategory; message: str; retryable: bool; correlation_id: str
    safe_metadata: object; application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3


@dataclass(frozen=True)
class AnalysisWarningDTOV3:
    code: ApplicationWarningCode
    message: str
    retryable: bool


T = TypeVar("T")


@dataclass(frozen=True)
class ApplicationOutcomeV3(Generic[T]):
    success: bool; value: T | None; error: AnalysisErrorDTOV3 | None
    warnings: tuple[object, ...]; correlation_id: str
    application_schema_version: str = APPLICATION_DTO_SCHEMA_VERSION_V3
    def __post_init__(self):
        if self.success != (self.value is not None and self.error is None):
            raise ValueError("ApplicationOutcomeV3 success/value/error invariant failed")
