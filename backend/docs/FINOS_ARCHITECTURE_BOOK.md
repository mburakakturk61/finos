# FINOS Architecture Book v1.5.0

**FINOS Constitution — Tek Resmi Mimari Referans**

| | |
|---|---|
| Doküman durumu | ONAYLANMIŞ — Resmi Referans |
| Versiyon | 1.5.0 |
| Kapsadığı sistem durumu | Milestone 1 → Milestone 5.0E (Docker doğrulanmış: 1716 passed, 0 failed, 0 skipped) |
| Bu dokümanın rolü | Bundan sonra yazılacak **her** milestone'un bağlayıcı referans kaynağı |
| Değiştirme yetkisi | Yalnızca açık kullanıcı onayı ile, ayrı bir revizyon turunda |
| "FINOS" ifadesinin statüsü | **Yalnızca dahili geliştirme kod adıdır** — nihai ticari marka/ürün adı değildir (bkz. Bölüm 0) |

---

## Önsöz

Bu doküman, FINOS platformunun mimarisini anlatan tek resmi kaynaktır. Milestone tasarım dokümanları (`docs/FINOS_MILESTONE_*_DESIGN.md`), belirli bir motorun veya özelliğin ayrıntılı tasarımını taşır; bu kitap ise onların hepsinin uyduğu **üst düzey, kalıcı kuralları** taşır. Bir milestone tasarım dokümanı ile bu kitap çelişirse, bu kitap bağlayıcıdır — çelişki bir tasarım hatası olarak ele alınır ve çözülür.

Bu kitap **icat edilmiş** bir mimari değildir. FINOS'un bugüne kadar inşa edilmiş, testleri gerçek bir Docker ortamında 1716 passed, 0 failed, 0 skipped sonucu veren dokuz finansal engine'inin, bunları koordine eden saf Analysis Orchestrator katmanının (Milestone 5.0A), Orchestration Persistence & Recovery Foundation katmanının (Milestone 5.0B), framework-bağımsız Analysis Application Layer'ın (Milestone 5.0C), versioned API & Integration Layer'ın (Milestone 5.0D) ve bunun production kimlik/güvenlik sınırını uygulayan Authentication & Authorization katmanının (Milestone 5.0E) davranışını, kurallarını ve sözleşmelerini olduğu gibi kayda geçirir. Her madde, kod tabanında halihazırda uygulanmış bir gerçeği tarif eder; hiçbir madde henüz var olmayan bir davranışı vaat etmez.

Bu kitabı okuyan biri — insan veya gelecekteki bir implementasyon turu — şu soruların cevabını burada bulmalıdır: *Bir motor ne yapar, ne yapmaz? Yeni bir motor nasıl eklenir? Bir registry nasıl büyütülür? Hangi işlemler kesinlikle yasaktır? Bir milestone ne zaman "tamamlanmış" sayılır?*

**Önemli bir netleştirme:** Bu dokümanda ve bu depoda geçen **"FINOS" ismi, yalnızca dahili bir geliştirme kod adıdır** — nihai ticari ürün/marka adı değildir ve henüz belirlenmemiştir. Bu ayrımın tam kapsamı ve bağlayıcı kuralları Bölüm 0'da (Proje Kod Adı Politikası) tanımlanır. Bölüm 0, bu Önsöz'ün doğrudan bir uzantısıdır ve aynı derecede bağlayıcıdır.

---

## İçindekiler

0. Proje Kod Adı Politikası (Project Codename Policy)
1. Projenin Amacı
2. Genel Sistem Mimarisi
3. Engine Dependency Graph
4. Tüm Engine'lerin Sorumlulukları
5. Her Engine'in Input / Output / Yapar / Asla Yapmaz Sözleşmesi
6. Registry Mimarisi
7. Immutable Dataclass Kuralları
8. Versioning Politikası
9. Schema Compatibility Politikası
10. Read-Only Invariant'lar
11. Determinizm Kuralları
12. Explainability Standartları
13. Warning Sistemi
14. Status Modeli
15. Test Stratejisi
16. Registry Isolation
17. Dependency Kuralları
18. Production Coding Standard
19. Yasaklar
20. Dosya Yapısı
21. Naming Standardı
22. Yeni Milestone Ekleme Prosedürü
23. Checklist (Genel Geliştirme)
24. Production Readiness Checklist
25. Release Checklist
26. Git Workflow
27. Mimari Prensiplerin Kısa Özeti

---

## 0. Proje Kod Adı Politikası (Project Codename Policy)

Bu bölüm, bu kitabın geri kalanı kadar bağlayıcıdır ve tüm milestone'lar, tüm production kodu ve tüm gelecekteki tasarım revizyonları için geçerlidir.

**0.1 — FINOS yalnızca dahili geliştirme kod adıdır.** Bu depo, bu doküman ve bu projenin geliştirme sürecinde kullanılan "FINOS" ismi, projenin dahili çalışma adıdır; bir ticari marka veya nihai ürün adı değildir.

**0.2 — Nihai ticari ürün/marka adı henüz belirlenmemiştir ve değişebilir.** Ürün yayına çıkmadan (production release) önce, ticari marka/ürün adı kararı ayrı ve bağımsız bir iş kararıdır; bu kod adıyla hiçbir kalıcı bağı yoktur.

**0.3 — Kod adı hiçbir teknik bağımlılık oluşturamaz.** "FINOS" ismi, sistemin hiçbir teknik davranışının, veri modelinin, sözleşmesinin veya iş mantığının bir parçası olamaz. Kod adının değişmesi, tek bir satır production kodunu bile etkilememelidir.

**0.4 — "FINOS" adı, production kodunda aşağıdaki alanlara hard-coded yazılamaz:**

- class / dataclass / enum adları,
- registry adları,
- database tablo ve kolon adları,
- migration adları,
- API endpoint yolları,
- JSON schema alanları,
- protocol ve interface adları,
- warning / error / disclaimer metinleri,
- rapor başlıkları,
- dashboard metinleri,
- kullanıcıya gösterilen (user-facing) UI metinleri.

Bu liste ayrıntılı bir yasak envanteri olarak Bölüm 19'da (Yasaklar) tekrar, doğrudan uygulanabilir madde madde şeklinde yer alır.

**0.5 — Ticari marka adı, ileride yalnızca configuration/branding katmanından sağlanacaktır.** Kullanıcıya gösterilecek nihai ürün adı, koddan ayrı, dışarıdan enjekte edilebilir bir konfigürasyon/branding katmanının sorumluluğundadır — bu katman v1 kapsamında henüz mevcut değildir ve mevcut olmaması, kod adının production metinlerine hard-code edilmesi için bir gerekçe oluşturmaz (bkz. Bölüm 0.9).

**0.6 — Marka değişikliği; finansal engine'leri, veri modellerini, registry'leri, API sözleşmelerini veya database şemasını değiştirmemelidir.** Bir marka/ürün adı değişikliği, yalnızca konfigürasyon/branding katmanında bir değer değişikliği olmalıdır. Hiçbir migration, hiçbir registry kaydı, hiçbir dataclass alanı, hiçbir API sözleşmesi bu değişiklikten etkilenmemelidir. Bir marka değişikliğinin bir migration gerektirmesi, mimari bir ihlal sinyalidir.

**0.7 — "FINOS" adı yalnızca aşağıdaki yerlerde kullanılabilir:**

- dahili dokümantasyon (bu kitap ve milestone tasarım dokümanları dahil),
- milestone adları (`FINOS_MILESTONE_4_3F_...` gibi),
- git commit geçmişi,
- geliştirme iletişimi (bu konuşma, iç tartışmalar),
- geçici proje klasörü/repository adı.

Bu, kod adının **yalnızca geliştirme-zamanı bağlamlarda** var olabileceği, **hiçbir çalışma-zamanı (runtime) davranışında veya kullanıcıya görünen yüzeyde** var olamayacağı anlamına gelir.

**0.8 — Yeni milestone'ların tamamı brand-independent production code ilkesine uymalıdır.** Bundan sonra tasarlanacak her milestone, tasarım dokümanı onaylanmadan önce, ürettiği hiçbir production sembolünün, metninin veya şemasının "FINOS" ismine veya herhangi bir markaya bağımlı olmadığını doğrulamalıdır (bkz. Bölüm 22, Bölüm 23-25 checklist'leri).

