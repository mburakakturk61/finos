"""bulk upload confirmation

Revision ID: 9d4f1a7c6e52
Revises: 2b6a8f4c9d31
Create Date: 2026-07-26 02:00:00.000000

Milestone 3 / Adım 1: bulk upload staging'i kullanıcı onayına (confirm)
bağlayan alanlar.

  * bulk_upload_batches.status CHECK constraint'i "confirmed" değerini
    içerecek şekilde genişletilir (native_enum=False olduğu için
    ALTER TYPE değil, drop+recreate CHECK). bulk_upload_batches.confirmed_at
    eklenir.
  * bulk_upload_items.user_decision (yeni, ayrı CHECK) -- classification_status
    (motor çıktısı) ile KARIŞTIRILMAMALI, kullanıcının insan kararıdır.
    Mevcut satırlar için (varsa) 'pending' server_default'u ile eklenir,
    ardından server_default kaldırılır -- ORM tarafındaki Python-seviyeli
    default ile aynı davranışa dönülür (bkz. app/models/bulk_upload_item.py).
  * bulk_upload_items.resolution_json (JSON/JSONB, nullable) -- kullanıcının
    önerdiği/düzenlediği firma-dönem-tür taslağı, yalnızca uygulama
    katmanında doğrulanır.
  * bulk_upload_items.resulting_company_id/resulting_period_id/
    resulting_document_id/resulting_analysis_id (nullable, RESTRICT FK) --
    yalnızca confirm başarılı olduktan sonra dolan audit izi.

NOT: Bu dört FK için constraint adları BİLEREK naming convention'ın
varsayılan üretiminden (fk_bulk_upload_items_resulting_<kolon>_<referans
tablo>) SAPAR -- "financial_analysis_results" gibi uzun referans tablo
adlarıyla PostgreSQL'in 63 karakter identifier sınırını AŞIYORDU (69
karaktere çıkıyordu, ilk denemede `alembic upgrade head` bu yüzden
başarısız oldu). Dördü de -- yalnızca sınırı aşan değil -- tutarlılık
için aynı kısaltılmış "fk_bulk_upload_items_resulting_<hedef>" kalıbını
kullanır (bkz. app/models/bulk_upload_item.py'deki ForeignKey(name=...)
eşleşen açık isimlendirme).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9d4f1a7c6e52"
down_revision: Union[str, None] = "2b6a8f4c9d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- bulk_upload_batches ---
    op.drop_constraint(
        "ck_bulk_upload_batches_status",
        "bulk_upload_batches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_bulk_upload_batches_status",
        "bulk_upload_batches",
        "status IN ('processing', 'completed', 'failed', 'confirmed')",
    )
    op.add_column(
        "bulk_upload_batches",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- bulk_upload_items ---
    op.add_column(
        "bulk_upload_items",
        sa.Column(
            "user_decision",
            sa.Enum(
                "pending",
                "accepted",
                "ignored",
                name="ck_bulk_upload_items_user_decision",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
            server_default="pending",
        ),
    )
    op.alter_column(
        "bulk_upload_items",
        "user_decision",
        server_default=None,
    )

    op.add_column(
        "bulk_upload_items",
        sa.Column(
            "resolution_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )

    op.add_column(
        "bulk_upload_items",
        sa.Column("resulting_company_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bulk_upload_items",
        sa.Column("resulting_period_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bulk_upload_items",
        sa.Column("resulting_document_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bulk_upload_items",
        sa.Column("resulting_analysis_id", sa.Uuid(as_uuid=True), nullable=True),
    )

    op.create_foreign_key(
        "fk_bulk_upload_items_resulting_company",
        "bulk_upload_items",
        "companies",
        ["resulting_company_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bulk_upload_items_resulting_period",
        "bulk_upload_items",
        "financial_periods",
        ["resulting_period_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bulk_upload_items_resulting_document",
        "bulk_upload_items",
        "financial_documents",
        ["resulting_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bulk_upload_items_resulting_analysis",
        "bulk_upload_items",
        "financial_analysis_results",
        ["resulting_analysis_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index(
        "ix_bulk_upload_items_resulting_company_id",
        "bulk_upload_items",
        ["resulting_company_id"],
        unique=False,
    )
    op.create_index(
        "ix_bulk_upload_items_resulting_period_id",
        "bulk_upload_items",
        ["resulting_period_id"],
        unique=False,
    )
    op.create_index(
        "ix_bulk_upload_items_resulting_document_id",
        "bulk_upload_items",
        ["resulting_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_bulk_upload_items_resulting_analysis_id",
        "bulk_upload_items",
        ["resulting_analysis_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bulk_upload_items_resulting_analysis_id",
        table_name="bulk_upload_items",
    )
    op.drop_index(
        "ix_bulk_upload_items_resulting_document_id",
        table_name="bulk_upload_items",
    )
    op.drop_index(
        "ix_bulk_upload_items_resulting_period_id",
        table_name="bulk_upload_items",
    )
    op.drop_index(
        "ix_bulk_upload_items_resulting_company_id",
        table_name="bulk_upload_items",
    )

    op.drop_constraint(
        "fk_bulk_upload_items_resulting_analysis",
        "bulk_upload_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bulk_upload_items_resulting_document",
        "bulk_upload_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bulk_upload_items_resulting_period",
        "bulk_upload_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bulk_upload_items_resulting_company",
        "bulk_upload_items",
        type_="foreignkey",
    )

    op.drop_column("bulk_upload_items", "resulting_analysis_id")
    op.drop_column("bulk_upload_items", "resulting_document_id")
    op.drop_column("bulk_upload_items", "resulting_period_id")
    op.drop_column("bulk_upload_items", "resulting_company_id")
    op.drop_column("bulk_upload_items", "resolution_json")
    op.drop_column("bulk_upload_items", "user_decision")

    op.drop_column("bulk_upload_batches", "confirmed_at")
    op.drop_constraint(
        "ck_bulk_upload_batches_status",
        "bulk_upload_batches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_bulk_upload_batches_status",
        "bulk_upload_batches",
        "status IN ('processing', 'completed', 'failed')",
    )
