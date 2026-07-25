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

## Bilinçli olarak yapılmayan bir şey

`backend/tests/data/generic/2024_detay_mizan.xlsx` gerçek, anonimleştirilmemiş
banka hesap bilgileri içeren bir mizan dosyasıdır. Hiçbir test bu dosyayı
kullanmaz; regresyon testi bellek içinde ürettiği kurgusal veriyle çalışır.
Bu dosyanın git geçmişinden temizlenmesi ayrı bir güvenlik görevi olarak ele
alınmalıdır (bkz. proje kök dizinindeki ilgili not / final rapor).
