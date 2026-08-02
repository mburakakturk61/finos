import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import BatchStatus

if TYPE_CHECKING:
    from app.models.bulk_upload_item import BulkUploadItem


class BulkUploadBatch(Base):
    """
    Bir toplu yükleme / sınıflandırma oturumu (Milestone 2 / Adım 3).

    Bu tablo ve ilişkili BulkUploadItem kayıtları bir "classification
    preview / staging" katmanıdır -- HİÇBİR FİZİKSEL DOSYA İÇERİĞİ
    saklanmaz, yalnızca metadata ve tespit sonuçları.

    Milestone 3 / Adım 1: kullanıcı onayı (confirm) sonrası
    status=CONFIRMED olur ve bu terminal/immutable bir durumdur -- bir
    daha confirm edilemez, item'larına bir daha PATCH uygulanamaz. Onay
    anında -- bu katmanda dosya saklanmadığı için -- confirm isteğinin
    kendisi accepted item'ların orijinal baytlarını yeniden taşır (bkz.
    app/services/bulk_upload.py confirm_bulk_upload). Confirm sonrası da
    fiziksel dosya YİNE saklanmaz; yalnızca üretilen FinancialDocument
    metadata'sı ve analiz sonucu kalıcı olur, orijinal dosya indirilemez
    veya yeniden parse edilemez. Kalıcı bir object storage eklenmesi
    bilinçli olarak bu adımın kapsamı DIŞINDA bırakıldı (bkz. tests/README.md,
    "Milestone 3 / Adım 1" bölümü) -- açık bir teknik borç.
    """

    __tablename__ = "bulk_upload_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("security_tenants.id", ondelete="RESTRICT"), index=True,
    )

    status: Mapped[BatchStatus] = mapped_column(
        Enum(
            BatchStatus,
            name="ck_bulk_upload_batches_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    total_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # document_type != unknown olan item sayısı (unclassified ile ayrık toplam).
    classified_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # document_type == unknown olan item sayısı.
    unclassified_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # classification_status in (duplicate, possible_duplicate) olan item sayısı.
    # classified/unclassified sayaçlarıyla ÖRTÜŞEBİLİR (bağımsız bir boyut) --
    # bir dosya hem "trial_balance olarak tanındı" hem "duplicate" olabilir.
    duplicate_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # cascade kasıtlı olarak "delete" içermiyor; silme DB seviyesinde
    # ondelete="RESTRICT" ile yönetiliyor (bkz. BulkUploadItem). Bu adımda
    # DELETE endpoint'i yok.
    items: Mapped[list["BulkUploadItem"]] = relationship(
        back_populates="batch",
        passive_deletes=True,
    )
