# FINOS Milestone 4.6 — Multi-Period Trend Engine Design

**Türkçe adı:** Çok Dönemli Eğilim Analizi Motoru

**Doküman durumu:** FINAL TASARIM ADAYI — implementasyon ayrı kullanıcı onayına tabidir

**Tasarım sürümü:** 1.0.0

**Bağlayıcı üst referans:** `FINOS_ARCHITECTURE_BOOK.md` v1.6.0

**Mevcut migration tabanı:** `d7e9a4c6f205`

**Kapsam:** Tek tenant, tek şirket/kanuni tüzel kişilik, tek para birimi, nominal çok-dönem analizi
**Kod adı politikası:** “FINOS” yalnız dahili geliştirme kod adıdır; hiçbir runtime sembolüne, tabloya, API alanına veya kullanıcı metnine taşınmaz.

---

## 0. Bağlayıcı karar özeti

Bu doküman aşağıdaki kararları kapatır:

1. Milestone 4.6, mevcut iki dönemli yatay analizleri veya büyüme oranlarını değiştirmez; ayrı bir N-dönem motorudur.
2. V1 yalnız tek `tenant_id`, tek `company_id` (aynı zamanda kanuni tüzel kişilik sınırı) ve tek `currency_code` içindeki nominal serileri işler.
3. Konsolidasyon, grup şirketleri, eliminasyon, azınlık payı ve kur çevrimi Milestone 4.7 kapsamındadır.
4. İki gözlem pairwise değişim için yeterlidir; gerçek trend için en az 3, volatilite için 4, kırılma için 5 kullanılabilir gözlem gerekir.
5. Trend sahibi ve tek payload sahibi `FinancialAnalysisResult` olur; `AnalysisType.MULTI_PERIOD_TREND` additive olarak eklenir.
6. Son kronolojik dönem anchor period’dur. Caller sırası semantik değildir; resolver kanonik sırayı üretir.
7. Kaynak seçimi açık sonuç kimlikleriyle yapılır; “en son”, “en iyi” veya sessiz fallback yoktur.
8. Mevcut Cash Flow iki-dönem lineage tablosu yeniden kullanılmaz. Ayrı, immutable N-dönem `trend_analysis_lineage` tasarlanır.
9. Eski V3 Orchestrator, Application-v2 ve Persistence-v3 sözleşmeleri dondurulur. Trend için ayrı V4/Application-v3/Persistence-v4 aileleri kullanılır.
10. Trend sonucu Ratio, Benchmark, Health Score, Credit Score veya Recommendation hesabına geri beslenmez.
11. Executive Report entegrasyonu yalnız yeni, versioned 1.2.0 presentation projection’dır; presentation katmanı hesap yapmaz.
12. Nominal/reel ayrımı açıkça gösterilir; enflasyon düzeltmesi ve reel büyüme v1 dışında kalır.
13. Event sourcing, tahmin/forecast, AI yorumu, pozitif source cache, distributed lock ve background execution yoktur.
14. Açık blocking karar sayısı 0’dır. Bu tasarımın onayı implementasyon izni sayılmaz.

---

## 1. Amaç ve sorumluluk sınırı

Multi-Period Trend Engine’in amacı, authoritative storage’dan doğrulanan ardışık finansal sonuçları aynı metrik tanımı altında bir seri haline getirmek; gözlemleri, dönemler arası geçişleri ve uygun olduğu yerde seri düzeyi özetleri deterministik olarak üretmektir.

Motor:

- Balance Sheet, Income Statement, Cash Flow ve Financial Ratio sonuçlarındaki mevcut kanonik değerleri okur;
- kaynak engine değerini yeniden hesaplamaz veya düzeltmez;
- mutlak değişim, kontrollü yüzde değişim, yön, uygun CAGR, istikrar, volatilite ve kırılma sinyali üretir;
- her değerin source result, digest, version, dönem ve evidence bağını korur;
- eksikliği sıfır saymaz;
- “iyileşme/kötüleşme” yargısını yalnız negatif kâr/zarar tabanının kapalı semantiğinde üretir; diğer yönleri olgusal olarak `UPWARD/DOWNWARD/STABLE/...` biçiminde taşır.

Motor asla:

- muhasebe kaydı, konsolidasyon veya eliminasyon yapmaz;
- BS/IS/Cash Flow/Ratio formülünü kopyalamaz;
- score ağırlığı, benchmark bandı veya recommendation kuralı değiştirmez;
- reel/enflasyondan arındırılmış sonuç, forecast veya olasılık üretmez;
- caller tarafından verilen historical payload’a güvenmez;
- database, SQLAlchemy, FastAPI veya Pydantic import etmez.

---

## 2. Kapsam ve kapsam dışı

### 2.1 Kapsam

- Tek şirket/tüzel kişilikte 2–60 açıkça seçilmiş dönem.
- Yıllık, aylık discrete, çeyreklik discrete, çeyreklik cumulative, temporary-tax cumulative ve sınırlı custom-discrete cadence.
- BS stock, IS flow, Cash Flow flow/stock ve Ratio rate serileri.
- Nominal TRY değerleri; para birimi resolver tarafından birebir doğrulanır.
- Gözlem, transition, contiguous segment ve aggregate evidence.
- Restatement-aware source resolution ve açık one-off disclosure.
- Immutable N-dönem lineage ve terminal orchestration persistence.
- V4 Orchestrator, Application-v3, Persistence-v4 ve Report 1.2.0 additive entegrasyonu.

### 2.2 Kesin kapsam dışı

- 4.7 konsolidasyon perimeter’ı, intercompany eliminations, minority interest, acquisition/disposal perimeter changes, group currency translation ve consolidated restatement.
- Enflasyon endeksi, satın alma gücü düzeltmesi veya reel büyüme.
- Forecast, budget variance, sezon düzeltmesi, anomaly ML veya AI anlatımı.
- Trend-aware score, benchmark, recommendation veya kredi kararı.
- Caller payload’ından historical source kabulü.
- API/router/UI, queue/worker/scheduler/batch runner.
- Mevcut public 5.0A–5.0E veya 4.5 contract’larının değiştirilmesi.

---

## 3. Mevcut mimariyle değişmez sözleşmeler

| Alan | Değişmez kural |
|---|---|
| Balance Sheet / Income Statement | Mevcut `facts`, horizontal analysis ve engine version davranışı değişmez. |
| Ratio Engine | Mevcut 57 oran ve altı Cash Flow oranı; pairwise growth formülleri değişmez. |
| Cash Flow | İki dönemli comparability, evidence, reconciliation ve lineage sözleşmeleri değişmez. |
| V3 Orchestrator | 11 düğüm / 28 kenar ve bütün public V3 tipleri değişmez. |
| Application-v2 | Command/query/DTO/outcome sözleşmeleri değişmez. |
| Persistence-v3 | Cash Flow ownership/snapshot/lineage davranışı değişmez. |
| Report 1.0.0 / 1.1.0 | Legacy ve Cash Flow-aware çıktılar bitişik ancak değişmez kalır. |
| Security | 5.0E tenant/subject/authorization/audit sınırları aynen uygulanır; trend yeni bypass oluşturmaz. |

Yeni aileler:

- `analysis_orchestrator_v4` — orchestration contract `4.0.0`;
- `analysis_application_v3` — application contract `3.0.0`;
- `orchestration_persistence_v4` — persistence contract `4.0.0`;
- `multi_period_trend` — engine schema/model `1.0.0`;
- Executive Report trend projection — schema/model `1.2.0`.

Bu ayrım additive’dir. Legacy sınıflara yeni enum üyesi veya alan eklenmez; V4/V3/V4 kendi enum ve DTO’larını tanımlar.

---

## 4. Terimler, kapalı enum’lar ve temel invariant’lar

### 4.1 Kapalı enum’lar

```text
TrendPeriodFamily =
  ANNUAL | MONTHLY_DISCRETE | QUARTERLY_DISCRETE |
  QUARTERLY_CUMULATIVE_YOY | TEMPORARY_TAX_CUMULATIVE_YOY |
  CUSTOM_DISCRETE

TrendMeasurementBasis =
  STOCK_AS_OF | DISCRETE_FLOW | CUMULATIVE_FLOW | RATIO_RATE

TrendEvidenceKind = EXACT | DERIVED | ESTIMATED | UNAVAILABLE

TrendResultStatus =
  COMPLETE | PARTIAL | INSUFFICIENT_FOR_TREND |
  NON_COMPARABLE | INVALID_INPUT | INTEGRITY_FAILURE

TrendMetricStatus = COMPLETE | PARTIAL | UNAVAILABLE

TrendDirection =
  UPWARD | DOWNWARD | STABLE | MIXED | SIGN_CHANGE | UNAVAILABLE

TrendPercentageStatus =
  CALCULATED | ZERO_BASE | NEGATIVE_BASE_IMPROVING |
  NEGATIVE_BASE_WORSENING | NEGATIVE_BASE_NO_CHANGE |
  SIGN_CHANGE | NOT_ELIGIBLE | MISSING_VALUE

TrendVolatilityCategory = LOW | MEDIUM | HIGH | UNAVAILABLE

TrendBreakDirection = UPWARD | DOWNWARD | SIGN_CHANGE | UNAVAILABLE

TrendRestatementState = ORIGINAL | RESTATED | UNDECLARED_LEGACY

TrendRestatementReason =
  NONE | ERROR_CORRECTION | ACCOUNTING_POLICY_CHANGE |
  PRESENTATION_RECLASSIFICATION | SCOPE_CHANGE | LEGACY_UNDECLARED

TrendOneOffTreatment = INCLUDED_UNADJUSTED | NOT_IDENTIFIED

TrendCagrStatus =
  CALCULATED | DISABLED | INSUFFICIENT_DATA | NON_ANNUAL |
  GAP_PRESENT | NON_POSITIVE_ENDPOINT | SIGN_CHANGE |
  RESTATEMENT_BOUNDARY | NUMERIC_NON_CONVERGENCE

TrendSourceEngineCode =
  FS_BALANCE_SHEET | FS_INCOME_STATEMENT | CASH_FLOW | RATIO

TrendSourceRole =
  BALANCE_SHEET | INCOME_STATEMENT | CASH_FLOW | FINANCIAL_RATIOS

TrendUnit = TRY | PERCENT | RATIO | DAYS

TrendSignPolicy =
  NEUTRAL | SIGNED_PERFORMANCE | INVERSE_CONTEXT | CONTEXT_DEPENDENT
```

### 4.2 Temel invariant’lar

