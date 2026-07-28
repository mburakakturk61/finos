"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 8.0'ın 8 kapalı, saf
strateji fonksiyonu için izole birim testleri (Bölüm 28 madde 3).
"""

from decimal import Decimal

from app.engines.common.recommendation_registry import (
    all_conditions,
    any_condition,
    banking_flag_present,
    data_coverage_gap,
    data_gap_present,
    debt_funded_growth,
    hard_fail_present,
    minimum_evidence,
)
from app.engines.common.recommendation_types import EvidenceRule, RecommendationCategory


def _empty_context(**overrides):
    context = {
        "signals": {},
        "health_score_hard_fails": set(),
        "health_score_critical_overrides": set(),
        "credit_score_hard_fails": set(),
        "credit_score_critical_overrides": set(),
        "banking_lens_flags": set(),
        "credit_score_data_gaps": set(),
        "category_coverage": {},
    }
    context.update(overrides)
    return context


def test_all_conditions_requires_every_evidence_true():
    context = _empty_context(
        signals={"current_ratio": {"tier": "critical"}, "quick_ratio": {"tier": "average"}}
    )
    rules = (
        EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),
        EvidenceRule(ratio_code="quick_ratio", tier_in=("critical",)),
    )
    assert all_conditions(rules, context) is False
    rules_all_true = (
        EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),
    )
    assert all_conditions(rules_all_true, context) is True


def test_any_condition_requires_at_least_one_true():
    context = _empty_context(signals={"current_ratio": {"tier": "average"}})
    rules = (
        EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),
        EvidenceRule(ratio_code="current_ratio", tier_in=("average",)),
    )
    assert any_condition(rules, context) is True
    rules_all_false = (EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),)
    assert any_condition(rules_all_false, context) is False


def test_minimum_evidence_counts_true_conditions():
    context = _empty_context(
        signals={
            "current_ratio": {"tier": "critical"},
            "quick_ratio": {"tier": "critical"},
            "cash_ratio": {"tier": "average"},
        }
    )
    rules = (
        EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),
        EvidenceRule(ratio_code="quick_ratio", tier_in=("critical",)),
        EvidenceRule(ratio_code="cash_ratio", tier_in=("critical",)),
    )
    assert minimum_evidence(rules, context, minimum_evidence_count=2) is True
    assert minimum_evidence(rules, context, minimum_evidence_count=3) is False


def test_hard_fail_present_checks_both_health_and_credit_score_sets():
    context = _empty_context(credit_score_hard_fails={"NEGATIVE_EQUITY"})
    rules = (EvidenceRule(hard_fail_code="NEGATIVE_EQUITY"),)
    assert hard_fail_present(rules, context) is True
    context_missing = _empty_context()
    assert hard_fail_present(rules, context_missing) is False


def test_banking_flag_present_checks_credit_score_banking_lens_flags():
    context = _empty_context(banking_lens_flags={"HIGH_LEVERAGE"})
    rules = (EvidenceRule(banking_lens_flag="HIGH_LEVERAGE"),)
    assert banking_flag_present(rules, context) is True
    assert banking_flag_present((EvidenceRule(banking_lens_flag="DEBT_SERVICE_STRESS"),), context) is False


def test_debt_funded_growth_is_special_named_wrapper_of_all_conditions():
    context = _empty_context(banking_lens_flags={"DEBT_FUNDED_GROWTH"})
    rules = (EvidenceRule(banking_lens_flag="DEBT_FUNDED_GROWTH"),)
    assert debt_funded_growth(rules, context) == all_conditions(rules, context) is True


def test_data_coverage_gap_checks_category_coverage_below_threshold():
    context = _empty_context(category_coverage={"liquidity": Decimal("0.30")})
    rules = (
        EvidenceRule(category_coverage_below=RecommendationCategory.LIQUIDITY, coverage_threshold=Decimal("0.50")),
    )
    assert data_coverage_gap(rules, context) is True
    context_ok = _empty_context(category_coverage={"liquidity": Decimal("0.90")})
    assert data_coverage_gap(rules, context_ok) is False


def test_data_gap_present_checks_credit_score_data_gaps():
    context = _empty_context(credit_score_data_gaps={"COLLATERAL"})
    rules = (EvidenceRule(credit_score_data_gap_code="COLLATERAL"),)
    assert data_gap_present(rules, context) is True
    assert data_gap_present((EvidenceRule(credit_score_data_gap_code="PAYMENT_HISTORY"),), context) is False


def test_strategies_are_pure_and_do_not_mutate_context():
    import copy

    context = _empty_context(signals={"current_ratio": {"tier": "critical"}})
    context_before = copy.deepcopy(context)
    rules = (EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),)
    all_conditions(rules, context)
    any_condition(rules, context)
    minimum_evidence(rules, context, minimum_evidence_count=1)
    assert context == context_before
