"""
Milestone 4.2: resmi bilanço/gelir tablosu standart Türkçe kalem etiketleri
-> canonical facts alan adı eşlemesi. `app.classification.document_classifier`
içindeki `PDF_KEYWORD_RULES`/`FILENAME_KEYWORD_RULES` ile AYNI desen
(anahtar-kelime -> hedef listesi), bağımsız bir uygulama -- hem etiketli
Excel satırlarını (`app.engines.balance_sheet/income_statement.extractor`)
hem metin tabanlı PDF satırlarını (`app.engines.common.label_line_parser`
üzerinden) ayrıştırmak için ortak olarak kullanılır.

Her kural (`anahtar_kelime`, `canonical_alan`) çiftidir; `anahtar_kelime`
`app.engines.common.text_normalize.normalize_text` ile normalize edilmiş
metne karşı `in` ile aranır. Liste sırası ÖNEMLİDİR -- daha spesifik/uzun
kalıplar, daha genel olanlardan ÖNCE gelir (ör. "donem net kari" "donem
kari"dan önce), aksi halde genel kalıp erken eşleşip yanlış alana yazar.
"""

BALANCE_SHEET_LABEL_RULES: list[tuple[str, str]] = [
    ("hazir degerler", "cash_and_equivalents"),
    ("kasa ve bankalar", "cash_and_equivalents"),
    ("nakit ve nakit benzerleri", "cash_and_equivalents"),
    ("stoklar", "inventory"),
    ("ticari alacaklar", "trade_receivables"),
    ("ticari borclar", "trade_payables"),
    ("donen varliklar toplami", "current_assets"),
    ("i donen varliklar", "current_assets"),
    ("donen varliklar", "current_assets"),
    ("duran varliklar toplami", "non_current_assets"),
    ("ii duran varliklar", "non_current_assets"),
    ("duran varliklar", "non_current_assets"),
    ("aktif toplami", "total_assets"),
    ("varliklar toplami", "total_assets"),
    ("kisa vadeli yabanci kaynaklar toplami", "short_term_liabilities"),
    ("kisa vadeli yabanci kaynaklar", "short_term_liabilities"),
    ("uzun vadeli yabanci kaynaklar toplami", "long_term_liabilities"),
    ("uzun vadeli yabanci kaynaklar", "long_term_liabilities"),
    ("ozkaynaklar toplami", "equity"),
    ("oz kaynaklar toplami", "equity"),
    ("ozkaynaklar", "equity"),
    ("oz kaynaklar", "equity"),
    ("pasif toplami", "total_liabilities_and_equity"),
    ("kaynaklar toplami", "total_liabilities_and_equity"),
]


INCOME_STATEMENT_LABEL_RULES: list[tuple[str, str]] = [
    ("brut satislar", "gross_sales"),
    ("satis indirimleri", "sales_deductions"),
    ("net satislar", "net_sales"),
    ("satislarin maliyeti", "cost_of_sales"),
    ("satilan mallar maliyeti", "cost_of_sales"),
    ("brut satis kari", "gross_profit"),
    ("brut kar", "gross_profit"),
    ("faaliyet giderleri", "operating_expenses"),
    ("diger faaliyetlerden olagan gelir ve karlar", "other_operating_income"),
    ("diger faaliyetlerden gelirler", "other_operating_income"),
    ("diger faaliyetlerden olagan gider ve zararlar", "other_operating_expenses"),
    ("diger faaliyetlerden giderler", "other_operating_expenses"),
    ("faaliyet kari", "operating_profit"),
    ("finansman giderleri", "financing_expenses"),
    ("olagandisi gelir ve karlar", "extraordinary_income"),
    ("olagandisi gelirler", "extraordinary_income"),
    ("olagandisi gider ve zararlar", "extraordinary_expenses"),
    ("olagandisi giderler", "extraordinary_expenses"),
    ("faiz ve vergi oncesi kar", "ebit"),
    ("amortisman ve itfa giderleri", "depreciation_and_amortization"),
    ("amortisman giderleri", "depreciation_and_amortization"),
    ("donem net kari", "net_profit"),
    ("donem net zarari", "net_profit"),
    ("donem kari", "profit_before_tax"),
    ("vergi oncesi kar", "profit_before_tax"),
]
