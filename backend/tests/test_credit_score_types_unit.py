"""
Milestone 4.3E (Credit Score Engine) / Adım 1: `app/engines/common/
credit_score_types.py` için gerçek, çalıştırılabilir birim testleri.

Not: bu sandbox'ta `pytest` kurulu değil (bkz. tests/README.md) --
diğer `app/engines/**` testleriyle AYNI konvansiyon: düz `test_*()`
fonksiyonları, `assert` + `try/except` ile hata-yolu testleri.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

from app.engines.common.credit_score_types import (
    CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR,
    CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
    CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
    CREDIT_INSUFFICIENT_DATA_COVERAGE_THRESHOLD,
    CREDIT_LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD,
    CREDIT_PROVISIONAL_CONFIDENCE_CEILING,
    CREDIT_SCORE_DATA_GAPS,
    CREDIT_SCORE_MODEL_VERSION,
    CREDIT_SCORE_SCHEMA_VERSION,
    STRENGTHS_WEAKNESSES_COUNT,
    TIER_TO_POINTS,
    BankingLensSignalRule,
    BankingLensSignals,
    CreditCategoryBreakdown,
    CreditCategoryWeightProfile,
    CreditCriticalOverrideRule,
    CreditHardFailRule,
    CreditRatioContribution,
    CreditRatioScoreWeight,
    CreditScoreComputationStatus,
    CreditScoreResult,
    DataGapDisclosure,
    HealthScoreReference,
    clamp_score,
    normalize_weights,
)


# --- Enum / sabit envanteri ------------------------------------------------


def test_credit_score_computation_status_has_exactly_3_values():
    assert {s.value for s in CreditScoreComputationStatus} == {
        "computed", "hard_fail_capped", "insufficient_data",
    }


def test_version_constants_are_non_empty_strings():
    assert isinstance(CREDIT_SCORE_SCHEMA_VERSION, str) and CREDIT_SCORE_SCHEMA_VERSION
    assert isinstance(CREDIT_SCORE_MODEL_VERSION, str) and CREDIT_SCORE_MODEL_VERSION


def test_binding_constants_match_design_doc_round_2():
    assert CREDIT_PROVISIONAL_CONFIDENCE_CEILING == Decimal("0.50")
    assert CREDIT_INSUFFICIENT_DATA_COVERAGE_THRESHOLD == Decimal("0.50")
    assert CREDIT_LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD == Decimal("0.70")
    assert CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER == Decimal("0.90")
    assert CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER == Decimal("0.65")
    assert CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR == Decimal("0.50")


def test_shared_helpers_are_reused_not_duplicated():
    # Bölüm 26 karar #3 / implementasyon kuralı #12: TIER_TO_POINTS,
    # clamp_score, normalize_weights, STRENGTHS_WEAKNESSES_COUNT
    # health_score_types'tan İTHAL EDİLİR -- burada ikinci bir kopyası
    # YOKTUR (import başarılı olması ve health_score_types'taki gerçek
    # değerlerle eşleşmesi bunu kanıtlar).
    assert TIER_TO_POINTS["excellent"] == Decimal("100")
    assert TIER_TO_POINTS["critical"] == Decimal("0")
    assert STRENGTHS_WEAKNESSES_COUNT == 5
    assert clamp_score(Decimal("150")) == Decimal("100")
    assert normalize_weights({"a": Decimal("1"), "b": Decimal("1")}) == {
        "a": Decimal("0.5"), "b": Decimal("0.5"),
    }


# --- Bölüm 19: CREDIT_SCORE_DATA_GAPS --------------------------------------


def test_credit_score_data_gaps_has_exactly_4_fixed_entries():
    assert len(CREDIT_SCORE_DATA_GAPS) == 4
    assert {g.gap_code for g in CREDIT_SCORE_DATA_GAPS} == {
        "FORWARD_CASH_FLOW", "COLLATERAL", "PAYMENT_HISTORY", "MANAGEMENT_QUALITY",
    }
    assert all(g.excluded_from_score is True for g in CREDIT_SCORE_DATA_GAPS)


def test_data_gap_disclosure_excluded_from_score_defaults_true():
    gap = DataGapDisclosure(gap_code="FORWARD_CASH_FLOW", description_tr="test")
    assert gap.excluded_from_score is True


# --- Dataclass'ların immutable (frozen) olduğu ------------------------------


def test_credit_category_weight_profile_is_frozen():
    profile = CreditCategoryWeightProfile(
        scope="global", scope_key=None, category_weights={"leverage": Decimal("0.25")}
    )
    try:
        profile.scope = "industry"
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_credit_ratio_score_weight_is_frozen_and_defaults():
    weight = CreditRatioScoreWeight(
        ratio_code="equity_ratio", category="leverage",
        ratio_weight=Decimal("0.333333"), role="critical",
    )
    assert weight.excluded_as_duplicate_of is None
    assert weight.duplicate_relationship is None
    try:
        weight.ratio_weight = Decimal("0.5")
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_credit_hard_fail_rule_is_frozen():
    rule = CreditHardFailRule(
        rule_code="NEGATIVE_EQUITY", predicate=lambda ratios, benchmarks: False,
        score_ceiling=Decimal("15"), rationale_tr="test",
    )
    try:
        rule.score_ceiling = Decimal("30")
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_credit_critical_override_rule_is_frozen():
    rule = CreditCriticalOverrideRule(
        ratio_code="current_ratio", category="liquidity",
        weak_multiplier=Decimal("0.90"), critical_multiplier=Decimal("0.65"),
        rationale_tr="test",
    )
    try:
        rule.category = "leverage"
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_banking_lens_signal_rule_is_frozen():
    rule = BankingLensSignalRule(
        flag_code="HIGH_LEVERAGE", category="leverage", rationale_tr="test",
        predicate=lambda signals: True, text_template_tr="{tier}",
        missing_input_note_tr="veri yok",
    )
    try:
        rule.flag_code = "OTHER"
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_credit_ratio_contribution_all_fields_settable():
    contribution = CreditRatioContribution(
        ratio_code="equity_ratio", benchmark_status="evaluated", tier="good",
        ratio_score=Decimal("75"), ratio_weight_applied=Decimal("0.333333"),
        role="critical", tier_fallback_used=False, reliability="medium",
        is_duplicate_excluded=False,
    )
    assert contribution.ratio_score == Decimal("75")
    assert contribution.role == "critical"


def test_credit_category_breakdown_holds_ratio_contributions_tuple():
    breakdown = CreditCategoryBreakdown(
        category="leverage", raw_score=Decimal("70"), score_after_override=Decimal("70"),
        weight_applied=Decimal("0.25"), coverage_ratio=Decimal("1.0"),
        redistributed_weights={"equity_ratio": Decimal("1.0")},
        critical_overrides_applied=(), ratio_contributions=(),
    )
    assert breakdown.ratio_contributions == ()


def test_health_score_reference_is_frozen_and_has_default_note():
    reference = HealthScoreReference(
        health_score_final_score=Decimal("70"), health_score_letter_rating="Sağlıklı",
        health_score_confidence=Decimal("0.60"), health_score_coverage=Decimal("1.0"),
        health_score_status="computed",
    )
    assert "Credit Score'un final_score hesaplamasına" in reference.note_tr
    try:
        reference.health_score_final_score = Decimal("80")
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass


def test_banking_lens_signals_defaults_are_safe():
    signals = BankingLensSignals(exposure_sensitivity="low", flags=())
    assert signals.not_a_credit_limit_recommendation is True
    assert "kredi limiti" in signals.disclaimer_tr


def test_banking_lens_signals_not_a_credit_limit_recommendation_cannot_be_overridden_to_false_silently():
    # Alan teknik olarak set edilebilir (frozen dataclass alanları init'te
    # verilir) ama HER ÜRETİM YOLU (servis katmanı) True vermelidir --
    # burada yalnızca varsayılanın True olduğu kanıtlanır (Bölüm 21 madde 8
    # servis-seviyesinde bunu daha kesin doğrular).
    signals = BankingLensSignals(exposure_sensitivity="high", flags=("HIGH_LEVERAGE",))
    assert signals.not_a_credit_limit_recommendation is True


def test_credit_score_result_is_frozen_and_holds_all_mandatory_fields():
    reference = HealthScoreReference(
        health_score_final_score=None, health_score_letter_rating=None,
        health_score_confidence=Decimal("0"), health_score_coverage=Decimal("0"),
        health_score_status="insufficient_data",
    )
    signals = BankingLensSignals(exposure_sensitivity="low", flags=())
    result = CreditScoreResult(
        status=CreditScoreComputationStatus.COMPUTED,
        final_score=Decimal("70.0"), pre_hard_fail_score=Decimal("70.0"),
        risk_tier="Sınırlı Risk", risk_tier_disclaimer_tr="resmi degildir",
        confidence_score=Decimal("0.50"), data_coverage_ratio=Decimal("0.90"),
        low_confidence_warning=False, provisional=True,
        category_breakdown=(), hard_fails_triggered=(), critical_overrides_applied=(),
        scoreable_ratio_codes=(), excluded_duplicate_ratio_codes=(),
        health_score_reference=reference, banking_lens_signals=signals,
        data_gap_disclosures=CREDIT_SCORE_DATA_GAPS,
        strengths=(), weaknesses=(), warnings=(),
        credit_score_schema_version=CREDIT_SCORE_SCHEMA_VERSION,
        credit_score_model_version=CREDIT_SCORE_MODEL_VERSION,
        health_score_schema_version="1.0.0", health_score_model_version="1.0.0",
        benchmark_registry_version="1.0.0", ratio_registry_version="1.1.0",
        category_weight_profile_used="global",
    )
    try:
        result.final_score = Decimal("80.0")
        assert False, "frozen dataclass mutasyonu reddetmeliydi"
    except FrozenInstanceError:
        pass
    assert len(result.data_gap_disclosures) == 4
