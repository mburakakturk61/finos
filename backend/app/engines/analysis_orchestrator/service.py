"""
Milestone 5.0A -- Analysis Orchestrator: `run_orchestration()` (Bolum 6/9/
10/26/31/45/60).

Bu modul HICBIR finansal hesaplama YAPMAZ -- yalnizca 9 motoru (10 motor
kodu -- Financial Statements iki ayri kod) dogru sirada, dogru girdilerle
cagirir, durumlarini gozlemler ve tek bir run-seviyeli sonuc uretir.
`docs/FINOS_MILESTONE_5_0A_ANALYSIS_ORCHESTRATOR_DESIGN.md` (v2, FINAL) bu
dosyanin TEK bagimsiz otoritesidir.

Kesin kurallar (bu dosyanin ihlal ETMEMESI gereken):
  - v1 TAMAMEN siralidir -- HICBIR ThreadPoolExecutor/async/paralellik (Bolum 7).
  - Orchestrator kendi saatini/kimligini URETMEZ -- `run_id`/`correlation_id`/
    `generated_at` CAGIRAN tarafindan saglanir; `timing_probe` de yalnizca
    CAGIRAN tarafindan enjekte edilirse kullanilir (Bolum 47/48).
  - Bir motorun sonucuna erisimin TEK yolu `engine_records`'tir -- ikinci
    bir depolama alani YOK (Bolum 23/30).
  - `StructuredError.message_tr` HER ZAMAN sabit bir sablon metindir --
    motorun ham exception mesaji hicbir zaman BIREBIR tasinmaz (Bolum 25).
"""

from __future__ import annotations

from typing import Any, Callable

from app.engines.analysis_orchestrator.dispatch import ORCHESTRATOR_ENGINE_DISPATCH
from app.engines.analysis_orchestrator.execution_plan import get_execution_plan
from app.engines.analysis_orchestrator.fingerprint import (
    canonical_hash,
    compute_engine_input_fingerprint,
)
from app.engines.analysis_orchestrator.registry import ENGINE_DEPENDENCY_REGISTRY
from app.engines.analysis_orchestrator.types import (
    EXECUTION_PLAN_VERSION,
    FINGERPRINT_SCHEMA_VERSION,
    ORCHESTRATION_MODEL_VERSION,
    ORCHESTRATION_SCHEMA_VERSION,
    EngineCode,
    EngineExecutionStatus,
    EngineResultEnvelope,
    ExecutionProvenance,
    ExecutionTelemetry,
    OrchestrationErrorCategory,
    OrchestrationRunRequest,
    OrchestrationRunResult,
    PerEngineExecutionRecord,
    PerEngineTelemetry,
    RunStatus,
    StructuredError,
    TimingProbe,
)

_ALIVE_STATUSES = (
    EngineExecutionStatus.COMPLETED,
    EngineExecutionStatus.DEGRADED,
    EngineExecutionStatus.REUSED,
)

# Bolum 25 -- guvenlik kurali: SABIT, onceden yazilmis sablon mesajlar.
# Motorun ham exception mesaji BURAYA hicbir zaman BIREBIR tasinmaz.
_MESSAGE_ENGINE_CONTRACT_VIOLATION = (
    "İlgili motor çağrısı geçersiz bir sözleşme kullandı veya beklenmeyen "
    "bir hata ile sonlandı."
)
_MESSAGE_INVALID_REQUEST = "Orkestrasyon çalıştırma isteği geçersiz (requested_outputs boş)."
_MESSAGE_FINGERPRINT_MISMATCH = (
    "Aynı run_id için daha önce farklı bir girdi parmak izi (request_fingerprint) "
    "kaydedilmiş -- bu istek reddedildi."
)
_MESSAGE_CANCELLED = "Çalıştırma, sağlanan cancellation_probe tarafından iptal edildi."


def _empty_result(
    request: OrchestrationRunRequest,
    *,
    status: RunStatus,
    structured_errors: "tuple[StructuredError, ...]",
    request_fingerprint: str,
) -> OrchestrationRunResult:
    return OrchestrationRunResult(
        run_id=request.run_id,
        correlation_id=request.correlation_id,
        generated_at=request.generated_at,
        status=status,
        engine_records=(),
        warnings=(),
        structured_errors=structured_errors,
        execution_provenance=ExecutionProvenance(EXECUTION_PLAN_VERSION, (), (), ()),
        input_version_inventory={},
        orchestration_schema_version=ORCHESTRATION_SCHEMA_VERSION,
        orchestration_model_version=ORCHESTRATION_MODEL_VERSION,
        execution_plan_version=EXECUTION_PLAN_VERSION,
        request_fingerprint=request_fingerprint,
    )


