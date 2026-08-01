"""
Milestone 5.0A -- Kategori F: Single Source of Truth testleri (Bolum 67-F).
Denetim bulgusu I1'in ("engine_records + ayri adlandirilmis alanlar
duplicate source-of-truth yaratiyordu") kok-neden cozumunun kaniti.
"""

from dataclasses import fields
from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    OrchestrationRunResult,
    OrchestratorResultAccessError,
    get_benchmark_result,
    get_credit_score_result,
    get_health_score_result,
    get_ratio_result,
    get_recommendation_result,
)
from tests._orch_fakes import build_request, make_constant_fake_dispatch


def test_orchestration_run_result_has_no_named_engine_result_fields():
    # Bolum 23: engine_records DISINDA hicbir motor-sonucu alani (ornegin
    # health_score_result/credit_score_result) YAPISAL OLARAK YOKTUR.
    field_names = {f.name for f in fields(OrchestrationRunResult)}
    forbidden = {
        "health_score_result", "credit_score_result", "recommendation_result",
        "executive_report_result", "dashboard_snapshot", "render_contract_preview",
        "financial_statements_result", "ratio_result", "benchmark_result",
    }
    assert field_names.isdisjoint(forbidden)
    assert "engine_records" in field_names


def _run_full_recommendation_chain():
    fake = make_constant_fake_dispatch()
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.RECOMMENDATION,))
        return run_orchestration(request)


def test_typed_accessors_return_the_same_object_identity_as_engine_records():
    result, _ = _run_full_recommendation_chain()
    records = {r.engine_code: r for r in result.engine_records}

    assert get_ratio_result(result) is records[EngineCode.RATIO].result.result
    assert get_benchmark_result(result) is records[EngineCode.BENCHMARK].result.result
    assert get_health_score_result(result) is records[EngineCode.HEALTH_SCORE].result.result
    assert get_credit_score_result(result) is records[EngineCode.CREDIT_SCORE].result.result
    assert get_recommendation_result(result) is records[EngineCode.RECOMMENDATION].result.result


def test_typed_accessor_rejects_engine_code_with_no_record():
    result, _ = _run_full_recommendation_chain()
    raised = False
    try:
        from app.engines.analysis_orchestrator.types import get_dashboard_snapshot

        get_dashboard_snapshot(result)  # DASHBOARD istenmedi -- hic kaydi yok
    except OrchestratorResultAccessError:
        raised = True
    assert raised


def test_typed_accessor_rejects_wrong_result_kind():
    result, _ = _run_full_recommendation_chain()
    raised = False
    try:
        # RATIO kaydina "HealthScoreResult" beklentisiyle erisim denemek
        # result_kind uyusmazligindan REDDETMELI (sessizce yanlis tip
        # DONMEMELI).
        from app.engines.analysis_orchestrator.types import _get_engine_result

        _get_engine_result(result, EngineCode.RATIO, "HealthScoreResult")
    except OrchestratorResultAccessError:
        raised = True
    assert raised
