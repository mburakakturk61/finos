from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import threading
import uuid
import time

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.analysis_application.adapters.persistence import SqlAlchemyRunPersistenceAdapter
from app.analysis_application.adapters.read import ApplicationReadIntegrityError, SqlAlchemyAnalysisReadAdapter
from app.analysis_application.adapters.scope_claim import SqlAlchemyRunScopeClaimRepository
from app.analysis_application.contracts import (
    ApplicationEngineCode,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
    FinancialSourceIntentDTO,
    FinancialSourceMode,
    FinancialSourceReferenceDTO,
    FinancialSourceRole,
)
from app.analysis_application.internal_types import ApplicationTerminalPersistenceRequest, OwnerAuditTimes
from app.analysis_application.ownership import resolve_financial_ownership_plan
from app.db.session import SessionLocal
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineExecutionStatus,
    EngineResultEnvelope,
    ExecutionProvenance,
    OrchestrationRunResult,
    PerEngineExecutionRecord,
    RunStatus,
)
from app.engines.balance_sheet.service import BalanceSheetAnalysisOutcome
from app.engines.income_statement.service import IncomeStatementAnalysisOutcome
from app.models.company import Company
from app.models.enums import AnalysisSourceRole, AnalysisStatus, PeriodStatus, PeriodType, SourceMode
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_revision_metadata import FinancialAnalysisResultRevisionMetadata
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.financial_period import FinancialPeriod
from app.orchestration_persistence.blob import FilesystemBlobStore


def _scope():
    with SessionLocal() as session, session.begin():
        company = Company(legal_name="Financial Binding Test", tax_number=uuid.uuid4().hex, currency="TRY")
        session.add(company); session.flush()
        period = FinancialPeriod(
            company_id=company.id, year=2026, period_type=PeriodType.YEAR_END,
            period_number=1, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            months_covered=12, is_year_end=True, status=PeriodStatus.DRAFT,
        )
        session.add(period); session.flush()
        return ApplicationScopeDTO(company.id, period.id, "tenant-a", ApplicationOperationKind.START, ApplicationOriginalOperation.START)


def _records(*, income_failed=False):
    bs = BalanceSheetAnalysisOutcome(AnalysisStatus.COMPLETED, SourceMode.MULTI_SOURCE_DERIVED, {"total_assets": 100}, None, None)
    income = IncomeStatementAnalysisOutcome(AnalysisStatus.COMPLETED, SourceMode.MULTI_SOURCE_DERIVED, {"net_sales": 80}, None, None)
    records = [
        PerEngineExecutionRecord(EngineCode.FS_BALANCE_SHEET, EngineExecutionStatus.COMPLETED, EngineResultEnvelope(EngineCode.FS_BALANCE_SHEET, "BalanceSheetAnalysisOutcome", bs), "completed", None, (), "1.0.0", "1.0.0", "a" * 64, "1.0.0"),
        PerEngineExecutionRecord(EngineCode.FS_INCOME_STATEMENT, EngineExecutionStatus.FAILED if income_failed else EngineExecutionStatus.COMPLETED, None if income_failed else EngineResultEnvelope(EngineCode.FS_INCOME_STATEMENT, "IncomeStatementAnalysisOutcome", income), "failed" if income_failed else "completed", None, (), "1.0.0", "1.0.0", "b" * 64, "1.0.0"),
        PerEngineExecutionRecord(EngineCode.RATIO, EngineExecutionStatus.SKIPPED if income_failed else EngineExecutionStatus.COMPLETED, None if income_failed else EngineResultEnvelope(EngineCode.RATIO, "dict", {"current_ratio": 1.25}), None, None, (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT), "1.0.0", "1.0.0", "c" * 64, "1.0.0"),
    ]
    return tuple(records)


def _intents(scope, *, allow_existing=False):
    return (
        FinancialSourceIntentDTO(ApplicationEngineCode.FS_BALANCE_SHEET, scope.company_id, scope.financial_period_id, None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, allow_existing, None, {}),
        FinancialSourceIntentDTO(ApplicationEngineCode.FS_INCOME_STATEMENT, scope.company_id, scope.financial_period_id, None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, allow_existing, None, {}),
        FinancialSourceIntentDTO(
            ApplicationEngineCode.RATIO, scope.company_id, scope.financial_period_id, None,
            (
                FinancialSourceReferenceDTO(FinancialSourceRole.PRIMARY_ANALYSIS, source_engine_code=ApplicationEngineCode.FS_BALANCE_SHEET),
                FinancialSourceReferenceDTO(FinancialSourceRole.SUPPORTING_ANALYSIS, source_engine_code=ApplicationEngineCode.FS_INCOME_STATEMENT),
            ),
            FinancialSourceMode.MULTI_SOURCE_DERIVED, allow_existing, None, {},
        ),
    )


