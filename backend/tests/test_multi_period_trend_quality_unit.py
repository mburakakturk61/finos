from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from app.engines.multi_period_trend import (
    TREND_METRIC_REGISTRY_V1,
    TrendComparabilityProfile,
    TrendComputationStatus,
    TrendCoverageKind,
    TrendDataQualityFlag,
    TrendDuplicatePolicy,
    TrendEvidenceLevel,
    TrendFinalMetricAvailability,
    TrendGapPolicy,
    TrendNominalAnalysisProfile,
    TrendOneOffDisclosureStatus,
    TrendOneOffStatus,
    TrendOverlapPolicy,
    TrendPeriodFamily,
    TrendRestatementDisclosureStatus,
    TrendRestatementProfile,
    TrendResultAssemblyError,
    TrendUnavailableMetric,
    TrendWarningCode,
    analyze_trend_aggregates,
    assemble_multi_period_trend_result,
    classify_metric_quality,
)

from test_multi_period_trend_pairwise_unit import COMPANY, TENANT, resolved_series


def _profile(*, restatement=TrendRestatementProfile.ORIGINAL):
    return TrendComparabilityProfile(
        tenant_id=TENANT,
        company_id=COMPANY,
        currency="TRY",
        accounting_basis="tfrs",
        accounting_policy_version="1.0.0",
        fiscal_calendar_reference="calendar-year",
        period_family=TrendPeriodFamily.ANNUAL,
        coverage_kind=TrendCoverageKind.CUMULATIVE,
        source_schema_version=None,
        source_model_version="1.0.0",
        require_source_digest=True,
        restatement_profile=restatement,
        nominal_analysis_profile=TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT,
        gap_policy=TrendGapPolicy.SEGMENT_WITHOUT_FILL,
        overlap_policy=TrendOverlapPolicy.REJECT,
        duplicate_policy=TrendDuplicatePolicy.REJECT,
    )


def _assemble(values, **series_kwargs):
    series = resolved_series(tuple(Decimal(str(item)) if item is not None else None for item in values), **series_kwargs)
    return assemble_multi_period_trend_result(
        (series,), _profile(), expected_metric_codes=(series.metric_code,)
    )


def test_complete_result_and_full_quality_counts():
    result = _assemble((100, 110, 121, 133.1, 146.41))
    completeness = result.data_quality.result_completeness
    assert result.status is TrendComputationStatus.COMPLETE
    assert completeness.expected_period_count == 5
    assert completeness.expected_metric_observation_count == 5
    assert completeness.available_observation_count == 5
    assert completeness.unavailable_observation_count == 0
    assert completeness.calculated_transition_count == 4
    assert completeness.calculated_cagr_count == 1
    assert completeness.calculated_volatility_count == 1
    assert completeness.calculated_break_count == 1
    assert result.data_quality.metric_quality[0].availability is TrendFinalMetricAvailability.AVAILABLE
    assert result.data_quality.metric_quality[0].evidence is TrendEvidenceLevel.DERIVED
    assert result.data_quality.observation_count == 5
    assert result.data_quality.required_observation_count == 3
    assert result.data_quality.usable_observation_count == 5
    assert result.data_quality.available_metric_count == 1
    assert result.data_quality.unavailable_metric_count == 0
    assert result.nominal_analysis_disclosure.nominal_values is True
    assert result.nominal_analysis_disclosure.inflation_adjusted is False


