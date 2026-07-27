"""
Milestone 4.3E (Credit Score Engine) / Adım 6: `app/engines/credit_
score/service.py::apply_critical_override` (Aşama F -- oransal critical
override) için gerçek, çalıştırılabilir birim testleri.

Credit Score'un 5 critical override kuralı (Bölüm 9, Onaylanmış Karar
#6): current_ratio(liquidity), equity_ratio(leverage), interest_
coverage_ratio(debt_service_capacity), net_profit_margin(profitability),
cash_conversion_cycle(activity) -- `growth` kategorisinde HİÇBİR kural
YOKTUR.
"""

from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.credit_score.service import apply_critical_override


def test_none_raw_score_returns_none_and_no_triggers():
    score, triggered = apply_critical_override("liquidity", None, {})
    assert score is None
    assert triggered == ()


def test_no_override_eligible_ratio_at_bad_tier_leaves_score_unchanged():
    signals = {"current_ratio": {"tier": "good"}}
    score, triggered = apply_critical_override("liquidity", Decimal("80"), signals)
    assert score == Decimal("80")
    assert triggered == ()


def test_category_without_any_override_rule_is_always_unchanged():
    # `growth` kategorisinde HİÇBİR critical override kuralı YOK.
    signals = {"sales_growth": {"tier": "critical"}}
    score, triggered = apply_critical_override("growth", Decimal("70"), signals)
    assert score == Decimal("70")
    assert triggered == ()


def test_liquidity_current_ratio_critical_tier_applies_065_multiplier():
    signals = {"current_ratio": {"tier": "critical"}}
    score, triggered = apply_critical_override("liquidity", Decimal("80"), signals)
    assert score == Decimal("52.0")  # 80 * 0.65
    assert triggered == ("current_ratio:critical",)


def test_liquidity_current_ratio_weak_tier_applies_090_multiplier():
    signals = {"current_ratio": {"tier": "weak"}}
    score, triggered = apply_critical_override("liquidity", Decimal("80"), signals)
    assert score == Decimal("72.0")  # 80 * 0.90
    assert triggered == ("current_ratio:weak",)


def test_leverage_equity_ratio_critical_tier_triggers():
    signals = {"equity_ratio": {"tier": "critical"}}
    score, triggered = apply_critical_override("leverage", Decimal("80"), signals)
    assert score == Decimal("52.0")
    assert triggered == ("equity_ratio:critical",)


def test_debt_service_capacity_interest_coverage_ratio_critical_tier_triggers():
    signals = {"interest_coverage_ratio": {"tier": "critical"}}
    score, triggered = apply_critical_override("debt_service_capacity", Decimal("80"), signals)
    assert score == Decimal("52.0")
    assert triggered == ("interest_coverage_ratio:critical",)


def test_profitability_net_profit_margin_critical_tier_triggers():
    signals = {"net_profit_margin": {"tier": "critical"}}
    score, triggered = apply_critical_override("profitability", Decimal("80"), signals)
    assert score == Decimal("52.0")
    assert triggered == ("net_profit_margin:critical",)


def test_activity_cash_conversion_cycle_critical_tier_triggers():
    signals = {"cash_conversion_cycle": {"tier": "critical"}}
    score, triggered = apply_critical_override("activity", Decimal("80"), signals)
    assert score == Decimal("52.0")
    assert triggered == ("cash_conversion_cycle:critical",)


def test_result_is_always_clamped_to_0_100_range():
    signals = {"net_profit_margin": {"tier": "critical"}}
    score, triggered = apply_critical_override("profitability", Decimal("100"), signals)
    assert Decimal("0") <= score <= Decimal("100")


def test_missing_signal_for_override_ratio_code_does_not_trigger():
    score, triggered = apply_critical_override("activity", Decimal("50"), {})
    assert score == Decimal("50")
    assert triggered == ()


def test_debt_to_equity_never_appears_as_a_trigger_even_at_critical_tier():
    # Onaylanmış Karar #5/Bölüm 7.2: debt_to_equity HİÇBİR critical
    # override kuralında yer ALAMAZ -- registry'de böyle bir kural
    # yoktur, dolayısıyla bu sinyal her zaman görmezden gelinir.
    signals = {"debt_to_equity": {"tier": "critical"}}
    score, triggered = apply_critical_override("leverage", Decimal("80"), signals)
    assert score == Decimal("80")
    assert triggered == ()


def test_combined_multiplier_would_floor_at_050_if_two_rules_existed():
    # Registry'de aynı kategoride 2 kural YOK (v1), ama floor mantığının
    # kendisi (fonksiyon seviyesinde) tek bir kuralla dahi test edilebilir:
    # 0.65 tek başına floor'un (0.50) ÜZERİNDE kalır, floor'a
    # DOKUNULMADIĞINI doğrular.
    signals = {"equity_ratio": {"tier": "critical"}}
    score, triggered = apply_critical_override("leverage", Decimal("10"), signals)
    assert score == Decimal("6.5")  # 10 * 0.65 -- floor devreye girmedi
