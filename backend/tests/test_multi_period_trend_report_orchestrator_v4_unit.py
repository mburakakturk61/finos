from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from app.engines.analysis_orchestrator_v3.types import OrchestrationEngineCodeV3 as E3
from app.engines.analysis_orchestrator_v4 import (
    ENGINE_DEPENDENCY_REGISTRY_V4,
    EXECUTION_PLAN_V4,
    FINGERPRINT_SCHEMA_VERSION_V4,
    ORCHESTRATOR_ENGINE_DISPATCH_V4,
    EngineExecutionStatusV4,
    EngineRawInputsV4,
    OrchestrationEngineCodeV4 as E,
    OrchestrationRunOptionsV4,
    OrchestrationRunRequestV4,
    PreviousEngineSnapshotV4,
    PreviousExecutionSnapshotV4,
    build_trend_pre_resolved_context_v1,
    compute_engine_input_fingerprint_v4,
    run_orchestration_v4,
)
from app.engines.balance_sheet.service import BalanceSheetAnalysisOutcome
from app.engines.common.report_types import ExecutiveReportResult, ReportSectionCode, ReportType
from app.engines.executive_reports.trend_integration import (
    REPORT_MODEL_VERSION_V1_2_TREND,
    REPORT_SCHEMA_VERSION_V1_2_TREND,
    canonical_report_presentation_digest_v1_2,
    generate_executive_report_v1_2,
)
from app.engines.income_statement.service import IncomeStatementAnalysisOutcome
from app.engines.multi_period_trend import canonical_trend_digest
from app.models.enums import AnalysisStatus, SourceMode

from test_multi_period_trend_orchestrator_v4_unit import _profile
from test_multi_period_trend_pairwise_unit import resolved_series
from test_report_pipeline_unit import _build_upstream, _cm
from test_render_contract_unit import _FULL_RENDER_CONTRACT


def _context(values=(100, 110, 121, 133, 146)):
    series = resolved_series(tuple(Decimal(str(item)) for item in values))
    return build_trend_pre_resolved_context_v1(
        resolved_series=(series,),
        comparability_profile=_profile(),
        expected_metric_codes=(series.metric_code,),
    )


def _request(ctx=None, snapshot=None, *, render=False):
    outputs = (E.MULTI_PERIOD_TREND, E.RENDER_CONTRACT) if render else (E.MULTI_PERIOD_TREND, E.EXECUTIVE_REPORT)
    return OrchestrationRunRequestV4(
        "trend-report-run",
        "trend-report-correlation",
        "2026-08-05T12:00:00+00:00",
        outputs,
        EngineRawInputsV4(trend_pre_resolved_context=ctx or _context()),
        OrchestrationRunOptionsV4(
            report_type=ReportType.CFO_EXECUTIVE_REPORT,
            company_metadata=_cm(),
            reporting_period_label_tr="2025",
            render_contract=_FULL_RENDER_CONTRACT if render else None,
        ),
        snapshot,
    )


def _patch_legacy_pipeline(monkeypatch):
    from app.engines.analysis_orchestrator_v3 import service as legacy_service

    balance, income, ratio, benchmark, health, credit, recommendation = _build_upstream()

    def canonical(value):
        if type(value) is float:
            return Decimal(str(value))
        if type(value) is dict:
            return {key: canonical(item) for key, item in value.items()}
        if type(value) is list:
            return [canonical(item) for item in value]
        return value

    balance, income, ratio, benchmark = map(canonical, (balance, income, ratio, benchmark))
    bs_outcome = BalanceSheetAnalysisOutcome(
        AnalysisStatus.COMPLETED, SourceMode.MULTI_SOURCE_DERIVED,
        dict(balance, engine_version="1.0.0"), None, None,
    )
    is_outcome = IncomeStatementAnalysisOutcome(
        AnalysisStatus.COMPLETED, SourceMode.MULTI_SOURCE_DERIVED,
        dict(income, engine_version="1.0.0"), None, None,
    )
    calls = {"ratio": 0}
    monkeypatch.setitem(legacy_service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E3.FS_BALANCE_SHEET, lambda **_: bs_outcome)
    monkeypatch.setitem(legacy_service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E3.FS_INCOME_STATEMENT, lambda **_: is_outcome)

    def ratio_call(**kwargs):
        calls["ratio"] += 1
        assert "trend_result" not in kwargs and "multi_period_trend" not in kwargs
        return ratio

    monkeypatch.setitem(legacy_service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E3.RATIO, ratio_call)
    monkeypatch.setitem(legacy_service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E3.BENCHMARK, lambda *_a, **_k: benchmark)
    monkeypatch.setitem(legacy_service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E3.HEALTH_SCORE, lambda *_a, **_k: health)
    monkeypatch.setitem(legacy_service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E3.CREDIT_SCORE, lambda *_a, **_k: credit)
    monkeypatch.setitem(legacy_service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E3.RECOMMENDATION, lambda *_a, **_k: recommendation)
    return calls


