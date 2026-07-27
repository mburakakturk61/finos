"""
Milestone 4.3E (Credit Score Engine) / Adım 10: `app/engines/credit_
score/service.py::build_banking_lens_signals` / `build_data_gap_
disclosures` (Bölüm 13/13.1/19) için gerçek, çalıştırılabilir birim
testleri.
"""

from app.engines.credit_score.service import (
    build_banking_lens_signals,
    build_data_gap_disclosures,
)


def _signal(tier=None, benchmark_status="evaluated", ratio_value=None):
    return {"tier": tier, "benchmark_status": benchmark_status, "ratio_value": ratio_value}


# --- BankingLensSignals: her bayrak icin ayri testler -----------------------


def test_no_signals_produces_zero_flags_and_low_exposure():
    banking_lens, missing = build_banking_lens_signals({})
    assert banking_lens.flags == ()
    assert banking_lens.exposure_sensitivity == "low"
    # 6 kuralin HEPSI icin veri eksik -- 6 missing-input notu uretilmeli.
    assert len(missing) == 6


def test_short_term_liquidity_strain_flag_triggers_on_weak_tier():
    signals = {"current_ratio": _signal(tier="weak")}
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "SHORT_TERM_LIQUIDITY_STRAIN" in banking_lens.flags


def test_short_term_liquidity_strain_flag_does_not_trigger_on_good_tier():
    signals = {"current_ratio": _signal(tier="good")}
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "SHORT_TERM_LIQUIDITY_STRAIN" not in banking_lens.flags


def test_high_leverage_flag_triggers_on_critical_tier():
    signals = {"equity_ratio": _signal(tier="critical")}
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "HIGH_LEVERAGE" in banking_lens.flags


def test_debt_service_stress_flag_triggers_on_negative_value_even_if_tier_good():
    signals = {"interest_coverage_ratio": _signal(tier="good", ratio_value=-1)}
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "DEBT_SERVICE_STRESS" in banking_lens.flags


def test_weak_profit_buffer_flag_triggers_on_weak_tier():
    signals = {"net_profit_margin": _signal(tier="weak")}
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "WEAK_PROFIT_BUFFER" in banking_lens.flags


def test_working_capital_strain_flag_triggers_on_critical_tier():
    signals = {"cash_conversion_cycle": _signal(tier="critical")}
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "WORKING_CAPITAL_STRAIN" in banking_lens.flags


def test_debt_funded_growth_flag_triggers_when_assets_grow_faster_than_equity():
    signals = {
        "total_assets_growth": _signal(ratio_value=0.30),
        "equity_growth": _signal(ratio_value=0.05),
    }
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "DEBT_FUNDED_GROWTH" in banking_lens.flags


def test_debt_funded_growth_flag_does_not_trigger_when_equity_grows_faster():
    signals = {
        "total_assets_growth": _signal(ratio_value=0.05),
        "equity_growth": _signal(ratio_value=0.30),
    }
    banking_lens, _ = build_banking_lens_signals(signals)
    assert "DEBT_FUNDED_GROWTH" not in banking_lens.flags


# --- Eksik/güvenilmez veride bayrak URETILMEZ, yalnizca warning -------------


def test_missing_input_produces_no_flag_but_a_data_gap_warning():
    banking_lens, missing = build_banking_lens_signals({"current_ratio": _signal(benchmark_status="ratio_status_not_calculated")})
    assert "SHORT_TERM_LIQUIDITY_STRAIN" not in banking_lens.flags
    codes = {w["code"] for w in missing}
    assert "BANKING_LENS_SHORT_TERM_LIQUIDITY_STRAIN_DATA_GAP" in codes


def test_flags_never_number_more_than_six():
    signals = {
        "current_ratio": _signal(tier="critical"),
        "equity_ratio": _signal(tier="critical"),
        "interest_coverage_ratio": _signal(tier="critical"),
        "net_profit_margin": _signal(tier="critical"),
        "cash_conversion_cycle": _signal(tier="critical"),
        "total_assets_growth": _signal(ratio_value=0.5),
        "equity_growth": _signal(ratio_value=0.1),
    }
    banking_lens, missing = build_banking_lens_signals(signals)
    assert len(banking_lens.flags) == 6
    assert missing == ()


# --- exposure_sensitivity esik davranisi ------------------------------------


def test_exposure_sensitivity_medium_for_one_to_two_flags():
    signals = {"current_ratio": _signal(tier="weak"), "equity_ratio": _signal(tier="weak")}
    banking_lens, _ = build_banking_lens_signals(signals)
    assert len(banking_lens.flags) == 2
    assert banking_lens.exposure_sensitivity == "medium"


def test_exposure_sensitivity_high_for_three_or_more_flags():
    signals = {
        "current_ratio": _signal(tier="critical"),
        "equity_ratio": _signal(tier="critical"),
        "interest_coverage_ratio": _signal(tier="critical"),
    }
    banking_lens, _ = build_banking_lens_signals(signals)
    assert len(banking_lens.flags) == 3
    assert banking_lens.exposure_sensitivity == "high"


# --- Kredi limiti onerisi YAPMAZ garantisi -----------------------------------


def test_banking_lens_signals_never_recommends_a_credit_limit():
    banking_lens, _ = build_banking_lens_signals({})
    assert banking_lens.not_a_credit_limit_recommendation is True
    assert "kredi limiti" in banking_lens.disclaimer_tr


# --- DataGapDisclosure --------------------------------------------------


def test_data_gap_disclosures_are_exactly_four_fixed_entries():
    disclosures = build_data_gap_disclosures()
    assert len(disclosures) == 4
    codes = {d.gap_code for d in disclosures}
    assert codes == {"FORWARD_CASH_FLOW", "COLLATERAL", "PAYMENT_HISTORY", "MANAGEMENT_QUALITY"}


def test_all_data_gap_disclosures_are_excluded_from_score():
    disclosures = build_data_gap_disclosures()
    assert all(d.excluded_from_score is True for d in disclosures)


def test_data_gap_disclosures_are_input_independent():
    # Bu fonksiyon HICBIR girdi almaz -- her cagride AYNI 4 sabit kayit doner.
    first = build_data_gap_disclosures()
    second = build_data_gap_disclosures()
    assert first == second
