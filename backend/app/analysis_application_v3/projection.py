"""Lossless engine-to-Application-v3 Trend projection."""

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from app.engines.multi_period_trend import MultiPeriodTrendResult, TrendMetricResult

from .contracts import (
    ApplicationTrendCompletenessDTOV3, ApplicationTrendFieldDTOV3,
    ApplicationTrendIssueDTOV3, ApplicationTrendMetricResultDTOV3,
    ApplicationTrendObservationDTOV3, ApplicationTrendResultDTOV3,
    ApplicationTrendStatusV3, ApplicationTrendTransitionDTOV3,
)


def _value(value):
    if value is None or type(value) in {bool, str, int, Decimal, UUID, date, datetime}:
        return value
    if isinstance(value, Enum):
        return value.value
    if type(value) is tuple:
        return tuple(_value(item) for item in value)
    if is_dataclass(value):
        return tuple(ApplicationTrendFieldDTOV3(item.name, _value(getattr(value, item.name))) for item in fields(value))
    raise TypeError("unsupported Trend application projection value")


def _fields(value, *, exclude=()):
    return tuple(
        ApplicationTrendFieldDTOV3(item.name, _value(getattr(value, item.name)))
        for item in fields(value) if item.name not in exclude
    )


def _issue(value):
    return ApplicationTrendIssueDTOV3(type(value).__name__, _fields(value))


def _metric(value: TrendMetricResult) -> ApplicationTrendMetricResultDTOV3:
    return ApplicationTrendMetricResultDTOV3(
        value.metric_code,
        ApplicationTrendStatusV3(value.status.value),
        tuple(ApplicationTrendObservationDTOV3(_fields(item)) for item in value.series.observations),
        tuple(ApplicationTrendTransitionDTOV3(_fields(item)) for item in value.series.transitions),
        _fields(value, exclude=("metric_code", "status", "series")),
    )


def project_trend_result_v3(result: MultiPeriodTrendResult) -> ApplicationTrendResultDTOV3:
    if type(result) is not MultiPeriodTrendResult:
        raise TypeError("Trend projection requires exact MultiPeriodTrendResult")
    if result.status.value not in {item.value for item in ApplicationTrendStatusV3}:
        raise ValueError("failure-only Trend status cannot be projected as a result")
    completeness = result.data_quality.result_completeness or result.data_quality.completeness
    return ApplicationTrendResultDTOV3(
        result.company_id, result.anchor_period_id, ApplicationTrendStatusV3(result.status.value),
        _fields(result.nominal_analysis_disclosure), tuple(_metric(item) for item in result.series),
        ApplicationTrendCompletenessDTOV3(_fields(completeness)), _fields(result.data_quality),
        tuple(_fields(item) for item in result.source_references),
        tuple(_fields(item) for item in result.lineage_references),
        tuple(_issue(item) for item in result.warnings), tuple(_issue(item) for item in result.errors),
        result.canonical_digest,
    )
