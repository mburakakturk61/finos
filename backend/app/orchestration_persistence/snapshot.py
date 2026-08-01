"""Fail-closed materialization of unchanged 5.0A previous-execution snapshots."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineExecutionStatus,
    PreviousEngineSnapshot,
    PreviousExecutionSnapshot,
)
from app.engines.balance_sheet.service import BalanceSheetAnalysisOutcome
from app.engines.income_statement.service import IncomeStatementAnalysisOutcome
from app.models.enums import AnalysisStatus, AnalysisSourceRole
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.orchestration_persistence import (
    OrchestrationArtifact,
    OrchestrationEngineExecution,
    OrchestrationPhysicalObject,
    OrchestrationRun,
)
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.codec import canonical_json_bytes, decode_artifact
from app.orchestration_persistence.errors import OrchestrationPersistenceError, PersistenceErrorCategory
from app.orchestration_persistence.types import (
    PersistenceRunScope,
    ResumeEngineBinding,
    ResumePersistenceContext,
    SnapshotLoadResult,
)


class SqlAlchemySnapshotBuilder:
    def __init__(self, session: Session, blob_store: FilesystemBlobStore) -> None:
        self.session = session
        self.blob_store = blob_store

    def _financial_result(self, execution: OrchestrationEngineExecution) -> tuple[object, str]:
        owner = self.session.get(FinancialAnalysisResult, execution.financial_analysis_result_id)
        if owner is None:
            raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_MISSING, "Financial result owner is missing.")
        if execution.engine_code == EngineCode.RATIO.value:
            if owner.result_json is None:
                raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_MISSING, "Ratio result owner payload is missing.")
            digest = hashlib.sha256(canonical_json_bytes(owner.result_json)).hexdigest()
            if execution.owner_content_digest != digest:
                raise OrchestrationPersistenceError(
                    PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                    "Financial result owner failed integrity verification.",
                )
            return owner.result_json, digest
        usage = execution.financial_trial_balance_usage
        roles = set(self.session.scalars(select(FinancialAnalysisResultSource.role).where(FinancialAnalysisResultSource.analysis_result_id == owner.id)))
        if usage == "fallback_source" and AnalysisSourceRole.TRIAL_BALANCE_FALLBACK not in roles:
            raise OrchestrationPersistenceError(
                PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                "Financial snapshot trial-balance provenance is inconsistent.",
            )
        if usage == "reconciliation_reference" and AnalysisSourceRole.SUPPORTING_ANALYSIS not in roles:
            raise OrchestrationPersistenceError(
                PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                "Financial snapshot reconciliation provenance is inconsistent.",
            )
        outcome_type = BalanceSheetAnalysisOutcome if execution.engine_code == EngineCode.FS_BALANCE_SHEET.value else IncomeStatementAnalysisOutcome
        outcome = outcome_type(owner.status, owner.source_mode, owner.result_json, owner.error_message, usage)
        digest_payload = {
            "status": owner.status,
            "source_mode": owner.source_mode,
            "result_json": owner.result_json,
            "error_message": owner.error_message,
            "trial_balance_usage": usage,
        }
        digest = hashlib.sha256(canonical_json_bytes(digest_payload)).hexdigest()
        if execution.owner_content_digest != digest:
            raise OrchestrationPersistenceError(
                PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                "Financial result owner failed integrity verification.",
            )
        return outcome, digest

    def _artifact_result(self, execution: OrchestrationEngineExecution) -> tuple[object, str]:
        artifact = self.session.get(OrchestrationArtifact, execution.artifact_id)
        if artifact is None:
            raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_MISSING, "Orchestration artifact is missing.")
        if artifact.inline_payload is not None:
            raw = canonical_json_bytes(artifact.inline_payload)
        else:
            physical = self.session.get(OrchestrationPhysicalObject, artifact.physical_object_id)
            if physical is None or physical.state != "ready":
                raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_MISSING, "Ready physical artifact is missing.")
            raw = self.blob_store.read_ready(physical.locator)
        value = decode_artifact(artifact.artifact_kind, raw, artifact.content_digest, artifact.serializer_schema_version)
        if execution.owner_content_digest != artifact.content_digest:
            raise OrchestrationPersistenceError(
                PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                "Execution artifact binding failed integrity verification.",
            )
        return value, artifact.content_digest

    def build_previous_execution_snapshot(self, run_id: str, target_scope: PersistenceRunScope) -> SnapshotLoadResult:
        run = self.session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == run_id))
        if run is None:
            raise OrchestrationPersistenceError(PersistenceErrorCategory.RUN_NOT_FOUND, "Previous orchestration run was not found.")
        if (run.company_id, run.period_id) != (target_scope.company_id, target_scope.period_id):
            raise OrchestrationPersistenceError(PersistenceErrorCategory.SCOPE_MISMATCH, "Previous run scope does not match target scope.")
        if run.finalized_at is None:
            raise OrchestrationPersistenceError(PersistenceErrorCategory.PREVIOUS_RUN_NOT_FINALIZED, "Previous run is not finalized.")
        executions = tuple(self.session.scalars(select(OrchestrationEngineExecution).where(OrchestrationEngineExecution.run_id == run.id).order_by(OrchestrationEngineExecution.execution_ordinal)))
        snapshots = []
        bindings = []
        for execution in executions:
            value = None
            digest = hashlib.sha256(b"").hexdigest()
            if execution.artifact_id:
                value, digest = self._artifact_result(execution)
            elif execution.financial_analysis_result_id:
                value, digest = self._financial_result(execution)
            elif execution.status in (
                EngineExecutionStatus.COMPLETED.value,
                EngineExecutionStatus.DEGRADED.value,
                EngineExecutionStatus.REUSED.value,
            ):
                raise OrchestrationPersistenceError(
                    PersistenceErrorCategory.ARTIFACT_MISSING,
                    "Successful execution result owner is missing.",
                )
            snapshots.append(PreviousEngineSnapshot(
                engine_code=EngineCode(execution.engine_code), execution_status=EngineExecutionStatus(execution.status),
                engine_schema_version_used=execution.engine_schema_version, engine_model_version_used=execution.engine_model_version,
                input_fingerprint=execution.input_fingerprint, fingerprint_schema_version=execution.fingerprint_schema_version,
                result_ref=value,
            ))
            bindings.append(ResumeEngineBinding(
                EngineCode(execution.engine_code), execution.id, execution.artifact_id,
                execution.financial_analysis_result_id, digest,
            ))
        snapshot = PreviousExecutionSnapshot(
            previous_run_id=run.run_id, request_fingerprint=run.request_fingerprint,
            orchestration_schema_version=run.orchestration_schema_version,
            orchestration_model_version=run.orchestration_model_version,
            execution_plan_version=run.execution_plan_version, engine_snapshots=tuple(snapshots),
        )
        context = ResumePersistenceContext(run.id, run.run_id, target_scope, tuple(bindings))
        return SnapshotLoadResult(snapshot, context)