def _compute_request_fingerprint(request: OrchestrationRunRequest) -> str:
    payload = {
        "requested_outputs": request.requested_outputs,
        "engine_inputs": request.engine_inputs,
        "run_options": request.run_options,
    }
    return canonical_hash(payload)


def _required_engine_codes(requested_outputs: "tuple[EngineCode, ...]") -> "set[EngineCode]":
    """Bolum 5 -- istenmeyen opsiyonel motorlar (Executive Report/Dashboard/
    Render Contract) hic calistirilmaz. Transitif kapanis YALNIZCA all_of/
    any_of uzerinden hesaplanir -- `optional` kenarlar bir motoru run'a
    ZORLAMAZ (Bolum 3)."""

    required = set(requested_outputs)
    changed = True
    while changed:
        changed = False
        for code in list(required):
            spec = ENGINE_DEPENDENCY_REGISTRY[code]
            for dep in spec.dependency.all_of + spec.dependency.any_of:
                if dep not in required:
                    required.add(dep)
                    changed = True
    return required


def _skipped_record(
    code: EngineCode, *, dependency_engine_codes: "tuple[EngineCode, ...]" = ()
) -> PerEngineExecutionRecord:
    return PerEngineExecutionRecord(
        engine_code=code,
        status=EngineExecutionStatus.SKIPPED,
        result=None,
        inner_status_value=None,
        error=None,
        dependency_engine_codes=dependency_engine_codes,
        engine_schema_version_used=None,
        engine_model_version_used=None,
        input_fingerprint="",
        fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
    )


def _result_of(
    dep_code: EngineCode, records: "dict[EngineCode, PerEngineExecutionRecord]"
) -> Any:
    record = records.get(dep_code)
    if record is None or record.result is None:
        return None
    return record.result.result


_FS_CODES = (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT)


def _dependency_is_satisfied(
    dep_code: EngineCode, records: "dict[EngineCode, PerEngineExecutionRecord]"
) -> bool:
    """
    Bir bagimliligin `all_of`/`any_of` gate'i icin "yeterince canli" olup
    olmadigini belirler. Cogu motor icin bu, genel EngineExecutionStatus
    canliligiyla (COMPLETED/DEGRADED/REUSED) AYNIDIR -- DEGRADED bu
    motorlarin HEPSI icin hala kullanilabilir bir sonuc nesnesi tasir.

    Financial Statements ISTISNASI (Bolum 2.1.1/9.1): `AnalysisStatus.
    FAILED` -> `EngineExecutionStatus.DEGRADED` eslemesi, GERCEKTE
    `result_json=None` (HICBIR kullanilabilir veri YOK) anlamina gelir.
    Bu yuzden RATIO'nun `any_of=(FS_BALANCE_SHEET, FS_INCOME_STATEMENT)`
    gate'i, genel "DEGRADED = canli" kuralini DEGIL, Bolum 3'un kendi
    kesin kuralini ("result_json ürettiyse") kullanmalidir -- aksi halde
    "ikisi de FAILED ise RATIO SKIPPED olur" kurali (Bolum 3) hicbir zaman
    tetiklenemezdi (DEGRADED zaten genel canlilik kontrolunu gecerdi).
    """

    record = records.get(dep_code)
    if record is None or record.status not in _ALIVE_STATUSES:
        return False
    if dep_code in _FS_CODES:
        outcome = record.result.result if record.result is not None else None
        return outcome is not None and getattr(outcome, "result_json", None) is not None
    return True


