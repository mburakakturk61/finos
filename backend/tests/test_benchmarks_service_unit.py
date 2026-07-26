"""
Milestone 4.3C (Benchmark Engine) / Adım 7: `app/engines/benchmarks/
service.py::evaluate_benchmarks()` için uçtan uca testler -- gerçek
`analyze_financial_ratios()` çıktısı üzerinde çalıştırılır (yeniden
hesaplama YOK, yalnızca okuma).
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.financial_ratios.service import analyze_financial_ratios


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


def _real_ratio_result_json(*, with_prior_period: bool = False):
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

    return analyze_financial_ratios(
        balance_sheet_result=bs_result,
        income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs,
        prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )


# --- Temel uçtan uca davranış -------------------------------------------


def test_evaluate_benchmarks_returns_expected_top_level_shape():
    ratio_result = _real_ratio_result_json()
    result = evaluate_benchmarks(ratio_result)

    assert result["engine"] == "benchmarks"
    assert "benchmark_registry_version" in result
    assert result["ratio_registry_version"] == ratio_result["ratio_registry_version"]
    assert set(result["categories"]) == set(ratio_result["categories"])


def test_evaluate_benchmarks_covers_all_57_ratio_keys():
    ratio_result = _real_ratio_result_json()
    result = evaluate_benchmarks(ratio_result)

    total_ratio_keys = sum(
        len(cat["ratios"]) for cat in ratio_result["categories"].values()
    )
    total_benchmark_keys = sum(
        len(cat["ratios"]) for cat in result["categories"].values()
    )
    assert total_ratio_keys == 57
    assert total_benchmark_keys == 57


def test_calculated_ratios_get_evaluated_status_with_a_tier():
    ratio_result = _real_ratio_result_json()
    result = evaluate_benchmarks(ratio_result)

    checked_any = False
    for category, cat_data in ratio_result["categories"].items():
        for ratio_key, ratio_data in cat_data["ratios"].items():
            benchmark_entry = result["categories"][category]["ratios"][ratio_key]
            if ratio_data["status"] == "calculated":
                # Ya EVALUATED (benchmark kayitliysa) ya da
                # BENCHMARK_NOT_REGISTERED (benchmarklanmayan ratio_code --
                # ornegin net_working_capital, unit=currency).
                assert benchmark_entry["status"] in (
                    "evaluated", "benchmark_not_registered"
                )
                if benchmark_entry["status"] == "evaluated":
                    assert benchmark_entry["tier"] in (
                        "excellent", "good", "average", "weak", "critical"
                    )
                    checked_any = True
    assert checked_any, "en az bir gercekten EVALUATED oran bekleniyordu"


def test_net_working_capital_is_benchmark_not_registered():
    ratio_result = _real_ratio_result_json()
    result = evaluate_benchmarks(ratio_result)
    entry = result["categories"]["liquidity"]["ratios"]["net_working_capital"]
    assert entry["status"] == "benchmark_not_registered"
    assert entry["tier"] is None


def test_cash_flow_category_all_benchmark_not_registered():
    ratio_result = _real_ratio_result_json()
    result = evaluate_benchmarks(ratio_result)
    for ratio_key, entry in result["categories"]["cash_flow"]["ratios"].items():
        assert entry["status"] == "benchmark_not_registered", ratio_key
        assert entry["tier"] is None


def test_sustainable_growth_rate_and_fixed_charge_coverage_not_registered():
    ratio_result = _real_ratio_result_json()
    result = evaluate_benchmarks(ratio_result)
    growth_entry = result["categories"]["growth"]["ratios"]["sustainable_growth_rate"]
    leverage_entry = result["categories"]["leverage"]["ratios"]["fixed_charge_coverage"]
    assert growth_entry["status"] == "benchmark_not_registered"
    assert leverage_entry["status"] == "benchmark_not_registered"


def test_growth_ratios_missing_input_without_prior_period_passthrough():
    # Onceki donem verilmedi -> growth_rate stratejisi missing_input dondurur
    # -- benchmark da bunu SEFFAFCA tasir, tier FABRIKE ETMEZ.
    ratio_result = _real_ratio_result_json(with_prior_period=False)
    result = evaluate_benchmarks(ratio_result)
    entry = result["categories"]["growth"]["ratios"]["sales_growth"]
    assert entry["status"] == "ratio_status_not_calculated"
    assert entry["tier"] is None
    assert entry["underlying_ratio_status"] == "missing_input"


def test_growth_ratios_evaluated_with_prior_period_carry_inflation_adjusted_false():
    ratio_result = _real_ratio_result_json(with_prior_period=True)
    result = evaluate_benchmarks(ratio_result)
    entry = result["categories"]["growth"]["ratios"]["sales_growth"]
    assert entry["status"] == "evaluated"
    assert entry["inflation_adjusted"] is False
    assert entry["reliability"] == "medium_low"
    assert entry["tier"] in ("excellent", "good", "average", "weak", "critical")


def test_industry_and_company_size_params_pass_through_top_level():
    ratio_result = _real_ratio_result_json()
    result = evaluate_benchmarks(
        ratio_result, industry_code="tekstil", company_size_bucket="small"
    )
    assert result["industry_code"] == "tekstil"
    assert result["company_size_bucket"] == "small"
    # 4.3C'de gercek override verisi BOS oldugu icin (Bolum 11/12) sonuc
    # yine de "default" scope'a duser -- ama HATA VERMEZ (sozlesme testi).
    entry = result["categories"]["liquidity"]["ratios"]["current_ratio"]
    if entry["status"] == "evaluated":
        assert entry["resolved_scope"] == "default"


def test_no_country_parameter_exists_in_function_signature():
    import inspect

    params = inspect.signature(evaluate_benchmarks).parameters
    assert "country_code" not in params
    assert "country" not in params


def test_evaluate_benchmarks_does_not_mutate_input_ratio_result():
    ratio_result = _real_ratio_result_json()
    import copy

    snapshot = copy.deepcopy(ratio_result)
    evaluate_benchmarks(ratio_result)
    assert ratio_result == snapshot


def test_debt_ratio_realistic_value_evaluates_to_expected_tier():
    # total_liabilities=900000+400000=1300000, total_assets=3000000
    # -> debt_ratio = 1300000/3000000 = 0.4333 -> average bandinda (>=0.4,<0.6)
    ratio_result = _real_ratio_result_json()
    debt_ratio_data = ratio_result["categories"]["leverage"]["ratios"]["debt_ratio"]
    assert debt_ratio_data["status"] == "calculated"
    assert Decimal(str(debt_ratio_data["value"])) == Decimal("0.4333")

    result = evaluate_benchmarks(ratio_result)
    entry = result["categories"]["leverage"]["ratios"]["debt_ratio"]
    assert entry["status"] == "evaluated"
    assert entry["tier"] == "average"
