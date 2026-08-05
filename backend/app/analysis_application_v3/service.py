"""Synchronous phased Application-v3 Trend use-case coordination."""

from datetime import timezone

from app.analysis_application.contracts import (
    AnalysisErrorCode, ApplicationErrorCategory, ApplicationEventType, ApplicationStatus,
    ApplicationWarningCode,
)
from app.analysis_application.ports import (
    ApplicationClockPort, AuthorizationPort, SecurityAuditEventDTO, SecurityAuditPort,
)
from app.engines.analysis_orchestrator_v4.types import OrchestrationEngineCodeV4
from app.orchestration_persistence_v4.types import (
    PersistTerminalTrendRunCommandV4, PersistenceRunScopeV4,
)

from .contracts import (
    AnalysisCommandResultDTOV3, AnalysisErrorDTOV3, AnalysisExecutionDTOV3, AnalysisWarningDTOV3,
    ApplicationEngineCodeV3, ApplicationOutcomeV3, ApplicationTrendStatusV3,
    ResumeAnalysisCommandV3, RetryAnalysisCommandV3, StartAnalysisCommandV3,
)
from .mapping import to_orchestration_request_v4
from .projection import project_trend_result_v3


class AnalysisApplicationServiceV3:
    def __init__(self, *, orchestrator, persistence, trend_sources, tenant_identities,
                 resume_snapshots,
                 authorization: AuthorizationPort, security_audit: SecurityAuditPort,
                 clock: ApplicationClockPort) -> None:
        self.orchestrator = orchestrator
        self.persistence = persistence
        self.trend_sources = trend_sources
        self.tenant_identities = tenant_identities
        self.resume_snapshots = resume_snapshots
        self.authorization = authorization
        self.security_audit = security_audit
        self.clock = clock

    def start(self, command: StartAnalysisCommandV3, cancellation_probe=None):
        return self._execute(command, self.authorization.authorize_start, ApplicationEventType.START_REQUESTED, cancellation_probe)

    def resume(self, command: ResumeAnalysisCommandV3, cancellation_probe=None):
        return self._execute(command, self.authorization.authorize_resume, ApplicationEventType.RESUME_REQUESTED, cancellation_probe)

    def retry(self, command: RetryAnalysisCommandV3, cancellation_probe=None):
        return self._execute(command, self.authorization.authorize_retry, ApplicationEventType.RETRY_REQUESTED, cancellation_probe)

    def _failure(self, command, code, message):
        error_code = AnalysisErrorCode(code)
        if code in {"UNAUTHORIZED", "AUTHORIZATION_REVOKED", "RESUME_SOURCE_UNAUTHORIZED"}:
            category = ApplicationErrorCategory.AUTHORIZATION
        elif "AUTHORIZATION_PROVIDER" in code or "AUDIT" in code:
            category = ApplicationErrorCategory.SECURITY_DEPENDENCY
        elif code == "EXECUTION_FAILED":
            category = ApplicationErrorCategory.EXECUTION
        elif code in {"SCOPE_MISMATCH", "PERSISTENCE_INTEGRITY_ERROR"}:
            category = ApplicationErrorCategory.INTEGRITY
        else:
            category = ApplicationErrorCategory.INTERNAL
        return ApplicationOutcomeV3(False, None, AnalysisErrorDTOV3(
            error_code,
            category, message,
            code.endswith("UNAVAILABLE"), command.correlation_id, {},
        ), (), command.correlation_id)

    def _audit(self, command, event, decision=None):
        try:
            self.security_audit.record_required_event(SecurityAuditEventDTO(
                event, self.clock.now_audit_time(), command.correlation_id,
                command.scope, command.audit_context.actor_id, command.run_id,
                decision_code=decision,
            ))
            return True
        except Exception:
            return False

    def _execute(self, command, authorize, event, cancellation_probe):
        if not self._audit(command, event):
            return self._failure(command, "SECURITY_AUDIT_FAILED", "Required security audit delivery failed.")
        try: decision = authorize(command.scope, command.audit_context)
        except Exception: return self._failure(command, "AUTHORIZATION_PROVIDER_UNAVAILABLE", "Authorization provider is unavailable.")
        if not decision.granted:
            self._audit(command, ApplicationEventType.AUTHORIZATION_DENIED, decision.decision_code)
            return self._failure(command, "UNAUTHORIZED", "Authorization was denied.")
        if not self._audit(command, ApplicationEventType.AUTHORIZATION_GRANTED, decision.decision_code):
            return self._failure(command, "SECURITY_AUDIT_FAILED", "Required security audit delivery failed.")
        try:
            tenant_id = self.tenant_identities.resolve_tenant_id(command.scope, command.audit_context)
            trend_context = self.trend_sources.resolve_trend_context(
                command.trend_request, command.scope, command.audit_context,
            ) if command.trend_request else None
            if trend_context is not None and (
                trend_context.resolved_series[0].tenant_id != tenant_id
                or trend_context.resolved_series[0].company_id != command.scope.company_id
                or trend_context.resolved_series[0].anchor_period_id != command.scope.financial_period_id
            ):
                return self._failure(command, "SCOPE_MISMATCH", "Resolved Trend source scope does not match the command.")
            resume_binding = None
            if command.scope.previous_run_id is not None:
                resume_decision = self.authorization.authorize_resume_source(
                    command.scope.previous_run_id, command.scope, command.audit_context,
                )
                if not resume_decision.granted:
                    return self._failure(command, "RESUME_SOURCE_UNAUTHORIZED", "Resume source authorization was denied.")
                resume_binding = self.resume_snapshots.load_verified_snapshot(
                    command.scope.previous_run_id, command.scope, command.audit_context,
                )
            request = to_orchestration_request_v4(
                command, trend_context=trend_context,
                previous_snapshot=resume_binding.snapshot if resume_binding else None,
            )
            run_result = self.orchestrator.run(request, cancellation_probe=cancellation_probe)
        except Exception:
            return self._failure(command, "EXECUTION_FAILED", "Analysis execution failed.")
        try: revalidated = authorize(command.scope, command.audit_context)
        except Exception: return self._failure(command, "AUTHORIZATION_PROVIDER_UNAVAILABLE", "Authorization provider is unavailable.")
        if not revalidated.granted:
            self._audit(command, ApplicationEventType.AUTHORIZATION_DENIED, revalidated.decision_code)
            return self._failure(command, "AUTHORIZATION_REVOKED" if revalidated.revoked else "UNAUTHORIZED", "Authorization is no longer valid.")
        if trend_context is None:
            return self._failure(command, "INTERNAL_INVARIANT_BREACH", "Trend context is missing.")
        try:
            persisted = self.persistence.persist_terminal_run(PersistTerminalTrendRunCommandV4(
                PersistenceRunScopeV4(
                    tenant_id, command.scope.company_id, command.scope.financial_period_id,
                    command.audit_context.actor_id,
                ),
                run_result, trend_context.lineage, trend_context.source_set_digest,
                trend_context.resolution_digest,
                resume_binding.financial_analysis_result_id if resume_binding else None,
                resume_binding.owner_content_digest if resume_binding else None,
            ))
        except Exception:
            return self._failure(command, "PERSISTENCE_INTEGRITY_ERROR", "Terminal persistence failed.")
        post_commit_audit_ok = self._audit(command, ApplicationEventType.TERMINAL_RUN_PERSISTED)
        trend_record = next(item for item in run_result.engine_records if item.engine_code is OrchestrationEngineCodeV4.MULTI_PERIOD_TREND)
        try:
            projection = project_trend_result_v3(trend_record.result.result)
        except Exception:
            return self._failure(command, "DTO_PROJECTION_FAILED", "The persisted result can be recovered by run id.")
        execution = AnalysisExecutionDTOV3(
            ApplicationEngineCodeV3.MULTI_PERIOD_TREND,
            __import__("app.analysis_application.contracts", fromlist=["ApplicationExecutionStatus"]).ApplicationExecutionStatus(trend_record.status.value),
            trend_record.inner_status_value, trend_record.engine_schema_version_used,
            trend_record.engine_model_version_used, trend_record.input_fingerprint, projection,
        )
        now = self.clock.now_audit_time().astimezone(timezone.utc)
        value = AnalysisCommandResultDTOV3(
            command.run_id, ApplicationStatus(run_result.status.value), run_result.request_fingerprint,
            persisted.owner_content_digest, command.scope, (execution,), now,
            persisted.idempotent_replay, command.run_id,
        )
        warnings = () if post_commit_audit_ok else (AnalysisWarningDTOV3(
            ApplicationWarningCode.SECURITY_AUDIT_POST_COMMIT_FAILED,
            "The terminal run was persisted; post-commit security audit delivery failed.",
            True,
        ),)
        return ApplicationOutcomeV3(True, value, None, warnings, command.correlation_id)
