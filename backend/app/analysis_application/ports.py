"""Dependency-inversion ports. No framework or ORM dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.analysis_application.contracts import (
    AnalysisCommandResultDTO, AnalysisExecutionDTO, AnalysisHistoryPageDTO,
    AnalysisResultDTO, AnalysisRunStatusDTO, ApplicationEngineCode,
    ApplicationEventType, ApplicationJsonValue, ApplicationOutcome,
    ApplicationAuditContextDTO, ApplicationScopeDTO,
    GetAnalysisResultQuery, GetAnalysisStatusQuery, GetExecutionDetailQuery,
    ListAnalysisHistoryQuery, ResumeAnalysisCommand, RetryAnalysisCommand,
    StartAnalysisCommand,
    ApplicationPayloadEnvelopeDTO,
    FinancialSourceIntentDTO,
)
from app.analysis_application.internal_types import (
    ApplicationTerminalPersistenceRequest, AuthorizedResumeSourceView,
    InternalRunView, LocalCancelResult, OwnerAuditTimes,
    ResolvedFinancialOwnershipPlan, RunScopeClaim, TerminalPersistenceResult,
    VerifiedApplicationScopeBinding,
)
from app.engines.analysis_orchestrator.types import OrchestrationRunResult
from app.orchestration_persistence.types import PersistenceRunScope, SnapshotLoadResult


@dataclass(frozen=True)
class AuthorizationDecision:
    granted: bool
    revoked: bool
    decision_code: str
    provider_decision_reference: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.granted and self.revoked:
            raise ValueError("Authorization cannot be granted and revoked.")


@dataclass(frozen=True)
class SecurityAuditEventDTO:
    event_type: ApplicationEventType
    occurred_at: datetime
    correlation_id: str
    scope: ApplicationScopeDTO
    actor_id: str
    run_id: str | None = None
    decision_code: str | None = None
    application_command_digest: str | None = None
    safe_attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SecurityAuditReceiptDTO:
    receipt_id: str
    event_type: ApplicationEventType
    recorded_at: datetime
    audit_record_digest: str


@dataclass(frozen=True)
class ObservabilityEventDTO:
    event_name: str
    correlation_id: str
    safe_attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LocalExecutionToken:
    token_id: str
    run_id: str
    scope: ApplicationScopeDTO


@dataclass(frozen=True)
class LocalExecutionDiagnostics:
    run_id: str
    correlation_id: str
    phase: str
    cancellation_requested: bool


class AnalysisExecutionGatewayPort(Protocol):
    def start(self, command: StartAnalysisCommand, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcome[AnalysisCommandResultDTO]: ...
    def resume(self, command: ResumeAnalysisCommand, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcome[AnalysisCommandResultDTO]: ...
    def retry(self, command: RetryAnalysisCommand, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcome[AnalysisCommandResultDTO]: ...


class AnalysisReadPort(Protocol):
    def get_run_by_id(self, run_id: str, scope: ApplicationScopeDTO) -> InternalRunView | None: ...
    def get_status(self, run_id: str, scope: ApplicationScopeDTO) -> AnalysisRunStatusDTO | None: ...
    def get_result(self, run_id: str, scope: ApplicationScopeDTO, *, include_payloads: bool) -> AnalysisResultDTO | None: ...
    def get_execution_detail(self, run_id: str, engine_code: ApplicationEngineCode, scope: ApplicationScopeDTO, *, include_payload: bool) -> AnalysisExecutionDTO | None: ...
    def list_history(self, scope: ApplicationScopeDTO, cursor: str | None, limit: int) -> AnalysisHistoryPageDTO: ...
    def load_scope(self, run_id: str) -> VerifiedApplicationScopeBinding | None: ...
    def load_resume_source(self, previous_run_id: str, target_scope: ApplicationScopeDTO, *, materialize_payloads: bool) -> AuthorizedResumeSourceView: ...


class AuthorizationPort(Protocol):
    def authorize_start(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def authorize_resume(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def authorize_resume_source(self, source_run_id: str, target_scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def authorize_read(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO, *, include_payload: bool) -> AuthorizationDecision: ...
    def authorize_cancel(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def authorize_retry(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...


class ActiveExecutionPort(Protocol):
    def register(self, run_id: str, scope: ApplicationScopeDTO, correlation_id: str) -> LocalExecutionToken: ...
    def unregister(self, token: LocalExecutionToken) -> None: ...
    def request_cancel(self, run_id: str, scope: ApplicationScopeDTO) -> LocalCancelResult: ...
    def is_active(self, run_id: str, scope: ApplicationScopeDTO) -> bool: ...
    def get_local_diagnostics(self, run_id: str, scope: ApplicationScopeDTO) -> LocalExecutionDiagnostics | None: ...


class SecurityAuditPort(Protocol):
    def record_required_event(self, event: SecurityAuditEventDTO) -> SecurityAuditReceiptDTO: ...


class ObservabilityPort(Protocol):
    def emit_best_effort_event(self, event: ObservabilityEventDTO) -> None: ...
    def increment_metric(self, name: str, value: int, tags: tuple[tuple[str, str], ...]) -> None: ...
    def record_timing(self, name: str, duration_ms: float, tags: tuple[tuple[str, str], ...]) -> None: ...


class ApplicationClockPort(Protocol):
    def now_audit_time(self) -> datetime: ...
    def resolve_business_time(self, caller_supplied: datetime | None) -> datetime: ...


class RunScopeClaimPort(Protocol):
    def claim(self, run_id: str, scope: ApplicationScopeDTO, application_command_digest: str, claimed_at: datetime) -> RunScopeClaim: ...
    def verify(self, run_id: str, scope: ApplicationScopeDTO, claim_token: str, expected_version: int) -> RunScopeClaim: ...
    def finalize(self, run_id: str, scope: ApplicationScopeDTO, claim_token: str, expected_version: int, persisted_run: object, finalized_at: datetime) -> RunScopeClaim: ...
    def load(self, run_id: str) -> RunScopeClaim | None: ...


class RunPersistencePort(Protocol):
    def persist_terminal_run(self, request: ApplicationTerminalPersistenceRequest) -> TerminalPersistenceResult: ...
    def build_previous_execution_snapshot(self, run_id: str, target_scope: PersistenceRunScope) -> SnapshotLoadResult: ...
    def resolve_financial_ownership_plan(self, run_result: OrchestrationRunResult, source_intents: tuple[FinancialSourceIntentDTO, ...], scope: ApplicationScopeDTO, audit_times: OwnerAuditTimes) -> ResolvedFinancialOwnershipPlan: ...
    def resolve_payload_references(self, run_id: str, scope: ApplicationScopeDTO, *, include_payloads: bool) -> tuple[ApplicationPayloadEnvelopeDTO, ...]: ...
