"""Framework-independent immutable N-period lineage contracts for 4.6G."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from hmac import compare_digest
from typing import Protocol, final
from uuid import UUID

from .canonical import canonical_trend_bytes, validate_sha256, validate_trend_reference
from .contracts import TrendContractError
from .types import TrendContractVersion, TrendEvidenceLevel, TrendPolicyVersion


TREND_LINEAGE_SCHEMA_VERSION = "1.0.0"
TREND_LINEAGE_REFERENCE_PREFIX = "trend-lineage:v1:sha256:"


class TrendLineageSourceRole(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    FINANCIAL_RATIOS = "financial_ratios"


class TrendLineageSourceEngineCode(str, Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    CASH_FLOW = "cash_flow"
    RATIO = "ratio"


class TrendLineageSourceAnalysisType(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    FINANCIAL_RATIOS = "financial_ratios"


class TrendLineagePortErrorCode(str, Enum):
    CONFLICT = "conflict"
    INTEGRITY_FAILURE = "integrity_failure"
    LOCK_TIMEOUT = "lock_timeout"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"


_ROLE_BINDINGS = {
    TrendLineageSourceRole.BALANCE_SHEET: (
        TrendLineageSourceEngineCode.FS_BALANCE_SHEET,
        TrendLineageSourceAnalysisType.BALANCE_SHEET,
    ),
    TrendLineageSourceRole.INCOME_STATEMENT: (
        TrendLineageSourceEngineCode.FS_INCOME_STATEMENT,
        TrendLineageSourceAnalysisType.INCOME_STATEMENT,
    ),
    TrendLineageSourceRole.CASH_FLOW: (
        TrendLineageSourceEngineCode.CASH_FLOW,
        TrendLineageSourceAnalysisType.CASH_FLOW,
    ),
    TrendLineageSourceRole.FINANCIAL_RATIOS: (
        TrendLineageSourceEngineCode.RATIO,
        TrendLineageSourceAnalysisType.FINANCIAL_RATIOS,
    ),
}


class _SafeLineageValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _text(value: object, name: str, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise TrendContractError(f"{name} must be bounded non-empty text")
    return value


@final
@dataclass(frozen=True, repr=False)
class TrendLineageEdge(_SafeLineageValue):
    ordinal: int
    source_period_id: UUID
    source_analysis_result_id: UUID
    source_role: TrendLineageSourceRole
    source_engine_code: TrendLineageSourceEngineCode
    source_analysis_type: TrendLineageSourceAnalysisType
    source_canonical_digest: str
    source_schema_version: str | None
    source_model_version: str
    observation_evidence: TrendEvidenceLevel
    comparability_proof_digest: str
    resolution_proof_reference: str
    lineage_schema_version: str = TREND_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise TrendContractError("lineage ordinal must be a non-negative integer")
        if type(self.source_period_id) is not UUID or type(self.source_analysis_result_id) is not UUID:
            raise TrendContractError("lineage source identities must be UUID")
        if (
            type(self.source_role) is not TrendLineageSourceRole
            or type(self.source_engine_code) is not TrendLineageSourceEngineCode
            or type(self.source_analysis_type) is not TrendLineageSourceAnalysisType
            or _ROLE_BINDINGS[self.source_role]
            != (self.source_engine_code, self.source_analysis_type)
        ):
            raise TrendContractError("lineage role, engine, and analysis type do not match")
        validate_sha256(self.source_canonical_digest, "source_canonical_digest")
        validate_sha256(self.comparability_proof_digest, "comparability_proof_digest")
        if self.source_schema_version is not None:
            _text(self.source_schema_version, "source_schema_version", 32)
        _text(self.source_model_version, "source_model_version", 32)
        if type(self.observation_evidence) is not TrendEvidenceLevel:
            raise TrendContractError("lineage evidence must be exact enum")
        validate_trend_reference(self.resolution_proof_reference)
        if self.lineage_schema_version != TREND_LINEAGE_SCHEMA_VERSION:
            raise TrendContractError("unsupported trend lineage schema version")


def _canonical_edges(edges: tuple[TrendLineageEdge, ...]) -> tuple[TrendLineageEdge, ...]:
    if type(edges) is not tuple or not edges or any(type(item) is not TrendLineageEdge for item in edges):
        raise TrendContractError("trend lineage must be a non-empty immutable exact tuple")
    role_order = {item: index for index, item in enumerate(TrendLineageSourceRole)}
    ordered = tuple(sorted(edges, key=lambda item: (item.ordinal, role_order[item.source_role])))
    if len({(item.ordinal, item.source_role) for item in ordered}) != len(ordered):
        raise TrendContractError("duplicate lineage ordinal/role")
    if len({(item.source_period_id, item.source_role) for item in ordered}) != len(ordered):
        raise TrendContractError("duplicate lineage period/role")
    if len({item.source_analysis_result_id for item in ordered}) != len(ordered):
        raise TrendContractError("one source cannot occupy multiple trend lineage rows")
    period_by_ordinal: dict[int, UUID] = {}
    for item in ordered:
        previous = period_by_ordinal.setdefault(item.ordinal, item.source_period_id)
        if previous != item.source_period_id:
            raise TrendContractError("one ordinal cannot identify multiple periods")
    if tuple(sorted(period_by_ordinal)) != tuple(range(len(period_by_ordinal))):
        raise TrendContractError("trend lineage ordinals must be zero-based and gapless")
    return ordered


def canonical_trend_lineage_set_digest(
    *,
    company_id: UUID,
    anchor_period_id: UUID,
    metric_registry_version: str,
    metric_registry_digest: str,
    policy_version: TrendPolicyVersion,
    contract_version: TrendContractVersion,
    lineage: tuple[TrendLineageEdge, ...],
) -> str:
    if type(company_id) is not UUID or type(anchor_period_id) is not UUID:
        raise TrendContractError("trend lineage scope identities must be UUID")
    _text(metric_registry_version, "metric_registry_version", 64)
    validate_sha256(metric_registry_digest, "metric_registry_digest")
    if type(policy_version) is not TrendPolicyVersion or type(contract_version) is not TrendContractVersion:
        raise TrendContractError("trend lineage policy/contract version is invalid")
    ordered = _canonical_edges(lineage)
    max_ordinal = max(item.ordinal for item in ordered)
    if {item.source_period_id for item in ordered if item.ordinal == max_ordinal} != {anchor_period_id}:
        raise TrendContractError("trend lineage anchor must equal the highest ordinal period")
    projection = (
        TREND_LINEAGE_SCHEMA_VERSION,
        company_id,
        anchor_period_id,
        metric_registry_version,
        metric_registry_digest,
        policy_version,
        contract_version,
        tuple(
            (
                item.ordinal,
                item.source_period_id,
                item.source_analysis_result_id,
                item.source_role,
                item.source_engine_code,
                item.source_analysis_type,
                item.source_canonical_digest,
                item.source_schema_version,
                item.source_model_version,
                item.observation_evidence,
                item.comparability_proof_digest,
                item.resolution_proof_reference,
                item.lineage_schema_version,
            )
            for item in ordered
        ),
    )
    return sha256(b"multi-period-trend/lineage-set/v1\0" + canonical_trend_bytes(projection)).hexdigest()


@final
@dataclass(frozen=True, repr=False)
class TrendLineageSet(_SafeLineageValue):
    trend_analysis_result_id: UUID
    tenant_id: UUID
    company_id: UUID
    anchor_period_id: UUID
    metric_registry_version: str
    metric_registry_digest: str
    policy_version: TrendPolicyVersion
    contract_version: TrendContractVersion
    lineage: tuple[TrendLineageEdge, ...]
    source_set_digest: str
    source_set_reference: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID
            for value in (
                self.trend_analysis_result_id,
                self.tenant_id,
                self.company_id,
                self.anchor_period_id,
            )
        ):
            raise TrendContractError("trend lineage owner/scope identities must be UUID")
        ordered = _canonical_edges(self.lineage)
        object.__setattr__(self, "lineage", ordered)
        expected = canonical_trend_lineage_set_digest(
            company_id=self.company_id,
            anchor_period_id=self.anchor_period_id,
            metric_registry_version=self.metric_registry_version,
            metric_registry_digest=self.metric_registry_digest,
            policy_version=self.policy_version,
            contract_version=self.contract_version,
            lineage=ordered,
        )
        validate_sha256(self.source_set_digest, "source_set_digest")
        if not compare_digest(self.source_set_digest, expected):
            raise TrendContractError("trend lineage source-set digest mismatch")
        if self.source_set_reference != TREND_LINEAGE_REFERENCE_PREFIX + expected:
            raise TrendContractError("trend lineage source-set reference mismatch")


def build_trend_lineage_set(
    *,
    trend_analysis_result_id: UUID,
    tenant_id: UUID,
    company_id: UUID,
    anchor_period_id: UUID,
    metric_registry_version: str,
    metric_registry_digest: str,
    policy_version: TrendPolicyVersion,
    contract_version: TrendContractVersion,
    lineage: tuple[TrendLineageEdge, ...],
) -> TrendLineageSet:
    digest = canonical_trend_lineage_set_digest(
        company_id=company_id,
        anchor_period_id=anchor_period_id,
        metric_registry_version=metric_registry_version,
        metric_registry_digest=metric_registry_digest,
        policy_version=policy_version,
        contract_version=contract_version,
        lineage=lineage,
    )
    return TrendLineageSet(
        trend_analysis_result_id=trend_analysis_result_id,
        tenant_id=tenant_id,
        company_id=company_id,
        anchor_period_id=anchor_period_id,
        metric_registry_version=metric_registry_version,
        metric_registry_digest=metric_registry_digest,
        policy_version=policy_version,
        contract_version=contract_version,
        lineage=lineage,
        source_set_digest=digest,
        source_set_reference=TREND_LINEAGE_REFERENCE_PREFIX + digest,
    )


@final
@dataclass(frozen=True, repr=False)
class VerifiedTrendLineage(_SafeLineageValue):
    owner_payload_digest: str
    lineage_set: TrendLineageSet

    def __post_init__(self) -> None:
        validate_sha256(self.owner_payload_digest, "owner_payload_digest")
        if type(self.lineage_set) is not TrendLineageSet:
            raise TrendContractError("verified lineage requires exact lineage set")


@final
class TrendLineagePortError(Exception):
    __slots__ = ("_code", "_sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("TrendLineagePortError is final")

    def __init__(self, code: TrendLineagePortErrorCode) -> None:
        if type(code) is not TrendLineagePortErrorCode:
            raise TrendContractError("lineage port error code must be exact enum")
        Exception.__init__(self)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False) and name != "__traceback__":
            raise AttributeError("TrendLineagePortError is immutable")
        object.__setattr__(self, name, value)

    def __getattribute__(self, name: str) -> object:
        if name in {"__cause__", "__context__"}:
            return None
        return object.__getattribute__(self, name)

    @property
    def code(self) -> TrendLineagePortErrorCode:
        return self._code

    @property
    def retryable(self) -> bool:
        return self._code in {
            TrendLineagePortErrorCode.LOCK_TIMEOUT,
            TrendLineagePortErrorCode.PERSISTENCE_UNAVAILABLE,
        }

    @property
    def args(self) -> tuple[()]:
        return ()

    def __repr__(self) -> str:
        return f"TrendLineagePortError(code={self._code.value})"

    __str__ = __repr__


class TrendLineageRepositoryPort(Protocol):
    def stage_exact_lineage(self, lineage_set: TrendLineageSet) -> VerifiedTrendLineage: ...

    def load_verified_lineage(self, trend_analysis_result_id: UUID) -> VerifiedTrendLineage: ...
