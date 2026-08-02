"""Milestone 5.0E Step 13 request-scoped analysis router security."""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.analysis_application.ports import AuthorizationDecision
from app.integrations.analysis_http.contracts import ApiRuntimeProfile
from app.security.authorization_adapter import LocalAuthorizationPolicyClient
from app.security.authorization_policy import SubjectReferenceHashCodec
from app.security.contracts import (
    AuthenticationAuditEvent,
    IdentityResolutionError,
    IdentityResolutionErrorCode,
)
from app.security.jwt import (
    JwtProviderUnavailable,
    JwtValidationError,
    extract_bearer_token,
)
from app.security.request_authentication import (
    RequestAuthorizationPlan,
    RequestBoundAuthenticationContextProvider,
    RequestBoundTrustedAuthorizationContextProvider,
)


class RouterAuthenticationErrorCode(str, enum.Enum):
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class RouterAuthenticationError(Exception):
    def __init__(self, code: RouterAuthenticationErrorCode) -> None:
        self.code = code
        super().__init__("Trusted authentication failed.")

    def __repr__(self) -> str:
        return f"RouterAuthenticationError(code={self.code.value!r})"


class AuthenticationAuditEventType(str, enum.Enum):
    AUTHENTICATION_SUCCEEDED = "AUTHENTICATION_SUCCEEDED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    UNTRUSTED_ISSUER_REJECTED = "UNTRUSTED_ISSUER_REJECTED"
    JWT_SIGNATURE_REJECTED = "JWT_SIGNATURE_REJECTED"
    JWKS_REFRESH_FAILED = "JWKS_REFRESH_FAILED"
    TENANT_MEMBERSHIP_REJECTED = "TENANT_MEMBERSHIP_REJECTED"
    PRINCIPAL_REVOKED = "PRINCIPAL_REVOKED"
    MEMBERSHIP_REVOKED = "MEMBERSHIP_REVOKED"


_JWT_AUTHENTICATION_AUDIT = {
    "TOKEN_TIME_REJECTED": AuthenticationAuditEventType.TOKEN_EXPIRED,
    "UNTRUSTED_ISSUER": AuthenticationAuditEventType.UNTRUSTED_ISSUER_REJECTED,
    "SIGNATURE_REJECTED": AuthenticationAuditEventType.JWT_SIGNATURE_REJECTED,
}

_IDENTITY_AUTHENTICATION_AUDIT = {
    IdentityResolutionErrorCode.PRINCIPAL_INACTIVE:
        AuthenticationAuditEventType.PRINCIPAL_REVOKED,
    IdentityResolutionErrorCode.SUBJECT_BINDING_INACTIVE:
        AuthenticationAuditEventType.PRINCIPAL_REVOKED,
    IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE:
        AuthenticationAuditEventType.MEMBERSHIP_REVOKED,
    IdentityResolutionErrorCode.MEMBERSHIP_EXPIRED:
        AuthenticationAuditEventType.MEMBERSHIP_REVOKED,
    IdentityResolutionErrorCode.TOKEN_REVOKED_BY_PRINCIPAL:
        AuthenticationAuditEventType.TOKEN_REVOKED,
    IdentityResolutionErrorCode.TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY:
        AuthenticationAuditEventType.TOKEN_REVOKED,
}


