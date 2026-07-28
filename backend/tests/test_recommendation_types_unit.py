"""
Milestone 4.3F (Recommendation Engine) / Adım 1: `app/engines/common/
recommendation_types.py` için gerçek, çalıştırılabilir birim testleri.
"""

import dataclasses
from decimal import Decimal

from app.engines.common.recommendation_types import (
    RECOMMENDATION_DISCLAIMER_TR,
    RecommendationCategory,
    RecommendationComputationStatus,
    RecommendationDifficultyBand,
    RecommendationImpactBand,
    RecommendationItem,
    RecommendationPriority,
    RecommendationResult,
    RecommendationRule,
    RecommendationSeverity,
    RecommendationTriggerStrategy,
    ResultBucket,
    category_to_result_bucket,
    next_better_tier_name,
    resolve_disclaimer_tr,
)


def test_recommendation_category_has_exactly_8_values():
    assert len(list(RecommendationCategory)) == 8


def test_recommendation_computation_status_has_exactly_5_values():
    assert len(list(RecommendationComputationStatus)) == 5
    values = {s.value for s in RecommendationComputationStatus}
    assert values == {
        "computed", "no_recommendations_triggered", "insufficient_data",
        "schema_incompatible", "version_mismatch",
    }


def test_recommendation_trigger_strategy_has_exactly_8_closed_strategies():
    assert len(list(RecommendationTriggerStrategy)) == 8


def test_category_to_result_bucket_deterministic_mapping():
    for category in (
        RecommendationCategory.LIQUIDITY, RecommendationCategory.WORKING_CAPITAL,
        RecommendationCategory.LEVERAGE, RecommendationCategory.PROFITABILITY,
        RecommendationCategory.ACTIVITY, RecommendationCategory.GROWTH,
    ):
        assert category_to_result_bucket(category) == ResultBucket.FINANCIAL
    assert category_to_result_bucket(RecommendationCategory.BANKING_READINESS) == ResultBucket.BANKING_READINESS
    assert category_to_result_bucket(RecommendationCategory.DATA_QUALITY) == ResultBucket.DATA_QUALITY


def test_recommendation_rule_is_frozen():
    assert dataclasses.fields(RecommendationRule)
    frozen_params = RecommendationRule.__dataclass_params__
    assert frozen_params.frozen is True


def test_recommendation_item_is_frozen():
    assert RecommendationItem.__dataclass_params__.frozen is True


def test_recommendation_result_is_frozen():
    assert RecommendationResult.__dataclass_params__.frozen is True


def test_priority_and_severity_and_bands_are_closed_enums():
    assert {p.value for p in RecommendationPriority} == {
        "critical", "high", "medium", "low", "informational",
    }
    assert {s.value for s in RecommendationSeverity} == {"critical", "high", "medium", "low"}
    assert {i.value for i in RecommendationImpactBand} == {"high", "medium", "low"}
    assert {d.value for d in RecommendationDifficultyBand} == {
        "low_effort", "moderate_effort", "structural_effort",
    }


def test_next_better_tier_name_never_returns_a_number():
    import re

    for tier in ("critical", "weak", "average", "good", "excellent", None, "unknown"):
        result = next_better_tier_name(tier)
        assert result is None or isinstance(result, str)
        if result is not None:
            assert not re.search(r"\d", result), f"'{result}' bir rakam İÇERİYOR."
    assert next_better_tier_name("critical") == "weak"
    assert next_better_tier_name("excellent") is None


def test_resolve_disclaimer_tr_general_vs_banking():
    general = resolve_disclaimer_tr("general")
    banking = resolve_disclaimer_tr("banking")
    assert general == RECOMMENDATION_DISCLAIMER_TR
    assert general in banking
    assert "kredi limiti" in banking
    assert len(banking) > len(general)


def test_recommendation_disclaimer_has_no_hardcoded_brand_name():
    # Bölüm 2.1 madde 12 -- jenerik "platformun içsel..." kalıbı, marka adı YOK.
    banned_terms = ("FINOS",)
    for term in banned_terms:
        assert term not in RECOMMENDATION_DISCLAIMER_TR
