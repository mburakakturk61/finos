# Milestone 4.3D — Financial Health Score Teknik Tasarımı

**Durum: TASARIM AŞAMASI — KARARLAR KİLİTLENDİ (4. tur) — SON ONAY BEKLİYOR**

Bu doküman yalnızca Milestone 4.3D'nin (Financial Health Score) teknik
tasarımını içerir. **Hiçbir kod yazılmadı, hiçbir dosya değiştirilmedi,
hiçbir migration oluşturulmadı, hiçbir test yazılmadı, hiçbir commit
yapılmadı.** Bu dokümandaki tüm dataclass/fonksiyon tanımları, dosya
yolları, ağırlık/eşik değerleri **önerilen/onaylanan bir tasarımdır** --
implementasyon yalnızca bu doküman son onay aldıktan SONRA başlayacaktır.

Bu, ikinci turdaki bağımsız mimari incelemenin bulgularını çözen 3. tur
revizyonun ARDINDAN, kullanıcının Bölüm 22'deki tüm açık kararları
**bağlayıcı kararlarla KİLİTLEDİĞİ** 4. ve son karar turudur. Bölüm 22
artık "Açık Kararlar" değil, **"Onaylanmış Kararlar"** başlığı taşır --
18 kararın TAMAMI, aşağıdaki 7 alanlı formatla tek tek kapatılmıştır:
(1) Karar başlığı, (2) Alternatifler, (3) Onaylanan seçenek, (4)
Gerekçe, (5) Risk, (6) Gelecekte değiştirilebilir mi?, (7) İmplementasyon
planındaki etkisi.

Bu milestone, kullanıcının kendi tanımıyla **FINOS'un en kritik karar
motorudur**. Bu ilk sürüm TAMAMEN heuristiktir (`provisional=True`
dürüstlük ilkesinin doğal devamı) -- makine öğrenmesi YOK, LLM YOK,
istatistiksel model YOK, online veri YOK.

---

## 0. Ön inceleme özeti (mevcut kod tabanı, bu tasarımın dayandığı gerçek zemin)

- `app/engines/common/ratio_formulas.py::RATIO_REGISTRY` — **57 kayıtlı
  oran**, 7 kategori (`liquidity`=7, `leverage`=10, `profitability`=11,
  `activity`=10, `efficiency`=6, `growth`=7, `cash_flow`=6).
  `RATIO_REGISTRY_VERSION="1.1.0"`. `ComputationStatus`: calculated/
  missing_input/undefined_zero_denominator/no_obligation/not_applicable/
  not_calculable. `reliability`: high/medium/medium_low/low/
  not_calculable.
- `app/engines/common/benchmark_types.py` + `benchmark_registry.py` --
  `BENCHMARK_REGISTRY` (57 kayıtlı orandan `unit=currency` olanlar VE
  her-zaman-`not_calculable` olanlar ÇIKARILARAK oluşur -- kesin sayı
  bu dokümanda ASLA sabit yazılmaz, bkz. Bölüm 0.1). Her girdi
  `source="internal_heuristic"`, `provisional=True`,
  `reliability_ceiling="medium"` (büyüme kategorisinde `"medium_low"`)
  taşır. `ideal_direction`: higher_is_better/lower_is_better/
  range_is_better.