def test_final_metric_availability_taxonomy_is_closed_and_ineligible_cagr_is_non_failure():
    assert tuple(item.value for item in TrendFinalMetricAvailability) == (
        "available",
        "partial",
        "insufficient_observations",
        "not_eligible",
        "unavailable_missing_input",
        "unavailable_incompatible_source",
        "invalid",
        "integrity_failure",
    )
    resolved = resolved_series(
        (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")),
        metric_code="ratio.current_ratio",
    )
    metric = analyze_trend_aggregates(resolved)
    definition = TREND_METRIC_REGISTRY_V1.get(resolved.metric_code)
    quality = classify_metric_quality(metric, definition)
    assert metric.cagr_result.status.value == "disabled"
    assert quality.availability is TrendFinalMetricAvailability.AVAILABLE
    assert quality.error_codes == ()


@pytest.mark.parametrize(
    ("values", "status", "availability"),
    [
        ((100, 110, 121), TrendComputationStatus.PARTIAL, TrendFinalMetricAvailability.PARTIAL),
        ((100, 110, 121, 133), TrendComputationStatus.PARTIAL, TrendFinalMetricAvailability.PARTIAL),
        ((100, 110), TrendComputationStatus.INSUFFICIENT_FOR_TREND, TrendFinalMetricAvailability.INSUFFICIENT_OBSERVATIONS),
        ((100, None), TrendComputationStatus.INSUFFICIENT_DATA, TrendFinalMetricAvailability.INSUFFICIENT_OBSERVATIONS),
    ],
)
def test_final_status_and_minimum_observation_matrix(values, status, availability):
    result = _assemble(values)
    assert result.status is status
    assert result.data_quality.metric_quality[0].availability is availability


def test_three_observations_keep_direction_but_volatility_and_break_unavailable():
    result = _assemble((100, 110, 121))
    metric = result.series[0]
    assert metric.direction.value == "increasing"
    assert metric.volatility_result.value is None
    assert metric.break_result.detected is None
    assert result.status is TrendComputationStatus.PARTIAL


def test_four_observations_calculate_volatility_but_not_break():
    result = _assemble((100, 110, 121, 133))
    metric = result.series[0]
    assert metric.volatility_result.value is not None
    assert metric.break_result.detected is None


def test_estimated_input_caps_metric_and_result_without_evidence_upgrade():
    evidence = (
        TrendEvidenceLevel.EXACT,
        TrendEvidenceLevel.DERIVED,
        TrendEvidenceLevel.ESTIMATED,
        TrendEvidenceLevel.EXACT,
        TrendEvidenceLevel.EXACT,
    )
    result = _assemble((100, 110, 121, 133, 146), evidence=evidence)
    quality = result.data_quality.metric_quality[0]
    assert result.status is TrendComputationStatus.PARTIAL
    assert quality.evidence is TrendEvidenceLevel.ESTIMATED
    assert result.data_quality.result_completeness.estimated_count == 1
    assert all(
        item.evidence is not TrendEvidenceLevel.EXACT
        for item in result.series[0].series.transitions
    )


def test_unavailable_is_never_fabricated_as_zero():
    result = _assemble((100, None, 121, 133, 146))
    observations = result.series[0].series.observations
    assert observations[1].value is None
    assert observations[1].evidence is TrendEvidenceLevel.UNAVAILABLE
    assert result.data_quality.missing_period_ids == (observations[1].period_id,)
    assert result.data_quality.result_completeness.unavailable_count == 1


def test_gap_is_segmented_without_bridge_or_fabricated_observation():
    result = _assemble((100, 110, 121, 133, 146), segments=(0, 0, 1, 1, 1), years=(2020, 2021, 2023, 2024, 2025))
    metric = result.series[0]
    assert result.status is TrendComputationStatus.PARTIAL
    assert result.data_quality.gap_count == 1
    assert result.data_quality.segment_count == 2
    assert TrendDataQualityFlag.MISSING_PERIOD in result.data_quality.quality_flags
    assert len(metric.series.observations) == 5
    assert all(
        not (item.from_period_id == metric.series.observations[1].period_id and item.to_period_id == metric.series.observations[2].period_id)
        for item in metric.series.transitions
    )


def test_restatement_boundary_and_unknown_disclosures_are_explicit():
    restatements = (
        TrendRestatementProfile.ORIGINAL,
        TrendRestatementProfile.ORIGINAL,
        TrendRestatementProfile.RESTATED,
        TrendRestatementProfile.RESTATED,
        TrendRestatementProfile.RESTATED,
    )
    result = _assemble(
        (100, 110, 121, 133, 146),
        segments=(0, 0, 1, 1, 1),
        restatements=restatements,
        one_offs=(TrendOneOffStatus.UNKNOWN,) * 5,
    )
    assert result.data_quality.restatement_disclosure is TrendRestatementDisclosureStatus.MIXED_SEGMENTED
    assert result.data_quality.one_off_disclosure is TrendOneOffDisclosureStatus.UNKNOWN_PRESENT
    assert result.data_quality.restatement_boundary_count == 1
    assert result.data_quality.one_off_unknown_count == 5
    assert TrendDataQualityFlag.RESTATEMENT_BOUNDARY in result.data_quality.quality_flags
    assert TrendDataQualityFlag.ONE_OFF_UNADJUSTED in result.data_quality.quality_flags


def test_legacy_restatement_is_unknown_not_original():
    result = _assemble(
        (100, 110, 121, 133, 146),
        restatements=(TrendRestatementProfile.UNDECLARED_LEGACY,) * 5,
    )
    assert result.data_quality.restatement_disclosure is TrendRestatementDisclosureStatus.UNKNOWN_PRESENT
    assert TrendDataQualityFlag.RESTATEMENT_UNKNOWN in result.data_quality.quality_flags


def test_missing_registry_metric_is_partial_and_counted_without_zero_series():
    series = resolved_series((Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133"), Decimal("146")))
    result = assemble_multi_period_trend_result(
        (series,),
        _profile(),
        expected_metric_codes=("bs.total_assets", "bs.cash_and_equivalents"),
    )
    assert result.status is TrendComputationStatus.PARTIAL
    assert len(result.series) == 1
    assert result.data_quality.missing_metric_codes == ("bs.cash_and_equivalents",)
    assert result.data_quality.result_completeness.expected_metric_observation_count == 10
    assert result.data_quality.result_completeness.unavailable_count == 5
    missing = next(item for item in result.data_quality.metric_quality if item.metric_code != "bs.total_assets")
    assert missing.availability is TrendFinalMetricAvailability.UNAVAILABLE_MISSING_INPUT


def test_incompatible_source_is_typed_and_does_not_zero_other_metric():
    series = resolved_series((Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133"), Decimal("146")))
    period_ids = tuple(item.observation.period_id for item in series.observations)
    unavailable = TrendUnavailableMetric(
        metric_code="bs.cash_and_equivalents",
        availability=TrendFinalMetricAvailability.UNAVAILABLE_INCOMPATIBLE_SOURCE,
        missing_period_ids=period_ids,
    )
    result = assemble_multi_period_trend_result(
        (series,),
        _profile(),
        expected_metric_codes=("bs.total_assets", "bs.cash_and_equivalents"),
        unavailable_metrics=(unavailable,),
    )
    assert result.status is TrendComputationStatus.PARTIAL
    assert result.data_quality.incompatible_source_count == 1
    incompatible = next(item for item in result.data_quality.metric_quality if item.metric_code == unavailable.metric_code)
    assert incompatible.availability is TrendFinalMetricAvailability.UNAVAILABLE_INCOMPATIBLE_SOURCE
    assert result.series[0].series.observations[0].value == Decimal("100.00")


def test_final_result_preserves_aggregate_fields_decimal_and_lineage_intent():
    result = _assemble((100, 110, 121, 133, 146))
    metric = result.series[0]
    assert type(metric.cagr_result.value_percent) is Decimal
    assert type(metric.stability_result.stable_tolerance) is Decimal
    assert type(metric.volatility_result.value) is Decimal
    assert metric.break_result.detected is not None
    assert len(result.source_references) == 5
    assert len(result.lineage_references) == 5
    assert all(item.lineage_schema_version == "1.0.0" for item in result.lineage_references)
    assert repr(result) == "MultiPeriodTrendResult()"
    assert "100" not in repr(result)


def test_warning_and_flag_order_is_canonical():
    result = _assemble(
        (100, 110, 121), one_offs=(TrendOneOffStatus.UNKNOWN,) * 3
    )
    assert tuple(item.code.value for item in result.warnings) == tuple(sorted(
        item.code.value for item in result.warnings
    ))
    flag_order = {item: index for index, item in enumerate(TrendDataQualityFlag)}
    assert result.data_quality.quality_flags == tuple(sorted(result.data_quality.quality_flags, key=flag_order.__getitem__))


def test_invalid_input_and_integrity_failure_are_safe_typed_failures():
    with pytest.raises(TrendResultAssemblyError) as invalid:
        assemble_multi_period_trend_result([], _profile())  # type: ignore[arg-type]
    assert invalid.value.status is TrendComputationStatus.INVALID_INPUT
    series = resolved_series((Decimal("1"), Decimal("2"), Decimal("3")))
    with pytest.raises(TrendResultAssemblyError) as integrity:
        assemble_multi_period_trend_result((series, series), _profile(), expected_metric_codes=(series.metric_code,))
    assert integrity.value.status is TrendComputationStatus.INTEGRITY_FAILURE
    assert invalid.value.args == ()
    assert invalid.value.__cause__ is None
    assert invalid.value.__context__ is None
    assert "Decimal" not in repr(integrity.value)
    with pytest.raises(TypeError):
        class InvalidAssemblyError(TrendResultAssemblyError):
            pass
    result = _assemble((1, 2, 3))
    with pytest.raises(FrozenInstanceError):
        result.status = TrendComputationStatus.COMPLETE  # type: ignore[misc]


def test_unknown_expected_metric_and_scope_mismatch_fail_closed():
    series = resolved_series((Decimal("1"), Decimal("2"), Decimal("3")))
    with pytest.raises(TrendResultAssemblyError) as unknown:
        assemble_multi_period_trend_result((series,), _profile(), expected_metric_codes=("unknown.metric",))
    assert unknown.value.status is TrendComputationStatus.INVALID_INPUT
    other_company = type(COMPANY)("22222222-2222-4222-8222-222222222222")
    wrong_profile = replace(_profile(), company_id=other_company)
    assert other_company != COMPANY
    with pytest.raises(TrendResultAssemblyError) as mismatch:
        assemble_multi_period_trend_result((series,), wrong_profile, expected_metric_codes=(series.metric_code,))
    assert mismatch.value.status is TrendComputationStatus.INTEGRITY_FAILURE
