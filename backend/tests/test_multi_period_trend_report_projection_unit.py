from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from app.engines.common.report_types import ReportSectionCode, ReportType
from app.engines.executive_reports.cash_flow_integration import generate_executive_report_v1_1
from app.engines.executive_reports.trend_integration import (
    REPORT_MODEL_VERSION_V1_2_TREND,
    REPORT_REGISTRY_V1_2_TREND,
    REPORT_SCHEMA_VERSION_V1_2_TREND,
    canonical_report_presentation_digest_v1_2,
    generate_executive_report_v1_2,
    integrate_trend_report_v1_2,
)
from app.engines.executive_reports.trend_projection import (
    TREND_REPORT_METRIC_CODES_V1_2,
    TREND_REPORT_METRIC_LABELS_TR_V1_2,
    TrendReportProjectionError,
    TrendReportSourceStatus,
    canonical_trend_report_presentation_digest_v1_2,
    project_trend_report_source_v1_2,
)
from app.engines.multi_period_trend import (
    TrendComputationStatus,
    TrendErrorCode,
    TrendEvidenceLevel,
    TrendOneOffStatus,
    TrendRestatementProfile,
    canonical_trend_digest,
    canonical_trend_reference,
)

from test_multi_period_trend_quality_unit import _assemble
from test_report_pipeline_unit import _build_upstream, _cm


def _projection(values=(100, 110, 121, 133, 146), **kwargs):
    result = _assemble(values, **kwargs)
    return result, project_trend_report_source_v1_2(
        requested=True,
        result=result,
        expected_company_id=result.company_id,
        expected_anchor_period_id=result.anchor_period_id,
        verified_result_digest=canonical_trend_digest(result),
        verified_result_reference=canonical_trend_reference(result),
    )


def _base_report(*, cash=False):
    bs, income, ratio, benchmark, health, credit, recommendation = _build_upstream()
    kwargs = {}
    if cash:
        from test_cash_flow_report_integration_unit import _cash_result
        from app.engines.cash_flow import CashFlowResultStatus
        kwargs = {
            "cash_flow_requested": True,
            "cash_flow_result": _cash_result(CashFlowResultStatus.COMPLETE_RECONCILED),
        }
    return generate_executive_report_v1_1(
        ReportType.CFO_EXECUTIVE_REPORT,
        bs,
        income,
        ratio,
        benchmark,
        health,
        credit,
        recommendation,
        company_metadata=_cm(),
        reporting_period_label_tr="2025",
        **kwargs,
    )


def _trend_blocks(report):
    section = next(item for item in report.sections if item.section_code is ReportSectionCode.SEC_PERIOD_COMPARISON_ANALYSIS)
    return tuple(item for item in section.content_blocks if item.source_field_path.startswith("multi_period_trend"))


def test_report_1_2_contract_registry_and_exact_presentation_manifest():
    assert (REPORT_SCHEMA_VERSION_V1_2_TREND, REPORT_MODEL_VERSION_V1_2_TREND) == ("1.2.0", "1.2.0")
    assert REPORT_REGISTRY_V1_2_TREND == tuple(ReportSectionCode)
    assert len(TREND_REPORT_METRIC_CODES_V1_2) == len(set(TREND_REPORT_METRIC_CODES_V1_2)) == 12
    assert tuple(TREND_REPORT_METRIC_LABELS_TR_V1_2) == TREND_REPORT_METRIC_CODES_V1_2


def test_complete_projection_is_lossless_decimal_nominal_and_deterministic():
    result, first = _projection()
    _, second = _projection()
    metric = first.metrics[0]
    assert first.status is TrendReportSourceStatus.COMPLETE
    assert first.company_id == result.company_id and first.anchor_period_id == result.anchor_period_id
    assert first.nominal_values is True and first.inflation_adjusted is False
    assert "enflasyondan arındırılmamıştır" in first.nominal_analysis_disclosure
    assert first.trend_result_digest == canonical_trend_digest(result)
    assert first.trend_result_reference == canonical_trend_reference(result)
    assert len(first.metrics) == 12 and type(metric.observations[0].value) is Decimal
    assert metric.observations[0].value == Decimal("100")
    assert first.presentation_digest == second.presentation_digest


def test_projection_preserves_pairwise_aggregate_and_no_recalculation(monkeypatch):
    result, projection = _projection((100, 120, 144, 100, 60))
    source = result.series[0]
    metric = projection.metrics[0]
    assert tuple(item.absolute_change for item in metric.transitions) == tuple(item.absolute_change for item in source.series.transitions)
    assert tuple(item.percentage_change for item in metric.transitions) == tuple(item.percentage_change for item in source.series.transitions)
    assert metric.aggregate.cagr_value_percent is source.cagr_result.value_percent
    assert metric.aggregate.volatility_value is source.volatility_result.value
    assert metric.aggregate.break_detected is source.break_result.detected


