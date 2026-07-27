# Milestone 4.3E — Credit Score Engine Teknik Tasarımı

**Durum: TASARIM AŞAMASI — KARARLAR KİLİTLENDİ (2. tur) — SON ONAY
BEKLİYOR**

Bu doküman yalnızca Milestone 4.3E'nin (Credit Score Engine) teknik
tasarımını içerir. **Hiçbir kod yazılmadı, hiçbir test yazılmadı, hiçbir
migration oluşturulmadı, hiçbir API/adapter eklenmedi, bulk upload
davranışına dokunulmadı, hiçbir mevcut dosya doküman dışında
değiştirilmedi, hiçbir commit/push yapılmadı.** Bu dokümandaki tüm
dataclass/fonksiyon tanımları, dosya yolları, ağırlık/eşik değerleri
**onaylanan** bir tasarımdır — implementasyon yalnızca kullanıcının ayrı,
açık bir "başla" talimatıyla başlayacaktır.

Bu, ilk turdaki tasarım taslağının ARDINDAN, kullanıcının Bölüm 26'daki
tüm açık kararları **bağlayıcı kararlarla KİLİTLEDİĞİ** 2. ve son karar
turudur. Bölüm 26 artık "Açık Tasarım Kararları" değil, **"Onaylanmış
Kararlar"** başlığı taşır — 15 kararın TAMAMI kapatılmıştır, açık karar
KALMAMIŞTIR.

---

## Bölüm 1 — Mevcut Sistem İncelemesi

### 1.1 Financial Ratio Engine (Milestone 4.3A/4.3B)

- `app/engines/common/ratio_formulas.py::RATIO_REGISTRY` — **57 kayıtlı
  oran**, 7 kategori: `liquidity` (7), `leverage` (10), `profitability`
  (11), `activity` (10), `efficiency` (6), `growth` (7), `cash_flow` (6,
  hepsi `not_calculable` — Cash Flow Engine henüz yok).
  `RATIO_REGISTRY_VERSION = "1.1.0"`.
- `ComputationStatus`: `calculated` / `missing_input` /
  `undefined_zero_denominator` / `no_obligation` / `not_applicable` /
  `not_calculable`.
- `reliability`: `high` / `medium` / `medium_low` / `low` /
  `not_calculable` — `app/engines/common/reliability.py::RELIABILITY_RANK`
  ile karşılaştırılır (`worse_reliability` — iki güvenilirlikten kötüsünü
  seçer).
- `app/engines/financial_ratios/service.py::analyze_financial_ratios()`
  — saf orkestrasyon fonksiyonu; `app/engines/financial_ratios/
  adapter.py::FinancialRatioEngineAdapter` — `EngineAdapter` protokolüne
  bağlı AMA hiçbir akışa (bulk upload, API) HENÜZ TAKILI DEĞİL.

### 1.2 Benchmark Engine (Milestone 4.3C)

