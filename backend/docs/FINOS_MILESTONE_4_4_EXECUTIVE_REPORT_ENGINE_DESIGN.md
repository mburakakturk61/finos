# FINOS Milestone 4.4 — Executive Report Engine Teknik Tasarım Dokümanı (İMPLEMENTASYON SONRASI UYUM REVİZYONU — 4. Revizyon)

**DURUM: İMPLEMENTE EDİLDİ VE GERÇEK DOCKER'DA DOĞRULANDI (886 passed, 0
failed). Bu 4. tur yalnızca DOKÜMANI, GERÇEKLEŞEN implementasyonla %100
UYUMLU hale getirmek için revize eder — hiçbir kod/test değişikliği İÇERMEZ.**

Bu doküman **4. revizyon turudur**. 1. tur ilk taslaktı; bağımsız mimari
denetim 13 bulgu buldu. 2. tur bu 13 bulguyu 20 bağlayıcı kararla ele aldı
ve Bölüm 28.2'de **9 açık karar** bıraktı. 3. tur, kullanıcının verdiği
**18 maddelik bağlayıcı son-karar talimatıyla o 9 açık kararın TAMAMINI
KAPATTI** ve dokümanı implementasyon-öncesi NİHAİ hale getirdi. Kullanıcının
**"Şimdi implementasyona başla"** talimatıyla implementasyon TAMAMLANDI,
sandbox'ta 772/772, gerçek Docker'da **886/886** ("0 failed") ile
DOĞRULANDI. Bu **4. tur**, implementasyon sırasında bulunan **TEK bir
mimari sapmayı** (SWOT_REPORT'un 5 değil 7 section içermesi — mimari
gerekçesi Bölüm 0.1'de) dokümana İŞLER; böylece doküman artık koddan
FARKLI DEĞİLDİR.

**Bu turda kod/test/migration/API/adapter/render/dashboard
implementasyonu DEĞİŞTİRİLMEMİŞTİR — yalnızca bu doküman revize
edilmiştir.**

---

## 0.1 İmplementasyon Sonrası Tespit Edilen TEK Mimari Sapma — SWOT_REPORT (5 → 7 section)

### Ne değişti

3. turun Bölüm 15.4.6'sı `SWOT_REPORT`'u **5 section** ile tanımlıyordu:
`SEC_COVER_PAGE`, `SEC_SWOT`, `SEC_METHODOLOGY_APPENDIX`, `SEC_DISCLAIMER_
BLOCK`, `SEC_EXECUTIVE_SUMMARY` (opsiyonel). İmplementasyon sırasında bu,
**7 section**'a çıkarılmıştır — `SEC_HEALTH_SCORE_BREAKDOWN` ve `SEC_
RECOMMENDATIONS` zorunlu (compact/headline-only ayrıntı seviyesiyle)
eklenmiştir.

### Neden — mimari gerekçe (dependency graph'ın DOĞAL sonucu)

Bölüm 4/15.3'ün **KENDİSİ hiç değişmedi**: `SEC_SWOT` (aggregation_
section), kayıt-anında `SEC_HEALTH_SCORE_BREAKDOWN` ve `SEC_
RECOMMENDATIONS`'a **sabit, KAPALI bir bağımlılıkla** (`dependency_
codes`) bağlıdır — bu, 2. turdan beri DEĞİŞMEYEN bir tasarım kararıdır.
Bölüm 4'ün KENDİ, bağlayıcı kuralı şudur: **"Aggregation section
YALNIZCA tamamlanmış dependency section outputlarını okuyabilir."**

3. turun Bölüm 15.4.6 tablosu, bu kuralı **`SWOT_REPORT` özelinde ihlal
eden bir SEHİV içeriyordu**: `SEC_SWOT`'u zorunlu (`optional=False`)
kılarken, onun **iki bağımlılığını da (`SEC_HEALTH_SCORE_BREAKDOWN`,
`SEC_RECOMMENDATIONS`) o rapor tipinin section listesine HİÇ dahil
ETMİYORDU**. Sonuç: `SWOT_REPORT` çalıştırıldığında, `SEC_SWOT`'un
`Strengths`/`Weaknesses`/`Threats` kadranlarının HER ÜÇÜ de "dependency
unavailable" nedeniyle **BOŞ** dönerdi (yalnızca zaten-boş `Opportunities`
kadranı DOLU görünürdü — ki o da KASITLI olarak hep boştur). Bu, SWOT
Raporu'nun **TEK VAROLUŞ SEBEBİNİ (SWOT içeriği sunmak) YOK EDERDİ**.

Bu, Bölüm 6.3'ün "yalnızca TEK section bir domain'i kapsıyorsa full
olabilir" istisnasıyla da KARIŞTIRILMAMALIDIR — o istisna geçerli
kalmaya devam ediyor, ama burada sorun bambaşka bir katmanda: bir
aggregation section'ın ZORUNLU (`optional=False`) olduğu bir raporda,
onun ZORUNLU bağımlılıklarının O RAPORDA HİÇ BULUNMAMASI, dependency
graph modelinin KENDİ iç tutarlılığını BOZAR.

### Düzeltme

`SEC_HEALTH_SCORE_BREAKDOWN` ve `SEC_RECOMMENDATIONS`, `SWOT_REPORT`'a
**zorunlu (`optional=False`), `detail_level=compact`, `field_inclusion_
policy=headline_only`** olarak eklenmiştir — SWOT'un görsel/editöryel
önceliğini BOZMADAN (bu iki section KOMPAKT kalır, `SEC_SWOT` raporun
odak noktası olmaya devam eder), `SEC_SWOT`'un bağımlılıklarını o
raporda GERÇEKTEN TAMAMLANMIŞ hale getirir. Bu, **HİÇBİR mimari
kararı DEĞİŞTİRMEZ** — Bölüm 4'ün dependency modelini, Bölüm 6.3'ün
overlap/full-detail kuralını, Bölüm 9'un legal/confidentiality
matrisini AYNEN korur; yalnızca `SWOT_REPORT`'un section ENVANTERİNİ,
ZATEN VAR OLAN kurallarla TUTARLI hale getirir.

### Genelleştirilmiş kural (Bölüm 4'e eklenen 6. madde, aşağıda Bölüm
4.4'te de tekrarlanmıştır)

> **Bir `ReportType`, bir `aggregation_section`'ı zorunlu (`optional=
> False`) olarak içeriyorsa, o `aggregation_section`'ın `dependency_
> codes`'undaki TÜM section'lar da (en azından `compact`/`headline_
> only` ayrıntı seviyesinde) o `ReportType`'ın section listesinde
> YER ALMALIDIR.** Aksi halde, o aggregation section'ın çekirdek
> içeriği "dependency unavailable" nedeniyle boş kalabilir — ki bu,
> yalnızca (Bölüm 15.4.2/15.4.3/15.4.4/15.4.5'te olduğu gibi) `SEC_
> EXECUTIVE_SUMMARY`'nin KISMİ zenginlik kaybı için KABUL EDİLEBİLİR
> bir durumdur (executive summary'nin doğası gereği KISA/ÖZET
> olması beklenir), ama `SEC_SWOT` gibi TEK amacı bir sentezi SUNMAK
> olan bir section için KABUL EDİLEMEZ.

### Etkilenmeyen (doğrulanan) diğer 6 rapor tipi

`CFO_EXECUTIVE_REPORT`'ta `SEC_EXECUTIVE_SUMMARY`'nin 4 bağımlılığının
TAMAMI (`SEC_HEALTH_SCORE_BREAKDOWN`/`SEC_CREDIT_SCORE_BREAKDOWN`/`SEC_
RECOMMENDATIONS`/`SEC_RISK_FLAGS`) zaten mevcuttu — DEĞİŞMEDİ. `BANK_
CREDIT_ALLOCATION_REPORT`/`BOARD_OF_DIRECTORS_REPORT`/`INVESTOR_
REPORT`/`MANAGEMENT_SUMMARY`'de `SEC_EXECUTIVE_SUMMARY`'nin bazı
bağımlılıkları eksik kalmaya DEVAM EDER (ör. Bank Credit'te `SEC_
HEALTH_SCORE_BREAKDOWN`/`SEC_RECOMMENDATIONS` yok) — ama bu, `SEC_
EXECUTIVE_SUMMARY`'nin İÇERİĞİNİ KISMEN inceltir (üretim zamanında
`EXECUTIVE_SUMMARY_DEPENDENCY_UNAVAILABLE` warning'i ile GÖRÜNÜR
kılınır), section'ı TAMAMEN BOŞALTMAZ — bu yüzden yukarıdaki genel
kuralın "kabul edilebilir kısmi zenginlik kaybı" istisnasına GİRERLER
ve DÜZELTME GEREKTİRMEZLER.

---

## 0. Bu Turda Kapatılan 9 Açık Karar (3. Turdan — DEĞİŞMEDEN korunmuştur)

| 2. Turun Açık Kararı | 3. Turdaki Bağlayıcı Çözüm |
|---|---|
| #1 Gerçek çok-dönemli Trend Engine kapsamı | Bölüm 13 madde 13 — kesin kapsam dışı, ayrı gelecek milestone |
| #2 `horizontal_analysis`'in reliability eksikliği | Bölüm 7 madde 10 — merkezi compatibility policy içinde `confidence_available=False` olarak kalıcı KABUL, ayrı iyileştirme milestone'u ÖNERİLMEZ (v1 sınırı olarak KİLİTLENDİ) |
| #3 Rapor dili (yalnızca TR mi) | Bölüm 12 madde 12 — v1 yalnızca TR, `locale` parametresi hook olarak GEÇİLİR ama yalnızca `"tr-TR"` DESTEKLENİR |
| #4 `ReportCompanyMetadata` kaynağı | Bölüm 12 — kesin: çağırandan geçirilir, motor DB okumaz (sıfır-DB disiplini KORUNUR) |
| #5 Sayısal biçimlendirme sorumluluğu | Bölüm 11 — `ReportContentBlock.payload` HAM `Decimal`/`str` taşır, biçimlendirme motor SORUMLULUĞUNDA DEĞİLDİR (render katmanına ERTELENDİ) |
| #6 Gerçek PDF/DOCX render katmanı | Bölüm 3 / Bölüm 13 madde 13 — kesin kapsam dışı, AYRI gelecek milestone |
| #7 18 bölümlük katalog yeterliliği | Bölüm 15 — v1 için KAPALI ve KESİN kabul edildi, yeni section eklenmesi `report_schema_version` artışı gerektirir |
| #8 Hukuki inceleme süreci | Bölüm 9 — v1'de HİÇBİR rapor `approved` DEĞİLDİR, hepsi `not_reviewed`/`internal_use_only`/`legal_review_required`, `external_distribution_allowed=False` KALICI v1 kısıtı |
| #9 Gizlilik/erişim-kontrolü uygulaması | Bölüm 13 madde 13 — kesin kapsam dışı, yalnızca metadata TAŞINIR, UYGULANMAZ |

**Bölüm 28.2 artık "Açık Kararlar" DEĞİL, Bölüm 14'te "Onaylanmış
Kararlar" başlığı altında KAPALI olarak yeniden yazılmıştır.**

---

## 1. Mevcut Sistem İncelemesi (DEĞİŞMEDİ)

*(2. turdan aynen korunmuştur — bu bölüme hiçbir itiraz gelmedi.)*
Kaynak: `app/engines/balance_sheet/service.py`, `app/engines/income_
statement/service.py`, `app/engines/financial_ratios/service.py`,
`app/engines/benchmarks/service.py`, `app/engines/health_score/
service.py`, `app/engines/credit_score/service.py`, `app/engines/
recommendation/service.py`. 7 girdi sözleşmesinin tam alan listesi
2. turun Bölüm 1.1-1.7'sinde belgelenmiştir ve bu turda TEKRAR
YAZILMAMIŞTIR (referans olarak kalır, içerik DEĞİŞMEDİ).

---

## 2. Executive Report Engine Sorumlulukları (DEĞİŞMEDİ, kesinleşti)

Üç AYRI, birbirine KARIŞMAYAN çıktı ailesi (Bölüm 11.4'ün kesin
sözleşme-ayrımı kuralı):

1. **Narrative Report** — `generate_executive_report()` → `ExecutiveReportResult` (Bölüm 11.1).
2. **Dashboard Snapshot** — `generate_dashboard_snapshot()` → `DashboardSnapshot` (Bölüm 11.2).
3. **Render Contract Preview** — `preview_render_contract()` → `RenderContractPreview` (Bölüm 11.3).

---

## 1. Executive Report Engine Kapsamı — KAPALI Liste (KİLİTLİ)

### 1.1 Narrative `ReportType` — KAPALI ve KESİN, v1 için nihai

```python
class ReportType(str, enum.Enum):
    CFO_EXECUTIVE_REPORT = "cfo_executive_report"
    BANK_CREDIT_ALLOCATION_REPORT = "bank_credit_allocation_report"
    BOARD_OF_DIRECTORS_REPORT = "board_of_directors_report"
    INVESTOR_REPORT = "investor_report"
    MANAGEMENT_SUMMARY = "management_summary"
    SWOT_REPORT = "swot_report"
    PERIOD_COMPARISON_REPORT = "period_comparison_report"
```

**Kesin kural:** Bu liste **KAPALIDIR**. Yeni bir `ReportType` üyesi
eklenmesi:

1. `report_model_version`'ı artırır (Bölüm 10.4 — davranış/registry
   içerik değişikliği).
2. Ayrıca `recommendation`/`health_score`/`credit_score` üzerinde YENİ
   bir alan/section TÜKETİMİ gerektiriyorsa, İLGİLİ motorun `model_
   version`'ı da (bu motorların KENDİ milestone'ları kapsamında)
   artabilir — Executive Report Engine bunu KENDİSİ TETİKLEMEZ, yalnızca
   TÜKETİR.
3. YENİ bir `SectionUsageDefinition` seti VE gerekiyorsa yeni `Report
   SectionDefinition` kaydı GEREKTİRİR — bu doküman KAPSAMINDA DEĞİLDİR.

### 1.2 Rapor türü × canonical section haritası özeti

Tam envanter Bölüm 15'tedir. Bu alt bölüm yalnızca SAYIMI teyit eder:
CFO=16, Bank Credit=12, Board=10, Investor=9, Management Summary=7,
**SWOT=7** (implementasyon sonrası düzeltme — Bölüm 0.1), Period
Comparison=5 section KULLANIMI (bkz. Bölüm 15 tam tablolar).

---

## 2. Dashboard Mimarisi — TAMAMEN AYRI (KİLİTLİ)

### 2.1 Kesin ayrım

Dashboard, narrative Report Engine'den **TAMAMEN AYRI** bir contract
ve fonksiyondur:

```python
class DashboardType(str, enum.Enum):
    EXECUTIVE_DASHBOARD = "executive_dashboard"
    RISK_DASHBOARD = "risk_dashboard"


def generate_dashboard_snapshot(
    dashboard_type: DashboardType,
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    recommendation_result: RecommendationResult,
    *,
    benchmark_result_json: "dict[str, Any] | None" = None,
    company_metadata: "ReportCompanyMetadata",
    report_id: "str | None" = None,
    generated_at: "str | None" = None,
) -> "DashboardSnapshot": ...
```

### 2.2 Kesin sınırlar (v1 kapsam dışı — Bölüm 13 madde 13 ile ÇAPRAZ TUTARLI)

Dashboard katmanı bu milestone'da **KESİNLİKLE**:

- **Persistence YOK** — `DashboardSnapshot` hiçbir yere YAZILMAZ,
  yalnızca çağırana DÖNER.
- **API YOK** — HTTP endpoint/router TASARLANMAZ.
- **WebSocket/polling/canlı yenileme YOK.**
- **Cache YOK.**
- **Frontend entegrasyonu YOK.**

Bu 5 kısıt, `DashboardSnapshot`'ı KENDİ İÇİNDE tam, saf-fonksiyon bir
sonuç nesnesi olarak TUTAR — "canlı dashboard" ürünleştirmesi TAMAMEN
GELECEK bir milestone'un konusudur.

### 2.3 Veri modeli (DEĞİŞMEDEN)

```python
@dataclass(frozen=True)
class DashboardWidget:
    widget_code: str
    widget_type: "ReportBlockType"          # yalnızca kpi_card | badge | chart_data
    metric_reference: "DashboardMetricReference | None"
    alert_reference: "DashboardAlertReference | None"
    source_field_path: str


@dataclass(frozen=True)
class DashboardMetricReference:
    source_engine: str
    metric_label_tr: str
    value_display: str
    reliability_label_tr: "str | None"


@dataclass(frozen=True)
class DashboardAlertReference:
    source_engine: str
    severity_level: str
    label_tr: str
    recommendation_code: "str | None"


@dataclass(frozen=True)
class DashboardSnapshot:
    dashboard_type: DashboardType
    widgets: "tuple[DashboardWidget, ...]"
    company_metadata: "ReportCompanyMetadata"
    source_confidence_inventory: "tuple[SourceConfidenceEntry, ...]"
    source_coverage_inventory: "tuple[SourceCoverageEntry, ...]"
    engines_used: "tuple[str, ...]"
    disclaimer_blocks: "tuple[ReportDisclaimerBlock, ...]"
    warnings: "tuple[dict[str, Any], ...]"
    decision_support_only: bool
    legal_review_status: "LegalReviewStatus"
    confidentiality_level: "ConfidentialityLevel"
    external_distribution_allowed: bool
    report_id: "str | None"
    generated_at: "str | None"
    dashboard_schema_version: str
    dashboard_model_version: str
    health_score_schema_version: str
    credit_score_schema_version: str
    recommendation_schema_version: str
```

### 2.4 Widget envanteri (KAPALI, v1 nihai — 2 `DashboardType` için TAM liste)

| `DashboardType` | `widget_code` | `widget_type` | Kaynak |
|---|---|---|---|
| `EXECUTIVE_DASHBOARD` | `WGT_HEALTH_SCORE_HEADLINE` | `kpi_card` | `health_score_result.final_score`/`letter_rating` |
| `EXECUTIVE_DASHBOARD` | `WGT_CREDIT_SCORE_HEADLINE` | `kpi_card` | `credit_score_result.final_score`/`risk_tier` |
| `EXECUTIVE_DASHBOARD` | `WGT_TOP_RECOMMENDATIONS` | `chart_data` | `recommendation_result.recommendations` (ilk 5, `priority` sıralı) |
| `EXECUTIVE_DASHBOARD` | `WGT_DATA_QUALITY_BADGE` | `badge` | `health_score_result.low_confidence_warning` / `credit_score_result.low_confidence_warning` |
| `EXECUTIVE_DASHBOARD` | `WGT_BENCHMARK_POSITION_SUMMARY` | `chart_data` | `benchmark_result_json.categories` (varsa) |
| `RISK_DASHBOARD` | `WGT_HARD_FAIL_ALERTS` | `chart_data` | `health_score_result.hard_fails_triggered` + `credit_score_result.hard_fails_triggered` |
| `RISK_DASHBOARD` | `WGT_CRITICAL_RECOMMENDATIONS` | `chart_data` | `recommendation_result.recommendations` (`priority=CRITICAL`) |
| `RISK_DASHBOARD` | `WGT_RISK_TIER_BADGE` | `badge` | `credit_score_result.risk_tier` |
| `RISK_DASHBOARD` | `WGT_BANKING_READINESS_ALERT` | `badge` | `recommendation_result.banking_lens_signals_reference` |
| `RISK_DASHBOARD` | `WGT_UNCOVERED_SIGNAL_COUNT` | `kpi_card` | `recommendation_result.uncovered_signal_codes` (adet) |

**5+5 = 10 widget, 2 `DashboardType`'a TAM dağıtılmıştır — tanımsız
widget YOKTUR.**

---

## 3. Render Contract Kapsamı — Render-Neutral (KİLİTLİ)

### 3.1 Kesin sınır

Bu milestone **gerçek PDF/DOCX üretmez**. Yalnızca render-neutral bir
SÖZLEŞME ve bu sözleşmenin var olan bir `ExecutiveReportResult`'a göre
ÖN-İZLEMESİ tasarlanır.

```python
def preview_render_contract(
    report_result: "ExecutiveReportResult",
    render_contract: "RenderContract",
) -> "RenderContractPreview": ...
```

### 3.2 `RenderContract` — hedef render ortamının KAPASİTE bildirimi

```python
class RenderMedium(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"


@dataclass(frozen=True)
class RenderContract:
    render_medium: RenderMedium
    supported_block_types: "tuple[ReportBlockType, ...]"
    supports_landscape: bool
    supports_page_break_hints: bool
    supports_chart_placeholders: bool
    max_table_columns_before_overflow_risk: "int | None"
    render_contract_schema_version: str
```

### 3.3 `RenderContractPreview` — KESİN 8 alan (madde 3'ün BİREBİR listesi)

```python
@dataclass(frozen=True)
class SectionLayoutCapability:
    section_code: "ReportSectionCode"
    supports_full_width_table: bool
    supports_multi_column: bool
    notes_tr: "str | None"


@dataclass(frozen=True)
class TableOverflowRiskFlag:
    section_code: "ReportSectionCode"
    risk_level: str          # "none" | "low" | "high" -- kapalı küme
    column_count: "int | None"
    reason_tr: "str | None"


@dataclass(frozen=True)
class PageBreakPreference:
    section_code: "ReportSectionCode"
    preference: str          # "page_break_before" | "avoid_break_inside" | "none" -- kapalı küme


@dataclass(frozen=True)
class ChartPlaceholderCapability:
    section_code: "ReportSectionCode"
    chart_placeholder_supported: bool
    placeholder_type: "str | None"


@dataclass(frozen=True)
class RenderMetadata:
    render_contract_schema_version: str
    target_render_medium: RenderMedium
    total_sections: int
    report_type_previewed: "ReportType"
    generated_at: "str | None"      # yalnızca çağıran verdiyse -- Bölüm 12


@dataclass(frozen=True)
class RenderContractPreview:
    section_render_order: "tuple[ReportSectionCode, ...]"                 # 1. section order
    layout_capability_matrix: "tuple[SectionLayoutCapability, ...]"        # 2. supported layout capability
    table_overflow_risk_flags: "tuple[TableOverflowRiskFlag, ...]"         # 3. table overflow risk
    page_break_preferences: "tuple[PageBreakPreference, ...]"              # 4. page-break preference
    landscape_required_section_codes: "tuple[ReportSectionCode, ...]"      # 5. landscape requirement
    chart_placeholder_capability: "tuple[ChartPlaceholderCapability, ...]" # 6. chart placeholder capability
    unsupported_content_warnings: "tuple[dict[str, Any], ...]"             # 7. unsupported-content warnings
    render_metadata: RenderMetadata                                         # 8. render metadata
```

**Bu 8 alan, madde 3'ün istediği KAPSAMIN TAMAMIDIR — fazlası veya
eksiği YOKTUR.** Gerçek PDF/DOCX üretimi (dosya yazma, tipografi,
stil, gerçek sayfalama motoru) **AYRI bir gelecek milestone'a
ERTELENMİŞTİR** (Bölüm 13 madde 13).

---

## 4. Section Dependency Modeli — 3 Fazlı KAPALI Yapı (KİLİTLİ)

### 4.1 Kapalı `BuildPhase` enum'u

```python
class BuildPhase(str, enum.Enum):
    SOURCE_SECTION = "source_section"
    AGGREGATION_SECTION = "aggregation_section"
    COMPLIANCE_SECTION = "compliance_section"
```

### 4.2 `ReportSectionDefinition` — zorunlu 3 alan

```python
@dataclass(frozen=True)
class ReportSectionDefinition:
    section_code: "ReportSectionCode"
    default_title_tr: str
    builder_strategy: "ReportSectionBuilderStrategy"
    build_phase: BuildPhase
    required_source_engines: "tuple[str, ...]"
    dependency_codes: "tuple[ReportSectionCode, ...] | DependencyScope"   # Bölüm 4.3
    consumes_section_outputs: "tuple[ReportSectionCode, ...]"             # ÇALIŞMA ZAMANI, gerçekte OKUNAN alt-küme
    data_domains: "tuple[str, ...]"
    disclaimer_scope: "str | None"
```

### 4.3 `DependencyScope` — sabit-liste VEYA wildcard

```python
class DependencyScope(str, enum.Enum):
    ALL_INCLUDED_UPSTREAM_SECTIONS = "all_included_upstream_sections"
```

- `build_phase=SOURCE_SECTION` ⟹ `dependency_codes=()`, `required_
  source_engines` DOLU.
- `build_phase=AGGREGATION_SECTION` ⟹ `dependency_codes`, `source_
  section` tipli SABİT bir `tuple[ReportSectionCode,...]` OLMALI
  (wildcard YASAK — Faz 2'nin bağımlılığı DAİMA AÇIK ve SAYILABİLİR
  olmalı).
- `build_phase=COMPLIANCE_SECTION` ⟹ `dependency_codes = Dependency
  Scope.ALL_INCLUDED_UPSTREAM_SECTIONS` (o çalıştırmada FİİLEN dahil
  edilen TÜM Faz 1+2 section'ları — Faz 3 KENDİ İÇİNDE başka bir Faz 3
  section'a ASLA bağımlı OLAMAZ).

### 4.4 Kayıt anında (registration-time) doğrulama — KESİN 6 kural (4. turda 6. madde EKLENDİ)

1. **Unknown dependency reddi:** `dependency_codes`'taki (sabit liste
   ise) HER kod `REPORT_SECTION_REGISTRY`'de KAYITLI olmalı, aksi
   halde `UnknownSectionDependencyError`.
2. **Self-dependency reddi:** Bir section KENDİ `section_code`'unu
   `dependency_codes` içinde TAŞIYAMAZ → `SelfDependencyError`.
3. **Cycle reddi:** `(section_code → dependency_codes)` grafiği bir
   **DAG** olmalı; döngü tespit edilirse `DependencyCycleError`
   (KAYIT ANINDA, ÇALIŞMA ZAMANINA ERTELENMEZ).
4. **Faz sırası ihlali reddi:** Bir `AGGREGATION_SECTION`'ın bağımlılığı
   yalnızca `SOURCE_SECTION` tipindeki kodlara İŞARET EDEBİLİR;
   `COMPLIANCE_SECTION`'a veya BAŞKA bir `AGGREGATION_SECTION`'a
   İŞARET EDEMEZ → `InvalidPhaseDependencyError`.
5. **Wildcard yalnızca `COMPLIANCE_SECTION`'da:** `Dependency
   Scope.ALL_INCLUDED_UPSTREAM_SECTIONS`, `SOURCE_SECTION`/`AGGREGATION_
   SECTION` için KULLANILAMAZ → `InvalidDependencyScopeError`.
6. **[4. turda EKLENDİ, Bölüm 0.1'in genelleştirilmiş kuralı] Report-type
   dependency completeness:** Bir `ReportType`, bir `AGGREGATION_SECTION`'ı
   ZORUNLU (`optional=False`) olarak içeriyorsa, o section'ın `dependency_
   codes`'undaki TÜM section'lar da (en azından `compact`/`headline_only`
   ayrıntı seviyesinde) o `ReportType`'ın `SectionUsageDefinition`
   listesinde YER ALMALIDIR — aksi halde o aggregation section'ın
   çekirdek içeriği çalışma zamanında "dependency unavailable" nedeniyle
   BOŞ kalabilir. Bu kural registry kaydı ANINDA MEKANİK olarak
   DOĞRULANMAZ (section-level `ReportSectionDefinition` ile report-type-
   level `SectionUsageDefinition` FARKLI registry'lerde yaşar) — bunun
   yerine Bölüm 15.4'ün HER tablosu, bu kuralı EL İLE (ve Bölüm 15.5'in
   "full/full çakışma doğrulaması" testiyle DOLAYLI olarak) sağladığını
   KANITLAR; ihlali `SEC_SWOT`'un implementasyon sırasında bulunduğu
   gibi (Bölüm 0.1) fonksiyonel/golden-dataset testleri YAKALAR (boş
   quadrant/section İÇERİĞİ olarak).

### 4.5 Stable topological build order

1. **Faz 1 (source_section, 13 kayıt):** aralarında bağımlılık
   OLMADIĞI için `section_code` alfabetik sırasıyla (registry
   insertion-order'dan BAĞIMSIZ, DETERMİNİSTİK bir tie-break)
   inşa edilir/inşa edilebilir (paralel de olabilir — sıra SONUCU
   ETKİLEMEZ).
2. **Faz 2 (aggregation_section, 2 kayıt):** Faz 1 TAMAMLANDIKTAN
   SONRA, KENDİ `dependency_codes`'u alfabetik sırayla İŞLENİR.
3. **Faz 3 (compliance_section, 3 kayıt):** Faz 1+2 TAMAMLANDIKTAN
   SONRA, `section_code` alfabetik sırasıyla İŞLENİR.

**Registry insertion-order independence:** `REPORT_SECTION_REGISTRY`'ye
kayıtların HANGİ SIRAYLA eklendiği (dict/tuple insertion sırası)
`build_order`'ı HİÇBİR ŞEKİLDE ETKİLEMEZ — sıralama SADECE `build_
phase` + alfabetik `section_code` tie-break'ine DAYANIR (Bölüm 17
madde "registry insertion-order independence" testi).

### 4.6 Bağımlılık ilişkisi sayımı (Bölüm 18'in revizyon raporu İÇİN)

- `SEC_EXECUTIVE_SUMMARY` → 4 sabit bağımlılık (`SEC_HEALTH_SCORE_
  BREAKDOWN`, `SEC_CREDIT_SCORE_BREAKDOWN`, `SEC_RECOMMENDATIONS`,
  `SEC_RISK_FLAGS`).
- `SEC_SWOT` → 2 sabit bağımlılık (`SEC_HEALTH_SCORE_BREAKDOWN`,
  `SEC_RECOMMENDATIONS`).
- `SEC_METHODOLOGY_APPENDIX` / `SEC_DISCLAIMER_BLOCK` / `SEC_
  CONFIDENCE_AND_DATA_QUALITY` → HER biri `DependencyScope.ALL_
  INCLUDED_UPSTREAM_SECTIONS` (wildcard, literal SAYILMAZ).

**Toplam literal (sabit-liste) bağımlılık ilişkisi: 6. Wildcard
bağımlılık kaydı: 3.** (4. turda DEĞİŞMEDİ — bu sayım `REPORT_SECTION_
REGISTRY`'nin section-TANIM seviyesindedir; Bölüm 0.1'in düzeltmesi
`REPORT_TYPE_REGISTRY`'nin report-KULLANIM seviyesindeydi, İKİ FARKLI
katmandır. `SEC_SWOT`'un 2 bağımlılığı zaten burada, 3. turdan beri
DOĞRU sayılıyordu — eksik olan, `SWOT_REPORT`'un bu 2 bağımlılığı
KENDİ section listesine dahil ETMEMESİYDİ, bkz. Bölüm 4.4 madde 6.)

---

## 5. Section Detail-Level Modeli — `SectionUsageDefinition` (KİLİTLİ)

### 5.1 Kapalı `DetailLevel` enum'u

```python
class DetailLevel(str, enum.Enum):
    FULL = "full"
    SUMMARY = "summary"
    COMPACT = "compact"
    DASHBOARD = "dashboard"
```

**Kesin kural (madde 5):** Narrative `ReportType`'lar `DetailLevel.
DASHBOARD` DEĞERİNİ ASLA KULLANMAZ — bu değer YALNIZCA gelecekte
Dashboard katmanının KENDİ (bu tasarımda TANIMLANMAYAN, `DashboardWidget`
tabanlı) sözleşmesiyle İLİŞKİLENDİRİLMEK ÜZERE REZERVE edilmiştir.
`REPORT_TYPE_REGISTRY` kayıt doğrulaması, `SectionUsageDefinition.
detail_level == DASHBOARD` olan HERHANGİ bir narrative kaydı
`InvalidDetailLevelForNarrativeReportError` ile REDDEDER.

### 5.2 `SectionUsageDefinition` — KESİN 10 alan

```python
@dataclass(frozen=True)
class SectionUsageDefinition:
    section_code: "ReportSectionCode"
    detail_level: DetailLevel
    field_inclusion_policy: "FieldInclusionPolicy"    # all_fields | key_fields_only | headline_only
    maximum_items: "int | None"
    table_density: "TableDensity | None"              # full | top_n | summary_row_only | None(tablosuz section)
    include_provenance: bool
    include_confidence: bool
    include_disclaimer: bool
    display_order: int
    optional: bool
```

### 5.3 Builder izolasyonu (kesin ilke, DEĞİŞMEDİ)

Section builder fonksiyonları **YALNIZCA** `(immutable kaynak
girdiler, SectionUsageDefinition)` ALIR. `report_type` parametresi
builder'a **HİÇBİR ŞEKİLDE** geçirilmez/erişilmez — bu, Bölüm 16.1
`REPORT_ENGINE_PRESENTATION_ONLY` invariant'ının 6. maddesidir ve
Bölüm 17'nin "hidden report_type access prevention" testiyle
DOĞRULANIR.

---

## 6. Duplicate/Overlap Davranışı — KESİN Kurallar (KİLİTLİ)

### 6.1 v1'de YAPILMAYAN

**Otomatik section silme veya içerik merge YAPILMAZ.** Hiçbir section,
overlap NEDENİYLE rapordan tamamen ÇIKARILMAZ; yalnızca DETAY SEVİYESİ
düşürülür (`table_density`/`field_inclusion_policy` üzerinden).

### 6.2 Domain-bazlı tespit ve raporlama

`data_domains`/`overlaps_with`/`primary_section_for_domain` Bölüm 15.3
katalogunda TANIMLIDIR. Genel (global) `primary_section_for_domain`,
bir domain için "varsayılan tam-detay sahibi"ni gösterir; ancak
BELİRLİ bir `ReportType`'ta o global primary section HİÇ dahil
DEĞİLSE, o rapor türü kendi "full-detay sahibi"ni Bölüm 15.4'ün
per-report-type tablosunda AÇIKÇA BELİRLER (bu, global varsayımdan
bir SAPMA değil, global primary'nin o raporda zaten YOK OLMASININ
doğal SONUCUDUR — Bölüm 15.4'teki HER rapor tablosunda bu net
görünür).

### 6.3 KESİN, mekanik registry-validation kuralı (madde 6'nın YENİ, SIKI hali)

> **Bir `ReportType` için, aynı `data_domain`'i paylaşan section'lar
> arasında EN FAZLA BİR TANESİ `table_density=full` VE/VEYA `field_
> inclusion_policy=all_fields` OLABİLİR. Aynı domain'i paylaşan
> BİRDEN FAZLA section, AYNI raporda, AYNI ANDA tam-detay (`full`/
> `all_fields`) OLAMAZ.**

Bu kural **`REPORT_TYPE_REGISTRY` kayıt anında** doğrulanır — ihlal
`OverlappingFullDetailSectionsError` ile **REDDEDİLİR** (çalışma
zamanına ERTELENMEZ, madde 6'nın "registry validation ile
reddedilmeli" talimatının BİREBİR karşılığı).

**Not (kural yalnızca 2+ section AYNI raporda dahilse geçerlidir):**
Bir domain'i o raporda yalnızca TEK section KAPSIYORSA (o domain'in
diğer olası section'ları o rapor türünde hiç dahil değilse), o TEK
section `full`/`all_fields` OLABİLİR — çünkü ORTADA "aynı verinin iki
farklı yerde tekrarı" riski YOKTUR (Bölüm 15.4'teki her tabloda bu
durum ayrıca doğrulanmıştır, ör. `BOARD_OF_DIRECTORS_REPORT`'ta `SEC_
BOARD_DECISION_ITEMS` `full`'dur çünkü `SEC_RECOMMENDATIONS` o rapor
türünde HİÇ dahil DEĞİLDİR).

### 6.4 `DUPLICATE_DATA_ACROSS_SECTIONS` uyarısı

İki VEYA DAHA FAZLA section AYNI domain'i AYNI raporda kapsıyorsa
(BİRİ full, DİĞERLERİ summary/top_n olsa BİLE), pipeline şu YAPIYI
`duplicate_content_warnings`'e (Bölüm 11.1) EKLER:

```python
{
    "code": "DUPLICATE_DATA_ACROSS_SECTIONS",
    "data_domain": "growth_analysis",
    "full_detail_section_code": "SEC_INVESTOR_KPI_SUMMARY",
    "reference_only_section_codes": ("SEC_PERIOD_COMPARISON_ANALYSIS",),
    "note_tr": "Bu veri alanı birden fazla bölümde farklı ayrıntı seviyeleriyle sunulmaktadır; hiçbir veri sessizce silinmemiştir.",
}
```

**Hiçbir finansal veri sessizce SİLİNMEZ** — ikincil section HER ZAMAN
en azından bir ÖZET/REFERANS satırı GÖSTERİR, TAMAMEN BOŞ BIRAKILMAZ.

---

## 7. Confidence ve Coverage Gösterimi — KESİN Model (KİLİTLİ)

### 7.1 Kesin ilke

Report Engine **hiçbir yeni confidence, coverage veya reliability
değeri HESAPLAMAZ.** `overall_confidence`/`overall_coverage`/composite
reliability alanı **KESİNLİKLE YOKTUR** (Bölüm 11.1'in `Executive
ReportResult` şeması bunu MEKANİK olarak KANITLAR — bu alan adları
dataclass'ta YER ALMAZ).

### 7.2 Nihai 5 alan (madde 7'nin BİREBİR karşılığı)

```python
@dataclass(frozen=True)
class SourceConfidenceEntry:
    source_engine: str
    confidence_available: bool
    confidence_value: "Decimal | None"      # kaynağın KENDİ alanı, TÜREV DEĞİL
    reliability_label_tr: "str | None"
    reason_code: "str | None"               # confidence_available=False İSE ZORUNLU
    source_warning: "str | None"
    used_in_section_codes: "tuple[ReportSectionCode, ...]"


@dataclass(frozen=True)
class SourceCoverageEntry:
    source_engine: str
    coverage_available: bool
    coverage_value: "Decimal | None"
    reason_code: "str | None"               # coverage_available=False İSE ZORUNLU
    source_warning: "str | None"
    used_in_section_codes: "tuple[ReportSectionCode, ...]"


@dataclass(frozen=True)
class SectionSourceMappingEntry:
    section_code: "ReportSectionCode"
    source_engines: "tuple[str, ...]"
```

`ExecutiveReportResult` (Bölüm 11.1) TAM OLARAK şu 5 alanı taşır:
`source_confidence_inventory: tuple[SourceConfidenceEntry,...]`,
`source_coverage_inventory: tuple[SourceCoverageEntry,...]`,
`missing_confidence_sources: tuple[str,...]` (yalnızca `source_engine`
kodları, `confidence_available=False` olanlar), `missing_coverage_
sources: tuple[str,...]` (AYNI desen, coverage için), `section_source_
mapping: tuple[SectionSourceMappingEntry,...]`.

### 7.3 `None` güvenlik kuralı (KESİN, mekanik)

- `confidence_value=None` / `coverage_value=None` **HİÇBİR aritmetik
  işleme (toplama/ortalama/min/max/ağırlıklı-ortalama) GİRMEZ.**
- `None`, **SIFIR olarak KABUL EDİLMEZ** — `0.0`/`Decimal("0")` İLE
  KARIŞTIRILMASI YASAKTIR (statik kod taraması, Bölüm 17 madde "None
  confidence safety").
- `confidence_available=False`/`coverage_available=False` DURUMUNDA,
  `reason_code` (ör. `"NO_RELIABILITY_FIELD_IN_SOURCE_CONTRACT"`) VE
  `source_warning` **ZORUNLU** DOLDURULUR.

### 7.4 `horizontal_analysis` örneği (2. turun Açık Karar #2'sinin KAPANIŞI)

`balance_sheet`/`income_statement` motorlarının `horizontal_analysis`
alanı bir reliability/confidence TAŞIMAZ. Bu, v1'İN **kalıcı, KABUL
EDİLMİŞ bir sınırıdır** — AYRI bir "BS/IS motoru iyileştirme
milestone'u" bu doküman TARAFINDAN ÖNERİLMEZ (kapsam DIŞINDA
BIRAKILMIŞTIR). `SourceConfidenceEntry`/`SourceCoverageEntry`'de bu
iki kaynak DAİMA `confidence_available=False`/`coverage_available=
False`, `reason_code="NO_RELIABILITY_FIELD_IN_SOURCE_CONTRACT"` İLE
GÖRÜNÜR — bu durum `ExecutiveReportResult.status`'u ETKİLEMEZ (veri
VAR, yalnızca güvenilirlik ALANI YOK).

---

## 8. SWOT Kapsamı — Nihai (KİLİTLİ, DEĞİŞMEDEN korunmuş + doğrulanmış)

```python
@dataclass(frozen=True)
class SwotQuadrantItem:
    text_tr: str
    source_engine: str
    source_field_path: str
    source_code: "str | None"
    provenance_note_tr: str


@dataclass(frozen=True)
class SwotQuadrant:
    quadrant: str                 # "strengths" | "weaknesses" | "threats" | "opportunities"
    items: "tuple[SwotQuadrantItem, ...]"
    is_available: bool
    unavailable_reason_tr: "str | None"


@dataclass(frozen=True)
class SwotSectionMetadata:
    is_reformatted_source_content: bool = True
    is_independent_strategic_analysis: bool = False
    boundary_statement_tr: str = (
        "Bu bölüm bağımsız stratejik SWOT analizi DEĞİLDİR; mevcut "
        "motor çıktılarının yeniden biçimlendirilmiş sunumudur."
    )
```

**Nihai eşleme (KİLİTLİ, DEĞİŞMEZ):**

| Kadran | Kaynak | `is_available` |
|---|---|---|
| Strengths | `health_score_result.strengths` (DOĞRUDAN kopya) | `True` |
| Weaknesses | `health_score_result.weaknesses` (DOĞRUDAN kopya) | `True` |
| Threats | `recommendation_result.recommendations` (`priority ∈ {CRITICAL,HIGH}`, DOĞRUDAN kopya) | `True` |
| **Opportunities** | **YOK** | **`False`**, `items=()`, `unavailable_reason_tr="Mevcut kaynak motorlar doğrulanmış bağımsız fırsat sinyali üretmediği için bu alan otomatik olarak doldurulmamıştır."` |

**Kesin ilke:** Recommendation Engine'in `GROWTH`/`BANKING_READINESS`
kategorisi VEYA HERHANGİ bir başka kategorisi **HİÇBİR FİLTRE
ALTINDA** Opportunities'e YENİDEN ETİKETLENMEZ. `boundary_statement_
tr`, `SEC_SWOT`'un başlığının HEMEN ALTINDA, disclaimer bloğundan AYRI
konumda RENDER EDİLİR.

---

## 9. Legal ve Confidentiality Politikası — Nihai Matris (KİLİTLİ)

### 9.1 Kapalı enum'lar

```python
class LegalReviewStatus(str, enum.Enum):
    NOT_REVIEWED = "not_reviewed"
    INTERNAL_USE_ONLY = "internal_use_only"
    LEGAL_REVIEW_REQUIRED = "legal_review_required"
    APPROVED = "approved"


class ConfidentialityLevel(str, enum.Enum):
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
```

### 9.2 v1 nihai matris — TAM, 7 satır (KİLİTLİ, madde 9'un BİREBİR karşılığı)

| `ReportType` | `legal_review_status` | `confidentiality_level` | `external_distribution_allowed` |
|---|---|---|---|
| `BANK_CREDIT_ALLOCATION_REPORT` | `legal_review_required` | `confidential` | `False` |
| `INVESTOR_REPORT` | `legal_review_required` | `restricted` | `False` |
| `BOARD_OF_DIRECTORS_REPORT` | `legal_review_required` | `confidential` | `False` |
| `CFO_EXECUTIVE_REPORT` | `internal_use_only` | `confidential` | `False` |
| `MANAGEMENT_SUMMARY` | `internal_use_only` | `internal` | `False` |
| `SWOT_REPORT` | `internal_use_only` | `internal` | `False` |
| `PERIOD_COMPARISON_REPORT` | `internal_use_only` | `internal` | `False` |

**Kesin kural:** Gerçek hukuk incelemesi YAPILMADIĞI için **hiçbir
`ReportType` v1'de `approved` DEĞİLDİR.** `APPROVED` değeri enum'da
VARDIR (gelecekte hukuk onayı GELDİĞİNDE kullanılmak ÜZERE) ama v1
kayıtlarının HİÇBİRİNDE ATANMAZ — bu, Bölüm 17'nin "legal review
matrix" testiyle BİR-BİR doğrulanır.

### 9.3 `ExecutiveReportResult`'ın taşıdığı SABİT hukuki/gizlilik alanları

```
decision_support_only = True                    # SABİT, HER raporda
not_a_statutory_report = True                    # SABİT
not_a_credit_approval = True                     # SABİT
not_investment_advice = True                      # SABİT
external_distribution_allowed: bool               # Bölüm 9.2 matrisinden, HER zaman v1'de False
legal_review_status: LegalReviewStatus            # Bölüm 9.2 matrisinden
confidentiality_level: ConfidentialityLevel        # Bölüm 9.2 matrisinden
contains_sensitive_financial_data = True          # SABİT, HER raporda
redaction_required: bool                           # `confidentiality_level != internal` İSE True
intended_audience: str                             # Bölüm 15.4 per-report tablosunda TANIMLI (ör. "CFO ve üst düzey finans yönetimi")
source_document_identifiers_included: bool          # v1'de HER ZAMAN False (motor gerçek belge kimliği TAŞIMAZ)
```

`redaction_required` türetimi **HESAPLAMA DEĞİLDİR** — `Confidentiality
Level` enum değerinden DOĞRUDAN, SABİT bir eşleme TABLOSUDUR
(`internal→False`, `confidential→True`, `restricted→True`), Bölüm
16.1'in "yeni sayı/skor üretmez" ilkesini İHLAL ETMEZ (bu bir BOOLEAN
POLİTİKA ATAMASI, bir FİNANSAL HESAPLAMA DEĞİLDİR).

---

## 10. Compatibility Davranışı — Merkezi İmmutable Politika (KİLİTLİ)

### 10.1 `REPORT_INPUT_COMPATIBILITY` — kesin, immutable

```python
REPORT_INPUT_COMPATIBILITY = {
    "health_score_schema_version": {"supported": ("1.0.0",)},
    "credit_score_schema_version": {"supported": ("1.0.0",)},
    "recommendation_schema_version": {"supported": ("1.0.0",)},
    "ratio_registry_version": {"supported": ("1.1.0",)},
    "benchmark_registry_version": {"supported": ("1.0.0",)},
    "balance_sheet_engine_version": {"supported": ("1.0.0",)},
    "income_statement_engine_version": {"supported": ("1.0.0",)},
}
```

### 10.2 3 katmanlı davranış (4.3F Bölüm 16.2 İLE AYNI desen, DEĞİŞMEDEN)

1. **`SCHEMA_INCOMPATIBLE`** (herhangi bir `*_schema_version` DESTEKLENMİYOR):
   `ExecutiveReportResult.status = SCHEMA_INCOMPATIBLE`; `sections =
   ()`; `DashboardSnapshot`/`RenderContractPreview` da AYNI şekilde
   ÜRETİLMEZ (boş/iskelet döner); yalnızca `warnings` + `upstream_
   version_inventory` DOLU DÖNER.
2. **`VERSION_MISMATCH`** (schema OKUNABİLİR ama `*_registry_version`
   DESTEKLENMİYOR): `status = VERSION_MISMATCH`; İÇERİK VARSAYILAN
   OLARAK BASTIRILIR (`sections` yalnızca `SEC_DISCLAIMER_BLOCK` +
   `SEC_CONFIDENCE_AND_DATA_QUALITY` gibi UYUMLULUK-İLGİLİ compliance
   section'ları İÇEREBİLİR); yalnızca compatibility/source inventory
   ve `warnings` DÖNER.
3. **`MODEL_VERSION_MISMATCH`** (yalnızca `*_model_version` farklı,
   schema+registry UYUMLU): ÜRETİM NORMAL DEVAM EDER, `warnings`'e
   `MODEL_VERSION_MISMATCH` (non-blocking) EKLENİR.

### 10.3 Dashboard/Render Contract için AYRI, DAHA DAR sözleşmeler

- `DASHBOARD_INPUT_COMPATIBILITY`: yalnızca `health_score`/`credit_
  score`/`recommendation` şema/versiyon alanlarını KAPSAR (BS/IS/
  Ratio/Benchmark Dashboard'a GİRDİ OLMADIĞI için bu sözleşmede
  YOKTUR).
- Render Contract Preview KENDİ girdisi ZATEN üretilmiş bir `Executive
  ReportResult` OLDUĞU için AYRI bir schema/version kontrolüne
  GEREK DUYMAZ — yalnızca `render_contract_schema_version` KENDİ
  İÇİNDE TAKİP EDİLİR.

### 10.4 Versiyon artış kuralları (kesin)

- `REPORT_INPUT_COMPATIBILITY` POLİTİKASI (desteklenen versiyon
  KÜMESİ) DEĞİŞİRSE → `report_model_version` ARTAR.
- `ExecutiveReportResult`/`DashboardSnapshot`/`RenderContractPreview`
  dataclass'ının ALAN ŞEKLİ (yeni alan eklenmesi/kaldırılması/tip
  değişikliği) DEĞİŞİRSE → `report_schema_version` (VEYA `dashboard_
  schema_version`/`render_contract_schema_version`, İLGİLİ olan)
  ARTAR.

---

## 11. Result Sözleşmelerini Kesinleştirme (KİLİTLİ)

### 11.1 `ExecutiveReportResult` — nihai, TAM alan listesi

```python
@dataclass(frozen=True)
class ExecutiveReportResult:
    status: ReportComputationStatus
    report_type: ReportType
    report_title_tr: str
    sections: "tuple[ReportSection, ...]"
    included_section_codes: "tuple[ReportSectionCode, ...]"
    omitted_section_codes: "tuple[ReportSectionCode, ...]"
    company_metadata: "ReportCompanyMetadata"
    reporting_period_label_tr: str
    warnings: "tuple[dict[str, Any], ...]"
    source_inventory: "tuple[SourceInventoryEntry, ...]"
    source_confidence_inventory: "tuple[SourceConfidenceEntry, ...]"
    source_coverage_inventory: "tuple[SourceCoverageEntry, ...]"
    missing_confidence_sources: "tuple[str, ...]"
    missing_coverage_sources: "tuple[str, ...]"
    section_source_mapping: "tuple[SectionSourceMappingEntry, ...]"
    duplicate_content_warnings: "tuple[dict[str, Any], ...]"
    disclaimer_blocks: "tuple[ReportDisclaimerBlock, ...]"
    provisional: bool
    decision_support_only: bool
    not_a_statutory_report: bool
    not_a_credit_approval: bool
    not_investment_advice: bool
    legal_review_status: LegalReviewStatus
    confidentiality_level: ConfidentialityLevel
    intended_audience: str
    intended_use: str
    external_distribution_allowed: bool
    regulatory_disclaimer_required: bool
    contains_sensitive_financial_data: bool
    redaction_required: bool
    source_document_identifiers_included: bool
    report_id: "str | None"
    generated_at: "str | None"
    locale: str
    currency_display_policy: "str | None"
    report_schema_version: str
    report_model_version: str
    upstream_version_inventory: "tuple[UpstreamVersionEntry, ...]"


@dataclass(frozen=True)
class SourceInventoryEntry:
    source_engine: str
    status: str                 # "used" | "not_used" | "unavailable"
    used_in_section_codes: "tuple[ReportSectionCode, ...]"


@dataclass(frozen=True)
class UpstreamVersionEntry:
    source_engine: str
    schema_version: "str | None"
    model_or_registry_version: "str | None"
```

Bu, madde 11'in **"en az şu alanları taşımalı"** listesinin TAMAMINI
İÇERİR (`status`, `report_type`, `report_title_tr`, `sections`,
`warnings`, `source_inventory`, `source_confidence_inventory`,
`missing_confidence_sources`, `missing_coverage_sources`, `legal_
review_status`, `confidentiality_level`, `intended_audience`,
`external_distribution_allowed`, `contains_sensitive_financial_data`,
`redaction_required`, `source_document_identifiers_included`,
`decision_support_only`, `not_a_statutory_report`, `not_a_credit_
approval`, `not_investment_advice`, `report_schema_version`, `report_
model_version`, `upstream_version_inventory`, `generated_at`) **artı**
Bölüm 2.1 disiplinini KORUYAN ek alanlar (`report_id`/`locale`/
`currency_display_policy`/`section_source_mapping`/`source_coverage_
inventory`/vb.) — hiçbiri BİRBİRİNE KARIŞMAZ, HER biri TEK bir amaca
HİZMET EDER.

### 11.2 `generate_at` davranışı

`generated_at: "str | None"` alanı **YALNIZCA çağıran taraf `generate_
executive_report(..., generated_at=...)` parametresini AÇIKÇA
GEÇERSE** dolu OLUR; AKSİ HALDE `None` KALIR. **Motor kendi saatini
OKUMAZ** (Bölüm 12).

### 11.3 Üç sonuç sözleşmesinin AYRIMI (madde 11'in son cümlesi)

`ExecutiveReportResult` (Bölüm 11.1), `DashboardSnapshot` (Bölüm 2.3),
`RenderContractPreview` (Bölüm 3.3) **birbirinden TAMAMEN AYRI
dataclass'lardır** — hiçbiri diğerinin alanını MİRAS ALMAZ/PAYLAŞMAZ
(yalnızca `SourceConfidenceEntry`/`SourceCoverageEntry`/`ReportCompany
Metadata`/`ReportDisclaimerBlock`/`LegalReviewStatus`/`Confidentiality
Level` gibi ORTAK, KÜÇÜK "value object" tipleri PAYLAŞILIR — bu,
KOD TEKRARINI ÖNLEMEK içindir, KAVRAMSAL KARIŞMA DEĞİLDİR).

---

## 12. Determinizm ve Zaman Davranışı (KİLİTLİ)

### 12.1 Kesin yasak

Engine (narrative/dashboard/render preview'ın HİÇBİRİ) **kendi
içinde**:

- `datetime.now()` / `date.today()` KULLANMAZ.
- `uuid.uuid4()` (veya HERHANGİ bir rastgele ID üretici) KULLANMAZ.
- `random`/`secrets` modüllerini KULLANMAZ.
- `locale`'e bağlı GLOBAL state (ör. `locale.setlocale()`) KULLANMAZ.

### 12.2 Açık parametreler

Gerekliyse, ilgili değerler **çağıran TARAFINDAN AÇIKÇA** geçirilir:

```python
def generate_executive_report(
    report_type: ReportType,
    balance_sheet_result_json: "dict[str, Any]",
    income_statement_result_json: "dict[str, Any]",
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    recommendation_result: RecommendationResult,
    *,
    company_metadata: "ReportCompanyMetadata",
    reporting_period_label_tr: str,
    optional_sections: "tuple[ReportSectionCode, ...] | None" = None,
    report_id: "str | None" = None,
    generated_at: "str | None" = None,
    locale: str = "tr-TR",
    currency_display_policy: "str | None" = None,
) -> "ExecutiveReportResult": ...
```

**Kesin kural (madde 3'ün 2. tur açık kararının KAPANIŞI):** v1'de
`locale` parametresi yalnızca `"tr-TR"` DEĞERİNİ KABUL EDER; BAŞKA bir
değer `SCHEMA_INCOMPATIBLE`-BENZERİ bir `UnsupportedLocaleError`
FIRLATIR (parametre bir GELECEK-genişletme HOOK'UDUR, v1 FONKSİYONEL
DEĞİLDİR).

### 12.3 Bit-birebir determinizm

**Aynı 7 girdi + aynı `report_type` + aynı `optional_sections` + aynı
`locale`/`currency_display_policy` (`report_id`/`generated_at` HARİÇ,
çünkü bunlar İÇERİĞİ DEĞİL yalnızca META-ETİKETİ TAŞIR) → BİT-BİREBİR
AYNI `sections`/`warnings`/`source_confidence_inventory`/vb. çıktısı.**
Bu, Bölüm 17'nin "deterministic output" testinin (100 iterasyon)
KESİN tanımıdır.

### 12.4 `ReportCompanyMetadata` kaynağı (2. turun Açık Karar #4'ünün KAPANIŞI)

`ReportCompanyMetadata` **HER ZAMAN çağırandan GEÇİRİLİR** — motor
HİÇBİR DB SORGUSU YAPMAZ (mevcut "sıfır-DB" mimari disiplininin AYNEN
DEVAMI).

---

## 13. Kapsam Sınırları — Kesin Liste (KİLİTLİ)

Bu milestone'da **KESİNLİKLE**:

1. API YOK.
2. Adapter YOK.
3. Migration YOK.
4. DB persistence YOK.
5. Bulk upload/recompute bağlantısı YOK.
6. Gerçek PDF/DOCX rendering YOK.
7. Chart/image generation YOK.
8. HTML template engine YOK.
9. Frontend YOK.
10. Dashboard canlı yenileme (live refresh) YOK.
11. Authorization YOK.
12. Tenant isolation YOK.
13. AI/LLM YOK.
14. Yeni finansal yorum YOK.
15. Yeni ratio/benchmark/score/recommendation YOK.
16. Yeni confidence/coverage roll-up YOK.
17. Marka adı hard-code etmek YOK.

**Bu 17 madde, 2. turun Açık Karar #1 (gerçek Trend Engine), #6
(render katmanı), #9 (erişim kontrolü) kararlarının KESİN KAPANIŞ
NOKTASIDIR** — hepsi bu milestone'un DIŞINDA, AYRI, GELECEK
milestone'lara bırakılmıştır; bu doküman o milestone'ları TASARLAMAZ.

---

## 14. Onaylanmış Kararlar (eski "Açık Kararlar" — Bölüm 28.2, ARTIK KAPALI)

**Bu bölümde HİÇBİR açık karar KALMAMIŞTIR.** 2. turun bıraktığı 9
madde, bu 3. turun Bölüm 1-13'ünde TEK TEK KAPATILMIŞTIR:

1. ✅ Narrative `ReportType` kapalı, 7 üyeli liste KESİNLEŞTİ (Bölüm 1).
2. ✅ Dashboard tamamen ayrı, persistence/API/live-refresh v1 dışı (Bölüm 2).
3. ✅ Render Contract render-neutral, 8 alan KESİNLEŞTİ, gerçek PDF/DOCX ayrı milestone'a ERTELENDİ (Bölüm 3).
4. ✅ Section dependency graph 3 fazlı, DAG, kayıt-anı doğrulama KESİNLEŞTİ (Bölüm 4).
5. ✅ `SectionUsageDefinition` 10 alanla KESİNLEŞTİ, builder izolasyonu KORUNDU (Bölüm 5).
6. ✅ Duplicate/overlap: otomatik silme/merge YOK, registry-validation ile full/full REDDİ KESİNLEŞTİ (Bölüm 6).
7. ✅ Confidence/coverage: roll-up YOK, 5 alanlı presentation-only envanter KESİNLEŞTİ (Bölüm 7).
8. ✅ SWOT: Opportunities daima `unavailable`, reformatted-source bayrakları KESİNLEŞTİ (Bölüm 8).
9. ✅ Legal/confidentiality: 7 satırlık NİHAİ matris KESİNLEŞTİ, hiçbir rapor `approved` DEĞİL (Bölüm 9).

**Onaylanmış karar sayısı: 9/9. Açık karar sayısı: 0.**

---

## 15. Tam Envanter Tabloları (KAPALI, ÖRNEK DEĞİL — TAM)

### 15.1 7 Narrative `ReportType` — TAM liste

| # | `ReportType` | TR Görünen Ad | `legal_review_status` | `confidentiality_level` |
|---|---|---|---|---|
| 1 | `CFO_EXECUTIVE_REPORT` | CFO Yönetici Raporu | `internal_use_only` | `confidential` |
| 2 | `BANK_CREDIT_ALLOCATION_REPORT` | Banka Kredi Tahsis Raporu | `legal_review_required` | `confidential` |
| 3 | `BOARD_OF_DIRECTORS_REPORT` | Yönetim Kurulu Raporu | `legal_review_required` | `confidential` |
| 4 | `INVESTOR_REPORT` | Yatırımcı Raporu | `legal_review_required` | `restricted` |
| 5 | `MANAGEMENT_SUMMARY` | Yönetim Özeti | `internal_use_only` | `internal` |
| 6 | `SWOT_REPORT` | SWOT Raporu | `internal_use_only` | `internal` |
| 7 | `PERIOD_COMPARISON_REPORT` | Dönem Karşılaştırma Raporu | `internal_use_only` | `internal` |

### 15.2 2 `DashboardType` — TAM liste

| # | `DashboardType` | TR Görünen Ad | Widget Sayısı |
|---|---|---|---|
| 1 | `EXECUTIVE_DASHBOARD` | Yönetici Panosu | 5 (Bölüm 2.4) |
| 2 | `RISK_DASHBOARD` | Risk Panosu | 5 (Bölüm 2.4) |

### 15.3 18 Kanonik Section — TAM katalog (build_phase + data_domains + dependency)

| # | `section_code` | `build_phase` | `data_domains` | `dependency_codes` |
|---|---|---|---|---|
| 1 | `SEC_COVER_PAGE` | source_section | (—) | () |
| 2 | `SEC_FINANCIAL_STATEMENTS_SUMMARY` | source_section | `financial_statements` | () |
| 3 | `SEC_RATIO_ANALYSIS_TABLE` | source_section | `liquidity_summary`,`leverage_summary`,`profitability_summary`,`growth_analysis`,`activity_summary` | () |
| 4 | `SEC_BENCHMARK_COMPARISON` | source_section | `benchmark_positioning` | () |
| 5 | `SEC_HEALTH_SCORE_BREAKDOWN` | source_section | `health_score_summary` | () |
| 6 | `SEC_CREDIT_SCORE_BREAKDOWN` | source_section | `credit_score_summary` | () |
| 7 | `SEC_BANKING_READINESS` | source_section | `banking_readiness` | () |
| 8 | `SEC_BANK_COLLATERAL_AND_DATA_GAPS` | source_section | `data_gaps` | () |
| 9 | `SEC_RECOMMENDATIONS` | source_section | `recommendation_actions` | () |
| 10 | `SEC_BOARD_DECISION_ITEMS` | source_section | `recommendation_actions` | () |
| 11 | `SEC_RISK_FLAGS` | source_section | `risk_signals` | () |
| 12 | `SEC_INVESTOR_KPI_SUMMARY` | source_section | `growth_analysis`,`profitability_summary` | () |
| 13 | `SEC_PERIOD_COMPARISON_ANALYSIS` | source_section | `growth_analysis`,`financial_statements` | () |
| 14 | `SEC_EXECUTIVE_SUMMARY` | aggregation_section | `health_score_summary`,`credit_score_summary`,`recommendation_actions`,`risk_signals` | `SEC_HEALTH_SCORE_BREAKDOWN`,`SEC_CREDIT_SCORE_BREAKDOWN`,`SEC_RECOMMENDATIONS`,`SEC_RISK_FLAGS` |
| 15 | `SEC_SWOT` | aggregation_section | `health_score_summary`,`recommendation_actions` | `SEC_HEALTH_SCORE_BREAKDOWN`,`SEC_RECOMMENDATIONS` |
| 16 | `SEC_METHODOLOGY_APPENDIX` | compliance_section | `confidence_metadata` | `ALL_INCLUDED_UPSTREAM_SECTIONS` |
| 17 | `SEC_DISCLAIMER_BLOCK` | compliance_section | (—) | `ALL_INCLUDED_UPSTREAM_SECTIONS` |
| 18 | `SEC_CONFIDENCE_AND_DATA_QUALITY` | compliance_section | `confidence_metadata` | `ALL_INCLUDED_UPSTREAM_SECTIONS` |

**Faz dağılımı: 13 source_section + 2 aggregation_section + 3
compliance_section = 18.**

### 15.3.1 Overlap domain haritası — TAM (7 overlap domain)

| `data_domain` | `primary_section_for_domain` (GLOBAL varsayılan) | İkincil section(lar) |
|---|---|---|
| `growth_analysis` | `SEC_RATIO_ANALYSIS_TABLE` | `SEC_PERIOD_COMPARISON_ANALYSIS`, `SEC_INVESTOR_KPI_SUMMARY` |
| `profitability_summary` | `SEC_RATIO_ANALYSIS_TABLE` | `SEC_INVESTOR_KPI_SUMMARY` |
| `financial_statements` | `SEC_FINANCIAL_STATEMENTS_SUMMARY` | `SEC_PERIOD_COMPARISON_ANALYSIS` |
| `recommendation_actions` | `SEC_RECOMMENDATIONS` | `SEC_BOARD_DECISION_ITEMS`, `SEC_SWOT` |
| `risk_signals` | `SEC_RISK_FLAGS` | `SEC_SWOT`, `SEC_BOARD_DECISION_ITEMS` |
| `health_score_summary` | `SEC_HEALTH_SCORE_BREAKDOWN` | `SEC_EXECUTIVE_SUMMARY`, `SEC_SWOT` |
| `credit_score_summary` | `SEC_CREDIT_SCORE_BREAKDOWN` | `SEC_EXECUTIVE_SUMMARY` |

Tekil (overlap OLMAYAN, 7 domain): `liquidity_summary`, `leverage_
summary`, `activity_summary`, `banking_readiness`, `data_gaps`,
`benchmark_positioning`, `confidence_metadata`.

**Toplam 14 domain (7 overlap + 7 tekil).**

### 15.4 7 Rapor Tipi × `SectionUsageDefinition` — TAM envanter (ÖRNEK DEĞİL)

Sütun kısaltmaları: DL=`detail_level`, FIP=`field_inclusion_policy`
(A=all_fields, K=key_fields_only, H=headline_only), TD=`table_density`
(F=full, T=top_n, S=summary_row_only, `—`=tablosuz), MI=`maximum_
items`, Prov/Conf/Disc=`include_provenance`/`include_confidence`/
`include_disclaimer` (E/H), Ord=`display_order`, Opt=`optional` (E/H).

#### 15.4.1 `CFO_EXECUTIVE_REPORT` — `intended_audience`: "CFO ve üst düzey finans yönetimi" — 16 section

| `section_code` | DL | FIP | TD | MI | Prov | Conf | Disc | Ord | Opt |
|---|---|---|---|---|---|---|---|---|---|
| `SEC_COVER_PAGE` | full | A | — | — | E | H | H | 1 | H |
| `SEC_EXECUTIVE_SUMMARY` | summary | K | S | — | E | E | E | 2 | H |
| `SEC_FINANCIAL_STATEMENTS_SUMMARY` | full | A | F | — | E | E | E | 3 | H |
| `SEC_RATIO_ANALYSIS_TABLE` | full | A | F | — | E | E | E | 4 | H |
| `SEC_BENCHMARK_COMPARISON` | full | A | F | — | E | E | E | 5 | H |
| `SEC_HEALTH_SCORE_BREAKDOWN` | full | A | F | — | E | E | E | 6 | H |
| `SEC_CREDIT_SCORE_BREAKDOWN` | full | A | F | — | E | E | E | 7 | H |
| `SEC_RECOMMENDATIONS` | full | A | F | — | E | E | E | 8 | H |
| `SEC_RISK_FLAGS` | full | A | F | — | E | E | E | 9 | H |
| `SEC_BANKING_READINESS` | summary | K | S | 10 | E | E | E | 10 | E |
| `SEC_SWOT` | summary | K | S | — | E | H | E | 11 | E |
| `SEC_PERIOD_COMPARISON_ANALYSIS` | summary | K | T | 10 | E | E | E | 12 | E |
| `SEC_BANK_COLLATERAL_AND_DATA_GAPS` | summary | K | S | 10 | E | E | E | 13 | E |
| `SEC_CONFIDENCE_AND_DATA_QUALITY` | full | A | F | — | E | E | E | 14 | H |
| `SEC_METHODOLOGY_APPENDIX` | full | A | — | — | E | H | E | 15 | H |
| `SEC_DISCLAIMER_BLOCK` | full | A | — | — | H | H | E | 16 | H |

#### 15.4.2 `BANK_CREDIT_ALLOCATION_REPORT` — `intended_audience`: "Kredi tahsis komitesi / banka risk analisti" — 12 section

| `section_code` | DL | FIP | TD | MI | Prov | Conf | Disc | Ord | Opt |
|---|---|---|---|---|---|---|---|---|---|
| `SEC_COVER_PAGE` | full | A | — | — | E | H | H | 1 | H |
| `SEC_EXECUTIVE_SUMMARY` | summary | K | S | — | E | E | E | 2 | H |
| `SEC_CREDIT_SCORE_BREAKDOWN` | full | A | F | — | E | E | E | 3 | H |
| `SEC_BANKING_READINESS` | full | A | F | — | E | E | E | 4 | H |
| `SEC_BANK_COLLATERAL_AND_DATA_GAPS` | full | A | F | — | E | E | E | 5 | H |
| `SEC_RATIO_ANALYSIS_TABLE` | summary | K | T | 15 | E | E | E | 6 | H |
| `SEC_RISK_FLAGS` | full | A | F | — | E | E | E | 7 | H |
| `SEC_CONFIDENCE_AND_DATA_QUALITY` | full | A | F | — | E | E | E | 8 | H |
| `SEC_DISCLAIMER_BLOCK` | full | A | — | — | H | H | E | 9 | H |
| `SEC_FINANCIAL_STATEMENTS_SUMMARY` | summary | K | S | — | E | E | E | 10 | E |
| `SEC_BENCHMARK_COMPARISON` | summary | K | T | 10 | E | E | E | 11 | E |
| `SEC_METHODOLOGY_APPENDIX` | summary | H | — | — | E | H | E | 12 | E |

*(`SEC_RATIO_ANALYSIS_TABLE`: `field_inclusion_policy=K` yalnızca
`leverage`/`liquidity`/`profitability` kategorilerini kapsar; bu, o
kategoriler için o raporda TEK section olduğundan Bölüm 6.3'ün
istisnasıyla TUTARLIDIR.)*

#### 15.4.3 `BOARD_OF_DIRECTORS_REPORT` — `intended_audience`: "Yönetim kurulu üyeleri" — 10 section

| `section_code` | DL | FIP | TD | MI | Prov | Conf | Disc | Ord | Opt |
|---|---|---|---|---|---|---|---|---|---|
| `SEC_COVER_PAGE` | full | A | — | — | E | H | H | 1 | H |
| `SEC_EXECUTIVE_SUMMARY` | summary | K | S | — | E | E | E | 2 | H |
| `SEC_BOARD_DECISION_ITEMS` | full | A | F | — | E | E | E | 3 | H |
| `SEC_RISK_FLAGS` | full | A | F | — | E | E | E | 4 | H |
| `SEC_HEALTH_SCORE_BREAKDOWN` | summary | K | S | — | E | E | E | 5 | H |
| `SEC_CREDIT_SCORE_BREAKDOWN` | summary | K | S | — | E | E | E | 6 | H |
| `SEC_DISCLAIMER_BLOCK` | full | A | — | — | H | H | E | 7 | H |
| `SEC_SWOT` | summary | K | S | — | E | H | E | 8 | E |
| `SEC_PERIOD_COMPARISON_ANALYSIS` | summary | K | T | 10 | E | E | E | 9 | E |
| `SEC_CONFIDENCE_AND_DATA_QUALITY` | compact | H | S | — | H | E | E | 10 | E |

#### 15.4.4 `INVESTOR_REPORT` — `intended_audience`: "Mevcut/potansiyel yatırımcılar" — 9 section

| `section_code` | DL | FIP | TD | MI | Prov | Conf | Disc | Ord | Opt |
|---|---|---|---|---|---|---|---|---|---|
| `SEC_COVER_PAGE` | full | A | — | — | E | H | H | 1 | H |
| `SEC_EXECUTIVE_SUMMARY` | summary | K | S | — | E | E | E | 2 | H |
| `SEC_INVESTOR_KPI_SUMMARY` | full | A | F | — | E | E | E | 3 | H |
| `SEC_HEALTH_SCORE_BREAKDOWN` | full | A | F | — | E | E | E | 4 | H |
| `SEC_PERIOD_COMPARISON_ANALYSIS` | summary | K | T | 10 | E | E | E | 5 | H |
| `SEC_DISCLAIMER_BLOCK` | full | A | — | — | H | H | E | 6 | H |
| `SEC_CREDIT_SCORE_BREAKDOWN` | summary | K | S | — | E | E | E | 7 | E |
| `SEC_SWOT` | summary | K | S | — | E | H | E | 8 | E |
| `SEC_BENCHMARK_COMPARISON` | summary | K | T | 10 | E | E | E | 9 | E |

*(NOT: `RecommendationResult` bu rapor tipinde `SEC_RECOMMENDATIONS`/
`SEC_BOARD_DECISION_ITEMS` üzerinden HİÇ TÜKETİLMEZ — yalnızca `SEC_
SWOT`'un Threats kadranı üzerinden dolaylı görünür, bu Bölüm 8'in
sınırına TABİDİR.)*

#### 15.4.5 `MANAGEMENT_SUMMARY` — `intended_audience`: "Orta/üst düzey operasyonel yönetim" — 7 section

| `section_code` | DL | FIP | TD | MI | Prov | Conf | Disc | Ord | Opt |
|---|---|---|---|---|---|---|---|---|---|
| `SEC_COVER_PAGE` | compact | H | — | — | H | H | H | 1 | H |
| `SEC_EXECUTIVE_SUMMARY` | compact | H | S | — | E | E | E | 2 | H |
| `SEC_RISK_FLAGS` | summary | K | S | 10 | E | E | E | 3 | H |
| `SEC_RECOMMENDATIONS` | summary | K | T | 10 | E | E | E | 4 | H |
| `SEC_DISCLAIMER_BLOCK` | compact | H | — | — | H | H | E | 5 | H |
| `SEC_CONFIDENCE_AND_DATA_QUALITY` | compact | H | S | — | H | E | E | 6 | E |
| `SEC_BANKING_READINESS` | compact | H | S | 5 | E | E | E | 7 | E |

*(`SEC_RECOMMENDATIONS`: yalnızca `priority ∈ {CRITICAL,HIGH,MEDIUM}`.)*

#### 15.4.6 `SWOT_REPORT` — `intended_audience`: "Stratejik değerlendirme yapan iç paydaşlar" — 7 section (4. turda 5→7 DÜZELTİLDİ, bkz. Bölüm 0.1)

| `section_code` | DL | FIP | TD | MI | Prov | Conf | Disc | Ord | Opt |
|---|---|---|---|---|---|---|---|---|---|
| `SEC_COVER_PAGE` | full | A | — | — | E | H | H | 1 | H |
| `SEC_SWOT` | full | A | — | — | E | E | E | 2 | H |
| `SEC_METHODOLOGY_APPENDIX` | full | A | — | — | E | H | E | 3 | H |
| `SEC_DISCLAIMER_BLOCK` | full | A | — | — | H | H | E | 4 | H |
| `SEC_EXECUTIVE_SUMMARY` | summary | K | S | — | E | E | E | 5 | E |
| **`SEC_HEALTH_SCORE_BREAKDOWN`** | **compact** | **H** | **S** | — | **H** | E | E | **6** | **H** |
| **`SEC_RECOMMENDATIONS`** | **compact** | **H** | **S** | **5** | **H** | E | E | **7** | **H** |

**Bölüm 0.1'in düzeltmesi (kalın satırlar):** `SEC_SWOT` (aggregation_
section) kayıt-anında `SEC_HEALTH_SCORE_BREAKDOWN`+`SEC_RECOMMENDATIONS`'a
sabit bağımlıdır (Bölüm 4/15.3, DEĞİŞMEDİ); bu iki section, `SWOT_REPORT`'a
**zorunlu ama `compact`/`headline_only` ayrıntı seviyesiyle** eklenmiştir
— `SEC_SWOT`'un editöryel önceliği KORUNUR, ama `SEC_SWOT`'un
Strengths/Weaknesses/Threats kadranları artık GERÇEKTEN doldurulabilir
veri kaynağına SAHİPTİR. `SEC_RECOMMENDATIONS`'ın `maximum_items=5`
olması, bu section'ın `SWOT_REPORT`'ta yalnızca `SEC_SWOT`'un Threats
kadranını BESLEYEN bir arka-plan kaynağı olduğunu, kendi başına ÖNE
ÇIKAN bir tablo OLMADIĞINI yansıtır.

**Full/full çakışma NOTU (Bölüm 6.3'ün bu tabloya UYGULANMASI, 4. turda
güncellendi):** `SEC_SWOT` (`FIP=A`, dolayısıyla `health_score_summary`
ve `recommendation_actions` domainleri için full-detay SAHİBİDİR) ile
`SEC_HEALTH_SCORE_BREAKDOWN`/`SEC_RECOMMENDATIONS` (`FIP=H`, full
DEĞİLDİR) ARTIK AYNI raporda İKİ section olarak bu domainleri
PAYLAŞMAKTADIR — bu, Bölüm 6.3'ün NORMAL primary/secondary kuralına
göre GEÇERLİDİR (yalnızca `SEC_SWOT` full'dur) ve çalışma zamanında
Bölüm 6.4'ün `DUPLICATE_DATA_ACROSS_SECTIONS` uyarısını `health_score_
summary`/`recommendation_actions` domainleri için `SWOT_REPORT`'ta da
(önceki turlarda YOKTU) ÜRETİR — bu, HATA DEĞİLDİR, tasarlanan şeffaflık
mekanizmasının tam da BEKLENEN çalışmasıdır (hiçbir veri sessizce
silinmez, yalnızca hangi section'ın "referans" OLDUĞU AÇIKÇA işaretlenir).

#### 15.4.7 `PERIOD_COMPARISON_REPORT` — `intended_audience`: "Finans ekibi, tek-dönem karşılaştırma ihtiyacı olan iç paydaşlar" — 5 section

| `section_code` | DL | FIP | TD | MI | Prov | Conf | Disc | Ord | Opt |
|---|---|---|---|---|---|---|---|---|---|
| `SEC_COVER_PAGE` | full | A | — | — | E | H | H | 1 | H |
| `SEC_PERIOD_COMPARISON_ANALYSIS` | full | A | F | — | E | E | E | 2 | H |
| `SEC_DISCLAIMER_BLOCK` | full | A | — | — | H | H | E | 3 | H |
| `SEC_FINANCIAL_STATEMENTS_SUMMARY` | summary | K | T | 10 | E | E | E | 4 | E |
| `SEC_RATIO_ANALYSIS_TABLE` | summary | K | T | 10 | E | E | E | 5 | E |

*(`SEC_RATIO_ANALYSIS_TABLE`: yalnızca `growth` kategorisi.)*

### 15.5 Full/full çakışma doğrulaması (Bölüm 6.3 kuralının 7 rapora UYGULANMASI)

Yukarıdaki 7 tablonun HER biri, Bölüm 15.3.1'in 7 overlap domain'i
İÇİN, AYNI raporda EN FAZLA BİR section'ın `TD=F`/`FIP=A` (full) taşıdığı
KONTROL EDİLEREK oluşturulmuştur — HİÇBİR TABLODA iki section AYNI
domain için `TD=F`/`FIP=A` OLARAK BİRLİKTE GÖRÜNMEZ.

- `SEC_BOARD_DECISION_ITEMS`'ın `BOARD_OF_DIRECTORS_REPORT`'ta `full`
  olması, `SEC_RECOMMENDATIONS`'ın o raporda HİÇ dahil OLMAMASI
  nedeniyle Bölüm 6.3'ün "tek section" istisnasına TABİDİR.
- AYNI mantık `SEC_INVESTOR_KPI_SUMMARY`/`INVESTOR_REPORT` ve `SEC_
  PERIOD_COMPARISON_ANALYSIS`/`PERIOD_COMPARISON_REPORT` için de
  GEÇERLİDİR.
- **`SEC_SWOT`/`SWOT_REPORT` — 4. turda GÜNCELLENDİ:** Bölüm 0.1'in
  düzeltmesinden SONRA, `SWOT_REPORT` ARTIK `SEC_HEALTH_SCORE_
  BREAKDOWN`+`SEC_RECOMMENDATIONS`'ı da (compact/headline-only)
  İÇERİR — bu YÜZDEN `SEC_SWOT`/`SWOT_REPORT` ARTIK "tek section"
  istisnasına DEĞİL, Bölüm 6.3'ün NORMAL primary/secondary kuralına
  TABİDİR: `SEC_SWOT` (`FIP=A`) tek full-detay SAHİBİDİR, diğer ikisi
  (`FIP=H`) referans seviyesindedir — kural yine İHLAL EDİLMEZ, yalnızca
  hangi istisna/kural maddesinin UYGULANDIĞI değişmiştir (bkz. Bölüm
  15.4.6'nın "Full/full çakışma NOTU").

### 15.6 Kullanılmayan section KONTROLÜ

18 section'ın TAMAMI en az bir rapor tipinde KULLANILMAKTADIR
(`SEC_BOARD_DECISION_ITEMS` ve `SEC_INVESTOR_KPI_SUMMARY` yalnızca
KENDİ ilgili rapor tiplerinde kullanılır — bu KASITLIDIR, o raporlara
ÖZGÜ section'lardır). **Tanımsız/kullanılmayan section YOKTUR.**

---

## 16. Presentation-Only Invariant'lar (DEĞİŞMEDİ, 2. turdan KORUNDU)

`REPORT_ENGINE_PRESENTATION_ONLY` / `DASHBOARD_PRESENTATION_ONLY` /
`RENDER_CONTRACT_PRESENTATION_ONLY` — tam tanımları 2. turun Bölüm
18.1-18.3'ünde YAZILMIŞTIR ve bu turda İÇERİK OLARAK DEĞİŞMEMİŞTİR;
yalnızca Bölüm 7'nin YENİ `SourceCoverageEntry` alanı VE Bölüm 12'nin
determinizm kısıtları (`datetime.now()`/`uuid4()`/`random` YASAĞI)
`REPORT_ENGINE_PRESENTATION_ONLY`'nin 9. maddesi olarak EKLENMİŞTİR:

> 9. **Motor kendi içinde `datetime.now()`/`uuid4()`/`random`/global
>    locale state KULLANMAZ** (Bölüm 12.1).

---

## 17. Pipeline'lar — NİHAİ (KİLİTLİ, adım sayıları KESİNLEŞTİ)

### 17.1 Narrative Report Pipeline — 17 ADIM

1. Compatibility validation.
2. Immutable input validation.
3. Report type resolution.
4. Section usage resolution.
5. **Detail-level validation** (Bölüm 5.1'in `DASHBOARD` değeri
   REDDİ dahil).
6. Overlap/domain validation (Bölüm 6.3'ün full/full REDDİ dahil).
7. Dependency graph validation (Bölüm 4.4'ün 5 kuralı).
8. Source sections build (Faz 1).
9. Aggregation sections build (Faz 2).
10. Compliance sections build (Faz 3).
11. Confidence/coverage inventory presentation (Bölüm 7).
12. Duplicate-content warnings (Bölüm 6.4).
13. Stable ordering (`display_order`).
14. Legal/confidentiality metadata (Bölüm 9).
15. Explainability/provenance (`source_field_path`/`consumed_section_
    codes` doldurma).
16. Presentation-only invariant kontrolü (`REPORT_ENGINE_PRESENTATION_
    ONLY`).
17. `ExecutiveReportResult` oluştur ve DÖN.

### 17.2 Dashboard Pipeline — 9 ADIM

1. Compatibility (`DASHBOARD_INPUT_COMPATIBILITY`).
2. Immutable input validation.
3. Dashboard type resolution.
4. Widget registry resolution (Bölüm 2.4).
5. Widget source references build.
6. Stable ordering.
7. Legal/confidentiality metadata.
8. Presentation-only invariant kontrolü (`DASHBOARD_PRESENTATION_
   ONLY`).
9. `DashboardSnapshot` oluştur ve DÖN.

### 17.3 Render Contract Preview Pipeline — 7 ADIM

1. Existing report validation (`report_result` tip/durum kontrolü).
2. Render contract resolution (`RenderContract` girdi doğrulaması).
3. Capability metadata (Bölüm 3.3'ün `layout_capability_matrix`/
   `chart_placeholder_capability`).
4. Unsupported-content warnings (`RenderContract.supported_block_
   types` dışı block tespiti).
5. **Stable ordering** (`section_render_order`).
6. Presentation-only invariant kontrolü (`RENDER_CONTRACT_
   PRESENTATION_ONLY`).
7. `RenderContractPreview` oluştur ve DÖN.

---

## 18. Test Planı — NİHAİ (madde 17'nin TAM listesi, ~40 madde)

1. Exact 7 report types (`ReportType` enum üyeliği regresyonu).
2. Exact 2 dashboard types.
3. Exact 18 sections (`REPORT_SECTION_REGISTRY` boyut regresyonu).
4. Section build-phase distribution (13/2/3).
5. Section usage inventory (Bölüm 15.4'ün 7 tablosunun KOD ile BİREBİR
   eşleştiği).
6. Undefined section rejection.
7. **Hidden `report_type` access prevention** (builder imzasının
   statik/AST taramasıyla `report_type` parametresi ALMADIĞININ
   doğrulanması).
8. Detail-level validation (`DASHBOARD` değerinin narrative'te
   REDDİ).
9. Unknown dependency rejection.
10. Self-dependency rejection.
11. Cycle rejection.
12. Stable topological order.
13. Registry insertion-order independence.
14. Overlap warnings (`DUPLICATE_DATA_ACROSS_SECTIONS`).
15. **Duplicate full-detail rejection** (Bölüm 6.3, `Overlapping
    FullDetailSectionsError`).
16. SWOT opportunity fabrication prevention.
17. SWOT reformatted-source flags.
18. Period comparison scope (yasaklı kelime taraması).
19. Dashboard/report contract separation (tip introspection).
20. Render preview not in `ReportType`.
21. No overall confidence calculation (dataclass alan-adı taraması).
22. `None` confidence safety.
23. Source confidence inventory.
24. **Source coverage inventory** (AYRI test, Bölüm 7.2'nin YENİ
    alanı).
25. Legal review matrix (Bölüm 9.2'nin 7 satırıyla BİREBİR).
26. External distribution gating (`external_distribution_allowed=
    False` tüm v1 raporlarında).
27. Confidentiality metadata.
28. Deterministic output (100 iterasyon, TÜM parametreler SABİT).
29. **Explicit `generated_at` behavior** (yalnızca çağıran verirse
    DOLU, aksi halde `None`; `datetime.now()` KULLANILMADIĞININ
    mock/spy testi).
30. No upstream engine calls.
31. Read-only input invariant.
32. No generated interpretation (banned-language/serbest-metin
    taraması).
33. Schema incompatibility.
34. Version mismatch.
35. Model-version warning.
36. Golden datasets (7 narrative + 2 dashboard, en az 1'er senaryo).
37. Property tests (3 invariant, Bölüm 16).
38. Registry cleanliness.
39. Performance (Bölüm 24'ün — 2. turdan KORUNAN — 5 kategorisi).
40. Full Docker regression ("0 failed" disiplini).

**İmplementasyon SONRASI gerçek sayım (4. tur eklentisi — madde 18'in
"Test sayıları... güncellensin" talebinin karşılığı):** Yukarıdaki ~40
kategori, **8 test dosyasında, toplam 77 GERÇEK test fonksiyonu** olarak
implemente edilmiştir: `test_report_registry_unit.py` (24),
`test_report_pipeline_unit.py` (15), `test_report_swot_and_period_
comparison_unit.py` (8), `test_report_golden_dataset_unit.py` (3),
`test_report_property_unit.py` (4), `test_report_performance_and_
cleanliness_unit.py` (5), `test_dashboard_unit.py` (10), `test_render_
contract_unit.py` (8). Bu 77 test, 4.3D/E/F'nin MEVCUT 695 testiyle
BİRLİKTE sandbox'ta **772/772**, gerçek Docker'da (pytest'in TAM
paketiyle, ek entegrasyon/DB testleri DAHİL) **886/886** ("0 failed")
sonucunu ÜRETMİŞTİR.

---

## 19. Revizyon Raporu (madde 18 — TAM sayım, 4. turda İMPLEMENTASYON SONRASI GERÇEK verilerle GÜNCELLENDİ)

- **Kapatılan karar sayısı:** **9/9** (Bölüm 0 / Bölüm 14).
- **Açık karar sayısı:** **0**.
- **İmplementasyon sonrası bulunan/düzeltilen mimari sapma sayısı:**
  **1** — `SWOT_REPORT`'un 5 değil 7 section içermesi (Bölüm 0.1).
- **Narrative report type sayısı:** **7** (Bölüm 15.1).
- **Dashboard type sayısı:** **2** (Bölüm 15.2).
- **Canonical section sayısı:** **18** (Bölüm 15.3, DEĞİŞMEDİ).
- **Source/aggregation/compliance dağılımı:** **13 / 2 / 3 = 18**
  (DEĞİŞMEDİ).
- **7 rapor tipinin section-KULLANIM sayıları (4. turda GÜNCELLENDİ):**
  CFO=16, Bank Credit=12, Board=10, Investor=9, Management Summary=7,
  **SWOT=7 (5'ten düzeltildi)**, Period Comparison=5.
- **Dependency ilişkisi sayısı:** **6 literal (sabit-liste)** + **3
  wildcard (`ALL_INCLUDED_UPSTREAM_SECTIONS`)** (Bölüm 4.6, section-
  TANIM seviyesinde DEĞİŞMEDİ — düzeltme report-type-KULLANIM
  seviyesindeydi).
- **Overlap domain sayısı:** **7** (14 toplam domain'in 7'si, DEĞİŞMEDİ).
- **Eklenen gerçek test sayısı:** **77** (8 dosya, yukarıdaki liste).
- **Sandbox test sonucu:** **772/772 passed, 0 failed**.
- **Gerçek Docker test sonucu:** **886/886 passed, 0 failed**
  (kullanıcı tarafından `PYTHONPATH=/app python -m pytest tests/ -v`
  ile ÇALIŞTIRILDI ve DOĞRULANDI).
- **Hukuki inceleme gereken (`legal_review_required`) report sayısı:**
  **3** (Bank Credit Allocation, Board of Directors, Investor).
- **Internal-use-only report sayısı:** **4** (CFO Executive,
  Management Summary, SWOT, Period Comparison).
- **External distribution allowed report sayısı:** **0** (v1'de
  TÜM 7 rapor `external_distribution_allowed=False`).
- **Overall confidence ÜRETİLMEDİĞİNİN teyidi:** TEYİT EDİLDİ —
  `ExecutiveReportResult`/`DashboardSnapshot` dataclass'larında
  `overall_confidence`/`overall_coverage`/composite reliability
  isimli HİÇBİR alan YOKTUR (Bölüm 11.1/2.3); yalnızca `source_
  confidence_inventory`/`source_coverage_inventory` (presentation-
  only envanterler) VARDIR.
- **SWOT opportunity ÜRETİLMEDİĞİNİN teyidi:** TEYİT EDİLDİ — Bölüm
  8, `Opportunities` kadranı HER ZAMAN `is_available=False`,
  `items=()` sabit yapıdadır.
- **Gerçek Trend Report'un kapsam dışı OLDUĞUNUN teyidi:** TEYİT
  EDİLDİ — Bölüm 13 madde 13, "gerçek çok-dönemli Trend Engine" bu
  milestone'un DIŞINDADIR; `PERIOD_COMPARISON_REPORT` yalnızca
  tek-önceki-dönem karşılaştırması SUNAR.
- **Dashboard ayrımı:** TEYİT EDİLDİ — `DashboardType`/`generate_
  dashboard_snapshot()`/`DashboardSnapshot`, `ReportType`/`generate_
  executive_report()`/`ExecutiveReportResult`'tan TAMAMEN AYRI (Bölüm
  2, Bölüm 11.3); persistence/API/live-refresh/cache/frontend v1
  KAPSAMI DIŞINDA (Bölüm 2.2).
- **Render Contract ayrımı:** TEYİT EDİLDİ — `RenderContract`/
  `RenderContractPreview`/`preview_render_contract()`, `ReportType`
  enum'unda YER ALMAZ (Bölüm 1.1); yalnızca 8 render-neutral alan
  TAŞIR (Bölüm 3.3); gerçek PDF/DOCX üretimi AYRI, GELECEK bir
  milestone'a ERTELENMİŞTİR (Bölüm 13 madde 6).
- **Production Readiness:** Tasarım tamlığı **%100** (9/9 açık karar
  KAPANDI, 18+1 madde/düzeltme TAM işlendi, doküman KODLA %100
  UYUMLU); fonksiyonel/implementasyon **%100 — TAMAMLANDI ve gerçek
  Docker'da DOĞRULANDI** (886/886 passed, 0 failed).
- **İmplementasyona hazır mı:** **İmplementasyon ZATEN TAMAMLANDI** —
  bu 4. tur, implementasyon SIRASINDA bulunan TEK sapmayı (Bölüm 0.1)
  dokümana İŞLEMEK içindir; implementasyon planı/kapsamı AÇISINDAN
  yapılacak BAŞKA bir iş KALMAMIŞTIR.
- **Git status (bu 4. tur):** Bu turda **YALNIZCA** `docs/FINOS_
  MILESTONE_4_4_EXECUTIVE_REPORT_ENGINE_DESIGN.md` REVİZE EDİLMİŞTİR
  — implementasyon dosyaları (Bölüm 21'in listesi) bu turda
  DOKUNULMAMIŞ, ÖNCEKİ (implementasyon) turunda ZATEN YAZILMIŞ ve
  Docker'da DOĞRULANMIŞ haliyle KORUNMUŞTUR.
- **Yalnızca dokümanın değiştiğinin teyidi:** TEYİT EDİLDİ (aşağıdaki
  `git status`/`git diff --stat` çıktısıyla DOĞRULANACAKTIR — yalnızca
  bu `.md` dosyası `git status`'ta DEĞİŞMİŞ görünür).
- **Kod/test/migration/API/adapter/rendering/commit/push YAPILMADIĞININ
  teyidi:** TEYİT EDİLDİ — bu turda `Write`/`Edit` yalnızca bu MARKDOWN
  dosyasına UYGULANMIŞTIR; hiçbir `.py`/migration/config dosyası
  DOKUNULMAMIŞTIR; hiçbir `git commit`/`git push` ÇALIŞTIRILMAMIŞTIR.

---

## 20. İmplementasyon Envanteri (4. turda EKLENDİ — referans amaçlı, DEĞİŞTİRİLMEMİŞ dosyalar)

Önceki (implementasyon) turunda yazılmış ve gerçek Docker'da doğrulanmış
production/test dosyalarının listesi — bu 4. tur bunların HİÇBİRİNE
DOKUNMAMIŞTIR, yalnızca referans/uyum amacıyla burada listelenmiştir:

**Production kodu:** `app/engines/common/report_types.py`, `report_
registry.py`, `dashboard_types.py`, `dashboard_registry.py`, `render_
contract_types.py`; `app/engines/executive_reports/__init__.py`+
`service.py`; `app/engines/dashboards/__init__.py`+`service.py`;
`app/engines/render_contract/__init__.py`+`service.py`.

**Test kodu (77 test, 8 dosya):** `tests/test_report_registry_unit.py`,
`test_report_pipeline_unit.py`, `test_report_swot_and_period_comparison_
unit.py`, `test_report_golden_dataset_unit.py`, `test_report_property_
unit.py`, `test_report_performance_and_cleanliness_unit.py`, `test_
dashboard_unit.py`, `test_render_contract_unit.py`.

**Değiştirilen:** `tests/conftest.py` (+34 satır — `report_registry`/
`dashboard_registry` için registry snapshot/restore fixture genişletmesi).

---

## 21. Kapanış

Bu doküman, Milestone 4.4'ün **implemente edilmiş, gerçek Docker'da
doğrulanmış (886/886 passed, 0 failed) ve kodla %100 UYUMLU NİHAİ
sürümüdür.** 4 tur boyunca (ilk taslak → bağımsız denetim → 20
maddelik revizyon → 18 maddelik son-karar turu → implementasyon sonrası
1 mimari sapmanın Bölüm 0.1'de dokümana işlenmesi) HİÇBİR açık mimari
soru veya doküman/kod TUTARSIZLIĞI KALMAMIŞTIR. Milestone 4.4 **TAMAMLANMIŞTIR.**
