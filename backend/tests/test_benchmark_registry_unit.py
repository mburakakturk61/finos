"""
Milestone 4.3C (Benchmark Engine) -- `app/engines/common/
benchmark_registry.py`'nin gerçek `BENCHMARK_REGISTRY` girdileri için
birim testleri. Adım 3'ten (Likidite+Borçluluk) başlayarak, sonraki
adımlarda (4-6) yeni assertion'lar EKLENECEK -- bu, `tests/
test_ratio_formulas_unit.py`'nin 4.3B'deki büyüme desenidir.
"""

from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- kayıtları tetikler
from app.engines.common.benchmark_types import (
    BENCHMARK_REGISTRY,
    BenchmarkComputationStatus,
    evaluate_benchmark,
    list_benchmarks_by_category,
    list_benchmarks_for_ratio,
)


# --- Adım 3: Likidite (6) + Borçluluk (9) = 15 --------------------------


def test_step3_liquidity_has_exactly_6_entries():
    entries = list_benchmarks_by_category("liquidity")
    codes = {m.benchmark_code for m in entries if not m.benchmark_code.startswith("_test")}
    assert codes == {
        "current_ratio",
        "working_capital_ratio",
        "quick_ratio",
        "cash_ratio",
        "defensive_interval_ratio",
        "working_capital_to_total_assets",
    }


def test_step3_leverage_has_exactly_9_entries():
    entries = list_benchmarks_by_category("leverage")
    codes = {m.benchmark_code for m in entries if not m.benchmark_code.startswith("_test")}
    assert codes == {
        "debt_ratio",
        "equity_ratio",
        "debt_to_equity",
        "long_term_debt_to_equity",
        "short_term_debt_ratio",
        "financial_leverage_multiplier",
        "interest_coverage_ratio",
        "ebitda_coverage_ratio",
        "debt_to_ebitda",
    }


def test_fixed_charge_coverage_has_no_benchmark():
    # HER ZAMAN not_calculable dondugu icin benchmarklanacak hicbir
    # deger yok (tasarim dokumani Bolum 8 giris notu).
    assert list_benchmarks_for_ratio("fixed_charge_coverage") == []


def test_net_working_capital_has_no_benchmark_currency_unit():
    # unit=currency -- olceklendirilmemis, kiyaslanamaz.
    assert list_benchmarks_for_ratio("net_working_capital") == []


def test_current_ratio_and_working_capital_ratio_share_same_thresholds_object():
    current = BENCHMARK_REGISTRY["current_ratio"]
    working_capital = BENCHMARK_REGISTRY["working_capital_ratio"]
    assert current.default_thresholds is working_capital.default_thresholds


def test_current_ratio_evaluation_excellent():
    result = evaluate_benchmark("current_ratio", "calculated", Decimal("1.6"), "high")
    assert result.status == BenchmarkComputationStatus.EVALUATED
    assert result.tier == "excellent"
    assert result.reliability == "medium"  # provisional ceiling


def test_current_ratio_evaluation_critical_both_sides():
    too_low = evaluate_benchmark("current_ratio", "calculated", Decimal("0.5"), "high")
    too_high = evaluate_benchmark("current_ratio", "calculated", Decimal("4.0"), "high")
    assert too_low.tier == "critical"
    assert too_high.tier == "critical"  # RANGE_IS_BETTER -- asiri yuksek de kotu


def test_debt_ratio_evaluation_good():
    result = evaluate_benchmark("debt_ratio", "calculated", Decimal("0.35"), "high")
    assert result.tier == "good"


def test_debt_ratio_evaluation_critical():
    result = evaluate_benchmark("debt_ratio", "calculated", Decimal("0.8"), "high")
    assert result.tier == "critical"


