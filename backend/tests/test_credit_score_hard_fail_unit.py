"""
Milestone 4.3E (Credit Score Engine) / Adım 7: `app/engines/credit_
score/service.py::apply_hard_fail_rules` (Aşama I) için gerçek,
çalıştırılabilir birim testleri.

Credit Score'un 2 hard-fail kuralı (Bölüm 10, Onaylanmış Karar #7):
NEGATIVE_EQUITY ceiling=15, SEVERE_DEBT_SERVICE_SHORTFALL ceiling=25 --
Health Score'un ceiling'lerinden (25/35) FARKLI, Credit'in KENDİ, daha
KATI (bankacılık lensli) model sabitleri.
"""

from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.credit_score.service import apply_hard_fail_rules


def test_none_preliminary_score_returns_none_and_no_triggers():
    score, triggered = apply_hard_fail_rules(None, {})
    assert score is None
    assert triggered == ()


def test_normal_signals_no_trigger_score_unchanged():
    signals = {
        "equity_ratio": {"ratio_value": Decimal("0.4"), "tier": "good", "benchmark_status": "evaluated"},
        "interest_coverage_ratio": {"ratio_value": Decimal("5"), "tier": "good", "benchmark_status": "evaluated"},
    }
    score, triggered = apply_hard_fail_rules(Decimal("75"), signals)
    assert score == Decimal("75")
    assert triggered == ()


def test_negative_equity_triggers_ceiling_15():
    signals = {"equity_ratio": {"ratio_value": Decimal("-0.15"), "tier": "critical", "benchmark_status": "evaluated"}}
    score, triggered = apply_hard_fail_rules(Decimal("70"), signals)
    assert score == Decimal("15")
    assert triggered == ("NEGATIVE_EQUITY",)


def test_severe_debt_service_shortfall_triggers_ceiling_25():
    signals = {"interest_coverage_ratio": {"ratio_value": Decimal("-3"), "tier": "critical", "benchmark_status": "evaluated"}}
    score, triggered = apply_hard_fail_rules(Decimal("60"), signals)
    assert score == Decimal("25")
    assert triggered == ("SEVERE_DEBT_SERVICE_SHORTFALL",)


def test_both_rules_trigger_simultaneously_lowest_ceiling_wins():
    signals = {
        "equity_ratio": {"ratio_value": Decimal("-0.2"), "tier": "critical", "benchmark_status": "evaluated"},
        "interest_coverage_ratio": {"ratio_value": Decimal("-1"), "tier": "critical", "benchmark_status": "evaluated"},
    }
    score, triggered = apply_hard_fail_rules(Decimal("90"), signals)
    assert score == Decimal("15")  # min(90, 15, 25) = 15
    assert set(triggered) == {"NEGATIVE_EQUITY", "SEVERE_DEBT_SERVICE_SHORTFALL"}


def test_preliminary_score_already_below_ceiling_stays_unchanged_but_still_reports_trigger():
    signals = {"equity_ratio": {"ratio_value": Decimal("-0.05"), "tier": "critical", "benchmark_status": "evaluated"}}
    score, triggered = apply_hard_fail_rules(Decimal("10"), signals)
    assert score == Decimal("10")  # min(10, 15) = 10
    assert triggered == ("NEGATIVE_EQUITY",)


def test_missing_ratio_value_does_not_trigger_hard_fail():
    # equity_ratio hic yok (eksik veri) -- hard fail YORUMLANMAZ.
    score, triggered = apply_hard_fail_rules(Decimal("50"), {})
    assert score == Decimal("50")
    assert triggered == ()


def test_missing_ratio_value_explicit_none_does_not_trigger():
    signals = {"equity_ratio": {"ratio_value": None, "tier": None, "benchmark_status": "ratio_status_not_calculated"}}
    score, triggered = apply_hard_fail_rules(Decimal("50"), signals)
    assert score == Decimal("50")
    assert triggered == ()


def test_result_is_clamped_to_0_100_range():
    signals = {"equity_ratio": {"ratio_value": Decimal("-0.5"), "tier": "critical", "benchmark_status": "evaluated"}}
    score, triggered = apply_hard_fail_rules(Decimal("100"), signals)
    assert Decimal("0") <= score <= Decimal("100")


def test_score_is_always_produced_never_a_binary_reject():
    # Hard-fail HER ZAMAN bir skor URETIR -- ikili kabul/red uretmez.
    signals = {"equity_ratio": {"ratio_value": Decimal("-999"), "tier": "critical", "benchmark_status": "evaluated"}}
    score, triggered = apply_hard_fail_rules(Decimal("99.9"), signals)
    assert score is not None
    assert score == Decimal("15")
