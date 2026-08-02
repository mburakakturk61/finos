from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, TimeoutError as SqlAlchemyTimeoutError

from app.db.session import SessionLocal
from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.models.security import (
    SecurityMembership,
    SecurityMembershipRole,
    SecurityPermission,
    SecurityPrincipal,
    SecurityRole,
    SecurityRolePermission,
    SecuritySubjectBinding,
    SecurityTenant,
)
from app.security.contracts import (
    IdentityKind,
    IdentityResolutionError,
    IdentityResolutionErrorCode,
    ProvisioningAuthority,
    ProvisioningCommand,
    ProvisioningOperationKind,
)
from app.security.identity import SqlAlchemySecurityIdentityRepository
from app.security.provisioning import SqlAlchemyIdentityProvisioningService


ISSUER = "https://issuer.example.test"
CORRELATION_ID = "corr-identity-000001"
REQUEST_ID = "request-identity-000001"
UTC = timezone.utc


@dataclass(frozen=True)
class _Seed:
    tenant_id: uuid.UUID
    tenant_key: str
    principal_id: uuid.UUID
    binding_id: uuid.UUID
    membership_id: uuid.UUID | None
    subject: str
    client_id: str | None
    now: datetime
    boundary: datetime


def _seed_identity(
    *,
    kind: IdentityKind = IdentityKind.HUMAN,
    role_permissions: tuple[tuple[str, tuple[str, ...]], ...] | None = None,
    with_membership: bool = True,
    boundary: datetime | None = None,
    now: datetime | None = None,
) -> _Seed:
    now = now or datetime(2026, 2, 1, 12, 0, 30, 123456, tzinfo=UTC)
    boundary = boundary or now - timedelta(seconds=30)
    suffix = uuid.uuid4().hex
    tenant = SecurityTenant(
        id=uuid.uuid4(), tenant_key="identity-" + suffix[:16], status="ACTIVE",
        policy_version=1, version=1,
    )
    principal = SecurityPrincipal(
        id=uuid.uuid4(), kind=kind.value, status="ACTIVE",
        tokens_valid_after=boundary, version=1,
    )
    subject = ("service:" if kind is IdentityKind.SERVICE else "user:") + suffix
    client_id = "client-" + suffix if kind is IdentityKind.SERVICE else None
    binding = SecuritySubjectBinding(
        id=uuid.uuid4(), principal_id=principal.id, issuer=ISSUER,
        subject=subject, service_client_id=client_id, status="ACTIVE",
    )
    membership = SecurityMembership(
        id=uuid.uuid4(), tenant_id=tenant.id, principal_id=principal.id,
        status="ACTIVE", valid_from=boundary, version=1,
    ) if with_membership else None
    if role_permissions is None:
        role_permissions = ((
            "CUSTOM_SERVICE" if kind is IdentityKind.SERVICE else "FINANCE_ANALYST",
            ("analysis.start",) if kind is IdentityKind.SERVICE else ("company.create",),
        ),)

    with SessionLocal() as session, session.begin():
        session.add_all((tenant, principal))
        session.flush()
        session.add(binding)
        if membership is not None:
            session.add(membership)
        session.flush()
        if membership is not None:
            for role_code, permission_codes in role_permissions:
                role = SecurityRole(
                    id=uuid.uuid4(), tenant_id=tenant.id, role_code=role_code,
                    built_in=role_code == "SERVICE_OPERATOR", status="ACTIVE", version=1,
                )
                session.add(role)
                session.flush()
                session.add(SecurityMembershipRole(
                    membership_id=membership.id, role_id=role.id,
                ))
                session.add_all(SecurityRolePermission(
                    role_id=role.id, permission_code=permission_code,
                ) for permission_code in permission_codes)
    return _Seed(
        tenant.id, tenant.tenant_key, principal.id, binding.id,
        membership.id if membership else None, subject, client_id, now, boundary,
    )


def _resolve(seed: _Seed, **overrides):
    values = {
        "issuer": ISSUER,
        "subject": seed.subject,
        "tenant_key": seed.tenant_key,
        "token_issued_at": seed.boundary,
        "expected_principal_kind": (
            IdentityKind.SERVICE if seed.client_id else IdentityKind.HUMAN
        ),
        "expected_service_client_id": seed.client_id,
        "correlation_id": CORRELATION_ID,
        "request_id": REQUEST_ID,
        "now": seed.now,
    }
    values.update(overrides)
    return SqlAlchemySecurityIdentityRepository(SessionLocal).resolve_principal_and_membership(**values)


