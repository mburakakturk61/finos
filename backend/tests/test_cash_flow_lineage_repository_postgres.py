"""Real PostgreSQL acceptance for Milestone 4.5F lineage persistence."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import os
from pathlib import Path
import threading
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.engines.cash_flow import (
    CashFlowErrorCode,
    CashFlowPortError,
    CashFlowResultStatus,
    CashFlowSourceRole,
    ResolvedCashFlowLineageEdge,
)
from app.integrations.cash_flow_lineage_repository import (
    SqlAlchemyCashFlowLineageRepository,
    authoritative_source_provenance_digest,
    canonical_source_provenance_digest,
)
from app.models.cash_flow_cross_period_lineage import CashFlowCrossPeriodLineage
from app.models.company import Company
from app.models.enums import (
    AnalysisStatus,
    AnalysisSourceRole,
    AnalysisType,
    PeriodCoverageKind,
    PeriodStatus,
    PeriodType,
    SourceMode,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.financial_period import FinancialPeriod
from app.models.orchestration_persistence import OrchestrationEngineExecution, OrchestrationRun


NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def lineage_database():
    original_url = get_settings().database_url
    base_url = make_url(original_url)
    database_name = f"finos_cf45f_repo_{uuid4().hex}"
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
        engine = create_engine(isolated_url, pool_size=10, max_overflow=0)
        yield engine, sessionmaker(bind=engine, expire_on_commit=False)
        engine.dispose()
    finally:
        os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"), {"name": database_name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin.dispose()


def _create_scope(factory):
    tenant_id, company_id, current_id, prior_id = uuid4(), uuid4(), uuid4(), uuid4()
    with factory() as session, session.begin():
        session.execute(
            text("INSERT INTO security_tenants (id,tenant_key,status,policy_version,version) VALUES (:id,:key,'ACTIVE',1,1)"),
            {"id": tenant_id, "key": f"cf-{tenant_id.hex[:20]}"},
        )
        session.add(Company(id=company_id, tenant_id=tenant_id, legal_name="4.5F synthetic", tax_number=company_id.hex, currency="TRY"))
        for period_id, year, start, end in (
            (prior_id, 2024, date(2024, 1, 1), date(2024, 12, 31)),
            (current_id, 2025, date(2025, 1, 1), date(2025, 12, 31)),
        ):
            session.add(FinancialPeriod(
                id=period_id, company_id=company_id, year=year, period_type=PeriodType.YEAR_END,
                period_number=4, start_date=start, end_date=end, months_covered=12,
                is_year_end=True, status=PeriodStatus.CLOSED,
                accounting_basis_code="tr_tdhp_accrual",
                accounting_policy_version="tr_tdhp_accrual/1.0.0",
                annual_reporting_period_start_date=start,
                annual_reporting_period_end_date=end,
                ifrs18_early_adopted=False,
                cash_flow_coverage_kind=PeriodCoverageKind.CUMULATIVE,
            ))
    return tenant_id, company_id, current_id, prior_id


def _sources(factory, scope):
    _tenant, company, current, prior = scope
    definitions = (
        (CashFlowSourceRole.CURRENT_BALANCE_SHEET, AnalysisType.BALANCE_SHEET, current),
        (CashFlowSourceRole.PRIOR_BALANCE_SHEET, AnalysisType.BALANCE_SHEET, prior),
        (CashFlowSourceRole.CURRENT_INCOME_STATEMENT, AnalysisType.INCOME_STATEMENT, current),
        (CashFlowSourceRole.CURRENT_TRIAL_BALANCE, AnalysisType.TRIAL_BALANCE, current),
        (CashFlowSourceRole.PRIOR_TRIAL_BALANCE, AnalysisType.TRIAL_BALANCE, prior),
    )
    rows = []
    with factory() as session, session.begin():
        for role, analysis_type, period in definitions:
            row = FinancialAnalysisResult(
                id=uuid4(), company_id=company, period_id=period, document_id=None,
                source_mode=SourceMode.MULTI_SOURCE_DERIVED, analysis_type=analysis_type,
                engine_version="1.0.0", status=AnalysisStatus.COMPLETED,
                result_json={"role": role.value, "amount": "100.00"}, error_message=None,
                started_at=NOW, completed_at=NOW,
            )
            session.add(row)
            rows.append((role, row))
        session.flush()
    return tuple(rows)


def _edges(factory, sources, scope):
    _tenant, _company, current, prior = scope
    edges = []
    with factory() as session:
        for role, source_stub in sources:
            source = session.get(FinancialAnalysisResult, source_stub.id)
            bindings = tuple(session.scalars(
                select(FinancialAnalysisResultSource)
                .where(FinancialAnalysisResultSource.analysis_result_id == source.id)
                .order_by(FinancialAnalysisResultSource.id)
            ))
            edges.append(ResolvedCashFlowLineageEdge(
                source_role=role,
                source_analysis_result_id=source.id,
                source_period_id=source.period_id,
                source_canonical_digest=source.canonical_result_digest,
                source_provenance_digest=canonical_source_provenance_digest(source, bindings),
                source_analysis_type=source.analysis_type,
                source_engine_version=source.engine_version,
                current_period_descriptor_digest="c" * 64,
                prior_period_descriptor_digest="d" * 64,
                comparability_proof_digest="e" * 64,
            ))
    return tuple(edges)


def _owner(scope, status=CashFlowResultStatus.COMPLETE_RECONCILED):
    _tenant, company, current, _prior = scope
    return FinancialAnalysisResult(
        id=uuid4(), company_id=company, period_id=current, document_id=None,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED, analysis_type=AnalysisType.CASH_FLOW,
        engine_version="1.0.0", status=AnalysisStatus.COMPLETED,
        result_json={"status": status.value, "cash_flow_schema_version": "1.0.0"},
        error_message=None, started_at=NOW, completed_at=NOW,
    )


def _seal(session: Session, owner: FinancialAnalysisResult, scope, status):
    _tenant, company, current, _prior = scope
    run = OrchestrationRun(
        id=uuid4(), run_id=f"cf-{uuid4()}", company_id=company, period_id=current,
        request_fingerprint="1" * 64, terminal_content_digest="2" * 64,
        correlation_id=None, generated_at=NOW, requested_outputs_json=["cash_flow"],
        warnings_json=[], input_version_inventory_json={}, status="fully_completed",
        orchestration_schema_version="3.0.0", orchestration_model_version="3.0.0",
        execution_plan_version="3.0.0", fingerprint_schema_version="1.0.0",
        previous_run_id=None, finalized_at=NOW,
    )
    session.add(run)
    session.flush()
    session.add(OrchestrationEngineExecution(
        id=uuid4(), run_id=run.id, engine_code="cash_flow", execution_ordinal=0,
        status="completed" if status is CashFlowResultStatus.COMPLETE_RECONCILED else "degraded",
        inner_status=status.value, dependency_engine_codes_json=[], engine_schema_version="1.0.0",
        engine_model_version="1.0.0", input_fingerprint="3" * 64,
        fingerprint_schema_version="1.0.0", result_kind="CashFlowResult",
        owner_content_digest="4" * 64, financial_analysis_result_id=owner.id,
    ))
    session.flush()


def _persist(factory, scope, edges, *, status=CashFlowResultStatus.COMPLETE_RECONCILED):
    owner = _owner(scope, status)
    with factory() as session, session.begin():
        session.add(owner)
        session.flush()
        SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
            cash_flow_owner_id=owner.id, tenant_id=scope[0], company_id=scope[1],
            current_period_id=scope[2], prior_period_id=scope[3],
            cash_flow_status=status, lineage=edges,
        )
        _seal(session, owner, scope, status)
    return owner


def _analysis_chain(factory, scope, length, *, cycle=False):
    _tenant, company, current, _prior = scope
    rows = []
    with factory() as session, session.begin():
        for index in range(length):
            row = FinancialAnalysisResult(
                id=uuid4(), company_id=company, period_id=current, document_id=None,
                source_mode=SourceMode.MULTI_SOURCE_DERIVED,
                analysis_type=AnalysisType.BALANCE_SHEET if index == 0 else AnalysisType.TRIAL_BALANCE,
                engine_version="1.0.0", status=AnalysisStatus.COMPLETED,
                result_json={"chain_index": index}, error_message=None,
                started_at=NOW, completed_at=NOW,
            )
            session.add(row)
            rows.append(row)
        session.flush()
    with factory() as session, session.begin():
        pairs = list(zip(rows, rows[1:]))
        if cycle:
            pairs.append((rows[-1], rows[0]))
        for parent, child in pairs:
            session.add(FinancialAnalysisResultSource(
                analysis_result_id=parent.id, company_id=company, period_id=current,
                source_document_id=None, source_analysis_result_id=child.id,
                role=AnalysisSourceRole.SUPPORTING_ANALYSIS,
            ))
    return tuple(rows)


def _edge_for_chain_root(factory, scope, root):
    with factory() as session:
        source = session.get(FinancialAnalysisResult, root.id)
        return ResolvedCashFlowLineageEdge(
            source_role=CashFlowSourceRole.CURRENT_BALANCE_SHEET,
            source_analysis_result_id=source.id, source_period_id=source.period_id,
            source_canonical_digest=source.canonical_result_digest,
            source_provenance_digest=authoritative_source_provenance_digest(session, source),
            source_analysis_type=source.analysis_type, source_engine_version=source.engine_version,
            current_period_descriptor_digest="c" * 64,
            prior_period_descriptor_digest="d" * 64,
            comparability_proof_digest="e" * 64,
        )


def test_atomic_owner_lineage_write_and_verified_read_back(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _persist(factory, scope, edges)
    with factory() as session, session.begin():
        verified = SqlAlchemyCashFlowLineageRepository(session).load_verified_lineage(owner.id)
        assert verified.lineage == edges
        assert len(verified.source_set_digest) == 64
        assert verified.owner_payload_digest == owner.canonical_result_digest
        assert session.scalar(select(FinancialAnalysisResultSource).where(
            FinancialAnalysisResultSource.analysis_result_id == owner.id
        )) is None


def test_transitive_provenance_closure_is_verified_and_stable(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    base = _edges(factory, _sources(factory, scope), scope)
    chain = _analysis_chain(factory, scope, 4)
    root_edge = _edge_for_chain_root(factory, scope, chain[0])
    edges = (root_edge,) + base[1:]
    owner = _persist(factory, scope, edges)
    with factory() as session, session.begin():
        verified = SqlAlchemyCashFlowLineageRepository(session).load_verified_lineage(owner.id)
        assert verified.lineage[0].source_provenance_digest == root_edge.source_provenance_digest


@pytest.mark.parametrize(("length", "cycle"), ((3, True), (18, False)))
def test_cycle_and_depth_seventeen_provenance_are_fail_closed(lineage_database, length, cycle):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    base = _edges(factory, _sources(factory, scope), scope)
    chain = _analysis_chain(factory, scope, length, cycle=cycle)
    owner = _owner(scope)
    with factory() as session:
        source = session.get(FinancialAnalysisResult, chain[0].id)
        with pytest.raises(CashFlowPortError):
            authoritative_source_provenance_digest(session, source)
    # No owner or lineage staging is attempted from an invalid closure.
    with factory() as session:
        assert session.get(FinancialAnalysisResult, owner.id) is None


def test_identical_replay_is_idempotent_and_creates_no_duplicate_rows(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _persist(factory, scope, edges)
    with factory() as session, session.begin():
        SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
            cash_flow_owner_id=owner.id, tenant_id=scope[0], company_id=scope[1],
            current_period_id=scope[2], prior_period_id=scope[3],
            cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED,
            lineage=tuple(reversed(edges)),
        )
        assert len(tuple(session.scalars(select(CashFlowCrossPeriodLineage).where(
            CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == owner.id
        )))) == 5


def test_same_owner_different_source_set_is_conflict(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _persist(factory, scope, edges)
    changed = (replace(edges[0], source_canonical_digest="f" * 64),) + edges[1:]
    with factory() as session, session.begin(), pytest.raises(CashFlowPortError) as captured:
        SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
            cash_flow_owner_id=owner.id, tenant_id=scope[0], company_id=scope[1],
            current_period_id=scope[2], prior_period_id=scope[3],
            cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED, lineage=changed,
        )
    assert captured.value.code is CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE


@pytest.mark.parametrize("failure", ("wrong_tenant", "wrong_prior", "wrong_digest", "wrong_role_period"))
def test_scope_period_and_digest_failures_stage_nothing(lineage_database, failure):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _owner(scope)
    tenant, company, current, prior = scope
    if failure == "wrong_tenant":
        tenant = uuid4()
    elif failure == "wrong_prior":
        prior = uuid4()
    elif failure == "wrong_digest":
        edges = (replace(edges[0], source_canonical_digest="f" * 64),) + edges[1:]
    else:
        edges = (replace(edges[0], source_period_id=scope[3]),) + edges[1:]
    with factory() as session:
        try:
            with session.begin():
                session.add(owner)
                session.flush()
                with pytest.raises(CashFlowPortError):
                    SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
                        cash_flow_owner_id=owner.id, tenant_id=tenant, company_id=company,
                        current_period_id=current, prior_period_id=prior,
                        cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED, lineage=edges,
                    )
                raise RuntimeError("force owner rollback")
        except RuntimeError:
            pass
    with factory() as session:
        assert session.get(FinancialAnalysisResult, owner.id) is None
        assert not tuple(session.scalars(select(CashFlowCrossPeriodLineage).where(
            CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == owner.id
        )))


def test_lineage_and_referenced_source_are_immutable(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _persist(factory, scope, edges)
    with factory() as session:
        row_id = session.scalar(select(CashFlowCrossPeriodLineage.id).where(
            CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == owner.id
        ))
    for statement, params in (
        ("UPDATE cash_flow_cross_period_lineage SET source_engine_version=source_engine_version WHERE id=:id", {"id": row_id}),
        ("DELETE FROM cash_flow_cross_period_lineage WHERE id=:id", {"id": row_id}),
        ("UPDATE financial_analysis_results SET engine_version=engine_version WHERE id=:id", {"id": edges[0].source_analysis_result_id}),
        ("DELETE FROM financial_analysis_results WHERE id=:id", {"id": edges[0].source_analysis_result_id}),
    ):
        with factory() as session, pytest.raises(DBAPIError):
            with session.begin():
                session.execute(text(statement), params)


def test_cross_company_source_is_rejected_without_partial_lineage(lineage_database):
    _engine, factory = lineage_database
    owner_scope = _create_scope(factory)
    foreign_scope = _create_scope(factory)
    owner_edges = _edges(factory, _sources(factory, owner_scope), owner_scope)
    foreign_edge = _edges(factory, _sources(factory, foreign_scope), foreign_scope)[0]
    mixed = (replace(
        foreign_edge,
        source_role=CashFlowSourceRole.CURRENT_BALANCE_SHEET,
        source_period_id=owner_scope[2],
        current_period_descriptor_digest=owner_edges[0].current_period_descriptor_digest,
        prior_period_descriptor_digest=owner_edges[0].prior_period_descriptor_digest,
        comparability_proof_digest=owner_edges[0].comparability_proof_digest,
    ),) + owner_edges[1:]
    owner = _owner(owner_scope)
    with factory() as session:
        with pytest.raises(CashFlowPortError):
            with session.begin():
                session.add(owner)
                session.flush()
                SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
                    cash_flow_owner_id=owner.id, tenant_id=owner_scope[0], company_id=owner_scope[1],
                    current_period_id=owner_scope[2], prior_period_id=owner_scope[3],
                    cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED, lineage=mixed,
                )
    with factory() as session:
        assert session.get(FinancialAnalysisResult, owner.id) is None


def test_invalid_source_status_is_rejected_without_partial_lineage(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    edges = _edges(factory, sources, scope)
    with factory() as session, session.begin():
        source = session.get(FinancialAnalysisResult, sources[0][1].id)
        source.status = AnalysisStatus.FAILED
    owner = _owner(scope)
    with factory() as session:
        with pytest.raises(CashFlowPortError):
            with session.begin():
                session.add(owner)
                session.flush()
                SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
                    cash_flow_owner_id=owner.id, tenant_id=scope[0], company_id=scope[1],
                    current_period_id=scope[2], prior_period_id=scope[3],
                    cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED, lineage=edges,
                )
    with factory() as session:
        assert session.get(FinancialAnalysisResult, owner.id) is None


def test_source_payload_digest_corruption_is_detected_on_read(lineage_database):
    engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _persist(factory, scope, edges)
    # Corruption simulation is isolated to this synthetic database and restores the guard.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE cash_flow_cross_period_lineage DISABLE TRIGGER trg_cf_20_guard_cash_flow_cross_period_lineage_upd"))
        connection.execute(
            text("UPDATE cash_flow_cross_period_lineage SET source_canonical_digest=:digest WHERE cash_flow_analysis_result_id=:id AND source_role='current_balance_sheet'"),
            {"digest": "f" * 64, "id": owner.id},
        )
        connection.execute(text("ALTER TABLE cash_flow_cross_period_lineage ENABLE TRIGGER trg_cf_20_guard_cash_flow_cross_period_lineage_upd"))
    with factory() as session, session.begin(), pytest.raises(CashFlowPortError) as captured:
        SqlAlchemyCashFlowLineageRepository(session).load_verified_lineage(owner.id)
    assert captured.value.code is CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE


def test_company_lock_timeout_is_fail_closed_without_raw_db_error(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _owner(scope)
    with factory() as setup, setup.begin():
        setup.add(owner)
        setup.flush()
        _seal(setup, owner, scope, CashFlowResultStatus.INSUFFICIENT_DATA)
    locker = factory()
    locker.begin()
    locker.execute(select(Company).where(Company.id == scope[1]).with_for_update()).scalar_one()
    try:
        with factory() as contender, contender.begin(), pytest.raises(CashFlowPortError) as captured:
            SqlAlchemyCashFlowLineageRepository(
                contender, statement_timeout_seconds=1, lock_timeout_seconds=0.05
            ).stage_exact_lineage(
                cash_flow_owner_id=owner.id, tenant_id=scope[0], company_id=scope[1],
                current_period_id=scope[2], prior_period_id=scope[3],
                cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED, lineage=edges,
            )
        assert captured.value.code is CashFlowErrorCode.PERSISTENCE_UNAVAILABLE
        assert "postgres" not in repr(captured.value).lower()
    finally:
        locker.rollback()
        locker.close()


def test_different_company_namespace_is_not_blocked(lineage_database):
    _engine, factory = lineage_database
    first_scope = _create_scope(factory)
    second_scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, second_scope), second_scope)
    owner = _owner(second_scope)
    locker = factory()
    locker.begin()
    locker.execute(select(Company).where(Company.id == first_scope[1]).with_for_update()).scalar_one()
    try:
        with factory() as session, session.begin():
            session.add(owner)
            session.flush()
            SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
                cash_flow_owner_id=owner.id, tenant_id=second_scope[0], company_id=second_scope[1],
                current_period_id=second_scope[2], prior_period_id=second_scope[3],
                cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED, lineage=edges,
            )
            _seal(session, owner, second_scope, CashFlowResultStatus.COMPLETE_RECONCILED)
    finally:
        locker.rollback()
        locker.close()


def test_concurrent_identical_replay_returns_one_immutable_lineage_set(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _persist(factory, scope, edges)
    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        try:
            with factory() as session, session.begin():
                barrier.wait(timeout=2)
                SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
                    cash_flow_owner_id=owner.id, tenant_id=scope[0], company_id=scope[1],
                    current_period_id=scope[2], prior_period_id=scope[3],
                    cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED,
                    lineage=tuple(reversed(edges)),
                )
            outcomes.append("success")
        except Exception as exc:  # pragma: no cover - asserted below
            outcomes.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert outcomes == ["success", "success"]
    with factory() as session:
        assert session.scalar(select(text("count(*)")).select_from(CashFlowCrossPeriodLineage).where(
            CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == owner.id
        )) == 5


def test_concurrent_conflicting_replay_is_fail_closed(lineage_database):
    _engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _persist(factory, scope, edges)
    changed = (replace(edges[0], source_canonical_digest="f" * 64),) + edges[1:]
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(candidate):
        try:
            with factory() as session, session.begin():
                barrier.wait(timeout=2)
                SqlAlchemyCashFlowLineageRepository(session).stage_exact_lineage(
                    cash_flow_owner_id=owner.id, tenant_id=scope[0], company_id=scope[1],
                    current_period_id=scope[2], prior_period_id=scope[3],
                    cash_flow_status=CashFlowResultStatus.COMPLETE_RECONCILED,
                    lineage=candidate,
                )
            outcomes.append("success")
        except CashFlowPortError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=worker, args=(candidate,)) for candidate in (edges, changed)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert sorted(str(value) for value in outcomes) == sorted(
        ("success", str(CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE))
    )


def test_missing_required_lineage_is_integrity_failure_on_read(lineage_database):
    engine, factory = lineage_database
    scope = _create_scope(factory)
    edges = _edges(factory, _sources(factory, scope), scope)
    owner = _owner(scope)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE orchestration_engine_executions DISABLE TRIGGER trg_cf_10_validate_orchestration_engine_executions_ins"))
    try:
        with factory() as session, session.begin():
            session.add(owner)
            session.flush()
            for edge in edges[:2]:
                session.add(CashFlowCrossPeriodLineage(
                    cash_flow_analysis_result_id=owner.id, tenant_id=scope[0], company_id=scope[1],
                    current_period_id=scope[2], prior_period_id=scope[3],
                    source_period_id=edge.source_period_id,
                    source_analysis_result_id=edge.source_analysis_result_id,
                    source_role=edge.source_role.value,
                    source_canonical_digest=edge.source_canonical_digest,
                    source_provenance_digest=edge.source_provenance_digest,
                    source_analysis_type=edge.source_analysis_type.value,
                    source_engine_version=edge.source_engine_version,
                    current_period_descriptor_digest=edge.current_period_descriptor_digest,
                    prior_period_descriptor_digest=edge.prior_period_descriptor_digest,
                    comparability_proof_digest=edge.comparability_proof_digest,
                    lineage_schema_version="1.0.0", lineage_policy_version="1.0.0",
                ))
            session.flush()
            _seal(session, owner, scope, CashFlowResultStatus.COMPLETE_RECONCILED)
    finally:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE orchestration_engine_executions ENABLE TRIGGER trg_cf_10_validate_orchestration_engine_executions_ins"))
    with factory() as session, session.begin(), pytest.raises(CashFlowPortError) as captured:
        SqlAlchemyCashFlowLineageRepository(session).load_verified_lineage(owner.id)
    assert captured.value.code is CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE
