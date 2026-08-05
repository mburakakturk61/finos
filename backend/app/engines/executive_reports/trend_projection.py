"""Presentation-only projection contracts for Executive Report 1.2.0.

The projection deliberately copies already-computed canonical Trend values.
It contains no financial formula, source resolver, persistence lookup, or
score/recommendation behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Final
from uuid import UUID

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    MultiPeriodTrendResult,
    TrendAggregateAvailability,
    TrendCagrStatus,
    TrendComparabilityStatus,
    TrendComputationStatus,
    TrendDirection,
    TrendEvidenceLevel,
    TrendFinalMetricAvailability,
    TrendMeasurementBasis,
    TrendMetricAvailability,
    TrendNegativeBaseDirection,
    TrendOneOffDisclosureStatus,
    TrendPeriodFamily,
    TrendRestatementDisclosureStatus,
    TrendTransitionKind,
    TrendVolatilityCategory,
    canonical_trend_digest,
    canonical_trend_reference,
)


TREND_REPORT_PRESENTATION_POLICY_VERSION_V1_2: Final = "trend-report-presentation/1.2.0"
TREND_REPORT_CONTRACT_VERSION_V1_2: Final = "1.2.0"
TREND_SOURCE_SCHEMA_VERSION_V1: Final = "1.0.0"
TREND_SOURCE_MODEL_VERSION_V1: Final = "1.0.0"

TREND_REPORT_METRIC_CODES_V1_2: Final = (
    "bs.total_assets",
    "bs.equity",
    "bs.cash_and_equivalents",
    "is.net_sales",
    "is.ebitda",
    "is.net_profit",
    "cf.operating_cash_flow",
    "cf.free_cash_flow",
    "ratio.current_ratio",
    "ratio.debt_to_equity",
    "ratio.net_profit_margin",
    "ratio.cash_flow_to_debt",
)

TREND_REPORT_METRIC_LABELS_TR_V1_2: Final = {
    "bs.total_assets": "Toplam Varlıklar",
    "bs.equity": "Özkaynaklar",
    "bs.cash_and_equivalents": "Nakit ve Nakit Benzerleri",
    "is.net_sales": "Net Satışlar",
    "is.ebitda": "FAVÖK",
    "is.net_profit": "Net Dönem Kârı/Zararı",
    "cf.operating_cash_flow": "İşletme Faaliyetlerinden Nakit Akışı",
    "cf.free_cash_flow": "Serbest Nakit Akışı",
    "ratio.current_ratio": "Cari Oran",
    "ratio.debt_to_equity": "Borç/Özkaynak Oranı",
    "ratio.net_profit_margin": "Net Kâr Marjı",
    "ratio.cash_flow_to_debt": "Nakit Akışı/Borç Oranı",
}


class TrendReportProjectionError(ValueError):
    """Safe boundary error; never includes source payload or raw exceptions."""

    __slots__ = ()


class TrendReportSourceStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT_FOR_TREND = "insufficient_for_trend"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, repr=False)
class TrendReportObservationV1_2:
    ordinal: int
    segment_ordinal: int
    period_id: UUID
    period_start_date: str
    period_end_date: str
    value: Decimal | None
    evidence: TrendEvidenceLevel
    source_result_id: UUID
    restatement_profile: str
    restatement_revision: int
    one_off_status: str
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class TrendReportTransitionV1_2:
    from_period_id: UUID
    to_period_id: UUID
    from_value: Decimal | None
    to_value: Decimal | None
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    percentage_unavailable_reason: str | None
    transition_kind: TrendTransitionKind
    direction: TrendDirection
    negative_base_direction: TrendNegativeBaseDirection
    evidence: TrendEvidenceLevel
    warning_codes: tuple[str, ...]
    error_codes: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class TrendReportAggregateV1_2:
    direction: TrendDirection
    direction_evidence: TrendEvidenceLevel
    cagr_value_percent: Decimal | None
    cagr_status: TrendCagrStatus | None
    cagr_evidence: TrendEvidenceLevel | None
    cagr_warning_codes: tuple[str, ...]
    stability: bool | None
    stability_availability: TrendAggregateAvailability | None
    stability_evidence: TrendEvidenceLevel | None
    stability_warning_codes: tuple[str, ...]
    volatility_value: Decimal | None
    volatility_category: TrendVolatilityCategory | None
    volatility_availability: TrendAggregateAvailability | None
    volatility_evidence: TrendEvidenceLevel | None
    volatility_warning_codes: tuple[str, ...]
    break_detected: bool | None
    break_unavailable_reason: str | None
    breakpoint_period_id: UUID | None
    break_direction: TrendDirection
    break_score: Decimal | None
    break_evidence: TrendEvidenceLevel
    break_warning_codes: tuple[str, ...]
    break_error_codes: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class TrendReportMetricV1_2:
    metric_code: str
    label_tr: str
    unit: str
    status: TrendComputationStatus | None
    availability: TrendMetricAvailability | None
    final_availability: TrendFinalMetricAvailability
    measurement_basis: TrendMeasurementBasis | None
    period_family: TrendPeriodFamily | None
    currency: str | None
    monetary_unit_multiplier: Decimal | None
    observations: tuple[TrendReportObservationV1_2, ...]
    transitions: tuple[TrendReportTransitionV1_2, ...]
    aggregate: TrendReportAggregateV1_2 | None
    metric_evidence: TrendEvidenceLevel
    usable_observation_count: int
    usable_transition_count: int
    missing_period_ids: tuple[UUID, ...]
    gap_pairs: tuple[tuple[UUID, UUID], ...]
    segment_boundaries: tuple[tuple[UUID, UUID, str], ...]
    warning_codes: tuple[str, ...]
    error_codes: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class TrendReportQualityV1_2:
    comparability_status: TrendComparabilityStatus
    observation_completeness: Decimal
    transition_completeness: Decimal
    expected_period_count: int
    resolved_period_count: int
    usable_observation_count: int
    usable_transition_count: int
    gap_count: int
    segment_count: int
    restatement_boundary_count: int
    one_off_unknown_count: int
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    unavailable_metric_count: int
    restatement_disclosure: TrendRestatementDisclosureStatus
    one_off_disclosure: TrendOneOffDisclosureStatus
    missing_period_ids: tuple[UUID, ...]
    missing_metric_codes: tuple[str, ...]
    quality_flag_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    error_codes: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class ExecutiveReportTrendProjectionV1_2:
    status: TrendReportSourceStatus
    company_id: UUID | None
    anchor_period_id: UUID | None
    report_contract_version: str
    trend_contract_version: str | None
    trend_schema_version: str | None
    trend_model_version: str | None
    metric_registry_version: str
    metric_registry_digest: str
    policy_version: str | None
    presentation_policy_version: str
    nominal_analysis_disclosure: str
    nominal_values: bool | None
    inflation_adjusted: bool | None
    currency: str | None
    comparability_status: TrendComparabilityStatus | None
    trend_result_reference: str | None
    trend_result_digest: str | None
    source_set_reference: str | None
    lineage_reference: str | None
    metrics: tuple[TrendReportMetricV1_2, ...]
    quality: TrendReportQualityV1_2 | None
    warning_codes: tuple[str, ...]
    error_codes: tuple[str, ...]
    presentation_digest: str

    def __repr__(self) -> str:
        return "ExecutiveReportTrendProjectionV1_2()"


def _issue_codes(items: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(sorted(item.code.value for item in items))


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise TrendReportProjectionError("non-finite Decimal is forbidden")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _digest_node(value: object) -> object:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TrendReportProjectionError("non-finite float is forbidden")
        return {"$type": "float", "value": repr(value)}
    if type(value) is Decimal:
        return {"$type": "decimal", "value": _decimal_text(value)}
    if type(value) is UUID:
        return {"$type": "uuid", "value": str(value)}
    if isinstance(value, Enum):
        return {"$type": "enum", "name": type(value).__name__, "value": value.value}
    if type(value) is tuple:
        return {"$type": "tuple", "items": [_digest_node(item) for item in value]}
    if type(value) is list:
        return {"$type": "list", "items": [_digest_node(item) for item in value]}
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TrendReportProjectionError("presentation mapping keys must be strings")
        return {"$type": "mapping", "items": [[key, _digest_node(value[key])] for key in sorted(value)]}
    if is_dataclass(value):
        return {
            "$type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [[field.name, _digest_node(getattr(value, field.name))] for field in fields(value)],
        }
    raise TrendReportProjectionError("unsupported presentation digest value")


def canonical_trend_report_presentation_digest_v1_2(value: object) -> str:
    encoded = json.dumps(
        _digest_node(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return sha256(b"executive-report/trend-presentation/v1.2\0" + encoded).hexdigest()


def _empty_metric(code: str) -> TrendReportMetricV1_2:
    definition = TREND_METRIC_REGISTRY_V1.get(code)
    return TrendReportMetricV1_2(
        code,
        TREND_REPORT_METRIC_LABELS_TR_V1_2[code],
        definition.unit.value,
        None,
        None,
        TrendFinalMetricAvailability.UNAVAILABLE_MISSING_INPUT,
        None,
        None,
        None,
        definition.monetary_unit_multiplier,
        (),
        (),
        None,
        TrendEvidenceLevel.UNAVAILABLE,
        0,
        0,
        (),
        (),
        (),
        (),
        (),
    )


def _metric_projection(result: MultiPeriodTrendResult, code: str) -> TrendReportMetricV1_2:
    definition = TREND_METRIC_REGISTRY_V1.get(code)
    metric = next((item for item in result.series if item.metric_code == code), None)
    quality = next((item for item in result.data_quality.metric_quality if item.metric_code == code), None)
    if metric is None:
        empty = _empty_metric(code)
        if quality is None:
            return empty
        return TrendReportMetricV1_2(
            empty.metric_code, empty.label_tr, empty.unit, None, None,
            quality.availability, None, None, None,
            definition.monetary_unit_multiplier, (), (), None, quality.evidence,
            quality.usable_observation_count, 0, quality.missing_period_ids, (), (),
            tuple(item.value for item in quality.warning_codes),
            tuple(item.value for item in quality.error_codes),
        )

    series = metric.series
    observations = tuple(
        TrendReportObservationV1_2(
            item.ordinal,
            item.segment_ordinal,
            item.period_id,
            item.period_start_date.isoformat(),
            item.period_end_date.isoformat(),
            item.value,
            item.evidence,
            item.source_result_id,
            item.restatement_profile.value,
            item.restatement_revision,
            item.one_off_status.value,
            _issue_codes(item.warnings),
        )
        for item in series.observations
    )
    transitions = tuple(
        TrendReportTransitionV1_2(
            item.from_period_id,
            item.to_period_id,
            item.from_value,
            item.to_value,
            item.absolute_change,
            item.percentage_change,
            None if item.percentage_change is not None else item.transition_kind.value,
            item.transition_kind,
            item.direction,
            item.negative_base_direction,
            item.evidence,
            _issue_codes(item.warnings),
            _issue_codes(item.errors),
        )
        for item in series.transitions
    )
    cagr = metric.cagr_result
    stability = metric.stability_result
    volatility = metric.volatility_result
    aggregate = TrendReportAggregateV1_2(
        metric.direction,
        metric.direction_evidence,
        None if cagr is None else cagr.value_percent,
        None if cagr is None else cagr.status,
        None if cagr is None else cagr.evidence,
        () if cagr is None else _issue_codes(cagr.warnings),
        None if stability is None else stability.stable,
        None if stability is None else stability.availability,
        None if stability is None else stability.evidence,
        () if stability is None else _issue_codes(stability.warnings),
        None if volatility is None else volatility.value,
        None if volatility is None else volatility.category,
        None if volatility is None else volatility.availability,
        None if volatility is None else volatility.evidence,
        () if volatility is None else _issue_codes(volatility.warnings),
        metric.break_result.detected,
        (
            None
            if metric.break_result.detected is not None
            else (_issue_codes(metric.break_result.warnings)[0] if metric.break_result.warnings else "break_unavailable")
        ),
        metric.break_result.breakpoint_period_id,
        metric.break_result.direction,
        metric.break_result.score,
        metric.break_result.evidence,
        _issue_codes(metric.break_result.warnings),
        _issue_codes(metric.break_result.errors),
    )
    final_availability = (
        quality.availability if quality is not None
        else TrendFinalMetricAvailability.AVAILABLE
        if metric.availability is TrendMetricAvailability.AVAILABLE
        else TrendFinalMetricAvailability.PARTIAL
    )
    return TrendReportMetricV1_2(
        code,
        TREND_REPORT_METRIC_LABELS_TR_V1_2[code],
        definition.unit.value,
        metric.status,
        metric.availability,
        final_availability,
        series.measurement_basis,
        series.period_family,
        series.currency,
        series.monetary_unit_multiplier,
        observations,
        transitions,
        aggregate,
        quality.evidence if quality is not None else series.evidence_summary.weakest_evidence,
        quality.usable_observation_count if quality is not None else series.completeness.available_observation_count,
        metric.transition_completeness.valid_count,
        quality.missing_period_ids if quality is not None else (),
        tuple((item.after_period_id, item.before_period_id) for item in series.gaps),
        tuple((item.after_period_id, item.before_period_id, item.kind.value) for item in series.segment_boundaries),
        tuple(sorted(set(
            _issue_codes(metric.warnings)
            + _issue_codes(series.warnings)
            + aggregate.cagr_warning_codes
            + aggregate.stability_warning_codes
            + aggregate.volatility_warning_codes
            + aggregate.break_warning_codes
        ))),
        tuple(sorted(set(
            _issue_codes(metric.errors)
            + _issue_codes(series.errors)
            + aggregate.break_error_codes
        ))),
    )


def _quality_projection(result: MultiPeriodTrendResult) -> TrendReportQualityV1_2:
    data = result.data_quality
    complete = data.result_completeness
    if complete is None:
        expected_periods = data.completeness.expected_observation_count
        resolved_periods = data.completeness.available_observation_count
        transition_ratio = Decimal(0)
    else:
        expected_periods = complete.expected_period_count
        resolved_periods = complete.resolved_period_count
        transition_ratio = (
            Decimal(0)
            if complete.eligible_transition_count == 0
            else Decimal(complete.calculated_transition_count) / Decimal(complete.eligible_transition_count)
        )
    return TrendReportQualityV1_2(
        data.comparability_status,
        data.completeness.available_ratio,
        transition_ratio,
        expected_periods,
        resolved_periods,
        data.usable_observation_count,
        data.usable_transition_count,
        data.gap_count,
        data.segment_count,
        data.restatement_boundary_count,
        data.one_off_unknown_count,
        data.evidence_summary.exact_count,
        data.evidence_summary.derived_count,
        data.evidence_summary.estimated_count,
        data.evidence_summary.unavailable_count,
        data.unavailable_metric_count,
        data.restatement_disclosure,
        data.one_off_disclosure,
        data.missing_period_ids,
        data.missing_metric_codes,
        tuple(item.value for item in data.quality_flags),
        _issue_codes(data.warnings),
        _issue_codes(data.errors),
    )


def _finalize_projection(**values: object) -> ExecutiveReportTrendProjectionV1_2:
    seed = ExecutiveReportTrendProjectionV1_2(**values, presentation_digest="")
    digest = canonical_trend_report_presentation_digest_v1_2(seed)
    return ExecutiveReportTrendProjectionV1_2(**values, presentation_digest=digest)


def project_trend_report_source_v1_2(
    *,
    requested: bool,
    result: MultiPeriodTrendResult | None,
    expected_company_id: UUID,
    expected_anchor_period_id: UUID,
    verified_result_digest: str | None,
    verified_result_reference: str | None,
    trend_schema_version: str | None = TREND_SOURCE_SCHEMA_VERSION_V1,
    trend_model_version: str | None = TREND_SOURCE_MODEL_VERSION_V1,
    failure_status: TrendComputationStatus | None = None,
    failure_error_codes: tuple[str, ...] = (),
) -> ExecutiveReportTrendProjectionV1_2:
    """Create a lossless, deterministic presentation projection.

    A caller must provide the verified canonical digest/reference for every
    result-bearing projection.  The function never trusts a caller payload or
    resolves historical sources.
    """

    if requested is not True:
        raise TrendReportProjectionError("trend report projection requires an explicit request")
    if type(expected_company_id) is not UUID or type(expected_anchor_period_id) is not UUID:
        raise TrendReportProjectionError("trend report scope must use exact UUID values")
    if result is None:
        if failure_status not in {
            None,
            TrendComputationStatus.INVALID_INPUT,
            TrendComputationStatus.INTEGRITY_FAILURE,
            TrendComputationStatus.INSUFFICIENT_DATA,
        }:
            raise TrendReportProjectionError("trend failure projection status is invalid")
        if verified_result_digest is not None or verified_result_reference is not None:
            raise TrendReportProjectionError("ownerless trend failure cannot carry a result reference")
        status = TrendReportSourceStatus.UNAVAILABLE if failure_status is None else TrendReportSourceStatus(failure_status.value)
        metrics = tuple(_empty_metric(code) for code in TREND_REPORT_METRIC_CODES_V1_2)
        return _finalize_projection(
            status=status,
            company_id=expected_company_id,
            anchor_period_id=expected_anchor_period_id,
            report_contract_version=TREND_REPORT_CONTRACT_VERSION_V1_2,
            trend_contract_version=None,
            trend_schema_version=None,
            trend_model_version=None,
            metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
            metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
            policy_version=None,
            presentation_policy_version=TREND_REPORT_PRESENTATION_POLICY_VERSION_V1_2,
            nominal_analysis_disclosure="Nominal trend sonucu kullanılamıyor; reel büyüme iddiası yoktur.",
            nominal_values=None,
            inflation_adjusted=None,
            currency=None,
            comparability_status=None,
            trend_result_reference=None,
            trend_result_digest=None,
            source_set_reference=None,
            lineage_reference=None,
            metrics=metrics,
            quality=None,
            warning_codes=("TREND_SOURCE_UNAVAILABLE",),
            error_codes=tuple(sorted(set(failure_error_codes))),
        )

    if type(result) is not MultiPeriodTrendResult or failure_status is not None or failure_error_codes:
        raise TrendReportProjectionError("trend report accepts exactly one canonical result")
    if (trend_schema_version, trend_model_version) != (
        TREND_SOURCE_SCHEMA_VERSION_V1,
        TREND_SOURCE_MODEL_VERSION_V1,
    ):
        raise TrendReportProjectionError("trend source version is unsupported")
    if result.company_id != expected_company_id or result.anchor_period_id != expected_anchor_period_id:
        raise TrendReportProjectionError("trend result scope mismatch")
    digest = canonical_trend_digest(result)
    reference = canonical_trend_reference(result)
    if verified_result_digest != digest or verified_result_reference != reference:
        raise TrendReportProjectionError("trend result digest/reference mismatch")
    if result.contract_version.value != TREND_SOURCE_SCHEMA_VERSION_V1:
        raise TrendReportProjectionError("trend contract version is unsupported")

    metrics = tuple(_metric_projection(result, code) for code in TREND_REPORT_METRIC_CODES_V1_2)
    quality = _quality_projection(result)
    warning_codes = tuple(sorted(set(_issue_codes(result.warnings) + quality.warning_codes)))
    error_codes = tuple(sorted(set(_issue_codes(result.errors) + quality.error_codes)))
    return _finalize_projection(
        status=TrendReportSourceStatus(result.status.value),
        company_id=result.company_id,
        anchor_period_id=result.anchor_period_id,
        report_contract_version=TREND_REPORT_CONTRACT_VERSION_V1_2,
        trend_contract_version=result.contract_version.value,
        trend_schema_version=trend_schema_version,
        trend_model_version=trend_model_version,
        metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        policy_version=result.policy_version.value,
        presentation_policy_version=TREND_REPORT_PRESENTATION_POLICY_VERSION_V1_2,
        nominal_analysis_disclosure="Nominal; enflasyondan arındırılmamıştır ve reel büyüme olarak yorumlanamaz.",
        nominal_values=result.nominal_analysis_disclosure.nominal_values,
        inflation_adjusted=result.nominal_analysis_disclosure.inflation_adjusted,
        currency=result.nominal_analysis_disclosure.currency,
        comparability_status=result.data_quality.comparability_status,
        trend_result_reference=reference,
        trend_result_digest=digest,
        source_set_reference=canonical_trend_reference(result.source_references),
        lineage_reference=canonical_trend_reference(result.lineage_references),
        metrics=metrics,
        quality=quality,
        warning_codes=warning_codes,
        error_codes=error_codes,
    )


if tuple(TREND_REPORT_METRIC_LABELS_TR_V1_2) != TREND_REPORT_METRIC_CODES_V1_2:
    raise RuntimeError("Trend report presentation manifest order is invalid")
for _metric_code in TREND_REPORT_METRIC_CODES_V1_2:
    TREND_METRIC_REGISTRY_V1.get(_metric_code)
