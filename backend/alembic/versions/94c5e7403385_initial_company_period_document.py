"""initial company period document

Revision ID: 94c5e7403385
Revises:
Create Date: 2026-07-25 00:00:00.000000

NOT: Aşağıdaki tüm sa.Enum(...) CHECK constraint değer listeleri bilinçli
olarak enum .value stiliyle küçük harf yazıldı (ör. "year_end", "draft",
"trial_balance", "pending") -- enum .name stiliyle DEĞİL (ör. "YEAR_END").
Bu, app/models/{financial_period,financial_document}.py içindeki karşılık
gelen sa.Enum(...) kolon tanımlarındaki `values_callable=lambda enum_cls:
[member.value for member in enum_cls]` ayarıyla uyumlu olmak zorundadır --
o ayar olmadan SQLAlchemy varsayılan olarak enum .name'ini yazar ve bu
CHECK constraint'lerle çakışır (bkz. Milestone 2 / Adım 1 sonrası
düzeltilen gerçek hata). Yeni bir enum-destekli kolon eklerken bu ikisini
birlikte güncelleyin.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "94c5e7403385"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- companies -----------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("trade_name", sa.String(length=255), nullable=True),
        sa.Column("tax_number", sa.String(length=32), nullable=False),
        sa.Column("tax_office", sa.String(length=255), nullable=True),
        sa.Column("sector", sa.String(length=255), nullable=True),
        sa.Column("nace_code", sa.String(length=16), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
    )
    # unique=True + index=True on the model column collapses into a single
    # unique index (SQLAlchemy behavior), not a separate unique constraint.
    op.create_index(
        "ix_companies_tax_number",
        "companies",
        ["tax_number"],
        unique=True,
    )

    # --- financial_periods ----------------------------------------------
    op.create_table(
        "financial_periods",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "period_type",
            sa.Enum(
                "year_end",
                "quarter",
                "temporary_tax",
                "monthly",
                "custom",
                name="ck_financial_periods_period_type",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("months_covered", sa.Integer(), nullable=False),
        sa.Column("is_year_end", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "active",
                "closed",
                name="ck_financial_periods_status",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_financial_periods_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_periods"),
        sa.UniqueConstraint(
            "company_id",
            "year",
            "period_type",
            "period_number",
            name="uq_financial_periods_company_year_type_number",
        ),
        # (id, company_id) çiftinin tekilliği: financial_documents
        # tarafındaki composite foreign key'in hedefi olabilmesi için gerekli.
        sa.UniqueConstraint(
            "id",
            "company_id",
            name="uq_financial_periods_id_company_id",
        ),
    )
    op.create_index(
        "ix_financial_periods_company_id",
        "financial_periods",
        ["company_id"],
        unique=False,
    )

    # --- financial_documents ---------------------------------------------
    op.create_table(
        "financial_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("period_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "document_type",
            sa.Enum(
                "trial_balance",
                "tax_declaration",
                "financial_statement",
                "other",
                name="ck_financial_documents_document_type",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=True),
        sa.Column("parser_name", sa.String(length=64), nullable=True),
        sa.Column("parser_version", sa.String(length=32), nullable=True),
        sa.Column(
            "processing_status",
            sa.Enum(
                "pending",
                "processing",
                "completed",
                "failed",
                name="ck_financial_documents_processing_status",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_financial_documents_company_id_companies",
            ondelete="RESTRICT",
        ),
        # Composite FK: period_id + company_id çiftinin financial_periods
        # tablosundaki (id, company_id) unique çiftiyle eşleşmesini zorunlu
        # kılar -- document.company_id'nin period.company_id ile
        # tutarsız olması veritabanı seviyesinde imkansız hale gelir.
        sa.ForeignKeyConstraint(
            ["period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_financial_documents_period_company_consistency",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_documents"),
    )
    op.create_index(
        "ix_financial_documents_company_id",
        "financial_documents",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_documents_period_id",
        "financial_documents",
        ["period_id"],
        unique=False,
    )


def downgrade() -> None:
    # Ters sırada: önce en bağımlı tablo.
    op.drop_index("ix_financial_documents_period_id", table_name="financial_documents")
    op.drop_index("ix_financial_documents_company_id", table_name="financial_documents")
    op.drop_table("financial_documents")

    op.drop_index("ix_financial_periods_company_id", table_name="financial_periods")
    op.drop_table("financial_periods")

    op.drop_index("ix_companies_tax_number", table_name="companies")
    op.drop_table("companies")
