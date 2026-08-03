"""Scope-qualified, authorized and audited Application-v2 read use cases."""

from __future__ import annotations

from app.analysis_application.contracts import AnalysisErrorCode, ApplicationEventType
from app.analysis_application.errors import ERROR_POLICIES
from app.analysis_application.ports import ObservabilityEventDTO, SecurityAuditEventDTO

from .contracts import (
    AnalysisErrorDTOV2,
    ApplicationOutcomeV2,
    GetAnalysisResultQueryV2,
    GetAnalysisStatusQueryV2,
    GetExecutionDetailQueryV2,
    ListAnalysisHistoryQueryV2,
)
from .ports import ApplicationV2PortError, ApplicationV2PortErrorCode


class AnalysisQueryServiceV2:
    def __init__(self, *, authorization, security_audit, observability, clock, tenant_scopes, reads) -> None:
        self.authorization = authorization
        self.security_audit = security_audit
        self.observability = observability
        self.clock = clock
        self.tenant_scopes = tenant_scopes
        self.reads = reads

    def get_status(self, query: GetAnalysisStatusQueryV2):
        return self._one(query, False, lambda verified: self.reads.get_status(query.run_id, query.scope, verified))

    def get_result(self, query: GetAnalysisResultQueryV2):
        return self._one(query, query.include_payloads, lambda verified: self.reads.get_result(query.run_id, query.scope, verified, include_payloads=query.include_payloads))

    def get_execution_detail(self, query: GetExecutionDetailQueryV2):
        return self._one(query, query.include_payload, lambda verified: self.reads.get_execution_detail(query.run_id, query.engine_code, query.scope, verified, include_payload=query.include_payload))

    def list_history(self, query: ListAnalysisHistoryQueryV2):
        authorized = self._preflight(query, False)
        if isinstance(authorized, ApplicationOutcomeV2):
            return authorized
        decision, verified = authorized
        if not self._audit(query, ApplicationEventType.HISTORY_READ, decision.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        try:
            value = self.reads.list_history(query.scope, verified, query.cursor, query.limit)
            return ApplicationOutcomeV2(True, value, None, (), query.correlation_id)
        except ValueError:
            return self._failure(AnalysisErrorCode.INVALID_QUERY, query.correlation_id)
        except ApplicationV2PortError as error:
            return self._failure(_read_code(error.code), query.correlation_id)
        except Exception:
            return self._failure(AnalysisErrorCode.INTERNAL_INVARIANT_BREACH, query.correlation_id)

    def _one(self, query, include_payload, reader):
        authorized = self._preflight(query, include_payload)
        if isinstance(authorized, ApplicationOutcomeV2):
            return authorized
        decision, verified = authorized
        if not self._audit(query, ApplicationEventType.RESULT_READ, decision.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        try:
            value = reader(verified)
        except ApplicationV2PortError as error:
            return self._failure(_read_code(error.code), query.correlation_id)
        except Exception:
            return self._failure(AnalysisErrorCode.INTERNAL_INVARIANT_BREACH, query.correlation_id)
        if value is None:
            return self._failure(AnalysisErrorCode.NOT_FOUND, query.correlation_id)
        return ApplicationOutcomeV2(True, value, None, (), query.correlation_id)

    def _preflight(self, query, include_payload):
        try:
            verified = self.tenant_scopes.resolve(query.scope, query.audit_context)
        except Exception:
            return self._failure(AnalysisErrorCode.SCOPE_MISMATCH, query.correlation_id)
        try:
            decision = self.authorization.authorize_read(
                query.scope, query.audit_context, include_payload=include_payload,
            )
        except Exception:
            self._audit(query, ApplicationEventType.AUTHORIZATION_DENIED, AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE.value)
            return self._failure(AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE, query.correlation_id)
        event = ApplicationEventType.AUTHORIZATION_GRANTED if decision.granted else ApplicationEventType.AUTHORIZATION_DENIED
        if not self._audit(query, event, decision.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        if not decision.granted:
            return self._failure(AnalysisErrorCode.UNAUTHORIZED, query.correlation_id)
        return decision, verified

    def _audit(self, query, event, decision_code):
        try:
            self.security_audit.record_required_event(SecurityAuditEventDTO(
                event, self.clock.now_audit_time(), query.correlation_id, query.scope,
                query.audit_context.actor_id, getattr(query, "run_id", None), decision_code,
            ))
            return True
        except Exception:
            try:
                self.observability.emit_best_effort_event(ObservabilityEventDTO(
                    "required_security_audit_failed", query.correlation_id,
                ))
            except Exception:
                pass
            return False

    @staticmethod
    def _failure(code, correlation_id):
        policy = ERROR_POLICIES[code]
        return ApplicationOutcomeV2(False, None, AnalysisErrorDTOV2(
            code, None, policy.category, "The analysis query could not be completed.",
            policy.retryable, correlation_id, {},
        ), (), correlation_id)


def _read_code(code):
    return {
        ApplicationV2PortErrorCode.NOT_FOUND: AnalysisErrorCode.NOT_FOUND,
        ApplicationV2PortErrorCode.SCOPE_MISMATCH: AnalysisErrorCode.SCOPE_MISMATCH,
        ApplicationV2PortErrorCode.CONFLICT: AnalysisErrorCode.PERSISTENCE_CONFLICT,
        ApplicationV2PortErrorCode.INTEGRITY: AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR,
        ApplicationV2PortErrorCode.UNAVAILABLE: AnalysisErrorCode.PERSISTENCE_UNAVAILABLE,
    }[code]
