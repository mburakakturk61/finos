# Milestone 5.0A — Analysis Orchestrator: Mimari Tasarım Dokümanı (v2 — Denetim Sonrası Revizyon)

| | |
|---|---|
| Doküman durumu | **TASARIM — 2. KARAR TURUNA HAZIR** (implementasyon başlamadı) |
| Versiyon | 2.0 — Bağımsız mimari denetim sonrası revizyon |
| Kapsam | Yalnızca mimari tasarım. Kod yok, test yok, migration yok, API yok, adapter yok. |
| Ana otorite | `docs/FINOS_ARCHITECTURE_BOOK.md` (bu doküman onunla çelişemez; çelişki varsa Architecture Book bağlayıcıdır) |
| Referans motor sözleşmeleri | Bölüm 2.1 — `app/engines/**` içindeki gerçek koddan çıkarılmıştır, v1'den değişmemiştir. |
| "FINOS" ifadesinin statüsü | Yalnızca dahili geliştirme kod adı (Architecture Book Bölüm 0). Bu doküman TAMAMEN yeniden tarandı — hiçbir yeni sembolde/metinde marka bağımlılığı yoktur (bkz. Bölüm 87). |
| Bu revizyonun tetikleyicisi | Bağımsız mimari denetim raporu (Principal Architect / Distributed Systems / Workflow-Orchestration / Financial Systems Auditor / Production Reliability rolleriyle yapılmış) — 4 ciddi, kendiliğinden çelişkili bulgu + 6 orta seviye bulgu tespit etti. Bu revizyon TÜMÜNÜ kök nedeninden çözer. |
| Kapsam dışı (bu turda kesinlikle yapılmayacak) | Kod, test, migration, API, adapter, background job, queue, bulk-upload bağlantısı, commit, push |

---

## 0. Önsöz ve Okuma Rehberi

Bu doküman, Milestone 5.0A tasarımının **v2** sürümüdür. v1, kullanıcının 82 maddelik kapsam listesini eksiksiz yanıtlamıştı, ancak ardından yapılan bağımsız bir mimari denetim, v1'in kendi içinde çelişen ve implementasyona geçilmeden düzeltilmesi gereken dört kök-neden sorunu tespit etti:

1. `callable_ref: str` alanı, Architecture Book §18'in yasakladığı dinamik string-den-fonksiyon-çözme desenini fiilen gerektiriyordu.
2. Financial Statements'ın iki alt motoru için "AND" (Bölüm 26) ve "OR" (Bölüm 5/28/33-S1) semantikleri aynı anda iddia ediliyordu.
3. `RunStatus.FULLY_COMPLETED`, TÜM motorlar `DEGRADED` olsa bile geçerli sayılabiliyordu — bu, dokümanın kendi "partial success sessizce başarılı sayılmaz" ilkesini ihlal ediyordu.
4. DAG kenar sayısı (23) matematiksel olarak yanlıştı (gerçek sayı 24).

Bunlara ek olarak altı orta-seviye bulgu (input fingerprint eksikliği, duplicate source-of-truth, versiyon alanlarının konsolidasyonu, `cancellation_token`'ın serileştirme çelişkisi, zamanlama alanlarının determinizm sözleşmesiyle karışması, ve execution plan'ın "türetilmiş mi elle mi yazılmış" belirsizliği) tespit edildi.

**Bu doküman, denetimdeki HER bulguyu kök nedeninden ele alır.** Değişen sözleşmeler, kapanan/kalan açık kararlar ve yeni Production Readiness değerlendirmesi Bölüm 87'de ("Bağımsız Mimari Denetim Sonrası Revizyon Raporu") ayrıntılı olarak raporlanır.

Kullanıcının orijinal 82 maddelik kapsamı bu dokümanda hâlâ tam olarak karşılanmaktadır; yalnızca ilgili bölümler denetim bulgularına göre yeniden yazılmıştır. Bölüm numaraları v1'e göre bir miktar kaymıştır (yeni bölümler eklendiği için); her bölüm başlığında hangi orijinal maddeyi kapsadığı hâlâ **(Madde N)** notasyonuyla belirtilir.

---

## İçindekiler

0. Önsöz ve Okuma Rehberi
1. Orchestrator'ın Kesin Sorumlulukları
2. Kapsam Dışı Sorumluluklar
2.1 Araştırma Temeli — Gerçek Motor Sözleşmeleri
3. Engine Dependency Graph (revize — `any_of`/`all_of` modeli)
4. Execution DAG (revize — 24 kenar, doğrulama checklist'i)
5. Zorunlu ve Opsiyonel Motorlar (revize)
6. Engine Execution Order (revize — v1 tamamen sequential)
7. Gelecekteki Paralellik Fırsatı (v1 Kapsamı Dışı) (revize)
8. Sequential Zorunluluklar (revize)
9. Failure Propagation (revize)
10. RunStatus Modeli — 5 Değerli Kapalı Enum (TAMAMEN YENİDEN YAZILDI)
11. Retry Politikası
12. Idempotency (revize — fingerprint referansı)
13. Re-run Davranışı (revize)
14. Resume/Recovery (revize — `PreviousExecutionSnapshot`)
15. Cancellation (TAMAMEN YENİDEN YAZILDI — `cancellation_probe`)
16. Timeout — v1'den Çıkarıldı (TAMAMEN YENİDEN YAZILDI)
17. Circuit Breaker Gerekip Gerekmediği
18. Engine Invocation Spec (revize — `callable_ref` KALDIRILDI)
19. Orchestrator Input/Output Contract (revize)
20. Immutable Dataclass Yapısı
21. ExecutionStatus Enum'ları (revize — `RunStatus` 5 değer)
22. Per-Engine Execution Record (revize — fingerprint alanları, timing kaldırıldı)
23. Run-Level Result Sözleşmesi (revize — tek source of truth, typed accessor'lar)
24. Warning/Error Modeli
25. Structured Error Taxonomy (revize — güvenlik/sanitization kuralları, `TIMEOUT_EXCEEDED` kaldırıldı)
26. Dependency Failure Davranışı (revize — `any_of`/`all_of`)
27. Optional Engine Failure Davranışı
28. Critical Engine Failure Davranışı (revize)
29. Determinizm — İki Ayrı Property (TAMAMEN YENİDEN YAZILDI)
30. Read-Only, No-Recompute ve Single-Source-of-Truth Invariant'ları (revize)
31. Upstream Result Reuse (revize — fingerprint şartları)
32. Global State Yasağı
33. Doğrudan Sorulan 14 Soruya Cevaplar (revize)
34. Registry Tabanlı Engine Planı Gerekip Gerekmediği
35. Engine Dependency Registry (revize — yalnızca metadata, callable YOK)
36. Engine Dispatch Table (YENİ — `ORCHESTRATOR_ENGINE_DISPATCH`)
37. Execution Plan Derivation (TAMAMEN YENİDEN YAZILDI — DAG'dan türetilir, duplicate yok)
38. Plan Versioning
39. Schema Compatibility
40. Versiyon Alanları — Konsolide Tablo (YENİ)
41. Input Fingerprint Modeli (YENİ — kapsamlı)
42. Input Version Inventory
43. Execution Provenance
44. Audit Trail Sözleşmesi
45. Timing/Telemetry Ayrımı (TAMAMEN YENİDEN YAZILDI — `ExecutionTelemetry`, `TimingProbe`)
46. Correlation ID / Run ID Davranışı
47. Time Bilgisinin Dışarıdan Verilmesi ve Monotonic Clock İstisnası (revize — Açık Karar #10 KAPANDI)
48. datetime.now/uuid4/random Yasağı
49. Metrics Sözleşmesi
50. Logging Sınırı
51. Persistence ile Sınır
52. API ile Sınır
53. Background Job ile Sınır
54. Bulk Upload ile Sınır
55. Transaction Sınırları
56. DB Yazmayan Saf Orchestrator Mümkün mü
57. Saf Orchestrator ile Persistence Adapter Ayrımı (revize — at-least-once netliği)
58. Synchronous vs Asynchronous Execution
59. In-Process vs Queue Tabanlı Execution
60. v1 İçin Önerilen Çalışma Modeli (revize — yeni imza)
61. Çok Şirketli Batch Analiz
62. Çok Dönemli Analiz
63. Tenant/Authorization Sınırı
64. Concurrency Notu — v1 Kapsamı Dışı (revize)
65. Registry Isolation (revize)
66. Test Isolation
67. Test Stratejisi (TAMAMEN YENİDEN YAZILDI — genişletilmiş kategoriler)
68. Performans Hedefleri (revize)
69. Memory Hedefleri
70. Risk Analizi (revize)
71. Enterprise Readiness
72. Production Readiness (revize — yeni yüzde)
73. Alt Adımlara Bölünmüş İmplementasyon Planı (revize)
74. Açık Kararlar (TAMAMEN YENİDEN YAZILDI — kapananlar çıkarıldı, kalanlar konsolide edildi)
75. Bağımsız Mimari Denetim Sonrası Revizyon Raporu (YENİ)
76. Kapanış

---

## 1. Orchestrator'ın Kesin Sorumlulukları (Madde 1)

Analysis Orchestrator'ın sorumluluğu, **9 motoru doğru sırada, doğru girdilerle çağırmak ve bunun etrafındaki koordinasyonu yönetmektir** — finansal içerik üretmek değil. Kesin sorumluluklar (v1'den değişmedi):

1. **Çağrı sırası kararı** — Bölüm 3/4'teki bağımlılık grafiğine göre, DAG'dan türetilmiş (Bölüm 37) deterministik bir sırayla.
2. **Sonuç taşıma (result threading)** — bir motorun çıktısını bir sonrakinin beklediği parametreye birebir eşleyerek aktarmak.
3. **Durum gözlemi** — her motorun status alanını okuyup Bölüm 6'daki (Madde 6 sözlüğü, artık **Bölüm 6 revize edilmiş "İnner-Status Mapping Tablosu"na taşındı, bkz. Bölüm 9.1**) eşlemeye göre `EngineExecutionStatus`'a çevirmek.
4. **İstisna yönetimi** — Recommendation/Executive Report/Render Contract'ın sözleşme-ihlali istisnalarını yakalayıp `StructuredError`'a (Bölüm 25, artık güvenlik kurallarıyla güçlendirilmiş) dönüştürmek.
5. **Run-seviyeli sonuç birleştirme** — `OrchestrationRunResult` (Bölüm 23, artık TEK source-of-truth ile).
6. **Gözlemlenebilirlik metadata'sı** — run_id/correlation_id/provenance DOLDURMAK (ÜRETMEK değil); zamanlama artık AYRI, opsiyonel bir `ExecutionTelemetry` sözleşmesindedir (Bölüm 45).
7. **Yeniden çalıştırılabilirlik** — fingerprint-doğrulanmış reuse kuralları (Bölüm 31/41).

---

## 2. Kapsam Dışı Sorumluluklar (Madde 2)

Orchestrator **kesinlikle** aşağıdakileri yapmaz — v1'deki listeye, denetimin gerektirdiği dört yeni madde eklenmiştir:

- Hiçbir finansal değer hesaplamaz, hiçbir motor sonucunu değiştirmez/yeniden hesaplamaz, rapor/dashboard içeriği uydurmaz (v1 ile aynı).
- Veritabanına yazmaz, migration içermez, API endpoint'i değildir, background job/queue değildir, bulk-upload'a bağlanmaz, yetkilendirme uygulamaz, kendi saatini/kimliğini üretmez (v1 ile aynı).
- **Dinamik string-den-callable-çözme yapmaz** — `importlib`/`getattr`/`eval`/`exec` ile motor fonksiyonu ÇÖZMEZ; TÜM motor çağrıları, import-zamanında bağlanmış doğrudan fonksiyon referanslarıyla yapılır (Bölüm 18/36, **denetim bulgusu H1'in kapanışı**).
- **v1'de motor çağrılarını paralelleştirmez** — tamamen sıralı (Bölüm 6/7, **denetim bulgusu C3'ün kapanışı**).
- **v1'de run-seviyeli bir zaman aşımı (timeout) sözleşmesi sunmaz** — yalnızca çağrılar arasında bir cancellation noktası sunar (Bölüm 15/16, **denetim bulgusu C2'nin kapanışı**).
- **Aynı `run_id` için farklı girdi fingerprint'i sessizce kabul etmez** — bu durumu açıkça reddeder (Bölüm 41, **denetim bulgusu R1'in kapanışı**).

---

## 2.1. Araştırma Temeli — Gerçek Motor Sözleşmeleri (Zemin Bölüm)

Bu bölüm v1'den **değişmemiştir** — bağımsız denetim, buradaki motor sözleşmesi çıkarımlarında hiçbir hata bulmadı (yalnızca bunların ÜZERİNE inşa edilen orchestration mantığında hatalar bulundu). Aşağıdaki envanter aynen korunmuştur.

### 2.1.1 Financial Statements Engine (`app/engines/balance_sheet`, `app/engines/income_statement`)

```
analyze_balance_sheet(
    *, content: bytes | None, filename: str | None,
    trial_balance_result: dict[str, Any] | None,
    prior_period_facts: BalanceSheetFacts | None = None,
) -> BalanceSheetAnalysisOutcome

analyze_income_statement(...)  # aynı desende, IncomeStatementFacts ile
```

`BalanceSheetAnalysisOutcome` alanları: `status: AnalysisStatus`, `source_mode: SourceMode | None`, `result_json: dict | None`, `error_message: str | None`, `trial_balance_usage: str | None`.

**Gerçek davranış:** `content` doğrudan ayrıştırılabiliyorsa authoritative kaynaktır; `trial_balance_result` yalnızca reconciliation için kullanılır. İkisi de yoksa/kullanılamıyorsa `status=AnalysisStatus.FAILED, result_json=None` döner — istisna FIRLATMAZ (`app/engines/balance_sheet/service.py:143`).

`AnalysisStatus` (4 değer): `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`. Motor yalnızca `COMPLETED`/`FAILED` üretir.

### 2.1.2 Financial Ratio Engine (`app/engines/financial_ratios`)

```
analyze_financial_ratios(
    *, balance_sheet_result: dict[str, Any] | None,
    income_statement_result: dict[str, Any] | None,
    prior_period_balance_sheet_result: dict | None = None,
    prior_period_income_statement_result: dict | None = None,
    period_start_date=None, period_end_date=None,
    period_months_covered: int | None = None,
) -> dict[str, Any]
```

**Kritik gerçek:** `balance_sheet_result` VE `income_statement_result` her ikisi de Optional'dır. `None` geldiğinde istisna FIRLATMAZ, tüm oranları `"not_calculable"` ile işaretler. Kaynak kodda `raise` YOKTUR.

### 2.1.3 Benchmark Engine (`app/engines/benchmarks`)

```
evaluate_benchmarks(
    ratio_result_json: dict[str, Any], *,
    industry_code: str | None = None,
    company_size_bucket: str | None = None,
) -> dict[str, Any]
```

`ratio_result_json` zorunlu, pozisyonel (Optional değil). Her oranın `status` alanına bakar. Kaynak kodda `raise` YOKTUR.

### 2.1.4 Health Score Engine (`app/engines/health_score`)

```
compute_financial_health_score(
    ratio_result_json: dict[str, Any],
    benchmark_result_json: dict[str, Any], *,
    industry_code: str | None = None,
    company_size_bucket: str | None = None,
    tenant_id: str | None = None,
) -> HealthScoreResult
```

`HealthScoreComputationStatus` (3 değer): `COMPUTED`, `HARD_FAIL_CAPPED`, `INSUFFICIENT_DATA`. Kaynak kodda `raise` YOKTUR. `tenant_id` **yetkilendirme DEĞİLDİR** — yalnızca kategori ağırlık profili segmentasyon anahtarıdır (v1'de her zaman `global`'a düşer).

### 2.1.5 Credit Score Engine (`app/engines/credit_score`)

```
compute_credit_score(
    ratio_result_json: dict[str, Any],
    benchmark_result_json: dict[str, Any],
    health_score_result: HealthScoreResult, *,
    industry_code: str | None = None,
    company_size_bucket: str | None = None,
    tenant_id: str | None = None,
) -> CreditScoreResult
```

`HealthScoreResult`'ı OKUR, yeniden hesaplamaz. `CreditScoreComputationStatus` (3 değer, health_score ile aynı isimler, bağımsız enum). Kaynak kodda `raise` YOKTUR.

### 2.1.6 Recommendation Engine (`app/engines/recommendation`)

```
generate_recommendations(
    ratio_result_json: dict[str, Any],
    benchmark_result_json: dict[str, Any],
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult, *,
    industry_code: str | None = None,
    company_size_bucket: str | None = None,
    tenant_id: str | None = None,
) -> RecommendationResult
```

Zincirdeki İLK motor: (a) tip-kontrolü için `ValueError` fırlatır (4 adet), (b) upstream schema/version uyumluluğunu FİİLEN kontrol eder — sonucu `RecommendationComputationStatus.SCHEMA_INCOMPATIBLE`/`VERSION_MISMATCH` olarak YANSIR (istisna değil). `RuntimeError` yalnızca invariant ihlalinde (mutasyon/registry boyutu). `RecommendationComputationStatus` (5 değer): `COMPUTED`, `NO_RECOMMENDATIONS_TRIGGERED`, `INSUFFICIENT_DATA`, `SCHEMA_INCOMPATIBLE`, `VERSION_MISMATCH`.

### 2.1.7 Executive Report Engine (`app/engines/executive_reports`)

```
generate_executive_report(
    report_type: ReportType,
    balance_sheet_result_json, income_statement_result_json,
    ratio_result_json, benchmark_result_json,
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    recommendation_result: RecommendationResult, *,
    company_metadata: ReportCompanyMetadata,
    reporting_period_label_tr: str,
    optional_sections: tuple[ReportSectionCode, ...] | None = None,
    report_id: str | None = None, generated_at: str | None = None,
    locale: str = "tr-TR", currency_display_policy: str | None = None,
) -> ExecutiveReportResult
```

TÜM ALTI yukarı-akış motorunun (7 parametre — Financial Statements×2 dahil) çıktısını ister. `ReportComputationStatus` (3 değer). `UnsupportedLocaleError`/`ValueError` yalnızca çağrı-sözleşmesi ihlalinde.

### 2.1.8 Dashboard Engine (`app/engines/dashboards`)

```
generate_dashboard_snapshot(
    dashboard_type: DashboardType,
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    recommendation_result: RecommendationResult, *,
    benchmark_result_json: dict | None = None,
    company_metadata: ReportCompanyMetadata,
    report_id: str | None = None, generated_at: str | None = None,
) -> DashboardSnapshot
```

Financial Statements/Ratio'ya doğrudan bağımlı DEĞİLDİR. `_check_dashboard_compatibility()`, uyumsuzsa istisna FIRLATMAZ — boş widgets + `SCHEMA_VERSION_UNSUPPORTED` warning'i.

### 2.1.9 Render Contract Preview (`app/engines/render_contract`)

```
preview_render_contract(
    report_result: ExecutiveReportResult,
    render_contract: RenderContract,
) -> RenderContractPreview
```

Yalnızca zaten üretilmiş bir `ExecutiveReportResult` alır. **Kendi bir computation-status enum'u YOKTUR** — yalnızca başarıyla döner ya da `InvalidReportResultError` fırlatır (bkz. Bölüm 9.1, bu motorun DEGRADED durumu YOKTUR — denetim bulgusu H4'ün kapanışı).

