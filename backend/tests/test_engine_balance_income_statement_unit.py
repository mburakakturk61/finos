"""
Milestone 4.2 (Balance Sheet + Income Statement Engine) için gerçek,
çalıştırılabilir birim testleri.

Bu dosya (app.engines.balance_sheet.**/app.engines.income_statement.**/
app.engines.common.** ile birlikte) yalnızca pandas/pypdf/stdlib'e
bağımlıdır -- sqlalchemy/fastapi/pydantic'e DEĞİL, bu yüzden
test_engine_registry_unit.py'deki AYNI sandbox-only `importlib` stub
tekniğiyle (bkz. tests/README.md) gerçekten çalıştırılabilir.

Sentetik fixture'lar tests/data/synthetic/generate_fixtures.py'de üretilir
ve GERÇEKTEN üretilip commit edilmiştir (soffice --headless ile) -- tamamen
kurgusal, hiçbir gerçek mükellef/mali veri içermez.
"""

import pathlib
from decimal import Decimal

from app.engines.balance_sheet.analyzer import (
    compute_horizontal_analysis as bs_compute_horizontal_analysis,
    compute_preliminary_structural_ratios,
    compute_vertical_analysis as bs_compute_vertical_analysis,
    compute_working_capital,
)
from app.engines.balance_sheet.extractor import (
    BalanceSheetExtractionError,
    extract_balance_sheet_facts,
)
from app.engines.balance_sheet.service import analyze_balance_sheet
from app.engines.common.canonical_facts import BalanceSheetFacts, IncomeStatementFacts
from app.engines.common.reconciliation import (
    MATERIAL_RECONCILIATION_DIFFERENCE,
    RECONCILIATION_DIFFERENCE,
    compare_with_tolerance,
)
from app.engines.common.trial_balance_fallback import (
    extract_balance_sheet_facts_from_trial_balance,
    extract_income_statement_facts_from_trial_balance,
)
from app.engines.income_statement.analyzer import resolve_ebit, resolve_ebitda
from app.engines.income_statement.extractor import (
    IncomeStatementExtractionError,
    extract_income_statement_facts,
)
from app.engines.income_statement.service import analyze_income_statement
from app.models.enums import AnalysisStatus, SourceMode
from app.trial_balance.service import analyze_trial_balance


FIXTURES_DIR = pathlib.Path(__file__).parent / "data" / "synthetic"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


# --- Extractor: doğrudan .xlsx yolu ----------------------------------------


def test_balance_sheet_extractor_reads_labeled_xlsx():
    content = _read_fixture("synthetic_balance_sheet_direct.xlsx")
    facts, warnings = extract_balance_sheet_facts(content, "synthetic_balance_sheet_direct.xlsx")

    assert facts.current_assets == Decimal("150000.0")
    assert facts.non_current_assets == Decimal("90000.0")
    assert facts.total_assets == Decimal("240000.0")
    assert facts.short_term_liabilities == Decimal("70000.0")
    assert facts.long_term_liabilities == Decimal("50000.0")
    assert facts.equity == Decimal("120000.0")
    assert facts.total_liabilities_and_equity == Decimal("240000.0")
    assert facts.cash_and_equivalents == Decimal("60000.0")
    assert facts.inventory == Decimal("35000.0")
    assert facts.trade_receivables == Decimal("45000.0")
    assert facts.trade_payables == Decimal("30000.0")
    assert warnings == []


def test_balance_sheet_extractor_reads_labeled_pdf():
    content = _read_fixture("synthetic_balance_sheet_labeled.pdf")
    facts, warnings = extract_balance_sheet_facts(content, "synthetic_balance_sheet_labeled.pdf")

    assert facts.total_assets == Decimal("180000.00")
    assert facts.total_liabilities_and_equity == Decimal("180000.00")
    assert facts.cash_and_equivalents == Decimal("45000.00")
    assert warnings == []


def test_balance_sheet_extractor_rejects_unsupported_kind():
    try:
        extract_balance_sheet_facts(b"not a real file", "belge.txt")
    except BalanceSheetExtractionError:
        pass
    else:
        raise AssertionError("Desteklenmeyen tür icin BalanceSheetExtractionError bekleniyordu.")


