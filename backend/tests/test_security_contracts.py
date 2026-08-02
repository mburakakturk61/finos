from __future__ import annotations

import ast
import uuid
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.security.contracts import (
    IdentityKind,
    IdentityResolutionError,
    IdentityResolutionErrorCode,
    IssuerRegistry,
    JwtAlgorithm,
    OidcIssuerProfile,
    ProvisioningAuthority,
    ProvisioningCommand,
    ProvisioningOperationKind,
    SecurityEntityStatus,
    VerifiedLocalIdentity,
)
from app.security.policy import BUILT_IN_ROLE_PERMISSIONS, PERMISSION_REGISTRY


def _profile(**overrides):
    values = {
        "issuer": "https://issuer.example.test",
        "human_audiences": frozenset({"analysis-human"}),
        "service_audiences": frozenset({"analysis-service"}),
        "jwks_uri": "https://keys.example.test/jwks.json",
        "jwks_allowed_hosts": frozenset({"keys.example.test"}),
        "allowed_algorithms": frozenset({JwtAlgorithm.RS256}),
        "allowed_types": frozenset({"at+jwt"}),
    }
    values.update(overrides)
    return OidcIssuerProfile(**values)


def test_security_core_contracts_have_no_framework_or_orm_imports():
    root = Path(__file__).parents[1] / "app" / "security"
    forbidden = {"fastapi", "pydantic", "sqlalchemy"}
    core_files = ("contracts.py", "policy.py", "jwt.py", "jwks.py")
    for filename in core_files:
        path = root / filename
        tree = ast.parse(path.read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])
        }
        assert not (imports & forbidden), path


def test_permission_and_role_registries_are_closed_and_exhaustive():
    assert len(PERMISSION_REGISTRY) == 33
    assert set(BUILT_IN_ROLE_PERMISSIONS) == {
        "TENANT_ADMIN", "FINANCE_ADMIN", "FINANCE_ANALYST",
        "REPORT_VIEWER", "AUDITOR", "SERVICE_OPERATOR",
    }
    assert set(BUILT_IN_ROLE_PERMISSIONS["TENANT_ADMIN"]) == set(PERMISSION_REGISTRY)
    assert all(
        PERMISSION_REGISTRY[code].service_allowed
        for code in BUILT_IN_ROLE_PERMISSIONS["SERVICE_OPERATOR"]
    )
    assert "security.role.assign" not in BUILT_IN_ROLE_PERMISSIONS["FINANCE_ADMIN"]


def test_issuer_profile_rejects_dynamic_or_ambiguous_trust_configuration():
    with pytest.raises(ValueError):
        _profile(jwks_uri="http://keys.example.test/jwks.json")
    with pytest.raises(ValueError):
        _profile(jwks_allowed_hosts=frozenset({"other.example.test"}))
    with pytest.raises(ValueError):
        _profile(service_audiences=frozenset({"analysis-human"}))
    with pytest.raises(ValueError):
        IssuerRegistry((_profile(), _profile()))


def test_provisioning_command_requires_canonical_time_and_idempotency_key():
    authority = ProvisioningAuthority(
        "bootstrap-control-plane", "BOOTSTRAP", None, None,
        AuthenticationStrength.PHISHING_RESISTANT,
    )
    command = ProvisioningCommand(
        ProvisioningOperationKind.CREATE_TENANT, authority,
        "provisioning-key-0001", datetime.now(timezone.utc), "corr-1", "1.0.0",
        (("tenant_key", "tenant-one"),),
    )
    assert command.operation is ProvisioningOperationKind.CREATE_TENANT
    with pytest.raises(ValueError):
        ProvisioningCommand(
            command.operation, authority, "short", command.requested_at,
            command.correlation_id, command.payload_schema_version, command.payload,
        )


def test_identity_kind_is_closed():
    assert tuple(IdentityKind) == (IdentityKind.HUMAN, IdentityKind.SERVICE)


def _local_identity(**overrides):
    principal_id = overrides.pop("principal_id", uuid.uuid4())
    tenant_id = overrides.pop("tenant_id", uuid.uuid4())
    membership_id = overrides.pop("membership_id", uuid.uuid4())
    digest = overrides.pop("role_set_digest", "a" * 64)
    membership_version = overrides.pop("membership_version", 2)
    tenant_policy_version = overrides.pop("tenant_policy_version", 3)
    registry_version = overrides.pop("permission_registry_version", "1.0.0")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = {
        "principal_id": principal_id,
        "principal_kind": IdentityKind.HUMAN,
        "provider_issuer": "https://issuer.example.test",
        "provider_subject": "user:subject-1",
        "tenant_id": tenant_id,
        "tenant_key": "tenant-one",
        "membership_id": membership_id,
        "principal_status": SecurityEntityStatus.ACTIVE,
        "tenant_status": SecurityEntityStatus.ACTIVE,
        "binding_status": SecurityEntityStatus.ACTIVE,
        "membership_status": SecurityEntityStatus.ACTIVE,
        "authentication_context_subject": "user:subject-1",
        "authentication_context_tenant_key": "tenant-one",
        "roles": ("FINANCE_ANALYST",),
        "permission_resolution_reference": (
            f"policy-ref/v1:{tenant_policy_version}:{membership_id}:"
            f"{membership_version}:{registry_version}:{digest}"
        ),
        "role_set_digest": digest,
        "permission_registry_version": registry_version,
        "tenant_policy_version": tenant_policy_version,
        "tokens_valid_after": now,
        "membership_valid_from": now,
        "membership_valid_until": None,
        "principal_version": 1,
        "membership_version": membership_version,
        "resolved_at": now,
    }
    values.update(overrides)
    return VerifiedLocalIdentity(**values)


