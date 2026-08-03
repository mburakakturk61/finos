"""PostgreSQL acceptance for automatic Cash Flow -> Ratio owner lineage."""

from sqlalchemy import select

from app.analysis_application_v2.adapters.persistence import SqlAlchemyRunPersistenceAdapterV3
from app.models.enums import AnalysisSourceRole
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.orchestration_persistence import OrchestrationEngineExecution, OrchestrationRun
from app.orchestration_persistence.blob import FilesystemBlobStore

from test_cash_flow_application_persistence_v3_postgres import (
    _request_and_context,
    _scope,
    _terminal,
)
from test_cash_flow_lineage_repository_postgres import lineage_database


def test_ratio_owner_gets_exact_same_run_cash_flow_supporting_lineage(
    lineage_database, tmp_path, monkeypatch,
):
    _engine, factory = lineage_database
    _scope(factory)
    run_result, context = _request_and_context(monkeypatch, include_ratio=True)

    with factory() as session:
        adapter = SqlAlchemyRunPersistenceAdapterV3(
            session, FilesystemBlobStore(tmp_path / "ratio-lineage-blobs")
        )
        command = _terminal(adapter, run_result, context, include_ratio=True)
        adapter.persist_terminal_run(command)

    with factory() as session:
        run = session.scalar(select(OrchestrationRun).where(
            OrchestrationRun.run_id == run_result.run_id
        ))
        executions = tuple(session.scalars(select(OrchestrationEngineExecution).where(
            OrchestrationEngineExecution.run_id == run.id
        )))
        owner_ids = {
            item.financial_analysis_result_id
            for item in executions
            if item.financial_analysis_result_id is not None
        }
        owners = tuple(session.scalars(select(FinancialAnalysisResult).where(
            FinancialAnalysisResult.id.in_(owner_ids)
        )))
        cash_owner = next(item for item in owners if item.analysis_type.value == "cash_flow")
        ratio_owner = next(item for item in owners if item.analysis_type.value == "financial_ratios")
        edges = tuple(session.scalars(select(FinancialAnalysisResultSource).where(
            FinancialAnalysisResultSource.analysis_result_id == ratio_owner.id,
            FinancialAnalysisResultSource.source_analysis_result_id == cash_owner.id,
        )))
        assert len(edges) == 1
        assert edges[0].role is AnalysisSourceRole.SUPPORTING_ANALYSIS
