# FINOS Architecture Blueprint v1.0

## 1. Ürün Tanımı

FINOS; şirketlerin mali verilerini farklı muhasebe programlarından, Excel dosyalarından ve vergi beyannamelerinden alarak standartlaştıran, doğrulayan, çok dönemli analiz eden ve banka kredi analizine uygun raporlar üreten finansal analiz platformudur.

FINOS'un ana kullanım senaryosu:

1. Firma oluşturulur.
2. Son üç mali dönem tanımlanır.
3. Her dönem için mizan ve beyanname yüklenir.
4. Dosyalar okunur ve standart veri modeline dönüştürülür.
5. Mizan ve beyanname verileri mutabakat edilir.
6. Finansal tablolar üretilir.
7. Dönemler karşılaştırılır.
8. Finansal oranlar hesaplanır.
9. Risk bulguları oluşturulur.
10. Kredi skoru ve yönetici özeti hazırlanır.

Örnek dönem seti:

- 2024 yıl sonu
- 2025 yıl sonu
- 2026 birinci geçici vergi dönemi

---

## 2. Temel Tasarım İlkeleri

### 2.1 Deterministik Finans Motoru

Tüm finansal hesaplamalar kod tarafından yapılır.

Yapay zekâ:

- Finansal oran hesaplamaz.
- Mizan toplamı hesaplamaz.
- Finansal tablo oluşturmaz.
- Eksik rakam üretmez.
- Varsayımı kesin bilgi gibi sunmaz.

Yapay zekâ yalnızca FINOS tarafından doğrulanmış verileri ve bulguları yorumlar.

### 2.2 Kaynak İzlenebilirliği

Her mali veri aşağıdaki bilgilere bağlanmalıdır:

- Firma
- Dönem
- Belge
- Sayfa veya satır
- Dosya adı
- Yükleme tarihi
- Parser sürümü
- Kullanılan kolon
- Orijinal değer
- Normalize edilmiş değer

### 2.3 Eksik Veri Yönetimi

Eksik veri sıfır kabul edilmez.

Örnek:

- Satış verisi bulunamadıysa `0` değil `null`
- Stok verisi yoksa stok devir hızı hesaplanmaz
- Gelir tablosu yoksa kârlılık analizi üretilmez
- Önceki dönem yoksa trend analizi yapılmaz

### 2.4 Muhasebe Programından Bağımsızlık

FINOS içinde bütün veriler ortak bir standart modele dönüştürülür.

Kaynaklar:

- Logo
- Mikro
- Netsis
- Luca
- ETA
- Zirve
- SAP
- Canias
- Nebim
- Genel Excel
- CSV
- PDF
- API

Finans motoru kaynak programı bilmez; yalnızca standart veri modelini kullanır.

---

## 3. Ana Sistem Katmanları

FINOS dört ana katmandan oluşur.

### 3.1 Data Ingestion Layer

Görevleri:

- Dosya yükleme
- Dosya türü tespiti
- Excel sayfa analizi
- Kolon tespiti
- Muhasebe programı tespiti
- Belge türü tespiti
- Dönem tespiti
- Sayısal değer normalizasyonu
- Hatalı satır ayıklama

### 3.2 Finance Engine

Görevleri:

- Standart veri modeli
- Hesap ağacı
- Mizan doğrulama
- Bilanço oluşturma
- Gelir tablosu oluşturma
- Nakit akış altyapısı
- Finansal oranlar
- Dikey analiz
- Yatay analiz
- Trend analizi
- Beyanname mutabakatı
- Risk kuralları
- Kredi skoru

### 3.3 Intelligence Layer

Görevleri:

- Deterministik içgörü üretme
- Risk açıklamaları
- Yönetici özeti
- Kredi analisti özeti
- CFO yorumu
- Eksik veri bildirimi
- Aksiyon önerileri

### 3.4 Presentation Layer

Görevleri:

- Web dashboard
- Firma ekranı
- Dönem ekranı
- Dosya yükleme ekranı
- Finansal tablolar
- Grafikler
- PDF raporu
- Excel dışa aktarma
- Banka analiz paketi

---

## 4. Temel Veri Modeli

### 4.1 Company

Bir analiz yapılan gerçek veya tüzel kişiyi temsil eder.

Alanlar:

- `id`
- `legal_name`
- `trade_name`
- `tax_number`
- `tax_office`
- `registration_number`
- `nace_code`
- `sector`
- `establishment_date`
- `country`
- `city`
- `currency`
- `created_at`
- `updated_at`

Kurallar:

- Vergi numarası firma içinde benzersiz olmalıdır.
- Bir firma birden fazla mali döneme sahip olabilir.
- Bir firma birden fazla belgeye sahip olabilir.

---

### 4.2 FinancialPeriod

Bir şirketin mali analiz dönemini temsil eder.

Alanlar:

- `id`
- `company_id`
- `year`
- `period_type`
- `period_number`
- `start_date`
- `end_date`
- `is_year_end`
- `months_covered`
- `status`
- `created_at`
- `updated_at`

`period_type` örnekleri:

- `year_end`
- `quarter`
- `temporary_tax`
- `monthly`
- `custom`

Örnekler:

```text
2024 yıl sonu
year = 2024
period_type = year_end
period_number = 4
months_covered = 12