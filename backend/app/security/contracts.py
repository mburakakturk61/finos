"""Security-core contracts. This module has no framework or ORM dependency."""

from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlsplit

from app.integrations.analysis_http.contracts import AuthenticationStrength


PERMISSION_REGISTRY_VERSION = "1.0.0"
CLAIMS_VERSION = "auth-claims/1"
TENANT_KEY_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
SUBJECT_PATTERN = re.compile(r"^[A-Za-z0-9._:@/|+\-]{1,255}$")
JTI_PATTERN = re.compile(r"^[A-Za-z0-9._~:\-]{16,128}$")
SERVICE_CLIENT_PATTERN = re.compile(r"^[\x21-\x7e]{1,255}$")
ROLE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
SAFE_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._~:\-]{1,128}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class IdentityKind(str, enum.Enum):
    HUMAN = "HUMAN"
    SERVICE = "SERVICE"


class SecurityEntityStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"


class IdentityResolutionErrorCode(str, enum.Enum):
    IDENTITY_NOT_FOUND = "IDENTITY_NOT_FOUND"
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    PRINCIPAL_KIND_MISMATCH = "PRINCIPAL_KIND_MISMATCH"
    TENANT_INACTIVE = "TENANT_INACTIVE"
    PRINCIPAL_INACTIVE = "PRINCIPAL_INACTIVE"
    SUBJECT_BINDING_INACTIVE = "SUBJECT_BINDING_INACTIVE"
    MEMBERSHIP_NOT_FOUND = "MEMBERSHIP_NOT_FOUND"
    MEMBERSHIP_INACTIVE = "MEMBERSHIP_INACTIVE"
    MEMBERSHIP_NOT_YET_VALID = "MEMBERSHIP_NOT_YET_VALID"
    MEMBERSHIP_EXPIRED = "MEMBERSHIP_EXPIRED"
    SERVICE_SAFE_ROLE_NOT_FOUND = "SERVICE_SAFE_ROLE_NOT_FOUND"
    SERVICE_ROLE_PERMISSION_INVALID = "SERVICE_ROLE_PERMISSION_INVALID"
    TOKEN_REVOKED_BY_PRINCIPAL = "TOKEN_REVOKED_BY_PRINCIPAL"
    TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY = "TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY"
    NONCANONICAL_IDENTITY_INPUT = "NONCANONICAL_IDENTITY_INPUT"
    DATA_INTEGRITY_VIOLATION = "DATA_INTEGRITY_VIOLATION"
    IDENTITY_STORE_UNAVAILABLE = "IDENTITY_STORE_UNAVAILABLE"
    IDENTITY_STORE_TIMEOUT = "IDENTITY_STORE_TIMEOUT"


