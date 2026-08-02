"""Milestone 5.0E Step 10 framework-independent authorization policy core."""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Protocol

from app.security.contracts import (
    PERMISSION_REGISTRY_VERSION,
    ROLE_CODE_PATTERN,
    SAFE_CORRELATION_PATTERN,
    SHA256_PATTERN,
    SUBJECT_PATTERN,
    TENANT_KEY_PATTERN,
    IdentityKind,
    VerifiedLocalIdentity,
)
from app.security.policy import BUILT_IN_ROLE_PERMISSIONS, PERMISSION_REGISTRY


class PolicyOperationKind(str, enum.Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    CANCEL = "CANCEL"
    RETRY = "RETRY"
    ADMINISTER = "ADMINISTER"


class SubjectPredicateKind(str, enum.Enum):
    NONE = "NONE"
    SELF = "SELF"
    INITIATOR = "INITIATOR"
    SAME_TENANT = "SAME_TENANT"
    EXPLICIT_SUBJECT_MATCH = "EXPLICIT_SUBJECT_MATCH"


class OwnershipRequirement(str, enum.Enum):
    NONE = "NONE"
    RESOURCE_OWNER_REQUIRED = "RESOURCE_OWNER_REQUIRED"
    TENANT_OWNERSHIP_REQUIRED = "TENANT_OWNERSHIP_REQUIRED"


class PolicyScopeType(str, enum.Enum):
    ANALYSIS_RUN = "ANALYSIS_RUN"
    ANALYSIS_RESULT = "ANALYSIS_RESULT"
    EXECUTION = "EXECUTION"
    COMPANY = "COMPANY"
    FINANCIAL_PERIOD = "FINANCIAL_PERIOD"
    DOCUMENT = "DOCUMENT"
    BULK_UPLOAD_BATCH = "BULK_UPLOAD_BATCH"
    TRIAL_BALANCE = "TRIAL_BALANCE"
    SYSTEM = "SYSTEM"
    TENANT = "TENANT"
    COMPANY_PERIOD = "COMPANY_PERIOD"


class PolicyExistenceHiding(str, enum.Enum):
    NONE = "NONE"
    HIDE_ON_TENANT_MISMATCH = "HIDE_ON_TENANT_MISMATCH"
    HIDE_ON_OWNERSHIP_MISMATCH = "HIDE_ON_OWNERSHIP_MISMATCH"
    ALWAYS_HIDE_DENIAL = "ALWAYS_HIDE_DENIAL"


class PolicyAuditRequirement(str, enum.Enum):
    NONE = "NONE"
    DENY_ONLY = "DENY_ONLY"
    ALLOW_AND_DENY = "ALLOW_AND_DENY"
    SECURITY_CRITICAL = "SECURITY_CRITICAL"


class PolicyAuthenticationStrength(str, enum.Enum):
    ANONYMOUS = "ANONYMOUS"
    PASSWORD = "PASSWORD"
    MFA = "MFA"
    PHISHING_RESISTANT = "PHISHING_RESISTANT"
    SERVICE_CREDENTIAL = "SERVICE_CREDENTIAL"


class ResourceOwnershipState(str, enum.Enum):
    TENANT_OWNED = "TENANT_OWNED"
    SUBJECT_OWNED = "SUBJECT_OWNED"
    SHARED_WITHIN_TENANT = "SHARED_WITHIN_TENANT"
    SYSTEM_OWNED = "SYSTEM_OWNED"


class PolicyOutcome(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    INDETERMINATE = "INDETERMINATE"


class PolicyReasonCode(str, enum.Enum):
    ALLOWED = "ALLOWED"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    REGISTRY_VERSION_MISMATCH = "REGISTRY_VERSION_MISMATCH"
    TENANT_POLICY_VERSION_MISMATCH = "TENANT_POLICY_VERSION_MISMATCH"
    PRINCIPAL_KIND_NOT_ALLOWED = "PRINCIPAL_KIND_NOT_ALLOWED"
    PERMISSION_NOT_GRANTED = "PERMISSION_NOT_GRANTED"
    INSUFFICIENT_AUTHENTICATION_STRENGTH = "INSUFFICIENT_AUTHENTICATION_STRENGTH"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    RESOURCE_OWNERSHIP_MISMATCH = "RESOURCE_OWNERSHIP_MISMATCH"
    SUBJECT_PREDICATE_FAILED = "SUBJECT_PREDICATE_FAILED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_STATE_INVALID = "RESOURCE_STATE_INVALID"
    POLICY_STORE_UNAVAILABLE = "POLICY_STORE_UNAVAILABLE"
    POLICY_STORE_TIMEOUT = "POLICY_STORE_TIMEOUT"
    DATA_INTEGRITY_VIOLATION = "DATA_INTEGRITY_VIOLATION"


PolicyEvaluationReasonCode = PolicyReasonCode


class SecuritySeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
_RESOURCE_VERSION_PATTERN = re.compile(r"^rsv1:[0-9a-f]{64}$")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SecurityAction:
    action_code: str
    required_permission: str
    resource_type: PolicyScopeType
    operation_kind: PolicyOperationKind
    minimum_authentication_strength: PolicyAuthenticationStrength
    allowed_principal_kinds: frozenset[IdentityKind]
    ownership_requirement: OwnershipRequirement
    subject_predicate_kind: SubjectPredicateKind
    existence_hiding_policy: PolicyExistenceHiding
    audit_requirement: PolicyAuditRequirement
    registry_version: str

    def __post_init__(self) -> None:
        if not _ACTION_PATTERN.fullmatch(self.action_code):
            raise ValueError("invalid action code")
        if self.action_code != self.required_permission or self.required_permission not in PERMISSION_REGISTRY:
            raise ValueError("invalid required permission")
        enums = (
            (self.resource_type, PolicyScopeType),
            (self.operation_kind, PolicyOperationKind),
            (self.minimum_authentication_strength, PolicyAuthenticationStrength),
            (self.ownership_requirement, OwnershipRequirement),
            (self.subject_predicate_kind, SubjectPredicateKind),
            (self.existence_hiding_policy, PolicyExistenceHiding),
            (self.audit_requirement, PolicyAuditRequirement),
        )
        if any(not isinstance(value, kind) for value, kind in enums):
            raise ValueError("action enum is invalid")
        if not self.allowed_principal_kinds or any(not isinstance(x, IdentityKind) for x in self.allowed_principal_kinds):
            raise ValueError("principal kind set is invalid")
        if self.ownership_requirement is OwnershipRequirement.RESOURCE_OWNER_REQUIRED and self.subject_predicate_kind is not SubjectPredicateKind.NONE:
            raise ValueError("owner action cannot duplicate owner predicate")
        if self.registry_version != PERMISSION_REGISTRY_VERSION:
            raise ValueError("registry version mismatch")


_OPERATION_BY_SOURCE = MappingProxyType({
    "CREATE": PolicyOperationKind.CREATE, "LIST": PolicyOperationKind.READ,
    "READ": PolicyOperationKind.READ, "VALIDATE": PolicyOperationKind.EXECUTE,
    "UPLOAD": PolicyOperationKind.EXECUTE, "UPDATE": PolicyOperationKind.UPDATE,
    "CONFIRM": PolicyOperationKind.EXECUTE, "START": PolicyOperationKind.EXECUTE,
    "RESUME": PolicyOperationKind.EXECUTE, "RESUME_SOURCE": PolicyOperationKind.EXECUTE,
    "RETRY": PolicyOperationKind.RETRY, "CANCEL_OWN": PolicyOperationKind.CANCEL,
    "CANCEL_ANY": PolicyOperationKind.CANCEL, "APPLICATION_READ_GUARD": PolicyOperationKind.READ,
    "APPLICATION_PAYLOAD_GUARD": PolicyOperationKind.READ, "STATUS_READ": PolicyOperationKind.READ,
    "RESULT_METADATA_READ": PolicyOperationKind.READ, "RESULT_PAYLOAD_READ": PolicyOperationKind.READ,
    "HISTORY_READ": PolicyOperationKind.READ, "EXECUTION_METADATA_READ": PolicyOperationKind.READ,
    "EXECUTION_PAYLOAD_READ": PolicyOperationKind.READ, "MANAGE": PolicyOperationKind.ADMINISTER,
    "ASSIGN": PolicyOperationKind.ADMINISTER,
})
_SCOPE_BY_SOURCE = MappingProxyType({
    "GLOBAL": PolicyScopeType.SYSTEM, "TENANT": PolicyScopeType.TENANT,
    "COMPANY": PolicyScopeType.COMPANY, "PERIOD": PolicyScopeType.FINANCIAL_PERIOD,
    "DOCUMENT": PolicyScopeType.DOCUMENT, "ANALYSIS_RESULT": PolicyScopeType.ANALYSIS_RESULT,
    "BULK_BATCH": PolicyScopeType.BULK_UPLOAD_BATCH,
    "COMPANY_PERIOD": PolicyScopeType.COMPANY_PERIOD,
    "ANALYSIS_RUN": PolicyScopeType.ANALYSIS_RUN,
})
_STRENGTH_BY_SOURCE = MappingProxyType({
    "BASIC": PolicyAuthenticationStrength.PASSWORD,
    "STRONG": PolicyAuthenticationStrength.MFA,
    "PHISHING_RESISTANT": PolicyAuthenticationStrength.PHISHING_RESISTANT,
})
_ALLOW_AND_DENY = frozenset({
    "company.create", "period.create", "trial_balance.validate", "trial_balance.upload",
    "bulk_upload.create", "bulk_upload.update", "bulk_upload.confirm", "analysis.start",
    "analysis.resume", "analysis.resume_source", "analysis.retry", "analysis.cancel.own",
    "analysis.cancel.any",
})
_SECURITY_CRITICAL = frozenset({"security.membership.manage", "security.role.assign"})


def _compile_action(code: str) -> SecurityAction:
    definition = PERMISSION_REGISTRY[code]
    try:
        operation = _OPERATION_BY_SOURCE[definition.action]
        scope = _SCOPE_BY_SOURCE[definition.scope_type]
        strength = _STRENGTH_BY_SOURCE[definition.minimum_authentication_strength.value]
    except KeyError as exc:
        raise RuntimeError("permission registry cannot be compiled") from exc
    kinds = frozenset(
        kind for kind, allowed in (
            (IdentityKind.HUMAN, definition.human_allowed),
            (IdentityKind.SERVICE, definition.service_allowed),
        ) if allowed
    )
    ownership = (
        OwnershipRequirement.RESOURCE_OWNER_REQUIRED if code == "analysis.cancel.own"
        else OwnershipRequirement.NONE if code in {"system.metadata.read", "analysis.cancel.any"}
        else OwnershipRequirement.TENANT_OWNERSHIP_REQUIRED
    )
    predicate = (
        SubjectPredicateKind.NONE
        if code in {"system.metadata.read", "analysis.cancel.own", "analysis.cancel.any"}
        else SubjectPredicateKind.SAME_TENANT
    )
    hiding = {
        "DENY_403": PolicyExistenceHiding.NONE,
        "NOT_APPLICABLE": PolicyExistenceHiding.NONE,
        "HIDE_404": PolicyExistenceHiding.ALWAYS_HIDE_DENIAL,
        "RUN_CONFLICT_409": PolicyExistenceHiding.HIDE_ON_TENANT_MISMATCH,
    }[definition.existence_hiding_policy.value]
    audit = (
        PolicyAuditRequirement.SECURITY_CRITICAL if code in _SECURITY_CRITICAL
        else PolicyAuditRequirement.ALLOW_AND_DENY if code in _ALLOW_AND_DENY
        else PolicyAuditRequirement.DENY_ONLY
    )
    return SecurityAction(
        code, code, scope, operation, strength, kinds, ownership, predicate,
        hiding, audit, PERMISSION_REGISTRY_VERSION,
    )


COMPILED_SECURITY_ACTIONS = MappingProxyType({code: _compile_action(code) for code in PERMISSION_REGISTRY})
SECURITY_ACTION_REGISTRY = COMPILED_SECURITY_ACTIONS
ACTION_TO_OPERATION = _OPERATION_BY_SOURCE


BUILT_IN_ROLE_MATRIX = MappingProxyType({
    role: MappingProxyType({code: code in permissions for code in PERMISSION_REGISTRY})
    for role, permissions in BUILT_IN_ROLE_PERMISSIONS.items()
})


def _registry_digest() -> str:
    records = [
        {
            "code": code,
            "resource": item.resource_type,
            "action": item.action,
            "scope": item.scope_type,
            "strength": item.minimum_authentication_strength.value,
            "human": item.human_allowed,
            "service": item.service_allowed,
            "hiding": item.existence_hiding_policy.value,
        }
        for code, item in sorted(PERMISSION_REGISTRY.items())
    ]
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _role_matrix_digest() -> str:
    records = [
        (role, tuple((code, "ALLOW" if matrix[code] else "DENY") for code in sorted(PERMISSION_REGISTRY)))
        for role, matrix in sorted(BUILT_IN_ROLE_MATRIX.items())
    ]
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


PERMISSION_REGISTRY_MANIFEST_DIGEST = "a4747956206d614490ea68f648fe3d890e575a90d733481bdf4d56ca69f12d3f"
BUILT_IN_ROLE_MATRIX_DIGEST = "fcc18e1761bfb293acabc4e3308beadd494f0c7fb8764fadbdf52b59cd417604"
if _registry_digest() != PERMISSION_REGISTRY_MANIFEST_DIGEST or _role_matrix_digest() != BUILT_IN_ROLE_MATRIX_DIGEST:
    raise RuntimeError("authorization policy golden manifest digest mismatch")


@dataclass(frozen=True)
class PolicyMaterializationRequest:
    principal_id: uuid.UUID
    membership_id: uuid.UUID
    principal_kind: IdentityKind
    tenant_id: uuid.UUID
    tenant_key: str
    roles: tuple[str, ...]
    permission_registry_version: str
    tenant_policy_version: int
    role_set_digest: str
    permission_resolution_reference: str
    current_time: datetime
    correlation_id: str

    def __post_init__(self) -> None:
        if not all(isinstance(x, uuid.UUID) for x in (self.principal_id, self.membership_id, self.tenant_id)):
            raise ValueError("materialization IDs must be UUIDs")
        if not isinstance(self.principal_kind, IdentityKind) or not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("materialization identity is invalid")
        if not self.roles or self.roles != tuple(sorted(set(self.roles))) or any(not ROLE_CODE_PATTERN.fullmatch(x) for x in self.roles):
            raise ValueError("materialization roles are invalid")
        if self.permission_registry_version != PERMISSION_REGISTRY_VERSION or self.tenant_policy_version <= 0:
            raise ValueError("materialization version is invalid")
        if not SHA256_PATTERN.fullmatch(self.role_set_digest) or not SAFE_CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("materialization proof is invalid")
        _utc(self.current_time)


@dataclass(frozen=True)
class EffectivePermissionSet:
    permission_codes: tuple[str, ...]
    role_codes: tuple[str, ...]
    principal_kind: IdentityKind
    membership_id: uuid.UUID
    permission_registry_version: str
    tenant_policy_version: int
    role_assignment_version: int
    role_set_digest: str
    materialized_at: datetime

    def __post_init__(self) -> None:
        if self.permission_codes != tuple(sorted(set(self.permission_codes))) or not self.permission_codes:
            raise ValueError("permissions must be sorted and unique")
        if any(code not in PERMISSION_REGISTRY for code in self.permission_codes):
            raise ValueError("unknown permission")
        if self.role_codes != tuple(sorted(set(self.role_codes))) or not self.role_codes:
            raise ValueError("roles must be sorted and unique")
        if not isinstance(self.principal_kind, IdentityKind) or not isinstance(self.membership_id, uuid.UUID):
            raise ValueError("permission principal is invalid")
        if self.permission_registry_version != PERMISSION_REGISTRY_VERSION or self.tenant_policy_version <= 0 or self.role_assignment_version <= 0:
            raise ValueError("permission version is invalid")
        if not SHA256_PATTERN.fullmatch(self.role_set_digest):
            raise ValueError("permission digest is invalid")
        _utc(self.materialized_at)


@dataclass(frozen=True)
class ResolvedPolicyRole:
    role_id: uuid.UUID
    role_code: str
    role_version: int
    assignment_version: int
    permission_codes: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class ResourceSecurityReference:
    scope_type: PolicyScopeType
    resource_id: uuid.UUID | str
    request_tenant_key: str | None
    company_id: uuid.UUID | None
    period_id: uuid.UUID | None
    expected_resource_version: str | None
    correlation_id: str
    referenced_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.scope_type, PolicyScopeType) or not SAFE_CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("resource reference is invalid")
        _utc(self.referenced_at)
        if self.expected_resource_version is not None and not _RESOURCE_VERSION_PATTERN.fullmatch(self.expected_resource_version):
            raise ValueError("expected resource version is invalid")
        if self.scope_type is PolicyScopeType.SYSTEM:
            if self.resource_id != "system" or self.request_tenant_key is not None or self.company_id is not None or self.period_id is not None:
                raise ValueError("system reference is invalid")
        elif self.scope_type is PolicyScopeType.TENANT:
            if self.resource_id != self.request_tenant_key or not isinstance(self.resource_id, str) or not TENANT_KEY_PATTERN.fullmatch(self.resource_id):
                raise ValueError("tenant reference is invalid")
            if self.company_id is not None or self.period_id is not None:
                raise ValueError("tenant reference fields are invalid")
        elif self.scope_type is PolicyScopeType.COMPANY_PERIOD:
            if not isinstance(self.company_id, uuid.UUID) or not isinstance(self.period_id, uuid.UUID):
                raise ValueError("company-period IDs are invalid")
            expected = f"cp1:{self.company_id}:{self.period_id}"
            if self.resource_id != expected or not self.request_tenant_key:
                raise ValueError("company-period reference is invalid")
        else:
            if self.scope_type is PolicyScopeType.ANALYSIS_RUN:
                if not isinstance(self.resource_id, str) or not self.resource_id:
                    raise ValueError("analysis run reference is invalid")
            elif not isinstance(self.resource_id, uuid.UUID):
                raise ValueError("resource ID must be UUID")
            if not self.request_tenant_key or self.company_id is not None or self.period_id is not None:
                raise ValueError("durable reference fields are invalid")

    def __repr__(self) -> str:
        return f"ResourceSecurityReference(scope_type={self.scope_type.value!r}, resource_id='<redacted>')"


@dataclass(frozen=True, repr=False)
class ResourceSecurityScope:
    resource_type: PolicyScopeType
    resource_id: uuid.UUID | str
    tenant_key: str | None
    company_id: uuid.UUID | None
    period_id: uuid.UUID | None
    owner_subject: str | None
    initiator_subject: str | None
    resource_version: str
    existence_hiding_policy: PolicyExistenceHiding
    ownership_state: ResourceOwnershipState
    resolved_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.resource_type, PolicyScopeType) or not _RESOURCE_VERSION_PATTERN.fullmatch(self.resource_version):
            raise ValueError("resource scope is invalid")
        if not isinstance(self.existence_hiding_policy, PolicyExistenceHiding) or not isinstance(self.ownership_state, ResourceOwnershipState):
            raise ValueError("resource scope enums are invalid")
        _utc(self.resolved_at)
        if self.tenant_key is not None and not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("resource tenant is invalid")
        if self.ownership_state is ResourceOwnershipState.SUBJECT_OWNED and not self.owner_subject:
            raise ValueError("subject-owned resource requires owner")

    def __repr__(self) -> str:
        return f"ResourceSecurityScope(resource_type={self.resource_type.value!r}, resource_id='<redacted>')"


