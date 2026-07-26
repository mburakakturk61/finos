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

import json
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.bulk_upload_item import BulkUploadItem
from app.schemas.bulk_upload import (
    BulkUploadBatchRead,
    BulkUploadConfirmItemResult,
    BulkUploadConfirmResponse,
    BulkUploadItemBulkPatchRequest,
    BulkUploadItemBulkPatchResponse,
    BulkUploadItemBulkPatchResult,
    BulkUploadItemPatchRequest,
    BulkUploadItemRead,
    BulkUploadResponse,
    ConfirmManifestEntry,
)
from app.schemas.pagination import Page
from app.services.bulk_upload import (
    BatchImmutableError,
    BatchNotReadyError,
    BulkUploadNotFoundError,
    BulkUploadSystemError,
    BulkUploadValidationError,
    ConfirmPreflightError,
    ItemPatchValidationError,
    UploadedFileInput,
    bulk_patch_item_decisions,
    confirm_bulk_upload,
    handle_bulk_upload,
    patch_bulk_upload_item,
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


# --- Milestone 3 / Adım 1: review + confirm -----------------------------


@router.patch(
    "/{batch_id}/items/{item_id}",
    response_model=BulkUploadItemRead,
    summary="Bir staging item'ını düzenle (firma/dönem/tür/karar)",
    description=(
        "Kısmi güncelleme -- yalnızca gönderilen alanlar değişir. "
        "'accepted' kararı için firma VE dönem çözümünün (bu istekte "
        "veya daha önce -- otomatik ön-doldurma dahil) zaten mevcut "
        "olması gerekir. Onaylanmış (confirmed) bir batch'in item'ları "
        "immutable'dır (409)."
    ),
)
def update_bulk_upload_item(
    batch_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: BulkUploadItemPatchRequest,
    db: Session = Depends(get_db),
) -> BulkUploadItem:
    company = (
        payload.company.model_dump(mode="json") if payload.company is not None else None
    )
    period = (
        payload.period.model_dump(mode="json") if payload.period is not None else None
    )
    document_type = payload.document_type.value if payload.document_type is not None else None
    decision = payload.decision.value if payload.decision is not None else None

    try:
        return patch_bulk_upload_item(
            db,
            batch_id,
            item_id,
            company=company,
            period=period,
            document_type=document_type,
            decision=decision,
        )
    except BulkUploadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except BatchImmutableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except ItemPatchValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except Exception as error:
        logger.exception(
            "Item PATCH sırasında beklenmeyen hata (item_id=%s)", item_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Beklenmeyen bir hata oluştu.",
        ) from error


@router.patch(
    "/{batch_id}/items",
    response_model=BulkUploadItemBulkPatchResponse,
    summary="Birden fazla item için toplu karar (accept/ignore)",
    description=(
        "Yalnızca KARAR (decision) toplu günceller -- firma/dönem/tür "
        "düzenlemesi için tek tek PATCH /items/{item_id} kullanılır. Bu, "
        "yüksek güvenle otomatik ön-doldurulmuş (auto_matched) item'ların "
        "kullanıcı tarafından tek tek düzenlenmeden toplu kabul "
        "edilebilmesini sağlar. Kısmi başarı modeli: geçersiz bir "
        "item_id veya eksik resolution'lı bir 'accepted' isteği DİĞER "
        "item'ları etkilemez -- her item için ayrı sonuç döner."
    ),
)
def bulk_update_bulk_upload_items(
    batch_id: uuid.UUID,
    payload: BulkUploadItemBulkPatchRequest,
    db: Session = Depends(get_db),
) -> BulkUploadItemBulkPatchResponse:
    decisions = [(entry.item_id, entry.decision.value) for entry in payload.items]

    try:
        results = bulk_patch_item_decisions(db, batch_id, decisions)
    except BulkUploadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except BatchImmutableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except Exception as error:
        logger.exception(
            "Toplu karar güncellemesi sırasında beklenmeyen hata "
            "(batch_id=%s)",
            batch_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Beklenmeyen bir hata oluştu.",
        ) from error

    return BulkUploadItemBulkPatchResponse(
        results=[BulkUploadItemBulkPatchResult(**result) for result in results]
    )


@router.post(
    "/{batch_id}/confirm",
    response_model=BulkUploadConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Kabul edilen item'ları production kayıtlarına dönüştür",
    description=(
        "Yalnızca user_decision='accepted' item'lar işlenir. İçerik "
        "gerektiren türler (şu an yalnızca trial_balance) için orijinal "
        "dosya baytının `files` alanında YENİDEN gönderilmesi zorunludur "
        "-- diğer türler (ör. corporate_tax_return, balance_sheet) için "
        "henüz bir analiz motoru olmadığından dosya istenmez, "
        "FinancialDocument staging metadata'sından oluşturulur. Her "
        "multipart dosya parçasının adı (filename) `manifest` JSON "
        "alanındaki ilgili item_id ile BİREBİR aynı olmalıdır (orijinal "
        "dosya adı değil -- bir batch içinde tekil olmayabilir). Tüm "
        "doğrulama ve analiz adımları TAMAMEN başarılı olmadan hiçbir "
        "kayıt yazılmaz (all-or-nothing, tam rollback). Onay sonrasında "
        "da fiziksel dosya içeriği YİNE saklanmaz -- yalnızca üretilen "
        "FinancialDocument metadata'sı ve analiz sonucu kalıcı olur; "
        "kalıcı object storage bu adımın kapsamı dışında bırakılmış "
        "açık bir teknik borçtur.\n\n"
        "Örnek istek (multipart/form-data):\n"
        "  manifest: "
        '[{"item_id": "11111111-1111-1111-1111-111111111111", '
        '"original_filename": "mizan.xlsx"}]\n'
        "  files: (dosya parçasının adı/filename'i = "
        '"11111111-1111-1111-1111-111111111111")'
    ),
)
async def confirm_bulk_upload_endpoint(
    batch_id: uuid.UUID,
    manifest: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
) -> BulkUploadConfirmResponse:
    try:
        raw_entries = json.loads(manifest)
        manifest_entries = [ConfirmManifestEntry.model_validate(entry) for entry in raw_entries]
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "manifest alanı geçerli bir JSON dizisi "
                "([{item_id, original_filename}, ...]) değil."
            ),
        ) from error

    manifest_item_ids = {entry.item_id for entry in manifest_entries}

    resubmitted_files: dict[uuid.UUID, UploadedFileInput] = {}
    for uploaded_file in files:
        if not uploaded_file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Her multipart dosya parçasının adı (filename) "
                    "ilgili item_id olmalıdır; adsız bir parça bulundu."
                ),
            )
        try:
            file_item_id = uuid.UUID(uploaded_file.filename)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"'{uploaded_file.filename}' geçerli bir item_id "
                    "(UUID) değil -- her dosya parçasının adı ilgili "
                    "item_id olmalıdır (orijinal dosya adı değil)."
                ),
            )
        if file_item_id not in manifest_item_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{file_item_id}' manifest'te tanımlı değil.",
            )
        content = await uploaded_file.read()
        resubmitted_files[file_item_id] = UploadedFileInput(
            filename=None,
            content=content,
            mime_type=uploaded_file.content_type,
        )

    try:
        summary = confirm_bulk_upload(db, batch_id, resubmitted_files)
    except BulkUploadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (BatchImmutableError, BatchNotReadyError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except ConfirmPreflightError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "errors": [
                    {
                        "item_id": str(item_error["item_id"]),
                        "code": item_error["code"],
                        "message": item_error["message"],
                    }
                    for item_error in error.errors
                ]
            },
        ) from error
    except BulkUploadSystemError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        ) from error
    except Exception as error:
        logger.exception(
            "Confirm sırasında beklenmeyen hata (batch_id=%s)", batch_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Beklenmeyen bir hata oluştu.",
        ) from error

    return BulkUploadConfirmResponse(
        batch_id=summary.batch.id,
        status=summary.batch.status,
        confirmed_at=summary.confirmed_at,
        created_company_count=summary.counts["created_company_count"],
        reused_company_count=summary.counts["reused_company_count"],
        created_period_count=summary.counts["created_period_count"],
        reused_period_count=summary.counts["reused_period_count"],
        created_document_count=summary.counts["created_document_count"],
        created_analysis_count=summary.counts["created_analysis_count"],
        ignored_item_count=summary.counts["ignored_item_count"],
        items=[
            BulkUploadConfirmItemResult(**item_result)
            for item_result in summary.item_results
        ],
    )
