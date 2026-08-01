# Milestone 5.0B — Orchestration Persistence & Recovery Foundation

| | |
|---|---|
| Doküman durumu | **TASARIM — BAĞIMSIZ MİMARİ DENETİM GEÇTİ; İMPLEMENTASYON ONAYI BEKLİYOR** |
| Milestone | **5.0B — Orchestration Persistence & Recovery Foundation** |
| Kapsam | Yalnızca persistence, immutable execution history, fingerprint/reuse snapshot persistence ve resume/recovery tasarımı |
| Ana otorite | `backend/docs/FINOS_ARCHITECTURE_BOOK.md` v1.1.0 |
| Değiştirilmeyen sözleşme | Milestone 5.0A Analysis Orchestrator public contract'larının tamamı |
| Kesin kapsam dışı | Kod, model, migration, repository, API, test, queue/worker, scheduler ve implementasyon |

---

## 0. Karar Özeti ve Normatif Dil

Bu dokümandaki **ZORUNLU**, **YASAK**, **YALNIZCA** ve **ASLA** ifadeleri bağlayıcıdır. Milestone 5.0B, Milestone 5.0A'nın saf Analysis Orchestrator katmanını değiştirmez; onun çevresine, farklı çağıranlar tarafından yeniden kullanılabilecek bir persistence/recovery sınırı tasarlar.

Bağlayıcı kararlar:

1. **Event sourcing kullanılmayacaktır.** Immutable audit kayıtları tutulur; event stream, aggregate reconstruction ve event replay yapılmaz.
2. Her veri/payload'ın tek bir storage owner'ı vardır. Aynı payload iki tabloda saklanmaz.
3. Küçük yapısal metadata JSONB olabilir; büyük sonuçlar artifact olarak yönetilir. Boyut sınıfı değiştiğinde şema migration'ı gerekmeyecek bir storage locator modeli kullanılır.
4. Analysis Orchestrator saf, deterministik ve SQLAlchemy'den bağımsız kalır.
5. Persistence Adapter; REST API, Queue Worker, CLI, Batch Runner ve Scheduler tarafından ortak kullanılabilecek application boundary'dir.
6. Milestone 5.0A public dataclass, enum, fonksiyon imzası, fingerprint, reuse, status ve determinism sözleşmeleri değiştirilmez.
7. Architecture Book v1.1.0 ile çelişen hiçbir karar geçerli değildir.

---

## 1. Amaç

Milestone 5.0B'nin amacı, bir orchestration run'ının:

- kimliğini ve immutable terminal sonucunu kalıcılaştırmak,
- motor bazlı execution history'sini eksiksiz saklamak,
- güvenli reuse için gerekli fingerprint ve sürüm kanıtlarını korumak,
- `PreviousExecutionSnapshot` sözleşmesini DB kayıtlarından yeniden oluşturmak,
- crash/retry ve at-least-once çağrı koşullarında idempotent persistence sağlamak,
- gelecekteki farklı execution giriş noktalarına ortak bir adapter sunmak

için implementasyona hazır bir mimari tanımlamaktır.

Bu milestone bir workflow engine, job scheduler veya event platformu değildir.

---

## 2. Değişmez Mimari Sınırlar

### 2.1 Milestone 5.0A public contract freeze

Aşağıdaki mevcut sözleşmeler **değiştirilmeyecektir**:

- `run_orchestration(request, *, cancellation_probe=None, timing_probe=None)` imzası ve dönüş modeli,
- `OrchestrationRunRequest`,
- `OrchestrationRunResult`,
- `PerEngineExecutionRecord`,
- `PreviousExecutionSnapshot` ve `PreviousEngineSnapshot`,
- `EngineExecutionStatus`, `RunStatus` ve `OrchestrationErrorCategory`,
- `ORCHESTRATION_SCHEMA_VERSION`, `ORCHESTRATION_MODEL_VERSION`, `EXECUTION_PLAN_VERSION` ve `FINGERPRINT_SCHEMA_VERSION`,
- canonical JSON + SHA-256 fingerprint algoritması,
- aynı `run_id` + farklı `request_fingerprint` kesin ret kuralı,
- fingerprint + engine schema/model version + transitif upstream geçerliliğine dayalı reuse kuralı,
- `engine_records` tek source-of-truth ilkesi,
- sıralı execution ve mevcut dependency DAG davranışı,
- business-payload ve full-result determinism ayrımı.

5.0B katmanı 5.0A tiplerini **tüketebilir ve yeniden oluşturabilir**; engine/orchestrator paketine persistence alanı, ORM annotation'ı, session, repository veya storage locator ekleyemez.

### 2.2 Engine katmanı yasağı

`app/engines/**`:

- SQLAlchemy/Alembic import etmez,
- DB/session/transaction açmaz,
- repository veya persistence adapter bilmez,
- blob/object storage bilmez,
- HTTP, queue veya scheduler bilmez,
- persistence amacıyla saat/UUID üretmez,
- result payload'ını storage formatına dönüştürmez.

Bağımlılık yönü her zaman dış katmandan içeri doğrudur:

```text
REST API / Queue Worker / CLI / Batch Runner / Scheduler
                         |
                         v
       Orchestration Persistence Application Service
              /                         \
             v                           v
Pure Analysis Orchestrator        Persistence Ports
                                        |
                                        v
                              PostgreSQL / Blob Adapter
```

Engine katmanından bu diyagramın üst veya sağ tarafına doğru hiçbir import yolu kurulamaz.

---

## 3. Kapsam

### 3.1 Kapsam içi

- orchestration run identity ve immutable terminal-result persistence,
- immutable terminal run kaydı,
- motor bazlı immutable execution history,
- run-level warnings, structured errors ve execution provenance,
- request/engine fingerprint ve version inventory persistence,
- result artifact metadata ve payload ownership,
- önceki run'dan `PreviousExecutionSnapshot` materialization,
- resume lineage,
- at-least-once koşullarında idempotent create/finalize davranışı,
- transaction, constraint ve index tasarımı,
- payload size/storage-tier politikası,
- retention için genişleme noktaları; retention uygulaması değil,
- gelecekte uygulanacak repository/adapter portlarının davranış sözleşmesi,
- implementasyon aşamasının test ve kabul planı.

### 3.2 Kapsam dışı

- REST endpoint ve Pydantic API şeması,
- queue, worker, scheduler ve background job,
- CLI veya batch runner implementasyonu,
- otomatik retry/backoff,
- distributed lock/lease,
- engine paralelliği, timeout veya çalışan engine'i zorla kesme,
- tenant authorization,
- çok şirketli batch orchestration,
- UI/frontend,
- event sourcing, event bus, event replay veya CQRS read model,
- artifact retention/purge worker'ı,
- production cloud object-storage provider seçimi/entegrasyonu (provider-neutral port ve durable filesystem reference adapter kapsam içidir),
- mevcut engine hesaplama veya 5.0A orchestrator kodunda değişiklik.

