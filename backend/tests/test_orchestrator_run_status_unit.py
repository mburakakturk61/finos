"""
Milestone 5.0A -- Kategori D: RunStatus'un 5 degerinin HER BIRI icin ayri
senaryo (Bolum 67-D). `COMPLETED_WITH_DEGRADATIONS` testi, denetim bulgusu
F1'in ("TUM motorlar DEGRADED olsa bile run YANLISLIKLA FULLY_COMPLETED
DONMEZ") kok-neden cozumunun en kritik regresyon testidir.
"""

from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import EngineCode, RunStatus
from tests._orch_fakes import (
    build_request,
    fs_outcome,
    health_score_result,
    make_constant_fake_dispatch,
    ratio_result,
)


def test_run_status_fully_completed_when_nothing_degraded():
    fake = make_constant_fake_dispatch()
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, _ = run_orchestration(request)
    assert result.status == RunStatus.FULLY_COMPLETED


def test_run_status_completed_with_degradations_when_all_engines_degraded():
    # KRITIK regresyon testi (denetim bulgusu F1): TUM motorlar DEGRADED
    # olsa bile run FULLY_COMPLETED DONMEMELIDIR.
    overrides = {
        EngineCode.RATIO: ratio_result(all_not_calculable=True),
        EngineCode.HEALTH_SCORE: health_score_result(status="insufficient_data"),
    }
    fake = make_constant_fake_dispatch(overrides)
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.HEALTH_SCORE,))
        result, _ = run_orchestration(request)

    records = {r.engine_code: r for r in result.engine_records}
    assert records[EngineCode.RATIO].status.value == "degraded"
    assert records[EngineCode.HEALTH_SCORE].status.value == "degraded"
    assert result.status == RunStatus.COMPLETED_WITH_DEGRADATIONS
    assert result.status != RunStatus.FULLY_COMPLETED


def test_run_status_partially_completed_when_some_failed_but_some_alive():
    fake = make_constant_fake_dispatch(
        {
            EngineCode.FS_BALANCE_SHEET: fs_outcome(status="failed"),
            EngineCode.FS_INCOME_STATEMENT: fs_outcome(status="failed"),
        }
    )
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RATIO,))
        result, _ = run_orchestration(request)
    assert result.status == RunStatus.PARTIALLY_COMPLETED


def test_run_status_failed_when_no_alive_records_at_all():
    def _raise(*args, **kwargs):
        raise RuntimeError("kasitli")

    fake = make_constant_fake_dispatch({EngineCode.FS_BALANCE_SHEET: _raise})
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.FS_BALANCE_SHEET,))
        result, _ = run_orchestration(request)
    assert result.status == RunStatus.FAILED


def test_run_status_failed_for_empty_requested_outputs():
    request = build_request(requested_outputs=())
    result, _ = run_orchestration(request)
    assert result.status == RunStatus.FAILED
    assert len(result.structured_errors) == 1
    assert result.structured_errors[0].category.value == "invalid_run_request"


def test_run_status_cancelled_when_cancellation_probe_fires():
    fake = make_constant_fake_dispatch()
    calls = {"n": 0}

    def _cancel_after_first():
        calls["n"] += 1
        return calls["n"] > 1

    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, _ = run_orchestration(request, cancellation_probe=_cancel_after_first)
    assert result.status == RunStatus.CANCELLED
