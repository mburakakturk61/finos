"""
Yıl, dönem tipi ve dönem numarası tespiti. Çelişki (ör. dosya adından
çıkan yıl ile belge içeriğinden çıkan yıl uyuşmuyor) confidence'ı LOW
bandına zorlar ve bir warning üretir (Milestone 2 / Adım 3, madde 5).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.classification.evidence import add_warning, new_warnings
from app.models.enums import DetectedDocumentType, PeriodType
from app.trial_balance.column_detector import normalize_text


# document_classifier zaten bir tür tespit ettiyse (ör. bilanço/gelir
# tablosu/mizan), bu türler dönem-tipi metninde ("gecici vergi"/"kurumlar
# vergisi") kesin bir eşleşme taşımayabilir ama yine de tipik olarak
# yıllık/dönemsel finansal tablolardır -- bu yüzden "mizan" ile aynı
# fallback mantığına (çeyrek işareti varsa geçici, yoksa yıl sonu +
# PERIOD_TYPE_INFERRED) dahil edilirler. Bu olmadan bu türler her zaman
# period_type=None / confidence=0.0'da kalır ve overall_confidence'ı
# gereksiz yere sıfıra çeker.
ANNUAL_LIKE_DOCUMENT_TYPES = frozenset(
    {
        DetectedDocumentType.TRIAL_BALANCE,
        DetectedDocumentType.BALANCE_SHEET,
        DetectedDocumentType.INCOME_STATEMENT,
    }
)


YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
YEAR_QUARTER_PATTERN = re.compile(r"\b((?:19|20)\d{2})\s*/\s*([1-4])\b")

CONFLICT_CONFIDENCE_CAP = 0.50  # LOW bandının (<0.70) altında -- çelişki her zaman düşük güvene zorlanır


@dataclass
class PeriodGuess:
    year: int | None
    period_type: PeriodType | None
    period_number: int | None
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _find_year_quarter(text: str) -> tuple[int, int] | None:
    match = YEAR_QUARTER_PATTERN.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _find_year(text: str) -> int | None:
    match = YEAR_PATTERN.search(text)
    if match:
        return int(match.group())
    return None


def detect_period(
    *,
    filename: str,
    content_text: str | None = None,
    content_source_label: str = "pdf_text",
    document_type_hint: DetectedDocumentType | None = None,
) -> PeriodGuess:
    evidence: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []

    normalized_content = normalize_text(content_text) if content_text else ""
    normalized_filename = normalize_text(filename)

    content_year_quarter = _find_year_quarter(normalized_content) if content_text else None
    filename_year_quarter = _find_year_quarter(normalized_filename)

    content_year = (
        content_year_quarter[0]
        if content_year_quarter
        else (_find_year(normalized_content) if content_text else None)
    )
    filename_year = (
        filename_year_quarter[0]
        if filename_year_quarter
        else _find_year(normalized_filename)
    )

    year = content_year if content_year is not None else filename_year
    year_source = (
        content_source_label
        if content_year is not None
        else ("filename" if filename_year is not None else None)
    )

    conflict = (
        content_year is not None
        and filename_year is not None
        and content_year != filename_year
    )

    is_temporary = (
        "gecici vergi" in normalized_content or "gecici vergi" in normalized_filename
    )
    is_corporate = "kurumlar vergisi" in normalized_content
    is_mizan = "mizan" in normalized_content or "mizan" in normalized_filename
    is_annual_like = is_mizan or document_type_hint in ANNUAL_LIKE_DOCUMENT_TYPES
    quarter_source = content_year_quarter or filename_year_quarter

    period_type: PeriodType | None = None
    period_number: int | None = None
    confidence = 0.0

    if is_temporary:
        period_type = PeriodType.TEMPORARY_TAX
        if quarter_source:
            period_number = quarter_source[1]
            confidence = 0.90
        else:
            confidence = 0.65
            add_warning(
                warnings,
                code="PERIOD_NUMBER_NOT_FOUND",
                message=(
                    "Geçici vergi dönemi tespit edildi ancak dönem "
                    "numarası (çeyrek) bulunamadı."
                ),
            )
    elif is_corporate:
        period_type = PeriodType.YEAR_END
        period_number = 4
        confidence = 0.90
    elif is_annual_like:
        if quarter_source:
            period_type = PeriodType.TEMPORARY_TAX
            period_number = quarter_source[1]
            confidence = 0.85
        else:
            period_type = PeriodType.YEAR_END
            period_number = 4
            confidence = 0.60
            add_warning(
                warnings,
                code="PERIOD_TYPE_INFERRED",
                message=(
                    "Dönem tipi belgeden kesin olarak belirlenemedi; "
                    "varsayılan olarak yıl sonu (year_end) kabul edildi."
                ),
            )

    if year is None:
        confidence = 0.0
        add_warning(
            warnings,
            code="YEAR_NOT_FOUND",
            message="Belgeden veya dosya adından bir yıl tespit edilemedi.",
        )

    if conflict:
        add_warning(
            warnings,
            code="YEAR_CONFLICT",
            message=(
                f"Dosya adından tespit edilen yıl ({filename_year}) ile "
                f"belge içeriğinden tespit edilen yıl ({content_year}) "
                "çelişiyor."
            ),
            filename_year=filename_year,
            content_year=content_year,
        )
        confidence = min(confidence, CONFLICT_CONFIDENCE_CAP)

    if year is not None and year_source is not None:
        evidence["year"] = {"value": year, "source": year_source}
    if period_type is not None:
        evidence["period_type"] = {
            "value": period_type.value,
            "source": content_source_label if content_text else "filename",
        }
    if period_number is not None:
        evidence["period_number"] = {
            "value": period_number,
            "source": content_source_label if quarter_source == content_year_quarter else "filename",
        }

    return PeriodGuess(
        year=year,
        period_type=period_type,
        period_number=period_number,
        confidence=confidence,
        evidence=evidence,
        warnings=warnings,
    )
