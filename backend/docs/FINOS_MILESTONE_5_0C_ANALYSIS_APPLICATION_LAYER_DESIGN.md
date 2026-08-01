# FINOS Milestone 5.0C — Analysis Application Layer Tasarımı

| | |
|---|---|
| Doküman durumu | REVİZE TASARIM — İmplementasyon onayı bekliyor |
| Doküman versiyonu | 3.0.0 |
| Hedef milestone | 5.0C — Analysis Application Layer |
| Mimari referans | FINOS Architecture Book v1.2.0 |
| Değişmez upstream sözleşmeler | Milestone 5.0A Analysis Orchestrator + Milestone 5.0B Orchestration Persistence & Recovery |
| Son doğrulanmış baseline | Docker: 998 passed, 0 failed, 0 skipped; Alembic head: `4f9d2a6b8c10` |
| Kapsam | Framework-bağımsız, senkron command/query use-case katmanı ve application DTO/port sözleşmeleri |
| Kesin kapsam dışı | API/router, Pydantic şeması, queue, worker, background execution, scheduler, batch runner, CLI, UI, event sourcing |

> **Kod adı politikası:** “FINOS” yalnız dahili geliştirme kod adıdır. Application sembolleri, DTO alanları, error code'ları ve port adları brand-independent olmak zorundadır.

---

## 0. Karar Özeti ve Normatif Dil

Bu dokümanda **ZORUNLU/YASAK** bağlayıcı, **ÖNERİLEN** güçlü varsayılan, **OPSİYONEL** ise sözleşmeyi bozmayan seçenektir.

Kilit kararlar:

1. 5.0C yalnız senkron, in-process use-case koordinasyonu sağlar; finansal hesaplama veya engine sonucu üretmez.
2. 5.0A ve 5.0B public contract'ları değiştirilmez.
3. Public command'lar persistence owner assembly taşımaz; yalnız `FinancialSourceIntentDTO` taşır. Financial owner binding gerçek engine sonucu görüldükten sonra application adapter tarafından oluşturulur.
4. Zorunlu entegrasyon yolu phased coordination'dır. Mevcut one-shot `execute_and_persist(...)`, 5.0C gateway'inin zorunlu veya varsayılan yolu değildir.
5. 5.0B request fingerprint ve terminal idempotency'nin authoritative sahibidir. 5.0C buna ek olarak tam application scope'unu preflight ve post-persist aşamalarında fail-closed doğrular.
6. Process-local active registry correctness/idempotency kaynağı değildir; yalnız cancellation, diagnostics ve local observability içindir.
7. Bütün beklenen business/dependency hataları immutable `ApplicationOutcome[T]` ile döner; exception yalnız programmer error veya yakalanmış internal invariant breach için iç sınırda kullanılır.
8. Security audit zorunlu ve observability'den ayrıdır. Required pre-execution audit başarısızsa use-case başlamaz.
9. Event sourcing, replay ve application-owned duplicate result storage yoktur.
10. Tasarım revizyonu B1–B6'yı kapatır; runtime readiness implementasyon ve test bulunmadığı için `%0`'dır.

---

## 1. Application Layer Amacı ve Sorumluluk Sınırı

Application Layer dış caller türlerinden bağımsız command/query girişleri sağlar; scope, authorization, audit, orchestration ve terminal persistence sırasını koordine eder; canonical kayıtları versioned DTO'lara projekte eder.

Katman:

- command ve query doğrulaması yapar;
- caller/tenant/company/period scope'unu bağlar;
- authorization'ı pre-execution ve pre-persistence noktalarında fail-closed uygular;
- değişmemiş 5.0A `run_orchestration()` çağrısını yapar;
- gerçek `engine_records` sonrasında financial owner binding üretir;
- değişmemiş 5.0B portları üzerinden terminal sonucu atomik persist eder;
- scope/idempotency dönüşünü yeniden doğrular;
- canonical storage owner'dan public DTO projection üretir.

Katman finansal değer hesaplamaz, engine reuse kararı kopyalamaz, ORM nesnesi açmaz, HTTP bilmez, transaction'ı engine süresi boyunca açık tutmaz ve background lifecycle sağlamaz.

---

## 2. 5.0A ve 5.0B ile Değişmez Sözleşmeler

### 2.1 Milestone 5.0A contract freeze

`EngineCode`, execution/run status'ları, `EngineRawInputs`, `OrchestrationRunOptions`, `OrchestrationRunRequest`, `OrchestrationRunResult`, `PreviousExecutionSnapshot`, structured error/telemetry tipleri, fingerprint/reuse kuralları ve:

```python
run_orchestration(
    request: OrchestrationRunRequest,
    *,
    cancellation_probe: Callable[[], bool] | None = None,
    timing_probe: TimingProbe | None = None,
) -> tuple[OrchestrationRunResult, ExecutionTelemetry | None]
```

aynen korunur. `engine_records` tek engine-result source of truth olmaya devam eder.

### 2.2 Milestone 5.0B contract freeze

`PersistenceRunScope`, `PersistTerminalRunCommand`, `FinancialResultOwnerBinding`, `ResumePersistenceContext`, `SnapshotLoadResult`, `PersistedRun`, history tipleri ve `RunStorePort`/`SnapshotReaderPort`/artifact/blob portları değiştirilmez. Unique `run_id`, canonical digest, single payload owner, immutable audit history, resume binding, 256 KiB inline ve 1 MiB run bütçesi ile staging → READY politikaları korunur.

5.0C, 5.0B tablo/model/constraint veya public contract'larını değiştirmez. B2 gereği ayrı bir 5.0C-owned durable `RunScopeClaim` store'u additive olarak eklenmek zorundadır; bu yeni owner 5.0B canonical payload/run tablolarının parçası değildir. Application core yalnız `RunScopeClaimPort` bilir; PostgreSQL model/repository/migration yalnız edge adapter katmanında yer alır. `RunPersistencePort` Bölüm 17'deki application anti-corruption port'udur ve var olan 5.0B tiplerine map eder.

### 2.3 Değişmez bağımlılık yönü

```text
future adapter
     |
     v
5.0C contracts/use cases
  | execution       | read
  v                 v
5.0A public API   5.0B canonical storage
  | result           ^
  +--- 5.0C binding -+
```

5.0A/5.0B, 5.0C'yi import etmez. Application core; FastAPI, Pydantic, SQLAlchemy veya ORM entity import etmez.

---

## 3. Application Service / Use Case Mimarisi

Command use-case'leri:

- `StartAnalysisUseCase.handle(StartAnalysisCommand)`
- `ResumeAnalysisUseCase.handle(ResumeAnalysisCommand)`
- `CancelAnalysisUseCase.handle(CancelAnalysisCommand)`
- `RetryAnalysisUseCase.handle(RetryAnalysisCommand)`

Query use-case'leri:

- `GetAnalysisStatusUseCase.handle(GetAnalysisStatusQuery)`
- `GetAnalysisResultUseCase.handle(GetAnalysisResultQuery)`
- `ListAnalysisHistoryUseCase.handle(ListAnalysisHistoryQuery)`
- `GetExecutionDetailUseCase.handle(GetExecutionDetailQuery)`

Her use-case tek public `handle` girişine, constructor injection'a ve kapalı outcome tipine sahiptir. Mapper, validator ve projection fonksiyonları pure application fonksiyonlarıdır. Composition root bu milestone kapsamında değildir.

---

## 4. Command Sözleşmeleri

### 4.1 Ortak supporting DTO'lar

```python
@dataclass(frozen=True)
class AnalysisInputsDTO:
    balance_sheet_content: bytes | None
    balance_sheet_filename: str | None
    income_statement_content: bytes | None
    income_statement_filename: str | None
    trial_balance_result: dict[str, ApplicationJsonValue] | None
    period_start_date: date | None
    period_end_date: date | None
    period_months_covered: int | None

@dataclass(frozen=True)
class AnalysisRunOptionsDTO:
    industry_code: str | None
    company_size_bucket: str | None
    engine_segmentation_tenant_id: str | None
    reporting_period_label_tr: str | None
    optional_report_sections: tuple[str, ...] | None
    currency_display_policy: str | None
    locale: str

@dataclass(frozen=True)
class PriorPeriodFactsDTO:
    schema_version: str
    statement_kind: FinancialStatementKind
    values: dict[str, Decimal | None]

@dataclass(frozen=True)
class PriorPeriodProjectionDTO:
    balance_sheet_facts: PriorPeriodFactsDTO | None
    income_statement_facts: PriorPeriodFactsDTO | None
    balance_sheet_result: dict[str, ApplicationJsonValue] | None
    income_statement_result: dict[str, ApplicationJsonValue] | None

@dataclass(frozen=True)
class CompanyMetadataDTO:
    schema_version: str
    company_name: str
    industry_label_tr: str | None
    company_size_label_tr: str | None
    fiscal_year_label_tr: str | None
    tax_id_masked: str | None

@dataclass(frozen=True)
class ReportRequestDTO:
    schema_version: str
    report_type: ApplicationReportType
    optional_section_codes: tuple[ApplicationReportSectionCode, ...] | None
    reporting_period_label_tr: str | None

@dataclass(frozen=True)
class DashboardRequestDTO:
    schema_version: str
    dashboard_type: ApplicationDashboardType

@dataclass(frozen=True)
class RenderContractRequestDTO:
    schema_version: str
    render_medium: ApplicationRenderMedium
    supported_block_types: tuple[ApplicationReportBlockType, ...]
    supports_landscape: bool
    supports_page_break_hints: bool
    supports_chart_placeholders: bool
    max_table_columns_before_overflow_risk: int | None
```

`PriorPeriodFactsDTO.values` kapalıdır. Balance-sheet anahtarları yalnız `current_assets`, `non_current_assets`, `total_assets`, `short_term_liabilities`, `long_term_liabilities`, `equity`, `total_liabilities_and_equity`, `cash_and_equivalents`, `inventory`, `trade_receivables`, `trade_payables`; income-statement anahtarları yalnız `gross_sales`, `sales_deductions`, `net_sales`, `cost_of_sales`, `gross_profit`, `operating_expenses`, `other_operating_income`, `other_operating_expenses`, `operating_profit`, `depreciation_and_amortization`, `ebit`, `ebitda`, `financing_expenses`, `extraordinary_income`, `extraordinary_expenses`, `profit_before_tax`, `net_profit` olabilir. Eksik fact `None` ile temsil edilir; bilinmeyen key reddedilir.

### 4.2 `StartAnalysisCommand`

```python
@dataclass(frozen=True)
class StartAnalysisCommand:
    run_id: str                                      # zorunlu, boş değil
    correlation_id: str                             # zorunlu, boş değil
    generated_at: datetime                          # zorunlu, timezone-aware
    scope: ApplicationScopeDTO                      # zorunlu; START invariant'ı
    audit_context: ApplicationAuditContextDTO       # zorunlu
    authorization_context_reference: str            # zorunlu opaque ref
    requested_outputs: tuple[ApplicationEngineCode, ...]  # zorunlu, boş değil
    inputs: AnalysisInputsDTO                       # zorunlu
    run_options: AnalysisRunOptionsDTO              # zorunlu
    source_intents: tuple[FinancialSourceIntentDTO, ...]  # zorunlu; boş olabilir
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str               # zorunlu
```

`scope.operation_kind == START`, `scope.original_operation == START`, `scope.previous_run_id is None` zorunludur. Financial engine istenmişse ona ait tek source intent zorunludur. Aynı engine için birden çok intent veya unrelated intent reddedilir.

### 4.3 `ResumeAnalysisCommand`

```python
@dataclass(frozen=True)
class ResumeAnalysisCommand:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCode, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTO, ...]
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str
```

Şu invariant'lar bağlayıcıdır:

- `run_id` yeni target run ID'dir ve `scope.previous_run_id`'den farklıdır;
- `scope.previous_run_id` zorunludur;
- `scope.operation_kind == RESUME` ve `scope.original_operation == RESUME`;
- source ve target için company, financial period ve tenant birebir eşittir;
- source authorization, snapshot metadata ve payload materialization'dan önce alınır;
- invalid/corrupted source hiçbir zaman clean Start'a düşmez.

### 4.4 `RetryAnalysisCommand`

```python
@dataclass(frozen=True)
class RetryAnalysisCommand:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCode, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTO, ...]
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str
```

Şu invariant'lar bağlayıcıdır:

- `run_id` yeni target run ID'dir;
- `scope.previous_run_id` ve `scope.original_operation` zorunludur;
- `scope.operation_kind == RETRY`;
- `original_operation == RESUME` ise Resume scope/source/auth/corruption invariant'larının tamamı uygulanır;
- automatic retry/backoff yoktur; retry explicit caller use-case'idir;
- 5.0A reuse kararı application tarafından kopyalanmaz.

### 4.5 `CancelAnalysisCommand`

```python
@dataclass(frozen=True)
class CancelAnalysisCommand:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str
```

Cancel için `requested_outputs`, inputs, run options, source intents, prior-period projection, company/report/dashboard/render alanları uygulanamaz ve taşınmaz. Scope, cancel eylemini değil hedef persisted run'ın exact `START`/`RESUME`/`RETRY` scope binding'ini taşır; company/period/tenant/operation/original-operation/previous-run alanlarının tamamı hedefle eşit olmalıdır.

---

## 5. Query Sözleşmeleri