def _invoke_engine(
    code: EngineCode,
    request: OrchestrationRunRequest,
    records: "dict[EngineCode, PerEngineExecutionRecord]",
) -> Any:
    callable_: Callable[..., Any] = ORCHESTRATOR_ENGINE_DISPATCH[code]
    ei = request.engine_inputs
    ro = request.run_options
    EC = EngineCode

    if code is EC.FS_BALANCE_SHEET:
        return callable_(
            content=ei.balance_sheet_content,
            filename=ei.balance_sheet_filename,
            trial_balance_result=ei.trial_balance_result,
            prior_period_facts=ei.prior_period_balance_sheet_facts,
        )
    if code is EC.FS_INCOME_STATEMENT:
        return callable_(
            content=ei.income_statement_content,
            filename=ei.income_statement_filename,
            trial_balance_result=ei.trial_balance_result,
            prior_period_facts=ei.prior_period_income_statement_facts,
        )
    if code is EC.RATIO:
        bs_outcome = _result_of(EC.FS_BALANCE_SHEET, records)
        is_outcome = _result_of(EC.FS_INCOME_STATEMENT, records)
        return callable_(
            balance_sheet_result=bs_outcome.result_json if bs_outcome is not None else None,
            income_statement_result=is_outcome.result_json if is_outcome is not None else None,
            prior_period_balance_sheet_result=ei.prior_period_balance_sheet_result,
            prior_period_income_statement_result=ei.prior_period_income_statement_result,
            period_start_date=ei.period_start_date,
            period_end_date=ei.period_end_date,
            period_months_covered=ei.period_months_covered,
        )
    if code is EC.BENCHMARK:
        return callable_(
            _result_of(EC.RATIO, records),
            industry_code=ro.industry_code,
            company_size_bucket=ro.company_size_bucket,
        )
    if code is EC.HEALTH_SCORE:
        return callable_(
            _result_of(EC.RATIO, records),
            _result_of(EC.BENCHMARK, records),
            industry_code=ro.industry_code,
            company_size_bucket=ro.company_size_bucket,
            tenant_id=ro.tenant_id,
        )
    if code is EC.CREDIT_SCORE:
        return callable_(
            _result_of(EC.RATIO, records),
            _result_of(EC.BENCHMARK, records),
            _result_of(EC.HEALTH_SCORE, records),
            industry_code=ro.industry_code,
            company_size_bucket=ro.company_size_bucket,
            tenant_id=ro.tenant_id,
        )
    if code is EC.RECOMMENDATION:
        return callable_(
            _result_of(EC.RATIO, records),
            _result_of(EC.BENCHMARK, records),
            _result_of(EC.HEALTH_SCORE, records),
            _result_of(EC.CREDIT_SCORE, records),
            industry_code=ro.industry_code,
            company_size_bucket=ro.company_size_bucket,
            tenant_id=ro.tenant_id,
        )
    if code is EC.EXECUTIVE_REPORT:
        bs_outcome = _result_of(EC.FS_BALANCE_SHEET, records)
        is_outcome = _result_of(EC.FS_INCOME_STATEMENT, records)
        return callable_(
            ro.report_type,
            bs_outcome.result_json if bs_outcome is not None else None,
            is_outcome.result_json if is_outcome is not None else None,
            _result_of(EC.RATIO, records),
            _result_of(EC.BENCHMARK, records),
            _result_of(EC.HEALTH_SCORE, records),
            _result_of(EC.CREDIT_SCORE, records),
            _result_of(EC.RECOMMENDATION, records),
            company_metadata=ro.company_metadata,
            reporting_period_label_tr=ro.reporting_period_label_tr,
            optional_sections=ro.optional_sections,
            report_id=request.run_id,
            generated_at=request.generated_at,
            locale=ro.locale,
            currency_display_policy=ro.currency_display_policy,
        )
    if code is EC.DASHBOARD:
        return callable_(
            ro.dashboard_type,
            _result_of(EC.HEALTH_SCORE, records),
            _result_of(EC.CREDIT_SCORE, records),
            _result_of(EC.RECOMMENDATION, records),
            benchmark_result_json=_result_of(EC.BENCHMARK, records),
            company_metadata=ro.company_metadata,
            report_id=request.run_id,
            generated_at=request.generated_at,
        )
    if code is EC.RENDER_CONTRACT:
        return callable_(_result_of(EC.EXECUTIVE_REPORT, records), ro.render_contract)

    raise ValueError(f"Bilinmeyen engine_code: {code!r}")  # pragma: no cover


def _ratio_result_is_fully_not_calculable(result: "dict[str, Any]") -> bool:
    categories = result.get("categories", {})
    if not categories:
        return True
    return all(cat.get("status") == "not_calculable" for cat in categories.values())


def _benchmark_result_has_any_evaluated(result: "dict[str, Any]") -> bool:
    categories = result.get("categories", {})
    for cat in categories.values():
        for ratio_entry in cat.get("ratios", {}).values():
            if ratio_entry.get("status") == "evaluated":
                return True
    return False


