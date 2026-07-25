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
    generate_pdf_fixtures()
    print("Sentetik fixture'lar uretildi:", OUTPUT_DIR)


if __name__ == "__main__":
    sys.exit(main())
