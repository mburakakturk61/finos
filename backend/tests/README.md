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

## 6. Milestone 4.2: Balance Sheet + Income Statement Engine

Bu adım Milestone 4.1'in altyapısı üzerine İKİ gerçek motor ekledi
(`app/engines/balance_sheet/**`, `app/engines/income_statement/**`,
paylaşılan yardımcılar `app/engines/common/**`de) ve registry'yi
`app/services/bulk_upload.py`'nin GERÇEK confirm dispatch akışına bağladı
(Milestone 4.1'deki "henüz bağlanmadı" kısıtı bilinçli olarak kaldırıldı).

### Yeni sentetik fixture'lar (`tests/data/synthetic/`)

`generate_fixtures.py`'ye eklenen fonksiyonlarla üretildi, tamamen kurgusal:

- `synthetic_balance_sheet_direct.xlsx` / `synthetic_income_statement_direct.xlsx`
  (EBIT satırı YOK) / `synthetic_income_statement_with_ebit.xlsx`: etiketli
  (Kalem/Tutar) doğrudan-belge extractor'ının `.xlsx` yolunu test eder.
- `synthetic_balance_sheet_labeled.pdf` / `synthetic_income_statement_labeled.pdf`
  (EBIT yok) / `synthetic_income_statement_with_ebit_labeled.pdf`: AYNI
  içerik, metin tabanlı PDF yolunu test eder (mevcut, sınıflandırma amaçlı
  `synthetic_balance_sheet.pdf`/`synthetic_income_statement.pdf` fixture'larına
  DOKUNULMADI -- onlar hâlâ Milestone 2 sınıflandırma testlerinde kullanılıyor,
  gerçek finansal kalem içermiyor).
- `synthetic_trial_balance_matched_bs_is.xlsx`: yukarıdaki `_direct` xlsx
  fixture'larıyla BİREBİR aynı toplamlara türeyen, dengeli (borç=alacak) bir
  mizan -- reconciliation'ın "within_tolerance=True" pozitif yolunu ve
  aynı-batch trial_balance+BS/IS senaryolarını gerçek veriyle test etmek
  için. Tüm extraction/analiz sonuçları gerçek kod çalıştırılarak elle
  doğrulandı (bkz. aşağıdaki "gerçekten çalıştırılan testler").

### Yeni test dosyaları

- `test_engine_balance_income_statement_unit.py` (sqlalchemy'siz, GERÇEKTEN
  çalıştırıldı): extractor'ların (.xlsx + PDF, her iki motor) gerçek
  fixture'lardan doğru alanları çıkardığını; sanitize edilmiş hata
  mesajlarını (desteklenmeyen tür, bozuk dosya -- ham exception hiçbir zaman
  sızmaz); EBIT politikasını (`operating_profit` asla `ebit`'e sessizce
  kopyalanmaz, yalnızca doğrudan raporlandıysa dolar, aksi halde
  `EBIT_NOT_DETERMINABLE` warning'i); EBITDA'nın yalnızca hem `ebit` hem
  `depreciation_and_amortization` doluyken hesaplandığını;
  `trial_balance_fallback`'in "hiç hesap yok" (boş `account_details`) ile
  "gerçekten sıfır" durumunu ayırt ettiğini (0 DEĞİL, `None`); iki-seviyeli
  reconciliation toleransının üç bandını (yuvarlama -> sessiz, ara ->
  `warning`/`RECONCILIATION_DIFFERENCE`, üst -> `high`/
  `MATERIAL_RECONCILIATION_DIFFERENCE`) ve referans=0 iken sıfıra bölme
  olmadığını; vertical/horizontal/working-capital/structural-ratio
  analizlerinin eksik girdide `None` + doğru provenance ürettiğini; ve tam
  servis orkestrasyonunun (`analyze_balance_sheet`/`analyze_income_statement`)
  hem temiz reconciliation hem materyal fark hem trial_balance-fallback hem
  "hiçbir kaynak yok -> FAILED" yollarını GERÇEK fixture'larla ve GERÇEK
  (mock değil) `analyze_trial_balance` çağrısıyla doğru şekilde ürettiğini
  kapsar.
- `test_engine_registry_unit.py` (güncellendi): Balance Sheet/Income
  Statement'ın registry'de kayıtlı olduğu (hem `DetectedDocumentType` hem
  `DocumentType` üzerinden), kayıtsız kalan türlerin (cash_flow_statement,
  corporate/temporary_tax_return -- 4.4/4.5'i bekliyor) hâlâ güvenle `None`
  döndüğü, ve registry'nin ARTIK `app/services/bulk_upload.py`'ye bağlı
  OLDUĞU (Milestone 4.1'in aksi yöndeki testi güncellendi/tersine çevrildi)
  eklendi -- `app/services/trial_balance_upload.py`'nin (kapsam dışı) hâlâ
  `app.engines`'e dokunmadığı testi AYNEN korundu.
- `test_canonical_facts_unit.py` (küçük ek): `BalanceSheetFacts`'ın yeni 4
  alanının (`cash_and_equivalents`/`inventory`/`trade_receivables`/
  `trade_payables`) da diğerleri gibi `Decimal | None` ve varsayılan `None`
  olduğu.
- `test_bulk_upload_confirm_bs_is_integration.py` (sqlalchemy/fastapi
  gerektirir, bu sandbox'ta ÇALIŞTIRILAMADI -- yalnızca py_compile +
  elle çapraz kontrol): onaylanan Milestone 4.2 kararı #5'teki senaryo
  listesinin API-seviyeli karşılığı -- aynı-batch trial_balance+balance_sheet
  birlikte onaylanması (BS `source_mode=direct_document` kalır, trial_balance
  yalnızca `role=supporting_analysis` olarak eklenir); aynı-batch'te
  tanınamayan bir BS belgesi + başarılı trial_balance ->
  `source_mode=trial_balance_derived`, `role=trial_balance_fallback`;
  batch'ler ARASI (aynı-batch DEĞİL) bir Balance Sheet'in DB'deki ÖNCEDEN
  var olan COMPLETED trial_balance sonucunu kaynak göstermesi; HER İKİ
  durumda da `financial_analysis_result_sources.source_analysis_result_id`'nin
  GERÇEK, FAZ 3'te üretilmiş id'ye işaret ettiği (sahte/uydurma bir UUID
  DEĞİL, doğrudan DB'den `db_session` ile sorgulanarak doğrulandı); batch
  ortasında bir income_statement item'ı `ENGINE_FAILED` dönerse (trial_balance
  fallback'i de yoksa) trial_balance dahil HİÇBİR şeyin yazılmadığı
  (tüm-ya-da-hiçbiri korunuyor); ve doğrudan bir gelir tablosunun
  `EBIT_NOT_DETERMINABLE` uyarısını API yanıtında doğru sızdırdığı.

### Registry artık gerçek dispatch'e BAĞLI (Milestone 4.1'in tersine kararı)

`app/engines/registry.py` içindeki `TrialBalanceEngineAdapter`/
`BalanceSheetEngineAdapter`/`IncomeStatementEngineAdapter`'ın ÜÇÜ de artık
`app/services/bulk_upload.py`'nin `_run_confirm_analyses`/
`_write_confirmed_records`'ı tarafından GERÇEKTEN çağrılıyor --
`CONTENT_REQUIRED_DETECTED_TYPES` sabit kümesi kaldırıldı, yerine
`_requires_content()` (registry lookup) geldi. trial_balance'ın davranışının
BİREBİR AYNI kaldığı, mevcut `test_bulk_upload_api.py`'deki TÜM trial_balance
confirm testlerinin (happy path, reuse, engine failure, duplicate, vb.)
hiçbir değişiklik gerektirmeden geçmeye devam etmesiyle kanıtlanmıştır --
`TrialBalanceEngineAdapter` artık `analyze_trial_balance`'ı DOĞRUDAN değil
registry üzerinden çağırıyor olsa da, sarma mantığı (aynı `content`/
`filename`, aynı dönüş şekli) DEĞİŞMEDİ.

### Aynı-batch dependency-aware orkestrasyon (onaylanan karar #5)

`_run_confirm_analyses` (FAZ 2) artık trial_balance türündeki item'ları ÖNCE
çalıştırıp başarılı sonuçlarını `identity_key` (VKN veya company_id +
yıl/dönem türü/dönem no -- gerçek DB id'si YOK, çünkü `mode="new"` bir
firma/dönem FAZ 3'e kadar var olmayabilir) ile anahtarlanan bir bellek-içi
haritada tutuyor. Aynı batch'teki Balance Sheet/Income Statement item'ları
eşleşen bir identity_key bulursa `context.trial_balance_pending_in_batch=True`
ile bu sonucu tüketiyor -- motor `EngineRunResult.pending_trial_balance_
source_role`'ü dolduruyor (sahte bir `analysis_result_id` ÜRETMEDEN). FAZ 3
(`_write_confirmed_records`) plan'ları dependency-first sırayla (trial_balance
ÖNCE, Python `sort()`'un stable olması sayesinde grup-içi orijinal sıra
korunarak) yazıyor; bir trial_balance'ın `FinancialAnalysisResult`'ı flush
edildiği AN, aynı identity_key'e sahip bekleyen `pending_trial_balance_
source_role`'ler gerçek id ile çözülüp `FinancialAnalysisResultSource`
satırına yazılıyor. Herhangi bir motor `ENGINE_FAILED` dönerse (FAZ 2'de)
mevcut TÜM-YA-DA-HİÇBİRİ davranışı korunuyor -- FAZ 3'e hiç geçilmiyor.

### `result_json` sözleşmesi (onaylanan karar #9)

Her iki motor de ortak üst-seviye anahtarları üretir: `engine`,
`engine_version`, `analysis_type`, `source_mode`, `facts`,
`vertical_analysis`, `horizontal_analysis`, `reconciliation`, `warnings`,
`missing_fields`, `calculation_provenance` (+ Income Statement'a özgü
`margins`, Balance Sheet'e özgü `working_capital`/
`preliminary_structural_ratios`). `calculation_provenance`'daki her giriş
`metric`/`formula`/`input_fields`/`missing_inputs`/`calculated` alanlarını
taşır -- `calculated=False` iken `missing_inputs` HER ZAMAN doludur (Milestone
4.2 sırasında `income_statement/analyzer.py::compute_margins`'de bulunan ve
düzeltilen bir kusur: `missing_inputs` her zaman boş `()` yazılıyordu,
`calculated=False` olsa bile -- artık hangi girdinin eksik olduğunu doğru
raporluyor).

### Bu sandbox'ın çalıştırma sınırlaması (yine değişmedi)

Aynı kısıt geçerli: `sqlalchemy`/`fastapi`/`alembic`/`psycopg`/`pytest`/
`httpx`/`pydantic`/`xlrd` bu sandbox'ta kurulu DEĞİL. `test_engine_balance_
income_statement_unit.py` (`app/engines/**` gibi sqlalchemy'ye bağımlı
OLMADIĞI için) `test_engine_registry_unit.py`/`test_chart_of_accounts_
parity.py`/`test_canonical_facts_unit.py` ile birlikte sandbox-only
`importlib` stub tekniğiyle GERÇEKTEN çalıştırıldı -- 4 dosya, TOPLAM 63
test, 63 passed / 0 failed / 0 skipped. `test_bulk_upload_confirm_bs_is_
integration.py` sqlalchemy/fastapi'ye bağımlı olduğu için bu sandbox'ta
çalıştırılamadı -- yalnızca `py_compile` ile sözdizimi kontrolünden ve
`test_bulk_upload_api.py`'deki mevcut confirm testi konvansiyonlarıyla elle
çapraz kontrolden geçirildi. Yerelde gerçek bir yeşil koşu için:

```
docker compose up -d db
cd backend
pip install -r requirements.txt
alembic upgrade head
pytest tests/ -v
```

## 7. Milestone 4.3A: Ratio Calculation Foundation

Bu adım Financial Ratio Engine'in (Milestone 4.3) yalnızca temel altyapısını
kurdu -- calculation strategy dispatch sistemi, computation status
sözleşmesi, ilk 9 ortak oranın merkezi kaydı (current_ratio/
working_capital_ratio/net_working_capital/debt_ratio/equity_ratio/
debt_to_equity/gross_profit_margin/operating_profit_margin/
net_profit_margin) ve Balance Sheet/Income Statement motorlarının bu
merkezi kaynağa yönlendirilmesi. Tam kapsam ve gerekçe için bkz.
`docs/FINOS_MILESTONE_4_3_FINANCIAL_RATIO_ENGINE_DESIGN.md` (Bölüm R/S).

**KESİN KAPSAM SINIRI:** benchmark/Health Score/Credit Score/Recommendation
Engine implementasyonu YOK, migration YOK, `ratio_recompute.py` YOK,
`app/services/bulk_upload.py`'ye HİÇBİR dokunuş YOK -- `FinancialRatioEngineAdapter`
registry'de kayıtlı ama hiçbir gerçek akışa (API/bulk upload/recompute)
bağlı DEĞİL, yalnızca izole/birim testleriyle çağrılabilir.

### Değişen/yeni dosyalar

- `app/engines/common/ratio_formulas.py` (BÜYÜK ÖLÇÜDE YENİDEN YAZILDI):
  `ComputationStatus` enum (`calculated`/`missing_input`/
  `undefined_zero_denominator`/`no_obligation`/`not_applicable`/
  `not_calculable`), `ComputationOutcome` dataclass, KAPALI
  `CALCULATION_STRATEGIES` sözlüğü (`"sum_division"`/`"linear_combination"`
  -- eval/exec/dinamik expression YOK), `RatioFormulaMetadata`'nın revize
  şekli, `compute_registered_ratio()` (tek giriş noktası), `json_safe_to_decimal`
  (yeni), ilk 9 `RatioFormulaMetadata` kaydı. `safe_divide`/
  `decimal_to_json_safe` DEĞİŞMEDİ.
- `app/engines/common/calculation_provenance.py`: `ProvenanceEntry`'ye 3
  additive alan (`source_analysis_result_ids`/`reliability`/
  `rounding_applied`) -- `provenance_to_dict()` BİLİNÇLİ OLARAK
  DEĞİŞTİRİLMEDİ (hâlâ 5 anahtar, BS/IS'in dış sözleşmesini korur), yeni
  `provenance_to_dict_extended()` yalnızca Ratio Engine'in kendi
  result_json'unda kullanılıyor.
- `app/engines/common/ratio_derived_facts.py` (YENİ): `compute_total_liabilities`,
  `compute_days_in_period` (gerçek tarih farkı birincil, `months_covered*30`
  yalnızca açık düşük-güven fallback).
- `app/engines/protocol.py`: `EngineRunContext`'e 4 additive alan
  (`balance_sheet_result`/`income_statement_result`/`prior_period_balance_sheet_result`/
  `prior_period_income_statement_result`).
- `app/engines/financial_ratios/` (YENİ paket): `adapter.py`
  (`FinancialRatioEngineAdapter` -- ilk 9 oranı hesaplar, hiçbir akışa
  bağlı değil), `service.py` (`analyze_financial_ratios`).
- `app/engines/registry.py`: `FinancialRatioEngineAdapter` yalnızca
  `_ENGINE_BY_ANALYSIS_TYPE`'a eklendi -- `DetectedDocumentType`/
  `DocumentType` yönlendirme tablolarına EKLENMEDİ (Ratio Engine bir
  belge sınıflandırma sonucu olarak asla tetiklenmez).
- `app/engines/balance_sheet/analyzer.py`: `compute_preliminary_structural_ratios`/
  `compute_working_capital` artık `compute_registered_ratio()`'ya
  yönlendiriliyor -- `result_json` şekli DEĞİŞMEDİ, sayısal değerler
  Milestone 4.2 ile bit-bir aynı (bkz. aşağıdaki testler).
- `app/engines/income_statement/analyzer.py`: `compute_margins`'in 3/5
  alanı (`gross_margin_pct`/`operating_margin_pct`/`net_margin_pct`) aynı
  şekilde yönlendirildi; `ebit_margin_pct`/`ebitda_margin_pct` RATIO_REGISTRY'de
  henüz kayıtlı olmadığı için eski yerel hesaplamayı KORUYOR.
- `tests/test_ratio_formulas_unit.py` (YENİ, sqlalchemy'siz, GERÇEKTEN
  çalıştırıldı): strateji fonksiyonlarının saf/kapalı olduğu; None-eksik ile
  gerçek-sıfır (no_obligation/undefined_zero_denominator) ayrımı;
  desteklenmeyen strateji ve bilinmeyen key'in kontrollü `not_calculable`
  ürettiği (exception/Infinity/NaN YOK); ilk 9 oranın RATIO_REGISTRY
  envanteri; bağımsız elle hesaplanmış golden dataset'e karşı bit-bir
  eşleşme; BS/IS analyzer'larının merkezi registry ile (ve eski
  `safe_divide` tabanlı hesaplamayla) bit-bir aynı sonucu ürettiği (D.3
  invariant'ı); `provenance_to_dict()`'in hâlâ yalnızca 5 anahtar ürettiği;
  `ratio_derived_facts`'in days_in_period kaynak önceliği; `FinancialRatioEngineAdapter`'ın
  gerçek BS/IS fixture'larıyla doğru sonuç ürettiği VE hiçbir akışa bağlı
  olmadığının kaynak-metni taramasıyla doğrulanması.
- `tests/test_engine_registry_unit.py` (güncellendi): `AnalysisType.FINANCIAL_RATIOS`
  artık `get_engine_for_analysis_type` üzerinden kayıtlı (yeni pozitif
  test + `_REGISTERED_ANALYSIS_TYPES` güncellemesi) -- `_REGISTERED_DETECTED_TYPES`/
  `_REGISTERED_DOCUMENT_TYPES` BİLİNÇLİ OLARAK DEĞİŞMEDİ.

### Merkezi formül sözleşmesinin nihai şekli

`RatioFormulaMetadata(key, category, display_name_tr, unit,
calculation_strategy, numerator_fields=(), denominator_fields=(),
addend_fields=(), subtrahend_fields=(),
zero_denominator_status=UNDEFINED_ZERO_DENOMINATOR, quantize_exp="0.0001")`.
İki strateji: `"sum_division"` (topla+böl, `safe_divide` ile bit-bir aynı
quantize/percentage davranışı) ve `"linear_combination"` (topla-çıkar,
quantize yok). `compute_registered_ratio(key, facts, *, reliability="high")
-> ComputationOutcome(status, value, missing_inputs, warnings, reliability,
provenance)` -- TEK giriş noktası.

### Sıfır payda / eksik veri davranışı (somut örnekler)

`current_ratio`, `short_term_liabilities=None` iken -> `missing_input`.
`current_ratio`, `short_term_liabilities=Decimal("0")` (gerçek sıfır) iken
-> `no_obligation` (value=None, warning YOK -- olumlu/nötr durum).
`debt_to_equity`, `equity=Decimal("0")` iken -> `undefined_zero_denominator`
(value=None, `severity="high"` warning VAR). Hiçbir durumda
`Decimal("Infinity")`/`NaN` üretilmedi (`test_no_strategy_ever_produces_infinity_or_nan`
ile battery test edildi).

### Gerçekten çalıştırılan testler ve regresyon sonucu

Sandbox-only `importlib` stub tekniğiyle (bkz. yukarıdaki "Bu sandbox'ın
çalıştırma sınırlaması" bölümleri) GERÇEKTEN çalıştırıldı:

```
tests/test_ratio_formulas_unit.py            (YENİ, 41 test)
tests/test_engine_balance_income_statement_unit.py  (DEĞİŞMEDİ, 31 test)
tests/test_engine_registry_unit.py           (güncellendi, 22 test -- +2 yeni)
tests/test_canonical_facts_unit.py           (DEĞİŞMEDİ, 7 test)
tests/test_chart_of_accounts_parity.py       (DEĞİŞMEDİ, 5 test)
```

**TOPLAM: 106 test, 106 passed, 0 failed, 0 skipped.** Bu, Milestone
4.2 sonundaki 63 testlik temel çizgiye (bkz. yukarısı) göre net +43 test
(+41 yeni, +2 registry güncellemesi) -- ve o 63 testin TAMAMI hiçbir
değişiklik olmadan yeşil kalmaya devam ediyor (yalnızca
`test_registry_returns_none_for_unregistered_analysis_types`'ın beklenen,
gerekçeli güncellemesi -- bkz. yukarısı).

`app/services/bulk_upload.py`/`app/trial_balance/**`/sqlalchemy-bağımlı
diğer testler (`test_bulk_upload_confirm_bs_is_integration.py` vb.) bu
adımda HİÇ DEĞİŞTİRİLMEDİ ve zaten önceki milestone'larda da bu sandbox'ta
çalıştırılamıyordu (aynı `sqlalchemy`/`fastapi`/`pydantic` kısıtı, bkz.
altta) -- yeniden çalıştırılmaya çalışılmadı, çünkü bu milestone'un kapsamı
onları hiç etkilemedi. `app.classification.*` testleri de (bu adımın
kapsamı dışında, dokunulmadı) yeniden koşulmadı.

Yerelde gerçek bir yeşil koşu için:

```
docker compose up -d db
cd backend
pip install -r requirements.txt
alembic upgrade head
pytest tests/ -v
```

## 8. Milestone 4.3B: Core Financial Ratios (Likidite/Kârlılık/Borçluluk/Faaliyet/Verimlilik/Büyüme/Nakit)

Onaylanan tasarım dokümanı: `docs/FINOS_MILESTONE_4_3B_TECHNICAL_DESIGN.md`
(2. tur onay kararlarıyla güncellendi). Bölüm 9'daki 10 adımlık plan
AYNEN, sırayla, her adımın testleri tam yeşil olmadan bir sonrakine
geçilmeden uygulandı.

### Yeni/genişleyen dosyalar

- `app/engines/common/ratio_formulas.py`: `RatioFormulaMetadata`'ya 6 yeni
  additive alan (`depends_on_ratios`, `current_field`, `prior_field`,
  `scale_field`, `engine_dependency`, `direct_document_only_fields`); 2 yeni
  strateji (`growth_rate`, `scaled_division` -- `CALCULATION_STRATEGIES`
  artık 4 kayıt); `register_ratio_formula`'ya `depends_on_ratios`
  doğrulaması; `RATIO_REGISTRY_VERSION` `"1.0.0"` → `"1.1.0"`; 48 yeni
  `register_ratio_formula` çağrısı (9 → 57 toplam kayıt).
- `app/engines/common/ratio_derived_facts.py`: `compute_days_in_period`'in
  birincil formülü `(end_date-start_date).days` → `(end_date-start_date).
  days + 1` (KAPSAYICI) düzeltildi + geçersiz tarih sırası kontrolü eklendi;
  9 yeni fonksiyon (`compute_average_inventory/_trade_receivables/
  _trade_payables/_total_assets/_equity/_working_capital`,
  `compute_quick_assets`, `compute_capital_employed`, `compute_tax_expense`,
  `compute_invested_capital`).
- `app/engines/protocol.py`: `EngineRunContext`'e 3 additive alan
  (`period_start_date`, `period_end_date`, `period_months_covered`).
- `app/engines/financial_ratios/service.py`: orkestrasyon Adım 3-9 boyunca
  önemli ölçüde genişledi -- `_CATEGORY_RATIO_KEYS` artık 7 kategori (57
  oran); `NOT_APPLICABLE` kısayolu (`direct_document_only_fields`);
  `engine_dependency` kısayolu; `average_*` enjeksiyonu +
  `calculation_basis`/`reliability` çifti; `effective_tax_rate` aralık-dışı
  kontrolü; `sustainable_growth_rate`/`fixed_charge_coverage` için her-zaman-
  `not_calculable` kısayolları; `prior_*` alan enjeksiyonu (büyüme oranları).
- `app/engines/financial_ratios/adapter.py`: `context.period_start_date/
  end_date/months_covered` ve `context.prior_period_income_statement_
  result`'ın `analyze_financial_ratios`'a iletilmesi (adaptör HÂLÂ hiçbir
  gerçek akışa bağlı değil).
- `app/engines/income_statement/analyzer.py`: `compute_margins`'in KALAN 2
  alanı (`ebit_margin_pct`/`ebitda_margin_pct`) da artık `RATIO_REGISTRY`
  üzerinden hesaplanıyor (`ebit_margin`/`ebitda_margin` kayıtları) --
  "registry duplication" riski kapatıldı, BS/IS'te bağımsız ikinci bir
  aritmetik formül KALMADI. `result_json["margins"]` şekli (5 anahtar)
  DEĞİŞMEDİ.
- `tests/test_ratio_formulas_unit.py`: 41 → 79 test (+38 yeni).

### Kesin oran sayısı

`RATIO_REGISTRY` toplam **57 kayıt** (4.3A'nın 9'u + 4.3B'nin 48 yenisi):
liquidity=7, leverage=10, profitability=11, activity=10, efficiency=6,
growth=7, cash_flow=6. Her zaman `not_calculable` kalan 8 oran:
`fixed_charge_coverage`, `sustainable_growth_rate`, ve Nakit Akışı
kategorisinin 6'sı (`engine_dependency="cash_flow"` ile).

### Strategy sözleşmeleri (kapalı küme, 4 kayıt)

- `sum_division`: `sum(numerator_fields) / sum(denominator_fields)` (DEĞİŞMEDİ).
- `linear_combination`: `sum(addend_fields) - sum(subtrahend_fields)` (DEĞİŞMEDİ).
- `growth_rate` (YENİ): `(facts[current_field] - facts[prior_field]) / abs(facts[prior_field]) * 100`.
  `prior==0` → `UNDEFINED_ZERO_DENOMINATOR` (NO_OBLIGATION DEĞİL).
- `scaled_division` (YENİ): `(sum(numerator_fields) / sum(denominator_fields)) * facts[scale_field]`,
  `unit="percentage"` ise quantize sonrası ×100 (sum_division ile tutarlı).
  Eval/exec/expression parser YOK; her ikisi de aynı `try/except
  (InvalidOperation, OverflowError, ArithmeticError)` güvenlik desenini
  miras alır.

### `depends_on_ratios` orkestrasyonu ve dependency sırası

`register_ratio_formula`, `depends_on_ratios`'taki her key'in kayıt ANINDA
RATIO_REGISTRY'de zaten var olduğunu doğrular (döngüsel bağımlılık yapısal
olarak imkansız). Orkestrasyon (`analyze_financial_ratios`), her oran
hesaplandığında `facts[ratio_key] = outcome.value` enjekte eder; kategori
işleme sırası (`_CATEGORY_RATIO_KEYS` dict sırası: liquidity → leverage →
profitability → activity → efficiency → growth → cash_flow) ve
kategori-içi tuple sırası, gerçek bağımlılık zincirini önce hesaplayacak
şekilde elle düzenlenmiştir:
`net_working_capital` → `working_capital_to_total_assets`/
`working_capital_turnover`; `inventory_turnover`/`receivables_turnover`/
`payables_turnover` → `days_inventory_outstanding`/`days_sales_outstanding`/
`days_payables_outstanding` → `cash_conversion_cycle`; `effective_tax_rate`
→ `return_on_invested_capital`; `return_on_equity` → (referans olarak)
`sustainable_growth_rate` (her zaman not_calculable kısayoluyla, gerçek
formül hiç çağrılmıyor).

### Status davranışları (yeni/değişen kararlar)

- `short_term_debt_ratio`: `total_liabilities=0` → `NO_OBLIGATION`,
  `value=None` (sahte 0/Infinity YOK).
- `interest_coverage_ratio`/`ebitda_coverage_ratio`: `financing_expenses=0`
  → `NO_OBLIGATION` (finansman gideri yok, olumlu durum).
- `quick_ratio`/`cash_ratio`/`defensive_interval_ratio`/
  `inventory_turnover`/`receivables_turnover`/`payables_turnover`: BS
  `source_mode != "direct_document"` iken `NOT_APPLICABLE`
  (`compute_registered_ratio` hiç çağrılmadan, `direct_document_only_
  fields` kontrolüyle) -- `MISSING_INPUT` ile karıştırılmaz.
- Nakit Akışı kategorisinin 6 oranı: HER ZAMAN `NOT_CALCULABLE`
  (`engine_dependency="cash_flow"`, Cash Flow Engine Milestone 4.4'ü
  bekliyor) -- `MISSING_INPUT` DEĞİL.
- `sustainable_growth_rate`/`fixed_charge_coverage`: HER ZAMAN
  `NOT_CALCULABLE` (kâr dağıtım verisi / kiralama gideri hiçbir motorda
  yok, kanuni/varsayılan değer FABRİKE EDİLMEDİ).
- `effective_tax_rate`: `[0,1]` aralığı dışında bir değer üretirse
  GİZLENMEZ, `EFFECTIVE_TAX_RATE_OUT_OF_EXPECTED_RANGE` warning'i +
  `reliability="low"` eklenir.
- `growth_rate` ailesi (`sales_growth` vb.): `prior==0` →
  `UNDEFINED_ZERO_DENOMINATOR`.

### Average fallback politikası

`average_inventory`/`average_trade_receivables`/`average_trade_payables`/
`average_total_assets`/`average_equity`/`average_working_capital`: ikisi de
doluysa `(current+prior)/2`, `reliability="high"`,
`calculation_basis="two_period_average"`; yalnızca cari doluysa
`current`'a düşülür, `reliability="medium"`,
`calculation_basis="ending_balance_fallback"` -- **WARNING ÜRETİLMEZ**
(önceki dönemin bulunmaması normal bir iş durumudur, `days_in_period`'in
`months_covered*30` fallback'inden BİLİNÇLİ OLARAK farklı bir politika).
`average_total_assets`, `return_on_assets` VE `asset_turnover` tarafından
AYNI enjekte edilmiş değerden okunur (test edildi, Bölüm 8 riski kapatıldı).

### `days_in_period` düzeltmesi

Birincil formül `(end_date - start_date).days + 1` (KAPSAYICI) -- eski
(`+1`siz) formül 2024 (artık yıl) için 365 üretiyordu, DOĞRUSU 366'dır.
Zorunlu testler (hepsi geçti): 2025 (normal yıl) → 365; 2024 (artık yıl) →
366; tarihler yok + `months_covered=12` → 360 (`reliability="low"`,
warning VAR); `end_date < start_date` → kontrollü `not_calculable` +
`DAYS_IN_PERIOD_INVALID_DATE_ORDER` warning (ham exception YOK); `date.min`/
`date.max` gibi uç tarihlerde bile exception sızmıyor.

### Gerçekten çalıştırılan testler ve regresyon sonucu

Sandbox-only `importlib` stub tekniğiyle GERÇEKTEN çalıştırıldı:

```
tests/test_ratio_formulas_unit.py            (genişledi, 79 test -- +38 yeni)
tests/test_engine_balance_income_statement_unit.py  (DEĞİŞMEDİ, 31 test)
tests/test_engine_registry_unit.py           (DEĞİŞMEDİ, 22 test)
tests/test_canonical_facts_unit.py           (DEĞİŞMEDİ, 7 test)
tests/test_chart_of_accounts_parity.py       (DEĞİŞMEDİ, 5 test)
```

**TOPLAM: 144 test, 144 passed, 0 failed, 0 skipped.** Milestone 4.3A'nın
106 testlik temel çizgisine göre net +38 test -- ve o 106 testin TAMAMI
hiçbir değişiklik olmadan (veya yalnızca genişletilerek) yeşil kalmaya
devam ediyor; hiçbir mevcut test "gerekçesiz" değiştirilmedi (BS/IS
`result_json` şekli/sayısal değerleri Milestone 4.2 ile bit-bir aynı
kaldı -- `test_analyze_income_statement_provenance_contract` ve
`test_provenance_to_dict_unchanged_5_keys` benzeri regresyon testleri
DEĞİŞMEDEN geçiyor).

`app/services/bulk_upload.py`/`app/trial_balance/**`/sqlalchemy-bağımlı
diğer testler bu milestone'da HİÇ DEĞİŞTİRİLMEDİ ve zaten bu sandbox'ta
çalıştırılamıyor (aynı `sqlalchemy`/`fastapi`/`pydantic` PyPI proxy kısıtı)
-- kaynak-metin taramasıyla (`git status`/`grep`) bu dosyalara HİÇBİR
dokunuş olmadığı doğrulandı.

### Performans ölçümü

57 kayıtlı oranın TAMAMI için tek bir `analyze_financial_ratios()` çağrısı
(gerçek sentetik BS+IS fixture'larıyla, 500 tekrar ortalaması):
**~0.22 ms/çağrı** -- 4.3A'nın 9-oranlı sürümüne göre oran sayısı ~6x
arttı ama süre ihmal edilebilir düzeyde kaldı (üstel artış YOK,
`depends_on_ratios` zincirlerinin en derini 3 seviye -- `cash_conversion_
cycle` → `days_*` → `*_turnover` -- ve her seviye yalnızca bir sözlük
okuması).

### Git durumu

Hiçbir commit/push yapılmadı (`git log` hâlâ `b278a1d` -- 4.3A'nın son
commit'i). Değişen dosyalar: 6 mevcut motor dosyası (`ratio_formulas.py`,
`ratio_derived_facts.py`, `protocol.py`, `financial_ratios/service.py`,
`financial_ratios/adapter.py`, `income_statement/analyzer.py`) + 1 test
dosyası (`test_ratio_formulas_unit.py`) + bu README. Yeni dosya: `docs/
FINOS_MILESTONE_4_3B_TECHNICAL_DESIGN.md`. `app/trial_balance/**`,
`app/services/bulk_upload.py`, `alembic/`, `app/api/**`'e HİÇBİR dokunuş
YOK (kaynak-metin taramasıyla doğrulandı). Migration YOK. `ratio_
recompute.py` YOK. Benchmark/Health Score/Credit Score/Recommendation
Engine implementasyonu YOK.

## Bilinçli olarak yapılmayan bir şey

`backend/tests/data/generic/2024_detay_mizan.xlsx` gerçek, anonimleştirilmemiş
banka hesap bilgileri içeren bir mizan dosyasıdır. Hiçbir test bu dosyayı
kullanmaz; regresyon testi bellek içinde ürettiği kurgusal veriyle çalışır.
Bu dosyanın git geçmişinden temizlenmesi ayrı bir güvenlik görevi olarak ele
alınmalıdır (bkz. proje kök dizinindeki ilgili not / final rapor).
