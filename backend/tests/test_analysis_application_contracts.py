from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest

from app.analysis_application.contracts import (
    AnalysisErrorCode, AnalysisErrorDTO, ApplicationAuditContextDTO,
    ApplicationEngineCode, ApplicationErrorCategory, ApplicationOperationKind,
    ApplicationOriginalOperation, ApplicationOutcome, ApplicationScopeDTO,
    ApplicationStatus, FinancialSourceIntentDTO, FinancialSourceMode,
    FinancialSourceReferenceDTO, FinancialSourceRole, PayloadOwnerType,
    ApplicationPayloadReferenceDTO, StartAnalysisCommand, ResumeAnalysisCommand,
    RetryAnalysisCommand, AnalysisInputsDTO, AnalysisRunOptionsDTO,
    validate_application_json,
)
from app.analysis_application.internal_types import OwnerAuditTimes
from app.analysis_application.ownership import resolve_financial_ownership_plan
from app.engines.analysis_orchestrator.types import (
    EngineCode, EngineExecutionStatus, ExecutionProvenance,
    OrchestrationRunResult, PerEngineExecutionRecord, RunStatus,
)
from app.orchestration_persistence.ownership import RESULT_OWNERSHIP_REGISTRY, ResultOwner


def _scope(kind=ApplicationOperationKind.START, original=ApplicationOriginalOperation.START):
    return ApplicationScopeDTO(uuid.uuid4(), uuid.uuid4(), "tenant", kind, original, None if kind is ApplicationOperationKind.START else "previous")


def _audit():
    return ApplicationAuditContextDTO("actor", "service", "test", "analysis")


def _command(cls, scope):
    intent = FinancialSourceIntentDTO(
        ApplicationEngineCode.FS_BALANCE_SHEET, scope.company_id,
        scope.financial_period_id, None, (),
        FinancialSourceMode.TRIAL_BALANCE_DERIVED, False, None, {},
    )
    return cls("run", "corr", datetime.now(timezone.utc), scope, _audit(), "auth", (ApplicationEngineCode.FS_BALANCE_SHEET,), AnalysisInputsDTO(), AnalysisRunOptionsDTO(), (intent,))


def test_closed_enums_and_command_fields_are_exact():
    assert ApplicationEngineCode.RATIO.value == "ratio"
    expected = {"run_id", "correlation_id", "generated_at", "scope", "audit_context", "authorization_context_reference", "requested_outputs", "inputs", "run_options", "source_intents", "prior_period_projection", "company_metadata", "report_request", "dashboard_request", "render_contract_request", "application_contract_version"}
    assert {item.name for item in fields(StartAnalysisCommand)} == expected
    assert {item.name for item in fields(ResumeAnalysisCommand)} == expected
    assert {item.name for item in fields(RetryAnalysisCommand)} == expected


def test_start_resume_retry_scope_invariants():
    assert _command(StartAnalysisCommand, _scope()).run_id == "run"
    assert _command(ResumeAnalysisCommand, _scope(ApplicationOperationKind.RESUME, ApplicationOriginalOperation.RESUME)).scope.previous_run_id == "previous"
    assert _command(RetryAnalysisCommand, _scope(ApplicationOperationKind.RETRY)).scope.previous_run_id == "previous"
    with pytest.raises(ValueError):
        _command(StartAnalysisCommand, _scope(ApplicationOperationKind.RESUME, ApplicationOriginalOperation.RESUME))


def test_financial_source_intent_roles_and_owner_registry():
    document_id = uuid.uuid4()
    ref = FinancialSourceReferenceDTO(FinancialSourceRole.PRIMARY_DOCUMENT, source_document_id=document_id)
    intent = FinancialSourceIntentDTO(ApplicationEngineCode.RATIO, uuid.uuid4(), uuid.uuid4(), document_id, (ref,), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {"amount": Decimal("1.20")})
    assert intent.engine_code is ApplicationEngineCode.RATIO
    with pytest.raises(ValueError):
        FinancialSourceReferenceDTO(FinancialSourceRole.PRIMARY_ANALYSIS, source_document_id=document_id)
    with pytest.raises(ValueError):
        FinancialSourceIntentDTO(ApplicationEngineCode.BENCHMARK, uuid.uuid4(), uuid.uuid4(), None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {})


def test_payload_reference_owner_xor_and_financial_serializer_none():
    ref = ApplicationPayloadReferenceDTO(PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT, "dict", "a" * 64, financial_analysis_result_id=uuid.uuid4())
    assert ref.artifact_serializer_schema_version is None
    with pytest.raises(ValueError):
        ApplicationPayloadReferenceDTO(PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT, "dict", "a" * 64, financial_analysis_result_id=uuid.uuid4(), artifact_serializer_schema_version="1")


def test_application_json_rejects_lists_non_string_keys_and_nonfinite():
    validate_application_json({"ok": (Decimal("1.2"), 3.5), "date": {"$application_type": "date", "value": "2026-01-01"}})
    for value in ([1], {1: "bad"}, float("nan"), float("inf"), Decimal("NaN"), {"$application_type": "datetime", "value": "2026-01-01T00:00:00"}, {"$application_type": "secret", "value": "x"}):
        with pytest.raises(ValueError):
            validate_application_json(value)


def test_application_outcome_discriminated_invariants():
    ok = ApplicationOutcome(True, "value", None, (), "corr")
    assert ok.value == "value"
    error = AnalysisErrorDTO(AnalysisErrorCode.INVALID_COMMAND, ApplicationErrorCategory.VALIDATION, "Invalid command.", False, "corr", {})
    failed = ApplicationOutcome(False, None, error, (), "corr")
    assert failed.error is error
    with pytest.raises(ValueError):
        ApplicationOutcome(True, None, None, (), "corr")


def test_application_status_is_closed_enum():
    assert {item.value for item in ApplicationStatus} == {"fully_completed", "completed_with_degradations", "partially_completed", "failed", "cancelled"}


def test_financial_owner_registry_matches_5_0b_line_by_line():
    financial = {
        ApplicationEngineCode(code.value)
        for code, ownership in RESULT_OWNERSHIP_REGISTRY.items()
        if ownership.owner is ResultOwner.FINANCIAL_ANALYSIS_RESULT
    }
    from app.analysis_application.contracts import FINANCIAL_OWNER_ENGINE_CODES
    assert financial == FINANCIAL_OWNER_ENGINE_CODES


def test_failed_and_skipped_financial_records_create_no_owner_plan():
    scope = _scope()
    records = tuple(
        PerEngineExecutionRecord(code, status, None, None, None, (), None, None, chr(97 + index) * 64, "1")
        for index, (code, status) in enumerate((
            (EngineCode.FS_BALANCE_SHEET, EngineExecutionStatus.FAILED),
            (EngineCode.FS_INCOME_STATEMENT, EngineExecutionStatus.FAILED),
            (EngineCode.RATIO, EngineExecutionStatus.SKIPPED),
        ))
    )
    result = OrchestrationRunResult("run", None, None, RunStatus.FAILED, records, (), (), ExecutionProvenance("2", (), (), (EngineCode.RATIO,)), {}, "2", "2", "2", "d" * 64)
    intents = tuple(FinancialSourceIntentDTO(ApplicationEngineCode(record.engine_code.value), scope.company_id, scope.financial_period_id, None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {}) for record in records)
    plan = resolve_financial_ownership_plan(result, intents, scope, OwnerAuditTimes(datetime.now(timezone.utc), datetime.now(timezone.utc)))
    assert plan.nodes == ()