1. `tenant_id`, `company_id`, currency, accounting basis ve legal-entity sınırı bütün seride aynıdır.
2. Dönemler overlap edemez; aynı cadence içinde kanonik ve artan sıradadır.
3. Eksik metrik `None/UNAVAILABLE` olur; hiçbir yerde `0` varsayılmaz.
4. Bir observation, yalnız doğrulanmış `FinancialAnalysisResult` sahibi ve digest’i üzerinden doğar.
5. Bir transition yalnız aynı contiguous segment içindeki iki kullanılabilir observation arasında doğar.
6. Bir aggregate yalnız kendi minimum gözlem eşiğini ve gap/restatement koşullarını sağlayan segmentte doğar.
7. Evidence iyileştirilemez: transition/aggregate evidence, girdilerindeki en zayıf evidence’dır.
8. Aynı request, aynı source set, aynı registry/policy/version → bit-bit aynı sonuç ve digest.
9. Source ID, digest, payload, scope, status veya version uyuşmazlığı fail-closed’dur.
10. Caller sırası fingerprint’i değiştirmez; resolver kanonik sıralamadan fingerprint üretir.

---

## 5. Minimum veri ve period/cadence matrisi

### 5.1 Minimum eşikler

| Hesap | Minimum kullanılabilir gözlem | Ek koşul |
|---|---:|---|
| Pairwise absolute change | 2 | Aynı contiguous segment |
| Pairwise percentage semantic | 2 | Registry eligible ve taban semantiği uygun |
| Seri yönü | 3 | Metric-specific contiguous observations |
| İstikrar | 3 | Yön ile aynı seri |
| CAGR | 2 endpoint | Gapless annual series, pozitif endpoint’ler |
| Volatilite | 4 | En az 3 normalized transition |
| Trend break | 5 | Her breakpoint tarafında en az 2 transition |

İki dönem seçildiğinde sonuç `INSUFFICIENT_FOR_TREND` olur; pairwise transition korunur, direction/volatility/break üretilmez. Tek dönemli request `INVALID_INPUT` olur. V1 üst sınırı 60 dönemdir.

### 5.2 Cadence matrisi

| Family | Kabul edilen period metadata | Kanonik ardışıklık | Flow karşılaştırması | CAGR |
|---|---|---|---|---|
| `ANNUAL` | `YEAR_END`, `CUMULATIVE`, 12 ay, tam annual boundary | Ardışık mali yıllar | Yıllık flow | Uygun metric’te evet |
| `MONTHLY_DISCRETE` | `MONTHLY`, `DISCRETE`, 1 ay | Bitişi izleyen ay başlangıcı | Aylık flow | V1’de hayır |
| `QUARTERLY_DISCRETE` | `QUARTER`, `DISCRETE`, 3 ay | Ardışık mali çeyrek | Çeyreklik flow | V1’de hayır |
| `QUARTERLY_CUMULATIVE_YOY` | `QUARTER`, `CUMULATIVE`; aynı `period_number` ve `months_covered` | Ardışık mali yıllarda aynı çeyrek | Aynı YTD kapsamı | V1’de hayır |
| `TEMPORARY_TAX_CUMULATIVE_YOY` | `TEMPORARY_TAX`, `CUMULATIVE`; aynı `period_number`/ay | Ardışık mali yıllarda aynı geçici vergi dönemi | Aynı YTD kapsamı | V1’de hayır |
| `CUSTOM_DISCRETE` | `CUSTOM`, açık `DISCRETE`, eşit gün sayısı | Caller’ın explicit set’i; overlap yok, `previous.end+1=current.start` | Eşit süreli flow | Hayır |

Bağlayıcı kurallar:

- Discrete ve cumulative tek seride karışamaz.
- Cumulative Q1→Q2→Q3, dönem performansı trendi gibi sunulmaz. Cumulative karşılaştırma yalnız aynı ordinal yıl-yıla yapılır.
- Monthly/quarterly discrete seri, cumulative kaynakla doldurulmaz veya cumulative’dan fark alınarak yeniden üretilmez.
- `CUSTOM` cumulative, period metadata’sı eksik, çakışan veya eşit süreli olmayan seri `NON_COMPARABLE` olur.
- Aynı period family’de annual boundary uzunluğu, fiscal start/end pattern, accounting basis/policy ve `ifrs18_early_adopted` değeri değişirse segment kırılır; sessiz karşılaştırma yapılmaz.
- Stock metrikleri period end anını temsil eder; flow metrikleri cadence kapsamını temsil eder. Aynı source period içinde olsalar bile basis’leri birbirine dönüştürülmez.

### 5.3 Gap ve segment politikası

Resolver bütün period set’ini kanonik sıraya koyar ve cadence successor kuralıyla contiguous segment’lere ayırır. Period gap bütün metrikleri; bir metric’in eksik observation’ı yalnız o metric’i böler. Transition gap üzerinden kurulmaz. Aggregate her segment için ayrı üretilir; result’ın anchor summary’si yalnız anchor period’u içeren son segmenti kullanır. Önceki segmentler kaybolmaz.

---

## 6. Trend Metric Registry

### 6.1 Registry sözleşmesi

`TREND_METRIC_REGISTRY_VERSION = "trend-metric-registry/1.0.0"` kapalı ve import-zamanında doğrulanan registry’dir. Her `TrendMetricDefinition` en az şunları taşır:

```text
metric_code: str
source_engine_code: TrendSourceEngineCode
source_path: tuple[str, ...]
measurement_basis_by_period_family:
  tuple[tuple[TrendPeriodFamily, TrendMeasurementBasis], ...]
unit: TRY | PERCENT | RATIO | DAYS
monetary_scale: int | None
sign_policy: NEUTRAL | SIGNED_PERFORMANCE | INVERSE_CONTEXT | CONTEXT_DEPENDENT
eligible_period_families: tuple[TrendPeriodFamily, ...]
percentage_change_enabled: bool
cagr_enabled: bool
direction_enabled: bool
volatility_enabled: bool
break_enabled: bool
direction_tolerance: Decimal
volatility_low_max: Decimal
volatility_medium_max: Decimal
break_score_min: Decimal
expected_engine_schema_version: str | None
expected_engine_model_version: str
evidence_mapping: TrendEvidenceMapping
registry_version: str
```

Mutable mapping, duplicate metric code/path, unknown unit/basis, float threshold, unsorted family tuple ve unsupported source version registry construction’ında reddedilir.

### 6.2 Exact v1 source version manifesti

| Source | Schema | Model/engine |
|---|---|---|
| `FS_BALANCE_SHEET` | `None` | `1.0.0` |
| `FS_INCOME_STATEMENT` | `None` | `1.0.0` |
| `CASH_FLOW` | `1.0.0` | `1.0.0` |
| `RATIO` | `1.0` | `1.1.0` |

Unknown major/minor veya payload içi version ile owner version uyuşmazlığı `INTEGRITY_FAILURE` olur. Gelecek uyumluluk yalnız yeni registry sürümüyle açılır.

### 6.3 Threshold profilleri

| Profile | Basis/unit | Raw direction tolerance | Normalized direction tolerance | Volatility LOW/MEDIUM | Break minimum |
|---|---|---:|---:|---:|---:|
| `MONEY_STOCK_V1` | STOCK/TRY scale 2 | `0.01` TRY | `0.0001` | `0.0500` / `0.1500` | `0.1000` |
| `MONEY_FLOW_V1` | DISCRETE veya CUMULATIVE/TRY scale 2 | `0.01` TRY | `0.0001` | `0.0500` / `0.1500` | `0.1000` |
| `RATIO_LEVEL_V1` | RATIO/PERCENT | `0.0001` | `0.0001` | `0.0500` / `0.1500` | `0.1000` |
| `DAYS_LEVEL_V1` | DAYS | `0.01` gün | `0.0001` | `0.0500` / `0.1500` | `0.1000` |

Volatility ve break threshold’leri normalize edilmiş dimensionless transition’lara uygulanır. Her manifest satırı profile’ı compile ederek exact threshold değerlerini kendi immutable definition’ında taşır; runtime profile lookup yoktur.

`measurement_basis_by_period_family` exact mapping’i şöyledir: bütün BS ve Cash Flow opening/closing metric’leri her family’de `STOCK_AS_OF`; bütün Ratio metric’leri `RATIO_RATE`; IS ve diğer Cash Flow flow metric’leri `ANNUAL/MONTHLY_DISCRETE/QUARTERLY_DISCRETE/CUSTOM_DISCRETE` için `DISCRETE_FLOW`, `QUARTERLY_CUMULATIVE_YOY/TEMPORARY_TAX_CUMULATIVE_YOY` için `CUMULATIVE_FLOW` taşır. Böylece tek metric code farklı cadence’lerde basis anlamını kaybetmez. Her `TrendObservation.measurement_basis`, bu exact mapping’den çözülen tek enum değeridir.

### 6.4 Exact bounded metric manifesti

`A` bütün altı period family’yi; `Y` yalnız `ANNUAL`; `F` annual/monthly-discrete/quarterly-discrete/custom-discrete’i; `CY` annual/quarterly-cumulative-YOY/temporary-tax-cumulative-YOY’yi ifade eden doküman kısaltmalarıdır. Runtime’da kısaltma yoktur; compiled tuple exact enum üyelerini taşır.

| Metric code | Source path | Basis | Profile | Family | % | CAGR |
|---|---|---|---|---|---:|---:|
| `bs.current_assets` | `facts.current_assets` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.non_current_assets` | `facts.non_current_assets` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.total_assets` | `facts.total_assets` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.short_term_liabilities` | `facts.short_term_liabilities` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.long_term_liabilities` | `facts.long_term_liabilities` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.equity` | `facts.equity` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.total_liabilities_and_equity` | `facts.total_liabilities_and_equity` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.cash_and_equivalents` | `facts.cash_and_equivalents` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.inventory` | `facts.inventory` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.trade_receivables` | `facts.trade_receivables` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `bs.trade_payables` | `facts.trade_payables` | STOCK_AS_OF | MONEY_STOCK_V1 | A | Evet | Yıllık |
| `is.net_sales` | `facts.net_sales` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.cost_of_sales` | `facts.cost_of_sales` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.gross_profit` | `facts.gross_profit` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.operating_expenses` | `facts.operating_expenses` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.operating_profit` | `facts.operating_profit` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.depreciation_and_amortization` | `facts.depreciation_and_amortization` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.ebit` | `facts.ebit` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.ebitda` | `facts.ebitda` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.financing_expenses` | `facts.financing_expenses` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.profit_before_tax` | `facts.profit_before_tax` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `is.net_profit` | `facts.net_profit` | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `cf.opening_cash_and_cash_equivalents` | attribute | STOCK_AS_OF | MONEY_STOCK_V1 | F+CY | Evet | Yıllık |
| `cf.closing_cash_and_cash_equivalents` | attribute | STOCK_AS_OF | MONEY_STOCK_V1 | F+CY | Evet | Yıllık |
| `cf.operating_cash_flow` | attribute/line item | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `cf.investing_cash_flow` | attribute/line item | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `cf.financing_cash_flow` | attribute/line item | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `cf.calculated_net_cash_change` | attribute/line item | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `cf.free_cash_flow` | attribute/line item | DISCRETE/CUMULATIVE_FLOW | MONEY_FLOW_V1 | F+CY | Evet | Yıllık |
| `ratio.current_ratio` | `categories.liquidity.ratios.current_ratio.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.quick_ratio` | `categories.liquidity.ratios.quick_ratio.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.cash_ratio` | `categories.liquidity.ratios.cash_ratio.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.debt_ratio` | `categories.leverage.ratios.debt_ratio.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.debt_to_equity` | `categories.leverage.ratios.debt_to_equity.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.gross_profit_margin` | `categories.profitability.ratios.gross_profit_margin.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.operating_profit_margin` | `categories.profitability.ratios.operating_profit_margin.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.net_profit_margin` | `categories.profitability.ratios.net_profit_margin.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.return_on_assets` | `categories.profitability.ratios.return_on_assets.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.return_on_equity` | `categories.profitability.ratios.return_on_equity.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.asset_turnover` | `categories.activity.ratios.asset_turnover.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.cash_conversion_cycle` | `categories.activity.ratios.cash_conversion_cycle.value` | RATIO_RATE | DAYS_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.operating_cash_flow_margin` | `categories.cash_flow.ratios.operating_cash_flow_margin.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.free_cash_flow_margin` | `categories.cash_flow.ratios.free_cash_flow_margin.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.cash_flow_to_debt` | `categories.cash_flow.ratios.cash_flow_to_debt.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |
| `ratio.cash_interest_coverage` | `categories.cash_flow.ratios.cash_interest_coverage.value` | RATIO_RATE | RATIO_LEVEL_V1 | A | Hayır | Hayır |

