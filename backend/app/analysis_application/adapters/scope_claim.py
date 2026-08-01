"""PostgreSQL edge adapter for immutable, durable run ownership reservations."""

from __future__ import annotations

import enum
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analysis_application.contracts import ApplicationScopeDTO, RunScopeClaimStatus
from app.analysis_application.internal_types import RunScopeClaim
from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.orchestration_persistence.types import PersistedRun


class ScopeClaimFailure(str, enum.Enum):
    CONFLICT = "SCOPE_CLAIM_CONFLICT"
    MISMATCH = "SCOPE_MISMATCH"
    UNAVAILABLE = "SCOPE_CLAIM_UNAVAILABLE"
    FINALIZATION_FAILED = "SCOPE_FINALIZATION_FAILED"


class ScopeClaimError(RuntimeError):
    def __init__(self, failure: ScopeClaimFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure


class SqlAlchemyRunScopeClaimRepository:
    """Each method owns one short transaction; the claim is not job state."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def claim(
        self, run_id: str, scope: ApplicationScopeDTO,
        application_command_digest: str, claimed_at: datetime,
    ) -> RunScopeClaim:
        values = {
            "claim_id": uuid.uuid4(), "run_id": run_id,
            "company_id": scope.company_id, "financial_period_id": scope.financial_period_id,
            "tenant_id": scope.tenant_id, "operation_kind": scope.operation_kind.value,
            "original_operation": scope.original_operation.value,
            "previous_run_id": scope.previous_run_id,
            "application_command_digest": application_command_digest,
            "status": RunScopeClaimStatus.CLAIMED.value, "version": 1,
            "claim_token": secrets.token_hex(32), "claimed_at": claimed_at,
        }
        try:
            with self._session_factory() as session, session.begin():
                created_id = session.scalar(
                    insert(AnalysisRunScopeClaim)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[AnalysisRunScopeClaim.run_id])
                    .returning(AnalysisRunScopeClaim.claim_id)
                )
                row = session.get(AnalysisRunScopeClaim, created_id) if created_id else session.scalar(
                    select(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.run_id == run_id)
                )
                if row is None:
                    raise ScopeClaimError(ScopeClaimFailure.UNAVAILABLE)
                result = _to_contract(row)
                if not _matches(result, scope) or result.application_command_digest != application_command_digest:
                    raise ScopeClaimError(ScopeClaimFailure.CONFLICT)
                return result
        except ScopeClaimError:
            raise
        except Exception as exc:
            raise ScopeClaimError(ScopeClaimFailure.UNAVAILABLE) from exc

    def verify(
        self, run_id: str, scope: ApplicationScopeDTO,
        claim_token: str, expected_version: int,
    ) -> RunScopeClaim:
        try:
            with self._session_factory() as session, session.begin():
                row = session.scalar(select(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.run_id == run_id))
                result = _to_contract(row) if row else None
                if result is None or not _matches(result, scope) or result.claim_token != claim_token or result.version != expected_version:
                    raise ScopeClaimError(ScopeClaimFailure.MISMATCH)
                return result
        except ScopeClaimError:
            raise
        except Exception as exc:
            raise ScopeClaimError(ScopeClaimFailure.UNAVAILABLE) from exc

    def finalize(
        self, run_id: str, scope: ApplicationScopeDTO,
        claim_token: str, expected_version: int,
        persisted_run: PersistedRun, finalized_at: datetime,
    ) -> RunScopeClaim:
        if (persisted_run.run_id != run_id or persisted_run.scope.company_id != scope.company_id
                or persisted_run.scope.period_id != scope.financial_period_id):
            raise ScopeClaimError(ScopeClaimFailure.FINALIZATION_FAILED)
        try:
            with self._session_factory() as session, session.begin():
                statement = (
                    update(AnalysisRunScopeClaim)
                    .where(
                        AnalysisRunScopeClaim.run_id == run_id,
                        AnalysisRunScopeClaim.company_id == scope.company_id,
                        AnalysisRunScopeClaim.financial_period_id == scope.financial_period_id,
                        AnalysisRunScopeClaim.tenant_id.is_not_distinct_from(scope.tenant_id),
                        AnalysisRunScopeClaim.operation_kind == scope.operation_kind.value,
                        AnalysisRunScopeClaim.original_operation == scope.original_operation.value,
                        AnalysisRunScopeClaim.previous_run_id.is_not_distinct_from(scope.previous_run_id),
                        AnalysisRunScopeClaim.claim_token == claim_token,
                        AnalysisRunScopeClaim.version == expected_version,
                        AnalysisRunScopeClaim.status == RunScopeClaimStatus.CLAIMED.value,
                    )
                    .values(
                        status=RunScopeClaimStatus.FINALIZED.value,
                        version=expected_version + 1,
                        persisted_run_id=persisted_run.id,
                        persisted_request_fingerprint=persisted_run.request_fingerprint,
                        persisted_terminal_content_digest=persisted_run.terminal_content_digest,
                        finalized_at=finalized_at,
                    )
                )
                row_count = session.execute(statement).rowcount
                row = session.scalar(select(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.run_id == run_id))
                result = _to_contract(row) if row else None
                expected_tuple = (
                    persisted_run.id, persisted_run.request_fingerprint,
                    persisted_run.terminal_content_digest,
                )
                actual_tuple = (
                    result.persisted_run_id, result.persisted_request_fingerprint,
                    result.persisted_terminal_content_digest,
                ) if result else None
                if row_count != 1 and not (
                    result and _matches(result, scope) and result.claim_token == claim_token
                    and result.status is RunScopeClaimStatus.FINALIZED and actual_tuple == expected_tuple
                ):
                    raise ScopeClaimError(ScopeClaimFailure.FINALIZATION_FAILED)
                return result
        except ScopeClaimError:
            raise
        except Exception as exc:
            raise ScopeClaimError(ScopeClaimFailure.FINALIZATION_FAILED) from exc

    def load(self, run_id: str) -> RunScopeClaim | None:
        try:
            with self._session_factory() as session, session.begin():
                row = session.scalar(select(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.run_id == run_id))
                return _to_contract(row) if row else None
        except Exception as exc:
            raise ScopeClaimError(ScopeClaimFailure.UNAVAILABLE) from exc


def _matches(claim: RunScopeClaim, scope: ApplicationScopeDTO) -> bool:
    return (
        claim.company_id == scope.company_id
        and claim.financial_period_id == scope.financial_period_id
        and claim.tenant_id == scope.tenant_id
        and claim.operation_kind is scope.operation_kind
        and claim.original_operation is scope.original_operation
        and claim.previous_run_id == scope.previous_run_id
    )


def _to_contract(row: AnalysisRunScopeClaim) -> RunScopeClaim:
    from app.analysis_application.contracts import ApplicationOperationKind, ApplicationOriginalOperation
    return RunScopeClaim(
        row.claim_id, row.run_id, row.company_id, row.financial_period_id, row.tenant_id,
        ApplicationOperationKind(row.operation_kind), ApplicationOriginalOperation(row.original_operation),
        row.previous_run_id, row.application_command_digest, RunScopeClaimStatus(row.status),
        row.version, row.claim_token, row.persisted_run_id, row.persisted_request_fingerprint,
        row.persisted_terminal_content_digest, row.claimed_at, row.finalized_at,
    )
