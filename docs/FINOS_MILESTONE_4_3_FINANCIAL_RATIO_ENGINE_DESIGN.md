# FINOS Milestone 4.3 — Financial Ratio Engine: Mimari ve Tasarım Dokümanı

**Durum:** Tasarım aşaması — onay bekliyor. Bu dokümanda **hiçbir kod, migration veya test yoktur**; yalnızca mimari karar ve sözleşme tasarımı vardır. Hiçbir mevcut dosya bu doküman hazırlanırken değiştirilmedi.

**Kapsam:** Milestone 4.3 — Financial Ratio Engine (oran motoru), Financial Health Score, Credit Score Engine, Industry Benchmark altyapısı, Recommendation Engine altyapısı, Explainability katmanı.

**Önceki referans doküman:** `docs/FINOS_MILESTONE_4_ARCHITECTURE_DESIGN.md` (Milestone 4'ün genel mimarisi — hibrit kaynak modeli, `financial_analysis_result_sources`, motor sözleşmesi). Bu doküman o kararları **değiştirmez**, üzerine inşa eder.

---

## Bölüm A — Mevcut Sistemin İncelemesi

Aşağıdaki inceleme, tasarım kararlarından önce yapılan tam kod tabanı taramasının özetidir. Hiçbir varsayımda bulunulmadı; her madde gerçek dosya içeriğine dayanır.

### A.1 Genel mimari özet (Milestone 4.1/4.2 sonrası mevcut durum)

FINOS bugün üç "motor" (engine) çalıştırıyor: `TrialBalanceEngineAdapter`, `BalanceSheetEngineAdapter`, `IncomeStatementEngineAdapter`. Her biri `app/engines/protocol.py`'deki `EngineAdapter` Protocol'üne uyar (`analysis_type`, `requires_content`, `run(*, content, filename, context) -> EngineRunResult`). `app/engines/registry.py`, `AnalysisType` değerini **tek doğruluk kaynağı** olarak kullanan bir sözlükle (`_ENGINE_BY_ANALYSIS_TYPE`) bu üç adaptörü kayıt altına alır ve iki ayrı sınıflandırma dünyasından (`DetectedDocumentType`, `DocumentType`) bu tek kayda yönlendirme yapar.

Motorların hepsi `app/engines/common/**` altındaki, **sqlalchemy/fastapi/pydantic'e sıfır bağımlı** ortak modülleri kullanır: `canonical_facts.py` (extractor→analyzer arası bellek-içi veri şekilleri), `calculation_provenance.py` (her türetilmiş metrik için "nasıl hesaplandı / neden hesaplanamadı" kaydı), `reconciliation.py` (iki kaynak arası mutabakat), `trial_balance_fallback.py` (mizan sonucundan kanonik factsçıkarımı), `ratio_formulas.py` (**bilinçli olarak boş** bırakılmış oran formülü sözleşme iskeleti — bkz. A.10).

Her motorun kendi paketi extractor→analyzer→service→adapter dörtlüsünden oluşur (`app/engines/balance_sheet/**`, `app/engines/income_statement/**`). Bu desen 4.3'te de korunacaktır.

### A.2 Motor protokolü (`EngineAdapter`) ve Registry — 4.3 açısından önemli noktalar

`EngineRunContext` (`app/engines/protocol.py`) şu an şu alanları taşıyor: `company_id: uuid.UUID | None`, `period_id: uuid.UUID | None` (4.2'de opsiyonel yapıldı — FAZ2'de henüz DB'de yaratılmamış firma/dönem için gerçek UUID yok), `trial_balance_result: dict | None`, `trial_balance_analysis_result_id: uuid.UUID | None`, `trial_balance_pending_in_batch: bool`, ve `EngineRunResult.pending_trial_balance_source_role`. Bu alanlar **Balance Sheet/Income Statement özelinde** "mizan fallback" senaryosu için tasarlanmıştı, ama dosyanın kendi docstring'i açıkça şunu söylüyor: *"yalnızca ileride kimlik bağlamına ihtiyaç duyacak motorlar (ör. Milestone 4.3 Financial Ratio Engine, FAZ 3 sonrası/DB id'leri kesinleştikten sonra çalışacağı için) için hazır bir alan."* Yani protokol, Ratio Engine'in **aynı-batch içinde değil, FAZ 3'ten SONRA (BS/IS sonuçları flush edildikten sonra) çalışacağı** varsayımıyla zaten hazırlanmış. Bu varsayım 4.3 tasarımında da korunacak (bkz. B.9, M).

`AnalysisType.FINANCIAL_RATIOS` enum değeri **zaten tanımlı** (`app/models/enums.py`) ama registry'de kayıtlı bir adaptörü yok — 4.3'ün ekleyeceği `FinancialRatioEngineAdapter` bu boşluğu dolduracak.

### A.3 Kanonik veri modelleri (`canonical_facts.py`)

`BalanceSheetFacts`, `IncomeStatementFacts`, `CashFlowFacts` (henüz üretilmiyor — Milestone 4.4), `TaxReturnFacts` (henüz üretilmiyor — Milestone 4.5) tanımlı. Tüm parasal alanlar `Decimal | None` — eksik veri `None`'dır, asla fabrikasyon `0` değildir. Bu disiplin 4.3'te de **birebir** korunacaktır; Ratio Engine'in üreteceği hiçbir oran, eksik bir girdiden dolayı sessizce `0` üretmeyecektir.

Önemli tespit: `BalanceSheetFacts`'te `total_liabilities` alanı **yok** — `short_term_liabilities + long_term_liabilities` her ihtiyaç duyulduğunda ayrı ayrı türetiliyor (bkz. `balance_sheet/analyzer.py::compute_preliminary_structural_ratios`, satır 152-157). Bu, 4.3'te bir **türetilmiş ara katman** (derived/composite facts) ihtiyacını doğuruyor — bkz. B.5 ve C.0.

### A.4 Ortak modüller — 4.3'ün doğrudan üzerine inşa edeceği üç modül

**`ratio_formulas.py`** (bkz. A.10 — ayrı ele alınıyor, çünkü bu 4.3'ün "resmi giriş noktası").

**`reconciliation.py`**: iki seviyeli tolerans (rounding: `max(1.00, |ref|*%0.01)`; material: `max(100.00, |ref|*%0.5)`) ve **hotfix sonrası nihai sözleşme** `build_reconciliation_summary(*, performed, compared_against, findings) -> dict` — `{"compared_against", "performed", "within_tolerance", "material_difference", "differences"}` şeklini üretir. Bu, 4.3'te BS/IS ile Ratio Engine arası (ve gelecekte Ratio Engine ile Cash Flow Engine arası) çapraz doğrulamalarda **aynen** yeniden kullanılacaktır — yeni bir reconciliation sözleşmesi icat edilmeyecek.

**`calculation_provenance.py`**: `ProvenanceEntry(metric, derivation_rule, input_fields, missing_inputs, calculated)` — her türetilmiş metrik için zorunlu. 4.3'ün **Explainability** katmanının (Bölüm I) temel taşı budur; sıfırdan yeni bir explainability şeması icat edilmeyecek, bu şema **genişletilecek**.

### A.5 Balance Sheet / Income Statement motorları — "preliminary" oranların durumu

`balance_sheet/analyzer.py::compute_preliminary_structural_ratios` (current_ratio, debt_ratio, equity_ratio, debt_to_equity) ve `compute_working_capital` (net_working_capital, working_capital_ratio), kodun kendi docstring'inde **açıkça** "Financial Ratio Engine'in (Milestone 4.3) NİHAİ, çapraz-tablo sonucunun YERİNE GEÇMEZ" diye işaretlenmiş ve `result_json["preliminary_structural_ratios"]` altında ayrı bir alanda saklanıyor (BS engine'in kendi `result_json`'ında, `financial_ratios` analiz sonucunda DEĞİL). `income_statement/analyzer.py::compute_margins` benzer şekilde `result_json["margins"]` altında gross/operating/net margin gibi tek-tablo oranları üretiyor.

Bu, 4.3'ün karşılaştığı **gerçek bir teknik borç** — aynı formüller (current_ratio, debt_ratio, equity_ratio, debt_to_equity, gross_profit_margin, operating_profit_margin, net_profit_margin vb.) hem BS/IS motorlarında (yerel, tek-tablo, "preliminary") hem de yakında Ratio Engine'de (çapraz-tablo, "authoritative") hesaplanacak. Bölüm D bu çakışmayı **kod tekrarı olmadan** nasıl çözeceğimizi tasarlıyor.

### A.6 Kaynak izlenebilirliği (`FinancialAnalysisResultSource`)

DB seviyesinde zorlanan XOR kuralı (`source_document_id` XOR `source_analysis_result_id`), kendine-referans yasağı, ve role↔kaynak-türü eşleşmesi (`AnalysisSourceRole`: `primary_document`, `primary_analysis`, `trial_balance_fallback`, `prior_period_reference`, `supporting_document`, `supporting_analysis`) zaten var ve **Ratio Engine'in en yoğun kullanacağı tablo bu olacak** — çünkü Ratio Engine tanımı gereği `SourceMode.MULTI_SOURCE_DERIVED`'dır (bkz. `SourceMode` docstring'i, satır 192-197: *"Financial Ratio Engine -- Milestone 4.3"* örnek olarak zaten anılıyor) ve BS sonucu + IS sonucu + (opsiyonel) mizan sonucu + (opsiyonel) önceki dönem sonucu gibi **birden fazla** kaynağa aynı anda referans verecek. Şema bunun için zaten hazır; yeni bir migration'a **yalnızca yeni tablo için değil**, mevcut tabloyu kullanmak için ihtiyaç yok — ama Ratio Engine'e özgü yeni tablolar (benchmark, health score, credit score — bkz. Bölüm M) elbette yeni migration gerektirecek.

### A.7 Bulk Upload orkestrasyonu (FAZ1/FAZ2/FAZ3) — Ratio Engine'in ne zaman çalışacağı

`app/services/bulk_upload.py`, `_run_confirm_preflight` (FAZ1, salt-okunur), `_run_confirm_analyses` (FAZ2, bellek-içi, DB transaction'ı açık değilken motorları `_run_single_engine` ile `get_engine_for_detected_type` üzerinden çağırıyor) ve `_write_confirmed_records` (FAZ3, tek transaction'da yazma) olmak üzere üç fazlı. `AcceptedItemPlan` dataclass'ı her kabul edilmiş item için firma/dönem çözümlemesini, mizan bağımlılığını (`trial_balance_pending_in_batch`) ve motor sonucunu taşıyor.

Kritik gözlem: bugünkü tasarım, **bir batch içindeki BS/IS motorlarının birbirine değil, yalnızca mizana bağımlı olabileceğini** varsayıyor (dependency-aware sıralama yalnızca "mizan önce, BS/IS sonra" akışını çözüyor). Ratio Engine ise **BS VE IS'in ikisine birden** bağımlı olacak — bu, FAZ2/FAZ3 orkestrasyonuna **yeni bir bağımlılık sınıfı** ekler (bkz. B.9, M.3). Ratio Engine'in "aynı batch içinde henüz flush edilmemiş BS/IS sonucu" senaryosunu (mizanın bugün yaşadığı `trial_balance_pending_in_batch` sorunuyla birebir aynı sınıf problem) çözmesi gerekecek.

### A.8 `app/trial_balance/ratios.py` ve `insights.py` — legacy modüller, kapsam dışı bırakılmayacak

`app/trial_balance/ratios.py::build_ratios`, mizan `result_json`'ı içinde **float tabanlı** (Decimal değil), tek-tablo (yalnızca mizandan üretilen BS+IS'ten) `liquidity`/`leverage`/`profitability`/`coverage`/`data_quality` alt sözlüklerini üretiyor; `insights.py::build_insights` bunun üzerine eşik-tabanlı (current_ratio<1, debt_to_equity>3 vb.) metin uyarıları ekliyor. Bu modüller **mizan analiz sonucunun kendi iç sözleşmesinin bir parçası** — `app/trial_balance/service.py`'nin dış API'sini değiştirmeden bunlara dokunmak Milestone 4.3'ün kapsamı DEĞİL (bkz. Q.2). Ancak Ratio Engine'in ürettiği sonuçlar bunlarla **kavramsal olarak çakışacağı** için (current_ratio, debt_to_equity, gross_profit_margin aynı isimlerle iki yerde var olacak), Bölüm D bu ikisinin nasıl "aynı doğruya" işaret edeceğini (yalnızca mizan-tek-kaynaklı bir analiz söz konusu olduğunda) netleştiriyor.

### A.9 `ratio_formulas.py` — bilinçli boş bırakılan iskelet, 4.3'ün "resmi" doldurma noktası

4.1'de bilinçli olarak **boş** bırakıldı (`RATIO_REGISTRY: dict[str, RatioFormulaMetadata] = {}`), gerekçesi kod içinde açık: *"henüz hiçbir motor bu formülleri çağırmayacakken 'çalışan altyapı görünümü veren ölü API' BİLEREK üretilmedi."* Sağladığı üç gerçek şey: `safe_divide` (Decimal-güvenli, `None`/sıfır-bölme koruması, `ROUND_HALF_UP` ile 4 ondalık varsayılan quantize), `decimal_to_json_safe` (yalnızca dışa yazarken Decimal→float), ve `RatioFormulaMetadata` dataclass'ı (`key`, `category`, `display_name_tr`, `numerator_fields`, `denominator_fields`, `unit`). **4.3'ün birincil görevlerinden biri bu registry'yi doldurmaktır** — bu, "tek formül kaynağı" ilkesinin (Bölüm D) somut karşılığıdır.

### A.10 `FinancialPeriod` modeli — dönem uzunluğu hesapları için gerekli alanlar zaten var

`app/models/financial_period.py`: `year`, `period_type` (`year_end`/`quarter`/`temporary_tax`/`monthly`/`custom`), `period_number`, `start_date: Date` (NOT NULL), `end_date: Date` (NOT NULL), `months_covered: int`, `is_year_end: bool`. **Düzeltme (2. tur onay, madde 8):** `days_in_period`'in **tek kaynağı** `(end_date - start_date).days` (gerçek takvim günü farkı) olacaktır — `start_date`/`end_date` şema seviyesinde zorunlu olduğu için bu her zaman mevcuttur. `months_covered * 30` **yalnızca** çağıran bağlamda (ör. ileride `FinancialPeriod`'un tam nesnesi değil yalnızca kısmi alanları taşınan bir senaryo) gerçek tarihler erişilemezse, **açıkça `reliability="low"` işaretli bir fallback** olarak kullanılabilir — hiçbir zaman sessizce, birincil kaynakmış gibi kullanılmaz. Yeni bir alan/migration gerekmez.

### A.11 `app/trial_balance/financial_statements.py` — mizan motorunun ürettiği gerçek sözleşme

`build_balance_sheet`/`build_income_statement`, `trial_balance_fallback.py`'nin (A.4) okuduğu `financial_statements.balance_sheet`/`income_statement` alt sözlüklerini üretiyor. Önemli: mizan motoru **envanter/alacak/borç gibi alt kalem ayrıştırması yapmıyor** (yalnızca 1-5 sınıf toplamları) — bu, Ratio Engine'in mizan-fallback modunda **quick ratio, cash ratio, devir hızı oranlarının hiçbirini hesaplayamayacağı** anlamına geliyor (yalnızca current_ratio, debt_ratio, equity_ratio, debt_to_equity, marjlar hesaplanabilir). Bu kısıt Bölüm C'de her ilgili oranın "hesaplanamama şartı" olarak açıkça işaretlenecek.

### A.12 Tespit edilen boşluklar — 4.3'ün doldurması gereken yerler (özet)

1. `RATIO_REGISTRY` boş — doldurulacak (~100-150 kayıt).
2. `AnalysisType.FINANCIAL_RATIOS` registry'de kayıtlı değil — `FinancialRatioEngineAdapter` eklenecek.
3. BS/IS'teki "preliminary" oranlar ile Ratio Engine'in "authoritative" oranları arasında kod tekrarı riski — tek kaynağa indirilecek (Bölüm D).
4. `EngineRunContext`/`EngineRunResult`'ta çoklu-kaynak (BS+IS+opsiyonel mizan+opsiyonel önceki dönem) senaryosu için ek alanlara ihtiyaç var — additive genişletme (Bölüm M).
5. FAZ2/FAZ3 orkestrasyonunda "BS ve IS'in ikisine birden bağımlı üçüncü motor" sınıfı hiç yok — yeni bağımlılık sınıfı tasarlanacak (Bölüm B.9).
6. Health Score / Credit Score / Benchmark / Recommendation için **hiçbir model, tablo, ya da sözleşme yok** — sıfırdan tasarlanacak (Bölüm E-H, M).
7. Ortalama bakiye (average balance) ihtiyacı olan devir hızı oranları için `EngineRunContext`'e önceki dönem BS/IS facts'i taşıyan alan yok — additive eklenecek (Bölüm B.5, M).

---

## Bölüm B — Financial Ratio Engine'in Sorumlulukları

### B.1 Temel sorumluluk tanımı

Financial Ratio Engine (`AnalysisType.FINANCIAL_RATIOS`), bir şirketin **aynı döneme ait** Balance Sheet ve Income Statement analiz sonuçlarını (gerekiyorsa Cash Flow ve önceki dönem sonuçlarını da) girdi olarak alan, bunlardan ~100-150 finansal oranı, bir Financial Health Score'u, bir Credit Score'u ve (varsa) sektör karşılaştırmalı öngörüleri üreten, **kendisi hiçbir belge ayrıştırmayan, yalnızca zaten hesaplanmış `canonical_facts`/`result_json` üzerinde çalışan** bir "derived-only" (türetilmiş-yalnız) motordur. `SourceMode.MULTI_SOURCE_DERIVED` — tanım gereği tek bir `document_id`'ye bağlanamaz.

### B.2 Hangi oranlar hesaplanacak?

Bölüm C'de tam katalog var (14 kategori, 100+ oran). Özet: Likidite, Kârlılık, Faaliyet (devir hızları), Borçluluk/Leverage, Verimlilik, Büyüme, Yatırım, Nakit Akışı, Piyasa, Bankacılık, IFRS-uyumlu ek göstergeler, Risk, Sermaye Yapısı, Çalışma Sermayesi.

### B.3 Hangi belgeler kullanılacak?

Doğrudan belge **kullanılmaz** — Ratio Engine kendisi hiçbir dosya ayrıştırmaz (bu, A.1'deki "extractor yok" tasarım kararının doğal sonucu). Girdisi her zaman **başka analiz sonuçlarıdır**: aynı döneme ait `FinancialAnalysisResult` (BALANCE_SHEET), `FinancialAnalysisResult` (INCOME_STATEMENT), opsiyonel olarak `FinancialAnalysisResult` (TRIAL_BALANCE — yalnızca BS/IS mevcut değilse doğrudan fallback olarak, ya da mevcutsa yalnızca reconciliation referansı olarak), opsiyonel olarak önceki dönemin BS/IS sonuçları (büyüme oranları ve ortalama-bakiye oranları için), ve gelecekte (Milestone 4.4 sonrası) opsiyonel Cash Flow sonucu.

### B.4 Hangi engine hangi veriyi sağlayacak?

| Veri | Sağlayan | Zorunlu mu? |
|---|---|---|
| `current_assets`, `total_assets`, `equity`, vb. bilanço kalemleri | Balance Sheet Engine sonucu (`result_json["facts"]`) — yoksa mizan-fallback | Evet (en az biri) |
| `net_sales`, `gross_profit`, `ebit`, `ebitda`, `net_profit` vb. | Income Statement Engine sonucu — yoksa mizan-fallback | Evet (en az biri) |
| `cash_and_equivalents`, `inventory`, `trade_receivables`, `trade_payables` | **Yalnızca** Balance Sheet Engine'in doğrudan-belge (`direct_document`) sonucu — mizan bu ayrıntıyı hiç üretmiyor (bkz. A.11) | Hayır — yoksa ilgili oranlar `null` |
| Önceki dönem BS/IS `facts` | Aynı firmanın bir önceki `FinancialPeriod`'una ait tamamlanmış BS/IS sonuçları | Hayır — yoksa büyüme/ortalama-bakiye oranları `null` |
| `operating_cash_flow`, `free_cash_flow` vb. | Cash Flow Engine (Milestone 4.4 — henüz yok) | Hayır — Milestone 4.4'e kadar bu kategori tamamen `null`/`not_calculable` |
| Sektör ortalamaları | Industry Benchmark (Bölüm G — henüz veri yok) | Hayır — Milestone 4.3C sonrası dahi opsiyonel |

### B.5 Eksik belge varsa ne olacak? Null politikası nasıl işleyecek?

**Tek bir kural, üç seviyede uygulanır** (mevcut "eksik veri asla 0 değildir" ilkesinin doğrudan devamı):

1. **Girdi seviyesi:** BS sonucu yoksa `BalanceSheetFacts`'in ilgili alanları `None`'dır (BS motorunun kendisi zaten böyle döner). Ratio Engine bunu **kendisi türetmez**, olduğu gibi devralır.
2. **Hesaplama seviyesi:** Her oran, formülündeki **tüm** girdi alanları dolu değilse hesaplanmaz — sonuç `null`, `calculated=False`, `missing_inputs` dolu (bkz. `ProvenanceEntry`). Kısmi hesaplama (bir bileşeni 0 sayarak) **asla** yapılmaz — bu, `compute_preliminary_structural_ratios`'taki `total_liabilities_missing` deseninin (A.3) birebir genellemesidir.
3. **Kategori seviyesi:** Bir kategorinin (ör. Nakit Akışı) **tüm girdileri** eksikse (ör. Cash Flow Engine henüz devrede değilse), o kategorinin tamamı `"not_calculable"` durumuyla işaretlenir, tek tek `null` oranlar yerine kategori düzeyinde açık bir sebep metni üretilir (bkz. K.4).

`0` yalnızca kaynak veride **gerçekten** sıfır olduğunda kullanılır — bu ayrım zaten `trial_balance_fallback.py`'de (A.4) `account_details` listesinin boş olup olmamasına bakılarak çözülmüş durumda; Ratio Engine bu ayrımı **yeniden üretmez**, devraldığı `canonical_facts`'teki `None`/`Decimal(0)` ayrımına güvenir.

### B.6 Fallback mekanizması nasıl olacak?

BS/IS Engine'lerin hibrit modeliyle **tutarlı, iç içe geçmiş** iki seviyeli fallback:

- **Seviye 1 (BS/IS kendi içinde):** BS/IS Engine zaten kendi `source_mode`'unu (`direct_document` ya da `trial_balance_derived`) belirlemiş olarak Ratio Engine'e ulaşır. Ratio Engine bu kararı **sorgulamaz, tekrar üretmez** — olduğu gibi kullanır ve kendi `sources` listesine yansıtır (bkz. B.8).
- **Seviye 2 (BS veya IS'in hiç var olmaması):** BS sonucu hiç yoksa ama mizan sonucu varsa, Ratio Engine `trial_balance_fallback.py::extract_balance_sheet_facts_from_trial_balance`'ı **doğrudan kendisi çağırabilir** (BS Engine'i atlayarak) — ama yalnızca BS Engine'in kendisi de çalıştırılmamışsa. Bu, "her motor kendi fallback'ini kendi yapar, üst motor bunu tekrar icat etmez" ilkesiyle çelişmez çünkü BS Engine zaten çalıştırılabilir durumdaysa (registry'de kayıtlı, mizan mevcut) normal akışta zaten çalışır ve Ratio Engine ona doğrudan erişir; bu "kestirme" yalnızca BS Engine'in bir sebeple (ör. eski, migration-öncesi veri) hiç çalıştırılmadığı geçmiş dönemler için bir güvenlik ağıdır.

### B.7 Kaynak önceliği ne olacak?

Aynı finansal kavram (ör. `net_sales`) için birden fazla kaynak varsa öncelik sırası:

1. Balance Sheet/Income Statement Engine'in `direct_document` sonucu (en yüksek güvenilirlik).
2. Balance Sheet/Income Statement Engine'in `trial_balance_derived` sonucu.
3. Mizan sonucunun Ratio Engine tarafından doğrudan okunması (yalnızca B.6 Seviye 2 güvenlik ağı).

Bu öncelik, her oranın `reliability` alanına (Bölüm C.0) doğrudan yansır — kaynağı 1 olan oranlar `high`, kaynağı 2 olanlar `medium`, kaynağı 3 olanlar `medium_low` güvenilirlik taşır.

### B.8 Source tracking nasıl korunacak?

Ratio Engine'in ürettiği her `FinancialAnalysisResult` satırı için `financial_analysis_result_sources`'a **en az iki, tipik olarak üç-dört** satır yazılır: BS sonucu → `role=primary_analysis`, IS sonucu → `role=primary_analysis`, (kullanıldıysa) mizan sonucu → `role=trial_balance_fallback` ya da `role=supporting_analysis` (BS/IS zaten kendi mizan kaynağını kaydettiği için burada **çift kayıt yapılmaz** — Ratio Engine yalnızca *kendisinin* mizanı **doğrudan** kullandığı B.6 Seviye 2 durumunda kendi satırını ekler), (kullanıldıysa) önceki dönem BS/IS sonucu → `role=prior_period_reference`. Bu, A.6'da tespit edilen "şema zaten hazır" gözleminin doğrudan uygulanmasıdır — yeni bir izlenebilirlik mekanizması icat edilmez.

### B.9 Reconciliation nasıl çalışacak?

İki farklı reconciliation türü, ikisi de mevcut `reconciliation.py` (A.4) altyapısını **aynen** kullanır:

- **Çapraz-motor tutarlılık kontrolü:** Ratio Engine, BS'in `total_assets`'i ile IS'in türettiği bazı ara toplamların (ör. `net_profit` ile BS'teki dönem kârı hesabının, mizan üzerinden varsa) tutarlı olup olmadığını `compare_with_tolerance` ile kontrol eder; sonuç `result_json["cross_engine_reconciliation"]` altında `build_reconciliation_summary` şekliyle raporlanır.
- **BS/IS'in preliminary oranlarıyla tutarlılık:** Ratio Engine'in "authoritative" current_ratio'su ile BS Engine'in "preliminary" current_ratio'sunun (aynı formül, aynı girdi olduğu için) **matematiksel olarak birebir eşit olması beklenir** — bu bir reconciliation değil, bir **invariant**'tır (bkz. Bölüm D, L.4 boundary testleri bunu doğrular).

### B.10 Registry entegrasyonu nasıl olacak?

`FinancialRatioEngineAdapter`, `analysis_type = AnalysisType.FINANCIAL_RATIOS`, `requires_content = False` (hiç belge almaz) olarak `_ENGINE_BY_ANALYSIS_TYPE`'a eklenir. **Ama** mevcut `DetectedDocumentType`/`DocumentType` yönlendirme tablolarına **eklenmez** — çünkü Ratio Engine hiçbir zaman bir "yüklenen belge"nin sınıflandırma sonucu olarak tetiklenmez; tetiklenme mekanizması tamamen farklıdır (bkz. B.11). Bu, registry'nin `get_engine_for_analysis_type` fonksiyonunun (zaten var, `get_engine_for_detected_type`'tan bağımsız) tam olarak var olma sebebidir.

### B.11 Tetiklenme modeli — bulk upload akışından bağımsız yeni bir orkestrasyon yolu

BS/IS/TrialBalance "bir belge yüklendi → sınıflandırıldı → motor çalıştı" modeliyle tetiklenir. Ratio Engine'in tetiklenme sebebi **bir belge değil, bir "dönem artık BS+IS açısından tam" durumu**dur. Bu nedenle 4.3, bulk upload FAZ2/FAZ3'ün **içine** bir dördüncü motor olarak sıkıştırmak yerine, FAZ3 sonrası (transaction commit edildikten sonra) çalışan **ayrı bir orkestrasyon adımı** tasarlar: `app/services/ratio_recompute.py` (bkz. Bölüm M) — bulk upload confirm işlemi başarıyla bittiğinde, o batch'te BS ve/veya IS sonucu üretilmiş her (company_id, period_id) çifti için bu servis senkron ya da (Milestone 4.3 implementasyonunda karara bağlanacak, bkz. Q.4) asenkron olarak tetiklenir. Bu, A.7'de tespit edilen "BS ve IS'in ikisine birden bağımlı motor" sınıfı sorununu, FAZ2/FAZ3'ün karmaşıklığını artırmadan, **ayrı bir faz** ekleyerek çözer.

---

## Bölüm C — Oran Kategorileri ve Katalog

### C.0 Tüm kategoriler için ortak politikalar (tekrar etmemek için burada tek yerde)

**Decimal politikası:** Tüm iç hesaplama `Decimal` ile yapılır (asla `float`). Oran birimi `"ratio"` ise `safe_divide` varsayılanıyla (`quantize_exp="0.0001"`, `ROUND_HALF_UP`) 4 ondalığa yuvarlanır. `"percentage"` birimi, `ratio * 100` olarak üretilir ve yine 4 ondalık taşınır (görüntüleme katmanında 2 ondalığa indirilmesi bir sunum kararıdır, veri katmanının sorumluluğu değildir). `"days"` birimi `(360 veya gerçek gün sayısı) / devir_hızı` formülüyle üretilir, yine 4 ondalık `Decimal` olarak tutulur. `"currency"` birimi (ör. net_working_capital) hiç quantize edilmez, kaynak tutarların doğal hassasiyetinde kalır. Dışa (`result_json`) yazarken **her zaman** `decimal_to_json_safe` kullanılır — hesaplama içi mantık hiçbir yerde `float`'a düşmez.

**Bölme sıfır kontrolü:** İstisnasız `safe_divide` (`app.engines.common.ratio_formulas`) üzerinden — payda `None` ya da `0` ise sonuç `None`'dır, `ZeroDivisionError` fırlatılmaz, sonsuz/`NaN` üretilmez.

**Null politikası:** B.5'te tanımlanan üç seviyeli kural (girdi/hesaplama/kategori) tüm oranlar için geçerlidir; ayrıca aşağıda listelenmez, her kategorinin başında yalnızca **o kategoriye özgü ek koşullar** belirtilir.

**Güvenilirlik seviyeleri (`reliability`):** `high` (tüm girdiler `direct_document` kaynaklı, tahmin/ortalama yok), `medium` (en az bir girdi `trial_balance_derived` ya da ortalama-bakiye türetimi kullanıyor), `medium_low` (B.6 Seviye 2 güvenlik ağı ya da tahmini/varsayıma dayalı bir bileşen kullanılıyor), `not_calculable` (bir durum değeri, sayısal değer değil — girdi tamamen eksik).

**Kaynak önceliği (`source_priority`):** B.7'de tanımlanan 1→2→3 sıralaması; kategori tablolarında yalnızca standart dışı bir öncelik varsa ayrıca belirtilir.

**Türetilmiş ara alanlar (composite facts):** `BalanceSheetFacts`'te doğrudan bulunmayan ama birden çok oranda tekrar kullanılan bileşenler, Ratio Engine'in "Foundation" katmanında (Milestone 4.3A, bkz. Bölüm O) **bir kez** türetilir ve önbelleğe alınır: `total_liabilities = short_term_liabilities + long_term_liabilities`, `average_total_assets`, `average_equity`, `average_inventory`, `average_trade_receivables`, `average_trade_payables` (hepsi `(dönem_başı + dönem_sonu) / 2`, yalnızca önceki dönem BS facts'i mevcutsa hesaplanır; yoksa dönem-sonu bakiyeye düşülür ve `reliability` bir kademe düşürülür — bkz. ilgili oranlarda "ortalama/dönem-sonu" notu), `days_in_period` (`FinancialPeriod.end_date - start_date`, gerçek takvim günü — A.10). Bu ara katman **kendi başına bir oran değildir**, `result_json`'da `"derived_base_figures"` altında şeffafça raporlanır (Bölüm K) ki hangi oranın hangi ara değeri kullandığı izlenebilsin.

**Açıklama metni (`explanation`) şablonu:** Her oran için üç parçalı sabit şablon kullanılır — *(1) ne ölçer, (2) hangi yönü iyi/kötü sayılır (yüksek mi düşük mü tercih edilir, bağlama göre değişir uyarısıyla), (3) hangi girdilerden üretildi.* Tam metinler `app/engines/common/ratio_explanations.py`'de (Bölüm M) Türkçe olarak, `RatioFormulaMetadata.key` ile eşleşen sözlük halinde tutulacak — bu doküman her oran için şablonun **ilk iki parçasını** özetler, üçüncü parça `numerator_fields`/`denominator_fields`'ten otomatik türetilir (elle tekrar yazılmaz).

Aşağıdaki tablolarda **Alanlar** sütunu `canonical_facts` alan adlarını birebir kullanır (`bs.` = `BalanceSheetFacts`, `is.` = `IncomeStatementFacts`, `cf.` = `CashFlowFacts`, `der.` = türetilmiş ara alan, `prior.` = önceki dönem karşılığı, `bench.` = benchmark verisi).

---

### C.1 Likidite (Liquidity) — 8 oran

Kullanılan motorlar: Balance Sheet Engine (birincil), Trial Balance Engine (yalnızca current_ratio/quick_ratio'nun kaba hali için fallback — quick/cash ratio mizan-fallback'te **hesaplanamaz**, çünkü `cash_and_equivalents`/`inventory` mizan motorunda hiç üretilmiyor, bkz. A.11).

| Anahtar | Ad | Formül | Alanlar | Birim | Hesaplanamama şartı | Güvenilirlik |
|---|---|---|---|---|---|---|
| `current_ratio` | Cari Oran | `current_assets / short_term_liabilities` | `bs.current_assets`, `bs.short_term_liabilities` | ratio | biri `None` ya da payda 0 | high (direct) / medium (TB-derived) |
| `quick_ratio` | Asit-Test Oranı | `(current_assets - inventory) / short_term_liabilities` | `bs.current_assets`, `bs.inventory`, `bs.short_term_liabilities` | ratio | `inventory` yalnızca direct_document'te var — TB-derived'ta her zaman `not_calculable` | high (yalnızca direct) |
| `cash_ratio` | Nakit Oranı | `cash_and_equivalents / short_term_liabilities` | `bs.cash_and_equivalents`, `bs.short_term_liabilities` | ratio | `cash_and_equivalents` yalnızca direct_document'te var | high (yalnızca direct) |
| `net_working_capital` | Net İşletme Sermayesi | `current_assets - short_term_liabilities` | `bs.current_assets`, `bs.short_term_liabilities` | currency | biri `None` | high/medium |
| `working_capital_ratio` | İşletme Sermayesi Oranı | `current_assets / short_term_liabilities` (current_ratio ile aynı formül, farklı bağlamda raporlanır — BS Engine'deki `working_capital_ratio` ile **birebir aynı kaynak**, bkz. Bölüm D) | `bs.current_assets`, `bs.short_term_liabilities` | ratio | current_ratio ile aynı | current_ratio ile aynı |
| `defensive_interval_ratio` | Savunma Aralığı Oranı (gün) | `(cash_and_equivalents + trade_receivables) / (operating_expenses + cost_of_sales) * days_in_period` | `bs.cash_and_equivalents`, `bs.trade_receivables`, `is.operating_expenses`, `is.cost_of_sales`, `der.days_in_period` | days | herhangi biri `None`, ya da payda 0 | high (yalnızca direct BS + herhangi IS kaynağı) |
| `working_capital_to_total_assets` | İşletme Sermayesi / Toplam Aktif | `net_working_capital / total_assets` | `der.net_working_capital`, `bs.total_assets` | ratio | biri `None` | high/medium |
| `current_liability_coverage` | Kısa Vadeli Borç Karşılama (nakit bazlı) | `cash_and_equivalents / short_term_liabilities` | `bs.cash_and_equivalents`, `bs.short_term_liabilities` | ratio | `cash_and_equivalents` yalnızca direct_document'te var | high (yalnızca direct) — cash_ratio ile aynı hesap, farklı isimle bankacılık jargonunda kullanılır (Bölüm C.10'da tekrar referans verilir, **ikinci kez hesaplanmaz**) |

*Kaynak önceliği:* standart (B.7). *Ek not:* `quick_ratio`/`cash_ratio`, mizan-fallback modunda hesaplanamayan oranların **temsili örneğidir** — Bölüm C'deki tüm sonraki kategorilerde aynı kısıt (`cash_and_equivalents`/`inventory`/`trade_receivables`/`trade_payables` yalnızca `direct_document`'te var) ayrıca tekrar yazılmaz, yalnızca ilgili oranda "(yalnızca direct)" notuyla işaretlenir.

### C.2 Kârlılık (Profitability) — 10 oran

Kullanılan motorlar: Income Statement Engine (birincil, marjlar), Balance Sheet Engine (getiri oranlarının paydası için).

| Anahtar | Ad | Formül | Alanlar | Birim | Hesaplanamama şartı |
|---|---|---|---|---|---|
| `gross_profit_margin` | Brüt Kâr Marjı | `gross_profit / net_sales` | `is.gross_profit`, `is.net_sales` | percentage | biri `None`/payda 0 |
| `operating_profit_margin` | Faaliyet Kâr Marjı | `operating_profit / net_sales` | `is.operating_profit`, `is.net_sales` | percentage | aynı |
| `ebit_margin` | EBIT Marjı | `ebit / net_sales` | `is.ebit`, `is.net_sales` | percentage | `ebit` yalnızca doğrudan raporlanmışsa (bkz. `resolve_ebit` — asla `operating_profit`'ten sessizce kopyalanmaz, A.5) |
| `ebitda_margin` | EBITDA Marjı | `ebitda / net_sales` | `is.ebitda`, `is.net_sales` | percentage | `ebitda` için `depreciation_and_amortization` de gerekli |
| `net_profit_margin` | Net Kâr Marjı | `net_profit / net_sales` | `is.net_profit`, `is.net_sales` | percentage | `net_profit` yalnızca 69x hesapları gerçekten raporlanmışsa (A.11) |
| `pretax_profit_margin` | Vergi Öncesi Kâr Marjı | `profit_before_tax / net_sales` | `is.profit_before_tax`, `is.net_sales` | percentage | biri `None` |
| `return_on_assets` | Aktif Kârlılığı (ROA) | `net_profit / average_total_assets` | `is.net_profit`, `der.average_total_assets` | percentage | ortalama yoksa `bs.total_assets` (dönem sonu) ile, `reliability=medium` |
| `return_on_equity` | Özkaynak Kârlılığı (ROE) | `net_profit / average_equity` | `is.net_profit`, `der.average_equity` | percentage | aynı ortalama/dönem-sonu kuralı |
| `return_on_capital_employed` | Kullanılan Sermaye Kârlılığı (ROCE) | `ebit / (total_assets - short_term_liabilities)` | `is.ebit`, `bs.total_assets`, `bs.short_term_liabilities` | percentage | herhangi biri `None` |
| `return_on_invested_capital` | Yatırılan Sermaye Kârlılığı (ROIC) | `ebit * (1 - efektif_vergi_oranı) / (equity + long_term_liabilities)` | `is.ebit`, `der.effective_tax_rate` (Bölüm C.11'den), `bs.equity`, `bs.long_term_liabilities` | percentage | `effective_tax_rate` hesaplanamıyorsa (vergi beyannamesi yoksa) **varsayılan olarak Türkiye kurumlar vergisi kanuni oranı kullanılmaz** — `None` döner, tahmini oran fabrikasyon edilmez (`reliability=not_calculable` bu durumda) |

*Kaynak önceliği:* standart. *Not:* `ebit`/`ebitda` tabanlı tüm oranlar için 4.3, IS Engine'in v1 politikasını (A.5 — asla sessiz kopyalama) **aynen** miras alır.

### C.3 Faaliyet / Devir Hızları (Activity) — 10 oran

Kullanılan motorlar: Balance Sheet + Income Statement birlikte. **Tamamı yalnızca `direct_document` BS sonucunda** hesaplanabilir (envanter/alacak/borç ayrıntısı gerektirir, A.11).

| Anahtar | Ad | Formül | Alanlar | Birim |
|---|---|---|---|---|
| `inventory_turnover` | Stok Devir Hızı | `cost_of_sales / average_inventory` | `is.cost_of_sales`, `der.average_inventory` | ratio |
| `receivables_turnover` | Alacak Devir Hızı | `net_sales / average_trade_receivables` | `is.net_sales`, `der.average_trade_receivables` | ratio |
| `payables_turnover` | Borç Devir Hızı | `cost_of_sales / average_trade_payables` | `is.cost_of_sales`, `der.average_trade_payables` | ratio |
| `asset_turnover` | Aktif Devir Hızı | `net_sales / average_total_assets` | `is.net_sales`, `der.average_total_assets` | ratio |
| `fixed_asset_turnover` | Duran Varlık Devir Hızı | `net_sales / non_current_assets` | `is.net_sales`, `bs.non_current_assets` | ratio |
| `working_capital_turnover` | İşletme Sermayesi Devir Hızı | `net_sales / net_working_capital` | `is.net_sales`, `der.net_working_capital` | ratio |
| `days_inventory_outstanding` | Stokta Kalma Süresi (gün) | `days_in_period / inventory_turnover` | `der.days_in_period`, `der.inventory_turnover` | days |
| `days_sales_outstanding` | Alacak Tahsil Süresi (gün) | `days_in_period / receivables_turnover` | `der.days_in_period`, `der.receivables_turnover` | days |
| `days_payables_outstanding` | Borç Ödeme Süresi (gün) | `days_in_period / payables_turnover` | `der.days_in_period`, `der.payables_turnover` | days |
| `cash_conversion_cycle` | Nakit Dönüşüm Süresi (gün) | `days_inventory_outstanding + days_sales_outstanding - days_payables_outstanding` | üstteki üç türetilmiş gün değeri | days |

*Ek not:* Ortalama bakiye hesaplanabiliyorsa `reliability=high`, dönem-sonu bakiyeye düşülüyorsa `reliability=medium` (C.0'daki genel kural).

### C.4 Borçluluk / Leverage — 10 oran

| Anahtar | Ad | Formül | Alanlar | Birim |
|---|---|---|---|---|
| `debt_ratio` | Borç Oranı | `total_liabilities / total_assets` | `der.total_liabilities`, `bs.total_assets` | ratio |
| `equity_ratio` | Özkaynak Oranı | `equity / total_assets` | `bs.equity`, `bs.total_assets` | ratio |
| `debt_to_equity` | Borç/Özkaynak Oranı | `total_liabilities / equity` | `der.total_liabilities`, `bs.equity` | ratio |
| `long_term_debt_to_equity` | Uzun Vadeli Borç/Özkaynak | `long_term_liabilities / equity` | `bs.long_term_liabilities`, `bs.equity` | ratio |
| `short_term_debt_ratio` | Kısa Vadeli Borç Oranı | `short_term_liabilities / total_liabilities` | `bs.short_term_liabilities`, `der.total_liabilities` | ratio |
| `financial_leverage_multiplier` | Finansal Kaldıraç Çarpanı | `total_assets / equity` | `bs.total_assets`, `bs.equity` | ratio |
| `interest_coverage_ratio` | Faiz Karşılama Oranı (EBIT bazlı) | `ebit / financing_expenses` | `is.ebit`, `is.financing_expenses` | ratio |
| `ebitda_coverage_ratio` | EBITDA ile Faiz Karşılama | `ebitda / financing_expenses` | `is.ebitda`, `is.financing_expenses` | ratio |
| `debt_to_ebitda` | Borç/EBITDA | `total_liabilities / ebitda` | `der.total_liabilities`, `is.ebitda` | ratio |
| `fixed_charge_coverage` | Sabit Ödeme Karşılama Oranı | `(ebit + operating_lease_payments) / (financing_expenses + operating_lease_payments)` | `is.ebit`, `is.financing_expenses`, `operating_lease_payments` (**bugün canonical_facts'te yok**) | ratio — **`not_calculable` (girdi hiç yok, kiralama gideri ayrıştırması bugün hiçbir motorda mevcut değil; formül gelecekteki genişletme için burada tasarlanmıştır)** |

*Ek not:* `fixed_charge_coverage`, "bugünkü veriyle yapılamayan analiz"in katalogdaki ilk somut örneğidir — dürüstçe `not_calculable` olarak işaretlenir, formülü tasarlanır ama hiçbir zaman sahte bir değer üretmez.

### C.5 Verimlilik (Efficiency) — 8 oran

Gider yapısının satış/faaliyet ölçeğine oranını inceleyen kategori (Faaliyet/Activity kategorisinden farkı: burada devir hızı değil, **gider disiplini** ölçülür).

| Anahtar | Ad | Formül | Alanlar | Birim |
|---|---|---|---|---|
| `operating_expense_ratio` | Faaliyet Gideri Oranı | `operating_expenses / net_sales` | `is.operating_expenses`, `is.net_sales` | ratio |
| `cost_of_sales_ratio` | Satışların Maliyeti Oranı | `cost_of_sales / net_sales` | `is.cost_of_sales`, `is.net_sales` | ratio |
| `overhead_ratio` | Genel Gider Oranı | `(operating_expenses + other_operating_expenses) / net_sales` | `is.operating_expenses`, `is.other_operating_expenses`, `is.net_sales` | ratio |
| `ebit_to_opex` | EBIT / Faaliyet Gideri | `ebit / operating_expenses` | `is.ebit`, `is.operating_expenses` | ratio |
| `non_operating_income_dependency` | Faaliyet Dışı Gelir Bağımlılığı | `other_operating_income / operating_profit` | `is.other_operating_income`, `is.operating_profit` | ratio — yüksek değer, "asıl faaliyetten değil yan gelirlerden kâr" uyarısı taşır |
| `financing_expense_to_sales` | Finansman Gideri / Satış | `financing_expenses / net_sales` | `is.financing_expenses`, `is.net_sales` | ratio |
| `asset_utilization_efficiency` | Varlık Kullanım Verimliliği | `net_sales / total_assets` (asset_turnover'la aynı formül, farklı kategoride "verimlilik" bağlamıyla raporlanır — **ikinci kez hesaplanmaz**, C.3'teki `asset_turnover` sonucuna referans verir) | `is.net_sales`, `bs.total_assets` | ratio |
| `equity_efficiency` | Özkaynak Kullanım Verimliliği | `net_sales / equity` | `is.net_sales`, `bs.equity` | ratio |

### C.6 Büyüme (Growth) — 7 oran

Tamamı **önceki dönem BS/IS `facts`'i gerektirir** (B.4) — mevcut değilse tüm kategori `not_calculable`. Formüller, BS/IS motorlarının zaten ürettiği `horizontal_analysis` ile **aynı matematiği** kullanır (Bölüm D — tekrar icat edilmez, yalnızca dönem-bazlı tekil metrikler yerine oran-bazlı büyüme metrikleri olarak yeniden sunulur).

| Anahtar | Ad | Formül | Alanlar | Birim |
|---|---|---|---|---|
| `sales_growth` | Satış Büyümesi | `(net_sales - prior.net_sales) / abs(prior.net_sales) * 100` | `is.net_sales`, `prior.net_sales` | percentage |
| `gross_profit_growth` | Brüt Kâr Büyümesi | aynı desen | `is.gross_profit`, `prior.gross_profit` | percentage |
| `ebitda_growth` | EBITDA Büyümesi | aynı desen | `is.ebitda`, `prior.ebitda` | percentage |
| `net_profit_growth` | Net Kâr Büyümesi | aynı desen | `is.net_profit`, `prior.net_profit` | percentage |
| `total_assets_growth` | Toplam Aktif Büyümesi | aynı desen | `bs.total_assets`, `prior.total_assets` | percentage |
| `equity_growth` | Özkaynak Büyümesi | aynı desen | `bs.equity`, `prior.equity` | percentage |
| `sustainable_growth_rate` | Sürdürülebilir Büyüme Oranı | `return_on_equity * (1 - kar_dagitim_orani)` | `der.return_on_equity`, `kar_dagitim_orani` (**bugün canonical_facts'te/hiçbir motorda yok — kâr dağıtımı/temettü verisi mevcut değil**) | ratio — **`not_calculable`** (formül tasarlanmıştır, girdi yoktur; kâr dağıtım oranı olmadan güvenli bir varsayım (ör. %0 dağıtım) yapılmaz çünkü bu sahte kesinlik yaratır) |

### C.7 Yatırım (Investment) — 6 oran

Bu kategori, Türkiye'deki halka açık olmayan KOBİ/orta ölçekli şirketler için **büyük ölçüde uygulanamaz** — dürüstçe böyle işaretlenir; formüller halka açık şirketler ve gelecekteki manuel piyasa-verisi girişi için tasarlanır.

| Anahtar | Ad | Formül | Alanlar | Hesaplanamama şartı |
|---|---|---|---|---|
| `book_value_per_share` | Hisse Başına Defter Değeri | `equity / share_count` | `bs.equity`, `share_count` (**yok**) | her zaman `not_calculable` (hisse sayısı verisi hiçbir motorda yok) |
| `earnings_per_share` | Hisse Başına Kâr (EPS) | `net_profit / share_count` | `is.net_profit`, `share_count` (**yok**) | her zaman `not_calculable` |
| `price_to_book` | Piyasa Değeri / Defter Değeri | `market_cap / equity` | `market_cap` (**yok — Bölüm G'de tasarlanan gelecekteki manuel/harici veri girişi**), `bs.equity` | her zaman `not_calculable` (bugün) |
| `retained_earnings_ratio` | Dağıtılmamış Kâr Oranı | `retained_earnings / equity` | `retained_earnings` (BS'te ayrı bir kalem olarak ayrıştırılmıyor — 5 sınıfının alt kırılımı gerekir) | `not_calculable` — BS extractor'ının bugünkü ayrıştırma derinliği yetersiz |
| `return_on_invested_capital_investment_view` | Yatırım Getirisi (Yatırımcı Bakışı) | `net_profit / (equity + long_term_liabilities)` (ROIC'in basitleştirilmiş, vergi-düzeltmesiz hali — C.2'deki `return_on_invested_capital` ile karıştırılmamalı, burada vergi ayarlaması yok) | `is.net_profit`, `bs.equity`, `bs.long_term_liabilities` | biri `None` — **bu, kategorideki tek gerçekten hesaplanabilir oran** |
| `capital_intensity` | Sermaye Yoğunluğu | `total_assets / net_sales` | `bs.total_assets`, `is.net_sales` | biri `None`/payda 0 |

### C.8 Nakit Akışı (Cash Flow) — 6 oran

Tamamı `CashFlowFacts` gerektirir — **Cash Flow Engine Milestone 4.4'te gelecek**, bu kategori 4.3 devreye girdiğinde **tamamen `not_calculable`** olacak, ama formüller ve `RatioFormulaMetadata` kayıtları şimdiden `RATIO_REGISTRY`'ye eklenir (böylece 4.4 devreye girdiğinde yalnızca veri akışı bağlanır, formül tasarımı tekrar yapılmaz).

| Anahtar | Ad | Formül | Alanlar |
|---|---|---|---|
| `operating_cash_flow_margin` | Faaliyet Nakit Akışı Marjı | `operating_cash_flow / net_sales` | `cf.operating_cash_flow`, `is.net_sales` |
| `free_cash_flow_margin` | Serbest Nakit Akışı Marjı | `free_cash_flow / net_sales` | `cf.free_cash_flow`, `is.net_sales` |
| `cash_flow_to_debt` | Nakit Akışı / Toplam Borç | `operating_cash_flow / total_liabilities` | `cf.operating_cash_flow`, `der.total_liabilities` |
| `cash_return_on_assets` | Nakit Bazlı Aktif Getirisi | `operating_cash_flow / average_total_assets` | `cf.operating_cash_flow`, `der.average_total_assets` |
| `cash_interest_coverage` | Nakit Bazlı Faiz Karşılama | `operating_cash_flow / financing_expenses` | `cf.operating_cash_flow`, `is.financing_expenses` |
| `operating_cash_flow_ratio` | Faaliyet Nakit Akışı / Kısa Vadeli Borç | `operating_cash_flow / short_term_liabilities` | `cf.operating_cash_flow`, `bs.short_term_liabilities` |

### C.9 Piyasa (Market) — 5 oran

Yalnızca halka açık/BIST şirketleri ve gelecekteki manuel piyasa-verisi girişi (Bölüm G) için — bugün **tamamı `not_calculable`**.

| Anahtar | Ad | Formül | Alanlar |
|---|---|---|---|
| `price_earnings_ratio` | Fiyat/Kazanç Oranı (F/K) | `market_price_per_share / earnings_per_share` | `market_price_per_share` (yok), `der.earnings_per_share` (C.7'den, zaten `not_calculable`) |
| `ev_to_ebitda` | Firma Değeri / EBITDA | `enterprise_value / ebitda` | `enterprise_value` (yok), `is.ebitda` |
| `dividend_yield` | Temettü Verimi | `dividend_per_share / market_price_per_share` | ikisi de yok |
| `market_to_book` | Piyasa/Defter Oranı | C.7'deki `price_to_book` ile aynı — burada piyasa bağlamıyla tekrar referans verilir, **ikinci kez hesaplanmaz** | — |
| `earnings_yield` | Kazanç Verimi | `earnings_per_share / market_price_per_share` | ikisi de yok |

### C.10 Bankacılık (Banking) — 6 oran

Banka kredi tahsis biriminin doğrudan kullandığı, önceki kategorilerdeki oranların **bankacılık bağlamında yeniden gruplanmış** hali — çoğu **zaten hesaplanmış** oranlara referans verir (kod tekrarı yok), yalnızca ikisi bu kategoriye özgü yeni formüldür.

| Anahtar | Ad | Formül | Kaynak |
|---|---|---|---|
| `tangible_net_worth` | Maddi Özkaynak | `equity - intangible_assets` | `bs.equity`, `intangible_assets` (**BS'te ayrı ayrıştırılmıyor — `not_calculable`**, formül tasarlanmıştır) |
| `net_debt_to_ebitda` | Net Borç / EBITDA | `(total_liabilities - cash_and_equivalents) / ebitda` | `der.total_liabilities`, `bs.cash_and_equivalents` (yalnızca direct), `is.ebitda` |
| `debt_service_coverage_ratio` | Borç Servis Karşılama Oranı (DSCR) | `ebitda / (financing_expenses + kisa_vadeli_borc_anapara_taksiti)` | `is.ebitda`, `is.financing_expenses`, anapara taksiti (**yok — kredi sözleşmesi verisi hiçbir motorda yok, `not_calculable`**) |
| `banking_current_ratio` | Bankacılık Cari Oranı (eşik yorumlu) | C.1'deki `current_ratio` — burada banka eşiği (tipik ≥1.20 beklenir) ile birlikte yorumlanır, **ikinci kez hesaplanmaz** | C.1 |
| `banking_leverage_threshold` | Bankacılık Kaldıraç Eşiği | C.4'teki `debt_to_equity` — banka eşiği (tipik ≤2.50 beklenir) ile birlikte yorumlanır, **ikinci kez hesaplanmaz** | C.4 |
| `quick_liquidity_for_credit` | Kredi Değerlendirmesi için Hızlı Likidite | C.1'deki `cash_ratio` ile aynı — bankacılık jargonunda ayrı isimle anılır, **ikinci kez hesaplanmaz** | C.1 |

### C.11 IFRS-Uyumlu Ek Göstergeler — 4 oran

**Önemli dürüstlük notu:** FINOS bugün Tekdüzen Hesap Planı (Türkiye Muhasebe Sistemi Uygulama Genel Tebliği tabanlı) üzerinde çalışıyor (`app/trial_balance/financial_statements.py::build_financial_statements`, `"basis": "Turkish Uniform Chart of Accounts"`). Gerçek IFRS (TFRS) mali tabloları (ör. diğer kapsamlı gelir, TFRS 16 kiralama, TFRS 9 beklenen kredi zararı karşılıkları) **hiçbir motor tarafından ayrıştırılmıyor**. Bu kategori, gelecekte bir TFRS-mapping katmanı eklendiğinde kullanılacak formülleri **şimdiden tasarlar** ama bugün tamamı `not_calculable`'dır — sahte bir "IFRS uyumluluğu" izlenimi verilmez.

| Anahtar | Ad | Formül | Alanlar | Durum |
|---|---|---|---|---|
| `effective_tax_rate` | Efektif Vergi Oranı | `(profit_before_tax - net_profit) / profit_before_tax` | `is.profit_before_tax`, `is.net_profit` | **Tek istisna — bugün hesaplanabilir**, IFRS'e özgü değil ama bu kategoride tutulur çünkü C.2'deki ROIC'in girdisidir |
| `comprehensive_income_ratio` | Diğer Kapsamlı Gelir Oranı | `other_comprehensive_income / net_profit` | `other_comprehensive_income` (yok) | `not_calculable` |
| `lease_adjusted_debt_ratio` | Kiralama-Düzeltmeli Borç Oranı (TFRS 16) | `(total_liabilities + lease_liabilities) / total_assets` | `lease_liabilities` (yok) | `not_calculable` |
| `expected_credit_loss_coverage` | Beklenen Kredi Zararı Karşılama (TFRS 9, finansal kuruluşlar için) | `ecl_provision / gross_receivables` | ikisi de yok | `not_calculable` — yalnızca finansal kuruluş müşterileri için anlamlı, FINOS bugün bu sektörü hedeflemiyor |

### C.12 Risk — 5 oran

| Anahtar | Ad | Formül | Alanlar | Durum |
|---|---|---|---|---|
| `altman_z_score` | Altman Z-Skoru (İflas Riski) | `1.2*(WC/TA) + 1.4*(RE/TA) + 3.3*(EBIT/TA) + 0.6*(E/TL) + 1.0*(Sales/TA)` | `der.net_working_capital`, `retained_earnings` (yok, C.7), `is.ebit`, `bs.total_assets`, `bs.equity`, `der.total_liabilities`, `is.net_sales` | `not_calculable` (retained_earnings eksik) — formül tasarlanmıştır, `retained_earnings` çözüldüğünde (gelecek) aktifleşir |
| `altman_z_score_simplified` | Basitleştirilmiş Z-Skor (özel şirketler için, RE hariç) | Yukarıdaki formülün `RE/TA` bileşenini çıkaran, literatürde tanımlı bir varyant (ör. Altman'ın 1983 özel-şirket modeli) | aynı, `retained_earnings` hariç | **Düzeltme (2. tur onay, madde 6):** kaynaklandırılmamış/yeniden kalibre edilmiş katsayılarla implemente edilmeyecek — güvenilir, açıkça atıflı (citation'lı) bir katsayı seti olmadan **`not_calculable`/kapsam dışı** kalır. FINOS'a özgü "yeniden kalibre edilmiş ağırlık" **asla** üretilmeyecek. |
| `operating_leverage_degree` | Faaliyet Kaldıraç Derecesi | `% ebit_degisimi / % net_sales_degisimi` (iki dönem gerektirir) | `is.ebit`, `prior.ebit`, `is.net_sales`, `prior.net_sales` | önceki dönem yoksa `not_calculable` |
| `earnings_volatility` | Kazanç Oynaklığı | son N dönemin `net_profit_margin` standart sapması | ≥3 dönem geçmiş veri gerekir | bugün yalnızca 2 dönem (cari+önceki) destekleniyor — `not_calculable`, gelecekte çok-dönemli geçmiş veri deposu (Bölüm N risk analizi) gerektirir |
| `liquidity_risk_flag` | Likidite Risk Bayrağı | `current_ratio < 1.0 VEYA net_working_capital < 0` kuralına dayalı boolean | `der.current_ratio`, `der.net_working_capital` | oranlar hesaplanabiliyorsa her zaman hesaplanabilir — bu, sayısal değil **kategorik** bir "oran"dır, Health Score/Recommendation Engine'in doğrudan girdisi |

### C.13 Sermaye Yapısı (Capital Structure) — 4 oran

| Anahtar | Ad | Formül | Alanlar |
|---|---|---|---|
| `equity_multiplier` | Özkaynak Çarpanı | C.4'teki `financial_leverage_multiplier` ile aynı — sermaye yapısı bağlamında tekrar referans verilir, **ikinci kez hesaplanmaz** | C.4 |
| `long_term_capital_ratio` | Uzun Vadeli Sermaye Oranı | `(equity + long_term_liabilities) / total_assets` | `bs.equity`, `bs.long_term_liabilities`, `bs.total_assets` |
| `permanent_capital_to_fixed_assets` | Sürekli Sermaye / Duran Varlık | `(equity + long_term_liabilities) / non_current_assets` | `bs.equity`, `bs.long_term_liabilities`, `bs.non_current_assets` |
| `capitalization_ratio` | Sermayelendirme Oranı | `long_term_liabilities / (long_term_liabilities + equity)` | `bs.long_term_liabilities`, `bs.equity` |

### C.14 Çalışma Sermayesi (Working Capital) — 4 oran

| Anahtar | Ad | Formül | Alanlar |
|---|---|---|---|
| `working_capital_needs` | İşletme Sermayesi İhtiyacı (BFR/WCR) | `(inventory + trade_receivables) - trade_payables` | `bs.inventory`, `bs.trade_receivables`, `bs.trade_payables` (yalnızca direct) |
| `working_capital_to_sales` | İşletme Sermayesi / Satış | `net_working_capital / net_sales` | `der.net_working_capital`, `is.net_sales` |
| `cash_conversion_efficiency` | Nakit Dönüşüm Verimliliği | `operating_cash_flow / net_working_capital` | `cf.operating_cash_flow` (yok — Milestone 4.4), `der.net_working_capital` | `not_calculable` bugün |
| `working_capital_funding_gap` | İşletme Sermayesi Finansman Açığı | `working_capital_needs - net_working_capital` | `der.working_capital_needs`, `der.net_working_capital` |

### C.15 Katalog özeti

14 kategori, toplam **93 benzersiz oran tanımı** (bazı oranlar birden fazla kategoride yorumsal bağlamla tekrar referans verilir ama yalnızca **bir kez** hesaplanır — bkz. Bölüm D). Bugün doğrudan hesaplanabilir: ~55. Yalnızca `direct_document` BS gerektiren (mizan-fallback'te `null`): ~20. Milestone 4.4 (Cash Flow) beklenen: ~10. Hiçbir motorda bugün girdisi olmayan, formülü tasarlanmış ama dürüstçe `not_calculable`: ~15 (retained_earnings, hisse sayısı, piyasa verisi, kiralama/TFRS 16, kâr dağıtımı, anapara taksiti gibi bugün FINOS'un hiçbir motorunun ayrıştırmadığı girdilere bağlı olanlar). Bu oranlar **kataloğa dahil edilmiştir** çünkü kullanıcı 100-150 oranlık kapsamlı bir katalog istemiştir ve gelecekteki genişlemeler için formül tasarımının şimdiden yapılmış olması değerlidir — ama hiçbiri implementasyonda sahte bir değerle "çalışıyormuş gibi" görünmeyecektir.

---

## Bölüm D — Mevcut Balance Sheet/Income Statement Motorlarıyla Entegrasyon (Sıfır Kod Tekrarı)

### D.1 Sorun tanımı

A.5'te tespit edildiği gibi, BS Engine (`compute_preliminary_structural_ratios`, `compute_working_capital`) ve IS Engine (`compute_margins`) bugün current_ratio/debt_ratio/equity_ratio/debt_to_equity/net_working_capital/working_capital_ratio ve gross/operating/net kâr marjlarını **kendi başlarına** hesaplıyor. Ratio Engine bunları **authoritative** olarak yeniden hesaplayacak. Aynı formülü iki yerde tutmak (D'nin çözmesi gereken risk): formül bir yerde değişirse diğeri unutulur, iki motor farklı yuvarlama/politika kullanabilir, test yükü ikiye katlanır.

### D.2 Çözüm — "Tek formül kaynağı" ilkesinin somutlaştırılması

**Karar 1 — `RATIO_REGISTRY` tek formül kaynağıdır, BS/IS Engine'ler kendi hesaplama fonksiyonlarını SİLMEZ, `ratio_formulas.RATIO_REGISTRY`'YE YÖNLENDİRİR.** `compute_preliminary_structural_ratios` ve `compute_margins`, Milestone 4.3'ten sonra **kendi Decimal aritmetiğini bırakır**, `app.engines.common.ratio_formulas.get_ratio_formula("current_ratio")` üzerinden aldıkları `RatioFormulaMetadata`'nın `numerator_fields`/`denominator_fields`'ini okuyarak `safe_divide`'ı **aynı şekilde** çağırır — formül tanımı (hangi alan bölünür) merkezde, çağrı yeri (hangi motor ne zaman çağırır) yerelde kalır. Bu, "iki yerde ayrı current_ratio tanımı yok" gerekliliğini (kullanıcı talebi, Bölüm 5) DB seviyesinde değil ama **kod seviyesinde** kesin olarak sağlar: `RATIO_REGISTRY["current_ratio"]` değişirse her iki çağıran da otomatik güncellenir.

**Karar 2 — "preliminary" etiketi kalır, ama artık gerçekten aynı sayıyı üretir.** BS/IS Engine'lerin `result_json["preliminary_structural_ratios"]`/`result_json["margins"]` alanları **isim olarak korunur** (geriye uyumluluk — mevcut testler/tüketiciler bu alanları okuyor) ama artık Ratio Engine'in üreteceği authoritative sonuçla **matematiksel olarak birebir aynı** değeri taşır (B.9'daki invariant). "Preliminary" kelimesi artık "muhtemelen farklı olabilir" anlamına gelmez, "yalnızca bu tek tabloya dayalı, çapraz-doğrulanmamış bir ön-görünüm" anlamına gelir — BS Engine'in kendisi Ratio Engine'i bekleyemez (BS analiz tek başına da anlamlı olmalı, kullanıcı BS'i tek başına yükleyebilir), bu yüzden "preliminary" ifadesi **kullanım bağlamını** doğru tarif etmeye devam eder, hesaplama kaynağını değil.

**Karar 3 — `app/trial_balance/ratios.py` DOKUNULMAZ (A.8 kararının teyidi).** Mizanın kendi `build_ratios`'u (float tabanlı, farklı sözleşme) Ratio Engine'in `RATIO_REGISTRY`'sine **taşınmaz, silinmez, değiştirilmez** — bu, mizan analiz sonucunun kendi iç sözleşmesidir ve Milestone 4.3'ün kapsamı dışındadır (Q.2'de netleştirilir). Ratio Engine kendi current_ratio'sunu hesaplarken mizan-fallback modundaysa `trial_balance_fallback.py` üzerinden `canonical_facts`'e döner, `app/trial_balance/ratios.py`'yi hiç import etmez — A.1'deki "trial_balance/**'e kod bağımlılığı yok" ilkesi 4.3'te de korunur.

**Karar 4 — Explainability tek kaynaktan gelir.** `ProvenanceEntry` üretimi de merkezileşir: `ratio_formulas.py`'ye eklenecek `compute_registered_ratio(key, facts_dict) -> tuple[Decimal | None, ProvenanceEntry]` fonksiyonu (Milestone 4.3A) hem değeri hem provenance kaydını **aynı çağrıda** üretir; BS/IS Engine'ler ve Ratio Engine bu tek fonksiyonu çağırır. Böylece "current_ratio nasıl hesaplandı" açıklaması her iki motorda **birebir aynı metni** üretir (Bölüm I).

### D.3 Kod tekrarını somut olarak ölçen kabul kriteri

Implementasyon sonrası doğrulanacak (test stratejisi, Bölüm L.4): `current_ratio`, `debt_ratio`, `equity_ratio`, `debt_to_equity`, `net_working_capital`, `working_capital_ratio`, `gross_profit_margin`, `operating_profit_margin`, `net_profit_margin` formüllerinin **hesaplama mantığı** (`numerator_fields`/`denominator_fields`/`quantize` kuralı) kod tabanında **tam olarak bir yerde** (`RATIO_REGISTRY`) tanımlı olmalı; `grep -rn "current_assets.*short_term_liabilities" app/engines/` çalıştırıldığında yalnızca `ratio_formulas.py`'deki kayıt ve onu çağıran ince sarmalayıcılar görünmeli, ikinci bir bağımsız Decimal bölme ifadesi görünmemeli.

---

## Bölüm E — Financial Health Score (100 Puanlık Sistem)

### E.1 Tasarım hedefi

Health Score, 100'e kadar puanlanan, **kategori bazlı ağırıklandırılmış**, eksik veriye karşı dayanıklı (missing-data-tolerant), CFO'nun "şirketim genel olarak ne durumda" sorusuna tek sayı ile ama **her zaman açıklanabilir şekilde** cevap veren bir kompozit skordur.

### E.2 Kategori seçimi ve gerekçesi

Kullanıcının önerdiği 7 kategori (Likidite, Kârlılık, Borçluluk, Verimlilik, Operasyon, Nakit, Büyüme) esas alınır; "Operasyon" kategorisi, Bölüm C'nin "Faaliyet/Activity" (devir hızları) kategorisiyle eşlenir (isim tutarlılığı için Health Score bağlamında "Operasyon" kullanılır, ratio kataloğunda "Faaliyet" — aynı 10 oranı kapsar).

### E.3 Alternatif ağırık modelleri — karşılaştırma

**Model A — Eşit Ağırlık (her kategori 100/7 ≈ %14.3):** Basit, açıklaması kolay, ama finansal gerçekliği yansıtmaz — bir KOBİ için likidite ve borçluluk, büyüme ve piyasa göstergelerinden çok daha kritiktir; eşit ağırık "her şey eşit önemli" gibi yanlış bir mesaj verir.

**Model B — Kredi-Odaklı Ağırık (Likidite %25, Borçluluk %25, Kârlılık %20, Nakit %15, Operasyon %10, Büyüme %5):** Banka bakış açısını öne çıkarır ama CFO'nun büyüme/verimlilik önceliklerini yeterince yansıtmaz; Credit Score Engine (Bölüm F) zaten bu bakış açısını ayrı olarak sağlıyor — Health Score'un bunu tekrar etmesi redundant.

**Model C — Dengeli, Ampirik Ağırlıklandırma (önerilen):** Likidite %18, Kârlılık %22, Borçluluk %18, Operasyon(Faaliyet) %14, Verimlilik %10, Nakit %10, Büyüme %8. Gerekçe: Kârlılık en yüksek ağırlığı alır çünkü sürdürülebilirliğin birincil göstergesidir (kısa vadede likidite sorunları kârlı bir şirkette çözülebilir, kârsız bir şirkette likidite geçicidir); Likidite ve Borçluluk ikinci sırada çünkü kısa-orta vadeli hayatta kalmayı belirler; Nakit düşük ağırlıklı çünkü Milestone 4.4'e kadar çoğu zaman `not_calculable` olacak (bkz. E.5 eksik-veri kuralı — ağırlığı otomatik olarak diğerlerine dağıtılır); Büyüme en düşük ağırlıklı çünkü **tek dönemlik** veriyle (önceki dönem yoksa) hiç hesaplanamayabilir.

**Önerilen model: C.** Gerekçe: Model A finansal önceliklendirmeyi yansıtmaz; Model B, Credit Score Engine'in kapsamıyla örtüşür ve Health Score'u "ikinci bir kredi notu"na indirger (kullanıcının ayrı ayrı istediği iki farklı araç, Bölüm 6 vs. Bölüm 7, aynı sonucu üretmemeli). Model C, CFO/genel yönetim bakış açısını (kârlılık ve sürdürülebilirlik önceliği) yansıtırken banka bakış açısını (likidite+borçluluk toplamı %36) da göz ardı etmez.

### E.4 Kategori içi puanlama

Her kategori kendi içinde 0-100 puanlanır, sonra kategori ağırlığıyla çarpılıp toplanır. Kategori içi puanlama, ilgili kategorideki her oranın **sektöre bağımsız, muhasebe-teorisi tabanlı eşik bantları** ile (Milestone 4.3D'de netleştirilecek, örnek: current_ratio için <1.0→0puan, 1.0-1.5→50puan, 1.5-2.5→100puan, >2.5→80puan [aşırı likidite atıl varlık işareti]) doğrusal enterpolasyonla 0-100'e haritalanmasının **ortalamasıdır**. Sektör benchmark'ı mevcutsa (Bölüm G), eşik bantları sektöre özgü hale gelir (Milestone 4.3C sonrası iyileştirme, 4.3D'nin ilk sürümü sektörden bağımsız sabit bantlarla başlar — dürüst MVP).

### E.5 Eksik veri yönetimi — Health Score'un en kritik tasarım kararı

**Kural:** Bir kategorideki oranların **hiçbiri** hesaplanamıyorsa (ör. Nakit kategorisi, Cash Flow Engine yokken), o kategori **puanlamaya dahil edilmez** ve ağırlığı **kalan hesaplanabilir kategorilere orantılı olarak yeniden dağıtılır** (yeniden-normalizasyon). Bir kategoride oranların **bir kısmı** hesaplanabiliyorsa, kategori puanı yalnızca hesaplanabilen oranların ortalamasıdır (eksik oranlar o kategorinin iç ortalamasında da 0 sayılmaz, sadece dışlanır). Bu iki kural, Health Score'un "eksik veri nedeniyle sahte düşük puan" üretmesini engeller — **`total_confidence`** adlı ek bir alan (Bölüm K) her zaman "kaç kategorinin kaç oranı gerçekten hesaplandı" oranını (ör. `%68 veri kapsamı`) şeffafça raporlar, böylece 60 puanlık bir skor "gerçekten kötü" ile "verinin yalnızca %40'ı mevcut" arasında **asla karıştırılmaz**.

---

## Bölüm F — Credit Score Engine (Banka Kredi Tahsis Bakış Açısı)

### F.1 Notlandırma ölçeği

`AAA, AA, A, BBB, BB, B, CCC` — yedi kademeli, uluslararası kredi derecelendirme kuruluşlarının (S&P/Moody's tarzı) sınıflandırma dilini kullanan ama **FINOS'un kendi içsel, banka-bağımsız** bir skorudur; gerçek bir kredi derecelendirme kuruluşunun notu değildir ve asla öyle sunulmaz (Bölüm F.4).

### F.2 Ağırıklandırma — hangi oranlar hangi ağırlıkta, kritik vs. destekleyici

**Kritik oranlar (skor üzerinde doğrudan ve büyük etki, eşik-altı durumda not tavanı uygulanır):** `current_ratio` (Likidite), `debt_to_equity` (Borçluluk), `interest_coverage_ratio`/`ebitda_coverage_ratio` (Borç servis kapasitesi), `net_profit_margin` (Kârlılık sürdürülebilirliği), `debt_to_ebitda` (Genel borçluluk yükü). Kural: bu beş orandan **herhangi biri** kritik-eşiğin altındaysa (ör. `interest_coverage_ratio < 1.0` — faiz giderini karşılayamıyor), nihai not **BB'nin üzerine çıkamaz**, girdilerin geri kalanı ne kadar iyi olursa olsun (bankacılıkta "tek kritik zayıflık genel notu sınırlar" ilkesinin karşılığı).

**Destekleyici oranlar (ağırlıklı ortalamaya katkı sağlar ama tek başına tavan koymaz):** `equity_ratio`, `quick_ratio`, `asset_turnover`, `receivables_turnover`, `sales_growth`, `return_on_assets`, `cash_conversion_cycle`, `working_capital_to_sales`.

**Ağırık dağılımı (100 üzerinden, önerilen):** Borç Servis Kapasitesi (interest/ebitda coverage) %25, Kaldıraç (debt_to_equity, debt_to_ebitda) %22, Likidite (current_ratio, quick_ratio) %18, Kârlılık (net_profit_margin, ROA) %18, Faaliyet/Verimlilik (turnover'lar) %10, Büyüme/trend %7.

### F.3 Not eşikleri (Milestone 4.3E'de kesinleştirilecek, burada ilk taslak bant)

Ağırlıklı kompozit skor (0-100) → not: `≥90 AAA`, `80-89 AA`, `70-79 A`, `60-69 BBB`, `50-59 BB`, `35-49 B`, `<35 CCC`. Kritik-oran tavanı (F.2) bu bandı **override** eder.

### F.4 Skorun sınırları — dürüstçe belirtilmesi gereken eksikler (kullanıcının açıkça istediği bölüm)

Bugünkü FINOS verisiyle **yapılamayan** ve Credit Score'un **yapamayacağını açıkça beyan etmesi gereken** analizler:

1. **Kredi geçmişi / ödeme performansı yok.** FINOS hiçbir zaman şirketin geçmiş kredi ödemelerini, gecikme kaydını, KKB/Findeks verisini görmez — skor **tamamen mali tablo bazlıdır**, davranışsal kredi riskini içermez.
2. **Teminat değerlendirmesi yok.** Gayrimenkul ipoteği, kefalet, teminat mektubu gibi kredi yapısına özgü unsurlar skora dahil değildir.
3. **Nakit akışı tahmini (forecasting) yok.** Skor **geçmişe dönük** (tarihsel mali tablo) veridir; bankaların kullandığı ileriye dönük nakit akışı projeksiyonu ve senaryo analizi bu milestone'da yoktur (Recommendation Engine'in what-if özelliği — Bölüm H — buna kısmen yaklaşır ama gerçek bir stokastik projeksiyon değildir).
4. **Sektör-göreli konumlandırma sınırlı.** Bölüm G'nin ilk sürümünde gerçek sektör verisi yoktur — skor mutlak eşiklerle çalışır, "sektöre göre iyi/kötü" ayrımını henüz yapamaz.
5. **Tek dönem/kısa geçmiş riski.** Çok-dönemli trend analizi (3-5 yıllık) olmadan skorun kararlılığı sınırlıdır — bir dönemlik anlık görüntü, döngüsel dalgalanmaları yanlış yorumlayabilir.
6. **Grup/konsolide risk yok.** Şirketler grubu içi kefalet zincirleri, ana şirket riski, ilişkili taraf işlemleri değerlendirmeye dahil değildir.
7. **Nitel (qualitative) faktörler yok.** Yönetim kalitesi, pazar konumu, rekabet ortamı gibi bankaların "soft" değerlendirme unsurları FINOS'un kapsamı dışındadır.

Bu sınırlar `result_json["credit_score"]["limitations"]` altında **her skorla birlikte otomatik olarak** raporlanır (Bölüm K) — sessizce gizlenmez.

---

## Bölüm G — Industry Benchmark Sistemi

### G.1 Bugünkü durum — dürüstçe

FINOS bugün **hiçbir gerçek sektör verisine sahip değil**. Bu bölüm, hiçbir veri olmadan çalışabilen bir mimari (sistem sektör verisi olmadan da tam işlevsel kalır, benchmark alanları `null`/`"benchmark_unavailable"` olur) ile, veri geldiğinde **kod değişikliği gerektirmeden** devreye girecek bir besleme/versiyonlama modeli tasarlar.

### G.2 Veri modeli (yalnızca tasarım — migration yok)

`IndustrySector` (sektör tanımı — NACE/Türkiye Sektör Sınıflaması [NACE Rev.2 Türkiye uyarlaması] kodu, ad, üst sektör hiyerarşisi — şirketler `Company` tablosuna eklenecek opsiyonel `sector_code` alanıyla eşlenir, bu alan bugün `Company` modelinde **yok**, additive migration Milestone 4.3C'de gerekir), `IndustryBenchmarkSet` (bir sektörün, bir dönemin, bir veri kaynağının ürettiği oran ortalamaları/medyan/çeyrekler kümesi — `sector_code`, `period_year`, `data_source`, `version`, `valid_from`, `valid_until`, `reliability_grade`), `IndustryBenchmarkValue` (bir `IndustryBenchmarkSet` içinde tek bir oranın değeri — `ratio_key` [RATIO_REGISTRY'deki `key` ile eşleşir], `p25`, `p50` [medyan], `p75`, `mean`, `sample_size`).

### G.3 Veri kaynakları — gelecekteki besleme kanalları (mimari düzeyde, implementasyon yok)

**T.C. Merkez Bankası (TCMB) Sektör Bilançoları:** TCMB'nin yıllık yayınladığı "Şirket Bilançoları" istatistikleri — sektör bazlı, halka açık olmayan şirketleri de kapsayan en geniş kaynak; yıllık gecikmeli yayınlanır (`valid_from`/`valid_until` bu gecikmeyi yansıtır).

**BDDK:** Bankacılık sektörüne özgü oranlar (sermaye yeterliliği, takipteki alacak oranı) — FINOS'un bankacılık dışı müşterileri için doğrudan kullanılmaz, ama Bölüm F.2'nin kredi skorlama eşiklerinin kalibrasyonu için referans olabilir.

**Borsa İstanbul (BIST) / KAP (Kamuyu Aydınlatma Platformu):** Yalnızca halka açık şirketler için ama **çeyreklik** güncellenen, en güncel finansal tablo kaynağı — Bölüm C.9 (Piyasa oranları) ve C.7 (Yatırım oranları) kategorilerinin gelecekte aktifleşmesi için birincil kaynak.

**TÜİK:** Sektörel üretim/ciro endeksleri — doğrudan oran değil ama büyüme kategorisi (C.6) için makro bağlam sağlar (`IndustryBenchmarkValue`'nun `ratio_key` alanı yalnızca `RATIO_REGISTRY` anahtarlarıyla sınırlı değildir, makro göstergeler için ayrı bir `MacroIndicatorValue` tablosu — Milestone 4.3C kapsamı dışına genişleme notu olarak burada işaretlenir).

**SPK:** Halka açık olmayan ama SPK'ya tabi (ör. halka arz sürecindeki) şirketlerin bağımsız denetim raporları — dolaylı kaynak, otomatik değil, manuel veri girişi gerektirebilir.

**Ticari finansal veri sağlayıcıları (ör. yerel kredi derecelendirme kuruluşları, ticaret odaları sektör raporları):** Ücretli/lisanslı API entegrasyonları — Milestone 4.3C bu entegrasyonların **arayüz sözleşmesini** (bir `BenchmarkDataSource` Protocol'ü, EngineAdapter'ın benchmark besleme tarafındaki karşılığı) tasarlar ama hiçbir gerçek entegrasyon yazmaz.

### G.4 Benchmark versiyonlama

Her `IndustryBenchmarkSet` **immutable**'dır (BS/IS `FinancialAnalysisResult`'ların versiyonlanabilir olması ilkesiyle tutarlı — A.1) — yeni veri geldiğinde eski set güncellenmez, yeni bir `version` numarasıyla yeni bir set eklenir; `valid_from`/`valid_until` hangi analiz sonuçlarının hangi seti kullanacağını belirler. Bir Ratio Engine sonucu, kullandığı benchmark setinin `id`+`version`'ını `result_json["benchmark_comparison"]["benchmark_set_id"]` içinde **saklar** — geçmişte üretilmiş bir sonuç, benchmark verisi sonradan güncellense bile **hangi benchmark'a göre üretildiğini kaybetmez** (izlenebilirlik ilkesinin benchmark'a genişletilmiş hali).

### G.5 Sektör sınıflaması

`Company` modeline additive `sector_code: str | None` alanı (NACE Rev.2 Türkiye kodları) — kullanıcı tarafından manuel girilir (Milestone 4.3C) ya da gelecekte VKN üzerinden bir dış kaynaktan (ör. Ticaret Sicili) otomatik doldurulabilir (bu otomasyon 4.3 kapsamında değildir). Sektör kodu yoksa Ratio Engine benchmark karşılaştırmasını **hiç yapmaz** — sahte/varsayılan bir sektör atanmaz.

### G.6 Geçerlilik tarihi ve veri güvenilirliği

`reliability_grade` (`official_statistical` [TCMB/TÜİK gibi resmî istatistik], `regulatory` [BDDK/SPK], `market_disclosed` [KAP/BIST], `commercial_licensed` [ücretli sağlayıcı], `estimated` [FINOS'un kendi tahmini — **yalnızca açıkça işaretlenerek** kullanılabilir, asla resmî veriyle karıştırılmaz]) her `IndustryBenchmarkSet`'e atanır ve `result_json`'da oranın yanında **her zaman** görünür — kullanıcı "bu benchmark ne kadar güvenilir" sorusuna her zaman cevap bulur.

---

## Bölüm H — Recommendation Engine Mimarisi (Altyapı — İmplementasyon Yok)

### H.1 Tasarım hedefi

Kullanıcının örnek verdiği çıktı türleri ("cari oranınızı 1.22'den 1.60'a yükseltmek için ~18M TL net işletme sermayesi artışı gerekir" vb.) üç farklı **recommendation türü**ne ayrılır ve her biri için ayrı bir hesaplama stratejisi tasarlanır — hepsi **matematiksel olarak geri türetilebilir** (Bölüm I), asla LLM tabanlı serbest metin üretimiyle "tahmin edilmez".

### H.2 Recommendation türleri

**Tür 1 — Hedef-Oran Optimizasyonu (`target_ratio_optimization`):** "current_ratio'yu X'ten Y'ye çıkarmak için Z TL değişim gerekir." Formül, oranın **tersine çözümü**dür: `current_ratio = current_assets / short_term_liabilities` verildiğinde, hedef `Y` için gereken `current_assets` değişimi `Δcurrent_assets = Y * short_term_liabilities - current_assets` (short_term_liabilities sabit tutulursa) ya da simetrik olarak `short_term_liabilities` azaltımı olarak da ifade edilebilir — **iki alternatif yol da sunulur**, hangisinin daha gerçekçi olduğuna dair bir öneri sistemin kendisi vermez (bu, kullanıcının kendi işletme kararıdır), yalnızca matematiği gösterir.

**Tür 2 — Sektör-Farkı Kapatma (`benchmark_gap_closure`):** "Stok devir süreniz sektör ortalamasının 31 gün üzerinde." Formül: `gap_days = company_days_inventory_outstanding - benchmark.p50`. Bölüm G'nin benchmark verisi **zorunlu ön koşuldur** — benchmark yoksa bu tür recommendation hiç üretilmez (sessizce atlanır, sahte bir sektör ortalaması varsayılmaz).

**Tür 3 — Skor-Etki Simülasyonu (`score_impact_simulation`):** "Alacak tahsil süresini 12 gün azaltmanız Health Score'u ~6 puan artıracaktır." Bölüm E.4'teki kategori-içi eşik-bantlama fonksiyonu **deterministik ve türevi alınabilir** (parçalı doğrusal) olduğu için, bir oranın varsayımsal yeni değeri E.4 fonksiyonuna verilip yeni kategori puanı ve dolayısıyla yeni toplam Health Score **doğrudan hesaplanabilir** — bu bir tahmin/regresyon değil, **aynı deterministik formülün ileri yönde tekrar çalıştırılmasıdır** (what-if simülasyonu, Bölüm H.3).

**Tür 4 — Kredi Notu Simülasyonu:** Tür 3'ün Credit Score (Bölüm F) üzerinde uygulanmış hali — "Özkaynak oranını %22'ye çıkarırsanız kredi notunuz BBB'den A'ya yaklaşacaktır." F.3'teki not-eşik fonksiyonu da deterministik olduğu için aynı prensip uygulanır.

### H.3 What-if senaryo motoru (altyapı tasarımı)

`RatioScenarioInput` (hangi oranın/hangi temel `canonical_facts` alanının hangi yeni değere değiştirileceğini tanımlayan, salt bellek-içi bir dataclass — DB'ye yazılmaz, kalıcı değildir) → `recompute_ratios_with_overrides(base_facts, overrides: dict) -> RatioComputationResult` (Milestone 4.3F'de yazılacak fonksiyon, **normal hesaplama fonksiyonunun aynısı**, yalnızca girdi olarak gerçek `canonical_facts` yerine üzerine `overrides` uygulanmış bir kopya alır — kod tekrarı yok, aynı `RATIO_REGISTRY` çağrılır) → sonuç, gerçek analiz sonucuyla **yan yana** (`baseline` vs. `scenario`) `result_json["what_if_scenarios"]` altında raporlanır, **asla** gerçek `FinancialAnalysisResult` olarak DB'ye yazılmaz (bu kritik — simülasyon sonucu gerçek analiz sonucuyla karıştırılamaz, `SourceMode`/`FinancialAnalysisResultSource` şemasına hiç girmez, tamamen istek-yanıt ömürlü bir hesaplamadır).

### H.4 İşletme sermayesi simülasyonu

H.2 Tür 1'in çalışma sermayesi özelinde genişlemesi: `net_working_capital` hedefine ulaşmak için `current_assets`/`inventory`/`trade_receivables`/`trade_payables` bileşenlerinden **hangisinin** değişmesi gerektiği ayrı ayrı senaryolanır (ör. "alacakları 12 gün hızlandırarak" vs. "stokları %8 azaltarak" aynı hedefe ulaşan iki farklı yol) — Bölüm C.3'teki devir hızı formüllerinin tersine çözümüyle üretilir.

### H.5 Bu milestone'da NE YAPILMAYACAK (kapsam sınırı, açıkça)

Recommendation Engine'in **metin üretimi** (Türkçe doğal dil cümlesi — "Cari oranınızı... yükseltmek için...") bu milestone'da **implemente edilmez**. 4.3F yalnızca yukarıdaki matematiksel altyapıyı (tersine-çözüm formülleri, what-if motoru, skor-etki simülasyonu) tasarlar ve (implementasyon fazında) kurar; öneri **metinlerinin** şablonlanması (`ratio_explanations.py`'ye benzer bir `recommendation_templates.py`) ayrı bir gelecek milestone'un (4.3F implementasyonunun kendi içindeki son adımı ya da 4.3'ün tamamlanmasından sonraki bir 4.6 gibi) kapsamına bırakılır — bu doküman yalnızca altyapının **tasarımını** teslim eder, kullanıcının 9. maddesindeki talimatla birebir tutarlı ("Bu milestone'da implementasyon yapılmayacak. Sadece altyapı.").

---

## Bölüm I — Explainability Sistemi

### I.1 İlke

**Hiçbir sayı, kaynağı gösterilmeden üretilmez.** Bu ilke üç seviyede uygulanır: (1) her oran → `ProvenanceEntry` (A.4/D.2 — zaten var, genişletilecek), (2) her Health Score kategori puanı → hangi oranların hangi ağırlıkla katkı sağladığının listesi, (3) her Recommendation → H.3'teki deterministik formülün adım adım gösterimi.

### I.2 Genişletilmiş `ProvenanceEntry` (additive, geriye uyumlu)

Mevcut `ProvenanceEntry(metric, derivation_rule, input_fields, missing_inputs, calculated)` yapısına Milestone 4.3'te şu **opsiyonel** (default değerli, mevcut çağıranları bozmayan) alanlar eklenir: `source_analysis_result_ids: tuple[str, ...] = ()` (bu metriğin hangi `FinancialAnalysisResult.id`'lerden geldiği — UUID'ler string olarak, JSON-serileştirme sınırında), `reliability: str | None = None` (Bölüm C.0), `rounding_applied: str | None = None` (hangi quantize kuralı uygulandığı, insan-okunur). Bu, `provenance_to_dict`'in ürettiği sözlüğe yeni anahtarlar ekler ama **var olanları değiştirmez** — BS/IS Engine'lerin bugünkü `calculation_provenance` çıktısı hâlâ şema-uyumlu kalır (yeni alanlar `None`/boş varsayılanla dolar).

### I.3 Health Score explainability

`result_json["health_score"]["explanation"]`: her kategori için `{category, weight, category_score, contributing_ratios: [{ratio_key, value, score_contribution, band_applied}], excluded_ratios: [{ratio_key, reason}], data_coverage_pct}`. Bir kullanıcı "neden 62 puan aldım" sorduğunda, sistem **hangi oranın hangi bant içine düştüğü ve kaç puan getirdiği** kadar ayrıntılı bir döküm verebilir — kara kutu yok.

### I.4 Credit Score explainability

Benzer şekilde `result_json["credit_score"]["explanation"]`: kritik oranların eşik durumu (`{ratio_key, value, threshold, breached: bool}` — F.2'deki tavan kuralının **hangi oranın tetiklediği** açıkça görünür), destekleyici oranların ağırıklı katkısı, ve nihai notun **hangi kuraldan** (ağırlıklı ortalama mı, kritik-tavan mı) geldiği.

### I.5 Recommendation explainability

Her recommendation kaydı zorunlu olarak `{recommendation_type, based_on_ratio_key, current_value, target_value, formula_applied, computed_delta}` taşır — H.2'deki dört türün her biri için formül metni **sabit şablon değil, gerçek kullanılan sayısal formülün** (ör. `"current_assets değişimi = 1.60 × 4,200,000 - 3,720,000 TL"`) kendisidir, yalnızca doğal dil çerçevesi şablonludur (H.5'in kapsam dışı bıraktığı kısım — cümle kalıbı; sayısal gerekçe her zaman gerçek hesaplamadan gelir).

---

## Bölüm J — Caching Stratejisi

### J.1 Neden gerekli

Ratio Engine, aynı iki (BS+IS) girdiden ~93 oran + Health Score + Credit Score + (varsa) Recommendation seti üretiyor — bu, BS/IS Engine'lerin tek-geçişli hesaplamasından **daha ağır** bir iş. Bir dönem için BS/IS değişmediği sürece Ratio Engine sonucunu **yeniden hesaplamak gereksizdir**.

### J.2 Cache anahtarı tasarımı

Cache anahtarı, girdi olarak kullanılan **tüm kaynakların id+versiyonunun** bir bileşimidir: `ratio_cache_key = hash(bs_analysis_result_id, bs_result_updated_at, is_analysis_result_id, is_result_updated_at, [prior_period_bs_id, prior_period_is_id varsa], engine_version, ratio_registry_version)`. `ratio_registry_version` (yeni bir sabit, `RATIO_REGISTRY`'nin şema/formül versiyonu — `ratio_formulas.py`'ye eklenecek `RATIO_REGISTRY_VERSION = "1.0.0"`) **formül değiştiğinde** (implementasyon sonrası bir formül düzeltmesi olduğunda) tüm cache'i geçersiz kılan bir sürüm damgasıdır — kod değişikliği ile veri değişikliğini aynı anahtar uzayında ayırt eder.

### J.3 Nerede önbelleğe alınır — DB'nin kendisi zaten bir cache'tir

**Temel karar:** Ayrı bir Redis/harici cache katmanı **bu milestone'da kurulmaz** (YAGNI — mevcut mimaride hiçbir yerde harici cache yok, A.1). Birincil "cache", Ratio Engine'in kendi `FinancialAnalysisResult` satırının **DB'de zaten var olmasıdır** — J.4'teki invalidation kuralı tetiklenmediği sürece, aynı dönem için Ratio Engine tekrar çalıştırılmaz, mevcut satır **olduğu gibi** döndürülür (bu, BS/IS Engine'lerin bugün **her zaman** yeniden hesapladığı davranıştan bilinçli bir sapmadır çünkü Ratio Engine'in girdi seti çok daha büyük ve pahalıdır).

### J.4 Invalidation (geçersiz kılma) kuralları

Ratio Engine sonucu şu durumlardan **herhangi biri** gerçekleştiğinde geçersiz sayılır ve yeniden hesaplanır: (1) o dönemin BS ya da IS `FinancialAnalysisResult`'ı için **yeni bir satır** oluşturulduğunda (motor yeniden çalıştırıldığında — mevcut mimaride analiz sonuçları immutable/versiyonlu olduğu için bu "güncelleme" değil "yeni satır" olarak gerçekleşir, A.1), (2) `RATIO_REGISTRY_VERSION` implementasyon sırasında yükseltildiğinde (formül düzeltmesi — **tüm** geçmiş Ratio Engine sonuçları, yeni bir arka plan "recompute" işiyle, kullanıcı talebi olmadan yeniden hesaplanabilir; bu iş Milestone 4.3 kapsamında **tasarlanır**, implementasyonu operasyonel bir karardır), (3) önceki dönem BS/IS sonucu **sonradan** eklendiğinde (ör. kullanıcı geçmiş bir dönemi geriye dönük yükler — bu, büyüme oranlarını `not_calculable`'dan hesaplanabilir hale getirir, dolayısıyla mevcut dönemin Ratio Engine sonucu da geçersiz sayılır — B.11 orkestrasyonunun **hem ileri hem geri** dönem tetiklemesi gerektiği anlamına gelir, implementasyon notu).

### J.5 Incremental recompute (kısmi yeniden hesaplama)

**Milestone 4.3'te YAPILMAYACAK** (dürüstçe kapsam dışı bırakılır): yalnızca değişen kategoriyi yeniden hesaplayan bir kısmi-recompute mekanizması, kod karmaşıklığını (hangi oranın hangi girdiye bağlı olduğunun bir bağımlılık grafiği gerektirir) bu milestone'un getirisine göre haklı çıkarmaz — J.4'teki tetikleyicilerden biri gerçekleştiğinde **tüm** Ratio Engine sonucu (93 oran + Health Score + Credit Score) **tek seferde** yeniden hesaplanır (BS/IS Engine'lerin zaten yaptığı "tam yeniden hesaplama" modeliyle tutarlı, A.1). Bu basitlik, `RATIO_REGISTRY`'nin merkezi doğası (Bölüm D) sayesinde performans açısından da kabul edilebilir — tek bir dönem için 93 `safe_divide` çağrısı milisaniyeler mertebesindedir, gerçek maliyet DB okuma/yazma tarafındadır, hesaplama tarafında değil.

### J.6 Registry uyumu

Cache/invalidation mantığı `app/engines/registry.py`'ye **yeni bir fonksiyon olarak değil**, Ratio Engine'in kendi `service.py`'sinin bir iç detayı olarak yaşar (BS/IS Engine'lerin `service.py`'lerinin kendi mantıklarını registry'den saklamasıyla tutarlı, A.1) — registry yalnızca "hangi adaptör hangi analysis_type'ı üretir" sorusuna cevap verir, "ne zaman yeniden hesaplanır" sorusuna değil.

---

## Bölüm K — `result_json` Sözleşmesi

### K.1 Tasarım ilkeleri

Backward-compatible (yeni alanlar her zaman additive/opsiyonel, mevcut BS/IS `result_json` şemaları hiç değişmez), versiyonlanabilir (`schema_version` alanı — J.2'deki `RATIO_REGISTRY_VERSION`'dan **bağımsız**, çünkü sözleşme şekli değişebilir formüller değişmeden de), explainability/recommendation/benchmark/health score/credit score'un hepsini tek bir kökten (`FinancialAnalysisResult.result_json`, `analysis_type=financial_ratios`) sunan **tek bir belge**.

### K.2 Üst düzey şekil

```
{
  "engine": "financial_ratios",
  "engine_version": "1.0.0",
  "schema_version": "1.0",
  "analysis_type": "financial_ratios",
  "source_mode": "multi_source_derived",
  "ratio_registry_version": "1.0.0",

  "period_context": {
    "company_id": "...", "period_id": "...",
    "days_in_period": 365, "period_type": "year_end"
  },

  "derived_base_figures": {
    "total_liabilities": ..., "average_total_assets": ...,
    "average_equity": ..., "average_inventory": ..., "...": "..."
  },

  "categories": {
    "liquidity": {
      "status": "calculated",
      "data_coverage_pct": 100.0,
      "ratios": {
        "current_ratio": {
          "value": 1.60, "unit": "ratio", "reliability": "high",
          "calculated": true, "missing_inputs": [],
          "source_priority": 1, "explanation": "...",
          "provenance": { "...": "bkz. I.2" }
        },
        "quick_ratio": { "value": null, "calculated": false,
          "reliability": "not_calculable",
          "missing_inputs": ["bs.inventory"], "...": "..." }
      }
    },
    "cash_flow": {
      "status": "not_calculable",
      "reason": "Cash Flow Engine (Milestone 4.4) bu FINOS kurulumunda henüz devrede değil.",
      "ratios": {}
    },
    "...": "diğer 12 kategori aynı şekilde"
  },

  "cross_engine_reconciliation": { "...": "bkz. B.9, reconciliation.py sözleşmesi" },

  "health_score": {
    "status": "calculated", "total_score": 62.4, "max_score": 100,
    "total_confidence_pct": 78.5,
    "category_scores": [
      { "category": "profitability", "weight": 0.22, "score": 55.0,
        "weighted_contribution": 12.1, "data_coverage_pct": 100.0 },
      "...": "diğer kategoriler"
    ],
    "excluded_categories": [
      { "category": "cash_flow", "reason": "not_calculable", "weight_redistributed": true }
    ],
    "explanation": { "...": "bkz. I.3" }
  },

  "credit_score": {
    "status": "calculated", "grade": "BBB", "composite_score": 64.2,
    "critical_breaches": [],
    "limitations": [ "bkz. F.4, sabit liste" ],
    "explanation": { "...": "bkz. I.4" }
  },

  "benchmark_comparison": {
    "status": "benchmark_unavailable",
    "reason": "Company.sector_code atanmamış ve/veya bu sektör için IndustryBenchmarkSet mevcut değil."
  },

  "recommendations": {
    "status": "not_implemented_this_milestone",
    "reason": "Milestone 4.3F yalnızca altyapıyı tasarlar; metin üretimi implementasyonu sonraki bir adımda."
  },

  "what_if_scenarios": [],

  "warnings": [],
  "missing_categories": ["cash_flow", "market"],
  "calculation_provenance": [ "...": "genişletilmiş ProvenanceEntry listesi, bkz. I.2" ]
}
```

### K.3 Backward compatibility garantisi

`schema_version="1.0"` ilk sürümdür. Gelecekteki her değişiklik şu üç kategoriden birine girmelidir: (1) **additive** (yeni alan, `schema_version` küçük sürüm artışı, ör. `1.1`) — eski tüketiciler bilinmeyen alanı yok sayar, kırılmaz; (2) **semantik genişleme** (ör. yeni bir `reliability` değeri eklenmesi) — yine küçük sürüm artışı; (3) **kırıcı değişiklik** (bir alanın anlamı/şekli değişir) — **yeni büyük `schema_version` (`2.0`)** gerektirir ve mevcut tüketiciler açıkça göç etmelidir; bu milestone bu tür bir değişikliği **planlamaz**, yalnızca ihtimale karşı sürüm alanını baştan koyar.

### K.4 Kategori-seviyesi `not_calculable` şekli (B.5 Seviye 3'ün somut karşılığı)

Her kategori nesnesi zorunlu olarak `status: "calculated" | "partial" | "not_calculable"` taşır. `"partial"`, kategorideki bazı oranların hesaplanabildiği ama hepsinin değil durumudur (K.2 örneğindeki `liquidity` gibi, `quick_ratio` `not_calculable` olsa da `current_ratio` hesaplanmışsa kategori `"partial"` olur — üstteki örnek basitleştirme için `"calculated"` gösterildi, gerçek şemada karma durum `"partial"`dır). `"not_calculable"` yalnızca kategorinin **hiçbir** oranı hesaplanamadığında kullanılır ve zorunlu bir `reason` metni taşır.

---

## Bölüm L — Test Stratejisi (Yalnızca Planlama — Hiçbir Test Yazılmadı)

Aşağıdaki tüm test kategorileri **implementasyon fazında** (4.3A'dan itibaren, bkz. Bölüm O) yazılacaktır. Mevcut test altyapısı (sqlalchemy-free sandbox-çalıştırılabilir `app/engines/common/**` testleri + gerçek Docker/Postgres entegrasyon testleri, `tests/README.md`'de belgeli iki katmanlı model) **aynen** korunur ve genişletilir.

**L.1 Unit testler:** `RATIO_REGISTRY`'deki her formülün izole `safe_divide` çağrısı doğru mu (girdi kombinasyonları: ikisi de dolu, biri eksik, payda sıfır, payda negatif [ör. negatif özkaynak — `debt_to_equity` özel durum, Bölüm N risk analizinde ele alınır]); `RatioFormulaMetadata` kayıt/çakışma kontrolü (`register_ratio_formula`'nın "aynı key ikinci kez kayıt edilemez" davranışı — zaten var, 93 kayıt için de geçerliliği doğrulanır).

**L.2 Integration testler:** BS+IS sonucu DB'de mevcutken Ratio Engine'in doğru `FinancialAnalysisResult` + `financial_analysis_result_sources` satırlarını ürettiğinin gerçek Postgres üzerinde doğrulanması (B.8'deki 2-4 satır kuralı); FAZ sonrası orkestrasyon (`ratio_recompute.py`, B.11) tetiklemesinin bulk upload confirm sonrası gerçekten çalıştığının uçtan uca testi.

**L.3 Regresyon testleri:** Milestone 4.3 sonrası BS/IS Engine'lerin `result_json` şemasının (`preliminary_structural_ratios`, `margins`) **hiç değişmediğinin** (D.2 Karar 2 — yalnızca değer kaynağı değişti, şekil değişmedi) doğrulanması; mevcut 174+ testin tamamının yeşil kaldığının teyidi.

**L.4 Boundary (sınır) testleri:** `total_liabilities=0` iken `debt_to_ebitda`/`debt_to_equity` davranışı; `short_term_liabilities=0` iken `current_ratio` (`safe_divide` zaten `None` döner, ama bu **iş açısından** "borcu yok" anlamına mı geliyor yoksa "veri eksik" mi — bu ayrımın `missing_inputs` ile `calculated=False` arasında net kalması test edilir, çünkü `short_term_liabilities=Decimal(0)` "gerçekten sıfır" olabilir, B.5 ayrımı); D.3'teki invariant testi (Ratio Engine'in current_ratio'su ile BS Engine'in preliminary current_ratio'sunun bit-bir aynı `Decimal` değeri üretmesi).

**L.5 Property-based testler:** (Milestone 4.3 implementasyonunda `hypothesis` kütüphanesi kullanılabilir — bugün `requirements.txt`'te yok, eklenmesi implementasyon kararı) rastgele `BalanceSheetFacts`/`IncomeStatementFacts` üretilip her oranın **asla** `ZeroDivisionError`/`OverflowError`/`decimal.InvalidOperation` fırlatmadığının, ve `reliability="not_calculable"` iken `value` alanının **her zaman** `null` olduğunun (asla yanlışlıkla bir sayı sızmadığının) doğrulanması.

**L.6 Golden dataset testleri:** Elle doğrulanmış, gerçekçi bir sentetik şirket profili (ör. "orta ölçekli üretim şirketi, current_ratio=1.6, debt_to_equity=1.2, ...") için **tüm 93 oranın** beklenen değerlerinin bir kez elle hesaplanıp sabit bir fixture'a yazılması, sonra motor çıktısının bu fixture'la satır satır karşılaştırılması — muhasebe formüllerinin "koddaki mantık kendi kendini doğruluyor" tuzağına düşmemesi için **bağımsız, elle doğrulanmış** bir referans şart.

**L.7 Stress testleri:** Çok büyük (`Decimal` hassasiyeti/performans) ve çok küçük (kuruş mertebesi) tutarlarla, ve çok sayıda (ör. 500) dönem için toplu Ratio Engine çalıştırmasının performans karakterizasyonu.

**L.8 Performans testleri:** J.5'teki "her zaman tam yeniden hesaplama" kararının gerçek maliyetinin ölçülmesi (93 oran + Health Score + Credit Score hesaplama süresi, DB yazma süresinden ayrıştırılmış olarak) — J.5'teki varsayımın (hesaplama maliyeti ihmal edilebilir) doğrulanması ya da çürütülmesi.

**L.9 Explainability testleri:** Her oran için `provenance.calculated=True` iken `value` dolu, `calculated=False` iken `value=null` invariant'ının **tüm 93 oran için** otomatik taranması (elle her oranı tek tek test etmek yerine `RATIO_REGISTRY`'yi dolaşan parametrik bir test).

**L.10 Benchmark testleri:** `IndustryBenchmarkSet` yokken `benchmark_comparison.status="benchmark_unavailable"` olduğunun, ve mevcutken versiyonlama/geçerlilik-tarihi filtrelemesinin (G.4) doğru çalıştığının testi — gerçek harici veri olmadan, sentetik `IndustryBenchmarkSet` fixture'larıyla.

**L.11 Recommendation testleri:** H.3'teki `recompute_ratios_with_overrides`'ın **normal hesaplama ile aynı `RATIO_REGISTRY`'yi** kullandığının (kod tekrarı yok invariantı) ve simülasyon sonucunun asla DB'ye kalıcı yazılmadığının testi.

---

## Bölüm M — Dosya/Klasör Yapısı

### M.1 Yeni klasörler ve dosyalar

```
app/engines/financial_ratios/          (yeni paket — BS/IS ile aynı desen)
  __init__.py
  service.py            analyze_financial_ratios(...) — tek giriş noktası
  adapter.py             FinancialRatioEngineAdapter (EngineAdapter Protocol)
  health_score.py         Bölüm E hesaplama mantığı
  credit_score.py         Bölüm F hesaplama mantığı
  recommendation.py       Bölüm H what-if/tersine-çözüm altyapısı (yalnızca fonksiyonlar, metin üretimi yok)

app/engines/common/
  ratio_formulas.py                    (MEVCUT — 93 RatioFormulaMetadata ile doldurulacak, YENİDEN YAZILMAZ)
  ratio_explanations.py                (YENİ — C.0'daki açıklama şablonları, Türkçe)
  ratio_derived_facts.py               (YENİ — C.0'daki "türetilmiş ara alanlar": total_liabilities, average_*, days_in_period)
  benchmark_types.py                   (YENİ — G.2'deki dataclass'lar, DB'den bağımsız saf şekiller — canonical_facts.py deseniyle tutarlı)

app/models/
  industry_sector.py                   (YENİ — G.2)
  industry_benchmark_set.py            (YENİ — G.2)
  industry_benchmark_value.py          (YENİ — G.2)
  financial_health_score.py            (YENİ — Health Score'un kalıcı DB izi, ayrı tablo mı yoksa result_json içinde mi kalacağı Q.3'te karar bekleyen bir konu)
  credit_score_result.py               (YENİ — aynı açık soru)

app/services/
  ratio_recompute.py                   (YENİ — B.11'deki FAZ-sonrası orkestrasyon)
  benchmark_ingestion.py               (YENİ — G.3'teki dış kaynak besleme arayüzü, gerçek entegrasyon YOK, yalnızca Protocol + manuel-girdi implementasyonu)

app/api/v1/
  financial_ratios.py                  (YENİ — GET endpoint'leri; mevcut analyses.py deseniyle tutarlı)
  benchmarks.py                        (YENİ — sektör/benchmark set CRUD, yalnızca G kapsamındaki temel okuma/manuel-girdi uçları)

tests/
  test_financial_ratios_unit.py         (YENİ — L.1, L.4, L.5, L.9)
  test_financial_ratios_golden_dataset.py (YENİ — L.6)
  test_health_credit_score_unit.py      (YENİ — E, F)
  test_ratio_recommendation_unit.py      (YENİ — L.11)
  test_bulk_upload_ratio_integration.py  (YENİ — L.2, L.3)
  test_benchmark_unit.py                 (YENİ — L.10)
```

### M.2 `app/engines/protocol.py` genişletmeleri (additive)

`EngineRunContext`'e eklenecek yeni **opsiyonel** alanlar (A.12 madde 4/7): `balance_sheet_result: dict | None = None`, `income_statement_result: dict | None = None` (Ratio Engine'in BS/IS `result_json`'larına doğrudan erişimi — mevcut `trial_balance_result` alanıyla aynı desen), `prior_period_balance_sheet_result: dict | None = None`, `prior_period_income_statement_result: dict | None = None` (ortalama-bakiye ve büyüme oranları için, C.0/C.6). Bu alanlar mevcut hiçbir motoru etkilemez (BS/IS/TrialBalance adaptörleri bunları kullanmaz, `None` varsayılanıyla geçer).

### M.3 `app/services/bulk_upload.py` üzerindeki etkiler

**Sıfır değişiklik gerektirir** (B.11'deki tasarım kararının doğal sonucu) — Ratio Engine, FAZ2/FAZ3'ün **içine değil**, FAZ3 sonrası `ratio_recompute.py`'ye eklenir. Bu, A.7'de tespit edilen "FAZ2/FAZ3'e yeni bağımlılık sınıfı ekleme" riskini **tamamen ortadan kaldırır** — bulk upload'ın bugünkü, zaten karmaşık dependency-aware mantığına dokunulmaz.

### M.4 Registry değişiklikleri

`app/engines/registry.py`'ye yalnızca üç satır eklenir: `FinancialRatioEngineAdapter` importu, `_ENGINE_BY_ANALYSIS_TYPE`'a `AnalysisType.FINANCIAL_RATIOS: FinancialRatioEngineAdapter()` kaydı. `_DETECTED_TYPE_TO_ANALYSIS_TYPE`/`_DOCUMENT_TYPE_TO_ANALYSIS_TYPE`'a **hiçbir ekleme yapılmaz** (B.10).

### M.5 Migration ihtiyacı (yalnızca liste — hiçbir migration bu aşamada yazılmaz)

Yeni tablolar: `industry_sectors`, `industry_benchmark_sets`, `industry_benchmark_values`, (Q.3'e bağlı olarak) `financial_health_scores`, `credit_score_results`. `companies` tablosuna additive `sector_code: str | None` kolonu. Mevcut hiçbir tabloya **kırıcı** değişiklik yoktur — hepsi ya yeni tablo ya da nullable additive kolon.

---

## Bölüm N — Risk Analizi

### N.1 Teknik riskler

**Performans riski (orta):** 93 oran + Health Score + Credit Score tek çalıştırmada hesaplanıyor — J.5'te "ihmal edilebilir" varsayıldı ama gerçek `Decimal` aritmetiği maliyeti L.8'de ölçülene kadar **doğrulanmamış bir varsayımdır**. Azaltım: L.8 performans testleri implementasyonun **erken** bir adımı olarak planlanmalı (4.3B sonunda, tüm kategoriler eklenmeden önce ara ölçüm).

**Şema genişleme riski (düşük-orta):** `EngineRunContext`'e M.2'deki 4 yeni alanın eklenmesi additive olsa da, `EngineRunContext`'i tüketen her yer (bugün BS/IS/TrialBalance adaptörleri, gelecekte Cash Flow) bu alanları **görmezden gelebilmelidir** — `runtime_checkable Protocol` kullanan `EngineAdapter`'ın statik tip kontrolü bunu garanti etmez (Python Protocol'leri fazladan alanları reddetmez ama motor kodu yanlışlıkla yeni alanlara bağımlı hale gelebilir). Azaltım: code review disiplini + L.3 regresyon testleri.

**Cache/invalidation eksikliği riski (düşük, J.5'te bilinçli kabul edildi):** "Her zaman tam yeniden hesapla" kararı, çok sayıda dönem birikince (ör. binlerce şirket × birden fazla dönem) toplu bir `RATIO_REGISTRY_VERSION` yükseltmesinde ciddi bir arka plan iş yüküne dönüşebilir — bu, bugünkü ölçekte (MVP/erken aşama FINOS) kabul edilebilir bir risktir, ölçek büyüdükçe yeniden değerlendirilmelidir (bu doküman bunu bir gelecek-riski olarak **açıkça** işaretler, çözmez).

### N.2 Muhasebesel riskler

**Negatif özkaynak/negatif payda riski (yüksek önem, sık karşılaşılır):** Türkiye'de zarar eden KOBİ'lerde negatif özkaynak sık görülür — `debt_to_equity`, `return_on_equity`, `financial_leverage_multiplier` gibi oranlar payda negatifken **matematiksel olarak tanımlı ama yorumsal olarak yanıltıcı** sonuçlar üretir (ör. hem borç hem özkaynak negatifse oran pozitif çıkar ama "iyi" görünüp aslında kötü bir durumu gizler). Azaltım: `RatioFormulaMetadata`'ya (implementasyon fazında) bir `negative_denominator_policy` alanı eklenmesi — bu tür oranlar için sonuç hesaplanır AMA `warnings`'e otomatik bir `"NEGATIVE_DENOMINATOR_CAUTION"` bayrağı eklenir (Health Score/Credit Score bu bayrağı görüp ilgili oranı **düşük güvenilirlikle** işlem görür ya da o kategoriyi otomatik olarak inceleme gerektirir işaretler).

**Tekdüzen Hesap Planı ↔ IFRS uyumsuzluğu (orta, C.11'de zaten dürüstçe işaretlendi):** Kullanıcının "IFRS" kategorisi talebi ile FINOS'un bugünkü Tekdüzen-tabanlı mimarisi arasındaki gerçek boşluk — yanlış bir "IFRS uyumluluğu" izlenimi verilmesi riski. Azaltım: C.11'in açık dürüstlük notu + `result_json`'da hiçbir IFRS oranının sahte biçimde dolu görünmemesi.

**Dönem uzunluğu normalizasyonu riski (orta):** `days_in_period` farklı dönem tipleri (`monthly` vs `year_end` vs `temporary_tax`) arasında oranların (özellikle "days" birimli olanların, C.3) **doğrudan karşılaştırılabilir olmadığı** anlamına gelir — 3 aylık geçici vergi dönemi ile yıllık dönemin `days_sales_outstanding`'i aynı ölçekte değildir. Azaltım: `result_json["period_context"]`'in her zaman `period_type`/`days_in_period`'i açıkça taşıması (K.2) ve Health Score/Credit Score'un (implementasyon fazında) yalnızca **aynı period_type**'a sahip dönemleri birbiriyle karşılaştırması.

### N.3 Yanlış yorum üretme riski (misinterpretation risk)

**"Tek sayı" yanılgısı:** Health Score/Credit Score gibi kompozit tek-sayı göstergeler, kullanıcıyı ayrıntıları görmeden karar vermeye teşvik edebilir. Azaltım: I.3/I.4'teki zorunlu explainability + E.5'teki `total_confidence_pct`'in **her zaman** skorla birlikte görünmesi — düşük veri kapsamıyla üretilen bir skorun yanıltıcı bir kesinlik izlenimi vermemesi.

**Recommendation'ların "tavsiye" gibi algılanması riski:** H.2'deki matematiksel tersine-çözümler ("Z TL değişim gerekir") **finansal tavsiye değildir**, yalnızca matematiksel bir ilişkidir — bir şirketin gerçekten bu değişimi yapıp yapamayacağı (nakit kısıtları, piyasa koşulları) sistemin bilgisi dışındadır. Azaltım: her recommendation çıktısının (implementasyon fazında) "bu bir finansal tavsiye değil, matematiksel bir ilişkidir" açıklamasını taşıması gerekir — <legal_and_financial_advice> ilkesiyle tutarlı bir tasarım gereksinimi.

### N.4 Benchmark riski

Gerçek sektör verisi olmadan (G.1) erken kullanıcıların "tahmini"/`estimated` güvenilirlikli benchmark'lara **resmi veri gibi** güvenmesi riski. Azaltım: G.6'daki `reliability_grade`'in her zaman görünür olması + `estimated` dereceli benchmark'ların (implementasyon fazında) UI'da farklı görsel olarak işaretlenmesi (bu doküman UI tasarlamaz, ama veri sözleşmesinin bunu **mümkün kıldığını** garanti eder).

### N.5 Performans riski (ölçek)

N.1'de teknik risk olarak değinildi; iş riski boyutu: bulk upload'ta yüzlerce belge tek seferde onaylanırsa (B.11), FAZ3 sonrası tetiklenen `ratio_recompute.py` çağrıları senkron ise kullanıcı deneyimini (confirm isteğinin yanıt süresi) doğrudan etkiler. Azaltım: Q.4'te işaretlendiği gibi senkron/asenkron kararı implementasyon fazına bırakılmıştır; asenkron seçilirse bir kuyruk/arka plan iş mekanizması (bugün FINOS'ta **hiç yok** — yeni bir altyapı bileşeni, kapsamı genişletir) gerekecektir.

### N.6 Banka tarafındaki riskler

Credit Score'un F.4'te listelenen sınırlarının banka kullanıcıları tarafından **yanlış anlaşılması** (bir FINOS notu ile gerçek bir kredi kuruluşu notunun karıştırılması) — itibar ve olası yasal risk. Azaltım: her Credit Score çıktısının (implementasyon fazında) "bu resmi bir kredi derecelendirmesi değildir" ibaresini taşıması zorunlu kılınmalıdır (tasarım gereksinimi olarak burada kayıt altına alınır).

### N.7 Explainability riskleri

Genişletilmiş `ProvenanceEntry`'nin (I.2) her oran için doğru `source_analysis_result_ids`'i taşıması **manuel disiplin** gerektirir — bir geliştirici yeni bir oran eklerken bu alanı doldurmayı unutabilir. Azaltım: L.9'daki parametrik test (`RATIO_REGISTRY`'yi dolaşan) bunu **otomatik olarak** her oran için zorunlu kılar, code review'a bırakılmaz.

### N.8 Gelecekte genişletilebilirlik

Cash Flow Engine (4.4) ve Tax Return Engine (4.5) devreye girdiğinde, C.8/C.11/C.12'deki `not_calculable` oranların **kod değişikliği olmadan, yalnızca veri akışı bağlanarak** aktifleşmesi gerekir (A.9'daki "formül tasarımı şimdiden, veri sonra" ilkesi) — bu, M.2'deki additive `EngineRunContext` alanlarının (ör. gelecekte `cash_flow_result: dict | None`) aynı desende genişletilmesiyle sağlanır. Risk: bu disiplin bozulursa (ör. Cash Flow Engine'in kendi ayrı bir "oran modülü" icat etmesi), Bölüm D'nin "tek formül kaynağı" ilkesi zamanla erozyona uğrayabilir — azaltım, gelecekteki her milestone'un bu dokümanın D.2 kararlarına açıkça referans vermesi (bu doküman, gelecekteki milestone'lar için de bir mimari referans olarak kalıcıdır, yalnızca 4.3'e özgü değil).

---

## Bölüm O — Alt Fazlara Bölünme (4.3A–4.3F)

Her alt faz, kendinden önceki faz(lar) tamamlanmadan **başlayamaz** (katı bağımlılık zinciri) — bu, Milestone 4.1→4.2 arasındaki "önce sözleşme, sonra implementasyon" disiplininin (A.9) doğal devamıdır.

### Milestone 4.3A — Ratio Calculation Foundation

**Kapsam:** `ratio_formulas.py`'nin gerçek formüllerle doldurulması **değil** — yalnızca altyapı: `compute_registered_ratio()` fonksiyonu (D.2 Karar 4), `ratio_derived_facts.py` (C.0'daki türetilmiş ara alanlar: `total_liabilities`, `average_*`, `days_in_period`), genişletilmiş `ProvenanceEntry` (I.2), `RATIO_REGISTRY_VERSION` sabiti (J.2), `EngineRunContext`'in M.2'deki 4 yeni alanla genişletilmesi, `FinancialRatioEngineAdapter`'ın **iskelet** hali (henüz oran hesaplamıyor, yalnızca registry'ye kayıtlı, `status=not_calculable` sabit dönüyor). **Çıktı:** BS/IS Engine'lerin `compute_preliminary_structural_ratios`/`compute_margins`'inin D.2 Karar 1'e göre `RATIO_REGISTRY`'ye yönlendirilmesi (bu noktada registry'de yalnızca 9 formül var: current_ratio, debt_ratio, equity_ratio, debt_to_equity, net_working_capital, working_capital_ratio, gross/operating/net_profit_margin — BS/IS'in bugün zaten hesapladıkları).

### Milestone 4.3B — Core Financial Ratios

**Kapsam:** C.1 (Likidite), C.2 (Kârlılık), C.4 (Borçluluk), C.3 (Faaliyet), C.5 (Verimlilik), C.6 (Büyüme), C.8'in **formül kaydı** (Nakit — hesaplanamaz ama `RATIO_REGISTRY`'ye kayıtlı, N.8 ilkesi) — toplam ~55 doğrudan hesaplanabilir + ~10 `not_calculable`-ama-kayıtlı oran. `FinancialRatioEngineAdapter` artık gerçek hesaplama yapıyor. L.1/L.4/L.5/L.6/L.9 testleri bu fazda yazılır. **L.8 performans testi bu fazın sonunda yapılır** (N.1'deki erken doğrulama önerisi).

### Milestone 4.3C — Benchmark Foundation

**Kapsam:** G.2'deki üç yeni model (`IndustrySector`, `IndustryBenchmarkSet`, `IndustryBenchmarkValue`) + migration, `Company.sector_code` additive kolonu + migration, `benchmark_ingestion.py`'nin **yalnızca manuel-veri-girişi** implementasyonu (gerçek TCMB/BDDK/BIST entegrasyonu **bu milestone'da da yapılmaz** — yalnızca arayüz + manuel/CSV girişi), `benchmarks.py` API router'ı (temel CRUD). L.10 testleri.

### Milestone 4.3D — Financial Health Score

**Kapsam:** `health_score.py` (Bölüm E) — 7 kategori, Model C ağırıklandırması (E.3), E.4'teki eşik-bantlama fonksiyonu (sektörden bağımsız sabit bantlarla, "dürüst MVP" — G.6'daki sektöre-özgü bantlama **bu fazda yapılmaz**, C.3D+ bir iyileştirme notu olarak bırakılır), E.5'teki eksik-veri yeniden-normalizasyon mantığı, I.3'teki explainability şekli. `financial_health_scores` tablosu/migration (Q.3'e bağlı — result_json içinde mi ayrı tabloda mı kalıcı olacağı burada kesinleştirilir). Bağımlılık: 4.3B'nin tüm "Core" oranları hazır olmalı (Health Score bunları girdi alır).

### Milestone 4.3E — Credit Score Architecture

**Kapsam:** `credit_score.py` (Bölüm F) — F.2'deki kritik/destekleyici ayrımı, F.3'teki not eşikleri, F.4'teki sınırların `result_json`'a otomatik yazılması, I.4'teki explainability. `credit_score_results` tablosu/migration (Q.3'e bağlı). Bağımlılık: 4.3B (oranlar) + 4.3D (Health Score'un bazı ara hesaplamaları — ör. `sustainable_growth_rate` gibi bazı oranlar Health Score'un E.4 bant mantığıyla paylaşılan altyapıyı kullanabilir, implementasyon detayı).

### Milestone 4.3F — Recommendation Engine Architecture

**Kapsam:** H.3'teki `recompute_ratios_with_overrides` what-if motoru, H.2'deki 4 recommendation türünün **matematiksel** (metin-üretimsiz, H.5) implementasyonu, `recommendation.py`. Bağımlılık: 4.3B (temel oranlar), 4.3C (Tür 2 — benchmark gap için), 4.3D/4.3E (Tür 3/4 — skor simülasyonu için). **Bu faz kasıtlı olarak son sıradadır** çünkü diğer tüm bileşenlere bağımlıdır.

---

## Bölüm P — Milestone 4.3 Implementation Plan (Görev Bazlı)

*(4.1/4.2'nin görev listeleri detay seviyesinde — implementasyon başladığında bu liste birebir görev takibi için kullanılacaktır. Hiçbiri şu an başlatılmamıştır.)*

**4.3A — Foundation (tahmini 12 görev):** (1) `ratio_derived_facts.py` yaz — `total_liabilities`/`average_*`/`days_in_period` türetimi. (2) `ProvenanceEntry`'yi I.2'deki additive alanlarla genişlet. (3) `RATIO_REGISTRY_VERSION` sabiti ekle. (4) `compute_registered_ratio()` yaz (D.2 Karar 4). (5) `EngineRunContext`'i M.2'deki 4 alanla genişlet. (6) `AnalysisType.FINANCIAL_RATIOS` için `FinancialRatioEngineAdapter` iskeletini yaz (`status=not_calculable` sabit). (7) Registry'ye kaydet (M.4). (8) BS Engine'in `compute_preliminary_structural_ratios`'unu `RATIO_REGISTRY`'ye yönlendir (D.2 Karar 1) — 9 mevcut formülü kaydet. (9) IS Engine'in `compute_margins`'ini aynı şekilde yönlendir. (10) `ratio_formulas.py`'ye ilk 9 `RatioFormulaMetadata` kaydını ekle. (11) L.1/L.3/L.4 testlerinin ilk seti (yalnızca 9 formül için). (12) Syntax check + regresyon (mevcut 174+ test hâlâ yeşil mi).

**4.3B — Core Ratios (tahmini 20 görev):** (13-19) C.1/C.2/C.3/C.4/C.5/C.6/C.8'in kalan ~74 `RatioFormulaMetadata` kaydı, kategori başına ayrı görev. (20) `ratio_explanations.py` — 93 oranın açıklama şablonu. (21) `FinancialRatioEngineAdapter`'ı gerçek hesaplama yapacak şekilde tamamla. (22) `ratio_recompute.py` — B.11'deki FAZ-sonrası orkestrasyon. (23) `app/services/bulk_upload.py`'ye **yalnızca** confirm-sonrası çağrı ekle (M.3 — dahili mantığa dokunma). (24) Sentetik fixture'lar — BS+IS'i tam dolu bir dönem senaryosu. (25) L.6 golden dataset — elle hesaplanmış referans. (26) L.1/L.4/L.5/L.9 tam kapsam. (27) L.8 performans testi + ölçüm raporu. (28) API router `financial_ratios.py` — GET endpoint. (29) `tests/README.md` güncelleme. (30) Syntax + regresyon + final rapor.

**4.3C — Benchmark Foundation (tahmini 10 görev):** (31) `IndustrySector`/`IndustryBenchmarkSet`/`IndustryBenchmarkValue` modelleri. (32) `Company.sector_code` additive kolon. (33) Migration + cross-check (PostgreSQL 63 karakter kısıt disiplini — A.10 hatırlatması). (34) `benchmark_types.py` (saf dataclass'lar). (35) `benchmark_ingestion.py` — manuel/CSV girişi Protocol + implementasyonu. (36) `benchmarks.py` API router. (37) G.4 versiyonlama mantığı. (38) `benchmark_comparison` alanının Ratio Engine `result_json`'a entegrasyonu (K.2). (39) L.10 testleri. (40) Syntax + regresyon + final rapor.

**4.3D — Health Score (tahmini 10 görev):** (41) `health_score.py` — E.3 Model C ağırıkları. (42) E.4 eşik-bantlama fonksiyonu (sabit bantlar). (43) E.5 eksik-veri yeniden-normalizasyon. (44) I.3 explainability şekli. (45) `financial_health_scores` tablosu/migration (Q.3 kararına göre). (46) `health_score` alanının `result_json`'a entegrasyonu. (47) L.1/L.4 testleri (Health Score özelinde — eşik sınırları, eksik kategori senaryoları). (48) Golden dataset genişletme. (49) API entegrasyonu. (50) Syntax + regresyon + final rapor.

**4.3E — Credit Score (tahmini 9 görev):** (51) `credit_score.py` — F.2 kritik/destekleyici ayrımı. (52) F.3 not eşikleri + kritik-tavan override mantığı. (53) F.4 sınırlar listesinin sabit içerik olarak gömülmesi. (54) I.4 explainability. (55) `credit_score_results` tablosu/migration (Q.3). (56) `result_json` entegrasyonu. (57) Testler (kritik-tavan senaryoları dahil). (58) API entegrasyonu. (59) Syntax + regresyon + final rapor.

**4.3F — Recommendation Engine (tahmini 8 görev):** (60) `recompute_ratios_with_overrides()` — H.3. (61) H.2 Tür 1 (hedef-oran tersine-çözüm). (62) H.2 Tür 2 (benchmark-farkı, 4.3C'ye bağımlı). (63) H.2 Tür 3/4 (skor simülasyonu, 4.3D/E'ye bağımlı). (64) `recommendation.py` — H.4 işletme sermayesi simülasyonu. (65) `what_if_scenarios` alanının `result_json`'a entegrasyonu (K.2 — kalıcı yazılmaz, yalnızca istek-yanıt). (66) L.11 testleri. (67) Syntax + regresyon + **milestone 4.3'ün tamamının** final raporu.

**Toplam tahmini görev sayısı: ~69** (4.1'in ~11, 4.2'nin ~13 görevine kıyasla, Ratio Engine'in kapsamının genişliğini yansıtır — bu bir üst sınır tahminidir, implementasyon sırasında alt görevlere bölünebilir ya da birleştirilebilir).

---

## Bölüm Q — Kapanış Soruları

### Q.1 Bu mimari mevcut FINOS altyapısıyla yüzde kaç uyumlu?

**~90% uyumlu.** Gerekçe: `EngineAdapter`/`registry`/`canonical_facts`/`calculation_provenance`/`reconciliation`/`FinancialAnalysisResultSource`/`SourceMode.MULTI_SOURCE_DERIVED` altyapılarının **tamamı zaten var ve Ratio Engine'i öngörecek şekilde tasarlanmış** (A.2, A.6 — "Financial Ratio Engine -- Milestone 4.3" ismiyle kod içi docstring'lerde zaten anılıyor). Uyumsuz/yeni olan %10'luk kısım: (1) `EngineRunContext`'in çoklu-BS/IS-sonuç taşıma alanları (additive, kırıcı değil), (2) FAZ2/FAZ3'e değil FAZ-sonrasına bağlanan **yeni bir orkestrasyon yolu** (B.11 — mevcut orkestrasyonu değiştirmez, yanına eklenir), (3) Health Score/Credit Score/Benchmark için **tamamen yeni** tablolar (mevcut şemayla çakışmaz, yalnızca genişletir).

### Q.2 Mevcut sistemde değiştirilmesi gereken noktalar var mı?

**Evet, iki nokta — ikisi de additive/genişletme, kırıcı değil:** (1) BS Engine'in `compute_preliminary_structural_ratios`'u ve IS Engine'in `compute_margins`'i, D.2 Karar 1 gereği kendi Decimal aritmetiklerini bırakıp `RATIO_REGISTRY`'ye yönlendirilecek — dış `result_json` şekli **değişmez** (D.2 Karar 2), yalnızca iç hesaplama kaynağı merkezileşir. (2) `EngineRunContext`/`ProvenanceEntry` M.2/I.2'deki additive alanlarla genişletilecek. **Değiştirilmeyecek (kapsam dışı, A.8/D.2 Karar 3):** `app/trial_balance/ratios.py`, `app/trial_balance/insights.py`, mizan motorunun kendi `result_json` sözleşmesi.

### Q.3 Hangi tasarım kararları kesin alınmalı?

Şu kararlar implementasyon başlamadan **önce kesinleştirilmelidir** (bu doküman öneri sunar, onay bekler): (1) `RATIO_REGISTRY`'nin tek formül kaynağı olması ve BS/IS'in buna yönlendirilmesi (Bölüm D — mimarinin temel taşı, sonradan değiştirmek maliyetli). (2) Health Score kategori ağırıkları — Model C (E.3) önerisi, ama kesin sayılar (%18/%22/%18/%14/%10/%10/%8) implementasyon öncesi son onay gerektirir. (3) Ratio Engine'in tetiklenme modeli — FAZ-sonrası ayrı orkestrasyon (B.11), FAZ2/FAZ3'ün içine değil. (4) `SourceMode.MULTI_SOURCE_DERIVED` + `financial_analysis_result_sources`'ın Ratio Engine için **değiştirilmeden** kullanılması (Bölüm B.8 — yeni bir izlenebilirlik mekanizması icat edilmeyecek).

### Q.4 Hangi kararlar implementasyon öncesinde tekrar onay gerektiriyor?

(1) **Health Score/Credit Score'un kalıcılık modeli** (M.5, Q.3'te de anılan açık soru) — ayrı tablo mı (`financial_health_scores`, `credit_score_results`) yoksa yalnızca Ratio Engine'in `result_json`'ı içinde mi kalacak? Ayrı tablo, tarihsel trend sorgulamayı kolaylaştırır ama şema karmaşıklığı ekler; yalnızca `result_json`, basit ama trend sorgusu için her seferinde JSON parse gerektirir. (2) **`ratio_recompute.py`'nin senkron mu asenkron mu çalışacağı** (N.5) — asenkron seçilirse bugün FINOS'ta hiç olmayan bir kuyruk/arka plan iş altyapısı gerekir, bu kapsamı genişletir ve ayrı bir onay gerektirir. (3) **Benchmark'ın ilk sürümde hangi sektör(ler) için manuel veri ile doldurulacağı** (G.3/G.5) — bu bir ürün/iş kararıdır, mimari bir karar değildir. (4) **Sektöre-özgü Health Score bantlama'nın ne zaman aktifleşeceği** (E.4'ün "dürüst MVP" notu) — 4.3D'de sabit bantlarla mı başlanacak, yoksa 4.3C ile eş zamanlı mı geliştirilecek?

### Q.5 Bu milestone tamamlandığında FINOS'un genel proje ilerlemesi yaklaşık yüzde kaç olacak?

Milestone haritası: Milestone 1-3 (temel altyapı, mizan, sınıflandırma, bulk upload, onay akışı) + Milestone 4.1 (Analysis Foundation) + Milestone 4.2 (Balance Sheet/Income Statement) tamamlandı. Milestone 4 kapsamında planlanan alt-milestonelar: 4.1 ✓, 4.2 ✓, 4.3 (bu doküman), 4.4 (Cash Flow), 4.5 (Tax Return). Milestone 4'ün kendisi FINOS'un "analiz motorları" katmanının tamamıdır; bunun ötesinde (bu doküman kapsamında bilinmeyen, önceki mimari dokümanlarda da henüz detaylandırılmamış) muhtemel gelecek milestonelar: raporlama/sunum katmanı, çok-dönemli konsolide analiz, kullanıcı arayüzü entegrasyonu, gerçek benchmark veri entegrasyonları (G.3'ün "mimari hazır ama implementasyon yok" durumdan çıkması), Recommendation Engine'in metin üretimi (H.5'in bıraktığı boşluk). Bu bilinmezlik nedeniyle **kesin bir yüzde iddia etmek yanıltıcı olur** — dürüst bir kaba tahmin: Milestone 4'ün alt-fazları (4.1-4.5) FINOS'un "çekirdek analiz motoru" hedefinin tamamı sayılırsa, 4.3'ün tamamlanması bu çekirdeğin **~60%'ını** (4.1+4.2+4.3, ratio engine'in kapsamının cash_flow/tax_return'e göre daha büyük olması nedeniyle ağırlıklı) temsil eder; FINOS'un **toplam** ürün vizyonu (raporlama, benchmark entegrasyonu, recommendation metin üretimi, UI gibi bu dokümanın kapsamı dışındaki katmanlar dahil) içindeyse bu oran **çok daha düşüktür** ve şu an güvenilir biçimde tahmin edilemez — bu dürüstlük, kullanıcının Credit Score için istediği "sınırları açıkça yaz" ilkesinin (Bölüm F.4) bu kapanış sorusuna da uygulanmış halidir.

---

---

## Bölüm R — Milestone 4.3A Revizyon Kararları (2. Tur Onay)

Mimari doküman genel olarak onaylandı. Bu bölüm, kullanıcının 2. tur onayında verdiği 9 kararı tasarıma işler ve **yalnızca Milestone 4.3A**'nın revize kapsamını/planını tanımlar. 4.3B–4.3F bu bölümden **etkilenmez**, Bölüm O/P'deki mevcut tanımları geçerliliğini korur (yalnızca 4.3A'nın kendi alt-bölümleri bu revizyonla güncellenmiş sayılır).

### R.1 Calculation Strategy sistemi (madde 1) — `RatioFormulaMetadata`'nın revizyonu

**Sorun:** Orijinal tasarımdaki (A.9, D.2) `numerator_fields`/`denominator_fields` yalnızca "a/b" şeklindeki basit bölmeleri ifade edebiliyor; toplama (`total_liabilities = short_term + long_term`), çıkarma (`net_working_capital`), gelecekte ortalama-bakiye, mutlak değer, gün dönüşümü, oran-oranı (ratio-of-ratio) ve boolean/kategorik sonuçlar (`liquidity_risk_flag`, Bölüm C.12) için yetersiz.

**Karar:** `eval`/dinamik kod/string-expression **kullanılmaz**. Bunun yerine, **kapalı bir küme** (closed set) halinde, adı `RatioFormulaMetadata.calculation_strategy: str` alanıyla seçilen, her biri saf ve tek başına test edilebilir Python fonksiyonlarına yönlenen bir **strateji dispatch tablosu** tasarlanır:

```
CALCULATION_STRATEGIES: dict[str, Callable[[RatioFormulaMetadata, dict[str, Decimal | None]], ComputationOutcome]]
```

**4.3A'da tanımlanacak iki strateji** (ilk 9 oranın tamamını kapsar):

- `"sum_division"` — `value = sum(numerator_fields) / sum(denominator_fields)`. Herhangi bir alan `None` ise `MISSING_INPUT`; tüm alanlar doluyken payda toplamı tam olarak `0` ise `metadata.zero_denominator_status`'a bakılır (bkz. R.2); aksi halde `CALCULATED`.
- `"linear_combination"` — `value = sum(addend_fields) - sum(subtrahend_fields)`. Bölme/payda kavramı yok; herhangi bir alan `None` ise `MISSING_INPUT`, aksi halde her zaman `CALCULATED`.

**`RatioFormulaMetadata` revize şekli** (flat dataclass, mevcut kod tabanının stiliyle tutarlı — `ProvenanceEntry`/`ReconciliationFinding` deseni):

```
key, category, display_name_tr, unit, calculation_strategy: str,
numerator_fields: tuple[str, ...] = (),
denominator_fields: tuple[str, ...] = (),
addend_fields: tuple[str, ...] = (),
subtrahend_fields: tuple[str, ...] = (),
zero_denominator_status: ComputationStatus = ComputationStatus.UNDEFINED_ZERO_DENOMINATOR,
quantize_exp: str = "0.0001",
```

Her strateji yalnızca kendi ilgili alanlarını okur (ör. `linear_combination` `numerator_fields`'i hiç kullanmaz) — bu, birkaç kullanılmayan alan pahasına (kabul edilen basitlik/saflık ödünleşimi) tip-güvenli, `Union`/discriminated-type karmaşıklığı olmadan bir tasarım sağlar.

**İleride (4.3B+, bu turda İNŞA EDİLMEZ, yalnızca tasarımı önceden not edilir):** `"average_balance_division"` (ortalama bakiye gerektiren devir hızları), `"days_conversion"` (`days_in_period / base_ratio_key` — başka bir zaten-kayıtlı `RATIO_REGISTRY` anahtarına referans verir, sıfırdan hesaplamaz), `"ratio_of_ratio"` (bir oranın başka bir oranla ilişkisi), `"boolean_threshold"` (`liquidity_risk_flag` gibi kategorik sonuçlar). Bu dört strateji **yalnızca isim ve genel imza olarak** burada kayıt altına alınır; 4.3A kapsamında hiçbiri implemente edilmez.

**`compute_registered_ratio(key: str, facts: dict[str, Decimal | None]) -> tuple[ComputationOutcome, ProvenanceEntry]`** — D.2 Karar 4'ün somutlaşmış hali: `RATIO_REGISTRY[key]`'i okur, `CALCULATION_STRATEGIES[metadata.calculation_strategy]`'yi çağırır, `ProvenanceEntry`'yi (I.2) aynı çağrıda üretir. BS/IS Engine'ler ve (ileride) Ratio Engine **yalnızca bu fonksiyonu** çağırır — Decimal aritmetiği hiçbir çağıran motorda tekrar yazılmaz.

### R.2 Computation Status sözleşmesi (madde 2)

**Yeni enum — `ComputationStatus`** (`app/engines/common/ratio_formulas.py`'ye eklenecek):

| Değer | Anlamı |
|---|---|
| `calculated` | Değer başarıyla hesaplandı, `value` doludur. |
| `missing_input` | Gerekli alanlardan en az biri `None` — veri hiç yok/eksik. |
| `undefined_zero_denominator` | Tüm girdiler doluydu (hiçbiri `None` değil) ama payda **gerçekten** `0` ve bu oran için sıfır paydanın tanımlı bir iş anlamı **yok** (matematiksel olarak tanımsız, ör. `debt_to_equity` için `equity=0`) — yüksek önemli bir `warning` eşlik eder. |
| `no_obligation` | Payda **gerçekten** `0` ve bu, o oran için **açık, olumlu/nötr bir iş durumunu** ifade ediyor (ör. `current_ratio` için `short_term_liabilities=0` → "şirketin kısa vadeli borcu yok"). Değer yine `None`'dır (0'a bölme yapılmaz) ama durum `undefined_zero_denominator`'dan **ayrıdır**. |
| `not_applicable` | Bu oranın formülü, mevcut `source_mode`/bağlam için **yapısal olarak** hiç uygulanamaz (ör. `quick_ratio`, `source_mode=trial_balance_derived` iken — mizan motoru `inventory` alanını hiçbir zaman üretmez; bu, "bu kayıtta veri eksik" değil "bu kaynaktan bu asla gelmez" anlamındadır). |
| `not_calculable` | Formülün ihtiyaç duyduğu alan **hiçbir motorda/canonical_facts'te tanımlı değil** (Bölüm C'deki ~15 "girdisi hiç yok" oranı — ör. `share_count`). Kayıt-zamanı/katalog-seviyesi bir durumdur, çalışma-zamanında normalde hiç tetiklenmez. |

**`ComputationOutcome` dataclass:** `{value: Decimal | None, status: ComputationStatus, missing_inputs: tuple[str, ...] = (), note: str | None = None}`. **Hiçbir zaman** `Decimal("Infinity")`/`float("nan")` üretilmez — tanımsız/no-obligation/eksik durumların **hepsinde** `value=None`, iş anlamı yalnızca `status` (ve gerekirse `warnings` listesindeki bir kayıt, `undefined_zero_denominator` için otomatik) üzerinden taşınır.

**`None` vs. gerçek `0` ayrımı — somut kural:** Bir alan `facts` sözlüğünde `None` ise → `missing_input`. Aynı alan `Decimal("0")` ise (gerçekten sıfır, `canonical_facts`'in "eksik veri asla 0 değildir" ilkesi zaten bu ayrımı üretim noktasında garanti ediyor, B.5) → strateji fonksiyonu bunu **girdi eksikliği olarak değil, gerçek bir sayısal değer olarak** işler; yalnızca bu değer **payda toplamının tamamı** `0` yaparsa `zero_denominator_status` devreye girer.

**4.3A'daki 9 oran için `zero_denominator_status` ataması:**

| Oran | `zero_denominator_status` | Gerekçe |
|---|---|---|
| `current_ratio`, `working_capital_ratio` | `no_obligation` | `short_term_liabilities=0` → kısa vadeli borç yok, olumlu/nötr bir durum |
| `debt_ratio`, `equity_ratio` | `undefined_zero_denominator` (varsayılan) | `total_assets=0` muhasebesel olarak anlamsız/tanımsız bir durum |
| `debt_to_equity` | `undefined_zero_denominator` (varsayılan) | `equity=0` ciddi bir finansal sıkıntı işaretidir, "borç yok" ile karıştırılamaz — yüksek önemli warning üretir |
| `gross_profit_margin`, `operating_profit_margin`, `net_profit_margin` | `undefined_zero_denominator` (varsayılan) | `net_sales=0` — dönemde hiç satış yok, marj tanımsız |
| `net_working_capital` | *(yok — `linear_combination`, payda kavramı yok)* | — |

### R.3 Health/Credit Score kalıcılık modeli (madde 3)

Karar kesinleşti: ayrı DB tablosu **yok**; ileride Ratio Engine'in `FinancialAnalysisResult.result_json`'u içinde immutable/versiyonlu saklanacak (M.5'teki "Q.3'e bağlı" notu bu kararla **kapandı** — `financial_health_scores`/`credit_score_results` tabloları M.1/M.5'ten **çıkarılmıştır**). 4.3A kapsamında zaten hiçbir Health/Credit Score kodu yazılmıyor — bu yalnızca ileriye dönük bir mimari kayıt.

### R.4 `ratio_recompute` tasarımı — 4.3A'da yazılmayacak, yalnızca sözleşmesi kesinleşti (madde 4)

Tasarım (B.11'in netleştirilmiş hali, implementasyonu **4.3B'ye** bırakılıyor): bulk upload confirm transaction'ı commit edildikten **sonra**, **ayrı bir DB transaction'ında** çalışır; hata durumunda **confirmed batch'i geri almaz** (rollback yapmaz), yalnızca kendi `FinancialAnalysisResult`'ını `status=FAILED` + `error_message` ile yazar (BS/IS Engine'lerin bugünkü hata-yazma deseniyle tutarlı, A.5) — bu, batch onayı ile oran hesaplaması arasında **hata izolasyonu** sağlar. İlk sürüm **senkron**dur (kuyruk/arka plan iş altyapısı yok, N.5/Q.4'teki açık soru bu turda "senkron" olarak kapatıldı). **4.3A'da `app/services/ratio_recompute.py` dosyası oluşturulmayacak** — yalnızca bu sözleşme (imza + davranış) burada kayıt altına alınmıştır; dosyanın kendisi ve `bulk_upload.py`'ye bağlanması 4.3B'nin işidir.

### R.5 4.3A'nın kesinleşmiş kapsamı (madde 5 + yukarıdaki kararların birleşimi)

**İçinde:**
1. `ComputationStatus` enum + `ComputationOutcome` dataclass (R.2).
2. `CalculationStrategy` dispatch sistemi — yalnızca `sum_division` + `linear_combination` (R.1).
3. `RatioFormulaMetadata`'nın revize şekli + `RATIO_REGISTRY`'ye ilk 9 kayıt (current_ratio, debt_ratio, equity_ratio, debt_to_equity, net_working_capital, working_capital_ratio, gross_profit_margin, operating_profit_margin, net_profit_margin).
4. `compute_registered_ratio()` merkezi fonksiyonu.
5. Derived facts altyapısı — **yalnızca** `total_liabilities` (debt_ratio/debt_to_equity'nin ihtiyacı) ve `days_in_period` (R.8/madde 8 kuralıyla, gerçek tarih farkı — henüz hiçbir 4.3A oranı tarafından tüketilmese de altyapı olarak kuruluyor). `average_*` alanları (önceki döneme bağımlı) **4.3A'da YOK** — hiçbir 4.3A oranı bunu kullanmıyor, önceki-dönem `EngineRunContext` alanları henüz gerçek veriyle beslenmiyor olacağı için ertelendi.
6. `ProvenanceEntry`'nin I.2'deki additive alanlarla genişletilmesi.
7. `EngineRunContext`'e M.2'deki 4 yeni alan (`balance_sheet_result`, `income_statement_result`, `prior_period_balance_sheet_result`, `prior_period_income_statement_result`) — additive, hiçbir mevcut adaptörü etkilemez.
8. `FinancialRatioEngineAdapter` — **artık yalnızca iskelet değil**, gerçek 9 oranı hesaplayan ama registry dışında hiçbir yere (bulk upload akışı, `ratio_recompute`) bağlanmayan bir adaptör. `analysis_type=FINANCIAL_RATIOS`, `requires_content=False`, `context.balance_sheet_result`/`context.income_statement_result`'tan okur.
9. Registry kaydı (`_ENGINE_BY_ANALYSIS_TYPE`'a eklenir; `_DETECTED_TYPE_TO_ANALYSIS_TYPE`/`_DOCUMENT_TYPE_TO_ANALYSIS_TYPE`'a **eklenmez**, B.10).
10. `balance_sheet/analyzer.py::compute_preliminary_structural_ratios` ve `income_statement/analyzer.py::compute_margins`'in `compute_registered_ratio()`'ya yönlendirilmesi (D.2 Karar 1/2) — `result_json` şekli **birebir korunur**, yalnızca iç hesaplama kaynağı merkezileşir.
11. Birim testleri (R.2'deki her `ComputationStatus` dalı için, özellikle `no_obligation`/`undefined_zero_denominator` ayrımı) + regresyon testleri (BS/IS `result_json`'ın değişmediğinin ve değerlerin bit-bir aynı kaldığının doğrulanması, D.3 invariant'ı).

**Dışında (kesinlikle yapılmayacak):** 4.3B'nin diğer oranları, benchmark/Health Score/Credit Score/Recommendation implementasyonu, herhangi bir migration, `ratio_recompute.py` dosyası ve bağlanması, commit/push.

### R.6 Diğer maddelerin teyidi

Madde 6 (Altman basitleştirilmiş) → C.12 düzeltildi (yukarıda). Madde 7 (Health Score ağırıkları/Credit Score eşikleri taslak, yeniden onay gerektirir) → Bölüm E.3/F.3 zaten "önerilen"/"taslak bant" diliyle yazılmıştı, bu tur bunu **teyit eder**, hiçbir sayı bu turda kesinleşmedi. Madde 8 (days_in_period) → A.10/C.0 düzeltildi (yukarıda). Madde 9 → bu bölümün kendisi, kodlamadan önce sunulan revize plandır.

---

## Bölüm S — Milestone 4.3A Uygulama Planı (Onay Bekliyor — Kod Yazılmadı)

*(Bölüm P'deki orijinal "4.3A" alt-listesinin yerini alır; 4.3B–4.3F Bölüm P'de değişmeden kalır.)*

1. `app/engines/common/ratio_formulas.py`: `ComputationStatus` enum, `ComputationOutcome` dataclass ekle.
2. Aynı dosyada `RatioFormulaMetadata`'yı R.1'deki revize şekle güncelle (`calculation_strategy`, `addend_fields`, `subtrahend_fields`, `zero_denominator_status` alanları eklenir; `numerator_fields`/`denominator_fields` korunur).
3. `compute_sum_division()` ve `compute_linear_combination()` saf fonksiyonlarını yaz + `CALCULATION_STRATEGIES` dispatch sözlüğünü kaydet.
4. `compute_registered_ratio(key, facts) -> tuple[ComputationOutcome, ProvenanceEntry]` yaz.
5. `RATIO_REGISTRY`'ye ilk 9 `RatioFormulaMetadata` kaydını R.2 tablosundaki `zero_denominator_status` atamalarıyla ekle.
6. `app/engines/common/ratio_derived_facts.py` (yeni dosya): `compute_total_liabilities()`, `compute_days_in_period()` (R.8/madde 8 kuralı — gerçek tarih farkı birincil, `months_covered*30` yalnızca açık düşük-güven fallback).
7. `app/engines/common/calculation_provenance.py`: `ProvenanceEntry`'ye I.2'deki additive alanları (`source_analysis_result_ids`, `reliability`, `rounding_applied`) ekle — mevcut çağıranları bozmayan varsayılan değerlerle.
8. `app/engines/protocol.py`: `EngineRunContext`'e M.2'deki 4 additive alanı ekle.
9. `app/engines/financial_ratios/` yeni paket: `__init__.py`, `adapter.py` (`FinancialRatioEngineAdapter` — 9 oranı hesaplar), `service.py` (`analyze_financial_ratios()` — BS/IS `result_json`'larından `canonical_facts`'e dönüşüm + `compute_registered_ratio` çağrıları + `result_json` üretimi, K.2 şekline uygun ama yalnızca 9 oranı dolu, diğer kategoriler `not_calculable`/boş).
10. `app/engines/registry.py`: `FinancialRatioEngineAdapter` import + `_ENGINE_BY_ANALYSIS_TYPE` kaydı (yalnızca bu iki satır — B.10, M.4).
11. `app/engines/balance_sheet/analyzer.py::compute_preliminary_structural_ratios`'u `compute_registered_ratio()`'ya yönlendir — `result_json["preliminary_structural_ratios"]` şekli değişmez.
12. `app/engines/income_statement/analyzer.py::compute_margins`'i aynı şekilde yönlendir — `result_json["margins"]` şekli değişmez.
13. Birim testleri: `tests/test_ratio_formulas_unit.py` (yeni) — `compute_sum_division`/`compute_linear_combination`'ın her `ComputationStatus` dalı, R.2'deki `zero_denominator_status` atamalarının 9 oran için doğruluğu, `compute_registered_ratio`'nun provenance üretimi.
14. Regresyon testleri: mevcut `tests/test_engine_balance_income_statement_unit.py`'nin **hiç değişmeden** yeşil kalması (D.3 invariant — preliminary oranların sayısal değeri değişmedi) + D.3'teki yeni bit-birebir-eşitlik testi.
15. `py_compile` ile tüm değişen/yeni dosyaların syntax kontrolü + sandbox'ta çalıştırılabilen testlerin tam koşumu + mevcut 177 testin regresyon durumunun (sandbox'ta koşulabilenler için gerçek koşum, Docker/Postgres gerektirenler için dürüst "koşulamadı" notu) raporlanması.
16. Final rapor: değişen dosyalar, merkezi formül sözleşmesinin nihai şekli, sıfır-payda/eksik-veri davranışının somut örneklerle gösterimi, çalıştırılan/çalıştırılamayan testler, regresyon sonucu, git durumu (commit/push yapılmadığının teyidi).

**Bu plan onaylanmadan hiçbir kod yazılmayacaktır.**

---

*Doküman sonu (2. tur revizyonla). Onay bekleniyor — hiçbir kod, migration veya test bu doküman hazırlanırken/güncellenirken yazılmadı.*

