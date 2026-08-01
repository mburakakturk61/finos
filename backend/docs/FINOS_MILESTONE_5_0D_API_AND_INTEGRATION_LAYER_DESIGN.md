# Milestone 5.0D — API and Integration Layer Design

**Doküman türü:** Tasarım — production implementasyonu değildir
**Durum:** MİMARİ İNCELEMEYE HAZIR; blocking açık karar yoktur
**Design Readiness:** %100
**Runtime Readiness:** %0 — bu milestone için henüz kod/test yoktur
**Bağlayıcı ana referans:** `docs/FINOS_ARCHITECTURE_BOOK.md` v1.3.0
**Değişmeden kullanılacak sözleşmeler:** Milestone 5.0A, 5.0B ve 5.0C public contract'ları
**Son doğrulanmış sistem tabanı:** 1042 passed, 0 failed, 0 skipped; PostgreSQL integration/concurrency dahil; Alembic head `5c1a7e9d3b20`

> Bu dokümandaki **FINOS** ifadesi yalnız dahili geliştirme kod adıdır. Yeni runtime sembolleri, endpoint'ler, schema adları, OpenAPI metadata'sı, hata metinleri ve kullanıcıya görünen içerik brand-independent olacaktır.

---

## 1. Amaç

Milestone 5.0D'nin amacı, Milestone 5.0C Analysis Application Layer'ın senkron command/query use-case'lerini HTTP üzerinden erişilebilir kılan, FastAPI'ye özgü ayrıntıları application core'un dışında tutan production-grade bir **API ve integration adapter sınırı** tasarlamaktır.

Bu katman:

- HTTP request'i doğrulanmış 5.0C command/query nesnesine dönüştürür;
- authenticated caller context'ini tenant-aware application scope ve audit context'e map eder;
- 5.0C `ApplicationOutcome[T]` sonucunu versioned HTTP response'a dönüştürür;
- idempotency, correlation, hata gizleme, pagination, OpenAPI ve dependency injection politikalarını uygular;
- finansal hesaplama, persistence assembly, owner/lineage kararı veya reuse kararı üretmez.

5.0D, yeni bir domain/application davranışı değildir. Mevcut Production Ready 5.0A–5.0C davranışını HTTP boundary üzerinden kayıpsız ve fail-closed biçimde açan anti-corruption adapter'ıdır.

---

## 2. Kapsam

5.0D implementasyon kapsamı, ayrıca kullanıcı onayı verilirse, yalnız şunlardan oluşacaktır:

1. `/api/v1/analysis-runs` altında yeni, brand-independent FastAPI router'ı.
2. Versioned Pydantic HTTP request/response şemaları.
3. HTTP JSON ↔ 5.0C typed DTO codec/mapping katmanı.
4. Authentication principal'ı ve request metadata'sını 5.0C scope/audit context'e map eden integration boundary.
5. Mevcut 5.0C application/query service'lerinin dependency injection composition'ı.
6. Start, Resume, Retry, Cancel ve dört query endpoint'i.
7. Kapalı HTTP hata eşlemesi, güvenli response envelope ve response headers.
8. Scope-qualified, HMAC-authenticated cursor wrapper'ı.
9. Unit, router contract, OpenAPI, security ve gerçek PostgreSQL integration testleri.
10. Mevcut FastAPI uygulamasına yalnız router registration seviyesinde additive bağlantı.
11. Persisted document/result girdilerini cryptographic integrity ile materialize eden trusted input resolver adapter'ları.
12. Production authorization, required security-audit, observability, clock ve authentication-context provider composition'ı.
13. Process-local bounded analysis admission control.
14. Infrastructure error kategorisini koruyan `ApiAnalysisReadFacade` integration adapter'ı.
15. `analysis_run_scope_claims.initiating_subject_id` için 5.0D-owned additive migration/model/repository wiring'i; 5.0C public port imzaları değişmez.

Bu milestone yeni payload tablosu veya duplicate source of truth oluşturmaz. Subject ownership, yeni bir tablo yerine mevcut durable run ownership reservation'a tek additive alan olarak bağlanır. Bu alan workflow/job state değildir.

---

## 3. Kapsam Dışı

Aşağıdakiler 5.0D kapsamında değildir:

- 5.0A Orchestrator public contract veya davranış değişikliği;
- 5.0B persistence **public contract** değişikliği; 5.0D'nin aşağıda kilitlenen iki additive integrity/ownership alanı dışında persistence refactor'ı;
- 5.0C application public contract veya use-case davranış değişikliği;
- engine hesaplama, registry, dispatch, fingerprint veya determinism değişikliği;
- queue, background worker, scheduler, batch runner veya durable job registry;
- async/background analysis yürütme, polling job state'i veya websocket/SSE;
- distributed lock, exactly-once execution, automatic retry veya backoff;
- event sourcing, event replay veya CQRS read model;
- yeni blob/object storage veya document-content persistence;
- ad-hoc/unpersisted raw upload ile analysis çalıştırma;
- UI/frontend;
- mevcut bulk-upload/trial-balance endpoint'lerinin davranışını değiştirme;
- mevcut `/api/v1/analyses/{analysis_id}` financial owner endpoint'ini kaldırma veya yeniden adlandırma;
- identity provider'ın kullanıcı/rol yönetimi, token issuance veya tenant provisioning'i;
- rate-limit altyapısı ve API gateway kurulumu;
- mevcut legacy runtime brand string'lerinin kapsam-genişleten toplu refactor'ı.

5.0D yalnız senkron request/response integration katmanıdır. HTTP bağlantısının kopması durable cancellation garantisi değildir.

5.0D implementasyonunda izin verilen persistence değişikliği yalnız şunlardır: mevcut `analysis_run_scope_claims` reservation'ına `initiating_subject_id`, authoritative local financial owner'a `canonical_result_digest`. İkisi additive migration'dır; payload kopyalamaz, 5.0B public port/repository sözleşmesini değiştirmez ve başka model/repository genişlemesine yetki vermez.

---

## 4. Mevcut Mimari Analizi

### 4.1 Milestone 5.0A — Analysis Orchestrator

`app/engines/analysis_orchestrator/` dokuz engine'i deterministic dependency graph ile koordine eder. Public giriş `OrchestrationRunRequest`, public terminal çıkış `OrchestrationRunResult` ve resume girdisi `PreviousExecutionSnapshot` değişmeyecektir. Gerçek engine çıktısı `EngineResultEnvelope.result` alanındadır. HTTP katmanı bu dataclass'ları serialize etmez veya doğrudan dışarı açmaz.

### 4.2 Milestone 5.0B — Persistence & Recovery

`app/orchestration_persistence/` terminal run, execution, error, financial owner/artifact reference ve resume snapshot bütünlüğünün authoritative sahibidir. `run_id + request_fingerprint`, canonical digest, immutable history, payload ownership, SAVEPOINT loser-discard ve resume binding kuralları değişmeyecektir. Router repository çağırmayacak; yalnız 5.0C use-case'ini çağıracaktır.

### 4.3 Milestone 5.0C — Analysis Application Layer

`app/analysis_application/` exact command/query/DTO/enum ve `ApplicationOutcome[T]` sözleşmelerini sağlar. Start/Resume/Retry/Cancel senkron use-case'leri; scope claim, authorization, audit, Orchestrator ve persistence koordinasyonunu zaten sahiplenir. Read use-case'leri scope-qualified'dır. FastAPI/Pydantic/SQLAlchemy application core'a sızmaz.

5.0D'nin kullanacağı public yüzey:

- `AnalysisApplicationService.start/resume/retry/cancel`;
- `AnalysisQueryService.get_status/get_result/get_execution_detail/list_history`;
- 5.0C command/query DTO'ları ve kapalı enum'lar;
- `ApplicationOutcome[T]`;
- mevcut 5.0C port implementasyonları ve composition dependencies.

### 4.4 Mevcut API ve bulk-upload akışları

Mevcut API `/api/v1` altında company, period, document, financial analysis result, trial-balance upload ve bulk-upload akışlarını taşır. Liste endpoint'lerinin bir bölümü offset pagination kullanır. Yeni analysis-run history endpoint'i mevcut 5.0C stable keyset cursor sözleşmesini kullanacak; legacy offset endpoint'leri bu milestone'da değiştirilmeyecektir.

`POST /api/v1/periods/{period_id}/trial-balances` source document metadata'sı ile `FinancialAnalysisResult` üretir; mevcut repository tek başına document byte storage sağlamaz. Bu nedenle production 5.0D composition'ı authoritative document-content sistemine bağlanan `DocumentInputResolverPort` olmadan ready olamaz. 5.0D:

- var olmayan bir content store varsaymayacak;
- caller'dan document-backed BS/IS byte'ı kabul etmeyecek;
- caller'ın verdiği trusted `FinancialDocument` ID'sini resolver üzerinden scope/checksum/content ile birlikte materialize edecek;
- trial-balance payload'ını caller JSON'undan kabul etmeyecek; trusted `FinancialAnalysisResult` ID'sinden resolver ile yükleyecek;
- hesaplama girdisi ile provenance ID'sini aynı resolved immutable nesneden üretecek;
- resolver binding'i olmayan deployment'ı readiness=false sayacak.

**Input provenance invariant:**

```text
PERSISTED_SOURCE_ID_PRESENT
    -> computation input MUST be materialized from, and cryptographically
       verified against, that exact persisted source.
```

Caller-supplied source ID ile farklı byte/payload birleşimi hiçbir fallback yolunda kabul edilmez. Ad-hoc/unpersisted upload ve `UNPERSISTED_UPLOAD`/`AD_HOC_INPUT` source mode'u 5.0D v1'de **desteklenmez**.

### 4.5 Mevcut transaction sınırları

HTTP router transaction sahibi değildir. Session lifecycle FastAPI dependency tarafından sağlanır; claim/persistence/read adapter'larının mevcut transaction kuralları korunur. Terminal run + execution + owner/lineage + artifact atomikliği 5.0B/5.0C adapter'larında kalır. HTTP response serialization hiçbir DB commit'i geri alamaz.

---

## 5. API Katmanının Sistemdeki Yeri

```text
HTTP client
   │
   ▼
FastAPI router + Pydantic HTTP schemas                [5.0D]
   │  authenticate / validate / map / serialize
   ▼
AnalysisApplicationService / AnalysisQueryService    [5.0C, değişmez]
   ├────────► Analysis Orchestrator                   [5.0A, saf/değişmez]
   └────────► Persistence & Recovery                  [5.0B, değişmez]
                    │
                    ▼
                PostgreSQL
```

Bağımlılık yalnız dıştan içe akar. `app/analysis_application/**` hiçbir `app/api`, FastAPI veya Pydantic importu alamaz. Router engine, ORM model veya repository import edemez. SQLAlchemy yalnız mevcut adapter/composition sınırında bulunabilir.

Önerilen dosya sınırı:

```text
app/
├── api/v1/analysis_runs.py                 # yalnız route declarations
├── schemas/analysis_runs_v1.py             # Pydantic wire contracts
└── integrations/analysis_http/
    ├── codec.py                            # tagged JSON/Decimal/date-time codec
    ├── mapping.py                          # HTTP ↔ 5.0C DTO mapping
    ├── errors.py                           # exhaustive HTTP mapping
    ├── identity.py                         # authentication boundary protocol/adapter
    ├── cursor.py                           # HMAC cursor envelope
    └── dependencies.py                     # FastAPI composition root
```

Bu isimler brand-independent'dır. `app/main.py` yalnız router registration için değişebilir; mevcut endpoint davranışları değiştirilmez.

---

## 6. HTTP Boundary

### 6.1 Temel kararlar

- API prefix: `/api/v1/analysis-runs`.
- Wire schema version: `ANALYSIS_HTTP_SCHEMA_VERSION = "1.0.0"`.
- Application schema version: değişmeden `APPLICATION_DTO_SCHEMA_VERSION = "1.0.0"`.
- Storage serializer version wire contract değildir.
- Start/Resume/Retry senkrondur; response terminal outcome oluşana kadar açık kalır.
- Background kabul (`202 Accepted`) kullanılmaz.
- Write endpoint'leri `application/json`, read/cancel endpoint'leri standart headers/query parametreleri kullanır.
- Write JSON yalnız trusted persisted source ID'leri taşır; raw BS/IS byte veya trial-balance result payload taşımaz.
- Router doğrudan bytes/JSON'u loglamaz.

### 6.2 Header sözleşmesi

| Header | Write | Read/Cancel | Kural |
|---|---:|---:|---|
| `Idempotency-Key` | zorunlu | yasak | 5.0C `run_id`; 1–128 ASCII, `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$` |
| `X-Correlation-ID` | zorunlu | zorunlu | 1–128 aynı karakter kümesi; write retry'da birebir aynı olmalı |
| `X-API-Contract-Version` | zorunlu | zorunlu | yalnız `1.0.0`; farklı değer `API_CONTRACT_VERSION_UNSUPPORTED` |
| Provider-specific credential | trusted adapter'a bağlı | trusted adapter'a bağlı | 5.0D router parse etmez; raw değer log/audit/error'a girmez |
| `Content-Type` | `application/json` | yok/standart | yanlış media type `415` |

Her HTTP attempt için adapter-internal ayrı bir request ID üretilebilir ve `X-Request-ID` response header'ında dönebilir. Bu ID 5.0C command digest'ine girmez. `X-Correlation-ID` ise application contract alanıdır ve aynı idempotent retry boyunca stabil kalır.

`X-User-Id`, `X-Tenant-Id`, `X-Subject-Id` veya benzeri caller-supplied raw identity header'ları hiçbir ortamda trusted identity kaynağı değildir. Production'da bu header'ların varlığı authentication sağlamaz; trusted context yoksa request fail-closed reddedilir.

### 6.3 Wire serialization

HTTP JSON boundary, application DTO ve 5.0B storage codec'inden ayrıdır:

