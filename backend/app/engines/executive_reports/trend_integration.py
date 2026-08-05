"""Executive Report 1.2.0 integration for canonical Trend results."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Final

from app.engines.common.report_types import (
    ExecutiveReportResult,
    ReportBlockType,
    ReportContentBlock,
    ReportSection,
    ReportSectionCode,
    SectionSourceMappingEntry,
    SourceConfidenceEntry,
    SourceCoverageEntry,
    SourceInventoryEntry,
    UpstreamVersionEntry,
)
from app.engines.common.report_registry import REPORT_SECTION_REGISTRY
from app.engines.multi_period_trend import MultiPeriodTrendResult, TrendComputationStatus

from .cash_flow_integration import generate_executive_report_v1_1
from .trend_projection import (
    ExecutiveReportTrendProjectionV1_2,
    TREND_REPORT_METRIC_CODES_V1_2,
    TREND_SOURCE_MODEL_VERSION_V1,
    TREND_SOURCE_SCHEMA_VERSION_V1,
    TrendReportSourceStatus,
    canonical_trend_report_presentation_digest_v1_2,
    project_trend_report_source_v1_2,
)


REPORT_SCHEMA_VERSION_V1_2_TREND: Final = "1.2.0"
REPORT_MODEL_VERSION_V1_2_TREND: Final = "1.2.0"
REPORT_REGISTRY_V1_2_TREND: Final = tuple(ReportSectionCode)
REPORT_SOURCE_ENGINE_INVENTORY_V1_2_TREND: Final = (
    "balance_sheet",
    "income_statement",
    "financial_ratios",
    "benchmarks",
    "health_score",
    "credit_score",
    "recommendation",
    "cash_flow",
    "multi_period_trend",
)

_LEGACY_WARNING_CODE = "SINGLE_PERIOD_COMPARISON_ONLY"
_TREND_WARNING_ORDER = (
    "TREND_PARTIAL_RESULT",
    "TREND_INSUFFICIENT_FOR_TREND",
    "TREND_INSUFFICIENT_DATA",
    "TREND_GAP_SEGMENTED",
    "TREND_RESTATEMENT_DISCLOSED",
    "TREND_ONE_OFF_UNKNOWN",
    "TREND_ESTIMATED_EVIDENCE",
    "TREND_UNAVAILABLE_METRIC",
    "TREND_SOURCE_FAILURE",
    "TREND_SOURCE_UNAVAILABLE",
)


def _warning_codes(projection: ExecutiveReportTrendProjectionV1_2) -> tuple[str, ...]:
    present = set(projection.warning_codes)
    if projection.status is TrendReportSourceStatus.PARTIAL:
        present.add("TREND_PARTIAL_RESULT")
    if projection.status is TrendReportSourceStatus.INSUFFICIENT_FOR_TREND:
        present.add("TREND_INSUFFICIENT_FOR_TREND")
    if projection.status is TrendReportSourceStatus.INSUFFICIENT_DATA:
        present.add("TREND_INSUFFICIENT_DATA")
    if projection.status in {TrendReportSourceStatus.INVALID_INPUT, TrendReportSourceStatus.INTEGRITY_FAILURE}:
        present.add("TREND_SOURCE_FAILURE")
    if projection.status is TrendReportSourceStatus.UNAVAILABLE:
        present.add("TREND_SOURCE_UNAVAILABLE")
    if projection.quality is not None:
        if projection.quality.gap_count:
            present.add("TREND_GAP_SEGMENTED")
        if projection.quality.restatement_boundary_count:
            present.add("TREND_RESTATEMENT_DISCLOSED")
        if projection.quality.restatement_disclosure.value != "original_only":
            present.add("TREND_RESTATEMENT_DISCLOSED")
        if projection.quality.one_off_disclosure.value == "unknown_present":
            present.add("TREND_ONE_OFF_UNKNOWN")
        if projection.quality.estimated_count:
            present.add("TREND_ESTIMATED_EVIDENCE")
        if projection.quality.unavailable_metric_count:
            present.add("TREND_UNAVAILABLE_METRIC")
    ordered = tuple(code for code in _TREND_WARNING_ORDER if code in present)
    extras = tuple(sorted(present - set(_TREND_WARNING_ORDER)))
    return ordered + extras


def _rows(projection: ExecutiveReportTrendProjectionV1_2) -> tuple[dict[str, Any], ...]:
    result = []
    for metric in projection.metrics:
        aggregate = metric.aggregate
        result.append({
            "metric_code": metric.metric_code,
            "label_tr": metric.label_tr,
            "unit": metric.unit,
            "status": None if metric.status is None else metric.status.value,
            "availability": metric.final_availability.value,
            "measurement_basis": None if metric.measurement_basis is None else metric.measurement_basis.value,
            "period_family": None if metric.period_family is None else metric.period_family.value,
            "direction": None if aggregate is None else aggregate.direction.value,
            "cagr_value_percent": None if aggregate is None else aggregate.cagr_value_percent,
            "cagr_status": None if aggregate is None or aggregate.cagr_status is None else aggregate.cagr_status.value,
            "volatility_value": None if aggregate is None else aggregate.volatility_value,
            "volatility_category": None if aggregate is None or aggregate.volatility_category is None else aggregate.volatility_category.value,
            "break_detected": None if aggregate is None else aggregate.break_detected,
            "break_unavailable_reason": None if aggregate is None else aggregate.break_unavailable_reason,
            "breakpoint_period_id": None if aggregate is None or aggregate.breakpoint_period_id is None else str(aggregate.breakpoint_period_id),
            "usable_observation_count": metric.usable_observation_count,
            "usable_transition_count": metric.usable_transition_count,
        })
    return tuple(result)


def _projection_blocks(projection: ExecutiveReportTrendProjectionV1_2) -> tuple[ReportContentBlock, ...]:
    status_row = {
        "trend_status": projection.status.value,
        "company_id": None if projection.company_id is None else str(projection.company_id),
        "anchor_period_id": None if projection.anchor_period_id is None else str(projection.anchor_period_id),
        "trend_contract_version": projection.trend_contract_version,
        "metric_registry_version": projection.metric_registry_version,
        "metric_registry_digest": projection.metric_registry_digest,
        "policy_version": projection.policy_version,
        "nominal_disclosure": projection.nominal_analysis_disclosure,
        "nominal_values": projection.nominal_values,
        "inflation_adjusted": projection.inflation_adjusted,
        "currency": projection.currency,
        "comparability_status": None if projection.comparability_status is None else projection.comparability_status.value,
        "trend_result_reference": projection.trend_result_reference,
        "source_set_reference": projection.source_set_reference,
        "lineage_reference": projection.lineage_reference,
        "presentation_digest": projection.presentation_digest,
    }
    metric_rows = _rows(projection)
    observation_rows = tuple(
        {
            "metric_code": metric.metric_code,
            "ordinal": item.ordinal,
            "segment_ordinal": item.segment_ordinal,
            "period_id": str(item.period_id),
            "period_start_date": item.period_start_date,
            "period_end_date": item.period_end_date,
            "value": item.value,
            "evidence": item.evidence.value,
            "restatement_profile": item.restatement_profile,
            "one_off_status": item.one_off_status,
        }
        for metric in projection.metrics
        for item in metric.observations
    )
    transition_rows = tuple(
        {
            "metric_code": metric.metric_code,
            "from_period_id": str(item.from_period_id),
            "to_period_id": str(item.to_period_id),
            "absolute_change": item.absolute_change,
            "percentage_change": item.percentage_change,
            "percentage_unavailable_reason": item.percentage_unavailable_reason,
            "transition_kind": item.transition_kind.value,
            "direction": item.direction.value,
            "negative_base_direction": item.negative_base_direction.value,
            "evidence": item.evidence.value,
        }
        for metric in projection.metrics
        for item in metric.transitions
    )
    quality_row = None if projection.quality is None else asdict(projection.quality)
    boundary_rows = tuple(
        {
            "metric_code": metric.metric_code,
            "after_period_id": str(after),
            "before_period_id": str(before),
            "kind": kind,
        }
        for metric in projection.metrics
        for after, before, kind in metric.segment_boundaries
    )
    issue_items = tuple({"kind": "warning", "code": code} for code in _warning_codes(projection)) + tuple(
        {"kind": "error", "code": code} for code in projection.error_codes
    )
    return (
        ReportContentBlock(ReportBlockType.TABLE, {"columns": list(status_row), "rows": (status_row,)}, "multi_period_trend.status/disclosure", "multi_period_trend.status"),
        ReportContentBlock(ReportBlockType.TABLE, {"columns": list(metric_rows[0]) if metric_rows else [], "rows": metric_rows}, "multi_period_trend.metrics", "multi_period_trend.metrics"),
        ReportContentBlock(ReportBlockType.TABLE, {"columns": list(observation_rows[0]) if observation_rows else [], "rows": observation_rows}, "multi_period_trend.observations", "multi_period_trend.evidence"),
        ReportContentBlock(ReportBlockType.TABLE, {"columns": list(transition_rows[0]) if transition_rows else [], "rows": transition_rows}, "multi_period_trend.transitions", "multi_period_trend.transitions"),
        ReportContentBlock(ReportBlockType.TABLE, {"columns": [] if quality_row is None else list(quality_row), "rows": () if quality_row is None else (quality_row,)}, "multi_period_trend.data_quality", "multi_period_trend.completeness"),
        ReportContentBlock(ReportBlockType.TABLE, {"columns": list(boundary_rows[0]) if boundary_rows else [], "rows": boundary_rows}, "multi_period_trend.segment_boundaries", "multi_period_trend.lineage"),
        ReportContentBlock(ReportBlockType.BULLET_LIST, {"items": issue_items}, "multi_period_trend.warnings/errors", "multi_period_trend.issues"),
    )


def integrate_trend_report_v1_2(
    base_report: ExecutiveReportResult,
    projection: ExecutiveReportTrendProjectionV1_2,
) -> ExecutiveReportResult:
    """Augment an immutable 1.0/1.1 report without recomputation."""

    if type(base_report) is not ExecutiveReportResult or type(projection) is not ExecutiveReportTrendProjectionV1_2:
        raise TypeError("Trend report integration requires exact canonical contracts")
    if base_report.report_schema_version not in {"1.0.0", "1.1.0"} or base_report.report_model_version not in {"1.0.0", "1.1.0"}:
        raise ValueError("cross-version report cast/reuse is forbidden")
    if any(item.source_engine == "multi_period_trend" for item in base_report.source_inventory):
        raise ValueError("Trend source is already present in base report")

    target = ReportSectionCode.SEC_PERIOD_COMPARISON_ANALYSIS
    used = target in base_report.included_section_codes
    warning_codes = _warning_codes(projection)
    sections: list[ReportSection] = []
    target_found = False
    for section in base_report.sections:
        if section.section_code is target:
            target_found = True
            legacy_free_warnings = tuple(
                item for item in section.warnings if item.get("code") != _LEGACY_WARNING_CODE
            )
            section = replace(
                section,
                content_blocks=section.content_blocks + _projection_blocks(projection),
                source_engines=section.source_engines + ("multi_period_trend",),
                explainability_note_tr=(
                    section.explainability_note_tr
                    + " Multi-period Trend alanları canonical sonuçtan yeniden hesaplama yapılmadan yansıtılmıştır."
                ),
                warnings=legacy_free_warnings + tuple({"code": code} for code in warning_codes),
            )
        sections.append(section)
    if not target_found:
        definition = REPORT_SECTION_REGISTRY[target]
        sections.append(ReportSection(
            section_code=target,
            title_tr=definition.display_name_tr,
            build_phase=definition.build_phase,
            is_mandatory_for_report_type=False,
            content_blocks=_projection_blocks(projection),
            source_engines=definition.source_engine_codes + ("multi_period_trend",),
            consumed_section_codes=(),
            data_domains=definition.data_domains,
            explainability_note_tr="Multi-period Trend alanları canonical sonuçtan yeniden hesaplama yapılmadan yansıtılmıştır.",
            disclaimer_scope="general",
            is_reformatted_source_content=True,
            is_independent_strategic_analysis=False,
            warnings=tuple({"code": code} for code in warning_codes),
        ))
        order = {code: index for index, code in enumerate(ReportSectionCode)}
        sections.sort(key=lambda item: order[item.section_code])
    mapping = tuple(
        replace(item, source_engines=item.source_engines + ("multi_period_trend",))
        if item.section_code is target else item
        for item in base_report.section_source_mapping
    )
    if not any(item.section_code is target for item in mapping):
        definition = REPORT_SECTION_REGISTRY[target]
        mapping = tuple(sorted(
            mapping + (SectionSourceMappingEntry(target, definition.source_engine_codes + ("multi_period_trend",)),),
            key=lambda item: tuple(ReportSectionCode).index(item.section_code),
        ))
    base_warnings = tuple(item for item in base_report.warnings if item.get("code") != _LEGACY_WARNING_CODE)
    used = True
    used_sections = (target,)
    quality = projection.quality
    coverage_available = quality is not None
    coverage_value = None if quality is None else quality.observation_completeness
    source_status = "used" if used and projection.trend_result_digest is not None else "unavailable"
    upstream = UpstreamVersionEntry(
        "multi_period_trend", projection.trend_schema_version, projection.trend_model_version,
    )
    complete = projection.status is TrendReportSourceStatus.COMPLETE
    return replace(
        base_report,
        sections=tuple(sections),
        included_section_codes=tuple(item.section_code for item in sections),
        omitted_section_codes=tuple(code for code in base_report.omitted_section_codes if code is not target),
        warnings=base_warnings + tuple({"code": code} for code in warning_codes),
        source_inventory=base_report.source_inventory + (SourceInventoryEntry("multi_period_trend", source_status, used_sections),),
        source_confidence_inventory=base_report.source_confidence_inventory + (SourceConfidenceEntry(
            "multi_period_trend", False, None, None, "PER_OBSERVATION_EVIDENCE_NOT_ENGINE_LEVEL",
            "Trend güvenilirliği observation/transition/aggregate evidence olarak sunulur.", used_sections,
        ),),
        source_coverage_inventory=base_report.source_coverage_inventory + (SourceCoverageEntry(
            "multi_period_trend", coverage_available, coverage_value,
            None if coverage_available else "TREND_RESULT_UNAVAILABLE",
            None if coverage_available else "Trend completeness bilgisi kullanılamıyor.", used_sections,
        ),),
        missing_confidence_sources=base_report.missing_confidence_sources + ("multi_period_trend",),
        missing_coverage_sources=(
            base_report.missing_coverage_sources if coverage_available
            else base_report.missing_coverage_sources + ("multi_period_trend",)
        ),
        section_source_mapping=mapping,
        provisional=base_report.provisional or not complete,
        report_schema_version=REPORT_SCHEMA_VERSION_V1_2_TREND,
        report_model_version=REPORT_MODEL_VERSION_V1_2_TREND,
        upstream_version_inventory=base_report.upstream_version_inventory + (upstream,),
    )


def generate_executive_report_v1_2(
    *args: Any,
    trend_requested: bool = False,
    trend_result: MultiPeriodTrendResult | None = None,
    expected_company_id=None,
    expected_anchor_period_id=None,
    verified_trend_result_digest: str | None = None,
    verified_trend_result_reference: str | None = None,
    trend_failure_status: TrendComputationStatus | None = None,
    trend_failure_error_codes: tuple[str, ...] = (),
    **kwargs: Any,
) -> ExecutiveReportResult:
    base = generate_executive_report_v1_1(*args, **kwargs)
    if not trend_requested:
        if any(item is not None for item in (trend_result, expected_company_id, expected_anchor_period_id, verified_trend_result_digest, verified_trend_result_reference, trend_failure_status)) or trend_failure_error_codes:
            raise ValueError("unrequested Trend state cannot enter the report")
        return base
    projection = project_trend_report_source_v1_2(
        requested=True,
        result=trend_result,
        expected_company_id=expected_company_id,
        expected_anchor_period_id=expected_anchor_period_id,
        verified_result_digest=verified_trend_result_digest,
        verified_result_reference=verified_trend_result_reference,
        failure_status=trend_failure_status,
        failure_error_codes=trend_failure_error_codes,
    )
    return integrate_trend_report_v1_2(base, projection)


def canonical_report_presentation_digest_v1_2(report: ExecutiveReportResult) -> str:
    if type(report) is not ExecutiveReportResult or (
        report.report_schema_version,
        report.report_model_version,
    ) != (REPORT_SCHEMA_VERSION_V1_2_TREND, REPORT_MODEL_VERSION_V1_2_TREND):
        raise ValueError("report presentation digest requires exact Report 1.2.0")
    # Execution identity/audit time are not presentation semantics and must not
    # make an otherwise identical Report 1.2.0 payload non-reusable.
    projection = replace(report, report_id=None, generated_at=None)
    return canonical_trend_report_presentation_digest_v1_2(projection)


if len(REPORT_REGISTRY_V1_2_TREND) != len(set(REPORT_REGISTRY_V1_2_TREND)) or len(TREND_REPORT_METRIC_CODES_V1_2) != 12:
    raise RuntimeError("Report 1.2.0 registry/metric manifest is invalid")
