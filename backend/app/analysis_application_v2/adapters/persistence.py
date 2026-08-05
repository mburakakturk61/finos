"""SQLAlchemy adapter for the additive Application-v2 / Orchestrator-v3 path."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import hmac
import json
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.engines.analysis_orchestrator_v3.execution_plan import EXECUTION_PLAN_V3
from app.engines.analysis_orchestrator_v3.registry import ENGINE_DEPENDENCY_REGISTRY_V3
from app.engines.analysis_orchestrator_v3.types import (
    EngineExecutionStatusV3,
    EngineResultEnvelopeV3,
    FinancialAnalysisStatusV3,
    FinancialSourceModeV3,
    OrchestrationEngineCodeV3,
    OrchestrationJsonObjectV3,
    PreviousEngineSnapshotV3,
    PreviousExecutionSnapshotV3,
)
from app.engines.cash_flow.contracts import CashFlowResult
from app.engines.cash_flow.lineage import ResolvedCashFlowLineageEdge
from app.engines.cash_flow.lineage import CashFlowPortError
from app.engines.cash_flow.types import CashFlowSourceRole
from app.integrations.cash_flow_lineage_repository import SqlAlchemyCashFlowLineageRepository
from app.models.company import Company
from app.models.cash_flow_cross_period_lineage import CashFlowCrossPeriodLineage
from app.models.enums import AnalysisStatus, AnalysisType, SourceMode
from app.analysis_application.contracts import (
    ExecutionCategory,
    FinancialComputationStatus,
    PayloadOwnerType,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_revision_metadata import FinancialAnalysisResultRevisionMetadata
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
from app.orchestration_persistence.codec import (
    SERIALIZER_FORMAT,
    canonical_json_bytes,
    decode_artifact,
)
from app.orchestration_persistence_v3.cash_flow_codec import (
    cash_flow_owner_content_digest,
    decode_cash_flow_financial_result,
    encode_cash_flow_financial_result,
)
from app.orchestration_persistence_v3.types import (
    PersistedRunV3,
    PersistenceRunScopeV3,
    ResumeEngineBindingV3,
    ResumePersistenceContextV3,
    SnapshotLoadResultV3,
)

from ..contracts import (
    ApplicationCashFlowErrorCodeV2,
    ApplicationEngineCodeV2,
    ApplicationFinancialSourceModeV2,
    ApplicationPayloadEnvelopeDTOV2,
    ApplicationPayloadKindV2,
    ApplicationPayloadReferenceDTOV2,
    ApplicationProjectedErrorDTOV2,
    FinancialSourceIntentDTOV2,
)
from ..ownership import resolve_financial_ownership_plan_v3
from ..projection import project_cash_flow_result_v2
from ..ports import (
    ApplicationTerminalPersistenceRequestV3,
    ApplicationV2PortError,
    ApplicationV2PortErrorCode,
    ResolvedFinancialOwnershipPlanV3,
    TerminalPersistenceResultV3,
    VerifiedApplicationScopeBindingV3,
)


_FINANCIAL_TYPES = {
    OrchestrationEngineCodeV3.FS_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    OrchestrationEngineCodeV3.FS_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    OrchestrationEngineCodeV3.CASH_FLOW: AnalysisType.CASH_FLOW,
    OrchestrationEngineCodeV3.RATIO: AnalysisType.FINANCIAL_RATIOS,
}
_ALIVE = {
    EngineExecutionStatusV3.COMPLETED,
    EngineExecutionStatusV3.DEGRADED,
    EngineExecutionStatusV3.REUSED,
}


def _fail(code: ApplicationV2PortErrorCode) -> None:
    raise ApplicationV2PortError(code)


def _plain(value):
    if type(value) is OrchestrationJsonObjectV3:
        return {key: _plain(item) for key, item in value.items}
    if type(value) is tuple:
        return [_plain(item) for item in value]
    return value


def _v3_object(value) -> OrchestrationJsonObjectV3:
    if type(value) is OrchestrationJsonObjectV3:
        return value
    if type(value) is not dict:
        raise ValueError("V3 object payload is invalid")
    return OrchestrationJsonObjectV3(tuple(
        (key, _v3_object(item) if type(item) is dict else tuple(
            _v3_object(child) if type(child) is dict else child for child in item
        ) if type(item) is list else item)
        for key, item in sorted(value.items())
    ))


def _terminal_node(value):
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is Decimal:
        return {"$type": "decimal", "value": str(value)}
    if type(value) is UUID:
        return {"$type": "uuid", "value": str(value)}
    if type(value) is date:
        return {"$type": "date", "value": value.isoformat()}
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("terminal semantic datetime must be timezone-aware")
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, Enum):
        return {"$type": "enum", "value": value.value}
    if type(value) in {tuple, list}:
        return [_terminal_node(item) for item in value]
    if type(value) is dict:
        return {str(key): _terminal_node(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "$type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [[field.name, _terminal_node(getattr(value, field.name))] for field in fields(value)],
        }
    raise TypeError("unsupported V3 terminal semantic value")


def _terminal_bytes(value) -> bytes:
    return json.dumps(
        _terminal_node(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _financial_payload(record):
    value = record.result.result
    if record.engine_code in {
        OrchestrationEngineCodeV3.FS_BALANCE_SHEET,
        OrchestrationEngineCodeV3.FS_INCOME_STATEMENT,
    }:
        return _plain(value.result_json) if value.result_json is not None else None
    if record.engine_code is OrchestrationEngineCodeV3.CASH_FLOW:
        return encode_cash_flow_financial_result(value)[0]
    if record.engine_code is OrchestrationEngineCodeV3.RATIO:
        return _plain(value)
    raise ValueError("artifact engine has no financial payload")


def _owner_content_digest(record, owner: FinancialAnalysisResult) -> str:
    if record.engine_code is OrchestrationEngineCodeV3.RATIO:
        projection = owner.result_json
    else:
        usage = (
            record.result.result.trial_balance_usage
            if record.engine_code in {
                OrchestrationEngineCodeV3.FS_BALANCE_SHEET,
                OrchestrationEngineCodeV3.FS_INCOME_STATEMENT,
            }
            else None
        )
        projection = {
            "status": owner.status,
            "source_mode": owner.source_mode,
            "result_json": owner.result_json,
            "error_message": owner.error_message,
            "trial_balance_usage": usage,
        }
    return sha256(canonical_json_bytes(projection)).hexdigest()


class SqlAlchemyRunPersistenceAdapterV3:
    """Own one terminal transaction; never downcast to the frozen V1 ports."""

    def __init__(self, session: Session, blob_store: FilesystemBlobStore) -> None:
        self.session = session
        self.blob_store = blob_store
        self.lineage = SqlAlchemyCashFlowLineageRepository(session)

    def resolve_financial_ownership_plan(
        self,
        run_result,
        source_intents: tuple[FinancialSourceIntentDTOV2, ...],
        cash_flow_request,
        pre_resolved_context,
        verified_scope: VerifiedApplicationScopeBindingV3,
        started_at: datetime,
        completed_at: datetime,
    ) -> ResolvedFinancialOwnershipPlanV3:
        if cash_flow_request is None and pre_resolved_context is not None:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        return resolve_financial_ownership_plan_v3(
            run_result,
            source_intents,
            pre_resolved_context,
            started_at=started_at,
            completed_at=completed_at,
        )

    def persist_terminal_run(
        self, request: ApplicationTerminalPersistenceRequestV3,
    ) -> TerminalPersistenceResultV3:
        if type(request) is not ApplicationTerminalPersistenceRequestV3:
            raise TypeError("V3 persistence rejects legacy/duck-typed commands")
        try:
            self._set_timeouts()
            self._validate_request(request)
            company = self.session.execute(
                select(Company).where(Company.id == request.verified_scope.persistence_scope.company_id).with_for_update()
            ).scalar_one_or_none()
            if company is None or company.tenant_id != request.verified_scope.persistence_scope.tenant_id:
                _fail(ApplicationV2PortErrorCode.SCOPE_MISMATCH)
            prepared, owner_digests = self._prepare_payloads(request)
            terminal_digest = self._terminal_digest(request, owner_digests)
            existing = self._run_row(request.run_result.run_id)
            if existing is not None:
                persisted = self._verify_idempotent(existing, request, terminal_digest)
                self.session.commit()
                return TerminalPersistenceResultV3(persisted, True)

            savepoint = self.session.begin_nested()
            try:
                owner_ids = self._stage_financial_owners(request)
                run = self._stage_run(request, terminal_digest)
                self.session.flush()
            except IntegrityError:
                savepoint.rollback()
                existing = self._run_row(request.run_result.run_id)
                if existing is None:
                    raise
                persisted = self._verify_idempotent(existing, request, terminal_digest)
                self.session.commit()
                return TerminalPersistenceResultV3(persisted, True)
            else:
                savepoint.commit()

            self._stage_executions_and_errors(request, run, owner_ids, prepared, owner_digests)
            self.session.commit()
            return TerminalPersistenceResultV3(self._project(run, request.verified_scope.persistence_scope), False)
        except (ApplicationV2PortError, CashFlowPortError):
            self.session.rollback()
            raise
        except IntegrityError:
            self.session.rollback()
            _fail(ApplicationV2PortErrorCode.CONFLICT)
        except (DBAPIError, SQLAlchemyError):
            self.session.rollback()
            _fail(ApplicationV2PortErrorCode.UNAVAILABLE)
        except Exception:
            self.session.rollback()
            _fail(ApplicationV2PortErrorCode.INTEGRITY)

    def _set_timeouts(self) -> None:
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self.session.execute(text("SELECT set_config('statement_timeout', '5000ms', true)"))
            self.session.execute(text("SELECT set_config('lock_timeout', '1000ms', true)"))

    def _validate_request(self, request) -> None:
        result = request.run_result
        scope = request.verified_scope
        if scope.run_id != result.run_id or scope.scope.company_id != scope.persistence_scope.company_id or scope.scope.financial_period_id != scope.persistence_scope.period_id:
            _fail(ApplicationV2PortErrorCode.SCOPE_MISMATCH)
        if (result.orchestration_schema_version, result.orchestration_model_version, result.execution_plan_version) != ("3.0.0", "3.0.0", "3.0.0"):
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        if len(result.request_fingerprint) != 64 or not request.requested_outputs:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        requested = tuple(OrchestrationEngineCodeV3(item.value) for item in request.requested_outputs)
        required = set(requested)
        changed = True
        while changed:
            changed = False
            for code in tuple(required):
                dependency = ENGINE_DEPENDENCY_REGISTRY_V3[code].dependency
                for item in dependency.all_of + dependency.any_of:
                    if item not in required:
                        required.add(item)
                        changed = True
        expected = tuple(code for code in EXECUTION_PLAN_V3 if code in required)
        if tuple(item.engine_code for item in result.engine_records) != expected:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        records_with_financial_result = {
            ApplicationEngineCodeV2(item.engine_code.value)
            for item in result.engine_records
            if item.engine_code in _FINANCIAL_TYPES and item.result is not None and item.status in _ALIVE
        }
        planned = tuple(item.engine_code for item in request.financial_ownership_plan.nodes)
        if len(planned) != len(set(planned)) or set(planned) != records_with_financial_result:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        expected_order = tuple(ApplicationEngineCodeV2(item.value) for item in OrchestrationEngineCodeV3 if item in _FINANCIAL_TYPES)
        if planned != tuple(item for item in expected_order if item in set(planned)):
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        if request.resume_context is not None and request.resume_context.scope != scope.persistence_scope:
            _fail(ApplicationV2PortErrorCode.SCOPE_MISMATCH)

    def _prepare_payloads(self, request):
        plan = {OrchestrationEngineCodeV3(item.engine_code.value): item for item in request.financial_ownership_plan.nodes}
        prepared = {}
        digests = {}
        inline_bytes = 0
        for record in request.run_result.engine_records:
            if record.result is None:
                if record.status in _ALIVE:
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                continue
            if record.engine_code in _FINANCIAL_TYPES:
                node = plan.get(record.engine_code)
                if node is None:
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                digests[record.engine_code] = node.expected_owner_content_digest
            else:
                artifact = prepare_artifact(
                    record.result.result_kind,
                    record.result.result,
                    current_inline_bytes=inline_bytes,
                )
                prepared[record.engine_code] = artifact
                digests[record.engine_code] = artifact.content_digest
                if artifact.inline_payload is not None:
                    inline_bytes += artifact.byte_size
        return prepared, digests

    def _terminal_digest(self, request, owner_digests) -> str:
        result = request.run_result
        projection = {
            "contract": "orch.terminal_run.v3",
            "run_id": result.run_id,
            "correlation_id": result.correlation_id,
            "generated_at": result.generated_at,
            "request_fingerprint": result.request_fingerprint,
            "scope": request.verified_scope.persistence_scope,
            "previous_run": request.resume_context.previous_run_id if request.resume_context else None,
            "status": result.status,
            "requested_outputs": request.requested_outputs,
            "versions": (result.orchestration_schema_version, result.orchestration_model_version, result.execution_plan_version),
            "records": tuple({
                "engine_code": record.engine_code,
                "status": record.status,
                "inner_status": record.inner_status_value,
                "dependencies": record.dependency_engine_codes,
                "schema": record.engine_schema_version_used,
                "model": record.engine_model_version_used,
                "input_fingerprint": record.input_fingerprint,
                "fingerprint_schema": record.fingerprint_schema_version,
                "result_kind": record.result.result_kind if record.result else None,
                "owner_content_digest": owner_digests.get(record.engine_code),
                "error": record.error,
            } for record in result.engine_records),
            "warnings": result.warnings,
            "errors": result.structured_errors,
            "provenance": result.execution_provenance,
            "input_versions": result.input_version_inventory,
            "financial_owner_semantics": request.financial_ownership_plan.nodes,
        }
        return sha256(_terminal_bytes(projection)).hexdigest()

    def _stage_financial_owners(self, request) -> dict[OrchestrationEngineCodeV3, object]:
        records = {item.engine_code: item for item in request.run_result.engine_records}
        resume = {item.engine_code: item for item in request.resume_context.engine_bindings} if request.resume_context else {}
        owner_ids = {}
        for node in request.financial_ownership_plan.nodes:
            code = OrchestrationEngineCodeV3(node.engine_code.value)
            record = records[code]
            if record.status is EngineExecutionStatusV3.REUSED:
                binding = resume.get(code)
                if binding is None or binding.financial_analysis_result_id is None:
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                owner = self._verify_existing_owner(binding.financial_analysis_result_id, request, record, node)
                if binding.owner_content_digest != node.expected_owner_content_digest:
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                owner_ids[code] = owner.id
                continue
            if node.expected_existing_owner_id is not None:
                owner = self._verify_existing_owner(node.expected_existing_owner_id, request, record, node)
                owner_ids[code] = owner.id
                continue
            owner = self._create_owner(request, record, node)
            owner_ids[code] = owner.id
            if code is OrchestrationEngineCodeV3.CASH_FLOW:
                self._stage_cash_flow_lineage(request, record, node, owner_ids)
            else:
                self._stage_same_period_lineage(request, owner.id, node, owner_ids)
        return owner_ids

    def _create_owner(self, request, record, node) -> FinancialAnalysisResult:
        value = record.result.result
        payload = _financial_payload(record)
        if record.engine_code in {
            OrchestrationEngineCodeV3.FS_BALANCE_SHEET,
            OrchestrationEngineCodeV3.FS_INCOME_STATEMENT,
        }:
            status = AnalysisStatus(value.status.value)
            source_mode = SourceMode(value.source_mode.value)
            error_message = value.error_message
        elif record.engine_code is OrchestrationEngineCodeV3.CASH_FLOW:
            if type(value) is not CashFlowResult or node.primary_document_id is not None:
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
            status, source_mode, error_message = AnalysisStatus.COMPLETED, SourceMode.MULTI_SOURCE_DERIVED, None
        else:
            status, source_mode, error_message = AnalysisStatus.COMPLETED, SourceMode(node.source_mode.value), None
        canonical_digest = sha256(canonical_json_bytes(payload)).hexdigest() if payload is not None else None
        if canonical_digest != node.expected_canonical_result_digest:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        owner = FinancialAnalysisResult(
            company_id=request.verified_scope.persistence_scope.company_id,
            period_id=request.verified_scope.persistence_scope.period_id,
            document_id=node.primary_document_id,
            source_mode=source_mode,
            analysis_type=_FINANCIAL_TYPES[record.engine_code],
            engine_version=record.engine_model_version_used,
            status=status,
            result_json=payload,
            canonical_result_digest=canonical_digest,
            error_message=error_message,
            started_at=request.financial_ownership_plan.started_at,
            completed_at=request.financial_ownership_plan.completed_at,
        )
        self.session.add(owner)
        self.session.flush()
        self.session.add(FinancialAnalysisResultRevisionMetadata(
            analysis_result_id=owner.id,
            tenant_id=request.verified_scope.persistence_scope.tenant_id,
            company_id=request.verified_scope.persistence_scope.company_id,
            period_id=request.verified_scope.persistence_scope.period_id,
            restatement_state="ORIGINAL",
            restatement_revision=0,
            restatement_reason="NONE",
            supersedes_analysis_result_id=None,
            metadata_schema_version="1.0.0",
        ))
        if not hmac.compare_digest(_owner_content_digest(record, owner), node.expected_owner_content_digest):
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        return owner

    def _verify_existing_owner(self, owner_id, request, record, node):
        owner = self.session.get(FinancialAnalysisResult, owner_id)
        scope = request.verified_scope.persistence_scope
        if owner is None or (owner.company_id, owner.period_id, owner.analysis_type) != (scope.company_id, scope.period_id, _FINANCIAL_TYPES[record.engine_code]):
            _fail(ApplicationV2PortErrorCode.SCOPE_MISMATCH)
        payload_digest = sha256(canonical_json_bytes(owner.result_json)).hexdigest() if owner.result_json is not None else None
        if payload_digest != owner.canonical_result_digest or payload_digest != node.expected_canonical_result_digest:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        if record.engine_code is OrchestrationEngineCodeV3.CASH_FLOW:
            result = decode_cash_flow_financial_result(owner.result_json, owner.canonical_result_digest)
            if cash_flow_owner_content_digest(result) != node.expected_owner_content_digest:
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
        elif _owner_content_digest(record, owner) != node.expected_owner_content_digest:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        return owner

    def _stage_same_period_lineage(self, request, owner_id, node, owner_ids) -> None:
        scope = request.verified_scope.persistence_scope
        for edge in node.same_period_lineage_plan:
            source_id = edge.existing_source_analysis_result_id
            if edge.same_run_source_engine_code is not None:
                source_id = owner_ids.get(OrchestrationEngineCodeV3(edge.same_run_source_engine_code.value))
                if source_id is None:
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
            self.session.add(FinancialAnalysisResultSource(
                analysis_result_id=owner_id,
                company_id=scope.company_id,
                period_id=scope.period_id,
                source_document_id=edge.source_document_id,
                source_analysis_result_id=source_id,
                role=edge.role,
            ))
        self.session.flush()

    def _stage_cash_flow_lineage(self, request, record, node, owner_ids) -> None:
        result = record.result.result
        scope = request.verified_scope.persistence_scope
        edges = []
        for edge in node.cash_flow_lineage_plan:
            source_id = edge.existing_source_analysis_result_id
            if edge.same_run_source_engine_code is not None:
                source_id = owner_ids.get(OrchestrationEngineCodeV3(edge.same_run_source_engine_code.value))
            if source_id is None:
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
            edges.append(ResolvedCashFlowLineageEdge(
                edge.source_role,
                source_id,
                edge.source_period_id,
                edge.source_canonical_digest,
                edge.source_provenance_digest,
                edge.source_analysis_type,
                edge.source_engine_version,
                edge.current_period_descriptor_digest,
                edge.prior_period_descriptor_digest,
                edge.comparability_proof_digest,
            ))
        self.lineage.stage_exact_lineage(
            cash_flow_owner_id=owner_ids[OrchestrationEngineCodeV3.CASH_FLOW],
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            current_period_id=scope.period_id,
            prior_period_id=result.prior_period_id,
            cash_flow_status=result.status,
            lineage=tuple(edges),
        )

    def _stage_run(self, request, terminal_digest):
        result, scope = request.run_result, request.verified_scope.persistence_scope
        previous_id = request.resume_context.persisted_run_id if request.resume_context else None
        if request.resume_context is not None:
            previous = self.session.get(OrchestrationRun, previous_id)
            if previous is None or previous.run_id != request.resume_context.previous_run_id or (previous.company_id, previous.period_id) != (scope.company_id, scope.period_id):
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
        run = OrchestrationRun(
            run_id=result.run_id,
            company_id=scope.company_id,
            period_id=scope.period_id,
            request_fingerprint=result.request_fingerprint,
            terminal_content_digest=terminal_digest,
            correlation_id=result.correlation_id,
            generated_at=datetime.fromisoformat(result.generated_at) if result.generated_at else None,
            requested_outputs_json=[item.value for item in request.requested_outputs],
            warnings_json=[_plain(item) for item in result.warnings],
            input_version_inventory_json=_plain(result.input_version_inventory),
            status=result.status.value,
            orchestration_schema_version=result.orchestration_schema_version,
            orchestration_model_version=result.orchestration_model_version,
            execution_plan_version=result.execution_plan_version,
            fingerprint_schema_version=result.engine_records[0].fingerprint_schema_version if result.engine_records else "1.0.0",
            previous_run_id=previous_id,
            finalized_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        return run

    def _stage_executions_and_errors(self, request, run, owner_ids, prepared, owner_digests):
        resume = {item.engine_code: item for item in request.resume_context.engine_bindings} if request.resume_context else {}
        executions = {}
        for ordinal, record in enumerate(request.run_result.engine_records):
            artifact_id = financial_id = reused_id = None
            usage = None
            if record.status is EngineExecutionStatusV3.REUSED:
                binding = resume.get(record.engine_code)
                if binding is None:
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                artifact_id, financial_id, reused_id = binding.artifact_id, binding.financial_analysis_result_id, binding.source_engine_execution_id
                source = self.session.get(OrchestrationEngineExecution, reused_id)
                if source is None or (source.engine_code, source.input_fingerprint, source.engine_schema_version, source.engine_model_version, source.owner_content_digest) != (
                    record.engine_code.value, record.input_fingerprint, record.engine_schema_version_used, record.engine_model_version_used, binding.owner_content_digest,
                ):
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                usage = source.financial_trial_balance_usage
            elif record.result is not None and record.engine_code in _FINANCIAL_TYPES:
                financial_id = owner_ids[record.engine_code]
                if record.engine_code in {OrchestrationEngineCodeV3.FS_BALANCE_SHEET, OrchestrationEngineCodeV3.FS_INCOME_STATEMENT}:
                    usage = record.result.result.trial_balance_usage
            elif record.result is not None:
                item = prepared[record.engine_code]
                physical = None
                if item.storage_backend.value == "external_blob":
                    staged = self.blob_store.stage(f"{request.run_result.run_id}/{record.engine_code.value}", item.canonical_bytes)
                    locator = self.blob_store.verify_and_publish(staged, digest=item.content_digest, byte_size=item.byte_size)
                    physical = OrchestrationPhysicalObject(locator=locator, state="ready", content_digest=item.content_digest, byte_size=item.byte_size)
                    self.session.add(physical)
                    self.session.flush()
                artifact = OrchestrationArtifact(
                    content_digest=item.content_digest,
                    artifact_kind=item.result_kind,
                    serializer_format=SERIALIZER_FORMAT,
                    serializer_schema_version=item.serializer_schema_version,
                    media_type="application/json",
                    byte_size=item.byte_size,
                    storage_backend=item.storage_backend.value,
                    inline_payload=item.inline_payload,
                    physical_object_id=physical.id if physical else None,
                )
                self.session.add(artifact)
                self.session.flush()
                artifact_id = artifact.id
                if physical:
                    self.session.add(OrchestrationArtifactLocation(artifact_id=artifact.id, physical_object_id=physical.id, revision=1))
            execution = OrchestrationEngineExecution(
                run_id=run.id,
                engine_code=record.engine_code.value,
                execution_ordinal=ordinal,
                status=record.status.value,
                inner_status=record.inner_status_value,
                dependency_engine_codes_json=[item.value for item in record.dependency_engine_codes],
                engine_schema_version=record.engine_schema_version_used,
                engine_model_version=record.engine_model_version_used,
                input_fingerprint=record.input_fingerprint,
                fingerprint_schema_version=record.fingerprint_schema_version,
                result_kind=record.result.result_kind if record.result else None,
                owner_content_digest=owner_digests.get(record.engine_code),
                financial_trial_balance_usage=usage,
                artifact_id=artifact_id,
                financial_analysis_result_id=financial_id,
                reused_from_engine_execution_id=reused_id,
            )
            self.session.add(execution)
            self.session.flush()
            executions[record.engine_code] = execution
        for ordinal, error in enumerate(request.run_result.structured_errors):
            execution = executions.get(error.engine_code)
            is_cash = error.cash_flow_error_code is not None
            self.session.add(OrchestrationError(
                run_id=run.id,
                engine_execution_id=execution.id if execution else None,
                error_ordinal=ordinal,
                category=error.category.value,
                engine_code=error.engine_code.value if error.engine_code else None,
                message=error.message_tr,
                original_exception_type=error.original_exception_type,
                cash_flow_error_code=error.cash_flow_error_code.value if is_cash else None,
                safe_metadata_json=_plain(error.safe_metadata) if is_cash else None,
                error_retryable=error.retryable if is_cash else None,
            ))
        self.session.flush()

    def _run_row(self, run_id):
        return self.session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == run_id))

    def _verify_idempotent(self, row, request, terminal_digest):
        scope = request.verified_scope.persistence_scope
        if (
            row.request_fingerprint != request.run_result.request_fingerprint
            or row.terminal_content_digest != terminal_digest
            or (row.company_id, row.period_id) != (scope.company_id, scope.period_id)
            or (row.orchestration_schema_version, row.orchestration_model_version, row.execution_plan_version) != ("3.0.0", "3.0.0", "3.0.0")
        ):
            _fail(ApplicationV2PortErrorCode.CONFLICT)
        return self._project(row, scope)

    @staticmethod
    def _project(row, scope):
        return PersistedRunV3(row.id, row.run_id, row.request_fingerprint, row.terminal_content_digest, scope, row.finalized_at, row.orchestration_schema_version)

    def build_previous_execution_snapshot(self, run_id: str, target_scope: PersistenceRunScopeV3) -> SnapshotLoadResultV3:
        try:
            run = self._run_row(run_id)
            if run is None:
                _fail(ApplicationV2PortErrorCode.NOT_FOUND)
            company = self.session.execute(
                select(Company).where(Company.id == target_scope.company_id).with_for_update()
            ).scalar_one_or_none()
            if company is None or company.tenant_id != target_scope.tenant_id or (run.company_id, run.period_id) != (target_scope.company_id, target_scope.period_id):
                _fail(ApplicationV2PortErrorCode.SCOPE_MISMATCH)
            if (run.orchestration_schema_version, run.orchestration_model_version, run.execution_plan_version) != ("3.0.0", "3.0.0", "3.0.0"):
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
            executions = tuple(self.session.scalars(select(OrchestrationEngineExecution).where(
                OrchestrationEngineExecution.run_id == run.id
            ).order_by(OrchestrationEngineExecution.execution_ordinal)))
            snapshots, bindings = [], []
            for execution in executions:
                code = OrchestrationEngineCodeV3(execution.engine_code)
                value = None
                financial_digest = None
                if execution.financial_analysis_result_id is not None:
                    value, financial_digest = self._load_financial_snapshot(execution, code, target_scope)
                elif execution.artifact_id is not None:
                    value = self._load_artifact_snapshot(execution)
                elif execution.status in {item.value for item in _ALIVE}:
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                envelope = EngineResultEnvelopeV3(code, execution.result_kind, value) if value is not None else None
                snapshots.append(PreviousEngineSnapshotV3(
                    code,
                    EngineExecutionStatusV3(execution.status),
                    execution.engine_schema_version,
                    execution.engine_model_version,
                    execution.input_fingerprint,
                    execution.fingerprint_schema_version,
                    envelope,
                ))
                bindings.append(ResumeEngineBindingV3(
                    code,
                    execution.id,
                    execution.artifact_id,
                    execution.financial_analysis_result_id,
                    execution.owner_content_digest,
                    financial_digest,
                    execution.input_fingerprint,
                    execution.engine_schema_version,
                    execution.engine_model_version,
                ))
            snapshot = PreviousExecutionSnapshotV3(
                run.run_id, run.request_fingerprint, run.orchestration_schema_version,
                run.orchestration_model_version, run.execution_plan_version, tuple(snapshots),
            )
            context = ResumePersistenceContextV3(run.id, run.run_id, target_scope, tuple(bindings))
            return SnapshotLoadResultV3(snapshot, context)
        except ApplicationV2PortError:
            raise
        except (DBAPIError, SQLAlchemyError):
            _fail(ApplicationV2PortErrorCode.UNAVAILABLE)
        except Exception:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)

    def _load_financial_snapshot(self, execution, code, scope):
        owner = self.session.get(FinancialAnalysisResult, execution.financial_analysis_result_id)
        if owner is None or (owner.company_id, owner.period_id, owner.analysis_type) != (scope.company_id, scope.period_id, _FINANCIAL_TYPES[code]):
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        payload_digest = sha256(canonical_json_bytes(owner.result_json)).hexdigest() if owner.result_json is not None else None
        if payload_digest != owner.canonical_result_digest:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        if code is OrchestrationEngineCodeV3.CASH_FLOW:
            value = decode_cash_flow_financial_result(owner.result_json, owner.canonical_result_digest)
            if cash_flow_owner_content_digest(value) != execution.owner_content_digest:
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
            rows = tuple(self.session.scalars(
                select(CashFlowCrossPeriodLineage)
                .where(CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == owner.id)
                .order_by(CashFlowCrossPeriodLineage.source_role)
            ))
            edges = tuple(ResolvedCashFlowLineageEdge(
                source_role=CashFlowSourceRole(row.source_role),
                source_analysis_result_id=row.source_analysis_result_id,
                source_period_id=row.source_period_id,
                source_canonical_digest=row.source_canonical_digest,
                source_provenance_digest=row.source_provenance_digest,
                source_analysis_type=AnalysisType(row.source_analysis_type),
                source_engine_version=row.source_engine_version,
                current_period_descriptor_digest=row.current_period_descriptor_digest,
                prior_period_descriptor_digest=row.prior_period_descriptor_digest,
                comparability_proof_digest=row.comparability_proof_digest,
            ) for row in rows)
            verified_edges = self.lineage._source_edges(
                owner, scope.tenant_id, scope.company_id, scope.period_id,
                value.prior_period_id, value.status, edges,
            )
            references = {item.source_role: item for item in value.source_lineage_references}
            if set(references) != {item.source_role for item in verified_edges}:
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
            for edge in verified_edges:
                reference = references[edge.source_role]
                if (
                    reference.source_period_id != edge.source_period_id
                    or reference.canonical_digest != edge.source_canonical_digest
                    or reference.source_provenance_digest != edge.source_provenance_digest
                ):
                    _fail(ApplicationV2PortErrorCode.INTEGRITY)
                if reference.source_analysis_result_id is not None:
                    if reference.source_analysis_result_id != edge.source_analysis_result_id:
                        _fail(ApplicationV2PortErrorCode.INTEGRITY)
                else:
                    source_execution = self.session.scalar(select(OrchestrationEngineExecution).where(
                        OrchestrationEngineExecution.run_id == execution.run_id,
                        OrchestrationEngineExecution.financial_analysis_result_id == edge.source_analysis_result_id,
                    ))
                    if source_execution is None or source_execution.engine_code != reference.same_run_engine_code:
                        _fail(ApplicationV2PortErrorCode.INTEGRITY)
            return value, payload_digest
        if code is OrchestrationEngineCodeV3.RATIO:
            value = _v3_object(owner.result_json)
        else:
            cls = __import__("app.engines.analysis_orchestrator_v3.types", fromlist=[
                "BalanceSheetAnalysisOutcomeV3" if code is OrchestrationEngineCodeV3.FS_BALANCE_SHEET else "IncomeStatementAnalysisOutcomeV3"
            ])
            outcome_type = getattr(cls, "BalanceSheetAnalysisOutcomeV3" if code is OrchestrationEngineCodeV3.FS_BALANCE_SHEET else "IncomeStatementAnalysisOutcomeV3")
            value = outcome_type(
                FinancialAnalysisStatusV3(owner.status.value),
                FinancialSourceModeV3(owner.source_mode.value) if owner.source_mode else None,
                _v3_object(owner.result_json) if owner.result_json is not None else None,
                owner.error_message,
                execution.financial_trial_balance_usage,
            )
        envelope = type("Record", (), {"engine_code": code, "result": type("Envelope", (), {"result": value})()})()
        if _owner_content_digest(envelope, owner) != execution.owner_content_digest:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        return value, payload_digest

    def _load_artifact_snapshot(self, execution):
        artifact = self.session.get(OrchestrationArtifact, execution.artifact_id)
        if artifact is None or execution.owner_content_digest != artifact.content_digest:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
        if artifact.inline_payload is not None:
            raw = canonical_json_bytes(artifact.inline_payload)
        else:
            physical = self.session.get(OrchestrationPhysicalObject, artifact.physical_object_id)
            if physical is None or physical.state != "ready":
                _fail(ApplicationV2PortErrorCode.INTEGRITY)
            raw = self.blob_store.read_ready(physical.locator)
        value = decode_artifact(artifact.artifact_kind, raw, artifact.content_digest, artifact.serializer_schema_version)
        if artifact.artifact_kind == "dict" and type(value) is dict and set(value) == {"items"}:
            value = _v3_object(dict(value["items"]))
        return value

    def resolve_payload_references(self, run_id, verified_scope, *, include_payloads):
        try:
            run = self._run_row(run_id)
            scope = verified_scope.persistence_scope
            if run is None:
                _fail(ApplicationV2PortErrorCode.NOT_FOUND)
            company = self.session.get(Company, scope.company_id)
            if company is None or company.tenant_id != scope.tenant_id or (run.company_id, run.period_id) != (scope.company_id, scope.period_id):
                _fail(ApplicationV2PortErrorCode.SCOPE_MISMATCH)
            executions = tuple(self.session.scalars(
                select(OrchestrationEngineExecution)
                .where(OrchestrationEngineExecution.run_id == run.id)
                .order_by(OrchestrationEngineExecution.execution_ordinal)
            ))
            owner_by_engine = {
                item.engine_code: item.financial_analysis_result_id
                for item in executions if item.financial_analysis_result_id is not None
            }
            envelopes = []
            for execution in executions:
                if execution.financial_analysis_result_id is None and execution.artifact_id is None:
                    continue
                code = OrchestrationEngineCodeV3(execution.engine_code)
                error_row = self.session.scalar(
                    select(OrchestrationError)
                    .where(OrchestrationError.engine_execution_id == execution.id)
                    .order_by(OrchestrationError.error_ordinal)
                    .limit(1)
                )
                projected_error = None
                if error_row is not None:
                    projected_error = ApplicationProjectedErrorDTOV2(
                        ExecutionCategory(error_row.category),
                        ApplicationEngineCodeV2(error_row.engine_code) if error_row.engine_code else None,
                        ApplicationCashFlowErrorCodeV2(error_row.cash_flow_error_code) if error_row.cash_flow_error_code else None,
                        error_row.message,
                        bool(error_row.error_retryable),
                        error_row.safe_metadata_json or {},
                    )
                if execution.financial_analysis_result_id is not None:
                    owner = self.session.get(FinancialAnalysisResult, execution.financial_analysis_result_id)
                    if owner is None:
                        _fail(ApplicationV2PortErrorCode.INTEGRITY)
                    payload_kind = ApplicationPayloadKindV2.CASH_FLOW if code is OrchestrationEngineCodeV3.CASH_FLOW else ApplicationPayloadKindV2.GENERIC_FINANCIAL
                    reference = ApplicationPayloadReferenceDTOV2(
                        PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT,
                        execution.result_kind,
                        execution.owner_content_digest,
                        owner.id,
                        None,
                        None,
                    )
                    generic = cash_projection = None
                    if include_payloads:
                        if code is OrchestrationEngineCodeV3.CASH_FLOW:
                            result, _digest = self._load_financial_snapshot(execution, code, scope)
                            cash_projection = project_cash_flow_result_v2(
                                result,
                                same_run_owner=lambda engine_code: owner_by_engine[engine_code],
                            )
                        else:
                            generic = owner.result_json if owner.result_json is not None else {}
                    same_period = tuple(str(item) for item in self.session.scalars(
                        select(FinancialAnalysisResultSource.source_analysis_result_id)
                        .where(
                            FinancialAnalysisResultSource.analysis_result_id == owner.id,
                            FinancialAnalysisResultSource.source_analysis_result_id.is_not(None),
                        )
                        .order_by(FinancialAnalysisResultSource.role)
                    ))
                    cross_period = tuple(str(item) for item in self.session.scalars(
                        select(CashFlowCrossPeriodLineage.source_analysis_result_id)
                        .where(CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == owner.id)
                        .order_by(CashFlowCrossPeriodLineage.source_role)
                    )) if code is OrchestrationEngineCodeV3.CASH_FLOW else ()
                    envelopes.append(ApplicationPayloadEnvelopeDTOV2(
                        reference,
                        FinancialComputationStatus(owner.status.value),
                        ApplicationFinancialSourceModeV2(owner.source_mode.value),
                        payload_kind,
                        include_payloads,
                        generic,
                        cash_projection,
                        projected_error,
                        owner.error_message,
                        execution.inner_status,
                        execution.financial_trial_balance_usage,
                        same_period + cross_period,
                        execution.engine_schema_version,
                        execution.engine_model_version,
                    ))
                else:
                    artifact = self.session.get(OrchestrationArtifact, execution.artifact_id)
                    if artifact is None or artifact.content_digest != execution.owner_content_digest:
                        _fail(ApplicationV2PortErrorCode.INTEGRITY)
                    generic = None
                    if include_payloads:
                        value = self._load_artifact_snapshot(execution)
                        generic = json.loads(canonical_json_bytes(value))
                    envelopes.append(ApplicationPayloadEnvelopeDTOV2(
                        ApplicationPayloadReferenceDTOV2(
                            PayloadOwnerType.ORCHESTRATION_ARTIFACT,
                            execution.result_kind,
                            artifact.content_digest,
                            None,
                            artifact.id,
                            artifact.serializer_schema_version,
                        ),
                        FinancialComputationStatus.COMPLETED,
                        None,
                        ApplicationPayloadKindV2.ARTIFACT,
                        include_payloads,
                        generic,
                        None,
                        projected_error,
                        None,
                        execution.inner_status,
                        None,
                        (),
                        execution.engine_schema_version,
                        execution.engine_model_version,
                    ))
            return tuple(envelopes)
        except ApplicationV2PortError:
            raise
        except (DBAPIError, SQLAlchemyError):
            _fail(ApplicationV2PortErrorCode.UNAVAILABLE)
        except Exception:
            _fail(ApplicationV2PortErrorCode.INTEGRITY)