def test_identity_resolution_error_taxonomy_and_metadata_are_exhaustive_and_safe():
    assert len(IdentityResolutionErrorCode) == 19
    assert {item.value for item in IdentityResolutionErrorCode} == {
        "IDENTITY_NOT_FOUND", "TENANT_NOT_FOUND", "TENANT_MISMATCH",
        "PRINCIPAL_KIND_MISMATCH", "TENANT_INACTIVE", "PRINCIPAL_INACTIVE",
        "SUBJECT_BINDING_INACTIVE", "MEMBERSHIP_NOT_FOUND", "MEMBERSHIP_INACTIVE",
        "MEMBERSHIP_NOT_YET_VALID", "MEMBERSHIP_EXPIRED",
        "SERVICE_SAFE_ROLE_NOT_FOUND", "SERVICE_ROLE_PERMISSION_INVALID",
        "TOKEN_REVOKED_BY_PRINCIPAL", "TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY",
        "NONCANONICAL_IDENTITY_INPUT", "DATA_INTEGRITY_VIOLATION",
        "IDENTITY_STORE_UNAVAILABLE", "IDENTITY_STORE_TIMEOUT",
    }
    for code in IdentityResolutionErrorCode:
        error = IdentityResolutionError(code, correlation_id="corr-safe-0000001")
        assert error.safe_message == str(error)
        assert error.audit_event and error.metric_name
        assert error.retryable is (code in {
            IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE,
            IdentityResolutionErrorCode.IDENTITY_STORE_TIMEOUT,
        })
        assert "http" not in vars(error)


def test_identity_resolution_error_is_immutable_deterministic_and_redacts_raw_cause():
    error = IdentityResolutionError(
        IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE,
        correlation_id="corr-safe-0000001",
    )
    assert error == IdentityResolutionError(
        IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE,
        correlation_id="corr-safe-0000001",
    )
    assert hash(error) == hash(IdentityResolutionError(
        IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE,
        correlation_id="corr-safe-0000001",
    ))
    with pytest.raises(FrozenInstanceError):
        error.safe_message = "changed"
    with pytest.raises(TypeError):
        IdentityResolutionError("IDENTITY_NOT_FOUND")
    raw = "postgresql://secret@db/private SQL SELECT bearer-token"
    try:
        raise error from RuntimeError(raw)
    except IdentityResolutionError as raised:
        assert raw not in str(raised)
        assert raw not in repr(raised)
        assert raised.args == ("Identity service is unavailable.",)


def test_verified_local_identity_is_frozen_and_accepts_exact_contract():
    identity = _local_identity()
    assert identity.roles == ("FINANCE_ANALYST",)
    with pytest.raises(FrozenInstanceError):
        identity.roles = ("AUDITOR",)


@pytest.mark.parametrize("overrides", [
    {"principal_id": "not-a-uuid"},
    {"principal_kind": "HUMAN"},
    {"provider_issuer": "https://ISSUER.example.test"},
    {"principal_status": SecurityEntityStatus.SUSPENDED},
    {"principal_version": 0},
    {"roles": ()},
    {"roles": ("REPORT_VIEWER", "AUDITOR")},
    {"roles": ("AUDITOR", "AUDITOR")},
    {"role_set_digest": "BAD"},
    {"permission_registry_version": "2.0.0"},
    {"tokens_valid_after": datetime(2026, 1, 1)},
    {"tokens_valid_after": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3)))},
])
def test_verified_local_identity_rejects_invalid_dto_local_state(overrides):
    with pytest.raises(ValueError):
        _local_identity(**overrides)


def test_verified_local_identity_rejects_malformed_or_cross_field_proof():
    identity = _local_identity()
    with pytest.raises(ValueError):
        replace(identity, permission_resolution_reference="policy-ref/v1:broken")
    with pytest.raises(ValueError):
        replace(identity, tenant_policy_version=identity.tenant_policy_version + 1)
    with pytest.raises(ValueError):
        replace(identity, membership_version=identity.membership_version + 1)
