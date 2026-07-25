from pydantic import BaseModel

from app.schemas.financial_analysis_result import FinancialAnalysisResultRead
from app.schemas.financial_document import FinancialDocumentRead


class TrialBalanceUploadResponse(BaseModel):
    """POST /api/v1/periods/{period_id}/trial-balances yanıtı."""

    document: FinancialDocumentRead
    analysis: FinancialAnalysisResultRead
