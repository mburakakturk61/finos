"""Synchronous phased coordination for the additive Application-v2 path."""

from __future__ import annotations

from collections.abc import Callable

from app.analysis_application.contracts import (
    AnalysisErrorCode,
    ApplicationEventType,
    ApplicationWarningCode,
    CancellationStatus,
)
from app.analysis_application.errors import ERROR_POLICIES
from app.analysis_application.ports import (
    ActiveExecutionPort,
    ApplicationClockPort,
    AuthorizationPort,
    ObservabilityEventDTO,
    ObservabilityPort,
    SecurityAuditEventDTO,
    SecurityAuditPort,
)
from app.engines.cash_flow.types import CashFlowErrorCode

from .contracts import (
    AnalysisCommandResultDTOV2,
    AnalysisErrorDTOV2,
    AnalysisWarningDTOV2,
    ApplicationCashFlowErrorCodeV2,
    ApplicationOutcomeV2,
    CancelAnalysisCommandV2,
    CancellationResultDTOV2,
    ResumeAnalysisCommandV2,
    RetryAnalysisCommandV2,
    StartAnalysisCommandV2,
)
from .mapping import application_command_digest_v2, to_orchestration_request_v3
from .ports import (
    AnalysisOrchestratorPortV3,
    AnalysisReadPortV2,
    ApplicationTerminalPersistenceRequestV3,
    ApplicationV2PortError,
    ApplicationV2PortErrorCode,
    CashFlowSourceResolverPort,
    ComparablePeriodResolverPort,
    RunPersistencePortV3,
    RunScopeClaimPortV3,
    TenantScopeResolverPortV3,
)
from .resolution import resolve_cash_flow_pre_run_context_v2

ExecutionCommandV2 = StartAnalysisCommandV2 | ResumeAnalysisCommandV2 | RetryAnalysisCommandV2


