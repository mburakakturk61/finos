"""Scope-qualified canonical PostgreSQL read/projection adapter."""

from __future__ import annotations

import uuid
import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_application.adapters.scope_claim import SqlAlchemyRunScopeClaimRepository
from app.analysis_application.contracts import (
    AnalysisExecutionDTO,
    AnalysisHistoryPageDTO,
    AnalysisResultDTO,
    AnalysisRunStatusDTO,
    AnalysisRunSummaryDTO,
    ApplicationEngineCode,
    ApplicationExecutionStatus,
    ApplicationPayloadEnvelopeDTO,
    ApplicationPayloadReferenceDTO,
    ApplicationProjectedErrorDTO,
    ApplicationScopeDTO,
    ApplicationStatus,
    ExecutionCategory,
    FinancialComputationStatus,
    FinancialSourceMode,
    PayloadOwnerType,
)
from app.analysis_application.internal_types import (
    AuthorizedResumeSourceView,
    InternalRunView,
    VerifiedApplicationScopeBinding,
)
from app.engines.analysis_orchestrator.types import EngineCode
from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.orchestration_persistence import (
    OrchestrationArtifact,
    OrchestrationEngineExecution,
    OrchestrationError,
    OrchestrationPhysicalObject,
    OrchestrationRun,
)
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.codec import decode_artifact
from app.orchestration_persistence.codec import canonical_json_bytes
from app.orchestration_persistence.snapshot import SqlAlchemySnapshotBuilder
from app.orchestration_persistence.types import PersistenceRunScope


class ApplicationReadIntegrityError(RuntimeError):
    pass


