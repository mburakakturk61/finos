"""Strict versioned wire contracts for analysis-run endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.analysis_application.contracts import (
    ApplicationDashboardType,
    ApplicationEngineCode,
    ApplicationOriginalOperation,
    ApplicationRenderMedium,
    ApplicationReportBlockType,
    ApplicationReportSectionCode,
    ApplicationReportType,
    FinancialSourceMode,
    FinancialSourceRole,
    FinancialStatementKind,
)


class _StrictModel(BaseModel):
    # HTTP JSON has string encodings for UUID/datetime/Decimal/Enum. Pydantic
    # parses only those declared encodings; unknown fields remain forbidden.
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisInputsRequestV1(_StrictModel):
    balance_sheet_document_id: uuid.UUID | None = None
    income_statement_document_id: uuid.UUID | None = None
    trial_balance_analysis_result_id: uuid.UUID | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    period_months_covered: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start_date and self.period_end_date and self.period_start_date > self.period_end_date:
            raise ValueError("Period start must not be after period end.")
        return self


class AnalysisRunOptionsRequestV1(_StrictModel):
    industry_code: str | None = None
    company_size_bucket: str | None = None
    engine_segmentation_tenant_id: str | None = None
    reporting_period_label_tr: str | None = None
    optional_report_sections: tuple[str, ...] | None = None
    currency_display_policy: str | None = None
    locale: str = "tr-TR"


class FinancialSourceReferenceRequestV1(_StrictModel):
    role: FinancialSourceRole
    source_document_id: uuid.UUID | None = None
    source_analysis_result_id: uuid.UUID | None = None
    source_engine_code: ApplicationEngineCode | None = None

    @model_validator(mode="after")
    def exact_source(self):
        if sum(value is not None for value in (
            self.source_document_id, self.source_analysis_result_id, self.source_engine_code,
        )) != 1:
            raise ValueError("Exactly one source reference is required.")
        return self


class FinancialSourceIntentRequestV1(_StrictModel):
    engine_code: ApplicationEngineCode
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    primary_document_id: uuid.UUID | None = None
    source_bindings: tuple[FinancialSourceReferenceRequestV1, ...]
    requested_source_mode: FinancialSourceMode
    allow_existing_canonical_owner: bool
    expected_existing_owner_id: uuid.UUID | None = None
    provenance_metadata: dict[str, Any] = Field(default_factory=dict)
    caller_supplied_business_timestamp: datetime | None = None


class PriorPeriodFactsRequestV1(_StrictModel):
    statement_kind: FinancialStatementKind
    values: dict[str, Decimal | None]
    schema_version: Literal["1.0.0"] = "1.0.0"


class PriorPeriodProjectionRequestV1(_StrictModel):
    balance_sheet_facts: PriorPeriodFactsRequestV1 | None = None
    income_statement_facts: PriorPeriodFactsRequestV1 | None = None
    balance_sheet_result: dict[str, Any] | None = None
    income_statement_result: dict[str, Any] | None = None


class CompanyMetadataRequestV1(_StrictModel):
    company_name: str = Field(min_length=1, max_length=512)
    industry_label_tr: str | None = None
    company_size_label_tr: str | None = None
    fiscal_year_label_tr: str | None = None
    tax_id_masked: str | None = None
    schema_version: Literal["1.0.0"] = "1.0.0"


class ReportRequestV1(_StrictModel):
    report_type: ApplicationReportType
    optional_section_codes: tuple[ApplicationReportSectionCode, ...] | None = None
    reporting_period_label_tr: str | None = None
    schema_version: Literal["1.0.0"] = "1.0.0"


class DashboardRequestV1(_StrictModel):
    dashboard_type: ApplicationDashboardType
    schema_version: Literal["1.0.0"] = "1.0.0"


class RenderContractRequestV1(_StrictModel):
    render_medium: ApplicationRenderMedium
    supported_block_types: tuple[ApplicationReportBlockType, ...]
    supports_landscape: bool
    supports_page_break_hints: bool
    supports_chart_placeholders: bool
    max_table_columns_before_overflow_risk: int | None = Field(default=None, ge=1)
    schema_version: Literal["1.0.0"] = "1.0.0"


class _ExecutionRequestV1(_StrictModel):
    generated_at: datetime
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    purpose: str = Field(min_length=1, max_length=128)
    requested_outputs: tuple[ApplicationEngineCode, ...] = Field(min_length=1)
    inputs: AnalysisInputsRequestV1
    run_options: AnalysisRunOptionsRequestV1
    source_intents: tuple[FinancialSourceIntentRequestV1, ...]
    prior_period_projection: PriorPeriodProjectionRequestV1 | None = None
    company_metadata: CompanyMetadataRequestV1 | None = None
    report_request: ReportRequestV1 | None = None
    dashboard_request: DashboardRequestV1 | None = None
    render_contract_request: RenderContractRequestV1 | None = None
    api_contract_version: Literal["1.0.0"] = "1.0.0"
    application_contract_version: Literal["1.0.0"] = "1.0.0"

    @field_validator("generated_at")
    @classmethod
    def aware_generated_at(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def unique_contract_values(self):
        if len(set(self.requested_outputs)) != len(self.requested_outputs):
            raise ValueError("Requested outputs must be unique.")
        if len({item.engine_code for item in self.source_intents}) != len(self.source_intents):
            raise ValueError("Source intents must be unique by engine.")
        if any((item.company_id, item.financial_period_id) != (self.company_id, self.financial_period_id) for item in self.source_intents):
            raise ValueError("Source intent scope mismatch.")
        return self


class StartAnalysisRequestV1(_ExecutionRequestV1):
    pass


class ResumeAnalysisRequestV1(_ExecutionRequestV1):
    pass


class RetryAnalysisRequestV1(_ExecutionRequestV1):
    original_operation: ApplicationOriginalOperation


class ApiScopeResponseV1(_StrictModel):
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    tenant_id: str | None
    operation_kind: str
    original_operation: str
    previous_run_id: str | None


class ApiErrorV1(_StrictModel):
    code: str
    category: str
    message: str
    retryable: bool
    correlation_id: str
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class ApiWarningV1(_StrictModel):
    code: str
    message: str
    retryable: bool


class AnalysisExecutionResponseV1(_StrictModel):
    engine_code: str
    status: str
    inner_status: str | None
    engine_schema_version: str | None
    engine_model_version: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    error: dict[str, Any] | None
    dependency_engine_codes: tuple[str, ...]
    payload: dict[str, Any] | None
    reused_from_run_id: str | None
    application_schema_version: str


class AnalysisCommandResponseV1(_StrictModel):
    run_id: str
    status: str
    request_fingerprint: str
    terminal_content_digest: str
    scope: ApiScopeResponseV1
    executions: tuple[AnalysisExecutionResponseV1, ...]
    persisted_at: datetime
    idempotent_replay: bool
    recovery_query_run_id: str
    application_schema_version: str


class CancellationResponseV1(_StrictModel):
    run_id: str
    status: str
    scope: ApiScopeResponseV1
    requested_at: datetime
    application_schema_version: str


class AnalysisRunStatusResponseV1(_StrictModel):
    run_id: str
    status: str
    scope: ApiScopeResponseV1
    finalized_at: datetime
    engine_statuses: tuple[tuple[str, str], ...]
    terminal: bool
    application_schema_version: str


class AnalysisResultResponseV1(_StrictModel):
    run_id: str
    status: str
    scope: ApiScopeResponseV1
    request_fingerprint: str
    executions: tuple[AnalysisExecutionResponseV1, ...]
    warnings: tuple[Any, ...]
    structured_errors: tuple[dict[str, Any], ...]
    execution_plan_version: str
    orchestration_schema_version: str
    orchestration_model_version: str
    finalized_at: datetime
    application_schema_version: str


class AnalysisRunSummaryResponseV1(_StrictModel):
    run_id: str
    status: str
    scope: ApiScopeResponseV1
    requested_outputs: tuple[str, ...]
    finalized_at: datetime
    previous_run_id: str | None
    application_schema_version: str


class AnalysisHistoryPageResponseV1(_StrictModel):
    items: tuple[AnalysisRunSummaryResponseV1, ...]
    next_cursor: str | None
    application_schema_version: str


class ResponseSerializationRecoveryV1(_StrictModel):
    run_id: str
    correlation_id: str
    persisted: Literal[True] = True
    recovery_endpoint: str
    recovery_reference: str


T = TypeVar("T")


class ApiOutcomeResponseV1(_StrictModel, Generic[T]):
    success: bool
    data: T | None
    error: ApiErrorV1 | None
    warnings: tuple[ApiWarningV1, ...]
    correlation_id: str
    api_schema_version: Literal["1.0.0"] = "1.0.0"
    application_schema_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def outcome_invariant(self):
        if self.success != (self.data is not None and self.error is None):
            raise ValueError("HTTP outcome invariant failed.")
        return self