- `app/engines/benchmarks/service.py::evaluate_benchmarks()` — saf,
  bağımsız bir kütüphane fonksiyonu (2. tur onay karar #6, 4.3C).
- **Kritik, tekrar eden bir yapısal gerçek:** `current_ratio` ve
  `working_capital_ratio` BİREBİR AYNI formülü paylaşır -- bu, çok daha
  geniş bir "duplicate/derived sinyal" ailesinin yalnızca bir üyesidir
  (bkz. Bölüm 8.1 — bu 4. turda NİHAİ olarak KİLİTLENMİŞ sınıflandırma).
- Henüz kayıtlı olmayan/boş kategoriler: `investment`, `market`,
  `banking`, `ifrs`, `risk`, `capital_structure`, `working_capital` (4.3E/
  F/G'nin kapsamı, `RATIO_REGISTRY`'de HİÇ yok).
- `Company` modelinde `sector`/`nace_code` var, `country`/şirket ölçeği
  alanı YOK; **`tenant`/çok-kiracılı bir kavram platformun HİÇBİR
  yerinde YOK.**

### 0.1 Terminoloji — registry'den türetilen sayılar (sabit sayı YOK)

```python
benchmarkable_ratio_count = len(BENCHMARK_REGISTRY)
# -- BENCHMARK_REGISTRY'nin o ANKİ toplam girdi sayısı.

duplicate_ratio_count = len([
    m for m in RATIO_SCORE_WEIGHTS.values() if m.ratio_weight == 0
])
# -- Bölüm 8.1'de "explainability-only" (ratio_weight=0) işaretlenen
# oranların sayısı.

scoreable_ratio_count = benchmarkable_ratio_count - duplicate_ratio_count
# -- Health Score'un GERÇEKTEN puanlama evreni (ratio_weight > 0).
```

Dokümanda geçen her sayı bu formüllerin ÇALIŞMA ANINDA hesaplanmış bir
ANLIK GÖRÜNTÜSÜDÜR -- formüllerin kendisi asla sabit sayıya indirgenmez.

## 1. Amaç

`Ratio Engine` (4.3A/B) ve `Benchmark Engine`'in (4.3C) ürettiği,
birbirinden bağımsız oran+tier bilgisini tek, **açıklanabilir**,
**deterministik**, **versiyonlanabilir** bir Financial Health Score'a
(0-100, 1 ondalık -- Bölüm 22 karar #1) birleştirmek. Her puan, hangi
oranın hangi tier'a düştüğüne, hangi ağırlıkla katkı verdiğine ve hangi
kural(lar)ın devreye girdiğine kadar GERİYE İZLENEBİLİR olmalıdır.

## 2. Kapsam

**Kapsam İÇİNDE:** tek sayısal skor (0-100, 1 ondalık) + 6-kademeli
Türkçe rating (Bölüm 16); 6 aktif kategori alt-skoru; kategori
ağırlıkları (Bölüm 8, v1 sabit değerler) + merkezi registry'de tanımlı
kategori-içi `ratio_weight`ler (Bölüm 11-nolu karar, eşit ağırlık YOK);
geleceğe dönük override mimarisi (global/industry/company_size/tenant,
Bölüm 8.2, YALNIZCA global aktif); duplicate/derived sinyal filtreleme
(Bölüm 8.1, nihai sınıflandırma); eksik veri yeniden ağırlıklandırması +
coverage eşikleri (%50/%70, Bölüm 9/11); ayrı confidence + data
coverage (Bölüm 10/11); 2 hard-fail kuralı (Bölüm 12); oransal
çarpanlı critical override (Bölüm 13); tier içi doğrusal interpolasyon +
kontrollü sabit fallback (Bölüm 6.2); tam explainability modeli (Bölüm
14); 4 eksenli versiyonlama (Bölüm 17, `health_score_schema_version`
dahil).

**Kapsam DIŞINDA (bu doküman TASARLAMAZ/implemente ETMEZ, Bölüm 22
karar #10/#17/#18 ile KİLİTLENDİ):**

- **API YOK, adapter YOK, bulk upload/recompute bağlantısı YOK, DB
  persistence YOK** -- saf kütüphane fonksiyonu olarak kalır.
- Credit Score, Recommendation Engine (4.3E/4.3F'nin konusu).
- **AI/LLM YOK** -- strengths/weaknesses metinleri STRING TEMPLATE'tir.
- **Tenant/industry override AKTİVASYONU YOK** -- yalnızca `global`
  profili dolu, diğer 3 seviye yalnızca veri sözleşmesi/hook (Bölüm 8.2).
- Gerçek Türkiye sektör verisiyle kalibrasyon.
- `cash_flow`/`investment`/`market`/`banking`/`ifrs`/`risk`/
  `capital_structure`/`working_capital` kategorilerinin skora dahil
  edilmesi.
- **Trend/monotonluk katmanı** -- `previous_score`/`score_delta`/
  `coverage_delta` gibi alanlar 4.3D'de İMPLEMENTE EDİLMEZ (Bölüm 15,
  açıkça kapsam dışı not).

## 3. Faz sınırları

**Bu TASARIM fazında:** sıfır kod, sıfır dosya değişikliği, sıfır
migration, sıfır test, sıfır commit. 4.3E (Bankacılık+Risk+Credit
Score), 4.3F (Çalışma Sermayesi+Öneri altyapısı), 4.3G (Yatırım/Piyasa/
IFRS/Sermaye Yapısı) İÇERİKLERİ DEĞİŞMEDEN kalır.

## 4. Mimari

### 4.1 Katman sırası ve girdi sözleşmesi

```
Ratio Engine (result_json)  ──┐
                               ├──▶  Financial Health Score (bu milestone)
Benchmark Engine (result_json)┘
```

Financial Health Score'un pipeline'ı YALNIZCA iki girdi alır --
`ratio_result_json` ve `benchmark_result_json`. Hard-fail/critical-
override predicate'leri hem `ratio_result_json`'daki DEĞERLERİ hem
`benchmark_result_json`'daki TIER'ları okuyabilir -- ikisi de sanksiyonlu
iki motorun İÇİNDEDİR, üçüncü bir motora/ham BS-IS alanına HİÇBİR ZAMAN
erişilmez.

Tier içi doğrusal interpolasyon (Bölüm 6.2) nedeniyle Health Score,
`BENCHMARK_REGISTRY`'nin KENDİSİNDEN (yalnızca serileştirilmiş JSON'dan
DEĞİL) `BenchmarkThresholds` sınır değerlerini okur -- bu, HÂLÂ "yalnızca
Ratio+Benchmark Engine" sınırının İÇİNDEDİR, üçüncü bir motor
EKLENMEZ.

### 4.2 Yeni dosyalar (önerilen, henüz oluşturulmadı)

```
app/engines/common/health_score_types.py     # dataclass'lar, enum'lar,
                                              # tier interpolation + fallback
app/engines/common/health_score_registry.py  # CATEGORY_WEIGHT_PROFILES
                                              # (yalnızca global dolu),
                                              # RATIO_SCORE_WEIGHTS
                                              # (ratio_weight'li, Bölüm 11),
                                              # HARD_FAIL_RULES (2 kural),
                                              # CRITICAL_OVERRIDE_RULES
                                              # (oransal çarpan)
app/engines/health_score/service.py          # compute_financial_health_
                                              # score(ratio_result_json,
                                              # benchmark_result_json, ...)
```

**Süreklilik kararı (Bölüm 22 karar #10, ONAYLANDI):** saf kütüphane,
API/adapter/migration YOK.

## 5. Veri modeli

```python
class HealthScoreTier(str, enum.Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    WEAK = "weak"
    CRITICAL = "critical"


class HealthScoreComputationStatus(str, enum.Enum):
    COMPUTED = "computed"
    HARD_FAIL_CAPPED = "hard_fail_capped"
    INSUFFICIENT_DATA = "insufficient_data"  # coverage < %50 (Bölüm 11)


@dataclass(frozen=True)
class CategoryWeightProfile:
    scope: str                       # "global" | "industry" | "company_size" | "tenant"
    scope_key: "str | None"
    category_weights: dict[str, Decimal]


@dataclass(frozen=True)
class RatioScoreWeight:
    ratio_code: str
    category: str
    ratio_weight: Decimal            # Bölüm 11: kategori içinde normalize, duplicate=0
    excluded_as_duplicate_of: "str | None" = None
    duplicate_relationship: "str | None" = None
    # "identical_formula" | "algebraic_complement" |
    # "reciprocal_via_period_constant" | "summary_signal_normalized"


@dataclass(frozen=True)
class HardFailRule:
    rule_code: str
    predicate: "Callable[[dict, dict], bool]"  # (ratios, benchmarks) -> bool
    score_ceiling: Decimal
    rationale_tr: str


@dataclass(frozen=True)
class CriticalOverrideRule:
    ratio_code: str
    category: str
    weak_multiplier: Decimal          # 0.90 (Bölüm 13)
    critical_multiplier: Decimal      # 0.70 (Bölüm 13)
    rationale_tr: str


@dataclass(frozen=True)
class RatioContribution:
    ratio_code: str
    benchmark_status: str
    tier: "str | None"
    ratio_score: "Decimal | None"        # Bölüm 6.2 stratejisiyle üretilen puan
    ratio_weight_applied: Decimal        # redistribute SONRASI etkin ağırlık
    tier_fallback_used: bool             # YENİ: interpolasyon yerine sabit puan mı kullanıldı
    reliability: str
    is_duplicate_excluded: bool          # YENİ: explainability-only mu


@dataclass(frozen=True)
class CategoryBreakdown:
    category: str
    raw_score: "Decimal | None"                # clamp'li
    score_after_override: "Decimal | None"     # clamp'li
    weight_applied: Decimal
    coverage_ratio: Decimal
    redistributed_weights: dict[str, Decimal]  # YENİ: ratio_code -> etkin ağırlık
    critical_overrides_applied: tuple[str, ...]
    ratio_contributions: tuple[RatioContribution, ...]


@dataclass(frozen=True)
class HealthScoreResult:
    status: HealthScoreComputationStatus
    final_score: "Decimal | None"
    pre_hard_fail_score: "Decimal | None"
    letter_rating: "str | None"
    rating_disclaimer_tr: str             # "resmi kredi derecelendirmesi degildir"
    confidence_score: Decimal
    data_coverage_ratio: Decimal
    low_confidence_warning: bool          # YENİ: coverage %50-69.99 bandi
    provisional: bool
    category_breakdown: tuple[CategoryBreakdown, ...]
    hard_fails_triggered: tuple[str, ...]
    critical_overrides_applied: tuple[str, ...]
    scoreable_ratio_codes: tuple[str, ...]     # YENİ: explainability
    excluded_duplicate_ratio_codes: tuple[str, ...]  # YENİ
    strengths: tuple[dict, ...]
    weaknesses: tuple[dict, ...]
    warnings: tuple[dict, ...]
    health_score_schema_version: str      # YENİ (Bölüm 17)
    health_score_model_version: str
    benchmark_registry_version: str
    ratio_registry_version: str
    category_weight_profile_used: str     # "global" | "industry:X" | ...
```

## 6. Score pipeline (NİHAİ SIRA -- 4. tur bağlayıcı karar)

**Bağlayıcı sıra (kullanıcı tarafından TAM olarak belirlendi):**

**Aşama A — Ratio sonuçlarını oku.** `ratio_result_json`'dan her
`ratio_code` için ham değer + reliability çıkarılır.

**Aşama B — Benchmark sonuçlarını oku.** `benchmark_result_json`'dan her
`ratio_code` için `(benchmark_status, tier)` çıkarılır; bu adımda AYNI
ZAMANDA her kategori ve genel `data_coverage_ratio` hesaplanır
(EVALUATED sayısı / `scoreable_ratio_count`, Bölüm 0.1).

**Aşama B.5 — INSUFFICIENT_DATA kapısı (Bölüm 11, coverage burada
bilindiği için doğal konumu).** `data_coverage_ratio < 0.50` İSE:
pipeline BURADA DURUR -- `status=INSUFFICIENT_DATA`, `final_score=None`,
`letter_rating=None`. Aşama C-J çalışmaz; yalnızca coverage/confidence/
warnings alanları (teşhis amaçlı) doldurulur.

**Aşama C — Duplicate/derived sinyalleri filtrele.** `RATIO_SCORE_
WEIGHTS`'te `ratio_weight=0` (Bölüm 8.1'in nihai sınıflandırması)
işaretli oranlar puanlama havuzundan ÇIKARILIR -- yalnızca
`category_breakdown.ratio_contributions`'ta `is_duplicate_excluded=True`
ile GÖRÜNTÜLENMEK üzere kalırlar (explainability), sayısal skora
KATKI VERMEZLER.

**Aşama D — Oran puanlarını üret.** Kalan (scoreable) her oran için
Bölüm 6.2'deki strateji (doğrusal interpolasyon, gerekirse kontrollü
sabit fallback) uygulanarak `ratio_score` (0-100) üretilir.

**Aşama E — Kategori ham skorlarını üret.** Her kategoride, EVALUATED
scoreable oranların `ratio_score`'u, kendi `ratio_weight`i (Bölüm 9'daki
missing-data normalizasyonu SONRASI, yani yalnızca hesaplanabilenler
arasında yeniden normalize edilmiş ağırlıkla) ile ağırlıklı ortalaması
alınarak `raw_score` üretilir. Sıfır EVALUATED oranlı kategori
`raw_score=None` kalır (asla fabrike edilmez).

**Aşama F — Critical override'ları kategori seviyesinde uygula.** Bölüm
13'teki oransal çarpan modeli, HER KATEGORİNİN KENDİ `raw_score`'una
uygulanır (kategoriler arası ağırlıklandırmadan ÖNCE -- eski tasarımın
2. tur incelemede bulunan sıralama hatası burada KESİN olarak çözülmüş
durumda kalır).

**Aşama G — Her kategori skorunu [0,100] aralığına clamp et.**
`score_after_override = max(0, min(100, raw_score * combined_multiplier))`.

**Aşama H — Kategori ağırlıklarını uygula.** `score_after_override=None`
olan kategoriler dışlanır, kalan kategorilerin Bölüm 8/8.2'den çözümlenen
ağırlıkları KENDİ ARALARINDA yeniden normalize edilir → ağırlıklı
ortalama (`preliminary_score`).

