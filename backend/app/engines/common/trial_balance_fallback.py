"""
Milestone 4.2: `app.trial_balance.service.analyze_trial_balance`'ın ürettiği
ve DB'ye kaydedilmiş `result_json`'un `BalanceSheetFacts`/`IncomeStatementFacts`
kanonik şekline eşlenmesi (Milestone 4 mimari kararı B.2/Alternatif 3, hibrit
kaynak modeli).

BU DOSYA `app/trial_balance/**`'TEN HİÇBİR ŞEY IMPORT ETMEZ -- yalnızca
ZATEN DB'DE KAYITLI, sözleşmesi (`financial_statements.balance_sheet`/
`income_statement` alt sözlükleri) `tests/README.md` ve
`app/trial_balance/service.py`'nin dış sözleşmesi olarak sabit kabul edilen
bir `dict`'i okur. Bu bir KOD bağımlılığı değil, VERİ bağımlılığıdır.

ÖNEMLİ İNCELİK -- "gerçekten sıfır" ile "hesap yok" ayrımı: trial_balance
motorunun `build_balance_sheet`/`build_income_statement` fonksiyonları
`defaultdict(lambda: ZERO)` kullanır -- bir bölüme (ör. `equity`) hiç hesap
düşmediğinde de sonuç `0` olur, GERÇEKTEN sıfır bir özkaynak ile ayırt
edilemez. Bu modül, her bölümün `account_details` altındaki (aynı adlı)
listesinin BOŞ olup olmadığına bakarak bu ikisini ayırt eder: liste boşsa
o alan `None` bırakılır (0 fabrikasyon edilmez); liste doluysa hesaplanan
değer (0 dahil) olduğu gibi taşınır.
"""

from decimal import Decimal
from typing import Any

from app.engines.common.canonical_facts import BalanceSheetFacts, IncomeStatementFacts


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _section_value(
    section_dict: dict[str, Any],
    account_details: dict[str, list],
    field_name: str,
) -> Decimal | None:
    entries = (account_details or {}).get(field_name) or []
    if not entries:
        return None
    return _to_decimal(section_dict.get(field_name))


_BS_SECTION_FIELDS = [
    "current_assets",
    "non_current_assets",
    "short_term_liabilities",
    "long_term_liabilities",
    "equity",
]

_IS_SECTION_FIELDS = [
    "gross_sales",
    "sales_deductions",
    "cost_of_sales",
    "operating_expenses",
    "other_operating_income",
    "other_operating_expenses",
    "financing_expenses",
    "extraordinary_income",
    "extraordinary_expenses",
]

# net_sales/gross_profit/operating_profit/calculated_profit_before_tax
# trial_balance motorunda TÜRETİLMİŞ (bölüm toplamlarının farkı/toplamı)
# alanlardır, kendi `account_details` girişleri YOKTUR -- bileşenleri
# (ör. net_sales için gross_sales ve sales_deductions) doluysa bu türetilmiş
# değer de anlamlıdır.
_IS_DERIVED_FIELDS = {
    "net_sales": ("gross_sales", "sales_deductions"),
    "gross_profit": ("gross_sales", "sales_deductions", "cost_of_sales"),
    "operating_profit": (
        "gross_sales",
        "sales_deductions",
        "cost_of_sales",
        "operating_expenses",
        "other_operating_income",
        "other_operating_expenses",
    ),
}


def extract_balance_sheet_facts_from_trial_balance(
    trial_balance_result: dict[str, Any] | None,
) -> BalanceSheetFacts:
    balance_sheet = (
        (trial_balance_result or {})
        .get("financial_statements", {})
        .get("balance_sheet", {})
    ) or {}
    account_details = balance_sheet.get("account_details") or {}

    kwargs: dict[str, Decimal | None] = {
        field_name: _section_value(balance_sheet, account_details, field_name)
        for field_name in _BS_SECTION_FIELDS
    }

    # total_assets/total_liabilities_and_equity: bileşenlerinden BİRİ bile
    # None ise toplam da None -- kısmi toplam (bilinmeyen bir bileşeni 0
    # sayarak) asla üretilmez.
    kwargs["total_assets"] = (
        kwargs["current_assets"] + kwargs["non_current_assets"]
        if kwargs["current_assets"] is not None and kwargs["non_current_assets"] is not None
        else None
    )
    kwargs["total_liabilities_and_equity"] = (
        kwargs["short_term_liabilities"] + kwargs["long_term_liabilities"] + kwargs["equity"]
        if kwargs["short_term_liabilities"] is not None
        and kwargs["long_term_liabilities"] is not None
        and kwargs["equity"] is not None
        else None
    )

    # cash_and_equivalents/inventory/trade_receivables/trade_payables:
    # trial_balance motoru bu düzeyde ayrıştırma yapmıyor -- HER ZAMAN None
    # (onaylanan Milestone 4.2 kararı #1).
    return BalanceSheetFacts(**kwargs)


def extract_income_statement_facts_from_trial_balance(
    trial_balance_result: dict[str, Any] | None,
) -> IncomeStatementFacts:
    income_statement = (
        (trial_balance_result or {})
        .get("financial_statements", {})
        .get("income_statement", {})
    ) or {}
    account_details = income_statement.get("account_details") or {}

    kwargs: dict[str, Decimal | None] = {
        field_name: _section_value(income_statement, account_details, field_name)
        for field_name in _IS_SECTION_FIELDS
    }

    for derived_field, components in _IS_DERIVED_FIELDS.items():
        if all(kwargs[component] is not None for component in components):
            kwargs[derived_field] = _to_decimal(income_statement.get(derived_field))
        else:
            kwargs[derived_field] = None

    kwargs["profit_before_tax"] = (
        _to_decimal(income_statement.get("calculated_profit_before_tax"))
        if kwargs["operating_profit"] is not None and kwargs["financing_expenses"] is not None
        else None
    )

    # net_profit: yalnızca 69x (dönem kâr/zarar) hesapları GERÇEKTEN
    # raporlanmışsa doldurulur -- bkz. modül docstring'i.
    period_profit_entries = account_details.get("period_profit_loss_accounts") or []
    kwargs["net_profit"] = (
        _to_decimal(income_statement.get("reported_period_profit_loss"))
        if period_profit_entries
        else None
    )

    # ebit / ebitda / depreciation_and_amortization: trial_balance motoru
    # bunları HİÇ üretmiyor -- HER ZAMAN None (onaylanan Milestone 4.2
    # kararı #3 -- operating_profit asla ebit'e sessizce kopyalanmaz).
    kwargs["ebit"] = None
    kwargs["ebitda"] = None
    kwargs["depreciation_and_amortization"] = None

    return IncomeStatementFacts(**kwargs)
