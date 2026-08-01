"""Milestone 5.0C durable run ownership reservation.

Revision ID: 5c1a7e9d3b20
Revises: 4f9d2a6b8c10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5c1a7e9d3b20"
down_revision: Union[str, None] = "4f9d2a6b8c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


def upgrade() -> None:
    # Historical databases retained VARCHAR(13), although the frozen
    # AnalysisType contract already contains longer INCOME_STATEMENT and
    # FINANCIAL_RATIOS values.  Widen only; this aligns storage with the
    # existing model/public contract and does not add a new enum value.
    op.alter_column(
        "financial_analysis_results", "analysis_type",
        existing_type=sa.String(length=13), type_=sa.String(), existing_nullable=False,
    )
    op.create_table(
        "analysis_run_scope_claims",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(255), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("financial_period_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(255)),
        sa.Column("operation_kind", sa.String(16), nullable=False),
        sa.Column("original_operation", sa.String(16), nullable=False),
        sa.Column("previous_run_id", sa.String(255)),
        sa.Column("application_command_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(64), nullable=False),
        sa.Column("persisted_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("persisted_request_fingerprint", sa.String(64)),
        sa.Column("persisted_terminal_content_digest", sa.String(64)),
        sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("claim_id", name=op.f("pk_analysis_run_scope_claims")),
        sa.UniqueConstraint("run_id", name="uq_analysis_run_scope_claims_run_id"),
        sa.ForeignKeyConstraint(
            ["financial_period_id", "company_id"],
            ["financial_periods.id", "financial_periods.company_id"],
            name="fk_analysis_run_scope_claims_period_company", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["persisted_run_id"], ["orchestration_runs.id"],
            name=op.f("fk_analysis_run_scope_claims_persisted_run_id_orchestration_runs"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("operation_kind IN ('START','RESUME','RETRY')", name=op.f("ck_analysis_run_scope_claims_operation_kind")),
        sa.CheckConstraint("original_operation IN ('START','RESUME')", name=op.f("ck_analysis_run_scope_claims_original_operation")),
        sa.CheckConstraint("status IN ('CLAIMED','FINALIZED')", name=op.f("ck_analysis_run_scope_claims_status")),
        sa.CheckConstraint("version > 0", name=op.f("ck_analysis_run_scope_claims_version_positive")),
        sa.CheckConstraint(_sha256_check("application_command_digest"), name=op.f("ck_analysis_run_scope_claims_command_digest_sha256")),
        sa.CheckConstraint("persisted_request_fingerprint IS NULL OR " + _sha256_check("persisted_request_fingerprint"), name=op.f("ck_analysis_run_scope_claims_persisted_fingerprint_sha256")),
        sa.CheckConstraint("persisted_terminal_content_digest IS NULL OR " + _sha256_check("persisted_terminal_content_digest"), name=op.f("ck_analysis_run_scope_claims_persisted_digest_sha256")),
        sa.CheckConstraint(
            "(operation_kind = 'START' AND original_operation = 'START' AND previous_run_id IS NULL) OR "
            "(operation_kind = 'RESUME' AND original_operation = 'RESUME' AND previous_run_id IS NOT NULL) OR "
            "(operation_kind = 'RETRY' AND previous_run_id IS NOT NULL)",
            name=op.f("ck_analysis_run_scope_claims_scope_lifecycle"),
        ),
        sa.CheckConstraint(
            "(status = 'CLAIMED' AND persisted_run_id IS NULL AND persisted_request_fingerprint IS NULL "
            "AND persisted_terminal_content_digest IS NULL AND finalized_at IS NULL) OR "
            "(status = 'FINALIZED' AND persisted_run_id IS NOT NULL AND persisted_request_fingerprint IS NOT NULL "
            "AND persisted_terminal_content_digest IS NOT NULL AND finalized_at IS NOT NULL)",
            name=op.f("ck_analysis_run_scope_claims_finalization_fields"),
        ),
    )
    op.execute("""
        CREATE FUNCTION reject_analysis_run_scope_claim_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'analysis run scope claims are immutable';
            END IF;
            IF OLD.claim_id IS DISTINCT FROM NEW.claim_id
               OR OLD.run_id IS DISTINCT FROM NEW.run_id
               OR OLD.company_id IS DISTINCT FROM NEW.company_id
               OR OLD.financial_period_id IS DISTINCT FROM NEW.financial_period_id
               OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
               OR OLD.operation_kind IS DISTINCT FROM NEW.operation_kind
               OR OLD.original_operation IS DISTINCT FROM NEW.original_operation
               OR OLD.previous_run_id IS DISTINCT FROM NEW.previous_run_id
               OR OLD.application_command_digest IS DISTINCT FROM NEW.application_command_digest
               OR OLD.claim_token IS DISTINCT FROM NEW.claim_token
               OR OLD.claimed_at IS DISTINCT FROM NEW.claimed_at THEN
                RAISE EXCEPTION 'analysis run scope ownership is immutable';
            END IF;
            IF OLD.status <> 'CLAIMED' OR NEW.status <> 'FINALIZED'
               OR NEW.version <> OLD.version + 1
               OR NEW.persisted_run_id IS NULL
               OR NEW.persisted_request_fingerprint IS NULL
               OR NEW.persisted_terminal_content_digest IS NULL
               OR NEW.finalized_at IS NULL THEN
                RAISE EXCEPTION 'only one valid claim finalization is permitted';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_analysis_run_scope_claims_immutable
        BEFORE UPDATE OR DELETE ON analysis_run_scope_claims
        FOR EACH ROW EXECUTE FUNCTION reject_analysis_run_scope_claim_mutation();
    """)
    op.create_index(
        "ix_analysis_run_scope_claims_scope_status",
        "analysis_run_scope_claims",
        ["company_id", "financial_period_id", "tenant_id", "status", "persisted_run_id"],
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_analysis_run_scope_claims_scope_status")
    op.execute("DROP TRIGGER IF EXISTS trg_analysis_run_scope_claims_immutable ON analysis_run_scope_claims")
    op.execute("DROP FUNCTION IF EXISTS reject_analysis_run_scope_claim_mutation()")
    op.drop_table("analysis_run_scope_claims")
    # Deliberately do not shrink analysis_type back to VARCHAR(13): doing so
    # could destroy or reject values from the pre-existing public enum.
