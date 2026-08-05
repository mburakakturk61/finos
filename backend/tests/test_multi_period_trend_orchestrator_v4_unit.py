from dataclasses import fields, replace
from decimal import Decimal
from uuid import UUID

import pytest

from app.engines.analysis_orchestrator_v3.types import OrchestrationEngineCodeV3
from app.engines.analysis_orchestrator_v4 import (
    ENGINE_DEPENDENCY_REGISTRY_V4, EXECUTION_PLAN_V4,
    EngineExecutionStatusV4, EngineRawInputsV4, EngineResultEnvelopeV4,
    OrchestrationEngineCodeV4 as E, OrchestrationRunOptionsV4,
    OrchestrationRunRequestV4, PreviousEngineSnapshotV4,
    PreviousExecutionSnapshotV4, build_trend_pre_resolved_context_v1,
    compute_engine_input_fingerprint_v4, compute_request_fingerprint_v4,
    run_orchestration_v4,
)
from app.engines.multi_period_trend import (
    TrendComparabilityProfile, TrendCoverageKind, TrendDuplicatePolicy,
    TrendGapPolicy, TrendNominalAnalysisProfile, TrendOverlapPolicy,
    TrendPeriodFamily, TrendRestatementProfile,
)

from test_multi_period_trend_pairwise_unit import COMPANY, TENANT, resolved_series


def _profile():
    return TrendComparabilityProfile(
        tenant_id=TENANT, company_id=COMPANY, currency="TRY",
        accounting_basis="tfrs", accounting_policy_version="1.0.0",
        fiscal_calendar_reference="calendar-year",
        period_family=TrendPeriodFamily.ANNUAL,
        coverage_kind=TrendCoverageKind.CUMULATIVE,
        source_schema_version=None, source_model_version="1.0.0",
        require_source_digest=True, restatement_profile=TrendRestatementProfile.ORIGINAL,
        nominal_analysis_profile=TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT,
        gap_policy=TrendGapPolicy.SEGMENT_WITHOUT_FILL,
        overlap_policy=TrendOverlapPolicy.REJECT,
        duplicate_policy=TrendDuplicatePolicy.REJECT,
    )


def context(values=(100, 110, 121)):
    series = resolved_series(tuple(Decimal(str(item)) for item in values))
    return build_trend_pre_resolved_context_v1(
        resolved_series=(series,), comparability_profile=_profile(),
        expected_metric_codes=(series.metric_code,),
    )


def request(ctx=None, snapshot=None):
    ctx = ctx or context()
    return OrchestrationRunRequestV4(
        "trend-run", "correlation", "2026-08-05T12:00:00+00:00",
        (E.MULTI_PERIOD_TREND,), EngineRawInputsV4(trend_pre_resolved_context=ctx),
        OrchestrationRunOptionsV4(tenant_id="tenant"), snapshot,
    )


def test_v4_graph_manifest_is_exact_and_legacy_enum_is_unchanged():
    assert len(ENGINE_DEPENDENCY_REGISTRY_V4) == 12
    assert sum(len(item.dependency.all_of) for item in ENGINE_DEPENDENCY_REGISTRY_V4.values()) == 23
    assert sum(len(item.dependency.any_of) for item in ENGINE_DEPENDENCY_REGISTRY_V4.values()) == 2
    assert sum(len(item.dependency.optional) for item in ENGINE_DEPENDENCY_REGISTRY_V4.values()) == 4
    assert E.MULTI_PERIOD_TREND not in tuple(OrchestrationEngineCodeV3)
    assert ENGINE_DEPENDENCY_REGISTRY_V4[E.MULTI_PERIOD_TREND].dependency.all_of == ()
    assert ENGINE_DEPENDENCY_REGISTRY_V4[E.EXECUTIVE_REPORT].dependency.optional[-1] is E.MULTI_PERIOD_TREND


def test_v4_execution_plan_is_deterministic_and_has_all_nodes():
    assert len(EXECUTION_PLAN_V4) == len(set(EXECUTION_PLAN_V4)) == 12
    assert EXECUTION_PLAN_V4.index(E.MULTI_PERIOD_TREND) < EXECUTION_PLAN_V4.index(E.EXECUTIVE_REPORT)


