from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    TrendEvidenceLevel,
    TrendEvidenceMappingReason,
    TrendRatioComputationStatus,
    TrendRatioReliability,
    TrendSourceEngineType,
    TrendSourceMetricProjection,
    TrendSourceMetricStatus,
    TrendSourceMode,
    map_source_metric_evidence,
)


def _projection(
    engine: TrendSourceEngineType,
    *,
    value: Decimal | None = Decimal("10.00"),
    evidence: TrendEvidenceLevel = TrendEvidenceLevel.EXACT,
    status: TrendSourceMetricStatus = TrendSourceMetricStatus.RESULT_BEARING,
    digest_verified: bool = True,
    provenance_verified: bool = True,
    field_present: bool = True,
    source_mode: TrendSourceMode | None = None,
    schema_version: str | None = None,
    model_version: str = "1.0.0",
    ratio_status: TrendRatioComputationStatus | None = None,
    ratio_reliability: TrendRatioReliability | None = None,
):
    if engine is TrendSourceEngineType.CASH_FLOW:
        schema_version = "1.0.0"
    if engine is TrendSourceEngineType.FINANCIAL_RATIOS:
        schema_version = "1.0"
        model_version = "1.1.0"
        ratio_status = ratio_status or TrendRatioComputationStatus.CALCULATED
        ratio_reliability = ratio_reliability or TrendRatioReliability.HIGH
    return TrendSourceMetricProjection(
        source_engine_type=engine,
        schema_version=schema_version,
        model_version=model_version,
        status=status,
        digest_verified=digest_verified,
        provenance_verified=provenance_verified,
        field_present=field_present,
        value=value,
        source_evidence=evidence,
        source_mode=source_mode,
        ratio_status=ratio_status,
        ratio_reliability=ratio_reliability,
    )


@pytest.mark.parametrize("metric_code", ("bs.total_assets", "is.net_sales"))
@pytest.mark.parametrize(
    "source_mode,source_evidence,expected",
    (
        (TrendSourceMode.DIRECT_DOCUMENT, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.EXACT),
        (TrendSourceMode.DIRECT_DOCUMENT, TrendEvidenceLevel.DERIVED, TrendEvidenceLevel.DERIVED),
        (TrendSourceMode.TRIAL_BALANCE_DERIVED, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.DERIVED),
        (TrendSourceMode.TRIAL_BALANCE_DERIVED, TrendEvidenceLevel.ESTIMATED, TrendEvidenceLevel.ESTIMATED),
    ),
)
def test_balance_sheet_income_statement_exact_derived_and_never_upgrade(
    metric_code, source_mode, source_evidence, expected
):
    definition = TREND_METRIC_REGISTRY_V1.get(metric_code)
    outcome = map_source_metric_evidence(
        definition,
        _projection(
            definition.source_engine_type,
            source_mode=source_mode,
            evidence=source_evidence,
        ),
    )
    assert outcome.source_accepted is True
    assert outcome.value == Decimal("10.00")
    assert outcome.evidence is expected
    assert outcome.reason is TrendEvidenceMappingReason.MAPPED


@pytest.mark.parametrize("evidence", tuple(TrendEvidenceLevel))
def test_cash_flow_evidence_is_passthrough_or_weakened_only(evidence):
    definition = TREND_METRIC_REGISTRY_V1.get("cf.operating_cash_flow")
    source = _projection(TrendSourceEngineType.CASH_FLOW, evidence=evidence)
    outcome = map_source_metric_evidence(definition, source)
    if evidence is TrendEvidenceLevel.UNAVAILABLE:
        assert outcome.value is None
        assert outcome.evidence is TrendEvidenceLevel.UNAVAILABLE
    else:
        assert outcome.value == Decimal("10.00")
        assert outcome.evidence is evidence