class RequestAuthenticationFactory:
    """Convert one bearer credential into one request-bound trusted provider."""

    is_fake = False
    is_request_bound_factory = True

    def __init__(
        self, *, verifier, identity_repository, security_audit, clock,
        subject_codec, runtime_profile: ApiRuntimeProfile,
    ) -> None:
        if any(value is None for value in (
            verifier, identity_repository, security_audit, clock, subject_codec,
        )):
            raise ValueError("authentication factory dependency is missing")
        self._verifier = verifier
        self._identities = identity_repository
        self._audit = security_audit
        self._clock = clock
        self._subjects = subject_codec
        self.runtime_profile = runtime_profile

    def authenticate(
        self, *, authorization_headers: tuple[str, ...],
        correlation_id: str, request_id: str,
    ) -> RequestBoundAuthenticationContextProvider:
        now = self._clock.now_audit_time()
        verified = None
        try:
            if not authorization_headers:
                raise RouterAuthenticationError(RouterAuthenticationErrorCode.MISSING)
            raw = extract_bearer_token(authorization_headers)
            verified = self._verifier.verify(raw, now=now)
            identity = self._identities.resolve_principal_and_membership(
                issuer=verified.issuer, subject=verified.subject,
                tenant_key=verified.tenant_key, token_issued_at=verified.issued_at,
                expected_principal_kind=verified.token_kind,
                expected_service_client_id=verified.service_client_id,
                correlation_id=correlation_id, request_id=request_id, now=now,
            )
            provider = RequestBoundAuthenticationContextProvider(
                verified_token=verified, verified_identity=identity,
                correlation_id=correlation_id, request_id=request_id,
                runtime_profile=self.runtime_profile,
            )
            self._record_audit(
                AuthenticationAuditEventType.AUTHENTICATION_SUCCEEDED,
                "AUTHENTICATION_SUCCEEDED", correlation_id, request_id, now, verified,
            )
            return provider
        except RouterAuthenticationError as error:
            self._record_failure_audit(
                AuthenticationAuditEventType.AUTHENTICATION_FAILED,
                error.code.value, correlation_id, request_id, now, verified,
            )
            raise
        except JwtProviderUnavailable:
            self._record_failure_audit(
                AuthenticationAuditEventType.JWKS_REFRESH_FAILED,
                "JWKS_REFRESH_FAILED", correlation_id, request_id, now, verified,
            )
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.UNAVAILABLE) from None
        except IdentityResolutionError as error:
            unavailable = {
                IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE,
                IdentityResolutionErrorCode.IDENTITY_STORE_TIMEOUT,
            }
            self._record_failure_audit(
                _IDENTITY_AUTHENTICATION_AUDIT.get(
                    error.code, AuthenticationAuditEventType.TENANT_MEMBERSHIP_REJECTED,
                ),
                error.code.value, correlation_id, request_id, now, verified,
            )
            raise RouterAuthenticationError(
                RouterAuthenticationErrorCode.UNAVAILABLE
                if error.code in unavailable else RouterAuthenticationErrorCode.INVALID
            ) from None
        except JwtValidationError as error:
            self._record_failure_audit(
                _JWT_AUTHENTICATION_AUDIT.get(
                    error.reason, AuthenticationAuditEventType.AUTHENTICATION_FAILED,
                ),
                error.reason, correlation_id, request_id, now, verified,
            )
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.INVALID) from None
        except (TimeoutError, ConnectionError):
            self._record_failure_audit(
                AuthenticationAuditEventType.AUTHENTICATION_FAILED,
                "PROVIDER_UNAVAILABLE", correlation_id, request_id, now, verified,
            )
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.UNAVAILABLE) from None
        except Exception:
            self._record_failure_audit(
                AuthenticationAuditEventType.AUTHENTICATION_FAILED,
                "INTEGRITY_FAILURE", correlation_id, request_id, now, verified,
            )
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.INVALID) from None

    def _record_failure_audit(self, *args) -> None:
        try:
            self._record_audit(*args)
        except RouterAuthenticationError:
            raise
        except Exception:
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.UNAVAILABLE) from None

    def _record_audit(
        self, event_type, reason, correlation_id, request_id, occurred_at, verified,
    ) -> None:
        subject_reference = None
        if verified is not None:
            subject_reference = self._subjects.encode(
                issuer=verified.issuer, tenant_key=verified.tenant_key,
                principal_kind=verified.token_kind,
                provider_subject=verified.subject,
            )
        request_reference = "qar1:" + hashlib.sha256(
            ("qar1\n" + request_id).encode("utf-8")
        ).hexdigest()
        safe_attributes = [
            ("reason_code", reason),
            ("request_reference", request_reference),
        ]
        if subject_reference is not None:
            safe_attributes.append(("subject_reference", subject_reference))
        receipt = self._audit.record_required_event(AuthenticationAuditEvent(
            event_type=event_type.value,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            authority_id="authentication-boundary",
            safe_attributes=tuple(sorted(safe_attributes)),
        ))
        if receipt is None:
            raise RuntimeError("Authentication audit receipt is unavailable.")

    @property
    def trusted_issuers(self) -> frozenset[str]:
        return self._verifier.trusted_issuers

    def readiness_check(self, deadline: datetime) -> bool:
        try:
            return all((
                bool(self._verifier.readiness_check(deadline)),
                bool(self._identities.readiness_check(deadline)),
                bool(self._audit.readiness_check(deadline)),
                bool(self._clock.readiness_check(deadline)),
            ))
        except Exception:
            return False


@dataclass(frozen=True)
class _CachedDecision:
    scope: object
    actor: object
    decision: AuthorizationDecision