def test_balance_sheet_extractor_sanitizes_garbage_xlsx():
    # .xlsx uzantili ama gecerli bir Excel dosyasi olmayan icerik -- ham
    # exception/traceback ASLA disari sizmamali (onaylanan Milestone 4.2
    # karari #6).
    try:
        extract_balance_sheet_facts(b"bu gecerli bir excel dosyasi degil", "bozuk.xlsx")
    except BalanceSheetExtractionError as error:
        assert "Excel" in str(error) or "bozuk" in str(error).lower()
    else:
        raise AssertionError("Bozuk xlsx icin BalanceSheetExtractionError bekleniyordu.")


def test_income_statement_extractor_reads_labeled_xlsx_without_ebit():
    content = _read_fixture("synthetic_income_statement_direct.xlsx")
    facts, warnings = extract_income_statement_facts(content, "synthetic_income_statement_direct.xlsx")

    assert facts.net_sales == Decimal("575000.0")
    assert facts.gross_profit == Decimal("225000.0")
    assert facts.operating_profit == Decimal("122000.0")
    assert facts.net_profit == Decimal("81000.0")
    # EBIT satırı BİLEREK bu fixture'da yok.
    assert facts.ebit is None
    assert facts.depreciation_and_amortization is None
    assert warnings == []


def test_income_statement_extractor_reads_labeled_xlsx_with_ebit():
    content = _read_fixture("synthetic_income_statement_with_ebit.xlsx")
    facts, warnings = extract_income_statement_facts(content, "synthetic_income_statement_with_ebit.xlsx")

    assert facts.ebit == Decimal("125000.0")
    assert facts.depreciation_and_amortization == Decimal("18000.0")
    # operating_profit AYRI kalmalı, ebit'e sessizce eşitlenmemeli.
    assert facts.operating_profit == Decimal("122000.0")
    assert facts.operating_profit != facts.ebit
    assert warnings == []


def test_income_statement_extractor_reads_labeled_pdf_with_ebit():
    content = _read_fixture("synthetic_income_statement_with_ebit_labeled.pdf")
    facts, warnings = extract_income_statement_facts(
        content, "synthetic_income_statement_with_ebit_labeled.pdf"
    )

    assert facts.ebit == Decimal("103000.00")
    assert facts.depreciation_and_amortization == Decimal("14000.00")
    assert facts.operating_profit == Decimal("100000.00")
    assert warnings == []


def test_income_statement_extractor_rejects_unsupported_kind():
    try:
        extract_income_statement_facts(b"not a real file", "belge.txt")
    except IncomeStatementExtractionError:
        pass
    else:
        raise AssertionError("Desteklenmeyen tur icin IncomeStatementExtractionError bekleniyordu.")


# --- EBIT/EBITDA politikası (onaylanan Milestone 4.2 kararı #3) -----------


def test_resolve_ebit_returns_none_and_warning_when_not_reported():
    facts = IncomeStatementFacts(operating_profit=Decimal("100000"))
    ebit, provenance, warning = resolve_ebit(facts)

    assert ebit is None
    assert provenance.calculated is False
    assert warning is not None
    assert warning["code"] == "EBIT_NOT_DETERMINABLE"


def test_resolve_ebit_never_silently_copies_operating_profit():
    facts = IncomeStatementFacts(operating_profit=Decimal("100000"))
    ebit, _, _ = resolve_ebit(facts)
    assert ebit != facts.operating_profit
    assert ebit is None


def test_resolve_ebit_returns_direct_value_when_reported():
    facts = IncomeStatementFacts(operating_profit=Decimal("100000"), ebit=Decimal("103000"))
    ebit, provenance, warning = resolve_ebit(facts)

    assert ebit == Decimal("103000")
    assert provenance.calculated is True
    assert warning is None


def test_resolve_ebitda_requires_both_ebit_and_da():
    ebitda, provenance = resolve_ebitda(Decimal("100000"), None)
    assert ebitda is None
    assert provenance.calculated is False
    assert "depreciation_and_amortization" in provenance.missing_inputs

    ebitda2, provenance2 = resolve_ebitda(None, Decimal("18000"))
    assert ebitda2 is None
    assert provenance2.calculated is False

    ebitda3, provenance3 = resolve_ebitda(Decimal("103000"), Decimal("14000"))
    assert ebitda3 == Decimal("117000")
    assert provenance3.calculated is True


# --- trial_balance fallback: eksik veri asla sıfır değildir ---------------


