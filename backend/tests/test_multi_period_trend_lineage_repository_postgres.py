"""PostgreSQL acceptance for immutable Multi-Period Trend lineage persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
import os
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    TrendContractVersion,
    TrendEvidenceLevel,
    TrendLineageEdge,
    TrendLineagePortError,
    TrendLineagePortErrorCode,
    TrendLineageSourceAnalysisType,
    TrendLineageSourceEngineCode,
    TrendLineageSourceRole,
    TrendPolicyVersion,
    build_trend_lineage_set,
)
from app.integrations.trend_lineage_repository import SqlAlchemyTrendLineageRepository
from app.integrations.trend_period_repository import trend_company_lock_key
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
from app.models.trend_analysis_lineage import TrendAnalysisLineage


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
ROLE_BINDINGS = {
    TrendLineageSourceRole.BALANCE_SHEET: (
        TrendLineageSourceEngineCode.FS_BALANCE_SHEET,
        TrendLineageSourceAnalysisType.BALANCE_SHEET,
        AnalysisType.BALANCE_SHEET,
        None,
        "1.0.0",
    ),
    TrendLineageSourceRole.INCOME_STATEMENT: (
        TrendLineageSourceEngineCode.FS_INCOME_STATEMENT,
        TrendLineageSourceAnalysisType.INCOME_STATEMENT,
        AnalysisType.INCOME_STATEMENT,
        None,
        "1.0.0",
    ),
    TrendLineageSourceRole.CASH_FLOW: (
        TrendLineageSourceEngineCode.CASH_FLOW,
        TrendLineageSourceAnalysisType.CASH_FLOW,
        AnalysisType.CASH_FLOW,
        "1.0.0",
        "1.0.0",
    ),
    TrendLineageSourceRole.FINANCIAL_RATIOS: (
        TrendLineageSourceEngineCode.RATIO,
        TrendLineageSourceAnalysisType.FINANCIAL_RATIOS,
        AnalysisType.FINANCIAL_RATIOS,
        "1.0",
        "1.1.0",
    ),
}


@pytest.fixture(scope="module")
def trend_lineage_database():
    original_url = get_settings().database_url
    base_url = make_url(original_url)
    database_name = f"finos_tr46g_repo_{uuid4().hex}"
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
        engine = create_engine(isolated_url, pool_size=12, max_overflow=0)
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


def _create_scope(factory, count: int = 3):
    tenant_id, company_id = uuid4(), uuid4()
    periods = tuple(uuid4() for _ in range(count))
    with factory() as session, session.begin():
        session.execute(
            text(
                "INSERT INTO security_tenants "
                "(id,tenant_key,status,policy_version,version) "
                "VALUES (:id,:key,'ACTIVE',1,1)"
            ),
            {"id": tenant_id, "key": f"tr46g-{tenant_id.hex[:20]}"},
        )
        session.add(
            Company(
                id=company_id,
                tenant_id=tenant_id,
                legal_name="4.6G trend lineage synthetic",
                tax_number=company_id.hex,
                currency="TRY",
            )
        )
        for index, period_id in enumerate(periods):
            year = 2020 + index
            session.add(
                FinancialPeriod(
                    id=period_id,
                    company_id=company_id,
                    year=year,
                    period_type=PeriodType.YEAR_END,
                    period_number=4,
                    start_date=date(year, 1, 1),
                    end_date=date(year, 12, 31),
                    months_covered=12,
                    is_year_end=True,
                    status=PeriodStatus.CLOSED,
                    accounting_basis_code="tr_tdhp_accrual",
                    accounting_policy_version="tr_tdhp_accrual/1.0.0",
                    annual_reporting_period_start_date=date(year, 1, 1),
                    annual_reporting_period_end_date=date(year, 12, 31),
                    ifrs18_early_adopted=False,
                    cash_flow_coverage_kind=PeriodCoverageKind.CUMULATIVE,
                )
            )
    return tenant_id, company_id, periods


def _sources(factory, scope, roles=(TrendLineageSourceRole.BALANCE_SHEET,), *, metadata=True):
    tenant_id, company_id, periods = scope
    rows: list[tuple[int, TrendLineageSourceRole, FinancialAnalysisResult]] = []
    with factory() as session, session.begin():
        for ordinal, period_id in enumerate(periods):
            for role in roles:
                _engine, _source_type, analysis_type, _schema, model = ROLE_BINDINGS[role]
                row = FinancialAnalysisResult(
                    id=uuid4(),
                    company_id=company_id,
                    period_id=period_id,
                    document_id=None,
                    source_mode=SourceMode.MULTI_SOURCE_DERIVED,
                    analysis_type=analysis_type,
                    engine_version=model,
                    status=AnalysisStatus.COMPLETED,
                    result_json={"ordinal": ordinal, "role": role.value, "amount": str(100 + ordinal)},
                    error_message=None,
                    started_at=NOW,
                    completed_at=NOW,
                )
                session.add(row)
                rows.append((ordinal, role, row))
        session.flush()
        if metadata:
            session.add_all(
                FinancialAnalysisResultRevisionMetadata(
                    analysis_result_id=row.id,
                    tenant_id=tenant_id,
                    company_id=company_id,
                    period_id=row.period_id,
                    restatement_state="ORIGINAL",
                    restatement_revision=0,
                    restatement_reason="NONE",
                    supersedes_analysis_result_id=None,
                    metadata_schema_version="1.0.0",
                )
                for _ordinal, _role, row in rows
            )
    return tuple(rows)


def _lineage_set(scope, sources, *, owner_id=None, transform=None):
    tenant_id, company_id, periods = scope
    owner_id = owner_id or uuid4()
    edges = []
    for position, (ordinal, role, source) in enumerate(sources):
        engine, source_type, _analysis_type, schema, model = ROLE_BINDINGS[role]
        edge = TrendLineageEdge(
            ordinal=ordinal,
            source_period_id=source.period_id,
            source_analysis_result_id=source.id,
            source_role=role,
            source_engine_code=engine,
            source_analysis_type=source_type,
            source_canonical_digest=source.canonical_result_digest,
            source_schema_version=schema,
            source_model_version=model,
            observation_evidence=TrendEvidenceLevel.EXACT,
            comparability_proof_digest=f"{(position % 9) + 1}" * 64,
            resolution_proof_reference="trend:v1:sha256:" + f"{((position + 4) % 9) + 1}" * 64,
        )
        edges.append(transform(edge, position) if transform else edge)
    return build_trend_lineage_set(
        trend_analysis_result_id=owner_id,
        tenant_id=tenant_id,
        company_id=company_id,
        anchor_period_id=periods[-1],
        metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        policy_version=TrendPolicyVersion.V1,
        contract_version=TrendContractVersion.V1,
        lineage=tuple(reversed(edges)),
    )


def _owner(scope, lineage_set):
    _tenant_id, company_id, periods = scope
    return FinancialAnalysisResult(
        id=lineage_set.trend_analysis_result_id,
        company_id=company_id,
        period_id=periods[-1],
        document_id=None,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED,
        analysis_type=AnalysisType.MULTI_PERIOD_TREND,
        engine_version="1.0.0",
        status=AnalysisStatus.COMPLETED,
        result_json={
            "status": "complete",
            "source_set_digest": lineage_set.source_set_digest,
            "lineage_count": len(lineage_set.lineage),
            "metric_registry_version": lineage_set.metric_registry_version,
            "metric_registry_digest": lineage_set.metric_registry_digest,
            "policy_version": lineage_set.policy_version.value,
            "contract_version": lineage_set.contract_version.value,
        },
        error_message=None,
        started_at=NOW,
        completed_at=NOW,
    )


def _persist(factory, scope, lineage_set):
    owner = _owner(scope, lineage_set)
    with factory() as session, session.begin():
        session.add(owner)
        session.flush()
        SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(lineage_set)
    return owner


@pytest.mark.parametrize("period_count", (3, 5, 7))
def test_arbitrary_n_atomic_write_and_verified_read_back(trend_lineage_database, period_count):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory, period_count)
    lineage_set = _lineage_set(scope, _sources(factory, scope))
    owner = _persist(factory, scope, lineage_set)
    with factory() as session, session.begin():
        verified = SqlAlchemyTrendLineageRepository(session).load_verified_lineage(owner.id)
        assert verified.lineage_set == lineage_set
        assert verified.owner_payload_digest == owner.canonical_result_digest
        assert session.scalar(
            select(func.count()).select_from(TrendAnalysisLineage).where(
                TrendAnalysisLineage.trend_analysis_result_id == owner.id
            )
        ) == period_count
        assert not hasattr(TrendAnalysisLineage, "result_json")


def test_multi_role_sources_are_persisted_with_one_period_per_ordinal(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    roles = (
        TrendLineageSourceRole.BALANCE_SHEET,
        TrendLineageSourceRole.INCOME_STATEMENT,
        TrendLineageSourceRole.FINANCIAL_RATIOS,
    )
    lineage_set = _lineage_set(scope, _sources(factory, scope, roles))
    _persist(factory, scope, lineage_set)
    assert {edge.source_role for edge in lineage_set.lineage} == set(roles)
    assert tuple(TrendLineageSourceRole) == (
        TrendLineageSourceRole.BALANCE_SHEET,
        TrendLineageSourceRole.INCOME_STATEMENT,
        TrendLineageSourceRole.CASH_FLOW,
        TrendLineageSourceRole.FINANCIAL_RATIOS,
    )
    assert len(lineage_set.lineage) == 9


def test_failed_source_validation_rolls_back_owner_metadata_and_lineage(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    lineage_set = _lineage_set(
        scope,
        sources,
        transform=lambda edge, position: replace(edge, source_canonical_digest="f" * 64)
        if position == 0
        else edge,
    )
    owner = _owner(scope, lineage_set)
    with pytest.raises(TrendLineagePortError) as captured:
        with factory() as session, session.begin():
            session.add(owner)
            session.flush()
            SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(lineage_set)
    assert captured.value.code is TrendLineagePortErrorCode.INTEGRITY_FAILURE
    with factory() as session:
        assert session.get(FinancialAnalysisResult, owner.id) is None
        assert session.get(FinancialAnalysisResultRevisionMetadata, owner.id) is None
        assert session.scalar(
            select(func.count()).select_from(TrendAnalysisLineage).where(
                TrendAnalysisLineage.trend_analysis_result_id == owner.id
            )
        ) == 0


def test_exact_replay_is_idempotent_and_conflicting_replay_is_rejected(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    lineage_set = _lineage_set(scope, sources)
    owner = _persist(factory, scope, lineage_set)
    with factory() as session, session.begin():
        verified = SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(lineage_set)
        assert verified.lineage_set == lineage_set
    conflict = _lineage_set(
        scope,
        sources,
        owner_id=owner.id,
        transform=lambda edge, position: replace(edge, observation_evidence=TrendEvidenceLevel.DERIVED)
        if position == 0
        else edge,
    )
    with factory() as session, session.begin(), pytest.raises(TrendLineagePortError) as captured:
        SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(conflict)
    assert captured.value.code is TrendLineagePortErrorCode.CONFLICT

    proof_conflict = _lineage_set(
        scope,
        sources,
        owner_id=owner.id,
        transform=lambda edge, position: replace(edge, comparability_proof_digest="e" * 64)
        if position == 0
        else edge,
    )
    with factory() as session, session.begin(), pytest.raises(TrendLineagePortError) as proof_error:
        SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(proof_conflict)
    assert proof_error.value.code is TrendLineagePortErrorCode.CONFLICT


def test_savepoint_discard_removes_staged_loser_owner_metadata_and_lineage(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    canonical_set = _lineage_set(scope, sources)
    canonical_owner = _persist(factory, scope, canonical_set)
    loser_set = _lineage_set(scope, sources)
    loser = _owner(scope, loser_set)
    with factory() as session, session.begin():
        savepoint = session.begin_nested()
        session.add(loser)
        session.flush()
        SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(loser_set)
        savepoint.rollback()
    with factory() as session:
        assert session.get(FinancialAnalysisResult, canonical_owner.id) is not None
        assert session.get(FinancialAnalysisResult, loser.id) is None
        assert session.get(FinancialAnalysisResultRevisionMetadata, loser.id) is None
        assert session.scalar(
            select(func.count()).select_from(TrendAnalysisLineage).where(
                TrendAnalysisLineage.trend_analysis_result_id == loser.id
            )
        ) == 0


def test_cross_company_source_and_missing_revision_metadata_fail_closed(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    other_scope = _create_scope(factory)
    foreign = _sources(factory, other_scope)
    bad_set = _lineage_set(
        scope,
        ((0, foreign[0][1], foreign[0][2]),) + _sources(factory, scope)[1:],
    )
    with pytest.raises(TrendLineagePortError):
        _persist(factory, scope, bad_set)

    scope_without_metadata = _create_scope(factory)
    sources_without_metadata = _sources(factory, scope_without_metadata, metadata=False)
    missing_set = _lineage_set(scope_without_metadata, sources_without_metadata)
    with pytest.raises(TrendLineagePortError) as captured:
        _persist(factory, scope_without_metadata, missing_set)
    assert captured.value.code is TrendLineagePortErrorCode.INTEGRITY_FAILURE


def test_missing_source_and_non_trend_owner_fail_closed(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    missing_set = _lineage_set(
        scope,
        sources,
        transform=lambda edge, position: replace(edge, source_analysis_result_id=uuid4())
        if position == 0
        else edge,
    )
    with pytest.raises(TrendLineagePortError) as missing:
        _persist(factory, scope, missing_set)
    assert missing.value.code is TrendLineagePortErrorCode.INTEGRITY_FAILURE

    valid_set = _lineage_set(scope, sources)
    invalid_owner = _owner(scope, valid_set)
    invalid_owner.analysis_type = AnalysisType.BALANCE_SHEET
    with factory() as session, session.begin(), pytest.raises(TrendLineagePortError) as non_trend:
        session.add(invalid_owner)
        session.flush()
        SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(valid_set)
    assert non_trend.value.code is TrendLineagePortErrorCode.INTEGRITY_FAILURE


@pytest.mark.parametrize("mutation", ("status", "version"))
def test_source_terminal_state_and_version_are_revalidated(trend_lineage_database, mutation):
    engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    lineage_set = _lineage_set(scope, sources)
    with engine.begin() as connection:
        if mutation == "status":
            connection.execute(
                text("UPDATE financial_analysis_results SET status='failed' WHERE id=:id"),
                {"id": sources[0][2].id},
            )
        else:
            connection.execute(
                text("UPDATE financial_analysis_results SET engine_version='9.0.0' WHERE id=:id"),
                {"id": sources[0][2].id},
            )
    with pytest.raises(TrendLineagePortError) as captured:
        _persist(factory, scope, lineage_set)
    assert captured.value.code is TrendLineagePortErrorCode.INTEGRITY_FAILURE


def test_non_chronological_ordinal_mapping_is_rejected(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    reordered = (
        (0, sources[1][1], sources[1][2]),
        (1, sources[0][1], sources[0][2]),
        sources[2],
    )
    lineage_set = _lineage_set(scope, reordered)
    with pytest.raises(TrendLineagePortError) as captured:
        _persist(factory, scope, lineage_set)
    assert captured.value.code is TrendLineagePortErrorCode.INTEGRITY_FAILURE


@pytest.mark.parametrize(
    ("statement", "target"),
    (
        ("UPDATE trend_analysis_lineage SET observation_evidence='derived' WHERE trend_analysis_result_id=:id", "owner"),
        ("DELETE FROM trend_analysis_lineage WHERE trend_analysis_result_id=:id", "owner"),
        ("UPDATE financial_analysis_result_revision_metadata SET restatement_reason='LEGACY_UNDECLARED' WHERE analysis_result_id=:id", "owner"),
        ("DELETE FROM financial_analysis_result_revision_metadata WHERE analysis_result_id=:id", "owner"),
        ("UPDATE financial_analysis_results SET engine_version='9.0.0' WHERE id=:id", "owner"),
        ("DELETE FROM financial_analysis_results WHERE id=:id", "owner"),
        ("UPDATE financial_analysis_results SET engine_version='9.0.0' WHERE id=:id", "source"),
        ("DELETE FROM financial_analysis_results WHERE id=:id", "source"),
    ),
)
def test_all_trend_owned_records_reject_real_update_and_delete(trend_lineage_database, statement, target):
    engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    lineage_set = _lineage_set(scope, sources)
    owner = _persist(factory, scope, lineage_set)
    target_id = sources[0][2].id if target == "source" else owner.id
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(text(statement), {"id": target_id})


@pytest.mark.parametrize("corruption", ("missing_row", "source_set", "reference"))
def test_read_back_detects_missing_row_and_source_set_corruption(trend_lineage_database, corruption):
    engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    lineage_set = _lineage_set(scope, _sources(factory, scope))
    owner = _persist(factory, scope, lineage_set)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE trend_analysis_lineage DISABLE TRIGGER USER"))
        if corruption == "missing_row":
            connection.execute(
                text(
                    "DELETE FROM trend_analysis_lineage "
                    "WHERE trend_analysis_result_id=:id AND ordinal=0"
                ),
                {"id": owner.id},
            )
        elif corruption == "source_set":
            connection.execute(
                text(
                    "UPDATE trend_analysis_lineage SET source_set_digest=:digest "
                    "WHERE trend_analysis_result_id=:id AND ordinal=0"
                ),
                {"digest": "f" * 64, "id": owner.id},
            )
        else:
            connection.execute(
                text(
                    "UPDATE trend_analysis_lineage SET resolution_proof_reference=:reference "
                    "WHERE trend_analysis_result_id=:id AND ordinal=0"
                ),
                {"reference": "trend:v1:sha256:" + "f" * 64, "id": owner.id},
            )
        connection.execute(text("ALTER TABLE trend_analysis_lineage ENABLE TRIGGER USER"))
    with factory() as session, session.begin(), pytest.raises(TrendLineagePortError) as captured:
        SqlAlchemyTrendLineageRepository(session).load_verified_lineage(owner.id)
    assert captured.value.code is TrendLineagePortErrorCode.INTEGRITY_FAILURE


def test_database_rejects_invalid_check_and_duplicate_append(trend_lineage_database):
    engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    lineage_set = _lineage_set(scope, _sources(factory, scope))
    owner = _persist(factory, scope, lineage_set)
    row = lineage_set.lineage[0]
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO trend_analysis_lineage (
                      id,trend_analysis_result_id,tenant_id,company_id,anchor_period_id,
                      ordinal,source_period_id,source_analysis_result_id,source_role,
                      source_engine_code,source_analysis_type,source_canonical_digest,
                      source_schema_version,source_model_version,observation_evidence,
                      comparability_proof_digest,resolution_proof_reference,
                      source_set_digest,lineage_schema_version
                    ) VALUES (
                      :row_id,:owner,:tenant,:company,:anchor,-1,:period,:source,
                      'balance_sheet','fs_balance_sheet','balance_sheet',:digest,NULL,
                      '1.0.0','exact',:proof,:reference,:source_set,'1.0.0'
                    )
                    """
                ),
                {
                    "row_id": uuid4(),
                    "owner": owner.id,
                    "tenant": scope[0],
                    "company": scope[1],
                    "anchor": scope[2][-1],
                    "period": row.source_period_id,
                    "source": row.source_analysis_result_id,
                    "digest": row.source_canonical_digest,
                    "proof": row.comparability_proof_digest,
                    "reference": row.resolution_proof_reference,
                    "source_set": lineage_set.source_set_digest,
                },
            )


