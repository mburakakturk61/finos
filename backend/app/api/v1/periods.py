import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.company import Company
from app.models.financial_period import FinancialPeriod
from app.schemas.financial_period import (
    FinancialPeriodCreate,
    FinancialPeriodRead,
)
from app.schemas.pagination import Page


router = APIRouter(prefix="/api/v1", tags=["periods"])


def _get_company_or_404(company_id: uuid.UUID, db: Session) -> Company:
    company = db.get(Company, company_id)

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Firma bulunamadı.",
        )

    return company


@router.post(
    "/companies/{company_id}/periods",
    response_model=FinancialPeriodRead,
    status_code=status.HTTP_201_CREATED,
)
def create_period(
    company_id: uuid.UUID,
    payload: FinancialPeriodCreate,
    db: Session = Depends(get_db),
) -> FinancialPeriod:
    _get_company_or_404(company_id, db)

    period = FinancialPeriod(
        company_id=company_id,
        **payload.model_dump(),
    )
    db.add(period)

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Bu firma için aynı yıl, dönem tipi ve dönem numarasına "
                "sahip bir dönem zaten var."
            ),
        ) from error

    db.refresh(period)
    return period


@router.get(
    "/companies/{company_id}/periods",
    response_model=Page[FinancialPeriodRead],
)
def list_periods(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page[FinancialPeriodRead]:
    _get_company_or_404(company_id, db)

    settings = get_settings()
    effective_limit = min(
        limit or settings.default_page_limit,
        settings.max_page_limit,
    )

    total = (
        db.scalar(
            select(func.count())
            .select_from(FinancialPeriod)
            .where(FinancialPeriod.company_id == company_id)
        )
        or 0
    )

    periods = db.scalars(
        select(FinancialPeriod)
        .where(FinancialPeriod.company_id == company_id)
        .order_by(
            FinancialPeriod.year.desc(),
            FinancialPeriod.period_number.desc(),
        )
        .offset(offset)
        .limit(effective_limit)
    ).all()

    return Page[FinancialPeriodRead](
        items=list(periods),
        total=total,
        limit=effective_limit,
        offset=offset,
    )


@router.get("/periods/{period_id}", response_model=FinancialPeriodRead)
def get_period(
    period_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FinancialPeriod:
    period = db.get(FinancialPeriod, period_id)

    if period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dönem bulunamadı.",
        )

    return period
