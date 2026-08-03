"""Synchronous V3 orchestrator with a first-class Cash Flow node."""

from __future__ import annotations

from typing import Callable

from app.engines.analysis_orchestrator.service import _extract_versions, _map_inner_status
from app.engines.analysis_orchestrator.types import EngineCode as LegacyEngineCode
from app.engines.cash_flow.contracts import CashFlowEngineOutcome, CashFlowResult, canonical_cash_flow_digest
from app.engines.cash_flow.types import CASH_FLOW_MODEL_VERSION, CASH_FLOW_SCHEMA_VERSION, CashFlowResultStatus

from .dispatch import ORCHESTRATOR_ENGINE_DISPATCH_V3
from .execution_plan import EXECUTION_PLAN_V3
from .fingerprint import canonical_v3_hash, compute_engine_input_fingerprint_v3, compute_request_fingerprint_v3
from .registry import ENGINE_DEPENDENCY_REGISTRY_V3
from .types import (
    EMPTY_JSON_OBJECT_V3,
    EXECUTION_PLAN_VERSION_V3,
    FINGERPRINT_SCHEMA_VERSION_V3,
    ORCHESTRATION_MODEL_VERSION_V3,
    ORCHESTRATION_SCHEMA_VERSION_V3,
    BalanceSheetAnalysisOutcomeV3,
    EngineExecutionStatusV3,
    EngineResultEnvelopeV3,
    ExecutionProvenanceV3,
    ExecutionTelemetryV3,
    FinancialAnalysisStatusV3,
    FinancialSourceModeV3,
    IncomeStatementAnalysisOutcomeV3,
    OrchestrationEngineCodeV3 as E,
    OrchestrationErrorCategoryV3,
    OrchestrationJsonObjectV3,
    OrchestrationRunRequestV3,
    OrchestrationRunResultV3,
    ORCHESTRATION_V3_ENGINE_VERSION_MANIFEST,
    PerEngineExecutionRecordV3,
    PerEngineTelemetryV3,
    RunStatusV3,
    StructuredErrorV3,
    TimingProbeV3,
)

_ALIVE = {EngineExecutionStatusV3.COMPLETED, EngineExecutionStatusV3.DEGRADED, EngineExecutionStatusV3.REUSED}
_SAFE_GENERIC_MESSAGES = {
    OrchestrationErrorCategoryV3.ENGINE_CONTRACT_VIOLATION: "Motor sözleşmesi doğrulanamadı.",
    OrchestrationErrorCategoryV3.DEPENDENCY_UNAVAILABLE: "Gerekli motor bağımlılığı kullanılamıyor.",
    OrchestrationErrorCategoryV3.VERSION_INCOMPATIBLE_ON_REUSE: "Önceki çalıştırmanın motor sürümü uyumlu değil.",
    OrchestrationErrorCategoryV3.FINGERPRINT_MISMATCH_ON_REUSE: "Önceki çalıştırmanın girdi parmak izi eşleşmiyor.",
    OrchestrationErrorCategoryV3.INVALID_RUN_REQUEST: "Analiz isteği geçersiz.",
    OrchestrationErrorCategoryV3.CANCELLED: "Analiz iptal edildi.",
}


def _object(value: object) -> OrchestrationJsonObjectV3:
    if type(value) is OrchestrationJsonObjectV3:
        return value
    if type(value) is not dict:
        raise TypeError("V3 object projection requires dict")
    items = []
    for key in sorted(value):
        item = value[key]
        if type(item) is dict:
            item = _object(item)
        elif type(item) is list:
            item = tuple(_object(x) if type(x) is dict else x for x in item)
        items.append((key, item))
    return OrchestrationJsonObjectV3(tuple(items))


def _dict(value: OrchestrationJsonObjectV3 | None):
    if value is None:
        return None
    return {key: (_dict(item) if type(item) is OrchestrationJsonObjectV3 else item) for key, item in value.items}


def _project_fs(code: E, raw: object):
    cls = BalanceSheetAnalysisOutcomeV3 if code is E.FS_BALANCE_SHEET else IncomeStatementAnalysisOutcomeV3
    status = FinancialAnalysisStatusV3(raw.status.value)
    source_mode = FinancialSourceModeV3(raw.source_mode.value) if raw.source_mode is not None else None
    payload = _object(raw.result_json) if raw.result_json is not None else None
    return cls(status, source_mode, payload, raw.error_message, raw.trial_balance_usage)


