import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyRead
from app.schemas.pagination import Page
from app.integrations.analysis_http.legacy_security import (
    require_legacy_route_security,
    resolve_legacy_tenant_id,
)


router = APIRouter(
    prefix="/api/v1/companies", tags=["companies"],
    dependencies=[Depends(require_legacy_route_security)],
)


@router.post(
    "",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
)
def create_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(resolve_legacy_tenant_id),
) -> Company:
    company = Company(tenant_id=tenant_id, **payload.model_dump())
    db.add(company)

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu vergi numarasına sahip bir firma zaten kayıtlı.",
        ) from error

    db.refresh(company)
    return company


@router.get("", response_model=Page[CompanyRead])
def list_companies(
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(resolve_legacy_tenant_id),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page[CompanyRead]:
    settings = get_settings()
    effective_limit = min(
        limit or settings.default_page_limit,
        settings.max_page_limit,
    )

    scope_filter = Company.tenant_id == tenant_id if tenant_id is not None else True
    total = db.scalar(select(func.count()).select_from(Company).where(scope_filter)) or 0

    companies = db.scalars(
        select(Company)
        .where(scope_filter)
        .order_by(Company.created_at.desc(), Company.id)
        .offset(offset)
        .limit(effective_limit)
    ).all()

    return Page[CompanyRead](
        items=list(companies),
        total=total,
        limit=effective_limit,
        offset=offset,
    )


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(resolve_legacy_tenant_id),
) -> Company:
    query = select(Company).where(Company.id == company_id)
    if tenant_id is not None:
        query = query.where(Company.tenant_id == tenant_id)
    company = db.scalar(query)

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Firma bulunamadı.",
        )

    return company