def test_interest_coverage_no_obligation_passthrough_not_fabricated():
    # NO_OBLIGATION -- finansman gideri=0, olumlu bir is durumu olsa da
    # value=None oldugu icin sayisal bir tier FABRIKE EDILMEZ.
    result = evaluate_benchmark(
        "interest_coverage_ratio", "no_obligation", None, "not_calculable"
    )
    assert result.status == BenchmarkComputationStatus.RATIO_STATUS_NOT_CALCULATED
    assert result.tier is None
    assert result.underlying_ratio_status == "no_obligation"


def test_all_step3_entries_carry_provisional_heuristic_triple():
    for code in (
        "current_ratio", "working_capital_ratio", "quick_ratio", "cash_ratio",
        "defensive_interval_ratio", "working_capital_to_total_assets",
        "debt_ratio", "equity_ratio", "debt_to_equity", "long_term_debt_to_equity",
        "short_term_debt_ratio", "financial_leverage_multiplier",
        "interest_coverage_ratio", "ebitda_coverage_ratio", "debt_to_ebitda",
    ):
        metadata = BENCHMARK_REGISTRY[code]
        assert metadata.source == "internal_heuristic"
        assert metadata.provisional is True
        assert metadata.reliability_ceiling == "medium"


def test_all_step3_units_match_ratio_registry():
    from app.engines.common.ratio_formulas import get_ratio_formula

    for code, metadata in BENCHMARK_REGISTRY.items():
        if code.startswith("_test"):
            continue
        ratio_metadata = get_ratio_formula(metadata.ratio_code)
        assert ratio_metadata is not None
        assert metadata.unit == ratio_metadata.unit, code


# --- Adım 4: Kârlılık (11) ------------------------------------------------


def test_step4_profitability_has_exactly_11_entries():
    entries = list_benchmarks_by_category("profitability")
    codes = {m.benchmark_code for m in entries if not m.benchmark_code.startswith("_test")}
    assert codes == {
        "gross_profit_margin", "operating_profit_margin", "net_profit_margin",
        "ebit_margin", "ebitda_margin", "pretax_profit_margin",
        "return_on_capital_employed", "effective_tax_rate",
        "return_on_invested_capital", "return_on_assets", "return_on_equity",
    }


def test_effective_tax_rate_benchmark_uses_centralized_statutory_thresholds():
    from app.engines.common.benchmark_types import effective_tax_rate_thresholds

    metadata = BENCHMARK_REGISTRY["effective_tax_rate"]
    assert metadata.default_thresholds == effective_tax_rate_thresholds()
    assert metadata.ideal_direction.value == "range_is_better"


def test_effective_tax_rate_evaluation_near_statutory_rate_is_excellent():
    result = evaluate_benchmark("effective_tax_rate", "calculated", Decimal("0.24"), "high")
    assert result.tier == "excellent"


def test_effective_tax_rate_evaluation_far_from_statutory_rate_is_critical():
    result = evaluate_benchmark("effective_tax_rate", "calculated", Decimal("0.90"), "high")
    assert result.tier == "critical"


def test_net_profit_margin_evaluation_tiers():
    critical = evaluate_benchmark("net_profit_margin", "calculated", Decimal("-5"), "high")
    excellent = evaluate_benchmark("net_profit_margin", "calculated", Decimal("18"), "high")
    assert critical.tier == "critical"
    assert excellent.tier == "excellent"


def test_step4_profitability_missing_input_not_fabricated():
    result = evaluate_benchmark("return_on_equity", "missing_input", None, "not_calculable")
    assert result.status == BenchmarkComputationStatus.RATIO_STATUS_NOT_CALCULATED
    assert result.tier is None


def test_all_step4_entries_carry_provisional_heuristic_triple():
    for code in (
        "gross_profit_margin", "operating_profit_margin", "net_profit_margin",
        "ebit_margin", "ebitda_margin", "pretax_profit_margin",
        "return_on_capital_employed", "effective_tax_rate",
        "return_on_invested_capital", "return_on_assets", "return_on_equity",
    ):
        metadata = BENCHMARK_REGISTRY[code]
        assert metadata.source == "internal_heuristic"
        assert metadata.provisional is True
        assert metadata.reliability_ceiling == "medium"


