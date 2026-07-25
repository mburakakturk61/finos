import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import AnalysisStatus, AnalysisType

if TYPE_CHECKING:
    from app.models.financial_document import FinancialDocument


class FinancialAnalysisResult(Base):
    """
    Bir FinancialDocument üzerinde çalıştırılan bir analiz çalışmasının
    sonucu ve durumu (Milestone 2 / Adım 2). Bilinçli olarak FinancialDocument
    üzerine gömülü bir JSON kolonu DEĞİL, ayrı bir tablo -- aynı belge
    üzerinde ileride birden fazla analiz çalışması (ör. motor güncellemesi
    sonrası yeniden analiz) versiyonlanabilir biçimde saklanabilsin diye.

    company_id/period_id, document_id ile birlikte composite foreign key
    içinde tutulur -- document.company_id/period_id ile TUTARSIZ bir
    (company_id, period_id, document_id) üçlüsü veritabanı seviyesinde
    imkansızdır (bkz. __table_args__). Company/FinancialPeriod'a ayrıca
    doğrudan foreign key YOK -- tutarlılık zaten financial_documents
    üzerinden zincirleme garanti ediliyor, tek doğruluk kaynağı korunuyor.
    """

    __tablename__ = "financial_analysis_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "company_id", "period_id"],
            [
                "financial_documents.id",
                "financial_documents.company_id",
                "financial_documents.period_id",
            ],
            name="fk_financial_analysis_results_document_consistency",
            ondelete="RESTRICT",
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
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )

    analysis_type: Mapped[AnalysisType] = mapped_column(
        Enum(
            AnalysisType,
            name="ck_financial_analysis_results_analysis_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(
            AnalysisStatus,
            name="ck_financial_analysis_results_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    # PostgreSQL'de native JSONB, başka her dialect'te (ör. SQLite testleri)
    # generic JSON -- fallback'e güvenmek yerine SQLAlchemy'nin resmi
    # with_variant mekanizmasıyla açıkça belirtiliyor.
    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(String(2000))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped["FinancialDocument"] = relationship(
        back_populates="analysis_results",
        foreign_keys=[document_id],
    )