def test_trial_balance_fallback_balance_sheet_zero_vs_missing_disambiguation():
    # account_details BOŞ (hiç hesap yok) olan bir bölüm -- defaultdict
    # 0 döndürse bile None olarak yorumlanmalı (eksik veri != sıfır).
    tb_result = {
        "financial_statements": {
            "balance_sheet": {
                "current_assets": 0,
                "non_current_assets": 50000,
                "total_assets": 50000,
                "short_term_liabilities": 0,
                "long_term_liabilities": 0,
                "equity": 50000,
                "total_liabilities_and_equity": 50000,
                "account_details": {
                    "current_assets": [],  # gerçekten hiç hesap yok
                    "non_current_assets": [{"account_code": "252", "amount": 50000}],
                    "equity": [{"account_code": "500", "amount": 50000}],
                },
            }
        }
    }

    facts = extract_balance_sheet_facts_from_trial_balance(tb_result)

    assert facts.current_assets is None  # 0 degil -- hic hesap yoktu
    assert facts.non_current_assets == Decimal("50000")
    assert facts.short_term_liabilities is None
    assert facts.equity == Decimal("50000")
    # 4.2'nin yeni alanları trial_balance fallback'te HER ZAMAN None.
    assert facts.cash_and_equivalents is None
    assert facts.inventory is None
    assert facts.trade_receivables is None
    assert facts.trade_payables is None


def test_trial_balance_fallback_income_statement_zero_vs_missing_disambiguation():
    tb_result = {
        "financial_statements": {
            "income_statement": {
                "gross_sales": 100000,
                "sales_deductions": 0,
                "net_sales": 100000,
                "cost_of_sales": 60000,
                "gross_profit": 40000,
                "operating_expenses": 0,
                "other_operating_income": 0,
                "other_operating_expenses": 0,
                "operating_profit": 40000,
                "financing_expenses": 0,
                "account_details": {
                    "gross_sales": [{"account_code": "600", "amount": 100000}],
                    "sales_deductions": [],  # gercekten hic hesap yok
                    "cost_of_sales": [{"account_code": "620", "amount": 60000}],
                    "operating_expenses": [],
                    "financing_expenses": [],
                },
            }
        }
    }

    facts = extract_income_statement_facts_from_trial_balance(tb_result)

    assert facts.gross_sales == Decimal("100000")
    assert facts.sales_deductions is None  # 0 degil -- hic hesap yoktu
    assert facts.operating_expenses is None
    assert facts.financing_expenses is None
    assert facts.ebit is None
    assert facts.ebitda is None
    assert facts.depreciation_and_amortization is None


def test_trial_balance_fallback_uses_real_engine_output():
    # Sentetik gerçek mizan -- app.trial_balance.service.analyze_trial_balance
    # gerçekten çalıştırılıp çıktısı fallback mapper'a verilir (mock DEĞİL).
    content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")
    tb_result = analyze_trial_balance(content=content, filename="mizan.xlsx")

    bs_facts = extract_balance_sheet_facts_from_trial_balance(tb_result)
    assert bs_facts.current_assets == Decimal("150000.0")
    assert bs_facts.total_assets == Decimal("240000.0")

    is_facts = extract_income_statement_facts_from_trial_balance(tb_result)
    assert is_facts.net_sales == Decimal("575000.0")
    assert is_facts.operating_profit == Decimal("122000.0")


# --- Reconciliation: iki-seviyeli tolerans ---------------------------------


def test_reconciliation_within_rounding_tolerance_produces_no_finding():
    finding = compare_with_tolerance(
        compared_field="total_assets",
        direct_value=Decimal("10000.50"),
        reference_value=Decimal("10000.00"),
    )
    assert finding is None  # fark 0.50, rounding tolerance = max(1, 1) = 1


def test_reconciliation_between_rounding_and_material_is_warning():
    finding = compare_with_tolerance(
        compared_field="total_assets",
        direct_value=Decimal("10050.00"),
        reference_value=Decimal("10000.00"),
    )
    assert finding is not None
    assert finding.severity == "warning"
    assert finding.code == RECONCILIATION_DIFFERENCE
    assert finding.applied_rounding_tolerance == Decimal("1.00")
    assert finding.applied_material_threshold == Decimal("100.00")  # 10000*0.005=50 < 100 taban


