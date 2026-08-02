"""Milestone 5.0E Step 11 authorization adapter and revalidation boundary."""

from __future__ import annotations

import enum
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.analysis_application.contracts import (
    ApplicationAuditContextDTO,
    ApplicationEventType,
    ApplicationScopeDTO,
)
from app.analysis_application.ports import (
    ApplicationClockPort,
    AuthorizationDecision,
    ObservabilityEventDTO,
    ObservabilityPort,
    SecurityAuditEventDTO,
    SecurityAuditPort,
    SecurityAuditReceiptDTO,
)
from app.security.authorization_policy import (
    COMPILED_SECURITY_ACTIONS,
    PERMISSION_REGISTRY_VERSION,
    AuthorizationPolicyEnginePort,
    AuthorizationPolicyRepositoryPort,
    AuditIntent,
    EffectivePermissionSet,
    PolicyAuthenticationStrength,
    PolicyEvaluationConstructionError,
    PolicyEvaluationRequest,
    PolicyEvaluationResult,
    PolicyMaterializationRequest,
    PolicyOutcome,
    PolicyReasonCode,
    PolicyRepositoryError,
    PolicyRepositoryErrorCode,
    PolicyScopeType,
    ResourceSecurityReference,
    SubjectReferenceHashCodec,
)
from app.security.contracts import (
    SAFE_CORRELATION_PATTERN,
    SERVICE_CLIENT_PATTERN,
    SUBJECT_PATTERN,
    TENANT_KEY_PATTERN,
    IdentityKind,
    IdentityResolutionError,
    IdentityResolutionErrorCode,
    SecurityIdentityRepositoryPort,
    VerifiedLocalIdentity,
)


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SRH1 = re.compile(r"^srh1:k[1-9][0-9]*:[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REFERENCE = re.compile(r"^(?:rsv1|srh1:k[1-9][0-9]*|ar1|cr1):[0-9a-f]{64}$")
_MAX_CONTEXT_AGE = timedelta(minutes=15)
_FUTURE_SKEW = timedelta(seconds=60)
_AUTHZ_REFERENCE = re.compile(
    r"^authz:v1:(H|S):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([1-9][0-9]*):([1-9][0-9]*)$"
)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


class AuthorizationCheckpoint(str, enum.Enum):
    START = "START"
    RESUME = "RESUME"
    RESUME_SOURCE = "RESUME_SOURCE"
    READ = "READ"
    CANCEL = "CANCEL"
    RETRY = "RETRY"
    PRE_PERSIST_START = "PRE_PERSIST_START"
    PRE_PERSIST_RESUME = "PRE_PERSIST_RESUME"
    PRE_PERSIST_RETRY = "PRE_PERSIST_RETRY"
    PRE_PERSIST_RESUME_SOURCE = "PRE_PERSIST_RESUME_SOURCE"


class TrustedAuthorizationContextErrorCode(str, enum.Enum):
    AUTH_CONTEXT_MISSING = "AUTH_CONTEXT_MISSING"
    AUTH_CONTEXT_INVALID = "AUTH_CONTEXT_INVALID"
    AUTH_CONTEXT_STALE = "AUTH_CONTEXT_STALE"
    AUTH_CONTEXT_EXPIRED = "AUTH_CONTEXT_EXPIRED"
    AUTH_CONTEXT_SUBJECT_MISMATCH = "AUTH_CONTEXT_SUBJECT_MISMATCH"
    AUTH_CONTEXT_TENANT_MISMATCH = "AUTH_CONTEXT_TENANT_MISMATCH"
    AUTH_CONTEXT_PROVIDER_UNAVAILABLE = "AUTH_CONTEXT_PROVIDER_UNAVAILABLE"
    AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION = "AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION"


class AuthorizationAuditDeliveryErrorCode(str, enum.Enum):
    AUDIT_STORE_UNAVAILABLE = "AUDIT_STORE_UNAVAILABLE"
    AUDIT_STORE_TIMEOUT = "AUDIT_STORE_TIMEOUT"
    AUDIT_EVENT_INVALID = "AUDIT_EVENT_INVALID"
    AUDIT_EVENT_UNSUPPORTED = "AUDIT_EVENT_UNSUPPORTED"
    AUDIT_DELIVERY_CONFLICT = "AUDIT_DELIVERY_CONFLICT"
    AUDIT_DATA_INTEGRITY_VIOLATION = "AUDIT_DATA_INTEGRITY_VIOLATION"


class AuthorizationAdapterDecisionCode(str, enum.Enum):
    AUTHZ_ALLOWED = "AUTHZ_ALLOWED"
    AUTHZ_UNKNOWN_ACTION = "AUTHZ_UNKNOWN_ACTION"
    AUTHZ_UNKNOWN_PERMISSION = "AUTHZ_UNKNOWN_PERMISSION"
    AUTHZ_UNKNOWN_ROLE = "AUTHZ_UNKNOWN_ROLE"
    AUTHZ_REGISTRY_VERSION_MISMATCH = "AUTHZ_REGISTRY_VERSION_MISMATCH"
    AUTHZ_TENANT_POLICY_VERSION_MISMATCH = "AUTHZ_TENANT_POLICY_VERSION_MISMATCH"
    AUTHZ_PRINCIPAL_KIND_NOT_ALLOWED = "AUTHZ_PRINCIPAL_KIND_NOT_ALLOWED"
    AUTHZ_PERMISSION_NOT_GRANTED = "AUTHZ_PERMISSION_NOT_GRANTED"
    AUTHZ_STRENGTH_INSUFFICIENT = "AUTHZ_STRENGTH_INSUFFICIENT"
    AUTHZ_TENANT_MISMATCH = "AUTHZ_TENANT_MISMATCH"
    AUTHZ_RESOURCE_OWNERSHIP_MISMATCH = "AUTHZ_RESOURCE_OWNERSHIP_MISMATCH"
    AUTHZ_SUBJECT_PREDICATE_FAILED = "AUTHZ_SUBJECT_PREDICATE_FAILED"
    AUTHZ_RESOURCE_NOT_FOUND = "AUTHZ_RESOURCE_NOT_FOUND"
    AUTHZ_RESOURCE_STATE_INVALID = "AUTHZ_RESOURCE_STATE_INVALID"
    AUTHZ_PROVIDER_UNAVAILABLE = "AUTHZ_PROVIDER_UNAVAILABLE"
    AUTHZ_PROVIDER_TIMEOUT = "AUTHZ_PROVIDER_TIMEOUT"
    AUTHZ_POLICY_INTEGRITY_FAILURE = "AUTHZ_POLICY_INTEGRITY_FAILURE"
    AUTHZ_CONTEXT_MISSING = "AUTHZ_CONTEXT_MISSING"
    AUTHZ_CONTEXT_INVALID = "AUTHZ_CONTEXT_INVALID"
    AUTHZ_CONTEXT_STALE = "AUTHZ_CONTEXT_STALE"
    AUTHZ_CONTEXT_EXPIRED = "AUTHZ_CONTEXT_EXPIRED"
    AUTHZ_CONTEXT_SUBJECT_MISMATCH = "AUTHZ_CONTEXT_SUBJECT_MISMATCH"
    AUTHZ_CONTEXT_TENANT_MISMATCH = "AUTHZ_CONTEXT_TENANT_MISMATCH"
    AUTHZ_CONTEXT_INTEGRITY_FAILURE = "AUTHZ_CONTEXT_INTEGRITY_FAILURE"
    AUDIT_REQUIRED_BUT_UNAVAILABLE = "AUDIT_REQUIRED_BUT_UNAVAILABLE"
    AUTHZ_AUDIT_INTEGRITY_FAILURE = "AUTHZ_AUDIT_INTEGRITY_FAILURE"
    AUTHZ_IDENTITY_REVOKED_PRINCIPAL = "AUTHZ_IDENTITY_REVOKED_PRINCIPAL"
    AUTHZ_IDENTITY_REVOKED_MEMBERSHIP = "AUTHZ_IDENTITY_REVOKED_MEMBERSHIP"
    AUTHZ_IDENTITY_REVOKED_TOKEN = "AUTHZ_IDENTITY_REVOKED_TOKEN"
    AUTHZ_TENANT_INACTIVE = "AUTHZ_TENANT_INACTIVE"
    AUTHZ_IDENTITY_NOT_FOUND = "AUTHZ_IDENTITY_NOT_FOUND"
    AUTHZ_IDENTITY_TENANT_NOT_FOUND = "AUTHZ_IDENTITY_TENANT_NOT_FOUND"
    AUTHZ_IDENTITY_TENANT_MISMATCH = "AUTHZ_IDENTITY_TENANT_MISMATCH"
    AUTHZ_IDENTITY_PRINCIPAL_KIND_MISMATCH = "AUTHZ_IDENTITY_PRINCIPAL_KIND_MISMATCH"
    AUTHZ_IDENTITY_MEMBERSHIP_NOT_FOUND = "AUTHZ_IDENTITY_MEMBERSHIP_NOT_FOUND"
    AUTHZ_IDENTITY_MEMBERSHIP_NOT_YET_VALID = "AUTHZ_IDENTITY_MEMBERSHIP_NOT_YET_VALID"
    AUTHZ_IDENTITY_SERVICE_SAFE_ROLE_NOT_FOUND = "AUTHZ_IDENTITY_SERVICE_SAFE_ROLE_NOT_FOUND"
    AUTHZ_IDENTITY_SERVICE_ROLE_PERMISSION_INVALID = "AUTHZ_IDENTITY_SERVICE_ROLE_PERMISSION_INVALID"
    AUTHZ_IDENTITY_NONCANONICAL_INPUT = "AUTHZ_IDENTITY_NONCANONICAL_INPUT"
    AUTHZ_IDENTITY_INTEGRITY_FAILURE = "AUTHZ_IDENTITY_INTEGRITY_FAILURE"
    AUTHZ_REVALIDATION_REVOKED_PRINCIPAL = "AUTHZ_REVALIDATION_REVOKED_PRINCIPAL"
    AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP = "AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP"
    AUTHZ_REVALIDATION_REVOKED_TOKEN = "AUTHZ_REVALIDATION_REVOKED_TOKEN"
    AUTHZ_REVALIDATION_REVOKED_TENANT = "AUTHZ_REVALIDATION_REVOKED_TENANT"
    AUTHZ_REVALIDATION_REVOKED_POLICY = "AUTHZ_REVALIDATION_REVOKED_POLICY"
    AUTHZ_REVALIDATION_REVOKED_RESOURCE = "AUTHZ_REVALIDATION_REVOKED_RESOURCE"
    AUTHZ_ADAPTER_INTEGRITY_FAILURE = "AUTHZ_ADAPTER_INTEGRITY_FAILURE"


class AuditDeliveryState(str, enum.Enum):
    PENDING = "PENDING"
    NOT_REQUIRED = "NOT_REQUIRED"
    DELIVERED = "DELIVERED"
    FAILED_REQUIRED = "FAILED_REQUIRED"
    FAILED_NON_REQUIRED = "FAILED_NON_REQUIRED"


_CONTEXT_METADATA = {
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_MISSING:
        (False, "security.authorization.context_missing", "Authorization context is unavailable.", AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_MISSING),
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID:
        (False, "security.authorization.context_invalid", "Authorization context is invalid.", AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_INVALID),
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_STALE:
        (False, "security.authorization.context_stale", "Authorization context is stale.", AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_STALE),
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_EXPIRED:
        (False, "security.authorization.context_expired", "Authorization context is expired.", AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_EXPIRED),
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_SUBJECT_MISMATCH:
        (False, "security.authorization.context_subject_mismatch", "Authorization context is inconsistent.", AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_SUBJECT_MISMATCH),
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_TENANT_MISMATCH:
        (False, "security.authorization.context_tenant_mismatch", "Authorization context is inconsistent.", AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_TENANT_MISMATCH),
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_PROVIDER_UNAVAILABLE:
        (True, "security.authorization.context_provider_unavailable", "Authorization provider is unavailable.", AuthorizationAdapterDecisionCode.AUTHZ_PROVIDER_UNAVAILABLE),
    TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION:
        (False, "security.authorization.context_integrity", "Authorization context is invalid.", AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_INTEGRITY_FAILURE),
}


_AUDIT_METADATA = {
    AuthorizationAuditDeliveryErrorCode.AUDIT_STORE_UNAVAILABLE:
        (True, "security.authorization.audit_store_unavailable", "Authorization audit is unavailable."),
    AuthorizationAuditDeliveryErrorCode.AUDIT_STORE_TIMEOUT:
        (True, "security.authorization.audit_store_timeout", "Authorization audit timed out."),
    AuthorizationAuditDeliveryErrorCode.AUDIT_EVENT_INVALID:
        (False, "security.authorization.audit_event_invalid", "Authorization audit event is invalid."),
    AuthorizationAuditDeliveryErrorCode.AUDIT_EVENT_UNSUPPORTED:
        (False, "security.authorization.audit_event_unsupported", "Authorization audit event is unsupported."),
    AuthorizationAuditDeliveryErrorCode.AUDIT_DELIVERY_CONFLICT:
        (False, "security.authorization.audit_delivery_conflict", "Authorization audit delivery conflicted."),
    AuthorizationAuditDeliveryErrorCode.AUDIT_DATA_INTEGRITY_VIOLATION:
        (False, "security.authorization.audit_integrity", "Authorization audit integrity validation failed."),
}


class TrustedAuthorizationContextError(Exception):
    __slots__ = ("_code", "_correlation_reference", "_frozen")

    def __init__(self, code: TrustedAuthorizationContextErrorCode, *, correlation_reference: str | None = None) -> None:
        if not isinstance(code, TrustedAuthorizationContextErrorCode):
            raise TypeError("invalid context error code")
        if correlation_reference is not None and not re.fullmatch(r"cr1:[0-9a-f]{64}", correlation_reference):
            raise ValueError("invalid correlation reference")
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_correlation_reference", correlation_reference)
        Exception.__init__(self, _CONTEXT_METADATA[code][2])
        object.__setattr__(self, "_frozen", True)

    @property
    def code(self) -> TrustedAuthorizationContextErrorCode: return self._code
    @property
    def correlation_reference(self) -> str | None: return self._correlation_reference
    @property
    def retryable(self) -> bool: return _CONTEXT_METADATA[self.code][0]
    @property
    def metric_name(self) -> str: return _CONTEXT_METADATA[self.code][1]
    @property
    def safe_message(self) -> str: return _CONTEXT_METADATA[self.code][2]
    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False): raise AttributeError("immutable")
        object.__setattr__(self, name, value)
    def __delattr__(self, name): raise AttributeError("immutable")
    def __init_subclass__(cls, **kwargs): raise TypeError("TrustedAuthorizationContextError is final")
    def __str__(self): return self.safe_message
    def __repr__(self): return f"TrustedAuthorizationContextError(code={self.code.value!r})"


