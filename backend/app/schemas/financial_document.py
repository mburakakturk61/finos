import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DocumentType, ProcessingStatus


class FinancialDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    period_id: uuid.UUID
    document_type: DocumentType
    original_filename: str
    mime_type: str
    file_size: int
    checksum: str
    source_system: str | None
    parser_name: str | None
    parser_version: str | None
    processing_status: ProcessingStatus
    uploaded_at: datetime
    processed_at: datetime | None
    error_message: str | None