**Aşama I — Hard fail tavanlarını uygula.** Bölüm 12'deki 2 kural
değerlendirilir; herhangi biri tetiklenirse `pre_hard_fail_score` =
Aşama H çıktısı SAKLANIR, `final_score = min(pre_hard_fail_score,
score_ceiling)`, `status=HARD_FAIL_CAPPED`.

**Aşama J — Final skoru [0,100] aralığına clamp et.**
`final_score = max(0, min(100, final_score))`.

**Aşama K — Rating, confidence, coverage ve explainability üret.**
Bölüm 10/11/14/16'daki tanımlarla `HealthScoreResult` doldurulur.

### 6.1 `TIER_TO_POINTS` (kontrollü fallback için sabit referans)

```python
TIER_TO_POINTS: dict[str, Decimal] = {
    "excellent": Decimal("100"),
    "good": Decimal("75"),
    "average": Decimal("50"),
    "weak": Decimal("25"),
    "critical": Decimal("0"),
}
```

### 6.2 Tier puanlama: doğrusal interpolasyon + kontrollü sabit fallback (BAĞLAYICI KARAR)

**Karar (Bölüm 22 karar #11/#12 ile kilitlendi):** varsayılan strateji
tier SINIRLARI arasında DOĞRUSAL İNTERPOLASYONDUR (cliff effect'i
gidermek için). **Ancak** ilgili benchmark bandı AÇIK UÇLUYSA (örn.
`higher_is_better`'da "excellent" bandının doğal bir üst referans
noktası yoksa) VEYA interpolasyon için gereken İKİ sınır noktası
mevcut DEĞİLSE (örn. `RANGE_IS_BETTER`'da bazı iç içe bant
konfigürasyonlarında ya da tek-sınırlı özel durumlarda), **kontrollü
sabit tier puanına (`TIER_TO_POINTS`) FALLBACK yapılır.**

```python
def continuous_points_higher_is_better(value, critical, weak, average, good):
    anchors = [(critical, Decimal("0")), (weak, Decimal("25")),
               (average, Decimal("50")), (good, Decimal("75"))]
    if value < critical:
        return Decimal("0"), False
    if value >= good:
        return Decimal("100"), False       # excellent bandi acik uclu -- ust sinirda kilitlenir
    for (lo_v, lo_p), (hi_v, hi_p) in zip(anchors, anchors[1:]):
        if lo_v <= value < hi_v:
            fraction = (value - lo_v) / (hi_v - lo_v)
            return lo_p + fraction * (hi_p - lo_p), False
    return TIER_TO_POINTS[tier_of(value)], True   # fallback -- iki sinir bulunamadi
```

`RANGE_IS_BETTER` için formülün TAMAMI implementasyon adım 4'te (tier
interpolation) netleştirilecektir -- bu doküman YAKLAŞIMI (interpolasyon
+ fallback) ve fallback'in AÇIKÇA işaretlenmesi zorunluluğunu sabitler,
`RANGE_IS_BETTER`'a özgü tam formülü değil (Bölüm 22 karar #12).

**Fallback KULLANILDIĞINDA, `RatioContribution.tier_fallback_used=True`
olarak Explainability çıktısında AÇIKÇA gösterilir** -- kullanıcı hangi
oranların "gerçek" interpolasyonla, hangilerinin sabit-puan fallback ile
puanlandığını HER ZAMAN görebilir.

Tier LABEL'ı (excellent/.../critical) Explainability ve hard-fail/
critical-override kural eşleştirmesi için HÂLÂ kullanılır; yalnızca
SAYISAL SKORA giren katkı artık (fallback dışında) sürekli hesaplanır.

## 7. Benchmark ile ilişki

(Değişmedi.) `BenchmarkComputationStatus`'un her değeri farklı
davranır: `EVALUATED` → Aşama D-E'de normal puanlama; `RATIO_STATUS_NOT_
CALCULATED` → scoreable paydaya dahil ama EVALUATED sayılmaz, ağırlığı
yeniden dağıtıma girer (Bölüm 9); `BENCHMARK_NOT_REGISTERED` →
`scoreable_ratio_count`'un dışındadır.

## 8. Kategori ağırlıkları (v1 -- BAĞLAYICI KARAR)

**Onaylanan v1 GLOBAL ağırlıkları** (Bölüm 22 karar #7,
`CategoryWeightProfile(scope="global", scope_key=None, ...)`):

| Kategori | Ağırlık |
|---|---|
| Likidite (liquidity) | %20 |
| Borçluluk (leverage) | %25 |
| Kârlılık (profitability) | %20 |
| Faaliyet (activity) | %15 |
| Verimlilik (efficiency) | %10 |
| Büyüme (growth) | %10 |
| Nakit Akışı (cash_flow) | **%0 (yapısal, Cash Flow Engine yok)** |

Bu ağırlıklar `provisional=True` ve `health_score_model_version`e
bağlıdır -- değiştiğinde model versiyonu YÜKSELTİLİR (Bölüm 17).

**Kategori-içi oran ağırlıkları (Bölüm 22 karar #8, BAĞLAYICI):** EŞİT
AĞIRLIK KULLANILMAZ. Her scoreable sinyal için `health_score_registry.
py`'de merkezi bir `ratio_weight` tanımlanır; bir kategorideki tüm
`ratio_weight`lerin toplamı NORMALİZE edilerek 1.00 yapılır.
Explainability-only (duplicate/derived, Bölüm 8.1) sinyallerin
`ratio_weight` değeri HER ZAMAN 0'dır. Kesin sayısal `ratio_weight`
değerleri implementasyon Adım 2'de (`health_score_registry.py`)
tanımlanacaktır -- bu doküman METODOLOJİYİ sabitler, tek tek sayısal
tabloyu DEĞİL (kod yazılmadığı için).

## 8.1 Duplicate Signal Analizi (NİHAİ SINIFLANDIRMA -- BAĞLAYICI KARAR)

Kullanıcının 4. tur bağlayıcı kararıyla, 12 oranın sınıflandırması
NİHAİ olarak şu şekilde KİLİTLENMİŞTİR ("aynı ekonomik sinyal bir kez
puanlanacak" ilkesi):

| # | ratio_code | ratio_weight | Sınıflandırma / Gerekçe |
|---|---|---|---|
| 1 | `current_ratio` | **> 0 (scored)** | Likidite kategorisinin temel sinyali. |
| 2 | `working_capital_ratio` | **0 (explainability-only)** | current_ratio ile BİREBİR AYNI formül (`identical_formula`). |
| 3 | `equity_ratio` | **> 0 (scored, ANA sinyal)** | Sermaye yapısı grubunun ana temsilcisi olarak SEÇİLDİ. |
| 4 | `debt_ratio` | **0 (explainability-only)** | `= 1 - equity_ratio` (`algebraic_complement`) -- destekleyici/açıklama amaçlı kalır, ayrıca skora GİRMEZ. |
| 5 | `financial_leverage_multiplier` | **0 (explainability-only)** | `= 1/equity_ratio` (`algebraic_complement` zincirinin devamı) -- destekleyici/açıklama amaçlı kalır. |
| 6 | `inventory_turnover` | **> 0 (scored)** | Faaliyet kategorisinin stok-verimliliği sinyali. |
| 7 | `days_inventory_outstanding` | **0 (explainability-only)** | `= days_in_period / inventory_turnover` (`reciprocal_via_period_constant`). |
| 8 | `receivables_turnover` | **> 0 (scored)** | Tahsilat verimliliği sinyali. |
| 9 | `days_sales_outstanding` | **0 (explainability-only)** | `reciprocal_via_period_constant`. |
| 10 | `payables_turnover` | **0 (explainability-only)** | Bu turda `days_payables_outstanding` LEHİNE tercih EDİLMEDİ -- ödeme disiplini sinyali artık GÜN CİNSİNDEN (DPO) puanlanıyor, `payables_turnover` yalnızca açıklama amaçlı kalır. |
| 11 | `days_payables_outstanding` | **> 0 (scored)** | Ödeme disiplini sinyalinin SEÇİLEN temsilcisi (`= days_in_period / payables_turnover`, ama bu turda bilinçli olarak payables_turnover YERİNE tercih edildi -- CFO iletişiminde "gün" birimi daha sezgisel). |
| 12 | `cash_conversion_cycle` | **> 0 (scored, bağımsız özet sinyal)** | `= DIO + DSO - DPO` -- matematiksel olarak türetilmiş bir bileşik olsa da, bilinçli bir ÜRÜN kararıyla BAĞIMSIZ bir özet sinyal olarak puanlanır (CFO'lar için tek bakışta nakit döngüsü göstergesi). **Bunun getirdiği bilgi-çakışması riski, aşağıdaki ağırlık normalizasyonu ile YÖNETİLİR.** |

**Ağırlık normalizasyon kuralı (12 numaralı satırın gereği):** Activity
kategorisinde artık 4 scored sinyal var (`inventory_turnover`,
`receivables_turnover`, `days_payables_outstanding`,
`cash_conversion_cycle`) -- ama CCC, DIO/DSO/DPO'nun (dolayısıyla dolaylı
olarak inventory_turnover/receivables_turnover/DPO'nun) bir fonksiyonu
olduğu için, bu 4 sinyalin `ratio_weight`leri EŞİT DAĞITILMAZ: CCC'ye,
diğer 3 BAĞIMSIZ bileşenin toplamından DAHA DÜŞÜK bir `ratio_weight`
verilerek (`duplicate_relationship="summary_signal_normalized"`
işaretiyle), activity kategorisinin "aynı bilgiyi 4 kez sayma" riski
azaltılır -- kesin sayısal oran implementasyon Adım 2/3'te (duplicate
signal ve ağırlık validasyonları) belirlenecektir.

**Sonuç:** 12 oran incelendi → **6 scored** (current_ratio, equity_ratio,
inventory_turnover, receivables_turnover, days_payables_outstanding,
cash_conversion_cycle), **6 explainability-only** (working_capital_ratio,
debt_ratio, financial_leverage_multiplier, days_inventory_outstanding,
days_sales_outstanding, payables_turnover). `duplicate_ratio_count`/
`scoreable_ratio_count` bu tablodan DİNAMİK türetilir (Bölüm 0.1),
dokümanda sabit sayı YAZILMAZ.

**Kapsam dürüstlüğü (değişmedi):** bu analiz yalnızca kullanıcının
listelediği 12 oranla SINIRLIDIR. Kalan `benchmarkable_ratio_count - 12`
oranın (özellikle `debt_to_equity`'nin `equity_ratio` ailesiyle olası
ilişkisinin) TAM denetimi bu turda YAPILMADI -- Bölüm 22 karar #16 ile
GELECEĞE ertelendiği resmen kapatıldı.

## 8.2 Kategori Ağırlığı Override Mimarisi (tasarım-only, implementasyon YOK)

**Çözümleme sırası (Bölüm 22 karar #17 ile KİLİTLENDİ):** `tenant >
industry > company_size > global`.

```python
@dataclass(frozen=True)
class CategoryWeightProfile:
    scope: str
    scope_key: "str | None"
    category_weights: dict[str, Decimal]


