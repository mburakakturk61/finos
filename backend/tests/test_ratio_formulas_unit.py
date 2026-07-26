"""
Milestone 4.3A (Ratio Calculation Foundation) için gerçek, çalıştırılabilir
birim testleri -- `app.engines.common.ratio_formulas`/`ratio_derived_facts`
ve `app.engines.financial_ratios.**`, `app.engines.balance_sheet.analyzer`/
`app.engines.income_statement.analyzer`'ın merkezi registry'ye yönlendirilmiş
hâli için.

Bu dosya (app.engines.** ile birlikte) yalnızca stdlib'e bağımlıdır --
sqlalchemy/fastapi/pydantic'e DEĞİL, bu yüzden
test_engine_balance_income_statement_unit.py'deki AYNI sandbox-only
`importlib` stub tekniğiyle (bkz. tests/README.md) gerçekten
çalıştırılabilir.

Kapsam: onaylanan Milestone 4.3A kararları (bkz.
docs/FINOS_MILESTONE_4_3_FINANCIAL_RATIO_ENGINE_DESIGN.md, Bölüm R/S):
  1. Calculation strategy dispatch'in kapalı/güvenli olduğu.
  2. None (missing_input) ile gerçek sıfır (no_obligation/
     undefined_zero_denominator) ayrımının doğru çalıştığı.
  3. ComputationOutcome'un status/value/missing_inputs/warnings/
     reliability/provenance'ı tutarlı ürettiği.
  4. Desteklenmeyen stratejinin kontrollü not_calculable ürettiği, hiçbir
     zaman exception/Infinity/NaN sızdırmadığı.
  5. BS/IS motorlarının merkezi registry'ye yönlendirildiği VE
     result_json şeklinin/sayısal değerlerinin Milestone 4.2 ile bit-bir
     aynı kaldığı (D.3 invariant'ı).
  6. days_in_period'in gerçek tarih farkını birincil kaynak olarak
     kullandığı, months_covered*30'un yalnızca açık düşük-güven fallback
     olduğu.
"""

import pathlib
from datetime import date
from decimal import Decimal

from app.engines.balance_sheet.analyzer import (
    compute_preliminary_structural_ratios,
    compute_working_capital,
)
from app.engines.balance_sheet.service import analyze_balance_sheet
from app.engines.common.canonical_facts import BalanceSheetFacts, IncomeStatementFacts
from app.engines.common.calculation_provenance import provenance_to_dict, provenance_to_dict_extended
from app.engines.common.ratio_derived_facts import (
    compute_average_equity,
    compute_average_inventory,
    compute_average_total_assets,
    compute_average_trade_payables,
    compute_average_trade_receivables,
    compute_average_working_capital,
    compute_days_in_period,
    compute_invested_capital,
    compute_tax_expense,
    compute_total_liabilities,
)
from app.engines.common.ratio_formulas import (
    CALCULATION_STRATEGIES,
    RATIO_REGISTRY,
    RATIO_REGISTRY_VERSION,
    ComputationOutcome,
    ComputationStatus,
    RatioFormulaMetadata,
    compute_growth_rate,
    compute_linear_combination,
    compute_registered_ratio,
    compute_scaled_division,
    compute_sum_division,
    decimal_to_json_safe,
    get_ratio_formula,
    json_safe_to_decimal,
    list_ratio_formulas_by_category,
    register_ratio_formula,
    safe_divide,
)
from app.engines.financial_ratios.adapter import FinancialRatioEngineAdapter
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.income_statement.analyzer import compute_margins, resolve_ebit, resolve_ebitda
from app.engines.income_statement.service import analyze_income_statement
from app.engines.protocol import EngineRunContext
from app.models.enums import AnalysisStatus


FIXTURES_DIR = pathlib.Path(__file__).parent / "data" / "synthetic"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


# --- Calculation Strategy: kapalı, saf fonksiyonlar ------------------------


def test_calculation_strategies_registry_is_closed_and_pure():
    # Milestone 4.3B (onaylanan tasarım Bölüm 3): "growth_rate" ve
    # "scaled_division" GERÇEKTEN gerekli bulunup eklendi --
    # "average_balance_division"/"ratio_of_ratio"/"boolean_threshold"
    # BİLİNÇLİ OLARAK reddedildi (mevcut stratejiler + depends_on_ratios
    # orkestrasyonu yeterli bulundu). Kapalı küme genişledi ama HALA
    # kapalıdır -- eval/exec/expression YOK.
    assert set(CALCULATION_STRATEGIES.keys()) == {
        "sum_division",
        "linear_combination",
        "growth_rate",
        "scaled_division",
    }
    assert CALCULATION_STRATEGIES["sum_division"] is compute_sum_division
    assert CALCULATION_STRATEGIES["linear_combination"] is compute_linear_combination
    assert CALCULATION_STRATEGIES["growth_rate"] is compute_growth_rate
    assert CALCULATION_STRATEGIES["scaled_division"] is compute_scaled_division


