"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 8b (ZORUNLU):
confidence modeli (Bölüm 15.4 madde a-h) -- min-ceiling davranışı,
DATA_QUALITY sabit 1.00, confidence != coverage.
"""

from decimal import Decimal

from app.engines.common.recommendation_registry import RECOMMENDATION_RULES
from app.engines.common.recommendation_types import RecommendationCategory
from app.engines.recommendation.service import _compute_confidence


def _rule(code: str):
    return next(r for r in RECOMMENDATION_RULES if r.recommendation_code == code)


def test_data_quality_items_always_have_fixed_confidence_1_00():
    rule = _rule("DQ_IMPROVE_LIQUIDITY_DATA_COVERAGE")
    result = _compute_confidence(rule, (), {}, {}, {})
    assert result["confidence"] == Decimal("1.00")
    assert result["confidence_basis"] == "data_coverage_fact"


def test_confidence_is_minimum_not_average_of_ceilings():
    rule = _rule("LIQ_IMPROVE_QUICK_RATIO")  # confidence_ceiling=0.75
    signals = {"quick_ratio": {"tier": "critical", "ratio_reliability": "high", "benchmark_reliability": "high"}}
    provisional_by_ratio = {"quick_ratio": False}
    category_coverage = {RecommendationCategory.LIQUIDITY.value: Decimal("0.30")}  # < 0.50 -> ceiling 0.50
    triggering_evidence = rule.evidence_rules
    result = _compute_confidence(rule, triggering_evidence, signals, provisional_by_ratio, category_coverage)
    # min(evidence_ceiling=1.00, rule_ceiling=0.75, provisional_ceiling=1.00, coverage_ceiling=0.50) = 0.50
    assert result["confidence"] == Decimal("0.50")
    assert result["confidence_basis"] == "category_coverage"


def test_provisional_evidence_caps_confidence_at_0_75():
    rule = _rule("LIQ_IMPROVE_QUICK_RATIO")
    signals = {"quick_ratio": {"tier": "critical", "ratio_reliability": "high", "benchmark_reliability": "high"}}
    provisional_by_ratio = {"quick_ratio": True}
    category_coverage = {RecommendationCategory.LIQUIDITY.value: Decimal("1.0")}
    result = _compute_confidence(rule, rule.evidence_rules, signals, provisional_by_ratio, category_coverage)
    assert result["confidence"] <= Decimal("0.75")
    assert result["provisional"] is True


def test_low_evidence_reliability_caps_confidence_via_reliability_map():
    rule = _rule("LIQ_IMPROVE_QUICK_RATIO")
    signals = {"quick_ratio": {"tier": "critical", "ratio_reliability": "low", "benchmark_reliability": "low"}}
    provisional_by_ratio = {"quick_ratio": False}
    category_coverage = {RecommendationCategory.LIQUIDITY.value: Decimal("1.0")}
    result = _compute_confidence(rule, rule.evidence_rules, signals, provisional_by_ratio, category_coverage)
    assert result["confidence"] == Decimal("0.50")
    assert result["confidence_basis"] == "evidence_reliability"


def test_confidence_result_is_decimal_quantized_to_2_decimals():
    rule = _rule("LIQ_IMPROVE_QUICK_RATIO")
    signals = {"quick_ratio": {"tier": "critical", "ratio_reliability": "high", "benchmark_reliability": "high"}}
    result = _compute_confidence(rule, rule.evidence_rules, signals, {"quick_ratio": False}, {RecommendationCategory.LIQUIDITY.value: Decimal("1.0")})
    assert isinstance(result["confidence"], Decimal)
    assert result["confidence"] == result["confidence"].quantize(Decimal("0.01"))
    assert Decimal("0") <= result["confidence"] <= Decimal("1")


def test_confidence_and_coverage_are_never_conflated():
    # coverage is a SEPARATE field passed through unchanged; confidence
    # is DERIVED via min-ceiling -- they may coincide numerically but are
    # NEVER the same field / never substitute one another.
    rule = _rule("LIQ_IMPROVE_QUICK_RATIO")
    signals = {"quick_ratio": {"tier": "critical", "ratio_reliability": "high", "benchmark_reliability": "high"}}
    category_coverage = {RecommendationCategory.LIQUIDITY.value: Decimal("0.55")}
    result = _compute_confidence(rule, rule.evidence_rules, signals, {"quick_ratio": False}, category_coverage)
    # coverage_ceiling band for 0.55 (>=0.50,<0.80) -> 0.75; rule ceiling 0.75 too.
    assert result["confidence"] == Decimal("0.75")
    # coverage itself (0.55) is reported separately in the candidate dict,
    # not overwritten by confidence (0.75) -- verified at the candidate level
    # in test_recommendation_service integration tests.
