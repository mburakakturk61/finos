"""analysis foundation

Revision ID: 3a7c2e9f5b14
Revises: 9d4f1a7c6e52
Create Date: 2026-07-26 12:00:00.000000

Milestone 4.1 (Analysis Foundation): Milestone 4'ün (Financial Statement
Intelligence Engine) altyapı adımı. Bu migration YALNIZCA şema hazırlığı
yapar -- hiçbir yeni motor (Balance Sheet/Income Statement/Cash Flow/Tax
Return/Financial Ratio) implemente edilmedi, app/trial_balance/**'e ve
mevcut bulk upload/trial balance upload dispatch akışlarına dokunulmadı.

Değişiklikler:

  1. Enum CHECK genişletmeleri (native_enum=False olduğu için ALTER TYPE
     değil, mevcut desenle aynı drop+recreate CHECK):
       - financial_documents.document_type: +balance_sheet,
         +income_statement, +cash_flow_statement, +corporate_tax_return,
         +temporary_tax_return (eski tax_declaration/financial_statement
         SİLİNMEDİ, geriye dönük uyumluluk için korunuyor).
       - financial_analysis_results.analysis_type: +balance_sheet,
         +income_statement, +cash_flow, +tax_return, +financial_ratios.
       - bulk_upload_items.detected_document_type: +cash_flow_statement.

  2. financial_analysis_results:
       - document_id: NOT NULL -> NULLABLE. Dönem-seviyeli, çoklu-kaynaklı
         motorlar (Financial Ratio -- Milestone 4.3; Cash Flow'un derived
         modu -- Milestone 4.4) tek bir belgeye zincirlenemez.
       - YENİ source_mode kolonu (SourceMode enum, NOT NULL). Mevcut
         satırlar (hepsi bugüne kadar yalnızca trial_balace) için geçici
         server_default='direct_document' ile eklenir (gerçeğe uygun --
         hepsi doğrudan yüklenen dosyadan üretildi), sonra server_default
         kaldırılır (Milestone 3'teki user_decision deseniyle aynı).
       - YENİ fk_financial_analysis_results_period_company: (period_id,
         company_id) -> financial_periods (id, company_id), RESTRICT. HER
         ZAMAN devrede (document_id'den bağımsız) -- document_id NULL
         olduğunda company_id/period_id'nin geçerli bir çift olduğunu
         garanti eden TEK mekanizma budur (eski composite FK, Postgres
         MATCH SIMPLE semantiği gereği document_id NULL iken devre dışı
         kalır).
       - YENİ uq_financial_analysis_results_id_company_period: UNIQUE
         (id, company_id, period_id) -- yeni financial_analysis_result_
         sources tablosunun source_analysis_result_id composite FK'sinin
         hedefi olabilmesi için.
       - YENİ ck_financial_analysis_results_direct_requires_document:
         source_mode='direct_document' iken document_id NULL OLAMAZ
         (onaylanan Milestone 4.1 kararı #3).

  3. YENİ tablo financial_analysis_result_sources: bir analiz sonucunun
     hangi belge(ler)den ve/veya hangi başka analiz sonucundan (sonuçlarından)
     beslendiğinin DB seviyesinde zorlanan izi (onaylanan Milestone 4.1
     kararı #2-#4). company_id/period_id BİLİNÇLİ OLARAK denormalize --
     üç composite FK (parent/document/analysis) bu iki kolon üzerinden
     "kaynak, üst analiz sonucuyla AYNI company/period'a ait olmalı"
     garantisini doğrudan Postgres'e devrediyor. XOR CHECK (tam olarak bir
     kaynak türü), self-reference CHECK (bir sonuç kendini kaynak
     gösteremez) ve role<->kaynak-türü eşleşme CHECK'i de dahil.

NOT (PostgreSQL 63 karakter identifier sınırı): bu migration'daki TÜM yeni
constraint/index adları açıkça (name=...) verildi ve commit öncesi
programatik olarak ölçüldü -- en uzunu 55 karakter
(ix_financial_analysis_result_sources_analysis_result_id). Özellikle iki
UNIQUE constraint'in (by_document / by_analysis) varsayılan naming
convention'a bırakılması ÇAKIŞIRDI -- ikisinin de column_0_name'i
analysis_result_id olduğu için '9d4f1a7c6e52'deki 69-karakter dersiyle
aynı kategoriden bir tuzak.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3a7c2e9f5b14"
down_revision: Union[str, None] = "9d4f1a7c6e52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Enum CHECK genisletmeleri ---

    op.drop_constraint(
        "ck_financial_documents_document_type",
        "financial_documents",
        type_="check",
    )
    op.create_check_constraint(
        "ck_financial_documents_document_type",
        "financial_documents",
        "document_type IN ("
        "'trial_balance', 'tax_declaration', 'financial_statement', 'other', "
        "'balance_sheet', 'income_statement', 'cash_flow_statement', "
        "'corporate_tax_return', 'temporary_tax_return'"
        ")",
    )

    op.drop_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        "analysis_type IN ("
        "'trial_balance', 'balance_sheet', 'income_statement', 'cash_flow', "
        "'tax_return', 'financial_ratios'"
        ")",
    )

    op.drop_constraint(
        "ck_bulk_upload_items_detected_document_type",
        "bulk_upload_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_bulk_upload_items_detected_document_type",
        "bulk_upload_items",
        "detected_document_type IN ("
        "'trial_balance', 'corporate_tax_return', 'temporary_tax_return', "
        "'balance_sheet', 'income_statement', 'cash_flow_statement', 'unknown'"
        ")",
    )

    # --- 2. financial_analysis_results ---

    op.alter_column(
        "financial_analysis_results",
        "document_id",
        nullable=True,
    )

    op.add_column(
        "financial_analysis_results",
        sa.Column(
            "source_mode",
            sa.Enum(
                "direct_document",
                "trial_balance_derived",
                "multi_source_derived",
                name="ck_financial_analysis_results_source_mode",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
            server_default="direct_document",
        ),
    )
    op.alter_column(
        "financial_analysis_results",
        "source_mode",
        server_default=None,
    )

    op.create_foreign_key(
        "fk_financial_analysis_results_period_company",
        "financial_analysis_results",
        "financial_periods",
        ["period_id", "company_id"],
        ["id", "company_id"],
        ondelete="RESTRICT",
    )

    op.create_unique_constraint(
        "uq_financial_analysis_results_id_company_period",
        "financial_analysis_results",
        ["id", "company_id", "period_id"],
    )

    op.create_check_constraint(
        "ck_financial_analysis_results_direct_requires_document",
        "financial_analysis_results",
        "(source_mode <> 'direct_document') OR (document_id IS NOT NULL)",
    )

    # --- 3. YENI tablo: financial_analysis_result_sources ---

    op.create_table(
        "financial_analysis_result_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("analysis_result_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("period_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_analysis_result_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "primary_document",
                "primary_analysis",
                "trial_balance_fallback",
                "prior_period_reference",
                "supporting_document",
                "supporting_analysis",
                name="ck_financial_analysis_result_sources_role",
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_result_id", "company_id", "period_id"],
            [
                "financial_analysis_results.id",
                "financial_analysis_results.company_id",
                "financial_analysis_results.period_id",
            ],
            name="fk_financial_analysis_result_sources_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id", "company_id", "period_id"],
            [
                "financial_documents.id",
                "financial_documents.company_id",
                "financial_documents.period_id",
            ],
            name="fk_financial_analysis_result_sources_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_analysis_result_id", "company_id", "period_id"],
            [
                "financial_analysis_results.id",
                "financial_analysis_results.company_id",
                "financial_analysis_results.period_id",
            ],
            name="fk_financial_analysis_result_sources_analysis",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "analysis_result_id",
            "source_document_id",
            name="uq_financial_analysis_result_sources_by_document",
        ),
        sa.UniqueConstraint(
            "analysis_result_id",
            "source_analysis_result_id",
            name="uq_financial_analysis_result_sources_by_analysis",
        ),
        sa.CheckConstraint(
            "(source_document_id IS NOT NULL) <> (source_analysis_result_id IS NOT NULL)",
            name="ck_financial_analysis_result_sources_xor_source",
        ),
        sa.CheckConstraint(
            "source_analysis_result_id IS NULL OR source_analysis_result_id <> analysis_result_id",
            name="ck_financial_analysis_result_sources_no_self_ref",
        ),
        sa.CheckConstraint(
            "(role NOT IN ('primary_document', 'supporting_document')"
            " OR source_document_id IS NOT NULL)"
            " AND (role NOT IN ('primary_analysis', 'supporting_analysis', 'trial_balance_fallback')"
            " OR source_analysis_result_id IS NOT NULL)",
            name="ck_financial_analysis_result_sources_role_source_match",
        ),
    )

    op.create_index(
        "ix_financial_analysis_result_sources_analysis_result_id",
        "financial_analysis_result_sources",
        ["analysis_result_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_analysis_result_sources_company_id",
        "financial_analysis_result_sources",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_analysis_result_sources_period_id",
        "financial_analysis_result_sources",
        ["period_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_analysis_result_sources_source_document_id",
        "financial_analysis_result_sources",
        ["source_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_analysis_result_sources_source_analysis_id",
        "financial_analysis_result_sources",
        ["source_analysis_result_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_analysis_result_sources_company_period",
        "financial_analysis_result_sources",
        ["company_id", "period_id"],
        unique=False,
    )


def downgrade() -> None:
    # --- 3'ün tersi: yeni tabloyu sil (DROP TABLE, tabloya bagli tum
    # index/constraint'leri otomatik olarak birlikte kaldirir) ---

    op.drop_table("financial_analysis_result_sources")

    # --- 2'nin tersi ---

    op.drop_constraint(
        "ck_financial_analysis_results_direct_requires_document",
        "financial_analysis_results",
        type_="check",
    )
    op.drop_constraint(
        "uq_financial_analysis_results_id_company_period",
        "financial_analysis_results",
        type_="unique",
    )
    op.drop_constraint(
        "fk_financial_analysis_results_period_company",
        "financial_analysis_results",
        type_="foreignkey",
    )
    op.drop_column("financial_analysis_results", "source_mode")

    # NOT: eger upgrade sonrasi gercekten document_id IS NULL olan satirlar
    # yazildiysa (Milestone 4.1 sonrasi, source_mode != direct_document ile),
    # bu adim NOT NULL ihlali nedeniyle basarisiz olur -- bu, "yeni veriyle
    # downgrade" durumunun beklenen/normal sinirlamasidir, Milestone 4.1'in
    # kendisiyle ilgili bir kusur degildir.
    op.alter_column(
        "financial_analysis_results",
        "document_id",
        nullable=False,
    )

    # --- 1'in tersi: enum CHECK'leri orijinal (Milestone 3 sonu) haline
    # dondur ---

    op.drop_constraint(
        "ck_bulk_upload_items_detected_document_type",
        "bulk_upload_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_bulk_upload_items_detected_document_type",
        "bulk_upload_items",
        "detected_document_type IN ("
        "'trial_balance', 'corporate_tax_return', 'temporary_tax_return', "
        "'balance_sheet', 'income_statement', 'unknown'"
        ")",
    )

    op.drop_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        "analysis_type IN ('trial_balance')",
    )

    op.drop_constraint(
        "ck_financial_documents_document_type",
        "financial_documents",
        type_="check",
    )
    op.create_check_constraint(
        "ck_financial_documents_document_type",
        "financial_documents",
        "document_type IN ('trial_balance', 'tax_declaration', 'financial_statement', 'other')",
    )
