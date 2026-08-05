"""Framework-neutral Application-v3 integration ports."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.analysis_application.contracts import ApplicationAuditContextDTO, ApplicationScopeDTO
from app.engines.analysis_orchestrator_v4.types import OrchestrationRunRequestV4, OrchestrationRunResultV4, PreviousExecutionSnapshotV4, TrendPreResolvedContextV1
from app.orchestration_persistence_v4.types import PersistedTrendRunV4, PersistTerminalTrendRunCommandV4

from .contracts import TrendRequestDTOV3


class TrendSourceResolverPortV3(Protocol):
    def resolve_trend_context(
        self, request: TrendRequestDTOV3, scope: ApplicationScopeDTO,
        actor: ApplicationAuditContextDTO,
    ) -> TrendPreResolvedContextV1: ...


class TenantIdentityResolverPortV3(Protocol):
    def resolve_tenant_id(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> UUID: ...


@dataclass(frozen=True)
class TrendResumeSnapshotBindingV4:
    snapshot: PreviousExecutionSnapshotV4
    financial_analysis_result_id: UUID
    owner_content_digest: str


class TrendResumeSnapshotResolverPortV4(Protocol):
    def load_verified_snapshot(
        self, previous_run_id: str, scope: ApplicationScopeDTO,
        actor: ApplicationAuditContextDTO,
    ) -> TrendResumeSnapshotBindingV4: ...


class AnalysisOrchestratorPortV4(Protocol):
    def run(self, request: OrchestrationRunRequestV4, *, cancellation_probe: Callable[[], bool] | None = None) -> OrchestrationRunResultV4: ...


class TrendTerminalPersistencePortV4(Protocol):
    def persist_terminal_run(self, command: PersistTerminalTrendRunCommandV4) -> PersistedTrendRunV4: ...


class SynchronousOrchestratorV4Adapter:
    def run(self, request, *, cancellation_probe=None):
        from app.engines.analysis_orchestrator_v4.service import run_orchestration_v4
        return run_orchestration_v4(request, cancellation_probe=cancellation_probe)[0]