Manifest **45 metric** içerir: 11 BS + 11 IS + 7 Cash Flow + 16 Ratio. Direction, volatility ve break 45 metric’in tamamında açıktır; minimum veri ve eligibility ayrıca uygulanır. Monetary metric’lerde sign policy `SIGNED_PERFORMANCE` yalnız `gross_profit`, `operating_profit`, `ebit`, `ebitda`, `profit_before_tax`, `net_profit`, `operating_cash_flow`, `investing_cash_flow`, `financing_cash_flow`, `calculated_net_cash_change`, `free_cash_flow` için kullanılır; diğerleri `NEUTRAL` veya registry’deki kapalı context policy’sidir. Bu policy score/favorability üretmez.

### 6.5 Evidence mapping

| Source | Mapping |
|---|---|
| BS/IS direct document + present fact | `EXACT` |
| BS/IS trial-balance derived + present fact | `DERIVED` |
| BS/IS missing fact veya failed source | `UNAVAILABLE` |
| Cash Flow | İlgili canonical line item’ın `evidence_kind` değeri; summary/line mismatch integrity failure |
| Ratio calculated | En iyi ihtimalle `DERIVED`; low reliability veya estimated Cash Flow dependency ise `ESTIMATED`; not-calculable ise `UNAVAILABLE` |

Ratio observation, upstream formülün sonucu olduğu için `EXACT` olarak yükseltilemez.

---

## 7. Authoritative N-period source resolution

### 7.1 Request ve port

```python
class TrendSourceResolutionRepositoryPort(Protocol):
    def load_resolution_snapshot(
        self, request: TrendPeriodResolutionRequest
    ) -> TrendResolutionSnapshot: ...

class TrendMultiPeriodInputResolver:
    def resolve(
        self, request: TrendPeriodResolutionRequest
    ) -> TrendInputResolutionOutcome: ...
```

`TrendPeriodResolutionRequest` alanları:

- `tenant_id: UUID`
- `company_id: UUID`
- `expected_anchor_period_id: UUID`
- `explicit_period_ids: tuple[UUID, ...]` (2–60, duplicate yok; input sırası semantik değil)
- `explicit_sources: tuple[TrendSourceSelection, ...]`
- `period_family: TrendPeriodFamily`
- `expected_currency: str` (v1 `TRY`)
- `expected_accounting_basis: str`
- `expected_accounting_policy_version: str`
- `expected_registry_version: str`
- `expected_trend_policy_version: str`
- `correlation_id: str`
- `resolved_at: UTC datetime`

`TrendSourceSelection` exact olarak `period_id`, `source_role`, `analysis_result_id` taşır. `source_role` yalnız `BALANCE_SHEET`, `INCOME_STATEMENT`, `CASH_FLOW`, `FINANCIAL_RATIOS` olabilir. Her `(period_id, source_role)` en fazla bir ID taşır. Eksik role otomatik source araması başlatmaz; ilgili metrikler `UNAVAILABLE` olur.

### 7.2 Explicit selection policy

1. Caller yalnız source kimliği niyetini taşır; payload taşıyamaz.
2. Repository her ID’yi `tenant_id + company_id + period_id + analysis_type` ile qualified sorgular.
3. Unknown ve cross-tenant/cross-company kaynak aynı safe `SOURCE_NOT_FOUND` sonucuna iner; existence probe yoktur.
4. Source `COMPLETED` olmalı, `result_json`/canonical digest bulunmalı ve digest yeniden hesaplandığında eşleşmelidir.
5. Owner engine version ile payload version ve registry version manifesti eşleşmelidir.
6. Seçilen source, aynı restatement zincirinde authoritative chain head olmalıdır. Superseded source `STALE_RESTATEMENT_SOURCE` ile reddedilir.
7. Aynı role için “latest completed”, engine version sıralaması veya UUID tie-break ile seçim yapılmaz.
8. Source payload cache’lenmez. Her execution’da PostgreSQL authoritative okunur.

### 7.3 Kanonik sıra ve proof

Resolver period’ları cadence-specific ordinal ile sıralar. Eşit ordinal, overlap, yanlış anchor veya belirsiz fiscal calendar fail-closed’dur. `candidate_set_digest` caller sırasından bağımsız olarak şu tuple’ın SHA-256 digest’idir:

```text
(tenant_id, company_id, period_family,
 ordered_period_descriptors,
 ordered(period_id, source_role, source_result_id, canonical_digest,
         source_schema_version, source_model_version,
         restatement_state, restatement_revision),
 registry_version, trend_policy_version)
```

Her segment için `comparability_proof_digest`; bütün çözüm için `resolution_digest` domain-separated canonical codec ile üretilir. UUID, date, UTC datetime, Decimal, Enum ve tuple tagged olarak kodlanır; map key’leri NFC `str`, sıralı ve unique’dir. Float kabul edilmez.

### 7.4 Concurrency ve stale-read koruması

Initial resolution saf engine çağrısından önce yapılır. Persistence öncesinde adapter:

1. `tenant_id + company_id` için transaction-scoped company lock alır;
2. bütün period/source/restatement satırlarını terminal transaction içinde yeniden sorgular;
3. scope, status, version, payload digest, chain head, candidate-set ve comparability proof’u yeniden hesaplar;
4. initial resolution ile byte-for-byte karşılaştırır;
5. fark varsa owner/lineage yazmadan `SOURCE_SET_CHANGED` conflict üretir.

Company lock için v1 uygulaması domain-separated `(tenant UUID, company UUID)` SHA-256’nın ilk signed 64-bit parçasıyla `pg_advisory_xact_lock` kullanır. Hash çakışması yalnız gereksiz serialization yaratabilir; yanlış scope birleştiremez. Lock release transaction sonundadır. Positive cache ve stale fallback yoktur.

---

## 8. Hesaplama sözleşmeleri

### 8.1 Decimal, canonicalization ve rounding

- İç hesapların tamamı finite `Decimal` kullanır; `float` yasaktır.
- Mevcut JSON numeric değeri yalnız `Decimal(str(value))` ile decode edilir; bool, non-finite ve locale-formatted string reddedilir.
- Monetary observation ve absolute change `0.01`; percentage, CAGR, normalized volatility ve break score `0.0001`; days `0.01` ölçeğinde `ROUND_HALF_EVEN` ile yalnız final boundary’de quantize edilir.
- Intermediate sonuçlar local Decimal context precision 50 ile hesaplanır; global Decimal context değiştirilmez.
- Signed zero final boundary’de canonical positive zero olur.

### 8.2 Pairwise absolute change

Kullanılabilir ardışık iki observation için:

```text
absolute_change = current_value - prior_value
```

Basis conversion yoktur. Stock, flow ve ratio aynı subtraction operatörünü kullanır fakat result basis alanını korur.

### 8.3 Percentage ve sign semantics

Registry `percentage_change_enabled=False` ise `NOT_ELIGIBLE`.

```text
prior > 0 and no sign change:
    percentage = (current - prior) / abs(prior) * 100
    status = CALCULATED

prior == 0:
    percentage = None
    status = ZERO_BASE

prior < 0 and current < 0:
    percentage = None
    current > prior  -> NEGATIVE_BASE_IMPROVING
    current < prior  -> NEGATIVE_BASE_WORSENING
    current == prior -> NEGATIVE_BASE_NO_CHANGE

prior/current farklı işaretli veya negatiften/pozitiften sıfıra geçiş:
    percentage = None
    status = SIGN_CHANGE
```

Absolute change her durumda kalır. Negatif base için matematiksel bir oran gösterilmez. `IMPROVING/WORSENING` yalnız `SIGNED_PERFORMANCE` metric’lerinde kâr/zarar veya nakit üretimi yönünü açıklar; borç/varlık metric’lerinde favorable judgement yoktur.

### 8.4 Direction ve stability

En az 3 kullanılabilir observation bulunan segmentte adjacent delta’lar metric tolerance’a göre sınıflanır:

1. Her observation değeri içinde hem negatif hem pozitif varsa `SIGN_CHANGE`.
2. Bütün `abs(delta) <= tolerance` ise `STABLE`.
3. Bütün delta’lar `>= -tolerance` ve en az biri `> tolerance` ise `UPWARD`.
4. Bütün delta’lar `<= tolerance` ve en az biri `< -tolerance` ise `DOWNWARD`.
5. Aksi halde `MIXED`.

`stability=True` yalnız `STABLE`; diğerleri false; eligibility yoksa `None` olur. Yön, olumlu/olumsuz finansal karar değildir.

### 8.5 CAGR

CAGR yalnız registry’de açık monetary metric, `ANNUAL` gapless segment ve pozitif first/last endpoint için hesaplanır:

```text
n = last_fiscal_year - first_fiscal_year  # pozitif tam sayı
CAGR = (nth_root(last / first, n) - 1) * 100
```

`nth_root`, precision 50 Decimal Newton iteration kullanır; initial guess `1`, maksimum 128 iteration, iki ardışık `0.000000000001` quantized sonuç eşit olduğunda durur. Yakınsamama `INTEGRITY_FAILURE` değil metric-level `UNAVAILABLE/CAGR_NUMERIC_NON_CONVERGENCE` olur ve warning üretir. Zero/negative endpoint, sign change, gap, restatement boundary, non-annual cadence veya disabled metric’te CAGR `None` olur; bunun nedeni kapalı `TrendCagrStatus` ile taşınır.

### 8.6 Volatilite

En az 4 kullanılabilir observation (`m = n-1 >= 3` transition) için:

```text
scale_unit = 0.01 (money/days) veya 0.0001 (ratio)
s_i = abs(x_i - x_(i-1)) / max(abs(x_i), abs(x_(i-1)), scale_unit)
mean_s = sum(s_i) / m
volatility = sqrt(sum((s_i - mean_s)^2) / m)
```

