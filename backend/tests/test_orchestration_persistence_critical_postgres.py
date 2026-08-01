import dataclasses
import hashlib
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.session import SessionLocal
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineExecutionStatus,
    EngineResultEnvelope,
    ExecutionProvenance,
    OrchestrationRunResult,
    PerEngineExecutionRecord,
    RunStatus,
)
from app.engines.balance_sheet.service import BalanceSheetAnalysisOutcome
from app.models.company import Company
from app.models.enums import (
    AnalysisSourceRole,
    AnalysisStatus,
    AnalysisType,
    PeriodStatus,
    PeriodType,
    SourceMode,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.financial_period import FinancialPeriod
from app.models.orchestration_persistence import (
    OrchestrationArtifact,
    OrchestrationEngineExecution,
    OrchestrationError,
    OrchestrationPhysicalObject,
    OrchestrationRun,
)
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.codec import canonical_json_bytes
from app.orchestration_persistence.errors import OrchestrationPersistenceError, PersistenceErrorCategory
from app.orchestration_persistence.repository import SqlAlchemyOrchestrationRepository
from app.orchestration_persistence.snapshot import SqlAlchemySnapshotBuilder
from app.orchestration_persistence.types import (
    PersistTerminalRunCommand,
    PersistenceRunScope,
    ResumeEngineBinding,
    ResumePersistenceContext,
)

FP = "a" * 64
INPUT_FP = "b" * 64


def _scope(session):
    marker = uuid.uuid4().hex
    company = Company(legal_name="Persistence Test", tax_number=marker, currency="TRY")
    session.add(company)
    session.flush()
    period = FinancialPeriod(
        company_id=company.id,
        year=2026,
        period_type=PeriodType.YEAR_END,
        period_number=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        months_covered=12,
        is_year_end=True,
        status=PeriodStatus.DRAFT,
    )
    session.add(period)
    session.flush()
    return PersistenceRunScope(company.id, period.id)


def _run(session, scope, *, previous_id=None, status="fully_completed"):
    row = OrchestrationRun(
        run_id=f"run-{uuid.uuid4().hex}", company_id=scope.company_id, period_id=scope.period_id,
        request_fingerprint=FP, terminal_content_digest="c" * 64, correlation_id=None,
        generated_at=None, requested_outputs_json=[EngineCode.FS_BALANCE_SHEET.value],
        warnings_json=[], input_version_inventory_json={}, status=status,
        orchestration_schema_version="2.0.0", orchestration_model_version="2.0.0",
        execution_plan_version="2.0.0", fingerprint_schema_version="1.0.0",
        previous_run_id=previous_id, finalized_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def _financial_source(session, scope, *, previous_id=None, trial_balance_usage=None):
    run = _run(session, scope, previous_id=previous_id)
    payload = {"engine": "balance_sheet", "engine_version": "1.0.0", "facts": {"cash": "10"}}
    source_mode = (
        SourceMode.TRIAL_BALANCE_DERIVED
        if trial_balance_usage == "fallback_source"
        else SourceMode.MULTI_SOURCE_DERIVED
    )
    owner = FinancialAnalysisResult(
        company_id=scope.company_id, period_id=scope.period_id, document_id=None,
        source_mode=source_mode, analysis_type=AnalysisType.BALANCE_SHEET,
        engine_version="1.0.0", status=AnalysisStatus.COMPLETED, result_json=payload,
        error_message=None, started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
    )
    session.add(owner)
    session.flush()
    if trial_balance_usage == "fallback_source":
        trial_owner = FinancialAnalysisResult(
            company_id=scope.company_id, period_id=scope.period_id, document_id=None,
            source_mode=SourceMode.MULTI_SOURCE_DERIVED, analysis_type=AnalysisType.TRIAL_BALANCE,
            engine_version="1.0.0", status=AnalysisStatus.COMPLETED, result_json={"trial": True},
            error_message=None, started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
        )
        session.add(trial_owner)
        session.flush()
        session.add(FinancialAnalysisResultSource(
            analysis_result_id=owner.id, company_id=scope.company_id, period_id=scope.period_id,
            source_document_id=None, source_analysis_result_id=trial_owner.id,
            role=AnalysisSourceRole.TRIAL_BALANCE_FALLBACK,
        ))
    outcome = BalanceSheetAnalysisOutcome(
        AnalysisStatus.COMPLETED, source_mode, payload, None, trial_balance_usage
    )
    digest_payload = {
        "status": outcome.status, "source_mode": outcome.source_mode,
        "result_json": outcome.result_json, "error_message": outcome.error_message,
        "trial_balance_usage": outcome.trial_balance_usage,
    }
    digest = hashlib.sha256(canonical_json_bytes(digest_payload)).hexdigest()
    execution = OrchestrationEngineExecution(
        run_id=run.id, engine_code=EngineCode.FS_BALANCE_SHEET.value, execution_ordinal=0,
        status=EngineExecutionStatus.COMPLETED.value, inner_status=AnalysisStatus.COMPLETED.value,
        dependency_engine_codes_json=[], engine_schema_version=None, engine_model_version="1.0.0",
        input_fingerprint=INPUT_FP, fingerprint_schema_version="1.0.0",
        result_kind="BalanceSheetAnalysisOutcome", owner_content_digest=digest,
        financial_trial_balance_usage=trial_balance_usage, artifact_id=None,
        financial_analysis_result_id=owner.id, reused_from_engine_execution_id=None,
    )
    session.add(execution)
    session.flush()
    return run, owner, execution, outcome, digest


def _resume_command(scope, source_run, execution, outcome, digest, *, run_id=None):
    record = PerEngineExecutionRecord(
        EngineCode.FS_BALANCE_SHEET, EngineExecutionStatus.REUSED,
        EngineResultEnvelope(EngineCode.FS_BALANCE_SHEET, "BalanceSheetAnalysisOutcome", outcome),
        None, None, (), None, "1.0.0", INPUT_FP, "1.0.0",
    )
    result = OrchestrationRunResult(
        run_id or f"resume-{uuid.uuid4().hex}", None, None, RunStatus.FULLY_COMPLETED,
        (record,), (), (), ExecutionProvenance("2.0.0", (EngineCode.FS_BALANCE_SHEET,), (EngineCode.FS_BALANCE_SHEET,), ()),
        {}, "2.0.0", "2.0.0", "2.0.0", "d" * 64,
    )
    binding = ResumeEngineBinding(
        EngineCode.FS_BALANCE_SHEET, execution.id, execution.artifact_id,
        execution.financial_analysis_result_id, digest,
    )
    context = ResumePersistenceContext(source_run.id, source_run.run_id, scope, (binding,))
    return PersistTerminalRunCommand(scope, result, (EngineCode.FS_BALANCE_SHEET,), context)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda binding: dataclasses.replace(binding, source_engine_execution_id=uuid.uuid4()),
        lambda binding: dataclasses.replace(binding, artifact_id=uuid.uuid4()),
        lambda binding: dataclasses.replace(binding, financial_analysis_result_id=uuid.uuid4()),
        lambda binding: dataclasses.replace(binding, canonical_digest="e" * 64),
        lambda binding: dataclasses.replace(binding, financial_analysis_result_id=None),
    ),
    ids=("spoofed-binding", "wrong-artifact-owner", "wrong-financial-owner", "digest-corruption", "missing-owner"),
)
def test_resume_owner_binding_is_fail_closed_postgres(tmp_path, mutation):
    session = SessionLocal()
    scope = _scope(session)
    source_run, _owner, execution, outcome, digest = _financial_source(session, scope)
    session.commit()
    command = _resume_command(scope, source_run, execution, outcome, digest)
    bad_binding = mutation(command.resume_context.engine_bindings[0])
    command = dataclasses.replace(
        command,
        resume_context=dataclasses.replace(command.resume_context, engine_bindings=(bad_binding,)),
    )
    repository = SqlAlchemyOrchestrationRepository(session, FilesystemBlobStore(tmp_path))
    with pytest.raises(OrchestrationPersistenceError) as caught:
        repository.persist_terminal_run(command)
    assert caught.value.category in {
        PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE,
        PersistenceErrorCategory.PERSISTENCE_INVARIANT_VIOLATION,
    }
    session.close()


