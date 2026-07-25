"""
app.classification.* için gerçek, çalıştırılabilir birim testleri
(Milestone 2 / Adım 3). Yalnızca committed sentetik fixture'lar (bkz.
tests/README.md, "Sentetik fixture üretimi") ve düz metin girdileri
kullanılır -- backend/tests/data/generic/2024_detay_mizan.xlsx (gerçek,
anonimleştirilmemiş veri) hiçbir testte kullanılmaz.

app.trial_balance/** motoruna bu testlerde hiçbir şekilde dokunulmadı;
yalnızca app.classification paketi kapsanıyor.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.classification.company_identity_resolver import resolve_company_identity
from app.classification.document_classifier import classify_document_type
from app.classification.orchestrator import classify_file
from app.classification.pdf_text_extractor import extract_pdf_text
from app.classification.vkn import is_valid_vkn
from app.models.enums import DetectedDocumentType, PeriodType


FIXTURES_DIR = Path(__file__).parent / "data" / "synthetic"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


# --- VKN checksum -----------------------------------------------------


def test_vkn_valid_checksum():
    assert is_valid_vkn("1234567890") is True


def test_vkn_invalid_checksum():
    assert is_valid_vkn("1234567891") is False


# --- PDF metin çıkarımı -------------------------------------------------


def test_pdf_text_extraction_corporate_tax_return():
    content = _read_fixture("synthetic_corporate_tax_return.pdf")
    text = extract_pdf_text(content)

    assert "kurumlar vergisi" in text.lower()
    assert "2025" in text


# --- company_identity_resolver (düz metin, fixture gerekmez) -----------


def test_resolve_company_identity_labeled_valid_vkn():
    text = "Unvan: FINOS KURGUSAL TEST A.S.\nVergi Kimlik No: 1234567890\n"
    guess = resolve_company_identity(filename="test.pdf", content_text=text)

    assert guess.tax_number == "1234567890"
    assert guess.company_name == "FINOS KURGUSAL TEST A.S."
    assert guess.confidence == pytest.approx(0.95)
    assert guess.warnings == []


def test_resolve_company_identity_never_silently_discards_bad_vkn():
    text = "Unvan: FINOS KURGUSAL TEST A.S.\nVergi Kimlik No: 1234567891\n"
    guess = resolve_company_identity(filename="test.pdf", content_text=text)

    # Checksum başarısız olsa da VKN değeri raporlanmaya devam eder --
    # yalnızca confidence düşer ve bir warning eklenir.
    assert guess.tax_number == "1234567891"
    assert guess.confidence == pytest.approx(0.60)
    assert any(w["code"] == "VKN_CHECKSUM_FAILED" for w in guess.warnings)


# --- document_classifier (dosya adı fallback, düşük güven) --------------


def test_classify_document_type_filename_only_is_low_confidence():
    guess = classify_document_type(filename="2025_Bilanco.pdf")

    assert guess.document_type == DetectedDocumentType.BALANCE_SHEET
    assert guess.confidence < 0.70


# --- orchestrator.classify_file: uçtan uca sentetik fixture'lar ---------


def test_classify_corporate_tax_return_valid_vkn():
    content = _read_fixture("synthetic_corporate_tax_return.pdf")
    result = classify_file("2025 Kurumlar Vergisi Beyannamesi.pdf", content)

    assert result.document_type == DetectedDocumentType.CORPORATE_TAX_RETURN
    assert result.tax_number == "1234567890"
    assert result.year == 2025
    assert result.period_type == PeriodType.YEAR_END
    assert result.period_number == 4
    assert result.confidence_score >= Decimal("0.90")
    assert result.warnings == []


def test_classify_corporate_tax_return_bad_vkn_never_silently_discarded():
    content = _read_fixture("synthetic_corporate_tax_return_bad_vkn.pdf")
    result = classify_file("2024 Kurumlar Vergisi Beyannamesi.pdf", content)

    assert result.document_type == DetectedDocumentType.CORPORATE_TAX_RETURN
    assert result.tax_number == "1234567891"
    assert result.confidence_score == Decimal("0.60")
    assert any(w["code"] == "VKN_CHECKSUM_FAILED" for w in result.warnings)


def test_classify_temporary_tax_return():
    content = _read_fixture("synthetic_temporary_tax_return.pdf")
    result = classify_file("2026-1 Gecici Vergi Beyannamesi.pdf", content)

    assert result.document_type == DetectedDocumentType.TEMPORARY_TAX_RETURN
    assert result.year == 2026
    assert result.period_type == PeriodType.TEMPORARY_TAX
    assert result.period_number == 1
    assert result.confidence_score >= Decimal("0.90")


def test_classify_balance_sheet_infers_year_end_period():
    """
    Regresyon testi: period_detector başlangıçta bilanço/gelir tablosu
    için hiçbir dönem-tipi çıkarım kuralına sahip değildi; bu, period_type
    her zaman None kalıp confidence'ı gereksiz yere 0.00'a çekiyordu (bkz.
    orchestrator.py / period_detector.py'deki ANNUAL_LIKE_DOCUMENT_TYPES
    fallback'i). Bu test o düzeltmenin kalıcı olduğunu doğrular.
    """
    content = _read_fixture("synthetic_balance_sheet.pdf")
    result = classify_file("Bilanco.pdf", content)

    assert result.document_type == DetectedDocumentType.BALANCE_SHEET
    assert result.year == 2025
    assert result.period_type == PeriodType.YEAR_END
    assert result.period_number == 4
    assert result.confidence_score > Decimal("0.00")
    assert any(w["code"] == "PERIOD_TYPE_INFERRED" for w in result.warnings)


def test_classify_income_statement_infers_year_end_period():
    content = _read_fixture("synthetic_income_statement.pdf")
    result = classify_file("Gelir Tablosu.pdf", content)

    assert result.document_type == DetectedDocumentType.INCOME_STATEMENT
    assert result.year == 2025
    assert result.period_type == PeriodType.YEAR_END
    assert result.confidence_score > Decimal("0.00")


def test_classify_trial_balance_xlsx_detects_type_without_identity():
    """
    Düz bir mizan .xlsx dosyasında (yalnızca hesap kodu/adı/borç/alacak
    kolonları) firma kimliği (VKN/unvan) genellikle bulunmaz -- bu gerçek
    bir sınırlamadır, bir hata değil. document_type_confidence yüksek
    kalırken overall confidence_score (bileşenlerin min()'i olduğu için)
    düşük kalır; bu da bulk_upload servisinin item'ı needs_review'e
    düşürmesini doğru şekilde sağlar.
    """
    content = _read_fixture("synthetic_trial_balance.xlsx")
    result = classify_file("2025_Mizan.xlsx", content)

    assert result.document_type == DetectedDocumentType.TRIAL_BALANCE
    assert result.document_type_confidence >= Decimal("0.90")
    assert result.company_name is None
    assert result.tax_number is None
    assert result.confidence_score == Decimal("0.00")


def test_classify_legacy_xls_trial_balance():
    """
    .xls (legacy OLE2/BIFF) okuma xlrd motorunu gerektirir. xlrd
    requirements.txt'e eklendi ancak bu değişikliğin hazırlandığı
    sandbox'ta kurulu DEĞİL (PyPI ağ erişimi yok) -- bu yüzden bu test
    xlrd bulunamazsa zarifçe atlanır, sahte bir "geçti" sonucu üretmez.
    Yerelde `pip install -r requirements.txt` sonrası çalışır. Bkz.
    tests/README.md, "Milestone 2 / Adım 3" bölümü.
    """
    pytest.importorskip("xlrd")

    content = _read_fixture("synthetic_trial_balance.xls")
    result = classify_file("2025_Mizan.xls", content)

    assert result.document_type == DetectedDocumentType.TRIAL_BALANCE
