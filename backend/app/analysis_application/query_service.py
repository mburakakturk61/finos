"""Authorized, audited public query use cases over the canonical read port."""

from __future__ import annotations

from app.analysis_application.contracts import (
    AnalysisErrorCode, AnalysisErrorDTO, ApplicationEventType, ApplicationOutcome,
    GetAnalysisResultQuery, GetAnalysisStatusQuery, GetExecutionDetailQuery,
    ListAnalysisHistoryQuery,
)
from app.analysis_application.errors import ERROR_POLICIES
from app.analysis_application.ports import SecurityAuditEventDTO


class AnalysisQueryService:
    def __init__(self, *, authorization, security_audit, observability, clock, reads) -> None:
        self.authorization = authorization
        self.security_audit = security_audit
        self.observability = observability
        self.clock = clock
        self.reads = reads

    def get_status(self, query: GetAnalysisStatusQuery):
        return self._one(query, False, lambda: self.reads.get_status(query.run_id, query.scope))

    def get_result(self, query: GetAnalysisResultQuery):
        return self._one(query, query.include_payloads, lambda: self.reads.get_result(query.run_id, query.scope, include_payloads=query.include_payloads))

    def get_execution_detail(self, query: GetExecutionDetailQuery):
        return self._one(query, query.include_payload, lambda: self.reads.get_execution_detail(query.run_id, query.engine_code, query.scope, include_payload=query.include_payload))

    def list_history(self, query: ListAnalysisHistoryQuery):
        authorized = self._authorize(query, False)
        if isinstance(authorized, ApplicationOutcome): return authorized
        if not self._audit(query, ApplicationEventType.HISTORY_READ, authorized.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        try:
            value = self.reads.list_history(query.scope, query.cursor, query.limit)
            return ApplicationOutcome(True, value, None, (), query.correlation_id)
        except ValueError:
            return self._failure(AnalysisErrorCode.INVALID_QUERY, query.correlation_id)
        except Exception:
            return self._failure(AnalysisErrorCode.PERSISTENCE_UNAVAILABLE, query.correlation_id)

    def _one(self, query, include_payload, reader):
        authorized = self._authorize(query, include_payload)
        if isinstance(authorized, ApplicationOutcome): return authorized
        if not self._audit(query, ApplicationEventType.RESULT_READ, authorized.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        try:
            value = reader()
        except Exception:
            return self._failure(AnalysisErrorCode.NOT_FOUND, query.correlation_id)
        if value is None:
            return self._failure(AnalysisErrorCode.NOT_FOUND, query.correlation_id)
        return ApplicationOutcome(True, value, None, (), query.correlation_id)

    def _authorize(self, query, include_payload):
        try:
            decision = self.authorization.authorize_read(query.scope, query.audit_context, include_payload=include_payload)
        except Exception:
            if not self._audit(query, ApplicationEventType.AUTHORIZATION_DENIED, AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE.value):
                return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
            return self._failure(AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE, query.correlation_id)
        event = ApplicationEventType.AUTHORIZATION_GRANTED if decision.granted else ApplicationEventType.AUTHORIZATION_DENIED
        if not self._audit(query, event, decision.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        if not decision.granted:
            return self._failure(AnalysisErrorCode.UNAUTHORIZED, query.correlation_id)
        return decision

    def _audit(self, query, event, decision_code):
        try:
            self.security_audit.record_required_event(SecurityAuditEventDTO(
                event, self.clock.now_audit_time(), query.correlation_id,
                query.scope, query.audit_context.actor_id,
                getattr(query, "run_id", None), decision_code,
            ))
            return True
        except Exception:
            try:
                from app.analysis_application.ports import ObservabilityEventDTO
                self.observability.emit_best_effort_event(ObservabilityEventDTO("required_security_audit_failed", query.correlation_id))
            except Exception:
                pass
            return False

    @staticmethod
    def _failure(code, correlation_id):
        policy = ERROR_POLICIES[code]
        error = AnalysisErrorDTO(code, policy.category, "The analysis query could not be completed.", policy.retryable, correlation_id, {})
        return ApplicationOutcome(False, None, error, (), correlation_id)
