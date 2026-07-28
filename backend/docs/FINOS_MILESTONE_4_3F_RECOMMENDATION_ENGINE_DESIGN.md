# FINOS Milestone 4.3F — Recommendation Engine Teknik Tasarım Dokümanı

**DURUM: YALNIZCA TASARIM — HENÜZ ONAY BEKLİYOR. HİÇBİR KOD/TEST/MIGRATION/
API/ADAPTER YAZILMADI, HİÇBİR DOSYA DEĞİŞTİRİLMEDİ.**

Bu doküman, kullanıcının açık ve ayrı "başla" talimatı olmadan
implementasyona KESİNLİKLE geçilmeyeceği bağlayıcı kısıtıyla
hazırlanmıştır. 4.3D (Financial Health Score) ve 4.3E (Credit Score
Engine) tasarım dokümanlarıyla AYNI ayrıntı seviyesinde, AYNI mimari
disiplinle yazılmıştır.

---

## 1. Mevcut Sistem İncelemesi

Recommendation Engine'in üzerine kurulacağı dört motorun TAM mimarisi bu
turda yeniden incelendi. Aşağıdaki envanter, doğrudan mevcut kaynak
koddan (dosya okumalarıyla) çıkarılmıştır — varsayım YOKTUR.

### 1.1 Financial Ratio Engine (4.3A/4.3B)

- `app/engines/common/ratio_formulas.py` — `RATIO_REGISTRY: dict[str,
  RatioFormulaMetadata]`, **57 oran**, `RATIO_REGISTRY_VERSION="1.1.0"`.
- `RatioFormulaMetadata` alanları: `key`, `category` (7 native kategori:
  `liquidity`/`leverage`/`profitability`/`activity`/`efficiency`/
  `growth`/`cash_flow`), `display_name_tr`, `unit`
  (`"ratio"`/`"percentage"`/`"days"`/`"currency"`),
  `calculation_strategy` (kapalı küme: `sum_division`/
  `linear_combination`/`growth_rate`/`scaled_division`, eval/exec YOK),
  `numerator_fields`/`denominator_fields`/`addend_fields`/
  `subtrahend_fields`, `zero_denominator_status`, `quantize_exp`,
  `depends_on_ratios`, `current_field`/`prior_field`, `scale_field`,
  `engine_dependency`, `direct_document_only_fields`.
- `ComputationStatus` (6 değer): `CALCULATED`/`MISSING_INPUT`/
  `UNDEFINED_ZERO_DENOMINATOR`/`NO_OBLIGATION`/`NOT_APPLICABLE`/
  `NOT_CALCULABLE` — eksik veri (`None`) ile gerçek sıfır payda KESİNLİKLE
  ayrıştırılır, hiçbir hesaplama `Infinity`/`NaN` üretmez.
- `ComputationOutcome`: `status`, `value`, `missing_inputs`, `warnings`,
  `reliability`, `provenance` HER ZAMAN birlikte üretilir.
- `analyze_financial_ratios()` (`app/engines/financial_ratios/service.py`)
  çıktısı: `{"engine", "engine_version", "ratio_registry_version",
  "categories": {cat: {"status", "ratios": {ratio_key: {"value",
  "status", "reliability", "warnings", "provenance"}}}}, "warnings": [...]}`.
  Bu yapı, Benchmark/Health Score/Credit Score motorlarının HEPSİNİN
  ORTAK girdi sözleşmesidir — Recommendation Engine de AYNI yapıyı
  SADECE OKUYACAKTIR.

### 1.2 Benchmark Engine (4.3C)

- `app/engines/common/benchmark_types.py` — `BENCHMARK_REGISTRY: dict[str,
  BenchmarkMetadata]`, **48 benchmark**, `BENCHMARK_REGISTRY_VERSION=
  "1.0.0"`. `benchmark_code == ratio_code` (Bölüm 7 kararı) — bu yüzden
  `ratio_key -> benchmark` eşlemesi DOĞRUDANDIR.
- `BenchmarkIdealDirection`: `HIGHER_IS_BETTER`/`LOWER_IS_BETTER`/
  `RANGE_IS_BETTER` (iç içe bantlar, ör. `current_ratio`).
- `BenchmarkThresholds`: `excellent`/`good`/`average`/`weak`/`critical`/
  `warning_threshold` — tek skaler VEYA `(min,max)` demeti.
- `evaluate_benchmarks()` (`app/engines/benchmarks/service.py`) çıktısı:
  `{"engine", "engine_version", "benchmark_registry_version",
  "ratio_registry_version", "industry_code", "company_size_bucket",
  "categories": {cat: {"ratios": {ratio_key: {"status", "tier",
  "reliability", "warning_flag", "underlying_ratio_status",
  "resolved_scope", "provisional", "inflation_adjusted",
  "warnings"}}}}}`. `tier` 5 değerli: `excellent/good/average/weak/
  critical` — Health Score/Credit Score/Recommendation Engine'in ORTAK
  "iyilik" dilidir.
- `BenchmarkComputationStatus`: `EVALUATED`/`RATIO_STATUS_NOT_CALCULATED`/
  `BENCHMARK_NOT_REGISTERED`/(rezerve: `PERCENTILE_DATA_UNAVAILABLE`/
  `STALE_BENCHMARK_DATA`).

### 1.3 Financial Health Score Engine (4.3D)

- `app/engines/common/health_score_types.py` +
  `app/engines/common/health_score_registry.py` +
  `app/engines/health_score/service.py`.
- Native 7 kategoriden **6'sı aktif** (`cash_flow` yapısal %0):
  `liquidity`(0.20)/`leverage`(0.25)/`profitability`(0.20)/
  `activity`(0.15)/`efficiency`(0.10)/`growth`(0.10).
- `RATIO_SCORE_WEIGHTS`: 48 girdi (42 scored + 6 duplicate/
  explainability-only).
- `HARD_FAIL_RULES` (2): `NEGATIVE_EQUITY` (ceiling=**25**),
  `SEVERE_DEBT_SERVICE_SHORTFALL` (ceiling=**35**).
- `CRITICAL_OVERRIDE_RULES` (5): `current_ratio`(liquidity),
  `debt_to_equity`(leverage), `interest_coverage_ratio`(leverage),
  `net_profit_margin`(profitability), `cash_conversion_cycle`(activity)
  — weak=0.90/critical=0.70 çarpan, kategori taban=0.50.
- Coverage üç bant: `<0.50` → `INSUFFICIENT_DATA` (final_score=None),
  `[0.50,0.70)` → `low_confidence_warning=True`, `>=0.70` → normal.
  Confidence tavanı **0.60**.
- `HealthScoreResult` (nihai sonuç dataclass'ı) alan alan:
  `status`(`HealthScoreComputationStatus`: `COMPUTED`/
  `HARD_FAIL_CAPPED`/`INSUFFICIENT_DATA`), `final_score`(`Decimal|None`,
  0-100 1 ondalık), `pre_hard_fail_score`, `letter_rating`(`str|None`,
  6 kademeli TR "sağlık sınıfı" dili: Çok Güçlü/Güçlü/Sağlıklı/
  İzlenmeli/Zayıf/Kritik), `rating_disclaimer_tr`, `confidence_score`,
  `data_coverage_ratio`, `low_confidence_warning`, `provisional`,
  `category_breakdown`(`tuple[CategoryBreakdown,...]`),
  `hard_fails_triggered`(`tuple[str,...]`),
  `critical_overrides_applied`(`tuple[str,...]`),
  `scoreable_ratio_codes`, `excluded_duplicate_ratio_codes`,
  `strengths`/`weaknesses`(`tuple[dict[str,Any],...]` — `ratio_code`/
  `category`/`tier`/`ratio_score`/`display_name_tr`/`text_tr`),
  `warnings`, `health_score_schema_version`, `health_score_model_
  version`, `benchmark_registry_version`, `ratio_registry_version`,
  `category_weight_profile_used`.
- `CategoryBreakdown`: `category`, `raw_score`, `score_after_override`,
  `weight_applied`, `coverage_ratio`, `redistributed_weights`,
  `critical_overrides_applied`, `ratio_contributions`(`tuple[
  RatioContribution,...]`).
- `RatioContribution`: `ratio_code`, `benchmark_status`, `tier`,
  `ratio_score`, `ratio_weight_applied`, `tier_fallback_used`,
  `reliability`, `is_duplicate_excluded`.
- Paylaşılan yardımcılar (`health_score_types.py`'de tanımlı, HEM Credit
  Score HEM ileride Recommendation Engine tarafından YENİDEN
  KULLANILACAK): `normalize_weights()`, `clamp_score()`,
  `TIER_TO_POINTS`, `HealthScoreTier`, `CONFIDENCE_RELIABILITY_WEIGHT`,
  `STRENGTHS_WEAKNESSES_COUNT=5`.

### 1.4 Credit Score Engine (4.3E) — en yeni, en yakın emsal

- `app/engines/common/credit_score_types.py` +
  `app/engines/common/credit_score_registry.py` +
  `app/engines/credit_score/service.py`.
- **KENDİ, Health Score'dan FARKLI 6-kategorili taksonomi** (bankacılık
  lensli): `liquidity`(0.20)/`leverage`(0.25, yalnızca sermaye yapısı)/
  `debt_service_capacity`(0.25, YENİ — Health Score'un `leverage`'ının
  borç-servisi alt kümesi AYRILDI)/`profitability`(0.15, Health Score'un
  `profitability`+`efficiency` BİRLEŞİMİ)/`activity`(0.10)/`growth`
  (0.05). **Bu, Recommendation Engine'in KENDİ taksonomisini
  tasarlarken doğrudan emsal aldığı KANITLANMIŞ bir desendir: "downstream
  motor, upstream'in kategorilerini birebir MİRAS ALMAK ZORUNDA
  DEĞİLDİR — aksiyona/amaca göre YENİDEN GRUPLAYABİLİR."**
- `CreditRatioScoreWeight.role`: `"critical"`/`"supporting"`/
  `"explainability_only"` — YENİ bir üçlü eksen (Health Score'un ikili
  scored/excluded ayrımından daha zengin).
- `CreditHardFailRule` ceiling'leri Health Score'dan FARKLI (Credit Score
  KENDİ, daha sıkı model sabitleri kullanır — `NEGATIVE_EQUITY`=15,
  `SEVERE_DEBT_SERVICE_SHORTFALL`=25) — **"aynı SAYISAL değer bile olsa,
  her motor KENDİ, bağımsız versiyonlanan model sabitini tanımlar"**
  ilkesinin kanıtlı emsali.
- **`INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE`**: Credit Score'un
  SAYISAL hesaplaması `HealthScoreResult`'a HİÇ bağlı DEĞİLDİR —
  `HealthScoreReference` yalnızca salt-okunur özet/tutarlılık amaçlıdır.
  **Bu invariant Recommendation Engine'e DOĞRUDAN taşınmaz** (bkz. Bölüm
  3/4) — Recommendation Engine'in amacı zaten Health/Credit Score'un
  SONUÇLARINI okuyup aksiyon üretmektir, bu yüzden onlara "bağımlı
  olmama" DEĞİL, "onları asla YENİDEN HESAPLAMAMA/MUTASYONA
  UĞRATMAMA" farklı bir salt-okunurluk invariantı geçerlidir (Bölüm 12).
- `BankingLensSignalRule` (6 deterministik bayrak):
  `SHORT_TERM_LIQUIDITY_STRAIN`/`HIGH_LEVERAGE`/`DEBT_SERVICE_STRESS`/
  `WEAK_PROFIT_BUFFER`/`WORKING_CAPITAL_STRAIN`/`DEBT_FUNDED_GROWTH` —
  `predicate(signals) -> bool|None` (`None`=yetersiz veri, bayrak YOK).
  `BankingLensSignals.not_a_credit_limit_recommendation=True` HER ZAMAN
  — Recommendation Engine'in Banking katmanı (Bölüm 26) bu KURALI
  BİREBİR MİRAS ALIR.
- `DataGapDisclosure` (4 sabit): `FORWARD_CASH_FLOW`/`COLLATERAL`/
  `PAYMENT_HISTORY`/`MANAGEMENT_QUALITY`, `excluded_from_score=True` HER
  ZAMAN.