### 2.1.10 Özet Tablo — Hata Modeli Sınıflandırması

| Motor | "Veri yetersiz/uyumsuz" nasıl ifade edilir | Gerçek istisna(lar) |
|---|---|---|
| Financial Statements | `status=AnalysisStatus.FAILED`, `result_json=None` | Yok |
| Ratio | `"status": "not_calculable"` (oran bazında) | Yok |
| Benchmark | `"status": "not_calculable"` (oran bazında, okunur) | Yok |
| Health Score | `status=HealthScoreComputationStatus.INSUFFICIENT_DATA/HARD_FAIL_CAPPED` | Yok |
| Credit Score | `status=CreditScoreComputationStatus.INSUFFICIENT_DATA/HARD_FAIL_CAPPED` | Yok |
| Recommendation | `status=RecommendationComputationStatus.INSUFFICIENT_DATA/SCHEMA_INCOMPATIBLE/VERSION_MISMATCH` | `ValueError`, `RuntimeError` |
| Executive Report | `status=ReportComputationStatus.SCHEMA_INCOMPATIBLE/VERSION_MISMATCH` | `UnsupportedLocaleError`, `ValueError` |
| Dashboard | `is_compatible=False` → boş widgets + warning | Yok |
| Render Contract | (yok — girdi zaten üretilmiş bir rapor); **kendi status'u yok** | `InvalidReportResultError` |

---

## 3. Engine Dependency Graph (Madde 3) — REVİZE: `any_of`/`all_of` Modeli

**Denetim bulgusu H2'nin kök-neden çözümü.** v1'deki `EngineInvocationSpec.required_inputs: tuple[str, ...]`, yalnızca AND (hepsi zorunlu) semantiğini ifade edebiliyordu; bu, RATIO'nun FS_BALANCE_SHEET/FS_INCOME_STATEMENT ile ilişkisini (yalnızca BİRİNİN yeterli olduğu bir OR ilişkisi) YANLIŞ modelliyordu ve Bölüm 5/28/33-S1 ile Bölüm 26 arasında doğrudan bir çelişki yaratıyordu.

**Yeni, deklaratif bağımlılık modeli:**

```
@dataclass(frozen=True)
class DependencyRequirement:
    all_of: "tuple[EngineCode, ...]"      # HEPSİ COMPLETED/DEGRADED/REUSED olmalı
    any_of: "tuple[EngineCode, ...]"      # EN AZ BİRİ COMPLETED/DEGRADED/REUSED olmalı
    optional: "tuple[EngineCode, ...]"    # SKIPPED/FAILED olsa bile motor yine de çağrılır (girdi None geçilir)
```

Bir `EngineCode`'un bağımlılığı, `all_of` VE `any_of` kümelerinin İKİSİNİN BİRDEN karşılanmasını gerektirir (bir küme boşsa o küme otomatik karşılanmış sayılır). `optional`, Dashboard'un `benchmark_result_json`'u gibi TAMAMEN opsiyonel girdileri ifade eder (Bölüm 5).

**Somut örnekler (Bölüm 35'teki `ENGINE_DEPENDENCY_REGISTRY`'nin önizlemesi):**

```
RATIO:            DependencyRequirement(all_of=(), any_of=(FS_BALANCE_SHEET, FS_INCOME_STATEMENT), optional=())
BENCHMARK:        DependencyRequirement(all_of=(RATIO,), any_of=(), optional=())
HEALTH_SCORE:     DependencyRequirement(all_of=(RATIO, BENCHMARK), any_of=(), optional=())
CREDIT_SCORE:     DependencyRequirement(all_of=(RATIO, BENCHMARK, HEALTH_SCORE), any_of=(), optional=())
RECOMMENDATION:   DependencyRequirement(all_of=(RATIO, BENCHMARK, HEALTH_SCORE, CREDIT_SCORE), any_of=(), optional=())
EXECUTIVE_REPORT: DependencyRequirement(all_of=(FS_BALANCE_SHEET, FS_INCOME_STATEMENT, RATIO, BENCHMARK, HEALTH_SCORE, CREDIT_SCORE, RECOMMENDATION), any_of=(), optional=())
DASHBOARD:        DependencyRequirement(all_of=(HEALTH_SCORE, CREDIT_SCORE, RECOMMENDATION), any_of=(), optional=(BENCHMARK,))
RENDER_CONTRACT:  DependencyRequirement(all_of=(EXECUTIVE_REPORT,), any_of=(), optional=())
```

**Kural (Bölüm 26 ile tutarlı, artık çelişkisiz):**

- **RATIO:** FS_BALANCE_SHEET VEYA FS_INCOME_STATEMENT'ten EN AZ BİRİ `result_json` ürettiyse (yani `EngineExecutionStatus.COMPLETED` veya `DEGRADED`, bkz. Bölüm 9.1) RATIO çağrılır — bu durumda başarısız olanın karşılığı `None` olarak RATIO'ya geçirilir (motorun kendi `Optional` parametre sözleşmesi buna zaten izin verir, Bölüm 2.1.2). İKİSİ de `FAILED` ise (`result_json=None` her ikisinde de) RATIO **çağrılmaz**, `SKIPPED` olarak işaretlenir.
- Bunun dışındaki TÜM motorlar (Benchmark, Health Score, Credit Score, Recommendation, Executive Report) yalnızca `all_of` kullanır — klasik AND semantiği, v1'in orijinal (doğru) modeliyle aynı.
- Dashboard, `all_of` (3 zorunlu) + `optional` (Benchmark) kombinasyonunu kullanır.

**Metodolojik gerekçe (denetimin Bölüm 3 — Finansal/Metodolojik Hatalar bulgusuna doğrudan cevap):** Ratio'yu `(None, None)` ile çalıştırmak yerine SKIP etmenin gerekçesi şudur — (a) `(None, None)` ile üretilecek "tamamen not_calculable" bir Ratio sonucu, gerçek kök nedeni (Financial Statements'ın HİÇBİR girdi üretemediği) gizler ve bunun yerine Ratio katmanında yeni, ANLAMSIZ bir "veri yetersiz" mesajı üretir; (b) run seviyesinde `SKIPPED` + açık bir `ENGINE_SKIPPED_DUE_TO_CRITICAL_FAILURE` (dependency_engine_codes ile hangi FS motorunun başarısız olduğunu gösteren) warning'i, kullanıcıya kök nedeni DAHA NET gösterir; (c) zincirin geri kalanının (Health Score/Credit Score/Recommendation'ın kendi `INSUFFICIENT_DATA` mekanizması) BOŞ bir Ratio/Benchmark sonucuyla nasıl davranacağı zaten test edilmemiş bir yoldur — SKIP, bu belirsiz yolu tamamen ELER. Bu, denetimin işaret ettiği karşıt argümanı (zincirin kendi graceful-degradation mekanizmasından faydalanmak) BİLEREK reddeden, açık bir tasarım kararıdır — Bölüm 74 Açık Karar listesinden ÇIKARILMIŞ ve burada KİLİTLENMİŞTİR.

---

## 4. Execution DAG (Madde 4) — REVİZE: 24 Kenar, Doğrulama Checklist'i

**Denetim bulgusu H3'ün (kenar sayısı hatası) kök-neden çözümü.** Kenar listesi bağımsız olarak yeniden sayıldı (elle + script ile doğrulandı):

```
düğümler (10): {FS_BALANCE_SHEET, FS_INCOME_STATEMENT, RATIO, BENCHMARK, HEALTH_SCORE,
                CREDIT_SCORE, RECOMMENDATION, EXECUTIVE_REPORT, DASHBOARD, RENDER_CONTRACT}

kenarlar (TOPLAM 24 — 21 zorunlu + 3 opsiyonel/any_of-kaynaklı):
  1.  FS_BALANCE_SHEET   -> RATIO             [any_of grubu]
  2.  FS_INCOME_STATEMENT -> RATIO            [any_of grubu]
  3.  RATIO              -> BENCHMARK          [zorunlu]
  4.  RATIO              -> HEALTH_SCORE       [zorunlu]
  5.  BENCHMARK          -> HEALTH_SCORE       [zorunlu]
  6.  RATIO              -> CREDIT_SCORE       [zorunlu]
  7.  BENCHMARK          -> CREDIT_SCORE       [zorunlu]
  8.  HEALTH_SCORE       -> CREDIT_SCORE       [zorunlu]
  9.  RATIO              -> RECOMMENDATION     [zorunlu]
  10. BENCHMARK          -> RECOMMENDATION     [zorunlu]
  11. HEALTH_SCORE       -> RECOMMENDATION     [zorunlu]
  12. CREDIT_SCORE       -> RECOMMENDATION     [zorunlu]
  13. FS_BALANCE_SHEET   -> EXECUTIVE_REPORT   [zorunlu]
  14. FS_INCOME_STATEMENT -> EXECUTIVE_REPORT  [zorunlu]
  15. RATIO              -> EXECUTIVE_REPORT   [zorunlu]
  16. BENCHMARK          -> EXECUTIVE_REPORT   [zorunlu]
  17. HEALTH_SCORE       -> EXECUTIVE_REPORT   [zorunlu]
  18. CREDIT_SCORE       -> EXECUTIVE_REPORT   [zorunlu]
  19. RECOMMENDATION     -> EXECUTIVE_REPORT   [zorunlu]
  20. HEALTH_SCORE       -> DASHBOARD          [zorunlu]
  21. CREDIT_SCORE       -> DASHBOARD          [zorunlu]
  22. RECOMMENDATION     -> DASHBOARD          [zorunlu]
  23. BENCHMARK          -> DASHBOARD          [opsiyonel]
  24. EXECUTIVE_REPORT   -> RENDER_CONTRACT    [zorunlu]
```

**Kenar dağılımı:** 10 düğüm, 24 toplam kenar = 2 `any_of` kenarı (RATIO'nun iki FS girdisi) + 21 `all_of` (zorunlu) kenar + 1 `optional` kenar (BENCHMARK→DASHBOARD).

**Registry kayıt-anı doğrulama checklist'i (Bölüm 35'e eklenir):**