class SqlAlchemyAnalysisReadAdapter:
    def __init__(self, session: Session, blob_store: FilesystemBlobStore) -> None:
        self.session = session
        self.blob_store = blob_store

    def load_scope(self, run_id: str) -> VerifiedApplicationScopeBinding | None:
        claim_row = self.session.scalar(select(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.run_id == run_id))
        if claim_row is None:
            return None
        claim = _claim_contract(claim_row)
        scope = ApplicationScopeDTO(
            claim.company_id, claim.financial_period_id, claim.tenant_id,
            claim.operation_kind, claim.original_operation, claim.previous_run_id,
        )
        return VerifiedApplicationScopeBinding(
            run_id, scope, PersistenceRunScope(claim.company_id, claim.financial_period_id),
            claim.application_command_digest, claim.claim_id, claim.version, claim.status,
        )

    def get_run_by_id(self, run_id: str, scope: ApplicationScopeDTO) -> InternalRunView | None:
        binding = self.load_scope(run_id)
        if binding is None:
            return None
        if binding.scope != scope:
            raise ApplicationReadIntegrityError("Scope mismatch.")
        row = self.session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == run_id))
        if row is None:
            return None
        if (row.company_id, row.period_id) != (scope.company_id, scope.financial_period_id):
            raise ApplicationReadIntegrityError("Persistence scope mismatch.")
        previous = self.session.get(OrchestrationRun, row.previous_run_id) if row.previous_run_id else None
        return InternalRunView(
            row.id, row.run_id, ApplicationStatus(row.status),
            PersistenceRunScope(row.company_id, row.period_id),
            tuple(ApplicationEngineCode(item) for item in row.requested_outputs_json),
            row.request_fingerprint, row.terminal_content_digest,
            previous.run_id if previous else None, row.finalized_at,
        )

    def get_status(self, run_id: str, scope: ApplicationScopeDTO) -> AnalysisRunStatusDTO | None:
        view = self.get_run_by_id(run_id, scope)
        if view is None:
            return None
        rows = tuple(self.session.scalars(
            select(OrchestrationEngineExecution)
            .where(OrchestrationEngineExecution.run_id == view.persisted_run_id)
            .order_by(OrchestrationEngineExecution.execution_ordinal)
        ))
        return AnalysisRunStatusDTO(
            run_id, view.status, scope, view.finalized_at,
            tuple((ApplicationEngineCode(row.engine_code), ApplicationExecutionStatus(row.status)) for row in rows),
        )

    def get_result(self, run_id: str, scope: ApplicationScopeDTO, *, include_payloads: bool) -> AnalysisResultDTO | None:
        view = self.get_run_by_id(run_id, scope)
        if view is None:
            return None
        run = self.session.get(OrchestrationRun, view.persisted_run_id)
        rows = tuple(self.session.scalars(
            select(OrchestrationEngineExecution)
            .where(OrchestrationEngineExecution.run_id == view.persisted_run_id)
            .order_by(OrchestrationEngineExecution.execution_ordinal)
        ))
        executions = tuple(self._execution(row, include_payloads) for row in rows)
        errors = tuple(_project_error(row) for row in self.session.scalars(
            select(OrchestrationError)
            .where(OrchestrationError.run_id == view.persisted_run_id)
            .order_by(OrchestrationError.error_ordinal)
        ))
        return AnalysisResultDTO(
            run_id=run_id, status=view.status, scope=scope,
            request_fingerprint=view.request_fingerprint, executions=executions,
            warnings=tuple(_application_value(item) for item in run.warnings_json), structured_errors=errors,
            execution_plan_version=run.execution_plan_version,
            orchestration_schema_version=run.orchestration_schema_version,
            orchestration_model_version=run.orchestration_model_version,
            finalized_at=run.finalized_at,
        )

    def get_execution_detail(self, run_id: str, engine_code: ApplicationEngineCode, scope: ApplicationScopeDTO, *, include_payload: bool) -> AnalysisExecutionDTO | None:
        view = self.get_run_by_id(run_id, scope)
        if view is None:
            return None
        row = self.session.scalar(select(OrchestrationEngineExecution).where(
            OrchestrationEngineExecution.run_id == view.persisted_run_id,
            OrchestrationEngineExecution.engine_code == engine_code.value,
        ))
        return self._execution(row, include_payload) if row else None

    def list_history(self, scope: ApplicationScopeDTO, cursor: str | None, limit: int) -> AnalysisHistoryPageDTO:
        if limit < 1 or limit > 200:
            raise ValueError("History limit must be between 1 and 200.")
        statement = (
            select(OrchestrationRun, AnalysisRunScopeClaim)
            .join(AnalysisRunScopeClaim, AnalysisRunScopeClaim.persisted_run_id == OrchestrationRun.id)
            .where(
                AnalysisRunScopeClaim.company_id == scope.company_id,
                AnalysisRunScopeClaim.financial_period_id == scope.financial_period_id,
                AnalysisRunScopeClaim.tenant_id.is_not_distinct_from(scope.tenant_id),
                AnalysisRunScopeClaim.status == "FINALIZED",
            )
        )
        if cursor:
            try:
                finalized_text, row_id = cursor.rsplit("|", 1)
                finalized_at, cursor_id = datetime.fromisoformat(finalized_text), uuid.UUID(row_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("History cursor is invalid.") from exc
            statement = statement.where(
                (OrchestrationRun.finalized_at < finalized_at)
                | ((OrchestrationRun.finalized_at == finalized_at) & (OrchestrationRun.id < cursor_id))
            )
        rows = tuple(self.session.execute(
            statement.order_by(OrchestrationRun.finalized_at.desc(), OrchestrationRun.id.desc()).limit(limit + 1)
        ))
        page = rows[:limit]
        items = tuple(
            AnalysisRunSummaryDTO(
                run.run_id, ApplicationStatus(run.status),
                _scope_from_claim(claim), tuple(ApplicationEngineCode(item) for item in run.requested_outputs_json),
                run.finalized_at, claim.previous_run_id,
            )
            for run, claim in page
        )
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1][0]
            next_cursor = f"{last.finalized_at.isoformat()}|{last.id}"
        return AnalysisHistoryPageDTO(items, next_cursor)

    def load_resume_source(self, previous_run_id: str, target_scope: ApplicationScopeDTO, *, materialize_payloads: bool) -> AuthorizedResumeSourceView:
        binding = self.load_scope(previous_run_id)
        if binding is None:
            raise ApplicationReadIntegrityError("Resume source not found.")
        source = binding.scope
        if (source.company_id, source.financial_period_id, source.tenant_id) != (
            target_scope.company_id, target_scope.financial_period_id, target_scope.tenant_id,
        ):
            raise ApplicationReadIntegrityError("Resume source scope mismatch.")
        run = self.get_run_by_id(previous_run_id, source)
        if run is None:
            raise ApplicationReadIntegrityError("Resume source canonical run is missing.")
        loaded = None
        if materialize_payloads:
            loaded = SqlAlchemySnapshotBuilder(self.session, self.blob_store).build_previous_execution_snapshot(
                previous_run_id, PersistenceRunScope(source.company_id, source.financial_period_id)
            )
        return AuthorizedResumeSourceView(run, binding, materialize_payloads, loaded)

    def _execution(self, row: OrchestrationEngineExecution, include_payload: bool) -> AnalysisExecutionDTO:
        error_row = self.session.scalar(select(OrchestrationError).where(OrchestrationError.engine_execution_id == row.id).order_by(OrchestrationError.error_ordinal))
        reused_run_id = None
        if row.reused_from_engine_execution_id:
            source = self.session.get(OrchestrationEngineExecution, row.reused_from_engine_execution_id)
            source_run = self.session.get(OrchestrationRun, source.run_id) if source else None
            reused_run_id = source_run.run_id if source_run else None
        projected_error = _project_error(error_row) if error_row else None
        payload = self._payload(row, include_payload, projected_error) if (row.artifact_id or row.financial_analysis_result_id) else None
        return AnalysisExecutionDTO(
            engine_code=ApplicationEngineCode(row.engine_code),
            status=ApplicationExecutionStatus(row.status), inner_status=row.inner_status,
            engine_schema_version=row.engine_schema_version,
            engine_model_version=row.engine_model_version,
            input_fingerprint=row.input_fingerprint,
            fingerprint_schema_version=row.fingerprint_schema_version,
            error=projected_error,
            dependency_engine_codes=tuple(ApplicationEngineCode(item) for item in row.dependency_engine_codes_json),
            payload=payload, reused_from_run_id=reused_run_id,
        )

    def _payload(self, execution: OrchestrationEngineExecution, include: bool, projected_error) -> ApplicationPayloadEnvelopeDTO:
        if execution.financial_analysis_result_id:
            owner = self.session.get(FinancialAnalysisResult, execution.financial_analysis_result_id)
            if owner is None or not execution.owner_content_digest:
                raise ApplicationReadIntegrityError("Financial owner is missing.")
            digest_payload = owner.result_json
            if execution.engine_code in {EngineCode.FS_BALANCE_SHEET.value, EngineCode.FS_INCOME_STATEMENT.value}:
                digest_payload = {
                    "status": owner.status, "source_mode": owner.source_mode,
                    "result_json": owner.result_json, "error_message": owner.error_message,
                    "trial_balance_usage": execution.financial_trial_balance_usage,
                }
            if hashlib.sha256(canonical_json_bytes(digest_payload)).hexdigest() != execution.owner_content_digest:
                raise ApplicationReadIntegrityError("Financial owner digest verification failed.")
            sources = tuple(sorted(
                self.session.scalars(select(FinancialAnalysisResultSource).where(FinancialAnalysisResultSource.analysis_result_id == owner.id)),
                key=lambda item: (_SOURCE_ROLE_ORDER[item.role.value], str(item.source_document_id or item.source_analysis_result_id)),
            ))
            reference = ApplicationPayloadReferenceDTO(
                PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT, execution.result_kind,
                execution.owner_content_digest, financial_analysis_result_id=owner.id,
            )
            return ApplicationPayloadEnvelopeDTO(
                reference, FinancialComputationStatus(owner.status.value),
                FinancialSourceMode(owner.source_mode.value), owner.result_json if include else None,
                projected_error, owner.error_message, execution.inner_status,
                execution.financial_trial_balance_usage,
                tuple(f"{item.role.value}:{item.source_document_id or item.source_analysis_result_id}" for item in sources),
                execution.engine_schema_version, execution.engine_model_version,
            )
        artifact = self.session.get(OrchestrationArtifact, execution.artifact_id)
        if artifact is None or not execution.owner_content_digest or artifact.content_digest != execution.owner_content_digest:
            raise ApplicationReadIntegrityError("Artifact owner is missing or mismatched.")
        result_payload = None
        if include:
            if artifact.inline_payload is not None:
                raw = canonical_json_bytes(artifact.inline_payload)
            else:
                physical = self.session.get(OrchestrationPhysicalObject, artifact.physical_object_id)
                if physical is None or physical.state != "ready":
                    raise ApplicationReadIntegrityError("Artifact blob is unavailable.")
                raw = self.blob_store.read_ready(physical.locator)
            result_payload = decode_artifact(artifact.artifact_kind, raw, artifact.content_digest, artifact.serializer_schema_version)
            from app.analysis_application.mapping import _project_value
            result_payload = _project_value(result_payload)
        reference = ApplicationPayloadReferenceDTO(
            PayloadOwnerType.ORCHESTRATION_ARTIFACT, artifact.artifact_kind,
            artifact.content_digest, artifact_id=artifact.id,
            artifact_serializer_schema_version=artifact.serializer_schema_version,
        )
        return ApplicationPayloadEnvelopeDTO(
            reference, FinancialComputationStatus.COMPLETED, None, result_payload,
            projected_error, None, execution.inner_status, None, (),
            execution.engine_schema_version, execution.engine_model_version,
        )


def _project_error(row: OrchestrationError) -> ApplicationProjectedErrorDTO:
    return ApplicationProjectedErrorDTO(
        ExecutionCategory(row.category),
        ApplicationEngineCode(row.engine_code) if row.engine_code else None,
        row.message,
    )


def _claim_contract(row):
    from app.analysis_application.adapters.scope_claim import _to_contract
    return _to_contract(row)


def _scope_from_claim(row):
    from app.analysis_application.contracts import ApplicationOperationKind, ApplicationOriginalOperation
    return ApplicationScopeDTO(
        row.company_id, row.financial_period_id, row.tenant_id,
        ApplicationOperationKind(row.operation_kind), ApplicationOriginalOperation(row.original_operation),
        row.previous_run_id,
    )


def _application_value(value):
    from app.analysis_application.mapping import _project_value
    return _project_value(value)


_SOURCE_ROLE_ORDER = {
    "primary_document": 0,
    "primary_analysis": 1,
    "trial_balance_fallback": 2,
    "supporting_document": 3,
    "supporting_analysis": 4,
    "prior_period_reference": 5,
}