def test_sum_division_calculated_path():
    metadata = RatioFormulaMetadata(
        key="_t_sum_division_ok",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    outcome = compute_sum_division(metadata, {"a": Decimal("150000"), "b": Decimal("70000")})
    assert outcome.status == ComputationStatus.CALCULATED
    assert outcome.value == Decimal("2.1429")


def test_sum_division_percentage_unit_multiplies_after_quantize():
    metadata = RatioFormulaMetadata(
        key="_t_sum_division_pct",
        category="_test",
        display_name_tr="Test",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    outcome = compute_sum_division(metadata, {"a": Decimal("225000"), "b": Decimal("575000")})
    assert outcome.status == ComputationStatus.CALCULATED
    assert outcome.value == Decimal("39.1300")


def test_sum_division_missing_numerator_field_is_missing_input():
    metadata = RatioFormulaMetadata(
        key="_t_missing_num",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    outcome = compute_sum_division(metadata, {"a": None, "b": Decimal("100")})
    assert outcome.status == ComputationStatus.MISSING_INPUT
    assert outcome.value is None
    assert outcome.missing_inputs == ("a",)


def test_sum_division_missing_denominator_field_is_missing_input():
    metadata = RatioFormulaMetadata(
        key="_t_missing_den",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    # Alan facts sözlüğünde HİÇ yok (None ile aynı muameleyi görmeli).
    outcome = compute_sum_division(metadata, {"a": Decimal("100")})
    assert outcome.status == ComputationStatus.MISSING_INPUT
    assert outcome.missing_inputs == ("b",)


def test_sum_division_zero_denominator_undefined_by_default():
    metadata = RatioFormulaMetadata(
        key="_t_zero_undefined",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    outcome = compute_sum_division(metadata, {"a": Decimal("50"), "b": Decimal("0")})
    assert outcome.status == ComputationStatus.UNDEFINED_ZERO_DENOMINATOR
    assert outcome.value is None
    assert len(outcome.warnings) == 1
    assert outcome.warnings[0]["code"] == "UNDEFINED_ZERO_DENOMINATOR"
    assert outcome.warnings[0]["severity"] == "high"


def test_sum_division_zero_denominator_no_obligation_when_configured():
    metadata = RatioFormulaMetadata(
        key="_t_zero_no_obligation",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
    )
    outcome = compute_sum_division(metadata, {"a": Decimal("50"), "b": Decimal("0")})
    assert outcome.status == ComputationStatus.NO_OBLIGATION
    assert outcome.value is None
    # no_obligation -- olumsuz bir "warning" YOK, yalnızca durum bilgisi.
    assert outcome.warnings == ()


def test_linear_combination_calculated_path_no_quantize():
    metadata = RatioFormulaMetadata(
        key="_t_linear",
        category="_test",
        display_name_tr="Test",
        unit="currency",
        calculation_strategy="linear_combination",
        addend_fields=("a",),
        subtrahend_fields=("b",),
    )
    outcome = compute_linear_combination(metadata, {"a": Decimal("150000"), "b": Decimal("70000")})
    assert outcome.status == ComputationStatus.CALCULATED
    assert outcome.value == Decimal("80000")


def test_linear_combination_missing_input():
    metadata = RatioFormulaMetadata(
        key="_t_linear_missing",
        category="_test",
        display_name_tr="Test",
        unit="currency",
        calculation_strategy="linear_combination",
        addend_fields=("a",),
        subtrahend_fields=("b",),
    )
    outcome = compute_linear_combination(metadata, {"a": None, "b": Decimal("10")})
    assert outcome.status == ComputationStatus.MISSING_INPUT
    assert outcome.missing_inputs == ("a",)


def test_no_strategy_ever_produces_infinity_or_nan():
    # Sıfır payda dahil, hiçbir kombinasyon Infinity/NaN üretmez -- ya
    # None (durum ile birlikte) ya da sonlu bir Decimal döner.
    metadata = RatioFormulaMetadata(
        key="_t_no_inf",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    battery = [
        {"a": Decimal("0"), "b": Decimal("0")},
        {"a": Decimal("-100"), "b": Decimal("0")},
        {"a": Decimal("1E30"), "b": Decimal("1E-30")},
        {"a": Decimal("-1"), "b": Decimal("3")},
        {"a": None, "b": None},
    ]
    for facts in battery:
        outcome = compute_sum_division(metadata, facts)
        if outcome.value is not None:
            assert outcome.value.is_finite()


# --- register_ratio_formula: kontrollü doğrulama ---------------------------


def test_register_ratio_formula_rejects_duplicate_key():
    metadata = RatioFormulaMetadata(
        key="current_ratio",  # zaten kayıtlı
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    try:
        register_ratio_formula(metadata)
    except ValueError as error:
        assert "current_ratio" in str(error)
    else:
        raise AssertionError("Zaten kayıtlı key için ValueError bekleniyordu.")


def test_register_ratio_formula_rejects_unsupported_strategy():
    metadata = RatioFormulaMetadata(
        key="_t_unsupported_strategy_registration",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="not_a_real_strategy",
    )
    try:
        register_ratio_formula(metadata)
    except ValueError as error:
        assert "not_a_real_strategy" in str(error)
    else:
        raise AssertionError("Bilinmeyen strateji için ValueError bekleniyordu.")
    assert "_t_unsupported_strategy_registration" not in RATIO_REGISTRY


# --- compute_registered_ratio: uçtan uca sözleşme --------------------------


def test_compute_registered_ratio_unknown_key_is_not_calculable_no_exception():
    outcome = compute_registered_ratio("_this_key_does_not_exist", {})
    assert outcome.status == ComputationStatus.NOT_CALCULABLE
    assert outcome.value is None
    assert outcome.reliability == "not_calculable"
    assert outcome.provenance is not None
    assert outcome.provenance.calculated is False


def test_compute_registered_ratio_unsupported_strategy_is_controlled_not_calculable():
    # register_ratio_formula bunu normalde engeller -- desteklenmeyen
    # stratejinin ÇALIŞMA ZAMANINDA da (ör. ileride RATIO_REGISTRY dışarıdan
    # bir mekanizmayla değiştirilirse) kontrollü ele alındığını doğrulamak
    # için RATIO_REGISTRY'ye register_ratio_formula'yı BİLİNÇLİ OLARAK
    # bypass ederek doğrudan yazılıyor (yalnızca bu test için, sonda
    # temizleniyor).
    bogus = RatioFormulaMetadata(
        key="_t_bogus_strategy_runtime",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="totally_unknown_strategy",
    )
    RATIO_REGISTRY["_t_bogus_strategy_runtime"] = bogus
    try:
        outcome = compute_registered_ratio("_t_bogus_strategy_runtime", {})
        assert outcome.status == ComputationStatus.NOT_CALCULABLE
        assert outcome.value is None
        assert any(w["code"] == "UNSUPPORTED_CALCULATION_STRATEGY" for w in outcome.warnings)
    finally:
        del RATIO_REGISTRY["_t_bogus_strategy_runtime"]


def test_compute_registered_ratio_reliability_only_set_when_calculated():
    outcome_ok = compute_registered_ratio(
        "current_ratio",
        {"current_assets": Decimal("150000"), "short_term_liabilities": Decimal("70000")},
        reliability="medium",
    )
    assert outcome_ok.status == ComputationStatus.CALCULATED
    assert outcome_ok.reliability == "medium"

    outcome_missing = compute_registered_ratio(
        "current_ratio", {"current_assets": None, "short_term_liabilities": Decimal("70000")},
        reliability="medium",
    )
    assert outcome_missing.status == ComputationStatus.MISSING_INPUT
    assert outcome_missing.reliability == "not_calculable"


def test_compute_registered_ratio_none_vs_real_zero_current_ratio():
    # None girdi -> missing_input.
    missing = compute_registered_ratio(
        "current_ratio", {"current_assets": Decimal("100"), "short_term_liabilities": None}
    )
    assert missing.status == ComputationStatus.MISSING_INPUT

    # Gerçek sıfır kısa vadeli borç -> no_obligation (current_ratio için).
    no_obligation = compute_registered_ratio(
        "current_ratio", {"current_assets": Decimal("100"), "short_term_liabilities": Decimal("0")}
    )
    assert no_obligation.status == ComputationStatus.NO_OBLIGATION
    assert no_obligation.value is None


def test_compute_registered_ratio_zero_equity_is_undefined_not_no_obligation():
    outcome = compute_registered_ratio(
        "debt_to_equity", {"total_liabilities": Decimal("50000"), "equity": Decimal("0")}
    )
    assert outcome.status == ComputationStatus.UNDEFINED_ZERO_DENOMINATOR
    assert outcome.value is None
    assert any(w["code"] == "UNDEFINED_ZERO_DENOMINATOR" for w in outcome.warnings)


# --- RATIO_REGISTRY: ilk 9 ortak oranın tam envanteri -----------------------


_EXPECTED_9_RATIOS = {
    "current_ratio": ("liquidity", "ratio"),
    "working_capital_ratio": ("liquidity", "ratio"),
    "net_working_capital": ("liquidity", "currency"),
    "debt_ratio": ("leverage", "ratio"),
    "equity_ratio": ("leverage", "ratio"),
    "debt_to_equity": ("leverage", "ratio"),
    "gross_profit_margin": ("profitability", "percentage"),
    "operating_profit_margin": ("profitability", "percentage"),
    "net_profit_margin": ("profitability", "percentage"),
}


def test_ratio_registry_contains_exactly_the_first_9_ratios():
    for key, (category, unit) in _EXPECTED_9_RATIOS.items():
        metadata = get_ratio_formula(key)
        assert metadata is not None, key
        assert metadata.category == category, key
        assert metadata.unit == unit, key


def test_list_ratio_formulas_by_category():
    # Milestone 4.3B / Step 3+6: liquidity kategorisine quick_ratio/
    # cash_ratio/defensive_interval_ratio/working_capital_to_total_assets
    # eklendi.
    liquidity = list_ratio_formulas_by_category("liquidity")
    assert {m.key for m in liquidity} == {
        "current_ratio",
        "working_capital_ratio",
        "net_working_capital",
        "quick_ratio",
        "cash_ratio",
        "defensive_interval_ratio",
        "working_capital_to_total_assets",
    }


def test_ratio_registry_version_is_defined():
    # Milestone 4.3B: RatioFormulaMetadata'nın şekli değişti (depends_on_
    # ratios/current_field/prior_field/scale_field/engine_dependency/
    # direct_document_only_fields eklendi) -- J.2 cache-anahtarı disiplini
    # gereği "1.0.0" -> "1.1.0" yükseltildi.
    assert RATIO_REGISTRY_VERSION == "1.1.0"


# --- Milestone 4.3B: growth_rate stratejisi -------------------------------


def test_growth_rate_calculated_path():
    metadata = RatioFormulaMetadata(
        key="_t_growth_rate_ok",
        category="_test",
        display_name_tr="Test",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="net_sales",
        prior_field="prior_net_sales",
    )
    outcome = compute_growth_rate(
        metadata, {"net_sales": Decimal("120"), "prior_net_sales": Decimal("100")}
    )
    assert outcome.status == ComputationStatus.CALCULATED
    assert outcome.value == Decimal("20.0000")


def test_growth_rate_negative_growth():
    metadata = RatioFormulaMetadata(
        key="_t_growth_rate_negative",
        category="_test",
        display_name_tr="Test",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="net_sales",
        prior_field="prior_net_sales",
    )
    outcome = compute_growth_rate(
        metadata, {"net_sales": Decimal("80"), "prior_net_sales": Decimal("100")}
    )
    assert outcome.status == ComputationStatus.CALCULATED
    assert outcome.value == Decimal("-20.0000")


def test_growth_rate_missing_current_or_prior_is_missing_input():
    metadata = RatioFormulaMetadata(
        key="_t_growth_rate_missing",
        category="_test",
        display_name_tr="Test",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="net_sales",
        prior_field="prior_net_sales",
    )
    missing_prior = compute_growth_rate(
        metadata, {"net_sales": Decimal("120"), "prior_net_sales": None}
    )
    assert missing_prior.status == ComputationStatus.MISSING_INPUT
    assert missing_prior.missing_inputs == ("prior_net_sales",)

    missing_current = compute_growth_rate(
        metadata, {"net_sales": None, "prior_net_sales": Decimal("100")}
    )
    assert missing_current.status == ComputationStatus.MISSING_INPUT
    assert missing_current.missing_inputs == ("net_sales",)


def test_growth_rate_zero_prior_is_undefined_not_no_obligation():
    # Onaylanan tasarım kararı: "büyüme yok" ile "geçen dönem sıfırdı"
    # KARIŞTIRILMAZ -- prior==0 NO_OBLIGATION değil, UNDEFINED_ZERO_
    # DENOMINATOR'dur.
    metadata = RatioFormulaMetadata(
        key="_t_growth_rate_zero_prior",
        category="_test",
        display_name_tr="Test",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="net_sales",
        prior_field="prior_net_sales",
    )
    outcome = compute_growth_rate(
        metadata, {"net_sales": Decimal("120"), "prior_net_sales": Decimal("0")}
    )
    assert outcome.status == ComputationStatus.UNDEFINED_ZERO_DENOMINATOR
    assert outcome.value is None
    assert any(w["code"] == "UNDEFINED_ZERO_DENOMINATOR" for w in outcome.warnings)


def test_growth_rate_never_leaks_exception_on_huge_decimals():
    metadata = RatioFormulaMetadata(
        key="_t_growth_rate_huge",
        category="_test",
        display_name_tr="Test",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="net_sales",
        prior_field="prior_net_sales",
    )
    huge = Decimal("1E+6000")
    outcome = compute_growth_rate(metadata, {"net_sales": huge, "prior_net_sales": Decimal("1")})
    assert outcome.status in (ComputationStatus.CALCULATED, ComputationStatus.NOT_CALCULABLE)
    assert outcome.value != Decimal("Infinity")


# --- Milestone 4.3B: scaled_division stratejisi ---------------------------


def test_scaled_division_calculated_path():
    metadata = RatioFormulaMetadata(
        key="_t_scaled_division_ok",
        category="_test",
        display_name_tr="Test",
        unit="days",
        calculation_strategy="scaled_division",
        numerator_fields=("cash_and_equivalents", "trade_receivables"),
        denominator_fields=("operating_expenses", "cost_of_sales"),
        scale_field="days_in_period",
    )
    facts = {
        "cash_and_equivalents": Decimal("50"),
        "trade_receivables": Decimal("50"),
        "operating_expenses": Decimal("40"),
        "cost_of_sales": Decimal("60"),
        "days_in_period": Decimal("365"),
    }
    outcome = compute_scaled_division(metadata, facts)
    assert outcome.status == ComputationStatus.CALCULATED
    # (100 / 100) * 365 = 365
    assert outcome.value == Decimal("365.0000")


def test_scaled_division_missing_scale_field_is_missing_input():
    metadata = RatioFormulaMetadata(
        key="_t_scaled_division_missing_scale",
        category="_test",
        display_name_tr="Test",
        unit="days",
        calculation_strategy="scaled_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
        scale_field="scale",
    )
    outcome = compute_scaled_division(metadata, {"a": Decimal("10"), "b": Decimal("5"), "scale": None})
    assert outcome.status == ComputationStatus.MISSING_INPUT
    assert "scale" in outcome.missing_inputs


def test_scaled_division_zero_denominator_uses_metadata_status():
    metadata = RatioFormulaMetadata(
        key="_t_scaled_division_zero_denom",
        category="_test",
        display_name_tr="Test",
        unit="days",
        calculation_strategy="scaled_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
        scale_field="scale",
        zero_denominator_status=ComputationStatus.UNDEFINED_ZERO_DENOMINATOR,
    )
    outcome = compute_scaled_division(
        metadata, {"a": Decimal("10"), "b": Decimal("0"), "scale": Decimal("365")}
    )
    assert outcome.status == ComputationStatus.UNDEFINED_ZERO_DENOMINATOR
    assert outcome.value is None


def test_scaled_division_never_leaks_exception():
    metadata = RatioFormulaMetadata(
        key="_t_scaled_division_huge",
        category="_test",
        display_name_tr="Test",
        unit="days",
        calculation_strategy="scaled_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
        scale_field="scale",
    )
    outcome = compute_scaled_division(
        metadata, {"a": Decimal("1E+6000"), "b": Decimal("1"), "scale": Decimal("1E+6000")}
    )
    assert outcome.status in (ComputationStatus.CALCULATED, ComputationStatus.NOT_CALCULABLE)
    assert outcome.value != Decimal("Infinity")


# --- Milestone 4.3B: depends_on_ratios kayıt-zamanı doğrulaması -----------


def test_register_ratio_formula_rejects_unregistered_dependency():
    metadata = RatioFormulaMetadata(
        key="_t_depends_on_unregistered",
        category="_test",
        display_name_tr="Test",
        unit="days",
        calculation_strategy="sum_division",
        numerator_fields=("days_in_period",),
        denominator_fields=("_t_some_ratio_that_does_not_exist_yet",),
        depends_on_ratios=("_t_some_ratio_that_does_not_exist_yet",),
    )
    try:
        register_ratio_formula(metadata)
    except ValueError as error:
        assert "_t_some_ratio_that_does_not_exist_yet" in str(error)
    else:
        raise AssertionError("Kayıtsız bağımlılık için ValueError bekleniyordu.")
    assert "_t_depends_on_unregistered" not in RATIO_REGISTRY


def test_register_ratio_formula_accepts_already_registered_dependency():
    base = RatioFormulaMetadata(
        key="_t_dependency_base",
        category="_test",
        display_name_tr="Test",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("a",),
        denominator_fields=("b",),
    )
    register_ratio_formula(base)
    try:
        dependent = RatioFormulaMetadata(
            key="_t_dependency_dependent",
            category="_test",
            display_name_tr="Test",
            unit="days",
            calculation_strategy="sum_division",
            numerator_fields=("days_in_period",),
            denominator_fields=("_t_dependency_base",),
            depends_on_ratios=("_t_dependency_base",),
        )
        register_ratio_formula(dependent)
        try:
            # Bağımlılığın ZATEN HESAPLANMIŞ değeri, orkestrasyon tarafından
            # facts dict'e KENDİ key'iyle enjekte edilmiş gibi simüle edilir.
            facts = {"days_in_period": Decimal("365"), "_t_dependency_base": Decimal("5")}
            outcome = compute_registered_ratio("_t_dependency_dependent", facts)
            assert outcome.status == ComputationStatus.CALCULATED
            assert outcome.value == Decimal("73.0000")
        finally:
            del RATIO_REGISTRY["_t_dependency_dependent"]
    finally:
        del RATIO_REGISTRY["_t_dependency_base"]


# --- Milestone 4.3B / Step 4: effective_tax_rate / return_on_invested_capital


def test_effective_tax_rate_calculated_normal_range():
    facts = {"tax_expense": Decimal("21000"), "profit_before_tax": Decimal("102000")}
    outcome = compute_registered_ratio("effective_tax_rate", facts)
    assert outcome.status == ComputationStatus.CALCULATED
    assert outcome.value == Decimal("0.2059")
    assert get_ratio_formula("effective_tax_rate").unit == "ratio"


def test_effective_tax_rate_missing_input():
    missing_pbt = compute_registered_ratio(
        "effective_tax_rate", {"tax_expense": Decimal("100"), "profit_before_tax": None}
    )
    assert missing_pbt.status == ComputationStatus.MISSING_INPUT

    missing_tax_expense = compute_registered_ratio(
        "effective_tax_rate", {"tax_expense": None, "profit_before_tax": Decimal("100")}
    )
    assert missing_tax_expense.status == ComputationStatus.MISSING_INPUT


def test_effective_tax_rate_zero_profit_before_tax_is_undefined():
    outcome = compute_registered_ratio(
        "effective_tax_rate", {"tax_expense": Decimal("0"), "profit_before_tax": Decimal("0")}
    )
    assert outcome.status == ComputationStatus.UNDEFINED_ZERO_DENOMINATOR
    assert outcome.value is None


def test_return_on_invested_capital_calculated_when_effective_tax_rate_available():
    # Orkestrasyonun yaptığı gibi: effective_tax_rate ÖNCE hesaplanır,
    # sonucu (1 - value) olarak facts'e enjekte edilir, SONRA ROIC okur.
    etr_outcome = compute_registered_ratio(
        "effective_tax_rate", {"tax_expense": Decimal("21000"), "profit_before_tax": Decimal("102000")}
    )
    facts = {
        "ebit": Decimal("150000"),
        "invested_capital": Decimal("170000"),
        "one_minus_effective_tax_rate": Decimal("1") - etr_outcome.value,
    }
    outcome = compute_registered_ratio("return_on_invested_capital", facts)
    assert outcome.status == ComputationStatus.CALCULATED
    assert outcome.value is not None
    assert outcome.reliability == "high"


def test_return_on_invested_capital_not_calculable_when_scale_field_absent():
    # effective_tax_rate hesaplanamadıysa (missing_input/undefined), ROIC de
    # hesaplanmamalı -- "one_minus_effective_tax_rate" facts'te YOK.
    facts = {"ebit": Decimal("150000"), "invested_capital": Decimal("170000")}
    outcome = compute_registered_ratio("return_on_invested_capital", facts)
    assert outcome.status == ComputationStatus.MISSING_INPUT
    assert outcome.value is None


def test_return_on_invested_capital_depends_on_effective_tax_rate_in_registry():
    metadata = get_ratio_formula("return_on_invested_capital")
    assert metadata.depends_on_ratios == ("effective_tax_rate",)
    assert metadata.calculation_strategy == "scaled_division"


def test_analyze_financial_ratios_effective_tax_rate_out_of_range_is_not_hidden():
    # Milestone 4.3B (2. tur onay karar #7): net_profit > profit_before_tax
    # (olağandışı gelir kalemleri nedeniyle teorik olarak mümkün) ->
    # tax_expense negatif -> effective_tax_rate < 0. Değer GİZLENMEZ,
    # yalnızca warning + reliability="low" eklenir.
    bs_json = {
        "source_mode": "direct_document",
        "facts": {
            "current_assets": 100000.0, "non_current_assets": 50000.0,
            "total_assets": 150000.0, "short_term_liabilities": 40000.0,
            "long_term_liabilities": 30000.0, "equity": 80000.0,
            "cash_and_equivalents": 20000.0, "inventory": 10000.0,
            "trade_receivables": 15000.0, "trade_payables": 8000.0,
        },
    }
    is_json = {
        "source_mode": "direct_document",
        "facts": {
            "net_sales": 500000.0, "cost_of_sales": 300000.0,
            "gross_profit": 200000.0, "operating_expenses": 80000.0,
            "operating_profit": 120000.0, "financing_expenses": 10000.0,
            "profit_before_tax": 100000.0, "net_profit": 110000.0,  # net > pretax!
        },
    }
    result = analyze_financial_ratios(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        period_start_date=date(2025, 1, 1),
        period_end_date=date(2025, 12, 31),
    )
    etr = result["categories"]["profitability"]["ratios"]["effective_tax_rate"]
    assert etr["status"] == "calculated"
    assert etr["value"] is not None
    assert etr["value"] < 0
    assert etr["reliability"] == "low"
    assert any(w["code"] == "EFFECTIVE_TAX_RATE_OUT_OF_EXPECTED_RANGE" for w in etr["warnings"])


# --- Golden dataset: bit-bir bağımsız doğrulama (D.3 invariant'ı) ---------


_GOLDEN_FACTS = {
    "current_assets": Decimal("150000.0"),
    "short_term_liabilities": Decimal("70000.0"),
    "long_term_liabilities": Decimal("50000.0"),
    "total_assets": Decimal("240000.0"),
    "equity": Decimal("120000.0"),
    "gross_profit": Decimal("225000.0"),
    "operating_profit": Decimal("122000.0"),
    "net_profit": Decimal("81000.0"),
    "net_sales": Decimal("575000.0"),
}

# Bağımsız olarak (bu testten AYRI bir Python oturumunda, saf decimal
# modülüyle, app kodunu HİÇ çağırmadan) elle hesaplanmış referans değerler.
_GOLDEN_EXPECTED = {
    "current_ratio": Decimal("2.1429"),
    "working_capital_ratio": Decimal("2.1429"),
    "net_working_capital": Decimal("80000.0"),
    "debt_ratio": Decimal("0.5000"),
    "equity_ratio": Decimal("0.5000"),
    "debt_to_equity": Decimal("1.0000"),
    "gross_profit_margin": Decimal("39.1300"),
    "operating_profit_margin": Decimal("21.2200"),
    "net_profit_margin": Decimal("14.0900"),
}


def test_golden_dataset_all_9_ratios_match_independently_computed_reference():
    facts = dict(_GOLDEN_FACTS)
    facts["total_liabilities"] = compute_total_liabilities(
        facts["short_term_liabilities"], facts["long_term_liabilities"]
    )
    assert facts["total_liabilities"] == Decimal("120000.0")

    for key, expected in _GOLDEN_EXPECTED.items():
        outcome = compute_registered_ratio(key, facts)
        assert outcome.status == ComputationStatus.CALCULATED, key
        assert outcome.value == expected, (key, outcome.value, expected)


# --- D.3 invariant: BS/IS analyzer'ları merkezi registry ile bit-bir aynı -


def test_bs_preliminary_structural_ratios_match_registry_bit_for_bit():
    facts = BalanceSheetFacts(
        current_assets=_GOLDEN_FACTS["current_assets"],
        short_term_liabilities=_GOLDEN_FACTS["short_term_liabilities"],
        long_term_liabilities=_GOLDEN_FACTS["long_term_liabilities"],
        total_assets=_GOLDEN_FACTS["total_assets"],
        equity=_GOLDEN_FACTS["equity"],
    )
    result, provenance = compute_preliminary_structural_ratios(facts)

    assert result["current_ratio"] == _GOLDEN_EXPECTED["current_ratio"]
    assert result["debt_ratio"] == _GOLDEN_EXPECTED["debt_ratio"]
    assert result["equity_ratio"] == _GOLDEN_EXPECTED["equity_ratio"]
    assert result["debt_to_equity"] == _GOLDEN_EXPECTED["debt_to_equity"]

    # Eski (Milestone 4.2, safe_divide DOĞRUDAN çağrılarak) hesaplamayla da
    # bağımsız çapraz kontrol -- iki yol da AYNI sonucu üretmeli.
    old_current_ratio = safe_divide(facts.current_assets, facts.short_term_liabilities)
    old_total_liabilities = facts.short_term_liabilities + facts.long_term_liabilities
    old_debt_ratio = safe_divide(old_total_liabilities, facts.total_assets)
    assert result["current_ratio"] == old_current_ratio
    assert result["debt_ratio"] == old_debt_ratio

    for entry in provenance:
        assert entry.calculated is True


def test_bs_working_capital_matches_registry_bit_for_bit():
    facts = BalanceSheetFacts(
        current_assets=_GOLDEN_FACTS["current_assets"],
        short_term_liabilities=_GOLDEN_FACTS["short_term_liabilities"],
    )
    result, _ = compute_working_capital(facts)
    assert result["net_working_capital"] == _GOLDEN_EXPECTED["net_working_capital"]
    assert result["working_capital_ratio"] == _GOLDEN_EXPECTED["working_capital_ratio"]


def test_bs_structural_ratios_missing_input_still_none_after_migration():
    # Mevcut regresyon testinin (test_engine_balance_income_statement_unit.py
    # ::test_balance_sheet_structural_ratios_missing_input_is_none) AYNI
    # senaryosu -- merkezi registry'ye geçtikten sonra da davranış aynı.
    facts = BalanceSheetFacts(current_assets=Decimal("150000"))  # short_term_liabilities eksik
    result, provenance = compute_preliminary_structural_ratios(facts)
    assert result["current_ratio"] is None
    entry = next(p for p in provenance if p.metric == "current_ratio")
    assert entry.calculated is False
    # Milestone 4.3A İYİLEŞTİRMESİ: eski kodda current_ratio/equity_ratio
    # için missing_inputs HER ZAMAN () idi (bir tutarsızlık) -- merkezi
    # registry artık gerçek eksik alan adını raporluyor.
    assert "short_term_liabilities" in entry.missing_inputs


def test_is_margins_match_registry_bit_for_bit():
    facts = IncomeStatementFacts(
        gross_profit=_GOLDEN_FACTS["gross_profit"],
        operating_profit=_GOLDEN_FACTS["operating_profit"],
        net_profit=_GOLDEN_FACTS["net_profit"],
        net_sales=_GOLDEN_FACTS["net_sales"],
    )
    margins, provenance = compute_margins(facts, ebit=None, ebitda=None)

    assert margins["gross_margin_pct"] == _GOLDEN_EXPECTED["gross_profit_margin"]
    assert margins["operating_margin_pct"] == _GOLDEN_EXPECTED["operating_profit_margin"]
    assert margins["net_margin_pct"] == _GOLDEN_EXPECTED["net_profit_margin"]

    # result_json["margins"] şekli (5 anahtar) DEĞİŞMEDİ.
    assert set(margins.keys()) == {
        "gross_margin_pct", "operating_margin_pct", "ebit_margin_pct",
        "ebitda_margin_pct", "net_margin_pct",
    }
    # Provenance'ın YEREL alan adına (result_json["margins"] anahtarına)
    # yeniden adlandırıldığı (dataclasses.replace) doğrulanıyor.
    metrics = {p.metric for p in provenance}
    assert metrics == {
        "gross_margin_pct", "operating_margin_pct", "ebit_margin_pct",
        "ebitda_margin_pct", "net_margin_pct",
    }


def test_provenance_to_dict_unchanged_5_keys_even_after_migration():
    # Milestone 4.3A onayı madde 5/kritik regresyon koruması:
    # provenance_to_dict() BS/IS'in dış sözleşmesi için HÂLÂ yalnızca 5
    # anahtar üretmeli -- yeni reliability/rounding_applied/
    # source_analysis_result_ids alanları BURADA SIZMAMALI.
    facts = BalanceSheetFacts(
        current_assets=_GOLDEN_FACTS["current_assets"],
        short_term_liabilities=_GOLDEN_FACTS["short_term_liabilities"],
        long_term_liabilities=_GOLDEN_FACTS["long_term_liabilities"],
        total_assets=_GOLDEN_FACTS["total_assets"],
        equity=_GOLDEN_FACTS["equity"],
    )
    _, provenance = compute_preliminary_structural_ratios(facts)
    for entry in provenance:
        as_dict = provenance_to_dict(entry)
        assert set(as_dict.keys()) == {"metric", "formula", "input_fields", "missing_inputs", "calculated"}
        # Ama dataclass'ın kendisinde yeni alanlar GERÇEKTEN dolu.
        assert entry.reliability is not None
        assert entry.rounding_applied is not None

        extended = provenance_to_dict_extended(entry)
        assert set(extended.keys()) == {
            "metric", "formula", "input_fields", "missing_inputs", "calculated",
            "source_analysis_result_ids", "reliability", "rounding_applied",
        }


# --- Full-service regresyon: gerçek fixture'larla uçtan uca ----------------


def test_analyze_balance_sheet_current_ratio_matches_golden_value_with_real_fixture():
    content = _read_fixture("synthetic_balance_sheet_direct.xlsx")
    outcome = analyze_balance_sheet(content=content, filename="bilanco.xlsx", trial_balance_result=None)
    assert outcome.status == AnalysisStatus.COMPLETED
    ratios = outcome.result_json["preliminary_structural_ratios"]
    assert ratios["current_ratio"] == 2.1429
    assert ratios["debt_ratio"] == 0.5
    assert ratios["equity_ratio"] == 0.5
    assert ratios["debt_to_equity"] == 1.0
    wc = outcome.result_json["working_capital"]
    assert wc["net_working_capital"] == 80000.0
    assert wc["working_capital_ratio"] == 2.1429


def test_analyze_income_statement_margins_match_golden_value_with_real_fixture():
    content = _read_fixture("synthetic_income_statement_direct.xlsx")
    outcome = analyze_income_statement(content=content, filename="gelir_tablosu.xlsx", trial_balance_result=None)
    assert outcome.status == AnalysisStatus.COMPLETED
    margins = outcome.result_json["margins"]
    assert margins["gross_margin_pct"] == 39.13
    assert margins["net_margin_pct"] == 14.09


# --- ratio_derived_facts: total_liabilities / days_in_period ---------------


def test_compute_total_liabilities_none_when_either_missing():
    assert compute_total_liabilities(None, Decimal("50")) is None
    assert compute_total_liabilities(Decimal("50"), None) is None


def test_compute_total_liabilities_sums_when_both_present():
    assert compute_total_liabilities(Decimal("70000"), Decimal("50000")) == Decimal("120000")


def test_days_in_period_real_dates_primary_source_high_reliability():
    # Milestone 4.3B (2. tur onay karar #8): FinancialPeriod.start_date/
    # end_date KAPSAYICIDIR -- 2024 ARTIK YIL olduğu için 01.01-31.12
    # aralığı 366 gün üretmelidir (365 DEĞİL -- eski, +1'siz formülün
    # ürettiği yanlış değer).
    value, reliability, warning = compute_days_in_period(
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), months_covered=12
    )
    assert value == Decimal("366")
    assert reliability == "high"
    assert warning is None


def test_days_in_period_normal_year_is_365():
    # Zorunlu test (2. tur onay karar #8, madde 1): 2025 ARTIK YIL DEĞİL.
    value, reliability, warning = compute_days_in_period(
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31), months_covered=12
    )
    assert value == Decimal("365")
    assert reliability == "high"
    assert warning is None


def test_days_in_period_leap_year_is_366():
    # Zorunlu test (2. tur onay karar #8, madde 2): 2024 ARTIK YIL.
    value, reliability, warning = compute_days_in_period(
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), months_covered=12
    )
    assert value == Decimal("366")
    assert reliability == "high"
    assert warning is None


def test_days_in_period_invalid_date_order_is_controlled_not_calculable():
    # Zorunlu test (2. tur onay karar #8, madde 4): end_date < start_date
    # -- kontrollü not_calculable + domain warning, ham exception/negatif
    # gün sayısı ASLA sızmaz.
    value, reliability, warning = compute_days_in_period(
        start_date=date(2025, 12, 31), end_date=date(2025, 1, 1), months_covered=12
    )
    assert value is None
    assert reliability == "not_calculable"
    assert warning is not None
    assert warning["code"] == "DAYS_IN_PERIOD_INVALID_DATE_ORDER"


def test_days_in_period_extreme_dates_never_raise():
    # Zorunlu test (2. tur onay karar #8, madde 5): çok uzak tarihlerde bile
    # hiçbir ham exception (OverflowError vb.) sızmamalı.
    value, reliability, warning = compute_days_in_period(
        start_date=date.min, end_date=date.max, months_covered=None
    )
    assert reliability in ("high", "not_calculable")
    if value is not None:
        assert value > Decimal("0")


def test_days_in_period_fallback_only_when_dates_missing_and_flagged():
    value, reliability, warning = compute_days_in_period(
        start_date=None, end_date=None, months_covered=12
    )
    assert value == Decimal("360")
    assert reliability == "low"
    assert warning is not None
    assert warning["code"] == "DAYS_IN_PERIOD_LOW_CONFIDENCE_FALLBACK"


def test_days_in_period_not_calculable_when_nothing_available():
    value, reliability, warning = compute_days_in_period(
        start_date=None, end_date=None, months_covered=None
    )
    assert value is None
    assert reliability == "not_calculable"
    assert warning is None


def test_days_in_period_partial_dates_still_uses_fallback_not_silently_wrong():
    # Yalnızca start_date var, end_date yok -- birincil kaynak KULLANILAMAZ,
    # fallback'e (varsa) düşülür, sessizce yanlış bir tarih farkı ÜRETİLMEZ.
    value, reliability, warning = compute_days_in_period(
        start_date=date(2024, 1, 1), end_date=None, months_covered=3
    )
    assert value == Decimal("90")
    assert reliability == "low"
    assert warning is not None


# --- Milestone 4.3B: average_* ortak deseni --------------------------------


def test_average_two_periods_present_is_two_period_average_high_reliability():
    for fn in (
        compute_average_inventory,
        compute_average_trade_receivables,
        compute_average_trade_payables,
        compute_average_total_assets,
        compute_average_equity,
        compute_average_working_capital,
    ):
        value, reliability, calculation_basis = fn(Decimal("120"), Decimal("100"))
        assert value == Decimal("110")
        assert reliability == "high"
        assert calculation_basis == "two_period_average"


def test_average_only_current_present_is_ending_balance_fallback_no_warning():
    # 2. tur onay karar #4: warning YOK, yalnızca reliability/
    # calculation_basis alan çifti.
    value, reliability, calculation_basis = compute_average_inventory(Decimal("100"), None)
    assert value == Decimal("100")
    assert reliability == "medium"
    assert calculation_basis == "ending_balance_fallback"


def test_average_both_missing_is_not_calculable():
    value, reliability, calculation_basis = compute_average_total_assets(None, None)
    assert value is None
    assert reliability == "not_calculable"
    assert calculation_basis == "not_calculable"


def test_average_real_zero_prior_is_not_confused_with_none():
    # Onceki donem inventory=0 (gercek sifir) -- None DEGIL, ortalamaya
    # KATILIR.
    value, reliability, calculation_basis = compute_average_inventory(Decimal("100"), Decimal("0"))
    assert value == Decimal("50")
    assert reliability == "high"
    assert calculation_basis == "two_period_average"


def test_average_total_assets_shared_by_roa_and_asset_turnover_single_source():
    # Bolum 8 riski: iki oran AYNI fonksiyondan AYNI sonucu okumali.
    roa_input = compute_average_total_assets(Decimal("500"), Decimal("400"))
    asset_turnover_input = compute_average_total_assets(Decimal("500"), Decimal("400"))
    assert roa_input == asset_turnover_input


# --- Milestone 4.3B: tax_expense / invested_capital ara büyüklükleri ------


def test_compute_tax_expense_both_present():
    assert compute_tax_expense(Decimal("100"), Decimal("80")) == Decimal("20")


def test_compute_tax_expense_missing_is_none():
    assert compute_tax_expense(None, Decimal("80")) is None
    assert compute_tax_expense(Decimal("100"), None) is None


def test_compute_invested_capital_both_present():
    assert compute_invested_capital(Decimal("300"), Decimal("200")) == Decimal("500")


def test_compute_invested_capital_missing_is_none():
    assert compute_invested_capital(None, Decimal("200")) is None
    assert compute_invested_capital(Decimal("300"), None) is None


# --- json_safe_to_decimal / decimal_to_json_safe: sınır dönüşümü ----------


def test_json_safe_to_decimal_round_trip():
    original = Decimal("2.1429")
    as_json = decimal_to_json_safe(original)
    back = json_safe_to_decimal(as_json)
    assert back == original


def test_json_safe_to_decimal_none_stays_none():
    assert json_safe_to_decimal(None) is None
    assert decimal_to_json_safe(None) is None


# --- FinancialRatioEngineAdapter / analyze_financial_ratios: izole -------


def _build_bs_is_results():
    bs_content = _read_fixture("synthetic_balance_sheet_direct.xlsx")
    bs_outcome = analyze_balance_sheet(content=bs_content, filename="bilanco.xlsx", trial_balance_result=None)
    is_content = _read_fixture("synthetic_income_statement_direct.xlsx")
    is_outcome = analyze_income_statement(content=is_content, filename="gelir.xlsx", trial_balance_result=None)
    return bs_outcome.result_json, is_outcome.result_json


def test_financial_ratio_adapter_matches_protocol():
    adapter = FinancialRatioEngineAdapter()
    assert adapter.analysis_type.value == "financial_ratios"
    assert adapter.requires_content is False


def test_financial_ratio_adapter_fails_cleanly_without_any_source():
    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext()  # balance_sheet_result/income_statement_result ikisi de None
    result = adapter.run(content=None, filename=None, context=context)
    assert result.status == AnalysisStatus.FAILED
    assert result.result_json is None
    assert result.error_message is not None


def test_financial_ratio_adapter_computes_first_9_ratios_with_real_bs_is_results():
    bs_json, is_json = _build_bs_is_results()
    adapter = FinancialRatioEngineAdapter()
    # Milestone 4.3B: gün-bazlı oranlar (defensive_interval_ratio) için
    # period_start_date/end_date sağlanıyor -- 2024 ARTIK YIL, 366 gün.
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )

    result = adapter.run(content=None, filename=None, context=context)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.source_mode.value == "multi_source_derived"
    assert result.sources == []  # Milestone 4.3A: source-tracking henüz YOK

    body = result.result_json
    assert body["engine"] == "financial_ratios"
    assert body["ratio_registry_version"] == RATIO_REGISTRY_VERSION

    liquidity = body["categories"]["liquidity"]
    assert liquidity["status"] == "calculated"
    assert liquidity["ratios"]["current_ratio"]["value"] == 2.1429
    assert liquidity["ratios"]["current_ratio"]["status"] == "calculated"
    assert liquidity["ratios"]["current_ratio"]["reliability"] == "high"
    # Milestone 4.3B / Step 3: yeni Likidite oranları -- BS source_mode
    # direct_document olduğu için quick_ratio/cash_ratio NOT_APPLICABLE
    # DEĞİL, gerçekten CALCULATED.
    assert liquidity["ratios"]["quick_ratio"]["value"] == 1.6429
    assert liquidity["ratios"]["quick_ratio"]["status"] == "calculated"
    assert liquidity["ratios"]["cash_ratio"]["value"] == 0.8571
    assert liquidity["ratios"]["defensive_interval_ratio"]["value"] == 83.5435
    assert liquidity["ratios"]["defensive_interval_ratio"]["unit"] == "days"

    leverage = body["categories"]["leverage"]
    assert leverage["ratios"]["debt_to_equity"]["value"] == 1.0
    # Milestone 4.3B / Step 3: yeni Borçluluk oranları. Bu sentetik IS
    # fixture'ında ebit/ebitda alanları `null`dır (resolve_ebit/resolve_
    # ebitda v1 politikası gereği türetilemiyor) -- bu yüzden ebit/ebitda'ya
    # bağımlı 3 oran (interest_coverage_ratio/ebitda_coverage_ratio/
    # debt_to_ebitda) dürüstçe missing_input'tur, kategori "partial"dır
    # (9 orandan 6'sı hesaplanır) -- sahte bir değer ÜRETİLMEDİ.
    assert leverage["status"] == "partial"
    assert leverage["ratios"]["long_term_debt_to_equity"]["status"] == "calculated"
    assert leverage["ratios"]["financial_leverage_multiplier"]["status"] == "calculated"
    assert leverage["ratios"]["interest_coverage_ratio"]["status"] == "missing_input"
    assert leverage["ratios"]["ebitda_coverage_ratio"]["status"] == "missing_input"
    assert leverage["ratios"]["debt_to_ebitda"]["status"] == "missing_input"
    assert leverage["ratios"]["fixed_charge_coverage"]["status"] == "not_calculable"
    assert leverage["ratios"]["fixed_charge_coverage"]["value"] is None

    profitability = body["categories"]["profitability"]
    assert profitability["ratios"]["gross_profit_margin"]["value"] == 39.13
    # Milestone 4.3B / Step 4: yeni Kârlılık oranları. Bu sentetik IS
    # fixture'ında ebit/ebitda `null`dır -- ebit_margin/ebitda_margin/
    # return_on_capital_employed/return_on_invested_capital dürüstçe
    # missing_input'tur; pretax_profit_margin/effective_tax_rate ise
    # yalnızca profit_before_tax/net_profit'e ihtiyaç duyduğu için
    # GERÇEKTEN hesaplanır.
    assert profitability["status"] == "partial"
    assert profitability["ratios"]["pretax_profit_margin"]["value"] == 17.74
    assert profitability["ratios"]["effective_tax_rate"]["value"] == 0.2059
    assert profitability["ratios"]["effective_tax_rate"]["unit"] == "ratio"
    assert profitability["ratios"]["ebit_margin"]["status"] == "missing_input"
    assert profitability["ratios"]["return_on_invested_capital"]["status"] == "missing_input"
    # Milestone 4.3B / Step 5: önceki dönem BS SAĞLANMADI -- average_*
    # ending_balance_fallback'e düşer (dönem-sonu bakiye), reliability
    # "medium"a düşer, WARNING ÜRETİLMEZ (yalnızca calculation_basis).
    assert profitability["ratios"]["return_on_assets"]["value"] == 33.75
    assert profitability["ratios"]["return_on_assets"]["calculation_basis"] == "ending_balance_fallback"
    assert profitability["ratios"]["return_on_assets"]["reliability"] == "medium"
    assert profitability["ratios"]["return_on_equity"]["value"] == 67.5

    activity = body["categories"]["activity"]
    assert activity["ratios"]["asset_turnover"]["value"] == 2.3958
    assert activity["ratios"]["inventory_turnover"]["value"] == 10.0
    assert activity["ratios"]["receivables_turnover"]["value"] == 12.7778
    assert activity["ratios"]["payables_turnover"]["value"] == 11.6667
    assert activity["ratios"]["inventory_turnover"]["calculation_basis"] == "ending_balance_fallback"
    # Milestone 4.3B / Step 6: depends_on_ratios zinciri -- fixed_asset_
    # turnover/working_capital_turnover/days_*/cash_conversion_cycle.
    assert activity["ratios"]["fixed_asset_turnover"]["value"] == 6.3889
    assert activity["ratios"]["working_capital_turnover"]["value"] == 7.1875
    assert activity["ratios"]["days_inventory_outstanding"]["value"] == 36.6
    assert activity["ratios"]["days_inventory_outstanding"]["unit"] == "days"
    assert activity["ratios"]["days_sales_outstanding"]["value"] == 28.6434
    assert activity["ratios"]["days_payables_outstanding"]["value"] == 31.3713
    assert activity["ratios"]["cash_conversion_cycle"]["value"] == 33.8721

    liquidity_wcta = body["categories"]["liquidity"]["ratios"]["working_capital_to_total_assets"]
    assert liquidity_wcta["value"] == 0.3333
    assert liquidity_wcta["status"] == "calculated"

    efficiency = body["categories"]["efficiency"]
    assert efficiency["ratios"]["operating_expense_ratio"]["value"] == 19.13
    assert efficiency["ratios"]["cost_of_sales_ratio"]["value"] == 60.87
    assert efficiency["ratios"]["overhead_ratio"]["value"] == 20.52
    assert efficiency["ratios"]["non_operating_income_dependency"]["value"] == 12.3
    assert efficiency["ratios"]["financing_expense_to_sales"]["value"] == 3.48
    # ebit null oldugu icin ebit_to_opex missing_input -- kategori partial.
    assert efficiency["ratios"]["ebit_to_opex"]["status"] == "missing_input"
    assert efficiency["status"] == "partial"

    # Milestone 4.3B / Step 8: onceki donem SAGLANMADI -- tum buyume
    # oranlari missing_input (sustainable_growth_rate HER ZAMAN
    # not_calculable), kategori "not_calculable".
    growth = body["categories"]["growth"]
    assert growth["status"] == "not_calculable"
    assert growth["ratios"]["sales_growth"]["status"] == "missing_input"
    assert growth["ratios"]["sustainable_growth_rate"]["status"] == "not_calculable"
    assert growth["ratios"]["sustainable_growth_rate"]["value"] is None

    # Milestone 4.3B / Step 9: Nakit Akışı kategorisi tamamı engine_
    # dependency ile HER ZAMAN not_calculable -- MISSING_INPUT DEĞİL.
    cash_flow = body["categories"]["cash_flow"]
    assert cash_flow["status"] == "not_calculable"
    for ratio in cash_flow["ratios"].values():
        assert ratio["status"] == "not_calculable"
        assert ratio["value"] is None
        assert any(w["code"] == "ENGINE_DEPENDENCY_NOT_AVAILABLE" for w in ratio["warnings"])

    # Milestone 4.3B / Step 5-9 sonunda 7 kategori dolu (liquidity/leverage/
    # profitability/activity/efficiency/growth/cash_flow) -- kalan 7'si
    # dürüstçe listeleniyor (Bölüm 10'daki 7 faz-atanmamış kategori).
    assert len(body["missing_categories"]) == 7
    assert "cash_flow" not in body["missing_categories"]
    assert "liquidity" not in body["missing_categories"]
    assert "activity" not in body["missing_categories"]
    assert "efficiency" not in body["missing_categories"]
    assert "growth" not in body["missing_categories"]

    assert body["derived_base_figures"]["total_liabilities"] == 120000.0
    assert body["derived_base_figures"]["quick_assets"] == 115000.0
    assert body["derived_base_figures"]["days_in_period"] == 366.0
    assert body["derived_base_figures"]["invested_capital"] == 170000.0

    # calculation_provenance genişletilmiş şekilde (8 anahtar) -- Milestone
    # 4.3B sonunda 57 oran (7 likidite + 10 borçluluk [fixed_charge_
    # coverage dahil] + 11 kârlılık + 10 faaliyet + 6 verimlilik + 7 büyüme
    # + 6 nakit akışı).
    assert len(body["calculation_provenance"]) == 57
    for entry in body["calculation_provenance"]:
        assert set(entry.keys()) == {
            "metric", "formula", "input_fields", "missing_inputs", "calculated",
            "source_analysis_result_ids", "reliability", "rounding_applied",
        }


def test_financial_ratio_adapter_partial_when_only_balance_sheet_available():
    bs_json, _ = _build_bs_is_results()
    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=None,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )

    result = adapter.run(content=None, filename=None, context=context)
    assert result.status == AnalysisStatus.COMPLETED

    body = result.result_json
    # defensive_interval_ratio, IS alanlarına (operating_expenses/
    # cost_of_sales) da ihtiyaç duyar -- IS yokken bu oran missing_input
    # olur, liquidity kategorisi "partial" olur (6 orandan 5'i hesaplanır).
    assert body["categories"]["liquidity"]["status"] == "partial"
    assert body["categories"]["liquidity"]["ratios"]["current_ratio"]["status"] == "calculated"
    assert (
        body["categories"]["liquidity"]["ratios"]["defensive_interval_ratio"]["status"]
        == "missing_input"
    )
    # leverage'ın 6/9'u yalnızca BS alanlarına (debt_ratio/equity_ratio/
    # debt_to_equity/long_term_debt_to_equity/short_term_debt_ratio/
    # financial_leverage_multiplier) bağımlı, kalan 3'ü (interest_coverage_
    # ratio/ebitda_coverage_ratio/debt_to_ebitda) IS alanlarına (ebit/
    # ebitda/financing_expenses) ihtiyaç duyar -- IS yokken bunlar da
    # missing_input'tur, kategori "partial"dır.
    assert body["categories"]["leverage"]["status"] == "partial"
    assert body["categories"]["leverage"]["ratios"]["debt_ratio"]["status"] == "calculated"
    assert (
        body["categories"]["leverage"]["ratios"]["interest_coverage_ratio"]["status"]
        == "missing_input"
    )
    # profitability tamamen IS'e bağımlı -- IS yoksa hiçbiri hesaplanamaz.
    assert body["categories"]["profitability"]["status"] == "not_calculable"
    for ratio in body["categories"]["profitability"]["ratios"].values():
        assert ratio["status"] == "missing_input"
        assert ratio["value"] is None


def test_financial_ratio_adapter_average_uses_two_period_average_when_prior_available():
    # Milestone 4.3B / Step 5: onceki donem BS SAGLANDIGINDA average_* iki
    # donemin ortalamasi olmali, reliability="high"/calculation_basis=
    # "two_period_average" olmali (ending_balance_fallback DEGIL).
    bs_json, is_json = _build_bs_is_results()
    prior_bs_json = dict(bs_json)
    prior_bs_json["facts"] = dict(bs_json["facts"])
    # onceki donem total_assets/inventory farkli (ortalamanin GERCEKTEN
    # iki degerin ortalamasi oldugunu kanitlamak icin).
    prior_bs_json["facts"]["total_assets"] = 200000.0
    prior_bs_json["facts"]["inventory"] = 25000.0

    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        prior_period_balance_sheet_result=prior_bs_json,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )
    result = adapter.run(content=None, filename=None, context=context)
    body = result.result_json

    # average_total_assets = (240000 + 200000) / 2 = 220000
    roa = body["categories"]["profitability"]["ratios"]["return_on_assets"]
    assert roa["calculation_basis"] == "two_period_average"
    assert roa["reliability"] == "high"
    # net_profit(81000) / average_total_assets(220000) * 100
    expected_roa = round(float(Decimal("81000") / Decimal("220000") * Decimal("100")), 4)
    assert roa["value"] == expected_roa or abs(roa["value"] - expected_roa) < 0.01

    # average_inventory = (35000 + 25000) / 2 = 30000
    inventory_turnover = body["categories"]["activity"]["ratios"]["inventory_turnover"]
    assert inventory_turnover["calculation_basis"] == "two_period_average"
    assert inventory_turnover["reliability"] == "high"


def test_average_total_assets_shared_between_roa_and_asset_turnover_end_to_end():
    # Bolum 8 riski: return_on_assets VE asset_turnover AYNI
    # average_total_assets enjekte edilmis degerinden okumali.
    bs_json, is_json = _build_bs_is_results()
    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )
    result = adapter.run(content=None, filename=None, context=context)
    body = result.result_json
    roa = body["categories"]["profitability"]["ratios"]["return_on_assets"]
    asset_turnover = body["categories"]["activity"]["ratios"]["asset_turnover"]
    assert roa["calculation_basis"] == asset_turnover["calculation_basis"]
    assert roa["reliability"] == asset_turnover["reliability"]


