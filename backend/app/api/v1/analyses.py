import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.company import Company
from app.schemas.financial_analysis_result import FinancialAnalysisResultRead
from app.integrations.analysis_http.legacy_security import require_legacy_route_security, resolve_legacy_tenant_id


router = APIRouter(
    prefix="/api/v1/analyses", tags=["analyses"],
    dependencies=[Depends(require_legacy_route_security)],
)


@router.get("/{analysis_id}", response_model=FinancialAnalysisResultRead)
def get_analysis(
    analysis_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(resolve_legacy_tenant_id),
) -> FinancialAnalysisResult:
    query = select(FinancialAnalysisResult).join(
        Company, Company.id == FinancialAnalysisResult.company_id,
    ).where(FinancialAnalysisResult.id == analysis_id)
    if tenant_id is not None:
        query = query.where(Company.tenant_id == tenant_id)
    analysis = db.scalar(query)

    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analiz sonucu bulunamadı.",
        )

    return analysis
