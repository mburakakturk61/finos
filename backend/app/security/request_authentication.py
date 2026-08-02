"""Milestone 5.0E Step 12 request-bound authentication/authorization bridge."""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.analysis_application.contracts import (
    ApplicationAuditContextDTO,
    ApplicationScopeDTO,
)
from app.integrations.analysis_http.contracts import (
    ApiRuntimeProfile,
    AuthenticationContext,
    AuthenticationContextError,
    AuthenticationProviderUnavailable,
    AuthenticationStrength,
)
from app.security.authorization_adapter import (
    AuthorizationCheckpoint,
    TrustedAuthorizationContext,
    TrustedAuthorizationContextError,
    TrustedAuthorizationContextErrorCode,
)
from app.security.authorization_policy import (
    PolicyAuthenticationStrength,
    PolicyScopeType,
    ResourceSecurityReference,
)
from app.security.contracts import (
    CLAIMS_VERSION,
    SAFE_CORRELATION_PATTERN,
    SERVICE_CLIENT_PATTERN,
    TENANT_KEY_PATTERN,
    IdentityKind,
    VerifiedJwt,
    VerifiedLocalIdentity,
)


_MAX_CONTEXT_AGE = timedelta(minutes=15)
_FUTURE_SKEW = timedelta(seconds=60)
_AUTHORIZATION_REFERENCE = re.compile(
    r"^authz:v1:(H|S):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]*):([1-9][0-9]*)$"
)
_RESOURCE_VERSION = re.compile(r"^rsv1:[0-9a-f]{64}$")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, repr=False)
class TrustedRequestIdentityProfile:
    principal_kind: IdentityKind
    service_client_id: str | None
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.principal_kind, IdentityKind):
            raise ValueError("request principal kind is invalid")
        if not isinstance(self.request_id, str) or not SAFE_CORRELATION_PATTERN.fullmatch(self.request_id):
            raise ValueError("request identifier is invalid")
        if self.principal_kind is IdentityKind.HUMAN:
            if self.service_client_id is not None:
                raise ValueError("human request profile is invalid")
        elif (
            not isinstance(self.service_client_id, str)
            or not SERVICE_CLIENT_PATTERN.fullmatch(self.service_client_id)
        ):
            raise ValueError("service request profile is invalid")

    def __repr__(self) -> str:
        return f"TrustedRequestIdentityProfile(principal_kind={self.principal_kind.value!r})"


@dataclass(frozen=True, repr=False)
class RequestAuthorizationTarget:
    checkpoint: AuthorizationCheckpoint
    scope_type: PolicyScopeType
    resource_id: uuid.UUID | str
    tenant_key: str
    company_id: uuid.UUID | None = None
    period_id: uuid.UUID | None = None
    expected_resource_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, AuthorizationCheckpoint):
            raise ValueError("authorization target checkpoint is invalid")
        if self.scope_type not in {PolicyScopeType.COMPANY_PERIOD, PolicyScopeType.ANALYSIS_RUN}:
            raise ValueError("authorization target scope is invalid")
        if not isinstance(self.tenant_key, str) or not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("authorization target tenant is invalid")
        if self.expected_resource_version is not None and not _RESOURCE_VERSION.fullmatch(self.expected_resource_version):
            raise ValueError("authorization target version is invalid")
        expected_scope = _CHECKPOINT_SCOPE[self.checkpoint]
        if self.scope_type is not expected_scope and not (
            self.checkpoint is AuthorizationCheckpoint.READ
            and self.scope_type is PolicyScopeType.COMPANY_PERIOD
        ):
            raise ValueError("authorization target does not match checkpoint")
        if self.scope_type is PolicyScopeType.COMPANY_PERIOD:
            if not isinstance(self.company_id, uuid.UUID) or not isinstance(self.period_id, uuid.UUID):
                raise ValueError("company-period target identifiers are invalid")
            if self.resource_id != f"cp1:{self.company_id}:{self.period_id}":
                raise ValueError("company-period target resource is invalid")
        elif (
            not isinstance(self.resource_id, str)
            or not self.resource_id
            or self.company_id is not None
            or self.period_id is not None
        ):
            raise ValueError("analysis-run target is invalid")

    def __repr__(self) -> str:
        return (
            f"RequestAuthorizationTarget(checkpoint={self.checkpoint.value!r}, "
            f"scope_type={self.scope_type.value!r}, resource_id='<redacted>')"
        )