def test_financial_ratio_adapter_days_inventory_outstanding_missing_when_turnover_not_applicable():
    # Milestone 4.3B / Step 6 (Bölüm 3.2 "kayıp bilgi" tradeoff'u): BS
    # trial_balance_derived modda inventory_turnover NOT_APPLICABLE olur;
    # bu deger facts'e None olarak enjekte edilir, days_inventory_
    # outstanding bunu MISSING_INPUT olarak gorur (kendi basina NOT_
    # APPLICABLE degil) -- asil neden inventory_turnover'in KENDI
    # sonucunda hala izlenebilir.
    bs_json, is_json = _build_bs_is_results()
    bs_json = dict(bs_json)
    bs_json["source_mode"] = "trial_balance_derived"
    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )
    result = adapter.run(content=None, filename=None, context=context)
    body = result.result_json
    activity = body["categories"]["activity"]
    assert activity["ratios"]["inventory_turnover"]["status"] == "not_applicable"
    assert activity["ratios"]["days_inventory_outstanding"]["status"] == "missing_input"
    assert "inventory_turnover" in activity["ratios"]["days_inventory_outstanding"]["missing_inputs"]
    assert activity["ratios"]["cash_conversion_cycle"]["status"] == "missing_input"


def test_no_circular_dependency_possible_in_activity_chain():
    # Statik test (Property test'in basitleştirilmiş biçimi): tüm
    # depends_on_ratios zincirlerinin KENDİLERİNDEN ÖNCE tanımlı olduğu --
    # register_ratio_formula bunu kayıt anında ZATEN garanti eder, ama
    # burada AÇIKÇA da doğrulanıyor (sonlu, döngüsüz bir DAG).
    visited: set[str] = set()

    def _walk(key: str, stack: tuple[str, ...]) -> None:
        assert key not in stack, f"Döngüsel bağımlılık tespit edildi: {stack} -> {key}"
        metadata = get_ratio_formula(key)
        if metadata is None:
            return
        for dep in metadata.depends_on_ratios:
            _walk(dep, stack + (key,))
        visited.add(key)

    for ratio_key in ("cash_conversion_cycle", "working_capital_to_total_assets", "return_on_invested_capital"):
        _walk(ratio_key, ())
    assert "inventory_turnover" in visited or "effective_tax_rate" in visited or "net_working_capital" in visited


