"""PostgreSQL terminal adapter for V4 Trend owner/lineage/run atomicity."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.engines.analysis_orchestrator_v4.types import (
    EngineExecutionStatusV4, EngineResultEnvelopeV4, OrchestrationEngineCodeV4,
    PreviousEngineSnapshotV4, PreviousExecutionSnapshotV4, get_trend_result_v4,
)
from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1, TrendLineagePortError,
    build_trend_lineage_set,
)
from app.integrations.trend_lineage_repository import SqlAlchemyTrendLineageRepository
from app.models.company import Company
from app.models.enums import AnalysisStatus, AnalysisType, SourceMode
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.orchestration_persistence import OrchestrationEngineExecution, OrchestrationRun

from .trend_codec import (
    decode_trend_financial_result, encode_trend_financial_result,
    trend_owner_content_digest,
)
from .types import LoadedTrendSnapshotV4, PersistedTrendRunV4, PersistTerminalTrendRunCommandV4, PersistenceRunScopeV4


class PersistenceV4ErrorCode:
    CONFLICT = "conflict"
    INTEGRITY_FAILURE = "integrity_failure"
    UNAVAILABLE = "unavailable"


class PersistenceV4Error(RuntimeError):
    __slots__ = ("code",)
    def __init__(self, code: str):
        RuntimeError.__init__(self)
        self.code = code
    def __str__(self): return f"PersistenceV4Error(code={self.code})"
    __repr__ = __str__


def _terminal_digest(command: PersistTerminalTrendRunCommandV4, owner_digest: str) -> str:
    result = command.run_result
    node = (
        "orch.terminal-run.v4", result.run_id, result.request_fingerprint,
        str(command.scope.tenant_id), str(command.scope.company_id), str(command.scope.anchor_period_id),
        command.scope.initiating_subject_id, result.status.value,
        tuple(item.value for item in result.execution_provenance.engine_call_sequence),
        owner_digest, command.source_set_digest,
        result.orchestration_schema_version, result.orchestration_model_version, result.execution_plan_version,
    )
    return sha256(repr(node).encode("utf-8")).hexdigest()


def _validate_result_lineage(command: PersistTerminalTrendRunCommandV4, trend_result) -> None:
    lineage_by_source = {item.source_analysis_result_id: item for item in command.lineage}
    result_lineage_by_source = {
        item.source_result_id: item for item in trend_result.lineage_references
    }
    result_source_by_id = {
        item.source_result_id: item for item in trend_result.source_references
    }
    if not (
        len(lineage_by_source)
        == len(result_lineage_by_source)
        == len(result_source_by_id)
        == len(command.lineage)
    ):
        raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
    for source_id, edge in lineage_by_source.items():
        lineage_reference = result_lineage_by_source.get(source_id)
        source_reference = result_source_by_id.get(source_id)
        if lineage_reference is None or source_reference is None or (
            lineage_reference.ordinal,
            lineage_reference.period_id,
            lineage_reference.canonical_source_digest,
            lineage_reference.comparability_proof_digest,
            lineage_reference.lineage_schema_version,
        ) != (
            edge.ordinal,
            edge.source_period_id,
            edge.source_canonical_digest,
            edge.comparability_proof_digest,
            edge.lineage_schema_version,
        ) or (
            source_reference.company_id,
            source_reference.period_id,
            source_reference.source_engine_type.value,
            source_reference.source_schema_version,
            source_reference.source_model_version,
            source_reference.canonical_source_digest,
            source_reference.evidence,
        ) != (
            command.scope.company_id,
            edge.source_period_id,
            edge.source_role.value,
            edge.source_schema_version,
            edge.source_model_version,
            edge.source_canonical_digest,
            edge.observation_evidence,
        ):
            raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)


class SqlAlchemyTrendTerminalPersistenceV4:
    """Owns one transaction; the savepoint discards every concurrent loser write."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _run(session: Session, run_id: str):
        return session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == run_id))

    @staticmethod
    def _verify_existing(session, row, command, terminal_digest, owner_digest):
        if (
            row.request_fingerprint != command.run_result.request_fingerprint
            or row.terminal_content_digest != terminal_digest
            or (row.company_id, row.period_id) != (command.scope.company_id, command.scope.anchor_period_id)
            or (row.orchestration_schema_version, row.orchestration_model_version, row.execution_plan_version) != ("4.0.0", "4.0.0", "4.0.0")
        ):
            raise PersistenceV4Error(PersistenceV4ErrorCode.CONFLICT)
        execution = session.scalar(select(OrchestrationEngineExecution).where(
            OrchestrationEngineExecution.run_id == row.id,
            OrchestrationEngineExecution.engine_code == OrchestrationEngineCodeV4.MULTI_PERIOD_TREND.value,
        ))
        if execution is None or execution.financial_analysis_result_id is None or not hmac.compare_digest(execution.owner_content_digest or "", owner_digest):
            raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
        owner = session.get(FinancialAnalysisResult, execution.financial_analysis_result_id)
        if owner is None or owner.result_json is None or owner.canonical_result_digest is None:
            raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
        decode_trend_financial_result(owner.result_json, owner.canonical_result_digest)
        verified = SqlAlchemyTrendLineageRepository(session).load_verified_lineage(owner.id)
        if not hmac.compare_digest(verified.lineage_set.source_set_digest, command.source_set_digest):
            raise PersistenceV4Error(PersistenceV4ErrorCode.CONFLICT)
        return PersistedTrendRunV4(row.id, owner.id, owner_digest, command.source_set_digest, True)

    def persist_terminal_run(self, command: PersistTerminalTrendRunCommandV4) -> PersistedTrendRunV4:
        if type(command) is not PersistTerminalTrendRunCommandV4:
            raise TypeError("Persistence-v4 requires exact terminal command")
        trend_record = next((item for item in command.run_result.engine_records if item.engine_code is OrchestrationEngineCodeV4.MULTI_PERIOD_TREND), None)
        if trend_record is None or trend_record.result is None or trend_record.status not in {
            EngineExecutionStatusV4.COMPLETED, EngineExecutionStatusV4.DEGRADED, EngineExecutionStatusV4.REUSED,
        }:
            raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
        trend_result = get_trend_result_v4(command.run_result)
        if trend_result is None or (trend_result.company_id, trend_result.anchor_period_id) != (command.scope.company_id, command.scope.anchor_period_id):
            raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
        _validate_result_lineage(command, trend_result)
        payload, payload_digest = encode_trend_financial_result(
            trend_result, source_set_digest=command.source_set_digest,
            resolution_digest=command.resolution_digest,
            lineage_count=len(command.lineage),
            metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
            metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
            policy_version=trend_result.policy_version.value,
            contract_version=trend_result.contract_version.value,
        )
        owner_digest = trend_owner_content_digest(payload)
        terminal_digest = _terminal_digest(command, owner_digest)
        session = self._session_factory()
        try:
            with session.begin():
                company = session.scalar(select(Company).where(
                    Company.id == command.scope.company_id,
                    Company.tenant_id == command.scope.tenant_id,
                ).with_for_update())
                if company is None:
                    raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                existing = self._run(session, command.run_result.run_id)
                if existing is not None:
                    return self._verify_existing(session, existing, command, terminal_digest, owner_digest)
                try:
                    with session.begin_nested():
                        if trend_record.status is EngineExecutionStatusV4.REUSED:
                            owner = session.get(FinancialAnalysisResult, command.reused_trend_owner_id)
                            if owner is None or owner.result_json is None or owner.canonical_result_digest is None:
                                raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                            reused_value = decode_trend_financial_result(owner.result_json, owner.canonical_result_digest)
                            if reused_value.canonical_digest != trend_result.canonical_digest or not hmac.compare_digest(
                                command.reused_trend_owner_content_digest or "", owner_digest,
                            ):
                                raise PersistenceV4Error(PersistenceV4ErrorCode.CONFLICT)
                            SqlAlchemyTrendLineageRepository(session).load_verified_lineage(owner.id)
                        else:
                            owner = FinancialAnalysisResult(
                                id=uuid4(), company_id=command.scope.company_id,
                                period_id=command.scope.anchor_period_id, document_id=None,
                                source_mode=SourceMode.MULTI_SOURCE_DERIVED,
                                analysis_type=AnalysisType.MULTI_PERIOD_TREND,
                                engine_version="1.0.0", status=AnalysisStatus.COMPLETED,
                                result_json=payload, canonical_result_digest=payload_digest,
                                error_message=None, started_at=datetime.now(timezone.utc),
                                completed_at=datetime.now(timezone.utc),
                            )
                            session.add(owner)
                            session.flush()
                            lineage_set = build_trend_lineage_set(
                                trend_analysis_result_id=owner.id,
                                tenant_id=command.scope.tenant_id,
                                company_id=command.scope.company_id,
                                anchor_period_id=command.scope.anchor_period_id,
                                metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
                                metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
                                policy_version=trend_result.policy_version,
                                contract_version=trend_result.contract_version,
                                lineage=command.lineage,
                            )
                            if not hmac.compare_digest(lineage_set.source_set_digest, command.source_set_digest):
                                raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                            SqlAlchemyTrendLineageRepository(session).stage_exact_lineage(lineage_set)
                        run = OrchestrationRun(
                            run_id=command.run_result.run_id,
                            company_id=command.scope.company_id, period_id=command.scope.anchor_period_id,
                            request_fingerprint=command.run_result.request_fingerprint,
                            terminal_content_digest=terminal_digest,
                            correlation_id=command.run_result.correlation_id,
                            generated_at=datetime.fromisoformat(command.run_result.generated_at) if command.run_result.generated_at else None,
                            requested_outputs_json=[OrchestrationEngineCodeV4.MULTI_PERIOD_TREND.value],
                            warnings_json=[], input_version_inventory_json=dict(command.run_result.input_version_inventory),
                            status=command.run_result.status.value,
                            orchestration_schema_version="4.0.0", orchestration_model_version="4.0.0",
                            execution_plan_version="4.0.0", fingerprint_schema_version="4.0.0",
                            previous_run_id=None, finalized_at=datetime.now(timezone.utc),
                        )
                        session.add(run)
                        session.flush()
                except IntegrityError:
                    existing = self._run(session, command.run_result.run_id)
                    if existing is None:
                        raise
                    return self._verify_existing(session, existing, command, terminal_digest, owner_digest)
                reused_execution_id = None
                if trend_record.status is EngineExecutionStatusV4.REUSED:
                    reused_execution_id = session.scalar(select(OrchestrationEngineExecution.id).where(
                        OrchestrationEngineExecution.financial_analysis_result_id == owner.id,
                        OrchestrationEngineExecution.engine_code == OrchestrationEngineCodeV4.MULTI_PERIOD_TREND.value,
                    ).order_by(OrchestrationEngineExecution.created_at).limit(1))
                    if reused_execution_id is None:
                        raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                session.add(OrchestrationEngineExecution(
                    run_id=run.id, engine_code=OrchestrationEngineCodeV4.MULTI_PERIOD_TREND.value,
                    execution_ordinal=0, status=trend_record.status.value,
                    inner_status=trend_record.inner_status_value, dependency_engine_codes_json=[],
                    engine_schema_version=trend_record.engine_schema_version_used,
                    engine_model_version=trend_record.engine_model_version_used,
                    input_fingerprint=trend_record.input_fingerprint,
                    fingerprint_schema_version=trend_record.fingerprint_schema_version,
                    result_kind="TrendAnalysisResult", owner_content_digest=owner_digest,
                    financial_trial_balance_usage=None, artifact_id=None,
                    financial_analysis_result_id=owner.id,
                    reused_from_engine_execution_id=reused_execution_id,
                ))
                session.flush()
                return PersistedTrendRunV4(run.id, owner.id, owner_digest, command.source_set_digest, False)
        except PersistenceV4Error:
            raise
        except (TrendLineagePortError, IntegrityError):
            raise PersistenceV4Error(PersistenceV4ErrorCode.CONFLICT) from None
        except SQLAlchemyError:
            raise PersistenceV4Error(PersistenceV4ErrorCode.UNAVAILABLE) from None
        except Exception:
            raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE) from None
        finally:
            session.close()

    def build_previous_execution_snapshot(
        self, run_id: str, scope: PersistenceRunScopeV4,
    ) -> LoadedTrendSnapshotV4:
        session = self._session_factory()
        try:
            with session.begin():
                company = session.scalar(select(Company).where(
                    Company.id == scope.company_id, Company.tenant_id == scope.tenant_id,
                ).with_for_update())
                run = self._run(session, run_id)
                if company is None or run is None or (run.company_id, run.period_id) != (scope.company_id, scope.anchor_period_id):
                    raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                if (run.orchestration_schema_version, run.orchestration_model_version, run.execution_plan_version) != ("4.0.0", "4.0.0", "4.0.0"):
                    raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                execution = session.scalar(select(OrchestrationEngineExecution).where(
                    OrchestrationEngineExecution.run_id == run.id,
                    OrchestrationEngineExecution.engine_code == OrchestrationEngineCodeV4.MULTI_PERIOD_TREND.value,
                ))
                if execution is None or execution.financial_analysis_result_id is None:
                    raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                owner = session.get(FinancialAnalysisResult, execution.financial_analysis_result_id)
                if owner is None or owner.result_json is None or owner.canonical_result_digest is None:
                    raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                result = decode_trend_financial_result(owner.result_json, owner.canonical_result_digest)
                verified = SqlAlchemyTrendLineageRepository(session).load_verified_lineage(owner.id)
                owner_digest = trend_owner_content_digest(owner.result_json)
                if not hmac.compare_digest(owner_digest, execution.owner_content_digest or ""):
                    raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                resolution_digest = owner.result_json.get("resolution_digest")
                if type(resolution_digest) is not str or len(resolution_digest) != 64:
                    raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE)
                envelope = EngineResultEnvelopeV4(
                    OrchestrationEngineCodeV4.MULTI_PERIOD_TREND, "TrendAnalysisResult", result,
                )
                snapshot = PreviousExecutionSnapshotV4(
                    run.run_id, run.request_fingerprint, "4.0.0", "4.0.0", "4.0.0",
                    (PreviousEngineSnapshotV4(
                        OrchestrationEngineCodeV4.MULTI_PERIOD_TREND,
                        EngineExecutionStatusV4(execution.status),
                        execution.engine_schema_version, execution.engine_model_version,
                        execution.input_fingerprint, execution.fingerprint_schema_version,
                        envelope, owner.id, owner_digest,
                        verified.lineage_set.source_set_digest, resolution_digest,
                        owner.result_json.get("metric_registry_digest"),
                        owner.result_json.get("policy_version"), True,
                    ),),
                )
                return LoadedTrendSnapshotV4(snapshot, owner.id, owner_digest)
        except PersistenceV4Error:
            raise
        except SQLAlchemyError:
            raise PersistenceV4Error(PersistenceV4ErrorCode.UNAVAILABLE) from None
        except Exception:
            raise PersistenceV4Error(PersistenceV4ErrorCode.INTEGRITY_FAILURE) from None
        finally:
            session.close()
