"""
Milestone 4.1 (Analysis Foundation): yeni motorların (Balance Sheet/Income
Statement/Cash Flow/Tax Return -- Milestone 4.2/4.4/4.5) extractor <->
analyzer arası ortak, kanonik veri şekilleri.

Bu dosya YALNIZCA ŞEKİL tanımlar -- hiçbir dosya ayrıştırma, hesap
sınıflandırma veya hesaplama mantığı İÇERMEZ. Gerçek extractor'lar
(ham dosya -> bu şekiller) Milestone 4.2+'da yazılacak.

Bu yapılar KALICI DB TABLOSU DEĞİLDİR -- yalnızca bellek içi, extractor'dan
analyzer'a geçiş biçimleridir (tıpkı app/trial_balance/models.py::
TrialBalanceAccount'ın kalıcı olmaması gibi). Kalıcı olan tek şey, sonuçta
üretilen FinancialAnalysisResult.result_json'dur.

KURAL (onaylanan Milestone 4.1 kararı #6): tüm parasal alanlar `Decimal | None`
-- asla `float`. Eksik veri `None`'dır, `0` DEĞİLDİR; `0` yalnızca kaynak
belgede GERÇEKTEN sıfır olduğunda kullanılır (docs/FINOS_ARCHITECTURE_V1.md
bölüm 2.3 ile birebir tutarlı). JSON serialization sınırındaki kontrollü
Decimal->float dönüşümü için bkz. app.engines.common.ratio_formulas::
decimal_to_json_safe -- bu dönüşüm YALNIZCA dışa (result_json'a) yazarken
yapılır, bu dataclass'ların içi HER ZAMAN Decimal kalır.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class BalanceSheetFacts:
    """Bir dönemin bilanço kalemlerinin kanonik özeti (Milestone 4.2'de
    doldurulacak). Alan adları app.engines.common.chart_of_accounts.
    BALANCE_SHEET_SECTIONS değerleriyle bilinçli olarak birebir eşleşir."""

    current_assets: Decimal | None = None
    non_current_assets: Decimal | None = None
    total_assets: Decimal | None = None
    short_term_liabilities: Decimal | None = None
    long_term_liabilities: Decimal | None = None
    equity: Decimal | None = None
    total_liabilities_and_equity: Decimal | None = None
    # Hesap kodu -> [{"account_code", "account_name", "amount"}] -- Decimal
    # olarak, ayrıntı satırları için isteğe bağlı kırılım. Milestone 4.2+
    # extractor'ları doldurur; None kalması "ayrıntı yok" anlamına gelir,
    # "sıfır" anlamına GELMEZ.
    account_details: dict[str, list[dict]] | None = None


@dataclass
class IncomeStatementFacts:
    """Bir dönemin gelir tablosu kalemlerinin kanonik özeti (Milestone 4.2'de
    doldurulacak). Alan adları app.engines.common.chart_of_accounts.
    INCOME_STATEMENT_SECTIONS değerleriyle bilinçli olarak birebir eşleşir,
    artı EBIT/EBITDA gibi türetilmiş kalemler."""

    gross_sales: Decimal | None = None
    sales_deductions: Decimal | None = None
    net_sales: Decimal | None = None
    cost_of_sales: Decimal | None = None
    gross_profit: Decimal | None = None
    operating_expenses: Decimal | None = None
    other_operating_income: Decimal | None = None
    other_operating_expenses: Decimal | None = None
    operating_profit: Decimal | None = None
    # Amortisman/itfa gideri -- EBITDA'nın EBIT'e eklenen kısmı. Extractor
    # tarafından ayrıca tespit edilmesi gerekir (Tekdüzen'de gider
    # hesaplarının içine gömülü); None ise EBITDA hesaplanamaz (0 varsayılmaz).
    depreciation_and_amortization: Decimal | None = None
    ebit: Decimal | None = None
    ebitda: Decimal | None = None
    financing_expenses: Decimal | None = None
    extraordinary_income: Decimal | None = None
    extraordinary_expenses: Decimal | None = None
    profit_before_tax: Decimal | None = None
    net_profit: Decimal | None = None
    account_details: dict[str, list[dict]] | None = None


@dataclass
class CashFlowFacts:
    """Bir dönemin nakit akış kalemlerinin kanonik özeti (Milestone 4.4'te
    doldurulacak) -- hem doğrudan yüklenen bir nakit akış tablosundan hem de
    iki ardışık dönemin bilançosu + gelir tablosundan dolaylı türetimle
    (indirect method) üretilebilir; bu dataclass her iki üretim yolu için de
    aynı hedef şekildir."""

    operating_cash_flow: Decimal | None = None
    investing_cash_flow: Decimal | None = None
    financing_cash_flow: Decimal | None = None
    net_change_in_cash: Decimal | None = None
    free_cash_flow: Decimal | None = None
    beginning_cash_balance: Decimal | None = None
    ending_cash_balance: Decimal | None = None


@dataclass
class TaxReturnFacts:
    """Bir dönemin vergi beyannamesi kalemlerinin kanonik özeti (Milestone
    4.5'te doldurulacak) -- Geçici/Kurumlar Vergisi Beyannamesi ortak
    şekli. accounting_profit alanı, mutabakat (muhasebe kârı vs vergi
    matrahı) için İLGİLİ dönemin Income Statement/trial_balance sonucundan
    ayrıca okunur; bu dataclass'ın kendisi yalnızca BEYANNAMEDEN çıkarılan
    kalemleri tutar."""

    tax_base: Decimal | None = None  # vergi matrahı
    declared_tax: Decimal | None = None
    accounting_profit: Decimal | None = None  # mutabakat referansı (opsiyonel)
    permanent_differences: Decimal | None = None
    temporary_differences: Decimal | None = None
    disallowed_expenses_total: Decimal | None = None  # KKEG toplamı
    exemptions_and_deductions: Decimal | None = None