Bütün query'ler scope-qualified ve payload yüklenmeden önce authorize edilmiş olmalıdır.

```python
@dataclass(frozen=True)
class GetAnalysisStatusQuery:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str

@dataclass(frozen=True)
class GetAnalysisResultQuery:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    include_payloads: bool
    application_contract_version: str

@dataclass(frozen=True)
class ListAnalysisHistoryQuery:
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    cursor: str | None
    limit: int
    application_contract_version: str

@dataclass(frozen=True)
class GetExecutionDetailQuery:
    run_id: str
    engine_code: ApplicationEngineCode
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    include_payload: bool
    application_contract_version: str
```

Query scope'u query eylemini değil hedef run'ın persisted scope binding'ini taşır. `operation_kind`, `original_operation` ve `previous_run_id` hedef run için beklenen değerlerle doldurulur ve exact compare edilir. `limit` izin verilen kapalı aralıkta olmalı; cursor opaque ve değiştirilmeden read port'a geçirilmelidir. Wrong-scope kayıt `NOT_FOUND` gibi maskelenebilir, fakat internal security audit'te `SCOPE_MISMATCH_DETECTED` kaydedilir; hiçbir payload veya success DTO üretilmez.

---

## 6. API'den Bağımsız Versioned Application DTO'ları

### 6.1 Tip cebiri ve serialization

```python
APPLICATION_DTO_SCHEMA_VERSION = "1.0.0"

class ApplicationEngineCode(str, Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    RATIO = "ratio"
    BENCHMARK = "benchmark"
    HEALTH_SCORE = "health_score"
    CREDIT_SCORE = "credit_score"
    RECOMMENDATION = "recommendation"
    EXECUTIVE_REPORT = "executive_report"
    DASHBOARD = "dashboard"
    RENDER_CONTRACT = "render_contract"

class ApplicationOperationKind(str, Enum):
    START = "START"
    RESUME = "RESUME"
    RETRY = "RETRY"

class ApplicationOriginalOperation(str, Enum):
    START = "START"
    RESUME = "RESUME"

class FinancialStatementKind(str, Enum):
    BALANCE_SHEET = "BALANCE_SHEET"
    INCOME_STATEMENT = "INCOME_STATEMENT"

class ApplicationReportType(str, Enum):
    CFO_EXECUTIVE_REPORT = "cfo_executive_report"
    BANK_CREDIT_ALLOCATION_REPORT = "bank_credit_allocation_report"
    BOARD_OF_DIRECTORS_REPORT = "board_of_directors_report"
    INVESTOR_REPORT = "investor_report"
    MANAGEMENT_SUMMARY = "management_summary"
    SWOT_REPORT = "swot_report"
    PERIOD_COMPARISON_REPORT = "period_comparison_report"

class ApplicationDashboardType(str, Enum):
    EXECUTIVE_DASHBOARD = "executive_dashboard"
    RISK_DASHBOARD = "risk_dashboard"

class ApplicationRenderMedium(str, Enum):
    PDF = "pdf"
    DOCX = "docx"

class ApplicationReportBlockType(str, Enum):
    KPI_CARD = "kpi_card"
    TABLE = "table"
    BULLET_LIST = "bullet_list"
    PARAGRAPH = "paragraph"
    CHART_DATA = "chart_data"
    BADGE = "badge"

class ApplicationReportSectionCode(str, Enum):
    SEC_COVER_PAGE = "SEC_COVER_PAGE"
    SEC_FINANCIAL_STATEMENTS_SUMMARY = "SEC_FINANCIAL_STATEMENTS_SUMMARY"
    SEC_RATIO_ANALYSIS_TABLE = "SEC_RATIO_ANALYSIS_TABLE"
    SEC_BENCHMARK_COMPARISON = "SEC_BENCHMARK_COMPARISON"
    SEC_HEALTH_SCORE_BREAKDOWN = "SEC_HEALTH_SCORE_BREAKDOWN"
    SEC_CREDIT_SCORE_BREAKDOWN = "SEC_CREDIT_SCORE_BREAKDOWN"
    SEC_BANKING_READINESS = "SEC_BANKING_READINESS"
    SEC_BANK_COLLATERAL_AND_DATA_GAPS = "SEC_BANK_COLLATERAL_AND_DATA_GAPS"
    SEC_RECOMMENDATIONS = "SEC_RECOMMENDATIONS"
    SEC_BOARD_DECISION_ITEMS = "SEC_BOARD_DECISION_ITEMS"
    SEC_RISK_FLAGS = "SEC_RISK_FLAGS"
    SEC_INVESTOR_KPI_SUMMARY = "SEC_INVESTOR_KPI_SUMMARY"
    SEC_PERIOD_COMPARISON_ANALYSIS = "SEC_PERIOD_COMPARISON_ANALYSIS"
    SEC_EXECUTIVE_SUMMARY = "SEC_EXECUTIVE_SUMMARY"
    SEC_SWOT = "SEC_SWOT"
    SEC_METHODOLOGY_APPENDIX = "SEC_METHODOLOGY_APPENDIX"
    SEC_DISCLAIMER_BLOCK = "SEC_DISCLAIMER_BLOCK"
    SEC_CONFIDENCE_AND_DATA_QUALITY = "SEC_CONFIDENCE_AND_DATA_QUALITY"

class ApplicationStatus(str, Enum):
    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ApplicationExecutionStatus(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"

class ExecutionCategory(str, Enum):
    ENGINE_CONTRACT_VIOLATION = "engine_contract_violation"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VERSION_INCOMPATIBLE_ON_REUSE = "version_incompatible_on_reuse"
    FINGERPRINT_MISMATCH_ON_REUSE = "fingerprint_mismatch_on_reuse"
    INVALID_RUN_REQUEST = "invalid_run_request"
    CANCELLED = "cancelled"

class CancellationStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    NOT_ACTIVE = "NOT_ACTIVE"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    NOT_FOUND = "NOT_FOUND"

class ApplicationPayloadOwnerType(str, Enum):
    FINANCIAL_ANALYSIS_RESULT = "FINANCIAL_ANALYSIS_RESULT"
    ORCHESTRATION_ARTIFACT = "ORCHESTRATION_ARTIFACT"

class FinancialSourceMode(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"

class FinancialComputationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class FinancialSourceRole(str, Enum):
    PRIMARY_DOCUMENT = "primary_document"
    SUPPORTING_DOCUMENT = "supporting_document"
    PRIMARY_ANALYSIS = "primary_analysis"
    SUPPORTING_ANALYSIS = "supporting_analysis"
    TRIAL_BALANCE_FALLBACK = "trial_balance_fallback"
    PRIOR_PERIOD_REFERENCE = "prior_period_reference"

class ApplicationEventType(str, Enum):
    START_REQUESTED = "START_REQUESTED"
    RESUME_REQUESTED = "RESUME_REQUESTED"
    RETRY_REQUESTED = "RETRY_REQUESTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    AUTHORIZATION_GRANTED = "AUTHORIZATION_GRANTED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    SCOPE_MISMATCH_DETECTED = "SCOPE_MISMATCH_DETECTED"
    RUN_ID_CONFLICT_DETECTED = "RUN_ID_CONFLICT_DETECTED"
    RESUME_SOURCE_ACCEPTED = "RESUME_SOURCE_ACCEPTED"
    RESUME_SOURCE_REJECTED = "RESUME_SOURCE_REJECTED"
    TERMINAL_RUN_PERSISTED = "TERMINAL_RUN_PERSISTED"
    RESULT_READ = "RESULT_READ"
    HISTORY_READ = "HISTORY_READ"

class AnalysisErrorCode(str, Enum):
    INVALID_COMMAND = "INVALID_COMMAND"
    INVALID_QUERY = "INVALID_QUERY"
    UNAUTHORIZED = "UNAUTHORIZED"
    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"
    AUTHORIZATION_PROVIDER_UNAVAILABLE = "AUTHORIZATION_PROVIDER_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    RUN_ID_CONFLICT = "RUN_ID_CONFLICT"
    FINGERPRINT_CONFLICT = "FINGERPRINT_CONFLICT"
    SCOPE_CLAIM_CONFLICT = "SCOPE_CLAIM_CONFLICT"
    SCOPE_CLAIM_UNAVAILABLE = "SCOPE_CLAIM_UNAVAILABLE"
    SCOPE_FINALIZATION_FAILED = "SCOPE_FINALIZATION_FAILED"
    RESUME_SOURCE_INVALID = "RESUME_SOURCE_INVALID"
    RESUME_SOURCE_CORRUPTED = "RESUME_SOURCE_CORRUPTED"
    RESUME_SOURCE_UNAUTHORIZED = "RESUME_SOURCE_UNAUTHORIZED"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"
    PERSISTENCE_INTEGRITY_ERROR = "PERSISTENCE_INTEGRITY_ERROR"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    DTO_PROJECTION_FAILED = "DTO_PROJECTION_FAILED"
    SECURITY_AUDIT_FAILED = "SECURITY_AUDIT_FAILED"
    INTERNAL_INVARIANT_BREACH = "INTERNAL_INVARIANT_BREACH"

class ApplicationErrorCategory(str, Enum):
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INTEGRITY = "integrity"
    DEPENDENCY = "dependency"
    EXECUTION = "execution"
    RECOVERY = "recovery"
    SECURITY_DEPENDENCY = "security_dependency"
    INTERNAL = "internal"

class ApplicationWarningCode(str, Enum):
    SECURITY_AUDIT_POST_COMMIT_FAILED = "SECURITY_AUDIT_POST_COMMIT_FAILED"

class RunScopeClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    FINALIZED = "FINALIZED"

ApplicationJsonScalar = None | bool | str | int | Decimal | float
ApplicationJsonValue = (
    ApplicationJsonScalar
    | tuple["ApplicationJsonValue", ...]
    | dict[str, "ApplicationJsonValue"]
)
```

Normatif kurallar:

- `bool`, `int`'ten önce doğrulanır; map key yalnız `str` olabilir.
- `float` yalnız finite olabilir; NaN ve ±Infinity reddedilir.
- Application DTO koleksiyon biçimi tuple'dır. Public DTO içinde list yasaktır; future JSON adapter gelen JSON array'i tuple'a normalize eder ve çıkışta tuple'ı JSON array'e çevirir.
- Typed application DTO içinde yukarıdaki gerçek enum tipleri taşınır. Yalnız future JSON boundary adapter enum'u `.value` ile serialize eder; unknown value fail-closed reddedilir.
- `Decimal`, typed DTO içinde `Decimal` kalır ve string'e düşürülmez. JSON encoding future adapter sorumluluğudur.
- Contract alanlarındaki tarih/zamanlar typed `date`/timezone-aware `datetime`'dır. Serbest metadata içindeki tarih `{ "$application_type": "date", "value": "YYYY-MM-DD" }`, datetime ise `{ "$application_type": "datetime", "value": "RFC3339-with-offset" }` tagged map'i ile taşınır; başka tag/key biçimi kabul edilmez.
- `APPLICATION_DTO_SCHEMA_VERSION`, storage codec version'ı değildir. `artifact_serializer_schema_version` ayrı eksendir.
- Serialization sırası deterministik map-key sorting, tuple order preservation, explicit enum value ve canonical Decimal kurallarıyla golden vector testine tabidir. Bu codec 5.0B storage codec'inin yerine geçmez.

### 6.2 Scope, audit ve financial source intent

```python
@dataclass(frozen=True)
class ApplicationScopeDTO:
    company_id: UUID
    financial_period_id: UUID
    tenant_id: str | None
    operation_kind: ApplicationOperationKind
    original_operation: ApplicationOriginalOperation
    previous_run_id: str | None

@dataclass(frozen=True)
class ApplicationAuditContextDTO:
    actor_id: str
    caller_type: str
    request_source: str
    purpose: str
    client_request_id: str | None
    ip_hash: str | None
    user_agent_hash: str | None
    attributes: dict[str, ApplicationJsonValue]

@dataclass(frozen=True)
class FinancialSourceReferenceDTO:
    role: FinancialSourceRole
    source_document_id: UUID | None
    source_analysis_result_id: UUID | None
    source_engine_code: ApplicationEngineCode | None

@dataclass(frozen=True)
class FinancialSourceIntentDTO:
    engine_code: ApplicationEngineCode
    company_id: UUID
    financial_period_id: UUID
    primary_document_id: UUID | None
    source_bindings: tuple[FinancialSourceReferenceDTO, ...]
    requested_source_mode: FinancialSourceMode
    allow_existing_canonical_owner: bool
    expected_existing_owner_id: UUID | None
    provenance_metadata: dict[str, ApplicationJsonValue]
    caller_supplied_business_timestamp: datetime | None
```

`FinancialSourceIntentDTO` persistence command değildir. Caller owner table, `create_owner`, `existing_owner_id` modu, `analysis_type`, engine persistence version'ları, `created_at/finalized_at` veya canonical owner FK üretemez. `expected_existing_owner_id`, yalnız caller'ın beklediği canonical owner'a ilişkin fail-closed compare-and-verify niyetidir; adapter owner tipini gerçek engine code/result ve canonical storage üzerinden belirler.

