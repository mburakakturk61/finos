"""
Milestone 5.0A -- Kategori H: Cancellation testleri (Bolum 67-H). Denetim
bulgusu C1'in ("cancellation_token serilestirme celismesi yaratiyordu")
kok-neden cozumunun kaniti: `cancellation_probe` request'in bir ALANI
DEGIL, `run_orchestration()`'in ayri bir cagri parametresidir.
"""

import dataclasses
from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import EngineCode, EngineExecutionStatus, OrchestrationRunRequest, RunStatus
from tests._orch_fakes import build_request, make_constant_fake_dispatch


def test_orchestration_run_request_has_no_callable_fields():
    # Bolum 19: OrchestrationRunRequest TAMAMEN JSON-serilestirilebilir
    # olmalidir -- hicbir Callable alan TASIMAZ.
    for f in dataclasses.fields(OrchestrationRunRequest):
        assert f.name not in ("cancellation_token", "cancellation_probe", "timing_probe")


def test_cancellation_probe_called_before_each_engine_call():
    fake = make_constant_fake_dispatch()
    call_log = []

    def probe():
        call_log.append(len(call_log))
        return False

    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, _ = run_orchestration(request, cancellation_probe=probe)

    assert len(call_log) == len(result.engine_records)
    assert result.status == RunStatus.FULLY_COMPLETED


def test_cancellation_mid_plan_skips_remaining_engines_but_keeps_completed_ones():
    fake = make_constant_fake_dispatch()
    calls = {"n": 0}

    def cancel_after_third_check():
        calls["n"] += 1
        return calls["n"] > 3  # ilk 3 motor calisir, sonrasi iptal

    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, _ = run_orchestration(request, cancellation_probe=cancel_after_third_check)

    records = {r.engine_code: r for r in result.engine_records}
    completed_count = sum(1 for r in result.engine_records if r.status == EngineExecutionStatus.COMPLETED)
    skipped_count = sum(1 for r in result.engine_records if r.status == EngineExecutionStatus.SKIPPED)
    assert completed_count == 3
    assert skipped_count == len(result.engine_records) - 3
    assert result.status == RunStatus.CANCELLED
    # Iptalden SONRAKI motorlar gercekten CAGRILMAMIS (call_sequence'e hic
    # girmemis) olmali.
    assert EngineCode.RECOMMENDATION not in result.execution_provenance.engine_call_sequence
    assert len(result.execution_provenance.engine_call_sequence) == 3


def test_a_running_engine_call_cannot_be_interrupted_mid_call():
    # Bolum 15'in kesin siniri: cancellation_probe yalnizca motor
    # CAGRILARI ARASINDA etkilidir -- zaten baslamis/tamamlanmis bir cagri
    # geriye donuk KESILEMEZ. FS_BALANCE_SHEET calisirken probe'u True'ya
    # ceviriyoruz -- bu, FS_BALANCE_SHEET'in KENDI sonucunu ETKILEMEMELI,
    # yalnizca BIR SONRAKI (FS_INCOME_STATEMENT) cagrisini engellemelidir.
    from tests._orch_fakes import fs_outcome

    call_started = {"flag": False}

    def slow_engine(*args, **kwargs):
        call_started["flag"] = True
        return fs_outcome(status="completed")

    fake = make_constant_fake_dispatch({EngineCode.FS_BALANCE_SHEET: slow_engine})

    def probe():
        return call_started["flag"]  # FS_BALANCE_SHEET baslar baslamaz True doner

    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT))
        result, _ = run_orchestration(request, cancellation_probe=probe)

    records = {r.engine_code: r for r in result.engine_records}
    # FS_BALANCE_SHEET zaten baslatildigi/tamamlandigi icin KESILMEDI --
    # sonucu tam ve dogru sekilde COMPLETED olarak kayda gecti.
    assert records[EngineCode.FS_BALANCE_SHEET].status == EngineExecutionStatus.COMPLETED
    # FS_INCOME_STATEMENT ise cagrilmadan ONCE iptal tespit edildigi icin
    # hic CALISTIRILMADI.
    assert records[EngineCode.FS_INCOME_STATEMENT].status == EngineExecutionStatus.SKIPPED
    assert result.status == RunStatus.CANCELLED


def test_cancellation_produces_a_single_structured_cancelled_error():
    fake = make_constant_fake_dispatch()

    def always_cancel():
        return True

    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, _ = run_orchestration(request, cancellation_probe=always_cancel)

    assert result.status == RunStatus.CANCELLED
    assert len(result.structured_errors) == 1
    assert result.structured_errors[0].category.value == "cancelled"
    assert all(r.status == EngineExecutionStatus.SKIPPED for r in result.engine_records)
