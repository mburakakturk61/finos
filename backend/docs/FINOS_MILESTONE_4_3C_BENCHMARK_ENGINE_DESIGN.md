# Milestone 4.3C — Benchmark Engine Teknik Tasarımı

**Durum: ONAYLANDI (2. tur, 9 bağlayıcı karar ile) — İmplementasyon
devam ediyor.**

Bu doküman, kullanıcının 1. tur onayı ("temel yaklaşım onaylandı, ancak 9
karar bağlayıcıdır") sonrasında Bölüm 22/23 ve bunlarla doğrudan ilişkili
tüm bölümler (4, 5, 6, 8.3, 8.4, 8.6, 8.7, 11, 12, 13, 15, 18, 21) bu 9
kararla REVİZE EDİLEREK güncellenmiştir. Aşağıdaki içerik artık nihai,
onaylı tasarımdır — implementasyon bu revize haline göre yürütülür.

Bu doküman Milestone 4.3C'nin (Benchmark Engine) teknik tasarımını içerir.
2. tur onayla birlikte implementasyon Bölüm 23'teki 8 adımlık plana göre
başlamıştır. **Bağlayıcı sınır (2. tur onay ile de teyit edildi):** bu
milestone'da hiçbir migration, `AnalysisType` eklemesi, adapter, registry
motor kaydı, API/bulk upload bağlantısı, Health Score, Credit Score veya
Recommendation Engine kodu YAZILMAZ — Benchmark Engine bu fazda tamamen
saf, bağımsız bir değerlendirme kütüphanesi/service olarak kalır (bkz.
Bölüm 22 karar #6).

---

## 0. Ön inceleme özeti (mevcut kod tabanı)

Tasarıma başlamadan önce aşağıdaki mevcut bileşenler baştan sona incelendi:

- `app/engines/common/ratio_formulas.py` — `RATIO_REGISTRY` (57 kayıtlı
  oran, `RATIO_REGISTRY_VERSION="1.1.0"`), `RatioFormulaMetadata`,
  `ComputationStatus`, `ComputationOutcome`, 4 kapalı `calculation_strategy`
  (`sum_division`/`linear_combination`/`growth_rate`/`scaled_division`),
  `register_ratio_formula` (tekilcilik + `depends_on_ratios` ön-kayıt
  doğrulaması), `compute_registered_ratio`.
- `app/engines/common/ratio_derived_facts.py` — `average_*`,
  `compute_days_in_period` (+1 kapsayıcı düzeltmesi dahil),
  `compute_quick_assets`/`compute_capital_employed`/`compute_tax_expense`/
  `compute_invested_capital`.
- `app/engines/financial_ratios/service.py` — `analyze_financial_ratios`
  orkestrasyonu: `_CATEGORY_RATIO_KEYS` (7 kategori, 57 oran),
  `_not_applicable_outcome`/`_engine_dependency_not_calculable_outcome`/
  `_fixed_charge_coverage_not_calculable_outcome`/
  `_sustainable_growth_rate_not_calculable_outcome`,
  `_apply_effective_tax_rate_range_check`, `_reliability_for_category`,
  `derived_base_figures`, `missing_categories` (7 kategori henüz boş:
  investment/market/banking/ifrs/risk/capital_structure/working_capital).
- `app/engines/financial_ratios/adapter.py` — `FinancialRatioEngineAdapter`,
  HİÇBİR gerçek akışa (bulk upload/API/ratio_recompute) bağlı değil.
- `app/engines/protocol.py` — `EngineRunContext` (additive alanlar:
  `balance_sheet_result`/`income_statement_result`/`prior_period_*`/
  `period_start_date`/`period_end_date`/`period_months_covered`),
  `EngineRunResult`, `EngineAdapter` Protocol.
- `app/engines/registry.py` — `_ENGINE_BY_ANALYSIS_TYPE` (TEK doğruluk
  kaynağı, 4 adaptör: trial_balance/balance_sheet/income_statement/
  financial_ratios), `_DETECTED_TYPE_TO_ANALYSIS_TYPE`/
  `_DOCUMENT_TYPE_TO_ANALYSIS_TYPE`.
- `app/models/enums.py::AnalysisType` — `native_enum=False,
  create_constraint=True` ile bir CHECK constraint'e bağlı (bkz. Bölüm 18)
  — yeni bir `AnalysisType` üyesi eklemek bir Alembic migration'ı
  GEREKTİRİR.
- `app/models/company.py::Company` — `sector: str | None` (serbest metin)
  ve `nace_code: str | None` (yapısal NACE sınıflandırma kodu) ZATEN
  MEVCUT. `country`/`city`/`registration_number`/`establishment_date`
  Milestone 2'de BİLİNÇLİ OLARAK dışarıda bırakılmış (docstring'de açıkça
  yazıyor) ve BUGÜN HİÇ YOK. Şirket ölçeği (çalışan sayısı, ciro dilimi
  vb.) için de HİÇBİR alan yok.
- `grep -ril "benchmark"`, `grep -ril "health_score|healthscore"`,
  `grep -ril "credit_score|creditscore"`, ve dosya adı taraması — TÜMÜ
  `backend/app` içinde SIFIR sonuç döndü. **Benchmark/Health Score/Credit
  Score için hiçbir hazırlık, hiçbir kısmi kod, hiçbir taslak yok** — bu
  tamamen yeşil alan (greenfield) bir tasarımdır.

Bu inceleme, aşağıdaki tasarımın **gerçek, güncel** 57 kayıtlı orana ve
**gerçek, güncel** `Company` şemasına dayandığını doğrular.

---

## 1. Amaç

Benchmark Engine'in amacı, Financial Ratio Engine'in (Milestone 4.3A/B)
ürettiği ham oran değerlerini (`value` + `status`) **bağımsız bir referans
çerçevesiyle** karşılaştırarak nitel bir konum bilgisi üretmektir:
"bu oran, benzer şirketler/sektörler/ölçekler arasında iyi mi, kötü mü,
ortalama mı?" sorusuna kontrollü, açıklanabilir (explainable), asla
fabrike edilmeyen bir cevap vermek.

Bu altyapı, gelecekteki Health Score (Milestone 4.3E sonrası) ve Credit
Score (Milestone 4.3E) hesaplamalarının **girdisi** olacaktır — ama bu
doküman KESİNLİKLE o hesaplamaların kendisini tasarlamaz (bkz. Bölüm 3).
Benchmark Engine, ratio engine'in "value nedir" sorusuna verdiği cevaptan
BAĞIMSIZ olarak "bu value nasıl yorumlanır" sorusuna cevap veren, ayrı bir
kaygı (concern) katmanıdır.

## 2. Kapsam

**Kapsam İÇİNDE:**

- Benchmark metadata veri modeli (`BenchmarkThresholds`,
  `BenchmarkMetadata`, `BenchmarkComputationStatus`) — saf Python
  dataclass/enum, sqlalchemy'ye SIFIR bağımlı (mevcut
  `app/engines/common/**` deseniyle tutarlı).
- `BENCHMARK_REGISTRY` — RATIO_REGISTRY'nin 57 girdisinden **ölçek-bağımsız
  birimli** (`unit ∈ {"ratio", "percentage", "days"}`) ve **bu fazda
  gerçekten CALCULATED üretebilen** ratio_code'lar için varsayılan
  (global/genel) eşik bantlarının tanımlanması — toplam **48 benchmark
  girdisi** (bkz. Bölüm 8 için tam liste ve gerekçe).
- Percentile/sektör/şirket ölçeği/ülke override'ları için **yapısal
  destek** (alanlar, doğrulama, çözümleme sırası) — ama GERÇEK percentile
  veri kümesi, GERÇEK sektör-override tablosu, GERÇEK ülke-override
  tablosu bu fazda DOLDURULMAZ (bkz. Bölüm 10-13 — "tasarlandı ama
  doldurulmadı" deseni, 4.3B'nin `sustainable_growth_rate`/
  `average_*` politikalarıyla aynı entelektüel dürüstlük ilkesi).
- Benchmark değerlendirme orkestrasyonunun (nasıl çağrılacağı, hangi
  girdilere ihtiyaç duyacağı) mimari tasarımı.
- Test stratejisi, performans analizi (tahmini — henüz kod yok), risk
  analizi, versiyonlama, yaşam döngüsü.

**Kapsam DIŞINDA (bu doküman TASARLAMAZ):**

