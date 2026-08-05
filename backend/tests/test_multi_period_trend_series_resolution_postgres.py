from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.engines.analysis_orchestrator_v4 import build_trend_pre_resolved_context_v1
from app.engines.multi_period_trend import (
    TREND_COMPARABILITY_PROFILE_VERSION_V1,
    TREND_METRIC_REGISTRY_V1,
    TrendComparabilityProfile,
    TrendCoverageKind,
    TrendDuplicatePolicy,
    TrendGapPolicy,
    TrendNominalAnalysisProfile,
    TrendOverlapPolicy,
    TrendPeriodFamily,
    TrendRestatementProfile,
    TrendSeriesResolutionErrorCode,
    TrendSeriesResolutionRequest,
    TrendSeriesResolutionStatus,
    TrendSourceSelectionIntent,
    TrendSourceSelectionRole,
    TrendMultiPeriodSeriesResolver,
    canonical_candidate_set_digest,
)
from app.integrations.trend_period_repository import (
    SqlAlchemyTrendSeriesRepository,
    fiscal_calendar_reference,
    trend_company_lock_key,
)
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
from app.models.financial_analysis_result_revision_metadata import FinancialAnalysisResultRevisionMetadata
from app.models.financial_period import FinancialPeriod


@pytest.fixture(scope="module")
def trend_database_server():
    original_url = get_settings().database_url
    base_url = make_url(original_url)
    database_name = f"finos_tr46c_repo_{uuid.uuid4().hex}"
    isolated_url = base_url.set(database=database_name)
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    try:
        os.environ["DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
        get_settings.cache_clear()
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        command.upgrade(config, "head")
        engine = create_engine(isolated_url, pool_size=8, max_overflow=0)
        yield engine, sessionmaker(bind=engine, expire_on_commit=False)
        engine.dispose()
    finally:
        os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin.dispose()


@pytest.fixture
def trend_database(trend_database_server):
    engine, sessions = trend_database_server
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO security_tenants (id,tenant_key,status,policy_version,version) "
            "VALUES (:id,:key,'ACTIVE',1,1)"
        ), {"id": tenant_id, "key": f"trend-{tenant_id.hex}"})
    with sessions.begin() as session:
        session.add(Company(
            id=company_id,
            tenant_id=tenant_id,
            legal_name="Trend 4.6C synthetic",
            tax_number=company_id.hex,
            currency="TRY",
        ))
    yield engine, sessions, tenant_id, company_id


def _period(company_id, index, *, status=PeriodStatus.CLOSED):
    year = 2020 + index
    return FinancialPeriod(
        id=uuid.uuid4(),
        company_id=company_id,
        year=year,
        period_type=PeriodType.YEAR_END,
        period_number=4,
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        months_covered=12,
        is_year_end=True,
        status=status,
        accounting_basis_code="tr_tdhp_accrual",
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        annual_reporting_period_start_date=date(year, 1, 1),
        annual_reporting_period_end_date=date(year, 12, 31),
        ifrs18_early_adopted=False,
        cash_flow_coverage_kind=PeriodCoverageKind.CUMULATIVE,
    )


def _payload(value, *, version="1.0.0"):
    return {
        "engine": "balance_sheet",
        "engine_version": version,
        "analysis_type": "balance_sheet",
        "source_mode": "trial_balance_derived",
        "facts": {"total_assets": str(value)},
    }


def _source(company_id, period_id, value, *, status=AnalysisStatus.COMPLETED, version="1.0.0"):
    now = datetime.now(timezone.utc)
    return FinancialAnalysisResult(
        id=uuid.uuid4(),
        company_id=company_id,
        period_id=period_id,
        document_id=None,
        source_mode=SourceMode.TRIAL_BALANCE_DERIVED,
        analysis_type=AnalysisType.BALANCE_SHEET,
        engine_version=version,
        status=status,
        result_json=_payload(value, version=version) if status is AnalysisStatus.COMPLETED else None,
        error_message=None if status is AnalysisStatus.COMPLETED else "safe failure",
        started_at=now,
        completed_at=now if status is AnalysisStatus.COMPLETED else None,
    )


def _revision_metadata(tenant_id, company_id, source, *, state="ORIGINAL", revision=0, supersedes=None):
    return FinancialAnalysisResultRevisionMetadata(
        analysis_result_id=source.id,
        tenant_id=tenant_id,
        company_id=company_id,
        period_id=source.period_id,
        restatement_state=state,
        restatement_revision=revision,
        restatement_reason="NONE" if state == "ORIGINAL" else "ERROR_CORRECTION",
        supersedes_analysis_result_id=supersedes,
        metadata_schema_version="1.0.0",
    )


