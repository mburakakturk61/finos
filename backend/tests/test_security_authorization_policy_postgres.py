from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.enums import PeriodStatus, PeriodType
from app.models.financial_period import FinancialPeriod
from app.models.security import (
    SecurityMembership,
    SecurityMembershipRole,
    SecurityPrincipal,
    SecurityRole,
    SecurityRolePermission,
    SecuritySubjectBinding,
    SecurityTenant,
)
from app.security.authorization_policy import (
    PolicyMaterializationRequest,
    PolicyRepositoryError,
    PolicyRepositoryErrorCode,
    PolicyScopeType,
)
from app.security.contracts import IdentityKind
from app.security.identity import SqlAlchemySecurityIdentityRepository
from app.security.policy_repositories import (
    SqlAlchemyAuthorizationPolicyRepository,
    SqlAlchemyResourceSecurityRepository,
    SqlAlchemySyntheticSecurityScopeResolver,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 2, 12, 0, 0, 123456, tzinfo=UTC)
ISSUER = "https://issuer.policy.example.test"
CORRELATION_ID = "corr-policy-postgres-0001"


@dataclass(frozen=True)
class _PolicySeed:
    tenant_id: uuid.UUID
    tenant_key: str
    principal_id: uuid.UUID
    membership_id: uuid.UUID
    subject: str


def _seed_policy_identity(
    *,
    kind: IdentityKind = IdentityKind.HUMAN,
    permission_code: str = "company.read",
) -> _PolicySeed:
    suffix = uuid.uuid4().hex
    tenant = SecurityTenant(
        id=uuid.uuid4(),
        tenant_key="policy-" + suffix[:16],
        status="ACTIVE",
        policy_version=1,
        version=1,
    )
    principal = SecurityPrincipal(
        id=uuid.uuid4(),
        kind=kind.value,
        status="ACTIVE",
        tokens_valid_after=NOW - timedelta(minutes=1),
        version=1,
    )
    subject = ("service:" if kind is IdentityKind.SERVICE else "user:") + suffix
    membership = SecurityMembership(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        principal_id=principal.id,
        status="ACTIVE",
        valid_from=NOW - timedelta(minutes=1),
        version=1,
    )
    role = SecurityRole(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        role_code="CUSTOM_POLICY_" + suffix[:12].upper(),
        built_in=False,
        status="ACTIVE",
        version=1,
    )
    binding = SecuritySubjectBinding(
        id=uuid.uuid4(),
        principal_id=principal.id,
        issuer=ISSUER,
        subject=subject,
        service_client_id=("client-" + suffix if kind is IdentityKind.SERVICE else None),
        status="ACTIVE",
    )
    with SessionLocal() as session, session.begin():
        session.add_all((tenant, principal))
        session.flush()
        session.add_all((membership, role, binding))
        session.flush()
        session.add_all((
            SecurityMembershipRole(membership_id=membership.id, role_id=role.id),
            SecurityRolePermission(role_id=role.id, permission_code=permission_code),
        ))
    return _PolicySeed(tenant.id, tenant.tenant_key, principal.id, membership.id, subject)


def _identity(seed: _PolicySeed, *, kind: IdentityKind = IdentityKind.HUMAN):
    return SqlAlchemySecurityIdentityRepository(SessionLocal).resolve_principal_and_membership(
        issuer=ISSUER,
        subject=seed.subject,
        tenant_key=seed.tenant_key,
        token_issued_at=NOW,
        expected_principal_kind=kind,
        expected_service_client_id=(
            "client-" + seed.subject.removeprefix("service:")
            if kind is IdentityKind.SERVICE
            else None
        ),
        correlation_id=CORRELATION_ID,
        request_id="request-policy-postgres-0001",
        now=NOW,
    )


def _materialization(identity):
    return PolicyMaterializationRequest(
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
        current_time=NOW,
        correlation_id=CORRELATION_ID,
    )


def _seed_company_period(tenant: SecurityTenant, *, year: int):
    suffix = uuid.uuid4().hex
    company = Company(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        legal_name="Policy Company " + suffix,
        tax_number=suffix,
        currency="TRY",
    )
    period = FinancialPeriod(
        id=uuid.uuid4(),
        company_id=company.id,
        year=year,
        period_type=PeriodType.YEAR_END,
        period_number=1,
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        months_covered=12,
        is_year_end=True,
        status=PeriodStatus.ACTIVE,
    )
    return company, period


def test_authoritative_policy_materialization_revalidates_identity_proof_postgres():
    seed = _seed_policy_identity()
    identity = _identity(seed)
    result = SqlAlchemyAuthorizationPolicyRepository(SessionLocal).resolve_effective_permissions(
        _materialization(identity)
    )
    assert result.permission_codes == ("company.read",)
    assert result.role_codes == identity.roles
    assert result.role_set_digest == identity.role_set_digest