Square root precision 50 Decimal Newton iteration ile, final `0.0001` HALF_EVEN yapılır. Her iki endpoint sıfırsa `s_i=0`; negatif değer ve sign change formülü bozmaz. Sign change ayrıca direction/transition’da görünür. Category: `<=0.0500 LOW`, `>0.0500 ve <=0.1500 MEDIUM`, `>0.1500 HIGH`. Gap, unavailable observation veya blocking restatement aynı segmenti böler; segmentler üzerinden ortak volatilite üretilmez.

Bu ölçü büyüme büyüklüğünü değil, normalize edilmiş değişim hızının değişkenliğini ölçer; sabit yüksek büyüme düşük volatilite verebilir.

### 8.7 Trend break

En az 5 observation’lı contiguous segmentte signed normalized transition kullanılır:

```text
t_i = (x_i - x_(i-1)) / max(abs(x_i), abs(x_(i-1)), scale_unit)
```

Candidate split, her iki tarafta en az 2 transition bırakır. Her taraf “coherent” olmalıdır: tarafın bütün transition’ları `> 0.0001`, bütün transition’ları `< -0.0001` veya hepsi kapalı `[-0.0001, 0.0001]` tolerance bandında olmalıdır. Mixed taraf candidate değildir; tek-period spike kırılma sayılmaz.

```text
left_mean  = arithmetic_mean(left transitions)
right_mean = arithmetic_mean(right transitions)
break_score = abs(right_mean - left_mean)
```

`break_score >= 0.1000` ve tarafların coherent sınıfı/magnitude bandı farklıysa candidate kabul edilir. Birden fazla candidate’da en büyük score; eşitlikte en erken sağ-segment period ordinal’i seçilir. `breakpoint_period_id`, sağ segmentin ilk observation’ıdır. Değerlerin işareti breakpoint’te değişirse direction `SIGN_CHANGE`; aksi halde `right_mean > left_mean` için `UPWARD`, diğerinde `DOWNWARD` olur. Gap veya `ACCOUNTING_POLICY_CHANGE/PRESENTATION_RECLASSIFICATION/SCOPE_CHANGE/UNDECLARED_LEGACY` restatement boundary üzerinden break hesaplanmaz. Forecast veya nedensellik iddiası yoktur.

### 8.8 Nominal, restatement ve one-off

- Bütün monetary sonuçlar nominal TRY’dir. Result ve report projection `nominal_values=true`, `inflation_adjusted=false` disclosure taşır.
- `ERROR_CORRECTION`: explicit latest chain head kullanılır, warning üretilir; accounting policy aynıysa segment bölünmez.
- `ACCOUNTING_POLICY_CHANGE`, `PRESENTATION_RECLASSIFICATION`, `SCOPE_CHANGE`: boundary’den seri bölünür.
- `UNDECLARED_LEGACY`: pairwise absolute ve uygun percentage gösterilebilir; CAGR/volatility/break boundary üzerinden hesaplanmaz, evidence en fazla `ESTIMATED` olur ve overall result en fazla `PARTIAL`dır.
- V1 hiçbir one-off kalemi otomatik dışlamaz. Tanımlanmış adjustment registry bulunmadığı için bütün değerler `INCLUDED_UNADJUSTED` veya kaynakta işaret yoksa `NOT_IDENTIFIED` taşır. One-off olduğu bilinen ama tutarı/kapalı policy’si olmayan değer görünür kalır ve `ONE_OFF_INCLUDED_UNADJUSTED` warning’i üretir.

---

## 9. Framework-bağımsız engine contract’ları

Tüm contract’lar `@dataclass(frozen=True, repr=False)` olur; mutable list/dict kabul etmez. Enum’lar exact type ile doğrulanır; duck typing yoktur. `str/repr` raw payload, exception, company/tenant adı veya PII taşımaz.

### 9.1 `TrendObservation`

```python
@dataclass(frozen=True, repr=False)
class TrendObservation:
    ordinal: int
    period_id: UUID
    period_start: date
    period_end: date
    period_family: TrendPeriodFamily
    period_number: int
    coverage_kind: PeriodCoverageKind
    metric_code: str
    measurement_basis: TrendMeasurementBasis
    value: Decimal | None
    unit: TrendUnit
    evidence: TrendEvidenceKind
    source_analysis_result_id: UUID
    source_engine_code: TrendSourceEngineCode
    source_canonical_digest: str
    source_schema_version: str | None
    source_model_version: str
    restatement_state: TrendRestatementState
    restatement_revision: int
    one_off_treatment: TrendOneOffTreatment
    observation_digest: str
```

Invariant’lar:

- `ordinal >= 0`; period tarihleri geçerli; digest lowercase SHA-256’dır.
- `value is None` iff evidence `UNAVAILABLE`; non-null değer finite Decimal’dır.
- Metric code, source/path/basis/unit/version registry definition ile birebir eşleşir.
- Observation tuple’ı `(ordinal, metric_code)` kanonik sıralı ve unique’dir.
- `observation_digest`, yukarıdaki finansal alanların domain-separated canonical projection’ıdır; audit zamanı içermez.

### 9.2 Transition ve segment contract’ları

```python
@dataclass(frozen=True, repr=False)
class TrendTransition:
    metric_code: str
    from_period_id: UUID
    to_period_id: UUID
    absolute_change: Decimal
    percentage_change: Decimal | None
    percentage_status: TrendPercentageStatus
    pair_direction: TrendDirection
    evidence: TrendEvidenceKind
    transition_digest: str

@dataclass(frozen=True, repr=False)
class TrendSegmentSummary:
    segment_ordinal: int
    first_period_id: UUID
    last_period_id: UUID
    observation_count: int
    direction: TrendDirection
    stable: bool | None
    cagr_percent: Decimal | None
    cagr_status: TrendCagrStatus
    volatility: Decimal | None
    volatility_category: TrendVolatilityCategory
    break_detected: bool | None
    breakpoint_period_id: UUID | None
    break_direction: TrendBreakDirection
    break_score: Decimal | None
    evidence: TrendEvidenceKind
    summary_digest: str
```

Transition farklı segmentleri bağlayamaz. Break alanları exact all-null/false veya exact complete set invariant’ına uyar.

### 9.3 Metric ve result contract’ları

```python
@dataclass(frozen=True, repr=False)
class TrendMetricResult:
    metric_code: str
    status: TrendMetricStatus
    measurement_basis: TrendMeasurementBasis
    unit: TrendUnit
    observations: tuple[TrendObservation, ...]
    transitions: tuple[TrendTransition, ...]
    segments: tuple[TrendSegmentSummary, ...]
    missing_period_ids: tuple[UUID, ...]
    warnings: tuple[TrendIssue, ...]
    evidence: TrendEvidenceKind
    metric_digest: str

@dataclass(frozen=True, repr=False)
class TrendAnalysisResult:
    status: TrendResultStatus
    tenant_id: UUID
    company_id: UUID
    anchor_period_id: UUID
    period_family: TrendPeriodFamily
    ordered_period_ids: tuple[UUID, ...]
    period_descriptors: tuple[TrendPeriodDescriptor, ...]
    metric_results: tuple[TrendMetricResult, ...]  # exact 45 registry order
    completeness: TrendCompleteness
    evidence: TrendEvidenceSummary
    warnings: tuple[TrendIssue, ...]
    nominal_values: bool
    inflation_adjusted: bool
    currency_code: str
    candidate_set_digest: str
    resolution_digest: str
    registry_version: str
    trend_policy_version: str
    trend_schema_version: str
    trend_model_version: str
    result_digest: str
```

`metric_results` exact registry sırasındadır; eksik source nedeniyle metric satırı silinmez, `UNAVAILABLE` taşır. `nominal_values=True`, `inflation_adjusted=False`, currency `TRY`, schema/model `1.0.0` v1’de sabittir.

### 9.4 Outcome ve failure

```python
@dataclass(frozen=True, repr=False)
class TrendEngineOutcome:
    success: bool
    value: TrendAnalysisResult | None
    error: TrendEngineFailure | None
```

- `success=True` → value zorunlu, error `None`; result status yalnız `COMPLETE/PARTIAL/INSUFFICIENT_FOR_TREND/NON_COMPARABLE`.
- `success=False` → value `None`, error zorunlu; failure status yalnız `INVALID_INPUT/INTEGRITY_FAILURE`.
- Beklenen veri yetersizliği exception değildir.
- Programmer invariant breach dışındaki raw exception public boundary’ye çıkmaz.

### 9.5 Error ve warning taxonomy

Kapalı fatal code’lar:

```text
INVALID_REQUEST, INVALID_PERIOD_SET, SOURCE_NOT_FOUND,
SOURCE_SCOPE_MISMATCH, SOURCE_STATUS_INVALID, SOURCE_VERSION_UNSUPPORTED,
SOURCE_DIGEST_MISMATCH, SOURCE_SET_CHANGED, STALE_RESTATEMENT_SOURCE,
PERIOD_METADATA_INTEGRITY_FAILURE, REGISTRY_INTEGRITY_FAILURE,
RESOLUTION_UNAVAILABLE, PERSISTENCE_CONFLICT, PERSISTENCE_INTEGRITY_FAILURE
```

Kapalı warning code’lar:

```text
MINIMUM_TREND_DATA_INCOMPLETE, PERIOD_GAP_SEGMENTED,
METRIC_OBSERVATION_UNAVAILABLE, PERCENTAGE_ZERO_BASE,
NEGATIVE_BASE_SEMANTIC_ONLY, SIGN_CHANGE_PERCENTAGE_SUPPRESSED,
CAGR_NOT_ELIGIBLE, CAGR_NUMERIC_NON_CONVERGENCE,
VOLATILITY_NOT_ELIGIBLE, BREAK_NOT_ELIGIBLE,
RESTATEMENT_ERROR_CORRECTION_USED, RESTATEMENT_BOUNDARY_SEGMENTED,
LEGACY_RESTATEMENT_STATUS_UNDECLARED, ONE_OFF_INCLUDED_UNADJUSTED,
NOMINAL_NOT_INFLATION_ADJUSTED, SOURCE_EVIDENCE_ESTIMATED
```

Message’lar safe, sabit template’tir. Raw SQL, DSN, payload, filename, exception message veya stack trace taşımaz.

---

## 10. Status, completeness, evidence ve data quality

### 10.1 Overall status kararı

| Koşul | Status |
|---|---|
| Malformed request/unsupported enum/version | `INVALID_INPUT` failure |
| Digest/scope/storage/registry invariant breach | `INTEGRITY_FAILURE` failure |
| Period set geçerli fakat temel cadence karşılaştırılamıyor | `NON_COMPARABLE` result |
| Anchor segmentte hiçbir metric için 3 kullanılabilir observation yok; en az bir pairwise var | `INSUFFICIENT_FOR_TREND` |
| Bütün 45 metric exact expected observation set’i ve eligibility çıktılarıyla mevcut | `COMPLETE` |
| En az bir trend metric üretildi, fakat missing/estimated/gap/restatement/unavailable var | `PARTIAL` |

