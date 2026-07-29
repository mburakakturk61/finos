"""
Milestone 4.4 -- 7 narrative ReportType için golden dataset (uçtan-uca
motor zinciri: BS/IS/Ratio/Benchmark/Health/Credit/Recommendation ->
Executive Report Engine).
"""

from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.report_types import ReportCompanyMetadata, ReportComputationStatus, ReportType
from app.engines.credit_score.service import compute_credit_score
from app.engines.executive_reports.service import generate_executive_report
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations


def _bs_facts():
    return {"source_mode": "direct_document", "facts": {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }, "engine_version": "1.0.0", "horizontal_analysis": {"net_sales_growth": 0.12}}


def _is_facts():
    return {"source_mode": "direct_document", "facts": {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }, "engine_version": "1.0.0", "horizontal_analysis": {"net_sales_growth": 0.12}}


def _negative_equity_bs_facts():
    bs = _bs_facts()
    bs["facts"]["equity"] = -50000.0
    return bs


def _generate(bs, is_, report_type, optional_all=True):
    ratio = analyze_financial_ratios(
        balance_sheet_result=bs, income_statement_result=is_,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark = evaluate_benchmarks(ratio)
    hs = compute_financial_health_score(ratio, benchmark)
    cs = compute_credit_score(ratio, benchmark, hs)
    rec = generate_recommendations(ratio, benchmark, hs, cs)

    from app.engines.common.report_registry import REPORT_TYPE_REGISTRY
    optional_sections = None
    if optional_all:
        optional_sections = tuple(u.section_code for u in REPORT_TYPE_REGISTRY[report_type])

    return generate_executive_report(
        report_type, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=ReportCompanyMetadata(company_name="Golden A.Ş."),
        reporting_period_label_tr="2024", optional_sections=optional_sections,
    )


def test_all_7_report_types_produce_computed_status_with_expected_section_counts():
    bs, is_ = _bs_facts(), _is_facts()
    expected_counts = {
        ReportType.CFO_EXECUTIVE_REPORT: 16,
        ReportType.BANK_CREDIT_ALLOCATION_REPORT: 12,
        ReportType.BOARD_OF_DIRECTORS_REPORT: 10,
        ReportType.INVESTOR_REPORT: 9,
        ReportType.MANAGEMENT_SUMMARY: 7,
        ReportType.SWOT_REPORT: 7,
        ReportType.PERIOD_COMPARISON_REPORT: 5,
    }
    for rt, expected in expected_counts.items():
        result = _generate(bs, is_, rt)
        assert result.status == ReportComputationStatus.COMPUTED, rt
        assert len(result.sections) == expected, rt
        assert result.report_title_tr


def test_negative_equity_scenario_produces_hard_fail_risk_flags_across_report_types():
    bs, is_ = _negative_equity_bs_facts(), _is_facts()
    for rt in (ReportType.CFO_EXECUTIVE_REPORT, ReportType.BANK_CREDIT_ALLOCATION_REPORT):
        result = _generate(bs, is_, rt)
        risk_section = [s for s in result.sections if s.section_code.value == "SEC_RISK_FLAGS"]
        assert risk_section, rt
        rows = risk_section[0].content_blocks[0].payload["rows"]
        assert any(r["flag_code"] == "NEGATIVE_EQUITY" for r in rows), rt


def test_mandatory_only_report_still_computes_for_all_7_types():
    bs, is_ = _bs_facts(), _is_facts()
    for rt in ReportType:
        result = _generate(bs, is_, rt, optional_all=False)
        assert result.status == ReportComputationStatus.COMPUTED, rt
        assert all(s.is_mandatory_for_report_type for s in result.sections), rt