CATEGORY_WEIGHT_PROFILES: dict[tuple[str, str], CategoryWeightProfile] = {
    ("global", None): CategoryWeightProfile(
        scope="global", scope_key=None,
        category_weights={...},  # Bölüm 8 tablosu
    ),
    # industry/company_size/tenant seviyeleri: BU TURDA HİÇBİR KAYIT
    # EKLENMEZ -- yalnızca resolve_category_weights()'in imzası ve
    # cözümleme SIRASI tasarlanır (asagida). Bos "placeholder" kod
    # (bos dict girdileri, bos sozluk populate eden fonksiyonlar vb.)
    # BILINCLI OLARAK URETILMEZ -- yalnizca VERI SOZLESMESI/HOOK
    # (fonksiyon imzasi + cozumleme sirasi) tasarlanir.
}


def resolve_category_weights(
    *, industry_code=None, company_size_bucket=None, tenant_id=None,
) -> CategoryWeightProfile:
    if tenant_id and (p := CATEGORY_WEIGHT_PROFILES.get(("tenant", tenant_id))):
        return p
    if industry_code and (p := CATEGORY_WEIGHT_PROFILES.get(("industry", industry_code))):
        return p
    if company_size_bucket and (p := CATEGORY_WEIGHT_PROFILES.get(("company_size", company_size_bucket))):
        return p
    return CATEGORY_WEIGHT_PROFILES[("global", None)]
```

**4.3D'de NE YAPILIR, NE YAPILMAZ (Bölüm 22 karar #17/#18 ile kesinleşti):**
- YAPILIR: yalnızca `("global", None)` DOLU. `resolve_category_weights()`
  fonksiyonunun İMZASI ve ÇÖZÜMLEME SIRASI (tenant>industry>company_
  size>global) tasarlanır/implemente edilir.
- YAPILMAZ: `tenant_id`'nin platformda HİÇBİR karşılığı YOK -- bu
  parametre TAMAMEN ileriye-dönük bir veri sözleşmesidir, "aktivasyon"
  (gerçek tenant/industry override KAYDI oluşturma) bu fazın KAPSAMI
  DIŞINDADIR. Boş/anlamsız placeholder KOD (ör. `{}` ile önceden
  doldurulmuş sahte kayıtlar) ÜRETİLMEZ.

## 9. Missing data yeniden ağırlıklandırması ve coverage eşikleri (BAĞLAYICI KARAR)

**İki seviyeli yeniden dağıtım (değişmedi):**

1. **Kategori-içi:** bir kategorideki eksik (EVALUATED olmayan)
   sinyallerin `ratio_weight`i, o kategoride HESAPLANABİLEN sinyaller
   arasında ORANTILI olarak yeniden dağıtılır.
2. **Kategoriler arası:** tamamen eksik (sıfır EVALUATED sinyalli) bir
   kategori, kategoriler arası ağırlıklandırmadan (Aşama H) ÇIKARILIR;
   ağırlığı, hesaplanabilen kalan kategoriler arasında ORANTILI
   dağıtılır.

**Coverage eşikleri (Bölüm 22 karar #15 ile KİLİTLENDİ, Bölüm 11 ile
bağlantılı):**
- `data_coverage_ratio < %50` → **skor üretilmez**, `status=
  INSUFFICIENT_DATA`, `final_score=null`, `letter_rating=null`.
- `%50 <= data_coverage_ratio < %70` → skor ÜRETİLİR, ama
  `low_confidence_warning=True` ZORUNLU olarak `HealthScoreResult`'a
  yazılır.
- `data_coverage_ratio >= %70` → normal hesaplama, uyarı yok.

## 10. Confidence modeli (BAĞLAYICI KARAR)

**Girdi faktörleri (Bölüm 22 karar #13 ile KİLİTLENDİ):** benchmark
reliability, ratio reliability, average-balance fallback kullanımı
(4.3B'den), benchmark'ın `provisional=True` olması, eksik KRİTİK
girdilerin varlığı.

```
confidence_score = min(
    weighted_average(reliability_rank(r) for r in evaluated_ratios),
    PROVISIONAL_CONFIDENCE_CEILING,  # = 0.60 (asagida)
)
```

**`PROVISIONAL_CONFIDENCE_CEILING = 0.60`** (önceki turda önerilen 0.70
DEĞİL) -- gerekçe: `BENCHMARK_REGISTRY`'nin TAMAMI `internal_heuristic`/
`provisional=True` olduğundan, bir skorun HİÇBİR ZAMAN "yüksek güven"
iddia edemeyeceği daha SIKI bir tavanla ifade edilir.

**Coverage confidence DEĞİLDİR ve confidence formülüne DOĞRUDAN
EŞİTLENMEZ** (Bölüm 22 karar #3 ile ayrı tutulmaya devam eder) -- ikisi
`HealthScoreResult`'ta AYRI alanlardır (`confidence_score`,
`data_coverage_ratio`).

## 11. Data coverage modeli ve INSUFFICIENT_DATA (BAĞLAYICI KARAR)

`data_coverage_ratio = (EVALUATED oran sayısı) / scoreable_ratio_count`
(Bölüm 0.1, sabit sayı YOK).

`INSUFFICIENT_DATA_COVERAGE_THRESHOLD = Decimal("0.50")` --
Bölüm 9'daki üç bantlı davranış (< %50 skor yok / %50-69.99 uyarılı skor
/ >= %70 normal) burada RESMİ olarak sabitlenmiştir (Bölüm 22 karar #15).
Eksik veri, HİÇBİR ZAMAN hard-fail olarak yorumlanmaz -- yalnızca
confidence/coverage/warnings üzerinden raporlanır (Bölüm 12).

## 12. Hard fail kuralları v1 (BAĞLAYICI KARAR -- 2 KURAL)

**Kural 1: NEGATIVE_EQUITY.**

```python
HardFailRule(
    rule_code="NEGATIVE_EQUITY",
    predicate=lambda ratios, benchmarks: ratios.get("equity_ratio") is not None
                                          and ratios["equity_ratio"] < 0,
    score_ceiling=Decimal("25"),   # onceki turda 30 idi, bu turda 25'e KILITLENDI
    rationale_tr=(
        "Özkaynak negatif -- TTK madde 376 kapsamında 'sermaye kaybı/"
        "borca batıklık' bölgesine işaret eder. Diğer kategorilerdeki "
        "güçlü performansla TELAFİ EDİLEMEZ."
    ),
)
```

**Kural 2: SEVERE_DEBT_SERVICE_SHORTFALL (2. tur incelemenin önerdiği
`STRUCTURAL_UNPROFITABILITY` kuralının YERİNE, bu turun bağlayıcı
kararıyla).**

```python
HardFailRule(
    rule_code="SEVERE_DEBT_SERVICE_SHORTFALL",
    predicate=lambda ratios, benchmarks: ratios.get("interest_coverage_ratio") is not None
                                          and ratios["interest_coverage_ratio"] < 0,
    score_ceiling=Decimal("35"),
    rationale_tr=(
        "Faiz karşılama oranı HESAPLANMIŞ ve NEGATİF -- şirket faaliyet "
        "kârıyla faiz giderini dahi karşılayamıyor. Ciddi bir borç "
        "servis riski sinyalidir, diğer kategorilerle TAM telafi "
        "edilemez."
    ),
)
```

**Eksik veri hard-fail olarak yorumlanmaz (BAĞLAYICI netleştirme):** her
iki predicate de, ilgili oran `None`/hesaplanamamışsa `False` döner --
yani "veri eksik" hiçbir zaman "hard fail tetiklendi" ile
KARIŞTIRILMAZ. Eksik kritik girdi yalnızca confidence/coverage/warnings
üzerinden raporlanır (Bölüm 10/11).

Bu iki kuralla v1 SINIRLI tutulur -- proliferasyon riski (Bölüm 21)
kontrollü kalır.

## 13. Critical override kuralları (BAĞLAYICI KARAR -- oransal çarpan modeli)

**Sabit puan/yüzde cezası TAMAMEN TERK EDİLDİ -- yerine kategori skoruna
ORANSAL ÇARPAN uygulanır:**

```python
CRITICAL_OVERRIDE_WEAK_MULTIPLIER: Decimal = Decimal("0.90")
CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER: Decimal = Decimal("0.70")
CRITICAL_OVERRIDE_CATEGORY_FLOOR: Decimal = Decimal("0.50")