`COMPLETE`, bütün metric değerlerinin non-null olmasını gerçek veri üzerinde çoğu zaman gerektirdiği için güçlü bir statüdür; `PARTIAL` production başarısızlığı değildir.

### 10.2 `TrendCompleteness`

Exact alanlar:

- `expected_period_count`, `resolved_period_count`;
- `expected_metric_observation_count = period_count * 45`;
- `available_observation_count`, `unavailable_observation_count`;
- `exact_count`, `derived_count`, `estimated_count`, `unavailable_count`;
- `eligible_transition_count`, `calculated_transition_count`;
- `eligible_cagr_count`, `calculated_cagr_count`;
- `eligible_volatility_count`, `calculated_volatility_count`;
- `eligible_break_count`, `calculated_break_count`;
- `gap_count`, `restatement_boundary_count`;
- `available_ratio: Decimal` (0–1, scale 4).

Counts payload’dan yeniden sayılır ve constructor’da doğrulanır. Confidence score yoktur.

### 10.3 Evidence propagation

Evidence rank: `EXACT > DERIVED > ESTIMATED > UNAVAILABLE`.

- Observation evidence source mapping’den gelir.
- Transition evidence iki observation’ın minimumudur.
- Segment aggregate evidence kullanılan observation ve transition’ların minimumudur.
- Metric evidence kullanılabilir segmentlerin minimumudur; hiçbiri yoksa `UNAVAILABLE`.
- Result evidence yalnız sayım özetidir; tek bir “genel güven puanı” üretmez.

### 10.4 Data-quality flag’leri

```text
MISSING_PERIOD, PERIOD_OVERLAP, CADENCE_MISMATCH,
DISCRETE_CUMULATIVE_MIX, CURRENCY_MISMATCH,
ACCOUNTING_BASIS_MISMATCH, ACCOUNTING_POLICY_BOUNDARY,
IFRS18_POLICY_BOUNDARY, SOURCE_MISSING, SOURCE_UNAVAILABLE,
SOURCE_DIGEST_INVALID, SOURCE_VERSION_INVALID,
RESTATEMENT_BOUNDARY, RESTATEMENT_UNKNOWN,
ONE_OFF_UNADJUSTED, METRIC_MISSING, ZERO_BASE,
NEGATIVE_BASE, SIGN_CHANGE, NOMINAL_ONLY
```

Flag tuple’ları declaration order’da canonical ve unique’dir.

---

## 11. Restatement metadata modeli

Restatement, `FinancialPeriod`’ın değil bir finansal sonucun özelliğidir. Bu nedenle mevcut period tablosuna semantik olarak yanlış revision alanı eklenmez. Additive `financial_analysis_result_revision_metadata` tablosu kullanılır.

### 11.1 Tablo

```text
financial_analysis_result_revision_metadata
  analysis_result_id UUID PK
  tenant_id UUID NOT NULL
  company_id UUID NOT NULL
  period_id UUID NOT NULL
  restatement_state VARCHAR(24) NOT NULL
  restatement_revision INTEGER NOT NULL
  restatement_reason VARCHAR(40) NOT NULL
  supersedes_analysis_result_id UUID NULL
  metadata_schema_version VARCHAR(16) NOT NULL = '1.0.0'
  created_at TIMESTAMPTZ NOT NULL
```

Constraint’ler:

- Owner `(analysis_result_id, company_id, period_id)` composite FK ile aynı scope’tadır.
- `(company_id, tenant_id)` company FK’si tenant bağını zorlar.
- `supersedes_analysis_result_id` aynı company/period scope’unda bir `FinancialAnalysisResult`’a composite FK’dır.
- `revision >= 0`.
- `ORIGINAL`: revision 0, supersedes null, reason exact `NONE`.
- `RESTATED`: revision > 0, supersedes dolu, reason legacy değildir.
- `UNDECLARED_LEGACY`: revision 0, supersedes null, reason `LEGACY_UNDECLARED`.
- Insert trigger superseded row’un aynı `analysis_type` olduğunu ve revision’ın tam `previous+1` olduğunu doğrular.
- UPDATE ve DELETE PostgreSQL trigger’larıyla reddedilir.
- Index: `(company_id, period_id, restatement_state, restatement_revision)` ve `supersedes_analysis_result_id`.

Yeni result write path metadata satırını owner ile aynı transaction’da zorunlu yazar. Legacy `FinancialAnalysisResult` satırları migration’da `UNDECLARED_LEGACY/0/LEGACY_UNDECLARED` ile backfill edilir. Bu backfill geçmişe “original” iddiası eklemez.

---

## 12. Persistence, payload ownership ve N-period lineage

### 12.1 Storage Ownership Matrix

| Veri | Tek sahibi | Diğer tabloların taşıdığı |
|---|---|---|
| Trend result payload | `financial_analysis_results.result_json` (`MULTI_PERIOD_TREND`) | Payload kopyası yok |
| Trend canonical digest | `financial_analysis_results.canonical_result_digest` | Lineage owner FK ile referans |
| Per-source N-period provenance | `trend_analysis_lineage` | Yalnız ID/digest/version/evidence/proof |
| Terminal execution/audit | Mevcut V4 orchestration persistence kayıtları | Trend payload yok; owner FK/ref |
| Restatement metadata | `financial_analysis_result_revision_metadata` | Result payload kopyası yok |

Event sourcing kullanılmaz. Immutable history domain state’i replay ederek kurmak için değil, denetim ve source ownership doğrulaması için tutulur.

### 12.2 `trend_analysis_lineage` modeli

```text
trend_analysis_lineage
  id UUID PK
  trend_analysis_result_id UUID NOT NULL
  tenant_id UUID NOT NULL
  company_id UUID NOT NULL
  anchor_period_id UUID NOT NULL
  ordinal INTEGER NOT NULL
  source_period_id UUID NOT NULL
  source_analysis_result_id UUID NOT NULL
  source_role VARCHAR(32) NOT NULL
  source_engine_code VARCHAR(40) NOT NULL
  source_analysis_type VARCHAR(40) NOT NULL
  source_canonical_digest CHAR(64) NOT NULL
  source_schema_version VARCHAR(32) NULL
  source_model_version VARCHAR(32) NOT NULL
  observation_evidence VARCHAR(16) NOT NULL
  comparability_proof_digest CHAR(64) NOT NULL
  source_set_digest CHAR(64) NOT NULL
  lineage_schema_version VARCHAR(16) NOT NULL = '1.0.0'
  created_at TIMESTAMPTZ NOT NULL
```

### 12.3 FK, unique, check ve index’ler

- Owner FK: `(trend_analysis_result_id, company_id, anchor_period_id)` → `financial_analysis_results(id, company_id, period_id)`, `RESTRICT`.
- Source FK: `(source_analysis_result_id, company_id, source_period_id)` → aynı result composite key, `RESTRICT`.
- Tenant FK: `(company_id, tenant_id)` → `companies(id, tenant_id)`, `RESTRICT`.
- Period FKs: `(anchor_period_id, company_id)` ve `(source_period_id, company_id)` → `financial_periods`, `RESTRICT`.
- Unique `(trend_analysis_result_id, ordinal, source_role)`.
- Unique `(trend_analysis_result_id, source_period_id, source_role)`.
- Unique `(trend_analysis_result_id, source_analysis_result_id)`.
- Check `ordinal >= 0`; role exact dört değer; evidence exact dört değer; lineage version `1.0.0`; digest’ler lowercase SHA-256.
- Index `source_analysis_result_id`; `(company_id, anchor_period_id)`; `(trend_analysis_result_id, ordinal)`.
- PostgreSQL UPDATE ve DELETE trigger’ları bütün lineage satırlarını immutable yapar.

Repository bütün ordinal’lerin 0’dan gapless başladığını, aynı period’un bütün role satırlarında aynı ordinal’i kullandığını, son ordinal period’un anchor olduğunu ve source set’in resolution proof ile birebir eşleştiğini owner insert’inden önce doğrular. Terminal transaction bu seti tek seferde yazar.

### 12.4 Atomik transaction

Tek transaction aşağıdakileri atomik yapar:

1. company-scoped advisory lock;
2. terminal source re-query/proof verification;
3. V4 run/idempotency recheck;
4. staged `FinancialAnalysisResult` trend owner;
5. owner revision metadata;
6. bütün trend lineage satırları;
7. engine execution/owner reference ve terminal run kayıtları;
8. canonical digest ve scope doğrulaması;
9. commit.

Owner, lineage veya terminal run’ın biri başarısızsa hepsi rollback olur.

Concurrent idempotent yarışta owner/lineage staging bir SAVEPOINT içinde yapılır. `persist_terminal_run_v4()` mevcut canonical run için erken idempotent dönüş yaparsa loser `ROLLBACK TO SAVEPOINT` ile kendi staged owner, revision metadata ve lineage satırlarını discard eder; bunlar outer transaction commit’inde kalıcılaşamaz. Dönen canonical owner’ın source set/digest/scope’u yeniden doğrulanmadan success verilmez.

### 12.5 Idempotency ve reuse

Fingerprint şunları içerir:

- normalized V4 request ve requested outputs;
- tenant/company/anchor/period family;
- ordered period descriptors;
- ordered source IDs, roles, canonical digests, schema/model versions;
- restatement metadata;
- candidate set, resolution ve comparability proof digest’leri;
- 45-metric registry digest’i;
- trend policy/codec/schema/model versions;
- V4 graph/plan/contract versions.

Kurallar:

- Same run ID + same scope + same fingerprint/source set → exact idempotent success/reuse.
- Same run ID + different source set, company, tenant, anchor, cadence veya fingerprint → fail-closed conflict.
- Missing/corrupt lineage, unknown cross-major snapshot veya source digest change → reuse reddi; clean-start fallback yoktur.
- Source set değişikliği yeni run/fingerprint gerektirir.

---

## 13. Alembic migration tasarımı

Milestone 4.6G’de tek additive revision oluşturulur; `down_revision = "d7e9a4c6f205"`. Revision ID implementasyon anında Alembic tarafından üretilecek; bu doküman sahte ID tanımlamaz. Migration sonunda tek head olmalıdır.

Upgrade sırası:

1. `AnalysisType` check constraint’ine `multi_period_trend` additive değeri ekle.
2. `financial_analysis_result_revision_metadata` tablo/constraint/index’lerini oluştur.
3. Mevcut `FinancialAnalysisResult` satırlarını `UNDECLARED_LEGACY` ile backfill et; count ve scope doğrula.
4. Metadata insert-chain validation ve UPDATE/DELETE immutability trigger/function’larını oluştur.
5. `trend_analysis_lineage` tablo/constraint/index’lerini oluştur.
6. Lineage UPDATE/DELETE immutability trigger/function’larını oluştur.
7. Constraint catalog ve single-head doğrulaması yap.

Downgrade fail-safe:

