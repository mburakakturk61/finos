"""Milestone 5.0B critical review integrity constraints.

Revision ID: 4f9d2a6b8c10
Revises: 3e8c3f6501ce
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4f9d2a6b8c10"
down_revision: Union[str, None] = "3e8c3f6501ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sha256_check(column: str) -> str:
    remainder = column
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column}) = 64 AND length({remainder}) = 0"


def upgrade() -> None:
    op.add_column("orchestration_engine_executions", sa.Column("owner_content_digest", sa.String(64)))
    op.add_column("orchestration_engine_executions", sa.Column("financial_trial_balance_usage", sa.String(32)))
    op.create_check_constraint(
        op.f("ck_orchestration_runs_status"),
        "orchestration_runs",
        "status IN ('fully_completed','completed_with_degradations','partially_completed','failed','cancelled')",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_result_owner_status_xor"),
        "orchestration_engine_executions",
        "((status IN ('completed','degraded','reused')) AND "
        "((artifact_id IS NOT NULL) <> (financial_analysis_result_id IS NOT NULL))) OR "
        "((status IN ('not_started','failed','skipped')) AND artifact_id IS NULL AND financial_analysis_result_id IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_status"),
        "orchestration_engine_executions",
        "status IN ('not_started','completed','degraded','failed','skipped','reused')",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_code"),
        "orchestration_engine_executions",
        "engine_code IN ('fs_balance_sheet','fs_income_statement','ratio','benchmark','health_score','credit_score','recommendation','executive_report','dashboard','render_contract')",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_engine_owner_mapping"),
        "orchestration_engine_executions",
        "((engine_code IN ('fs_balance_sheet','fs_income_statement','ratio')) AND artifact_id IS NULL) OR "
        "((engine_code NOT IN ('fs_balance_sheet','fs_income_statement','ratio')) AND financial_analysis_result_id IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_owner_digest_presence"),
        "orchestration_engine_executions",
        "((artifact_id IS NOT NULL OR financial_analysis_result_id IS NOT NULL) AND owner_content_digest IS NOT NULL) OR "
        "(artifact_id IS NULL AND financial_analysis_result_id IS NULL AND owner_content_digest IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_owner_digest_sha256"),
        "orchestration_engine_executions",
        "owner_content_digest IS NULL OR " + _sha256_check("owner_content_digest"),
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_financial_trial_balance_usage"),
        "orchestration_engine_executions",
        "financial_trial_balance_usage IS NULL OR "
        "(engine_code IN ('fs_balance_sheet','fs_income_statement') AND "
        "financial_trial_balance_usage IN ('fallback_source','reconciliation_reference'))",
    )
    op.create_check_constraint(
        op.f("ck_orchestration_engine_executions_no_self_reuse"),
        "orchestration_engine_executions",
        "reused_from_engine_execution_id IS NULL OR reused_from_engine_execution_id <> id",
    )


def downgrade() -> None:
    for name in (
        "no_self_reuse",
        "financial_trial_balance_usage",
        "owner_digest_sha256",
        "owner_digest_presence",
        "engine_owner_mapping",
        "engine_code",
        "status",
        "result_owner_status_xor",
    ):
        op.drop_constraint(
            op.f(f"ck_orchestration_engine_executions_{name}"),
            "orchestration_engine_executions",
            type_="check",
        )
    op.drop_constraint(op.f("ck_orchestration_runs_status"), "orchestration_runs", type_="check")
    op.drop_column("orchestration_engine_executions", "financial_trial_balance_usage")
    op.drop_column("orchestration_engine_executions", "owner_content_digest")