Financial intent yalnız ownership registry'de `FINANCIAL_ANALYSIS_RESULT` sahibi olan `FS_BALANCE_SHEET`, `FS_INCOME_STATEMENT` ve `RATIO` engine'leri için geçerlidir; diğer engine code'ları `INVALID_COMMAND` olur. Her `FinancialSourceReferenceDTO` içinde `source_document_id`, `source_analysis_result_id`, `source_engine_code` alanlarından **tam biri** doludur. Document rolleri yalnız document ID; analysis rolleri yalnız analysis-result ID veya same-run engine reference ile kullanılabilir. `source_engine_code`, caller'ın owner ID seçmesi değildir; aynı terminal run içindeki üretici engine'e yönelik lineage intent'idir ve yalnız persistence adapter tarafından transaction-local owner ID'ye çözümlenir.

Gerçek 5.0B `AnalysisSourceRole` kümesi birebir kullanılır: `PRIMARY_DOCUMENT`, `SUPPORTING_DOCUMENT`, `PRIMARY_ANALYSIS`, `SUPPORTING_ANALYSIS`, `TRIAL_BALANCE_FALLBACK`, `PRIOR_PERIOD_REFERENCE`. 5.0B'de bulunmayan `GENERATED_FROM_BALANCE_SHEET` veya `GENERATED_FROM_INCOME_STATEMENT` gibi yeni roller uydurulmaz. Ratio için balance-sheet bağı `PRIMARY_ANALYSIS`, income-statement bağı `SUPPORTING_ANALYSIS` rolüyle ve ilgili `source_engine_code` ile ifade edilir.

`source_document_ids` ve `source_analysis_result_ids`, ayrı caller alanları değildir; `source_bindings` üzerinden sırasını koruyarak türetilen read-only projection'lardır. Böylece aynı kaynak iki farklı public alanda tutulmaz. Intent company/period'i command scope ile eşit olmalı; duplicate `(role, source-kind, source-ref)` reddedilir. Business timestamp yalnız iş provenance'ıdır, audit/engine generated time değildir ve timezone-aware olmalıdır.

`ApplicationScopeDTO.operation_kind` hedef analysis run'ın operation'ıdır; Cancel/Read eylemi bu alana yazılmaz. `START` için `original_operation=START` ve previous yoktur; `RESUME` için `original_operation=RESUME` ve previous zorunludur; `RETRY` için original operation ve previous zorunludur.

### 6.2.1 5.0B ownership registry uyumluluk matrisi

| 5.0B engine | 5.0B owner | Analysis type | Public financial intent | Post-result davranışı |
|---|---|---|---|---|
| `FS_BALANCE_SHEET` | `FINANCIAL_ANALYSIS_RESULT` | `BALANCE_SHEET` | zorunlu | completed/degraded result için owner node |
| `FS_INCOME_STATEMENT` | `FINANCIAL_ANALYSIS_RESULT` | `INCOME_STATEMENT` | zorunlu | completed/degraded result için owner node |
| `RATIO` | `FINANCIAL_ANALYSIS_RESULT` | `FINANCIAL_RATIOS` | zorunlu | completed/degraded result için BS/IS lineage'lı owner node |
| `BENCHMARK` | `ORCHESTRATION_ARTIFACT` | yok | yasak | 5.0B artifact owner |
| `HEALTH_SCORE` | `ORCHESTRATION_ARTIFACT` | yok | yasak | 5.0B artifact owner |
| `CREDIT_SCORE` | `ORCHESTRATION_ARTIFACT` | yok | yasak | 5.0B artifact owner |
| `RECOMMENDATION` | `ORCHESTRATION_ARTIFACT` | yok | yasak | 5.0B artifact owner |
| `EXECUTIVE_REPORT` | `ORCHESTRATION_ARTIFACT` | yok | yasak | 5.0B artifact owner |
| `DASHBOARD` | `ORCHESTRATION_ARTIFACT` | yok | yasak | 5.0B artifact owner |
| `RENDER_CONTRACT` | `ORCHESTRATION_ARTIFACT` | yok | yasak | 5.0B artifact owner |

Bu tablo `RESULT_OWNERSHIP_REGISTRY` ile satır satır aynı olmak zorundadır ve registry contract testiyle korunur.

### 6.3 Payload reference ve envelope

```python
@dataclass(frozen=True)
class ApplicationPayloadReferenceDTO:
    owner_type: ApplicationPayloadOwnerType
    financial_analysis_result_id: UUID | None
    artifact_id: UUID | None
    result_kind: str
    canonical_digest: str
    artifact_serializer_schema_version: str | None

@dataclass(frozen=True)
class ApplicationProjectedErrorDTO:
    category: ExecutionCategory
    engine_code: ApplicationEngineCode | None
    message: str

@dataclass(frozen=True)
class ApplicationPayloadEnvelopeDTO:
    payload_reference: ApplicationPayloadReferenceDTO
    computation_status: FinancialComputationStatus
    source_mode: FinancialSourceMode | None
    result_payload: ApplicationJsonValue | None
    structured_error: ApplicationProjectedErrorDTO | None
    message: str | None
    inner_status: str | None
    trial_balance_usage: ApplicationJsonValue | None
    provenance_source_references: tuple[str, ...]
    engine_schema_version: str | None
    engine_model_version: str | None
    application_schema_version: str
```

Owner XOR zorunludur:

- `FINANCIAL_ANALYSIS_RESULT`: `financial_analysis_result_id` zorunlu, `artifact_id=None`, canonical digest zorunlu, `artifact_serializer_schema_version=None` zorunludur.
- `ORCHESTRATION_ARTIFACT`: `artifact_id`, `result_kind`, canonical digest ve `artifact_serializer_schema_version` zorunlu; financial ID `None`'dır.

Financial owner'ı artifact serializer version taşımaya zorlamak yasaktır. BS/IS projection; computation/inner status, source mode, payload, structured error/message, trial-balance usage, provenance/source refs ve engine schema/model version'larını kayıpsız taşır. Eksik alanı sessiz default ile üretmek yerine projection fail-closed olur.

### 6.4 Public result DTO'ları

```python
@dataclass(frozen=True)
class AnalysisWarningDTO:
    code: ApplicationWarningCode
    message: str
    retryable: bool

@dataclass(frozen=True)
class AnalysisErrorDTO:
    code: AnalysisErrorCode
    category: ApplicationErrorCategory
    message: str                    # allowlisted public metin
    retryable: bool
    correlation_id: str
    safe_metadata: dict[str, ApplicationJsonValue]
    application_schema_version: str

@dataclass(frozen=True)
class AnalysisExecutionDTO:
    engine_code: ApplicationEngineCode
    status: ApplicationExecutionStatus
    inner_status: str | None
    error: ApplicationProjectedErrorDTO | None
    dependency_engine_codes: tuple[ApplicationEngineCode, ...]
    engine_schema_version: str | None
    engine_model_version: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    payload: ApplicationPayloadEnvelopeDTO | None
    reused_from_run_id: str | None
    application_schema_version: str

@dataclass(frozen=True)
class AnalysisCommandResultDTO:
    run_id: str
    status: ApplicationStatus
    request_fingerprint: str
    terminal_content_digest: str
    scope: ApplicationScopeDTO
    executions: tuple[AnalysisExecutionDTO, ...]
    persisted_at: datetime
    idempotent_replay: bool
    recovery_query_run_id: str
    application_schema_version: str

@dataclass(frozen=True)
class AnalysisRunSummaryDTO:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    requested_outputs: tuple[ApplicationEngineCode, ...]
    finalized_at: datetime
    previous_run_id: str | None
    application_schema_version: str

@dataclass(frozen=True)
class AnalysisRunStatusDTO:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    finalized_at: datetime
    engine_statuses: tuple[tuple[ApplicationEngineCode, ApplicationExecutionStatus], ...]
    terminal: bool
    application_schema_version: str

@dataclass(frozen=True)
class AnalysisResultDTO:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    request_fingerprint: str
    executions: tuple[AnalysisExecutionDTO, ...]
    warnings: tuple[ApplicationJsonValue, ...]
    structured_errors: tuple[ApplicationProjectedErrorDTO, ...]
    execution_plan_version: str
    orchestration_schema_version: str
    orchestration_model_version: str
    finalized_at: datetime
    application_schema_version: str

@dataclass(frozen=True)
class AnalysisHistoryPageDTO:
    items: tuple[AnalysisRunSummaryDTO, ...]
    next_cursor: str | None
    application_schema_version: str

@dataclass(frozen=True)
class CancellationResultDTO:
    run_id: str
    status: CancellationStatus
    scope: ApplicationScopeDTO
    requested_at: datetime
    application_schema_version: str
```

`engine_statuses` engine plan sırasındadır; arbitrary dict değildir. Error DTO raw exception/trace taşımaz. Public result içinde 5.0A dataclass veya ORM entity bulunmaz.

### 6.5 `ApplicationOutcome[T]`

```python
@dataclass(frozen=True)
class ApplicationOutcome(Generic[T]):
    success: bool
    value: T | None
    error: AnalysisErrorDTO | None
    warnings: tuple[AnalysisWarningDTO, ...]
    correlation_id: str
    application_schema_version: str
```

`success=True` ise `value` zorunlu ve `error=None`; `success=False` ise `value=None` ve `error` zorunludur. Expected validation, authorization, conflict, not-found ve persistence hataları outcome'dur. Raw upstream exception çıkmaz. Programmer error/invariant breach internal exception olabilir; public boundary yakalar, sanitize eder ve `INTERNAL_INVARIANT_BREACH` outcome üretir.

Cancellation'ın beş durumu normal business result olabilir. Authorization failure, invalid request ve scope mismatch error outcome'dur. `NOT_ACTIVE` ayrıca error code olarak modellenmez.

---

## 7. Engine Dataclass'larının Dış Dünyaya Açılmaması ve Normatif Mapping

| Application alanı | Değişmemiş 5.0A hedefi |
|---|---|
| command run/correlation/generated_at/requested_outputs | `OrchestrationRunRequest` aynı anlamlı alanları; datetime RFC3339 string'e explicit mapper ile |
| `AnalysisInputsDTO` | `EngineRawInputs` document/trial-balance/period alanları |
| `PriorPeriodFactsDTO(BALANCE_SHEET)` | `prior_period_balance_sheet_facts` için `BalanceSheetFacts` |
| `PriorPeriodFactsDTO(INCOME_STATEMENT)` | `prior_period_income_statement_facts` için `IncomeStatementFacts` |
| prior result map'leri | `prior_period_balance_sheet_result` / `prior_period_income_statement_result` |
| run option industry/size/segmentation tenant | `industry_code` / `company_size_bucket` / `tenant_id`; auth tenant'a otomatik kopyalanmaz |
| `ReportRequestDTO.report_type` | `OrchestrationRunOptions.report_type: Any` içine doğrulanmış `ReportType` |
| report section values | `optional_sections: Any` içine doğrulanmış `tuple[ReportSectionCode,...]` |
| `DashboardRequestDTO.dashboard_type` | `dashboard_type: Any` içine doğrulanmış `DashboardType` |
| `CompanyMetadataDTO` | `company_metadata: Any` içine doğrulanmış `ReportCompanyMetadata` |
| `RenderContractRequestDTO` | `render_contract: Any` içine doğrulanmış `RenderContract` |

5.0A'nın `Any` alanları application'da `Any` olarak tekrar edilmez. Mapping kapalı enum/field doğrulaması yapar; lossless map edemediği değeri `INVALID_COMMAND` ile reddeder. Reverse projection canonical storage kayıtlarından yapılır, engine dataclass referansı döndürmez.

---

## 8. Orchestrator + Persistence Phased Coordination Akışı

Start/Resume/Retry için tek normatif sıra:

1. **A — Application preflight:** contract, scope, source intent, required audit ve authorization doğrulanır; mevcut run varsa scope + application command digest değerlendirilir.
2. **B — Resume context:** gerekiyorsa source metadata authorize edilir; authorization grant audit'i yazıldıktan sonra snapshot/payload yüklenir ve integrity doğrulanır.
3. **C — Execution:** command, değişmemiş `OrchestrationRunRequest`'e map edilir; değişmemiş `run_orchestration()` çağrılır.
4. **D — Result inspection:** yalnız gerçek `OrchestrationRunResult.engine_records` incelenir.
5. **E — Binding resolution:** yalnız `COMPLETED` veya `DEGRADED` ve `record.result is not None` olan financial execution için intent + gerçek `record.result.result` kullanılarak transaction-neutral `ResolvedFinancialOwnershipPlan` üretilir.
6. **F — No phantom binding:** `FAILED`, `SKIPPED`, `NOT_STARTED`, `REUSED` veya `record.result is None` için yeni owner node/binding üretilmez. Reused owner, doğrulanmış resume context ile 5.0B tarafından korunur.
7. **Authorization revalidation:** persistence'tan hemen önce yeniden yetkilendirme yapılır ve required grant/deny audit'i yazılır.
8. **G — Persistence request:** gerçek result, telemetry, resume context ve post-result ownership plan ile internal `ApplicationTerminalPersistenceRequest` oluşturulur. Değişmemiş 5.0B `PersistTerminalRunCommand`, transaction-local owner ID'leri çözüldükten sonra yalnız persistence adapter içinde oluşturulur.
9. **H — Atomic persist:** `RunPersistencePort.persist_terminal_run()` çağrılır; adapter aynı unit-of-work içinde planı materialize edip mevcut 5.0B persistence davranışını uygular.
10. **I — Return validation/projection:** dönen `PersistedRun.scope`, full application scope binding, run ID ve fingerprint/idempotency sonucu yeniden doğrulanır; sonra canonical read projection yapılır.

