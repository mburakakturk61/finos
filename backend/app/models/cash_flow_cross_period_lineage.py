"""Immutable cross-period source ownership for Cash Flow results."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


class CashFlowCrossPeriodLineage(Base):
    __tablename__ = "cash_flow_cross_period_lineage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cash_flow_analysis_result_id", "company_id", "current_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_cf_lineage_owner_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_analysis_result_id", "company_id", "source_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_cf_lineage_source_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "tenant_id"],
            ["companies.id", "companies.tenant_id"],
            name="fk_cf_lineage_company_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["current_period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_cf_lineage_current_period_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["prior_period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_cf_lineage_prior_period_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("cash_flow_analysis_result_id", "source_role", name="uq_cf_lineage_owner_role"),
        UniqueConstraint("cash_flow_analysis_result_id", "source_analysis_result_id", name="uq_cf_lineage_owner_source"),
        CheckConstraint(
            "source_role IN ('current_balance_sheet','prior_balance_sheet','current_income_statement','current_trial_balance','prior_trial_balance')",
            name="ck_cf_lineage_source_role",
        ),
        CheckConstraint(
            "((source_role LIKE 'current_%' AND source_period_id = current_period_id) OR "
            "(source_role LIKE 'prior_%' AND prior_period_id IS NOT NULL AND source_period_id = prior_period_id AND source_period_id <> current_period_id))",
            name="ck_cf_lineage_role_period_direction",
        ),
        CheckConstraint(_sha256_check("source_canonical_digest"), name="ck_cf_lineage_source_canonical_digest"),
        CheckConstraint(_sha256_check("source_provenance_digest"), name="ck_cf_lineage_source_provenance_digest"),
        CheckConstraint(_sha256_check("current_period_descriptor_digest"), name="ck_cf_lineage_current_descriptor_digest"),
        CheckConstraint(
            "(prior_period_descriptor_digest IS NULL AND comparability_proof_digest IS NULL) OR "
            "(prior_period_descriptor_digest IS NOT NULL AND comparability_proof_digest IS NOT NULL)",
            name="ck_cf_lineage_prior_proof_pair",
        ),
        CheckConstraint(
            "prior_period_descriptor_digest IS NULL OR " + _sha256_check("prior_period_descriptor_digest"),
            name="ck_cf_lineage_prior_descriptor_digest",
        ),
        CheckConstraint(
            "comparability_proof_digest IS NULL OR " + _sha256_check("comparability_proof_digest"),
            name="ck_cf_lineage_comparability_proof_digest",
        ),
        CheckConstraint("lineage_schema_version = '1.0.0'", name="ck_cf_lineage_schema_version"),
        CheckConstraint("lineage_policy_version = '1.0.0'", name="ck_cf_lineage_policy_version"),
        Index("ix_cf_lineage_source_analysis_result_id", "source_analysis_result_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cash_flow_analysis_result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    current_period_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    prior_period_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_period_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_analysis_result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_role: Mapped[str] = mapped_column(String(40), nullable=False)
    source_canonical_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_provenance_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    current_period_descriptor_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_period_descriptor_digest: Mapped[str | None] = mapped_column(String(64))
    comparability_proof_digest: Mapped[str | None] = mapped_column(String(64))
    lineage_schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    lineage_policy_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return f"CashFlowCrossPeriodLineage(id={self.id!s})"
