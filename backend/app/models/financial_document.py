import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import DocumentType, ProcessingStatus

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.financial_analysis_result import FinancialAnalysisResult
    from app.models.financial_period import FinancialPeriod


class FinancialDocument(Base):
    """
    Bir firmaya ve mali döneme yüklenen kaynak belge (mizan, beyanname vb.)
    ve işlenme durumu. Bkz. docs/FINOS_ARCHITECTURE_V1.md bölüm 2.2 (kaynak
    izlenebilirliği).

    Milestone 2 / Adım 1 kapsamında bu tablo yalnızca kuruluyor; henüz
    hiçbir API endpoint'i belge oluşturmuyor veya trial-balance akışına
    bağlamıyor (o kablolama sonraki adımda yapılacak).
    """

    __tablename__ = "financial_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="RESTRICT",
        ),
        # Composite FK: period_id + company_id çiftinin financial_periods
        # tablosundaki (id, company_id) unique çiftiyle eşleşmesini zorunlu
        # kılar. Bu, document.company_id'nin period.company_id ile tutarsız
        # olmasını veritabanı seviyesinde imkansız hale getirir -- servis
        # katmanına güvenilmiyor.
        ForeignKeyConstraint(
            ["period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            ondelete="RESTRICT",
            name="fk_financial_documents_period_company_consistency",
        ),
        # Milestone 2 / Adım 2: FinancialAnalysisResult'ın composite FK
        # hedefi olabilmesi için (id, company_id, period_id) üçlüsünün
        # tekil olduğunu garanti eder.
        UniqueConstraint(
            "id",
            "company_id",
            "period_id",
            name="uq_financial_documents_id_company_period",
        ),
        # Aynı dönem için aynı checksum'a sahip bir belge yalnızca bir kez
        # var olabilir (409 Conflict kararı) -- farklı dönemler/firmalar
        # için aynı checksum serbesttir.
        UniqueConstraint(
            "period_id",
            "checksum",
            name="uq_financial_documents_period_checksum",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )

    document_type: Mapped[DocumentType] = mapped_column(
        Enum(
            DocumentType,
            name="ck_financial_documents_document_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            # values_callable OLMADAN SQLAlchemy .name'i ("TRIAL_BALANCE")
            # yazar; migration'daki CHECK constraint küçük harfli .value'yu
            # ("trial_balance") bekliyor. Bkz. financial_period.py'deki
            # aynı düzeltme ve ilk migration dosyasındaki not.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)

    source_system: Mapped[str | None] = mapped_column(String(64))
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(
            ProcessingStatus,
            name="ck_financial_documents_processing_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ProcessingStatus.PENDING,
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(2000))

    company: Mapped["Company"] = relationship(
        back_populates="documents",
        foreign_keys=[company_id],
    )
    period: Mapped["FinancialPeriod"] = relationship(
        back_populates="documents",
        foreign_keys=[period_id],
    )
    analysis_results: Mapped[list["FinancialAnalysisResult"]] = relationship(
        back_populates="document",
        foreign_keys="[FinancialAnalysisResult.document_id]",
        passive_deletes=True,
    )
