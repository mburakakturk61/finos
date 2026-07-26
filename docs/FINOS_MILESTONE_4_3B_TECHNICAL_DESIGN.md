# FINOS Milestone 4.3B — Core Financial Ratios: Teknik Tasarım Dokümanı

**Durum:** Tasarım ONAYLANDI (2. tur, 8 düzeltme kararıyla birlikte — Bölüm 11/12). Implementasyon bu revizyondan sonra, Bölüm 9'daki 10 adımlık plana göre başlıyor.

**Önceki durum:** Milestone 4.3A tamamlandı, commit edildi (`b278a1d`), test durumu: sandbox'ta gerçekten çalıştırılan 106 test + Docker/Postgres'e bağımlı diğer testlerle birlikte kullanıcının bildirdiği toplam 220 test yeşil.

**Kapsam:** `docs/FINOS_MILESTONE_4_3_FINANCIAL_RATIO_ENGINE_DESIGN.md` Bölüm O'daki "Milestone 4.3B — Core Financial Ratios" fazı: **Likidite, Kârlılık, Borçluluk, Faaliyet, Verimlilik, Büyüme, Nakit oranları** (7 kategori). Katalogdaki diğer 7 kategori (Yatırım, Piyasa, Bankacılık, IFRS, Risk, Sermaye Yapısı, Çalışma Sermayesi) bu fazın kapsamı **DIŞINDA** — bkz. Bölüm 10.

---

## Bölüm 1 — Mevcut Mimarinin Özeti (4.3A'dan Devralınan)

Aşağıdaki özet, bu tasarımdan önce yapılan tam kod okumasına dayanır (`app/engines/common/ratio_formulas.py`, `ratio_derived_facts.py`, `app/engines/financial_ratios/{adapter,service}.py`, `app/engines/protocol.py`, `app/engines/registry.py`, `app/engines/balance_sheet/analyzer.py`, `app/engines/income_statement/analyzer.py` — hepsi güncel hâliyle okundu).

### 1.1 Registry yapısı

`RATIO_REGISTRY: dict[str, RatioFormulaMetadata]` — modül-seviyesi, süreç ömrü boyunca bir kez doldurulan sözlük. `register_ratio_formula()` iki şeyi doğrular: (a) `key` daha önce kayıtlı değil, (b) `calculation_strategy` `CALCULATION_STRATEGIES`'te GERÇEKTEN var — ikisi de erken (`ValueError`), kayıt anında. Bugün **9 kayıt** var: `current_ratio`, `working_capital_ratio`, `net_working_capital` (liquidity); `debt_ratio`, `equity_ratio`, `debt_to_equity` (leverage); `gross_profit_margin`, `operating_profit_margin`, `net_profit_margin` (profitability).

`RatioFormulaMetadata` alanları: `key`, `category`, `display_name_tr`, `unit` (`"ratio"|"percentage"|"days"|"currency"`), `calculation_strategy`, `numerator_fields`/`denominator_fields` (yalnızca `sum_division`), `addend_fields`/`subtrahend_fields` (yalnızca `linear_combination`), `zero_denominator_status` (varsayılan `UNDEFINED_ZERO_DENOMINATOR`), `quantize_exp` (varsayılan `"0.0001"`).

### 1.2 Strategy dispatch modeli

`CALCULATION_STRATEGIES: dict[str, Callable[[RatioFormulaMetadata, dict[str, Decimal|None]], ComputationOutcome]]` — **kapalı küme**, bugün yalnızca iki anahtar: `"sum_division"` (`compute_sum_division` — alanları toplar, böler, `unit="percentage"` ise quantize SONRASI ×100) ve `"linear_combination"` (`compute_linear_combination` — alanları toplar/çıkarır, quantize YOK). Her ikisi de `try/except (InvalidOperation, OverflowError, ArithmeticError)` ile sarılı — hiçbir ham Decimal exception dışarı sızmaz, kontrollü `NOT_CALCULABLE` + tanılama warning'ine dönüşür. Eval/exec/dinamik expression **yok** ve olmayacak.

### 1.3 ComputationOutcome / ComputationStatus

