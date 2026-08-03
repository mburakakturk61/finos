"""Framework-independent Cash Flow cross-period lineage contracts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, final
from uuid import UUID

from app.models.enums import AnalysisType

from .contracts import canonical_cash_flow_bytes
from .errors import CashFlowContractError
from .types import CashFlowErrorCode, CashFlowResultStatus, CashFlowSourceRole


CASH_FLOW_LINEAGE_SCHEMA_VERSION = "1.0.0"
CASH_FLOW_LINEAGE_POLICY_VERSION = "1.0.0"

_ROLE_TYPE = {
    CashFlowSourceRole.CURRENT_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.PRIOR_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.CURRENT_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    CashFlowSourceRole.CURRENT_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    CashFlowSourceRole.PRIOR_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
}
_BASE_ROLES = frozenset(
    {
        CashFlowSourceRole.CURRENT_BALANCE_SHEET,
        CashFlowSourceRole.PRIOR_BALANCE_SHEET,
        CashFlowSourceRole.CURRENT_INCOME_STATEMENT,
    }
)
_RESULT_STATUSES = frozenset(tuple(CashFlowResultStatus)[:5])


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise CashFlowContractError(f"{name} must be a lowercase SHA-256 digest")
    return value


@final
@dataclass(frozen=True, repr=False)
class ResolvedCashFlowLineageEdge:
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
        if type(self.source_role) is not CashFlowSourceRole:
            raise CashFlowContractError("invalid Cash Flow lineage source role")
        if type(self.source_analysis_result_id) is not UUID or type(self.source_period_id) is not UUID:
            raise CashFlowContractError("lineage source identities must be UUID")
        if type(self.source_analysis_type) is not AnalysisType or _ROLE_TYPE[self.source_role] is not self.source_analysis_type:
            raise CashFlowContractError("lineage role and source analysis type do not match")
        if type(self.source_engine_version) is not str or not self.source_engine_version or len(self.source_engine_version) > 32:
            raise CashFlowContractError("invalid source engine version")
        for name in (
            "source_canonical_digest",
            "source_provenance_digest",
            "current_period_descriptor_digest",
        ):
            _digest(getattr(self, name), name)
        for name in ("prior_period_descriptor_digest", "comparability_proof_digest"):
            value = getattr(self, name)
            if value is not None:
                _digest(value, name)
        if (self.prior_period_descriptor_digest is None) != (self.comparability_proof_digest is None):
            raise CashFlowContractError("prior period descriptor and comparability proof must be both null or both set")

    def __repr__(self) -> str:
        return "ResolvedCashFlowLineageEdge()"

    __str__ = __repr__


def canonical_cash_flow_lineage_set_digest(
    *,
    owner_analysis_result_id: UUID,
    current_period_id: UUID,
    prior_period_id: UUID | None,
    owner_payload_digest: str,
    lineage: tuple[ResolvedCashFlowLineageEdge, ...],
) -> str:
    if type(owner_analysis_result_id) is not UUID or type(current_period_id) is not UUID:
        raise CashFlowContractError("lineage owner/current period identities must be UUID")
    if prior_period_id is not None and type(prior_period_id) is not UUID:
        raise CashFlowContractError("prior period identity must be UUID or null")
    _digest(owner_payload_digest, "owner_payload_digest")
    ordered = _canonical_lineage(lineage)
    projection = (
        "cf.lineage_set.v1",
        CASH_FLOW_LINEAGE_SCHEMA_VERSION,
        CASH_FLOW_LINEAGE_POLICY_VERSION,
        owner_analysis_result_id,
        current_period_id,
        prior_period_id,
        owner_payload_digest,
        tuple(
            (
                item.source_role,
                item.source_analysis_result_id,
                item.source_period_id,
                item.source_canonical_digest,
                item.source_provenance_digest,
                item.source_analysis_type,
                item.source_engine_version,
                item.current_period_descriptor_digest,
                item.prior_period_descriptor_digest,
                item.comparability_proof_digest,
            )
            for item in ordered
        ),
    )
    return sha256(b"cash-flow/lineage-set/v1\0" + canonical_cash_flow_bytes(projection)).hexdigest()


def _canonical_lineage(
    lineage: tuple[ResolvedCashFlowLineageEdge, ...],
) -> tuple[ResolvedCashFlowLineageEdge, ...]:
    if type(lineage) is not tuple or any(type(item) is not ResolvedCashFlowLineageEdge for item in lineage):
        raise CashFlowContractError("lineage must be an immutable edge tuple")
    roles = tuple(item.source_role for item in lineage)
    sources = tuple(item.source_analysis_result_id for item in lineage)
    if len(set(roles)) != len(roles):
        raise CashFlowContractError("duplicate Cash Flow lineage role")
    if len(set(sources)) != len(sources):
        raise CashFlowContractError("one source cannot satisfy multiple lineage roles")
    return tuple(sorted(lineage, key=lambda item: tuple(CashFlowSourceRole).index(item.source_role)))


def validate_cash_flow_lineage_role_set(
    status: CashFlowResultStatus,
    lineage: tuple[ResolvedCashFlowLineageEdge, ...],
) -> tuple[ResolvedCashFlowLineageEdge, ...]:
    if type(status) is not CashFlowResultStatus or status not in _RESULT_STATUSES:
        raise CashFlowContractError("lineage requires a result-bearing Cash Flow status")
    ordered = _canonical_lineage(lineage)
    roles = frozenset(item.source_role for item in ordered)
    if status is not CashFlowResultStatus.INSUFFICIENT_DATA and not _BASE_ROLES.issubset(roles):
        raise CashFlowContractError("complete/partial Cash Flow lineage misses a required base role")
    return ordered


@final
@dataclass(frozen=True, repr=False)
class VerifiedCashFlowLineage:
    cash_flow_owner_id: UUID
    tenant_id: UUID
    company_id: UUID
    current_period_id: UUID
    prior_period_id: UUID | None
    cash_flow_status: CashFlowResultStatus
    owner_payload_digest: str
    lineage: tuple[ResolvedCashFlowLineageEdge, ...]
    source_set_digest: str

    def __repr__(self) -> str:
        return "VerifiedCashFlowLineage()"

    __str__ = __repr__


@final
class CashFlowPortError(Exception):
    __slots__ = ("_code", "_sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("CashFlowPortError is final")

    def __init__(self, code: CashFlowErrorCode) -> None:
        if code not in {CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE, CashFlowErrorCode.PERSISTENCE_UNAVAILABLE}:
            raise CashFlowContractError("invalid lineage persistence error code")
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("CashFlowPortError is immutable")
        object.__setattr__(self, name, value)

    @property
    def code(self) -> CashFlowErrorCode:
        return self._code

    @property
    def retryable(self) -> bool:
        return self._code is CashFlowErrorCode.PERSISTENCE_UNAVAILABLE

    def __repr__(self) -> str:
        return f"CashFlowPortError(code={self._code.value})"

    __str__ = __repr__


class CashFlowLineageRepositoryPort(Protocol):
    def stage_exact_lineage(
        self,
        *,
        cash_flow_owner_id: UUID,
        tenant_id: UUID,
        company_id: UUID,
        current_period_id: UUID,
        prior_period_id: UUID | None,
        cash_flow_status: CashFlowResultStatus,
        lineage: tuple[ResolvedCashFlowLineageEdge, ...],
    ) -> None: ...

    def load_verified_lineage(self, cash_flow_owner_id: UUID) -> VerifiedCashFlowLineage: ...
