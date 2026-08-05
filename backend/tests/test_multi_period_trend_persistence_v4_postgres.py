from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.engines.analysis_orchestrator_v4 import (
    EngineRawInputsV4, OrchestrationEngineCodeV4, OrchestrationRunOptionsV4,
    OrchestrationRunRequestV4, build_trend_pre_resolved_context_v1,
    run_orchestration_v4,
)
from app.engines.multi_period_trend import (
    TrendComparabilityProfile, TrendCoverageKind, TrendDuplicatePolicy,
    TrendGapPolicy, TrendNominalAnalysisProfile, TrendOverlapPolicy,
    TrendPeriodFamily, TrendRestatementProfile, ResolvedTrendObservation,
    canonical_trend_digest, canonical_trend_lineage_set_digest,
    canonical_trend_reference,
)
from app.models.enums import AnalysisType
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.orchestration_persistence import OrchestrationEngineExecution, OrchestrationRun
from app.models.trend_analysis_lineage import TrendAnalysisLineage
from app.orchestration_persistence_v4 import (
    PersistenceRunScopeV4, PersistTerminalTrendRunCommandV4,
    PersistenceV4Error, SqlAlchemyTrendTerminalPersistenceV4,
    decode_trend_financial_result,
)

from test_multi_period_trend_lineage_repository_postgres import (
    _create_scope, _sources, trend_lineage_database,
)
from test_multi_period_trend_pairwise_unit import resolved_series


def _context(scope, sources):
    tenant_id, company_id, periods = scope
    base = resolved_series((Decimal("100"), Decimal("110"), Decimal("121")))
    source_by_period = {row.period_id: row for _ordinal, _role, row in sources}
    observations = []
    for index, item in enumerate(base.observations):
        source = sources[index][2]
        observation = replace(
            item.observation, company_id=company_id, period_id=periods[index],
            source_result_id=source.id,
            canonical_source_digest=source.canonical_result_digest,
        )
        observations.append(ResolvedTrendObservation(
            item.fiscal_ordinal, item.source_field_path, observation,
            canonical_trend_digest((item.fiscal_ordinal, item.source_field_path, observation)),
        ))
    resolution_digest = canonical_trend_digest((base.metric_code, tuple(item.observation_digest for item in observations)))
    series = replace(
        base, tenant_id=tenant_id, company_id=company_id, anchor_period_id=periods[-1],
        observations=tuple(observations), resolution_digest=resolution_digest,
        resolution_reference=canonical_trend_reference(resolution_digest),
    )
    profile = TrendComparabilityProfile(
        tenant_id=tenant_id, company_id=company_id, currency="TRY",
        accounting_basis="tfrs", accounting_policy_version="1.0.0",
        fiscal_calendar_reference="calendar-year", period_family=TrendPeriodFamily.ANNUAL,
        coverage_kind=TrendCoverageKind.CUMULATIVE, source_schema_version=None,
        source_model_version="1.0.0", require_source_digest=True,
        restatement_profile=TrendRestatementProfile.ORIGINAL,
        nominal_analysis_profile=TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT,
        gap_policy=TrendGapPolicy.SEGMENT_WITHOUT_FILL,
        overlap_policy=TrendOverlapPolicy.REJECT, duplicate_policy=TrendDuplicatePolicy.REJECT,
    )
    return build_trend_pre_resolved_context_v1(
        resolved_series=(series,), comparability_profile=profile,
        expected_metric_codes=(series.metric_code,),
    )


def _command(scope, context, *, run_id=None):
    request = OrchestrationRunRequestV4(
        run_id or f"tr46h-{uuid4()}", "tr46h-correlation", datetime.now(timezone.utc).isoformat(),
        (OrchestrationEngineCodeV4.MULTI_PERIOD_TREND,),
        EngineRawInputsV4(trend_pre_resolved_context=context),
        OrchestrationRunOptionsV4(tenant_id=str(scope[0])),
    )
    result, _ = run_orchestration_v4(request)
    return PersistTerminalTrendRunCommandV4(
        PersistenceRunScopeV4(scope[0], scope[1], scope[2][-1], "subject-46h"),
        result, context.lineage, context.source_set_digest,
        context.resolution_digest,
    )