- Herhangi bir `MULTI_PERIOD_TREND` owner, trend lineage, `RESTATED` metadata veya revision `>0` varsa downgrade açık exception ile durur; veri silmez.
- Yalnız migration backfill’i olan `UNDECLARED_LEGACY/0` satırlar varsa bunlar doğrulandıktan sonra trigger/table’lar kaldırılabilir ve AnalysisType check önceki listeye döner.
- Downgrade içinde cascade veya data-coercion yoktur.
- Upgrade→downgrade→upgrade boş DB’de; dolu-data downgrade refusal PostgreSQL’de zorunlu testtir.

SQLite yalnız contract/unit testleri içindir. FK/check/trigger/concurrency/lock/idempotency davranışlarının kabul kaynağı gerçek PostgreSQL’dir.

---

## 14. V4 Orchestrator sözleşmesi

### 14.1 Graph

`OrchestrationEngineCodeV4`, V3’ün 11 exact üyesini yeni enum’da tekrar tanımlar ve yalnız `MULTI_PERIOD_TREND` üyesini ekler. V3 enum mutasyona uğramaz.

V4 graph exact shape:

- 12 node;
- 23 `all_of` edge;
- 2 `any_of` edge;
- 4 `optional` edge;
- toplam 29 edge.

V3’ten tek yeni edge, `EXECUTIVE_REPORT` için optional `MULTI_PERIOD_TREND` bağıdır. Trend node’un engine-graph upstream’i yoktur; trusted `TrendPreResolvedContextV1` Application-v3 tarafından sağlanır. Context yokken trend output istenirse request constructor reddeder. Ratio’ya trend edge’i yoktur.

### 14.2 Exact yeni V4 tipleri

```text
OrchestrationEngineCodeV4.MULTI_PERIOD_TREND
OrchestrationEngineInputsV4.trend_pre_resolved_context: TrendPreResolvedContextV1 | None
EngineResultEnvelopeV4.result_kind = "TrendAnalysisResult"
EngineResultEnvelopeV4.result = exact TrendAnalysisResult
PreviousExecutionSnapshotV4
OrchestrationRunRequestV4
OrchestrationRunResultV4
```

V4 registry version manifest, V3 source engine version’larını aynen taşır ve trend için `("1.0.0", "1.0.0")` ekler. Dispatch doğrudan callable reference’tır; dynamic import/string dispatch yoktur.

### 14.3 Resume/reuse

Resume yalnız V4 snapshot, graph/plan/contract `4.0.0`, aynı source set, aynı resolution/registry/policy digest ve aynı scope ile mümkündür. V3 snapshot V4’e, V4 snapshot V3’e duck-type edilmez. Invalid/corrupt source’ta clean-start fallback yasaktır.

---

## 15. Application-v3 sözleşmesi

Application-v3, Application-v2’nin additive major fork’udur; v2 class’larına alan eklemez.

### 15.1 Request intent

```python
@dataclass(frozen=True, repr=False)
class TrendSourceSelectionIntentDTOV3:
    period_id: UUID
    source_role: ApplicationTrendSourceRoleV3
    source_analysis_result_id: UUID

@dataclass(frozen=True, repr=False)
class TrendRequestDTOV3:
    expected_anchor_period_id: UUID
    period_ids: tuple[UUID, ...]
    source_selections: tuple[TrendSourceSelectionIntentDTOV3, ...]
    period_family: ApplicationTrendPeriodFamilyV3
    expected_currency: str
    expected_accounting_basis: str
    expected_accounting_policy_version: str
    expected_metric_registry_version: str
    expected_trend_policy_version: str
    trend_contract_version: str = "1.0.0"
```

Caller historical payload, digest, restatement revision, evidence veya lineage assembly taşımaz. Bunlar trusted adapter/repository tarafından çözülür.

### 15.2 Command ailesi

Public V3 command alanları tek tek aşağıdaki gibidir; “v2 ile aynı” şeklinde örtük alan yoktur. `ApplicationScopeDTO`, `ApplicationAuditContextDTO`, `AnalysisInputsDTO`, `AnalysisRunOptionsDTO`, `PriorPeriodProjectionDTO`, `CompanyMetadataDTO`, `DashboardRequestDTO` ve `RenderContractRequestDTO` değişmemiş 5.0C value contract’ları olarak import edilir; yeni alan eklenmez. Financial/Cash Flow/Report intent’leri V3 engine enum/version’larıyla `FinancialSourceIntentDTOV3`, `CashFlowRequestDTOV3` ve `ReportRequestDTOV3` olarak exact tanımlanır.

```python
@dataclass(frozen=True, repr=False)
class StartAnalysisCommandV3:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV3, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV3, ...]
    cash_flow_request: CashFlowRequestDTOV3 | None
    trend_request: TrendRequestDTOV3 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTOV3 | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "3.0.0"

@dataclass(frozen=True, repr=False)
class ResumeAnalysisCommandV3:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV3, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV3, ...]
    cash_flow_request: CashFlowRequestDTOV3 | None
    trend_request: TrendRequestDTOV3 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTOV3 | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "3.0.0"

@dataclass(frozen=True, repr=False)
class RetryAnalysisCommandV3:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV3, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV3, ...]
    cash_flow_request: CashFlowRequestDTOV3 | None
    trend_request: TrendRequestDTOV3 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTOV3 | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "3.0.0"

@dataclass(frozen=True, repr=False)
class CancelAnalysisCommandV3:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = "3.0.0"
```

Requested output’ta `MULTI_PERIOD_TREND` bulunması ile `trend_request` varlığı exact iff’dir. Scope `financial_period_id` anchor ile eşleşir. Resume/Retry’de `scope.previous_run_id` zorunlu ve `run_id`’den farklıdır; `scope.original_operation` mevcut frozen semantics’e uyar. Invalid resume/retry source’ta clean-start fallback yoktur.

Query alanları da exact tanımlıdır:

```python
@dataclass(frozen=True, repr=False)
class GetAnalysisStatusQueryV3:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = "3.0.0"

@dataclass(frozen=True, repr=False)
class GetAnalysisResultQueryV3:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    include_payloads: bool
    application_contract_version: str = "3.0.0"

@dataclass(frozen=True, repr=False)
class GetExecutionDetailQueryV3:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    engine_code: ApplicationEngineCodeV3
    include_payload: bool
    application_contract_version: str = "3.0.0"

@dataclass(frozen=True, repr=False)
class ListAnalysisHistoryQueryV3:
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    cursor: str | None
    limit: int
    application_contract_version: str = "3.0.0"
```

V2 query/command class’ları değişmez ve V3 request kabul etmez.

### 15.3 Phased use-case akışı

1. Command validation ve ApplicationScope/RunScopeClaim preflight.
2. Pre-execution authorization ve required security audit.
3. Trend source intent’in scope-qualified authoritative resolution’ı.
4. Gerekirse V4 resume snapshot ve exact source proof yükleme.
5. V4 orchestration çağrısı.
6. Pre-persistence authorization revalidation.
7. Company lock altında source set terminal re-query.
8. Gerçek V4 `EngineResultEnvelopeV4.result` içinden trend owner/lineage binding assembly.
9. Persistence-v4 terminal transaction.
10. Persisted scope/idempotency/source set post-check.
11. Application DTO projection ve post-commit audit.

Authorization revoke olursa execution maliyeti geri alınamaz fakat persistence yapılmaz ve raw trend payload caller’a verilmez. Post-commit audit failure canonical run’ı rollback etmez; mevcut zorunlu warning davranışı korunur. DTO projection failure sonrası persisted run geri alınmaz; recovery query ile okunabilir.

### 15.4 Application DTO projection

Yeni exact DTO’lar:

- `ApplicationTrendObservationDTOV3`
- `ApplicationTrendTransitionDTOV3`
- `ApplicationTrendSegmentSummaryDTOV3`
- `ApplicationTrendMetricResultDTOV3`
- `ApplicationTrendCompletenessDTOV3`
- `ApplicationTrendResultDTOV3`
- `ApplicationTrendIssueDTOV3`

Engine dataclass’ı dışarı doğrudan açılmaz. Decimal typed kalır; JSON serialization gelecekteki API adapter sorumluluğudur. Application DTO schema version `3.0.0`, storage serializer version’dan ayrıdır.

---

## 16. Persistence-v4 sözleşmesi

Persistence-v4, V3 owner/snapshot davranışını kopyalamadan additive olarak genişletir; V3 public class’larını değiştirmez.

```python
@dataclass(frozen=True, repr=False)
class TrendLineageBindingV4:
    ordinal: int
    source_period_id: UUID
    source_analysis_result_id: UUID
    source_role: TrendLineageSourceRoleV4
    source_engine_code: OrchestrationEngineCodeV4
    source_analysis_type: AnalysisType
    source_canonical_digest: str
    source_schema_version: str | None
    source_model_version: str
    observation_evidence: TrendEvidenceKind
    comparability_proof_digest: str
    source_set_digest: str

@dataclass(frozen=True, repr=False)
class CreateTrendFinancialResultOwnerV4:
    analysis_type: Literal[AnalysisType.MULTI_PERIOD_TREND]
    source_mode: Literal[SourceMode.MULTI_SOURCE_DERIVED]
    document_id: None
    anchor_period_id: UUID
    engine_version: str
    started_at: datetime
    completed_at: datetime
    revision_metadata: FinancialResultRevisionBindingV4
    trend_lineage: tuple[TrendLineageBindingV4, ...]

@dataclass(frozen=True, repr=False)
class PersistTerminalRunCommandV4:
    scope: PersistenceRunScopeV4
    run_result: OrchestrationRunResultV4
    requested_outputs: tuple[OrchestrationEngineCodeV4, ...]
    resume_context: ResumePersistenceContextV4 | None
    financial_owner_bindings: tuple[FinancialResultOwnerBindingV4, ...]
    telemetry: ExecutionTelemetryV4 | None
    persistence_contract_version: str = "4.0.0"
```

Trend owner yalnız `MULTI_SOURCE_DERIVED`, `document_id=None` olabilir; aynı-period `financial_analysis_result_sources` payload/lineage kopyası taşımaz. `FinancialAnalysisResult`’ın canonical digest’i codec ile yeniden doğrulanır. Trend owner’da expected lineage, initial resolution, terminal re-query ve result içi source references dördü exact eşleşmelidir.

Snapshot V4, trend için owner FK, canonical digest, engine schema/model, input fingerprint, ordered source set, registry/policy ve lineage proof taşır. Load sırasında bütün source result’lar ve lineage satırları yeniden doğrulanır.

---

## 17. Executive Report 1.2.0 entegrasyonu

Legacy Report 1.0.0 ve Cash Flow-aware Report 1.1.0 değişmez. Yeni `ExecutiveReportTrendProjectionV1_2`:

- verified `TrendAnalysisResult` exact type/schema/model/digest kabul eder;
- mevcut `SEC_PERIOD_COMPARISON_ANALYSIS` bölümünü trend-aware projection ile doldurur; report registry’ye hesap motoru eklemez;
- anchor period, cadence, nominal disclosure, period gaps, restatement boundaries, evidence ve unavailable metric’leri gösterir;
- metric registry order’dan seçilmiş bounded sunum setini taşır;
- percentage/CAGR/volatility/break değerlerini yeniden hesaplamaz;
- score, benchmark veya recommendation metnini değiştirmez;
- source engine code ve result digest reference’larını korur;
- `report_schema_version = report_model_version = "1.2.0"` üretir.