---

## 4. Event Sourcing Kullanılmaması

### 4.1 Karar

Sistem **event-sourced değildir**. Run ve engine execution kayıtları append-only audit kanıtlarıdır; domain state bu kayıtlardan event replay ile yeniden üretilmez.

### 4.2 Saklanan gerçekler

- Bir run için tek bir identity/header kaydı bulunur.
- Run'ın terminal sonucu immutable finalization ile kaydedilir.
- Her engine execution sonucu bir immutable audit satırıdır.
- Resume ilişkisi, yeni run'dan seçilen önceki run'a açık bir lineage referansıdır.
- History sorguları doğrudan bu kayıtlardan yapılır; event projection üretilmez.

### 4.3 Yasaklanan desenler

- `events` adlı genel amaçlı append-only domain stream,
- sequence number üzerinden aggregate replay,
- run state'ini event listesinden yeniden kurma,
- event upcaster zinciri,
- projection/checkpoint altyapısı,
- “source of truth event stream, tablolar yalnız projection” yaklaşımı.

Audit immutability, event sourcing anlamına gelmez. Bu ayrım implementasyon dokümantasyonunda ve adlandırmada korunmalıdır.

---

## 5. Kavramsal Veri Modeli

Bu bölüm tablo isimlerini implementasyon sözleşmesi olarak kilitlemez; brand-independent önerilen isimleri ve sorumlulukları tanımlar.

### 5.1 `orchestration_runs`

Bir run'ın tek kimlik ve immutable terminal-result sahibidir.

Önerilen alan grupları:

- internal UUID primary key,
- dışarıdan verilen `run_id` — global unique,
- `request_fingerprint`,
- `terminal_content_digest`,
- nullable `correlation_id`,
- çağıranın sağladığı nullable `generated_at`,
- zorunlu company/period scope referansları,
- requested output codes,
- run status,
- orchestration schema/model version,
- execution plan version,
- fingerprint schema version,
- previous/resume source run FK,
- `finalized_at`,
- DB audit timestamps.

`run_id` tek başına UNIQUE olmalıdır. Böylece aynı run kimliğiyle farklı fingerprint taşıyan ikinci bir kayıt fiziksel olarak mümkün olmaz. Persistence yalnız tamamlanmış bir 5.0A çağrısının döndürdüğü authoritative `OrchestrationRunResult.request_fingerprint` ile yapılır. Adapter 5.0A'nın private fingerprint fonksiyonuna bağlanmaz ve algoritmayı kopyalamaz. Adapter davranışı:

- aynı `run_id` + aynı fingerprint: idempotent mevcut kaydı döndür,
- aynı `run_id` + farklı fingerprint: kesin conflict,
- yeni `run_id`: terminal sonucu atomik olarak insert et.

`generated_at`, 5.0A'nın çağıran tarafından sağlanan iş alanıdır. `finalized_at` ise persistence audit zamanıdır; birbirlerinin yerine kullanılamaz.

`terminal_content_digest`, persistence idempotency kanıtıdır; 5.0A request/engine fingerprint'lerinin yerine geçmez. SHA-256, canonical JSON projection üzerinde hesaplanır. Projection şunları kapsar: run/correlation/generated-at değerleri, authoritative request fingerprint, run status, requested outputs, orchestration/execution versions, ordered engine execution metadata, her result owner'ın canonical content digest'i, warnings, structured errors ve input version inventory. DB UUID/FK değerleri, physical blob locator, DB audit timestamps, telemetry ve storage tier projection'a girmez. Digest'in tek sahibi `orchestration_runs.terminal_content_digest` alanıdır; artifact relocation digest'i değiştirmez.

### 5.2 `orchestration_engine_executions`

Her run içindeki engine record'un tek execution-history sahibidir.

Önerilen alan grupları:

- internal UUID primary key,
- run FK,
- `engine_code`,
- deterministik `execution_ordinal`,
- execution status,
- nullable inner status,
- dependency engine code listesi veya normalleştirilmiş, yalnız metadata niteliğinde representation,
- engine schema/model versions,
- input fingerprint ve fingerprint schema version,
- result kind,
- nullable artifact FK,
- nullable `FinancialAnalysisResult` FK,
- reuse source engine-execution FK,
- immutable creation audit zamanı.

Her run/engine code çifti UNIQUE olmalıdır. `execution_ordinal` da run içinde UNIQUE olmalıdır. `REUSED` kayıt, payload'ı kopyalamaz; reuse kaynağındaki artifact'a referans verir ve `reused_from_engine_execution_id` taşır.

Sonuç sahibi iki olasılıktan en fazla biridir: orchestration artifact veya mevcut `FinancialAnalysisResult`. İki nullable owner FK arasında XOR/at-most-one constraint bulunur. `result_kind` sonuç beklediği halde iki FK de boşsa bunun status ile uyumu ayrıca zorlanır. Polymorphic bir string locator, DB foreign key garantisinin yerine kullanılamaz.

Result-kind ownership mapping bağlayıcıdır:

| Engine code | Result owner | Owner subtype |
|---|---|---|
| `FS_BALANCE_SHEET` | `financial_analysis_results` | `AnalysisType.BALANCE_SHEET` |
| `FS_INCOME_STATEMENT` | `financial_analysis_results` | `AnalysisType.INCOME_STATEMENT` |
| `RATIO` | `financial_analysis_results` | `AnalysisType.FINANCIAL_RATIOS` |
| `BENCHMARK` | `orchestration_artifacts` | versioned JSON artifact |
| `HEALTH_SCORE` | `orchestration_artifacts` | versioned JSON artifact |
| `CREDIT_SCORE` | `orchestration_artifacts` | versioned JSON artifact |
| `RECOMMENDATION` | `orchestration_artifacts` | versioned JSON artifact |
| `EXECUTIVE_REPORT` | `orchestration_artifacts` | versioned JSON/external artifact |
| `DASHBOARD` | `orchestration_artifacts` | versioned JSON/external artifact |
| `RENDER_CONTRACT` | `orchestration_artifacts` | versioned JSON/external artifact |

Persistence katmanındaki statik, brand-independent result-ownership/codec registry bu tabloyu uygular. Registry engine dispatch değildir, engine paketinde bulunmaz ve callable import path/string reflection taşımaz. Bir engine code için owner değiştirmek veri migration'ı gerektiren açık mimari revizyondur.

### 5.3 `orchestration_artifacts`

`FinancialAnalysisResult` tarafından sahiplenmeyen orchestration result payload'larının tek sahibidir. Inline JSONB ve external blob aynı logical artifact modelinin iki storage tier'ıdır.

Önerilen alan grupları:

