"""
Tüm ORM modelleri burada import edilir ki Base.metadata (ve dolayısıyla
Alembic autogenerate) her modeli görsün. Yeni bir model eklendiğinde
buraya da eklenmesi gerekir.
"""

from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.bulk_upload_item import BulkUploadItem
from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.models.company import Company
from app.models.enums import (
    AnalysisSourceRole,
    AnalysisStatus,
    AnalysisType,
    BatchStatus,
    ClassificationStatus,
    DetectedDocumentType,
    DocumentType,
    ItemReviewDecision,
    PeriodStatus,
    PeriodType,
    ProcessingStatus,
    SourceMode,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod
from app.models.orchestration_persistence import (
    OrchestrationArtifact,
    OrchestrationArtifactLocation,
    OrchestrationEngineExecution,
    OrchestrationError,
    OrchestrationPhysicalObject,
    OrchestrationRun,
)
from app.models.security import (
    SecurityMembership,
    SecurityMembershipRole,
    SecurityPermission,
    SecurityPrincipal,
    SecurityProvisioningOperation,
    SecurityResourceBindingQuarantine,
    SecurityRole,
    SecurityRolePermission,
    SecuritySubjectBinding,
    SecurityTenant,
)

__all__ = [
    "Company",
    "FinancialPeriod",
    "FinancialDocument",
    "FinancialAnalysisResult",
    "FinancialAnalysisResultSource",
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
    "ItemReviewDecision",
    "SourceMode",
    "AnalysisSourceRole",
    "OrchestrationRun",
    "OrchestrationEngineExecution",
    "OrchestrationArtifact",
    "OrchestrationPhysicalObject",
    "OrchestrationArtifactLocation",
    "OrchestrationError",
    "AnalysisRunScopeClaim",
    "SecurityTenant",
    "SecurityPrincipal",
    "SecuritySubjectBinding",
    "SecurityMembership",
    "SecurityPermission",
    "SecurityRole",
    "SecurityRolePermission",
    "SecurityMembershipRole",
    "SecurityProvisioningOperation",
    "SecurityResourceBindingQuarantine",
]