def _assert_error(seed: _Seed, code: IdentityResolutionErrorCode, **overrides):
    with pytest.raises(IdentityResolutionError) as caught:
        _resolve(seed, **overrides)
    assert caught.value.code is code
    return caught.value


def test_valid_human_resolution_has_deterministic_canonical_proof_postgres():
    seed = _seed_identity()
    first = _resolve(seed)
    second = _resolve(seed)
    assert first.principal_kind is IdentityKind.HUMAN
    assert first.roles == ("FINANCE_ANALYST",)
    assert first.role_set_digest == second.role_set_digest
    assert first.permission_resolution_reference == second.permission_resolution_reference
    assert first.membership_id == seed.membership_id


@pytest.mark.parametrize("role_code", ["SERVICE_OPERATOR", "CUSTOM_SERVICE"])
def test_valid_service_resolution_supports_builtin_or_custom_service_safe_role_postgres(role_code):
    seed = _seed_identity(
        kind=IdentityKind.SERVICE,
        role_permissions=((role_code, ("analysis.start", "analysis.read")),),
    )
    identity = _resolve(seed)
    assert identity.principal_kind is IdentityKind.SERVICE
    assert identity.roles == (role_code,)


def test_service_client_binding_mismatch_is_rejected_postgres():
    seed = _seed_identity(kind=IdentityKind.SERVICE)
    _assert_error(
        seed,
        IdentityResolutionErrorCode.PRINCIPAL_KIND_MISMATCH,
        expected_service_client_id="client-wrong-binding",
    )


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(seconds=1)])
def test_token_at_or_after_effective_boundary_is_accepted_postgres(delta):
    boundary = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
    seed = _seed_identity(boundary=boundary, now=boundary + timedelta(seconds=5))
    identity = _resolve(seed, token_issued_at=boundary + delta)
    assert identity.tokens_valid_after == boundary


@pytest.mark.parametrize("microsecond", [1, 999999])
def test_microsecond_database_boundary_is_not_truncated_postgres(microsecond):
    boundary = datetime(2026, 2, 1, 12, 0, 0, microsecond, tzinfo=UTC)
    seed = _seed_identity(boundary=boundary, now=boundary + timedelta(seconds=2))
    _assert_error(
        seed,
        IdentityResolutionErrorCode.TOKEN_REVOKED_BY_PRINCIPAL,
        token_issued_at=datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC),
    )


def test_postgres_microsecond_round_trip_and_timezone_input_normalization():
    boundary = datetime(2026, 2, 1, 12, 0, 0, 654321, tzinfo=UTC)
    seed = _seed_identity(boundary=boundary, now=boundary + timedelta(seconds=2))
    plus_three = boundary.astimezone(timezone(timedelta(hours=3)))
    identity = _resolve(seed, token_issued_at=plus_three)
    assert identity.tokens_valid_after == boundary
    assert identity.tokens_valid_after.microsecond == 654321


def test_exact_membership_validity_boundaries_are_inclusive_postgres():
    seed = _seed_identity()
    valid_until = seed.now + timedelta(seconds=10)
    with SessionLocal() as session, session.begin():
        membership = session.get(SecurityMembership, seed.membership_id)
        membership.valid_until = valid_until
    assert _resolve(seed, now=seed.boundary).membership_valid_from == seed.boundary
    assert _resolve(seed, now=valid_until).membership_valid_until == valid_until


@pytest.mark.parametrize(("override", "expected"), [
    ({"tenant_key": "missing-tenant"}, IdentityResolutionErrorCode.TENANT_NOT_FOUND),
    ({"subject": "missing:subject"}, IdentityResolutionErrorCode.IDENTITY_NOT_FOUND),
    ({"expected_principal_kind": IdentityKind.SERVICE, "expected_service_client_id": "client-other"}, IdentityResolutionErrorCode.PRINCIPAL_KIND_MISMATCH),
    ({"tenant_key": "Not-Canonical"}, IdentityResolutionErrorCode.NONCANONICAL_IDENTITY_INPUT),
    ({"issuer": "https://ISSUER.example.test"}, IdentityResolutionErrorCode.NONCANONICAL_IDENTITY_INPUT),
    ({"token_issued_at": datetime(2026, 1, 1)}, IdentityResolutionErrorCode.NONCANONICAL_IDENTITY_INPUT),
])
def test_input_and_lookup_failures_are_closed_postgres(override, expected):
    _assert_error(_seed_identity(), expected, **override)