- UUID: canonical küçük harfli hyphenated string.
- timezone-aware datetime: RFC 3339, offset zorunlu; normalize edilen `Z`/`+00:00` tek canonical application datetime'a map edilir.
- date: ISO `YYYY-MM-DD`.
- Enum: yalnız `.value`.
- Decimal: explicit typed alanlarda JSON string; exponent yasak, canonical regex `^-?(0|[1-9][0-9]*)(\.[0-9]+)?$`.
- Generic `ApplicationJsonValue` Decimal/date/datetime değerleri sırasıyla `{"$application_type":"decimal|date|datetime","value":"..."}` tag'iyle taşınır.
- Generic tuple JSON array olarak taşınır ve adapter tarafından tuple'a dönüştürülür; application core'a list girmez.
- Map key yalnız string; `$application_type` içeren map exact tagged-field setine uymalıdır.
- NaN, positive/negative infinity ve non-finite Decimal reddedilir.
- Unknown field tüm request modellerinde reddedilir (`extra="forbid"`).
- Response serializer unknown application type gördüğünde `RESPONSE_SERIALIZATION_FAILED`; raw value dönülmez.

### 6.4 Boyut sınırları

- JSON request body: en çok 2 MiB.
- Authoritative resolver'ın döndürdüğü her document content: en çok 10 MiB.
- Body limiti route handler tam body materialize etmeden; resolved content limiti engine çağrısından önce uygulanır.
- Bu limitler 5.0B'nin 256 KiB inline/1 MiB run persistence bütçesiyle karıştırılmaz; biri HTTP input, diğeri canonical persisted output politikasıdır.

---

## 7. Router Mimarisi

`analysis_runs.py` ince adapter olacaktır. Her route yalnız şu sırayı uygular:

1. Header/path/query extraction.
2. Authentication dependency.
3. Media type/body-size validation.
4. Pydantic wire-model validation.
5. HTTP-to-application mapping.
6. 5.0C service çağrısı.
7. Exhaustive outcome-to-HTTP mapping.
8. Response serialization ve güvenli headers.

Router içinde ORM query, commit/rollback, owner binding, snapshot, fingerprint, digest, engine dispatch veya error-string improvisation yasaktır.

Route'lar sync `def` olarak çalıştırılır veya FastAPI'nin threadpool sınırı açıkça kullanılır; CPU-bound Orchestrator event loop üzerinde çalıştırılmaz. Bu bir background job değildir: threadpool task tamamlanmadan HTTP terminal response üretilmez.

Mevcut `app/api/v1/analyses.py` financial result owner endpoint'idir ve korunur. Yeni route collection adı `analysis-runs` olduğu için semantik/path çakışması yoktur.

---

## 8. Endpoint Envanteri

| Method | Path | Use-case | Success | Body/Query |
|---|---|---|---|---|
| `POST` | `/api/v1/analysis-runs` | Start | yeni: `201`; replay: `200` | JSON `StartAnalysisRequestV1` |
| `POST` | `/api/v1/analysis-runs/{previous_run_id}/resume` | Resume, new run | yeni: `201`; replay: `200` | JSON `ResumeAnalysisRequestV1` |
| `POST` | `/api/v1/analysis-runs/{previous_run_id}/retry` | Retry, new run | yeni: `201`; replay: `200` | JSON `RetryAnalysisRequestV1` |
| `POST` | `/api/v1/analysis-runs/{run_id}/cancel` | cooperative local cancel | `200` | `company_id`, `financial_period_id` query |
| `GET` | `/api/v1/analysis-runs/{run_id}/status` | status | `200` | required company/period query |
| `GET` | `/api/v1/analysis-runs/{run_id}/result` | result | `200` | company/period, `include_payloads=false` |
| `GET` | `/api/v1/analysis-runs/{run_id}/executions/{engine_code}` | execution detail | `200` | company/period, `include_payload=false` |
| `GET` | `/api/v1/analysis-runs` | history | `200` | company/period, cursor, limit |

Start/Resume/Retry'nin `201` ve `200` ayrımı yalnız `AnalysisCommandResultDTO.idempotent_replay` alanından yapılır. Cancel hiçbir zaman `202` dönmez; `CancellationStatus` normal business result'tır.

---

## 9. Request DTO Sözleşmeleri

Tüm modeller frozen/strict Pydantic v2 modelidir; `extra="forbid"`. HTTP DTO'ları 5.0C dataclass'ları değildir.

### 9.1 Ortak nested DTO'lar

```text
AnalysisInputsRequestV1
  balance_sheet_document_id: UUID | null
  income_statement_document_id: UUID | null
  trial_balance_analysis_result_id: UUID | null
  period_start_date: date | null
  period_end_date: date | null
  period_months_covered: int | null

AnalysisRunOptionsRequestV1
  industry_code: str | null
  company_size_bucket: str | null
  engine_segmentation_tenant_id: str | null
  reporting_period_label_tr: str | null
  optional_report_sections: tuple[str, ...] | null
  currency_display_policy: str | null
  locale: str = "tr-TR"

FinancialSourceReferenceRequestV1
  role: FinancialSourceRole
  source_document_id: UUID | null
  source_analysis_result_id: UUID | null
  source_engine_code: ApplicationEngineCode | null

FinancialSourceIntentRequestV1
  engine_code: ApplicationEngineCode
  company_id: UUID
  financial_period_id: UUID
  primary_document_id: UUID | null
  source_bindings: tuple[FinancialSourceReferenceRequestV1, ...]
  requested_source_mode: FinancialSourceMode
  allow_existing_canonical_owner: bool
  expected_existing_owner_id: UUID | null
  provenance_metadata: dict[str, ApplicationWireValue]
  caller_supplied_business_timestamp: aware datetime | null

PriorPeriodFactsRequestV1
  statement_kind: FinancialStatementKind
  values: exact closed map[str, Decimal-string | null]
  schema_version: "1.0.0"

PriorPeriodProjectionRequestV1
  balance_sheet_facts: PriorPeriodFactsRequestV1 | null
  income_statement_facts: PriorPeriodFactsRequestV1 | null
  balance_sheet_result: ApplicationWireMap | null
  income_statement_result: ApplicationWireMap | null

CompanyMetadataRequestV1
  company_name: str
  industry_label_tr: str | null
  company_size_label_tr: str | null
  fiscal_year_label_tr: str | null
  tax_id_masked: str | null
  schema_version: "1.0.0"

ReportRequestV1
  report_type: ApplicationReportType
  optional_section_codes: tuple[ApplicationReportSectionCode, ...] | null
  reporting_period_label_tr: str | null
  schema_version: "1.0.0"

DashboardRequestV1
  dashboard_type: ApplicationDashboardType
  schema_version: "1.0.0"

RenderContractRequestV1
  render_medium: ApplicationRenderMedium
  supported_block_types: tuple[ApplicationReportBlockType, ...]
  supports_landscape: bool
  supports_page_break_hints: bool
  supports_chart_placeholders: bool
  max_table_columns_before_overflow_risk: int | null
  schema_version: "1.0.0"
```

BS/IS raw bytes ve trial-balance payload HTTP DTO alanı değildir. Resolver sonuçları `AnalysisInputsDTO.balance_sheet_content/balance_sheet_filename`, `income_statement_content/income_statement_filename` ve `trial_balance_result` alanlarına map edilir. Filename authoritative metadata'dan gelir fakat güvenlik kararı değildir; extension, MIME ve magic-byte birlikte doğrulanır.

### 9.2 StartAnalysisRequestV1 — tam alan listesi

```text
generated_at: aware datetime                         # zorunlu, retry'da stabil
company_id: UUID                                    # zorunlu
financial_period_id: UUID                           # zorunlu
purpose: str                                        # zorunlu, 1..128
requested_outputs: tuple[ApplicationEngineCode, ...]# zorunlu, unique/non-empty
inputs: AnalysisInputsRequestV1                     # zorunlu
run_options: AnalysisRunOptionsRequestV1            # zorunlu
source_intents: tuple[FinancialSourceIntentRequestV1, ...] # zorunlu exact closure
prior_period_projection: PriorPeriodProjectionRequestV1 | null
company_metadata: CompanyMetadataRequestV1 | null
report_request: ReportRequestV1 | null
dashboard_request: DashboardRequestV1 | null
render_contract_request: RenderContractRequestV1 | null
api_contract_version: "1.0.0"
application_contract_version: "1.0.0"
```

Mapping sabitleri:

- `run_id = Idempotency-Key`;
- `correlation_id = X-Correlation-ID`;
- scope operation/original: `START/START`, previous `None`;
- tenant, actor, caller type, request source ve authorization reference authenticated principal'dan;
- audit `purpose` request'ten, `client_request_id = Idempotency-Key`;
- IP/user-agent raw tutulmaz; keyed hash yalnız ayrı security-audit event metadata'sına gider, application command/digest/fingerprint alanına girmez.

### 9.3 ResumeAnalysisRequestV1 — tam alan listesi

Resume request, Start ile “aynı” diye tanımlanmaz; alanları açıkça şunlardır:

```text
generated_at: aware datetime
company_id: UUID
financial_period_id: UUID
purpose: str
requested_outputs: tuple[ApplicationEngineCode, ...]
inputs: AnalysisInputsRequestV1
run_options: AnalysisRunOptionsRequestV1
source_intents: tuple[FinancialSourceIntentRequestV1, ...]
prior_period_projection: PriorPeriodProjectionRequestV1 | null
company_metadata: CompanyMetadataRequestV1 | null
report_request: ReportRequestV1 | null
dashboard_request: DashboardRequestV1 | null
render_contract_request: RenderContractRequestV1 | null
api_contract_version: "1.0.0"
application_contract_version: "1.0.0"
```

Yeni target `run_id = Idempotency-Key`; source `previous_run_id` path'ten gelir. İkisi farklı olmak zorundadır. Scope `operation_kind=RESUME`, `original_operation=RESUME` olarak adapter tarafından sabitlenir. Clean-start fallback yoktur.

### 9.4 RetryAnalysisRequestV1 — tam alan listesi

```text
generated_at: aware datetime
company_id: UUID
financial_period_id: UUID
purpose: str
original_operation: ApplicationOriginalOperation    # START veya RESUME, zorunlu
requested_outputs: tuple[ApplicationEngineCode, ...]
inputs: AnalysisInputsRequestV1
run_options: AnalysisRunOptionsRequestV1
source_intents: tuple[FinancialSourceIntentRequestV1, ...]
prior_period_projection: PriorPeriodProjectionRequestV1 | null
company_metadata: CompanyMetadataRequestV1 | null
report_request: ReportRequestV1 | null
dashboard_request: DashboardRequestV1 | null
render_contract_request: RenderContractRequestV1 | null
api_contract_version: "1.0.0"
application_contract_version: "1.0.0"
```

Target `run_id = Idempotency-Key`, source ID path'ten gelir; eşitlik yasaktır. Scope `operation_kind=RETRY` ve body'deki `original_operation` ile kurulur. `original_operation=RESUME` ise 5.0C resume source authorization/integrity kurallarının tamamı uygulanır. API automatic retry/backoff yapmaz.

### 9.5 Cancel ve query girdileri

Cancel body taşımaz. `run_id` path'ten, `company_id` ve `financial_period_id` query'den, tenant ve audit identity principal'dan gelir. Known claim için exact persisted scope metadata-only çözülür; caller company/period/tenant ile uyuşmazsa payload materialize edilmeden fail-closed cevap verilir. Unknown claim için structural `START/START/None` scope kurulup 5.0C normal `NOT_FOUND` cancellation result'ı alınabilir.

Run-specific read query'leri:

```text
company_id: UUID                    # zorunlu
financial_period_id: UUID           # zorunlu
include_payloads/include_payload: bool = false
```

History query:

```text
company_id: UUID                    # zorunlu
financial_period_id: UUID           # zorunlu
cursor: str | null
limit: int = 50                     # 1..200
```

History için 5.0C `ApplicationScopeDTO` structural read carrier'ı `START/START/None` ile kurulur; bu bir `RunScopeClaim`, operation filter veya new-run intent değildir. Authorization adapter history action'ını route/use-case bağlamından ayırır.

---

## 10. Response DTO Sözleşmeleri

### 10.1 Ortak envelope

```text
ApiOutcomeResponseV1[T]
  success: bool
  data: T | null
  error: ApiErrorV1 | null
  warnings: tuple[ApiWarningV1, ...]
  correlation_id: str
  api_schema_version: "1.0.0"
  application_schema_version: "1.0.0"
```

Invariant:

- `success=true` → `data` zorunlu, `error=null`;
- `success=false` → `data=null`, `error` zorunlu;
- warnings iki durumda da taşınabilir;
- raw `ApplicationOutcome` veya dataclass repr'i response yapılmaz.

### 10.2 Error/warning

```text
ApiErrorV1
  code: ApiErrorCodeV1
  category: str
  message: str
  retryable: bool
  correlation_id: str
  safe_metadata: dict[str, ApplicationWireValue]

ApiWarningV1
  code: str
  message: str
  retryable: bool
```

### 10.3 Command/cancellation response

```text
AnalysisCommandResponseV1
  run_id: str
  status: ApplicationStatus
  request_fingerprint: str
  terminal_content_digest: str
  scope: ApplicationScopeResponseV1
  executions: tuple[AnalysisExecutionResponseV1, ...]
  persisted_at: aware datetime
  idempotent_replay: bool
  recovery_query_run_id: str
  application_schema_version: str

CancellationResponseV1
  run_id: str
  status: CancellationStatus
  scope: ApplicationScopeResponseV1
  requested_at: aware datetime
  application_schema_version: str
```

CancellationStatus `ACCEPTED`, `ALREADY_REQUESTED`, `NOT_ACTIVE`, `ALREADY_TERMINAL`, `NOT_FOUND` değerlerinin tamamı normal `success=true`, HTTP 200 business sonuçlarıdır.

### 10.4 Query response'ları

