"""Pure Milestone 4.6C explicit N-period series resolution."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from hmac import compare_digest

from .canonical import canonical_trend_digest, canonical_trend_reference
from .contracts import TrendGap, TrendObservation, TrendSegmentBoundary, TrendWarning
from .evidence_mapping import (
    TrendRatioComputationStatus,
    TrendRatioReliability,
    TrendSourceMetricProjection,
    TrendSourceMetricStatus,
    TrendSourceMode,
    map_source_metric_evidence,
)
from .registry import TREND_METRIC_REGISTRY_V1, TrendMetricDefinition, TrendMetricRegistry
from .resolution_contracts import (
    TREND_COMPARABILITY_PROFILE_VERSION_V1,
    TREND_SERIES_RESOLUTION_CONTRACT_VERSION,
    ResolvedTrendObservation,
    ResolvedTrendSegment,
    ResolvedTrendSeries,
    TrendResolvedPeriod,
    TrendResolvedPeriodStatus,
    TrendResolvedPeriodType,
    TrendResolvedSourceCandidate,
    TrendResolvedSourceStatus,
    TrendSeriesRepositoryError,
    TrendSeriesRepositoryPort,
    TrendSeriesResolutionErrorCode,
    TrendSeriesResolutionRequest,
    TrendSeriesResolutionResult,
    TrendSeriesResolutionSnapshot,
    TrendSeriesResolutionStatus,
    TrendSourceSelectionRole,
    canonical_candidate_set_digest,
)
from .types import (
    TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1,
    TrendCoverageKind,
    TrendEvidenceLevel,
    TrendOneOffStatus,
    TrendPeriodFamily,
    TrendPolicyVersion,
    TrendRestatementProfile,
    TrendSegmentBoundaryKind,
    TrendSourceEngineType,
    TrendWarningCode,
    weakest_evidence,
)


_ROLE_BY_ENGINE = {
    TrendSourceEngineType.BALANCE_SHEET: TrendSourceSelectionRole.BALANCE_SHEET,
    TrendSourceEngineType.INCOME_STATEMENT: TrendSourceSelectionRole.INCOME_STATEMENT,
    TrendSourceEngineType.CASH_FLOW: TrendSourceSelectionRole.CASH_FLOW,
    TrendSourceEngineType.FINANCIAL_RATIOS: TrendSourceSelectionRole.FINANCIAL_RATIOS,
}


def _failed(code: TrendSeriesResolutionErrorCode) -> TrendSeriesResolutionResult:
    return TrendSeriesResolutionResult(TrendSeriesResolutionStatus.FAILED, None, code)


def _period_family_error(period: TrendResolvedPeriod, family: TrendPeriodFamily) -> bool:
    if family is TrendPeriodFamily.ANNUAL:
        return not (
            period.period_type is TrendResolvedPeriodType.YEAR_END
            and period.coverage_kind is TrendCoverageKind.CUMULATIVE
            and period.months_covered == 12
            and (period.end_date - period.start_date).days + 1 in {365, 366}
        )
    if family is TrendPeriodFamily.MONTHLY_DISCRETE:
        return not (
            period.period_type is TrendResolvedPeriodType.MONTHLY
            and period.coverage_kind is TrendCoverageKind.DISCRETE
            and period.months_covered == 1
            and 1 <= period.fiscal_ordinal <= 12
        )
    if family is TrendPeriodFamily.QUARTERLY_DISCRETE:
        return not (
            period.period_type is TrendResolvedPeriodType.QUARTER
            and period.coverage_kind is TrendCoverageKind.DISCRETE
            and period.months_covered == 3
            and 1 <= period.fiscal_ordinal <= 4
        )
    if family is TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY:
        return not (
            period.period_type is TrendResolvedPeriodType.QUARTER
            and period.coverage_kind is TrendCoverageKind.CUMULATIVE
            and period.months_covered in {3, 6, 9}
            and 1 <= period.fiscal_ordinal <= 3
            and period.months_covered == period.fiscal_ordinal * 3
        )
    if family is TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY:
        return not (
            period.period_type is TrendResolvedPeriodType.TEMPORARY_TAX
            and period.coverage_kind is TrendCoverageKind.CUMULATIVE
            and period.months_covered in {3, 6, 9, 12}
            and 1 <= period.fiscal_ordinal <= 4
            and period.months_covered == period.fiscal_ordinal * 3
        )
    return not (
        family is TrendPeriodFamily.CUSTOM_DISCRETE
        and period.period_type is TrendResolvedPeriodType.CUSTOM
        and period.coverage_kind is TrendCoverageKind.DISCRETE
    )


def _cadence_position(period: TrendResolvedPeriod, family: TrendPeriodFamily) -> int:
    if family is TrendPeriodFamily.ANNUAL:
        return period.year
    if family is TrendPeriodFamily.MONTHLY_DISCRETE:
        return period.year * 12 + period.fiscal_ordinal
    if family is TrendPeriodFamily.QUARTERLY_DISCRETE:
        return period.year * 4 + period.fiscal_ordinal
    if family in {
        TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY,
        TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY,
    }:
        return period.year
    return period.start_date.toordinal()


def _validate_periods(
    request: TrendSeriesResolutionRequest,
    periods: tuple[TrendResolvedPeriod, ...],
) -> tuple[tuple[TrendResolvedPeriod, ...] | None, TrendSeriesResolutionErrorCode | None]:
    if len(periods) != len(request.explicit_period_ids):
        return None, TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND
    ordered = tuple(sorted(
        periods,
        key=lambda item: (item.start_date, item.end_date, item.fiscal_ordinal, str(item.period_id)),
    ))
    if set(item.period_id for item in ordered) != set(request.explicit_period_ids):
        return None, TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND
    if len({item.period_id for item in ordered}) != len(ordered):
        return None, TrendSeriesResolutionErrorCode.INVALID_PERIOD_SET
    for period in ordered:
        if period.tenant_id != request.tenant_id or period.company_id != request.company_id:
            return None, TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND
        if period.status not in {TrendResolvedPeriodStatus.CLOSED, TrendResolvedPeriodStatus.APPROVED}:
            return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
        if period.end_date > request.resolution_timestamp.date():
            return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
        if period.currency != request.expected_currency or period.monetary_unit_multiplier != request.expected_monetary_unit_multiplier:
            return None, TrendSeriesResolutionErrorCode.CURRENCY_MISMATCH
        if period.accounting_basis != request.expected_accounting_basis:
            return None, TrendSeriesResolutionErrorCode.ACCOUNTING_POLICY_MISMATCH
        if period.accounting_policy_version != request.expected_accounting_policy_version:
            return None, TrendSeriesResolutionErrorCode.ACCOUNTING_POLICY_MISMATCH
        if period.fiscal_calendar_reference != request.fiscal_calendar_reference:
            return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
        if _period_family_error(period, request.expected_period_family):
            return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
    if ordered[-1].period_id != request.anchor_period_id:
        return None, TrendSeriesResolutionErrorCode.INVALID_PERIOD_SET
    if any(previous.end_date >= current.start_date for previous, current in zip(ordered, ordered[1:])):
        return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
    family = request.expected_period_family
    if family in {
        TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY,
        TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY,
    } and len({item.fiscal_ordinal for item in ordered}) != 1:
        return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
    if family is TrendPeriodFamily.ANNUAL:
        durations = {item.months_covered for item in ordered}
        if durations != {12}:
            return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
    if family is TrendPeriodFamily.CUSTOM_DISCRETE:
        if request.comparability_profile_version != TREND_COMPARABILITY_PROFILE_VERSION_V1:
            return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
        if len({item.months_covered for item in ordered}) != 1:
            return None, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
    return ordered, None


def _source_projection(source: TrendResolvedSourceCandidate) -> TrendSourceMetricProjection:
    source_mode = TrendSourceMode(source.source_mode) if source.source_mode is not None else None
    ratio_status = (
        TrendRatioComputationStatus(source.ratio_status)
        if source.ratio_status is not None else None
    )
    ratio_reliability = (
        TrendRatioReliability(source.ratio_reliability)
        if source.ratio_reliability is not None else None
    )
    status = (
        TrendSourceMetricStatus.RESULT_BEARING
        if source.source_status is TrendResolvedSourceStatus.COMPLETED
        else TrendSourceMetricStatus.FAILED
    )
    return TrendSourceMetricProjection(
        source_engine_type=source.source_engine_type,
        schema_version=source.source_schema_version,
        model_version=source.source_model_version,
        status=status,
        digest_verified=source.digest_verified,
        provenance_verified=source.provenance_verified,
        field_present=source.field_present,
        value=source.value,
        source_evidence=source.source_evidence,
        source_mode=source_mode,
        ratio_status=ratio_status,
        ratio_reliability=ratio_reliability,
    )


def _validate_sources(
    request: TrendSeriesResolutionRequest,
    definition: TrendMetricDefinition,
    periods: tuple[TrendResolvedPeriod, ...],
    sources: tuple[TrendResolvedSourceCandidate, ...],
) -> TrendSeriesResolutionErrorCode | None:
    if len(sources) != len(periods):
        return TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND
    intent_by_period = {item.period_id: item for item in request.explicit_sources}
    if len({item.analysis_result_id for item in sources}) != len(sources):
        return TrendSeriesResolutionErrorCode.AMBIGUOUS_SOURCE
    if len({item.period_id for item in sources}) != len(sources):
        return TrendSeriesResolutionErrorCode.AMBIGUOUS_SOURCE
    expected_role = _ROLE_BY_ENGINE[definition.source_engine_type]
    for source in sources:
        intent = intent_by_period.get(source.period_id)
        if intent is None or source.analysis_result_id != intent.analysis_result_id:
            return TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND
        if intent.source_role is not expected_role or source.source_role is not expected_role:
            return TrendSeriesResolutionErrorCode.AMBIGUOUS_SOURCE
        if source.tenant_id != request.tenant_id or source.company_id != request.company_id:
            return TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND
        if source.source_engine_type is not definition.source_engine_type or source.source_analysis_type is not definition.source_analysis_type:
            return TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE
        if source.source_field_path != definition.source_field_path:
            return TrendSeriesResolutionErrorCode.REGISTRY_INTEGRITY_FAILURE
        if source.source_status is not TrendResolvedSourceStatus.COMPLETED:
            return TrendSeriesResolutionErrorCode.SOURCE_STATUS_INVALID
        if source.canonical_digest is None or source.recomputed_digest is None or not source.digest_verified:
            return TrendSeriesResolutionErrorCode.SOURCE_DIGEST_MISMATCH
        if not compare_digest(source.canonical_digest, source.recomputed_digest):
            return TrendSeriesResolutionErrorCode.SOURCE_DIGEST_MISMATCH
        if not definition.source_compatibility(
            schema_version=source.source_schema_version,
            model_version=source.source_model_version,
        ).accepted:
            return TrendSeriesResolutionErrorCode.SOURCE_VERSION_UNSUPPORTED
        if not source.provenance_verified:
            return TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE
        if not source.authoritative_chain_head_verified:
            return TrendSeriesResolutionErrorCode.STALE_RESTATEMENT_SOURCE
    return None


def _gap_between(
    previous: TrendResolvedPeriod,
    current: TrendResolvedPeriod,
    family: TrendPeriodFamily,
) -> bool:
    if family is TrendPeriodFamily.CUSTOM_DISCRETE:
        return previous.end_date + timedelta(days=1) != current.start_date
    return _cadence_position(current, family) - _cadence_position(previous, family) > 1


def resolve_series_snapshot(
    request: TrendSeriesResolutionRequest,
    snapshot: TrendSeriesResolutionSnapshot,
    registry: TrendMetricRegistry = TREND_METRIC_REGISTRY_V1,
) -> TrendSeriesResolutionResult:
    if type(request) is not TrendSeriesResolutionRequest or type(snapshot) is not TrendSeriesResolutionSnapshot:
        return _failed(TrendSeriesResolutionErrorCode.INVALID_REQUEST)
    if type(registry) is not TrendMetricRegistry:
        return _failed(TrendSeriesResolutionErrorCode.REGISTRY_INTEGRITY_FAILURE)
    if (
        request.expected_metric_registry_version != registry.registry_version
        or request.expected_metric_registry_digest != registry.digest
        or request.expected_metric_registry_version != TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1
    ):
        return _failed(TrendSeriesResolutionErrorCode.REGISTRY_INTEGRITY_FAILURE)
    try:
        definition = registry.get(request.metric_code)
    except ValueError:
        return _failed(TrendSeriesResolutionErrorCode.INVALID_REQUEST)
    periods, period_error = _validate_periods(request, snapshot.periods)
    if period_error is not None or periods is None:
        return _failed(period_error or TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD)
    source_error = _validate_sources(request, definition, periods, snapshot.sources)
    if source_error is not None:
        return _failed(source_error)
    expected_candidate_digest = canonical_candidate_set_digest(request, snapshot.periods, snapshot.sources)
    if not compare_digest(expected_candidate_digest, snapshot.candidate_set_digest):
        return _failed(TrendSeriesResolutionErrorCode.SOURCE_SET_CHANGED)

    source_by_period = {item.period_id: item for item in snapshot.sources}
    gaps: list[TrendGap] = []
    boundaries: list[TrendSegmentBoundary] = []
    segment_by_period: dict = {periods[0].period_id: 0}
    segment_ordinal = 0
    for previous, current in zip(periods, periods[1:]):
        has_gap = _gap_between(previous, current, request.expected_period_family)
        restatement_changed = previous.restatement_profile is not current.restatement_profile
        if has_gap:
            gaps.append(TrendGap(
                previous.period_id,
                current.period_id,
                previous.end_date + timedelta(days=1),
                current.start_date - timedelta(days=1),
            ))
            boundaries.append(TrendSegmentBoundary(
                previous.period_id, current.period_id, TrendSegmentBoundaryKind.PERIOD_GAP
            ))
        if restatement_changed:
            boundaries.append(TrendSegmentBoundary(
                previous.period_id, current.period_id, TrendSegmentBoundaryKind.RESTATEMENT_CHANGE
            ))
        if has_gap or restatement_changed:
            segment_ordinal += 1
        segment_by_period[current.period_id] = segment_ordinal

    observations: list[ResolvedTrendObservation] = []
    for ordinal, period in enumerate(periods):
        source = source_by_period[period.period_id]
        try:
            mapped = map_source_metric_evidence(definition, _source_projection(source))
        except (TypeError, ValueError):
            return _failed(TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE)
        if not mapped.source_accepted:
            return _failed(TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE)
        evidence = mapped.evidence
        warnings: list[TrendWarning] = []
        if period.restatement_profile is TrendRestatementProfile.UNDECLARED_LEGACY:
            if evidence is not TrendEvidenceLevel.UNAVAILABLE:
                evidence = weakest_evidence(evidence, TrendEvidenceLevel.ESTIMATED)
            warnings.append(TrendWarning(TrendWarningCode.LEGACY_RESTATEMENT_STATUS_UNDECLARED))
        if period.one_off_status is TrendOneOffStatus.UNKNOWN:
            warnings.append(TrendWarning(TrendWarningCode.ONE_OFF_STATUS_UNKNOWN))
        if evidence is TrendEvidenceLevel.UNAVAILABLE:
            warnings.append(TrendWarning(TrendWarningCode.METRIC_OBSERVATION_UNAVAILABLE))
        observation = TrendObservation(
            ordinal=ordinal,
            segment_ordinal=segment_by_period[period.period_id],
            company_id=request.company_id,
            period_id=period.period_id,
            period_start_date=period.start_date,
            period_end_date=period.end_date,
            period_family=request.expected_period_family,
            coverage_kind=period.coverage_kind,
            measurement_basis=definition.measurement_basis_for(request.expected_period_family),
            value=mapped.value if evidence is not TrendEvidenceLevel.UNAVAILABLE else None,
            currency=period.currency,
            monetary_unit_multiplier=period.monetary_unit_multiplier,
            scale=definition.scale,
            evidence=evidence,
            source_result_id=source.analysis_result_id,
            source_engine_type=source.source_engine_type,
            source_schema_version=source.source_schema_version,
            source_model_version=source.source_model_version,
            canonical_source_digest=source.canonical_digest,
            restatement_profile=period.restatement_profile,
            restatement_revision=period.restatement_revision,
            one_off_status=period.one_off_status,
            warnings=tuple(warnings),
        )
        observation_digest = canonical_trend_digest((period.fiscal_ordinal, source.source_field_path, observation))
        observations.append(ResolvedTrendObservation(
            period.fiscal_ordinal, source.source_field_path, observation, observation_digest
        ))

    segments: list[ResolvedTrendSegment] = []
    for current_segment in range(segment_ordinal + 1):
        ordinals = tuple(
            item.observation.ordinal for item in observations
            if item.observation.segment_ordinal == current_segment
        )
        proof = canonical_trend_digest((
            "trend-comparability-proof/v1",
            TREND_COMPARABILITY_PROFILE_VERSION_V1,
            request.tenant_id, request.company_id,
            request.expected_period_family,
            tuple(
                (
                    observations[index].observation.period_id,
                    observations[index].observation.source_result_id,
                    observations[index].observation.canonical_source_digest,
                    observations[index].observation.source_schema_version,
                    observations[index].observation.source_model_version,
                    observations[index].observation.restatement_profile,
                    observations[index].observation.restatement_revision,
                    observations[index].observation.segment_ordinal,
                )
                for index in ordinals
            ),
        ))
        segments.append(ResolvedTrendSegment(current_segment, ordinals, proof))

    resolution_projection = (
        request.tenant_id, request.company_id, request.anchor_period_id,
        request.metric_code, request.expected_period_family,
        request.expected_currency, request.expected_monetary_unit_multiplier,
        request.expected_accounting_basis, request.expected_accounting_policy_version,
        request.fiscal_calendar_reference, registry.registry_version, registry.digest,
        tuple(item.observation.period_id for item in observations),
        tuple(item.observation.source_result_id for item in observations),
        tuple(item.observation.canonical_source_digest for item in observations),
        tuple(item.observation.source_schema_version for item in observations),
        tuple(item.observation.source_model_version for item in observations),
        tuple(item.observation.evidence for item in observations),
        tuple(gaps), tuple(boundaries), tuple(segments),
        snapshot.candidate_set_digest,
        TREND_SERIES_RESOLUTION_CONTRACT_VERSION,
    )
    resolution_digest = canonical_trend_digest(resolution_projection)
    series = ResolvedTrendSeries(
        tenant_id=request.tenant_id,
        company_id=request.company_id,
        anchor_period_id=request.anchor_period_id,
        metric_code=request.metric_code,
        period_family=request.expected_period_family,
        currency=request.expected_currency,
        monetary_unit_multiplier=request.expected_monetary_unit_multiplier,
        observations=tuple(observations),
        gaps=tuple(gaps),
        segment_boundaries=tuple(boundaries),
        segments=tuple(segments),
        candidate_set_digest=snapshot.candidate_set_digest,
        resolution_digest=resolution_digest,
        resolution_reference=canonical_trend_reference(resolution_digest),
        nominal_values=True,
        inflation_adjusted=False,
        contract_version=TREND_SERIES_RESOLUTION_CONTRACT_VERSION,
    )
    max_available_segment = max(
        sum(
            item.observation.value is not None and item.observation.segment_ordinal == segment.segment_ordinal
            for item in observations
        )
        for segment in segments
    )
    status = (
        TrendSeriesResolutionStatus.RESOLVED
        if max_available_segment >= 3
        else TrendSeriesResolutionStatus.INSUFFICIENT_FOR_TREND
        if max_available_segment == 2
        else TrendSeriesResolutionStatus.INSUFFICIENT_DATA
    )
    return TrendSeriesResolutionResult(status, series, None)


class TrendMultiPeriodSeriesResolver:
    def __init__(
        self,
        repository: TrendSeriesRepositoryPort,
        registry: TrendMetricRegistry = TREND_METRIC_REGISTRY_V1,
    ) -> None:
        self._repository = repository
        self._registry = registry

    def resolve(self, request: TrendSeriesResolutionRequest) -> TrendSeriesResolutionResult:
        try:
            snapshot = self._repository.load_resolution_snapshot(request)
        except TrendSeriesRepositoryError as exc:
            return _failed(exc.code)
        except Exception:
            return _failed(TrendSeriesResolutionErrorCode.RESOLUTION_UNAVAILABLE)
        return resolve_series_snapshot(request, snapshot, self._registry)
