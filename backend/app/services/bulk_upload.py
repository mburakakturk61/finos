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

Milestone 3 / Adım 1 (confirm_bulk_upload -- dosyanın alt kısmı): staging'i
kullanıcı onayıyla production kayıtlarına (Company/FinancialPeriod/
FinancialDocument/FinancialAnalysisResult) dönüştürür. ÜÇ AYRI FAZ:
  FAZ 1 (_run_confirm_preflight): yalnızca DB OKUMA. Her accepted item
    için firma/dönem çözümü, gerekiyorsa yeniden gönderilen dosyanın
    checksum'ı, duplicate document kontrolü -- İLK HATADA DURMAZ, tüm
    accepted item'lardaki tüm hataları toplar. Herhangi bir hata varsa
    HİÇBİR ŞEY yazılmadan ConfirmPreflightError fırlatılır (router -> 422).
  FAZ 2 (_run_confirm_analyses): yalnızca BELLEKTE. trial_balance türündeki
    item'lar için mevcut analyze_trial_balance motoru (değiştirilmeden)
    çağrılır -- bu fonksiyon `db` parametresi bile ALMAZ, hiçbir DB
    transaction'ı açık değilken çalışır (uzun sürebilecek analiz DB
    kilidi tutmaz). Herhangi bir analiz başarısız olursa yine HİÇBİR ŞEY
    yazılmadan aynı ConfirmPreflightError ile reddedilir.
  FAZ 3 (_write_confirmed_records): TEK transaction. Yalnızca FAZ 1 ve
    FAZ 2 TAMAMEN başarılıysa açılır -- Company/FinancialPeriod find-or-
    create, FinancialDocument + (varsa) FinancialAnalysisResult oluşturma,
    BulkUploadItem.resulting_*_id'lerin set edilmesi, batch=CONFIRMED,
    hepsi TEK commit. Herhangi bir adımda hata olursa TAM rollback --
    yarım Company/Period/Document kaydı asla kalmaz.
Confirmed bir batch immutable'dır (BatchImmutableError -> 409, tekrar
confirm edilemez, item'larına PATCH uygulanamaz). Accepted OLMAYAN
(ignored veya hâlâ pending) hiçbir item production tablolarına yazılmaz;
resulting_*_id'leri her zaman NULL kalır.
"""

import calendar
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.classification.evidence import add_warning, new_warnings
from app.classification.orchestrator import classify_file
from app.core.config import get_settings
from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.bulk_upload_item import BulkUploadItem
from app.models.company import Company
from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    BatchStatus,
    ClassificationStatus,
    DetectedDocumentType,
    DocumentType,
    ItemReviewDecision,
    PeriodType,
    ProcessingStatus,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod
from app.trial_balance.service import analyze_trial_balance


logger = logging.getLogger(__name__)


# document_classifier/company_identity_resolver/period_detector'daki
# >=0.90 "auto_matched" bandıyla BİLEREK aynı eşik -- duplicate
# kesinliği de aynı "yüksek güven" tanımını kullanır.
HIGH_CONFIDENCE_THRESHOLD = Decimal("0.90")

# DetectedDocumentType (tahmin, 5 tür + unknown) -> DocumentType (gerçek
# FinancialDocument türü, 4 kaba kategori). UNKNOWN BİLEREK burada yok --
# confirm edilecek bir item asla UNKNOWN olamaz (bkz. ItemResolution
# şemasındaki validator). Milestone 3 / Adım 1 kararı: DocumentType'ın
# kendisi genişletilmedi (mevcut Adım 1 modeline dokunulmuyor); bu eşleme
# yalnızca burada, uygulama katmanında yaşıyor.
DETECTED_TO_DOCUMENT_TYPE: dict[DetectedDocumentType, DocumentType] = {
    DetectedDocumentType.TRIAL_BALANCE: DocumentType.TRIAL_BALANCE,
    DetectedDocumentType.CORPORATE_TAX_RETURN: DocumentType.TAX_DECLARATION,
    DetectedDocumentType.TEMPORARY_TAX_RETURN: DocumentType.TAX_DECLARATION,
    DetectedDocumentType.BALANCE_SHEET: DocumentType.FINANCIAL_STATEMENT,
    DetectedDocumentType.INCOME_STATEMENT: DocumentType.FINANCIAL_STATEMENT,
}

# Yalnızca bu türler için gerçek bir analiz motoru var (şu an yalnızca
# trial_balance). Confirm sırasında YALNIZCA bu türdeki accepted item'lar
# için dosya baytının yeniden gönderilmesi ZORUNLUDUR. Diğer türler (ör.
# corporate_tax_return, balance_sheet) için FinancialDocument yine de
# oluşturulur -- ancak STAGING metadata'sından (ilk POST /bulk-uploads
# sırasında gerçek bayt görülerek hesaplanmış checksum/file_size dahil),
# baytın yeniden istenmesine gerek DUYULMADAN -- çünkü henüz çalıştırılacak
# bir motor yok (bkz. "gerekiyorsa FinancialAnalysisResult" kararı).
CONTENT_REQUIRED_DETECTED_TYPES = frozenset({DetectedDocumentType.TRIAL_BALANCE})

PARSER_NAME = "generic"
PARSER_VERSION = "1.0.0"
ENGINE_VERSION = "1.0.0"


@dataclass
class UploadedFileInput:
    """Router'dan servise geçirilen, henüz DB'ye yazılmamış tek bir dosya."""

    filename: str | None
    content: bytes
    mime_type: str | None


class BulkUploadValidationError(Exception):
    """İstek, hiçbir dosya sınıflandırılmadan ÖNCE reddedildi (router -> 400)."""


class BulkUploadNotFoundError(Exception):
    """Batch veya item bulunamadı (router -> 404)."""


class BatchImmutableError(Exception):
    """
    Batch zaten CONFIRMED -- item'larına PATCH uygulanamaz, batch tekrar
    confirm edilemez (router -> 409). Milestone 3 / Adım 1 immutability
    kararı.
    """


class ItemPatchValidationError(Exception):
    """PATCH payload'ı geçersiz (router -> 422, tek item için fail-fast)."""