`AnalysisRunStatusResponseV1`, `AnalysisResultResponseV1`, `AnalysisExecutionResponseV1`, `AnalysisHistoryPageResponseV1` alanları 5.0C DTO'larını kayıpsız taşır:

```text
AnalysisRunStatusResponseV1
  run_id, status, scope, finalized_at,
  engine_statuses: tuple[{engine_code, status}, ...],
  terminal, application_schema_version

AnalysisResultResponseV1
  run_id, status, scope, request_fingerprint,
  executions, warnings, structured_errors,
  execution_plan_version, orchestration_schema_version,
  orchestration_model_version, finalized_at, application_schema_version

AnalysisExecutionResponseV1
  engine_code, status, inner_status,
  engine_schema_version, engine_model_version,
  input_fingerprint, fingerprint_schema_version,
  error, dependency_engine_codes, payload,
  reused_from_run_id, application_schema_version

AnalysisHistoryPageResponseV1
  items: tuple[AnalysisRunSummaryResponseV1, ...]
  next_cursor: str | null
  application_schema_version
```

`ApplicationPayloadReferenceDTO` ayrımı korunur:

- financial owner: `owner_type=FINANCIAL_ANALYSIS_RESULT`, `financial_analysis_result_id`, canonical digest; `artifact_id=null`, `artifact_serializer_schema_version=null`;
- artifact owner: `owner_type=ORCHESTRATION_ARTIFACT`, `artifact_id`, result kind, canonical digest ve artifact serializer schema version; financial ID null.

Payload envelope; computation status, source mode, result payload, structured error/message, inner status, trial-balance usage, provenance references ve engine schema/model version alanlarının tamamını taşır. Engine dataclass'ı açılmaz.

### 10.5 Response headers

- `X-Correlation-ID`: outcome correlation ID.
- `X-Request-ID`: HTTP attempt ID.
- `X-API-Contract-Version: 1.0.0`.
- `Cache-Control: no-store` tüm analysis-run response'larında.
- `X-Content-Type-Options: nosniff` deployment middleware veya app seviyesinde.
- Financial payload/digest içeren response'larda ETag üretilmez; 5.0B digest public cache validator yapılmaz.

### 10.6 Post-commit response serialization recovery

Terminal persistence ve post-persist scope/subject verification başarıyla tamamlandıktan sonra HTTP DTO projection veya JSON serialization hata verirse canonical run geri alınmaz ve application execution tekrar çalıştırılmaz. Adapter yalnız aşağıdaki sabit güvenli envelope'u, HTTP 500 ve `RESPONSE_SERIALIZATION_FAILED` ile döndürür:

```text
ResponseSerializationRecoveryV1
  run_id: str
  correlation_id: str
  persisted: Literal[true]
  recovery_endpoint: "/api/v1/analysis-runs/{run_id}/result"
  recovery_reference: str                 # run_id ile aynı opaque değer
```

Bu envelope ancak persisted run'ın scope ve initiating-subject binding'i request ile yeniden doğrulandıktan sonra üretilebilir. Payload, digest, source ID, exception message/repr veya stack trace içermez. Operational alert ve required security-audit event denenir; post-commit audit sink hatası canonical run'ı etkilemez. Client aynı Start/Resume/Retry isteğini tekrarlarsa persisted idempotent result okunur, analysis yeniden çalıştırılmaz.

---

## 11. Error Modeli

### 11.1 Boundary error code'ları

`ApiErrorCodeV1`, aşağıdaki HTTP-boundary değerleri ile 5.0C `AnalysisErrorCode` değerlerinin kapalı birleşimidir:

- `MALFORMED_REQUEST`
- `INVALID_HEADER`
- `AUTHENTICATION_REQUIRED`
- `AUTHENTICATION_PROVIDER_UNAVAILABLE`
- `UNSUPPORTED_MEDIA_TYPE`
- `REQUEST_TOO_LARGE`
- `API_CONTRACT_VERSION_UNSUPPORTED`
- `INVALID_CURSOR`
- `RESPONSE_SERIALIZATION_FAILED`
- `RUN_SUBJECT_MISMATCH`
- `RUN_SUBJECT_UNBOUND`
- `ADMISSION_LIMIT_REACHED`
- `SOURCE_INTEGRITY_ERROR`
- `SOURCE_NOT_FOUND`
- `SOURCE_SCOPE_MISMATCH`
- `SOURCE_UNAUTHORIZED`
- `SOURCE_STATUS_INVALID`
- `SOURCE_TYPE_INVALID`
- `SOURCE_CONTENT_UNAVAILABLE`
- `SOURCE_RESOLVER_UNAVAILABLE`
- tüm mevcut `AnalysisErrorCode` değerleri, isimleri değiştirilmeden.

### 11.2 Exhaustive HTTP mapping

| Error code/category | HTTP | Retryable policy | Fail mode |
|---|---:|---|---|
| `MALFORMED_REQUEST`, `INVALID_HEADER` | 400 | false | closed |
| `AUTHENTICATION_REQUIRED` | 401 | false | closed; `WWW-Authenticate` profile'a göre |
| `AUTHENTICATION_PROVIDER_UNAVAILABLE` | 503 | true | closed |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | false | closed |
| `REQUEST_TOO_LARGE` | 413 | false | closed before full materialization |
| `API_CONTRACT_VERSION_UNSUPPORTED` | 400 | false | closed |
| `INVALID_CURSOR` | 422 | false | closed |
| `ADMISSION_LIMIT_REACHED` | 429 | true | closed; `Retry-After` zorunlu |
| `RUN_SUBJECT_MISMATCH`, `RUN_SUBJECT_UNBOUND` | 409 | false | closed |
| `SOURCE_INTEGRITY_ERROR` | 500 | false | closed + security alert |
| `SOURCE_NOT_FOUND` | 404 | false | closed; existence hiding uygulanır |
| `SOURCE_SCOPE_MISMATCH` | 409 | false | closed; computation başlamaz |
| `SOURCE_UNAUTHORIZED` | 403 | false | closed; payload materialize edilmez |
| `SOURCE_STATUS_INVALID`, `SOURCE_TYPE_INVALID` | 422 | false | closed; caller payload'ına fallback yok |
| `SOURCE_CONTENT_UNAVAILABLE`, `SOURCE_RESOLVER_UNAVAILABLE` | 503 | true | closed; fallback yok |
| `INVALID_COMMAND`, `INVALID_QUERY` | 422 | false | closed |
| `UNAUTHORIZED`, `AUTHORIZATION_REVOKED`, `RESUME_SOURCE_UNAUTHORIZED` | 403 | false | closed |
| `AUTHORIZATION_PROVIDER_UNAVAILABLE` | 503 | true | closed |
| `NOT_FOUND` | 404 | false | closed; unauthorized existence gizlenir |
| `SCOPE_MISMATCH`, `RUN_ID_CONFLICT`, `FINGERPRINT_CONFLICT`, `SCOPE_CLAIM_CONFLICT`, `PERSISTENCE_CONFLICT` | 409 | false | closed |
| `SCOPE_CLAIM_UNAVAILABLE`, `PERSISTENCE_UNAVAILABLE`, `SECURITY_AUDIT_FAILED` | 503 | true | closed |
| `RESUME_SOURCE_INVALID` | 409 | false | clean-start yok |
| `RESUME_SOURCE_CORRUPTED`, `PERSISTENCE_INTEGRITY_ERROR`, `INTERNAL_INVARIANT_BREACH` | 500 | false | closed + operational alert |
| `EXECUTION_FAILED` | 500 | false | closed; raw engine exception yok |
| `SCOPE_FINALIZATION_FAILED`, `DTO_PROJECTION_FAILED` | 500 | true | canonical commit olabilir; safe recovery hint korunur |
| `RESPONSE_SERIALIZATION_FAILED` | 500 | true | canonical commit geri alınmaz |

Mapping table import-time exhaustiveness assertion ile `set(AnalysisErrorCode)` kapsamını doğrular. Yeni 5.0C error code eklenirse adapter açık mapping eklenmeden başlatılamaz; fakat 5.0D, 5.0C enum'unu değiştirmez.

Public message sabit allowlist'ten gelir. Raw exception, SQL, stack trace, auth token, document byte'ı, financial payload veya digest hata mesajına/log context'e girmez. `safe_metadata` yalnız primitive/tagged güvenli alanları ve 5.0C'nin sağladığı `run_id/recovery_query_run_id` hint'ini taşıyabilir.

---

## 12. Authentication / Authorization Sınırı

### 12.1 Bağlayıcı v1 trust profile

Milestone 5.0D gerçek bir authentication sistemi kurmaz. Token doğrulama, credential parsing, kullanıcı oturumu, OAuth/OIDC, SSO, MFA, identity provisioning veya issuer key discovery bu milestone'un sorumluluğu değildir. API katmanı yalnız dış bir trusted authentication adapter/composition root tarafından önceden doğrulanmış, framework-bağımsız bir `AuthenticationContext` kabul eder.

```text
external trusted authentication adapter / composition root
        │  verifies identity outside 5.0D
        ▼
TrustedAuthenticationContextProviderPort.current_context()
        │
        ▼
immutable AuthenticationContext
        │
        ├─► HTTP adapter -> ApplicationScopeDTO
        └─► HTTP adapter -> ApplicationAuditContextDTO
                              │
                              ▼
                    5.0C AuthorizationPort
```

`AuthenticationContext` üretmek API router'ın, HTTP schema'nın veya application core'un sorumluluğu değildir. Router credential parse etmez ve raw header'lardan context assemble etmez.

### 12.2 Exact AuthenticationContext sözleşmesi

```python
@dataclass(frozen=True)
class AuthenticationContext:
    subject_id: str
    tenant_id: str | None
    authentication_method: str
    authentication_strength: AuthenticationStrength
    issued_at: datetime
    expires_at: datetime | None
    correlation_id: str
    claims_version: str
    trusted_issuer: str
    authorization_context_reference: str
```

`AuthenticationStrength` HTTP/framework bağımsız kapalı enum'dur:

- `BASIC`
- `STRONG`
- `PHISHING_RESISTANT`

Invariant'lar:

1. Nesne immutable/frozen'dır; FastAPI, Starlette, Pydantic, request veya token tipi taşımaz.
2. `subject_id`, `authentication_method`, `claims_version`, `trusted_issuer`, `correlation_id` ve `authorization_context_reference` boş olamaz.
3. `issued_at` ve varsa `expires_at` timezone-aware olmalıdır; `expires_at > issued_at` zorunludur.
4. `issued_at` zorunludur; trusted clock'a göre en fazla 60 saniye gelecekte olabilir. Daha ileri timestamp fail-closed'dur.
5. Context yaşı `now - issued_at <= 15 dakika` olmalıdır. Daha eski context, `expires_at` hâlâ ileri tarih olsa bile reddedilir.
6. `expires_at` varsa request kabul anında `expires_at > now` olmalıdır. `expires_at=None` maksimum 15 dakikalık context-age sınırını kaldırmaz.
7. `trusted_issuer`, composition root'ta önceden tanımlanmış allowlist/profile ile eşleşmelidir; caller input'u değildir.
8. Context `correlation_id`, HTTP `X-Correlation-ID` ile birebir eşleşmelidir. Uyuşmazlık malformed/untrusted authentication'dır.
9. `authorization_context_reference` token, token ID veya credential değildir; aynı subject/tenant/claims policy context'i için stabil opaque referanstır ve idempotent retry boyunca değişmez.
10. Context'in Python tipine sahip olmak tek başına trust kanıtı değildir; yalnız production composition root'un bağladığı trusted provider'dan gelen instance kabul edilir.

### 12.3 Application mapping

HTTP adapter aşağıdaki deterministic mapping'i uygular:

```text
ApplicationScopeDTO.tenant_id
    <- AuthenticationContext.tenant_id

ApplicationAuditContextDTO.actor_id
    <- AuthenticationContext.subject_id
ApplicationAuditContextDTO.caller_type
    <- "authenticated_http_caller"
ApplicationAuditContextDTO.request_source
    <- "api_v1"
ApplicationAuditContextDTO.purpose
    <- validated request purpose veya route-specific closed purpose
ApplicationAuditContextDTO.client_request_id
    <- Idempotency-Key (write) veya X-Request-ID (read/cancel)

command/query.authorization_context_reference
    <- AuthenticationContext.authorization_context_reference
```

Raw authentication claims, credentials ve issuer metadata'sının tamamı audit attributes'a kopyalanmaz. Gerekli `authentication_method`, `authentication_strength`, `claims_version` ve `trusted_issuer` değerleri yalnız allowlist edilmiş güvenli audit metadata'sı olarak taşınabilir; subject/tenant zaten typed alanların sahibidir.

### 12.4 Authentication ve authorization ayrımı

- **Authentication:** caller kimliğinin trusted dış adapter tarafından doğrulanması ve immutable context sağlanmasıdır.
- **Authorization:** doğrulanmış subject/tenant'ın belirli company/period/run action'ına erişip erişemeyeceği kararıdır ve değişmemiş 5.0C `AuthorizationPort` sorumluluğudur.

Authentication success authorization grant anlamına gelmez. Authentication başarılı, authorization deny sonucu normal ve zorunlu bir test senaryosudur. Router authorization kararı üretmez; 5.0C pre-execution ve pre-persistence revalidation'ı bypass edemez.

### 12.5 Fail-closed politika

- missing context: `AUTHENTICATION_REQUIRED`, HTTP 401;
- malformed context veya correlation mismatch: `AUTHENTICATION_REQUIRED`, HTTP 401;
- untrusted issuer: `AUTHENTICATION_REQUIRED`, HTTP 401;
- expired context: `AUTHENTICATION_REQUIRED`, HTTP 401;
- trusted context provider unavailable: `AUTHENTICATION_PROVIDER_UNAVAILABLE`, HTTP 503;
- tenant/subject scope mismatch: Section 12.8'deki tek kapalı karar tablosu uygulanır;
- anonymous veya raw-header fallback: yasak.