def test_financial_ratio_adapter_growth_ratios_calculated_with_prior_period():
    # Milestone 4.3B / Step 8: onceki donem BS+IS SAGLANDIGINDA buyume
    # oranlari GERCEKTEN hesaplanmali.
    bs_json, is_json = _build_bs_is_results()
    prior_bs_json = dict(bs_json)
    prior_bs_json["facts"] = dict(bs_json["facts"])
    prior_bs_json["facts"]["total_assets"] = 200000.0
    prior_bs_json["facts"]["equity"] = 100000.0
    prior_is_json = dict(is_json)
    prior_is_json["facts"] = dict(is_json["facts"])
    prior_is_json["facts"]["net_sales"] = 500000.0
    prior_is_json["facts"]["gross_profit"] = 180000.0
    prior_is_json["facts"]["net_profit"] = 70000.0

    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        prior_period_balance_sheet_result=prior_bs_json,
        prior_period_income_statement_result=prior_is_json,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )
    result = adapter.run(content=None, filename=None, context=context)
    body = result.result_json
    growth = body["categories"]["growth"]

    # sales_growth = (575000-500000)/500000*100 = 15.0
    assert growth["ratios"]["sales_growth"]["status"] == "calculated"
    assert growth["ratios"]["sales_growth"]["value"] == 15.0
    # net_profit_growth = (81000-70000)/70000*100
    assert growth["ratios"]["net_profit_growth"]["status"] == "calculated"
    # total_assets_growth = (240000-200000)/200000*100 = 20.0
    assert growth["ratios"]["total_assets_growth"]["value"] == 20.0
    # equity_growth = (120000-100000)/100000*100 = 20.0
    assert growth["ratios"]["equity_growth"]["value"] == 20.0
    # ebitda hala None oldugu icin ebitda_growth missing_input.
    assert growth["ratios"]["ebitda_growth"]["status"] == "missing_input"
    assert growth["status"] == "partial"


