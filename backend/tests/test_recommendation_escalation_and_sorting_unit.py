"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 6/10: öncelik/
severity eskalasyon modeli (Bölüm 9.2) + stable deterministic sıralama
(Bölüm 9.3 / kullanıcının implementasyon-onay mesajı madde 9).
"""

from decimal import Decimal

from app.engines.common.recommendation_types import (
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSeverity,
    RecommendationTriggerSource,
    ResultBucket,
)
from app.engines.recommendation.service import _apply_priority_escalation, _sort_key


def _candidate(**overrides):
    base = {
        "base_priority": RecommendationPriority.MEDIUM,
        "priority": RecommendationPriority.MEDIUM,
        "severity": RecommendationSeverity.MEDIUM,
        "confidence": Decimal("0.75"),
        "triggered_by": (),
        "category": RecommendationCategory.LIQUIDITY,
        "recommendation_code": "_TEST_CODE",
    }
    base.update(overrides)
    return base


def test_hard_fail_escalates_unconditionally_to_critical():
    candidate = _candidate(
        base_priority=RecommendationPriority.MEDIUM,
        triggered_by=(RecommendationTriggerSource.HEALTH_SCORE_HARD_FAIL.value,),
    )
    _apply_priority_escalation(candidate, {})
    assert candidate["priority"] == RecommendationPriority.CRITICAL
    # base_priority (registry değeri, burada rule referansı DEĞİL, kayıt
    # simülasyonu) MUTASYONA UĞRAMADI -- yalnızca öğrenilen alan değişti.
    assert candidate["base_priority"] == RecommendationPriority.MEDIUM


def test_critical_override_escalates_to_at_least_high():
    candidate = _candidate(
        base_priority=RecommendationPriority.MEDIUM,
        triggered_by=(RecommendationTriggerSource.CREDIT_SCORE_CRITICAL_OVERRIDE.value,),
    )
    _apply_priority_escalation(candidate, {})
    assert candidate["priority"] == RecommendationPriority.HIGH


def test_critical_override_does_not_downgrade_already_critical():
    candidate = _candidate(
        base_priority=RecommendationPriority.CRITICAL,
        triggered_by=(RecommendationTriggerSource.CREDIT_SCORE_CRITICAL_OVERRIDE.value,),
    )
    _apply_priority_escalation(candidate, {})
    assert candidate["priority"] == RecommendationPriority.CRITICAL


def test_severity_nudge_is_exactly_one_rank_and_never_skips():
    candidate = _candidate(
        base_priority=RecommendationPriority.LOW,
        severity=RecommendationSeverity.CRITICAL,
        confidence=Decimal("0.90"),
    )
    _apply_priority_escalation(candidate, {})
    assert candidate["priority"] == RecommendationPriority.MEDIUM  # LOW -> MEDIUM, tek kademe


def test_low_confidence_blocks_severity_nudge():
    candidate = _candidate(
        base_priority=RecommendationPriority.LOW,
        severity=RecommendationSeverity.CRITICAL,
        confidence=Decimal("0.40"),
    )
    _apply_priority_escalation(candidate, {})
    assert candidate["priority"] == RecommendationPriority.LOW  # nüans ENGELLENDİ


def test_no_escalation_when_severity_not_critical_and_no_hard_fail_or_override():
    candidate = _candidate(base_priority=RecommendationPriority.MEDIUM, severity=RecommendationSeverity.MEDIUM)
    _apply_priority_escalation(candidate, {})
    assert candidate["priority"] == RecommendationPriority.MEDIUM


def test_sort_key_orders_by_priority_rank_first():
    critical = _candidate(priority=RecommendationPriority.CRITICAL, recommendation_code="A")
    critical["priority_rank"] = 0
    low = _candidate(priority=RecommendationPriority.LOW, recommendation_code="B")
    low["priority_rank"] = 3
    assert _sort_key(critical) < _sort_key(low)


def test_sort_is_deterministic_and_independent_of_input_order():
    import random

    candidates = []
    for i in range(10):
        c = _candidate(recommendation_code=f"CODE_{i:02d}", confidence=Decimal("0.75"))
        c["priority_rank"] = i % 3
        candidates.append(c)

    baseline = sorted(candidates, key=_sort_key)
    baseline_codes = [c["recommendation_code"] for c in baseline]

    for _ in range(20):
        shuffled = list(candidates)
        random.shuffle(shuffled)
        result = sorted(shuffled, key=_sort_key)
        assert [c["recommendation_code"] for c in result] == baseline_codes