def test_financial_snapshot_preserves_5_0a_semantics_and_detects_owner_corruption(tmp_path):
    session = SessionLocal()
    scope = _scope(session)
    source_run, owner, _execution, outcome, _digest = _financial_source(
        session, scope, trial_balance_usage="fallback_source"
    )
    session.commit()
    builder = SqlAlchemySnapshotBuilder(session, FilesystemBlobStore(tmp_path))
    loaded = builder.build_previous_execution_snapshot(source_run.run_id, scope)
    restored = loaded.snapshot.engine_snapshots[0].result_ref
    assert restored == outcome
    owner.result_json = {"tampered": True}
    session.commit()
    with pytest.raises(OrchestrationPersistenceError) as caught:
        builder.build_previous_execution_snapshot(source_run.run_id, scope)
    assert caught.value.category is PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE
    session.close()


def test_wrong_artifact_owner_binding_is_rejected_postgres(tmp_path):
    session = SessionLocal()
    scope = _scope(session)
    source_run = _run(session, scope)
    payload = {"benchmark": "canonical"}
    raw = canonical_json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    artifact = OrchestrationArtifact(
        content_digest=digest, artifact_kind="dict", serializer_format="canonical_json",
        serializer_schema_version="1.0.0", media_type="application/json", byte_size=len(raw),
        storage_backend="inline_jsonb", inline_payload=payload, physical_object_id=None,
    )
    session.add(artifact)
    session.flush()
    source_execution = OrchestrationEngineExecution(
        run_id=source_run.id, engine_code=EngineCode.BENCHMARK.value, execution_ordinal=0,
        status=EngineExecutionStatus.COMPLETED.value, inner_status="evaluated",
        dependency_engine_codes_json=[EngineCode.RATIO.value], engine_schema_version=None,
        engine_model_version="1.0.0", input_fingerprint=INPUT_FP,
        fingerprint_schema_version="1.0.0", result_kind="dict", owner_content_digest=digest,
        financial_trial_balance_usage=None, artifact_id=artifact.id,
        financial_analysis_result_id=None, reused_from_engine_execution_id=None,
    )
    session.add(source_execution)
    session.commit()
    failed_records = tuple(
        PerEngineExecutionRecord(
            code, EngineExecutionStatus.FAILED, None, None, None, (), None, None,
            chr(98 + index) * 64, "1.0.0",
        )
        for index, code in enumerate(
            (EngineCode.FS_BALANCE_SHEET, EngineCode.FS_INCOME_STATEMENT, EngineCode.RATIO)
        )
    )
    benchmark_record = PerEngineExecutionRecord(
        EngineCode.BENCHMARK, EngineExecutionStatus.REUSED,
        EngineResultEnvelope(EngineCode.BENCHMARK, "dict", payload), None, None,
        (EngineCode.RATIO,), None, "1.0.0", INPUT_FP, "1.0.0",
    )
    result = OrchestrationRunResult(
        f"resume-{uuid.uuid4().hex}", None, None, RunStatus.PARTIALLY_COMPLETED,
        failed_records + (benchmark_record,), (), (),
        ExecutionProvenance("2.0.0", (EngineCode.BENCHMARK,), (EngineCode.BENCHMARK,), ()),
        {}, "2.0.0", "2.0.0", "2.0.0", "d" * 64,
    )
    binding = ResumeEngineBinding(
        EngineCode.BENCHMARK, source_execution.id, uuid.uuid4(), None, digest
    )
    command = PersistTerminalRunCommand(
        scope, result, (EngineCode.BENCHMARK,),
        ResumePersistenceContext(source_run.id, source_run.run_id, scope, (binding,)),
    )
    repository = SqlAlchemyOrchestrationRepository(session, FilesystemBlobStore(tmp_path))
    with pytest.raises(OrchestrationPersistenceError) as caught:
        repository.persist_terminal_run(command)
    assert caught.value.category is PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE
    session.close()