def test_concurrent_identical_and_conflicting_replay_are_serialized(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    lineage_set = _lineage_set(scope, sources)
    owner = _persist(factory, scope, lineage_set)
    conflict = _lineage_set(
        scope,
        sources,
        owner_id=owner.id,
        transform=lambda edge, position: replace(edge, observation_evidence=TrendEvidenceLevel.DERIVED)
        if position == 0
        else edge,
    )

    def replay(candidate):
        try:
            with factory() as session, session.begin():
                SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(candidate)
            return "success"
        except TrendLineagePortError as error:
            return error.code.value

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = tuple(executor.map(replay, (lineage_set, conflict, lineage_set, conflict)))
    assert outcomes.count("success") == 2
    assert outcomes.count(TrendLineagePortErrorCode.CONFLICT.value) == 2
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(TrendAnalysisLineage).where(
                TrendAnalysisLineage.trend_analysis_result_id == owner.id
            )
        ) == 3


def test_company_lock_timeout_is_fail_closed_and_other_company_is_not_blocked(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope_a = _create_scope(factory)
    set_a = _lineage_set(scope_a, _sources(factory, scope_a))
    owner_a = _persist(factory, scope_a, set_a)
    scope_b = _create_scope(factory)
    set_b = _lineage_set(scope_b, _sources(factory, scope_b))
    owner_b = _persist(factory, scope_b, set_b)
    holder = factory()
    holder.begin()
    holder.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": trend_company_lock_key(scope_a[0], scope_a[1])},
    )
    try:
        with factory() as session, session.begin():
            verified = SqlAlchemyTrendLineageRepository(session).load_verified_lineage(owner_b.id)
            assert verified.lineage_set == set_b
        with factory() as session, session.begin(), pytest.raises(TrendLineagePortError) as captured:
            SqlAlchemyTrendLineageRepository(
                session,
                statement_timeout_seconds=0.10,
                lock_timeout_seconds=0.05,
            ).load_verified_lineage(owner_a.id)
        assert captured.value.code is TrendLineagePortErrorCode.LOCK_TIMEOUT
    finally:
        holder.rollback()
        holder.close()


def test_port_errors_are_safe_and_do_not_expose_database_details():
    error = TrendLineagePortError(TrendLineagePortErrorCode.PERSISTENCE_UNAVAILABLE)
    rendered = f"{error!s} {error!r}"
    assert "postgres" not in rendered.lower()
    assert "sql" not in rendered.lower()
    assert error.args == ()
    assert error.__cause__ is None
    assert error.__context__ is None