_IDENTITY_ERROR_METADATA = MappingProxyType({
    IdentityResolutionErrorCode.IDENTITY_NOT_FOUND:
        (False, "IDENTITY_RESOLUTION_REJECTED", "security.identity.not_found", "Identity could not be resolved."),
    IdentityResolutionErrorCode.TENANT_NOT_FOUND:
        (False, "IDENTITY_RESOLUTION_REJECTED", "security.identity.tenant_not_found", "Identity could not be resolved."),
    IdentityResolutionErrorCode.TENANT_MISMATCH:
        (False, "CROSS_TENANT_IDENTITY_REJECTED", "security.identity.tenant_mismatch", "Identity scope is invalid."),
    IdentityResolutionErrorCode.PRINCIPAL_KIND_MISMATCH:
        (False, "IDENTITY_PROFILE_REJECTED", "security.identity.kind_mismatch", "Identity profile is invalid."),
    IdentityResolutionErrorCode.TENANT_INACTIVE:
        (False, "IDENTITY_STATE_REJECTED", "security.identity.tenant_inactive", "Identity is not active."),
    IdentityResolutionErrorCode.PRINCIPAL_INACTIVE:
        (False, "IDENTITY_STATE_REJECTED", "security.identity.principal_inactive", "Identity is not active."),
    IdentityResolutionErrorCode.SUBJECT_BINDING_INACTIVE:
        (False, "IDENTITY_STATE_REJECTED", "security.identity.binding_inactive", "Identity is not active."),
    IdentityResolutionErrorCode.MEMBERSHIP_NOT_FOUND:
        (False, "IDENTITY_MEMBERSHIP_REJECTED", "security.identity.membership_not_found", "Identity membership is invalid."),
    IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE:
        (False, "IDENTITY_MEMBERSHIP_REJECTED", "security.identity.membership_inactive", "Identity membership is invalid."),
    IdentityResolutionErrorCode.MEMBERSHIP_NOT_YET_VALID:
        (False, "IDENTITY_MEMBERSHIP_REJECTED", "security.identity.membership_not_yet_valid", "Identity membership is invalid."),
    IdentityResolutionErrorCode.MEMBERSHIP_EXPIRED:
        (False, "IDENTITY_MEMBERSHIP_REJECTED", "security.identity.membership_expired", "Identity membership is invalid."),
    IdentityResolutionErrorCode.SERVICE_SAFE_ROLE_NOT_FOUND:
        (False, "SERVICE_IDENTITY_REJECTED", "security.identity.service_role_not_found", "Service identity grant is invalid."),
    IdentityResolutionErrorCode.SERVICE_ROLE_PERMISSION_INVALID:
        (False, "SERVICE_IDENTITY_REJECTED", "security.identity.service_role_invalid", "Service identity grant is invalid."),
    IdentityResolutionErrorCode.TOKEN_REVOKED_BY_PRINCIPAL:
        (False, "REVOKED_TOKEN_REJECTED", "security.identity.token_principal_revoked", "Identity token is not valid."),
    IdentityResolutionErrorCode.TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY:
        (False, "IDENTITY_VALIDITY_REJECTED", "security.identity.token_before_validity", "Identity token is not valid."),
    IdentityResolutionErrorCode.NONCANONICAL_IDENTITY_INPUT:
        (False, "IDENTITY_INPUT_REJECTED", "security.identity.input_invalid", "Identity input is invalid."),
    IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION:
        (False, "IDENTITY_INTEGRITY_FAILURE", "security.identity.integrity_failure", "Identity state is invalid."),
    IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE:
        (True, "IDENTITY_STORE_FAILURE", "security.identity.store_unavailable", "Identity service is unavailable."),
    IdentityResolutionErrorCode.IDENTITY_STORE_TIMEOUT:
        (True, "IDENTITY_STORE_FAILURE", "security.identity.store_timeout", "Identity service is unavailable."),
})

if frozenset(_IDENTITY_ERROR_METADATA) != frozenset(IdentityResolutionErrorCode):
    raise RuntimeError("Identity resolution metadata must be exhaustive.")


@dataclass(frozen=True, repr=False, init=False, eq=False)
class IdentityResolutionError(Exception):
    code: IdentityResolutionErrorCode
    safe_message: str
    retryable: bool
    audit_event: str
    metric_name: str
    correlation_id: str | None

    def __init__(
        self,
        code: IdentityResolutionErrorCode,
        *,
        correlation_id: str | None = None,
    ) -> None:
        if not isinstance(code, IdentityResolutionErrorCode):
            raise TypeError("Identity resolution error code must be a closed enum value.")
        if correlation_id is not None and not SAFE_CORRELATION_PATTERN.fullmatch(correlation_id):
            raise ValueError("Identity resolution correlation ID is invalid.")
        retryable, audit_event, metric_name, safe_message = _IDENTITY_ERROR_METADATA[code]
        Exception.__init__(self, safe_message)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "safe_message", safe_message)
        object.__setattr__(self, "retryable", retryable)
        object.__setattr__(self, "audit_event", audit_event)
        object.__setattr__(self, "metric_name", metric_name)
        object.__setattr__(self, "correlation_id", correlation_id)

    def __str__(self) -> str:
        return self.safe_message

    def __repr__(self) -> str:
        return (
            "IdentityResolutionError("
            f"code={self.code!r}, retryable={self.retryable!r}, "
            f"correlation_id={self.correlation_id!r})"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, IdentityResolutionError) and (
            self.code,
            self.correlation_id,
        ) == (other.code, other.correlation_id)

    def __hash__(self) -> int:
        return hash((self.code, self.correlation_id))


