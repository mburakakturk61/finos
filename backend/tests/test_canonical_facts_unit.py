"""
app.engines.common.canonical_facts içindeki kanonik veri şekillerinin
(BalanceSheetFacts/IncomeStatementFacts/CashFlowFacts/TaxReturnFacts) hem
TAM hem KISMİ doldurulabildiğini, ve tüm parasal alanların `Decimal | None`
olduğunu (float DEĞİL) doğrular (Milestone 4.1 -- Analysis Foundation,
onaylanan karar #6).

Bu dosya yalnızca stdlib'e bağımlıdır (sqlalchemy/fastapi/pydantic'e DEĞİL).
"""

import dataclasses
from decimal import Decimal

from app.engines.common.canonical_facts import (
    BalanceSheetFacts,
    CashFlowFacts,
    IncomeStatementFacts,
    TaxReturnFacts,
)


ALL_FACT_CLASSES = (BalanceSheetFacts, IncomeStatementFacts, CashFlowFacts, TaxReturnFacts)


def _monetary_field_names(instance) -> list[str]:
    return [
        f.name
        for f in dataclasses.fields(instance)
        if f.name not in {"account_details"}
    ]


def test_all_fact_classes_default_to_none():
    for cls in ALL_FACT_CLASSES:
        instance = cls()
        for name in _monetary_field_names(instance):
            assert getattr(instance, name) is None, f"{cls.__name__}.{name}"


def test_balance_sheet_facts_accepts_decimal_and_partial_fill():
    facts = BalanceSheetFacts(
        current_assets=Decimal("1000.50"),
        total_assets=Decimal("5000.00"),
    )
    assert facts.current_assets == Decimal("1000.50")
    assert isinstance(facts.total_assets, Decimal)
    # Doldurulmayan alan None kalmalı -- 0 değil.
    assert facts.non_current_assets is None
    assert facts.equity is None


def test_income_statement_facts_zero_is_preserved_not_confused_with_missing():
    # 0 GERÇEK bir değer olmalı (eksik veriyle karıştırılmamalı) --
    # onaylanan Milestone 4.1 kararı #6: "sıfır yalnızca kaynak belgede
    # gerçekten sıfır varsa kullanılmalı".
    facts = IncomeStatementFacts(gross_sales=Decimal("0"))
    assert facts.gross_sales == Decimal("0")
    assert facts.gross_sales is not None
    # Ayrı, doldurulmamış bir alan hâlâ None olmalı.
    assert facts.net_sales is None


def test_cash_flow_facts_partial_fill():
    facts = CashFlowFacts(operating_cash_flow=Decimal("12345.67"))
    assert facts.operating_cash_flow == Decimal("12345.67")
    assert facts.free_cash_flow is None


def test_tax_return_facts_partial_fill():
    facts = TaxReturnFacts(tax_base=Decimal("100000.00"), declared_tax=Decimal("25000.00"))
    assert facts.tax_base == Decimal("100000.00")
    assert facts.declared_tax == Decimal("25000.00")
    assert facts.accounting_profit is None
    assert facts.temporary_differences is None


def test_balance_sheet_facts_milestone_4_2_additive_fields():
    # Milestone 4.2 (onaylanan karar #1): cash_and_equivalents/inventory/
    # trade_receivables/trade_payables eklendi -- additive, hiçbir zaman
    # 0'a varsayılanmaz, direkt extractor yalnızca tespit edebildiğini
    # doldurur, trial_balance fallback bunları HER ZAMAN None bırakır (bkz.
    # test_engine_balance_income_statement_unit.py).
    facts = BalanceSheetFacts(
        cash_and_equivalents=Decimal("1000.00"),
        trade_receivables=Decimal("2000.00"),
    )
    assert facts.cash_and_equivalents == Decimal("1000.00")
    assert facts.trade_receivables == Decimal("2000.00")
    assert facts.inventory is None
    assert facts.trade_payables is None


def test_no_monetary_field_declares_float():
    for cls in ALL_FACT_CLASSES:
        instance = cls()
        for f in dataclasses.fields(instance):
            if f.name == "account_details":
                continue
            type_str = str(f.type)
            assert "float" not in type_str, (
                f"{cls.__name__}.{f.name} float iceriyor gibi gorunuyor: {type_str}"
            )
            assert "Decimal" in type_str, (
                f"{cls.__name__}.{f.name} Decimal beyan etmiyor: {type_str}"
            )