Start, Resume, Retry, Cancel, History, Status, Result ve Execution Detail endpoint'lerinin tamamı trusted `AuthenticationContext` gerektirir. Production default'unda `/docs`, `/redoc` ve `/openapi.json` kapalıdır; açık hale getirilecekse aynı trusted context + explicit documentation authorization gerekir. Yalnız `/health/live` authentication olmadan 200/503 process-liveness dönebilir. `/health/ready` authentication istemez fakat yalnız genel `ready: bool` ve sabit status döndürür; dependency adı, DSN, issuer, tenant veya exception ayrıntısı sızdırmaz. Analysis endpoint'i hiçbir profile'da public olamaz.

### 12.6 Development/test adapter ayrımı

Development/test ortamı deterministic fake context provider kullanabilir; bu provider:

- production modül/composition path'inde default olarak import veya bind edilmez;
- açık `development`/`test` environment guard'ı gerektirir;
- production environment'ta seçilirse startup fail-closed olur;
- raw `X-User-Id`, `X-Tenant-Id` veya benzeri header'lardan context üretmez;
- test fixture/config tarafından doğrudan immutable context alır;
- production adapter ile aynı `TrustedAuthenticationContextProviderPort` davranış kontratına uyar.

Production composition root, dış trusted adapter bağlanmadan başlatılamaz. 5.0D production authentication sağlayıcısı implemente etmez; yalnız trusted context boundary'sini tüketir.

### 12.7 Sonraki security milestone'u

Gerçek sağlayıcı entegrasyonu, credential/token doğrulama, OAuth/OIDC, SSO, MFA, JWKS/key rotation, identity lifecycle ve tenant claim üretimi ayrı security milestone'una bırakılmıştır. Bu gelecek çalışma 5.0D `AuthenticationContext` trust boundary'sini kullanır; 5.0A–5.0C contract'larını değiştiremez.

### 12.8 Durable subject ownership ve kapalı HTTP karar tablosu

Authoritative current subject yalnız `AuthenticationContext.subject_id`'dir. Yeni 5.0D run'larında initiating subject, mevcut `analysis_run_scope_claims` reservation'ına `initiating_subject_id` alanıyla atomik bağlanır. Bu alan audit kaydı, workflow state veya authorization grant değildir; immutable run ownership metadata'sıdır.

5.0C public `RunScopeClaimPort` imzaları değişmez. Production composition, aynı protocol'ü uygulayan subject-bound concrete repository'yi request context ile kurar:

```python
SubjectBoundRunScopeClaimRepository(
    session_factory: Callable[[], Session],
    initiating_subject_id: str,
)
```

Bu sınıf mevcut repository'yi sonradan saran ve ikinci UPDATE yapan bir decorator değildir. `claim`, `run_id, tenant_id, company_id, financial_period_id, operation_kind, initiating_subject_id` alanlarını tek PostgreSQL INSERT/unique-CAS statement'ında yazar. Conflict halinde authoritative satırı aynı kısa transaction içinde kilitli/consistent okuyup altı alanın tamamını exact karşılaştırır; herhangi bir fark typed conflict'tir. `verify` ve `finalize`, `run_id` ile birlikte beş ownership alanını ve subject'i WHERE/CAS predicate'ine dahil eder; zero-row veya mismatch fail-closed'dur. `finalize` ownership alanlarını değiştirmez, yalnız mevcut 5.0C finalization invariant'ını uygular. API preflight/post-result kontrolü için yalnız metadata okuyan `ApiRunOwnershipInspectorPort.load(run_id) -> ApiRunOwnershipView | None` kullanılır. Router ORM çağırmaz.

Database uniqueness `run_id` üzerinde tektir; tenant/company/period/subject ayrı namespace yaratmaz. Böylece aynı `run_id` iki tenant, company, period, operation veya subject tarafından aynı anda claim edilemez. Claim/verify/finalize'ın her biri ayrı kısa transaction olsa da immutable row + exact CAS predicate, preflight → persist → finalize → DTO projection boyunca ownership'in değişmesini engeller. Terminal persist öncesi ve DTO projection öncesi exact scope/subject yeniden doğrulanır. Post-commit audit failure bu satırı değiştiremez veya geri alamaz.

Migration additive'dir. Pre-5.0D historical claim'ler `initiating_subject_id=NULL` olarak legacy-unbound kalır. PostgreSQL trigger migration sonrasında yeni INSERT'te null/blank subject'i reddeder; mevcut immutability/finalization trigger'ı subject alanını immutable ownership sütunları kümesine ekler ve UPDATE/DELETE ile subject değişimini reddeder. Böylece legacy satırları uydurma bir subject ile backfill edilmez, fakat yeni claim DB seviyesinde subject'siz oluşamaz. Legacy run'lar HTTP write replay yapamaz (`RUN_SUBJECT_UNBOUND`, 409); read ise aynı tenant içinde yalnız explicit `AuthorizationPort` grant'iyle mümkündür.

| Senaryo | Write | Read/Cancel | HTTP |
|---|---|---|---:|
| Authentication yok/malformed/expired/untrusted | başlamaz | başlamaz | 401 |
| Authentication var, authorization deny | başlamaz | payload/existence policy dışında veri yok | 403 |
| Gerçek resource yok | — | not found | 404 |
| Cross-tenant veya wrong company/period read | — | existence gizlenir | 404 |
| Aynı tenant, farklı subject read, explicit authorization grant | — | izin verilir | 200 |
| Aynı tenant, farklı subject read, deny | — | reddedilir | 403 |
| Aynı run + aynı tenant/scope + aynı initiating subject + aynı command/fingerprint | replay mümkün | — | 200 |
| Aynı run + aynı tenant/scope + farklı initiating subject | conflict | — | 409 `RUN_SUBJECT_MISMATCH` |
| Aynı run + farklı tenant/company/period/operation | conflict; response DTO yok | — | 409 `SCOPE_MISMATCH` |
| Legacy unbound run write replay | conflict | — | 409 `RUN_SUBJECT_UNBOUND` |

Different-subject write için authorization grant otomatik replay hakkı vermez; subject ownership kontrolü authorization'dan bağımsız ek fail-closed kapıdır. Wrong-scope persisted result hiçbir durumda response'a map edilmez. Read tarafında initiating subject eşitliği otomatik grant değildir; `AuthorizationPort` her zaman çalışır.

---

## 13. Validation Kuralları

Validation dört sırada uygulanır:

1. **Transport:** method, content type, body size, required header.
2. **Wire schema:** Pydantic strict type, closed enum, extra forbid, string/count bounds.
3. **Cross-field adapter invariants:** path/body/header/scope/source-reference tutarlılığı.
4. **Application invariants:** değişmemiş 5.0C dataclass constructors ve mapping.

Normatif cross-field kurallar:

- `Idempotency-Key` target run ID'dir; body'de ikinci run ID alanı yoktur.
- Resume/Retry path source ID ile target ID farklıdır.
- source intent company/period body scope ile birebir aynıdır.
- requested output dependency closure'ı için financial source intent kümesi exact olmalıdır; 5.0C mapping son authoritative kontroldür.
- request source ID'si yoksa ilgili persisted computation input'u üretilmez;
- document/result ID, aynı engine'in `FinancialSourceIntentDTO.source_bindings` kümesinde uygun kapalı role ile tam bir kez bulunmalıdır;
- `period_start_date <= period_end_date`; months 1..12.
- duplicate output/source binding/section/block type reddedilir.
- prior-period fact key seti 5.0C closed setiyle birebir olmalıdır.
- report/dashboard/render request yalnız ilgili requested output dependency'si varsa kabul edilir; aksi payload confusion olarak reddedilir.
- tenant, actor ve auth reference body'den kabul edilmez.
- `include_payload(s)` varsayılan false; true için ayrıca payload-read authorization uygulanır.
- unknown cursor/version/tag/enum fail-closed'dur.

Validation error lokasyonları internal ayrıntıyı sınırlayan `safe_metadata.fields` allowlist'iyle verilebilir; request değeri echo edilmez.

### 13.1 Trusted input resolver sözleşmeleri

```python
@dataclass(frozen=True)
class ResolvedDocumentInput:
    document_id: UUID
    company_id: UUID
    financial_period_id: UUID
    content: bytes
    original_filename: str
    mime_type: str
    sha256_checksum: str
    document_type: str

class DocumentInputResolverPort(Protocol):
    def resolve_document_input(
        self,
        *,
        document_id: UUID,
        company_id: UUID,
        financial_period_id: UUID,
        expected_engine_code: ApplicationEngineCode,
        authentication: AuthenticationContext,
    ) -> ResolvedDocumentInput: ...

@dataclass(frozen=True)
class ResolvedTrialBalanceInput:
    analysis_result_id: UUID
    company_id: UUID
    financial_period_id: UUID
    result_payload: dict[str, ApplicationJsonValue]
    canonical_digest: str
    analysis_type: str
    status: str

class AnalysisResultInputResolverPort(Protocol):
    def resolve_trial_balance_input(
        self,
        *,
        analysis_result_id: UUID,
        company_id: UUID,
        financial_period_id: UUID,
        authentication: AuthenticationContext,
    ) -> ResolvedTrialBalanceInput: ...
```

Her iki resolver da trusted integration adapter'dır; router ORM/repository/content store çağırmaz. Resolution yalnız authentication tamamlandıktan ve metadata-read authorization grant edildikten sonra yapılır. Raw exception sabit `ApiInputResolutionErrorCode` kümesine normalize edilir:

- `SOURCE_NOT_FOUND`;
- `SOURCE_SCOPE_MISMATCH`;
- `SOURCE_UNAUTHORIZED`;
- `SOURCE_STATUS_INVALID`;
- `SOURCE_TYPE_INVALID`;
- `SOURCE_CONTENT_UNAVAILABLE`;
- `SOURCE_CHECKSUM_MISMATCH`;
- `SOURCE_CANONICAL_DIGEST_MISMATCH`;
- `SOURCE_RESOLVER_UNAVAILABLE`.

Not-found/unauthorized existence hiding H1 tablosuna uyar; checksum/digest mismatch integrity error olarak HTTP 500 ve operational security alert üretir. Resolver unavailable HTTP 503'tür. Hiçbir durumda caller payload'ına fallback yapılmaz.

### 13.2 Document integrity ve file policy

`DocumentInputResolverPort` şu kontrollerin tamamını engine çağrısından önce yapar:

1. `FinancialDocument.id/company_id/period_id` exact eşleşmesi.
2. Document status `completed`; expected BS/IS document classification/type uyumu.
3. Authoritative content storage'dan bytes materialization.
4. `sha256(content)` ile persisted 64-char lowercase SHA-256 checksum exact eşitliği.
5. Content length `1..10 MiB`.
6. Kapalı format allowlist: `.xlsx` + `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` + ZIP/OOXML magic; veya `.pdf` + `application/pdf` + `%PDF-` magic.
7. PDF'nin engine'in mevcut text-extractable PDF kuralına uyumu; `.xls`, OCR-only/image PDF ve diğer formatlar reddedilir.

Filename tek başına trusted değildir; yalnız extension sinyali olarak MIME ve magic-byte ile birlikte kullanılır. Resolver'ın döndürdüğü checksum/bytes immutable aynı nesnededir. Request'te document ID varken raw content alanı bulunmadığından “başka byte + bu document ID” temsili schema seviyesinde imkânsızdır.

### 13.3 Trial-balance result integrity

`AnalysisResultInputResolverPort` yalnız:

- exact company/period scope'taki;
- `analysis_type=trial_balance`;
- terminal `completed` status'taki;
- non-null map `result_json` sahibi

owner'ı kabul eder. Adapter storage canonical codec'iyle payload byte'larını üretir, SHA-256 hesaplar ve owner'ın authoritative stored canonical digest'iyle constant-time karşılaştırır. Stored digest yoksa result input olarak kullanılamaz; caller-supplied digest veya payload baseline sayılmaz.

Local PostgreSQL owner authoritative store ise, 5.0D implementation `financial_analysis_results` üzerinde 5.0D-owned additive, immutable-on-terminal `canonical_result_digest` alanı/backfill/write-path doğrulaması uygulamak zorundadır. Digest, storage canonical codec ile `result_json` üzerinden üretilir; terminal non-null payload için 64 lowercase hex ve non-null olması DB CHECK + insert/update trigger ile zorlanır. Trigger terminal owner'ın `result_json` veya `canonical_result_digest` alanının sonradan değiştirilmesini reddeder. Backfill aynı codec'i kullanır ve doğrulanamayan satır deployment readiness'i kapatır. Yeni owner yazımında mevcut persistence adapter digest'i `EngineResultEnvelope.result` üzerinden hesaplar; public 5.0B binding/command'a alan eklenmez. Bu değişiklik payload kopyalamaz ve 5.0B public persistence contract'ını değiştirmez. Alternatif external authoritative owner adapter aynı stored-digest garantisini sağlamalıdır. Digest mismatch/corruption halinde `AnalysisInputsDTO` kurulmaz ve Orchestrator çağrılmaz.

### 13.4 Mapping atomikliği

HTTP mapper, `AnalysisInputsDTO` ve `FinancialSourceIntentDTO`'yu aynı resolved source setinden tek adımda kurar. Ayrı caller alanlarının sonradan birleştirilmesi yasaktır:

```text
ResolvedDocumentInput(document_id, verified bytes, checksum)
    -> AnalysisInputsDTO.content/filename
    -> matching FinancialSourceReferenceDTO(source_document_id=document_id)

ResolvedTrialBalanceInput(result_id, verified payload, digest)
    -> AnalysisInputsDTO.trial_balance_result
    -> matching FinancialSourceReferenceDTO(source_analysis_result_id=result_id)
```

Resolver sonucu ile intent ID/role uyuşmazsa `INVALID_COMMAND`; computation başlamaz.

---

## 14. Idempotency Davranışı

