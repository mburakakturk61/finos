"""Milestone 5.0B orchestration persistence and recovery foundation.

Revision ID: 3e8c3f6501ce
Revises: 3a7c2e9f5b14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3e8c3f6501ce"
down_revision: Union[str, None] = "3a7c2e9f5b14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


def upgrade() -> None:
    op.create_table(
        "orchestration_physical_objects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("locator", sa.String(1024), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum_etag", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("state IN ('staged','ready','quarantined')", name="ck_orchestration_physical_objects_state"),
        sa.CheckConstraint(_sha256_check("content_digest"), name="ck_orchestration_physical_objects_digest_sha256"),
        sa.CheckConstraint("byte_size >= 0", name="ck_orchestration_physical_objects_byte_size_nonnegative"),
        sa.UniqueConstraint("locator", name="uq_orchestration_physical_objects_locator"),
    )
    op.create_table(
        "orchestration_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("artifact_kind", sa.String(64), nullable=False),
        sa.Column("serializer_format", sa.String(32), nullable=False),
        sa.Column("serializer_schema_version", sa.String(32), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_backend", sa.String(16), nullable=False),
        sa.Column("inline_payload", JSONB),
        sa.Column("physical_object_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["physical_object_id"], ["orchestration_physical_objects.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(_sha256_check("content_digest"), name="ck_orchestration_artifacts_digest_sha256"),
        sa.CheckConstraint("byte_size >= 0", name="ck_orchestration_artifacts_byte_size_nonnegative"),
        sa.CheckConstraint("storage_backend IN ('inline_jsonb','external_blob')", name="ck_orchestration_artifacts_storage_backend"),
        sa.CheckConstraint("(storage_backend='inline_jsonb' AND inline_payload IS NOT NULL AND physical_object_id IS NULL) OR (storage_backend='external_blob' AND inline_payload IS NULL AND physical_object_id IS NOT NULL)", name="ck_orchestration_artifacts_storage_owner_xor"),
        sa.UniqueConstraint("id", "content_digest", name="uq_orchestration_artifacts_id_digest"),
    )
    op.create_index("ix_orchestration_artifacts_content_digest", "orchestration_artifacts", ["content_digest"])
    op.create_table(
        "orchestration_artifact_locations",
        sa.Column("artifact_id", sa.Uuid(), primary_key=True),
        sa.Column("physical_object_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["orchestration_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["physical_object_id"], ["orchestration_physical_objects.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "orchestration_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.String(255), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("terminal_content_digest", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(255)),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("requested_outputs_json", JSONB, nullable=False),
        sa.Column("warnings_json", JSONB, nullable=False),
        sa.Column("input_version_inventory_json", JSONB, nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("orchestration_schema_version", sa.String(32), nullable=False),
        sa.Column("orchestration_model_version", sa.String(32), nullable=False),
        sa.Column("execution_plan_version", sa.String(32), nullable=False),
        sa.Column("fingerprint_schema_version", sa.String(32), nullable=False),
        sa.Column("previous_run_id", sa.Uuid()),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["period_id", "company_id"], ["financial_periods.id", "financial_periods.company_id"], name="fk_orchestration_runs_period_company", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_run_id"], ["orchestration_runs.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(_sha256_check("request_fingerprint"), name="ck_orchestration_runs_request_fingerprint_sha256"),
        sa.CheckConstraint(_sha256_check("terminal_content_digest"), name="ck_orchestration_runs_terminal_digest_sha256"),
        sa.CheckConstraint("previous_run_id IS NULL OR previous_run_id <> id", name="ck_orchestration_runs_no_self_resume"),
        sa.UniqueConstraint("run_id", name="uq_orchestration_runs_run_id"),
    )
    op.create_index("ix_orchestration_runs_scope_finalized", "orchestration_runs", ["company_id", "period_id", "finalized_at"])
    op.create_index("ix_orchestration_runs_correlation_id", "orchestration_runs", ["correlation_id"])
    op.create_index("ix_orchestration_runs_previous_run_id", "orchestration_runs", ["previous_run_id"])
    op.create_index("ix_orchestration_runs_status", "orchestration_runs", ["status"])
    op.create_table(
        "orchestration_engine_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("engine_code", sa.String(64), nullable=False),
        sa.Column("execution_ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("inner_status", sa.String(64)),
        sa.Column("dependency_engine_codes_json", JSONB, nullable=False),
        sa.Column("engine_schema_version", sa.String(32)),
        sa.Column("engine_model_version", sa.String(32)),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("fingerprint_schema_version", sa.String(32), nullable=False),
        sa.Column("result_kind", sa.String(64)),
        sa.Column("artifact_id", sa.Uuid()),
        sa.Column("financial_analysis_result_id", sa.Uuid()),
        sa.Column("reused_from_engine_execution_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["orchestration_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["orchestration_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_analysis_result_id"], ["financial_analysis_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reused_from_engine_execution_id"], ["orchestration_engine_executions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", "engine_code", name="uq_orchestration_execution_run_engine"),
        sa.UniqueConstraint("run_id", "execution_ordinal", name="uq_orchestration_execution_run_ordinal"),
        sa.CheckConstraint("execution_ordinal >= 0", name="ck_orchestration_engine_executions_ordinal_nonnegative"),
        sa.CheckConstraint(_sha256_check("input_fingerprint"), name="ck_orchestration_engine_executions_input_fingerprint_sha256"),
        sa.CheckConstraint("NOT (artifact_id IS NOT NULL AND financial_analysis_result_id IS NOT NULL)", name="ck_orchestration_engine_executions_result_owner_at_most_one"),
        sa.CheckConstraint("(status='reused' AND reused_from_engine_execution_id IS NOT NULL) OR (status<>'reused' AND reused_from_engine_execution_id IS NULL)", name="ck_orchestration_engine_executions_reuse_source_status"),
        sa.CheckConstraint("status IN ('completed','degraded','reused') OR (artifact_id IS NULL AND financial_analysis_result_id IS NULL)", name="ck_orchestration_engine_executions_no_result_for_non_result_status"),
    )
    op.create_index("ix_orchestration_execution_engine_status", "orchestration_engine_executions", ["engine_code", "status"])
    op.create_table(
        "orchestration_errors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("engine_execution_id", sa.Uuid()),
        sa.Column("error_ordinal", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("engine_code", sa.String(64)),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("original_exception_type", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["orchestration_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["engine_execution_id"], ["orchestration_engine_executions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", "error_ordinal", name="uq_orchestration_errors_run_ordinal"),
        sa.CheckConstraint("error_ordinal >= 0", name="ck_orchestration_errors_ordinal_nonnegative"),
    )
    op.execute("""
    CREATE FUNCTION reject_orchestration_canonical_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable orchestration record'; END $$
    """)
    for table in (
        "orchestration_runs", "orchestration_engine_executions", "orchestration_errors",
        "orchestration_artifacts", "orchestration_physical_objects",
    ):
        op.execute(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_orchestration_canonical_mutation()")


def downgrade() -> None:
    for table in (
        "orchestration_physical_objects", "orchestration_artifacts", "orchestration_errors",
        "orchestration_engine_executions", "orchestration_runs",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_orchestration_canonical_mutation()")
    op.drop_table("orchestration_errors")
    op.drop_table("orchestration_engine_executions")
    op.drop_table("orchestration_runs")
    op.drop_table("orchestration_artifact_locations")
    op.drop_table("orchestration_artifacts")
    op.drop_table("orchestration_physical_objects")