@pytest.mark.parametrize("field", ["role_set_digest", "permission_resolution_reference"])
def test_policy_materialization_rejects_forged_proof_postgres(field):
    seed = _seed_policy_identity()
    request = _materialization(_identity(seed))
    values = dict(request.__dict__)
    values[field] = "0" * 64 if field == "role_set_digest" else "policy-ref/v1:forged"
    with pytest.raises(PolicyRepositoryError) as caught:
        SqlAlchemyAuthorizationPolicyRepository(SessionLocal).resolve_effective_permissions(
            PolicyMaterializationRequest(**values)
        )
    assert caught.value.code is PolicyRepositoryErrorCode.PROOF_MISMATCH


def test_service_permission_safety_is_rechecked_from_postgres():
    seed = _seed_policy_identity(kind=IdentityKind.SERVICE, permission_code="analysis.start")
    identity = _identity(seed, kind=IdentityKind.SERVICE)
    with SessionLocal() as session, session.begin():
        role_id = session.scalar(
            select(SecurityRole.id).where(SecurityRole.role_code == identity.roles[0])
        )
        session.execute(delete(SecurityRolePermission).where(SecurityRolePermission.role_id == role_id))
        session.add(SecurityRolePermission(role_id=role_id, permission_code="company.create"))
    with pytest.raises(PolicyRepositoryError) as caught:
        SqlAlchemyAuthorizationPolicyRepository(SessionLocal).resolve_effective_permissions(
            _materialization(identity)
        )
    assert caught.value.code is PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION


def test_company_resource_model_a_hides_unknown_and_cross_tenant_identically_postgres():
    tenant_a = SecurityTenant(
        id=uuid.uuid4(), tenant_key="model-a-" + uuid.uuid4().hex[:12],
        status="ACTIVE", policy_version=1, version=1,
    )
    tenant_b = SecurityTenant(
        id=uuid.uuid4(), tenant_key="model-b-" + uuid.uuid4().hex[:12],
        status="ACTIVE", policy_version=1, version=1,
    )
    company_a, period_a = _seed_company_period(tenant_a, year=2024)
    company_b, period_b = _seed_company_period(tenant_b, year=2025)
    with SessionLocal() as session, session.begin():
        session.add_all((tenant_a, tenant_b))
        session.flush()
        session.add_all((company_a, company_b))
        session.flush()
        session.add_all((period_a, period_b))
    repository = SqlAlchemyResourceSecurityRepository(SessionLocal)
    visible = repository.resolve_durable_scope(
        resource_type=PolicyScopeType.COMPANY,
        resource_id=company_a.id,
        expected_tenant_key=tenant_a.tenant_key,
        current_time=NOW,
        correlation_id=CORRELATION_ID,
    )
    assert visible.company_id == company_a.id
    for resource_id in (company_b.id, uuid.uuid4()):
        with pytest.raises(PolicyRepositoryError) as caught:
            repository.resolve_durable_scope(
                resource_type=PolicyScopeType.COMPANY,
                resource_id=resource_id,
                expected_tenant_key=tenant_a.tenant_key,
                current_time=NOW,
                correlation_id=CORRELATION_ID,
            )
        assert caught.value.code is PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND


def test_synthetic_company_period_rejects_wrong_same_tenant_pair_postgres():
    tenant = SecurityTenant(
        id=uuid.uuid4(), tenant_key="pair-" + uuid.uuid4().hex[:16],
        status="ACTIVE", policy_version=1, version=1,
    )
    company_a, period_a = _seed_company_period(tenant, year=2024)
    company_b, period_b = _seed_company_period(tenant, year=2025)
    with SessionLocal() as session, session.begin():
        session.add(tenant)
        session.flush()
        session.add_all((company_a, company_b))
        session.flush()
        session.add_all((period_a, period_b))
    resolver = SqlAlchemySyntheticSecurityScopeResolver(SessionLocal)
    with pytest.raises(PolicyRepositoryError) as caught:
        resolver.resolve_company_period_scope(
            company_id=company_a.id,
            financial_period_id=period_b.id,
            expected_tenant_key=tenant.tenant_key,
            current_time=NOW,
            correlation_id=CORRELATION_ID,
        )
    assert caught.value.code is PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND


def test_synthetic_tenant_and_company_period_are_authoritative_postgres():
    tenant = SecurityTenant(
        id=uuid.uuid4(), tenant_key="synthetic-" + uuid.uuid4().hex[:12],
        status="ACTIVE", policy_version=7, version=1,
    )
    company, period = _seed_company_period(tenant, year=2026)
    with SessionLocal() as session, session.begin():
        session.add(tenant)
        session.flush()
        session.add(company)
        session.flush()
        session.add(period)
    resolver = SqlAlchemySyntheticSecurityScopeResolver(SessionLocal)
    tenant_scope = resolver.resolve_tenant_scope(
        tenant_key=tenant.tenant_key,
        identity_tenant_key=tenant.tenant_key,
        expected_tenant_policy_version=7,
        current_time=NOW,
        correlation_id=CORRELATION_ID,
    )
    pair_scope = resolver.resolve_company_period_scope(
        company_id=company.id,
        financial_period_id=period.id,
        expected_tenant_key=tenant.tenant_key,
        current_time=NOW,
        correlation_id=CORRELATION_ID,
    )
    assert tenant_scope.tenant_key == pair_scope.tenant_key == tenant.tenant_key
    assert (pair_scope.company_id, pair_scope.period_id) == (company.id, period.id)