5.0B authoritative request fingerprint/idempotency sahibi, 5.0C scope-aware command digest/claim sahibi olmaya devam eder. HTTP katmanı yeni bir idempotency store oluşturmaz.

Write retry eşitliği için aşağıdaki alanların tamamı stabil olmalıdır:

- `Idempotency-Key` / target `run_id`;
- `X-Correlation-ID`;
- `generated_at`;
- authenticated `subject_id`, tenant ve stabil authorization context reference;
- purpose ve request payload'ın tamamı;
- resolved source ID'leri, authoritative checksum/digest'leri ve trusted filename metadata'sı.

Semantik:

```text
same key + same principal/scope + same complete command + same fingerprint
    -> canonical idempotent replay, HTTP 200, idempotent_replay=true

same key + different company/period/tenant
    -> fail-closed 409; hiçbir wrong-scope DTO yok

same key + same scope + different subject/header/body/generated_at/correlation/resolved-source-digest
    -> command/fingerprint conflict, 409
```

API adapter body normalizasyonuyla iki farklı wire payload'ı “aynı” saymaz. Client aynı logical request için canonical/stabil payload'ı tekrar göndermelidir. Concurrent duplicate aynı/cross process olabilir; ActiveExecutionPort reddetmez. Terminal winner 5.0B tarafından belirlenir; loser staged financial owner/lineage SAVEPOINT rollback/discard kuralı korunur.

HTTP proxy'nin güvenli method retry'sı yalnız client aynı headers/body'yi koruyorsa mümkündür. Adapter automatic retry yapmaz.

---

## 15. Start / Resume / Retry / Cancel Endpoint Akışları

### 15.1 Start

```text
authenticate
→ transport/wire validation
→ admission lease acquire
→ authorize input-source metadata read
→ trusted document/result resolution ve integrity validation
→ principal + headers + body + resolved sources -> StartAnalysisCommand
→ AnalysisApplicationService.start
→ 5.0C audit/auth/claim/orchestrator/owner-plan/revalidation/persist/finalize
→ ApplicationOutcome mapping
→ explicit response serialization
→ finally admission lease release
→ 201 new veya 200 replay
```

Input mapping finansal hesaplama değildir. Verified resolver bytes/payload'ı yalnız `AnalysisInputsDTO`, aynı resolver nesnesindeki source ID/role ise yalnız `FinancialSourceIntentDTO` olur. Caller raw byte/payload veya persistence owner/table/FK/audit time seçemez.

### 15.2 Resume

Resume source ID path'ten, new target ID idempotency header'dan gelir. API payload source snapshot taşımaz. 5.0C source metadata check → source authorization → 5.0B snapshot materialization sırası aynen korunur. Source/target company-period-tenant eşit değilse 409/403 fail-closed; clean-start yoktur.

### 15.3 Retry

Retry yeni run ID ve source run ID gerektirir. Body `original_operation` kapalı enum'dur. API reuse eligibility hesaplamaz, previous snapshot üretmez ve automatic retry yapmaz. `original_operation=RESUME` için resume doğrulaması zorunludur.

### 15.4 Cancel

Cancel explicit HTTP çağrısıdır ve local cooperative cancellation isteğidir. Normal response status'u `CancellationStatus` taşır. Local invocation yokluğu persisted run yokluğu anlamına gelmez; 5.0C canonical read/claim kontrolü sonucu `NOT_ACTIVE`, `ALREADY_TERMINAL` veya `NOT_FOUND` ayrımı yapılır. API durable cancellation veya cross-process cancellation garantisi vermez.

### 15.5 Client disconnect

v1'de HTTP disconnect otomatik cancel değildir. Engine thread'i zorla öldürülmez; explicit cancel endpoint dışında cancellation probe tetiklenmez. Bu davranış aynı-process/cross-process correctness farkı oluşturmaz ve terminal persistence bütünlüğünü korur.

### 15.6 Process-local bounded admission control

Rate limiting/quota sonraki milestone'a kalabilir; fakat 5.0D analysis execution limitsiz olamaz.

```python
@dataclass(frozen=True)
class AdmissionLease:
    lease_id: str
    tenant_key: str
    subject_id: str
    acquired_at: datetime

class AnalysisAdmissionControlPort(Protocol):
    def try_acquire(
        self,
        *,
        tenant_id: str | None,
        subject_id: str,
        run_id: str,
        acquired_at: datetime,
    ) -> AdmissionLease | None: ...

    def release(self, lease: AdmissionLease) -> None: ...
```

Normatif production defaults ve config validation:

- `GLOBAL_MAX_ACTIVE_ANALYSES=4`, zorunlu integer `> 0`;
- `TENANT_MAX_ACTIVE_ANALYSES=2`, zorunlu integer `> 0` ve global limitten büyük olamaz;
- `SUBJECT_MAX_ACTIVE_ANALYSES=2`, opsiyonel; set ise `> 0` ve tenant limitten büyük olamaz;
- `ADMISSION_RETRY_AFTER_SECONDS=5`, integer `1..60`;
- acquire non-blocking'dir; local queue oluşturmaz.

Global, tenant veya subject budget doluysa response `429 Too Many Requests`, error `ADMISSION_LIMIT_REACHED`, `retryable=true` ve `Retry-After: 5` olur. 503 kullanılmaz. Lease authentication ve wire validation sonrasında, trusted source materialization ve threadpool execution öncesinde alınır. Input resolution, 5.0C use-case, HTTP projection ve explicit serialization tek `try/finally` lease lifecycle'ı içindedir. Success, replay, validation-after-resolution, authorization deny/revoke, resolver error, engine exception, cancellation, persistence/projection/serialization failure ve client disconnect dahil bütün çıkışlarda release exact-once/idempotent çalışır.

Router hafif async boundary'de authenticate/validate/admission yapar; yalnız lease alındıktan sonra explicit bounded `run_in_threadpool` ile senkron use-case'i başlatır. Her request için yeni executor/thread oluşturmak yasaktır. Process worker threadpool kapasitesi global admission limitinden küçük olamaz; limitsiz thread spawning yoktur.

Admission v1 process-local'dır. Multi-process toplam limit veya distributed fairness garantisi vermez; her process aynı finite config'i uygular. Distributed admission control gelecek milestone'dur. Bu mekanizma idempotency/correctness sahibi değildir; saturation geçici transport sonucu olduğundan aynı request daha sonra aynı idempotency key ile yeniden denenebilir.

### 15.7 Deadline/deployment contract

- `ANALYSIS_REQUEST_DEADLINE_SECONDS=120`, zorunlu finite `> 0` config;
- application deadline cancellation probe'a cooperative sinyal verir; hard kill garantisi yoktur;
- ASGI server graceful timeout en az 130 saniye, reverse proxy upstream timeout en az 135 saniye olarak deployment validation'da zorlanır;
- body/header read timeout ayrı ve en çok 15 saniyedir;
- proxy/client timeout veya disconnect sonrasında backend execution bir sonraki cooperative probe'a ya da terminal completion'a kadar devam edebilir;
- böyle bir execution lease'i ancak backend `finally` tamamlandığında bırakır; transport disconnect release sinyali değildir;
- background/queue davranışı veya durable active-job iddiası yoktur.

---

## 16. History ve Query Endpointleri

Mevcut `AnalysisQueryService._one()` bütün read exception'larını `NOT_FOUND`'a indirdiği için 5.0D, 503/500 kategorisini bu sonuçtan yeniden üretmeye çalışmaz. 5.0C public contract veya implementation değiştirilmez. HTTP read path'i, aynı public DTO/portları kullanan trusted integration coordinator üzerinden yürür:

```python
class ApiReadAction(str, Enum):
    STATUS_READ = "analysis.status.read"
    RESULT_METADATA_READ = "analysis.result.metadata.read"
    RESULT_PAYLOAD_READ = "analysis.result.payload.read"
    EXECUTION_METADATA_READ = "analysis.execution.metadata.read"
    EXECUTION_PAYLOAD_READ = "analysis.execution.payload.read"
    HISTORY_READ = "analysis.history.read"
    INPUT_SOURCE_READ = "analysis.input_source.read"

class ApiAnalysisReadFacade:
    def __init__(
        self,
        *,
        reads: AnalysisReadPort,
        authorization: AuthorizationPort,
        security_audit: SecurityAuditPort,
        observability: ObservabilityPort,
        clock: ApplicationClockPort,
        error_classifier: ApiReadErrorClassifier,
    ) -> None: ...

    def get_status(self, query: GetAnalysisStatusQuery) -> ApiReadOutcome[AnalysisRunStatusDTO]: ...
    def get_result(self, query: GetAnalysisResultQuery) -> ApiReadOutcome[AnalysisResultDTO]: ...
    def get_execution_detail(self, query: GetExecutionDetailQuery) -> ApiReadOutcome[AnalysisExecutionDTO]: ...
    def list_history(self, query: ListAnalysisHistoryQuery) -> ApiReadOutcome[AnalysisHistoryPageDTO]: ...
```

Facade router değildir; ORM/model/repository import etmez. Scope-qualified `AnalysisReadPort` ve mevcut authorization/audit ports üzerinden çalışır. `ApiReadErrorClassifier` yalnız kapalı trusted exception tiplerini sınıflandırır:

- `None`/typed not-found -> `NOT_FOUND`;
- `ApplicationReadIntegrityError`/digest/invariant error -> `INTEGRITY_FAILURE`;
- SQLAlchemy/driver connection timeout/unavailable typed errors -> `INFRASTRUCTURE_UNAVAILABLE`;
- cursor/value validation -> `INVALID_QUERY`;
- unknown exception -> `INTERNAL_INVARIANT_BREACH`.

String message veya exception text üzerinden sınıflandırma yasaktır. Raw exception public outcome'a girmez. Bu façade 5.0C `AnalysisQueryService` public contract'ını değiştirmez; yalnız HTTP integration path'inin category-preserving coordinator'ıdır.

Tüm read endpoint'lerinde sıralama:

1. authenticate;
2. company/period + principal tenant target'ını kur;
3. run-specific ise facade üzerinden claim scope/subject metadata'sını payload materialize etmeden çöz;
4. caller scope ile exact karşılaştır;
5. closed `ApiReadAction` ile 5.0C query DTO/audit purpose kur;
6. facade `AuthorizationPort` ve required `SecurityAuditPort` akışını çağır;
7. facade authoritative read'i çalıştırıp typed infrastructure result üretir;
8. outcome'u serialize et.

Wrong tenant/company/period response'u hiçbir result/execution/payload DTO'ya map edilmez. Run-specific endpoint'lerde claim metadata'sı yoksa generic 404. Unauthorized existence ile missing resource public message'i ayrıştırılmaz.

`include_payloads=false` ve `include_payload=false` varsayılandır. True isteği ayrı `authorize_read(..., include_payload=True)` kontrolünden geçer. Payload digest/owner ID'leri yalnız başarılı authorization sonrası response'a girer.

History yalnız finalized canonical run'ları döndürür. `RunScopeClaim` running-job state'i değildir; history'de CLAIMED ama terminal olmayan reservation yayımlanmaz.

Kesin HTTP mapping:

| Facade sonucu | HTTP |
|---|---:|
| true not found | 404 |
| cross-tenant/wrong-scope hidden read | 404 |
| same-tenant authenticated authorization deny | 403 |
| malformed cursor/input | 422 |
| persistence/driver unavailable | 503 |
| integrity/invariant breach | 500 |

History structural scope alanı 5.0C DTO construction gereği kullanılsa bile authorization action'ı `ApiReadAction.HISTORY_READ` ve `audit_context.purpose="analysis.history.read"` ile zorunlu olarak ayrıştırılır. Production authorization adapter bu action'ı START yetkisi olarak yorumlayamaz; import-time/action-exhaustiveness testleri bunu zorlar.

---

## 17. Pagination

History pagination keyset/cursor tabanlıdır; offset kullanılmaz. İç 5.0C cursor sıralaması `(finalized_at DESC, orchestration_run.id DESC)` olarak stabildir.

HTTP cursor doğrudan internal cursor değildir:

```text
CursorEnvelopeV1
  version: 1
  tenant_scope_hash: str
  company_id: UUID
  financial_period_id: UUID
  internal_cursor: str
  key_id: str
  issued_at: aware datetime
  expires_at: aware datetime
  signature: base64url(HMAC-SHA256(...))
```

Kurallar:

- Signed payload, `signature` alanı **hariç** yukarıdaki alanların exact kümesidir. Unknown/missing alan, duplicate JSON key veya non-string value reddedilir.
- UUID'ler canonical lowercase hyphenated; datetime'lar UTC RFC 3339 `YYYY-MM-DDTHH:MM:SSZ`; integer `version=1`; JSON key'leri Unicode code-point sırasıyla sıralı, whitespace'siz ve UTF-8 encode edilir. Bu byte dizisi `signed_bytes`'tır.
- `signature = base64url_without_padding(HMAC-SHA256(keyring[key_id], signed_bytes))` olarak hesaplanır. Son taşıma değeri, signed payload + signature içeren canonical JSON'un padding'siz base64url encode edilmiş halidir.
- `tenant_scope_hash = hex(SHA-256(UTF-8("tenant:v1:" + (tenant_id veya "<none>"))))`; raw tenant ID cursor'a girmez. Hash yalnız scope bağlama sinyalidir, authorization yerine geçmez.
- HMAC key environment/secret provider'dan gelir; source code'a yazılmaz. `key_id` yalnız startup'ta doğrulanmış finite keyring içinde lookup edilir; dynamic path/file/secret lookup tetiklemez.
- Encode yalnız tek `ACTIVE` key ile yapılır. Decode `ACTIVE` veya `RETIRED_VERIFY_ONLY` key'i kabul eder; `DISABLED`/unknown key reddedilir. Retired verification grace süresi cursor TTL'den kısa olamaz.
- Signature, decoded byte uzunluğu ve formatı doğrulandıktan sonra `hmac.compare_digest` eşdeğeri constant-time primitive ile karşılaştırılır.
- `issued_at` zorunludur, trusted clock'a göre en fazla 60 saniye gelecekte olabilir. `expires_at = issued_at + 24 saat` zorunludur; `expires_at <= now` ise cursor reddedilir. Key retirement cursor expiry kuralını bypass edemez.
- Scope hash, company, period veya tenant mismatch, signature/tamper, future skew, expiry, invalid key state ve version mismatch aynı güvenli `INVALID_CURSOR`/422 sonucuna normalize edilir; doğrulama DB query'den önce yapılır.
- `limit` cursor içinde değildir; page'ler arasında 1..200 aralığında değişebilir, sıralamayı bozmaz.
- `limit+1` fetch ile next cursor üretilir; boş/son sayfada null.

