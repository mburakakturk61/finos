from datetime import datetime, timezone

import pytest

from app.integrations.analysis_http.contracts import ApiRuntimeProfile
from app.integrations.analysis_http.dependencies import AnalysisApiRuntime


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ISSUERS = frozenset({"https://issuer.example"})


class _Binding:
    is_fake = False
    is_allow_all = False
    is_noop = False

    def __init__(self, *, ready=True):
        self.ready = ready

    def readiness_check(self, _deadline): return self.ready
    def current_context(self): raise RuntimeError("request-bound authentication is required")
    def authenticate(self, **_kwargs): return object()
    def authorize_start(self, *_args, **_kwargs): return object()
    def authorize_resume(self, *_args, **_kwargs): return object()
    def authorize_resume_source(self, *_args, **_kwargs): return object()
    def authorize_read(self, *_args, **_kwargs): return object()
    def authorize_cancel(self, *_args, **_kwargs): return object()
    def authorize_retry(self, *_args, **_kwargs): return object()
    def record_required_event(self, *_args, **_kwargs): return object()
    def emit_best_effort_event(self, *_args, **_kwargs): return None
    def now_audit_time(self): return NOW
    def resolve_business_time(self, value): return value or NOW
    def resolve_document_input(self, **_kwargs): return object()
    def resolve_trial_balance_input(self, **_kwargs): return object()
    def try_acquire(self, **_kwargs): return object()
    def release(self, _lease): return None
    def encode(self, **_kwargs): return "cursor"
    def decode(self, *_args, **_kwargs): return "cursor"
    def bind(self, **_kwargs): return object()
    def authorize(self, **_kwargs): return object()


class _RequestAuthentication(_Binding):
    trusted_issuers = ISSUERS


class _LegacySecurity(_Binding):
    retry_after_seconds = 1


def _runtime(*, audit_ready=True, observability_ready=True, auth_factory=None, legacy=None):
    return AnalysisApiRuntime(
        profile=ApiRuntimeProfile.PRODUCTION,
        trusted_issuers=ISSUERS,
        authentication_context_provider=_Binding(ready=False),
        authorization=_Binding(),
        security_audit=_Binding(ready=audit_ready),
        observability=_Binding(ready=observability_ready),
        clock=_Binding(),
        document_inputs=_Binding(),
        result_inputs=_Binding(),
        admission=_Binding(),
        cursor_codec=_Binding(),
        ownership_inspector=object(),
        session_factory=object(),
        blob_store=object(),
        active_executions=object(),
        request_authentication_factory=auth_factory or _RequestAuthentication(),
        request_security_factory=_Binding(),
        legacy_security=legacy or _LegacySecurity(),
    )


def test_production_runtime_uses_request_authentication_readiness_not_obsolete_global_provider():
    runtime = _runtime()
    runtime.validate()
    assert runtime.readiness_check() is True


def test_required_audit_outage_blocks_readiness_but_observability_outage_does_not():
    assert _runtime(audit_ready=False).readiness_check() is False
    assert _runtime(observability_ready=False).readiness_check() is True


def test_issuer_registry_mismatch_is_startup_failure():
    authentication = _RequestAuthentication()
    authentication.trusted_issuers = frozenset({"https://attacker.example"})
    runtime = _runtime(auth_factory=authentication)
    with pytest.raises(ValueError, match="issuer registry"):
        runtime.validate()
    assert runtime.readiness_check() is False


def test_fake_or_incomplete_legacy_security_is_production_failure():
    fake = _LegacySecurity()
    fake.is_fake = True
    with pytest.raises(ValueError, match="request security"):
        _runtime(legacy=fake).validate()

    incomplete = _Binding()
    incomplete.authorize = None
    with pytest.raises(ValueError, match="legacy security"):
        _runtime(legacy=incomplete).validate()


def test_missing_non_http_runtime_binding_is_fail_closed():
    runtime = _runtime()
    object.__setattr__(runtime, "blob_store", None)
    with pytest.raises(ValueError, match="runtime binding"):
        runtime.validate()
    assert runtime.readiness_check() is False