- immutable artifact UUID,
- canonical content digest (`sha256`),
- artifact kind/result kind,
- serializer format ve serializer schema version,
- media type,
- byte size,
- storage backend enum: `inline_jsonb` veya `external_blob`,
- inline JSON-codec payload JSONB veya external locator — XOR,
- external object checksum/etag metadata'sı,
- creation audit zamanı.

Storage backend değişimi, engine execution FK'sini veya snapshot sözleşmesini değiştirmez. Canonical artifact row ve locator finalized olduktan sonra immutable'dır. Fiziksel tier relocation gerekiyorsa yeni bir physical-object/location kaydı oluşturulur ve ayrı, atomik bir locator-indirection pointer'ı compare-and-swap ile değiştirilir; artifact digest, logical artifact ID ve audit geçmişi korunur. Bu taşıma history/event replay değildir.

### 5.4 Run-level owned metadata

Run-level warnings ve input version inventory küçük/bounded JSONB kolonları olarak `orchestration_runs` tarafından sahiplenilir. Requested outputs da aynı run owner üzerinde typed JSON array olarak saklanır. Tüm alanlar allowlist ile serialize edilir; full request dump edilmez.

`ExecutionProvenance.engine_call_sequence`, `reused_engine_codes` ve `skipped_engine_codes` ayrıca saklanmaz. Bunların canonical owner'ı `orchestration_engine_executions.execution_ordinal/status` kayıtlarıdır; history ve `OrchestrationRunResult` materialization sırasında deterministik olarak türetilir. `execution_plan_version` run owner'da kalır.

### 5.5 `orchestration_errors`

Run-level ve engine-level structured error kayıtlarının tek sahibidir:

- internal UUID primary key,
- zorunlu run FK,
- nullable engine execution FK,
- error ordinal,
- kapalı persistence/orchestration error category value,
- nullable engine code,
- sanitize edilmiş message,
- allowlist edilmiş nullable original exception type.

Engine execution FK doluysa hata engine-level, boşsa run-level'dır. Aynı hata ayrıca run JSONB veya execution kolonlarında tutulmaz. 5.0A sonucu yeniden oluşturulurken run ve engine ilişkileri üzerinden materialize edilir.

---

## 6. Storage Ownership Matrix

| Veri yapısı / payload | Tek storage owner | Referans verenler | Yasaklanan duplicate |
|---|---|---|---|
| Run identity, request fingerprint, run status ve orchestration versions | `orchestration_runs` | API/worker/CLI adapter sonuçları | Aynı alanların engine execution veya generic JSON result içine kopyalanması |
| Requested outputs | `orchestration_runs.requested_outputs_json` | History/result materializer | Tam request veya run-options JSON dump'ı |
| `PerEngineExecutionRecord` metadata'sı | `orchestration_engine_executions` | Run history ve snapshot builder | Aynı execution record'un run JSONB içine gömülmesi |
| Orchestration'a özgü engine result payload'ı | `orchestration_artifacts` | Engine execution FK'leri | Execution tablosunda ikinci JSONB kopyası |
| BS/IS/Ratio result payload'ları | `financial_analysis_results` | Execution'ın doğrudan `financial_analysis_result_id` FK'si | Aynı payload'ın `orchestration_artifacts` içine kopyalanması |
| Mevcut analiz source provenance | `financial_analysis_result_sources` | Financial result/history sorguları | Orchestration provenance içinde belge/analiz kaynak listesinin tekrarı |
| Reused result payload | İlk canonical artifact veya mevcut financial analysis result owner'ı | Yeni execution'ın source FK'si | Her resume run'ında payload kopyası |
| Structured error | `orchestration_errors` | Run/engine history projection | Raw exception/stack trace veya aynı hatanın JSON/engine kolon kopyası |
| Warnings | `orchestration_runs.warnings_json` | Run read model | Artifact payload içine tekrar gömme |
| Input version inventory | `orchestration_runs.input_version_inventory_json` | Run result materializer | Artifact veya execution satırlarında kopya |
| Execution provenance/call sequence/reused/skipped listeleri | `orchestration_engine_executions` ordinal ve status alanları | Audit/history tarafından türetilir | Ayrı provenance JSON/tablosu |
| Fingerprint | Kullanıldığı seviyedeki owner: request için run, engine input için execution | Snapshot/reuse validator | Artifact payload içine fingerprint kopyası |
| Resume lineage | Yeni run üzerindeki previous run FK; engine reuse lineage execution FK | History ve snapshot builder | Ayrı genel-purpose event/audit stream |
| External blob bytes | Blob/object store | `orchestration_artifacts.external_locator` | DB JSONB veya bytea içinde ikinci kopya |

### 6.1 Tek sahiplik kuralı

Bir payload için **bir canonical owner** vardır. Diğer kayıtlar yalnız stable ID/FK ve doğrulama digest'i taşır. Read modelleri çalışma anında join/materialization ile üretilir; kalıcı duplicate read model oluşturulmaz.

### 6.2 Mevcut `FinancialAnalysisResult` ile sınır

`FinancialAnalysisResult`, balance-sheet, income-statement ve financial-ratio payload'larının sahibidir. Bu üç orchestration engine execution için persistence application service uygun `FinancialAnalysisResult` owner kaydını oluşturur veya canonical mevcut kaydı referanslar; yeni artifact payload oluşturmaz.

Diğer yedi engine output'u `orchestration_artifacts` tarafından sahiplenilir. Aynı logical payload'ın hem `financial_analysis_results.result_json` hem `orchestration_artifacts.inline_payload` içinde tutulması yasaktır.

Bu eşleme Bölüm 5.2'deki kapalı registry ile uygulanır; runtime string-dispatch engine katmanına eklenemez.

---

## 7. Payload Size Policy

### 7.1 İlkeler

- JSONB, küçük ve orta boy yapısal payload içindir; sınırsız artifact deposu değildir.
- Ham belge bytes, PDF/DOCX, image, render çıktısı ve büyük dashboard/report payload'ı JSONB'ye yazılmaz.
- Fiziksel storage kararı engine veya orchestrator tarafından verilmez; persistence artifact writer verir.
- Storage tier seçimi sonucu semantik olarak değiştirmez.
- Raw input document bytes hiçbir orchestration tablosuna veya fingerprint kaydına yazılmaz.

### 7.2 Normatif eşikler

İlk implementasyon için önerilen varsayılanlar:

- canonical JSON-codec payload `<= 256 KiB`: `inline_jsonb` kullanılabilir,
- `> 256 KiB`: `external_blob` zorunlu,
- `>= 128 KiB`: gözlemlenebilirlik warning metriği üretilir; payload yine 256 KiB'ye kadar inline kalabilir,
- tek run'ın toplam inline artifact bütçesi `<= 1 MiB`,
- sık sorgulanan indekslenebilir metadata payload'dan ayrılır ve bounded kolonlarda tutulur.

