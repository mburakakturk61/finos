"""SQLAlchemy/PostgreSQL terminal-run repository and transaction boundary."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engines.analysis_orchestrator.execution_plan import get_execution_plan
from app.engines.analysis_orchestrator.registry import ENGINE_DEPENDENCY_REGISTRY
from app.engines.analysis_orchestrator.types import EngineCode, EngineExecutionStatus
from app.models.enums import AnalysisStatus
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.orchestration_persistence import (
    OrchestrationArtifact,
    OrchestrationArtifactLocation,
    OrchestrationEngineExecution,
    OrchestrationError,
    OrchestrationPhysicalObject,
    OrchestrationRun,
)
from app.orchestration_persistence.artifacts import prepare_artifact
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.codec import SERIALIZER_FORMAT, canonical_json_bytes
from app.orchestration_persistence.errors import OrchestrationPersistenceError, PersistenceErrorCategory
from app.orchestration_persistence.ownership import RESULT_OWNERSHIP_REGISTRY, ResultOwner
from app.orchestration_persistence.types import (
    FinancialResultOwnerBinding,
    PersistedRun,
    PersistTerminalRunCommand,
    PersistenceRunScope,
    RunHistoryPage,
)


def _fail(message: str, category: PersistenceErrorCategory = PersistenceErrorCategory.PERSISTENCE_INVARIANT_VIOLATION) -> None:
    raise OrchestrationPersistenceError(category, message)


class SqlAlchemyOrchestrationRepository:
    def __init__(self, session: Session, blob_store: FilesystemBlobStore) -> None:
        self.session = session
        self.blob_store = blob_store

    def load_run(self, run_id: str) -> PersistedRun | None:
        row = self.session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == run_id))
        return self._project(row) if row else None

    def list_run_history(
        self, scope: PersistenceRunScope, cursor: str | None, limit: int
    ) -> RunHistoryPage:
        if limit < 1 or limit > 200:
            _fail("History page limit must be between 1 and 200.")
        statement = select(OrchestrationRun).where(
            OrchestrationRun.company_id == scope.company_id,
            OrchestrationRun.period_id == scope.period_id,
        )
        if cursor:
            try:
                finalized_text, row_id = cursor.rsplit("|", 1)
                finalized_at = datetime.fromisoformat(finalized_text)
                cursor_id = uuid.UUID(row_id)
            except (ValueError, TypeError) as exc:
                raise OrchestrationPersistenceError(
                    PersistenceErrorCategory.PERSISTENCE_INVARIANT_VIOLATION,
                    "History cursor is invalid.",
                ) from exc
            statement = statement.where(
                (OrchestrationRun.finalized_at < finalized_at)
                | ((OrchestrationRun.finalized_at == finalized_at) & (OrchestrationRun.id < cursor_id))
            )
        rows = tuple(self.session.scalars(
            statement.order_by(OrchestrationRun.finalized_at.desc(), OrchestrationRun.id.desc()).limit(limit + 1)
        ))
        page_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page_rows:
            last = page_rows[-1]
            next_cursor = f"{last.finalized_at.isoformat()}|{last.id}"
        return RunHistoryPage(tuple(self._project(row) for row in page_rows), next_cursor)

    @staticmethod
    def _project(row: OrchestrationRun) -> PersistedRun:
        return PersistedRun(row.id, row.run_id, row.request_fingerprint, row.terminal_content_digest, PersistenceRunScope(row.company_id, row.period_id), row.finalized_at)

    def _validate_command(self, command: PersistTerminalRunCommand) -> None:
        result = command.run_result
        if not result.request_fingerprint or len(result.request_fingerprint) != 64:
            _fail("Authoritative request fingerprint is invalid.")
        if not command.requested_outputs or len(set(command.requested_outputs)) != len(command.requested_outputs):
            _fail("Requested outputs must be non-empty and unique.")
        required = set(command.requested_outputs)
        changed = True
        while changed:
            changed = False
            for code in tuple(required):
                dependency = ENGINE_DEPENDENCY_REGISTRY[code].dependency
                for item in dependency.all_of + dependency.any_of:
                    if item not in required:
                        required.add(item)
                        changed = True
        expected = tuple(code for code in get_execution_plan() if code in required)
        actual = tuple(record.engine_code for record in result.engine_records)
        if expected != actual:
            _fail("Requested output dependency closure does not match engine records.")
        if command.resume_context and command.resume_context.scope != command.scope:
            _fail("Resume scope does not match run scope.", PersistenceErrorCategory.SCOPE_MISMATCH)
        reused = {record.engine_code: record for record in result.engine_records if record.status is EngineExecutionStatus.REUSED}
        source_bindings = {item.engine_code: item for item in command.resume_context.engine_bindings} if command.resume_context else {}
        if set(reused) != set(source_bindings):
            _fail("Resume source bindings must exactly match reused executions.")
        if command.resume_context:
            previous = self.session.get(OrchestrationRun, command.resume_context.persisted_run_id)
            if previous is None or previous.run_id != command.resume_context.previous_run_id:
                _fail("Previous persisted run identity is invalid.")
            if previous.run_id == result.run_id:
                _fail("A resumed run must use a new run ID.")
            if (previous.company_id, previous.period_id) != (command.scope.company_id, command.scope.period_id):
                _fail("Previous persisted run scope mismatch.", PersistenceErrorCategory.SCOPE_MISMATCH)
            self._validate_lineage(previous)
            for code, record in reused.items():
                binding = source_bindings[code]
                source = self.session.get(OrchestrationEngineExecution, binding.source_engine_execution_id)
                if source is None or source.run_id != previous.id or source.engine_code != code.value:
                    _fail("Reused execution source binding is invalid.")
                if (source.input_fingerprint, source.fingerprint_schema_version, source.engine_schema_version, source.engine_model_version) != (
                    record.input_fingerprint, record.fingerprint_schema_version,
                    record.engine_schema_version_used, record.engine_model_version_used,
                ):
                    _fail("Reused execution source contract mismatch.")
                if (
                    binding.artifact_id != source.artifact_id
                    or binding.financial_analysis_result_id != source.financial_analysis_result_id
                    or binding.canonical_digest != source.owner_content_digest
                ):
                    _fail(
                        "Reused execution owner binding does not match its source.",
                        PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                    )
                actual_digest = self._verified_owner_digest(source)
                if actual_digest != binding.canonical_digest:
                    _fail(
                        "Reused execution owner content failed integrity verification.",
                        PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                    )
                result_payload = self._record_digest_payload(record)
                if hashlib.sha256(canonical_json_bytes(result_payload)).hexdigest() != actual_digest:
                    _fail(
                        "Reused result payload does not match its canonical owner.",
                        PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
                    )

    def _validate_lineage(self, previous: OrchestrationRun) -> None:
        visited: set[uuid.UUID] = set()
        current: OrchestrationRun | None = previous
        while current is not None:
            if current.id in visited:
                _fail("Resume lineage contains a cycle.")
            visited.add(current.id)
            if current.finalized_at is None:
                _fail(
                    "Previous run is not finalized.",
                    PersistenceErrorCategory.PREVIOUS_RUN_NOT_FINALIZED,
                )
            current = self.session.get(OrchestrationRun, current.previous_run_id) if current.previous_run_id else None

    def _verified_owner_digest(self, execution: OrchestrationEngineExecution) -> str:
        if (execution.artifact_id is None) == (execution.financial_analysis_result_id is None):
            _fail("Source execution does not have exactly one result owner.")
        if execution.artifact_id is not None:
            artifact = self.session.get(OrchestrationArtifact, execution.artifact_id)
            if artifact is None:
                _fail("Source artifact owner is missing.", PersistenceErrorCategory.ARTIFACT_MISSING)
            if artifact.inline_payload is not None:
                raw = canonical_json_bytes(artifact.inline_payload)
            else:
                physical = self.session.get(OrchestrationPhysicalObject, artifact.physical_object_id)
                if physical is None or physical.state != "ready":
                    _fail("Source physical artifact is not ready.", PersistenceErrorCategory.ARTIFACT_MISSING)
                raw = self.blob_store.read_ready(physical.locator)
            digest = hashlib.sha256(raw).hexdigest()
            if digest != artifact.content_digest or len(raw) != artifact.byte_size:
                _fail("Source artifact owner is corrupt.", PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE)
            return digest
        owner = self.session.get(FinancialAnalysisResult, execution.financial_analysis_result_id)
        if owner is None:
            _fail("Source financial owner is missing.", PersistenceErrorCategory.ARTIFACT_MISSING)
        payload = self._financial_owner_digest_payload(
            EngineCode(execution.engine_code), owner, execution.financial_trial_balance_usage
        )
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()

    def _financial_binding_map(self, command: PersistTerminalRunCommand) -> dict[EngineCode, FinancialResultOwnerBinding]:
        bindings = {binding.engine_code: binding for binding in command.financial_owner_bindings}
        if len(bindings) != len(command.financial_owner_bindings):
            _fail("Duplicate financial owner binding.")
        return bindings

    def _bind_financial_owner(self, command: PersistTerminalRunCommand, record, binding: FinancialResultOwnerBinding, digest: str) -> uuid.UUID:
        expected_type = RESULT_OWNERSHIP_REGISTRY[record.engine_code].analysis_type
        outcome = record.result.result
        if binding.existing_owner_id:
            owner = self.session.get(FinancialAnalysisResult, binding.existing_owner_id)
            if owner is None or owner.company_id != command.scope.company_id or owner.period_id != command.scope.period_id or owner.analysis_type != expected_type:
                _fail("Existing financial result owner does not match scope/type.")
            owner_digest_payload = self._financial_owner_digest_payload(
                record.engine_code,
                owner,
                outcome.trial_balance_usage
                if record.engine_code in (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT)
                else None,
            )
            if hashlib.sha256(canonical_json_bytes(owner_digest_payload)).hexdigest() != digest:
                _fail("Financial result owner payload digest mismatch.", PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE)
            if record.engine_code in (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT) and (
                owner.status != outcome.status
                or owner.source_mode != outcome.source_mode
                or owner.error_message != outcome.error_message
            ):
                _fail("Financial result owner semantics do not match the 5.0A result.")
            return owner.id
        create = binding.create_owner
        assert create is not None
        if create.analysis_type != expected_type:
            _fail("Created financial result owner type mismatch.")
        if record.engine_code in (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT):
            if create.source_mode != outcome.source_mode:
                _fail("Created financial result source mode does not match the 5.0A result.")
            owner_status = outcome.status
            error_message = outcome.error_message
        else:
            owner_status = AnalysisStatus.COMPLETED
            error_message = None
        payload = self._financial_payload(record)
        owner = FinancialAnalysisResult(
            company_id=command.scope.company_id, period_id=command.scope.period_id,
            document_id=create.document_id, source_mode=create.source_mode,
            analysis_type=create.analysis_type, engine_version=create.engine_version,
            status=owner_status, result_json=payload,
            canonical_result_digest=(
                hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
                if payload is not None else None
            ),
            error_message=error_message,
            started_at=create.started_at, completed_at=create.completed_at,
        )
        self.session.add(owner)
        self.session.flush()
        for source in create.source_bindings:
            self.session.add(FinancialAnalysisResultSource(
                analysis_result_id=owner.id, company_id=command.scope.company_id,
                period_id=command.scope.period_id, source_document_id=source.source_document_id,
                source_analysis_result_id=source.source_analysis_result_id, role=source.role,
            ))
        return owner.id

    @staticmethod
    def _record_owner_payload(record):
        payload = record.result.result
        if record.engine_code in (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT):
            payload = payload.result_json
        if record.engine_code is EngineCode.RATIO and not isinstance(payload, dict):
            _fail("Financial result owner payload must be a JSON object.")
        if record.engine_code in (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT) and payload is not None and not isinstance(payload, dict):
            _fail("Financial statement owner payload must be a JSON object or null.")
        return json.loads(canonical_json_bytes(payload))

    _financial_payload = _record_owner_payload

    @staticmethod
    def _financial_owner_digest_payload(
        engine_code: EngineCode,
        owner: FinancialAnalysisResult,
        trial_balance_usage: str | None,
    ):
        if engine_code is EngineCode.RATIO:
            return owner.result_json
        return {
            "status": owner.status,
            "source_mode": owner.source_mode,
            "result_json": owner.result_json,
            "error_message": owner.error_message,
            "trial_balance_usage": trial_balance_usage,
        }

    @staticmethod
    def _record_digest_payload(record):
        if record.engine_code not in (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT):
            return SqlAlchemyOrchestrationRepository._record_owner_payload(record)
        outcome = record.result.result
        return {
            "status": outcome.status,
            "source_mode": outcome.source_mode,
            "result_json": outcome.result_json,
            "error_message": outcome.error_message,
            "trial_balance_usage": outcome.trial_balance_usage,
        }

    def persist_terminal_run(self, command: PersistTerminalRunCommand) -> PersistedRun:
        self._validate_command(command)
        result = command.run_result
        bindings = self._financial_binding_map(command)
        prepared = {}
        inline_bytes = 0
        result_digests: dict[EngineCode, str] = {}
        for record in result.engine_records:
            if record.result is None:
                continue
            ownership = RESULT_OWNERSHIP_REGISTRY[record.engine_code]
            owned_payload = (
                self._record_digest_payload(record)
                if ownership.owner is ResultOwner.FINANCIAL_ANALYSIS_RESULT
                else record.result.result
            )
            raw = canonical_json_bytes(owned_payload)
            result_digests[record.engine_code] = hashlib.sha256(raw).hexdigest()
            if RESULT_OWNERSHIP_REGISTRY[record.engine_code].owner is ResultOwner.ORCHESTRATION_ARTIFACT and record.status is not EngineExecutionStatus.REUSED:
                item = prepare_artifact(record.result.result_kind, record.result.result, current_inline_bytes=inline_bytes)
                prepared[record.engine_code] = item
                if item.inline_payload is not None:
                    inline_bytes += item.byte_size
        projection = {
            "run_id": result.run_id, "correlation_id": result.correlation_id, "generated_at": result.generated_at,
            "request_fingerprint": result.request_fingerprint, "status": result.status.value,
            "requested_outputs": [code.value for code in command.requested_outputs],
            "versions": [result.orchestration_schema_version, result.orchestration_model_version, result.execution_plan_version],
            "records": [{"engine": r.engine_code.value, "status": r.status.value, "inner": r.inner_status_value,
                         "dependencies": [d.value for d in r.dependency_engine_codes], "schema": r.engine_schema_version_used,
                         "model": r.engine_model_version_used, "input_fingerprint": r.input_fingerprint,
                         "fingerprint_schema": r.fingerprint_schema_version, "result_kind": r.result.result_kind if r.result else None,
                         "result_digest": result_digests.get(r.engine_code)} for r in result.engine_records],
            "warnings": result.warnings,
            "errors": [{"category": e.category.value, "engine": e.engine_code.value if e.engine_code else None,
                        "message": e.message_tr, "type": e.original_exception_type} for e in result.structured_errors],
            "input_versions": result.input_version_inventory,
        }
        terminal_digest = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
        existing = self.session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == result.run_id))
        if existing:
            if existing.request_fingerprint == result.request_fingerprint and existing.terminal_content_digest == terminal_digest:
                return self._project(existing)
            _fail("Run ID conflicts with an immutable terminal result.", PersistenceErrorCategory.RUN_ID_CONFLICT)
        now = datetime.now(timezone.utc)
        previous_db_id = command.resume_context.persisted_run_id if command.resume_context else None
        run = OrchestrationRun(
            run_id=result.run_id, company_id=command.scope.company_id, period_id=command.scope.period_id,
            request_fingerprint=result.request_fingerprint, terminal_content_digest=terminal_digest,
            correlation_id=result.correlation_id, generated_at=datetime.fromisoformat(result.generated_at) if result.generated_at else None,
            requested_outputs_json=[code.value for code in command.requested_outputs], warnings_json=list(result.warnings),
            input_version_inventory_json=dict(result.input_version_inventory), status=result.status.value,
            orchestration_schema_version=result.orchestration_schema_version, orchestration_model_version=result.orchestration_model_version,
            execution_plan_version=result.execution_plan_version,
            fingerprint_schema_version=result.engine_records[0].fingerprint_schema_version if result.engine_records else "1.0.0",
            previous_run_id=previous_db_id, finalized_at=now,
        )
        self.session.add(run)
        try:
            self.session.flush()
            execution_by_code = {}
            resume_bindings = {item.engine_code: item for item in command.resume_context.engine_bindings} if command.resume_context else {}
            for ordinal, record in enumerate(result.engine_records):
                artifact_id = financial_id = reused_id = None
                owner_digest = result_digests.get(record.engine_code)
                financial_trial_balance_usage = None
                if record.status is EngineExecutionStatus.REUSED:
                    source = resume_bindings.get(record.engine_code)
                    if source is None:
                        _fail("Reused execution is missing its source binding.")
                    artifact_id, financial_id, reused_id = source.artifact_id, source.financial_analysis_result_id, source.source_engine_execution_id
                    source_execution = self.session.get(OrchestrationEngineExecution, reused_id)
                    assert source_execution is not None
                    owner_digest = source_execution.owner_content_digest
                    financial_trial_balance_usage = source_execution.financial_trial_balance_usage
                elif record.result is not None and RESULT_OWNERSHIP_REGISTRY[record.engine_code].owner is ResultOwner.ORCHESTRATION_ARTIFACT:
                    item = prepared[record.engine_code]
                    physical = None
                    if item.storage_backend.value == "external_blob":
                        staged = self.blob_store.stage(f"{result.run_id}/{record.engine_code.value}", item.canonical_bytes)
                        locator = self.blob_store.verify_and_publish(staged, digest=item.content_digest, byte_size=item.byte_size)
                        physical = OrchestrationPhysicalObject(locator=locator, state="ready", content_digest=item.content_digest, byte_size=item.byte_size)
                        self.session.add(physical); self.session.flush()
                    artifact = OrchestrationArtifact(content_digest=item.content_digest, artifact_kind=item.result_kind,
                        serializer_format=SERIALIZER_FORMAT, serializer_schema_version=item.serializer_schema_version,
                        media_type="application/json", byte_size=item.byte_size, storage_backend=item.storage_backend.value,
                        inline_payload=item.inline_payload, physical_object_id=physical.id if physical else None)
                    self.session.add(artifact); self.session.flush(); artifact_id = artifact.id
                    if physical:
                        self.session.add(OrchestrationArtifactLocation(artifact_id=artifact.id, physical_object_id=physical.id, revision=1))
                elif record.result is not None:
                    binding = bindings.get(record.engine_code)
                    if binding is None:
                        _fail("Financial engine result is missing its owner binding.")
                    financial_id = self._bind_financial_owner(command, record, binding, result_digests[record.engine_code])
                    if record.engine_code in (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT):
                        financial_trial_balance_usage = record.result.result.trial_balance_usage
                execution = OrchestrationEngineExecution(run_id=run.id, engine_code=record.engine_code.value,
                    execution_ordinal=ordinal, status=record.status.value, inner_status=record.inner_status_value,
                    dependency_engine_codes_json=[code.value for code in record.dependency_engine_codes],
                    engine_schema_version=record.engine_schema_version_used, engine_model_version=record.engine_model_version_used,
                    input_fingerprint=record.input_fingerprint, fingerprint_schema_version=record.fingerprint_schema_version,
                    result_kind=record.result.result_kind if record.result else None, artifact_id=artifact_id,
                    financial_analysis_result_id=financial_id, reused_from_engine_execution_id=reused_id,
                    owner_content_digest=owner_digest,
                    financial_trial_balance_usage=financial_trial_balance_usage)
                self.session.add(execution); self.session.flush(); execution_by_code[record.engine_code] = execution
            for ordinal, error in enumerate(result.structured_errors):
                execution = execution_by_code.get(error.engine_code) if error.engine_code else None
                self.session.add(OrchestrationError(run_id=run.id, engine_execution_id=execution.id if execution else None,
                    error_ordinal=ordinal, category=error.category.value, engine_code=error.engine_code.value if error.engine_code else None,
                    message=error.message_tr, original_exception_type=error.original_exception_type))
            extra_bindings = set(bindings) - {r.engine_code for r in result.engine_records if r.result is not None}
            if extra_bindings:
                _fail("Financial owner binding supplied for an absent result.")
            self.session.commit()
            return self._project(run)
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == result.run_id))
            if existing and existing.request_fingerprint == result.request_fingerprint and existing.terminal_content_digest == terminal_digest:
                return self._project(existing)
            raise OrchestrationPersistenceError(PersistenceErrorCategory.RUN_ID_CONFLICT, "Concurrent terminal persistence conflict.") from exc
        except Exception:
            self.session.rollback()
            raise