def test_atomic_owner_lineage_terminal_run_and_readback(trend_lineage_database):
    engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    sources = _sources(factory, scope)
    context = _context(scope, sources)
    command = _command(scope, context)
    persisted = SqlAlchemyTrendTerminalPersistenceV4(factory).persist_terminal_run(command)
    assert persisted.idempotent_replay is False
    with factory() as session:
        owner = session.get(FinancialAnalysisResult, persisted.trend_analysis_result_id)
        assert owner.analysis_type is AnalysisType.MULTI_PERIOD_TREND
        decoded = decode_trend_financial_result(owner.result_json, owner.canonical_result_digest)
        assert decoded.canonical_digest == command.run_result.engine_records[0].result.result.canonical_digest
        assert session.scalar(select(func.count()).select_from(TrendAnalysisLineage).where(
            TrendAnalysisLineage.trend_analysis_result_id == owner.id
        )) == len(context.lineage)
        execution = session.scalar(select(OrchestrationEngineExecution).where(
            OrchestrationEngineExecution.run_id == persisted.run_id
        ))
        assert execution.engine_code == "multi_period_trend"
        assert execution.financial_analysis_result_id == owner.id
    loaded = SqlAlchemyTrendTerminalPersistenceV4(factory).build_previous_execution_snapshot(
        command.run_result.run_id, command.scope,
    )
    assert loaded.financial_analysis_result_id == persisted.trend_analysis_result_id
    assert loaded.snapshot.engine_snapshots[0].trend_lineage_verified is True


def test_exact_replay_and_conflicting_source_set(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    context = _context(scope, _sources(factory, scope))
    command = _command(scope, context)
    adapter = SqlAlchemyTrendTerminalPersistenceV4(factory)
    first = adapter.persist_terminal_run(command)
    second = adapter.persist_terminal_run(command)
    assert second.idempotent_replay is True
    assert second.trend_analysis_result_id == first.trend_analysis_result_id
    with pytest.raises(PersistenceV4Error):
        adapter.persist_terminal_run(replace(command, source_set_digest="f" * 64))


def test_result_lineage_must_match_terminal_lineage_binding(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    context = _context(scope, _sources(factory, scope))
    command = _command(scope, context)
    tampered_lineage = (
        replace(context.lineage[0], comparability_proof_digest="f" * 64),
        *context.lineage[1:],
    )
    tampered_source_set = canonical_trend_lineage_set_digest(
        company_id=scope[1],
        anchor_period_id=scope[2][-1],
        metric_registry_version=context.metric_registry_version,
        metric_registry_digest=context.metric_registry_digest,
        policy_version=context.policy_version,
        contract_version=context.contract_version,
        lineage=tampered_lineage,
    )
    with pytest.raises(PersistenceV4Error):
        SqlAlchemyTrendTerminalPersistenceV4(factory).persist_terminal_run(replace(
            command,
            lineage=tampered_lineage,
            source_set_digest=tampered_source_set,
        ))


def test_concurrent_loser_leaves_no_orphan_owner_or_lineage(trend_lineage_database):
    _engine, factory = trend_lineage_database
    scope = _create_scope(factory)
    context = _context(scope, _sources(factory, scope))
    command = _command(scope, context, run_id=f"tr46h-race-{uuid4()}")
    def persist():
        return SqlAlchemyTrendTerminalPersistenceV4(factory).persist_terminal_run(command)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _item: persist(), range(2)))
    assert sum(item.idempotent_replay for item in outcomes) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OrchestrationRun).where(
            OrchestrationRun.run_id == command.run_result.run_id
        )) == 1
        owner_ids = {item.trend_analysis_result_id for item in outcomes}
        assert len(owner_ids) == 1
        assert session.scalar(select(func.count()).select_from(FinancialAnalysisResult).where(
            FinancialAnalysisResult.id.in_(owner_ids)
        )) == 1
        assert session.scalar(select(func.count()).select_from(TrendAnalysisLineage).where(
            TrendAnalysisLineage.trend_analysis_result_id.in_(owner_ids)
        )) == len(context.lineage)