Missing intent, wrong existing owner, result/intention engine mismatch veya unexpected binding fail-closed `PERSISTENCE_INTEGRITY_ERROR`/`INVALID_COMMAND` sonucudur. One-shot `OrchestrationPersistenceService.execute_and_persist(...)` bu sırayı sağlayamadığı için 5.0C'nin mandatory integration path'i değildir. 5.0C mevcut 5.0A ve 5.0B public portlarını phased coordination ile kullanır.

### 8.1 Financial owner ve Ratio lineage assembly

`ResolvedFinancialOwnershipPlan` public command/DTO değildir; gerçek engine sonucu görüldükten sonra application persistence adapter sınırında üretilen immutable internal plandır. Her plan node'u engine code, gerçek outcome, gerçek engine model version, doğrulanmış source mode, create-vs-verified-existing intent ve role-bearing lineage edge'lerini taşır. `analysis_type` yalnız Bölüm 6.2.1 registry mapping'inden; owner payload/digest yalnız gerçek `EngineResultEnvelope.result` üzerinden; audit zamanları yalnız injected clock/lifecycle üzerinden türetilir.

Resolver kuralları:

- `requested_source_mode`, gerçek BS/IS outcome `source_mode` ile exact eşleşmelidir; persist edilen değer her durumda gerçek outcome'dan alınır. Ratio için mode, doğrulanmış input lineage'a göre `MULTI_SOURCE_DERIVED` olmalıdır.
- `primary_document_id` doluysa aynı ID'yi taşıyan tam bir `PRIMARY_DOCUMENT` edge zorunludur; boşsa böyle bir edge olamaz.
- `allow_existing_canonical_owner=False` iken `expected_existing_owner_id=None` zorunludur. True olduğunda expected ID zorunludur ve owner scope/type/digest/outcome semantiği 5.0B tarafından doğrulanır; mismatch fallback-create yapmaz.
- 5.0B `CreateFinancialResultOwner.engine_version`, `record.engine_model_version_used` değerinden oluşturulur; değer yoksa create yasaktır. Schema version yalnız orchestration execution kaydında kalır ve engine-version alanına karıştırılmaz.
- External document/analysis source edge'leri doğrudan gerçek 5.0B `FinancialResultSourceBinding`'e map edilir. Same-run engine edge'i ancak bu bölümdeki transaction-local resolution sonrasında analysis-result ID'ye dönüşür.
- `FAILED`, `SKIPPED`, `NOT_STARTED`, `REUSED` veya `record.result is None` node üretmez. Reused execution yalnız resume context owner'ını kullanır.

Yeni BS/IS ve Ratio owner'ları aynı run'da oluşuyorsa normatif transaction sırası şöyledir:

1. Adapter, caller'dan owner/FK almadan bütün CREATE financial node'ları için transaction-local UUID'leri kendisi preallocate eder.
2. BS/IS owner satırları gerçek outcome semantiğiyle aynı terminal PostgreSQL transaction'ında hazırlanır.
3. Ratio planındaki `source_engine_code=FS_BALANCE_SHEET` edge'i preallocated BS owner ID'sine `PRIMARY_ANALYSIS`; `source_engine_code=FS_INCOME_STATEMENT` edge'i preallocated IS owner ID'sine `SUPPORTING_ANALYSIS` olarak çözülür.
4. Eksik/failed/skipped/reused olmayan bir required source engine, duplicate edge, wrong scope veya role/source-kind mismatch tüm transaction'ı reddeder. Mixed BS success/IS failure halinde Ratio engine dependency nedeniyle sonuç üretmemiş olmalıdır; Ratio sonucu varsa eksik lineage fail-closed integrity breach'tir.
5. Owner satırları ve `FinancialAnalysisResultSource` lineage satırları flush edilir; sonra 5.0B terminal run/execution kayıtları bu preallocated owner ID'lerine bağlanır.
6. 5.0B'nin owner payload digest, status, source mode, analysis type ve scope doğrulamaları aynen çalışır; herhangi hata bütün staged owner/lineage/run kayıtlarını rollback eder.
7. Commit; financial owners + lineage + orchestration run + executions + artifacts için tek atomik terminal transaction'dır.

Same-run analysis edge resolution kapalıdır: source financial execution bu run'da yeni `COMPLETED/DEGRADED` owner üretiyorsa preallocated ID; `REUSED` ise doğrulanmış `ResumePersistenceContext` owner ID; verified-existing intent kullanıyorsa digest/scope/type doğrulanmış existing owner ID seçilir. `FAILED/SKIPPED/NOT_STARTED`, missing owner veya artifact-owned engine hiçbir analysis edge'e çözülemez. Bu seçim caller tarafından yapılamaz.

Bu mekanizma 5.0B public dataclass/port alanlarını değiştirmez. Application `RunPersistencePort`, internal planı kabul eder; SQLAlchemy edge adapter'ı planı aynı unit-of-work içinde canonical owner/source satırlarına materialize eder, transaction-local owner ID'lerini kullanan değişmemiş 5.0B `FinancialResultOwnerBinding(existing_owner_id=...)` değerlerini ve `PersistTerminalRunCommand`'ı oluşturur, ardından aynı `Session` üzerindeki değişmemiş `RunStorePort.persist_terminal_run()` çağrısını yapar. 5.0B owner digest/scope/type/semantic kontrolleri staged satırlara da uygulanır ve repository commit/rollback'u bütün unit-of-work'ü kapsar. Transaction-local UUID üretimi ve FK assembly public command'a, application DTO'ya veya pure use-case'e sızamaz. Adapter aynı session/atomik unit-of-work'ü sağlayamıyorsa `PERSISTENCE_INTEGRITY_ERROR` ile fail-closed olur; owner'ları ayrı transaction'da önceden commit etmek yasaktır.

Concurrent idempotent persistence için ek transaction kuralı bağlayıcıdır:

1. Adapter financial owner/source staging başlamadan hemen önce aynı `Session` üzerinde bir SAVEPOINT açar.
2. Transaction-local owner ve lineage satırları yalnız bu SAVEPOINT içinde add/flush edilir.
3. Değişmemiş `RunStorePort.persist_terminal_run()` yeni canonical run'ı commit ederse repository commit'i SAVEPOINT dahil bütün terminal unit-of-work'ü sonlandırır.
4. Repository aynı fingerprint + terminal digest'e sahip mevcut run nedeniyle erken idempotent dönüş yaparsa repository commit/rollback yapmamış olabilir. Adapter bunu SAVEPOINT'in hâlâ active olmasıyla fail-closed tespit eder ve public DTO, claim finalize veya başka write işleminden **önce** zorunlu `rollback-to-savepoint` uygular.
5. Rollback sonrasında staged owner/source nesneleri session identity map'ten expire/expunge edilir. Sonraki herhangi bir commit bu satırları yeniden flush edemez; loser invocation'ın preallocated owner ID'leri ve lineage ID'leri PostgreSQL'de bulunamaz.
6. Rollback-to-savepoint veya discard doğrulanamazsa adapter bütün session transaction'ını rollback eder ve `PERSISTENCE_INTEGRITY_ERROR` döndürür; idempotent success projection yasaktır.
7. Integrity-error yarış yolunda 5.0B repository zaten full rollback yapmışsa adapter staged state'in kalmadığını doğrular; ikinci kez owner yazmaz.

Dolayısıyla erken idempotent dönüş canonical winner run'ı okuyabilir fakat loser invocation'ın staged financial owner/lineage kayıtlarını hiçbir koşulda kalıcılaştıramaz. `FinancialResultOwnerBinding(existing_owner_id=...)` yalnız SAVEPOINT içinde staged ve aynı terminal commit'e aday canonical owner için internal adapter tarafından kullanılabilir; idempotent-existing dönüşte bu ID'ler discard edilir ve dışarı açıklanmaz.

---

## 9. Transaction ve Authorization Sınırı

- Validation, audit, authorization, snapshot read ve engine execution sırasında terminal persistence transaction'ı açık tutulmaz.
- 5.0B repository, terminal run + engine execution + owner/artifact kayıtlarını tek transaction'da atomik persist eder.
- External blob staging transaction öncesi olabilir; READY referansı ve DB commit 5.0B politikasına tabidir.
- Post-persist scope validation ve projection ayrı read aşamasıdır; commit'i geri almaz.
- Pre-execution authorization zorunludur.
- Uzun sürebilen execution sonrasında pre-persistence authorization revalidation zorunludur.
- Revalidation deny/revocation ise terminal persistence yapılmaz, raw `OrchestrationRunResult` caller'a verilmez, required security audit yazılır ve `UNAUTHORIZED` veya `AUTHORIZATION_REVOKED` döner. Harcanmış CPU geri alınamaz.
- Resume source payload materialization, `authorize_resume_source` grant + required audit başarıyla tamamlanmadan yapılamaz.

---

## 10. Scope-Aware Idempotency

Authoritative engine `request_fingerprint` ve terminal conflict kararı 5.0B'nindir. 5.0C tam scope binding'i ayrıca zorunlu tutar:

```text
(company_id, financial_period_id, tenant_id,
 operation_kind, original_operation, previous_run_id)
```

Security audit scope sahibi değildir ve scope doğrulama girdisi olarak kullanılamaz. Full binding ayrı durable `RunScopeClaim` sözleşmesinin tek sahibidir:

```python
@dataclass(frozen=True)
class RunScopeClaim:
    claim_id: UUID
    run_id: str
    company_id: UUID
    financial_period_id: UUID
    tenant_id: str | None
    operation_kind: ApplicationOperationKind
    original_operation: ApplicationOriginalOperation
    previous_run_id: str | None
    application_command_digest: str
    status: RunScopeClaimStatus
    version: int
    claim_token: str
    persisted_run_id: UUID | None
    persisted_request_fingerprint: str | None
    persisted_terminal_content_digest: str | None
    claimed_at: datetime
    finalized_at: datetime | None
```

`run_id` durable store seviyesinde unique'tir. Scope alanları ve command digest CLAIMED olduktan sonra immutable'dır. `claim_token` secret olmayan opaque CAS token'ıdır; public DTO'ya çıkmaz. Claim store financial/domain payload saklamaz, event log değildir ve 5.0B canonical run'ın yerine geçmez.

`RunScopeClaim` yalnız immutable **run ownership reservation**'ıdır. Workflow state, running job, scheduler, queue item, durable execution registry veya event-sourcing event'i değildir. Engine'in çalışıp çalışmadığını, progress'i, attempt'i, cancellation durumunu ya da worker sahipliğini göstermez. `CLAIMED`, yalnız `run_id` için scope sahibinin atomik olarak ayrıldığını; `FINALIZED`, aynı reservation'ın canonical terminal tuple'a bağlandığını ifade eder. Bu iki değer analysis execution lifecycle status'ları değildir.

Production adapter'ı additive PostgreSQL `analysis_run_scope_claims` tablosudur. En az `UNIQUE(run_id)`, status check, positive version check, CLAIMED/FINALIZED conditional-field check ve scope alanlarını UPDATE/DELETE'e karşı immutable kılan PostgreSQL trigger zorunludur. Finalize yalnız status/version CAS update'idir; scope veya command digest update edemez. Claim token plaintext loglanmaz. Bu tablo yalnız scope ownership sahibidir; engine result, artifact veya financial payload tutamaz. In-memory fake yalnız unit test içindir.

### 10.1 Atomik claim / verify / finalize lifecycle

| İşlem | Atomik davranış | Aynı scope | Farklı scope/tenant | Unavailable/timeout |
|---|---|---|---|---|
| `claim` | unique `run_id` üzerinde insert-if-absent/CAS | aynı command digest ile mevcut claim idempotent döner | `SCOPE_CLAIM_CONFLICT`; mevcut claim açıklanmaz | `SCOPE_CLAIM_UNAVAILABLE`, fail-closed, execution yok |
| `verify` | `run_id + claim_token + version + full scope` exact compare | verified claim döner | `SCOPE_MISMATCH`, fail-closed | `SCOPE_CLAIM_UNAVAILABLE`, fail-closed |
| `finalize` | `CLAIMED(version=n) -> FINALIZED(version=n+1)` CAS; persisted ID/fingerprint/digest tek sefer bağlanır | aynı terminal tuple ile idempotent success | wrong tenant/scope/token veya farklı terminal tuple kesin ret | `SCOPE_FINALIZATION_FAILED`; commit geri alınmaz, DTO yok, recovery gerekir |

İki tenant aynı `run_id`'yi claim edemez. Aynı company/period olsa bile tenant veya operation farkı conflict'tir. Claim overwrite, delete, release-to-different-scope ve last-writer-wins yasaktır. Crash sonrası CLAIMED kayıt korunur; exact scope/command retry devam edebilir, farklı scope asla devralamaz.

Preflight:

1. Command validate edilir, required request audit ve authorization tamamlanır.
2. `RunScopeClaimPort.claim(...)` çağrısı execution'dan **önce** yapılır.
3. Mevcut claim varsa full scope + application command digest exact compare edilir; mismatch success mapping'den önce kesin reddedilir.
4. Finalized claim ve canonical 5.0B run aynı persisted tuple'ı gösteriyorsa canonical result doğrudan okunabilir.
5. CLAIMED claim yanında terminal 5.0B run varsa bu crash-after-commit recovery'dir: DB company/period + claim token/scope doğrulanır ve finalize CAS tamamlanır; engine yeniden çalıştırılmaz.
6. Claim var fakat canonical run yoksa yalnız exact claim sahibi execution'a/retry'a devam edebilir.

