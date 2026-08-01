"""
Bir mizan dosyasını belirli bir firma/döneme bağlayan, FinancialDocument +
FinancialAnalysisResult kayıtlarını oluşturan ve mevcut trial_balance
motorunu (app.trial_balance.service.analyze_trial_balance) çalıştıran
orkestrasyon katmanı (Milestone 2 / Adım 2).

ÖNEMLİ: Bu dosya trial_balance motorunun hesaplama mantığına HİÇ dokunmaz;
yalnızca motoru bir sınır (boundary) olarak çağırır ve sonucunu/hatasını
veritabanına yazar. parser_name/parser_version/engine_version sabitleri
bilinçli olarak burada tanımlandı, app/trial_balance/** paketine
eklenmedi -- o pakete sıfır dokunuş garantisi korunuyor.

Aşamalı (iki transaction'lı) akış:
  1) FinancialDocument + FinancialAnalysisResult PROCESSING durumunda
     oluşturulup commit edilir -- motor hiç çalışmadan ÖNCE audit kaydı
     kalıcı hale gelir.
  2) Motor (transaction dışında) çalıştırılır.
  3) Sonuca göre ikinci bir transaction ile COMPLETED/FAILED durumuna
     güncellenip commit edilir.
Böylece süreç motor çalışırken ya da adım 3'te çökse bile en azından
"PROCESSING'te kaldı" durumundaki bir audit kaydı her zaman kalıcıdır.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import AnalysisStatus, AnalysisType, DocumentType, ProcessingStatus
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod
from app.orchestration_persistence.codec import canonical_json_bytes
from app.trial_balance.service import analyze_trial_balance


logger = logging.getLogger(__name__)


PARSER_NAME = "generic"
PARSER_VERSION = "1.0.0"
ENGINE_VERSION = "1.0.0"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSION = ".xlsx"

# DB'ye ve HTTP response'a yazılan mesajlar HER ZAMAN bu sabit,
# önceden yazılmış string'lerden seçilir -- ham exception metni veya
# stack trace hiçbir şekilde bu ikisine yazılmaz (yalnızca uygulama
# loguna, logger.exception ile).
GENERIC_FILE_ERROR_MESSAGE = (
    "Excel dosyası okunamadı veya ayrıştırılamadı. Dosya bozuk ya da "
    "beklenen mizan formatında olmayabilir."
)
GENERIC_SYSTEM_ERROR_MESSAGE = "Analiz sırasında beklenmeyen bir hata oluştu."


class UploadValidationError(Exception):
    """Dosya, motor hiç çalıştırılmadan ÖNCE reddedildi (router -> 400)."""


class DuplicateChecksumError(Exception):
    """Aynı dönem için aynı checksum zaten var (router -> 409)."""

    def __init__(self, existing_document_id: uuid.UUID | None):
        self.existing_document_id = existing_document_id
        super().__init__("duplicate checksum for period")


class TrialBalanceEngineError(Exception):
    """
    Motor sınırında oluşan, kullanıcının dosyasına atfedilen hata
    (router -> 422). Mesajı her zaman GENERIC_FILE_ERROR_MESSAGE'dır.
    """


class TrialBalanceUploadResult:
    def __init__(
        self,
        document: FinancialDocument,
        analysis: FinancialAnalysisResult,
    ) -> None:
        self.document = document
        self.analysis = analysis


def _validate_upload(filename: str | None, content: bytes) -> None:
    if not filename:
        raise UploadValidationError("Dosya adı bulunamadı.")

    if not filename.lower().endswith(ALLOWED_EXTENSION):
        raise UploadValidationError(
            "Şimdilik yalnızca .xlsx dosyaları kabul edilir."
        )

    if not content:
        raise UploadValidationError("Yüklenen dosya boş.")

    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("Dosya boyutu 10 MB sınırını aşıyor.")


def _find_existing_by_checksum(
    db: Session,
    period_id: uuid.UUID,
    checksum: str,
) -> FinancialDocument | None:
    return db.scalars(
        select(FinancialDocument).where(
            FinancialDocument.period_id == period_id,
            FinancialDocument.checksum == checksum,
        )
    ).first()


def _mark_failed(
    db: Session,
    document: FinancialDocument,
    analysis: FinancialAnalysisResult,
    message: str,
) -> None:
    """Motor hatası (422) sonrası document+analysis'i FAILED işaretler.
    Bu da başarısız olursa yalnızca loglar, exception'ı yutar -- çağıran
    zaten kendi hatasını (TrialBalanceEngineError) fırlatacak."""

    try:
        failed_at = datetime.now(timezone.utc)
        document.processing_status = ProcessingStatus.FAILED
        document.processed_at = failed_at
        analysis.status = AnalysisStatus.FAILED
        analysis.completed_at = failed_at
        analysis.error_message = message
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Motor hatası sonrası failed durumuna güncelleme de "
            "başarısız oldu (document_id=%s)",
            document.id,
        )


def _best_effort_mark_failed(
    db: Session,
    document_id: uuid.UUID,
    analysis_id: uuid.UUID,
) -> None:
    """
    Başarı yolundaki (transaction 2b) güncelleme beklenmedik şekilde
    çöktüğünde çağrılır. Nesneleri YENİDEN sorgulayarak, ayrı ve
    korumalı bir denemeyle failed işaretler. Bu da başarısız olursa
    yalnızca loglar; çağıran zaten orijinal hatayı yeniden fırlatıp
    router'ın 500 dönmesini sağlayacaktır.
    """

    try:
        document = db.get(FinancialDocument, document_id)
        analysis = db.get(FinancialAnalysisResult, analysis_id)

        if document is not None and analysis is not None:
            failed_at = datetime.now(timezone.utc)
            document.processing_status = ProcessingStatus.FAILED
            document.processed_at = failed_at
            analysis.status = AnalysisStatus.FAILED
            analysis.completed_at = failed_at
            analysis.error_message = GENERIC_SYSTEM_ERROR_MESSAGE
            db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "best-effort failed güncellemesi de başarısız oldu "
            "(document_id=%s, analysis_id=%s)",
            document_id,
            analysis_id,
        )


def handle_trial_balance_upload(
    db: Session,
    period: FinancialPeriod,
    filename: str | None,
    content: bytes,
    mime_type: str,
) -> TrialBalanceUploadResult:
    _validate_upload(filename, content)

    checksum = hashlib.sha256(content).hexdigest()

    # Ön-kontrol: gereksiz motor çalıştırmayı önlemek için. Gerçek garanti
    # aşağıdaki UniqueConstraint(period_id, checksum) + IntegrityError
    # yakalama -- burası yalnızca hızlı/erken bir kısayol.
    existing = _find_existing_by_checksum(db, period.id, checksum)
    if existing is not None:
        raise DuplicateChecksumError(existing_document_id=existing.id)

    document_id = uuid.uuid4()
    analysis_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    document = FinancialDocument(
        id=document_id,
        company_id=period.company_id,
        period_id=period.id,
        document_type=DocumentType.TRIAL_BALANCE,
        original_filename=filename,
        mime_type=mime_type,
        file_size=len(content),
        checksum=checksum,
        source_system=None,  # motor çalışmadan önce bilinmiyor
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        processing_status=ProcessingStatus.PROCESSING,
    )
    analysis = FinancialAnalysisResult(
        id=analysis_id,
        company_id=period.company_id,
        period_id=period.id,
        document_id=document_id,
        analysis_type=AnalysisType.TRIAL_BALANCE,
        engine_version=ENGINE_VERSION,
        status=AnalysisStatus.PROCESSING,
        started_at=started_at,
    )

    db.add(document)
    db.add(analysis)

    # --- TRANSACTION 1: audit kaydı motor çalışmadan ÖNCE kalıcı olur ---
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        conflicting = _find_existing_by_checksum(db, period.id, checksum)
        raise DuplicateChecksumError(
            existing_document_id=conflicting.id if conflicting else None
        ) from error

    db.refresh(document)
    db.refresh(analysis)

    # --- MOTOR ÇAĞRISI (açık transaction dışında, saf hesaplama) ---
    try:
        result = analyze_trial_balance(content=content, filename=filename)
    except Exception:
        logger.exception(
            "trial_balance motoru belgeyi işlerken hata verdi "
            "(document_id=%s)",
            document_id,
        )
        _mark_failed(db, document, analysis, GENERIC_FILE_ERROR_MESSAGE)
        raise TrialBalanceEngineError(GENERIC_FILE_ERROR_MESSAGE)

    # --- TRANSACTION 2: başarı durumunu kalıcı hale getir ---
    try:
        completed_at = datetime.now(timezone.utc)
        document.processing_status = ProcessingStatus.COMPLETED
        document.processed_at = completed_at
        document.source_system = result.get("vendor")
        analysis.status = AnalysisStatus.COMPLETED
        analysis.completed_at = completed_at
        analysis.result_json = result
        analysis.canonical_result_digest = hashlib.sha256(
            canonical_json_bytes(result)
        ).hexdigest()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Analiz sonucu kaydedilirken beklenmeyen hata "
            "(document_id=%s)",
            document_id,
        )
        _best_effort_mark_failed(db, document_id, analysis_id)
        raise

    db.refresh(document)
    db.refresh(analysis)

    return TrialBalanceUploadResult(document=document, analysis=analysis)