Eşikler configuration'dır; DB schema veya engine contract değildir. Eşik değişikliği migration gerektirmez.

### 7.3 Büyük payload stratejisi

`orchestration_artifacts` logical identity'yi storage backend'den ayırır:

```text
artifact_id
  +-- inline_jsonb   -> inline JSON-codec payload
  `-- external_blob  -> provider-neutral external_locator + digest + byte_size
```

PDF, render edilmiş rapor, büyük dashboard snapshot veya gelecekte boyutu büyüyen herhangi bir result kind, aynı artifact ID/FK düzenini kullanır. Yeni bir payload türü için engine execution tablosuna kolon eklemek veya tablo değiştirmek gerekmez.

`external_locator` provider-neutral olmalı; bucket/provider marka adı DB schema, API contract veya engine tiplerine gömülmemelidir. Signed URL kalıcılaştırılmaz; gerektiğinde dış katmanda kısa ömürlü üretilir.

5.0B'nin gelecekteki implementasyon kapsamına provider-neutral `BlobStorePort` ve durable, configured-volume kullanan filesystem reference adapter dahildir. Bu reference adapter staging dosyasını aynı filesystem üzerinde atomik rename ile yayımlar ve Docker/PostgreSQL integration testlerinde büyük payload yolunu doğrular. Cloud object-store adapter seçimi sonraki deployment milestone'una kalır. Böylece `>256 KiB` sonuçlar 5.0B'de finalize edilebilir; external blob davranışı kağıt üzerinde kalan bir feature değildir.

### 7.4 Atomiklik ve blob yazımı

PostgreSQL ile external blob tek ACID transaction paylaşamaz. Bu nedenle:

1. payload canonical serialize edilir ve digest hesaplanır,
2. blob, run-scoped staging key'e yazılır,
3. storage adapter bytes'ı yeniden okuyup digest/size doğrular,
4. verified staging object, content-addressed final key'e idempotent biçimde publish edilir (`READY`),
5. DB transaction yalnız `READY` final locator'ı artifact owner'a bağlar ve run'ı terminal olarak insert eder,
6. DB commit başarısızsa referanssız final blob orphan reconciliation adayıdır,
7. DB hiçbir zaman staging, doğrulanmamış veya tamamlanmamış blob'u terminal artifact olarak göstermez.

Cleanup worker implementasyonu kapsam dışıdır; ancak artifact state/metadata ileride orphan reconciliation'a izin vermelidir.

Physical object state'i kapalıdır: `STAGED`, `READY`, `QUARANTINED`. Yalnız `READY` object locator bir finalized artifact tarafından referanslanabilir. Idempotency key canonical digest + byte size + serializer schema version'dan türetilir. Locator relocation, yeni `READY` object oluşturup digest'i doğruladıktan sonra mutable indirection kaydını expected-current-locator compare-and-swap ile değiştirir; eski object retention süresi dolmadan silinmez.

### 7.5 Serileştirme

- Artifact serializer sürümlü ve deterministik olmalıdır.
- Digest canonical serialized bytes üzerinden hesaplanır.
- Python pickle yasaktır.
- Arbitrary class/module path persistence yasaktır.
- `Any` taşıyan 5.0A result_ref, adapter sınırında izinli, sürümlü bir serialized representation veya mevcut owner FK'sine dönüştürülür.
- Deserialize edilen result, beklenen `result_kind` ve serializer schema version ile doğrulanmadan `PreviousEngineSnapshot.result_ref` içine konulamaz.

---

## 8. Future Adapter Boundary

### 8.1 Katmanlar

Önerilen sınır üç parçadır:

1. **Application service:** execute, persist terminal result, load history ve build snapshot use-case'lerini koordine eder.
2. **Persistence ports:** framework bağımsız davranış arayüzleri; run store, execution store, artifact store ve snapshot reader.
3. **Adapters:** SQLAlchemy/PostgreSQL ve gelecekteki blob provider implementasyonları.

REST API, Queue Worker, CLI, Batch Runner ve Scheduler yalnız application service'i çağırır. Birbirlerine veya doğrudan ORM modellerine bağımlı olmazlar.

### 8.2 Kavramsal port sözleşmeleri

İsimler implementasyon aşamasında kesinleştirilecektir; davranışlar bağlayıcıdır:

- `load_run(run_id) -> PersistedRun | None`
- `persist_terminal_run(command: PersistTerminalRunCommand) -> PersistedRun`
- `store_owned_artifact(result_kind, payload) -> ArtifactRef`
- `load_owned_artifact(ref) -> validated payload`
- `build_previous_execution_snapshot(run_id, target_request_context) -> PreviousExecutionSnapshot`
- `list_run_history(scope, cursor, limit) -> page`

Portlar engine katmanında tanımlanmaz. ORM entity'leri port sınırından dışarı sızmaz.

### 8.3 Persistence-owned command ve binding'ler

5.0A result nesnesi persistence lineage ve source-owner kimliklerini taşımaz; bu bilinçli contract freeze nedeniyle değiştirilmez. Application katmanına ait immutable `PersistTerminalRunCommand` şu bileşenleri taşır:

- zorunlu `PersistenceRunScope(company_id, period_id)`,
- değişmeden alınmış `OrchestrationRunResult`,
- değişmeden alınmış `requested_outputs: tuple[EngineCode, ...]`,
- nullable `ResumePersistenceContext`,
- BS/IS/Ratio için `FinancialResultOwnerBinding` tuple'ı,
- opsiyonel, non-authoritative telemetry.

`ResumePersistenceContext`, snapshot builder'ın `PreviousExecutionSnapshot` ile birlikte döndürdüğü process-local persistence context'tir:

- canonical previous persisted run ID,
- `previous_run_id` business değeri,
- previous run scope,
- her snapshot engine code'u için source engine-execution DB ID'si,
- source result-owner FK ve canonical digest.

`requested_outputs`, çağıranın oluşturduğu değişmez `OrchestrationRunRequest.requested_outputs` tuple'ından command'a aynen kopyalanır; full request veya raw engine input taşınmaz. Persist katmanı mevcut execution-plan kurallarıyla requested-output dependency closure'ını hesaplar ve bunun ordered `OrchestrationRunResult.engine_records` engine-code kümesiyle birebir eşleşmesini zorunlu kılar. Boş, duplicate, bilinmeyen veya result kayıtlarıyla uyuşmayan requested outputs tüm persist'i reddeder. Bu alan engine records'tan tersine tahmin edilmez ve request fingerprint yeniden hesaplanmaz.

Application service aynı context'in snapshot bölümünü değişmeden `OrchestrationRunRequest.previous_execution_snapshot` alanına verir; persistence bölümünü command'a taşır. Persist sırasında:

- result içindeki her `REUSED` engine için tam bir source binding zorunludur,
- source execution aynı previous run/scope'a ait ve finalized olmalıdır,
- engine code, input fingerprint, fingerprint schema version ve engine versions result kaydıyla eşleşmelidir,
- non-`REUSED` engine için source binding yasaktır,
- result reuse provenance ile context arasında fark varsa tüm persist reddedilir.

`FinancialResultOwnerBinding`, `FS_BALANCE_SHEET`, `FS_INCOME_STATEMENT` ve `RATIO` için kapalı bir bağdır. İki moddan tam biri kullanılır:

1. `existing_owner`: aynı company/period ve doğru `AnalysisType` taşıyan mevcut `FinancialAnalysisResult` ID'si; canonical payload digest'i engine result digest'iyle eşleşmelidir.
2. `create_owner`: doğru `AnalysisType`, source mode, nullable/required document ID, engine version, started/completed audit zamanları ve tam `FinancialAnalysisResultSource` binding tuple'ı.

`create_owner` kaynak binding'leri gerçek document/analysis UUID'leri ve rollerini taşır. Adapter mevcut composite FK, direct-document check, XOR source ve role/source kurallarını aynen uygular. Binding scope ile çelişirse, direct-document için document eksikse, derived provenance eksikse veya result digest uyuşmazsa persist fail-closed reddedilir. Bu metadata 5.0A engine sonucundan tahmin edilmez; trusted caller/application input provenance context'inden gelir. Üç finansal engine sonucu payload içeriyorsa ilgili owner binding zorunludur; sonuç yoksa binding yasaktır.

### 8.4 Application service akışı

```text
Caller
  -> provide trusted, mandatory company/period PersistenceRunScope
  -> optional build_previous_execution_snapshot(previous_run_id)
     -> retain paired ResumePersistenceContext
  -> construct unchanged OrchestrationRunRequest
  -> call unchanged run_orchestration(...)
  -> validate returned run_id/fingerprint/contracts
  -> construct PersistTerminalRunCommand with scope, exact requested outputs, resume and financial-owner bindings
  -> persist terminal run + execution history + artifact references atomically
     -> same run_id / same authoritative result => return idempotently
     -> same run_id / different fingerprint or terminal content => reject
  -> return persisted projection