# Aşama F (Bölüm 6): bir kategoride tetiklenen HER override kuralının
# (tier="weak" ise 0.90, tier="critical" ise 0.70) çarpanları ÇARPILIR,
# ama SONUÇ asla CATEGORY_FLOOR'un ALTINA düşürülmez:
combined_multiplier = max(
    math.prod(triggered_multipliers) if triggered_multipliers else Decimal("1"),
    CRITICAL_OVERRIDE_CATEGORY_FLOOR,
)
score_after_override = max(0, min(100, raw_score * combined_multiplier))
```

Bu, "aynı kategoride birden fazla critical tetiklenirse çarpanlar
SINIRSIZ çarpılmayacak" kuralını (çarpımın kendisi bounded, floor=0.50
ile sınırlanmış) ve "kategori başına minimum çarpan tabanı 0.50" kuralını
BİRLİKTE karşılar. Sonuç HER ZAMAN `[0,100]` aralığına clamp edilir
(Aşama G).

**v1 önerilen kural listesi:**

| ratio_code | category | weak → | critical → | gerekçe |
|---|---|---|---|---|
| `current_ratio` | liquidity | ×0.90 | ×0.70 | Temel ödeme gücü sinyali |
| `debt_to_equity` | leverage | ×0.90 | ×0.70 | Klasik kaldıraç red flag'i (Bölüm 8.1 yan bulgusu -- equity_ratio ailesiyle olası ilişkisi Bölüm 22 karar #16'da gelecek denetime bırakıldı) |
| `interest_coverage_ratio` | leverage | ×0.90 | ×0.70 | Borç servisi yetersizliği (Hard Fail Kural 2 ile TAMAMLAYICI, kesişmeyen bir erken-uyarı sinyali) |
| `net_profit_margin` | profitability | ×0.90 | ×0.70 | Temel kârlılık sinyali |
| `cash_conversion_cycle` | activity | ×0.90 | ×0.70 | CCC artık scored bir sinyal olduğu için (Bölüm 8.1) activity kategorisi için critical-override temsilcisi olarak GERİ EKLENDİ (Bölüm 22 karar #18) |

## 14. Explainability modeli (BAĞLAYICI KARAR -- zorunlu alan listesi)

Her `HealthScoreResult` şu alanları ZORUNLU olarak taşır (Bölüm 22
karar #14 ile kilitlendi):

- `health_score_schema_version`, `health_score_model_version`,
  `ratio_registry_version`, `benchmark_registry_version`
- `scoreable_ratio_codes`, `excluded_duplicate_ratio_codes` (+ her
  duplicate için `duplicate_relationship` gerekçesi)
- her scored oran için: `ratio_score`, `ratio_weight_applied`,
  `tier_fallback_used`
- her kategori için: `raw_score`, `score_after_override`,
  `redistributed_weights`
- `hard_fails_triggered`, `critical_overrides_applied`
- `final_score`, `confidence_score`, `data_coverage_ratio`,
  `low_confidence_warning`
- `warnings` (Ratio Engine + Benchmark Engine + Health Score
  seviyelerinin birleşimi)

## 15. Strengths / Weaknesses üretimi ve Monotonluk notu

**Strengths/weaknesses (değişmedi, N kararı bu turda kullanıcı
tarafından belirtilmedi -- Bölüm 22 karar #13'te kapatılan varsayılan:
N=5).** Aday havuzu yalnızca `ratio_weight>0` (scored, duplicate
OLMAYAN) oranlardır.

**Monotonluk (BAĞLAYICI netleştirme, Bölüm 22'nin dışında ama bu turda
eklendi):** Daha fazla veri geldiğinde (yeni dönem, önceki eksik bir
oranın hesaplanabilir hale gelmesi vb.) skorun DEĞİŞEBİLECEĞİ -- hatta
BAZEN düşebileceği -- açıkça KABUL EDİLİR. Bu bir HATA olarak
gizlenmez; skor, o anki mevcut veriye göre dürüst bir hesaplamadır,
"veri arttıkça skor sadece iyileşir" gibi YANLIŞ bir monotonluk garantisi
VERİLMEZ.

`previous_score`, `score_delta`, `coverage_delta` gibi alanlar
GELECEKTE bir trend katmanında gösterilecektir -- **4.3D'de bu alanlar
İMPLEMENTE EDİLMEZ** (Bölüm 2, kapsam dışı).

## 16. Rating harf sistemi (BAĞLAYICI KARAR -- 6 kademeli Türkçe skala)

AAA-D KULLANILMAZ. **v1 içsel sağlık sınıfları (Bölüm 22 karar #2 ile
KİLİTLENDİ):**

| Aralık | Sınıf |
|---|---|
| 85 – 100 | Çok Güçlü |
| 70 – 84,9 | Güçlü |
| 55 – 69,9 | Sağlıklı |
| 40 – 54,9 | İzlenmeli |
| 25 – 39,9 | Zayıf |
| 0 – 24,9 | Kritik |

Bu isimler her zaman **"resmî kredi derecelendirmesi değildir"**
uyarısıyla (`HealthScoreResult.rating_disclaimer_tr`) birlikte
gösterilir.

## 17. Versioning stratejisi (BAĞLAYICI KARAR -- 4 eksen)

Dört BAĞIMSIZ versiyon ekseni (Bölüm 22 karar #16'nın kapsadığı konuya
komşu, doğrudan bu bölümde sabitlenir):

- `health_score_schema_version` — **YENİ.** `HealthScoreResult`'ın JSON
  ŞEKLİ (alan isimleri/tipleri) değiştiğinde yükseltilir -- MODEL
  mantığından (ağırlık/eşik) BAĞIMSIZDIR.
- `health_score_model_version` — ağırlık, eşik, hard-fail veya override
  kuralı değiştiğinde yükseltilir.
- `ratio_registry_version`, `benchmark_registry_version` — alt
  motorlardan olduğu gibi taşınır.

Tüm dördü HER `HealthScoreResult`'ta BİRLİKTE saklanır; eski skorlar
versiyon yükseldiğinde YENİDEN HESAPLANMAZ.

## 18. API etkileri

(Değişmedi, Bölüm 22 karar #10 ile KESİNLEŞTİ.) Sıfır API/adapter/
migration.

## 19. Performans hedefi

(Değişmedi.) Ölçülmüş referans: `analyze_financial_ratios()` ~0.30ms,
`evaluate_benchmarks()` ~0.11ms. Health Score pipeline'ı, duplicate
filtreleme (Aşama C) + tier interpolasyonu (Aşama D, `BENCHMARK_
REGISTRY`'den sınır okuma dahil) + oransal override (Aşama F) ekler.
**Hedef: < 0.3ms ek yük, toplam pipeline < 1.2ms/çağrı** -- GERÇEK
ölçüm implementasyon Adım 10'da (regression/performance testleri)
yapılacaktır.

## 20. Test stratejisi

1. **Registry doğrulama:** kategori ağırlıklarının (her profil için)
   toplamının 1.0 olduğu; her kategorideki `ratio_weight` toplamının
   1.00'e normalize edildiği; duplicate işaretli TÜM oranların
   `ratio_weight=0` olduğu; `excluded_as_duplicate_of` hedeflerinin
   KENDİLERİNİN duplicate OLMADIĞI (zincirleme yasağı); Bölüm 8.1'in 6
   scored + 6 explainability-only sınıflandırmasının TAM eşleştiği;
   critical-override `ratio_code`'larının HEPSİNİN `ratio_weight>0`
   (scoreable) oranlardan seçildiği.
2. **Pipeline sıra/clamp testleri:** override'ın kategori seviyesinde,
   kategoriler arası ağırlıklandırmadan ÖNCE (Aşama F→G→H sırası)
   uygulandığı; her aşama çıktısının `[0,100]` dışına ÇIKAMADIĞI;
   `CRITICAL_OVERRIDE_CATEGORY_FLOOR=0.50`'nin gerçekten sınırladığı.
3. **`INSUFFICIENT_DATA`/coverage bandı testleri:** `<0.50`,
   `[0.50,0.70)`, `>=0.70` üç bandın HER BİRİNİN doğru davranışı
   (skor yok / uyarılı skor / normal skor).
4. **Hard-fail testleri:** her iki kuralın (negatif özkaynak ceiling=25,
   faiz karşılama negatif ceiling=35) ayrı ayrı VE BİRLİKTE tetiklendiği
   senaryolar; eksik veri durumunda predicate'lerin `False` döndüğü
   (hard-fail YANLIŞLIKLA tetiklenmediği) kanıtı.
5. **Critical override testleri:** tek kural / birden fazla kural aynı
   kategoride tetiklendiğinde çarpımın DOĞRU hesaplandığı VE floor'un
   altına düşmediği.
6. **Tier interpolasyon + fallback testleri:** tier sınırlarının iki
   tarafında sürekliliğin kanıtı; açık uçlu/tek-sınırlı bantlarda
   fallback'in tetiklendiği VE `tier_fallback_used=True` olarak
   işaretlendiği.
7. **Pipeline uçtan uca (golden senaryolar):** mükemmel şirket, zayıf
   likidite+güçlü kârlılık, negatif özkaynak, negatif faiz karşılama,
   düşük coverage (`INSUFFICIENT_DATA`), orta coverage (`low_confidence_
   warning`), önceki dönem yok.
8. **Confidence/coverage formül testleri, rating sınır testleri
   (6 bandın uç değerleri), explainability zorunlu-alan testleri,
   determinism testi (aynı girdi → bit-birebir aynı çıktı, 100
   iterasyon), full regression + gerçek performans ölçümü.**

## 21. Risk analizi

1. **Heuristik/kalibre-edilmemiş ağırlıklar ve eşikler** -- DEVAM
   EDİYOR (v1'in doğası), `provisional=True` ile taşınır.
2. **Duplicate sinyal politikasının GENİŞLETİLMİŞ ama HÂLÂ SINIRLI
   kapsamı** -- 12 oran kapatıldı, kalan ~36 oranın (özellikle
   `debt_to_equity`) TAM denetimi Bölüm 22 karar #16 ile GELECEĞE
   ertelendi.
3. **`cash_conversion_cycle`'ın bilinçli olarak "bağımsız özet sinyal"
   sayılması** -- matematiksel olarak türetilmiş bir bileşik, gerçek
   yeni bilgi TAŞIMIYOR; risk, activity kategorisinin dolaylı olarak
   AŞIRI ağırlıklandırılmasıdır. Azaltım: Bölüm 8.1'deki ağırlık
   normalizasyonu (CCC'ye düşük `ratio_weight`), ama BU YİNE DE bir
   ürün tercihi risk-kabulüdür, tam matematiksel temizlik DEĞİLDİR.
4. **Tam kompanzasyon riski** -- Hard Fail + oransal Critical Override
   ile KISMEN yönetiliyor.
5. **6-kademeli Türkçe rating isimlerinin resmi kredi derecelendirmesi
   ile karıştırılması** -- disclaimer ile azaltılıyor, TAM ORTADAN
   KALKMIYOR.
6. **Enflasyon-düzeltmesiz büyüme** -- DEVAM EDİYOR, %10 ağırlıkla
   sınırlı.
7. **Hard-fail proliferasyonu** -- 2 kuralla KONTROLLÜ tutuluyor.
8. **Dört versiyon ekseni (artık `health_score_schema_version` dahil)**
   -- reprodüktibilite karmaşıklığı ARTTI, tüm dördü birlikte saklanarak
   yönetiliyor.
9. **`RANGE_IS_BETTER` sürekli interpolasyon formülünün TAM
   netleşmemiş olması** (Bölüm 6.2) -- implementasyon Adım 4'e
   bırakıldı, bu bir AÇIK TEKNİK RİSKTİR.
10. **Bölüm 8.2'nin "tenant" seviyesi** -- platformda BUGÜN karşılığı
    olmayan spekülatif bir kavram; YAGNI riski, yalnızca veri
    sözleşmesi/hook (kod DEĞİL) ile SINIRLI tutularak azaltılıyor.
11. **Yeni sabitlerin (confidence ceiling %60, coverage eşikleri %50/
    %70, override çarpanları 0.90/0.70/floor 0.50) kalibre EDİLMEMİŞ
    olması** -- hepsi `provisional=True` zinciriyle taşınıyor, gerçek
    veriyle doğrulanmadı.
12. **Monotonsuzluğun (skorun düşebileceği) kullanıcı algısında
    "hata" olarak yorumlanma riski** -- Bölüm 15'teki AÇIK kabul ve
    ileride trend katmanı ile azaltılacak, 4.3D'de TAM çözülmüyor.

## 22. Onaylanmış Kararlar

Aşağıdaki 18 karar, kullanıcının 4. tur bağlayıcı talimatıyla
KİLİTLENMİŞTİR. Format: (1) Karar başlığı, (2) Alternatifler, (3)
Onaylanan seçenek, (4) Gerekçe, (5) Risk, (6) Gelecekte değiştirilebilir
mi?, (7) İmplementasyon planındaki etkisi.

---

**1. Puan ölçeği**
- *Alternatifler:* 0-100 (1 ondalık) / 0-1000 / FICO-tarzı 300-850.
- *Onaylanan seçenek:* 0-100, 1 ondalık.
- *Gerekçe:* 0-1000/FICO ölçekleri, kalibre edilmemiş bir heuristik
  modelde YANLIŞ hassasiyet algısı yaratır; 0-100 hem CFO'lar için
  sezgisel hem "1 ondalık" ile makul bir çözünürlük sağlar.
- *Risk:* Düşük -- yalnızca kozmetik.
- *Gelecekte değiştirilebilir mi?* Evet, `health_score_schema_version`
  yükseltmesiyle.
- *İmplementasyon etkisi:* Adım 1 (`health_score_types.py` -- `Decimal`
  alan tipi ve yuvarlama kuralı).

**2. Letter rating nomenklatürü**
- *Alternatifler:* AAA-D / okul notu (A-F) / benchmark'ın 5-tier'ı /
  6 kademeli özel Türkçe skala.
- *Onaylanan seçenek:* 6 kademeli Türkçe skala (Çok Güçlü/Güçlü/
  Sağlıklı/İzlenmeli/Zayıf/Kritik), "resmi kredi derecelendirmesi
  değildir" uyarısıyla.
- *Gerekçe:* AAA-D gerçek kredi derecelendirme kuruluşlarıyla
  karıştırılma riski taşır; bu skala FINOS'a özgü, Türkçe, iş
  bağlamına uygun ve disclaimer ile şeffaf.
- *Risk:* Disclaimer'a rağmen bazı kullanıcılar "resmi" algılayabilir.
- *Gelecekte değiştirilebilir mi?* Evet, model versiyonu yükseltilerek.
- *İmplementasyon etkisi:* Adım 6 (rating hesaplama + testleri, plan
  bkz. Bölüm 23 -- not: bu revize planda ayrı adım olarak
  numaralandırılmadı, Adım 5/9'a entegre).

**3. Confidence ve Data Coverage ayrı mı**
- *Alternatifler:* tek "data quality score" / iki ayrı alan.
- *Onaylanan seçenek:* iki ayrı alan (`confidence_score`,
  `data_coverage_ratio`), BİRLEŞTİRİLMEZ.
- *Gerekçe:* "ne kadarını biliyoruz" (coverage) ile "bildiğimize ne
  kadar güvenebiliriz" (confidence) kavramsal olarak FARKLI sorulardır;
  birleştirmek bilgi kaybına yol açar.
- *Risk:* İki ayrı sayı, bazı kullanıcı arayüzlerinde kafa karıştırabilir.
- *Gelecekte değiştirilebilir mi?* Teorik olarak evet ama ÖNERİLMEZ.
- *İmplementasyon etkisi:* Adım 8 (confidence/coverage).

**4. Hard-fail tavan mekanizması**
- *Alternatifler:* `min(score, ceiling)` / sabit değere sıfırlama /
  ağırlıklı ceza.
- *Onaylanan seçenek:* `min(score, ceiling)`, `pre_hard_fail_score`
  HER ZAMAN ayrıca saklanır/gösterilir.
- *Gerekçe:* Şeffaflık -- kullanıcı hem "gerçek" hesaplanan skoru hem
  hard-fail sonrası tavanlanmış skoru görür.
- *Risk:* Düşük.
- *Gelecekte değiştirilebilir mi?* Evet.
- *İmplementasyon etkisi:* Adım 7 (hard fail + insufficient data).

**5. Negatif özkaynak muamelesi**
- *Alternatifler:* hard-fail (sert tavan) / kademeli ceza / yok sayma.
- *Onaylanan seçenek:* Hard Fail Kural 1, `score_ceiling=25`.
- *Gerekçe:* TTK madde 376 kapsamında yasal bir eşik -- diğer
  kategorilerdeki güçlü performansla TELAFİ EDİLEMEYECEK yapısal risk.
- *Risk:* 25 sabiti kalibre edilmemiş.
- *Gelecekte değiştirilebilir mi?* Evet, model versiyonu yükseltilerek.
- *İmplementasyon etkisi:* Adım 7.

**6. Kompanzasyon modeli**
- *Alternatifler:* tam kompanzasyon (ağırlıklı ortalama tek başına) /
  hard-fail + oransal critical override hibriti / yalnızca hard-fail.
- *Onaylanan seçenek:* hibrit -- ağırlıklı ortalama + kategori
  seviyesinde oransal critical override (weak×0.90/critical×0.70,
  floor 0.50) + hard fail.
- *Gerekçe:* Saf ağırlıklı ortalama, tek bir çok kötü sinyali diğer
  kategorilerle "yıkayabilir"; hibrit model bunu önler ama TAM
  compensation'ı da yasaklamaz (esneklik korunur).
- *Risk:* Çarpan değerleri (0.90/0.70/0.50) heuristik.
- *Gelecekte değiştirilebilir mi?* Evet.
- *İmplementasyon etkisi:* Adım 6 (critical override + clamp).

**7. Kategori ağırlıkları**
- *Alternatifler:* eşit ağırlık (6×~%16.7) / kârlılık-ağırlıklı /
  borçluluk-ağırlıklı (onaylanan) / dinamik.
- *Onaylanan seçenek:* liquidity %20, leverage %25, profitability %20,
  activity %15, efficiency %10, growth %10.
- *Gerekçe:* Kredi/risk odaklı bir "sağlık" skoru için borçluluk EN
  yüksek ağırlığı taşır; kârlılık ve likidite ikinci sırada eşit önemde.
- *Risk:* Ampirik kalibrasyon YOK, tamamen heuristik sıralama.
- *Gelecekte değiştirilebilir mi?* Evet, model versiyonu yükseltilerek;
  Bölüm 8.2 override mimarisiyle sektöre göre de değişebilir (gelecekte).
- *İmplementasyon etkisi:* Adım 2 (`health_score_registry.py`).

**8. Kategori-içi oran ağırlıkları**
- *Alternatifler:* eşit ağırlık / merkezi registry'de tanımlı ağırlıklar
  (onaylanan).
- *Onaylanan seçenek:* eşit ağırlık YOK -- her scored oran için
  registry'de `ratio_weight`, kategori içinde normalize edilerek
  toplam 1.00.
- *Gerekçe:* Bazı oranlar (ör. current_ratio) bir kategori için diğer
  oranlardan (ör. cash_conversion_cycle) daha temel bir sinyaldir; eşit
  ağırlık bu farkı görmezden gelir.
- *Risk:* Kesin sayısal değerler implementasyon adımına bırakıldı,
  bu doküman yalnızca metodolojiyi sabitliyor.
- *Gelecekte değiştirilebilir mi?* Evet.
- *İmplementasyon etkisi:* Adım 2, Adım 3 (duplicate signal ve ağırlık
  validasyonları).

**9. Duplicate/derived oranların scoring dışı bırakılması**
- *Alternatifler:* yalnızca birebir-aynı-formül duplicate'leri çıkar /
  12 oranın TAMAMINI tek tek sınıflandır (onaylanan).
- *Onaylanan seçenek:* Bölüm 8.1'deki nihai sınıflandırma -- 6 scored,
  6 explainability-only; equity_ratio ana sermaye-yapısı sinyali;
  days_payables_outstanding scored (payables_turnover değil);
  cash_conversion_cycle bağımsız özet sinyal olarak scored (ağırlık
  normalizasyonuyla).
- *Gerekçe:* "Aynı ekonomik sinyal bir kez puanlanır" ilkesi + CFO
  iletişiminde en sezgisel temsilcilerin (equity_ratio, gün-cinsinden
  DPO, CCC) seçilmesi.
- *Risk:* CCC'nin scored tutulması matematiksel temizlikten bir
  ÖDÜNdür (Bölüm 21 risk #3).
- *Gelecekte değiştirilebilir mi?* Evet.
- *İmplementasyon etkisi:* Adım 3.

**10. API/persistence sürekliliği ve kapsam sınırı**
- *Alternatifler:* saf kütüphane (onaylanan) / adapter+migration+API.
- *Onaylanan seçenek:* saf kütüphane, ayrı tablo YOK; ileride Ratio
  Engine `result_json`'a bağlanması AYRI bir onay gerektirir. API,
  adapter, bulk upload/recompute, DB persistence, Credit Score,
  Recommendation Engine, AI/LLM, tenant/industry override aktivasyonu
  -- HEPSİ bu fazın DIŞINDA.
- *Gerekçe:* 4.3B/4.3C'nin "saf kütüphane, önce doğrula, sonra
  entegre et" disiplini korunuyor.
- *Risk:* Düşük -- kapsam netliği riski azaltıyor.
- *Gelecekte değiştirilebilir mi?* Evet, ayrı bir milestone/onayla.
- *İmplementasyon etkisi:* Adım 9 (explainability + service
  orchestration) -- yalnızca fonksiyon imzası, adapter YOK.

**11. Tier puanlama stratejisi**
- *Alternatifler:* sabit tier puanı / sürekli (doğrusal) interpolasyon
  (onaylanan) + kontrollü fallback.
- *Onaylanan seçenek:* doğrusal interpolasyon varsayılan, açık
  uçlu/tek-sınırlı bantlarda sabit puana (`TIER_TO_POINTS`) fallback,
  fallback her zaman `tier_fallback_used=True` ile işaretlenir.
- *Gerekçe:* Cliff effect'i giderir, Credit Score Engine'e daha temiz
  bir girdi bırakır; fallback, tanımsız durumlarda çökmeyi önler.
- *Risk:* Girdi sözleşmesi derinleşir (`BENCHMARK_REGISTRY`'ye doğrudan
  erişim gerekir, Bölüm 4.1).
- *Gelecekte değiştirilebilir mi?* Evet.
- *İmplementasyon etkisi:* Adım 4 (tier interpolation).

**12. `RANGE_IS_BETTER` sürekli interpolasyon formülü**
- *Alternatifler:* tam formülü şimdi sabitle / yaklaşımı sabitle, tam
  formülü implementasyona bırak (onaylanan).
- *Onaylanan seçenek:* yaklaşım (interpolasyon + fallback ilkesi)
  sabit, TAM formül Adım 4'te netleşecek.
- *Gerekçe:* `RANGE_IS_BETTER`'ın iç içe bant yapısı, tasarım
  dokümanında kod yazmadan tam formülize edilemeyecek kadar
  implementasyon-detaylı.
- *Risk:* Açık teknik risk (Bölüm 21 risk #9) olarak kayıtlı.
- *Gelecekte değiştirilebilir mi?* Evet, Adım 4 sırasında netleşecek.
- *İmplementasyon etkisi:* Adım 4.

**13. Strengths/weaknesses sayısı (N)**
- *Alternatifler:* 3 / 5 (önerilen, kullanıcı tarafından bu turda
  spesifik verilmedi).
- *Onaylanan seçenek:* N=5 (tasarımcı önerisi olarak kapatıldı).
- *Gerekçe:* 5, CFO'nun tek bakışta özümseyebileceği makul bir üst
  sınır; 3 çok az bilgi verebilir.
- *Risk:* Kullanıcı onayı olmadan kapatılan tek karar -- gelecekte
  kolayca değiştirilebilir.
- *Gelecekte değiştirilebilir mi?* Evet, kolaylıkla (konfigürasyon
  sabiti).
- *İmplementasyon etkisi:* Adım 9.

**14. `RANGE_IS_BETTER` asimetrik risk muamelesi**
- *Alternatifler:* simetrik (onaylanan, v1) / asimetrik (ör.
  current_ratio'nun çok yüksek olması da hafif bir risk sinyali
  sayılabilir).
- *Onaylanan seçenek:* v1'de simetrik kalır.
- *Gerekçe:* Asimetrik risk modellemesi, gerçek veriyle kalibre
  edilmeden EKLENMESİ riskli bir karmaşıklıktır.
- *Risk:* current_ratio gibi oranlarda "çok yüksek = her zaman iyi"
  yanlış varsayımı devam eder.
- *Gelecekte değiştirilebilir mi?* Evet.
- *İmplementasyon etkisi:* Adım 4 (RANGE_IS_BETTER formülüyle birlikte).

**15. Yeni sabitler (confidence ceiling, coverage eşikleri, override
çarpanları)**
- *Alternatifler:* çeşitli sayısal değerler.
- *Onaylanan seçenek:* `PROVISIONAL_CONFIDENCE_CEILING=0.60`,
  `INSUFFICIENT_DATA_COVERAGE_THRESHOLD=0.50` (+ `0.50-0.70` uyarı
  bandı), `CRITICAL_OVERRIDE_WEAK_MULTIPLIER=0.90`,
  `CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER=0.70`,
  `CRITICAL_OVERRIDE_CATEGORY_FLOOR=0.50`.
- *Gerekçe:* Bölüm 10/11/13'te tek tek gerekçelendirildi.
- *Risk:* Hepsi kalibre edilmemiş heuristik -- `provisional=True`.
- *Gelecekte değiştirilebilir mi?* Evet, model versiyonu yükseltilerek.
- *İmplementasyon etkisi:* Adım 2, 6, 7, 8.

**16. Bölüm 8.1'in TAM denetimi (kalan oranlar)**
- *Alternatifler:* şimdi tam denetim yap / v1 kapsamını 12 oranla
  sınırla, tam denetimi ertele (onaylanan).
- *Onaylanan seçenek:* v1 kapsamı bu 12 oranla sınırlı kalır; kalan
  oranların (özellikle `debt_to_equity`) sistematik denetimi gelecek
  bir teknik-borç turuna ERTELENDİ.
- *Gerekçe:* Kullanıcının 4. tur talimatı yalnızca bu 12 oranı
  kapsıyordu; tam registry denetimi bu revizyonun kapsamını aşar.
- *Risk:* Bilinen ama ÇÖZÜLMEMİŞ bir teknik borç (Bölüm 21 risk #2).
- *Gelecekte değiştirilebilir mi?* Evet, ayrı bir mini-milestone olarak.
- *İmplementasyon etkisi:* Adım 3'ün NOTU olarak (kapsam sınırı
  açıkça kod yorumlarında da belirtilecek).

**17. Bölüm 8.2'nin "tenant" seviyesi**
- *Alternatifler:* tamamen çıkar (YAGNI) / yalnızca tasarım-only
  4. seviye olarak KORU (onaylanan).
- *Onaylanan seçenek:* korunuyor -- `tenant > industry > company_size >
  global` sırası tasarlanıyor, yalnızca `global` aktif, diğerleri
  yalnızca veri sözleşmesi/hook (kod DEĞİL).
- *Gerekçe:* Kullanıcının açık talimatı; gelecekteki olası çok-kiracılı
  bir mimariye HAZIR bir sözleşme bırakmak, şimdiden gerçek veri
  KAYDETMEDEN mümkün.
- *Risk:* FINOS'un gerçekten çok-kiracılı olup olmayacağı belirsiz --
  YAGNI riski TAMAMEN ortadan kalkmıyor, yalnızca "kod üretmeme"
  disipliniyle SINIRLANIYOR.
- *Gelecekte değiştirilebilir mi?* Evet, hatta tamamen kaldırılabilir.
- *İmplementasyon etkisi:* Adım 2 (yalnızca fonksiyon imzası/çözümleme
  sırası, veri KAYDI yok).

**18. Activity kategorisi için critical-override temsilcisi**
- *Alternatifler:* boş bırak (v1, 3. tur revizyonun kararı) /
  `cash_conversion_cycle` ekle (onaylanan, CCC scored olduğu için).
- *Onaylanan seçenek:* `cash_conversion_cycle`, weak×0.90/critical×0.70.
- *Gerekçe:* CCC bu turda scored bir sinyal haline geldiği için,
  activity kategorisinin de diğer kategoriler gibi bir critical-
  override temsilcisi olması tutarlılık sağlar.
- *Risk:* CCC'nin zaten bileşik/türetilmiş doğası (risk #3), override
  sinyali olarak da aynı çekinceyi taşır.
- *Gelecekte değiştirilebilir mi?* Evet.
- *İmplementasyon etkisi:* Adım 6.

---

**Tüm 18 karar KAPANMIŞTIR.** Bu bölüm artık "Açık Kararlar" değil,
**"Onaylanmış Kararlar"** statüsündedir.

## 23. İmplementasyon planı (REVİZE, test-kapılı 11 adım)

| Adım | İçerik | Test kapısı |
|---|---|---|
| 1 | `health_score_types.py` -- dataclass'lar (Bölüm 5), enum'lar, `TIER_TO_POINTS` | Tip/serialize testleri geçmeden Adım 2'ye geçilmez |
| 2 | `health_score_registry.py` -- `CATEGORY_WEIGHT_PROFILES` (yalnızca `global`, Bölüm 8), `resolve_category_weights()` (Bölüm 8.2 sırası), `RATIO_SCORE_WEIGHTS` (Bölüm 8.1), `HARD_FAIL_RULES` (Bölüm 12), `CRITICAL_OVERRIDE_RULES` (Bölüm 13) | Registry doğrulama testleri (Bölüm 20.1) geçmeden Adım 3'e geçilmez |
| 3 | Duplicate signal ve ağırlık validasyonları -- kategori içi `ratio_weight` toplamının 1.00'e normalize edildiği, duplicate'lerin `ratio_weight=0` olduğu, `excluded_as_duplicate_of` zincirleme yasağı | Bölüm 20.1 testleri %100 yeşil olmadan Adım 4'e geçilmez |
| 4 | Tier interpolation -- `continuous_points_*` fonksiyonları (higher/lower/range_is_better), fallback mantığı, `tier_fallback_used` işaretleme | Bölüm 20.6 testleri geçmeden Adım 5'e geçilmez |
| 5 | Category scoring + missing-data normalization -- Aşama C-E (Bölüm 6) | Kategori-içi/kategoriler-arası yeniden dağıtım testleri geçmeden Adım 6'ya geçilmez |
| 6 | Critical override + clamp -- Aşama F-G (Bölüm 13) | Bölüm 20.5 testleri geçmeden Adım 7'ye geçilmez |
| 7 | Hard fail + insufficient data -- Aşama B.5, I (Bölüm 11-12) | Bölüm 20.3/20.4 testleri geçmeden Adım 8'e geçilmez |
| 8 | Confidence/coverage -- Aşama K'nın confidence/coverage kısmı (Bölüm 10-11) | Formül testleri geçmeden Adım 9'a geçilmez |
| 9 | Explainability + service orchestration -- `compute_financial_health_score()` (Bölüm 4.2, 14), rating (Bölüm 16), strengths/weaknesses (Bölüm 15) | Explainability zorunlu-alan testleri geçmeden Adım 10'a geçilmez |
| 10 | Unit/golden/property/regression/performance testleri (Bölüm 20 TAMAMI) -- gerçek `ratio_result_json`+`benchmark_result_json` üzerinde uçtan uca | %100 yeşil olmadan Adım 11'e geçilmez |
| 11 | Final rapor -- gerçek performans ölçümü, `tests/README.md` güncellemesi, dürüst özet | Kullanıcı onayı |

Migration/adapter/API bu planın HİÇBİR adımında YOKTUR (Bölüm 22 karar
#10). Commit/push implementasyon fazında dahi YALNIZCA kullanıcının
açık talimatıyla yapılır.

---

## Kapsam dışı özet (tekrar, netlik için)

Credit Score, Recommendation Engine, gerçek Türkiye sektör verisiyle
kalibrasyon, `cash_flow`/`investment`/`market`/`banking`/`ifrs`/`risk`/
`capital_structure`/`working_capital` kategorileri, LLM tabanlı doğal
dil üretimi, migration/adapter/API/bulk-upload/DB persistence, gerçek
çok-kiracılı altyapı, trend/monotonluk katmanı (`previous_score`/
`score_delta`/`coverage_delta`) -- bunların HİÇBİRİ bu milestone'u
KAPSAMAZ.

## Onay bekleniyor

Bölüm 22'deki 18 karar TAMAMEN kapatılmış, kilitlenmiş ve bağlayıcı
hale gelmiştir. Bu doküman artık implementasyona geçiş için SON kullanıcı
onayını beklemektedir. Onay SONRASINDA Bölüm 23'teki 11 adımlık,
test-kapılı plan izlenerek implementasyona başlanacaktır -- şu ana kadar
**hiçbir kod yazılmadı, hiçbir dosya değiştirilmedi, hiçbir migration
oluşturulmadı, hiçbir test yazılmadı, hiçbir commit yapılmadı.**