- `app/engines/common/benchmark_types.py` — `BENCHMARK_REGISTRY: dict[str,
  BenchmarkMetadata] = {}` (boş tanım) + `register_benchmark()` (kayıt
  anında `RATIO_REGISTRY`'de var olma zorunluluğunu doğrular — **bu
  validasyon 4.3E'de de AYNEN korunacaktır, gevşetilmeyecektir**).
  `BenchmarkIdealDirection`: `HIGHER_IS_BETTER` / `LOWER_IS_BETTER` /
  `RANGE_IS_BETTER`. `BenchmarkThresholds` (excellent/good/average/weak/
  critical — skaler ya da `(lo, hi)` demeti).
- `app/engines/common/benchmark_registry.py` — `BENCHMARK_REGISTRY`'yi
  GERÇEK 48 girdiyle DOLDURAN modül (import edilmesi bir YAN ETKİDİR).
  `BENCHMARK_REGISTRY_VERSION = "1.0.0"`. Her girdi `source=
  "internal_heuristic"`, `provisional=True`, `reliability_ceiling=
  "medium"` (büyümede `"medium_low"`) taşır.
- `app/engines/benchmarks/service.py::evaluate_benchmarks(ratio_result_
  json) -> dict` — saf, bağımsız kütüphane fonksiyonu; sıfır API/adapter/
  DB bağlantısı.

### 1.3 Financial Health Score Engine (Milestone 4.3D) — DOĞRULANMIŞ DURUM

**Milestone 4.3D TAMAMLANDI, GERÇEK Docker ortamında DOĞRULANDI ve
commit'lendi:**

- Gerçek Docker/pytest sonucu: **531 passed, 0 failed, 10 warnings.**
- Commit: **`71ca335`** — "feat(health-score): implement Milestone 4.3D
  Financial Health Score engine".
- İki gerçek-ortam-özel hata (RATIO_REGISTRY sızıntısı ve `tests/
  conftest.py` import-sırası hatası) bulunup KÖK NEDENİNDEN düzeltildi;
  ikisi de bu 531 testin İÇİNDE, kalıcı regresyon testleriyle
  KORUNMAKTADIR (Bölüm 1.6).

Bu artık kanıtlanmış, üretimde-doğrulanmış bir zemindir — 4.3E bu zemin
ÜZERİNE inşa eder.

- `app/engines/common/health_score_types.py`:
  - `HealthScoreTier` (excellent/good/average/weak/critical — Benchmark
    Engine'in tier sözlüğüyle birebir aynı).
  - `HealthScoreComputationStatus`: `COMPUTED` / `HARD_FAIL_CAPPED` /
    `INSUFFICIENT_DATA`.
  - Sabitler: `TIER_TO_POINTS` (100/75/50/25/0),
    `PROVISIONAL_CONFIDENCE_CEILING = Decimal("0.60")`,
    `INSUFFICIENT_DATA_COVERAGE_THRESHOLD = Decimal("0.50")`,
    `LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD = Decimal("0.70")`,
    `CRITICAL_OVERRIDE_WEAK_MULTIPLIER = Decimal("0.90")`,
    `CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER = Decimal("0.70")`,
    `CRITICAL_OVERRIDE_CATEGORY_FLOOR = Decimal("0.50")`,
    `STRENGTHS_WEAKNESSES_COUNT = 5`, `CONFIDENCE_RELIABILITY_WEIGHT`
    (high=1.0/medium=0.66/medium_low=0.5/low=0.33/not_calculable=0).
  - Paylaşılan yardımcılar: `normalize_weights()`, `clamp_score()` —
    **4.3E bunları YENİDEN YAZMAZ, aynı modülden import eder.**
  - Dataclass'lar: `CategoryWeightProfile`, `RatioScoreWeight`,
    `HardFailRule`, `CriticalOverrideRule`, `RatioContribution`,
    `CategoryBreakdown`, `HealthScoreResult` (tam alan listesi Bölüm
    1.3.1'de).
- `app/engines/common/health_score_registry.py` — GERÇEK, commit'lenmiş
  içerik (bu doküman bu içeriği DEĞİŞTİRMEZ, yalnızca OKUR/referans
  alır):
  - `RATIO_SCORE_WEIGHTS` — 48 girdi: **42 scored + 6 explainability-
    only** (liquidity 5/1, leverage 7/2, profitability 11/0, activity
    7/3, efficiency 6/0, growth 6/0). 6 duplicate: `working_capital_
    ratio`, `debt_ratio`, `financial_leverage_multiplier`, `days_
    inventory_outstanding`, `days_sales_outstanding`, `payables_
    turnover`. **ÖNEMLİ:** Health Score'da `debt_to_equity` SCORED'DUR
    (Health Score'un KENDİ, zaten commit'lenmiş kararı) — Credit Score
    bu ratio'yu KENDİ registry'sinde FARKLI sınıflandırır (Bölüm 7/9,
    Health Score'un koduna DOKUNULMAZ, yalnızca Credit Score'un KENDİ,
    ayrı registry'sinde farklı bir politika uygulanır).
  - `CATEGORY_WEIGHT_PROFILES` — YALNIZCA `("global", None)` dolu:
    liquidity %20, leverage %25, profitability %20, activity %15,
    efficiency %10, growth %10, cash_flow %0 (yapısal).
  - `HARD_FAIL_RULES` — 2 kural: `NEGATIVE_EQUITY` (ceiling=25),
    `SEVERE_DEBT_SERVICE_SHORTFALL` (ceiling=35).
  - `CRITICAL_OVERRIDE_RULES` — 5 kural: `current_ratio`/liquidity,
    `debt_to_equity`/leverage, `interest_coverage_ratio`/leverage,
    `net_profit_margin`/profitability, `cash_conversion_cycle`/activity.
- `app/engines/health_score/service.py::compute_financial_health_score(
  ratio_result_json, benchmark_result_json, *, industry_code=None,
  company_size_bucket=None, tenant_id=None) -> HealthScoreResult` — saf
  kütüphane fonksiyonu, sıfır API/adapter/DB.

#### 1.3.1 `HealthScoreResult` — Credit Score'un OKUYACAĞI TAM sözleşme

```python
@dataclass(frozen=True)
class HealthScoreResult:
    status: HealthScoreComputationStatus
    final_score: "Decimal | None"
    pre_hard_fail_score: "Decimal | None"
    letter_rating: "str | None"
    rating_disclaimer_tr: str
    confidence_score: Decimal
    data_coverage_ratio: Decimal
    low_confidence_warning: bool
    provisional: bool
    category_breakdown: "tuple[CategoryBreakdown, ...]"
    hard_fails_triggered: "tuple[str, ...]"
    critical_overrides_applied: "tuple[str, ...]"
    scoreable_ratio_codes: "tuple[str, ...]"
    excluded_duplicate_ratio_codes: "tuple[str, ...]"
    strengths: "tuple[dict[str, Any], ...]"
    weaknesses: "tuple[dict[str, Any], ...]"
    warnings: "tuple[dict[str, Any], ...]"
    health_score_schema_version: str
    health_score_model_version: str
    benchmark_registry_version: str
    ratio_registry_version: str
    category_weight_profile_used: str
```

Credit Score bu sözleşmeyi **BİREBİR OKUR** — ama Bölüm 2/3'te KESİN
olarak kilitlendiği üzere, bu alanlardan HİÇBİRİ Credit Score'un SAYISAL
skoruna GİRMEZ (yalnızca referans/tutarlılık/explainability amaçlı
okunur).

### 1.4 `app/engines/protocol.py` (EngineAdapter sözleşmesi)

`EngineAdapter` Protocol'ü, `EngineRunContext`, `EngineRunResult`. **4.3D
bu protokole HİÇ bağlanmadı** — **4.3E de AYNI ilkeyle bağlanmayacak**
(Bölüm 2 kapsam sınırı).

### 1.5 Yardımcı modüller

- `app/engines/common/company_size_classifier.py::classify_company_size(
  net_sales, total_assets) -> CompanySizeClassification` — `bucket`
  (micro/small/medium/large), `reliability` HİÇBİR ZAMAN `"high"` değil,
  `disclaimer`, `is_official_sme_classification=False`.
- `app/engines/common/reliability.py::RELIABILITY_RANK`/`worse_
  reliability()`.
- `Company` modeli: `sector`/`nace_code` VAR, `country`/şirket ölçeği
  alanı YOK. **`tenant` kavramı platformun HİÇBİR yerinde YOK.**

### 1.6 Test altyapısı ve mevcut koruma mekanizması

- `tests/README.md` — iki katmanlı strateji (SQLite API sözleşmesi +
  gerçek PostgreSQL entegrasyon testleri).
- **`tests/conftest.py`** — 4.3D'nin gerçek Docker doğrulama turunda
  eklenen, artık **commit'li ve doğrulanmış** `autouse=True`
  `_snapshot_shared_engine_registries` fixture'ı: her testten ÖNCE
  `RATIO_REGISTRY`/`BENCHMARK_REGISTRY`/`RATIO_SCORE_WEIGHTS`'in sığ
  kopyasını (lazy, DOĞRU sırayla — `ratio_formulas` → `benchmark_
  registry` → `health_score_registry` — import ederek) alır, test
  bitince `finally` ile BİREBİR geri yükler. **Credit Score'un KENDİ
  registry'leri (Bölüm 24) implementasyon Adım 12'de bu fixture'ın
  snapshot/restore listesine EKLENECEKTİR** — 4.3D'nin gerçek Docker
  turunda yaşanan `_test_*` sızıntı hatasının (RATIO_REGISTRY'ye geçici
  bir kaydın geri alınmaması) 4.3E'de TEKRARLANMAMASI için bu ZORUNLU bir
  implementasyon adımıdır (Bölüm 21, madde 11).

---

## Bölüm 2 — Credit Score Engine Sorumlulukları

Credit Score Engine, bir **bankanın kredi tahsis bakış açısıyla**,
şirketin finansal risk profilini deterministik, açıklanabilir ve resmi
olmayan bir içsel skorla ifade eder. Sorumlulukları:

1. **YALNIZCA üç girdiyi okur** (Bölüm 4): `ratio_result_json`,
   `benchmark_result_json`, `HealthScoreResult`. Ham bilanço/gelir
   tablosu/mizan/belge ayrıştırma katmanına **DOĞRUDAN ERİŞİM YOK**.
2. Bankacılık-lensli KENDİ kategori ağırlıklarını, kritik oran
   override'larını ve hard-fail kurallarını **YALNIZCA `ratio_result_
   json`/`benchmark_result_json` üzerinden** hesaplar (Bölüm 3 — KESİN
   ilke).
3. `HealthScoreResult`'ı **YALNIZCA** referans/tutarlılık/explainability
   amaçlı okur — sayısal skora, kategori ağırlığına veya ratio
   contribution hesabına **KESİNLİKLE KARIŞTIRMAZ** (Bölüm 3).
4. Eksik veri kalemlerini (KKB/Findeks, teminat, ödeme geçmişi, ileri
   dönem nakit akışı) **fabrike etmez** — yapılandırılmış bir "veri
   boşluğu" alanıyla raporlar (Bölüm 19).
5. Her sonucun **"resmî kredi derecelendirmesi değildir"** uyarısını
   taşımasını garanti eder (Bölüm 12).
6. Saf bir kütüphane fonksiyonudur — sıfır API, sıfır adapter, sıfır DB
   persistence, sıfır bulk-upload bağlantısı (Bölüm 2.1).

### 2.1 Kesin kapsam dışı (bu milestone TASARLAMAZ/implemente ETMEZ)

- API YOK, adapter YOK, bulk upload/recompute bağlantısı YOK, DB
  persistence YOK, migration YOK.
- KKB/Findeks entegrasyonu YOK.
- Gerçek teminat/collateral değerleme modeli YOK.
- Belirli bir TRY tutarında kredi limiti/tahsis ÖNERİSİ YOK (Bölüm 13).
- AI/LLM YOK — tüm metinler string template'tir.
- Tenant/industry override AKTİVASYONU YOK (Bölüm 16).
- Çok dönemli trend/momentum skorlaması YOK (Onaylanmış Karar #9).

---

## Bölüm 3 — Health Score ile Credit Score Arasındaki Kesin Fark

Bu, tüm tasarımın en kritik ayrım noktasıdır.

### 3.1 Bakış açısı ve kategori farkları

| Boyut | Financial Health Score (4.3D) | Credit Score (4.3E) |
|---|---|---|
| **Bakış açısı** | Genel finansal "sağlık" — dengeli | Banka kredi tahsis mercei — GERİ ÖDEME KAPASİTESİ odaklı |
| **Kategori ağırlıkları** | Dengeli (leverage %25 en yüksek, growth/efficiency %10'ar) | Borç servisi + kaldıraç AĞIRLIKLI (Bölüm 8 — birlikte %50) |
| **Growth'un rolü** | Pozitif katkı sinyali (%10) | İKİNCİL (%5), borçla finanse büyüme risk İŞARETİ de olabilir (Bölüm 18, `DEBT_FUNDED_GROWTH` bayrağı) |
| **Notlandırma dili** | 6 kademeli SAĞLIK sınıfı | 6 kademeli RİSK sınıfı — KASITLI FARKLI kelime seçimi |
| **Veri kapsamı** | Yalnızca Ratio+Benchmark | Ratio+Benchmark (skor İÇİN) + Health Score (yalnızca referans İÇİN) |

### 3.2 KESİN, BAĞLAYICI hesaplama izolasyon ilkesi (Onaylanmış Karar #3)

**`INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE`** — Credit Score'un
`final_score`'u ve TÜM `CreditCategoryBreakdown` alanları (`raw_score`,
`score_after_override`, `ratio_contributions`), **YALNIZCA** `ratio_
result_json` ve `benchmark_result_json`'ın bir fonksiyonudur.
`health_score_result` parametresi bu hesaplamaya **HİÇBİR** girdi
sağlamaz — matematiksel olarak:

```
final_score = F(ratio_result_json, benchmark_result_json)
# health_score_result BU FONKSİYONUN DEĞİŞKENİ DEĞİLDİR.
```

`HealthScoreResult`, YALNIZCA şu 4 amaçla okunur:

1. **`HealthScoreReference`** (Bölüm 14) — Credit Score sonucuna eklenen,
   salt-okunur bir ÖZET (`health_score_final_score`, `health_score_
   letter_rating`, `health_score_confidence`, `health_score_coverage`,
   `health_score_status`).
2. **Tutarlılık kontrolü** — `health_score_result.ratio_registry_
   version`/`benchmark_registry_version`'ın, Credit Score'a ayrıca
   geçirilen `ratio_result_json`/`benchmark_result_json`'ın KENDİ
   versiyon alanlarıyla UYUŞUP UYUŞMADIĞI (Bölüm 4.3).
3. **Version/status/coverage/confidence KARŞILAŞTIRMASI** — ör.
   `health_score_result.status == INSUFFICIENT_DATA` iken Credit
   Score'un KENDİ coverage'ının farklı olabileceğinin `warnings`'e not
   düşülmesi (Bölüm 11).
4. **Explainability ve warning** — Health Score'un ürettiği `warnings`
   listesinin Credit Score'un KENDİ `warnings`'ine BİRLEŞTİRİLMESİ
   (Bölüm 14).

**Bunun DIŞINDA hiçbir okuma yolu YOKTUR.** Bu, "Health Score değerini
tek başına Credit Score olarak kopyalama" ve "aynı matematiksel sinyali
birden çok kez sayma" ilkelerinin YAPISAL garantisidir — `HealthScoreResult.
category_breakdown`'daki `raw_score`/`ratio_score` değerleri dahi
Credit Score'un KENDİ hesaplamasına ENJEKTE EDİLMEZ; Credit Score kendi
`ratio_score`'unu Bölüm 5/8/9'daki KENDİ tier-interpolasyon + kategori
ağırlıklandırma mantığıyla, `ratio_result_json`/`benchmark_result_json`
üzerinden SIFIRDAN (ama Health Score'un PAYLAŞILAN yardımcı
fonksiyonlarını — `normalize_weights()`, tier interpolasyon stratejisi —
YENİDEN KULLANARAK, kod tekrarı OLMADAN) üretir.

**Zorunlu tasarım invariantı ve property test (Bölüm 21, madde 7'de
detaylandırılmıştır):** Aynı `ratio_result_json`/`benchmark_result_json`
çifti, FARKLI (hatta adversarial/bozuk) `HealthScoreResult` nesneleriyle
çağrıldığında, `compute_credit_score()`'un `final_score`'u ve TÜM
`category_breakdown`'ı **BİT-BİREBİR AYNI** kalmalıdır. Bu, implementasyon
Adım 14'te (property testleri) ZORUNLU bir test olarak yazılacaktır —
"green" olmadan Adım 14 TAMAMLANMIŞ SAYILMAZ.

---

## Bölüm 4 — Girdi ve Çıktı Sözleşmesi

### 4.1 Fonksiyon imzası (Onaylanmış Karar #1)

```python
def compute_credit_score(
    ratio_result_json: dict[str, Any],
    benchmark_result_json: dict[str, Any],
    health_score_result: HealthScoreResult,
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
    tenant_id: "str | None" = None,
) -> CreditScoreResult: ...
```

`health_score_result` parametresi **`HealthScoreResult` dataclass'ı,
DOĞRUDAN** (serileştirilmiş `dict` DEĞİL) — Health Score ile Credit
Score AYNI Python process'inde, AYNI "saf kütüphane" katmanında çalışır;
aralarında bir serileştirme sınırı (network/DB/API) yoktur, dolayısıyla
dataclass'ı olduğu gibi geçirmek hem tip-güvenli hem de gereksiz bir
`to_dict()`/`from_dict()` icadından kaçınır.

### 4.2 `CreditScoreResult`

```python
@dataclass(frozen=True)
class CreditScoreResult:
    status: CreditScoreComputationStatus
    final_score: "Decimal | None"
    pre_hard_fail_score: "Decimal | None"
    risk_tier: "str | None"
    risk_tier_disclaimer_tr: str
    confidence_score: Decimal
    data_coverage_ratio: Decimal
    low_confidence_warning: bool
    provisional: bool
    category_breakdown: "tuple[CreditCategoryBreakdown, ...]"
    hard_fails_triggered: "tuple[str, ...]"
    critical_overrides_applied: "tuple[str, ...]"
    scoreable_ratio_codes: "tuple[str, ...]"
    excluded_duplicate_ratio_codes: "tuple[str, ...]"
    health_score_reference: "HealthScoreReference"
    banking_lens_signals: "BankingLensSignals"
    data_gap_disclosures: "tuple[DataGapDisclosure, ...]"
    strengths: "tuple[dict[str, Any], ...]"
    weaknesses: "tuple[dict[str, Any], ...]"
    warnings: "tuple[dict[str, Any], ...]"
    credit_score_schema_version: str
    credit_score_model_version: str
    health_score_schema_version: str
    health_score_model_version: str
    benchmark_registry_version: str
    ratio_registry_version: str
    category_weight_profile_used: str
```

### 4.3 Girdi doğrulaması

- `ratio_result_json`/`benchmark_result_json`'ın kendi `ratio_registry_
  version`/`benchmark_registry_version` alanları, `health_score_result.
  ratio_registry_version`/`benchmark_registry_version` ile UYUŞMUYORSA,
  `warnings`'e bir `VERSION_MISMATCH_ACROSS_INPUTS` uyarısı EKLENİR — ama
  hesaplama REDDEDİLMEZ (Bölüm 3.2'nin invariantı gereği zaten `health_
  score_result` sayısal sonucu ETKİLEMEZ, bu yalnızca bir KALİTE
  uyarısıdır).
- `health_score_result.status == INSUFFICIENT_DATA` İSE: Credit Score
  KENDİ coverage hesaplamasını (Bölüm 11) YİNE DE `ratio_result_json`/
  `benchmark_result_json` üzerinden BAĞIMSIZ yapar (Bölüm 3.2 invariantı
  — iki motorun scoreable evreni FARKLI olduğu için, Health Score'un
  yetersiz veri durumu Credit Score'u OTOMATİK etkilemez).

---

## Bölüm 5 — Scoreable Sinyal Envanteri ve Kategori Eşlemesi

Credit Score, Ratio/Benchmark Engine'e DOĞRUDAN erişemediği için
scoreable evreni HER ZAMAN `RATIO_REGISTRY` (57) ∩ `BENCHMARK_REGISTRY`
(48)'in bir ALT/YENİDEN AĞIRLIKLANDIRILMIŞ kümesidir; sayılar HER ZAMAN
registry'den TÜRETİLİR (`scoreable_ratio_count`/`excluded_duplicate_
ratio_count` gibi sabitler dokümanda asla elle yazılmaz — yalnızca bu
BÖLÜMDEKİ tablo, o ANKİ registry içeriğinin bir ANLIK GÖRÜNTÜSÜDÜR).

### 5.1 Kategori eşlemesi (Onaylanmış Karar #4 — 6 kategori)

Health Score'un 6 kategorisi (`liquidity`, `leverage`, `profitability`,
`activity`, `efficiency`, `growth`), Credit Score'un bankacılık-lensli 6
kategorisine şu şekilde YENİDEN GRUPLANIR:

| Credit Score kategorisi | Kaynak (Health Score kategorisi/alt-kümesi) | Ağırlık |
|---|---|---|
| Likidite / Ödeme Gücü | `liquidity` (aynen) | %20 |
| Kaldıraç / Sermaye Yapısı | `leverage`'ın SERMAYE YAPISI alt-kümesi (`equity_ratio`, `debt_ratio`, `financial_leverage_multiplier`, `debt_to_equity`, `long_term_debt_to_equity`, `short_term_debt_ratio`) | %25 |
| Borç Servis Kapasitesi | `leverage`'ın BORÇ SERVİSİ alt-kümesi (`interest_coverage_ratio`, `ebitda_coverage_ratio`, `debt_to_ebitda`) | %25 |
| Kârlılık / Geri Ödeme Tamponu | `profitability` (11) + `efficiency` (6) BİRLEŞTİRİLDİ — maliyet-yapısı oranları nihayetinde kârlılığı AÇIKLADIĞI için | %15 |
| Faaliyet / Çalışma Sermayesi | `activity` (aynen) | %10 |
| Büyüme (İKİNCİL) | `growth` (aynen) | %5 |
| *(Nakit Akışı)* | `cash_flow` — yapısal, Cash Flow Engine yok | %0 |

**Toplam: %100.** `leverage`'ın İKİYE bölünmesi (Kaldıraç vs Borç Servis
Kapasitesi) ve `efficiency`'nin `profitability`'ye KATILMASI, Health
Score'un 6 kategorisini Credit Score'un KENDİ 6 kategorisine
DÖNÜŞTÜRÜR — kategori SAYISI aynı kalır (Onaylanmış Karar #4), ama
GRUPLAMA bankacılık mantığına göre YENİDEN yapılır: "ne kadar borçlu"
(stok/bilanço kaldıracı) ile "bu borcu ödeyebiliyor mu" (akış/borç
servisi) AYRI kategorilerdir ve birbirini ortalamada SEYRELTMEZ.

### 5.2 Tam Ratio-Weight Envanteri (Bölüm 24'te registry olarak
implemente edilecek TAM tablo — artık örnek DEĞİL)

Aşağıdaki tablo, `BENCHMARK_REGISTRY`'nin (48 girdi) TAMAMINI, Credit
Score'un 6 kategorisine dağıtılmış ve HER kategoride `ratio_weight`
toplamı TAM `1.00`'e normalize edilmiş olarak listeler. `role` sütunu:
`critical` (kategori override + muhtemel hard-fail tetikleyicisi),
`supporting` (yalnızca kategori ortalamasına katkı), `explainability_
only` (`ratio_weight=0`, duplicate/derived).

**Likidite / Ödeme Gücü (%20 — 5 scored + 1 explainability-only):**

| ratio_code | role | ratio_weight | duplicate_of | critical override | hard-fail |
|---|---|---|---|---|---|
| `current_ratio` | critical | 0.200000 | — | EVET | Hayır |
| `working_capital_ratio` | explainability_only | 0 | `current_ratio` (`identical_formula`) | Hayır | Hayır |
| `quick_ratio` | supporting | 0.200000 | — | Hayır | Hayır |
| `cash_ratio` | supporting | 0.200000 | — | Hayır | Hayır |
| `defensive_interval_ratio` | supporting | 0.200000 | — | Hayır | Hayır |
| `working_capital_to_total_assets` | supporting | 0.200000 | — | Hayır | Hayır |

**Kaldıraç / Sermaye Yapısı (%25 — 3 scored + 3 explainability-only):**

| ratio_code | role | ratio_weight | duplicate_of | critical override | hard-fail |
|---|---|---|---|---|---|
| `equity_ratio` | critical | 0.333333 | — | EVET | **EVET (NEGATIVE_EQUITY)** |
| `debt_ratio` | explainability_only | 0 | `equity_ratio` (`algebraic_complement`, `= 1 - equity_ratio`) | Hayır | Hayır |
| `financial_leverage_multiplier` | explainability_only | 0 | `equity_ratio` (`algebraic_complement`, `= 1/equity_ratio`) | Hayır | Hayır |
| `debt_to_equity` | explainability_only | 0 | `equity_ratio` (`algebraic_complement`, `= (1-equity_ratio)/equity_ratio`) | **Hayır (Onaylanmış Karar #5)** | Hayır |
| `long_term_debt_to_equity` | supporting | 0.333333 | — | Hayır | Hayır |
| `short_term_debt_ratio` | supporting | 0.333334 | — | Hayır | Hayır |

**Borç Servis Kapasitesi (%25 — 3 scored + 0 explainability-only):**

| ratio_code | role | ratio_weight | duplicate_of | critical override | hard-fail |
|---|---|---|---|---|---|
| `interest_coverage_ratio` | critical | 0.333333 | — | EVET | **EVET (SEVERE_DEBT_SERVICE_SHORTFALL)** |
| `ebitda_coverage_ratio` | supporting | 0.333333 | — | Hayır | Hayır |
| `debt_to_ebitda` | supporting | 0.333334 | — | Hayır | Hayır |

**Kârlılık / Geri Ödeme Tamponu (%15 — 17 scored + 0 explainability-only):**

| ratio_code | role | ratio_weight | critical override | hard-fail |
|---|---|---|---|---|
| `net_profit_margin` | critical | 0.058824 | EVET | Hayır |
| `gross_profit_margin` | supporting | 0.058824 | Hayır | Hayır |
| `operating_profit_margin` | supporting | 0.058824 | Hayır | Hayır |
| `ebit_margin` | supporting | 0.058824 | Hayır | Hayır |
| `ebitda_margin` | supporting | 0.058824 | Hayır | Hayır |
| `pretax_profit_margin` | supporting | 0.058824 | Hayır | Hayır |
| `return_on_capital_employed` | supporting | 0.058824 | Hayır | Hayır |
| `effective_tax_rate` | supporting | 0.058824 | Hayır | Hayır |
| `return_on_invested_capital` | supporting | 0.058824 | Hayır | Hayır |
| `return_on_assets` | supporting | 0.058824 | Hayır | Hayır |
| `return_on_equity` | supporting | 0.058824 | Hayır | Hayır |
| `operating_expense_ratio` | supporting | 0.058824 | Hayır | Hayır |
| `cost_of_sales_ratio` | supporting | 0.058824 | Hayır | Hayır |
| `overhead_ratio` | supporting | 0.058824 | Hayır | Hayır |
| `ebit_to_opex` | supporting | 0.058824 | Hayır | Hayır |
| `non_operating_income_dependency` | supporting | 0.058824 | Hayır | Hayır |
| `financing_expense_to_sales` | supporting | 0.058824 | Hayır | Hayır |

(17 × 0.058824 ≈ 1.000008 — kayıt anında `normalize_weights()`'in artık
düzeltmesiyle TAM `1.000000`'a tamamlanır, en büyük ham ağırlıklı
girdiye eklenerek; bu doküman yalnızca yaklaşık ondalık gösterir, gerçek
implementasyon `Decimal` hassasiyetiyle TAM 1'e normalize eder.)

**Faaliyet / Çalışma Sermayesi (%10 — 7 scored + 3 explainability-only):**

| ratio_code | role | ratio_weight (ham) | ratio_weight (normalize) | duplicate_of | critical override |
|---|---|---|---|---|---|
| `cash_conversion_cycle` | critical | 0.5 | 0.076923 | — (`summary_signal_normalized` — DIO+DSO-DPO'nun bileşimi, düşük ağırlık) | EVET |
| `asset_turnover` | supporting | 1 | 0.153846 | — | Hayır |
| `inventory_turnover` | supporting | 1 | 0.153846 | — | Hayır |
| `receivables_turnover` | supporting | 1 | 0.153846 | — | Hayır |
| `fixed_asset_turnover` | supporting | 1 | 0.153846 | — | Hayır |
| `working_capital_turnover` | supporting | 1 | 0.153846 | — | Hayır |
| `days_payables_outstanding` | supporting | 1 | 0.153846 | — | Hayır |
| `payables_turnover` | explainability_only | 0 | 0 | `days_payables_outstanding` (`reciprocal_via_period_constant`) | Hayır |
| `days_inventory_outstanding` | explainability_only | 0 | 0 | `inventory_turnover` (`reciprocal_via_period_constant`) | Hayır |
| `days_sales_outstanding` | explainability_only | 0 | 0 | `receivables_turnover` (`reciprocal_via_period_constant`) | Hayır |

**Büyüme (%5 — 6 scored + 0 explainability-only):**

| ratio_code | role | ratio_weight | critical override | hard-fail |
|---|---|---|---|---|
| `sales_growth` | supporting | 0.166667 | Hayır | Hayır |
| `gross_profit_growth` | supporting | 0.166667 | Hayır | Hayır |
| `ebitda_growth` | supporting | 0.166667 | Hayır | Hayır |
| `net_profit_growth` | supporting | 0.166666 | Hayır | Hayır |
| `total_assets_growth` | supporting | 0.166667 | Hayır | Hayır |
| `equity_growth` | supporting | 0.166666 | Hayır | Hayır |

### 5.3 Konsolide sayım

- **Toplam scoreable (scored) oran: 41** (Likidite 5 + Kaldıraç 3 + Borç
  Servis 3 + Kârlılık 17 + Faaliyet 7 + Büyüme 6).
- **Toplam explainability-only oran: 7** (Likidite 1 + Kaldıraç 3 +
  Faaliyet 3).
- **Toplam: 48** (= `BENCHMARK_REGISTRY` boyutu — TAM eşleşme, hiçbir
  oran kaybolmadı/çift sayılmadı).
- Health Score'un 42/6 dağılımından farkı: **`debt_to_equity`'nin scored'
  dan explainability-only'ye taşınması** (Onaylanmış Karar #5) — bu TEK
  fark, 41/7'ye yol açar (42-1=41 scored, 6+1=7 explainability-only).

---

## Bölüm 6 — Kritik ve Destekleyici Oran Ayrımı

Health Score'un iki-değerli (`ratio_weight>0` scored / `=0`
explainability-only) sınıflandırmasının ÜZERİNE, Credit Score ÜÇÜNCÜ bir
eksen ekler — Bölüm 5.2'deki tabloda HER oran için `role` (`critical` /
`supporting` / `explainability_only`) sütunuyla TAM olarak tanımlanmıştır:

```python
@dataclass(frozen=True)
class CreditRatioScoreWeight:
    ratio_code: str
    category: str
    ratio_weight: Decimal
    role: str                        # "critical" | "supporting" | "explainability_only"
    excluded_as_duplicate_of: "str | None" = None
    duplicate_relationship: "str | None" = None
```

- **`critical`** — kategori ortalamasına katkı verir HEM DE Bölüm 9
  (critical override)/Bölüm 10 (hard-fail) kurallarının TETİKLEYİCİSİ
  olabilir: `current_ratio`, `equity_ratio`, `interest_coverage_ratio`,
  `net_profit_margin`, `cash_conversion_cycle` (5 oran — Bölüm 9'daki 5
  critical override kuralıyla TAM örtüşür).
- **`supporting`** — yalnızca kategori ortalamasına katkı verir, hiçbir
  tavan/hard-fail kuralını TETİKLEMEZ (kalan 36 scored oran).
- **`explainability_only`** — `ratio_weight=0` (7 oran, Bölüm 5.3).

---

## Bölüm 7 — Duplicate / Correlated Signal Politikası

### 7.1 Genel ilke (Health Score'dan miras)

Credit Score, Health Score'un Bölüm 8.1'de kilitlediği duplicate/derived
sınıflandırma MANTIĞINI (dört ilişki türü: `identical_formula`,
`algebraic_complement`, `reciprocal_via_period_constant`, `summary_
signal_normalized`) AYNEN kullanır — sıfırdan yeni bir sınıflandırma
metodolojisi İCAT EDİLMEZ. Ancak Credit Score'un KENDİ registry'si,
Health Score'unkinden **BAĞIMSIZ bir veri yapısıdır** (Bölüm 1.3) ve
KENDİ, bankacılık-lensli gerekçelerle bazı oranları FARKLI
sınıflandırabilir — Bölüm 7.2 tam olarak bunun bir örneğidir.

### 7.2 `equity_ratio` / `debt_to_equity` politikası (Onaylanmış Karar #5)

**Matematiksel gerekçe (standart bilanço denkliği ile KESİN
kanıtlanmıştır):**

```
total_assets = total_liabilities + equity
equity_ratio = equity / total_assets
debt_to_equity = total_liabilities / equity
             = (total_assets - equity) / equity
             = total_assets/equity - 1
             = (1 / equity_ratio) - 1
             = (1 - equity_ratio) / equity_ratio
```

`debt_to_equity`, `equity_ratio`'nun **deterministik, cebirsel bir
dönüşümüdür** (gerçek kod: `app/engines/common/ratio_formulas.py` —
`equity_ratio = equity/total_assets`, `debt_to_equity = total_
liabilities/equity`; ikisi de AYNI iki muhasebe büyüklüğünün (equity,
total_assets/total_liabilities) bir fonksiyonu, ve `total_liabilities =
total_assets - equity` özdeşliği İKİSİNİ TEK bir serbestlik derecesine
indirger). Bu nedenle ikisini AYNI kategoride BAĞIMSIZ scored sinyal
olarak kullanmak, kullanıcının "aynı matematiksel sinyali farklı oran
adlarıyla birden çok kez sayma" ilkesini İHLAL eden bir **duplicate
weighting** yaratır.

**Nihai politika (KESİNLEŞTİ, Bölüm 5.2'de uygulanmıştır):**

- `equity_ratio`: **scored + critical** (Kaldıraç kategorisinin ana
  temsilcisi, hem critical-override hem `NEGATIVE_EQUITY` hard-fail
  tetikleyicisi).
- `debt_to_equity`: **explainability_only** (`excluded_as_duplicate_of
  = "equity_ratio"`, `duplicate_relationship = "algebraic_complement"`)
  — Health Score'da scored olsa da, Credit Score'un KENDİ registry'sinde
  BU politika geçerlidir (Health Score'un kodu DEĞİŞTİRİLMEZ).
- `debt_to_equity`, **hiçbir critical override veya hard-fail kuralını
  TEK BAŞINA tetiklemez** — Bölüm 9/10'daki hiçbir kural `debt_to_
  equity`'yi predicate olarak KULLANMAZ.
- **Kaldıraç çeşitliliği**, `debt_to_equity`'nin YERİNE, GERÇEKTEN farklı
  borç yapısı sinyalleriyle sağlanır: `long_term_debt_to_equity`
  (`long_term_liabilities/equity` — VADE yapısını yakalar, `equity_
  ratio`'dan matematiksel olarak BAĞIMSIZ bir serbestlik derecesi taşır
  çünkü `long_term_liabilities`, `total_liabilities`'in yalnızca bir
  PARÇASIDIR) ve `short_term_debt_ratio` (`short_term_liabilities/
  total_liabilities` — `equity`'yi HİÇ içermeyen, tamamen farklı bir
  oran). Her ikisi de `supporting` rolüyle scored (Bölüm 5.2).

### 7.3 Diğer duplicate ilişkileri

Kalan 6 explainability-only oran (`working_capital_ratio`, `financial_
leverage_multiplier`, `payables_turnover`, `days_inventory_outstanding`,
`days_sales_outstanding` + yukarıdaki `debt_to_equity`), Health Score'un
kilitlediği İLİŞKİLERLE (hedef oran + `duplicate_relationship`)
BİREBİR aynıdır — bunlar YENİDEN tartışılmaz, doğrudan miras alınır.

---

## Bölüm 8 — Kategori Ağırlıkları

Bölüm 5.1'de tam gerekçeli ve KİLİTLENMİŞ:

| Kategori | Ağırlık |
|---|---|
| Kaldıraç / Sermaye Yapısı | %25 |
| Borç Servis Kapasitesi | %25 |
| Likidite / Ödeme Gücü | %20 |
| Kârlılık / Geri Ödeme Tamponu | %15 |
| Faaliyet / Çalışma Sermayesi | %10 |
| Büyüme | %5 |
| Nakit Akışı | %0 (yapısal) |

**Toplam: %100.** Tüm ağırlıklar `provisional=True` ve `credit_score_
model_version`e bağlıdır — değiştiğinde model versiyonu YÜKSELTİLİR
(Bölüm 15).

---

## Bölüm 9 — Kritik Oran Override'ları (Kategori Skoruna ORANSAL ÇARPAN)

**Terminoloji netliği (kesin ayrım):** Bu bölümdeki "critical override",
bir KATEGORİNİN ham skoruna oransal bir çarpan uygular (kategoriler
arası ağırlıklandırmadan ÖNCE, Health Score'un Aşama F'siyle AYNI
konumda). Bu, Bölüm 10'daki "hard-fail ceiling" (FİNAL skora üst sınır
koyan, farklı bir mekanizma) ile KARIŞTIRILMAMALIDIR — ikisi ayrı
kavramlardır, ayrı tetikleyicileri ve ayrı matematiksel etkileri vardır.

```python
CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER: Decimal = Decimal("0.90")
CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER: Decimal = Decimal("0.65")
CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR: Decimal = Decimal("0.50")

combined_multiplier = max(
    math.prod(triggered_multipliers) if triggered_multipliers else Decimal("1"),
    CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR,
)
score_after_override = max(0, min(100, raw_score * combined_multiplier))
```

`critical` tier çarpanı **0.65** (Health Score'un 0.70'inden DAHA SIKI)
— bir bankanın kritik-bantta bir borç-servis/kaldıraç/likidite/kârlılık/
çalışma-sermayesi sinyaline Health Score'dan DAHA AZ tolerans göstermesi
beklenir; kullanıcının "critical ratio breach genel ortalamada
seyrelmemeli" ilkesi bu DAHA AGRESİF çarpanla DAHA GÜÇLÜ karşılanır.

**Onaylanmış v1 kritik oran override listesi (5 kural — Bölüm 5.2/6 ile
TAM tutarlı):**

| ratio_code | kategori | weak → | critical → | gerekçe |
|---|---|---|---|---|
| `current_ratio` | Likidite | ×0.90 | ×0.65 | Temel ödeme gücü sinyali |
| `equity_ratio` | Kaldıraç | ×0.90 | ×0.65 | Sermaye yapısının temel sinyali — HEM override HEM hard-fail (Bölüm 10) tetikleyicisi: hard-fail EKSTREM (negatif) durumu, override ORTA-şiddetli (weak/critical ama henüz negatif olmayan) durumu yakalar |
| `interest_coverage_ratio` | Borç Servis Kapasitesi | ×0.90 | ×0.65 | Borç servisi yetersizliği — Hard Fail Kural 2 ile TAMAMLAYICI |
| `net_profit_margin` | Kârlılık | ×0.90 | ×0.65 | Temel kârlılık sinyali |
| `cash_conversion_cycle` | Faaliyet | ×0.90 | ×0.65 | Çalışma sermayesi/nakit döngüsü sinyali |

**KESİN not:** `debt_to_equity` bu listede YOKTUR ve OLMAYACAKTIR
(Bölüm 7.2) — `role="explainability_only"` bir oranın critical-override
listesinde bulunması registry kayıt-anı validasyonuyla (Health Score'un
`register_ratio_score_weight`'iyle AYNI disiplin) REDDEDİLECEKTİR.

---

## Bölüm 10 — Hard-Fail Kuralları (FİNAL Skora Üst Sınır / Ceiling)

**Terminoloji netliği:** Bu bölümdeki "hard-fail", pipeline'ın EN
SONUNDA (kategoriler arası ağırlıklandırmadan SONRA), `final_score`'a
sert bir ÜST SINIR (ceiling) koyar — Bölüm 9'daki "critical override"
(kategori seviyesinde, oransal çarpan) ile FARKLI bir mekanizmadır. Hard-
fail bir "ikili red" (skor üretmeme) DEĞİLDİR — skor HER ZAMAN üretilir,
yalnızca bir tavanla SINIRLANIR (Onaylanmış Karar #13).

Health Score'un 2 kuralı **TABAN olarak AYNEN korunur, ama Credit Score
için DAHA SIKI tavanlarla:**

| rule_code | predicate | ceiling (Health Score) | ceiling (Credit Score) |
|---|---|---|---|
| `NEGATIVE_EQUITY` | `equity_ratio < 0` | 25 | **15** |
| `SEVERE_DEBT_SERVICE_SHORTFALL` | `interest_coverage_ratio < 0` | 35 | **25** |

Gerekçe: bir banka, negatif özkaynağı veya negatif faiz karşılamayı
Health Score'un "genel sağlık" bakışından DAHA ciddiye alır (bu tür
şirketlere yeni kredi tahsisi tipik olarak İSTİSNAİ/güvence gerektirir).
**Üçüncü, YENİ bir hard-fail kuralı EKLENMEMİŞTİR** — 2 kuralla SINIRLI
kalınarak proliferasyon riski (Bölüm 23) kontrollü tutulur.

**Eksik veri hard-fail olarak YORUMLANMAZ (KESİN):** her iki predicate de
ilgili oran `None`/hesaplanamamışsa `False` döner.

---

## Bölüm 11 — Coverage ve Confidence Politikası

İki seviyeli yeniden dağıtım (kategori-içi + kategoriler arası, Health
Score'un `normalize_weights()` paylaşılan yardımcısı ile AYNI matematik)
ve AYNI 3 coverage bandı:

- `data_coverage_ratio < %50` → `status=INSUFFICIENT_DATA`,
  `final_score=None`, `risk_tier=None`.
- `%50 <= data_coverage_ratio < %70` → skor ÜRETİLİR,
  `low_confidence_warning=True` ZORUNLU.
- `data_coverage_ratio >= %70` → normal.

**Confidence tavanı (Onaylanmış Karar #8):**

```python
CREDIT_PROVISIONAL_CONFIDENCE_CEILING: Decimal = Decimal("0.50")
```

Gerekçe: Credit Score, Health Score'un TÜM belirsizliğini (provisional/
internal_heuristic benchmark'lar) miras alır VE Bölüm 19'da listelenen
EK, YAPISAL veri boşluklarını (KKB/teminat/ödeme geçmişi/ileri nakit
akışı) taşır — bu nedenle "güven" iddiası Health Score'un 0.60'ından
DAHA SIKI bir tavanla (0.50) sınırlanır. **Coverage confidence DEĞİLDİR**
ve `CreditScoreResult`'ta AYRI alanlardır.

---

## Bölüm 12 — Notlandırma Ölçeği

**Puan ölçeği (Onaylanmış Karar #2): 0–100, 1 ondalık.** Health Score
ile TUTARLI; 0–1000 ölçeğinin gerçek kredi bürolarının (KKB/Findeks/
FICO) çağrıştırdığı "istatistiksel kalibrasyon" izlenimini VERMEMEK
için kasıtlı olarak KAÇINILIR.

**Notlandırma dili (Onaylanmış Karar #2): 6 kademeli Türkçe RİSK
kademesi** — AAA/AA/A gibi uluslararası derecelendirme notları
KULLANILMAZ; Health Score'un KENDİ "sağlık sınıfı" dili de TEKRAR
KULLANILMAZ (karıştırılmasın diye kasıtlı farklı kelime seçimi):

| Aralık | Kademe |
|---|---|
| 80 – 100 | Düşük Risk |
| 65 – 79,9 | Sınırlı Risk |
| 50 – 64,9 | İzlenmesi Gereken Risk |
| 35 – 49,9 | Yükselen Risk |
| 20 – 34,9 | Yüksek Risk |
| 0 – 19,9 | Kritik Risk |

Her sonuç, **`risk_tier_disclaimer_tr`** alanıyla şu (marka adı
HARDCODE EDİLMEMİŞ, jenerik) uyarıyı taşır:

```python
CREDIT_RISK_TIER_DISCLAIMER_TR = (
    "Bu sınıflandırma platformun içsel, heuristik bir risk göstergesidir "
    "-- resmî bir kredi derecelendirmesi (KKB/Findeks/uluslararası "
    "derecelendirme kuruluşu notu) DEĞİLDİR ve böyle KULLANILMAMALIDIR."
)
```

---

## Bölüm 13 — Bankacılık Bakış Açısıyla Limitler

**Kesin ilke:** Credit Score, **HİÇBİR ZAMAN belirli bir TRY tutarında
kredi limiti/tahsis tutarı ÖNERMEZ.**

```python
@dataclass(frozen=True)
class BankingLensSignals:
    exposure_sensitivity: str          # "low" | "medium" | "high"
    flags: "tuple[str, ...]"
    not_a_credit_limit_recommendation: bool = True   # HER ZAMAN True, değiştirilemez
    disclaimer_tr: str = (
        "Bu alan bir kredi limiti, tahsis tutarı veya teminat yeterliliği "
        "ÖNERMEZ -- yalnızca hangi risk boyutlarının daha yakından "
        "incelenmesi gerektiğine dair niteliksel işaretlerdir."
    )
```

### 13.1 Deterministik bayrak sözleşmesi (KESİNLEŞTİ — implementasyonda İCAT EDİLMEYECEK)

Her bayrak, ZATEN HESAPLANMIŞ `ratio_result_json`/`benchmark_result_
json` çıktısındaki `tier` alanını (Benchmark Engine'in KENDİ, zaten
onaylı eşiklerini) okur — **YENİ bir sayısal eşik İCAT EDİLMEZ.** Yeterli
veri yoksa (ilgili oran `benchmark_status != "evaluated"`) bayrak
ÜRETİLMEZ; bunun yerine `data_gap_disclosures`'a (Bölüm 19) veya
`warnings`'e bir not düşülür — **eksik veri asla "düşük risk" ya da
"yüksek risk" olarak YORUMLANMAZ.**

| flag_code | kategori/oran | predicate | missing-input davranışı | açıklama şablonu (`text_tr`) | hard-fail/override ilişkisi |
|---|---|---|---|---|---|
| `SHORT_TERM_LIQUIDITY_STRAIN` | Likidite / `current_ratio` | `current_ratio` evaluated VE `tier ∈ {weak, critical}` | evaluated değilse: bayrak YOK, `warnings`'e `"current_ratio değerlendirilemediği için likidite gerilimi işareti üretilemedi"` | `"Kısa vadeli ödeme gücü {tier} bantta (current_ratio)."` | Bilgilendirici — `current_ratio` ZATEN critical-override'da (Bölüm 9), ek bir ceza UYGULANMAZ |
| `HIGH_LEVERAGE` | Kaldıraç / `equity_ratio` | `equity_ratio` evaluated VE `tier ∈ {weak, critical}` | evaluated değilse: bayrak YOK, veri boşluğu notu | `"Sermaye yapısı {tier} bantta (equity_ratio)."` | Bilgilendirici — `equity_ratio` ZATEN critical-override + hard-fail'de (Bölüm 9/10) |
| `DEBT_SERVICE_STRESS` | Borç Servis Kapasitesi / `interest_coverage_ratio` | `interest_coverage_ratio` evaluated VE (`tier ∈ {weak, critical}` VEYA değer `<0`) | evaluated değilse: bayrak YOK | `"Faiz/borç servis karşılama {tier} bantta veya negatif (interest_coverage_ratio)."` | `SEVERE_DEBT_SERVICE_SHORTFALL` hard-fail'i tetiklendiğinde bu bayrak DA BEKLENİR (birlikte görünmesi TUTARLILIK kanıtıdır, test edilir) |
| `WEAK_PROFIT_BUFFER` | Kârlılık / `net_profit_margin` | `net_profit_margin` evaluated VE `tier ∈ {weak, critical}` | evaluated değilse: bayrak YOK | `"Kârlılık tamponu {tier} bantta (net_profit_margin)."` | Bilgilendirici — `net_profit_margin` ZATEN critical-override'da |
| `WORKING_CAPITAL_STRAIN` | Faaliyet / `cash_conversion_cycle` | `cash_conversion_cycle` evaluated VE `tier ∈ {weak, critical}` | evaluated değilse: bayrak YOK (DIO/DSO/DPO bileşenlerinden biri eksikse CCC zaten `not_calculable` olur, doğal olarak yayılır) | `"Çalışma sermayesi/nakit döngüsü {tier} bantta (cash_conversion_cycle)."` | Bilgilendirici — `cash_conversion_cycle` ZATEN critical-override'da |
| `DEBT_FUNDED_GROWTH` | Büyüme + Kaldıraç (ÇAPRAZ) / `total_assets_growth`, `equity_growth` | `total_assets_growth` VE `equity_growth` İKİSİ DE evaluated VE `total_assets_growth > equity_growth` VE `total_assets_growth > 0` | İKİSİNDEN biri evaluated değilse: bayrak YOK, veri boşluğu notu | `"Toplam varlık büyümesi (%{total_assets_growth}) özkaynak büyümesinin (%{equity_growth}) üzerinde -- büyümenin borçla finanse edilmiş olma olasılığı."` | Bilgilendirici — Büyüme kategorisinde HİÇBİR critical-override/hard-fail kuralı YOK, bu bayrak TEK BAŞINA hiçbir sayısal cezaya yol AÇMAZ |

**6 bayrağın TAMAMI** yalnızca `tier`/değer okuma ve basit karşılaştırma
kullanır — hiçbiri implementasyon sırasında YENİDEN yorumlanacak
belirsiz bir "iyi karar" GEREKTİRMEZ.

---

## Bölüm 14 — Explainability Yapısı

`CreditScoreResult` şu alanları ZORUNLU taşır:

- `credit_score_schema_version`, `credit_score_model_version`, `health_
  score_schema_version`, `health_score_model_version`, `ratio_registry_
  version`, `benchmark_registry_version` (Bölüm 15 — 6 eksen).
- `scoreable_ratio_codes`, `excluded_duplicate_ratio_codes` (Bölüm 5.3 —
  41/7).
- Her scored oran için: `ratio_score`, `ratio_weight_applied`, `role`
  (Bölüm 6), `tier_fallback_used`.
- Her kategori için: `raw_score`, `score_after_override`, `redistributed_
  weights`.
- `hard_fails_triggered` (Bölüm 10), `critical_overrides_applied`
  (Bölüm 9) — AYRI alanlar, KARIŞTIRILMAZ.
- `health_score_reference`:

```python
@dataclass(frozen=True)
class HealthScoreReference:
    health_score_final_score: "Decimal | None"
    health_score_letter_rating: "str | None"
    health_score_confidence: Decimal
    health_score_coverage: Decimal
    health_score_status: str
    note_tr: str = (
        "Bu alan yalnızca Financial Health Score'un ÖZETİDİR -- Credit "
        "Score'un kendisi DEĞİLDİR, doğrudan kopyalanmamıştır ve Credit "
        "Score'un final_score hesaplamasına HİÇBİR GİRDİ SAĞLAMAZ "
        "(bkz. Bölüm 3.2 -- INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE)."
    )
```

- `banking_lens_signals` (Bölüm 13), `data_gap_disclosures` (Bölüm 19).
- `final_score`, `confidence_score`, `data_coverage_ratio`, `low_
  confidence_warning`.
- `warnings` (Ratio + Benchmark + Health Score + Credit Score
  seviyelerinin birleşimi).

---

## Bölüm 15 — Model Versiyonlama

Altı BAĞIMSIZ versiyon ekseni:

- `credit_score_schema_version` — `CreditScoreResult`'ın JSON ŞEKLİ
  değiştiğinde yükseltilir.
- `credit_score_model_version` — ağırlık/eşik/hard-fail/override kuralı
  değiştiğinde yükseltilir.
- `health_score_schema_version`, `health_score_model_version` — Health
  Score'dan OLDUĞU GİBİ TAŞINIR.
- `ratio_registry_version`, `benchmark_registry_version` — alt
  motorlardan olduğu gibi taşınır.

Tüm altısı HER `CreditScoreResult`'ta BİRLİKTE saklanır; eski skorlar
versiyon yükseldiğinde YENİDEN HESAPLANMAZ.

---

## Bölüm 16 — Override Mimarisi

Health Score'un Bölüm 8.2'siyle YAPISAL OLARAK AYNI, ama KENDİ, AYRI
sözlüğü:

```python
CREDIT_CATEGORY_WEIGHT_PROFILES: dict[tuple[str, str], CreditCategoryWeightProfile] = {
    ("global", None): CreditCategoryWeightProfile(
        scope="global", scope_key=None,
        category_weights={...},  # Bölüm 8 tablosu
    ),
    # industry/company_size/tenant: BU TURDA HİÇBİR KAYIT EKLENMEZ.
}


def resolve_credit_category_weights(
    *, industry_code=None, company_size_bucket=None, tenant_id=None,
) -> CreditCategoryWeightProfile:
    if tenant_id and (p := CREDIT_CATEGORY_WEIGHT_PROFILES.get(("tenant", tenant_id))):
        return p
    if industry_code and (p := CREDIT_CATEGORY_WEIGHT_PROFILES.get(("industry", industry_code))):
        return p
    if company_size_bucket and (p := CREDIT_CATEGORY_WEIGHT_PROFILES.get(("company_size", company_size_bucket))):
        return p
    return CREDIT_CATEGORY_WEIGHT_PROFILES[("global", None)]
```

Çözümleme sırası: `tenant > industry > company_size > global`. **Yalnızca
`("global", None)` AKTİF** — diğer 3 seviye YALNIZCA veri sözleşmesi/
hook; boş placeholder kod ÜRETİLMEZ; `tenant_id`'nin platformda hiçbir
karşılığı YOK.

---

## Bölüm 17 — Sektör ve Şirket Ölçeği Etkisi

`company_size_classifier.py::classify_company_size()` AYNEN yeniden
kullanılır (kod TEKRARLANMAZ). `Company.sector`/`nace_code` alanları
MEVCUT ama Credit Score'un KENDİSİ bu alanları OKUMAZ (yalnızca ÇAĞIRAN
servis katmanı ileride `industry_code` parametresini bu alanlardan
türetip geçirebilir). v1'de yalnızca HOOK tasarlanır, gerçek sektörel
ayarlama YAPILMAZ (Bölüm 16 ile aynı ilke).

---

## Bölüm 18 — Negatif Özkaynak ve Negatif Kâr Davranışı

### 18.1 Negatif özkaynak

`NEGATIVE_EQUITY` hard-fail kuralı (ceiling=15) + `equity_ratio` critical
override (Bölüm 9/10) — İKİ AYRI mekanizma, İKİ AYRI şiddet seviyesini
yakalar: override "zayıf/kritik ama henüz negatif değil" durumunu,
hard-fail "kesin negatif" durumunu.

### 18.2 Negatif kâr

`net_profit_margin < 0` veya `operating_profit < 0` için AYRI bir
hard-fail kuralı EKLENMEZ (proliferasyon riski, Bölüm 10) — bunun yerine
Bölüm 9'daki `net_profit_margin` critical override'ı üzerinden kategori
seviyesinde CEZALANDIRILIR. Bu, "tek dönem negatif kâr otomatik red" gibi
AŞIRI SERT bir davranışı ÖNLER.

**Çok dönemli zarar trendi**, Onaylanmış Karar #9 (tek dönem, v1) gereği
bu milestone'un kapsamı DIŞINDADIR.

---

## Bölüm 19 — Eksik Nakit Akışı / Teminat / Ödeme Geçmişi Sınırları

Platform BUGÜN şunları HİÇ İÇERMEZ: (1) ileri dönem nakit akışı
projeksiyonu, (2) teminat/collateral verisi, (3) KKB/Findeks ödeme
geçmişi, (4) yönetim kalitesi/covenant uyumu/kefil gücü.

```python
@dataclass(frozen=True)
class DataGapDisclosure:
    gap_code: str          # "FORWARD_CASH_FLOW" | "COLLATERAL" | "PAYMENT_HISTORY" | "MANAGEMENT_QUALITY"
    description_tr: str
    excluded_from_score: bool = True   # HER ZAMAN True


CREDIT_SCORE_DATA_GAPS: tuple[DataGapDisclosure, ...] = (
    DataGapDisclosure(
        gap_code="FORWARD_CASH_FLOW",
        description_tr=(
            "İleri dönem nakit akışı projeksiyonu bu platformda mevcut "
            "değildir -- skor yalnızca geçmiş dönem mali tablolarına "
            "dayanır."
        ),
    ),
    DataGapDisclosure(
        gap_code="COLLATERAL",
        description_tr=(
            "Teminat/collateral verisi mevcut değildir -- skor teminat "
            "yeterliliğini (LTV vb.) HİÇ değerlendirmez."
        ),
    ),
    DataGapDisclosure(
        gap_code="PAYMENT_HISTORY",
        description_tr=(
            "KKB/Findeks gibi bir kredi bürosu ödeme geçmişi entegrasyonu "
            "YOKTUR -- skor, geçmiş ödeme davranışını HİÇ yansıtmaz."
        ),
    ),
    DataGapDisclosure(
        gap_code="MANAGEMENT_QUALITY",
        description_tr=(
            "Yönetim kalitesi, covenant uyumu veya kefil gücü gibi "
            "niteliksel faktörler bu skora DAHİL DEĞİLDİR."
        ),
    ),
)
```

Bu dört kayıt **HER `CreditScoreResult.data_gap_disclosures`'ta SABİT**
olarak bulunur (platformun BUGÜNKÜ YAPISAL sınırı, dönemsel bir "eksik
veri" değil) — bu dört boyut skora HİÇ GİRMEZ (ne 0 ne "iyi" varsayılır),
TAMAMEN dışarıda bırakılır ve AÇIKÇA beyan edilir.

---

## Bölüm 20 — Result JSON Sözleşmesi

`CreditScoreResult`, Health Score'un `HealthScoreResult` deseniyle AYNI
disiplinle bir `@dataclass(frozen=True)`'dır — bu fazda BİR JSON
serileştirme fonksiyonu YAZILMAZ (API/adapter YOK). Gelecekte bir
adapter/API eklenirse, alan isimleri ZATEN `snake_case` ve `Decimal`/
`enum` tipleri, codebase'in mevcut `decimal_to_json_safe()`/`json_safe_
to_decimal()` yardımcılarıyla doğrudan uyumludur. Alt yapılar
(`CreditCategoryBreakdown`, `HealthScoreReference`, `BankingLensSignals`,
`DataGapDisclosure`) hepsi `frozen=True` dataclass'lardır.

---

## Bölüm 21 — Test Stratejisi

1. **Registry doğrulama:** kategori ağırlıklarının (Bölüm 8) toplamının
   1.0 olduğu; her kategorideki `ratio_weight` toplamının (Bölüm 5.2)
   TAM 1.00'e normalize edildiği; `role` sınıflandırmasının Bölüm 5.2/6
   ile TAM eşleştiği (41 scored, 7 explainability-only); critical-
   override `ratio_code`'larının HEPSİNİN `role="critical"` oranlardan
   seçildiği; `debt_to_equity`'nin HİÇBİR critical-override/hard-fail
   kuralında GEÇMEDİĞİNİN registry kayıt-anı validasyonuyla
   REDDEDİLDİĞİ (Bölüm 7.2/9).
2. **Duplicate/correlated signal testleri:** `equity_ratio`/`debt_to_
   equity` cebirsel ilişkisinin (Bölüm 7.2 formülü) GERÇEK ratio
   formülleriyle (sentetik BS verisiyle) sayısal olarak DOĞRULANMASI;
   `long_term_debt_to_equity`/`short_term_debt_ratio`'nun `equity_
   ratio`'dan BAĞIMSIZ (aynı olmayan) bir serbestlik derecesi taşıdığının
   kanıtlanması.
3. **Pipeline sıra/clamp testleri:** her aşama çıktısının `[0,100]`
   dışına ÇIKAMADIĞI; critical override'ın (Bölüm 9) kategori
   seviyesinde, kategoriler arası ağırlıklandırmadan ÖNCE, hard-fail
   ceiling'inin (Bölüm 10) İSE EN SONDA uygulandığı — iki mekanizmanın
   PIPELINE SIRASINDA da AÇIKÇA ayrıştığının testi.
4. **Coverage/confidence bandı testleri:** üç bandın HER BİRİ;
   `CREDIT_PROVISIONAL_CONFIDENCE_CEILING=0.50`'nin gerçekten
   sınırladığı.
5. **Hard-fail testleri:** her iki kuralın (ceiling=15/25) ayrı ayrı VE
   birlikte tetiklendiği senaryolar; eksik veride predicate'lerin
   `False` döndüğü.
6. **Kritik oran override testleri:** Bölüm 9'daki 5 kuralın tek/birden
   fazla aynı kategoride tetiklendiğinde çarpımın DOĞRU hesaplandığı,
   floor'un altına düşmediği.
7. **`INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE` property testi
   (ZORUNLU, Bölüm 3.2):** AYNI `ratio_result_json`/`benchmark_result_
   json` çifti ile EN AZ 5 FARKLI (bazıları bilinçli olarak
   "adversarial" — ör. `final_score=Decimal("0")`, `status=HARD_FAIL_
   CAPPED`, `confidence_score=Decimal("0")` gibi UÇ değerler taşıyan)
   `HealthScoreResult` nesnesi enjekte edilir; `compute_credit_score()`
   çağrılarının `final_score`'unun VE TÜM `category_breakdown`'ının
   BİT-BİREBİR AYNI kaldığı kanıtlanır. **Bu test YEŞİL olmadan Adım 14
   TAMAMLANMIŞ SAYILMAZ.**
8. **`BankingLensSignals`/`DataGapDisclosure` testleri:** Bölüm 13.1'deki
   6 bayrağın HER BİRİNİN predicate'inin doğru çalıştığı; eksik girdide
   bayrak ÜRETİLMEDİĞİ (yalnızca veri-boşluğu/warning); `DEBT_SERVICE_
   STRESS` ile `SEVERE_DEBT_SERVICE_SHORTFALL` hard-fail'inin BİRLİKTE
   göründüğü senaryo; 4 sabit veri boşluğunun HER ZAMAN mevcut olduğu;
   `not_a_credit_limit_recommendation=True`'nun DEĞİŞTİRİLEMEDİĞİ.
9. **Golden senaryolar:** düşük risk (mükemmel şirket), zayıf likidite +
   güçlü kârlılık, negatif özkaynak, negatif faiz karşılama, yüksek
   kaldıraç + zayıf borç servisi BİRLİKTE (Bölüm 5.1'in kategori-ayrımı
   gerekçesini KANITLAYAN senaryo), borçla finanse büyüme (`DEBT_FUNDED_
   GROWTH` bayrağı), düşük coverage, orta coverage, `health_score_
   result.status=INSUFFICIENT_DATA` iken Credit Score'un KENDİ
   coverage'ının FARKLI davranabildiği senaryo.
10. **Property testleri:** determinizm (100 iterasyon bit-birebir aynı
    çıktı), clamp invariantları, monotonluk-garantisi-YOK kabul testi,
    madde 7'deki Health-Score-bağımsızlık invariantı.
11. **Regresyon testleri:** `RATIO_REGISTRY`/`BENCHMARK_REGISTRY`/`RATIO_
    SCORE_WEIGHTS` boyutlarının Credit Score kullanımından ETKİLENMEDİĞİ
    — **VE** implementasyon Adım 12'de, YENİ `CREDIT_RATIO_SCORE_
    WEIGHTS`/`CREDIT_CATEGORY_WEIGHT_PROFILES`/`CREDIT_HARD_FAIL_RULES`/
    `CREDIT_CRITICAL_OVERRIDE_RULES` registry'lerinin `tests/conftest.py`
    'deki `_snapshot_shared_engine_registries` fixture'ının snapshot/
    restore listesine EKLENMESİ ZORUNLUDUR (Bölüm 1.6) — 4.3D'nin gerçek
    Docker turunda yaşanan sızıntı hatasının TEKRARLANMAMASI için.
12. **Performans testleri** (Bölüm 22).

---

## Bölüm 22 — Performans Hedefi

Ölçülmüş referans (4.3D, gerçek Docker doğrulamalı): `analyze_financial_
ratios()` ~0.30ms, `evaluate_benchmarks()` ~0.11ms, `compute_financial_
health_score()` marjinal ek yük ~0.30ms (tam pipeline ~0.66ms).

Credit Score, ÜÇ ZATEN HESAPLANMIŞ sonucu OKUR (Health Score'u DAHİ
yeniden hesaplamaz, yalnızca referans için okur — Bölüm 3.2). **Hedef:
< 0.2ms ek yük, dört motorun (Ratio+Benchmark+Health+Credit) TAM
pipeline'ı < 1.5ms/çağrı.** GERÇEK ölçüm, implementasyonun SON adımında
(Bölüm 25, Adım 16) yapılacaktır.

---

## Bölüm 23 — Risk Analizi

1. **Heuristik/kalibre-edilmemiş ağırlıklar ve eşikler** — `provisional=
   True` ile taşınır; hard-fail ceiling'leri (15/25), critical override
   çarpanı (0.65), confidence tavanı (0.50) hiçbiri GERÇEK banka
   temerrüt verisiyle DOĞRULANMADI.
2. **Bankacılık-lensli kategori taksonomisinin (Bölüm 5.1) bir ÜRÜN
   TERCİHİ olması** — "Kaldıraç" ve "Borç Servis Kapasitesi"nin AYRI
   kategoriler olması GEREKÇELİ bir tercihtir, ama TEK bir "doğru"
   taksonomi YOKTUR.
3. **"Resmî kredi derecelendirmesi" ile karıştırılma riski** — Bölüm 12
   disclaimer'ı ile azaltılır, TAM ORTADAN KALKMAZ.
4. **Sektör/şirket ölçeği kalibrasyonunun TAMAMEN YOK olması** (Bölüm
   17) — bir inşaat şirketiyle bir teknoloji şirketinin AYNI eşiklerle
   değerlendirilmesi gerçek bankacılık pratiğinden SAPAR; v1'de BİLİNÇLİ
   bir sınırlamadır.
5. **Tek dönem sınırlaması** (Bölüm 18.2/Onaylanmış Karar #9) — art arda
   zarar/bozulma trendi YAKALANAMAZ.
6. **Altı versiyon ekseni** (Bölüm 15) — reprodüktibilite karmaşıklığı
   Health Score'dan bile FAZLA.
7. **`BankingLensSignals`'ın niteliksel bayraklarının BİLE yanlış
   yorumlanma riski** — bir kullanıcının bir bayrağı "kredi reddedildi"
   gibi okuma eğilimi olabilir; `not_a_credit_limit_recommendation` ve
   disclaimer'larla azaltılır, TAM ORTADAN KALKMAZ.
8. **Veri boşluklarının (Bölüm 19) "eksik" ile "yapısal olarak hiç yok"
   arasındaki farkın kullanıcılara YETERİNCE net anlatılamaması riski**
   — `DataGapDisclosure.excluded_from_score=True` sabit alanıyla
   azaltılır.
9. **`Health_score_result`'ın Credit Score hesaplamasına HİÇ karışmaması
   ilkesinin (Bölüm 3.2) implementasyon sırasında YANLIŞLIKLA ihlal
   edilme riski** — bu, Bölüm 21 madde 7'deki ZORUNLU property testiyle
   yapısal olarak kontrol edilir, ama bu test YAZILANA kadar (implementasyon
   Adım 14) bu KAĞIT ÜZERİNDE bir garanti olarak kalır.
10. **Hard-fail proliferasyonu** — 2 kuralla KONTROLLÜ tutuluyor.

---

## Bölüm 24 — Dosya ve Klasör Yapısı

```
app/engines/common/credit_score_types.py
    # dataclass'lar (CreditScoreResult, CreditCategoryBreakdown,
    # CreditRatioScoreWeight, CreditHardFailRule, CreditCriticalOverrideRule,
    # HealthScoreReference, BankingLensSignals, DataGapDisclosure),
    # enum'lar (CreditScoreComputationStatus), sabitler.

app/engines/common/credit_score_registry.py
    # CREDIT_RATIO_SCORE_WEIGHTS (Bölüm 5.2'nin TAM tablosu),
    # CREDIT_CATEGORY_WEIGHT_PROFILES (yalnızca global dolu),
    # CREDIT_HARD_FAIL_RULES (2 kural), CREDIT_CRITICAL_OVERRIDE_RULES
    # (5 kural), CREDIT_BANKING_LENS_SIGNAL_RULES (6 kural, Bölüm 13.1).

app/engines/credit_score/__init__.py
    # boş.

app/engines/credit_score/service.py
    # compute_credit_score(...) -> CreditScoreResult.

docs/FINOS_MILESTONE_4_3E_CREDIT_SCORE_ENGINE_DESIGN.md
    # bu doküman.
```

Saf kütüphane, API/adapter/migration YOK — `app/engines/protocol.py`'ye
BAĞLANMAZ.

---

## Bölüm 25 — Alt Adımlara Bölünmüş İmplementasyon Planı

**Her adım tamamen yeşil olmadan sonraki adıma geçilmez.**

1. `credit_score_types.py` — enum'lar, sabitler, dataclass'lar.
2. `credit_score_registry.py` — `CREDIT_RATIO_SCORE_WEIGHTS` (Bölüm 5.2'nin
   TAM tablosu, registry'den türetilmiş), `CREDIT_CATEGORY_WEIGHT_
   PROFILES` (Bölüm 8).
3. Duplicate/correlated signal validasyonu — `equity_ratio`/`debt_to_
   equity` ilişkisinin (Bölüm 7.2) sayısal doğrulaması + 6 diğer
   explainability-only kaydın mirası.
4. Kategori skorlama (Bölüm 8 ağırlıkları + Bölüm 6 `role` ayrımı).
5. Coverage yeniden ağırlıklandırma (Bölüm 11, `normalize_weights()`
   yeniden kullanılarak).
6. Kritik oran override'ları (Bölüm 9, oransal çarpan).
7. Hard-fail kuralları (Bölüm 10, ceiling=15/25).
8. Confidence (Bölüm 11, tavan=0.50).
9. `HealthScoreReference` entegrasyonu (Bölüm 3.2/4 — Health Score'un
   sonucunu YALNIZCA OKUMA, hesaplamaya KARIŞTIRMAMA — bu adımda
   `INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE`'ın kod-seviyesi
   uygulaması netleşir).
10. `BankingLensSignals` (Bölüm 13.1, 6 deterministik bayrak) +
    `DataGapDisclosure` (Bölüm 19, 4 sabit kayıt).
11. Explainability + servis orkestrasyonu (`compute_credit_score()`).
12. Unit testler (Bölüm 21, madde 1-6) — **`tests/conftest.py`'nin
    autouse fixture'ına Credit Score registry'lerinin EKLENMESİ bu
    adımda YAPILIR.**
13. Golden dataset testleri (Bölüm 21, madde 9).
14. Property testleri (Bölüm 21, madde 7/10) — **`INVARIANT: HEALTH_
    SCORE_INPUT_INDEPENDENCE` testi bu adımda YEŞİL olmadan adım
    TAMAMLANMIŞ SAYILMAZ.**
15. Regresyon testleri (Bölüm 21, madde 11).
16. Performans testleri (Bölüm 22).
17. Final rapor (yalnızca sonuç raporu, kod YAZILMAZ).

Her adım sonunda Health Score'un kullandığı EXACT rapor formatı ile
raporlanır: *Değişen dosyalar / Eklenen test sayısı / Geçen test sayısı /
Yeni risk / Production Readiness / Bir sonraki adıma geçilebilir mi.*

---

## Bölüm 26 — Onaylanmış Kararlar

Aşağıdaki 15 karar, kullanıcının 2. tur bağlayıcı talimatıyla
KİLİTLENMİŞTİR. **Açık karar KALMAMIŞTIR.**

1. **`HealthScoreResult` girdi tipi:** doğrudan dataclass (Bölüm 4.1).
2. **Puan ölçeği + notlandırma dili:** 0–100, 1 ondalık, 6 kademeli
   Türkçe RİSK kademesi (Bölüm 12).
3. **Health Score'un rolü:** yalnızca referans/tutarlılık/explainability
   — sayısal skora, kategori ağırlığına, ratio contribution hesabına
   KESİNLİKLE girmez (Bölüm 3.2 — `INVARIANT: HEALTH_SCORE_INPUT_
   INDEPENDENCE`, zorunlu property testle korunur).
4. **Kategori taksonomisi:** 6 kategori, Kaldıraç/Borç Servis Kapasitesi
   ayrımı (Bölüm 5.1).
5. **`equity_ratio`/`debt_to_equity` politikası:** `equity_ratio`
   scored+critical; `debt_to_equity` explainability-only, hiçbir
   critical-override/hard-fail kuralını TEK BAŞINA tetiklemez; kaldıraç
   çeşitliliği `long_term_debt_to_equity`/`short_term_debt_ratio` ile
   sağlanır (Bölüm 7.2).
6. **Critical override çarpanları:** weak=0.90, critical=0.65, kategori
   floor=0.50 (Bölüm 9).
7. **Hard-fail ceiling'leri:** `NEGATIVE_EQUITY`=15, `SEVERE_DEBT_
   SERVICE_SHORTFALL`=25 (Bölüm 10).
8. **Provisional confidence tavanı:** 0.50 (Bölüm 11).
9. **Dönem kapsamı:** v1 tek dönem; çok dönemli trend GELECEĞE
   ertelenir (Bölüm 18.2/23).
10. **Nitel veri mimarisi:** additive hook'lar (`DataGapDisclosure`)
    TASARLANIR, gerçek nitel veri entegrasyonu YAPILMAZ (Bölüm 19).
11. **Override aktivasyonu:** yalnızca `global` ağırlık aktif; tenant/
    industry/company_size yalnızca hook (Bölüm 16).
12. **Ceza modeli:** oransal çarpan (sabit puan cezası DEĞİL, Bölüm 9).
13. **Hard-fail mekanizması:** score ceiling (ikili kabul/red YOK,
    Bölüm 10).
14. **Coverage yeniden dağıtımı:** eksik kategori SIFIR sayılmaz,
    ağırlık orantılı yeniden normalize edilir (Bölüm 11).
15. **Puanlama stratejisi:** sürekli interpolasyon + kontrollü tier
    fallback (Health Score'un Bölüm 6.2 stratejisiyle AYNI, Bölüm 5/9).

---

## Kapsam Dışı Özet (tekrar, netlik için)

API YOK, adapter YOK, migration YOK, DB persistence YOK, bulk upload
bağlantısı YOK, KKB/Findeks entegrasyonu YOK, teminat/collateral modeli
YOK, belirli TRY tutarlı kredi limiti önerisi YOK, AI/LLM YOK, tenant/
industry override AKTİVASYONU YOK, çok dönemli trend/momentum skorlaması
YOK, gerçek Türkiye bankacılık verisiyle kalibrasyon YOK.

## Production Readiness Tahmini

**Tasarım aşamasında Production Readiness: %90** — 15 kararın TAMAMI
kilitlendi, Bölüm 5.2'de HER scoreable/explainability-only oran için
TAM (örnek değil) bir registry tablosu üretildi, terminoloji (critical
override vs hard-fail ceiling) netleşti, `BankingLensSignals`'ın 6
bayrağı deterministik olarak tanımlandı. Kalan %10, DOĞAL olarak
implementasyon sırasında ortaya çıkabilecek (Bölüm 23'te listelenen)
kalibrasyon/gerçek-kod detaylarına aittir — **henüz hiçbir kod
yazılmadığı için işlevsel Production Readiness hâlâ %0'dır**, bu %90
yalnızca "implementasyona hazır TASARIM" anlamında okunmalıdır.

## İmplementasyona Hazır mı?

**Evet — tasarım açısından hazır.** 15 kararın tamamı kilitlendi, açık
karar kalmadı. Kullanıcının ayrı, açık bir "başla" talimatı ile
implementasyon (Bölüm 25'teki 17 adım) başlayabilir.

## Revizyon Raporu

- **Kapatılan karar sayısı:** 15/15 (Bölüm 26, açık karar KALMADI).
- **Scoreable (scored) oran sayısı:** 41.
- **Explainability-only oran sayısı:** 7.
- **Kategori dağılımı:** Likidite (5 scored/1 excl, %20), Kaldıraç (3
  scored/3 excl, %25), Borç Servis Kapasitesi (3 scored/0 excl, %25),
  Kârlılık (17 scored/0 excl, %15), Faaliyet (7 scored/3 excl, %10),
  Büyüme (6 scored/0 excl, %5).
- **Hard-fail kural sayısı:** 2 (`NEGATIVE_EQUITY`=15, `SEVERE_DEBT_
  SERVICE_SHORTFALL`=25).
- **Critical override kural sayısı:** 5 (`current_ratio`, `equity_
  ratio`, `interest_coverage_ratio`, `net_profit_margin`, `cash_
  conversion_cycle`).
- **`BankingLensSignals` kural sayısı:** 6 (`SHORT_TERM_LIQUIDITY_
  STRAIN`, `HIGH_LEVERAGE`, `DEBT_SERVICE_STRESS`, `WEAK_PROFIT_BUFFER`,
  `WORKING_CAPITAL_STRAIN`, `DEBT_FUNDED_GROWTH`).
- **Production Readiness:** %90 (tasarım hazırlığı; kod henüz %0).
- **İmplementasyona hazır mı:** Evet, tasarım kilitlendi — kullanıcının
  ayrı "başla" talimatı bekleniyor.
- **Git status:** yalnızca bu doküman değişti (kod/test/migration
  DOKUNULMADI, commit/push YAPILMADI).

## Onay Bekleniyor

Bu doküman yalnızca REVİZE EDİLDİ ve tekrar onay bekliyor. Kodlamaya
BAŞLANMADI. Kullanıcının açık, ayrı bir "başla" talimatı olmadan
implementasyon (Bölüm 25) başlamayacaktır.
