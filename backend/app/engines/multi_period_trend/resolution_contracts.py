"""Framework-independent contracts for Milestone 4.6C series resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Protocol
from uuid import UUID

from .canonical import canonical_trend_digest, canonical_trend_reference, normalize_decimal, validate_sha256
from .contracts import TrendGap, TrendObservation, TrendSegmentBoundary
from .registry import TrendSourceAnalysisType
from .types import (
    TrendCoverageKind,
    TrendEvidenceLevel,
    TrendOneOffStatus,
    TrendPeriodFamily,
    TrendRestatementProfile,
    TrendSourceEngineType,
)


TREND_SERIES_RESOLUTION_CONTRACT_VERSION = "trend-series-resolution/1.0.0"
TREND_COMPARABILITY_PROFILE_VERSION_V1 = "trend-comparability/1.0.0"


class TrendSeriesResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    INSUFFICIENT_FOR_TREND = "insufficient_for_trend"
    INSUFFICIENT_DATA = "insufficient_data"
    NON_COMPARABLE = "non_comparable"
    FAILED = "failed"


class TrendSeriesResolutionErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    INVALID_PERIOD_SET = "invalid_period_set"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_SCOPE_MISMATCH = "source_scope_mismatch"
    SOURCE_STATUS_INVALID = "source_status_invalid"
    SOURCE_VERSION_UNSUPPORTED = "source_version_unsupported"
    SOURCE_DIGEST_MISMATCH = "source_digest_mismatch"
    SOURCE_SET_CHANGED = "source_set_changed"
    STALE_RESTATEMENT_SOURCE = "stale_restatement_source"
    AMBIGUOUS_SOURCE = "ambiguous_source"
    INCOMPATIBLE_PERIOD = "incompatible_period"
    COMPANY_MISMATCH = "company_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    ACCOUNTING_POLICY_MISMATCH = "accounting_policy_mismatch"
    PERIOD_METADATA_INTEGRITY_FAILURE = "period_metadata_integrity_failure"
    REGISTRY_INTEGRITY_FAILURE = "registry_integrity_failure"
    RESOLUTION_UNAVAILABLE = "resolution_unavailable"
    STORE_TIMEOUT = "store_timeout"
    STORE_UNAVAILABLE = "store_unavailable"
    INTEGRITY_FAILURE = "integrity_failure"


class TrendSourceSelectionRole(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    FINANCIAL_RATIOS = "financial_ratios"


class TrendResolvedPeriodType(str, Enum):
    YEAR_END = "year_end"
    MONTHLY = "monthly"
    QUARTER = "quarter"
    TEMPORARY_TAX = "temporary_tax"
    CUSTOM = "custom"


class TrendResolvedPeriodStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"
    APPROVED = "approved"


class TrendResolvedSourceStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
    PROCESSING = "processing"


class TrendSeriesResolutionContractError(ValueError):
    __slots__ = ()


class _SafeResolutionValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _uuid(value: object, name: str) -> UUID:
    if type(value) is not UUID:
        raise TrendSeriesResolutionContractError(f"{name} must be UUID")
    return value


def _text(value: object, name: str, maximum: int = 128) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise TrendSeriesResolutionContractError(f"{name} must be bounded non-empty text")
    return value


def _utc(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TrendSeriesResolutionContractError(f"{name} must be timezone-aware datetime")
    normalized = value.astimezone(timezone.utc)
    return normalized


@dataclass(frozen=True, repr=False)
class TrendSourceSelectionIntent(_SafeResolutionValue):
    period_id: UUID
    source_role: TrendSourceSelectionRole
    analysis_result_id: UUID

    def __post_init__(self) -> None:
        _uuid(self.period_id, "period_id")
        _uuid(self.analysis_result_id, "analysis_result_id")
        if type(self.source_role) is not TrendSourceSelectionRole:
            raise TrendSeriesResolutionContractError("source_role must be exact enum")


@dataclass(frozen=True, repr=False)
class TrendSeriesResolutionRequest(_SafeResolutionValue):
    tenant_id: UUID
    company_id: UUID
    anchor_period_id: UUID
    metric_code: str
    explicit_period_ids: tuple[UUID, ...]
    explicit_sources: tuple[TrendSourceSelectionIntent, ...]
    expected_period_family: TrendPeriodFamily
    expected_currency: str
    expected_monetary_unit_multiplier: Decimal
    expected_accounting_basis: str
    expected_accounting_policy_version: str
    fiscal_calendar_reference: str
    comparability_profile_version: str
    expected_metric_registry_version: str
    expected_metric_registry_digest: str
    correlation_reference: str
    resolution_timestamp: datetime

    def __post_init__(self) -> None:
        _uuid(self.tenant_id, "tenant_id")
        _uuid(self.company_id, "company_id")
        _uuid(self.anchor_period_id, "anchor_period_id")
        _text(self.metric_code, "metric_code", 80)
        if type(self.explicit_period_ids) is not tuple or not 2 <= len(self.explicit_period_ids) <= 60:
            raise TrendSeriesResolutionContractError("explicit_period_ids must contain 2..60 UUIDs")
        if any(type(item) is not UUID for item in self.explicit_period_ids):
            raise TrendSeriesResolutionContractError("explicit_period_ids must contain UUIDs")
        if len(set(self.explicit_period_ids)) != len(self.explicit_period_ids):
            raise TrendSeriesResolutionContractError("duplicate period intent")
        if self.anchor_period_id not in self.explicit_period_ids:
            raise TrendSeriesResolutionContractError("anchor period must be explicit")
        if type(self.explicit_sources) is not tuple or any(
            type(item) is not TrendSourceSelectionIntent for item in self.explicit_sources
        ):
            raise TrendSeriesResolutionContractError("explicit_sources must be exact tuple")
        source_ids = tuple(item.analysis_result_id for item in self.explicit_sources)
        source_keys = tuple((item.period_id, item.source_role) for item in self.explicit_sources)
        if len(set(source_ids)) != len(source_ids):
            raise TrendSeriesResolutionContractError("duplicate source result intent")
        if len(set(source_keys)) != len(source_keys):
            raise TrendSeriesResolutionContractError("ambiguous source intent")
        if set(item.period_id for item in self.explicit_sources) != set(self.explicit_period_ids):
            raise TrendSeriesResolutionContractError("each explicit period requires exactly one source intent")
        if type(self.expected_period_family) is not TrendPeriodFamily:
            raise TrendSeriesResolutionContractError("expected_period_family must be exact enum")
        if self.expected_currency != "TRY":
            raise TrendSeriesResolutionContractError("v1 resolution requires TRY")
        if self.expected_monetary_unit_multiplier != Decimal("1"):
            raise TrendSeriesResolutionContractError("v1 resolution requires monetary multiplier 1")
        _text(self.expected_accounting_basis, "expected_accounting_basis", 64)
        _text(self.expected_accounting_policy_version, "expected_accounting_policy_version", 96)
        _text(self.fiscal_calendar_reference, "fiscal_calendar_reference", 128)
        if self.comparability_profile_version != TREND_COMPARABILITY_PROFILE_VERSION_V1:
            raise TrendSeriesResolutionContractError("unsupported comparability profile")
        _text(self.expected_metric_registry_version, "expected_metric_registry_version", 96)
        validate_sha256(self.expected_metric_registry_digest, "expected_metric_registry_digest")
        _text(self.correlation_reference, "correlation_reference", 128)
        object.__setattr__(self, "resolution_timestamp", _utc(self.resolution_timestamp, "resolution_timestamp"))


@dataclass(frozen=True, repr=False)
class TrendResolvedPeriod(_SafeResolutionValue):
    tenant_id: UUID
    company_id: UUID
    period_id: UUID
    year: int
    period_type: TrendResolvedPeriodType
    fiscal_ordinal: int
    start_date: date
    end_date: date
    months_covered: int
    status: TrendResolvedPeriodStatus
    coverage_kind: TrendCoverageKind
    accounting_basis: str
    accounting_policy_version: str
    fiscal_calendar_reference: str
    currency: str
    monetary_unit_multiplier: Decimal
    restatement_profile: TrendRestatementProfile
    restatement_revision: int
    one_off_status: TrendOneOffStatus

    def __post_init__(self) -> None:
        for name in ("tenant_id", "company_id", "period_id"):
            _uuid(getattr(self, name), name)
        if type(self.year) is not int or not 1900 <= self.year <= 2200:
            raise TrendSeriesResolutionContractError("period year is invalid")
        if type(self.period_type) is not TrendResolvedPeriodType:
            raise TrendSeriesResolutionContractError("period_type must be exact enum")
        if type(self.fiscal_ordinal) is not int or self.fiscal_ordinal <= 0:
            raise TrendSeriesResolutionContractError("fiscal_ordinal must be positive")
        if type(self.start_date) is not date or type(self.end_date) is not date or self.start_date > self.end_date:
            raise TrendSeriesResolutionContractError("period dates are invalid")
        if type(self.months_covered) is not int or self.months_covered <= 0:
            raise TrendSeriesResolutionContractError("months_covered must be positive")
        if type(self.status) is not TrendResolvedPeriodStatus or type(self.coverage_kind) is not TrendCoverageKind:
            raise TrendSeriesResolutionContractError("period status/coverage is invalid")
        for name in ("accounting_basis", "accounting_policy_version", "fiscal_calendar_reference"):
            _text(getattr(self, name), name, 128)
        if (
            type(self.currency) is not str
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
            or self.monetary_unit_multiplier not in {Decimal("1"), Decimal("1000"), Decimal("1000000")}
        ):
            raise TrendSeriesResolutionContractError("period monetary profile is invalid")
        if type(self.restatement_profile) is not TrendRestatementProfile:
            raise TrendSeriesResolutionContractError("restatement_profile must be exact enum")
        if type(self.restatement_revision) is not int or self.restatement_revision < 0:
            raise TrendSeriesResolutionContractError("restatement_revision is invalid")
        if type(self.one_off_status) is not TrendOneOffStatus:
            raise TrendSeriesResolutionContractError("one_off_status must be exact enum")


@dataclass(frozen=True, repr=False)
class TrendResolvedSourceCandidate(_SafeResolutionValue):
    source_role: TrendSourceSelectionRole
    analysis_result_id: UUID
    tenant_id: UUID
    company_id: UUID
    period_id: UUID
    source_engine_type: TrendSourceEngineType
    source_analysis_type: TrendSourceAnalysisType
    source_status: TrendResolvedSourceStatus
    source_field_path: tuple[str, ...]
    source_schema_version: str | None
    source_model_version: str
    canonical_digest: str | None
    recomputed_digest: str | None
    digest_verified: bool
    provenance_verified: bool
    authoritative_chain_head_verified: bool
    value: Decimal | None
    field_present: bool
    source_evidence: TrendEvidenceLevel
    source_mode: str | None
    ratio_status: str | None
    ratio_reliability: str | None

    def __post_init__(self) -> None:
        if type(self.source_role) is not TrendSourceSelectionRole:
            raise TrendSeriesResolutionContractError("source role is invalid")
        for name in ("analysis_result_id", "tenant_id", "company_id", "period_id"):
            _uuid(getattr(self, name), name)
        if type(self.source_engine_type) is not TrendSourceEngineType or type(self.source_analysis_type) is not TrendSourceAnalysisType:
            raise TrendSeriesResolutionContractError("source engine/analysis type is invalid")
        if type(self.source_status) is not TrendResolvedSourceStatus:
            raise TrendSeriesResolutionContractError("source status is invalid")
        if type(self.source_field_path) is not tuple or not self.source_field_path or any(type(item) is not str or not item for item in self.source_field_path):
            raise TrendSeriesResolutionContractError("source_field_path is invalid")
        if self.source_schema_version is not None:
            _text(self.source_schema_version, "source_schema_version", 32)
        _text(self.source_model_version, "source_model_version", 32)
        for value, name in ((self.canonical_digest, "canonical_digest"), (self.recomputed_digest, "recomputed_digest")):
            if value is not None:
                validate_sha256(value, name)
        for name in ("digest_verified", "provenance_verified", "authoritative_chain_head_verified", "field_present"):
            if type(getattr(self, name)) is not bool:
                raise TrendSeriesResolutionContractError(f"{name} must be bool")
        if self.value is not None:
            if type(self.value) is not Decimal or not self.value.is_finite():
                raise TrendSeriesResolutionContractError("source value must be finite Decimal or None")
            object.__setattr__(self, "value", normalize_decimal(self.value))
        if not self.field_present and self.value is not None:
            raise TrendSeriesResolutionContractError("missing field cannot carry value")
        if type(self.source_evidence) is not TrendEvidenceLevel:
            raise TrendSeriesResolutionContractError("source_evidence is invalid")


@dataclass(frozen=True, repr=False)
class TrendSeriesResolutionSnapshot(_SafeResolutionValue):
    periods: tuple[TrendResolvedPeriod, ...]
    sources: tuple[TrendResolvedSourceCandidate, ...]
    candidate_set_digest: str

    def __post_init__(self) -> None:
        if type(self.periods) is not tuple or any(type(item) is not TrendResolvedPeriod for item in self.periods):
            raise TrendSeriesResolutionContractError("period snapshot is invalid")
        if type(self.sources) is not tuple or any(type(item) is not TrendResolvedSourceCandidate for item in self.sources):
            raise TrendSeriesResolutionContractError("source snapshot is invalid")
        validate_sha256(self.candidate_set_digest, "candidate_set_digest")


@dataclass(frozen=True, repr=False)
class ResolvedTrendObservation(_SafeResolutionValue):
    fiscal_ordinal: int
    source_field_path: tuple[str, ...]
    observation: TrendObservation
    observation_digest: str

    def __post_init__(self) -> None:
        if type(self.fiscal_ordinal) is not int or self.fiscal_ordinal <= 0:
            raise TrendSeriesResolutionContractError("fiscal ordinal is invalid")
        if type(self.source_field_path) is not tuple or not self.source_field_path:
            raise TrendSeriesResolutionContractError("source field path is invalid")
        if type(self.observation) is not TrendObservation:
            raise TrendSeriesResolutionContractError("observation must be exact TrendObservation")
        validate_sha256(self.observation_digest, "observation_digest")
        if self.observation_digest != canonical_trend_digest((self.fiscal_ordinal, self.source_field_path, self.observation)):
            raise TrendSeriesResolutionContractError("observation digest mismatch")


@dataclass(frozen=True, repr=False)
class ResolvedTrendSegment(_SafeResolutionValue):
    segment_ordinal: int
    observation_ordinals: tuple[int, ...]
    comparability_proof_digest: str

    def __post_init__(self) -> None:
        if type(self.segment_ordinal) is not int or self.segment_ordinal < 0:
            raise TrendSeriesResolutionContractError("segment ordinal is invalid")
        if type(self.observation_ordinals) is not tuple or not self.observation_ordinals:
            raise TrendSeriesResolutionContractError("segment requires observations")
        if tuple(sorted(self.observation_ordinals)) != self.observation_ordinals:
            raise TrendSeriesResolutionContractError("segment observation ordinals are not canonical")
        validate_sha256(self.comparability_proof_digest, "comparability_proof_digest")


@dataclass(frozen=True, repr=False)
class ResolvedTrendSeries(_SafeResolutionValue):
    tenant_id: UUID
    company_id: UUID
    anchor_period_id: UUID
    metric_code: str
    period_family: TrendPeriodFamily
    currency: str
    monetary_unit_multiplier: Decimal
    observations: tuple[ResolvedTrendObservation, ...]
    gaps: tuple[TrendGap, ...]
    segment_boundaries: tuple[TrendSegmentBoundary, ...]
    segments: tuple[ResolvedTrendSegment, ...]
    candidate_set_digest: str
    resolution_digest: str
    resolution_reference: str
    nominal_values: bool
    inflation_adjusted: bool
    contract_version: str

    def __post_init__(self) -> None:
        for name in ("tenant_id", "company_id", "anchor_period_id"):
            _uuid(getattr(self, name), name)
        _text(self.metric_code, "metric_code", 80)
        if type(self.period_family) is not TrendPeriodFamily:
            raise TrendSeriesResolutionContractError("period_family is invalid")
        if self.currency != "TRY" or self.monetary_unit_multiplier != Decimal("1"):
            raise TrendSeriesResolutionContractError("series monetary profile is invalid")
        if type(self.observations) is not tuple or any(type(item) is not ResolvedTrendObservation for item in self.observations):
            raise TrendSeriesResolutionContractError("observations are invalid")
        if not 2 <= len(self.observations) <= 60:
            raise TrendSeriesResolutionContractError("resolved series requires 2..60 observations")
        if tuple(item.observation.ordinal for item in self.observations) != tuple(range(len(self.observations))):
            raise TrendSeriesResolutionContractError("observation order is not canonical")
        if self.observations[-1].observation.period_id != self.anchor_period_id:
            raise TrendSeriesResolutionContractError("anchor must be final observation")
        if type(self.gaps) is not tuple or any(type(item) is not TrendGap for item in self.gaps):
            raise TrendSeriesResolutionContractError("gaps are invalid")
        if type(self.segment_boundaries) is not tuple or any(type(item) is not TrendSegmentBoundary for item in self.segment_boundaries):
            raise TrendSeriesResolutionContractError("segment boundaries are invalid")
        if type(self.segments) is not tuple or any(type(item) is not ResolvedTrendSegment for item in self.segments):
            raise TrendSeriesResolutionContractError("segments are invalid")
        validate_sha256(self.candidate_set_digest, "candidate_set_digest")
        validate_sha256(self.resolution_digest, "resolution_digest")
        if self.resolution_reference != canonical_trend_reference(self.resolution_digest):
            raise TrendSeriesResolutionContractError("resolution reference mismatch")
        if self.nominal_values is not True or self.inflation_adjusted is not False:
            raise TrendSeriesResolutionContractError("v1 series must be nominal and not inflation-adjusted")
        if self.contract_version != TREND_SERIES_RESOLUTION_CONTRACT_VERSION:
            raise TrendSeriesResolutionContractError("unsupported resolution contract version")


@dataclass(frozen=True, repr=False)
class TrendSeriesResolutionResult(_SafeResolutionValue):
    status: TrendSeriesResolutionStatus
    series: ResolvedTrendSeries | None
    error_code: TrendSeriesResolutionErrorCode | None

    def __post_init__(self) -> None:
        if type(self.status) is not TrendSeriesResolutionStatus:
            raise TrendSeriesResolutionContractError("resolution status is invalid")
        if self.status is TrendSeriesResolutionStatus.FAILED:
            if self.series is not None or type(self.error_code) is not TrendSeriesResolutionErrorCode:
                raise TrendSeriesResolutionContractError("failed result requires only typed error")
        elif type(self.series) is not ResolvedTrendSeries or self.error_code is not None:
            raise TrendSeriesResolutionContractError("successful/insufficient result requires series only")


class TrendSeriesRepositoryError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: TrendSeriesResolutionErrorCode) -> None:
        if type(code) is not TrendSeriesResolutionErrorCode:
            raise TypeError("repository error code must be exact enum")
        self.code = code
        super().__init__("trend series repository operation failed")

    def __repr__(self) -> str:
        return "TrendSeriesRepositoryError()"

    __str__ = __repr__


class TrendSeriesRepositoryPort(Protocol):
    def load_resolution_snapshot(
        self, request: TrendSeriesResolutionRequest
    ) -> TrendSeriesResolutionSnapshot: ...


def canonical_candidate_set_digest(
    request: TrendSeriesResolutionRequest,
    periods: tuple[TrendResolvedPeriod, ...],
    sources: tuple[TrendResolvedSourceCandidate, ...],
) -> str:
    """Canonical candidate identity; excludes audit time and extracted values."""

    ordered_periods = tuple(sorted(
        periods,
        key=lambda item: (item.start_date, item.end_date, item.fiscal_ordinal, str(item.period_id)),
    ))
    ordered_sources = tuple(sorted(
        sources,
        key=lambda item: (str(item.period_id), item.source_role.value, str(item.analysis_result_id)),
    ))
    projection = (
        request.tenant_id,
        request.company_id,
        request.anchor_period_id,
        request.metric_code,
        request.expected_period_family,
        request.expected_currency,
        request.expected_monetary_unit_multiplier,
        request.expected_accounting_basis,
        request.expected_accounting_policy_version,
        request.fiscal_calendar_reference,
        request.comparability_profile_version,
        tuple(
            (
                item.period_id, item.year, item.period_type, item.fiscal_ordinal,
                item.start_date, item.end_date, item.months_covered, item.status,
                item.coverage_kind, item.accounting_basis,
                item.accounting_policy_version, item.fiscal_calendar_reference,
                item.currency, item.monetary_unit_multiplier,
                item.restatement_profile, item.restatement_revision,
                item.one_off_status,
            )
            for item in ordered_periods
        ),
        tuple(
            (
                item.period_id, item.source_role, item.analysis_result_id,
                item.source_engine_type, item.source_analysis_type,
                item.source_status, item.source_field_path,
                item.canonical_digest, item.recomputed_digest,
                item.source_schema_version, item.source_model_version,
                item.digest_verified, item.provenance_verified,
                item.authoritative_chain_head_verified,
            )
            for item in ordered_sources
        ),
        request.expected_metric_registry_version,
        request.expected_metric_registry_digest,
        TREND_SERIES_RESOLUTION_CONTRACT_VERSION,
    )
    return canonical_trend_digest(projection)