@pytest.mark.parametrize(("target", "status", "expected"), [
    ("tenant", "SUSPENDED", IdentityResolutionErrorCode.TENANT_INACTIVE),
    ("principal", "DISABLED", IdentityResolutionErrorCode.PRINCIPAL_INACTIVE),
    ("membership", "SUSPENDED", IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE),
])
def test_inactive_state_precedence_is_fail_closed_postgres(target, status, expected):
    seed = _seed_identity()
    model, row_id = {
        "tenant": (SecurityTenant, seed.tenant_id),
        "principal": (SecurityPrincipal, seed.principal_id),
        "membership": (SecurityMembership, seed.membership_id),
    }[target]
    with SessionLocal() as session, session.begin():
        session.get(model, row_id).status = status
    _assert_error(seed, expected, token_issued_at=seed.boundary - timedelta(days=1))


def test_inactive_binding_precedes_missing_membership_postgres():
    seed = _seed_identity(with_membership=False)
    with SessionLocal() as session, session.begin():
        binding = session.get(SecuritySubjectBinding, seed.binding_id)
        binding.status = "REVOKED"
        binding.revoked_at = seed.now
        binding.revocation_reason = "TEST"
    _assert_error(seed, IdentityResolutionErrorCode.SUBJECT_BINDING_INACTIVE)


def test_missing_membership_and_cross_tenant_mismatch_are_distinct_postgres():
    missing = _seed_identity(with_membership=False)
    _assert_error(missing, IdentityResolutionErrorCode.MEMBERSHIP_NOT_FOUND)
    seed = _seed_identity()
    other = _seed_identity()
    _assert_error(seed, IdentityResolutionErrorCode.TENANT_MISMATCH, tenant_key=other.tenant_key)


@pytest.mark.parametrize(("valid_from_delta", "valid_until_delta", "expected"), [
    (timedelta(hours=1), None, IdentityResolutionErrorCode.MEMBERSHIP_NOT_YET_VALID),
    (timedelta(hours=-2), timedelta(hours=-1), IdentityResolutionErrorCode.MEMBERSHIP_EXPIRED),
])
def test_membership_validity_precedes_token_revocation_postgres(valid_from_delta, valid_until_delta, expected):
    seed = _seed_identity()
    with SessionLocal() as session, session.begin():
        membership = session.get(SecurityMembership, seed.membership_id)
        membership.valid_from = seed.now + valid_from_delta
        membership.valid_until = seed.now + valid_until_delta if valid_until_delta else None
    _assert_error(seed, expected, token_issued_at=seed.boundary - timedelta(days=1))


def test_effective_maximum_boundary_selects_membership_code_postgres():
    seed = _seed_identity()
    membership_boundary = seed.boundary + timedelta(seconds=1, microseconds=1)
    with SessionLocal() as session, session.begin():
        session.get(SecurityMembership, seed.membership_id).valid_from = membership_boundary
    _assert_error(
        seed,
        IdentityResolutionErrorCode.TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY,
        token_issued_at=seed.boundary + timedelta(seconds=1),
    )


def test_service_without_role_is_rejected_postgres():
    seed = _seed_identity(kind=IdentityKind.SERVICE, role_permissions=())
    _assert_error(seed, IdentityResolutionErrorCode.SERVICE_SAFE_ROLE_NOT_FOUND)


def test_human_without_active_role_is_data_integrity_violation_postgres():
    seed = _seed_identity(role_permissions=())
    _assert_error(seed, IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION)


@pytest.mark.parametrize("permission_codes", [
    ("company.create",),
    ("analysis.start", "company.create"),
])
def test_service_human_only_or_mixed_permission_role_is_rejected_postgres(permission_codes):
    seed = _seed_identity(
        kind=IdentityKind.SERVICE,
        role_permissions=(("CUSTOM_SERVICE", permission_codes),),
    )
    _assert_error(seed, IdentityResolutionErrorCode.SERVICE_ROLE_PERMISSION_INVALID)


def test_human_service_only_role_is_data_integrity_violation_postgres():
    seed = _seed_identity(role_permissions=(("SERVICE_OPERATOR", ("analysis.start",)),))
    _assert_error(seed, IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION)


def test_stale_permission_registry_is_data_integrity_violation_postgres():
    seed = _seed_identity()
    code = "test.stale." + uuid.uuid4().hex
    with SessionLocal() as session, session.begin():
        role_id = session.scalar(select(SecurityMembershipRole.role_id).where(
            SecurityMembershipRole.membership_id == seed.membership_id
        ))
        session.add(SecurityPermission(
            permission_code=code, resource_type="TEST", action="READ", scope_type="TENANT",
            minimum_authentication_strength="BASIC", human_allowed=True,
            service_allowed=False, existence_hiding_policy="DENY_403",
            permission_registry_version="0.9.0",
        ))
        session.flush()
        session.add(SecurityRolePermission(role_id=role_id, permission_code=code))
    _assert_error(seed, IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION)


