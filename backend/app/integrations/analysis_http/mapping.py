"""Explicit wire-to-application and application-to-wire mapping."""

from __future__ import annotations

import dataclasses
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from app.analysis_application.contracts import (
    AnalysisInputsDTO,
    AnalysisRunOptionsDTO,
    ApplicationAuditContextDTO,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
    CancelAnalysisCommand,
    CompanyMetadataDTO,
    DashboardRequestDTO,
    FinancialSourceIntentDTO,
    FinancialSourceReferenceDTO,
    GetAnalysisResultQuery,
    GetAnalysisStatusQuery,
    GetExecutionDetailQuery,
    ListAnalysisHistoryQuery,
    PriorPeriodFactsDTO,
    PriorPeriodProjectionDTO,
    RenderContractRequestDTO,
    ReportRequestDTO,
    ResumeAnalysisCommand,
    RetryAnalysisCommand,
    StartAnalysisCommand,
)


def application_scope(*, request, authentication, operation_kind, original_operation, previous_run_id=None):
    return ApplicationScopeDTO(
        request.company_id, request.financial_period_id, authentication.tenant_id,
        operation_kind, original_operation, previous_run_id,
    )


def audit_context(*, request, authentication, client_request_id, actor_id=None):
    attributes = {
        "authentication_method": authentication.authentication_method,
        "authentication_strength": authentication.authentication_strength.value,
        "claims_version": authentication.claims_version,
    }
    if actor_id is None:
        attributes["trusted_issuer"] = authentication.trusted_issuer
    return ApplicationAuditContextDTO(
        actor_id or authentication.subject_id, "authenticated_http_caller", "api_v1",
        request.purpose, client_request_id,
        attributes=attributes,
    )


def resolve_inputs(*, request, authentication, document_resolver, result_resolver):
    inputs = request.inputs
    balance = income = trial = None
    if inputs.balance_sheet_document_id is not None:
        balance = document_resolver.resolve_document_input(
            document_id=inputs.balance_sheet_document_id,
            company_id=request.company_id,
            financial_period_id=request.financial_period_id,
            expected_engine_code="fs_balance_sheet",
            authentication=authentication,
        )
    if inputs.income_statement_document_id is not None:
        income = document_resolver.resolve_document_input(
            document_id=inputs.income_statement_document_id,
            company_id=request.company_id,
            financial_period_id=request.financial_period_id,
            expected_engine_code="fs_income_statement",
            authentication=authentication,
        )
    if inputs.trial_balance_analysis_result_id is not None:
        trial = result_resolver.resolve_trial_balance_input(
            analysis_result_id=inputs.trial_balance_analysis_result_id,
            company_id=request.company_id,
            financial_period_id=request.financial_period_id,
            authentication=authentication,
        )
    resolved_document_ids = {
        item.document_id for item in (balance, income) if item is not None
    }
    resolved_result_ids = {trial.analysis_result_id} if trial is not None else set()
    intent_document_ids = {
        binding.source_document_id
        for intent in request.source_intents for binding in intent.source_bindings
        if binding.source_document_id is not None
    }
    intent_result_ids = {
        binding.source_analysis_result_id
        for intent in request.source_intents for binding in intent.source_bindings
        if binding.source_analysis_result_id is not None
    }
    if intent_document_ids != resolved_document_ids or intent_result_ids != resolved_result_ids:
        raise ValueError("Persisted source intent does not match the resolved computation input.")
    return AnalysisInputsDTO(
        balance_sheet_content=balance.content if balance else None,
        balance_sheet_filename=balance.original_filename if balance else None,
        income_statement_content=income.content if income else None,
        income_statement_filename=income.original_filename if income else None,
        trial_balance_result=trial.result_payload if trial else None,
        period_start_date=inputs.period_start_date,
        period_end_date=inputs.period_end_date,
        period_months_covered=inputs.period_months_covered,
    )