`ComputationOutcome(status, value, missing_inputs=(), warnings=(), reliability="not_calculable", provenance=None)`. `ComputationStatus`: `CALCULATED`, `MISSING_INPUT` (bir alan `None`), `UNDEFINED_ZERO_DENOMINATOR` (payda gerçekten 0, iş anlamı tanımsız), `NO_OBLIGATION` (payda gerçekten 0, iş anlamı olumlu/nötr — yalnızca `current_ratio`/`working_capital_ratio` bugün bunu kullanıyor), `NOT_APPLICABLE` (henüz HİÇ tetiklenmiyor — 4.3A'nın 9 oranının hepsi her modda yapısal olarak uygulanabilir), `NOT_CALCULABLE` (kayıtsız key/desteklenmeyen strateji/beklenmeyen sayısal hata).

### 1.4 Provenance

`ProvenanceEntry` (5 orijinal alan + 3 additive: `source_analysis_result_ids`, `reliability`, `rounding_applied`). `provenance_to_dict()` **DEĞİŞMEDİ** (hâlâ 5 anahtar — BS/IS'in dış sözleşmesi), `provenance_to_dict_extended()` 8 anahtar üretir, yalnızca Ratio Engine'in kendi `result_json`'unda kullanılıyor. `compute_registered_ratio(key, facts, *, reliability="high")` TEK giriş noktası — `RATIO_REGISTRY[key]`'i okur, ilgili strateji fonksiyonunu çağırır, `ProvenanceEntry`'yi AYNI çağrıda üretir (`_build_derivation_rule` formül metnini `numerator_fields`/`denominator_fields`/`addend_fields`/`subtrahend_fields`'ten OTOMATİK türetir).

### 1.5 Adapter

`FinancialRatioEngineAdapter` (`app/engines/financial_ratios/adapter.py`): `analysis_type=FINANCIAL_RATIOS`, `requires_content=False`. `context.balance_sheet_result`/`context.income_statement_result` ikisi de `None` ise `FAILED`; aksi halde `analyze_financial_ratios()`'u çağırıp `COMPLETED` döner. `sources=[]` HER ZAMAN boş (source-tracking henüz yok). Registry'de **yalnızca** `get_engine_for_analysis_type` üzerinden kayıtlı — `DetectedDocumentType`/`DocumentType` yönlendirme tablolarına eklenmedi. Hiçbir API/bulk-upload/recompute akışına bağlı değil.

### 1.6 Analyzer entegrasyonu (BS/IS)

`balance_sheet/analyzer.py::compute_preliminary_structural_ratios`/`compute_working_capital` ve `income_statement/analyzer.py::compute_margins` (yalnızca 3/5 alanı: `gross_margin_pct`/`operating_margin_pct`/`net_margin_pct`) artık `compute_registered_ratio()`'ya yönlendiriliyor — `result_json` şekli (anahtar adları) DEĞİŞMEDİ, sayısal değerler Milestone 4.2 ile bit-bir aynı. `income_statement/analyzer.py`'de `ebit_margin_pct`/`ebitda_margin_pct` HÂLÂ yerel `safe_divide` ile hesaplanıyor (RATIO_REGISTRY'de kayıtlı değiller) — bu, Bölüm 8'de ele alınan bir "kısmi migrasyon" durumu.

### 1.7 `ratio_derived_facts.py` (bugünkü hâli)

Yalnızca iki fonksiyon: `compute_total_liabilities(short_term, long_term)` ve `compute_days_in_period(*, start_date, end_date, months_covered)` (gerçek tarih farkı birincil, `months_covered*30` yalnızca açık düşük-güven fallback, warning ile). `average_*` yok — 4.3A'nın hiçbir oranı ihtiyaç duymuyordu. **2. tur onayla (karar #8) `compute_days_in_period`'in birincil formülünün `(end_date - start_date).days` (EXCLUSIVE, `+1` YOK) olduğu tespit edildi — bu, 4.3B'de `+1` (INCLUSIVE) olarak düzeltilecek, bkz. Bölüm 4.1.**

### 1.8 `EngineRunContext` (bugünkü hâli)

`company_id`, `period_id`, `trial_balance_result`, `trial_balance_analysis_result_id`, `trial_balance_pending_in_batch`, `balance_sheet_result`, `income_statement_result`, `prior_period_balance_sheet_result`, `prior_period_income_statement_result` — SON İKİSİ (`prior_period_*`) **zaten var** ama hiçbir oran tarafından tüketilmiyor (4.3A'da yalnızca altyapı olarak eklendi). 4.3B bunları **ilk kez gerçekten kullanacak**.

### 1.9 `analyze_financial_ratios` orkestrasyonu (bugünkü hâli)

`_CATEGORY_RATIO_KEYS` sabit sözlüğü (yalnızca 3 kategori × 3 oran), `_build_facts_dict()` (BS+IS `result_json["facts"]`'ını `json_safe_to_decimal` ile Decimal'e çevirip TEK düz sözlükte birleştirir, `total_liabilities`'i enjekte eder), kategori-seviyesi `status` (`calculated`/`partial`/`not_calculable`) hesaplama mantığı, `missing_categories` listesi. Bu orkestrasyon 4.3B'de **önemli ölçüde genişleyecek** (Bölüm 5/9).

---

## Bölüm 2 — 4.3B Kapsamındaki Finansal Oranlar (Tam Liste)

Toplam **48 yeni oran** (9 mevcut + 48 = 4.3B sonunda 57 kayıtlı oran — 2. tur onayla `effective_tax_rate`'in eklenmesiyle 47'den 48'e YÜKSELTİLDİ, bkz. Bölüm 2.2). Her tablo bir kategoriye aittir; sütunlar: **Anahtar | Ad | Formül | Alanlar | Derived Facts | Strategy | Status Davranışı | Edge Case'ler | Reliability**.

### 2.1 Likidite (4 yeni: quick_ratio, cash_ratio, defensive_interval_ratio, working_capital_to_total_assets)

| Anahtar | Ad | Formül | Alanlar | Derived Facts | Strategy | Status Davranışı | Edge Case'ler | Reliability |
|---|---|---|---|---|---|---|---|---|
| `quick_ratio` | Asit-Test Oranı | `(current_assets - inventory) / short_term_liabilities` | `current_assets`, `inventory`, `short_term_liabilities` | `quick_assets = current_assets - inventory` (yeni) | `sum_division` (numerator=`quick_assets`) | `short_term_liabilities=0` → `no_obligation`; `inventory`/`current_assets` None → `missing_input` | `trial_balance_derived` modda `inventory` HER ZAMAN None — bkz. Bölüm 6 (NOT_APPLICABLE tartışması) | high (yalnızca direct BS) |
| `cash_ratio` | Nakit Oranı | `cash_and_equivalents / short_term_liabilities` | `cash_and_equivalents`, `short_term_liabilities` | yok | `sum_division` | `short_term_liabilities=0` → `no_obligation` | aynı NOT_APPLICABLE tartışması | high (yalnızca direct) |
| `defensive_interval_ratio` | Savunma Aralığı Oranı (gün) | `(cash_and_equivalents + trade_receivables) / (operating_expenses + cost_of_sales) * days_in_period` | `cash_and_equivalents`, `trade_receivables`, `operating_expenses`, `cost_of_sales` | `days_in_period` (MEVCUT, 4.3A'da kuruldu ama tüketilmiyordu — İLK gerçek tüketici) | **YENİ `scaled_division`** (bkz. Bölüm 3.4 — 2. tur onayla ERTELENMEDİ, gerçekten implemente edilecek) | `(operating_expenses+cost_of_sales)=0` → `undefined_zero_denominator`; `days_in_period` hesaplanamazsa (tarihler yoksa fallback, hiçbir zaman `None` değil) `scale_field` daima dolu | Formül üç adımlı (topla, böl, günle çarp) — `scaled_division` stratejisiyle TEK adımda ifade edilir | high (yalnızca direct BS+herhangi IS) |
| `working_capital_to_total_assets` | İşletme Sermayesi / Toplam Aktif | `net_working_capital / total_assets` | `total_assets` | `net_working_capital` (zaten RATIO_REGISTRY'de kayıtlı bir oran — `depends_on_ratios` ile enjekte edilecek, bkz. Bölüm 3.2) | `sum_division` | `total_assets=0` → `undefined_zero_denominator` | `net_working_capital` `MISSING_INPUT` ise bu oran da `missing_input` (enjekte edilen değer None) | high/medium |

**Not (`defensive_interval_ratio`, 2. TUR ONAYLA GÜNCELLENDİ):** Kullanıcı kararı #1 gereği bu oran ERTELENMEYECEK. Kapalı dispatch modeline yeni, genel amaçlı, saf bir **`scaled_division`** stratejisi eklenir — sözleşmesi Bölüm 3.4'te tanımlanmıştır: `(sum(numerator_fields) / sum(denominator_fields)) * scale_field`. Eval/exec/expression parser YOK; yalnızca açıkça kayıtlı metadata alanlarını okur, mevcut `try/except` Decimal/status güvenlik desenini miras alır.

### 2.2 Kârlılık (8 yeni: ebit_margin, ebitda_margin, pretax_profit_margin, return_on_assets, return_on_equity, return_on_capital_employed, effective_tax_rate, return_on_invested_capital)

**2. TUR ONAYLA GÜNCELLENDİ (karar #7):** `return_on_invested_capital`'ın "her zaman not_calculable" tasarımı ÇELİŞKİLİYDİ — kanuni vergi oranı asla varsayılamaz ama `effective_tax_rate`, mevcut IS alanlarından (`profit_before_tax`, `net_profit`) DETERMİNİSTİK olarak türetilebilir. Bu nedenle `effective_tax_rate` KENDİSİ destekleyici bir `RATIO_REGISTRY` kaydı olarak eklenir (Bölüm 5.3 kuralına göre RATIO_REGISTRY'de — çünkü kullanıcıya doğrudan anlamlı, bağımsız bir metriktir, yalnızca bir ara büyüklük değildir) ve `return_on_invested_capital` buna `depends_on_ratios=("effective_tax_rate",)` ile bağlanır. Bu, Kârlılık kategorisinin oran sayısını 7'den **8'e** çıkarır.

| Anahtar | Ad | Formül | Alanlar | Derived Facts | Strategy | Status Davranışı | Edge Case'ler | Reliability |
|---|---|---|---|---|---|---|---|---|
| `ebit_margin` | EBIT Marjı | `ebit / net_sales` | `ebit`, `net_sales` | yok | `sum_division` | `ebit=None` (rapor edilmemiş) → `missing_input`; `net_sales=0` → `undefined_zero_denominator` | `ebit` yalnızca IS `facts` içinde varsa (resolve_ebit v1 politikası) dolu | high |
| `ebitda_margin` | EBITDA Marjı | `ebitda / net_sales` | `ebitda`, `net_sales` | yok | `sum_division` | aynı | `ebitda`, `ebit`+`depreciation_and_amortization` ikisi de doluysa var | high |
| `pretax_profit_margin` | Vergi Öncesi Kâr Marjı | `profit_before_tax / net_sales` | `profit_before_tax`, `net_sales` | yok | `sum_division` | `net_sales=0` → `undefined_zero_denominator` | — | high |
| `return_on_assets` | Aktif Kârlılığı (ROA) | `net_profit / average_total_assets` | `net_profit` | `average_total_assets` (YENİ, bkz. Bölüm 4) | `sum_division` | `average_total_assets=0` → `undefined_zero_denominator`; önceki dönem yoksa `average_total_assets` = dönem-sonu (reliability düşer) | Ortalama/dönem-sonu ayrımı Bölüm 4'te | high (ortalama) / medium (dönem-sonu) |
| `return_on_equity` | Özkaynak Kârlılığı (ROE) | `net_profit / average_equity` | `net_profit` | `average_equity` (YENİ) | `sum_division` | aynı desen | negatif özkaynak riski (Bölüm 8) | high/medium |
| `return_on_capital_employed` | ROCE | `ebit / (total_assets - short_term_liabilities)` | `ebit`, `total_assets`, `short_term_liabilities` | `capital_employed = total_assets - short_term_liabilities` (YENİ, `linear_combination`, kendisi de RATIO_REGISTRY'ye kaydedilecek bir "yardımcı oran" mı yoksa saf derived-fact mi -- bkz. Bölüm 5.3) | `sum_division` (numerator=`ebit`, denominator=`capital_employed`) | `capital_employed=0` → `undefined_zero_denominator` | — | high |
| `effective_tax_rate` | Efektif Vergi Oranı | `(profit_before_tax - net_profit) / profit_before_tax` | `profit_before_tax`, `net_profit` | yok | `sum_division` (numerator=`linear_combination` sonucu enjekte edilmiş `tax_expense = profit_before_tax - net_profit`, bkz. not) | `profit_before_tax=None` veya `net_profit=None` → `missing_input`; `profit_before_tax=0` → `undefined_zero_denominator`; sonuç `<0` veya `>1` çıkarsa DEĞER GİZLENMEZ, açık `warning` + `reliability="low"` notu eklenir | Kanuni vergi oranı ASLA varsayılmaz; yalnızca gerçek IS verisinden türetilir | high (normal aralıkta) / low (aralık dışı, ama görünür) |
| `return_on_invested_capital` | ROIC | `ebit * (1 - effective_tax_rate) / (equity + long_term_liabilities)` | `ebit`, `equity`, `long_term_liabilities` | `capital_employed` benzeri `invested_capital = equity + long_term_liabilities` (YENİ, `ratio_derived_facts.py`) | `sum_division`, numerator ve denominator'dan biri `effective_tax_rate`'in ENJEKTE EDİLMİŞ değerine bağlı (`depends_on_ratios=("effective_tax_rate",)`) | `effective_tax_rate` hesaplanamazsa (`missing_input`/`undefined_zero_denominator`) ROIC de `missing_input`; `invested_capital=0` → `undefined_zero_denominator` | `effective_tax_rate`'in aralık-dışı warning'i ROIC'e de YANSITILIR (provenance zinciri üzerinden) | effective_tax_rate ile aynı |

**Not (`effective_tax_rate`'in `tax_expense` ara değeri):** `(profit_before_tax - net_profit)` ifadesi, TEK bir `sum_division` çağrısına doğrudan beslenemeyeceği için (numerator iki alanın FARKI, sum_division yalnızca TOPLAMI destekler), bu ara değer `ratio_derived_facts.py`'de `compute_tax_expense(profit_before_tax, net_profit)` olarak (Bölüm 5.3 kuralına göre saf bir ara büyüklük, kullanıcıya doğrudan sunulmuyor) türetilip facts dict'e enjekte edilir; `effective_tax_rate`'in `sum_division` kaydı `numerator_fields=("tax_expense",)`, `denominator_fields=("profit_before_tax",)` okur.

### 2.3 Borçluluk (6 yeni + 1 not_calculable: long_term_debt_to_equity, short_term_debt_ratio, financial_leverage_multiplier, interest_coverage_ratio, ebitda_coverage_ratio, debt_to_ebitda, fixed_charge_coverage)

| Anahtar | Ad | Formül | Alanlar | Derived Facts | Strategy | Status Davranışı | Edge Case'ler | Reliability |
|---|---|---|---|---|---|---|---|---|
| `long_term_debt_to_equity` | Uzun Vadeli Borç/Özkaynak | `long_term_liabilities / equity` | `long_term_liabilities`, `equity` | yok | `sum_division` | `equity=0` → `undefined_zero_denominator` (yüksek önem) | — | high |
| `short_term_debt_ratio` | Kısa Vadeli Borç Oranı | `short_term_liabilities / total_liabilities` | `short_term_liabilities` | `total_liabilities` (MEVCUT) | `sum_division` | `total_liabilities=0` → **`no_obligation`, `value=null`** (2. tur onayla KESİNLEŞTİ, karar #2 — sahte 0/Infinity ÜRETİLMEZ) | Şirketin hiç borcu yoksa iş anlamı "borç yok" (olumlu), ama oranın SAYISAL değeri `null` kalır — `NO_OBLIGATION` durumunda değer üretmeme ilkesi `current_ratio` ile TUTARLI | high |
| `financial_leverage_multiplier` | Finansal Kaldıraç Çarpanı | `total_assets / equity` | `total_assets`, `equity` | yok | `sum_division` | `equity=0` → `undefined_zero_denominator` | — | high |
| `interest_coverage_ratio` | Faiz Karşılama Oranı (EBIT) | `ebit / financing_expenses` | `ebit`, `financing_expenses` | yok | `sum_division` | `financing_expenses=0` → **finansman gideri yok, iyi bir durum** → `no_obligation` (yeni atama) | Faiz gideri sıfırsa "karşılama" kavramı anlamsız değil, "gerek yok" anlamına gelir | high |
| `ebitda_coverage_ratio` | EBITDA ile Faiz Karşılama | `ebitda / financing_expenses` | `ebitda`, `financing_expenses` | yok | `sum_division` | `financing_expenses=0` → `no_obligation` | aynı | high |
| `debt_to_ebitda` | Borç/EBITDA | `total_liabilities / ebitda` | `ebitda` | `total_liabilities` (MEVCUT) | `sum_division` | `ebitda=0` → `undefined_zero_denominator`; `ebitda=None` → `missing_input` | Negatif EBITDA'da oran negatif çıkar — yorumsal risk (Bölüm 8) | medium (ebitda genelde daha az güvenilir çünkü D&A ayrıştırması gerektirir) |
| `fixed_charge_coverage` | Sabit Ödeme Karşılama Oranı | `(ebit + lease_payments) / (financing_expenses + lease_payments)` | `lease_payments` (YOK) | — | — | **HER ZAMAN `not_calculable`** | kiralama gideri ayrıştırması hiçbir motorda yok | not_calculable |

### 2.4 Faaliyet / Devir Hızları (10 yeni: hepsi)

| Anahtar | Ad | Formül | Alanlar | Derived Facts | Strategy | Status Davranışı | Edge Case'ler | Reliability |
|---|---|---|---|---|---|---|---|---|
| `inventory_turnover` | Stok Devir Hızı | `cost_of_sales / average_inventory` | `cost_of_sales` | `average_inventory` (YENİ) | `sum_division` | `average_inventory=0` → `undefined_zero_denominator` (stok sıfırsa devir tanımsız/sonsuz) | Yalnızca direct BS (`inventory` yalnızca orada var) | high/medium |
| `receivables_turnover` | Alacak Devir Hızı | `net_sales / average_trade_receivables` | `net_sales` | `average_trade_receivables` (YENİ) | `sum_division` | aynı desen | yalnızca direct BS | high/medium |
| `payables_turnover` | Borç Devir Hızı | `cost_of_sales / average_trade_payables` | `cost_of_sales` | `average_trade_payables` (YENİ) | `sum_division` | aynı desen | yalnızca direct BS | high/medium |
| `asset_turnover` | Aktif Devir Hızı | `net_sales / average_total_assets` | `net_sales` | `average_total_assets` (YENİ, ROA ile PAYLAŞILAN) | `sum_division` | `average_total_assets=0` → `undefined_zero_denominator` (pratikte imkansız ama formül olarak ele alınmalı) | — | high/medium |
| `fixed_asset_turnover` | Duran Varlık Devir Hızı | `net_sales / non_current_assets` | `net_sales`, `non_current_assets` | yok (dönem-sonu, ortalama DEĞİL — katalog kararı) | `sum_division` | `non_current_assets=0` → `undefined_zero_denominator` | — | high |
| `working_capital_turnover` | İşletme Sermayesi Devir Hızı | `net_sales / net_working_capital` | `net_sales` | `net_working_capital` (MEVCUT RATIO_REGISTRY kaydı — `depends_on_ratios`) | `sum_division` | `net_working_capital=0` → `undefined_zero_denominator`; negatifse oran negatif (yorumsal not) | `net_working_capital` `missing_input`/`no_obligation` ise bu oran da hesaplanamaz | high/medium |
| `days_inventory_outstanding` | Stokta Kalma Süresi (gün) | `days_in_period / inventory_turnover` | — | `days_in_period` (MEVCUT) | `sum_division` (denominator = enjekte edilmiş `inventory_turnover` DEĞERİ, bkz. Bölüm 3.2) | `inventory_turnover` hesaplanamazsa `missing_input`; `inventory_turnover=0`'a asla ulaşılmaz (zaten `undefined` olurdu) | `depends_on_ratios=("inventory_turnover",)` | inventory_turnover ile aynı |
| `days_sales_outstanding` | Alacak Tahsil Süresi (gün) | `days_in_period / receivables_turnover` | — | `days_in_period` | `sum_division` (enjekte edilmiş) | aynı desen | `depends_on_ratios=("receivables_turnover",)` | receivables_turnover ile aynı |
| `days_payables_outstanding` | Borç Ödeme Süresi (gün) | `days_in_period / payables_turnover` | — | `days_in_period` | `sum_division` (enjekte edilmiş) | aynı desen | `depends_on_ratios=("payables_turnover",)` | payables_turnover ile aynı |
| `cash_conversion_cycle` | Nakit Dönüşüm Süresi (gün) | `DIO + DSO - DPO` | — | — | `linear_combination` (addend=`days_inventory_outstanding`,`days_sales_outstanding`; subtrahend=`days_payables_outstanding` — ÜÇÜ DE enjekte edilmiş değer) | Üç bileşenden biri `missing_input` ise tamamı `missing_input` | `depends_on_ratios=("days_inventory_outstanding","days_sales_outstanding","days_payables_outstanding")` | üç bileşenin en düşüğü |

### 2.5 Verimlilik (6 yeni: operating_expense_ratio, cost_of_sales_ratio, overhead_ratio, ebit_to_opex, non_operating_income_dependency, financing_expense_to_sales)

| Anahtar | Ad | Formül | Alanlar | Derived Facts | Strategy | Status Davranışı | Edge Case'ler | Reliability |
|---|---|---|---|---|---|---|---|---|
| `operating_expense_ratio` | Faaliyet Gideri Oranı | `operating_expenses / net_sales` | `operating_expenses`, `net_sales` | yok | `sum_division` | `net_sales=0` → `undefined_zero_denominator` | — | high |
| `cost_of_sales_ratio` | Satışların Maliyeti Oranı | `cost_of_sales / net_sales` | `cost_of_sales`, `net_sales` | yok | `sum_division` | aynı | — | high |
| `overhead_ratio` | Genel Gider Oranı | `(operating_expenses + other_operating_expenses) / net_sales` | `operating_expenses`, `other_operating_expenses`, `net_sales` | yok | `sum_division` (çok-alanlı numerator, MEVCUT desteklenen şekil) | aynı | — | high |
| `ebit_to_opex` | EBIT / Faaliyet Gideri | `ebit / operating_expenses` | `ebit`, `operating_expenses` | yok | `sum_division` | `operating_expenses=0` → nadir ama teorik olarak mümkün, `undefined_zero_denominator` | — | high |
| `non_operating_income_dependency` | Faaliyet Dışı Gelir Bağımlılığı | `other_operating_income / operating_profit` | `other_operating_income`, `operating_profit` | yok | `sum_division` | `operating_profit=0` → `undefined_zero_denominator` | Negatif `operating_profit`'te oran işareti yanıltıcı olabilir (yorumsal not, Bölüm 8) | high |
| `financing_expense_to_sales` | Finansman Gideri / Satış | `financing_expenses / net_sales` | `financing_expenses`, `net_sales` | yok | `sum_division` | `net_sales=0` → `undefined_zero_denominator` | — | high |

*(`asset_utilization_efficiency`/`equity_efficiency`, katalogda `asset_turnover`'a alias olarak işaretlenmişti — 4.3B'de AYRI kayıt AÇILMAYACAK, kategori-gruplama seviyesinde referans verilecek, bkz. Bölüm 5.4.)*

### 2.6 Büyüme (6 yeni + 1 not_calculable: sales_growth, gross_profit_growth, ebitda_growth, net_profit_growth, total_assets_growth, equity_growth, sustainable_growth_rate)

| Anahtar | Ad | Formül | Alanlar | Derived Facts | Strategy | Status Davranışı | Edge Case'ler | Reliability |
|---|---|---|---|---|---|---|---|---|
| `sales_growth` | Satış Büyümesi | `(net_sales - prior_net_sales) / abs(prior_net_sales) * 100` | `net_sales`, `prior_net_sales` (YENİ isimlendirme, bkz. Bölüm 3.3) | yok | **YENİ `growth_rate`** | `prior_net_sales=None` → `missing_input` (önceki dönem hiç yok); `prior_net_sales=0` → `undefined_zero_denominator` (büyüme oranı sıfırdan tanımsız/sonsuz) | Önceki dönem BS/IS sonucu `context.prior_period_*`'ta yoksa TÜM büyüme kategorisi `not_calculable` | high (ikisi de direct) / medium |
| `gross_profit_growth` | Brüt Kâr Büyümesi | aynı desen | `gross_profit`, `prior_gross_profit` | yok | `growth_rate` | aynı | aynı | aynı |
| `ebitda_growth` | EBITDA Büyümesi | aynı desen | `ebitda`, `prior_ebitda` | yok | `growth_rate` | aynı | `ebitda` her iki dönemde de dolu olmalı | aynı |
| `net_profit_growth` | Net Kâr Büyümesi | aynı desen | `net_profit`, `prior_net_profit` | yok | `growth_rate` | aynı | — | aynı |
| `total_assets_growth` | Toplam Aktif Büyümesi | aynı desen | `total_assets`, `prior_total_assets` | yok | `growth_rate` | aynı | — | aynı |
| `equity_growth` | Özkaynak Büyümesi | aynı desen | `equity`, `prior_equity` | yok | `growth_rate` | aynı | Negatif özkaynaktan pozitife geçişte `abs(prior)` işaret kaybını maskeler (Bölüm 8 riski) | aynı |
| `sustainable_growth_rate` | Sürdürülebilir Büyüme Oranı | `ROE * (1 - kâr_dağıtım_oranı)` | `kâr_dağıtım_oranı` (YOK) | `return_on_equity` (MEVCUT) | — | **HER ZAMAN `not_calculable`** | Kâr dağıtım/temettü verisi hiçbir motorda yok — varsayılan (%0 dağıtım) FABRİKE EDİLMEZ | not_calculable |

### 2.7 Nakit Akışı (6 — hepsi `not_calculable`, `engine_dependency="cash_flow"` ile işaretli)

| Anahtar | Ad | Formül | Alanlar | Status Davranışı |
|---|---|---|---|---|
| `operating_cash_flow_margin` | Faaliyet Nakit Akışı Marjı | `operating_cash_flow / net_sales` | `operating_cash_flow` (YOK — `CashFlowFacts`, Milestone 4.4) | **HER ZAMAN `not_calculable`** (2. tur onayla KESİNLEŞTİ, karar #3 — `engine_dependency="cash_flow"` metadata'sı sayesinde `missing_input` DEĞİL) |
| `free_cash_flow_margin` | Serbest Nakit Akışı Marjı | `free_cash_flow / net_sales` | `free_cash_flow` (YOK) | aynı |
| `cash_flow_to_debt` | Nakit Akışı / Toplam Borç | `operating_cash_flow / total_liabilities` | `operating_cash_flow` (YOK) | aynı |
| `cash_return_on_assets` | Nakit Bazlı Aktif Getirisi | `operating_cash_flow / average_total_assets` | `operating_cash_flow` (YOK) | aynı |
| `cash_interest_coverage` | Nakit Bazlı Faiz Karşılama | `operating_cash_flow / financing_expenses` | `operating_cash_flow` (YOK) | aynı |
| `operating_cash_flow_ratio` | Faaliyet Nakit Akışı / Kısa Vadeli Borç | `operating_cash_flow / short_term_liabilities` | `operating_cash_flow` (YOK) | aynı |

**Önemli tasarım notu (2. TUR ONAYLA GÜNCELLENDİ, karar #3):** Bu 6 oranın hepsi `engine_dependency="cash_flow"` metadata alanıyla işaretlenir. Orkestrasyon (`analyze_financial_ratios`), bir oranın `engine_dependency` alanı doluyken ilgili motorun sonucu `EngineRunContext`'te YOKSA (bugün `cash_flow_result` diye bir alan yok), `compute_registered_ratio`'yu HİÇ ÇAĞIRMADAN doğrudan `NOT_CALCULABLE` üretir — "bu motor henüz mevcut değil" ile "veri eksik" ayrımı netleşir. `MISSING_INPUT`, yalnızca ihtiyaç duyulan motor/analiz GERÇEKTEN mevcutken (`cash_flow_result` `EngineRunContext`'te varken) ilgili alan yine de `None` ise kullanılır — bu davranış 4.4'te (Cash Flow Engine implemente edildiğinde) devreye girecektir.

### 2.8 Kategori Özeti (2. TUR ONAYLA YENİDEN HESAPLANDI)

| Kategori | Yeni oran sayısı | Not |
|---|---|---|
| Likidite | 4 | `defensive_interval_ratio` artık `scaled_division` ile gerçekten hesaplanıyor (ertelenmedi) |
| Kârlılık | 8 | `effective_tax_rate` eklendi (karar #7); `return_on_invested_capital` artık koşullu hesaplanabilir |
| Borçluluk | 7 | 6 hesaplanabilir + `fixed_charge_coverage` (her zaman `not_calculable`) |
| Faaliyet | 10 | değişmedi |
| Verimlilik | 6 | değişmedi |
| Büyüme | 7 | 6 hesaplanabilir + `sustainable_growth_rate` (her zaman `not_calculable`) |
| Nakit Akışı | 6 | hepsi `engine_dependency="cash_flow"` ile her zaman `not_calculable` |
| **Toplam yeni** | **48** | |

7 kategori, **48 yeni oran**. Her zaman `not_calculable` kalan oranlar: `fixed_charge_coverage`, `sustainable_growth_rate`, Nakit Akışı'nın 6'sı = **toplam 8 her-zaman-not_calculable** (önceki turdaki 9'dan 8'e düştü çünkü `return_on_invested_capital` artık `effective_tax_rate` girdisi mevcut olduğunda GERÇEKTEN hesaplanabilir). 4.3A'nın 9'u ile birlikte **4.3B sonunda RATIO_REGISTRY'de 9 + 48 = 57 kayıt** olacak.

---

## Bölüm 3 — Calculation Strategy Analizi

### 3.1 `average_balance_division` — GEREKLİ DEĞİL (yeni strateji olarak reddedildi)

**Değerlendirme:** Kullanıcının önerdiği bu strateji, "ortalama bakiye / bir alan" hesaplamasını kapsıyor gibi görünüyor (ör. `inventory_turnover = cost_of_sales / average_inventory`). Ama incelendiğinde, bu **matematiksel olarak `sum_division`'ın kendisidir** — TEK fark, paydanın `average_inventory` gibi ÖNCEDEN TÜRETİLMİŞ bir değer olmasıdır, hesaplama ŞEKLİNİN (topla-böl) kendisi DEĞİŞMEZ. `average_inventory`'yi `ratio_derived_facts.py`'de (tıpkı `total_liabilities` gibi) bir kez türetip facts dict'e enjekte edersek, `sum_division` bunu HİÇBİR DEĞİŞİKLİK OLMADAN tüketebilir.

**Karar: GEREKSİZ.** Yeni bir `"average_balance_division"` stratejisi eklemek, `RATIO_REGISTRY`'nin `numerator_fields`/`denominator_fields` semantiğini gereksiz yere ikiye bölerdi (bir strateji "ham alan", diğeri "türetilmiş ortalama alan" okuyor gibi görünürdü, ama ikisi de aynı `facts.get(field_name)` erişimini yapıyor). Bunun yerine: `ratio_derived_facts.py`'ye `average_inventory`/`average_trade_receivables`/`average_trade_payables`/`average_total_assets`/`average_equity` fonksiyonları eklenir (Bölüm 4), bu değerler facts dict'e `total_liabilities` ile AYNI desende enjekte edilir, ve `sum_division` DEĞİŞMEDEN kullanılır.

### 3.2 `ratio_of_ratio` — GEREKLİ DEĞİL (yeni STRATEJİ olarak), ama YENİ BİR ORKESTRASYON MEKANİZMASI gerekli

**Değerlendirme:** Katalogdaki gerçek ihtiyaçlar (days_inventory_outstanding = days_in_period / inventory_turnover; cash_conversion_cycle = DIO + DSO − DPO; working_capital_to_total_assets = net_working_capital / total_assets) hep "bir oranın ZATEN HESAPLANMIŞ DEĞERİNİ başka bir oranın girdisi olarak kullanma" şeklinde. Bunun için `CALCULATION_STRATEGIES`'e yeni bir dispatch fonksiyonu EKLEMEK yerine (ki bu, "hangi strateji hangi ratio'ları okuyabilir" gibi ikinci bir bağımlılık grafiği daha yaratırdı), **var olan `sum_division`/`linear_combination`'ı DEĞİŞTİRMEDEN** şu ORKESTRASYON kuralını ekliyoruz:

1. `RatioFormulaMetadata`'ya yeni bir alan: `depends_on_ratios: tuple[str, ...] = ()` — bu oranın hangi BAŞKA `RATIO_REGISTRY` anahtarlarının SONUCUNA (facts değil, `ComputationOutcome.value`'suna) ihtiyaç duyduğunu belirtir.
2. `analyze_financial_ratios()` (service.py), tüm kayıtlı oranları **topolojik sırada** (bağımlılığı olmayanlar önce, `depends_on_ratios` dolu olanlar bağımlılıkları hesaplandıktan SONRA) işler.
3. Bir oran hesaplandığında, `ComputationOutcome.value`'su (CALCULATED değilse `None`) facts dict'e **KENDİ `key`'i ile** enjekte edilir (ör. `facts["inventory_turnover"] = outcome.value`).
4. Bağımlı oranın `RatioFormulaMetadata`'sı (ör. `days_inventory_outstanding`) `denominator_fields=("inventory_turnover",)` yazar — `sum_division` bunu SIRADAN bir facts-alanı gibi okur, `inventory_turnover` hesaplanamadıysa (`None`) otomatik olarak `missing_input` üretir.

**Karar: yeni bir `calculation_strategy` DEĞİL, `depends_on_ratios` + topolojik orkestrasyon YETERLİ.** Bu, "kapalı dispatch modeli korunacak" gereksinimini (yalnızca 2 kayıtlı strateji artı Bölüm 3.3'teki tek istisna) en iyi karşılayan çözümdür — strateji SAYISI artmaz, yalnızca `RatioFormulaMetadata`'ya bir alan ve orkestrasyona bir aşama eklenir.

**Kayıp bilgi uyarısı (dürüstçe belirtilmeli):** bağımlı bir oranın `missing_inputs` alanı yalnızca `"inventory_turnover"` ismini gösterir — `inventory_turnover`'ın KENDİSİ neden hesaplanamadı (missing_input mi, undefined_zero_denominator mi) bu seviyede KAYBOLUR. Kullanıcı asıl nedeni `result_json["categories"]["activity"]["ratios"]["inventory_turnover"]` altında AYRICA görebilir (aynı result_json içinde), bu yüzden bilgi tamamen kaybolmaz, yalnızca bağımlı oranın kendi `missing_inputs` alanında tekrarlanmaz. Bu, Bölüm 8'de "provenance bozulması" riski olarak ayrıca değerlendirilmiştir.

### 3.3 `growth_rate` — GERÇEKTEN GEREKLİ, YENİ STRATEJİ ÖNERİLİYOR

**Değerlendirme:** Büyüme oranlarının formülü (`(current - prior) / abs(prior) * 100`) ne `sum_division` (payda üzerinde `abs()` yok, pay üzerinde çıkarma yok) ne `linear_combination` (bölme yok) ile doğrudan ifade edilemez. Alternatif olarak her büyüme oranı için iki ayrı derived-fact (`delta`, `abs_prior`) türetip `sum_division`'a beslemek DE mümkündür ama bu, 6 oran için 12 neredeyse birebir aynı derived-fact fonksiyonu üretir — DRY ilkesini ihlal eder ve `ratio_derived_facts.py`'yi gereksiz şişirir.

**Karar: YENİ bir `"growth_rate"` stratejisi eklensin.** Sözleşme önerisi:

```
RatioFormulaMetadata alanına iki yeni, YALNIZCA growth_rate'in okuduğu alan:
  current_field: str | None = None
  prior_field: str | None = None

compute_growth_rate(metadata, facts) -> ComputationOutcome:
  current = facts.get(metadata.current_field)
  prior = facts.get(metadata.prior_field)
  if current is None or prior is None:
      -> MISSING_INPUT (eksik olan(lar)ı missing_inputs'a yaz)
  if prior == 0:
      -> UNDEFINED_ZERO_DENOMINATOR (büyüme oranı sıfırdan tanımsız/sonsuzdur,
         NO_OBLIGATION DEĞİL -- "büyüme yok" ile "geçen dönem sıfırdı" karıştırılmaz)
  value = (current - prior) / abs(prior) * 100  [quantize(quantize_exp), ROUND_HALF_UP]
  -> CALCULATED
```

Bu, mevcut iki stratejiyle AYNI imzayı (`(metadata, facts) -> ComputationOutcome`) korur, AYNI `try/except` güvenlik desenini miras alır, `CALCULATION_STRATEGIES` sözlüğüne üçüncü bir kapalı, saf fonksiyon olarak eklenir. Eval/exec/expression YOK.

### 3.4 `scaled_division` — 2. TUR ONAYLA KESİNLEŞTİ (karar #1), YENİ STRATEJİ OLARAK EKLENİYOR

**Karar (kullanıcı onayı, artık tartışmaya açık değil):** `defensive_interval_ratio` ERTELENMEYECEK. Kapalı dispatch modeline dördüncü, genel-amaçlı ve saf bir strateji eklenir: **`scaled_division`**.

**Sözleşme:**

```
RatioFormulaMetadata alanına YALNIZCA scaled_division'ın okuduğu ek alan:
  scale_field: str | None = None   -- facts dict'te veya depends_on_ratios
                                        enjeksiyonuyla dolu bir "çarpan" alanı

compute_scaled_division(metadata, facts) -> ComputationOutcome:
  numerator = sum(facts.get(f) for f in metadata.numerator_fields)   [None varsa -> missing_input]
  denominator = sum(facts.get(f) for f in metadata.denominator_fields)
  scale = facts.get(metadata.scale_field)
  if numerator/denominator toplamlarında herhangi bir alan None veya scale None:
      -> MISSING_INPUT
  if denominator == 0:
      -> metadata.zero_denominator_status (varsayılan UNDEFINED_ZERO_DENOMINATOR)
  value = (numerator / denominator) * scale   [quantize(quantize_exp), ROUND_HALF_UP]
  -> CALCULATED
```

Yani sözleşme TAM OLARAK kullanıcının belirttiği gibidir: `(sum(numerator_fields) / sum(denominator_fields)) * scale_field`. `defensive_interval_ratio` için: `numerator_fields=("cash_and_equivalents","trade_receivables")`, `denominator_fields=("operating_expenses","cost_of_sales")`, `scale_field="days_in_period"` (facts dict'e `ratio_derived_facts.compute_days_in_period()`'ten enjekte edilen MEVCUT alan — YENİ bir `depends_on_ratios` gerekmez çünkü `days_in_period` zaten bir "ratio" değil bir "derived fact"tir).

Bu strateji AYNI `try/except (InvalidOperation, OverflowError, ArithmeticError)` güvenlik desenini miras alır; eval/exec/expression parser KESİNLİKLE kullanılmaz; yalnızca açıkça kayıtlı `numerator_fields`/`denominator_fields`/`scale_field` metadata alanlarını okur. `CALCULATION_STRATEGIES` artık **4 kayıtlı strateji** içerir: `sum_division`, `linear_combination`, `growth_rate`, `scaled_division`.

**Genellik notu:** `scaled_division`, katalogda şu an yalnızca `defensive_interval_ratio` tarafından kullanılıyor, ama sözleşmesi TEK-kullanımlık değil — gelecekteki "oran × gün" veya "oran × katsayı" ihtiyaçları (ör. gelecek fazlardaki bazı bankacılık/yatırım oranları) için de kullanılabilir genel bir yetenektir.

### 3.5 `effective_tax_rate` → `return_on_invested_capital` bağımlılığı — YENİ STRATEJİ GEREKMİYOR

**2. tur onayla eklenen (karar #7) `return_on_invested_capital` düzeltmesi, Bölüm 3.2'nin `depends_on_ratios` mekanizmasının DOĞRUDAN bir uygulamasıdır** — yeni bir strateji GEREKTİRMEZ. `effective_tax_rate`, `sum_division` ile normal şekilde hesaplanan SIRADAN bir `RATIO_REGISTRY` kaydıdır (Bölüm 2.2); `return_on_invested_capital`, `depends_on_ratios=("effective_tax_rate",)` ile bu oranın SONUCUNU facts dict'ten okur (`facts["effective_tax_rate"]`), tıpkı `days_inventory_outstanding`'in `inventory_turnover`'ı okuduğu gibi. Tek fark: ROIC'in kendi `sum_division` formülü `(1 - effective_tax_rate)` içerir — bu da `ratio_derived_facts.py`'de `compute_one_minus_effective_tax_rate(effective_tax_rate)` gibi KÜÇÜK bir ara-büyüklük fonksiyonuyla (Bölüm 5.3 kuralına göre, kullanıcıya sunulmayan saf bir ara değer) çözülür; `effective_tax_rate` aralık-dışı (`<0` veya `>1`) olduğunda bu ara fonksiyon değeri GİZLEMEZ, yalnızca üst orana (ROIC) `warning`'i PROVENANCE ZİNCİRİ üzerinden taşır.

---

## Bölüm 4 — `ratio_derived_facts.py` Genişlemesi

**2. TUR ONAYLA GÜNCELLENDİ (karar #4):** Önceki dönemin bulunmaması NORMAL bir iş durumudur (veri kalitesi sorunu DEĞİL) — bu yüzden `average_*` fonksiyonları `warning` ÜRETMEZ. Bunun yerine, HER `average_*` sonucu iki AÇIK alan taşır: `reliability` (`"high"`/`"medium"`) ve `calculation_basis` (`"two_period_average"`/`"ending_balance_fallback"`). Bu ikisi `ComputationOutcome`/provenance'ta HER ZAMAN birlikte görünür — sessiz bir düşüş asla olmaz, yalnızca warning YERİNE açık, yapılandırılmış bir alan çifti kullanılır.

Tüm yeni fonksiyonlar AYNI güncellenmiş desen: `(current, prior) -> (value, reliability, calculation_basis)`:
- İkisi de doluysa: `value=(current+prior)/2`, `reliability="high"`, `calculation_basis="two_period_average"`.
- Yalnızca `current` doluysa (`prior=None`): `value=current`, `reliability="medium"`, `calculation_basis="ending_balance_fallback"` — **warning YOK**, yalnızca bu iki alan.
- İkisi de `None`: `value=None` (çağıran oran `missing_input` olur).

| Fonksiyon | Kullanan oranlar | Üretildiği alanlar | Eksik veri davranışı | Provenance bilgisi |
|---|---|---|---|---|
| `compute_average_inventory(current_inventory, prior_inventory)` | `inventory_turnover` | BS `inventory` (cari + önceki dönem) | yukarıdaki üç dallı desen | `calculation_basis`/`reliability` çifti provenance'ta |
| `compute_average_trade_receivables(current, prior)` | `receivables_turnover` | BS `trade_receivables` | aynı desen | aynı |
| `compute_average_trade_payables(current, prior)` | `payables_turnover` | BS `trade_payables` | aynı desen | aynı |
| `compute_average_total_assets(current, prior)` | `return_on_assets`, `asset_turnover` (PAYLAŞILAN) | BS `total_assets` | aynı desen | aynı |
| `compute_average_equity(current, prior)` | `return_on_equity` | BS `equity` | aynı desen | aynı |
| `compute_average_working_capital(current_nwc, prior_nwc)` | **hiçbir 4.3B oranı tarafından ZORUNLU kullanılmıyor** — katalogdaki `working_capital_turnover` bilinçli olarak dönem-sonu `net_working_capital` kullanıyor (Bölüm 2.4). Bu fonksiyon YİNE DE tasarlanır ama 4.3B'nin HİÇBİR ratio kaydı bunu TÜKETMEYECEK | BS `current_assets`/`short_term_liabilities`'ten türeyen `net_working_capital` (cari+önceki) | aynı desen | aynı, "opsiyonel/kullanılmıyor" notuyla |
| `compute_tax_expense(profit_before_tax, net_profit)` | `effective_tax_rate` | IS `profit_before_tax`/`net_profit` | ikisi de dolu olmalı, `None` ise `None` döner (çağıran oran `missing_input`) | ara büyüklük, kullanıcıya sunulmaz (Bölüm 5.3) |
| `compute_invested_capital(equity, long_term_liabilities)` | `return_on_invested_capital` | BS `equity`/`long_term_liabilities` | ikisi de dolu olmalı | ara büyüklük |

**Genel eksik veri kuralı (tüm `average_*` için ortak):** `context.prior_period_balance_sheet_result`/`prior_period_income_statement_result` (`EngineRunContext`'te ZATEN VAR, 4.3A'dan miras) `None` ise TÜM `average_*` fonksiyonları `ending_balance_fallback`'e düşer — `compute_days_in_period`'in `months_covered*30` fallback'inden BİLİNÇLİ OLARAK FARKLIDIR: o daima warning üretir (tarih eksikliği bir veri kalitesi sorunudur), `average_*` ise hiçbir zaman warning üretmez (önceki dönem yokluğu normal bir iş durumudur) — ayrım artık kesinleşmiştir, açık bir tasarım tercihi değil.

### 4.1 `days_in_period` sözleşmesi — 2. TUR ONAYLA DÜZELTİLDİ (karar #8)

`FinancialPeriod.start_date`/`end_date` KAPSAYICI (inclusive) dönem sınırlarıdır. Bu nedenle birincil formül:

```
days_in_period = (end_date - start_date).days + 1
```

(4.3A'daki orijinal tasarımda `+1` YOKTU — bu, 01.01-31.12 gibi tam-yıl aralıklarında 364 gün üretiyordu, 365/366 DEĞİL. Bu düzeltme, `days_inventory_outstanding` gibi gün-bazlı 4.3B oranlarının doğru çalışması için ZORUNLUDUR.)

Öncelik sırası (DEĞİŞMEDİ, yalnızca birincil formül düzeltildi):
1. `start_date`/`end_date` ikisi de doluysa → `(end_date - start_date).days + 1`, `reliability="high"`, warning YOK.
2. Tarihler yoksa ama `months_covered` doluysa → `months_covered * 30`, `reliability="low"`, **açık warning ZORUNLU** (4.3A'daki gibi, DEĞİŞMEDİ).
3. `end_date < start_date` (geçersiz sıra) → **kontrollü `not_calculable`** + domain warning (`"gecersiz_tarih_sirasi"`) — asla ham `ValueError`/negatif gün sayısı sızdırılmaz.
4. Hiçbiri yoksa → `None`, `missing_input`.

**Zorunlu testler (2. tur onayla eklendi):**
- 01.01.2025 – 31.12.2025 (normal yıl) → **365**.
- 01.01.2024 – 31.12.2024 (artık yıl) → **366**.
- Tarihler yok, yalnızca `months_covered=12` → `360`, `reliability="low"`, warning VAR.
- `end_date < start_date` → `not_calculable` + domain warning, ham exception YOK.
- Çok uzak/geçersiz tarih (ör. `date.min`/`date.max` kombinasyonu) `OverflowError` üretmez, kontrollü `not_calculable`'a düşer.

**`days_in_period`'in tüketicileri:** `defensive_interval_ratio` (`scaled_division.scale_field`) ve `days_inventory_outstanding`/`days_sales_outstanding`/`days_payables_outstanding` (`sum_division.numerator_fields`).

---

## Bölüm 5 — Registry Genişlemesi

### 5.1 `depends_on_ratios: tuple[str, ...] = ()` — GEREKLİ

Bölüm 3.2'nin gerekçesi: `days_inventory_outstanding`/`days_sales_outstanding`/`days_payables_outstanding`/`cash_conversion_cycle`/`working_capital_to_total_assets` bu alanı kullanacak. `register_ratio_formula()`'ya EK bir doğrulama eklenir: `depends_on_ratios`'taki her key, kayıt ANINDA `RATIO_REGISTRY`'de ZATEN var olmalı (bağımlılıklar KENDİLERİNDEN SONRA tanımlanan bir orana işaret edemez — bu, modül-seviyesi kayıt sırasını ZATEN bir topolojik sıralamaya zorlar, ayrı bir "sıralama algoritması" gerektirmez, yalnızca "önce bağımlılığı tanımla" disiplini).

### 5.2 `current_field`/`prior_field: str | None = None` — GEREKLİ (yalnızca `growth_rate` için)

Bölüm 3.3'ün doğal sonucu.

### 5.2b `scale_field: str | None = None` — GEREKLİ (yalnızca `scaled_division` için, 2. tur onayla eklendi)

Bölüm 3.4'ün doğal sonucu — `defensive_interval_ratio`'nun `days_in_period` çarpanını taşır.

### 5.3 "Yardımcı türetilmiş oranlar" (ör. `capital_employed`) — RATIO_REGISTRY'YE Mİ, `ratio_derived_facts.py`'YE Mİ?

**Karar: `ratio_derived_facts.py`'YE.** `capital_employed = total_assets - short_term_liabilities` kullanıcıya doğrudan sunulan bir "oran" DEĞİL, yalnızca `return_on_capital_employed`'in bir ara bileşenidir (tıpkı `total_liabilities` gibi) — `RATIO_REGISTRY`'ye kaydedilirse `result_json["categories"]`'de görünmesi beklenir ki bu yanıltıcıdır (kullanıcıya "capital_employed" diye bir "oran" sunmak anlamsız, bu bir ara büyüklüktür). **Kural netleştirildi:** bir büyüklük (a) birden fazla oranda TEKRAR kullanılıyorsa VE (b) kendisi bağımsız bir "kullanıcıya anlamlı oran" DEĞİLSE → `ratio_derived_facts.py`. Bir büyüklük kullanıcıya doğrudan anlamlı bir oran olarak sunulacaksa (ör. `net_working_capital`, `working_capital_ratio`) → `RATIO_REGISTRY`.

### 5.4 Kategori-içi "alias" oranlar (ör. `asset_utilization_efficiency`) — YENİ KAYIT AÇILMAYACAK

Katalogda "aynı hesap, farklı bağlamda tekrar referans verilir" diye işaretlenen oranlar (`asset_utilization_efficiency`≡`asset_turnover`, `equity_efficiency`≡ yeni ama BENZER değil aslında AYRI bir oran — kontrol edildi, `equity_efficiency = net_sales/equity` GERÇEKTEN farklı bir formül, `asset_turnover`'dan farklı, bu yüzden KENDİ kaydını alacak, alias DEĞİL) — yalnızca gerçek alias'lar (`asset_utilization_efficiency`) `_CATEGORY_RATIO_KEYS`'te (service.py) aynı `key`'e (`asset_turnover`) birden fazla kategoriden REFERANS vererek çözülür, `RATIO_REGISTRY`'de İKİNCİ bir kayıt AÇILMAZ (D.2 Karar 1'in doğal devamı).

### 5.5 `engine_dependency: str | None = None` — 2. TUR ONAYLA KESİNLEŞTİ (karar #3, artık ÖNERİ DEĞİL, ZORUNLU)

Yeni metadata alanı: `engine_dependency: str | None = None` (Nakit Akışı'nın 6 oranı için `"cash_flow"`). `analyze_financial_ratios` orkestrasyonu, `engine_dependency` doluyken ilgili motorun sonucu `EngineRunContext`'te YOKSA, `compute_registered_ratio`'yu HİÇ ÇAĞIRMADAN doğrudan `NOT_CALCULABLE` üretir. `MISSING_INPUT`, yalnızca ilgili motor GERÇEKTEN mevcutken (`EngineRunContext`'te sonucu varken) belirli bir alan yine de `None` ise kullanılır. Bu, 4.3B'nin Step 9'unda (Bölüm 9) implemente edilecek — artık onay bekleyen bir soru DEĞİL.

### 5.6 `RATIO_REGISTRY_VERSION` güncellemesi

4.3B'nin 48 yeni kaydı + yukarıdaki metadata genişlemeleri (`depends_on_ratios`, `current_field`/`prior_field`, `scale_field`, `engine_dependency`, `direct_document_only_fields`) `RatioFormulaMetadata`'nın ŞEKLİNİ değiştirdiği için `RATIO_REGISTRY_VERSION` `"1.0.0"` → `"1.1.0"`'a yükseltilmelidir (J.2'deki cache-anahtarı tasarımının gerektirdiği disiplin — formül/şema değiştiğinde sürüm damgası da değişir). 4.3B sonunda `RATIO_REGISTRY` **57 kayıt** içerecektir (9 + 48).

---

## Bölüm 6 — ComputationOutcome Analizi (Yeni Oranlarda Durum Davranışı)

**Missing input:** Değişmedi — herhangi bir gerekli alan `None` ise `MISSING_INPUT`. Yeni oranlarda TEK fark: bazı alanlar artık `depends_on_ratios` üzerinden ENJEKTE ediliyor (Bölüm 3.2) — enjekte edilen değer `None` ise davranış AYNI (`missing_inputs`'a o ratio-key'in adı yazılır).

**Zero denominator:** `debt_to_equity`/`long_term_debt_to_equity`/`financial_leverage_multiplier`/`ebit_margin`/vb. için `UNDEFINED_ZERO_DENOMINATOR` (varsayılan) korunuyor. YENİ atama: `interest_coverage_ratio`/`ebitda_coverage_ratio` için `financing_expenses=0` → `NO_OBLIGATION` (finansman gideri olmaması olumlu bir durum, "karşılama oranı tanımsız" değil, "karşılanacak bir şey yok" demek) — bu, `current_ratio`'daki `NO_OBLIGATION` mantığının BORÇ SERVİSİ bağlamına genellenmiş hâlidir.

**No obligation:** Yukarıdaki iki yeni atamayla birlikte + `short_term_debt_ratio` toplam **5 oran** bu statüyü kullanacak (`current_ratio`, `working_capital_ratio`, `interest_coverage_ratio`, `ebitda_coverage_ratio`, `short_term_debt_ratio`). `short_term_debt_ratio`'nun `total_liabilities=0` durumu **2. tur onayla (karar #2) KESİNLEŞTİ**: `status=NO_OBLIGATION`, `value=None` (null) — sahte 0 veya Infinity ASLA üretilmez. Bu, "borç yok" iş anlamının doğru şekilde `NO_OBLIGATION` ile temsil edildiği ama sayısal bir DEĞER üretmediği (çünkü 0/0 gerçekten TANIMSIZDIR, yalnızca iş anlamı olumludur) bir tasarımdır — `current_ratio`'nun mevcut `NO_OBLIGATION` davranışıyla (o da `value=None` üretir) TUTARLIDIR.

**Not applicable:** İLK KEZ gerçekten tetiklenecek — `quick_ratio`/`cash_ratio`, BS `source_mode="trial_balance_derived"` iken. Tasarım kararı (Bölüm 5'e ek): bu kontrol `compute_registered_ratio`'nun İÇİNDE DEĞİL, **orkestrasyon katmanında** (`analyze_financial_ratios`) yapılacak — çünkü yalnızca orkestrasyon, hangi BS sonucunun hangi `source_mode`'dan geldiğini bilir. Yeni bir `RatioFormulaMetadata.direct_document_only_fields: tuple[str,...]` alanı (`quick_ratio`→`("inventory",)`, `cash_ratio`→`("cash_and_equivalents",)`) ile işaretlenir; orkestrasyon, BS `source_mode != "direct_document"` VE bu alan(lar) formülde kullanılıyorsa, `compute_registered_ratio`'yu HİÇ ÇAĞIRMADAN doğrudan `ComputationOutcome(status=NOT_APPLICABLE, ...)` üretir.

**Not calculable:** Bölüm 2'deki her-zaman-`not_calculable` 8 oran (`fixed_charge_coverage`, `sustainable_growth_rate`, Nakit Akışı'nın 6'sı — `engine_dependency` mekanizmasıyla, Bölüm 5.5 KESİNLEŞTİ) + `return_on_invested_capital`/`effective_tax_rate`'in KOŞULLU `not_calculable` hâli (girdi eksikse).

**Partial availability:** Kategori-seviyesi (K.4 politikası, DEĞİŞMEDİ) — ör. Faaliyet kategorisinde `inventory_turnover` hesaplanır ama `receivables_turnover` (BS mizan-fallback olduğu için `trade_receivables` yok) hesaplanamazsa, kategori `status="partial"`.

**Average hesaplanamaması:** 2. tur onayla (karar #4) KESİNLEŞTİ — Bölüm 4'teki `average_*` fonksiyonları ASLA warning üretmez (önceki dönem yokluğu normal bir iş durumudur). Bunun yerine HER sonuç `reliability` (`"high"`/`"medium"`) ve `calculation_basis` (`"two_period_average"`/`"ending_balance_fallback"`) alan çiftini taşır — bu artık onaya açık bir tercih DEĞİL, kesin sözleşmedir.

**Hiçbir durumda Infinity/NaN:** Yeni `growth_rate` VE `scaled_division` stratejileri de AYNI `try/except (InvalidOperation, OverflowError, ArithmeticError)` desenini miras alacak; `abs(prior)` işlemi Decimal için güvenlidir (`Decimal.__abs__` asla exception fırlatmaz), `prior==0`/`denominator==0` payda kontrolü `sum_division` ile BİREBİR aynı önce-kontrol-sonra-böl desenini kullanacak. `days_in_period`'in `+1` düzeltmesi de (Bölüm 4.1) `date` aritmetiğinde asla ham exception sızdırmaz — geçersiz tarih sırası kontrollü `not_calculable`'a düşer.

---

## Bölüm 7 — Test Stratejisi

**Unit Tests:** (a) `compute_growth_rate` — calculated/missing_input/undefined_zero_denominator/negatif-current/negatif-prior kombinasyonları; (b) her yeni `average_*` fonksiyonu — ikisi de dolu/yalnızca cari/ikisi de boş; (c) `depends_on_ratios` enjeksiyonunun doğru sırada çalıştığı (`days_inventory_outstanding`'in `inventory_turnover`'dan SONRA hesaplandığı); (d) `register_ratio_formula`'nın `depends_on_ratios`'taki bilinmeyen key'i reddettiği; (e) yeni `NOT_APPLICABLE` tetiklenme mantığının (quick_ratio/cash_ratio, trial_balance_derived modda) doğru çalıştığı.

**Golden Dataset:** Mevcut 4.3A golden dataset'i (gerçek fixture değerleriyle) GENİŞLETİLİR — aynı sentetik BS/IS fixture'ları için 47 yeni oranın TAMAMININ elle (bağımsız script ile) hesaplanmış referans değerleriyle bit-bir eşleştiği; AYRICA önceki dönem fixture'ı GEREKİR (Büyüme kategorisi için) — yeni bir sentetik "önceki dönem" BS/IS fixture çifti üretilmesi gerekecek (mevcut fixture'ların %10-15 farklı bir varyantı, tamamen kurgusal).

**Regression Tests:** (a) 4.3A'nın 9 oranının DEĞİŞMEDİĞİ (aynı golden değerler); (b) BS/IS `result_json` şeklinin DEĞİŞMEDİĞİ; (c) `RATIO_REGISTRY_VERSION` yükseltmesinin cache-anahtarı tasarımını (J.2, henüz implemente edilmedi ama gelecekte bozmayacak şekilde) etkilemediği.

**Property Tests:** `hypothesis` (bugün `requirements.txt`'te YOK — eklenmesi implementasyon kararı) ile: rastgele `Decimal` kombinasyonları için TÜM 56 kayıtlı oranın asla `Infinity`/`NaN`/ham exception üretmediği; `depends_on_ratios` zincirinin (3 seviyeye kadar — `cash_conversion_cycle` → `days_*` → `*_turnover`) her zaman sonlu bir sürede sonuçlandığı (döngüsel bağımlılık YOK garantisi — `register_ratio_formula`'nın "bağımlılık kendinden önce tanımlanmalı" kuralı bunu yapısal olarak imkansız kılar, ama bir test bunu AÇIKÇA da doğrulamalı).

**Performance Tests:** 56 oranın (9'dan 56'ya çıkışın) tek bir `analyze_financial_ratios()` çağrısındaki toplam hesaplama süresinin 4.3A'daki 9-oranlı sürüme göre orantılı (yaklaşık 6x, üstel DEĞİL) arttığının ölçülmesi — `depends_on_ratios` zincirinin performans üzerinde (yeniden hesaplama/tekrar) olumsuz bir etkisi olmadığının doğrulanması.

**Edge Case Tests:** (a) negatif özkaynak + `debt_to_equity`/`return_on_equity`/`financial_leverage_multiplier` (Bölüm 8 riski); (b) `prior_period_balance_sheet_result`/`prior_period_income_statement_result` YALNIZCA BİRİ sağlanmışsa (BS var IS yok) büyüme kategorisinin `partial` davrandığı; (c) `average_inventory` için önceki dönem `inventory=0` (gerçek sıfır) iken ortalamanın DOĞRU hesaplandığı (0 ile None karışmadığı); (d) çok büyük/çok küçük Decimal değerlerle `growth_rate`'in taşma üretmediği.

---

## Bölüm 8 — Risk Analizi

**Registry duplication (orta risk):** `ebit_margin_pct`/`ebitda_margin_pct` bugün `income_statement/analyzer.py`'de YEREL `safe_divide` ile hesaplanıyor (4.3A'nın bilinçli kapsam sınırı). 4.3B'de `ebit_margin`/`ebitda_margin` RATIO_REGISTRY'ye eklenince, EĞER `income_statement/analyzer.py` GÜNCELLENMEZSE, aynı formül İKİ yerde (yerel + registry) var olmaya devam eder — tam da D.2'nin önlemeye çalıştığı durum. **Çözüm:** 4.3B'nin implementasyon adımlarından biri (Bölüm 9), `compute_margins`'in KALAN 2 alanını da (`ebit_margin_pct`/`ebitda_margin_pct`) registry'ye yönlendirmek OLMALI — bu, "kısmi migrasyonu tamamlama" görevi olarak AÇIKÇA plana eklenir.

**Analyzer divergence (düşük risk, kontrol altında):** BS/IS analyzer'ları yalnızca `compute_registered_ratio`'yu ÇAĞIRIYOR, kendi Decimal aritmetiği YOK (4.3A'da sağlandı) — 4.3B'nin yeni oranları BS/IS analyzer'larının DIŞINDA (yalnızca `financial_ratios/service.py`'de) yaşayacağı için bu risk yeni oranlar için baştan itibaren YOK.

**Strategy explosion (orta risk, aktif olarak yönetiliyor):** Bölüm 3, 4 önerilen stratejiden (average_balance_division, ratio_of_ratio, growth_rate, scaled_ratio) yalnızca BİRİNİ (`growth_rate`) gerçekten gerekli buldu; ikisini (average_balance_division, ratio_of_ratio) mevcut stratejilerin + yeni bir orkestrasyon mekanizmasının (`depends_on_ratios`) yeterli olduğunu göstererek REDDETTİ; birini (`scaled_ratio`, defensive_interval_ratio için) ERTELEDİ. **Bu disiplin gelecekte de korunmalı** — her yeni oran için ÖNCE "mevcut 2-3 strateji + derived facts + depends_on_ratios ile ifade edilebilir mi" sorusu sorulmalı, YENİ strateji SON çare olmalı.

**Average hesaplarının tutarsızlığı (orta risk):** `average_total_assets`, hem `return_on_assets` HEM `asset_turnover` tarafından PAYLAŞILIYOR — eğer implementasyon sırasında bu iki oran YANLIŞLIKLA farklı `average_total_assets` türetimi kullanırsa (ör. biri dönem-sonu, diğeri ortalama), sonuçlar tutarsız olur. **Çözüm:** `average_total_assets` TEK bir `ratio_derived_facts.compute_average_total_assets()` çağrısıyla facts dict'e BİR KEZ enjekte edilmeli (BS analyzer'ın `total_liabilities`'i tek enjekte etmesiyle AYNI desen), iki oran da AYNI facts-dict anahtarını (`"average_total_assets"`) okumalı — bu, implementasyon planında (Bölüm 9) açıkça bir adım olarak yazılmalı.

**Provenance bozulması (orta risk, Bölüm 3.2'de zaten tartışıldı):** `depends_on_ratios` enjeksiyonu, bağımlı oranın `missing_inputs`'ında yalnızca üst-oranın ADINI gösterir, ALT NEDENİ göstermez. **Çözüm:** genişletilmiş provenance'a (`provenance_to_dict_extended`) opsiyonel bir `depends_on_provenance: tuple[str,...]` alanı (bağımlı olunan oranların KENDİ provenance metric-adları) eklenerek, kullanıcı isterse zinciri takip edebilir — bu, ProvenanceEntry'ye 4. bir additive alan anlamına gelir (yine geriye uyumlu, `provenance_to_dict()` DEĞİŞMEZ).

**Backward compatibility (düşük risk, disiplinli additive tasarım sayesinde):** Tüm önerilen genişlemeler (`depends_on_ratios`, `current_field`/`prior_field`, `engine_dependency`, `direct_document_only_fields`) `RatioFormulaMetadata`'ya VARSAYILAN DEĞERLİ (`= ()` / `= None`) alanlar olarak eklenir — 4.3A'nın 9 kaydı hiçbir değişiklik gerektirmeden ÇALIŞMAYA DEVAM EDER. `RATIO_REGISTRY_VERSION` yükseltmesi (Bölüm 5.6) bunu AÇIKÇA işaretler.

**Yorumsal/muhasebesel risk (orta, yeni tespit edilen):** Negatif `operating_profit`/`equity`/`ebitda` durumlarında bazı oranların işareti (ör. `non_operating_income_dependency`, `debt_to_ebitda`) yanıltıcı olabilir — bu Bölüm 6'da her ilgili oranda ayrıca not edildi; implementasyon aşamasında (Bölüm 9) bu oranlara `negative_component_warning` gibi ek bir bayrak eklenip eklenmeyeceği AYRI bir onay konusu olarak işaretlenmiştir (mimari doküman N.2'nin genel "negatif özkaynak" riskinin somutlaşmış hâli).

---

## Bölüm 9 — Implementasyon Planı (Küçük Adımlar)

**Step 1 — Registry metadata genişlemesi (yalnızca şema, yeni oran YOK).**
Dosyalar: `app/engines/common/ratio_formulas.py` (`RatioFormulaMetadata`'ya `depends_on_ratios`, `current_field`/`prior_field`, `scale_field`, `engine_dependency`, `direct_document_only_fields` additive alanları; `growth_rate` VE `scaled_division` stratejileri + `CALCULATION_STRATEGIES`'e kayıt; `register_ratio_formula`'ya `depends_on_ratios` doğrulaması; `RATIO_REGISTRY_VERSION` → `"1.1.0"`).
Testler: mevcut 4.3A testlerinin (106) DEĞİŞMEDEN geçtiği + yeni `compute_growth_rate`/`compute_scaled_division` birim testleri.
Başarı kriteri: 9 mevcut oran bit-bir aynı, `growth_rate`/`scaled_division` izole test edilebilir, henüz hiçbir yeni oran KAYITLI değil.

**Step 2 — `ratio_derived_facts.py` genişlemesi (average_* + tax_expense/invested_capital + days_in_period `+1` düzeltmesi).**
Dosyalar: `ratio_derived_facts.py` (5 `average_*` + `compute_tax_expense` + `compute_invested_capital` yeni fonksiyonlar; `compute_days_in_period`'in birincil formülü `(end_date-start_date).days` → `(end_date-start_date).days + 1` DÜZELTİLİR, Bölüm 4.1).
Testler: her `average_*` için two_period_average/ending_balance_fallback/None; `days_in_period` için Bölüm 4.1'deki 5 zorunlu test (365/366/fallback/geçersiz sıra/exception yok).
Başarı kriteri: fonksiyonlar izole, `financial_ratios/service.py`'ye HENÜZ bağlanmadı; `days_in_period` düzeltmesi mevcut 4.3A testlerini BOZMAZ (henüz hiçbir 4.3A oranı bunu tüketmiyor).

**Step 3 — Likidite + Borçluluk'un kalan oranları (bağımlılığı OLMAYAN 9 oran: quick_ratio, cash_ratio, defensive_interval_ratio [scaled_division], long_term_debt_to_equity, short_term_debt_ratio, financial_leverage_multiplier, interest_coverage_ratio, ebitda_coverage_ratio, debt_to_ebitda).**
Dosyalar: `ratio_formulas.py` (9 yeni `register_ratio_formula` çağrısı), `financial_ratios/service.py` (`_CATEGORY_RATIO_KEYS` genişletme, `NOT_APPLICABLE` orkestrasyon mantığı — `direct_document_only_fields`).
Testler: golden dataset genişletme (9 oran), `NOT_APPLICABLE` senaryosu (mizan-fallback BS ile quick_ratio/cash_ratio), `short_term_debt_ratio`'nun `total_liabilities=0` → `no_obligation`/`value=None` davranışı.
Başarı kriteri: 18 oran kayıtlı, tüm status dalları (missing_input/no_obligation/undefined/not_applicable) en az bir gerçek senaryoda kanıtlanmış.

**Step 4 — Kârlılık'ın kalan oranları (ebit_margin, ebitda_margin, pretax_profit_margin, return_on_capital_employed, effective_tax_rate, return_on_invested_capital [artık koşullu hesaplanabilir]).**
Dosyalar: `ratio_formulas.py`, `income_statement/analyzer.py` (ebit_margin_pct/ebitda_margin_pct'in registry'ye TAM yönlendirilmesi — Bölüm 8 "registry duplication" riskinin kapatılması).
Testler: golden dataset + `effective_tax_rate`'in aralık-dışı (`<0`/`>1`) durumda değeri GİZLEMEDEN warning ürettiğinin testi + `income_statement/analyzer.py`'nin `result_json["margins"]` şeklinin DEĞİŞMEDİĞİNİN regresyon testi (4.3A'daki `test_provenance_to_dict_unchanged_5_keys` desenine benzer).
Başarı kriteri: `ebit_margin_pct`/`ebitda_margin_pct` artık İKİ yerde değil, TEK yerde (registry) tanımlı; ROIC `effective_tax_rate` mevcutken GERÇEKTEN hesaplanıyor.

**Step 5 — Ortalama-bakiye bağımlı oranlar (return_on_assets, return_on_equity, asset_turnover + Faaliyet kategorisinin ilk 3'ü: inventory_turnover, receivables_turnover, payables_turnover).**
Dosyalar: `ratio_formulas.py` (6 yeni kayıt), `financial_ratios/service.py` (`_build_facts_dict`'in `prior_period_balance_sheet_result`/`prior_period_income_statement_result`'ı OKUMAYA başlaması, `average_*` enjeksiyonu).
Testler: önceki-dönem fixture'ı OLAN ve OLMAYAN iki senaryo (reliability high vs medium).
Başarı kriteri: `average_total_assets`'in `return_on_assets` VE `asset_turnover` tarafından AYNI enjekte edilmiş değerden okunduğu (Bölüm 8 riskinin kapatıldığı) doğrulanmış.

**Step 6 — `depends_on_ratios` orkestrasyonu + bağımlı Faaliyet oranları (fixed_asset_turnover, working_capital_turnover, days_inventory_outstanding, days_sales_outstanding, days_payables_outstanding, cash_conversion_cycle, working_capital_to_total_assets).**
Dosyalar: `financial_ratios/service.py` (topolojik hesaplama sırası — büyük bir orkestrasyon değişikliği), `ratio_formulas.py` (7 yeni kayıt).
Testler: bağımlılık sırasının doğru çalıştığı, bir üst-oran `missing_input` iken bağımlı oranın da doğru şekilde etkilendiği, döngüsel bağımlılık olmadığının statik testi.
Başarı kriteri: Faaliyet kategorisinin TAMAMI (10/10) kayıtlı ve doğru sıralı hesaplanıyor.

**Step 7 — Verimlilik (6 oran, bağımlılık YOK, en basit adım).**
Dosyalar: `ratio_formulas.py` (6 yeni kayıt), `financial_ratios/service.py` (`_CATEGORY_RATIO_KEYS`'e ekleme).
Testler: golden dataset.
Başarı kriteri: Verimlilik kategorisi tam.

**Step 8 — Büyüme (6 hesaplanabilir + 1 not_calculable).**
Dosyalar: `ratio_formulas.py` (7 kayıt, `growth_rate` stratejisini KULLANAN ilk gerçek oranlar), `financial_ratios/service.py` (`prior_period_*`'tan `prior_` önekli alanların facts dict'e enjeksiyonu — Bölüm 3.3'ün isimlendirme kuralı), yeni sentetik "önceki dönem" fixture çifti (`tests/data/synthetic/generate_fixtures.py`'ye ek).
Testler: önceki dönem YOK/VAR senaryoları, negatif-prior edge case.
Başarı kriteri: Büyüme kategorisi tam, `growth_rate` stratejisi gerçek verilerle kanıtlanmış.

**Step 9 — Nakit Akışı (6 oran, hepsi `engine_dependency="cash_flow"` ile kayıtlı, hepsi `not_calculable`).**
Dosyalar: `ratio_formulas.py` (6 kayıt, `engine_dependency` alanı DOLU), `financial_ratios/service.py` (`engine_dependency` kontrolü — ilgili motor `EngineRunContext`'te yoksa `compute_registered_ratio` ÇAĞRILMADAN `NOT_CALCULABLE`).
Testler: hepsinin tutarlı biçimde `NOT_CALCULABLE` döndüğü (MISSING_INPUT DEĞİL), sahte bir değer ASLA sızmadığı.
Başarı kriteri: 57 oranın TAMAMI kayıtlı, kapsam tamamlandı.

**Step 10 — Tam regresyon + final rapor.**
`py_compile` tüm değişen dosyalar, sandbox-only test koşumu (mevcut + yeni testler), Docker/Postgres'e bağımlı testlerin ETKİLENMEDİĞİNİN (bulk_upload.py'ye dokunulmadığı için) kaynak-metin taramasıyla doğrulanması, dürüst final rapor.

**Kritik not:** Bu 10 adım **sıralı bağımlıdır** (Step 6, Step 2/5'e; Step 8, Step 1'e bağımlı) — hiçbiri, bir öncekinin testleri geçmeden başlamamalıdır. Adım sayısı/gruplama, implementasyon onayı sırasında kullanıcı tarafından birleştirilebilir/bölünebilir.

---

## Bölüm 10 — Milestone Sınır Kontrolü

Bu doküman hazırlanırken ve (onay sonrası) implementasyon sırasında **kesinlikle yapılmayacaklar**:

- **Migration yok** — yeni oranların hepsi mevcut `canonical_facts`/`FinancialAnalysisResult.result_json` şeması İÇİNDE kalıyor; hiçbir yeni DB tablosu/kolonu gerekmiyor.
- **Benchmark sistemi yok** — Milestone 4.3C'nin kapsamı, bu dokümanda tasarlanmadı/implemente edilmedi.
- **Health Score yok** — Milestone 4.3D'nin kapsamı.
- **Credit Score yok** — Milestone 4.3E'nin kapsamı.
- **Recommendation Engine yok** — Milestone 4.3F'nin kapsamı.
- **`ratio_recompute.py` yok** — 4.3A'da da oluşturulmadı, bu fazda da oluşturulmayacak; `FinancialRatioEngineAdapter` hâlâ hiçbir gerçek akışa bağlı olmayacak (Bölüm 1.5).
- **API değişikliği yok** — `app/api/v1/**`'e hiçbir yeni endpoint/değişiklik.
- **Bulk upload davranışı değişmeyecek** — `app/services/bulk_upload.py`'ye HİÇBİR dokunuş (4.3A'daki testin, `test_analyze_financial_ratios_is_not_wired_to_bulk_upload_or_recompute`, aynen geçerli kalması bekleniyor).
- **`app/trial_balance/**` dosyalarına dokunulmayacak** — 4.3A'daki disiplin (A.8/D.2 Karar 3) aynen korunuyor.
- **Milestone 4.4'e (Cash Flow Engine) geçilmeyecek** — Nakit Akışı kategorisinin 6 oranı BUGÜNKÜ veriyle `not_calculable`/`missing_input` kalacak, gerçek `CashFlowFacts` üretimi bu fazın kapsamı DIŞINDA.

**2. TUR ONAYLA KESİNLEŞEN FAZ PLANI (karar #5):** Daha önce hiçbir faza atanmamış 7 kategori (~37 oran) artık şöyle planlanmıştır:
- **4.3E:** Bankacılık + Risk oranları, ardından Credit Score.
- **4.3F:** Çalışma Sermayesi oranları + Recommendation altyapısı.
- **YENİ 4.3G:** Yatırım, Piyasa, IFRS ve Sermaye Yapısı oranları.

Bu kategoriler 4.3B'ye DAHİL EDİLMEDİ — yalnızca faz ataması netleşti, implementasyonları yine kendi fazlarını bekliyor.

---

## Bölüm 11 — Kapanış: 2. Tur Onayla Çözülen Kararlar

Aşağıdaki 6 soru, kullanıcının 2. tur onayıyla TAMAMI çözülmüştür — artık açık soru YOKTUR:

1. **`defensive_interval_ratio`** → ERTELENMEDİ. `scaled_division` stratejisi eklendi (Bölüm 3.4, karar #1).
2. **`short_term_debt_ratio`'nun `total_liabilities=0` durumu** → `NO_OBLIGATION`, `value=None` (karar #2).
3. **`engine_dependency` metadata alanı** → 4.3B'de EKLENECEK, Nakit Akışı oranları `NOT_CALCULABLE` dönecek (karar #3).
4. **`average_*` fallback'inde warning** → warning YOK, bunun yerine `reliability`/`calculation_basis` alan çifti HER ZAMAN dolu (karar #4).
5. **Kalan 7 kategorinin faz ataması** → 4.3E (Bankacılık+Risk+Credit Score), 4.3F (Çalışma Sermayesi+Recommendation altyapısı), YENİ 4.3G (Yatırım+Piyasa+IFRS+Sermaye Yapısı) (karar #5).
6. **10 implementasyon adımının sırası** → AYNEN korunacak, birleştirilmeyecek/genişletilmeyecek, bir adımın testleri tam yeşil olmadan sonraki adıma geçilmeyecek (karar #6).

Ayrıca: ROIC/`effective_tax_rate` tasarım çelişkisi düzeltildi (Bölüm 2.2/3.5, karar #7); `days_in_period` sözleşmesi `+1` (kapsayıcı) olarak düzeltildi (Bölüm 4.1, karar #8).

---

## Bölüm 12 — Kesin Kapsam Sınırları (Implementasyon Öncesi Son Teyit)

Implementasyon sırasında KESİNLİKLE yapılmayacaklar (kullanıcının son mesajıyla yeniden teyit edildi): migration yok; Benchmark implementasyonu yok; Health Score yok; Credit Score yok; Recommendation Engine yok; `ratio_recompute.py` yok; API değişikliği yok; bulk upload değişikliği yok; `app/trial_balance/**` değişikliği yok; commit veya push yok; 4.3C veya sonraki fazlara geçiş yok.

---

*Doküman sonu. Bu revizyonla onay tamamlanmıştır — implementasyon aşağıdaki Bölüm 9 planına göre başlayacaktır.*