def _map_inner_status(code: EngineCode, raw_result: Any) -> "tuple[EngineExecutionStatus, str | None]":
    """Bolum 9.1 -- tam ic-durum esleme tablosunun birebir kodu."""

    EC = EngineCode

    if code in (EC.FS_BALANCE_SHEET, EC.FS_INCOME_STATEMENT):
        value = raw_result.status.value
        return (EngineExecutionStatus.COMPLETED if value == "completed" else EngineExecutionStatus.DEGRADED), value

    if code is EC.RATIO:
        if _ratio_result_is_fully_not_calculable(raw_result):
            return EngineExecutionStatus.DEGRADED, "not_calculable"
        return EngineExecutionStatus.COMPLETED, "calculated"

    if code is EC.BENCHMARK:
        if _benchmark_result_has_any_evaluated(raw_result):
            return EngineExecutionStatus.COMPLETED, "evaluated"
        return EngineExecutionStatus.DEGRADED, "not_calculable"

    if code in (EC.HEALTH_SCORE, EC.CREDIT_SCORE, EC.EXECUTIVE_REPORT):
        value = raw_result.status.value
        return (EngineExecutionStatus.COMPLETED if value == "computed" else EngineExecutionStatus.DEGRADED), value

    if code is EC.RECOMMENDATION:
        value = raw_result.status.value
        is_completed = value in ("computed", "no_recommendations_triggered")
        return (EngineExecutionStatus.COMPLETED if is_completed else EngineExecutionStatus.DEGRADED), value

    if code is EC.DASHBOARD:
        if len(raw_result.widgets) == 0:
            return EngineExecutionStatus.DEGRADED, "incompatible"
        return EngineExecutionStatus.COMPLETED, "compatible"

    if code is EC.RENDER_CONTRACT:
        # Bu motorun kendi bir computation-status'u YOKTUR -- basarili
        # donus HER ZAMAN COMPLETED'tir, DEGRADED yapisal olarak imkansizdir.
        return EngineExecutionStatus.COMPLETED, None

    raise ValueError(f"Bilinmeyen engine_code: {code!r}")  # pragma: no cover


def _extract_versions(code: EngineCode, raw_result: Any) -> "tuple[str | None, str | None]":
    EC = EngineCode

    if code in (EC.FS_BALANCE_SHEET, EC.FS_INCOME_STATEMENT):
        rj = raw_result.result_json
        if rj is None:
            return None, None
        return None, rj.get("engine_version")
    if code is EC.RATIO:
        return raw_result.get("schema_version"), raw_result.get("ratio_registry_version")
    if code is EC.BENCHMARK:
        return None, raw_result.get("benchmark_registry_version")
    if code is EC.HEALTH_SCORE:
        return raw_result.health_score_schema_version, raw_result.health_score_model_version
    if code is EC.CREDIT_SCORE:
        return raw_result.credit_score_schema_version, raw_result.credit_score_model_version
    if code is EC.RECOMMENDATION:
        return raw_result.recommendation_schema_version, raw_result.recommendation_model_version
    if code is EC.EXECUTIVE_REPORT:
        return raw_result.report_schema_version, raw_result.report_model_version
    if code is EC.DASHBOARD:
        return raw_result.dashboard_schema_version, raw_result.dashboard_model_version
    if code is EC.RENDER_CONTRACT:
        return raw_result.render_metadata.render_contract_schema_version, None

    raise ValueError(f"Bilinmeyen engine_code: {code!r}")  # pragma: no cover


def _compute_run_status(
    records: "dict[EngineCode, PerEngineExecutionRecord]", *, cancelled: bool
) -> RunStatus:
    """Bolum 10 -- 5 degerli, ayrik RunStatus hesaplamasi. TUM uretilen
    kayitlar (yalnizca dogrudan requested_outputs degil, transitif olarak
    gereken TUMU) dikkate alinir -- bir upstream'in DEGRADED olmasi run'in
    FULLY_COMPLETED sayilmasini ENGELLER (denetim bulgusu F1'in kok-neden
    cozumunun calisma-zamani karsiligi)."""

    if cancelled:
        return RunStatus.CANCELLED

    statuses = [record.status for record in records.values()]
    if not statuses:
        return RunStatus.FAILED

    has_alive = any(status in _ALIVE_STATUSES for status in statuses)
    if not has_alive:
        return RunStatus.FAILED

    has_failed_or_skipped = any(
        status in (EngineExecutionStatus.FAILED, EngineExecutionStatus.SKIPPED) for status in statuses
    )
    if has_failed_or_skipped:
        return RunStatus.PARTIALLY_COMPLETED

    has_degraded = any(status == EngineExecutionStatus.DEGRADED for status in statuses)
    if has_degraded:
        return RunStatus.COMPLETED_WITH_DEGRADATIONS

    return RunStatus.FULLY_COMPLETED


