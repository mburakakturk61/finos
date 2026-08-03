"""Real PostgreSQL integration/concurrency tests for Milestone 4.5C."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.engines.cash_flow import (
    CASH_FLOW_REQUIRED_SOURCE_ROLES_V1,
    CashFlowAccountingBasisCode,
    CashFlowInputResolutionStatus,
    CashFlowMultiPeriodInputResolver,
    CashFlowPeriodResolutionRequest,
)
from app.integrations.cash_flow_period_repository import SqlAlchemyComparablePeriodRepository
from app.engines.cash_flow.policy import CashFlowPresentationProfile
from app.engines.cash_flow.types import CashFlowErrorCode
from app.models.company import Company
from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    PeriodCoverageKind,
    PeriodStatus,
    PeriodType,
    SourceMode,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_period import FinancialPeriod
from app.models.security import SecurityTenant


DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL URL required")


@pytest.fixture(scope="module", autouse=True)
def _upgrade_head():
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture()
def database():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    with sessions.begin() as session:
        session.add(SecurityTenant(
            id=tenant_id,
            tenant_key=f"cf-{tenant_id.hex[:20]}",
            status="ACTIVE",
            policy_version=1,
            version=1,
        ))
        session.flush()
        session.add(Company(
            id=company_id,
            tenant_id=tenant_id,
            legal_name="Cash Flow 4.5C Test",
            tax_number=f"CF45C-{company_id.hex[:20]}",
            currency="TRY",
        ))
    yield engine, sessions, tenant_id, company_id
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM financial_analysis_results WHERE company_id=:id"), {"id": company_id})
        connection.execute(text("DELETE FROM financial_periods WHERE company_id=:id"), {"id": company_id})
        connection.execute(text("DELETE FROM companies WHERE id=:id"), {"id": company_id})
        connection.execute(text("DELETE FROM security_tenants WHERE id=:id"), {"id": tenant_id})
    engine.dispose()


def _period(
    company_id,
    *,
    period_id=None,
    year=2023,
    period_type=PeriodType.YEAR_END,
    number=4,
    start=date(2023, 1, 1),
    end=date(2023, 12, 31),
    annual_start=None,
    annual_end=None,
    months=12,
    coverage=PeriodCoverageKind.CUMULATIVE,
    metadata=True,
    status=PeriodStatus.CLOSED,
):
    values = dict(
        id=period_id or uuid.uuid4(),
        company_id=company_id,
        year=year,
        period_type=period_type,
        period_number=number,
        start_date=start,
        end_date=end,
        months_covered=months,
        is_year_end=period_type is PeriodType.YEAR_END,
        status=status,
    )
    if metadata:
        values.update(
            accounting_basis_code="tr_tdhp_accrual",
            accounting_policy_version="tr_tdhp_accrual/1.0.0",
            annual_reporting_period_start_date=annual_start or start,
            annual_reporting_period_end_date=annual_end or end,
            ifrs18_early_adopted=False,
            cash_flow_coverage_kind=coverage,
        )
    return FinancialPeriod(**values)


def _analysis(company_id, period_id, analysis_type, *, status=AnalysisStatus.COMPLETED):
    now = datetime.now(timezone.utc)
    return FinancialAnalysisResult(
        id=uuid.uuid4(),
        company_id=company_id,
        period_id=period_id,
        document_id=None,
        analysis_type=analysis_type,
        engine_version="1.0.0",
        status=status,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED,
        started_at=now,
        completed_at=now if status is AnalysisStatus.COMPLETED else None,
        result_json={"analysis_type": analysis_type.value} if status is AnalysisStatus.COMPLETED else None,
        error_message=None if status is AnalysisStatus.COMPLETED else "safe failure",
    )


def _seed_annual(sessions, company_id, *, metadata=True):
    prior = _period(company_id, metadata=metadata)
    current = _period(
        company_id,
        year=2024,
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        metadata=metadata,
    )
    with sessions.begin() as session:
        session.add_all((prior, current))
        if metadata:
            session.flush()
            session.add_all((
                _analysis(company_id, current.id, AnalysisType.BALANCE_SHEET),
                _analysis(company_id, current.id, AnalysisType.INCOME_STATEMENT),
                _analysis(company_id, current.id, AnalysisType.TRIAL_BALANCE),
                _analysis(company_id, prior.id, AnalysisType.BALANCE_SHEET),
                _analysis(company_id, prior.id, AnalysisType.TRIAL_BALANCE),
            ))
    return prior, current


def _request(tenant_id, company_id, current_id, *, explicit=None):
    return CashFlowPeriodResolutionRequest(
        tenant_id=tenant_id,
        company_id=company_id,
        current_period_id=current_id,
        required_source_roles=CASH_FLOW_REQUIRED_SOURCE_ROLES_V1,
        expected_currency="TRY",
        expected_accounting_basis=CashFlowAccountingBasisCode.TR_TDHP_ACCRUAL,
        expected_accounting_policy_version="tr_tdhp_accrual/1.0.0",
        expected_presentation_profile=CashFlowPresentationProfile.TMS_TFRS_2024_INDIRECT_V1,
        expected_mapping_registry_version="1.0.0",
        correlation_id="cf-pg-integration",
        resolved_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        explicit_prior_period_id=explicit,
    )


def _resolver(sessions, **kwargs):
    return CashFlowMultiPeriodInputResolver(SqlAlchemyComparablePeriodRepository(sessions, **kwargs))


def test_postgres_valid_annual_and_explicit_resolution(database):
    _engine, sessions, tenant_id, company_id = database
    prior, current = _seed_annual(sessions, company_id)
    request = _request(tenant_id, company_id, current.id, explicit=prior.id)
    first = _resolver(sessions).resolve(request)
    second = _resolver(sessions).resolve(request)
    assert first.success and first.value.status is CashFlowInputResolutionStatus.RESOLVED
    assert first.value == second.value
    assert first.value.prior_period_id == prior.id


def test_postgres_legacy_all_null_metadata_is_not_backfilled(database):
    _engine, sessions, tenant_id, company_id = database
    _prior, current = _seed_annual(sessions, company_id, metadata=False)
    outcome = _resolver(sessions).resolve(_request(tenant_id, company_id, current.id))
    assert outcome.success and outcome.value.status is CashFlowInputResolutionStatus.INSUFFICIENT_DATA
    with sessions() as session:
        stored = session.get(FinancialPeriod, current.id)
        assert stored.accounting_basis_code is None
        assert stored.cash_flow_coverage_kind is None


@pytest.mark.parametrize(
    "partial_values",
    (
        {"accounting_basis_code": "tr_tdhp_accrual"},
        {
            "accounting_basis_code": "unsupported",
            "accounting_policy_version": "unsupported/1.0.0",
            "annual_reporting_period_start_date": date(2024, 1, 1),
            "annual_reporting_period_end_date": date(2024, 12, 31),
            "ifrs18_early_adopted": False,
            "cash_flow_coverage_kind": PeriodCoverageKind.CUMULATIVE,
        },
    ),
)
def test_postgres_invalid_period_metadata_insert_is_rejected(database, partial_values):
    _engine, sessions, _tenant_id, company_id = database
    row = _period(company_id, year=2024, start=date(2024, 1, 1), end=date(2024, 12, 31), metadata=False)
    for name, value in partial_values.items():
        setattr(row, name, value)
    with pytest.raises(IntegrityError):
        with sessions.begin() as session:
            session.add(row)


def test_postgres_exact_constraint_and_trigger_catalog(database):
    engine, _sessions, _tenant_id, _company_id = database
    with engine.connect() as connection:
        checks = set(connection.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conrelid='financial_periods'::regclass AND contype='c'
        """)).scalars())
        triggers = set(connection.execute(text("""
            SELECT tgname FROM pg_trigger
            WHERE tgrelid='financial_periods'::regclass AND NOT tgisinternal
        """)).scalars())
    assert {
        "ck_financial_periods_cf_policy_all_null_or_set",
        "ck_financial_periods_cf_supported_basis_policy",
        "ck_financial_periods_cf_annual_containment",
        "ck_financial_periods_cf_coverage_kind",
        "ck_financial_periods_cash_flow_coverage_kind",
    }.issubset(checks)
    assert {
        "trg_cf_00_namespace_financial_periods_ins",
        "trg_cf_00_namespace_financial_periods_upd",
        "trg_cf_00_namespace_financial_periods_del",
    }.issubset(triggers)


