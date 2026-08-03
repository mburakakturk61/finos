"""Framework-neutral ports for Application v2 phased coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, final
from uuid import UUID

from app.analysis_application.contracts import ApplicationAuditContextDTO, ApplicationScopeDTO, ApplicationStatus, RunScopeClaimStatus
from app.engines.analysis_orchestrator_v3.types import ExecutionTelemetryV3, OrchestrationRunResultV3
from app.engines.cash_flow.contracts import CashFlowPreResolvedContext
from app.engines.cash_flow.contracts import (
    CashFlowAccountEvidence,
    CashFlowNonCashBridgeComponent,
    CashFlowPeriodDescriptor,
    CashFlowSourceSnapshot,
)
from app.engines.cash_flow.types import CashFlowSourceRole
from app.models.enums import AnalysisSourceRole, AnalysisType
from app.orchestration_persistence_v3.types import PersistedRunV3, PersistenceRunScopeV3, ResumePersistenceContextV3, SnapshotLoadResultV3

from .contracts import (
    AnalysisCommandResultDTOV2,
    AnalysisExecutionDTOV2,
    AnalysisHistoryPageDTOV2,
    ApplicationPayloadEnvelopeDTOV2,
    AnalysisResultDTOV2,
    AnalysisRunStatusDTOV2,
    ApplicationEngineCodeV2,
    ApplicationFinancialSourceModeV2,
    ApplicationOutcomeV2,
    CancelAnalysisCommandV2,
    CancellationResultDTOV2,
    CashFlowRequestDTOV2,
    FinancialSourceIntentDTOV2,
    ResumeAnalysisCommandV2,
    RetryAnalysisCommandV2,
    StartAnalysisCommandV2,
)


@dataclass(frozen=True)
class VerifiedTenantScopeV3:
    tenant_key: str
    tenant_id: UUID
    company_id: UUID
    initiating_subject_id: str


@dataclass(frozen=True)
class RunScopeClaimV3:
    claim_id: UUID
    run_id: str
    application_scope: ApplicationScopeDTO
    persistence_scope: PersistenceRunScopeV3
    initiating_subject_id: str
    application_command_digest: str
    status: RunScopeClaimStatus
    version: int
    claim_token: str
    persisted_run_id: UUID | None
    persisted_request_fingerprint: str | None
    persisted_terminal_content_digest: str | None
    claimed_at: datetime
    finalized_at: datetime | None


@dataclass(frozen=True)
class VerifiedApplicationScopeBindingV3:
    run_id: str
    scope: ApplicationScopeDTO
    persistence_scope: PersistenceRunScopeV3
    initiating_subject_id: str
    application_command_digest: str
    claim_id: UUID
    claim_version: int
    claim_status: RunScopeClaimStatus


@dataclass(frozen=True)
class PlannedSamePeriodSourceEdgeV3:
    role: AnalysisSourceRole
    source_document_id: UUID | None
    existing_source_analysis_result_id: UUID | None
    same_run_source_engine_code: ApplicationEngineCodeV2 | None

    def __post_init__(self) -> None:
        if sum(x is not None for x in (self.source_document_id, self.existing_source_analysis_result_id, self.same_run_source_engine_code)) != 1:
            raise ValueError("same-period source edge requires exact locator XOR")


@dataclass(frozen=True)
class PlannedCashFlowLineageEdgeV3:
    source_role: CashFlowSourceRole
    existing_source_analysis_result_id: UUID | None
    same_run_source_engine_code: ApplicationEngineCodeV2 | None
    source_period_id: UUID
    source_canonical_digest: str
    source_provenance_digest: str
    source_analysis_type: AnalysisType
    source_engine_version: str
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None

    def __post_init__(self) -> None:
        if (self.existing_source_analysis_result_id is None) == (self.same_run_source_engine_code is None):
            raise ValueError("Cash Flow lineage locator must be exact XOR")


@dataclass(frozen=True)
class ResolvedFinancialOwnerNodeV3:
    engine_code: ApplicationEngineCodeV2
    expected_existing_owner_id: UUID | None
    allow_existing_canonical_owner: bool
    create_new_owner: bool
    primary_document_id: UUID | None
    source_mode: ApplicationFinancialSourceModeV2
    same_period_lineage_plan: tuple[PlannedSamePeriodSourceEdgeV3, ...]
    cash_flow_lineage_plan: tuple[PlannedCashFlowLineageEdgeV3, ...]
    expected_canonical_result_digest: str | None
    expected_owner_content_digest: str
    expected_current_period_descriptor_digest: str | None
    expected_prior_period_descriptor_digest: str | None
    expected_comparability_proof_digest: str | None


@dataclass(frozen=True)
class ResolvedFinancialOwnershipPlanV3:
    nodes: tuple[ResolvedFinancialOwnerNodeV3, ...]
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True)
class ApplicationTerminalPersistenceRequestV3:
    verified_scope: VerifiedApplicationScopeBindingV3
    run_result: OrchestrationRunResultV3
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    resume_context: ResumePersistenceContextV3 | None
    financial_ownership_plan: ResolvedFinancialOwnershipPlanV3
    telemetry: ExecutionTelemetryV3 | None


@dataclass(frozen=True)
class TerminalPersistenceResultV3:
    persisted_run: PersistedRunV3
    idempotent_replay: bool


@dataclass(frozen=True)
class InternalRunViewV3:
    persisted_run: PersistedRunV3
    status: ApplicationStatus
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    previous_run_id: str | None


@dataclass(frozen=True)
class AuthorizedResumeSourceViewV3:
    run: InternalRunViewV3
    verified_scope: VerifiedApplicationScopeBindingV3
    payloads_materialized: bool
    snapshot_load_result: SnapshotLoadResultV3 | None


class ApplicationV2PortErrorCode(str, Enum):
    NOT_FOUND = "not_found"
    SCOPE_MISMATCH = "scope_mismatch"
    CONFLICT = "conflict"
    INTEGRITY = "integrity"
    UNAVAILABLE = "unavailable"


_PORT_MESSAGES = {
    ApplicationV2PortErrorCode.NOT_FOUND: "Requested application resource was not found.",
    ApplicationV2PortErrorCode.SCOPE_MISMATCH: "Application scope verification failed.",
    ApplicationV2PortErrorCode.CONFLICT: "Application persistence conflict.",
    ApplicationV2PortErrorCode.INTEGRITY: "Application persistence integrity verification failed.",
    ApplicationV2PortErrorCode.UNAVAILABLE: "Application persistence is unavailable.",
}


@final
class ApplicationV2PortError(Exception):
    __slots__ = ("code", "safe_message")

    def __init__(self, code: ApplicationV2PortErrorCode) -> None:
        self.code = code
        self.safe_message = _PORT_MESSAGES[code]
        super().__init__(self.safe_message)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ApplicationV2PortError is final")


class AnalysisOrchestratorPortV3(Protocol):
    def run(self, request, *, cancellation_probe: Callable[[], bool] | None = None): ...


class AnalysisExecutionGatewayPortV2(Protocol):
    def start(self, command: StartAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def resume(self, command: ResumeAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def retry(self, command: RetryAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def cancel(self, command: CancelAnalysisCommandV2) -> ApplicationOutcomeV2[CancellationResultDTOV2]: ...


class AnalysisReadPortV2(Protocol):
    def get_run_by_id(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3) -> InternalRunViewV3 | None: ...
    def get_status(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3) -> AnalysisRunStatusDTOV2 | None: ...
    def get_result(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, *, include_payloads: bool) -> AnalysisResultDTOV2 | None: ...
    def get_execution_detail(self, run_id: str, engine_code: ApplicationEngineCodeV2, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, *, include_payload: bool) -> AnalysisExecutionDTOV2 | None: ...
    def list_history(self, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, cursor: str | None, limit: int) -> AnalysisHistoryPageDTOV2: ...
    def load_scope(self, run_id: str, verified_tenant: VerifiedTenantScopeV3) -> VerifiedApplicationScopeBindingV3 | None: ...
    def load_resume_source(self, previous_run_id: str, target_scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, *, materialize_payloads: bool) -> AuthorizedResumeSourceViewV3: ...


class RunPersistencePortV3(Protocol):
    def persist_terminal_run(self, request: ApplicationTerminalPersistenceRequestV3) -> TerminalPersistenceResultV3: ...
    def build_previous_execution_snapshot(self, run_id: str, target_scope: PersistenceRunScopeV3) -> SnapshotLoadResultV3: ...
    def resolve_financial_ownership_plan(self, run_result: OrchestrationRunResultV3, source_intents: tuple[FinancialSourceIntentDTOV2, ...], cash_flow_request: CashFlowRequestDTOV2 | None, pre_resolved_context: CashFlowPreResolvedContext | None, verified_scope: VerifiedApplicationScopeBindingV3, started_at: datetime, completed_at: datetime) -> ResolvedFinancialOwnershipPlanV3: ...
    def resolve_payload_references(self, run_id: str, verified_scope: VerifiedApplicationScopeBindingV3, *, include_payloads: bool) -> tuple[ApplicationPayloadEnvelopeDTOV2, ...]: ...


class TenantScopeResolverPortV3(Protocol):
    def resolve(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> VerifiedTenantScopeV3: ...


class RunScopeClaimPortV3(Protocol):
    def claim(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, application_command_digest: str, claimed_at: datetime) -> RunScopeClaimV3: ...
    def verify(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, claim_token: str, expected_version: int) -> RunScopeClaimV3: ...
    def finalize(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, claim_token: str, expected_version: int, persisted_run: PersistedRunV3, finalized_at: datetime) -> RunScopeClaimV3: ...
    def load(self, run_id: str) -> RunScopeClaimV3 | None: ...


@dataclass(frozen=True)
class ResolvedCashFlowPreRunSources:
    prior_balance_sheet: CashFlowSourceSnapshot | None
    current_trial_balance: CashFlowSourceSnapshot | None
    prior_trial_balance: CashFlowSourceSnapshot | None
    account_evidence: tuple[CashFlowAccountEvidence, ...]
    noncash_bridge_components: tuple[CashFlowNonCashBridgeComponent, ...]
    pre_resolved_evidence_bundle_digest: str
    source_candidate_set_digest: str
    opening_account_coverage_complete: bool
    closing_account_coverage_complete: bool


class ComparablePeriodResolutionStatus(str, Enum):
    EXACT_MATCH = "exact_match"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class ComparablePeriodResolution:
    status: ComparablePeriodResolutionStatus
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    comparability_proof_digest: str | None
    candidate_count: int

    def __post_init__(self) -> None:
        exact = self.status is ComparablePeriodResolutionStatus.EXACT_MATCH
        if exact:
            if self.candidate_count != 1 or self.prior_period is None or self.comparability_proof_digest is None:
                raise ValueError("exact comparable period requires one proven candidate")
        elif self.candidate_count != 0 or self.prior_period is not None or self.comparability_proof_digest is not None:
            raise ValueError("no-match comparable period cannot carry a prior proof")


class ComparablePeriodResolverPort(Protocol):
    def resolve_exact_prior_period(
        self, *, tenant_id: UUID, company_id: UUID, current_period_id: UUID,
        required_currency_code: str, accounting_basis_code: str,
        accounting_policy_version: str,
    ) -> ComparablePeriodResolution: ...


class CashFlowSourceResolverPort(Protocol):
    def resolve_pre_run_sources(
        self, *, tenant_id: UUID, company_id: UUID, current_period_id: UUID,
        prior_period_id: UUID | None,
    ) -> ResolvedCashFlowPreRunSources: ...