def test_reconciliation_above_material_threshold_is_high():
    finding = compare_with_tolerance(
        compared_field="total_assets",
        direct_value=Decimal("10200.00"),
        reference_value=Decimal("10000.00"),
    )
    assert finding is not None
    assert finding.severity == "high"
    assert finding.code == MATERIAL_RECONCILIATION_DIFFERENCE


def test_reconciliation_zero_reference_skips_percentage_but_still_evaluates():
    finding = compare_with_tolerance(
        compared_field="equity", direct_value=Decimal("5"), reference_value=Decimal("0")
    )
    assert finding is not None
    assert finding.percentage_difference is None  # sifira bolme YOK
    assert finding.severity == "warning"


def test_reconciliation_none_value_never_compared():
    assert compare_with_tolerance(
        compared_field="equity", direct_value=None, reference_value=Decimal("100")
    ) is None
    assert compare_with_tolerance(
        compared_field="equity", direct_value=Decimal("100"), reference_value=None
    ) is None


# --- Analyzer: vertical/horizontal/working capital/structural ratios ------


def test_balance_sheet_vertical_analysis_uses_total_assets_as_base():
    facts = BalanceSheetFacts(current_assets=Decimal("50000"), total_assets=Decimal("200000"))
    result, provenance = bs_compute_vertical_analysis(facts)
    assert result["current_assets_pct_of_total_assets"] == Decimal("25.00")
    assert any(p.calculated for p in provenance)


def test_balance_sheet_horizontal_analysis_requires_prior_period():
    current = BalanceSheetFacts(total_assets=Decimal("200000"))
    result, provenance = bs_compute_horizontal_analysis(current, None)
    assert result["total_assets_change_pct"] is None
    entry = next(p for p in provenance if p.metric == "total_assets_change_pct")
    assert entry.calculated is False
    assert "prior_period" in entry.missing_inputs


def test_balance_sheet_working_capital_requires_both_components():
    facts = BalanceSheetFacts(current_assets=Decimal("150000"), short_term_liabilities=Decimal("70000"))
    result, _ = compute_working_capital(facts)
    assert result["net_working_capital"] == Decimal("80000")


def test_balance_sheet_structural_ratios_missing_input_is_none():
    facts = BalanceSheetFacts(current_assets=Decimal("150000"))  # short_term_liabilities eksik
    result, provenance = compute_preliminary_structural_ratios(facts)
    assert result["current_ratio"] is None
    entry = next(p for p in provenance if p.metric == "current_ratio")
    assert entry.calculated is False


# --- Service (full orchestration): direct + reconciliation + fallback -----


def test_analyze_balance_sheet_direct_with_clean_reconciliation():
    tb_content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")
    tb_result = analyze_trial_balance(content=tb_content, filename="mizan.xlsx")

    bs_content = _read_fixture("synthetic_balance_sheet_direct.xlsx")
    outcome = analyze_balance_sheet(
        content=bs_content, filename="bilanco.xlsx", trial_balance_result=tb_result
    )

    assert outcome.status == AnalysisStatus.COMPLETED
    assert outcome.source_mode == SourceMode.DIRECT_DOCUMENT
    assert outcome.trial_balance_usage == "reconciliation_reference"
    assert outcome.result_json["reconciliation"]["performed"] is True
    assert outcome.result_json["reconciliation"]["within_tolerance"] is True
    assert outcome.result_json["reconciliation"]["material_difference"] is False
    assert outcome.result_json["reconciliation"]["differences"] == []
    assert outcome.result_json["engine"] == "balance_sheet"
    for key in (
        "engine", "engine_version", "analysis_type", "source_mode", "facts",
        "vertical_analysis", "horizontal_analysis", "reconciliation",
        "warnings", "missing_fields", "calculation_provenance",
    ):
        assert key in outcome.result_json, key