def _request(scope, run_id, *, income_failed=False, allow_existing=False):
    records = _records(income_failed=income_failed)
    result = OrchestrationRunResult(
        run_id, "corr", datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        RunStatus.PARTIALLY_COMPLETED if income_failed else RunStatus.FULLY_COMPLETED,
        records, (), (), ExecutionProvenance("2.0.0", tuple(item.engine_code for item in records), (), tuple(item.engine_code for item in records if item.status is EngineExecutionStatus.SKIPPED)),
        {}, "2.0.0", "2.0.0", "2.0.0", "d" * 64,
    )
    plan = resolve_financial_ownership_plan(
        result, _intents(scope, allow_existing=allow_existing), scope,
        OwnerAuditTimes(datetime.now(timezone.utc), datetime.now(timezone.utc)),
    )
    return ApplicationTerminalPersistenceRequest(scope, result, (ApplicationEngineCode.RATIO,), None, plan, None)


def _counts(scope):
    with SessionLocal() as session:
        owners = session.scalar(select(func.count()).select_from(FinancialAnalysisResult).where(FinancialAnalysisResult.company_id == scope.company_id))
        sources = session.scalar(select(func.count()).select_from(FinancialAnalysisResultSource).where(FinancialAnalysisResultSource.company_id == scope.company_id))
        return owners, sources


def test_bs_is_ratio_new_owner_lineage_is_atomic_postgres(tmp_path):
    scope = _scope()
    with SessionLocal() as session:
        adapter = SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path))
        outcome = adapter.persist_terminal_run(_request(scope, "owners-" + uuid.uuid4().hex))
        assert outcome.idempotent_replay is False
    assert _counts(scope) == (3, 2)
    with SessionLocal() as session:
        ratio = session.scalar(select(FinancialAnalysisResult).where(FinancialAnalysisResult.company_id == scope.company_id, FinancialAnalysisResult.analysis_type == "financial_ratios"))
        roles = set(session.scalars(select(FinancialAnalysisResultSource.role).where(FinancialAnalysisResultSource.analysis_result_id == ratio.id)))
        assert roles == {AnalysisSourceRole.PRIMARY_ANALYSIS, AnalysisSourceRole.SUPPORTING_ANALYSIS}
        metadata = tuple(session.scalars(select(FinancialAnalysisResultRevisionMetadata).where(
            FinancialAnalysisResultRevisionMetadata.company_id == scope.company_id,
            FinancialAnalysisResultRevisionMetadata.period_id == scope.financial_period_id,
        )))
        assert len(metadata) == 3
        assert {(item.restatement_state, item.restatement_revision, item.restatement_reason) for item in metadata} == {
            ("ORIGINAL", 0, "NONE")
        }


def test_mixed_financial_results_create_no_phantom_bindings_postgres(tmp_path):
    scope = _scope()
    request = _request(scope, "mixed-" + uuid.uuid4().hex, income_failed=True)
    assert tuple(node.engine_code for node in request.financial_ownership_plan.nodes) == (ApplicationEngineCode.FS_BALANCE_SHEET,)
    with SessionLocal() as session:
        SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path)).persist_terminal_run(request)
    assert _counts(scope) == (1, 0)


def test_idempotent_early_return_discards_staged_owners_and_lineage_postgres(tmp_path):
    scope = _scope()
    request = _request(scope, "replay-" + uuid.uuid4().hex)
    times = OwnerAuditTimes(datetime.now(timezone.utc), datetime.now(timezone.utc))
    with SessionLocal() as session:
        first = SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path)).persist_terminal_run(request)
    before = _counts(scope)
    with SessionLocal() as session:
        replay = SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path)).persist_terminal_run(request)
    assert first.persisted_run.id == replay.persisted_run.id
    assert replay.idempotent_replay is True
    assert _counts(scope) == before == (3, 2)


@pytest.mark.parametrize("_iteration", range(3))
def test_concurrent_same_run_race_discards_loser_staged_graph_postgres(tmp_path, _iteration):
    scope = _scope()
    request = _request(scope, "owner-race-" + uuid.uuid4().hex)
    barrier = threading.Barrier(2)

    def persist(_):
        with SessionLocal() as session:
            barrier.wait()
            return SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path)).persist_terminal_run(request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(persist, range(2)))
    assert results[0].persisted_run.id == results[1].persisted_run.id
    assert sum(item.idempotent_replay for item in results) == 1
    assert _counts(scope) == (3, 2)


