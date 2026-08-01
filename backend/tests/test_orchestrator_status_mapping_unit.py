"""
Milestone 5.0A -- Kategori C: Bolum 9.1'deki TAM ic-durum -> Engine
ExecutionStatus esleme tablosunun parametrik (her satir icin ayri test
fonksiyonu) dogrulamasi. `NO_RECOMMENDATIONS_TRIGGERED -> COMPLETED`
(YANLIS siniflandirmaya karsi ozel bir regresyon testidir) ve Render
Contract'in DEGRADED durumunun YAPISAL OLARAK IMKANSIZ oldugu bu dosyanin
en kritik iki iddiasidir.
"""

from app.engines.analysis_orchestrator.service import _map_inner_status
from app.engines.analysis_orchestrator.types import EngineCode, EngineExecutionStatus
from tests._orch_fakes import (
    benchmark_result,
    credit_score_result,
    dashboard_snapshot,
    executive_report_result,
    fs_outcome,
    health_score_result,
    ratio_result,
    recommendation_result,
    render_contract_preview,
)


def test_fs_balance_sheet_completed_maps_to_completed():
    status, value = _map_inner_status(EngineCode.FS_BALANCE_SHEET, fs_outcome(status="completed"))
    assert status == EngineExecutionStatus.COMPLETED
    assert value == "completed"


def test_fs_balance_sheet_failed_maps_to_degraded():
    status, value = _map_inner_status(EngineCode.FS_BALANCE_SHEET, fs_outcome(status="failed"))
    assert status == EngineExecutionStatus.DEGRADED
    assert value == "failed"


def test_fs_income_statement_completed_maps_to_completed():
    status, _ = _map_inner_status(EngineCode.FS_INCOME_STATEMENT, fs_outcome(status="completed"))
    assert status == EngineExecutionStatus.COMPLETED


def test_fs_income_statement_failed_maps_to_degraded():
    status, _ = _map_inner_status(EngineCode.FS_INCOME_STATEMENT, fs_outcome(status="failed"))
    assert status == EngineExecutionStatus.DEGRADED


def test_ratio_all_not_calculable_maps_to_degraded():
    status, value = _map_inner_status(EngineCode.RATIO, ratio_result(all_not_calculable=True))
    assert status == EngineExecutionStatus.DEGRADED
    assert value == "not_calculable"


def test_ratio_at_least_one_calculated_maps_to_completed():
    status, value = _map_inner_status(EngineCode.RATIO, ratio_result(all_not_calculable=False))
    assert status == EngineExecutionStatus.COMPLETED
    assert value == "calculated"


def test_benchmark_all_not_calculable_maps_to_degraded():
    status, value = _map_inner_status(EngineCode.BENCHMARK, benchmark_result(any_evaluated=False))
    assert status == EngineExecutionStatus.DEGRADED
    assert value == "not_calculable"


def test_benchmark_at_least_one_evaluated_maps_to_completed():
    status, value = _map_inner_status(EngineCode.BENCHMARK, benchmark_result(any_evaluated=True))
    assert status == EngineExecutionStatus.COMPLETED
    assert value == "evaluated"


def test_health_score_computed_maps_to_completed():
    status, value = _map_inner_status(EngineCode.HEALTH_SCORE, health_score_result(status="computed"))
    assert status == EngineExecutionStatus.COMPLETED
    assert value == "computed"


def test_health_score_hard_fail_capped_maps_to_degraded():
    status, value = _map_inner_status(EngineCode.HEALTH_SCORE, health_score_result(status="hard_fail_capped"))
    assert status == EngineExecutionStatus.DEGRADED
    assert value == "hard_fail_capped"


def test_health_score_insufficient_data_maps_to_degraded():
    status, value = _map_inner_status(EngineCode.HEALTH_SCORE, health_score_result(status="insufficient_data"))
    assert status == EngineExecutionStatus.DEGRADED
    assert value == "insufficient_data"


def test_credit_score_computed_maps_to_completed():
    status, _ = _map_inner_status(EngineCode.CREDIT_SCORE, credit_score_result(status="computed"))
    assert status == EngineExecutionStatus.COMPLETED


