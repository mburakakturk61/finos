"""Authentication-context validation without credential parsing."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from app.integrations.analysis_http.contracts import (
    ApiRuntimeProfile,
    AuthenticationContext,
    AuthenticationContextError,
    AuthenticationProviderUnavailable,
)


MAX_CONTEXT_AGE = timedelta(minutes=15)
MAX_FUTURE_SKEW = timedelta(seconds=60)


def validate_authentication_context(
    context: AuthenticationContext,
    *,
    correlation_id: str,
    trusted_issuers: frozenset[str],
    now: datetime,
) -> AuthenticationContext:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Trusted authentication clock must be timezone-aware.")
    required = (
        context.subject_id, context.authentication_method, context.correlation_id,
        context.claims_version, context.trusted_issuer,
        context.authorization_context_reference,
    )
    if any(not value or not value.strip() for value in required):
        raise AuthenticationContextError("Authentication context is incomplete.")
    if context.issued_at.tzinfo is None or context.issued_at.utcoffset() is None:
        raise AuthenticationContextError("Authentication context time is invalid.")
    if context.expires_at is not None and (
        context.expires_at.tzinfo is None
        or context.expires_at.utcoffset() is None
        or context.expires_at <= context.issued_at
        or context.expires_at <= now
    ):
        raise AuthenticationContextError("Authentication context is expired.")
    if context.issued_at > now + MAX_FUTURE_SKEW or now - context.issued_at > MAX_CONTEXT_AGE:
        raise AuthenticationContextError("Authentication context freshness is invalid.")
    if context.trusted_issuer not in trusted_issuers:
        raise AuthenticationContextError("Authentication issuer is not trusted.")
    if not hmac.compare_digest(context.correlation_id, correlation_id):
        raise AuthenticationContextError("Authentication correlation is invalid.")
    return context


class UnavailableAuthenticationContextProvider:
    runtime_profile = ApiRuntimeProfile.PRODUCTION
    is_fake = False

    def current_context(self) -> AuthenticationContext:
        raise AuthenticationProviderUnavailable("Trusted authentication provider is unavailable.")

    def readiness_check(self, deadline: datetime) -> bool:
        return False


class StaticAuthenticationContextProvider:
    """Explicit TEST/DEVELOPMENT adapter; production validation rejects it."""

    is_fake = True

    def __init__(self, context: AuthenticationContext, profile: ApiRuntimeProfile) -> None:
        if profile is ApiRuntimeProfile.PRODUCTION:
            raise ValueError("A static authentication adapter is forbidden in production.")
        self.context = context
        self.runtime_profile = profile

    def current_context(self) -> AuthenticationContext:
        return self.context

    def readiness_check(self, deadline: datetime) -> bool:
        return True


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
