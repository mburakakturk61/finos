"""
Tüm ORM modelleri burada import edilir ki Base.metadata (ve dolayısıyla
Alembic autogenerate) her modeli görsün. Yeni bir model eklendiğinde
buraya da eklenmesi gerekir.
"""

from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.bulk_upload_item import BulkUploadItem
from app.models.company import Company
from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    BatchStatus,
    ClassificationStatus,
    DetectedDocumentType,
    DocumentType,
    PeriodStatus,
    PeriodType,
    ProcessingStatus,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod

__all__ = [
    "Company",
    "FinancialPeriod",
    "FinancialDocument",
    "FinancialAnalysisResult",
    "BulkUploadBatch",
    "BulkUploadItem",
    "PeriodType",
    "PeriodStatus",
    "DocumentType",
    "ProcessingStatus",
    "AnalysisType",
    "AnalysisStatus",
    "BatchStatus",
    "DetectedDocumentType",
    "ClassificationStatus",
]