@dataclass(frozen=True)
class VerifiedLocalIdentity:
    principal_id: uuid.UUID
    principal_kind: IdentityKind
    provider_issuer: str
    provider_subject: str
    tenant_id: uuid.UUID
    tenant_key: str
    membership_id: uuid.UUID
    principal_status: SecurityEntityStatus
    tenant_status: SecurityEntityStatus
    binding_status: SecurityEntityStatus
    membership_status: SecurityEntityStatus
    authentication_context_subject: str
    authentication_context_tenant_key: str
    roles: tuple[str, ...]
    permission_resolution_reference: str
    role_set_digest: str
    permission_registry_version: str
    tenant_policy_version: int
    tokens_valid_after: datetime
    membership_valid_from: datetime
    membership_valid_until: datetime | None
    principal_version: int
    membership_version: int
    resolved_at: datetime

    def __post_init__(self) -> None:
        if not all(isinstance(value, uuid.UUID) for value in (
            self.principal_id, self.tenant_id, self.membership_id,
        )):
            raise ValueError("Identity IDs must be UUID instances.")
        if not isinstance(self.principal_kind, IdentityKind):
            raise ValueError("Principal kind must be a closed enum value.")
        if not _canonical_issuer(self.provider_issuer):
            raise ValueError("Provider issuer is not canonical.")
        if not SUBJECT_PATTERN.fullmatch(self.provider_subject):
            raise ValueError("Provider subject is not canonical.")
        if not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("Tenant key is not canonical.")
        if self.authentication_context_subject != self.provider_subject:
            raise ValueError("Authentication subject does not match provider subject.")
        if self.authentication_context_tenant_key != self.tenant_key:
            raise ValueError("Authentication tenant does not match resolved tenant.")
        statuses = (
            self.principal_status, self.tenant_status,
            self.binding_status, self.membership_status,
        )
        if any(value is not SecurityEntityStatus.ACTIVE for value in statuses):
            raise ValueError("Resolved identity state must be active.")
        if not isinstance(self.roles, tuple) or not self.roles:
            raise ValueError("Resolved roles must be a non-empty tuple.")
        if any(not isinstance(role, str) or not ROLE_CODE_PATTERN.fullmatch(role) for role in self.roles):
            raise ValueError("Resolved role code is not canonical.")
        if self.roles != tuple(sorted(set(self.roles))):
            raise ValueError("Resolved roles must be sorted and unique.")
        if not SHA256_PATTERN.fullmatch(self.role_set_digest):
            raise ValueError("Role-set digest is invalid.")
        if self.permission_registry_version != PERMISSION_REGISTRY_VERSION:
            raise ValueError("Permission registry version is unsupported.")
        versions = (self.tenant_policy_version, self.principal_version, self.membership_version)
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in versions):
            raise ValueError("Identity versions must be positive integers.")
        for value in (
            self.tokens_valid_after, self.membership_valid_from,
            self.resolved_at,
        ):
            _require_normalized_utc(value)
        if self.membership_valid_until is not None:
            _require_normalized_utc(self.membership_valid_until)
            if self.membership_valid_until <= self.membership_valid_from:
                raise ValueError("Membership validity range is invalid.")
        expected_reference = (
            f"policy-ref/v1:{self.tenant_policy_version}:{self.membership_id}:"
            f"{self.membership_version}:{self.permission_registry_version}:"
            f"{self.role_set_digest}"
        )
        if self.permission_resolution_reference != expected_reference:
            raise ValueError("Permission resolution reference is invalid.")


class SecurityIdentityRepositoryPort(Protocol):
    def resolve_principal_and_membership(
        self,
        *,
        issuer: str,
        subject: str,
        tenant_key: str,
        token_issued_at: datetime,
        expected_principal_kind: IdentityKind,
        expected_service_client_id: str | None,
        correlation_id: str,
        request_id: str,
        now: datetime,
    ) -> VerifiedLocalIdentity: ...


