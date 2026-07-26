# FINOS backend test stratejisi

İki katmanlı bir yaklaşım kullanılıyor -- kapsamları kasıtlı olarak farklı:

## 1. SQLite tabanlı testler (`test_companies_api.py`, `test_periods_api.py`,
   `test_trial_balance_regression.py`, `test_trial_balance_upload_api.py`)

- In-memory SQLite üzerinde `Base.metadata.create_all()` ile şema kurulur
  (Alembic migration'ları çalıştırılmaz).
- Amaç: API sözleşmesi -- status code'lar, request/response şekli, iş
  kuralları (409 çakışma, 404, pagination, tarih doğrulama).
- Hızlı, Docker/Postgres gerektirmez, CI'de her zaman çalışır.
- Kapsam DIŞI: PostgreSQL'e özgü davranışlar (composite foreign key,
  RESTRICT silme davranışı, gerçek Alembic migration'ların hatasız
  uygulanması). SQLite foreign key/unique constraint desteği Postgres'le
  bire bir aynı değildir ve bu testler bunu doğrulamaz.

## 2. Gerçek PostgreSQL entegrasyon testleri (`test_postgres_integration.py`,
   `test_trial_balance_upload_postgres_integration.py`)

- `TEST_DATABASE_URL` (veya `DATABASE_URL`) ortam değişkeni erişilebilir
  gerçek bir PostgreSQL'e işaret ediyorsa çalışır; aksi halde
  `pytest.skip(...)` ile zarifçe atlanır -- sahte "geçti" sonucu üretmez.
- `alembic upgrade head` çalıştırarak migration'ların (94c5e7403385 +
  1f0e6d51f21b) gerçekten uygulanabilir olduğunu doğrular.
- `test_postgres_integration.py`: Company/FinancialPeriod/FinancialDocument
  composite foreign key tutarlılığı, `tax_number` unique ihlali ve
  `ondelete=RESTRICT` silme davranışı.
- `test_trial_balance_upload_postgres_integration.py` (Milestone 2 / Adım 2):
  `financial_documents.(period_id, checksum)` unique constraint,
  `FinancialAnalysisResult`'ın composite foreign key tutarlılığı
  (`document_id`+`company_id`+`period_id`), analiz sonucu olan bir belgenin
  `RESTRICT` ile silinememesi, ve `result_json` kolonunun gerçekten native
  `jsonb` olduğu (`pg_typeof`).
- Bunların hepsi SQLite'ta güvenilir biçimde doğrulanamayacak PostgreSQL'e
  özgü DB-seviyesi garantilerdir.

## Bilinen sınırlama (bu değişikliğin yapıldığı ortamda)

Bu değişiklik, PyPI'a ağ erişimi olmayan ve Docker/root yetkisi bulunmayan
bir sandbox içinde hazırlandı. Postgres entegrasyon testleri doğru
yazıldı ancak o ortamda fiilen çalıştırılıp doğrulanamadı. Yerelde
çalıştırmak için:

```
docker compose up -d db
cd backend
pip install -r requirements.txt
alembic upgrade head
pytest tests/test_postgres_integration.py tests/test_trial_balance_upload_postgres_integration.py -v
```

## 3. Milestone 2 / Adım 3: bulk upload + sınıflandırma önizlemesi

- `test_classification_unit.py`: `app.classification.*` (VKN checksum,
  PDF/Excel metadata çıkarımı, document/company/period tespiti,
  orkestratör) için gerçek, çalıştırılabilir birim testleri. Yalnızca bu
  dizindeki (`tests/data/synthetic/`) committed sentetik fixture'ları ve
  düz metin girdilerini kullanır. `app.trial_balance/**` motoruna hiçbir
  şekilde dokunulmadı.
- `test_bulk_upload_api.py`: SQLite üzerinde `POST /api/v1/bulk-uploads`
  ve okuma endpointlerinin API sözleşmesi -- çoklu dosya sınıflandırması,
  batch içi checksum çakışması (`duplicate`), önceki COMPLETED bir
  batch'e karşı `possible_duplicate`, onaylanmış bir `FinancialDocument`'a
  karşı kesin `duplicate`, boş dosya (`unrecognized`), pagination.