def test_request_rejects_missing_context_and_cross_major_codes():
    with pytest.raises(ValueError):
        OrchestrationRunRequestV4("x", None, None, (E.MULTI_PERIOD_TREND,), EngineRawInputsV4(), OrchestrationRunOptionsV4())
    with pytest.raises(TypeError):
        OrchestrationRunRequestV4("x", None, None, (OrchestrationEngineCodeV3.RATIO,), EngineRawInputsV4(), OrchestrationRunOptionsV4())


def test_fingerprint_is_order_independent_but_source_registry_policy_and_graph_bound():
    one = resolved_series((Decimal("100"), Decimal("110"), Decimal("121")), metric_code="bs.total_assets")
    two = resolved_series((Decimal("10"), Decimal("11"), Decimal("12")), metric_code="bs.equity")
    a = build_trend_pre_resolved_context_v1(resolved_series=(one, two), comparability_profile=_profile(), expected_metric_codes=(one.metric_code, two.metric_code))
    b = build_trend_pre_resolved_context_v1(resolved_series=(two, one), comparability_profile=_profile(), expected_metric_codes=(one.metric_code, two.metric_code))
    assert compute_request_fingerprint_v4(request(a)) == compute_request_fingerprint_v4(request(b))
    changed = context((100, 110, 122))
    assert compute_request_fingerprint_v4(request(a)) != compute_request_fingerprint_v4(request(changed))
    assert compute_engine_input_fingerprint_v4(E.MULTI_PERIOD_TREND, request(a), {}) != compute_engine_input_fingerprint_v4(E.MULTI_PERIOD_TREND, request(changed), {})


def test_trend_dispatch_runs_once_and_returns_result_bearing_degraded_status(monkeypatch):
    calls = []
    from app.engines.analysis_orchestrator_v4 import service
    original = service.ORCHESTRATOR_ENGINE_DISPATCH_V4[E.MULTI_PERIOD_TREND]
    def wrapped(**kwargs):
        calls.append(1)
        return original(**kwargs)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V4, E.MULTI_PERIOD_TREND, wrapped)
    result, telemetry = run_orchestration_v4(request())
    assert telemetry is None and calls == [1]
    record = result.engine_records[0]
    assert record.engine_code is E.MULTI_PERIOD_TREND
    assert record.status is EngineExecutionStatusV4.DEGRADED
    assert record.result.result_kind == "TrendAnalysisResult"
    assert record.result.result.status.value == "partial"


def test_insufficient_for_trend_is_degraded_not_technical_failure():
    result, _ = run_orchestration_v4(request(context((100, 110))))
    assert result.engine_records[0].status is EngineExecutionStatusV4.DEGRADED
    assert result.engine_records[0].inner_status_value == "insufficient_for_trend"
    assert result.structured_errors == ()


def test_compatible_v4_reuse_and_lineage_fail_closed():
    base = request()
    first, _ = run_orchestration_v4(base)
    record = first.engine_records[0]
    ctx = base.engine_inputs.trend_pre_resolved_context
    snapshot = PreviousExecutionSnapshotV4(
        "old", first.request_fingerprint, "4.0.0", "4.0.0", "4.0.0",
        (PreviousEngineSnapshotV4(
            E.MULTI_PERIOD_TREND, record.status, "1.0.0", "1.0.0",
            record.input_fingerprint, "4.0.0", record.result,
            UUID("11111111-1111-4111-8111-111111111119"), "a" * 64,
            ctx.source_set_digest, ctx.resolution_digest, ctx.metric_registry_digest,
            ctx.policy_version.value, True,
        ),),
    )
    reused, _ = run_orchestration_v4(request(ctx, snapshot))
    assert reused.engine_records[0].status is EngineExecutionStatusV4.REUSED
    corrupted = replace(snapshot.engine_snapshots[0], trend_source_set_digest="b" * 64)
    bad_snapshot = replace(snapshot, engine_snapshots=(corrupted,))
    failed, _ = run_orchestration_v4(request(ctx, bad_snapshot))
    assert failed.status.value == "failed"
    assert failed.structured_errors[0].category.value == "resume_lineage_integrity_failure"


def test_v4_envelope_rejects_wrong_result_kind():
    with pytest.raises(TypeError):
        EngineResultEnvelopeV4(E.MULTI_PERIOD_TREND, "dict", {})
