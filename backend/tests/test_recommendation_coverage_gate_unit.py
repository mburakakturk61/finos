"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 6a (ZORUNLU):
coverage-gate muafiyeti (`coverage_policy=exempt_hard_fail`) + negatif
kontrol (`subject_to_gate` elenir).
"""

from decimal import Decimal

from app.engines.common.recommendation_registry import RECOMMENDATION_RULES
from app.engines.common.recommendation_types import RecommendationCategory
from app.engines.recommendation.service import passes_coverage_gate


def _rule(code: str):
    return next(r for r in RECOMMENDATION_RULES if r.recommendation_code == code)


def test_exempt_hard_fail_rule_passes_gate_even_at_zero_coverage():
    rule = _rule("LEV_STRENGTHEN_EQUITY_BASE")
    assert rule.coverage_policy == "exempt_hard_fail"
    zero_coverage = {RecommendationCategory.LEVERAGE.value: Decimal("0.0")}
    assert passes_coverage_gate(rule, zero_coverage) is True


def test_second_exempt_hard_fail_rule_passes_gate_even_at_zero_coverage():
    rule = _rule("LEV_IMPROVE_INTEREST_COVERAGE")
    zero_coverage = {RecommendationCategory.LEVERAGE.value: Decimal("0.0")}
    assert passes_coverage_gate(rule, zero_coverage) is True


def test_subject_to_gate_rule_is_excluded_at_zero_coverage_negative_control():
    rule = _rule("LEV_REVIEW_DEBT_MATURITY_MIX")
    assert rule.coverage_policy == "subject_to_gate"
    zero_coverage = {RecommendationCategory.LEVERAGE.value: Decimal("0.0")}
    assert passes_coverage_gate(rule, zero_coverage) is False


def test_subject_to_gate_rule_passes_at_high_coverage():
    rule = _rule("LEV_REVIEW_DEBT_MATURITY_MIX")
    high_coverage = {RecommendationCategory.LEVERAGE.value: Decimal("0.90")}
    assert passes_coverage_gate(rule, high_coverage) is True


def test_always_evaluated_data_quality_rule_passes_gate_regardless_of_coverage():
    rule = _rule("DQ_IMPROVE_LEVERAGE_DATA_COVERAGE")
    assert rule.coverage_policy == "always_evaluated"
    zero_coverage = {RecommendationCategory.LEVERAGE.value: Decimal("0.0")}
    assert passes_coverage_gate(rule, zero_coverage) is True


def test_boundary_exactly_at_threshold_passes():
    from app.engines.common.recommendation_types import CATEGORY_COVERAGE_GATE_THRESHOLD

    rule = _rule("LEV_REVIEW_DEBT_MATURITY_MIX")
    boundary_coverage = {RecommendationCategory.LEVERAGE.value: CATEGORY_COVERAGE_GATE_THRESHOLD}
    assert passes_coverage_gate(rule, boundary_coverage) is True
