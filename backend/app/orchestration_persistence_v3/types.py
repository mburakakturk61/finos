"""ORM-free, version-isolated persistence contracts for orchestration V3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol
from uuid import UUID

from app.engines.analysis_orchestrator_v3.types import (
    ExecutionTelemetryV3,
    OrchestrationEngineCodeV3,
    OrchestrationRunResultV3,
    PreviousExecutionSnapshotV3,
)
from app.engines.cash_flow.types import CashFlowSourceRole
from app.models.enums import AnalysisSourceRole, AnalysisType, SourceMode

PERSISTENCE_CONTRACT_VERSION_V3 = "3.0.0"


def _digest(value: str | None, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if type(value) is not str or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be lowercase SHA-256")


class ResultOwnerV3(str, Enum):
    FINANCIAL_ANALYSIS_RESULT = "financial_analysis_result"
    ORCHESTRATION_ARTIFACT = "orchestration_artifact"


@dataclass(frozen=True)
class ResultOwnershipSpecV3:
    owner: ResultOwnerV3
    analysis_type: AnalysisType | None

    def __post_init__(self) -> None:
        if (self.owner is ResultOwnerV3.FINANCIAL_ANALYSIS_RESULT) != (self.analysis_type is not None):
            raise ValueError("financial ownership requires an analysis type")


_F = ResultOwnerV3.FINANCIAL_ANALYSIS_RESULT
_A = ResultOwnerV3.ORCHESTRATION_ARTIFACT
RESULT_OWNERSHIP_REGISTRY_V3: Mapping[OrchestrationEngineCodeV3, ResultOwnershipSpecV3] = MappingProxyType({
    OrchestrationEngineCodeV3.FS_BALANCE_SHEET: ResultOwnershipSpecV3(_F, AnalysisType.BALANCE_SHEET),
    OrchestrationEngineCodeV3.FS_INCOME_STATEMENT: ResultOwnershipSpecV3(_F, AnalysisType.INCOME_STATEMENT),
    OrchestrationEngineCodeV3.CASH_FLOW: ResultOwnershipSpecV3(_F, AnalysisType.CASH_FLOW),
    OrchestrationEngineCodeV3.RATIO: ResultOwnershipSpecV3(_F, AnalysisType.FINANCIAL_RATIOS),
    OrchestrationEngineCodeV3.BENCHMARK: ResultOwnershipSpecV3(_A, None),
    OrchestrationEngineCodeV3.HEALTH_SCORE: ResultOwnershipSpecV3(_A, None),
    OrchestrationEngineCodeV3.CREDIT_SCORE: ResultOwnershipSpecV3(_A, None),
    OrchestrationEngineCodeV3.RECOMMENDATION: ResultOwnershipSpecV3(_A, None),
    OrchestrationEngineCodeV3.EXECUTIVE_REPORT: ResultOwnershipSpecV3(_A, None),
    OrchestrationEngineCodeV3.DASHBOARD: ResultOwnershipSpecV3(_A, None),
    OrchestrationEngineCodeV3.RENDER_CONTRACT: ResultOwnershipSpecV3(_A, None),
})


@dataclass(frozen=True)
class PersistenceRunScopeV3:
    tenant_id: UUID
    company_id: UUID
    period_id: UUID

    def __post_init__(self) -> None:
        if not all(type(item) is UUID for item in (self.tenant_id, self.company_id, self.period_id)):
            raise TypeError("V3 persistence scope requires UUID values")


@dataclass(frozen=True)
class ResumeEngineBindingV3:
    engine_code: OrchestrationEngineCodeV3
    source_engine_execution_id: UUID
    artifact_id: UUID | None
    financial_analysis_result_id: UUID | None
    owner_content_digest: str | None
    financial_result_canonical_digest: str | None
    input_fingerprint: str
    engine_schema_version: str | None
    engine_model_version: str | None

    def __post_init__(self) -> None:
        if (self.artifact_id is not None) and (self.financial_analysis_result_id is not None):
            raise ValueError("resume binding owner fields are mutually exclusive")
        spec = RESULT_OWNERSHIP_REGISTRY_V3[self.engine_code]
        has_owner = self.artifact_id is not None or self.financial_analysis_result_id is not None
        if has_owner:
            if spec.owner is ResultOwnerV3.FINANCIAL_ANALYSIS_RESULT and self.financial_analysis_result_id is None:
                raise ValueError("financial engine must bind a financial owner")
            if spec.owner is ResultOwnerV3.ORCHESTRATION_ARTIFACT and self.artifact_id is None:
                raise ValueError("artifact engine must bind an artifact owner")
            _digest(self.owner_content_digest, "owner_content_digest")
        elif self.owner_content_digest is not None or self.financial_result_canonical_digest is not None:
            raise ValueError("ownerless execution cannot carry owner digests")
        _digest(self.financial_result_canonical_digest, "financial_result_canonical_digest", nullable=True)
        _digest(self.input_fingerprint, "input_fingerprint")


@dataclass(frozen=True)
class ResumePersistenceContextV3:
    persisted_run_id: UUID
    previous_run_id: str
    scope: PersistenceRunScopeV3
    engine_bindings: tuple[ResumeEngineBindingV3, ...]
    orchestration_contract_version: str = "3.0.0"

    def __post_init__(self) -> None:
        if self.orchestration_contract_version != "3.0.0":
            raise ValueError("V3 resume context cannot accept another major version")
        if type(self.engine_bindings) is not tuple or len({x.engine_code for x in self.engine_bindings}) != len(self.engine_bindings):
            raise ValueError("resume bindings must be a unique tuple")


@dataclass(frozen=True)
class SnapshotLoadResultV3:
    snapshot: PreviousExecutionSnapshotV3
    persistence_context: ResumePersistenceContextV3


@dataclass(frozen=True)
class FinancialResultSourceBindingV3:
    role: AnalysisSourceRole
    source_document_id: UUID | None
    source_analysis_result_id: UUID | None

    def __post_init__(self) -> None:
        if (self.source_document_id is None) == (self.source_analysis_result_id is None):
            raise ValueError("same-period source binding requires one locator")


@dataclass(frozen=True)
class CashFlowLineageBindingV3:
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID
    source_period_id: UUID
    source_canonical_digest: str
    source_provenance_digest: str
    source_analysis_type: AnalysisType
    source_engine_version: str
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None

    def __post_init__(self) -> None:
        for name in ("source_canonical_digest", "source_provenance_digest", "current_period_descriptor_digest"):
            _digest(getattr(self, name), name)
        _digest(self.prior_period_descriptor_digest, "prior_period_descriptor_digest", nullable=True)
        _digest(self.comparability_proof_digest, "comparability_proof_digest", nullable=True)
        if (self.prior_period_descriptor_digest is None) != (self.comparability_proof_digest is None):
            raise ValueError("prior descriptor and comparability proof form a pair")


@dataclass(frozen=True)
class CreateFinancialResultOwnerV3:
    analysis_type: AnalysisType
    source_mode: SourceMode
    document_id: UUID | None
    engine_version: str
    started_at: datetime
    completed_at: datetime
    same_period_source_bindings: tuple[FinancialResultSourceBindingV3, ...]
    cash_flow_lineage: tuple[CashFlowLineageBindingV3, ...]

    def __post_init__(self) -> None:
        if self.analysis_type is AnalysisType.CASH_FLOW:
            if self.source_mode is not SourceMode.MULTI_SOURCE_DERIVED or self.document_id is not None or self.same_period_source_bindings:
                raise ValueError("Cash Flow owner has only cross-period lineage")
        elif self.cash_flow_lineage:
            raise ValueError("non-Cash-Flow owner cannot carry cross-period lineage")
        if self.completed_at < self.started_at:
            raise ValueError("owner completion precedes start")


@dataclass(frozen=True)
class FinancialResultOwnerBindingV3:
    engine_code: OrchestrationEngineCodeV3
    existing_owner_id: UUID | None
    create_owner: CreateFinancialResultOwnerV3 | None
    expected_same_period_source_bindings: tuple[FinancialResultSourceBindingV3, ...]
    expected_cash_flow_lineage: tuple[CashFlowLineageBindingV3, ...]
    expected_canonical_result_digest: str | None
    expected_owner_content_digest: str
    expected_current_period_descriptor_digest: str | None
    expected_prior_period_descriptor_digest: str | None
    expected_comparability_proof_digest: str | None

    def __post_init__(self) -> None:
        if (self.existing_owner_id is None) == (self.create_owner is None):
            raise ValueError("financial owner mode must be exact XOR")
        if RESULT_OWNERSHIP_REGISTRY_V3[self.engine_code].owner is not ResultOwnerV3.FINANCIAL_ANALYSIS_RESULT:
            raise ValueError("artifact engine cannot use financial owner binding")
        _digest(self.expected_owner_content_digest, "expected_owner_content_digest")
        _digest(self.expected_canonical_result_digest, "expected_canonical_result_digest", nullable=True)
        for name in ("expected_current_period_descriptor_digest", "expected_prior_period_descriptor_digest", "expected_comparability_proof_digest"):
            _digest(getattr(self, name), name, nullable=True)
        is_cf = self.engine_code is OrchestrationEngineCodeV3.CASH_FLOW
        if is_cf != bool(self.expected_cash_flow_lineage or self.expected_current_period_descriptor_digest):
            raise ValueError("Cash Flow binding requires Cash Flow proof fields only")
        if is_cf and self.expected_same_period_source_bindings:
            raise ValueError("Cash Flow binding cannot carry same-period sources")
        if not is_cf and self.expected_cash_flow_lineage:
            raise ValueError("non-Cash-Flow binding cannot carry cross-period lineage")
        if self.create_owner is not None and (
            self.create_owner.same_period_source_bindings != self.expected_same_period_source_bindings
            or self.create_owner.cash_flow_lineage != self.expected_cash_flow_lineage
        ):
            raise ValueError("staged and expected lineage must match exactly")


@dataclass(frozen=True)
class PersistTerminalRunCommandV3:
    scope: PersistenceRunScopeV3
    run_result: OrchestrationRunResultV3
    requested_outputs: tuple[OrchestrationEngineCodeV3, ...]
    resume_context: ResumePersistenceContextV3 | None
    financial_owner_bindings: tuple[FinancialResultOwnerBindingV3, ...]
    telemetry: ExecutionTelemetryV3 | None
    persistence_contract_version: str = PERSISTENCE_CONTRACT_VERSION_V3

    def __post_init__(self) -> None:
        if self.persistence_contract_version != PERSISTENCE_CONTRACT_VERSION_V3:
            raise ValueError("unknown persistence contract version")
        if any(type(code) is not OrchestrationEngineCodeV3 for code in self.requested_outputs):
            raise TypeError("V3 persistence command rejects legacy engine codes")


@dataclass(frozen=True)
class PersistedRunV3:
    id: UUID
    run_id: str
    request_fingerprint: str
    terminal_content_digest: str
    scope: PersistenceRunScopeV3
    finalized_at: datetime
    orchestration_contract_version: str


@dataclass(frozen=True)
class RunHistoryPageV3:
    items: tuple[PersistedRunV3, ...]
    next_cursor: str | None


class RunStorePortV3(Protocol):
    def load_run(self, run_id: str) -> PersistedRunV3 | None: ...
    def persist_terminal_run(self, command: PersistTerminalRunCommandV3) -> PersistedRunV3: ...
    def list_run_history(self, scope: PersistenceRunScopeV3, cursor: str | None, limit: int) -> RunHistoryPageV3: ...


class SnapshotReaderPortV3(Protocol):
    def build_previous_execution_snapshot(self, run_id: str, target_scope: PersistenceRunScopeV3) -> SnapshotLoadResultV3: ...


def validate_result_ownership_registry_v3() -> None:
    if tuple(RESULT_OWNERSHIP_REGISTRY_V3) != tuple(OrchestrationEngineCodeV3):
        raise RuntimeError("V3 ownership registry order mismatch")
    specs = tuple(RESULT_OWNERSHIP_REGISTRY_V3.values())
    if sum(x.owner is _F for x in specs) != 4 or sum(x.owner is _A for x in specs) != 7:
        raise RuntimeError("V3 ownership registry must be 4 financial / 7 artifact")


validate_result_ownership_registry_v3()