- `test_bulk_upload_postgres_integration.py`: `bulk_upload_items` ->
  `bulk_upload_batches` üzerindeki `RESTRICT` silme davranışı,
  `warnings_json`/`detection_evidence_json`'ın gerçekten native `jsonb`
  olduğu, tüm `ClassificationStatus`/`DetectedDocumentType` değerlerinin
  CHECK constraint'i ihlal etmediği, ve `checksum` kolonunda KASITLI
  OLARAK unique constraint olmadığının (aynı checksum'lu iki item serbestçe
  var olabilir) DB seviyesinde doğrulanması. Diğer Postgres testleri gibi
  erişilebilir bir PostgreSQL yoksa zarifçe skip edilir.

### Sentetik fixture üretimi (`tests/data/synthetic/`)

Tüm fixture'lar tamamen kurgusaldır (sahte firma adları, sahte ama
checksum kurallarına uyan/uymayan VKN'ler, küçük kurgusal tutarlar).
`.xlsx` fixture'ı doğrudan pandas/openpyxl ile bellek içinde üretilir.
`.xls` (legacy OLE2/BIFF) ve `.pdf` fixture'ları için **kasıtlı olarak
`xlwt`/`fpdf2` gibi ek bir runtime/test bağımlılığı eklenmedi** ve OLE2
baytları elle üretilmedi -- bunun yerine bu sandbox'ta önceden kurulu
olan **LibreOffice** (`soffice --headless`), tek seferlik, projeye
bağımlılık olarak eklenmeyen bir dönüştürme aracı olarak kullanıldı.

Üretim yöntemi tamamen `tests/data/synthetic/generate_fixtures.py`
içinde belgelenmiştir ve tekrar çalıştırılabilir:

```
cd backend/tests/data/synthetic
python3 generate_fixtures.py
```

Bu betik: (1) pandas ile kurgusal bir mizan `.xlsx`'i üretir, (2)
`soffice --headless --convert-to xls:"MS Excel 97"` ile aynı içeriği
legacy `.xls`'e dönüştürür, (3) beş adet kurgusal PDF için düz metin
içerikleri (ör. "KURUMLAR VERGISI BEYANNAMESI", "Vergi Kimlik No:
1234567890") bir sistem geçici dizininde yazıp `soffice --headless
--convert-to pdf` ile PDF'e dönüştürür. Yalnızca üretilen küçük ikili
dosyalar committed edilir; LibreOffice'in kendisi `requirements.txt`'e
eklenmedi.

Not: bu betiğin çalıştırıldığı sandbox'ta bu dizindeki dosyalar
silinemediği/yeniden adlandırılamadığı için (`.~lock.*#` LibreOffice kilit
dosyaları ve bir seferlik `synthetic_corporate_tax_return.txt` kalıntısı)
elle temizlenmesi gerekiyor -- bunlar zararsızdır (pytest tarafından
toplanmaz) ve yerelde güvenle `rm .~lock.* synthetic_corporate_tax_return.txt`
ile silinebilir.

### Bilinen sınırlama: `.xls` / `xlrd` skip

