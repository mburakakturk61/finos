"""Milestone 4.5C authoritative period-policy metadata.

Revision ID: c4f7a9d2e103
Revises: b2e5f0c7d902
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c4f7a9d2e103"
down_revision = "b2e5f0c7d902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financial_periods", sa.Column("accounting_basis_code", sa.String(32), nullable=True))
    op.add_column("financial_periods", sa.Column("accounting_policy_version", sa.String(64), nullable=True))
    op.add_column("financial_periods", sa.Column("annual_reporting_period_start_date", sa.Date(), nullable=True))
    op.add_column("financial_periods", sa.Column("annual_reporting_period_end_date", sa.Date(), nullable=True))
    op.add_column("financial_periods", sa.Column("ifrs18_early_adopted", sa.Boolean(), nullable=True))
    op.add_column("financial_periods", sa.Column("cash_flow_coverage_kind", sa.String(16), nullable=True))

    op.create_check_constraint(
        op.f("ck_financial_periods_cf_policy_all_null_or_set"),
        "financial_periods",
        "(accounting_basis_code IS NULL AND accounting_policy_version IS NULL "
        "AND annual_reporting_period_start_date IS NULL "
        "AND annual_reporting_period_end_date IS NULL "
        "AND ifrs18_early_adopted IS NULL AND cash_flow_coverage_kind IS NULL) OR "
        "(accounting_basis_code IS NOT NULL AND accounting_policy_version IS NOT NULL "
        "AND annual_reporting_period_start_date IS NOT NULL "
        "AND annual_reporting_period_end_date IS NOT NULL "
        "AND ifrs18_early_adopted IS NOT NULL AND cash_flow_coverage_kind IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_financial_periods_cf_supported_basis_policy"),
        "financial_periods",
        "accounting_basis_code IS NULL OR "
        "(accounting_basis_code = 'tr_tdhp_accrual' "
        "AND accounting_policy_version = 'tr_tdhp_accrual/1.0.0')",
    )
    op.create_check_constraint(
        op.f("ck_financial_periods_cf_annual_containment"),
        "financial_periods",
        "annual_reporting_period_start_date IS NULL OR "
        "(annual_reporting_period_start_date <= start_date "
        "AND start_date <= end_date AND end_date <= annual_reporting_period_end_date)",
    )
    op.create_check_constraint(
        op.f("ck_financial_periods_cf_coverage_kind"),
        "financial_periods",
        "cash_flow_coverage_kind IS NULL OR "
        "(period_type = 'year_end' AND cash_flow_coverage_kind = 'cumulative') OR "
        "(period_type = 'monthly' AND cash_flow_coverage_kind = 'discrete') OR "
        "(period_type = 'temporary_tax' AND cash_flow_coverage_kind = 'cumulative') OR "
        "period_type IN ('quarter', 'custom')",
    )
    op.create_check_constraint(
        op.f("ck_financial_periods_cash_flow_coverage_kind"),
        "financial_periods",
        "cash_flow_coverage_kind IS NULL OR cash_flow_coverage_kind IN ('discrete','cumulative')",
    )

    op.execute("""
        CREATE FUNCTION cf_lock_financial_period_company_namespace()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM 1 FROM companies WHERE id = NEW.company_id FOR UPDATE NOWAIT;
            ELSIF TG_OP = 'DELETE' THEN
                PERFORM 1 FROM companies WHERE id = OLD.company_id FOR UPDATE NOWAIT;
            ELSE
                PERFORM 1 FROM companies
                WHERE id IN (OLD.company_id, NEW.company_id)
                ORDER BY id FOR UPDATE NOWAIT;
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_cf_00_namespace_financial_periods_ins
        BEFORE INSERT ON financial_periods FOR EACH ROW
        EXECUTE FUNCTION cf_lock_financial_period_company_namespace();
        CREATE TRIGGER trg_cf_00_namespace_financial_periods_upd
        BEFORE UPDATE ON financial_periods FOR EACH ROW
        EXECUTE FUNCTION cf_lock_financial_period_company_namespace();
        CREATE TRIGGER trg_cf_00_namespace_financial_periods_del
        BEFORE DELETE ON financial_periods FOR EACH ROW
        EXECUTE FUNCTION cf_lock_financial_period_company_namespace();
    """)


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.scalar(sa.text("""
        SELECT count(*) FROM financial_periods
        WHERE accounting_basis_code IS NOT NULL
           OR accounting_policy_version IS NOT NULL
           OR annual_reporting_period_start_date IS NOT NULL
           OR annual_reporting_period_end_date IS NOT NULL
           OR ifrs18_early_adopted IS NOT NULL
           OR cash_flow_coverage_kind IS NOT NULL
    """))
    if populated:
        raise RuntimeError("Cash Flow period-policy metadata must be empty before downgrade.")

    op.execute("DROP TRIGGER IF EXISTS trg_cf_00_namespace_financial_periods_del ON financial_periods")
    op.execute("DROP TRIGGER IF EXISTS trg_cf_00_namespace_financial_periods_upd ON financial_periods")
    op.execute("DROP TRIGGER IF EXISTS trg_cf_00_namespace_financial_periods_ins ON financial_periods")
    op.execute("DROP FUNCTION IF EXISTS cf_lock_financial_period_company_namespace()")
    # PostgreSQL drops every CHECK that depends on these columns together
    # with its column.  Relying on dependency removal also keeps downgrade
    # robust across SQLAlchemy naming-convention rendering.
    op.drop_column("financial_periods", "cash_flow_coverage_kind")
    op.drop_column("financial_periods", "ifrs18_early_adopted")
    op.drop_column("financial_periods", "annual_reporting_period_end_date")
    op.drop_column("financial_periods", "annual_reporting_period_start_date")
    op.drop_column("financial_periods", "accounting_policy_version")
    op.drop_column("financial_periods", "accounting_basis_code")