def test_credit_score_hard_fail_capped_maps_to_degraded():
    status, _ = _map_inner_status(EngineCode.CREDIT_SCORE, credit_score_result(status="hard_fail_capped"))
    assert status == EngineExecutionStatus.DEGRADED


def test_credit_score_insufficient_data_maps_to_degraded():
    status, _ = _map_inner_status(EngineCode.CREDIT_SCORE, credit_score_result(status="insufficient_data"))
    assert status == EngineExecutionStatus.DEGRADED


def test_recommendation_computed_maps_to_completed():
    status, _ = _map_inner_status(EngineCode.RECOMMENDATION, recommendation_result(status="computed"))
    assert status == EngineExecutionStatus.COMPLETED


def test_recommendation_no_recommendations_triggered_maps_to_completed():
    # KRITIK regresyon testi: veri yeterli ama hicbir kural tetiklenmedi
    # (sirket saglikli) OLUMLU bir sonuctur, DEGRADED DEGILDIR.
    status, value = _map_inner_status(
        EngineCode.RECOMMENDATION, recommendation_result(status="no_recommendations_triggered")
    )
    assert status == EngineExecutionStatus.COMPLETED
    assert value == "no_recommendations_triggered"


def test_recommendation_insufficient_data_maps_to_degraded():
    status, _ = _map_inner_status(EngineCode.RECOMMENDATION, recommendation_result(status="insufficient_data"))
    assert status == EngineExecutionStatus.DEGRADED


def test_recommendation_schema_incompatible_maps_to_degraded():
    status, _ = _map_inner_status(EngineCode.RECOMMENDATION, recommendation_result(status="schema_incompatible"))
    assert status == EngineExecutionStatus.DEGRADED


def test_recommendation_version_mismatch_maps_to_degraded():
    status, _ = _map_inner_status(EngineCode.RECOMMENDATION, recommendation_result(status="version_mismatch"))
    assert status == EngineExecutionStatus.DEGRADED


def test_executive_report_computed_maps_to_completed():
    status, _ = _map_inner_status(EngineCode.EXECUTIVE_REPORT, executive_report_result(status="computed"))
    assert status == EngineExecutionStatus.COMPLETED


def test_executive_report_schema_incompatible_maps_to_degraded():
    status, _ = _map_inner_status(
        EngineCode.EXECUTIVE_REPORT, executive_report_result(status="schema_incompatible")
    )
    assert status == EngineExecutionStatus.DEGRADED


def test_executive_report_version_mismatch_maps_to_degraded():
    status, _ = _map_inner_status(EngineCode.EXECUTIVE_REPORT, executive_report_result(status="version_mismatch"))
    assert status == EngineExecutionStatus.DEGRADED


def test_dashboard_compatible_maps_to_completed():
    status, value = _map_inner_status(EngineCode.DASHBOARD, dashboard_snapshot(widgets=({"w": 1},)))
    assert status == EngineExecutionStatus.COMPLETED
    assert value == "compatible"


def test_dashboard_incompatible_maps_to_degraded():
    status, value = _map_inner_status(EngineCode.DASHBOARD, dashboard_snapshot(widgets=()))
    assert status == EngineExecutionStatus.DEGRADED
    assert value == "incompatible"


def test_render_contract_success_maps_to_completed():
    status, value = _map_inner_status(EngineCode.RENDER_CONTRACT, render_contract_preview())
    assert status == EngineExecutionStatus.COMPLETED
    assert value is None


def test_render_contract_has_no_degraded_state_structurally():
    # Bolum 9.1: bu motorun kendi bir computation-status'u YOKTUR --
    # DEGRADED asla uretilemez, ne kadar "kotu" bir RenderContractPreview
    # verilirse verilsin sonuc HER ZAMAN COMPLETED'tir (basarili donduyse).
    for preview in (render_contract_preview(), render_contract_preview()):
        status, _ = _map_inner_status(EngineCode.RENDER_CONTRACT, preview)
        assert status == EngineExecutionStatus.COMPLETED
        assert status != EngineExecutionStatus.DEGRADED
