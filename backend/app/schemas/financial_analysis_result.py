import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import AnalysisStatus, AnalysisType


class FinancialAnalysisResultSummary(BaseModel):
    """
    Liste görünümü (GET /documents/{id}/analyses). result_json BİLİNÇLİ
    OLARAK İÇERMEZ -- potansiyel olarak büyük bir JSON gövdesi; tam sonuç
    yalnızca detay endpoint'inde (GET /analyses/{id}) döner.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    period_id: uuid.UUID
    document_id: uuid.UUID
    analysis_type: AnalysisType
    engine_version: str
    status: AnalysisStatus
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class FinancialAnalysisResultRead(FinancialAnalysisResultSummary):
    """Detay görünümü -- result_json dahil."""

    result_json: dict[str, Any] | None