def run_orchestration(
    request: OrchestrationRunRequest,
    *,
    cancellation_probe: "Callable[[], bool] | None" = None,
    timing_probe: "TimingProbe | None" = None,
) -> "tuple[OrchestrationRunResult, ExecutionTelemetry | None]":
    """TEK genel API -- Bolum 60. Senkron, tamamen sirali, DB'siz, API'siz."""

    if not request.requested_outputs:
        error = StructuredError(
            category=OrchestrationErrorCategory.INVALID_RUN_REQUEST,
            engine_code=None,
            message_tr=_MESSAGE_INVALID_REQUEST,
        )
        return _empty_result(
            request, status=RunStatus.FAILED, structured_errors=(error,), request_fingerprint=""
        ), None

    request_fingerprint = _compute_request_fingerprint(request)

    snapshot = request.previous_execution_snapshot
    if (
        snapshot is not None
        and snapshot.previous_run_id == request.run_id
        and snapshot.request_fingerprint != request_fingerprint
    ):
        error = StructuredError(
            category=OrchestrationErrorCategory.FINGERPRINT_MISMATCH_ON_REUSE,
            engine_code=None,
            message_tr=_MESSAGE_FINGERPRINT_MISMATCH,
        )
        return _empty_result(
            request,
            status=RunStatus.FAILED,
            structured_errors=(error,),
            request_fingerprint=request_fingerprint,
        ), None

    plan = get_execution_plan()
    required = _required_engine_codes(request.requested_outputs)
    ordered_targets = tuple(code for code in plan if code in required)

    previous_by_code = (
        {s.engine_code: s for s in snapshot.engine_snapshots} if snapshot is not None else {}
    )

    records: "dict[EngineCode, PerEngineExecutionRecord]" = {}
    output_fingerprints: "dict[EngineCode, str]" = {}
    reused_codes: "list[EngineCode]" = []
    skipped_codes: "list[EngineCode]" = []
    call_sequence: "list[EngineCode]" = []
    structured_errors: "list[StructuredError]" = []
    version_inventory: "dict[str, str]" = {}
    per_engine_telemetry: "list[PerEngineTelemetry]" = []
    cancelled = False

    start_time = timing_probe.now() if timing_probe is not None else None

    for code in ordered_targets:
        if not cancelled and cancellation_probe is not None and cancellation_probe():
            cancelled = True
            structured_errors.append(
                StructuredError(OrchestrationErrorCategory.CANCELLED, None, _MESSAGE_CANCELLED)
            )

        if cancelled:
            skipped_codes.append(code)
            records[code] = _skipped_record(code)
            continue

        spec = ENGINE_DEPENDENCY_REGISTRY[code]
        dep = spec.dependency

        all_ok = all(_dependency_is_satisfied(d, records) for d in dep.all_of)
        any_ok = any(_dependency_is_satisfied(d, records) for d in dep.any_of) if dep.any_of else True

        if not (all_ok and any_ok):
            skipped_codes.append(code)
            records[code] = _skipped_record(
                code, dependency_engine_codes=dep.all_of + dep.any_of + dep.optional
            )
            continue

        input_fp = compute_engine_input_fingerprint(
            code,
            raw_inputs=request.engine_inputs,
            run_options=request.run_options,
            upstream_fingerprints=output_fingerprints,
        )

        alive_deps_consulted = tuple(dep.all_of) + tuple(
            d for d in dep.any_of if _dependency_is_satisfied(d, records)
        )
        deps_reused_ok = all(d in reused_codes for d in alive_deps_consulted)

        previous = previous_by_code.get(code)
        reusable = (
            previous is not None
            and previous.execution_status
            in (EngineExecutionStatus.COMPLETED, EngineExecutionStatus.DEGRADED)
            and previous.input_fingerprint == input_fp
            and previous.fingerprint_schema_version == FINGERPRINT_SCHEMA_VERSION
            and deps_reused_ok
        )

        dependency_engine_codes = dep.all_of + dep.any_of + dep.optional
        t0 = timing_probe.now() if timing_probe is not None else None

        if reusable:
            envelope = (
                EngineResultEnvelope(code, spec.produces, previous.result_ref)
                if previous.result_ref is not None
                else None
            )
            records[code] = PerEngineExecutionRecord(
                engine_code=code,
                status=EngineExecutionStatus.REUSED,
                result=envelope,
                inner_status_value=None,
                error=None,
                dependency_engine_codes=dependency_engine_codes,
                engine_schema_version_used=previous.engine_schema_version_used,
                engine_model_version_used=previous.engine_model_version_used,
                input_fingerprint=input_fp,
                fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
            )
            reused_codes.append(code)
            call_sequence.append(code)
            if previous.result_ref is not None:
                output_fingerprints[code] = canonical_hash(previous.result_ref)
            if timing_probe is not None:
                t1 = timing_probe.now()
                per_engine_telemetry.append(
                    PerEngineTelemetry(
                        code,
                        (t0 - start_time) * 1000 if start_time is not None else None,
                        (t1 - t0) * 1000,
                    )
                )
            continue

        try:
            raw_result = _invoke_engine(code, request, records)
        except Exception as exc:  # noqa: BLE001 -- kasitli genis yakalama (Eksen B guvenligi)
            structured_error = StructuredError(
                category=OrchestrationErrorCategory.ENGINE_CONTRACT_VIOLATION,
                engine_code=code,
                message_tr=_MESSAGE_ENGINE_CONTRACT_VIOLATION,
                original_exception_type=type(exc).__name__,
            )
            structured_errors.append(structured_error)
            records[code] = PerEngineExecutionRecord(
                engine_code=code,
                status=EngineExecutionStatus.FAILED,
                result=None,
                inner_status_value=None,
                error=structured_error,
                dependency_engine_codes=dependency_engine_codes,
                engine_schema_version_used=None,
                engine_model_version_used=None,
                input_fingerprint=input_fp,
                fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
            )
            call_sequence.append(code)
            if timing_probe is not None:
                t1 = timing_probe.now()
                per_engine_telemetry.append(
                    PerEngineTelemetry(
                        code,
                        (t0 - start_time) * 1000 if start_time is not None else None,
                        (t1 - t0) * 1000,
                    )
                )
            continue

        status, inner_status_value = _map_inner_status(code, raw_result)
        schema_v, model_v = _extract_versions(code, raw_result)
        if schema_v:
            version_inventory[f"{code.value}_schema_version"] = schema_v
        if model_v:
            version_inventory[f"{code.value}_model_version"] = model_v

        records[code] = PerEngineExecutionRecord(
            engine_code=code,
            status=status,
            result=EngineResultEnvelope(code, spec.produces, raw_result),
            inner_status_value=inner_status_value,
            error=None,
            dependency_engine_codes=dependency_engine_codes,
            engine_schema_version_used=schema_v,
            engine_model_version_used=model_v,
            input_fingerprint=input_fp,
            fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
        )
        call_sequence.append(code)
        output_fingerprints[code] = canonical_hash(raw_result)
        if timing_probe is not None:
            t1 = timing_probe.now()
            per_engine_telemetry.append(
                PerEngineTelemetry(
                    code,
                    (t0 - start_time) * 1000 if start_time is not None else None,
                    (t1 - t0) * 1000,
                )
            )

    run_status = _compute_run_status(records, cancelled=cancelled)
    provenance = ExecutionProvenance(
        execution_plan_version=EXECUTION_PLAN_VERSION,
        engine_call_sequence=tuple(call_sequence),
        reused_engine_codes=tuple(reused_codes),
        skipped_engine_codes=tuple(skipped_codes),
    )

    result = OrchestrationRunResult(
        run_id=request.run_id,
        correlation_id=request.correlation_id,
        generated_at=request.generated_at,
        status=run_status,
        engine_records=tuple(records[code] for code in ordered_targets),
        warnings=(),
        structured_errors=tuple(structured_errors),
        execution_provenance=provenance,
        input_version_inventory=version_inventory,
        orchestration_schema_version=ORCHESTRATION_SCHEMA_VERSION,
        orchestration_model_version=ORCHESTRATION_MODEL_VERSION,
        execution_plan_version=EXECUTION_PLAN_VERSION,
        request_fingerprint=request_fingerprint,
    )

    telemetry = None
    if timing_probe is not None:
        total = (timing_probe.now() - start_time) * 1000 if start_time is not None else None
        telemetry = ExecutionTelemetry(per_engine=tuple(per_engine_telemetry), total_duration_ms=total)

    return result, telemetry
