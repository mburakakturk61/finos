"""
Milestone 5.0A -- Kategori B: Dependency (any_of/all_of) testleri (Bolum
67-B). Denetim bulgusu H2'nin (Financial Statements AND/OR celiskisi)
kok-neden cozumunun calisma-zamani kaniti.
"""

from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineExecutionStatus,
    RunStatus,
    get_ratio_result,
)
from tests._orch_fakes import build_request, fs_outcome, make_constant_fake_dispatch


def _records_by_code(result):
    return {r.engine_code: r for r in result.engine_records}


def test_ratio_runs_when_only_balance_sheet_succeeds():
    overrides = {
        EngineCode.FS_BALANCE_SHEET: fs_outcome(status="completed"),
        EngineCode.FS_INCOME_STATEMENT: fs_outcome(status="failed"),
    }
    fake = make_constant_fake_dispatch(overrides)
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RATIO,))
        result, _ = run_orchestration(request)

    records = _records_by_code(result)
    assert records[EngineCode.FS_BALANCE_SHEET].status == EngineExecutionStatus.COMPLETED
    assert records[EngineCode.FS_INCOME_STATEMENT].status == EngineExecutionStatus.DEGRADED
    assert records[EngineCode.RATIO].status in (
        EngineExecutionStatus.COMPLETED,
        EngineExecutionStatus.DEGRADED,
    )
    assert get_ratio_result(result) is not None


def test_ratio_runs_when_only_income_statement_succeeds():
    overrides = {
        EngineCode.FS_BALANCE_SHEET: fs_outcome(status="failed"),
        EngineCode.FS_INCOME_STATEMENT: fs_outcome(status="completed"),
    }
    fake = make_constant_fake_dispatch(overrides)
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RATIO,))
        result, _ = run_orchestration(request)

    records = _records_by_code(result)
    assert records[EngineCode.FS_BALANCE_SHEET].status == EngineExecutionStatus.DEGRADED
    assert records[EngineCode.FS_INCOME_STATEMENT].status == EngineExecutionStatus.COMPLETED
    assert records[EngineCode.RATIO].status != EngineExecutionStatus.SKIPPED


def test_ratio_is_skipped_when_both_financial_statements_fail():
    overrides = {
        EngineCode.FS_BALANCE_SHEET: fs_outcome(status="failed"),
        EngineCode.FS_INCOME_STATEMENT: fs_outcome(status="failed"),
    }
    fake = make_constant_fake_dispatch(overrides)
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RATIO,))
        result, _ = run_orchestration(request)

    records = _records_by_code(result)
    assert records[EngineCode.RATIO].status == EngineExecutionStatus.SKIPPED
    assert result.status == RunStatus.PARTIALLY_COMPLETED


def test_chained_skip_propagates_through_entire_downstream_chain():
    overrides = {
        EngineCode.FS_BALANCE_SHEET: fs_outcome(status="failed"),
        EngineCode.FS_INCOME_STATEMENT: fs_outcome(status="failed"),
    }
    fake = make_constant_fake_dispatch(overrides)
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        result, _ = run_orchestration(request)

    records = _records_by_code(result)
    for code in (
        EngineCode.RATIO,
        EngineCode.BENCHMARK,
        EngineCode.HEALTH_SCORE,
        EngineCode.CREDIT_SCORE,
        EngineCode.RECOMMENDATION,
    ):
        assert records[code].status == EngineExecutionStatus.SKIPPED, code
    # Skip zincirinin dependency_engine_codes'u dogru izlenmis olmali.
    assert EngineCode.RATIO in records[EngineCode.BENCHMARK].dependency_engine_codes


def test_benchmark_failure_cascades_through_all_of_chain_to_dashboard():
    # Not: DASHBOARD'un `optional=(BENCHMARK,)` kenari, MEVCUT graf
    # topolojisinde (Bolum 4/35) pratikte "gozlemlenemez" bir durumdur --
    # Health/Credit/Recommendation'in KENDI `all_of`'u zaten BENCHMARK'a
    # bagli oldugu icin, Benchmark basarisiz olursa bunlar da SKIPPED olur
    # ve Dashboard transitif olarak SKIPPED olur. Bu test, o cascade'in
    # GERCEKTEN calistigini (optional kenarin, upstream all_of zincirindeki
    # zorunlulugu ORTADAN KALDIRMADIGINI) dogrular. `optional` threading
    # mekanizmasinin KENDISI (Dashboard'un Benchmark'siz cagrilabilmesi)
    # asagidaki test_invoke_engine_passes_none_for_missing_optional_
    # dependency ile izole test edilir.
    fake = make_constant_fake_dispatch()

    def _failing_benchmark(*args, **kwargs):
        raise RuntimeError("kasitli test hatasi")

    fake[EngineCode.BENCHMARK] = _failing_benchmark

    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.DASHBOARD,))
        result, _ = run_orchestration(request)

    records = _records_by_code(result)
    assert records[EngineCode.BENCHMARK].status == EngineExecutionStatus.FAILED
    assert records[EngineCode.HEALTH_SCORE].status == EngineExecutionStatus.SKIPPED
    assert records[EngineCode.DASHBOARD].status == EngineExecutionStatus.SKIPPED


def test_invoke_engine_passes_none_for_missing_optional_dependency():
    # DASHBOARD'un cagri sozlesmesinde `benchmark_result_json` optional bir
    # kwarg'dir (Bolum 2.1.8) -- BENCHMARK'a dair hicbir kayit olmasa bile
    # `_invoke_engine`'in None gecerek cagirabildigini izole dogrular.
    from app.engines.analysis_orchestrator.service import _invoke_engine
    from app.engines.analysis_orchestrator.types import EngineExecutionStatus as _S
    from app.engines.analysis_orchestrator.types import EngineResultEnvelope, PerEngineExecutionRecord

    captured = {}

    def _fake_dashboard(dashboard_type, health, credit, recommendation, *, benchmark_result_json, **kwargs):
        captured["benchmark_result_json"] = benchmark_result_json
        return "ok"

    fake = make_constant_fake_dispatch({EngineCode.DASHBOARD: _fake_dashboard})
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        records = {
            EngineCode.HEALTH_SCORE: PerEngineExecutionRecord(
                EngineCode.HEALTH_SCORE, _S.COMPLETED, EngineResultEnvelope(EngineCode.HEALTH_SCORE, "x", "hs"),
                None, None, (), None, None, "fp", "1.0.0",
            ),
            EngineCode.CREDIT_SCORE: PerEngineExecutionRecord(
                EngineCode.CREDIT_SCORE, _S.COMPLETED, EngineResultEnvelope(EngineCode.CREDIT_SCORE, "x", "cs"),
                None, None, (), None, None, "fp", "1.0.0",
            ),
            EngineCode.RECOMMENDATION: PerEngineExecutionRecord(
                EngineCode.RECOMMENDATION, _S.COMPLETED, EngineResultEnvelope(EngineCode.RECOMMENDATION, "x", "rec"),
                None, None, (), None, None, "fp", "1.0.0",
            ),
            # BENCHMARK icin BILEREK hic kayit yok.
        }
        request = build_request(requested_outputs=(EngineCode.DASHBOARD,))
        _invoke_engine(EngineCode.DASHBOARD, request, records)

    assert captured["benchmark_result_json"] is None
