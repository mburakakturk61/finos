from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.orchestration_persistence import (
    OrchestrationArtifact,
    OrchestrationEngineExecution,
    OrchestrationRun,
)


def _names(table, kind):
    return {constraint.name for constraint in table.constraints if isinstance(constraint, kind)}


def test_run_identity_and_scope_constraints_are_declared():
    assert "uq_orchestration_runs_run_id" in _names(OrchestrationRun.__table__, UniqueConstraint)
    checks = _names(OrchestrationRun.__table__, CheckConstraint)
    assert "ck_orchestration_runs_request_fingerprint_sha256" in checks
    assert "ck_orchestration_runs_terminal_digest_sha256" in checks
    assert "ck_orchestration_runs_no_self_resume" in checks


def test_execution_has_per_run_uniqueness_and_owner_checks():
    uniques = _names(OrchestrationEngineExecution.__table__, UniqueConstraint)
    assert "uq_orchestration_execution_run_engine" in uniques
    assert "uq_orchestration_execution_run_ordinal" in uniques
    checks = _names(OrchestrationEngineExecution.__table__, CheckConstraint)
    assert "ck_orchestration_engine_executions_result_owner_at_most_one" in checks
    assert "ck_orchestration_engine_executions_reuse_source_status" in checks


def test_artifact_has_inline_external_xor():
    assert "ck_orchestration_artifacts_storage_owner_xor" in _names(
        OrchestrationArtifact.__table__, CheckConstraint
    )