Normatif sıra ve güvenlik kapısı:

```text
PREFLIGHT + ATOMIC CLAIM
        -> 5.0A EXECUTION
        -> 5.0B TERMINAL PERSIST
        -> CLAIM VERIFY + FINALIZE CAS
        -> CANONICAL DTO PROJECTION
```

- Persist öncesi claim tekrar verify edilir.
- `PersistedRun.scope` company/period'i command ve claim ile exact eşit olmalıdır.
- Persisted ID, authoritative fingerprint ve terminal digest finalize CAS ile claim'e bağlanır.
- Finalize başarıyla tamamlanmadan hiçbir success DTO/payload açıklanamaz.
- Wrong-tenant finalize veya DTO projection kesin fail-closed'dur.
- Concurrent cross-scope race claim aşamasında durdurulur; persistence'a ulaşamaz.
- Post-commit security audit başarısızlığı claim ownership veya finalized scope'u değiştiremez. Canonical run geri alınmaz ve yalnız mandatory warning politikası uygulanır.
- Security audit kayıtları claim'i create/verify/finalize edemez ve claim recovery kaynağı değildir.

Bağlayıcı invariant'lar:

```text
SAME_RUN_ID_SAME_SCOPE_SAME_FINGERPRINT       -> idempotent success mümkündür
SAME_RUN_ID_DIFFERENT_SCOPE                   -> kesin ret
SAME_RUN_ID_SAME_SCOPE_DIFFERENT_FINGERPRINT  -> kesin conflict/ret
```

Application-command digest; exact command recovery ve scope preflight yardımcısıdır, 5.0B request fingerprint'inin yerine geçmez.

---

## 11. Resume/Reuse ve Retry Akışı

Resume yeni target run ID ve previous run ID gerektirir. Source scope metadata-only okunur, target ile eşitliği ve authorization doğrulanır, sonra `build_previous_execution_snapshot` çağrılır. 5.0B binding; source execution, owner FK, canonical digest, engine/schema/model version ve input fingerprint'i fail-closed doğrular. 5.0C snapshot içeriğini üretmez veya reuse eligibility hesaplamaz; snapshot'ı değişmemiş 5.0A'ya verir.

Retry da yeni target run ID gerektirir. `original_operation=START` ise previous run yalnız provenance/retry kaynağıdır; `RESUME` ise tüm resume invariant'ları geçerlidir. Reuse kararı yalnız 5.0A'dadır. Invalid/missing/corrupted/unauthorized source hiçbir zaman clean Start fallback'e dönüşmez. Automatic retry ve backoff kapsam dışıdır.

Transitive reuse corruption, wrong owner veya scope mismatch `RESUME_SOURCE_CORRUPTED`/`RESUME_SOURCE_INVALID` outcome'dur; engine çalıştırılmaz.

---

## 12. Cancellation ve Local Active Execution

`ActiveExecutionPort` yalnız cooperative cancellation, local diagnostics ve progress/observability hook'ları içindir. Correctness, idempotency, authorization veya persisted existence kaynağı değildir.

V1 semantiği:

- aynı duplicate request aynı process'te de execution'a başlayabilir;
- otomatik `RUN_ALREADY_ACTIVE` reddi yoktur;
- aynı/farklı process terminal semantiği eşittir; nihai idempotency 5.0B'dedir;
- distributed lock, exactly-once execution ve durable active-job registry kapsam dışıdır;
- cancel local invocation bulursa `ACCEPTED` veya `ALREADY_REQUESTED`; bulmazsa canonical terminal lookup'a göre `ALREADY_TERMINAL`, `NOT_FOUND` veya `NOT_ACTIVE` dönebilir;
- local invocation yokluğu persisted run yokluğu anlamına gelmez;
- cancellation probe engine sınırlarında gözlenir; hard-stop/rollback garantisi yoktur.

Register failure correctness'i engellemez, ancak local cancellation özelliğini kaybettireceği için operational alert ve warning üretir. Unregister `finally` içinde çağrılır. Cancellation ile idempotency birbirine bağlanmaz.

---

## 13. Authorization Hook'ları

Default deny uygulanır. Start/Resume/Retry pre-execution; Cancel hedef scope; bütün read query'leri metadata/payload öncesi authorize edilir. Resume için source ve target ayrı karar alır. Execution sonrası pre-persistence revalidation zorunludur.

Authorization provider unavailable fail-closed `AUTHORIZATION_PROVIDER_UNAVAILABLE` üretir. Grant ve deny kararlarının required security audit kaydı yazılamazsa işlem başlamaz/devam etmez. Revocation `AUTHORIZATION_REVOKED` ile ayrıştırılır.

---

## 14. Caller Identity / Tenant Context Sınırı

`audit_context.actor_id` identity, `scope.tenant_id` authorization isolation, `run_options.engine_segmentation_tenant_id` ise yalnız engine business segmentation alanıdır. Birbirine otomatik kopyalanamaz. Company/period/tenant üçlüsü bütün read/write authorization çağrılarında bulunur. Caller-supplied owner/table/engine audit time kabul edilmez.

---

## 15. Correlation ve Audit Context

`correlation_id` caller tarafından üretilir, boş olamaz ve outcome'da korunur. `generated_at` application request/audit zamanıdır; engine determinism'ine gizlice enjekte edilmez. Audit context allowlisted metadata taşır; raw document, financial payload, token, stack trace veya raw exception yasaktır.

Required audit kaydı; run ID, correlation, full scope, actor reference, event, safe decision code ve canonical application-command digest taşıyabilir. Digest 5.0B request fingerprint değildir.

---

## 16. Error Taxonomy ve Application Outcome

### 16.1 Kapalı public error code kümesi

`ApplicationErrorCode` şu değerlerle kapalıdır:

`INVALID_COMMAND`, `INVALID_QUERY`, `UNAUTHORIZED`, `AUTHORIZATION_REVOKED`, `AUTHORIZATION_PROVIDER_UNAVAILABLE`, `NOT_FOUND`, `SCOPE_MISMATCH`, `RUN_ID_CONFLICT`, `FINGERPRINT_CONFLICT`, `SCOPE_CLAIM_CONFLICT`, `SCOPE_CLAIM_UNAVAILABLE`, `SCOPE_FINALIZATION_FAILED`, `RESUME_SOURCE_INVALID`, `RESUME_SOURCE_CORRUPTED`, `RESUME_SOURCE_UNAUTHORIZED`, `PERSISTENCE_CONFLICT`, `PERSISTENCE_INTEGRITY_ERROR`, `PERSISTENCE_UNAVAILABLE`, `EXECUTION_FAILED`, `DTO_PROJECTION_FAILED`, `SECURITY_AUDIT_FAILED`, `INTERNAL_INVARIANT_BREACH`.

### 16.2 Exhaustive mapping

| Public code | Kaynak | Public message policy | Retryable | Semantic category | Fail | Required audit |
|---|---|---|---:|---|---|---|
| `INVALID_COMMAND` | command/schema/closed-enum validation | sabit validation metni + safe field code | hayır | validation | closed | request event |
| `INVALID_QUERY` | query/cursor/limit validation | sabit query metni | hayır | validation | closed | read event |
| `UNAUTHORIZED` | authorization deny/revalidation deny | kaynak ayrıntısını gizleyen sabit metin | hayır | authorization | closed | deny |
| `AUTHORIZATION_REVOKED` | pre-persist revalidation revocation | sabit revocation metni | hayır | authorization | closed | deny |
| `AUTHORIZATION_PROVIDER_UNAVAILABLE` | auth timeout/unavailable | sabit dependency metni | evet | dependency | closed | denial/failure attempt |
| `NOT_FOUND` | scope-qualified canonical lookup miss | existence leak etmeyen sabit metin | hayır | not_found | closed | read/cancel |
| `SCOPE_MISMATCH` | preflight/post-persist/read scope mismatch | expected/actual değer içermeyen metin | hayır | conflict/security | closed | scope mismatch |
| `RUN_ID_CONFLICT` | same run ID incompatible scope/command binding | payload/fingerprint göstermeyen metin | hayır | conflict | closed | run conflict |
| `FINGERPRINT_CONFLICT` | 5.0B authoritative fingerprint mismatch | digest göstermeyen metin | hayır | conflict | closed | run conflict |
| `SCOPE_CLAIM_CONFLICT` | atomic claim unique/CAS mismatch | mevcut tenant/scope'u açmayan metin | hayır | conflict | closed | scope mismatch |
| `SCOPE_CLAIM_UNAVAILABLE` | claim store timeout/unavailable | sabit dependency metni | evet | dependency | closed | operational alert |
| `SCOPE_FINALIZATION_FAILED` | post-commit finalize timeout/CAS failure | safe run ID/recovery hint | evet | recovery | closed | operational alert |
| `RESUME_SOURCE_INVALID` | missing/invalid chain/status/scope | source payload içermeyen metin | hayır | validation/conflict | closed | resume rejected |
| `RESUME_SOURCE_CORRUPTED` | digest/owner/version/fingerprint corruption | hangi payloadın bozuk olduğunu açmayan metin | hayır | integrity | closed | resume rejected + alert |
| `RESUME_SOURCE_UNAUTHORIZED` | source authorization deny | source existence gizleyen metin | hayır | authorization | closed | deny/resume rejected |
| `PERSISTENCE_CONFLICT` | unique/concurrent terminal conflict; fingerprint conflict ayrı code'a map edilir | DB ayrıntısı içermeyen metin | hayır | conflict | closed | run conflict |
| `PERSISTENCE_INTEGRITY_ERROR` | owner/binding/constraint/digest invariant | tablo/FK/raw SQL içermeyen metin | hayır | integrity | closed | required + alert |
| `PERSISTENCE_UNAVAILABLE` | DB/blob dependency unavailable | sabit dependency metni | evet | dependency | closed | failure attempt |
| `EXECUTION_FAILED` | unexpected orchestration boundary failure | engine raw exception içermeyen metin | hayır | execution | closed | required + alert |
| `DTO_PROJECTION_FAILED` | committed canonical run projection failure | safe run ID/recovery hint dışında ayrıntı yok | evet | recovery | closed | required + alert |
| `SECURITY_AUDIT_FAILED` | required pre-exec/auth audit failure | sink/exception ayrıntısı içermeyen metin | evet | security_dependency | closed | operational alert |
| `INTERNAL_INVARIANT_BREACH` | programmer error/caught impossible state | generic correlation metni | hayır | internal | closed | required + alert |

Tablo exhaustive'tir: public boundary başka code çıkaramaz. Ham exception message, SQL, stack trace ve secret/financial content hiçbir public message veya metadata'ya girmez.

### 16.3 Post-commit warning

`SECURITY_AUDIT_POST_COMMIT_FAILED` error değildir, kapalı `AnalysisWarningDTO.code` değeridir. Terminal DB commit başarılıysa business result success kalır, canonical run geri alınmaz, warning zorunlu eklenir ve ayrı operational alert best effort üretilir.

---

## 17. Dependency Injection ve Exact Port Sözleşmeleri

Bütün portlar `Protocol` tabanlı, framework bağımsızdır. Adapter exception'ları port sınırında internal normalized failure'lara çevrilir; use-case bunları Bölüm 16 outcome'larına map eder.

Port imzalarında kullanılan internal value object'ler de belirsiz bırakılmaz:

```python
@dataclass(frozen=True)
class InternalRunView:
    persisted_run_id: UUID
    run_id: str
    status: ApplicationStatus
    persistence_scope: PersistenceRunScope
    requested_outputs: tuple[ApplicationEngineCode, ...]
    request_fingerprint: str
    terminal_content_digest: str
    previous_run_id: str | None
    finalized_at: datetime

@dataclass(frozen=True)
class VerifiedApplicationScopeBinding:
    run_id: str
    scope: ApplicationScopeDTO
    persistence_scope: PersistenceRunScope
    application_command_digest: str
    claim_id: UUID
    claim_version: int
    claim_status: RunScopeClaimStatus

@dataclass(frozen=True)
class AuthorizedResumeSourceView:
    run: InternalRunView
    verified_scope: VerifiedApplicationScopeBinding
    payloads_materialized: bool
    snapshot_load_result: SnapshotLoadResult | None

@dataclass(frozen=True)
class AuthorizationDecision:
    granted: bool
    revoked: bool
    decision_code: str
    provider_decision_reference: str
    decided_at: datetime

@dataclass(frozen=True)
class OwnerAuditTimes:
    started_at: datetime
    completed_at: datetime

@dataclass(frozen=True)
class ResolvedFinancialLineageEdge:
    role: FinancialSourceRole
    source_document_id: UUID | None
    source_analysis_result_id: UUID | None
    source_engine_code: ApplicationEngineCode | None

@dataclass(frozen=True)
class ResolvedFinancialOwnerNode:
    engine_code: ApplicationEngineCode
    expected_existing_owner_id: UUID | None
    create_new_owner: bool
    source_mode: FinancialSourceMode
    lineage: tuple[ResolvedFinancialLineageEdge, ...]

@dataclass(frozen=True)
class ResolvedFinancialOwnershipPlan:
    nodes: tuple[ResolvedFinancialOwnerNode, ...]

@dataclass(frozen=True)
class ApplicationTerminalPersistenceRequest:
    scope: ApplicationScopeDTO
    run_result: OrchestrationRunResult
    requested_outputs: tuple[ApplicationEngineCode, ...]
    resume_context: ResumePersistenceContext | None
    financial_ownership_plan: ResolvedFinancialOwnershipPlan
    telemetry: ExecutionTelemetry | None

@dataclass(frozen=True)
class LocalExecutionToken:
    token_id: str
    run_id: str
    scope: ApplicationScopeDTO

@dataclass(frozen=True)
class LocalCancelResult:
    status: CancellationStatus

@dataclass(frozen=True)
class LocalExecutionDiagnostics:
    run_id: str
    correlation_id: str
    phase: str
    cancellation_requested: bool

@dataclass(frozen=True)
class SecurityAuditEventDTO:
    event_type: ApplicationEventType
    occurred_at: datetime
    run_id: str | None
    correlation_id: str
    scope: ApplicationScopeDTO
    actor_id: str
    decision_code: str | None
    application_command_digest: str | None
    safe_attributes: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class SecurityAuditReceiptDTO:
    receipt_id: str
    event_type: ApplicationEventType
    recorded_at: datetime
    audit_record_digest: str

@dataclass(frozen=True)
class ObservabilityEventDTO:
    event_name: str
    correlation_id: str
    safe_attributes: tuple[tuple[str, str], ...]
```

