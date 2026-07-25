import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.schemas.financial_analysis_result import FinancialAnalysisResultRead


router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])


@router.get("/{analysis_id}", response_model=FinancialAnalysisResultRead)
def get_analysis(
    analysis_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FinancialAnalysisResult:
    analysis = db.get(FinancialAnalysisResult, analysis_id)

    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analiz sonucu bulunamadı.",
        )

    return analysis
