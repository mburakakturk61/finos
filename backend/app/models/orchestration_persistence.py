"""ORM owners for immutable Milestone 5.0B terminal orchestration history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


class OrchestrationPhysicalObject(Base):
    __tablename__ = "orchestration_physical_objects"
    __table_args__ = (
        CheckConstraint("state IN ('staged', 'ready', 'quarantined')", name="state"),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint(_sha256_check("content_digest"), name="digest_sha256"),
        UniqueConstraint("locator", name="uq_orchestration_physical_objects_locator"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    locator: Mapped[str] = mapped_column(String(1024), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_etag: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrchestrationArtifact(Base):
    __tablename__ = "orchestration_artifacts"
    __table_args__ = (
        CheckConstraint(_sha256_check("content_digest"), name="digest_sha256"),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("storage_backend IN ('inline_jsonb', 'external_blob')", name="storage_backend"),
        CheckConstraint(
            "(storage_backend = 'inline_jsonb' AND inline_payload IS NOT NULL AND physical_object_id IS NULL) OR "
            "(storage_backend = 'external_blob' AND inline_payload IS NULL AND physical_object_id IS NOT NULL)",
            name="storage_owner_xor",
        ),
        UniqueConstraint("id", "content_digest", name="uq_orchestration_artifacts_id_digest"),
        Index("ix_orchestration_artifacts_content_digest", "content_digest"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    serializer_format: Mapped[str] = mapped_column(String(32), nullable=False)
    serializer_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(16), nullable=False)
    inline_payload: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON_TYPE)
    physical_object_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orchestration_physical_objects.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrchestrationArtifactLocation(Base):
    """Mutable CAS indirection; canonical artifact/object rows stay immutable."""
    __tablename__ = "orchestration_artifact_locations"
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orchestration_artifacts.id", ondelete="RESTRICT"), primary_key=True
    )
    physical_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orchestration_physical_objects.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrchestrationRun(Base):
    __tablename__ = "orchestration_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["period_id", "company_id"], ["financial_periods.id", "financial_periods.company_id"],
            name="fk_orchestration_runs_period_company", ondelete="RESTRICT"
        ),
        CheckConstraint(_sha256_check("request_fingerprint"), name="request_fingerprint_sha256"),
        CheckConstraint(_sha256_check("terminal_content_digest"), name="terminal_digest_sha256"),
        CheckConstraint("previous_run_id IS NULL OR previous_run_id <> id", name="no_self_resume"),
        CheckConstraint("finalized_at IS NOT NULL", name="terminal_is_finalized"),
        CheckConstraint(
            "status IN ('fully_completed','completed_with_degradations','partially_completed','failed','cancelled')",
            name="status",
        ),
        UniqueConstraint("run_id", name="uq_orchestration_runs_run_id"),
        Index("ix_orchestration_runs_scope_finalized", "company_id", "period_id", "finalized_at"),
        Index("ix_orchestration_runs_correlation_id", "correlation_id"),
        Index("ix_orchestration_runs_previous_run_id", "previous_run_id"),
        Index("ix_orchestration_runs_status", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_outputs_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=False)
    input_version_inventory_json: Mapped[dict[str, str]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    orchestration_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    orchestration_model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_plan_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="RESTRICT")
    )
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrchestrationEngineExecution(Base):
    __tablename__ = "orchestration_engine_executions"
    __table_args__ = (
        UniqueConstraint("run_id", "engine_code", name="uq_orchestration_execution_run_engine"),
        UniqueConstraint("run_id", "execution_ordinal", name="uq_orchestration_execution_run_ordinal"),
        CheckConstraint("execution_ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(_sha256_check("input_fingerprint"), name="input_fingerprint_sha256"),
        CheckConstraint(
            "((status IN ('completed','degraded','reused')) AND "
            "((artifact_id IS NOT NULL) <> (financial_analysis_result_id IS NOT NULL))) OR "
            "((status IN ('not_started','failed','skipped')) AND artifact_id IS NULL AND financial_analysis_result_id IS NULL)",
            name="result_owner_status_xor",
        ),
        CheckConstraint(
            "NOT (artifact_id IS NOT NULL AND financial_analysis_result_id IS NOT NULL)",
            name="result_owner_at_most_one",
        ),
        CheckConstraint(
            "(status = 'reused' AND reused_from_engine_execution_id IS NOT NULL) OR "
            "(status <> 'reused' AND reused_from_engine_execution_id IS NULL)", name="reuse_source_status"
        ),
        CheckConstraint(
            "status IN ('not_started','completed','degraded','failed','skipped','reused')",
            name="status",
        ),
        CheckConstraint(
            "status IN ('completed','degraded','reused') OR "
            "(artifact_id IS NULL AND financial_analysis_result_id IS NULL)",
            name="no_result_for_non_result_status",
        ),
        CheckConstraint(
            "engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio','benchmark','health_score','credit_score','recommendation','executive_report','dashboard','render_contract','multi_period_trend')",
            name="engine_code",
        ),
        CheckConstraint(
            "((engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio','multi_period_trend')) AND artifact_id IS NULL) OR "
            "((engine_code NOT IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio','multi_period_trend')) AND financial_analysis_result_id IS NULL)",
            name="engine_owner_mapping",
        ),
        CheckConstraint(
            "((artifact_id IS NOT NULL OR financial_analysis_result_id IS NOT NULL) AND owner_content_digest IS NOT NULL) OR "
            "(artifact_id IS NULL AND financial_analysis_result_id IS NULL AND owner_content_digest IS NULL)",
            name="owner_digest_presence",
        ),
        CheckConstraint(
            "owner_content_digest IS NULL OR " + _sha256_check("owner_content_digest"),
            name="owner_digest_sha256",
        ),
        CheckConstraint(
            "financial_trial_balance_usage IS NULL OR "
            "(engine_code IN ('fs_balance_sheet','fs_income_statement') AND "
            "financial_trial_balance_usage IN ('fallback_source','reconciliation_reference'))",
            name="financial_trial_balance_usage",
        ),
        CheckConstraint(
            "reused_from_engine_execution_id IS NULL OR reused_from_engine_execution_id <> id",
            name="no_self_reuse",
        ),
        Index("ix_orchestration_execution_engine_status", "engine_code", "status"),
        Index(
            "ix_orchestration_engine_executions_financial_analysis_result_id",
            "financial_analysis_result_id",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="RESTRICT"), nullable=False)
    engine_code: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    inner_status: Mapped[str | None] = mapped_column(String(64))
    dependency_engine_codes_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    engine_schema_version: Mapped[str | None] = mapped_column(String(32))
    engine_model_version: Mapped[str | None] = mapped_column(String(32))
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    result_kind: Mapped[str | None] = mapped_column(String(64))
    owner_content_digest: Mapped[str | None] = mapped_column(String(64))
    financial_trial_balance_usage: Mapped[str | None] = mapped_column(String(32))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("orchestration_artifacts.id", ondelete="RESTRICT"))
    financial_analysis_result_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("financial_analysis_results.id", ondelete="RESTRICT"))
    reused_from_engine_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("orchestration_engine_executions.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrchestrationError(Base):
    __tablename__ = "orchestration_errors"
    __table_args__ = (
        UniqueConstraint("run_id", "error_ordinal", name="uq_orchestration_errors_run_ordinal"),
        CheckConstraint("error_ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "(cash_flow_error_code IS NULL AND safe_metadata_json IS NULL AND error_retryable IS NULL) OR "
            "(cash_flow_error_code IS NOT NULL AND safe_metadata_json IS NOT NULL AND error_retryable IS NOT NULL)",
            name="cash_flow_extension_all_null_or_set",
        ),
        CheckConstraint(
            "cash_flow_error_code IS NULL OR engine_code = 'cash_flow'",
            name="cash_flow_extension_engine",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="RESTRICT"), nullable=False)
    engine_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("orchestration_engine_executions.id", ondelete="RESTRICT"))
    error_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_code: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    original_exception_type: Mapped[str | None] = mapped_column(String(255))
    cash_flow_error_code: Mapped[str | None] = mapped_column(String(64))
    safe_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    error_retryable: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
