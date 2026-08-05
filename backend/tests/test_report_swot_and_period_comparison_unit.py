"""
Milestone 4.4 -- SWOT (Opportunities fabrication prevention, reformatted-
source bayrakları, kaynak metnin DEĞİŞTİRİLMEMESİ) + Period Comparison
(isimlendirme/kapsam, "Trend Report" kalıntısı taraması) testleri.
"""

import inspect
from datetime import date
from pathlib import Path

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.report_types import (
    SWOT_BOUNDARY_STATEMENT_TR,
    ReportCompanyMetadata,
    ReportType,
)
from app.engines.credit_score.service import compute_credit_score
from app.engines.executive_reports import service as report_service
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
    }, "engine_version": "1.0.0", "horizontal_analysis": {"net_sales_growth": 0.12}}
    is_ = {"source_mode": "direct_document", "facts": {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }, "engine_version": "1.0.0", "horizontal_analysis": {"net_sales_growth": 0.12}}
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


def _cm():
    return ReportCompanyMetadata(company_name="Test A.Ş.")


def _swot_payload(result):
    section = [s for s in result.sections if s.section_code.value == "SEC_SWOT"][0]
    return section, [b for b in section.content_blocks if b.block_type.value == "bullet_list"][0].payload


def test_swot_opportunities_always_unavailable_and_empty():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(ReportType.SWOT_REPORT, bs, is_, ratio, benchmark, hs, cs, rec, company_metadata=_cm(), reporting_period_label_tr="2024")
    _, payload = _swot_payload(result)
    opportunities = [q for q in payload["quadrants"] if q["quadrant"] == "opportunities"][0]
    assert opportunities["is_available"] is False
    assert opportunities["items"] == []
    assert opportunities["unavailable_reason_tr"]


def test_recommendation_categories_never_relabeled_as_opportunity():
    source = inspect.getsource(report_service._b_swot)
    assert '"opportunities"' in source
    # opportunities kadranı SwotQuadrant("opportunities", (), False, ...) -- SABİT boş tuple
    assert 'SwotQuadrant("opportunities", (), False,' in source


def test_swot_carries_reformatted_source_flags_and_boundary_statement():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(ReportType.SWOT_REPORT, bs, is_, ratio, benchmark, hs, cs, rec, company_metadata=_cm(), reporting_period_label_tr="2024")
    section, payload = _swot_payload(result)
    assert payload["is_reformatted_source_content"] is True
    assert payload["is_independent_strategic_analysis"] is False
    assert section.content_blocks[0].payload["text_tr"] == SWOT_BOUNDARY_STATEMENT_TR


def test_swot_strengths_and_weaknesses_text_unchanged_from_health_score():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(ReportType.SWOT_REPORT, bs, is_, ratio, benchmark, hs, cs, rec, company_metadata=_cm(), reporting_period_label_tr="2024")
    _, payload = _swot_payload(result)
    strengths_texts = {i["text_tr"] for q in payload["quadrants"] if q["quadrant"] == "strengths" for i in q["items"]}
    source_texts = {s["text_tr"] for s in hs.strengths}
    assert strengths_texts == source_texts

    weaknesses_texts = {i["text_tr"] for q in payload["quadrants"] if q["quadrant"] == "weaknesses" for i in q["items"]}
    source_weakness_texts = {w["text_tr"] for w in hs.weaknesses}
    assert weaknesses_texts == source_weakness_texts


def test_period_comparison_report_type_name_is_correct():
    assert ReportType.PERIOD_COMPARISON_REPORT.value == "period_comparison_report"
    values = {rt.value for rt in ReportType}
    assert "trend_report" not in values


def test_period_comparison_warns_about_single_period_scope():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(ReportType.PERIOD_COMPARISON_REPORT, bs, is_, ratio, benchmark, hs, cs, rec, company_metadata=_cm(), reporting_period_label_tr="2024")
    assert any(w.get("code") == "SINGLE_PERIOD_COMPARISON_ONLY" for w in result.warnings)


def test_legacy_report_source_files_have_no_trend_report_type_residue():
    banned_terms = ("Trend Report", "TREND_REPORT", "trend_report")
    project_root = Path(__file__).resolve().parents[1]
    paths = (
        project_root / "app" / "engines" / "common" / "report_types.py",
        project_root / "app" / "engines" / "common" / "report_registry.py",
        project_root / "app" / "engines" / "executive_reports" / "service.py",
        project_root / "app" / "engines" / "executive_reports" / "cash_flow_integration.py",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for term in banned_terms:
            assert term not in text, f"{path}: yasaklı '{term}' ifadesi bulundu"


def test_period_comparison_content_makes_no_multi_year_trend_claims():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(ReportType.PERIOD_COMPARISON_REPORT, bs, is_, ratio, benchmark, hs, cs, rec, company_metadata=_cm(), reporting_period_label_tr="2024")
    banned_terms = ("momentum", "tahmin", "forecast", "projeksiyon", "bozulma modeli", "istatistiksel eğilim")
    for section in result.sections:
        for block in section.content_blocks:
            text_repr = str(block.payload).lower()
            for term in banned_terms:
                assert term not in text_repr, f"{section.section_code}: yasaklı '{term}' ifadesi bulundu"
