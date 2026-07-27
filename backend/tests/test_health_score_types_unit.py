"""
Milestone 4.3D (Financial Health Score) / Adım 1: `app/engines/common/
health_score_types.py` için gerçek, çalıştırılabilir birim testleri.

Not: bu sandbox'ta `pytest` kurulu değil (bkz. tests/README.md) --
diğer `app/engines/**` testleriyle AYNI konvansiyon: düz `test_*()`
fonksiyonları, `assert` + `try/except` ile hata-yolu testleri, harici bir
test çatısına bağımlılık YOK.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

from app.engines.common.health_score_types import (
    CRITICAL_OVERRIDE_CATEGORY_FLOOR,
    CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
    CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
    HEALTH_SCORE_MODEL_VERSION,
    HEALTH_SCORE_SCHEMA_VERSION,
    INSUFFICIENT_DATA_COVERAGE_THRESHOLD,
    LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD,
    PROVISIONAL_CONFIDENCE_CEILING,
    STRENGTHS_WEAKNESSES_COUNT,
    TIER_TO_POINTS,
    CategoryBreakdown,
    CategoryWeightProfile,
    CriticalOverrideRule,
    HardFailRule,
    HealthScoreComputationStatus,
    HealthScoreResult,
    HealthScoreTier,
    RatioContribution,
    RatioScoreWeight,
    clamp_score,
)


# --- Enum / sabit envanteri ----------------------------------------------


def test_health_score_tier_has_exactly_5_values_matching_benchmark_tiers():
    assert {t.value for t in HealthScoreTier} == {
        "excellent", "good", "average", "weak", "critical",
    }


def test_health_score_computation_status_has_exactly_3_values():
    assert {s.value for s in HealthScoreComputationStatus} == {
        "computed", "hard_fail_capped", "insufficient_data",
    }


def test_tier_to_points_has_5_entries_linear_spacing():
    assert TIER_TO_POINTS == {
        "excellent": Decimal("100"),
        "good": Decimal("75"),
        "average": Decimal("50"),
        "weak": Decimal("25"),
        "critical": Decimal("0"),
    }


def test_version_constants_are_non_empty_strings():
    assert isinstance(HEALTH_SCORE_SCHEMA_VERSION, str) and HEALTH_SCORE_SCHEMA_VERSION
    assert isinstance(HEALTH_SCORE_MODEL_VERSION, str) and HEALTH_SCORE_MODEL_VERSION


def test_binding_constants_match_design_doc_round_4():
    assert PROVISIONAL_CONFIDENCE_CEILING == Decimal("0.60")
    assert INSUFFICIENT_DATA_COVERAGE_THRESHOLD == Decimal("0.50")
    assert LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD == Decimal("0.70")
    assert CRITICAL_OVERRIDE_WEAK_MULTIPLIER == Decimal("0.90")
    assert CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER == Decimal("0.70")
    assert CRITICAL_OVERRIDE_CATEGORY_FLOOR == Decimal("0.50")
    assert STRENGTHS_WEAKNESSES_COUNT == 5


# --- clamp_score ----------------------------------------------------------


def test_clamp_score_clamps_below_zero():
    assert clamp_score(Decimal("-15.5")) == Decimal("0")


def test_clamp_score_clamps_above_100_exact():
    assert clamp_score(Decimal("142")) == Decimal("100")


def test_clamp_score_passes_through_in_range_value():
    assert clamp_score(Decimal("55.5")) == Decimal("55.5")


def test_clamp_score_boundary_values_are_inclusive():
    assert clamp_score(Decimal("0")) == Decimal("0")
    assert clamp_score(Decimal("100")) == Decimal("100")


def test_clamp_score_none_passthrough():
    assert clamp_score(None) is None


# --- Dataclass'ların immutable (frozen) olduğu ----------------------------


def test_category_weight_profile_is_frozen():
    profile = CategoryWeightProfile(
        scope="global", scope_key=None, category_weights={"liquidity": Decimal("0.20")}
    )
    try:
        profile.scope = "industry"
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_ratio_score_weight_is_frozen_and_defaults():
    weight = RatioScoreWeight(
        ratio_code="current_ratio", category="liquidity", ratio_weight=Decimal("0.20")
    )
    assert weight.excluded_as_duplicate_of is None
    assert weight.duplicate_relationship is None
    try:
        weight.ratio_weight = Decimal("0.30")
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_hard_fail_rule_is_frozen():
    rule = HardFailRule(
        rule_code="NEGATIVE_EQUITY",
        predicate=lambda ratios, benchmarks: False,
        score_ceiling=Decimal("25"),
        rationale_tr="test",
    )
    try:
        rule.score_ceiling = Decimal("30")
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_critical_override_rule_is_frozen():
    rule = CriticalOverrideRule(
        ratio_code="current_ratio",
        category="liquidity",
        weak_multiplier=Decimal("0.90"),
        critical_multiplier=Decimal("0.70"),
        rationale_tr="test",
    )
    try:
        rule.category = "leverage"
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_ratio_contribution_all_fields_settable():
    contribution = RatioContribution(
        ratio_code="current_ratio",
        benchmark_status="evaluated",
        tier="good",
        ratio_score=Decimal("75"),
        ratio_weight_applied=Decimal("0.20"),
        tier_fallback_used=False,
        reliability="medium",
        is_duplicate_excluded=False,
    )
    assert contribution.ratio_score == Decimal("75")


def test_category_breakdown_holds_ratio_contributions_tuple():
    breakdown = CategoryBreakdown(
        category="liquidity",
        raw_score=Decimal("70"),
        score_after_override=Decimal("70"),
        weight_applied=Decimal("0.20"),
        coverage_ratio=Decimal("1.0"),
        redistributed_weights={"current_ratio": Decimal("1.0")},
        critical_overrides_applied=(),
        ratio_contributions=(),
    )
    assert breakdown.ratio_contributions == ()


def test_health_score_result_is_frozen_and_holds_all_mandatory_fields():
    result = HealthScoreResult(
        status=HealthScoreComputationStatus.COMPUTED,
        final_score=Decimal("70.0"),
        pre_hard_fail_score=Decimal("70.0"),
        letter_rating="Sağlıklı",
        rating_disclaimer_tr="resmi kredi derecelendirmesi degildir",
        confidence_score=Decimal("0.60"),
        data_coverage_ratio=Decimal("0.90"),
        low_confidence_warning=False,
        provisional=True,
        category_breakdown=(),
        hard_fails_triggered=(),
        critical_overrides_applied=(),
        scoreable_ratio_codes=(),
        excluded_duplicate_ratio_codes=(),
        strengths=(),
        weaknesses=(),
        warnings=(),
        health_score_schema_version=HEALTH_SCORE_SCHEMA_VERSION,
        health_score_model_version=HEALTH_SCORE_MODEL_VERSION,
        benchmark_registry_version="1.0.0",
        ratio_registry_version="1.1.0",
        category_weight_profile_used="global",
    )
    try:
        result.final_score = Decimal("80.0")
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass
