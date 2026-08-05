from app.engines.common.report_types import ReportSectionCode
from app.engines.executive_reports.trend_integration import integrate_trend_report_v1_2
from app.engines.executive_reports.trend_projection import project_trend_report_source_v1_2
from app.engines.multi_period_trend import canonical_trend_digest, canonical_trend_reference
from app.orchestration_persistence_v4 import SqlAlchemyTrendTerminalPersistenceV4

from test_multi_period_trend_persistence_v4_postgres import (
    _command,
    _context,
    _create_scope,
    _sources,
    trend_lineage_database,
)
from test_multi_period_trend_report_projection_unit import _base_report


def test_stored_verified_trend_snapshot_projects_to_report_without_source_recalculation(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    context = _context(scope, _sources(factory, scope))
    command = _command(scope, context)
    adapter = SqlAlchemyTrendTerminalPersistenceV4(factory)
    persisted = adapter.persist_terminal_run(command)
    loaded = adapter.build_previous_execution_snapshot(command.run_result.run_id, command.scope)
    envelope = loaded.snapshot.engine_snapshots[0].result
    trend = envelope.result
    projection = project_trend_report_source_v1_2(
        requested=True,
        result=trend,
        expected_company_id=command.scope.company_id,
        expected_anchor_period_id=command.scope.anchor_period_id,
        verified_result_digest=canonical_trend_digest(trend),
        verified_result_reference=canonical_trend_reference(trend),
    )
    report = integrate_trend_report_v1_2(_base_report(), projection)
    section = next(item for item in report.sections if item.section_code is ReportSectionCode.SEC_PERIOD_COMPARISON_ANALYSIS)
    assert persisted.trend_analysis_result_id == loaded.financial_analysis_result_id
    assert projection.trend_result_digest == canonical_trend_digest(command.run_result.engine_records[0].result.result)
    assert loaded.snapshot.engine_snapshots[0].owner_content_digest is not None
    assert any(item.source_field_path == "multi_period_trend.metrics" for item in section.content_blocks)
