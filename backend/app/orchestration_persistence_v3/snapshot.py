"""Strict V3 snapshot construction without legacy upcast or fallback."""

from __future__ import annotations

from app.engines.analysis_orchestrator_v3.types import (
    OrchestrationRunResultV3,
    PreviousEngineSnapshotV3,
    PreviousExecutionSnapshotV3,
)


class SnapshotV3IntegrityError(ValueError):
    pass


def snapshot_from_terminal_result_v3(result: OrchestrationRunResultV3) -> PreviousExecutionSnapshotV3:
    if type(result) is not OrchestrationRunResultV3:
        raise TypeError("V3 snapshot builder rejects legacy run results")
    if (result.orchestration_schema_version, result.orchestration_model_version, result.execution_plan_version) != (
        "3.0.0", "3.0.0", "3.0.0",
    ):
        raise SnapshotV3IntegrityError("terminal run is not V3-compatible")
    seen = set()
    snapshots = []
    for record in result.engine_records:
        if record.engine_code in seen:
            raise SnapshotV3IntegrityError("duplicate engine execution")
        seen.add(record.engine_code)
        if record.result is not None and record.result.engine_code is not record.engine_code:
            raise SnapshotV3IntegrityError("engine result envelope owner mismatch")
        snapshots.append(PreviousEngineSnapshotV3(
            engine_code=record.engine_code,
            execution_status=record.status,
            engine_schema_version_used=record.engine_schema_version_used,
            engine_model_version_used=record.engine_model_version_used,
            input_fingerprint=record.input_fingerprint,
            fingerprint_schema_version=record.fingerprint_schema_version,
            result=record.result,
        ))
    return PreviousExecutionSnapshotV3(
        previous_run_id=result.run_id,
        request_fingerprint=result.request_fingerprint,
        orchestration_schema_version=result.orchestration_schema_version,
        orchestration_model_version=result.orchestration_model_version,
        execution_plan_version=result.execution_plan_version,
        engine_snapshots=tuple(snapshots),
    )