class BatchNotReadyError(Exception):
    """
    Batch henüz sınıflandırma sürecini (COMPLETED) tamamlamamış --
    PROCESSING veya FAILED durumunda confirm edilemez (router -> 409).
    """


class ConfirmPreflightError(Exception):
    """
    Confirm ön-doğrulaması (veya analiz aşaması) başarısız -- HİÇBİR
    şey yazılmadı (router -> 422). `errors`, her biri
    {item_id, code, message} olan bir liste -- ilk hatada durmaz, TÜM
    accepted item'lardaki TÜM hataları toplar.
    """

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("confirm preflight validation failed")


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


def _derive_period_dates(
    year: int,
    period_type: PeriodType,
    period_number: int,
) -> tuple[date, date, int, bool]:
    """
    Yeni bir dönem TASLAĞI için başlangıç/bitiş tarihi üretir -- kullanıcı
    PATCH ile bunu her zaman değiştirebilir, bu yalnızca bir ön-doldurma
    sezgiselliğidir, resmi bir mali takvim motoru DEĞİLDİR.
    """

    if period_type == PeriodType.YEAR_END:
        return date(year, 1, 1), date(year, 12, 31), 12, True

    if period_type == PeriodType.TEMPORARY_TAX:
        # Basit takvim çeyreği sezgiselliği (1->Oca-Mar, 2->Nis-Haz, ...).
        # Türk vergi mevzuatındaki kümülatif geçici vergi dönemi tanımının
        # YERİNE GEÇMEZ -- yalnızca kullanıcının düzenleyebileceği bir
        # başlangıç taslağıdır.
        quarter = max(1, min(period_number, 4))
        start_month = 3 * (quarter - 1) + 1
        end_month = 3 * quarter
        start = date(year, start_month, 1)
        last_day = calendar.monthrange(year, end_month)[1]
        end = date(year, end_month, last_day)
        return start, end, 3, False

    # QUARTER/MONTHLY/CUSTOM: period_detector bunları şu an hiç üretmiyor --
    # savunmacı, güvenli bir fallback (tam yıl).
    return date(year, 1, 1), date(year, 12, 31), 12, False