`excel_metadata_extractor.py`, `.xls` dosyaları için `xlrd` motorunu
kullanır (requirements.txt'e eklendi). Bu değişikliğin hazırlandığı
sandbox'ta PyPI ağ erişimi olmadığı için `xlrd` kurulamadı --
`test_classification_unit.py::test_classify_legacy_xls_trial_balance`
bu yüzden `pytest.importorskip("xlrd")` ile zarifçe SKIP edilir (sahte
bir "geçti" sonucu üretmez). `.xls` DESTEĞİNİN KENDİSİ kodda tamdır
(`_engine_for_filename` `.xls` için `xlrd` seçer, `synthetic_trial_balance.xls`
fixture'ı committed'dir) -- yalnızca bu SANDBOX'ta doğrulanamadı. Yerelde
`pip install -r requirements.txt` sonrası bu test de dahil olmak üzere
tüm sınıflandırma testleri çalışır:

```
cd backend
pip install -r requirements.txt
pytest tests/test_classification_unit.py tests/test_bulk_upload_api.py -v
```

## 4. Milestone 3 / Adım 1: bulk upload confirmation (review + onay)

- `test_bulk_upload_api.py` (aynı dosyaya eklendi, yeni bölüm): auto_matched
  item'larda `resolution_json`'ın otomatik ön-doldurulduğu (var olan/yeni
  firma+dönem taslağı), tek-item `PATCH .../items/{item_id}`, toplu karar
  `PATCH .../items` (kısmi başarı modeli), ve `POST .../confirm`'in tüm
  akışları: mutlu yol (Company/FinancialPeriod/FinancialDocument/
  FinancialAnalysisResult gerçekten oluşuyor mu -- `GET /api/v1/documents/
  {id}` ve `GET /api/v1/analyses/{id}` ile çapraz doğrulanıyor), aynı
  confirm çağrısı İÇİNDE ve AYRI batch'ler ARASINDA firma/dönem reuse,
  eksik dosya (`MISSING_FILE`), checksum uyuşmazlığı (`CHECKSUM_MISMATCH`),
  motor hatası sonrası HİÇBİR ŞEY yazılmadığının doğrulanması
  (`ENGINE_FAILED` -- Company sayısı değişmiyor, batch hâlâ `completed`),
  `(period_id, checksum)` çakışması (`DUPLICATE_DOCUMENT`), confirmed bir
  batch'in tekrar confirm edilememesi (409) ve item'larına PATCH
  uygulanamaması (409, immutability), ve ignored item'ların production
  tablolarına HİÇ yazılmadığının (`resulting_*_id` hepsi null) doğrulanması.
- `test_bulk_upload_postgres_integration.py` (aynı dosyaya eklendi):
  `BatchStatus.CONFIRMED` ve tüm `ItemReviewDecision` değerlerinin CHECK
  constraint'i ihlal etmediği, `resolution_json`'ın native `jsonb` olduğu,
  ve dört yeni `resulting_*_id` FK'sinin (companies/financial_periods/
  financial_documents/financial_analysis_results) her biri için RESTRICT
  silme davranışının ayrı ayrı doğrulanması.

### Migration sorunu ve düzeltmesi: PostgreSQL 63 karakter identifier sınırı

İlk yazılan migration'da (`9d4f1a7c6e52`) dört yeni `resulting_*_id`
FK'sinin adı, projenin standart naming convention'ıyla (bkz.
`app/db/base.py`) OTOMATİK üretildiğinde -- `financial_analysis_results`
gibi uzun referans tablo adlarıyla birleşince -- PostgreSQL'in 63 karakter
identifier sınırını AŞIYORDU:

```
fk_bulk_upload_items_resulting_analysis_id_financial_analysis_results  (69 karakter)
```

Bu, `alembic upgrade head`'in gerçek bir PostgreSQL'e karşı ilk
çalıştırılmasında fiilen tespit edildi. Düzeltme: dördü de (yalnızca
sınırı aşan değil, TUTARLILIK için) kısaltılmış, açık bir isimlendirme
kalıbına geçirildi -- `app/models/bulk_upload_item.py`'deki her
`ForeignKey(...)` çağrısına açık `name=` verildi (naming convention'ın
varsayılan üretimini bilerek geçersiz kılar) ve migration'daki
`op.create_foreign_key`/`op.drop_constraint` çağrıları aynı isimlerle
güncellendi:

```
fk_bulk_upload_items_resulting_company    (38 karakter)
fk_bulk_upload_items_resulting_period     (37 karakter)
fk_bulk_upload_items_resulting_document   (39 karakter)
fk_bulk_upload_items_resulting_analysis   (39 karakter)
```

Projedeki TÜM constraint/index adları (eski + yeni) bu düzeltmeden sonra
tek tek uzunluk kontrolünden geçirildi; en uzunu 62 karakterdir
(`fk_bulk_upload_items_resulting_document_id_financial_documents` --
DÜZELTİLMEDEN ÖNCEki hâliyle), düzeltme sonrası en uzunu 50 karakterdir.

