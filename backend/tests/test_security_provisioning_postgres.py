from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.models.security import SecurityPrincipal, SecurityProvisioningOperation, SecurityTenant
from app.security.contracts import (
    ProvisioningAuthority,
    ProvisioningCommand,
    ProvisioningErrorCode,
    ProvisioningOperationKind,
)
from app.security.provisioning import SqlAlchemyIdentityProvisioningService


class _Audit:
    def __init__(self, fail=False): self.fail = fail; self.events = []
    def record_required_event(self, event):
        if self.fail: raise RuntimeError("audit unavailable")
        self.events.append(event)
        return "receipt-" + uuid.uuid4().hex
    def readiness_check(self, deadline): return not self.fail


def _authority(kind="PLATFORM", tenant_key=None, principal_id=None):
    return ProvisioningAuthority(
        f"{kind.lower()}-authority", kind, tenant_key, principal_id,
        AuthenticationStrength.PHISHING_RESISTANT,
    )


def _command(operation, authority, payload, key=None, reason=None):
    return ProvisioningCommand(
        operation, authority, key or "provisioning-" + uuid.uuid4().hex,
        datetime.now(timezone.utc), "corr-" + uuid.uuid4().hex, "1.0.0",
        tuple(payload.items()), reason_code=reason,
    )


def _tenant_command(authority, tenant_key, key=None, subject=None):
    return _command(
        ProvisioningOperationKind.CREATE_TENANT, authority,
        {"tenant_key": tenant_key, "issuer": "https://issuer.example.test", "subject": subject or "user:" + uuid.uuid4().hex},
        key,
    )


def test_bootstrap_and_platform_tenant_provisioning_are_separate_and_atomic_postgres():
    audit = _Audit()
    service = SqlAlchemyIdentityProvisioningService(SessionLocal, audit)
    with SessionLocal() as session:
        has_tenant = session.scalar(select(func.count()).select_from(SecurityTenant)) > 0
    authority = _authority("PLATFORM" if has_tenant else "BOOTSTRAP")
    tenant_key = "tenant-" + uuid.uuid4().hex[:16]
    outcome = service.create_tenant(_tenant_command(authority, tenant_key))
    assert outcome.success
    with SessionLocal() as session:
        tenant = session.scalar(select(SecurityTenant).where(SecurityTenant.tenant_key == tenant_key))
        assert tenant is not None
        assert tenant.status == "ACTIVE"
    wrong = service.create_tenant(_tenant_command(_authority("TENANT_ADMIN", tenant_key), "tenant-" + uuid.uuid4().hex[:16]))
    assert not wrong.success


def test_provisioning_idempotency_same_payload_and_conflict_postgres():
    service = SqlAlchemyIdentityProvisioningService(SessionLocal, _Audit())
    key = "provisioning-" + uuid.uuid4().hex
    command = _tenant_command(_authority("PLATFORM"), "tenant-" + uuid.uuid4().hex[:16], key)
    first = service.create_tenant(command)
    second = service.create_tenant(command)
    assert first.success and second.success and second.idempotent_replay
    conflict = service.create_tenant(_tenant_command(
        _authority("PLATFORM"), "tenant-" + uuid.uuid4().hex[:16], key,
    ))
    assert not conflict.success
    assert conflict.error_code is ProvisioningErrorCode.IDEMPOTENCY_CONFLICT


def test_required_audit_failure_prevents_transaction_postgres():
    service = SqlAlchemyIdentityProvisioningService(SessionLocal, _Audit(fail=True))
    tenant_key = "tenant-" + uuid.uuid4().hex[:16]
    outcome = service.create_tenant(_tenant_command(_authority("PLATFORM"), tenant_key))
    assert outcome.error_code is ProvisioningErrorCode.AUDIT_FAILED
    with SessionLocal() as session:
        assert session.scalar(select(SecurityTenant.id).where(SecurityTenant.tenant_key == tenant_key)) is None


def test_duplicate_subject_binding_rolls_back_principal_postgres():
    service = SqlAlchemyIdentityProvisioningService(SessionLocal, _Audit())
    subject = "service:" + uuid.uuid4().hex
    payload = {
        "kind": "SERVICE", "issuer": "https://issuer.example.test",
        "subject": subject, "service_client_id": "client-" + uuid.uuid4().hex,
    }
    first = service.create_principal(_command(ProvisioningOperationKind.CREATE_PRINCIPAL, _authority("PLATFORM"), payload))
    assert first.success
    with SessionLocal() as session:
        count_before = session.scalar(select(func.count()).select_from(SecurityPrincipal))
    payload["service_client_id"] = "client-" + uuid.uuid4().hex
    second = service.create_principal(_command(ProvisioningOperationKind.CREATE_PRINCIPAL, _authority("PLATFORM"), payload))
    assert second.error_code is ProvisioningErrorCode.PERSISTENCE_CONFLICT
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(SecurityPrincipal)) == count_before


def test_concurrent_same_provisioning_key_has_one_operation_postgres():
    service = SqlAlchemyIdentityProvisioningService(SessionLocal, _Audit())
    key = "provisioning-" + uuid.uuid4().hex
    command = _tenant_command(_authority("PLATFORM"), "tenant-" + uuid.uuid4().hex[:16], key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _index: service.create_tenant(command), range(2)))
    assert all(outcome.success for outcome in outcomes)
    assert sum(outcome.idempotent_replay for outcome in outcomes) == 1
    with SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(SecurityProvisioningOperation).where(
            SecurityProvisioningOperation.authority_id == command.authority.authority_id,
            SecurityProvisioningOperation.idempotency_key == key,
        ))
        assert count == 1