@pytest.mark.parametrize(
    "reliability,source_evidence,expected",
    (
        (TrendRatioReliability.HIGH, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.DERIVED),
        (TrendRatioReliability.MEDIUM, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.DERIVED),
        (TrendRatioReliability.MEDIUM_LOW, TrendEvidenceLevel.DERIVED, TrendEvidenceLevel.DERIVED),
        (TrendRatioReliability.LOW, TrendEvidenceLevel.EXACT, TrendEvidenceLevel.ESTIMATED),
        (TrendRatioReliability.HIGH, TrendEvidenceLevel.ESTIMATED, TrendEvidenceLevel.ESTIMATED),
    ),
)
def test_ratio_evidence_is_never_exact_and_low_is_estimated(
    reliability, source_evidence, expected
):
    definition = TREND_METRIC_REGISTRY_V1.get("ratio.current_ratio")
    outcome = map_source_metric_evidence(
        definition,
        _projection(
            TrendSourceEngineType.FINANCIAL_RATIOS,
            evidence=source_evidence,
            ratio_reliability=reliability,
        ),
    )
    assert outcome.evidence is expected
    assert outcome.evidence is not TrendEvidenceLevel.EXACT


def test_not_calculable_ratio_maps_to_unavailable_without_zero():
    definition = TREND_METRIC_REGISTRY_V1.get("ratio.current_ratio")
    outcome = map_source_metric_evidence(
        definition,
        _projection(
            TrendSourceEngineType.FINANCIAL_RATIOS,
            value=None,
            evidence=TrendEvidenceLevel.UNAVAILABLE,
            ratio_status=TrendRatioComputationStatus.NOT_CALCULABLE,
            ratio_reliability=TrendRatioReliability.NOT_CALCULABLE,
        ),
    )
    assert outcome.source_accepted is True
    assert outcome.value is None
    assert outcome.evidence is TrendEvidenceLevel.UNAVAILABLE
    assert outcome.reason is TrendEvidenceMappingReason.RATIO_NOT_CALCULABLE


@pytest.mark.parametrize("metric_code", ("bs.total_assets", "is.net_sales", "cf.free_cash_flow", "ratio.debt_ratio"))
def test_missing_field_and_none_are_unavailable_not_decimal_zero(metric_code):
    definition = TREND_METRIC_REGISTRY_V1.get(metric_code)
    kwargs = {}
    if definition.source_engine_type in {TrendSourceEngineType.BALANCE_SHEET, TrendSourceEngineType.INCOME_STATEMENT}:
        kwargs["source_mode"] = TrendSourceMode.DIRECT_DOCUMENT
    outcome = map_source_metric_evidence(
        definition,
        _projection(
            definition.source_engine_type,
            value=None,
            field_present=False,
            evidence=TrendEvidenceLevel.UNAVAILABLE,
            **kwargs,
        ),
    )
    assert outcome.value is None
    assert outcome.evidence is TrendEvidenceLevel.UNAVAILABLE
    assert outcome.reason is TrendEvidenceMappingReason.MISSING_VALUE


@pytest.mark.parametrize(
    "status,reason",
    (
        (TrendSourceMetricStatus.FAILED, TrendEvidenceMappingReason.SOURCE_FAILED),
        (TrendSourceMetricStatus.INVALID, TrendEvidenceMappingReason.SOURCE_INVALID),
        (TrendSourceMetricStatus.INTEGRITY_FAILURE, TrendEvidenceMappingReason.SOURCE_INTEGRITY_FAILURE),
    ),
)
def test_failed_invalid_and_integrity_sources_produce_no_usable_observation(status, reason):
    definition = TREND_METRIC_REGISTRY_V1.get("bs.total_assets")
    outcome = map_source_metric_evidence(
        definition,
        _projection(
            TrendSourceEngineType.BALANCE_SHEET,
            value=None,
            evidence=TrendEvidenceLevel.UNAVAILABLE,
            status=status,
            source_mode=TrendSourceMode.DIRECT_DOCUMENT,
        ),
    )
    assert outcome.source_accepted is False
    assert outcome.value is None
    assert outcome.reason is reason


