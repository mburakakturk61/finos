"""Synchronous V4 orchestration with isolated Trend execution and reuse."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from app.engines.analysis_orchestrator_v3.fingerprint import compute_request_fingerprint_v3
from app.engines.analysis_orchestrator_v3.service import run_orchestration_v3
from app.engines.analysis_orchestrator_v3.types import (
    EngineExecutionStatusV3, EngineRawInputsV3, EngineResultEnvelopeV3,
    OrchestrationEngineCodeV3, OrchestrationRunOptionsV3, OrchestrationRunRequestV3,
    PreviousEngineSnapshotV3, PreviousExecutionSnapshotV3,
)
from app.engines.common.report_types import ExecutiveReportResult
from app.engines.executive_reports.trend_integration import (
    REPORT_MODEL_VERSION_V1_2_TREND,
    REPORT_SCHEMA_VERSION_V1_2_TREND,
    canonical_report_presentation_digest_v1_2,
    integrate_trend_report_v1_2,
)
from app.engines.executive_reports.trend_projection import project_trend_report_source_v1_2
from app.engines.multi_period_trend import (
    MultiPeriodTrendResult, TrendComputationStatus, TrendResultAssemblyError,
    canonical_trend_digest, canonical_trend_reference,
)

from .dispatch import ORCHESTRATOR_ENGINE_DISPATCH_V4
from .execution_plan import EXECUTION_PLAN_V4
from .fingerprint import compute_engine_input_fingerprint_v4, compute_request_fingerprint_v4
from .registry import ENGINE_DEPENDENCY_REGISTRY_V4
from .types import (
    EXECUTION_PLAN_VERSION_V4, FINGERPRINT_SCHEMA_VERSION_V4,
    ORCHESTRATION_MODEL_VERSION_V4, ORCHESTRATION_SCHEMA_VERSION_V4,
    EngineExecutionStatusV4, EngineResultEnvelopeV4, ExecutionProvenanceV4,
    OrchestrationEngineCodeV4 as E, OrchestrationErrorCategoryV4,
    OrchestrationRunOptionsV4, OrchestrationRunRequestV4, OrchestrationRunResultV4,
    PerEngineExecutionRecordV4, RunStatusV4, StructuredErrorV4,
)


_ALIVE = {EngineExecutionStatusV4.COMPLETED, EngineExecutionStatusV4.DEGRADED, EngineExecutionStatusV4.REUSED}
_SAFE_MESSAGES = {
    OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION: "Motor sözleşmesi doğrulanamadı.",
    OrchestrationErrorCategoryV4.VERSION_INCOMPATIBLE_ON_REUSE: "Önceki çalıştırma sürümü uyumlu değil.",
    OrchestrationErrorCategoryV4.FINGERPRINT_MISMATCH_ON_REUSE: "Önceki çalıştırma girdisi eşleşmiyor.",
    OrchestrationErrorCategoryV4.RESUME_LINEAGE_INTEGRITY_FAILURE: "Önceki trend lineage doğrulaması başarısız.",
    OrchestrationErrorCategoryV4.INVALID_RUN_REQUEST: "Analiz isteği geçersiz.",
}


def _wants_trend_report(request: OrchestrationRunRequestV4) -> bool:
    return (
        E.MULTI_PERIOD_TREND in request.requested_outputs
        and bool({E.EXECUTIVE_REPORT, E.RENDER_CONTRACT} & set(request.requested_outputs))
    )


def _legacy_request(request: OrchestrationRunRequestV4) -> OrchestrationRunRequestV3 | None:
    outputs = tuple(OrchestrationEngineCodeV3(item.value) for item in request.requested_outputs if item is not E.MULTI_PERIOD_TREND)
    if not outputs:
        return None
    ei, ro = request.engine_inputs, request.run_options
    legacy_inputs = EngineRawInputsV3(
        balance_sheet_content=ei.balance_sheet_content,
        balance_sheet_filename=ei.balance_sheet_filename,
        income_statement_content=ei.income_statement_content,
        income_statement_filename=ei.income_statement_filename,
        trial_balance_result=ei.trial_balance_result,
        prior_period_balance_sheet_facts=ei.prior_period_balance_sheet_facts,
        prior_period_income_statement_facts=ei.prior_period_income_statement_facts,
        prior_period_balance_sheet_result=ei.prior_period_balance_sheet_result,
        prior_period_income_statement_result=ei.prior_period_income_statement_result,
        period_start_date=ei.period_start_date,
        period_end_date=ei.period_end_date,
        period_months_covered=ei.period_months_covered,
        cash_flow_pre_resolved_context=ei.cash_flow_pre_resolved_context,
    )
    legacy_options = OrchestrationRunOptionsV3(**vars(ro))
    base = OrchestrationRunRequestV3(
        request.run_id, request.correlation_id, request.generated_at, outputs,
        legacy_inputs, legacy_options,
    )
    snapshot = request.previous_execution_snapshot
    if snapshot is None:
        return base
    trend_report = _wants_trend_report(request)
    excluded_snapshots = {E.EXECUTIVE_REPORT, E.RENDER_CONTRACT} if trend_report else set()
    legacy_snapshots = tuple(
        PreviousEngineSnapshotV3(
            OrchestrationEngineCodeV3(item.engine_code.value),
            EngineExecutionStatusV3(item.execution_status.value),
                item.engine_schema_version_used, item.engine_model_version_used,
                item.input_fingerprint, item.fingerprint_schema_version,
            None if item.result is None else EngineResultEnvelopeV3(
                OrchestrationEngineCodeV3(item.result.engine_code.value),
                item.result.result_kind, item.result.result,
            ),
        )
        for item in snapshot.engine_snapshots
        if item.engine_code is not E.MULTI_PERIOD_TREND and item.engine_code not in excluded_snapshots
    )
    legacy_snapshot = PreviousExecutionSnapshotV3(
        snapshot.previous_run_id, compute_request_fingerprint_v3(base),
        "3.0.0", "3.0.0", "3.0.0", legacy_snapshots,
    )
    return OrchestrationRunRequestV3(
        request.run_id, request.correlation_id, request.generated_at, outputs,
        legacy_inputs, legacy_options, legacy_snapshot,
    )


def _map_legacy_record(record) -> PerEngineExecutionRecordV4:
    code = E(record.engine_code.value)
    error = None if record.error is None else StructuredErrorV4(
        OrchestrationErrorCategoryV4(record.error.category.value), code,
        record.error.message_tr,
        record.error.cash_flow_error_code.value if record.error.cash_flow_error_code else None,
        record.error.retryable,
    )
    envelope = None if record.result is None else EngineResultEnvelopeV4(
        code, record.result.result_kind, record.result.result,
    )
    return PerEngineExecutionRecordV4(
        code, EngineExecutionStatusV4(record.status.value), envelope,
        record.inner_status_value, error,
        tuple(E(item.value) for item in record.dependency_engine_codes),
        record.engine_schema_version_used, record.engine_model_version_used,
        record.input_fingerprint, record.fingerprint_schema_version,
    )


def _run_status(records: dict[E, PerEngineExecutionRecordV4], cancelled: bool) -> RunStatusV4:
    if cancelled:
        return RunStatusV4.CANCELLED
    statuses = tuple(item.status for item in records.values())
    if not statuses or not any(item in _ALIVE for item in statuses):
        return RunStatusV4.FAILED
    if any(item in {EngineExecutionStatusV4.FAILED, EngineExecutionStatusV4.SKIPPED} for item in statuses):
        return RunStatusV4.PARTIALLY_COMPLETED
    if EngineExecutionStatusV4.DEGRADED in statuses:
        return RunStatusV4.COMPLETED_WITH_DEGRADATIONS
    return RunStatusV4.FULLY_COMPLETED


def _failure(request, fingerprint, category, *, code=None, records=()):
    error = StructuredErrorV4(category, code, _SAFE_MESSAGES[category], None, False)
    return OrchestrationRunResultV4(
        request.run_id, request.correlation_id, request.generated_at, RunStatusV4.FAILED,
        tuple(records), (), (error,), ExecutionProvenanceV4(EXECUTION_PLAN_VERSION_V4, (), (), ()), (),
        ORCHESTRATION_SCHEMA_VERSION_V4, ORCHESTRATION_MODEL_VERSION_V4,
        EXECUTION_PLAN_VERSION_V4, fingerprint,
    ), None


def _trend_report_projection(request, trend_record):
    context = request.engine_inputs.trend_pre_resolved_context
    if context is None:
        raise ValueError("Trend-aware report requires trusted Trend context")
    first = context.resolved_series[0]
    result = None
    if trend_record is not None and trend_record.result is not None:
        candidate = trend_record.result.result
        if type(candidate) is not MultiPeriodTrendResult:
            raise TypeError("Trend report input envelope is invalid")
        result = candidate
    failure_status = None
    failure_codes: tuple[str, ...] = ()
    if result is None and trend_record is not None:
        if trend_record.inner_status_value in {
            TrendComputationStatus.INVALID_INPUT.value,
            TrendComputationStatus.INTEGRITY_FAILURE.value,
            TrendComputationStatus.INSUFFICIENT_DATA.value,
        }:
            failure_status = TrendComputationStatus(trend_record.inner_status_value)
        if trend_record.error is not None and trend_record.error.safe_code is not None:
            failure_codes = (trend_record.error.safe_code,)
    return project_trend_report_source_v1_2(
        requested=True,
        result=result,
        expected_company_id=first.company_id,
        expected_anchor_period_id=first.anchor_period_id,
        verified_result_digest=None if result is None else canonical_trend_digest(result),
        verified_result_reference=None if result is None else canonical_trend_reference(result),
        failure_status=failure_status,
        failure_error_codes=failure_codes,
    )


def _integrate_trend_aware_report(
    request: OrchestrationRunRequestV4,
    records: dict[E, PerEngineExecutionRecordV4],
    snapshot,
    reused: list[E],
    call_sequence: list[E],
    errors: list[StructuredErrorV4],
) -> None:
    if not _wants_trend_report(request):
        return
    base_record = records.get(E.EXECUTIVE_REPORT)
    trend_record = records.get(E.MULTI_PERIOD_TREND)
    if base_record is None:
        return
    dependencies = ENGINE_DEPENDENCY_REGISTRY_V4[E.EXECUTIVE_REPORT].dependency
    upstream = {
        code: record.input_fingerprint
        for code in dependencies.all_of + dependencies.optional
        if (record := records.get(code)) is not None
    }
    if trend_record is not None:
        trend_state = (
            canonical_trend_digest(trend_record.result.result)
            if trend_record.result is not None
            else canonical_trend_digest((trend_record.status, trend_record.inner_status_value, trend_record.error.safe_code if trend_record.error else None))
        )
        upstream[E.MULTI_PERIOD_TREND] = trend_state
    input_fp = compute_engine_input_fingerprint_v4(E.EXECUTIVE_REPORT, request, upstream)
    old = next((item for item in snapshot.engine_snapshots if item.engine_code is E.EXECUTIVE_REPORT), None) if snapshot else None
    dependency_codes = dependencies.all_of + dependencies.any_of + dependencies.optional
    dependency_reused = all(
        code not in records or code in reused
        for code in dependency_codes
    )
    if old is not None and old.execution_status in {EngineExecutionStatusV4.COMPLETED, EngineExecutionStatusV4.DEGRADED}:
        if (
            old.engine_schema_version_used,
            old.engine_model_version_used,
            old.fingerprint_schema_version,
        ) != (REPORT_SCHEMA_VERSION_V1_2_TREND, REPORT_MODEL_VERSION_V1_2_TREND, FINGERPRINT_SCHEMA_VERSION_V4):
            error = StructuredErrorV4(
                OrchestrationErrorCategoryV4.VERSION_INCOMPATIBLE_ON_REUSE,
                E.EXECUTIVE_REPORT,
                _SAFE_MESSAGES[OrchestrationErrorCategoryV4.VERSION_INCOMPATIBLE_ON_REUSE],
                None,
                False,
            )
            errors.append(error)
            records[E.EXECUTIVE_REPORT] = replace(base_record, status=EngineExecutionStatusV4.FAILED, result=None, error=error, input_fingerprint=input_fp)
            return
        if old.input_fingerprint != input_fp or old.result is None or type(old.result.result) is not ExecutiveReportResult:
            error = StructuredErrorV4(
                OrchestrationErrorCategoryV4.FINGERPRINT_MISMATCH_ON_REUSE,
                E.EXECUTIVE_REPORT,
                _SAFE_MESSAGES[OrchestrationErrorCategoryV4.FINGERPRINT_MISMATCH_ON_REUSE],
                None,
                False,
            )
            errors.append(error)
            records[E.EXECUTIVE_REPORT] = replace(base_record, status=EngineExecutionStatusV4.FAILED, result=None, error=error, input_fingerprint=input_fp)
            return
        if dependency_reused:
            records[E.EXECUTIVE_REPORT] = PerEngineExecutionRecordV4(
                E.EXECUTIVE_REPORT,
                EngineExecutionStatusV4.REUSED,
                old.result,
                old.result.result.status.value,
                None,
                dependency_codes,
                REPORT_SCHEMA_VERSION_V1_2_TREND,
                REPORT_MODEL_VERSION_V1_2_TREND,
                input_fp,
                FINGERPRINT_SCHEMA_VERSION_V4,
            )
            reused.append(E.EXECUTIVE_REPORT)
            call_sequence.append(E.EXECUTIVE_REPORT)
            return
    if base_record.result is None or type(base_record.result.result) is not ExecutiveReportResult:
        return
    try:
        projection = _trend_report_projection(request, trend_record)
        report = integrate_trend_report_v1_2(base_record.result.result, projection)
        status = (
            EngineExecutionStatusV4.COMPLETED
            if projection.status.value == "complete" and base_record.status is EngineExecutionStatusV4.COMPLETED
            else EngineExecutionStatusV4.DEGRADED
        )
        records[E.EXECUTIVE_REPORT] = PerEngineExecutionRecordV4(
            E.EXECUTIVE_REPORT,
            status,
            EngineResultEnvelopeV4(E.EXECUTIVE_REPORT, "ExecutiveReportResult", report),
            projection.status.value,
            None,
            dependency_codes,
            REPORT_SCHEMA_VERSION_V1_2_TREND,
            REPORT_MODEL_VERSION_V1_2_TREND,
            input_fp,
            FINGERPRINT_SCHEMA_VERSION_V4,
        )
        call_sequence.append(E.EXECUTIVE_REPORT)
    except Exception:
        error = StructuredErrorV4(
            OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION,
            E.EXECUTIVE_REPORT,
            _SAFE_MESSAGES[OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION],
            None,
            False,
        )
        errors.append(error)
        records[E.EXECUTIVE_REPORT] = replace(
            base_record,
            status=EngineExecutionStatusV4.FAILED,
            result=None,
            error=error,
            engine_schema_version_used=REPORT_SCHEMA_VERSION_V1_2_TREND,
            engine_model_version_used=REPORT_MODEL_VERSION_V1_2_TREND,
            input_fingerprint=input_fp,
            fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION_V4,
        )


def _refresh_render_contract(
    request: OrchestrationRunRequestV4,
    records: dict[E, PerEngineExecutionRecordV4],
    call_sequence: list[E],
    errors: list[StructuredErrorV4],
) -> None:
    if not (
        E.MULTI_PERIOD_TREND in request.requested_outputs
        and E.RENDER_CONTRACT in request.requested_outputs
    ):
        return
    report_record = records.get(E.EXECUTIVE_REPORT)
    base = records.get(E.RENDER_CONTRACT)
    if report_record is None or report_record.result is None or base is None:
        return
    input_fp = compute_engine_input_fingerprint_v4(
        E.RENDER_CONTRACT,
        request,
        {E.EXECUTIVE_REPORT: canonical_report_presentation_digest_v1_2(report_record.result.result)},
    )
    try:
        rendered = ORCHESTRATOR_ENGINE_DISPATCH_V4[E.RENDER_CONTRACT](
            report_record.result.result,
            request.run_options.render_contract,
        )
        records[E.RENDER_CONTRACT] = PerEngineExecutionRecordV4(
            E.RENDER_CONTRACT,
            EngineExecutionStatusV4.COMPLETED,
            EngineResultEnvelopeV4(E.RENDER_CONTRACT, "RenderContractPreview", rendered),
            None,
            None,
            (E.EXECUTIVE_REPORT,),
            base.engine_schema_version_used,
            base.engine_model_version_used,
            input_fp,
            FINGERPRINT_SCHEMA_VERSION_V4,
        )
        call_sequence.append(E.RENDER_CONTRACT)
    except Exception:
        error = StructuredErrorV4(
            OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION,
            E.RENDER_CONTRACT,
            _SAFE_MESSAGES[OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION],
            None,
            False,
        )
        errors.append(error)
        records[E.RENDER_CONTRACT] = replace(base, status=EngineExecutionStatusV4.FAILED, result=None, error=error, input_fingerprint=input_fp)


def run_orchestration_v4(
    request: OrchestrationRunRequestV4,
    *, cancellation_probe: Callable[[], bool] | None = None,
    timing_probe=None,
):
    if type(request) is not OrchestrationRunRequestV4:
        raise TypeError("run_orchestration_v4 accepts only V4 requests")
    if not request.requested_outputs:
        return _failure(request, "", OrchestrationErrorCategoryV4.INVALID_RUN_REQUEST)
    request_fp = compute_request_fingerprint_v4(request)
    snapshot = request.previous_execution_snapshot
    if snapshot is not None and snapshot.request_fingerprint != request_fp:
        return _failure(request, request_fp, OrchestrationErrorCategoryV4.FINGERPRINT_MISMATCH_ON_REUSE)

    records: dict[E, PerEngineExecutionRecordV4] = {}
    call_sequence: list[E] = []
    reused: list[E] = []
    skipped: list[E] = []
    errors: list[StructuredErrorV4] = []
    cancelled = False
    legacy_request = _legacy_request(request)
    if legacy_request is not None:
        legacy_result, _ = run_orchestration_v3(
            legacy_request, cancellation_probe=cancellation_probe, timing_probe=timing_probe,
        )
        for item in legacy_result.engine_records:
            mapped = _map_legacy_record(item)
            records[mapped.engine_code] = mapped
        deferred = (
            {E.EXECUTIVE_REPORT, E.RENDER_CONTRACT}
            if _wants_trend_report(request)
            else set()
        )
        call_sequence.extend(
            code for item in legacy_result.execution_provenance.engine_call_sequence
            if (code := E(item.value)) not in deferred
        )
        reused.extend(
            code for item in legacy_result.execution_provenance.reused_engine_codes
            if (code := E(item.value)) not in deferred
        )
        skipped.extend(E(item.value) for item in legacy_result.execution_provenance.skipped_engine_codes)
        errors.extend(item.error for item in records.values() if item.error is not None)
        cancelled = legacy_result.status.value == "cancelled"

    if E.MULTI_PERIOD_TREND in request.requested_outputs:
        code = E.MULTI_PERIOD_TREND
        context = request.engine_inputs.trend_pre_resolved_context
        input_fp = compute_engine_input_fingerprint_v4(code, request, {})
        old = next((item for item in snapshot.engine_snapshots if item.engine_code is code), None) if snapshot else None
        if cancelled or (cancellation_probe and cancellation_probe()):
            cancelled = True
            skipped.append(code)
            records[code] = PerEngineExecutionRecordV4(
                code, EngineExecutionStatusV4.SKIPPED, None, None, None, (),
                None, None, input_fp, FINGERPRINT_SCHEMA_VERSION_V4,
            )
        elif snapshot is not None and old is None:
            return _failure(request, request_fp, OrchestrationErrorCategoryV4.RESUME_LINEAGE_INTEGRITY_FAILURE, code=code, records=records.values())
        elif old is not None:
            version_ok = (
                old.engine_schema_version_used, old.engine_model_version_used,
                old.fingerprint_schema_version,
            ) == ("1.0.0", "1.0.0", FINGERPRINT_SCHEMA_VERSION_V4)
            proof_ok = (
                old.trend_source_set_digest == context.source_set_digest
                and old.trend_resolution_digest == context.resolution_digest
                and old.trend_registry_digest == context.metric_registry_digest
                and old.trend_policy_version == context.policy_version.value
                and old.trend_lineage_verified is True
                and old.result is not None
                and type(old.result.result) is MultiPeriodTrendResult
            )
            if not version_ok:
                return _failure(request, request_fp, OrchestrationErrorCategoryV4.VERSION_INCOMPATIBLE_ON_REUSE, code=code, records=records.values())
            if old.input_fingerprint != input_fp:
                return _failure(request, request_fp, OrchestrationErrorCategoryV4.FINGERPRINT_MISMATCH_ON_REUSE, code=code, records=records.values())
            if not proof_ok:
                return _failure(request, request_fp, OrchestrationErrorCategoryV4.RESUME_LINEAGE_INTEGRITY_FAILURE, code=code, records=records.values())
            records[code] = PerEngineExecutionRecordV4(
                code, EngineExecutionStatusV4.REUSED, old.result, old.result.result.status.value,
                None, (), "1.0.0", "1.0.0", input_fp, FINGERPRINT_SCHEMA_VERSION_V4,
            )
            reused.append(code)
            call_sequence.append(code)
        else:
            try:
                raw = ORCHESTRATOR_ENGINE_DISPATCH_V4[code](pre_resolved_context=context)
                if type(raw) is not MultiPeriodTrendResult:
                    raise TypeError("Trend dispatch returned an invalid result type")
                if raw.status in {TrendComputationStatus.INVALID_INPUT, TrendComputationStatus.INTEGRITY_FAILURE}:
                    raise TrendResultAssemblyError(raw.status)
                status = EngineExecutionStatusV4.COMPLETED if raw.status is TrendComputationStatus.COMPLETE else EngineExecutionStatusV4.DEGRADED
                envelope = EngineResultEnvelopeV4(code, "TrendAnalysisResult", raw)
                records[code] = PerEngineExecutionRecordV4(
                    code, status, envelope, raw.status.value, None, (), "1.0.0", "1.0.0",
                    input_fp, FINGERPRINT_SCHEMA_VERSION_V4,
                )
                call_sequence.append(code)
            except TrendResultAssemblyError as exc:
                error = StructuredErrorV4(
                    OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION, code,
                    _SAFE_MESSAGES[OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION],
                    exc.status.value, False,
                )
                errors.append(error)
                records[code] = PerEngineExecutionRecordV4(
                    code, EngineExecutionStatusV4.FAILED, None, exc.status.value, error, (),
                    "1.0.0", "1.0.0", input_fp, FINGERPRINT_SCHEMA_VERSION_V4,
                )
            except Exception:
                error = StructuredErrorV4(
                    OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION, code,
                    _SAFE_MESSAGES[OrchestrationErrorCategoryV4.ENGINE_CONTRACT_VIOLATION], None, False,
                )
                errors.append(error)
                records[code] = PerEngineExecutionRecordV4(
                    code, EngineExecutionStatusV4.FAILED, None, TrendComputationStatus.INTEGRITY_FAILURE.value,
                    error, (), "1.0.0", "1.0.0", input_fp, FINGERPRINT_SCHEMA_VERSION_V4,
                )

    _integrate_trend_aware_report(request, records, snapshot, reused, call_sequence, errors)
    _refresh_render_contract(request, records, call_sequence, errors)
    actual_calls = set(call_sequence)
    call_sequence = [code for code in EXECUTION_PLAN_V4 if code in actual_calls]
    reused_set = set(reused)
    reused = [code for code in EXECUTION_PLAN_V4 if code in reused_set]
    skipped_set = set(skipped)
    skipped = [code for code in EXECUTION_PLAN_V4 if code in skipped_set]
    ordered = tuple(records[code] for code in EXECUTION_PLAN_V4 if code in records)
    inventory = tuple(sorted(
        (f"{record.engine_code.value}_model_version", record.engine_model_version_used)
        for record in ordered if record.engine_model_version_used
    ))
    return OrchestrationRunResultV4(
        request.run_id, request.correlation_id, request.generated_at, _run_status(records, cancelled),
        ordered, (), tuple(errors),
        ExecutionProvenanceV4(EXECUTION_PLAN_VERSION_V4, tuple(call_sequence), tuple(reused), tuple(skipped)),
        inventory, ORCHESTRATION_SCHEMA_VERSION_V4, ORCHESTRATION_MODEL_VERSION_V4,
        EXECUTION_PLAN_VERSION_V4, request_fp,
    ), None