@dataclass(frozen=True, repr=False)
class PolicyEvaluationRequest:
    identity: VerifiedLocalIdentity
    authentication_strength: PolicyAuthenticationStrength
    action: SecurityAction
    resource_reference: ResourceSecurityReference
    explicit_subject: str | None
    target_subject: str | None
    correlation_id: str
    evaluated_at: datetime
    expected_registry_version: str
    expected_tenant_policy_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.identity, VerifiedLocalIdentity) or not isinstance(self.authentication_strength, PolicyAuthenticationStrength):
            raise ValueError("evaluation identity is invalid")
        if not isinstance(self.action, SecurityAction) or not isinstance(self.resource_reference, ResourceSecurityReference):
            raise ValueError("evaluation contract is invalid")
        if self.correlation_id != self.resource_reference.correlation_id or not SAFE_CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("evaluation correlation is invalid")
        if self.expected_registry_version != PERMISSION_REGISTRY_VERSION or self.expected_tenant_policy_version <= 0:
            raise ValueError("evaluation version is invalid")
        evaluated = _utc(self.evaluated_at)
        if _utc(self.resource_reference.referenced_at) > evaluated:
            raise ValueError("resource reference is from the future")
        for subject in (self.explicit_subject, self.target_subject):
            if subject is not None and not SUBJECT_PATTERN.fullmatch(subject):
                raise ValueError("evaluation subject is invalid")