Legacy offset pagination endpoint'leri değiştirilmez.

---

## 18. OpenAPI Politikası

- Yeni tag: `analysis-runs`.
- Operation ID'ler explicit ve stabil: `start_analysis_run_v1`, `resume_analysis_run_v1`, `retry_analysis_run_v1`, `cancel_analysis_run_v1`, `get_analysis_run_status_v1`, `get_analysis_run_result_v1`, `get_analysis_execution_v1`, `list_analysis_run_history_v1`.
- Her endpoint tüm success/error status modellerini açıkça listeler.
- JSON source-reference alanları, required headers, resolver allowlist'i ve boyut sınırları description'da bulunur; raw file/payload alanı yayımlanmaz.
- Enum'lar OpenAPI'de kapalı değer listesi olarak görünür.
- Örnekler sentetik ve hassas olmayan değerler kullanır; gerçek tax ID/token/digest/payload yoktur.
- Schema/operation adı ve açıklamalarında dahili kod adı veya ticari marka yoktur.
- Pydantic schema, 5.0C dataclass veya ORM schema'sını reflection ile üretmez.
- OpenAPI golden snapshot testi yalnız intentional API contract değişikliğinde explicit approval ile güncellenir.
- Existing OpenAPI path ve schema'ları geriye dönük korunur.

Mevcut application title/root metadata'sındaki legacy code-name kullanımı 5.0D tarafından yeni şemalara kopyalanmaz. Toplu branding refactor'ı kapsam dışıdır; Architecture Book brand-independent politikasına uygun ayrı onay gerektirir.

---

## 19. API Versioning

Üç version alanı ayrıdır:

1. URL major: `/api/v1` — breaking HTTP contract sınırı.
2. `ANALYSIS_HTTP_SCHEMA_VERSION=1.0.0` — wire DTO minor/patch takibi.
3. `APPLICATION_DTO_SCHEMA_VERSION=1.0.0` — değişmemiş 5.0C contract.

5.0B artifact serializer version yalnız artifact payload reference'ında taşınır; API veya application schema version yerine kullanılamaz.

Politika:

- additive optional HTTP field: wire minor;
- validation/message-only compatible fix: wire patch;
- field removal/type/path/error semantic değişikliği: yeni URL major;
- unknown requested version fail-closed;
- server supported version response header'ında döner;
- API v1 adapter 5.0C v1 application contract'ına explicit mapping yapar; version guessing yoktur.

5.0A, 5.0B veya 5.0C public contract değişikliği 5.0D versioning mekanizmasıyla gizlenemez.

---

## 20. Dependency Injection

### 20.1 Runtime profile

```python
class ApiRuntimeProfile(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"
```

Profile tek, immutable startup config kaynağından gelir; request/header ile değiştirilemez.

| Profile | İzin verilen güvenlik adapter'ı | Kesin yasak |
|---|---|---|
| `PRODUCTION` | external trusted context provider, deny-capable production authorization, durable security audit, real UTC clock, configured observability | fake auth, allow-all auth, in-memory/no-op audit, missing/no-op required adapter |
| `TEST` | explicit deterministic fake'ler | production credential/secret'e erişim, profile auto-detection |
| `DEVELOPMENT` | yalnız explicit `ALLOW_LOCAL_SECURITY_ADAPTERS=true` ile local adapter ve startup warning | flag olmadan local/fake; production environment marker ile birlikte local adapter |

Production composition validation başarısızsa process başlatılabilir fakat `/health/ready` false kalır ve analysis router registration/serving aktif olmaz; deployment ready sayılmaz. Silent fallback yoktur.

### 20.2 Gerçek composition ve transaction grafiği

```text
process-scoped
  ├─ SessionLocal / session_factory
  ├─ configured BlobStore
  ├─ trusted DocumentInputResolverPort
  ├─ trusted AnalysisResultInputResolverPort
  ├─ TrustedAuthenticationContextProviderPort (external trusted binding)
  ├─ ProductionAuthorizationAdapter -> external policy decision source
  ├─ DurableSecurityAuditAdapter -> required append-only audit sink
  ├─ ProductionObservabilityAdapter -> telemetry sink
  ├─ UtcApplicationClockAdapter
  └─ CursorCodec

request-scoped API lifecycle
  ├─ AuthenticationContext
  ├─ request Session
  │    ├─ SqlAlchemyAnalysisReadAdapter(session, blob_store)
  │    ├─ SqlAlchemyRunPersistenceAdapter(session, blob_store)
  │    └─ ApiAnalysisReadFacade(reads=read_adapter, authorization=..., security_audit=..., observability=..., clock=..., error_classifier=...)
  ├─ SubjectBoundRunScopeClaimRepository(session_factory, subject_id)
  ├─ ProcessLocalAnalysisAdmissionControl
  ├─ AnalysisApplicationService
  └─ AnalysisQueryService

inside 5.0C use-case
  ├─ claim/verify/finalize -> each opens its own short session_factory transaction
  ├─ terminal persistence -> request Session + 5.0B owned transaction/SAVEPOINT
  └─ read projection -> request Session read transaction; rollback/close at request end
```

`SqlAlchemyRunScopeClaimRepository` request Session almaz. Gerçek constructor `SqlAlchemyRunScopeClaimRepository(session_factory: Callable[[], Session])` şeklindedir; subject-bound 5.0D adapter aynı short-transaction topolojisini korur. Claim, verify ve finalize terminal persistence transaction'ıyla birleştirilmez. `RunScopeClaim` workflow/job state değildir.

### 20.3 Exact construction contract

| Bileşen | Constructor / source | Timeout | Outage davranışı |
|---|---|---:|---|
| Authentication context provider | `TrustedAuthenticationContextProviderPort.current_context() -> AuthenticationContext` | 2 s | 401 missing/invalid; provider exception/timeout 503 |
| Authorization | mevcut 5.0C `AuthorizationPort`; `ProductionAuthorizationAdapter(policy_client, timeout_seconds=2.0)` | 2 s/call | fail-closed `AUTHORIZATION_PROVIDER_UNAVAILABLE`; execution/persist yok |
| Security audit | mevcut 5.0C `SecurityAuditPort`; `DurableSecurityAuditAdapter(audit_client, timeout_seconds=3.0)` | 3 s/event | pre-execution/decision failure use-case'i bloklar; post-commit failure warning |
| Observability | mevcut 5.0C `ObservabilityPort`; `ProductionObservabilityAdapter(telemetry_client, timeout_seconds=0.25)` | 250 ms | best-effort; business outcome değişmez |
| Clock | mevcut 5.0C `ApplicationClockPort`; `UtcApplicationClockAdapter()` | local | zorunlu; timezone-aware UTC, audit time system clock, business time caller/injected rule |
| Document input | `SqlAlchemyDocumentInputResolver(session_factory, content_store, timeout_seconds=3.0)` implements `DocumentInputResolverPort` | 3 s | 503 unavailable; 500 digest mismatch; fallback yok |
| Result input | `SqlAlchemyAnalysisResultInputResolver(session_factory, canonical_codec, timeout_seconds=3.0)` implements `AnalysisResultInputResolverPort` | 3 s | 503 unavailable; 500 digest mismatch; fallback yok |
| Scope claim | `SubjectBoundRunScopeClaimRepository(SessionLocal, context.subject_id)` | DB config | typed scope/subject conflict; method-owned transaction |
| Read facade | `ApiAnalysisReadFacade(reads, authorization, security_audit, observability, clock, error_classifier)` | DB config | typed 404/503/500 ayrımı |
| Admission | `ProcessLocalAnalysisAdmissionControl(global_limit, tenant_limit, subject_limit, retry_after)` | non-blocking acquire | saturation 429 |

Required external clients async retry/backoff yapmaz; tek bounded call yapar. Timeout hiçbir zaman deny, not-found veya empty audit receipt olarak yorumlanmaz.

Exact production construction imzaları şunlardır; `settings` yalnız process startup'ta doğrulanmış immutable config'tir:

```python
clock = UtcApplicationClockAdapter()
authn = ExternalTrustedAuthenticationContextProvider(
    context_source=external_auth_context_source,
    trusted_issuers=settings.trusted_issuers,
    clock=clock,
    timeout_seconds=2.0,
)
authorization = ProductionAuthorizationAdapter(
    policy_client=external_policy_client,
    timeout_seconds=2.0,
)
security_audit = DurableSecurityAuditAdapter(
    audit_client=external_durable_audit_client,
    timeout_seconds=3.0,
)
observability = ProductionObservabilityAdapter(
    telemetry_client=external_telemetry_client,
    timeout_seconds=0.25,
)
# Aşağısı request-scoped construction'dır:
authentication_context = authn.current_context()
scope_claims = SubjectBoundRunScopeClaimRepository(
    session_factory=SessionLocal,
    initiating_subject_id=authentication_context.subject_id,
)
document_inputs = SqlAlchemyDocumentInputResolver(
    session_factory=SessionLocal,
    content_store=authoritative_document_content_store,
    timeout_seconds=3.0,
)
result_inputs = SqlAlchemyAnalysisResultInputResolver(
    session_factory=SessionLocal,
    canonical_codec=storage_canonical_codec,
    timeout_seconds=3.0,
)
admission = ProcessLocalAnalysisAdmissionControl(
    global_limit=settings.global_max_active_analyses,
    tenant_limit=settings.tenant_max_active_analyses,
    subject_limit=settings.subject_max_active_analyses,
    retry_after_seconds=settings.admission_retry_after_seconds,
)
```

`external_auth_context_source`, `external_policy_client`, `external_durable_audit_client`, `external_telemetry_client` ve authoritative content store deployment tarafından explicit bind edilen trusted integration dependencies'dir; environment name'den dinamik fake seçimi yapılmaz. 5.0D bunların protocol adapter'larını sağlar, gerçek OAuth/OIDC/token issuance sistemini sağlamaz.

Composition root'un tek giriş/çıkış sözleşmesi:

```python
@dataclass(frozen=True)
class ProductionIntegrationBindings:
    authentication_context_provider: TrustedAuthenticationContextProviderPort
    authorization: AuthorizationPort
    security_audit: SecurityAuditPort
    observability: ObservabilityPort
    clock: ApplicationClockPort
    document_inputs: DocumentInputResolverPort
    result_inputs: AnalysisResultInputResolverPort
    admission: AnalysisAdmissionControlPort
    cursor_codec: CursorCodecPort

def build_analysis_api_dependencies(
    *,
    profile: ApiRuntimeProfile,
    bindings: ProductionIntegrationBindings,
    session_factory: Callable[[], Session],
    blob_store: BlobStorePort,
    settings: AnalysisApiSettings,
) -> AnalysisApiDependencies: ...
```

`build_analysis_api_dependencies` önce bütün binding'lerin concrete capability/profile marker'ını ve config'i doğrular; sonra router dependencies üretir. Eksik/forbidden binding'de partially wired router döndürmez. Required adapter health sözleşmesi `readiness_check(deadline: datetime) -> AdapterReadiness` olup yalnız bounded call yapar. `AdapterReadiness.ready=false` veya exception production readiness'i false yapar; public readiness response'u adapter adını/açıklamasını yayımlamaz. Observability'nin readiness sonucu business admission'ı kapatmaz, fakat binding'in kendisi yine zorunludur.

| Karar noktası | Timeout/outage | Retryable | Sonuç | Fail mode |
|---|---|---:|---|---|
| authentication context alma | 2 s timeout/unavailable | true | 503 | closed |
| context missing/malformed/expired/untrusted | uygulanmaz | false | 401 | closed |
| authorization pre-execution deny | bounded karar | false | 403; resolver/execution yok | closed |
| authorization provider pre-execution unavailable | 2 s | true | 503 | closed |
| resume source authorization deny/unavailable | aynı | false/true | 403/503; snapshot/payload materialize edilmez | closed |
| pre-persistence authorization revalidation deny/revoked | bounded karar | false | 403; terminal persistence ve payload response yok | closed |
| pre-persistence authorization provider unavailable | 2 s | true | 503; persistence yok | closed |
| pre-execution/decision security audit unavailable | 3 s | true | 503; use-case başlamaz/ilerlemez | closed |
| post-commit security audit unavailable | 3 s | true warning | success korunur + mandatory warning/alert | commit korunur |
| observability timeout/outage | 250 ms | n/a | business outcome değişmez | open yalnız telemetry için |
| source resolver unavailable | 3 s | true | 503; computation yok | closed |
| persistence conflict | DB timeout içinde | false | 409 | closed |
| persistence unavailable | DB timeout içinde | true | 503 | closed |
| execution failed | application terminal result | false | 500 | closed; raw exception yok |
| cancel local active | non-blocking | n/a | 200 `ACCEPTED`/`ALREADY_REQUESTED` | normal result |
| cancel local inactive/terminal/missing | non-blocking | n/a | 200 `NOT_ACTIVE`/`ALREADY_TERMINAL`/`NOT_FOUND` | normal result |

### 20.4 Startup/readiness validation

`validate_production_composition(profile, bindings)` aşağıdakilerin tamamını router serving öncesi doğrular:

- required adapter instance'ları var;
- adapter capability marker/profile `PRODUCTION` ile uyumlu;
- fake/test/allow-all/in-memory/no-op required adapter yok;
- authentication issuer allowlist ve context freshness policy yüklü;
- authorization provider bounded health probe başarılı;
- security-audit sink write/readiness probe başarılı;
- DB, blob/source resolver ve cursor active key hazır;
- admission limits pozitif ve finite;
- clock timezone-aware UTC üretir.

Readiness periyodik olarak required dependency availability'sini kontrol eder. Security audit unavailable veya authorization provider unavailable ise ready=false; mevcut in-flight transaction geri alınmaz. Observability outage ready durumunu ve business işlemini bloklamaz, fakat operational warning/metric best effort üretilir. Readiness public response'u dependency ayrıntısını açıklamaz.

Genel kurallar:

- router global mutable Session tutmaz;
- router/service dependency construction sırasında DB transaction başlatmaz;
- application service'i mocklamak zorunlu değildir; port fake'leriyle test edilir;
- production trusted authentication-context provider binding'i eksikse app startup fail-closed olur; permissive/no-op/raw-header auth fallback yoktur;
- fake authentication-context provider yalnız explicit development/test composition'ında bind edilebilir; production environment guard'ı fake binding'i reddeder;
- Observability binding'i production'da zorunludur fakat outage business outcome'u bloklamaz; no-op yalnız explicit TEST/DEVELOPMENT profile'ında kullanılabilir; required SecurityAudit hiçbir profile fallback'i değildir;
- local active registry process-scoped kalır, durable correctness kaynağı yapılmaz;
- dependency override yalnız test composition'ında açıkça kullanılır.

---

## 21. FastAPI Adapter Sınırı

FastAPI/Pydantic şu dosya bölgelerinin dışına çıkamaz:

- `app/api/**`;
- `app/schemas/**`;
- `app/integrations/analysis_http/**` içindeki HTTP adapter/composition dosyaları.

Yasaklar:

- application core'da `Request`, `Response`, `HTTPException`, `Depends`, Pydantic model;
- router'dan ORM/repository/engine importu;
- `ApplicationOutcome` error'unu raw `HTTPException.detail` olarak döndürme;
- Pydantic `from_attributes` ile ORM/application dataclass'ı implicit dışarı açma;
- arbitrary JSON serializer fallback (`default=str`);
- response serialization hatasında terminal transaction rollback denemesi;
- sync engine'i async event loop içinde doğrudan çalıştırma.

FastAPI validation'ın varsayılan 422 payload'ı standard API envelope'u bypass etmeyecektir. Request validation exception handler, güvenli ve versioned `ApiOutcomeResponseV1` üretir.

---

## 22. Framework Bağımsızlığı

5.0D, application core'a framework sızdırmama yönünde bir anti-corruption layer'dır. Statik/transitive import testleri şunları doğrular:

- `app/analysis_application/**` core dosyaları FastAPI, Starlette, Pydantic, SQLAlchemy, Alembic ve `app.api` import etmez;
- `app/engines/analysis_orchestrator/**` API/persistence import etmez;
- `app/orchestration_persistence/**` HTTP schema/request import etmez;
- HTTP schemas engine dataclass veya ORM model import etmez;
- mapping yalnız public 5.0C contracts ve HTTP DTO'larını bilir.

FastAPI başka bir framework ile değiştirildiğinde 5.0A–5.0C kodu değişmemelidir.

---

## 23. Test Stratejisi

### 23.1 Wire contract ve codec unit testleri

- tüm request/response modellerinin exact field/type/required/optional contract testleri;
- closed enum ve unknown-field rejection;
- Decimal/tagged date/datetime/tuple/map golden vectors;
- non-finite float/Decimal ve non-string key rejection;
- API/application/storage schema version ayrımı;
- financial vs artifact payload reference projection;
- financial owner serializer version null;
- response serialization failure safe envelope.

### 23.2 Router contract testleri

- sekiz endpoint'in path/method/operation ID/status modeli;
- Start new 201, idempotent replay 200;
- Resume/Retry new target ID ve path source ID mapping;
- Cancel beş normal status'un tamamında success/200;
- query include-payload default false;
- malformed JSON, missing source/header, forbidden raw byte/payload field, unsupported media ve oversized body/resolved content;
- default FastAPI validation payload'ının standard envelope'a normalize edilmesi;
- no raw exception/message/stack/token/payload leakage;
- existing `/api/v1/analyses/{analysis_id}` ve legacy route regression.

### 23.3 Authentication/authorization/security testleri

- missing authentication context 401;
- malformed authentication context 401;
- untrusted issuer 401;
- expired context 401;
- `issued_at` 60 saniyeden fazla future skew ve 15 dakikadan eski context 401;
- context/header correlation mismatch 401;
- trusted context provider outage 503, fail-closed;
- tenant yalnız principal'dan;
- tenant mismatch ve subject mismatch fail-closed;
- body/header tenant spoofing alanı bulunmaması;
- production'da raw `X-User-Id`/`X-Tenant-Id` identity header'larının reddi;
- development/test fake adapter ile production trusted adapter composition ayrımı;
- production environment'ta fake adapter seçiminin startup failure üretmesi;
- authentication success + authorization deny sonucu;
- authorization deny/revoke/provider unavailable mapping;
- resume source payload authorization ordering;
- wrong company/period/tenant resource existence gizleme;
- required audit failure 503;
- post-commit audit failure success + warning;
- logs/metrics/audit capture'ında hassas veri yokluğu;
- production default'unda docs/OpenAPI kapalı; explicit enable halinde trusted authentication + docs authorization zorunlu;
- live/ready ayrımı ve readiness response'unda dependency ayrıntısı bulunmaması.

### 23.4 Idempotency ve mapping testleri

- same key/correlation/generated_at/principal/body/resolved source digest → replay;
- same key + different correlation/generated_at/body/source ID/resolved digest/trusted filename metadata → conflict;
- same key + different company/period/tenant/principal → fail-closed;
- same subject exact replay 200; farklı subject aynı tenant replay 409 `RUN_SUBJECT_MISMATCH`;
- authorized same-tenant cross-subject read 200; denied cross-subject read 403;
- cross-tenant read 404 ve cross-tenant write 409;
- legacy unbound write replay 409;
- same-process/cross-process semantic equality;
- HTTP DTO → exact Start/Resume/Retry/Cancel dataclass equality;
- `EngineResultEnvelope.result` dışında eski `result_ref` adı bulunmaması;
- owner/table/FK/audit time caller'dan taşınmaması.

### 23.5 Query/pagination testleri

- scope-qualified status/result/execution/history;
- default metadata-only ve authorized payload read;
- first/second/last page stable cursor;
- same finalized timestamp tie-break;
- cursor tamper, wrong tenant/company/period/key/version;
- exact signed-bytes golden vector, signature-field exclusion ve constant-time verifier kullanım guard'ı;
- HMAC key rotation: active encode, retired verify-only grace, disabled/unknown rejection;
- cursor expiry, excessive future skew, malformed/duplicate/unknown field;
- limit 1, 200, 0, 201;
- concurrent insert sırasında keyset stability.

### 23.6 Dependency/import/OpenAPI testleri

- exact DI fake implementations;
- missing required production dependency startup failure;
- application/orchestrator transitive forbidden-import guards;
- router no ORM/repository/engine import guard;
- OpenAPI golden snapshot ve duplicate operation ID yokluğu;
- OpenAPI/runtime stringlerinde yeni hard-coded code-name/brand yokluğu.

### 23.7 PostgreSQL integration ve concurrency testleri

- gerçek endpoint → 5.0C → PostgreSQL terminal run uçtan uca;
- start/resume/retry/cancel/query authorization ve scope bağları;
- cross-tenant same-key yarışında yalnız tek scope claim/canonical run;
- concurrent same-scope replay ve staged owner/lineage loser discard;
- BS/IS/Ratio owner lineage HTTP input mapping;
- post-persistence DTO/HTTP serialization failure recovery read'i;
- cursor ikinci sayfa;
- connection/session cleanup ve failed request sonrası transaction reuse;
- 5.0B immutable trigger ve migration-cycle regression'larının değişmeden geçmesi.

### 23.8 Input provenance ve resolver testleri

- document ID ile birlikte raw/different bytes alanı schema seviyesinde reddedilir;
- trusted document bytes ile persisted checksum mismatch'inde Orchestrator çağrılmaz;
- trial-balance result ID ile birlikte caller payload alanı reddedilir;
- stored trial-balance canonical digest corruption fail-closed 500;
- fake/nonexistent provenance source 404; hiçbir synthetic lineage kurulmaz;
- wrong company/period document ve result source fail-closed;
- source status/type mismatch 422;
- resolver unavailable 503; caller payload fallback'i yok;
- resolver'ın ürettiği input ID/digest ile `FinancialSourceIntentDTO` source role/ID exact eşitliği;
- `PERSISTED_SOURCE_ID_PRESENT` invariant'ının tüm BS/IS/trial-balance mapping yollarında property testi.

### 23.9 Production composition ve readiness testleri

- missing `AuthorizationPort` veya `SecurityAuditPort` production startup/readiness failure;
- missing trusted authentication-context provider production startup/readiness failure;
- production profile'da fake authentication, allow-all authorization, in-memory/no-op audit kesin rejection;
- audit sink unavailable ve authorization provider unavailable durumunda readiness=false;
- pre-execution required audit outage write use-case'i başlatmaz;
- observability outage business işlemini bloklamaz fakat adapter binding'i yoksa production validation geçmez;
- clock/resolver/cursor/admission binding veya invalid config readiness=false;
- TEST fake'lerinin PRODUCTION graph'ına transitively giremediği import/capability testleri.

### 23.10 Subject claim ve transaction topolojisi testleri

- gerçek `session_factory` ile subject-bound repository construction;
- claim/verify/finalize'ın üç ayrı kısa transaction açtığı, request Session kullanmadığı;
- 5.0B terminal persistence'ın ayrı request-scoped transaction/SAVEPOINT kullandığı;
- read adapter transaction'ının request sonunda rollback/close edildiği;
- `run_id` uniqueness altında cross-tenant/cross-company/cross-period/cross-subject race'te tek immutable claim;
- wrong tenant/subject verify/finalize zero-row fail-closed;
- DTO projection öncesi wrong tenant/subject yeniden doğrulamasında hiçbir DTO üretilmemesi;
- additive migration upgrade → downgrade → upgrade, legacy-null ve new-row non-null invariant'ları.
- PostgreSQL insert trigger'ının migration öncesi legacy-null satırları korurken yeni null `initiating_subject_id` insert'ini reddetmesi;
- immutability trigger'ının `initiating_subject_id` UPDATE/DELETE girişimini gerçekten reddetmesi.

### 23.11 Query error classification testleri

- authoritative true not-found 404;
- DB connection outage/timeout 503;
- digest/integrity/invariant failure 500;
- hidden unauthorized wrong-scope read 404, same-tenant authorization deny 403;
- malformed cursor/input 422;
- unknown/raw exception'ın safe fixed message'e normalize edilmesi; repr/stack/SQL sızıntısı olmaması;
- history authorization'ın `HISTORY_READ` kullanması ve START yetkisiyle karışmaması.

### 23.12 Admission ve timeout testleri

- global ve tenant saturation; opsiyonel subject saturation;
- saturation exact 429 + configured `Retry-After` ve `retryable=true`;
- success, replay, validation/resolver error, authorization revoke, execution exception, cancellation, projection/serialization failure ve disconnect sonrası lease exact-once release;
- same-process concurrent request'lerde finite budget; cross-process toplam garanti iddia edilmemesi;
- yeni executor/thread üretme yasağı ve bounded shared threadpool kapasite testi;
- deadline cooperative cancellation; proxy timeout sonrası backend'in sürebileceği contract testi.

### 23.13 Post-commit recovery testleri

- terminal commit success + DTO projection/JSON serialization failure sonucu 500 safe recovery envelope;
- envelope exact `run_id`, `correlation_id`, `persisted=true`, recovery endpoint/reference alanları dışında payload/digest/raw error taşımaması;
- aynı command retry'ının persisted result'ı okuması ve engine'i yeniden çalıştırmaması;
- post-commit audit failure'ın success + mandatory warning üretmesi ve scope/subject claim'i etkilememesi.

Testler production kodunda test-only bypass oluşturamaz.

---

## 24. Docker Kabul Kriterleri

İmplementasyon başlamadan önce zorunlu baseline:

```bash
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python -m pytest tests/ -q'
```

Baseline en az doğrulanmış `1042 passed, 0 failed, 0 skipped` davranışını korumalıdır; dependency warning'leri ayrı raporlanır. Baseline fail ise implementasyon başlamaz.

Milestone kabulü için:

1. Her test-gated alt adım 0 failed.
2. Tam Docker suite 0 failed.
3. Gerçek PostgreSQL integration suite 0 failed.
4. Cross-tenant/idempotency/concurrent loser race suite 0 failed.
5. OpenAPI golden ve forbidden-import/brand scans 0 failed.
6. Mevcut 5.0A, 5.0B ve 5.0C regression testleri değişmeden geçer.
7. Mevcut legacy API/bulk-upload/trial-balance regression testleri geçer.
8. `git diff --check` temiz.
9. `git status --short` yalnız onaylı 5.0D dosyalarını gösterir.
10. Additive `initiating_subject_id` ve `canonical_result_digest` migration'ları upgrade → downgrade → upgrade, backfill, constraint/index ve PostgreSQL concurrency testlerinden geçer; final Alembic head implementasyon sırasında gerçek migration kimliğiyle raporlanır.
    - scope-claim trigger yeni INSERT'te null subject'i reddeder, legacy null satırı korur ve subject UPDATE/DELETE'ini reddeder;
    - terminal non-null financial payload için canonical digest DB seviyesinde zorunlu ve 64 lowercase hex'tir; terminal digest mutation gerçek UPDATE ile reddedilir;
    - repository, yeni financial owner digest'ini mevcut `EngineResultEnvelope.result` üzerinden storage codec ile hesaplar; 5.0B public command imzası değişmez.