def _record(result, code):
    return next(item for item in result.engine_records if item.engine_code is code)


def test_v4_dispatch_uses_report_1_2_only_and_graph_edge_is_exact():
    assert ORCHESTRATOR_ENGINE_DISPATCH_V4[E.EXECUTIVE_REPORT] is generate_executive_report_v1_2
    report_dependencies = ENGINE_DEPENDENCY_REGISTRY_V4[E.EXECUTIVE_REPORT].dependency
    assert E.MULTI_PERIOD_TREND in report_dependencies.optional
    assert E.MULTI_PERIOD_TREND not in ENGINE_DEPENDENCY_REGISTRY_V4[E.RATIO].dependency.optional
    assert EXECUTION_PLAN_V4.index(E.MULTI_PERIOD_TREND) < EXECUTION_PLAN_V4.index(E.EXECUTIVE_REPORT)


def test_trend_aware_report_runs_once_after_trend_and_ratio_never_consumes_it(monkeypatch):
    calls = _patch_legacy_pipeline(monkeypatch)
    result, _ = run_orchestration_v4(_request())
    trend = _record(result, E.MULTI_PERIOD_TREND)
    report = _record(result, E.EXECUTIVE_REPORT)
    assert calls == {"ratio": 1}
    assert trend.status is EngineExecutionStatusV4.COMPLETED
    assert report.status is EngineExecutionStatusV4.COMPLETED
    assert (report.engine_schema_version_used, report.engine_model_version_used) == ("1.2.0", "1.2.0")
    assert type(report.result.result) is ExecutiveReportResult
    assert report.result.result.report_schema_version == "1.2.0"
    assert result.execution_provenance.engine_call_sequence.count(E.MULTI_PERIOD_TREND) == 1
    assert result.execution_provenance.engine_call_sequence.count(E.EXECUTIVE_REPORT) == 1
    assert result.execution_provenance.engine_call_sequence.index(E.MULTI_PERIOD_TREND) < result.execution_provenance.engine_call_sequence.index(E.EXECUTIVE_REPORT)


def test_report_1_2_contains_exact_trend_section_and_preserves_downstream_sources(monkeypatch):
    _patch_legacy_pipeline(monkeypatch)
    result, _ = run_orchestration_v4(_request())
    report = _record(result, E.EXECUTIVE_REPORT).result.result
    section = next(item for item in report.sections if item.section_code is ReportSectionCode.SEC_PERIOD_COMPARISON_ANALYSIS)
    assert "multi_period_trend" in section.source_engines
    assert tuple(item.source_engine for item in report.source_inventory)[-1] == "multi_period_trend"
    assert all(item.source_engine != "multi_period_trend" for item in report.source_inventory[:-1])
    assert len(tuple(item for item in section.content_blocks if item.source_field_path.startswith("multi_period_trend"))) == 7


def test_render_contract_consumes_refreshed_report_1_2_after_trend(monkeypatch):
    _patch_legacy_pipeline(monkeypatch)
    result, _ = run_orchestration_v4(_request(render=True))
    report = _record(result, E.EXECUTIVE_REPORT)
    render = _record(result, E.RENDER_CONTRACT)
    assert report.result.result.report_schema_version == "1.2.0"
    assert render.status is EngineExecutionStatusV4.COMPLETED
    assert result.execution_provenance.engine_call_sequence.index(E.MULTI_PERIOD_TREND) < result.execution_provenance.engine_call_sequence.index(E.EXECUTIVE_REPORT) < result.execution_provenance.engine_call_sequence.index(E.RENDER_CONTRACT)


def test_report_fingerprint_binds_trend_digest_status_evidence_and_is_order_independent():
    request = _request()
    one = {E.MULTI_PERIOD_TREND: "a" * 64, E.RECOMMENDATION: "b" * 64}
    reordered = {E.RECOMMENDATION: "b" * 64, E.MULTI_PERIOD_TREND: "a" * 64}
    changed = {E.MULTI_PERIOD_TREND: "c" * 64, E.RECOMMENDATION: "b" * 64}
    assert compute_engine_input_fingerprint_v4(E.EXECUTIVE_REPORT, request, one) == compute_engine_input_fingerprint_v4(E.EXECUTIVE_REPORT, request, reordered)
    assert compute_engine_input_fingerprint_v4(E.EXECUTIVE_REPORT, request, one) != compute_engine_input_fingerprint_v4(E.EXECUTIVE_REPORT, request, changed)


def _snapshot(result, request):
    ctx = request.engine_inputs.trend_pre_resolved_context
    items = []
    for record in result.engine_records:
        common = dict(
            engine_code=record.engine_code,
            execution_status=record.status,
            engine_schema_version_used=record.engine_schema_version_used,
            engine_model_version_used=record.engine_model_version_used,
            input_fingerprint=record.input_fingerprint,
            fingerprint_schema_version=record.fingerprint_schema_version,
            result=record.result,
        )
        if record.engine_code is E.MULTI_PERIOD_TREND:
            common.update(
                financial_analysis_result_id=UUID("11111111-1111-4111-8111-111111111199"),
                owner_content_digest="a" * 64,
                trend_source_set_digest=ctx.source_set_digest,
                trend_resolution_digest=ctx.resolution_digest,
                trend_registry_digest=ctx.metric_registry_digest,
                trend_policy_version=ctx.policy_version.value,
                trend_lineage_verified=True,
            )
        items.append(PreviousEngineSnapshotV4(**common))
    return PreviousExecutionSnapshotV4(
        "previous-trend-report-run",
        result.request_fingerprint,
        "4.0.0",
        "4.0.0",
        "4.0.0",
        tuple(items),
    )


def test_exact_report_reuse_is_v4_only_and_cross_version_is_rejected(monkeypatch):
    _patch_legacy_pipeline(monkeypatch)
    request = _request()
    first, _ = run_orchestration_v4(request)
    snapshot = _snapshot(first, request)
    reused, _ = run_orchestration_v4(_request(snapshot=snapshot))
    assert _record(reused, E.MULTI_PERIOD_TREND).status is EngineExecutionStatusV4.REUSED
    assert _record(reused, E.EXECUTIVE_REPORT).status is EngineExecutionStatusV4.REUSED
    report_snapshot = next(item for item in snapshot.engine_snapshots if item.engine_code is E.EXECUTIVE_REPORT)
    bad = replace(report_snapshot, engine_model_version_used="1.1.0")
    changed = replace(snapshot, engine_snapshots=tuple(bad if item.engine_code is E.EXECUTIVE_REPORT else item for item in snapshot.engine_snapshots))
    rejected, _ = run_orchestration_v4(_request(snapshot=changed))
    report = _record(rejected, E.EXECUTIVE_REPORT)
    assert report.status is EngineExecutionStatusV4.FAILED
    assert report.error.category.value == "version_incompatible_on_reuse"


def test_missing_or_corrupt_trend_snapshot_blocks_report_reuse(monkeypatch):
    _patch_legacy_pipeline(monkeypatch)
    request = _request()
    first, _ = run_orchestration_v4(request)
    snapshot = _snapshot(first, request)
    missing = replace(snapshot, engine_snapshots=tuple(item for item in snapshot.engine_snapshots if item.engine_code is not E.MULTI_PERIOD_TREND))
    rejected, _ = run_orchestration_v4(_request(snapshot=missing))
    assert rejected.status.value == "failed"
    assert rejected.structured_errors[0].category.value == "resume_lineage_integrity_failure"


def test_report_presentation_digest_is_canonical_and_contains_no_raw_preimage(monkeypatch):
    _patch_legacy_pipeline(monkeypatch)
    result, _ = run_orchestration_v4(_request())
    report = _record(result, E.EXECUTIVE_REPORT).result.result
    digest = canonical_report_presentation_digest_v1_2(report)
    assert len(digest) == 64 and digest == canonical_report_presentation_digest_v1_2(report)
    assert digest != canonical_trend_digest(_record(result, E.MULTI_PERIOD_TREND).result.result)
    assert "result_json" not in digest and "trial_balance" not in digest


def test_legacy_version_constants_and_v4_report_versions_are_separate(monkeypatch):
    from app.engines.executive_reports.cash_flow_integration import REPORT_SCHEMA_VERSION_V1_1_CASH_FLOW
    from app.engines.common.report_types import REPORT_SCHEMA_VERSION

    assert REPORT_SCHEMA_VERSION == "1.0.0"
    assert REPORT_SCHEMA_VERSION_V1_1_CASH_FLOW == "1.1.0"
    assert (REPORT_SCHEMA_VERSION_V1_2_TREND, REPORT_MODEL_VERSION_V1_2_TREND) == ("1.2.0", "1.2.0")
    _patch_legacy_pipeline(monkeypatch)
    result, _ = run_orchestration_v4(_request())
    assert _record(result, E.EXECUTIVE_REPORT).fingerprint_schema_version == FINGERPRINT_SCHEMA_VERSION_V4