class PolicyRepositoryErrorCode(str, enum.Enum):
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    STORE_TIMEOUT = "STORE_TIMEOUT"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
    REGISTRY_VERSION_MISMATCH = "REGISTRY_VERSION_MISMATCH"
    TENANT_POLICY_VERSION_MISMATCH = "TENANT_POLICY_VERSION_MISMATCH"
    PROOF_MISMATCH = "PROOF_MISMATCH"
    DATA_INTEGRITY_VIOLATION = "DATA_INTEGRITY_VIOLATION"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"


_REPOSITORY_ERROR_METADATA = MappingProxyType({
    PolicyRepositoryErrorCode.STORE_UNAVAILABLE: (True, "security.policy.repository.unavailable", "security.policy.repository.store_unavailable", "Policy store is unavailable."),
    PolicyRepositoryErrorCode.STORE_TIMEOUT: (True, "security.policy.repository.timeout", "security.policy.repository.store_timeout", "Policy store timed out."),
    PolicyRepositoryErrorCode.UNKNOWN_ROLE: (False, "security.policy.repository.unknown_role", "security.policy.repository.unknown_role", "Policy role is invalid."),
    PolicyRepositoryErrorCode.UNKNOWN_PERMISSION: (False, "security.policy.repository.unknown_permission", "security.policy.repository.unknown_permission", "Policy permission is invalid."),
    PolicyRepositoryErrorCode.REGISTRY_VERSION_MISMATCH: (False, "security.policy.repository.registry_version", "security.policy.repository.registry_version_mismatch", "Policy registry version is invalid."),
    PolicyRepositoryErrorCode.TENANT_POLICY_VERSION_MISMATCH: (False, "security.policy.repository.tenant_version", "security.policy.repository.tenant_policy_version_mismatch", "Tenant policy version is invalid."),
    PolicyRepositoryErrorCode.PROOF_MISMATCH: (False, "security.policy.repository.proof_mismatch", "security.policy.repository.proof_mismatch", "Policy proof is invalid."),
    PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION: (False, "security.policy.repository.integrity", "security.policy.repository.data_integrity_violation", "Policy state is invalid."),
    PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND: (False, "security.policy.repository.resource_not_found", "security.policy.repository.resource_not_found", "Resource is not accessible."),
})


