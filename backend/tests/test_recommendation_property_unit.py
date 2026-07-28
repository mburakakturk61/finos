"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 7/8/10 (ZORUNLU):
`INVARIANT: RECOMMENDATION_ENGINE_READ_ONLY` property testi + determinizm
+ registry sıra bağımsızlığı + `RecommendationDirectionalContext`'in
SIFIR sayısal değer taşıdığının kanıtı.
"""

import copy
import re
from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.credit_score_registry import CREDIT_RATIO_SCORE_WEIGHTS
from app.engines.common.health_score_registry import RATIO_SCORE_WEIGHTS
from app.engines.common.ratio_formulas import RATIO_REGISTRY
from app.engines.common.recommendation_registry import RECOMMENDATION_RULES
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


def _build_inputs(equity=1700000.0):
    bs_result = {"source_mode": "direct_document", "facts": _bs_facts(equity=equity)}
    is_result = {"source_mode": "direct_document", "facts": _is_facts()}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    credit_score_result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    return ratio_result, benchmark_result, health_score_result, credit_score_result


def test_read_only_invariant_inputs_and_registries_unchanged_after_call():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs()

    ratio_before = copy.deepcopy(ratio_result)
    benchmark_before = copy.deepcopy(benchmark_result)
    ratio_registry_size = len(RATIO_REGISTRY)
    benchmark_registry_size = len(BENCHMARK_REGISTRY)
    health_weights_size = len(RATIO_SCORE_WEIGHTS)
    credit_weights_size = len(CREDIT_RATIO_SCORE_WEIGHTS)
    rules_size = len(RECOMMENDATION_RULES)

    generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)

    assert ratio_result == ratio_before
    assert benchmark_result == benchmark_before
    assert len(RATIO_REGISTRY) == ratio_registry_size
    assert len(BENCHMARK_REGISTRY) == benchmark_registry_size
    assert len(RATIO_SCORE_WEIGHTS) == health_weights_size
    assert len(CREDIT_RATIO_SCORE_WEIGHTS) == credit_weights_size
    assert len(RECOMMENDATION_RULES) == rules_size


def test_determinism_100_iterations_bit_identical_output():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs(equity=-200000.0)

    first = generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
    first_codes = tuple(item.recommendation_code for item in first.recommendations)
    first_priorities = tuple(item.priority for item in first.recommendations)
    first_confidences = tuple(item.confidence for item in first.recommendations)

    for _ in range(100):
        result = generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
        assert tuple(item.recommendation_code for item in result.recommendations) == first_codes
        assert tuple(item.priority for item in result.recommendations) == first_priorities
        assert tuple(item.confidence for item in result.recommendations) == first_confidences


def test_output_order_independent_of_registry_insertion_order():
    import app.engines.common.recommendation_registry as reg_module

    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs(equity=-200000.0)
    baseline = generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
    baseline_codes = tuple(item.recommendation_code for item in baseline.recommendations)

    original_rules = reg_module.RECOMMENDATION_RULES
    try:
        shuffled = tuple(reversed(original_rules))
        reg_module.RECOMMENDATION_RULES = shuffled
        result = generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
        assert tuple(item.recommendation_code for item in result.recommendations) == baseline_codes
    finally:
        reg_module.RECOMMENDATION_RULES = original_rules


def test_directional_context_never_contains_a_digit():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs(equity=-200000.0)
    result = generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
    for item in result.recommendations:
        if item.directional_context is not None:
            assert not re.search(r"\d", item.directional_context.improvement_direction_tr)
            if item.directional_context.next_better_tier_name is not None:
                assert not re.search(r"\d", item.directional_context.next_better_tier_name)


def test_upstream_engines_are_never_called_by_recommendation_engine():
    """Bölüm 19.1/28 madde 8 -- gerçek simülasyon/skor yeniden hesaplama YOK."""

    import unittest.mock as mock

    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs()

    with (
        mock.patch("app.engines.financial_ratios.service.analyze_financial_ratios") as m1,
        mock.patch("app.engines.benchmarks.service.evaluate_benchmarks") as m2,
        mock.patch("app.engines.health_score.service.compute_financial_health_score") as m3,
        mock.patch("app.engines.credit_score.service.compute_credit_score") as m4,
    ):
        generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
        m1.assert_not_called()
        m2.assert_not_called()
        m3.assert_not_called()
        m4.assert_not_called()