def test_digest_provenance_mismatch_and_wrong_engine_are_fail_closed():
    definition = TREND_METRIC_REGISTRY_V1.get("bs.total_assets")
    digest_failure = map_source_metric_evidence(
        definition,
        _projection(
            TrendSourceEngineType.BALANCE_SHEET,
            digest_verified=False,
            source_mode=TrendSourceMode.DIRECT_DOCUMENT,
        ),
    )
    wrong_engine = map_source_metric_evidence(
        definition,
        _projection(TrendSourceEngineType.CASH_FLOW),
    )
    provenance_failure = map_source_metric_evidence(
        definition,
        _projection(
            TrendSourceEngineType.BALANCE_SHEET,
            provenance_verified=False,
            source_mode=TrendSourceMode.DIRECT_DOCUMENT,
        ),
    )
    assert digest_failure.source_accepted is False
    assert digest_failure.reason is TrendEvidenceMappingReason.SOURCE_DIGEST_MISMATCH
    assert provenance_failure.source_accepted is False
    assert provenance_failure.reason is TrendEvidenceMappingReason.SOURCE_PROVENANCE_UNVERIFIED
    assert wrong_engine.source_accepted is False
    assert wrong_engine.reason is TrendEvidenceMappingReason.SOURCE_INTEGRITY_FAILURE


@pytest.mark.parametrize(
    "schema_version,model_version",
    (("99.0", "1.1.0"), ("1.0", "99.0.0"), ("2.0", "2.0.0")),
)
def test_unknown_and_cross_major_source_versions_never_resolve(schema_version, model_version):
    definition = TREND_METRIC_REGISTRY_V1.get("ratio.current_ratio")
    source = _projection(TrendSourceEngineType.FINANCIAL_RATIOS)
    source = TrendSourceMetricProjection(
        source.source_engine_type, schema_version, model_version, source.status,
        source.digest_verified, source.provenance_verified, source.field_present, source.value,
        source.source_evidence, source.source_mode, source.ratio_status,
        source.ratio_reliability,
    )
    outcome = map_source_metric_evidence(definition, source)
    assert outcome.source_accepted is False
    assert outcome.reason is TrendEvidenceMappingReason.SOURCE_VERSION_UNSUPPORTED


def test_projection_is_immutable_safe_and_rejects_confidence_or_raw_payload_fields():
    projection = _projection(
        TrendSourceEngineType.BALANCE_SHEET,
        source_mode=TrendSourceMode.DIRECT_DOCUMENT,
    )
    with pytest.raises(FrozenInstanceError):
        projection.value = Decimal("1")
    assert repr(projection) == "TrendSourceMetricProjection()"
    assert "10.00" not in repr(projection)
    with pytest.raises(TypeError):
        TrendSourceMetricProjection(
            source_engine_type=TrendSourceEngineType.BALANCE_SHEET,
            schema_version=None,
            model_version="1.0.0",
            status=TrendSourceMetricStatus.RESULT_BEARING,
            digest_verified=True,
            provenance_verified=True,
            field_present=True,
            value=Decimal("10"),
            source_evidence=TrendEvidenceLevel.EXACT,
            source_mode=TrendSourceMode.DIRECT_DOCUMENT,
            confidence_score=Decimal("1"),
        )


def test_negative_zero_is_canonicalized_without_fabricating_missing_value():
    projection = _projection(
        TrendSourceEngineType.BALANCE_SHEET,
        value=Decimal("-0.00"),
        source_mode=TrendSourceMode.DIRECT_DOCUMENT,
    )
    outcome = map_source_metric_evidence(
        TREND_METRIC_REGISTRY_V1.get("bs.total_assets"), projection
    )
    assert outcome.value == Decimal(0)
    assert outcome.value.as_tuple().sign == 0


def test_evidence_mapping_module_has_no_raw_source_or_trend_calculation_surface():
    import app.engines.multi_period_trend.evidence_mapping as module

    assert not hasattr(module, "resolve_series")
    assert not hasattr(module, "calculate_direction")
    assert not hasattr(module, "calculate_cagr")
    assert not hasattr(module, "raw_payload")