@pytest.mark.parametrize(
    ("values", "kind", "percentage", "negative"),
    (
        ((100, 125), "percentage_available", Decimal("25.0000"), "not_applicable"),
        ((0, 10), "absolute_only_zero_base", None, "not_applicable"),
        ((10, -1), "absolute_only_sign_change", None, "not_applicable"),
        ((-100, -80), "absolute_only_negative_base", None, "improving"),
        ((-80, -100), "absolute_only_negative_base", None, "worsening"),
    ),
)
def test_transition_semantics_are_preserved(values, kind, percentage, negative):
    _result, projection = _projection(values)
    transition = projection.metrics[0].transitions[0]
    assert transition.transition_kind.value == kind
    assert transition.percentage_change == percentage
    assert transition.negative_base_direction.value == negative
    assert transition.percentage_unavailable_reason == (None if percentage is not None else kind)


def test_ratio_rate_never_becomes_growth_percentage():
    result, projection = _projection((1, 2, 3, 4, 5), metric_code="ratio.current_ratio")
    metric = next(item for item in projection.metrics if item.metric_code == "ratio.current_ratio")
    assert metric.measurement_basis.value == "ratio_rate"
    assert all(item.transition_kind.value == "absolute_only_ratio_rate" for item in metric.transitions)
    assert all(item.percentage_change is None for item in metric.transitions)
    assert metric.aggregate.cagr_value_percent is None
    assert result.series[0].cagr_result.status.value == "disabled"


def test_gap_segments_restatement_and_one_off_unknown_are_visible():
    restatements = (
        TrendRestatementProfile.ORIGINAL,
        TrendRestatementProfile.ORIGINAL,
        TrendRestatementProfile.RESTATED,
        TrendRestatementProfile.RESTATED,
        TrendRestatementProfile.RESTATED,
    )
    _result, projection = _projection(
        (100, 110, 121, 133, 146),
        segments=(0, 0, 1, 2, 2),
        years=(2020, 2021, 2022, 2024, 2025),
        restatements=restatements,
        one_offs=(TrendOneOffStatus.UNKNOWN,) * 5,
    )
    metric = projection.metrics[0]
    assert projection.status is TrendReportSourceStatus.PARTIAL
    assert projection.quality.gap_count == 1 and projection.quality.segment_count == 3
    assert projection.quality.restatement_boundary_count == 1
    assert projection.quality.one_off_unknown_count == 5
    assert {item.segment_ordinal for item in metric.observations} == {0, 1, 2}
    assert metric.segment_boundaries


def test_missing_metric_remains_none_and_cannot_become_zero_or_empty_string():
    _result, projection = _projection()
    missing = projection.metrics[1]
    assert missing.metric_code == "bs.equity"
    assert missing.observations == () and missing.aggregate is None
    assert missing.final_availability.value == "unavailable_missing_input"
    rendered = repr(projection)
    assert "trial_balance" not in rendered and "account_code" not in rendered


@pytest.mark.parametrize(
    ("values", "status"),
    (
        ((100, 110), TrendReportSourceStatus.INSUFFICIENT_FOR_TREND),
        ((100, None), TrendReportSourceStatus.INSUFFICIENT_DATA),
    ),
)
def test_insufficient_statuses_never_claim_real_trend(values, status):
    _result, projection = _projection(values)
    metric = projection.metrics[0]
    assert projection.status is status
    assert metric.aggregate.direction.value == "insufficient_data"
    assert metric.aggregate.volatility_value is None
    assert metric.aggregate.break_detected is None


@pytest.mark.parametrize("status", (TrendComputationStatus.INVALID_INPUT, TrendComputationStatus.INTEGRITY_FAILURE))
def test_invalid_and_integrity_failures_are_safe_ownerless_projections(status):
    projection = project_trend_report_source_v1_2(
        requested=True,
        result=None,
        expected_company_id=UUID(int=1),
        expected_anchor_period_id=UUID(int=2),
        verified_result_digest=None,
        verified_result_reference=None,
        failure_status=status,
        failure_error_codes=(TrendErrorCode.CONTRACT_INTEGRITY_FAILURE.value,),
    )
    assert projection.status.value == status.value
    assert projection.trend_result_reference is None and projection.trend_result_digest is None
    assert projection.quality is None and all(item.observations == () for item in projection.metrics)
    assert "Traceback" not in repr(projection) and "SELECT " not in repr(projection)


def test_scope_digest_version_and_reference_mismatches_fail_closed():
    result = _assemble((100, 110, 121, 133, 146))
    common = dict(
        requested=True,
        result=result,
        expected_company_id=result.company_id,
        expected_anchor_period_id=result.anchor_period_id,
        verified_result_digest=canonical_trend_digest(result),
        verified_result_reference=canonical_trend_reference(result),
    )
    for changed in (
        {"expected_company_id": UUID(int=999)},
        {"expected_anchor_period_id": UUID(int=999)},
        {"verified_result_digest": "a" * 64},
        {"verified_result_reference": "trend:v1:sha256:" + "b" * 64},
        {"trend_model_version": "9.9.9"},
    ):
        with pytest.raises(TrendReportProjectionError):
            project_trend_report_source_v1_2(**(common | changed))