11. API/router dışında engine/application/persistence public contract diff'i yoktur.
12. Commit/push ayrıca kullanıcı onayı olmadan yapılmaz.

---

## 25. Riskler

| Risk | Etki | Mitigation | Blocking |
|---|---|---|---|
| Forged/untrusted AuthenticationContext injection | tenant spoofing / unauthorized access | yalnız trusted composition binding, issuer/expiry/correlation validation, production fake/raw-header yasağı | hayır |
| Senkron uzun CPU request | timeout, threadpool saturation | bounded ingress/server timeout, concurrency cap, load test; background'a dönüş yok | hayır |
| Trusted source materialization memory baskısı | process memory exhaustion | resolver başına 10 MiB hard limit, admission-before-resolution, no logging | hayır |
| Idempotent retry'da değişen timestamp/correlation/principal | conflict | required stable headers/body ve contract tests | hayır |
| Metadata preflight existence leak | cross-tenant enumeration | generic not-found/unauthorized policy, payload-before-auth yasağı | hayır |
| Cursor tampering/replay | scope bypass/query instability | scope-bound HMAC cursor, key rotation | hayır |
| Response projection/serialization failure after commit | client belirsizliği | canonical run korunur, safe recovery hint, later GET | hayır |
| Legacy API'nin offset/error-envelope farklılığı | API tutarsızlığı | yalnız yeni router standardı; legacy refactor kapsam dışı | hayır |
| Legacy runtime code-name metni | brand policy debt | yeni 5.0D yüzeyinde sıfır kullanım; ayrı onaylı remediation | hayır |
| External blob payload read latency | synchronous response latency | include payload default false, timeout/metrics | hayır |
| Resolver/source provenance misbinding | forged financial lineage | exact scope/type/status + checksum/digest, same resolved-object mapping, no raw fallback | hayır |
| Production adapter eksik/permissive binding | authorization/audit bypass | closed runtime profile, capability validation, readiness=false | hayır |
| Subject replay takeover | same-tenant cross-user result disclosure | immutable initiating subject, unique run ID, deterministic 409/403/404 | hayır |
| Process-local admission'ın multi-worker sınırı | deployment toplam concurrency'si worker sayısıyla büyür | finite per-process limits, documented capacity, distributed control future milestone | hayır |

---

## 26. Reddedilen Alternatifler

1. **Router'ın doğrudan Orchestrator çağırması:** 5.0C authorization/audit/scope/idempotency bypass; reddedildi.
2. **Router'ın repository/ORM kullanması:** transaction ve ownership duplication; reddedildi.
3. **Engine/application dataclass'larını FastAPI response_model yapmak:** framework leakage ve accidental field exposure; reddedildi.
4. **Yeni `/api/v1/analyses` run semantiği:** mevcut financial owner endpoint'iyle çakışma; reddedildi.
5. **Raw bytes için base64 JSON veya multipart:** caller byte'ı ile persisted provenance ID'si arasında sahte bağ kurulmasına izin verir; v1 yalnız trusted persisted source ID kabul eder.
6. **Resolver olmadan document ID'yi provenance saymak:** hesaplama girdisini authoritative source'a bağlamaz; reddedildi.
7. **Tenant/actor/auth reference'ı request body'den almak:** spoofing; reddedildi.
8. **Server'ın write retry'da yeni generated_at/correlation üretmesi:** 5.0C command digest conflict; reddedildi.
9. **API-level idempotency tablosu/cache'i:** duplicate source of truth; reddedildi.
10. **Same-process duplicate'i 409 reddetmek:** cross-process semantiğini bozar; reddedildi.
11. **Disconnect'i durable cancel saymak:** local/non-durable ActiveExecution sınırını ihlal eder; reddedildi.
12. **Resume/Retry corruption'da Start fallback:** fail-closed sözleşmeye aykırı; reddedildi.
13. **Offset history pagination:** concurrent insert altında stabil değil; keyset cursor seçildi.
14. **Unsigned/raw internal cursor:** scope tampering ve internal ID exposure; HMAC envelope seçildi.
15. **Security audit'i observability/log ile ikame etmek:** required audit semantiğini bozar; reddedildi.
16. **202 + background worker:** milestone kapsamı dışında; reddedildi.
17. **Event sourcing:** Architecture Book tarafından yasak; reddedildi.
18. **HTTP status'u application core'a eklemek:** 5.0C public contract/framework independence ihlali; reddedildi.
19. **Automatic retry/backoff:** explicit Retry use-case ve idempotency sınırına aykırı; reddedildi.
20. **Mevcut tüm API'yi aynı anda yeni envelope/pagination'a taşımak:** kapsam dışı breaking refactor; reddedildi.

---

## 27. Açık Kararlar

### 27.1 Blocking açık kararlar

**Yoktur.** D1, Section 12'deki bağlayıcı trusted `AuthenticationContext` boundary kararıyla kapatılmıştır. 5.0D gerçek authentication sistemi veya provider entegrasyonu kurmayacak; yalnız dış trusted composition root'un doğruladığı immutable context'i tüketecektir.

### 27.2 Kilitlenmiş kararlar

- route family `/api/v1/analysis-runs`;
- senkron terminal HTTP modeli;
- yalnız trusted persisted source ID input'u; ad-hoc/raw upload yok;
- run ID için `Idempotency-Key`;
- stable write correlation/generated-at/principal mapping;
- tenant/actor/auth reference server-derived;
- immutable, framework-independent trusted `AuthenticationContext` boundary;
- production'da raw identity header ve fake adapter yasağı;
- authentication ile 5.0C authorization'ın kesin ayrımı;
- strict versioned Pydantic wire DTO'ları;
- `ApplicationOutcome` exhaustive HTTP mapping;
- HMAC scope-bound keyset cursor;
- initiating-subject-bound durable run reservation ve deterministik 401/403/404/409 tablosu;
- typed `ApiAnalysisReadFacade` ile 404/503/500 ayrımı;
- finite process-local admission ve saturation için 429 + `Retry-After`;
- cancel sonuçlarının HTTP 200 normal business sonucu olması;
- yalnız iki additive integrity/ownership alanı; 5.0A/5.0B/5.0C public contract değişikliği yok;
- no queue/worker/scheduler/UI/event sourcing.

### 27.3 Future Hardening — 5.0D kapsamında kodlanmayacak

- durable background execution/job API;
- distributed cancellation/single-flight;
- gateway-level rate limiting/quota management;
- gerçek token doğrulama, OAuth/OIDC, SSO, MFA ve provider-specific admin/provisioning;
- cursor key management service/HSM integration;
- raw document content object store;
- websocket/SSE progress stream;
- legacy API envelope/pagination standardization;
- legacy runtime code-name remediation;
- load/chaos automation ve multi-region routing.

**Açık karar sayısı:** 0 blocking, 0 non-blocking.

---

## 28. Architecture Book v1.4.0 Güncelleme Planı

Milestone 5.0D implementasyonu 0 failed ile doğrulanıp ayrıca kapatıldıktan sonra, ayrı kullanıcı onayıyla Architecture Book v1.4.0 senkronizasyonu yapılacaktır. Güncelleme en az şunları içerir:

1. Kapsanan sistem durumu Milestone 5.0D ve gerçek final Docker sonucu.
2. HTTP/API Integration Layer'ın 5.0C application boundary üzerindeki yeri.
3. `/api/v1/analysis-runs` route family ve exact endpoint envanteri.
4. Versioned wire DTO, application DTO ve storage codec ayrımı.
5. Authentication HTTP boundary / authorization application boundary ayrımı.
6. Scope-aware HTTP idempotency ve stable retry headers/body politikası.
7. Trusted source-ID resolution, checksum/digest, file allowlist, size limit ve sensitive-data kuralları.
8. Exhaustive error envelope/HTTP mapping.
9. HMAC scope-bound keyset pagination.
10. FastAPI/Pydantic'in application core dışında kalması.
11. Synchronous-only, no queue/worker/scheduler/UI/event sourcing sınırı.
12. Brand-independent endpoint/OpenAPI/schema politikası.
13. Additive subject/digest migration'larının gerçek final Alembic head'i; yalnız implementasyon bunu doğrularsa.

Architecture Book implementasyondan önce “gelecek davranış” yazmak için değiştirilmez.

---

## 29. Kullanıcı Onay Kapısı

Bu dokümanın oluşturulması implementasyon yetkisi değildir.

İmplementasyona geçilebilmesi için sırasıyla:

1. Bağımsız mimari/security/API denetimi blocking bulgu bırakmamalıdır.
2. Kullanıcı tasarımı açıkça FINAL olarak onaylamalıdır.
3. Kullanıcı ayrıca Milestone 5.0D implementasyonuna geçiş için açık talimat vermelidir.
4. Zorunlu Docker baseline 0 failed olmalıdır.

Bu kapılar kapanmadan kod, test, migration, model, repository, API/router implementasyonu, commit veya push yapılmaz. Yol haritasındaki sonraki milestone'a geçilmez.

---

## Tasarım Kapanış Durumu

- Blocking açık karar: **0**.
- Design Readiness: **%100**.
- Runtime Readiness: **%0**.
- Implementasyona hazır: **Tasarım açısından evet; implementasyon henüz yetkilendirilmemiştir ve bağımsız denetim ile açık kullanıcı onayı zorunludur.**
- 5.0A/5.0B/5.0C public contract değişikliği: **Yok**.
- Engine değişikliği: **Yok**.
- Event sourcing: **Yok ve yasak**.

---

## D1 Kapanış Raporu

| Konu | Bağlayıcı kapanış kararı |
|---|---|
| Authentication sahipliği | 5.0D gerçek authentication sistemi kurmaz; router/application core context üretmez |
| Trust source | Yalnız dış trusted authentication adapter/composition root |
| Contract | Immutable, framework-independent `AuthenticationContext`; subject, tenant, method, strength, issued/expiry, correlation, claims version, trusted issuer ve stable authorization reference |
| Production güvenliği | Raw identity header, anonymous fallback, fake/no-op adapter yasak; missing/malformed/untrusted/expired context fail-closed |
| Development/test | Explicit environment-guarded deterministic fake provider; production composition'dan ayrıdır |
| Authorization ayrımı | Authentication identity doğrular; erişim kararı değişmemiş 5.0C `AuthorizationPort`'ta kalır |
| Future security | Token validation, OAuth/OIDC, SSO, MFA ve gerçek provider entegrasyonu sonraki security milestone'una bırakıldı |
| Test kapsamı | Missing/malformed/untrusted/expired, tenant/subject mismatch, raw-header rejection, fake/production separation ve auth-success/authz-deny senaryoları zorunlu |
| D1 durumu | **KAPALI** |
| Kalan blocking karar | **0** |

---

## Bağımsız Final Mimari Denetim Sonrası Revizyon Raporu

| Bulgu | Kök neden | Uygulanan düzeltme | Eklenen sözleşme | Eklenen test kategorisi | Durum |
|---|---|---|---|---|---|
| C1 | Caller computation input'u ile persisted provenance ID arasında cryptographic/authoritative bağ yoktu | Raw/ad-hoc input v1'den çıkarıldı; document ve trial-balance yalnız trusted resolver'dan scope/type/status/checksum/digest doğrulamasıyla materialize edilir | `DocumentInputResolverPort`, `AnalysisResultInputResolverPort`, `PERSISTED_SOURCE_ID_PRESENT` invariant'ı, `canonical_result_digest` | provenance mismatch/corruption/fake source/wrong scope/status/type ve property testleri | **KAPALI** |
| C2 | Production authn/authz/audit/observability/clock binding ve outage topolojisi executable değildi | Closed runtime profiles, exact constructors, startup capability validation, bounded timeout ve readiness politikası kilitlendi | `ApiRuntimeProfile`, production composition graph ve decision table | missing/fake/permissive adapter, outage ve readiness testleri | **KAPALI** |
| H1 | Run replay/read policy initiating subject'i durable ownership'e bağlamıyordu | Subject mevcut immutable scope reservation'a atomik eklendi; unique/CAS ve deterministik 401/403/404/409 politikası tanımlandı | `initiating_subject_id`, `SubjectBoundRunScopeClaimRepository`, `ApiRunOwnershipInspectorPort` | same/different subject replay, authorized/denied cross-subject read, cross-tenant race | **KAPALI** |
| H2 | DI grafiği request Session ile short-transaction repository sınırını karıştırıyordu | Request lifecycle, use-case lifecycle, claim short transactions, terminal persistence transaction ve read transaction ayrıldı | Real `session_factory` constructor/wiring ve transaction ownership graph | gerçek wiring, ayrı transaction, wrong-subject verify/finalize, migration cycle | **KAPALI** |
| H3 | 5.0C query service kayıp hata kategorilerinden HTTP 503/500 üretilemezdi | Router/repository bypass etmeden typed infrastructure kategorisini koruyan integration facade seçildi | `ApiAnalysisReadFacade`, `ApiReadErrorClassifier`, `ApiReadAction.HISTORY_READ` | true not-found, DB outage, integrity, hidden deny ve raw-error redaction | **KAPALI** |
| H4 | Sync execution için finite admission ve overload cevabı yoktu | Process-local global/tenant/optional-subject lease, exact 429/Retry-After ve finally-release politikası tanımlandı | `AnalysisAdmissionControlPort`, finite defaults, deployment deadline contract | saturation, release-all-paths, bounded threadpool ve timeout risk testleri | **KAPALI** |

**Revizyon sonucu:** 2 kritik ve 4 yüksek blocking bulgu kök nedenleriyle kapanmıştır. Kalan blocking karar **0**, Design Readiness **%100**, Runtime Readiness **%0**'dır. Tasarım implementasyona hazırdır; implementasyon için kullanıcı onay kapısı ve yeşil Docker baseline zorunludur.