class PolicyRepositoryError(Exception):
    __slots__ = ("_code", "_correlation_id", "_safe_message", "_retryable", "_metric_name", "_audit_event", "_internal_cause", "_frozen")

    def __init__(self, *, code: PolicyRepositoryErrorCode, correlation_id: str, internal_cause: BaseException | None = None) -> None:
        if not isinstance(code, PolicyRepositoryErrorCode):
            raise TypeError("invalid PolicyRepositoryErrorCode")
        if not SAFE_CORRELATION_PATTERN.fullmatch(correlation_id):
            raise ValueError("invalid correlation_id")
        if internal_cause is not None and not isinstance(internal_cause, BaseException):
            raise TypeError("invalid internal_cause")
        metadata = _REPOSITORY_ERROR_METADATA[code]
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_correlation_id", correlation_id)
        object.__setattr__(self, "_retryable", metadata[0])
        object.__setattr__(self, "_metric_name", metadata[1])
        object.__setattr__(self, "_audit_event", metadata[2])
        object.__setattr__(self, "_safe_message", metadata[3])
        object.__setattr__(self, "_internal_cause", internal_cause)
        Exception.__init__(self, self._safe_message)
        object.__setattr__(self, "_frozen", True)

    @property
    def code(self) -> PolicyRepositoryErrorCode: return self._code
    @property
    def correlation_id(self) -> str: return self._correlation_id
    @property
    def safe_message(self) -> str: return self._safe_message
    @property
    def retryable(self) -> bool: return self._retryable
    @property
    def metric_name(self) -> str: return self._metric_name
    @property
    def audit_event(self) -> str: return self._audit_event
    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False): raise AttributeError("immutable")
        object.__setattr__(self, name, value)
    def __delattr__(self, name: str) -> None: raise AttributeError("immutable")
    def __init_subclass__(cls, **kwargs: object) -> None: raise TypeError("PolicyRepositoryError is final")
    def __str__(self) -> str: return self._safe_message
    def __repr__(self) -> str: return f"PolicyRepositoryError(code={self.code.value!r}, correlation_id='<redacted>')"


class PolicyEvaluationConstructionError(Exception):
    __slots__ = ("_code", "_safe_message", "_metric_name", "_audit_event", "_correlation_id", "_internal_cause", "_frozen")
    def __init__(self, *, correlation_id: str | None, internal_cause: BaseException | None = None) -> None:
        if correlation_id is not None and not SAFE_CORRELATION_PATTERN.fullmatch(correlation_id): correlation_id = None
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_code", "POLICY_EVALUATION_CONSTRUCTION_FAILED")
        object.__setattr__(self, "_safe_message", "Policy evaluation result could not be constructed.")
        object.__setattr__(self, "_metric_name", "security.policy.result_construction_failure")
        object.__setattr__(self, "_audit_event", "security.authorization.indeterminate.data_integrity_violation")
        object.__setattr__(self, "_correlation_id", correlation_id)
        object.__setattr__(self, "_internal_cause", internal_cause)
        Exception.__init__(self, self._safe_message, self._code)
        object.__setattr__(self, "_frozen", True)
    @property
    def code(self) -> str: return self._code
    @property
    def safe_message(self) -> str: return self._safe_message
    @property
    def metric_name(self) -> str: return self._metric_name
    @property
    def audit_event(self) -> str: return self._audit_event
    @property
    def correlation_id(self) -> str | None: return self._correlation_id
    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False): raise AttributeError("immutable")
        object.__setattr__(self, name, value)
    def __delattr__(self, name: str) -> None: raise AttributeError("immutable")
    def __init_subclass__(cls, **kwargs: object) -> None: raise TypeError("PolicyEvaluationConstructionError is final")
    def __str__(self) -> str: return self._safe_message
    def __repr__(self) -> str: return "PolicyEvaluationConstructionError(code='POLICY_EVALUATION_CONSTRUCTION_FAILED')"


