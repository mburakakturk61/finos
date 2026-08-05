"""Immutable restatement metadata owned by a FinancialAnalysisResult."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class FinancialAnalysisResultRevisionMetadata(Base):
    __tablename__ = "financial_analysis_result_revision_metadata"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_result_id", "company_id", "period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_far_revision_metadata_owner_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "tenant_id"],
            ["companies.id", "companies.tenant_id"],
            name="fk_far_revision_metadata_company_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_analysis_result_id", "company_id", "period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_far_revision_metadata_supersedes_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("restatement_revision >= 0", name="ck_far_revision_metadata_revision_nonnegative"),
        CheckConstraint(
            "(restatement_state='ORIGINAL' AND restatement_revision=0 AND supersedes_analysis_result_id IS NULL AND restatement_reason='NONE') OR "
            "(restatement_state='RESTATED' AND restatement_revision>0 AND supersedes_analysis_result_id IS NOT NULL AND restatement_reason IN ('ERROR_CORRECTION','ACCOUNTING_POLICY_CHANGE','PRESENTATION_RECLASSIFICATION','SCOPE_CHANGE')) OR "
            "(restatement_state='UNDECLARED_LEGACY' AND restatement_revision=0 AND supersedes_analysis_result_id IS NULL AND restatement_reason='LEGACY_UNDECLARED')",
            name="ck_far_revision_metadata_state_contract",
        ),
        CheckConstraint("metadata_schema_version='1.0.0'", name="ck_far_revision_metadata_schema_version"),
        Index(
            "ix_far_revision_metadata_scope_state_revision",
            "company_id", "period_id", "restatement_state", "restatement_revision",
        ),
        Index("ix_far_revision_metadata_supersedes", "supersedes_analysis_result_id"),
    )

    analysis_result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    restatement_state: Mapped[str] = mapped_column(String(24), nullable=False)
    restatement_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    restatement_reason: Mapped[str] = mapped_column(String(40), nullable=False)
    supersedes_analysis_result_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    metadata_schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return "FinancialAnalysisResultRevisionMetadata()"


