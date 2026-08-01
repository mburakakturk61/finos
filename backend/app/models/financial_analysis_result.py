import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import AnalysisStatus, AnalysisType, SourceMode

if TYPE_CHECKING:
    from app.models.financial_document import FinancialDocument


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


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
    imkansızdır (bkz. __table_args__).

    Milestone 4.1 (Analysis Foundation): document_id artık NULLABLE --
    dönem-seviyeli, çoklu-kaynaklı motorlar (ör. Financial Ratio Engine,
    Milestone 4.3; Cash Flow Engine'in derived modu, Milestone 4.4) tek bir
    belgeye zincirlenemez. Bu durumda company_id/period_id'nin GEÇERLİ ve
    TUTARLI bir çift olduğu artık document_id'nin varlığına değil, HER ZAMAN
    devrede olan fk_financial_analysis_results_period_company'ye (doğrudan
    financial_periods'a) bağlıdır -- Company/FinancialPeriod'a "asla
    doğrudan FK yok" kuralı bu adımda BİLİNÇLİ OLARAK gevşetildi, çünkü
    document_id artık her zaman bir tutarlılık zinciri sağlamıyor.

    source_mode alanı bu sonucun ESAS OLARAK hangi kaynaktan üretildiğini
    (bkz. app.models.enums.SourceMode) açıkça kaydeder;
    ck_financial_analysis_results_direct_requires_document, source_mode=
    direct_document iken document_id'nin NULL olamayacağını DB seviyesinde
    zorlar. Bir sonucun katkı sağlayan TÜM kaynakları (tek bir document_id
    ile ifade edilemeyen durumlar dahil) financial_analysis_result_sources
    tablosunda ayrıca, DB seviyesinde zorlanan biçimde tutulur -- kaynak
    izlenebilirliği yalnızca result_json'a bırakılmaz.
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
        # Milestone 4.1: document_id NULL olabildiği için, company_id/period_id
        # çiftinin geçerliliği artık BU FK ile, document_id'den bağımsız
        # olarak HER SATIRDA garanti edilir (yukarıdaki composite FK, Postgres
        # MATCH SIMPLE semantiği gereği document_id NULL iken devre dışı kalır).
        ForeignKeyConstraint(
            ["period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_financial_analysis_results_period_company",
            ondelete="RESTRICT",
        ),
        # financial_analysis_result_sources'ın source_analysis_result_id
        # composite FK'sinin hedefi olabilmesi için gerekli.
        UniqueConstraint(
            "id",
            "company_id",
            "period_id",
            name="uq_financial_analysis_results_id_company_period",
        ),
        # source_mode=direct_document iken document_id NULL OLAMAZ (onaylanan
        # Milestone 4.1 kararı #3). Diğer iki source_mode değeri için
        # document_id'nin dolu ya da boş olması serbesttir.
        CheckConstraint(
            "(source_mode <> 'direct_document') OR (document_id IS NOT NULL)",
            name="ck_financial_analysis_results_direct_requires_document",
        ),
        CheckConstraint(
            "(canonical_result_digest IS NULL OR (" + _sha256_check("canonical_result_digest") + ")) AND "
            "(status <> 'completed' OR result_json IS NULL OR canonical_result_digest IS NOT NULL)",
            name="ck_financial_analysis_results_canonical_digest",
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
    # Milestone 4.1: NOT NULL -> NULLABLE (bkz. sınıf docstring'i). Mevcut
    # trial_balance kayıtları için migration bu kolonu DOLU bırakır --
    # yalnızca YENİ, dönem-seviyeli (source_mode != direct_document) sonuçlar
    # NULL document_id ile yazılabilir.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )

    # Milestone 4.1: bu sonucun ESAS OLARAK hangi kaynaktan üretildiği (bkz.
    # app.models.enums.SourceMode). Geçici server_default ile eklenip (mevcut
    # trial_balance satırları için) düşürülür -- Milestone 3'teki
    # user_decision deseniyle aynı (bkz. migration).
    source_mode: Mapped[SourceMode] = mapped_column(
        Enum(
            SourceMode,
            name="ck_financial_analysis_results_source_mode",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=SourceMode.DIRECT_DOCUMENT,
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
    canonical_result_digest: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(2000))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Milestone 4.1: document_id NULLABLE olduğu için ilişki de artık
    # opsiyonel -- dönem-seviyeli (document_id IS NULL) sonuçlarda bu alan
    # None döner.
    document: Mapped["FinancialDocument | None"] = relationship(
        back_populates="analysis_results",
        foreign_keys=[document_id],
    )


@event.listens_for(FinancialAnalysisResult, "before_insert")
@event.listens_for(FinancialAnalysisResult, "before_update")
def _set_canonical_result_digest(_mapper, _connection, target: FinancialAnalysisResult) -> None:
    """Keep ORM writers compatible while the database remains authoritative."""
    if target.status is AnalysisStatus.COMPLETED and target.result_json is not None:
        import hashlib

        from app.orchestration_persistence.codec import canonical_json_bytes

        target.canonical_result_digest = hashlib.sha256(
            canonical_json_bytes(target.result_json)
        ).hexdigest()