def _persist_claimed(scope, run_id, tmp_path):
    claims = SqlAlchemyRunScopeClaimRepository(SessionLocal)
    claim = claims.claim(run_id, scope, "a" * 64, datetime.now(timezone.utc))
    with SessionLocal() as session:
        terminal = SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path)).persist_terminal_run(_request(scope, run_id))
    claims.finalize(run_id, scope, claim.claim_token, claim.version, terminal.persisted_run, datetime.now(timezone.utc))
    return terminal.persisted_run


def test_canonical_read_projects_financial_owner_semantics_and_verifies_digest_postgres(tmp_path):
    scope = _scope()
    run_id = "read-" + uuid.uuid4().hex
    _persist_claimed(scope, run_id, tmp_path)
    with SessionLocal() as session:
        adapter = SqlAlchemyAnalysisReadAdapter(session, FilesystemBlobStore(tmp_path))
        result = adapter.get_result(run_id, scope, include_payloads=True)
        assert len(result.executions) == 3
        for execution in result.executions:
            assert execution.payload.payload_reference.artifact_serializer_schema_version is None
            assert execution.payload.payload_reference.financial_analysis_result_id is not None
        ratio = result.executions[-1]
        assert ratio.payload.provenance_source_references[0].startswith("primary_analysis:")
        assert ratio.payload.provenance_source_references[1].startswith("supporting_analysis:")
        owner = session.get(FinancialAnalysisResult, result.executions[0].payload.payload_reference.financial_analysis_result_id)
        owner.result_json = {"tampered": True}
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()


def test_wrong_tenant_projection_is_fail_closed_postgres(tmp_path):
    scope = _scope()
    run_id = "wrong-tenant-" + uuid.uuid4().hex
    _persist_claimed(scope, run_id, tmp_path)
    wrong = ApplicationScopeDTO(scope.company_id, scope.financial_period_id, "tenant-b", scope.operation_kind, scope.original_operation)
    with SessionLocal() as session, pytest.raises(ApplicationReadIntegrityError):
        SqlAlchemyAnalysisReadAdapter(session, FilesystemBlobStore(tmp_path)).get_result(run_id, wrong, include_payloads=False)


def test_history_cursor_second_page_is_stable_and_tenant_qualified_postgres(tmp_path):
    scope = _scope()
    run_ids = tuple("history-" + uuid.uuid4().hex for _ in range(3))
    for run_id in run_ids:
        _persist_claimed(scope, run_id, tmp_path)
    with SessionLocal() as session:
        adapter = SqlAlchemyAnalysisReadAdapter(session, FilesystemBlobStore(tmp_path))
        first = adapter.list_history(scope, None, 2)
        second = adapter.list_history(scope, first.next_cursor, 2)
        assert len(first.items) == 2 and len(second.items) == 1
        assert not ({item.run_id for item in first.items} & {item.run_id for item in second.items})
        assert {item.run_id for item in first.items + second.items} == set(run_ids)


def test_allow_existing_owner_reuses_only_exact_payload_and_lineage_postgres(tmp_path):
    scope = _scope()
    with SessionLocal() as session:
        adapter = SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path))
        adapter.persist_terminal_run(_request(scope, "canonical-a-" + uuid.uuid4().hex))
    assert _counts(scope) == (3, 2)
    with SessionLocal() as session:
        adapter = SqlAlchemyRunPersistenceAdapter(session, FilesystemBlobStore(tmp_path))
        adapter.persist_terminal_run(_request(scope, "canonical-b-" + uuid.uuid4().hex, allow_existing=True))
    assert _counts(scope) == (3, 2)


def test_metadata_history_query_p95_is_below_100_ms_postgres(tmp_path):
    scope = _scope()
    for _ in range(3):
        _persist_claimed(scope, "history-perf-" + uuid.uuid4().hex, tmp_path)
    with SessionLocal() as session:
        adapter = SqlAlchemyAnalysisReadAdapter(session, FilesystemBlobStore(tmp_path))
        samples = []
        for _ in range(30):
            started = time.perf_counter()
            assert adapter.list_history(scope, None, 20).items
            samples.append((time.perf_counter() - started) * 1000)
        assert sorted(samples)[28] < 100