class AnalysisApplicationServiceV2:
    def __init__(
        self,
        *,
        orchestrator: AnalysisOrchestratorPortV3,
        persistence: RunPersistencePortV3,
        reads: AnalysisReadPortV2,
        claims: RunScopeClaimPortV3,
        tenant_scopes: TenantScopeResolverPortV3,
        authorization: AuthorizationPort,
        security_audit: SecurityAuditPort,
        observability: ObservabilityPort,
        active_executions: ActiveExecutionPort,
        clock: ApplicationClockPort,
        cash_flow_sources: CashFlowSourceResolverPort,
        comparable_periods: ComparablePeriodResolverPort,
    ) -> None:
        self.orchestrator = orchestrator
        self.persistence = persistence
        self.reads = reads
        self.claims = claims
        self.tenant_scopes = tenant_scopes
        self.authorization = authorization
        self.security_audit = security_audit
        self.observability = observability
        self.active_executions = active_executions
        self.clock = clock
        self.cash_flow_sources = cash_flow_sources
        self.comparable_periods = comparable_periods

    def start(self, command: StartAnalysisCommandV2, cancellation_probe=None):
        return self._execute(command, ApplicationEventType.START_REQUESTED, self.authorization.authorize_start, cancellation_probe)

    def resume(self, command: ResumeAnalysisCommandV2, cancellation_probe=None):
        return self._execute(command, ApplicationEventType.RESUME_REQUESTED, self.authorization.authorize_resume, cancellation_probe)

    def retry(self, command: RetryAnalysisCommandV2, cancellation_probe=None):
        return self._execute(command, ApplicationEventType.RETRY_REQUESTED, self.authorization.authorize_retry, cancellation_probe)

    def cancel(self, command: CancelAnalysisCommandV2):
        verified = self._tenant(command)
        if isinstance(verified, ApplicationOutcomeV2):
            return verified
        if not self._audit(command, ApplicationEventType.CANCEL_REQUESTED, None):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
        decision = self._authorize(self.authorization.authorize_cancel, command)
        if not decision or not decision.granted:
            return self._failure(AnalysisErrorCode.UNAUTHORIZED, command.correlation_id)
        local = self.active_executions.request_cancel(command.run_id, command.scope)
        status = local.status
        if status is CancellationStatus.NOT_ACTIVE:
            run = self.reads.get_run_by_id(command.run_id, command.scope, verified)
            status = CancellationStatus.ALREADY_TERMINAL if run is not None else CancellationStatus.NOT_FOUND
        return ApplicationOutcomeV2(
            True,
            CancellationResultDTOV2(command.run_id, status, command.scope, self.clock.now_audit_time()),
            None,
            (),
            command.correlation_id,
        )

    def _execute(self, command: ExecutionCommandV2, event, authorize, cancellation_probe):
        try:
            digest = application_command_digest_v2(command)
        except Exception:
            return self._failure(AnalysisErrorCode.INVALID_COMMAND, command.correlation_id)
        verified_tenant = self._tenant(command)
        if isinstance(verified_tenant, ApplicationOutcomeV2):
            return verified_tenant
        if not self._audit(command, event, digest):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
        decision = self._authorize(authorize, command)
        if decision is None:
            return self._failure(AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE, command.correlation_id)
        if not self._audit(command, ApplicationEventType.AUTHORIZATION_GRANTED if decision.granted else ApplicationEventType.AUTHORIZATION_DENIED, digest, decision.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, command.correlation_id)
        if not decision.granted:
            return self._failure(AnalysisErrorCode.UNAUTHORIZED, command.correlation_id)
        try:
            claim = self.claims.claim(
                command.run_id, command.scope, verified_tenant, digest, self.clock.now_audit_time(),
            )
        except ApplicationV2PortError as error:
            return self._failure(_port_code(error.code), command.correlation_id)
        except Exception:
            return self._failure(AnalysisErrorCode.SCOPE_CLAIM_UNAVAILABLE, command.correlation_id)

        snapshot = resume_context = None
        if command.scope.previous_run_id is not None:
            source = self._load_resume(command, verified_tenant, digest)
            if isinstance(source, ApplicationOutcomeV2):
                return source
            snapshot, resume_context = source

        try:
            pre_resolved = (
                resolve_cash_flow_pre_run_context_v2(
                    command.cash_flow_request,
                    verified_tenant,
                    comparable_periods=self.comparable_periods,
                    cash_flow_sources=self.cash_flow_sources,
                )
                if command.cash_flow_request is not None else None
            )
        except Exception as error:
            return self._typed_source_failure(error, command.correlation_id)

        token = None
        try:
            try:
                token = self.active_executions.register(command.run_id, command.scope, command.correlation_id)
            except Exception:
                self._observe("active_execution_register_failed", command.correlation_id)

            request = to_orchestration_request_v3(
                command,
                cash_flow_pre_resolved_context=pre_resolved,
                previous_execution_snapshot=snapshot,
            )

            def cancelled():
                external = bool(cancellation_probe and cancellation_probe())
                local = self.active_executions.get_local_diagnostics(command.run_id, command.scope)
                return external or bool(local and local.cancellation_requested)

            try:
                run_result = self.orchestrator.run(request, cancellation_probe=cancelled)
            except Exception:
                return self._failure(AnalysisErrorCode.EXECUTION_FAILED, command.correlation_id)
            if run_result.run_id != command.run_id:
                return self._failure(AnalysisErrorCode.INTERNAL_INVARIANT_BREACH, command.correlation_id)
            started = completed = self.clock.now_audit_time()
            try:
                plan = self.persistence.resolve_financial_ownership_plan(
                    run_result, command.source_intents, command.cash_flow_request,
                    pre_resolved, _verified_binding(command, claim), started, completed,
                )
            except Exception as error:
                return self._typed_persistence_failure(error, command.correlation_id)

            revalidated = self._authorize(authorize, command)
            if revalidated is None:
                return self._failure(AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE, command.correlation_id)
            if not revalidated.granted:
                self._audit(command, ApplicationEventType.AUTHORIZATION_DENIED, digest, revalidated.decision_code)
                return self._failure(AnalysisErrorCode.AUTHORIZATION_REVOKED if revalidated.revoked else AnalysisErrorCode.UNAUTHORIZED, command.correlation_id)
            if command.scope.previous_run_id is not None:
                source_revalidated = self._authorize_resume_source(command)
                if source_revalidated is None:
                    return self._failure(AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE, command.correlation_id)
                if not source_revalidated.granted:
                    self._audit(command, ApplicationEventType.RESUME_SOURCE_REJECTED, digest, source_revalidated.decision_code)
                    return self._failure(
                        AnalysisErrorCode.AUTHORIZATION_REVOKED
                        if source_revalidated.revoked else AnalysisErrorCode.RESUME_SOURCE_UNAUTHORIZED,
                        command.correlation_id,
                    )
            try:
                verified_claim = self.claims.verify(
                    command.run_id, command.scope, verified_tenant, claim.claim_token, claim.version,
                )
                terminal = self.persistence.persist_terminal_run(ApplicationTerminalPersistenceRequestV3(
                    _verified_binding(command, verified_claim), run_result, command.requested_outputs,
                    resume_context, plan, None,
                ))
            except ApplicationV2PortError as error:
                return self._failure(_port_code(error.code), command.correlation_id)
            except Exception as error:
                return self._typed_persistence_failure(error, command.correlation_id)
            persisted = terminal.persisted_run
            expected_scope = _verified_binding(command, verified_claim).persistence_scope
            if persisted.run_id != command.run_id or persisted.scope != expected_scope:
                return self._failure(AnalysisErrorCode.SCOPE_MISMATCH, command.correlation_id)
            try:
                self.claims.finalize(
                    command.run_id, command.scope, verified_tenant, verified_claim.claim_token,
                    verified_claim.version, persisted, self.clock.now_audit_time(),
                )
            except Exception:
                return self._failure(AnalysisErrorCode.SCOPE_FINALIZATION_FAILED, command.correlation_id, {"run_id": command.run_id})
            warnings = ()
            if not self._audit(command, ApplicationEventType.TERMINAL_RUN_PERSISTED, digest):
                warnings = (AnalysisWarningDTOV2(
                    ApplicationWarningCode.SECURITY_AUDIT_POST_COMMIT_FAILED,
                    "The terminal run was persisted; post-commit security audit delivery failed.",
                    True,
                ),)
            try:
                result = self.reads.get_result(
                    command.run_id, command.scope, verified_tenant, include_payloads=False,
                )
                if result is None:
                    raise ValueError
                value = AnalysisCommandResultDTOV2(
                    command.run_id, result.status, persisted.request_fingerprint,
                    persisted.terminal_content_digest, command.scope, result.executions,
                    persisted.finalized_at, terminal.idempotent_replay, command.run_id,
                )
                return ApplicationOutcomeV2(True, value, None, warnings, command.correlation_id)
            except Exception:
                self._observe("dto_projection_failed", command.correlation_id)
                return self._failure(AnalysisErrorCode.DTO_PROJECTION_FAILED, command.correlation_id, {"run_id": command.run_id, "recovery_query_run_id": command.run_id})
        finally:
            if token is not None:
                try:
                    self.active_executions.unregister(token)
                except Exception:
                    self._observe("active_execution_unregister_failed", command.correlation_id)

    def _load_resume(self, command, verified_tenant, digest):
        try:
            self.reads.load_resume_source(
                command.scope.previous_run_id, command.scope, verified_tenant,
                materialize_payloads=False,
            )
            decision = self.authorization.authorize_resume_source(
                command.scope.previous_run_id, command.scope, command.audit_context,
            )
            if not decision.granted:
                return self._failure(AnalysisErrorCode.RESUME_SOURCE_UNAUTHORIZED, command.correlation_id)
            self._audit(command, ApplicationEventType.RESUME_SOURCE_ACCEPTED, digest)
            loaded = self.persistence.build_previous_execution_snapshot(
                command.scope.previous_run_id,
                _persistence_scope(command, verified_tenant),
            )
            return loaded.snapshot, loaded.persistence_context
        except ApplicationV2PortError as error:
            code = AnalysisErrorCode.RESUME_SOURCE_CORRUPTED if error.code is ApplicationV2PortErrorCode.INTEGRITY else AnalysisErrorCode.RESUME_SOURCE_INVALID
            return self._failure(code, command.correlation_id)
        except Exception:
            return self._failure(AnalysisErrorCode.RESUME_SOURCE_INVALID, command.correlation_id)

    def _tenant(self, command):
        try:
            return self.tenant_scopes.resolve(command.scope, command.audit_context)
        except Exception:
            return self._failure(AnalysisErrorCode.SCOPE_MISMATCH, command.correlation_id)

    def _authorize(self, method, command):
        try:
            return method(command.scope, command.audit_context)
        except Exception:
            return None

    def _authorize_resume_source(self, command):
        try:
            return self.authorization.authorize_resume_source(
                command.scope.previous_run_id, command.scope, command.audit_context,
            )
        except Exception:
            return None

    def _typed_source_failure(self, error, correlation_id):
        code = getattr(error, "code", None)
        if type(code) is CashFlowErrorCode:
            return self._failure(AnalysisErrorCode.PERSISTENCE_UNAVAILABLE if getattr(error, "retryable", False) else AnalysisErrorCode.INVALID_COMMAND, correlation_id, cash_flow_code=code)
        return self._failure(AnalysisErrorCode.INTERNAL_INVARIANT_BREACH, correlation_id)

    def _typed_persistence_failure(self, error, correlation_id):
        code = getattr(error, "code", None)
        if type(code) is CashFlowErrorCode:
            public = AnalysisErrorCode.PERSISTENCE_UNAVAILABLE if code is CashFlowErrorCode.PERSISTENCE_UNAVAILABLE else AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR
            return self._failure(public, correlation_id, cash_flow_code=code)
        return self._failure(AnalysisErrorCode.PERSISTENCE_UNAVAILABLE, correlation_id)

    def _audit(self, command, event, digest, decision_code=None):
        try:
            self.security_audit.record_required_event(SecurityAuditEventDTO(
                event, self.clock.now_audit_time(), command.correlation_id, command.scope,
                command.audit_context.actor_id, command.run_id, decision_code, digest,
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

    @staticmethod
    def _failure(code, correlation_id, metadata=None, *, cash_flow_code=None):
        policy = ERROR_POLICIES[code]
        return ApplicationOutcomeV2(False, None, AnalysisErrorDTOV2(
            code,
            ApplicationCashFlowErrorCodeV2(cash_flow_code.value) if cash_flow_code else None,
            policy.category,
            "The analysis request could not be completed.",
            policy.retryable,
            correlation_id,
            metadata or {},
        ), (), correlation_id)


def _persistence_scope(command, verified_tenant):
    from app.orchestration_persistence_v3.types import PersistenceRunScopeV3
    return PersistenceRunScopeV3(
        verified_tenant.tenant_id, command.scope.company_id, command.scope.financial_period_id,
    )


def _verified_binding(command, claim):
    from .ports import VerifiedApplicationScopeBindingV3
    return VerifiedApplicationScopeBindingV3(
        command.run_id, command.scope, claim.persistence_scope, claim.initiating_subject_id,
        claim.application_command_digest, claim.claim_id, claim.version, claim.status,
    )


def _port_code(code):
    return {
        ApplicationV2PortErrorCode.NOT_FOUND: AnalysisErrorCode.NOT_FOUND,
        ApplicationV2PortErrorCode.SCOPE_MISMATCH: AnalysisErrorCode.SCOPE_MISMATCH,
        ApplicationV2PortErrorCode.CONFLICT: AnalysisErrorCode.PERSISTENCE_CONFLICT,
        ApplicationV2PortErrorCode.INTEGRITY: AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR,
        ApplicationV2PortErrorCode.UNAVAILABLE: AnalysisErrorCode.PERSISTENCE_UNAVAILABLE,
    }[code]
