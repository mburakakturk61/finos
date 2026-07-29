"""
Milestone 4.4 -- Render Contract Preview testleri: `RENDER_CONTRACT_
PREVIEW`'in `ReportType` içinde OLMADIĞI, 8 render-neutral alan, unsupported-
content warning, `RENDER_CONTRACT_PRESENTATION_ONLY` property testi.
"""

from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.render_contract_types import RenderContract, RenderContractPreview, RenderMedium
from app.engines.common.report_types import ReportBlockType, ReportCompanyMetadata, ReportType
from app.engines.credit_score.service import compute_credit_score
from app.engines.executive_reports.service import generate_executive_report
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations
from app.engines.render_contract.service import InvalidReportResultError, preview_render_contract


def _build_report(report_type=ReportType.CFO_EXECUTIVE_REPORT):
    bs = {"source_mode": "direct_document", "facts": {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }, "engine_version": "1.0.0", "horizontal_analysis": {}}
    is_ = {"source_mode": "direct_document", "facts": {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }, "engine_version": "1.0.0", "horizontal_analysis": {}}
    ratio = analyze_financial_ratios(
        balance_sheet_result=bs, income_statement_result=is_,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark = evaluate_benchmarks(ratio)
    hs = compute_financial_health_score(ratio, benchmark)
    cs = compute_credit_score(ratio, benchmark, hs)
    rec = generate_recommendations(ratio, benchmark, hs, cs)
    return generate_executive_report(
        report_type, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
    )


_FULL_RENDER_CONTRACT = RenderContract(
    RenderMedium.PDF,
    (ReportBlockType.KPI_CARD, ReportBlockType.TABLE, ReportBlockType.BULLET_LIST, ReportBlockType.PARAGRAPH, ReportBlockType.CHART_DATA, ReportBlockType.BADGE),
    True, True, True, 6,
)


def test_render_contract_preview_not_a_report_type_value():
    values = {rt.value for rt in ReportType}
    assert "render_contract_preview" not in values


def test_render_contract_preview_has_exactly_8_fields():
    fields = set(RenderContractPreview.__dataclass_fields__.keys())
    assert fields == {
        "section_render_order", "layout_capability_matrix", "table_overflow_risk_flags",
        "page_break_preferences", "landscape_required_section_codes", "chart_placeholder_capability",
        "unsupported_content_warnings", "render_metadata",
    }


def test_section_render_order_matches_report_section_order():
    report = _build_report()
    preview = preview_render_contract(report, _FULL_RENDER_CONTRACT)
    assert preview.section_render_order == tuple(s.section_code for s in report.sections)


def test_unsupported_content_warning_generated_for_restricted_contract():
    report = _build_report()
    restricted = RenderContract(RenderMedium.PDF, (ReportBlockType.PARAGRAPH,), False, False, False, None)
    preview = preview_render_contract(report, restricted)
    assert len(preview.unsupported_content_warnings) > 0
    assert all(w["code"] == "UNSUPPORTED_BLOCK_TYPE" for w in preview.unsupported_content_warnings)


def test_invalid_report_result_type_rejected():
    try:
        preview_render_contract("not-a-report-result", _FULL_RENDER_CONTRACT)  # type: ignore[arg-type]
        assert False, "InvalidReportResultError beklenirdi"
    except InvalidReportResultError:
        pass


def test_render_contract_preview_produces_no_new_financial_content():
    report = _build_report()
    preview = preview_render_contract(report, _FULL_RENDER_CONTRACT)
    # RenderContractPreview'de HİÇBİR alan finansal DEĞER TAŞIMAZ -- yalnızca
    # section_code/risk_level/preference/bool gibi yapısal metadata.
    for flag in preview.table_overflow_risk_flags:
        assert flag.risk_level.value in {"none", "low", "high"}
    assert preview.render_metadata.total_sections == len(report.sections)


def test_render_contract_property_deterministic_across_all_7_report_types():
    for rt in ReportType:
        report = _build_report(rt)
        first = preview_render_contract(report, _FULL_RENDER_CONTRACT)
        second = preview_render_contract(report, _FULL_RENDER_CONTRACT)
        assert first == second, rt


def test_render_contract_does_not_mutate_report_result():
    report = _build_report()
    sections_before = report.sections
    preview_render_contract(report, _FULL_RENDER_CONTRACT)
    assert report.sections == sections_before
