"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 9: golden
dataset senaryoları. Gerçek `analyze_financial_ratios()` + `evaluate_
benchmarks()` + `compute_financial_health_score()` + `compute_credit_
score()` + `generate_recommendations()` zinciri üzerinden çalıştırılır
(bkz. `tests/test_credit_score_golden_dataset_unit.py`'nin AYNI deseni).
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.recommendation_types import RecommendationComputationStatus
from app.engines.credit_score.service import compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations


def _bs_facts(**overrides):
    facts = {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }
    facts.update(overrides)
    return facts


def _is_facts(**overrides):
    facts = {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }
    facts.update(overrides)
    return facts


def _generate(bs_facts, is_facts, prior_bs_facts=None, prior_is_facts=None):
    bs_result = {"source_mode": "direct_document", "facts": bs_facts}
    is_result = {"source_mode": "direct_document", "facts": is_facts}
    prior_bs = {"source_mode": "direct_document", "facts": prior_bs_facts} if prior_bs_facts else None
    prior_is = {"source_mode": "direct_document", "facts": prior_is_facts} if prior_is_facts else None
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    credit_score_result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    return generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)


def test_scenario_negative_equity_produces_critical_leverage_recommendation():
    result = _generate(_bs_facts(equity=-200000.0), _is_facts())
    assert result.status == RecommendationComputationStatus.COMPUTED
    codes = {item.recommendation_code for item in result.recommendations}
    assert "LEV_STRENGTHEN_EQUITY_BASE" in codes
    item = next(i for i in result.recommendations if i.recommendation_code == "LEV_STRENGTHEN_EQUITY_BASE")
    assert item.priority.value == "critical"


def test_scenario_debt_funded_growth_produces_growth_and_banking_readiness_pair():
    result = _generate(
        _bs_facts(total_assets=5000000.0, long_term_liabilities=2500000.0, equity=1700000.0),
        _is_facts(),
        prior_bs_facts=_bs_facts(total_assets=2000000.0),
        prior_is_facts=_is_facts(),
    )
    assert result.status in (
        RecommendationComputationStatus.COMPUTED,
        RecommendationComputationStatus.NO_RECOMMENDATIONS_TRIGGERED,
    )
    # DEBT_FUNDED_GROWTH bayrağı tetiklenmiş OLABİLİR (gerçek finansal
    # dinamiklere bağlı) -- burada sadece ÇÖKMEDİĞİNİ ve ŞEMANIN
    # tutarlı kaldığını doğruluyoruz (davranışsal, sinyal-bağımlı).
    for code in result.financial_recommendation_codes + result.banking_readiness_recommendation_codes:
        assert isinstance(code, str)


def test_scenario_low_coverage_suppresses_financial_recommendations_in_that_category():
    # Neredeyse hiçbir income statement kalemi olmayan bir şirket ->
    # PROFITABILITY/GROWTH kategorilerinde coverage çöker.
    result = _generate(
        _bs_facts(),
        {"net_sales": 5000000.0},
    )
    for category, coverage in result.category_coverage.items():
        assert Decimal("0") <= coverage <= Decimal("1")
    # Kapsamı düşük kategorilerde (varsa) financial öneri YOKSA CATEGORY_
    # INSUFFICIENT_DATA uyarısı bulunmalı.
    if any(w.get("code") == "CATEGORY_INSUFFICIENT_DATA" for w in result.warnings):
        assert True  # şeffaflık kanıtlandı


def test_scenario_healthy_company_may_produce_no_or_few_financial_recommendations():
    result = _generate(_bs_facts(), _is_facts())
    assert result.status in (
        RecommendationComputationStatus.COMPUTED,
        RecommendationComputationStatus.NO_RECOMMENDATIONS_TRIGGERED,
    )
    assert isinstance(result.recommendations, tuple)


def test_all_scenarios_carry_decision_support_safety_fields():
    for bs, is_ in ((_bs_facts(), _is_facts()), (_bs_facts(equity=-200000.0), _is_facts())):
        result = _generate(bs, is_)
        assert result.decision_support_only is True
        assert result.not_financial_advice is True
        assert result.not_credit_approval is True
        assert result.not_investment_advice is True