def build_execution_command(
    *, request, run_id, correlation_id, authentication, operation_kind,
    original_operation, previous_run_id, resolved_inputs, actor_id=None,
):
    scope = application_scope(
        request=request, authentication=authentication,
        operation_kind=operation_kind, original_operation=original_operation,
        previous_run_id=previous_run_id,
    )
    if request.run_options.engine_segmentation_tenant_id not in (None, authentication.tenant_id):
        raise ValueError("Engine tenant segmentation cannot differ from authenticated tenant.")
    run_options = AnalysisRunOptionsDTO(
        request.run_options.industry_code,
        request.run_options.company_size_bucket,
        authentication.tenant_id,
        request.run_options.reporting_period_label_tr,
        request.run_options.optional_report_sections,
        request.run_options.currency_display_policy,
        request.run_options.locale,
    )
    intents = tuple(FinancialSourceIntentDTO(
        item.engine_code, item.company_id, item.financial_period_id,
        item.primary_document_id,
        tuple(FinancialSourceReferenceDTO(
            binding.role, binding.source_document_id,
            binding.source_analysis_result_id, binding.source_engine_code,
        ) for binding in item.source_bindings),
        item.requested_source_mode, item.allow_existing_canonical_owner,
        item.expected_existing_owner_id, _application_value(item.provenance_metadata),
        item.caller_supplied_business_timestamp,
    ) for item in request.source_intents)
    common = dict(
        run_id=run_id, correlation_id=correlation_id, generated_at=request.generated_at,
        scope=scope,
        audit_context=audit_context(
            request=request, authentication=authentication, client_request_id=run_id,
            actor_id=actor_id,
        ),
        authorization_context_reference=authentication.authorization_context_reference,
        requested_outputs=request.requested_outputs, inputs=resolved_inputs,
        run_options=run_options, source_intents=intents,
        prior_period_projection=_prior(request.prior_period_projection),
        company_metadata=(CompanyMetadataDTO(**request.company_metadata.model_dump()) if request.company_metadata else None),
        report_request=(ReportRequestDTO(**request.report_request.model_dump()) if request.report_request else None),
        dashboard_request=(DashboardRequestDTO(**request.dashboard_request.model_dump()) if request.dashboard_request else None),
        render_contract_request=(RenderContractRequestDTO(**request.render_contract_request.model_dump()) if request.render_contract_request else None),
        application_contract_version=request.application_contract_version,
    )
    cls = {
        ApplicationOperationKind.START: StartAnalysisCommand,
        ApplicationOperationKind.RESUME: ResumeAnalysisCommand,
        ApplicationOperationKind.RETRY: RetryAnalysisCommand,
    }[operation_kind]
    return cls(**common)


def build_cancel_command(*, run_id, correlation_id, generated_at, scope, authentication, actor_id=None):
    actor = ApplicationAuditContextDTO(
        actor_id or authentication.subject_id, "authenticated_http_caller", "api_v1",
        "analysis.cancel", run_id,
    )
    return CancelAnalysisCommand(
        run_id, correlation_id, generated_at, scope, actor,
        authentication.authorization_context_reference,
    )


def build_run_query(*, kind, run_id, correlation_id, generated_at, scope, authentication, include_payload=False, engine_code=None, actor_id=None):
    actor = ApplicationAuditContextDTO(
        actor_id or authentication.subject_id, "authenticated_http_caller", "api_v1",
        f"analysis.{kind}", correlation_id,
    )
    common = dict(
        run_id=run_id, correlation_id=correlation_id, generated_at=generated_at,
        scope=scope, audit_context=actor,
        authorization_context_reference=authentication.authorization_context_reference,
    )
    if kind == "status": return GetAnalysisStatusQuery(**common)
    if kind == "result": return GetAnalysisResultQuery(**common, include_payloads=include_payload)
    return GetExecutionDetailQuery(**common, engine_code=engine_code, include_payload=include_payload)


def build_history_query(*, correlation_id, generated_at, scope, authentication, cursor, limit, actor_id=None):
    actor = ApplicationAuditContextDTO(
        actor_id or authentication.subject_id, "authenticated_http_caller", "api_v1",
        "analysis.history.read", correlation_id,
    )
    return ListAnalysisHistoryQuery(
        correlation_id, generated_at, scope, actor,
        authentication.authorization_context_reference, cursor, limit,
    )


def to_wire(value):
    if value is None or isinstance(value, (bool, str, int, float)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, (datetime, date)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if not value.__class__.__module__.startswith("app.analysis_application"):
            raise ValueError("Only application DTO dataclasses may cross the HTTP boundary.")
        return {field.name: to_wire(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, tuple):
        return tuple(to_wire(item) for item in value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("HTTP map keys must be strings.")
        return {key: to_wire(item) for key, item in value.items()}
    raise ValueError("Unsupported HTTP projection value.")


def _application_value(value):
    if isinstance(value, list):
        return tuple(_application_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _application_value(item) for key, item in value.items()}
    return value


def _prior(value):
    if value is None:
        return None
    def facts(item):
        return PriorPeriodFactsDTO(item.statement_kind, item.values, item.schema_version) if item else None
    return PriorPeriodProjectionDTO(
        facts(value.balance_sheet_facts), facts(value.income_statement_facts),
        _application_value(value.balance_sheet_result) if value.balance_sheet_result else None,
        _application_value(value.income_statement_result) if value.income_statement_result else None,
    )
