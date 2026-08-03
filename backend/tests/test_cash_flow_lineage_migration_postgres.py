"""Migration and catalog acceptance for Milestone 4.5F."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


REVISION = "d7e9a4c6f205"
MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_cash_flow_cross_period_lineage.py"


def _database():
    original_url = get_settings().database_url
    base_url = make_url(original_url)
    name = f"finos_cf45f_migration_{uuid4().hex}"
    url = base_url.set(database=name)
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    return original_url, name, url, admin, config


def _drop(original_url, name, admin, engine=None):
    if engine is not None:
        engine.dispose()
    os.environ["DATABASE_URL"] = original_url
    get_settings.cache_clear()
    with admin.connect() as connection:
        connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"), {"name": name})
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


def test_migration_is_self_contained_and_repository_has_one_head():
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    modules = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "app" not in modules
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [REVISION]


def test_exact_catalog_and_empty_upgrade_downgrade_upgrade_cycle():
    original, name, url, admin, config = _database()
    engine = None
    try:
        command.upgrade(config, "head")
        engine = create_engine(url)
        inspector = inspect(engine)
        assert {column["name"] for column in inspector.get_columns("cash_flow_cross_period_lineage")} == {
            "id", "cash_flow_analysis_result_id", "tenant_id", "company_id",
            "current_period_id", "prior_period_id", "source_period_id",
            "source_analysis_result_id", "source_role", "source_canonical_digest",
            "source_provenance_digest", "source_analysis_type", "source_engine_version",
            "current_period_descriptor_digest", "prior_period_descriptor_digest",
            "comparability_proof_digest", "lineage_schema_version",
            "lineage_policy_version", "created_at",
        }
        assert {item["name"] for item in inspector.get_unique_constraints("cash_flow_cross_period_lineage")} == {
            "uq_cf_lineage_owner_role", "uq_cf_lineage_owner_source"
        }
        assert "ix_cf_lineage_source_analysis_result_id" in {
            item["name"] for item in inspector.get_indexes("cash_flow_cross_period_lineage")
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            triggers = set(connection.scalars(text("""
                SELECT tgname FROM pg_trigger
                WHERE tgrelid='cash_flow_cross_period_lineage'::regclass AND NOT tgisinternal
            """)))
            assert triggers == {
                "trg_cf_00_namespace_cash_flow_cross_period_lineage_ins",
                "trg_cf_10_validate_cash_flow_cross_period_lineage_ins",
                "trg_cf_20_guard_cash_flow_cross_period_lineage_upd",
                "trg_cf_20_guard_cash_flow_cross_period_lineage_del",
            }
        command.downgrade(config, "c4f7a9d2e103")
        assert "cash_flow_cross_period_lineage" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
    finally:
        _drop(original, name, admin, engine)


def test_downgrade_with_cash_flow_owner_is_fail_safe():
    original, name, url, admin, config = _database()
    engine = None
    try:
        command.upgrade(config, "head")
        engine = create_engine(url)
        tenant, company, period, owner, run = (uuid4() for _ in range(5))
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO security_tenants (id,tenant_key,status,policy_version,version) VALUES (:id,:key,'ACTIVE',1,1)"), {"id": tenant, "key": f"cf-{tenant.hex[:20]}"})
            connection.execute(text("INSERT INTO companies (id,tenant_id,legal_name,tax_number,currency) VALUES (:id,:tenant,'4.5F downgrade',:tax,'TRY')"), {"id": company, "tenant": tenant, "tax": company.hex})
            connection.execute(text("""
                INSERT INTO financial_periods (
                    id,company_id,year,period_type,period_number,start_date,end_date,
                    months_covered,is_year_end,status,accounting_basis_code,
                    accounting_policy_version,annual_reporting_period_start_date,
                    annual_reporting_period_end_date,ifrs18_early_adopted,cash_flow_coverage_kind
                ) VALUES (:id,:company,2025,'year_end',4,'2025-01-01','2025-12-31',12,true,'closed',
                    'tr_tdhp_accrual','tr_tdhp_accrual/1.0.0','2025-01-01','2025-12-31',false,'cumulative')
            """), {"id": period, "company": company})
            connection.execute(text("""
                INSERT INTO financial_analysis_results (
                    id,company_id,period_id,document_id,source_mode,analysis_type,engine_version,
                    status,result_json,canonical_result_digest,error_message,started_at,completed_at
                ) VALUES (:id,:company,:period,NULL,'multi_source_derived','cash_flow','1.0.0',
                    'completed','{"status":"insufficient_data"}'::jsonb,:digest,NULL,:now,:now)
            """), {"id": owner, "company": company, "period": period, "digest": "a" * 64, "now": now})
            connection.execute(text("""
                INSERT INTO orchestration_runs (
                    id,run_id,company_id,period_id,request_fingerprint,terminal_content_digest,
                    requested_outputs_json,warnings_json,input_version_inventory_json,status,
                    orchestration_schema_version,orchestration_model_version,execution_plan_version,
                    fingerprint_schema_version,finalized_at
                ) VALUES (:id,:run_id,:company,:period,:request,:terminal,'["cash_flow"]','[]','{}',
                    'completed_with_degradations','3.0.0','3.0.0','3.0.0','1.0.0',:now)
            """), {"id": run, "run_id": f"cf-{run}", "company": company, "period": period, "request": "b" * 64, "terminal": "c" * 64, "now": now})
            connection.execute(text("""
                INSERT INTO orchestration_engine_executions (
                    id,run_id,engine_code,execution_ordinal,status,inner_status,
                    dependency_engine_codes_json,engine_schema_version,engine_model_version,
                    input_fingerprint,fingerprint_schema_version,result_kind,owner_content_digest,
                    financial_analysis_result_id
                ) VALUES (:id,:run,'cash_flow',0,'degraded','insufficient_data','[]','1.0.0','1.0.0',
                    :fingerprint,'1.0.0','CashFlowResult',:owner_digest,:owner)
            """), {"id": uuid4(), "run": run, "fingerprint": "d" * 64, "owner_digest": "e" * 64, "owner": owner})
        with pytest.raises(RuntimeError, match="must be empty before downgrade"):
            command.downgrade(config, "c4f7a9d2e103")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
    finally:
        _drop(original, name, admin, engine)

