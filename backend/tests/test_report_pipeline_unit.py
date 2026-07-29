"""
Milestone 4.4 -- `generate_executive_report()` pipeline davranış testleri:
compatibility (3 katman), hidden report_type erişim engeli, confidence/
coverage envanteri, None güvenliği, determinism, read-only invariant,
upstream motor çağrılmadığı, generated_at/report_id davranışı, banned
generated-interpretation taraması.
"""

import copy
import dataclasses
import inspect
from datetime import date
from unittest.mock import patch

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.credit_score.service import compute_credit_score
from app.engines.executive_reports import service as report_service
from app.engines.executive_reports.service import (
    SOURCE_BUILDERS,
    AGGREGATION_BUILDERS,
    COMPLIANCE_BUILDERS,
    UnsupportedLocaleError,
    generate_executive_report,
)
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations
from app.engines.common.report_types import ReportCompanyMetadata, ReportComputationStatus, ReportType


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


def _build_upstream():
    bs = _bs_facts()
    is_ = _is_facts()
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


def test_unsupported_locale_rejected():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    try:
        generate_executive_report(
            ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=_cm(), reporting_period_label_tr="2024", locale="en-US",
        )
        assert False, "UnsupportedLocaleError beklenirdi"
    except UnsupportedLocaleError:
        pass


def test_schema_incompatible_yields_empty_sections_and_no_engine_calls():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    bad_hs = dataclasses.replace(hs, health_score_schema_version="9.9.9")
    result = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, bad_hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    assert result.status == ReportComputationStatus.SCHEMA_INCOMPATIBLE
    assert result.sections == ()
    assert any(w["code"] == "SCHEMA_VERSION_UNSUPPORTED" for w in result.warnings)


def test_version_mismatch_suppresses_content_to_compliance_only():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    bad_ratio = copy.deepcopy(ratio)
    bad_ratio["ratio_registry_version"] = "9.9.9"
    result = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, bad_ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    assert result.status == ReportComputationStatus.VERSION_MISMATCH
    codes = {s.section_code.value for s in result.sections}
    assert codes.issubset({"SEC_DISCLAIMER_BLOCK", "SEC_CONFIDENCE_AND_DATA_QUALITY"})


def test_matching_versions_compute_normally_with_no_model_version_mismatch_warning():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    assert result.status == ReportComputationStatus.COMPUTED
    assert not any(w["code"] == "MODEL_VERSION_MISMATCH" for w in result.warnings)


def test_hidden_report_type_access_prevention_via_signature_inspection():
    all_builders = list(SOURCE_BUILDERS.values()) + list(AGGREGATION_BUILDERS.values()) + list(COMPLIANCE_BUILDERS.values())
    assert len(all_builders) == 18
    for builder in all_builders:
        params = list(inspect.signature(builder).parameters.keys())
        assert "report_type" not in params, f"{builder.__name__}: report_type parametresi ALMAMALI"
        source = inspect.getsource(builder)
        assert "report_type" not in source, f"{builder.__name__}: report_type İÇİNDE HİÇ GEÇMEMELİ"


def test_no_overall_confidence_field_on_result():
    field_names = {f.name for f in dataclasses.fields(report_service.ExecutiveReportResult)}
    banned = {"overall_confidence", "overall_coverage", "overall_reliability", "composite_confidence", "minimum_confidence_score"}
    assert not (field_names & banned)


def test_none_confidence_and_coverage_marked_unavailable_with_reason_code():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    for entry in result.source_confidence_inventory:
        if not entry.confidence_available:
            assert entry.confidence_value is None
            assert entry.reason_code is not None
            assert entry.source_warning is not None
    for entry in result.source_coverage_inventory:
        if not entry.coverage_available:
            assert entry.coverage_value is None
            assert entry.reason_code is not None
    assert set(result.missing_confidence_sources) == {"balance_sheet", "income_statement", "financial_ratios", "benchmarks", "recommendation"}
    assert set(result.missing_coverage_sources) == {"balance_sheet", "income_statement", "financial_ratios", "benchmarks", "recommendation"}
    engines_with_confidence = {e.source_engine for e in result.source_confidence_inventory if e.confidence_available}
    assert engines_with_confidence == {"health_score", "credit_score"}


def test_deterministic_output_across_100_iterations():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    first = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    for _ in range(100):
        again = generate_executive_report(
            ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=_cm(), reporting_period_label_tr="2024",
        )
        assert again.sections == first.sections
        assert again.warnings == first.warnings
        assert again.source_confidence_inventory == first.source_confidence_inventory


def test_generated_at_and_report_id_only_set_when_caller_provides_them():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result_default = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    assert result_default.generated_at is None
    assert result_default.report_id is None

    result_explicit = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
        report_id="RPT-001", generated_at="2026-07-29T00:00:00Z",
    )
    assert result_explicit.generated_at == "2026-07-29T00:00:00Z"
    assert result_explicit.report_id == "RPT-001"


def test_no_datetime_now_uuid4_random_in_service_source():
    source = inspect.getsource(report_service)
    assert "datetime.now(" not in source
    assert "date.today(" not in source
    assert "uuid.uuid4(" not in source
    assert "uuid4()" not in source
    assert "random." not in source


def test_no_input_mutation_of_4_raw_json_inputs():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    bs_before, is_before, ratio_before, bench_before = (copy.deepcopy(bs), copy.deepcopy(is_), copy.deepcopy(ratio), copy.deepcopy(benchmark))
    generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    assert bs == bs_before
    assert is_ == is_before
    assert ratio == ratio_before
    assert benchmark == bench_before


def test_no_upstream_engine_functions_called_from_report_engine():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    with patch("app.engines.financial_ratios.service.analyze_financial_ratios") as m1, \
         patch("app.engines.benchmarks.service.evaluate_benchmarks") as m2, \
         patch("app.engines.health_score.service.compute_financial_health_score") as m3, \
         patch("app.engines.credit_score.service.compute_credit_score") as m4, \
         patch("app.engines.recommendation.service.generate_recommendations") as m5:
        generate_executive_report(
            ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
            company_metadata=_cm(), reporting_period_label_tr="2024",
        )
        for m in (m1, m2, m3, m4, m5):
            m.assert_not_called()


def test_all_content_blocks_carry_nonempty_source_field_path():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    for section in result.sections:
        for block in section.content_blocks:
            assert block.source_field_path, f"{section.section_code}: source_field_path BOŞ olamaz"


def test_all_sections_carry_reformatted_source_flags():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(
        ReportType.CFO_EXECUTIVE_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    for section in result.sections:
        assert section.is_reformatted_source_content is True
        assert section.is_independent_strategic_analysis is False


def test_result_carries_all_mandatory_legal_and_safety_flags():
    bs, is_, ratio, benchmark, hs, cs, rec = _build_upstream()
    result = generate_executive_report(
        ReportType.BANK_CREDIT_ALLOCATION_REPORT, bs, is_, ratio, benchmark, hs, cs, rec,
        company_metadata=_cm(), reporting_period_label_tr="2024",
    )
    assert result.decision_support_only is True
    assert result.not_a_statutory_report is True
    assert result.not_a_credit_approval is True
    assert result.not_investment_advice is True
    assert result.contains_sensitive_financial_data is True
    assert result.external_distribution_allowed is False
    assert result.legal_review_status.value == "legal_review_required"
    assert result.confidentiality_level.value == "confidential"
    assert result.redaction_required is True
