"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 11: `tests/
conftest.py`'nin genişletilmiş autouse fixture'ının kapsadığı 4 yeni
registry için temizlik/regresyon testleri (bu dosyanın KENDİSİ, sandbox
test runner fixture MEKANİZMASINI kullanmadığı için, `try/finally` İLE
kendi temizliğini yapar -- Bölüm 1.6 NOT 1'in disiplini).
"""

from decimal import Decimal

import app.engines.common.recommendation_registry as reg_module
from app.engines.common.recommendation_registry import (
    RECOMMENDATION_RULES,
    register_recommendation_rule,
)
from app.engines.common.recommendation_types import (
    EvidenceRule,
    RecommendationCategory,
    RecommendationDifficultyBand,
    RecommendationImpactBand,
    RecommendationPriority,
    RecommendationRule,
    RecommendationSeverity,
    RecommendationTriggerStrategy,
    ResultBucket,
    resolve_disclaimer_tr,
)


def test_temporary_registration_does_not_leak_into_global_registry():
    original_size = len(reg_module.RECOMMENDATION_RULES_BY_CODE)
    temp_rule = RecommendationRule(
        recommendation_code="_test_temp_rule",
        category=RecommendationCategory.LIQUIDITY,
        result_bucket=ResultBucket.FINANCIAL,
        base_priority=RecommendationPriority.MEDIUM,
        severity=RecommendationSeverity.MEDIUM,
        impact_band=RecommendationImpactBand.MEDIUM,
        difficulty_band=RecommendationDifficultyBand.MODERATE_EFFORT,
        trigger_strategy=RecommendationTriggerStrategy.ALL_CONDITIONS,
        trigger_mode="all",
        evidence_rules=(EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),),
        minimum_evidence_count=1,
        prerequisite_rules=(), blocking_rules=(),
        merge_group=None, evidence_group="_test", underlying_risk_code="_TEST",
        conflict_group=None, mutually_exclusive_group=None,
        confidence_ceiling=Decimal("0.75"), coverage_policy="subject_to_gate",
        related_ratio_codes=("current_ratio",),
        title_tr="Test", explanation_tr="Test", action_steps_tr=("Test",), assumptions_tr=("Test",),
        disclaimer_tr=resolve_disclaimer_tr("general"), disclaimer_scope="general",
        model_version_introduced="1.0.0", deprecated_since=None, replacement_recommendation_code=None,
    )
    isolated_registry = {}
    register_recommendation_rule(temp_rule, registry=isolated_registry)

    assert len(reg_module.RECOMMENDATION_RULES_BY_CODE) == original_size
    assert "_test_temp_rule" not in reg_module.RECOMMENDATION_RULES_BY_CODE
    assert len(RECOMMENDATION_RULES) == 39


def test_calling_generate_recommendations_repeatedly_does_not_grow_registries():
    from datetime import date

    import app.engines.common.benchmark_registry  # noqa: F401
    from app.engines.benchmarks.service import evaluate_benchmarks
    from app.engines.credit_score.service import compute_credit_score
    from app.engines.financial_ratios.service import analyze_financial_ratios
    from app.engines.health_score.service import compute_financial_health_score
    from app.engines.recommendation.service import generate_recommendations

    bs_result = {"source_mode": "direct_document", "facts": {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }}
    is_result = {"source_mode": "direct_document", "facts": {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    credit_score_result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    size_before = len(RECOMMENDATION_RULES)
    for _ in range(10):
        generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
    assert len(RECOMMENDATION_RULES) == size_before


def test_recommendation_rules_by_code_matches_recommendation_rules_tuple():
    assert set(reg_module.RECOMMENDATION_RULES_BY_CODE.keys()) == {
        r.recommendation_code for r in RECOMMENDATION_RULES
    }
