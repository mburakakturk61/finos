"""Pure, non-persisting final result assembly for Milestone 4.6F."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_EVEN

from .analyzer import analyze_trend_aggregates
from .completeness import build_result_completeness
from .contracts import (
    MultiPeriodTrendResult,
    TrendCompleteness,
    TrendDataQuality,
    TrendEvidenceSummary,
    TrendLineageReference,
    TrendMetricQuality,
    TrendNominalDisclosure,
    TrendSourceReference,
    TrendUnavailableMetric,
    TrendWarning,
)
from .errors import TrendResultAssemblyError
from .policy import TREND_ACCOUNTING_POLICY_V1, TrendAccountingPolicy, TrendComparabilityProfile
from .quality import (
    classify_metric_quality,
    one_off_disclosure,
    quality_flags,
    restatement_disclosure,
)
from .registry import TREND_METRIC_REGISTRY_V1, TrendMetricRegistry
from .resolution_contracts import ResolvedTrendSeries
from .types import (
    TrendComparabilityStatus,
    TrendComputationStatus,
    TrendContractVersion,
    TrendEvidenceLevel,
    TrendFinalMetricAvailability,
    TrendNominalAnalysisProfile,
    TrendOneOffStatus,
    TrendPolicyVersion,
    TrendRestatementProfile,
    TrendSegmentBoundaryKind,
    TrendWarningCode,
    weakest_evidence,
)


def _fail(status: TrendComputationStatus) -> None:
    raise TrendResultAssemblyError(status)


def _canonical_expected_codes(
    expected_metric_codes: tuple[str, ...] | None,
    registry: TrendMetricRegistry,
) -> tuple[str, ...]:
    codes = (
        tuple(item.metric_code for item in registry.definitions)
        if expected_metric_codes is None
        else expected_metric_codes
    )
    if type(codes) is not tuple or not codes or any(type(item) is not str for item in codes):
        _fail(TrendComputationStatus.INVALID_INPUT)
    if len(set(codes)) != len(codes):
        _fail(TrendComputationStatus.INVALID_INPUT)
    registry_order = {item.metric_code: item.display_order_index for item in registry.definitions}
    if any(item not in registry_order for item in codes):
        _fail(TrendComputationStatus.INVALID_INPUT)
    return tuple(sorted(codes, key=registry_order.__getitem__))


def _validate_scope(
    resolved: tuple[ResolvedTrendSeries, ...],
    profile: TrendComparabilityProfile,
) -> tuple[tuple, tuple]:
    first = resolved[0]
    period_ids = tuple(item.observation.period_id for item in first.observations)
    scopes = {
        (
            item.tenant_id, item.company_id, item.anchor_period_id, item.period_family,
            item.currency, item.monetary_unit_multiplier,
            tuple(obs.observation.period_id for obs in item.observations),
        )
        for item in resolved
    }
    if len(scopes) != 1:
        _fail(TrendComputationStatus.INTEGRITY_FAILURE)
    if (
        profile.tenant_id != first.tenant_id
        or profile.company_id != first.company_id
        or profile.currency != first.currency
        or profile.period_family is not first.period_family
    ):
        _fail(TrendComputationStatus.INTEGRITY_FAILURE)
    return period_ids, tuple(item.observation for item in first.observations)


def _source_and_lineage_references(metrics, resolved_by_code):
    sources: dict = {}
    lineage: dict = {}
    for metric in metrics:
        resolved = resolved_by_code[metric.metric_code]
        proof_by_segment = {
            item.segment_ordinal: item.comparability_proof_digest
            for item in resolved.segments
        }
        for observation in metric.series.observations:
            candidate = TrendSourceReference(
                company_id=observation.company_id,
                period_id=observation.period_id,
                source_result_id=observation.source_result_id,
                source_engine_type=observation.source_engine_type,
                source_schema_version=observation.source_schema_version,
                source_model_version=observation.source_model_version,
                canonical_source_digest=observation.canonical_source_digest,
                evidence=observation.evidence,
            )
            existing = sources.get(observation.source_result_id)
            if existing is not None:
                if (
                    existing.company_id, existing.period_id, existing.source_engine_type,
                    existing.source_schema_version, existing.source_model_version,
                    existing.canonical_source_digest,
                ) != (
                    candidate.company_id, candidate.period_id, candidate.source_engine_type,
                    candidate.source_schema_version, candidate.source_model_version,
                    candidate.canonical_source_digest,
                ):
                    _fail(TrendComputationStatus.INTEGRITY_FAILURE)
                candidate = replace(existing, evidence=weakest_evidence(existing.evidence, candidate.evidence))
            sources[observation.source_result_id] = candidate
            key = (observation.period_id, observation.source_result_id)
            reference = TrendLineageReference(
                ordinal=observation.ordinal,
                period_id=observation.period_id,
                source_result_id=observation.source_result_id,
                canonical_source_digest=observation.canonical_source_digest,
                comparability_proof_digest=proof_by_segment[observation.segment_ordinal],
                lineage_schema_version="1.0.0",
            )
            existing_lineage = lineage.get(key)
            if existing_lineage is not None and existing_lineage != reference:
                _fail(TrendComputationStatus.INTEGRITY_FAILURE)
            lineage[key] = reference
    return tuple(sources.values()), tuple(lineage.values())


def _overall_status(metrics, metric_quality, missing_metric_codes, has_estimated, degraded_boundaries):
    available_counts = tuple(item.series.completeness.available_observation_count for item in metrics)
    if not any(count >= 2 for count in available_counts):
        return TrendComputationStatus.INSUFFICIENT_DATA
    if not any(count >= 3 for count in available_counts):
        return TrendComputationStatus.INSUFFICIENT_FOR_TREND
    fully_available = all(
        item.availability is TrendFinalMetricAvailability.AVAILABLE
        for item in metric_quality
    )
    if (
        fully_available
        and not missing_metric_codes
        and not has_estimated
        and not degraded_boundaries
        and all(item.status is TrendComputationStatus.COMPLETE for item in metrics)
    ):
        return TrendComputationStatus.COMPLETE
    return TrendComputationStatus.PARTIAL


def assemble_multi_period_trend_result(
    resolved_series: tuple[ResolvedTrendSeries, ...],
    profile: TrendComparabilityProfile,
    *,
    expected_metric_codes: tuple[str, ...] | None = None,
    unavailable_metrics: tuple[TrendUnavailableMetric, ...] = (),
    registry: TrendMetricRegistry = TREND_METRIC_REGISTRY_V1,
    policy: TrendAccountingPolicy = TREND_ACCOUNTING_POLICY_V1,
) -> MultiPeriodTrendResult:
    """Assemble the immutable 4.6F result without persistence or integration I/O."""

    if (
        type(resolved_series) is not tuple
        or not resolved_series
        or any(type(item) is not ResolvedTrendSeries for item in resolved_series)
        or type(profile) is not TrendComparabilityProfile
        or type(registry) is not TrendMetricRegistry
        or type(policy) is not TrendAccountingPolicy
        or type(unavailable_metrics) is not tuple
        or any(type(item) is not TrendUnavailableMetric for item in unavailable_metrics)
    ):
        _fail(TrendComputationStatus.INVALID_INPUT)
    expected_codes = _canonical_expected_codes(expected_metric_codes, registry)
    resolved_by_code = {item.metric_code: item for item in resolved_series}
    if len(resolved_by_code) != len(resolved_series):
        _fail(TrendComputationStatus.INTEGRITY_FAILURE)
    unavailable_by_code = {item.metric_code: item for item in unavailable_metrics}
    if len(unavailable_by_code) != len(unavailable_metrics) or set(unavailable_by_code).intersection(resolved_by_code):
        _fail(TrendComputationStatus.INTEGRITY_FAILURE)
    if any(code not in expected_codes for code in (*resolved_by_code, *unavailable_by_code)):
        _fail(TrendComputationStatus.INVALID_INPUT)
    period_ids, _ = _validate_scope(resolved_series, profile)
    try:
        ordered_resolved = tuple(
            resolved_by_code[code] for code in expected_codes if code in resolved_by_code
        )
        metrics = tuple(analyze_trend_aggregates(item, registry, policy) for item in ordered_resolved)
        metric_quality = tuple(
            classify_metric_quality(item, registry.get(item.metric_code)) for item in metrics
        )
    except TrendResultAssemblyError:
        raise
    except Exception:
        _fail(TrendComputationStatus.INTEGRITY_FAILURE)

    undisclosed_metric_codes = tuple(
        code for code in expected_codes
        if code not in resolved_by_code and code not in unavailable_by_code
    )
    unavailable_missing_codes = tuple(
        code for code, item in unavailable_by_code.items()
        if item.availability is TrendFinalMetricAvailability.UNAVAILABLE_MISSING_INPUT
    )
    missing_metric_codes = tuple(
        code for code in expected_codes
        if code in set((*undisclosed_metric_codes, *unavailable_missing_codes))
    )
    missing_quality = tuple(
        TrendMetricQuality(
            metric_code=code,
            availability=(
                unavailable_by_code[code].availability
                if code in unavailable_by_code
                else TrendFinalMetricAvailability.UNAVAILABLE_MISSING_INPUT
            ),
            evidence=TrendEvidenceLevel.UNAVAILABLE,
            usable_observation_count=0,
            segment_ordinals=(),
            missing_period_ids=(
                unavailable_by_code[code].missing_period_ids
                if code in unavailable_by_code
                else period_ids
            ),
            warning_codes=(
                unavailable_by_code[code].warning_codes
                if code in unavailable_by_code
                else ()
            ),
        )
        for code in expected_codes if code not in resolved_by_code
    )
    all_metric_quality = (*metric_quality, *missing_quality)
    unique_gaps = {
        (gap.after_period_id, gap.before_period_id)
        for item in metrics for gap in item.series.gaps
    }
    unique_restatements = {
        (boundary.after_period_id, boundary.before_period_id)
        for item in metrics for boundary in item.series.segment_boundaries
        if boundary.kind is TrendSegmentBoundaryKind.RESTATEMENT_CHANGE
    }
    total_expected = sum(item.series.completeness.expected_observation_count for item in metrics)
    total_available = sum(item.series.completeness.available_observation_count for item in metrics)
    total_unavailable = total_expected - total_available
    ratio = (
        Decimal(0)
        if total_expected == 0
        else (Decimal(total_available) / Decimal(total_expected)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_EVEN
        )
    )
    evidence_counts = {
        level: sum(getattr(item.series.evidence_summary, f"{level.value}_count") for item in metrics)
        for level in TrendEvidenceLevel
    }
    populated_evidence = tuple(level for level in TrendEvidenceLevel if evidence_counts[level])
    if not populated_evidence:
        _fail(TrendComputationStatus.INTEGRITY_FAILURE)
    old_completeness = TrendCompleteness(
        expected_observation_count=total_expected,
        available_observation_count=total_available,
        unavailable_observation_count=total_unavailable,
        available_ratio=ratio,
    )
    evidence_summary = TrendEvidenceSummary(
        exact_count=evidence_counts[TrendEvidenceLevel.EXACT],
        derived_count=evidence_counts[TrendEvidenceLevel.DERIVED],
        estimated_count=evidence_counts[TrendEvidenceLevel.ESTIMATED],
        unavailable_count=evidence_counts[TrendEvidenceLevel.UNAVAILABLE],
        weakest_evidence=weakest_evidence(*populated_evidence),
    )
    result_completeness = build_result_completeness(
        metrics,
        expected_period_count=len(period_ids),
        expected_metric_count=len(expected_codes),
        gap_count=len(unique_gaps),
        restatement_boundary_count=len(unique_restatements),
    )
    one_off_unknown_count = sum(
        observation.one_off_status is TrendOneOffStatus.UNKNOWN
        for item in metrics for observation in item.series.observations
    )
    missing_period_ids = tuple(sorted({
        observation.period_id
        for item in metrics for observation in item.series.observations
        if observation.value is None
    }.union(
        period_id for item in unavailable_metrics for period_id in item.missing_period_ids
    ), key=str))
    warnings = {
        (warning.code, warning.safe_reference): warning
        for item in metrics for warning in item.warnings
    }
    nominal_warning = TrendWarning(TrendWarningCode.NOMINAL_NOT_INFLATION_ADJUSTED)
    warnings[(nominal_warning.code, nominal_warning.safe_reference)] = nominal_warning
    restatement_state = restatement_disclosure(metrics)
    one_off_state = one_off_disclosure(metrics)
    flags = quality_flags(metrics, missing_metric_codes=missing_metric_codes)
    data_quality = TrendDataQuality(
        comparability_status=(
            TrendComparabilityStatus.SEGMENTED
            if unique_gaps or unique_restatements
            else TrendComparabilityStatus.COMPARABLE
        ),
        profile=profile,
        completeness=old_completeness,
        evidence_summary=evidence_summary,
        gap_count=len(unique_gaps),
        restatement_boundary_count=len(unique_restatements),
        one_off_unknown_count=one_off_unknown_count,
        result_completeness=result_completeness,
        metric_quality=all_metric_quality,
        missing_period_ids=missing_period_ids,
        missing_metric_codes=missing_metric_codes,
        incompatible_source_count=sum(
            item.availability is TrendFinalMetricAvailability.UNAVAILABLE_INCOMPATIBLE_SOURCE
            for item in unavailable_metrics
        ),
        segment_count=len({
            observation.segment_ordinal
            for item in metrics for observation in item.series.observations
        }),
        restatement_disclosure=restatement_state,
        one_off_disclosure=one_off_state,
        quality_flags=flags,
        warnings=tuple(warnings.values()),
        errors=(),
    )
    status = _overall_status(
        metrics,
        all_metric_quality,
        missing_metric_codes,
        result_completeness.estimated_count > 0,
        bool(unique_gaps or unique_restatements),
    )
    sources, lineage = _source_and_lineage_references(metrics, resolved_by_code)
    try:
        return MultiPeriodTrendResult(
            company_id=resolved_series[0].company_id,
            anchor_period_id=resolved_series[0].anchor_period_id,
            status=status,
            nominal_analysis_disclosure=TrendNominalDisclosure(
                profile=TrendNominalAnalysisProfile.NOMINAL_ONLY_NO_INFLATION_ADJUSTMENT,
                currency=resolved_series[0].currency,
                nominal_values=True,
                inflation_adjusted=False,
            ),
            series=metrics,
            data_quality=data_quality,
            source_references=sources,
            lineage_references=lineage,
            policy_version=TrendPolicyVersion.V1,
            contract_version=TrendContractVersion.V1,
            warnings=tuple(warnings.values()),
            errors=(),
        )
    except TrendResultAssemblyError:
        raise
    except Exception:
        _fail(TrendComputationStatus.INTEGRITY_FAILURE)
