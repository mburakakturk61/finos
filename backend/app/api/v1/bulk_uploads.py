"""
Toplu dosya yükleme + otomatik sınıflandırma önizlemesi (Milestone 2 /
Adım 3).

ÖNEMLİ -- bu bir "sınıflandırma önizlemesi / taslak" (classification
preview / staging) katmanıdır, KALICI belge kaydı DEĞİLDİR:
  * Hiçbir fiziksel dosya İÇERİĞİ hiçbir yerde saklanmaz. Yalnızca
    metadata (dosya adı, mime türü, boyut, checksum) ve
    DocumentClassifier/CompanyIdentityResolver/PeriodDetector'ın
    ürettiği tahminler + kanıtlar (detection_evidence_json) kalıcı olur.
  * Bu endpoint'ten dönen item'lar kullanıcı tarafından ONAYLANMADAN
    FinancialDocument'a (Milestone 2 / Adım 2) dönüşmez. Henüz
    uygulanmamış bir gelecekteki onay adımı, ya dosyaların YENİDEN
    yüklenmesini ya da geçici bir object storage eklenmesini
    gerektirecektir -- bu adımda dosya baytları hiçbir aşamada diske ya
    da DB'ye yazılmaz.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.bulk_upload_item import BulkUploadItem
from app.schemas.bulk_upload import BulkUploadBatchRead, BulkUploadItemRead, BulkUploadResponse
from app.schemas.pagination import Page
from app.services.bulk_upload import (
    BulkUploadSystemError,
    BulkUploadValidationError,
    UploadedFileInput,
    handle_bulk_upload,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bulk-uploads", tags=["bulk-uploads"])


def _get_batch_or_404(batch_id: uuid.UUID, db: Session) -> BulkUploadBatch:
    batch = db.get(BulkUploadBatch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu yükleme kaydı bulunamadı.",
        )
    return batch


@router.post(
    "",
    response_model=BulkUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Birden fazla dosyayı sınıflandırma önizlemesi için yükle",
    description=(
        "Birden fazla dosyayı (PDF/.xlsx/.xls) kabul eder, her birini "
        "firma/yıl/dönem/belge türü açısından sınıflandırır ve bir "
        "TASLAK (staging) sonucu döner. Hiçbir fiziksel dosya içeriği "
        "saklanmaz; yalnızca metadata + sınıflandırma tahminleri kalıcı "
        "olur. Bu adım nihai belge kaydı OLUŞTURMAZ -- onay için ayrı "
        "bir adım gerekir."
    ),
)
async def create_bulk_upload(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> BulkUploadResponse:
    file_inputs: list[UploadedFileInput] = []
    for uploaded_file in files:
        content = await uploaded_file.read()
        file_inputs.append(
            UploadedFileInput(
                filename=uploaded_file.filename,
                content=content,
                mime_type=uploaded_file.content_type,
            )
        )

    try:
        batch = handle_bulk_upload(db=db, files=file_inputs)
    except BulkUploadValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except BulkUploadSystemError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        ) from error
    except Exception as error:
        logger.exception("Toplu yükleme sırasında beklenmeyen hata")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Beklenmeyen bir hata oluştu.",
        ) from error

    return BulkUploadResponse(
        batch=BulkUploadBatchRead.model_validate(batch),
        items=[BulkUploadItemRead.model_validate(item) for item in batch.items],
    )


@router.get("/{batch_id}", response_model=BulkUploadBatchRead)
def get_bulk_upload_batch(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> BulkUploadBatch:
    return _get_batch_or_404(batch_id, db)


@router.get("/{batch_id}/items", response_model=Page[BulkUploadItemRead])
def list_bulk_upload_items(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page[BulkUploadItemRead]:
    _get_batch_or_404(batch_id, db)

    settings = get_settings()
    effective_limit = min(
        limit or settings.default_page_limit,
        settings.max_page_limit,
    )

    total = (
        db.scalar(
            select(func.count())
            .select_from(BulkUploadItem)
            .where(BulkUploadItem.batch_id == batch_id)
        )
        or 0
    )

    items = db.scalars(
        select(BulkUploadItem)
        .where(BulkUploadItem.batch_id == batch_id)
        .order_by(BulkUploadItem.created_at.asc())
        .offset(offset)
        .limit(effective_limit)
    ).all()

    return Page[BulkUploadItemRead](
        items=list(items),
        total=total,
        limit=effective_limit,
        offset=offset,
    )
