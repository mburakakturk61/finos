"""
trial_balance motorunun (app/trial_balance/**) Milestone 2 / Adım 1
kapsamında bozulmadığını doğrulayan regresyon testi.

Bilinçli olarak gerçek tests/data/generic/2024_detay_mizan.xlsx dosyasını
KULLANMAZ -- o dosya gerçek, anonimleştirilmemiş banka hesap verisi içerir
(bkz. tests/README.md). Bunun yerine bellek içinde küçük, tamamen kurgusal,
denk (debit == credit) bir mizan üretir; hiçbir yeni ikili fixture
commitlenmez.

Bu dosya yalnızca pandas'a bağımlıdır (fastapi/sqlalchemy'ye değil), bu
yüzden trial_balance motoru üzerinde app katmanının geri kalanından
bağımsız olarak çalıştırılabilir.
"""

from decimal import Decimal
from io import BytesIO

import pandas as pd

from app.trial_balance.service import analyze_trial_balance


def _build_synthetic_trial_balance_bytes() -> bytes:
    """
    Tamamen kurgusal, başabaş (net kâr = 0) bir mizan üretir. Rakamlar
    öyle seçildi ki hem toplam borç/alacak dengede olsun hem de üretilen
    bilanço denk çıksın -- gerçek bir müşteri verisine hiçbir benzerliği
    yoktur.
    """

    rows = [
        {"Hesap Kodu": "100", "Hesap Adı": "KASA", "Borç Tutarı": 50000, "Alacak Tutarı": 0},
        {"Hesap Kodu": "120", "Hesap Adı": "ALICILAR", "Borç Tutarı": 30000, "Alacak Tutarı": 0},
        {"Hesap Kodu": "153", "Hesap Adı": "TİCARİ MALLAR", "Borç Tutarı": 20000, "Alacak Tutarı": 0},
        {"Hesap Kodu": "320", "Hesap Adı": "SATICILAR", "Borç Tutarı": 0, "Alacak Tutarı": 25000},
        {"Hesap Kodu": "500", "Hesap Adı": "SERMAYE", "Borç Tutarı": 0, "Alacak Tutarı": 75000},
        {"Hesap Kodu": "600", "Hesap Adı": "YURTİÇİ SATIŞLAR", "Borç Tutarı": 0, "Alacak Tutarı": 40000},
        {"Hesap Kodu": "621", "Hesap Adı": "SATILAN TİCARİ MALLAR MALİYETİ", "Borç Tutarı": 20000, "Alacak Tutarı": 0},
        {"Hesap Kodu": "631", "Hesap Adı": "PAZARLAMA SATIŞ DAĞITIM GİDERLERİ", "Borç Tutarı": 20000, "Alacak Tutarı": 0},
    ]

    dataframe = pd.DataFrame(rows)
    buffer = BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def test_trial_balance_engine_still_validates_and_computes():
    content = _build_synthetic_trial_balance_bytes()

    result = analyze_trial_balance(content=content, filename="synthetic_test.xlsx")

    assert result["status"] == "VALID"
    assert result["row_count"] == 8
    assert result["detected_columns"]["account_code"] == "Hesap Kodu"
    assert result["detected_columns"]["debit"] == "Borç Tutarı"
    assert result["detected_columns"]["credit"] == "Alacak Tutarı"

    total_debit = Decimal(str(result["totals"]["total_debit"]))
    total_credit = Decimal(str(result["totals"]["total_credit"]))
    assert total_debit == total_credit == Decimal("140000.00")
    assert result["totals"]["balanced"] is True

    balance_sheet = result["financial_statements"]["balance_sheet"]
    assert balance_sheet["balanced"] is True
    assert balance_sheet["current_assets"] == 100000.0
    assert balance_sheet["total_assets"] == 100000.0
    assert balance_sheet["short_term_liabilities"] == 25000.0
    assert balance_sheet["equity"] == 75000.0

    income_statement = result["financial_statements"]["income_statement"]
    assert income_statement["net_sales"] == 40000.0
    assert income_statement["cost_of_sales"] == 20000.0
    assert income_statement["gross_profit"] == 20000.0
    assert income_statement["operating_profit"] == 0.0
    assert income_statement["calculated_profit_before_tax"] == 0.0

    ratios = result["financial_ratios"]
    assert ratios["liquidity"]["current_ratio"] == 4.0
    assert ratios["profitability"]["gross_profit_margin"] == 0.5

    assert result["errors"] == []