### Confirm multipart sözleşmesi

`POST /api/v1/bulk-uploads/{batch_id}/confirm` iki form alanı alır:

- `manifest` (metin alanı, JSON dizisi): `[{"item_id": "<uuid>",
  "original_filename": "mizan.xlsx"}, ...]` -- `accepted` durumundaki ve
  içerik gerektiren (şu an yalnızca `trial_balance`) item'ların TAM
  listesi. `original_filename` yalnızca bilgi/log amaçlıdır.
- `files` (tekrarlı dosya alanı): her parçanın dosya ADI (`filename`)
  -- orijinal dosya adı DEĞİL -- ilgili item_id'nin kendisi (UUID string)
  olmalıdır. Orijinal dosya adları bir batch içinde tekil olmak zorunda
  olmadığı için eşleştirme anahtarı olarak güvenilmez; item_id her zaman
  tekildir.

Örnek (httpx/requests tarzı):

```python
import json, requests

manifest = json.dumps([
    {"item_id": "11111111-1111-1111-1111-111111111111", "original_filename": "mizan.xlsx"},
])
requests.post(
    f"{BASE_URL}/api/v1/bulk-uploads/{batch_id}/confirm",
    data={"manifest": manifest},
    files=[
        ("files", ("11111111-1111-1111-1111-111111111111", open("mizan.xlsx", "rb"), XLSX_MIME)),
    ],
)
```

İçerik GEREKTİRMEYEN türler (ör. `corporate_tax_return`, `balance_sheet`)
için o item'a karşılık gelen bir `files` parçası göndermeye GEREK YOKTUR
-- `FinancialDocument` staging metadata'sından oluşturulur (henüz
çalıştırılacak bir motor olmadığı için).

### Fiziksel dosya saklama -- confirm sonrasında da YOK (açık teknik borç)