_CHECKPOINT_SCOPE = {
    AuthorizationCheckpoint.START: PolicyScopeType.COMPANY_PERIOD,
    AuthorizationCheckpoint.RESUME: PolicyScopeType.COMPANY_PERIOD,
    AuthorizationCheckpoint.RETRY: PolicyScopeType.COMPANY_PERIOD,
    AuthorizationCheckpoint.PRE_PERSIST_START: PolicyScopeType.COMPANY_PERIOD,
    AuthorizationCheckpoint.PRE_PERSIST_RESUME: PolicyScopeType.COMPANY_PERIOD,
    AuthorizationCheckpoint.PRE_PERSIST_RETRY: PolicyScopeType.COMPANY_PERIOD,
    AuthorizationCheckpoint.RESUME_SOURCE: PolicyScopeType.ANALYSIS_RUN,
    AuthorizationCheckpoint.PRE_PERSIST_RESUME_SOURCE: PolicyScopeType.ANALYSIS_RUN,
    AuthorizationCheckpoint.CANCEL: PolicyScopeType.ANALYSIS_RUN,
    AuthorizationCheckpoint.READ: PolicyScopeType.ANALYSIS_RUN,
}


@dataclass(frozen=True, repr=False)
class RequestAuthorizationPlan:
    targets: tuple[RequestAuthorizationTarget, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.targets, tuple) or not self.targets:
            raise ValueError("authorization plan must be a non-empty tuple")
        if any(not isinstance(item, RequestAuthorizationTarget) for item in self.targets):
            raise ValueError("authorization plan target is invalid")
        checkpoints = tuple(item.checkpoint for item in self.targets)
        if len(checkpoints) != len(set(checkpoints)):
            raise ValueError("authorization plan has duplicate checkpoints")
        order = {value: index for index, value in enumerate(AuthorizationCheckpoint)}
        if checkpoints != tuple(sorted(checkpoints, key=order.__getitem__)):
            raise ValueError("authorization plan must be canonically ordered")

    def target_for(self, checkpoint: AuthorizationCheckpoint) -> RequestAuthorizationTarget:
        for target in self.targets:
            if target.checkpoint is checkpoint:
                return target
        raise TrustedAuthorizationContextError(
            TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID
        )

    def __repr__(self) -> str:
        return f"RequestAuthorizationPlan(checkpoints={tuple(item.checkpoint.value for item in self.targets)!r})"