class ResourceSecurityVersionCodec:
    PREFIX = b"rsv1\n"
    def canonical_bytes(self, fields: tuple[tuple[str, str], ...], values: Mapping[str, object]) -> bytes:
        if set(values) != {name for name, _ in fields}: raise ValueError("manifest fields mismatch")
        output = bytearray(self.PREFIX)
        for name, tag in fields:
            actual_tag = ("n" if values[name] is None else tag[:-1]) if tag.endswith("?") else tag
            payload = self._payload(actual_tag, values[name])
            output.extend(f"{name}|{actual_tag}|{len(payload)}|".encode()); output.extend(payload); output.extend(b"\n")
        return bytes(output)
    def version(self, fields: tuple[tuple[str, str], ...], values: Mapping[str, object]) -> str:
        return "rsv1:" + hashlib.sha256(self.canonical_bytes(fields, values)).hexdigest()
    def primitive_bytes(self, value: object, tag: str) -> bytes:
        return self.canonical_bytes((("value", tag),), {"value": value})
    def scope_bytes(self, scope_type: PolicyScopeType, values: Mapping[str, object]) -> bytes:
        if not isinstance(scope_type, PolicyScopeType): raise ValueError("scope type is invalid")
        return self.canonical_bytes(RESOURCE_SCOPE_MANIFESTS[scope_type], values)
    def scope_version(self, scope_type: PolicyScopeType, values: Mapping[str, object]) -> str:
        return "rsv1:" + hashlib.sha256(self.scope_bytes(scope_type, values)).hexdigest()
    @staticmethod
    def _payload(tag: str, value: object) -> bytes:
        if tag == "n":
            if value is not None: raise ValueError("null expected")
            return b"null"
        if tag == "s":
            if not isinstance(value, str): raise ValueError("str expected")
            return value.encode()
        if tag == "u":
            if not isinstance(value, uuid.UUID): raise ValueError("UUID expected")
            return str(value).encode()
        if tag == "e":
            if not isinstance(value, enum.Enum): raise ValueError("enum expected")
            return str(value.value).encode()
        if tag == "i":
            if not isinstance(value, int) or isinstance(value, bool): raise ValueError("int expected")
            return str(value).encode()
        if tag == "b":
            if not isinstance(value, bool): raise ValueError("bool expected")
            return b"true" if value else b"false"
        if tag == "t": return _utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ").encode()  # type: ignore[arg-type]
        if tag == "d":
            if not isinstance(value, date) or isinstance(value, datetime): raise ValueError("date expected")
            return value.isoformat().encode()
        if tag == "m":
            if not isinstance(value, Decimal) or not value.is_finite(): raise ValueError("Decimal expected")
            text = format(value, "f"); text = text.rstrip("0").rstrip(".") if "." in text else text
            return ("0" if Decimal(text or "0") == 0 else text).encode()
        if tag == "x":
            if not isinstance(value, bytes): raise ValueError("bytes expected")
            return value.hex().encode()
        if tag == "q":
            if not isinstance(value, tuple): raise ValueError("tuple expected")
            encoded = []
            for item in value:
                if not isinstance(item, str): raise ValueError("tuple strings expected")
                raw = item.encode(); encoded.append(b"s:" + str(len(raw)).encode() + b":" + raw + b"|")
            if encoded != sorted(set(encoded)): raise ValueError("tuple must be sorted and unique")
            return str(len(encoded)).encode() + b"|" + b"".join(encoded)
        raise ValueError("unknown type tag")


class SubjectReferenceHashCodec:
    def __init__(self, keys: Mapping[str, bytes], *, active_key_version: str) -> None:
        if not re.fullmatch(r"k[1-9][0-9]*", active_key_version) or active_key_version not in keys:
            raise ValueError("active subject-reference key is invalid")
        if any(not isinstance(key, bytes) or len(key) < 32 for key in keys.values()): raise ValueError("subject-reference key is invalid")
        self._keys = MappingProxyType(dict(keys)); self._active = active_key_version
    def encode(self, *, issuer: str, tenant_key: str, principal_kind: IdentityKind, provider_subject: str, key_version: str | None = None) -> str:
        version = key_version or self._active
        if version not in self._keys or not TENANT_KEY_PATTERN.fullmatch(tenant_key) or not SUBJECT_PATTERN.fullmatch(provider_subject):
            raise ValueError("subject reference input is invalid")
        if not isinstance(principal_kind, IdentityKind) or not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise ValueError("subject reference input is invalid")
        fields = (("key_version", "s", version), ("domain", "s", "finos-security-subject-reference-v1"), ("issuer", "s", issuer), ("tenant_key", "s", tenant_key), ("principal_kind", "e", principal_kind.value), ("provider_subject", "s", provider_subject))
        frame = bytearray(b"srh1\n")
        for name, tag, value in fields:
            raw=value.encode(); frame.extend(f"{name}|{tag}|{len(raw)}|".encode()); frame.extend(raw); frame.extend(b"\n")
        return f"srh1:{version}:" + hmac.new(self._keys[version], bytes(frame), hashlib.sha256).hexdigest()


@dataclass(frozen=True, repr=False)
class AuditIntent:
    required: bool
    requirement: PolicyAuditRequirement
    event_name: str
    outcome: PolicyOutcome
    reason_code: PolicyReasonCode
    action_code: str
    resource_type: PolicyScopeType
    correlation_id: str
    subject_reference_hash: str
    tenant_key: str
    security_severity: SecuritySeverity

    def __post_init__(self) -> None:
        if not isinstance(self.required, bool):
            raise ValueError("audit required flag is invalid")
        if not all(isinstance(value, expected) for value, expected in (
            (self.requirement, PolicyAuditRequirement),
            (self.outcome, PolicyOutcome),
            (self.reason_code, PolicyReasonCode),
            (self.resource_type, PolicyScopeType),
            (self.security_severity, SecuritySeverity),
        )):
            raise ValueError("audit enums are invalid")
        expected_event = (
            "security.authorization."
            f"{self.outcome.value.lower()}.{self.reason_code.value.lower()}"
        )
        if self.event_name != expected_event:
            raise ValueError("audit event name is invalid")
        if not _ACTION_PATTERN.fullmatch(self.action_code):
            raise ValueError("audit action is invalid")
        if not SAFE_CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("audit correlation is invalid")
        if not re.fullmatch(r"srh1:k[1-9][0-9]*:[0-9a-f]{64}", self.subject_reference_hash):
            raise ValueError("audit subject reference is invalid")
        if not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("audit tenant is invalid")

    def __repr__(self) -> str:
        return (
            f"AuditIntent(event_name={self.event_name!r}, "
            "subject_reference_hash='<redacted>', tenant_key='<redacted>')"
        )

    __str__ = __repr__


