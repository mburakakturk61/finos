"""Migration and catalog acceptance for Milestone 4.6G."""

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


REVISION = "e8f1b6d3a704"
PREVIOUS = "d7e9a4c6f205"
MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_multi_period_trend_lineage.py"


def _database():
    original_url = get_settings().database_url
    base_url = make_url(original_url)
    name = f"finos_tr46g_migration_{uuid4().hex}"
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


def _scope(connection):
    tenant, company = uuid4(), uuid4()
    periods = tuple(uuid4() for _ in range(3))
    connection.execute(text(
        "INSERT INTO security_tenants (id,tenant_key,status,policy_version,version) VALUES (:id,:key,'ACTIVE',1,1)"
    ), {"id": tenant, "key": f"trend-{tenant.hex[:20]}"})
    connection.execute(text(
        "INSERT INTO companies (id,tenant_id,legal_name,tax_number,currency) VALUES (:id,:tenant,'4.6G migration',:tax,'TRY')"
    ), {"id": company, "tenant": tenant, "tax": company.hex})
    for index, period in enumerate(periods):
        year = 2023 + index
        connection.execute(text("""
            INSERT INTO financial_periods (
              id,company_id,year,period_type,period_number,start_date,end_date,
              months_covered,is_year_end,status,accounting_basis_code,
              accounting_policy_version,annual_reporting_period_start_date,
              annual_reporting_period_end_date,ifrs18_early_adopted,cash_flow_coverage_kind
            ) VALUES (:id,:company,:year,'year_end',4,:start,:end,12,true,'closed',
              'tr_tdhp_accrual','tr_tdhp_accrual/1.0.0',:start,:end,false,'cumulative')
        """), {
            "id": period, "company": company, "year": year,
            "start": f"{year}-01-01", "end": f"{year}-12-31",
        })
    return tenant, company, periods