# --- Adım 5: Faaliyet (10) -- payables RANGE_IS_BETTER ---------------------


def test_step5_activity_has_exactly_10_entries():
    entries = list_benchmarks_by_category("activity")
    codes = {m.benchmark_code for m in entries if not m.benchmark_code.startswith("_test")}
    assert codes == {
        "asset_turnover", "inventory_turnover", "receivables_turnover",
        "payables_turnover", "fixed_asset_turnover", "working_capital_turnover",
        "days_inventory_outstanding", "days_sales_outstanding",
        "days_payables_outstanding", "cash_conversion_cycle",
    }


def test_payables_turnover_is_range_is_better():
    metadata = BENCHMARK_REGISTRY["payables_turnover"]
    assert metadata.ideal_direction.value == "range_is_better"


def test_days_payables_outstanding_is_range_is_better():
    metadata = BENCHMARK_REGISTRY["days_payables_outstanding"]
    assert metadata.ideal_direction.value == "range_is_better"


def test_payables_turnover_too_fast_is_risky():
    # ASIRI HIZLI odeme (tedarikci finansmanindan yararlanilmiyor) --
    # weak bandinin bile disinda -> critical.
    result = evaluate_benchmark("payables_turnover", "calculated", Decimal("1"), "high")
    assert result.tier == "critical"


def test_payables_turnover_too_slow_is_risky():
    # ASIRI YAVAS odeme (odeme gucluk sinyali) -- ayni sekilde critical.
    result = evaluate_benchmark("payables_turnover", "calculated", Decimal("20"), "high")
    assert result.tier == "critical"


def test_payables_turnover_sweet_spot_is_excellent():
    result = evaluate_benchmark("payables_turnover", "calculated", Decimal("6"), "high")
    assert result.tier == "excellent"


def test_payables_turnover_warning_flag_both_sides():
    below = evaluate_benchmark("payables_turnover", "calculated", Decimal("3.5"), "high")
    above = evaluate_benchmark("payables_turnover", "calculated", Decimal("9.5"), "high")
    within = evaluate_benchmark("payables_turnover", "calculated", Decimal("6"), "high")
    assert below.warning_flag is True
    assert above.warning_flag is True
    assert within.warning_flag is False


def test_days_payables_outstanding_too_fast_and_too_slow_both_risky():
    too_fast = evaluate_benchmark(
        "days_payables_outstanding", "calculated", Decimal("2"), "high"
    )
    too_slow = evaluate_benchmark(
        "days_payables_outstanding", "calculated", Decimal("200"), "high"
    )
    sweet_spot = evaluate_benchmark(
        "days_payables_outstanding", "calculated", Decimal("60"), "high"
    )
    assert too_fast.tier == "critical"
    assert too_slow.tier == "critical"
    assert sweet_spot.tier == "excellent"


def test_cash_conversion_cycle_negative_is_excellent():
    # Negatif nakit donusum suresi (bazi perakende/FMCG sirketlerinde
    # gorulur) -- lower_is_better icin en iyi durum.
    result = evaluate_benchmark("cash_conversion_cycle", "calculated", Decimal("-10"), "high")
    assert result.tier == "excellent"


def test_all_step5_entries_carry_provisional_heuristic_triple():
    for code in (
        "asset_turnover", "inventory_turnover", "receivables_turnover",
        "payables_turnover", "fixed_asset_turnover", "working_capital_turnover",
        "days_inventory_outstanding", "days_sales_outstanding",
        "days_payables_outstanding", "cash_conversion_cycle",
    ):
        metadata = BENCHMARK_REGISTRY[code]
        assert metadata.source == "internal_heuristic"
        assert metadata.provisional is True
        assert metadata.reliability_ceiling == "medium"


# --- Adım 6: Verimlilik (6) + Büyüme (6, nominal) ------------------------


