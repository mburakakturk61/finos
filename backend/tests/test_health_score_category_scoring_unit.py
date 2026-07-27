"""
Milestone 4.3D (Financial Health Score) / Adım 5: `app/engines/health_
score/service.py::build_category_breakdown` (Aşama E -- kategori ham
skoru) için gerçek, çalıştırılabilir birim testleri. Gerçek
`analyze_financial_ratios()` + `evaluate_benchmarks()` çıktısı üzerinde
çalıştırılır.
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import (
    build_category_breakdown,
    collect_ratio_signals,
    compute_ratio_score,
    filter_scoreable_signals,
    registry_ratio_weights_for_category,
)


def _bs_facts(**overrides):
    facts = {
        "current_assets": 1500000.0,
        "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0,
        "total_assets": 3000000.0,
        "equity": 1700000.0,
        "inventory": 300000.0,
        "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0,
        "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }
    facts.update(overrides)
    return facts


def _is_facts(**overrides):
    facts = {
        "net_sales": 5000000.0,
        "gross_profit": 2000000.0,
        "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0,
        "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0,
        "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0,
        "profit_before_tax": 750000.0,
        "net_profit": 600000.0,
        "ebit": 850000.0,
        "ebitda": 1000000.0,
    }
    facts.update(overrides)
    return facts


def _real_result_jsons(*, with_prior_period: bool = True):
    bs_result = {"source_mode": "direct_document", "facts": _bs_facts()}
    is_result = {"source_mode": "direct_document", "facts": _is_facts()}

    prior_bs = None
    prior_is = None
    if with_prior_period:
        prior_bs = {
            "source_mode": "direct_document",
            "facts": _bs_facts(total_assets=2500000.0, equity=1400000.0),
        }
        prior_is = {
            "source_mode": "direct_document",
            "facts": _is_facts(
                net_sales=4000000.0, gross_profit=1600000.0,
                ebitda=800000.0, net_profit=400000.0,
            ),
        }

    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result,
        income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs,
        prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    return ratio_result, benchmark_result


# --- Tam coverage senaryosu -------------------------------------------------


def test_full_coverage_category_raw_score_matches_manual_weighted_average():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "leverage")
    weights = registry_ratio_weights_for_category("leverage")

    breakdown = build_category_breakdown("leverage", scored, excluded, weights)

    manual_weighted_sum = Decimal("0")
    manual_weight_sum = Decimal("0")
    for ratio_code, signal in scored.items():
        points, _ = compute_ratio_score(ratio_code, signal)
        if signal.get("benchmark_status") == "evaluated" and points is not None:
            manual_weighted_sum += points * weights[ratio_code]
            manual_weight_sum += weights[ratio_code]
    expected = manual_weighted_sum / manual_weight_sum

    assert breakdown.raw_score == expected
    assert breakdown.category == "leverage"


def test_full_coverage_category_has_coverage_ratio_one():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "profitability")
    weights = registry_ratio_weights_for_category("profitability")

    breakdown = build_category_breakdown("profitability", scored, excluded, weights)
    assert breakdown.coverage_ratio == Decimal("1")


def test_excluded_duplicate_ratios_appear_in_contributions_with_zero_weight():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "liquidity")
    weights = registry_ratio_weights_for_category("liquidity")

    breakdown = build_category_breakdown("liquidity", scored, excluded, weights)
    wc_contribution = next(
        c for c in breakdown.ratio_contributions if c.ratio_code == "working_capital_ratio"
    )
    assert wc_contribution.is_duplicate_excluded is True
    assert wc_contribution.ratio_score is None
    assert wc_contribution.ratio_weight_applied == Decimal("0")


def test_scored_ratio_contribution_has_nonzero_weight_and_score():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "liquidity")
    weights = registry_ratio_weights_for_category("liquidity")

    breakdown = build_category_breakdown("liquidity", scored, excluded, weights)
    cr_contribution = next(
        c for c in breakdown.ratio_contributions if c.ratio_code == "current_ratio"
    )
    assert cr_contribution.is_duplicate_excluded is False
    assert cr_contribution.ratio_score is not None
    assert cr_contribution.ratio_weight_applied > 0


def test_raw_score_is_clamped_between_0_and_100():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    for category in ("liquidity", "leverage", "profitability", "activity", "efficiency", "growth"):
        scored, excluded = filter_scoreable_signals(signals, category)
        weights = registry_ratio_weights_for_category(category)
        breakdown = build_category_breakdown(category, scored, excluded, weights)
        if breakdown.raw_score is not None:
            assert Decimal("0") <= breakdown.raw_score <= Decimal("100"), category


def test_redistributed_weights_field_matches_input_weights_dict():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "efficiency")
    weights = registry_ratio_weights_for_category("efficiency")

    breakdown = build_category_breakdown("efficiency", scored, excluded, weights)
    assert breakdown.redistributed_weights == weights


# --- Sıfır EVALUATED senaryosu (raw_score=None, asla fabrike edilmez) ------


def test_zero_evaluated_category_raw_score_is_none_not_fabricated():
    scored = {
        "current_ratio": {
            "category": "liquidity", "ratio_value": None, "ratio_status": "missing_input",
            "ratio_reliability": "not_calculable", "benchmark_status": "ratio_status_not_calculated",
            "tier": None, "benchmark_reliability": "not_calculable",
        },
    }
    excluded = {}
    weights = {"current_ratio": Decimal("1")}
    breakdown = build_category_breakdown("liquidity", scored, excluded, weights)
    assert breakdown.raw_score is None
    assert breakdown.coverage_ratio == Decimal("0")


def test_registry_ratio_weights_for_category_sums_to_one():
    for category in ("liquidity", "leverage", "profitability", "activity", "efficiency", "growth"):
        weights = registry_ratio_weights_for_category(category)
        assert sum(weights.values()) == Decimal("1"), category
