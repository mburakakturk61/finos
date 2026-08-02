from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.security.contracts import ProvisioningAuthority
from app.security.historical_binding import (
    HistoricalTenantBindingCommand,
    HistoricalTenantBindingConflict,
    SqlAlchemyHistoricalTenantBindingService,
)


class _Audit:
    def record_required_event(self, _event): return "e2-audit-receipt"
    def readiness_check(self, _deadline): return True


def _config(url):
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    return config


@pytest.fixture()
def isolated_database():
    original = get_settings().database_url
    base = make_url(original)
    name = "finos_e2_" + uuid.uuid4().hex
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    isolated_url = base.set(database=name)
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield isolated_url
    finally:
        os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"
            ), {"name": name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def _legacy_rows(engine, *, tenant_key=None):
    company_id, period_id, claim_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO companies (id,legal_name,tax_number,currency)
            VALUES (:id,'Legacy',:tax,'TRY')
        """), {"id": company_id, "tax": uuid.uuid4().hex})
        connection.execute(text("""
            INSERT INTO financial_periods
                (id,company_id,year,period_type,period_number,start_date,end_date,
                 months_covered,is_year_end,status)
            VALUES (:id,:company,2026,'year_end',1,'2026-01-01','2026-12-31',12,true,'draft')
        """), {"id": period_id, "company": company_id})
        connection.execute(text("""
            INSERT INTO analysis_run_scope_claims
                (claim_id,run_id,company_id,financial_period_id,tenant_id,
                 initiating_subject_id,operation_kind,original_operation,
                 application_command_digest,status,version,claim_token)
            VALUES (:id,:run,:company,:period,:tenant,'subject','START','START',
                    :digest,'CLAIMED',1,:token)
        """), {
            "id": claim_id, "run": "run-" + uuid.uuid4().hex,
            "company": company_id, "period": period_id, "tenant": tenant_key,
            "digest": "a" * 64, "token": "b" * 64,
        })
    return company_id, claim_id


def test_e2_rejects_unknown_or_noncanonical_historical_claim(isolated_database):
    config = _config(isolated_database)
    command.upgrade(config, "a1e5f0c7d901")
    engine = create_engine(isolated_database)
    _legacy_rows(engine, tenant_key="unknown-tenant")
    with pytest.raises(RuntimeError):
        command.upgrade(config, "b2e5f0c7d902")
    engine.dispose()


def test_explicit_binding_then_e2_enforces_fk_nonnull_immutability_and_cycle(isolated_database):
    config = _config(isolated_database)
    command.upgrade(config, "a1e5f0c7d901")
    engine = create_engine(isolated_database)
    tenant_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO security_tenants (id,tenant_key,status,policy_version,version)
            VALUES (:id,'tenant-one','ACTIVE',1,1)
        """), {"id": tenant_id})
    company_id, claim_id = _legacy_rows(engine, tenant_key=None)
    sessions = sessionmaker(engine, expire_on_commit=False)
    service = SqlAlchemyHistoricalTenantBindingService(sessions, _Audit())
    authority = ProvisioningAuthority(
        "platform-e2", "PLATFORM", None, None,
        AuthenticationStrength.PHISHING_RESISTANT,
    )
    binding = HistoricalTenantBindingCommand(
        authority, "historical-bind-1001", "tenant-one", (company_id,), (),
        (claim_id,), datetime.now(timezone.utc), "corr-e2",
    )
    first = service.bind(binding)
    second = service.bind(binding)
    assert first.bound_company_count == 1 and first.bound_run_claim_count == 1
    assert second.idempotent_replay
    with pytest.raises(HistoricalTenantBindingConflict):
        service.bind(HistoricalTenantBindingCommand(
            authority, binding.idempotency_key, "tenant-one", (), (), (),
            binding.requested_at, binding.correlation_id,
        ))

    command.upgrade(config, "b2e5f0c7d902")
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "b2e5f0c7d902"
        assert connection.scalar(text("SELECT tenant_id FROM companies WHERE id=:id"), {"id": company_id}) == tenant_id
        assert connection.scalar(text("SELECT tenant_id FROM analysis_run_scope_claims WHERE claim_id=:id"), {"id": claim_id}) == "tenant-one"

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(Exception):
            connection.execute(text("""
                INSERT INTO companies (id,legal_name,tax_number,currency)
                VALUES (:id,'Missing tenant',:tax,'TRY')
            """), {"id": uuid.uuid4(), "tax": uuid.uuid4().hex})
        transaction.rollback()

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(Exception):
            connection.execute(text(
                "UPDATE companies SET tenant_id=:other WHERE id=:id"
            ), {"other": uuid.uuid4(), "id": company_id})
        transaction.rollback()

    command.downgrade(config, "a1e5f0c7d901")
    command.upgrade(config, "b2e5f0c7d902")
    engine.dispose()


def test_e2_quarantines_unbound_historical_rows(isolated_database):
    config = _config(isolated_database)
    command.upgrade(config, "a1e5f0c7d901")
    engine = create_engine(isolated_database)
    company_id, claim_id = _legacy_rows(engine, tenant_key=None)
    command.upgrade(config, "b2e5f0c7d902")
    with engine.connect() as connection:
        quarantined = set(connection.execute(text("""
            SELECT resource_type,resource_id FROM security_resource_binding_quarantine
        """)))
    assert ("COMPANY", company_id) in quarantined
    assert ("ANALYSIS_RUN_SCOPE_CLAIM", claim_id) in quarantined
    engine.dispose()
