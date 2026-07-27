"""
Milestone 4.3D (Financial Health Score) / Adım 3: `app/engines/health_
score/service.py::collect_ratio_signals` / `filter_scoreable_signals`
(Aşama A/B/C -- Ratio+Benchmark oku, duplicate/derived sinyalleri
filtrele) için gerçek, çalıştırılabilir birim testleri. Gerçek
`analyze_financial_ratios()` + `evaluate_benchmarks()` çıktısı üzerinde
çalıştırılır (yeniden hesaplama YOK, yalnızca okuma).
"""

from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import (
    ACTIVE_CATEGORIES,
    collect_ratio_signals,
    filter_scoreable_signals,
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


def _real_result_jsons(*, with_prior_period: bool = False):
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


# --- collect_ratio_signals -------------------------------------------------


def test_collect_ratio_signals_covers_every_ratio_in_ratio_result():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)

    total_ratio_keys = sum(
        len(cat["ratios"]) for cat in ratio_result["categories"].values()
    )
    assert len(signals) == total_ratio_keys


def test_collect_ratio_signals_calculated_and_evaluated_ratio_has_full_fields():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)

    signal = signals["debt_ratio"]
    assert signal["category"] == "leverage"
    assert signal["ratio_status"] == "calculated"
    assert signal["benchmark_status"] == "evaluated"
    assert signal["tier"] in ("excellent", "good", "average", "weak", "critical")
    assert signal["ratio_value"] is not None


def test_collect_ratio_signals_missing_prior_period_growth_is_not_calculated():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=False)
    signals = collect_ratio_signals(ratio_result, benchmark_result)

    signal = signals["sales_growth"]
    assert signal["ratio_status"] == "missing_input"
    assert signal["benchmark_status"] == "ratio_status_not_calculated"
    assert signal["tier"] is None


def test_collect_ratio_signals_cash_flow_category_is_benchmark_not_registered():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)

    for ratio_code, ratio_data in ratio_result["categories"]["cash_flow"]["ratios"].items():
        signal = signals[ratio_code]
        assert signal["benchmark_status"] == "benchmark_not_registered"
        assert signal["tier"] is None


def test_collect_ratio_signals_does_not_mutate_inputs():
    ratio_result, benchmark_result = _real_result_jsons()
    import copy

    ratio_snapshot = copy.deepcopy(ratio_result)
    benchmark_snapshot = copy.deepcopy(benchmark_result)
    collect_ratio_signals(ratio_result, benchmark_result)
    assert ratio_result == ratio_snapshot
    assert benchmark_result == benchmark_snapshot


# --- filter_scoreable_signals -----------------------------------------------


def test_filter_liquidity_excludes_working_capital_ratio_only():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "liquidity")

    assert "current_ratio" in scored
    assert "working_capital_ratio" not in scored
    assert "working_capital_ratio" in excluded
    assert len(scored) == 5
    assert len(excluded) == 1


def test_filter_leverage_excludes_debt_ratio_and_financial_leverage_multiplier():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "leverage")

    assert "equity_ratio" in scored
    assert "debt_ratio" in excluded
    assert "financial_leverage_multiplier" in excluded
    assert len(scored) == 7
    assert len(excluded) == 2


def test_filter_activity_scores_ccc_and_dpo_excludes_payables_turnover_and_days_variants():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "activity")

    assert "cash_conversion_cycle" in scored
    assert "days_payables_outstanding" in scored
    assert "payables_turnover" in excluded
    assert "days_inventory_outstanding" in excluded
    assert "days_sales_outstanding" in excluded
    assert len(scored) == 7
    assert len(excluded) == 3


def test_filter_profitability_efficiency_growth_have_zero_exclusions():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)

    for category, expected_scored in (
        ("profitability", 11), ("efficiency", 6), ("growth", 6),
    ):
        scored, excluded = filter_scoreable_signals(signals, category)
        assert len(excluded) == 0, category
        assert len(scored) == expected_scored, category


def test_filter_scoreable_signals_never_returns_non_benchmarked_ratios():
    # net_working_capital (unit=currency) hicbir kategoride scored/excluded
    # kumelerinde GORUNMEMELI -- BENCHMARK_REGISTRY'de zaten kayitli degil.
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    scored, excluded = filter_scoreable_signals(signals, "liquidity")
    assert "net_working_capital" not in scored
    assert "net_working_capital" not in excluded


def test_all_active_categories_are_covered_by_filter():
    ratio_result, benchmark_result = _real_result_jsons()
    signals = collect_ratio_signals(ratio_result, benchmark_result)
    for category in ACTIVE_CATEGORIES:
        scored, excluded = filter_scoreable_signals(signals, category)
        assert isinstance(scored, dict)
        assert isinstance(excluded, dict)