class RequestBoundAuthenticationContextProvider:
    """Immutable 5.0D provider built only from verified token and local identity outputs."""

    __slots__ = ("_context", "_identity_profile", "_runtime_profile")
    is_fake = False
    is_request_bound = True

    def __init__(
        self,
        *,
        verified_token: VerifiedJwt,
        verified_identity: VerifiedLocalIdentity,
        correlation_id: str,
        request_id: str,
        runtime_profile: ApiRuntimeProfile,
    ) -> None:
        if not isinstance(verified_token, VerifiedJwt) or not isinstance(verified_identity, VerifiedLocalIdentity):
            raise ValueError("verified authentication inputs are invalid")
        if not isinstance(runtime_profile, ApiRuntimeProfile):
            raise ValueError("runtime profile is invalid")
        if not SAFE_CORRELATION_PATTERN.fullmatch(correlation_id) or not SAFE_CORRELATION_PATTERN.fullmatch(request_id):
            raise ValueError("request correlation is invalid")
        if verified_token.claims_version != CLAIMS_VERSION:
            raise ValueError("claims version is invalid")
        if (
            verified_token.issuer != verified_identity.provider_issuer
            or verified_token.subject != verified_identity.provider_subject
            or verified_token.tenant_key != verified_identity.tenant_key
            or verified_token.token_kind is not verified_identity.principal_kind
        ):
            raise ValueError("verified token and identity binding is invalid")
        issued_at = _utc(verified_token.issued_at)
        expires_at = _utc(verified_token.expires_at)
        if expires_at <= issued_at or issued_at < max(
            verified_identity.tokens_valid_after,
            verified_identity.membership_valid_from,
        ):
            raise ValueError("verified token validity binding is invalid")
        kind = verified_identity.principal_kind
        if kind is IdentityKind.HUMAN:
            if verified_token.service_client_id is not None:
                raise ValueError("human token profile is invalid")
            method = "oidc_bearer_jwt"
        else:
            if (
                not isinstance(verified_token.service_client_id, str)
                or not SERVICE_CLIENT_PATTERN.fullmatch(verified_token.service_client_id)
                or verified_token.authentication_strength is not AuthenticationStrength.STRONG
            ):
                raise ValueError("service token profile is invalid")
            method = "oauth2_client_credentials_jwt"
        kind_code = "H" if kind is IdentityKind.HUMAN else "S"
        reference = (
            f"authz:v1:{kind_code}:{verified_identity.membership_id}:"
            f"{verified_identity.membership_version}:{verified_identity.tenant_policy_version}"
        )
        self._context = AuthenticationContext(
            subject_id=verified_token.subject,
            tenant_id=verified_token.tenant_key,
            authentication_method=method,
            authentication_strength=verified_token.authentication_strength,
            issued_at=issued_at,
            expires_at=expires_at,
            correlation_id=correlation_id,
            claims_version=verified_token.claims_version,
            trusted_issuer=verified_token.issuer,
            authorization_context_reference=reference,
        )
        self._identity_profile = TrustedRequestIdentityProfile(
            principal_kind=kind,
            service_client_id=verified_token.service_client_id,
            request_id=request_id,
        )
        self._runtime_profile = runtime_profile

    @property
    def runtime_profile(self) -> ApiRuntimeProfile:
        return self._runtime_profile

    def current_context(self) -> AuthenticationContext:
        return self._context

    def trusted_identity_profile(self) -> TrustedRequestIdentityProfile:
        return self._identity_profile

    def readiness_check(self, deadline: datetime) -> bool:
        try:
            _utc(deadline)
        except ValueError:
            return False
        return True

    def __repr__(self) -> str:
        return f"RequestBoundAuthenticationContextProvider(profile={self.runtime_profile.value!r}, identity='<redacted>')"