def test_step6_efficiency_has_exactly_6_entries():
    entries = list_benchmarks_by_category("efficiency")
    codes = {m.benchmark_code for m in entries if not m.benchmark_code.startswith("_test")}
    assert codes == {
        "operating_expense_ratio", "cost_of_sales_ratio", "overhead_ratio",
        "ebit_to_opex", "non_operating_income_dependency",
        "financing_expense_to_sales",
    }


def test_step6_growth_has_exactly_6_entries():
    entries = list_benchmarks_by_category("growth")
    codes = {m.benchmark_code for m in entries if not m.benchmark_code.startswith("_test")}
    assert codes == {
        "sales_growth", "gross_profit_growth", "ebitda_growth",
        "net_profit_growth", "total_assets_growth", "equity_growth",
    }


def test_sustainable_growth_rate_has_no_benchmark():
    # HER ZAMAN not_calculable donduğu icin benchmarklanacak hicbir
    # deger yok (tasarim dokumani Bolum 8 giris notu, 2. tur onay karar #8
    # ile ayni ilke).
    assert list_benchmarks_for_ratio("sustainable_growth_rate") == []


def test_all_growth_entries_carry_inflation_adjusted_false_and_medium_low_ceiling():
    for code in (
        "sales_growth", "gross_profit_growth", "ebitda_growth",
        "net_profit_growth", "total_assets_growth", "equity_growth",
    ):
        metadata = BENCHMARK_REGISTRY[code]
        assert metadata.inflation_adjusted is False
        assert metadata.reliability_ceiling == "medium_low"
        assert metadata.category == "growth"


def test_growth_evaluation_reliability_capped_at_medium_low_even_with_high_ratio_reliability():
    result = evaluate_benchmark("sales_growth", "calculated", Decimal("25"), "high")
    assert result.status == BenchmarkComputationStatus.EVALUATED
    assert result.reliability == "medium_low"
    assert result.inflation_adjusted is False


def test_net_profit_growth_evaluation_tiers():
    critical = evaluate_benchmark("net_profit_growth", "calculated", Decimal("-20"), "high")
    excellent = evaluate_benchmark("net_profit_growth", "calculated", Decimal("60"), "high")
    assert critical.tier == "critical"
    assert excellent.tier == "excellent"


def test_efficiency_entries_are_lower_is_better_except_ebit_to_opex():
    for code in (
        "operating_expense_ratio", "cost_of_sales_ratio", "overhead_ratio",
        "non_operating_income_dependency", "financing_expense_to_sales",
    ):
        assert BENCHMARK_REGISTRY[code].ideal_direction.value == "lower_is_better"
    assert BENCHMARK_REGISTRY["ebit_to_opex"].ideal_direction.value == "higher_is_better"


def test_cash_flow_category_has_zero_benchmarks_no_placeholders():
    # 2. tur onay karar #8: Cash Flow Engine (4.4) henuz yok -- placeholder
    # BenchmarkMetadata kaydı OLUSTURULMADI, olu kod/sahte yapisal tamlik YOK.
    entries = list_benchmarks_by_category("cash_flow")
    assert entries == []
    for ratio_code in (
        "operating_cash_flow_margin", "free_cash_flow_margin",
        "cash_flow_to_debt", "cash_return_on_assets",
        "cash_interest_coverage", "operating_cash_flow_ratio",
    ):
        assert list_benchmarks_for_ratio(ratio_code) == []


def test_total_benchmark_registry_count_is_48():
    real_entries = [
        code for code in BENCHMARK_REGISTRY if not code.startswith("_test")
    ]
    assert len(real_entries) == 48, (
        f"beklenen 48 gercek benchmark girdisi, bulunan: {len(real_entries)}"
    )


def test_all_48_ratio_codes_exist_in_rato_registry_and_units_match():
    from app.engines.common.ratio_formulas import RATIO_REGISTRY

    for code, metadata in BENCHMARK_REGISTRY.items():
        if code.startswith("_test"):
            continue
        assert metadata.ratio_code in RATIO_REGISTRY
        assert metadata.unit == RATIO_REGISTRY[metadata.ratio_code].unit