def test_analyze_balance_sheet_flags_material_mismatch():
    # BİLEREK ilgisiz iki fixture -- trial_balance'ın küçük rakamları ile
    # doğrudan belgenin büyük rakamları arasında MATERIAL fark bekleniyor.
    tb_content = _read_fixture("synthetic_trial_balance.xlsx")
    tb_result = analyze_trial_balance(content=tb_content, filename="mizan.xlsx")

    bs_content = _read_fixture("synthetic_balance_sheet_direct.xlsx")
    outcome = analyze_balance_sheet(
        content=bs_content, filename="bilanco.xlsx", trial_balance_result=tb_result
    )

    assert outcome.result_json["reconciliation"]["performed"] is True
    assert outcome.result_json["reconciliation"]["within_tolerance"] is False
    assert outcome.result_json["reconciliation"]["material_difference"] is True
    codes = {f["code"] for f in outcome.result_json["reconciliation"]["differences"]}
    assert MATERIAL_RECONCILIATION_DIFFERENCE in codes
    # direct_document HER ZAMAN authoritative -- trial_balance degeri
    # facts'i SESSIZCE degistirmez.
    assert outcome.result_json["facts"]["current_assets"] == 150000.0


def test_analyze_balance_sheet_falls_back_to_trial_balance_when_no_content():
    tb_content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")
    tb_result = analyze_trial_balance(content=tb_content, filename="mizan.xlsx")

    outcome = analyze_balance_sheet(content=None, filename=None, trial_balance_result=tb_result)

    assert outcome.status == AnalysisStatus.COMPLETED
    assert outcome.source_mode == SourceMode.TRIAL_BALANCE_DERIVED
    assert outcome.trial_balance_usage == "fallback_source"
    assert outcome.result_json["facts"]["current_assets"] == 150000.0
    # Fallback yolunda 4.2'nin yeni alt-kalem alanları HER ZAMAN None.
    assert outcome.result_json["facts"]["cash_and_equivalents"] is None
    # Fallback = TEK kaynak kullanıldı, bu bir reconciliation DEĞİL.
    reconciliation = outcome.result_json["reconciliation"]
    assert reconciliation["performed"] is False
    assert reconciliation["within_tolerance"] is None
    assert reconciliation["material_difference"] is None
    assert reconciliation["differences"] == []


def test_analyze_balance_sheet_fails_cleanly_without_any_source():
    outcome = analyze_balance_sheet(content=None, filename=None, trial_balance_result=None)
    assert outcome.status == AnalysisStatus.FAILED
    assert outcome.result_json is None
    assert outcome.error_message is not None


def test_analyze_income_statement_direct_with_clean_reconciliation_and_ebit_warning():
    tb_content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")
    tb_result = analyze_trial_balance(content=tb_content, filename="mizan.xlsx")

    is_content = _read_fixture("synthetic_income_statement_direct.xlsx")
    outcome = analyze_income_statement(
        content=is_content, filename="gelir_tablosu.xlsx", trial_balance_result=tb_result
    )

    assert outcome.status == AnalysisStatus.COMPLETED
    assert outcome.result_json["reconciliation"]["performed"] is True
    assert outcome.result_json["reconciliation"]["within_tolerance"] is True
    assert outcome.result_json["reconciliation"]["material_difference"] is False
    assert outcome.result_json["facts"]["operating_profit"] == 122000.0
    assert outcome.result_json["facts"]["ebit"] is None
    assert "ebit" in outcome.result_json["missing_fields"]
    assert any(w["code"] == "EBIT_NOT_DETERMINABLE" for w in outcome.result_json["warnings"])
    # operating_profit ve ebit result_json'da AYRI, ayrıştırılabilir alanlar.
    assert outcome.result_json["facts"]["operating_profit"] != outcome.result_json["facts"]["ebit"]


def test_analyze_income_statement_with_ebit_computes_ebitda():
    is_content = _read_fixture("synthetic_income_statement_with_ebit.xlsx")
    outcome = analyze_income_statement(content=is_content, filename="x.xlsx", trial_balance_result=None)

    assert outcome.result_json["facts"]["ebit"] == 125000.0
    assert outcome.result_json["facts"]["ebitda"] == 125000.0 + 18000.0
    assert not any(w["code"] == "EBIT_NOT_DETERMINABLE" for w in outcome.result_json["warnings"])


def test_analyze_income_statement_provenance_contract():
    is_content = _read_fixture("synthetic_income_statement_direct.xlsx")
    outcome = analyze_income_statement(content=is_content, filename="x.xlsx", trial_balance_result=None)

    provenance = outcome.result_json["calculation_provenance"]
    assert len(provenance) > 0
    for entry in provenance:
        assert set(entry.keys()) == {"metric", "formula", "input_fields", "missing_inputs", "calculated"}
        if not entry["calculated"]:
            assert len(entry["missing_inputs"]) > 0