def test_same_run_id_different_request_fingerprint_is_rejected(tmp_path):
    session = SessionLocal()
    scope = _scope(session)
    source_run, _owner, execution, outcome, digest = _financial_source(session, scope)
    session.commit()
    repository = SqlAlchemyOrchestrationRepository(session, FilesystemBlobStore(tmp_path))
    command = _resume_command(scope, source_run, execution, outcome, digest)
    repository.persist_terminal_run(command)
    conflicting = dataclasses.replace(
        command,
        run_result=dataclasses.replace(command.run_result, request_fingerprint="f" * 64),
    )
    with pytest.raises(OrchestrationPersistenceError) as caught:
        repository.persist_terminal_run(conflicting)
    assert caught.value.category is PersistenceErrorCategory.RUN_ID_CONFLICT
    session.close()


def test_transitive_reuse_corruption_and_invalid_resume_chain_are_rejected(tmp_path):
    session = SessionLocal()
    scope = _scope(session)
    first_run, owner, first_execution, outcome, digest = _financial_source(session, scope)
    second_run = _run(session, scope, previous_id=first_run.id)
    second_execution = OrchestrationEngineExecution(
        run_id=second_run.id, engine_code=EngineCode.FS_BALANCE_SHEET.value, execution_ordinal=0,
        status=EngineExecutionStatus.REUSED.value, inner_status=None, dependency_engine_codes_json=[],
        engine_schema_version=None, engine_model_version="1.0.0", input_fingerprint=INPUT_FP,
        fingerprint_schema_version="1.0.0", result_kind="BalanceSheetAnalysisOutcome",
        owner_content_digest=digest, financial_trial_balance_usage=None, artifact_id=None,
        financial_analysis_result_id=owner.id, reused_from_engine_execution_id=first_execution.id,
    )
    session.add(second_execution)
    session.commit()
    repository = SqlAlchemyOrchestrationRepository(session, FilesystemBlobStore(tmp_path))
    corrupted = _resume_command(scope, second_run, second_execution, outcome, "e" * 64)
    with pytest.raises(OrchestrationPersistenceError):
        repository.persist_terminal_run(corrupted)
    invalid = _resume_command(scope, first_run, first_execution, outcome, digest, run_id=first_run.run_id)
    with pytest.raises(OrchestrationPersistenceError):
        repository.persist_terminal_run(invalid)
    session.close()