@dataclass(frozen=True, repr=False)
class PolicyEvaluationResult:
    outcome: PolicyOutcome
    reason_code: PolicyReasonCode
    evaluated_action: str
    principal_id: uuid.UUID
    tenant_key: str
    resource_type: PolicyScopeType
    resource_id: uuid.UUID | str
    matched_permission: str | None
    authentication_strength: PolicyAuthenticationStrength
    principal_kind: IdentityKind
    subject_predicate_result: bool | None
    ownership_result: bool | None
    existence_hiding_required: bool
    audit_intent: AuditIntent
    policy_registry_version: str
    tenant_policy_version: int
    evaluated_at: datetime
    correlation_id: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, expected) for value, expected in (
            (self.outcome, PolicyOutcome),
            (self.reason_code, PolicyReasonCode),
            (self.principal_id, uuid.UUID),
            (self.resource_type, PolicyScopeType),
            (self.authentication_strength, PolicyAuthenticationStrength),
            (self.principal_kind, IdentityKind),
            (self.existence_hiding_required, bool),
            (self.audit_intent, AuditIntent),
        )):
            raise ValueError("policy result types are invalid")
        if not _ACTION_PATTERN.fullmatch(self.evaluated_action):
            raise ValueError("policy result action is invalid")
        if not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("policy result tenant is invalid")
        if self.policy_registry_version != PERMISSION_REGISTRY_VERSION or self.tenant_policy_version <= 0:
            raise ValueError("policy result version is invalid")
        if not SAFE_CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("policy result correlation is invalid")
        _utc(self.evaluated_at)
        if self.audit_intent.reason_code is not self.reason_code or self.audit_intent.outcome is not self.outcome:
            raise ValueError("policy result audit reason is invalid")
        if self.audit_intent.action_code != self.evaluated_action or self.audit_intent.correlation_id != self.correlation_id:
            raise ValueError("policy result audit binding is invalid")
        if self.outcome is PolicyOutcome.ALLOW:
            if self.reason_code is not PolicyReasonCode.ALLOWED or self.matched_permission is None or self.subject_predicate_result is not True or self.ownership_result is not True:
                raise ValueError("invalid allow result")
        elif self.matched_permission is not None:
            raise ValueError("non-allow cannot expose permission")

    def __repr__(self) -> str:
        return (
            f"PolicyEvaluationResult(outcome={self.outcome.value!r}, "
            f"reason_code={self.reason_code.value!r}, "
            f"correlation_id={self.correlation_id!r})"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class _ReasonMetadata:
    outcome: PolicyOutcome; retryable: bool; always_hide: bool; severity: SecuritySeverity; metric: str; message: str


_RM = {
    PolicyReasonCode.ALLOWED: (PolicyOutcome.ALLOW,False,False,SecuritySeverity.LOW,"security.policy.allow","Policy evaluation allowed."),
    PolicyReasonCode.UNKNOWN_ACTION:(PolicyOutcome.DENY,False,True,SecuritySeverity.HIGH,"security.policy.unknown_action","Policy action is invalid."),
    PolicyReasonCode.UNKNOWN_PERMISSION:(PolicyOutcome.DENY,False,True,SecuritySeverity.CRITICAL,"security.policy.unknown_permission","Policy permission is invalid."),
    PolicyReasonCode.UNKNOWN_ROLE:(PolicyOutcome.DENY,False,False,SecuritySeverity.HIGH,"security.policy.unknown_role","Policy role is invalid."),
    PolicyReasonCode.REGISTRY_VERSION_MISMATCH:(PolicyOutcome.DENY,False,False,SecuritySeverity.HIGH,"security.policy.registry_version","Policy version is invalid."),
    PolicyReasonCode.TENANT_POLICY_VERSION_MISMATCH:(PolicyOutcome.DENY,False,False,SecuritySeverity.HIGH,"security.policy.tenant_version","Policy version is invalid."),
    PolicyReasonCode.PRINCIPAL_KIND_NOT_ALLOWED:(PolicyOutcome.DENY,False,False,SecuritySeverity.MEDIUM,"security.policy.principal_kind","Principal kind is not permitted."),
    PolicyReasonCode.PERMISSION_NOT_GRANTED:(PolicyOutcome.DENY,False,False,SecuritySeverity.MEDIUM,"security.policy.permission_denied","Permission is not granted."),
    PolicyReasonCode.INSUFFICIENT_AUTHENTICATION_STRENGTH:(PolicyOutcome.DENY,False,False,SecuritySeverity.MEDIUM,"security.policy.strength","Authentication strength is insufficient."),
    PolicyReasonCode.TENANT_MISMATCH:(PolicyOutcome.DENY,False,True,SecuritySeverity.HIGH,"security.policy.tenant_mismatch","Resource scope is not accessible."),
    PolicyReasonCode.RESOURCE_OWNERSHIP_MISMATCH:(PolicyOutcome.DENY,False,False,SecuritySeverity.HIGH,"security.policy.ownership","Resource scope is not accessible."),
    PolicyReasonCode.SUBJECT_PREDICATE_FAILED:(PolicyOutcome.DENY,False,False,SecuritySeverity.MEDIUM,"security.policy.subject","Subject predicate is not satisfied."),
    PolicyReasonCode.RESOURCE_NOT_FOUND:(PolicyOutcome.DENY,False,True,SecuritySeverity.MEDIUM,"security.policy.resource_not_found","Resource is not accessible."),
    PolicyReasonCode.RESOURCE_STATE_INVALID:(PolicyOutcome.DENY,False,True,SecuritySeverity.CRITICAL,"security.policy.resource_invalid","Resource security state is invalid."),
    PolicyReasonCode.POLICY_STORE_UNAVAILABLE:(PolicyOutcome.INDETERMINATE,True,True,SecuritySeverity.HIGH,"security.policy.store_unavailable","Policy service is unavailable."),
    PolicyReasonCode.POLICY_STORE_TIMEOUT:(PolicyOutcome.INDETERMINATE,True,True,SecuritySeverity.HIGH,"security.policy.store_timeout","Policy service is unavailable."),
    PolicyReasonCode.DATA_INTEGRITY_VIOLATION:(PolicyOutcome.INDETERMINATE,False,True,SecuritySeverity.CRITICAL,"security.policy.integrity_failure","Policy state is invalid."),
}
POLICY_REASON_METADATA = MappingProxyType({k:_ReasonMetadata(*v) for k,v in _RM.items()})

TOP_LEVEL_PRECEDENCE = tuple(range(1, 19))
STEP7_PRECEDENCE = tuple(f"7.{index}" for index in range(1, 12))
STEP10_PRECEDENCE = tuple(f"10.{index}" for index in range(1, 12))
STEP7_LITERAL_CASES = MappingProxyType({
    "S7-01": PolicyReasonCode.POLICY_STORE_TIMEOUT,
    "S7-02": PolicyReasonCode.POLICY_STORE_UNAVAILABLE,
    "S7-03": PolicyReasonCode.UNKNOWN_ROLE,
    "S7-04": PolicyReasonCode.REGISTRY_VERSION_MISMATCH,
    "S7-05": PolicyReasonCode.TENANT_POLICY_VERSION_MISMATCH,
    "S7-06": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S7-07": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S7-08": PolicyReasonCode.UNKNOWN_ROLE,
    "S7-09": PolicyReasonCode.REGISTRY_VERSION_MISMATCH,
    "S7-10": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S7-11": PolicyReasonCode.UNKNOWN_PERMISSION,
})
STEP10_LITERAL_CASES = MappingProxyType({
    "S10-01": PolicyReasonCode.RESOURCE_STATE_INVALID,
    "S10-02": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S10-03": PolicyReasonCode.POLICY_STORE_TIMEOUT,
    "S10-04": PolicyReasonCode.POLICY_STORE_UNAVAILABLE,
    "S10-05": PolicyReasonCode.RESOURCE_NOT_FOUND,
    "S10-06": PolicyReasonCode.RESOURCE_NOT_FOUND,
    "S10-07": PolicyReasonCode.RESOURCE_NOT_FOUND,
    "S10-08": PolicyReasonCode.RESOURCE_NOT_FOUND,
    "S10-09": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S10-10": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S10-11": PolicyReasonCode.RESOURCE_STATE_INVALID,
    "S10-12": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S10-13": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S10-14": PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    "S10-15": PolicyReasonCode.TENANT_MISMATCH,
    "S10-16": PolicyReasonCode.RESOURCE_NOT_FOUND,
    "S10-17": PolicyReasonCode.RESOURCE_NOT_FOUND,
})


class AuthorizationPolicyRepositoryPort(Protocol):
    def resolve_role_assignments(self, request: PolicyMaterializationRequest) -> tuple[ResolvedPolicyRole, ...]: ...
    def resolve_effective_permissions(self, request: PolicyMaterializationRequest) -> EffectivePermissionSet: ...
    def validate_registry_versions(self, request: PolicyMaterializationRequest) -> None: ...
    def resolve_tenant_policy_version(self, tenant_id: uuid.UUID, *, correlation_id: str) -> int: ...


class ResourceSecurityRepositoryPort(Protocol):
    def resolve_durable_scope(self, *, resource_type: PolicyScopeType, resource_id: uuid.UUID | str, expected_tenant_key: str, current_time: datetime, correlation_id: str) -> ResourceSecurityScope: ...


class SyntheticSecurityScopeResolverPort(Protocol):
    def resolve_system_scope(self, *, current_time: datetime, correlation_id: str) -> ResourceSecurityScope: ...
    def resolve_tenant_scope(self, *, tenant_key: str, identity_tenant_key: str, expected_tenant_policy_version: int, current_time: datetime, correlation_id: str) -> ResourceSecurityScope: ...
    def resolve_company_period_scope(self, *, company_id: uuid.UUID, financial_period_id: uuid.UUID, expected_tenant_key: str, current_time: datetime, correlation_id: str) -> ResourceSecurityScope: ...


RESOURCE_SCOPE_MANIFESTS = MappingProxyType({
    PolicyScopeType.SYSTEM: (("resource_type","e"),("resource_id","s")),
    PolicyScopeType.TENANT: (("resource_type","e"),("tenant_id","u"),("tenant_key","s"),("tenant_policy_version","i")),
    PolicyScopeType.COMPANY: (("resource_type","e"),("id","u"),("tenant_id","u"),("updated_at","t")),
    PolicyScopeType.FINANCIAL_PERIOD: (("resource_type","e"),("id","u"),("company_id","u"),("status","e"),("updated_at","t")),
    PolicyScopeType.COMPANY_PERIOD: (("resource_type","e"),("resource_id","s"),("company_id","u"),("period_id","u"),("company_updated_at","t"),("period_updated_at","t")),
    PolicyScopeType.DOCUMENT: (("resource_type","e"),("id","u"),("company_id","u"),("period_id","u"),("checksum","x"),("processing_status","e"),("processed_at","t?")),
    PolicyScopeType.ANALYSIS_RESULT: (("resource_type","e"),("id","u"),("company_id","u"),("period_id","u"),("status","e"),("canonical_result_digest","x"),("completed_at","t?")),
    PolicyScopeType.ANALYSIS_RUN: (("resource_type","e"),("claim_id","u"),("run_id","s"),("company_id","u"),("financial_period_id","u"),("tenant_key","s"),("initiating_subject_reference","s"),("claim_version","i"),("claim_status","e"),("terminal_content_digest","x?")),
    PolicyScopeType.EXECUTION: (("resource_type","e"),("execution_id","u"),("orchestration_run_id","u"),("engine_code","e"),("status","e"),("input_fingerprint","x"),("owner_content_digest","x?"),("claim_version","i")),
    PolicyScopeType.BULK_UPLOAD_BATCH: (("resource_type","e"),("id","u"),("tenant_id","u"),("status","e"),("total_file_count","i"),("classified_file_count","i"),("unclassified_file_count","i"),("duplicate_file_count","i"),("completed_at","t?"),("confirmed_at","t?")),
    PolicyScopeType.TRIAL_BALANCE: (("resource_type","e"),("id","u"),("company_id","u"),("period_id","u"),("analysis_type","e"),("source_mode","e"),("status","e"),("canonical_result_digest","x"),("completed_at","t?")),
})


_REPO_TO_REASON = {
    PolicyRepositoryErrorCode.STORE_UNAVAILABLE: PolicyReasonCode.POLICY_STORE_UNAVAILABLE,
    PolicyRepositoryErrorCode.STORE_TIMEOUT: PolicyReasonCode.POLICY_STORE_TIMEOUT,
    PolicyRepositoryErrorCode.UNKNOWN_ROLE: PolicyReasonCode.UNKNOWN_ROLE,
    PolicyRepositoryErrorCode.UNKNOWN_PERMISSION: PolicyReasonCode.UNKNOWN_PERMISSION,
    PolicyRepositoryErrorCode.REGISTRY_VERSION_MISMATCH: PolicyReasonCode.REGISTRY_VERSION_MISMATCH,
    PolicyRepositoryErrorCode.TENANT_POLICY_VERSION_MISMATCH: PolicyReasonCode.TENANT_POLICY_VERSION_MISMATCH,
    PolicyRepositoryErrorCode.PROOF_MISMATCH: PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION: PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
    PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND: PolicyReasonCode.RESOURCE_NOT_FOUND,
}


class AuthorizationPolicyEngine:
    def __init__(self, *, resource_repository: ResourceSecurityRepositoryPort, synthetic_resolver: SyntheticSecurityScopeResolverPort, subject_codec: SubjectReferenceHashCodec) -> None:
        self._resources=resource_repository; self._synthetic=synthetic_resolver; self._subjects=subject_codec

    def evaluate(self, *, request: PolicyEvaluationRequest, effective_permissions: EffectivePermissionSet) -> PolicyEvaluationResult:
        action = COMPILED_SECURITY_ACTIONS.get(request.action.action_code)
        if action is None or action != request.action: return self._result(request, PolicyReasonCode.UNKNOWN_ACTION)
        if action.required_permission not in PERMISSION_REGISTRY: return self._result(request, PolicyReasonCode.UNKNOWN_PERMISSION)
        if request.expected_registry_version != PERMISSION_REGISTRY_VERSION or effective_permissions.permission_registry_version != PERMISSION_REGISTRY_VERSION: return self._result(request, PolicyReasonCode.REGISTRY_VERSION_MISMATCH)
        if request.identity.principal_kind not in action.allowed_principal_kinds: return self._result(request, PolicyReasonCode.PRINCIPAL_KIND_NOT_ALLOWED)
        if request.expected_tenant_policy_version != request.identity.tenant_policy_version or effective_permissions.tenant_policy_version != request.identity.tenant_policy_version: return self._result(request, PolicyReasonCode.TENANT_POLICY_VERSION_MISMATCH)
        if effective_permissions.principal_kind is not request.identity.principal_kind or effective_permissions.membership_id != request.identity.membership_id or effective_permissions.role_set_digest != request.identity.role_set_digest: return self._result(request, PolicyReasonCode.DATA_INTEGRITY_VIOLATION)
        if not self._strength_ok(request.identity.principal_kind, request.authentication_strength, action.minimum_authentication_strength): return self._result(request, PolicyReasonCode.INSUFFICIENT_AUTHENTICATION_STRENGTH)
        try: scope=self._resolve(request)
        except PolicyRepositoryError as exc: return self._result(request, _REPO_TO_REASON[exc.code])
        if request.resource_reference.expected_resource_version is not None and request.resource_reference.expected_resource_version != scope.resource_version: return self._result(request, PolicyReasonCode.RESOURCE_STATE_INVALID, scope)
        if scope.resource_type is not PolicyScopeType.SYSTEM and scope.tenant_key != request.identity.tenant_key: return self._result(request, PolicyReasonCode.TENANT_MISMATCH, scope)
        ownership=True
        if action.ownership_requirement is OwnershipRequirement.RESOURCE_OWNER_REQUIRED:
            if not scope.owner_subject: return self._result(request, PolicyReasonCode.RESOURCE_STATE_INVALID, scope, ownership=False)
            if scope.owner_subject != request.identity.provider_subject: return self._result(request, PolicyReasonCode.RESOURCE_OWNERSHIP_MISMATCH, scope, ownership=False)
        elif action.ownership_requirement is OwnershipRequirement.TENANT_OWNERSHIP_REQUIRED and scope.tenant_key != request.identity.tenant_key:
            return self._result(request, PolicyReasonCode.TENANT_MISMATCH, scope, ownership=False)
        predicate=self._predicate(request, scope)
        if predicate is None: return self._result(request, PolicyReasonCode.RESOURCE_STATE_INVALID, scope, ownership=ownership)
        if not predicate: return self._result(request, PolicyReasonCode.SUBJECT_PREDICATE_FAILED, scope, ownership=ownership, predicate=False)
        if action.required_permission not in effective_permissions.permission_codes: return self._result(request, PolicyReasonCode.PERMISSION_NOT_GRANTED, scope, ownership=ownership, predicate=True)
        return self._result(request, PolicyReasonCode.ALLOWED, scope, ownership=True, predicate=True)

    def _resolve(self, request: PolicyEvaluationRequest) -> ResourceSecurityScope:
        ref=request.resource_reference; now=request.evaluated_at
        if ref.scope_type is PolicyScopeType.SYSTEM: return self._synthetic.resolve_system_scope(current_time=now,correlation_id=request.correlation_id)
        if ref.scope_type is PolicyScopeType.TENANT: return self._synthetic.resolve_tenant_scope(tenant_key=str(ref.resource_id),identity_tenant_key=request.identity.tenant_key,expected_tenant_policy_version=request.expected_tenant_policy_version,current_time=now,correlation_id=request.correlation_id)
        if ref.scope_type is PolicyScopeType.COMPANY_PERIOD: return self._synthetic.resolve_company_period_scope(company_id=ref.company_id,financial_period_id=ref.period_id,expected_tenant_key=request.identity.tenant_key,current_time=now,correlation_id=request.correlation_id)  # type: ignore[arg-type]
        return self._resources.resolve_durable_scope(resource_type=ref.scope_type,resource_id=ref.resource_id,expected_tenant_key=request.identity.tenant_key,current_time=now,correlation_id=request.correlation_id)

    @staticmethod
    def _strength_ok(kind: IdentityKind, actual: PolicyAuthenticationStrength, minimum: PolicyAuthenticationStrength) -> bool:
        if kind is IdentityKind.SERVICE: return actual is PolicyAuthenticationStrength.SERVICE_CREDENTIAL
        if actual is PolicyAuthenticationStrength.SERVICE_CREDENTIAL: return False
        order={PolicyAuthenticationStrength.ANONYMOUS:0,PolicyAuthenticationStrength.PASSWORD:1,PolicyAuthenticationStrength.MFA:2,PolicyAuthenticationStrength.PHISHING_RESISTANT:3}
        return order.get(actual,-1)>=order.get(minimum,99)

    @staticmethod
    def _predicate(request: PolicyEvaluationRequest, scope: ResourceSecurityScope) -> bool | None:
        kind=request.action.subject_predicate_kind
        if kind is SubjectPredicateKind.NONE: return True if request.explicit_subject is None and request.target_subject is None else None
        if kind is SubjectPredicateKind.SELF: return None if request.target_subject is None or request.explicit_subject is not None else request.identity.provider_subject==request.target_subject
        if kind is SubjectPredicateKind.EXPLICIT_SUBJECT_MATCH: return None if request.explicit_subject is None or request.target_subject is not None else request.identity.provider_subject==request.explicit_subject
        if kind is SubjectPredicateKind.INITIATOR: return None if scope.initiator_subject is None or request.explicit_subject is not None or request.target_subject is not None else request.identity.provider_subject==scope.initiator_subject
        if kind is SubjectPredicateKind.SAME_TENANT: return None if scope.tenant_key is None or request.explicit_subject is not None or request.target_subject is not None else request.identity.tenant_key==scope.tenant_key
        return None

    def _result(self, request: PolicyEvaluationRequest, reason: PolicyReasonCode, scope: ResourceSecurityScope | None=None, *, ownership: bool | None=None, predicate: bool | None=None) -> PolicyEvaluationResult:
        meta=POLICY_REASON_METADATA[reason]; action=request.action
        requirement=PolicyAuditRequirement.SECURITY_CRITICAL if reason in {PolicyReasonCode.UNKNOWN_ACTION,PolicyReasonCode.UNKNOWN_PERMISSION,PolicyReasonCode.DATA_INTEGRITY_VIOLATION} else action.audit_requirement
        required=meta.outcome is PolicyOutcome.INDETERMINATE or requirement is PolicyAuditRequirement.SECURITY_CRITICAL or requirement is PolicyAuditRequirement.ALLOW_AND_DENY or (meta.outcome is PolicyOutcome.DENY and requirement is PolicyAuditRequirement.DENY_ONLY)
        hiding=meta.always_hide or (meta.outcome is not PolicyOutcome.ALLOW and action.existence_hiding_policy is not PolicyExistenceHiding.NONE)
        try:
            subject_ref=self._subjects.encode(issuer=request.identity.provider_issuer,tenant_key=request.identity.tenant_key,principal_kind=request.identity.principal_kind,provider_subject=request.identity.provider_subject)
            intent=AuditIntent(required,requirement,f"security.authorization.{meta.outcome.value.lower()}.{reason.value.lower()}",meta.outcome,reason,action.action_code,action.resource_type,request.correlation_id,subject_ref,request.identity.tenant_key,meta.severity)
            return PolicyEvaluationResult(meta.outcome,reason,action.action_code,request.identity.principal_id,request.identity.tenant_key,action.resource_type,(scope.resource_id if scope else request.resource_reference.resource_id),(action.required_permission if reason is PolicyReasonCode.ALLOWED else None),request.authentication_strength,request.identity.principal_kind,(True if reason is PolicyReasonCode.ALLOWED else predicate),(True if reason is PolicyReasonCode.ALLOWED else ownership),hiding,intent,PERMISSION_REGISTRY_VERSION,request.identity.tenant_policy_version,_utc(request.evaluated_at),request.correlation_id)
        except Exception as exc:
            if isinstance(exc, PolicyEvaluationConstructionError): raise
            raise PolicyEvaluationConstructionError(correlation_id=request.correlation_id,internal_cause=exc) from exc


class AuthorizationPolicyEnginePort(Protocol):
    def evaluate(self, *, request: PolicyEvaluationRequest, effective_permissions: EffectivePermissionSet) -> PolicyEvaluationResult: ...
