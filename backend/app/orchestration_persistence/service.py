"""Caller-neutral execute/persist application service; no API or worker coupling."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import OrchestrationRunRequest
from app.orchestration_persistence.repository import SqlAlchemyOrchestrationRepository
from app.orchestration_persistence.snapshot import SqlAlchemySnapshotBuilder
from app.orchestration_persistence.types import (
    FinancialResultOwnerBinding,
    PersistedRun,
    PersistTerminalRunCommand,
    PersistenceRunScope,
)


class OrchestrationPersistenceService:
    def __init__(self, repository: SqlAlchemyOrchestrationRepository, snapshot_builder: SqlAlchemySnapshotBuilder) -> None:
        self.repository = repository
        self.snapshot_builder = snapshot_builder

    def execute_and_persist(
        self,
        request: OrchestrationRunRequest,
        scope: PersistenceRunScope,
        *,
        previous_run_id: str | None = None,
        financial_owner_bindings: tuple[FinancialResultOwnerBinding, ...] = (),
        cancellation_probe: Callable[[], bool] | None = None,
        timing_probe=None,
    ) -> PersistedRun:
        resume_context = None
        if previous_run_id is not None:
            loaded = self.snapshot_builder.build_previous_execution_snapshot(previous_run_id, scope)
            request = dataclasses.replace(request, previous_execution_snapshot=loaded.snapshot)
            resume_context = loaded.persistence_context
        result, telemetry = run_orchestration(request, cancellation_probe=cancellation_probe, timing_probe=timing_probe)
        if result.run_id != request.run_id:
            raise ValueError("Orchestrator returned a mismatched run identity.")
        if resume_context is not None:
            reused_codes = {record.engine_code for record in result.engine_records if record.status.value == "reused"}
            resume_context = dataclasses.replace(
                resume_context,
                engine_bindings=tuple(item for item in resume_context.engine_bindings if item.engine_code in reused_codes),
            )
        return self.repository.persist_terminal_run(PersistTerminalRunCommand(
            scope=scope, run_result=result, requested_outputs=request.requested_outputs,
            resume_context=resume_context, financial_owner_bindings=financial_owner_bindings,
            telemetry=telemetry,
        ))