def test_projection_is_immutable_and_digest_is_order_sensitive_to_canonical_content():
    _result, projection = _projection()
    with pytest.raises(FrozenInstanceError):
        projection.status = TrendReportSourceStatus.PARTIAL
    changed = replace(projection, warning_codes=("x",), presentation_digest="")
    assert canonical_trend_report_presentation_digest_v1_2(changed) != projection.presentation_digest


def test_report_1_2_preserves_legacy_content_and_replaces_legacy_trend_claim_warning():
    _result, projection = _projection()
    base = _base_report(cash=True)
    report = integrate_trend_report_v1_2(base, projection)
    assert report.report_schema_version == report.report_model_version == "1.2.0"
    assert set(report.included_section_codes) == set(base.included_section_codes) | {ReportSectionCode.SEC_PERIOD_COMPARISON_ANALYSIS}
    assert len(report.sections) == len(base.sections) + 1
    assert tuple(item.source_engine for item in report.source_inventory[:-1]) == tuple(item.source_engine for item in base.source_inventory)
    assert report.source_inventory[-1].source_engine == "multi_period_trend"
    assert all(item.get("code") != "SINGLE_PERIOD_COMPARISON_ONLY" for item in report.warnings)
    assert len(_trend_blocks(report)) == 7
    assert canonical_report_presentation_digest_v1_2(report) == canonical_report_presentation_digest_v1_2(report)
    assert canonical_report_presentation_digest_v1_2(report) == canonical_report_presentation_digest_v1_2(
        replace(report, report_id="another-run", generated_at="2099-01-01T00:00:00+00:00")
    )


def test_report_generator_returns_byte_equivalent_legacy_when_trend_not_requested():
    bs, income, ratio, benchmark, health, credit, recommendation = _build_upstream()
    args = (ReportType.CFO_EXECUTIVE_REPORT, bs, income, ratio, benchmark, health, credit, recommendation)
    kwargs = dict(company_metadata=_cm(), reporting_period_label_tr="2025")
    before = generate_executive_report_v1_1(*args, **kwargs)
    after = generate_executive_report_v1_2(*args, trend_requested=False, **kwargs)
    assert after == before
    assert after.report_schema_version == "1.0.0"


def test_report_1_1_cash_flow_snapshot_remains_equal_when_trend_not_requested():
    assert generate_executive_report_v1_2 is not generate_executive_report_v1_1
    base = _base_report(cash=True)
    assert base.report_schema_version == "1.1.0"
    assert all(item.source_engine != "multi_period_trend" for item in base.source_inventory)


def test_report_failure_projection_is_typed_and_no_raw_payload_leaks():
    projection = project_trend_report_source_v1_2(
        requested=True, result=None,
        expected_company_id=UUID(int=1), expected_anchor_period_id=UUID(int=2),
        verified_result_digest=None, verified_result_reference=None,
        failure_status=TrendComputationStatus.INTEGRITY_FAILURE,
        failure_error_codes=("contract_integrity_failure",),
    )
    report = integrate_trend_report_v1_2(_base_report(), projection)
    rows = _trend_blocks(report)[1].payload["rows"]
    assert len(rows) == 12 and all(row["availability"] == "unavailable_missing_input" for row in rows)
    text = repr(report)
    assert "raw-token" not in text and "postgresql://" not in text and "Traceback" not in text


def test_golden_scenario_manifest_is_exact_and_versioned():
    path = Path(__file__).parent / "fixtures" / "trend_report_v1_2_golden.json"
    golden = json.loads(path.read_text())
    assert golden["contract_version"] == "1.2.0"
    assert tuple(golden["metric_codes"]) == TREND_REPORT_METRIC_CODES_V1_2
    assert tuple(golden["scenarios"]) == (
        "complete_five_period_annual", "partial_gap_segmented", "two_observation",
        "sign_change_loss", "volatility_break", "invalid_integrity",
    )
    vectors = {
        "complete_five_period_annual": _projection((100, 110, 121, 133, 146))[1],
        "partial_gap_segmented": _projection(
            (100, 110, 121, 133, 146),
            segments=(0, 0, 1, 1, 1), years=(2020, 2021, 2023, 2024, 2025),
        )[1],
        "two_observation": _projection((100, 110))[1],
        "sign_change_loss": _projection((-100, -80, 10, 20, 30))[1],
        "volatility_break": _projection((100, 101, 1000, 1001, 1002))[1],
    }
    assert {
        key: projection.presentation_digest for key, projection in vectors.items()
    } == {
        key: golden["scenarios"][key]["presentation_digest"] for key in vectors
    }


def test_no_forbidden_downstream_engine_import_or_calculation_surface():
    package = Path(__file__).parents[1] / "app" / "engines" / "executive_reports"
    source = (package / "trend_projection.py").read_text() + (package / "trend_integration.py").read_text()
    for forbidden in (
        "calculate_cagr", "calculate_volatility", "calculate_trend_break",
        "analyze_financial_ratios", "calculate_health_score", "calculate_credit_score",
        "generate_recommendations", "sqlalchemy", "fastapi",
    ):
        assert forbidden not in source.lower()