def _seed(sessions, tenant_id, company_id, count=3):
    periods = tuple(_period(company_id, index) for index in range(1, count + 1))
    sources = tuple(_source(company_id, period.id, Decimal(index * 100)) for index, period in enumerate(periods, start=1))
    with sessions.begin() as session:
        session.add_all(periods)
        session.flush()
        session.add_all(sources)
        session.flush()
        session.add_all(_revision_metadata(tenant_id, company_id, source) for source in sources)
    return periods, sources


def _request(tenant_id, company_id, periods, sources):
    return TrendSeriesResolutionRequest(
        tenant_id=tenant_id,
        company_id=company_id,
        anchor_period_id=periods[-1].id,
        metric_code="bs.total_assets",
        explicit_period_ids=tuple(period.id for period in periods),
        explicit_sources=tuple(
            TrendSourceSelectionIntent(period.id, TrendSourceSelectionRole.BALANCE_SHEET, source.id)
            for period, source in zip(periods, sources, strict=True)
        ),
        expected_period_family=TrendPeriodFamily.ANNUAL,
        expected_currency="TRY",
        expected_monetary_unit_multiplier=Decimal("1"),
        expected_accounting_basis="tr_tdhp_accrual",
        expected_accounting_policy_version="tr_tdhp_accrual/1.0.0",
        fiscal_calendar_reference=fiscal_calendar_reference(date(2021, 1, 1), date(2021, 12, 31)),
        comparability_profile_version=TREND_COMPARABILITY_PROFILE_VERSION_V1,
        expected_metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        expected_metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        correlation_reference="trend-pg-integration",
        resolution_timestamp=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


def _resolver(sessions, repository_type=SqlAlchemyTrendSeriesRepository, **kwargs):
    return TrendMultiPeriodSeriesResolver(repository_type(sessions, **kwargs))


def test_postgres_explicit_resolution_is_deterministic_and_no_latest_fallback(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id, 5)
    request = _request(tenant_id, company_id, periods, sources)
    first = _resolver(sessions).resolve(request)
    with sessions.begin() as session:
        extra = _source(company_id, periods[-1].id, Decimal("999999"))
        session.add(extra)
        session.flush()
        session.add(_revision_metadata(tenant_id, company_id, extra))
    second = _resolver(sessions).resolve(request)
    assert first.status is TrendSeriesResolutionStatus.RESOLVED
    assert first.series.resolution_digest == second.series.resolution_digest
    assert tuple(item.observation.source_result_id for item in first.series.observations) == tuple(source.id for source in sources)


def test_postgres_input_order_is_semantically_irrelevant(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    normal = _request(tenant_id, company_id, periods, sources)
    reversed_request = _request(tenant_id, company_id, tuple(reversed(periods)), tuple(reversed(sources)))
    reversed_request = replace(reversed_request, anchor_period_id=periods[-1].id)
    first = _resolver(sessions).resolve(normal)
    second = _resolver(sessions).resolve(reversed_request)
    assert first.series.resolution_digest == second.series.resolution_digest


def test_postgres_shared_source_has_metric_independent_comparability_proof(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    total_assets = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, sources))
    equity_request = replace(
        _request(tenant_id, company_id, periods, sources),
        metric_code="bs.equity",
    )
    equity = _resolver(sessions).resolve(equity_request)
    assert tuple(item.comparability_proof_digest for item in total_assets.series.segments) == tuple(
        item.comparability_proof_digest for item in equity.series.segments
    )
    context = build_trend_pre_resolved_context_v1(
        resolved_series=(total_assets.series, equity.series),
        comparability_profile=TrendComparabilityProfile(
            tenant_id=tenant_id,
            company_id=company_id,
            currency="TRY",
            accounting_basis="tr_tdhp_accrual",
            accounting_policy_version="tr_tdhp_accrual/1.0.0",
            fiscal_calendar_reference=fiscal_calendar_reference(
                date(2021, 1, 1), date(2021, 12, 31)
            ),
            period_family=TrendPeriodFamily.ANNUAL,
            coverage_kind=TrendCoverageKind.CUMULATIVE,
            source_schema_version=None,
            source_model_version="1.0.0",
            require_source_digest=True,
            restatement_profile=TrendRestatementProfile.ORIGINAL,
            nominal_analysis_profile=TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT,
            gap_policy=TrendGapPolicy.SEGMENT_WITHOUT_FILL,
            overlap_policy=TrendOverlapPolicy.REJECT,
            duplicate_policy=TrendDuplicatePolicy.REJECT,
        ),
        expected_metric_codes=("bs.total_assets", "bs.equity"),
    )
    assert len(context.lineage) == len(periods)


def test_postgres_missing_and_cross_company_source_are_hidden_as_not_found(trend_database):
    engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    missing = list(sources)
    missing[0] = type("SourceId", (), {"id": uuid.uuid4()})()
    result = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, tuple(missing)))
    assert result.error_code is TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND

    other_company = uuid.uuid4()
    with sessions.begin() as session:
        session.add(Company(id=other_company, tenant_id=tenant_id, legal_name="Other", tax_number=other_company.hex, currency="TRY"))
        other_period = _period(other_company, 1)
        session.add(other_period)
        session.flush()
        foreign = _source(other_company, other_period.id, Decimal("1"))
        session.add(foreign)
        session.flush()
        session.add(_revision_metadata(tenant_id, other_company, foreign))
    claimed = list(sources)
    claimed[0] = foreign
    hidden = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, tuple(claimed)))
    assert hidden.error_code is TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND


@pytest.mark.parametrize(
    "mutation,error",
    (
        ("status", TrendSeriesResolutionErrorCode.SOURCE_STATUS_INVALID),
        ("digest", TrendSeriesResolutionErrorCode.SOURCE_DIGEST_MISMATCH),
        ("version", TrendSeriesResolutionErrorCode.SOURCE_VERSION_UNSUPPORTED),
    ),
)
def test_postgres_source_status_digest_and_version_fail_closed(trend_database, mutation, error):
    engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    selected_sources = sources
    with engine.begin() as connection:
        if mutation == "status":
            connection.execute(update(FinancialAnalysisResult).where(FinancialAnalysisResult.id == sources[0].id).values(status=AnalysisStatus.FAILED))
        elif mutation == "digest":
            bad_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            payload = _payload("100")
            connection.execute(text("""
                INSERT INTO financial_analysis_results
                    (id,company_id,period_id,document_id,source_mode,analysis_type,
                     engine_version,status,result_json,canonical_result_digest,
                     error_message,started_at,completed_at)
                VALUES
                    (:id,:company,:period,NULL,'trial_balance_derived','balance_sheet',
                     '1.0.0','completed',CAST(:payload AS jsonb),:digest,NULL,:now,:now)
            """), {
                "id": bad_id, "company": company_id, "period": periods[0].id,
                "payload": json.dumps(payload), "digest": "f" * 64, "now": now,
            })
            connection.execute(text("""
                INSERT INTO financial_analysis_result_revision_metadata
                    (analysis_result_id,tenant_id,company_id,period_id,restatement_state,
                     restatement_revision,restatement_reason,supersedes_analysis_result_id,
                     metadata_schema_version)
                VALUES (:id,:tenant,:company,:period,'ORIGINAL',0,'NONE',NULL,'1.0.0')
            """), {
                "id": bad_id, "tenant": tenant_id,
                "company": company_id, "period": periods[0].id,
            })
            selected_sources = (SimpleNamespace(id=bad_id),) + sources[1:]
        else:
            connection.execute(update(FinancialAnalysisResult).where(FinancialAnalysisResult.id == sources[0].id).values(engine_version="9.0.0"))
    result = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, selected_sources))
    assert result.status is TrendSeriesResolutionStatus.FAILED
    assert result.error_code is error


def test_postgres_period_status_is_fail_closed(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods = (_period(company_id, 1), _period(company_id, 2, status=PeriodStatus.ACTIVE))
    sources = tuple(_source(company_id, period.id, Decimal("1")) for period in periods)
    with sessions.begin() as session:
        session.add_all(periods)
        session.flush()
        session.add_all(sources)
        session.flush()
        session.add_all(_revision_metadata(tenant_id, company_id, source) for source in sources)
    result = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, sources))
    assert result.error_code is TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD


def test_postgres_missing_revision_metadata_is_integrity_failure(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    missing_metadata_source = _source(company_id, periods[0].id, Decimal("123"))
    with sessions.begin() as session:
        session.add(missing_metadata_source)
    selected = (missing_metadata_source,) + sources[1:]
    result = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, selected))
    assert result.status is TrendSeriesResolutionStatus.FAILED
    assert result.error_code is TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE


def test_postgres_superseded_source_is_rejected_and_chain_head_is_restated(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    replacement = _source(company_id, periods[0].id, Decimal("125"))
    with sessions.begin() as session:
        session.add(replacement)
        session.flush()
        session.add(_revision_metadata(
            tenant_id,
            company_id,
            replacement,
            state="RESTATED",
            revision=1,
            supersedes=sources[0].id,
        ))
    stale = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, sources))
    assert stale.status is TrendSeriesResolutionStatus.FAILED
    assert stale.error_code is TrendSeriesResolutionErrorCode.STALE_RESTATEMENT_SOURCE

    selected = (replacement,) + sources[1:]
    resolved = _resolver(sessions).resolve(_request(tenant_id, company_id, periods, selected))
    assert resolved.status is TrendSeriesResolutionStatus.INSUFFICIENT_FOR_TREND
    assert resolved.series.observations[0].observation.restatement_profile is TrendRestatementProfile.RESTATED


