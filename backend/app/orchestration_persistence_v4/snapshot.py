"""Verified Persistence-v4 snapshot construction."""

from app.engines.analysis_orchestrator_v4.types import (
    OrchestrationEngineCodeV4, OrchestrationRunResultV4,
    PreviousEngineSnapshotV4, PreviousExecutionSnapshotV4,
    TrendPreResolvedContextV1,
)


class SnapshotV4IntegrityError(ValueError):
    pass


def snapshot_from_terminal_result_v4(
    result: OrchestrationRunResultV4,
    *,
    trend_context: TrendPreResolvedContextV1 | None,
    trend_lineage_verified: bool,
    trend_financial_analysis_result_id=None,
    trend_owner_content_digest: str | None = None,
) -> PreviousExecutionSnapshotV4:
    if type(result) is not OrchestrationRunResultV4:
        raise TypeError("Persistence-v4 snapshot requires exact V4 run result")
    if (result.orchestration_schema_version, result.orchestration_model_version, result.execution_plan_version) != ("4.0.0", "4.0.0", "4.0.0"):
        raise SnapshotV4IntegrityError("terminal run is not V4-compatible")
    snapshots = []
    seen = set()
    for record in result.engine_records:
        if record.engine_code in seen:
            raise SnapshotV4IntegrityError("duplicate V4 engine execution")
        seen.add(record.engine_code)
        kwargs = {}
        if record.engine_code is OrchestrationEngineCodeV4.MULTI_PERIOD_TREND:
            if record.result is None or not trend_lineage_verified or type(trend_context) is not TrendPreResolvedContextV1:
                raise SnapshotV4IntegrityError("Trend snapshot requires result and verified lineage")
            kwargs = {
                "trend_source_set_digest": trend_context.source_set_digest,
                "trend_resolution_digest": trend_context.resolution_digest,
                "trend_registry_digest": trend_context.metric_registry_digest,
                "trend_policy_version": trend_context.policy_version.value,
                "trend_lineage_verified": True,
                "financial_analysis_result_id": trend_financial_analysis_result_id,
                "owner_content_digest": trend_owner_content_digest,
            }
        snapshots.append(PreviousEngineSnapshotV4(
            record.engine_code, record.status, record.engine_schema_version_used,
            record.engine_model_version_used, record.input_fingerprint,
            record.fingerprint_schema_version, record.result, **kwargs,
        ))
    return PreviousExecutionSnapshotV4(
        result.run_id, result.request_fingerprint, result.orchestration_schema_version,
        result.orchestration_model_version, result.execution_plan_version, tuple(snapshots),
    )
