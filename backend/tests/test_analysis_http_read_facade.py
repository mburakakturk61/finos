from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.analysis_application.adapters.read import ApplicationReadIntegrityError
from app.analysis_application.contracts import (
    AnalysisErrorCode,
    ApplicationAuditContextDTO,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
    GetAnalysisStatusQuery,
)
from app.analysis_application.ports import AuthorizationDecision, SecurityAuditReceiptDTO
from app.integrations.analysis_http.read_facade import ApiAnalysisReadFacade


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Authorization:
    def authorize_read(self, scope, actor, *, include_payload):
        return AuthorizationDecision(True, False, "grant", "decision", NOW)


class _Audit:
    def record_required_event(self, event):
        return SecurityAuditReceiptDTO("receipt", event.event_type, NOW, "a" * 64)


class _Observability:
    def emit_best_effort_event(self, event): pass


class _Clock:
    def now_audit_time(self): return NOW


class _Reads:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def get_status(self, run_id, scope):
        if self.error:
            raise self.error
        return self.result


def _query():
    scope = ApplicationScopeDTO(
        uuid.uuid4(), uuid.uuid4(), "tenant",
        ApplicationOperationKind.START, ApplicationOriginalOperation.START,
    )
    audit = ApplicationAuditContextDTO("subject", "USER", "HTTP", "READ")
    return GetAnalysisStatusQuery("run-1", "corr", NOW, scope, audit, "auth-ref")


def _facade(reads):
    return ApiAnalysisReadFacade(
        reads=reads, authorization=_Authorization(), security_audit=_Audit(),
        observability=_Observability(), clock=_Clock(),
    )


@pytest.mark.parametrize(
    ("reads", "expected"),
    (
        (_Reads(result=None), AnalysisErrorCode.NOT_FOUND),
        (
            _Reads(error=OperationalError("SELECT secret", {}, RuntimeError("db secret"))),
            AnalysisErrorCode.PERSISTENCE_UNAVAILABLE,
        ),
        (
            _Reads(error=ApplicationReadIntegrityError("integrity secret")),
            AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR,
        ),
        (_Reads(error=RuntimeError("upstream secret")), AnalysisErrorCode.INTERNAL_INVARIANT_BREACH),
    ),
)
def test_read_facade_preserves_error_category_and_redacts_raw_exception(reads, expected):
    outcome = _facade(reads).get_status(_query())
    assert outcome.success is False
    assert outcome.error.code is expected
    assert "secret" not in outcome.error.message.lower()