**0.9 — Production-facing metinlerde ürün adı gerektiğinde, açık bir parametre veya gelecekteki branding configuration kullanılmalıdır.** Bir rapor başlığında, bir dashboard metninde veya bir disclaimer'da ürün/marka adı görünmesi gerekiyorsa, bu değer her zaman çağıranın sağladığı açık bir `brand` / `product_name` parametresi (veya ileride eklenecek bir branding configuration katmanı) üzerinden geçirilir — asla sabit bir string olarak koda gömülmez. Bu, Bölüm 11'deki determinizm parametrizasyon desenine (`generated_at`/`report_id`'nin yalnızca çağıran tarafından sağlanması) doğrudan paraleldir: marka adı da, tıpkı zaman/kimlik gibi, motorun kendi içinde asla üretmediği/varsaymadığı, dışarıdan enjekte edilen bir değerdir.

**0.10 — Bu kitaptaki mevcut "FINOS" ifadelerinin veya var olan tarihsel doküman isimlerinin (`FINOS_MILESTONE_*_DESIGN.md`, `FINOS_ARCHITECTURE_BOOK.md` gibi) topluca değiştirilmesi gerekmez.** Bu doküman ve milestone dosya adları, Bölüm 0.7'nin izin verdiği "dahili dokümantasyon" ve "milestone adları" kategorisine girdiği için olduğu gibi kalır. Bu politikanın hedefi geçmişi yeniden yazmak değil, **bundan sonraki her production kod kararının** brand-independent olmasını garanti altına almaktır.

---

## 1. Projenin Amacı

FINOS, Türk şirketlerinin mizan (trial balance) verilerinden başlayarak; bilanço ve gelir tablosu üretimi, finansal oran analizi, sektör benchmark karşılaştırması, finansal sağlık skoru, kredi skoru, aksiyon önerisi ve yönetici raporlaması üreten uçtan uca bir **finansal zeka platformu**dur.

Platformun temel iddiası şudur: bir muhasebe mizanından başlayarak, hiçbir adımda insan yorumuna veya yapay zeka çıkarımına dayanmadan — yalnızca deterministik, denetlenebilir, açıklanabilir hesaplama zincirleriyle — bir CFO'nun karar almasına yardımcı olacak kalitede bir analiz üretebilmek.

Bu iddia, platformun mimarisini doğrudan şekillendirir:

**Denetlenebilirlik önceliklidir.** Her sayının nereden geldiği (`source_engine_codes`, `calculation_provenance`, `section_source_mapping`) izlenebilir olmalıdır. Bir rapor satırındaki hiçbir rakam, hangi girdi verisinden hangi formülle üretildiği gösterilemeden var olamaz.

**Determinizm önceliklidir.** Aynı girdi, aynı seçenekler → bit-bit aynı çıktı. Bu, platformun hem test edilebilir hem de hukuki/finansal bağlamda güvenilir olmasının önkoşuludur (bkz. Bölüm 11).

**Katmanlı sorumluluk ayrımı önceliklidir.** Ham veri ayrıştırma (trial_balance), finansal tablo üretimi (balance_sheet/income_statement), oran hesaplama (financial_ratios), karşılaştırma (benchmarks), skorlama (health_score/credit_score), aksiyon önerisi (recommendation) ve sunum (executive_reports/dashboards/render_contract) birbirinden kesin sınırlarla ayrılmıştır. Hiçbir katman, bir üst katmanın işini yeniden yapmaz (bkz. Bölüm 19 — "upstream recompute yasak").

**Kapsam disiplini önceliklidir.** Her milestone, yalnızca onaylanan kapsamı implemente eder. API, kalıcılık (persistence), gerçek PDF/DOCX render, frontend, kimlik doğrulama, AI/LLM entegrasyonu gibi konular, ayrı ve açıkça onaylanmış milestone'lar dışında hiçbir motor kodunda yer almaz.

Bu kitap, bu dört önceliği somut, denetlenebilir kurallara dönüştürür.

---

## 2. Genel Sistem Mimarisi

FINOS backend'i, FastAPI tabanlı bir Python servisidir (`fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `psycopg`, `pydantic-settings`, `pytest` — bkz. `requirements.txt`). Analysis Platform, beş temel mimari bölgeye ayrılır:

**A. API & Integration Layer** (`app/api/v1/analysis_runs.py`, `app/schemas/analysis_runs_v1.py`, `app/integrations/analysis_http/**`) — versioned HTTP boundary, trusted authentication context tüketimi, request/response mapping, authoritative input resolution, local admission control ve production composition doğrulamasını sahiplenir. FastAPI/Pydantic bu dış sınırda kalır; router engine veya persistence repository'sini doğrudan çağırmaz.

**B. Authentication & Authorization Layer** (`app/security/**`, `app/integrations/analysis_http/router_security.py`, `legacy_security.py`) — provider-neutral JWT/JWKS doğrulaması, authoritative tenant/principal/membership çözümlemesi, permission registry ve policy evaluation, request-bound security context, 5.0C `AuthorizationPort` adapter'ı, route protection, audit teslimi ve redaction sınırını sahiplenir. Authentication kimliği kanıtlar; authorization erişim kararını ayrı verir. Her iki sınır da outage, revoke ve integrity failure durumunda fail-closed'dur.

**C. Kalıcılık ve mevcut servisler** (`app/models`, `app/services`, `app/db`, `app/core`, `app/classification`, `app/trial_balance`, `app/orchestration_persistence`) — mizan yükleme, belge sınıflandırma, şirket/dönem/belge kalıcılığı, bulk-upload ve terminal orchestration persistence gibi veritabanı-bağımlı işlevleri barındırır. SQLAlchemy ORM modelleri (`app/models/*.py`) ve Alembic migration'ları (`alembic/`) burada yaşar.

**D. Analysis Application Layer** (`app/analysis_application/**`) — API/integration caller sözleşmeleri ile saf Orchestrator ve persistence portları arasındaki framework-bağımsız, senkron use-case koordinasyon bölgesidir. Core sözleşme ve servisleri FastAPI, Pydantic ve SQLAlchemy'den bağımsızdır; framework/persistence ayrıntıları yalnız adapter sınırında bulunur.

**E. Engine katmanı** (`app/engines/**`) — SIFIR SQLAlchemy bağımlılığı olan, saf, deterministik, read-only hesaplama motorlarının bulunduğu katman. Bu katman, girdi olarak yalnızca sade Python veri yapıları (dict/dataclass) alır, çıktı olarak yalnızca sade Python veri yapıları (frozen dataclass) üretir. Hiçbir engine modülü veritabanına bağlanmaz, HTTP çağrısı yapmaz, dosya sistemine yazmaz.

Analysis request bağımlılık yönü tek yönlüdür:

```text
HTTP request
    → API & Integration Layer (FastAPI/Pydantic boundary)
    → Authentication & Authorization (request-bound, fail-closed)
    → Analysis Application Layer (framework-independent use case)
    → Analysis Orchestrator (saf koordinasyon)
    → Financial engines (saf hesaplama)
    → Orchestration Persistence adapters / PostgreSQL
```

```
                         ┌─────────────────────────────┐
                         │   app/trial_balance/**      │
                         │  (mizan ayrıştırma, ham      │
                         │   muhasebe verisi → normalize │
                         │   edilmiş hesap ağacı)        │
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │  app/engines/balance_sheet    │
                         │  app/engines/income_statement │
                         │  ("Financial Statements")     │
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │  app/engines/financial_ratios │
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │  app/engines/benchmarks       │
                         └──────────────┬───────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                                       │
        ┌───────────▼────────────┐                          │
        │ app/engines/health_score│                          │
        └───────────┬────────────┘                          │
                    │                                        │
        ┌───────────▼────────────┐                           │
        │ app/engines/credit_score│                          │
        └───────────┬────────────┘                           │
                    │                                        │
        ┌───────────▼────────────┐                           │
        │app/engines/recommendation                          │
        └───────────┬────────────┘                           │
                    │                                        │
       ┌────────────┼─────────────────────┬──────────────────┘
       │            │                     │
┌──────▼──────┐┌────▼─────────┐  ┌────────▼────────┐
│  executive_  ││  dashboards  │  │ render_contract │
│  reports     ││              │  │ (preview only)  │
└──────────────┘└──────────────┘  └─────────────────┘
```

`app/engines/common/**`, tüm engine'lerin paylaştığı tip tanımlarını (`*_types.py`) ve registry'leri (`*_registry.py`) barındıran ortak kütüphanedir. Hiçbir engine, başka bir engine'in `service.py` iç uygulamasını import etmez — yalnızca `common/` üzerinden paylaşılan sözleşmeleri (contracts) ve doğrudan yukarı akış (upstream) sonuç nesnelerini kullanır.

**Koordinasyon alt-katmanı — Analysis Orchestrator (Milestone 5.0A):** Dokuz finansal engine'in ÜZERİNDE, kendisi **hiçbir finansal hesaplama yapmayan** bir koordinasyon alt-katmanı bulunur: `app/engines/analysis_orchestrator/`. Bu katman, dokuz motoru Bölüm 3'teki bağımlılık grafiğine göre doğru sırada, doğru girdilerle çağırır, her birinin durumunu gözlemler ve tek bir run-seviyeli sonuç (`OrchestrationRunResult`) üretir — hiçbir motorun sonucunu değiştirmez, hiçbir değeri yeniden hesaplamaz, hiçbir yeni finansal yargı üretmez. Bu ayrım, Bölüm 1'deki katmanlı sorumluluk ilkesinin doğrudan bir uzantısıdır: dokuz motor **NEYİN** hesaplanacağını, Orchestrator yalnızca **NE ZAMAN** ve **HANGİ SIRADA** çağrılacağını belirler. Orchestrator, motorları `ORCHESTRATOR_ENGINE_DISPATCH` adlı, import-zamanında doğrudan Python fonksiyon referanslarıyla doldurulan sabit bir eşlemeyle çağırır — hiçbir dinamik/string-tabanlı çözümleme kullanmaz (bkz. Bölüm 6, Bölüm 18-19).

**Orchestration Persistence & Recovery Foundation (Milestone 5.0B):** `app/orchestration_persistence/`, tamamlanmış 5.0A run sonuçlarını kalıcılaştıran, motor bazlı immutable audit history oluşturan ve önceki bir run'dan 5.0A `PreviousExecutionSnapshot` sözleşmesini yeniden kuran ayrı application/persistence katmanıdır. Saf `app/engines/analysis_orchestrator/` altında SQLAlchemy veya persistence importu yoktur; 5.0A public sözleşmeleri ve Orchestrator davranışı değişmeden kalır. Bağımlılık yalnız dıştan içe akar: application service saf Orchestrator'ı çağırır, sonucunu repository üzerinden yazar ve gerektiğinde snapshot builder ile resume girdisini hazırlar; Orchestrator bu bileşenleri bilmez.

Bu foundation'ın sınırları şöyledir:

- **Persistence Application Service:** caller-neutral `execute → optional resume snapshot → persist terminal run` akışını koordine eder; HTTP, queue veya scheduler sözleşmesi taşımaz.
- **Repository:** SQLAlchemy/PostgreSQL transaction sınırıdır; terminal run, engine execution kayıtları, structured error kayıtları ve bunların canonical result-owner bağlarını tek DB transaction'ında kalıcılaştırır.
- **Snapshot Builder:** yalnız persistence kayıtlarından ve doğrulanmış owner payload'larından 5.0A `PreviousExecutionSnapshot`/`PreviousEngineSnapshot` nesnelerini materialize eder.
- **Artifact Store / Blob Store sınırı:** deterministic canonical JSON codec, SHA-256 bütünlük kontrolü ve inline/external tier seçimini sahiplenir. `BlobStorePort` provider-neutral'dır; mevcut reference adapter durable filesystem kullanır.

**Persistence modelleri ve tablo sahipliği:** `orchestration_runs` run identity, request fingerprint, terminal status/versions ve terminal content digest'in; `orchestration_engine_executions` sıralı motor execution metadata'sı, input fingerprint, owner FK ve reuse lineage'ın; `orchestration_errors` structured error history'sinin; `orchestration_artifacts` finansal olmayan canonical payload ve digest'in; `orchestration_physical_objects` external blob metadata'sının sahibidir. `orchestration_artifact_locations`, canonical artifact/object satırlarını değiştirmeden fiziksel konum indirection'ı için ayrılmış mutable pointer tablosudur. Milestone 5.0B foundation revision'ı `4f9d2a6b8c10`, Milestone 5.0C scope-claim revision'ı `5c1a7e9d3b20`, Milestone 5.0D revision'ı `8b6e4d2c1a90`, Milestone 5.0E identity foundation/enforcement revision'ları `a1e5f0c7d901` ve `b2e5f0c7d902`; güncel tek Alembic head `b2e5f0c7d902`'dir.

**Storage Ownership Matrix — tek payload sahibi ilkesi:**

| Veri / payload | Tek canonical sahip | Yalnız referanslayan kayıt |
|---|---|---|
| Run identity, request fingerprint, terminal status ve orchestration versions | `orchestration_runs` | History/application projection'ları |
| BS, IS ve Ratio payload'ları | `financial_analysis_results` | `orchestration_engine_executions.financial_analysis_result_id` |
| Benchmark, Health Score, Credit Score, Recommendation, Executive Report, Dashboard ve Render Contract payload'ları | `orchestration_artifacts` | `orchestration_engine_executions.artifact_id` |
| External payload byte'ları | Blob store; metadata sahibi `orchestration_physical_objects` | `orchestration_artifacts.physical_object_id` ve location indirection |
| Structured execution error'ları | `orchestration_errors` | Run/execution FK'leri |

Bir engine result payload'ı hem `financial_analysis_results` hem `orchestration_artifacts` içinde tutulmaz; execution satırı payload kopyalamaz, tam olarak bir owner FK taşır. `FinancialAnalysisResult` ile yeni execution/artifact kayıtları arasında ikinci bir source of truth oluşturulmaz. Bu model **event sourcing değildir**: ara state/event stream, replay veya CQRS read model yoktur; yalnız immutable terminal run ve engine audit history vardır.

**Idempotency, resume ve fail-closed bütünlük:** `orchestration_runs.run_id` DB'de unique'dir. Aynı `run_id`, yalnız authoritative `request_fingerprint` ve canonical `terminal_content_digest` de aynıysa mevcut immutable sonucu idempotent biçimde döndürür; aynı `run_id` + farklı fingerprint veya farklı terminal içerik fail-closed `RUN_ID_CONFLICT` ile reddedilir. Resume sırasında target company/period scope'u önceki run ile birebir eşleşmeli ve source run terminal olmalıdır. Her reused engine binding'i source execution, owner FK (`artifact_id` veya `financial_analysis_result_id`), canonical digest, engine code, engine schema/model version, input fingerprint ve fingerprint schema version ile doğrulanır; lineage cycle, eksik owner veya transitive corruption sessiz fallback olmadan structured persistence error üretir ve yazma reddedilir.

Snapshot builder, BS/IS için 5.0A `EngineResultEnvelope.result` semantiğini korur: outcome içindeki status, source mode, result JSON, error message ve trial-balance usage birlikte yeniden kurulur. Execution'ın `inner_status` değeri ile structured error kayıtları ayrıca immutable execution/error history içinde korunur. Financial owner payload'ı yalnız ham JSON'dan varsayımla kurulmaz: owner scope/type/provenance bilgisi ve kalıcı canonical digest doğrulanır. Artifact yüklemede de canonical byte'ların SHA-256 digest'i decode öncesinde doğrulanır; uyuşmazlıkta snapshot üretilmez.

**Payload tier ve crash güvenliği:** Canonical JSON payload `<= 256 KiB` ise ve run'ın birikimli inline payload'ı `<= 1 MiB` kalıyorsa JSONB içinde tutulabilir; bu sınırların dışındaki payload external blob'a gider. External yazma `staging → byte-size/SHA-256 verification → content-addressed READY publish → DB binding` sırasını izler; terminal DB kaydı hiçbir zaman staging veya doğrulanmamış locator göstermez. PostgreSQL trigger'ları `orchestration_runs`, `orchestration_engine_executions`, `orchestration_errors`, `orchestration_artifacts` ve `orchestration_physical_objects` tablolarında gerçek `UPDATE` ve `DELETE` işlemlerini reddeder; location indirection bilinçli olarak bu immutable canonical kümenin dışındadır.

**5.0B kapsam sınırı:** API/router, queue, background worker, scheduler, batch runner, CLI ve UI eklenmemiştir. Event sourcing, checkpoint/job lifecycle, automatic retry ve orphan/blob cleanup worker'ı da bu milestone'un parçası değildir.

**Persistence Future Hardening (blocking değildir; sonraki milestone'larda ayrı tasarım/onay gerektirir):** locator relocation için tam compare-and-swap operasyonu ve retention/orphan reconciliation; cloud object-store adapter'ı; binary/PDF artifact writer'ları; directory-level filesystem durability (`fsync`) güçlendirmesi; exotic map/union ve non-finite float codec kurallarının sıkılaştırılması; ek FK/query-plan index incelemesi; structured error alanları için daha dar allowlist. Bu maddeler mevcut 5.0B terminal persistence/recovery sözleşmesinin parçası olarak vaat edilmez.

**Analysis Application Layer (Milestone 5.0C):** `app/analysis_application/`, değişmemiş 5.0A Analysis Orchestrator ile değişmemiş 5.0B persistence sözleşmeleri arasında framework-bağımsız bir application/use-case sınırıdır. Bu katman yalnız senkron koordinasyon yapar; finansal hesaplama yapmaz, engine sonucunu yeniden üretmez ve engine dataclass'larını dış dünyaya doğrudan açmaz. Application core'da FastAPI, Pydantic, SQLAlchemy veya Alembic importu yoktur. SQLAlchemy yalnız `app/analysis_application/adapters/` altındaki persistence/read/scope-claim adapter'larında bulunur.

Bağımlılık yönü ve transaction sorumluluğu şöyledir:

```
API & Integration caller adapter'ı
        │
        ▼
versioned application contracts + senkron use-case service
        ├──────────────► saf 5.0A Analysis Orchestrator
        └──────────────► 5.0B persistence/recovery portları
                              │
                              ▼
                     PostgreSQL transaction sınırı
```

**Exact command/query ve sonuç sözleşmeleri:** Application contract version'ı açıkça taşınan `StartAnalysisCommand`, `ResumeAnalysisCommand`, `RetryAnalysisCommand` ve `CancelAnalysisCommand` birbirinden ayrı immutable command'lardır. Read tarafında `GetAnalysisStatusQuery`, `GetAnalysisResultQuery`, `ListAnalysisHistoryQuery` ve `GetExecutionDetailQuery` bulunur. Versioned application DTO'ları; command sonucu, run summary/status/result, execution detail, history page, cancellation sonucu, source intent, scope/audit context ve payload reference/envelope projection'larını kapsar. Public alanlarda kapalı enum tipleri kullanılır; beklenen validation, authorization, conflict, not-found, persistence ve execution hataları immutable `ApplicationOutcome[T]` içinde `success/value/error/warnings` invariant'larıyla döner. Raw exception message veya stack trace public DTO'ya taşınmaz. Application DTO şeması, 5.0B storage serializer şemasından ayrıdır; financial owner reference'ında artifact serializer version zorunlu değildir.

**Start / Resume / Retry / Cancel akışları:** Start; required security audit, pre-execution authorization ve durable scope claim'den sonra 5.0A'yı çağırır, gerçek terminal engine sonuçlarından owner planı üretir, authorization'ı persistence öncesi yeniden doğrular ve terminal sonucu kalıcılaştırır. Resume, source authorization tamamlanmadan snapshot payload'ını materialize etmez; doğrulanmış 5.0B `PreviousExecutionSnapshot` girdisini değişmemiş 5.0A sözleşmesine geçirir. Retry yeni bir `run_id` ve önceki run bağını taşır; original operation `RESUME` ise resume doğrulamalarının tamamı aynen uygulanır. Bozuk/geçersiz resume veya retry kaynağında clean-start fallback yasaktır. Cancel yalnız process-local aktif invocation'a cooperative cancellation isteği iletir; terminal persistence veya idempotency kararını vermez.

**Post-result financial owner ve lineage assembly:** Public command, persistence-oriented owner FK veya owner-tablosu kararı değil, yalnız `FinancialSourceIntentDTO` ile kaynak/provenance niyeti taşır. 5.0A `EngineResultEnvelope.result` incelendikten sonra yalnız başarılı/degraded ve gerçek finansal sonuç üreten Balance Sheet, Income Statement ve Financial Ratios execution'ları için 5.0B financial owner binding oluşturulur; failed/skipped veya sonucu olmayan execution binding üretmez. Kaynak rolleri kapalı ve deterministiktir. Ratio lineage'ı, yeni oluşturulan BS/IS owner'larını aynı terminal transaction içinde çözümler ve canonical financial owner'a bağlar; mixed BS/IS sonuçları da gerçek terminal sonuçlara göre fail-closed işlenir. Aynı payload ikinci bir owner tablosuna kopyalanmaz.

**RunScopeClaim — durable ownership reservation:** `analysis_run_scope_claims`, `run_id`, company, financial period, nullable tenant, operation/original-operation, previous run, application command digest ve initiating subject bağını atomik olarak rezerve eder. Lifecycle `claim → verify → terminal persist → finalize → DTO projection` sırasındadır. `run_id` uniqueness ile on-conflict claim ve token/version tabanlı compare-and-set finalize, aynı `run_id`'nin başka tenant/company/period/subject tarafından sahiplenilmesini engeller; her uyuşmazlık fail-closed'dur. Claim finalize edilmeden veya scope-qualified doğrulanmadan hiçbir sonuç DTO'ya projekte edilmez. `RunScopeClaim` bir workflow state'i, running job, scheduler, queue, durable execution registry veya event stream değildir; yalnız immutable run ownership reservation'dır. Security audit scope ownership kaynağı değildir ve post-commit audit hatası bu binding'i değiştiremez.

**Scope-aware idempotency ve concurrent loser güvenliği:** 5.0B authoritative `request_fingerprint` sahibi olmaya devam eder; 5.0C buna company/period/tenant/operation scope doğrulamasını preflight ve post-persist aşamalarında ekler. Aynı `run_id` + aynı scope + aynı command/fingerprint idempotent canonical sonucu okuyabilir. Aynı `run_id` + farklı company, period veya tenant kesin olarak reddedilir. Aynı-scope/farklı fingerprint de conflict'tir. Concurrent idempotent persistence sırasında 5.0B erken mevcut-run dönüşü yaparsa veya yarış kaybedilirse, o invocation'ın staged financial owner ve lineage yazıları nested transaction/SAVEPOINT üzerinden rollback-to-savepoint edilip discard edilir; concurrent loser'a ait orphan owner/lineage kalıcılaşmaz.

**Authorization, audit, observability ve recovery:** Authorization pre-execution ve pre-persistence revalidation olmak üzere iki fail-closed kontrol noktasına sahiptir; revoke/deny halinde terminal persistence yapılmaz. Required `SecurityAuditPort`, best-effort `ObservabilityPort`'tan ayrıdır. Pre-execution audit veya authorization-decision audit yazılamazsa use-case başlamaz. Terminal DB commit sonrasında audit sink hata verirse canonical run geri alınmaz; success korunur, `SECURITY_AUDIT_POST_COMMIT_FAILED` warning'i ve operational alert üretilir. Commit sonrasında DTO projection hata verirse run yine geri alınmaz; `DTO_PROJECTION_FAILED` recovery sonucu güvenli run hint'i taşır ve aynı command daha sonra canonical persisted sonucu read use-case ile okuyabilir, analysis yeniden çalıştırılmaz.

**Local ActiveExecutionPort:** Process-local registry yalnız cooperative cancellation, diagnostics ve local observability/progress hook'ları içindir. Correctness, scope ownership veya idempotency kaynağı değildir. Duplicate invocation aynı process'te de başlayabilir; terminal kararı 5.0B persistence verir. Böylece same-process ve cross-process duplicate semantiği eşittir. Distributed lock, exactly-once execution ve durable active-job registry mevcut değildir.

**5.0C kapsam sınırı:** Milestone 5.0C kendi turunda API/router, queue, background worker, scheduler, batch runner, CLI veya UI eklememiştir. Background execution, distributed lock, automatic retry/backoff ve event sourcing yoktur. Application Layer yalnız senkron use-case orchestration sağlar; HTTP caller adapter'ı daha sonra Milestone 5.0D ile ayrı sınırda eklenmiştir.

### API & Integration Layer (Milestone 5.0D)

`app/integrations/analysis_http/**`, `app/api/v1/analysis_runs.py` ve `app/schemas/analysis_runs_v1.py`, 5.0C application use-case'lerinin dış HTTP adapter'ıdır. Router yalnız application service/read facade ve integration portlarını çağırır; engine service'lerini veya orchestration repository'sini doğrudan çağırmaz. FastAPI request/dependency nesneleri ile Pydantic şemaları bu boundary'nin dış yüzünde kalır; 5.0A, 5.0B ve 5.0C public sözleşmeleri değişmemiştir.

**HTTP Boundary ve router yapısı:** Analysis API prefix'i `/api/v1/analysis-runs`'dır. Sekiz sabit operation bulunur: Start, Resume, Retry, Cancel; Status, Result, History ve Execution Detail. Write endpoint'leri senkron 5.0C use-case'lerini çağırır; background execution, queue veya worker üretmez. Read endpoint'leri scope-qualified ownership preflight ve `ApiAnalysisReadFacade` üzerinden true not-found, persistence unavailable ve integrity/invariant hata kategorilerini ayırır. Yanlış tenant/company/period/subject sonucu hiçbir response DTO'suna map edilmez. Ham upstream exception, stack trace veya hassas payload HTTP cevabına taşınmaz.

**Versioned API contracts:** `X-API-Contract-Version: 1.0.0`, `X-Correlation-ID` ve write isteklerinde `Idempotency-Key` zorunlu boundary girdileridir. `analysis_runs_v1.py` içindeki kapalı Pydantic request/response şemaları, exact 5.0C command/query/DTO/enum sözleşmelerine explicit mapper ile dönüştürülür. `ApplicationOutcome[T]`, sabit HTTP status/error envelope politikasına map edilir. Response serialization/projection başarısızlığı canonical persisted run'ı geri almaz; cevap yalnız güvenli `run_id`, `correlation_id`, `persisted=true` ve recovery endpoint/reference metadata'sı taşır.

**AuthenticationContext ve authorization ayrımı:** 5.0D API boundary'si yalnız trusted, immutable ve framework-independent `AuthenticationContext` tüketir; context üretimini router veya application core'a vermez. Milestone 5.0E'de bu production provider-neutral JWT/JWKS ve authoritative local identity adapter'ıyla bağlanmıştır. Context; subject, nullable tenant, authentication method/strength, issued/expiry time, correlation ID, claims version, trusted issuer ve authorization context reference taşır. Issuer allowlist, expiry, en fazla 15 dakikalık yaş, 60 saniyelik future skew ve correlation binding fail-closed doğrulanır. `X-User-Id`, `X-Tenant-Id`, `X-Subject-Id` gibi raw identity header'ları trusted identity değildir ve reddedilir. Authentication kimliği doğrular; erişim kararı ayrı `AuthorizationPort` tarafından verilir. Production profile fake authentication, allow-all authorization, fake/no-op required security audit veya eksik adapter kabul etmez.

**Subject ve scope binding:** `analysis_run_scope_claims.initiating_subject_id`, run ownership reservation'ını initiating subject'e de bağlar. Aynı run/scope/fingerprint replay yalnız aynı subject için idempotent success olabilir; farklı subject replay `409` conflict'tir. Cross-tenant write/read fail-closed'dur. Aynı tenant içindeki başka subject'in read erişimi ayrıca authorization kararı gerektirir. `RunScopeClaim` hâlâ job/workflow state'i değildir; bu ek binding yalnız immutable ownership reservation'ın bir parçasıdır.

**Trusted Input Resolution:** Document-backed Balance Sheet/Income Statement girdilerinde caller raw dosya byte'ı göndermez; persisted `FinancialDocument` ID, `DocumentInputResolverPort` tarafından authoritative content store'dan çözülür. Resolver company/period, document type/status, declared size, SHA-256 checksum, kapalı uzantı/MIME/magic-byte politikasını doğrular; mevcut sınır 10 MiB ve desteklenen içerik `.xlsx` veya `.pdf`'dir. Trial-balance girdisi yalnız persisted `FinancialAnalysisResult` ID üzerinden `AnalysisResultInputResolverPort` ile yüklenir; owner scope/type/status ve kalıcı `canonical_result_digest` doğrulanır. Persisted source ID ile computation input'u eşleşmiyorsa Orchestrator çağrılmaz. Terminal financial result payload/digest alanları PostgreSQL trigger'ı ile sonradan değiştirilemez.

**Admission Control:** `ProcessLocalAnalysisAdmissionControl`, config kaynaklı fakat limitsiz olamayan global, tenant ve opsiyonel subject limitleri için lease üretir. Saturation kesin `429 Too Many Requests` ve bounded `Retry-After` cevabıdır. Lease success, cancellation, exception ve projection failure dahil tüm çıkışlarda `finally` ile bırakılır. Bu mekanizma process-local overload korumasıdır; distributed lock, global multi-process quota veya idempotency kaynağı değildir.

**Cursor ve pagination güvenliği:** History cursor'ı canonical JSON bytes üzerinde HMAC-SHA-256 ile imzalanır; signature signed payload dışında tutulur. Envelope key ID, tenant/company/period scope hash/binding, issued/expiry time ve internal cursor taşır. Yalnız active veya verify-only retired key kabul edilir; signature constant-time karşılaştırılır, tamper/future/expiry/scope mismatch `422` ile reddedilir.

**Production composition ve readiness:** `AnalysisApiRuntime`, trusted authentication provider, authorization, durable security audit, best-effort observability, application clock, document/result resolver, admission ve cursor codec binding'lerini doğrular. `PRODUCTION` profilinde eksik veya güvensiz binding fail-closed'dur. `/health/live` yalnız process canlılığını, `/health/ready` ise required adapter/config readiness'ini ayrıntı sızdırmadan bildirir. Built-in OpenAPI/docs URL'leri production uygulamasında kapalıdır; schema contract testleri uygulamanın `openapi()` üretimini doğrudan doğrular. Security audit correctness sınırıdır; observability outage business işlemini bloklamaz. Post-commit audit hatası persisted run'ı geri almaz ve 5.0C warning politikasını korur.

**5.0D kapsam sınırı:** API yalnız senkron request/response use-case adapter'ıdır. Queue, background worker, scheduler, batch runner, UI, distributed lock, automatic retry/backoff, provider-spesifik authentication sistemi ve event sourcing eklenmemiştir. Process-local admission multi-process toplam limit garantisi vermez; uzun süren senkron execution, deployment reverse-proxy/server timeout sözleşmesine tabidir.

### Authentication & Authorization (Milestone 5.0E)

`app/security/**`, Milestone 5.0D'nin trusted-context kabul noktasını gerçek, provider-neutral bir production güvenlik zinciriyle tamamlar. HTTP bearer credential yalnız request boundary'de alınır; `ProviderNeutralJwtVerifier` issuer/audience/algorithm ve zaman claim'lerini doğrular, `BoundedJwksProvider` ise bounded JWKS discovery/cache/refresh sınırını uygular. `none`, allowlist dışı veya algorithm-confusion girişimleri, unknown `kid`, geçersiz imza, expired/not-yet-valid/future token, stale key ve provider outage grant üretmez. Raw `X-User-Id`, `X-Tenant-Id` veya benzeri identity header'ları hâlâ güven kaynağı değildir.

**Identity ve tenant authoritative modeli:** PostgreSQL'deki `security_tenants`, `security_principals`, `security_subject_bindings`, `security_memberships`, `security_permissions`, `security_roles`, `security_role_permissions` ve `security_membership_roles` tabloları tenant, HUMAN/SERVICE principal, issuer+subject binding, membership ve rol/permission sahipliğinin canonical kaynağıdır. `SqlAlchemySecurityIdentityRepository`, her resolution'da bu kaynağı yeniden okur; positive identity/authorization cache yoktur. Tenant, binding, principal ve membership status/validity/version kontrolleri ile `token_iat < max(principal.tokens_valid_after, membership revocation boundary)` kuralı mikrosaniyeli UTC `TIMESTAMPTZ` sınırında fail-closed uygulanır; eşit timestamp kabul edilir. HUMAN ve SERVICE aynı tenant membership modelini kullanır, fakat permission safety eksenleri ayrıdır; SERVICE yalnız service-safe rol/permission kümesiyle çözülür.

**Provisioning ve revocation:** `SqlAlchemyIdentityProvisioningService`, trusted internal provisioning authority üzerinden tenant/principal/binding/membership/rol ilişkilerini idempotent ve transaction-safe biçimde kurar; public role-management API veya UI yoktur. `security_provisioning_operations` authority+idempotency key replay'ini bağlar. Revocation principal ve membership sınırlarında authoritative state değişikliğidir; sonraki request resolution bunu cache gecikmesi olmadan görür. Historical tenant binding, açık internal service ile doğrulanır; enforce migration'ı bağlanmamış eski satırları quarantine eder ve tenant FK'lerini fail-closed hale getirir.

**Permission registry ve policy engine:** Kapalı `PERMISSION_REGISTRY` exact 33 permission/action içerir. Altı built-in rol (`TENANT_ADMIN`, `FINANCE_ADMIN`, `FINANCE_ANALYST`, `REPORT_VIEWER`, `AUDITOR`, `SERVICE_OPERATOR`) için 6 × 33 exhaustive role matrix import/test zamanında doğrulanır; custom roller authoritative PostgreSQL yolundan materialize edilir. `AuthorizationPolicyEngine`, 11 üyeli `PolicyScopeType`, 17 üyeli reason taxonomy ve 18 basamaklı fail-fast precedence ile immutable `PolicyEvaluationResult` üretir. Resource çözümleme yalnız `ResourceSecurityReference → engine-selected resolver → authoritative ResourceSecurityScope` yolunu kullanır. Durable kaynaklarda Model A tenant-qualified hiding geçerlidir: unknown ve cross-tenant kaynak aynı `RESOURCE_NOT_FOUND` sonucuna gider; unscoped fallback veya existence probe yoktur. Owner ile initiator birbirinin yerine kullanılmaz.

**Request-bound context ve 5.0C adapter:** `RequestBoundAuthenticationContextProvider` doğrulanmış JWT ile authoritative local identity'yi immutable 5.0D `AuthenticationContext`'e map eder. `RequestBoundTrustedAuthorizationContextProvider`, her request/checkpoint için identity, resource ve correlation bağını process-global state kullanmadan sağlar. `LocalAuthorizationPolicyClient`, değişmemiş 5.0C `AuthorizationPort`'u uygular; Adım 9 identity repository ve Adım 10 policy repository/engine sonuçlarını değişmemiş `AuthorizationDecision`'a fail-closed map eder. Pre-execution kontrolü ile pre-persistence revalidation ayrı fresh değerlendirmelerdir; aradaki principal, membership, policy veya resource revoke terminal persistence'ı engeller.

**API ve legacy route protection:** `AnalysisRequestSecuritySession`, analysis-run endpoint'lerinde request-bound authentication, exact action authorization, admission ve audit lifecycle'ını izole eder. Executable route registry exact 28 kayıttır: yalnız `/health/live` ve `/health/ready` public; sekiz analysis-run ve on sekiz legacy route protected'dır. Legacy company/period/document/analysis/trial-balance/bulk-upload read ve write yolları authoritative tenant'a scope edilir; bulk classification, duplicate detection, resolution ve confirm lineage da cross-tenant kaynağı kullanamaz. Registry ile FastAPI route envanteri startup/test zamanında birebir karşılaştırılır; yeni ve sınıflandırılmamış route ready sayılmaz.

**Audit, redaction ve HTTP failure yüzeyi:** Authentication ve authorization security event'leri durable `SecurityAuditPort` üzerinden teslim edilir; required pre-execution/detailed decision audit outage'ı fail-closed'dur. Policy engine yalnız deterministic audit intent üretir, sink çağrısını adapter sahiplenir. Token, raw claim, subject, issuer, tenant key, SQL/DSN, stack trace ve PII event/error/metric/log yüzeyine taşınmaz; correlation ve subject yalnız safe canonical hash/reference ile temsil edilir. HTTP mapping kapalıdır: missing/invalid authentication `401` ve doğru `WWW-Authenticate`, authenticated deny `403`, hidden resource `404`, run/scope/subject conflict `409`, admission saturation `429` + `Retry-After`, required provider outage `503`; raw upstream exception response'a sızmaz.

**Production composition ve readiness:** `PRODUCTION` profili gerçek request authentication factory, identity/policy/resource repository'leri, authorization adapter, durable security audit, application clock, admission ve input resolver binding'lerini startup ve readiness sırasında doğrular. Fake/test authentication, allow-all authorization, in-memory/no-op required audit veya eksik binding production'da yasaktır. Identity/policy PostgreSQL, JWKS verifier/provider, audit sink ve clock availability aktif readiness kontrolleridir; observability outage correctness'i bloklamaz. Production docs/OpenAPI kapalıdır; live endpoint yalnız process canlılığını, ready endpoint ise hassas ayrıntı vermeden required dependency durumunu bildirir.

**5.0E kapsam sınırı:** OAuth/OIDC provider'a özgü login/consent UI, browser session/cookie, MFA enrollment, public provisioning/role administration endpoint'i, queue/worker/scheduler/UI, distributed authorization cache/lock ve event sourcing eklenmemiştir. 5.0A–5.0D public sözleşmeleri ve engine hesaplama davranışı değişmemiştir.

API katmanı ile engine katmanı arasındaki köprü, `app/engines/protocol.py`'de tanımlı `EngineSourceRef`/`EngineRunContext` sözleşme katmanıdır (Milestone 4.1+). Bu dosya, kalıcılık katmanının engine sonuçlarını nasıl referanslayacağını tanımlar; engine'lerin kendisi bu sözleşmeye bağımlı değildir — bağımlılık tek yönlüdür (API → engine, asla tersi değil).

---

## 3. Engine Dependency Graph

Dokuz engine, kesin ve döngüsüz (acyclic) bir bağımlılık zinciri oluşturur:

```
Financial Statements (balance_sheet + income_statement)
        │
        ▼
    Ratios (financial_ratios)
        │
        ▼
    Benchmarks
        │
        ├──────────────┐
        ▼              │
   Health Score         │
        │               │
        ▼               │
   Credit Score          │
        │               │
        ▼               │
   Recommendation        │
        │               │
        ├───────────────┴────┐
        ▼                    ▼
  Executive Report      Dashboard
        │
        ▼
  Render Contract (yalnızca ExecutiveReportResult üzerinden çalışır — Dashboard'dan bağımsızdır)
```

Kesin bağımlılık kuralları:

- **Financial Statements**, hiçbir engine'e bağımlı değildir; yalnızca `app/trial_balance/**`'in ürettiği normalize edilmiş hesap verisini tüketir.
- **Ratios**, Financial Statements çıktısını (bilanço + gelir tablosu JSON sonucu) tüketir — ama bu bağımlılık bir AND değil, bir **`any_of`**'tur: Balance Sheet VEYA Income Statement sonuçlarından EN AZ BİRİ üretildiyse Ratio çalışır (eksik olan tarafa `None` geçirilir); ikisi de üretilemediyse Ratio atlanır (bkz. aşağıdaki "Kod-seviyesinde zorunlu kılınma" notu).
- **Benchmarks**, yalnızca Ratios çıktısını tüketir.
- **Health Score**, Ratios ve Benchmarks çıktılarını tüketir.
- **Credit Score**, Ratios, Benchmarks ve Health Score çıktılarını tüketir (Health Score'u referans alır, yeniden hesaplamaz — bkz. Bölüm 19).
- **Recommendation**, Ratios, Benchmarks, Health Score ve Credit Score çıktılarını tüketir.
- **Executive Report**, yukarı akıştaki tüm altı motorun (Financial Statements, Ratios, Benchmarks, Health Score, Credit Score, Recommendation) çıktılarını tüketir; hiçbirini yeniden hesaplamaz, yalnızca sunum sözleşmesine (`ExecutiveReportResult`) dönüştürür.
- **Dashboard**, Health Score, Credit Score, Recommendation ve Benchmarks çıktılarını tüketir; Financial Statements/Ratios'a doğrudan bağımlı değildir (Dashboard, özet/headline seviyesinde çalışır, ham oran tablolarını göstermez).
- **Render Contract**, yalnızca `ExecutiveReportResult` girdisini tüketir; hiçbir upstream engine'i doğrudan çağırmaz, yalnızca zaten üretilmiş bir raporun section sırasını ve render-nötr metadata'sını üretir.

Bu graph **tek yönlüdür**: hiçbir engine, kendisine bağımlı olan bir engine'i geri çağıramaz veya onun sonucunu bekleyemez. Bir engine yalnızca kendisinden önceki (yukarı akıştaki) engine'lerin sonuçlarını parametre olarak alır.

**Kod-seviyesinde zorunlu kılınma (Milestone 5.0A):** Yukarıdaki graf, `app/engines/analysis_orchestrator/registry.py`'deki `ENGINE_DEPENDENCY_REGISTRY` ile artık yalnızca kavramsal değil, kayıt-anında doğrulanan, çalışma zamanında zorunlu kılınan bir yapıdır. Bu registry'de Financial Statements tek bir birleşik düğüm değil, `FS_BALANCE_SHEET` / `FS_INCOME_STATEMENT` olarak İKİ ayrı motor koduna karşılık gelir; toplam **10 düğüm, 24 kenar** vardır — **21 kenar `all_of`** (klasik AND — bir motorun TÜM listelenen bağımlılıklarının tamamlanmış/dereceli olması gerekir), **2 kenar `any_of`** (Ratio'nun `FS_BALANCE_SHEET`/`FS_INCOME_STATEMENT` bağımlılığı — yukarıdaki OR kuralının kod karşılığı) ve **1 kenar `optional`** (Dashboard'un Benchmark'a bağımlılığı — Benchmark mevcutsa kullanılır, mevcut değilse Dashboard yine de çalışır; Health Score/Credit Score/Recommendation zaten Benchmark'a `all_of` ile bağlı olduğu için bu kenar pratikte dolaylı olarak zaten sağlanmış olur). Bu üç bağımlılık türü (`all_of`/`any_of`/`optional`), `DependencyRequirement` adlı deklaratif bir sözleşmeyle ifade edilir.

---

## 4. Tüm Engine'lerin Sorumlulukları

### 4.1 Financial Statements (`app/engines/balance_sheet`, `app/engines/income_statement`)

Normalize edilmiş mizan hesap ağacından, Türk muhasebe standardına (Tekdüzen Hesap Planı) uygun bilanço ve gelir tablosu üretir. `source_mode` (`direct_document` / diğer), `facts` (kalem bazlı finansal değerler), `engine_version`, `horizontal_analysis` (dönemsel karşılaştırma, varsa) alanlarını taşıyan bir sonuç sözlüğü döner.

### 4.2 Ratios (`app/engines/financial_ratios`)

Bilanço ve gelir tablosu sonuçlarından 57 finansal oranı hesaplar (`RATIO_REGISTRY`, `RATIO_REGISTRY_VERSION = "1.1.0"`). Likidite, karlılık, verimlilik, kaldıraç ve büyüme kategorilerini kapsar. Her oranın hesaplama kökeni (`calculation_provenance`) sonuçta taşınır.

### 4.3 Benchmarks (`app/engines/benchmarks`)

Hesaplanan oranları, şirket büyüklüğüne ve sektöre göre 48 gerçek sektör-benchmark girdisiyle (`BENCHMARK_REGISTRY`) karşılaştırır. Şirketi büyüklük sınıfına yerleştirir (`company_size_classifier`) ve her oran için pozisyon (üstünde/altında/civarında) belirler.

### 4.4 Health Score (`app/engines/health_score`)

Oran ve benchmark sonuçlarından, kategori bazlı ağırlıklandırılmış bir finansal sağlık skoru üretir. Kritik eşik aşımlarını (`critical_override`), sert başarısızlık durumlarını (`hard_fail`), veri kapsamı normalizasyonunu (`coverage_normalization`) ve güven puanlamasını (`confidence`) içerir.

### 4.5 Credit Score (`app/engines/credit_score`)

Health Score sonucunu referans alarak (yeniden hesaplamadan), bankacılık merceğinden (`banking_lens`) bir kredi skoru üretir. Health Score'un ürettiği kategori kırılımını temel alır, kendi kritik override/hard-fail/coverage/confidence katmanlarını üstüne ekler.

### 4.6 Recommendation (`app/engines/recommendation`)

Ratios, Benchmarks, Health Score ve Credit Score sonuçlarından, 39 kural içeren bir tetikleyici (`trigger strategy`) registry'si (`RECOMMENDATION_RULES`) üzerinden aksiyon önerileri üretir. Kapsam kapısı (`coverage_gate`), çakışma/tekrar giderme (`dedup_conflict`), eskalasyon ve sıralama, güvenlik alanları (`safety_fields`) içerir.

### 4.7 Executive Report (`app/engines/executive_reports`)

Altı yukarı akış motorunun sonuçlarını, 7 rapor tipinden birine (`ReportType`) göre, 18 kanonik section'dan (`ReportSectionCode`) oluşan yapılandırılmış, sunuma hazır bir `ExecutiveReportResult`'a dönüştürür. Yeni hiçbir finansal değer hesaplamaz — yalnızca var olan sonuçları seçer, biçimlendirir, özetler.

### 4.8 Dashboard (`app/engines/dashboards`)

Health Score, Credit Score, Recommendation ve Benchmark sonuçlarından, 2 dashboard tipinden birine (`DashboardType`) göre, 10 widget'lık envanterden seçilmiş 5'er widget içeren küçük, hafif bir `DashboardSnapshot` üretir. Section/narrative içermez; yalnızca headline-seviye widget verisi taşır.

### 4.9 Render Contract (`app/engines/render_contract`)

Zaten üretilmiş bir `ExecutiveReportResult`'ı girdi alarak, belirli bir render ortamının (`RenderContract`: medium, desteklenen block tipleri, tablo/landscape/chart kapasitesi) bu raporu nasıl karşılayacağını tarif eden render-nötr bir `RenderContractPreview` üretir. Gerçek PDF/DOCX/HTML üretmez — yalnızca "bu rapor bu ortamda render edilebilir mi, hangi riskler var" sorusuna yapısal bir cevap üretir.

---

## 5. Her Engine'in: Input / Output / Yapar / Asla Yapmaz

### 5.1 Financial Statements

| | |
|---|---|
| Input | `app/trial_balance/**`'in ürettiği normalize edilmiş hesap ağacı (Tekdüzen Hesap Planı kodlarına göre gruplanmış kalemler) |
| Output | `{"source_mode", "facts": {...}, "engine_version", "horizontal_analysis": {...}}` sözlüğü |
| Yapar | Ham hesap bakiyelerini bilanço/gelir tablosu kalemlerine eşler; yatay analiz (varsa prior period) hesaplar |
| Asla Yapmaz | Oran hesaplamaz, benchmark karşılaştırması yapmaz, veritabanına yazmaz, mizan ayrıştırma mantığını tekrar etmez |

### 5.2 Ratios

| | |
|---|---|
| Input | Balance Sheet + Income Statement sonuç sözlükleri, opsiyonel prior-period sonuçları, dönem başlangıç/bitiş tarihleri |
| Output | 57 oranlık `calculation_provenance` dahil yapılandırılmış oran sonucu |
| Yapar | Likidite/karlılık/verimlilik/kaldıraç/büyüme oranlarını `Decimal` aritmetiğiyle hesaplar |
| Asla Yapmaz | Benchmark karşılaştırması yapmaz, skor üretmez, finansal tablo kalemlerini yeniden hesaplamaz |

### 5.3 Benchmarks

| | |
|---|---|
| Input | Ratio sonucu |
| Output | Her oran için sektör pozisyonu, şirket büyüklük sınıfı |
| Yapar | 48 kayıtlı benchmark girdisiyle karşılaştırma yapar, büyüklük sınıflandırması uygular |
| Asla Yapmaz | Oranları yeniden hesaplamaz, skor üretmez, öneri üretmez |

### 5.4 Health Score

| | |
|---|---|
| Input | Ratio sonucu, Benchmark sonucu |
| Output | Kategori kırılımlı skor, kritik override bayrakları, coverage/confidence metadata |
| Yapar | Ağırlıklı kategori skorlaması, tier interpolasyonu, hard-fail/critical-override tespiti, açıklanabilir skor gerekçesi üretir |
| Asla Yapmaz | Oran/benchmark yeniden hesaplamaz, kredi skoru üretmez, öneri üretmez |

### 5.5 Credit Score

| | |
|---|---|
| Input | Ratio sonucu, Benchmark sonucu, Health Score sonucu |
| Output | Bankacılık mercekli kredi skoru, kategori kırılımı, coverage/confidence metadata |
| Yapar | Health Score kategori kırılımını referans alır, bankacılık-özel sinyalleri (`banking_lens`) ekler, kendi hard-fail/critical-override katmanını uygular |
| Asla Yapmaz | Health Score'u yeniden hesaplamaz (yalnızca referans alır), oran/benchmark yeniden hesaplamaz, öneri üretmez |

### 5.6 Recommendation

| | |
|---|---|
| Input | Ratio, Benchmark, Health Score, Credit Score sonuçları |
| Output | Sıralanmış, çakışması giderilmiş aksiyon önerileri listesi, her biri güvenlik alanları ve güven metadata'sıyla |
| Yapar | 39 tetikleyici kuralını değerlendirir, kapsam kapısından geçirir, çakışma/tekrarı giderir, eskale eder ve sıralar |
| Asla Yapmaz | Skorları yeniden hesaplamaz, yeni finansal yorum üretmez, rapor/dashboard biçimlendirmesi yapmaz |

### 5.7 Executive Report

| | |
|---|---|
| Input | Financial Statements, Ratio, Benchmark, Health Score, Credit Score, Recommendation sonuçları + `ReportType` + `ReportCompanyMetadata` + `reporting_period_label_tr` |
| Output | `ExecutiveReportResult` (sections, legal/confidentiality metadata, confidence/coverage envanterleri) |
| Yapar | Section'ları bağımlılık grafiğine göre inşa eder, overlap/duplicate-content kurallarını uygular, legal review durumunu atar |
| Asla Yapmaz | Yeni finansal değer hesaplamaz, yeni oran/benchmark/skor/öneri üretmez, roll-up confidence/coverage üretmez, `datetime.now()`/`uuid4()`/`random` kullanmaz |

### 5.8 Dashboard

| | |
|---|---|
| Input | Health Score, Credit Score, Recommendation, Benchmark sonuçları + `DashboardType` + `ReportCompanyMetadata` |
| Output | `DashboardSnapshot` (5 widget, legal metadata) |
| Yapar | 10 widget'lık envanterden dashboard tipine uygun 5'ini seçer, headline-seviye veri doldurur |
| Asla Yapmaz | Section/narrative üretmez, upstream engine'leri kendisi çağırmaz (yalnızca hazır sonuçları alır), yeni hesaplama yapmaz |

### 5.9 Render Contract

| | |
|---|---|
| Input | `ExecutiveReportResult`, `RenderContract` (medium + kapasite tanımı) |
| Output | `RenderContractPreview` (8 render-nötr alan) |
| Yapar | Section render sırasını, tablo taşma riskini, sayfa kırılım tercihini, desteklenmeyen içerik uyarılarını üretir |
| Asla Yapmaz | Gerçek PDF/DOCX/HTML üretmez, raporu mutasyona uğratmaz, yeni finansal içerik taşımaz |

---

## 6. Registry Mimarisi

Her engine'in kanonik veri kümesi (oranlar, benchmark'lar, skor kuralları, öneri kuralları, rapor section'ları, rapor tipleri, dashboard widget'ları), **modül yükleme anında** doldurulan, sabit bir Python sözlüğü (registry) olarak tanımlanır. Örnekler:

- `RATIO_REGISTRY` (57 kayıt) — `app/engines/common/ratio_formulas.py`
- `BENCHMARK_REGISTRY` (48 kayıt) — `app/engines/common/benchmark_types.py` / `benchmark_registry.py`
- `RECOMMENDATION_RULES` (39 kayıt) — `app/engines/common/recommendation_types.py` / `recommendation_registry.py`
- `REPORT_SECTION_REGISTRY` (18 kayıt), `REPORT_TYPE_REGISTRY` (7 kayıt) — `app/engines/common/report_registry.py`
- `DASHBOARD_WIDGET_REGISTRY` (2 tip × 5 widget = 10 kayıt) — `app/engines/common/dashboard_registry.py`
- `ENGINE_DEPENDENCY_REGISTRY` (10 düğüm, 24 kenar) — `app/engines/analysis_orchestrator/registry.py`

**`ORCHESTRATOR_ENGINE_DISPATCH` bir registry DEĞİLDİR (kesin ayrım):** `app/engines/analysis_orchestrator/dispatch.py`'deki `ORCHESTRATOR_ENGINE_DISPATCH`, dokuz motorun gerçek, çağrılabilir fonksiyon referanslarını tutar — ama bu, yukarıdaki registry'lerin aksine hiçbir kayıt-doğrulama mantığı taşımaz; yalnızca **import-zamanında, doğrudan Python `import` ifadeleriyle bir kez doldurulan sabit bir eşlemedir.** `ENGINE_DEPENDENCY_REGISTRY` "hangi motor hangi motora bağımlı" (metadata) sorusuna, `ORCHESTRATOR_ENGINE_DISPATCH` ise "bu motoru gerçekte nasıl çağırırım" (executable) sorusuna cevap verir — bu ikisi KESİN OLARAK AYRI iki yapıdır (bkz. Bölüm 18-19, dinamik dispatch yasağı).

**Kayıt anında doğrula (validate-at-registration) prensibi:** Her registry, bir kayıt eklendiği anda o kaydın tüm yapısal kurallarını doğrular (bağımlılık kodlarının var olduğu, döngü olmadığı, aynı domain'in iki "full" section'da olmadığı, vb.). Geçersiz bir kayıt, modül import edilirken (yani uygulama başlarken) hemen hata fırlatır — çalışma zamanında sessizce yutulan bir hata asla olmaz.

**Registry mutasyona kapalıdır (frozen after load):** Registry'ler modül seviyesinde bir kez doldurulur; hiçbir servis fonksiyonu çalışma zamanında registry'ye kayıt eklemez veya çıkarmaz. `test_repeated_calls_do_not_grow_report_registries` gibi testler, tekrarlı servis çağrılarının registry boyutunu değiştirmediğini doğrular.

**İzole registry testi (isolation seams):** `register_report_section`/`register_report_type` gibi kayıt fonksiyonları, `registry=` parametresiyle çağrıldığında global registry'ye değil, çağıranın verdiği izole bir sözlüğe yazar. Bu, testlerin global registry'yi kirletmeden kayıt-doğrulama mantığını test edebilmesini sağlar (bkz. Bölüm 16).

**Genelleştirilmiş bağımlılık-bütünlüğü kuralı (SWOT 5→7 düzeltmesinden türetilmiştir):** Bir `ReportType`, zorunlu bir `aggregation_section` içeriyorsa, o section'ın `dependency_codes`'unda listelenen tüm section'lar da aynı `ReportType`'ın kullanım tablosunda (en azından `compact`/`headline_only` detay seviyesinde) bulunmalıdır. Aksi halde, aggregation section'ın girdi kaynakları hiç inşa edilmez ve section sessizce (gracefully) boş/eksik içerik üretir — bu, registry doğrulamasının **yakalayamadığı** ama mimari olarak yanlış bir durumdur. Bu kural, yeni bir `ReportType` veya yeni bir `aggregation_section` eklenirken registry kayıt anında elle gözden geçirilmelidir (bkz. Bölüm 17).

---

## 7. Immutable Dataclass Kuralları

Her engine'in girdi ve çıktı veri yapıları, `@dataclass(frozen=True)` ile tanımlanır. Bu, aşağıdaki garantileri sağlar:

- Bir sonuç nesnesi üretildikten sonra, hiçbir alanı değiştirilemez (`FrozenInstanceError` fırlatılır).
- Downstream bir engine, aldığı upstream sonucu **asla mutasyona uğratamaz** — yalnızca okuyabilir ve yeni bir nesne üretmek için girdi olarak kullanabilir.
- Testler, bir servis çağrısından önce ve sonra aynı nesnenin eşitliğini (`==`) karşılaştırarak mutasyon olmadığını doğrulayabilir (`test_render_contract_does_not_mutate_report_result` gibi).

Koleksiyon alanları (liste yerine) `tuple` olarak tanımlanır — Python'da `list` mutable olduğu için, bir dataclass `frozen=True` olsa bile içindeki bir `list` alanı yine de `.append()` edilebilir. FINOS'ta bu sızıntı, tüm koleksiyon alanlarının `tuple` olmasıyla kapatılır (örn. `RenderContract`'ın `supported_block_types: tuple[ReportBlockType, ...]` alanı).

Sözlük (dict) gerektiren durumlarda (örn. `primary_section_for_domain`), alan ya `types.MappingProxyType` ile sarmalanır ya da yalnızca kayıt anında (registry doldurulurken) yazılıp sonrasında bir daha yazılmayacağı testlerle garanti edilir.

---

## 8. Versioning Politikası

Her engine ve her paylaşımlı registry, kendi bağımsız versiyon sabitini taşır:

| Bileşen | Sabit | Bugünkü değer |
|---|---|---|
| Ratio registry | `RATIO_REGISTRY_VERSION` | `1.1.0` |
| Benchmark registry | `BENCHMARK_REGISTRY_VERSION` | `1.0.0` |
| Health Score | `HEALTH_SCORE_SCHEMA_VERSION` / `HEALTH_SCORE_MODEL_VERSION` | `1.0.0` / `1.0.0` |
| Credit Score | `CREDIT_SCORE_SCHEMA_VERSION` / `CREDIT_SCORE_MODEL_VERSION` | `1.0.0` / `1.0.0` |
| Recommendation | `RECOMMENDATION_SCHEMA_VERSION` / `RECOMMENDATION_MODEL_VERSION` | `1.0.0` / `1.0.0` |
| Executive Report | `REPORT_SCHEMA_VERSION` / `REPORT_MODEL_VERSION` | `1.0.0` / `1.0.0` |
| Dashboard | `DASHBOARD_SCHEMA_VERSION` / `DASHBOARD_MODEL_VERSION` | `1.0.0` / `1.0.0` |
| Render Contract | `RENDER_CONTRACT_SCHEMA_VERSION` | `1.0.0` |
| Financial Statements | `ENGINE_VERSION` (her motorda ayrı) | `1.0.0` |
| Analysis Orchestrator (koordinasyon) | `ORCHESTRATION_SCHEMA_VERSION` / `ORCHESTRATION_MODEL_VERSION` | `2.0.0` / `2.0.0` |
| Analysis Orchestrator (execution plan) | `EXECUTION_PLAN_VERSION` | `2.0.0` |
| Analysis Orchestrator (input fingerprint) | `FINGERPRINT_SCHEMA_VERSION` | `1.0.0` |

Analysis Orchestrator'ın kendi versiyon eksenleri, motorların KENDİ schema/model versiyonlarından AYRIDIR: `ORCHESTRATION_SCHEMA_VERSION`/`ORCHESTRATION_MODEL_VERSION`, `OrchestrationRunRequest`/`OrchestrationRunResult`'ın kendi alan yapısını ve davranış mantığını (ör. reuse kuralı, durum-eşleme tablosu) izler; `EXECUTION_PLAN_VERSION`, `ENGINE_DEPENDENCY_REGISTRY`'nin yapısını (yeni bir motor eklendiğinde artar) izler; `FINGERPRINT_SCHEMA_VERSION`, girdi parmak izi (input fingerprint) hesaplama algoritmasının kendisini izler.

**Schema version** ile **model version** arasındaki ayrım kesindir:

- **Schema version**, çıktının *yapısını* (hangi alanlar var, hangi tipte) tarif eder. Bir alan eklenip çıkarıldığında artar.
- **Model version**, çıktının *içeriğinin nasıl hesaplandığını* tarif eder. Bir formül, ağırlık, eşik değeri değiştiğinde artar; yapı aynı kalsa bile.

**Versiyon artırma kuralları:**

- Yeni bir `ReportType` eklemek → `REPORT_MODEL_VERSION` artırılmalıdır (yeni bir sunum kombinasyonu, modelin davranış yüzeyini genişletir).
- Bir section'ın builder mantığı değiştiğinde (aynı section kodu, farklı hesaplama) → ilgili engine'in `MODEL_VERSION`'ı artırılmalıdır.
- Yeni bir alan eklendiğinde (geriye uyumlu, opsiyonel) → `SCHEMA_VERSION`'ın patch/minor seviyesi artırılabilir.
- Var olan bir alan kaldırıldığında veya anlamı değiştiğinde → `SCHEMA_VERSION`'ın major seviyesi artırılmalıdır ve bu, bir **breaking change** olarak Bölüm 9'daki uyumluluk politikasını tetikler.

Her `ReportSectionDefinition`, kendi `model_version_introduced` alanını taşır — bu, bir section'ın hangi model versiyonunda tanıtıldığını kalıcı olarak kaydeder ve geriye dönük analiz/denetim için kullanılır. `deprecated_since` ve `replacement_section_code` alanları, bir section kullanımdan kaldırıldığında (ama registry'den asla silinmeden) o geçişi işaretler.

---

## 9. Schema Compatibility Politikası

FINOS, upstream bir engine sonucunun (örn. bir `HealthScoreResult`) beklenen versiyonla eşleşmediği durumları merkezi, değişmez (immutable) bir uyumluluk politikasıyla ele alır. Bu politika, Milestone 4.3F'de (Recommendation Engine) kuruldu ve Milestone 4.4'te (Executive Report) birebir aynı desenle tekrar kullanıldı — **tek bir uyumluluk modeli, tüm engine'ler tarafından paylaşılır.**

Üç katmanlı davranış modeli:

1. **`SCHEMA_INCOMPATIBLE` (bloklayıcı hata):** Gelen sonucun *yapısı* (schema) beklenenle uyuşmuyorsa (örn. zorunlu bir alan tamamen yok), işlem durur ve açık bir hata fırlatılır. Bu durumda kısmi/yanlış yorumlanmış bir sonuç üretmek, hiç sonuç üretmemekten daha tehlikelidir.
2. **`VERSION_MISMATCH` (bloklayıcı hata, schema-seviyesi):** Gelen sonucun `schema_version`'ı, bu engine'in desteklediği aralığın dışındaysa, işlem durur.
3. **`MODEL_VERSION_MISMATCH` (bloklamayan uyarı):** Gelen sonucun *yapısı* uyumlu ama `model_version`'ı beklenenden farklıysa, işlem **devam eder** ve sonuca bir `MODEL_VERSION_MISMATCH` warning'i eklenir (bkz. Bölüm 13). Bu, "veri yapısal olarak okunabilir ama hesaplama mantığı güncel olmayabilir" durumunu şeffaf şekilde işaretler; downstream tüketici (insan veya başka bir sistem) bu uyarıyı görür ve kendi kararını verir.

`REPORT_EXPECTED_UPSTREAM_MODEL_VERSIONS` gibi merkezi bir eşleme tablosu, her upstream engine için beklenen model versiyonunu tutar; bu tablo, yeni bir upstream versiyon çıktığında tek bir yerden güncellenir.

---

## 10. Read-Only Invariant'lar

FINOS'ta üç sunum katmanı motoru (Executive Report, Dashboard, Render Contract), **presentation-only invariant** adı verilen ve testlerle sürekli doğrulanan bir dizi garanti taşır:

**`REPORT_ENGINE_PRESENTATION_ONLY`:** Executive Report, hiçbir yeni finansal değer hesaplamaz; yalnızca upstream sonuçlardan seçim, biçimlendirme ve özetleme yapar. Bir raporun ürettiği hiçbir sayısal alan, upstream sonuçlarda karşılığı olmayan bir hesaplamanın ürünü olamaz.

**`DASHBOARD_PRESENTATION_ONLY`:** Dashboard, upstream engine'leri kendisi çağırmaz (`test_dashboard_property_no_upstream_engine_calls`, `unittest.mock.patch` ile upstream fonksiyonların hiç çağrılmadığını doğrular) — yalnızca zaten hesaplanmış sonuçları parametre olarak alır ve widget'lara dönüştürür.

**`RENDER_CONTRACT_PRESENTATION_ONLY`:** Render Contract Preview'daki hiçbir alan finansal değer taşımaz; yalnızca yapısal metadata (section kodu, risk seviyesi, tercih, boolean bayrak) taşır.

Bu üç invariant, her engine'in kendi test dosyasında en az bir "property test" ile doğrulanır ve yeni bir sunum motoru eklendiğinde aynı desen zorunludur.

**Genel read-only kural:** Hiçbir engine, aldığı girdi nesnesini mutasyona uğratmaz (bkz. Bölüm 7 — frozen dataclass). Hiçbir engine, veritabanına yazmaz, dosya sistemine yazmaz, ağ çağrısı yapmaz. Bir engine fonksiyonunun tek yan etkisi, kendi dönüş değerini hesaplamaktır.

---

## 11. Determinizm Kuralları

**Temel kural:** Aynı girdi + aynı seçenekler → bit-bit aynı çıktı. Bu, `test_dashboard_deterministic_output` gibi testlerde 25 tekrarlı çağrının birebir eşit sonuç ürettiği doğrulanarak somutlaştırılır; `test_render_contract_property_deterministic_across_all_7_report_types` gibi testlerde tüm rapor tipleri için tekrarlanır.

Determinizmi bozan ve bu yüzden **kesinlikle yasak** olan üç kaynak:

1. **Sistem saati (`datetime.now()`, `datetime.utcnow()`):** Bir engine kendi zaman damgasını üretemez. `generated_at` gibi zaman alanları, yalnızca **çağıranın açıkça sağladığı** bir parametre olarak var olur; sağlanmazsa alan `None` kalır (`test_generated_at_and_report_id_only_set_when_provided`).
2. **Rastgelelik (`uuid4()`, `random.*`):** Bir engine kendi kimlik üretemez. `report_id` gibi alanlar da aynı şekilde yalnızca çağıranın sağladığı bir parametredir.
3. **Yerel/global durum (`locale` global state, ortam değişkenine bağlı biçimlendirme):** Para birimi görüntüleme politikası (`currency_display_policy`), dil (`locale`) gibi her şey açık parametre olarak geçirilir; process-global bir `locale.setlocale()` çağrısına asla dayanılmaz.

Her yeni servis dosyası için, kaynak kodun bu üç deseni içermediğini doğrulayan bir statik test yazılır (`inspect.getsource()` ile kaynağı okuyup `"datetime.now("`, `"uuid4()"`, `"random."` alt-dizelerinin yokluğunu doğrulamak) — bkz. `test_no_datetime_now_uuid4_random_in_dashboard_service_source` örneği. Bu desen, her yeni engine/servis dosyası için tekrarlanması gereken zorunlu bir test kalıbıdır.

**İstisna — monotonic clock, yalnızca telemetry için (Milestone 5.0A):** Analysis Orchestrator, `run_orchestration(request, *, timing_probe=None)` imzasıyla, **yalnızca çağıranın açıkça enjekte ettiği** bir `TimingProbe` (`time.perf_counter()` gibi monotonic bir saat sarmalayıcısı) kabul edebilir. Bu, yukarıdaki `datetime.now()`/`uuid4()`/`random.*` yasağının kapsamına GİRMEZ, çünkü: (a) Orchestrator'ın kendisi hiçbir saat kütüphanesini kendi başına import edip çağırmaz — saat okuma sorumluluğu tamamen çağırana aittir; (b) `timing_probe`'un ürettiği `ExecutionTelemetry`, iş sonucunun (`OrchestrationRunResult`) bir PARÇASI DEĞİLDİR — ayrı, opsiyonel bir dönüş değeridir; (c) `timing_probe=None` iken hiçbir telemetry üretilmez, davranış tamamen belirlenimlidir. Takvim/duvar-saati okuma (`datetime.now()` ile "bugün ne" sorusuna cevap vermek) hâlâ kesinlikle yasaktır — istisna yalnızca, iş sonucunun dışında tutulan, dışarıdan enjekte edilen, monotonic bir gözlemlenebilirlik sinyaline özgüdür.

**İki ayrı determinizm özelliği (Milestone 5.0A ile genelleştirilen terminoloji):** `BUSINESS_PAYLOAD_DETERMINISM`, aynı finansal girdiler + aynı seçeneklerle üretilen sonucun *iş içeriğinin* (finansal/hesaplama sonuçları) bit-bir aynı olmasını ifade eder — bu, çağıranın sağladığı `run_id`/`correlation_id`/`generated_at` gibi kimlik/zaman alanları farklı olsa bile geçerlidir (bu alanlar zaten iş içeriğinin parçası değildir, bkz. yukarıdaki `generated_at`/`report_id` kuralı). `FULL_RESULT_DETERMINISM`, buna ek olarak run_id/correlation_id/generated_at de dahil TÜM sonuç nesnesinin (telemetry hariç) bit-bir aynı olmasını ifade eder. Bu ayrım, "aynı girdi → aynı çıktı" temel kuralının (yukarısı) hangi alanları kapsadığını kesinleştirir ve gelecekteki her motor/koordinasyon katmanı için bağlayıcı bir terminolojidir.

---

## 12. Explainability Standartları

FINOS'un temel iddiası (Bölüm 1), her sayının kökeninin izlenebilir olmasını gerektirir. Bu, üç mekanizmayla sağlanır:

**Calculation provenance:** Ratio engine, her oranın hangi ham girdi kalemlerinden, hangi formülle hesaplandığını `calculation_provenance` alanında taşır (57 kayıt — `test_len(body["calculation_provenance"]) == 57`).

**Source engine codes:** Her `ReportSectionDefinition`, o section'ın hangi upstream engine kod(lar)ından beslendiğini `source_engine_codes` alanında taşır.

**Section source mapping:** `ExecutiveReportResult`, her section için hangi upstream sonuç alanlarının kullanıldığını `section_source_mapping` alanında taşır — bu, bir raporu okuyan kişinin "bu paragraf hangi hesaplamadan geldi" sorusuna kod seviyesinde cevap bulabilmesini sağlar.

**Confidence/coverage envanteri (roll-up yasağıyla birlikte):** Bir rapor veya dashboard'un genel/kompozit bir "güven skoru" **yoktur** — bu bilinçli bir mimari karardır. Onun yerine, `source_confidence_inventory` ve `source_coverage_inventory` alanları, her kaynağın kendi confidence/coverage değerini ayrı ayrı taşır; `missing_confidence_sources`/`missing_coverage_sources` alanları hangi kaynakların eksik olduğunu açıkça listeler. Bir kaynağın confidence/coverage değeri yoksa, bu değer **asla sıfır olarak varsayılmaz** ve **asla hesaplamaya dahil edilmez** — `reason_code` + `warning` ile "unavailable" olarak işaretlenir (bkz. Bölüm 13). Bu, "eksik veriyi sıfır say" gibi sessizce yanıltıcı bir davranışı kesin olarak engeller.

**SWOT ve strateji üretimi sınırı:** SWOT section'ı, Health Score ve Recommendation sonuçlarının yeniden biçimlendirilmiş halidir (`is_reformatted_source_content=True`), **bağımsız bir stratejik analiz değildir** (`is_independent_strategic_analysis=False`). Fırsatlar (Opportunities) kadranı, FINOS'un elindeki verilerle bağımsız olarak üretilemeyeceği için her zaman boş/kullanılamaz durumda, açık bir `reason_code` ile birlikte sunulur — asla var olmayan bir analiz varmış gibi doldurulmaz.

---

## 13. Warning Sistemi

FINOS'ta hata iki kategoriye ayrılır: **bloklayıcı hatalar** (exception fırlatılır, işlem durur) ve **bloklamayan uyarılar** (`warnings` listesine eklenir, işlem sonucu üretilmeye devam eder). Bir motorun ne zaman hangisini kullanacağı, engine'in read-only/presentation-only doğasına göre belirlenir: veri eksikliği veya versiyon uyumsuzluğu genellikle bloklamaz (şeffaf şekilde işaretlenir), yapısal/schema uyumsuzluğu genellikle bloklar.

Standart warning kod ailesi (her warning bir `code` + açıklayıcı alanlar taşıyan sözlük/dataclass'tır):

- **`MODEL_VERSION_MISMATCH`** — bkz. Bölüm 9. Upstream sonucun model versiyonu beklenenden farklı, ama yapısal olarak uyumlu.
- **`DUPLICATE_DATA_ACROSS_SECTIONS`** — bir veri domain'i (örn. `health_score_summary`), birden fazla section'da (biri "primary/full", diğeri "secondary/summary") göründüğünde üretilir. Bu bir hata değildir; bilinçli bir tasarım kararının (bazı domainlerin birden fazla section'da farklı detay seviyeleriyle görünmesi) şeffaf işaretlenmesidir.
- **`UNSUPPORTED_BLOCK_TYPE`** — Render Contract Preview'da, hedef render ortamının desteklemediği bir içerik bloğu tipi (örn. `CHART_DATA`) bir section'da gerekli olduğunda üretilir.
- **Eksik confidence/coverage kaynağı uyarıları** — `missing_confidence_sources`/`missing_coverage_sources` listelerindeki her kayıp kaynak için, o kaynağın neden eksik olduğunu açıklayan bir `reason_code` ile birlikte üretilir.

**Kesin kural:** Bir uyarı **asla veri silmez**. Bir section veya widget, uyumsuz/eksik veri yüzünden "sessizce" kaldırılmaz — ya boş/kullanılamaz olarak açık bir nedenle gösterilir ya da bir uyarıyla birlikte mevcut haliyle sunulur.

---

## 14. Status Modeli

**`ReportComputationStatus`** (Executive Report), bir raporun hesaplama sürecinin genel durumunu üç değerle tarif eder (tam başarı / kısmi veri eksikliğiyle tamamlanma / bloklayıcı hata — tasarım dokümanındaki tam adlandırmaya bkz.). Bu status, raporun *kullanılabilir* olup olmadığının en üst seviye göstergesidir; bir tüketici önce bu alana bakar.

**`LegalReviewStatus` / `ConfidentialityLevel`** (Executive Report ve Dashboard), bir sunum çıktısının hukuki inceleme durumunu ve gizlilik seviyesini taşır. v1 kapsamında **hiçbir rapor "onaylanmış" (approved) durumda üretilmez** — her rapor, en azından "iç kullanım" (`internal_use_only`) seviyesinde başlar ve `external_distribution_allowed=False`, `decision_support_only=True` olarak işaretlenir (bkz. `test_golden_dataset_both_dashboard_types`). Bu, FINOS raporlarının bir CFO'nun karar desteği aracı olduğunu, resmi/hukuki bir belge olmadığını açıkça sınırlar.

**`BuildPhase`** (Executive Report section'ları için), bir section'ın inşa aşamasını üç değerle tarif eder: `source_section` (doğrudan upstream veriden inşa edilir, başka section'a bağımlı değildir), `aggregation_section` (diğer section'ların çıktısını okuyarak birleştirir — örn. SWOT), `compliance_section` (metodoloji/uyum notları üretir, `ALL_INCLUDED_UPSTREAM_SECTIONS` joker bağımlılığıyla, o raporda dahil olan tüm section'ları referans alabilir ama yeni finansal yorum üretemez).

**`DetailLevel`** (section kullanım tanımı için), bir section'ın belirli bir rapor tipinde ne kadar ayrıntılı sunulacağını dört değerle tarif eder: `full`, `summary`, `compact`, `dashboard`. **Anlatı (narrative) raporlar `dashboard` seviyesini asla kullanamaz** — bu, narrative ve dashboard sunum sözleşmelerinin birbirine karışmasını registry seviyesinde engeller.

---

## 15. Test Stratejisi

FINOS iki paralel test rejimi kullanır:

**A. Sandbox test rejimi** (bu konuşma/implementasyon ortamında kullanılır): `sqlalchemy`/`fastapi`/`pydantic` paketleri PyPI proxy'den kurulamadığı için, `app.models` için `sys.modules`'e önceden kaydedilen bir stub namespace paketi tekniğiyle, `app/models/__init__.py`'nin eager ORM importlarını hiç çalıştırmadan yalnızca `app.engines.**` (SIFIR sqlalchemy bağımlılığı) testlerini gerçekten çalıştırmak mümkündür (`run_tests.py`). Bu rejim, hızlı geri bildirim döngüsü için kullanılır ama **nihai kabul kriteri değildir.**

**B. Gerçek Docker test rejimi** (nihai kabul kriteri): `PYTHONPATH=/app python -m pytest tests/ -v`, tam bağımlılık kurulu gerçek bir konteynerde çalıştırılır. **Hiçbir milestone, gerçek Docker ortamında `0 failed` sonucu görülmeden "tamamlandı" ilan edilemez.** Milestone 4.4, bu rejimde 886/886 test ile; Milestone 5.0A (Analysis Orchestrator), 971/971 test ile; Milestone 5.0B (Orchestration Persistence & Recovery Foundation), 998/998 test ile; Milestone 5.0C (Analysis Application Layer), 1042/1042 test ile; Milestone 5.0D (API & Integration Layer), 1066/1066 test ile; Milestone 5.0E (Authentication & Authorization) ise **1716 passed, 0 failed, 0 skipped** ile doğrulanmıştır. Son koşuda 22 dependency/Alembic deprecation warning'i raporlanmıştır; bunlar test failure değildir.

**İki katmanlı entegrasyon testi ayrımı** (`tests/README.md`): API-sözleşme testleri SQLite üzerinde çalışır (hızlı, izole); gerçek entegrasyon testleri `TEST_DATABASE_URL`/`DATABASE_URL` ortam değişkeni ile gate'lenmiş gerçek PostgreSQL üzerinde çalışır ve ortam değişkeni yoksa `pytest.skip` ile zarifçe atlanır. Milestone 5.0B'nin PostgreSQL testleri gerçek constraint/trigger davranışını, negatif resume binding ve owner-integrity senaryolarını, idempotency çatışmasını, cursor'ın ikinci sayfasını ve migration `upgrade → downgrade → upgrade` çevrimini gerçek SQL ile doğrular. Milestone 5.0C PostgreSQL/concurrency testleri; RunScopeClaim uniqueness ve cross-tenant yarışlarını, wrong-scope finalize/projection reddini, BS/IS/Ratio owner-lineage assembly'yi ve concurrent loser SAVEPOINT rollback/discard güvenliğini gerçek transaction'larla doğrular. Milestone 5.0D testleri sekiz router operation'ını, trusted input resolution, HMAC cursor, admission ve HTTP schema sınırlarını kapsar. Milestone 5.0E testleri JWT/JWKS negatif saldırı yüzeyini, provisioning/revocation'ı, 19 kodlu identity resolution taxonomy'sini, HUMAN/SERVICE permission safety'yi, 33 action ve 198 built-in role-matrix hücresini, 17 policy reason reachability'yi, Model A hiding'i, request-bound context izolasyonunu, `AuthorizationPort` mapping/revalidation/audit delivery'yi, exact 28-route registry'yi, legacy tenant scoping'i ve production composition/readiness'i doğrular. Güncel tek Alembic head `b2e5f0c7d902`'dir.

**5.0D ayrı kapanış kapıları:** Tam pakete ek olarak router/API integration 15/15, PostgreSQL/migration integration 33/33, authentication/authorization/security 8/8, concurrency/admission-control 7/7 ve OpenAPI/schema contract 12/12 test ile bağımsız çalıştırılmıştır; tümünde `0 failed` sonucu alınmıştır.

**5.0E ayrı kapanış kapıları:** JWT/JWKS, provisioning, E2 enforcement, identity repository/revocation, policy engine, 5.0C authorization adapter, request-bound authentication ve route/legacy security testleri birlikte **638 passed, 0 failed, 0 skipped** sonucunu vermiştir. Analysis application/API revalidation ve gerçek migration-cycle grubu ayrıca **33 passed, 0 failed, 0 skipped** ile doğrulanmıştır. Isolated PostgreSQL üzerinde `upgrade → downgrade → upgrade` çevrimi geçmiş; backend ve PostgreSQL servisleri sağlıklı kalmıştır.

**Sentetik fixture üretimi:** `tests/data/synthetic/generate_fixtures.py`, pandas + tek seferlik `soffice --headless` (LibreOffice) dönüştürmesiyle test mizan dosyaları üretir; LibreOffice bağımlılığı **proje bağımlılığı olarak eklenmemiştir** — yalnızca fixture üretimi için tek seferlik yerel bir araçtır.

**Zorunlu test katmanları (her yeni engine/section/rapor tipi için):** type/registry unit testleri, orkestrasyon/pipeline testleri, coverage/confidence testleri, golden dataset testleri (gerçekçi uçtan uca senaryo), property-based testler (invariant'ların rastgele/parametrik girdilerle doğrulanması), performans smoke testleri (gevşek üst sınır, kesin sertifikasyon değil), registry cleanliness/regression testleri (registry boyutunun büyümediği, izole kaydın sızmadığı).

**`tests/conftest.py` autouse fixture — `_snapshot_shared_engine_registries`:** Her test, çalışmadan önce tüm paylaşımlı registry'lerin bir anlık görüntüsünü (snapshot) alır ve test bittiğinde bu görüntüyü **LIFO (son eklenen ilk geri yüklenen) sırayla** geri yükler. Şu an 9 modülü, kesin import sırasıyla kapsar:

```
ratio_formulas → benchmark_registry → benchmark_types →
health_score_registry → credit_score_registry →
recommendation_registry → report_registry → dashboard_registry →
analysis_orchestrator.registry
```

`analysis_orchestrator.registry` (Milestone 5.0A), diğerlerine bağımlı değildir (yalnızca `analysis_orchestrator.types`'a bağımlıdır) — ama tutarlılık için EN SON eklenir, LIFO restore'da EN ÖNCE geri yüklenir.

Bu fixture, bir testin (kasıtlı veya kazara) bir registry'ye kalıcı kayıt eklemesi durumunda, sonraki testlerin bu kirlenmeden etkilenmemesini garanti eden **son savunma hattıdır** (defense-in-depth) — her testin kendi `try`/`finally` temizliğine ek olarak, sistemsel bir güvenlik ağı sağlar.

---

## 16. Registry Isolation

Registry isolation, iki ayrı ama tamamlayıcı mekanizmayla sağlanır:

**1. Fonksiyon seviyesi izolasyon (`registry=` parametresi):** `register_report_section(definition, registry=isolated_dict)` gibi kayıt fonksiyonları, opsiyonel bir `registry` parametresi kabul eder. Parametre verilmezse global registry'ye yazar; verilirse yalnızca çağıranın sağladığı sözlüğe yazar. Bu, testlerin "geçersiz bir kayıt reddedilir mi" gibi doğrulama senaryolarını, global registry'yi hiç dokunmadan test edebilmesini sağlar (`test_isolated_section_registration_does_not_leak_into_global_registry`, `test_isolated_report_type_registration_does_not_leak_into_global_registry`).

**2. Test-seviyesi otomatik izolasyon (`conftest.py` autouse fixture):** Bölüm 15'te tarif edilen snapshot/restore mekanizması, herhangi bir testin (izolasyon parametresini kullanmayı unutsa bile) global registry'yi kalıcı olarak değiştirmesini engeller.

Bu iki katman birlikte, "bir testin registry'ye yazdığı kayıt, başka hiçbir teste asla sızmaz" garantisini sağlar — registry boyutu her testten önce ve sonra aynı kalmalıdır (`len(REPORT_SECTION_REGISTRY) == 18` gibi sabit sayı doğrulamaları, testler boyunca değişmeden kalır).

---

## 17. Dependency Kuralları

**Kayıt anında doğrulanan yapısal kurallar** (bir registry'ye geçersiz bir kayıt eklenmeye çalışıldığında modül import anında hata fırlatılır):

- **Bilinmeyen bağımlılık reddi:** Bir section, var olmayan bir `dependency_codes` girdisine referans veremez.
- **Kendine bağımlılık reddi:** Bir section, kendi kodunu `dependency_codes` içinde taşıyamaz.
- **Döngü reddi:** Bağımlılık grafiğinde herhangi bir döngü (A→B→A) reddedilir.
- **Faz sırası kuralı:** `source_section`'lar hiçbir section'ın çıktısını tüketemez (`consumes_section_outputs=()`); yalnızca `aggregation_section`'lar tamamlanmış bağımlılık çıktılarını okuyabilir; `compliance_section`'lar yeni finansal yorum üretemez, yalnızca metodoloji/uyum metadata'sı üretebilir.
- **Kararlı topolojik sıra:** Bağımlılık grafiği, kayıt ekleme sırasından bağımsız olarak her zaman aynı, kararlı bir topolojik sırayla çözülür (`insertion-order independence`).
- **Rapor tipi bağımlılık bütünlüğü (Bölüm 6'da tanıtılan genelleştirilmiş kural):** Bir `ReportType`, zorunlu bir `aggregation_section` içeriyorsa, o section'ın tüm `dependency_codes`'u aynı `ReportType`'ın kullanım tablosunda en azından `compact`/`headline_only` seviyesinde bulunmalıdır. Bu kural, registry'nin kendisi tarafından otomatik doğrulanmaz (çünkü "hangi section'ların hangi rapor tiplerinde bulunması gerektiği" iş kuralı, yapısal bir grafik kuralından farklıdır) — bu yüzden **yeni bir ReportType veya aggregation_section eklenirken, implementasyon öncesi tasarım incelemesinde elle kontrol edilmesi zorunludur** (bkz. Bölüm 22).

**Overlap / duplicate-content kuralları:** Bir section'ın `data_domains` alanı, o section'ın hangi veri alanlarını (örn. `health_score_summary`) taşıdığını bildirir. `primary_section_for_domain`, her domain için hangi section'ın "birincil/tam" gösterim olduğunu belirler. Aynı domain, aynı rapor tipinde iki section'da **aynı anda `full` detay seviyesinde** olamaz — bu, registry doğrulamasında reddedilir. İkincil section'lar aynı domain'i `summary`/`compact`/referans seviyesinde gösterebilir; bu durumda otomatik olarak bir `DUPLICATE_DATA_ACROSS_SECTIONS` uyarısı üretilir (bkz. Bölüm 13), **hiçbir veri sessizce silinmez.**

---

## 18. Production Coding Standard

- **Aritmetik:** Tüm finansal/skor hesaplamaları `Decimal` ile yapılır; `float` yalnızca dış sistemlerden gelen ham girdi değerlerini bir kez `Decimal`'e dönüştürürken kullanılabilir, asla ara hesaplamada değil.
- **Veri yapıları:** Girdi/çıktı sözleşmeleri `@dataclass(frozen=True)`; koleksiyonlar `tuple`; enum'lar `Enum`/`StrEnum` ile kapalı (closed) kümeler olarak tanımlanır — bir enum'a yeni bir değer eklemek, her zaman açık bir tasarım kararı ve versiyon artışı gerektirir (bkz. Bölüm 8).
- **Dispatch:** Bir kod yoluna göre davranış seçimi, her zaman **deklaratif** bir desenle yapılır — bir registry sözlüğünden strateji fonksiyonu/enum değeri okumak gibi. `eval`/`exec` veya dinamik `getattr`-tabanlı string-den-fonksiyon-çözme gibi dolaylı dispatch mekanizmaları kullanılmaz (bkz. Bölüm 19).
- **Fonksiyon imzaları:** Bir builder fonksiyonu, ihtiyaç duymadığı bilgiye (örn. `report_type`) erişemez — bu, imza incelemesiyle test edilir (`test_hidden_report_type_access_prevention_via_signature_inspection` deseni: builder kaynak kodunda ilgili değişken adının hiç geçmediğini doğrulamak).
- **None-safety:** Eksik/hesaplanamayan bir değer, asla sıfır veya boş string ile "doldurulmaz" — `None` olarak kalır ve tüketen kod, `None` durumunu açıkça ele alır (bkz. Bölüm 12).
- **Türkçe içerik, İngilizce kod:** Kullanıcıya gösterilecek metinler (`display_name_tr`, `reporting_period_label_tr`, hata/uyarı mesajları) Türkçedir; kod (değişken/fonksiyon/sınıf adları, docstring'ler, yorum satırları) da bu projede **Türkçe** yazılır (bu depoda gözlemlenen tutarlı konvansiyon) ama semboller (enum değerleri, alan adları) İngilizce kalır.

---

## 19. Yasaklar

Aşağıdaki işlemler, hiçbir engine/servis kodunda **kesinlikle yasaktır**. Her yeni dosya için, statik kaynak-inceleme testiyle (bkz. Bölüm 11) doğrulanması zorunludur:

- **`eval` yasak** — dinamik kod değerlendirme, hiçbir dispatch veya hesaplama yolunda kullanılmaz.
- **`exec` yasak** — dinamik kod çalıştırma, hiçbir koşulda kullanılmaz.
- **`datetime.now()` / `datetime.utcnow()` yasak** — determinizmi bozar (bkz. Bölüm 11); zaman damgaları yalnızca çağıranın sağladığı parametredir.
- **`uuid4()` yasak** — determinizmi bozar; kimlikler yalnızca çağıranın sağladığı parametredir.
- **`random.*` yasak** — determinizmi bozar; hiçbir hesaplama veya sıralama rastgeleliğe dayanmaz.
- **Global mutable state yasak** — modül seviyesinde, çalışma zamanında değiştirilebilen paylaşımlı bir değişken (registry'ler hariç, onlar da yalnızca import-anında bir kez doldurulur ve sonra salt-okunur muamele görür) tanımlanmaz.
- **Upstream recompute yasak** — bir downstream engine, upstream bir engine'in zaten hesapladığı bir değeri (örn. Credit Score'un Health Score'u) **asla yeniden hesaplamaz**; yalnızca referans alır. Bu, hem performans hem de "iki yerde aynı hesaplamanın farklı sonuç vermesi" riskini yapısal olarak imkânsız kılar.
- **AI/LLM entegrasyonu yasak** (v1 kapsamında) — hiçbir engine, bir dil modeli veya olasılıksal içerik üretme mekanizmasına bağımlı değildir; tüm çıktılar deterministik, kural-tabanlı hesaplamalardır.
- **Hardcoded "FINOS" / marka adı yasak (bkz. Bölüm 0 — Proje Kod Adı Politikası):** "FINOS" ismi (veya ileride belirlenecek herhangi bir nihai ticari marka/ürün adı), production kodunda aşağıdaki hiçbir alana sabit metin olarak gömülemez:
  - class / dataclass / enum adları,
  - registry adları,
  - database tablo ve kolon adları,
  - migration adları,
  - API endpoint yolları,
  - JSON schema alanları,
  - protocol ve interface adları,
  - warning / error / disclaimer metinleri,
  - rapor başlıkları,
  - dashboard metinleri,
  - kullanıcıya gösterilen (user-facing) UI metinleri.

  Kod adı, yalnızca Bölüm 0.7'nin izin verdiği dahili bağlamlarda (dokümantasyon, milestone adları, git commit geçmişi, geliştirme iletişimi, geçici proje klasörü adı) var olabilir. Production-facing bir metinde ürün adı gerekiyorsa, bu değer yalnızca açık bir `brand`/`product_name` parametresi veya ileride eklenecek bir branding configuration katmanı üzerinden geçirilir (bkz. Bölüm 0.9). Bir marka değişikliği, hiçbir finansal engine'i, veri modelini, registry'yi, API sözleşmesini veya database şemasını etkilememeli, hiçbir migration gerektirmemelidir (bkz. Bölüm 0.6).
- **Roll-up confidence/coverage yasak** — Bölüm 12'de tarif edildiği gibi, bir raporun/dashboard'un tek bir "genel güven skoru" hesaplanması yasaktır; her kaynağın kendi confidence/coverage'ı ayrı taşınır.
- **Sessiz veri silme yasak** — bir section/widget/uyarı, kullanıcıya görünmeden "kaybolamaz"; her zaman ya gösterilir ya da açık bir nedenle "kullanılamaz" olarak işaretlenir.
- **Duplicate payload owner yasak** — aynı canonical engine result payload'ı birden fazla tabloda tutulamaz; execution/history satırları yalnız Storage Ownership Matrix'in belirlediği tek owner'a FK ile bağlanır.
- **Event sourcing yasak** — immutable terminal audit history, event stream değildir; orchestration event replay, CQRS read model veya ara-state event persistence ayrı bir açık milestone olmadan eklenemez.
- **Saf Orchestrator'a persistence sızıntısı yasak** — `app/engines/analysis_orchestrator/**`, SQLAlchemy, ORM model, repository, artifact store veya başka bir persistence bileşeni import edemez.
- **Kapsam dışı prod kodu yasak** (ayrı milestone onayı olmadıkça) — onaylı Milestone 5.0D/5.0E route ve security envanteri dışındaki yeni API endpoint'i, queue/background worker, scheduler, batch runner, CLI/UI, gerçek PDF/DOCX/HTML render, provider-spesifik login/consent UI, browser session/cookie veya MFA enrollment, dashboard canlı yenileme/websocket/polling/cache katmanı. Milestone 5.0B persistence foundation, Milestone 5.0C senkron application/use-case katmanı, Milestone 5.0D'nin exact HTTP/integration adapter'ı ve Milestone 5.0E provider-neutral authentication/authorization katmanı bu genel yasağın açık ve sınırlı istisnalarıdır.

---

## 20. Dosya Yapısı

```
backend/
├── alembic/                          # DB migration'ları (head: b2e5f0c7d902)
├── alembic.ini
├── requirements.txt                  # fastapi, sqlalchemy, alembic, psycopg,
│                                      # pydantic-settings, pandas, openpyxl,
│                                      # pypdf, xlrd, pytest, httpx
├── docs/
│   ├── FINOS_ARCHITECTURE_BOOK.md    # BU DOKÜMAN — tek resmi mimari referans
│   └── FINOS_MILESTONE_<id>_<NAME>_DESIGN.md   # her milestone'un tasarım dokümanı
├── app/
│   ├── api/v1/                       # HTTP endpoint'leri
│   │   └── analysis_runs.py          # 5.0D — sekiz versioned analysis-run operation'ı
│   ├── models/                       # SQLAlchemy ORM modelleri
│   │   ├── orchestration_persistence.py  # 5.0B immutable run/execution/artifact/error modelleri
│   │   ├── analysis_run_scope_claim.py   # 5.0C/5.0D scope + initiating-subject reservation
│   │   ├── security.py               # 5.0E tenant/principal/binding/membership/role state'i
│   │   └── financial_analysis_result.py  # Financial owner + canonical result digest
│   ├── schemas/                      # Pydantic şemaları (API boundary)
│   │   └── analysis_runs_v1.py       # 5.0D versioned request/response/error sözleşmeleri
│   ├── services/                     # Kalıcılık-katmanı servisleri (bulk_upload,
│   │                                  # trial_balance_upload)
│   ├── core/config.py                # Uygulama konfigürasyonu
│   ├── db/base.py, session.py        # DB bağlantı/oturum yönetimi
│   ├── classification/               # Belge sınıflandırma pipeline'ı
│   ├── orchestration_persistence/    # 5.0B application/persistence boundary
│   │   ├── service.py                # Caller-neutral execute/resume/persist koordinasyonu
│   │   ├── repository.py             # SQLAlchemy terminal transaction + history pagination
│   │   ├── snapshot.py               # Fail-closed PreviousExecutionSnapshot builder
│   │   ├── ownership.py              # Storage Ownership Matrix registry'si (3 financial + 7 artifact)
│   │   ├── codec.py, artifacts.py    # Canonical JSON/SHA-256 ve payload tier seçimi
│   │   ├── blob.py                   # Durable filesystem staging → READY adapter'ı
│   │   └── ports.py, types.py        # Framework-neutral sınırlar ve immutable komut/projection'lar
│   ├── analysis_application/         # 5.0C framework-independent senkron use-case katmanı
│   │   ├── contracts.py              # Exact command/query/DTO/enum/ApplicationOutcome sözleşmeleri
│   │   ├── service.py                # Start/Resume/Retry/Cancel koordinasyonu
│   │   ├── query_service.py          # Scope-qualified read use-case'leri
│   │   ├── ownership.py              # BS/IS/Ratio post-result owner/lineage planı
│   │   ├── mapping.py, errors.py     # 5.0A mapping ve kapalı error policy
│   │   ├── active.py                 # Yalnız process-local cancellation/diagnostics
│   │   ├── ports.py                  # Authorization/audit/observability/scope/persistence portları
│   │   └── adapters/                 # SQLAlchemy read/persistence/scope-claim adapter'ları
│   ├── integrations/
│   │   └── analysis_http/            # 5.0D framework-independent integration adapters
│   │       ├── contracts.py          # Authentication/input/admission/runtime contracts
│   │       ├── security.py           # AuthenticationContext trust/freshness validation
│   │       ├── inputs.py             # Trusted document/result resolution + integrity checks
│   │       ├── admission.py          # Process-local bounded concurrency leases
│   │       ├── cursor.py             # Scope-bound canonical HMAC cursor
│   │       ├── mapping.py            # HTTP ↔ 5.0C explicit mapping
│   │       ├── read_facade.py         # Typed read error/category preservation
│   │       ├── runtime.py             # Production profile adapter validation
│   │       ├── dependencies.py        # Session-factory/transaction-aware composition
│   │       ├── router_security.py      # 5.0E request-bound authn/authz/audit session'ı
│   │       ├── legacy_security.py      # 28-route registry ve legacy tenant protection
│   │       └── errors.py              # ApplicationOutcome → safe HTTP error mapping
│   ├── security/                      # 5.0E Authentication & Authorization core/adapters
│   │   ├── contracts.py               # Identity/JWT/provisioning immutable sözleşmeleri
│   │   ├── jwt.py, jwks.py            # Provider-neutral verifier ve bounded key provider
│   │   ├── provisioning.py            # Idempotent authoritative identity provisioning
│   │   ├── historical_binding.py      # Historical tenant binding/quarantine servisi
│   │   ├── identity.py                # Fresh PostgreSQL identity/revocation resolution
│   │   ├── policy.py                  # 33 permission + 6 built-in role registry'si
│   │   ├── authorization_policy.py    # 17-reason deterministic policy engine
│   │   ├── policy_repositories.py     # Tenant-qualified PostgreSQL resource/policy adapter'ları
│   │   ├── authorization_adapter.py   # Değişmemiş 5.0C AuthorizationPort adapter'ı
│   │   └── request_authentication.py  # Request-bound trusted context provider'ları
│   ├── trial_balance/                # Mizan ayrıştırma, normalize etme, hesap ağacı
│   │   └── parsers/                  # Format-özel ayrıştırıcılar
│   └── engines/
│       ├── protocol.py               # EngineSourceRef/EngineRunContext sözleşmesi
│       ├── common/                   # PAYLAŞIMLI tip/registry kütüphanesi
│       │   ├── ratio_formulas.py             # RATIO_REGISTRY (57)
│       │   ├── benchmark_types.py            # BENCHMARK_REGISTRY_VERSION
│       │   ├── benchmark_registry.py         # BENCHMARK_REGISTRY (48)
│       │   ├── health_score_types.py         # HEALTH_SCORE_*_VERSION
│       │   ├── health_score_registry.py
│       │   ├── credit_score_types.py         # CREDIT_SCORE_*_VERSION
│       │   ├── credit_score_registry.py
│       │   ├── recommendation_types.py       # RECOMMENDATION_*_VERSION
│       │   ├── recommendation_registry.py    # RECOMMENDATION_RULES (39)
│       │   ├── report_types.py               # REPORT_*_VERSION, ReportType (7),
│       │   │                                 # ReportSectionCode (18)
│       │   ├── report_registry.py            # REPORT_SECTION_REGISTRY (18),
│       │   │                                 # REPORT_TYPE_REGISTRY (7)
│       │   ├── dashboard_types.py            # DASHBOARD_*_VERSION, DashboardType (2)
│       │   ├── dashboard_registry.py         # DASHBOARD_WIDGET_REGISTRY (10)
│       │   └── render_contract_types.py      # RENDER_CONTRACT_SCHEMA_VERSION
│       ├── balance_sheet/service.py
│       ├── income_statement/service.py
│       ├── financial_ratios/service.py
│       ├── benchmarks/service.py
│       ├── health_score/service.py
│       ├── credit_score/service.py
│       ├── recommendation/service.py
│       ├── executive_reports/
│       │   ├── __init__.py
│       │   └── service.py
│       ├── dashboards/
│       │   ├── __init__.py
│       │   └── service.py
│       ├── render_contract/
│       │   ├── __init__.py
│       │   └── service.py
│       └── analysis_orchestrator/    # Milestone 5.0A — koordinasyon katmanı (motor DEĞİL)
│           ├── __init__.py
│           ├── types.py              # EngineCode, RunStatus, DependencyRequirement, vb.
│           ├── registry.py           # ENGINE_DEPENDENCY_REGISTRY (10 düğüm, 24 kenar)
│           ├── dispatch.py           # ORCHESTRATOR_ENGINE_DISPATCH (registry DEĞİL)
│           ├── execution_plan.py     # DAG'dan deterministik topological sort
│           ├── fingerprint.py        # SHA-256 canonical-JSON input fingerprint
│           └── service.py            # run_orchestration()
└── tests/
    ├── README.md                     # İki katmanlı test stratejisi (SQLite/Postgres)
    ├── conftest.py                   # Autouse registry snapshot/restore fixture
    ├── data/synthetic/generate_fixtures.py
    ├── _orch_fakes.py                 # Orchestrator testleri için paylaşımlı sahte motor fabrikaları
    ├── test_analysis_runs_api.py          # 5.0D router/OpenAPI/subject/admission testleri
    ├── test_analysis_http_*.py            # Auth, resolver, cursor, read-facade testleri
    ├── test_analysis_api_integrity_postgres.py # Digest/subject DB bütünlük testleri
    ├── test_security_jwt.py, test_security_jwks.py
    ├── test_security_identity_repository_postgres.py
    ├── test_security_authorization_policy*.py
    ├── test_security_authorization_adapter*.py
    ├── test_security_request_authentication.py
    ├── test_security_legacy_routes.py
    ├── test_security_production_readiness.py
    └── test_<engine>_<aspect>_unit.py    # Her engine için ayrı test dosyaları
```

**Kesin kural:** `app/engines/**` altındaki hiçbir dosya, `sqlalchemy`, `fastapi`, veya `pydantic` import etmez. Bu, engine katmanının kalıcılık katmanından tamamen bağımsız test edilebilmesini sağlayan mimari sınırın somut karşılığıdır.

---

## 21. Naming Standardı

**Modül/dosya adları:**

- Her engine'in servis mantığı: `app/engines/<engine_name>/service.py` (+ `__init__.py`).
- Paylaşımlı tip tanımları: `app/engines/common/<engine_name>_types.py`.
- Paylaşımlı registry: `app/engines/common/<engine_name>_registry.py`.
- Test dosyaları: `tests/test_<engine_name>_<aspect>_unit.py` (örn. `test_health_score_critical_override_unit.py`, `test_report_swot_and_period_comparison_unit.py`).
- Milestone tasarım dokümanları: `docs/FINOS_MILESTONE_<id>_<UPPER_SNAKE_NAME>_DESIGN.md` (örn. `FINOS_MILESTONE_4_3F_RECOMMENDATION_ENGINE_DESIGN.md`).

**Sembol adları:**

- Enum sınıfları: `PascalCase` (`ReportType`, `DetailLevel`, `BuildPhase`).
- Enum değerleri (Python tarafı): `UPPER_SNAKE_CASE` (`ReportType.CFO_EXECUTIVE_REPORT`); dış temsil (`.value`) `lower_snake_case` string (`"cfo_executive_report"`).
- Registry sabitleri: `UPPER_SNAKE_CASE` (`REPORT_SECTION_REGISTRY`, `RATIO_REGISTRY`).
- Versiyon sabitleri: `<COMPONENT>_SCHEMA_VERSION` / `<COMPONENT>_MODEL_VERSION` / `<COMPONENT>_REGISTRY_VERSION` / `ENGINE_VERSION` deseni.
- Section kodları: `SEC_<UPPER_SNAKE_DESCRIPTION>` (`SEC_SWOT`, `SEC_HEALTH_SCORE_BREAKDOWN`).
- Widget kodları: `WGT_<UPPER_SNAKE_DESCRIPTION>` (`WGT_HEALTH_SCORE_HEADLINE`).
- Servis fonksiyonları: fiil-öncelikli `snake_case` (`generate_executive_report`, `evaluate_benchmarks`, `compute_financial_health_score`, `preview_render_contract`).
- Hata sınıfları: `<Reason>Error` (`InvalidReportResultError`, `OverlappingFullDetailSectionsError`).

**Türkçe alan adları yalnızca içerik alanlarında kullanılır** (`display_name_tr`, `reporting_period_label_tr`) — yapısal/teknik alan adları her zaman İngilizcedir.

**Brand-independent naming (bkz. Bölüm 0 — Proje Kod Adı Politikası):** Yukarıdaki hiçbir sembol kategorisi (enum sınıfı, registry sabiti, section/widget kodu, servis fonksiyonu, hata sınıfı) "FINOS" ön eki veya kod adına referans içeremez — bugüne kadar gözlemlenen tüm gerçek semboller (`ReportType`, `HealthScoreResult`, `RATIO_REGISTRY`, `SEC_SWOT`, `generate_executive_report`, `InvalidReportResultError` gibi) zaten bu kurala uygundur ve bu, bilinçli bir mimari tercihin sonucudur, tesadüf değildir. Yeni eklenecek hiçbir sembol de bu kalıptan sapamaz — bir sembol adı, projenin kod adı değişse bile hiçbir zaman güncellenmeye ihtiyaç duymamalıdır. Dosya/doküman adlandırması (bu kitap, milestone dokümanları) bu kuralın istisnasıdır — Bölüm 0.7/0.10'da açıklandığı gibi, dahili dokümantasyon kod adını taşıyabilir; yasak yalnızca **production kodu ve kullanıcıya görünen yüzeyler** için geçerlidir.

---

## 22. Yeni Milestone Ekleme Prosedürü

Yeni bir milestone (yeni bir engine, yeni bir section/rapor tipi, yeni bir registry genişlemesi) eklenirken izlenmesi zorunlu adımlar:

1. **Bu kitabı oku.** Yeni milestone'un tasarımı, bu kitaptaki hiçbir kuralla (Bölüm 6-19) çelişemez. Çelişki varsa, önce bu kitabın kendisinin bir revizyon turuyla güncellenmesi gerekip gerekmediği açıkça tartışılır — sessizce yok sayılmaz.
2. **Tasarım dokümanı yaz** (`docs/FINOS_MILESTONE_<id>_<NAME>_DESIGN.md`) — yalnızca tasarım, kod/test yazılmaz. Kapsam sınırları, veri sözleşmeleri, dependency etkileşimi, açık kararlar listesi içerir.
3. **Plan → eleştiri → revize → onay döngüsü** — tasarım dokümanı, kullanıcı onayına kadar birden fazla revizyon turundan geçebilir. Her tur, önceki turun açık kararlarını kapatmaya odaklanır.
4. **Bağımlılık bütünlüğü kontrolü (Bölüm 17 kuralı):** Yeni bir section veya rapor tipi ekleniyorsa, her `aggregation_section`'ın `dependency_codes`'unun, onu kullanan her `ReportType`'ın kullanım tablosunda da bulunduğu elle doğrulanır — bu, registry'nin kendisi tarafından otomatik yakalanmaz (bkz. Bölüm 17, SWOT 5→7 dersi).
5. **Versiyon artırma kararı** (Bölüm 8) — yeni eklenen şey bir schema değişikliği mi, model değişikliği mi, yoksa ikisi de mi, açıkça belirlenir ve ilgili sabitler güncellenir.
6. **Onay sonrası, test-gated implementasyon:** Her adım için önce test, sonra üretim kodu; her adımın kendi testleri VE tam regresyon yeşil olmadan bir sonraki adıma geçilmez (bkz. Bölüm 15, Bölüm 23).
7. **Sandbox doğrulama** — hızlı geri bildirim için `run_tests.py` (veya güncel eşdeğeri) ile.
8. **Gerçek Docker doğrulama (zorunlu, nihai):** `PYTHONPATH=/app python -m pytest tests/ -v`, `0 failed` sonucu. Bu adım atlanamaz; sandbox sonucu tek başına yeterli kabul kriteri değildir.
9. **Kapsam dışı kontrolü (final scope check):** `git status`/`git diff --stat` ile yalnızca beklenen dosyaların değiştiği doğrulanır; kapsam dışı hiçbir dosyanın (alembic/, api/, protocol.py, vb.) dokunulmadığı teyit edilir.
10. **Revizyon raporu** — ne değişti, kaç test eklendi, hangi sayılar (registry boyutu, section sayısı) güncellendi, sandbox ve Docker sonuçları, Production Readiness durumu.
11. **Bu kitabın güncellenmesi (gerekirse):** Yeni milestone, bu kitapta tarif edilen genel bir kuralı somutlaştırıyorsa (yeni bir örnek olarak) veya yeni bir genel kural doğuruyorsa (SWOT 5→7 dersinde olduğu gibi), bu kitap ayrı bir, açıkça onaylanmış bir revizyon turunda güncellenir.
12. **Commit/push yalnızca açık kullanıcı onayıyla** (bkz. Bölüm 26) — hiçbir adımda otomatik commit/push yapılmaz.

---

## 23. Checklist (Genel Geliştirme)

Her implementasyon adımı için:

- [ ] Bu adımın testleri önce yazıldı mı (test-first)?
- [ ] Üretim kodu, yalnızca onaylanmış tasarım dokümanındaki kapsamı mı karşılıyor?
- [ ] Yeni registry kaydı, kayıt-anı doğrulamasından geçiyor mu (bilinmeyen/döngü/kendine-bağımlılık reddi)?
- [ ] Yeni dataclass'lar `frozen=True`, koleksiyonlar `tuple` mi?
- [ ] `datetime.now()`/`uuid4()`/`random.*` kaynak kodda yok mu (statik test ile doğrulandı mı)?
- [ ] Bu adımın testleri VE tam regresyon %100 yeşil mi?
- [ ] Registry boyutu (varsa) beklenen sabit sayıya mı eşit (`len(...) == N`)?
- [ ] Tekrarlı çağrı testi, registry'nin büyümediğini doğruluyor mu?
- [ ] İzole kayıt testi, global registry'ye sızmadığını doğruluyor mu?
- [ ] Yeni upstream-bağımlı bir alan, `None`-safety kuralına uyuyor mu (asla sıfır/boş ile doldurulmuyor mu)?
- [ ] Presentation-only invariant (varsa) property testiyle doğrulandı mı?
- [ ] **Production kodunda hard-coded "FINOS"/marka adı taraması yapıldı mı** (bkz. Bölüm 0, Bölüm 19) — yeni/değişen dosyalarda class/dataclass/enum adı, registry adı, DB tablo/kolon adı, migration adı, API path, JSON schema alanı, protocol/interface adı, warning/error/disclaimer metni, rapor başlığı, dashboard metni veya UI metni içinde "FINOS" (veya ileride belirlenecek marka adı) sabit metin olarak geçmiyor mu?

---

## 24. Production Readiness Checklist

Bir milestone'un "üretime hazır" (%100 Production Readiness) ilan edilebilmesi için:

- [ ] Tasarım dokümanındaki TÜM açık kararlar kapatıldı (sıfır açık karar).
- [ ] Onaylanmış kapsam ile implementasyon birebir örtüşüyor (kapsam sapması varsa, dokümana işlendi — bkz. Bölüm 22 madde 11).
- [ ] Sandbox test sonucu: 0 fail.
- [ ] **Gerçek Docker test sonucu: 0 fail** (zorunlu, sandbox yeterli değil).
- [ ] Tüm registry boyutları, beklenen sabit sayılarla eşleşiyor.
- [ ] `git status`/`git diff --stat`, yalnızca beklenen dosyaların değiştiğini gösteriyor.
- [ ] Kapsam dışı hiçbir alan dokunulmamış (`alembic/`, `app/api/`, `app/models/`, `app/engines/protocol.py` gibi, milestone kapsamında olmadıkça).
- [ ] Hiçbir yasak işlem (Bölüm 19) kaynak kodda yok.
- [ ] Determinizm property testleri (tekrarlı çağrı eşitliği) geçiyor.
- [ ] Presentation-only / read-only invariant'lar (varsa) property testleriyle doğrulandı.
- [ ] Versiyon sabitleri (schema/model), yapılan değişikliğin niteliğine uygun şekilde güncellendi (bkz. Bölüm 8).
- [ ] Revizyon raporu yazıldı — değişen dosyalar, eklenen test sayısı, sandbox/Docker sonuçları, kalan risk (varsa) açıkça listelendi.
- [ ] **Production kodunda hard-coded FINOS/marka adı taraması** temiz (bkz. Bölüm 0, Bölüm 19, Bölüm 23) — bu milestone'un dokunduğu hiçbir dosyada kod adı veya marka adı sabit metin olarak gömülü değil.
- [ ] **API/DB/schema/protocol isimlerinin brand-independent olduğu doğrulandı** — yeni/değişen API endpoint yolları, database tablo/kolon adları, JSON schema alanları ve protocol/interface adlarının hiçbiri "FINOS" veya herhangi bir marka adına referans içermiyor (bkz. Bölüm 0.4, Bölüm 21).
- [ ] **Marka değişikliğinin migration gerektirmediği doğrulandı** — bu milestone'un ürettiği hiçbir migration, registry kaydı veya API sözleşmesi, varsayımsal bir marka/ürün adı değişikliğiyle değişmek zorunda kalmaz (bkz. Bölüm 0.6).
- [ ] **Kullanıcıya gösterilen marka adının config kaynaklı olduğu doğrulandı** — bu milestone'da kullanıcı-yüzü (rapor başlığı, dashboard metni, disclaimer, UI metni) bir ürün/marka adı içeriyorsa, bu değer sabit metin değil, açık bir `brand`/`product_name` parametresi veya branding configuration katmanından geliyor (bkz. Bölüm 0.9).
- [ ] Persistence milestone'unda Storage Ownership Matrix tek owner sağlıyor; execution satırlarında duplicate payload yok.
- [ ] `run_id` uniqueness ve aynı ID/farklı fingerprint fail-closed davranışı gerçek PostgreSQL üzerinde doğrulandı.
- [ ] Resume scope, source execution, owner FK, canonical digest, engine/schema/model version ve input fingerprint bağları negatif testlerle doğrulandı.
- [ ] Canonical immutable orchestration tablolarında gerçek PostgreSQL `UPDATE` ve `DELETE` işlemleri trigger tarafından reddediliyor.
- [ ] Inline 256 KiB ve run başına 1 MiB bütçe tüm artifact yazma akışında uygulanıyor; external blob yalnız doğrulanmış READY locator ile bağlanıyor.
- [ ] Application core'un FastAPI, Pydantic, SQLAlchemy ve Alembic'ten transitively bağımsız olduğu import-guard testiyle doğrulandı.
- [ ] Start/Resume/Retry/Cancel command'ları, dört read query'si, kapalı enum'lar ve `ApplicationOutcome[T]` invariant'ları contract testleriyle doğrulandı.
- [ ] `RunScopeClaim` claim/verify/finalize akışı; aynı `run_id` için farklı company/period/tenant ve concurrent cross-tenant yarışlarında fail-closed davranıyor.
- [ ] BS, IS ve Ratio post-result financial owner/lineage assembly; failed/skipped/mixed sonuçlar ve source-role mapping ile doğrulandı.
- [ ] Concurrent idempotent loser'ın staged owner/lineage satırları SAVEPOINT rollback/discard sonrasında kalıcılaşmıyor.
- [ ] Pre-execution authorization, pre-persistence revalidation, required security audit ve best-effort observability sınırları negatif testlerle doğrulandı.
- [ ] Analysis router yalnız 5.0C application service/read facade üzerinden çalışıyor; engine veya orchestration repository'sine doğrudan çağrı yapmıyor.
- [ ] FastAPI/Pydantic yalnız API boundary'de; SQLAlchemy application contract/core sözleşmelerine sızmıyor.
- [ ] Production runtime profile eksik/fake authentication, allow-all authorization ve fake/no-op required security audit binding'lerini fail-closed reddediyor; readiness required adapter/config durumunu ayrıntı sızdırmadan doğruluyor.
- [ ] Raw identity header'ları reddediliyor; AuthenticationContext issuer, expiry, max-age, future-skew ve correlation kuralları negatif testlerle doğrulanıyor.
- [ ] Document ve trial-balance input'ları authoritative source'tan çözülüyor; scope/type/status ile checksum/canonical digest uyuşmazlıkları Orchestrator çağrısından önce fail-closed reddediliyor.
- [ ] Aynı `run_id` için tenant/company/period/initiating-subject uyuşmazlığı response projection öncesinde reddediliyor; wrong-scope persisted sonuç dışarı verilmiyor.
- [ ] HMAC history cursor canonical signed bytes, key rotation, constant-time signature, expiry ve scope/tamper kontrolleriyle doğrulanıyor.
- [ ] Global/tenant/opsiyonel-subject admission limitleri sonlu; saturation `429` + `Retry-After` üretiyor ve lease tüm terminal/hata yollarında bırakılıyor.
- [ ] HTTP error envelope raw exception/stack trace/hassas payload sızdırmıyor; post-persistence serialization failure yalnız güvenli recovery metadata'sı döndürüyor.
- [ ] API, PostgreSQL, authentication/security, concurrency/admission ve OpenAPI/schema kapanış testleri ayrı kapılar olarak `0 failed` sonucu veriyor.
- [ ] Post-commit audit failure canonical başarıyı warning ile koruyor; post-persistence DTO projection failure run'ı geri almadan read recovery sağlıyor.
- [ ] Local `ActiveExecutionPort` yalnız cancellation/diagnostics için kullanılıyor; same-process ve cross-process duplicate semantiği persistence-idempotency bakımından eşit.
- [ ] JWT doğrulaması issuer/audience/algorithm/time allowlist'lerini uygular; unknown `kid`, stale JWKS, key rotation/outage ve signature failure hiçbir koşulda fail-open olmaz.
- [ ] Tenant/principal/subject binding/membership/role state'i authoritative PostgreSQL'den fresh çözülür; principal ve membership revocation boundary'leri negatif ve mikrosaniyeli exact-boundary testleriyle doğrulanır.
- [ ] HUMAN/SERVICE permission eksenleri ayrıdır; 33 action, altı built-in rolün 198 hücreli matrisi, custom-role proof/version/digest ve unknown permission/role/version fail-closed davranışı exhaustive test edilir.
- [ ] Policy engine'in 17 reason'ı, 18 basamaklı precedence'i, 11 scope resolver'ı, owner/initiator predicate'leri ve Model A cross-tenant hiding davranışı deterministik/reachability testleriyle doğrulanır.
- [ ] Değişmemiş 5.0C `AuthorizationPort` adapter'ı required detailed audit delivery'yi ve pre-persistence identity/policy/resource revalidation'ı fresh state ile fail-closed uygular.
- [ ] Request-bound authentication/authorization context'i concurrent request'ler arasında sızmaz; raw token/claim/subject/issuer/tenant/PII safe error, audit, metric, log veya response yüzeyine çıkmaz.
- [ ] Executable route registry FastAPI envanteriyle exact eşleşir; yalnız live/ready public, analysis-run ve legacy route'ların tamamı protected'dır. Legacy read/write/bulk resolution yolları tenant-qualified'dır.
- [ ] Production composition fake/test authentication, allow-all authorization, no-op/in-memory required audit ve eksik dependency'yi reddeder; JWKS, PostgreSQL identity/policy ve audit availability readiness'i belirler.
- [ ] Authentication/authorization HTTP mapping'i `401/403/404/409/429/503`, `WWW-Authenticate`, existence hiding ve raw-exception redaction kurallarıyla contract testlerinden geçer.
- [ ] Security migration zinciri tek head'dir ve isolated PostgreSQL üzerinde `upgrade → downgrade → upgrade` çevrimini geçer.
- [ ] Commit/push YAPILMADI (yalnızca kullanıcı açıkça isterse yapılır).

---

## 25. Release Checklist

Bir milestone'un implementasyonu tamamlandıktan ve Production Readiness onaylandıktan sonra, bir "release" (commit + gerekirse push) için:

- [ ] Kullanıcıdan açık, yazılı release onayı alındı mı ("commit et", "push et" gibi bir talimat var mı)?
- [ ] Commit mesajı, proje konvansiyonuna uyuyor mu: `feat(<scope>): implement Milestone <id> <Name>` (bkz. Bölüm 26, gerçek git log örnekleri).
- [ ] `git status` çıktısı commit öncesi kullanıcıya gösterildi mi?
- [ ] Staged değişiklikler (`git diff --cached` veya `git add` sonrası `git status`) gözden geçirildi mi — beklenmeyen/hassas dosya (secret, `.env`, kişisel veri) yok mu?
- [ ] Bu kitabın (varsa) ilgili bölümleri, yeni milestone'un ürettiği genelleştirilmiş kuralları yansıtacak şekilde güncellendi mi?
- [ ] Milestone tasarım dokümanının durumu ("İmplementasyona hazır" → "Tamamlanmıştır") güncellendi mi?
- [ ] **Release öncesi son kod-adı taraması** tekrarlandı mı (bkz. Bölüm 0, Bölüm 24) — commit edilecek diff'te hard-coded "FINOS"/marka adı, brand-independent olmayan API/DB/schema/protocol ismi veya config-kaynaklı olmayan kullanıcı-yüzü marka metni yok?
- [ ] Push, yalnızca kullanıcı açıkça "push et" dediğinde yapılıyor mu (commit onayı, push onayı yerine geçmez)?

---

## 26. Git Workflow

**Commit mesajı konvansiyonu** (gerçek `git log` geçmişinden doğrulanmıştır):

```
feat(<scope>): <açıklama>
```

Gözlemlenen örnekler:

```
feat(recommendation): implement Milestone 4.3F Recommendation Engine
feat(credit-score): implement Milestone 4.3E Credit Score engine
feat(health-score): implement Milestone 4.3D Financial Health Score engine
feat(benchmarks): implement Milestone 4.3C benchmark engine
feat(ratios): implement Milestone 4.3B core financial ratios
feat(ratios): add financial ratio engine foundation
feat(analysis): add balance sheet and income statement engines
feat(bulk-upload): implement confirmation workflow
feat(classification): bulk document classification pipeline
feat(upload): persistent trial balance upload and analysis pipeline
feat(persistence): Company/FinancialPeriod/FinancialDocument altyapısı
```

**Scope adları**, ilgili engine/alanın kısa adıdır (`ratios`, `benchmarks`, `health-score`, `credit-score`, `recommendation`, `bulk-upload`, `classification`, `upload`, `persistence`, `analysis`).

**Kesin disiplin — bu depoda, bu ana kadar, HİÇBİR istisnası olmadan gözlemlenmiştir:**

- **Commit, yalnızca kullanıcının açık talimatıyla yapılır.** Bir milestone implementasyonu, testleri dahil %100 tamamlanmış olsa bile, kullanıcı "commit et" demeden commit edilmez.
- **Push, commit'ten ayrı bir onay gerektirir.** Commit onayı, push onayı anlamına gelmez.
- Milestone 4.4'ün implementasyonu bu kitabın yazıldığı an itibarıyla `git log`'da henüz görünmemektedir (son commit hâlâ `65934ed feat(recommendation): ...`) — bu, yukarıdaki disiplinin doğrudan kanıtıdır: 886/886 Docker-doğrulanmış bir milestone bile, açık kullanıcı onayı olmadan commit edilmemiştir.
- Doküman-only revizyon turları (örn. bu kitabın kendisi, veya bir tasarım dokümanının doc-sync revizyonu) da aynı kurala tabidir — hiçbir `.md` değişikliği, kullanıcı istemeden commit edilmez.

---

## 27. Mimari Prensiplerin Kısa Özeti

FINOS'un mimarisi, aşağıdaki yirmi altı prensibe indirgenebilir:

1. **Denetlenebilirlik önce gelir.** Her sayı, kaynağına kadar izlenebilir olmalıdır (provenance, source_engine_codes, section_source_mapping).
2. **Determinizm mutlaktır.** Aynı girdi → aynı çıktı, her zaman. Sistem saati, rastgelelik, global durum bu garantiyi asla bozamaz.
3. **Katmanlar tek yönlü ve döngüsüzdür.** Financial Statements → Ratios → Benchmarks → Health Score → Credit Score → Recommendation → (Executive Report / Dashboard) → Render Contract. Hiçbir motor, kendisinden sonrakini bekleyemez veya öncekini yeniden hesaplayamaz.
4. **Sunum katmanı asla yeni gerçek üretmez.** Executive Report, Dashboard, Render Contract — üçü de yalnızca var olan sonuçları seçer, biçimlendirir, sunar; hiçbiri yeni bir finansal yargı üretmez.
5. **Registry'ler kayıt anında doğrulanır, sonrasında donar.** Geçersiz bir kayıt, uygulama başlarken hemen patlar — çalışma zamanında sessizce kabul edilmez.
6. **Eksik veri, sıfır değildir.** `None`, her zaman `None` olarak kalır; asla sıfıra veya boşa yuvarlanmaz; her zaman bir `reason_code`'la açıklanır.
7. **Uyarı, veri silmez.** Uyumsuzluk/eksiklik, kullanıcıdan gizlenmez — açık bir `warning` ile birlikte sunulur.
8. **Immutability, güvenin temelidir.** Frozen dataclass + tuple koleksiyonlar, bir sonucun üretildikten sonra asla değişemeyeceğini garanti eder.
9. **Kapsam disiplini, her milestone'un sınırıdır.** Onaylanmayan hiçbir şey (API, persistence, gerçek render, frontend, auth, AI) o milestone'un kodunda yer almaz.
10. **Hiçbir şey, kullanıcı onayı olmadan kalıcılaşmaz.** Ne bir mimari karar, ne bir commit, ne bir push — hepsi açık, yazılı onay bekler.
11. **Kod adı, marka değildir; marka, koda gömülmez.** "FINOS" yalnızca dahili bir geliştirme kod adıdır (bkz. Bölüm 0); nihai ticari marka/ürün adı henüz belirlenmemiştir ve hiçbir production sembolüne, şemaya veya kullanıcı-yüzü metnine sabit olarak gömülemez — bir marka değişikliği, yalnızca gelecekteki bir konfigürasyon/branding katmanını etkilemeli, tek bir engine, registry, migration veya API sözleşmesini bile etkilememelidir.
12. **Koordinasyon, hesaplama değildir; Orchestrator finansal değer üretmez.** Analysis Orchestrator (Milestone 5.0A), dokuz motoru doğru sırada ve doğru girdilerle çağırır, durumlarını gözlemler, tek bir run-seviyeli sonuç üretir — ama hiçbir finansal değer hesaplamaz, hiçbir motorun sonucunu değiştirmez veya yeniden hesaplamaz. "Neyin hesaplanacağı" motorların, "ne zaman ve hangi sırada çağrılacağı" yalnızca Orchestrator'ın sorumluluğudur; bu ikisi asla karışmaz.
13. **Kalıcılık, saf Orchestrator'ın dışındadır.** SQLAlchemy, repository, snapshot ve artifact bileşenleri yalnız `app/orchestration_persistence/` sınırında yaşar; 5.0A public sözleşmeleri ve hesaplama/koordinasyon davranışı persistence için değiştirilmez.
14. **Her payload'ın tek canonical sahibi vardır.** Financial result veya orchestration artifact owner'ı Storage Ownership Matrix ile belirlenir; execution history payload kopyalamaz, owner'a bağlanır. Immutable audit history event sourcing değildir.
15. **Recovery fail-closed ve içerik-doğrulamalıdır.** Resume/reuse; scope, lineage, source execution, owner FK, digest ve sürüm/fingerprint bağlarının tamamı doğrulanmadan gerçekleşmez. Büyük payload yalnız doğrulanmış READY blob üzerinden terminal kayda bağlanır.
16. **Application Layer açık, framework-bağımsız bir use-case sınırıdır.** Exact command/query/DTO/enum ve `ApplicationOutcome[T]` sözleşmeleri 5.0A ile 5.0B'yi senkron olarak koordine eder; finansal hesaplama yapmaz ve FastAPI, Pydantic veya SQLAlchemy'yi application core'a taşımaz.
17. **Run ownership reservation, workflow state değildir.** `RunScopeClaim`, bir `run_id`'yi company/period/tenant/operation scope'una atomik ve fail-closed bağlar; job, scheduler, queue, durable execution registry veya event stream rolü üstlenmez. Idempotency'nin authoritative fingerprint kararı 5.0B'de kalır; process-local active registry yalnız cancellation/diagnostics içindir.
18. **Security audit, observability ve canonical state birbirinden ayrıdır.** Required security audit ve authorization kontrolleri execution/persistence öncesinde fail-closed'dur; best-effort observability correctness kaynağı değildir. Terminal commit sonrası audit veya DTO projection hatası canonical run'ı geri almaz ve açık warning/recovery sonucu üretir.
19. **HTTP boundary application core'u sarar, delmez.** API router yalnız versioned request/response mapping ve integration sorumluluklarını taşır; engine veya persistence repository'sini doğrudan çağırmaz. FastAPI/Pydantic dış boundary'de, application command/query/DTO sözleşmeleri framework dışında kalır.
20. **Kimlik caller header'ından değil, trusted context'ten gelir.** Raw identity header'ları güven kaynağı değildir. AuthenticationContext production composition tarafından sağlanır ve freshness/issuer/correlation kurallarıyla doğrulanır; authentication ile authorization ayrı fail-closed kararlardır.
21. **Persisted provenance, gerçek computation input'una cryptographic olarak bağlıdır.** Document ve analysis-result ID'leri yalnız metadata değildir; input authoritative resolver tarafından aynı scope/type/status ve checksum/canonical digest doğrulamasıyla materialize edilir. Bağ doğrulanmadan hesaplama başlamaz.
22. **Overload koruması idempotency değildir.** Process-local admission sonlu global/tenant/subject lease'leriyle senkron HTTP yükünü sınırlar ve saturation'ı `429` ile bildirir; distributed correctness, run ownership veya terminal idempotency kararı vermez.
23. **Authentication ve authorization ayrı, fail-closed güvenlik sınırlarıdır.** JWT/JWKS token'ın trusted issuer adına kimlik kanıtı olduğunu doğrular; PostgreSQL identity ve policy state'i bu kimliğin hangi tenant/resource action'ına erişebileceğini ayrıca belirler. Birinin başarısı diğerinin grant'i değildir.
24. **Tenant state ve permission state authoritative storage'dan fresh okunur.** Positive identity/authorization cache yoktur. Principal, membership, binding, role, policy veya resource revoke bir sonraki resolution/revalidation'da görülür; outage, unknown proof/version ve integrity failure izin üretmez.
25. **Kaynak varlığı tenant sınırını delemez.** Durable resource çözümleme yalnız tenant-qualified Model A lookup kullanır; unknown ve cross-tenant kaynak aynı hidden not-found sonucuna gider. Unscoped existence probe veya fallback yasaktır; owner ve initiator farklı semantik kimliklerdir.
26. **Route güvenliği executable registry ile kapalı envanterdir.** Yalnız açıkça public ilan edilen live/ready endpoint'leri authentication istemez. Analysis-run ve legacy yüzeylerin tamamı request-bound context, exact action authorization, tenant scoping, audit/redaction ve production composition doğrulamasına tabidir; sınıflandırılmamış route production-ready değildir.

Bu yirmi altı prensip, bu kitabın geri kalan bölümlerinin özüdür. Yeni bir milestone tasarlanırken bir kural belirsizse, doğru cevap her zaman bu yirmi altı prensibin en katı yorumudur.

---

*Bu doküman, FINOS mimarisinin Milestone 5.0E itibarıyla (1716 passed, 0 failed, 0 skipped; Docker-doğrulanmış JWT/JWKS, PostgreSQL identity/provisioning/revocation, authorization policy/adapter, request-bound context, route protection, audit/redaction, migration-cycle ve production readiness testleri dahil) durumunu yansıtır. Analysis Platform artık saf engine ve Orchestrator katmanları, immutable persistence/recovery foundation, framework-bağımsız application use-case katmanı, trusted/versioned HTTP integration boundary'si ve provider-neutral, fail-closed Authentication & Authorization katmanından oluşur. Güncel tek Alembic head `b2e5f0c7d902`'dir. Queue, worker, scheduler, batch runner, UI, distributed lock, automatic retry/backoff, provider-spesifik login/consent UI, browser session/cookie, MFA enrollment ve event sourcing mevcut değildir. 5.0A–5.0D public sözleşmeleri değişmemiştir. Gelecekteki her milestone bu kitaba uymalı; bu kitapla çelişen her tasarım kararı ayrı bir onaylı revizyon turunda bu kitaba işlenmelidir.*