- Health Score hesaplama mantığı (skorların birleştirilmesi/ağırlıklandırılması).
- Credit Score hesaplama mantığı.
- Recommendation Engine.
- `cash_flow` kategorisinin 6 oranı için benchmark, placeholder dahil
  (Cash Flow Engine — Milestone 4.4 — henüz yok; bu oranlar bugün HER
  ZAMAN `not_calculable` döndüğü için benchmarklanacak hiçbir değer yok,
  2. tur onay karar #8 ile KESİNLEŞTİ — bkz. Bölüm 8.7).
- `sustainable_growth_rate`/`fixed_charge_coverage` (57 kayıtlı oranın
  içinde ama HER ZAMAN `not_calculable` — aynı gerekçe).
- Gerçek percentile/peer veri kümesi temini (Bölüm 10 — hangi kaynaktan
  temin edileceği bu milestone'un dışında bırakıldı, yalnızca altyapı
  sözleşmesi tasarlandı).
- `Company.country`/`Company` şirket ölçeği alanları için migration.
- Milestone 4.3E (Bankacılık+Risk+Kredi Skoru), 4.3F (Çalışma Sermayesi+
  Öneri altyapısı), 4.3G (Yatırım/Piyasa/IFRS/Sermaye Yapısı) — bunlar
  ayrı, gelecekteki fazlardır.

## 3. Faz sınırları

Bu TASARIM fazında (şu an):
- **Sıfır kod, sıfır dosya değişikliği, sıfır migration, sıfır test, sıfır
  commit.** Yalnızca bu Markdown dokümanı üretildi.

Onay SONRASI implementasyon fazında (Bölüm 23'teki adım planı) geçerli
olacak kesin sınırlar:
- Health Score YOK, Credit Score YOK, Recommendation Engine YOK.
- `ratio_recompute.py` YOK.
- API endpoint değişikliği YOK.
- Bulk upload değişikliği YOK.
- `app/trial_balance/**` değişikliği YOK.
- `app/engines/financial_ratios/**` dosyalarının **mevcut** mantığında
  DEĞİŞİKLİK YOK (yalnızca yeni, bağımsız `app/engines/benchmarks/**`
  paketi eklenir — Bölüm 4'teki mimari kararın doğal sonucu).
- Migration: yalnızca Bölüm 23 Adım 8'de AÇIKÇA işaretlenen, YENİ bir
  `AnalysisType` üyesi eklemeyi gerektiren TEK alt-adım migration
  dokunur — ve bu alt-adım implementasyon planının GERİ KALANINDAN
  AYRI, kullanıcıdan AYRICA onay istenerek yapılacaktır.
- Commit/push YOK (kullanıcı açıkça istemedikçe).
- Milestone 4.3D/E/F/G'ye geçiş YOK.

## 4. Mimari

### 4.1 Neden ayrı bir motor/paket (ve neden `financial_ratios` içine gömülmedi)?

İki alternatif değerlendirildi:

**Alternatif A (REDDEDİLDİ) — Benchmark'ı doğrudan
`analyze_financial_ratios`'un çıktısına göm** (her `ratios[key]` dict'ine
bir `"benchmark"` alt-anahtarı ekle). Reddedilme gerekçesi: ratio
hesaplama ile benchmark değerlendirme, **farklı veri kaynaklarına**
(şirketin kendi mali tabloları vs. harici/referans sektör verisi),
**farklı versiyon ritimlerine** (`RATIO_REGISTRY_VERSION` bir formül
düzeltildiğinde değişir; `BENCHMARK_REGISTRY_VERSION` bir sektör eşiği
yıllık güncellendiğinde değişir — bu ikisi BAĞIMSIZ olay akışlarıdır) ve
**farklı yaşam döngülerine** (bir oranın DEĞERİ bir kez hesaplanır ve
değişmez; bir benchmark'ın TIER ATAMASI, referans veri güncellenirse
YENİDEN DEĞERLENDİRİLEBİLİR — ratio'yu yeniden hesaplamadan, bkz. Bölüm
17) sahiptir. Bunları TEK bir modülde birleştirmek, az önce tamamlanmış
ve 144/144 testle doğrulanmış `financial_ratios/service.py`'yi yeniden
açmayı ve onun test yüzeyini büyütmeyi gerektirirdi — gereksiz risk.

**Alternatif B (SEÇİLDİ) — Bağımsız `app/engines/benchmarks/` paketi.**
Financial Ratio Engine'in ZATEN ÜRETTİĞİ `result_json`'u (yeniden
hesaplama YOK — B.3 ilkesinin benchmark'a genellemesi) GİRDİ olarak okur,
kendi `result_json`'unu üretir. `app/engines/financial_ratios/**`
dosyalarının bugünkü içeriği HİÇ DEĞİŞMEZ.

### 4.2 Yeni dosyalar (2. tur onayla REVİZE EDİLDİ — Bölüm 22 karar #6)

**Bağlayıcı karar #6:** Benchmark Engine bu milestone'da KENDİ
`AnalysisType`'ı, KENDİ `EngineAdapter`'ı OLMAYACAK ve
`app.engines.registry`'ye KAYDEDİLMEYECEK — hiçbir DB'ye
`FinancialAnalysisResult` yazmayacak, hiçbir API/bulk upload akışına
bağlanmayacak. Bu nedenle Bölüm 4.1'deki "Alternatif B" mimari yönü
korunur (ayrı paket/registry/service) AMA `app/engines/protocol.py`'ye
HİÇBİR additive alan eklenmez, `EngineRunContext` bu fazda HİÇ
KULLANILMAZ — `evaluate_benchmarks()` sıradan, doğrudan keyword
argümanlarıyla çağrılan saf bir Python fonksiyonudur. Persistence ve
gerçek akışa bağlanma (adapter/AnalysisType/migration/API), AYRI bir
gelecek milestone'un VE ayrı bir onayın konusudur.

```
app/engines/common/reliability.py           # _worse_reliability'nin
                                             # financial_ratios/service.py'den
                                             # taşınan, İKİ motorun da
                                             # paylaştığı ortak hali
app/engines/common/benchmark_types.py       # dataclass'lar, enum, kapalı
                                             # threshold_bands stratejisi
                                             # (mevcut ratio_formulas.py
                                             # deseniyle birebir tutarlı)
app/engines/common/benchmark_registry.py    # BENCHMARK_REGISTRY'nin 48
                                             # register_benchmark() çağrısı
                                             # (kategori kategori, Bölüm 8)
app/engines/common/company_size_classifier.py  # saf fonksiyon: mali
                                             # büyüklüklerden (yeni DB alanı
                                             # OLMADAN) şirket ölçeği türetir
app/engines/benchmarks/service.py           # evaluate_benchmarks(...) --
                                             # saf, bağımsız kütüphane
                                             # fonksiyonu (adapter/context
                                             # YOK)
```

**Bu fazda KESİNLİKLE OLUŞTURULMAYACAK dosyalar/değişiklikler** (Bölüm 22
karar #6, #5 ile tutarlı): `app/engines/benchmarks/adapter.py`,
`app/engines/protocol.py`'de HERHANGİ bir değişiklik (ne
`financial_ratios_result`, ne `industry_code`/`company_size_bucket`, ne
de `country_code` — hiçbiri context'e eklenmez), `app/engines/registry.py`
değişikliği, `AnalysisType.BENCHMARK_COMPARISON` enum üyesi, herhangi bir
Alembic migration.

Bu paket de `app/trial_balance/**`'ten SIFIR import içerir; SQLAlchemy/
FastAPI/Pydantic'e sıfır bağımlıdır (sandbox'ta gerçekten çalıştırılabilir
testler için, mevcut zorunlu desen).

## 5. Veri modeli

Bu fazda **yeni bir DB tablosu ÖNERİLMEZ.** `FinancialAnalysisResult`
tablosu zaten `result_json` (JSONB) + `analysis_type` + `source_mode` +
`status` alanlarına sahip — Benchmark Engine'in çıktısı da (ratio
engine'inki gibi) bu ŞEMAYA sığar; ihtiyaç duyulan tek şema değişikliği
`analysis_type` CHECK constraint'ine yeni bir değer eklemektir (Bölüm 18).

Python tarafında veri modeli tamamen **bellek-içi, saf dataclass**'lardır
(aşağıdaki gibi — kesin implementasyon Bölüm 23 Adım 1'de netleşecek):

```python
class BenchmarkIdealDirection(str, enum.Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    RANGE_IS_BETTER = "range_is_better"  # ideal bir ORTA bant, iki uçta da kötü


class BenchmarkComputationStatus(str, enum.Enum):
    EVALUATED = "evaluated"
    RATIO_STATUS_NOT_CALCULATED = "ratio_status_not_calculated"
    BENCHMARK_NOT_REGISTERED = "benchmark_not_registered"
    PERCENTILE_DATA_UNAVAILABLE = "percentile_data_unavailable"  # rezerve
    STALE_BENCHMARK_DATA = "stale_benchmark_data"                # rezerve


@dataclass(frozen=True)
class BenchmarkThresholds:
    # ideal_direction=range_is_better ise her alan bir (min, max) tuple'ı
    # OLMALI; aksi halde tek bir Decimal skaler OLMALI (register_benchmark
    # bunu doğrular).
    excellent: "Decimal | tuple[Decimal, Decimal] | None"
    good: "Decimal | tuple[Decimal, Decimal] | None"
    average: "Decimal | tuple[Decimal, Decimal] | None"
    weak: "Decimal | tuple[Decimal, Decimal] | None"
    critical: "Decimal | tuple[Decimal, Decimal] | None"
    warning_threshold: "Decimal | None"


@dataclass(frozen=True)
class BenchmarkMetadata:
    benchmark_code: str
    ratio_code: str          # RATIO_REGISTRY'de kayıt ANINDA var olmalı
    category: str            # ratio'nun kategorisiyle AYNI (tutarlılık)
    benchmark_type: str      # kapalı küme, bkz. Bölüm 6 -- şimdilik yalnız
                             # "threshold_bands"
    unit: str                # RATIO_REGISTRY[ratio_code].unit ile AYNI
                             # OLMALI (kayıt anında doğrulanır)
    ideal_direction: BenchmarkIdealDirection
    default_thresholds: BenchmarkThresholds
    source: str = "internal_heuristic"   # Bölüm 9 -- 4.3C'de TEK değer
    # Bağlayıcı karar #1 (2. tur onay): bu üç alan HER ZAMAN BİRLİKTE,
    # tutarlı biçimde taşınır -- 4.3C'nin TÜM girdilerinde
    # provisional=True, source="internal_heuristic",
    # reliability_ceiling="medium" (büyüme kategorisi hariç, bkz. karar
    # #7 -- "medium_low"). Tüketen sistemler (gelecekteki Health/Credit
    # Score) `provisional=True` gördüğünde bu değeri resmi/ampirik bir
    # referansmış gibi KULLANAMAZ.
    provisional: bool = True
    reliability_ceiling: str = "medium"
    # Bağlayıcı karar #7: yalnızca category="growth" girdilerinde
    # anlamlıdır -- nominal (TÜFE düzeltmesiz) bir büyüme benchmark'ı
    # olduğunu AÇIKÇA işaretler. Diğer kategorilerde None (büyüme dışı
    # bir orana enflasyon ayarı kavramı uygulanmaz).
    inflation_adjusted: "bool | None" = None
    version: str = "1.0.0"
    last_reviewed_at: "date | None" = None
    supports_percentile: bool = False
    supports_industry_override: bool = False
    supports_company_size_override: bool = False
    # Bağlayıcı karar #5: `supports_country_override` alanı KASITLI
    # OLARAK YOK -- ülke desteği bu fazda yalnızca "ertelendi" değil,
    # HİÇBİR iskelet/skeleton kod olarak bile MODELE DAHİL EDİLMEDİ
    # (YAGNI). Bkz. Bölüm 13.
    industry_overrides: "dict[str, BenchmarkThresholds]" = field(default_factory=dict)
    company_size_overrides: "dict[str, BenchmarkThresholds]" = field(default_factory=dict)
```

## 6. Registry yapısı

`BENCHMARK_REGISTRY: dict[str, BenchmarkMetadata]` — `RATIO_REGISTRY`'nin
BİREBİR aynı disipliniyle yönetilir:

`register_benchmark(metadata: BenchmarkMetadata) -> None` şu kontrolleri
kayıt ANINDA (çalışma zamanında değil, modül yüklenirken) yapar —
`register_ratio_formula`'nın `depends_on_ratios` ön-doğrulamasıyla AYNI
felsefe:

1. `benchmark_code` `BENCHMARK_REGISTRY`'de zaten yoksa (tekilcilik).
2. `metadata.ratio_code`, `RATIO_REGISTRY`'de **kayıt anında zaten var**
   olmalı (`get_ratio_formula(ratio_code) is not None`) — yoksa
   `ValueError`. Bu, benchmark'ların yanlışlıkla var olmayan/yazım hatalı
   bir ratio_code'a bağlanmasını yapısal olarak imkansız kılar.
3. `metadata.unit == RATIO_REGISTRY[ratio_code].unit` — birim uyuşmazlığı
   erken, kontrollü bir `ValueError` ile reddedilir (ör. bir oranın birimi
   "percentage" iken benchmark'ın "ratio" ölçeğinde eşikler taşıması
   sessizce YANLIŞ bir karşılaştırmaya yol açardı).
4. `metadata.unit in ("ratio", "percentage", "days")` — **`unit="currency"`
   olan hiçbir ratio_code benchmarklanamaz** (bkz. Bölüm 8, "neden
   `net_working_capital` yok" açıklaması) — kayıt anında `ValueError`.
5. `benchmark_type in BENCHMARK_STRATEGIES` (kapalı küme — bkz. aşağı).
6. `ideal_direction`'a göre eşik şekli doğrulanır: `RANGE_IS_BETTER` ise
   HER dolu eşik bir `(min, max)` tuple'ı olmalı (`min < max`); aksi
   halde HER dolu eşik bir skaler `Decimal` olmalı.
7. **Monotonluk doğrulaması** — `HIGHER_IS_BETTER` için
   `critical < weak < average < good < excellent` (skaler sınırlar
   kesişmez/çakışmaz); `LOWER_IS_BETTER` için ters sıra;
   `RANGE_IS_BETTER` için bantlar iç içe geçmeli (excellent en dar/merkez
   bant, critical en geniş/dış bant) — bozuk bir tasarımcı girdisi
   (ör. `good` sınırının `excellent`'i kapsaması) kayıt anında
   `ValueError` ile YAKALANIR, çalışma zamanında sessizce yanlış bir tier
   üretmez.
8. **(2. tur onay, karar #1) `reliability_ceiling ∈ {"medium",
   "medium_low"}` olmalı** — `provisional=True` iken (4.3C'nin
   TAMAMINDA) `reliability_ceiling="high"` KESİNLİKLE reddedilir
   (`ValueError`) — kayıt anında yakalanır.
9. **(2. tur onay, karar #7) `category="growth"` ise `inflation_adjusted`
   `None` OLAMAZ VE `reliability_ceiling` `"medium_low"` OLMAK
   ZORUNDADIR** — nominal büyüme benchmark'ının bu iki alanı eksik/yanlış
   bırakılarak kayıt edilmesi kayıt anında `ValueError` ile reddedilir.
10. **(2. tur onay, karar #9) `ratio_code == "effective_tax_rate"` ise
    `default_thresholds`, merkezi `STATUTORY_CORPORATE_TAX_RATE_TR`
    sabitinden TÜRETİLMİŞ olmalı** — ham sayısal sınırların başka bir
    dosyada tekrar sabit olarak yazılması (kanuni oranın birden fazla
    yerde bakımı gereken bir "gerçek" haline gelmesi) YASAKTIR; bu kural
    kod incelemesiyle + Adım 4'teki özel bir testle (statutory rate
    sabiti değiştirildiğinde bantların OTOMATİK kaydığını doğrulayan)
    zorlanır.

### 6.1 Override çözümleme sırası (2. tur onay, karar #2)

`evaluate_benchmark()` bir oranı değerlendirirken, birden fazla override
türü aynı anda eşleşebilirse şu ÖNCELİK SIRASI uygulanır:

```
industry_overrides  >  company_size_overrides  >  default_thresholds
```

Gerekçe: oran normlarındaki farklılıklar tipik olarak sektörler arasında,
şirket ölçekleri arasından DAHA BÜYÜKTÜR (ör. bir "ticaret" şirketiyle bir
"imalat" şirketinin stok devir hızı normu, aynı sektördeki küçük/büyük
şirket farkından daha belirleyicidir).

**`country_overrides` bu zincire HİÇ DAHİL DEĞİLDİR** (Bölüm 22 karar #5
— ülke desteği bu fazda tamamen ertelendi, çözümleme mantığında ülke
kavramı hiç YOKTUR, bkz. Bölüm 13). 4.3C'de `industry_overrides`/
`company_size_overrides` dict'leri BOŞ kalacağı için (Bölüm 11/12) bu sıra
şimdilik yalnızca bir SÖZLEŞME olarak testlerle (sahte/sentetik override
fixture'larıyla) doğrulanır — gerçek override verisi geldiğinde davranış
değişmeden çalışmaya devam edeceği garanti altına alınır.

`CALCULATION_STRATEGIES`'in benchmark karşılığı — **kapalı küme**,
eval/exec YOK:

```python
BENCHMARK_STRATEGIES: dict[str, Callable[..., BenchmarkComputationStatus]] = {
    "threshold_bands": evaluate_threshold_bands,  # 4.3C'nin TEK stratejisi
}
```

`benchmark_type` alanı ileride (`"peer_relative"`, `"boolean_flag"` gibi)
genişleyebilir olacak şekilde tasarlandı ama **4.3C yalnızca
`"threshold_bands"` implemente eder** — 4.3B'nin "yalnızca gerçekten
gerekli olan stratejiyi ekle" disiplininin aynısı.

## 7. Benchmark metadata modeli

(Tam dataclass tanımları Bölüm 5'te verildi.) Burada modelin YORUMU:

- `benchmark_code` ile `ratio_code` BİLİNÇLİ OLARAK ayrı alanlardır —
  4.3C'de her ratio_code için TEK bir benchmark_code kaydedilir
  (`benchmark_code == ratio_code`, "genel/varsayılan kapsam" anlamında),
  ama model TEORİK olarak aynı ratio_code'a birden fazla benchmark_code
  bağlanmasına izin verir (ör. gelecekte farklı bir yayınlanmış
  çalışmadan gelen alternatif bir eşik seti, `"current_ratio__iso500"`
  gibi) — bu genişleme YAGNI ilkesiyle 4.3C'de KULLANILMAZ, yalnızca
  alan ayrımı gelecek için hazır bırakılır.
- `default_thresholds` HER ZAMAN doludur (genel/global bant) —
  `industry_overrides`/`company_size_overrides` boş dict'ler olarak
  kalabilir (4.3C'de İKİSİ DE boş kalacak, bkz. Bölüm 11-12) ve
  çözümleme sırasında (Bölüm 6.1) bulunamazsa sessizce
  `default_thresholds`'a düşülür (Bölüm 17). `country_overrides` alanı
  MODELDE YOKTUR (Bölüm 5, 13 — 2. tur onay karar #5).
- `source`/`provisional`/`reliability_ceiling` ÜÇLÜSÜ (Bölüm 9) HER
  girdi için `"internal_heuristic"`/`True`/`"medium"` (büyüme
  kategorisinde `"medium_low"`) olacak 4.3C'de — bu, `reliability`
  tavanını doğrudan etkiler (Bölüm 15).
- `two-way (min,max)` eşikler yalnızca `RANGE_IS_BETTER` için kullanılır
  — bu fazda `current_ratio`, `working_capital_ratio`,
  `working_capital_to_total_assets`, `effective_tax_rate`,
  `payables_turnover` ve `days_payables_outstanding` bu modeli kullanır
  (2. tur onay karar #3, bkz. Bölüm 8.1/8.3/8.4).

## 8. Benchmark kategorileri

**Genel kural (register_benchmark madde 4):** yalnızca `unit ∈ {"ratio",
"percentage", "days"}` olan ratio_code'lar benchmarklanabilir.
`unit="currency"` olan TEK kayıtlı oran — `net_working_capital` (likidite
kategorisi) — şirket ölçeğine göre doğal olarak farklılaştığı (10M TRY
cirolu bir şirketle 10B TRY cirolu bir şirketin net işletme sermayesi
mutlak tutarları KIYASLANAMAZ) için **BENCHMARK_REGISTRY'e dahil
edilmez**. Normalize edilmiş hali zaten ayrı bir kayıtlı oran olarak
mevcuttur: `working_capital_to_total_assets` (unit="ratio") — o
benchmarklanır.

Ayrıca 8 oran **HER ZAMAN `not_calculable`** döndüğü için (bkz. Bölüm 0)
benchmarklanmaz: `sustainable_growth_rate`, `fixed_charge_coverage`, ve
`cash_flow` kategorisinin 6 oranı (`operating_cash_flow_margin`,
`free_cash_flow_margin`, `cash_flow_to_debt`, `cash_return_on_assets`,
`cash_interest_coverage`, `operating_cash_flow_ratio`) — bir değeri HİÇ
üretilmeyen bir orana "iyi/kötü" etiketi vermenin hiçbir iş anlamı yoktur.

**Toplam: 57 kayıtlı oran − 1 (currency) − 8 (her zaman not_calculable) =
48 benchmarklanan ratio_code.**

> **ÖNEMLİ DÜRÜSTLÜK NOTU (2. tur onay karar #1 ile BAĞLAYICI hale
> geldi):** Aşağıdaki `excellent`/`good`/`average`/`weak`/`critical`/
> `warning_threshold` sayısal değerleri, genel kurumsal finans/kredi
> analizi literatüründeki YAYGIN, DERS KİTABI düzeyinde kabul görmüş
> kurallardır (ör. "cari oran 1.5-2.0 idealdir", "borç/özkaynak 1.0 altı
> güvenli sayılır" gibi). **Türkiye'ye özgü, sektör bazlı, ampirik olarak
> kalibre edilmiş GERÇEK veriler DEĞİLDİR** — HER girdi
> `source="internal_heuristic"`, `provisional=True`,
> `reliability_ceiling="medium"` (büyüme kategorisinde `"medium_low"`)
> ÜÇLÜSÜYLE işaretlenmiştir (Bölüm 5, 9, 15). **Bu üçü BİRLİKTE, bu
> eşiklerin Health Score veya Credit Score hesaplamasına
> BAĞLANMAYACAĞININ ve gerçek TCMB/KAP/İSO/BDDK veya doğrulanmış sektör
> verisi gelmeden resmi/ampirik bir referansmış gibi
> SUNULMAYACAĞININ bağlayıcı işaretidir.**

### 8.1 Likidite (6 benchmark)

| benchmark_code | ratio_code | unit | ideal_direction | critical | weak | average | good | excellent | warning_threshold |
|---|---|---|---|---|---|---|---|---|---|
| current_ratio | current_ratio | ratio | range_is_better | (-∞,0.8)∪(3.5,∞) | [0.8,1.0)∪(2.5,3.5] | [1.0,1.3)∪(2.0,2.5] | [1.3,1.5)∪(1.8,2.0] | [1.5,1.8] | 1.0 |
| working_capital_ratio | working_capital_ratio | ratio | range_is_better | *(current_ratio ile AYNI `BenchmarkThresholds` nesnesi paylaşılır — bkz. not)* | | | | | 1.0 |
| quick_ratio | quick_ratio | ratio | higher_is_better | <0.4 | 0.4–0.7 | 0.7–1.0 | 1.0–1.5 | >1.5 | 0.7 |
| cash_ratio | cash_ratio | ratio | higher_is_better | <0.1 | 0.1–0.2 | 0.2–0.5 | 0.5–1.0 | >1.0 | 0.2 |
| defensive_interval_ratio | defensive_interval_ratio | days | higher_is_better | <30 | 30–60 | 60–90 | 90–180 | >180 | 60 |
| working_capital_to_total_assets | working_capital_to_total_assets | ratio | range_is_better | <-0.05 or >0.45 | [-0.05,0)∪(0.35,0.45] | [0,0.05)∪(0.30,0.35] | [0.05,0.10)∪(0.20,0.30] | [0.10,0.20] | 0.0 |

**Not:** `working_capital_ratio` ve `current_ratio`, `RATIO_REGISTRY`'de
**birebir aynı** formülü (`current_assets / short_term_liabilities`)
paylaşır (4.1/4.2'den kalan, kasıtlı isim ikiliği). Bu yüzden ikisinin
`BenchmarkMetadata`'sı da AYNI `BenchmarkThresholds` nesnesini referans
alır — iki ayrı `benchmark_code` var ama sayısal eşikler TEK bir yerde
tanımlanıp paylaşılır (drift/tutarsızlık riski yapısal olarak önlenir,
4.3B'nin `average_total_assets` tekilleştirme deseniyle aynı ilke).

### 8.2 Borçluluk (9 benchmark)

| benchmark_code | ratio_code | unit | ideal_direction | critical | weak | average | good | excellent | warning_threshold |
|---|---|---|---|---|---|---|---|---|---|
| debt_ratio | debt_ratio | ratio | lower_is_better | >0.75 | 0.6–0.75 | 0.4–0.6 | 0.3–0.4 | <0.3 | 0.6 |
| equity_ratio | equity_ratio | ratio | higher_is_better | <0.2 | 0.2–0.35 | 0.35–0.5 | 0.5–0.6 | >0.6 | 0.35 |
| debt_to_equity | debt_to_equity | ratio | lower_is_better | >4.0 | 2.0–4.0 | 1.0–2.0 | 0.5–1.0 | <0.5 | 2.0 |
| long_term_debt_to_equity | long_term_debt_to_equity | ratio | lower_is_better | >2.0 | 1.0–2.0 | 0.5–1.0 | 0.25–0.5 | <0.25 | 1.0 |
| short_term_debt_ratio | short_term_debt_ratio | ratio | lower_is_better | >0.9 | 0.75–0.9 | 0.6–0.75 | 0.4–0.6 | <0.4 | 0.75 |
| financial_leverage_multiplier | financial_leverage_multiplier | ratio | lower_is_better | >5.0 | 3.0–5.0 | 2.0–3.0 | 1.5–2.0 | <1.5 | 3.0 |
| interest_coverage_ratio | interest_coverage_ratio | ratio | higher_is_better | <1 | 1–2 | 2–4 | 4–8 | >8 | 1.5 |
| ebitda_coverage_ratio | ebitda_coverage_ratio | ratio | higher_is_better | <1 | 1–3 | 3–6 | 6–10 | >10 | 2 |
| debt_to_ebitda | debt_to_ebitda | ratio | lower_is_better | >6.0 | 4.0–6.0 | 2.5–4.0 | 1.5–2.5 | <1.5 | 4.0 |

`interest_coverage_ratio`/`ebitda_coverage_ratio`, ilgili oran
`NO_OBLIGATION` (finansman gideri=0) durumundayken benchmark
değerlendirmesi de `RATIO_STATUS_NOT_CALCULATED` döner — "faiz yükü yok"
olumlu bir iş durumu olsa da, `value=None` olduğu için sayısal bir tier
FABRİKE EDİLMEZ (bkz. Bölüm 16).

### 8.3 Kârlılık (11 benchmark)

| benchmark_code | ratio_code | unit | ideal_direction | critical | weak | average | good | excellent | warning_threshold |
|---|---|---|---|---|---|---|---|---|---|
| gross_profit_margin | gross_profit_margin | percentage | higher_is_better | <5 | 5–15 | 15–25 | 25–40 | >40 | 10 |
| operating_profit_margin | operating_profit_margin | percentage | higher_is_better | <0 | 0–6 | 6–12 | 12–20 | >20 | 3 |
| net_profit_margin | net_profit_margin | percentage | higher_is_better | <0 | 0–3 | 3–8 | 8–15 | >15 | 1 |
| ebit_margin | ebit_margin | percentage | higher_is_better | <0 | 0–5 | 5–10 | 10–18 | >18 | 2 |
| ebitda_margin | ebitda_margin | percentage | higher_is_better | <0 | 0–8 | 8–14 | 14–22 | >22 | 3 |
| pretax_profit_margin | pretax_profit_margin | percentage | higher_is_better | <0 | 0–3 | 3–7 | 7–14 | >14 | 1 |
| return_on_capital_employed | return_on_capital_employed | percentage | higher_is_better | <0 | 0–6 | 6–12 | 12–20 | >20 | 3 |
| effective_tax_rate | effective_tax_rate | ratio | range_is_better | <0 or >0.60 | [0,0.10)∪(0.40,0.60] | [0.10,0.15)∪(0.33,0.40] | [0.15,0.20)∪(0.28,0.33] | [0.20,0.28] | ±0.10 sapma |
| return_on_invested_capital | return_on_invested_capital | percentage | higher_is_better | <0 | 0–5 | 5–10 | 10–18 | >18 | 2 |
| return_on_assets | return_on_assets | percentage | higher_is_better | <0 | 0–2 | 2–5 | 5–10 | >10 | 1 |
| return_on_equity | return_on_equity | percentage | higher_is_better | <0 | 0–6 | 6–12 | 12–20 | >20 | 2 |

`effective_tax_rate` bandı, Türkiye'nin (bu dokümanın yazıldığı tarihte)
~%25 kurumlar vergisi oranı civarında merkezlenmiştir — **bu oran yasal
olarak değişebilir.** 2. tur onay karar #9 gereği bu MERKEZİLEŞTİRİLMİŞTİR:

```python
# app/engines/common/benchmark_types.py -- TEK kaynak
STATUTORY_CORPORATE_TAX_RATE_TR: Decimal = Decimal("0.25")

def _effective_tax_rate_thresholds(statutory_rate: Decimal) -> BenchmarkThresholds:
    return BenchmarkThresholds(
        excellent=(statutory_rate - Decimal("0.05"), statutory_rate + Decimal("0.03")),
        good=(statutory_rate - Decimal("0.10"), statutory_rate + Decimal("0.08")),
        average=(statutory_rate - Decimal("0.15"), statutory_rate + Decimal("0.15")),
        weak=(Decimal("0"), statutory_rate + Decimal("0.35")),
        critical=None,  # <0 veya >0.60 -- 4.3B'nin [0,1]-dışı uyarısıyla
                        # TUTARLI olarak ayrıca ele alınır (aşağıda).
        warning_threshold=Decimal("0.10"),  # statutory_rate'ten sapma
    )
```

`benchmark_registry.py` bu fonksiyonu `STATUTORY_CORPORATE_TAX_RATE_TR`
İLE çağırarak `effective_tax_rate` girdisini kaydeder — ham sayısal sınır
DEĞERLERİ (0.20/0.28/0.15/0.33 vb.) HİÇBİR dosyada ikinci kez SABİT
olarak YAZILMAZ (Bölüm 6 madde 10 kuralı). Mevzuat değiştiğinde yalnızca
`STATUTORY_CORPORATE_TAX_RATE_TR` güncellenir, tüm bant TEK noktadan
kayar. 4.3B'nin `_apply_effective_tax_rate_range_check`'in ürettiği [0,1]
dışı uyarısıyla TUTARLI olarak, aralık dışı değerler burada da otomatik
`critical` bandına düşer.

### 8.4 Faaliyet (10 benchmark)

| benchmark_code | ratio_code | unit | ideal_direction | critical | weak | average | good | excellent | warning_threshold |
|---|---|---|---|---|---|---|---|---|---|
| asset_turnover | asset_turnover | ratio | higher_is_better | <0.3 | 0.3–0.6 | 0.6–1.0 | 1.0–1.5 | >1.5 | 0.5 |
| inventory_turnover | inventory_turnover | ratio | higher_is_better | <1.5 | 1.5–3 | 3–5 | 5–8 | >8 | 2 |
| receivables_turnover | receivables_turnover | ratio | higher_is_better | <2 | 2–5 | 5–8 | 8–12 | >12 | 3 |
| payables_turnover | payables_turnover | ratio | **range_is_better** | <2 or >14 | [2,3)∪(11,14] | [3,4)∪(9,11] | [4,5)∪(7,9] | [5,7] | <4 veya >9 |
| fixed_asset_turnover | fixed_asset_turnover | ratio | higher_is_better | <0.7 | 0.7–1.5 | 1.5–2.5 | 2.5–4 | >4 | 1 |
| working_capital_turnover | working_capital_turnover | ratio | higher_is_better | <1 | 1–3 | 3–5 | 5–8 | >8 | 2 |
| days_inventory_outstanding | days_inventory_outstanding | days | lower_is_better | >120 | 75–120 | 45–75 | 30–45 | <30 | 90 |
| days_sales_outstanding | days_sales_outstanding | days | lower_is_better | >90 | 60–90 | 45–60 | 30–45 | <30 | 75 |
| days_payables_outstanding | days_payables_outstanding | days | **range_is_better** | <5 or >150 | [5,15)∪(120,150] | [15,30)∪(95,120] | [30,45)∪(75,95] | [45,75] | <15 veya >95 |
| cash_conversion_cycle | cash_conversion_cycle | days | lower_is_better | >90 | 60–90 | 30–60 | 0–30 | <0 | 60 |

**Not (2. tur onay, karar #3/#9 — ÇÖZÜMLENDİ):** `payables_turnover`/
`days_payables_outstanding` artık `RANGE_IS_BETTER` olarak modellenmiştir
— hem AŞIRI HIZLI ödeme (tedarikçi finansmanından yararlanılmıyor, nakit
verimsiz kullanılıyor) HEM AŞIRI YAVAŞ ödeme (ödeme güçlüğü/likidite
sıkıntısı sinyali) `weak`/`critical` bantlarına düşecek şekilde İKİ
TARAFLI risk AÇIKÇA modellenmiştir. `excellent` bandı ORTA bir "sweet
spot" (payables_turnover için [5,7], DPO için [45,75] gün) — ikisi de
`RATIO_REGISTRY`'de matematiksel olarak TERS ilişkili olduğu için (DPO =
days_in_period / payables_turnover) bantlar birbirini yaklaşık olarak
yansıtacak şekilde ayrı ayrı kalibre edildi (tam matematiksel tersi
DEĞİL — turnover ve gün-bazlı yuvarlama farkları nedeniyle küçük
sapmalar olabilir, bu KABUL EDİLEBİLİR bir yaklaşıklıktır). Test sınırları
Adım 5'te açıkça (her bandın İKİ ucu da) test edilecektir (2. tur onay
karar #9).

### 8.5 Verimlilik (6 benchmark)

| benchmark_code | ratio_code | unit | ideal_direction | critical | weak | average | good | excellent | warning_threshold |
|---|---|---|---|---|---|---|---|---|---|
| operating_expense_ratio | operating_expense_ratio | percentage | lower_is_better | >30 | 22–30 | 15–22 | 10–15 | <10 | 25 |
| cost_of_sales_ratio | cost_of_sales_ratio | percentage | lower_is_better | >90 | 78–90 | 65–78 | 50–65 | <50 | 85 |
| overhead_ratio | overhead_ratio | percentage | lower_is_better | >28 | 20–28 | 13–20 | 8–13 | <8 | 22 |
| ebit_to_opex | ebit_to_opex | ratio | higher_is_better | <0.3 | 0.3–0.8 | 0.8–1.3 | 1.3–2.0 | >2.0 | 0.6 |
| non_operating_income_dependency | non_operating_income_dependency | percentage | lower_is_better | >60 | 35–60 | 20–35 | 10–20 | <10 | 40 |
| financing_expense_to_sales | financing_expense_to_sales | percentage | lower_is_better | >10 | 6–10 | 3–6 | 1–3 | <1 | 6 |

### 8.6 Büyüme (6 benchmark)

> **KRİTİK MAKROEKONOMİK UYARI — 2. tur onay karar #7 ile ÇÖZÜMLENDİ:**
> Aşağıdaki 6 büyüme benchmark'ının TAMAMI **nominal** (enflasyondan
> arındırılmamış) büyüme oranları içindir. Türkiye'nin yüksek enflasyon
> ortamında, ör. yıllık %60 TÜFE varken %30 nominal satış büyümesi aslında
> REEL bir KÜÇÜLMEDİR. Bu bantlar bu düzeltmeyi YAPMAZ. Karar #7 gereği,
> bu 6 girdinin HER BİRİ artık AÇIKÇA şu şekilde işaretlenir:
> `inflation_adjusted=False` (Bölüm 5) ve `reliability_ceiling=
> "medium_low"` (Bölüm 15'teki genel `"medium"` tavanından DAHA DÜŞÜK —
> büyüme kategorisinin özel, ek bir belirsizlik kaynağı taşıdığının
> açık göstergesi). 4.3C reel/TÜFE düzeltmeli bir varyant YAZMAZ (Bölüm
> 3, bağlayıcı sınır) — gelecekteki Health/Credit Score hesapları bu
> oranları enflasyon düzeltmesi YAPMADAN KULLANAMAZ; bu kısıtlama artık
> veri modelinde (`inflation_adjusted=False` alanı) makine-okunabilir
> şekilde taşınır, yalnızca dokümantasyonda değil.

| benchmark_code | ratio_code | unit | ideal_direction | critical | weak | average | good | excellent | warning_threshold |
|---|---|---|---|---|---|---|---|---|---|
| sales_growth | sales_growth | percentage | higher_is_better | <0 | 0–10 | 10–20 | 20–40 | >40 | 5 |
| gross_profit_growth | gross_profit_growth | percentage | higher_is_better | <0 | 0–10 | 10–20 | 20–40 | >40 | 5 |
| ebitda_growth | ebitda_growth | percentage | higher_is_better | <0 | 0–10 | 10–20 | 20–40 | >40 | 5 |
| net_profit_growth | net_profit_growth | percentage | higher_is_better | <-10 | -10–5 | 5–20 | 20–50 | >50 | 0 |
| total_assets_growth | total_assets_growth | percentage | higher_is_better | <0 | 0–5 | 5–15 | 15–30 | >30 | 0 |
| equity_growth | equity_growth | percentage | higher_is_better | <0 | 0–5 | 5–12 | 12–25 | >25 | 0 |

### 8.7 Nakit Akışı — 0 benchmark (bilinçli olarak boş, 2. tur onayla KESİNLEŞTİ)

Cash Flow Engine (Milestone 4.4) henüz yok; bu kategorinin 6 oranı bugün
HER ZAMAN `not_calculable`. **2. tur onay karar #8:** `BENCHMARK_REGISTRY`'de
bu kategori için HİÇBİR girdi açılmaz — ne gerçek eşiklerle, ne de "yer
tutucu"/placeholder olarak. Ölü kod veya sahte yapısal tamlık ÜRETİLMEZ.
Cash Flow benchmark'ları, Cash Flow Engine GERÇEKTEN var olduğunda (4.4
sonrası), ayrı bir milestone ve ayrı bir onayla eklenecektir.

## 9. Benchmark kaynakları

`BenchmarkMetadata.source` alanı, kapalı bir string kümesinden gelir:

```python
BenchmarkSource = (
    "internal_heuristic",       # 4.3C'nin TEK doldurduğu kaynak türü
    "published_industry_study", # rezerve -- ör. İSO 500, TCMB sektör
                                 # bilançoları -- 4.3C'de HİÇ kullanılmaz
    "regulatory_reference",     # rezerve -- ör. BDDK/SPK yayınladığı
                                 # sektörel eşikler
    "peer_percentile_computed", # rezerve -- gerçek müşteri/peer verisinden
                                 # istatistiksel olarak türetilmiş eşikler
)
```

4.3C'de `BENCHMARK_REGISTRY`'deki **48 girdinin TAMAMI**
`source="internal_heuristic"` olarak işaretlenir — bu, dürüstçe, HENÜZ
gerçek/ampirik bir veri kaynağına dayanmadıklarını belirtir (Bölüm 8'in
başındaki uyarıyla tutarlı) ve `reliability` tavanını doğrudan etkiler
(Bölüm 15).

## 10. Percentile / median / ideal range yaklaşımı

`BenchmarkMetadata.supports_percentile: bool` alanı, gelecekte bir
ratio_code için gerçek bir dağılım (ör. "bu sektördeki 500 şirketin
current_ratio'sunun p10/p25/median/p75/p90 değerleri") tanımlanabileceğini
İŞARETLEMEK için vardır. 4.3C'de:

- `supports_percentile=False` **48 girdinin tamamında** — gerçek bir
  percentile veri kümesi (peer şirket örneklemi) bu fazda MEVCUT DEĞİL,
  fabrike edilmez (4.3B'nin `sustainable_growth_rate` politikasıyla aynı
  dürüstlük ilkesi).
- Model, ileride doldurulacak bir `PercentileEstimate` dataclass'ı için
  hazır bir sözleşme tanımlar (implementasyon fazında eklenecek):
  ```python
  @dataclass(frozen=True)
  class PercentileEstimate:
      p10: Decimal; p25: Decimal; median: Decimal
      p75: Decimal; p90: Decimal
      sample_size: int
      percentile_source: str   # ör. "tcmb_sektor_bilancolari_2025"
      as_of_date: date
  ```
- `evaluate_benchmark()` çağrıldığında `supports_percentile=True` AMA
  gerçek `PercentileEstimate` verisi o an sağlanmamışsa, kontrollü
  `BenchmarkComputationStatus.PERCENTILE_DATA_UNAVAILABLE` döner —
  ASLA sahte bir percentile ("%50'nin üzerinde" gibi) üretilmez.
- "İdeal aralık" (ideal range) kavramı zaten `ideal_direction=
  RANGE_IS_BETTER` + `(min,max)` eşik çiftleri ile Bölüm 5/6'da
  karşılanmıştır — ayrı bir mekanizma GEREKTİRMEZ.

**Sonuç: 4.3C, percentile ALTYAPISINI tasarlar ama HİÇBİR ratio_code için
gerçek percentile verisi YAYINLAMAZ.**

## 11. Sektör bazlı benchmark desteği

`Company.sector` (serbest metin) ve `Company.nace_code` (yapısal
sınıflandırma kodu) **bugün zaten mevcut** (Bölüm 0). Bu, sektör
override'ları için gerçek bir veri kaynağının VAR OLDUĞU anlamına gelir
— ama iki önemli tasarım kararı gerekiyor:

1. **`sector` (serbest metin) DEĞİL, `nace_code` (yapısal) override
   anahtarı olarak kullanılmalıdır** — serbest metin alanların yazım/
   büyük-küçük harf tutarsızlığı ("Tekstil" vs "tekstil" vs "TEKSTİL"),
   override tablosunda sessizce KAÇIRILAN eşleşmelere yol açar (Bölüm 21
   risk #4).
2. NACE kodları binlerce alt kategoriye ayrılır — her NACE kodu için ayrı
   bir benchmark seti tutmak pratik değildir. Önerilen yaklaşım: NACE
   kodlarını ~15-20 GENİŞ "benchmark sektör grubu"na (ör.
   "imalat_tekstil", "perakende_ticaret", "inşaat", "gıda_üretim" gibi)
   eşleyen AYRI bir statik `NACE_TO_BENCHMARK_INDUSTRY_GROUP: dict[str,
   str]` eşleme tablosu tasarlanmalı (implementasyon fazında).

4.3C'de: `BenchmarkMetadata.supports_industry_override=True` **yapısal
olarak** 48 girdinin tamamında set edilir (kapasite VAR), ama
`industry_overrides` dict'i **HEPSİNDE BOŞ** kalır — gerçek sektör-bazlı
sayılar (ör. "tekstil sektöründe current_ratio ortalaması X'tir")
Türkiye'ye özgü, ampirik olarak toplanmış bir veri kümesi gerektirir ve bu
milestone'un kapsamı dışındadır (Bölüm 22 karar #1).

Çözümleme sırasındaki önceliği (2. tur onay karar #2:
`industry > company_size > default`) için bkz. Bölüm 6.1.

## 12. Şirket ölçeği bazlı benchmark desteği

**Kritik bulgu (Bölüm 0):** `Company` modelinde bugün şirket ölçeğini
(çalışan sayısı, ciro dilimi, KOBİ sınıfı vb.) belirleyen HİÇBİR alan
YOK. Bu, iki yol sunuyor:

**Yol A (ÖNERİLEN, şema değişikliği GEREKTİRMEZ):** şirket ölçeğini,
Financial Ratio Engine'in ZATEN ürettiği `net_sales`/`total_assets`
büyüklüklerinden **türetilmiş bir proxy** olarak hesapla —
`app/engines/common/company_size_classifier.py::classify_company_size(
net_sales, total_assets) -> tuple[str, str]` (döner: `(bucket,
reliability)`). Türkiye'deki KOBİ tanımına (KGK/KOSGEB eşikleri — yıllık
net satış hasılatı VEYA mali bilanço toplamı) yakın bir yaklaşım
kullanılabilir: `"micro"` / `"small"` / `"medium"` / `"large"`. **Önemli
sınırlama:** resmi KOBİ tanımı çalışan sayısını DA dikkate alır; bu veri
hiçbir yerde YOK, bu yüzden bu sınıflandırma yalnızca mali büyüklük
bacağını kullanır ve `reliability="medium"` (asla "high") olarak
işaretlenmelidir — dürüstçe eksik bir sınıflandırma olduğu açık kalır.

**Yol B (REDDEDİLDİ bu fazda):** `Company`'ye `employee_count`/
`company_size_bucket` gibi yeni bir DB alanı ekle — bu bir migration
gerektirir, bu fazın "migration yok" kısıtına aykırıdır.

**2. tur onay karar #4 (bağlayıcı, Yol A'yı netleştirir):**
- Migration YAZILMAZ — Yol A (mali büyüklük proxy'si) onaylandı.
- `classify_company_size()`'ın döndürdüğü `reliability` **HİÇBİR ZAMAN
  `"high"` OLAMAZ** (kayıt/kullanım anında bu kısıtlama koda ve teste
  bağlanır — en fazla `"medium"`).
- Çalışan sayısının VERİ OLARAK EKSİK OLDUĞU, üretilen her sonuçta
  AÇIKÇA belirtilmelidir (ör. `employee_count_available=False` alanı
  veya eşdeğer bir açıklayıcı not/uyarı — kesin şekil Adım 2'de
  netleşecek, ama bilgi HİÇBİR ZAMAN sessizce kaybolmayacaktır).
- Bu sınıflandırma **resmi bir KOBİ sınıflandırması OLARAK
  SUNULMAYACAKTIR** — çıktıda/dokümantasyonda "yaklaşık, yalnızca mali
  büyüklüğe dayalı bir dahili sınıflandırma" olduğu açıkça ifade edilir,
  KGK/KOSGEB'in resmi tanımıyla eşdeğer olduğu iddia edilmez.

4.3C'de: `supports_company_size_override=True` yapısal olarak 48
girdinin tamamında set edilir, `company_size_classifier.py`'nin TASARIMI
(saf fonksiyon imzası) bu dokümanda verilir (Bölüm 4.2), ama
`company_size_overrides` dict'i **HEPSİNDE BOŞ** kalır (gerçek ölçek-bazlı
eşik farklılaştırması, sektör override'larıyla aynı gerekçeyle, ayrı bir
veri toplama çabası gerektirir).

## 13. Ülke desteği

**2. tur onay karar #5 (bağlayıcı — YAGNI ilkesi tam olarak uygulanır):**
ülke desteği bu fazda **TAMAMEN ERTELENMİŞTİR** — yalnızca "veri
doldurulmadı" anlamında değil, **hiçbir kod/model iskeleti bile
eklenmez.** Bu, Bölüm 11/12'deki sektör/şirket-ölçeği yaklaşımından
BİLİNÇLİ OLARAK farklıdır (onlarda yapısal destek `True` ama veri boş;
ülkede yapısal destek dahi YOK).

**Kesin olarak EKLENMEYECEKLER:**
- `EngineRunContext.country_code` alanı (zaten Bölüm 4.2 kararı gereği
  `EngineRunContext`'e HİÇBİR alan eklenmiyor, ama açıkça teyit edilir:
  ülke için de HAYIR).
- `BenchmarkMetadata.country_overrides` alanı (Bölüm 5'te dataclass'tan
  ÇIKARILDI).
- `BenchmarkMetadata.supports_country_override` alanı (Bölüm 5'te
  dataclass'tan ÇIKARILDI).
- Herhangi bir "country resolution logic" (Bölüm 6.1'deki override
  çözümleme sırasında ülke kavramı hiç GEÇMEZ).
- Boş/iskelet ("skeleton") bir country modülü/sınıfı/enum'u.

**Gerekçe:** `Company` modelinde `country` alanı Milestone 2'de BİLİNÇLİ
OLARAK dışarıda bırakılmış ve BUGÜN HİÇ YOK (Bölüm 0). Platform bugün
fiilen yalnızca Türkiye şirketlerini analiz ediyor. Kullanılmayacağı
kesin olan bir soyutlamayı şimdiden inşa etmek (YAGNI ihlali) hem
gereksiz karmaşıklık hem de "yarım kalmış/test edilmemiş" bir kod yüzeyi
riski taşır. Çok-ülkeli genişleme gerçek bir yol haritası maddesi
olduğunda (`Company.country` alanı + migration + gerçek ülke-bazlı veri
+ bu tasarımın kendisi güncellenerek) sıfırdan, o zamanki gerçek ihtiyaca
göre tasarlanacaktır.

## 14. Versionlama

İki BAĞIMSIZ versiyon numarası:

- `RATIO_REGISTRY_VERSION` (bugün `"1.1.0"`) — oran FORMÜLLERİ
  değiştiğinde artar (4.3B'de `"1.0.0"` → `"1.1.0"`).
- `BENCHMARK_REGISTRY_VERSION` (yeni, önerilen: `"1.0.0"` 4.3C'nin ilk
  implementasyonunda) — benchmark EŞİKLERİ (sayısal bantlar) veya
  metadata şekli değiştiğinde artar; RATIO_REGISTRY_VERSION'dan TAMAMEN
  BAĞIMSIZ artar (bir sektör eşiği yıllık güncellendiğinde ratio
  formülleri DEĞİŞMEZ).

Her `BenchmarkMetadata` kaydı ayrıca kendi `version`/`last_reviewed_at`
alanlarını taşır (Bölüm 5) — TEK bir benchmark girdisinin güncellenmesi
(ör. yalnızca `debt_ratio`'nun eşikleri revize edilirse) tüm registry'nin
versiyonunu artırmadan izlenebilir olsun diye (kayıt-seviyesi granülerlik,
registry-seviyesi versiyon ile BİRLİKTE var olur).

`evaluate_benchmarks()`'ın ürettiği `result_json`, HEM okuduğu ratio
sonucunun `ratio_registry_version`'unu HEM KENDİ
`benchmark_registry_version`'unu taşır — bir geçmiş analiz sonucunun
"hangi formül VE hangi eşik setiyle" üretildiği HER ZAMAN yeniden
kurulabilir (Bölüm 17).

## 15. Reliability modeli

Benchmark `reliability`'si, `ratio`'nun kendi `reliability`'sinden
**BAĞIMSIZ DEĞİL** — iki katmanlı (2. tur onay kararları #1/#4/#7 ile
netleşti):

1. **Taban:** benchmark edilen oranın KENDİ `reliability`'si (ör.
   `average_total_assets`'in `ending_balance_fallback`'ten gelen
   `"medium"`'u) — bir oranın DEĞERİ zaten düşük güvenilirse, ona
   dayanan benchmark yorumu da ASLA daha yüksek bir güvenilirlikte
   sunulamaz (`_worse_reliability` ile AYNI "kötüsünü al" ilkesi, 4.3B
   Bölüm 8 tutarlılık kuralının benchmark'a genellemesi).
2. **Girdi-seviyesi tavan (`BenchmarkMetadata.reliability_ceiling`,
   Bölüm 5):** `provisional=True` olduğu sürece (4.3C'nin TAMAMI)
   benchmark reliability'si **ASLA `"high"` OLAMAZ**:
   - Genel kural: `reliability_ceiling="medium"` (48 girdinin çoğu —
     likidite/borçluluk/kârlılık/faaliyet/verimlilik).
   - **Büyüme kategorisi istisnası (karar #7):**
     `reliability_ceiling="medium_low"` — nominal (TÜFE düzeltmesiz)
     olmanın getirdiği EK belirsizlik nedeniyle genel tavandan DAHA
     DÜŞÜK.
   - **Şirket ölçeği sınıflandırması (karar #4):**
     `classify_company_size()`'ın kendi ürettiği `reliability` de AYNI
     ilkeyle **ASLA `"high"` olamaz** (çalışan sayısı verisi eksik) —
     bu, benchmark reliability zincirine bir company_size override
     kullanıldığında girdi olarak katılır.
   - `"high"` benchmark reliability'si yalnızca `source ∈
     {"published_industry_study", "regulatory_reference",
     "peer_percentile_computed"}` olan (4.3C'de HİÇ populate edilmeyen)
     girdiler için ayrılmıştır.

Nihai benchmark reliability = `_worse_reliability(ratio_reliability,
metadata.reliability_ceiling)` — mevcut `_worse_reliability` yardımcı
fonksiyonu (bugün `financial_ratios/service.py` içinde) `app/engines/
common/reliability.py`'ye TAŞINIR (Bölüm 4.2, Adım 1) ve HER İKİ motor
da (ratio + benchmark) oradan import eder — yeni bir kopya YAZILMAZ.

## 16. Computation status etkileri

`BenchmarkComputationStatus` (Bölüm 5) davranışları:

- **`EVALUATED`**: ratio `status=CALCULATED` VE `value is not None` VE
  ilgili `BENCHMARK_REGISTRY` girdisi bulunur → tier ataması yapılır.
- **`RATIO_STATUS_NOT_CALCULATED`**: ratio `status != CALCULATED`
  (yani `missing_input`/`undefined_zero_denominator`/`no_obligation`/
  `not_applicable`/`not_calculable`'IN HERHANGİ BİRİ) → benchmark
  DEĞERLENDİRİLMEZ, `value=None`, orijinal ratio `status`'u
  `ratios[key]["benchmark"]["underlying_ratio_status"]` olarak
  ŞEFFAFÇA taşınır (asla gizlenmez, asla bir tier'a zorlanmaz — ör.
  `NO_OBLIGATION` "iyi" anlamına gelse de sayısal bir tier FABRİKE
  EDİLMEZ).
- **`BENCHMARK_NOT_REGISTERED`**: `ratio_code`, `BENCHMARK_REGISTRY`'de
  yok (ör. bugün `cash_flow` kategorisinin 6 oranı, veya gelecekte
  4.3E/F/G'nin henüz benchmarklanmamış yeni oranları) — dürüstçe
  raporlanır, `missing_categories`'e benzer bir "eksik benchmark"
  listesi üretilir.
- **`PERCENTILE_DATA_UNAVAILABLE`** (rezerve, 4.3C'de asla tetiklenmez
  çünkü `supports_percentile=False` her yerde).
- **`STALE_BENCHMARK_DATA`** (rezerve, Bölüm 17).

`evaluate_benchmark()` saf fonksiyonu, `compute_sum_division` gibi
mevcut stratejilerin ATTIĞI güvenlik desenini birebir korur: hiçbir ham
exception dışarı sızmaz, beklenmeyen bir durum kontrollü bir status'a
(`BENCHMARK_NOT_REGISTERED` benzeri bir "internal error" varyantı)
dönüştürülür.

## 17. Ratio ile benchmark ilişkisinin yaşam döngüsü

1. Bir `RatioFormulaMetadata` `RATIO_REGISTRY`'ye kayıt edilir (belirli
   bir `RATIO_REGISTRY_VERSION`'da), formülü + `unit`'i sabitlenir.
2. Bir `BenchmarkMetadata`, o `ratio_code`'a `register_benchmark()` ile
   bağlanır — kayıt anında `unit` eşleşmesi doğrulanır (Bölüm 6) ve
   **hangi `RATIO_REGISTRY_VERSION`'a karşı doğrulandığı**
   `compatible_ratio_registry_version` alanına yazılır (Bölüm 5'e
   eklenecek bir alan, implementasyon fazında netleşir).
3. Bir analiz çalıştırıldığında: ratio HESAPLANIR (değişmez, bir kez
   üretilir) → benchmark o ANKİ `BENCHMARK_REGISTRY`'ye göre
   DEĞERLENDİRİLİR (ratio'nun DEĞERİ sabit kalırken tier ataması,
   registry güncellenirse DEĞİŞEBİLİR).
4. **Formül değişikliği senaryosu:** eğer gelecekte (ör. 4.3E'de) bir
   ratio'nun formülü/birimi değişir ve `RATIO_REGISTRY_VERSION` artarsa,
   o ratio_code'a bağlı eski `BenchmarkMetadata`'nın
   `compatible_ratio_registry_version`'u ARTIK GEÇERLİ olan versiyonla
   eşleşmeyebilir → `evaluate_benchmark()` bunu tespit eder ve
   `STALE_BENCHMARK_DATA` döner (sessizce YANLIŞ bir karşılaştırma
   YAPILMAZ) — benchmark girdisinin manuel olarak gözden geçirilip
   yeniden onaylanması (yeni bir `compatible_ratio_registry_version` ile)
   gerekir.
5. **Eşik güncelleme senaryosu:** bir benchmark'ın sayısal bantları
   (ör. `debt_ratio`'nun `critical` sınırı) güncellendiğinde, YALNIZCA
   `BENCHMARK_REGISTRY_VERSION` artar — ratio'nun kendisi HİÇ etkilenmez,
   geçmiş analiz sonuçlarındaki `ratio` değerleri DEĞİŞMEZ, yalnızca
   BUGÜNDEN İTİBAREN yapılan yeni benchmark değerlendirmeleri yeni
   bantları kullanır. Geçmiş bir analiz sonucu tekrar görüntülendiğinde,
   o anki `benchmark_registry_version_at_evaluation` (sonuçla BİRLİKTE
   saklanan) sayesinde "o zaman hangi eşiklerle değerlendirildiği"
   yeniden kurulabilir (reprodüktibilite).

## 18. API etkileri

**2. tur onay karar #6 ile KESİNLEŞTİ: bu milestone'da SIFIR API
değişikliği, SIFIR adapter, SIFIR `AnalysisType` eklemesi, SIFIR
migration.** `BenchmarkEngineAdapter` diye bir sınıf bu fazda
YAZILMAYACAK (Bölüm 4.2) — `app.engines.registry`'ye HİÇBİR kayıt
yapılmayacak. `evaluate_benchmarks()` yalnızca doğrudan çağrılan, saf bir
Python fonksiyonudur (ör. gelecekte bir Jupyter/script/manuel test
içinden çağrılabilir, ama HİÇBİR gerçek HTTP isteğine/bulk upload
akışına bağlı DEĞİLDİR).

**Gelecekteki (bu milestone'un TAMAMEN DIŞINDA, ayrı bir milestone VE
ayrı bir onay gerektiren) olası yön, yalnızca bilgi amaçlı — bu doküman
bunu ÖNERMEZ, yalnızca gelecekte değerlendirilebilecek bir olasılık
olarak not eder:**

- Persistence/gerçek akış bağlanması istenirse, yeni bir
  `AnalysisType.BENCHMARK_COMPARISON` enum üyesi eklenmesi GEREKİR
  (Bölüm 4.1) — bu, `financial_analysis_results.analysis_type` CHECK
  constraint'ini (`ck_financial_analysis_results_analysis_type`,
  `native_enum=False, create_constraint=True` — Bölüm 0'da doğrulandı)
  güncelleyen bir Alembic migration'ı GEREKTİRİR.
- Böyle bir endpoint eklendiğinde muhtemel şekli:
  `GET /companies/{company_id}/periods/{period_id}/analyses/benchmark-comparison`
  — `result_json["categories"][cat]["ratios"][key]["benchmark"]` alt
  yapısıyla (bkz. Bölüm 16'daki alan örnekleri).

Bu ikisi de **bu milestone'da YAZILMAZ.**

## 19. Test stratejisi

`app/engines/financial_ratios/**`'in test rigor'uyla AYNI disiplinle
(sandbox'ta gerçekten çalıştırılabilir, sqlalchemy'siz):

1. **`register_benchmark` doğrulama testleri:** yinelenen `benchmark_code`
   reddi; var olmayan `ratio_code` reddi; `unit` uyuşmazlığı reddi;
   `unit="currency"` reddi; `RANGE_IS_BETTER` için skaler eşik verilirse
   reddi; monotonluk ihlali (ör. `good` sınırı `excellent`'i kapsıyor)
   reddi.
2. **`evaluate_benchmark` saf fonksiyon testleri:** her tier sınırının
   İKİ TARAFI (ör. `debt_ratio=0.75` tam sınırda hangi tarafa düşüyor —
   sınır dahil/hariç kuralı AÇIKÇA test edilir); `value=None` girişte
   HİÇBİR ZAMAN tier üretilmediği; `RATIO_STATUS_NOT_CALCULATED`
   durumunda orijinal ratio status'unun şeffafça taşındığı;
   `RANGE_IS_BETTER` için ikili bant sınırlarının doğru çalıştığı
   (`current_ratio` örneğiyle).
3. **Override çözümleme sırası testleri (Bölüm 22 karar #2'de
   netleşecek sırayla):** sahte/sentetik `industry_overrides`/
   `company_size_overrides` fixture'larıyla, GERÇEK veri populate
   edilmeden ÖNCE bile çözümleme mantığının doğru çalıştığının
   kanıtlanması (4.3B'nin `depends_on_ratios` döngüsel-bağımlılık
   statik testiyle aynı "gerçek veri gelmeden önce iskeleti doğrula"
   disiplini).
4. **`company_size_classifier` testleri:** bilinen mali büyüklük
   kombinasyonlarının doğru `bucket`/`reliability` ürettiği; `None`
   girdilerde fabrike edilmiş bir sınıf ÜRETİLMEDİĞİ.
5. **Uçtan uca `evaluate_benchmarks()` testleri:** gerçek (4.3B
   testlerinden ödünç alınan) BS/IS fixture'larıyla üretilmiş GERÇEK bir
   `analyze_financial_ratios()` çıktısı üzerinde çalıştırılarak, 48
   benchmarklı ratio_code'un hepsinin `EVALUATED` veya doğru
   gerekçeli bir "hesaplanamadı" durumunda olduğunun; 9 benchmarklanmayan
   ratio_code'un (`net_working_capital` + 8 her-zaman-not_calculable)
   `BENCHMARK_NOT_REGISTERED`/ilgisiz olarak dürüstçe işaretlendiğinin
   doğrulanması.
6. **Versiyon uyumsuzluğu testi:** sahte bir `compatible_ratio_
   registry_version` uyuşmazlığı senaryosunda `STALE_BENCHMARK_DATA`
   üretildiğinin kanıtlanması.

Tahmini test sayısı: ~60-80 (4.3B'nin `test_ratio_formulas_unit.py`
büyüklüğüyle KARŞILAŞTIRILABİLİR mertebede) — implementasyon fazında
kesinleşecek.

## 20. Performans analizi

**Bu bir TAHMİNDİR — henüz kod yazılmadığı için ÖLÇÜLEMEZ** (4.3B
raporundaki ~0.22ms/call gibi GERÇEK bir ölçüm burada YOKTUR, dürüstçe
belirtilir).

Karmaşıklık analizi: `evaluate_benchmark()` tek bir oran için sabit
sayıda karşılaştırma yapan (dict lookup + 5 sınır karşılaştırması) O(1)
saf bir fonksiyondur — Decimal bölme/exception riski YOKTUR (yalnızca
karşılaştırma operatörleri). 48 ratio_code için tam bir
`evaluate_benchmarks()` çağrısı, 4.3B'nin 57-oranlık
`analyze_financial_ratios()` çağrısına (~0.22ms) benzer büyüklük
mertebesinde, muhtemelen DAHA DÜŞÜK (bölme/Decimal exception yakalama
yok) bir ek yük (<0.1ms tahmin) getirmesi beklenir. **Bu tahmin,
implementasyon fazının son adımında GERÇEK ölçümle doğrulanmalı ve
raporlanmalıdır** (4.3B Adım 10'daki disiplinle aynı).

## 21. Risk analizi

1. **Ampirik olmayan eşik değerleri (Bölüm 8 başlığındaki uyarı):**
   `internal_heuristic` kaynaklı sayılar, Türkiye'ye özgü sektör
   gerçekliğini yansıtmayabilir → Health/Credit Score'a YANLIŞ sinyal
   verme riski. **Azaltım (2. tur onay karar #1 ile KESİNLEŞTİ):**
   `source="internal_heuristic"` + `provisional=True` +
   `reliability_ceiling="medium"` ÜÇLÜSÜ HER girdide BİRLİKTE taşınır;
   bu üçü, gerçek TCMB/KAP/İSO/BDDK veya doğrulanmış sektör verisi
   gelmeden bu değerlerin Health/Credit Score'a BAĞLANMAMASI gerektiğinin
   makine-okunabilir işaretidir.
2. **Türkiye'nin yüksek enflasyon ortamı, nominal büyüme bantlarını
   (Bölüm 8.6) YANILTICI kılabilir** — %30 nominal büyüme, gerçek TÜFE
   %60 iken REEL bir küçülmedir. **Azaltım (2. tur onay karar #7 ile
   KESİNLEŞTİ):** 4.3C reel/TÜFE düzeltmeli bir varyant YAZMAZ; bunun
   yerine 6 büyüme girdisinin HER BİRİ `inflation_adjusted=False` +
   `reliability_ceiling="medium_low"` ile işaretlenir — gelecekteki
   Health/Credit Score bu alanı KONTROL ETMEDEN bu oranları
   KULLANAMAYACAK şekilde sözleşme netleştirildi.
3. **Şirket ölçeği sınıflandırması yalnızca mali büyüklüklere dayanıyor**
   (çalışan sayısı verisi yok) — emek-yoğun/sermaye-yoğun şirketleri
   yanlış sınıflayabilir. **Azaltım (2. tur onay karar #4 ile
   KESİNLEŞTİ):** `reliability` HİÇBİR ZAMAN `"high"` olamaz + çalışan
   sayısının eksik olduğu çıktıda AÇIKÇA belirtilir + resmi bir KOBİ
   sınıflandırması OLARAK SUNULMAZ (Bölüm 12).
4. **`Company.sector` serbest metin alanı, override eşleştirmesinde
   sessiz kaçırılan eşleşmelere yol açabilir.** **Azaltım:** override
   anahtarı olarak `sector` DEĞİL, yapısal `nace_code` (+ ayrı bir
   NACE→benchmark-grubu eşleme tablosu) kullanılması ÖNERİLİR (Bölüm 11).
5. **Benchmark verisinin bayatlaması** (sayılar yıllarca gözden
   geçirilmezse sessizce yanlış hale gelir). **Azaltım:**
   `last_reviewed_at` zorunlu alan + periyodik gözden geçirme süreci
   (operasyonel, kod dışı) + `STALE_BENCHMARK_DATA` mekanizması
   (Bölüm 17).
6. **Sınır-çizgisi "uçurum etkisi"** (ör. net kâr marjı %14.9→%15.1
   olduğunda "average"dan "good"a ANİ sıçrama, oysa gerçek fark
   önemsizdir). **Azaltım:** ileride sürekli percentile skorlaması
   (Bölüm 10) bu etkiyi yumuşatabilir — 4.3C'de bu MEVCUT DEĞİL,
   yalnızca gelecekteki bir iyileştirme yolu olarak not edilir.
7. **Health Score'un (gelecek) HEM ham oranı HEM benchmark tier'ını AYRI
   girdi olarak kullanması durumunda çifte sayım riski** — bu, Benchmark
   Engine'in kendi kaygısı DEĞİLDİR, Health Score tasarımına
   devredilmiştir (kapsam dışı, bkz. Bölüm 2).
8. **Ratio formülü/birimi ileride değişirse eski benchmark eşiklerinin
   sessizce yanlış kalması** — Bölüm 17'de `STALE_BENCHMARK_DATA`
   mekanizmasıyla ele alındı.
9. **`AnalysisType` CHECK constraint migration'ının (Bölüm 18) yanlış
   zamanlanması** — implementasyon planının erken bir adımında
   yapılırsa, geri kalan tasarım/kod hazır olmadan bir DB şeması
   değişikliği "asılı kalabilir". **Azaltım:** Bölüm 23'te bu migration
   BİLİNÇLİ OLARAK son adımlardan birine (Adım 8) yerleştirildi ve AYRI
   onay şartı kondu.

## 22. Çözümlenmiş tasarım kararları (2. tur onay — 9 bağlayıcı karar)

Aşağıdaki 9 karar, kullanıcının 2. tur onayıyla BAĞLAYICI hale gelmiştir.
Her karar, doğrudan etkilediği bölüm(ler)de de işlendi (çapraz referans
verildi) — burada TEK bir yerde toplu özet olarak tutulur.

1. **Geçici (provisional) benchmark eşikleri.** `source=
   "internal_heuristic"`, `reliability_ceiling="medium"`,
   `provisional=True` — 4.3C'nin TÜM girdilerinde HER ZAMAN BİRLİKTE
   taşınır (Bölüm 5). Bu eşikler gerçek Türkiye sektör verisi DEĞİLDİR.
   Health Score veya Credit Score hesaplamasına BAĞLANMAYACAK. Gerçek
   TCMB/KAP/İSO/BDDK veya doğrulanmış sektör verisi gelmeden resmi ya da
   ampirik bir benchmarkmış gibi SUNULMAYACAK (Bölüm 9, 21).
2. **Override önceliği.** `industry_overrides > company_size_overrides
   > default_thresholds` (Bölüm 6.1). `country` desteği bu fazda
   tamamen ertelendiği için çözümleme zincirine HİÇ DAHİL EDİLMEZ
   (Bölüm 13).
3. **`RANGE_IS_BETTER` kapsamı.** Bu fazda şu 6 oranda kullanılır:
   `current_ratio`, `working_capital_ratio`,
   `working_capital_to_total_assets`, `effective_tax_rate`,
   `payables_turnover`, `days_payables_outstanding` (Bölüm 8.1/8.3/8.4).
   `quick_ratio` ve `financial_leverage_multiplier`
   **mevcut higher/lower yaklaşımında kalır** (DEĞİŞMEDİ). Payables
   oranlarında AŞIRI DÜŞÜK veya AŞIRI YÜKSEK değerlerin İKİSİNİN DE
   riskli olabileceği artık AÇIKÇA, iki taraflı bantlarla modellenmiştir
   (Bölüm 8.4).
4. **Şirket ölçeği.** Migration YAZILMAZ; `net_sales`/`total_assets`
   üzerinden migration'sız mali büyüklük proxy'si KABUL EDİLDİ (Yol A,
   Bölüm 12). `reliability` HİÇBİR ZAMAN `"high"` olamaz; çalışan
   sayısının eksik olduğu çıktıda AÇIKÇA belirtilir; bu sınıflandırma
   resmi KOBİ sınıflandırması OLARAK SUNULMAZ.
5. **Ülke desteği.** Bu fazda TAMAMEN ERTELENDİ. `country_code` context
   alanı, `country_overrides`, country resolution logic, boş country
   iskelet kodu — HİÇBİRİ EKLENMEZ (YAGNI, Bölüm 13).
6. **Mimari.** Benchmark sistemi ayrı paket + ayrı registry + ayrı
   service olarak geliştirilir (Bölüm 4). AMA bu fazda ayrı/kalıcı bir
   Engine/`AnalysisType` OLMAYACAK — `AnalysisType.BENCHMARK_COMPARISON`
   eklenmeyecek, CHECK constraint migration'ı yazılmayacak,
   `BenchmarkEngineAdapter` oluşturulmayacak, `app/engines/registry.py`'ye
   kayıt yapılmayacak, DB'ye Benchmark `FinancialAnalysisResult`
   yazılmayacak, API/bulk upload akışına bağlanmayacak (Bölüm 18). Bu
   milestone'da Benchmark Engine saf ve bağımsız bir değerlendirme
   kütüphanesi/service olarak kalır — persistence ve gerçek akış
   bağlantısı AYRI bir milestone ve AYRI bir onayla yapılacak.
7. **Enflasyon ve büyüme oranları.** 4.3C'de reel büyüme veya TÜFE
   entegrasyonu YAZILMAZ. Nominal büyüme benchmark'ları registry'de
   kalır AMA: nominal olduğu AÇIKÇA işaretlenir
   (`inflation_adjusted=False`), `reliability_ceiling="medium_low"`
   olur (genel `"medium"` tavanından DAHA DÜŞÜK), gelecekteki Health/
   Credit Score hesaplarında enflasyon düzeltmesi YAPILMADAN
   KULLANILMAYACAKTIR (Bölüm 8.6, 15, 21).
8. **Cash Flow benchmark'ları.** Cash Flow Engine mevcut olmadığı için
   placeholder `BenchmarkMetadata` kayıtları OLUŞTURULMAZ. Cash Flow
   benchmark'ları Milestone 4.4 sonrasına bırakılır. Ölü kod veya sahte
   yapısal tamlık ÜRETİLMEZ (Bölüm 8.7).
9. **Statutory tax rate ve payables modeli.** `effective_tax_rate`
   benchmark'ında yasal oran TEK bir merkezi parametreden
   (`STATUTORY_CORPORATE_TAX_RATE_TR`) okunur; oran farklı dosyalarda
   sabit sayı olarak TEKRAR EDİLMEZ (Bölüm 6 madde 10, Bölüm 8.3).
   Payables turnover ve DPO için `RANGE_IS_BETTER` bantları netleştirildi
   ve test sınırları (her bandın İKİ ucu) Adım 5'te açıkça belirtilecek
   (Bölüm 8.4, 19).

**Kalan açık nokta yok** — 9 kararın tamamı bağlayıcı ve bu revizyonla
tasarıma işlendi. İmplementasyon Bölüm 23'teki plana göre başlar.

## 23. Milestone implementasyon planı (2. tur onayla REVİZE EDİLDİ)

4.3B'nin kanıtlanmış "her adım 100% yeşil testle kapanmadan bir sonrakine
geçilmez" disipliniyle, kullanıcının bağlayıcı 8 adımlık revize planı:

| Adım | İçerik | Migration/Adapter/API? |
|---|---|---|
| 1 | `benchmark_types.py` — dataclass'lar, enum'lar, kapalı `threshold_bands` stratejisi, `register_benchmark`/`evaluate_benchmark`, ortak reliability yardımcı fonksiyonu (`_worse_reliability`'nin `app/engines/common/reliability.py`'ye taşınması, ratio VE benchmark motorlarının paylaşması için) + testler | Hayır |
| 2 | `company_size_classifier.py` — migration'sız mali büyüklük proxy'si + testler | Hayır |
| 3 | Likidite ve borçluluk benchmark registry kayıtları (6+9=15) + testler | Hayır |
| 4 | Kârlılık benchmark kayıtları (11) — merkezi `STATUTORY_CORPORATE_TAX_RATE_TR` modeli dahil + testler | Hayır |
| 5 | Faaliyet benchmark kayıtları (10) — `payables_turnover`/`days_payables_outstanding` `RANGE_IS_BETTER` + testler | Hayır |
| 6 | Verimlilik (6) + nominal büyüme (6) benchmark kayıtları — `inflation_adjusted=False`, `reliability_ceiling="medium_low"` (büyüme) + testler | Hayır |
| 7 | `app/engines/benchmarks/service.py::evaluate_benchmarks()` — gerçek financial ratio `result_json` girdisi üzerinde uçtan uca test | Hayır |
| 8 | Tam regresyon + performans ölçümü (gerçek, Bölüm 20'deki tahminin yerini alır) + `tests/README.md` güncellemesi + dürüst final rapor | Hayır |

**Bu milestone'da (8 adımın HİÇBİRİNDE) YAZILMAYACAKLAR:** hiçbir
migration, `AnalysisType.BENCHMARK_COMPARISON` eklemesi, `adapter.py`,
`app/engines/registry.py`'ye kayıt, API endpoint'i, bulk upload
bağlantısı, Health Score, Credit Score, Recommendation Engine kodu
(Bölüm 22 karar #6).

Her adımda: bir önceki adımın testleri %100 yeşil olmadan sıradaki adıma
geçilmez; adımlar birleştirilmez/kapsamı genişletilmez (4.3B'nin bağlayıcı
kararı #6'nın aynısı). Commit/push YAPILMAZ.

---

## Kapsam dışı özet (tekrar, netlik için — 2. tur onayla teyit edildi)

Health Score hesaplaması, Credit Score hesaplaması, Recommendation
Engine, gerçek percentile/peer veri kümesi, `Company.country`/şirket
ölçeği için migration, `cash_flow` kategorisi benchmark'ları (placeholder
dahil), enflasyon düzeltmeli büyüme varyantı, `AnalysisType`
eklemesi/CHECK constraint migration'ı, `BenchmarkEngineAdapter`,
`app/engines/registry.py` kaydı, API endpoint'i, bulk upload/
trial_balance değişikliği, country desteği (herhangi bir iskelet dahil)
— bunların HİÇBİRİ bu milestone'u KAPSAMAZ.

## Onay durumu

**ONAYLANDI (2. tur, 9 bağlayıcı karar ile).** Bölüm 22'deki 9 karar
kullanıcı tarafından bağlayıcı olarak verildi ve bu revizyonla Bölüm
4/5/6/8/11/12/13/15/18/21/22/23'e işlendi. İmplementasyon Bölüm 23'teki
8 adımlık plana göre başlamıştır — her adımda 100% yeşil test şartı,
migration/adapter/API/Health-Credit-Score yasağı, commit/push yasağı
AYNEN geçerlidir.