def test_financial_ratio_adapter_growth_ratio_negative_prior_edge_case():
    # Negatif onceki-donem degeri (ozkaynak zarar donemi gibi) -- growth_rate
    # abs(prior) kullanir, deger dogru isaretle hesaplanir, exception YOK.
    bs_json, is_json = _build_bs_is_results()
    prior_bs_json = dict(bs_json)
    prior_bs_json["facts"] = dict(bs_json["facts"])
    prior_bs_json["facts"]["equity"] = -50000.0
    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        prior_period_balance_sheet_result=prior_bs_json,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )
    result = adapter.run(content=None, filename=None, context=context)
    body = result.result_json
    equity_growth = body["categories"]["growth"]["ratios"]["equity_growth"]
    assert equity_growth["status"] == "calculated"
    # (120000 - (-50000)) / abs(-50000) * 100 = 340.0
    assert equity_growth["value"] == 340.0


def test_financial_ratio_adapter_not_applicable_when_bs_is_trial_balance_derived():
    # Milestone 4.3B (Bölüm 6): quick_ratio/cash_ratio/defensive_interval_
    # ratio, BS source_mode "direct_document" DEĞİLKEN NOT_APPLICABLE
    # döner -- missing_input DEĞİL (yapısal olarak imkansız, veri eksik
    # değil).
    bs_json, is_json = _build_bs_is_results()
    bs_json = dict(bs_json)
    bs_json["source_mode"] = "trial_balance_derived"
    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(
        balance_sheet_result=bs_json,
        income_statement_result=is_json,
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
    )

    result = adapter.run(content=None, filename=None, context=context)
    body = result.result_json
    liquidity = body["categories"]["liquidity"]
    assert liquidity["ratios"]["quick_ratio"]["status"] == "not_applicable"
    assert liquidity["ratios"]["quick_ratio"]["value"] is None
    assert liquidity["ratios"]["cash_ratio"]["status"] == "not_applicable"
    assert liquidity["ratios"]["defensive_interval_ratio"]["status"] == "not_applicable"
    # current_ratio gibi 4.3A'nın 9 oranı bu kısıtlamaya tabi DEĞİL --
    # trial_balance_derived modda da hesaplanabilir kalmalı.
    assert liquidity["ratios"]["current_ratio"]["status"] == "calculated"


def test_analyze_financial_ratios_is_not_wired_to_bulk_upload_or_recompute():
    """
    Onaylanan Milestone 4.3A kesin sınırı: ratio_recompute.py OLUŞTURULMADI
    ve app/services/bulk_upload.py'ye HİÇBİR bağlantı eklenmedi. Bu test,
    bulk_upload.py'nin kaynak metninde financial_ratios/FinancialRatioEngine
    referansı OLMADIĞINI doğrulayarak bu sınırın yanlışlıkla ihlal
    edilmediğini garanti eder.
    """
    import pathlib as _pathlib

    bulk_upload_path = _pathlib.Path(__file__).parent.parent / "app" / "services" / "bulk_upload.py"
    source = bulk_upload_path.read_text(encoding="utf-8")
    assert "financial_ratios" not in source
    assert "FinancialRatioEngineAdapter" not in source

    ratio_recompute_path = _pathlib.Path(__file__).parent.parent / "app" / "services" / "ratio_recompute.py"
    assert not ratio_recompute_path.exists()