def test_postgres_source_digest_corruption_fails_closed(database):
    engine, sessions, tenant_id, company_id = database
    _prior, current = _seed_annual(sessions, company_id)
    with engine.begin() as connection:
        connection.execute(text("""
            DELETE FROM financial_analysis_results
            WHERE company_id=:company AND period_id=:period
              AND analysis_type='balance_sheet'
        """), {"company": company_id, "period": current.id})
        connection.execute(text("""
            INSERT INTO financial_analysis_results (
                id, company_id, period_id, document_id, analysis_type,
                engine_version, status, source_mode, result_json,
                canonical_result_digest, error_message, started_at, completed_at
            ) VALUES (
                :id, :company, :period, NULL, 'balance_sheet',
                '1.0.0', 'completed', 'multi_source_derived',
                CAST(:payload AS jsonb), :digest, NULL, now(), now()
            )
        """), {
            "id": uuid.uuid4(),
            "company": company_id,
            "period": current.id,
            "payload": '{"analysis_type":"balance_sheet"}',
            "digest": "f" * 64,
        })
    outcome = _resolver(sessions).resolve(_request(tenant_id, company_id, current.id))
    assert outcome.error.code is CashFlowErrorCode.SOURCE_DIGEST_MISMATCH


def test_postgres_duplicate_source_role_fails_closed(database):
    _engine, sessions, tenant_id, company_id = database
    _prior, current = _seed_annual(sessions, company_id)
    with sessions.begin() as session:
        session.add(_analysis(company_id, current.id, AnalysisType.BALANCE_SHEET))
    outcome = _resolver(sessions).resolve(_request(tenant_id, company_id, current.id))
    assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT


def test_concurrent_identical_resolution_returns_same_result(database):
    _engine, sessions, tenant_id, company_id = database
    _prior, current = _seed_annual(sessions, company_id)
    request = _request(tenant_id, company_id, current.id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _item: _resolver(sessions).resolve(request), range(2)))
    assert all(outcome.success for outcome in outcomes)
    assert outcomes[0].value == outcomes[1].value


def test_company_namespace_lock_timeout_is_fail_closed(database):
    engine, sessions, tenant_id, company_id = database
    _prior, current = _seed_annual(sessions, company_id)
    blocker = engine.connect()
    transaction = blocker.begin()
    blocker.execute(select(Company).where(Company.id == company_id).with_for_update())
    try:
        outcome = _resolver(
            sessions,
            statement_timeout_seconds=0.3,
            lock_timeout_seconds=0.1,
        ).resolve(_request(tenant_id, company_id, current.id))
        assert outcome.error.code is CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE
        assert outcome.error.retryable is True
    finally:
        transaction.rollback()
        blocker.close()


def test_period_insert_trigger_rejects_phantom_while_company_locked(database):
    engine, sessions, _tenant_id, company_id = database
    _prior, _current = _seed_annual(sessions, company_id)
    blocker = engine.connect()
    transaction = blocker.begin()
    blocker.execute(select(Company).where(Company.id == company_id).with_for_update())
    try:
        with pytest.raises(DBAPIError) as exc_info:
            with sessions.begin() as session:
                session.add(_period(
                    company_id,
                    year=2022,
                    start=date(2022, 1, 1),
                    end=date(2022, 12, 31),
                ))
        assert getattr(exc_info.value.orig, "sqlstate", None) == "55P03"
    finally:
        transaction.rollback()
        blocker.close()


def test_namespace_lock_rejects_concurrent_source_candidate_insertion(database):
    _engine, sessions, tenant_id, company_id = database
    _prior, current = _seed_annual(sessions, company_id)

    class RacingRepository(SqlAlchemyComparablePeriodRepository):
        inserted = False

        def _before_terminal_requery(self, _session, _request):
            if not self.inserted:
                with sessions.begin() as writer:
                    writer.add(_analysis(company_id, current.id, AnalysisType.BALANCE_SHEET))
                self.inserted = True

    outcome = CashFlowMultiPeriodInputResolver(RacingRepository(sessions)).resolve(
        _request(tenant_id, company_id, current.id)
    )
    assert outcome.error.code is CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE
    assert outcome.error.retryable is True


def test_cross_company_candidate_is_invisible(database):
    engine, sessions, tenant_id, company_id = database
    _prior, current = _seed_annual(sessions, company_id)
    other_tenant, other_company = uuid.uuid4(), uuid.uuid4()
    with sessions.begin() as session:
        session.add(SecurityTenant(id=other_tenant, tenant_key=f"cf-{other_tenant.hex[:20]}", status="ACTIVE", policy_version=1, version=1))
        session.flush()
        session.add(Company(id=other_company, tenant_id=other_tenant, legal_name="Other", tax_number=f"CF45C-{other_company.hex[:20]}", currency="TRY"))
        session.flush()
        session.add(_period(other_company, year=2023))
    try:
        outcome = _resolver(sessions).resolve(_request(tenant_id, company_id, current.id))
        assert outcome.success and outcome.value.status is CashFlowInputResolutionStatus.RESOLVED
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM financial_periods WHERE company_id=:id"), {"id": other_company})
            connection.execute(text("DELETE FROM companies WHERE id=:id"), {"id": other_company})
            connection.execute(text("DELETE FROM security_tenants WHERE id=:id"), {"id": other_tenant})
