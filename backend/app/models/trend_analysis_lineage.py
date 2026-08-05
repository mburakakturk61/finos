"""Immutable N-period provenance rows for Multi-Period Trend owners."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


class TrendAnalysisLineage(Base):
    __tablename__ = "trend_analysis_lineage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["trend_analysis_result_id", "company_id", "anchor_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_trend_lineage_owner_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_analysis_result_id", "company_id", "source_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_trend_lineage_source_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "tenant_id"],
            ["companies.id", "companies.tenant_id"],
            name="fk_trend_lineage_company_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["anchor_period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_trend_lineage_anchor_period_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_trend_lineage_source_period_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("trend_analysis_result_id", "ordinal", "source_role", name="uq_trend_lineage_owner_ordinal_role"),
        UniqueConstraint("trend_analysis_result_id", "source_period_id", "source_role", name="uq_trend_lineage_owner_period_role"),
        UniqueConstraint("trend_analysis_result_id", "source_analysis_result_id", name="uq_trend_lineage_owner_source"),
        CheckConstraint("ordinal >= 0", name="ck_trend_lineage_ordinal_nonnegative"),
        CheckConstraint(
            "source_role IN ('balance_sheet','income_statement','cash_flow','financial_ratios')",
            name="ck_trend_lineage_source_role",
        ),
        CheckConstraint(
            "source_engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio')",
            name="ck_trend_lineage_source_engine_code",
        ),
        CheckConstraint(
            "source_analysis_type IN ('balance_sheet','income_statement','cash_flow','financial_ratios')",
            name="ck_trend_lineage_source_analysis_type",
        ),
        CheckConstraint(
            "(source_role='balance_sheet' AND source_engine_code='fs_balance_sheet' AND source_analysis_type='balance_sheet') OR "
            "(source_role='income_statement' AND source_engine_code='fs_income_statement' AND source_analysis_type='income_statement') OR "
            "(source_role='cash_flow' AND source_engine_code='cash_flow' AND source_analysis_type='cash_flow') OR "
            "(source_role='financial_ratios' AND source_engine_code='ratio' AND source_analysis_type='financial_ratios')",
            name="ck_trend_lineage_role_engine_type",
        ),
        CheckConstraint(
            "observation_evidence IN ('exact','derived','estimated','unavailable')",
            name="ck_trend_lineage_observation_evidence",
        ),
        CheckConstraint(_sha256_check("source_canonical_digest"), name="ck_trend_lineage_source_digest"),
        CheckConstraint(_sha256_check("comparability_proof_digest"), name="ck_trend_lineage_comparability_digest"),
        CheckConstraint(_sha256_check("source_set_digest"), name="ck_trend_lineage_source_set_digest"),
        CheckConstraint(
            "length(resolution_proof_reference)=80 AND substr(resolution_proof_reference,1,16)='trend:v1:sha256:' AND "
            + _sha256_check("substr(resolution_proof_reference,17)"),
            name="ck_trend_lineage_resolution_reference",
        ),
        CheckConstraint("lineage_schema_version='1.0.0'", name="ck_trend_lineage_schema_version"),
        Index("ix_trend_lineage_source_analysis_result_id", "source_analysis_result_id"),
        Index("ix_trend_lineage_company_anchor", "company_id", "anchor_period_id"),
        Index("ix_trend_lineage_owner_ordinal", "trend_analysis_result_id", "ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trend_analysis_result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    anchor_period_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_period_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_analysis_result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_engine_code: Mapped[str] = mapped_column(String(40), nullable=False)
    source_analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_canonical_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_schema_version: Mapped[str | None] = mapped_column(String(32))
    source_model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_evidence: Mapped[str] = mapped_column(String(16), nullable=False)
    comparability_proof_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    resolution_proof_reference: Mapped[str] = mapped_column(String(96), nullable=False)
    source_set_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return "TrendAnalysisLineage()"

