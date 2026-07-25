import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, func
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
    saklanmaz, yalnızca metadata ve tespit sonuçları. Company/
    FinancialPeriod/FinancialDocument (Milestone 2 / Adım 1-2) ile HENÜZ
    hiçbir ilişkisi yok; kullanıcı onayı sonrası gerçek kayıtlara
    bağlama ayrı bir sonraki adımdır. Onay anında -- bu adımda dosya
    saklanmadığı için -- ya dosyaların yeniden yüklenmesi istenecek ya da
    ileride geçici bir object storage eklenecektir.
    """

    __tablename__ = "bulk_upload_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
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

    # cascade kasıtlı olarak "delete" içermiyor; silme DB seviyesinde
    # ondelete="RESTRICT" ile yönetiliyor (bkz. BulkUploadItem). Bu adımda
    # DELETE endpoint'i yok.
    items: Mapped[list["BulkUploadItem"]] = relationship(
        back_populates="batch",
        passive_deletes=True,
    )