def _required(requested: tuple[E, ...]) -> set[E]:
    result = set(requested)
    changed = True
    while changed:
        changed = False
        for code in tuple(result):
            dep = ENGINE_DEPENDENCY_REGISTRY_V3[code].dependency
            for item in dep.all_of + dep.any_of:
                if item not in result:
                    result.add(item)
                    changed = True
    return result


def _usable(code: E, records: dict[E, PerEngineExecutionRecordV3], *, cash_flow_gate=False) -> bool:
    record = records.get(code)
    if record is None or record.status not in _ALIVE or record.result is None:
        return False
    if code in {E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT} and not cash_flow_gate:
        return record.result.result.result_json is not None
    return True


def _invoke(code: E, request, raw_results, records):
    fn = ORCHESTRATOR_ENGINE_DISPATCH_V3[code]
    ei, ro = request.engine_inputs, request.run_options
    if code is E.FS_BALANCE_SHEET:
        return fn(content=ei.balance_sheet_content, filename=ei.balance_sheet_filename, trial_balance_result=_dict(ei.trial_balance_result), prior_period_facts=ei.prior_period_balance_sheet_facts)
    if code is E.FS_INCOME_STATEMENT:
        return fn(content=ei.income_statement_content, filename=ei.income_statement_filename, trial_balance_result=_dict(ei.trial_balance_result), prior_period_facts=ei.prior_period_income_statement_facts)
    if code is E.CASH_FLOW:
        return fn(pre_resolved_context=ei.cash_flow_pre_resolved_context, current_balance_sheet=raw_results.get(E.FS_BALANCE_SHEET), current_income_statement=raw_results.get(E.FS_INCOME_STATEMENT))
    if code is E.RATIO:
        bs, inc = raw_results.get(E.FS_BALANCE_SHEET), raw_results.get(E.FS_INCOME_STATEMENT)
        return fn(balance_sheet_result=bs.result_json if bs else None, income_statement_result=inc.result_json if inc else None, prior_period_balance_sheet_result=_dict(ei.prior_period_balance_sheet_result), prior_period_income_statement_result=_dict(ei.prior_period_income_statement_result), period_start_date=ei.period_start_date, period_end_date=ei.period_end_date, period_months_covered=ei.period_months_covered, cash_flow_result=raw_results.get(E.CASH_FLOW))
    if code is E.BENCHMARK:
        return fn(raw_results.get(E.RATIO), industry_code=ro.industry_code, company_size_bucket=ro.company_size_bucket)
    if code is E.HEALTH_SCORE:
        return fn(raw_results.get(E.RATIO), raw_results.get(E.BENCHMARK), industry_code=ro.industry_code, company_size_bucket=ro.company_size_bucket, tenant_id=ro.tenant_id)
    if code is E.CREDIT_SCORE:
        return fn(raw_results.get(E.RATIO), raw_results.get(E.BENCHMARK), raw_results.get(E.HEALTH_SCORE), industry_code=ro.industry_code, company_size_bucket=ro.company_size_bucket, tenant_id=ro.tenant_id)
    if code is E.RECOMMENDATION:
        return fn(raw_results.get(E.RATIO), raw_results.get(E.BENCHMARK), raw_results.get(E.HEALTH_SCORE), raw_results.get(E.CREDIT_SCORE), industry_code=ro.industry_code, company_size_bucket=ro.company_size_bucket, tenant_id=ro.tenant_id)
    if code is E.EXECUTIVE_REPORT:
        cash_requested = E.CASH_FLOW in request.requested_outputs
        cash_record = records.get(E.CASH_FLOW)
        failure_status = None
        failure_code = None
        if cash_requested and E.CASH_FLOW not in raw_results and cash_record is not None:
            if cash_record.inner_status_value in {
                CashFlowResultStatus.INVALID_INPUT.value,
                CashFlowResultStatus.INTEGRITY_FAILURE.value,
            }:
                failure_status = CashFlowResultStatus(cash_record.inner_status_value)
                failure_code = cash_record.error.cash_flow_error_code if cash_record.error else None
        bs_outcome = raw_results[E.FS_BALANCE_SHEET]
        is_outcome = raw_results[E.FS_INCOME_STATEMENT]
        return fn(
            ro.report_type,
            bs_outcome.result_json,
            is_outcome.result_json,
            raw_results[E.RATIO],
            raw_results[E.BENCHMARK],
            raw_results[E.HEALTH_SCORE],
            raw_results[E.CREDIT_SCORE],
            raw_results[E.RECOMMENDATION],
            company_metadata=ro.company_metadata,
            reporting_period_label_tr=ro.reporting_period_label_tr,
            optional_sections=ro.optional_sections,
            report_id=request.run_id,
            generated_at=request.generated_at,
            locale=ro.locale,
            currency_display_policy=ro.currency_display_policy,
            cash_flow_requested=cash_requested,
            cash_flow_result=raw_results.get(E.CASH_FLOW),
            cash_flow_failure_status=failure_status,
            cash_flow_error_code=failure_code,
        )
    if code is E.DASHBOARD:
        return fn(raw_results[E.HEALTH_SCORE], raw_results[E.CREDIT_SCORE], raw_results[E.RECOMMENDATION], benchmark_results=raw_results.get(E.BENCHMARK), dashboard_type=ro.dashboard_type)
    if code is E.RENDER_CONTRACT:
        return fn(raw_results[E.EXECUTIVE_REPORT], ro.render_contract)
    raise ValueError("unknown V3 engine")


