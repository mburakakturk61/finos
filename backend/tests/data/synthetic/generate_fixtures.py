"""
Bu dizindeki (backend/tests/data/synthetic/) ikili (binary) fixture'ların
NASIL üretildiğini gösteren, tek seferlik, ÇALIŞTIRILABİLİR bir üretim
betiği (Milestone 2 / Adım 3). Bu bir test dosyası DEĞİLDİR ve pytest
tarafından toplanmaz (dosya adı test_*.py değil).

Neden bu yöntem: .xls (legacy OLE2/BIFF) ve .pdf üretimi için xlwt/fpdf2
gibi ek bir runtime/test bağımlılığı EKLEMEMEK istendi (kullanıcı talebi).
Bu sandbox'ta önceden kurulu olan LibreOffice (soffice --headless), tek
seferlik, proje bağımlılığı OLMAYAN bir dönüştürme aracı olarak kullanıldı:
  1) .xlsx / .txt kaynak içerik pandas/düz metin ile bellek içinde üretilir.
  2) `soffice --headless --convert-to xls:"MS Excel 97"` (veya `--convert-to
     pdf`) ile ikili hedef formata dönüştürülür.
  3) Yalnızca üretilen küçük ikili dosya committed edilir; LibreOffice'in
     kendisi requirements.txt'e EKLENMEDİ.

Yeniden üretmek için (LibreOffice kurulu bir makinede):
    cd backend/tests/data/synthetic
    python3 generate_fixtures.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


OUTPUT_DIR = Path(__file__).parent


def _convert_with_libreoffice(source: Path, target_format: str) -> None:
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            target_format,
            "--outdir",
            str(OUTPUT_DIR),
            str(source),
        ],
        check=True,
        capture_output=True,
    )


def generate_trial_balance_xlsx() -> None:
    """Tamamen kurgusal, küçük bir mizan -- gerçek bir hesap/bakiye
    içermez. account_code/account_name/debit/credit kolon-alias tespiti
    (app.trial_balance.column_detector, salt-okunur reuse) ve
    DetectedDocumentType.TRIAL_BALANCE sınıflandırması için kullanılır."""

    data = {
        "Hesap Kodu": ["100", "120", "320", "500"],
        "Hesap Adi": ["KASA", "ALICILAR", "SATICILAR", "SERMAYE"],
        "Borc": [10000.00, 25000.00, 0.00, 0.00],
        "Alacak": [0.00, 0.00, 15000.00, 20000.00],
    }
    dataframe = pd.DataFrame(data)
    target = OUTPUT_DIR / "synthetic_trial_balance.xlsx"
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="Mizan", index=False)


def generate_trial_balance_xls() -> None:
    """synthetic_trial_balance.xlsx'i legacy .xls (OLE2/BIFF) formatına
    LibreOffice ile dönüştürür -- xlwt kullanılmaz, OLE2 baytları elle
    üretilmez."""

    source = OUTPUT_DIR / "synthetic_trial_balance.xlsx"
    _convert_with_libreoffice(source, "xls:MS Excel 97")


def generate_balance_sheet_direct_xlsx() -> None:
    """Milestone 4.2: etiketli (Kalem/Tutar) bir bilanço -- app.engines.
    balance_sheet.extractor'ın doğrudan .xlsx yolunu ve app.engines.common.
    statement_labels.BALANCE_SHEET_LABEL_RULES eşlemesini test eder.
    Tamamen kurgusal; toplamlar bilinçli olarak dengeli (aktif=pasif)."""

    rows = [
        ("Hazir Degerler", "60000.00"),
        ("Stoklar", "35000.00"),
        ("Ticari Alacaklar", "45000.00"),
        ("I. Donen Varliklar Toplami", "150000.00"),
        ("II. Duran Varliklar Toplami", "90000.00"),
        ("Aktif Toplami", "240000.00"),
        ("Ticari Borclar", "30000.00"),
        ("Kisa Vadeli Yabanci Kaynaklar Toplami", "70000.00"),
        ("Uzun Vadeli Yabanci Kaynaklar Toplami", "50000.00"),
        ("Ozkaynaklar Toplami", "120000.00"),
        ("Pasif Toplami", "240000.00"),
    ]
    dataframe = pd.DataFrame(rows, columns=["Kalem", "Tutar"])
    target = OUTPUT_DIR / "synthetic_balance_sheet_direct.xlsx"
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="Bilanco", index=False)


def generate_income_statement_direct_xlsx() -> None:
    """Milestone 4.2: etiketli (Kalem/Tutar) bir gelir tablosu -- BİLEREK
    EBIT/amortisman satırı İÇERMEZ (EBIT_NOT_DETERMINABLE uyarı yolunu
    gerçek veriyle test etmek için). Tamamen kurgusal."""

    rows = [
        ("Brut Satislar", "600000.00"),
        ("Satis Indirimleri", "25000.00"),
        ("Net Satislar", "575000.00"),
        ("Satislarin Maliyeti", "350000.00"),
        ("Brut Satis Kari", "225000.00"),
        ("Faaliyet Giderleri", "110000.00"),
        ("Diger Faaliyetlerden Olagan Gelir ve Karlar", "15000.00"),
        ("Diger Faaliyetlerden Olagan Gider ve Zararlar", "8000.00"),
        ("Faaliyet Kari", "122000.00"),
        ("Finansman Giderleri", "20000.00"),
        ("Donem Kari", "102000.00"),
        ("Donem Net Kari", "81000.00"),
    ]
    dataframe = pd.DataFrame(rows, columns=["Kalem", "Tutar"])
    target = OUTPUT_DIR / "synthetic_income_statement_direct.xlsx"
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="GelirTablosu", index=False)


def generate_trial_balance_matched_bs_is_xlsx() -> None:
    """Milestone 4.2: `synthetic_balance_sheet_direct.xlsx` VE
    `synthetic_income_statement_direct.xlsx` ile BİLEREK birebir aynı
    toplamlara türeyen, dengeli (borç=alacak) bir mizan -- reconciliation'ın
    "within_tolerance=True, findings=[]" pozitif yolunu VE aynı-batch
    trial_balance+balance_sheet/income_statement senaryolarını gerçek
    veriyle test etmek için. "900" prefixli geçici kapanış hesabı, gelir
    tablosu hesaplarının (60-65) bu ara mizanda henüz kapatılmamış olması
    nedeniyle oluşan (kâr kadar) borç-alacak farkını dengeler -- 9 prefix'i
    ne BALANCE_SHEET_SECTIONS ne INCOME_STATEMENT_SECTIONS'ta olduğu için
    hiçbir bölüme sızmaz, yalnızca genel borç=alacak doğrulamasını geçirir.
    """

    rows = [
        ("100", "KASA", "150000.00", "0.00"),
        ("252", "BINALAR", "90000.00", "0.00"),
        ("320", "SATICILAR", "0.00", "70000.00"),
        ("400", "UZUN VADELI BANKA KREDILERI", "0.00", "50000.00"),
        ("500", "SERMAYE", "0.00", "120000.00"),
        ("600", "YURTICI SATISLAR", "0.00", "600000.00"),
        ("611", "SATISTAN IADELER", "25000.00", "0.00"),
        ("620", "SATILAN MAMULLER MALIYETI", "350000.00", "0.00"),
        ("630", "ARASTIRMA GELISTIRME GIDERLERI", "110000.00", "0.00"),
        ("640", "FAIZ GELIRLERI", "0.00", "15000.00"),
        ("653", "KOMISYON GIDERLERI", "8000.00", "0.00"),
        ("900", "GECICI KAPANIS HESABI", "122000.00", "0.00"),
    ]
    dataframe = pd.DataFrame(
        rows, columns=["Hesap Kodu", "Hesap Adi", "Borc", "Alacak"]
    )
    dataframe["Borc"] = dataframe["Borc"].astype(float)
    dataframe["Alacak"] = dataframe["Alacak"].astype(float)
    assert dataframe["Borc"].sum() == dataframe["Alacak"].sum()

    target = OUTPUT_DIR / "synthetic_trial_balance_matched_bs_is.xlsx"
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="Mizan", index=False)


def generate_income_statement_with_ebit_xlsx() -> None:
    """Milestone 4.2: yukarıdakiyle AYNI gelir tablosu, ancak EBIT ve
    amortisman/itfa gideri satırları AÇIKÇA eklendi -- resolve_ebit'in
    "belgede doğrudan raporlandı" (yol a) pozitif yolunu ve EBITDA
    hesaplamasını gerçek veriyle test etmek için."""

    rows = [
        ("Brut Satislar", "600000.00"),
        ("Satis Indirimleri", "25000.00"),
        ("Net Satislar", "575000.00"),
        ("Satislarin Maliyeti", "350000.00"),
        ("Brut Satis Kari", "225000.00"),
        ("Faaliyet Giderleri", "110000.00"),
        ("Diger Faaliyetlerden Olagan Gelir ve Karlar", "15000.00"),
        ("Diger Faaliyetlerden Olagan Gider ve Zararlar", "8000.00"),
        ("Faaliyet Kari", "122000.00"),
        ("Faiz ve Vergi Oncesi Kar", "125000.00"),
        ("Amortisman ve Itfa Giderleri", "18000.00"),
        ("Finansman Giderleri", "20000.00"),
        ("Donem Kari", "102000.00"),
        ("Donem Net Kari", "81000.00"),
    ]
    dataframe = pd.DataFrame(rows, columns=["Kalem", "Tutar"])
    target = OUTPUT_DIR / "synthetic_income_statement_with_ebit.xlsx"
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="GelirTablosu", index=False)


PDF_FIXTURES: dict[str, str] = {
    "synthetic_corporate_tax_return.pdf": (
        "KURUMLAR VERGISI BEYANNAMESI\n"
        "Hesap Donemi: 2025\n"
        "Unvan: FINOS KURGUSAL TEST ANONIM SIRKETI\n"
        "Vergi Kimlik No: 1234567890\n"
        "\n"
        "Bu belge tamamen kurgusaldir; gercek bir mukellefi veya mali "
        "veriyi temsil etmez. Milestone 2 / Adim 3 test fixture'i olarak "
        "uretilmistir.\n"
    ),
    "synthetic_corporate_tax_return_bad_vkn.pdf": (
        "KURUMLAR VERGISI BEYANNAMESI\n"
        "Hesap Donemi: 2024\n"
        "Unvan: FINOS KURGUSAL TEST IKINCI ANONIM SIRKETI\n"
        "Vergi Kimlik No: 1234567891\n"
        "\n"
        "Bu belge tamamen kurgusaldir. Vergi Kimlik No BILEREK checksum'dan "
        "gecmeyen bir deger icerir (VKN_CHECKSUM_FAILED uyarisini test "
        "etmek icin).\n"
    ),
    "synthetic_temporary_tax_return.pdf": (
        "GECICI VERGI BEYANNAMESI\n"
        "Donem: 2026/1\n"
        "Hesap Donemi Yili: 2026\n"
        "Unvan: FINOS KURGUSAL TEST UCUNCU LIMITED SIRKETI\n"
        "Vergi Kimlik No: 1234567890\n"
        "\n"
        "Bu belge tamamen kurgusaldir; gercek bir mukellefi temsil etmez.\n"
    ),
    "synthetic_balance_sheet.pdf": (
        "BILANCO\n"
        "Hesap Donemi: 2025\n"
        "Unvan: FINOS KURGUSAL TEST DORDUNCU ANONIM SIRKETI\n"
        "Vergi Kimlik No: 1234567890\n"
        "\n"
        "Bu belge tamamen kurgusaldir; gercek bir mukellefi temsil etmez.\n"
    ),
    "synthetic_income_statement.pdf": (
        "GELIR TABLOSU\n"
        "Hesap Donemi: 2025\n"
        "Unvan: FINOS KURGUSAL TEST BESINCI ANONIM SIRKETI\n"
        "Vergi Kimlik No: 1234567890\n"
        "\n"
        "Bu belge tamamen kurgusaldir; gercek bir mukellefi temsil etmez.\n"
    ),
    # Milestone 4.2: aşağıdaki üç PDF, yukarıdakilerin aksine GERÇEK
    # etiketli finansal kalemler içerir -- app.engines.balance_sheet/
    # income_statement.extractor'ın metin tabanlı PDF yolunu ve
    # app.engines.common.statement_labels eşlemesini test eder. Satır
    # sırası ve etiketler, label_line_parser'ın "her satırda kural
    # listesindeki İLK eşleşen anahtar kelime" davranışıyla yanlış alana
    # yazılmayacak şekilde BİLEREK seçildi (bkz. tests/README.md).
    "synthetic_balance_sheet_labeled.pdf": (
        "BILANCO\n"
        "Hesap Donemi: 2025\n"
        "Unvan: FINOS KURGUSAL TEST ALTINCI ANONIM SIRKETI\n"
        "Vergi Kimlik No: 1234567890\n"
        "\n"
        "Bu belge tamamen kurgusaldir; gercek bir mukellefi temsil etmez. "
        "Milestone 4.2 test fixture'idir.\n"
        "\n"
        "AKTIF (VARLIKLAR)\n"
        "Hazir Degerler: 45.000,00\n"
        "Stoklar: 28.000,00\n"
        "Ticari Alacaklar: 37.000,00\n"
        "I. Donen Varliklar Toplami: 110.000,00\n"
        "II. Duran Varliklar Toplami: 70.000,00\n"
        "Aktif Toplami: 180.000,00\n"
        "\n"
        "PASIF (KAYNAKLAR)\n"
        "Ticari Borclar: 22.000,00\n"
        "Kisa Vadeli Yabanci Kaynaklar Toplami: 55.000,00\n"
        "Uzun Vadeli Yabanci Kaynaklar Toplami: 35.000,00\n"
        "Ozkaynaklar Toplami: 90.000,00\n"
        "Pasif Toplami: 180.000,00\n"
    ),
    "synthetic_income_statement_labeled.pdf": (
        "GELIR TABLOSU\n"
        "Hesap Donemi: 2025\n"
        "Unvan: FINOS KURGUSAL TEST YEDINCI ANONIM SIRKETI\n"
        "Vergi Kimlik No: 1234567890\n"
        "\n"
        "Bu belge tamamen kurgusaldir; gercek bir mukellefi temsil etmez. "
        "Milestone 4.2 test fixture'idir. EBIT satiri BILEREK yok -- "
        "EBIT_NOT_DETERMINABLE uyarisini test eder.\n"
        "\n"
        "Brut Satislar: 520.000,00\n"
        "Satis Indirimleri: 20.000,00\n"
        "Net Satislar: 500.000,00\n"
        "Satislarin Maliyeti: 310.000,00\n"
        "Brut Satis Kari: 190.000,00\n"
        "Faaliyet Giderleri: 95.000,00\n"
        "Diger Faaliyetlerden Olagan Gelir ve Karlar: 12.000,00\n"
        "Diger Faaliyetlerden Olagan Gider ve Zararlar: 7.000,00\n"
        "Faaliyet Kari: 100.000,00\n"
        "Finansman Giderleri: 18.000,00\n"
        "Donem Kari: 82.000,00\n"
        "Donem Net Kari: 65.000,00\n"
    ),
    "synthetic_income_statement_with_ebit_labeled.pdf": (
        "GELIR TABLOSU\n"
        "Hesap Donemi: 2025\n"
        "Unvan: FINOS KURGUSAL TEST SEKIZINCI ANONIM SIRKETI\n"
        "Vergi Kimlik No: 1234567890\n"
        "\n"
        "Bu belge tamamen kurgusaldir; gercek bir mukellefi temsil etmez. "
        "Milestone 4.2 test fixture'idir. EBIT ve amortisman satirlari "
        "BILEREK eklendi -- pozitif EBIT/EBITDA yolunu test eder.\n"
        "\n"
        "Brut Satislar: 520.000,00\n"
        "Satis Indirimleri: 20.000,00\n"
        "Net Satislar: 500.000,00\n"
        "Satislarin Maliyeti: 310.000,00\n"
        "Brut Satis Kari: 190.000,00\n"
        "Faaliyet Giderleri: 95.000,00\n"
        "Diger Faaliyetlerden Olagan Gelir ve Karlar: 12.000,00\n"
        "Diger Faaliyetlerden Olagan Gider ve Zararlar: 7.000,00\n"
        "Faaliyet Kari: 100.000,00\n"
        "Faiz ve Vergi Oncesi Kar: 103.000,00\n"
        "Amortisman ve Itfa Giderleri: 14.000,00\n"
        "Finansman Giderleri: 18.000,00\n"
        "Donem Kari: 82.000,00\n"
        "Donem Net Kari: 65.000,00\n"
    ),
}


def generate_pdf_fixtures() -> None:
    # Ara .txt kaynak dosyaları KASITLI OLARAK bir sistem geçici dizininde
    # oluşturulur, committed fixture dizininde DEĞİL -- bazı mount'larda
    # (ör. bu betiğin ilk çalıştırıldığı sandbox) yazılan dosyalar
    # silinemiyor/yeniden adlandırılamıyor; geçici dizin bu sınırlamaya
    # tabi değildir ve `TemporaryDirectory` çıkışta kendini temizler.
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for pdf_filename, content in PDF_FIXTURES.items():
            txt_source = tmp_path / (Path(pdf_filename).stem + ".txt")
            txt_source.write_text(content, encoding="utf-8")
            _convert_with_libreoffice(txt_source, "pdf")


def main() -> None:
    generate_trial_balance_xlsx()
    generate_trial_balance_xls()
    generate_balance_sheet_direct_xlsx()
    generate_income_statement_direct_xlsx()
    generate_income_statement_with_ebit_xlsx()
    generate_trial_balance_matched_bs_is_xlsx()
    generate_pdf_fixtures()
    print("Sentetik fixture'lar uretildi:", OUTPUT_DIR)


if __name__ == "__main__":
    sys.exit(main())
