import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import PeriodCoverageKind, PeriodStatus, PeriodType

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.financial_document import FinancialDocument


class FinancialPeriod(Base):
    """
    Bir firmanın mali analiz dönemi. Bkz. docs/FINOS_ARCHITECTURE_V1.md
    bölüm 4.2.
    """

    __tablename__ = "financial_periods"
    __table_args__ = (
        # Aynı firma için aynı (yıl, dönem tipi, dönem no) kombinasyonu
        # yalnızca bir kez var olabilir -- yinelenen dönem girişini engeller.
        UniqueConstraint(
            "company_id",
            "year",
            "period_type",
            "period_number",
            name="uq_financial_periods_company_year_type_number",
        ),
        # FinancialDocument tarafındaki composite foreign key'in hedefi
        # olabilmesi için gerekli: (id, company_id) çiftinin tekil olduğunu
        # garanti eder ve document.company_id == period.company_id kuralının
        # veritabanı seviyesinde uygulanmasını sağlar.
        UniqueConstraint(
            "id",
            "company_id",
            name="uq_financial_periods_id_company_id",
        ),
        CheckConstraint(
            "(accounting_basis_code IS NULL AND accounting_policy_version IS NULL "
            "AND annual_reporting_period_start_date IS NULL "
            "AND annual_reporting_period_end_date IS NULL "
            "AND ifrs18_early_adopted IS NULL AND cash_flow_coverage_kind IS NULL) OR "
            "(accounting_basis_code IS NOT NULL AND accounting_policy_version IS NOT NULL "
            "AND annual_reporting_period_start_date IS NOT NULL "
            "AND annual_reporting_period_end_date IS NOT NULL "
            "AND ifrs18_early_adopted IS NOT NULL AND cash_flow_coverage_kind IS NOT NULL)",
            name=conv("ck_financial_periods_cf_policy_all_null_or_set"),
        ),
        CheckConstraint(
            "accounting_basis_code IS NULL OR "
            "(accounting_basis_code = 'tr_tdhp_accrual' "
            "AND accounting_policy_version = 'tr_tdhp_accrual/1.0.0')",
            name=conv("ck_financial_periods_cf_supported_basis_policy"),
        ),
        CheckConstraint(
            "annual_reporting_period_start_date IS NULL OR "
            "(annual_reporting_period_start_date <= start_date "
            "AND start_date <= end_date "
            "AND end_date <= annual_reporting_period_end_date)",
            name=conv("ck_financial_periods_cf_annual_containment"),
        ),
        CheckConstraint(
            "cash_flow_coverage_kind IS NULL OR "
            "(period_type = 'year_end' AND cash_flow_coverage_kind = 'cumulative') OR "
            "(period_type = 'monthly' AND cash_flow_coverage_kind = 'discrete') OR "
            "(period_type = 'temporary_tax' AND cash_flow_coverage_kind = 'cumulative') OR "
            "period_type IN ('quarter', 'custom')",
            name=conv("ck_financial_periods_cf_coverage_kind"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False)

    period_type: Mapped[PeriodType] = mapped_column(
        Enum(
            PeriodType,
            # Açık, tam nitelikli isim -- SQLAlchemy'nin Enum/CheckConstraint
            # + naming-convention etkileşimindeki belirsizliğe güvenmemek için
            # (bkz. ilk migration dosyasındaki not).
            name="ck_financial_periods_period_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            # values_callable OLMADAN SQLAlchemy, enum üyesinin .value'su
            # yerine .name'ini (ör. "YEAR_END") veritabanına yazar. Bu,
            # migration'daki CHECK constraint'in beklediği küçük harfli
            # .value ("year_end") ile uyuşmaz ve her INSERT'te constraint
            # ihlaline yol açar. .value'nun yazılmasını garanti eder.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    months_covered: Mapped[int] = mapped_column(Integer, nullable=False)
    is_year_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[PeriodStatus] = mapped_column(
        Enum(
            PeriodStatus,
            name="ck_financial_periods_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=PeriodStatus.DRAFT,
    )

    accounting_basis_code: Mapped[str | None] = mapped_column(String(32))
    accounting_policy_version: Mapped[str | None] = mapped_column(String(64))
    annual_reporting_period_start_date: Mapped[date | None] = mapped_column(Date)
    annual_reporting_period_end_date: Mapped[date | None] = mapped_column(Date)
    ifrs18_early_adopted: Mapped[bool | None] = mapped_column(Boolean)
    cash_flow_coverage_kind: Mapped[PeriodCoverageKind | None] = mapped_column(
        Enum(
            PeriodCoverageKind,
            name=conv("ck_financial_periods_cash_flow_coverage_kind"),
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )

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

    company: Mapped["Company"] = relationship(
        back_populates="periods",
        foreign_keys=[company_id],
    )
    documents: Mapped[list["FinancialDocument"]] = relationship(
        back_populates="period",
        foreign_keys="[FinancialDocument.period_id]",
        passive_deletes=True,
    )
