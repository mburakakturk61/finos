import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import (
    ClassificationStatus,
    DetectedDocumentType,
    ItemReviewDecision,
    PeriodType,
)

if TYPE_CHECKING:
    from app.models.bulk_upload_batch import BulkUploadBatch


class BulkUploadItem(Base):
    """
    Toplu yüklemede tek bir dosyanın sınıflandırma sonucu (Milestone 2 /
    Adım 3). Fiziksel dosya içeriği HİÇ saklanmaz -- yalnızca metadata
    (ad, mime, boyut, checksum) ve DocumentClassifier/CompanyIdentityResolver/
    PeriodDetector'ın ürettiği tahminler + kanıtlar.

    checksum üzerinde KASITLI OLARAK unique constraint YOK: bu taslak
    katmanda aynı checksum'a sahip birden fazla kayıt bir hata değil,
    kullanıcıya sunulacak bir bulgudur (classification_status=duplicate /
    possible_duplicate). Sert engelleme (409) yalnızca onaylanmış
    FinancialDocument akışında (Milestone 2 / Adım 2) uygulanıyor.

    Milestone 3 / Adım 1: kullanıcının inceleme kararı (user_decision) ve
    önerdiği/düzenlediği firma-dönem-tür çözümü (resolution_json) burada
    tutulur. classification_status (motor çıktısı) ile user_decision
    (insan kararı) BİLEREK ayrı alanlardır. resolution_json hiçbir
    production tabloya yazma YAPMAZ -- yalnızca confirm anında
    kullanılacak bir taslaktır. resulting_*_id alanları yalnızca confirm
    BAŞARILI olduktan sonra dolar; ignored veya hiç confirm edilmemiş bir
    item'da bunlar her zaman NULL kalır.
    """

    __tablename__ = "bulk_upload_items"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bulk_upload_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    detected_document_type: Mapped[DetectedDocumentType] = mapped_column(
        Enum(
            DetectedDocumentType,
            name="ck_bulk_upload_items_detected_document_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    detected_company_name: Mapped[str | None] = mapped_column(String(255))
    detected_tax_number: Mapped[str | None] = mapped_column(String(32))
    detected_year: Mapped[int | None] = mapped_column(Integer)

    # Mevcut PeriodType (Milestone 2 / Adım 1) BİLEREK tekrar kullanılıyor --
    # "tespit edilen dönem tipi" ile sistemin geri kalanındaki dönem tipi
    # aynı kavram; ayrı bir enum gereksiz kopya olurdu.
    detected_period_type: Mapped[PeriodType | None] = mapped_column(
        Enum(
            PeriodType,
            name="ck_bulk_upload_items_detected_period_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    detected_period_number: Mapped[int | None] = mapped_column(Integer)

    # document_type / company_identity / period bileşen güvenlerinin
    # MİNİMUMU (en zayıf halka belirleyici). 0.00-1.00 aralığında sabit
    # noktalı -- float ikili yuvarlama belirsizliğinden kaçınmak için
    # Numeric(3,2) (parasal bir alan değil, olasılık benzeri bir skor).
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    classification_status: Mapped[ClassificationStatus] = mapped_column(
        Enum(
            ClassificationStatus,
            name="ck_bulk_upload_items_classification_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    warnings_json: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    detection_evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )

    # Kullanıcının kararı (Milestone 3 / Adım 1) -- classification_status
    # (yukarıda) ile KARIŞTIRILMAMALI, bkz. class docstring.
    user_decision: Mapped[ItemReviewDecision] = mapped_column(
        Enum(
            ItemReviewDecision,
            name="ck_bulk_upload_items_user_decision",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ItemReviewDecision.PENDING,
    )

    # Kullanıcının (veya auto_matched item'lar için otomatik ön-doldurmanın)
    # önerdiği firma/dönem/belge türü taslağı. Şekli app.schemas.bulk_upload
    # içindeki Pydantic şemalarıyla (ItemResolutionCompany/Period) doğrulanır
    # -- detection_evidence_json/warnings_json gibi DB seviyesinde
    # zorlanmıyor, uygulama katmanında. confirm bu alanı OKUR, hiçbir zaman
    # tek başına production tablosuna yazmaz.
    resolution_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )

    # Yalnızca confirm BAŞARILI olduktan sonra dolar (audit izi). RESTRICT --
    # bu kayıtlar asla CASCADE ile silinemez.
    #
    # ForeignKey(name=...) BİLEREK açıkça verildi: naming convention'ın
    # varsayılan üretimi (fk_bulk_upload_items_resulting_<kolon>_<referans
    # tablo>) "financial_analysis_results" gibi uzun tablo adlarıyla
    # PostgreSQL'in 63 karakter identifier sınırını AŞIYOR (69 karaktere
    # çıkıyordu). Dördü de -- yalnızca sınırı aşan değil -- tutarlılık için
    # aynı kısaltılmış "fk_bulk_upload_items_resulting_<hedef>" kalıbını
    # kullanır (referans tablo adı isimden bilerek çıkarıldı; kolon adının
    # kendisi zaten hedefi açıkça belirtiyor).
    resulting_company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="RESTRICT",
            name="fk_bulk_upload_items_resulting_company",
        ),
        index=True,
    )
    resulting_period_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "financial_periods.id",
            ondelete="RESTRICT",
            name="fk_bulk_upload_items_resulting_period",
        ),
        index=True,
    )
    resulting_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "financial_documents.id",
            ondelete="RESTRICT",
            name="fk_bulk_upload_items_resulting_document",
        ),
        index=True,
    )
    resulting_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "financial_analysis_results.id",
            ondelete="RESTRICT",
            name="fk_bulk_upload_items_resulting_analysis",
        ),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    batch: Mapped["BulkUploadBatch"] = relationship(back_populates="items")