def test_all_canonical_tables_reject_real_update_and_delete(tmp_path):
    session = SessionLocal()
    scope = _scope(session)
    run, _owner, execution, _outcome, _digest = _financial_source(session, scope)
    error = OrchestrationError(
        run_id=run.id, engine_execution_id=execution.id, error_ordinal=0,
        category="engine_contract_violation", engine_code=EngineCode.FS_BALANCE_SHEET.value,
        message="safe", original_exception_type="ValueError",
    )
    artifact = OrchestrationArtifact(
        content_digest=hashlib.sha256(b"{}").hexdigest(), artifact_kind="dict",
        serializer_format="canonical_json", serializer_schema_version="1.0.0",
        media_type="application/json", byte_size=2, storage_backend="inline_jsonb",
        inline_payload={}, physical_object_id=None,
    )
    physical = OrchestrationPhysicalObject(
        locator=f"ready/{uuid.uuid4().hex}", state="ready", content_digest="a" * 64, byte_size=0,
    )
    session.add_all((error, artifact, physical))
    session.commit()
    targets = (
        (OrchestrationRun, run.id, {"status": "failed"}),
        (OrchestrationEngineExecution, execution.id, {"inner_status": "changed"}),
        (OrchestrationError, error.id, {"message": "changed"}),
        (OrchestrationArtifact, artifact.id, {"media_type": "text/plain"}),
        (OrchestrationPhysicalObject, physical.id, {"state": "quarantined"}),
    )
    for model, row_id, values in targets:
        with pytest.raises(DBAPIError):
            session.execute(update(model).where(model.id == row_id).values(**values))
            session.commit()
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(delete(model).where(model.id == row_id))
            session.commit()
        session.rollback()
    session.close()


def test_owner_status_engine_and_reuse_constraints_reject_invalid_rows():
    session = SessionLocal()
    scope = _scope(session)
    run = _run(session, scope, status="failed")
    artifact = OrchestrationArtifact(
        content_digest="a" * 64, artifact_kind="dict", serializer_format="canonical_json",
        serializer_schema_version="1.0.0", media_type="application/json", byte_size=2,
        storage_backend="inline_jsonb", inline_payload={}, physical_object_id=None,
    )
    owner = FinancialAnalysisResult(
        company_id=scope.company_id, period_id=scope.period_id, document_id=None,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED, analysis_type=AnalysisType.BALANCE_SHEET,
        engine_version="1.0.0", status=AnalysisStatus.COMPLETED, result_json={}, error_message=None,
        started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
    )
    session.add_all((artifact, owner))
    session.commit()
    base = dict(
        run_id=run.id, execution_ordinal=0, inner_status=None, dependency_engine_codes_json=[],
        engine_schema_version=None, engine_model_version="1.0.0", input_fingerprint=INPUT_FP,
        fingerprint_schema_version="1.0.0", result_kind=None,
        owner_content_digest=None, financial_trial_balance_usage=None,
        artifact_id=None, financial_analysis_result_id=None, reused_from_engine_execution_id=None,
    )
    invalid_rows = (
        dict(base, engine_code=EngineCode.FS_BALANCE_SHEET.value, status="invalid"),
        dict(base, engine_code="unknown_engine", status=EngineExecutionStatus.FAILED.value),
        dict(base, engine_code=EngineCode.FS_BALANCE_SHEET.value, status=EngineExecutionStatus.COMPLETED.value,
             result_kind="BalanceSheetAnalysisOutcome", owner_content_digest="a" * 64,
             artifact_id=artifact.id, financial_analysis_result_id=owner.id),
        dict(base, engine_code=EngineCode.FS_BALANCE_SHEET.value, status=EngineExecutionStatus.REUSED.value,
             result_kind="BalanceSheetAnalysisOutcome", owner_content_digest="a" * 64,
             financial_analysis_result_id=owner.id, reused_from_engine_execution_id=None),
    )
    for values in invalid_rows:
        session.add(OrchestrationEngineExecution(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    session.close()


def test_cursor_second_page_is_stable(tmp_path):
    session = SessionLocal()
    scope = _scope(session)
    for _ in range(3):
        _run(session, scope, status="failed")
    session.commit()
    repository = SqlAlchemyOrchestrationRepository(session, FilesystemBlobStore(tmp_path))
    first = repository.list_run_history(scope, None, 2)
    second = repository.list_run_history(scope, first.next_cursor, 2)
    assert len(first.items) == 2
    assert len(second.items) == 1
    assert {item.id for item in first.items}.isdisjoint(item.id for item in second.items)
    assert second.next_cursor is None
    session.close()
