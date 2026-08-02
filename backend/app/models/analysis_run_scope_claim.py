"""Durable 5.0C run ownership reservation; not workflow or job state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


class AnalysisRunScopeClaim(Base):
    __tablename__ = "analysis_run_scope_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["financial_period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_analysis_run_scope_claims_period_company", ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", name="uq_analysis_run_scope_claims_run_id"),
        Index(
            "ix_analysis_run_scope_claims_scope_status",
            "company_id", "financial_period_id", "tenant_id", "status", "persisted_run_id",
        ),
        Index(
            "ix_analysis_run_scope_claims_subject_scope",
            "initiating_subject_id", "tenant_id", "company_id", "financial_period_id",
        ),
        CheckConstraint("operation_kind IN ('START','RESUME','RETRY')", name="operation_kind"),
        CheckConstraint("original_operation IN ('START','RESUME')", name="original_operation"),
        CheckConstraint("status IN ('CLAIMED','FINALIZED')", name="status"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(_sha256_check("application_command_digest"), name="command_digest_sha256"),
        CheckConstraint(
            "persisted_request_fingerprint IS NULL OR " + _sha256_check("persisted_request_fingerprint"),
            name="persisted_fingerprint_sha256",
        ),
        CheckConstraint(
            "persisted_terminal_content_digest IS NULL OR " + _sha256_check("persisted_terminal_content_digest"),
            name="persisted_digest_sha256",
        ),
        CheckConstraint(
            "(operation_kind = 'START' AND original_operation = 'START' AND previous_run_id IS NULL) OR "
            "(operation_kind = 'RESUME' AND original_operation = 'RESUME' AND previous_run_id IS NOT NULL) OR "
            "(operation_kind = 'RETRY' AND previous_run_id IS NOT NULL)",
            name="scope_lifecycle",
        ),
        CheckConstraint(
            "(status = 'CLAIMED' AND persisted_run_id IS NULL AND persisted_request_fingerprint IS NULL "
            "AND persisted_terminal_content_digest IS NULL AND finalized_at IS NULL) OR "
            "(status = 'FINALIZED' AND persisted_run_id IS NOT NULL AND persisted_request_fingerprint IS NOT NULL "
            "AND persisted_terminal_content_digest IS NOT NULL AND finalized_at IS NOT NULL)",
            name="finalization_fields",
        ),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    financial_period_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(
        String(63), ForeignKey("security_tenants.tenant_key", ondelete="RESTRICT")
    )
    initiating_subject_id: Mapped[str | None] = mapped_column(String(255))
    operation_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    original_operation: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_run_id: Mapped[str | None] = mapped_column(String(255))
    application_command_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_token: Mapped[str] = mapped_column(String(64), nullable=False)
    persisted_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="RESTRICT")
    )
    persisted_request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    persisted_terminal_content_digest: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
