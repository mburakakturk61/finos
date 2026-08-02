"""Transactional trusted provisioning adapter for authoritative security state."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.security import (
    SecurityMembership,
    SecurityMembershipRole,
    SecurityPrincipal,
    SecurityProvisioningOperation,
    SecurityRole,
    SecurityRolePermission,
    SecuritySubjectBinding,
    SecurityTenant,
)
from app.security.contracts import (
    AuthenticationAuditEvent,
    AuthenticationSecurityAuditPort,
    IdentityKind,
    ProvisioningCommand,
    ProvisioningErrorCode,
    ProvisioningOperationKind,
    ProvisioningOutcome,
    ProvisioningStatus,
    TENANT_KEY_PATTERN,
)
from app.security.policy import BUILT_IN_ROLE_PERMISSIONS


class ProvisioningClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SqlAlchemyIdentityProvisioningService:
    def __init__(self, session_factory, audit: AuthenticationSecurityAuditPort, clock=None) -> None:
        self._sessions = session_factory
        self._audit = audit
        self._clock = clock or ProvisioningClock()

    def create_tenant(self, command: ProvisioningCommand) -> ProvisioningOutcome:
        return self._execute(command, self._create_tenant)

    def create_principal(self, command: ProvisioningCommand) -> ProvisioningOutcome:
        return self._execute(command, self._create_principal)

    def create_membership(self, command: ProvisioningCommand) -> ProvisioningOutcome:
        return self._execute(command, self._create_membership)

    def assign_role(self, command: ProvisioningCommand) -> ProvisioningOutcome:
        return self._execute(command, self._assign_role)

    def revoke_membership(self, command: ProvisioningCommand) -> ProvisioningOutcome:
        return self._execute(command, self._revoke_membership)

    def revoke_principal(self, command: ProvisioningCommand) -> ProvisioningOutcome:
        return self._execute(command, self._revoke_principal)

    def rotate_subject_binding(self, command: ProvisioningCommand) -> ProvisioningOutcome:
        return self._execute(command, self._rotate_subject_binding)

    def get_provisioning_status(self, authority_id: str, idempotency_key: str) -> ProvisioningOutcome | None:
        with self._sessions() as session:
            row = session.scalar(select(SecurityProvisioningOperation).where(
                SecurityProvisioningOperation.authority_id == authority_id,
                SecurityProvisioningOperation.idempotency_key == idempotency_key,
            ))
            return self._outcome(row, replay=True) if row is not None else None

    def _execute(self, command: ProvisioningCommand, mutation) -> ProvisioningOutcome:
        if command.operation is not self._operation_for(mutation):
            return self._failure(ProvisioningErrorCode.INVALID_COMMAND)
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("Provisioning clock must be timezone-aware.")
        if command.effective_at is not None and (
            command.effective_at.tzinfo is None
            or command.effective_at.utcoffset() is None
            or command.effective_at > now + timedelta(seconds=60)
        ):
            return self._failure(ProvisioningErrorCode.INVALID_COMMAND)
        payload_digest = self._digest(command)
        try:
            receipt_id = self._audit.record_required_event(AuthenticationAuditEvent(
                "PROVISIONING_MUTATION_AUTHORIZED", now, command.correlation_id,
                command.authority.authority_id,
                (("operation", command.operation.value), ("payload_digest", payload_digest)),
            ))
        except Exception:
            return self._failure(ProvisioningErrorCode.AUDIT_FAILED)
        try:
            with self._sessions() as session, session.begin():
                existing = session.scalar(select(SecurityProvisioningOperation).where(
                    SecurityProvisioningOperation.authority_id == command.authority.authority_id,
                    SecurityProvisioningOperation.idempotency_key == command.idempotency_key,
                ))
                if existing is not None:
                    if existing.payload_digest != payload_digest:
                        return self._failure(ProvisioningErrorCode.IDEMPOTENCY_CONFLICT)
                    return self._outcome(existing, replay=True)
                result = mutation(session, command, now)
                row = SecurityProvisioningOperation(
                    id=uuid.uuid4(), authority_id=command.authority.authority_id,
                    idempotency_key=command.idempotency_key, operation_kind=command.operation.value,
                    payload_digest=payload_digest, payload_schema_version=command.payload_schema_version,
                    status="COMPLETED", audit_receipt_id=str(receipt_id), result_json=result,
                )
                session.add(row)
                session.flush()
                outcome = self._outcome(row, replay=False)
            try:
                self._audit.record_required_event(AuthenticationAuditEvent(
                    "PROVISIONING_MUTATION_COMMITTED", now, command.correlation_id,
                    command.authority.authority_id, (("operation_id", str(outcome.operation_id)),),
                ))
            except Exception:
                pass
            return outcome
        except IntegrityError:
            replay = self.get_provisioning_status(command.authority.authority_id, command.idempotency_key)
            if replay is not None:
                with self._sessions() as session:
                    row = session.scalar(select(SecurityProvisioningOperation).where(
                        SecurityProvisioningOperation.authority_id == command.authority.authority_id,
                        SecurityProvisioningOperation.idempotency_key == command.idempotency_key,
                    ))
                    if row is not None and row.payload_digest == payload_digest:
                        return self._outcome(row, replay=True)
            return self._failure(ProvisioningErrorCode.PERSISTENCE_CONFLICT)
        except (SQLAlchemyError, ValueError, KeyError):
            return self._failure(ProvisioningErrorCode.PERSISTENCE_CONFLICT)

    @staticmethod
    def _operation_for(mutation) -> ProvisioningOperationKind:
        return {
            "_create_tenant": ProvisioningOperationKind.CREATE_TENANT,
            "_create_principal": ProvisioningOperationKind.CREATE_PRINCIPAL,
            "_create_membership": ProvisioningOperationKind.CREATE_MEMBERSHIP,
            "_assign_role": ProvisioningOperationKind.ASSIGN_ROLE,
            "_revoke_membership": ProvisioningOperationKind.REVOKE_MEMBERSHIP,
            "_revoke_principal": ProvisioningOperationKind.REVOKE_PRINCIPAL,
            "_rotate_subject_binding": ProvisioningOperationKind.ROTATE_SUBJECT_BINDING,
        }[mutation.__name__]

    @staticmethod
    def _payload(command: ProvisioningCommand) -> dict[str, str]:
        result = dict(command.payload)
        if len(result) != len(command.payload):
            raise ValueError("Duplicate provisioning payload key.")
        return result

    @classmethod
    def _digest(cls, command: ProvisioningCommand) -> str:
        value = {
            "operation": command.operation.value,
            "schema": command.payload_schema_version,
            "payload": sorted(command.payload),
            "effective_at": command.effective_at.isoformat() if command.effective_at else None,
            "reason": command.reason_code,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _require_authority(command: ProvisioningCommand, *kinds: str) -> None:
        if command.authority.authority_kind not in kinds:
            raise ValueError("Provisioning authority is not permitted.")

    def _create_tenant(self, session, command: ProvisioningCommand, now: datetime) -> dict[str, str]:
        existing_tenants = session.scalar(select(SecurityTenant.id).limit(1))
        self._require_authority(command, "BOOTSTRAP" if existing_tenants is None else "PLATFORM")
        payload = self._payload(command)
        tenant_key = payload["tenant_key"]
        if not TENANT_KEY_PATTERN.fullmatch(tenant_key):
            raise ValueError("Tenant key is invalid.")
        tenant = SecurityTenant(
            id=uuid.uuid4(), tenant_key=tenant_key, status="ACTIVE", policy_version=1,
            version=1, bootstrap_closed_at=now if existing_tenants is None else None,
        )
        principal = SecurityPrincipal(
            id=uuid.uuid4(), kind="HUMAN", status="ACTIVE", tokens_valid_after=now,
            version=1,
        )
        binding = SecuritySubjectBinding(
            id=uuid.uuid4(), principal_id=principal.id, issuer=payload["issuer"],
            subject=payload["subject"], status="ACTIVE",
        )
        membership = SecurityMembership(
            id=uuid.uuid4(), tenant_id=tenant.id, principal_id=principal.id,
            status="ACTIVE", valid_from=now, version=1,
        )
        # PostgreSQL trigger'ları subject/membership FK sahiplerini statement
        # anında okur. Parent'ları önce kesinleştirerek flush sırasını ORM
        # mapper kayıt sırasına bırakmayız.
        session.add_all((tenant, principal))
        session.flush()
        session.add_all((binding, membership))
        session.flush()
        roles: dict[str, SecurityRole] = {}
        for role_code, permissions in BUILT_IN_ROLE_PERMISSIONS.items():
            role = SecurityRole(
                id=uuid.uuid4(), tenant_id=tenant.id, role_code=role_code,
                built_in=True, status="ACTIVE", version=1,
            )
            session.add(role)
            session.flush()
            roles[role_code] = role
            session.add_all(SecurityRolePermission(role_id=role.id, permission_code=code) for code in permissions)
        session.flush()
        session.add(SecurityMembershipRole(membership_id=membership.id, role_id=roles["TENANT_ADMIN"].id))
        session.flush()
        return {
            "tenant_id": str(tenant.id), "tenant_key": tenant.tenant_key,
            "principal_id": str(principal.id), "membership_id": str(membership.id),
        }

    def _create_principal(self, session, command: ProvisioningCommand, now: datetime) -> dict[str, str]:
        self._require_authority(command, "PLATFORM")
        payload = self._payload(command)
        kind = IdentityKind(payload["kind"])
        client_id = payload.get("service_client_id")
        if (kind is IdentityKind.SERVICE) != (client_id is not None):
            raise ValueError("Service client binding is invalid.")
        principal = SecurityPrincipal(
            id=uuid.uuid4(), kind=kind.value, status="ACTIVE", tokens_valid_after=now,
            version=1,
        )
        binding = SecuritySubjectBinding(
            id=uuid.uuid4(), principal_id=principal.id, issuer=payload["issuer"],
            subject=payload["subject"], service_client_id=client_id, status="ACTIVE",
        )
        session.add_all((principal, binding))
        session.flush()
        return {"principal_id": str(principal.id), "binding_id": str(binding.id)}

    def _create_membership(self, session, command: ProvisioningCommand, now: datetime) -> dict[str, str]:
        self._require_authority(command, "TENANT_ADMIN")
        payload = self._payload(command)
        if command.authority.tenant_key != payload["tenant_key"]:
            raise ValueError("Cross-tenant membership creation.")
        tenant = session.scalar(select(SecurityTenant).where(SecurityTenant.tenant_key == payload["tenant_key"]))
        principal = session.get(SecurityPrincipal, uuid.UUID(payload["principal_id"]))
        if tenant is None or principal is None or principal.status != "ACTIVE":
            raise ValueError("Membership target is invalid.")
        membership = SecurityMembership(
            id=uuid.uuid4(), tenant_id=tenant.id, principal_id=principal.id,
            status="ACTIVE", valid_from=now, version=1,
        )
        session.add(membership)
        session.flush()
        return {"membership_id": str(membership.id), "tenant_id": str(tenant.id)}

    def _assign_role(self, session, command: ProvisioningCommand, _now: datetime) -> dict[str, str]:
        self._require_authority(command, "TENANT_ADMIN")
        payload = self._payload(command)
        membership = session.get(SecurityMembership, uuid.UUID(payload["membership_id"]))
        if membership is None:
            raise ValueError("Membership not found.")
        tenant = session.get(SecurityTenant, membership.tenant_id)
        principal = session.get(SecurityPrincipal, membership.principal_id)
        role = session.scalar(select(SecurityRole).where(
            SecurityRole.tenant_id == membership.tenant_id,
            SecurityRole.role_code == payload["role_code"], SecurityRole.status == "ACTIVE",
        ))
        if tenant is None or command.authority.tenant_key != tenant.tenant_key or role is None or principal is None:
            raise ValueError("Cross-tenant role assignment.")
        if (principal.kind == "SERVICE") != (role.role_code == "SERVICE_OPERATOR"):
            raise ValueError("Principal kind cannot receive the requested built-in role.")
        session.add(SecurityMembershipRole(membership_id=membership.id, role_id=role.id))
        return {"membership_id": str(membership.id), "role_id": str(role.id)}

    def _revoke_membership(self, session, command: ProvisioningCommand, now: datetime) -> dict[str, str]:
        self._require_authority(command, "TENANT_ADMIN")
        payload = self._payload(command)
        membership = session.get(SecurityMembership, uuid.UUID(payload["membership_id"]), with_for_update=True)
        tenant = session.get(SecurityTenant, membership.tenant_id) if membership else None
        if membership is None or tenant is None or tenant.tenant_key != command.authority.tenant_key:
            raise ValueError("Cross-tenant membership revocation.")
        membership.status = "REVOKED"
        membership.revoked_at = command.effective_at or now
        membership.revoked_by_principal_id = command.authority.principal_id
        membership.revocation_reason = command.reason_code or "ADMIN_REVOKED"
        membership.version += 1
        return {"membership_id": str(membership.id)}

    def _revoke_principal(self, session, command: ProvisioningCommand, now: datetime) -> dict[str, str]:
        self._require_authority(command, "PLATFORM")
        payload = self._payload(command)
        principal = session.get(SecurityPrincipal, uuid.UUID(payload["principal_id"]), with_for_update=True)
        if principal is None:
            raise ValueError("Principal not found.")
        effective = command.effective_at or now
        principal.status = "DISABLED"
        principal.tokens_valid_after = effective
        principal.revoked_at = effective
        principal.revocation_reason = command.reason_code or "PLATFORM_REVOKED"
        principal.version += 1
        return {"principal_id": str(principal.id)}

    def _rotate_subject_binding(self, session, command: ProvisioningCommand, now: datetime) -> dict[str, str]:
        self._require_authority(command, "PLATFORM")
        payload = self._payload(command)
        old = session.get(SecuritySubjectBinding, uuid.UUID(payload["binding_id"]), with_for_update=True)
        if old is None or old.status != "ACTIVE":
            raise ValueError("Subject binding not found.")
        old.status = "REVOKED"
        old.revoked_at = now
        old.revocation_reason = command.reason_code or "SUBJECT_ROTATED"
        new = SecuritySubjectBinding(
            id=uuid.uuid4(), principal_id=old.principal_id, issuer=payload["issuer"],
            subject=payload["subject"], service_client_id=payload.get("service_client_id"),
            status="ACTIVE",
        )
        session.add(new)
        session.flush()
        return {"principal_id": str(old.principal_id), "binding_id": str(new.id)}

    @staticmethod
    def _failure(code: ProvisioningErrorCode) -> ProvisioningOutcome:
        return ProvisioningOutcome(False, None, ProvisioningStatus.REJECTED, code)

    @staticmethod
    def _outcome(row: SecurityProvisioningOperation, *, replay: bool) -> ProvisioningOutcome:
        return ProvisioningOutcome(True, row.id, ProvisioningStatus.COMPLETED, None, replay)