class AuthorizationAuditDeliveryError(Exception):
    __slots__ = ("_code", "_frozen")

    def __init__(self, code: AuthorizationAuditDeliveryErrorCode) -> None:
        if not isinstance(code, AuthorizationAuditDeliveryErrorCode):
            raise TypeError("invalid audit error code")
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_code", code)
        Exception.__init__(self, _AUDIT_METADATA[code][2])
        object.__setattr__(self, "_frozen", True)

    @property
    def code(self) -> AuthorizationAuditDeliveryErrorCode: return self._code
    @property
    def retryable(self) -> bool: return _AUDIT_METADATA[self.code][0]
    @property
    def metric_name(self) -> str: return _AUDIT_METADATA[self.code][1]
    @property
    def safe_message(self) -> str: return _AUDIT_METADATA[self.code][2]
    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False): raise AttributeError("immutable")
        object.__setattr__(self, name, value)
    def __delattr__(self, name): raise AttributeError("immutable")
    def __init_subclass__(cls, **kwargs): raise TypeError("AuthorizationAuditDeliveryError is final")
    def __str__(self): return self.safe_message
    def __repr__(self): return f"AuthorizationAuditDeliveryError(code={self.code.value!r})"


@dataclass(frozen=True, repr=False)
class TrustedAuthorizationContext:
    issuer: str
    subject: str
    tenant_key: str
    token_issued_at: datetime
    expires_at: datetime | None
    expected_principal_kind: IdentityKind
    service_client_id: str | None
    authentication_strength: PolicyAuthenticationStrength
    correlation_id: str
    request_id: str | None
    authorization_context_reference: str
    checkpoint: AuthorizationCheckpoint
    resource_reference: ResourceSecurityReference
    resolved_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.issuer, str) or not self.issuer.startswith("https://") or self.issuer != self.issuer.strip():
            raise ValueError("context issuer is invalid")
        if not SUBJECT_PATTERN.fullmatch(self.subject) or not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("context identity is invalid")
        if not isinstance(self.expected_principal_kind, IdentityKind) or not isinstance(self.authentication_strength, PolicyAuthenticationStrength):
            raise ValueError("context profile is invalid")
        if self.expected_principal_kind is IdentityKind.HUMAN:
            if self.service_client_id is not None or self.authentication_strength is PolicyAuthenticationStrength.SERVICE_CREDENTIAL:
                raise ValueError("human context is invalid")
        elif not isinstance(self.service_client_id, str) or not SERVICE_CLIENT_PATTERN.fullmatch(self.service_client_id) or self.authentication_strength is not PolicyAuthenticationStrength.SERVICE_CREDENTIAL:
            raise ValueError("service context is invalid")
        if not SAFE_CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("context correlation is invalid")
        if self.request_id is not None and not SAFE_CORRELATION_PATTERN.fullmatch(self.request_id):
            raise ValueError("context request is invalid")
        if not isinstance(self.authorization_context_reference, str) or not self.authorization_context_reference.startswith("authz:v1:"):
            raise ValueError("context reference is invalid")
        if not isinstance(self.checkpoint, AuthorizationCheckpoint) or not isinstance(self.resource_reference, ResourceSecurityReference):
            raise ValueError("context checkpoint is invalid")
        token_time = _utc(self.token_issued_at)
        resolved = _utc(self.resolved_at)
        if self.expires_at is not None:
            _utc(self.expires_at)
        if _utc(self.resource_reference.referenced_at) > resolved or self.resource_reference.correlation_id != self.correlation_id:
            raise ValueError("context resource reference is invalid")
        if token_time > resolved + _FUTURE_SKEW:
            raise ValueError("context token time is invalid")

    def __repr__(self) -> str:
        return f"TrustedAuthorizationContext(checkpoint={self.checkpoint.value!r}, subject='<redacted>', tenant='<redacted>')"