`AuthorizationDecision.granted` ile `revoked` aynı anda true olamaz; deny/revoke decision code'u zorunludur. `LocalCancelResult` yalnız `ACCEPTED`, `ALREADY_REQUESTED`, `NOT_ACTIVE` alt kümesini kullanabilir. Bütün datetime'lar timezone-aware'dır. `AuthorizedResumeSourceView.payloads_materialized=False` iken snapshot `None` olmalıdır; `True` ancak source authorization grant'i required audit receipt'iyle kaydedildikten sonra mümkündür. `OwnerAuditTimes` caller alanlarından assemble edilmez; injected clock ve execution lifecycle tarafından üretilir. Port-internal DTO'lar public response değildir ve ORM nesnesi taşıyamaz.

### 17.1 Durable run scope claim port

```python
class RunScopeClaimPort(Protocol):
    def claim(
        self, run_id: str, scope: ApplicationScopeDTO,
        application_command_digest: str, claimed_at: datetime,
    ) -> RunScopeClaim: ...

    def verify(
        self, run_id: str, scope: ApplicationScopeDTO,
        claim_token: str, expected_version: int,
    ) -> RunScopeClaim: ...

    def finalize(
        self, run_id: str, scope: ApplicationScopeDTO,
        claim_token: str, expected_version: int,
        persisted_run: PersistedRun, finalized_at: datetime,
    ) -> RunScopeClaim: ...

    def load(self, run_id: str) -> RunScopeClaim | None: ...
```

Port durable/transactional adapter gerektirir; in-memory implementation production için yasaktır. `claim` ve `finalize` atomik unique/CAS işlemleridir. Timeout veya unavailable hiçbir zaman “claim yok” olarak yorumlanmaz. Port application transaction sahibi değildir; kendi kısa atomic operation'ının sahibidir. Cancellation claim'i release etmez. Adapter exception'ları yalnız `SCOPE_CLAIM_CONFLICT`, `SCOPE_CLAIM_UNAVAILABLE`, `SCOPE_FINALIZATION_FAILED` mapping'lerine normalize edilir.

### 17.2 Execution gateway

```python
class AnalysisExecutionGatewayPort(Protocol):
    def start(
        self, command: StartAnalysisCommand,
        cancellation_probe: Callable[[], bool] | None = None,
    ) -> ApplicationOutcome[AnalysisCommandResultDTO]: ...

    def resume(
        self, command: ResumeAnalysisCommand,
        cancellation_probe: Callable[[], bool] | None = None,
    ) -> ApplicationOutcome[AnalysisCommandResultDTO]: ...

    def retry(
        self, command: RetryAnalysisCommand,
        cancellation_probe: Callable[[], bool] | None = None,
    ) -> ApplicationOutcome[AnalysisCommandResultDTO]: ...
```

Gateway phased flow'un sahibidir, SQL transaction sahibi değildir. Full command scope zorunludur. Cancellation probe yalnız 5.0A'ya aktarılır. Expected errors outcome'dur; raw exception çıkmaz.

### 17.3 Read port

```python
class AnalysisReadPort(Protocol):
    def get_run_by_id(self, run_id: str, scope: ApplicationScopeDTO) -> InternalRunView | None: ...
    def get_status(self, run_id: str, scope: ApplicationScopeDTO) -> AnalysisRunStatusDTO | None: ...
    def get_result(
        self, run_id: str, scope: ApplicationScopeDTO, *, include_payloads: bool
    ) -> AnalysisResultDTO | None: ...
    def get_execution_detail(
        self, run_id: str, engine_code: ApplicationEngineCode, scope: ApplicationScopeDTO,
        *, include_payload: bool
    ) -> AnalysisExecutionDTO | None: ...
    def list_history(
        self, scope: ApplicationScopeDTO, cursor: str | None, limit: int
    ) -> AnalysisHistoryPageDTO: ...
    def load_scope(self, run_id: str) -> VerifiedApplicationScopeBinding | None: ...
    def load_resume_source(
        self, previous_run_id: str, target_scope: ApplicationScopeDTO,
        *, materialize_payloads: bool
    ) -> AuthorizedResumeSourceView: ...
```

Read port transaction'ı kısa, read-only ve adapter-owned'dır. Scope zorunludur; wrong scope fail-closed, payload authorization öncesi materialization yasaktır. `load_scope`, 5.0B company/period ile finalized `RunScopeClaim` alanlarını karşılaştırır; audit kayıtlarından scope üretmez. Error normalization raw ORM/SQL sızıntısını engeller.

### 17.4 Persistence anti-corruption port

```python
class RunPersistencePort(Protocol):
    def persist_terminal_run(
        self, request: ApplicationTerminalPersistenceRequest
    ) -> PersistedRun: ...

    def build_previous_execution_snapshot(
        self, run_id: str, target_scope: PersistenceRunScope
    ) -> SnapshotLoadResult: ...

    def resolve_financial_ownership_plan(
        self,
        run_result: OrchestrationRunResult,
        source_intents: tuple[FinancialSourceIntentDTO, ...],
        scope: ApplicationScopeDTO,
        audit_times: OwnerAuditTimes,
    ) -> ResolvedFinancialOwnershipPlan: ...

    def resolve_payload_references(
        self, run_id: str, scope: ApplicationScopeDTO,
        *, include_payloads: bool
    ) -> tuple[ApplicationPayloadEnvelopeDTO, ...]: ...
```

Port application core'da 5.0B anti-corruption sınırıdır; SQLAlchemy içermez. `persist_terminal_run` transaction'ı 5.0B edge adapter/repository'sine aittir ve internal planı transaction-local ID'lerle değişmemiş 5.0B owner/binding contract'ına map eder. Resolver yalnız post-result çalışır; failure fail-closed'dur. Snapshot/payload resolution owner/digest/version kurallarını değiştirmez. Cancellation persistence transaction'ını kesmez.

### 17.5 Authorization port

```python
class AuthorizationPort(Protocol):
    def authorize_start(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def authorize_resume(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def authorize_resume_source(
        self, source_run_id: str, target_scope: ApplicationScopeDTO,
        actor: ApplicationAuditContextDTO
    ) -> AuthorizationDecision: ...
    def authorize_read(
        self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO,
        *, include_payload: bool
    ) -> AuthorizationDecision: ...
    def authorize_cancel(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def authorize_retry(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
```

Port DB transaction sahibi değildir; full scope zorunludur. Deny/unavailable fail-closed. Pre-persistence revalidation aynı operation method'u ikinci kez çağırır. Cancellation grant'i yalnız local signal yetkisidir. Provider exception'ı normalized unavailable olur.

### 17.6 Active execution port

```python
class ActiveExecutionPort(Protocol):
    def register(self, run_id: str, scope: ApplicationScopeDTO, correlation_id: str) -> LocalExecutionToken: ...
    def unregister(self, token: LocalExecutionToken) -> None: ...
    def request_cancel(self, run_id: str, scope: ApplicationScopeDTO) -> LocalCancelResult: ...
    def is_active(self, run_id: str, scope: ApplicationScopeDTO) -> bool: ...
    def get_local_diagnostics(self, run_id: str, scope: ApplicationScopeDTO) -> LocalExecutionDiagnostics | None: ...
```

Process-local, transaction'sız ve non-authoritative'dir. Duplicate register execution'ı reddetmez. Failures business correctness'i veya persistence idempotency'sini belirlemez. Scope mismatch fail-closed cancel reddidir; unregister `finally` lifecycle'ındadır.

### 17.7 Security audit ve observability portları

```python
class SecurityAuditPort(Protocol):
    def record_required_event(
        self, event: SecurityAuditEventDTO
    ) -> SecurityAuditReceiptDTO: ...

class ObservabilityPort(Protocol):
    def emit_best_effort_event(self, event: ObservabilityEventDTO) -> None: ...
    def increment_metric(self, name: str, value: int, tags: tuple[tuple[str, str], ...]) -> None: ...
    def record_timing(self, name: str, duration_ms: float, tags: tuple[tuple[str, str], ...]) -> None: ...
```

Security audit required/fail-closed ve transaction dışıdır; receipt yalnız immutable audit event ID/digest döner ve scope ownership yetkisi taşımaz. Observability best-effort/fail-open'dır ve business outcome'u değiştirmez. İkisi aynı adapter/port olamaz. Raw payload/error yasaktır. Post-commit audit failure Bölüm 16 warning politikasına tabidir.

### 17.8 Clock port

```python
class ApplicationClockPort(Protocol):
    def now_audit_time(self) -> datetime: ...
    def resolve_business_time(self, caller_supplied: datetime | None) -> datetime: ...
```

Yalnız audit ve açık business timestamp sağlar; timezone-aware değer döner. Engine fingerprint/determinism, generated result veya elapsed timing'e sızmaz. Caller time varsa policy doğrulanır; yoksa injected clock kullanılır. Transaction/cancellation sahibi değildir.

### 17.9 Port behavioral decision table

| Port/operation | Success | Deny/conflict/integrity | Timeout/unavailable | Retryable | Fail policy | Transaction/cancel |
|---|---|---|---|---:|---|---|
| `authorize_start` | Start target grant | `UNAUTHORIZED` | `AUTHORIZATION_PROVIDER_UNAVAILABLE` | yalnız unavailable: evet | closed | transaction yok; cancellation'dan bağımsız |
| `authorize_resume` | Resume target grant | `UNAUTHORIZED` | provider unavailable | yalnız unavailable: evet | closed | source materialization yapmaz |
| `authorize_resume_source` | previous-run metadata/payload grant | `RESUME_SOURCE_UNAUTHORIZED` | provider unavailable | yalnız unavailable: evet | closed | grant audit'ten önce payload yok |
| `authorize_retry` | Retry target grant | `UNAUTHORIZED` | provider unavailable | yalnız unavailable: evet | closed | original operation invariant'ını değiştirmez |
| pre-persist revalidation | aynı target method ikinci çağrı | deny=`UNAUTHORIZED`; explicit revoke=`AUTHORIZATION_REVOKED` | provider unavailable | yalnız unavailable: evet | closed; persist/payload yok | harcanmış CPU geri alınmaz |
| `authorize_read` | scope + payload level grant | `UNAUTHORIZED` veya masked `NOT_FOUND` | provider unavailable | yalnız unavailable: evet | closed | read-only; materialization grant sonrası |
| `authorize_cancel` | local cancel yetkisi | `UNAUTHORIZED` | provider unavailable | yalnız unavailable: evet | closed | grant terminal/idempotency kararı değildir |
| scope `claim/verify` | exact immutable claim | conflict/mismatch | claim unavailable | yalnız unavailable: evet | closed | kendi kısa atomic CAS işlemi |
| scope `finalize` | terminal tuple atomik bağlanır | wrong tenant/token/tuple kesin ret | finalize failed | evet, exact recovery | closed; DTO yok | DB commit'i rollback etmez |
| read metadata/result/history | authorized scope-qualified DTO/view | missing=`NOT_FOUND`; wrong scope=`SCOPE_MISMATCH` internal/masked public | `PERSISTENCE_UNAVAILABLE` | yalnız unavailable: evet | closed; wrong-scope DTO yok | kısa read-only transaction; cancel etkisiz |
| resume snapshot/payload load | verified 5.0B snapshot/context | invalid chain=`RESUME_SOURCE_INVALID`; digest/owner corruption=`RESUME_SOURCE_CORRUPTED` | `PERSISTENCE_UNAVAILABLE` | yalnız unavailable: evet | closed; clean-start yok | source auth + audit sonrası read |
| financial ownership resolver | complete registry/role plan | missing intent/role/result=`PERSISTENCE_INTEGRITY_ERROR` | I/O yapmaz, timeout yok | hayır | closed | transaction-neutral; cancel etkisiz |
| `persist_terminal_run` | tek terminal commit | fingerprint=`FINGERPRINT_CONFLICT`; diğer unique=`PERSISTENCE_CONFLICT`; invariant=`PERSISTENCE_INTEGRITY_ERROR` | `PERSISTENCE_UNAVAILABLE` | yalnız unavailable: evet | closed | transaction adapter-owned; cancel commit'i kesmez |
| execution gateway | 5.0A terminal result | unexpected boundary=`EXECUTION_FAILED` | application wall-clock timeout üretmez | hayır | closed | yalnız cooperative cancellation probe |
| active execution | local token/result | scope mismatch error outcome | registry outage diagnostics alert | hayır | correctness için fail-open | no transaction; `finally` unregister |
| required security audit (pre/auth) | receipt | sink reject/failure | `SECURITY_AUDIT_FAILED` | evet | closed | execution/persist başlamaz |
| required security audit (post-commit) | receipt | sink failure | mandatory warning | operational retry | business success korunur | scope claim/finalize etkilenmez |
| observability | best-effort | drop/alert | drop/alert | uygulanamaz | open | business outcome/cancel değişmez |
| application clock | timezone-aware audit/business time | invalid caller time=`INVALID_COMMAND`; invalid injected time=`INTERNAL_INVARIANT_BREACH` | remote I/O yasak, timeout yok | hayır | closed for validation | transaction/cancel sahibi değil |

