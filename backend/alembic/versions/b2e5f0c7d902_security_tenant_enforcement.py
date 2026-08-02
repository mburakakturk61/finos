"""Milestone 5.0E E2 tenant binding enforcement.

Revision ID: b2e5f0c7d902
Revises: a1e5f0c7d901
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "b2e5f0c7d902"
down_revision = "a1e5f0c7d901"
branch_labels = None
depends_on = None


def _quarantine(bind, table_name: str, id_column: str, resource_type: str) -> None:
    rows = bind.execute(sa.text(
        f"SELECT {id_column} FROM {table_name} WHERE tenant_id IS NULL"
    )).scalars()
    for resource_id in rows:
        bind.execute(sa.text("""
            INSERT INTO security_resource_binding_quarantine
                (id, resource_type, resource_id, reason_code, status)
            VALUES (:id, :resource_type, :resource_id, 'HISTORICAL_TENANT_UNBOUND', 'OPEN')
            ON CONFLICT (resource_type, resource_id) DO NOTHING
        """), {
            "id": uuid.uuid4(), "resource_type": resource_type,
            "resource_id": resource_id,
        })


def upgrade() -> None:
    bind = op.get_bind()
    invalid = bind.scalar(sa.text("""
        SELECT count(*)
        FROM analysis_run_scope_claims c
        LEFT JOIN security_tenants t ON t.tenant_key = c.tenant_id
        WHERE c.tenant_id IS NOT NULL
          AND (
              c.tenant_id !~ '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$'
              OR octet_length(c.tenant_id) NOT BETWEEN 3 AND 63
              OR t.id IS NULL
          )
    """))
    if invalid:
        raise RuntimeError(
            "Historical analysis run scope claims require explicit trusted tenant binding."
        )

    _quarantine(bind, "companies", "id", "COMPANY")
    _quarantine(bind, "bulk_upload_batches", "id", "BULK_UPLOAD_BATCH")
    _quarantine(bind, "analysis_run_scope_claims", "claim_id", "ANALYSIS_RUN_SCOPE_CLAIM")

    op.alter_column(
        "analysis_run_scope_claims", "tenant_id",
        existing_type=sa.String(255), type_=sa.String(63), existing_nullable=True,
    )
    op.create_foreign_key(
        "fk_analysis_run_scope_claims_tenant_key_security_tenants",
        "analysis_run_scope_claims", "security_tenants",
        ["tenant_id"], ["tenant_key"], ondelete="RESTRICT",
    )

    op.execute("""
        CREATE FUNCTION require_known_security_tenant() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id IS NULL THEN
                RAISE EXCEPTION 'new resource requires tenant ownership';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_companies_require_tenant
        BEFORE INSERT ON companies FOR EACH ROW
        EXECUTE FUNCTION require_known_security_tenant();
        CREATE TRIGGER trg_bulk_upload_batches_require_tenant
        BEFORE INSERT ON bulk_upload_batches FOR EACH ROW
        EXECUTE FUNCTION require_known_security_tenant();
        CREATE TRIGGER trg_analysis_run_scope_claims_require_tenant
        BEFORE INSERT ON analysis_run_scope_claims FOR EACH ROW
        EXECUTE FUNCTION require_known_security_tenant();
    """)
    op.execute("""
        CREATE FUNCTION reject_resource_tenant_transfer() RETURNS trigger AS $$
        BEGIN
            IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id THEN
                RAISE EXCEPTION 'tenant ownership is immutable';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_companies_tenant_immutable
        BEFORE UPDATE ON companies FOR EACH ROW
        EXECUTE FUNCTION reject_resource_tenant_transfer();
        CREATE TRIGGER trg_bulk_upload_batches_tenant_immutable
        BEFORE UPDATE ON bulk_upload_batches FOR EACH ROW
        EXECUTE FUNCTION reject_resource_tenant_transfer();
    """)
    op.execute("""
        CREATE FUNCTION reject_security_tenant_key_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.tenant_key IS DISTINCT FROM NEW.tenant_key THEN
                RAISE EXCEPTION 'tenant key is immutable';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_security_tenant_key_immutable
        BEFORE UPDATE ON security_tenants FOR EACH ROW
        EXECUTE FUNCTION reject_security_tenant_key_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_security_tenant_key_immutable ON security_tenants")
    op.execute("DROP FUNCTION IF EXISTS reject_security_tenant_key_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_bulk_upload_batches_tenant_immutable ON bulk_upload_batches")
    op.execute("DROP TRIGGER IF EXISTS trg_companies_tenant_immutable ON companies")
    op.execute("DROP FUNCTION IF EXISTS reject_resource_tenant_transfer()")
    op.execute("DROP TRIGGER IF EXISTS trg_analysis_run_scope_claims_require_tenant ON analysis_run_scope_claims")
    op.execute("DROP TRIGGER IF EXISTS trg_bulk_upload_batches_require_tenant ON bulk_upload_batches")
    op.execute("DROP TRIGGER IF EXISTS trg_companies_require_tenant ON companies")
    op.execute("DROP FUNCTION IF EXISTS require_known_security_tenant()")
    op.drop_constraint(
        "fk_analysis_run_scope_claims_tenant_key_security_tenants",
        "analysis_run_scope_claims", type_="foreignkey",
    )
    op.alter_column(
        "analysis_run_scope_claims", "tenant_id",
        existing_type=sa.String(63), type_=sa.String(255), existing_nullable=True,
    )