- [ ] Düğüm sayısı == 10.
- [ ] Zorunlu (`all_of`'tan gelen) kenar sayısı == 21.
- [ ] Opsiyonel (`optional`'dan gelen) kenar sayısı == 1.
- [ ] `any_of`'tan gelen kenar sayısı == 2.
- [ ] Toplam kenar sayısı == 24.
- [ ] Graf döngüsüz (acyclic).
- [ ] Her `EngineCode`, `ENGINE_DEPENDENCY_REGISTRY`'de tam olarak bir kez tanımlı.
- [ ] Her `DependencyRequirement.all_of`/`any_of`/`optional` içindeki her `EngineCode`, registry'de gerçekten var.

---

## 5. Zorunlu ve Opsiyonel Motorlar (Madde 5) — REVİZE

| Motor | Zorunlu mu? | Gerekçe |
|---|---|---|
| Financial Statements (FS_BALANCE_SHEET, FS_INCOME_STATEMENT) | **`any_of` — en az biri yeterli** (Bölüm 3) | RATIO'nun girdisi; ikisi BİRDEN başarısız olursa RATIO SKIP olur |
| Ratio | **Zorunlu (`all_of` ile downstream'e bağlanır)** | Benchmark'ın zorunlu girdisi |
| Benchmark | **Zorunlu** | Health/Credit/Recommendation/Executive Report'un girdisi |
| Health Score | **Zorunlu** | Credit Score ve Recommendation'ın zorunlu girdisi |
| Credit Score | **Zorunlu** | Recommendation'ın zorunlu girdisi |
| Recommendation | **Zorunlu** | Executive Report ve Dashboard'ın zorunlu girdisi |
| Executive Report | **Opsiyonel (run-seviyesinde `requested_outputs` ile seçilebilir)** | Bir run yalnızca Dashboard isteyip Executive Report istemeyebilir |
| Dashboard | **Opsiyonel (run-seviyesinde seçilebilir)** | Bir run yalnızca Executive Report isteyip Dashboard istemeyebilir |
| Render Contract Preview | **Opsiyonel, Executive Report'a `all_of` bağımlı** | Yalnızca Executive Report üretildiyse VE istendiyse |

"Zorunlu" burada **"DAG'da atlanamaz"** anlamına gelir; her motor kendi içinde `DEGRADED` durumuna düşebilir (Bölüm 9.1). Financial Statements artık kendi özel `any_of` satırıyla, önceki AND/OR çelişkisi olmadan tarif edilmiştir.

---

## 6. Engine Execution Order (Madde 6) — REVİZE: v1 Tamamen Sequential

**Denetim bulgusu C3'ün kök-neden çözümü.** v1'deki "paralel çalışabilecek aşamalar" (FS_BS/FS_IS, EXEC_REPORT/DASHBOARD) kavramı **v1'den tamamen çıkarılmıştır** (gerekçe: Bölüm 7). Kanonik, kilitli, TAMAMEN SIRALI çalıştırma sırası:

```
1. FS_BALANCE_SHEET
2. FS_INCOME_STATEMENT
3. RATIO
4. BENCHMARK
5. HEALTH_SCORE
6. CREDIT_SCORE
7. RECOMMENDATION
8. EXECUTIVE_REPORT
9. DASHBOARD
10. RENDER_CONTRACT
```

Bu sıra, Bölüm 37'deki DAG'dan **türetilmiş, deterministik bir topological sort**'un tek olası (tam sıralı, eş-seviye tie-break'i alfabetik `EngineCode.value`'ya göre uygulanan) çıktısıdır — registry insertion-order'dan bağımsızdır.

---

## 7. Gelecekteki Paralellik Fırsatı (v1 Kapsamı Dışı) (Madde 7) — REVİZE

**Denetim bulgusu C3'ün tam gerekçesi.** v1'in TAMAMEN sıralı olmasının nedenleri:

1. **Motorlar CPU-bound'dur, I/O yapmazlar** (Architecture Book §10) — Python GIL, CPU-bound bytecode yürütmesini thread'ler arasında GERÇEKTEN paralelleştirmez; `ThreadPoolExecutor` kullanmak, bu motorlar için ölçülebilir bir hızlanma SAĞLAMAZ (thread oluşturma/context-switch maliyeti, motorların kendi sub-100ms çalışma süresini kolayca AŞABİLİR).
2. **Paralel çalıştırma, non-determinism riski taşır** — iki motorun gerçek tamamlanma sırası OS thread zamanlamasına bağlı hale gelir; bu, `ExecutionProvenance.engine_call_sequence`'in (Bölüm 43) HER ZAMAN aynı olması gerektiği iddiasıyla (Bölüm 29) potansiyel çelişki yaratır.
3. **Hata/cancellation/reuse/test mantığı gereksiz karmaşıklaşır** — paralel dallardan biri `FAILED` olduğunda diğerinin ne zaman durdurulacağı, cancellation sinyalinin paralel çağrılar arasında nasıl gözlemleneceği gibi sorular, sıralı bir modelde HİÇ ORTAYA ÇIKMAZ.

**FS_BALANCE_SHEET/FS_INCOME_STATEMENT** ve **EXECUTIVE_REPORT/DASHBOARD** çiftleri arasında GERÇEKTEN bir DAG kenarı olmadığı (Bölüm 4) doğrudur — bu, **teorik bir gelecek-optimizasyon fırsatıdır**, ama v1 implementasyon planına (Bölüm 73) DAHİL EDİLMEMİŞTİR. Eğer gelecekte gerçek Docker ölçümleri (Bölüm 68) bu iki çiftin paralelleştirilmesinin ANLAMLI bir kazanç sağladığını gösterirse, bu, saf Orchestrator'ın KENDİSİNDE değil, onu saran bir **workflow-runner katmanında** (Bölüm 57) ele alınmalıdır — sıralı çalıştırma sözleşmesi, `run_orchestration()`'ın v1 kapsamındaki TEK davranışıdır.

---

## 8. Sequential Zorunluluklar (Madde 8) — REVİZE

v1'de **TÜM** motor çağrıları sıralıdır — `RATIO → BENCHMARK → HEALTH_SCORE → CREDIT_SCORE → RECOMMENDATION → EXECUTIVE_REPORT → DASHBOARD → RENDER_CONTRACT`. Bölüm 7'nin kaldırdığı paralellik nedeniyle, "hangi çiftler paralel olabilirdi" ayrımı artık yalnızca TARİHSEL/gelecek-referans niteliğindedir.

**"Aynı motor aynı run içinde sebepsiz iki kez çağrılamaz" ilkesi (bağlayıcı, v1'den değişmedi):** Orchestrator, `RecommendationResult`'ı Executive Report VE Dashboard için **bir kez** üretip aynı obje referansıyla her ikisine de taşır.

---

## 9. Failure Propagation (Madde 9) — REVİZE

Bölüm 2.1.10'daki sınıflandırmaya dayanarak, iki farklı "başarısızlık" ekseni:

**Eksen A — Status-tabanlı derecelenme:** Bir motor kendi status alanını dereceli bir değere ayarlar ama **yine de bir sonuç nesnesi döner**. Orchestrator: (a) `PerEngineExecutionRecord`'u `DEGRADED` işaretler (Bölüm 9.1'deki TAM eşleme tablosuna göre), (b) downstream'i YİNE DE çağırır.

**Eksen B — İstisna-tabanlı sözleşme ihlali:** Bir motor istisna fırlatırsa, downstream'e hiçbir sonuç geçirilemez; o motor ve bağımlıları `FAILED`/`SKIPPED` olur.

### 9.1 Tam İnner-Status → EngineExecutionStatus Eşleme Tablosu (Madde 6'nın genişletilmiş hali — denetim bulgusu F2'nin kök-neden çözümü)

Bu tablo, v1'deki TEK örnekli ("INSUFFICIENT_DATA → DEGRADED") eksik anlatımın yerine geçen, **eksiksiz, her motor için her olası iç durumu kapsayan** kesin sözleşmedir. Implementasyon, bu tablodaki HER satırı birebir uygulamak ve test etmek (Bölüm 67) ZORUNDADIR.

| Motor | İç durum | `EngineExecutionStatus` | Gerekçe |
|---|---|---|---|
| Financial Statements (BS veya IS, ayrı ayrı) | `AnalysisStatus.COMPLETED` | `COMPLETED` | Normal üretim |
| Financial Statements (BS veya IS, ayrı ayrı) | `AnalysisStatus.FAILED` (TEK motor) | **`DEGRADED`** | Bu FS alt-motoru başarısız oldu AMA `any_of` semantiği (Bölüm 3) sayesinde RATIO diğerinin sonucuyla yine de çağrılabilir — bu motorun KENDİSİ "sonuç üretemedi" ama run'ın geri kalanını SKIP ETTİRMEZ, bu yüzden FAILED değil DEGRADED sınıflandırılır |
| Financial Statements — **her ikisi de** `FAILED` | (iki kayıt birden `DEGRADED`) | RATIO ayrıca `SKIPPED` olur, run `PARTIALLY_COMPLETED` | Bölüm 3'teki `any_of` kuralı: ikisi de result_json=None ise RATIO çağrılmaz |
| Ratio | Tüm oranlar `"not_calculable"` | **`DEGRADED`** | Motor istisna üretmedi ama hiçbir anlamlı değer hesaplanamadı |
| Ratio | En az bir oran `"calculated"` | `COMPLETED` | Kısmi de olsa anlamlı içerik üretildi |
| Benchmark | Tüm girdiler `"not_calculable"` | **`DEGRADED`** | — |
| Benchmark | En az bir oran `"evaluated"` | `COMPLETED` | — |
| Health Score | `COMPUTED` | `COMPLETED` | — |
| Health Score | `HARD_FAIL_CAPPED` | **`DEGRADED`** | Skor üretildi ama bir hard-fail kuralıyla sınırlandı |
| Health Score | `INSUFFICIENT_DATA` | **`DEGRADED`** | `final_score=None`, ama nesne geçerli |
| Credit Score | `COMPUTED` | `COMPLETED` | — |
| Credit Score | `HARD_FAIL_CAPPED` | **`DEGRADED`** | — |
| Credit Score | `INSUFFICIENT_DATA` | **`DEGRADED`** | — |
| Recommendation | `COMPUTED` | `COMPLETED` | — |
| Recommendation | **`NO_RECOMMENDATIONS_TRIGGERED`** | **`COMPLETED`** (DEĞİL DEGRADED) | Motorun kendi docstring'i: "veri yeterli, hiçbir kural tetiklenmedi (şirket sağlıklı)" — bu OLUMLU bir sonuçtur, veri eksikliği değildir |
| Recommendation | `INSUFFICIENT_DATA` | **`DEGRADED`** | — |
| Recommendation | `SCHEMA_INCOMPATIBLE` | **`DEGRADED`** | Yapı okunabilir, içerik bastırılmış |
| Recommendation | `VERSION_MISMATCH` | **`DEGRADED`** | — |
| Executive Report | `COMPUTED` | `COMPLETED` | — |
| Executive Report | `SCHEMA_INCOMPATIBLE` | **`DEGRADED`** | `sections=()`, ama nesne geçerli |
| Executive Report | `VERSION_MISMATCH` | **`DEGRADED`** | — |
| Dashboard | `is_compatible=True` | `COMPLETED` | — |
| Dashboard | `is_compatible=False` | **`DEGRADED`** | `widgets=()`, ama nesne geçerli |
| Render Contract | Başarılı nesne dönüşü | `COMPLETED` | **Bu motorun kendi bir computation-status'u YOKTUR — `DEGRADED` durumu YAPISAL OLARAK MEVCUT DEĞİLDİR** |
| Render Contract | `InvalidReportResultError` fırlatıldı | `FAILED` | Eksen B — sözleşme ihlali |

**Kesin kural (yeni invariant):** `EngineExecutionStatus.DEGRADED`, yalnızca motorun KENDİ bir iç durumu (enum değeri veya `is_compatible` bayrağı) olduğunda üretilebilir. Render Contract gibi böyle bir iç durumu OLMAYAN motorlar için Orchestrator asla `DEGRADED` üretmez — yalnızca `COMPLETED`/`FAILED`/`SKIPPED`/`REUSED` arasında seçim yapar.

---

## 10. RunStatus Modeli — 5 Değerli Kapalı Enum (Madde 10) — TAMAMEN YENİDEN YAZILDI

**Denetim bulgusu F1'in kök-neden çözümü.** v1'deki 4 değerli `RunStatus` (`FULLY_COMPLETED`/`PARTIALLY_COMPLETED`/`FAILED`/`CANCELLED`), TÜM motorlar `DEGRADED` olsa bile run'ı `FULLY_COMPLETED` sayabiliyordu — bu, dokümanın kendi "partial success sessizce başarılı sayılmaz" ilkesinin ihlaliydi. **Yeni, 5 değerli, kapalı enum:**

```
class RunStatus(str, Enum):
    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Kesin, bağlayıcı anlamlar:**

- **`FULLY_COMPLETED`:** İstenen (`requested_outputs`) TÜM motorlar `EngineExecutionStatus.COMPLETED` veya `REUSED` durumundadır — **hiçbir `DEGRADED`, `FAILED` veya `SKIPPED` YOKTUR.** Bu, "gerçekten hiçbir dereceleme/eksik veri olmadan, tam kaliteli bir sonuç" anlamına gelir.
- **`COMPLETED_WITH_DEGRADATIONS`:** Hiçbir `FAILED`/`SKIPPED` YOKTUR, ama en az bir motor `DEGRADED`'dir. Bu, "run engelsiz tamamlandı ama en az bir motor eksik/dereceli veriyle çalıştı — sonuç KULLANILABİLİR ama İHTİYATLA okunmalı" anlamına gelir.
- **`PARTIALLY_COMPLETED`:** En az bir motor `FAILED` VEYA bağımlılık nedeniyle `SKIPPED`'dir, ama en az bir anlamlı motor sonucu (herhangi bir `COMPLETED`/`DEGRADED`/`REUSED` kaydı) üretilmiştir.
- **`FAILED`:** İstenen HİÇBİR anlamlı sonuç üretilememiştir (örn. Financial Statements'ın ikisi de FAILED olup RATIO'nun SKIP olduğu ve zincirin tamamen boşaldığı durum) VEYA `OrchestrationRunRequest`'in kendisi geçersizdir (Bölüm 25 `INVALID_RUN_REQUEST`).
- **`CANCELLED`:** Çağrılar arasında `cancellation_probe` (Bölüm 15) `True` gözlemlenmiş ve plan tamamlanmadan durdurulmuştur.

**Yapısal garanti:** Bu 5 değer, ayrık ve kapsayıcıdır — bir run HER ZAMAN tam olarak BİRİNE düşer, hiçbir "dereceli ama etiketsiz" ara durum yoktur. `COMPLETED_WITH_DEGRADATIONS`'ın varlığı, "partial success sessizce başarılı sayılmaz" ilkesini artık **yapısal olarak** (bir enum değeri seviyesinde, prosa açıklamayla değil) garanti eder: bir çağıran, yalnızca `status == FULLY_COMPLETED` kontrolü yaparak "hiçbir dereceleme yok" güvencesini alabilir; `COMPLETED_WITH_DEGRADATIONS` gördüğünde bunun FARKLI bir durum olduğunu ZORUNLU olarak fark eder.

---

## 11. Retry Politikası (Madde 11)

v1'de Orchestrator'ın kendisi otomatik retry YAPMAZ (v1'den değişmedi — Bölüm 74 Açık Karar #3'te kilitlenmiştir: bu TAMAMEN gelecekteki bir workflow-runner'a aittir).

---

## 12. Idempotency (Madde 12) — REVİZE

Orchestrator çağrı-seviyesinde idempotenttir: aynı `run_id` + aynı `request_fingerprint` (Bölüm 41 — **YENİ**, v1'deki yalnızca "aynı girdiler" ifadesinin somut, doğrulanabilir karşılığı) ile iki kez çağrıldığında, bit-bir aynı `OrchestrationRunResult`'ı üretir (BUSINESS_PAYLOAD_DETERMINISM ekseninde, Bölüm 29). `run_id` aynı ama `request_fingerprint` FARKLIYSA, bu artık **sessizce idempotent bir tekrar DEĞİL, açık bir hata durumudur** (Bölüm 41, `INVALID_RUN_REQUEST`).

---

## 13. Re-run Davranışı (Madde 13) — REVİZE

1. **Temiz re-run:** Önceki sonuç sağlanmadı — Orchestrator DAG'ı baştan çalıştırır.
2. **Kısmi re-run / resume:** Çağıran, `PreviousExecutionSnapshot`'ı (Bölüm 14 — v1'deki ağır `previous_run_result: OrchestrationRunResult` yerine geçen HAFİF sözleşme) sağlar. Orchestrator, snapshot'taki her kaydı Bölüm 31'deki (fingerprint + versiyon) şartlara göre değerlendirir; şartları sağlayanlar `REUSED`, sağlamayanlar yeniden çalıştırılır.

---

## 14. Resume/Recovery (Madde 14) — REVİZE: `PreviousExecutionSnapshot`

**Denetim bulgusu R3'ün kök-neden çözümü.** v1'de `OrchestrationRunRequest.previous_run_result: OrchestrationRunResult | None` alanı, request tipini bir ÖNCEKİ result tipine bağımlı kılıyordu (gereksiz coupling) ve TÜM önceki sonucu (potansiyel olarak büyük, iç içe geçmiş nesneler) bellekte taşımayı gerektiriyordu. **Yeni, hafif, tek yönlü sözleşme:**

```
@dataclass(frozen=True)
class PreviousExecutionSnapshot:
    previous_run_id: str
    request_fingerprint: str                          # Bölüm 41
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    engine_snapshots: "tuple[PreviousEngineSnapshot, ...]"

@dataclass(frozen=True)
class PreviousEngineSnapshot:
    engine_code: "EngineCode"
    execution_status: "EngineExecutionStatus"
    engine_schema_version_used: "str | None"
    engine_model_version_used: "str | None"
    input_fingerprint: str
    fingerprint_schema_version: str
    result_ref: "Any | None"                           # yalnızca reuse edilecekse gerçek nesne referansı
```

`OrchestrationRunRequest` artık `previous_run_result` yerine `previous_execution_snapshot: PreviousExecutionSnapshot | None` taşır (Bölüm 19). **Bu snapshot'ın NEREDEN geldiği (bir önceki `OrchestrationRunResult`'tan mı türetildiği, yoksa bir persistence-adapter'ın DB'den mi okuduğu) Orchestrator'ın kapsamı DIŞINDADIR** — Orchestrator yalnızca sağlanan snapshot'ı, Bölüm 31'deki reuse şartlarına göre değerlendirir.

**Version-uyum kuralı:** Bölüm 31/41'e bkz. — artık YALNIZCA versiyon değil, versiyon + fingerprint BİRLİKTE kontrol edilir.

---

## 15. Cancellation (Madde 15) — TAMAMEN YENİDEN YAZILDI: `cancellation_probe`

**Denetim bulgusu C1'in kök-neden çözümü.** v1'de `cancellation_token: Callable[[], bool] | None`, `OrchestrationRunRequest` (frozen dataclass, iddia edilen "serileştirilebilir" bir sözleşme) İÇİNDE bir alandı — bir Python `Callable`/closure JSON'a serileştirilemez, bu da TÜM request'i queue-hazır olmaktan çıkarıyordu.

**Yeni imza (Bölüm 60 ile tutarlı):**

```
run_orchestration(
    request: OrchestrationRunRequest,
    *,
    cancellation_probe: "Callable[[], bool] | None" = None,
    timing_probe: "TimingProbe | None" = None,     # Bölüm 45
) -> OrchestrationRunResult
```

`cancellation_probe` artık `OrchestrationRunRequest`'in bir ALANI DEĞİL, `run_orchestration()`'a **ayrı, process-local bir çağrı parametresidir.** Bu, şunu garanti eder: `OrchestrationRunRequest`'in KENDİSİ (Bölüm 19), Callable içermez, tamamen serileştirilebilir kalır; `cancellation_probe` hiçbir queue payload'ına GİRMEZ — yalnızca AYNI process içinde, DOĞRUDAN Python çağrısıyla kullanılabilir.

**Davranış (v1'den değişmedi):** Orchestrator, her motor çağrısından ÖNCE `cancellation_probe()` çağrılabilirse kontrol eder; `True` dönerse DAG'ın geri kalanı `SKIPPED (cancelled)` olur, run `RunStatus.CANCELLED` döner. **Kesin sınır (v1'den değişmedi):** Orchestrator, ÇALIŞMAKTA OLAN bir motor çağrısını KESEMEZ — cancellation yalnızca motor çağrıları ARASINDAKİ noktalarda etkilidir.

---

## 16. Timeout — v1'den Çıkarıldı (Madde 16) — TAMAMEN YENİDEN YAZILDI

**Denetim bulgusu C2'nin kök-neden çözümü.** v1'deki `max_run_duration_seconds` alanı ve `TIMEOUT_EXCEEDED` hata kategorisi **v1'den TAMAMEN ÇIKARILMIŞTIR.**

**Gerekçe:** Bölüm 15'in kendi kesin sınırı — Orchestrator çalışmakta olan bir motor çağrısını kesemez — bir "run-seviyeli timeout" sözleşmesini YAPISAL OLARAK ANLAMSIZ kılar: eğer TEK bir motor çağrısı (patolojik biçimde) uzun sürerse, bir zaman aşımı sözleşmesi bunu DURDURAMAZ; yalnızca ÇAĞRILAR ARASINDA kontrol edilebilir, tıpkı cancellation gibi — ama bu durumda "timeout" ismi, "bu süreyi aşarsam kesilirim" beklentisini YARATIR ki bu beklenti YANLIŞTIR (yanıltıcı sözleşme). Gerçek bir timeout garantisi, ancak motor çağrısını KENDİ sürecinden/thread'inden ZORLA kesebilen bir mekanizma (process isolation, sinyal-tabanlı kesme) ile sağlanabilir — bu, saf, senkron, in-process bir Orchestrator'ın DEĞİL, bir **workflow-runner/process-izolasyon katmanının** sorumluluğudur (Bölüm 57).

v1, YALNIZCA Bölüm 15'teki `cancellation_probe` noktalarını destekler — bu, "zaman aşımı" değil, "çağıranın İSTEĞE BAĞLI olarak, çağrılar arasında durdurabilmesi"dir; ikisi FARKLI garantilerdir ve doküman bunları artık KARIŞTIRMAZ.

`OrchestrationErrorCategory.TIMEOUT_EXCEEDED` (Bölüm 25), bu nedenle **v1'den kaldırılmıştır**; gelecekte gerçek bir process-izolasyon katmanı eklenirse, o katmanın KENDİ hata taksonomisinde yeniden değerlendirilebilir (`future-reserved`, bu dokümanın kapsamı dışında).

---

## 17. Circuit Breaker Gerekip Gerekmediği (Madde 17)

Gerekmiyor, v1 kapsamında (v1'den değişmedi — motorlar I/O yapmayan saf fonksiyonlardır, dış servis yoktur).

---

## 18. Engine Invocation Spec (Madde 18) — REVİZE: `callable_ref` KALDIRILDI

**Denetim bulgusu H1'in kök-neden çözümü.** v1'deki `EngineInvocationSpec.callable_ref: str` alanı, çalışma zamanında `importlib`/`getattr` ile çözülmesi gereken bir string'di — bu, Architecture Book §18'in *"eval/exec veya dinamik getattr-tabanlı string-den-fonksiyon-çözme gibi dolaylı dispatch mekanizmaları kullanılmaz"* kuralını DOĞRUDAN ihlal ediyordu.

**Yeni model — metadata ile executable dispatch KESİN OLARAK AYRILMIŞTIR:**

```
@dataclass(frozen=True)
class EngineInvocationSpec:
    engine_code: "EngineCode"
    dependency: "DependencyRequirement"          # Bölüm 3
    produces: str                                 # örn. "HealthScoreResult" -- yalnızca dokümantasyon/tip etiketi
    is_critical: bool                             # Bölüm 28
    # NOT: callable_ref YOKTUR. Çağrılabilir referans, TAMAMEN AYRI bir
    # yapı olan ORCHESTRATOR_ENGINE_DISPATCH'te (Bölüm 36) tutulur.
```

`EngineInvocationSpec`, artık YALNIZCA **metadata** (bağımlılık ilişkisi, kritiklik, üretilen tip adı) taşır — hiçbir çalıştırılabilir referans içermez. Gerçek callable bağlama, Bölüm 36'daki `ORCHESTRATOR_ENGINE_DISPATCH` sözlüğünde, **import-zamanında, doğrudan Python fonksiyon referanslarıyla** yapılır.

---

## 19. Orchestrator Input/Output Contract (Madde 19) — REVİZE

```
@dataclass(frozen=True)
class OrchestrationRunRequest:
    run_id: str                                          # ÇAĞIRAN sağlar
    correlation_id: "str | None"                          # ÇAĞIRAN sağlar
    generated_at: "str | None"                             # ÇAĞIRAN sağlar
    requested_outputs: "tuple[EngineCode, ...]"
    engine_inputs: "EngineRawInputs"                       # content/filename/trial_balance_result/dönem tarihleri/vb.
    run_options: "OrchestrationRunOptions"                 # rapor tipi, dashboard tipi, locale, industry_code, company_size_bucket, tenant_id, vb.
    previous_execution_snapshot: "PreviousExecutionSnapshot | None"   # Bölüm 14 (ESKİ previous_run_result YERİNE)
    # NOT: cancellation_token BURADA YOKTUR (Bölüm 15) -- ayrı çağrı parametresidir.
    # NOT: max_run_duration_seconds BURADA YOKTUR (Bölüm 16) -- v1'den çıkarılmıştır.
```

**Serileştirme sözleşmesi (yeni, açık madde):** `OrchestrationRunRequest`'in TÜM alanları (yukarıdakiler) sade veri (`str`, `tuple`, iç içe frozen dataclass) olduğundan, bu nesne **tamamen JSON-serileştirilebilirdir** — gelecekte bir queue-tabanlı çalıştırıcı bu nesneyi doğrudan bir mesaj payload'ı olarak taşıyabilir. `cancellation_probe`/`timing_probe` (Bölüm 15/45) bu sözleşmenin DIŞINDA, yalnızca `run_orchestration()`'ın process-local çağrı parametreleridir — **hiçbir zaman serileştirilmesi/kuyruğa konması beklenmez.**

**Çıktı sözleşmesi:** Bölüm 23.

---

## 20. Immutable Dataclass Yapısı (Madde 20)

Architecture Book §7 ile birebir (v1'den değişmedi): TÜM yeni veri yapıları `@dataclass(frozen=True)`, koleksiyonlar `tuple`. Orchestrator hiçbir motor sonucunu sarmalamaz/kopyalamaz.

---

## 21. ExecutionStatus Enum'ları (Madde 21) — REVİZE

```
class EngineExecutionStatus(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    DEGRADED = "degraded"            # bkz. Bölüm 9.1 TAM eşleme tablosu
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"

class RunStatus(str, Enum):          # bkz. Bölüm 10 -- TAM anlamlarıyla
    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

`EngineExecutionStatus`'un `COMPLETED`/`DEGRADED` ayrımı, artık Bölüm 9.1'deki EKSİKSİZ tabloya göre türetilir — v1'deki tek-örnekli, eksik anlatım YERİNE geçmiştir.

---

## 22. Per-Engine Execution Record (Madde 22) — REVİZE: Fingerprint Alanları, Timing Kaldırıldı

**Denetim bulgusu V1 ve D3'ün kök-neden çözümü.** v1'deki tek `engine_version_used: str` alanı KALDIRILMIŞTIR (schema/model version'ı birbirine karıştırıyordu); `started_at_offset_ms`/`duration_ms` (zamanlama) alanları da KALDIRILMIŞTIR (Bölüm 45'e taşındı).

```
@dataclass(frozen=True)
class PerEngineExecutionRecord:
    engine_code: "EngineCode"
    status: "EngineExecutionStatus"
    result: "EngineResultEnvelope | None"          # Bölüm 23 -- Any DEĞİL, tipli zarf
    inner_status_value: "str | None"                # motorun kendi status'unun .value'su (gözlemlenebilirlik)
    error: "StructuredError | None"                 # yalnızca FAILED ise (Bölüm 25)
    dependency_engine_codes: "tuple[EngineCode, ...]"
    engine_schema_version_used: "str | None"        # ESKİ tek engine_version_used YERİNE (V1 bulgusu)
    engine_model_version_used: "str | None"
    input_fingerprint: str                          # Bölüm 41
    fingerprint_schema_version: str                 # Bölüm 41
    # NOT: started_at_offset_ms / duration_ms BURADA YOKTUR -- bkz. Bölüm 45 PerEngineTelemetry.
```

---

## 23. Run-Level Result Sözleşmesi (Madde 23) — REVİZE: Tek Source of Truth

**Denetim bulgusu I1'in kök-neden çözümü.** v1'de `OrchestrationRunResult`, hem `engine_records` (her biri kendi `result_ref: Any`'siyle) HEM DE ayrı adlandırılmış alanlar (`health_score_result`, `credit_score_result`, vb.) taşıyordu — aynı nesne İKİ yoldan erişilebilirdi, bu da tutarsızlık riski yaratıyordu.

**Yeni model:**

```
@dataclass(frozen=True)
class EngineResultEnvelope:
    engine_code: "EngineCode"
    result_kind: str                    # örn. "HealthScoreResult" -- tip etiketi, doğrulama için
    result: "Any"                       # gerçek motor nesnesi (dict veya frozen dataclass), değiştirilmeden

@dataclass(frozen=True)
class OrchestrationRunResult:
    run_id: str
    correlation_id: "str | None"
    generated_at: "str | None"
    status: "RunStatus"                                    # Bölüm 10
    engine_records: "tuple[PerEngineExecutionRecord, ...]"  # TEK SOURCE OF TRUTH
    warnings: "tuple[dict[str, Any], ...]"
    structured_errors: "tuple[StructuredError, ...]"
    execution_provenance: "ExecutionProvenance"
    input_version_inventory: "dict[str, str]"
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    request_fingerprint: str
    # NOT: health_score_result / credit_score_result / recommendation_result /
    # executive_report_result / dashboard_snapshot / render_contract_preview
    # BURADA AYRI ALANLAR OLARAK YOKTUR -- bkz. aşağıdaki typed accessor'lar.
```

**Tip güvenli erişim (duplicate state OLMADAN):** `OrchestrationRunResult` üzerinde, `engine_records`'tan arama yapan SAF yardımcı fonksiyonlar tanımlanır — bunlar hiçbir YENİ state SAKLAMAZ, yalnızca `engine_code` + `result_kind` doğrulaması yapıp mevcut kaydı döndürür:

```
def get_health_score_result(run_result: OrchestrationRunResult) -> "HealthScoreResult | None": ...
def get_credit_score_result(run_result: OrchestrationRunResult) -> "CreditScoreResult | None": ...
def get_recommendation_result(run_result: OrchestrationRunResult) -> "RecommendationResult | None": ...
def get_executive_report_result(run_result: OrchestrationRunResult) -> "ExecutiveReportResult | None": ...
def get_dashboard_snapshot(run_result: OrchestrationRunResult) -> "DashboardSnapshot | None": ...
def get_render_contract_preview(run_result: OrchestrationRunResult) -> "RenderContractPreview | None": ...
```

Her fonksiyon: (1) ilgili `engine_code`'a sahip `PerEngineExecutionRecord`'u `engine_records`'tan bulur, (2) kaydın `result` alanındaki `EngineResultEnvelope.result_kind`'ın BEKLENEN tiple eşleştiğini doğrular (eşleşmezse `TypeError`/`ValueError` fırlatır — yanlış motor/yanlış tip asla sessizce döndürülmez), (3) `envelope.result`'u döndürür. **Kesin kural: aynı sonuç, hiçbir koşulda iki ayrı depolama alanında tutulmaz.**

---

## 24. Warning/Error Modeli (Madde 24)

v1'den değişmedi (Architecture Book §13 ile birebir) — bir motor `DEGRADED` olsa bile downstream YİNE DE çağrılır, sonuç sessizce run'dan çıkarılmaz.

---

## 25. Structured Error Taxonomy (Madde 25) — REVİZE: Güvenlik Kuralları, `TIMEOUT_EXCEEDED` Kaldırıldı

```
class OrchestrationErrorCategory(str, Enum):
    ENGINE_CONTRACT_VIOLATION = "engine_contract_violation"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VERSION_INCOMPATIBLE_ON_REUSE = "version_incompatible_on_reuse"
    FINGERPRINT_MISMATCH_ON_REUSE = "fingerprint_mismatch_on_reuse"   # YENİ -- Bölüm 41
    INVALID_RUN_REQUEST = "invalid_run_request"
    CANCELLED = "cancelled"
    # NOT: TIMEOUT_EXCEEDED KALDIRILDI (Bölüm 16)

@dataclass(frozen=True)
class StructuredError:
    category: "OrchestrationErrorCategory"
    engine_code: "EngineCode | None"
    message_tr: str                            # bkz. güvenlik kuralları aşağıda
    original_exception_type: "str | None"       # yalnızca sınıf adı, örn. "ValueError"
    # NOT: stack trace veya ham exception mesajı BURADA TAŞINMAZ (aşağıya bkz.)
```

**Güvenlik/sanitization kuralları (YENİ, denetim Bölüm 17'nin kök-neden çözümü):**

1. `message_tr`, YALNIZCA production-güvenli, ÖNCEDEN NORMALİZE EDİLMİŞ bir Türkçe metin olabilir — motorun ham exception mesajı (`str(exc)`) BİREBİR TAŞINMAZ; Orchestrator, her `OrchestrationErrorCategory` için SABİT, ÖNCEDEN YAZILMIŞ bir şablon mesaj kullanır (örn. `ENGINE_CONTRACT_VIOLATION` için her zaman "İlgili motor çağrısı geçersiz bir sözleşme kullandı" gibi sabit bir metin — motorun `ValueError`'ının TAM İÇERİĞİ değil).
2. `original_exception_type`, YALNIZCA `type(exc).__name__` (örn. `"ValueError"`) taşır — asıl exception nesnesi, argümanları veya mesajı ASLA taşınmaz.
3. **Stack trace, `OrchestrationRunResult`'a HİÇBİR ŞEKİLDE eklenmez.** Teşhis amaçlı tam stack trace gerekiyorsa, bu YALNIZCA Orchestrator'ın dışına, güvenli erişimli ayrı bir logging/telemetry sink'ine (Bölüm 50, Orchestrator'ın kendisi tarafından yazılmaz, çağıranın sorumluluğunda) gidebilir — bu, iş sonucu sözleşmesinin bir parçası DEĞİLDİR.
4. Dosya adı, belge içeriği, hesap numarası, müşteri/şirket adı gibi HERHANGİ bir hassas/kişisel/finansal veri, `StructuredError`'ın hiçbir alanına YAZILAMAZ — bu, gelecekte yeni bir motor exception mesajı eklenirken de KORUNMASI gereken kalıcı bir kısıt olarak buraya kaydedilmiştir.

---

## 26. Dependency Failure Davranışı (Madde 26) — REVİZE: `any_of`/`all_of`

Bir motorun `all_of` kümesindeki HERHANGİ BİR bağımlılığı `SKIPPED`/`FAILED` olduysa, o motor **çağrılmaz**, `SKIPPED` olur. `any_of` kümesindeki bağımlılıklardan **EN AZ BİRİ** `COMPLETED`/`DEGRADED`/`REUSED` ise motor ÇAĞRILIR (Bölüm 3) — yalnızca `any_of` kümesinin TAMAMI `FAILED`/`SKIPPED` ise motor `SKIPPED` olur. `optional` kümesindeki bağımlılıklar hiçbir zaman SKIP tetiklemez — eksikse motora `None` geçirilir.

**Önemli ayrım (Bölüm 9 Eksen A ile karıştırılmamalı):** Bir upstream'in `DEGRADED` olması downstream'i SKIP ETTİRMEZ — yalnızca upstream'in GERÇEKTEN sonuç üretemediği (`FAILED`, ilgili `all_of`/`any_of` kümesi tamamen karşılanamadığı) durumda SKIP tetiklenir.

---

## 27. Optional Engine Failure Davranışı (Madde 27)

v1'den değişmedi — Executive Report/Dashboard birbirinden bağımsızdır; biri `FAILED` olursa diğerini etkilemez, run en kötü ihtimalle `PARTIALLY_COMPLETED` olur (artık Bölüm 10'daki 5 değerli modelle).

---

## 28. Critical Engine Failure Davranışı (Madde 28) — REVİZE

`any_of`/`all_of` modeliyle netleşen hâliyle: Financial Statements'ın İKİSİ de `FAILED` olması, RATIO'nun (ve transitif olarak TÜM downstream'in) `SKIPPED` olmasına yol açan TEK gerçek "hard failure" noktasıdır (Bölüm 3'te KİLİTLENMİŞ karar). Recommendation'ın `ValueError`/`RuntimeError`'ı da bir Eksen B örneğidir — ama bu, orchestrator'ın KENDİ çağrı hatasını (yanlış tip geçirme, invariant ihlali) temsil eder, veri kalitesi sorunu değildir.

---

## 29. Determinizm — İki Ayrı Property (Madde 29) — TAMAMEN YENİDEN YAZILDI

**Denetim bulgusu D2/D3'ün kök-neden çözümü.** v1'deki tek, aşırı-genel determinizm iddiası ("aynı girdiler → bit-bir aynı sonuç") iki AYRI property'ye bölünmüştür:

**`BUSINESS_PAYLOAD_DETERMINISM`:** Aynı `engine_inputs` + aynı `run_options` + aynı `requested_outputs` + aynı motor schema/model versiyonları + aynı `execution_plan_version` + aynı reuse/snapshot kararları verildiğinde, TÜM motor sonuçlarının (`engine_records[i].result`) finansal/iş içeriği bit-bir aynıdır — `run_id`/`correlation_id`/`generated_at` FARKLI olsa bile.

**`FULL_RESULT_DETERMINISM`:** Yukarıdakine EK olarak `run_id` + `correlation_id` + `generated_at` + `request_fingerprint` de aynıysa, TÜM `OrchestrationRunResult` (zamanlama/telemetry alanları HARİÇ, Bölüm 45) bit-bir aynıdır.

**Netleştirme (v1'in belirsiz bıraktığı nokta artık açık):** Aynı finansal girdilerle ama FARKLI `run_id`/`generated_at` ile iki çağrı, `BUSINESS_PAYLOAD_DETERMINISM` anlamında AYNI motor sonuçlarını üretir, ama TAM `OrchestrationRunResult` nesnesi (run_id/generated_at farklı olduğu için) DOĞAL OLARAK farklıdır — bu bir determinizm İHLALİ DEĞİLDİR, `FULL_RESULT_DETERMINISM`'in tanımı gereği BEKLENEN bir farktır. Telemetry (Bölüm 45) HER İKİ property'nin de kapsamı DIŞINDADIR.

DAG'ın çalıştırma sırası (Bölüm 6) artık TAMAMEN sıralı ve DAG'dan türetilmiş (Bölüm 37) olduğundan, registry insertion-order'a bağlı değildir — bu da her iki determinizm property'sinin de önkoşuludur.

---

## 30. Read-Only, No-Recompute ve Single-Source-of-Truth Invariant'ları (Madde 30) — REVİZE

Architecture Book §10'a paralel, ÜÇ invariant (üçüncüsü YENİ):

**`ORCHESTRATOR_NO_RECOMPUTE_INVARIANT`:** v1'den değişmedi — her `engine_code` için gerçek çağrı sayısı `unittest.mock.patch` ile `call_count == (1 REUSED değilse, 0 REUSED/SKIPPED ise)` doğrulanır.

**`ORCHESTRATOR_READ_ONLY_INVARIANT`:** v1'den değişmedi — `envelope.result is <motorun döndürdüğü orijinal nesne>` (obje kimliği) korunur.

**`ORCHESTRATOR_SINGLE_SOURCE_OF_TRUTH_INVARIANT` (YENİ — denetim bulgusu I1'in kök-neden çözümünün test-seviyesi karşılığı):** Bir motorun sonucuna erişmenin TEK yolu `engine_records` (veya Bölüm 23'teki typed accessor'lar, ki onlar da `engine_records`'tan okur) olduğundan, bu invariant otomatik olarak sağlanır — `OrchestrationRunResult`'ta İKİNCİ bir depolama alanı YAPISAL OLARAK YOKTUR, dolayısıyla "iki temsilin birbirinden ayrışması" riski TASARIM GEREĞİ ortadan kalkmıştır (test-seviyesinde ayrıca doğrulanır, Bölüm 67).

---

## 31. Upstream Result Reuse (Madde 31) — REVİZE: Fingerprint Şartları

**Denetim bulgusu R1/R2'nin kök-neden çözümü.** Bir motorun sonucu, YALNIZCA şu şartların **TAMAMI** sağlanırsa reuse edilebilir:

1. `engine_code` aynı.
2. Önceki kaydın `status`'u `COMPLETED` veya `DEGRADED` idi (ASLA `FAILED`/`SKIPPED` reuse edilmez).
3. `engine_schema_version_used` aynı.
4. `engine_model_version_used` aynı.
5. `fingerprint_schema_version` aynı.
6. **`input_fingerprint` aynı** (Bölüm 41 — YENİ, v1'de YOKTU).
7. O motora giden TÜM upstream bağımlılıkları da (transitif olarak) reuse edilebilir OLMALI VE onların `input_fingerprint`'leri de bu run'daki (yeniden hesaplanmış veya reuse edilmiş) haliyle TUTARLI olmalı — **eğer bir upstream, BU run'da fiilen yeniden hesaplandıysa (reuse edilmediyse), ondan sonraki HİÇBİR downstream motor, kendi versiyon/fingerprint'i eski haliyle eşleşse bile, ARTIK reuse EDİLEMEZ; zorunlu olarak yeniden hesaplanır** (yeni, kesin transitif-geçersizleştirme kuralı — R2'nin kök-neden çözümü).

Şartlardan biri sağlanmazsa motor **REUSED değil**, yeniden çalıştırılır.

**Aynı `run_id`, farklı `request_fingerprint` (Bölüm 41):** Bu durum sessizce reuse EDİLMEZ ve sessizce üzerine yazılmaz — `OrchestrationErrorCategory.INVALID_RUN_REQUEST` (veya daha spesifik `FINGERPRINT_MISMATCH_ON_REUSE`, Bölüm 25) ile **kesin olarak reddedilir.**

---

## 32. Global State Yasağı (Madde 32)

v1'den değişmedi — Architecture Book §19 ile birebir. `ENGINE_DEPENDENCY_REGISTRY` (Bölüm 35) ve `ORCHESTRATOR_ENGINE_DISPATCH` (Bölüm 36), "import-anında bir kez doldurulan, sonra salt-okunur" registry deseninin İSTİSNASI olarak module-level var olabilir.

---

## 33. Doğrudan Sorulan 14 Soruya Cevaplar (Madde 33) — REVİZE

**S1 — Financial Statements Engine olmadan Ratio Engine çalışabilir mi?**
Evet — ve artık bu, `DependencyRequirement(any_of=(FS_BALANCE_SHEET, FS_INCOME_STATEMENT))` ile AÇIKÇA, çelişkisiz modellenmiştir (Bölüm 3): FS'lerden EN AZ BİRİ sonuç ürettiyse RATIO çağrılır (diğerine `None` geçirilir); İKİSİ de `FAILED` ise RATIO `SKIPPED` olur (KİLİTLİ karar, Bölüm 3'teki metodolojik gerekçeyle).

**S2 — Benchmark Engine, Ratio Engine başarısızsa nasıl davranır?** v1 ile aynı — Ratio hiçbir zaman gerçek anlamda istisna fırlatmaz, yalnızca `DEGRADED` olabilir (Bölüm 9.1); Benchmark bunu YİNE DE alır ve kendi içinde derecelenir.

**S3 — Health Score ve Credit Score hangi sonuçlara bağımlıdır?** v1 ile aynı (Bölüm 2.1.4-2.1.5).

**S4 — Recommendation Engine hangi motorların başarısına bağlıdır?** v1 ile aynı (Bölüm 2.1.6), artık `all_of=(RATIO, BENCHMARK, HEALTH_SCORE, CREDIT_SCORE)` ile deklaratif modellenmiş.

**S5 — Executive Report hangi eksik girdilerle partial üretilebilir?** v1 ile aynı mantık (Bölüm 2.1.7), artık `all_of` ile (7 zorunlu girdi) modellenmiş — herhangi biri SKIP/FAILED ise Executive Report da SKIP olur.

**S6 — Dashboard hangi eksik girdilerle üretilebilir?** v1 ile aynı — `all_of=(HEALTH_SCORE, CREDIT_SCORE, RECOMMENDATION)`, `optional=(BENCHMARK,)`.

**S7 — Render Contract hangi aşamada çalışmalıdır?** v1 ile aynı — yalnızca Executive Report nesnesi üretildiyse (status ne olursa olsun) VE istendiyse, DAG'ın son (10.) adımı olarak.

**S8 — Bir motor failure sonrası run yeniden başlatıldığında hangi sonuçlar reuse edilir?**
Bölüm 31'deki 7 şartın TAMAMINI (versiyon + **fingerprint** + transitif tutarlılık) sağlayan kayıtlar reuse edilir; diğerleri yeniden çalıştırılır.

**S9 — Reuse edilen sonuçların version uyumu nasıl doğrulanır?**
Artık YALNIZCA versiyon değil: `engine_schema_version_used` + `engine_model_version_used` + `fingerprint_schema_version` + `input_fingerprint`'in HEPSİNİN eşleşmesiyle (Bölüm 31/41 — v1'deki tek-string kontrolünün YERİNE).

**S10 — Retry aynı sonucu iki kez persistence'a yazma riskini nasıl önler?**
v1 saf Orchestrator bu riski hiç TAŞIMAZ (DB'ye yazmaz). Gelecekteki adapter, `run_id` + `request_fingerprint` UNIQUE constraint/upsert deseniyle bunu çözmelidir (Bölüm 57 "at-least-once" netliğiyle) — bu KAPSAM DIŞI kalmaya devam eder, ama artık "aynı run_id farklı fingerprint" durumu Orchestrator seviyesinde KESİN REDDEDİLDİĞİ için (Bölüm 31) adapter'ın işi kolaylaşır.

**S11 — Saf orchestrator ile gerçek workflow runner nasıl ayrılmalıdır?** v1 ile aynı (Bölüm 56-57).

**S12 — v1 senkron mu, async mi olmalı?** **Senkron VE tamamen sıralı** (Bölüm 6/7/58 — paralellik de v1'den çıkarıldığı için bu cevap artık DAHA kesin).

**S13 — Queue mimarisi şimdiden tasarlanmalı mı?** Yalnızca hook (v1 ile aynı, Bölüm 59) — artık `OrchestrationRunRequest`'in GERÇEKTEN tamamen serileştirilebilir olduğu da AYRICA garanti edilmiştir (Bölüm 19, `cancellation_probe` çıkarıldığı için).

**S14 — Çok şirketli batch v1'de mi?** Hayır, sonraki milestone'da (v1 ile aynı, Bölüm 61).

---

## 34. Registry Tabanlı Engine Planı Gerekip Gerekmediği (Madde 33/34)

Evet, gereklidir (v1 ile aynı gerekçe) — ama artık TEK bir source-of-truth (`ENGINE_DEPENDENCY_REGISTRY`, Bölüm 35) üzerinden, ikinci bir elle-yazılmış plan OLMADAN (Bölüm 37).

---

## 35. Engine Dependency Registry (Madde 34) — REVİZE: Yalnızca Metadata

**Denetim bulgusu H1'in ikinci yarısı.** `ENGINE_DEPENDENCY_REGISTRY`, artık YALNIZCA bağımlılık METADATA'sı taşır — hiçbir çağrılabilir referans içermez:

```
ENGINE_DEPENDENCY_REGISTRY: "dict[EngineCode, EngineInvocationSpec]" = {
    EngineCode.FS_BALANCE_SHEET:    EngineInvocationSpec(FS_BALANCE_SHEET, DependencyRequirement((), (), ()), "BalanceSheetAnalysisOutcome", is_critical=True),
    EngineCode.FS_INCOME_STATEMENT: EngineInvocationSpec(FS_INCOME_STATEMENT, DependencyRequirement((), (), ()), "IncomeStatementAnalysisOutcome", is_critical=True),
    EngineCode.RATIO:               EngineInvocationSpec(RATIO, DependencyRequirement((), (FS_BALANCE_SHEET, FS_INCOME_STATEMENT), ()), "dict", is_critical=True),
    EngineCode.BENCHMARK:           EngineInvocationSpec(BENCHMARK, DependencyRequirement((RATIO,), (), ()), "dict", is_critical=True),
    EngineCode.HEALTH_SCORE:        EngineInvocationSpec(HEALTH_SCORE, DependencyRequirement((RATIO, BENCHMARK), (), ()), "HealthScoreResult", is_critical=True),
    EngineCode.CREDIT_SCORE:        EngineInvocationSpec(CREDIT_SCORE, DependencyRequirement((RATIO, BENCHMARK, HEALTH_SCORE), (), ()), "CreditScoreResult", is_critical=True),
    EngineCode.RECOMMENDATION:      EngineInvocationSpec(RECOMMENDATION, DependencyRequirement((RATIO, BENCHMARK, HEALTH_SCORE, CREDIT_SCORE), (), ()), "RecommendationResult", is_critical=True),
    EngineCode.EXECUTIVE_REPORT:    EngineInvocationSpec(EXECUTIVE_REPORT, DependencyRequirement((FS_BALANCE_SHEET, FS_INCOME_STATEMENT, RATIO, BENCHMARK, HEALTH_SCORE, CREDIT_SCORE, RECOMMENDATION), (), ()), "ExecutiveReportResult", is_critical=False),
    EngineCode.DASHBOARD:           EngineInvocationSpec(DASHBOARD, DependencyRequirement((HEALTH_SCORE, CREDIT_SCORE, RECOMMENDATION), (), (BENCHMARK,)), "DashboardSnapshot", is_critical=False),
    EngineCode.RENDER_CONTRACT:     EngineInvocationSpec(RENDER_CONTRACT, DependencyRequirement((EXECUTIVE_REPORT,), (), ()), "RenderContractPreview", is_critical=False),
}
```

**Kayıt anında doğrulanacak kurallar (Bölüm 4'ün checklist'iyle birlikte):** (a) her `all_of`/`any_of`/`optional` içindeki `EngineCode` registry'de var, (b) graf döngüsüz, (c) her `EngineCode` tam bir kez tanımlı, (d) düğüm/kenar sayıları Bölüm 4'teki sabit sayılarla (10/24/21/1/2) eşleşiyor.

---

## 36. Engine Dispatch Table (YENİ) — `ORCHESTRATOR_ENGINE_DISPATCH`

**Denetim bulgusu H1'in tam çözümü.** Gerçek, çağrılabilir motor fonksiyonları, `ENGINE_DEPENDENCY_REGISTRY`'den TAMAMEN AYRI, ikinci bir yapıda, **import-zamanında doğrudan fonksiyon referanslarıyla** bağlanır:

```
from app.engines.balance_sheet.service import analyze_balance_sheet
from app.engines.income_statement.service import analyze_income_statement
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.health_score.service import compute_financial_health_score
from app.engines.credit_score.service import compute_credit_score
from app.engines.recommendation.service import generate_recommendations
from app.engines.executive_reports.service import generate_executive_report
from app.engines.dashboards.service import generate_dashboard_snapshot
from app.engines.render_contract.service import preview_render_contract

ORCHESTRATOR_ENGINE_DISPATCH: "dict[EngineCode, Callable[..., Any]]" = {
    EngineCode.FS_BALANCE_SHEET:    analyze_balance_sheet,
    EngineCode.FS_INCOME_STATEMENT: analyze_income_statement,
    EngineCode.RATIO:               analyze_financial_ratios,
    EngineCode.BENCHMARK:           evaluate_benchmarks,
    EngineCode.HEALTH_SCORE:        compute_financial_health_score,
    EngineCode.CREDIT_SCORE:        compute_credit_score,
    EngineCode.RECOMMENDATION:      generate_recommendations,
    EngineCode.EXECUTIVE_REPORT:    generate_executive_report,
    EngineCode.DASHBOARD:           generate_dashboard_snapshot,
    EngineCode.RENDER_CONTRACT:     preview_render_contract,
}
```

**Kesin kurallar:**

- **`importlib`, `getattr` (dinamik/string-tabanlı), `eval`, `exec` KULLANILMAZ** — her callable, standart Python `import` ifadesiyle, MODÜL YÜKLEME ANINDA bağlanır (Architecture Book §18 ile TAM uyum).
- **Kayıt anında tamlık doğrulaması:** `ENGINE_DEPENDENCY_REGISTRY`'deki HER `EngineCode` için `ORCHESTRATOR_ENGINE_DISPATCH`'te KARŞILIK GELEN bir callable bulunmalıdır — bu, modül import edilirken (`assert set(ENGINE_DEPENDENCY_REGISTRY) == set(ORCHESTRATOR_ENGINE_DISPATCH)` türünden bir kontrolle) doğrulanır; eksik veya FAZLA bir `EngineCode` varsa import ANINDA reddedilir (uygulama hiç başlamaz).
- **Metadata (Bölüm 35) ile executable dispatch (bu bölüm) KESİN OLARAK AYRI iki yapıdır** — biri "hangi motor hangi motora bağımlı" sorusuna, diğeri "bu motoru GERÇEKTEN nasıl çağırırım" sorusuna cevap verir. Bu ayrım, testlerin `ORCHESTRATOR_ENGINE_DISPATCH`'teki TEK bir callable'ı (örn. `unittest.mock.patch` ile) sahtelemesini, `ENGINE_DEPENDENCY_REGISTRY`'nin bağımlılık metadata'sına HİÇ DOKUNMADAN mümkün kılar.
- **Process-local production wiring:** `ORCHESTRATOR_ENGINE_DISPATCH`, TAMAMEN process-içi bir bağlamadır — `OrchestrationRunRequest`/`OrchestrationRunResult` gibi serileştirilebilir sözleşmelerin PARÇASI DEĞİLDİR (Bölüm 19). Bir queue-tabanlı çalıştırıcı, `OrchestrationRunRequest`'i taşıyabilir ama `ORCHESTRATOR_ENGINE_DISPATCH`'i ASLA taşımaz — her worker process, kendi `ORCHESTRATOR_ENGINE_DISPATCH`'ini kendi import'larıyla oluşturur.

---

## 37. Execution Plan Derivation (Madde 35/36) — TAMAMEN YENİDEN YAZILDI

**Denetim bulgusu D1'in kök-neden çözümü.** v1'de HEM "registry'den türetilmeli" (Bölüm 34 ilkesi) HEM DE elle yazılmış bir `EXECUTION_PLAN_REGISTRY` sabiti (Bölüm 36 örneği) vardı — bu belirsizlik **kesin olarak çözülmüştür:**

**v1 kararı (KİLİTLİ, artık açık karar değil):**

- **`ENGINE_DEPENDENCY_REGISTRY` (Bölüm 35), TEK source of truth'tur.**
- **Execution plan, bu registry'den, HER ÇAĞRIDA (veya modül-yükleme anında bir kez) deterministik bir topological sort ile TÜRETİLİR** — elle yazılmış, registry'den bağımsız İKİNCİ bir "plan" sabiti (`EXECUTION_PLAN_REGISTRY` gibi) **v1'de YOKTUR.**
- **Tie-break kuralı (yeni, kesin):** Topological sort'ta birden fazla düğüm aynı "hazır" (tüm bağımlılıkları çözülmüş) durumdaysa, aralarındaki sıra **`EngineCode.value`'nun alfabetik sırasına** göre belirlenir — bu, insertion-order'dan TAMAMEN bağımsız, deterministik bir tie-break kuralıdır (Bölüm 4/69'un "insertion-order independence" iddiasının SOMUT, algoritmik karşılığı).
- Registry'ye motorlar hangi sırayla eklenirse eklensin (test senaryosu dahil), türetilen plan HER ZAMAN AYNIDIR.
- **Cache:** Plan çıktısı, performans için bir `immutable tuple` olarak ÖNBELLEĞE alınabilir (`@functools.lru_cache` veya modül-seviyeli bir sabit gibi), AMA bu cache HER ZAMAN `ENGINE_DEPENDENCY_REGISTRY`'den türetilmiş OLMALIDIR — cache, kendi başına BAĞIMSIZ bir ikinci kaynak DEĞİLDİR, yalnızca türetme sonucunun bir performans optimizasyonudur.
- **Kayıt anında reddedilenler:** Bilinmeyen bağımlılık (registry'de olmayan bir `EngineCode`'a referans), kendine-bağımlılık (`X`'in kendi `all_of`/`any_of`'unda `X` geçmesi), döngü — HEPSİ modül import edilirken (topological sort algoritması bir döngü/eksik düğüm bulduğunda) REDDEDİLİR.

**v1'de tamamen sıralı olduğu için (Bölüm 6/7), türetilen plan basit bir DÜZ SIRA (tuple of EngineCode) olur** — v1'deki "aşama" (stage) kavramı (paralel gruplar) artık YOKTUR; bu, Bölüm 7'nin kaldırdığı paralelliğin doğal bir sonucudur. Gelecekte paralellik eklenirse (workflow-runner katmanında), plan yapısı "aşamalar" biçimine genişletilebilir — ama bu v1'in kapsamı DIŞINDADIR.

---

## 38. Plan Versioning (Madde 36)

`execution_plan_version: str` (Bölüm 19/23), `ENGINE_DEPENDENCY_REGISTRY`'nin YAPISI (düğüm/kenar seti) değiştiğinde artırılır. Bölüm 37'nin artık türetilmiş-tek-kaynak modeli sayesinde, "plan'ın yapısı" ile "registry'nin yapısı" ARTIK AYNI ŞEYDİR — bu, v1'deki "plan schema vs strateji" ayrımını (D1 çözüldüğü için) BASİTLEŞTİRİR: v1'de paralellik/strateji kavramı olmadığından, `execution_plan_version` YALNIZCA registry'nin (düğüm/kenar/dependency-requirement) yapısal değişikliğini izler.

---

## 39. Schema Compatibility (Madde 37)

v1 ile aynı ilke — Orchestrator'ın KENDİ `OrchestrationRunResult`/plan sözleşmelerinin şeması, Architecture Book §9'daki 3 katmanlı modelle yönetilir; bu, motorların KENDİ ARALARINDAKİ uyumluluktan (Bölüm 2.1) AYRI bir eksendir.

---

## 40. Versiyon Alanları — Konsolide Tablo (YENİ) (Madde 38)

**Denetim bulgusu V1/V2'nin kök-neden çözümü.** v1'deki tek `engine_version_used: str` alanı ve dağınık versiyon-ekseni anlatımı, TEK bir konsolide tabloda toplanmıştır:

| Versiyon Ekseni | Nerede taşınır | Neyi izler | Ne zaman artırılır |
|---|---|---|---|
| `orchestration_schema_version` | `OrchestrationRunResult` | `OrchestrationRunResult`/`OrchestrationRunRequest`'in KENDİ alan yapısı | Bir alan eklenip/çıkarıldığında |
| `orchestration_model_version` | `OrchestrationRunResult` | Orchestrator'ın DAVRANIŞ mantığı (örn. reuse kuralı, status-eşleme tablosu değişirse) | Bölüm 9.1/31'deki kurallar değiştiğinde |
| `execution_plan_version` | `OrchestrationRunResult` | `ENGINE_DEPENDENCY_REGISTRY`'nin yapısı (Bölüm 38) | Yeni motor eklendiğinde/bağımlılık değiştiğinde |
| `fingerprint_schema_version` | `PerEngineExecutionRecord`, `EngineInputFingerprint` | Fingerprint'in NASIL hesaplandığı (Bölüm 41'deki canonical-JSON algoritması) | Hash algoritması/canonical-form kuralı değişirse |
| `engine_schema_version_used` (motor başına) | `PerEngineExecutionRecord` | O motorun kendi `*_schema_version`'ı (Architecture Book §8) | Motorun kendi schema'sı değiştiğinde (Orchestrator'ın kontrolü DIŞINDA, yalnızca GÖZLEMLENİR) |
| `engine_model_version_used` (motor başına) | `PerEngineExecutionRecord` | O motorun kendi `*_model_version`'ı | Motorun kendi hesaplama mantığı değiştiğinde (yalnızca GÖZLEMLENİR) |

**Kural:** `ENGINE_DEPENDENCY_REGISTRY`'ye yeni bir motor eklemek → `execution_plan_version` artar. Bir motorun KENDİ schema/model version'ı değişmesi → Orchestrator'ın HİÇBİR versiyonunu DEĞİŞTİRMEZ, yalnızca `engine_schema_version_used`/`engine_model_version_used` alanlarında GÖZLEMLENEN değer değişir (bu, reuse-red kararlarını tetikleyebilir, Bölüm 31).

---

## 41. Input Fingerprint Modeli (YENİ) (Madde 39/ilgili)

**Denetim bulgusu R1'in tam, kapsamlı çözümü.**

```
@dataclass(frozen=True)
class EngineInputFingerprint:
    engine_code: "EngineCode"
    fingerprint: str                       # SHA-256 hex digest
    fingerprint_schema_version: str

@dataclass(frozen=True)
class RequestFingerprint:
    request_fingerprint: str                # TÜM run'ın birleşik özeti (SHA-256 hex digest)
    engine_input_fingerprints: "tuple[EngineInputFingerprint, ...]"
```

**Her motorun fingerprint'i, YALNIZCA o motorun GERÇEKTEN tükettiği girdilerden türetilir** (bir motorun kullanmadığı bir alanın değişmesi, o motorun fingerprint'ini ETKİLEMEMELİDİR — bu, gereksiz reuse-red'lerini önler):

| Motor | Fingerprint girdisi |
|---|---|
| Financial Statements (her biri) | `content` (veya `trial_balance_result`) + `filename` + `prior_period_facts` |
| Ratio | Financial Statements'ın (kullanılan) `result_json`'larının fingerprint'leri + dönem tarihleri/ay sayısı |
| Benchmark | Ratio fingerprint'i + `industry_code`/`company_size_bucket` |
| Health Score | Ratio + Benchmark fingerprint'leri + `industry_code`/`company_size_bucket`/`tenant_id` |
| Credit Score | Ratio + Benchmark + Health Score fingerprint'leri + segment seçenekleri |
| Recommendation | Ratio + Benchmark + Health Score + Credit Score fingerprint'leri + segment seçenekleri |
| Executive Report | TÜM 7 gerçek upstream sonucunun fingerprint'leri + `report_type`/`optional_sections`/`locale`/`currency_display_policy`/`company_metadata`/`reporting_period_label_tr` |
| Dashboard | Health Score + Credit Score + Recommendation fingerprint'leri + (varsa) Benchmark fingerprint'i + `dashboard_type`/`company_metadata` |
| Render Contract | Executive Report fingerprint'i + `render_contract` (medium/kapasite tanımı) |

**Hash politikası (kesin, bağlayıcı):**

1. **Canonical, deterministic JSON temsili** — hash'lenecek her yapı önce canonical bir JSON string'e dönüştürülür.
2. **Key sıralaması ZORUNLU** — tüm dict anahtarları alfabetik sıraya konur (`json.dumps(..., sort_keys=True)` deseni).
3. **`Decimal` değerleri canonical string olarak** (örn. `str(Decimal(...))`, bilimsel gösterim/farklı ondalık basamak sayısı riskini önlemek için normalize edilmiş).
4. **Enum değerleri `.value` ile** (Python nesne repr'i değil).
5. **Tuple sırası KORUNUR** (sıra anlamlıdır, sıralanmaz).
6. **Set/map insertion-order fingerprint'i ETKİLEMEZ** (adım 2'nin doğal sonucu).
7. **Ham binary/dosya içeriği (`content: bytes`) için SHA-256** doğrudan bayt dizisi üzerinden hesaplanır.
8. **Hash algoritması: SHA-256** (tüm fingerprint'ler için tek, sabit algoritma).
9. **`fingerprint_schema_version` AYRI tutulur** — hash algoritması/canonical-form kuralı değişirse (örn. SHA-256'dan başka bir algoritmaya geçilirse), bu versiyon artar; eski fingerprint'ler yeni versiyonla KARŞILAŞTIRILAMAZ (otomatik reuse-red, Bölüm 31 madde 5).
10. **Secrets/credentials fingerprint kaynağına ASLA girmez** (zaten motor girdilerinde böyle bir alan yok, ama gelecekte eklenirse bu kural bağlayıcı kalır).
11. **Hassas ham veri fingerprint İÇİNDE TUTULMAZ** — yalnızca digest (hash çıktısı) saklanır, orijinal içerik fingerprint nesnesinden GERİ ÇIKARILAMAZ.

**Reuse şartları (Bölüm 31'in tam listesi, burada özetlenir):** `engine_code` aynı + `engine_schema_version_used` aynı + `engine_model_version_used` aynı + `fingerprint_schema_version` aynı + `input_fingerprint` aynı + TÜM transitif upstream fingerprint'leri uyumlu.

**Aynı `run_id` + FARKLI `request_fingerprint`:** `OrchestrationErrorCategory.INVALID_RUN_REQUEST` (veya `FINGERPRINT_MISMATCH_ON_REUSE`) ile KESİN REDDEDİLİR — sessiz reuse veya otomatik overwrite YOKTUR (Bölüm 12/31).

---

## 42. Input Version Inventory (Madde 39)

v1 ile aynı — `OrchestrationRunResult.input_version_inventory: dict[str, str]`, her motor çağrısında kullanılan TÜM upstream versiyon bilgisini toplar (Executive Report'un `upstream_version_inventory` deseninin run-seviyesine genellenmiş hali).

---

## 43. Execution Provenance (Madde 40)

```
@dataclass(frozen=True)
class ExecutionProvenance:
    execution_plan_version: str                      # Bölüm 38
    engine_call_sequence: "tuple[EngineCode, ...]"     # GERÇEKTEN çağrılan motorlar, ÇAĞRILMA SIRASIYLA
    reused_engine_codes: "tuple[EngineCode, ...]"
    skipped_engine_codes: "tuple[EngineCode, ...]"
```

v1'in aksine, artık `engine_call_sequence` **her zaman Bölüm 37'deki türetilmiş, tamamen sıralı plan sırasına eşittir** — paralellik kaldırıldığı için (Bölüm 7) bu alan ARTIK hiçbir OS-thread-zamanlama belirsizliği taşımaz, TAM olarak deterministiktir.

---

## 44. Audit Trail Sözleşmesi (Madde 41)

v1 ile aynı — `ExecutionProvenance` + `engine_records` + `structured_errors` üçlüsü, Bölüm 25'teki güvenlik kurallarıyla güçlendirilmiş haliyle, eksiksiz bir audit kaydı oluşturur.

---

## 45. Timing/Telemetry Ayrımı (Madde 42) — TAMAMEN YENİDEN YAZILDI

**Denetim bulgusu D3'ün kök-neden çözümü.** Zamanlama verisi, `OrchestrationRunResult`/`PerEngineExecutionRecord`'dan TAMAMEN ÇIKARILMIŞ, AYRI, opsiyonel bir sözleşmeye taşınmıştır:

```
@dataclass(frozen=True)
class PerEngineTelemetry:
    engine_code: "EngineCode"
    started_at_offset_ms: "float | None"     # run başlangıcına göre BAĞIL süre
    duration_ms: "float | None"

@dataclass(frozen=True)
class ExecutionTelemetry:
    per_engine: "tuple[PerEngineTelemetry, ...]"
    total_duration_ms: "float | None"

class TimingProbe(Protocol):
    def now(self) -> float: ...    # örn. time.perf_counter() sarmalayıcısı
```

**`run_orchestration()`'ın yeni imzası (Bölüm 15/60 ile tutarlı):**

```
def run_orchestration(
    request: OrchestrationRunRequest,
    *,
    cancellation_probe: "Callable[[], bool] | None" = None,
    timing_probe: "TimingProbe | None" = None,
) -> "tuple[OrchestrationRunResult, ExecutionTelemetry | None]":
    ...
```

**Kesin kurallar:**

1. `timing_probe` sağlanmazsa (`None`), **hiçbir telemetry üretilmez** — dönüş değeri `(run_result, None)` olur.
2. Zamanlama, **YALNIZCA açıkça enjekte edilen `timing_probe` üzerinden** üretilir — Orchestrator kendi başına ASLA `time.perf_counter()`/`datetime.now()` çağırmaz (Bölüm 48). `timing_probe`, çağıranın (test kodunun veya bir gelecekteki gözlemlenebilirlik adaptörünün) sağladığı, monotonic bir saat sarmalayıcısıdır.
3. `ExecutionTelemetry`, `OrchestrationRunResult`'IN BİR PARÇASI DEĞİLDİR — AYRI bir dönüş değeridir. Bu, Bölüm 29'daki `FULL_RESULT_DETERMINISM`/`BUSINESS_PAYLOAD_DETERMINISM` testlerinin, timing alanlarını "hariç tutmayı hatırlamak" YERİNE, YAPISAL OLARAK timing'i hiç görmemesini sağlar.
4. **Architecture Book ile çelişki sınırı (açık istisna, Bölüm 47'de detaylandırılır):** Bu tasarım, Architecture Book §11'in "Orchestrator kendi saatini okumaz" ilkesini İHLAL ETMEZ — Orchestrator'ın KENDİSİ hiçbir saat OKUMAZ; saat okuma sorumluluğu TAMAMEN çağırana (`timing_probe`'u sağlayan tarafa) aittir. Bu, tıpkı `generated_at`/`report_id`'nin çağıran tarafından sağlanması gibi bir "dışarıdan enjeksiyon" desenidir, motorun/orchestrator'ın kendi başına ürettiği bir değer DEĞİLDİR.

---

## 46. Correlation ID / Run ID Davranışı (Madde 43)

v1 ile aynı — `run_id`/`correlation_id` çağıran tarafından sağlanır, her `PerEngineExecutionRecord`'a ve `ExecutionProvenance`'a yayılır.

---

## 47. Time Bilgisinin Dışarıdan Verilmesi ve Monotonic Clock İstisnası (Madde 44) — REVİZE: Açık Karar #10 KAPANDI

**Denetim bulgusu D4'ün kök-neden çözümü.** v1'de bu, çözülmemiş bir açık karar (Açık Karar #10) olarak bırakılmıştı. **Bu revizyonda KESİN OLARAK KİLİTLENİR:**

**Kural (bağlayıcı, artık açık karar değil):** "Orchestrator kendi saatini okumaz" ilkesi, **takvim/duvar-saati okumasını** (yani `datetime.now()`/`datetime.utcnow()` ile "bugünün tarihi/saati nedir" sorusuna motor/orchestrator içinden cevap vermeyi) yasaklar — bu, sonuçların İÇERİĞİNE gömülen, TEKRARLANAMAZ bir değer üretir (Architecture Book §11'in asıl endişesi budur). **Monotonic clock okuma (`time.perf_counter()` türü), bu yasağın KAPSAMINA GİRMEZ**, çünkü: (a) yalnızca AÇIKÇA enjekte edilen bir `timing_probe` (Bölüm 45) üzerinden, çağıranın kontrolünde gerçekleşir — Orchestrator kendi başına asla bir saat kütüphanesi import edip ÇAĞIRMAZ; (b) ürettiği değer (`ExecutionTelemetry`), İŞ SONUCUNUN (`OrchestrationRunResult`) bir PARÇASI DEĞİLDİR, AYRI, opsiyonel bir gözlemlenebilirlik yapısıdır; (c) iki özdeş çağrı arasındaki süre farkı, ne "iş sonucunu" değiştirir ne de belirlenimsiz bir İŞ DEĞERİ üretir — yalnızca o çalıştırmaya özgü bir gözlem kaydıdır.

Bu istisna, Architecture Book'un kendisine (Bölüm 11 "Determinizm Kuralları") gelecekte AÇIKÇA bir dipnot olarak eklenmesi ÖNERİLİR (ayrı, onaylı bir Architecture Book revizyon turunda) — ama bu önerinin KENDİSİ bu dokümanın kapsamı dışındadır; bu doküman yalnızca kendi Bölüm 45/47'sinde istisnayı KESİN olarak tarif eder.

---

## 48. datetime.now/uuid4/random Yasağı (Madde 45)

v1 ile aynı, Bölüm 47'deki netleştirmeyle güçlendirilmiş: `datetime.now(`, `datetime.utcnow(`, `uuid4(`, `random.` alt-dizeleri Orchestrator kaynak kodunda KESİNLİKLE bulunmaz (statik kaynak-inceleme testiyle doğrulanır, Bölüm 67). `time.perf_counter()` gibi monotonic clock çağrıları, YALNIZCA `TimingProbe` implementasyonunun İÇİNDE (Orchestrator'ın kendi kodunun DIŞINDA, çağıran tarafından sağlanan bir sarmalayıcıda) bulunabilir.

---

## 49. Metrics Sözleşmesi (Madde 46)

v1 ile aynı — Orchestrator kendi metrics üretmez/yayınlamaz; `ExecutionTelemetry` (artık AYRI bir dönüş değeri, Bölüm 45) bir dış katman tarafından okunup istenen sisteme aktarılabilir.

---

## 50. Logging Sınırı (Madde 47)

v1 ile aynı + Bölüm 25 güvenlik kurallarına çapraz referans: Orchestrator production log satırı yazmaz; stack trace/debug detayı YALNIZCA dış bir logging sink'ine, Orchestrator'ın KENDİSİ tarafından değil, çağıran tarafından iletilebilir.

---

## 51-56. Persistence / API / Background Job / Bulk Upload / Transaction / DB'siz Orchestrator Sınırları (Madde 48-53)

v1 ile TAMAMEN aynı (Orchestrator hâlâ hiçbir DB bağlantısı açmaz, API endpoint'i değildir, background job/queue implementasyonu değildir, bulk-upload'a bağlanmaz, transaction açmaz/kapatmaz; DB'siz saf orchestrator hem mümkün hem de mimari olarak gereklidir — 9 motorun SIFIR SQLAlchemy bağımlılığıyla tutarlı).

---

## 57. Saf Orchestrator ile Persistence Adapter Ayrımı (Madde 54) — REVİZE: At-Least-Once Netliği

**Denetim bulgusu R4'ün kök-neden çözümü.** v1'deki diyagram korunur; buna EK olarak:

**Teslimat semantiği (yeni, açık madde — Madde 16 "at-least-once sınırı" talimatının karşılığı):**

- Saf Orchestrator (`run_orchestration()`), **DB'ye yazmaz, kendi başına EXACTLY-ONCE garantisi VERMEZ** — çağrıldığında bir kez DAG yürütür ve sonucu döndürür; bunun ÖTESİNDE hiçbir teslimat garantisi ÜSTLENMEZ.
- Bu saf fonksiyonun ÜZERİNE inşa edilecek herhangi bir workflow/persistence katmanı, doğası gereği **at-least-once** semantiğiyle çalışacaktır (örn. bir mesaj kuyruğu, bir çalıştırmayı retry ile birden fazla kez tetikleyebilir).
- **Exactly-once persistence (bir sonucun TAM OLARAK bir kez kalıcı hale getirilmesi), bu milestone'un kapsamı DIŞINDADIR** — bu, gelecekteki bir persistence-adapter'ın, `run_id` + `request_fingerprint` (Bölüm 41) üzerinde bir UNIQUE constraint/upsert deseniyle çözmesi gereken bir sorumluluktur.
- Bu netlik, Bölüm 31/41'deki "aynı `run_id` + farklı `request_fingerprint` KESİN REDDEDİLİR" kuralıyla BİRLEŞTİĞİNDE, gelecekteki adapter'ın işini kolaylaştırır: adapter, yalnızca "aynı `run_id` + aynı `request_fingerprint`" durumunu (gerçek bir at-least-once tekrarını) idempotent şekilde ele almak zorundadır; "aynı `run_id` farklı girdi" durumu zaten Orchestrator seviyesinde ELENMİŞTİR.

---

## 58-59. Synchronous vs Asynchronous, In-Process vs Queue (Madde 55-56)

v1 ile aynı karar (Senkron, In-process) — artık Bölüm 6/7'nin paralelliği v1'den tamamen çıkarmasıyla DAHA GÜÇLÜ bir gerekçeye sahip: senkron VE tamamen sıralı, hiçbir eşzamanlılık ilkeli (concurrency primitive) gerektirmez.

---

## 60. v1 İçin Önerilen Çalışma Modeli (Madde 57) — REVİZE: Yeni İmza

**Senkron, tamamen sıralı, tek-run, DB'siz, API'siz, saf fonksiyon çağrısı:**

```
def run_orchestration(
    request: OrchestrationRunRequest,
    *,
    cancellation_probe: "Callable[[], bool] | None" = None,
    timing_probe: "TimingProbe | None" = None,
) -> "tuple[OrchestrationRunResult, ExecutionTelemetry | None]":
    ...
```

v1'deki `run_orchestration(request) -> OrchestrationRunResult` imzasından farklar: (1) `cancellation_probe`/`timing_probe` ayrı, process-local, serileştirilmeyen parametrelerdir (Bölüm 15/45), (2) dönüş değeri artık `(OrchestrationRunResult, ExecutionTelemetry | None)` çiftidir (Bölüm 45), (3) `max_run_duration_seconds` YOKTUR (Bölüm 16).

---

## 61-63. Çok Şirketli Batch, Çok Dönemli Analiz, Tenant/Authorization (Madde 58-60)

v1 ile aynı (batch ve gerçek çok-dönemli trend analizi v1 dışı; `prior_period_*` parametreleri zaten desteklenir; `tenant_id` yetkilendirme DEĞİLDİR, yalnızca segmentasyon anahtarıdır).

---

## 64. Concurrency Notu — v1 Kapsamı Dışı (Madde 61) — REVİZE

**Denetim bulgusu C3'ün son netleştirmesi.** v1'de HİÇBİR paralel çalıştırma OLMADIĞI için (Bölüm 6/7), thread-safety/concurrency KONUSU v1'de PRATİKTE ORTAYA ÇIKMAZ — Orchestrator tek bir thread'de, tamamen sıralı çalışır. Bölüm 7'de tarif edilen gelecekteki paralellik fırsatı GERÇEKLEŞTİRİLİRSE, o zaman "iki motor arasında kenar yoksa VE immutable girdi okuyorsa güvenlidir" kuralı yeniden gündeme gelir — ama bu, v1'in DEĞİL, gelecekteki bir workflow-runner optimizasyonunun konusudur.

---

## 65. Registry Isolation (Madde 62) — REVİZE

`ENGINE_DEPENDENCY_REGISTRY` (Bölüm 35), Architecture Book §16 ile aynı iki katmanlı izolasyon desenini kullanır: (1) kayıt fonksiyonlarının opsiyonel `registry=` parametresi, (2) `tests/conftest.py`'nin autouse fixture'ının bu registry'yi mevcut LIFO zincirine eklemesi. **`ORCHESTRATOR_ENGINE_DISPATCH` (Bölüm 36) bir "registry" DEĞİLDİR** (kayıt-doğrulama mantığı taşımaz, yalnızca sabit import-zamanı bağlamalardır) — testlerde tek tek callable'ların `unittest.mock.patch` ile geçici olarak DEĞİŞTİRİLMESİ yeterlidir, ayrı bir snapshot/restore fixture'ı GEREKMEZ.

---

## 66. Test Isolation (Madde 63)

v1 ile aynı — her Orchestrator testi kendi `ENGINE_DEPENDENCY_REGISTRY` durumunu izole kurup geri alır.

---

## 67. Test Stratejisi (Madde 64-75) — TAMAMEN YENİDEN YAZILDI

**Denetim Bölüm 11/18'in ("test stratejisi boşlukları") ve kullanıcının Madde 18 talimatının tam karşılığı.** Aşağıdaki kategoriler, implementasyon aşamasında ZORUNLU test grupları olarak ele alınır (v1'deki dağınık, ~12 küçük bölüme yayılmış anlatımın yerine, tek bir konsolide, kategorilere ayrılmış envanterdir):

**A. Registry/DAG testleri:**
- 10 düğüm doğrulaması.
- 24 toplam kenar, 21 zorunlu (`all_of`), 2 `any_of`-kaynaklı, 1 opsiyonel kenar dağılımı doğrulaması.
- Bilinmeyen bağımlılık, kendine-bağımlılık, döngü reddi (import-anı).
- Registry insertion-order independence (motorlar farklı sırada tanımlansa bile türetilen plan AYNI).
- Eşit-seviyeli düğümlerde deterministik tie-break (alfabetik `EngineCode.value`) doğrulaması.
- `ENGINE_DEPENDENCY_REGISTRY` ↔ `ORCHESTRATOR_ENGINE_DISPATCH` tamlık eşleşmesi (Bölüm 36).

**B. Dependency (`any_of`/`all_of`) testleri:**
- BS başarılı / IS başarısız (RATIO'nun BS ile çağrıldığı, IS'nin `None` geçtiği).
- BS başarısız / IS başarılı (simetrik).
- İkisi de başarısız (RATIO `SKIPPED`, run `PARTIALLY_COMPLETED` veya `FAILED`, Bölüm 10).
- 3+ seviyelik zincirleme SKIP (FS→RATIO→BENCHMARK→...→DASHBOARD'un TAMAMININ SKIP olduğu senaryo).

**C. Status mapping testleri (Bölüm 9.1'in TAM tablosunun parametrik testi):**
- TÜM ~17 iç status değeri için ayrı ayrı parametrik test (her satır Bölüm 9.1 tablosundan).
- `NO_RECOMMENDATIONS_TRIGGERED → COMPLETED` (YANLIŞ sınıflandırmayı ÖZELLİKLE test eden bir regresyon testi).
- `HARD_FAIL_CAPPED → DEGRADED` (Health/Credit Score, ayrı ayrı).
- Dashboard `is_compatible=False → DEGRADED`.
- Render Contract başarılı → `COMPLETED`; `InvalidReportResultError` → `FAILED`; **`DEGRADED` durumunun bu motor için HİÇBİR koşulda üretilemediğinin doğrulanması.**

**D. RunStatus testleri (Bölüm 10'un 5 değerinin HER BİRİ için ayrı senaryo):**
- `FULLY_COMPLETED` (hiçbir DEGRADED/FAILED/SKIPPED yok).
- `COMPLETED_WITH_DEGRADATIONS` (en az bir DEGRADED, hiçbir FAILED/SKIPPED yok) — **v1'deki en kritik regresyon testi: TÜM motorlar DEGRADED olduğunda run'ın YANLIŞLIKLA `FULLY_COMPLETED` DÖNMEDİĞİNİN doğrulanması.**
- `PARTIALLY_COMPLETED`.
- `FAILED`.
- `CANCELLED`.

**E. Fingerprint/Reuse testleri:**
- Aynı `run_id` + aynı `request_fingerprint` → reuse.
- Aynı `run_id` + FARKLI `request_fingerprint` → **KESİN RED** (`INVALID_RUN_REQUEST`/`FINGERPRINT_MISMATCH_ON_REUSE`).
- Aynı motor versiyonu + FARKLI girdi (fingerprint farklı) → reuse REDDİ (v1'in en kritik güvenlik açığının kapandığının kanıtı).
- Schema version uyuşmazlığı → reuse reddi.
- Model version uyuşmazlığı → reuse reddi.
- `fingerprint_schema_version` uyuşmazlığı → reuse reddi.
- Upstream yeniden hesaplandıysa (reuse edilmediyse) downstream'in ZORUNLU olarak yeniden hesaplandığı (transitif geçersizleştirme, Bölüm 31 madde 7).
- Transitif reuse (upstream'in TAMAMI reuse edilebiliyorsa downstream de reuse edilebilir).
- Adversarial: tam bir `PreviousExecutionSnapshot` ile, İÇİNDEKİ bir kaydın versiyon/fingerprint'i şu anki registry ile UYUMSUZ olduğunda doğru reddin gerçekleştiği.

**F. Single Source of Truth testleri:**
- Bir motorun sonucuna YALNIZCA `engine_records` üzerinden erişilebildiği (ikinci bir alan OLMADIĞININ tip-seviyesinde doğrulanması).
- Typed accessor'ların (`get_health_score_result()` vb.) doğru tipi döndürdüğü.
- Yanlış `engine_code`/`result_kind` ile çağrılan bir accessor'ın açıkça REDDETTİĞİ (sessizce `None`/yanlış tip DÖNMEDİĞİ).

**G. Determinism testleri:**
- `BUSINESS_PAYLOAD_DETERMINISM`: aynı finansal girdi + farklı `run_id`/`generated_at` → motor sonuçları AYNI, ama tam `OrchestrationRunResult` FARKLI (run_id/generated_at nedeniyle) — bu FARKIN BEKLENEN olduğunu doğrulayan bir test.
- `FULL_RESULT_DETERMINISM`: TÜM girdiler (run_id dahil) aynıyken 25 tekrarlı çağrının bit-bir aynı `OrchestrationRunResult` ürettiği.
- Telemetry'nin (varsa) her iki determinizm testinde de HARİÇ TUTULDUĞU (ayrı dönüş değeri olduğu için otomatik sağlanır, Bölüm 45).
- Registry insertion-order independence (B/A kategorileriyle çakışan, ama determinizm açısından ayrı bir property testi).

**H. Cancellation testleri:**
- `cancellation_probe`'un N'inci çağrıdan önce `True` döndüğü senaryoda ilk N-1 motorun tamamlandığı, kalanların `SKIPPED (cancelled)` olduğu.
- Çalışan bir motor çağrısının cancellation ile KESİLEMEDİĞİNİN (motor çağrısı başladıktan sonra `cancellation_probe` `True` dönse bile o ÇAĞRININ TAMAMLANDIĞI) doğrulanması.
- `OrchestrationRunRequest`'in serileştirilmiş (örn. JSON) formunun `cancellation_probe`/`timing_probe` içermediğinin/içeremeyeceğinin doğrulanması.

**I. Safety/Sanitization testleri (Bölüm 25'in kök-neden çözümünün testi):**
- Hassas bir exception mesajının (varsayımsal/simüle edilmiş) `StructuredError.message_tr`'ye HAM olarak SIZMADIĞININ doğrulanması.
- `StructuredError`'ın hiçbir alanında stack trace/traceback metninin bulunmadığının statik/çalışma-zamanı doğrulaması.
- Orchestrator kaynak kodunda `eval(`/`exec(`/`importlib`/dinamik `getattr(`-tabanlı dispatch YOKLUĞUNUN statik taranması (Architecture Book §11 deseninin genişletilmiş hali).
- Production sembollerinde (class/enum/registry adları) marka-bağımsızlığın (hiçbir "FINOS" hard-code'unun) statik taranması.

**Kaldırılan test kategorileri (v1 kapsamı dışına taşındığı için artık GEREKMEZ):** Timeout testleri (Bölüm 16), race-condition/paralel-yürütme stres testleri (Bölüm 7/64 — v1'de paralellik yok).

---

## 68. Performans Hedefleri (Madde 76) — REVİZE

**Denetim Bölüm 19 talimatının karşılığı.** v1'in TAMAMEN sıralı pipeline'ı için:

- Kesin sayısal hedefler bu aşamada FABRİKE EDİLMEZ — **ölçüm gerçek Docker ortamında yapılacaktır**, buradaki sayılar PROVİZYONELDİR.
- **Telemetry KAPALI (varsayılan, `timing_probe=None`) ve telemetry AÇIK (`timing_probe` sağlanmış) senaryolar AYRI ölçülecektir** — `timing_probe` enjeksiyonunun kendisinin (fonksiyon çağrısı overhead'i) performansa ek bir maliyeti olup olmadığı ayrıca raporlanmalıdır.
- **Tam pipeline (10 motorun HEPSİ) ve "leaf-output budaması" (yalnızca belirli `requested_outputs` için gereken alt-küme) AYRI ölçülecektir** — Bölüm 37'nin backward-slicing'i (yalnızca Dashboard isteniyorsa Executive Report/Render Contract'ın hiç çağrılmaması gibi) gerçek bir performans farkı yaratabilir.
- **Sahte `<1ms` gibi aşırı iyimser garantiler VERİLMEZ** — motorların kendi gevşek hedefleri (Architecture Book §15, `<5ms`/`<100ms` mertebesinde) toplandığında, gerçekçi bir beklenti "birkaç yüz milisaniyeyi aşmama" mertebesindedir; kesin sayı yalnızca gerçek ölçümle kilitlenecektir.
- **Gerçek p50/p95 (medyan ve 95. yüzdelik) raporlanacaktır** — yalnızca ortalama veya tek bir en-iyi-durum sayısı YETERLİ SAYILMAZ.

---

## 69. Memory Hedefleri (Madde 77)

v1 ile aynı — kesin sayısal hedef bu aşamada fabrike edilmez, implementasyon sonrası gerçek ölçümle kilitlenir (Bölüm 74 Açık Karar listesinde kalan tek madde).

---

## 70. Risk Analizi (Madde 78) — REVİZE

| Risk | Etki | Azaltma (bu revizyonda uygulanan) |
|---|---|---|
| ~~Financial Statements AND/OR çelişkisi~~ | ~~Yüksek~~ | **KAPANDI** — `DependencyRequirement.any_of` modeli (Bölüm 3) |
| ~~`callable_ref` string dispatch~~ | ~~Yüksek~~ | **KAPANDI** — `ORCHESTRATOR_ENGINE_DISPATCH` doğrudan callable bağlama (Bölüm 36) |
| ~~`FULLY_COMPLETED` DEGRADED gizleme~~ | ~~Yüksek~~ | **KAPANDI** — 5 değerli `RunStatus`, `COMPLETED_WITH_DEGRADATIONS` (Bölüm 10) |
| ~~Input fingerprint eksikliği~~ | ~~Yüksek~~ | **KAPANDI** — Bölüm 41, reuse şartlarına eklendi |
| ~~Duplicate source of truth~~ | ~~Orta~~ | **KAPANDI** — `engine_records` tek kaynak, typed accessor'lar (Bölüm 23) |
| ~~Kenar sayısı hatası~~ | ~~Düşük (ama güven zedeleyici)~~ | **KAPANDI** — 24 olarak düzeltildi, checklist eklendi (Bölüm 4) |
| Gerçek implementasyon, bu dokümanın `any_of`/fingerprint/status-mapping kurallarını EKSİKSİZ uygulamazsa | Yüksek | Bölüm 67'deki test kategorileri, HER kuralı ayrı ayrı doğrulayacak şekilde tasarlandı |
| Gelecekte paralellik eklenirse (Bölüm 7), non-determinism riski YENİDEN gündeme gelir | Orta (yalnızca gelecekte, v1'de YOK) | Bölüm 7'de açıkça "gelecekteki workflow-runner sorumluluğu" olarak sınırlandı |

---

## 71. Enterprise Readiness (Madde 79)

v1 ile aynı temel değerlendirme, ARTIK GÜÇLENDİRİLMİŞ: yapılandırılmış hata taksonomisi (Bölüm 25, artık güvenlik kurallarıyla), tam audit/provenance izlenebilirliği, **fingerprint-doğrulanmış** reuse (Bölüm 31/41), determinizm (Bölüm 29, artık iki net property ile). Bilinçli olarak v1 dışı bırakılanlar aynı kalır: dağıtık/kuyruk-tabanlı çalıştırma, otomatik retry/backoff, çok-kiracılı yetkilendirme UYGULAMASI, çok-şirketli batch, timeout/paralellik (YENİ olarak da v1 dışına alındı).

---

## 72. Production Readiness (Madde 80) — REVİZE

Doküman hâlâ bir tasarımdır — implementasyon YOKTUR. Ama denetim sonrası ölçüt karşılanma durumu:

- [x] TÜM 82 orijinal madde + denetimin 22 revizyon maddesi bu dokümanda YANITLANDI/UYGULANDI.
- [x] Hiçbir motor sözleşmesi tahmin edilmedi (Bölüm 2.1 değişmedi).
- [x] Architecture Book ile ÇELİŞKİ KALMADI (H1 kapandı — Bölüm 36).
- [x] 4 kritik + 6 orta seviye denetim bulgusunun TAMAMI kök nedeninden çözüldü (Bölüm 75).
- [x] Açık kararlar yeniden konsolide edildi, kapananlar çıkarıldı (Bölüm 74).
- [ ] Kod/test/migration/API/adapter YAZILMADI (bu turun kesin sınırı — hâlâ karşılanıyor, implementasyon henüz başlamadı).

**Yeni Production Readiness değerlendirmesi (tasarım-olgunluğu ekseninde): ~85%** (v1'deki ~55%'ten yükseldi — Bölüm 75'te ayrıntılı gerekçelendirilmiştir). Kalan %15, implementasyonun BU dokümandaki kuralları (özellikle Bölüm 9.1 tam eşleme tablosu, Bölüm 41 fingerprint algoritması, Bölüm 67 test kategorileri) EKSİKSİZ uygulamasına ve gerçek Docker ölçümlerinin (Bölüm 68-69) yapılmasına bağlıdır — bunlar tasarım kağıdı üzerinde ÇÖZÜLEMEZ, yalnızca implementasyonla doğrulanabilir.

---

## 73. Alt Adımlara Bölünmüş İmplementasyon Planı (Madde 82) — REVİZE

1. **Adım 0 (YENİ):** Bu revizyonun (v2) kullanıcı tarafından ONAYLANMASI — implementasyon BU onay olmadan başlamaz.
2. **Adım 1 — Kalan açık kararların kapatılması** (Bölüm 74 — artık yalnızca 4 gerçek ürün kararı kaldı).
3. **Adım 2 — `orchestrator_types.py`:** `EngineCode`, `EngineExecutionStatus`, `RunStatus` (5 değer), `OrchestrationErrorCategory` enum'ları + `DependencyRequirement`, `EngineInvocationSpec` (callable_ref OLMADAN), `PerEngineExecutionRecord` (fingerprint alanlarıyla), `EngineResultEnvelope`, `StructuredError`, `ExecutionProvenance`, `OrchestrationRunRequest`, `OrchestrationRunResult`, `PreviousExecutionSnapshot`/`PreviousEngineSnapshot`, `RequestFingerprint`/`EngineInputFingerprint`, `ExecutionTelemetry`/`PerEngineTelemetry`, `TimingProbe` frozen dataclass'ları/protokolleri.
4. **Adım 3 — `orchestrator_registry.py`:** `ENGINE_DEPENDENCY_REGISTRY` (metadata) + kayıt-anı DAG doğrulama (10 düğüm/24 kenar/21+1+2 dağılımı, döngü/bilinmeyen-düğüm reddi).
5. **Adım 4 — `orchestrator_dispatch.py`:** `ORCHESTRATOR_ENGINE_DISPATCH` — doğrudan import'lar + tamlık doğrulaması.
6. **Adım 5 — `fingerprint.py`:** Canonical-JSON + SHA-256 fingerprint hesaplama fonksiyonları (Bölüm 41'deki motor-başına girdi tablosuna göre).
7. **Adım 6 — `execution_plan.py`:** DAG'dan deterministik topological sort + alfabetik tie-break (Bölüm 37).
8. **Adım 7 — `analysis_orchestrator/service.py`:** `run_orchestration()` — TAMAMEN sıralı çalıştırma (Bölüm 6), Bölüm 9.1'deki TAM status-eşleme, `any_of`/`all_of` dependency çözümleme (Bölüm 26), reuse/fingerprint kontrolü (Bölüm 31), cancellation_probe/timing_probe entegrasyonu.
9. **Adım 8 — `tests/conftest.py` genişletme:** `ENGINE_DEPENDENCY_REGISTRY`'nin LIFO snapshot/restore zincirine eklenmesi.
10. **Adım 9 — Test suite:** Bölüm 67'deki TÜM kategoriler (A'dan I'ya).
11. **Adım 10 — Sandbox doğrulama, ardından GERÇEK Docker doğrulama + p50/p95 ölçümü** (Bölüm 68).
12. **Adım 11 — Kapsam kontrolü + Architecture Book güncellemesi** (monotonic-clock istisnasının, Bölüm 47'nin önerdiği şekilde, ayrı bir onaylı turda Architecture Book'a eklenip eklenmeyeceği kullanıcıya sorulur).

**v1 implementasyon planına DAHİL EDİLMEYENLER (bilinçli):** Paralellik/`ThreadPoolExecutor` (Bölüm 7), `max_run_duration_seconds`/timeout (Bölüm 16), otomatik retry (Bölüm 11), batch runner (Bölüm 61).

---

## 74. Açık Kararlar (Madde 81) — TAMAMEN YENİDEN YAZILDI

**v1'deki 11 açık karardan KAPANANLAR** (denetim bulgularının kök-neden çözümü olarak bu revizyonda BAĞLAYICI şekilde kilitlenmiştir, artık açık değildir):

- ~~#1 (FS ikisi de FAILED → Ratio SKIP mi)~~ — **KİLİTLENDİ: SKIP** (Bölüm 3, `any_of` modeliyle çelişkisiz hale getirildi).
- ~~#2 (Execution Plan budama stratejisi)~~ — **KİLİTLENDİ: DAG'dan türetilmiş, duplicate plan yok** (Bölüm 37).
- ~~#4 (RunStatus'a CANCELLED eklensin mi)~~ — **KİLİTLENDİ: evet, 5 değerli enum'un parçası** (Bölüm 10).
- ~~#5 (max_run_duration_seconds v1'e girsin mi)~~ — **KİLİTLENDİ: HAYIR, v1'den çıkarıldı** (Bölüm 16).
- ~~#7 (retry'ın persistence idempotency'si hangi milestone'da)~~ — **KİLİTLENDİ: gelecekteki adapter, at-least-once + unique-constraint deseniyle** (Bölüm 57), fingerprint-red kuralı v1'de zaten devrede.
- ~~#10 (monotonic clock istisnası)~~ — **KİLİTLENDİ: Bölüm 47'de kesin kural yazıldı.**
- Ayrıca denetimin yeni tespit ettiği ve bu revizyonda kapatılan: `callable_ref` → doğrudan dispatch (Bölüm 36), input fingerprint modeli (Bölüm 41), duplicate state (Bölüm 23), `engine_version_used` tek alan → iki alan (Bölüm 22/40), `cancellation_token` serileştirme çelişkisi (Bölüm 15), paralellik kararı (Bölüm 7 — v1 dışı).

**Kalan GERÇEK açık kararlar (4 — yalnızca gerçek ürün/mimari tercihleri, implementasyonu ENGELLEMEYEN):**

1. Otomatik retry (backoff/deneme-sayısı) hiçbir zaman Orchestrator'ın kapsamına girmeyecek mi, yoksa çok ileride (5.0B+) sınırlı bir versiyonu mu düşünülecek? (Bölüm 11 — şimdilik "asla Orchestrator'da değil" varsayımıyla ilerleniyor, ama gelecekteki workflow-runner'ın TAM kapsamı henüz tasarlanmadı.)
2. Çok-şirketli Batch Runner'ın hangi milestone numarasıyla (5.1, 5.2, vb.) planlanacağı (Bölüm 61).
3. Monotonic-clock istisnasının (Bölüm 47), Architecture Book'un KENDİSİNE ayrı bir onaylı revizyon turuyla AÇIKÇA dipnot olarak eklenip eklenmeyeceği — bu doküman yalnızca 5.0A kapsamında kuralı kilitler, Architecture Book'un GÜNCELLENMESİ ayrı bir karardır.
4. Bellek hedefinin kesin sayısal değeri — implementasyon sonrası gerçek ölçümle kilitlenecek (Bölüm 69).

**Toplam kalan açık karar sayısı: 4** (v1'deki 11'den; 7'si bu revizyonda kapatıldı, kalan 4'ü implementasyonu ENGELLEMEYEN, gerçek ürün-kararı niteliğindeki maddelerdir).

---

## 75. Bağımsız Mimari Denetim Sonrası Revizyon Raporu

Bu bölüm, denetim raporundaki HER bulguyu, uygulanan düzeltmeyi, değişen sözleşmeyi ve kapanan/kalan açık kararı ayrı ayrı raporlar.

### 75.1 Kritik Bulgular (Denetim Bölüm 2/14 — "Gerçek Mimari Hatalar" ve "En Büyük 15 Risk")

| # | Bulgu | Uygulanan Düzeltme | Değişen Sözleşme | Durum |
|---|---|---|---|---|
| H1 | `callable_ref: str`, Architecture Book §18'i ihlal ediyordu | `EngineInvocationSpec`'ten `callable_ref` kaldırıldı; `ORCHESTRATOR_ENGINE_DISPATCH: dict[EngineCode, Callable]` ile doğrudan import-zamanı bağlama eklendi | Bölüm 18, 35, 36 | **KAPANDI** |
| H2 | FS için AND (Bölüm 26) vs OR (Bölüm 5/28/33-S1) çelişkisi | `DependencyRequirement(all_of, any_of, optional)` modeli eklendi; RATIO artık `any_of=(FS_BALANCE_SHEET, FS_INCOME_STATEMENT)` | Bölüm 3, 26, 35 | **KAPANDI** |
| H3 | Kenar sayısı "23" iddiası matematiksel olarak yanlıştı (gerçek: 24) | Kenar listesi yeniden sayıldı, "24" olarak düzeltildi, dağılım (21 zorunlu + 2 any_of + 1 opsiyonel) eklendi, registry doğrulama checklist'i eklendi | Bölüm 4 | **KAPANDI** |
| H4 | Render Contract'ın status'suzluğu, DEGRADED sınıflandırma modelinde ele alınmamıştı | Bölüm 9.1'e "Render Contract için DEGRADED yapısal olarak mevcut değildir" kesin kuralı eklendi | Bölüm 9.1, 2.1.9 | **KAPANDI** |
| F1 | `RunStatus.FULLY_COMPLETED`, TÜM motorlar DEGRADED olsa bile geçerliydi | `RunStatus` 4 değerden 5 değere çıkarıldı; `COMPLETED_WITH_DEGRADATIONS` eklendi | Bölüm 10, 21 | **KAPANDI** |
| R1 | Reuse yalnızca versiyon eşitliğine bakıyordu, girdi eşitliğine bakmıyordu | `RequestFingerprint`/`EngineInputFingerprint` (SHA-256, canonical JSON) eklendi; reuse şartlarına fingerprint eşleşmesi eklendi; aynı run_id+farklı fingerprint KESİN REDDEDİLİR | Bölüm 31, 41 | **KAPANDI** |
| C1 | `cancellation_token: Callable`, serileştirilebilirlik iddiasıyla çelişiyordu | `cancellation_token` request'ten çıkarıldı; `run_orchestration(request, *, cancellation_probe=..., timing_probe=...)` ayrı parametreler oldu | Bölüm 15, 19, 60 | **KAPANDI** |
| I1 | `engine_records` + ayrı adlandırılmış alanlar duplicate source-of-truth yaratıyordu | Adlandırılmış alanlar kaldırıldı; `EngineResultEnvelope` + typed accessor fonksiyonlar (`get_health_score_result()` vb.) eklendi | Bölüm 23, 30 | **KAPANDI** |

### 75.2 Orta Seviye Bulgular

| # | Bulgu | Uygulanan Düzeltme | Değişen Sözleşme | Durum |
|---|---|---|---|---|
| V1 | `engine_version_used: str` tek alan schema/model version'ı karıştırıyordu | `engine_schema_version_used` + `engine_model_version_used` olarak ikiye ayrıldı | Bölüm 22, 40 | **KAPANDI** |
| V2 | Versiyon eksenleri arasındaki ilişki konsolide edilmemişti | Tek bir "Versiyon Alanları Konsolide Tablosu" eklendi | Bölüm 40 | **KAPANDI** |
| D1 | Execution Plan "türetilmiş mi elle mi" belirsizdi | KİLİTLENDİ: yalnızca `ENGINE_DEPENDENCY_REGISTRY`'den türetilir, ikinci elle-yazılmış plan YOK | Bölüm 37 | **KAPANDI** |
| D2/D3 | Determinizm iddiası run_id/generated_at istisnasını belirtmiyordu; timing alanları sonucun içindeydi | İki ayrı property (`BUSINESS_PAYLOAD_DETERMINISM`/`FULL_RESULT_DETERMINISM`) tanımlandı; timing `ExecutionTelemetry`'ye taşındı | Bölüm 29, 45 | **KAPANDI** |
| D4 | Monotonic clock istisnası açık karardı | Bölüm 47'de kesin kural olarak kilitlendi | Bölüm 47 | **KAPANDI** |
| C2 | `max_run_duration_seconds` çalışan bir motoru kesemiyordu — yanıltıcı sözleşme | v1'den TAMAMEN çıkarıldı, `TIMEOUT_EXCEEDED` kategorisi kaldırıldı | Bölüm 16, 25 | **KAPANDI** |
| C3 | Paralellik (ThreadPoolExecutor) GIL nedeniyle faydasız + non-determinism riskliydi | v1'den TAMAMEN çıkarıldı, tamamen sıralı çalıştırma zorunlu kılındı | Bölüm 6, 7, 58, 64 | **KAPANDI** |
| M1 | SKIP kararının metodolojik gerekçesi tek yönlüydü | Bölüm 3'e açık, iki-yönlü gerekçelendirme eklendi (SKIP'in neden tercih edildiği + karşıt argümanın neden reddedildiği) | Bölüm 3 | **KAPANDI** |
| R3 | `previous_run_result: OrchestrationRunResult` ağır coupling yaratıyordu | `PreviousExecutionSnapshot`/`PreviousEngineSnapshot` (hafif, tek yönlü) ile değiştirildi | Bölüm 14, 19 | **KAPANDI** |
| R4 | Exactly-once/at-least-once ayrımı belirtilmemişti | Bölüm 57'ye açık "at-least-once, exactly-once kapsam dışı" netliği eklendi | Bölüm 57 | **KAPANDI** |
| — | StructuredError güvenlik/sanitization kuralları eksikti | Bölüm 25'e 4 maddelik güvenlik kuralı seti eklendi (sabit şablon mesajlar, stack trace asla taşınmaz, hassas veri yasağı) | Bölüm 25 | **KAPANDI** |
| — | Status-eşleme tablosu eksiksiz değildi (özellikle NO_RECOMMENDATIONS_TRIGGERED riski) | Bölüm 9.1'de TÜM ~17 iç durum için eksiksiz tablo eklendi | Bölüm 9.1 | **KAPANDI** |
| — | Test stratejisi boşlukları (fault injection, adversarial resume, single-source-of-truth, safety testleri eksikti) | Bölüm 67 tamamen yeniden yazıldı, 9 kategori (A-I) altında genişletildi | Bölüm 67 | **KAPANDI** |

### 75.3 Kapanan/Kalan Açık Karar Özeti

- v1'deki 11 açık karardan **7'si bu revizyonda bağlayıcı şekilde kilitlendi** (Bölüm 74).
- **4 gerçek açık karar kalmıştır** (otomatik retry'ın nihai kapsamı, batch runner'ın milestone numarası, Architecture Book'a monotonic-clock dipnotunun eklenip eklenmeyeceği, kesin bellek hedefi) — bunların HİÇBİRİ implementasyona başlamayı ENGELLEMEZ, tümü ya gelecekteki milestone'ların ya da implementasyon-sonrası ölçümün konusudur.

### 75.4 Yeni Production Readiness: **~85%** (v1: ~55%)

Artış gerekçesi: 4 kritik + 6 orta seviye bulgunun TAMAMI kök nedeninden çözüldü; Architecture Book ile ÇELİŞKİ KALMADI; test stratejisi kapsamlı hale getirildi. Kalan %15, yalnızca implementasyon+gerçek-ölçüm ile kapatılabilir (tasarım kağıdında daha fazla ilerleme mümkün değildir).

### 75.5 İmplementasyona Hazır mı?

**Kısmen hazır, 2. karar turu onayına bağlı olarak EVET.** Denetimin işaret ettiği TÜM kök-neden sorunları bu revizyonda çözülmüştür; doküman artık kendi içinde çelişkisizdir ve Architecture Book ile tam uyumludur. Kalan 4 açık karar, implementasyonu engellemeyen ikincil ürün kararlarıdır. **Kullanıcının bu v2 revizyonunu AÇIKÇA onaylaması, implementasyona geçmenin ön koşuludur** — bu doküman kendi kendine bu onayı varsaymaz.

---

## 76. Kapanış

Bu doküman (v2), Milestone 5.0A — Analysis Orchestrator tasarımını, bağımsız bir mimari denetimin tespit ettiği TÜM bulgulara göre kök nedeninden revize etmiştir. `callable_ref` string-dispatch'i kaldırılmış (doğrudan `ORCHESTRATOR_ENGINE_DISPATCH` ile değiştirilmiş), Financial Statements AND/OR çelişkisi `DependencyRequirement.any_of` modeliyle çözülmüş, DAG kenar sayısı 24 olarak düzeltilmiş, `RunStatus` 5 değere çıkarılarak dereceli-ama-hatasız durumlar artık sessizce gizlenemez hale getirilmiş, input fingerprint modeli eklenmiş, duplicate source-of-truth giderilmiş, cancellation/timeout/paralellik sözleşmeleri netleştirilmiş/v1 dışına taşınmış, versiyon alanları ayrıştırılmış ve konsolide edilmiştir. Bu turda **hiçbir kod, test, migration, API, adapter yazılmamış; hiçbir commit/push yapılmamıştır.** 4 gerçek açık karar (Bölüm 74) kullanıcının onayını beklemektedir. İmplementasyona **geçilmemiştir** — bu doküman yalnızca 2. karar turuna hazırlanmış bir tasarımdır.
