import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.financial_document import FinancialDocument
    from app.models.financial_period import FinancialPeriod


class Company(Base):
    """
    Analiz yapılan gerçek veya tüzel kişi.
    Bkz. docs/FINOS_ARCHITECTURE_V1.md bölüm 4.1.

    Not: Blueprint'teki tam alan kümesinin bir alt kümesi uygulanıyor.
    `registration_number`, `establishment_date`, `country`, `city` bu
    milestone'da bilinçli olarak dışarıda bırakıldı (Milestone 2 kapsam
    kararı) ve ileride eklenebilir.
    """

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("security_tenants.id", ondelete="RESTRICT"), index=True,
    )

    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(255))

    # Vergi numarası firma içinde benzersiz olmalıdır (blueprint kuralı).
    tax_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        index=True,
    )
    tax_office: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(255))
    nace_code: Mapped[str | None] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # cascade kasıtlı olarak "delete"/"delete-orphan" İÇERMİYOR: silme
    # davranışı DB seviyesinde ondelete="RESTRICT" ile yönetiliyor (bkz.
    # FinancialPeriod/FinancialDocument). passive_deletes=True, ORM'un bir
    # Company silinirken alt kayıtları yükleyip FK'yi null'a çekmeye
    # çalışmasını (ki company_id NOT NULL olduğu için bu zaten başarısız
    # olurdu) ENGELLER; DELETE doğrudan veritabanına gönderilir ve
    # RESTRICT kuralı temiz bir IntegrityError ile devreye girer.
    # Bu milestone'da zaten DELETE endpoint'i yok. İleride gerçek silme
    # ihtiyacı doğarsa RESTRICT korunarak deleted_at/is_active tabanlı
    # soft delete eklenmesi öneriliyor.
    periods: Mapped[list["FinancialPeriod"]] = relationship(
        back_populates="company",
        passive_deletes=True,
    )
    documents: Mapped[list["FinancialDocument"]] = relationship(
        back_populates="company",
        foreign_keys="[FinancialDocument.company_id]",
        passive_deletes=True,
    )
