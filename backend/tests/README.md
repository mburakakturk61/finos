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

## Bilinçli olarak yapılmayan bir şey

`backend/tests/data/generic/2024_detay_mizan.xlsx` gerçek, anonimleştirilmemiş
banka hesap bilgileri içeren bir mizan dosyasıdır. Hiçbir test bu dosyayı
kullanmaz; regresyon testi bellek içinde ürettiği kurgusal veriyle çalışır.
Bu dosyanın git geçmişinden temizlenmesi ayrı bir güvenlik görevi olarak ele
alınmalıdır (bkz. proje kök dizinindeki ilgili not / final rapor).