def _expected_engine_versions(code: E, request: OrchestrationRunRequestV3):
    if code is E.EXECUTIVE_REPORT and E.CASH_FLOW in request.requested_outputs:
        return ("1.1.0", "1.1.0")
    return ORCHESTRATION_V3_ENGINE_VERSION_MANIFEST[code]


def _run_status(records, cancelled):
    if cancelled:
        return RunStatusV3.CANCELLED
    statuses = tuple(record.status for record in records.values())
    if not statuses or not any(item in _ALIVE for item in statuses):
        return RunStatusV3.FAILED
    if any(item in {EngineExecutionStatusV3.FAILED, EngineExecutionStatusV3.SKIPPED} for item in statuses):
        return RunStatusV3.PARTIALLY_COMPLETED
    if EngineExecutionStatusV3.DEGRADED in statuses:
        return RunStatusV3.COMPLETED_WITH_DEGRADATIONS
    return RunStatusV3.FULLY_COMPLETED


def run_orchestration_v3(request: OrchestrationRunRequestV3, *, cancellation_probe: Callable[[], bool] | None = None, timing_probe: TimingProbeV3 | None = None):
    if type(request) is not OrchestrationRunRequestV3:
        raise TypeError("run_orchestration_v3 accepts only V3 requests")
    if not request.requested_outputs:
        error = StructuredErrorV3(OrchestrationErrorCategoryV3.INVALID_RUN_REQUEST, None, _SAFE_GENERIC_MESSAGES[OrchestrationErrorCategoryV3.INVALID_RUN_REQUEST], None, EMPTY_JSON_OBJECT_V3, False)
        return OrchestrationRunResultV3(request.run_id, request.correlation_id, request.generated_at, RunStatusV3.FAILED, (), (), (error,), ExecutionProvenanceV3(EXECUTION_PLAN_VERSION_V3, (), (), ()), EMPTY_JSON_OBJECT_V3, ORCHESTRATION_SCHEMA_VERSION_V3, ORCHESTRATION_MODEL_VERSION_V3, EXECUTION_PLAN_VERSION_V3, ""), None
    request_fp = compute_request_fingerprint_v3(request)
    snapshot = request.previous_execution_snapshot
    if snapshot is not None and (snapshot.orchestration_schema_version, snapshot.orchestration_model_version, snapshot.execution_plan_version) != ("3.0.0", "3.0.0", "3.0.0"):
        error = StructuredErrorV3(OrchestrationErrorCategoryV3.VERSION_INCOMPATIBLE_ON_REUSE, None, _SAFE_GENERIC_MESSAGES[OrchestrationErrorCategoryV3.VERSION_INCOMPATIBLE_ON_REUSE], None, EMPTY_JSON_OBJECT_V3, False)
        return OrchestrationRunResultV3(request.run_id, request.correlation_id, request.generated_at, RunStatusV3.FAILED, (), (), (error,), ExecutionProvenanceV3(EXECUTION_PLAN_VERSION_V3, (), (), ()), EMPTY_JSON_OBJECT_V3, ORCHESTRATION_SCHEMA_VERSION_V3, ORCHESTRATION_MODEL_VERSION_V3, EXECUTION_PLAN_VERSION_V3, request_fp), None
    if snapshot is not None and snapshot.request_fingerprint != request_fp:
        error = StructuredErrorV3(OrchestrationErrorCategoryV3.FINGERPRINT_MISMATCH_ON_REUSE, None, _SAFE_GENERIC_MESSAGES[OrchestrationErrorCategoryV3.FINGERPRINT_MISMATCH_ON_REUSE], None, EMPTY_JSON_OBJECT_V3, False)
        return OrchestrationRunResultV3(request.run_id, request.correlation_id, request.generated_at, RunStatusV3.FAILED, (), (), (error,), ExecutionProvenanceV3(EXECUTION_PLAN_VERSION_V3, (), (), ()), EMPTY_JSON_OBJECT_V3, ORCHESTRATION_SCHEMA_VERSION_V3, ORCHESTRATION_MODEL_VERSION_V3, EXECUTION_PLAN_VERSION_V3, request_fp), None
    previous = {item.engine_code: item for item in snapshot.engine_snapshots} if snapshot else {}
    required = _required(request.requested_outputs)
    records, raw_results, upstream = {}, {}, {}
    call_sequence, reused, skipped, errors = [], [], [], []
    cancelled = False
    for code in (item for item in EXECUTION_PLAN_V3 if item in required):
        if cancellation_probe and cancellation_probe():
            cancelled = True
        deps = ENGINE_DEPENDENCY_REGISTRY_V3[code].dependency
        if cancelled:
            skipped.append(code)
            records[code] = PerEngineExecutionRecordV3(code, EngineExecutionStatusV3.SKIPPED, None, None, None, deps.all_of + deps.any_of + deps.optional, None, None, "", FINGERPRINT_SCHEMA_VERSION_V3)
            continue
        cash_gate = code is E.CASH_FLOW
        all_ok = all(_usable(dep, records, cash_flow_gate=cash_gate) for dep in deps.all_of)
        any_ok = any(_usable(dep, records) for dep in deps.any_of) if deps.any_of else True
        if not all_ok or not any_ok:
            skipped.append(code)
            error = None
            if code is E.CASH_FLOW:
                error = StructuredErrorV3(OrchestrationErrorCategoryV3.DEPENDENCY_UNAVAILABLE, code, _SAFE_GENERIC_MESSAGES[OrchestrationErrorCategoryV3.DEPENDENCY_UNAVAILABLE], None, EMPTY_JSON_OBJECT_V3, False)
                errors.append(error)
            records[code] = PerEngineExecutionRecordV3(code, EngineExecutionStatusV3.SKIPPED, None, None, error, deps.all_of + deps.any_of + deps.optional, None, None, "", FINGERPRINT_SCHEMA_VERSION_V3)
            continue
        input_fp = compute_engine_input_fingerprint_v3(code, request, upstream)
        old = previous.get(code)
        selected_dependencies = tuple(
            dep for dep in deps.all_of + deps.any_of + deps.optional if dep in required
        )
        dependencies_reused = all(dep in reused for dep in selected_dependencies)
        expected_versions = _expected_engine_versions(code, request)
        if old is not None and old.execution_status in {EngineExecutionStatusV3.COMPLETED, EngineExecutionStatusV3.DEGRADED}:
            mismatch_category = None
            if (old.engine_schema_version_used, old.engine_model_version_used) != expected_versions:
                mismatch_category = OrchestrationErrorCategoryV3.VERSION_INCOMPATIBLE_ON_REUSE
            elif old.input_fingerprint != input_fp or old.fingerprint_schema_version != FINGERPRINT_SCHEMA_VERSION_V3:
                mismatch_category = OrchestrationErrorCategoryV3.FINGERPRINT_MISMATCH_ON_REUSE
            elif code is E.CASH_FLOW and (old.result is None or type(old.result.result) is not CashFlowResult):
                mismatch_category = OrchestrationErrorCategoryV3.VERSION_INCOMPATIBLE_ON_REUSE
            if mismatch_category is not None:
                error = StructuredErrorV3(mismatch_category, code, _SAFE_GENERIC_MESSAGES[mismatch_category], None, EMPTY_JSON_OBJECT_V3, False)
                errors.append(error)
                records[code] = PerEngineExecutionRecordV3(code, EngineExecutionStatusV3.FAILED, None, None, error, deps.all_of + deps.any_of + deps.optional, None, None, input_fp, FINGERPRINT_SCHEMA_VERSION_V3)
                continue
        reusable = old is not None and old.execution_status in {EngineExecutionStatusV3.COMPLETED, EngineExecutionStatusV3.DEGRADED} and old.input_fingerprint == input_fp and old.fingerprint_schema_version == FINGERPRINT_SCHEMA_VERSION_V3 and (old.engine_schema_version_used, old.engine_model_version_used) == expected_versions and dependencies_reused
        if reusable:
            record = PerEngineExecutionRecordV3(code, EngineExecutionStatusV3.REUSED, old.result, old.result.result.status.value if code is E.CASH_FLOW and old.result else None, None, deps.all_of + deps.any_of + deps.optional, old.engine_schema_version_used, old.engine_model_version_used, input_fp, FINGERPRINT_SCHEMA_VERSION_V3)
            records[code] = record
            raw_results[code] = old.result.result if old.result else None
            reused.append(code); call_sequence.append(code)
            upstream[code] = canonical_cash_flow_digest(old.result.result) if code is E.CASH_FLOW else canonical_v3_hash(old.result.result)
            continue
        try:
            raw = _invoke(code, request, raw_results, records)
            call_sequence.append(code)
            if code is E.CASH_FLOW:
                if type(raw) is not CashFlowEngineOutcome:
                    raise TypeError("Cash Flow dispatch must return CashFlowEngineOutcome")
                if not raw.success:
                    failure = raw.error
                    error = StructuredErrorV3(OrchestrationErrorCategoryV3.ENGINE_CONTRACT_VIOLATION, code, failure.safe_message, failure.code, EMPTY_JSON_OBJECT_V3, failure.retryable)
                    errors.append(error)
                    records[code] = PerEngineExecutionRecordV3(code, EngineExecutionStatusV3.FAILED, None, raw.status.value, error, deps.all_of + deps.any_of + deps.optional, CASH_FLOW_SCHEMA_VERSION, CASH_FLOW_MODEL_VERSION, input_fp, FINGERPRINT_SCHEMA_VERSION_V3)
                    upstream[code] = canonical_v3_hash(OrchestrationJsonObjectV3((("cash_flow_error_code", failure.code.value), ("cash_flow_failure_status", raw.status.value))))
                    continue
                result = raw.value
                status = EngineExecutionStatusV3.COMPLETED if result.status is CashFlowResultStatus.COMPLETE_RECONCILED else EngineExecutionStatusV3.DEGRADED
                envelope = EngineResultEnvelopeV3(code, "CashFlowResult", result)
                schema_v, model_v = CASH_FLOW_SCHEMA_VERSION, CASH_FLOW_MODEL_VERSION
                projected = result
            else:
                legacy_code = LegacyEngineCode(code.value)
                legacy_status, inner = _map_inner_status(legacy_code, raw)
                status = EngineExecutionStatusV3(legacy_status.value)
                schema_v, model_v = _extract_versions(legacy_code, raw)
                projected = _project_fs(code, raw) if code in {E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT} else (_object(raw) if type(raw) is dict else raw)
                envelope = EngineResultEnvelopeV3(code, ENGINE_DEPENDENCY_REGISTRY_V3[code].produces, projected)
            records[code] = PerEngineExecutionRecordV3(code, status, envelope, result.status.value if code is E.CASH_FLOW else inner, None, deps.all_of + deps.any_of + deps.optional, schema_v, model_v, input_fp, FINGERPRINT_SCHEMA_VERSION_V3)
            raw_results[code] = raw if code is not E.CASH_FLOW else result
            upstream[code] = canonical_cash_flow_digest(result) if code is E.CASH_FLOW else canonical_v3_hash(projected)
        except Exception:
            error = StructuredErrorV3(OrchestrationErrorCategoryV3.ENGINE_CONTRACT_VIOLATION, code, _SAFE_GENERIC_MESSAGES[OrchestrationErrorCategoryV3.ENGINE_CONTRACT_VIOLATION], None, EMPTY_JSON_OBJECT_V3, False, "unexpected_engine_failure")
            errors.append(error)
            records[code] = PerEngineExecutionRecordV3(code, EngineExecutionStatusV3.FAILED, None, None, error, deps.all_of + deps.any_of + deps.optional, None, None, input_fp, FINGERPRINT_SCHEMA_VERSION_V3)
            if code is E.CASH_FLOW:
                upstream[code] = canonical_v3_hash(OrchestrationJsonObjectV3((("cash_flow_error_code", None), ("cash_flow_failure_status", "unexpected_engine_failure"))))
    ordered_records = tuple(records[code] for code in EXECUTION_PLAN_V3 if code in records)
    inventory = OrchestrationJsonObjectV3(tuple(sorted((f"{record.engine_code.value}_model_version", record.engine_model_version_used) for record in ordered_records if record.engine_model_version_used)))
    result = OrchestrationRunResultV3(request.run_id, request.correlation_id, request.generated_at, _run_status(records, cancelled), ordered_records, (), tuple(errors), ExecutionProvenanceV3(EXECUTION_PLAN_VERSION_V3, tuple(call_sequence), tuple(reused), tuple(skipped)), inventory, ORCHESTRATION_SCHEMA_VERSION_V3, ORCHESTRATION_MODEL_VERSION_V3, EXECUTION_PLAN_VERSION_V3, request_fp)
    return result, None
