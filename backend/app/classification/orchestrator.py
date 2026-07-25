"""
Tek bir dosyayı sınıflandırmak için tek giriş noktası. PDF/Excel ayrımı
yalnızca uzantıya değil, dosya imzasına (magic bytes) da bakılarak
yapılır -- yanlış etiketlenmiş uzantılara karşı ek bir sağlamlık katmanı.

Bu modül DB'ye HİÇ dokunmaz, saf/stateless'tır. Duplicate kontrolü
(checksum + mevcut kayıtlar) app/services/bulk_upload.py'de, DB
erişimi gerektiren bir sonraki katmanda yapılır.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.classification.company_identity_resolver import resolve_company_identity
from app.classification.document_classifier import classify_document_type
from app.classification.evidence import add_warning, new_warnings
from app.classification.excel_metadata_extractor import (
    ExcelExtractionError,
    extract_excel_metadata,
)
from app.classification.pdf_text_extractor import (
    PdfExtractionError,
    extract_pdf_text,
)
from app.classification.period_detector import detect_period
from app.models.enums import DetectedDocumentType, PeriodType


PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"  # .xlsx (zip tabanlı)
OLE2_MAGIC = b"\xd0\xcf\x11\xe0"  # legacy .xls


@dataclass
class ClassificationResult:
    document_type: DetectedDocumentType
    company_name: str | None
    tax_number: str | None
    year: int | None
    period_type: PeriodType | None
    period_number: int | None
    confidence_score: Decimal
    # Bileşen bazlı güvenler -- overall confidence_score bunların min()'i,
    # ancak servis katmanındaki duplicate tespiti (bkz.
    # app/services/bulk_upload.py) özellikle "firma + dönem yüksek
    # güvenle tespit edildi mi" sorusunu belge türü güveninden BAĞIMSIZ
    # sormak zorunda -- bu yüzden üçü de ayrı ayrı dışa açılıyor.
    document_type_confidence: Decimal = Decimal("0.00")
    company_identity_confidence: Decimal = Decimal("0.00")
    period_confidence: Decimal = Decimal("0.00")
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _sniff_kind(filename: str, content: bytes) -> str:
    """'pdf' | 'excel' | 'unknown' -- yalnızca uzantıya değil dosya imzasına
    da bakar (yanlış etiketlenmiş uzantılara karşı ek sağlamlık)."""

    header = content[:8]

    if header.startswith(PDF_MAGIC):
        return "pdf"
    if header.startswith(ZIP_MAGIC) or header.startswith(OLE2_MAGIC):
        return "excel"

    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        return "pdf"
    if lower_name.endswith((".xlsx", ".xls", ".xlsm")):
        return "excel"

    return "unknown"


def classify_file(filename: str, content: bytes) -> ClassificationResult:
    kind = _sniff_kind(filename, content)

    warnings = new_warnings()
    content_text: str | None = None
    excel_headers: list[str] | None = None
    excel_sheets: list[str] | None = None
    content_source_label = "pdf_text"

    if kind == "pdf":
        try:
            content_text = extract_pdf_text(content)
            if not content_text.strip():
                add_warning(
                    warnings,
                    code="PDF_NO_EXTRACTABLE_TEXT",
                    message=(
                        "PDF'ten metin çıkarılamadı; belge taranmış "
                        "(görüntü tabanlı) olabilir. OCR bu aşamada "
                        "desteklenmiyor."
                    ),
                )
                content_text = None
        except PdfExtractionError as error:
            add_warning(warnings, code="PDF_EXTRACTION_FAILED", message=str(error))
            content_text = None

    elif kind == "excel":
        content_source_label = "excel_content"
        try:
            metadata = extract_excel_metadata(content, filename)
            excel_headers = metadata.column_headers
            excel_sheets = metadata.sheet_names
            content_text = "\n".join(metadata.sheet_names + [metadata.sample_rows_text])
        except ExcelExtractionError as error:
            add_warning(warnings, code="EXCEL_EXTRACTION_FAILED", message=str(error))

    else:
        add_warning(
            warnings,
            code="UNSUPPORTED_FILE_TYPE",
            message=(
                "Desteklenmeyen dosya türü (yalnızca .pdf/.xlsx/.xls "
                "destekleniyor)."
            ),
        )

    doc_guess = classify_document_type(
        filename=filename,
        pdf_text=content_text if kind == "pdf" else None,
        excel_column_headers=excel_headers,
        excel_sheet_names=excel_sheets,
    )

    identity_guess = resolve_company_identity(
        filename=filename,
        content_text=content_text,
        content_source_label=content_source_label,
    )

    period_guess = detect_period(
        filename=filename,
        content_text=content_text,
        content_source_label=content_source_label,
        document_type_hint=doc_guess.document_type,
    )

    evidence: dict[str, Any] = {}
    if doc_guess.document_type != DetectedDocumentType.UNKNOWN:
        entry: dict[str, Any] = {
            "value": doc_guess.document_type.value,
            "source": doc_guess.source,
        }
        if doc_guess.snippet:
            entry["evidence"] = doc_guess.snippet
        evidence["document_type"] = entry

    evidence.update(identity_guess.evidence)
    evidence.update(period_guess.evidence)

    warnings.extend(identity_guess.warnings)
    warnings.extend(period_guess.warnings)

    doc_confidence = Decimal(str(doc_guess.confidence)).quantize(Decimal("0.01"))
    identity_confidence = Decimal(str(identity_guess.confidence)).quantize(Decimal("0.01"))
    period_confidence = Decimal(str(period_guess.confidence)).quantize(Decimal("0.01"))

    overall_confidence = min(
        doc_confidence, identity_confidence, period_confidence
    ).quantize(Decimal("0.01"))

    return ClassificationResult(
        document_type=doc_guess.document_type,
        company_name=identity_guess.company_name,
        tax_number=identity_guess.tax_number,
        year=period_guess.year,
        period_type=period_guess.period_type,
        period_number=period_guess.period_number,
        confidence_score=overall_confidence,
        document_type_confidence=doc_confidence,
        company_identity_confidence=identity_confidence,
        period_confidence=period_confidence,
        evidence=evidence,
        warnings=warnings,
    )
