"""
Milestone 5.0A -- Performans/telemetry sanity testleri (Bolum 68).
Bolum 68'in talimati geregi KESIN sayisal hedefler burada FABRIKE EDILMEZ
-- yalnizca: (a) timing_probe=None iken telemetry uretilmedigi, (b)
timing_probe verildiginde telemetry'nin her calisan motor icin bir kayit
icerdigi ve (c) sahte motorlarla tam zincirin makul (comert, provizyonel)
bir ust sinir icinde tamamlandigi dogrulanir.
"""

import time
from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import EngineCode
from tests._orch_fakes import build_request, make_constant_fake_dispatch


class _RealClockProbe:
    def now(self) -> float:
        return time.perf_counter()


def test_no_telemetry_when_timing_probe_not_provided():
    fake = make_constant_fake_dispatch()
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, telemetry = run_orchestration(request)
    assert telemetry is None
    assert result is not None


def test_telemetry_has_one_entry_per_executed_engine_when_probe_provided():
    fake = make_constant_fake_dispatch()
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, telemetry = run_orchestration(request, timing_probe=_RealClockProbe())

    assert telemetry is not None
    assert len(telemetry.per_engine) == len(result.engine_records)
    assert telemetry.total_duration_ms is not None
    assert telemetry.total_duration_ms >= 0
    for entry in telemetry.per_engine:
        assert entry.duration_ms is not None
        assert entry.duration_ms >= 0


def test_full_fake_chain_completes_within_generous_provisional_bound():
    # Bolum 68: kesin p50/p95 yalnizca gercek Docker olcumuyle kilitlenir.
    # Burada yalnizca "makul olcude hizli" (saniyeler mertebesinde DEGIL)
    # cok comert bir ust sinir dogrulanir -- performans REGRESYONU degil,
    # yapisal bir sonsuz-dongu/deadlock olmadiginin kaniti amaclanir.
    fake = make_constant_fake_dispatch()
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(
            requested_outputs=(
                EngineCode.EXECUTIVE_REPORT,
                EngineCode.DASHBOARD,
                EngineCode.RENDER_CONTRACT,
            )
        )
        start = time.perf_counter()
        result, _ = run_orchestration(request)
        elapsed_seconds = time.perf_counter() - start

    assert len(result.engine_records) == 10
    assert elapsed_seconds < 5.0  # cok comert, provizyonel ust sinir
