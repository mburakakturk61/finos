"""
Milestone 4.3E (Credit Score Engine) / Adım 5: `app/engines/credit_
score/service.py`'nin coverage normalization fonksiyonları
(`redistribute_category_weights` / `compute_overall_data_coverage_ratio`
[Health Score'dan yeniden kullanılır] / `determine_insufficient_data_
and_warning` / `resolve_cross_category_weights`) için gerçek,
çalıştırılabilir birim testleri.
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.credit_score_types import CreditCategoryBreakdown, CreditCategoryWeightProfile
from app.engines.credit_score.service import (
    ACTIVE_CATEGORIES,
    compute_overall_data_coverage_ratio,
    determine_insufficient_data_and_warning,
    filter_scoreable_signals,
    redistribute_category_weights,
    registry_ratio_weights_for_category,
    resolve_cross_category_weights,
)
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import collect_ratio_signals


def _bs_facts(**overrides):
    facts = {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }
    facts.update(overrides)
    return facts


def _is_facts(**overrides):
    facts = {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }
    facts.update(overrides)
    return facts


def _real_result_jsons(*, with_prior_period: bool):
    bs_result = {"source_mode": "direct_document", "facts": _bs_facts()}
    is_result = {"source_mode": "direct_document", "facts": _is_facts()}
    prior_bs = prior_is = None
    if with_prior_period:
        prior_bs = {
            "source_mode": "direct_document",
            "facts": _bs_facts(total_assets=2500000.0, equity=1400000.0),
        }
        prior_is = {
            "source_mode": "direct_document",
            "facts": _is_facts(net_sales=4000000.0, gross_profit=1600000.0, ebitda=800000.0, net_profit=400000.0),
        }
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    return ratio_result, evaluate_benchmarks(ratio_result)


# --- redistribute_category_weights -----------------------------------------


def test_redistribute_full_coverage_equals_registry_weights():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, _ = filter_scoreable_signals(signals, "profitability")

    redistributed = redistribute_category_weights("profitability", scored)
    registry = registry_ratio_weights_for_category("profitability")
    assert redistributed == registry


def test_redistribute_partial_coverage_sums_to_one_and_zeroes_missing():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=False)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, _ = filter_scoreable_signals(signals, "growth")

    redistributed = redistribute_category_weights("growth", scored)
    # with_prior_period=False -> growth kategorisindeki TÜM oranlar
    # ratio_status_not_calculated (hicbiri evaluated degil).
    assert all(w == Decimal("0") for w in redistributed.values())


def test_redistribute_partial_coverage_liquidity_like_scenario():
    scored = {
        "current_ratio": {"benchmark_status": "evaluated"},
        "quick_ratio": {"benchmark_status": "evaluated"},
        "cash_ratio": {"benchmark_status": "ratio_status_not_calculated"},
        "defensive_interval_ratio": {"benchmark_status": "evaluated"},
        "working_capital_to_total_assets": {"benchmark_status": "ratio_status_not_calculated"},
    }
    redistributed = redistribute_category_weights("liquidity", scored)
    assert redistributed["cash_ratio"] == Decimal("0")
    assert redistributed["working_capital_to_total_assets"] == Decimal("0")
    assert redistributed["current_ratio"] > 0
    assert sum(redistributed.values()) == Decimal("1")


# --- compute_overall_data_coverage_ratio (Health Score'dan yeniden kullanılır) --


def test_overall_coverage_is_one_when_all_prior_period_data_present():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    all_scored = {
        category: filter_scoreable_signals(signals, category)[0] for category in ACTIVE_CATEGORIES
    }
    assert compute_overall_data_coverage_ratio(all_scored) == Decimal("1")


def test_overall_coverage_drops_below_one_without_prior_period():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=False)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    all_scored = {
        category: filter_scoreable_signals(signals, category)[0] for category in ACTIVE_CATEGORIES
    }
    coverage = compute_overall_data_coverage_ratio(all_scored)
    assert Decimal("0") < coverage < Decimal("1")


def test_overall_coverage_zero_scoreable_returns_zero_not_exception():
    assert compute_overall_data_coverage_ratio({}) == Decimal("0")


# --- determine_insufficient_data_and_warning (Credit'in KENDİ sabitleri) ----


def test_coverage_below_50_percent_is_insufficient_data():
    is_insufficient, warning = determine_insufficient_data_and_warning(Decimal("0.4999"))
    assert is_insufficient is True
    assert warning is False


def test_coverage_exactly_50_percent_is_not_insufficient_but_warns():
    is_insufficient, warning = determine_insufficient_data_and_warning(Decimal("0.50"))
    assert is_insufficient is False
    assert warning is True


def test_coverage_just_below_70_percent_still_warns():
    is_insufficient, warning = determine_insufficient_data_and_warning(Decimal("0.6999"))
    assert is_insufficient is False
    assert warning is True


def test_coverage_exactly_70_percent_is_normal_no_warning():
    is_insufficient, warning = determine_insufficient_data_and_warning(Decimal("0.70"))
    assert is_insufficient is False
    assert warning is False


def test_coverage_full_is_normal_no_warning():
    is_insufficient, warning = determine_insufficient_data_and_warning(Decimal("1.0"))
    assert is_insufficient is False
    assert warning is False


# --- resolve_cross_category_weights -----------------------------------------


def _make_breakdown(category, raw_score):
    return CreditCategoryBreakdown(
        category=category, raw_score=raw_score, score_after_override=None,
        weight_applied=Decimal("0"), coverage_ratio=Decimal("1"),
        redistributed_weights={}, critical_overrides_applied=(), ratio_contributions=(),
    )


def test_resolve_cross_category_weights_all_present_matches_global_profile():
    profile = CreditCategoryWeightProfile(
        scope="global", scope_key=None,
        category_weights={
            "liquidity": Decimal("0.20"), "leverage": Decimal("0.25"),
            "debt_service_capacity": Decimal("0.25"), "profitability": Decimal("0.15"),
            "activity": Decimal("0.10"), "growth": Decimal("0.05"),
        },
    )
    breakdowns = {cat: _make_breakdown(cat, Decimal("60")) for cat in profile.category_weights}
    resolved = resolve_cross_category_weights(breakdowns, profile)
    assert resolved == profile.category_weights


def test_resolve_cross_category_weights_excludes_missing_category_and_renormalizes():
    profile = CreditCategoryWeightProfile(
        scope="global", scope_key=None,
        category_weights={
            "liquidity": Decimal("0.20"), "leverage": Decimal("0.25"),
            "debt_service_capacity": Decimal("0.25"), "profitability": Decimal("0.15"),
            "activity": Decimal("0.10"), "growth": Decimal("0.05"),
        },
    )
    breakdowns = {cat: _make_breakdown(cat, Decimal("60")) for cat in profile.category_weights}
    breakdowns["growth"] = _make_breakdown("growth", None)  # tamamen eksik kategori

    resolved = resolve_cross_category_weights(breakdowns, profile)
    assert resolved["growth"] == Decimal("0")
    assert sum(resolved.values()) == Decimal("1")
    assert resolved["leverage"] > profile.category_weights["leverage"]
