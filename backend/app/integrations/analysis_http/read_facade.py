"""HTTP-side typed read coordinator preserving infrastructure categories."""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError, OperationalError

from app.analysis_application.adapters.read import ApplicationReadIntegrityError
from app.analysis_application.contracts import (
    AnalysisErrorCode,
    AnalysisErrorDTO,
    ApplicationErrorCategory,
    ApplicationEventType,
    ApplicationOutcome,
)
from app.analysis_application.ports import (
    ObservabilityEventDTO,
    SecurityAuditEventDTO,
)


_MESSAGES = {
    AnalysisErrorCode.INVALID_QUERY: "The analysis query is invalid.",
    AnalysisErrorCode.UNAUTHORIZED: "The analysis query is not authorized.",
    AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE: "Authorization is temporarily unavailable.",
    AnalysisErrorCode.SECURITY_AUDIT_FAILED: "Required security audit delivery failed.",
    AnalysisErrorCode.NOT_FOUND: "The analysis resource was not found.",
    AnalysisErrorCode.PERSISTENCE_UNAVAILABLE: "Analysis storage is temporarily unavailable.",
    AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR: "Analysis result integrity verification failed.",
    AnalysisErrorCode.INTERNAL_INVARIANT_BREACH: "The analysis query could not be completed.",
}


class ApiAnalysisReadFacade:
    def __init__(self, *, reads, authorization, security_audit, observability, clock) -> None:
        self.reads = reads
        self.authorization = authorization
        self.security_audit = security_audit
        self.observability = observability
        self.clock = clock

    def get_status(self, query):
        return self._one(query, False, lambda: self.reads.get_status(query.run_id, query.scope))

    def get_result(self, query):
        return self._one(
            query, query.include_payloads,
            lambda: self.reads.get_result(query.run_id, query.scope, include_payloads=query.include_payloads),
        )

    def get_execution_detail(self, query):
        return self._one(
            query, query.include_payload,
            lambda: self.reads.get_execution_detail(
                query.run_id, query.engine_code, query.scope, include_payload=query.include_payload,
            ),
        )

    def list_history(self, query):
        return self._one(
            query, False,
            lambda: self.reads.list_history(query.scope, query.cursor, query.limit),
            event=ApplicationEventType.HISTORY_READ,
        )

    def _one(self, query, include_payload, reader, *, event=ApplicationEventType.RESULT_READ):
        try:
            decision = self.authorization.authorize_read(
                query.scope, query.audit_context, include_payload=include_payload,
            )
        except Exception:
            return self._failure(AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE, query.correlation_id)
        if not self._audit(query, ApplicationEventType.AUTHORIZATION_GRANTED if decision.granted else ApplicationEventType.AUTHORIZATION_DENIED, decision.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        if not decision.granted:
            return self._failure(AnalysisErrorCode.UNAUTHORIZED, query.correlation_id)
        if not self._audit(query, event, decision.decision_code):
            return self._failure(AnalysisErrorCode.SECURITY_AUDIT_FAILED, query.correlation_id)
        try:
            value = reader()
        except ValueError:
            return self._failure(AnalysisErrorCode.INVALID_QUERY, query.correlation_id)
        except ApplicationReadIntegrityError:
            return self._failure(AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR, query.correlation_id)
        except (OperationalError, DBAPIError):
            return self._failure(AnalysisErrorCode.PERSISTENCE_UNAVAILABLE, query.correlation_id)
        except Exception:
            return self._failure(AnalysisErrorCode.INTERNAL_INVARIANT_BREACH, query.correlation_id)
        if value is None:
            return self._failure(AnalysisErrorCode.NOT_FOUND, query.correlation_id)
        return ApplicationOutcome(True, value, None, (), query.correlation_id)

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
                self.observability.emit_best_effort_event(
                    ObservabilityEventDTO("required_security_audit_failed", query.correlation_id)
                )
            except Exception:
                pass
            return False

    @staticmethod
    def _failure(code, correlation_id):
        category = {
            AnalysisErrorCode.INVALID_QUERY: ApplicationErrorCategory.VALIDATION,
            AnalysisErrorCode.UNAUTHORIZED: ApplicationErrorCategory.AUTHORIZATION,
            AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE: ApplicationErrorCategory.DEPENDENCY,
            AnalysisErrorCode.SECURITY_AUDIT_FAILED: ApplicationErrorCategory.SECURITY_DEPENDENCY,
            AnalysisErrorCode.NOT_FOUND: ApplicationErrorCategory.NOT_FOUND,
            AnalysisErrorCode.PERSISTENCE_UNAVAILABLE: ApplicationErrorCategory.DEPENDENCY,
            AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR: ApplicationErrorCategory.INTEGRITY,
            AnalysisErrorCode.INTERNAL_INVARIANT_BREACH: ApplicationErrorCategory.INTERNAL,
        }[code]
        retryable = code in {
            AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE,
            AnalysisErrorCode.SECURITY_AUDIT_FAILED,
            AnalysisErrorCode.PERSISTENCE_UNAVAILABLE,
        }
        return ApplicationOutcome(
            False, None,
            AnalysisErrorDTO(code, category, _MESSAGES[code], retryable, correlation_id, {}),
            (), correlation_id,
        )
