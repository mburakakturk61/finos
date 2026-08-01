"""
Milestone 5.0A -- Golden dataset / gercek uctan-uca pipeline testi.

Bu dosya, TEK BASINA orchestrator mantigini degil, `run_orchestration()`'in
GERCEK 9 motoru (10 motor kodu) -- hicbir sahte/mock CALLABLE olmadan --
dogru sirada, dogru girdilerle GERCEKTEN cagirip anlamli, tutarli bir
`OrchestrationRunResult` urettigini kanitlar. Sentetik trial-balance
fixture'i (tests/data/synthetic/synthetic_trial_balance_matched_bs_is.xlsx,
tamamen kurgusal veri) `analyze_trial_balance` ile isleyip, Financial
Statements motorlarini "trial_balance_derived" (fallback) yoluyla
calistirir -- bkz. tests/test_engine_balance_income_statement_unit.py'deki
ayni desen.
"""

import pathlib

from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineExecutionStatus,
    EngineRawInputs,
    OrchestrationRunOptions,
    RunStatus,
    get_credit_score_result,
    get_dashboard_snapshot,
    get_executive_report_result,
    get_health_score_result,
    get_ratio_result,
    get_recommendation_result,
    get_render_contract_preview,
)
from app.engines.common.dashboard_types import DashboardType
from app.engines.common.render_contract_types import RenderContract, RenderMedium
from app.engines.common.report_types import ReportBlockType, ReportCompanyMetadata, ReportType
from app.trial_balance.service import analyze_trial_balance
from tests._orch_fakes import build_request

FIXTURES_DIR = pathlib.Path(__file__).parent / "data" / "synthetic"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _real_request(requested_outputs) -> "object":
    tb_content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")
    tb_result = analyze_trial_balance(content=tb_content, filename="mizan.xlsx")

    engine_inputs = EngineRawInputs(trial_balance_result=tb_result)
    run_options = OrchestrationRunOptions(
        report_type=ReportType.CFO_EXECUTIVE_REPORT,
        dashboard_type=DashboardType.EXECUTIVE_DASHBOARD,
        company_metadata=ReportCompanyMetadata(company_name="Sentetik Test A.Ş."),
        reporting_period_label_tr="2024",
        render_contract=RenderContract(
            RenderMedium.PDF,
            (
                ReportBlockType.KPI_CARD,
                ReportBlockType.TABLE,
                ReportBlockType.BULLET_LIST,
                ReportBlockType.PARAGRAPH,
                ReportBlockType.CHART_DATA,
                ReportBlockType.BADGE,
            ),
            True,
            True,
            True,
            6,
        ),
    )
    return build_request(
        run_id="golden-run-1",
        requested_outputs=requested_outputs,
        engine_inputs=engine_inputs,
        run_options=run_options,
    )


def test_real_engines_full_chain_produces_a_coherent_result():
    request = _real_request(
        (EngineCode.EXECUTIVE_REPORT, EngineCode.DASHBOARD, EngineCode.RENDER_CONTRACT)
    )
    result, _ = run_orchestration(request)

    records = {r.engine_code: r for r in result.engine_records}
    assert len(records) == 10

    # Trial-balance-fallback yolunda BS/IS COMPLETED donmelidir (gercek,
    # tutarli bir mizan fixture'i kullanildigi icin).
    assert records[EngineCode.FS_BALANCE_SHEET].status == EngineExecutionStatus.COMPLETED
    assert records[EngineCode.FS_INCOME_STATEMENT].status == EngineExecutionStatus.COMPLETED

    # Zincirin geri kalani en azindan calisti (COMPLETED/DEGRADED/REUSED) --
    # SKIPPED/FAILED yok, gercek veriyle tam bir çalistirma bekleniyor.
    for code in EngineCode:
        assert records[code].status not in (EngineExecutionStatus.SKIPPED, EngineExecutionStatus.FAILED), code

    assert result.status in (RunStatus.FULLY_COMPLETED, RunStatus.COMPLETED_WITH_DEGRADATIONS)

    ratio_result = get_ratio_result(result)
    assert ratio_result is not None
    assert ratio_result["engine"] == "financial_ratios"

    health = get_health_score_result(result)
    assert health is not None
    credit = get_credit_score_result(result)
    assert credit is not None
    recommendation = get_recommendation_result(result)
    assert recommendation is not None
    report = get_executive_report_result(result)
    assert report is not None
    dashboard = get_dashboard_snapshot(result)
    assert dashboard is not None
    render_preview = get_render_contract_preview(result)
    assert render_preview is not None

    # Provenance -- cagri sirasi TAM olarak turetilmis plana esit olmali.
    assert result.execution_provenance.engine_call_sequence == tuple(
        code for code in result.execution_provenance.engine_call_sequence
    )
    assert len(result.execution_provenance.engine_call_sequence) == 10
    assert result.execution_provenance.reused_engine_codes == ()
    assert result.execution_provenance.skipped_engine_codes == ()


def test_real_engines_partial_request_only_pulls_required_subset():
    # Yalnizca RATIO istenirse, Executive Report/Dashboard/Render Contract
    # HIC calismamalidir (Bolum 5 -- opsiyonel motorlar istenmedikce
    # calismaz).
    request = _real_request((EngineCode.RATIO,))
    result, _ = run_orchestration(request)

    codes_present = {r.engine_code for r in result.engine_records}
    assert codes_present == {EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT, EngineCode.RATIO}
    assert EngineCode.EXECUTIVE_REPORT not in codes_present
    assert EngineCode.DASHBOARD not in codes_present
    assert EngineCode.RENDER_CONTRACT not in codes_present


def test_real_engines_reuse_across_two_identical_runs():
    from app.engines.analysis_orchestrator.types import EngineExecutionStatus as _S
    from app.engines.analysis_orchestrator.types import PreviousEngineSnapshot, PreviousExecutionSnapshot

    request1 = _real_request((EngineCode.RECOMMENDATION,))
    result1, _ = run_orchestration(request1)

    snapshots = tuple(
        PreviousEngineSnapshot(
            r.engine_code, r.status, r.engine_schema_version_used, r.engine_model_version_used,
            r.input_fingerprint, r.fingerprint_schema_version,
            r.result.result if r.result is not None else None,
        )
        for r in result1.engine_records
        if r.status in (_S.COMPLETED, _S.DEGRADED)
    )
    previous = PreviousExecutionSnapshot(
        "golden-run-1", result1.request_fingerprint, result1.orchestration_schema_version,
        result1.orchestration_model_version, result1.execution_plan_version, snapshots,
    )

    request2 = _real_request((EngineCode.RECOMMENDATION,))
    request2 = build_request(
        run_id="golden-run-1",
        requested_outputs=request2.requested_outputs,
        engine_inputs=request2.engine_inputs,
        run_options=request2.run_options,
        previous_execution_snapshot=previous,
    )
    result2, _ = run_orchestration(request2)

    assert all(r.status == _S.REUSED for r in result2.engine_records)
    assert result2.request_fingerprint == result1.request_fingerprint
