from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import threading
import uuid
import time

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError

from app.analysis_application.contracts import (
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
    RunScopeClaimStatus,
)
from app.analysis_application.adapters.scope_claim import (
    ScopeClaimError,
    ScopeClaimFailure,
    SqlAlchemyRunScopeClaimRepository,
)
from app.db.session import SessionLocal
from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.models.company import Company
from app.models.enums import PeriodStatus, PeriodType
from app.models.financial_period import FinancialPeriod
from app.models.orchestration_persistence import OrchestrationRun
from app.orchestration_persistence.types import PersistedRun, PersistenceRunScope


def _scope(tenant: str) -> ApplicationScopeDTO:
    with SessionLocal() as session, session.begin():
        company = Company(legal_name="Scope Claim Test", tax_number=uuid.uuid4().hex, currency="TRY")
        session.add(company)
        session.flush()
        period = FinancialPeriod(
            company_id=company.id, year=2026, period_type=PeriodType.YEAR_END,
            period_number=1, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            months_covered=12, is_year_end=True, status=PeriodStatus.DRAFT,
        )
        session.add(period)
        session.flush()
        return ApplicationScopeDTO(
            company.id, period.id, tenant,
            ApplicationOperationKind.START, ApplicationOriginalOperation.START,
        )


def _persisted_run(scope: ApplicationScopeDTO, run_id: str) -> PersistedRun:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session, session.begin():
        row = OrchestrationRun(
            run_id=run_id, company_id=scope.company_id, period_id=scope.financial_period_id,
            request_fingerprint="b" * 64, terminal_content_digest="c" * 64,
            correlation_id="corr", generated_at=now, requested_outputs_json=[], warnings_json=[],
            input_version_inventory_json={}, status="fully_completed",
            orchestration_schema_version="2.0.0", orchestration_model_version="2.0.0",
            execution_plan_version="2.0.0", fingerprint_schema_version="1.0.0",
            previous_run_id=None, finalized_at=now,
        )
        session.add(row)
        session.flush()
        return PersistedRun(row.id, run_id, "b" * 64, "c" * 64, PersistenceRunScope(scope.company_id, scope.financial_period_id), now)


def test_claim_is_idempotent_only_for_exact_scope_and_digest_postgres():
    repository = SqlAlchemyRunScopeClaimRepository(SessionLocal)
    scope = _scope("tenant-a")
    now = datetime.now(timezone.utc)
    first = repository.claim("claim-" + uuid.uuid4().hex, scope, "a" * 64, now)
    second = repository.claim(first.run_id, scope, "a" * 64, now)
    assert first == second
    with pytest.raises(ScopeClaimError) as caught:
        repository.claim(first.run_id, ApplicationScopeDTO(scope.company_id, scope.financial_period_id, "tenant-b", scope.operation_kind, scope.original_operation), "a" * 64, now)
    assert caught.value.failure is ScopeClaimFailure.CONFLICT
    with pytest.raises(ScopeClaimError):
        repository.claim(first.run_id, scope, "d" * 64, now)


def test_cross_tenant_same_run_claim_race_has_exactly_one_winner_postgres():
    repository = SqlAlchemyRunScopeClaimRepository(SessionLocal)
    first_scope = _scope("tenant-a")
    second_scope = _scope("tenant-b")
    run_id = "race-" + uuid.uuid4().hex
    barrier = threading.Barrier(2)

    def attempt(scope):
        barrier.wait()
        try:
            return repository.claim(run_id, scope, "a" * 64, datetime.now(timezone.utc))
        except ScopeClaimError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(attempt, (first_scope, second_scope)))
    assert sum(not isinstance(item, ScopeClaimError) for item in outcomes) == 1
    assert sum(isinstance(item, ScopeClaimError) and item.failure is ScopeClaimFailure.CONFLICT for item in outcomes) == 1


def test_finalize_is_cas_idempotent_and_wrong_tenant_is_fail_closed_postgres():
    repository = SqlAlchemyRunScopeClaimRepository(SessionLocal)
    scope = _scope("tenant-a")
    run_id = "finalize-" + uuid.uuid4().hex
    claim = repository.claim(run_id, scope, "a" * 64, datetime.now(timezone.utc))
    persisted = _persisted_run(scope, run_id)
    wrong = ApplicationScopeDTO(scope.company_id, scope.financial_period_id, "tenant-b", scope.operation_kind, scope.original_operation)
    with pytest.raises(ScopeClaimError) as caught:
        repository.finalize(run_id, wrong, claim.claim_token, claim.version, persisted, datetime.now(timezone.utc))
    assert caught.value.failure is ScopeClaimFailure.FINALIZATION_FAILED
    finalized = repository.finalize(run_id, scope, claim.claim_token, claim.version, persisted, datetime.now(timezone.utc))
    assert finalized.status is RunScopeClaimStatus.FINALIZED
    assert finalized.version == 2
    assert repository.finalize(run_id, scope, claim.claim_token, claim.version, persisted, finalized.finalized_at) == finalized


def test_scope_claim_rejects_real_update_and_delete_postgres():
    repository = SqlAlchemyRunScopeClaimRepository(SessionLocal)
    scope = _scope("tenant-a")
    claim = repository.claim("immutable-" + uuid.uuid4().hex, scope, "a" * 64, datetime.now(timezone.utc))
    for statement in (
        update(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.claim_id == claim.claim_id).values(tenant_id="attacker"),
        delete(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.claim_id == claim.claim_id),
    ):
        with SessionLocal() as session:
            with pytest.raises(DBAPIError):
                session.execute(statement)
                session.commit()
            session.rollback()


def test_existing_scope_claim_lookup_p95_is_below_50_ms_postgres():
    repository = SqlAlchemyRunScopeClaimRepository(SessionLocal)
    scope = _scope("tenant-perf")
    claim = repository.claim("perf-" + uuid.uuid4().hex, scope, "a" * 64, datetime.now(timezone.utc))
    samples = []
    for _ in range(30):
        started = time.perf_counter()
        assert repository.load(claim.run_id) is not None
        samples.append((time.perf_counter() - started) * 1000)
    assert sorted(samples)[28] < 50
