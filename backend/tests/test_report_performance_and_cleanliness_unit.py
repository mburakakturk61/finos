"""
Milestone 4.4 -- performans smoke testi (gevşek regresyon üst sınırı,
Bölüm 24'ün <2ms/<5ms hedeflerinin KESİN SERTİFİKASYONU DEĞİL) + registry
cleanliness (tekrarlı çağrılar registry'leri BÜYÜTMEZ, izole kayıt global
registry'ye SIZMAZ).
"""

import time
from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.report_registry import REPORT_SECTION_REGISTRY, REPORT_TYPE_REGISTRY
from app.engines.common.report_types import (
    BuildPhase,
    DetailLevel,
    FieldInclusionPolicy,
    ReportCompanyMetadata,
    ReportSectionBuilderStrategy,
    ReportSectionCode,
    ReportSectionDefinition,
    ReportType,
    SectionUsageDefinition,
)
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


def test_heavy_narrative_report_completes_within_loose_bound():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    iterations = 100
    start = time.perf_counter()
    for _ in range(iterations):
        generate_executive_report(
            ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
        )
    elapsed = time.perf_counter() - start
    per_call_ms = (elapsed / iterations) * 1000
    # Gevşek regresyon üst sınırı (sandbox donanımı) -- Bölüm 24'ün
    # provisional <5ms hedefinin KESİN SERTİFİKASYONU için GERÇEK Docker
    # ortamında AYRICA ölçülmelidir.
    assert per_call_ms < 100.0, f"per_call_ms={per_call_ms:.3f} beklenenden ÇOK yüksek"


def test_light_management_summary_completes_within_loose_bound():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    iterations = 100
    start = time.perf_counter()
    for _ in range(iterations):
        generate_executive_report(
            ReportType.MANAGEMENT_SUMMARY, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
        )
    elapsed = time.perf_counter() - start
    per_call_ms = (elapsed / iterations) * 1000
    assert per_call_ms < 50.0, f"per_call_ms={per_call_ms:.3f} beklenenden ÇOK yüksek"


def test_repeated_calls_do_not_grow_report_registries():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    section_size_before = len(REPORT_SECTION_REGISTRY)
    type_size_before = len(REPORT_TYPE_REGISTRY)
    for _ in range(10):
        generate_executive_report(
            ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=ReportCompanyMetadata(company_name="Test"), reporting_period_label_tr="2024",
        )
    assert len(REPORT_SECTION_REGISTRY) == section_size_before
    assert len(REPORT_TYPE_REGISTRY) == type_size_before


def test_isolated_section_registration_does_not_leak_into_global_registry():
    import app.engines.common.report_registry as rr

    original_size = len(rr.REPORT_SECTION_REGISTRY)
    isolated = {}
    temp_def = ReportSectionDefinition(
        section_code=ReportSectionCode.SEC_COVER_PAGE,  # zaten kayıtlı, ama İZOLE registry'de DEĞİL
        display_name_tr="Test", build_phase=BuildPhase.SOURCE_SECTION, dependency_codes=(),
        consumes_section_outputs=(), data_domains=(), overlaps_with=(), primary_section_for_domain={},
        builder_strategy=ReportSectionBuilderStrategy.COVER_PAGE, source_engine_codes=("test",),
        model_version_introduced="1.0.0", deprecated_since=None, replacement_section_code=None,
    )
    rr.register_report_section(temp_def, registry=isolated)
    assert len(rr.REPORT_SECTION_REGISTRY) == original_size
    assert ReportSectionCode.SEC_COVER_PAGE in isolated
    assert len(rr.REPORT_SECTION_REGISTRY) == 18


def test_isolated_report_type_registration_does_not_leak_into_global_registry():
    import app.engines.common.report_registry as rr

    original_size = len(rr.REPORT_TYPE_REGISTRY)
    isolated_types = {}
    usage = SectionUsageDefinition(
        ReportSectionCode.SEC_COVER_PAGE, DetailLevel.FULL, FieldInclusionPolicy.ALL_FIELDS,
        None, None, True, False, False, 1, False,
    )
    rr.register_report_type(ReportType.CFO_EXECUTIVE_REPORT, (usage,), registry=isolated_types)
    assert len(rr.REPORT_TYPE_REGISTRY) == original_size
    assert len(rr.REPORT_TYPE_REGISTRY[ReportType.CFO_EXECUTIVE_REPORT]) == 16
