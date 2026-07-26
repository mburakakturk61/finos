import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import AnalysisSourceRole


class FinancialAnalysisResultSource(Base):
    """
    Milestone 4.1 (Analysis Foundation): bir FinancialAnalysisResult'ın hangi
    belge(ler)den ve/veya hangi başka analiz sonucundan (sonuçlarından)
    beslendiğinin DB seviyesinde zorlanan izi. Dönem-seviyeli, çoklu-kaynaklı
    motorlar (ör. Financial Ratio Engine -- Milestone 4.3; Cash Flow
    Engine'in derived modu -- Milestone 4.4) tek bir document_id'ye
    zincirlenemez; bu tablo o durumda kaynak izlenebilirliğini
    (docs/FINOS_ARCHITECTURE_V1.md bölüm 2.2) korur -- izlenebilirlik
    yalnızca result_json içine bırakılmaz.

    Her satır TAM OLARAK BİR kaynak gösterir: source_document_id XOR
    source_analysis_result_id (bkz. ck_..._xor_source). Bir analiz sonucu
    kendi kendisini kaynak gösteremez (bkz. ck_..._no_self_ref). role
    (AnalysisSourceRole) ile kaynak türü arasındaki eşleşme de DB
    seviyesinde zorlanır (bkz. ck_..._role_source_match):
      - primary_document / supporting_document -> yalnızca source_document_id
      - primary_analysis / supporting_analysis / trial_balance_fallback ->
        yalnızca source_analysis_result_id
      - prior_period_reference -> her iki kaynak türüyle de kullanılabilir

    company_id/period_id BİLİNÇLİ OLARAK denormalize edilmiştir -- yalnızca
    bu sayede hem üst analiz sonucunun hem de kaynağın (belge veya başka
    analiz sonucu) AYNI company/period'a ait olduğu, servis katmanına
    güvenilmeden, doğrudan composite foreign key ile garanti edilebiliyor
    (bkz. üç ForeignKeyConstraint) -- "mümkün olan en güçlü DB garantisi"
    isteğinin karşılığı budur.

    BİLİNÇLİ TASARIM KARARI -- relationship() TANIMLANMADI: financial_
    analysis_results tablosuna İKİ farklı composite FK yolu var (üst analiz
    sonucu + source_analysis_result_id) ve company_id/period_id her ikisinde
    de ORTAK. SQLAlchemy'nin bu iki yolu relationship() foreign_keys/
    primaryjoin ile güvenilir biçimde ayırt edip edemeyeceği bu ortamda
    (sqlalchemy kurulu değil, gerçek çalıştırılarak doğrulanamıyor)
    doğrulanamadı. Yanlış yapılandırılmış ama "çalışıyormuş gibi görünen"
    bir relationship, hiç relationship olmamasından daha risklidir. Bu,
    mevcut kod tabanındaki emsalle de tutarlı: BulkUploadItem.resulting_*_id
    kolonları da (Milestone 3) relationship() TANIMLAMAZ, düz UUID + FK
    olarak kalır ve gerektiğinde açık select() sorgusuyla okunur. Aynı desen
    burada da izlendi -- ileride gerçekten sqlalchemy kurulu bir ortamda
    doğrulanıp eklenebilir.
    """

    __tablename__ = "financial_analysis_result_sources"
    __table_args__ = (
        # Üst analiz sonucu -- HER ZAMAN zorunlu. Bu satırın ait olduğu
        # FinancialAnalysisResult gerçek ve aynı company/period'a mı ait?
        ForeignKeyConstraint(
            ["analysis_result_id", "company_id", "period_id"],
            [
                "financial_analysis_results.id",
                "financial_analysis_results.company_id",
                "financial_analysis_results.period_id",
            ],
            name="fk_financial_analysis_result_sources_parent",
            ondelete="RESTRICT",
        ),
        # Kaynak belge -- yalnızca source_document_id doluyken (Postgres
        # MATCH SIMPLE semantiği gereği NULL iken devre dışı). Kaynak belge
        # aynı company/period'a mı ait?
        ForeignKeyConstraint(
            ["source_document_id", "company_id", "period_id"],
            [
                "financial_documents.id",
                "financial_documents.company_id",
                "financial_documents.period_id",
            ],
            name="fk_financial_analysis_result_sources_document",
            ondelete="RESTRICT",
        ),
        # Kaynak analiz sonucu -- yalnızca source_analysis_result_id
        # doluyken. Kaynak analiz sonucu aynı company/period'a mı ait?
        ForeignKeyConstraint(
            ["source_analysis_result_id", "company_id", "period_id"],
            [
                "financial_analysis_results.id",
                "financial_analysis_results.company_id",
                "financial_analysis_results.period_id",
            ],
            name="fk_financial_analysis_result_sources_analysis",
            ondelete="RESTRICT",
        ),
        # Aynı belge, aynı analiz sonucuna iki kez kaynak olarak eklenemez.
        UniqueConstraint(
            "analysis_result_id",
            "source_document_id",
            name="uq_financial_analysis_result_sources_by_document",
        ),
        # Aynı analiz sonucu, aynı üst analiz sonucuna iki kez kaynak olarak
        # eklenemez.
        UniqueConstraint(
            "analysis_result_id",
            "source_analysis_result_id",
            name="uq_financial_analysis_result_sources_by_analysis",
        ),
        # Tam olarak bir kaynak türü dolu olmalı -- ikisi birden dolu ya da
        # ikisi birden boş olan satır reddedilir.
        CheckConstraint(
            "(source_document_id IS NOT NULL) <> (source_analysis_result_id IS NOT NULL)",
            name="ck_financial_analysis_result_sources_xor_source",
        ),
        # Bir analiz sonucu kendi kendisini kaynak gösteremez (onaylanan
        # Milestone 4.1 kararı #4).
        CheckConstraint(
            "source_analysis_result_id IS NULL OR source_analysis_result_id <> analysis_result_id",
            name="ck_financial_analysis_result_sources_no_self_ref",
        ),
        # role <-> kaynak türü eşleşmesi (onaylanan Milestone 4.1 kararı #2).
        # prior_period_reference için kasıtlı olarak hiçbir kısıt yok -- her
        # iki kaynak türüyle de kullanılabilir.
        CheckConstraint(
            "(role NOT IN ('primary_document', 'supporting_document')"
            " OR source_document_id IS NOT NULL)"
            " AND (role NOT IN ('primary_analysis', 'supporting_analysis', 'trial_balance_fallback')"
            " OR source_analysis_result_id IS NOT NULL)",
            name="ck_financial_analysis_result_sources_role_source_match",
        ),
        # Dönem bazlı toplu sorgular için (ör. "bu dönemin tüm kaynak
        # katkılarını getir") -- tekil kolon indeksleri (index=True, aşağıda)
        # bu composite erişim deseni için yeterli değil.
        Index(
            "ix_financial_analysis_result_sources_company_period",
            "company_id",
            "period_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    analysis_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
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

    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        index=True,
    )
    source_analysis_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        index=True,
    )

    role: Mapped[AnalysisSourceRole] = mapped_column(
        Enum(
            AnalysisSourceRole,
            name="ck_financial_analysis_result_sources_role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
