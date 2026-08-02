"""Milestone 5.0E authoritative tenant, identity and authorization state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index,
    Integer, JSON, String, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class SecurityTenant(Base):
    __tablename__ = "security_tenants"
    __table_args__ = (
        CheckConstraint(
            "length(tenant_key) BETWEEN 3 AND 63 "
            "AND tenant_key = lower(tenant_key) "
            "AND tenant_key = trim(tenant_key)",
            name="tenant_key_canonical",
        ),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED','DISABLED')", name="status"),
        CheckConstraint("policy_version > 0 AND version > 0", name="versions_positive"),
        Index("ix_security_tenants_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    bootstrap_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SecurityPrincipal(Base):
    __tablename__ = "security_principals"
    __table_args__ = (
        CheckConstraint("kind IN ('HUMAN','SERVICE')", name="kind"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED','DISABLED')", name="status"),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_security_principals_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    tokens_valid_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_principals.id", ondelete="RESTRICT"))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SecuritySubjectBinding(Base):
    __tablename__ = "security_subject_bindings"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_security_subject_bindings_issuer_subject"),
        CheckConstraint("status IN ('ACTIVE','REVOKED')", name="status"),
        CheckConstraint(
            "(status='ACTIVE' AND revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(status='REVOKED' AND revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_fields",
        ),
        Index("ix_security_subject_bindings_principal_status", "principal_id", "status"),
        Index(
            "uq_security_subject_bindings_issuer_client",
            "issuer", "service_client_id", unique=True,
            postgresql_where=text("service_client_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_principals.id", ondelete="RESTRICT"), nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    service_client_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_principals.id", ondelete="RESTRICT"))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityMembership(Base):
    __tablename__ = "security_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "principal_id", name="uq_security_memberships_tenant_principal"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED','REVOKED')", name="status"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity"),
        CheckConstraint(
            "(status<>'REVOKED' AND revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(status='REVOKED' AND revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_fields",
        ),
        Index("ix_security_memberships_tenant_status", "tenant_id", "status"),
        Index("ix_security_memberships_principal_status", "principal_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_tenants.id", ondelete="RESTRICT"), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_principals.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_principals.id", ondelete="RESTRICT"))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SecurityPermission(Base):
    __tablename__ = "security_permissions"
    __table_args__ = (
        CheckConstraint("minimum_authentication_strength IN ('BASIC','STRONG','PHISHING_RESISTANT')", name="strength"),
        CheckConstraint("human_allowed OR service_allowed", name="principal_kind_allowed"),
    )

    permission_code: Mapped[str] = mapped_column(String(96), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(48), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(48), nullable=False)
    minimum_authentication_strength: Mapped[str] = mapped_column(String(32), nullable=False)
    human_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    service_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    existence_hiding_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    permission_registry_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityRole(Base):
    __tablename__ = "security_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role_code", name="uq_security_roles_tenant_code"),
        CheckConstraint("status IN ('ACTIVE','DISABLED')", name="status"),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_security_roles_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_tenants.id", ondelete="RESTRICT"), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SecurityRolePermission(Base):
    __tablename__ = "security_role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_roles.id", ondelete="RESTRICT"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(96), ForeignKey("security_permissions.permission_code", ondelete="RESTRICT"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityMembershipRole(Base):
    __tablename__ = "security_membership_roles"

    membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_memberships.id", ondelete="RESTRICT"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("security_roles.id", ondelete="RESTRICT"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityProvisioningOperation(Base):
    __tablename__ = "security_provisioning_operations"
    __table_args__ = (
        UniqueConstraint("authority_id", "idempotency_key", name="uq_security_provisioning_authority_key"),
        CheckConstraint("status IN ('COMPLETED','REJECTED')", name="status"),
        CheckConstraint("length(payload_digest)=64", name="payload_digest_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    authority_id: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    audit_receipt_id: Mapped[str] = mapped_column(String(255), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityResourceBindingQuarantine(Base):
    __tablename__ = "security_resource_binding_quarantine"
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_security_quarantine_resource"),
        CheckConstraint("status IN ('OPEN','RESOLVED')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
