"""Migration-cycle acceptance for Milestone 4.5C period-policy metadata."""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def test_cash_flow_period_metadata_fail_safe_downgrade_and_cycle():
    original_url = get_settings().database_url
    base_url = make_url(original_url)
    database_name = f"finos_cf45c_migration_{uuid.uuid4().hex}"
    isolated_url = base_url.set(database=database_name)
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    try:
        os.environ["DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
        get_settings.cache_clear()
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        command.upgrade(config, "head")
        engine = create_engine(isolated_url)
        tenant_id, company_id, period_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "e8f1b6d3a704"
            connection.execute(text("""
                INSERT INTO security_tenants (id,tenant_key,status,policy_version,version)
                VALUES (:id,:key,'ACTIVE',1,1)
            """), {"id": tenant_id, "key": f"cf-{tenant_id.hex[:20]}"})
            connection.execute(text("""
                INSERT INTO companies (id,tenant_id,legal_name,tax_number,currency)
                VALUES (:id,:tenant,'4.5C migration',:tax,'TRY')
            """), {"id": company_id, "tenant": tenant_id, "tax": company_id.hex[:20]})
            connection.execute(text("""
                INSERT INTO financial_periods (
                    id,company_id,year,period_type,period_number,start_date,end_date,
                    months_covered,is_year_end,status,accounting_basis_code,
                    accounting_policy_version,annual_reporting_period_start_date,
                    annual_reporting_period_end_date,ifrs18_early_adopted,
                    cash_flow_coverage_kind
                ) VALUES (
                    :id,:company,2025,'year_end',4,'2025-01-01','2025-12-31',
                    12,true,'closed','tr_tdhp_accrual','tr_tdhp_accrual/1.0.0',
                    '2025-01-01','2025-12-31',false,'cumulative'
                )
            """), {"id": period_id, "company": company_id})

        with pytest.raises(RuntimeError, match="must be empty before downgrade"):
            command.downgrade(config, "b2e5f0c7d902")

        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE financial_periods SET
                    accounting_basis_code=NULL,
                    accounting_policy_version=NULL,
                    annual_reporting_period_start_date=NULL,
                    annual_reporting_period_end_date=NULL,
                    ifrs18_early_adopted=NULL,
                    cash_flow_coverage_kind=NULL
                WHERE id=:id
            """), {"id": period_id})

        command.downgrade(config, "b2e5f0c7d902")
        assert "accounting_basis_code" not in {
            column["name"] for column in inspect(engine).get_columns("financial_periods")
        }
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "e8f1b6d3a704"
        engine.dispose()
    finally:
        os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()
        with admin_engine.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()
