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
from app.engines.common.ratio_derived_facts import compute_days_in_period, compute_total_liabilities
from app.engines.common.ratio_formulas import (
    CALCULATION_STRATEGIES,
    RATIO_REGISTRY,
    RATIO_REGISTRY_VERSION,
    ComputationOutcome,
    ComputationStatus,
    RatioFormulaMetadata,
    compute_linear_combination,
    compute_registered_ratio,
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
    assert set(CALCULATION_STRATEGIES.keys()) == {"sum_division", "linear_combination"}
    assert CALCULATION_STRATEGIES["sum_division"] is compute_sum_division
    assert CALCULATION_STRATEGIES["linear_combination"] is compute_linear_combination


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
    liquidity = list_ratio_formulas_by_category("liquidity")
    assert {m.key for m in liquidity} == {"current_ratio", "working_capital_ratio", "net_working_capital"}


def test_ratio_registry_version_is_defined():
    assert RATIO_REGISTRY_VERSION == "1.0.0"


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
    value, reliability, warning = compute_days_in_period(
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), months_covered=12
    )
    assert value == Decimal("365")
    assert reliability == "high"
    assert warning is None


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
    context = EngineRunContext(balance_sheet_result=bs_json, income_statement_result=is_json)

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

    leverage = body["categories"]["leverage"]
    assert leverage["ratios"]["debt_to_equity"]["value"] == 1.0

    profitability = body["categories"]["profitability"]
    assert profitability["ratios"]["gross_profit_margin"]["value"] == 39.13

    # 11 kategori henüz kayıtlı değil -- dürüstçe listeleniyor.
    assert len(body["missing_categories"]) == 11
    assert "cash_flow" in body["missing_categories"]
    assert "liquidity" not in body["missing_categories"]

    assert body["derived_base_figures"]["total_liabilities"] == 120000.0

    # calculation_provenance genişletilmiş şekilde (8 anahtar).
    assert len(body["calculation_provenance"]) == 9
    for entry in body["calculation_provenance"]:
        assert set(entry.keys()) == {
            "metric", "formula", "input_fields", "missing_inputs", "calculated",
            "source_analysis_result_ids", "reliability", "rounding_applied",
        }


def test_financial_ratio_adapter_partial_when_only_balance_sheet_available():
    bs_json, _ = _build_bs_is_results()
    adapter = FinancialRatioEngineAdapter()
    context = EngineRunContext(balance_sheet_result=bs_json, income_statement_result=None)

    result = adapter.run(content=None, filename=None, context=context)
    assert result.status == AnalysisStatus.COMPLETED

    body = result.result_json
    assert body["categories"]["liquidity"]["status"] == "calculated"
    assert body["categories"]["leverage"]["status"] == "calculated"
    # profitability tamamen IS'e bağımlı -- IS yoksa hiçbiri hesaplanamaz.
    assert body["categories"]["profitability"]["status"] == "not_calculable"
    for ratio in body["categories"]["profitability"]["ratios"].values():
        assert ratio["status"] == "missing_input"
        assert ratio["value"] is None


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
