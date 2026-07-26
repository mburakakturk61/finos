import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    BatchStatus,
    ClassificationStatus,
    DetectedDocumentType,
    ItemReviewDecision,
    PeriodType,
)
from app.schemas.company import CompanyBase
from app.schemas.financial_period import FinancialPeriodBase


class BulkUploadItemRead(BaseModel):
    """
    Tek bir dosyanın sınıflandırma taslağı. Bu bir FinancialDocument DEĞİLDİR
    -- fiziksel dosya içeriği hiçbir yerde saklanmaz, yalnızca metadata ve
    tahminler. resulting_*_id alanları yalnızca bu item confirm ile
    BAŞARIYLA production kaydına dönüştürüldüyse dolar; aksi halde (henüz
    confirm edilmemiş veya ignored) hepsi null'dır (Milestone 3 / Adım 1).
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

    user_decision: ItemReviewDecision
    resolution_json: dict[str, Any] | None

    resulting_company_id: uuid.UUID | None
    resulting_period_id: uuid.UUID | None
    resulting_document_id: uuid.UUID | None
    resulting_analysis_id: uuid.UUID | None

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
    confirmed_at: datetime | None


class BulkUploadResponse(BaseModel):
    """
    POST /api/v1/bulk-uploads yanıtı.

    ÖNEMLİ: Bu, bir "sınıflandırma önizlemesi / taslak" (classification
    preview / staging) sonucudur. Hiçbir fiziksel dosya saklanmadı; bu
    yanıttaki item'lar kullanıcı tarafından ONAYLANMADAN (bkz.
    POST /api/v1/bulk-uploads/{batch_id}/confirm) kalıcı FinancialDocument
    kaydına dönüşmez.
    """

    batch: BulkUploadBatchRead
    items: list[BulkUploadItemRead]


# --- Item resolution (Milestone 3 / Adım 1) ---------------------------
#
# Kullanıcının (veya auto_matched item'lar için otomatik ön-doldurmanın)
# önerdiği firma/dönem taslağı. "existing" / "new" ayrık birleşimi
# (discriminated union, `mode` alanı) -- ya var olan bir kayda referans
# ya da yeni bir kayıt için TAM alan kümesi, asla ikisinin karışımı değil.
# Yeni kayıt alanları mevcut CompanyBase/FinancialPeriodBase'den TÜRETİLİR
# -- POST /api/v1/companies ve POST /api/v1/companies/{id}/periods ile
# AYNI validasyon kurallarını (ör. end_date >= start_date) bedavaya alır,
# ayrı bir kopya tanımlanmaz.


class ExistingCompanyResolution(BaseModel):
    mode: Literal["existing"] = "existing"
    id: uuid.UUID


class NewCompanyResolution(CompanyBase):
    mode: Literal["new"] = "new"


ItemResolutionCompany = Annotated[
    Union[ExistingCompanyResolution, NewCompanyResolution],
    Field(discriminator="mode"),
]


class ExistingPeriodResolution(BaseModel):
    mode: Literal["existing"] = "existing"
    id: uuid.UUID


class NewPeriodResolution(FinancialPeriodBase):
    mode: Literal["new"] = "new"


ItemResolutionPeriod = Annotated[
    Union[ExistingPeriodResolution, NewPeriodResolution],
    Field(discriminator="mode"),
]


class ItemResolution(BaseModel):
    """
    BulkUploadItem.resolution_json'ın doğrulanmış şekli. Üç alan da
    bağımsız olarak opsiyoneldir (PATCH kısmi güncelleme yapabilir) --
    ancak `decision=accepted` için company VE period'un İKİSİNİN de
    dolu olması zorunludur (bkz. app/services/bulk_upload.py).
    """

    company: ItemResolutionCompany | None = None
    period: ItemResolutionPeriod | None = None
    # UNKNOWN burada KASITLI OLARAK geçersizdir -- confirm edilecek bir
    # item'ın gerçek bir belge türüne sahip olması gerekir.
    document_type: DetectedDocumentType | None = None

    @model_validator(mode="after")
    def check_document_type_not_unknown(self) -> "ItemResolution":
        if self.document_type == DetectedDocumentType.UNKNOWN:
            raise ValueError(
                "document_type 'unknown' olamaz; kullanıcı gerçek bir "
                "belge türü seçmelidir."
            )
        return self


# --- PATCH /api/v1/bulk-uploads/{batch_id}/items/{item_id} -------------


class BulkUploadItemPatchRequest(BaseModel):
    """
    Kısmi güncelleme: yalnızca gönderilen alanlar değişir. `company`/
    `period`/`document_type` resolution_json'a merge edilir; `decision`
    user_decision'ı doğrudan günceller (accepted için company+period'un
    zaten çözülmüş -- bu istekte VEYA daha önceki bir PATCH'te -- olması
    zorunludur).
    """

    company: ItemResolutionCompany | None = None
    period: ItemResolutionPeriod | None = None
    document_type: DetectedDocumentType | None = None
    decision: ItemReviewDecision | None = None


# --- PATCH /api/v1/bulk-uploads/{batch_id}/items (toplu karar) ---------


class BulkUploadItemBulkDecisionEntry(BaseModel):
    item_id: uuid.UUID
    decision: ItemReviewDecision


class BulkUploadItemBulkPatchRequest(BaseModel):
    """
    Yalnızca KARAR (decision) toplu güncellemesi içindir -- firma/dönem/tür
    düzenlemesi tek tek PATCH /items/{item_id} üzerinden yapılır. Bu,
    50 item için 50 ayrı istek yapılmasını önler: kullanıcı auto_matched
    (ön-doldurulmuş) item'ları tek istekte toplu kabul edebilir.
    """

    items: list[BulkUploadItemBulkDecisionEntry]


class BulkUploadItemBulkPatchResult(BaseModel):
    item_id: uuid.UUID
    success: bool
    user_decision: ItemReviewDecision | None = None
    error: str | None = None


class BulkUploadItemBulkPatchResponse(BaseModel):
    results: list[BulkUploadItemBulkPatchResult]


# --- POST /api/v1/bulk-uploads/{batch_id}/confirm -----------------------


class ConfirmManifestEntry(BaseModel):
    """
    Confirm isteğinin `manifest` form alanındaki JSON dizisinin bir öğesi.
    original_filename yalnızca bilgi/log amaçlıdır (eşleştirme İÇİN
    KULLANILMAZ -- eşleştirme, ilgili multipart `files` parçasının
    dosya adının `item_id` ile birebir aynı olmasıyla yapılır; orijinal
    dosya adları bir batch içinde tekil olmak zorunda olmadığı için
    eşleştirme anahtarı olarak güvenilmezdir).
    """

    item_id: uuid.UUID
    original_filename: str


class BulkUploadConfirmError(BaseModel):
    item_id: uuid.UUID
    code: str
    message: str


class BulkUploadConfirmItemResult(BaseModel):
    item_id: uuid.UUID
    resulting_company_id: uuid.UUID | None = None
    resulting_period_id: uuid.UUID | None = None
    resulting_document_id: uuid.UUID | None = None
    resulting_analysis_id: uuid.UUID | None = None


class BulkUploadConfirmResponse(BaseModel):
    """
    ÖNEMLİ: Confirm sonrasında da fiziksel dosya içeriği saklanmaz --
    yalnızca üretilen FinancialDocument metadata'sı ve (varsa) analiz
    sonucu kalıcı olur. Orijinal dosya bu yanıttan sonra indirilemez veya
    yeniden parse edilemez. Kalıcı object storage bilinçli olarak bu
    adımın kapsamı DIŞINDA bırakılan, açık bir teknik borçtur.
    """

    batch_id: uuid.UUID
    status: BatchStatus
    confirmed_at: datetime

    created_company_count: int
    reused_company_count: int
    created_period_count: int
    reused_period_count: int
    created_document_count: int
    created_analysis_count: int
    ignored_item_count: int

    items: list[BulkUploadConfirmItemResult]