def _canonical_issuer(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.netloc == parsed.netloc.lower()
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _require_normalized_utc(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Identity datetime must be timezone-aware UTC.")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Identity datetime must be normalized to UTC.")


class JwtAlgorithm(str, enum.Enum):
    RS256 = "RS256"
    PS256 = "PS256"
    ES256 = "ES256"


class ExistenceHidingPolicy(str, enum.Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DENY_403 = "DENY_403"
    HIDE_404 = "HIDE_404"
    RUN_CONFLICT_409 = "RUN_CONFLICT_409"


class ProvisioningOperationKind(str, enum.Enum):
    CREATE_TENANT = "CREATE_TENANT"
    CREATE_PRINCIPAL = "CREATE_PRINCIPAL"
    CREATE_MEMBERSHIP = "CREATE_MEMBERSHIP"
    ASSIGN_ROLE = "ASSIGN_ROLE"
    REVOKE_MEMBERSHIP = "REVOKE_MEMBERSHIP"
    REVOKE_PRINCIPAL = "REVOKE_PRINCIPAL"
    ROTATE_SUBJECT_BINDING = "ROTATE_SUBJECT_BINDING"


class ProvisioningStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class ProvisioningErrorCode(str, enum.Enum):
    INVALID_COMMAND = "INVALID_COMMAND"
    UNAUTHORIZED = "UNAUTHORIZED"
    IDEMPOTENCY_CONFLICT = "PROVISIONING_IDEMPOTENCY_CONFLICT"
    DUPLICATE_BINDING = "DUPLICATE_SUBJECT_BINDING"
    CROSS_TENANT = "CROSS_TENANT_PROVISIONING"
    AUDIT_FAILED = "SECURITY_AUDIT_FAILED"
    PERSISTENCE_CONFLICT = "PROVISIONING_PERSISTENCE_CONFLICT"
    PERSISTENCE_UNAVAILABLE = "PROVISIONING_PERSISTENCE_UNAVAILABLE"


@dataclass(frozen=True)
class AuthenticationStrengthRule:
    evidence_type: str
    evidence_value: str
    strength: AuthenticationStrength

    def __post_init__(self) -> None:
        if self.evidence_type not in {"acr", "amr"} or not self.evidence_value:
            raise ValueError("Authentication strength rule is invalid.")


@dataclass(frozen=True)
class OidcIssuerProfile:
    issuer: str
    human_audiences: frozenset[str]
    service_audiences: frozenset[str]
    jwks_uri: str
    jwks_allowed_hosts: frozenset[str]
    allowed_algorithms: frozenset[JwtAlgorithm]
    allowed_types: frozenset[str]
    tenant_claim: str = "tenant_id"
    claims_version_claim: str = "claims_version"
    strength_mapping: tuple[AuthenticationStrengthRule, ...] = ()
    jwks_fresh_ttl_seconds: int = 300
    http_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        issuer = urlsplit(self.issuer)
        jwks = urlsplit(self.jwks_uri)
        for parsed in (issuer, jwks):
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Issuer and JWKS URLs must be canonical HTTPS URLs.")
        if jwks.hostname not in self.jwks_allowed_hosts:
            raise ValueError("JWKS host is not allowlisted.")
        if not self.human_audiences or not self.service_audiences:
            raise ValueError("Human and service audiences are required.")
        if self.human_audiences & self.service_audiences:
            raise ValueError("Human and service audiences must be disjoint.")
        if not self.allowed_algorithms or not self.allowed_types:
            raise ValueError("Algorithms and token types are required.")
        if not 30 <= self.jwks_fresh_ttl_seconds <= 900:
            raise ValueError("JWKS fresh TTL is outside the allowed range.")
        if not 0.25 <= self.http_timeout_seconds <= 3.0:
            raise ValueError("JWKS timeout is outside the allowed range.")


class IssuerRegistry:
    def __init__(self, profiles: tuple[OidcIssuerProfile, ...]) -> None:
        by_issuer: dict[str, OidcIssuerProfile] = {}
        audiences: set[str] = set()
        for profile in profiles:
            if profile.issuer in by_issuer:
                raise ValueError("Duplicate issuer profile.")
            profile_audiences = set(profile.human_audiences | profile.service_audiences)
            if audiences & profile_audiences:
                raise ValueError("Audience cannot be shared across issuer profiles.")
            audiences.update(profile_audiences)
            by_issuer[profile.issuer] = profile
        if not by_issuer:
            raise ValueError("At least one issuer profile is required.")
        self._profiles = by_issuer

    def get(self, issuer: str) -> OidcIssuerProfile | None:
        return self._profiles.get(issuer)

    @property
    def issuers(self) -> frozenset[str]:
        return frozenset(self._profiles)


@dataclass(frozen=True)
class VerificationKey:
    issuer: str
    kid: str
    algorithm: JwtAlgorithm
    key: object


@dataclass(frozen=True)
class VerifiedJwt:
    issuer: str
    subject: str
    tenant_key: str
    token_kind: IdentityKind
    audience: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    not_before: datetime | None
    jti: str
    claims_version: str
    authentication_strength: AuthenticationStrength
    kid: str
    algorithm: JwtAlgorithm
    service_client_id: str | None = None


class VerificationKeyProviderPort(Protocol):
    def get_key(
        self, profile: OidcIssuerProfile, kid: str, algorithm: JwtAlgorithm,
        *, now: datetime,
    ) -> VerificationKey: ...

    def readiness_check(self, deadline: datetime) -> bool: ...


@dataclass(frozen=True)
class PermissionDefinition:
    permission_code: str
    resource_type: str
    action: str
    scope_type: str
    minimum_authentication_strength: AuthenticationStrength
    human_allowed: bool
    service_allowed: bool
    existence_hiding_policy: ExistenceHidingPolicy
    permission_registry_version: str = PERMISSION_REGISTRY_VERSION

    def __post_init__(self) -> None:
        if not all((self.permission_code, self.resource_type, self.action, self.scope_type)):
            raise ValueError("Permission definition fields are required.")
        if not (self.human_allowed or self.service_allowed):
            raise ValueError("Permission must allow at least one principal kind.")
        if self.permission_registry_version != PERMISSION_REGISTRY_VERSION:
            raise ValueError("Unsupported permission registry version.")


@dataclass(frozen=True)
class ProvisioningAuthority:
    authority_id: str
    authority_kind: str
    tenant_key: str | None
    principal_id: uuid.UUID | None
    authentication_strength: AuthenticationStrength


@dataclass(frozen=True)
class ProvisioningCommand:
    operation: ProvisioningOperationKind
    authority: ProvisioningAuthority
    idempotency_key: str
    requested_at: datetime
    correlation_id: str
    payload_schema_version: str
    payload: tuple[tuple[str, str], ...]
    effective_at: datetime | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not JTI_PATTERN.fullmatch(self.idempotency_key):
            raise ValueError("Provisioning idempotency key is invalid.")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Provisioning time must be timezone-aware.")
        if not self.correlation_id or not self.payload_schema_version:
            raise ValueError("Provisioning correlation and schema version are required.")


@dataclass(frozen=True)
class ProvisioningOutcome:
    success: bool
    operation_id: uuid.UUID | None
    status: ProvisioningStatus
    error_code: ProvisioningErrorCode | None
    idempotent_replay: bool = False

    def __post_init__(self) -> None:
        if self.success != (self.error_code is None):
            raise ValueError("Provisioning outcome invariant is invalid.")


class IdentityProvisioningPort(Protocol):
    def create_tenant(self, command: ProvisioningCommand) -> ProvisioningOutcome: ...
    def create_principal(self, command: ProvisioningCommand) -> ProvisioningOutcome: ...
    def create_membership(self, command: ProvisioningCommand) -> ProvisioningOutcome: ...
    def assign_role(self, command: ProvisioningCommand) -> ProvisioningOutcome: ...
    def revoke_membership(self, command: ProvisioningCommand) -> ProvisioningOutcome: ...
    def revoke_principal(self, command: ProvisioningCommand) -> ProvisioningOutcome: ...
    def rotate_subject_binding(self, command: ProvisioningCommand) -> ProvisioningOutcome: ...
    def get_provisioning_status(
        self, authority_id: str, idempotency_key: str,
    ) -> ProvisioningOutcome | None: ...


@dataclass(frozen=True)
class AuthenticationAuditEvent:
    event_type: str
    occurred_at: datetime
    correlation_id: str
    authority_id: str
    safe_attributes: tuple[tuple[str, str], ...] = ()


class AuthenticationSecurityAuditPort(Protocol):
    def record_required_event(self, event: AuthenticationAuditEvent) -> str: ...
    def readiness_check(self, deadline: datetime) -> bool: ...


class BootstrapTrustPort(Protocol):
    def verify_bootstrap_authority(self, envelope: object, *, now: datetime) -> ProvisioningAuthority: ...
    def verify_platform_provisioning_authority(self, envelope: object, *, now: datetime) -> ProvisioningAuthority: ...
    def is_bootstrap_open(self) -> bool: ...
