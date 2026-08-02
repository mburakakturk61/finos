import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.financial_period import FinancialPeriod
from app.models.company import Company
from app.schemas.trial_balance_upload import TrialBalanceUploadResponse
from app.services.trial_balance_upload import (
    DuplicateChecksumError,
    TrialBalanceEngineError,
    UploadValidationError,
    handle_trial_balance_upload,
)
from app.integrations.analysis_http.legacy_security import require_legacy_route_security, resolve_legacy_tenant_id


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/periods", tags=["trial-balances"],
    dependencies=[Depends(require_legacy_route_security)],
)


@router.post(
    "/{period_id}/trial-balances",
    response_model=TrialBalanceUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_trial_balance(
    period_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(resolve_legacy_tenant_id),
) -> TrialBalanceUploadResponse:
    query = select(FinancialPeriod).join(Company).where(FinancialPeriod.id == period_id)
    if tenant_id is not None:
        query = query.where(Company.tenant_id == tenant_id)
    period = db.scalar(query)
    if period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dönem bulunamadı.",
        )

    content = await file.read()

    try:
        result = handle_trial_balance_upload(
            db=db,
            period=period,
            filename=file.filename,
            content=content,
            mime_type=file.content_type or "application/octet-stream",
        )
    except UploadValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except DuplicateChecksumError as error:
        detail = "Bu dönem için aynı içerikte bir belge zaten yüklü."
        if error.existing_document_id is not None:
            detail += f" (document_id={error.existing_document_id})"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from error
    except TrialBalanceEngineError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except Exception as error:
        # Motor sınırının dışında, beklenmeyen bir sistem hatası --
        # tam detay yalnızca uygulama loguna, kullanıcıya asla ham
        # exception metni dönülmez.
        logger.exception(
            "Trial-balance upload sırasında beklenmeyen hata "
            "(period_id=%s)",
            period_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Beklenmeyen bir hata oluştu.",
        ) from error

    return TrialBalanceUploadResponse(
        document=result.document,
        analysis=result.analysis,
    )
