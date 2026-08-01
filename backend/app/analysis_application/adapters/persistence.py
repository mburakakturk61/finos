"""5.0B anti-corruption adapter with transaction-local owner staging."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.analysis_application.contracts import ApplicationEngineCode, ApplicationScopeDTO, FinancialSourceRole
from app.analysis_application.internal_types import (
    ApplicationTerminalPersistenceRequest,
    OwnerAuditTimes,
    ResolvedFinancialOwnershipPlan,
    TerminalPersistenceResult,
)
from app.analysis_application.ownership import resolve_financial_ownership_plan
from app.engines.analysis_orchestrator.types import EngineCode
from app.models.enums import AnalysisSourceRole, AnalysisStatus, AnalysisType, SourceMode
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.codec import canonical_json_bytes
from app.orchestration_persistence.repository import SqlAlchemyOrchestrationRepository
from app.orchestration_persistence.snapshot import SqlAlchemySnapshotBuilder
from app.orchestration_persistence.types import (
    FinancialResultOwnerBinding,
    PersistTerminalRunCommand,
    PersistenceRunScope,
)

_ANALYSIS_TYPES = {
    ApplicationEngineCode.FS_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    ApplicationEngineCode.FS_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    ApplicationEngineCode.RATIO: AnalysisType.FINANCIAL_RATIOS,
}


class SqlAlchemyRunPersistenceAdapter:
    def __init__(self, session: Session, blob_store: FilesystemBlobStore) -> None:
        self.session = session
        self.repository = SqlAlchemyOrchestrationRepository(session, blob_store)
        self.snapshot_builder = SqlAlchemySnapshotBuilder(session, blob_store)

    def resolve_financial_ownership_plan(self, run_result, source_intents, scope, audit_times=None):
        if audit_times is None:
            raise ValueError("Owner audit times are required.")
        return resolve_financial_ownership_plan(run_result, source_intents, scope, audit_times)

    def build_previous_execution_snapshot(self, run_id: str, target_scope: PersistenceRunScope):
        return self.snapshot_builder.build_previous_execution_snapshot(run_id, target_scope)

    def persist_terminal_run(
        self, request: ApplicationTerminalPersistenceRequest,
    ) -> TerminalPersistenceResult:
        existing_before = self.repository.load_run(request.run_result.run_id)
        savepoint = self.session.begin_nested()
        staged: list[FinancialAnalysisResult] = []
        try:
            bindings = self._stage_financial_owners(request, request.financial_ownership_plan.audit_times, staged)
            command = PersistTerminalRunCommand(
                scope=PersistenceRunScope(request.scope.company_id, request.scope.financial_period_id),
                run_result=request.run_result,
                requested_outputs=tuple(EngineCode(item.value) for item in request.requested_outputs),
                resume_context=request.resume_context,
                financial_owner_bindings=bindings,
                telemetry=request.telemetry,
            )
            persisted = self.repository.persist_terminal_run(command)
            idempotent_replay = existing_before is not None
            if savepoint.is_active:
                savepoint.rollback()
                idempotent_replay = True
                for owner in staged:
                    if owner in self.session:
                        self.session.expunge(owner)
            elif staged and any(not inspect(owner).persistent for owner in staged):
                # The 5.0B repository resolved a concurrent unique race by
                # rolling back this transaction and returning the winner.
                # Staged owners are transient/detached and cannot persist.
                idempotent_replay = True
            return TerminalPersistenceResult(persisted, idempotent_replay)
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            raise

    def resolve_payload_references(self, run_id: str, scope: ApplicationScopeDTO, *, include_payloads: bool):
        raise NotImplementedError("Read projection is supplied by the read adapter.")

    def _stage_financial_owners(
        self, request: ApplicationTerminalPersistenceRequest,
        audit_times: OwnerAuditTimes,
        staged: list[FinancialAnalysisResult],
    ) -> tuple[FinancialResultOwnerBinding, ...]:
        records = {ApplicationEngineCode(record.engine_code.value): record for record in request.run_result.engine_records}
        owner_ids = {}
        bindings = []
        for node in request.financial_ownership_plan.nodes:
            record = records[node.engine_code]
            resolved_lineage = []
            for edge in node.lineage:
                source_analysis_id = edge.source_analysis_result_id
                if edge.source_engine_code is not None:
                    source_analysis_id = owner_ids.get(edge.source_engine_code)
                    if source_analysis_id is None:
                        raise ValueError("Same-run financial lineage source is unavailable.")
                resolved_lineage.append((edge.role, edge.source_document_id, source_analysis_id))
            existing_owner_id = node.expected_existing_owner_id
            if existing_owner_id is None and node.allow_existing_canonical_owner:
                existing_owner_id = self._find_exact_existing_owner(request, node, record, tuple(resolved_lineage))
            if existing_owner_id is not None:
                self._verify_exact_lineage(existing_owner_id, tuple(resolved_lineage))
                owner_ids[node.engine_code] = existing_owner_id
                bindings.append(FinancialResultOwnerBinding(EngineCode(node.engine_code.value), existing_owner_id=existing_owner_id))
                continue
            if record.result is None or not record.engine_model_version_used:
                raise ValueError("Financial owner requires a concrete result and engine model version.")
            outcome = record.result.result
            if node.engine_code in (ApplicationEngineCode.FS_BALANCE_SHEET, ApplicationEngineCode.FS_INCOME_STATEMENT):
                if SourceMode(outcome.source_mode.value) is not SourceMode(node.source_mode.value):
                    raise ValueError("Financial source mode differs from the engine result.")
                payload = outcome.result_json
                status = AnalysisStatus(outcome.status.value)
                error_message = outcome.error_message
            else:
                if not isinstance(outcome, dict):
                    raise ValueError("Ratio owner payload must be a dictionary.")
                payload = outcome
                status = AnalysisStatus.COMPLETED
                error_message = None
            normalized_payload = json.loads(canonical_json_bytes(payload)) if payload is not None else None
            owner = FinancialAnalysisResult(
                company_id=request.scope.company_id,
                period_id=request.scope.financial_period_id,
                document_id=node.primary_document_id,
                source_mode=SourceMode(node.source_mode.value),
                analysis_type=_ANALYSIS_TYPES[node.engine_code],
                engine_version=record.engine_model_version_used,
                status=status,
                result_json=normalized_payload,
                error_message=error_message,
                started_at=audit_times.started_at,
                completed_at=audit_times.completed_at,
            )
            self.session.add(owner)
            self.session.flush()
            staged.append(owner)
            owner_ids[node.engine_code] = owner.id
            for role, source_document_id, source_analysis_id in resolved_lineage:
                self.session.add(FinancialAnalysisResultSource(
                    analysis_result_id=owner.id,
                    company_id=request.scope.company_id,
                    period_id=request.scope.financial_period_id,
                    source_document_id=source_document_id,
                    source_analysis_result_id=source_analysis_id,
                    role=AnalysisSourceRole(role.value),
                ))
            self.session.flush()
            bindings.append(FinancialResultOwnerBinding(EngineCode(node.engine_code.value), existing_owner_id=owner.id))
        return tuple(bindings)

    def _find_exact_existing_owner(self, request, node, record, lineage):
        candidates = tuple(self.session.scalars(select(FinancialAnalysisResult).where(
            FinancialAnalysisResult.company_id == request.scope.company_id,
            FinancialAnalysisResult.period_id == request.scope.financial_period_id,
            FinancialAnalysisResult.analysis_type == _ANALYSIS_TYPES[node.engine_code],
            FinancialAnalysisResult.engine_version == record.engine_model_version_used,
        )))
        exact = []
        target_digest = hashlib.sha256(canonical_json_bytes(
            SqlAlchemyOrchestrationRepository._record_digest_payload(record)
        )).hexdigest()
        for owner in candidates:
            usage = record.result.result.trial_balance_usage if node.engine_code in {
                ApplicationEngineCode.FS_BALANCE_SHEET, ApplicationEngineCode.FS_INCOME_STATEMENT,
            } else None
            payload = SqlAlchemyOrchestrationRepository._financial_owner_digest_payload(
                EngineCode(node.engine_code.value), owner, usage,
            )
            if hashlib.sha256(canonical_json_bytes(payload)).hexdigest() != target_digest:
                continue
            if self._lineage(owner.id) == self._lineage_tuple(lineage):
                exact.append(owner.id)
        if len(exact) > 1:
            raise ValueError("Canonical financial owner resolution is ambiguous.")
        return exact[0] if exact else None

    def _verify_exact_lineage(self, owner_id, lineage):
        if self._lineage(owner_id) != self._lineage_tuple(lineage):
            raise ValueError("Existing financial owner lineage mismatch.")

    def _lineage(self, owner_id):
        rows = self.session.scalars(select(FinancialAnalysisResultSource).where(
            FinancialAnalysisResultSource.analysis_result_id == owner_id
        ))
        return frozenset((row.role.value, row.source_document_id, row.source_analysis_result_id) for row in rows)

    @staticmethod
    def _lineage_tuple(lineage):
        return frozenset((role.value, document_id, analysis_id) for role, document_id, analysis_id in lineage)