def _insert_source(connection, company, period, digest):
    source = uuid4()
    now = datetime.now(timezone.utc)
    connection.execute(text("""
        INSERT INTO financial_analysis_results (
          id,company_id,period_id,document_id,source_mode,analysis_type,engine_version,
          status,result_json,canonical_result_digest,error_message,started_at,completed_at
        ) VALUES (:id,:company,:period,NULL,'multi_source_derived','balance_sheet','1.0.0',
          'completed','{"source":"fixture"}'::jsonb,:digest,NULL,:now,:now)
    """), {"id": source, "company": company, "period": period, "digest": digest, "now": now})
    return source


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
        assert {column["name"] for column in inspector.get_columns("trend_analysis_lineage")} == {
            "id", "trend_analysis_result_id", "tenant_id", "company_id", "anchor_period_id",
            "ordinal", "source_period_id", "source_analysis_result_id", "source_role",
            "source_engine_code", "source_analysis_type", "source_canonical_digest",
            "source_schema_version", "source_model_version", "observation_evidence",
            "comparability_proof_digest", "resolution_proof_reference", "source_set_digest",
            "lineage_schema_version", "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("financial_analysis_result_revision_metadata")} == {
            "analysis_result_id", "tenant_id", "company_id", "period_id", "restatement_state",
            "restatement_revision", "restatement_reason", "supersedes_analysis_result_id",
            "metadata_schema_version", "created_at",
        }
        assert {item["name"] for item in inspector.get_unique_constraints("trend_analysis_lineage")} == {
            "uq_trend_lineage_owner_ordinal_role",
            "uq_trend_lineage_owner_period_role",
            "uq_trend_lineage_owner_source",
        }
        assert {item["name"] for item in inspector.get_indexes("trend_analysis_lineage") if not item.get("unique")} == {
            "ix_trend_lineage_source_analysis_result_id",
            "ix_trend_lineage_company_anchor",
            "ix_trend_lineage_owner_ordinal",
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            triggers = set(connection.scalars(text("""
                SELECT tgname FROM pg_trigger
                WHERE tgrelid='trend_analysis_lineage'::regclass AND NOT tgisinternal
            """)))
            assert triggers == {
                "trg_tr46g_10_validate_trend_lineage_ins",
                "trg_tr46g_20_trend_lineage_upd",
                "trg_tr46g_20_trend_lineage_del",
            }
            analysis_check = connection.scalar(text("""
                SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conrelid='financial_analysis_results'::regclass
                  AND contype='c'
                  AND pg_get_constraintdef(oid) LIKE '%analysis_type%'
                  AND pg_get_constraintdef(oid) LIKE '%multi_period_trend%'
            """))
            assert "multi_period_trend" in analysis_check
        command.downgrade(config, PREVIOUS)
        assert "trend_analysis_lineage" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
    finally:
        _drop(original, name, admin, engine)


def test_populated_trend_downgrade_is_fail_safe_and_rows_are_immutable():
    original, name, url, admin, config = _database()
    engine = None
    try:
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.begin() as connection:
            tenant, company, periods = _scope(connection)
            sources = (
                _insert_source(connection, company, periods[0], "1" * 64),
                _insert_source(connection, company, periods[2], "2" * 64),
            )
            owner = uuid4()
            now = datetime.now(timezone.utc)
            payload = (
                '{"contract_version":"1.0.0","lineage_count":2,'
                '"metric_registry_digest":"' + "a" * 64 + '",'
                '"metric_registry_version":"trend-metric-registry/1.0.0",'
                '"policy_version":"trend-accounting-policy/1.0.0",'
                '"source_set_digest":"' + "b" * 64 + '"}'
            )
            connection.execute(text("""
                INSERT INTO financial_analysis_results (
                  id,company_id,period_id,document_id,source_mode,analysis_type,engine_version,
                  status,result_json,canonical_result_digest,error_message,started_at,completed_at
                ) VALUES (:id,:company,:period,NULL,'multi_source_derived','multi_period_trend','1.0.0',
                  'completed',CAST(:payload AS jsonb),:digest,NULL,:now,:now)
            """), {"id": owner, "company": company, "period": periods[2], "payload": payload, "digest": "c" * 64, "now": now})
            connection.execute(text("""
                INSERT INTO financial_analysis_result_revision_metadata (
                  analysis_result_id,tenant_id,company_id,period_id,restatement_state,
                  restatement_revision,restatement_reason,supersedes_analysis_result_id,metadata_schema_version
                ) VALUES (:owner,:tenant,:company,:period,'ORIGINAL',0,'NONE',NULL,'1.0.0')
            """), {"owner": owner, "tenant": tenant, "company": company, "period": periods[2]})
            for ordinal, (period, source, digest) in enumerate(zip((periods[0], periods[2]), sources, ("1" * 64, "2" * 64))):
                connection.execute(text("""
                    INSERT INTO trend_analysis_lineage (
                      id,trend_analysis_result_id,tenant_id,company_id,anchor_period_id,ordinal,
                      source_period_id,source_analysis_result_id,source_role,source_engine_code,
                      source_analysis_type,source_canonical_digest,source_schema_version,
                      source_model_version,observation_evidence,comparability_proof_digest,
                      resolution_proof_reference,source_set_digest,lineage_schema_version
                    ) VALUES (:id,:owner,:tenant,:company,:anchor,:ordinal,:period,:source,
                      'balance_sheet','fs_balance_sheet','balance_sheet',:source_digest,NULL,'1.0.0',
                      'exact',:proof,:reference,:set_digest,'1.0.0')
                """), {
                    "id": uuid4(), "owner": owner, "tenant": tenant, "company": company,
                    "anchor": periods[2], "ordinal": ordinal, "period": period, "source": source,
                    "source_digest": digest, "proof": f"{ordinal + 3}" * 64,
                    "reference": "trend:v1:sha256:" + f"{ordinal + 5}" * 64,
                    "set_digest": "b" * 64,
                })
        with pytest.raises(Exception):
            with engine.begin() as connection:
                connection.execute(text("UPDATE trend_analysis_lineage SET observation_evidence='derived' WHERE trend_analysis_result_id=:id"), {"id": owner})
        with pytest.raises(Exception):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM trend_analysis_lineage WHERE trend_analysis_result_id=:id"), {"id": owner})
        with pytest.raises(RuntimeError, match="prevents safe downgrade"):
            command.downgrade(config, PREVIOUS)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            assert connection.scalar(text("SELECT count(*) FROM trend_analysis_lineage WHERE trend_analysis_result_id=:id"), {"id": owner}) == 2
    finally:
        _drop(original, name, admin, engine)
