"""PostgreSQL acceptance for the 4.5G V3 terminal application adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import threading
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.analysis_application.contracts import (
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
    RunScopeClaimStatus,
)
from app.analysis_application_v2.adapters.persistence import SqlAlchemyRunPersistenceAdapterV3
from app.analysis_application_v2.contracts import (
    ApplicationEngineCodeV2,
    ApplicationFinancialSourceModeV2,
    FinancialSourceIntentDTOV2,
)
from app.analysis_application_v2.ports import (
    ApplicationTerminalPersistenceRequestV3,
    ApplicationV2PortError,
    VerifiedApplicationScopeBindingV3,
)
from app.engines.analysis_orchestrator_v3.service import run_orchestration_v3
from app.engines.analysis_orchestrator_v3.types import (
    EngineRawInputsV3,
    OrchestrationEngineCodeV3,
    OrchestrationRunOptionsV3,
    OrchestrationRunRequestV3,
)
from app.engines.balance_sheet.service import BalanceSheetAnalysisOutcome
from app.engines.cash_flow import (
    CashFlowEngineOutcome,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
)
from app.engines.income_statement.service import IncomeStatementAnalysisOutcome
from app.models.cash_flow_cross_period_lineage import CashFlowCrossPeriodLineage
from app.models.company import Company
from app.models.enums import (
    AnalysisStatus,
    PeriodCoverageKind,
    PeriodStatus,
    PeriodType,
    SourceMode,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_period import FinancialPeriod
from app.models.orchestration_persistence import OrchestrationEngineExecution, OrchestrationRun
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence_v3.cash_flow_codec import decode_cash_flow_financial_result
from app.orchestration_persistence_v3.types import PersistenceRunScopeV3

from test_cash_flow_contracts_unit import COMPANY_ID, CURRENT_ID, TENANT_ID, _descriptor, _result
from test_cash_flow_lineage_repository_postgres import lineage_database


NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _scope(factory):
    with factory() as session, session.begin():
        if session.get(Company, COMPANY_ID) is not None:
            return
        session.execute(
            text("INSERT INTO security_tenants (id,tenant_key,status,policy_version,version) VALUES (:id,'cf-45g','ACTIVE',1,1)"),
            {"id": TENANT_ID},
        )
        session.add(Company(
            id=COMPANY_ID,
            tenant_id=TENANT_ID,
            legal_name="4.5G synthetic",
            tax_number=COMPANY_ID.hex,
            currency="TRY",
        ))
        session.add(FinancialPeriod(
            id=CURRENT_ID,
            company_id=COMPANY_ID,
            year=2025,
            period_type=PeriodType.MONTHLY,
            period_number=2,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 28),
            months_covered=1,
            is_year_end=False,
            status=PeriodStatus.CLOSED,
            accounting_basis_code="tr_tdhp_accrual",
            accounting_policy_version="tr_tdhp_accrual/1.0.0",
            annual_reporting_period_start_date=date(2025, 1, 1),
            annual_reporting_period_end_date=date(2025, 12, 31),
            ifrs18_early_adopted=False,
            cash_flow_coverage_kind=PeriodCoverageKind.DISCRETE,
        ))


def _statement(outcome_type):
    return outcome_type(
        AnalysisStatus.COMPLETED,
        SourceMode.MULTI_SOURCE_DERIVED,
        {"engine_version": "1.0.0", "value": "1.00"},
        None,
        None,
    )


def _request_and_context(monkeypatch, *, include_ratio=False):
    from app.engines.analysis_orchestrator_v3 import service
    from test_cash_flow_orchestration_v3_unit import _context

    context = replace(
        _context(),
        prior_period=None,
        comparability_proof_digest=None,
    )
    cash_result = _result(
        status=CashFlowResultStatus.INSUFFICIENT_DATA,
        reconciliation_status=CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
        opening=None,
        closing=None,
        operating=None,
        difference=None,
    )
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, OrchestrationEngineCodeV3.FS_BALANCE_SHEET, lambda **_: _statement(BalanceSheetAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, OrchestrationEngineCodeV3.FS_INCOME_STATEMENT, lambda **_: _statement(IncomeStatementAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, OrchestrationEngineCodeV3.CASH_FLOW, lambda **_: CashFlowEngineOutcome(cash_result.status, True, cash_result, None))
    request = OrchestrationRunRequestV3(
        run_id=f"cash-flow-v3-{uuid4()}",
        correlation_id="corr-45g",
        generated_at=NOW.isoformat(),
        requested_outputs=(
            (OrchestrationEngineCodeV3.CASH_FLOW, OrchestrationEngineCodeV3.RATIO)
            if include_ratio
            else (OrchestrationEngineCodeV3.CASH_FLOW,)
        ),
        engine_inputs=EngineRawInputsV3(cash_flow_pre_resolved_context=context),
        run_options=OrchestrationRunOptionsV3(),
    )
    result, _ = run_orchestration_v3(request)
    return result, context


def _terminal(adapter, result, context, *, include_ratio=False):
    application_scope = ApplicationScopeDTO(
        COMPANY_ID,
        CURRENT_ID,
        "cf-45g",
        ApplicationOperationKind.START,
        ApplicationOriginalOperation.START,
    )
    persistence_scope = PersistenceRunScopeV3(TENANT_ID, COMPANY_ID, CURRENT_ID)
    verified = VerifiedApplicationScopeBindingV3(
        result.run_id,
        application_scope,
        persistence_scope,
        "subject-45g",
        "a" * 64,
        uuid4(),
        1,
        RunScopeClaimStatus.CLAIMED,
    )
    intents = tuple(
        FinancialSourceIntentDTOV2(
            code,
            COMPANY_ID,
            CURRENT_ID,
            None,
            (),
            ApplicationFinancialSourceModeV2.MULTI_SOURCE_DERIVED,
            False,
            None,
            {},
            None,
        )
        for code in (
            ApplicationEngineCodeV2.FS_BALANCE_SHEET,
            ApplicationEngineCodeV2.FS_INCOME_STATEMENT,
            *(
                (ApplicationEngineCodeV2.RATIO,)
                if include_ratio
                else ()
            ),
        )
    )
    plan = adapter.resolve_financial_ownership_plan(
        result,
        intents,
        object(),
        context,
        verified,
        NOW,
        NOW,
    )
    return ApplicationTerminalPersistenceRequestV3(
        verified,
        result,
        (
            (ApplicationEngineCodeV2.CASH_FLOW, ApplicationEngineCodeV2.RATIO)
            if include_ratio
            else (ApplicationEngineCodeV2.CASH_FLOW,)
        ),
        None,
        plan,
        None,
    )


def test_v3_terminal_owner_lineage_replay_and_snapshot_are_atomic(
    lineage_database, tmp_path, monkeypatch,
):
    _engine, factory = lineage_database
    _scope(factory)
    run_result, context = _request_and_context(monkeypatch)

    with factory() as session:
        adapter = SqlAlchemyRunPersistenceAdapterV3(session, FilesystemBlobStore(tmp_path / "blobs"))
        command = _terminal(adapter, run_result, context)
        first = adapter.persist_terminal_run(command)
        assert first.idempotent_replay is False

    with factory() as session:
        adapter = SqlAlchemyRunPersistenceAdapterV3(session, FilesystemBlobStore(tmp_path / "blobs"))
        replay = adapter.persist_terminal_run(command)
        assert replay.idempotent_replay is True
        envelopes = adapter.resolve_payload_references(
            run_result.run_id, command.verified_scope, include_payloads=True,
        )
        cash_envelope = next(item for item in envelopes if item.payload_kind.value == "cash_flow")
        assert cash_envelope.cash_flow_projection.status.value == "insufficient_data"
        assert cash_envelope.payload_reference.artifact_serializer_schema_version is None
        snapshot = adapter.build_previous_execution_snapshot(
            run_result.run_id,
            PersistenceRunScopeV3(TENANT_ID, COMPANY_ID, CURRENT_ID),
        )
        cash = next(item for item in snapshot.snapshot.engine_snapshots if item.engine_code is OrchestrationEngineCodeV3.CASH_FLOW)
        assert cash.result.result.status is CashFlowResultStatus.INSUFFICIENT_DATA

    with factory() as session:
        run = session.scalar(select(OrchestrationRun).where(OrchestrationRun.run_id == run_result.run_id))
        executions = tuple(session.scalars(select(OrchestrationEngineExecution).where(OrchestrationEngineExecution.run_id == run.id)))
        owners = tuple(session.scalars(select(FinancialAnalysisResult).where(
            FinancialAnalysisResult.company_id == COMPANY_ID,
            FinancialAnalysisResult.period_id == CURRENT_ID,
        )))
        cash_owner = next(item for item in owners if item.analysis_type.value == "cash_flow")
        assert len(executions) == 3
        assert len(owners) == 3
        assert not tuple(session.scalars(select(CashFlowCrossPeriodLineage).where(
            CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == cash_owner.id
        )))
        decoded = decode_cash_flow_financial_result(cash_owner.result_json, cash_owner.canonical_result_digest)
        assert decoded.status is CashFlowResultStatus.INSUFFICIENT_DATA

    with factory() as session:
        adapter = SqlAlchemyRunPersistenceAdapterV3(session, FilesystemBlobStore(tmp_path / "blobs"))
        conflicting = replace(
            command,
            run_result=replace(command.run_result, request_fingerprint="f" * 64),
        )
        with pytest.raises(ApplicationV2PortError):
            adapter.persist_terminal_run(conflicting)

    concurrent_result, concurrent_context = _request_and_context(monkeypatch)
    with factory() as session:
        adapter = SqlAlchemyRunPersistenceAdapterV3(session, FilesystemBlobStore(tmp_path / "blobs"))
        concurrent_command = _terminal(adapter, concurrent_result, concurrent_context)
    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        try:
            with factory() as session:
                adapter = SqlAlchemyRunPersistenceAdapterV3(session, FilesystemBlobStore(tmp_path / "blobs"))
                barrier.wait(timeout=5)
                outcomes.append(adapter.persist_terminal_run(concurrent_command).idempotent_replay)
        except Exception as error:  # pragma: no cover - asserted below
            outcomes.append(error)

    threads = (threading.Thread(target=worker), threading.Thread(target=worker))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(outcomes) == [False, True]
    with factory() as session:
        concurrent_run = session.scalar(select(OrchestrationRun).where(
            OrchestrationRun.run_id == concurrent_result.run_id
        ))
        concurrent_executions = tuple(session.scalars(select(OrchestrationEngineExecution).where(
            OrchestrationEngineExecution.run_id == concurrent_run.id
        )))
        owner_ids = {item.financial_analysis_result_id for item in concurrent_executions}
        assert len(owner_ids) == 3
        assert session.scalar(select(text("count(*)")).select_from(FinancialAnalysisResult).where(
            FinancialAnalysisResult.id.in_(owner_ids)
        )) == 3