def _auto_fill_resolution(
    db: Session,
    *,
    detected_document_type: DetectedDocumentType,
    detected_company_name: str | None,
    detected_tax_number: str | None,
    detected_year: int | None,
    detected_period_type: PeriodType | None,
    detected_period_number: int | None,
) -> dict[str, Any] | None:
    """
    Yalnızca classification_status=AUTO_MATCHED item'lar için çağrılır
    (bkz. _build_item) -- yüksek güvenle tespit edilmiş firma/dönem
    bilgisi, kullanıcının tek tek PATCH yapmasına gerek kalmadan toplu
    kabul edebilmesi için bir resolution_json TASLAĞI olarak önceden
    doldurulur. user_decision YİNE DE PENDING kalır ve hiçbir production
    tabloya bu aşamada yazılmaz -- kullanıcı hâlâ (toplu ya da tek tek)
    açıkça kabul etmelidir.
    """

    if (
        not detected_tax_number
        or detected_year is None
        or detected_period_type is None
        or detected_period_number is None
    ):
        # AUTO_MATCHED olabilmek için bunların hepsi zaten dolu olmalı
        # (confidence_score bileşenlerin min()'i) -- yine de savunmacı.
        return None

    existing_company = db.scalars(
        select(Company).where(Company.tax_number == detected_tax_number).limit(1)
    ).first()

    if existing_company is not None:
        company_resolution: dict[str, Any] = {
            "mode": "existing",
            "id": str(existing_company.id),
        }
        existing_period = db.scalars(
            select(FinancialPeriod).where(
                FinancialPeriod.company_id == existing_company.id,
                FinancialPeriod.year == detected_year,
                FinancialPeriod.period_type == detected_period_type,
                FinancialPeriod.period_number == detected_period_number,
            ).limit(1)
        ).first()
    else:
        company_resolution = {
            "mode": "new",
            "legal_name": detected_company_name or detected_tax_number,
            "tax_number": detected_tax_number,
            "currency": "TRY",
        }
        existing_period = None

    if existing_period is not None:
        period_resolution: dict[str, Any] = {
            "mode": "existing",
            "id": str(existing_period.id),
        }
    else:
        start_date, end_date, months_covered, is_year_end = _derive_period_dates(
            detected_year, detected_period_type, detected_period_number
        )
        period_resolution = {
            "mode": "new",
            "year": detected_year,
            "period_type": detected_period_type.value,
            "period_number": detected_period_number,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "months_covered": months_covered,
            "is_year_end": is_year_end,
        }

    return {
        "company": company_resolution,
        "period": period_resolution,
        "document_type": detected_document_type.value,
    }


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

    resolution_json: dict[str, Any] | None = None
    if classification_status == ClassificationStatus.AUTO_MATCHED:
        resolution_json = _auto_fill_resolution(
            db,
            detected_document_type=document_type,
            detected_company_name=company_name,
            detected_tax_number=tax_number,
            detected_year=year,
            detected_period_type=period_type,
            detected_period_number=period_number,
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
        user_decision=ItemReviewDecision.PENDING,
        resolution_json=resolution_json,
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


# --- PATCH (tek item ve toplu karar) -- Milestone 3 / Adım 1 -----------
#
# Bu fonksiyonlar BİLEREK Pydantic şemalarını (app.schemas.bulk_upload)
# İÇE AKTARMAZ -- servis katmanı mevcut app/services/trial_balance_upload.py
# ile aynı konvansiyonu izler (yalnızca primitive/dict/dataclass), API
# sözleşmesi validasyonu router'da (FastAPI + Pydantic) yapılır. Buradaki
# `_validate_*` fonksiyonları yalnızca DB'ye bakmayı gerektiren iş
# kurallarını (ör. "id gerçekten var mı") kontrol eder; alan/tip
# doğrulaması zaten router seviyesinde Pydantic tarafından yapılmıştır.


def _get_batch_or_404(db: Session, batch_id: uuid.UUID) -> BulkUploadBatch:
    batch = db.get(BulkUploadBatch, batch_id)
    if batch is None:
        raise BulkUploadNotFoundError("Batch bulunamadı.")
    return batch


def _require_batch_not_confirmed(batch: BulkUploadBatch) -> None:
    if batch.status == BatchStatus.CONFIRMED:
        raise BatchImmutableError(
            "Onaylanmış (confirmed) bir batch'in item'ları değiştirilemez."
        )


def _get_item_or_404(
    db: Session,
    batch_id: uuid.UUID,
    item_id: uuid.UUID,
) -> BulkUploadItem:
    item = db.get(BulkUploadItem, item_id)
    if item is None or item.batch_id != batch_id:
        raise BulkUploadNotFoundError("Item bulunamadı.")
    return item


def _validate_company_resolution(db: Session, company: dict[str, Any]) -> None:
    mode = company.get("mode")
    if mode == "existing":
        raw_id = company.get("id")
        try:
            company_id = uuid.UUID(str(raw_id))
        except (TypeError, ValueError) as error:
            raise ItemPatchValidationError(
                "company.id geçerli bir UUID olmalıdır."
            ) from error
        if db.get(Company, company_id) is None:
            raise ItemPatchValidationError(
                f"company_id bulunamadı: {company_id}"
            )
    elif mode == "new":
        if not company.get("legal_name") or not company.get("tax_number"):
            raise ItemPatchValidationError(
                "Yeni firma için legal_name ve tax_number zorunludur."
            )
    else:
        raise ItemPatchValidationError(
            "company.mode 'existing' veya 'new' olmalıdır."
        )


def _validate_period_resolution(db: Session, period: dict[str, Any]) -> None:
    mode = period.get("mode")
    if mode == "existing":
        raw_id = period.get("id")
        try:
            period_id = uuid.UUID(str(raw_id))
        except (TypeError, ValueError) as error:
            raise ItemPatchValidationError(
                "period.id geçerli bir UUID olmalıdır."
            ) from error
        if db.get(FinancialPeriod, period_id) is None:
            raise ItemPatchValidationError(f"period_id bulunamadı: {period_id}")
    elif mode == "new":
        required_fields = (
            "year",
            "period_type",
            "period_number",
            "start_date",
            "end_date",
            "months_covered",
        )
        missing = [field for field in required_fields if period.get(field) is None]
        if missing:
            raise ItemPatchValidationError(
                f"Yeni dönem için eksik alanlar: {', '.join(missing)}"
            )
        if str(period["end_date"]) < str(period["start_date"]):
            raise ItemPatchValidationError("end_date, start_date'ten önce olamaz.")
    else:
        raise ItemPatchValidationError(
            "period.mode 'existing' veya 'new' olmalıdır."
        )


def _require_full_resolution(resolution: dict[str, Any]) -> None:
    if not resolution.get("company"):
        raise ItemPatchValidationError(
            "'accepted' kararı için önce firma çözümü gereklidir."
        )
    if not resolution.get("period"):
        raise ItemPatchValidationError(
            "'accepted' kararı için önce dönem çözümü gereklidir."
        )
    if not resolution.get("document_type"):
        raise ItemPatchValidationError(
            "'accepted' kararı için önce belge türü gereklidir."
        )
    if resolution["document_type"] == DetectedDocumentType.UNKNOWN.value:
        raise ItemPatchValidationError("Belge türü 'unknown' olamaz.")


def patch_bulk_upload_item(
    db: Session,
    batch_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    company: dict[str, Any] | None,
    period: dict[str, Any] | None,
    document_type: str | None,
    decision: str | None,
) -> BulkUploadItem:
    """
    Tek bir item için kısmi güncelleme. Yalnızca gönderilen alanlar
    değişir. `decision="accepted"` için company/period/document_type'ın
    (bu istekte VEYA önceki bir PATCH'te / otomatik ön-doldurmada)
    zaten çözülmüş olması zorunludur.
    """

    batch = _get_batch_or_404(db, batch_id)
    _require_batch_not_confirmed(batch)
    item = _get_item_or_404(db, batch_id, item_id)

    resolution: dict[str, Any] = dict(item.resolution_json or {})

    if company is not None:
        _validate_company_resolution(db, company)
        resolution["company"] = company
    if period is not None:
        _validate_period_resolution(db, period)
        resolution["period"] = period
    if document_type is not None:
        if document_type == DetectedDocumentType.UNKNOWN.value:
            raise ItemPatchValidationError("Belge türü 'unknown' olamaz.")
        resolution["document_type"] = document_type

    item.resolution_json = resolution or None

    if decision is not None:
        new_decision = ItemReviewDecision(decision)
        if new_decision == ItemReviewDecision.ACCEPTED:
            _require_full_resolution(resolution)
        item.user_decision = new_decision

    db.commit()
    db.refresh(item)
    return item


def bulk_patch_item_decisions(
    db: Session,
    batch_id: uuid.UUID,
    decisions: list[tuple[uuid.UUID, str]],
) -> list[dict[str, Any]]:
    """
    Yalnızca KARAR toplu güncellemesi (firma/dönem/tür düzenlemesi yok --
    bunun için tek-item PATCH kullanılır). Kısmi başarı modeli: geçersiz
    bir item_id veya eksik resolution'lı bir 'accepted' isteği DİĞER
    item'ları etkilemez -- her item için ayrı sonuç/hata döner, geçerli
    olanlar commit edilir.
    """

    batch = _get_batch_or_404(db, batch_id)
    _require_batch_not_confirmed(batch)

    results: list[dict[str, Any]] = []

    for item_id, decision in decisions:
        item = db.get(BulkUploadItem, item_id)
        if item is None or item.batch_id != batch_id:
            results.append(
                {
                    "item_id": item_id,
                    "success": False,
                    "user_decision": None,
                    "error": "Item bulunamadı.",
                }
            )
            continue

        try:
            new_decision = ItemReviewDecision(decision)
            if new_decision == ItemReviewDecision.ACCEPTED:
                _require_full_resolution(item.resolution_json or {})
        except (ValueError, ItemPatchValidationError) as error:
            results.append(
                {
                    "item_id": item_id,
                    "success": False,
                    "user_decision": None,
                    "error": str(error),
                }
            )
            continue

        item.user_decision = new_decision
        results.append(
            {
                "item_id": item_id,
                "success": True,
                "user_decision": new_decision,
                "error": None,
            }
        )

    db.commit()
    return results


# --- Confirm (Milestone 3 / Adım 1) -------------------------------------


@dataclass
class AcceptedItemPlan:
    """FAZ 1'de üretilen, saf/plain bir çözüm planı -- ORM nesnesi DEĞİL.
    FAZ 2 ve FAZ 3, session rollback/expire davranışından etkilenmemek
    için ORM nesnelerine değil bu plan nesnelerine güvenir."""

    item_id: uuid.UUID
    checksum: str
    original_filename: str
    mime_type: str
    file_size: int
    company_resolution: dict[str, Any]
    period_resolution: dict[str, Any]
    detected_document_type: DetectedDocumentType


@dataclass
class ConfirmSummary:
    batch: BulkUploadBatch
    confirmed_at: datetime
    counts: dict[str, int]
    item_results: list[dict[str, Any]]


def _company_period_mismatch(
    db: Session,
    company_resolution: dict[str, Any],
    period_resolution: dict[str, Any],
) -> bool:
    """Var olan bir dönem, henüz var olmayan (mode=new) bir firmaya asla
    bağlanamaz; var olan bir dönem+firma çifti seçildiyse period.company_id
    gerçekten seçilen company ile eşleşmelidir."""

    if company_resolution.get("mode") == "new" and period_resolution.get("mode") == "existing":
        return True

    if company_resolution.get("mode") == "existing" and period_resolution.get("mode") == "existing":
        try:
            resolved_company_id = uuid.UUID(str(company_resolution["id"]))
            resolved_period = db.get(FinancialPeriod, uuid.UUID(str(period_resolution["id"])))
        except (TypeError, ValueError, KeyError):
            return False  # zaten ayrı validasyonlarda yakalanır
        if resolved_period is not None and resolved_period.company_id != resolved_company_id:
            return True

    return False


def _run_confirm_preflight(
    db: Session,
    batch: BulkUploadBatch,
    resubmitted_files: dict[uuid.UUID, "UploadedFileInput"],
) -> list[AcceptedItemPlan]:
    """
    FAZ 1 -- yalnızca DB OKUMA. İlk hatada durmaz: her accepted item
    bağımsız olarak kontrol edilir, TÜM hatalar tek bir listede toplanır.
    Herhangi bir hata varsa ConfirmPreflightError fırlatılır ve `plans`
    ASLA döndürülmez (hiçbir şey yazılmamış olur).
    """

    accepted_items = db.scalars(
        select(BulkUploadItem).where(
            BulkUploadItem.batch_id == batch.id,
            BulkUploadItem.user_decision == ItemReviewDecision.ACCEPTED,
        )
    ).all()

    errors: list[dict[str, Any]] = []
    plans: list[AcceptedItemPlan] = []

    for item in accepted_items:
        resolution = item.resolution_json or {}
        company_resolution = resolution.get("company")
        period_resolution = resolution.get("period")
        document_type_value = resolution.get("document_type")

        if not company_resolution:
            errors.append({
                "item_id": item.id, "code": "COMPANY_UNRESOLVED",
                "message": "Firma çözümü eksik.",
            })
        else:
            try:
                _validate_company_resolution(db, company_resolution)
            except ItemPatchValidationError as error:
                errors.append({
                    "item_id": item.id, "code": "COMPANY_UNRESOLVED",
                    "message": str(error),
                })

        if not period_resolution:
            errors.append({
                "item_id": item.id, "code": "PERIOD_UNRESOLVED",
                "message": "Dönem çözümü eksik.",
            })
        else:
            try:
                _validate_period_resolution(db, period_resolution)
            except ItemPatchValidationError as error:
                errors.append({
                    "item_id": item.id, "code": "PERIOD_UNRESOLVED",
                    "message": str(error),
                })

        if (
            company_resolution
            and period_resolution
            and _company_period_mismatch(db, company_resolution, period_resolution)
        ):
            errors.append({
                "item_id": item.id, "code": "COMPANY_PERIOD_MISMATCH",
                "message": "Seçilen dönem, seçilen/oluşturulacak firmaya ait değil.",
            })

        if not document_type_value or document_type_value == DetectedDocumentType.UNKNOWN.value:
            errors.append({
                "item_id": item.id, "code": "DOCUMENT_TYPE_UNRESOLVED",
                "message": "Belge türü eksik veya 'unknown'.",
            })
            continue

        detected_document_type = DetectedDocumentType(document_type_value)
        needs_content = detected_document_type in CONTENT_REQUIRED_DETECTED_TYPES

        file_input = resubmitted_files.get(item.id)
        if needs_content:
            if file_input is None:
                errors.append({
                    "item_id": item.id, "code": "MISSING_FILE",
                    "message": "Bu item için dosya yeniden gönderilmedi.",
                })
            else:
                actual_checksum = hashlib.sha256(file_input.content).hexdigest()
                if actual_checksum != item.checksum:
                    errors.append({
                        "item_id": item.id, "code": "CHECKSUM_MISMATCH",
                        "message": (
                            "Yeniden gönderilen dosyanın checksum'ı "
                            "staging kaydıyla uyuşmuyor."
                        ),
                    })

        if period_resolution and period_resolution.get("mode") == "existing":
            try:
                period_id = uuid.UUID(str(period_resolution["id"]))
            except (TypeError, ValueError):
                period_id = None
            if period_id is not None:
                existing_doc = db.scalars(
                    select(FinancialDocument.id).where(
                        FinancialDocument.period_id == period_id,
                        FinancialDocument.checksum == item.checksum,
                    ).limit(1)
                ).first()
                if existing_doc is not None:
                    errors.append({
                        "item_id": item.id, "code": "DUPLICATE_DOCUMENT",
                        "message": (
                            "Bu dönem için aynı içerikte bir belge zaten "
                            f"var (document_id={existing_doc})."
                        ),
                    })

        plans.append(AcceptedItemPlan(
            item_id=item.id,
            checksum=item.checksum,
            original_filename=item.original_filename,
            mime_type=item.mime_type,
            file_size=item.file_size,
            company_resolution=company_resolution,
            period_resolution=period_resolution,
            detected_document_type=detected_document_type,
        ))

    if errors:
        raise ConfirmPreflightError(errors)

    return plans


def _run_confirm_analyses(
    plans: list[AcceptedItemPlan],
    resubmitted_files: dict[uuid.UUID, "UploadedFileInput"],
) -> dict[uuid.UUID, dict[str, Any]]:
    """
    FAZ 2 -- yalnızca BELLEKTE çalışır. BİLEREK `db` parametresi ALMAZ --
    bu, hiçbir DB transaction'ının açık olmadığını KOD SEVİYESİNDE
    garanti eder (uzun sürebilecek analiz DB kilidi tutmaz). Yalnızca
    trial_balance türündeki item'lar için mevcut analyze_trial_balance
    motoru (değiştirilmeden) çağrılır. Herhangi bir analiz başarısız
    olursa TÜM confirm isteği aynı ConfirmPreflightError ile reddedilir
    -- henüz hiçbir transaction açılmadığı için ekstra rollback gerekmez.
    """

    results: dict[uuid.UUID, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []

    for plan in plans:
        if plan.detected_document_type != DetectedDocumentType.TRIAL_BALANCE:
            continue

        file_input = resubmitted_files[plan.item_id]  # FAZ 1 zaten garantiledi
        try:
            results[plan.item_id] = analyze_trial_balance(
                content=file_input.content,
                filename=plan.original_filename,
            )
        except Exception:
            logger.exception(
                "Confirm sırasında trial_balance motoru hata verdi "
                "(item_id=%s)",
                plan.item_id,
            )
            errors.append({
                "item_id": plan.item_id, "code": "ENGINE_FAILED",
                "message": (
                    "Dosya analiz edilemedi. Dosya bozuk ya da beklenen "
                    "mizan formatında olmayabilir."
                ),
            })

    if errors:
        raise ConfirmPreflightError(errors)

    return results


def _find_or_create_company(
    db: Session,
    resolution: dict[str, Any],
) -> tuple[Company, bool]:
    """Döner: (company, created). VKN eşleşen mevcut bir Company varsa
    HER ZAMAN o reuse edilir -- mode='new' olsa bile (FAZ 1 ile FAZ 3
    arasında başka bir istek aynı VKN'yi oluşturmuş olabilir; ayrıca
    Company.tax_number zaten DB'de unique, bu kontrol gereksiz bir
    IntegrityError'ı da önler)."""

    if resolution["mode"] == "existing":
        company = db.get(Company, uuid.UUID(str(resolution["id"])))
        return company, False

    existing = db.scalars(
        select(Company).where(Company.tax_number == resolution["tax_number"])
    ).first()
    if existing is not None:
        return existing, False

    company = Company(
        legal_name=resolution["legal_name"],
        trade_name=resolution.get("trade_name"),
        tax_number=resolution["tax_number"],
        tax_office=resolution.get("tax_office"),
        sector=resolution.get("sector"),
        nace_code=resolution.get("nace_code"),
        currency=resolution.get("currency") or "TRY",
    )
    db.add(company)
    db.flush()
    return company, True


def _find_or_create_period(
    db: Session,
    company_id: uuid.UUID,
    resolution: dict[str, Any],
) -> tuple[FinancialPeriod, bool]:
    """Döner: (period, created). Aynı (company, year, period_type,
    period_number) zaten varsa HER ZAMAN reuse edilir (bkz.
    _find_or_create_company'deki aynı gerekçe)."""

    if resolution["mode"] == "existing":
        period = db.get(FinancialPeriod, uuid.UUID(str(resolution["id"])))
        return period, False

    period_type = PeriodType(resolution["period_type"])
    existing = db.scalars(
        select(FinancialPeriod).where(
            FinancialPeriod.company_id == company_id,
            FinancialPeriod.year == resolution["year"],
            FinancialPeriod.period_type == period_type,
            FinancialPeriod.period_number == resolution["period_number"],
        )
    ).first()
    if existing is not None:
        return existing, False

    period = FinancialPeriod(
        company_id=company_id,
        year=resolution["year"],
        period_type=period_type,
        period_number=resolution["period_number"],
        start_date=date.fromisoformat(resolution["start_date"]),
        end_date=date.fromisoformat(resolution["end_date"]),
        months_covered=resolution["months_covered"],
        is_year_end=resolution.get("is_year_end", False),
    )
    db.add(period)
    db.flush()
    return period, True


def _write_confirmed_records(
    db: Session,
    batch_id: uuid.UUID,
    plans: list[AcceptedItemPlan],
    analysis_results: dict[uuid.UUID, dict[str, Any]],
) -> ConfirmSummary:
    """
    FAZ 3 -- TEK transaction. Yalnızca FAZ 1 ve FAZ 2 TAMAMEN başarılıysa
    çağrılır. Herhangi bir adımda hata olursa TAM rollback -- yarım
    Company/Period/Document/Analysis kaydı asla kalmaz.
    """

    counts = {
        "created_company_count": 0,
        "reused_company_count": 0,
        "created_period_count": 0,
        "reused_period_count": 0,
        "created_document_count": 0,
        "created_analysis_count": 0,
    }
    item_results: list[dict[str, Any]] = []

    try:
        for plan in plans:
            company, company_created = _find_or_create_company(db, plan.company_resolution)
            counts["created_company_count" if company_created else "reused_company_count"] += 1

            period, period_created = _find_or_create_period(
                db, company.id, plan.period_resolution
            )
            counts["created_period_count" if period_created else "reused_period_count"] += 1

            document_type = DETECTED_TO_DOCUMENT_TYPE[plan.detected_document_type]
            engine_result = analysis_results.get(plan.item_id)
            now = datetime.now(timezone.utc)
            is_trial_balance = plan.detected_document_type == DetectedDocumentType.TRIAL_BALANCE

            document = FinancialDocument(
                company_id=company.id,
                period_id=period.id,
                document_type=document_type,
                original_filename=plan.original_filename,
                mime_type=plan.mime_type,
                file_size=plan.file_size,
                checksum=plan.checksum,
                parser_name=PARSER_NAME if is_trial_balance else None,
                parser_version=PARSER_VERSION if is_trial_balance else None,
                processing_status=(
                    ProcessingStatus.COMPLETED if engine_result is not None
                    else ProcessingStatus.PENDING
                ),
                processed_at=now if engine_result is not None else None,
            )
            db.add(document)
            db.flush()
            counts["created_document_count"] += 1

            analysis = None
            if engine_result is not None:
                analysis = FinancialAnalysisResult(
                    company_id=company.id,
                    period_id=period.id,
                    document_id=document.id,
                    analysis_type=AnalysisType.TRIAL_BALANCE,
                    engine_version=ENGINE_VERSION,
                    status=AnalysisStatus.COMPLETED,
                    started_at=now,
                    completed_at=now,
                    result_json=engine_result,
                )
                db.add(analysis)
                db.flush()
                counts["created_analysis_count"] += 1
                document.source_system = engine_result.get("vendor")

            item = db.get(BulkUploadItem, plan.item_id)
            item.resulting_company_id = company.id
            item.resulting_period_id = period.id
            item.resulting_document_id = document.id
            item.resulting_analysis_id = analysis.id if analysis else None

            item_results.append({
                "item_id": plan.item_id,
                "resulting_company_id": company.id,
                "resulting_period_id": period.id,
                "resulting_document_id": document.id,
                "resulting_analysis_id": analysis.id if analysis else None,
            })

        batch = db.get(BulkUploadBatch, batch_id)
        confirmed_at = datetime.now(timezone.utc)
        batch.status = BatchStatus.CONFIRMED
        batch.confirmed_at = confirmed_at

        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception(
            "Confirm yazma transaction'ı başarısız oldu (batch_id=%s)",
            batch_id,
        )
        raise BulkUploadSystemError(
            "Onay sırasında kayıtlar oluşturulamadı; hiçbir değişiklik "
            "uygulanmadı."
        ) from error

    db.refresh(batch)
    return ConfirmSummary(
        batch=batch,
        confirmed_at=confirmed_at,
        counts=counts,
        item_results=item_results,
    )


def confirm_bulk_upload(
    db: Session,
    batch_id: uuid.UUID,
    resubmitted_files: dict[uuid.UUID, "UploadedFileInput"],
) -> ConfirmSummary:
    """Bkz. modül docstring'indeki FAZ 1/2/3 açıklaması."""

    batch = _get_batch_or_404(db, batch_id)

    if batch.status == BatchStatus.CONFIRMED:
        raise BatchImmutableError("Bu batch zaten onaylanmış.")
    if batch.status != BatchStatus.COMPLETED:
        raise BatchNotReadyError(
            "Batch sınıflandırma tamamlanmadan (status=completed olmadan) "
            "onaylanamaz."
        )

    total_item_count = db.scalar(
        select(func.count())
        .select_from(BulkUploadItem)
        .where(BulkUploadItem.batch_id == batch_id)
    ) or 0

    # --- FAZ 1 ---
    plans = _run_confirm_preflight(db, batch, resubmitted_files)

    # Yalnızca-okuma sorgularının açtığı örtük transaction'ı kapat --
    # aşağıdaki (potansiyel olarak yavaş) FAZ 2 sırasında hiçbir DB
    # transaction'ı açık KALMAMALI. (SQLAlchemy Session.rollback() burada
    # zararsızdır: henüz hiçbir INSERT/UPDATE yapılmadı, yalnızca SELECT'ler
    # çalıştı; nesneler expire olur, sonraki erişimde şeffafça yeniden
    # okunur.)
    db.rollback()

    # --- FAZ 2 ---
    analysis_results = _run_confirm_analyses(plans, resubmitted_files)

    # --- FAZ 3 ---
    summary = _write_confirmed_records(db, batch_id, plans, analysis_results)

    summary.counts["ignored_item_count"] = total_item_count - len(plans)
    return summary
