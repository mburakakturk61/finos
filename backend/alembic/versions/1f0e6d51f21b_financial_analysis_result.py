"""financial analysis result

Revision ID: 1f0e6d51f21b
Revises: 94c5e7403385
Create Date: 2026-07-26 00:00:00.000000

NOT: sa.Enum(...) CHECK constraint değer listeleri bilinçli olarak enum
.value stiliyle küçük harf yazıldı (ör. "trial_balance", "pending") --
.name stiliyle DEĞİL. Bu, app/models/financial_analysis_result.py'deki
karşılık gelen sa.Enum(...) kolon tanımlarındaki `values_callable=lambda
enum_cls: [member.value for member in enum_cls]` ayarıyla uyumlu olmak
zorundadır -- bkz. ilk migration dosyasındaki (94c5e7403385) aynı not ve
Milestone 2 / Adım 1 sonrası düzeltilen gerçek hata.

result_json kolonu JSON().with_variant(JSONB(), "postgresql") kullanır:
PostgreSQL'de native JSONB, başka her yerde generic JSON.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "1f0e6d51f21b"
down_revision: Union[str, None] = "94c5e7403385"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- financial_documents: Milestone 2 / Adım 2 için yeni constraint'ler ---
    # FinancialAnalysisResult'ın composite FK hedefi olabilmesi için gerekli:
    # (id, company_id, period_id) üçlüsünün tekil olduğunu garanti eder.
    op.create_unique_constraint(
        "uq_financial_documents_id_company_period",
        "financial_documents",
        ["id", "company_id", "period_id"],
    )
    # Aynı dönem için aynı checksum'a sahip bir belge yalnızca bir kez var
    # olabilir (409 Conflict kararı) -- farklı dönemler/firmalar için aynı
    # checksum serbesttir.
    op.create_unique_constraint(
        "uq_financial_documents_period_checksum",
        "financial_documents",
        ["period_id", "checksum"],
    )

    # --- financial_analysis_results ---
    op.create_table(
        "financial_analysis_results",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("period_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "analysis_type",
            sa.Enum(
                "trial_balance",
                name="ck_financial_analysis_results_analysis_type",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "completed",
                "failed",
                name="ck_financial_analysis_results_status",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "result_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "company_id", "period_id"],
            [
                "financial_documents.id",
                "financial_documents.company_id",
                "financial_documents.period_id",
            ],
            name="fk_financial_analysis_results_document_consistency",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_analysis_results"),
    )
    op.create_index(
        "ix_financial_analysis_results_company_id",
        "financial_analysis_results",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_analysis_results_period_id",
        "financial_analysis_results",
        ["period_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_analysis_results_document_id",
        "financial_analysis_results",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_financial_analysis_results_document_id",
        table_name="financial_analysis_results",
    )
    op.drop_index(
        "ix_financial_analysis_results_period_id",
        table_name="financial_analysis_results",
    )
    op.drop_index(
        "ix_financial_analysis_results_company_id",
        table_name="financial_analysis_results",
    )
    op.drop_table("financial_analysis_results")

    op.drop_constraint(
        "uq_financial_documents_period_checksum",
        "financial_documents",
        type_="unique",
    )
    op.drop_constraint(
        "uq_financial_documents_id_company_period",
        "financial_documents",
        type_="unique",
    )