Confirm, accepted item'lar için orijinal dosya baytının YENİDEN
gönderilmesini ister (bkz. yukarısı) ve bu baytları yalnızca FAZ 2'de
(bellekte, `analyze_trial_balance`'a girdi olarak) kullanır -- HİÇBİR
AŞAMADA diske veya DB'ye yazmaz. Confirm başarıyla tamamlandıktan SONRA
da orijinal dosya indirilemez veya yeniden parse edilemez; yalnızca
`FinancialDocument` metadata'sı (ad, checksum, boyut, tür) ve (varsa)
`FinancialAnalysisResult.result_json` kalıcı olur. Kalıcı bir object
storage (S3/MinIO vb.) eklenmesi bu adımın kapsamı DIŞINDA bırakıldı --
açık, kayıtlı bir teknik borçtur; gelecekteki bir milestone'un konusudur.

### Gelecekteki multi-tenant için not (bu adımda uygulanmadı)

`app/services/bulk_upload.py`'deki `_find_or_create_company` gibi
fonksiyonlar şu an VKN'ye göre TÜM sistemde (global) firma arar. SaaS/
multi-tenant bir yapı kurulduğunda bu aramanın tenant sınırına
çekilmesi gerekecektir (aksi halde bir tenant'ın firması başka bir
tenant'ın yüklemesiyle yanlışlıkla eşleşebilir). Bu milestone'da
`tenant_id` migration'ı KASITLI OLARAK eklenmedi; yalnızca bu not
bırakıldı.

### Bu sandbox'ın çalıştırma sınırlaması (değişmedi)

Milestone 2'den bu yana aynı sınırlama geçerli: bu sandbox'ta PyPI ağ
erişimi, Docker, root/sudo yetkisi ve gerçek bir PostgreSQL YOK; `fastapi`,
`sqlalchemy`, `alembic`, `psycopg`, `pytest`, `httpx`, `pydantic`, `xlrd`
kurulu DEĞİL ve kurulamıyor (`pip install` PyPI proxy'sinde 403 ile
başarısız oluyor). Bu yüzden `alembic upgrade head` ve yukarıdaki yeni
testler bu ortamda GERÇEKTEN çalıştırılıp doğrulanamadı -- yalnızca (a)
tüm yeni/değişen dosyalar `python3 -m py_compile` ile sözdizimi
kontrolünden geçirildi, (b) migration, modellerle satır satır elle
çapraz kontrol edildi, (c) tüm constraint/index adları programatik
olarak 63 karakter sınırına karşı tek tek ölçüldü, (d) `app.classification.*`
ve `app.trial_balance.*` gibi salt pandas/pypdf'e bağımlı, sqlalchemy
GEREKTİRMEYEN kod yollarındaki testler sandbox-only bir `importlib` stub
tekniğiyle gerçekten çalıştırıldı (bkz. aşağıdaki final rapor). Yerelde
gerçek bir yeşil koşu için:

```
docker compose up -d db
cd backend
pip install -r requirements.txt
alembic upgrade head
pytest tests/ -v
```

## 5. Milestone 4.1: Analysis Foundation (yalnızca altyapı, henüz motor yok)

Bu adım hiçbir yeni motor (Balance Sheet/Income Statement/Cash Flow/Tax
Return/Financial Ratio) implemente etmedi -- yalnızca Milestone 4'ün geri
kalanının üzerine kurulacağı şema/sözleşme altyapısını kurdu. `app/trial_balance/**`
ve mevcut bulk upload/trial balance upload dispatch akışlarına
DOKUNULMADI (registry henüz gerçek dispatch'e bağlı değil, bkz. aşağısı).

- `test_engine_registry_unit.py`: `app.engines.protocol`/`app.engines.registry`
  için gerçek, çalıştırılabilir birim testleri -- `EngineSourceRef`'in XOR
  kuralını Python seviyesinde erken doğrulaması, `TrialBalanceEngineAdapter`'ın
  gerçek `analyze_trial_balance`'ı çalıştırıp başarı/hata durumlarını doğru
  şekle sardığı (sentetik, tamamen kurgusal mizan verisiyle -- gerçek veri
  yok), registry'nin HEM `DetectedDocumentType` HEM `DocumentType` üzerinden
  aynı adaptöre eriştiği, kayıtlı olmayan tüm türler için güvenle `None`
  döndüğü, ve -- kapsam sınırı koruması olarak -- `app/services/bulk_upload.py`
  ile `app/services/trial_balance_upload.py`'nin `app.engines`'den hiçbir şey
  import ETMEDİĞİNİN kaynak metni okunarak doğrulanması (onaylanan Milestone
  4.1 kararı #1'in yanlışlıkla ihlal edilmediğinin garantisi).
- `test_chart_of_accounts_parity.py`: `app.engines.common.chart_of_accounts`
  içindeki BAĞIMSIZ Tekdüzen Hesap Planı kopyasının `app.trial_balance.
  financial_statements`'daki orijinal tanımla (`BALANCE_SHEET_SECTIONS`,
  `INCOME_STATEMENT_SECTIONS`, `get_numeric_prefix` davranışı) birebir eşit
  kaldığını doğrular -- iki kopya arasında ileride oluşabilecek sürüklenmeyi
  (drift) CI'de anında yakalayacak tek mekanizma (onaylanan Milestone 4.1
  kararı #4).
- `test_canonical_facts_unit.py`: `BalanceSheetFacts`/`IncomeStatementFacts`/
  `CashFlowFacts`/`TaxReturnFacts`'ın hem tam hem kısmi doldurulabildiği, TÜM
  parasal alanların `Decimal | None` olduğu (float DEĞİL), eksik verinin
  `None` kaldığı ve `0`'ın eksik veriyle karıştırılmadığı (onaylanan
  Milestone 4.1 kararı #6).
- `test_financial_analysis_result_sources_postgres_integration.py` (gerçek
  Postgres, skip-if-unavailable): `source_mode='direct_document'` iken
  `document_id`'nin NULL olamayacağı, `trial_balance_derived`/
  `multi_source_derived` iken NULL olabileceği, `fk_financial_analysis_results_
  period_company`'nin `document_id`'den bağımsız olarak company/period
  tutarlılığını HER ZAMAN garanti ettiği, `financial_analysis_result_sources`
  tablosundaki XOR kaynak kuralı, self-reference engeli, role<->kaynak-türü
  eşleşmesi (onaylanan karar #2), üç composite FK'nin farklı company/period'a
  ait kaynakları reddettiği, iki unique constraint'in yinelenen kaynak
  satırlarını engellediği, RESTRICT'in kaynak gösterilen belge/analiz
  sonucunun silinmesini engellediği, ve `source_mode`'un Python-seviyeli ORM
  default'unun (`direct_document`) doğru çalıştığı.

### Registry'nin gerçek dispatch'e bağlı OLMADIĞI (onaylanan karar)

`app/engines/registry.py` içindeki `TrialBalanceEngineAdapter`,
`app/trial_balance/service.py::analyze_trial_balance`'ı sarar ve registry
sözleşmesinin gerçek kodla (mock değil) çalıştığını kanıtlar -- ama
`app/services/bulk_upload.py` ve `app/services/trial_balance_upload.py`'nin
BUGÜNKÜ, 93/93 geçen üretim dispatch mantığı bu adımda DEĞİŞTİRİLMEDİ.
Registry'nin gerçek dispatch'e bağlanması Milestone 4.2'de, ilk yeni motor
(Balance Sheet/Income Statement) eklendiğinde yapılacak.

### PostgreSQL 63 karakter identifier ön-kontrolü (bu adımda da tekrarlandı)

Migration (`3a7c2e9f5b14`) yazılmadan ÖNCE tüm yeni constraint/index adları
programatik olarak ölçüldü (en uzunu 55 karakter,
`ix_financial_analysis_result_sources_analysis_result_id`) ve migration
tamamlandıktan sonra PROJE GENELİNDE (62 identifier, eski + yeni) tekrar
ölçüldü -- hepsi sınırın altında. İki yeni `UNIQUE` constraint
(`uq_financial_analysis_result_sources_by_document`/`_by_analysis`) özellikle
açık `name=` gerektiriyordu: ikisinin de `column_0_name`'i
`analysis_result_id` olduğu için varsayılan naming convention'a
bırakılsaydı ÇAKIŞIRDI -- `9d4f1a7c6e52`'deki 69-karakter dersiyle aynı
kategoriden bir tuzak.

### Bu sandbox'ın çalıştırma sınırlaması (yine değişmedi)

Aynı kısıt geçerli: `sqlalchemy`/`fastapi`/`alembic`/`psycopg`/`pytest`/
`httpx`/`pydantic`/`xlrd` bu sandbox'ta kurulu DEĞİL. `test_engine_registry_unit.py`,
`test_chart_of_accounts_parity.py`, `test_canonical_facts_unit.py`
(sqlalchemy/fastapi/pydantic'e bağımlı OLMADIKLARI için -- `app/engines/**`
bilinçli olarak `app/trial_balance/**` gibi izole tasarlandı) sandbox-only
`importlib` stub tekniğiyle GERÇEKTEN çalıştırıldı. `test_financial_analysis_
result_sources_postgres_integration.py` sqlalchemy'ye bağımlı olduğu için
bu sandbox'ta çalıştırılamadı -- yalnızca `py_compile` ile sözdizimi
kontrolünden ve migration/modelle satır satır elle çapraz kontrolden
geçirildi. Yerelde gerçek bir yeşil koşu için:

```
docker compose up -d db
cd backend
pip install -r requirements.txt
alembic upgrade head
pytest tests/test_engine_registry_unit.py tests/test_chart_of_accounts_parity.py \
  tests/test_canonical_facts_unit.py \
  tests/test_financial_analysis_result_sources_postgres_integration.py -v
```

## Bilinçli olarak yapılmayan bir şey

`backend/tests/data/generic/2024_detay_mizan.xlsx` gerçek, anonimleştirilmemiş
banka hesap bilgileri içeren bir mizan dosyasıdır. Hiçbir test bu dosyayı
kullanmaz; regresyon testi bellek içinde ürettiği kurgusal veriyle çalışır.
Bu dosyanın git geçmişinden temizlenmesi ayrı bir güvenlik görevi olarak ele
alınmalıdır (bkz. proje kök dizinindeki ilgili not / final rapor).
