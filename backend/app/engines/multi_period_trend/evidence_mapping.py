"""Closed source-result to trend-observation evidence mapping.

Inputs are narrow verified projections.  Raw engine payloads, trial balances,
account details, and confidence scores are intentionally not accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .canonical import normalize_decimal
from .registry import TrendEvidenceMappingProfile, TrendMetricDefinition
from .types import TrendEvidenceLevel, TrendSourceEngineType, weakest_evidence


class TrendSourceMetricStatus(str, Enum):
    RESULT_BEARING = "result_bearing"
    FAILED = "failed"
    INVALID = "invalid"
    INTEGRITY_FAILURE = "integrity_failure"


class TrendSourceMode(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"


class TrendRatioComputationStatus(str, Enum):
    CALCULATED = "calculated"
    NOT_CALCULABLE = "not_calculable"


class TrendRatioReliability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    MEDIUM_LOW = "medium_low"
    LOW = "low"
    NOT_CALCULABLE = "not_calculable"


class TrendEvidenceMappingReason(str, Enum):
    MAPPED = "mapped"
    MISSING_VALUE = "missing_value"
    SOURCE_FAILED = "source_failed"
    SOURCE_INVALID = "source_invalid"
    SOURCE_INTEGRITY_FAILURE = "source_integrity_failure"
    SOURCE_DIGEST_MISMATCH = "source_digest_mismatch"
    SOURCE_PROVENANCE_UNVERIFIED = "source_provenance_unverified"
    SOURCE_VERSION_UNSUPPORTED = "source_version_unsupported"
    SOURCE_MODE_UNSUPPORTED = "source_mode_unsupported"
    SOURCE_EVIDENCE_UNAVAILABLE = "source_evidence_unavailable"
    RATIO_NOT_CALCULABLE = "ratio_not_calculable"


class _SafeEvidenceValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


@dataclass(frozen=True, repr=False)
class TrendSourceMetricProjection(_SafeEvidenceValue):
    source_engine_type: TrendSourceEngineType
    schema_version: str | None
    model_version: str
    status: TrendSourceMetricStatus
    digest_verified: bool
    provenance_verified: bool
    field_present: bool
    value: Decimal | None
    source_evidence: TrendEvidenceLevel
    source_mode: TrendSourceMode | None = None
    ratio_status: TrendRatioComputationStatus | None = None
    ratio_reliability: TrendRatioReliability | None = None

    def __post_init__(self) -> None:
        if type(self.source_engine_type) is not TrendSourceEngineType:
            raise ValueError("source_engine_type must be exact enum")
        if self.schema_version is not None and (type(self.schema_version) is not str or not self.schema_version):
            raise ValueError("schema_version must be non-empty string or None")
        if type(self.model_version) is not str or not self.model_version:
            raise ValueError("model_version must be non-empty string")
        if type(self.status) is not TrendSourceMetricStatus:
            raise ValueError("status must be exact enum")
        if (
            type(self.digest_verified) is not bool
            or type(self.provenance_verified) is not bool
            or type(self.field_present) is not bool
        ):
            raise ValueError("digest/provenance verification and field_present must be bool")
        if self.value is not None:
            if type(self.value) is not Decimal or not self.value.is_finite():
                raise ValueError("value must be finite Decimal or None")
            object.__setattr__(self, "value", normalize_decimal(self.value))
        if not self.field_present and self.value is not None:
            raise ValueError("missing field cannot carry value")
        if type(self.source_evidence) is not TrendEvidenceLevel:
            raise ValueError("source_evidence must be exact enum")
        if self.status is not TrendSourceMetricStatus.RESULT_BEARING and self.value is not None:
            raise ValueError("non-result-bearing source cannot carry value")
        if self.source_engine_type in {
            TrendSourceEngineType.BALANCE_SHEET,
            TrendSourceEngineType.INCOME_STATEMENT,
        }:
            if self.source_mode is not None and type(self.source_mode) is not TrendSourceMode:
                raise ValueError("source_mode must be exact enum")
            if self.ratio_status is not None or self.ratio_reliability is not None:
                raise ValueError("BS/IS projection cannot carry ratio metadata")
        elif self.source_mode is not None:
            raise ValueError("source_mode is supported only for BS/IS projections")
        if self.source_engine_type is TrendSourceEngineType.FINANCIAL_RATIOS:
            if type(self.ratio_status) is not TrendRatioComputationStatus:
                raise ValueError("ratio projection requires ratio_status")
            if type(self.ratio_reliability) is not TrendRatioReliability:
                raise ValueError("ratio projection requires ratio_reliability")
            if self.ratio_status is TrendRatioComputationStatus.NOT_CALCULABLE:
                if self.value is not None or self.ratio_reliability is not TrendRatioReliability.NOT_CALCULABLE:
                    raise ValueError("not-calculable ratio cannot carry a value or reliability")
            elif self.ratio_reliability is TrendRatioReliability.NOT_CALCULABLE:
                raise ValueError("calculated ratio requires calculable reliability")
        elif self.ratio_status is not None or self.ratio_reliability is not None:
            raise ValueError("non-ratio projection cannot carry ratio metadata")


@dataclass(frozen=True, repr=False)
class TrendEvidenceMappingOutcome(_SafeEvidenceValue):
    source_accepted: bool
    value: Decimal | None
    evidence: TrendEvidenceLevel
    reason: TrendEvidenceMappingReason

    def __post_init__(self) -> None:
        if type(self.source_accepted) is not bool:
            raise ValueError("source_accepted must be bool")
        if self.value is not None and (type(self.value) is not Decimal or not self.value.is_finite()):
            raise ValueError("mapped value must be finite Decimal or None")
        if type(self.evidence) is not TrendEvidenceLevel or type(self.reason) is not TrendEvidenceMappingReason:
            raise ValueError("evidence outcome enums are invalid")
        if (self.value is None) != (self.evidence is TrendEvidenceLevel.UNAVAILABLE):
            raise ValueError("unavailable evidence must exactly match missing value")
        if not self.source_accepted and self.value is not None:
            raise ValueError("rejected source cannot produce usable observation")


def _unavailable(reason: TrendEvidenceMappingReason, *, accepted: bool) -> TrendEvidenceMappingOutcome:
    return TrendEvidenceMappingOutcome(accepted, None, TrendEvidenceLevel.UNAVAILABLE, reason)


def map_source_metric_evidence(
    definition: TrendMetricDefinition,
    source: TrendSourceMetricProjection,
) -> TrendEvidenceMappingOutcome:
    """Map a verified narrow source projection without ever upgrading evidence."""

    if type(definition) is not TrendMetricDefinition or type(source) is not TrendSourceMetricProjection:
        raise ValueError("exact metric definition and source projection are required")
    if source.source_engine_type is not definition.source_engine_type:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_INTEGRITY_FAILURE, accepted=False)
    if source.status is TrendSourceMetricStatus.FAILED:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_FAILED, accepted=False)
    if source.status is TrendSourceMetricStatus.INVALID:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_INVALID, accepted=False)
    if source.status is TrendSourceMetricStatus.INTEGRITY_FAILURE:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_INTEGRITY_FAILURE, accepted=False)
    if not source.digest_verified:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_DIGEST_MISMATCH, accepted=False)
    if not source.provenance_verified:
        return _unavailable(
            TrendEvidenceMappingReason.SOURCE_PROVENANCE_UNVERIFIED,
            accepted=False,
        )
    if not definition.source_compatibility(
        schema_version=source.schema_version, model_version=source.model_version
    ).accepted:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_VERSION_UNSUPPORTED, accepted=False)
    if (
        definition.evidence_mapping is TrendEvidenceMappingProfile.RATIO_RELIABILITY
        and source.ratio_status is TrendRatioComputationStatus.NOT_CALCULABLE
    ):
        return _unavailable(TrendEvidenceMappingReason.RATIO_NOT_CALCULABLE, accepted=True)
    if not source.field_present or source.value is None:
        return _unavailable(TrendEvidenceMappingReason.MISSING_VALUE, accepted=True)
    if source.source_evidence is TrendEvidenceLevel.UNAVAILABLE:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_EVIDENCE_UNAVAILABLE, accepted=True)

    profile = definition.evidence_mapping
    if profile in {
        TrendEvidenceMappingProfile.BALANCE_SHEET_SOURCE_MODE,
        TrendEvidenceMappingProfile.INCOME_STATEMENT_SOURCE_MODE,
    }:
        if source.source_mode is TrendSourceMode.DIRECT_DOCUMENT:
            candidate = TrendEvidenceLevel.EXACT
        elif source.source_mode is TrendSourceMode.TRIAL_BALANCE_DERIVED:
            candidate = TrendEvidenceLevel.DERIVED
        else:
            return _unavailable(TrendEvidenceMappingReason.SOURCE_MODE_UNSUPPORTED, accepted=False)
    elif profile is TrendEvidenceMappingProfile.CASH_FLOW_PASSTHROUGH:
        candidate = source.source_evidence
    elif profile is TrendEvidenceMappingProfile.RATIO_RELIABILITY:
        if source.ratio_status is TrendRatioComputationStatus.NOT_CALCULABLE:
            return _unavailable(TrendEvidenceMappingReason.RATIO_NOT_CALCULABLE, accepted=True)
        if source.ratio_reliability is TrendRatioReliability.LOW:
            candidate = TrendEvidenceLevel.ESTIMATED
        elif source.ratio_reliability in {
            TrendRatioReliability.HIGH,
            TrendRatioReliability.MEDIUM,
            TrendRatioReliability.MEDIUM_LOW,
        }:
            candidate = TrendEvidenceLevel.DERIVED
        else:
            return _unavailable(TrendEvidenceMappingReason.RATIO_NOT_CALCULABLE, accepted=True)
    else:  # pragma: no cover - closed enum and definition validation make this unreachable
        raise ValueError("unsupported evidence mapping profile")

    evidence = weakest_evidence(candidate, source.source_evidence)
    if evidence is TrendEvidenceLevel.UNAVAILABLE:
        return _unavailable(TrendEvidenceMappingReason.SOURCE_EVIDENCE_UNAVAILABLE, accepted=True)
    return TrendEvidenceMappingOutcome(True, source.value, evidence, TrendEvidenceMappingReason.MAPPED)