Report presentation set’i exact olarak şu 12 metric’tir:

```text
bs.total_assets, bs.equity, bs.cash_and_equivalents,
is.net_sales, is.ebitda, is.net_profit,
cf.operating_cash_flow, cf.free_cash_flow,
ratio.current_ratio, ratio.debt_to_equity,
ratio.net_profit_margin, ratio.cash_flow_to_debt
```

Bir metric unavailable ise satır silinmez; reason/evidence gösterilir. “Nominal; enflasyondan arındırılmamıştır” disclosure zorunludur.

---

## 18. Security, authorization ve sensitive-data sınırı

- Application-v3 bütün write/read use-case’lerinde mevcut 5.0E trusted AuthenticationContext ve AuthorizationPort adapter’ını kullanır; yeni auth modeli yoktur.
- Trend source resolver sorguları tenant/company-qualified’dır. Cross-tenant kaynak aynı not-found/hiding davranışını verir.
- Trend write replay initiating subject, tenant, company, anchor period ve operation scope’u doğrular.
- Caller historical payload, canonical digest veya evidence veremez.
- Raw result payload security audit’e yazılmaz. Audit metadata yalnız run/correlation/action/safe code/digest reference taşır ve fingerprint’e dahil edilmez.
- Error/warning/`repr` raw SQL, DSN, UUID dışı PII, document content, token/claim veya upstream exception message taşımaz.
- No-op/fake authorization/audit production profile’da halen yasaktır.

---

## 19. Determinizm ve performance sınırları

### 19.1 Determinizm inventory’si

Fingerprint/result digest’e dahil:

- ordered source set ve source content digest’leri;
- period/cadence/restatement descriptors;
- registry, trend policy, codec, schema/model versions;
- V4 graph/plan/contract versions;
- requested metric/output set.

Dahil değil:

- wall-clock duration;
- DB row insertion timestamp;
- audit IP/user-agent hash’i;
- telemetry;
- post-commit audit sonucu.

### 19.2 Bounded execution

- Request 2–60 period ve exact 45 metric ile sınırlıdır.
- Engine karmaşıklığı `O(period_count * metric_count)`; break candidate taraması metric başına en fazla `O(period_count^2)` fakat 60-period hard bound ile kapalıdır.
- Engine thread/process açmaz; I/O yapmaz.
- Resolver tek bounded source query set’i ve terminal re-query kullanır; N+1 source fetch yasaktır.
- Unit benchmark kabul hedefi: 60 period × 45 metric saf engine p95 < 250 ms; PostgreSQL resolver+persistence p95 < 1 s (CI host varyansı için wall-clock hard assertion değil, ayrı performance profile).

---

## 20. Test stratejisi ve zorunlu kabul matrisi

### 20.1 Contract ve registry testleri

- Bütün enum exact member/value golden’ları.
- 45/45 metric manifest, 11+11+7+16 family count.
- Source path, basis, unit, profile, period eligibility, percentage/CAGR flag ve version manifest golden’ları.
- Duplicate/unsorted/float/unknown path/version registry construction negative testleri.
- Frozen dataclass, safe `str/repr`, Decimal/UUID/date/datetime canonical codec testleri.
- Same input → same bytes/digest property testleri.

### 20.2 Cadence ve resolution testleri

- Annual, monthly discrete, quarterly discrete, quarterly cumulative YoY, temporary-tax cumulative YoY ve custom discrete positive vectors.
- Discrete+cumulative mix, cumulative Q1→Q2 misuse, wrong ordinal, overlap, gap, unequal custom duration, fiscal boundary change.
- Input order permutations → same canonical order/fingerprint.
- Same tenant/company/currency/basis/policy positive; wrong tenant/company/currency/basis/policy fail-closed.
- Explicit source missing, duplicate role, ambiguous/superseded source, wrong analysis type/status/version.
- Corrupted canonical digest, payload/version mismatch, terminal source-set change.
- Company lock ve terminal re-query concurrency testleri.

### 20.3 Hesaplama golden/property testleri

- Pairwise positive, zero base, both negative improving/worsening/equal, positive↔negative ve zero sign transitions.
- Eksik value’ın sıfır sayılmaması.
- Direction: upward/downward/stable/mixed/sign-change literal vectors.
- CAGR: 2/3/10 yıllık positive vectors, zero/negative/sign/gap/non-annual rejection, Newton convergence golden.
- Volatility: all-zero, constant-level, constant-growth, negative, zero-crossing, sign-change ve threshold exact boundaries `0.0500/0.1500`.
- Break: minimum 5, coherent upward/downward/sign change, spike/noise rejection, equal-score earliest tie-break, threshold exact boundary.
- Decimal precision, signed-zero ve HALF_EVEN boundary vectors.
- Gap/metric missing/restatement segment property testleri.

### 20.4 Evidence/data-quality testleri

- BS/IS direct→EXACT, fallback→DERIVED, missing→UNAVAILABLE.
- Cash Flow exact/derived/estimated/unavailable line mapping ve summary mismatch integrity failure.
- Ratio calculated→DERIVED maximum, estimated upstream downgrade, not-calculable→UNAVAILABLE.
- Observation→transition→segment→metric worst-evidence propagation.
- Completeness count recomputation ve tam 45×N expected count.
- Legacy restatement evidence downgrade; policy/reclassification boundary; error-correction chain head.
- One-off no-auto-exclusion ve nominal disclosure.

### 20.5 PostgreSQL model/migration testleri

- PK/FK/scope/tenant/source/owner constraint negative insert’leri.
- Duplicate owner+ordinal+role, owner+period+role ve owner+source rejection.
- Invalid digest/evidence/role/version/ordinal rejection.
- Bütün yeni immutable tablolarda gerçek SQL UPDATE/DELETE rejection.
- Restatement revision chain/type/scope/revision-step negative tests.
- Owner + metadata + N lineage + terminal execution atomic rollback.
- Concurrent exact replay ve same-run/different-source conflict.
- Idempotent early-return SAVEPOINT loser owner/metadata/lineage discard testi.
- Missing/corrupt lineage resume/reuse fail-closed.
- Upgrade→downgrade→upgrade ve non-empty downgrade refusal.
- Single Alembic head.

### 20.6 Integration/regression testleri

- V4 12/23/2/4/29 graph golden; V3 11/23/2/3/28 regression.
- Trend requested iff trusted pre-resolved context.
- V4 result envelope exact `TrendAnalysisResult`; cross-major snapshot rejection.
- Application-v3 start/resume/retry/cancel/query outcomes; authorization revalidation; projection failure recovery.
- Persistence-v4 owner/lineage/source proof mapping.
- Report 1.2.0 exact 12 metric projection, unavailable/gap/evidence/nominal disclosure; Reports 1.0.0/1.1.0 golden unchanged.
- Ratio/Benchmark/Health/Credit/Recommendation outputs byte-equivalent with/without trend optional result.
- 5.0A–5.0E and Milestone 4.5 public contract/import regression.
- Transitive no FastAPI/Pydantic/SQLAlchemy import in trend engine/application contracts.

### 20.7 Production closure gate

- Hedefli unit/property testleri: 0 failed, 0 skipped.
- PostgreSQL integration/concurrency/migration testleri: 0 failed, 0 skipped.
- Tam Docker `tests/`: 0 failed, 0 skipped.
- `git diff --check`: temiz.
- Backend/PostgreSQL healthy; tek migration head.
- Migration/model/public contract/design sapması ayrı raporlanır.

---

## 21. Test-gated implementasyon sırası

Her aşama kendi hedefli kapısı tamamen yeşil olmadan sonraki aşamaya geçmez.

### 21.1 4.6A — Contracts and Trend Accounting Policy

- **Kapsam:** Enum’lar, observation/transition/segment/result/outcome, Decimal/rounding, status ve cadence policy.
- **Production dosyaları:** `app/engines/multi_period_trend/{types,contracts,errors,policy}.py`.
- **Migration/model:** Yok.
- **Public contract:** Legacy contract etkisi yok.
- **Testler:** Exact DTO/enums, invariant, safe repr, canonical types, policy matrix.
- **PostgreSQL/concurrency:** Yok.
- **Geçiş kriteri:** Hedefli contract/policy + mevcut engine contract regresyonları 0 failed/0 skipped; diff-check temiz.

### 21.2 4.6B — Trend Metric Registry and Evidence Mapping

- **Kapsam:** 45 metric, source version manifest, threshold profiles, evidence mapping.
- **Production dosyaları:** `registry.py`, `evidence.py`.
- **Migration/model:** Yok.
- **Public contract:** Yok.
- **Testler:** 45 golden satır/count/path/flags; construction negative; source evidence vectors.
- **PostgreSQL/concurrency:** Yok.
- **Geçiş kriteri:** 4.6A+B ve BS/IS/CF/Ratio registry regresyonları yeşil.

### 21.3 4.6C — Multi-Period Series Resolution

- **Kapsam:** Resolution request/snapshot/outcome, cadence ordering, explicit source policy, digest/version/scope verification, segmentation ve terminal proof contract.
- **Production dosyaları:** `resolution_contracts.py`, `resolution.py`, `app/integrations/trend_period_repository.py`.
- **Migration/model:** Restatement metadata modeli henüz yazılmaz; fake contracts ve mevcut rows okunur. Model/migration 4.6G’dedir.
- **Public contract:** Yok.
- **Testler:** Bütün cadence/cross-scope/digest/status/version/source selection vectors.
- **PostgreSQL/concurrency:** Gerçek source resolution ve company-lock/re-query tests.
- **Geçiş kriteri:** Unit + PostgreSQL resolution + 4.5 period resolver regresyonu yeşil.

### 21.4 4.6D — Pairwise Change and Direction Core

- **Kapsam:** Observation extraction, absolute/percentage/sign, transition, direction/stability.
- **Production dosyaları:** `calculation.py`, `service.py` başlangıcı.
- **Migration/model:** Yok.
- **Public contract:** Yok.
- **Testler:** Literal pairwise/sign/direction ve property determinism.
- **PostgreSQL/concurrency:** Yok.
- **Geçiş kriteri:** 4.6A–D hedefli set + legacy horizontal/growth ratio regresyonları yeşil.

### 21.5 4.6E — CAGR, Stability, Volatility and Break Analysis

- **Kapsam:** CAGR Newton root, normalized volatility, closed threshold category, coherent break algorithm.
- **Production dosyaları:** `calculation.py`, `aggregates.py`, `service.py`.
- **Migration/model:** Yok.
- **Public contract:** Yok.
- **Testler:** Exact golden/boundary/minimum/noise/tie/property vectors.
- **PostgreSQL/concurrency:** Yok.
- **Geçiş kriteri:** Bütün numeric tests ve 60×45 performance profile kabul edilir.

### 21.6 4.6F — Completeness, Evidence and Data Quality

