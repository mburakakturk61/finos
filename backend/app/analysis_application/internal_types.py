"""Framework-free internal value objects used across application ports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.analysis_application.contracts import (
    ApplicationEngineCode,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
    ApplicationStatus,
    FinancialSourceMode,
    FinancialSourceRole,
    RunScopeClaimStatus,
    CancellationStatus,
)
from app.engines.analysis_orchestrator.types import ExecutionTelemetry, OrchestrationRunResult
from app.orchestration_persistence.types import (
    PersistedRun,
    PersistenceRunScope,
    ResumePersistenceContext,
    SnapshotLoadResult,
)


@dataclass(frozen=True)
class RunScopeClaim:
    claim_id: uuid.UUID
    run_id: str
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    tenant_id: str | None
    operation_kind: ApplicationOperationKind
    original_operation: ApplicationOriginalOperation
    previous_run_id: str | None
    application_command_digest: str
    status: RunScopeClaimStatus
    version: int
    claim_token: str
    persisted_run_id: uuid.UUID | None
    persisted_request_fingerprint: str | None
    persisted_terminal_content_digest: str | None
    claimed_at: datetime
    finalized_at: datetime | None


@dataclass(frozen=True)
class InternalRunView:
    persisted_run_id: uuid.UUID
    run_id: str
    status: ApplicationStatus
    persistence_scope: PersistenceRunScope
    requested_outputs: tuple[ApplicationEngineCode, ...]
    request_fingerprint: str
    terminal_content_digest: str
    previous_run_id: str | None
    finalized_at: datetime


@dataclass(frozen=True)
class VerifiedApplicationScopeBinding:
    run_id: str
    scope: ApplicationScopeDTO
    persistence_scope: PersistenceRunScope
    application_command_digest: str
    claim_id: uuid.UUID
    claim_version: int
    claim_status: RunScopeClaimStatus


@dataclass(frozen=True)
class AuthorizedResumeSourceView:
    run: InternalRunView
    verified_scope: VerifiedApplicationScopeBinding
    payloads_materialized: bool
    snapshot_load_result: SnapshotLoadResult | None

    def __post_init__(self) -> None:
        if self.payloads_materialized != (self.snapshot_load_result is not None):
            raise ValueError("Resume source materialization invariant failed.")


@dataclass(frozen=True)
class OwnerAuditTimes:
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True)
class ResolvedFinancialLineageEdge:
    role: FinancialSourceRole
    source_document_id: uuid.UUID | None
    source_analysis_result_id: uuid.UUID | None
    source_engine_code: ApplicationEngineCode | None


@dataclass(frozen=True)
class ResolvedFinancialOwnerNode:
    engine_code: ApplicationEngineCode
    expected_existing_owner_id: uuid.UUID | None
    allow_existing_canonical_owner: bool
    create_new_owner: bool
    primary_document_id: uuid.UUID | None
    source_mode: FinancialSourceMode
    lineage: tuple[ResolvedFinancialLineageEdge, ...]


@dataclass(frozen=True)
class ResolvedFinancialOwnershipPlan:
    nodes: tuple[ResolvedFinancialOwnerNode, ...]
    audit_times: OwnerAuditTimes


@dataclass(frozen=True)
class ApplicationTerminalPersistenceRequest:
    scope: ApplicationScopeDTO
    run_result: OrchestrationRunResult
    requested_outputs: tuple[ApplicationEngineCode, ...]
    resume_context: ResumePersistenceContext | None
    financial_ownership_plan: ResolvedFinancialOwnershipPlan
    telemetry: ExecutionTelemetry | None


@dataclass(frozen=True)
class TerminalPersistenceResult:
    persisted_run: PersistedRun
    idempotent_replay: bool


@dataclass(frozen=True)
class LocalCancelResult:
    status: CancellationStatus

    def __post_init__(self) -> None:
        if self.status not in {
            CancellationStatus.ACCEPTED,
            CancellationStatus.ALREADY_REQUESTED,
            CancellationStatus.NOT_ACTIVE,
        }:
            raise ValueError("Invalid process-local cancellation result.")