class RequestBoundTrustedAuthorizationContextProvider:
    """Request-local bridge consumed by the Step 11 authorization adapter."""

    __slots__ = (
        "_authentication", "_plan", "_issuers", "_clock", "_runtime_profile",
        "_snapshot", "_cache", "_lock",
    )
    is_fake = False
    is_request_bound = True

    def __init__(
        self,
        *,
        authentication_provider: object,
        authorization_plan: RequestAuthorizationPlan,
        trusted_issuers: frozenset[str],
        clock: object,
        runtime_profile: ApiRuntimeProfile,
    ) -> None:
        if not isinstance(authorization_plan, RequestAuthorizationPlan):
            raise ValueError("request authorization plan is invalid")
        if not isinstance(runtime_profile, ApiRuntimeProfile):
            raise ValueError("runtime profile is invalid")
        if not isinstance(trusted_issuers, frozenset) or not trusted_issuers:
            raise ValueError("trusted issuer allowlist is required")
        required = ("current_context", "trusted_identity_profile", "readiness_check")
        if any(not callable(getattr(authentication_provider, name, None)) for name in required):
            raise ValueError("request-bound authentication provider is invalid")
        if runtime_profile is ApiRuntimeProfile.PRODUCTION and (
            getattr(authentication_provider, "is_fake", False)
            or not getattr(authentication_provider, "is_request_bound", False)
            or getattr(authentication_provider, "runtime_profile", None) is not ApiRuntimeProfile.PRODUCTION
        ):
            raise ValueError("unsafe authentication provider is forbidden in production")
        if not callable(getattr(clock, "now_audit_time", None)) or not callable(getattr(clock, "readiness_check", None)):
            raise ValueError("trusted request clock is invalid")
        self._authentication = authentication_provider
        self._plan = authorization_plan
        self._issuers = trusted_issuers
        self._clock = clock
        self._runtime_profile = runtime_profile
        self._snapshot: AuthenticationContext | None = None
        self._cache: dict[AuthorizationCheckpoint, TrustedAuthorizationContext] = {}
        self._lock = threading.Lock()

    @property
    def runtime_profile(self) -> ApiRuntimeProfile:
        return self._runtime_profile

    def resolve_context(
        self,
        *,
        checkpoint: AuthorizationCheckpoint,
        application_scope: ApplicationScopeDTO,
        audit_context: ApplicationAuditContextDTO,
    ) -> TrustedAuthorizationContext:
        if not isinstance(checkpoint, AuthorizationCheckpoint):
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID
            )
        if not isinstance(application_scope, ApplicationScopeDTO) or not isinstance(audit_context, ApplicationAuditContextDTO):
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID
            )
        with self._lock:
            cached = self._cache.get(checkpoint)
            if cached is not None:
                return cached
            resolved = self._materialize(checkpoint, application_scope)
            self._cache[checkpoint] = resolved
            return resolved

    def _materialize(
        self,
        checkpoint: AuthorizationCheckpoint,
        application_scope: ApplicationScopeDTO,
    ) -> TrustedAuthorizationContext:
        try:
            context = self._authentication.current_context()
        except AuthenticationProviderUnavailable:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_PROVIDER_UNAVAILABLE
            ) from None
        except (TimeoutError, ConnectionError):
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_PROVIDER_UNAVAILABLE
            ) from None
        except AuthenticationContextError:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID
            ) from None
        except Exception:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION
            ) from None
        if context is None:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_MISSING
            )
        if not isinstance(context, AuthenticationContext):
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID
            )
        if self._snapshot is None:
            self._snapshot = context
        elif context != self._snapshot:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION
            )
        try:
            now = _utc(self._clock.now_audit_time())
            profile = self._authentication.trusted_identity_profile()
            if not isinstance(profile, TrustedRequestIdentityProfile):
                raise ValueError("trusted identity profile is invalid")
            self._validate_context(context, profile, application_scope, now)
            target = self._plan.target_for(checkpoint)
            self._validate_target(target, context, application_scope)
            reference = ResourceSecurityReference(
                scope_type=target.scope_type,
                resource_id=target.resource_id,
                request_tenant_key=target.tenant_key,
                company_id=target.company_id,
                period_id=target.period_id,
                expected_resource_version=target.expected_resource_version,
                correlation_id=context.correlation_id,
                referenced_at=now,
            )
            strength = self._map_strength(context, profile)
            return TrustedAuthorizationContext(
                issuer=context.trusted_issuer,
                subject=context.subject_id,
                tenant_key=context.tenant_id,
                token_issued_at=_utc(context.issued_at),
                expires_at=_utc(context.expires_at) if context.expires_at is not None else None,
                expected_principal_kind=profile.principal_kind,
                service_client_id=profile.service_client_id,
                authentication_strength=strength,
                correlation_id=context.correlation_id,
                request_id=profile.request_id,
                authorization_context_reference=context.authorization_context_reference,
                checkpoint=checkpoint,
                resource_reference=reference,
                resolved_at=now,
            )
        except TrustedAuthorizationContextError:
            raise
        except (TypeError, ValueError):
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID
            ) from None
        except Exception:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION
            ) from None

    def _validate_context(self, context, profile, scope, now) -> None:
        required = (
            context.subject_id,
            context.authentication_method,
            context.correlation_id,
            context.claims_version,
            context.trusted_issuer,
            context.authorization_context_reference,
        )
        if any(not isinstance(value, str) or not value or value != value.strip() for value in required):
            raise ValueError("authentication context is incomplete")
        if context.trusted_issuer not in self._issuers or context.claims_version != CLAIMS_VERSION:
            raise ValueError("authentication context trust is invalid")
        if not SAFE_CORRELATION_PATTERN.fullmatch(context.correlation_id):
            raise ValueError("authentication correlation is invalid")
        if context.tenant_id is None or not TENANT_KEY_PATTERN.fullmatch(context.tenant_id):
            raise ValueError("authentication tenant is invalid")
        if scope.tenant_id is None or context.tenant_id != scope.tenant_id:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_TENANT_MISMATCH
            )
        issued = _utc(context.issued_at)
        if issued > now + _FUTURE_SKEW:
            raise ValueError("authentication issue time is invalid")
        if context.expires_at is not None and _utc(context.expires_at) <= now:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_EXPIRED
            )
        if now - issued > _MAX_CONTEXT_AGE:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_STALE
            )
        match = _AUTHORIZATION_REFERENCE.fullmatch(context.authorization_context_reference)
        expected_kind = "H" if profile.principal_kind is IdentityKind.HUMAN else "S"
        if match is None or match.group(1) != expected_kind:
            raise ValueError("authorization context reference is invalid")

    @staticmethod
    def _map_strength(context, profile) -> PolicyAuthenticationStrength:
        if profile.principal_kind is IdentityKind.SERVICE:
            if (
                context.authentication_method != "oauth2_client_credentials_jwt"
                or context.authentication_strength is not AuthenticationStrength.STRONG
                or profile.service_client_id is None
            ):
                raise ValueError("service authentication mapping is invalid")
            return PolicyAuthenticationStrength.SERVICE_CREDENTIAL
        if context.authentication_method != "oidc_bearer_jwt" or profile.service_client_id is not None:
            raise ValueError("human authentication mapping is invalid")
        mapping = {
            AuthenticationStrength.BASIC: PolicyAuthenticationStrength.PASSWORD,
            AuthenticationStrength.STRONG: PolicyAuthenticationStrength.MFA,
            AuthenticationStrength.PHISHING_RESISTANT: PolicyAuthenticationStrength.PHISHING_RESISTANT,
        }
        try:
            return mapping[context.authentication_strength]
        except (KeyError, TypeError):
            raise ValueError("human authentication strength is invalid") from None

    @staticmethod
    def _validate_target(target, context, scope) -> None:
        if target.tenant_key != context.tenant_id:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_TENANT_MISMATCH
            )
        if target.scope_type is PolicyScopeType.COMPANY_PERIOD and (
            target.company_id != scope.company_id
            or target.period_id != scope.financial_period_id
        ):
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID
            )

    def readiness_check(self, deadline: datetime) -> bool:
        try:
            _utc(deadline)
            if self.runtime_profile is ApiRuntimeProfile.PRODUCTION and (
                getattr(self._authentication, "is_fake", False)
                or not getattr(self._authentication, "is_request_bound", False)
            ):
                return False
            return bool(
                self._authentication.readiness_check(deadline)
                and self._clock.readiness_check(deadline)
            )
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"RequestBoundTrustedAuthorizationContextProvider(profile={self.runtime_profile.value!r}, identity='<redacted>')"


assert len(_CHECKPOINT_SCOPE) == len(AuthorizationCheckpoint) == 10