class _MutatingRepository(SqlAlchemyTrendSeriesRepository):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._snapshot_count = 0

    def _snapshot(self, session, request, definition):
        snapshot = super()._snapshot(session, request, definition)
        self._snapshot_count += 1
        if self._snapshot_count == 2:
            changed = replace(
                snapshot.sources[0],
                canonical_digest="e" * 64,
                recomputed_digest="e" * 64,
            )
            sources = (changed,) + snapshot.sources[1:]
            return replace(
                snapshot,
                sources=sources,
                candidate_set_digest=canonical_candidate_set_digest(
                    request, snapshot.periods, sources
                ),
            )
        return snapshot


class _PhantomRepository(SqlAlchemyTrendSeriesRepository):
    def _before_terminal_requery(self, session, request):
        now = datetime.now(timezone.utc)
        payload = _payload("777")
        source = FinancialAnalysisResult(
            id=uuid.uuid4(), company_id=request.company_id,
            period_id=request.explicit_period_ids[0], document_id=None,
            source_mode=SourceMode.TRIAL_BALANCE_DERIVED,
            analysis_type=AnalysisType.BALANCE_SHEET, engine_version="1.0.0",
            status=AnalysisStatus.COMPLETED, result_json=payload,
            started_at=now, completed_at=now,
        )
        session.add(source)
        session.flush()
        session.add(_revision_metadata(request.tenant_id, request.company_id, source))


def test_postgres_terminal_requery_detects_digest_mutation(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    result = _resolver(sessions, _MutatingRepository).resolve(_request(tenant_id, company_id, periods, sources))
    assert result.error_code is TrendSeriesResolutionErrorCode.SOURCE_SET_CHANGED


def test_postgres_phantom_unrequested_source_does_not_change_explicit_set(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    result = _resolver(sessions, _PhantomRepository).resolve(_request(tenant_id, company_id, periods, sources))
    assert result.status is TrendSeriesResolutionStatus.RESOLVED
    assert len(result.series.observations) == 3


def test_postgres_concurrent_identical_resolution_is_deterministic(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    request = _request(tenant_id, company_id, periods, sources)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: _resolver(sessions).resolve(request), range(2)))
    assert all(item.status is TrendSeriesResolutionStatus.RESOLVED for item in results)
    assert len({item.series.resolution_digest for item in results}) == 1


def test_postgres_company_lock_timeout_is_typed(trend_database):
    engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    request = _request(tenant_id, company_id, periods, sources)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": trend_company_lock_key(tenant_id, company_id)})
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(_resolver(sessions, lock_timeout_seconds=0.05).resolve, request).result(timeout=5)
        assert result.error_code is TrendSeriesResolutionErrorCode.STORE_TIMEOUT
    finally:
        transaction.rollback()
        connection.close()


def test_postgres_no_stale_cache_after_authoritative_payload_change(trend_database):
    _engine, sessions, tenant_id, company_id = trend_database
    periods, sources = _seed(sessions, tenant_id, company_id)
    request = _request(tenant_id, company_id, periods, sources)
    first = _resolver(sessions).resolve(request)
    replacement = _source(company_id, periods[0].id, Decimal("888"))
    with sessions.begin() as session:
        session.add(replacement)
        session.flush()
        session.add(_revision_metadata(tenant_id, company_id, replacement))
    replacement_sources = (replacement,) + sources[1:]
    second = _resolver(sessions).resolve(
        _request(tenant_id, company_id, periods, replacement_sources)
    )
    assert second.status is TrendSeriesResolutionStatus.RESOLVED
    assert first.series.resolution_digest != second.series.resolution_digest


def test_postgres_different_company_uses_independent_lock_namespace(trend_database):
    engine, sessions, tenant_id, company_id = trend_database
    _periods, _sources = _seed(sessions, tenant_id, company_id)
    other_company = uuid.uuid4()
    with sessions.begin() as session:
        session.add(Company(id=other_company, tenant_id=tenant_id, legal_name="Other lock", tax_number=other_company.hex, currency="TRY"))
    periods, sources = _seed(sessions, tenant_id, other_company)
    request = _request(tenant_id, other_company, periods, sources)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": trend_company_lock_key(tenant_id, company_id)})
        result = _resolver(sessions, lock_timeout_seconds=0.05).resolve(request)
        assert result.status is TrendSeriesResolutionStatus.RESOLVED
    finally:
        transaction.rollback()
        connection.close()