def test_role_change_is_visible_without_positive_cache_and_changes_proof_postgres():
    seed = _seed_identity()
    before = _resolve(seed)
    with SessionLocal() as session, session.begin():
        tenant = session.get(SecurityTenant, seed.tenant_id)
        membership = session.get(SecurityMembership, seed.membership_id)
        role_id = session.scalar(select(SecurityMembershipRole.role_id).where(
            SecurityMembershipRole.membership_id == seed.membership_id
        ))
        role = session.get(SecurityRole, role_id)
        role.version += 1
        membership.version += 1
        tenant.policy_version += 1
        session.add(SecurityRolePermission(role_id=role_id, permission_code="company.list"))
    after = _resolve(seed)
    assert after.role_set_digest != before.role_set_digest
    assert after.permission_resolution_reference != before.permission_resolution_reference
    assert after.membership_version == before.membership_version + 1
    assert after.tenant_policy_version == before.tenant_policy_version + 1


class _Audit:
    def record_required_event(self, _event):
        return "receipt-identity-step9"

    def readiness_check(self, _deadline):
        return True


def _provisioning_command(seed: _Seed, operation: ProvisioningOperationKind):
    authority_kind = "PLATFORM" if operation is ProvisioningOperationKind.REVOKE_PRINCIPAL else "TENANT_ADMIN"
    authority = ProvisioningAuthority(
        authority_id="identity-step9-authority",
        authority_kind=authority_kind,
        tenant_key=seed.tenant_key if authority_kind == "TENANT_ADMIN" else None,
        principal_id=seed.principal_id,
        authentication_strength=AuthenticationStrength.PHISHING_RESISTANT,
    )
    target_key = "principal_id" if operation is ProvisioningOperationKind.REVOKE_PRINCIPAL else "membership_id"
    target_value = seed.principal_id if target_key == "principal_id" else seed.membership_id
    return ProvisioningCommand(
        operation=operation,
        authority=authority,
        idempotency_key="step9-revoke-" + uuid.uuid4().hex,
        requested_at=datetime.now(UTC),
        correlation_id=CORRELATION_ID,
        payload_schema_version="1.0.0",
        payload=((target_key, str(target_value)),),
        effective_at=seed.now,
        reason_code="STEP9_TEST",
    )


@pytest.mark.parametrize(("operation", "expected"), [
    (ProvisioningOperationKind.REVOKE_PRINCIPAL, IdentityResolutionErrorCode.PRINCIPAL_INACTIVE),
    (ProvisioningOperationKind.REVOKE_MEMBERSHIP, IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE),
])
def test_provisioning_revoke_commit_is_visible_on_next_resolution_postgres(operation, expected):
    seed = _seed_identity()
    assert _resolve(seed).principal_id == seed.principal_id
    provisioning = SqlAlchemyIdentityProvisioningService(SessionLocal, _Audit())
    outcome = (
        provisioning.revoke_principal(_provisioning_command(seed, operation))
        if operation is ProvisioningOperationKind.REVOKE_PRINCIPAL
        else provisioning.revoke_membership(_provisioning_command(seed, operation))
    )
    assert outcome.success
    _assert_error(seed, expected)


@pytest.mark.parametrize(("factory_error", "expected"), [
    (SqlAlchemyTimeoutError("pool secret"), IdentityResolutionErrorCode.IDENTITY_STORE_TIMEOUT),
    (OperationalError("SELECT secret", {}, RuntimeError("dsn secret")), IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE),
])
def test_database_failures_are_redacted_and_fail_closed(factory_error, expected):
    seed = _seed_identity()

    def failing_factory():
        raise factory_error

    repository = SqlAlchemySecurityIdentityRepository(failing_factory)
    with pytest.raises(IdentityResolutionError) as caught:
        repository.resolve_principal_and_membership(
            issuer=ISSUER, subject=seed.subject, tenant_key=seed.tenant_key,
            token_issued_at=seed.boundary, expected_principal_kind=IdentityKind.HUMAN,
            expected_service_client_id=None, correlation_id=CORRELATION_ID,
            request_id=REQUEST_ID, now=seed.now,
        )
    assert caught.value.code is expected
    rendered = str(caught.value) + repr(caught.value)
    assert "secret" not in rendered
    assert "SELECT" not in rendered


def test_repository_rejects_invalid_timeout_configuration():
    with pytest.raises(ValueError):
        SqlAlchemySecurityIdentityRepository(SessionLocal, statement_timeout_seconds=0)
    with pytest.raises(ValueError):
        SqlAlchemySecurityIdentityRepository(SessionLocal, statement_timeout_seconds=3.1)