- `CreditScoreResult` alan alan: `status`(`CreditScoreComputationStatus`),
  `final_score`, `pre_hard_fail_score`, `risk_tier`(`str|None`, 6
  kademeli TR RİSK dili — Health Score'un "sağlık sınıfı" dilinden
  KASITLI FARKLI kelime seçimi: Düşük Risk/Sınırlı Risk/İzlenmesi
  Gereken Risk/Yükselen Risk/Yüksek Risk/Kritik Risk),
  `risk_tier_disclaimer_tr`, `confidence_score`(tavan **0.50** — Health
  Score'dan DAHA SIKI), `data_coverage_ratio`, `low_confidence_warning`,
  `provisional`, `category_breakdown`, `hard_fails_triggered`,
  `critical_overrides_applied`, `scoreable_ratio_codes`,
  `excluded_duplicate_ratio_codes`, `health_score_reference`
  (`HealthScoreReference` — salt özet), `banking_lens_signals`,
  `data_gap_disclosures`, `strengths`, `weaknesses`, `warnings`, 6
  versiyon alanı, `category_weight_profile_used`.
- Paylaşılan kod disiplini KANITLANMIŞ ÖRNEK: `credit_score_types.py`
  `clamp_score`/`normalize_weights`/`TIER_TO_POINTS`/`HealthScoreTier`/
  `CONFIDENCE_RELIABILITY_WEIGHT`'i `health_score_types.py`'den DOĞRUDAN
  import eder, YENİDEN TANIMLAMAZ. `credit_score/service.py`, tier
  interpolasyonunu (`compute_ratio_score` ve iç yardımcıları) ile
  sinyal-toplamayı (`collect_ratio_signals`) `health_score/service.py`'den
  DOĞRUDAN import edip YENİDEN KULLANIR.

### 1.5 `protocol.py` — motorun EngineAdapter'dan bağımsızlığının kanıtı

`app/engines/protocol.py` (`EngineSourceRef`/`EngineRunContext`/
`EngineRunResult`/`EngineAdapter`) — Health Score VE Credit Score
paketlerinin HİÇBİRİ bu dosyaya BAĞLI DEĞİLDİR, HİÇBİR
`ClassVar[AnalysisType]`/`run()` implementasyonu YOKTUR. Bu dosya
4.3D/4.3E boyunca HİÇ değiştirilmedi — **Recommendation Engine de AYNI
şekilde bu dosyaya DOKUNMAYACAK, `EngineAdapter` sözleşmesini
İMPLEMENTE ETMEYECEK.**

### 1.6 `tests/conftest.py` — paylaşılan registry koruma disiplini

Autouse `_snapshot_shared_engine_registries` fixture'ı, ŞU AN
`RATIO_REGISTRY`/`BENCHMARK_REGISTRY`/`RATIO_SCORE_WEIGHTS`/
`CREDIT_RATIO_SCORE_WEIGHTS`/`CREDIT_CATEGORY_WEIGHT_PROFILES`/
`CREDIT_HARD_FAIL_RULES`/`CREDIT_CRITICAL_OVERRIDE_RULES`/
`CREDIT_BANKING_LENS_SIGNAL_RULES`'i LAZY, DOĞRU sıralı importlarla
snapshot/restore ediyor. **Recommendation Engine implementasyona
geçtiğinde bu fixture, KENDİ yeni registry'lerini (Bölüm 8) de AYNI
disiplinle kapsayacak şekilde GENİŞLETİLECEKTİR** — bu, önceki iki
gerçek-Docker hatasının (import sırası + registry sızıntısı) KESİN
önleyici tedbiridir, şimdiden kayıt altına alınıyor.

**REVİZYON NOTU (mimari denetim sonrası — Madde 9, ZORUNLU düzeltme):**
Denetim raporu, import sırasının ve container tiplerinin İMA EDİLDİĞİNİ
(açıkça yazılmadığını) tespit etmişti — geçmişteki İKİ gerçek hatanın
kök nedeni tam olarak buydu. Bu revizyon her ikisini de AÇIKÇA, bağlayıcı
bir kural olarak yazar:

**Zorunlu import sırası (genişletilmiş zincir):**

```
app.engines.common.ratio_formulas
  -> app.engines.common.benchmark_registry
  -> app.engines.common.benchmark_types
  -> app.engines.common.health_score_registry
  -> app.engines.common.credit_score_registry
  -> app.engines.common.recommendation_registry   # YENİ, HER ZAMAN EN SON
```

`recommendation_registry.py`, `health_score_registry`/`credit_score_
registry`'den YALNIZCA doğrulama amaçlı (Bölüm 8.2 madde 8 — `hard_
fail_code`/`banking_lens_flag` katalog kontrolü) import yapar; bu import
TEK YÖNLÜDÜR, `health_score_registry`/`credit_score_registry` GERİYE
DOĞRU `recommendation_registry`'yi ASLA import ETMEZ (döngüsel import
riski YAPISAL olarak yoktur).

**Container tipleri ve restore stratejisi (`tests/conftest.py`
fixture'ının genişletilmiş hali, LIFO sırayla restore):**

| Registry | Container tipi | Restore stratejisi |
|---|---|---|
| `RECOMMENDATION_RULES` | `tuple[RecommendationRule, ...]` (immutable) | referans yeniden atama |
| `RECOMMENDATION_CONFLICT_PAIRS` | `tuple[tuple[str, str], ...]` (immutable) | referans yeniden atama |
| `RECOMMENDATION_CATEGORY_WEIGHT_PROFILES` | `dict[...]` (mutable) | `clear()` + `update()` |
| `BANKING_FLAG_TO_RATIO_OVERLAP` | `dict[str, tuple[str, ...]]` (mutable) | `clear()` + `update()` — iç değerler (tuple) zaten immutable, SIĞ kopya YETERLİDİR |

Fixture'ın snapshot AŞAMASI import sırasıyla AYNI sırada (yukarıdaki
zincir), restore AŞAMASI ise `finally` bloğunda TERS sırada (LIFO)
çalışır — bu, mevcut 8 registry için ZATEN kullanılan desenin
Recommendation Engine'in 4 yeni registry'sine BİREBİR uzantısıdır,
YENİ bir desen İCAT EDİLMEMİŞTİR. Test dosyalarında geçici registry
mutasyonu yapan HERHANGİ bir test, `try/finally` İLE kendi eklediğini
GERİ ALMALIDIR — autouse fixture TEK BAŞINA (yalnızca test'ler ARASI
sızıntıya karşı) bir güvencedir, TEK BİR testin kendi İÇİNDEKİ
best-practice temizliğin YERİNE GEÇMEZ.

---

## 2. Recommendation Engine Sorumlulukları

Recommendation Engine, mevcut dört motorun **SONUÇLARINI okuyup**,
kullanıcıya somut, açıklanabilir, deterministik **finansal aksiyon
önerileri** üretir. Sorumlulukları:

1. `ratio_result_json` + `benchmark_result_json` + `HealthScoreResult`
   + `CreditScoreResult`'ı **SALT-OKUNUR** girdi olarak alır.
2. Her bir zayıf/kritik sinyali (tier=weak/critical, hard-fail,
   critical-override, BankingLensSignal bayrağı), KENDİ registry'sindeki
   (Bölüm 8) deterministik kurallarla eşleştirip somut bir
   `RecommendationItem` üretir.
3. Önerileri önceliklendirir (Bölüm 9), etki/zorluk bantlarıyla
   etiketler (Bölüm 10/11), çakışan/yinelenen önerileri yönetir (Bölüm
   13/14).
4. Her öneri için TAM açıklanabilirlik sağlar (Bölüm 15) — hangi
   oran/tier/motor sonucu tetikledi, neden bu öncelik.
5. Hiçbir zaman resmî mali/hukuki danışmanlık yerine geçmediğini
   belirten bir uyarı taşır (Bölüm 15/34).
6. Saf bir kütüphane fonksiyonudur — sıfır API, sıfır adapter, sıfır DB
   persistence, sıfır bulk-upload bağlantısı (Bölüm 2.1 ile AYNI
   disiplin).

### 2.1 Kesin kapsam dışı (bu milestone TASARLAMAZ/implemente ETMEZ)

1. **Hiçbir oranı yeniden hesaplamaz** — `analyze_financial_ratios()`'ı
   HİÇ ÇAĞIRMAZ.
2. **Hiçbir benchmark üretmez** — `evaluate_benchmarks()`'ı HİÇ
   ÇAĞIRMAZ.
3. **Hiçbir score üretmez** — `compute_financial_health_score()`/
   `compute_credit_score()`'u HİÇ ÇAĞIRMAZ.
4. **Sayısal What-if/simülasyon YOK** (v1) — bkz. Bölüm 19'un kesin
   gerekçesi; yalnızca YÖNSEL (directional) eşik-mesafesi bilgisi
   verilir, YENİ bir skor asla FABRİKE EDİLMEZ.
5. Hiçbir API/router/schema/adapter/migration eklenmez.
6. `app/services/bulk_upload.py`'a bağlanmaz.
7. `app/trial_balance/**`'e dokunmaz.
8. `app/engines/protocol.py`'a dokunmaz, `EngineAdapter` implemente
   etmez.
9. KKB/Findeks/teminat/ödeme geçmişi/yönetim kalitesi gibi platformda
   YAPISAL OLARAK OLMAYAN verilerin KENDİSİNE dair bir DEĞERLENDİRME
   (ör. "teminat durumunuz zayıf/güçlü") ÜRETMEZ (Credit Score'un
   `DataGapDisclosure`'ının BİREBİR mirası). **Netleştirme (son onay
   turu, Madde 3/8):** Bölüm 20a'nın `DQ_ADDRESS_*` kuralları (36-39)
   bu ilkeyi İHLAL ETMEZ — onlar veri EKSİKLİĞİNİN kendisini (bir OLGU
   olarak) raporlar, eksik olan veri HAKKINDA bir DEĞERLENDİRME/tahmin
   ÜRETMEZ (ör. "teminat verinizi ekleyin" der, "teminatınız
   yetersizdir" DEMEZ).
10. Belirli bir TRY tutarında kredi limiti/tahsis önerisi VERMEZ (Bölüm
    20a'nın BANKING_READINESS kuralları, Credit Score'un
    `BankingLensSignals.not_a_credit_limit_recommendation=True`
    kuralının mirası).
11. Metin üretimi için AI/LLM KULLANMAZ — TÜM `title_tr`/`action_tr`/
    `rationale_tr` metinleri, registry'de SABİT, deterministik Türkçe
    string'lerdir (parametrik `{tier}`/`{ratio_value}` yer tutucularıyla,
    BankingLensSignalRule'ın `text_template_tr` desenindeki AYNI
    disiplin).
12. Production-facing sabit metinlerde hardcode marka adı YOK (Health
    Score'un `RATING_DISCLAIMER_TR`/Credit Score'un `CREDIT_RISK_TIER_
    DISCLAIMER_TR`'siyle AYNI jenerik "platformun içsel..." kalıbı).
13. Tenant/industry/company_size override'ları YALNIZCA hook (çözümleme
    SIRASI) olarak tasarlanır/implemente edilir — gerçek veri
    KAYDEDİLMEZ (Bölüm 17, Health/Credit Score'la AYNI desen).
14. Commit/push YAPILMAZ.

---

## 3. Financial Health Score ile İlişkisi

Recommendation Engine, `HealthScoreResult`'ı **DOĞRUDAN bir tetikleyici
sinyal kaynağı** olarak okur (Credit Score'un aksine — Credit Score
Health Score'u yalnızca REFERANS için okurken, Recommendation Engine'in
VAROLUŞ SEBEBİ zaten "skorları okuyup aksiyona çevirmek"tir, bu yüzden
bağımlılık BEKLENEN ve GEREKLİDİR):

- `health_score_result.hard_fails_triggered` → `CRITICAL` öncelikli
  öneri tetikleyicisi (Bölüm 9).
- `health_score_result.critical_overrides_applied` → `HIGH` öncelikli
  öneri tetikleyicisi.
- `health_score_result.category_breakdown[*].ratio_contributions[*]`
  içindeki `tier="weak"`/`"critical"` olan, `is_duplicate_excluded=False`
  katkılar → kategoriye özgü öneri kuralı (Bölüm 20-25) tetikleyicisi.
- `health_score_result.status==INSUFFICIENT_DATA` iken, Health
  Score'dan türeyen öneriler için `category_breakdown` YİNE DE dönmüş
  olabilir (Health Score'un kendi tasarımı gereği teşhis amaçlı kırılım
  her zaman döner) — Recommendation Engine bu durumda dahi KENDİ
  coverage hesaplamasını (Bölüm 12) YAPAR, Health Score'un
  `INSUFFICIENT_DATA` durumunu OLDUĞU GİBİ KOPYALAMAZ.
- `health_score_result.strengths`/`weaknesses` → v1'de DOĞRUDAN
  KULLANILMAZ (Bölüm 7 kararı: Recommendation Engine KENDİ tetikleme
  mantığını `category_breakdown`'ın ham `ratio_contributions`'ından
  üretir; `strengths`/`weaknesses` zaten UI'da AYRICA gösterilen bir
  alan olduğu için mükerrer bir "closing the loop" ihtiyacı YOKTUR).

**Kesin ilke:** Recommendation Engine, Health Score'un SAYISAL
`final_score`/`confidence_score`/`data_coverage_ratio` değerlerini
KENDİ ürettiği HİÇBİR SAYIYA GİRDİ OLARAK KULLANMAZ (zaten hiçbir sayı
ÜRETMEZ) — yalnızca hangi kategori/oranın ZAYIF olduğunu OKUR ve buna
karşılık gelen METİN önerisini registry'den ÇEKER.

---

## 4. Credit Score ile İlişkisi

`CreditScoreResult`, Health Score ile SİMETRİK bir tetikleyici kaynağıdır
— ayrıca İKİ EK sorumluluk taşır:

1. **BANKING_READINESS katmanının (Bölüm 20a) BİRİNCİL girdisi**:
   `credit_score_result.banking_lens_signals.flags` → doğrudan
   BANKING_READINESS kategorisi önerilerini tetikler (6 kural, Bölüm
   20a).
2. **DATA_QUALITY kategorisinin İKİNCİ kaynağı** (Bölüm 20a):
   `credit_score_result.data_gap_disclosures` HEM `RecommendationResult.
   data_gap_disclosures`'a DOĞRUDAN, YENİDEN HESAPLANMADAN pass-through
   EDİLİR HEM DE 4 `DQ_ADDRESS_*` kuralı (36-39) İLE AKSİYON üretebilen
   DATA_QUALITY önerilerine DÖNÜŞTÜRÜLÜR (son onay turu, Madde 3/8 —
   Recommendation Engine'in bu 4 alanda VERİSİ YOKTUR, bu yüzden
   EKSİKLİĞİN kendisi raporlanır, eksik veri HAKKINDA bir tahmin
   ÜRETİLMEZ).

`credit_score_result.hard_fails_triggered`/`critical_overrides_applied`
Health Score ile AYNI şekilde (Bölüm 3) `CRITICAL`/`HIGH` öncelik
tetikleyicisidir. `credit_score_result.risk_tier`, `INFORMATIONAL`
seviyeli bir "genel bağlam" alanı olarak öneri açıklamalarında
(`supporting_evidence`) referans gösterilebilir ama TEK BAŞINA bir
öneri TETİKLEMEZ (yalnızca ratio-seviyeli tier'lar/hard-fail/override
tetikler — Bölüm 8/9).

**Kesin ilke (Credit Score'un `INVARIANT: HEALTH_SCORE_INPUT_
INDEPENDENCE`'ının Recommendation Engine'deki KARŞILIĞI değil, AYRI bir
kural):** Recommendation Engine, `CreditScoreResult`'ı okurken
`compute_credit_score()`'u ASLA yeniden ÇAĞIRMAZ, `CreditScoreResult`
nesnesini ASLA MUTASYONA UĞRATMAZ (bkz. Bölüm 12 pipeline'ın "salt
okunur" garantisi, Bölüm 28 test stratejisindeki zorunlu property
testi).

---

## 5. Girdi/Çıktı Sözleşmesi

### 5.1 Fonksiyon imzası (önerilen)

```python
def generate_recommendations(
    ratio_result_json: dict[str, Any],
    benchmark_result_json: dict[str, Any],
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    *,
    industry_code: str | None = None,
    company_size_bucket: str | None = None,
    tenant_id: str | None = None,
) -> RecommendationResult: ...
```

Dört girdi de **ZORUNLUDUR** (opsiyonel/`None` DEĞİLDİR) — Recommendation
Engine'in bütün amacı bu dört motorun sonucunu BİRLEŞTİRMEK olduğu için,
eksik bir motor sonucuyla çağrılması "kısmi ama sessiz" bir davranışa
değil, çağıranın (orkestrasyon katmanı, henüz bu milestone'un kapsamı
DIŞINDA) TÜM motorları ÖNCE ÇALIŞTIRMIŞ olmasını ZORUNLU KILAN AÇIK bir
sözleşmeye bağlanır. `health_score_result`/`credit_score_result`
DOĞRUDAN dataclass olarak geçirilir (Credit Score'un 4.1 kararıyla AYNI
gerekçe — aynı process, aynı saf-kütüphane katmanı, serileştirme sınırı
YOK).

`industry_code`/`company_size_bucket`/`tenant_id` — Bölüm 17'nin
çözümleme sırası için (v1'de yalnızca `global` dolu, Health/Credit
Score'la AYNI desen).

### 5.2 Girdi yapıları (TEKRAR HESAPLANMAZ, yalnızca OKUNUR)

- `ratio_result_json`/`benchmark_result_json` — Bölüm 1.1/1.2'de
  tanımlanan yapılar.
- `health_score_result: HealthScoreResult` — Bölüm 1.3.
- `credit_score_result: CreditScoreResult` — Bölüm 1.4.

### 5.3 Çıktı

`RecommendationResult` (Bölüm 6) — tam alan listesi, TAM açıklanabilir,
`Decimal`/`tuple`/frozen dataclass disiplini KORUNARAK.

---

## 6. `RecommendationResult` Dataclass

```python
@dataclass(frozen=True)
class RecommendationResult:
    status: RecommendationComputationStatus
    recommendations: tuple["RecommendationItem", ...]
    financial_recommendation_codes: "tuple[str, ...]"       # YENİ (Madde 10, Aşama 17) -- recommendations içindeki alt küme referansı
    banking_readiness_recommendation_codes: "tuple[str, ...]"  # YENİ (Madde 10, Aşama 17)
    data_quality_recommendation_codes: "tuple[str, ...]"    # YENİ (Madde 10, Aşama 17)
    category_coverage: "dict[str, Decimal]"
    uncovered_signal_codes: "tuple[str, ...]"               # YENİ (Madde 3) -- HİÇBİR kural tarafından kapsanmayan ratio_code'lar; skora/priority'ye ETKİMEZ
    health_score_reference: "RecommendationHealthScoreReference"
    credit_score_reference: "RecommendationCreditScoreReference"
    banking_lens_signals_reference: "BankingLensSignals"   # credit_score_result'tan DOĞRUDAN, yeniden hesaplanmadan taşınır
    data_gap_disclosures: "tuple[DataGapDisclosure, ...]"  # credit_score_result'tan DOĞRUDAN taşınır
    conflict_groups: "tuple[RecommendationConflictGroup, ...]"
    mutually_exclusive_groups: "tuple[RecommendationMutuallyExclusiveGroup, ...]"  # YENİ (Madde 9) -- conflict_groups'tan YAPISAL OLARAK AYRI (Bölüm 13.3)
    warnings: "tuple[dict[str, Any], ...]"
    disclaimer_tr: str
    provisional: bool
    recommendation_schema_version: str
    recommendation_model_version: str
    health_score_schema_version: str
    health_score_model_version: str
    credit_score_schema_version: str
    credit_score_model_version: str
    benchmark_registry_version: str
    ratio_registry_version: str
    category_weight_profile_used: str
```

**`uncovered_signal_codes` (Madde 3, kesin ilke):** bu alan HİÇBİR
skora, priority'ye veya confidence'a ETKİMEZ — YALNIZCA modelin hangi
sinyalleri HENÜZ bir kurala BAĞLAMADIĞINI şeffaf şekilde raporlar
(Bölüm 20a'daki TAM kapsam tablosunun runtime karşılığı). Statik olarak
`RECOMMENDATION_RULES`'ın `related_ratio_codes`/`evidence_rules`
BİRLEŞİMİ İLE Bölüm 18.1'in 48 sinyal listesinin FARKI alınarak
hesaplanır — registry-sabit bir küme olduğu için AYNI süreç için HER
ZAMAN AYNIDIR (girdiye bağlı DEĞİLDİR).

Alan alan gerekçe:

- `status`: aşağıdaki `RecommendationComputationStatus` — TEK bir
  sayısal skor olmadığı için Health/Credit Score'un `COMPUTED/
  HARD_FAIL_CAPPED/INSUFFICIENT_DATA` üçlüsü DOĞRUDAN uygulanamaz,
  Recommendation Engine'e ÖZGÜ bir versiyonu tanımlanır (Bölüm 12.5).
- `recommendations`: nihai, sıralanmış (Bölüm 9) `RecommendationItem`
  listesi.
- `category_coverage`: Recommendation Engine'in KENDİ 8-kategorili
  taksonomisinde (Bölüm 18), hangi kategoride ne kadar sinyal
  DEĞERLENDİRİLEBİLDİĞİ (0-1 arası `Decimal`) — şeffaflık.
- `health_score_reference`/`credit_score_reference`: Credit Score'un
  `HealthScoreReference` desenindeki KÜÇÜK özet struct'lar (Bölüm 6.1)
  — UI'ın "bu öneriler hangi genel skora dayanıyor" sorusuna cevap
  verir, YENİDEN HESAPLAMA İÇERMEZ.
- `banking_lens_signals_reference`/`data_gap_disclosures`: Credit
  Score'dan DOĞRUDAN, ikinci bir kopya YAZILMADAN taşınır.
- `conflict_groups`: Bölüm 13'ün veri modeli.
- `warnings`: dört girdinin `warnings`'lerinin BİRLEŞİMİ (Health
  Score'un `collect_all_warnings` desenindeki AYNI mantık, Recommendation
  Engine'e özgü ek uyarılarla — ör. `CATEGORY_INSUFFICIENT_DATA`,
  `CONFLICTING_RECOMMENDATIONS`).
- `disclaimer_tr`: Bölüm 15.3'teki jenerik, marka-adı-içermeyen uyarı.
- `provisional`: HER ZAMAN `True` (v1 — Health/Credit Score'la AYNI
  disiplin, kalibrasyon henüz gerçek veriyle yapılmadı).
- 8 versiyon alanı: Bölüm 16.

#### 6.1 Yardımcı struct'lar

```python
@dataclass(frozen=True)
class RecommendationHealthScoreReference:
    health_score_final_score: "Decimal | None"
    health_score_letter_rating: "str | None"
    health_score_status: str
    note_tr: str = (
        "Bu alan yalnızca Financial Health Score'un ÖZETİDİR -- "
        "Recommendation Engine'in öneri metinleri bu alandan DOĞRUDAN "
        "ÜRETİLMEZ, yalnızca bağlam sağlar."
    )

@dataclass(frozen=True)
class RecommendationCreditScoreReference:
    credit_score_final_score: "Decimal | None"
    credit_score_risk_tier: "str | None"
    credit_score_status: str
    note_tr: str = (
        "Bu alan yalnızca Credit Score'un ÖZETİDİR -- öneri metinleri bu "
        "alandan DOĞRUDAN ÜRETİLMEZ, yalnızca bağlam sağlar."
    )
```

#### 6.2 `RecommendationComputationStatus`

```python
class RecommendationComputationStatus(str, enum.Enum):
    COMPUTED = "computed"                                    # en az bir kategori değerlendirilebildi
    NO_RECOMMENDATIONS_TRIGGERED = "no_recommendations_triggered"  # veri yeterli ama hiçbir kural tetiklenmedi (şirket sağlıklı)
    INSUFFICIENT_DATA = "insufficient_data"                  # TÜM kategorilerde coverage < eşik
    SCHEMA_INCOMPATIBLE = "schema_incompatible"              # üst motor şema versiyonu desteklenmiyor -- HİÇBİR öneri üretilmez
    VERSION_MISMATCH = "version_mismatch"                    # YENİ (son onay turu, Madde 7) -- ratio/benchmark registry versiyonu desteklenmiyor, YALNIZCA DATA_QUALITY üretilir
```

`NO_RECOMMENDATIONS_TRIGGERED`, Health/Credit Score'da KARŞILIĞI
OLMAYAN, Recommendation Engine'e ÖZGÜ üçüncü bir durumdur — "veri
yeterliydi ama şirket o kadar sağlıklı ki hiçbir aksiyon tetiklenmedi"
durumunu, "veri YETERSİZ olduğu için öneri üretilemedi" durumundan
AÇIKÇA AYIRIR.

**`SCHEMA_INCOMPATIBLE`/`VERSION_MISMATCH` (KİLİTLİ, Bölüm 16.1/16.2,
Madde 7):** Bölüm 12 Aşama 1'de (pipeline'ın EN BAŞI) `RECOMMENDATION_
INPUT_COMPATIBILITY` politikasına karşı bir ön-kontrol yapılır:

- `health_score_schema_versions`/`credit_score_schema_versions`
  desteklenmiyorsa → `SCHEMA_INCOMPATIBLE`, `recommendations=()`
  (TAMAMEN boş — banking/data-quality DAHİL), `SCHEMA_VERSION_
  UNSUPPORTED` uyarısı.
- `ratio_registry_versions`/`benchmark_registry_versions`
  desteklenmiyorsa (şema OKUNABİLİR) → `VERSION_MISMATCH`, finansal/
  banking_readiness önerileri BASTIRILIR, YALNIZCA `DATA_QUALITY`
  üretilebilir, `RATIO_OR_BENCHMARK_VERSION_UNSUPPORTED` uyarısı.

**Kesin ilke:** sistem ASLA bilinmeyen bir şema/registry versiyonu
üzerinde "olası alanları tahmin ederek" ÇALIŞMAYA ÇALIŞMAZ — bu, hatalı/
eksik önerilerin SESSİZCE üretilmesinden DAHA GÜVENLİDİR.

---

## 7. `RecommendationType` Mimarisi

Üç ayrı, birbirini tamamlayan eksen (Credit Score'un `role` üçlü ekseni
gibi, ama Recommendation Engine'e özgü):

### 7.1 `RecommendationCategory` (7 değer — Bölüm 18)

```python
class RecommendationCategory(str, enum.Enum):
    WORKING_CAPITAL = "working_capital"
    LIQUIDITY = "liquidity"
    LEVERAGE = "leverage"
    PROFITABILITY = "profitability"
    ACTIVITY = "activity"
    GROWTH = "growth"
    BANKING = "banking"
```

### 7.2 `RecommendationTriggerSource` (hangi motor/mekanizma tetikledi)

```python
class RecommendationTriggerSource(str, enum.Enum):
    HEALTH_SCORE_HARD_FAIL = "health_score_hard_fail"
    HEALTH_SCORE_CRITICAL_OVERRIDE = "health_score_critical_override"
    HEALTH_SCORE_WEAK_TIER = "health_score_weak_tier"
    CREDIT_SCORE_HARD_FAIL = "credit_score_hard_fail"
    CREDIT_SCORE_CRITICAL_OVERRIDE = "credit_score_critical_override"
    CREDIT_SCORE_WEAK_TIER = "credit_score_weak_tier"
    BANKING_LENS_SIGNAL = "banking_lens_signal"
```

Bir `RecommendationItem.triggered_by` alanı BUNLARDAN **birden fazlasını**
içerebilir (Bölüm 14 — dedup sonrası birleşim).

### 7.3 v1'DE OLMAYAN ("strength reinforcement") tür — KİLİTLİ KARAR (son onay turu)

**KİLİTLİ (son onay turu, ONAY GEREKTİRMEZ):** Recommendation Engine v1,
**YALNIZCA** şu dört sonuç türünü üretir: (1) aksiyon gerektiren
finansal risk/zayıflık önerileri, (2) veri kalitesi/kapsam boşluğu
önerileri (`DATA_QUALITY` kategorisi), (3) banka-hazırlığı önerileri
(`BANKING_READINESS` kategorisi). "Güçlü yönünüzü koruyun", "aynı
şekilde devam edin" veya herhangi bir reinforcement/pekiştirme türü
**v1'de KESİN OLARAK YOKTUR ve v2'ye de TAŞINMAYACAK bir kapsam
sınırıdır** (gelecekte eklenmesi istenirse bu, YENİ bir milestone/tasarım
turu gerektirir — bu doküman içinde bir "hook" bile BIRAKILMAMIŞTIR).

**Gerekçe (kilitleme kararı):** Recommendation Engine'in amacı aksiyon
gerektiren finansal sorunları ve veri boşluklarını önceliklendirmektir
— güçlü yönler zaten Health Score'un `strengths` alanı ve Credit
Score'un explainability çıktılarında MEVCUTTUR (Bölüm 1.3/1.4), ikinci
bir yerde TEKRAR ÜRETİLMESİNE gerek YOKTUR. Bu KARARLAŞTIRILMIŞTIR,
artık Bölüm 33'te açık madde DEĞİLDİR.

---

## 8. Recommendation Registry — KİLİTLİ (son onay turu, Madde 6)

### 8.0 Nihai deklaratif trigger modeli (Madde 6, ZORUNLU, kapalı strateji kümesi)

**KİLİTLİ KARAR:** Serbest nested expression/expression tree/dinamik
kullanıcı-tanımlı mantık v1'de KESİNLİKLE KULLANILMAZ. Önceki turun
`trigger_conditions`/`condition_logic` modeli, kullanıcının bu turda
verdiği KESİN şemaya göre YENİDEN adlandırılmış ve GENİŞLETİLMİŞTİR:
`EvidenceRule` (eski `RecommendationTriggerCondition`) + `trigger_mode`
+ `evidence_rules` (düz tuple) + `minimum_evidence_count` + `prerequisite_
rules` + `blocking_rules`.

```python
@dataclass(frozen=True)
class EvidenceRule:
    """
    TEK bir atomik kanıt koşulu. Alanlardan YALNIZCA biri (ratio_code+
    tier_in ÇİFTİ HARİÇ, o ikisi TEK bir tür sayılır) dolu olabilir --
    kayıt anında MUTUAL EXCLUSIVITY doğrulanır (8.2 madde 6).
    """
    ratio_code: "str | None" = None
    tier_in: "tuple[str, ...] | None" = None
    hard_fail_code: "str | None" = None
    critical_override_ratio_code: "str | None" = None
    banking_lens_flag: "str | None" = None
    category_coverage_below: "RecommendationCategory | None" = None   # DATA_QUALITY kuralları için
    coverage_threshold: "Decimal | None" = None                       # category_coverage_below İLE birlikte, SABİT Decimal("0.50")
    credit_score_data_gap_code: "str | None" = None                   # DATA_QUALITY kuralları için (4 sabit kod)
```

**Kapalı, kayıtlı, saf strateji fonksiyonları (Madde 6'nın istediği
TAM liste):**

```python
def all_conditions(evidence_rules, context) -> bool: ...      # HER evidence_rule TRUE olmalı
def any_condition(evidence_rules, context) -> bool: ...       # EN AZ biri TRUE olmalı
def minimum_evidence(evidence_rules, context, minimum_evidence_count) -> bool: ...  # EN AZ N tanesi TRUE
def debt_funded_growth(evidence_rules, context) -> bool: ...  # banking_lens_flag=="DEBT_FUNDED_GROWTH" özel-adlı sarmalayıcı (okunabilirlik için)
def hard_fail_present(evidence_rules, context) -> bool: ...   # hard_fail_code kontrolüne özel-adlı sarmalayıcı
def banking_flag_present(evidence_rules, context) -> bool: ...  # banking_lens_flag kontrolüne özel-adlı sarmalayıcı
def data_coverage_gap(evidence_rules, context) -> bool: ...   # category_coverage_below kontrolü (DATA_QUALITY)
def data_gap_present(evidence_rules, context) -> bool: ...    # credit_score_data_gap_code kontrolü (DATA_QUALITY)
```

Her strateji: **sabit isimle `RecommendationTriggerStrategy` enum'unda
KAYITLI, SAF (yan etkisiz), test edilebilir, eval/exec İÇERMEYEN,
kullanıcı girdisinden KOD ÜRETMEYEN** bir fonksiyondur. `debt_funded_
growth`/`hard_fail_present`/`banking_flag_present`/`data_coverage_gap`/
`data_gap_present`, aslında `all_conditions`/`any_condition`'ın ÖZEL-
ADLI, TEK-koşullu sarmalayıcılarıdır — okunabilirlik/explainability
için ayrı isimlerle KAYITLIDIRLAR (bir registry okuyucusunun `trigger_
strategy="hard_fail_present"` görmesi, `trigger_strategy="all_
conditions"` görmesinden DAHA AÇIKLAYICIDIR), ama MEKANİK olarak
`all_conditions`'ın bir örneğidir (kod TEKRARI yoktur, ince bir
isimlendirme katmanıdır).

```python
class RecommendationTriggerStrategy(str, enum.Enum):
    ALL_CONDITIONS = "all_conditions"
    ANY_CONDITION = "any_condition"
    MINIMUM_EVIDENCE = "minimum_evidence"
    DEBT_FUNDED_GROWTH = "debt_funded_growth"
    HARD_FAIL_PRESENT = "hard_fail_present"
    BANKING_FLAG_PRESENT = "banking_flag_present"
    DATA_COVERAGE_GAP = "data_coverage_gap"
    DATA_GAP_PRESENT = "data_gap_present"
```

**İç-içe mantık (Bölüm 33'ün eski #10'u):** implementasyon sırasında
"A VE (B VEYA C)" gibi bir ihtiyaç çıkarsa, bu YENİ bir strateji ADI
(ör. `nested_group`) olarak, YİNE kapalı/saf/kayıtlı bir fonksiyon
şeklinde eklenir — serbest expression tree ASLA eklenmez. Bu, düşük
öncelikli, engelleyici olmayan bir implementasyon notu olarak
KALIR (Bölüm 33'te artık "açık karar" değil, bir UYGULAMA NOTUDUR).

### 8.1 `RecommendationRule` dataclass (TAM, 29 alan, son onay turu)

```python
@dataclass(frozen=True)
class RecommendationRule:
    recommendation_code: str
    category: RecommendationCategory
    result_bucket: ResultBucket                        # category'den TÜRETİLİR, kayıtta ÇAPRAZ DOĞRULANIR (8.2 madde 9)
    base_priority: RecommendationPriority
    severity: RecommendationSeverity
    impact_band: RecommendationImpactBand
    difficulty_band: RecommendationDifficultyBand
    trigger_strategy: RecommendationTriggerStrategy
    trigger_mode: str                                  # "all" | "any" -- strategy'nin İÇ birleştirme mantığı
    evidence_rules: "tuple[EvidenceRule, ...]"
    minimum_evidence_count: int                         # trigger_strategy="minimum_evidence" DIŞINDA genelde 1
    prerequisite_rules: "tuple[str, ...]"                # bu öneri için ÖN KOŞUL olan recommendation_code'lar (v1'de çoğu BOŞ)
    blocking_rules: "tuple[str, ...]"                    # aktifse bu öneriyi `blocked=True` yapan recommendation_code'lar (v1'de çoğu BOŞ)
    merge_group: "str | None"
    evidence_group: str                                 # açıklayıcı etiket, ör. "inventory_days_family"
    underlying_risk_code: str                            # motor-bağımsız semantik risk kimliği
    conflict_group: "str | None"
    mutually_exclusive_group: "str | None"               # Bölüm 13.3 -- conflict_group'tan YAPISAL OLARAK AYRI
    confidence_ceiling: Decimal                          # Bölüm 15.4 -- bu kuralın ULAŞABİLECEĞİ MAKSİMUM confidence
    coverage_policy: str                                 # "subject_to_gate" | "exempt_hard_fail" | "always_evaluated"
    related_ratio_codes: "tuple[str, ...]"
    title_tr: str
    explanation_tr: str
    action_steps_tr: "tuple[str, ...]"
    assumptions_tr: "tuple[str, ...]"
    disclaimer_tr: str
    disclaimer_scope: str                                # "general" | "banking"
    model_version_introduced: str
    deprecated_since: "str | None"
    replacement_recommendation_code: "str | None"
```

**Alan gerekçeleri (yalnızca YENİ/değişen alanlar):**

- `result_bucket`: Bölüm 12 Aşama 17'nin 3-yönlü ayrımı için — `category`'den
  DETERMİNİSTİK türetilir (LIQUIDITY/WORKING_CAPITAL/LEVERAGE/
  PROFITABILITY/ACTIVITY/GROWTH → FINANCIAL; BANKING_READINESS →
  BANKING_READINESS; DATA_QUALITY → DATA_QUALITY) ve kayıt anında bu
  eşlemeyle ÇAPRAZ DOĞRULANIR (serbest seçim DEĞİLDİR).
- `severity`: `priority`'den AYRI bir eksen — bu kuralın ele aldığı
  finansal durumun VARSAYILAN ciddiyeti (registry-statik); `priority`
  ise NİHAİ SIRALAMA önceliğidir (Bölüm 9). Hard-fail kaynaklı kurallar
  `severity=CRITICAL`, critical-override kaynaklılar `severity=HIGH`,
  weak-tier kaynaklılar `severity=MEDIUM`, "aşırı iyi tier" caution
  kuralları (ör. `WC_MAINTAIN_INVENTORY_SAFETY_BUFFER`) `severity=LOW`.
- `coverage_policy`: Madde 1'in hard-fail muafiyetini registry-seviyesinde
  AÇIK bir alana taşır (önceki turda yalnızca `trigger_source`'tan
  DOLAYLI çıkarsanıyordu) — `"exempt_hard_fail"` ⟺ `trigger_strategy
  ∈ {HARD_FAIL_PRESENT}` (kayıtta çapraz doğrulanır), `"always_
  evaluated"` ⟺ `category=DATA_QUALITY`, aksi halde `"subject_to_gate"`.
- `prerequisite_rules`/`blocking_rules`: registry KAPASİTESİ olarak
  TANIMLIDIR (kayıt anında referans bütünlüğü DOĞRULANIR — 8.2 madde
  10) ama **v1'in 39 kurallık envanterinde HİÇBİRİ DOLU DEĞİLDİR** —
  bu, icat edilmiş bir ilişki eklemek yerine DÜRÜST bir "mekanizma HAZIR,
  henüz gerçek bir kullanım örneği YOK" beyanıdır (Madde 2'nin kırık-
  referans dersinin AYNI disiplinle burada da uygulanmasıdır).
- `mutually_exclusive_group`: yalnızca `WC_MAINTAIN_INVENTORY_SAFETY_
  BUFFER`/`WC_REDUCE_INVENTORY_DAYS` çiftinde DOLU (Bölüm 13.3).
- `model_version_introduced`/`deprecated_since`/`replacement_
  recommendation_code`: kural-seviyesi YAŞAM DÖNGÜSÜ takibi — v1'in
  TÜM kuralları `model_version_introduced="1.0.0"`, `deprecated_
  since=None`, `replacement_recommendation_code=None` taşır (henüz
  hiçbir kural DEPRECATE edilmedi).

### 8.2 Kayıt anında doğrulama (`register_recommendation_rule`) — GENİŞLETİLMİŞ

1. `recommendation_code` benzersiz olmalı.
2. `related_ratio_codes`'un HER biri `RATIO_REGISTRY`'de KAYITLI olmalı
   VE Bölüm 18.1'in `category` eşlemesiyle TUTARLI olmalı (bir kuralın
   `category`'si, `related_ratio_codes`'unun 18.1 tablosundaki
   kategorisiyle UYUŞMUYORSA kayıt REDDEDİLİR).
3. `category` geçerli bir `RecommendationCategory` üyesi olmalı;
   `result_bucket`, yukarıdaki DETERMİNİSTİK eşlemeyle UYUŞMALIDIR.
4. `conflict_group` doluysa AYNI grupta EN AZ 2 kural olmalı;
   `RECOMMENDATION_CONFLICT_PAIRS`'teki HER iki recommendation_code da
   `RECOMMENDATION_RULES`'ta KAYITLI OLMALIDIR (v1'de bu tablo BOŞ,
   Bölüm 13.2).
5. `disclaimer_scope="banking"` ⟺ `category=BANKING_READINESS`.
6. `evidence_rules`'taki HER `EvidenceRule`'un TAM OLARAK BİR "koşul
   türü" doldurmuş olması ZORUNLUDUR (`ratio_code`+`tier_in` ÇİFTİ TEK
   tür; `hard_fail_code`/`critical_override_ratio_code`/`banking_lens_
   flag`/`category_coverage_below`+`coverage_threshold`/`credit_score_
   data_gap_code`'dan yalnızca biri).
7. `ratio_code` kullanan koşullardaki oran kodu `related_ratio_codes`
   içinde de YER ALMALIDIR.
8. `tier_in` yalnızca `{"critical","weak","average","good","excellent"}`
   (BENCHMARK_REGISTRY'nin gerçek bant isimlerinden); `hard_fail_code`
   yalnızca Health/Credit Score'un bilinen hard-fail kataloğundan;
   `banking_lens_flag` yalnızca Credit Score'un 6 bilinen bayrağından;
   `credit_score_data_gap_code` yalnızca 4 bilinen `DataGapDisclosure`
   kodundan olmalıdır.
9. `mutually_exclusive_group` doluysa AYNI grupta EN AZ 2 kural olmalı
   VE bu kurallar `RECOMMENDATION_CONFLICT_PAIRS`'te AYRICA YER
   ALAMAZ (bir çift ya conflict YA DA mutually-exclusive'dır, İKİSİ
   BİRDEN DEĞİL — Bölüm 13.3).
10. `prerequisite_rules`/`blocking_rules` içindeki HER recommendation_
    code, `RECOMMENDATION_RULES`'ta KAYITLI OLMALIDIR (v1'de boş
    tuple'lar için bu kontrol TRIVIAL geçer).
11. `severity`/`base_priority`/`coverage_policy` yukarıdaki DETERMİNİSTİK
    eşlemelerle TUTARLI olmalı (ör. `trigger_strategy=HARD_FAIL_PRESENT`
    ⟹ `coverage_policy="exempt_hard_fail"` VE `severity=CRITICAL`).
12. `base_priority=INFORMATIONAL` **YALNIZCA** `result_bucket ∈
    {BANKING_READINESS, DATA_QUALITY}` olan kurallarda İZİN VERİLİR
    (Madde 4) — `FINANCIAL` bucket'ında `INFORMATIONAL` kayıt anında
    REDDEDİLİR.

### 8.3 Diğer registry'ler

```python
RECOMMENDATION_RULES: "tuple[RecommendationRule, ...]" = (...)                       # Bölüm 20a
RECOMMENDATION_CATEGORY_WEIGHT_PROFILES: "dict[tuple[str, str | None], Any]" = {...}  # Bölüm 17
RECOMMENDATION_CONFLICT_PAIRS: "tuple[tuple[str, str], ...]" = ()                     # Bölüm 13.2 -- v1'de BOŞ
RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS: "tuple[RecommendationMutuallyExclusiveGroup, ...]" = (...)  # Bölüm 13.3
BANKING_FLAG_TO_RATIO_OVERLAP: "dict[str, tuple[str, ...]]" = {...}                    # Bölüm 14.1
RECOMMENDATION_INPUT_COMPATIBILITY: "dict[str, frozenset[str]]" = {...}                # Bölüm 16.1
RELIABILITY_TO_CONFIDENCE_CEILING: "dict[str, Decimal]" = {...}                        # Bölüm 15.4
```

`RECOMMENDATION_CATEGORY_WEIGHT_PROFILES` — Bölüm 9'daki öncelik
hesaplamasında AĞIRLIK olarak KULLANILMAZ — yalnızca `category_coverage`
raporlamasında tie-break referansıdır (Health/Credit Score'daki kategori
ağırlığından KAVRAMSAL OLARAK FARKLI, Bölüm 30).

---

## 9. Priority (Öncelik) ve Severity Sistemi — KİLİTLİ (son onay turu, Madde 4)

### 9.1 `RecommendationPriority` (5 kademe) — LOW BAĞIMSIZ bir `base_priority` değeridir

**KİLİTLİ KARAR:** `LOW`, **bağımsız, açık bir `base_priority`
değeridir.** Önceki turun "zaten MEDIUM+ bir öneriyle kaplı kategoride
ikincil" örtük subset/duplicate mantığı **TAMAMEN KALDIRILMIŞTIR.**

```python
class RecommendationPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"

_PRIORITY_RANK: dict[str, int] = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4,
}


class RecommendationSeverity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

| `base_priority` | Registry-statik atama kuralı | Örnek |
|---|---|---|
| `CRITICAL` | `trigger_strategy=HARD_FAIL_PRESENT` | `LEV_STRENGTHEN_EQUITY_BASE` (NEGATIVE_EQUITY) |
| `HIGH` | `trigger_strategy` critical-override kanıtı okuyor | `LIQ_IMPROVE_CURRENT_RATIO` |
| `MEDIUM` | Weak-tier tabanlı, hard-fail/override YOK | `WC_REDUCE_INVENTORY_DAYS` |
| `LOW` | BAĞIMSIZ, registry-statik atama — "aşırı iyi tier" caution kuralları VEYA ikincil-önem kuralları (ÖRTÜK subset mantığı YOK) | `WC_MAINTAIN_INVENTORY_SAFETY_BUFFER`, `ACT_IMPROVE_FIXED_ASSET_TURNOVER` |
| `INFORMATIONAL` | **YALNIZCA** `result_bucket ∈ {BANKING_READINESS, DATA_QUALITY}` (Madde 4, 8.2 madde 12 ile ZORUNLU kılınır) — doğrudan finansal düzeltme aksiyonlarında KULLANILAMAZ | `BANK_PREPARE_LIQUIDITY_NARRATIVE` (bazı senaryolarda) |

**`severity`** (RecommendationSeverity, YENİ eksen) HER kuralın registry-
statik "bu durumun ne kadar ciddi olduğu" etiketidir — `priority`'den
BAĞIMSIZ tutulur (bir `LOW` priority kural yine de `severity=MEDIUM`
taşıyabilir; ikisi FARKLI SORULARA cevap verir: severity "durum ne
kadar kötü", priority "bu öneri listede NEREDE görünmeli").

### 9.2 Eskalasyon/bloklama modeli (deterministik, registry'de İCAT EDİLMEZ)

`base_priority`, kuralın SABİT, DEĞİŞMEZ ANLAMIDIR — aşağıdaki
mekanizmalar bunu bir RUNTIME KATMANI olarak ETKİLER, ama `base_
priority`'nin registry'deki DEĞERİNİ asla YENİDEN YAZMAZ:

1. **Hard-fail eskalasyonu (koşulsuz, Madde 1 ile TUTARLI):** kuralın
   `evidence_rules`'undan biri `health_score_result.hard_fails_
   triggered`/`credit_score_result.hard_fails_triggered` içinde
   eşleşiyorsa → nihai `priority = CRITICAL` (`base_priority` NE
   OLURSA olsun).
2. **Critical-override eskalasyonu:** `critical_overrides_applied`
   içinde eşleşme varsa → nihai `priority` EN AZ `HIGH` (`base_
   priority` zaten `HIGH`/`CRITICAL` ise DEĞİŞMEZ).
3. **`severity` nüansı (KONTROLLÜ, TEK kademe):** `severity=CRITICAL`
   olan ama madde 1/2 tarafından eskale EDİLMEMİŞ bir kural, nihai
   `priority`'yi TAM OLARAK BİR kademe YUKARI nüanslayabilir (ör.
   `MEDIUM` → `HIGH`) — ASLA iki kademe ATLAMAZ, ASLA `CRITICAL`/`HIGH`
   eskalasyonunun ÖNÜNE GEÇMEZ.
4. **`confidence_ceiling` sönümlemesi:** nihai `confidence` (Bölüm 15.4)
   `Decimal("0.50")`'nin ALTINDAYSA, madde 3'ün nüansı UYGULANMAZ
   (düşük güvenilirlikli bir kanıt, önceliği YUKARI ÇEKMEZ) — bu bir
   priority DÜŞÜRME değil, bir nüans ENGELLEMESİDİR.
5. **`blocked` işaretlemesi (bastırma DEĞİL):** kuralın `blocking_rules`
   listesindeki HERHANGİ bir recommendation_code AYNI çalıştırmada
   AKTİFSE, bu item `blocked=True` İŞARETLENİR — **priority DEĞERİ
   DEĞİŞMEZ**, item YİNE `recommendations`'ta YER ALIR (Bölüm 13'ün
   "asla bastırma" ilkesiyle TUTARLI), yalnızca tüketici tarafa "bu an
   için aksiyona GEÇİLMEMELİ" sinyali verilir. v1'in 39 kuralında
   `blocking_rules` BOŞ olduğu için bu alan v1'de HİÇ `True` DÖNMEZ —
   mekanizma HAZIR, kullanım örneği YOK (8.1'deki AYNI dürüstlük).

**Kesin ilke:** madde 1-5 bir ÜST KATMANDIR — `RecommendationRule.
base_priority`'nin registry'deki DEĞERİ hiçbir zaman MUTASYONA UĞRAMAZ,
yalnızca ÇIKTIDAKİ `RecommendationItem.priority` bu katmanın SONUCUNU
taşır.

### 9.3 Sıralama

`recommendations` tuple'ı, `(priority_rank, category.value,
recommendation_code)` anahtarıyla artan sırada, DETERMİNİSTİK olarak
sıralanır. `blocked=True` item'lar sıralamadan ÇIKARILMAZ, yalnızca
AYNI anahtarla sıralanmaya devam eder (görünürlük KAYBOLMAZ).

---

## 10. Impact (Etki) Sistemi

### 10.1 `RecommendationImpactBand`

```python
class RecommendationImpactBand(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

**Kesin ilke (kritik, Bölüm 19 ile doğrudan bağlantılı):** `impact_band`
**registry'de SABİT, öznel/uzman-tanımlı bir NİTELİKSEL etikettir** —
"bu aksiyonu uygularsanız skorunuz X puan artar" gibi SAYISAL bir
TAHMİN/PROJEKSİYON **DEĞİLDİR** ve asla öyle SUNULMAZ. Sayısal bir
projeksiyon üretmek, tanım gereği ratio/benchmark/score'u YENİDEN
HESAPLAMAYI gerektirir — bu, Bölüm 2.1 madde 1-3'ün AÇIKÇA YASAKLADIĞI
bir şeydir. `impact_band`, yalnızca "bu kategori genel olarak ne kadar
ağırlıklı/görünür bir sinyaldir" sorusuna (`base_priority`'den BAĞIMSIZ,
tamamlayıcı bir boyut — ör. `CRITICAL` öncelikli ama LOW impact'li bir
öneri OLABİLİR: acil ama etkisi dar kapsamlı bir düzeltme) editoryal bir
cevaptır.

### 10.2 Atama

Her `RecommendationRule` KAYIT ANINDA sabit bir `impact_band` taşır —
ÇALIŞMA ZAMANINDA hesaplanmaz/değişmez (Bölüm 20-26 tabloları).

---

## 11. Difficulty (Zorluk) Sistemi

### 11.1 `RecommendationDifficultyBand`

```python
class RecommendationDifficultyBand(str, enum.Enum):
    LOW_EFFORT = "low_effort"           # operasyonel, kısa vadede uygulanabilir
    MODERATE_EFFORT = "moderate_effort" # süreç/politika değişikliği gerektirir
    STRUCTURAL_EFFORT = "structural_effort"  # sermaye yapısı/uzun vadeli karar gerektirir
```

Örnekler: "vadesi geçmiş alacakları takip sıklaştırın" → `LOW_EFFORT`;
"tedarikçi ödeme vadelerini yeniden müzakere edin" → `MODERATE_EFFORT`;
"uzun vadeli borç yeniden yapılandırması değerlendirin" →
`STRUCTURAL_EFFORT`. Tıpkı `impact_band` gibi, KAYIT ANINDA SABİT,
editoryal bir etikettir — ÇALIŞMA ZAMANINDA hesaplanmaz.

---

## 12. Recommendation Üretim Pipeline'ı — KİLİTLİ, 20 ADIMLIK KESİN SIRA (son onay turu, Madde 10)

**INVARIANT: RECOMMENDATION_ENGINE_READ_ONLY** (Bölüm 28 madde 7 ile
kanıtlanır): pipeline boyunca `ratio_result_json`/`benchmark_result_
json`/`health_score_result`/`credit_score_result` HİÇBİR ADIMDA
MUTASYONA UĞRAMAZ; `RATIO_REGISTRY`/`BENCHMARK_REGISTRY`/`RATIO_SCORE_
WEIGHTS`/`CREDIT_RATIO_SCORE_WEIGHTS`/`RECOMMENDATION_RULES` boyutu/
içeriği DEĞİŞMEZ; `analyze_financial_ratios`/`evaluate_benchmarks`/
`compute_financial_health_score`/`compute_credit_score` fonksiyonlarının
HİÇBİRİ İÇERİDEN ÇAĞRILMAZ. Bu invariant HER 20 ADIMDA da geçerlidir —
aşağıda yalnızca adıma ÖZGÜ mutation-yasağı/failure-davranışı notları
tekrarlanır, genel invariant HER ZAMAN GEÇERLİDİR.

### Adım 1 — Upstream schema/version compatibility kontrolü

`RECOMMENDATION_INPUT_COMPATIBILITY` (Bölüm 16.1) kontrol edilir.
Uyumsuzsa pipeline BURADA DURUR: `SCHEMA_INCOMPATIBLE` (şema okunamaz)
veya `VERSION_MISMATCH` (şema OK, registry versiyonu desteklenmiyor) —
Bölüm 16.2. **Failure davranışı:** hiçbir sonraki adım ÇALIŞMAZ,
`RecommendationResult` doğrudan bu adımdan İNŞA EDİLİR (Adım 20'ye
DOĞRUDAN atlanır). **Mutation:** YOK (yalnızca OKUMA).

### Adım 2 — Girdileri immutable şekilde doğrula

4 girdinin (`ratio_result_json`/`benchmark_result_json`/`health_score_
result`/`credit_score_result`) beklenen ÜST-SEVİYE şekle sahip olduğu
doğrulanır (ör. `health_score_result` gerçekten bir `HealthScoreResult`
örneği mi). **Mutation YASAK** — bu adım yalnızca tip/şekil KONTROLÜ
yapar, hiçbir alanı YAZMAZ. **Failure:** beklenmeyen tip → `ValueError`
(çağıran hatası, İÇERİDE yutulmaz — Health/Credit Score'un mevcut
disipliniyle TUTARLI).

### Adım 3 — Evidence adaylarını topla

Health Score'un `collect_ratio_signals()`'ı REUSE edilerek `ratio_
result_json`+`benchmark_result_json`'dan düz bir `signals: dict[ratio_
code, dict]` üretilir (ikinci bir kopya YAZILMAZ). TEK bir `context`
sözlüğü inşa edilir:

```python
context = {
    "signals": signals,
    "health_score_hard_fails": set(health_score_result.hard_fails_triggered),
    "health_score_critical_overrides": set(health_score_result.critical_overrides_applied),
    "credit_score_hard_fails": set(credit_score_result.hard_fails_triggered),
    "credit_score_critical_overrides": set(credit_score_result.critical_overrides_applied),
    "banking_lens_flags": set(credit_score_result.banking_lens_signals.flags),
    "credit_score_data_gaps": set(dg.gap_code for dg in credit_score_result.data_gap_disclosures),
    "health_score_status": health_score_result.status,
    "credit_score_status": credit_score_result.status,
}
```

**Mutation YASAK** — `context` YENİ, BAĞIMSIZ bir sözlüktür, girdi
nesnelerinin İÇİNE yazmaz (`set(...)` KOPYALAR, referans TUTMAZ).

### Adım 4 — Hard-fail evidence'larını işaretle

`context["health_score_hard_fails"]`/`context["credit_score_hard_
fails"]`'in BOŞ olup olmadığı NOT EDİLİR (Adım 7/8'in coverage-gate
istisnası için gereklidir). **Mutation YOK** — yalnızca OKUMA.

### Adım 5 — Data-quality gap'lerini tespit et

`credit_score_result.data_gap_disclosures` (4 sabit kod) VE Adım 6'da
hesaplanacak kategori coverage'ları (henüz bu adımda YOK, bu yüzden bu
adım yalnızca `data_gap_disclosures`'ı okur; kategori-coverage kaynaklı
DATA_QUALITY tetikleyicileri Adım 9'da değerlendirilir) NOT edilir.

### Adım 6 — Declarative rule eligibility değerlendirmesi

`RECOMMENDATION_RULES`'taki HER kural için, kuralın `trigger_strategy`+
`evidence_rules`+`trigger_mode`+`minimum_evidence_count`'ı (Bölüm 8.0/
8.1) kapalı strateji fonksiyonlarıyla `context` üzerinde değerlendirilir.
`True` dönen kurallar "eligible" (uygun) İŞARETLENİR — HENÜZ
`RecommendationItem` ÜRETİLMEZ (yalnızca eligibility, Adım 9'da somut
adaya dönüştürülür). **Mutation YASAK** — strateji fonksiyonları SAF'tır
(Bölüm 8.0).

### Adım 7 — Coverage politikası uygula

Recommendation Engine'in KENDİ 8-kategorili taksonomisi (Bölüm 18)
üzerinden HER kategori için `category_coverage` hesaplanır (Health
Score'un `compute_overall_data_coverage_ratio` YAPISININ KENDİ, kısa
bir kopyası — Credit Score'un `redistribute_category_weights`'i NEDEN
kendi kopyasını tuttuğuyla AYNI gerekçe). `coverage_policy="subject_
to_gate"` olan eligible kurallar, KENDİ kategorisinin `category_
coverage < 0.50` olması durumunda BU ADIMDA elenmeye ADAY İŞARETLENİR
(kesin eleme Adım 8 SONRASI, Adım 9'dan ÖNCE uygulanır).

### Adım 8 — Hard-fail coverage exception uygula

`coverage_policy="exempt_hard_fail"` olan kurallar Adım 7'nin elemesinden
**KOŞULSUZ MUAF TUTULUR** — kategori coverage'ı %0 olsa DAHİ elenmezler
(Madde 1'in bağlayıcı kararı). `coverage_policy="always_evaluated"`
olan (`DATA_QUALITY`) kurallar da ZATEN muaftır (coverage gate onlar
için ANLAMSIZDIR — onlar zaten coverage EKSİKLİĞİNİ raporluyor).
**Gerekçe (tekrar, bağlayıcı):** en az verinin bulunduğu, dolayısıyla
en riskli anda en kritik uyarıyı bastırmak kabul EDİLEMEZ.

### Adım 9 — Aday recommendation item'larını oluştur

Adım 6'da eligible işaretlenen VE Adım 7-8'in coverage filtresinden
GEÇEN kurallar, somut `RecommendationItem` adaylarına dönüştürülür
(henüz confidence/dedup/conflict/priority-eskalasyon UYGULANMADAN —
yalnızca ham alan kopyalama). **Mutation YASAK.**

### Adım 10 — Per-item confidence/reliability hesapla

Bölüm 15.4'ün TAM modeli (madde a-h) HER adaya UYGULANIR: `confidence`/
`reliability`/`confidence_ceiling`/`coverage`/`provisional`/`confidence_
basis`/`evidence_reliabilities`/`missing_inputs` HESAPLANIR.
`DATA_QUALITY` kategorisindeki adaylar `confidence=1.00` SABİT alır.
**Mutation YASAK** — yalnızca YENİ alanlar HESAPLANIR, girdi
DEĞİŞTİRİLMEZ.

### Adım 11 — Duplicate/merge işle (Bölüm 14)

AYNI, BOŞ-OLMAYAN `merge_group` taşıyan adaylar TEK bir item'a
BİRLEŞTİRİLİR (title/action/explanation ilk kuralınki, `triggered_by`/
`related_ratio_codes`/`supporting_evidence` birleşimi, `priority` en
yükseği, `confidence` en düşüğü — Bölüm 15.4 ile TUTARLI min-ceiling
ilkesi).

### Adım 12 — Supporting ilişkileri kur

`evidence_group`/`underlying_risk_code` alanları üzerinden, AYNI
`underlying_risk_code`'u paylaşan (ama `merge_group`'u FARKLI olduğu
için BİRLEŞTİRİLMEYEN) item'lar arasında YALNIZCA explainability
amaçlı bir "ilişkili öneriler" referansı (`supporting_evidence`
içinde `source` alanıyla ZATEN görünür — AYRI bir yeni alan
GEREKMEZ) doğrulanır. **Mutation YOK.**

### Adım 13 — Conflict ve mutually-exclusive ilişkileri üret (Bölüm 13)

`RECOMMENDATION_CONFLICT_PAIRS`'teki (v1'de BOŞ) HER çift için, İKİ
tarafı da nihai listede varsa karşılıklı `conflicting_with`/`conflict_
group_id` doldurulur. `RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS`'taki
HER grup için (v1'de 1 grup, Bölüm 13.3) `mutually_exclusive_group_id`
doldurulur — bu YAPISAL olarak zaten aynı anda tetiklenemeyeceği için
pratikte İKİ tarafın da AYNI ANDA nihai listede olması BEKLENMEZ, ama
alan YİNE DE her item'da (varsa) DOLU taşınır.

### Adım 14 — Prerequisite/blocking kurallarını uygula

`blocking_rules`'ı BOŞ-OLMAYAN bir kuralın, listesindeki HERHANGİ bir
recommendation_code AYNI çalıştırmada aktifse `blocked=True` işaretlenir
(Bölüm 9.2 madde 5 — v1'de HİÇ tetiklenmez, mekanizma hazır). `prerequisite_
rules`'ı BOŞ-OLMAYAN bir kuralın, listesindeki TÜM recommendation_code'lar
aktif DEĞİLSE bu aday YİNE DE üretilir ama `warnings`'e bir `PREREQUISITE_
NOT_MET` notu düşülür (v1'de HİÇ tetiklenmez).

### Adım 15 — Priority escalation uygula (Bölüm 9.2)

Hard-fail/critical-override eskalasyonu + severity nüansı + confidence-
ceiling sönümlemesi UYGULANIR. `base_priority`'nin registry değeri
MUTASYONA UĞRAMAZ, yalnızca `RecommendationItem.priority` bu katmanın
SONUCUNU taşır.

### Adım 16 — Stable deterministic sorting uygula (Bölüm 9.3)

`(priority_rank, category.value, recommendation_code)` anahtarıyla
artan sırada DETERMİNİSTİK sıralama.

### Adım 17 — Financial / banking-readiness / data-quality listelerine ayır

`result_bucket` alanına göre `recommendations` tuple'ının İÇİNDEKİ
recommendation_code'lar `financial_recommendation_codes`/`banking_
readiness_recommendation_codes`/`data_quality_recommendation_codes`
(Bölüm 6) referans listelerine DAĞITILIR — veri KOPYALANMAZ, yalnızca
recommendation_code REFERANSLARI tutulur.

### Adım 18 — Explainability, warnings, uncovered signals ve model coverage üret

`uncovered_signal_codes` (Bölüm 6) hesaplanır (registry-sabit, Adım
9'un SONUÇLARINDAN bağımsız). Tüm adım-seviyesi uyarılar (`CATEGORY_
INSUFFICIENT_DATA`, `CONFLICTING_RECOMMENDATIONS`, `MODEL_VERSION_
MISMATCH`, `PREREQUISITE_NOT_MET` vb.) `warnings`'de TOPLANIR.

### Adım 19 — Read-only invariant doğrulaması

**ZORUNLU, implementasyonda property testle KANITLANIR (Bölüm 28 madde
7):** 4 girdi nesnesinin deep-copy karşılaştırmasıyla MUTASYONA
UĞRAMADIĞI, ilgili registry'lerin boyut/içeriğinin DEĞİŞMEDİĞİ, üst
motor fonksiyonlarının HİÇ ÇAĞRILMADIĞI (mock/spy) doğrulanır. Bu adım
YEŞİL olmadan pipeline SONUÇ DÖNDÜRMEZ (implementasyonda bir
`assert`/invariant-check olarak, HATA varsa `RuntimeError` fırlatılır
— asla sessizce geçilmez).

### Adım 20 — `RecommendationResult` oluştur

Tüm önceki adımların SONUÇLARI TEK bir `frozen` `RecommendationResult`
nesnesine TOPLANIR ve DÖNÜLÜR. **Mutation YASAK** — bu, pipeline'ın TEK
çıkış noktasıdır.

---

## 13. Çakışan ve Birbirini Dışlayan Önerilerin Yönetimi — KİLİTLİ (son onay turu, Madde 9)

**Kesin ilke:** Recommendation Engine, İKİ GEÇERLİ ama BİRBİRİNE
KISMEN TERS aksiyon önerisini ASLA otomatik olarak BASTIRMAZ/SEÇMEZ —
bu, kullanıcının (bir finans yöneticisinin) vermesi gereken bir İŞ
KARARIDIR, motorun DEĞİL. Bunun yerine HER İKİSİ de sonuçta YER ALIR,
`conflicting_with` alanıyla AÇIKÇA İŞARETLENİR, ve `warnings`'e bir
`CONFLICTING_RECOMMENDATIONS` notu düşülür.

### 13.1 `RecommendationConflictGroup`

```python
@dataclass(frozen=True)
class RecommendationConflictGroup:
    conflict_group_id: str
    recommendation_codes: "tuple[str, ...]"
    explanation_tr: str
```

### 13.2 `RECOMMENDATION_CONFLICT_PAIRS` — v1'de BOŞ, dürüstçe işaretlenmiş

**Kesin, dürüst tespit (son onay turu):** v1'in 39 kurallık gerçek
envanterinde (Bölüm 20a), İKİ FARKLI kuralın AYNI ANDA (gerçekten
birlikte, mantıksal olarak birbirini dışlamadan) tetiklenip GENUİNE
şekilde ZIT bir aksiyon önerdiği bir çift YOKTUR — bunu icat etmek
(ör. önceki turlarda kullanılan, hiç var olmayan bir "büyümeyi borçla
finanse et" kuralı UYDURMAK) Madde 2'nin düzelttiği kırık-referans
hatasını FARKLI bir biçimde TEKRARLARDI. Bu yüzden:

```python
RECOMMENDATION_CONFLICT_PAIRS: "tuple[tuple[str, str], ...]" = ()  # v1'de KASITLI OLARAK BOŞ
```

Mekanizma (Bölüm 8.2 madde 4'ün doğrulaması, Bölüm 12 Aşama 13) TAM
olarak İMPLEMENTE edilir ve TEST EDİLİR (Bölüm 28), yalnızca v1 kural
seti bu mekanizmayı GERÇEK bir çiftle DOLDURMAZ. Bir sonraki kural-seti
genişlemesinde (Bölüm 33 madde 4'ün ürün kararı) GERÇEK, doğrulanmış
çiftler eklenecektir.

### 13.3 `RecommendationMutuallyExclusiveGroup` — conflict'ten YAPISAL OLARAK AYRI (YENİ, Madde 9)

**Ayrım gerekçesi:** bir "conflict", İKİ kuralın AYNI ANDA, GERÇEKTEN
birlikte tetiklenip kullanıcıya İKİ farklı, birbirine kısmen ters
aksiyon sunmasıdır (yukarı, 13.1/13.2). Bir "mutually exclusive" ilişki
İSE, İKİ kuralın **mantıksal olarak AYNI ANDA tetiklenmesi mümkün
OLMAYAN**, AYNI oranın DİSJOINT tier aralıklarına dayanan bir ilişkidir
— bu YAPISAL bir garanti olduğu için "kullanıcıya iki seçenek sunup
karar verdirme" senaryosu OLUŞMAZ, yalnızca registry-seviyesinde
BELGELENMESİ gereken bir İLİŞKİDİR (ör. explainability/dokümantasyon
amaçlı).

```python
@dataclass(frozen=True)
class RecommendationMutuallyExclusiveGroup:
    mutually_exclusive_group_id: str
    recommendation_codes: "tuple[str, ...]"
    explanation_tr: str
```

**v1'deki TEK, gerçek örnek:** `WC_MAINTAIN_INVENTORY_SAFETY_BUFFER`
(Bölüm 20a — stok tamponunu koru, `days_inventory_outstanding`
tier∈{strong,ideal}'de tetiklenir) İLE `WC_REDUCE_INVENTORY_DAYS`
(Bölüm 20a — envanteri hızlandır, AYNI oranın tier∈{weak,critical}'de
tetiklenir) — bir oranın tier'i MANTIKSAL olarak yalnızca BİR bandda
olabileceği için bu ikisi ASLA aynı anda tetiklenemez.

```python
RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS: "tuple[RecommendationMutuallyExclusiveGroup, ...]" = (
    RecommendationMutuallyExclusiveGroup(
        mutually_exclusive_group_id="MEG_INVENTORY_LEVEL",
        recommendation_codes=("WC_MAINTAIN_INVENTORY_SAFETY_BUFFER", "WC_REDUCE_INVENTORY_DAYS"),
        explanation_tr=(
            "Bu iki öneri, aynı göstergenin (days_inventory_outstanding) "
            "birbirini dışlayan iki farklı bandına dayanır; aynı anda "
            "tetiklenmeleri mantıksal olarak mümkün değildir."
        ),
    ),
)
```

---

## 14. Duplicate Recommendation Politikası — KİLİTLİ (son onay turu, `merge_group` ile formalize)

**REVİZYON (son onay turu):** dedup mekanizması artık AD-HOC bir
"`_DUPLICATE_RATIO_PAIRS`" tablosuna DEĞİL, Bölüm 8.1'in registry-resmi
`merge_group` alanına DAYANIR — bu, Madde 9'un istediği "her ilişki
registry'de AÇIKÇA TANIMLI olsun" ilkesiyle TAM uyumludur.

**Tanım:** İki aday `RecommendationItem`, `recommendation_code`'ları
FARKLI olsa bile, **AYNI, BOŞ-OLMAYAN `merge_group` değerini
TAŞIYORLARSA** "aynı temel öneri" sayılır ve **BİRLEŞTİRİLİR** (çakışma
DEĞİL — çakışma Bölüm 13'te FARKLI, ZIT yönlü aksiyonlar için; duplicate
ise AYNI yönlü, yalnızca FARKLI kategori/motor kaynaklı tekrar için).

**Mimari iyileştirme (son onay turu):** Bölüm 8.1'in yeni `evidence_
rules`/`trigger_mode="any"` modeli sayesinde, Health Score VE Credit
Score'un AYNI temel zayıflığı (ör. düşük özkaynak) FARKLI oran
kodlarıyla işaret ettiği klasik senaryo artık **İKİ AYRI kural
YAZMAYI GEREKTİRMEZ** — `LEV_STRENGTHEN_EQUITY_BASE` (Bölüm 20a) TEK
BİR kuraldır ve `evidence_rules`'ı hem Health Score'un hem Credit
Score'un ilgili hard-fail/critical-override kanıtlarını `trigger_
mode="any"` ile ALTERNATİF olarak okur — bu, önceki turların
"iki kuralı sonradan birleştir" yaklaşımından DAHA TEMİZ bir
çözümdür (dedup mekanizmasına hiç ihtiyaç KALMAZ, çünkü zaten TEK
kural var).

`merge_group`, bu yüzden v1'de YALNIZCA **FARKLI kategorilerdeki**
(dolayısıyla FARKLI kurallar olarak KALMASI gereken, çünkü kategori
ayrımı EXPLAINABILITY için önemlidir) rulelar arasındaki dedup için
kullanılır — en somut örneği BANKING_READINESS/fonksiyonel kategori
örtüşmesidir (14.1).

**Birleştirme kuralı (`merge_group` eşleştiğinde):** `title_tr`/
`action_steps_tr`/`explanation_tr` İLK (registry sırasına göre)
kuralınki KULLANILIR, `triggered_by` İKİ kaynağın da
`RecommendationTriggerSource` değerlerinin BİRLEŞİMİ olur,
`related_ratio_codes`/`supporting_evidence` İKİSİNİN BİRLEŞİMİ olur,
`priority` İKİSİNİN EN YÜKSEĞİ (Bölüm 9) olur, `confidence` İKİSİNİN
EN DÜŞÜĞÜ (Bölüm 15.4'ün "ceiling'lerin en düşüğü" ilkesiyle TUTARLI).
**Kesin ilke:** Birleştirme SESSİZCE veri KAYBETMEZ — `supporting_
evidence` HER İKİ kaynağın ratio-seviyeli kanıtını da İÇERİR.

### 14.1 BANKING_READINESS ↔ fonksiyonel kategori dedup (`merge_group` ile)

`BANKING_FLAG_TO_RATIO_OVERLAP` registry'si (Bölüm 8.3) HER banking_lens
flag'i AYNI temel zayıflığı paylaşan fonksiyonel kategori kuralının
`merge_group` değeriyle EŞLER — Bölüm 20a'nın tam rule envanterinde HER
BANKING_READINESS kuralı ve KARŞILIK GELEN fonksiyonel kural AYNI
`merge_group` DEĞERİNİ TAŞIR (ör. `MG_WEAK_PROFIT_MARGIN`,
`MG_HIGH_LEVERAGE`, `MG_LIQUIDITY_STRAIN`, `MG_DEBT_SERVICE_STRESS`,
`MG_WORKING_CAPITAL_STRAIN`, `MG_DEBT_FUNDED_GROWTH`) — Bölüm 20a'daki
her kuralın `merge_group` sütununa BAKILARAK doğrulanabilir, AYRI bir
eşleme tablosu GEREKMEZ (registry'nin KENDİSİ tek doğruluk kaynağıdır).

**Birleşen item'ın `category`'si** fonksiyonel kategoridir (BANKING_
READINESS DEĞİL), ama `disclaimer_scope="banking"` KORUNUR (banking
disclaimer'ı KAYBOLMAZ) ve `triggered_by` içinde `BANKING_LENS_SIGNAL`
kaynağı da yer alır; `result_bucket` de fonksiyonel kuralınkiyle
(FINANCIAL) HİZALANIR.

**Test etkisi:** Bölüm 28 madde 4a — `merge_group` eşleşen bir
BANKING_READINESS/fonksiyonel kategori çiftinin golden-dataset
senaryosunda TEK bir item'a birleştiğinin doğrulanması.

---

## 15. Explainability Yapısı

**REVİZYON NOTU (son onay turu):** `RecommendationItem`, Madde 8/9
gereği TAMAMEN yeniden alan-hizalaması yapılmıştır: `rule_code` →
`recommendation_code`, `action_tr` → `action_steps_tr` (tekil cümle
yerine adım LİSTESİ), `rationale_tr` → `explanation_tr` (Madde 9'un
alan adlandırmasıyla hizalanır), confidence/reliability alanları
(Madde 8) ve `assumptions_tr`/`blocked`/`merge_group`/`underlying_risk_
code`/`mutually_exclusive_group_id` (Madde 4/6/9) EKLENMİŞTİR.

### 15.1 `RecommendationItem` dataclass (TAM, son onay turu)

```python
@dataclass(frozen=True)
class RecommendationItem:
    recommendation_code: str
    category: RecommendationCategory
    result_bucket: ResultBucket                                # Bölüm 12 Aşama 17 için
    severity: RecommendationSeverity                           # Bölüm 9 -- priority'den AYRI eksen
    title_tr: str
    explanation_tr: str
    action_steps_tr: "tuple[str, ...]"                         # ADIM listesi, tekil cümle DEĞİL
    assumptions_tr: "tuple[str, ...]"                          # bu önerinin dayandığı varsayımlar (YENİ)
    priority: RecommendationPriority
    priority_rank: int
    blocked: bool                                              # Madde 4 -- blocking_rules eşleşmesiyle True olabilir
    impact_band: RecommendationImpactBand
    difficulty_band: RecommendationDifficultyBand
    triggered_by: "tuple[str, ...]"                            # RecommendationTriggerSource değerleri, dedup edilmiş
    related_ratio_codes: "tuple[str, ...]"
    supporting_evidence: "tuple[dict[str, Any], ...]"
    conflict_group_id: "str | None"
    conflicting_with: "tuple[str, ...]"                        # recommendation_code'lar
    mutually_exclusive_group_id: "str | None"                  # Madde 9 -- conflict'ten YAPISAL OLARAK AYRI (Bölüm 13.3)
    merge_group: "str | None"                                  # Madde 9
    underlying_risk_code: str                                  # Madde 9 -- motor-bağımsız semantik risk kimliği
    directional_context: "RecommendationDirectionalContext | None"  # Bölüm 19.2, Madde 1
    confidence: Decimal                                        # Madde 8 -- 0-1 aralığı, en fazla 2 ondalık
    reliability: str                                           # Madde 8 -- tetikleyici kanıtın EN KÖTÜ reliability etiketi
    confidence_ceiling: Decimal                                # Madde 8 -- registry'den kopyalanan üst sınır
    coverage: Decimal                                          # Madde 8 -- confidence'tan AYRI alan (kategori coverage)
    provisional: bool                                          # Madde 8 -- herhangi bir kanıt provisional=True ise True
    confidence_basis: str                                      # Madde 8 -- hangi ceiling'in BAĞLAYICI olduğunun kısa etiketi
    evidence_reliabilities: "tuple[str, ...]"                  # Madde 8 -- HAM, birleştirilmemiş liste
    missing_inputs: "tuple[str, ...]"                          # Madde 8 -- bu item için eksik/not_calculable ratio_code'lar
    warnings: "tuple[dict[str, Any], ...]"                     # Madde 8 -- item-seviyesi uyarılar
    disclaimer_tr: str
```

### 15.2 `supporting_evidence` şekli

```python
{
    "ratio_code": "current_ratio",
    "display_name_tr": "Cari Oran",           # RATIO_REGISTRY'den okunur, ikinci bir kopya YAZILMAZ
    "tier": "critical",
    "ratio_value": Decimal("0.62"),
    "reliability": "high",                    # ratio_data["reliability"]'den DOĞRUDAN kopyalanır
    "benchmark_status": "evaluated",
    "source": "credit_score_critical_override",
}
```

Health Score'un `generate_strengths_weaknesses`'ındaki `_format_ratio_
value_tr`/`RATIO_REGISTRY` okuma deseninin AYNISI REUSE edilir.

### 15.4 Confidence modeli — KİLİTLİ (son onay turu, Madde 8)

**KARAR DEĞİŞİKLİĞİ (bağlayıcı, ONAY GEREKTİRMEZ):** Önceki turda
confidence alanının v2'ye ERTELENMESİ kararlaştırılmıştı. **Bu karar
KULLANICI TARAFINDAN AÇIKÇA GERİ ALINMIŞTIR** — confidence modeli ARTIK
v1'İN ZORUNLU bir parçasıdır.

**Nihai model (madde 8.a-h, birebir uygulanır):**

1. **Yalnızca tetikleyici evidence reliability değerleri hesaplama
   TEMELİDİR** — `supporting_evidence[*].reliability`'nin HAM
   listesi (`evidence_reliabilities`).
2. **Health Score/Credit Score final confidence değerleri DOĞRUDAN
   ortalama veya çarpan DEĞİLDİR** — yalnızca dolaylı olarak, ilgili
   evidence'ın (hard-fail/critical-override) KENDİ reliability'si
   üzerinden etki eder.
3. **Rule `confidence_ceiling`i uygulanır** (registry-STATİK üst sınır,
   Bölüm 8.1).
4. **Benchmark provisional/reliability ceiling'i uygulanır** — herhangi
   bir tetikleyici kanıt `provisional=True` taşıyorsa `Decimal("0.75")`
   ceiling.
5. **Coverage ceiling'i uygulanır** — kategori `category_coverage`'a
   göre: `>=0.80` → ceiling yok (1.00), `0.50<=x<0.80` → `0.75`,
   `<0.50` (yalnızca hard-fail-muaf item'lar için mümkün) → `0.50`.
6. **Nihai `confidence`, TÜM uygulanabilir ceiling'lerin (madde 3-5 +
   `RELIABILITY_TO_CONFIDENCE_CEILING` haritasından türeyen evidence
   ceiling'i) EN DÜŞÜĞÜDÜR** — `min()`, ASLA ortalama/çarpım DEĞİL.

```python
RELIABILITY_TO_CONFIDENCE_CEILING: dict[str, Decimal] = {
    "high": Decimal("1.00"),
    "medium": Decimal("0.75"),
    "medium_low": Decimal("0.60"),
    "low": Decimal("0.50"),
    "not_calculable": Decimal("0.00"),
}
```

7. **Sonuç 0-1 aralığında `Decimal`, en fazla 2 ondalık** (`quantize`
   ile yuvarlanır).
8. **Evidence yoksa finansal recommendation HESAPLANAMAZ** (bu durumda
   zaten aday üretilmez, Bölüm 12 Aşama 6/9). **`DATA_QUALITY`
   kategorisi AYRI davranır:** bu kategorideki item'ların confidence'ı
   HER ZAMAN `Decimal("1.00")`, `confidence_basis="data_coverage_fact"`
   — çünkü "bu kategoride veri kapsamı düşük" önermesi KENDİSİ bir
   OLGUDUR, ratio reliability'sine bağlı bir tahmin DEĞİLDİR.

**Kesin ilke:** `confidence` ve `coverage` AYRI alanlardır — `coverage`
kategori-seviyesi veri YETERLİLİĞİNİ, `confidence` ise BU ÖZEL item'ın
GÜVENİLİRLİĞİNİ ifade eder; biri diğerinin GİRDİSİ olabilir (madde 5)
ama AYNI ŞEY DEĞİLDİR ve İKİSİ DE ayrı ayrı raporlanır.

### 15.3 Disclaimer metinleri

```python
RECOMMENDATION_DISCLAIMER_TR = (
    "Bu öneriler platformun içsel, heuristik göstergelerine dayanır -- "
    "profesyonel mali/hukuki/vergi danışmanlığı YERİNE GEÇMEZ ve resmî "
    "bir tavsiye niteliği TAŞIMAZ. Nihai karar şirketinizin kendi mali "
    "danışmanına AİTTİR."
)

RECOMMENDATION_BANKING_DISCLAIMER_TR = (
    "Bu öneri bir kredi limiti, tahsis tutarı veya banka onayı GARANTİ "
    "ETMEZ -- yalnızca bankayla görüşme öncesinde hangi konuların "
    "hazırlanmasının faydalı olabileceğine dair niteliksel bir "
    "işarettir."
)
```

`disclaimer_scope="general"` kurallar `RECOMMENDATION_DISCLAIMER_TR`,
`"banking"` kurallar İKİSİNİ BİRDEN (`RECOMMENDATION_DISCLAIMER_TR + "
" + RECOMMENDATION_BANKING_DISCLAIMER_TR`) taşır. Marka adı hardcode
EDİLMEMİŞTİR (Bölüm 2.1 madde 12).

---

## 16. Versioning ve Uyumluluk Politikası — KİLİTLİ (son onay turu, Madde 7)

**SEKİZ bağımsız versiyon ekseni (değişmedi):**

- `recommendation_schema_version` — `RecommendationResult`'ın JSON
  ŞEKLİ değiştiğinde yükseltilir.
- `recommendation_model_version` — `RECOMMENDATION_RULES`/öncelik-etki-
  zorluk bantları/çakışma çiftleri/**`RECOMMENDATION_INPUT_
  COMPATIBILITY` politikası** değiştiğinde yükseltilir (Madde 7'nin
  bağlayıcı kuralı: uyumluluk politikası değişikliği MODEL version artışı
  gerektirir; `RecommendationResult` dataclass ŞEKLİ değişirse SCHEMA
  version artar — bu ikisi KARIŞTIRILMAZ).
- `health_score_schema_version`/`health_score_model_version` — Health
  Score'dan GEÇİRİLİR (redefine EDİLMEZ).
- `credit_score_schema_version`/`credit_score_model_version` — Credit
  Score'dan GEÇİRİLİR.
- `benchmark_registry_version`/`ratio_registry_version` — ikisinden de
  GEÇİRİLİR.

### 16.1 `RECOMMENDATION_INPUT_COMPATIBILITY` — merkezi, immutable politika

```python
RECOMMENDATION_INPUT_COMPATIBILITY: "dict[str, frozenset[str]]" = {
    "health_score_schema_versions": frozenset({...}),   # implementasyonda doldurulur
    "credit_score_schema_versions": frozenset({...}),
    "ratio_registry_versions": frozenset({...}),
    "benchmark_registry_versions": frozenset({...}),
}
```

Bu yapı, önceki turdaki `SUPPORTED_HEALTH_SCORE_SCHEMA_VERSIONS`/
`SUPPORTED_CREDIT_SCORE_SCHEMA_VERSIONS` sabitlerinin YERİNE geçer —
TEK, merkezi, `frozenset` (immutable) bir sözlükte TOPLANMIŞTIR.

### 16.2 Nihai davranış (kesin, üç seviyeli)

1. **`health_score_schema_versions`/`credit_score_schema_versions`
   desteklenmiyorsa (şema OKUNAMAZ seviyede uyumsuz):**
   `status = SCHEMA_INCOMPATIBLE`. **Hiçbir recommendation üretilmez —
   ne finansal, ne banking/data-quality.** Yalnızca yapılandırılmış bir
   `SCHEMA_VERSION_UNSUPPORTED` uyarısı VE hangi alanın/hangi versiyonun
   beklenip hangisinin alındığı bilgisi döner. Pipeline Aşama 1'de
   (Bölüm 12) DURUR.
2. **`ratio_registry_versions`/`benchmark_registry_versions`
   desteklenmiyor AMA şema OKUNABİLİYORSA:** `status = VERSION_
   MISMATCH`. **Finansal öneriler VARSAYILAN OLARAK BASTIRILIR** —
   yalnızca `DATA_QUALITY` kategorisi önerileri (ve `data_gap_
   disclosures` passthrough'u) üretilebilir; finansal/banking_readiness
   önerileri ÜRETİLMEZ. Zorunlu bir `RATIO_OR_BENCHMARK_VERSION_
   UNSUPPORTED` uyarısı döner.
3. **Yalnızca `recommendation_model_version` (VEYA Health/Credit
   Score'un KENDİ model_version'ları) FARKLIYSA, şema UYUMLUYSA:**
   hesaplama NORMAL şekilde devam eder (`COMPUTED`/`NO_RECOMMENDATIONS_
   TRIGGERED`/`INSUFFICIENT_DATA` her zamanki gibi belirlenir), yalnızca
   bir `MODEL_VERSION_MISMATCH` uyarısı EKLENİR (engelleyici DEĞİLDİR).

`RecommendationComputationStatus` bu nedenle **BEŞ** değere çıkar (Bölüm
6.2, güncellenmiştir): `COMPUTED`, `NO_RECOMMENDATIONS_TRIGGERED`,
`INSUFFICIENT_DATA`, `SCHEMA_INCOMPATIBLE`, `VERSION_MISMATCH`.

---

## 17. Override Mimarisi

Health/Credit Score'un `tenant > industry > company_size > global`
çözümleme SIRASIYLA AYNI desen — v1'de yalnızca `global` DOLU:

```python
def resolve_recommendation_category_weights(
    *, industry_code=None, company_size_bucket=None, tenant_id=None,
) -> RecommendationCategoryWeightProfile: ...
```

Gerçek veri KAYDEDİLMEZ (Bölüm 2.1 madde 13). `category_weight_profile_
used` HER ZAMAN `"global"` döner (v1).

---

## 18. Recommendation Kategorileri (8) — KİLİTLİ (son onay turu, Madde 5)

**KİLİTLİ KARAR:** `WORKING_CAPITAL`, `LIQUIDITY`'den KESİN OLARAK AYRI
bir kategori olarak KORUNUR. Nihai taksonomi **SEKİZ** kategoridir (önceki
turun 7'sine `DATA_QUALITY` eklenmiştir — Madde 8/3'ün getirdiği gerçek,
aksiyon üretebilen veri-kalitesi önerileri artık kendi kategorisine
sahiptir, önceden yalnızca passthrough'du):

| Kategori | Kapsam | Health/Credit Score'daki karşılık |
|---|---|---|
| `LIQUIDITY` | Bilanço-anı ödeme gücü/likit varlık yeterliliği | Health/Credit `liquidity` (birebir) |
| `WORKING_CAPITAL` | Operasyonel nakit döngüsü süreçleri | Health/Credit `activity`'nin bir alt kümesi |
| `LEVERAGE` | Sermaye yapısı + borç servisi | Health `leverage`, Credit `leverage`+`debt_service_capacity` |
| `PROFITABILITY` | Kârlılık marjları + verimlilik (eski `efficiency`) | Health `profitability`+`efficiency`, Credit `profitability` |
| `ACTIVITY` | Genel varlık/sabit kıymet operasyonel verimliliği (envanter/alacak/tedarikçi devri HARİÇ) | Health/Credit `activity`'nin geri kalanı |
| `GROWTH` | Satış/kâr/varlık/özkaynak büyüme oranları | Health/Credit `growth` |
| `BANKING_READINESS` | Credit Score `BankingLensSignals`'ından türeyen banka-hazırlığı önerileri | Credit Score'a özgü |
| `DATA_QUALITY` | Kategori coverage boşlukları + Credit Score `data_gap_disclosures` — AKSİYON üretebilen veri-kalitesi önerileri (YENİ, Madde 3/8) | Health/Credit Score'un coverage/data-gap kavramlarının aksiyon karşılığı |

**`LIQUIDITY` yalnızca KISA VADELİ ödeme gücü ve likit varlık
yeterliliğine odaklanır** (bilanço-anı oranlar); **`WORKING_CAPITAL`**
OPERASYONEL SÜREÇ aksiyonlarını (tahsilat sıklığı, stok politikası,
ödeme vadesi müzakeresi) kapsar; **`ACTIVITY`** ise YALNIZCA genel
varlık/sabit-kıymet operasyonel verimlilik sinyallerine odaklanır
(envanter/alacak/tedarikçi devri `WORKING_CAPITAL`'a taşınmıştır). Bu
üçlü ayrım KİLİTLENMİŞTİR.

### 18.1 Gerçek 48 benchmark sinyalinin kategorilere dağılımı (BENCHMARK_REGISTRY'nin gerçek içeriğinden türetilmiştir)

| Kategori | Sinyal sayısı | `ratio_code` listesi |
|---|---|---|
| `LIQUIDITY` | 6 | `current_ratio`, `working_capital_ratio`, `quick_ratio`, `cash_ratio`, `defensive_interval_ratio`, `working_capital_to_total_assets` |
| `WORKING_CAPITAL` | 8 | `days_sales_outstanding`, `receivables_turnover`, `days_inventory_outstanding`, `inventory_turnover`, `days_payables_outstanding`, `payables_turnover`, `cash_conversion_cycle`, `working_capital_turnover` |
| `LEVERAGE` | 9 | `debt_ratio`, `equity_ratio`, `debt_to_equity`, `long_term_debt_to_equity`, `short_term_debt_ratio`, `financial_leverage_multiplier`, `interest_coverage_ratio`, `ebitda_coverage_ratio`, `debt_to_ebitda` |
| `PROFITABILITY` | 17 | `gross_profit_margin`, `operating_profit_margin`, `net_profit_margin`, `ebit_margin`, `ebitda_margin`, `pretax_profit_margin`, `return_on_capital_employed`, `effective_tax_rate`, `return_on_invested_capital`, `return_on_assets`, `return_on_equity`, `operating_expense_ratio`, `cost_of_sales_ratio`, `overhead_ratio`, `ebit_to_opex`, `non_operating_income_dependency`, `financing_expense_to_sales` |
| `ACTIVITY` | 2 | `asset_turnover`, `fixed_asset_turnover` |
| `GROWTH` | 6 | `sales_growth`, `gross_profit_growth`, `ebitda_growth`, `net_profit_growth`, `total_assets_growth`, `equity_growth` |
| **TOPLAM (benchmark sinyalleri)** | **48** | (BENCHMARK_REGISTRY'nin TAMAMI — doğrulama: 6+8+9+17+2+6=48) |
| `BANKING_READINESS` | 6 (benchmark değil, `BankingLensSignals.flags`) | `SHORT_TERM_LIQUIDITY_STRAIN`, `HIGH_LEVERAGE`, `DEBT_SERVICE_STRESS`, `WEAK_PROFIT_BUFFER`, `WORKING_CAPITAL_STRAIN`, `DEBT_FUNDED_GROWTH` |
| `DATA_QUALITY` | 4 (benchmark değil, `data_gap_disclosures`) + 6 (kategori coverage boşluğu, her fonksiyonel kategori için 1) | `FORWARD_CASH_FLOW`, `COLLATERAL`, `PAYMENT_HISTORY`, `MANAGEMENT_QUALITY` + `LIQUIDITY`/`WORKING_CAPITAL`/`LEVERAGE`/`PROFITABILITY`/`ACTIVITY`/`GROWTH` coverage-boşluğu |

Bu tablo, Bölüm 8.2'nin registry-doğrulama mantığının GİRDİSİDİR: bir
kuralın `related_ratio_codes`'u bu tablodaki 48 kod DIŞINDA bir değer
İÇEREMEZ (zaten mevcut kural, Madde 5 ile GÜÇLENDİRİLMEKTEDİR — artık
kategori ATAMASI da bu tabloyla ÇAPRAZ DOĞRULANIR: bir kuralın
`category`'si, `related_ratio_codes`'unun bu tablodaki kategorisiyle
UYUŞMUYORSA kayıt REDDEDİLİR).

**`PROFITABILITY`'nin `efficiency`'yi yutma gerekçesi (DEĞİŞMEDİ):**
Credit Score Bölüm 5.1'deki AYNI gerekçe — `efficiency` oranları
NİHAİ olarak hep "kârlılığı iyileştirme" aksiyonuna çıkar.

---

## 19. Yönsel Eşik Bağlamı (Directional Threshold Context) — KİLİTLİ (son onay turu, Madde 1)

**KİLİTLİ KARAR (ONAY GEREKTİRMEZ):** Bu bölüm ARTIK açık bir tasarım
kararı DEĞİLDİR. "Simülasyon"/"what-if"/"eşik yakınlığı" gibi önceki
turların dil/kapsam belirsizlikleri TAMAMEN KALDIRILMIŞTIR. Nihai
davranış: **hiçbir gerçek simülasyon, hiçbir sayısal hedef büyüklüğü,
hiçbir oran farkı HESAPLANMAZ.** Yerine, TAMAMEN NİTELİKSEL, yapılandırılmış
bir `RecommendationDirectionalContext` nesnesi üretilir.

### 19.1 Gerilimin tanımı (değişmedi, tarihsel referans)

Klasik bir "What-if" özelliği **matematiksel olarak** `analyze_
financial_ratios`/`evaluate_benchmarks`/`compute_financial_health_
score`'un YENİDEN, DEĞİŞTİRİLMİŞ girdilerle ÇALIŞTIRILMASINI GEREKTİRİR
— bu, Bölüm 2.1'de KESİN OLARAK YASAKLANAN "hiçbir oranı yeniden
hesaplamayacak/hiçbir score üretmeyecek" ilkesini DOĞRUDAN İHLAL EDER
— bu yüzden v1 KESİNLİKLE gerçek simülasyon İÇERMEZ (bkz. 19.3).

### 19.2 Nihai yapı: `RecommendationDirectionalContext` — TAMAMEN NİTELİKSEL

```python
@dataclass(frozen=True)
class RecommendationDirectionalContext:
    ratio_code: str
    current_tier: str                    # ör. "weak" -- ZATEN HESAPLANMIŞ, motor çıktısından okunur
    ideal_direction: str                  # "higher_is_better" | "lower_is_better" | "range_is_better" -- BENCHMARK_REGISTRY'den DOĞRUDAN okunur
    improvement_direction_tr: str         # SABİT, registry-önceden-tanımlı NİTELİKSEL cümle (aşağıya bkz.) -- SAYI İÇERMEZ
    next_better_tier_name: "str | None"   # ör. "average" -- YALNIZCA bant İSMİ, eşik DEĞERİ DEĞİL; en iyi banttaysa None
```

**Alanların KESİN sınırları:**

- `current_tier`/`ideal_direction`: `evaluate_benchmarks()`'in ZATEN
  ÜRETTİĞİ, motor tarafından hesaplanmış çıktının BİREBİR okunmasıdır
  (Bölüm 1.2) — YENİDEN HESAPLAMA DEĞİLDİR.
- `improvement_direction_tr`: YALNIZCA ÜÇ sabit, registry-STATİK
  metinden biri (`ideal_direction`'a göre ÖNCEDEN yazılmış, runtime'da
  FORMATLANMAZ):
  - `HIGHER_IS_BETTER` → "Bu göstergenin YÜKSELMESİ istenen yöndür."
  - `LOWER_IS_BETTER` → "Bu göstergenin DÜŞMESİ istenen yöndür."
  - `RANGE_IS_BETTER` → "Bu gösterge belirli bir ARALIKTA kalmalıdır."
- `next_better_tier_name`: `BENCHMARK_REGISTRY`'nin bant SIRALAMASINDAN
  (critical < weak < average < good < excellent, kategoriye göre
  mevcut bantlar değişebilir) bir sonraki bandın YALNIZCA İSMİ —
  **HİÇBİR sayısal eşik değeri, HİÇBİR fark, HİÇBİR "kaç birim
  gerekli" bilgisi TAŞIMAZ.** Zaten en iyi banttaysa `None`.

**KESİNLİKLE ÜRETİLMEYECEKLER (Madde 1'in bağlayıcı yasağı):**
- sayısal eşik farkı,
- hedef oran değeri,
- operasyonel aksiyon miktarı ("stokları %20 azaltın" tarzı),
- Health Score veya Credit Score senaryosu/projeksiyonu,
- "skor şu kadar artar" tarzı HERHANGİ bir ifade.

Bu alan `RecommendationItem`'a `directional_context: "RecommendationDirectionalContext | None"`
olarak eklenir (önceki turun `threshold_proximity_note_tr` serbest-metin
alanının YERİNE geçer — serbest metin, yapılandırılmış, sabit-alanlı bir
nesneyle DEĞİŞTİRİLMİŞTİR; bu, hem test edilebilirliği hem de
"hiçbir sayı sızmıyor" garantisinin statik olarak doğrulanabilirliğini
ARTIRIR).

### 19.3 KAPSAM DIŞI bırakılan (gerçek) What-if simülasyonu — gelecek milestone hook'u

Aşağıdakiler v1'de KESİNLİKLE YOKTUR, yalnızca isim olarak
KAYDEDİLMİŞTİR (Health/Credit Score'un `industry_code`/
`company_size_bucket` hook desenindeki AYNI "iskelet bile eklenmez"
disiplini):

- Kullanıcının bir oranı MANUEL DEĞİŞTİRİP skorun NASIL DEĞİŞECEĞİNİ
  GÖRMESİ (gerçek "what-if" SİMÜLASYONU — bu kelime BİLİNÇLİ olarak
  YALNIZCA bu, v1 kapsamı DIŞINDA bırakılan madde için KULLANILIR, 19.2
  için ARTIK KULLANILMAZ) — bu, AYRI bir gelecek milestone'un
  (muhtemelen `compute_financial_health_score`/`compute_credit_score`'u
  DEĞİŞTİRİLMİŞ bir `ratio_result_json` KOPYASIYLA, ORİJİNAL sonucu
  ETKİLEMEDEN yeniden çağıran, AÇIKÇA "simülasyon modu" olarak
  işaretlenmiş YENİ bir fonksiyon gerektirecek) konusudur.

**Bu, Bölüm 33'te kullanıcı onayı gerektiren AÇIK bir tasarım kararı
olarak işaretlenmiştir** — önerilen karar: **19.2'deki niteliksel eşik-
yakınlığı ifadesi v1 kapsamına ALINSIN, 19.3'teki gerçek simülasyon
KESİNLİKLE v1 DIŞINDA bırakılsın.**

---

## 20a. Tam Rule Envanteri — KİLİTLİ (son onay turu, Madde 9), 39 kural, PLACEHOLDER YOK

**Ortak alanlar (tekrarı önlemek için burada bir kez belirtilir, HER
kural için AYNI değeri taşır):** `model_version_introduced="1.0.0"`,
`deprecated_since=None`, `replacement_recommendation_code=None`,
`prerequisite_rules=()`, `blocking_rules=()` (Bölüm 8.1'in dürüstlük
notu: mekanizma HAZIR, v1'de HİÇBİRİ DOLU DEĞİL), `disclaimer_tr=
RECOMMENDATION_DISCLAIMER_TR` (+ `RECOMMENDATION_BANKING_DISCLAIMER_TR`
yalnızca `disclaimer_scope="banking"` olanlarda), `conflict_group=None`
(v1'de `RECOMMENDATION_CONFLICT_PAIRS` boş, Bölüm 13.2), `mutually_
exclusive_group=None` (yalnızca #3/#4 hariç, aşağıda belirtilir).

Registry referans bütünlüğü: bu envanterdeki 39 `recommendation_code`,
Bölüm 13/14'teki TÜM referansların (mutually_exclusive_group, merge_
group) TEK kaynağıdır — başka hiçbir bölümde FARKLI bir kod
İCAT EDİLMEMİŞTİR.

### WORKING_CAPITAL (6 kural)

**1. `WC_REDUCE_RECEIVABLES_DAYS`**
category=WORKING_CAPITAL, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=LOW_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="days_sales_outstanding", tier_in=("weak","critical")),)
related_ratio_codes=("days_sales_outstanding",); merge_group=None; evidence_group="working_capital_cycle_days"; underlying_risk_code="RECEIVABLES_COLLECTION_DELAY_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Alacak Tahsilat Süresini Kısaltın"
explanation_tr="Alacaklarınızın nakde dönüşüm süresi, kayıtlı karşılaştırma bandına göre uzun görünmektedir; bu durum işletme sermayesi üzerinde baskı yaratabilir."
action_steps_tr=("Tahsilat sıklığını ve vade takibini gözden geçirin.", "Erken ödeme teşviki gibi seçenekleri değerlendirin.")
assumptions_tr=("Değerlendirme mevcut dönem finansal tablo verisine dayanır; sektöre özgü ödeme alışkanlıkları ayrıca dikkate alınmamıştır.",)

**2. `WC_EXTEND_PAYABLES_DAYS`**
category=WORKING_CAPITAL, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=LOW, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="days_payables_outstanding", tier_in=("weak",)),)
related_ratio_codes=("days_payables_outstanding",); merge_group=None; evidence_group="working_capital_cycle_days"; underlying_risk_code="SUPPLIER_FINANCING_UNDERUSE_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Tedarikçi Ödeme Vadelerini Gözden Geçirin"
explanation_tr="Tedarikçi ödeme vadeniz, kayıtlı karşılaştırma bandının erken-ödeme ucuna yakın görünmektedir; bu durum tedarikçi finansmanından yeterince yararlanılmadığına işaret edebilir."
action_steps_tr=("Tedarikçilerle ödeme vadesi koşullarını yeniden görüşmeyi değerlendirin.",)
assumptions_tr=("Bant sınıflandırması RANGE_IS_BETTER metodolojisine dayanır; erken/geç ödeme ayrımı bu tasarımda ayrıştırılmamıştır.",)

**3. `WC_REDUCE_INVENTORY_DAYS`**
category=WORKING_CAPITAL, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="days_inventory_outstanding", tier_in=("weak","critical")),)
related_ratio_codes=("days_inventory_outstanding",); merge_group=None; evidence_group="working_capital_cycle_days"; underlying_risk_code="SLOW_INVENTORY_TURNOVER_RISK"
mutually_exclusive_group="MEG_INVENTORY_LEVEL" (Bölüm 13.3)
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Stok Devir Hızını İyileştirin"
explanation_tr="Envanterinizin elde tutulma süresi, kayıtlı karşılaştırma bandına göre uzun görünmektedir."
action_steps_tr=("Stok seviyelerini ve sipariş sıklığını gözden geçirin.", "Yavaş hareket eden kalemleri ayrıca inceleyin.")
assumptions_tr=("Değerlendirme yalnızca dönem-sonu envanter verisine dayanır; mevsimsellik ayrıştırılmamıştır.",)

**4. `WC_MAINTAIN_INVENTORY_SAFETY_BUFFER`**
category=WORKING_CAPITAL, result_bucket=FINANCIAL, base_priority=LOW, severity=LOW, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="days_inventory_outstanding", tier_in=("good","excellent")),)
related_ratio_codes=("days_inventory_outstanding",); merge_group=None; evidence_group="working_capital_cycle_days"; underlying_risk_code="STOCKOUT_RISK"
mutually_exclusive_group="MEG_INVENTORY_LEVEL" (Bölüm 13.3 — #3 ile birlikte TEK grup)
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Stok Güvenlik Tamponunu Koruyun"
explanation_tr="Envanter seviyeniz kayıtlı karşılaştırma bandına göre oldukça yalın görünmektedir; bu durum tedarik kesintisi riskini artırabilir."
action_steps_tr=("Kritik girdiler için minimum güvenlik stoku politikasını gözden geçirin.",)
assumptions_tr=("Bu öneri talep/tedarik değişkenliği verisine dayanmaz; yalnızca stok günü göstergesine dayanır.",)

**5. `WC_ADDRESS_CASH_CONVERSION_CYCLE`**
category=WORKING_CAPITAL, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=HIGH, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=ANY_CONDITION, trigger_mode=any, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="cash_conversion_cycle", tier_in=("weak","critical")), EvidenceRule(critical_override_ratio_code="cash_conversion_cycle"))
related_ratio_codes=("cash_conversion_cycle",); merge_group="MG_WORKING_CAPITAL_STRAIN"; evidence_group="working_capital_cycle_days"; underlying_risk_code="CASH_CONVERSION_CYCLE_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Nakit Dönüşüm Süresini Kısaltacak Bir Plan Oluşturun"
explanation_tr="Nakit dönüşüm süreniz kayıtlı karşılaştırma bandına göre uzun görünmektedir; bu durum işletme sermayesi ihtiyacınızı artırabilir."
action_steps_tr=("Tahsilat, stok ve ödeme süreçlerini birlikte değerlendiren bir iyileştirme planı hazırlayın.",)
assumptions_tr=("Tek dönem verisine dayanır; yapısal mı geçici mi olduğu ayrıca değerlendirilmelidir.",)

**6. `WC_REVIEW_WORKING_CAPITAL_TURNOVER`**
category=WORKING_CAPITAL, result_bucket=FINANCIAL, base_priority=LOW, severity=LOW, impact_band=LOW, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="working_capital_turnover", tier_in=("weak","critical")),)
related_ratio_codes=("working_capital_turnover",); merge_group=None; evidence_group="working_capital_cycle_days"; underlying_risk_code="WORKING_CAPITAL_EFFICIENCY_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="İşletme Sermayesi Verimliliğini Gözden Geçirin"
explanation_tr="İşletme sermayesi devir hızınız kayıtlı karşılaştırma bandına göre düşük görünmektedir."
action_steps_tr=("Satış hacmi ile işletme sermayesi kullanımı arasındaki ilişkiyi gözden geçirin.",)
assumptions_tr=("Diğer working_capital göstergeleriyle (DSO/DPO/DIO/CCC) birlikte yorumlanması önerilir.",)

*(REVİZYON NOTU: `working_capital_turnover` Bölüm 18.1 ile TUTARLI şekilde
YALNIZCA bu kategoridedir — eski `ACT_REVIEW_WORKING_CAPITAL_TURNOVER`
KALDIRILMIŞTIR, ACTIVITY artık yalnızca #19-20'yi içerir.)*

### LIQUIDITY (4 kural)

**7. `LIQ_IMPROVE_CURRENT_RATIO`**
category=LIQUIDITY, result_bucket=FINANCIAL, base_priority=HIGH, severity=HIGH, impact_band=HIGH, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=ANY_CONDITION, trigger_mode=any, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)), EvidenceRule(critical_override_ratio_code="current_ratio"))
related_ratio_codes=("current_ratio",); merge_group="MG_LIQUIDITY_STRAIN"; evidence_group="liquidity_balance_sheet_family"; underlying_risk_code="SHORT_TERM_LIQUIDITY_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Cari Oranınızı İyileştirin"
explanation_tr="Kısa vadeli varlıklarınızın kısa vadeli yükümlülüklerinizi karşılama düzeyi kayıtlı karşılaştırma bandına göre zayıf görünmektedir."
action_steps_tr=("Kısa vadeli finansman yapınızı ve nakit yönetimi politikanızı gözden geçirin.",)
assumptions_tr=("Bilanço-anı bir orandır; dönem içi dalgalanmalar yansımayabilir.",)

**8. `LIQ_IMPROVE_QUICK_RATIO`**
category=LIQUIDITY, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="quick_ratio", tier_in=("weak","critical")),)
related_ratio_codes=("quick_ratio",); merge_group=None; evidence_group="liquidity_balance_sheet_family"; underlying_risk_code="LIQUID_ASSET_ADEQUACY_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Likit Varlık Yeterliliğinizi Gözden Geçirin"
explanation_tr="Stok hariç likit varlıklarınızın kısa vadeli yükümlülükleri karşılama düzeyi zayıf görünmektedir."
action_steps_tr=("Nakit ve nakit benzeri varlık yönetiminizi gözden geçirin.",)
assumptions_tr=("quick_ratio hesaplaması platformun mevcut formülüne dayanır.",)

**9. `LIQ_BUILD_CASH_BUFFER`**
category=LIQUIDITY, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="cash_ratio", tier_in=("critical",)),)
related_ratio_codes=("cash_ratio",); merge_group=None; evidence_group="liquidity_balance_sheet_family"; underlying_risk_code="CASH_BUFFER_ADEQUACY_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Nakit Tamponu Oluşturun"
explanation_tr="Nakit ve nakit benzeri varlıklarınız kısa vadeli yükümlülüklerinize göre kritik seviyede düşük görünmektedir."
action_steps_tr=("Asgari nakit tamponu politikası oluşturmayı değerlendirin.",)
assumptions_tr=("Dönem-sonu bakiyeye dayanır, günlük nakit pozisyonunu yansıtmayabilir.",)

**10. `LIQ_REVIEW_DEFENSIVE_INTERVAL`**
category=LIQUIDITY, result_bucket=FINANCIAL, base_priority=LOW, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="defensive_interval_ratio", tier_in=("critical",)),)
related_ratio_codes=("defensive_interval_ratio",); merge_group=None; evidence_group="liquidity_balance_sheet_family"; underlying_risk_code="DEFENSIVE_INTERVAL_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Savunma Süresi Göstergenizi Gözden Geçirin"
explanation_tr="Mevcut likit varlıklarınızla operasyonel giderlerinizi karşılayabileceğiniz süre kısa görünmektedir."
action_steps_tr=("Operasyonel gider planlaması ile likidite yönetiminizi birlikte gözden geçirin.",)
assumptions_tr=("Geçmiş dönem operasyonel gider ortalamasına dayanır.",)

### LEVERAGE (4 kural)

**11. `LEV_STRENGTHEN_EQUITY_BASE`**
category=LEVERAGE, result_bucket=FINANCIAL, base_priority=CRITICAL, severity=CRITICAL, impact_band=HIGH, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=HARD_FAIL_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(hard_fail_code="NEGATIVE_EQUITY"),)
related_ratio_codes=("equity_ratio","debt_to_equity"); merge_group="MG_HIGH_LEVERAGE"; evidence_group="capital_structure_family"; underlying_risk_code="OVERLEVERAGE_RISK"
confidence_ceiling=0.75; coverage_policy=exempt_hard_fail; disclaimer_scope=general
title_tr="Sermaye Yapınızı Güçlendirin"
explanation_tr="Özkaynak yapınızda platformun hard-fail eşiğini aşan ciddi bir zayıflık tespit edilmiştir."
action_steps_tr=("Sermaye yapısı güçlendirme seçeneklerini (özkaynak enjeksiyonu, borç yeniden yapılandırması gibi) mali danışmanınızla değerlendirin.",)
assumptions_tr=("Bu değerlendirme platformun içsel hard-fail eşiğine dayanır; hukuki/vergisel sonuçlar ayrıca değerlendirilmelidir.",)

**12. `LEV_IMPROVE_INTEREST_COVERAGE`**
category=LEVERAGE, result_bucket=FINANCIAL, base_priority=CRITICAL, severity=CRITICAL, impact_band=HIGH, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=HARD_FAIL_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(hard_fail_code="SEVERE_DEBT_SERVICE_SHORTFALL"),)
related_ratio_codes=("interest_coverage_ratio",); merge_group="MG_DEBT_SERVICE_STRESS"; evidence_group="debt_service_family"; underlying_risk_code="DEBT_SERVICE_RISK"
confidence_ceiling=0.75; coverage_policy=exempt_hard_fail; disclaimer_scope=general
title_tr="Borç Servisi Kapasitenizi Güçlendirin"
explanation_tr="Faiz karşılama kapasitenizde platformun hard-fail eşiğini aşan ciddi bir zayıflık tespit edilmiştir."
action_steps_tr=("Borç yeniden yapılandırma veya nakit akışı iyileştirme seçeneklerini değerlendirin.",)
assumptions_tr=("Bu değerlendirme platformun içsel hard-fail eşiğine dayanır.",)

**13. `LEV_REVIEW_DEBT_MATURITY_MIX`**
category=LEVERAGE, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="short_term_debt_ratio", tier_in=("critical",)),)
related_ratio_codes=("short_term_debt_ratio",); merge_group=None; evidence_group="capital_structure_family"; underlying_risk_code="DEBT_MATURITY_CONCENTRATION_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Borç Vade Dağılımınızı Gözden Geçirin"
explanation_tr="Kısa vadeli borç yükünüzün toplam borç içindeki payı yüksek görünmektedir."
action_steps_tr=("Borç vade yapınızı uzun vadeye kaydırma seçeneklerini değerlendirin.",)
assumptions_tr=("Dönem-sonu bilanço verisine dayanır.",)

**14. `LEV_MONITOR_DEBT_TO_EBITDA`**
category=LEVERAGE, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="debt_to_ebitda", tier_in=("weak","critical")),)
related_ratio_codes=("debt_to_ebitda",); merge_group=None; evidence_group="debt_service_family"; underlying_risk_code="DEBT_TO_EARNINGS_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Borç/FAVÖK Oranınızı İzleyin"
explanation_tr="Borcunuzun faaliyet kârlılığınıza oranı kayıtlı karşılaştırma bandına göre yüksek görünmektedir."
action_steps_tr=("Borçlanma hızınızı faaliyet kârlılığı büyümenizle karşılaştırarak izleyin.",)
assumptions_tr=("FAVÖK hesaplaması platformun mevcut formülüne dayanır.",)

### PROFITABILITY (4 kural)

**15. `PROF_IMPROVE_NET_MARGIN`**
category=PROFITABILITY, result_bucket=FINANCIAL, base_priority=HIGH, severity=HIGH, impact_band=HIGH, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=ANY_CONDITION, trigger_mode=any, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="net_profit_margin", tier_in=("critical",)), EvidenceRule(critical_override_ratio_code="net_profit_margin"))
related_ratio_codes=("net_profit_margin",); merge_group="MG_WEAK_PROFIT_MARGIN"; evidence_group="profitability_margin_family"; underlying_risk_code="WEAK_PROFITABILITY_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Net Kâr Marjınızı İyileştirin"
explanation_tr="Net kâr marjınız kayıtlı karşılaştırma bandına göre zayıf görünmektedir."
action_steps_tr=("Maliyet yapınızı ve fiyatlandırma politikanızı birlikte gözden geçirin.",)
assumptions_tr=("Tek dönem verisine dayanır; mevsimsellik/tek seferlik kalemler ayrıştırılmamıştır.",)

**16. `PROF_REVIEW_COST_OF_SALES`**
category=PROFITABILITY, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ANY_CONDITION, trigger_mode=any, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="cost_of_sales_ratio", tier_in=("weak","critical")), EvidenceRule(ratio_code="gross_profit_margin", tier_in=("weak","critical")))
related_ratio_codes=("cost_of_sales_ratio","gross_profit_margin"); merge_group=None; evidence_group="profitability_margin_family"; underlying_risk_code="COST_STRUCTURE_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Satışların Maliyeti Yapınızı Gözden Geçirin"
explanation_tr="Satışların maliyetinin satışlara oranı kayıtlı karşılaştırma bandına göre yüksek görünmektedir."
action_steps_tr=("Tedarik/üretim maliyet kalemlerini ayrıştırarak inceleyin.",)
assumptions_tr=("Muhasebe sınıflandırma tutarlılığı varsayılmıştır.",)

**17. `PROF_REVIEW_OPERATING_EXPENSES`**
category=PROFITABILITY, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="operating_expense_ratio", tier_in=("weak","critical")),)
related_ratio_codes=("operating_expense_ratio",); merge_group=None; evidence_group="profitability_margin_family"; underlying_risk_code="OPERATING_EXPENSE_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Operasyonel Giderlerinizi Gözden Geçirin"
explanation_tr="Operasyonel giderlerinizin satışlara oranı kayıtlı karşılaştırma bandına göre yüksek görünmektedir."
action_steps_tr=("Sabit ve değişken gider kalemlerini ayrıştırarak inceleyin.",)
assumptions_tr=("Muhasebe dönemleri arası tutarlılık varsayılmıştır.",)

**18. `PROF_IMPROVE_ASSET_RETURNS`**
category=PROFITABILITY, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=ANY_CONDITION, trigger_mode=any, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="return_on_assets", tier_in=("critical",)), EvidenceRule(ratio_code="return_on_equity", tier_in=("critical",)))
related_ratio_codes=("return_on_assets","return_on_equity"); merge_group=None; evidence_group="profitability_return_family"; underlying_risk_code="CAPITAL_RETURN_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Varlık/Özkaynak Getirinizi İyileştirin"
explanation_tr="Varlıklarınızın veya özkaynağınızın getiri düzeyi kayıtlı karşılaştırma bandına göre zayıf görünmektedir."
action_steps_tr=("Kârlılık ve varlık kullanım verimliliğini birlikte değerlendirin.",)
assumptions_tr=("Dönem-sonu bilanço büyüklükleri kullanılmıştır, ortalama bakiyeler DEĞİL.",)

### ACTIVITY (2 kural)

**19. `ACT_IMPROVE_ASSET_TURNOVER`**
category=ACTIVITY, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="asset_turnover", tier_in=("weak","critical")),)
related_ratio_codes=("asset_turnover",); merge_group=None; evidence_group="asset_efficiency_family"; underlying_risk_code="ASSET_UTILIZATION_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Varlık Devir Hızınızı İyileştirin"
explanation_tr="Toplam varlıklarınızın satış üretme verimliliği kayıtlı karşılaştırma bandına göre düşük görünmektedir."
action_steps_tr=("Az kullanılan varlıkları belirlemek için varlık envanterinizi gözden geçirin.",)
assumptions_tr=("Dönem-sonu toplam varlık büyüklüğü kullanılmıştır.",)

**20. `ACT_IMPROVE_FIXED_ASSET_TURNOVER`**
category=ACTIVITY, result_bucket=FINANCIAL, base_priority=LOW, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="fixed_asset_turnover", tier_in=("critical",)),)
related_ratio_codes=("fixed_asset_turnover",); merge_group=None; evidence_group="asset_efficiency_family"; underlying_risk_code="FIXED_ASSET_UTILIZATION_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Sabit Kıymet Devir Hızınızı Gözden Geçirin"
explanation_tr="Sabit kıymetlerinizin satış üretme verimliliği kayıtlı karşılaştırma bandına göre düşük görünmektedir."
action_steps_tr=("Kullanım oranı düşük sabit kıymetleri gözden geçirin.",)
assumptions_tr=("Amortisman politikası farklılıkları ayrıştırılmamıştır.",)

### GROWTH (3 kural)

**21. `GRW_REVIEW_DEBT_FUNDED_GROWTH`**
category=GROWTH, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=DEBT_FUNDED_GROWTH, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(banking_lens_flag="DEBT_FUNDED_GROWTH"),)
related_ratio_codes=("total_assets_growth",); merge_group="MG_DEBT_FUNDED_GROWTH"; evidence_group="growth_financing_family"; underlying_risk_code="DEBT_FUNDED_EXPANSION_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Borçla Finanse Edilen Büyümeyi Gözden Geçirin"
explanation_tr="Büyümenizin önemli ölçüde borç artışıyla birlikte gerçekleştiğine dair bir sinyal tespit edilmiştir."
action_steps_tr=("Büyüme finansmanınızın kaynak dağılımını (özkaynak/borç) gözden geçirin.",)
assumptions_tr=("Bu sinyal Credit Score'un banking-lens değerlendirmesinden DOĞRUDAN alınır, yeniden hesaplanmaz.",)

**22. `GRW_STABILIZE_SALES_GROWTH`**
category=GROWTH, result_bucket=FINANCIAL, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(ratio_code="sales_growth", tier_in=("critical",)),)
related_ratio_codes=("sales_growth",); merge_group=None; evidence_group="growth_trend_family"; underlying_risk_code="REVENUE_CONTRACTION_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Satış Büyümenizi Stabilize Edin"
explanation_tr="Satış büyümeniz kayıtlı karşılaştırma bandına göre sert bir daralma göstermektedir."
action_steps_tr=("Daralmanın geçici mi yapısal mı olduğunu ayrıştırmak için pazar/müşteri analizini gözden geçirin.",)
assumptions_tr=("Nominal büyüme kullanılmıştır (TÜFE düzeltmesi YOK — Bölüm 1.2'nin bağlayıcı kararı).",)

**23. `GRW_REVIEW_EQUITY_GROWTH_LAG`**
category=GROWTH, result_bucket=FINANCIAL, base_priority=LOW, severity=LOW, impact_band=LOW, difficulty_band=MODERATE_EFFORT
trigger_strategy=ALL_CONDITIONS, trigger_mode=all, minimum_evidence_count=2
evidence_rules=(EvidenceRule(ratio_code="equity_growth", tier_in=("weak","critical")), EvidenceRule(ratio_code="total_assets_growth", tier_in=("average","good","excellent")))
related_ratio_codes=("equity_growth","total_assets_growth"); merge_group=None; evidence_group="growth_trend_family"; underlying_risk_code="EQUITY_GROWTH_LAG_RISK"
confidence_ceiling=0.75; coverage_policy=subject_to_gate; disclaimer_scope=general
title_tr="Özkaynak Büyümesinin Varlık Büyümesine Göre Geride Kalmasını Gözden Geçirin"
explanation_tr="Varlıklarınız büyürken özkaynağınızın aynı hızda büyümediği görülmektedir; bu durum kaldıraç artışına işaret edebilir."
action_steps_tr=("Büyümenin finansman kaynağını (borç vs. özkaynak) gözden geçirin.",)
assumptions_tr=("Yalnızca tier-bazlı karşılaştırma kullanılmıştır (kapalı deklaratif model, Bölüm 8.0); ham büyüme farkı HESAPLANMAMIŞTIR.",)

### BANKING_READINESS (6 kural — Credit Score `BankingLensSignals`'ından birebir türer)

**24. `BANK_PREPARE_LIQUIDITY_NARRATIVE`**
category=BANKING_READINESS, result_bucket=BANKING_READINESS, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=LOW_EFFORT
trigger_strategy=BANKING_FLAG_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(banking_lens_flag="SHORT_TERM_LIQUIDITY_STRAIN"),)
related_ratio_codes=("current_ratio","quick_ratio","cash_ratio"); merge_group="MG_LIQUIDITY_STRAIN"; evidence_group="banking_readiness_family"; underlying_risk_code="SHORT_TERM_LIQUIDITY_RISK"
confidence_ceiling=0.65; coverage_policy=subject_to_gate; disclaimer_scope=banking
title_tr="Banka Görüşmesi İçin Likidite Açıklaması Hazırlayın"
explanation_tr="Kısa vadeli likidite göstergeleriniz, banka değerlendirmesinde dikkat çekebilecek bir zayıflık sinyali taşımaktadır."
action_steps_tr=("Likidite durumunuzu açıklayan kısa bir not hazırlayın.", "Banka görüşmesi öncesinde nakit yönetim planınızı gözden geçirin.")
assumptions_tr=("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir, yeniden hesaplanmaz.",)

**25. `BANK_PREPARE_LEVERAGE_NARRATIVE`**
category=BANKING_READINESS, result_bucket=BANKING_READINESS, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=LOW_EFFORT
trigger_strategy=BANKING_FLAG_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(banking_lens_flag="HIGH_LEVERAGE"),)
related_ratio_codes=("equity_ratio","debt_to_equity"); merge_group="MG_HIGH_LEVERAGE"; evidence_group="banking_readiness_family"; underlying_risk_code="OVERLEVERAGE_RISK"
confidence_ceiling=0.65; coverage_policy=subject_to_gate; disclaimer_scope=banking
title_tr="Kaldıraç Yapınızı Açıklayan Bir Not Hazırlayın"
explanation_tr="Kaldıraç göstergeleriniz banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır."
action_steps_tr=("Sermaye yapınızı ve borç kullanım gerekçenizi açıklayan bir not hazırlayın.",)
assumptions_tr=("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",)

**26. `BANK_DISCUSS_RESTRUCTURING_OPTIONS`**
category=BANKING_READINESS, result_bucket=BANKING_READINESS, base_priority=HIGH, severity=HIGH, impact_band=HIGH, difficulty_band=STRUCTURAL_EFFORT
trigger_strategy=BANKING_FLAG_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(banking_lens_flag="DEBT_SERVICE_STRESS"),)
related_ratio_codes=("interest_coverage_ratio",); merge_group="MG_DEBT_SERVICE_STRESS"; evidence_group="banking_readiness_family"; underlying_risk_code="DEBT_SERVICE_RISK"
confidence_ceiling=0.65; coverage_policy=subject_to_gate; disclaimer_scope=banking
title_tr="Banka İle Yeniden Yapılandırma Seçeneklerini Görüşün"
explanation_tr="Borç servisi kapasitenize ilişkin göstergeler banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır."
action_steps_tr=("Banka ile olası yeniden yapılandırma seçeneklerini görüşmeyi değerlendirin.",)
assumptions_tr=("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",)

**27. `BANK_PREPARE_PROFITABILITY_NARRATIVE`**
category=BANKING_READINESS, result_bucket=BANKING_READINESS, base_priority=LOW, severity=MEDIUM, impact_band=LOW, difficulty_band=LOW_EFFORT
trigger_strategy=BANKING_FLAG_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(banking_lens_flag="WEAK_PROFIT_BUFFER"),)
related_ratio_codes=("net_profit_margin",); merge_group="MG_WEAK_PROFIT_MARGIN"; evidence_group="banking_readiness_family"; underlying_risk_code="WEAK_PROFITABILITY_RISK"
confidence_ceiling=0.65; coverage_policy=subject_to_gate; disclaimer_scope=banking
title_tr="Kârlılık Trendini Açıklayan Bir Not Hazırlayın"
explanation_tr="Kârlılık göstergeleriniz banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır."
action_steps_tr=("Kârlılık trendinizi ve nedenlerini açıklayan bir not hazırlayın.",)
assumptions_tr=("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",)

**28. `BANK_DISCUSS_WORKING_CAPITAL_FACILITY`**
category=BANKING_READINESS, result_bucket=BANKING_READINESS, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=BANKING_FLAG_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(banking_lens_flag="WORKING_CAPITAL_STRAIN"),)
related_ratio_codes=("cash_conversion_cycle",); merge_group="MG_WORKING_CAPITAL_STRAIN"; evidence_group="banking_readiness_family"; underlying_risk_code="CASH_CONVERSION_CYCLE_RISK"
confidence_ceiling=0.65; coverage_policy=subject_to_gate; disclaimer_scope=banking
title_tr="İşletme Sermayesi Kredisi Seçeneklerini Araştırın"
explanation_tr="İşletme sermayesi göstergeleriniz banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır."
action_steps_tr=("İşletme sermayesi finansmanı seçeneklerini araştırmayı değerlendirin.",)
assumptions_tr=("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",)

**29. `BANK_REVIEW_GROWTH_FINANCING_MIX`**
category=BANKING_READINESS, result_bucket=BANKING_READINESS, base_priority=MEDIUM, severity=MEDIUM, impact_band=MEDIUM, difficulty_band=MODERATE_EFFORT
trigger_strategy=BANKING_FLAG_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(banking_lens_flag="DEBT_FUNDED_GROWTH"),)
related_ratio_codes=("total_assets_growth",); merge_group="MG_DEBT_FUNDED_GROWTH"; evidence_group="banking_readiness_family"; underlying_risk_code="DEBT_FUNDED_EXPANSION_RISK"
confidence_ceiling=0.65; coverage_policy=subject_to_gate; disclaimer_scope=banking
title_tr="Büyüme Finansmanı Karışımını Gözden Geçirin"
explanation_tr="Büyümenizin finansman karışımı banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır."
action_steps_tr=("Büyüme finansmanınızın borç/özkaynak dağılımını banka ile görüşmeden önce gözden geçirin.",)
assumptions_tr=("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",)

**Kesin ilke (Credit Score'dan BİREBİR miras, TÜM BANKING_READINESS kuralları için):**
HİÇBİR öneri belirli bir TRY tutarı, faiz oranı veya "X limitine hak
kazanırsınız" tarzı bir GARANTİ İÇERMEZ. `action_steps_tr` HER ZAMAN
"hazırlık/görüşme/araştırma" fiilleriyle biter, ASLA "X TL kredi alın"
DEMEZ.

### DATA_QUALITY (10 kural — YENİ kategori, Madde 3/8, artık AKSİYON üretebilir, salt passthrough DEĞİL)

**Kategori coverage boşluğu kuralları (6 — HER fonksiyonel kategori için 1):**

**30. `DQ_IMPROVE_LIQUIDITY_DATA_COVERAGE`** · **31. `DQ_IMPROVE_WORKING_CAPITAL_DATA_COVERAGE`** · **32. `DQ_IMPROVE_LEVERAGE_DATA_COVERAGE`** · **33. `DQ_IMPROVE_PROFITABILITY_DATA_COVERAGE`** · **34. `DQ_IMPROVE_ACTIVITY_DATA_COVERAGE`** · **35. `DQ_IMPROVE_GROWTH_DATA_COVERAGE`**

Her biri İÇİN ORTAK şablon (yalnızca `category_coverage_below` hedefi
ve `title_tr`/`explanation_tr` kategoriye göre değişir):
category=DATA_QUALITY, result_bucket=DATA_QUALITY, base_priority=INFORMATIONAL, severity=LOW, impact_band=LOW, difficulty_band=LOW_EFFORT
trigger_strategy=DATA_COVERAGE_GAP, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(category_coverage_below=<İLGİLİ KATEGORİ>, coverage_threshold=Decimal("0.50")),)
related_ratio_codes=(); merge_group=None; evidence_group="data_coverage_family"; underlying_risk_code="DATA_COVERAGE_RISK"
confidence_ceiling=1.00; coverage_policy=always_evaluated; disclaimer_scope=general
title_tr="{Kategori} Kategorisi İçin Veri Kapsamını İyileştirin" (ör. "Likidite Kategorisi İçin Veri Kapsamını İyileştirin")
explanation_tr="{Kategori} kategorisindeki oranların önemli bir kısmı hesaplanamıyor veya eksik; bu, bu alandaki değerlendirmenin güvenilirliğini sınırlamaktadır."
action_steps_tr=("İlgili finansal tablo kalemlerinin eksiksiz girildiğini kontrol edin.",)
assumptions_tr=("Bu öneri kategori coverage oranına dayanır, ratio değerlerinin kendisine DEĞİL; skora/priority'ye ETKİMEZ (Bölüm 6'nın uncovered_signal_codes ilkesiyle TUTARLI).",)

**Credit Score data-gap passthrough kuralları (4 — artık AKSİYON üretebilen DATA_QUALITY önerileri, salt passthrough DEĞİL):**

**36. `DQ_ADDRESS_FORWARD_CASH_FLOW_GAP`** (credit_score_data_gap_code="FORWARD_CASH_FLOW")
**37. `DQ_ADDRESS_COLLATERAL_DATA_GAP`** (credit_score_data_gap_code="COLLATERAL")
**38. `DQ_ADDRESS_PAYMENT_HISTORY_GAP`** (credit_score_data_gap_code="PAYMENT_HISTORY")
**39. `DQ_ADDRESS_MANAGEMENT_QUALITY_GAP`** (credit_score_data_gap_code="MANAGEMENT_QUALITY")

Ortak şablon:
category=DATA_QUALITY, result_bucket=DATA_QUALITY, base_priority=INFORMATIONAL, severity=LOW, impact_band=LOW, difficulty_band=LOW_EFFORT
trigger_strategy=DATA_GAP_PRESENT, trigger_mode=all, minimum_evidence_count=1
evidence_rules=(EvidenceRule(credit_score_data_gap_code=<İLGİLİ KOD>),)
related_ratio_codes=(); merge_group=None; evidence_group="credit_readiness_data_gap_family"; underlying_risk_code="CREDIT_READINESS_DATA_GAP"
confidence_ceiling=1.00; coverage_policy=always_evaluated; disclaimer_scope=general
explanation_tr="Platform bu alanda ilgili veriye şu an sahip değildir; bu durum Credit Score'un ilgili boyutunu sınırlamaktadır."
action_steps_tr=("Mümkünse ilgili veriyi platforma eklemeyi değerlendirin.",)
assumptions_tr=("Bu öneri, platformun ilgili veri türüne yapısal olarak SAHİP OLMADIĞI bilgisine dayanır; yeni bir hesaplama İÇERMEZ.",)

**REVİZYON NOTU (Madde 3/8):** bu 4 kural, önceki turun "salt passthrough,
ayrıca öneri ÜRETİLMEZ" ilkesini DEĞİŞTİRİR — artık `data_gap_
disclosures` HEM ham passthrough olarak (Bölüm 6) HEM DE bu 4 AKSİYON
üretebilen DATA_QUALITY önerisi olarak YER ALIR. Bu, kullanıcının bu
turdaki AÇIK talimatının (Madde 3: "kapsanmayan sinyaller sessizce
kaybolmayacak") DOĞAL bir uzantısıdır.

---

## 20b. Kural Kapsam Tablosu — `uncovered_signal_codes` (KİLİTLİ, Madde 3)

**Kesin ilke:** v1, 48 benchmark sinyalinin TAMAMI için ZORUNLU bir
kural ÜRETMEZ (Madde 3'ün bağlayıcı kararı — "kısmi ama kontrollü bir
rule seti"). Aşağıdaki tablo HER 48 sinyal için kapsanma durumunu,
gerekçesini ve gelecekteki aday kategoriyi TAM olarak gösterir.
Kapsanmayan sinyaller `RecommendationResult.uncovered_signal_codes`'ta
(Bölüm 6) ŞEFFAF şekilde raporlanır — HİÇBİR skora/priority'ye ETKİMEZ.

| Kategori | Kapsanan `ratio_code` (kural ile) | Kapsanmayan `ratio_code` | Kapsanmama gerekçesi | Gelecek aday kural kategorisi |
|---|---|---|---|---|
| LIQUIDITY (6) | current_ratio, quick_ratio, cash_ratio, defensive_interval_ratio (4) | working_capital_ratio, working_capital_to_total_assets (2) | `working_capital_ratio`, `current_ratio` ile AYNI formülü paylaşır (BENCHMARK_REGISTRY notu) — ayrı kural EKLENSE dedup ile ANINDA birleşirdi, ek DEĞER katmaz; `working_capital_to_total_assets` `current_ratio`/`cash_ratio` ile örtüşen bir bilanço-anı likidite sinyalidir | "ek likidite tamamlayıcı kuralları" (düşük öncelik) |
| WORKING_CAPITAL (8) | days_sales_outstanding, days_inventory_outstanding (x2 kural), days_payables_outstanding, cash_conversion_cycle, working_capital_turnover (6 kural, 5 benzersiz oran) | receivables_turnover, inventory_turnover, payables_turnover (3) | Bunlar, KENDİ "days" karşılıklarının (DSO/DIO/DPO) matematiksel TÜMLEYENİDİR (`turnover = 365/days` yaklaşık) — AYNI temel sinyali FARKLI birimde tekrar eder, kural eklense dedup GEREKTİRİRDİ | "turnover-birimli tamamlayıcı kurallar" (düşük öncelik, dedup mekanizması zaten HAZIR) |
| LEVERAGE (9) | equity_ratio, debt_to_equity (hard-fail üzerinden), interest_coverage_ratio (hard-fail üzerinden), short_term_debt_ratio, debt_to_ebitda (5) | debt_ratio, long_term_debt_to_equity, financial_leverage_multiplier, ebitda_coverage_ratio (4) | `debt_ratio` `equity_ratio`nun cebirsel tümleyenidir (≈1-equity_ratio); `long_term_debt_to_equity`/`financial_leverage_multiplier` `debt_to_equity` AİLESİNİN granüler varyantlarıdır; `ebitda_coverage_ratio` `interest_coverage_ratio` İLE AYNI borç-servisi sinyalini farklı payda ile tekrar eder | "granüler leverage varyant kuralları" (düşük öncelik) |
| PROFITABILITY (17) | net_profit_margin, cost_of_sales_ratio, gross_profit_margin, operating_expense_ratio, return_on_assets, return_on_equity (6) | operating_profit_margin, ebit_margin, ebitda_margin, pretax_profit_margin, return_on_capital_employed, effective_tax_rate, return_on_invested_capital, overhead_ratio, ebit_to_opex, non_operating_income_dependency, financing_expense_to_sales (11) | Marj ailesi (`operating_profit_margin`/`ebit_margin`/`ebitda_margin`/`pretax_profit_margin`) `net_profit_margin`/`gross_profit_margin` İLE AYNI kârlılık zayıflığını FARKLI kâr katmanlarında tekrar eder; `return_on_capital_employed`/`return_on_invested_capital` `return_on_assets`/`return_on_equity` ailesinin varyantıdır; `effective_tax_rate` RANGE_IS_BETTER, aksiyon-dönüştürülebilirliği düşük; verimlilik alt-grubu (`overhead_ratio` vb.) `operating_expense_ratio` İLE örtüşür | "granüler kârlılık/verimlilik varyant kuralları" (orta öncelik — Bölüm 33 madde 4'ün ürün kararına bağlı) |
| ACTIVITY (2) | asset_turnover, fixed_asset_turnover (2) | — (TAM kapsanmıştır) | — | — |
| GROWTH (6) | sales_growth, equity_growth, total_assets_growth (3, 2 kuralda) | gross_profit_growth, ebitda_growth, net_profit_growth (3) | Bu üçü `sales_growth` İLE AYNI büyüme/daralma yönünü kâr katmanlarında tekrar eder — `sales_growth` zaten en üst-seviye, en az gürültülü büyüme sinyalidir | "kâr-büyüme varyant kuralları" (düşük öncelik) |
| BANKING_READINESS (6 flag) | TÜMÜ (6/6) | — | — | — |
| DATA_QUALITY (4 gap + 6 coverage) | TÜMÜ (10/10) | — | — | — |

**Doğrulama:** 48 benchmark sinyalinden **25'i** en az bir kuralla
DOĞRUDAN kapsanmış (`related_ratio_codes` üzerinden), **23'ü**
`uncovered_signal_codes`'ta raporlanır (4+5+5+6+2+3=25 kapsanan;
2+3+4+11+0+3=23 kapsanmayan; 25+23=48 ✓). BANKING_READINESS (6 flag) ve
DATA_QUALITY (10 kaynak) TAM kapsanmıştır. Bu tablo Bölüm 33 madde
4'ün ("kural seti tamlığı") ürün kararına DOĞRUDAN GİRDİDİR.

---

## 28. Test Stratejisi

1. **Types/dataclass/enum testleri** — her yeni dataclass'ın alan
   sözleşmesi, `frozen=True` garantisi.
2. **Registry validasyon testleri** — Bölüm 8.2'nin 12 maddesinin
   TAMAMI (referans bütünlüğü, kategori↔result_bucket tutarlılığı,
   `evidence_rules` tekil-tür kontrolü, `tier_in`/`hard_fail_code`/
   `banking_lens_flag`/`credit_score_data_gap_code` katalog kontrolü,
   `mutually_exclusive_group`↔`conflict_group` ayrıklığı, `INFORMATIONAL`
   yalnızca BANKING_READINESS/DATA_QUALITY kısıtı).
3. **Kural-evidence_rules testleri** — Bölüm 20a'daki HER 39 kuralın
   gerçek `analyze_financial_ratios`+`evaluate_benchmarks`+`compute_
   financial_health_score`+`compute_credit_score` çıktısı üzerinde
   DOĞRU tetiklendiği/tetiklenmediği; strateji fonksiyonlarının
   (Bölüm 8.0) SAFLIĞININ (yan etkisiz) ayrı, izole birim testlerle
   doğrulanması.
4. **Dedup/merge testleri** (Bölüm 14) — AYNI `merge_group`'u paylaşan
   iki adayın TEK bir `RecommendationItem`'a birleştiği, `triggered_by`'ın
   BİRLEŞTİĞİ, `confidence`'ın EN DÜŞÜĞÜNÜN alındığı, hiçbir kanıtın
   KAYBOLMADIĞI.
4a. **BANKING_READINESS dedup testi** (Bölüm 14.1) — `merge_group`
    eşleşen bir BANKING_READINESS/fonksiyonel kategori çiftinin AYNI
    ÇALIŞTIRMADA tetiklendiği bir golden-dataset senaryosunda TEK bir
    `RecommendationItem`'a birleştiğinin VE banking disclaimer'ının
    KORUNDUĞUNUN doğrulanması.
5. **Çakışma/mutually-exclusive testleri** (Bölüm 13) — `RECOMMENDATION_
   MUTUALLY_EXCLUSIVE_GROUPS`'taki `MEG_INVENTORY_LEVEL` çiftinin
   YAPISAL olarak AYNI ANDA tetiklenemediğinin (100 rastgele fixture
   üzerinde property test) kanıtlanması; `RECOMMENDATION_CONFLICT_
   PAIRS`'in v1'de BOŞ olduğunun regresyon testi (gelecekte bir çift
   eklendiğinde mekanizmanın ÇALIŞTIĞINI doğrulayacak bir sentetik-
   registry testi AYRICA yazılır).
6. **Öncelik/severity eskalasyon testleri** (Bölüm 9.2) — hard-fail
   koşulsuz `CRITICAL` eskalasyonu, critical-override EN AZ `HIGH`
   eskalasyonu, severity nüansının TEK kademeyle SINIRLI olduğu,
   confidence<0.50'de nüansın ENGELLENDİĞİ, `base_priority`'nin
   registry'deki DEĞERİNİN hiçbir testte MUTASYONA UĞRAMADIĞI.
6a. **Coverage-gate muafiyet testi (ZORUNLU)** — `coverage_policy=
    exempt_hard_fail` olan bir `RecommendationItem`'ın, KENDİ kategorisinin
    `category_coverage`'ı KASITLI olarak `0.0`'a düşürülmüş bir test
    fixture'ında DAHİ nihai `recommendations` listesinde YER ALDIĞININ
    property test ile kanıtlanması; AYNI koşulda `coverage_policy=
    subject_to_gate` olan bir adayın EMİLDİĞİNİN (elendiğinin) ayrıca
    doğrulanması (negatif kontrol). Bu test YEŞİL olmadan Bölüm 32
    Adım 8 TAMAMLANMIŞ SAYILMAZ.
7. **`INVARIANT: RECOMMENDATION_ENGINE_READ_ONLY` property testi
   (ZORUNLU, Bölüm 12 Adım 19):** `generate_recommendations()`
   çağrısından ÖNCE/SONRA `RATIO_REGISTRY`/`BENCHMARK_REGISTRY`/
   `RATIO_SCORE_WEIGHTS`/`CREDIT_RATIO_SCORE_WEIGHTS`/`RECOMMENDATION_
   RULES` boyutlarının/içeriklerinin AYNI kaldığı; girdi olarak verilen
   4 nesnenin (deep-copy karşılaştırmasıyla) MUTASYONA UĞRAMADIĞI. **Bu
   test YEŞİL olmadan ilgili implementasyon adımı TAMAMLANMIŞ SAYILMAZ.**
8. **`RecommendationDirectionalContext` testleri** (Bölüm 19.2) —
   `improvement_direction_tr`'nin HER ZAMAN 3 sabit değerden biri OLDUĞU,
   `next_better_tier_name`'in yalnızca bant İSMİ taşıdığı (rakam
   İÇERMEDİĞİ, property testiyle regex kontrolü), HİÇBİR skor/oran
   YENİDEN HESAPLAMA ÇAĞRISI YAPILMADIĞI (mock/spy ile `compute_
   financial_health_score`/`compute_credit_score`'un ÇAĞRILMADIĞININ
   doğrulanması).
8a. **`SCHEMA_INCOMPATIBLE`/`VERSION_MISMATCH` testleri (ZORUNLU,
    Bölüm 16.2)** — desteklenmeyen bir şema versiyonuyla `status=
    SCHEMA_INCOMPATIBLE`+boş `recommendations`; desteklenmeyen bir
    ratio/benchmark registry versiyonuyla `status=VERSION_MISMATCH`+
    YALNIZCA `DATA_QUALITY` üretildiğinin; yalnızca model_version
    farklıyken NORMAL hesaplama+`MODEL_VERSION_MISMATCH` uyarısının
    doğrulanması.
8b. **Confidence modeli testleri (ZORUNLU, Bölüm 15.4)** — madde a-h'nin
    HER BİRİNİN ayrı ayrı test edilmesi: min-ceiling davranışı (ortalama/
    çarpım DEĞİL), `RELIABILITY_TO_CONFIDENCE_CEILING` haritasının doğru
    uygulandığı, `DATA_QUALITY` item'larının HER ZAMAN `confidence=1.00`
    döndürdüğü, `confidence`/`coverage`'ın HER ZAMAN AYRI alanlar olarak
    raporlandığı (aynı değeri taşısalar bile birbirinin YERİNE
    GEÇMEDİĞİ).
9. **Golden dataset senaryoları** — mükemmel şirket (öneri YOK,
   `NO_RECOMMENDATIONS_TRIGGERED`), negatif özkaynak (CRITICAL leverage
   önerisi + BANKING_READINESS `DEBT_SERVICE_STRESS`, `merge_group` ile
   BİRLEŞMİŞ), zayıf CCC + güçlü kârlılık (WORKING_CAPITAL MEDIUM +
   PROFITABILITY yok), borçla finanse büyüme (GROWTH + BANKING_READINESS
   `merge_group` ile birleşmiş tekli item), stok mutually-exclusive
   senaryosu (`WC_MAINTAIN_INVENTORY_SAFETY_BUFFER`/`WC_REDUCE_
   INVENTORY_DAYS`'in AYNI ANDA tetiklenmediğinin doğrulanması), düşük
   coverage (bazı kategoriler `DATA_QUALITY` üretir, finansal önerileri
   BASTIRILIR), `VERSION_MISMATCH` senaryosu.
10. **Property testleri** — determinizm (100 iterasyon bit-birebir aynı
    çıktı), sıralamanın HER ZAMAN `priority_rank` öncelikli olduğu,
    `blocked=True` item'ların sıralamadan ÇIKARILMADIĞI.
11. **Registry temizlik/regresyon testleri** — mevcut `tests/conftest.py`
    fixture'ının Bölüm 1.6'da TANIMLI 4 yeni registry'yi (container
    tipi/restore stratejisiyle) kapsayacak şekilde GENİŞLETİLMESİ
    ZORUNLUDUR.
12. **Performans testi** — Bölüm 29.
13. **Tam mevcut suite regresyon çalıştırması.**

---

## 29. Performans Hedefi

Mevcut ölçülen zincir (gerçek sandbox ölçümü, 4.3E final raporundan):
Ratio+Benchmark+Health+Credit ≈ **0,95 ms/çağrı**. Recommendation
Engine'in EK maliyeti hedefi **<0,5 ms/çağrı** (kural sayısı KESİN
olarak 39, her biri basit sözlük okuma/karşılaştırma + Bölüm 15.4'ün
min-ceiling confidence hesaplaması, O(kural sayısı) karmaşıklık — önceki
turun ~30-35 tahminine göre HAFİF yukarı revize edilmiştir çünkü
confidence modeli v1'e alınmıştır, Madde 8), **tam 5-motor zincir
toplamı <1,7 ms/çağrı** hedeflenir. Adım 17'de (Bölüm 32) bu hedef
GERÇEK 39-kural registry'siyle DOĞRULANACAKTIR.

---

## 30. Risk Analizi

1. **Mesleki tavsiye algısı riski** — öneri metinleri "resmî mali
   danışmanlık" gibi ALGILANABİLİR. Mitigasyon: Bölüm 15.3 disclaimer'ı
   HER `RecommendationItem`'da VE sonuç seviyesinde ZORUNLU.
2. **Çakışan önerilerin kullanıcıyı YANILTMASI riski** — İKİ ZIT
   öneriyle karşılaşan bir kullanıcı KARARSIZ kalabilir. Mitigasyon:
   Bölüm 13 — asla otomatik BASTIRMA, AÇIK `conflicting_with` +
   `explanation_tr`.
3. **Statik impact/difficulty bantlarının UNCALIBRATED olması** —
   editoryal/öznel etiketler, gerçek şirket verisiyle DOĞRULANMAMIŞTIR
   (Health/Credit Score'un "tüm eşikler provisional" ilkesiyle AYNI
   dürüstlük — Bölüm 34'te açıkça belirtilir).
4. **ÜÇÜNCÜ bir kategori taksonomisi (Recommendation'ın KENDİSİ) —
   Health Score'un 7'si, Credit Score'un 6'sı, Recommendation'ın 8'i
   (Madde 5 ile `DATA_QUALITY` eklendi) — bilişsel yük riski.**
   Mitigasyon: Bölüm 18/18.1'in HER kategori eşleşmesi VE 48 sinyalin
   TAMAMININ dağılımı AÇIKÇA dokümante edilmiştir; implementasyon
   sonrası UI katmanı (bu milestone'un kapsamı DIŞINDA) net bir
   eşleme tablosu göstermelidir.
5. **BANKING_READINESS katmanının kredi onayı/limiti ile KARIŞTIRILMASI
   riski** — Credit Score'la AYNI risk, AYNI mitigasyon (Bölüm 20a
   disclaimer — TÜM 6 kural için ZORUNLU).
6. **Eşik-yakınlığı bağlamının (Bölüm 19) YANLIŞ ANLAŞILMASI riski**
   — kullanıcı niteliksel ifadeyi bir SKOR TAHMİNİ/hedef sanabilir.
   Mitigasyon (Madde 6 revizyonuyla GÜÇLENDİRİLDİ): `threshold_
   proximity_note_tr` artık sayısal fark İÇERMEZ, YALNIZCA 3 sabit
   niteliksel metinden biridir, ve metnin KENDİSİ "bu bir hedef değer
   veya skor tahmini DEĞİLDİR" ibaresini TAŞIR — risk azaltıldı ama
   SIFIRLANMADI (bkz. Bölüm 34/35'teki genel uyarı).
7. **Sekiz versiyon ekseninin (Bölüm 16) TUTARSIZLAŞMA riski** —
   `ratio_registry_version`/`benchmark_registry_version` HEM Health
   Score'dan HEM Credit Score'dan geçirilir; ikisi TEORİK olarak
   FARKLI olabilir (ör. Health Score eski bir cache'ten geldiyse).
   Mitigasyon: pipeline bu iki değeri KARŞILAŞTIRIR, uyuşmazsa
   `VERSION_MISMATCH` warning'i üretir (skor/öneri ÜRETİMİNİ
   ENGELLEMEZ, yalnızca ŞEFFAFLIK). **REVİZYON (Madde 8):** bu risk
   yalnızca `ratio_registry_version`/`benchmark_registry_version`'ı
   kapsıyordu — `health_score_schema_version`/`credit_score_schema_
   version`'ın KENDİSİNİN desteklenmeyen bir sürüm olması AYRI VE DAHA
   CİDDİ bir risktir (alan adları/şekli DEĞİŞMİŞ olabilir, bu sadece
   "şeffaflık notu" ile geçiştirilemez) — bu durum ARTIK `VERSION_
   MISMATCH` uyarısıyla DEVAM ETMEZ, Bölüm 6.2/12 Aşama A0'daki YENİ
   `SCHEMA_INCOMPATIBLE` status'üyle işlemi TAMAMEN DURDURUR.
8. **(YENİ, Madde 8) Şema-uyumsuzluğu ön-kontrolünün YANLIŞ POZİTİF
   riski** — `SUPPORTED_*_SCHEMA_VERSIONS` tuple'ı implementasyon
   sırasında güncel tutulmazsa (ör. Health Score'un ZARARSIZ, geriye-
   uyumlu bir minor versiyon artışı bu listeye eklenmezse), Recommendation
   Engine GEREKSİZ yere `SCHEMA_INCOMPATIBLE` dönebilir. Mitigasyon:
   Bölüm 32 Adım 1'de bu tuple'ın Health/Credit Score'un GÜNCEL
   `*_schema_version` sabitleriyle senkron tutulması implementasyon
   kontrol listesine eklenmelidir (Bölüm 33'e yeni açık karar olarak
   İŞARETLENMEMİŞTİR — bu, implementasyon bakımı gerektiren teknik bir
   detaydır, tasarım kararı değildir).

---

## 31. Dosya Yapısı

```
app/engines/common/recommendation_types.py     # dataclass/enum/sabitler
app/engines/common/recommendation_registry.py  # RECOMMENDATION_RULES + diğer registry'ler
app/engines/recommendation/__init__.py         # boş
app/engines/recommendation/service.py          # generate_recommendations() pipeline
```

Mevcut `app/engines/common/**` ve `app/engines/{health_score,credit_
score}/**` deseniyle BİREBİR aynı iskelet — sqlalchemy/fastapi/
pydantic'e SIFIR bağımlı.

---

## 32. Alt İmplementasyon Planı (onay SONRASI için — ŞİMDİ ÇALIŞTIRILMAZ) — Bölüm 12'nin 20 Adımıyla HİZALANMIŞTIR

1. Adım 1 — `recommendation_types.py` (tüm enum'lar — `RecommendationCategory`
   [8], `ResultBucket`, `RecommendationSeverity`, `RecommendationTrigger
   Strategy`, `RecommendationComputationStatus` [5 değer] — ve tüm
   dataclass'lar: `EvidenceRule`, `RecommendationRule` [29 alan],
   `RecommendationItem` [Bölüm 15.1], `RecommendationDirectionalContext`,
   `RecommendationConflictGroup`, `RecommendationMutuallyExclusiveGroup`,
   `RECOMMENDATION_INPUT_COMPATIBILITY`, `RELIABILITY_TO_CONFIDENCE_
   CEILING`).
2. Adım 2 — `recommendation_registry.py` (Bölüm 20a'nın 39 kuralının TAM,
   implementasyon-hazır kaydı + `register_recommendation_rule`'ın 12
   maddelik doğrulaması + `BANKING_FLAG_TO_RATIO_OVERLAP` + `RECOMMENDATION_
   MUTUALLY_EXCLUSIVE_GROUPS` + 8 kapalı strateji fonksiyonu). Bölüm
   1.6'daki ZORUNLU import sırasına UYULUR: bu modül `credit_score_
   registry`'den SONRA, HER ZAMAN EN SON import edilir.
3. Adım 3 — Pipeline Adım 1-2 (compatibility kontrolü + girdi doğrulama).
4. Adım 4 — Pipeline Adım 3-5 (`_build_recommendation_context`, Health
   Score'un `collect_ratio_signals`'ını reuse, hard-fail/data-gap
   işaretleme).
5. Adım 5 — Pipeline Adım 6-9 (eligibility değerlendirme, coverage
   politikası + hard-fail istisnası, aday üretimi).
6. Adım 6 — Pipeline Adım 10 (Bölüm 15.4'ün TAM confidence modeli).
7. Adım 7 — Pipeline Adım 11-12 (`merge_group` dedup, supporting
   ilişkiler).
8. Adım 8 — Pipeline Adım 13-14 (conflict/mutually-exclusive, prerequisite/
   blocking — v1'de HİÇ tetiklenmeyen ama TAM test edilen mekanizmalar).
9. Adım 9 — Pipeline Adım 15-16 (priority/severity eskalasyonu, stable
   sort).
10. Adım 10 — Pipeline Adım 17-18 (3-yönlü bucket ayrımı, `uncovered_
    signal_codes`, warnings toplama).
11. Adım 11 — Pipeline Adım 19-20 (`INVARIANT: RECOMMENDATION_ENGINE_
    READ_ONLY` doğrulaması + `RecommendationResult` inşası).
12. Adım 12 — `generate_recommendations()` tam orkestrasyon (Adım 3-11'i
    TEK fonksiyonda birleştirir).
13. Adım 13 — Unit testler (Bölüm 28 madde 1-6, 4a, 6a, 8-8b) +
    `tests/conftest.py` fixture'ının Bölüm 1.6'da TANIMLI 4 yeni
    registry'yi kapsayacak şekilde GÜNCELLENMESİ ZORUNLU.
14. Adım 14 — Golden dataset testleri (Bölüm 28 madde 9).
15. Adım 15 — Property testleri (`INVARIANT: RECOMMENDATION_ENGINE_
    READ_ONLY` DAHİL, ZORUNLU, Bölüm 28 madde 7/10).
16. Adım 16 — Regresyon testleri (registry boyut/mutasyon kontrolü).
17. Adım 17 — Performans testleri (Bölüm 29 — YENİ hedef: 39 kural +
    confidence modeli dahil <0,5 ms/çağrı).
18. Adım 18 — Final rapor + final doğrulama + gerçek Docker/pytest
    koşusu istemi (4.3D/4.3E'deki AYNI disiplin: "0 failed gerçek
    Docker sonucu görülmeden tamamlandı DENMEZ").

---

## 33. Onaylanmış Kararlar — KAPALI (son onay turu, Madde 11)

**DURUM: TÜM AÇIK KARARLAR KULLANICI TARAFINDAN BAĞLAYICI ŞEKİLDE
KAPATILMIŞTIR.** Bu bölüm artık "açık tasarım kararları" DEĞİL,
onaylanmış, kilitli kararların KAYDIDIR. Aşağıdaki 11 madde (önceki
turun listesi) TEK TEK, kullanıcının bu turdaki AÇIK talimatlarıyla
KAPATILMIŞTIR — hiçbiri implementasyonu engelleyen bir onay
BEKLEMEMEKTEDİR.

1. **[ONAYLANDI] Bölüm 19 — Yönsel Eşik Bağlamı kapsamı:** gerçek
   simülasyon, sayısal hedef büyüklüğü, oran farkı KESİN OLARAK
   ÜRETİLMEYECEK; yalnızca `RecommendationDirectionalContext` (tier,
   ideal_direction, improvement_direction_tr, ratio_code, next_better_
   tier_name) — TAMAMEN niteliksel — v1 kapsamındadır. KİLİTLİ.
2. **[ONAYLANDI] Bölüm 7.3 — "strength reinforcement" türü:** v1'de
   KESİN OLARAK YOK, v2'ye de TAŞINMAYACAK bir kapsam sınırıdır. Güçlü
   yönler Health/Credit Score'un mevcut explainability çıktılarında
   KALIR. KİLİTLİ.
3. **[ONAYLANDI] Bölüm 13.2 — `RECOMMENDATION_CONFLICT_PAIRS`:** v1'de
   KASITLI OLARAK BOŞ (mekanizma TAM implemente/test edilir, gerçek bir
   çift YOK — icat EDİLMEZ). Genişleme, gelecekteki kural-seti
   büyümesiyle DOĞAL olarak gerçekleşecektir, AYRI bir onay
   GEREKTİRMEZ (Bölüm 8.2 madde 4'ün referans-bütünlüğü kilidi zaten
   YETERLİ güvencedir).
4. **[ONAYLANDI] Bölüm 20a/20b — rule set kapsamı:** v1, 48 sinyalin
   TAMAMINI KAPSAMAZ; kısmi ama KONTROLLÜ 39 kurallık bir envanterdir.
   Kapsanmayan 23 sinyal Bölüm 20b'de TAM gerekçeli tabloda listelenir
   VE `uncovered_signal_codes` ile runtime'da ŞEFFAF raporlanır (skora/
   priority'ye ETKİMEZ). KİLİTLİ.
5. **[ONAYLANDI] Bölüm 9.1 — `LOW` önceliği:** BAĞIMSIZ, açık bir
   `base_priority` değeridir; örtük "zaten kaplı kategoride ikincil"
   mantığı TAMAMEN KALDIRILMIŞTIR. KİLİTLİ.
6. **[ONAYLANDI] Bölüm 18 — `WORKING_CAPITAL` kategorisi:** `LIQUIDITY`'
   den KESİN OLARAK AYRI bir kategori olarak KORUNUR (8 kategorilik
   nihai taksonominin bir parçası). KİLİTLİ.
7. **[ONAYLANDI — KARAR DEĞİŞTİ] Bölüm 15.4 — Confidence modeli:**
   önceki turun "v2'ye ERTELE" kararı GERİ ALINMIŞTIR — confidence/
   reliability/confidence_ceiling/coverage/provisional/confidence_
   basis/evidence_reliabilities/missing_inputs/warnings alanları v1'İN
   ZORUNLU bir parçasıdır, min-ceiling modeliyle (madde a-h) TAM
   TANIMLANMIŞTIR. KİLİTLİ.
8. **[ONAYLANDI] Hard-fail/coverage-gate çelişkisi:** `coverage_
   policy="exempt_hard_fail"` olan kurallar coverage gate'ten KOŞULSUZ
   MUAFTIR (Bölüm 12 Adım 7-8). KİLİTLİ.
9. **[ONAYLANDI] Deklaratif trigger modeli:** `predicate: Callable`
   YERİNE `EvidenceRule`+`trigger_strategy`+`trigger_mode`+`evidence_
   rules`+`minimum_evidence_count`+`prerequisite_rules`+`blocking_
   rules` — 8 kapalı, saf, kayıtlı strateji fonksiyonu (Bölüm 8.0).
   Serbest nested expression/expression tree KESİN OLARAK v1 kapsamı
   DIŞINDA. KİLİTLİ.
10. **[UYGULAMA NOTU, ENGELLEYİCİ DEĞİL]** İç-içe mantık ("A VE (B VEYA
    C)") ihtiyacı çıkarsa, YENİ bir kapalı/saf/kayıtlı strateji adı
    (`nested_group` gibi) eklenir — serbest expression tree ASLA
    eklenmez. Bu bir açık KARAR değildir, implementasyon sırasında
    İZLENECEK bir tasarım İLKESİDİR.
11. **[UYGULAMA NOTU, ENGELLEYİCİ DEĞİL]** `RECOMMENDATION_INPUT_
    COMPATIBILITY`'nin Health/Credit Score'un GÜNCEL versiyonlarıyla
    SENKRON tutulması Bölüm 32 Adım 1'e YAZILMIŞ bir implementasyon
    bakım sorumluluğudur, bir tasarım kararı DEĞİLDİR.

**Sonuç: Bölüm 33'te bekleyen HİÇBİR açık karar KALMAMIŞTIR.**
Maddeler 1-9 kullanıcının bu turdaki bağlayıcı tercihleriyle
KAPATILMIŞ, madde 10-11 zaten "açık karar" değil UYGULAMA
NOTU olarak yeniden sınıflandırılmıştır.

---

## 34. Production Readiness Tahmini (İLK SÜRÜM — TARİHSEL KAYIT)

**NOT: Bu bölüm, mimari denetimden ÖNCEKİ ilk tasarım turunun
değerlendirmesidir; TARİHSEL KAYIT olarak KORUNMUŞTUR. GÜNCEL
değerlendirme için Bölüm 36'ya bakınız.**

- **Tasarım tamlığı:** ~%80 (35 başlığın TAMAMI dolduruldu, ama Bölüm
  33'teki 6 madde AÇIK — özellikle Bölüm 19/7.3/4 nihai onay
  gerektiriyor).
- **Fonksiyonel/implementasyon:** **%0** — hiçbir kod satırı
  yazılmadı (kullanıcının KESİN talimatı gereği).

## 35. İmplementasyona Hazır mı? (İLK SÜRÜM — TARİHSEL KAYIT)

**NOT: Bu bölümün verdiği "Hayır" cevabı, mimari denetimden ÖNCEKİ
duruma aittir. GÜNCEL değerlendirme için Bölüm 36'ya bakınız.**

**Hayır — henüz değil.** Bölüm 33'teki açık kararlar YANITLANMADAN,
implementasyon adımlarının (Bölüm 32) sırası/kapsamı NİHAİLEŞEMEZ.
Tasarım, bir SONRAKİ revizyon turunda bu açık kararlar netleştirildikten
sonra "Onaylanmış Kararlar" durumuna geçebilir (4.3D/4.3E'nin izlediği
İKİ TURLU onay süreciyle AYNI desen).

**Kullanıcının açık ve ayrı "başla" talimatı OLMADAN hiçbir kod/test/
migration/API/adapter YAZILMAYACAKTIR.**

---

## 36. Mimari Denetim Sonrası Revizyon Raporu

Bu bölüm, bağımsız mimari denetim raporunun 10 zorunlu maddesinin bu
revizyonda NASIL ele alındığını özetler. Kod/test/migration/API/adapter
YAZILMAMIŞTIR — bu, YALNIZCA doküman revizyonunun kaydıdır.

### 36.1 Çözülen mimari sorunlar

1. **Hard-fail/coverage-gate çelişkisi** — `trigger_source ∈
   {HEALTH_SCORE_HARD_FAIL, CREDIT_SCORE_HARD_FAIL}` kuralları artık
   kategori coverage gate'inden KOŞULSUZ MUAF (Bölüm 12 Aşama B/I,
   Bölüm 27, Bölüm 28 madde 6a). Denetim raporunun en ciddi bulduğu
   madde ÇÖZÜLDÜ.
2. **Kırık rule_code referansları (Bölüm 13.2)** — tüm örnekler gerçek,
   registry'de kayıtlı rule_code'larla değiştirildi; eksik olan gerçek
   çakışma senaryosunu karşılamak için `WC_MAINTAIN_INVENTORY_SAFETY_
   BUFFER` kuralı Bölüm 20'ye EKLENDİ (icat edilen referanslar yerine
   registry GENİŞLETİLEREK tutarlılık sağlandı). Bölüm 8.2'ye ayrıca
   çakışma-çifti referans bütünlüğü doğrulaması (madde 4) eklendi.
3. **`working_capital_turnover` kategori çelişkisi** — oran KESİN olarak
   WORKING_CAPITAL'a bağlandı (Bölüm 20), ACTIVITY'den (Bölüm 24)
   kaldırıldı. Gerekçe her iki bölümde de REVİZYON NOTU olarak yazılı.
4. **`predicate: Callable` mimarisi** — tamamen kaldırıldı, deklaratif,
   eval/exec içermeyen `RecommendationTriggerCondition` yapısıyla
   DEĞİŞTİRİLDİ (Bölüm 8.1). Kayıt-anında doğrulama (Bölüm 8.2) 4 yeni
   maddeyle (5-8) genişletildi.
5. **BANKING duplicate mekanizması boşluğu** — `BANKING_FLAG_TO_RATIO_
   OVERLAP` registry'si (Bölüm 8.3/14.1) ile BANKING ve fonksiyonel
   kategori önerileri arasındaki dedup boşluğu kapatıldı.
6. **What-if/simülasyon isimlendirme ve sayısal-yorum riski** — Bölüm
   19 yeniden adlandırıldı ("Eşik Yakınlığı Bağlamı"), sayısal fark
   tamamen kaldırıldı, yalnızca 3 sabit niteliksel metinden biri
   kullanılacak şekilde daraltıldı; alan `RecommendationItem`
   dataclass'ına (önceden eksikti) resmen EKLENDİ.
7. **Confidence/reliability sessiz boşluğu** — v1'de aggregate confidence
   alanı EKLENMEYECEĞİ açıkça, gerekçeli bir karar olarak yazıldı
   (Bölüm 15.4); `supporting_evidence`'a HAM `reliability` alanı
   eklenerek bilgi kaybı KISMEN giderildi.
8. **Schema version uyuşmazlığı davranışı** — yeni `SCHEMA_INCOMPATIBLE`
   status'ü ve Aşama A0 ön-kontrolü ile davranış NET tanımlandı (Bölüm
   6.2, Bölüm 12).
9. **Import sırası/fixture sırası belirsizliği** — Bölüm 1.6'da ZORUNLU
   import zinciri, container tipleri ve LIFO restore sırası AÇIKÇA
   yazıldı (artık İMA EDİLMİYOR).

### 36.2 Bilinçli olarak ertelenen konular

- **`RecommendationItem.confidence` (aggregate) alanı** — v2'ye
  ERTELENDİ, metodolojisi AYRI bir açık karar (Bölüm 33 #7'nin alt
  maddesi).
- **Gerçek "what-if" simülasyonu (Bölüm 19.3)** — v1 kapsamı DIŞINDA,
  isim-only hook olarak kalmaya devam ediyor.
- **`RECOMMENDATION_CONFLICT_PAIRS`'in TAM genişletilmesi** — yalnızca
  1 tam-doğrulanmış çift v1'de var; kural seti (Bölüm 33 #4) genişledikçe
  ele alınacak.
- **Kural setinin RATIO_REGISTRY'nin TAMAMINI kapsaması** — ~31 kurallık
  başlangıç seti korunuyor, tam kapsam ürün kararı bekliyor.
- **`condition_logic`'in iç-içe mantık (nested AND/OR) desteği** — şu an
  gerek görülmüyor, ihtiyaç çıkarsa AYRI bir revizyon konusu.

### 36.3 Yeni açık kararlar

Bölüm 33'e #10 (nested condition logic) ve #11 (schema-version tuple
bakımı) eklendi — ikisi de DÜŞÜK ÖNCELİKLİ, engelleyici DEĞİL.

### 36.4 Production Readiness (GÜNCEL)

- **Tasarım tamlığı:** ~%90 — denetim raporunun 5 "zorunlu" (must-fix)
  maddesinin TAMAMI (hard-fail/coverage-gate, kırık referanslar,
  kategori çelişkisi, predicate mimarisi, BANKING dedup) bu revizyonda
  ÇÖZÜLDÜ. Kalan %10, Bölüm 33'teki 7 açık maddenin (hiçbiri mimari
  hata DEĞİL, tümü meşru ürün/kapsam tercihi) kullanıcı onayı
  beklemesinden kaynaklanıyor.
- **Fonksiyonel/implementasyon:** **%0** — bu görevde de hiçbir kod
  satırı yazılmadı (kullanıcının bu turdaki KESİN talimatı gereği).

### 36.5 İmplementasyona hazır mı? (GÜNCEL DEĞERLENDİRME)

**Teknik/mimari açıdan: EVET, hazır — açık kararların onayı şartıyla.**
Gerekçe: denetim raporunun tespit ettiği TÜM somut hatalar (kırık
referans, kategori çelişkisi, güvenlik açığı niteliğindeki hard-fail/
coverage-gate çelişkisi, registry-first ilkesini ihlal eden Callable
mimarisi, BANKING dedup boşluğu) bu revizyonla GİDERİLDİ; bunların
hiçbiri artık implementasyonu engelleyen bir MİMARİ KUSUR değil. Geri
kalan 7 açık madde (Bölüm 33) TAMAMEN ürün/kapsam TERCİHLERİDİR —
teknik bir eksiklik değil, kullanıcının vermesi gereken bir onaydır.

**Buna rağmen prosedürel cevap: HAYIR, implementasyona HENÜZ
GEÇİLMEYECEK.** Çünkü: (1) projenin baştan beri uyguladığı iki-turlu
onay disiplini (4.3D/4.3E'de olduğu gibi) açık kararların kullanıcı
tarafından TEK TEK yanıtlanmasını gerektirir; (2) Bölüm 33'teki 7 açık
maddeden hiçbiri implementasyon PLANININ (Bölüm 32) sırasını/kapsamını
DEĞİŞTİRMEYECEK olsa bile (özellikle #1, #4 kural setinin BOYUTUNU
etkiler), kullanıcının bunları görmeden "başla" demesi projenin kendi
disiplinine AYKIRI olurdu; (3) kullanıcının bu turdaki talimatı zaten
"implementasyona HENÜZ BAŞLAMA" idi.

**Kalan kritik bloklayıcılar (teknik DEĞİL, onay bekleyen):** Bölüm 33
madde #1 (eşik-yakınlığı kapsamı), #2 (strength reinforcement), #4
(kural seti tamlığı), #5 (LOW önceliğin tanımı), #6 (WORKING_CAPITAL
ayrı kategori mi), #10, #11.

**Kullanıcının açık ve ayrı "başla" talimatı OLMADAN hiçbir kod/test/
migration/API/adapter YAZILMAYACAKTIR.**

---

## 37. Son Onay Turu Sonrası Nihai Rapor (KAPANIŞ)

Bu bölüm, Bölüm 36'nın (2. tur denetim-revizyonu) SONRASINDA gelen 3.
ve SON karar turunun sonuçlarını kaydeder. Bölüm 33'teki 7 açık madde
kullanıcının bu turdaki 11 bağlayıcı tercihiyle KAPATILMIŞTIR (Bölüm
33 artık "Onaylanmış Kararlar"). Kod/test/migration/API/adapter
YAZILMAMIŞTIR — bu YALNIZCA doküman revizyonunun kaydıdır.

### 37.1 Sayımlar (registry'nin GERÇEK, placeholder içermeyen hâlinden)

- **Gerçek mimari hata sayısı (bu turda tespit edilen YENİ):** 0 — 2.
  tur denetiminin 5 zorunlu maddesi ÖNCEKİ turda çözülmüştü; bu tur
  yalnızca AÇIK KARARLARI kapattı, yeni bir mimari hata bulunmadı/
  bildirilmedi.
- **Kapatılan karar sayısı:** 11/11 (Bölüm 33) — 9'u bağlayıcı ürün
  kararı, 2'si (madde 10-11) "açık karar" olmaktan çıkıp uygulama
  notuna DÖNÜŞTÜRÜLDÜ.
- **Toplam recommendation rule sayısı:** **39** (placeholder YOK, Bölüm
  20a).
- **Kategori dağılımı:** WORKING_CAPITAL=6, LIQUIDITY=4, LEVERAGE=4,
  PROFITABILITY=4, ACTIVITY=2, GROWTH=3, BANKING_READINESS=6,
  DATA_QUALITY=10 (toplam 6+4+4+4+2+3+6+10=**39** ✓).
- **Financial recommendation sayısı (result_bucket=FINANCIAL):**
  6+4+4+4+2+3=**23**.
- **Banking-readiness recommendation sayısı:** **6**.
- **Data-quality recommendation sayısı:** **10** (6 kategori-coverage +
  4 credit-score-gap).
- **Hard-fail kaynaklı rule sayısı (`coverage_policy=exempt_hard_fail`):**
  **2** (`LEV_STRENGTHEN_EQUITY_BASE`, `LEV_IMPROVE_INTEREST_COVERAGE`).
- **Conflict group sayısı:** **0** (`RECOMMENDATION_CONFLICT_PAIRS` v1'de
  KASITLI BOŞ, Bölüm 13.2).
- **Mutually-exclusive group sayısı:** **1** (`MEG_INVENTORY_LEVEL` —
  `WC_REDUCE_INVENTORY_DAYS`/`WC_MAINTAIN_INVENTORY_SAFETY_BUFFER`).
- **Merge group sayısı:** **6** (`MG_LIQUIDITY_STRAIN`, `MG_HIGH_
  LEVERAGE`, `MG_DEBT_SERVICE_STRESS`, `MG_WEAK_PROFIT_MARGIN`,
  `MG_WORKING_CAPITAL_STRAIN`, `MG_DEBT_FUNDED_GROWTH`) — HER biri TAM
  OLARAK 2 kural (1 BANKING_READINESS + 1 fonksiyonel) İÇERİR, toplam
  12/39 kural bir merge group'a ÜYEDİR.
- **Prerequisite/blocking ilişkisi sayısı:** **0** — mekanizma (Bölüm
  8.1/8.2 madde 10, Bölüm 12 Adım 14) TAM implemente/test edilir, v1
  envanterinde HİÇBİR kural bu alanları DOLU taşımaz (dürüst beyan,
  Bölüm 8.1'in "icat etme" disiplini).
- **Kapsanan sinyal sayısı:** 48 benchmark sinyalinden **25**'i
  (`related_ratio_codes` üzerinden), + BANKING_READINESS 6/6 flag, +
  DATA_QUALITY 10/10 kaynak = TOPLAM **41/58** girdi sinyali (48
  benchmark + 6 banking flag + 4 data-gap = 58 olası kaynak).
- **Kapsanmayan sinyal sayısı (`uncovered_signal_codes`):** benchmark
  sinyallerinden **23** (Bölüm 20b'nin TAM gerekçeli tablosu) —
  BANKING_READINESS/DATA_QUALITY kaynaklarında kapsanmayan YOKTUR.
- **Confidence modelinin nihai şekli:** min-ceiling modeli (Bölüm 15.4
  madde a-h) — evidence reliability ceiling'i, rule `confidence_
  ceiling`'i, provisional ceiling'i (0.75), coverage ceiling'inin
  (1.00/0.75/0.50) EN DÜŞÜĞÜ; ortalama/çarpım DEĞİL; `DATA_QUALITY`
  item'ları SABİT `1.00`; `confidence`≠`coverage` (ayrı alanlar).
- **Coverage/hard-fail exception davranışı:** `coverage_policy=
  exempt_hard_fail` kuralları kategori coverage'ından BAĞIMSIZ ÜRETİLİR
  (Bölüm 12 Adım 7-8); `always_evaluated` (`DATA_QUALITY`) kuralları
  ZATEN coverage-bağımsızdır; `subject_to_gate` (diğer 37 kural)
  `category_coverage>=0.50` GEREKTİRİR.
- **Simülasyonun bulunmadığının teyidi:** Bölüm 19.1-19.3 — `analyze_
  financial_ratios`/`evaluate_benchmarks`/`compute_financial_health_
  score`/`compute_credit_score` pipeline'ın HİÇBİR adımında (Bölüm 12,
  20 adım) ÇAĞRILMAZ (Adım 19'un `INVARIANT: RECOMMENDATION_ENGINE_
  READ_ONLY` testiyle KANITLANACAK); `RecommendationDirectionalContext`
  YALNIZCA ZATEN HESAPLANMIŞ tier/ideal_direction okur, SIFIR sayısal
  değer üretir.
- **Schema/version compatibility davranışı:** `RECOMMENDATION_INPUT_
  COMPATIBILITY` (Bölüm 16.1) — şema uyumsuzluğunda `SCHEMA_
  INCOMPATIBLE` (HİÇBİR öneri), registry-versiyon uyumsuzluğunda
  `VERSION_MISMATCH` (YALNIZCA `DATA_QUALITY`), yalnızca model_version
  farkında `MODEL_VERSION_MISMATCH` uyarısıyla NORMAL devam (Bölüm
  16.2).

### 37.2 Production Readiness (NİHAİ)

- **Tasarım tamlığı: ~%98.** Bölüm 33'teki TÜM maddeler kapatıldı;
  Bölüm 20a'nın 39 kuralı placeholder İÇERMİYOR; pipeline 20 adımda
  KESİNLEŞTİ; confidence/compatibility/kategori/trigger modelleri TAM
  TANIMLI. Kalan %2, implementasyon sırasında KAÇINILMAZ olarak ortaya
  çıkabilecek küçük, ÖNGÖRÜLEMEYEN ayrıntılar içindir (ör. gerçek Python
  tip-imza detayları) — bunlar TASARIM KARARI değil, KODLAMA detayıdır.
- **Fonksiyonel/implementasyon: %0** — bu turda da hiçbir kod satırı
  yazılmadı.

### 37.3 İmplementasyona hazır mı? (NİHAİ DEĞERLENDİRME)

**Teknik/mimari açıdan: EVET.** Bölüm 33'te bekleyen HİÇBİR açık karar
YOKTUR; Bölüm 20a'nın 39 kuralı TAM alan setiyle (29 alan/kural)
yazılmıştır; registry referans bütünlüğü (Bölüm 8.2'nin 12 maddesi) HER
kural için doğrulanabilir durumdadır; pipeline'ın 20 adımı KESİNDİR.
Bu, dokümanın implementasyona teknik olarak HAZIR olduğu anlamına gelir.

**Prosedürel olarak: Kullanıcının AYRI ve AÇIK "başla" talimatı
BEKLENMEKTEDİR** — bu turun kendi talimatı ("Revizyon tamamlandıktan
sonra... raporlanacak", "İmplementasyona başlama") KESİN OLARAK
implementasyonu bu mesajda İSTEMEMİŞTİR; yalnızca doküman revizyonu ve
rapor istenmiştir. Bu, projenin baştan beri uyguladığı disiplinin
(4.3D/4.3E/4.3F'nin TÜM turlarında) AYNI, KESİNTİSİZ devamıdır.

### 37.4 Kod/test/migration/API/adapter/commit/push teyidi

Bu turda (ve önceki 4.3F turlarının TAMAMINDA) `docs/FINOS_MILESTONE_
4_3F_RECOMMENDATION_ENGINE_DESIGN.md` DIŞINDA hiçbir dosya
değiştirilmedi. Hiçbir kod, test, migration, API, adapter yazılmadı.
Hiçbir commit veya push yapılmadı — bkz. bu mesajın sonundaki GİT
STATUS raporu.

**Kullanıcının açık ve ayrı "başla" talimatı OLMADAN hiçbir kod/test/
migration/API/adapter YAZILMAYACAKTIR.**
