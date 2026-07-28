"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 4/4a/5: dedup/
merge (`merge_group`) + çakışma/mutually-exclusive ilişkileri.
"""

from decimal import Decimal

from app.engines.common.recommendation_types import (
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSeverity,
    ResultBucket,
)
from app.engines.recommendation.service import (
    _apply_conflicts_and_mutual_exclusion,
    _merge_candidates,
)


def _candidate(**overrides):
    base = {
        "recommendation_code": "_TEST",
        "merge_group": None,
        "triggered_by": ("health_score_weak_tier",),
        "related_ratio_codes": ("current_ratio",),
        "supporting_evidence": ({"ratio_code": "current_ratio"},),
        "missing_inputs": (),
        "warnings": (),
        "source_recommendation_codes": ("_TEST",),
        "priority": RecommendationPriority.MEDIUM,
        "base_priority": RecommendationPriority.MEDIUM,
        "confidence": Decimal("0.75"),
        "disclaimer_tr": "genel uyarı",
        "conflict_group_id": None,
        "conflicting_with": (),
        "mutually_exclusive_group_id": None,
    }
    base.update(overrides)
    return base


def test_same_merge_group_candidates_are_merged_into_one():
    a = _candidate(
        recommendation_code="A", merge_group="MG_TEST", triggered_by=("health_score_weak_tier",),
        related_ratio_codes=("current_ratio",), priority=RecommendationPriority.MEDIUM,
        confidence=Decimal("0.75"),
    )
    b = _candidate(
        recommendation_code="B", merge_group="MG_TEST", triggered_by=("banking_lens_signal",),
        related_ratio_codes=("quick_ratio",), priority=RecommendationPriority.HIGH,
        confidence=Decimal("0.60"),
    )
    merged = _merge_candidates([a, b])
    assert len(merged) == 1
    item = merged[0]
    assert set(item["triggered_by"]) == {"health_score_weak_tier", "banking_lens_signal"}
    assert set(item["related_ratio_codes"]) == {"current_ratio", "quick_ratio"}
    assert item["priority"] == RecommendationPriority.HIGH  # en yüksek
    assert item["confidence"] == Decimal("0.60")  # en düşük
    assert len(item["supporting_evidence"]) == 2  # hiçbir kanıt KAYBOLMADI


def test_no_merge_group_candidates_stay_separate():
    a = _candidate(recommendation_code="A", merge_group=None)
    b = _candidate(recommendation_code="B", merge_group=None)
    merged = _merge_candidates([a, b])
    assert len(merged) == 2


def test_single_member_merge_group_passes_through_unchanged():
    a = _candidate(recommendation_code="A", merge_group="MG_SOLO")
    merged = _merge_candidates([a])
    assert len(merged) == 1
    assert merged[0]["recommendation_code"] == "A"


def test_conflict_pairs_empty_in_v1_produces_no_conflict_groups():
    a = _candidate(recommendation_code="A")
    b = _candidate(recommendation_code="B")
    candidates, conflict_groups, meg_groups = _apply_conflicts_and_mutual_exclusion([a, b])
    assert conflict_groups == ()  # RECOMMENDATION_CONFLICT_PAIRS boş


def test_mutually_exclusive_group_marks_both_when_both_present():
    a = _candidate(recommendation_code="WC_REDUCE_INVENTORY_DAYS")
    b = _candidate(recommendation_code="WC_MAINTAIN_INVENTORY_SAFETY_BUFFER")
    candidates, conflict_groups, meg_groups = _apply_conflicts_and_mutual_exclusion([a, b])
    by_code = {c["recommendation_code"]: c for c in candidates}
    assert by_code["WC_REDUCE_INVENTORY_DAYS"]["mutually_exclusive_group_id"] == "MEG_INVENTORY_LEVEL"
    assert by_code["WC_MAINTAIN_INVENTORY_SAFETY_BUFFER"]["mutually_exclusive_group_id"] == "MEG_INVENTORY_LEVEL"
    assert len(meg_groups) == 1


def test_mutually_exclusive_pair_structurally_cannot_both_trigger_in_real_pipeline():
    # Bölüm 13.3 -- days_inventory_outstanding'in tier'ı MANTIKSAL olarak
    # yalnızca BİR bantta olabilir (weak/critical XOR good/excellent),
    # bu yüzden gerçek pipeline'da bu ikisi ASLA aynı anda tetiklenmez.
    from app.engines.common.recommendation_registry import RECOMMENDATION_RULES

    reduce_rule = next(r for r in RECOMMENDATION_RULES if r.recommendation_code == "WC_REDUCE_INVENTORY_DAYS")
    buffer_rule = next(r for r in RECOMMENDATION_RULES if r.recommendation_code == "WC_MAINTAIN_INVENTORY_SAFETY_BUFFER")
    reduce_tiers = set(reduce_rule.evidence_rules[0].tier_in)
    buffer_tiers = set(buffer_rule.evidence_rules[0].tier_in)
    assert reduce_tiers.isdisjoint(buffer_tiers)
