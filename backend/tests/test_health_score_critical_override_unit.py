"""
Milestone 4.3D (Financial Health Score) / Adım 7: `app/engines/health_
score/service.py::apply_critical_override` (Aşama F -- oransal critical
override) için gerçek, çalıştırılabilir birim testleri.
"""

from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.health_score.service import apply_critical_override


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
    signals = {"operating_expense_ratio": {"tier": "critical"}}
    score, triggered = apply_critical_override("efficiency", Decimal("70"), signals)
    assert score == Decimal("70")
    assert triggered == ()


def test_single_critical_tier_trigger_applies_070_multiplier():
    signals = {"current_ratio": {"tier": "critical"}}
    score, triggered = apply_critical_override("liquidity", Decimal("80"), signals)
    assert score == Decimal("56.0")  # 80 * 0.70
    assert triggered == ("current_ratio:critical",)


def test_single_weak_tier_trigger_applies_090_multiplier():
    signals = {"current_ratio": {"tier": "weak"}}
    score, triggered = apply_critical_override("liquidity", Decimal("80"), signals)
    assert score == Decimal("72.0")  # 80 * 0.90
    assert triggered == ("current_ratio:weak",)


def test_two_simultaneous_critical_triggers_in_leverage_are_floored_at_050():
    signals = {
        "debt_to_equity": {"tier": "critical"},
        "interest_coverage_ratio": {"tier": "critical"},
    }
    score, triggered = apply_critical_override("leverage", Decimal("80"), signals)
    # 0.70 * 0.70 = 0.49 -> floor 0.50 devreye girer
    assert score == Decimal("40.0")  # 80 * 0.50
    assert set(triggered) == {"debt_to_equity:critical", "interest_coverage_ratio:critical"}


def test_two_simultaneous_weak_triggers_not_floored_since_above_050():
    signals = {
        "debt_to_equity": {"tier": "weak"},
        "interest_coverage_ratio": {"tier": "weak"},
    }
    score, triggered = apply_critical_override("leverage", Decimal("80"), signals)
    # 0.90 * 0.90 = 0.81 -- floor'un UZERINDE, dogrudan kullanilir
    assert score == Decimal("64.8")  # 80 * 0.81


def test_result_is_always_clamped_to_0_100_range():
    signals = {"net_profit_margin": {"tier": "critical"}}
    score, triggered = apply_critical_override("profitability", Decimal("100"), signals)
    assert Decimal("0") <= score <= Decimal("100")


def test_missing_signal_for_override_ratio_code_does_not_trigger():
    score, triggered = apply_critical_override("activity", Decimal("50"), {})
    assert score == Decimal("50")
    assert triggered == ()
