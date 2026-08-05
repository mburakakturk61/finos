"""Additive Persistence-v4 contracts and Trend ownership registry."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from app.engines.analysis_orchestrator_v4.types import OrchestrationEngineCodeV4, OrchestrationRunResultV4, PreviousExecutionSnapshotV4
from app.engines.multi_period_trend import TREND_LINEAGE_SCHEMA_VERSION, TrendLineageEdge
from app.models.enums import AnalysisType, SourceMode


PERSISTENCE_CONTRACT_VERSION_V4 = "4.0.0"


class ResultOwnerV4(str, Enum):
    FINANCIAL_ANALYSIS_RESULT = "financial_analysis_result"
    ORCHESTRATION_ARTIFACT = "orchestration_artifact"


@dataclass(frozen=True)
class ResultOwnershipSpecV4:
    engine_code: OrchestrationEngineCodeV4
    owner: ResultOwnerV4
    result_kind: str
    analysis_type: AnalysisType | None
    lineage_schema_version: str | None


_FINANCIAL = {
    OrchestrationEngineCodeV4.FS_BALANCE_SHEET: ("BalanceSheetAnalysisOutcomeV3", AnalysisType.BALANCE_SHEET, None),
    OrchestrationEngineCodeV4.FS_INCOME_STATEMENT: ("IncomeStatementAnalysisOutcomeV3", AnalysisType.INCOME_STATEMENT, None),
    OrchestrationEngineCodeV4.CASH_FLOW: ("CashFlowResult", AnalysisType.CASH_FLOW, "1.0.0"),
    OrchestrationEngineCodeV4.RATIO: ("dict", AnalysisType.FINANCIAL_RATIOS, None),
    OrchestrationEngineCodeV4.MULTI_PERIOD_TREND: ("TrendAnalysisResult", AnalysisType.MULTI_PERIOD_TREND, TREND_LINEAGE_SCHEMA_VERSION),
}

RESULT_OWNERSHIP_REGISTRY_V4: Mapping[OrchestrationEngineCodeV4, ResultOwnershipSpecV4] = MappingProxyType({
    code: ResultOwnershipSpecV4(
        code,
        ResultOwnerV4.FINANCIAL_ANALYSIS_RESULT if code in _FINANCIAL else ResultOwnerV4.ORCHESTRATION_ARTIFACT,
        _FINANCIAL[code][0] if code in _FINANCIAL else "artifact",
        _FINANCIAL[code][1] if code in _FINANCIAL else None,
        _FINANCIAL[code][2] if code in _FINANCIAL else None,
    )
    for code in OrchestrationEngineCodeV4
})


@dataclass(frozen=True, repr=False)
class PersistenceRunScopeV4:
    tenant_id: UUID
    company_id: UUID
    anchor_period_id: UUID
    initiating_subject_id: str


@dataclass(frozen=True, repr=False)
class PersistTerminalTrendRunCommandV4:
    scope: PersistenceRunScopeV4
    run_result: OrchestrationRunResultV4
    lineage: tuple[TrendLineageEdge, ...]
    source_set_digest: str
    resolution_digest: str
    reused_trend_owner_id: UUID | None = None
    reused_trend_owner_content_digest: str | None = None
    persistence_contract_version: str = PERSISTENCE_CONTRACT_VERSION_V4

    def __post_init__(self):
        if type(self.scope) is not PersistenceRunScopeV4 or type(self.run_result) is not OrchestrationRunResultV4:
            raise TypeError("Persistence-v4 rejects cross-major contracts")
        if self.persistence_contract_version != PERSISTENCE_CONTRACT_VERSION_V4:
            raise ValueError("unknown Persistence-v4 contract")
        if type(self.lineage) is not tuple or len(self.lineage) < 2 or any(type(item) is not TrendLineageEdge for item in self.lineage):
            raise ValueError("Persistence-v4 requires exact N-period lineage")
        if (self.reused_trend_owner_id is None) != (self.reused_trend_owner_content_digest is None):
            raise ValueError("reused Trend owner binding must be complete")


@dataclass(frozen=True, repr=False)
class PersistedTrendRunV4:
    run_id: UUID
    trend_analysis_result_id: UUID
    owner_content_digest: str
    source_set_digest: str
    idempotent_replay: bool


@dataclass(frozen=True, repr=False)
class LoadedTrendSnapshotV4:
    snapshot: PreviousExecutionSnapshotV4
    financial_analysis_result_id: UUID
    owner_content_digest: str


def validate_result_ownership_registry_v4() -> None:
    if tuple(RESULT_OWNERSHIP_REGISTRY_V4) != tuple(OrchestrationEngineCodeV4):
        raise ValueError("Persistence-v4 owner registry is incomplete")
    if RESULT_OWNERSHIP_REGISTRY_V4[OrchestrationEngineCodeV4.MULTI_PERIOD_TREND] != ResultOwnershipSpecV4(
        OrchestrationEngineCodeV4.MULTI_PERIOD_TREND, ResultOwnerV4.FINANCIAL_ANALYSIS_RESULT,
        "TrendAnalysisResult", AnalysisType.MULTI_PERIOD_TREND, TREND_LINEAGE_SCHEMA_VERSION,
    ):
        raise ValueError("Trend owner mapping mismatch")


validate_result_ownership_registry_v4()