```

Bu akış bilerek pre-execution reservation yapmaz. Böylece persistence katmanı, 5.0A'nın private `_compute_request_fingerprint` fonksiyonunu çağırmaz veya fingerprint algoritmasını kopyalamaz. Crash orchestrator dönüşünden önce/DB commit'ten önce olursa kalıcı run oluşmaz; at-least-once caller aynı request'i yeniden çalıştırabilir. Duplicate execution mümkündür, fakat duplicate veya çelişkili terminal persistence mümkün değildir.

`cancellation_probe` ve `timing_probe` process-local kalır; persistence request payload'ına girmez. Telemetry business result değildir ve tutulacaksa ayrı, non-authoritative gözlemlenebilirlik alanında tutulur.

---

## 9. Terminal Run ve Immutable Audit

### 9.1 Durum modeli

5.0B yalnız terminal-result persistence yapar. DB'de pre-execution `reserved`, `running` veya `abandoned` lifecycle satırı oluşturmaz. Kalıcı bir run her zaman eksiksiz 5.0A `RunStatus` değerine, engine history'sine ve fingerprint'e sahiptir. Gelecekte queue/job lifecycle gerekirse orchestration result history'sinden ayrı bir job-execution milestone'unda tasarlanır.

### 9.2 Immutability

- Finalized run'ın fingerprint, sonuç status'u, versions ve history içeriği update edilemez.
- Engine execution satırı insert edildikten sonra içerik update edilemez.
- Reused execution kaynağı sonradan değiştirilemez.
- Düzeltme, mevcut kaydı overwrite etmek yerine yeni `run_id` ile yeni run gerektirir.
- Artifact physical tier relocation canonical artifact row'u değiştirmez; yalnız ayrı locator indirection CAS ile güncellenir ve operasyonel audit üretir.

Immutability yalnız service-level kontrole bırakılmaz. PostgreSQL trigger'ları finalized run, engine execution, structured error ve canonical artifact payload satırlarında UPDATE/DELETE işlemlerini reddeder. Kontrollü retention/purge ileride ayrı, açık yetkili bakım prosedürü gerektirir. Locator indirection CAS güncellemesi bu canonical tablolardan ayrı operasyonel tabloda yaşar.

---

## 10. Transaction ve Idempotency Modeli

### 10.1 Terminal insert transaction

- Authoritative fingerprint yalnız `OrchestrationRunResult.request_fingerprint` alanından alınır.
- `run_id` global unique constraint ile terminal insert sırasında ayrılır.
- Conflict sonrası mevcut finalized satır aynı transaction snapshot'ında okunur.
- Fingerprint ve canonical terminal content digest eşitse mevcut run döndürülür.
- Fingerprint veya terminal content digest farklıysa hiçbir overwrite/upsert update yapılmadan conflict döner.

`ON CONFLICT DO UPDATE request_fingerprint=...` benzeri desen yasaktır.

### 10.2 Finalize transaction

DB-owned parçalar tek transaction'da yazılır:

- run terminal alanları,
- engine execution rows,
- run-level warnings/version inventory/requested outputs,
- normalized structured errors,
- artifact metadata/FK'leri,
- resume/reuse lineage.

Transaction sonunda run `finalized` olur. Ara kayıtlar final history sorgularına görünmemelidir.

### 10.3 Retry davranışı

- Mevcut run + aynı fingerprint ve terminal content digest: mevcut immutable sonucu döndür.
- Aynı `run_id` + farklı fingerprint: conflict.
- Finalize tekrarında farklı content/fingerprint/versions: invariant violation ve conflict; overwrite yok.

Bu yaklaşım at-least-once delivery altında idempotent persistence sağlar; “exactly-once execution” iddiasında bulunmaz.

### 10.4 Concurrency

İki caller aynı `run_id`'yi eşzamanlı persist ederse unique constraint kazananı belirler. Kaybeden transaction conflict sonrası mevcut finalized kaydı okuyup fingerprint + canonical terminal content digest karşılaştırmasını yapar. Eşitse idempotent başarı, farklıysa conflict döner. Process-local mutex doğruluk mekanizması olarak kullanılamaz.

---

## 11. Resume ve Recovery

### 11.1 Resume lineage

Resume yeni bir run'dır ve yeni `run_id` taşır. `previous_run_id` yalnız kaynak lineage'dır. Önceki run overwrite edilmez veya devam ettiriliyormuş gibi mutate edilmez.

### 11.2 Snapshot builder

Snapshot builder yalnız persistence katmanında bulunur ve mevcut 5.0A `PreviousExecutionSnapshot` nesnesini oluşturur:

- previous run identity/fingerprint/version alanlarını run owner'dan,
- engine status/fingerprint/version alanlarını execution owner'dan,
- `result_ref` nesnesini tek payload owner'ından,
- engine snapshot sırasını deterministik execution order'dan alır.

Builder snapshot ile eşzamanlı olarak Bölüm 8.3'teki `ResumePersistenceContext` nesnesini döndürür. Bu context 5.0A request'ine girmez ve ayrıca kalıcılaştırılmaz; mevcut canonical FK'leri command'a güvenli biçimde geri taşır.

Snapshot DB modeli değildir ve ayrıca kalıcılaştırılmaz. Her kullanımda canonical sahiplerden materialize edilir; böylece duplicate snapshot payload oluşmaz.

### 11.3 Uygunluk

Snapshot üretimi için aday run:

- aynı zorunlu company/period scope içinde olmalı,
- erişim/tenant kontrolü gelecekteki caller boundary'de doğrulanmalı,
- finalized olmalı,
- gerekli artifact'ları mevcut ve digest-doğrulanabilir olmalı,
- 5.0A'nın orchestration/execution/fingerprint version alanlarını eksiksiz taşımalı.

Bir engine snapshot'ının üretilmesi, reuse edileceği anlamına gelmez. Nihai reuse kararını değişmeden kalan 5.0A orchestrator verir.

### 11.4 Fail-closed kuralları

- Missing/corrupt artifact: ilgili engine snapshot `result_ref` ile üretilemez; sessiz yanlış reuse yok.
- Unknown serializer/result kind: reuse reddedilir.
- Digest mismatch: güvenlik/integrity hatası; payload kullanılmaz.
- Scope mismatch: tüm snapshot talebi reddedilir.
- Resume lineage cycle: DB constraint/service validation ile reddedilir.
- Previous run bulunamaması: explicit not-found; sessiz clean run'a dönüş caller kararı olmadan yapılmaz.

Target scope, 5.0A request içinden tahmin edilmez. Application caller'ın authentication/authorization sınırından gelen trusted `PersistenceRunScope(company_id, period_id)` parametresidir. Hem previous run hem yeni persisted run aynı scope'a composite FK/explicit comparison ile bağlıdır. 5.0B'de unscoped run yoktur; `(NULL, NULL)` üzerinden reuse yasaktır.

### 11.5 Crash recovery

Bu milestone automatic retry worker tasarlamaz. Orchestrator dönüşünden veya DB transaction commit'inden önce crash olursa hiçbir terminal run/history satırı kalıcı olmaz; at-least-once caller aynı request'i baştan çalıştırabilir. DB-owned terminal parçalar tek transaction'da yazıldığı için kısmi engine satırları final history gibi görünmez. Blob-first akıştan kalabilecek referanssız object yalnız orphan reconciliation konusudur. İleride checkpoint persistence istenirse ayrı milestone ve açık 5.0A sözleşme değerlendirmesi gerekir; 5.0B yalnız terminal-result persistence tasarlar.

Resume lineage cycle kontrolü yalnız self-FK check'e dayanmaz. Previous run'ın `finalized_at` değeri yeni run persist edilmeden önce mevcut olmalı ve lineage recursive query ile cycle-free doğrulanmalıdır. Yeni run henüz DB'de olmadığı için normal akışta geçmiş finalized zincirin yeni run'a geri dönmesi mümkün değildir; import/repair gibi ayrı operasyonlar aynı recursive invariant'ı ve transaction lock'ı uygulamak zorundadır.

---

## 12. Güvenlik, Gizlilik ve Veri Minimizasyonu

- Raw input document bytes orchestration persistence'a yazılmaz.
- Fingerprint kayıtları yalnız digest taşır.
- `StructuredError.message_tr` yalnız 5.0A'nın sanitize edilmiş sabit mesajını taşır.
- Raw exception message, stack trace, local path, SQL, secret veya kişisel veri audit tablosuna yazılmaz.
- External locator credential/signed URL içermez.
- Artifact encryption, access policy ve tenant authorization provider/caller sorumluluğudur; engine sorumluluğu değildir.
- Run options veya full request payload'ı saklanmaz; recovery için gerekli owner/source bilgisi yalnız typed persistence binding'lerinde taşınır.
- `tenant_id` 5.0A'da segmentasyon anahtarıdır; authorization kanıtı olarak kullanılamaz.
- Marka/kod adı hiçbir production tablo, kolon, enum, protocol veya storage locator adına gömülmez.

---

## 13. Constraint ve Index Planı

Implementasyonda en az şu garantiler bulunmalıdır:

- UNIQUE `orchestration_runs.run_id`,
- run fingerprint boş olamaz ve SHA-256 format kontrolü,
- terminal content digest boş olamaz ve SHA-256 format kontrolü,
- resume source run kendi kendisi olamaz,
- zorunlu run scope FK'leri mevcut company/period tutarlılık desenini izler,
- UNIQUE `(run_fk, engine_code)`,
- UNIQUE `(run_fk, execution_ordinal)`,
- artifact storage backend ile inline/external alanları arasında XOR check,
- engine execution artifact FK ile financial-analysis-result FK arasında at-most-one/XOR status uyumu,
- artifact digest format ve non-negative byte size check,
- `REUSED` execution için reuse source FK zorunluluğu,
- non-`REUSED` execution için reuse source FK yasağı,
- result olmayan status'larda artifact FK uyum kuralı,
- her run için terminal status/finalized_at zorunluluğu.

Önerilen sorgu indeksleri:

- company/period + newest finalized run,
- correlation ID,
- previous/resume source run,
- run status,
- engine code + status,
- artifact digest,
- resume source run.

Indexler gerçek query planı ile doğrulanmadan gereksiz çoğaltılmamalıdır.

---

## 14. Migration Stratejisi

İlerideki implementasyon tek ileri Alembic revision ile additive tablolar/constraint'ler oluşturmalıdır. Mevcut tabloların payload ownership'i değiştirilmez ve geçmiş veri backfill'i gerekmez.

Kurallar:

- upgrade/downgrade açık ve deterministik,
- ORM metadata ile migration birebir,
- PostgreSQL gerçek constraint davranışı integration test ile doğrulanır,
- enum/check değerleri Python `.value` sözleşmesiyle uyumlu,
- marka bağımsız isimler,
- payload tier eşikleri DB check'e gömülmez; configuration olarak kalır,
- external blob desteği için yeni engine-execution kolonu gerektirmeyen artifact locator şeması ve durable filesystem reference adapter ilk implementasyonda kurulur.

Bu doküman migration üretmez; yalnız gelecekteki implementasyonun kurallarını tanımlar.

---

## 15. Read Modelleri ve History

History çıktısı canonical tablolardan query-time materialize edilir:

- run summary,
- run detail,
- ordered engine executions,
- warnings/errors/provenance,
- resume/reuse lineage,
- artifact metadata ve yetkili payload resolution.

Kalıcı duplicate “full run JSON snapshot” oluşturulmaz. API/CLI response modeli ileride bu canonical kayıtlardan üretilir ve storage owner değildir.

Pagination cursor-based olmalı; offset pagination büyük history tabloları için zorunlu kabul edilmez. Public REST sözleşmesi 5.1 kapsamıdır.

---

## 16. Telemetry Ayrımı

5.0A `ExecutionTelemetry`, `OrchestrationRunResult` iş sonucunun parçası değildir. 5.0B'de de:

- reuse/fingerprint kararına girmez,
- business payload artifact'ına gömülmez,
- tutulursa non-authoritative observability owner'ında saklanır,
- yokluğu run history doğruluğunu etkilemez,
- wall-clock business field ile monotonic duration birbirine dönüştürülmez.

Telemetry persistence ilk implementasyon için opsiyoneldir.

---

## 17. Hata Taksonomisi

Persistence application boundary en az şu kapalı hata kategorilerini ayırmalıdır:

- run not found,
- run ID/fingerprint conflict,
- scope mismatch,
- previous run not finalized,
- immutable record conflict,
- artifact missing,
- artifact integrity failure,
- unsupported serializer/result kind,
- transaction failure,
- persistence invariant violation.

Bu kategoriler 5.0A `OrchestrationErrorCategory` enum'una eklenmez. Persistence hataları dış katmanın ayrı sözleşmesidir.

---

## 18. Test ve Kabul Planı — Gelecek Implementasyon İçin

Bu tasarım turunda test yazılmaz veya çalıştırılmaz. Implementasyon onayı sonrasında zorunlu test matrisi:

### A. Model/constraint

- same run ID/same fingerprint idempotency,
- same run ID/different fingerprint rejection,
- run/engine uniqueness,
- artifact inline/external XOR,
- scope consistency,
- immutable finalized rows,
- resume/reuse FK kuralları,
- resume context/result cross-check ve missing/spoofed source binding reddi,
- financial owner binding document/source-mode/provenance constraint'leri,

### B. Ownership

- mevcut `FinancialAnalysisResult` payload'ının artifact'a kopyalanmadığı,
- reused payload'ın kopyalanmadığı,
- snapshot'ın ayrıca kalıcılaştırılmadığı,
- full run JSON duplicate oluşturulmadığı.

### C. Payload

- 256 KiB sınırının iki tarafı,
- total inline budget,
- PDF/binary external-only,
- digest mismatch,
- serializer version mismatch,
- external blob DB commit failure/orphan senaryosu.

### D. Resume/recovery

- tam reuse snapshot,
- kısmi reuse,
- transitif invalidation'ın 5.0A tarafından korunması,
- corrupt/missing artifact fail-closed,
- wrong company/period rejection,
- lineage cycle rejection,
- duplicate execution sonrası idempotent terminal persistence.

### E. Boundary/safety

- `app/engines/**` içinde SQLAlchemy/persistence import'u bulunmaması,
- 5.0A public contract snapshot/regression testi,
- raw bytes, exception, stack trace ve secret persistence yasağı,
- ORM entity'nin application port dışına sızmaması.

### F. Gerçek ortam

- SQLite üzerinde hızlı contract testleri,
- PostgreSQL 16 üzerinde migration/constraint/concurrency testleri,
- tam Docker test paketi `0 failed`,
- mevcut resmi baseline olan 971 testte regression olmaması,
- artifact size ve history query performans ölçümleri.

Milestone, gerçek Docker ortamında `0 failed` görülmeden tamamlanmış sayılamaz.

---

## 19. Riskler ve Azaltımlar

| Risk | Seviye | Tasarım azaltımı |
|---|---|---|
| Aynı payload'ın result ve artifact tablolarında kopyalanması | Kritik | Storage Ownership Matrix + owner FK; duplicate payload testi |
| `Any result_ref` güvenli deserialize edilememesi | Kritik | allowlist result-kind codec, serializer version, pickle yasağı, digest doğrulama |
| Aynı run ID'nin farklı input ile overwrite edilmesi | Kritik | `run_id` UNIQUE + fingerprint compare + update/upsert yasağı |
| DB ve blob arasında yarım commit | Yüksek | blob-first idempotent write, verified locator, orphan reconciliation hook |
| Büyük JSONB ile DB şişmesi | Yüksek | 256 KiB tier sınırı, 1 MiB run budget, provider-neutral external locator |
| Yanlış company/period snapshot reuse | Kritik | scope FK ve snapshot builder fail-closed validation |
| Finalized audit kayıtlarının mutate edilmesi | Kritik | application + DB enforcement, correction-by-new-run |
| Job lifecycle ile 5.0A RunStatus'ın gelecekte karışması | Orta | 5.0B yalnız terminal run saklar; job lifecycle ayrı milestone/tablo |
| Event sourcing'in farkında olmadan oluşması | Orta | event stream/replay/projection yasağı; history canonical tablolardan okunur |
| Adapter'ın caller'a özel hale gelmesi | Yüksek | ortak application ports; REST/queue/CLI/batch/scheduler yalnız caller adapter |
| 5.0A public contract drift | Kritik | contract freeze ve statik/regression testleri |
| External locator'ın provider/credential sızdırması | Yüksek | provider-neutral locator; signed URL persistence yasağı |

---

## 20. Reddedilen Alternatifler

1. **Event sourcing:** Replay ve projection karmaşıklığı bu problem için gereksiz; reddedildi.
2. **Tüm run sonucunu tek JSONB kolonunda saklamak:** Sorgulanabilirlik, ownership ve büyük payload politikasını ihlal eder; reddedildi.
3. **Her resume'da payload kopyalamak:** Storage amplification ve duplicate source-of-truth yaratır; reddedildi.
4. **`FinancialAnalysisResult` tablosunu orchestration run tablosuna çevirmek:** Mevcut engine-result sorumluluğunu bozar; reddedildi.
5. **Orchestrator içine repository/session enjekte etmek:** Engine katmanı saflığını ve Architecture Book'u ihlal eder; reddedildi.
6. **Caller başına ayrı persistence uygulaması:** REST/worker/CLI arasında davranış drift'i yaratır; reddedildi.
7. **Python pickle ile result_ref saklamak:** Güvenlik, portability ve versioning nedeniyle reddedildi.
8. **`run_id + request_fingerprint` composite unique tek başına:** Aynı run ID'yle farklı fingerprint satırına izin vereceği için reddedildi; `run_id` tekil olmalıdır.
9. **Partial engine checkpoint'i 5.0B'ye eklemek:** 5.0A terminal-result contract'ını genişletme riski taşır; ayrı milestone'a bırakıldı.

---

## 21. Kilitlenmiş Implementasyon Kararları

Bağımsız denetim sonrasında aşağıdaki kararlar açık bırakılmamıştır:

1. Request fingerprint persistence öncesi yeniden hesaplanmaz; yalnız 5.0A sonucundaki authoritative değer kullanılır.
2. Pre-execution reservation/job lifecycle yoktur; yalnız atomik terminal-result persistence vardır.
3. Scope zorunlu company + period çiftidir; unscoped resume yoktur.
4. Result ownership mapping Bölüm 5.2'deki 3 financial-result + 7 artifact ayrımıdır.
5. Immutable canonical tablolarda PostgreSQL UPDATE/DELETE guard trigger'ı zorunludur.
6. `>256 KiB` için provider-neutral `BlobStorePort` ve durable filesystem reference adapter ilk implementasyon kapsamındadır.
7. Cloud object-store provider seçimi 5.0B'nin correctness veya kabul kapısı değildir; ayrı deployment milestone'udur.

Bu kararların değiştirilmesi ayrı bir tasarım revizyonu ve kullanıcı onayı gerektirir.

---

## 22. Önerilen Implementasyon Sırası — Onay Sonrası

Bu sıra yalnız gelecek planıdır; bu tasarım turunda uygulanmaz:

1. Architecture/design implementation approval.
2. Persistence domain records, ports ve error taxonomy.
3. ORM modelleri ve Alembic migration.
4. Artifact codec/ownership mapping.
5. PostgreSQL repositories ve transaction boundary.
6. Snapshot builder ve resume lineage.
7. Persistence application service.
8. Unit, ownership, safety ve PostgreSQL integration testleri.
9. Full Docker regression.
10. Ayrı onayla Architecture Book'un yeni gerçek sistem durumuna güncellenmesi.

REST API, queue worker ve diğer caller adapter'ları bu sıranın parçası değildir.

---

## 23. Architecture Book v1.1.0 Uyum Matrisi

| Architecture Book kuralı | 5.0B karşılığı |
|---|---|
| Kalıcılık/API ve engine katmanı ayrımı | Bölüm 2 ve 8; bağımlılık tek yönlü |
| Engine'lerde sıfır SQLAlchemy ve read-only davranış | Bölüm 2.2; değişmez yasak |
| Immutable dataclass ve tek source-of-truth | 5.0A contract freeze + Storage Ownership Matrix |
| Versioning/schema compatibility | Artifact serializer, engine ve fingerprint version alanları ayrı |
| Determinizm | Persistence audit zamanı business payload'dan ayrı; canonical digest |
| Structured warning/error güvenliği | Raw exception/stack trace persistence yasağı |
| Docker'da `0 failed` kabul kriteri | Bölüm 18.F |
| Kapsam disiplini | API/worker/model/migration implementasyonu bu turda yok |
| Marka bağımsız production sembolleri | Önerilen tüm tablo/port/locator isimleri brand-independent |
| Orchestrator yalnız koordinasyon yapar | Persistence dış application boundary'de; orchestrator değişmez |

Bu tasarım Architecture Book v1.1.0'ı değiştirmez. Implementasyon tamamlanıp gerçek sistem durumu değişmeden Architecture Book'a yeni gerçekmiş gibi hüküm eklenemez.

---

## 24. Bağımsız Mimari Denetim Sonucu

Tasarım, üreticiden ayrı bir inceleme geçişinde Principal Architecture / Persistence / Recovery / Data Integrity bakışlarıyla salt-okunur denetlenmiştir. İlk denetim `CHANGES REQUIRED` sonucu vermiş; bulgular tasarıma işlendikten sonra iki yeniden doğrulama yapılmıştır.

Kapatılan bulgu sınıfları:

- pre-execution fingerprint hesaplamasının 5.0A private fonksiyonuna bağımlılığı,
- external blob zorunluluğu ile adapter kapsamı çelişkisi,
- result-owner FK/XOR ve Storage Ownership belirsizliği,
- reservation concurrency/recovery state machine açığı,
- nullable scope ve cross-company/period resume riski,
- blob verify/publish/relocation atomikliği,
- çok düğümlü resume-lineage cycle kontrolü,
- run-level metadata owner belirsizliği,
- inline serializer format belirsizliği,
- resume source execution bağlarının 5.0A sonucunda bulunmaması,
- BS/IS/Ratio için document/source-mode/provenance binding eksikliği,
- terminal-content digest kapsamı/owner eksikliği,
- requested outputs'ın 5.0A sonucundan güvenle türetilememesi.

Final bağımsız denetim verdict'i: **READY FOR IMPLEMENTATION APPROVAL**. Yeni kritik veya yüksek seviye çelişki bulunmamış; event sourcing yasağı, 5.0A public contract freeze ve Architecture Book v1.1.0 uyumu korunmuştur.

Bu verdict implementasyonu otomatik olarak yetkilendirmez; yalnız tasarımın kullanıcı implementasyon onayına sunulabilir olduğunu gösterir.

---

## 25. Tasarım Tamamlanma Kontrol Listesi

- [x] Event sourcing açıkça yasaklandı; immutable audit/replay ayrımı yapıldı.
- [x] Storage Ownership Matrix ve tek sahiplik kuralı tanımlandı.
- [x] Mevcut `FinancialAnalysisResult` sahipliği korundu.
- [x] JSONB sınırı ve büyük payload/external blob stratejisi tanımlandı.
- [x] Gelecekte PDF/dashboard/rapor büyümesinin schema migration gerektirmemesi sağlandı.
- [x] REST/queue/CLI/batch/scheduler tarafından ortak kullanılan adapter boundary tanımlandı.
- [x] Engine/orchestrator bağımsızlığı korundu.
- [x] 5.0A public contract freeze açıkça yazıldı.
- [x] Idempotency, transaction ve concurrency kuralları tanımlandı.
- [x] Resume snapshot materialization ve fail-closed recovery tanımlandı.
- [x] Güvenlik ve veri minimizasyonu tanımlandı.
- [x] Architecture Book v1.1.0 uyum matrisi tamamlandı.
- [x] Bağımsız mimari denetim tamamlandı; tüm kritik/yüksek bulgular kapatıldı.
- [x] Kod, model, migration, repository, API ve test yazılmadı.

---

## 26. Karar Kapısı

Bu doküman yalnız tasarımdır. Bağımsız mimari denetim tamamlanıp bulgular bu dokümana işlense dahi aşağıdakiler için kullanıcıdan **ayrı ve açık implementasyon onayı** alınmadan hiçbir çalışma başlatılamaz:

- production kodu,
- ORM modeli,
- Alembic migration,
- repository/adapter,
- API,
- test,
- commit veya push.

Milestone 5.0B'nin implementasyonu, bu revize tasarımın kullanıcı tarafından ayrıca onaylanması sonrasında başlayabilecek ayrı bir turdur.
