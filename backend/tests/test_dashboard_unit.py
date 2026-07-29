"""
Milestone 4.4 -- Dashboard Snapshot katmanı testleri: tam 2 `DashboardType`
envanteri, tam 10 widget envanteri, `DASHBOARD_PRESENTATION_ONLY` property
testi, dashboard/report sözleşme ayrımı, golden dataset (her 2 dashboard
tipi).
"""

import inspect
from datetime import date
from unittest.mock import patch

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.dashboard_registry import DASHBOARD_WIDGET_REGISTRY
from app.engines.common.dashboard_types import ALLOWED_DASHBOARD_WIDGET_TYPES, DashboardSnapshot, DashboardType
from app.engines.common.report_types import ExecutiveReportResult, ReportCompanyMetadata
from app.engines.credit_score.service import compute_credit_score
from app.engines.dashboards.service import generate_dashboard_snapshot
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
    }}
    is_ = {"source_mode": "direct_document", "facts": {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }}
    ratio = analyze_financial_ratios(
        balance_sheet_result=bs, income_statement_result=is_,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark = evaluate_benchmarks(ratio)
    hs = compute_financial_health_score(ratio, benchmark)
    cs = compute_credit_score(ratio, benchmark, hs)
    rec = generate_recommendations(ratio, benchmark, hs, cs)
    return benchmark, hs, cs, rec


def test_exact_2_dashboard_types():
    assert {dt.value for dt in DashboardType} == {"executive_dashboard", "risk_dashboard"}
    assert len(DASHBOARD_WIDGET_REGISTRY) == 2


def test_exact_10_widget_inventory():
    total = sum(len(v) for v in DASHBOARD_WIDGET_REGISTRY.values())
    assert total == 10
    expected_executive = {"WGT_HEALTH_SCORE_HEADLINE", "WGT_CREDIT_SCORE_HEADLINE", "WGT_TOP_RECOMMENDATIONS", "WGT_DATA_QUALITY_BADGE", "WGT_BENCHMARK_POSITION_SUMMARY"}
    expected_risk = {"WGT_HARD_FAIL_ALERTS", "WGT_CRITICAL_RECOMMENDATIONS", "WGT_RISK_TIER_BADGE", "WGT_BANKING_READINESS_ALERT", "WGT_UNCOVERED_SIGNAL_COUNT"}
    assert {w.widget_code for w in DASHBOARD_WIDGET_REGISTRY[DashboardType.EXECUTIVE_DASHBOARD]} == expected_executive
    assert {w.widget_code for w in DASHBOARD_WIDGET_REGISTRY[DashboardType.RISK_DASHBOARD]} == expected_risk


def test_all_widget_types_restricted_to_allowed_set():
    for widgets in DASHBOARD_WIDGET_REGISTRY.values():
        for w in widgets:
            assert w.widget_type in ALLOWED_DASHBOARD_WIDGET_TYPES


def test_dashboard_snapshot_is_not_a_subtype_of_executive_report_result():
    assert not issubclass(DashboardSnapshot, ExecutiveReportResult)
    assert not issubclass(ExecutiveReportResult, DashboardSnapshot)
    dashboard_fields = {f for f in DashboardSnapshot.__dataclass_fields__}
    report_fields = {f for f in ExecutiveReportResult.__dataclass_fields__}
    assert "sections" not in dashboard_fields
    assert "widgets" not in report_fields


def test_dashboard_produces_no_sections_or_narrative_paragraphs():
    benchmark, hs, cs, rec = _build_upstream()
    snap = generate_dashboard_snapshot(
        DashboardType.EXECUTIVE_DASHBOARD, hs, cs, rec, benchmark_result_json=benchmark,
        company_metadata=ReportCompanyMetadata(company_name="Test"),
    )
    assert not hasattr(snap, "sections")
    for widget in snap.widgets:
        assert widget.widget_type.value in {"kpi_card", "badge", "chart_data"}


def test_golden_dataset_both_dashboard_types():
    benchmark, hs, cs, rec = _build_upstream()
    for dt in DashboardType:
        snap = generate_dashboard_snapshot(
            dt, hs, cs, rec, benchmark_result_json=benchmark,
            company_metadata=ReportCompanyMetadata(company_name="Test"),
        )
        assert len(snap.widgets) == 5, dt
        assert snap.legal_review_status.value == "internal_use_only"
        assert snap.external_distribution_allowed is False
        assert snap.decision_support_only is True


def test_dashboard_property_no_upstream_engine_calls():
    benchmark, hs, cs, rec = _build_upstream()
    with patch("app.engines.health_score.service.compute_financial_health_score") as m1, \
         patch("app.engines.credit_score.service.compute_credit_score") as m2, \
         patch("app.engines.recommendation.service.generate_recommendations") as m3:
        for dt in DashboardType:
            generate_dashboard_snapshot(dt, hs, cs, rec, benchmark_result_json=benchmark, company_metadata=ReportCompanyMetadata(company_name="Test"))
        for m in (m1, m2, m3):
            m.assert_not_called()


def test_dashboard_deterministic_output():
    benchmark, hs, cs, rec = _build_upstream()
    baseline = generate_dashboard_snapshot(DashboardType.EXECUTIVE_DASHBOARD, hs, cs, rec, benchmark_result_json=benchmark, company_metadata=ReportCompanyMetadata(company_name="Test"))
    for _ in range(25):
        again = generate_dashboard_snapshot(DashboardType.EXECUTIVE_DASHBOARD, hs, cs, rec, benchmark_result_json=benchmark, company_metadata=ReportCompanyMetadata(company_name="Test"))
        assert again == baseline


def test_generated_at_and_report_id_only_set_when_provided():
    benchmark, hs, cs, rec = _build_upstream()
    default = generate_dashboard_snapshot(DashboardType.EXECUTIVE_DASHBOARD, hs, cs, rec, benchmark_result_json=benchmark, company_metadata=ReportCompanyMetadata(company_name="Test"))
    assert default.generated_at is None and default.report_id is None
    explicit = generate_dashboard_snapshot(DashboardType.EXECUTIVE_DASHBOARD, hs, cs, rec, benchmark_result_json=benchmark, company_metadata=ReportCompanyMetadata(company_name="Test"), report_id="DASH-1", generated_at="2026-07-29T00:00:00Z")
    assert explicit.generated_at == "2026-07-29T00:00:00Z"
    assert explicit.report_id == "DASH-1"


def test_no_datetime_now_uuid4_random_in_dashboard_service_source():
    from app.engines.dashboards import service as dashboard_service

    source = inspect.getsource(dashboard_service)
    assert "datetime.now(" not in source
    assert "uuid4()" not in source
    assert "random." not in source
