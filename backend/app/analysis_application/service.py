"""Synchronous, framework-free 5.0C analysis use-case coordination."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from app.analysis_application.contracts import (
    AnalysisCommandResultDTO,
    AnalysisErrorCode,
    AnalysisErrorDTO,
    AnalysisWarningDTO,
    ApplicationEventType,
    ApplicationOutcome,
    ApplicationWarningCode,
    CancellationResultDTO,
    CancellationStatus,
    ResumeAnalysisCommand,
    RetryAnalysisCommand,
    RunScopeClaimStatus,
    StartAnalysisCommand,
)
from app.analysis_application.errors import ERROR_POLICIES
from app.analysis_application.internal_types import (
    ApplicationTerminalPersistenceRequest,
    OwnerAuditTimes,
)
from app.analysis_application.mapping import application_command_digest, to_orchestration_request
from app.analysis_application.ports import (
    ActiveExecutionPort,
    AnalysisReadPort,
    ApplicationClockPort,
    AuthorizationDecision,
    AuthorizationPort,
    ObservabilityEventDTO,
    ObservabilityPort,
    RunPersistencePort,
    RunScopeClaimPort,
    SecurityAuditEventDTO,
    SecurityAuditPort,
)
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import EngineExecutionStatus
from app.orchestration_persistence.errors import OrchestrationPersistenceError, PersistenceErrorCategory
from app.orchestration_persistence.types import PersistenceRunScope

ExecutionCommand = StartAnalysisCommand | ResumeAnalysisCommand | RetryAnalysisCommand
Executor = Callable[..., tuple[object, object]]


class AnalysisApplicationService:
    def __init__(
        self, *, authorization: AuthorizationPort, security_audit: SecurityAuditPort,
        observability: ObservabilityPort, active_executions: ActiveExecutionPort,
        clock: ApplicationClockPort, scope_claims: RunScopeClaimPort,
        persistence: RunPersistencePort, reads: AnalysisReadPort,
        executor: Executor = run_orchestration,
    ) -> None:
        self.authorization = authorization
        self.security_audit = security_audit
        self.observability = observability
        self.active_executions = active_executions
        self.clock = clock
        self.scope_claims = scope_claims
        self.persistence = persistence
        self.reads = reads
        self.executor = executor

    def start(self, command: StartAnalysisCommand, cancellation_probe=None) -> ApplicationOutcome[AnalysisCommandResultDTO]:
        return self._execute(command, ApplicationEventType.START_REQUESTED, self.authorization.authorize_start, cancellation_probe)

    def resume(self, command: ResumeAnalysisCommand, cancellation_probe=None) -> ApplicationOutcome[AnalysisCommandResultDTO]:
        return self._execute(command, ApplicationEventType.RESUME_REQUESTED, self.authorization.authorize_resume, cancellation_probe)

    def retry(self, command: RetryAnalysisCommand, cancellation_probe=None) -> ApplicationOutcome[AnalysisCommandResultDTO]:
        return self._execute(command, ApplicationEventType.RETRY_REQUESTED, self.authorization.authorize_retry, cancellation_probe)

    def cancel(self, command) -> ApplicationOutcome[CancellationResultDTO]:
        digest = None
        if not self._audit(command, ApplicationEventType.CANCEL_REQUESTED, digest):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
        decision = self._authorize(self.authorization.authorize_cancel, command)
        if isinstance(decision, AnalysisErrorCode):
            if not self._audit(command, ApplicationEventType.AUTHORIZATION_DENIED, digest, decision.value):
                return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
            return self._failure(decision, command.correlation_id)
        if not self._audit_authorization(command, decision, digest):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
        if not decision.granted:
            return self._failure(AnalysisErrorCode.UNAUTHORIZED, command.correlation_id)
        local = self.active_executions.request_cancel(command.run_id, command.scope)
        status = local.status
        if status is CancellationStatus.NOT_ACTIVE:
            run = self.reads.get_run_by_id(command.run_id, command.scope)
            if run is not None:
                status = CancellationStatus.ALREADY_TERMINAL
            elif self.scope_claims.load(command.run_id) is None:
                status = CancellationStatus.NOT_FOUND
        value = CancellationResultDTO(command.run_id, status, command.scope, self.clock.now_audit_time())
        return ApplicationOutcome(True, value, None, (), command.correlation_id)

    def _execute(self, command: ExecutionCommand, request_event, authorize_method, cancellation_probe):
        try:
            digest = application_command_digest(command)
        except Exception:
            return self._failure(AnalysisErrorCode.INVALID_COMMAND, command.correlation_id)
        if not self._audit(command, request_event, digest):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
        decision = self._authorize(authorize_method, command)
        if isinstance(decision, AnalysisErrorCode):
            if not self._audit(command, ApplicationEventType.AUTHORIZATION_DENIED, digest, decision.value):
                return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
            return self._failure(decision, command.correlation_id)
        if not self._audit_authorization(command, decision, digest):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
        if not decision.granted:
            return self._failure(AnalysisErrorCode.UNAUTHORIZED, command.correlation_id)
        try:
            claim = self.scope_claims.claim(command.run_id, command.scope, digest, self.clock.now_audit_time())
        except Exception as error:
            existing = self._safe_load_claim(command.run_id)
            if existing is not None and _scope_matches(existing, command.scope):
                return self._failure(AnalysisErrorCode.RUN_ID_CONFLICT, command.correlation_id)
            return self._failure(AnalysisErrorCode.SCOPE_MISMATCH if existing else AnalysisErrorCode.SCOPE_CLAIM_UNAVAILABLE, command.correlation_id)

        recovered = self._recover_existing(command, claim)
        if recovered is not None:
            return recovered

        snapshot = None
        resume_context = None
        if command.scope.previous_run_id is not None:
            source_error, snapshot, resume_context = self._load_authorized_source(command, digest)
            if source_error is not None:
                return source_error

        token = None
        try:
            try:
                token = self.active_executions.register(command.run_id, command.scope, command.correlation_id)
            except Exception:
                self._observe("active_execution_register_failed", command.correlation_id)

            request = to_orchestration_request(command, snapshot)

            def combined_cancel() -> bool:
                external = bool(cancellation_probe and cancellation_probe())
                diagnostics = self.active_executions.get_local_diagnostics(command.run_id, command.scope)
                return external or bool(diagnostics and diagnostics.cancellation_requested)

            try:
                run_result, telemetry = self.executor(request, cancellation_probe=combined_cancel)
            except Exception:
                return self._failure(AnalysisErrorCode.EXECUTION_FAILED, command.correlation_id)
            if run_result.run_id != command.run_id:
                return self._failure(AnalysisErrorCode.INTERNAL_INVARIANT_BREACH, command.correlation_id)
            if resume_context is not None:
                reused = {record.engine_code for record in run_result.engine_records if record.status is EngineExecutionStatus.REUSED}
                resume_context = dataclasses.replace(
                    resume_context,
                    engine_bindings=tuple(item for item in resume_context.engine_bindings if item.engine_code in reused),
                )
            times = OwnerAuditTimes(self.clock.now_audit_time(), self.clock.now_audit_time())
            try:
                plan = self.persistence.resolve_financial_ownership_plan(run_result, command.source_intents, command.scope, times)
            except Exception:
                return self._failure(AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR, command.correlation_id)

            revalidation = self._authorize(authorize_method, command)
            if isinstance(revalidation, AnalysisErrorCode):
                if not self._audit(command, ApplicationEventType.AUTHORIZATION_DENIED, digest, revalidation.value):
                    return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
                return self._failure(revalidation, command.correlation_id)
            if not self._audit_authorization(command, revalidation, digest):
                return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
            if not revalidation.granted:
                code = AnalysisErrorCode.AUTHORIZATION_REVOKED if revalidation.revoked else AnalysisErrorCode.UNAUTHORIZED
                return self._failure(code, command.correlation_id)
            try:
                verified = self.scope_claims.verify(command.run_id, command.scope, claim.claim_token, claim.version)
            except Exception:
                return self._failure(AnalysisErrorCode.SCOPE_MISMATCH, command.correlation_id)
            persistence_request = ApplicationTerminalPersistenceRequest(
                command.scope, run_result, command.requested_outputs,
                resume_context, plan, telemetry,
            )
            try:
                terminal = self.persistence.persist_terminal_run(persistence_request)
            except OrchestrationPersistenceError as error:
                return self._failure(_persistence_code(error.category), command.correlation_id)
            except Exception:
                return self._failure(AnalysisErrorCode.PERSISTENCE_UNAVAILABLE, command.correlation_id)
            persisted = terminal.persisted_run
            if (
                persisted.run_id != command.run_id
                or persisted.scope.company_id != command.scope.company_id
                or persisted.scope.period_id != command.scope.financial_period_id
            ):
                self._audit(command, ApplicationEventType.SCOPE_MISMATCH_DETECTED, digest)
                return self._failure(AnalysisErrorCode.SCOPE_MISMATCH, command.correlation_id)
            try:
                finalized = self.scope_claims.finalize(
                    command.run_id, command.scope, verified.claim_token, verified.version,
                    persisted, self.clock.now_audit_time(),
                )
            except Exception:
                return self._failure(
                    AnalysisErrorCode.SCOPE_FINALIZATION_FAILED, command.correlation_id,
                    {"run_id": command.run_id, "recovery_query_run_id": command.run_id},
                )
            warnings = ()
            if not self._audit(command, ApplicationEventType.TERMINAL_RUN_PERSISTED, digest):
                warnings = (AnalysisWarningDTO(
                    ApplicationWarningCode.SECURITY_AUDIT_POST_COMMIT_FAILED,
                    "The terminal run was persisted; post-commit security audit delivery failed.", True,
                ),)
                self._observe("security_audit_post_commit_failed", command.correlation_id)
            return self._project_command_result(command, persisted, terminal.idempotent_replay, warnings)
        finally:
            if token is not None:
                try:
                    self.active_executions.unregister(token)
                except Exception:
                    self._observe("active_execution_unregister_failed", command.correlation_id)

    def _load_authorized_source(self, command, digest):
        try:
            source = self.reads.load_resume_source(command.scope.previous_run_id, command.scope, materialize_payloads=False)
        except Exception:
            return self._failure(AnalysisErrorCode.RESUME_SOURCE_INVALID, command.correlation_id), None, None
        decision = self._authorize_source(command)
        if isinstance(decision, AnalysisErrorCode):
            if not self._audit(command, ApplicationEventType.RESUME_SOURCE_REJECTED, digest, decision.value):
                return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id), None, None
            return self._failure(decision, command.correlation_id), None, None
        if not self._audit_authorization(command, decision, digest):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id), None, None
        if not decision.granted:
            self._audit(command, ApplicationEventType.RESUME_SOURCE_REJECTED, digest)
            return self._failure(AnalysisErrorCode.RESUME_SOURCE_UNAUTHORIZED, command.correlation_id), None, None
        if not self._audit(command, ApplicationEventType.RESUME_SOURCE_ACCEPTED, digest):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id), None, None
        try:
            loaded = self.persistence.build_previous_execution_snapshot(
                command.scope.previous_run_id,
                PersistenceRunScope(command.scope.company_id, command.scope.financial_period_id),
            )
            return None, loaded.snapshot, loaded.persistence_context
        except OrchestrationPersistenceError as error:
            code = (
                AnalysisErrorCode.RESUME_SOURCE_CORRUPTED
                if error.category in {PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE, PersistenceErrorCategory.ARTIFACT_MISSING}
                else AnalysisErrorCode.RESUME_SOURCE_INVALID
            )
            return self._failure(code, command.correlation_id), None, None
        except Exception:
            return self._failure(AnalysisErrorCode.PERSISTENCE_UNAVAILABLE, command.correlation_id), None, None

    def _recover_existing(self, command, claim):
        try:
            run = self.reads.get_run_by_id(command.run_id, command.scope)
        except Exception:
            return self._failure(AnalysisErrorCode.PERSISTENCE_UNAVAILABLE, command.correlation_id)
        if claim.status is RunScopeClaimStatus.FINALIZED:
            if run is None or (
                claim.persisted_run_id != run.persisted_run_id
                or claim.persisted_request_fingerprint != run.request_fingerprint
                or claim.persisted_terminal_content_digest != run.terminal_content_digest
            ):
                return self._failure(AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR, command.correlation_id)
            return self._project_command_result(command, _persisted_from_view(run), True, ())
        if run is None:
            return None
        try:
            finalized = self.scope_claims.finalize(
                command.run_id, command.scope, claim.claim_token, claim.version,
                _persisted_from_view(run), self.clock.now_audit_time(),
            )
        except Exception:
            return self._failure(AnalysisErrorCode.SCOPE_FINALIZATION_FAILED, command.correlation_id, {"run_id": command.run_id})
        return self._project_command_result(command, _persisted_from_view(run), True, ())

    def _project_command_result(self, command, persisted, idempotent_replay, warnings):
        try:
            result = self.reads.get_result(command.run_id, command.scope, include_payloads=False)
            if result is None:
                raise ValueError("Canonical result is unavailable.")
            value = AnalysisCommandResultDTO(
                command.run_id, result.status, persisted.request_fingerprint,
                persisted.terminal_content_digest, command.scope, result.executions,
                persisted.finalized_at, idempotent_replay, command.run_id,
            )
            return ApplicationOutcome(True, value, None, warnings, command.correlation_id)
        except Exception:
            self._observe("dto_projection_failed", command.correlation_id)
            return self._failure(
                AnalysisErrorCode.DTO_PROJECTION_FAILED, command.correlation_id,
                {"run_id": command.run_id, "recovery_query_run_id": command.run_id},
            )

    def _authorize(self, method, command):
        try:
            return method(command.scope, command.audit_context)
        except Exception:
            return AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE

    def _authorize_source(self, command):
        try:
            return self.authorization.authorize_resume_source(
                command.scope.previous_run_id, command.scope, command.audit_context,
            )
        except Exception:
            return AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE

    def _audit_authorization(self, command, decision: AuthorizationDecision, digest):
        event = ApplicationEventType.AUTHORIZATION_GRANTED if decision.granted else ApplicationEventType.AUTHORIZATION_DENIED
        return self._audit(command, event, digest, decision.decision_code)

    def _audit(self, command, event, digest, decision_code=None):
        try:
            self.security_audit.record_required_event(SecurityAuditEventDTO(
                event, self.clock.now_audit_time(), command.correlation_id,
                command.scope, command.audit_context.actor_id, command.run_id,
                decision_code, digest,
            ))
            return True
        except Exception:
            self._observe("required_security_audit_failed", command.correlation_id)
            return False

    def _observe(self, name, correlation_id):
        try:
            self.observability.emit_best_effort_event(ObservabilityEventDTO(name, correlation_id))
        except Exception:
            pass

    def _safe_load_claim(self, run_id):
        try:
            return self.scope_claims.load(run_id)
        except Exception:
            return None

    @staticmethod
    def _failure(code, correlation_id, metadata=None):
        policy = ERROR_POLICIES[code]
        error = AnalysisErrorDTO(
            code, policy.category, _PUBLIC_MESSAGES[code], policy.retryable,
            correlation_id, metadata or {},
        )
        return ApplicationOutcome(False, None, error, (), correlation_id)


def _scope_matches(claim, scope):
    return (
        claim.company_id == scope.company_id and claim.financial_period_id == scope.financial_period_id
        and claim.tenant_id == scope.tenant_id and claim.operation_kind is scope.operation_kind
        and claim.original_operation is scope.original_operation and claim.previous_run_id == scope.previous_run_id
    )


def _persisted_from_view(view):
    from app.orchestration_persistence.types import PersistedRun
    return PersistedRun(
        view.persisted_run_id, view.run_id, view.request_fingerprint,
        view.terminal_content_digest, view.persistence_scope, view.finalized_at,
    )


def _persistence_code(category):
    if category is PersistenceErrorCategory.RUN_ID_CONFLICT:
        return AnalysisErrorCode.FINGERPRINT_CONFLICT
    if category is PersistenceErrorCategory.SCOPE_MISMATCH:
        return AnalysisErrorCode.SCOPE_MISMATCH
    if category in {PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE, PersistenceErrorCategory.PERSISTENCE_INVARIANT_VIOLATION, PersistenceErrorCategory.UNSUPPORTED_SERIALIZER_OR_RESULT_KIND}:
        return AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR
    if category in {PersistenceErrorCategory.IMMUTABLE_RECORD_CONFLICT}:
        return AnalysisErrorCode.PERSISTENCE_CONFLICT
    return AnalysisErrorCode.PERSISTENCE_UNAVAILABLE


_PUBLIC_MESSAGES = {code: "The analysis request could not be completed." for code in AnalysisErrorCode}
_PUBLIC_MESSAGES.update({
    AnalysisErrorCode.INVALID_COMMAND: "The analysis command is invalid.",
    AnalysisErrorCode.UNAUTHORIZED: "The analysis operation is not authorized.",
    AnalysisErrorCode.AUTHORIZATION_REVOKED: "Authorization was revoked before persistence.",
    AnalysisErrorCode.NOT_FOUND: "The requested analysis was not found.",
    AnalysisErrorCode.SCOPE_MISMATCH: "The analysis scope does not match.",
    AnalysisErrorCode.RUN_ID_CONFLICT: "The run identifier conflicts with an existing request.",
    AnalysisErrorCode.FINGERPRINT_CONFLICT: "The run identifier has a different request fingerprint.",
    AnalysisErrorCode.DTO_PROJECTION_FAILED: "The run was persisted but its result projection failed.",
})
