"""
Firma unvanı ve VKN tespiti. Öncelik sırası: belge içeriği > dosya
metadata > dosya adı. VKN ASLA dosya adından türetilmez -- örnek dosya
adlarının hiçbirinde zaten VKN geçmiyor, ve bu genel olarak güvenilmez
bir kaynaktır.

confidence_score'un item-level bileşenlerinden biri (company identity)
BİLEREK öncelikle VKN'ye dayanır: sistemdeki gerçek Company kaydı
tax_number ile eşleştirilir (bkz. Milestone 2 / Adım 1), unvan yalnızca
destekleyici bir sinyaldir.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.classification.evidence import add_warning, new_warnings
from app.classification.vkn import find_candidate_vkns, is_valid_vkn


LABELED_VKN_PATTERN = re.compile(r"vergi kimlik no[:\s]*([0-9]{10})", re.IGNORECASE)
LABELED_COMPANY_PATTERN = re.compile(r"unvan[:\s]*([^\n]{3,120})", re.IGNORECASE)
COMPANY_SUFFIX_PATTERN = re.compile(
    r"[^\n]{0,80}\b(anonim sirketi|a\.s\.|limited sirketi|ltd\. sti\.|ltd sti|kollektif sirketi)\b",
    re.IGNORECASE,
)

# VKN'nin bulunduğu ama etiketsiz veya checksum'dan geçmediği durumlarda
# NULL'A DÜŞÜRÜLMEZ -- yalnızca confidence düşer, warning eklenir.
LABELED_VALID_CONFIDENCE = 0.95
LABELED_INVALID_CHECKSUM_CONFIDENCE = 0.60
UNLABELED_VALID_CONFIDENCE = 0.70
UNLABELED_UNVALIDATED_CONFIDENCE = 0.40

LABELED_COMPANY_CONFIDENCE = 0.90
SUFFIX_ONLY_COMPANY_CONFIDENCE = 0.75
NAME_ONLY_PENALTY = 0.80  # tax_number bulunamadığında unvan güvenine uygulanan çarpan


@dataclass
class CompanyIdentityGuess:
    company_name: str | None
    tax_number: str | None
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _find_vkn(text: str) -> tuple[str | None, float, str | None, list[dict[str, Any]]]:
    warnings = new_warnings()
    labeled_match = LABELED_VKN_PATTERN.search(text)

    if labeled_match:
        candidate = labeled_match.group(1)
        if is_valid_vkn(candidate):
            return candidate, LABELED_VALID_CONFIDENCE, labeled_match.group(0), warnings

        add_warning(
            warnings,
            code="VKN_CHECKSUM_FAILED",
            message=(
                "Tespit edilen VKN checksum doğrulamasından geçmedi; "
                "hatalı OCR/format olabilir. Değer yine de raporlanıyor."
            ),
            value=candidate,
        )
        return candidate, LABELED_INVALID_CHECKSUM_CONFIDENCE, labeled_match.group(0), warnings

    candidates = find_candidate_vkns(text)
    for candidate in candidates:
        if is_valid_vkn(candidate):
            return candidate, UNLABELED_VALID_CONFIDENCE, candidate, warnings

    if candidates:
        add_warning(
            warnings,
            code="VKN_UNLABELED_CANDIDATE",
            message=(
                "Belgede 10 haneli bir sayı bulundu ancak açık bir "
                "'Vergi Kimlik No' etiketi yok ve checksum doğrulanamadı."
            ),
            value=candidates[0],
        )
        return candidates[0], UNLABELED_UNVALIDATED_CONFIDENCE, candidates[0], warnings

    return None, 0.0, None, warnings


def _find_company_name(text: str) -> tuple[str | None, float, str | None]:
    labeled_match = LABELED_COMPANY_PATTERN.search(text)
    if labeled_match:
        return labeled_match.group(1).strip(), LABELED_COMPANY_CONFIDENCE, labeled_match.group(0)

    suffix_match = COMPANY_SUFFIX_PATTERN.search(text)
    if suffix_match:
        return (
            suffix_match.group(0).strip(),
            SUFFIX_ONLY_COMPANY_CONFIDENCE,
            suffix_match.group(0).strip(),
        )

    return None, 0.0, None


def resolve_company_identity(
    *,
    filename: str,
    content_text: str | None = None,
    content_source_label: str = "pdf_text",
    metadata_text: str | None = None,
) -> CompanyIdentityGuess:
    evidence: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []

    tax_number: str | None = None
    tax_confidence = 0.0
    tax_source = content_source_label
    company_name: str | None = None
    company_confidence = 0.0
    company_source = content_source_label

    # 1) Belge içeriği (en yüksek öncelik)
    if content_text:
        tax_number, tax_confidence, tax_snippet, tax_warnings = _find_vkn(content_text)
        warnings.extend(tax_warnings)
        if tax_number:
            evidence["tax_number"] = {
                "value": tax_number,
                "source": content_source_label,
                **({"evidence": tax_snippet} if tax_snippet else {}),
            }

        company_name, company_confidence, company_snippet = _find_company_name(content_text)
        if company_name:
            evidence["company_name"] = {
                "value": company_name,
                "source": content_source_label,
                **({"evidence": company_snippet} if company_snippet else {}),
            }

    # 2) Dosya metadata (yalnızca içerikte bulunamadıysa denenir)
    if metadata_text:
        if not tax_number:
            tax_number, tax_confidence, tax_snippet, tax_warnings = _find_vkn(metadata_text)
            tax_source = "file_metadata"
            warnings.extend(tax_warnings)
            if tax_number:
                evidence["tax_number"] = {
                    "value": tax_number,
                    "source": "file_metadata",
                    **({"evidence": tax_snippet} if tax_snippet else {}),
                }

        if not company_name:
            company_name, company_confidence, company_snippet = _find_company_name(metadata_text)
            company_source = "file_metadata"
            if company_name:
                evidence["company_name"] = {
                    "value": company_name,
                    "source": "file_metadata",
                    **({"evidence": company_snippet} if company_snippet else {}),
                }

    # 3) Dosya adı -- YALNIZCA unvan için son çare; VKN dosya adından
    # ASLA türetilmez.
    if not company_name:
        # Bilinçli olarak boş bırakıldı: bu milestone'daki örnek dosya
        # adlarının hiçbirinde firma unvanı geçmiyor. İleride
        # "ACME_AS_2024_Mizan.xlsx" gibi bir desen için genişletilebilir.
        pass

    if tax_number:
        overall_confidence = tax_confidence
        if not company_name:
            add_warning(
                warnings,
                code="COMPANY_NAME_NOT_FOUND",
                message="VKN bulundu ancak firma unvanı tespit edilemedi.",
            )
    elif company_name:
        overall_confidence = round(company_confidence * NAME_ONLY_PENALTY, 2)
        add_warning(
            warnings,
            code="TAX_NUMBER_NOT_FOUND",
            message=(
                "Firma unvanı bulundu ancak VKN tespit edilemedi; yalnızca "
                "unvanla eşleştirme daha az güvenilirdir."
            ),
        )
    else:
        overall_confidence = 0.0
        add_warning(
            warnings,
            code="COMPANY_IDENTITY_NOT_FOUND",
            message="Ne VKN ne de firma unvanı tespit edilebildi.",
        )

    return CompanyIdentityGuess(
        company_name=company_name,
        tax_number=tax_number,
        confidence=overall_confidence,
        evidence=evidence,
        warnings=warnings,
    )
