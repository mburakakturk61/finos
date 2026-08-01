"""Runtime-profile validation and production integration adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.analysis_application.ports import AuthorizationDecision
from app.integrations.analysis_http.contracts import ApiRuntimeProfile


class UtcApplicationClockAdapter:
    runtime_profile = ApiRuntimeProfile.PRODUCTION
    is_fake = False
    is_noop = False

    def now_audit_time(self) -> datetime:
        return datetime.now(timezone.utc)

    def resolve_business_time(self, caller_supplied: datetime | None) -> datetime:
        if caller_supplied is None:
            return self.now_audit_time()
        if caller_supplied.tzinfo is None or caller_supplied.utcoffset() is None:
            raise ValueError("Business time must be timezone-aware.")
        return caller_supplied

    def readiness_check(self, deadline: datetime) -> bool:
        return self.now_audit_time().tzinfo is not None


class ExternalAuthorizationAdapter:
    runtime_profile = ApiRuntimeProfile.PRODUCTION
    is_fake = False
    is_allow_all = False
    is_noop = False

    def __init__(self, policy_client, *, timeout_seconds: float = 2.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Authorization timeout must be positive.")
        self.policy_client = policy_client
        self.timeout_seconds = timeout_seconds

    def _decide(self, action, scope, actor, **context):
        decision = self.policy_client.decide(
            action=action, scope=scope, actor=actor,
            timeout_seconds=self.timeout_seconds, **context,
        )
        if not isinstance(decision, AuthorizationDecision):
            raise RuntimeError("Authorization provider returned an invalid decision.")
        return decision

    def authorize_start(self, scope, actor): return self._decide("START", scope, actor)
    def authorize_resume(self, scope, actor): return self._decide("RESUME", scope, actor)
    def authorize_resume_source(self, source_run_id, target_scope, actor):
        return self._decide("RESUME_SOURCE", target_scope, actor, source_run_id=source_run_id)
    def authorize_read(self, scope, actor, *, include_payload):
        return self._decide("READ", scope, actor, include_payload=include_payload)
    def authorize_cancel(self, scope, actor): return self._decide("CANCEL", scope, actor)
    def authorize_retry(self, scope, actor): return self._decide("RETRY", scope, actor)

    def readiness_check(self, deadline):
        return bool(self.policy_client.readiness_check(deadline=deadline))


class DurableSecurityAuditAdapter:
    runtime_profile = ApiRuntimeProfile.PRODUCTION
    is_fake = False
    is_noop = False

    def __init__(self, audit_client, *, timeout_seconds: float = 3.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Security audit timeout must be positive.")
        self.audit_client = audit_client
        self.timeout_seconds = timeout_seconds

    def record_required_event(self, event):
        return self.audit_client.append(event=event, timeout_seconds=self.timeout_seconds)

    def readiness_check(self, deadline):
        return bool(self.audit_client.readiness_check(deadline=deadline))


class LoggingObservabilityAdapter:
    runtime_profile = ApiRuntimeProfile.PRODUCTION
    is_fake = False
    is_noop = False

    def __init__(self) -> None:
        self.logger = logging.getLogger("analysis_api.observability")

    def emit_best_effort_event(self, event) -> None:
        self.logger.info("analysis_event=%s correlation_id=%s", event.event_name, event.correlation_id)

    def increment_metric(self, name, value, tags) -> None:
        self.logger.info("analysis_metric=%s value=%s tags=%s", name, value, tuple(tags))

    def record_timing(self, name, duration_ms, tags) -> None:
        self.logger.info("analysis_timing=%s duration_ms=%s tags=%s", name, duration_ms, tuple(tags))

    def readiness_check(self, deadline):
        return True


@dataclass(frozen=True)
class ProductionIntegrationBindings:
    authentication_context_provider: object
    authorization: object
    security_audit: object
    observability: object
    clock: object
    document_inputs: object
    result_inputs: object
    admission: object
    cursor_codec: object


class ProductionCompositionError(RuntimeError):
    pass


def validate_runtime_bindings(profile: ApiRuntimeProfile, bindings: ProductionIntegrationBindings) -> None:
    values = tuple(bindings.__dict__.values())
    if any(value is None for value in values):
        raise ProductionCompositionError("Required analysis API binding is missing.")
    if profile is not ApiRuntimeProfile.PRODUCTION:
        return
    forbidden = (
        getattr(bindings.authentication_context_provider, "is_fake", False),
        getattr(bindings.authorization, "is_fake", False),
        getattr(bindings.authorization, "is_allow_all", False),
        getattr(bindings.security_audit, "is_fake", False),
        getattr(bindings.security_audit, "is_noop", False),
        getattr(bindings.observability, "is_noop", False),
    )
    if any(forbidden):
        raise ProductionCompositionError("Unsafe adapter is forbidden in production.")
    required_methods = {
        "authentication_context_provider": ("current_context", "readiness_check"),
        "authorization": (
            "authorize_start", "authorize_resume", "authorize_resume_source",
            "authorize_read", "authorize_cancel", "authorize_retry", "readiness_check",
        ),
        "security_audit": ("record_required_event", "readiness_check"),
        "observability": ("emit_best_effort_event", "readiness_check"),
        "clock": ("now_audit_time", "resolve_business_time", "readiness_check"),
        "document_inputs": ("resolve_document_input", "readiness_check"),
        "result_inputs": ("resolve_trial_balance_input", "readiness_check"),
        "admission": ("try_acquire", "release", "readiness_check"),
        "cursor_codec": ("encode", "decode", "readiness_check"),
    }
    for name, methods in required_methods.items():
        binding = getattr(bindings, name)
        if any(not callable(getattr(binding, method, None)) for method in methods):
            raise ProductionCompositionError(f"Required production binding is invalid: {name}")