External authorization, scope-claim, persistence ve security-audit adapter'ları deployment-configured finite I/O timeout uygulamak zorundadır; application core wall-clock ölçüp engine'i zorla kesmez. Timeout hiçbir portta deny, not-found veya empty result gibi yorumlanmaz. Expected satırlar `ApplicationOutcome`'a normalize edilir; raw exception çıkmaz. Explicit `RetryAnalysisCommand` yeni run ID gerektirir ve tabloda `retryable=False` olan sonucu otomatik yeniden çalıştırma izni vermez.

---

## 18. Framework Bağımsızlığı

Application package'in transitive import graph'ında FastAPI, Starlette, Pydantic, SQLAlchemy, ORM model veya Alembic bulunamaz. UUID/Decimal/date/datetime, frozen dataclass, Enum ve Protocol kullanılabilir. Future HTTP adapter application outcome'u HTTP'ye map eder; HTTP status application core'da bulunmaz.

---

## 19. State Machine ve Lifecycle

Ephemeral invocation:

```text
RECEIVED -> PREFLIGHTED -> AUTHORIZED -> [SNAPSHOT_READY]
         -> EXECUTING -> REAUTHORIZING -> PERSISTING -> PROJECTING -> RETURNED
```

Her aşama error outcome'a gidebilir. `PERSISTING` öncesi authorization revocation sonucu persistence yoktur. `PERSISTING` commit sonrası `PROJECTING` failure canonical run'ı geri almaz.

Persisted **analysis execution state** yalnız değişmemiş 5.0A terminal status'larıdır. 5.0C queued/running/cancelling/retrying workflow tablosu, durable job state'i veya execution registry eklemez. Ayrı `RunScopeClaim` lifecycle'ı `CLAIMED -> FINALIZED` yalnız immutable run ownership reservation metadata'sıdır; yukarıdaki execution state machine'inin parçası değildir ve execution'ın aktif olduğunu göstermez.

---

## 20. Read/Write Use-Case Ayrımı

Write use-case'leri execution + terminal persistence koordine eder. Query use-case'leri engine çalıştırmaz ve persistence yazmaz. History/status metadata default'tur; payload opt-in ve ayrı authorize edilir. Query-time projection yeni storage owner yaratmaz. Cursor, immutable `(finalized_at, persisted_run_id)` keyset sırasına dayanır.

---

## 21. Concurrency ve Duplicate Request Davranışı

Same-process ve cross-process duplicate çağrılar aynı semantiğe sahiptir: ikisi de execution'a başlayabilir, 5.0B unique `run_id` ve fingerprint/digest kuralları terminal kararı verir. Local registry duplicate'ı reject etmez. Preflight'ta exact persisted command bulunduysa execution yerine canonical read yapılır.

Concurrent cross-scope same-run race'te bir scope commit ederse diğer scope success DTO üretemez. Post-persist scope check zorunludur. Exactly-once execution iddiası yoktur; terminal canonicalization/idempotency vardır.

---

## 22. Fail-Closed Kurallar

Aşağıdakilerde execution/persistence/payload disclosure yapılmaz:

- invalid command/query/schema/enum;
- authorization deny, revocation veya provider outage;
- required security audit failure;
- missing/unverifiable full scope binding;
- wrong-scope existing/returned run;
- run/fingerprint conflict;
- missing/wrong financial source intent veya owner;
- invalid/corrupted/unauthorized resume chain;
- non-finite float, non-string key, unknown prior fact;
- canonical digest/owner/version/fingerprint mismatch;
- DTO projection invariant failure.

Resume/retry hiçbir koşulda clean Start fallback yapmaz. Wrong-scope result hiçbir public success DTO'ya map edilmez.

---

## 23. Determinizm Sınırları

Financial hesaplama, dependency ordering, reuse ve engine fingerprint 5.0A'ya aittir. Canonical payload digest/storage serialization 5.0B'ye aittir. 5.0C yalnız deterministic validation/mapping/application DTO serialization sağlar. Application command digest exact application replay guard'ıdır; 5.0B fingerprint'i değildir.

Audit wall-clock, correlation, timing ve observability business determinism'e katılmaz. `ApplicationClockPort` engine request'in deterministik alanlarını kendiliğinden değiştiremez.

---

## 24. Security Audit ve Observability

Kapalı required security event kümesi:

- `START_REQUESTED`
- `RESUME_REQUESTED`
- `RETRY_REQUESTED`
- `CANCEL_REQUESTED`
- `AUTHORIZATION_GRANTED`
- `AUTHORIZATION_DENIED`
- `SCOPE_MISMATCH_DETECTED`
- `RUN_ID_CONFLICT_DETECTED`
- `RESUME_SOURCE_ACCEPTED`
- `RESUME_SOURCE_REJECTED`
- `TERMINAL_RUN_PERSISTED`
- `RESULT_READ`
- `HISTORY_READ`

Pre-execution request audit yazılamazsa use-case başlamaz ve `SECURITY_AUDIT_FAILED` döner. Her grant/deny kaydı zorunludur; kaydedilemezse devam edilmez. `TERMINAL_RUN_PERSISTED` olayı DB commit ve başarılı scope-claim finalize sonrasında yazılır. Bu post-persistence audit başarısızsa DB commit/finalized claim geri alınmaz; projection başarılıysa success value korunur, mandatory `SECURITY_AUDIT_POST_COMMIT_FAILED` warning eklenir ve operational alert gönderilir. Projection ayrıca başarısızsa ana outcome `DTO_PROJECTION_FAILED` olur; audit failure operational alert olarak korunur ve canonical ownership yine değişmez.

Security audit event sourcing değildir; scope claim, domain state rebuild veya replay kaynağı olamaz. Scope ownership yalnız `RunScopeClaimPort` üzerinden okunur.

Observability yalnız allowlisted engine code/status, phase, duration bucket, result count ve correlation hash taşır. Sink failure fail-open'dır; required security audit'in yerine geçemez.

---

## 25. Security ve Sensitive-Data Sınırları

Raw document bytes, financial payload, auth token/context içeriği, tenant secrets, raw exception, SQL ve stack trace; error, audit, log, metric veya diagnostic'e konulamaz. `authorization_context_reference` opaque ref'tir. IDs yalnız authorization sonrası gerekli DTO'da açılır. Digests public error'a yazılmaz. `repr` testleri sensitive field leakage'ini engeller.

---

## 26. Test Stratejisi

### 26.1 Financial binding

- successful financial result + intent → post-result binding;
- failed/skipped/`record.result is None` → binding yok;
- missing source intent ve wrong existing owner fail-closed;
- mixed BS success / IS failure → yalnız BS binding;
- her iki financial execution failure → binding yok;
- Ratio financial owner ve registry'nin üç financial-owner satırı;
- source role mapping'in gerçek 5.0B enumuyla birebir uyumu;
- mixed BS/IS lineage ve eksik dependency halinde Ratio owner yasağı;
- yeni BS/IS owner ID'lerinin aynı transaction'da Ratio lineage'ına assembly edilmesi ve rollback;
- `PerEngineExecutionRecord.result` ve `EngineResultEnvelope.result` mapping contract testi;
- caller'ın owner table/audit/version assembly veremediği contract testi.

### 26.2 Scope/idempotency ve topology

- same run/same scope/same payload;
- aynı run ile farklı company, period veya tenant;
- same scope/different fingerprint;
- concurrent cross-scope same-run PostgreSQL race;
- cross-tenant scope race; yalnız tek atomic claim winner;
- `RunScopeClaim` unique `run_id`, exact idempotent claim ve different-command conflict;
- wrong-tenant verify/finalize kesin ret;
- wrong-tenant DTO projection'dan önce fail-closed;
- crash-after-terminal-commit / before-finalize recovery ve execution'ın tekrarlanmaması;
- post-commit audit failure'ın finalized claim'i değiştirememesi;
- post-persist returned scope mismatch;
- wrong-scope result'ın hiçbir DTO'ya map edilmemesi;
- same duplicate request same process, simulated cross process ve semantic equality;
- active registry'nin correctness kararı verememesi.

### 26.3 DTO, ports ve outcomes

- tüm public DTO'lar için full field/type/invariant/serialization contract;
- bütün kapalı alanlar için gerçek DTO enum contract ve unknown-value rejection;
- `ResumeAnalysisCommand` exact field/invariant contract;
- `RetryAnalysisCommand` exact field/invariant contract;
- financial vs artifact payload ref, financial serializer version `None`;
- BS/IS full semantic projection;
- Decimal/Enum/tuple/map/date/datetime ve finite-float golden vectors;
- exact port fake implementations ve method signature checks;
- behavioral port contract decision table'ın exhaustive fake/timeout tests;
- `ApplicationOutcome` success/failure XOR;
- exhaustive error mapping ve cancel normal-result modeli;
- transitive FastAPI/Pydantic/SQLAlchemy import yokluğu.

### 26.4 Authorization/audit/recovery

- deny, revocation ve provider unavailable;
- Start/Resume/Retry target authorization ile Resume source authorization'ın ayrılığı;
- her write use-case için pre-persistence authorization revalidation;
- pre-execution audit failure;
- pre-persistence revalidation failure: no persist/no payload;
- post-commit audit failure: success + mandatory warning;
- resume payload authorization ordering;
- terminal commit success + DTO projection failure;
- repeat exact Start reads persisted result, analysis yeniden çalışmaz;
- invalid resume/retry never clean-starts.

---

## 27. Property Test Planı

1. `ApplicationOutcome` XOR invariant'ı.
2. Recursive payload algebra: arbitrary nested tuple/string-map/Decimal/finite float round-trip; invalid key/list/non-finite rejection.
3. Scope'un herhangi tek alanını değiştirmek success'i imkânsız kılar.
4. DTO mapping aynı input için byte-stable application representation üretir.
5. Owner reference XOR ve serializer version conditional invariant'ı.
6. Financial engine status/`record.result` kombinasyonlarında binding yalnız allowed kümede üretilir.
7. Raw exception/secret marker hiçbir public DTO/audit/observability output'una çıkmaz.
8. Command → 5.0A mapping kapalı Any alanlarında type-safe ve deterministic kalır.

---

## 28. PostgreSQL Integration Test Planı

Gerçek PostgreSQL ile:

- phased terminal transaction atomicity;
- successful/mixed/failed financial owner binding satırları;
- Ratio owner'ın newly-created BS/IS owner ID'lerine aynı transaction'da role-correct lineage FK'leri;
- lineage veya terminal insert failure halinde new owner/source satırlarının tamamının rollback'i;
- **zorunlu concurrent idempotent early-return kabul testi:** aynı scope/fingerprint/payload ile iki gerçek PostgreSQL transaction ayrı owner/lineage ID'leri stage eder; winner canonical run'ı commit eder, loser `persist_terminal_run()` erken idempotent dönüşünde rollback-to-savepoint + discard uygular; loser session'da sonradan kasıtlı başka bir commit çalıştırıldıktan sonra dahi loser owner/lineage ID'lerinin bulunmadığı, yalnız winner ID'lerinin canonical executions tarafından referanslandığı doğrulanır;
- wrong existing owner ve owner/digest constraint rejection;
- same run same scope same fingerprint idempotency;
- same run different company/period/tenant ve different fingerprint conflicts;
- concurrent cross-scope same-run race ve loser'ın payload alamaması;
- unique `RunScopeClaim.run_id` üzerinde cross-tenant CAS race;
- wrong-tenant verify/finalize ve wrong-tenant DTO projection rejection;
- terminal commit sonrası finalize timeout recovery;
- scope-claim migration `upgrade -> downgrade -> upgrade`, unique/check/CAS ve gerçek immutable-field UPDATE/DELETE trigger testleri;
- post-persist returned scope mismatch adapter simulation;
- authorized resume snapshot, corrupted owner/digest/chain ve transitive corruption;
- retry-of-resume source invariants;
- history stable second-page keyset cursor;
- terminal commit + projection failure + subsequent idempotent read recovery;
- pre-persist revocation ile sıfır terminal row;
- post-commit audit sink failure ile canonical row'un korunması;
- immutable 5.0B tablolarda regression;
- tam Docker suite `0 failed`, `0 skipped`.

5.0C yalnız additive `analysis_run_scope_claims` migration'ını üretir; 5.0B migration head/table contract'larını değiştirmez. Integration test yeni 5.0C head üzerinde ve ayrıca 5.0B upgrade regression'ıyla çalışır.

