import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import BatchStatus, ClassificationStatus, DetectedDocumentType, PeriodType


class BulkUploadItemRead(BaseModel):
    """
    Tek bir dosyanın sınıflandırma taslağı. Bu bir FinancialDocument DEĞİLDİR
    -- fiziksel dosya içeriği hiçbir yerde saklanmaz, yalnızca metadata ve
    tahminler. Bir sonraki (henüz yapılmamış) onay adımı ya dosyaların
    yeniden yüklenmesini ya da geçici bir object storage eklenmesini
    gerektirecektir.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size: int
    checksum: str

    detected_document_type: DetectedDocumentType
    detected_company_name: str | None
    detected_tax_number: str | None
    detected_year: int | None
    detected_period_type: PeriodType | None
    detected_period_number: int | None

    confidence_score: Decimal
    classification_status: ClassificationStatus

    warnings_json: list[Any]
    detection_evidence_json: dict[str, Any]

    created_at: datetime


class BulkUploadBatchRead(BaseModel):
    """GET /api/v1/bulk-uploads/{batch_id} yanıtı (item'sız özet)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: BatchStatus
    total_file_count: int
    classified_file_count: int
    unclassified_file_count: int
    duplicate_file_count: int
    created_at: datetime
    completed_at: datetime | None


class BulkUploadResponse(BaseModel):
    """
    POST /api/v1/bulk-uploads yanıtı.

    ÖNEMLİ: Bu, bir "sınıflandırma önizlemesi / taslak" (classification
    preview / staging) sonucudur. Hiçbir fiziksel dosya saklanmadı; bu
    yanıttaki item'lar kullanıcı tarafından ONAYLANMADAN kalıcı
    FinancialDocument kaydına dönüşmez. Onay adımı (bu milestone'un
    kapsamı dışında) dosyaların yeniden yüklenmesini ya da geçici bir
    object storage eklenmesini gerektirecektir.
    """

    batch: BulkUploadBatchRead
    items: list[BulkUploadItemRead]
