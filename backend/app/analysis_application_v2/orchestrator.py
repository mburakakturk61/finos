"""Application-facing adapter for the pure synchronous V3 orchestrator."""

from __future__ import annotations

from collections.abc import Callable

from app.engines.analysis_orchestrator_v3.service import run_orchestration_v3
from app.engines.analysis_orchestrator_v3.types import OrchestrationRunRequestV3, OrchestrationRunResultV3


class SynchronousAnalysisOrchestratorAdapterV3:
    def run(
        self,
        request: OrchestrationRunRequestV3,
        *,
        cancellation_probe: Callable[[], bool] | None = None,
    ) -> OrchestrationRunResultV3:
        result, _telemetry = run_orchestration_v3(
            request, cancellation_probe=cancellation_probe,
        )
        return result