---

## 29. Performance Hedefleri

- Application validation/mapping p95: payload materialization hariç 25 ms altında.
- Existing-run preflight scope lookup p95: 50 ms altında yerel PostgreSQL hedefi.
- Metadata status/history query p95: 100 ms altında; cursor query plan index kullanmalı.
- Gateway engine süresi üzerinde transaction tutmamalı.
- Payload projection memory'si resolved payload büyüklüğüyle lineer olmalı; ikinci full copy saklanmamalı.

Bunlar release gate'te ölçülecek hedeflerdir, mevcut başarı iddiası değildir.

---

## 30. Production Readiness Kriterleri

Release için zorunlu:

1. Bütün DTO/port/outcome sözleşmeleri frozen ve versioned implement edilir.
2. Phased coordination ve post-result financial binding testlerle kanıtlanır.
3. Scope pre/post checks ve concurrent cross-scope race yeşildir.
4. Auth revalidation ve required security audit fail-closed çalışır.
5. Post-commit audit/projection recovery davranışı kanıtlanır.
6. Full test suite 0 failed/0 skipped, diff check temizdir.
7. Application import graph framework/ORM bağımsızdır.
8. 5.0A/5.0B public contract regression testleri değişmeden geçer.
9. Architecture Book gerçek implementasyon sonrası ayrı onayla senkronize edilir.

**Design readiness:** `%100` — B1–B6 normatif olarak kapalıdır.

**Runtime Production Readiness:** `%0` — henüz implementation/test yoktur.

**Blocking tasarım bulgusu:** `0`.

---

## 31. Risk Analizi

| Risk | Seviye | Azaltım |
|---|---|---|
| Durable scope-claim store availability'sine bağımlı | Yüksek | PostgreSQL unique/CAS, fail-closed timeout, crash-after-commit finalize recovery; 5.0B schema değişmez |
| Duplicate execution CPU maliyeti | Orta | Bilinçli at-least-once execution; persisted preflight optimization; distributed single-flight future |
| Auth execution sırasında revoke olabilir | Yüksek | Mandatory pre-persist revalidation; CPU maliyetinin geri alınamadığı açık |
| Post-commit projection/audit failure | Yüksek | Canonical commit korunur; recovery query ve warning/alert |
| DTO/engine drift | Yüksek | Explicit closed mapping + golden vectors + upstream contract tests |
| Audit'in yanlışlıkla event source sayılması | Yüksek | Domain rebuild yasağı ve ayrı canonical storage owner |
| Large payload memory pressure | Orta | Payload opt-in, 5.0B owner refs ve bütçe politikası |
| Cancellation'ın hard-stop sanılması | Orta | Cooperative/local-only kapalı status sözleşmesi |

---

## 32. Reddedilen Alternatifler

1. Public command'da `FinancialOwnerBindingDTO`: sonucu görmeden persistence kararı ve phantom owner üretir; reddedildi.
2. 5.0B one-shot service'i mandatory gateway yapmak: post-result binding zamanlamasını sağlamaz; reddedildi.
3. Application-owned fingerprint: 5.0B authority'sini çoğaltır; reddedildi.
4. Local single-flight ile correctness: process topology'ye göre farklı davranır; reddedildi.
5. FastAPI/Pydantic/SQLAlchemy contract'ları: framework/persistence leakage; reddedildi.
6. Engine dataclass'larını public response yapmak: upstream coupling; reddedildi.
7. Pre-execution running/job row: execution progress, worker ownership veya job lifecycle saklayan durable row reddedildi. `RunScopeClaim` bunun istisnası veya örtülü biçimi değildir; yalnız aynı `run_id` için immutable scope ownership reservation'ıdır ve running/progress/attempt bilgisi taşımaz.
8. Resume corruption'da clean Start: integrity hatasını gizler; reddedildi.
9. Retry için same run ID: yeni invocation lineage'ını belirsizleştirir; yeni target run ID seçildi.
10. Required security audit'i best-effort observability ile birleştirmek: security guarantee'i zayıflatır; reddedildi.
11. Post-commit audit failure'da canonical DB rollback: commit sonrası atomik olmayan ve veri kaybettiren davranış; reddedildi.
12. Event sourcing, automatic retry/backoff, distributed lock ve hard-stop cancel: kapsam dışı.

---

## 33. Açık Kararlar ve Future Hardening

### 33.1 Blocking açık kararlar

Yok — `0`. B1–B6 Bölüm 36'da kapatılmıştır.

### 33.2 Bu tasarımda kilitlenen kararlar

- Application contract/schema version `1.0.0`.
- Phased coordination ve post-result owner binding.
- 5.0B authoritative fingerprint; 5.0C full-scope pre/post guard.
- At-least-once synchronous execution, terminal idempotency.
- New target run ID kullanan Resume/Retry.
- Required security audit fail-closed; post-commit audit failure success + mandatory warning.
- Projection failure commit'i geri almaz ve read recovery sağlar.
- Query-time DTO projection; yeni payload owner yok.

### 33.3 Future Hardening — bu milestone'da kodlanmayacak

- distributed single-flight/lock ve exactly-once execution araştırması;
- durable cancellation/job/attempt registry;
- queue, worker, scheduler, batch runner ve automatic retry/backoff;
- public API/Pydantic adapter ve JSON boundary codec;
- security audit sink HA, retention ve reconciliation operasyonları;
- cloud blob orphan reconciliation;
- rate limiting/admission control;
- tenant/operation scope'unun gelecekte canonical persistence modeline taşınmasının ayrı migration tasarımı;
- performance/load/chaos test otomasyonu.

---

## 34. İmplementasyon Adımları

Her adım ayrı kullanıcı onayından sonra test-gated uygulanacaktır:

1. Frozen application contracts, recursive value algebra, closed enums/outcomes; aynı gate'te exact DTO/enum/outcome contract testleri.
2. Exact ports ve framework/ORM transitive import guards; aynı gate'te protocol fake/behavior/import tests.
3. Pure validators ve explicit 5.0A Any mapping adapters; aynı gate'te golden vector ve `EngineResultEnvelope.result` mapping tests.
4. Additive 5.0C `analysis_run_scope_claims` migration/model/repository adapter'ı, `RunScopeClaimPort`, required security audit ve authorization adapters/fakes; claim constraint/immutability/PostgreSQL race testleri aynı gate'te.
5. Phased execution gateway preflight + Start; aynı gate'te same-process/cross-process idempotency tests.
6. Post-result financial binding resolver ve transaction-local Ratio lineage assembly; aynı gate'te registry/role/mixed/new-owner PostgreSQL tests.
7. Resume/Retry snapshot/source authorization akışları; aynı gate'te exact command, corruption ve no-clean-start tests.
8. Pre-persist revalidation, atomic persistence, claim finalize ve post-persist scope check; aynı gate'te timeout/revocation/wrong-tenant/recovery tests.
9. Canonical read/projection ve projection-recovery davranışı; aynı gate'te owner XOR, serializer-version ve post-commit projection tests.
10. Local cooperative cancellation registry; aynı gate'te normal-result/cancel lifecycle tests.
11. Bölüm 26–28 matrisinde kalan coverage boşluğu olmadığının denetimi.
12. Full Docker regression, performance checks ve scope/diff audit.
13. Ayrı onayla Architecture Book sync.

5.0B migration/model değişikliği ve API/router/queue/worker/scheduler/UI adımı yoktur. Yalnız B2'nin zorunlu kıldığı 5.0C-owned additive scope-claim migration/model/repository adapter'ı kapsam içidir; application core'a SQLAlchemy sızamaz.

---

## 35. Architecture Book v1.3.0 Senkronizasyon Planı

Yalnız gerçek implementasyon ve tam Docker doğrulaması sonrasında ayrı onayla:

- version/sistem durumu/test sayıları gerçek sonuçla güncellenir;
- phased Application Layer, post-result financial binding ve contract freeze açıklanır;
- scope-aware idempotency, topology-neutral duplicate semantiği ve local cancellation sınırı eklenir;
- versioned DTO/outcome/error taxonomy ve framework bağımsızlığı kaydedilir;
- required security audit ile best-effort observability ayrımı yazılır;
- authorization revalidation ve projection recovery politikası eklenir;
- API/queue/worker/scheduler/batch/UI/event sourcing'in kapsam dışılığı korunur;
- FINOS'un yalnız geliştirme kod adı olduğu tekrarlanır.

---

## 36. Bağımsız Mimari Denetim Sonrası Revizyon Raporu

| Bulgu | Kök neden | Uygulanan düzeltme | Değişen sözleşme | Eklenen test kategorisi | Durum |
|---|---|---|---|---|---|
| B1 — Financial owner binding zamanlaması | Caller sonucu görmeden persistence owner assembly belirliyordu; Ratio/new-owner lineage eksikti | Public binding kaldırıldı; üç financial engine, gerçek source rolleri ve transaction-local Ratio lineage assembly ile A–I phased flow zorunlu oldu | Commands, ownership plan, persistence adapter | success/failure/mixed/Ratio/role/new-owner rollback | KAPALI |
| B2 — Scope-aware idempotency | 5.0B fingerprint doğru olsa da tenant/operation scope'u application dönüşünde bağlanmıyordu; audit yanlışlıkla scope sahibi yapılmıştı | Audit ownership'ten çıkarıldı; additive durable `RunScopeClaim` unique/CAS claim-verify-finalize lifecycle'ı eklendi | `ApplicationScopeDTO`, `RunScopeClaimPort`, read/preflight/outcome | company/period/tenant mismatch, claim race, wrong finalize/projection | KAPALI |
| B3 — Local single-flight | Process-local registry correctness/idempotency sanılıyordu | Registry yalnız cancel/diagnostics/observability; duplicate aynı ve farklı process'te aynı semantik | `ActiveExecutionPort`, cancellation statuses | same-process/cross-process semantic equality | KAPALI |
| B4 — Eksik public DTO'lar | Alan, tip, owner ve serializer eksenleri normatif değildi | Exact frozen DTO'lar, recursive algebra, typed report/prior/render mapping, financial/artifact XOR tanımlandı | Commands, queries, payload/result DTO'ları | full-field, golden vectors, BS/IS lossless projection | KAPALI |
| B5 — Port/outcome/error belirsizliği | Method signature, expected failure ve cancel modeli açık değildi | Exact ports, immutable `ApplicationOutcome[T]`, tek cancel modeli ve exhaustive mapping kilitlendi | Tüm ports/outcomes/error enum | port fakes, XOR, exhaustive mapping, recovery | KAPALI |
| B6 — Audit/observability karışımı | Security kararları best-effort telemetry ile aynı failure semantiğindeydi | Required `SecurityAuditPort`, iki auth checkpoint ve post-commit warning politikası ayrıldı | Audit events, authorization lifecycle, warnings | pre-audit/revalidation/post-commit/order tests | KAPALI |

---

## Kapanış

Bu revizyon conceptual architecture'ı uygulanabilir contract, sıra, failure ve recovery kurallarına dönüştürür. 5.0A/5.0B public contract'ları değişmez; yeni hesaplama veya payload owner, API ya da background execution eklenmez. Ayrı 5.0C scope claim store'u yalnız run ownership metadata'sının sahibidir.

**Tasarım verdict'i:** `READY FOR IMPLEMENTATION APPROVAL`.

**Runtime Production Readiness:** `NOT READY — %0; implementation ve test yok`.

**Blocking açık karar:** `0`.

İmplementasyona geçmek için ayrıca açık kullanıcı onayı zorunludur.

---

## Revizyon 3 Kapanış Raporu

| Blocking bulgu | Kök-neden düzeltmesi | Durum |
|---|---|---|
| B1 — Financial owner kapsamı | Ownership registry'nin üç financial engine'i, gerçek 5.0B source rolleri ve aynı terminal transaction'da Ratio → yeni BS/IS owner lineage assembly tanımlandı | KAPALI |
| B2 — Scope claim | Security audit ownership'ten çıkarıldı; durable PostgreSQL `RunScopeClaim` için atomic claim/verify/finalize, unique `run_id`, CAS ve wrong-tenant fail-closed kuralları kilitlendi | KAPALI |
| B3 — 5.0A gerçek alanları | Bütün engine-result akışı `PerEngineExecutionRecord.result` ve `EngineResultEnvelope.result` ile hizalandı | KAPALI |
| B4 — Exact DTO tipleri | Public closed alanlar gerçek enum oldu; Start/Resume/Retry ayrı tam field contract'larına kavuştu | KAPALI |
| B5 — Port behavior | Resume target authorization, revalidation, timeout, retryability, conflict, execution ve cancel kararları exhaustive decision table ile kilitlendi | KAPALI |
| B6 — Test matrisi | Ratio/role/new-owner lineage, scope CAS yarışları, exact DTO/enum, revalidation, port behavior ve envelope mapping testleri zorunlu oldu | KAPALI |

- Kalan blocking bulgu: **0**.
- Future hardening: distributed single-flight/exactly-once, durable cancellation/job attempts, queue/worker/scheduler/batch, automatic retry/backoff, public API adapter, claim-store HA/operational reconciliation, rate limiting ve load/chaos otomasyonu.
- Design Readiness: **%100**.
- Runtime Production Readiness: **%0** — implementation ve doğrulama henüz yapılmadı.
- Implementasyona hazır: **Evet; ayrıca açık kullanıcı onayı zorunludur**.
