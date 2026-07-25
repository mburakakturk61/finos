import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod
from app.schemas.financial_analysis_result import FinancialAnalysisResultSummary
from app.schemas.financial_document import FinancialDocumentRead
from app.schemas.pagination import Page


router = APIRouter(prefix="/api/v1", tags=["documents"])


def _get_period_or_404(period_id: uuid.UUID, db: Session) -> FinancialPeriod:
    period = db.get(FinancialPeriod, period_id)

    if period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dönem bulunamadı.",
        )

    return period


def _get_document_or_404(document_id: uuid.UUID, db: Session) -> FinancialDocument:
    document = db.get(FinancialDocument, document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Belge bulunamadı.",
        )

    return document


@router.get(
    "/periods/{period_id}/documents",
    response_model=Page[FinancialDocumentRead],
)
def list_period_documents(
    period_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page[FinancialDocumentRead]:
    _get_period_or_404(period_id, db)

    settings = get_settings()
    effective_limit = min(
        limit or settings.default_page_limit,
        settings.max_page_limit,
    )

    total = (
        db.scalar(
            select(func.count())
            .select_from(FinancialDocument)
            .where(FinancialDocument.period_id == period_id)
        )
        or 0
    )

    documents = db.scalars(
        select(FinancialDocument)
        .where(FinancialDocument.period_id == period_id)
        .order_by(FinancialDocument.uploaded_at.desc())
        .offset(offset)
        .limit(effective_limit)
    ).all()

    return Page[FinancialDocumentRead](
        items=list(documents),
        total=total,
        limit=effective_limit,
        offset=offset,
    )


@router.get("/documents/{document_id}", response_model=FinancialDocumentRead)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FinancialDocument:
    return _get_document_or_404(document_id, db)


@router.get(
    "/documents/{document_id}/analyses",
    response_model=Page[FinancialAnalysisResultSummary],
)
def list_document_analyses(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page[FinancialAnalysisResultSummary]:
    _get_document_or_404(document_id, db)

    settings = get_settings()
    effective_limit = min(
        limit or settings.default_page_limit,
        settings.max_page_limit,
    )

    total = (
        db.scalar(
            select(func.count())
            .select_from(FinancialAnalysisResult)
            .where(FinancialAnalysisResult.document_id == document_id)
        )
        or 0
    )

    analyses = db.scalars(
        select(FinancialAnalysisResult)
        .where(FinancialAnalysisResult.document_id == document_id)
        .order_by(FinancialAnalysisResult.created_at.desc())
        .offset(offset)
        .limit(effective_limit)
    ).all()

    return Page[FinancialAnalysisResultSummary](
        items=list(analyses),
        total=total,
        limit=effective_limit,
        offset=offset,
    )
