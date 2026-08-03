"""Milestone 4.5F immutable Cash Flow cross-period lineage.

Revision ID: d7e9a4c6f205
Revises: c4f7a9d2e103
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d7e9a4c6f205"
down_revision = "c4f7a9d2e103"
branch_labels = None
depends_on = None


ROLES = (
    "current_balance_sheet",
    "prior_balance_sheet",
    "current_income_statement",
    "current_trial_balance",
    "prior_trial_balance",
)


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


def _drop_engine_constraints() -> None:
    """Drop the two semantic engine constraints without trusting legacy names.

    Revision 4f9d2a6b8c10 was emitted with a naming-convention interaction that
    can produce PostgreSQL-truncated names.  Matching the unique constraint
    definitions keeps upgrades deterministic across both legacy catalog forms.
    """
    op.execute("""
    DO $$
    DECLARE
      matched record;
      matched_count integer;
    BEGIN
      SELECT count(*) INTO matched_count
      FROM pg_constraint
      WHERE conrelid='orchestration_engine_executions'::regclass
        AND contype='c'
        AND pg_get_constraintdef(oid) LIKE '%engine_code%'
        AND pg_get_constraintdef(oid) LIKE '%benchmark%'
        AND pg_get_constraintdef(oid) NOT LIKE '%artifact_id%';
      IF matched_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one engine-code constraint, found %', matched_count;
      END IF;
      FOR matched IN
        SELECT conname FROM pg_constraint
        WHERE conrelid='orchestration_engine_executions'::regclass
          AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%engine_code%'
          AND pg_get_constraintdef(oid) LIKE '%benchmark%'
          AND pg_get_constraintdef(oid) NOT LIKE '%artifact_id%'
      LOOP
        EXECUTE format('ALTER TABLE orchestration_engine_executions DROP CONSTRAINT %I', matched.conname);
      END LOOP;

      SELECT count(*) INTO matched_count
      FROM pg_constraint
      WHERE conrelid='orchestration_engine_executions'::regclass
        AND contype='c'
        AND pg_get_constraintdef(oid) LIKE '%engine_code%'
        AND pg_get_constraintdef(oid) LIKE '%artifact_id%'
        AND pg_get_constraintdef(oid) LIKE '%financial_analysis_result_id%';
      IF matched_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one engine-owner constraint, found %', matched_count;
      END IF;
      FOR matched IN
        SELECT conname FROM pg_constraint
        WHERE conrelid='orchestration_engine_executions'::regclass
          AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%engine_code%'
          AND pg_get_constraintdef(oid) LIKE '%artifact_id%'
          AND pg_get_constraintdef(oid) LIKE '%financial_analysis_result_id%'
      LOOP
        EXECUTE format('ALTER TABLE orchestration_engine_executions DROP CONSTRAINT %I', matched.conname);
      END LOOP;
    END $$;
    """)


def upgrade() -> None:
    bind = op.get_bind()
    invalid = bind.scalar(sa.text("""
        SELECT count(*) FROM orchestration_runs
        WHERE orchestration_schema_version <> '2.0.0'
           OR orchestration_model_version <> '2.0.0'
           OR execution_plan_version <> '2.0.0'
           OR fingerprint_schema_version <> '1.0.0'
    """))
    cash_flow_owners = bind.scalar(sa.text(
        "SELECT count(*) FROM financial_analysis_results WHERE analysis_type='cash_flow'"
    ))
    if invalid or cash_flow_owners:
        raise RuntimeError("Cash Flow persistence upgrade requires exact legacy V2 state.")

    op.create_unique_constraint(
        "uq_companies_id_tenant_id", "companies", ["id", "tenant_id"]
    )
    op.create_table(
        "cash_flow_cross_period_lineage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cash_flow_analysis_result_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("current_period_id", sa.Uuid(), nullable=False),
        sa.Column("prior_period_id", sa.Uuid()),
        sa.Column("source_period_id", sa.Uuid(), nullable=False),
        sa.Column("source_analysis_result_id", sa.Uuid(), nullable=False),
        sa.Column("source_role", sa.String(40), nullable=False),
        sa.Column("source_canonical_digest", sa.String(64), nullable=False),
        sa.Column("source_provenance_digest", sa.String(64), nullable=False),
        sa.Column("source_analysis_type", sa.String(40), nullable=False),
        sa.Column("source_engine_version", sa.String(32), nullable=False),
        sa.Column("current_period_descriptor_digest", sa.String(64), nullable=False),
        sa.Column("prior_period_descriptor_digest", sa.String(64)),
        sa.Column("comparability_proof_digest", sa.String(64)),
        sa.Column("lineage_schema_version", sa.String(16), nullable=False),
        sa.Column("lineage_policy_version", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cash_flow_analysis_result_id", "company_id", "current_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_cf_lineage_owner_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_analysis_result_id", "company_id", "source_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_cf_lineage_source_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "tenant_id"], ["companies.id", "companies.tenant_id"],
            name="fk_cf_lineage_company_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_period_id", "company_id"], ["financial_periods.id", "financial_periods.company_id"],
            name="fk_cf_lineage_current_period_company", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prior_period_id", "company_id"], ["financial_periods.id", "financial_periods.company_id"],
            name="fk_cf_lineage_prior_period_company", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("cash_flow_analysis_result_id", "source_role", name="uq_cf_lineage_owner_role"),
        sa.UniqueConstraint("cash_flow_analysis_result_id", "source_analysis_result_id", name="uq_cf_lineage_owner_source"),
        sa.CheckConstraint(
            "source_role IN (" + ",".join(repr(value) for value in ROLES) + ")",
            name="ck_cf_lineage_source_role",
        ),
        sa.CheckConstraint(
            "((source_role LIKE 'current_%' AND source_period_id=current_period_id) OR "
            "(source_role LIKE 'prior_%' AND prior_period_id IS NOT NULL "
            "AND source_period_id=prior_period_id AND source_period_id<>current_period_id))",
            name="ck_cf_lineage_role_period_direction",
        ),
        sa.CheckConstraint(_sha256_check("source_canonical_digest"), name="ck_cf_lineage_source_canonical_digest"),
        sa.CheckConstraint(_sha256_check("source_provenance_digest"), name="ck_cf_lineage_source_provenance_digest"),
        sa.CheckConstraint(_sha256_check("current_period_descriptor_digest"), name="ck_cf_lineage_current_descriptor_digest"),
        sa.CheckConstraint(
            "(prior_period_descriptor_digest IS NULL AND comparability_proof_digest IS NULL) OR "
            "(prior_period_descriptor_digest IS NOT NULL AND comparability_proof_digest IS NOT NULL)",
            name="ck_cf_lineage_prior_proof_pair",
        ),
        sa.CheckConstraint(
            "prior_period_descriptor_digest IS NULL OR " + _sha256_check("prior_period_descriptor_digest"),
            name="ck_cf_lineage_prior_descriptor_digest",
        ),
        sa.CheckConstraint(
            "comparability_proof_digest IS NULL OR " + _sha256_check("comparability_proof_digest"),
            name="ck_cf_lineage_comparability_proof_digest",
        ),
        sa.CheckConstraint("lineage_schema_version='1.0.0'", name="ck_cf_lineage_schema_version"),
        sa.CheckConstraint("lineage_policy_version='1.0.0'", name="ck_cf_lineage_policy_version"),
    )
    op.create_index(
        "ix_cf_lineage_source_analysis_result_id",
        "cash_flow_cross_period_lineage",
        ["source_analysis_result_id"],
    )
    op.create_index(
        "ix_orchestration_engine_executions_financial_analysis_result_id",
        "orchestration_engine_executions",
        ["financial_analysis_result_id"],
    )

    _drop_engine_constraints()
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_code"),
        "orchestration_engine_executions",
        "engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio','benchmark','health_score','credit_score','recommendation','executive_report','dashboard','render_contract')",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_owner_mapping"),
        "orchestration_engine_executions",
        "((engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio')) AND artifact_id IS NULL) OR "
        "((engine_code NOT IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio')) AND financial_analysis_result_id IS NULL)",
    )
    op.add_column("orchestration_errors", sa.Column("cash_flow_error_code", sa.String(64)))
    op.add_column("orchestration_errors", sa.Column("safe_metadata_json", postgresql.JSONB()))
    op.add_column("orchestration_errors", sa.Column("error_retryable", sa.Boolean()))
    op.create_check_constraint(
        op.f("ck_orchestration_errors_cash_flow_extension_all_null_or_set"),
        "orchestration_errors",
        "(cash_flow_error_code IS NULL AND safe_metadata_json IS NULL AND error_retryable IS NULL) OR "
        "(cash_flow_error_code IS NOT NULL AND safe_metadata_json IS NOT NULL AND error_retryable IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_errors_cash_flow_extension_engine"),
        "orchestration_errors",
        "cash_flow_error_code IS NULL OR engine_code='cash_flow'",
    )

    op.execute("""
    CREATE FUNCTION cf45f_lock_row_company_namespace() RETURNS trigger AS $$
    DECLARE company_uuid uuid;
    BEGIN
      IF TG_OP='DELETE' THEN company_uuid := OLD.company_id; ELSE company_uuid := NEW.company_id; END IF;
      PERFORM 1 FROM companies WHERE id=company_uuid FOR UPDATE NOWAIT;
      IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_lock_execution_company_namespace() RETURNS trigger AS $$
    BEGIN
      IF NEW.financial_analysis_result_id IS NOT NULL THEN
        PERFORM 1 FROM companies c JOIN orchestration_runs r ON r.company_id=c.id
        WHERE r.id=NEW.run_id FOR UPDATE OF c NOWAIT;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_validate_lineage_insert() RETURNS trigger AS $$
    DECLARE owner_row financial_analysis_results%ROWTYPE;
    DECLARE source_row financial_analysis_results%ROWTYPE;
    DECLARE company_tenant uuid;
    BEGIN
      SELECT tenant_id INTO company_tenant FROM companies WHERE id=NEW.company_id;
      IF company_tenant IS NULL OR company_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cash flow lineage scope invalid'; END IF;
      SELECT * INTO owner_row FROM financial_analysis_results WHERE id=NEW.cash_flow_analysis_result_id;
      SELECT * INTO source_row FROM financial_analysis_results WHERE id=NEW.source_analysis_result_id;
      IF owner_row.id IS NULL OR owner_row.analysis_type<>'cash_flow' OR owner_row.company_id<>NEW.company_id
         OR owner_row.period_id<>NEW.current_period_id OR owner_row.source_mode<>'multi_source_derived'
         OR owner_row.document_id IS NOT NULL OR owner_row.status<>'completed'
         OR owner_row.result_json IS NULL OR owner_row.canonical_result_digest IS NULL THEN
        RAISE EXCEPTION 'cash flow lineage owner invalid';
      END IF;
      IF source_row.id IS NULL OR source_row.company_id<>NEW.company_id OR source_row.period_id<>NEW.source_period_id
         OR source_row.status<>'completed' OR source_row.result_json IS NULL
         OR source_row.canonical_result_digest IS NULL OR source_row.canonical_result_digest<>NEW.source_canonical_digest
         OR source_row.analysis_type<>NEW.source_analysis_type OR source_row.engine_version<>NEW.source_engine_version THEN
        RAISE EXCEPTION 'cash flow lineage source invalid';
      END IF;
      IF (NEW.source_role IN ('current_balance_sheet','prior_balance_sheet') AND NEW.source_analysis_type<>'balance_sheet')
         OR (NEW.source_role='current_income_statement' AND NEW.source_analysis_type<>'income_statement')
         OR (NEW.source_role IN ('current_trial_balance','prior_trial_balance') AND NEW.source_analysis_type<>'trial_balance') THEN
        RAISE EXCEPTION 'cash flow lineage role type invalid';
      END IF;
      IF EXISTS (SELECT 1 FROM orchestration_engine_executions WHERE financial_analysis_result_id=NEW.cash_flow_analysis_result_id) THEN
        RAISE EXCEPTION 'sealed cash flow lineage cannot be appended';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_reject_lineage_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'immutable cash flow lineage'; END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_guard_cash_flow_owner_insert() RETURNS trigger AS $$
    BEGIN
      IF NEW.analysis_type='cash_flow' AND (
        NEW.source_mode<>'multi_source_derived' OR NEW.document_id IS NOT NULL OR NEW.status<>'completed'
        OR NEW.result_json IS NULL OR NEW.canonical_result_digest IS NULL OR NEW.error_message IS NOT NULL
        OR NEW.engine_version<>'1.0.0' OR NEW.started_at IS NULL OR NEW.completed_at IS NULL
        OR NEW.completed_at<NEW.started_at
      ) THEN RAISE EXCEPTION 'cash flow owner contract invalid'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_guard_protected_owner_mutation() RETURNS trigger AS $$
    BEGIN
      IF OLD.analysis_type='cash_flow' OR NEW.analysis_type='cash_flow'
         OR EXISTS (
           WITH RECURSIVE protected(id) AS (
             SELECT source_analysis_result_id FROM cash_flow_cross_period_lineage
             UNION
             SELECT s.source_analysis_result_id FROM financial_analysis_result_sources s
             JOIN protected p ON p.id=s.analysis_result_id
             WHERE s.source_analysis_result_id IS NOT NULL
           ) SELECT 1 FROM protected WHERE id IN (OLD.id,NEW.id)
         ) THEN
        RAISE EXCEPTION 'protected financial result is immutable';
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_guard_protected_source_binding() RETURNS trigger AS $$
    DECLARE parent_id uuid;
    BEGIN
      IF TG_OP='DELETE' THEN parent_id:=OLD.analysis_result_id; ELSE parent_id:=NEW.analysis_result_id; END IF;
      IF EXISTS (SELECT 1 FROM financial_analysis_results WHERE id=parent_id AND analysis_type='cash_flow')
         OR EXISTS (
           WITH RECURSIVE protected(id) AS (
             SELECT source_analysis_result_id FROM cash_flow_cross_period_lineage
             UNION
             SELECT s.source_analysis_result_id FROM financial_analysis_result_sources s
             JOIN protected p ON p.id=s.analysis_result_id
             WHERE s.source_analysis_result_id IS NOT NULL
           ) SELECT 1 FROM protected WHERE id=parent_id
         ) THEN
        RAISE EXCEPTION 'protected source binding is immutable';
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_guard_protected_document_mutation() RETURNS trigger AS $$
    DECLARE target_document_id uuid;
    BEGIN
      IF TG_OP='DELETE' THEN target_document_id:=OLD.id; ELSE target_document_id:=NEW.id; END IF;
      IF EXISTS (
        WITH RECURSIVE protected(id) AS (
          SELECT source_analysis_result_id FROM cash_flow_cross_period_lineage
          UNION
          SELECT s.source_analysis_result_id FROM financial_analysis_result_sources s
          JOIN protected p ON p.id=s.analysis_result_id
          WHERE s.source_analysis_result_id IS NOT NULL
        )
        SELECT 1 FROM protected p
        JOIN financial_analysis_results r ON r.id=p.id
        LEFT JOIN financial_analysis_result_sources s ON s.analysis_result_id=p.id
        WHERE r.document_id=target_document_id OR s.source_document_id=target_document_id
      ) THEN RAISE EXCEPTION 'protected financial document is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_validate_cash_flow_execution() RETURNS trigger AS $$
    DECLARE owner_row financial_analysis_results%ROWTYPE;
    DECLARE run_row orchestration_runs%ROWTYPE;
    DECLARE role_count integer;
    BEGIN
      IF NEW.engine_code='cash_flow' OR NEW.financial_analysis_result_id IS NOT NULL THEN
        SELECT * INTO run_row FROM orchestration_runs WHERE id=NEW.run_id;
        SELECT * INTO owner_row FROM financial_analysis_results WHERE id=NEW.financial_analysis_result_id;
        IF NEW.engine_code='cash_flow' AND (
          owner_row.id IS NULL OR owner_row.analysis_type<>'cash_flow' OR NEW.result_kind<>'CashFlowResult'
          OR run_row.company_id<>owner_row.company_id OR run_row.period_id<>owner_row.period_id
          OR run_row.orchestration_schema_version<>'3.0.0' OR run_row.orchestration_model_version<>'3.0.0'
          OR run_row.execution_plan_version<>'3.0.0' OR NEW.engine_schema_version<>'1.0.0'
          OR NEW.engine_model_version<>'1.0.0' OR NEW.fingerprint_schema_version<>'1.0.0'
          OR NEW.status NOT IN ('completed','degraded') OR NEW.reused_from_engine_execution_id IS NOT NULL
          OR NEW.inner_status NOT IN ('complete_reconciled','complete_unreconciled','partial_reconciled','partial_unreconciled','insufficient_data')
        ) THEN RAISE EXCEPTION 'cash flow execution contract invalid'; END IF;
        IF NEW.engine_code='cash_flow' AND NEW.inner_status<>'insufficient_data' THEN
          SELECT count(*) INTO role_count FROM cash_flow_cross_period_lineage
          WHERE cash_flow_analysis_result_id=NEW.financial_analysis_result_id
            AND source_role IN ('current_balance_sheet','prior_balance_sheet','current_income_statement');
          IF role_count<>3 THEN RAISE EXCEPTION 'cash flow execution lineage incomplete'; END IF;
        END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION cf45f_require_cash_flow_owner_seal() RETURNS trigger AS $$
    BEGIN
      IF NEW.analysis_type='cash_flow' AND NOT EXISTS (
        SELECT 1 FROM orchestration_engine_executions e
        JOIN orchestration_runs r ON r.id=e.run_id
        WHERE e.financial_analysis_result_id=NEW.id AND e.engine_code='cash_flow'
          AND e.result_kind='CashFlowResult' AND e.status IN ('completed','degraded')
          AND e.reused_from_engine_execution_id IS NULL
          AND r.company_id=NEW.company_id AND r.period_id=NEW.period_id
      ) THEN RAISE EXCEPTION 'cash flow owner must be sealed by terminal execution'; END IF;
      RETURN NULL;
    END; $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_cf_00_namespace_cash_flow_cross_period_lineage_ins
      BEFORE INSERT ON cash_flow_cross_period_lineage FOR EACH ROW EXECUTE FUNCTION cf45f_lock_row_company_namespace();
    CREATE TRIGGER trg_cf_10_validate_cash_flow_cross_period_lineage_ins
      BEFORE INSERT ON cash_flow_cross_period_lineage FOR EACH ROW EXECUTE FUNCTION cf45f_validate_lineage_insert();
    CREATE TRIGGER trg_cf_20_guard_cash_flow_cross_period_lineage_upd
      BEFORE UPDATE ON cash_flow_cross_period_lineage FOR EACH ROW EXECUTE FUNCTION cf45f_reject_lineage_mutation();
    CREATE TRIGGER trg_cf_20_guard_cash_flow_cross_period_lineage_del
      BEFORE DELETE ON cash_flow_cross_period_lineage FOR EACH ROW EXECUTE FUNCTION cf45f_reject_lineage_mutation();

    CREATE TRIGGER trg_cf_10_validate_financial_analysis_results_ins
      BEFORE INSERT ON financial_analysis_results FOR EACH ROW EXECUTE FUNCTION cf45f_guard_cash_flow_owner_insert();
    CREATE TRIGGER trg_cf_20_guard_financial_analysis_results_upd
      BEFORE UPDATE ON financial_analysis_results FOR EACH ROW EXECUTE FUNCTION cf45f_guard_protected_owner_mutation();
    CREATE TRIGGER trg_cf_20_guard_financial_analysis_results_del
      BEFORE DELETE ON financial_analysis_results FOR EACH ROW EXECUTE FUNCTION cf45f_guard_protected_owner_mutation();
    CREATE CONSTRAINT TRIGGER trg_cf_90_owner_sealed_deferred
      AFTER INSERT ON financial_analysis_results DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION cf45f_require_cash_flow_owner_seal();

    CREATE TRIGGER trg_cf_20_guard_financial_analysis_result_sources_ins
      BEFORE INSERT ON financial_analysis_result_sources FOR EACH ROW EXECUTE FUNCTION cf45f_guard_protected_source_binding();
    CREATE TRIGGER trg_cf_20_guard_financial_analysis_result_sources_upd
      BEFORE UPDATE ON financial_analysis_result_sources FOR EACH ROW EXECUTE FUNCTION cf45f_guard_protected_source_binding();
    CREATE TRIGGER trg_cf_20_guard_financial_analysis_result_sources_del
      BEFORE DELETE ON financial_analysis_result_sources FOR EACH ROW EXECUTE FUNCTION cf45f_guard_protected_source_binding();

    CREATE TRIGGER trg_cf_20_guard_financial_documents_upd
      BEFORE UPDATE ON financial_documents FOR EACH ROW EXECUTE FUNCTION cf45f_guard_protected_document_mutation();
    CREATE TRIGGER trg_cf_20_guard_financial_documents_del
      BEFORE DELETE ON financial_documents FOR EACH ROW EXECUTE FUNCTION cf45f_guard_protected_document_mutation();

    CREATE TRIGGER trg_cf_00_namespace_orchestration_engine_executions_ins
      BEFORE INSERT ON orchestration_engine_executions FOR EACH ROW EXECUTE FUNCTION cf45f_lock_execution_company_namespace();
    CREATE TRIGGER trg_cf_10_validate_orchestration_engine_executions_ins
      BEFORE INSERT ON orchestration_engine_executions FOR EACH ROW EXECUTE FUNCTION cf45f_validate_cash_flow_execution();
    """)

    for table in ("financial_documents", "financial_analysis_results", "financial_analysis_result_sources"):
        for event, sql_event in (("ins", "INSERT"), ("upd", "UPDATE"), ("del", "DELETE")):
            op.execute(
                f"CREATE TRIGGER trg_cf_00_namespace_{table}_{event} BEFORE {sql_event} ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION cf45f_lock_row_company_namespace()"
            )


def downgrade() -> None:
    bind = op.get_bind()
    blocked = bind.scalar(sa.text("""
        SELECT
          (SELECT count(*) FROM cash_flow_cross_period_lineage)
        + (SELECT count(*) FROM financial_analysis_results WHERE analysis_type='cash_flow')
        + (SELECT count(*) FROM orchestration_engine_executions WHERE engine_code='cash_flow')
        + (SELECT count(*) FROM orchestration_errors WHERE cash_flow_error_code IS NOT NULL)
        + (SELECT count(*) FROM orchestration_runs
           WHERE orchestration_schema_version<>'2.0.0'
              OR orchestration_model_version<>'2.0.0'
              OR execution_plan_version<>'2.0.0'
              OR fingerprint_schema_version<>'1.0.0')
    """))
    if blocked:
        raise RuntimeError("Cash Flow durable state must be empty before downgrade.")

    for table in ("financial_documents", "financial_analysis_results", "financial_analysis_result_sources"):
        for event in ("del", "upd", "ins"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_cf_00_namespace_{table}_{event} ON {table}")
    for trigger, table in (
        ("trg_cf_10_validate_orchestration_engine_executions_ins", "orchestration_engine_executions"),
        ("trg_cf_00_namespace_orchestration_engine_executions_ins", "orchestration_engine_executions"),
        ("trg_cf_20_guard_financial_analysis_result_sources_del", "financial_analysis_result_sources"),
        ("trg_cf_20_guard_financial_analysis_result_sources_upd", "financial_analysis_result_sources"),
        ("trg_cf_20_guard_financial_analysis_result_sources_ins", "financial_analysis_result_sources"),
        ("trg_cf_20_guard_financial_documents_del", "financial_documents"),
        ("trg_cf_20_guard_financial_documents_upd", "financial_documents"),
        ("trg_cf_90_owner_sealed_deferred", "financial_analysis_results"),
        ("trg_cf_20_guard_financial_analysis_results_del", "financial_analysis_results"),
        ("trg_cf_20_guard_financial_analysis_results_upd", "financial_analysis_results"),
        ("trg_cf_10_validate_financial_analysis_results_ins", "financial_analysis_results"),
        ("trg_cf_20_guard_cash_flow_cross_period_lineage_del", "cash_flow_cross_period_lineage"),
        ("trg_cf_20_guard_cash_flow_cross_period_lineage_upd", "cash_flow_cross_period_lineage"),
        ("trg_cf_10_validate_cash_flow_cross_period_lineage_ins", "cash_flow_cross_period_lineage"),
        ("trg_cf_00_namespace_cash_flow_cross_period_lineage_ins", "cash_flow_cross_period_lineage"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for function in (
        "cf45f_require_cash_flow_owner_seal",
        "cf45f_validate_cash_flow_execution",
        "cf45f_guard_protected_source_binding",
        "cf45f_guard_protected_document_mutation",
        "cf45f_guard_protected_owner_mutation",
        "cf45f_guard_cash_flow_owner_insert",
        "cf45f_reject_lineage_mutation",
        "cf45f_validate_lineage_insert",
        "cf45f_lock_execution_company_namespace",
        "cf45f_lock_row_company_namespace",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    op.drop_constraint(op.f("ck_orchestration_errors_cash_flow_extension_engine"), "orchestration_errors", type_="check")
    op.drop_constraint(op.f("ck_orchestration_errors_cash_flow_extension_all_null_or_set"), "orchestration_errors", type_="check")
    op.drop_column("orchestration_errors", "error_retryable")
    op.drop_column("orchestration_errors", "safe_metadata_json")
    op.drop_column("orchestration_errors", "cash_flow_error_code")
    _drop_engine_constraints()
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_code"), "orchestration_engine_executions",
        "engine_code IN ('fs_balance_sheet','fs_income_statement','ratio','benchmark','health_score','credit_score','recommendation','executive_report','dashboard','render_contract')",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_owner_mapping"), "orchestration_engine_executions",
        "((engine_code IN ('fs_balance_sheet','fs_income_statement','ratio')) AND artifact_id IS NULL) OR "
        "((engine_code NOT IN ('fs_balance_sheet','fs_income_statement','ratio')) AND financial_analysis_result_id IS NULL)",
    )
    op.drop_index("ix_orchestration_engine_executions_financial_analysis_result_id", table_name="orchestration_engine_executions")
    op.drop_index("ix_cf_lineage_source_analysis_result_id", table_name="cash_flow_cross_period_lineage")
    op.drop_table("cash_flow_cross_period_lineage")
    op.drop_constraint("uq_companies_id_tenant_id", "companies", type_="unique")
