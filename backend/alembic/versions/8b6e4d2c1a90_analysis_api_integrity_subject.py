"""Analysis API provenance digest and initiating-subject binding.

Revision ID: 8b6e4d2c1a90
Revises: 5c1a7e9d3b20
"""

from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa

from app.orchestration_persistence.codec import canonical_json_bytes


revision = "8b6e4d2c1a90"
down_revision = "5c1a7e9d3b20"
branch_labels = None
depends_on = None


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


def _scope_claim_trigger(*, include_subject: bool) -> str:
    subject_clause = (
        "OR OLD.initiating_subject_id IS DISTINCT FROM NEW.initiating_subject_id"
        if include_subject else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION reject_analysis_run_scope_claim_mutation()
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
               {subject_clause}
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
    """


def upgrade() -> None:
    op.add_column(
        "analysis_run_scope_claims",
        sa.Column("initiating_subject_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_analysis_run_scope_claims_subject_scope",
        "analysis_run_scope_claims",
        ["initiating_subject_id", "tenant_id", "company_id", "financial_period_id"],
    )
    op.execute(_scope_claim_trigger(include_subject=True))
    op.execute("""
        CREATE FUNCTION require_analysis_run_scope_claim_subject()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.initiating_subject_id IS NULL OR btrim(NEW.initiating_subject_id) = '' THEN
                RAISE EXCEPTION 'new analysis run scope claims require an initiating subject';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_analysis_run_scope_claims_require_subject
        BEFORE INSERT ON analysis_run_scope_claims
        FOR EACH ROW EXECUTE FUNCTION require_analysis_run_scope_claim_subject();
    """)

    op.add_column(
        "financial_analysis_results",
        sa.Column("canonical_result_digest", sa.String(length=64), nullable=True),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, result_json FROM financial_analysis_results "
        "WHERE status = 'completed' AND result_json IS NOT NULL"
    )).mappings()
    for row in rows:
        digest = hashlib.sha256(canonical_json_bytes(row["result_json"])).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE financial_analysis_results "
                "SET canonical_result_digest = :digest WHERE id = :id"
            ),
            {"digest": digest, "id": row["id"]},
        )
    op.create_check_constraint(
        "ck_financial_analysis_results_canonical_digest",
        "financial_analysis_results",
        "(canonical_result_digest IS NULL OR (" + _sha256_check("canonical_result_digest") + ")) "
        "AND (status <> 'completed' OR result_json IS NULL OR canonical_result_digest IS NOT NULL)",
    )
    op.execute("""
        CREATE FUNCTION protect_terminal_financial_result_integrity()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'completed' AND (
                OLD.result_json IS DISTINCT FROM NEW.result_json OR
                OLD.canonical_result_digest IS DISTINCT FROM NEW.canonical_result_digest
            ) THEN
                RAISE EXCEPTION 'terminal financial result payload integrity is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_financial_analysis_results_integrity
        BEFORE UPDATE ON financial_analysis_results
        FOR EACH ROW EXECUTE FUNCTION protect_terminal_financial_result_integrity();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_financial_analysis_results_integrity "
        "ON financial_analysis_results"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_terminal_financial_result_integrity()")
    op.drop_constraint(
        "ck_financial_analysis_results_canonical_digest",
        "financial_analysis_results",
        type_="check",
    )
    op.drop_column("financial_analysis_results", "canonical_result_digest")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_analysis_run_scope_claims_require_subject "
        "ON analysis_run_scope_claims"
    )
    op.execute("DROP FUNCTION IF EXISTS require_analysis_run_scope_claim_subject()")
    op.execute(_scope_claim_trigger(include_subject=False))
    op.drop_index(
        "ix_analysis_run_scope_claims_subject_scope",
        table_name="analysis_run_scope_claims",
    )
    op.drop_column("analysis_run_scope_claims", "initiating_subject_id")
