"""Immutable, framework-independent contracts for Milestone 4.6A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import UUID

from .canonical import (
    canonical_trend_digest,
    canonical_trend_reference,
    normalize_decimal,
    validate_sha256,
    validate_trend_reference,
)
from .policy import TrendComparabilityProfile
from .types import (
    TREND_EVIDENCE_RANK,
    TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1,
    TrendComparabilityStatus,
    TrendAggregateAvailability,
    TrendCagrStatus,
    TrendComputationStatus,
    TrendContractVersion,
    TrendCoverageKind,
    TrendDirection,
    TrendDataQualityFlag,
    TrendErrorCode,
    TrendEvidenceLevel,
    TrendFinalMetricAvailability,
    TrendMeasurementBasis,
    TrendMetricAvailability,
    TrendNegativeBaseDirection,
    TrendNominalAnalysisProfile,
    TrendOneOffDisclosureStatus,
    TrendOneOffStatus,
    TrendPeriodFamily,
    TrendPolicyVersion,
    TrendRestatementProfile,
    TrendRestatementDisclosureStatus,
    TrendSegmentBoundaryKind,
    TrendSourceEngineType,
    TrendTransitionKind,
    TrendVolatilityCategory,
    TrendWarningCode,
    weakest_evidence,
)


class TrendContractError(ValueError):
    __slots__ = ()


class _SafeContractValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _fail(message: str) -> None:
    raise TrendContractError(message)


def _uuid(value: object, name: str) -> UUID:
    if type(value) is not UUID:
        _fail(f"{name} must be UUID")
    return value


def _text(value: object, name: str, maximum: int = 128) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        _fail(f"{name} must be bounded non-empty text")
    return value


def _currency(value: object) -> str:
    if type(value) is not str or len(value) != 3 or value != value.upper() or not value.isascii() or not value.isalpha():
        _fail("currency must be uppercase three-letter ASCII text")
    return value


def _decimal_or_none(value: object, name: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        _fail(f"{name} must be finite Decimal or None")
    return normalize_decimal(value)


def _exact_tuple(value: object, item_type: type, name: str) -> tuple:
    if type(value) is not tuple or any(type(item) is not item_type for item in value):
        _fail(f"{name} must be an immutable exact tuple")
    return value


def _canonical_issues(value: object, item_type: type, name: str) -> tuple:
    items = _exact_tuple(value, item_type, name)
    ordered = tuple(sorted(items, key=lambda item: (item.code.value, item.safe_reference or "")))
    if len({(item.code, item.safe_reference) for item in ordered}) != len(ordered):
        _fail(f"{name} contains duplicates")
    return ordered


def _canonical_enums(value: object, item_type: type, name: str) -> tuple:
    items = _exact_tuple(value, item_type, name)
    if len(set(items)) != len(items):
        _fail(f"{name} contains duplicates")
    declaration_order = {item: index for index, item in enumerate(item_type)}
    return tuple(sorted(items, key=declaration_order.__getitem__))


def _has_period_gap(
    previous: "TrendObservation",
    current: "TrendObservation",
    family: TrendPeriodFamily,
) -> bool:
    if family in {
        TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY,
        TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY,
    }:
        return current.period_end_date.year - previous.period_end_date.year > 1
    return previous.period_end_date + timedelta(days=1) < current.period_start_date


@dataclass(frozen=True, repr=False)
class TrendWarning(_SafeContractValue):
    code: TrendWarningCode
    safe_reference: str | None = None

    def __post_init__(self) -> None:
        if type(self.code) is not TrendWarningCode:
            _fail("warning code must be exact enum")
        if self.safe_reference is not None:
            validate_trend_reference(self.safe_reference)


@dataclass(frozen=True, repr=False)
class TrendError(_SafeContractValue):
    code: TrendErrorCode
    safe_reference: str | None = None

    def __post_init__(self) -> None:
        if type(self.code) is not TrendErrorCode:
            _fail("error code must be exact enum")
        if self.safe_reference is not None:
            validate_trend_reference(self.safe_reference)


@dataclass(frozen=True, repr=False)
class TrendSourceReference(_SafeContractValue):
    company_id: UUID
    period_id: UUID
    source_result_id: UUID
    source_engine_type: TrendSourceEngineType
    source_schema_version: str | None
    source_model_version: str
    canonical_source_digest: str
    evidence: TrendEvidenceLevel

    def __post_init__(self) -> None:
        for name in ("company_id", "period_id", "source_result_id"):
            _uuid(getattr(self, name), name)
        if type(self.source_engine_type) is not TrendSourceEngineType:
            _fail("source engine type must be exact enum")
        if self.source_schema_version is not None:
            _text(self.source_schema_version, "source_schema_version", 32)
        _text(self.source_model_version, "source_model_version", 32)
        validate_sha256(self.canonical_source_digest, "canonical_source_digest")
        if type(self.evidence) is not TrendEvidenceLevel:
            _fail("source evidence must be exact enum")

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendLineageReference(_SafeContractValue):
    ordinal: int
    period_id: UUID
    source_result_id: UUID
    canonical_source_digest: str
    comparability_proof_digest: str
    lineage_schema_version: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            _fail("lineage ordinal must be non-negative integer")
        _uuid(self.period_id, "period_id")
        _uuid(self.source_result_id, "source_result_id")
        validate_sha256(self.canonical_source_digest, "canonical_source_digest")
        validate_sha256(self.comparability_proof_digest, "comparability_proof_digest")
        if self.lineage_schema_version != "1.0.0":
            _fail("unsupported lineage schema version")

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendObservation(_SafeContractValue):
    ordinal: int
    segment_ordinal: int
    company_id: UUID
    period_id: UUID
    period_start_date: date
    period_end_date: date
    period_family: TrendPeriodFamily
    coverage_kind: TrendCoverageKind
    measurement_basis: TrendMeasurementBasis
    value: Decimal | None
    currency: str
    monetary_unit_multiplier: Decimal
    scale: int
    evidence: TrendEvidenceLevel
    source_result_id: UUID
    source_engine_type: TrendSourceEngineType
    source_schema_version: str | None
    source_model_version: str
    canonical_source_digest: str
    restatement_profile: TrendRestatementProfile
    restatement_revision: int
    one_off_status: TrendOneOffStatus
    warnings: tuple[TrendWarning, ...] = ()

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            _fail("observation ordinal must be non-negative integer")
        if type(self.segment_ordinal) is not int or self.segment_ordinal < 0:
            _fail("segment ordinal must be non-negative integer")
        _uuid(self.company_id, "company_id")
        _uuid(self.period_id, "period_id")
        if type(self.period_start_date) is not date or type(self.period_end_date) is not date or self.period_start_date > self.period_end_date:
            _fail("observation period dates are invalid")
        for value, expected, name in (
            (self.period_family, TrendPeriodFamily, "period_family"),
            (self.coverage_kind, TrendCoverageKind, "coverage_kind"),
            (self.measurement_basis, TrendMeasurementBasis, "measurement_basis"),
            (self.evidence, TrendEvidenceLevel, "evidence"),
            (self.source_engine_type, TrendSourceEngineType, "source_engine_type"),
            (self.restatement_profile, TrendRestatementProfile, "restatement_profile"),
            (self.one_off_status, TrendOneOffStatus, "one_off_status"),
        ):
            if type(value) is not expected:
                _fail(f"{name} must be exact enum")
        normalized_value = _decimal_or_none(self.value, "value")
        if (normalized_value is None) != (self.evidence is TrendEvidenceLevel.UNAVAILABLE):
            _fail("missing value must map exactly to UNAVAILABLE evidence")
        object.__setattr__(self, "value", normalized_value)
        _currency(self.currency)
        multiplier = _decimal_or_none(self.monetary_unit_multiplier, "monetary_unit_multiplier")
        if multiplier not in {Decimal("1"), Decimal("1000"), Decimal("1000000")}:
            _fail("monetary unit multiplier is unsupported")
        object.__setattr__(self, "monetary_unit_multiplier", multiplier)
        if type(self.scale) is not int or not 0 <= self.scale <= 8:
            _fail("scale must be integer in range 0..8")
        _uuid(self.source_result_id, "source_result_id")
        if self.source_schema_version is not None:
            _text(self.source_schema_version, "source_schema_version", 32)
        _text(self.source_model_version, "source_model_version", 32)
        validate_sha256(self.canonical_source_digest, "canonical_source_digest")
        if type(self.restatement_revision) is not int or self.restatement_revision < 0:
            _fail("restatement revision must be non-negative integer")
        if self.restatement_profile is TrendRestatementProfile.ORIGINAL and self.restatement_revision != 0:
            _fail("original observation requires restatement revision zero")
        if self.restatement_profile is TrendRestatementProfile.RESTATED and self.restatement_revision <= 0:
            _fail("restated observation requires positive revision")
        if self.restatement_profile is TrendRestatementProfile.UNDECLARED_LEGACY and self.restatement_revision != 0:
            _fail("legacy observation requires revision zero")
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendGap(_SafeContractValue):
    after_period_id: UUID
    before_period_id: UUID
    first_missing_date: date
    last_missing_date: date

    def __post_init__(self) -> None:
        _uuid(self.after_period_id, "after_period_id")
        _uuid(self.before_period_id, "before_period_id")
        if self.after_period_id == self.before_period_id:
            _fail("gap endpoints must differ")
        if type(self.first_missing_date) is not date or type(self.last_missing_date) is not date or self.first_missing_date > self.last_missing_date:
            _fail("gap dates are invalid")


@dataclass(frozen=True, repr=False)
class TrendSegmentBoundary(_SafeContractValue):
    after_period_id: UUID
    before_period_id: UUID
    kind: TrendSegmentBoundaryKind

    def __post_init__(self) -> None:
        _uuid(self.after_period_id, "after_period_id")
        _uuid(self.before_period_id, "before_period_id")
        if self.after_period_id == self.before_period_id or type(self.kind) is not TrendSegmentBoundaryKind:
            _fail("segment boundary is invalid")


@dataclass(frozen=True, repr=False)
class TrendTransition(_SafeContractValue):
    metric_code: str
    from_period_id: UUID
    to_period_id: UUID
    from_value: Decimal | None
    to_value: Decimal | None
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    transition_kind: TrendTransitionKind
    direction: TrendDirection
    negative_base_direction: TrendNegativeBaseDirection
    evidence: TrendEvidenceLevel
    stable_tolerance: Decimal
    registry_digest: str
    policy_version: TrendPolicyVersion
    observation_reference_digests: tuple[str, str]
    source_reference_digests: tuple[str, str]
    transition_digest: str
    transition_reference: str
    warnings: tuple[TrendWarning, ...] = ()
    errors: tuple[TrendError, ...] = ()

    def __post_init__(self) -> None:
        _text(self.metric_code, "metric_code", 128)
        _uuid(self.from_period_id, "from_period_id")
        _uuid(self.to_period_id, "to_period_id")
        if self.from_period_id == self.to_period_id:
            _fail("transition endpoints must differ")
        prior = _decimal_or_none(self.from_value, "from_value")
        current = _decimal_or_none(self.to_value, "to_value")
        absolute = _decimal_or_none(self.absolute_change, "absolute_change")
        percentage = _decimal_or_none(self.percentage_change, "percentage_change")
        tolerance = _decimal_or_none(self.stable_tolerance, "stable_tolerance")
        if tolerance is None or tolerance < 0:
            _fail("stable tolerance must be non-negative Decimal")
        object.__setattr__(self, "from_value", prior)
        object.__setattr__(self, "to_value", current)
        object.__setattr__(self, "absolute_change", absolute)
        object.__setattr__(self, "percentage_change", percentage)
        object.__setattr__(self, "stable_tolerance", tolerance)
        if (
            type(self.transition_kind) is not TrendTransitionKind
            or type(self.direction) is not TrendDirection
            or type(self.negative_base_direction) is not TrendNegativeBaseDirection
            or type(self.evidence) is not TrendEvidenceLevel
            or type(self.policy_version) is not TrendPolicyVersion
        ):
            _fail("transition enum is invalid")
        validate_sha256(self.registry_digest, "registry_digest")
        for name in ("observation_reference_digests", "source_reference_digests"):
            digests = getattr(self, name)
            if type(digests) is not tuple or len(digests) != 2:
                _fail(f"{name} must contain two canonical digests")
            for digest in digests:
                validate_sha256(digest, name)
        validate_sha256(self.transition_digest, "transition_digest")
        validate_trend_reference(self.transition_reference)
        if self.transition_kind is TrendTransitionKind.PERCENTAGE_AVAILABLE:
            if prior is None or current is None or absolute is None or percentage is None:
                _fail("percentage transition requires both numeric values")
            if prior <= 0 or current <= 0:
                _fail("percentage transition requires positive-base semantics")
        elif self.transition_kind is TrendTransitionKind.UNAVAILABLE_MISSING_INPUT:
            if prior is not None and current is not None:
                _fail("missing-input transition requires a missing endpoint")
            if absolute is not None or percentage is not None or self.evidence is not TrendEvidenceLevel.UNAVAILABLE:
                _fail("unavailable transition cannot carry numeric values")
        elif prior is None or current is None or absolute is None or percentage is not None:
            _fail("absolute-only transition requires only absolute change")
        if self.transition_kind is TrendTransitionKind.ABSOLUTE_ONLY_ZERO_BASE and prior != 0:
            _fail("zero-base transition requires zero prior value")
        if self.transition_kind is TrendTransitionKind.ABSOLUTE_ONLY_NEGATIVE_BASE:
            if prior is None or current is None or prior >= 0 or current >= 0:
                _fail("negative-base transition requires two negative values")
            if self.negative_base_direction is TrendNegativeBaseDirection.NOT_APPLICABLE:
                _fail("negative-base transition requires semantic direction")
        elif self.negative_base_direction is not TrendNegativeBaseDirection.NOT_APPLICABLE:
            _fail("negative-base semantic direction is not applicable")
        if self.transition_kind is TrendTransitionKind.ABSOLUTE_ONLY_SIGN_CHANGE:
            if prior is None or current is None or not ((prior < 0 <= current) or (prior > 0 >= current)):
                _fail("sign-change transition requires an actual sign transition")
        expected_direction = (
            TrendDirection.INSUFFICIENT_DATA
            if prior is None or current is None
            else TrendDirection.SIGN_CHANGE
            if self.transition_kind is TrendTransitionKind.ABSOLUTE_ONLY_SIGN_CHANGE
            else TrendDirection.STABLE
            if abs(current - prior) <= tolerance
            else TrendDirection.INCREASING
            if current > prior
            else TrendDirection.DECREASING
        )
        if self.direction is not expected_direction:
            _fail("transition direction does not match endpoint values and tolerance")
        if self.evidence is TrendEvidenceLevel.EXACT:
            _fail("derived transition evidence cannot be EXACT")
        warnings = _canonical_issues(self.warnings, TrendWarning, "warnings")
        errors = _canonical_issues(self.errors, TrendError, "errors")
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        projection = (
            self.metric_code,
            self.from_period_id,
            self.to_period_id,
            prior,
            current,
            absolute,
            percentage,
            self.transition_kind,
            self.direction,
            self.negative_base_direction,
            self.evidence,
            tolerance,
            self.registry_digest,
            self.policy_version,
            self.observation_reference_digests,
            self.source_reference_digests,
            warnings,
            errors,
        )
        expected_digest = canonical_trend_digest(projection)
        if self.transition_digest != expected_digest:
            _fail("transition digest mismatch")
        if self.transition_reference != canonical_trend_reference(projection):
            _fail("transition reference mismatch")


@dataclass(frozen=True, repr=False)
class TrendCompleteness(_SafeContractValue):
    expected_observation_count: int
    available_observation_count: int
    unavailable_observation_count: int
    available_ratio: Decimal

    def __post_init__(self) -> None:
        for name in ("expected_observation_count", "available_observation_count", "unavailable_observation_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                _fail(f"{name} must be non-negative integer")
        if self.available_observation_count + self.unavailable_observation_count != self.expected_observation_count:
            _fail("completeness counts do not balance")
        ratio = _decimal_or_none(self.available_ratio, "available_ratio")
        if ratio is None or ratio < 0 or ratio > 1:
            _fail("available ratio must be Decimal in range 0..1")
        expected = (
            Decimal(0)
            if self.expected_observation_count == 0
            else (Decimal(self.available_observation_count) / Decimal(self.expected_observation_count)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_EVEN
            )
        )
        if normalize_decimal(ratio) != normalize_decimal(expected):
            _fail("available ratio does not match counts")
        object.__setattr__(self, "available_ratio", normalize_decimal(ratio))


@dataclass(frozen=True, repr=False)
class TrendEvidenceSummary(_SafeContractValue):
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    weakest_evidence: TrendEvidenceLevel

    def __post_init__(self) -> None:
        for name in ("exact_count", "derived_count", "estimated_count", "unavailable_count"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                _fail(f"{name} must be non-negative integer")
        if type(self.weakest_evidence) is not TrendEvidenceLevel:
            _fail("weakest evidence must be exact enum")
        counts = {
            TrendEvidenceLevel.EXACT: self.exact_count,
            TrendEvidenceLevel.DERIVED: self.derived_count,
            TrendEvidenceLevel.ESTIMATED: self.estimated_count,
            TrendEvidenceLevel.UNAVAILABLE: self.unavailable_count,
        }
        populated = tuple(level for level in TrendEvidenceLevel if counts[level] > 0)
        if not populated or self.weakest_evidence is not weakest_evidence(*populated):
            _fail("weakest evidence does not match counts")

    @property
    def total_count(self) -> int:
        return self.exact_count + self.derived_count + self.estimated_count + self.unavailable_count


@dataclass(frozen=True, repr=False)
class TrendTransitionCompleteness(_SafeContractValue):
    eligible_within_segment_count: int
    emitted_count: int
    valid_count: int
    unavailable_count: int
    boundary_excluded_count: int
    emitted_ratio: Decimal

    def __post_init__(self) -> None:
        for name in (
            "eligible_within_segment_count",
            "emitted_count",
            "valid_count",
            "unavailable_count",
            "boundary_excluded_count",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                _fail(f"{name} must be non-negative integer")
        if self.valid_count + self.unavailable_count != self.emitted_count:
            _fail("transition completeness emitted counts do not balance")
        if self.emitted_count > self.eligible_within_segment_count:
            _fail("emitted transitions exceed eligible pairs")
        ratio = _decimal_or_none(self.emitted_ratio, "emitted_ratio")
        expected = (
            Decimal(0)
            if self.eligible_within_segment_count == 0
            else (Decimal(self.emitted_count) / Decimal(self.eligible_within_segment_count)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_EVEN
            )
        )
        if ratio != expected:
            _fail("transition emitted ratio does not match counts")
        object.__setattr__(self, "emitted_ratio", normalize_decimal(ratio))


@dataclass(frozen=True, repr=False)
class TrendSeries(_SafeContractValue):
    metric_code: str
    company_id: UUID
    anchor_period_id: UUID
    period_family: TrendPeriodFamily
    measurement_basis: TrendMeasurementBasis
    observations: tuple[TrendObservation, ...]
    transitions: tuple[TrendTransition, ...]
    currency: str
    monetary_unit_multiplier: Decimal
    scale: int
    policy_version: TrendPolicyVersion
    metric_registry_version_reference: str
    completeness: TrendCompleteness
    evidence_summary: TrendEvidenceSummary
    gaps: tuple[TrendGap, ...]
    segment_boundaries: tuple[TrendSegmentBoundary, ...]
    warnings: tuple[TrendWarning, ...] = ()
    errors: tuple[TrendError, ...] = ()

    def __post_init__(self) -> None:
        _text(self.metric_code, "metric_code", 128)
        _uuid(self.company_id, "company_id")
        _uuid(self.anchor_period_id, "anchor_period_id")
        if type(self.period_family) is not TrendPeriodFamily or type(self.measurement_basis) is not TrendMeasurementBasis:
            _fail("series period family/basis is invalid")
        observations = _exact_tuple(self.observations, TrendObservation, "observations")
        if not 1 <= len(observations) <= 60:
            _fail("series requires 1..60 observations")
        ordered = tuple(sorted(observations, key=lambda item: (item.period_end_date, item.period_start_date, str(item.period_id))))
        if tuple(item.ordinal for item in ordered) != tuple(range(len(ordered))):
            _fail("observation ordinals must be gapless canonical chronology")
        for attr, message in (
            ("period_id", "duplicate observation period"),
            ("source_result_id", "duplicate observation source"),
            ("canonical_source_digest", "duplicate observation digest"),
        ):
            values = tuple(getattr(item, attr) for item in ordered)
            if len(values) != len(set(values)):
                _fail(message)
        for item in ordered:
            if item.company_id != self.company_id:
                _fail("series contains mixed company/legal entity")
            if item.period_family is not self.period_family:
                _fail("series contains mixed period family")
            if item.measurement_basis is not self.measurement_basis:
                _fail("series contains mixed measurement basis")
            if item.currency != self.currency:
                _fail("series contains mixed currency")
            if item.monetary_unit_multiplier != self.monetary_unit_multiplier or item.scale != self.scale:
                _fail("series contains mixed numeric unit/scale")
        if ordered[-1].period_id != self.anchor_period_id:
            _fail("anchor period must be the chronologically last observation")
        object.__setattr__(self, "observations", ordered)
        _currency(self.currency)
        multiplier = _decimal_or_none(self.monetary_unit_multiplier, "monetary_unit_multiplier")
        if multiplier not in {Decimal("1"), Decimal("1000"), Decimal("1000000")}:
            _fail("series monetary multiplier is unsupported")
        object.__setattr__(self, "monetary_unit_multiplier", multiplier)
        if type(self.scale) is not int or not 0 <= self.scale <= 8:
            _fail("series scale is invalid")
        if self.policy_version is not TrendPolicyVersion.V1:
            _fail("unsupported series policy version")
        if self.metric_registry_version_reference != TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1:
            _fail("unsupported metric registry version reference")

        derived_gaps: list[TrendGap] = []
        boundaries: list[TrendSegmentBoundary] = []
        expected_segment = 0
        if ordered[0].segment_ordinal != 0:
            _fail("first observation must start segment zero")
        for previous, current in zip(ordered, ordered[1:]):
            if previous.period_end_date >= current.period_start_date:
                _fail("observation periods overlap")
            has_gap = _has_period_gap(previous, current, self.period_family)
            restatement_change = previous.restatement_profile is not current.restatement_profile
            boundary_kinds = []
            if has_gap:
                derived_gaps.append(
                    TrendGap(
                        after_period_id=previous.period_id,
                        before_period_id=current.period_id,
                        first_missing_date=previous.period_end_date + timedelta(days=1),
                        last_missing_date=current.period_start_date - timedelta(days=1),
                    )
                )
                boundary_kinds.append(TrendSegmentBoundaryKind.PERIOD_GAP)
            if restatement_change:
                boundary_kinds.append(TrendSegmentBoundaryKind.RESTATEMENT_CHANGE)
            if boundary_kinds:
                expected_segment += 1
                boundaries.extend(
                    TrendSegmentBoundary(previous.period_id, current.period_id, kind)
                    for kind in boundary_kinds
                )
            if current.segment_ordinal != expected_segment:
                _fail("segment ordinal does not disclose gap/restatement boundary")
        supplied_gaps = _exact_tuple(self.gaps, TrendGap, "gaps")
        supplied_boundaries = _exact_tuple(self.segment_boundaries, TrendSegmentBoundary, "segment_boundaries")
        if supplied_gaps and supplied_gaps != tuple(derived_gaps):
            _fail("supplied gaps do not match observation chronology")
        if supplied_boundaries and supplied_boundaries != tuple(boundaries):
            _fail("supplied boundaries do not match observation chronology")
        object.__setattr__(self, "gaps", tuple(derived_gaps))
        object.__setattr__(self, "segment_boundaries", tuple(boundaries))

        transitions = _exact_tuple(self.transitions, TrendTransition, "transitions")
        observation_by_id = {item.period_id: item for item in ordered}
        chronological_pairs = {
            (left.period_id, right.period_id): index
            for index, (left, right) in enumerate(zip(ordered, ordered[1:]))
            if left.segment_ordinal == right.segment_ordinal
        }
        pairs = tuple((item.from_period_id, item.to_period_id) for item in transitions)
        if len(pairs) != len(set(pairs)) or any(pair not in chronological_pairs for pair in pairs):
            _fail("transitions must be unique adjacent within-segment pairs")
        ordered_transitions = tuple(sorted(transitions, key=lambda item: chronological_pairs[(item.from_period_id, item.to_period_id)]))
        for transition in ordered_transitions:
            endpoint_evidence = weakest_evidence(
                observation_by_id[transition.from_period_id].evidence,
                observation_by_id[transition.to_period_id].evidence,
            )
            if TREND_EVIDENCE_RANK[transition.evidence] > TREND_EVIDENCE_RANK[endpoint_evidence]:
                _fail("transition evidence cannot be stronger than input evidence")
        object.__setattr__(self, "transitions", ordered_transitions)

        if type(self.completeness) is not TrendCompleteness or self.completeness.expected_observation_count != len(ordered):
            _fail("series completeness does not match observations")
        available = sum(item.value is not None for item in ordered)
        if (
            self.completeness.available_observation_count != available
            or self.completeness.unavailable_observation_count != len(ordered) - available
        ):
            _fail("series completeness availability counts are incorrect")
        if type(self.evidence_summary) is not TrendEvidenceSummary or self.evidence_summary.total_count != len(ordered):
            _fail("series evidence summary does not match observations")
        evidence_counts = {level: sum(item.evidence is level for item in ordered) for level in TrendEvidenceLevel}
        if (
            self.evidence_summary.exact_count != evidence_counts[TrendEvidenceLevel.EXACT]
            or self.evidence_summary.derived_count != evidence_counts[TrendEvidenceLevel.DERIVED]
            or self.evidence_summary.estimated_count != evidence_counts[TrendEvidenceLevel.ESTIMATED]
            or self.evidence_summary.unavailable_count != evidence_counts[TrendEvidenceLevel.UNAVAILABLE]
        ):
            _fail("series evidence counts are incorrect")
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))
        object.__setattr__(self, "errors", _canonical_issues(self.errors, TrendError, "errors"))

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendBreakResult(_SafeContractValue):
    detected: bool | None
    breakpoint_period_id: UUID | None
    direction: TrendDirection
    score: Decimal | None
    evidence: TrendEvidenceLevel
    warnings: tuple[TrendWarning, ...] = ()
    errors: tuple[TrendError, ...] = ()
    coherence_tolerance: Decimal | None = None
    score_threshold: Decimal | None = None

    def __post_init__(self) -> None:
        if self.detected is not None and type(self.detected) is not bool:
            _fail("break detected discriminator must be bool or None")
        if self.breakpoint_period_id is not None:
            _uuid(self.breakpoint_period_id, "breakpoint_period_id")
        score = _decimal_or_none(self.score, "score")
        coherence_tolerance = _decimal_or_none(self.coherence_tolerance, "coherence_tolerance")
        score_threshold = _decimal_or_none(self.score_threshold, "score_threshold")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "coherence_tolerance", coherence_tolerance)
        object.__setattr__(self, "score_threshold", score_threshold)
        if coherence_tolerance is not None and coherence_tolerance < 0:
            _fail("break coherence tolerance must be non-negative")
        if score_threshold is not None and score_threshold < 0:
            _fail("break score threshold must be non-negative")
        if type(self.direction) is not TrendDirection or type(self.evidence) is not TrendEvidenceLevel:
            _fail("break result enum is invalid")
        if self.detected is True:
            if self.breakpoint_period_id is None or score is None or score < 0 or self.direction in {TrendDirection.INSUFFICIENT_DATA, TrendDirection.STABLE, TrendDirection.MIXED}:
                _fail("detected break requires complete fields")
        elif self.breakpoint_period_id is not None or score is not None:
            _fail("non-detected break cannot carry breakpoint/score")
        if self.detected is None and self.direction is not TrendDirection.INSUFFICIENT_DATA:
            _fail("unevaluated break requires insufficient-data direction")
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))
        object.__setattr__(self, "errors", _canonical_issues(self.errors, TrendError, "errors"))

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendCagrResult(_SafeContractValue):
    value_percent: Decimal | None
    status: TrendCagrStatus
    evidence: TrendEvidenceLevel
    warnings: tuple[TrendWarning, ...] = ()
    year_interval: int | None = None

    def __post_init__(self) -> None:
        value = _decimal_or_none(self.value_percent, "value_percent")
        object.__setattr__(self, "value_percent", value)
        if type(self.status) is not TrendCagrStatus or type(self.evidence) is not TrendEvidenceLevel:
            _fail("CAGR result enum is invalid")
        if self.status is TrendCagrStatus.CALCULATED:
            if value is None or self.evidence is TrendEvidenceLevel.UNAVAILABLE or type(self.year_interval) is not int or self.year_interval <= 0:
                _fail("calculated CAGR requires value and evidence")
        elif value is not None or self.evidence is not TrendEvidenceLevel.UNAVAILABLE or self.year_interval is not None:
            _fail("unavailable CAGR cannot carry value/evidence")
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendStabilityResult(_SafeContractValue):
    stable: bool | None
    availability: TrendAggregateAvailability
    evidence: TrendEvidenceLevel
    warnings: tuple[TrendWarning, ...] = ()
    stable_tolerance: Decimal | None = None

    def __post_init__(self) -> None:
        if self.stable is not None and type(self.stable) is not bool:
            _fail("stability discriminator must be bool or None")
        if type(self.availability) is not TrendAggregateAvailability or type(self.evidence) is not TrendEvidenceLevel:
            _fail("stability result enum is invalid")
        tolerance = _decimal_or_none(self.stable_tolerance, "stable_tolerance")
        if tolerance is not None and tolerance < 0:
            _fail("stability tolerance must be non-negative")
        object.__setattr__(self, "stable_tolerance", tolerance)
        if self.availability is TrendAggregateAvailability.CALCULATED:
            if self.stable is None or self.evidence is TrendEvidenceLevel.UNAVAILABLE or tolerance is None:
                _fail("calculated stability requires bool and evidence")
        elif self.stable is not None or self.evidence is not TrendEvidenceLevel.UNAVAILABLE:
            _fail("unavailable stability cannot carry result/evidence")
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendVolatilityResult(_SafeContractValue):
    value: Decimal | None
    category: TrendVolatilityCategory
    availability: TrendAggregateAvailability
    evidence: TrendEvidenceLevel
    warnings: tuple[TrendWarning, ...] = ()
    low_threshold: Decimal | None = None
    medium_threshold: Decimal | None = None

    def __post_init__(self) -> None:
        value = _decimal_or_none(self.value, "volatility")
        low = _decimal_or_none(self.low_threshold, "low_threshold")
        medium = _decimal_or_none(self.medium_threshold, "medium_threshold")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "low_threshold", low)
        object.__setattr__(self, "medium_threshold", medium)
        if (low is None) != (medium is None) or (low is not None and (low < 0 or low >= medium)):
            _fail("volatility thresholds are invalid")
        if (
            type(self.category) is not TrendVolatilityCategory
            or type(self.availability) is not TrendAggregateAvailability
            or type(self.evidence) is not TrendEvidenceLevel
        ):
            _fail("volatility result enum is invalid")
        if self.availability is TrendAggregateAvailability.CALCULATED:
            if value is None or value < 0 or self.category is TrendVolatilityCategory.UNAVAILABLE or self.evidence is TrendEvidenceLevel.UNAVAILABLE or low is None:
                _fail("calculated volatility requires complete fields")
        elif value is not None or self.category is not TrendVolatilityCategory.UNAVAILABLE or self.evidence is not TrendEvidenceLevel.UNAVAILABLE:
            _fail("unavailable volatility cannot carry result/evidence")
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendMetricResult(_SafeContractValue):
    metric_code: str
    status: TrendComputationStatus
    availability: TrendMetricAvailability
    series: TrendSeries
    direction: TrendDirection
    break_result: TrendBreakResult
    direction_evidence: TrendEvidenceLevel = TrendEvidenceLevel.UNAVAILABLE
    transition_completeness: TrendTransitionCompleteness | None = None
    cagr_result: TrendCagrResult | None = None
    stability_result: TrendStabilityResult | None = None
    volatility_result: TrendVolatilityResult | None = None
    warnings: tuple[TrendWarning, ...] = ()
    errors: tuple[TrendError, ...] = ()

    def __post_init__(self) -> None:
        _text(self.metric_code, "metric_code", 128)
        if (
            type(self.status) is not TrendComputationStatus
            or type(self.availability) is not TrendMetricAvailability
            or type(self.direction) is not TrendDirection
            or type(self.direction_evidence) is not TrendEvidenceLevel
        ):
            _fail("metric result enum is invalid")
        if type(self.series) is not TrendSeries or self.series.metric_code != self.metric_code:
            _fail("metric result series identity mismatch")
        if type(self.break_result) is not TrendBreakResult:
            _fail("metric break result type is invalid")
        if self.cagr_result is None:
            object.__setattr__(self, "cagr_result", TrendCagrResult(
                None, TrendCagrStatus.INSUFFICIENT_DATA, TrendEvidenceLevel.UNAVAILABLE
            ))
        elif type(self.cagr_result) is not TrendCagrResult:
            _fail("metric CAGR result type is invalid")
        if self.stability_result is None:
            object.__setattr__(self, "stability_result", TrendStabilityResult(
                None, TrendAggregateAvailability.UNAVAILABLE, TrendEvidenceLevel.UNAVAILABLE
            ))
        elif type(self.stability_result) is not TrendStabilityResult:
            _fail("metric stability result type is invalid")
        if self.volatility_result is None:
            object.__setattr__(self, "volatility_result", TrendVolatilityResult(
                None, TrendVolatilityCategory.UNAVAILABLE,
                TrendAggregateAvailability.UNAVAILABLE, TrendEvidenceLevel.UNAVAILABLE
            ))
        elif type(self.volatility_result) is not TrendVolatilityResult:
            _fail("metric volatility result type is invalid")
        segment_counts: dict[int, int] = {}
        for observation in self.series.observations:
            segment_counts[observation.segment_ordinal] = segment_counts.get(observation.segment_ordinal, 0) + 1
        eligible_pairs = sum(max(count - 1, 0) for count in segment_counts.values())
        valid_transitions = sum(item.absolute_change is not None for item in self.series.transitions)
        unavailable_transitions = len(self.series.transitions) - valid_transitions
        expected_transition_completeness = TrendTransitionCompleteness(
            eligible_within_segment_count=eligible_pairs,
            emitted_count=len(self.series.transitions),
            valid_count=valid_transitions,
            unavailable_count=unavailable_transitions,
            boundary_excluded_count=max(len(self.series.observations) - 1 - eligible_pairs, 0),
            emitted_ratio=(
                Decimal(0)
                if eligible_pairs == 0
                else (Decimal(len(self.series.transitions)) / Decimal(eligible_pairs)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_EVEN
                )
            ),
        )
        if self.transition_completeness is None:
            object.__setattr__(self, "transition_completeness", expected_transition_completeness)
        elif type(self.transition_completeness) is not TrendTransitionCompleteness or self.transition_completeness != expected_transition_completeness:
            _fail("metric transition completeness mismatch")
        if self.direction is TrendDirection.INSUFFICIENT_DATA:
            if self.direction_evidence is not TrendEvidenceLevel.UNAVAILABLE:
                _fail("insufficient direction requires unavailable evidence")
        elif self.direction_evidence is TrendEvidenceLevel.UNAVAILABLE:
            _fail("direction-bearing result requires available evidence")
        available = self.series.completeness.available_observation_count
        expected_availability = (
            TrendMetricAvailability.UNAVAILABLE
            if available == 0
            else TrendMetricAvailability.AVAILABLE
            if available == len(self.series.observations)
            else TrendMetricAvailability.PARTIAL
        )
        if self.availability is not expected_availability:
            _fail("metric availability does not match observations")
        if self.status is TrendComputationStatus.COMPLETE:
            if (
                self.availability is not TrendMetricAvailability.AVAILABLE
                or available < 3
                or self.series.gaps
                or self.series.segment_boundaries
                or self.series.evidence_summary.estimated_count
                or self.series.evidence_summary.unavailable_count
                or self.errors
            ):
                _fail("COMPLETE metric requires at least three available observations")
        elif self.status is TrendComputationStatus.PARTIAL:
            degraded = bool(
                self.availability is not TrendMetricAvailability.AVAILABLE
                or self.series.gaps
                or self.series.segment_boundaries
                or self.series.evidence_summary.estimated_count
                or self.series.evidence_summary.unavailable_count
                or self.warnings
                or self.errors
            )
            if available < 3 or not degraded:
                _fail("PARTIAL metric requires trend data with explicit degradation")
        elif self.status is TrendComputationStatus.INSUFFICIENT_FOR_TREND:
            if available != 2:
                _fail("INSUFFICIENT_FOR_TREND requires exactly two available observations")
            if self.direction is not TrendDirection.INSUFFICIENT_DATA:
                _fail("two observations cannot claim trend-bearing direction")
        elif self.status is TrendComputationStatus.INSUFFICIENT_DATA:
            if available >= 2:
                _fail("INSUFFICIENT_DATA requires fewer than two available observations")
        elif self.status in {TrendComputationStatus.INVALID_INPUT, TrendComputationStatus.INTEGRITY_FAILURE}:
            if not self.errors:
                _fail("failure metric status requires an error")
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))
        object.__setattr__(self, "errors", _canonical_issues(self.errors, TrendError, "errors"))

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendResultCompleteness(_SafeContractValue):
    expected_period_count: int
    resolved_period_count: int
    expected_metric_observation_count: int
    available_observation_count: int
    unavailable_observation_count: int
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    eligible_transition_count: int
    calculated_transition_count: int
    eligible_cagr_count: int
    calculated_cagr_count: int
    eligible_volatility_count: int
    calculated_volatility_count: int
    eligible_break_count: int
    calculated_break_count: int
    gap_count: int
    restatement_boundary_count: int
    available_ratio: Decimal

    def __post_init__(self) -> None:
        count_names = (
            "expected_period_count", "resolved_period_count",
            "expected_metric_observation_count", "available_observation_count",
            "unavailable_observation_count", "exact_count", "derived_count",
            "estimated_count", "unavailable_count", "eligible_transition_count",
            "calculated_transition_count", "eligible_cagr_count",
            "calculated_cagr_count", "eligible_volatility_count",
            "calculated_volatility_count", "eligible_break_count",
            "calculated_break_count", "gap_count", "restatement_boundary_count",
        )
        for name in count_names:
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                _fail(f"{name} must be non-negative integer")
        if self.resolved_period_count > self.expected_period_count:
            _fail("resolved period count exceeds expected period count")
        if self.available_observation_count + self.unavailable_observation_count != self.expected_metric_observation_count:
            _fail("result observation counts do not balance")
        if self.exact_count + self.derived_count + self.estimated_count + self.unavailable_count != self.expected_metric_observation_count:
            _fail("result evidence counts do not balance")
        for eligible, calculated in (
            (self.eligible_transition_count, self.calculated_transition_count),
            (self.eligible_cagr_count, self.calculated_cagr_count),
            (self.eligible_volatility_count, self.calculated_volatility_count),
            (self.eligible_break_count, self.calculated_break_count),
        ):
            if calculated > eligible:
                _fail("calculated aggregate count exceeds eligible count")
        ratio = _decimal_or_none(self.available_ratio, "available_ratio")
        expected_ratio = (
            Decimal(0)
            if self.expected_metric_observation_count == 0
            else (Decimal(self.available_observation_count) / Decimal(self.expected_metric_observation_count)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_EVEN
            )
        )
        if ratio != normalize_decimal(expected_ratio):
            _fail("result available ratio does not match counts")
        object.__setattr__(self, "available_ratio", ratio)

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendMetricQuality(_SafeContractValue):
    metric_code: str
    availability: TrendFinalMetricAvailability
    evidence: TrendEvidenceLevel
    usable_observation_count: int
    segment_ordinals: tuple[int, ...]
    missing_period_ids: tuple[UUID, ...] = ()
    warning_codes: tuple[TrendWarningCode, ...] = ()
    error_codes: tuple[TrendErrorCode, ...] = ()

    def __post_init__(self) -> None:
        _text(self.metric_code, "metric_code", 128)
        if type(self.availability) is not TrendFinalMetricAvailability or type(self.evidence) is not TrendEvidenceLevel:
            _fail("metric quality enum is invalid")
        if type(self.usable_observation_count) is not int or self.usable_observation_count < 0:
            _fail("usable observation count must be non-negative integer")
        if type(self.segment_ordinals) is not tuple or any(type(item) is not int or item < 0 for item in self.segment_ordinals):
            _fail("segment ordinals must be immutable non-negative integers")
        if tuple(sorted(set(self.segment_ordinals))) != self.segment_ordinals:
            _fail("segment ordinals are not canonical")
        missing = _exact_tuple(self.missing_period_ids, UUID, "missing_period_ids")
        ordered_missing = tuple(sorted(set(missing), key=str))
        if len(ordered_missing) != len(missing):
            _fail("missing period identifiers contain duplicates")
        object.__setattr__(self, "missing_period_ids", ordered_missing)
        object.__setattr__(self, "warning_codes", _canonical_enums(self.warning_codes, TrendWarningCode, "warning_codes"))
        object.__setattr__(self, "error_codes", _canonical_enums(self.error_codes, TrendErrorCode, "error_codes"))
        if self.availability is TrendFinalMetricAvailability.UNAVAILABLE_MISSING_INPUT and not self.missing_period_ids and self.usable_observation_count > 0:
            _fail("incomplete metric quality must disclose missing periods")
        if self.availability in {
            TrendFinalMetricAvailability.INVALID,
            TrendFinalMetricAvailability.INTEGRITY_FAILURE,
        } and not self.error_codes:
            _fail("failed metric quality requires an error code")

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendUnavailableMetric(_SafeContractValue):
    metric_code: str
    availability: TrendFinalMetricAvailability
    missing_period_ids: tuple[UUID, ...]
    warning_codes: tuple[TrendWarningCode, ...] = ()

    def __post_init__(self) -> None:
        _text(self.metric_code, "metric_code", 128)
        if self.availability not in {
            TrendFinalMetricAvailability.UNAVAILABLE_MISSING_INPUT,
            TrendFinalMetricAvailability.UNAVAILABLE_INCOMPATIBLE_SOURCE,
        } or type(self.availability) is not TrendFinalMetricAvailability:
            _fail("unavailable metric reason is invalid")
        periods = _exact_tuple(self.missing_period_ids, UUID, "missing_period_ids")
        if len(set(periods)) != len(periods):
            _fail("unavailable metric period identifiers contain duplicates")
        object.__setattr__(self, "missing_period_ids", tuple(sorted(periods, key=str)))
        object.__setattr__(self, "warning_codes", _canonical_enums(self.warning_codes, TrendWarningCode, "warning_codes"))


@dataclass(frozen=True, repr=False)
class TrendDataQuality(_SafeContractValue):
    comparability_status: TrendComparabilityStatus
    profile: TrendComparabilityProfile
    completeness: TrendCompleteness
    evidence_summary: TrendEvidenceSummary
    gap_count: int
    restatement_boundary_count: int
    one_off_unknown_count: int
    result_completeness: TrendResultCompleteness | None = None
    metric_quality: tuple[TrendMetricQuality, ...] = ()
    missing_period_ids: tuple[UUID, ...] = ()
    missing_metric_codes: tuple[str, ...] = ()
    incompatible_source_count: int = 0
    segment_count: int = 0
    restatement_disclosure: TrendRestatementDisclosureStatus = TrendRestatementDisclosureStatus.ORIGINAL_ONLY
    one_off_disclosure: TrendOneOffDisclosureStatus = TrendOneOffDisclosureStatus.UNKNOWN_PRESENT
    quality_flags: tuple[TrendDataQualityFlag, ...] = ()
    warnings: tuple[TrendWarning, ...] = ()
    errors: tuple[TrendError, ...] = ()

    def __post_init__(self) -> None:
        if type(self.comparability_status) is not TrendComparabilityStatus:
            _fail("comparability status must be exact enum")
        if type(self.profile) is not TrendComparabilityProfile or type(self.completeness) is not TrendCompleteness or type(self.evidence_summary) is not TrendEvidenceSummary:
            _fail("data-quality subcontracts are invalid")
        for name in ("gap_count", "restatement_boundary_count", "one_off_unknown_count", "incompatible_source_count", "segment_count"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                _fail(f"{name} must be non-negative integer")
        if self.result_completeness is not None and type(self.result_completeness) is not TrendResultCompleteness:
            _fail("result completeness type is invalid")
        metrics = _exact_tuple(self.metric_quality, TrendMetricQuality, "metric_quality")
        ordered_metrics = tuple(sorted(metrics, key=lambda item: item.metric_code))
        if len({item.metric_code for item in ordered_metrics}) != len(ordered_metrics):
            _fail("metric quality contains duplicate metric code")
        object.__setattr__(self, "metric_quality", ordered_metrics)
        missing_periods = _exact_tuple(self.missing_period_ids, UUID, "missing_period_ids")
        object.__setattr__(self, "missing_period_ids", tuple(sorted(set(missing_periods), key=str)))
        missing_metrics = _exact_tuple(self.missing_metric_codes, str, "missing_metric_codes")
        if any(not item or len(item) > 128 for item in missing_metrics) or len(set(missing_metrics)) != len(missing_metrics):
            _fail("missing metric codes are invalid")
        object.__setattr__(self, "missing_metric_codes", tuple(sorted(missing_metrics)))
        if type(self.restatement_disclosure) is not TrendRestatementDisclosureStatus or type(self.one_off_disclosure) is not TrendOneOffDisclosureStatus:
            _fail("quality disclosure enum is invalid")
        object.__setattr__(self, "quality_flags", _canonical_enums(self.quality_flags, TrendDataQualityFlag, "quality_flags"))
        object.__setattr__(self, "warnings", _canonical_issues(self.warnings, TrendWarning, "warnings"))
        object.__setattr__(self, "errors", _canonical_issues(self.errors, TrendError, "errors"))

    @property
    def available_metric_count(self) -> int:
        return sum(
            item.availability in {
                TrendFinalMetricAvailability.AVAILABLE,
                TrendFinalMetricAvailability.PARTIAL,
            }
            for item in self.metric_quality
        )

    @property
    def unavailable_metric_count(self) -> int:
        return len(self.metric_quality) - self.available_metric_count

    @property
    def observation_count(self) -> int:
        return self.result_completeness.expected_metric_observation_count if self.result_completeness else self.completeness.expected_observation_count

    @property
    def required_observation_count(self) -> int:
        if self.result_completeness and self.result_completeness.expected_period_count:
            metric_count = (
                self.result_completeness.expected_metric_observation_count
                // self.result_completeness.expected_period_count
            )
            return metric_count * 3
        return 3

    @property
    def usable_observation_count(self) -> int:
        return self.result_completeness.available_observation_count if self.result_completeness else self.completeness.available_observation_count

    @property
    def transition_count(self) -> int:
        return self.result_completeness.eligible_transition_count if self.result_completeness else 0

    @property
    def usable_transition_count(self) -> int:
        return self.result_completeness.calculated_transition_count if self.result_completeness else 0

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)


@dataclass(frozen=True, repr=False)
class TrendNominalDisclosure(_SafeContractValue):
    profile: TrendNominalAnalysisProfile
    currency: str
    nominal_values: bool
    inflation_adjusted: bool

    def __post_init__(self) -> None:
        if self.profile is not TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT:
            _fail("unsupported nominal analysis profile")
        _currency(self.currency)
        if self.nominal_values is not True or self.inflation_adjusted is not False:
            _fail("v1 requires nominal/non-inflation-adjusted disclosure")


@dataclass(frozen=True, repr=False)
class MultiPeriodTrendResult(_SafeContractValue):
    company_id: UUID
    anchor_period_id: UUID
    status: TrendComputationStatus
    nominal_analysis_disclosure: TrendNominalDisclosure
    series: tuple[TrendMetricResult, ...]
    data_quality: TrendDataQuality
    source_references: tuple[TrendSourceReference, ...]
    lineage_references: tuple[TrendLineageReference, ...]
    policy_version: TrendPolicyVersion
    contract_version: TrendContractVersion
    warnings: tuple[TrendWarning, ...] = ()
    errors: tuple[TrendError, ...] = ()

    def __post_init__(self) -> None:
        _uuid(self.company_id, "company_id")
        _uuid(self.anchor_period_id, "anchor_period_id")
        if type(self.status) is not TrendComputationStatus:
            _fail("result status must be exact enum")
        if type(self.nominal_analysis_disclosure) is not TrendNominalDisclosure or type(self.data_quality) is not TrendDataQuality:
            _fail("result disclosure/data-quality type is invalid")
        series = _exact_tuple(self.series, TrendMetricResult, "series")
        ordered_series = tuple(sorted(series, key=lambda item: item.metric_code))
        if len({item.metric_code for item in ordered_series}) != len(ordered_series):
            _fail("result contains duplicate metric series")
        for item in ordered_series:
            if item.series.company_id != self.company_id or item.series.anchor_period_id != self.anchor_period_id:
                _fail("result series scope/anchor mismatch")
            if item.series.currency != self.nominal_analysis_disclosure.currency:
                _fail("result series currency mismatch")
        if ordered_series:
            expected_period_ids = tuple(item.period_id for item in ordered_series[0].series.observations)
            if any(tuple(observation.period_id for observation in item.series.observations) != expected_period_ids for item in ordered_series[1:]):
                _fail("result metric series do not share one ordered period set")
        object.__setattr__(self, "series", ordered_series)
        sources = _exact_tuple(self.source_references, TrendSourceReference, "source_references")
        ordered_sources = tuple(sorted(sources, key=lambda item: (str(item.period_id), item.source_engine_type.value, str(item.source_result_id))))
        if len({item.source_result_id for item in ordered_sources}) != len(ordered_sources):
            _fail("result contains duplicate source reference")
        if any(item.company_id != self.company_id for item in ordered_sources):
            _fail("result source reference company mismatch")
        object.__setattr__(self, "source_references", ordered_sources)
        lineage = _exact_tuple(self.lineage_references, TrendLineageReference, "lineage_references")
        ordered_lineage = tuple(sorted(lineage, key=lambda item: (item.ordinal, str(item.period_id), str(item.source_result_id))))
        if len({(item.ordinal, item.source_result_id) for item in ordered_lineage}) != len(ordered_lineage):
            _fail("result contains duplicate lineage reference")
        object.__setattr__(self, "lineage_references", ordered_lineage)
        if ordered_series:
            expected_sources = {
                (observation.period_id, observation.source_result_id)
                for item in ordered_series
                for observation in item.series.observations
            }
            actual_sources = {(item.period_id, item.source_result_id) for item in ordered_sources}
            actual_lineage = {(item.period_id, item.source_result_id) for item in ordered_lineage}
            if actual_sources != expected_sources or actual_lineage != expected_sources:
                _fail("result source/lineage references do not cover observations exactly")
            expected_count = sum(item.series.completeness.expected_observation_count for item in ordered_series)
            available_count = sum(item.series.completeness.available_observation_count for item in ordered_series)
            unavailable_count = sum(item.series.completeness.unavailable_observation_count for item in ordered_series)
            if (
                self.data_quality.completeness.expected_observation_count != expected_count
                or self.data_quality.completeness.available_observation_count != available_count
                or self.data_quality.completeness.unavailable_observation_count != unavailable_count
            ):
                _fail("result data-quality completeness does not match metric series")
            evidence_totals = (
                sum(item.series.evidence_summary.exact_count for item in ordered_series),
                sum(item.series.evidence_summary.derived_count for item in ordered_series),
                sum(item.series.evidence_summary.estimated_count for item in ordered_series),
                sum(item.series.evidence_summary.unavailable_count for item in ordered_series),
            )
            if evidence_totals != (
                self.data_quality.evidence_summary.exact_count,
                self.data_quality.evidence_summary.derived_count,
                self.data_quality.evidence_summary.estimated_count,
                self.data_quality.evidence_summary.unavailable_count,
            ):
                _fail("result data-quality evidence does not match metric series")
            unique_gaps = {
                (gap.after_period_id, gap.before_period_id)
                for item in ordered_series
                for gap in item.series.gaps
            }
            unique_restatements = {
                (boundary.after_period_id, boundary.before_period_id)
                for item in ordered_series
                for boundary in item.series.segment_boundaries
                if boundary.kind is TrendSegmentBoundaryKind.RESTATEMENT_CHANGE
            }
            one_off_unknown = sum(
                observation.one_off_status is TrendOneOffStatus.UNKNOWN
                for item in ordered_series
                for observation in item.series.observations
            )
            if (
                self.data_quality.gap_count != len(unique_gaps)
                or self.data_quality.restatement_boundary_count != len(unique_restatements)
                or self.data_quality.one_off_unknown_count != one_off_unknown
            ):
                _fail("result data-quality boundary/one-off counts are incorrect")
            if self.data_quality.result_completeness is not None:
                result_completeness = self.data_quality.result_completeness
                if (
                    result_completeness.available_observation_count != available_count
                    or result_completeness.gap_count != len(unique_gaps)
                    or result_completeness.restatement_boundary_count != len(unique_restatements)
                    or result_completeness.expected_metric_observation_count
                    != result_completeness.expected_period_count * len(self.data_quality.metric_quality)
                ):
                    _fail("result-level completeness does not match canonical series")
                quality_codes = {item.metric_code for item in self.data_quality.metric_quality}
                if (
                    not {item.metric_code for item in ordered_series}.issubset(quality_codes)
                    or not set(self.data_quality.missing_metric_codes).issubset(quality_codes)
                ):
                    _fail("metric-quality coverage does not match result series")
        if self.policy_version is not TrendPolicyVersion.V1 or self.contract_version is not TrendContractVersion.V1:
            _fail("result policy/contract version is unsupported")
        warnings = _canonical_issues(self.warnings, TrendWarning, "warnings")
        errors = _canonical_issues(self.errors, TrendError, "errors")
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        if self.status is TrendComputationStatus.COMPLETE:
            if not ordered_series or any(item.status is not TrendComputationStatus.COMPLETE for item in ordered_series) or errors:
                _fail("COMPLETE result requires complete series and no errors")
            if self.data_quality.result_completeness is not None and (
                self.data_quality.missing_metric_codes
                or any(
                    item.availability is not TrendFinalMetricAvailability.AVAILABLE
                    for item in self.data_quality.metric_quality
                )
            ):
                _fail("COMPLETE result requires every expected metric to be available")
        elif self.status is TrendComputationStatus.PARTIAL:
            if not ordered_series or not any(item.status in {TrendComputationStatus.COMPLETE, TrendComputationStatus.PARTIAL} for item in ordered_series):
                _fail("PARTIAL result requires at least one trend-bearing series")
        elif self.status is TrendComputationStatus.INSUFFICIENT_FOR_TREND:
            if not ordered_series or any(item.series.completeness.available_observation_count >= 3 for item in ordered_series):
                _fail("INSUFFICIENT_FOR_TREND cannot contain trend-bearing series")
        elif self.status is TrendComputationStatus.INSUFFICIENT_DATA:
            if any(item.series.completeness.available_observation_count >= 2 for item in ordered_series):
                _fail("INSUFFICIENT_DATA cannot contain pairwise-capable series")
        elif self.status in {TrendComputationStatus.INVALID_INPUT, TrendComputationStatus.INTEGRITY_FAILURE}:
            if not errors:
                _fail("failure result requires errors")

    @property
    def canonical_digest(self) -> str:
        return canonical_trend_digest(self)

    @property
    def canonical_reference(self) -> str:
        return canonical_trend_reference(self)