class TrustedAuthorizationContextProviderPort(Protocol):
    def resolve_context(
        self, *, checkpoint: AuthorizationCheckpoint,
        application_scope: ApplicationScopeDTO,
        audit_context: ApplicationAuditContextDTO,
    ) -> TrustedAuthorizationContext: ...


class AuthorizationRevalidationPort(Protocol):
    def revalidate_start(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def revalidate_resume(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def revalidate_retry(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def revalidate_resume_source(self, source_run_id: str, target_scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...


class _RevalidationProofChanged(Exception):
    def __init__(self, code: AuthorizationAdapterDecisionCode) -> None:
        self.code = code


class AuthorizationDecisionReferenceCodec:
    """Canonical adr1 SHA-256 codec frozen by the Step 11 design."""

    PREFIX = b"adr1\n"
    FIELDS = (
        ("policy_registry_version", "s"),
        ("tenant_policy_version", "i?"),
        ("action_code", "s"),
        ("decision_code", "e"),
        ("policy_reason", "e?"),
        ("resource_version", "s?"),
        ("principal_reference", "s?"),
        ("membership_version", "i?"),
        ("identity_resolved_at", "t?"),
        ("policy_evaluated_at", "t"),
        ("audit_delivery", "e"),
        ("audit_receipt_reference", "s?"),
        ("correlation_reference", "s"),
    )

    def canonical_bytes(self, **values: object) -> bytes:
        if set(values) != {name for name, _ in self.FIELDS}:
            raise ValueError("ADR fields mismatch")
        if values["policy_registry_version"] != PERMISSION_REGISTRY_VERSION:
            raise ValueError("ADR registry version is invalid")
        if values["action_code"] not in COMPILED_SECURITY_ACTIONS:
            raise ValueError("ADR action is invalid")
        if not isinstance(values["decision_code"], AuthorizationAdapterDecisionCode):
            raise ValueError("ADR decision code is invalid")
        if values["policy_reason"] is not None and not isinstance(values["policy_reason"], PolicyReasonCode):
            raise ValueError("ADR policy reason is invalid")
        checks = (
            ("resource_version", r"^rsv1:[0-9a-f]{64}$"),
            ("principal_reference", r"^srh1:k[1-9][0-9]*:[0-9a-f]{64}$"),
            ("audit_receipt_reference", r"^ar1:[0-9a-f]{64}$"),
            ("correlation_reference", r"^cr1:[0-9a-f]{64}$"),
        )
        for name, pattern in checks:
            value = values[name]
            if value is not None and (not isinstance(value, str) or re.fullmatch(pattern, value) is None):
                raise ValueError(f"ADR {name} is invalid")
        if not isinstance(values["audit_delivery"], AuditDeliveryState):
            raise ValueError("ADR audit state is invalid")
        output = bytearray(self.PREFIX)
        for name, declared_tag in self.FIELDS:
            value = values[name]
            tag = "n" if value is None and declared_tag.endswith("?") else declared_tag.rstrip("?")
            payload = self._payload(tag, value)
            output.extend(f"{name}|{tag}|{len(payload)}|".encode())
            output.extend(payload)
            output.extend(b"\n")
        return bytes(output)

    def encode(self, **values: object) -> str:
        return "adr1:" + hashlib.sha256(self.canonical_bytes(**values)).hexdigest()

    @staticmethod
    def _payload(tag: str, value: object) -> bytes:
        if tag == "n":
            if value is not None: raise ValueError("null expected")
            return b"null"
        if tag == "s":
            if not isinstance(value, str) or not value: raise ValueError("string expected")
            return value.encode()
        if tag == "i":
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0: raise ValueError("positive integer expected")
            return str(value).encode()
        if tag == "e":
            if not isinstance(value, enum.Enum): raise ValueError("enum expected")
            return str(value.value).encode()
        if tag == "t":
            return _utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ").encode()  # type: ignore[arg-type]
        raise ValueError("unknown ADR tag")


_POLICY_DECISIONS = {
    PolicyReasonCode.ALLOWED: AuthorizationAdapterDecisionCode.AUTHZ_ALLOWED,
    PolicyReasonCode.UNKNOWN_ACTION: AuthorizationAdapterDecisionCode.AUTHZ_UNKNOWN_ACTION,
    PolicyReasonCode.UNKNOWN_PERMISSION: AuthorizationAdapterDecisionCode.AUTHZ_UNKNOWN_PERMISSION,
    PolicyReasonCode.UNKNOWN_ROLE: AuthorizationAdapterDecisionCode.AUTHZ_UNKNOWN_ROLE,
    PolicyReasonCode.REGISTRY_VERSION_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_REGISTRY_VERSION_MISMATCH,
    PolicyReasonCode.TENANT_POLICY_VERSION_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_TENANT_POLICY_VERSION_MISMATCH,
    PolicyReasonCode.PRINCIPAL_KIND_NOT_ALLOWED: AuthorizationAdapterDecisionCode.AUTHZ_PRINCIPAL_KIND_NOT_ALLOWED,
    PolicyReasonCode.PERMISSION_NOT_GRANTED: AuthorizationAdapterDecisionCode.AUTHZ_PERMISSION_NOT_GRANTED,
    PolicyReasonCode.INSUFFICIENT_AUTHENTICATION_STRENGTH: AuthorizationAdapterDecisionCode.AUTHZ_STRENGTH_INSUFFICIENT,
    PolicyReasonCode.TENANT_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_TENANT_MISMATCH,
    PolicyReasonCode.RESOURCE_OWNERSHIP_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_RESOURCE_OWNERSHIP_MISMATCH,
    PolicyReasonCode.SUBJECT_PREDICATE_FAILED: AuthorizationAdapterDecisionCode.AUTHZ_SUBJECT_PREDICATE_FAILED,
    PolicyReasonCode.RESOURCE_NOT_FOUND: AuthorizationAdapterDecisionCode.AUTHZ_RESOURCE_NOT_FOUND,
    PolicyReasonCode.RESOURCE_STATE_INVALID: AuthorizationAdapterDecisionCode.AUTHZ_RESOURCE_STATE_INVALID,
    PolicyReasonCode.POLICY_STORE_UNAVAILABLE: AuthorizationAdapterDecisionCode.AUTHZ_PROVIDER_UNAVAILABLE,
    PolicyReasonCode.POLICY_STORE_TIMEOUT: AuthorizationAdapterDecisionCode.AUTHZ_PROVIDER_TIMEOUT,
    PolicyReasonCode.DATA_INTEGRITY_VIOLATION: AuthorizationAdapterDecisionCode.AUTHZ_POLICY_INTEGRITY_FAILURE,
}


_IDENTITY_DECISIONS = {
    IdentityResolutionErrorCode.IDENTITY_NOT_FOUND: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_NOT_FOUND,
    IdentityResolutionErrorCode.TENANT_NOT_FOUND: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_TENANT_NOT_FOUND,
    IdentityResolutionErrorCode.TENANT_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_TENANT_MISMATCH,
    IdentityResolutionErrorCode.PRINCIPAL_KIND_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_PRINCIPAL_KIND_MISMATCH,
    IdentityResolutionErrorCode.TENANT_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_TENANT_INACTIVE,
    IdentityResolutionErrorCode.PRINCIPAL_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_REVOKED_PRINCIPAL,
    IdentityResolutionErrorCode.SUBJECT_BINDING_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_REVOKED_PRINCIPAL,
    IdentityResolutionErrorCode.MEMBERSHIP_NOT_FOUND: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_MEMBERSHIP_NOT_FOUND,
    IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_REVOKED_MEMBERSHIP,
    IdentityResolutionErrorCode.MEMBERSHIP_NOT_YET_VALID: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_MEMBERSHIP_NOT_YET_VALID,
    IdentityResolutionErrorCode.MEMBERSHIP_EXPIRED: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_REVOKED_MEMBERSHIP,
    IdentityResolutionErrorCode.SERVICE_SAFE_ROLE_NOT_FOUND: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_SERVICE_SAFE_ROLE_NOT_FOUND,
    IdentityResolutionErrorCode.SERVICE_ROLE_PERMISSION_INVALID: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_SERVICE_ROLE_PERMISSION_INVALID,
    IdentityResolutionErrorCode.TOKEN_REVOKED_BY_PRINCIPAL: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_REVOKED_TOKEN,
    IdentityResolutionErrorCode.TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_REVOKED_TOKEN,
    IdentityResolutionErrorCode.NONCANONICAL_IDENTITY_INPUT: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_NONCANONICAL_INPUT,
    IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION: AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_INTEGRITY_FAILURE,
    IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE: AuthorizationAdapterDecisionCode.AUTHZ_PROVIDER_UNAVAILABLE,
    IdentityResolutionErrorCode.IDENTITY_STORE_TIMEOUT: AuthorizationAdapterDecisionCode.AUTHZ_PROVIDER_TIMEOUT,
}


_REVALIDATION_IDENTITY = {
    IdentityResolutionErrorCode.TENANT_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_TENANT,
    IdentityResolutionErrorCode.PRINCIPAL_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_PRINCIPAL,
    IdentityResolutionErrorCode.SUBJECT_BINDING_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_PRINCIPAL,
    IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE: AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP,
    IdentityResolutionErrorCode.MEMBERSHIP_EXPIRED: AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP,
    IdentityResolutionErrorCode.TOKEN_REVOKED_BY_PRINCIPAL: AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_TOKEN,
    IdentityResolutionErrorCode.TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY: AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_TOKEN,
}


_POLICY_REVOKE_REASONS = frozenset({
    PolicyReasonCode.UNKNOWN_ROLE,
    PolicyReasonCode.UNKNOWN_PERMISSION,
    PolicyReasonCode.REGISTRY_VERSION_MISMATCH,
    PolicyReasonCode.TENANT_POLICY_VERSION_MISMATCH,
    PolicyReasonCode.PRINCIPAL_KIND_NOT_ALLOWED,
    PolicyReasonCode.PERMISSION_NOT_GRANTED,
})
_RESOURCE_REVOKE_REASONS = frozenset({
    PolicyReasonCode.TENANT_MISMATCH,
    PolicyReasonCode.RESOURCE_OWNERSHIP_MISMATCH,
    PolicyReasonCode.RESOURCE_STATE_INVALID,
})


@dataclass(frozen=True)
class _Attempt:
    decision: AuthorizationDecision
    principal_kind: IdentityKind | None


class LocalAuthorizationPolicyClient:
    """Framework-free adapter from Step 9/10 state to frozen 5.0C decisions."""

    requires_same_revalidation_instance = True
    is_fake = False
    is_allow_all = False
    is_noop = False

    def __init__(
        self, *, context_provider: TrustedAuthorizationContextProviderPort,
        identity_repository: SecurityIdentityRepositoryPort,
        policy_repository: AuthorizationPolicyRepositoryPort,
        policy_engine: AuthorizationPolicyEnginePort,
        security_audit: SecurityAuditPort,
        observability: ObservabilityPort,
        clock: ApplicationClockPort,
        subject_reference_hash_codec: SubjectReferenceHashCodec,
        decision_reference_codec: AuthorizationDecisionReferenceCodec | None = None,
        production_mode: bool = False,
    ) -> None:
        dependencies = (
            context_provider, identity_repository, policy_repository, policy_engine,
            security_audit, observability, clock, subject_reference_hash_codec,
        )
        if any(value is None for value in dependencies):
            raise ValueError("authorization adapter dependency is missing")
        if production_mode and getattr(context_provider, "is_fake", False):
            raise ValueError("fake authorization context provider is forbidden in production")
        self._contexts = context_provider
        self._identities = identity_repository
        self._policies = policy_repository
        self._engine = policy_engine
        self._audit = security_audit
        self._observability = observability
        self._clock = clock
        self._subjects = subject_reference_hash_codec
        self._references = decision_reference_codec or AuthorizationDecisionReferenceCodec()

    def authorize_start(self, scope, actor):
        return self._authorize(AuthorizationCheckpoint.START, "analysis.start", scope, actor).decision

    def authorize_resume(self, scope, actor):
        return self._authorize(AuthorizationCheckpoint.RESUME, "analysis.resume", scope, actor).decision

    def authorize_resume_source(self, source_run_id, target_scope, actor):
        return self._authorize(
            AuthorizationCheckpoint.RESUME_SOURCE, "analysis.resume_source",
            target_scope, actor, source_run_id=source_run_id,
        ).decision

    def authorize_read(self, scope, actor, *, include_payload):
        first = self._authorize(AuthorizationCheckpoint.READ, "analysis.read", scope, actor)
        if not first.decision.granted or not include_payload:
            return first.decision
        return self._authorize(AuthorizationCheckpoint.READ, "analysis.payload.read", scope, actor).decision

    def authorize_cancel(self, scope, actor):
        first = self._authorize(AuthorizationCheckpoint.CANCEL, "analysis.cancel.own", scope, actor)
        if first.decision.granted:
            return first.decision
        fallback_codes = {
            AuthorizationAdapterDecisionCode.AUTHZ_RESOURCE_OWNERSHIP_MISMATCH.value,
            AuthorizationAdapterDecisionCode.AUTHZ_PERMISSION_NOT_GRANTED.value,
        }
        if first.principal_kind is IdentityKind.HUMAN and first.decision.decision_code in fallback_codes:
            return self._authorize(AuthorizationCheckpoint.CANCEL, "analysis.cancel.any", scope, actor).decision
        return first.decision

    def authorize_retry(self, scope, actor):
        return self._authorize(AuthorizationCheckpoint.RETRY, "analysis.retry", scope, actor).decision

    def authorize_registered_action(self, action_code, scope, actor):
        if action_code not in COMPILED_SECURITY_ACTIONS:
            return self._terminal_decision(
                code=AuthorizationAdapterDecisionCode.AUTHZ_UNKNOWN_ACTION,
                scope=scope, actor=actor, action_code="analysis.read",
            )
        return self._authorize(
            AuthorizationCheckpoint.READ, action_code, scope, actor,
        ).decision

    def revalidate_start(self, scope, actor):
        return self._authorize(AuthorizationCheckpoint.PRE_PERSIST_START, "analysis.start", scope, actor, revalidation=True).decision

    def revalidate_resume(self, scope, actor):
        return self._authorize(AuthorizationCheckpoint.PRE_PERSIST_RESUME, "analysis.resume", scope, actor, revalidation=True).decision

    def revalidate_retry(self, scope, actor):
        return self._authorize(AuthorizationCheckpoint.PRE_PERSIST_RETRY, "analysis.retry", scope, actor, revalidation=True).decision

    def revalidate_resume_source(self, source_run_id, target_scope, actor):
        return self._authorize(
            AuthorizationCheckpoint.PRE_PERSIST_RESUME_SOURCE,
            "analysis.resume_source", target_scope, actor,
            source_run_id=source_run_id, revalidation=True,
        ).decision

    def _authorize(
        self, checkpoint: AuthorizationCheckpoint, action_code: str,
        scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO,
        *, source_run_id: str | None = None, revalidation: bool = False,
    ) -> _Attempt:
        try:
            context = self._resolve_context(checkpoint, scope, actor, source_run_id)
        except TrustedAuthorizationContextError as error:
            self._metric(error.metric_name)
            return _Attempt(self._terminal_decision(
                code=_CONTEXT_METADATA[error.code][3], scope=scope, actor=actor,
                action_code=action_code, correlation_reference=error.correlation_reference,
            ), None)
        except Exception:
            self._metric("security.authorization.context_integrity")
            return _Attempt(self._terminal_decision(
                code=AuthorizationAdapterDecisionCode.AUTHZ_CONTEXT_INTEGRITY_FAILURE,
                scope=scope, actor=actor, action_code=action_code,
            ), None)

        try:
            identity = self._resolve_identity(context, revalidation=revalidation)
        except _RevalidationProofChanged as error:
            return _Attempt(self._terminal_decision(
                code=error.code, scope=scope, actor=actor, action_code=action_code,
                context=context, revoked=True,
            ), None)
        except IdentityResolutionError as error:
            code = _REVALIDATION_IDENTITY.get(error.code) if revalidation else None
            code = code or _IDENTITY_DECISIONS.get(error.code, AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_INTEGRITY_FAILURE)
            revoked = error.code in _REVALIDATION_IDENTITY or error.code in {
                IdentityResolutionErrorCode.PRINCIPAL_INACTIVE,
                IdentityResolutionErrorCode.SUBJECT_BINDING_INACTIVE,
                IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE,
                IdentityResolutionErrorCode.MEMBERSHIP_EXPIRED,
                IdentityResolutionErrorCode.TOKEN_REVOKED_BY_PRINCIPAL,
                IdentityResolutionErrorCode.TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY,
            }
            self._metric(error.metric_name)
            return _Attempt(self._terminal_decision(
                code=code, scope=scope, actor=actor, action_code=action_code,
                context=context, revoked=revoked,
            ), None)
        except Exception:
            return _Attempt(self._terminal_decision(
                code=AuthorizationAdapterDecisionCode.AUTHZ_IDENTITY_INTEGRITY_FAILURE,
                scope=scope, actor=actor, action_code=action_code, context=context,
            ), None)

        try:
            action = COMPILED_SECURITY_ACTIONS[action_code]
            materialization = PolicyMaterializationRequest(
                principal_id=identity.principal_id,
                membership_id=identity.membership_id,
                principal_kind=identity.principal_kind,
                tenant_id=identity.tenant_id,
                tenant_key=identity.tenant_key,
                roles=identity.roles,
                permission_registry_version=identity.permission_registry_version,
                tenant_policy_version=identity.tenant_policy_version,
                role_set_digest=identity.role_set_digest,
                permission_resolution_reference=identity.permission_resolution_reference,
                current_time=context.resolved_at,
                correlation_id=context.correlation_id,
            )
            permissions = self._policies.resolve_effective_permissions(materialization)
            request = PolicyEvaluationRequest(
                identity=identity,
                authentication_strength=context.authentication_strength,
                action=action,
                resource_reference=context.resource_reference,
                explicit_subject=None,
                target_subject=None,
                correlation_id=context.correlation_id,
                evaluated_at=context.resolved_at,
                expected_registry_version=PERMISSION_REGISTRY_VERSION,
                expected_tenant_policy_version=identity.tenant_policy_version,
            )
            result = self._engine.evaluate(request=request, effective_permissions=permissions)
            if not isinstance(result, PolicyEvaluationResult) or result.evaluated_action != action_code:
                raise ValueError("policy result binding is invalid")
            return _Attempt(
                self._policy_decision(result, context, identity, scope, actor, revalidation),
                identity.principal_kind,
            )
        except PolicyRepositoryError as error:
            code, revoked = self._repository_error(error.code, revalidation)
            self._metric(error.metric_name)
            return _Attempt(self._terminal_decision(
                code=code, scope=scope, actor=actor, action_code=action_code,
                context=context, identity=identity, revoked=revoked,
            ), identity.principal_kind)
        except PolicyEvaluationConstructionError:
            return _Attempt(self._terminal_decision(
                code=AuthorizationAdapterDecisionCode.AUTHZ_ADAPTER_INTEGRITY_FAILURE,
                scope=scope, actor=actor, action_code=action_code,
                context=context, identity=identity,
            ), identity.principal_kind)
        except Exception:
            return _Attempt(self._terminal_decision(
                code=AuthorizationAdapterDecisionCode.AUTHZ_ADAPTER_INTEGRITY_FAILURE,
                scope=scope, actor=actor, action_code=action_code,
                context=context, identity=identity,
            ), identity.principal_kind)

    def _resolve_context(self, checkpoint, scope, actor, source_run_id):
        try:
            context = self._contexts.resolve_context(
                checkpoint=checkpoint, application_scope=scope, audit_context=actor,
            )
        except TrustedAuthorizationContextError:
            raise
        except (TimeoutError, ConnectionError):
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_PROVIDER_UNAVAILABLE,
            ) from None
        except Exception:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION,
            ) from None
        if context is None:
            raise TrustedAuthorizationContextError(TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_MISSING)
        if not isinstance(context, TrustedAuthorizationContext) or context.checkpoint is not checkpoint:
            raise TrustedAuthorizationContextError(TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID)
        if scope.tenant_id is None or context.tenant_key != scope.tenant_id:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_TENANT_MISMATCH,
                correlation_reference=self._reference("cr1", context.correlation_id),
            )
        subject_ref = self._subjects.encode(
            issuer=context.issuer, tenant_key=context.tenant_key,
            principal_kind=context.expected_principal_kind,
            provider_subject=context.subject,
        )
        if actor.actor_id != subject_ref:
            raise TrustedAuthorizationContextError(
                TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_SUBJECT_MISMATCH,
                correlation_reference=self._reference("cr1", context.correlation_id),
            )
        if context.token_issued_at > context.resolved_at + _FUTURE_SKEW:
            raise TrustedAuthorizationContextError(TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID)
        if context.expires_at is not None and context.expires_at <= context.resolved_at:
            raise TrustedAuthorizationContextError(TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_EXPIRED)
        if context.resolved_at - context.token_issued_at > _MAX_CONTEXT_AGE:
            raise TrustedAuthorizationContextError(TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_STALE)
        if source_run_id is not None and (
            context.resource_reference.scope_type is not PolicyScopeType.ANALYSIS_RUN
            or context.resource_reference.resource_id != source_run_id
        ):
            raise TrustedAuthorizationContextError(TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID)
        return context

    def _resolve_identity(self, context: TrustedAuthorizationContext, *, revalidation: bool) -> VerifiedLocalIdentity:
        request_id = context.request_id or self._reference(
            "ari1", self._reference("cr1", context.correlation_id) + "\n" + context.checkpoint.value,
        )
        identity = self._identities.resolve_principal_and_membership(
            issuer=context.issuer,
            subject=context.subject,
            tenant_key=context.tenant_key,
            token_issued_at=context.token_issued_at,
            expected_principal_kind=context.expected_principal_kind,
            expected_service_client_id=context.service_client_id,
            correlation_id=context.correlation_id,
            request_id=request_id,
            now=context.resolved_at,
        )
        if not isinstance(identity, VerifiedLocalIdentity):
            raise ValueError("identity result is invalid")
        match = _AUTHZ_REFERENCE.fullmatch(context.authorization_context_reference)
        if match is None:
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION,
                correlation_id=context.correlation_id,
            )
        kind, membership_id, membership_version, tenant_version = match.groups()
        expected_kind = "H" if identity.principal_kind is IdentityKind.HUMAN else "S"
        if kind != expected_kind or membership_id != str(identity.membership_id):
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION,
                correlation_id=context.correlation_id,
            )
        if int(membership_version) != identity.membership_version:
            if revalidation:
                raise _RevalidationProofChanged(
                    AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_POLICY
                )
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION,
                correlation_id=context.correlation_id,
            )
        if int(tenant_version) != identity.tenant_policy_version:
            if revalidation:
                raise _RevalidationProofChanged(
                    AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_POLICY
                )
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION,
                correlation_id=context.correlation_id,
            )
        return identity

    def _policy_decision(self, result, context, identity, scope, actor, revalidation):
        code = _POLICY_DECISIONS[result.reason_code]
        revoked = False
        if revalidation and result.outcome is not PolicyOutcome.ALLOW:
            if result.reason_code in _POLICY_REVOKE_REASONS:
                code = AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_POLICY
                revoked = True
            elif result.reason_code in _RESOURCE_REVOKE_REASONS:
                code = AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_RESOURCE
                revoked = True
        audit_state, receipt_ref, audit_error = self._deliver_policy_audit(
            result.audit_intent, result, code, scope,
        )
        granted = result.outcome is PolicyOutcome.ALLOW
        if audit_error is not None and result.audit_intent.required:
            granted = False
            if result.outcome is PolicyOutcome.ALLOW:
                code = (
                    AuthorizationAdapterDecisionCode.AUDIT_REQUIRED_BUT_UNAVAILABLE
                    if audit_error in {
                        AuthorizationAuditDeliveryErrorCode.AUDIT_STORE_UNAVAILABLE,
                        AuthorizationAuditDeliveryErrorCode.AUDIT_STORE_TIMEOUT,
                    }
                    else AuthorizationAdapterDecisionCode.AUTHZ_AUDIT_INTEGRITY_FAILURE
                )
        return self._build_decision(
            granted=granted, revoked=revoked, code=code,
            action_code=result.evaluated_action,
            policy_reason=result.reason_code,
            resource_version=context.resource_reference.expected_resource_version,
            principal_reference=result.audit_intent.subject_reference_hash,
            identity=identity, evaluated_at=result.evaluated_at,
            audit_state=audit_state, receipt_reference=receipt_ref,
            correlation_id=result.correlation_id,
        )

    def _deliver_policy_audit(self, intent, result, code, scope):
        if not isinstance(intent, AuditIntent):
            return AuditDeliveryState.FAILED_REQUIRED, None, AuthorizationAuditDeliveryErrorCode.AUDIT_EVENT_INVALID
        if not intent.required:
            return AuditDeliveryState.NOT_REQUIRED, None, None
        resource_ref = self._reference(
            "rr1", f"{result.resource_type.value}\n{result.resource_id}\n{result.evaluated_action}",
        )
        correlation_ref = self._reference("cr1", result.correlation_id)
        provisional = self._references.encode(
            policy_registry_version=result.policy_registry_version,
            tenant_policy_version=result.tenant_policy_version,
            action_code=result.evaluated_action,
            decision_code=code,
            policy_reason=result.reason_code,
            resource_version=None,
            principal_reference=intent.subject_reference_hash,
            membership_version=None,
            identity_resolved_at=None,
            policy_evaluated_at=result.evaluated_at,
            audit_delivery=AuditDeliveryState.PENDING,
            audit_receipt_reference=None,
            correlation_reference=correlation_ref,
        )
        event_type = (
            ApplicationEventType.AUTHORIZATION_GRANTED
            if result.outcome is PolicyOutcome.ALLOW
            else ApplicationEventType.AUTHORIZATION_DENIED
        )
        attributes = tuple(sorted({
            "action_code": result.evaluated_action,
            "audit_delivery": AuditDeliveryState.PENDING.value,
            "event_name": intent.event_name,
            "outcome": result.outcome.value,
            "policy_reason_code": result.reason_code.value,
            "provider_decision_reference": provisional,
            "resource_reference": resource_ref,
            "resource_type": result.resource_type.value,
            "security_severity": intent.security_severity.value,
            "subject_reference_hash": intent.subject_reference_hash,
            "tenant_reference": self._reference("tr1", intent.tenant_key),
        }.items()))
        idempotency_key = self._reference(
            "aik1",
            "\n".join((
                correlation_ref, intent.subject_reference_hash,
                result.evaluated_action, result.reason_code.value,
                resource_ref, result.evaluated_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                intent.event_name,
            )),
        )
        event_digest = self._reference(
            "aed1", repr((event_type.value, attributes, idempotency_key)),
        )
        attributes = tuple(sorted(attributes + (
            ("audit_event_digest", event_digest),
            ("audit_idempotency_key", idempotency_key),
        )))
        event = SecurityAuditEventDTO(
            event_type=event_type,
            occurred_at=result.evaluated_at,
            correlation_id=result.correlation_id,
            scope=scope,
            actor_id=intent.subject_reference_hash,
            decision_code=code.value,
            safe_attributes=attributes,
        )
        return self._record_audit(event, required=True)

    def _record_audit(self, event: SecurityAuditEventDTO, *, required: bool):
        try:
            receipt = self._audit.record_required_event(event)
            if not isinstance(receipt, SecurityAuditReceiptDTO):
                raise AuthorizationAuditDeliveryError(
                    AuthorizationAuditDeliveryErrorCode.AUDIT_DATA_INTEGRITY_VIOLATION
                )
            if (
                receipt.event_type is not event.event_type
                or not isinstance(receipt.receipt_id, str) or not receipt.receipt_id
                or not _HEX64.fullmatch(receipt.audit_record_digest)
                or _utc(receipt.recorded_at) < _utc(event.occurred_at)
            ):
                raise AuthorizationAuditDeliveryError(
                    AuthorizationAuditDeliveryErrorCode.AUDIT_DATA_INTEGRITY_VIOLATION
                )
            receipt_ref = self._reference(
                "ar1", f"{receipt.receipt_id}\n{receipt.audit_record_digest}\n{receipt.event_type.value}",
            )
            return AuditDeliveryState.DELIVERED, receipt_ref, None
        except AuthorizationAuditDeliveryError as error:
            self._metric(error.metric_name)
            code = error.code
        except TimeoutError:
            code = AuthorizationAuditDeliveryErrorCode.AUDIT_STORE_TIMEOUT
            self._metric(_AUDIT_METADATA[code][1])
        except ConnectionError:
            code = AuthorizationAuditDeliveryErrorCode.AUDIT_STORE_UNAVAILABLE
            self._metric(_AUDIT_METADATA[code][1])
        except Exception:
            code = AuthorizationAuditDeliveryErrorCode.AUDIT_DATA_INTEGRITY_VIOLATION
            self._metric(_AUDIT_METADATA[code][1])
        return (
            AuditDeliveryState.FAILED_REQUIRED if required else AuditDeliveryState.FAILED_NON_REQUIRED,
            None,
            code,
        )

    def _terminal_decision(
        self, *, code, scope, actor, action_code,
        context=None, identity=None, revoked=False, correlation_reference=None,
    ):
        now = self._clock.now_audit_time()
        correlation_id = context.correlation_id if context is not None else None
        correlation_ref = correlation_reference or (
            self._reference("cr1", correlation_id) if correlation_id else self._reference("cr1", "unavailable")
        )
        principal_ref = None
        if context is not None:
            try:
                principal_ref = self._subjects.encode(
                    issuer=context.issuer, tenant_key=context.tenant_key,
                    principal_kind=context.expected_principal_kind,
                    provider_subject=context.subject,
                )
            except Exception:
                principal_ref = None
        event = SecurityAuditEventDTO(
            event_type=ApplicationEventType.AUTHORIZATION_DENIED,
            occurred_at=now,
            correlation_id=correlation_id or "authorization-context-unavailable",
            scope=scope,
            actor_id=principal_ref or "<unresolved>",
            decision_code=code.value,
            safe_attributes=(("event_name", "security.authorization.deny.adapter_terminal"),),
        )
        audit_state, receipt_ref, _ = self._record_audit(event, required=True)
        return self._build_decision(
            granted=False, revoked=revoked, code=code,
            action_code=action_code,
            policy_reason=None, resource_version=None,
            principal_reference=principal_ref,
            identity=identity, evaluated_at=now,
            audit_state=audit_state, receipt_reference=receipt_ref,
            correlation_id=correlation_id,
            correlation_reference=correlation_ref,
        )

    def _build_decision(
        self, *, granted, revoked, code, action_code, policy_reason, resource_version,
        principal_reference, identity, evaluated_at, audit_state,
        receipt_reference, correlation_id, correlation_reference=None,
    ):
        try:
            if not isinstance(code, AuthorizationAdapterDecisionCode):
                raise ValueError("decision code is invalid")
            correlation_ref = correlation_reference or self._reference("cr1", correlation_id)
            reference = self._references.encode(
                policy_registry_version=PERMISSION_REGISTRY_VERSION,
                tenant_policy_version=(identity.tenant_policy_version if identity else None),
                action_code=action_code,
                decision_code=code,
                policy_reason=policy_reason,
                resource_version=resource_version,
                principal_reference=principal_reference,
                membership_version=(identity.membership_version if identity else None),
                identity_resolved_at=(identity.resolved_at if identity else None),
                policy_evaluated_at=evaluated_at,
                audit_delivery=audit_state,
                audit_receipt_reference=receipt_reference,
                correlation_reference=correlation_ref,
            )
            return AuthorizationDecision(granted, revoked, code.value, reference, _utc(evaluated_at))
        except Exception:
            return AuthorizationDecision(
                False, False,
                AuthorizationAdapterDecisionCode.AUTHZ_ADAPTER_INTEGRITY_FAILURE.value,
                "adr1:a31a2ecaceba5e0f9ad33c96bde95be366114e04e9b9a68bdb546ce66a65e3da",
                _utc(evaluated_at),
            )

    @staticmethod
    def _repository_error(code, revalidation):
        mapping = {
            PolicyRepositoryErrorCode.STORE_UNAVAILABLE: AuthorizationAdapterDecisionCode.AUTHZ_PROVIDER_UNAVAILABLE,
            PolicyRepositoryErrorCode.STORE_TIMEOUT: AuthorizationAdapterDecisionCode.AUTHZ_PROVIDER_TIMEOUT,
            PolicyRepositoryErrorCode.UNKNOWN_ROLE: AuthorizationAdapterDecisionCode.AUTHZ_UNKNOWN_ROLE,
            PolicyRepositoryErrorCode.UNKNOWN_PERMISSION: AuthorizationAdapterDecisionCode.AUTHZ_UNKNOWN_PERMISSION,
            PolicyRepositoryErrorCode.REGISTRY_VERSION_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_REGISTRY_VERSION_MISMATCH,
            PolicyRepositoryErrorCode.TENANT_POLICY_VERSION_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_TENANT_POLICY_VERSION_MISMATCH,
            PolicyRepositoryErrorCode.PROOF_MISMATCH: AuthorizationAdapterDecisionCode.AUTHZ_POLICY_INTEGRITY_FAILURE,
            PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION: AuthorizationAdapterDecisionCode.AUTHZ_POLICY_INTEGRITY_FAILURE,
            PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND: AuthorizationAdapterDecisionCode.AUTHZ_RESOURCE_NOT_FOUND,
        }
        revoked = revalidation and code in {
            PolicyRepositoryErrorCode.UNKNOWN_ROLE,
            PolicyRepositoryErrorCode.UNKNOWN_PERMISSION,
            PolicyRepositoryErrorCode.REGISTRY_VERSION_MISMATCH,
            PolicyRepositoryErrorCode.TENANT_POLICY_VERSION_MISMATCH,
        }
        return (
            AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_POLICY if revoked else mapping[code],
            revoked,
        )

    @staticmethod
    def _reference(prefix: str, value: str) -> str:
        if not isinstance(prefix, str) or not isinstance(value, str):
            raise ValueError("reference input is invalid")
        return f"{prefix}:" + hashlib.sha256((prefix + "\n" + value).encode()).hexdigest()

    def _metric(self, name: str) -> None:
        try:
            self._observability.increment_metric(name, 1, ())
        except Exception:
            pass


assert len(AuthorizationAdapterDecisionCode) == 47
assert len(TrustedAuthorizationContextErrorCode) == 8
assert len(AuthorizationAuditDeliveryErrorCode) == 6
assert len(_POLICY_DECISIONS) == 17
assert len(_IDENTITY_DECISIONS) == 19
