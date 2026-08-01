import dataclasses
import uuid
from datetime import date

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineExecutionStatus,
    ExecutionProvenance,
    OrchestrationRunResult,
    PerEngineExecutionRecord,
    RunStatus,
)
from app.models.company import Company
from app.models.enums import PeriodStatus, PeriodType
from app.models.financial_period import FinancialPeriod
from app.models.orchestration_persistence import OrchestrationRun
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.errors import OrchestrationPersistenceError
from app.orchestration_persistence.repository import SqlAlchemyOrchestrationRepository
from app.orchestration_persistence.types import PersistTerminalRunCommand, PersistenceRunScope


def _command(scope, run_id):
    fingerprint = "a" * 64
    record = PerEngineExecutionRecord(
        engine_code=EngineCode.FS_BALANCE_SHEET,
        status=EngineExecutionStatus.FAILED,
        result=None,
        inner_status_value=None,
        error=None,
        dependency_engine_codes=(),
        engine_schema_version_used="1.0.0",
        engine_model_version_used="1.0.0",
        input_fingerprint="b" * 64,
        fingerprint_schema_version="1.0.0",
    )
    result = OrchestrationRunResult(
        run_id=run_id,
        correlation_id=None,
        generated_at=None,
        status=RunStatus.FAILED,
        engine_records=(record,),
        warnings=(),
        structured_errors=(),
        execution_provenance=ExecutionProvenance("2.0.0", (EngineCode.FS_BALANCE_SHEET,), (), ()),
        input_version_inventory={},
        orchestration_schema_version="2.0.0",
        orchestration_model_version="2.0.0",
        execution_plan_version="2.0.0",
        request_fingerprint=fingerprint,
    )
    return PersistTerminalRunCommand(scope, result, (EngineCode.FS_BALANCE_SHEET,))


def test_postgres_idempotency_conflict_and_immutability(tmp_path):
    session = SessionLocal()
    marker = uuid.uuid4().hex
    company = Company(legal_name="5.0B Test", tax_number=marker, currency="TRY")
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
    session.commit()
    scope = PersistenceRunScope(company.id, period.id)
    repository = SqlAlchemyOrchestrationRepository(session, FilesystemBlobStore(tmp_path))
    command = _command(scope, f"run-{marker}")
    first = repository.persist_terminal_run(command)
    second = repository.persist_terminal_run(command)
    assert first == second
    page = repository.list_run_history(scope, None, 1)
    assert page.items[0].id == first.id
    conflicting = dataclasses.replace(command, run_result=dataclasses.replace(command.run_result, status=RunStatus.CANCELLED))
    with pytest.raises(OrchestrationPersistenceError):
        repository.persist_terminal_run(conflicting)
    with pytest.raises(DBAPIError):
        session.execute(update(OrchestrationRun).where(OrchestrationRun.id == first.id).values(status="cancelled"))
        session.commit()
    session.rollback()
    session.close()