- **Kapsam:** Evidence propagation, completeness counts, quality flags, nominal/restatement/one-off disclosure, final status.
- **Production dosyaları:** `quality.py`, `evidence.py`, `service.py`, `adapter.py`.
- **Migration/model:** Yok.
- **Public contract:** Yok.
- **Testler:** Evidence/count/status/segment/nominal golden’ları.
- **PostgreSQL/concurrency:** Resolver-integrated targeted tests.
- **Geçiş kriteri:** Tam pure-engine 4.6A–F kapısı yeşil.

### 21.7 4.6G — Persistence and Multi-Period Lineage

- **Kapsam:** AnalysisType additive model değeri, restatement metadata, N-period lineage, immutable triggers, repository, Persistence-v4, atomic idempotency.
- **Production dosyaları:** `app/models/{financial_analysis_result_revision_metadata,trend_analysis_lineage}.py`, `app/orchestration_persistence_v4/**`, `app/integrations/trend_lineage_repository.py`, model exports.
- **Migration/model:** Tek revision, base `d7e9a4c6f205`; iki yeni tablo ve AnalysisType check update.
- **Public contract:** V3 ve 5.0B contract değişmez; yeni V4 family.
- **Testler:** Model constraints, triggers, codec, owner/lineage, resume/reuse, migration cycle.
- **PostgreSQL/concurrency:** Zorunlu; exact replay, source conflict, SAVEPOINT loser discard, lock/re-query race.
- **Geçiş kriteri:** Bütün PostgreSQL/migration/concurrency + Persistence-v3 regresyonları 0 failed/0 skipped.

### 21.8 4.6H — Orchestrator/Application Integration

- **Kapsam:** V4 graph/dispatch/fingerprint/snapshot; Application-v3 commands/queries/ports/service/projection; authorization revalidation.
- **Production dosyaları:** `app/engines/analysis_orchestrator_v4/**`, `app/analysis_application_v3/**`, V4 adapters.
- **Migration/model:** Yok.
- **Public contract:** Yalnız yeni V4/V3 family; V3/Application-v2 frozen.
- **Testler:** Graph counts, envelope, fingerprint, start/resume/retry/cancel/read, scope/idempotency/auth/projection recovery.
- **PostgreSQL/concurrency:** Application+persistence full-path ve cross-scope race.
- **Geçiş kriteri:** V4/V3 integration ve bütün V3/v2 public contract golden’ları yeşil.

### 21.9 4.6I — Downstream Presentation Integration

- **Kapsam:** Report 1.2.0 exact 12-metric projection ve disclosure.
- **Production dosyaları:** `app/engines/executive_reports/trend_integration.py`; V4-only dispatch/mapping.
- **Migration/model:** Yok.
- **Public contract:** Report 1.0.0/1.1.0 değişmez; ayrı 1.2.0.
- **Testler:** Projection golden, unavailable/gap/evidence, no-recalculation, byte-equivalent score/ratio/recommendation regressions.
- **PostgreSQL/concurrency:** End-to-end stored trend→report read path.
- **Geçiş kriteri:** 4.6I + bütün legacy report golden’ları yeşil.

### 21.10 4.6J — Production Closure

- **Kapsam:** Bağımsız finansal/mimari/security audit; migration head/cycle; Docker full suite; Architecture Book ayrı kullanıcı onayıyla v1.7.0 senkronizasyonu.
- **Production dosyaları:** Blocking fix dışında yok; kapsam büyütülmez.
- **Migration/model:** Yalnız doğrulama.
- **Public contract:** Freeze audit.
- **Testler:** 4.6A–I gates, PostgreSQL, concurrency, migration cycle, full Docker.
- **Geçiş kriteri:** Kritik/yüksek blocking 0; 0 failed/0 skipped; diff-check temiz; tek head; healthy containers; Architecture Book sync ayrı onayla.

---

## 22. Risk analizi ve karşılıklar

| Risk | Seviye | Tasarım karşılığı |
|---|---|---|
| Discrete/cumulative karışması | Kritik | Exact cadence enum/matrix; mismatch non-comparable |
| Eksik dönemin sıfır sayılması | Kritik | `None/UNAVAILABLE`, metric segmentation |
| Cross-tenant source sızıntısı | Kritik | Tenant-qualified hiding, no existence probe |
| Caller payload spoofing | Kritik | ID intent + authoritative DB payload/digest |
| Stale source ile persistence | Kritik | Company lock + terminal re-query/proof |
| Duplicate payload owner | Yüksek | FinancialAnalysisResult tek owner; lineage metadata-only |
| Negatif base yüzde yanıltması | Yüksek | Percentage suppression + semantic status |
| CAGR misuse | Yüksek | Annual/gapless/positive exact eligibility |
| Restatement’ın trend gibi görünmesi | Yüksek | Revision metadata, chain head, segment boundary |
| Nominal büyümenin reel sunulması | Yüksek | Mandatory nominal disclosure |
| Gürültünün trend break sayılması | Orta | Two-transition coherent sides + threshold |
| Score ağırlıklarının örtük değişmesi | Yüksek | No trend edge/input to score/ratio/recommendation |
| Legacy contract drift | Yüksek | Separate V4/V3/V4 families + golden regressions |
| Advisory lock collision | Düşük | Yalnız over-serialization; scope/data birleşmez |

---

## 23. Reddedilen alternatifler

1. Mevcut BS/IS horizontal analysis’i N-döneme genişletmek — legacy contract/formül drift’i yaratır.
2. Ratio growth oranlarını trend serisi saymak — yalnız iki dönem ve sınırlı metric kapsar.
3. Cash Flow lineage tablosunu N-dönem için genişletmek — role/cardinality semantiğini bozar.
4. “Latest completed result” otomatik source selection — restatement/version/ambiguity riskinde deterministik değildir.
5. Eksik dönemi sıfır veya nearest period ile doldurmak — finansal olarak yanlış ve fail-open’dır.
6. Cumulative Q1/Q2/Q3’ü discrete trend gibi göstermek — coverage anlamını bozar.
7. Negatif tabanda standart percentage/CAGR göstermek — iyileşme yönünü ters/yanıltıcı gösterebilir.
8. Basit linear regression/ML break detector — açıklanabilirlik ve deterministik policy hedefini aşar.
9. Genel confidence score — farklı evidence eksiklerini tek sayıda gizler.
10. Trend’i score/recommendation ağırlıklarına bağlamak — yeni model validasyonu gerektirir ve v1 kapsamı dışıdır.
11. Event sourcing — state rebuild ihtiyacı yoktur; immutable lineage yeterlidir.
12. Tek request transaction boyunca DB session tutmak — saf engine süresince gereksiz lock/transaction ömrü yaratır.

---

## 24. Future hardening

Blocking olmayan, sonraki onaylı milestone’lara bırakılanlar:

- enflasyon/reel büyüme ve currency translation;
- seasonal adjustment ve rolling-window analytics;
- forecast/budget/anomaly modelleri;
- configurable/custom metric registry administration;
- deterministic one-off adjustment registry ve yönetim akışı;
- trend-aware score/benchmark/recommendation model validasyonu;
- distributed admission/lock ve background execution;
- group/consolidated trend (4.7);
- API/UI versioned trend endpoint ve visualizations;
- 60 dönem üstü offline/batch analiz.

---

## 25. Production Readiness kriterleri

Tasarım readiness ile runtime readiness ayrıdır.

### 25.1 Design readiness

- Accounting/period policy: kapalı.
- Metric manifest/version/evidence: kapalı.
- Percentage/sign/CAGR/direction/volatility/break formülleri: kapalı.
- Source resolution/concurrency/idempotency: kapalı.
- Payload ownership/lineage/migration: kapalı.
- V4/Application-v3/Persistence-v4/report boundary: kapalı.
- Blocking kullanıcı kararı: 0.

**Design Readiness: %100.**

### 25.2 Runtime readiness

Henüz production code, test, model veya migration yazılmadığı için **Implementation/Production Readiness: %0**. Runtime readiness ancak 4.6A–4.6J kapıları 0 failed/0 skipped ile tamamlanınca %100 olabilir.

---

## 26. Açık kararlar ve kullanıcı onay kapısı

### 26.1 Blocking açık kararlar

**Yok — 0.**

### 26.2 Non-blocking deployment/operasyon kararları

Saf engine davranışını etkilemeyen performans alarm eşikleri ve production dashboard isimleri deployment sırasında belirlenebilir; bunlar implementation blocker değildir ve fingerprint/policy’ye girmez.

### 26.3 Onay kapısı

Bu dokümanın FINAL kabulü production implementasyonuna otomatik izin vermez. Implementasyon ancak ayrı açık kullanıcı onayıyla 4.6A’dan başlayarak test-gated sırada yürütülür. 4.6 tamamen kapanmadan 4.7 veya başka milestone’a geçilmez. Commit/push ayrıca açık kullanıcı talebi olmadan yapılmaz.

---

## 27. Architecture Book senkronizasyon planı

4.6J tamamlandıktan ve Docker/PostgreSQL/migration kapıları doğrulandıktan sonra, ayrı kullanıcı onayıyla Architecture Book v1.7.0 aşağıdaki gerçek implementasyon bilgileriyle güncellenir:

- Multi-Period Trend Engine ve 45 metric registry;
- cadence/minimum/evidence/nominal policy;
- N-period authoritative resolution ve lineage ownership;
- V4 Orchestrator, Application-v3, Persistence-v4;
- Report 1.2.0 projection;
- gerçek Alembic head ve gerçek Docker test sayısı.

Bu tasarım turunda Architecture Book değiştirilmez ve gelecekteki test/migration sonucu uydurulmaz.

---

## 28. Tasarım kapanış kontrolü

Tek finansal/mimari bütünlük denetiminde aşağıdakiler doğrulanmıştır:

- Period family ile measurement basis ayrımı çelişkisizdir.
- Minimum observation eşikleri result/status davranışıyla uyumludur.
- Cumulative/discrete ve gap/restatement segment kuralları fail-closed’dur.
- 45 metric manifest yalnız mevcut BS/IS/Cash Flow/Ratio kanonik alanlarını tüketir.
- Percentage/sign/CAGR/volatility/break kuralları zero/negative/sign-change durumlarını kapatır.
- Evidence yükseltilmez; missing hiçbir yerde zero olmaz.
- FinancialAnalysisResult tek payload sahibidir; lineage duplicate source of truth değildir.
- Restatement metadata period tablosuna yanlış semantik yüklemez.
- V4/Application-v3/Persistence-v4 legacy public contract’ları değiştirmez.
- Trend score/recommendation/4.7 kapsamına sızmaz.
- 4.6A–4.6J sıra ve kabul kapıları uygulanabilirdir.
- Açık işaretleyici veya blocking karar yoktur.

**Kritik blocking: 0. Yüksek blocking: 0. Kalan gerçek kullanıcı kararı: 0.**

**Milestone 4.6 — Multi-Period Trend Engine tasarımı FINAL olarak onaylanabilir ve implementasyona hazırdır.**