class AnalysisRequestSecuritySession:
    """One-request AuthorizationPort/revalidation facade with initial-decision reuse."""

    requires_same_revalidation_instance = True
    is_fake = False

    def __init__(self, client: LocalAuthorizationPolicyClient, subject_codec: SubjectReferenceHashCodec, authentication_provider) -> None:
        self._client = client
        self._subjects = subject_codec
        self._authentication = authentication_provider
        self._cache: dict[str, _CachedDecision] = {}

    @property
    def actor_reference(self) -> str:
        context = self._authentication.current_context()
        profile = self._authentication.trusted_identity_profile()
        return self._subjects.encode(
            issuer=context.trusted_issuer, tenant_key=context.tenant_id,
            principal_kind=profile.principal_kind, provider_subject=context.subject_id,
        )

    def _initial(self, key, method, scope, actor):
        cached = self._cache.get(key)
        if cached is not None:
            if cached.scope != scope or cached.actor != actor:
                return AuthorizationDecision(False, False, "AUTHZ_CONTEXT_INTEGRITY_FAILURE", cached.decision.provider_decision_reference, cached.decision.decided_at)
            return cached.decision
        decision = method(scope, actor)
        self._cache[key] = _CachedDecision(scope, actor, decision)
        return decision

    def authorize_start(self, scope, actor): return self._initial("start", self._client.authorize_start, scope, actor)
    def authorize_resume(self, scope, actor): return self._initial("resume", self._client.authorize_resume, scope, actor)
    def authorize_resume_source(self, source_run_id, target_scope, actor):
        key = f"source:{source_run_id}"
        return self._initial(key, lambda scope, audit: self._client.authorize_resume_source(source_run_id, scope, audit), target_scope, actor)
    def authorize_cancel(self, scope, actor): return self._initial("cancel", self._client.authorize_cancel, scope, actor)
    def authorize_retry(self, scope, actor): return self._initial("retry", self._client.authorize_retry, scope, actor)
    def authorize_read(self, scope, actor, *, include_payload):
        key = f"read:{int(include_payload)}"
        return self._initial(key, lambda s, a: self._client.authorize_read(s, a, include_payload=include_payload), scope, actor)
    def authorize_endpoint(self, action_code, scope, actor):
        return self._initial(f"endpoint:{action_code}", lambda s, a: self._client.authorize_registered_action(action_code, s, a), scope, actor)
    def cache_read_guard(self, scope, actor, decision):
        self._cache["read:0"] = _CachedDecision(scope, actor, decision)
        self._cache["read:1"] = _CachedDecision(scope, actor, decision)
    def cache_cancel_guard(self, scope, actor, decision):
        self._cache["cancel"] = _CachedDecision(scope, actor, decision)
    def revalidate_start(self, scope, actor): return self._client.revalidate_start(scope, actor)
    def revalidate_resume(self, scope, actor): return self._client.revalidate_resume(scope, actor)
    def revalidate_retry(self, scope, actor): return self._client.revalidate_retry(scope, actor)
    def revalidate_resume_source(self, source_run_id, scope, actor): return self._client.revalidate_resume_source(source_run_id, scope, actor)


class RequestBoundAnalysisSecurityFactory:
    is_fake = False

    def __init__(self, *, identity_repository, policy_repository, policy_engine, security_audit, observability, clock, subject_codec, runtime_profile):
        self._identity = identity_repository; self._policy = policy_repository; self._engine = policy_engine
        self._audit = security_audit; self._observability = observability; self._clock = clock
        self._subjects = subject_codec; self.runtime_profile = runtime_profile

    def bind(self, *, authentication_provider, authorization_plan: RequestAuthorizationPlan, trusted_issuers):
        contexts = RequestBoundTrustedAuthorizationContextProvider(
            authentication_provider=authentication_provider,
            authorization_plan=authorization_plan, trusted_issuers=trusted_issuers,
            clock=self._clock, runtime_profile=self.runtime_profile,
        )
        client = LocalAuthorizationPolicyClient(
            context_provider=contexts, identity_repository=self._identity,
            policy_repository=self._policy, policy_engine=self._engine,
            security_audit=self._audit, observability=self._observability,
            clock=self._clock, subject_reference_hash_codec=self._subjects,
            production_mode=self.runtime_profile is ApiRuntimeProfile.PRODUCTION,
        )
        return AnalysisRequestSecuritySession(client, self._subjects, authentication_provider)

    def readiness_check(self, deadline):
        if any(value is None for value in (self._identity, self._policy, self._engine, self._audit, self._clock, self._subjects)):
            return False
        try:
            required = (self._identity, self._policy, self._audit, self._clock)
            return all(
                callable(getattr(value, "readiness_check", None))
                and bool(value.readiness_check(deadline))
                for value in required
            )
        except Exception:
            return False
