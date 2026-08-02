from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.analysis_application.contracts import (
    ApplicationAuditContextDTO,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
)
from app.analysis_application.ports import SecurityAuditReceiptDTO
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
from app.security.authorization_adapter import (
    AuthorizationCheckpoint,
    LocalAuthorizationPolicyClient,
    TrustedAuthorizationContext,
)
from app.security.authorization_policy import (
    AuthorizationPolicyEngine,
    PolicyAuthenticationStrength,
    PolicyScopeType,
    ResourceSecurityReference,
    SubjectReferenceHashCodec,
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
ISSUER = "https://issuer.adapter-postgres.example"
CODEC = SubjectReferenceHashCodec({"k1": bytes(range(32))}, active_key_version="k1")


@dataclass
class Seed:
    tenant_id: uuid.UUID
    tenant_key: str
    principal_id: uuid.UUID
    membership_id: uuid.UUID
    role_id: uuid.UUID
    subject: str
    company_id: uuid.UUID
    period_id: uuid.UUID
    membership_version: int = 1
    tenant_policy_version: int = 1
    expected_resource_version: str | None = None
    now: datetime = NOW


def _seed() -> Seed:
    suffix = uuid.uuid4().hex
    tenant = SecurityTenant(
        id=uuid.uuid4(), tenant_key="adapter-" + suffix[:16],
        status="ACTIVE", policy_version=1, version=1,
    )
    principal = SecurityPrincipal(
        id=uuid.uuid4(), kind="HUMAN", status="ACTIVE",
        tokens_valid_after=NOW - timedelta(minutes=2), version=1,
    )
    membership = SecurityMembership(
        id=uuid.uuid4(), tenant_id=tenant.id, principal_id=principal.id,
        status="ACTIVE", valid_from=NOW - timedelta(days=1), version=1,
    )
    role = SecurityRole(
        id=uuid.uuid4(), tenant_id=tenant.id,
        role_code="ADAPTER_" + suffix[:12].upper(),
        built_in=False, status="ACTIVE", version=1,
    )
    subject = "user:" + suffix
    binding = SecuritySubjectBinding(
        id=uuid.uuid4(), principal_id=principal.id, issuer=ISSUER,
        subject=subject, service_client_id=None, status="ACTIVE",
    )
    company = Company(
        id=uuid.uuid4(), tenant_id=tenant.id,
        legal_name="Adapter Company " + suffix,
        tax_number=suffix, currency="TRY",
    )
    period = FinancialPeriod(
        id=uuid.uuid4(), company_id=company.id, year=2026,
        period_type=PeriodType.YEAR_END, period_number=1,
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        months_covered=12, is_year_end=True, status=PeriodStatus.ACTIVE,
    )
    with SessionLocal() as session, session.begin():
        session.add_all((tenant, principal))
        session.flush()
        session.add_all((membership, role, binding, company))
        session.flush()
        session.add_all((
            SecurityMembershipRole(membership_id=membership.id, role_id=role.id),
            SecurityRolePermission(role_id=role.id, permission_code="analysis.start"),
            period,
        ))
    return Seed(
        tenant.id, tenant.tenant_key, principal.id, membership.id,
        role.id, subject, company.id, period.id,
    )


class ContextProvider:
    is_fake = False
    def __init__(self, seed: Seed): self.seed, self.calls = seed, []
    def resolve_context(self, *, checkpoint, application_scope, audit_context):
        self.calls.append(checkpoint)
        reference = ResourceSecurityReference(
            PolicyScopeType.COMPANY_PERIOD,
            f"cp1:{self.seed.company_id}:{self.seed.period_id}",
            self.seed.tenant_key, self.seed.company_id, self.seed.period_id,
            self.seed.expected_resource_version,
            "corr-adapter-postgres", self.seed.now,
        )
        return TrustedAuthorizationContext(
            ISSUER, self.seed.subject, self.seed.tenant_key,
            NOW - timedelta(minutes=1), self.seed.now + timedelta(minutes=5),
            IdentityKind.HUMAN, None, PolicyAuthenticationStrength.MFA,
            "corr-adapter-postgres", "request-adapter-postgres",
            f"authz:v1:H:{self.seed.membership_id}:{self.seed.membership_version}:{self.seed.tenant_policy_version}",
            checkpoint, reference, self.seed.now,
        )


class Audit:
    def __init__(self): self.events = []
    def record_required_event(self, event):
        self.events.append(event)
        return SecurityAuditReceiptDTO("receipt-postgres", event.event_type, event.occurred_at, "d" * 64)


class Clock:
    def __init__(self, seed): self.seed = seed
    def now_audit_time(self): return self.seed.now
    def resolve_business_time(self, value): return value or self.seed.now


class Observe:
    def increment_metric(self, name, value, tags): pass
    def emit_best_effort_event(self, event): pass
    def record_timing(self, name, duration_ms, tags): pass


def _client(seed):
    resources = SqlAlchemyResourceSecurityRepository(SessionLocal)
    synthetic = SqlAlchemySyntheticSecurityScopeResolver(SessionLocal)
    return LocalAuthorizationPolicyClient(
        context_provider=ContextProvider(seed),
        identity_repository=SqlAlchemySecurityIdentityRepository(SessionLocal),
        policy_repository=SqlAlchemyAuthorizationPolicyRepository(SessionLocal),
        policy_engine=AuthorizationPolicyEngine(
            resource_repository=resources, synthetic_resolver=synthetic,
            subject_codec=CODEC,
        ),
        security_audit=Audit(), observability=Observe(), clock=Clock(seed),
        subject_reference_hash_codec=CODEC,
    ), synthetic


def _scope(seed):
    return ApplicationScopeDTO(
        seed.company_id, seed.period_id, seed.tenant_key,
        ApplicationOperationKind.START, ApplicationOriginalOperation.START,
    )


def _actor(seed):
    subject_ref = CODEC.encode(
        issuer=ISSUER, tenant_key=seed.tenant_key,
        principal_kind=IdentityKind.HUMAN, provider_subject=seed.subject,
    )
    return ApplicationAuditContextDTO(subject_ref, "test", "postgres", "authorization")


def test_postgres_initial_authorization_and_fresh_revalidation_allow():
    seed = _seed()
    client, _ = _client(seed)
    assert client.authorize_start(_scope(seed), _actor(seed)).granted
    assert client.revalidate_start(_scope(seed), _actor(seed)).granted


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("principal", "AUTHZ_REVALIDATION_REVOKED_PRINCIPAL"),
        ("membership", "AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP"),
        ("token", "AUTHZ_REVALIDATION_REVOKED_TOKEN"),
        ("permission", "AUTHZ_REVALIDATION_REVOKED_POLICY"),
        ("tenant_policy", "AUTHZ_REVALIDATION_REVOKED_POLICY"),
    ),
)
def test_postgres_revalidation_observes_authoritative_revocation(mutation, expected):
    seed = _seed()
    client, _ = _client(seed)
    assert client.authorize_start(_scope(seed), _actor(seed)).granted
    with SessionLocal() as session, session.begin():
        if mutation == "principal":
            session.get(SecurityPrincipal, seed.principal_id).status = "DISABLED"
        elif mutation == "membership":
            session.get(SecurityMembership, seed.membership_id).status = "SUSPENDED"
        elif mutation == "token":
            session.get(SecurityPrincipal, seed.principal_id).tokens_valid_after = NOW
        elif mutation == "permission":
            session.execute(delete(SecurityRolePermission).where(
                SecurityRolePermission.role_id == seed.role_id,
            ))
            session.add(SecurityRolePermission(
                role_id=seed.role_id, permission_code="company.read",
            ))
        else:
            tenant = session.get(SecurityTenant, seed.tenant_id)
            tenant.policy_version = 2
    result = client.revalidate_start(_scope(seed), _actor(seed))
    assert (result.granted, result.revoked, result.decision_code) == (False, True, expected)


def test_postgres_resource_version_change_is_fail_closed_revalidation():
    seed = _seed()
    client, synthetic = _client(seed)
    initial_scope = synthetic.resolve_company_period_scope(
        company_id=seed.company_id, financial_period_id=seed.period_id,
        expected_tenant_key=seed.tenant_key, current_time=seed.now,
        correlation_id="corr-adapter-postgres",
    )
    seed.expected_resource_version = initial_scope.resource_version
    assert client.authorize_start(_scope(seed), _actor(seed)).granted
    seed.now = NOW + timedelta(seconds=1)
    with SessionLocal() as session, session.begin():
        company = session.get(Company, seed.company_id)
        company.updated_at = seed.now
    result = client.revalidate_start(_scope(seed), _actor(seed))
    assert (result.granted, result.revoked, result.decision_code) == (
        False, True, "AUTHZ_REVALIDATION_REVOKED_RESOURCE",
    )
