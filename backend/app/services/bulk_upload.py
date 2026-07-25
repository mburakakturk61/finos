"""
Çoklu dosya toplu yükleme + otomatik sınıflandırma orkestrasyonu (Milestone 2
/ Adım 3). Bu katman bir ONAY/KALICILAŞTIRMA adımı DEĞİLDİR -- yalnızca bir
"sınıflandırma önizlemesi / taslak" (classification preview / staging)
üretir. Hiçbir fiziksel dosya içeriği saklanmaz; yalnızca metadata
(ad, mime, boyut, checksum) ve app.classification.orchestrator.classify_file
çıktısı (tahmin edilen tür/firma/dönem + kanıt + uyarılar) kalıcı hale gelir.

Aşamalı (iki transaction'lı) akış, Milestone 2 / Adım 2'deki
app.services.trial_balance_upload ile aynı felsefeyi izler:
  1) BulkUploadBatch PROCESSING durumunda oluşturulup commit edilir --
     sınıflandırma döngüsü hiç başlamadan ÖNCE audit kaydı kalıcı olur.
  2) Her dosya (transaction dışında, saf/deterministik hesaplama) tek tek
     sınıflandırılır. Tek bir dosyanın PDF/Excel ayrıştırma hatası ASLA
     tüm batch'i düşürmez -- o dosya yalnızca UNRECOGNIZED + sanitize
     edilmiş bir uyarıyla işaretlenir (bkz. _build_item).
  3) Sonuç sayaçlarıyla (classified/unclassified/duplicate) birlikte
     ikinci bir transaction ile COMPLETED durumuna güncellenip commit
     edilir. Döngü sırasında beklenmeyen (dosya içeriğiyle ilgisiz,
     ör. DB bağlantı hatası) bir sistem hatası olursa batch FAILED'e
     çekilir ve BulkUploadSystemError fırlatılır (router -> 500).

Duplicate tespiti (bkz. _determine_classification_status) üç ayrı
kaynağı öncelik sırasıyla kontrol eder:
  a) Aynı istek/batch içinde checksum çakışması -- KESİN duplicate.
  b) Mevcut (onaylanmış) FinancialDocument tablosunda checksum eşleşmesi
     -- firma+dönem YÜKSEK güvenle (>=0.90) tespit edildiyse KESİN
     duplicate, aksi halde possible_duplicate.
  c) Önceki bir COMPLETED batch'teki BulkUploadItem'da checksum
     eşleşmesi -- (b) ile aynı güven kuralı uygulanır. PROCESSING veya
     FAILED durumundaki batch'lerin item'ları KASITLI OLARAK asla bir
     duplicate kaynağı olarak kullanılmaz (o batch'in sonucu henüz
     kesinleşmemiş/başarısız olmuş olabilir).
Hiçbir kaynakta eşleşme yoksa: document_type UNKNOWN ise UNRECOGNIZED,
overall confidence >= 0.90 ise AUTO_MATCHED, aksi halde NEEDS_REVIEW.
Bu beş değer birbirini dışlar; ek nüans yalnızca warnings_json'dadır.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.evidence import add_warning, new_warnings
from app.classification.orchestrator import classify_file
from app.core.config import get_settings
from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.bulk_upload_item import BulkUploadItem
from app.models.enums import BatchStatus, ClassificationStatus, DetectedDocumentType
from app.models.financial_document import FinancialDocument


logger = logging.getLogger(__name__)


# document_classifier/company_identity_resolver/period_detector'daki
# >=0.90 "auto_matched" bandıyla BİLEREK aynı eşik -- duplicate
# kesinliği de aynı "yüksek güven" tanımını kullanır.
HIGH_CONFIDENCE_THRESHOLD = Decimal("0.90")


@dataclass
class UploadedFileInput:
    """Router'dan servise geçirilen, henüz DB'ye yazılmamış tek bir dosya."""

    filename: str | None
    content: bytes
    mime_type: str | None


class BulkUploadValidationError(Exception):
    """İstek, hiçbir dosya sınıflandırılmadan ÖNCE reddedildi (router -> 400)."""


class BulkUploadSystemError(Exception):
    """
    Sınıflandırma döngüsü sırasında dosya içeriğiyle İLGİSİZ, beklenmeyen bir
    sistem hatası (router -> 500). Tek bir dosyanın ayrıştırma hatası bu
    değildir -- o durum sessizce UNRECOGNIZED + uyarı olarak ele alınır.
    """


def _validate_batch(files: list[UploadedFileInput]) -> None:
    if not files:
        raise BulkUploadValidationError("En az bir dosya yüklenmelidir.")

    settings = get_settings()
    if len(files) > settings.bulk_upload_max_files:
        raise BulkUploadValidationError(
            f"Bir istekte en fazla {settings.bulk_upload_max_files} dosya "
            "yüklenebilir."
        )


def _find_document_checksum_match(db: Session, checksum: str) -> uuid.UUID | None:
    return db.scalars(
        select(FinancialDocument.id)
        .where(FinancialDocument.checksum == checksum)
        .limit(1)
    ).first()


def _find_completed_batch_item_checksum_match(
    db: Session,
    checksum: str,
    exclude_batch_id: uuid.UUID,
) -> uuid.UUID | None:
    return db.scalars(
        select(BulkUploadItem.id)
        .join(BulkUploadBatch, BulkUploadItem.batch_id == BulkUploadBatch.id)
        .where(
            BulkUploadItem.checksum == checksum,
            BulkUploadBatch.status == BatchStatus.COMPLETED,
            BulkUploadItem.batch_id != exclude_batch_id,
        )
        .limit(1)
    ).first()


def _determine_classification_status(
    *,
    db: Session,
    batch_id: uuid.UUID,
    checksum: str,
    first_occurrence_id: uuid.UUID | None,
    document_type: DetectedDocumentType,
    identity_confidence: Decimal,
    period_confidence: Decimal,
    confidence_score: Decimal,
    warnings: list[dict[str, Any]],
) -> ClassificationStatus:
    if first_occurrence_id is not None:
        add_warning(
            warnings,
            code="DUPLICATE_WITHIN_BATCH",
            message=(
                "Bu dosya, aynı yükleme isteğindeki başka bir dosyayla "
                "aynı içeriğe (checksum) sahip."
            ),
            duplicate_of_item_id=str(first_occurrence_id),
        )
        return ClassificationStatus.DUPLICATE

    source_label: str | None = None
    source_id: uuid.UUID | None = None

    document_match_id = _find_document_checksum_match(db, checksum)
    if document_match_id is not None:
        source_label, source_id = "financial_document", document_match_id
    else:
        item_match_id = _find_completed_batch_item_checksum_match(
            db, checksum, batch_id
        )
        if item_match_id is not None:
            source_label, source_id = "bulk_upload_item", item_match_id

    if source_label is not None:
        is_certain = (
            identity_confidence >= HIGH_CONFIDENCE_THRESHOLD
            and period_confidence >= HIGH_CONFIDENCE_THRESHOLD
        )
        if is_certain:
            add_warning(
                warnings,
                code="DUPLICATE_CHECKSUM_MATCH",
                message=(
                    "Bu dosyanın içeriği (checksum), firma ve dönem yüksek "
                    "güvenle tespit edilmiş mevcut bir kayıtla eşleşiyor."
                ),
                source=source_label,
                source_id=str(source_id),
            )
            return ClassificationStatus.DUPLICATE

        add_warning(
            warnings,
            code="POSSIBLE_DUPLICATE_CHECKSUM_MATCH",
            message=(
                "Bu dosyanın içeriği (checksum) sistemde mevcut bir kayıtla "
                "eşleşiyor ancak firma/dönem kesin olarak doğrulanamadı."
            ),
            source=source_label,
            source_id=str(source_id),
        )
        return ClassificationStatus.POSSIBLE_DUPLICATE

    if document_type == DetectedDocumentType.UNKNOWN:
        return ClassificationStatus.UNRECOGNIZED

    if confidence_score >= HIGH_CONFIDENCE_THRESHOLD:
        return ClassificationStatus.AUTO_MATCHED

    return ClassificationStatus.NEEDS_REVIEW


def _build_item(
    db: Session,
    batch_id: uuid.UUID,
    file_input: UploadedFileInput,
    seen_checksums: dict[str, uuid.UUID],
) -> BulkUploadItem:
    item_id = uuid.uuid4()
    filename = file_input.filename or ""
    mime_type = file_input.mime_type or "application/octet-stream"
    content = file_input.content
    checksum = hashlib.sha256(content).hexdigest()

    warnings = new_warnings()
    if not file_input.filename:
        add_warning(
            warnings,
            code="FILENAME_MISSING",
            message=(
                "Dosya adı bulunamadı; sınıflandırma yalnızca içeriğe "
                "dayanıyor."
            ),
        )

    document_type = DetectedDocumentType.UNKNOWN
    company_name: str | None = None
    tax_number: str | None = None
    year: int | None = None
    period_type = None
    period_number: int | None = None
    confidence_score = Decimal("0.00")
    identity_confidence = Decimal("0.00")
    period_confidence = Decimal("0.00")
    evidence: dict[str, Any] = {}

    settings = get_settings()

    if not content:
        add_warning(
            warnings,
            code="EMPTY_FILE",
            message="Yüklenen dosya boş; sınıflandırma yapılamadı.",
        )
    elif len(content) > settings.bulk_upload_max_file_bytes:
        add_warning(
            warnings,
            code="FILE_TOO_LARGE",
            message=(
                f"Dosya boyutu {settings.bulk_upload_max_file_bytes} bayt "
                "sınırını aşıyor; sınıflandırma yapılamadı."
            ),
        )
    else:
        try:
            result = classify_file(filename, content)
            document_type = result.document_type
            company_name = result.company_name
            tax_number = result.tax_number
            year = result.year
            period_type = result.period_type
            period_number = result.period_number
            confidence_score = result.confidence_score
            identity_confidence = result.company_identity_confidence
            period_confidence = result.period_confidence
            evidence = result.evidence
            warnings.extend(result.warnings)
        except Exception:
            # Sanitize edilmiş, sabit bir uyarı -- ham exception/traceback
            # hiçbir zaman DB'ye veya HTTP yanıtına yazılmaz, yalnızca
            # uygulama loguna (bkz. Milestone 2 / Adım 2'deki aynı kural).
            logger.exception(
                "Dosya sınıflandırılırken beklenmeyen hata (filename=%s)",
                filename,
            )
            add_warning(
                warnings,
                code="CLASSIFICATION_FAILED",
                message=(
                    "Dosya sınıflandırılırken beklenmeyen bir hata oluştu."
                ),
            )

    first_occurrence_id = seen_checksums.get(checksum)
    if first_occurrence_id is None:
        seen_checksums[checksum] = item_id

    classification_status = _determine_classification_status(
        db=db,
        batch_id=batch_id,
        checksum=checksum,
        first_occurrence_id=first_occurrence_id,
        document_type=document_type,
        identity_confidence=identity_confidence,
        period_confidence=period_confidence,
        confidence_score=confidence_score,
        warnings=warnings,
    )

    return BulkUploadItem(
        id=item_id,
        batch_id=batch_id,
        original_filename=filename,
        mime_type=mime_type,
        file_size=len(content),
        checksum=checksum,
        detected_document_type=document_type,
        detected_company_name=company_name,
        detected_tax_number=tax_number,
        detected_year=year,
        detected_period_type=period_type,
        detected_period_number=period_number,
        confidence_score=confidence_score,
        classification_status=classification_status,
        warnings_json=warnings,
        detection_evidence_json=evidence,
    )


def _mark_batch_failed(db: Session, batch_id: uuid.UUID) -> None:
    """
    Sınıflandırma döngüsü sırasında dosya içeriğiyle ilgisiz bir sistem
    hatası oluştuğunda çağrılır. Nesneyi YENİDEN sorgulayarak, ayrı ve
    korumalı bir denemeyle FAILED işaretler. Bu da başarısız olursa
    yalnızca loglar -- çağıran zaten BulkUploadSystemError fırlatıp
    router'ın 500 dönmesini sağlayacaktır.
    """

    try:
        batch = db.get(BulkUploadBatch, batch_id)
        if batch is not None:
            batch.status = BatchStatus.FAILED
            batch.completed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Batch failed durumuna güncelleme de başarısız oldu "
            "(batch_id=%s)",
            batch_id,
        )


def handle_bulk_upload(
    db: Session,
    files: list[UploadedFileInput],
) -> BulkUploadBatch:
    _validate_batch(files)

    batch_id = uuid.uuid4()
    batch = BulkUploadBatch(
        id=batch_id,
        status=BatchStatus.PROCESSING,
        total_file_count=len(files),
        classified_file_count=0,
        unclassified_file_count=0,
        duplicate_file_count=0,
    )
    db.add(batch)

    # --- TRANSACTION 1: audit kaydı sınıflandırma başlamadan ÖNCE kalıcı olur ---
    db.commit()
    db.refresh(batch)

    items: list[BulkUploadItem] = []
    seen_checksums: dict[str, uuid.UUID] = {}

    try:
        for file_input in files:
            item = _build_item(db, batch_id, file_input, seen_checksums)
            db.add(item)
            items.append(item)
    except Exception as error:
        logger.exception(
            "Toplu yükleme sınıflandırma döngüsünde beklenmeyen sistem "
            "hatası (batch_id=%s)",
            batch_id,
        )
        db.rollback()
        _mark_batch_failed(db, batch_id)
        raise BulkUploadSystemError(
            "Toplu yükleme işlenirken beklenmeyen bir hata oluştu."
        ) from error

    classified_count = sum(
        1 for item in items
        if item.classification_status != ClassificationStatus.UNRECOGNIZED
    )
    unclassified_count = len(items) - classified_count
    duplicate_count = sum(
        1 for item in items
        if item.classification_status in (
            ClassificationStatus.DUPLICATE,
            ClassificationStatus.POSSIBLE_DUPLICATE,
        )
    )

    batch.classified_file_count = classified_count
    batch.unclassified_file_count = unclassified_count
    batch.duplicate_file_count = duplicate_count
    batch.status = BatchStatus.COMPLETED
    batch.completed_at = datetime.now(timezone.utc)

    # --- TRANSACTION 2: sonuç durumunu kalıcı hale getir ---
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception(
            "Batch sonucu kaydedilirken beklenmeyen hata (batch_id=%s)",
            batch_id,
        )
        _mark_batch_failed(db, batch_id)
        raise BulkUploadSystemError(
            "Toplu yükleme sonucu kaydedilirken beklenmeyen bir hata "
            "oluştu."
        ) from error

    db.refresh(batch)
    for item in items:
        db.refresh(item)

    return batch
