"""
Belge türü tespiti. İçerik tabanlı sinyaller (PDF metni, Excel kolon
yapısı/sheet adı) HER ZAMAN dosya adından önceliklidir ve daha yüksek
confidence taşır -- yalnızca dosya adına güvenilmez.

Mizan yapısı tespitinde app.trial_balance.column_detector.detect_columns
BİLEREK tekrar kullanılır (salt-okunur import, trial_balance motoruna
hiçbir değişiklik yapılmaz) -- aynı kolon-alias mantığının iki yerde
ayrı ayrı bakımı gereksiz ve tutarsızlık riski taşır.
"""

from dataclasses import dataclass

from app.models.enums import DetectedDocumentType
from app.trial_balance.column_detector import detect_columns, normalize_text


REQUIRED_TRIAL_BALANCE_COLUMNS = {
    "account_code",
    "account_name",
    "debit",
    "credit",
}

# (normalize_text edilmiş anahtar kelime, tür, confidence)
PDF_KEYWORD_RULES: list[tuple[str, DetectedDocumentType, float]] = [
    ("kurumlar vergisi beyannamesi", DetectedDocumentType.CORPORATE_TAX_RETURN, 0.95),
    ("gecici vergi beyannamesi", DetectedDocumentType.TEMPORARY_TAX_RETURN, 0.95),
    ("bilanco", DetectedDocumentType.BALANCE_SHEET, 0.85),
    ("gelir tablosu", DetectedDocumentType.INCOME_STATEMENT, 0.85),
]

FILENAME_KEYWORD_RULES: list[tuple[str, DetectedDocumentType]] = [
    ("kurumlar vergisi", DetectedDocumentType.CORPORATE_TAX_RETURN),
    ("gecici vergi", DetectedDocumentType.TEMPORARY_TAX_RETURN),
    ("bilanco", DetectedDocumentType.BALANCE_SHEET),
    ("gelir tablosu", DetectedDocumentType.INCOME_STATEMENT),
    ("mizan", DetectedDocumentType.TRIAL_BALANCE),
]

# Bilinçli olarak LOW bandında (<0.70): yalnızca dosya adına dayanan bir
# tespit hiçbir zaman auto_matched olamamalı.
FILENAME_ONLY_CONFIDENCE = 0.60
SHEET_NAME_MIZAN_CONFIDENCE = 0.80
COLUMN_STRUCTURE_CONFIDENCE = 0.92


@dataclass
class DocumentTypeGuess:
    document_type: DetectedDocumentType
    confidence: float
    source: str
    snippet: str | None = None


def classify_from_pdf_text(pdf_text: str) -> DocumentTypeGuess | None:
    normalized = normalize_text(pdf_text)

    for keyword, doc_type, confidence in PDF_KEYWORD_RULES:
        if keyword in normalized:
            return DocumentTypeGuess(doc_type, confidence, "pdf_text", keyword)

    return None


def classify_from_excel(
    column_headers: list[str],
    sheet_names: list[str],
) -> DocumentTypeGuess | None:
    detected_columns = detect_columns(column_headers)

    if REQUIRED_TRIAL_BALANCE_COLUMNS.issubset(detected_columns.keys()):
        return DocumentTypeGuess(
            DetectedDocumentType.TRIAL_BALANCE,
            COLUMN_STRUCTURE_CONFIDENCE,
            "excel_column_header",
            "account_code + account_name + debit + credit kolonları tespit edildi",
        )

    for sheet_name in sheet_names:
        if "mizan" in normalize_text(sheet_name):
            return DocumentTypeGuess(
                DetectedDocumentType.TRIAL_BALANCE,
                SHEET_NAME_MIZAN_CONFIDENCE,
                "excel_sheet_name",
                sheet_name,
            )

    return None


def classify_from_filename(filename: str) -> DocumentTypeGuess | None:
    normalized = normalize_text(filename)

    for keyword, doc_type in FILENAME_KEYWORD_RULES:
        if keyword in normalized:
            return DocumentTypeGuess(
                doc_type,
                FILENAME_ONLY_CONFIDENCE,
                "filename",
                keyword,
            )

    return None


def classify_document_type(
    *,
    filename: str,
    pdf_text: str | None = None,
    excel_column_headers: list[str] | None = None,
    excel_sheet_names: list[str] | None = None,
) -> DocumentTypeGuess:
    if pdf_text:
        guess = classify_from_pdf_text(pdf_text)
        if guess is not None:
            return guess

    if excel_column_headers is not None or excel_sheet_names is not None:
        guess = classify_from_excel(
            excel_column_headers or [],
            excel_sheet_names or [],
        )
        if guess is not None:
            return guess

    guess = classify_from_filename(filename)
    if guess is not None:
        return guess

    return DocumentTypeGuess(DetectedDocumentType.UNKNOWN, 0.0, "none")
