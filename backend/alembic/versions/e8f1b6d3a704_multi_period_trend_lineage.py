"""Milestone 4.6G immutable multi-period trend lineage.

Revision ID: e8f1b6d3a704
Revises: d7e9a4c6f205
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e8f1b6d3a704"
down_revision = "d7e9a4c6f205"
branch_labels = None
depends_on = None


ANALYSIS_TYPES = (
    "trial_balance", "balance_sheet", "income_statement", "cash_flow",
    "tax_return", "financial_ratios", "multi_period_trend",
)
LEGACY_ANALYSIS_TYPES = ANALYSIS_TYPES[:-1]


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


def _analysis_type_constraint(values: tuple[str, ...]) -> str:
    return "analysis_type IN (" + ",".join(repr(item) for item in values) + ")"


def _drop_engine_constraints() -> None:
    op.execute("""
    DO $$
    DECLARE matched record; matched_count integer;
    BEGIN
      SELECT count(*) INTO matched_count FROM pg_constraint
      WHERE conrelid='orchestration_engine_executions'::regclass AND contype='c'
        AND pg_get_constraintdef(oid) LIKE '%engine_code%'
        AND pg_get_constraintdef(oid) LIKE '%benchmark%'
        AND pg_get_constraintdef(oid) NOT LIKE '%artifact_id%';
      IF matched_count<>1 THEN RAISE EXCEPTION 'expected exactly one engine-code constraint, found %',matched_count; END IF;
      FOR matched IN SELECT conname FROM pg_constraint
        WHERE conrelid='orchestration_engine_executions'::regclass AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%engine_code%'
          AND pg_get_constraintdef(oid) LIKE '%benchmark%'
          AND pg_get_constraintdef(oid) NOT LIKE '%artifact_id%'
      LOOP EXECUTE format('ALTER TABLE orchestration_engine_executions DROP CONSTRAINT %I',matched.conname); END LOOP;
      SELECT count(*) INTO matched_count FROM pg_constraint
      WHERE conrelid='orchestration_engine_executions'::regclass AND contype='c'
        AND pg_get_constraintdef(oid) LIKE '%engine_code%'
        AND pg_get_constraintdef(oid) LIKE '%artifact_id%'
        AND pg_get_constraintdef(oid) LIKE '%financial_analysis_result_id%';
      IF matched_count<>1 THEN RAISE EXCEPTION 'expected exactly one engine-owner constraint, found %',matched_count; END IF;
      FOR matched IN SELECT conname FROM pg_constraint
        WHERE conrelid='orchestration_engine_executions'::regclass AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%engine_code%'
          AND pg_get_constraintdef(oid) LIKE '%artifact_id%'
          AND pg_get_constraintdef(oid) LIKE '%financial_analysis_result_id%'
      LOOP EXECUTE format('ALTER TABLE orchestration_engine_executions DROP CONSTRAINT %I',matched.conname); END LOOP;
    END $$;
    """)


def upgrade() -> None:
    bind = op.get_bind()
    unbound = bind.scalar(sa.text("""
        SELECT count(*) FROM financial_analysis_results r
        JOIN companies c ON c.id=r.company_id
        WHERE c.tenant_id IS NULL
    """))
    if unbound:
        raise RuntimeError("Trend lineage upgrade requires trusted tenant binding for every financial result.")

    op.drop_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        _analysis_type_constraint(ANALYSIS_TYPES),
    )
    _drop_engine_constraints()
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_code"),
        "orchestration_engine_executions",
        "engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio','benchmark','health_score','credit_score','recommendation','executive_report','dashboard','render_contract','multi_period_trend')",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_owner_mapping"),
        "orchestration_engine_executions",
        "((engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio','multi_period_trend')) AND artifact_id IS NULL) OR "
        "((engine_code NOT IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio','multi_period_trend')) AND financial_analysis_result_id IS NULL)",
    )

    op.create_table(
        "financial_analysis_result_revision_metadata",
        sa.Column("analysis_result_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("restatement_state", sa.String(24), nullable=False),
        sa.Column("restatement_revision", sa.Integer(), nullable=False),
        sa.Column("restatement_reason", sa.String(40), nullable=False),
        sa.Column("supersedes_analysis_result_id", sa.Uuid()),
        sa.Column("metadata_schema_version", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["analysis_result_id", "company_id", "period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_far_revision_metadata_owner_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "tenant_id"], ["companies.id", "companies.tenant_id"],
            name="fk_far_revision_metadata_company_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_analysis_result_id", "company_id", "period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_far_revision_metadata_supersedes_scope", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("restatement_revision>=0", name="ck_far_revision_metadata_revision_nonnegative"),
        sa.CheckConstraint(
            "(restatement_state='ORIGINAL' AND restatement_revision=0 AND supersedes_analysis_result_id IS NULL AND restatement_reason='NONE') OR "
            "(restatement_state='RESTATED' AND restatement_revision>0 AND supersedes_analysis_result_id IS NOT NULL AND restatement_reason IN ('ERROR_CORRECTION','ACCOUNTING_POLICY_CHANGE','PRESENTATION_RECLASSIFICATION','SCOPE_CHANGE')) OR "
            "(restatement_state='UNDECLARED_LEGACY' AND restatement_revision=0 AND supersedes_analysis_result_id IS NULL AND restatement_reason='LEGACY_UNDECLARED')",
            name="ck_far_revision_metadata_state_contract",
        ),
        sa.CheckConstraint("metadata_schema_version='1.0.0'", name="ck_far_revision_metadata_schema_version"),
    )
    op.create_index(
        "ix_far_revision_metadata_scope_state_revision",
        "financial_analysis_result_revision_metadata",
        ["company_id", "period_id", "restatement_state", "restatement_revision"],
    )
    op.create_index(
        "ix_far_revision_metadata_supersedes",
        "financial_analysis_result_revision_metadata",
        ["supersedes_analysis_result_id"],
    )
    op.execute("""
        INSERT INTO financial_analysis_result_revision_metadata (
          analysis_result_id,tenant_id,company_id,period_id,restatement_state,
          restatement_revision,restatement_reason,supersedes_analysis_result_id,
          metadata_schema_version
        )
        SELECT r.id,c.tenant_id,r.company_id,r.period_id,'UNDECLARED_LEGACY',0,
               'LEGACY_UNDECLARED',NULL,'1.0.0'
        FROM financial_analysis_results r JOIN companies c ON c.id=r.company_id
    """)
    source_count = bind.scalar(sa.text("SELECT count(*) FROM financial_analysis_results"))
    metadata_count = bind.scalar(sa.text("SELECT count(*) FROM financial_analysis_result_revision_metadata"))
    if source_count != metadata_count:
        raise RuntimeError("Trend revision metadata backfill count mismatch.")

    op.create_table(
        "trend_analysis_lineage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trend_analysis_result_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_period_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_period_id", sa.Uuid(), nullable=False),
        sa.Column("source_analysis_result_id", sa.Uuid(), nullable=False),
        sa.Column("source_role", sa.String(32), nullable=False),
        sa.Column("source_engine_code", sa.String(40), nullable=False),
        sa.Column("source_analysis_type", sa.String(40), nullable=False),
        sa.Column("source_canonical_digest", sa.String(64), nullable=False),
        sa.Column("source_schema_version", sa.String(32)),
        sa.Column("source_model_version", sa.String(32), nullable=False),
        sa.Column("observation_evidence", sa.String(16), nullable=False),
        sa.Column("comparability_proof_digest", sa.String(64), nullable=False),
        sa.Column("resolution_proof_reference", sa.String(96), nullable=False),
        sa.Column("source_set_digest", sa.String(64), nullable=False),
        sa.Column("lineage_schema_version", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["trend_analysis_result_id", "company_id", "anchor_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_trend_lineage_owner_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_analysis_result_id", "company_id", "source_period_id"],
            ["financial_analysis_results.id", "financial_analysis_results.company_id", "financial_analysis_results.period_id"],
            name="fk_trend_lineage_source_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "tenant_id"], ["companies.id", "companies.tenant_id"],
            name="fk_trend_lineage_company_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["anchor_period_id", "company_id"], ["financial_periods.id", "financial_periods.company_id"],
            name="fk_trend_lineage_anchor_period_company", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_period_id", "company_id"], ["financial_periods.id", "financial_periods.company_id"],
            name="fk_trend_lineage_source_period_company", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("trend_analysis_result_id", "ordinal", "source_role", name="uq_trend_lineage_owner_ordinal_role"),
        sa.UniqueConstraint("trend_analysis_result_id", "source_period_id", "source_role", name="uq_trend_lineage_owner_period_role"),
        sa.UniqueConstraint("trend_analysis_result_id", "source_analysis_result_id", name="uq_trend_lineage_owner_source"),
        sa.CheckConstraint("ordinal>=0", name="ck_trend_lineage_ordinal_nonnegative"),
        sa.CheckConstraint("source_role IN ('balance_sheet','income_statement','cash_flow','financial_ratios')", name="ck_trend_lineage_source_role"),
        sa.CheckConstraint("source_engine_code IN ('fs_balance_sheet','fs_income_statement','cash_flow','ratio')", name="ck_trend_lineage_source_engine_code"),
        sa.CheckConstraint("source_analysis_type IN ('balance_sheet','income_statement','cash_flow','financial_ratios')", name="ck_trend_lineage_source_analysis_type"),
        sa.CheckConstraint(
            "(source_role='balance_sheet' AND source_engine_code='fs_balance_sheet' AND source_analysis_type='balance_sheet') OR "
            "(source_role='income_statement' AND source_engine_code='fs_income_statement' AND source_analysis_type='income_statement') OR "
            "(source_role='cash_flow' AND source_engine_code='cash_flow' AND source_analysis_type='cash_flow') OR "
            "(source_role='financial_ratios' AND source_engine_code='ratio' AND source_analysis_type='financial_ratios')",
            name="ck_trend_lineage_role_engine_type",
        ),
        sa.CheckConstraint("observation_evidence IN ('exact','derived','estimated','unavailable')", name="ck_trend_lineage_observation_evidence"),
        sa.CheckConstraint(_sha256_check("source_canonical_digest"), name="ck_trend_lineage_source_digest"),
        sa.CheckConstraint(_sha256_check("comparability_proof_digest"), name="ck_trend_lineage_comparability_digest"),
        sa.CheckConstraint(_sha256_check("source_set_digest"), name="ck_trend_lineage_source_set_digest"),
        sa.CheckConstraint(
            "length(resolution_proof_reference)=80 AND substr(resolution_proof_reference,1,16)='trend:v1:sha256:' AND "
            + _sha256_check("substr(resolution_proof_reference,17)"),
            name="ck_trend_lineage_resolution_reference",
        ),
        sa.CheckConstraint("lineage_schema_version='1.0.0'", name="ck_trend_lineage_schema_version"),
    )
    op.create_index("ix_trend_lineage_source_analysis_result_id", "trend_analysis_lineage", ["source_analysis_result_id"])
    op.create_index("ix_trend_lineage_company_anchor", "trend_analysis_lineage", ["company_id", "anchor_period_id"])
    op.create_index("ix_trend_lineage_owner_ordinal", "trend_analysis_lineage", ["trend_analysis_result_id", "ordinal"])

    op.execute("""
    CREATE FUNCTION tr46g_validate_revision_insert() RETURNS trigger AS $$
    DECLARE owner_row financial_analysis_results%ROWTYPE;
    DECLARE previous_row financial_analysis_results%ROWTYPE;
    DECLARE previous_revision integer;
    BEGIN
      SELECT * INTO owner_row FROM financial_analysis_results WHERE id=NEW.analysis_result_id;
      IF owner_row.id IS NULL OR owner_row.company_id<>NEW.company_id OR owner_row.period_id<>NEW.period_id THEN
        RAISE EXCEPTION 'revision metadata owner invalid';
      END IF;
      IF NEW.restatement_state='RESTATED' THEN
        SELECT * INTO previous_row FROM financial_analysis_results WHERE id=NEW.supersedes_analysis_result_id;
        SELECT restatement_revision INTO previous_revision FROM financial_analysis_result_revision_metadata
          WHERE analysis_result_id=NEW.supersedes_analysis_result_id;
        IF previous_row.id IS NULL OR previous_row.analysis_type<>owner_row.analysis_type
           OR previous_revision IS NULL OR NEW.restatement_revision<>previous_revision+1 THEN
          RAISE EXCEPTION 'revision metadata chain invalid';
        END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION tr46g_reject_immutable_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'immutable trend persistence record'; END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION tr46g_guard_trend_owner_insert() RETURNS trigger AS $$
    BEGIN
      IF NEW.analysis_type='multi_period_trend' AND (
        NEW.source_mode<>'multi_source_derived' OR NEW.document_id IS NOT NULL
        OR NEW.status<>'completed' OR NEW.result_json IS NULL
        OR NEW.canonical_result_digest IS NULL OR NEW.error_message IS NOT NULL
        OR NEW.started_at IS NULL OR NEW.completed_at IS NULL OR NEW.completed_at<NEW.started_at
        OR NEW.engine_version<>'1.0.0'
        OR NOT (NEW.result_json ? 'source_set_digest')
        OR NOT (NEW.result_json ? 'lineage_count')
        OR NOT (NEW.result_json ? 'metric_registry_version')
        OR NOT (NEW.result_json ? 'metric_registry_digest')
        OR NOT (NEW.result_json ? 'policy_version')
        OR NOT (NEW.result_json ? 'contract_version')
      ) THEN RAISE EXCEPTION 'trend owner contract invalid'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION tr46g_validate_lineage_insert() RETURNS trigger AS $$
    DECLARE owner_row financial_analysis_results%ROWTYPE;
    DECLARE source_row financial_analysis_results%ROWTYPE;
    DECLARE expected_count integer;
    DECLARE existing_count integer;
    BEGIN
      SELECT * INTO owner_row FROM financial_analysis_results WHERE id=NEW.trend_analysis_result_id;
      SELECT * INTO source_row FROM financial_analysis_results WHERE id=NEW.source_analysis_result_id;
      IF owner_row.id IS NULL OR owner_row.analysis_type<>'multi_period_trend'
         OR owner_row.company_id<>NEW.company_id OR owner_row.period_id<>NEW.anchor_period_id
         OR owner_row.source_mode<>'multi_source_derived' OR owner_row.document_id IS NOT NULL
         OR owner_row.status<>'completed' OR owner_row.result_json IS NULL
         OR owner_row.canonical_result_digest IS NULL THEN
        RAISE EXCEPTION 'trend lineage owner invalid';
      END IF;
      IF source_row.id IS NULL OR source_row.company_id<>NEW.company_id
         OR source_row.period_id<>NEW.source_period_id OR source_row.status<>'completed'
         OR source_row.result_json IS NULL OR source_row.canonical_result_digest IS NULL
         OR source_row.canonical_result_digest<>NEW.source_canonical_digest
         OR source_row.analysis_type::text<>NEW.source_analysis_type
         OR source_row.engine_version<>NEW.source_model_version THEN
        RAISE EXCEPTION 'trend lineage source invalid';
      END IF;
      IF (NEW.source_role='balance_sheet' AND (NEW.source_schema_version IS NOT NULL OR NEW.source_model_version<>'1.0.0'))
         OR (NEW.source_role='income_statement' AND (NEW.source_schema_version IS NOT NULL OR NEW.source_model_version<>'1.0.0'))
         OR (NEW.source_role='cash_flow' AND (NEW.source_schema_version<>'1.0.0' OR NEW.source_model_version<>'1.0.0'))
         OR (NEW.source_role='financial_ratios' AND (NEW.source_schema_version<>'1.0' OR NEW.source_model_version<>'1.1.0')) THEN
        RAISE EXCEPTION 'trend lineage source version invalid';
      END IF;
      IF NEW.source_set_digest<>owner_row.result_json->>'source_set_digest' THEN
        RAISE EXCEPTION 'trend lineage source set invalid';
      END IF;
      expected_count := (owner_row.result_json->>'lineage_count')::integer;
      SELECT count(*) INTO existing_count FROM trend_analysis_lineage
        WHERE trend_analysis_result_id=NEW.trend_analysis_result_id;
      IF expected_count<2 OR existing_count>=expected_count THEN
        RAISE EXCEPTION 'sealed trend lineage cannot be appended';
      END IF;
      RETURN NEW;
    EXCEPTION WHEN invalid_text_representation THEN
      RAISE EXCEPTION 'trend owner lineage count invalid';
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION tr46g_require_complete_owner() RETURNS trigger AS $$
    DECLARE row_count integer;
    DECLARE ordinal_count integer;
    DECLARE min_ordinal integer;
    DECLARE max_ordinal integer;
    DECLARE expected_count integer;
    DECLARE period_conflicts integer;
    DECLARE max_period uuid;
    BEGIN
      IF NEW.analysis_type<>'multi_period_trend' THEN RETURN NULL; END IF;
      expected_count := (NEW.result_json->>'lineage_count')::integer;
      SELECT count(*),count(DISTINCT ordinal),min(ordinal),max(ordinal)
        INTO row_count,ordinal_count,min_ordinal,max_ordinal
        FROM trend_analysis_lineage WHERE trend_analysis_result_id=NEW.id;
      SELECT count(*) INTO period_conflicts FROM (
        SELECT ordinal FROM trend_analysis_lineage WHERE trend_analysis_result_id=NEW.id
        GROUP BY ordinal HAVING count(DISTINCT source_period_id)<>1
      ) invalid;
      SELECT source_period_id INTO max_period FROM trend_analysis_lineage
        WHERE trend_analysis_result_id=NEW.id AND ordinal=max_ordinal LIMIT 1;
      IF row_count<>expected_count OR ordinal_count<2 OR min_ordinal<>0
         OR max_ordinal+1<>ordinal_count OR period_conflicts<>0 OR max_period<>NEW.period_id
         OR EXISTS (SELECT 1 FROM trend_analysis_lineage WHERE trend_analysis_result_id=NEW.id
                    AND source_set_digest<>NEW.result_json->>'source_set_digest')
         OR NOT EXISTS (SELECT 1 FROM financial_analysis_result_revision_metadata
                        WHERE analysis_result_id=NEW.id) THEN
        RAISE EXCEPTION 'trend owner lineage incomplete';
      END IF;
      RETURN NULL;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION tr46g_guard_protected_result_mutation() RETURNS trigger AS $$
    DECLARE target_id uuid;
    BEGIN
      target_id:=OLD.id;
      IF TG_OP='DELETE' THEN
        IF OLD.analysis_type='multi_period_trend'
           OR EXISTS (SELECT 1 FROM trend_analysis_lineage WHERE source_analysis_result_id=target_id) THEN
          RAISE EXCEPTION 'protected trend financial result is immutable';
        END IF;
        RETURN OLD;
      END IF;
      IF OLD.analysis_type='multi_period_trend' OR NEW.analysis_type='multi_period_trend'
         OR EXISTS (SELECT 1 FROM trend_analysis_lineage WHERE source_analysis_result_id=target_id) THEN
        RAISE EXCEPTION 'protected trend financial result is immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_tr46g_10_validate_revision_metadata_ins
      BEFORE INSERT ON financial_analysis_result_revision_metadata FOR EACH ROW EXECUTE FUNCTION tr46g_validate_revision_insert();
    CREATE TRIGGER trg_tr46g_20_revision_metadata_upd
      BEFORE UPDATE ON financial_analysis_result_revision_metadata FOR EACH ROW EXECUTE FUNCTION tr46g_reject_immutable_mutation();
    CREATE TRIGGER trg_tr46g_20_revision_metadata_del
      BEFORE DELETE ON financial_analysis_result_revision_metadata FOR EACH ROW EXECUTE FUNCTION tr46g_reject_immutable_mutation();

    CREATE TRIGGER trg_tr46g_10_validate_trend_lineage_ins
      BEFORE INSERT ON trend_analysis_lineage FOR EACH ROW EXECUTE FUNCTION tr46g_validate_lineage_insert();
    CREATE TRIGGER trg_tr46g_20_trend_lineage_upd
      BEFORE UPDATE ON trend_analysis_lineage FOR EACH ROW EXECUTE FUNCTION tr46g_reject_immutable_mutation();
    CREATE TRIGGER trg_tr46g_20_trend_lineage_del
      BEFORE DELETE ON trend_analysis_lineage FOR EACH ROW EXECUTE FUNCTION tr46g_reject_immutable_mutation();

    CREATE TRIGGER trg_tr46g_10_validate_trend_owner_ins
      BEFORE INSERT ON financial_analysis_results FOR EACH ROW EXECUTE FUNCTION tr46g_guard_trend_owner_insert();
    CREATE TRIGGER trg_tr46g_20_protected_result_upd
      BEFORE UPDATE ON financial_analysis_results FOR EACH ROW EXECUTE FUNCTION tr46g_guard_protected_result_mutation();
    CREATE TRIGGER trg_tr46g_20_protected_result_del
      BEFORE DELETE ON financial_analysis_results FOR EACH ROW EXECUTE FUNCTION tr46g_guard_protected_result_mutation();
    CREATE CONSTRAINT TRIGGER trg_tr46g_90_trend_owner_complete
      AFTER INSERT ON financial_analysis_results DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION tr46g_require_complete_owner();
    """)


def downgrade() -> None:
    bind = op.get_bind()
    blocked = bind.scalar(sa.text("""
        SELECT
          (SELECT count(*) FROM financial_analysis_results WHERE analysis_type='multi_period_trend')
        + (SELECT count(*) FROM trend_analysis_lineage)
        + (SELECT count(*) FROM financial_analysis_result_revision_metadata
           WHERE restatement_state<>'UNDECLARED_LEGACY' OR restatement_revision<>0
              OR restatement_reason<>'LEGACY_UNDECLARED' OR supersedes_analysis_result_id IS NOT NULL)
    """))
    if blocked:
        raise RuntimeError("Multi-period trend durable state prevents safe downgrade.")

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

    for trigger, table in (
        ("trg_tr46g_90_trend_owner_complete", "financial_analysis_results"),
        ("trg_tr46g_20_protected_result_del", "financial_analysis_results"),
        ("trg_tr46g_20_protected_result_upd", "financial_analysis_results"),
        ("trg_tr46g_10_validate_trend_owner_ins", "financial_analysis_results"),
        ("trg_tr46g_20_trend_lineage_del", "trend_analysis_lineage"),
        ("trg_tr46g_20_trend_lineage_upd", "trend_analysis_lineage"),
        ("trg_tr46g_10_validate_trend_lineage_ins", "trend_analysis_lineage"),
        ("trg_tr46g_20_revision_metadata_del", "financial_analysis_result_revision_metadata"),
        ("trg_tr46g_20_revision_metadata_upd", "financial_analysis_result_revision_metadata"),
        ("trg_tr46g_10_validate_revision_metadata_ins", "financial_analysis_result_revision_metadata"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for function in (
        "tr46g_guard_protected_result_mutation",
        "tr46g_require_complete_owner",
        "tr46g_validate_lineage_insert",
        "tr46g_guard_trend_owner_insert",
        "tr46g_reject_immutable_mutation",
        "tr46g_validate_revision_insert",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    op.drop_index("ix_trend_lineage_owner_ordinal", table_name="trend_analysis_lineage")
    op.drop_index("ix_trend_lineage_company_anchor", table_name="trend_analysis_lineage")
    op.drop_index("ix_trend_lineage_source_analysis_result_id", table_name="trend_analysis_lineage")
    op.drop_table("trend_analysis_lineage")
    op.drop_index("ix_far_revision_metadata_supersedes", table_name="financial_analysis_result_revision_metadata")
    op.drop_index("ix_far_revision_metadata_scope_state_revision", table_name="financial_analysis_result_revision_metadata")
    op.drop_table("financial_analysis_result_revision_metadata")

    op.drop_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_financial_analysis_results_analysis_type",
        "financial_analysis_results",
        _analysis_type_constraint(LEGACY_ANALYSIS_TYPES),
    )
