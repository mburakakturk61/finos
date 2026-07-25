"""bulk upload batch and items

Revision ID: 2b6a8f4c9d31
Revises: 1f0e6d51f21b
Create Date: 2026-07-26 01:00:00.000000

Milestone 2 / Adım 3: bulk_upload_batches + bulk_upload_items. Bu iki
tablo bir "sınıflandırma önizlemesi / taslak" (classification preview /
staging) katmanıdır -- financial_documents/financial_analysis_results'a
(Milestone 2 / Adım 1-2) HİÇBİR şekilde dokunmaz, onlarla FK ilişkisi
yoktur. Hiçbir fiziksel dosya içeriği bu tablolarda saklanmaz; yalnızca
metadata + sınıflandırma tahminleri.

NOT: sa.Enum(...) CHECK constraint değer listeleri bilinçli olarak enum
.value stiliyle küçük harf yazıldı ("processing", "trial_balance",
"auto_matched" vb.) -- .name stiliyle DEĞİL. Bu,
app/models/bulk_upload_batch.py ve app/models/bulk_upload_item.py'deki
karşılık gelen sa.Enum(...) kolon tanımlarındaki
`values_callable=lambda enum_cls: [member.value for member in enum_cls]`
ayarıyla uyumlu olmak zorundadır -- bkz. 94c5e7403385'teki ilk not ve
Milestone 2 / Adım 1 sonrası düzeltilen gerçek hata.

bulk_upload_items.checksum'da KASITLI OLARAK unique constraint YOK
(yalnızca index) -- bu taslak katmanda aynı checksum'a sahip birden
fazla kayıt bir bütünlük ihlali değil, kullanıcıya sunulacak bir bulgudur
(classification_status=duplicate/possible_duplicate). Sert engelleme
(409) yalnızca onaylanmış financial_documents akışındadır.

warnings_json/detection_evidence_json: JSON().with_variant(JSONB(),
"postgresql") -- PostgreSQL'de native JSONB, başka her yerde generic
JSON.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2b6a8f4c9d31"
down_revision: Union[str, None] = "1f0e6d51f21b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bulk_upload_batches",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "processing",
                "completed",
                "failed",
                name="ck_bulk_upload_batches_status",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column("total_file_count", sa.Integer(), nullable=False),
        sa.Column("classified_file_count", sa.Integer(), nullable=False),
        sa.Column("unclassified_file_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_file_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_bulk_upload_batches"),
    )

    op.create_table(
        "bulk_upload_items",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("batch_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column(
            "detected_document_type",
            sa.Enum(
                "trial_balance",
                "corporate_tax_return",
                "temporary_tax_return",
                "balance_sheet",
                "income_statement",
                "unknown",
                name="ck_bulk_upload_items_detected_document_type",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column("detected_company_name", sa.String(length=255), nullable=True),
        sa.Column("detected_tax_number", sa.String(length=32), nullable=True),
        sa.Column("detected_year", sa.Integer(), nullable=True),
        sa.Column(
            "detected_period_type",
            sa.Enum(
                "year_end",
                "quarter",
                "temporary_tax",
                "monthly",
                "custom",
                name="ck_bulk_upload_items_detected_period_type",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=True,
        ),
        sa.Column("detected_period_number", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column(
            "classification_status",
            sa.Enum(
                "auto_matched",
                "needs_review",
                "duplicate",
                "possible_duplicate",
                "unrecognized",
                name="ck_bulk_upload_items_classification_status",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "warnings_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "detection_evidence_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["bulk_upload_batches.id"],
            name="fk_bulk_upload_items_batch_id_bulk_upload_batches",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bulk_upload_items"),
    )
    op.create_index(
        "ix_bulk_upload_items_batch_id",
        "bulk_upload_items",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_bulk_upload_items_checksum",
        "bulk_upload_items",
        ["checksum"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bulk_upload_items_checksum", table_name="bulk_upload_items")
    op.drop_index("ix_bulk_upload_items_batch_id", table_name="bulk_upload_items")
    op.drop_table("bulk_upload_items")
    op.drop_table("bulk_upload_batches")
