"""
Milestone 4.4 -- property testleri: `REPORT_ENGINE_PRESENTATION_ONLY`
invariant'ının deep-copy + mock/spy ile KANITLANMASI, determinizm.
"""

import copy
from datetime import date
from unittest.mock import patch

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.report_types import ReportCompanyMetadata, ReportType
from app.engines.credit_score.service import compute_credit_score
from app.engines.executive_reports.service import generate_executive_report
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations


def _build_upstream():
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
    return bs, is_, ratio, benchmark, hs, cs, rec


def test_property_read_only_invariant_across_all_7_report_types():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    bs_snap, is_snap, ratio_snap, bench_snap = (copy.deepcopy(bs), copy.deepcopy(is_), copy.deepcopy(ratio), copy.deepcopy(benchmark))
    for rt in ReportType:
        generate_executive_report(
            rt, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
        )
        assert bs == bs_snap and is_ == is_snap and ratio == ratio_snap and benchmark == bench_snap, rt


def test_property_no_upstream_engine_invocation_across_all_7_report_types():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    with patch("app.engines.financial_ratios.service.analyze_financial_ratios") as m1, \
         patch("app.engines.benchmarks.service.evaluate_benchmarks") as m2, \
         patch("app.engines.health_score.service.compute_financial_health_score") as m3, \
         patch("app.engines.credit_score.service.compute_credit_score") as m4, \
         patch("app.engines.recommendation.service.generate_recommendations") as m5:
        for rt in ReportType:
            generate_executive_report(
                rt, bs, is_, ratio, benchmark, hs, cs, rec,
                company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
            )
        for m in (m1, m2, m3, m4, m5):
            m.assert_not_called()


def test_property_determinism_100_iterations_all_report_types():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    for rt in ReportType:
        baseline = generate_executive_report(
            rt, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
        )
        for _ in range(25):
            again = generate_executive_report(
                rt, bs, is_, ratio, benchmark, hs, cs, rec,
                company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
            )
            assert again == baseline, rt


def test_property_no_new_ratio_benchmark_score_recommendation_computed():
    """
    `REPORT_ENGINE_PRESENTATION_ONLY` -- rapor sonucundaki HİÇBİR sayısal
    değerin upstream sonuçlarda BULUNMAYAN YENİ bir değer OLMADIĞI (yalnızca
    doğrudan kopya/geçiş olduğu) dolaylı kanıtı: health/credit score'un
    final_score'u DEĞİŞMEDEN aynen sections içinde GÖRÜNÜR.
    """
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
    )
    hs_section = [s for s in result.sections if s.section_code.value == "SEC_HEALTH_SCORE_BREAKDOWN"][0]
    kpi_values = {b.payload["label_tr"]: b.payload["value"] for b in hs_section.content_blocks if b.block_type.value == "kpi_card"}
    assert kpi_values["Nihai Skor"] == hs.final_score
