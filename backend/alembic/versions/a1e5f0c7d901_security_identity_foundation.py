"""Milestone 5.0E E1 security identity foundation.

Revision ID: a1e5f0c7d901
Revises: 8b6e4d2c1a90
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.security.policy import PERMISSION_REGISTRY


revision = "a1e5f0c7d901"
down_revision = "8b6e4d2c1a90"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "security_tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_key", sa.String(63), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("bootstrap_closed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("tenant_key", name="uq_security_tenants_tenant_key"),
        sa.CheckConstraint("tenant_key ~ '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$'", name="ck_security_tenants_tenant_key_canonical"),
        sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','DISABLED')", name="ck_security_tenants_status"),
        sa.CheckConstraint("policy_version > 0 AND version > 0", name="ck_security_tenants_versions_positive"),
    )
    op.create_index("ix_security_tenants_status", "security_tenants", ["status"])

    op.create_table(
        "security_principals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_principal_id", sa.Uuid(), sa.ForeignKey("security_principals.id", ondelete="RESTRICT")),
        sa.Column("revocation_reason", sa.String(64)),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('HUMAN','SERVICE')", name="ck_security_principals_kind"),
        sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','DISABLED')", name="ck_security_principals_status"),
        sa.CheckConstraint("version > 0", name="ck_security_principals_version_positive"),
    )
    op.create_index("ix_security_principals_status", "security_principals", ["status"])

    op.create_table(
        "security_subject_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("principal_id", sa.Uuid(), sa.ForeignKey("security_principals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("service_client_id", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_principal_id", sa.Uuid(), sa.ForeignKey("security_principals.id", ondelete="RESTRICT")),
        sa.Column("revocation_reason", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("issuer", "subject", name="uq_security_subject_bindings_issuer_subject"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_security_subject_bindings_status"),
        sa.CheckConstraint(
            "(status='ACTIVE' AND revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(status='REVOKED' AND revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="ck_security_subject_bindings_revocation_fields",
        ),
    )
    op.create_index("ix_security_subject_bindings_principal_status", "security_subject_bindings", ["principal_id", "status"])
    op.create_index(
        "uq_security_subject_bindings_issuer_client", "security_subject_bindings",
        ["issuer", "service_client_id"], unique=True,
        postgresql_where=sa.text("service_client_id IS NOT NULL"),
    )

    op.create_table(
        "security_memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("security_tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("principal_id", sa.Uuid(), sa.ForeignKey("security_principals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_principal_id", sa.Uuid(), sa.ForeignKey("security_principals.id", ondelete="RESTRICT")),
        sa.Column("revocation_reason", sa.String(64)),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "principal_id", name="uq_security_memberships_tenant_principal"),
        sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','REVOKED')", name="ck_security_memberships_status"),
        sa.CheckConstraint("version > 0", name="ck_security_memberships_version_positive"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="ck_security_memberships_validity"),
        sa.CheckConstraint(
            "(status<>'REVOKED' AND revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(status='REVOKED' AND revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="ck_security_memberships_revocation_fields",
        ),
    )
    op.create_index("ix_security_memberships_tenant_status", "security_memberships", ["tenant_id", "status"])
    op.create_index("ix_security_memberships_principal_status", "security_memberships", ["principal_id", "status"])

    op.create_table(
        "security_permissions",
        sa.Column("permission_code", sa.String(96), primary_key=True),
        sa.Column("resource_type", sa.String(48), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("scope_type", sa.String(48), nullable=False),
        sa.Column("minimum_authentication_strength", sa.String(32), nullable=False),
        sa.Column("human_allowed", sa.Boolean(), nullable=False),
        sa.Column("service_allowed", sa.Boolean(), nullable=False),
        sa.Column("existence_hiding_policy", sa.String(32), nullable=False),
        sa.Column("permission_registry_version", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("minimum_authentication_strength IN ('BASIC','STRONG','PHISHING_RESISTANT')", name="ck_security_permissions_strength"),
        sa.CheckConstraint("human_allowed OR service_allowed", name="ck_security_permissions_principal_kind_allowed"),
    )

    op.create_table(
        "security_roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("security_tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("role_code", sa.String(64), nullable=False),
        sa.Column("built_in", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "role_code", name="uq_security_roles_tenant_code"),
        sa.CheckConstraint("status IN ('ACTIVE','DISABLED')", name="ck_security_roles_status"),
        sa.CheckConstraint("version > 0", name="ck_security_roles_version_positive"),
    )
    op.create_index("ix_security_roles_tenant_status", "security_roles", ["tenant_id", "status"])

    op.create_table(
        "security_role_permissions",
        sa.Column("role_id", sa.Uuid(), sa.ForeignKey("security_roles.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("permission_code", sa.String(96), sa.ForeignKey("security_permissions.permission_code", ondelete="RESTRICT"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_security_role_permissions_permission", "security_role_permissions", ["permission_code"])

    op.create_table(
        "security_membership_roles",
        sa.Column("membership_id", sa.Uuid(), sa.ForeignKey("security_memberships.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("role_id", sa.Uuid(), sa.ForeignKey("security_roles.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_security_membership_roles_role", "security_membership_roles", ["role_id"])

    op.create_table(
        "security_provisioning_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("authority_id", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("operation_kind", sa.String(48), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("payload_schema_version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("audit_receipt_id", sa.String(255), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("authority_id", "idempotency_key", name="uq_security_provisioning_authority_key"),
        sa.CheckConstraint("status IN ('COMPLETED','REJECTED')", name="ck_security_provisioning_operations_status"),
        sa.CheckConstraint("length(payload_digest)=64", name="ck_security_provisioning_operations_payload_digest_length"),
    )

    op.create_table(
        "security_resource_binding_quarantine",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resource_type", sa.String(48), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_security_quarantine_resource"),
        sa.CheckConstraint("status IN ('OPEN','RESOLVED')", name="ck_security_resource_binding_quarantine_status"),
    )

    op.add_column("companies", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_companies_tenant_id_security_tenants", "companies", "security_tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_companies_tenant_id", "companies", ["tenant_id"])
    op.add_column("bulk_upload_batches", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_bulk_upload_batches_tenant_id_security_tenants", "bulk_upload_batches", "security_tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_bulk_upload_batches_tenant_id", "bulk_upload_batches", ["tenant_id"])

    rows = [
        {
            "permission_code": item.permission_code,
            "resource_type": item.resource_type,
            "action": item.action,
            "scope_type": item.scope_type,
            "minimum_authentication_strength": item.minimum_authentication_strength.value,
            "human_allowed": item.human_allowed,
            "service_allowed": item.service_allowed,
            "existence_hiding_policy": item.existence_hiding_policy.value,
            "permission_registry_version": item.permission_registry_version,
        }
        for item in PERMISSION_REGISTRY.values()
    ]
    op.bulk_insert(sa.table("security_permissions", *[
        sa.column("permission_code", sa.String), sa.column("resource_type", sa.String),
        sa.column("action", sa.String), sa.column("scope_type", sa.String),
        sa.column("minimum_authentication_strength", sa.String), sa.column("human_allowed", sa.Boolean),
        sa.column("service_allowed", sa.Boolean), sa.column("existence_hiding_policy", sa.String),
        sa.column("permission_registry_version", sa.String),
    ]), rows)

    op.execute("""
        CREATE FUNCTION enforce_security_subject_kind() RETURNS trigger AS $$
        DECLARE principal_kind text;
        BEGIN
            SELECT kind INTO principal_kind FROM security_principals WHERE id=NEW.principal_id;
            IF principal_kind IS NULL OR
               (principal_kind='SERVICE') IS DISTINCT FROM (NEW.service_client_id IS NOT NULL) THEN
                RAISE EXCEPTION 'subject binding principal kind mismatch';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_security_subject_kind BEFORE INSERT OR UPDATE ON security_subject_bindings
        FOR EACH ROW EXECUTE FUNCTION enforce_security_subject_kind();
    """)
    op.execute("""
        CREATE FUNCTION enforce_security_membership_role_tenant() RETURNS trigger AS $$
        DECLARE membership_tenant uuid; role_tenant uuid;
        BEGIN
            SELECT tenant_id INTO membership_tenant FROM security_memberships WHERE id=NEW.membership_id;
            SELECT tenant_id INTO role_tenant FROM security_roles WHERE id=NEW.role_id;
            IF membership_tenant IS NULL OR role_tenant IS NULL OR membership_tenant <> role_tenant THEN
                RAISE EXCEPTION 'cross-tenant role assignment';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_security_membership_role_tenant BEFORE INSERT OR UPDATE ON security_membership_roles
        FOR EACH ROW EXECUTE FUNCTION enforce_security_membership_role_tenant();
    """)
    op.execute("""
        CREATE FUNCTION reject_security_reference_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'immutable security reference'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_security_permissions_immutable BEFORE UPDATE OR DELETE ON security_permissions
        FOR EACH ROW EXECUTE FUNCTION reject_security_reference_mutation();
        CREATE TRIGGER trg_security_provisioning_immutable BEFORE UPDATE OR DELETE ON security_provisioning_operations
        FOR EACH ROW EXECUTE FUNCTION reject_security_reference_mutation();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION reject_analysis_run_scope_claim_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'analysis run scope claims are immutable';
            END IF;
            IF current_setting('app.security_historical_binding', true) = 'on'
               AND OLD.tenant_id IS NULL AND NEW.tenant_id IS NOT NULL
               AND OLD.claim_id IS NOT DISTINCT FROM NEW.claim_id
               AND OLD.run_id IS NOT DISTINCT FROM NEW.run_id
               AND OLD.company_id IS NOT DISTINCT FROM NEW.company_id
               AND OLD.financial_period_id IS NOT DISTINCT FROM NEW.financial_period_id
               AND OLD.initiating_subject_id IS NOT DISTINCT FROM NEW.initiating_subject_id
               AND OLD.operation_kind IS NOT DISTINCT FROM NEW.operation_kind
               AND OLD.original_operation IS NOT DISTINCT FROM NEW.original_operation
               AND OLD.previous_run_id IS NOT DISTINCT FROM NEW.previous_run_id
               AND OLD.application_command_digest IS NOT DISTINCT FROM NEW.application_command_digest
               AND OLD.status IS NOT DISTINCT FROM NEW.status
               AND OLD.version IS NOT DISTINCT FROM NEW.version
               AND OLD.claim_token IS NOT DISTINCT FROM NEW.claim_token
               AND OLD.persisted_run_id IS NOT DISTINCT FROM NEW.persisted_run_id
               AND OLD.persisted_request_fingerprint IS NOT DISTINCT FROM NEW.persisted_request_fingerprint
               AND OLD.persisted_terminal_content_digest IS NOT DISTINCT FROM NEW.persisted_terminal_content_digest
               AND OLD.claimed_at IS NOT DISTINCT FROM NEW.claimed_at
               AND OLD.finalized_at IS NOT DISTINCT FROM NEW.finalized_at THEN
                RETURN NEW;
            END IF;
            IF OLD.claim_id IS DISTINCT FROM NEW.claim_id
               OR OLD.run_id IS DISTINCT FROM NEW.run_id
               OR OLD.company_id IS DISTINCT FROM NEW.company_id
               OR OLD.financial_period_id IS DISTINCT FROM NEW.financial_period_id
               OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
               OR OLD.initiating_subject_id IS DISTINCT FROM NEW.initiating_subject_id
               OR OLD.operation_kind IS DISTINCT FROM NEW.operation_kind
               OR OLD.original_operation IS DISTINCT FROM NEW.original_operation
               OR OLD.previous_run_id IS DISTINCT FROM NEW.previous_run_id
               OR OLD.application_command_digest IS DISTINCT FROM NEW.application_command_digest
               OR OLD.claim_token IS DISTINCT FROM NEW.claim_token
               OR OLD.claimed_at IS DISTINCT FROM NEW.claimed_at THEN
                RAISE EXCEPTION 'analysis run scope ownership is immutable';
            END IF;
            IF OLD.status <> 'CLAIMED' OR NEW.status <> 'FINALIZED'
               OR NEW.version <> OLD.version + 1
               OR NEW.persisted_run_id IS NULL
               OR NEW.persisted_request_fingerprint IS NULL
               OR NEW.persisted_terminal_content_digest IS NULL
               OR NEW.finalized_at IS NULL THEN
                RAISE EXCEPTION 'only one valid claim finalization is permitted';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    bind = op.get_bind()
    state_count = bind.scalar(sa.text("""
        SELECT
            (SELECT count(*) FROM security_tenants) +
            (SELECT count(*) FROM security_principals) +
            (SELECT count(*) FROM security_memberships) +
            (SELECT count(*) FROM security_provisioning_operations) +
            (SELECT count(*) FROM companies WHERE tenant_id IS NOT NULL) +
            (SELECT count(*) FROM bulk_upload_batches WHERE tenant_id IS NOT NULL)
    """))
    if state_count:
        raise RuntimeError("Cannot remove the 5.0E security foundation while authoritative state exists.")
    op.execute("""
        CREATE OR REPLACE FUNCTION reject_analysis_run_scope_claim_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'analysis run scope claims are immutable';
            END IF;
            IF OLD.claim_id IS DISTINCT FROM NEW.claim_id
               OR OLD.run_id IS DISTINCT FROM NEW.run_id
               OR OLD.company_id IS DISTINCT FROM NEW.company_id
               OR OLD.financial_period_id IS DISTINCT FROM NEW.financial_period_id
               OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
               OR OLD.initiating_subject_id IS DISTINCT FROM NEW.initiating_subject_id
               OR OLD.operation_kind IS DISTINCT FROM NEW.operation_kind
               OR OLD.original_operation IS DISTINCT FROM NEW.original_operation
               OR OLD.previous_run_id IS DISTINCT FROM NEW.previous_run_id
               OR OLD.application_command_digest IS DISTINCT FROM NEW.application_command_digest
               OR OLD.claim_token IS DISTINCT FROM NEW.claim_token
               OR OLD.claimed_at IS DISTINCT FROM NEW.claimed_at THEN
                RAISE EXCEPTION 'analysis run scope ownership is immutable';
            END IF;
            IF OLD.status <> 'CLAIMED' OR NEW.status <> 'FINALIZED'
               OR NEW.version <> OLD.version + 1
               OR NEW.persisted_run_id IS NULL
               OR NEW.persisted_request_fingerprint IS NULL
               OR NEW.persisted_terminal_content_digest IS NULL
               OR NEW.finalized_at IS NULL THEN
                RAISE EXCEPTION 'only one valid claim finalization is permitted';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_security_provisioning_immutable ON security_provisioning_operations")
    op.execute("DROP TRIGGER IF EXISTS trg_security_permissions_immutable ON security_permissions")
    op.execute("DROP FUNCTION IF EXISTS reject_security_reference_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_security_membership_role_tenant ON security_membership_roles")
    op.execute("DROP FUNCTION IF EXISTS enforce_security_membership_role_tenant()")
    op.execute("DROP TRIGGER IF EXISTS trg_security_subject_kind ON security_subject_bindings")
    op.execute("DROP FUNCTION IF EXISTS enforce_security_subject_kind()")
    op.drop_index("ix_bulk_upload_batches_tenant_id", table_name="bulk_upload_batches")
    op.drop_constraint("fk_bulk_upload_batches_tenant_id_security_tenants", "bulk_upload_batches", type_="foreignkey")
    op.drop_column("bulk_upload_batches", "tenant_id")
    op.drop_index("ix_companies_tenant_id", table_name="companies")
    op.drop_constraint("fk_companies_tenant_id_security_tenants", "companies", type_="foreignkey")
    op.drop_column("companies", "tenant_id")
    op.drop_table("security_resource_binding_quarantine")
    op.drop_table("security_provisioning_operations")
    op.drop_index("ix_security_membership_roles_role", table_name="security_membership_roles")
    op.drop_table("security_membership_roles")
    op.drop_index("ix_security_role_permissions_permission", table_name="security_role_permissions")
    op.drop_table("security_role_permissions")
    op.drop_index("ix_security_roles_tenant_status", table_name="security_roles")
    op.drop_table("security_roles")
    op.drop_table("security_permissions")
    op.drop_index("ix_security_memberships_principal_status", table_name="security_memberships")
    op.drop_index("ix_security_memberships_tenant_status", table_name="security_memberships")
    op.drop_table("security_memberships")
    op.drop_index("uq_security_subject_bindings_issuer_client", table_name="security_subject_bindings")
    op.drop_index("ix_security_subject_bindings_principal_status", table_name="security_subject_bindings")
    op.drop_table("security_subject_bindings")
    op.drop_index("ix_security_principals_status", table_name="security_principals")
    op.drop_table("security_principals")
    op.drop_index("ix_security_tenants_status", table_name="security_tenants")
    op.drop_table("security_tenants")
