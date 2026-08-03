"""Framework-independent Multi-Period Input Resolution contracts (4.5C)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Protocol, final
from uuid import UUID

from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    PeriodCoverageKind,
    PeriodStatus,
    PeriodType,
    SourceMode,
)

from .errors import CashFlowContractError, CashFlowEngineFailure
from .contracts import CashFlowIssue
from .policy import CashFlowPresentationProfile
from .types import (
    CashFlowAccountingBasisCode,
    CashFlowErrorCode,
    CashFlowJsonObject,
    CashFlowSourceRole,
    CashFlowWarningCode,
)


CASH_FLOW_PERIOD_RESOLUTION_POLICY_VERSION = "1.0.0"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class CashFlowInputResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    INSUFFICIENT_DATA = "insufficient_data"


class CashFlowComparabilityRow(str, Enum):
    ANNUAL = "annual"
    MONTHLY_DISCRETE = "monthly_discrete"
    FIRST_FISCAL_MONTH = "first_fiscal_month"
    QUARTER_DISCRETE = "quarter_discrete"
    FIRST_FISCAL_QUARTER = "first_fiscal_quarter"
    QUARTER_CUMULATIVE = "quarter_cumulative"
    TEMPORARY_TAX_CUMULATIVE = "temporary_tax_cumulative"
    CUSTOM = "custom"


def _fail(message: str) -> None:
    raise CashFlowContractError(message)


def _uuid(value: object, name: str) -> None:
    if type(value) is not UUID:
        _fail(f"{name} must be UUID")


def _digest(value: object, name: str) -> None:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        _fail(f"{name} must be lowercase SHA-256")


def _text(value: object, name: str, maximum: int = 128) -> None:
    if type(value) is not str or not value or len(value) > maximum:
        _fail(f"{name} must be bounded non-empty text")


def _utc(value: object, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _fail(f"{name} must be timezone-aware datetime")
    if value.utcoffset() != timedelta(0):
        _fail(f"{name} must be UTC")


@dataclass(frozen=True, repr=False)
class CashFlowPeriodResolutionRequest:
    tenant_id: UUID
    company_id: UUID
    current_period_id: UUID
    required_source_roles: tuple[CashFlowSourceRole, ...]
    expected_currency: str
    expected_accounting_basis: CashFlowAccountingBasisCode
    expected_accounting_policy_version: str
    expected_presentation_profile: CashFlowPresentationProfile
    expected_mapping_registry_version: str
    correlation_id: str
    resolved_at: datetime
    explicit_prior_period_id: UUID | None = None

    def __post_init__(self) -> None:
        for name in ("tenant_id", "company_id", "current_period_id"):
            _uuid(getattr(self, name), name)
        if self.explicit_prior_period_id is not None:
            _uuid(self.explicit_prior_period_id, "explicit_prior_period_id")
        expected_roles = tuple(role for role in CashFlowSourceRole if role in self.required_source_roles)
        if type(self.required_source_roles) is not tuple or self.required_source_roles != expected_roles:
            _fail("required_source_roles must be unique and in declaration order")
        if not self.required_source_roles:
            _fail("required_source_roles cannot be empty")
        if self.expected_currency != "TRY":
            _fail("cash-flow v1 resolution supports TRY only")
        if self.expected_accounting_basis is not CashFlowAccountingBasisCode.TR_TDHP_ACCRUAL:
            _fail("unsupported expected accounting basis")
        for name in (
            "expected_accounting_policy_version",
            "expected_mapping_registry_version",
            "correlation_id",
        ):
            _text(getattr(self, name), name)
        if type(self.expected_presentation_profile) is not CashFlowPresentationProfile:
            _fail("invalid expected presentation profile")
        _utc(self.resolved_at, "resolved_at")


@dataclass(frozen=True, repr=False)
class CashFlowResolvedPeriod:
    period_id: UUID
    tenant_id: UUID
    company_id: UUID
    currency_code: str
    period_type: PeriodType
    period_number: int
    start_date: date
    end_date: date
    months_covered: int
    status: PeriodStatus
    accounting_basis_code: CashFlowAccountingBasisCode | None
    accounting_policy_version: str | None
    annual_reporting_period_start_date: date | None
    annual_reporting_period_end_date: date | None
    ifrs18_early_adopted: bool | None
    coverage_kind: PeriodCoverageKind | None

    def __post_init__(self) -> None:
        for name in ("period_id", "tenant_id", "company_id"):
            _uuid(getattr(self, name), name)
        if type(self.currency_code) is not str or len(self.currency_code) != 3:
            _fail("currency_code must be ISO-like three-letter text")
        if type(self.period_type) is not PeriodType or type(self.status) is not PeriodStatus:
            _fail("period type/status is invalid")
        if type(self.period_number) is not int or type(self.months_covered) is not int:
            _fail("period_number/months_covered must be integers")
        if type(self.start_date) is not date or type(self.end_date) is not date or self.start_date > self.end_date:
            _fail("period dates are invalid")
        metadata = (
            self.accounting_basis_code,
            self.accounting_policy_version,
            self.annual_reporting_period_start_date,
            self.annual_reporting_period_end_date,
            self.ifrs18_early_adopted,
            self.coverage_kind,
        )
        if any(value is None for value in metadata) and not all(value is None for value in metadata):
            _fail("period policy metadata must be all-null or all-present")
        if all(value is not None for value in metadata):
            if type(self.accounting_basis_code) is not CashFlowAccountingBasisCode:
                _fail("invalid accounting basis")
            _text(self.accounting_policy_version, "accounting_policy_version")
            if type(self.annual_reporting_period_start_date) is not date or type(self.annual_reporting_period_end_date) is not date:
                _fail("annual reporting boundaries must be date")
            if not self.annual_reporting_period_start_date <= self.start_date <= self.end_date <= self.annual_reporting_period_end_date:
                _fail("period is outside annual reporting boundaries")
            if type(self.ifrs18_early_adopted) is not bool or type(self.coverage_kind) is not PeriodCoverageKind:
                _fail("invalid IFRS18/coverage metadata")

    @property
    def metadata_complete(self) -> bool:
        return self.accounting_basis_code is not None


@dataclass(frozen=True, repr=False)
class CashFlowResolvedSource:
    source_role: CashFlowSourceRole
    analysis_result_id: UUID
    company_id: UUID
    period_id: UUID
    analysis_type: AnalysisType
    source_mode: SourceMode
    status: AnalysisStatus
    canonical_digest: str | None
    recomputed_payload_digest: str | None
    engine_version: str
    completed_at: datetime | None
    digest_verified: bool

    def __post_init__(self) -> None:
        if type(self.source_role) is not CashFlowSourceRole:
            _fail("invalid source role")
        for name in ("analysis_result_id", "company_id", "period_id"):
            _uuid(getattr(self, name), name)
        if type(self.analysis_type) is not AnalysisType or type(self.source_mode) is not SourceMode or type(self.status) is not AnalysisStatus:
            _fail("invalid source enum")
        if self.canonical_digest is not None:
            _digest(self.canonical_digest, "canonical_digest")
        if self.recomputed_payload_digest is not None:
            _digest(self.recomputed_payload_digest, "recomputed_payload_digest")
        _text(self.engine_version, "engine_version")
        if self.completed_at is not None:
            _utc(self.completed_at, "completed_at")
        if type(self.digest_verified) is not bool:
            _fail("digest_verified must be bool")


@dataclass(frozen=True, repr=False)
class CashFlowResolutionSnapshot:
    current_period: CashFlowResolvedPeriod
    prior_candidates: tuple[CashFlowResolvedPeriod, ...]
    source_candidates: tuple[CashFlowResolvedSource, ...]
    candidate_set_digest: str

    def __post_init__(self) -> None:
        if type(self.current_period) is not CashFlowResolvedPeriod:
            _fail("current_period must be resolved period")
        if type(self.prior_candidates) is not tuple or any(type(item) is not CashFlowResolvedPeriod for item in self.prior_candidates):
            _fail("prior_candidates must be immutable period tuple")
        if type(self.source_candidates) is not tuple or any(type(item) is not CashFlowResolvedSource for item in self.source_candidates):
            _fail("source_candidates must be immutable source tuple")
        if self.prior_candidates != tuple(sorted(self.prior_candidates, key=lambda item: str(item.period_id))):
            _fail("prior_candidates must be canonical UUID order")
        if self.source_candidates != tuple(sorted(self.source_candidates, key=lambda item: (item.source_role.value, str(item.analysis_result_id)))):
            _fail("source_candidates must be canonical role/UUID order")
        _digest(self.candidate_set_digest, "candidate_set_digest")


@dataclass(frozen=True, repr=False)
class CashFlowInputResolutionResult:
    status: CashFlowInputResolutionStatus
    tenant_id: UUID
    company_id: UUID
    current_period_id: UUID
    prior_period_id: UUID | None
    current_period: CashFlowResolvedPeriod
    prior_period: CashFlowResolvedPeriod | None
    sources: tuple[CashFlowResolvedSource, ...]
    comparability_row: CashFlowComparabilityRow | None
    comparability_proof_digest: str | None
    missing_source_roles: tuple[CashFlowSourceRole, ...]
    warnings: tuple[CashFlowIssue, ...]
    errors: tuple[CashFlowIssue, ...]
    candidate_set_digest: str
    resolution_policy_version: str
    resolution_digest: str

    def __post_init__(self) -> None:
        if type(self.status) is not CashFlowInputResolutionStatus:
            _fail("invalid resolution status")
        for name in ("tenant_id", "company_id", "current_period_id"):
            _uuid(getattr(self, name), name)
        if type(self.current_period) is not CashFlowResolvedPeriod or self.current_period.period_id != self.current_period_id:
            _fail("current period identity mismatch")
        if type(self.sources) is not tuple or any(type(item) is not CashFlowResolvedSource for item in self.sources):
            _fail("sources must be immutable")
        expected_missing = tuple(role for role in CashFlowSourceRole if role in self.missing_source_roles)
        if self.missing_source_roles != expected_missing:
            _fail("missing_source_roles must be canonical")
        if type(self.warnings) is not tuple or any(type(item) is not CashFlowIssue for item in self.warnings):
            _fail("warnings must be immutable CashFlowIssue tuple")
        if type(self.errors) is not tuple or any(type(item) is not CashFlowIssue for item in self.errors):
            _fail("errors must be immutable CashFlowIssue tuple")
        if self.errors:
            _fail("result-bearing resolution cannot carry errors")
        _digest(self.candidate_set_digest, "candidate_set_digest")
        _text(self.resolution_policy_version, "resolution_policy_version")
        _digest(self.resolution_digest, "resolution_digest")
        if self.status is CashFlowInputResolutionStatus.RESOLVED:
            if self.prior_period_id is None or self.prior_period is None or self.comparability_row is None:
                _fail("resolved input requires prior period and comparability row")
            if self.prior_period.period_id != self.prior_period_id or self.missing_source_roles:
                _fail("resolved input period/source invariant failed")
            _digest(self.comparability_proof_digest, "comparability_proof_digest")
        else:
            if self.prior_period_id is not None or self.prior_period is not None:
                _fail("insufficient input cannot claim prior period")
            if self.comparability_row is not None or self.comparability_proof_digest is not None:
                _fail("insufficient input cannot claim comparability proof")
            if not any(item.code is CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE for item in self.warnings):
                _fail("insufficient input requires minimum-data warning")


@dataclass(frozen=True, repr=False)
class CashFlowInputResolutionOutcome:
    success: bool
    value: CashFlowInputResolutionResult | None
    error: CashFlowEngineFailure | None

    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            _fail("outcome success must be bool")
        if self.success:
            if type(self.value) is not CashFlowInputResolutionResult or self.error is not None:
                _fail("successful outcome invariant failed")
        elif self.value is not None or type(self.error) is not CashFlowEngineFailure:
            _fail("failed outcome invariant failed")


@final
class CashFlowResolutionRepositoryError(Exception):
    __slots__ = ("code",)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("CashFlowResolutionRepositoryError is final")

    def __init__(self, code: CashFlowErrorCode) -> None:
        if code not in {
            CashFlowErrorCode.SOURCE_NOT_FOUND,
            CashFlowErrorCode.SOURCE_SCOPE_MISMATCH,
            CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT,
            CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE,
        }:
            _fail("invalid resolution repository error code")
        self.code = code
        super().__init__(code.value)

    def __str__(self) -> str:
        return f"CashFlowResolutionRepositoryError(code={self.code.value})"

    __repr__ = __str__


class ComparablePeriodRepositoryPort(Protocol):
    def load_resolution_snapshot(
        self, request: CashFlowPeriodResolutionRequest
    ) -> CashFlowResolutionSnapshot: ...


def canonical_resolution_bytes(payload: object) -> bytes:
    def project(value: object) -> object:
        if value is None or type(value) in {bool, str, int}:
            return value
        if type(value) is UUID:
            return {"$uuid": str(value)}
        if type(value) is date:
            return {"$date": value.isoformat()}
        if type(value) is datetime:
            return {"$datetime": value.astimezone(timezone.utc).isoformat(timespec="microseconds")}
        if isinstance(value, Enum):
            return {"$enum": f"{type(value).__name__}:{value.value}"}
        if type(value) is tuple:
            return [project(item) for item in value]
        if hasattr(value, "__dataclass_fields__"):
            return {name: project(getattr(value, name)) for name in value.__dataclass_fields__}
        _fail("unsupported resolution canonical value")

    return json.dumps(project(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_resolution_digest(domain: str, payload: object) -> str:
    _text(domain, "domain")
    return sha256(domain.encode("ascii") + b"\0" + canonical_resolution_bytes(payload)).hexdigest()
