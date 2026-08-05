from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from random import Random
from uuid import UUID

import pytest

from app.engines.multi_period_trend import (
    TREND_COMPARABILITY_PROFILE_VERSION_V1,
    TREND_METRIC_REGISTRY_V1,
    ResolvedTrendSeries,
    TrendCoverageKind,
    TrendEvidenceLevel,
    TrendOneOffStatus,
    TrendPeriodFamily,
    TrendResolvedPeriod,
    TrendResolvedPeriodStatus,
    TrendResolvedPeriodType,
    TrendResolvedSourceCandidate,
    TrendResolvedSourceStatus,
    TrendRestatementProfile,
    TrendSeriesResolutionContractError,
    TrendSeriesResolutionErrorCode,
    TrendSeriesResolutionRequest,
    TrendSeriesResolutionSnapshot,
    TrendSeriesResolutionStatus,
    TrendSourceAnalysisType,
    TrendSourceEngineType,
    TrendSourceSelectionIntent,
    TrendSourceSelectionRole,
    canonical_candidate_set_digest,
    resolve_series_snapshot,
)


TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
COMPANY = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OTHER_COMPANY = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
FISCAL = "fiscal-calendar:v1:01-01:12-31"
NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


def _id(prefix: int, ordinal: int) -> UUID:
    return UUID(f"{prefix:08x}-0000-4000-8000-{ordinal:012d}")


def _annual_period(index: int, *, year: int | None = None, **changes) -> TrendResolvedPeriod:
    year = year or 2020 + index
    values = dict(
        tenant_id=TENANT,
        company_id=COMPANY,
        period_id=_id(1, index),
        year=year,
        period_type=TrendResolvedPeriodType.YEAR_END,
        fiscal_ordinal=4,
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        months_covered=12,
        status=TrendResolvedPeriodStatus.CLOSED,
        coverage_kind=TrendCoverageKind.CUMULATIVE,
        accounting_basis="tr_tdhp_accrual",
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        fiscal_calendar_reference=FISCAL,
        currency="TRY",
        monetary_unit_multiplier=Decimal("1"),
        restatement_profile=TrendRestatementProfile.ORIGINAL,
        restatement_revision=0,
        one_off_status=TrendOneOffStatus.UNKNOWN,
    )
    values.update(changes)
    return TrendResolvedPeriod(**values)


def _periods_for(family: TrendPeriodFamily, count: int = 3) -> tuple[TrendResolvedPeriod, ...]:
    if family is TrendPeriodFamily.ANNUAL:
        return tuple(_annual_period(index) for index in range(1, count + 1))
    rows = []
    for index in range(1, count + 1):
        if family is TrendPeriodFamily.MONTHLY_DISCRETE:
            start = date(2025, index, 1)
            end = date(2025, index + 1, 1) - __import__("datetime").timedelta(days=1)
            period_type, months, coverage, fiscal = TrendResolvedPeriodType.MONTHLY, 1, TrendCoverageKind.DISCRETE, index
            year = 2025
        elif family is TrendPeriodFamily.QUARTERLY_DISCRETE:
            start_month = 1 + (index - 1) * 3
            start = date(2025, start_month, 1)
            end_month = start_month + 2
            end = date(2025, end_month + 1, 1) - __import__("datetime").timedelta(days=1)
            period_type, months, coverage, fiscal = TrendResolvedPeriodType.QUARTER, 3, TrendCoverageKind.DISCRETE, index
            year = 2025
        elif family is TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY:
            year = 2022 + index
            start, end = date(year, 1, 1), date(year, 6, 30)
            period_type, months, coverage, fiscal = TrendResolvedPeriodType.QUARTER, 6, TrendCoverageKind.CUMULATIVE, 2
        elif family is TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY:
            year = 2022 + index
            start, end = date(year, 1, 1), date(year, 9, 30)
            period_type, months, coverage, fiscal = TrendResolvedPeriodType.TEMPORARY_TAX, 9, TrendCoverageKind.CUMULATIVE, 3
        else:
            year = 2025
            start = date(2025, 1 + (index - 1) * 2, 1)
            end = date(2025, 1 + index * 2, 1) - __import__("datetime").timedelta(days=1)
            period_type, months, coverage, fiscal = TrendResolvedPeriodType.CUSTOM, 2, TrendCoverageKind.DISCRETE, index
        rows.append(_annual_period(
            index,
            year=year,
            period_id=_id(1, index),
            period_type=period_type,
            fiscal_ordinal=fiscal,
            start_date=start,
            end_date=end,
            months_covered=months,
            coverage_kind=coverage,
        ))
    return tuple(rows)


def _source(period: TrendResolvedPeriod, metric_code="bs.total_assets", *, value=Decimal("100"), **changes):
    definition = TREND_METRIC_REGISTRY_V1.get(metric_code)
    role = {
        TrendSourceEngineType.BALANCE_SHEET: TrendSourceSelectionRole.BALANCE_SHEET,
        TrendSourceEngineType.INCOME_STATEMENT: TrendSourceSelectionRole.INCOME_STATEMENT,
        TrendSourceEngineType.CASH_FLOW: TrendSourceSelectionRole.CASH_FLOW,
        TrendSourceEngineType.FINANCIAL_RATIOS: TrendSourceSelectionRole.FINANCIAL_RATIOS,
    }[definition.source_engine_type]
    version = definition.accepted_source_versions[0]
    mode = "direct_document" if definition.source_engine_type in {TrendSourceEngineType.BALANCE_SHEET, TrendSourceEngineType.INCOME_STATEMENT} else None
    ratio_status = "calculated" if definition.source_engine_type is TrendSourceEngineType.FINANCIAL_RATIOS and value is not None else None
    ratio_reliability = "high" if ratio_status else None
    evidence = TrendEvidenceLevel.EXACT
    values = dict(
        source_role=role,
        analysis_result_id=_id(2, period.period_id.int & 0xFFFF),
        tenant_id=period.tenant_id,
        company_id=period.company_id,
        period_id=period.period_id,
        source_engine_type=definition.source_engine_type,
        source_analysis_type=definition.source_analysis_type,
        source_status=TrendResolvedSourceStatus.COMPLETED,
        source_field_path=definition.source_field_path,
        source_schema_version=version.schema_version,
        source_model_version=version.model_version,
        canonical_digest=f"{period.period_id.int & 15:x}" * 64,
        recomputed_digest=f"{period.period_id.int & 15:x}" * 64,
        digest_verified=True,
        provenance_verified=True,
        authoritative_chain_head_verified=True,
        value=value,
        field_present=value is not None,
        source_evidence=evidence if value is not None else TrendEvidenceLevel.UNAVAILABLE,
        source_mode=mode,
        ratio_status=ratio_status if value is not None else ("not_calculable" if definition.source_engine_type is TrendSourceEngineType.FINANCIAL_RATIOS else None),
        ratio_reliability=ratio_reliability if value is not None else ("not_calculable" if definition.source_engine_type is TrendSourceEngineType.FINANCIAL_RATIOS else None),
    )
    values.update(changes)
    return TrendResolvedSourceCandidate(**values)


def _request(periods, metric_code="bs.total_assets", *, family=TrendPeriodFamily.ANNUAL, sources=None, **changes):
    sources = sources or tuple(_source(period, metric_code) for period in periods)
    values = dict(
        tenant_id=TENANT,
        company_id=COMPANY,
        anchor_period_id=periods[-1].period_id,
        metric_code=metric_code,
        explicit_period_ids=tuple(period.period_id for period in periods),
        explicit_sources=tuple(
            TrendSourceSelectionIntent(source.period_id, source.source_role, source.analysis_result_id)
            for source in sources
        ),
        expected_period_family=family,
        expected_currency="TRY",
        expected_monetary_unit_multiplier=Decimal("1"),
        expected_accounting_basis="tr_tdhp_accrual",
        expected_accounting_policy_version="tr_tdhp_accrual/1.0.0",
        fiscal_calendar_reference=FISCAL,
        comparability_profile_version=TREND_COMPARABILITY_PROFILE_VERSION_V1,
        expected_metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        expected_metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        correlation_reference="trend-resolution-unit",
        resolution_timestamp=NOW,
    )
    values.update(changes)
    return TrendSeriesResolutionRequest(**values)


def _snapshot(request, periods, sources):
    return TrendSeriesResolutionSnapshot(
        tuple(periods), tuple(sources), canonical_candidate_set_digest(request, tuple(periods), tuple(sources))
    )


def _resolve(periods, metric_code="bs.total_assets", *, family=TrendPeriodFamily.ANNUAL, sources=None, **request_changes):
    sources = sources or tuple(_source(period, metric_code) for period in periods)
    request = _request(periods, metric_code, family=family, sources=sources, **request_changes)
    return resolve_series_snapshot(request, _snapshot(request, periods, sources))


@pytest.mark.parametrize("count", (3, 5))
def test_successful_annual_series(count):
    outcome = _resolve(_periods_for(TrendPeriodFamily.ANNUAL, count))
    assert outcome.status is TrendSeriesResolutionStatus.RESOLVED
    assert len(outcome.series.observations) == count
    assert outcome.series.anchor_period_id == outcome.series.observations[-1].observation.period_id


@pytest.mark.parametrize("family", tuple(TrendPeriodFamily))
def test_all_six_cadence_families_resolve(family):
    periods = _periods_for(family)
    outcome = _resolve(periods, family=family)
    assert outcome.status is TrendSeriesResolutionStatus.RESOLVED
    assert outcome.series.period_family is family


def test_two_observations_are_insufficient_for_trend_and_one_available_is_insufficient_data():
    periods = _periods_for(TrendPeriodFamily.ANNUAL, 2)
    assert _resolve(periods).status is TrendSeriesResolutionStatus.INSUFFICIENT_FOR_TREND
    sources = (_source(periods[0]), _source(periods[1], value=None))
    result = _resolve(periods, sources=sources)
    assert result.status is TrendSeriesResolutionStatus.INSUFFICIENT_DATA
    assert result.series.observations[1].observation.value is None


@pytest.mark.parametrize("seed", range(12))
def test_input_order_independence_canonical_order_and_digest(seed):
    periods = list(_periods_for(TrendPeriodFamily.ANNUAL, 5))
    sources = [_source(period) for period in periods]
    request = _request(periods, sources=sources)
    expected = resolve_series_snapshot(request, _snapshot(request, periods, sources))
    Random(seed).shuffle(periods)
    Random(seed + 100).shuffle(sources)
    shuffled_request = replace(
        request,
        explicit_period_ids=tuple(period.period_id for period in periods),
        explicit_sources=tuple(
            TrendSourceSelectionIntent(source.period_id, source.source_role, source.analysis_result_id)
            for source in sources
        ),
    )
    actual = resolve_series_snapshot(shuffled_request, _snapshot(shuffled_request, periods, sources))
    assert tuple(item.observation.period_id for item in actual.series.observations) == tuple(
        item.observation.period_id for item in expected.series.observations
    )
    assert actual.series.resolution_digest == expected.series.resolution_digest


def test_request_rejects_duplicate_source_period_and_ambiguous_source_intents():
    periods = _periods_for(TrendPeriodFamily.ANNUAL, 2)
    sources = tuple(_source(period) for period in periods)
    with pytest.raises(TrendSeriesResolutionContractError, match="duplicate source"):
        replace(
            _request(periods, sources=sources),
            explicit_sources=(
                TrendSourceSelectionIntent(periods[0].period_id, sources[0].source_role, sources[0].analysis_result_id),
                TrendSourceSelectionIntent(periods[1].period_id, sources[1].source_role, sources[0].analysis_result_id),
            ),
        )
    with pytest.raises(TrendSeriesResolutionContractError, match="ambiguous"):
        first = TrendSourceSelectionIntent(
            periods[0].period_id, sources[0].source_role, sources[0].analysis_result_id
        )
        second = TrendSourceSelectionIntent(
            periods[0].period_id, sources[0].source_role, _id(2, 999)
        )
        replace(
            _request(periods, sources=sources),
            explicit_sources=(first, second),
        )


@pytest.mark.parametrize(
    "source_change,error",
    (
        ({"source_status": TrendResolvedSourceStatus.FAILED}, TrendSeriesResolutionErrorCode.SOURCE_STATUS_INVALID),
        ({"digest_verified": False}, TrendSeriesResolutionErrorCode.SOURCE_DIGEST_MISMATCH),
        ({"recomputed_digest": "f" * 64}, TrendSeriesResolutionErrorCode.SOURCE_DIGEST_MISMATCH),
        ({"source_model_version": "99.0.0"}, TrendSeriesResolutionErrorCode.SOURCE_VERSION_UNSUPPORTED),
        ({"source_field_path": ("facts", "wrong")}, TrendSeriesResolutionErrorCode.REGISTRY_INTEGRITY_FAILURE),
        ({"provenance_verified": False}, TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE),
        ({"authoritative_chain_head_verified": False}, TrendSeriesResolutionErrorCode.STALE_RESTATEMENT_SOURCE),
        ({"company_id": OTHER_COMPANY}, TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND),
    ),
)
def test_source_selection_and_integrity_fail_closed(source_change, error):
    periods = _periods_for(TrendPeriodFamily.ANNUAL, 3)
    sources = tuple(_source(period) for period in periods)
    sources = (replace(sources[0], **source_change),) + sources[1:]
    result = _resolve(periods, sources=sources)
    assert result.status is TrendSeriesResolutionStatus.FAILED
    assert result.error_code is error


@pytest.mark.parametrize(
    "period_change,error",
    (
        ({"company_id": OTHER_COMPANY}, TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND),
        ({"currency": "USD"}, TrendSeriesResolutionErrorCode.CURRENCY_MISMATCH),
        ({"accounting_basis": "other"}, TrendSeriesResolutionErrorCode.ACCOUNTING_POLICY_MISMATCH),
        ({"accounting_policy_version": "other/1.0"}, TrendSeriesResolutionErrorCode.ACCOUNTING_POLICY_MISMATCH),
        ({"fiscal_calendar_reference": "other"}, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD),
        ({"period_type": TrendResolvedPeriodType.MONTHLY}, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD),
        ({"coverage_kind": TrendCoverageKind.DISCRETE}, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD),
        ({"months_covered": 11}, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD),
        ({"start_date": date(2021, 2, 1)}, TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD),
    ),
)
def test_authoritative_comparability_fail_closed(period_change, error):
    periods = list(_periods_for(TrendPeriodFamily.ANNUAL, 3))
    periods[0] = replace(periods[0], **period_change)
    sources = tuple(_source(period) for period in periods)
    result = _resolve(tuple(periods), sources=sources)
    assert result.status is TrendSeriesResolutionStatus.FAILED
    assert result.error_code is error


def test_future_period_period_after_anchor_and_overlap_are_rejected():
    periods = list(_periods_for(TrendPeriodFamily.ANNUAL, 3))
    future = replace(periods[-1], year=2027, start_date=date(2027, 1, 1), end_date=date(2027, 12, 31))
    assert _resolve(tuple(periods[:-1] + [future]), sources=tuple(_source(p) for p in periods[:-1] + [future])).error_code is TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD
    with pytest.raises(TrendSeriesResolutionContractError, match="anchor"):
        _request(tuple(periods), anchor_period_id=_id(1, 99))
    overlap = replace(periods[1], start_date=date(2021, 12, 1))
    assert _resolve(tuple([periods[0], overlap, periods[2]]), sources=tuple(_source(p) for p in [periods[0], overlap, periods[2]])).error_code is TrendSeriesResolutionErrorCode.INCOMPATIBLE_PERIOD


def test_gap_is_metadata_not_zero_and_splits_series():
    periods = (_periods_for(TrendPeriodFamily.MONTHLY_DISCRETE, 1)[0],) + _periods_for(TrendPeriodFamily.MONTHLY_DISCRETE, 3)[2:]
    sources = tuple(_source(period) for period in periods)
    result = _resolve(periods, family=TrendPeriodFamily.MONTHLY_DISCRETE, sources=sources)
    assert len(result.series.gaps) == 1
    assert len(result.series.segments) == 2
    assert len(result.series.observations) == len(periods)
    assert all(item.observation.value != Decimal(0) for item in result.series.observations)


def test_restatement_segmentation_and_one_off_unknown_are_preserved():
    periods = list(_periods_for(TrendPeriodFamily.ANNUAL, 3))
    periods[2] = replace(periods[2], restatement_profile=TrendRestatementProfile.RESTATED, restatement_revision=1)
    sources = tuple(_source(period) for period in periods)
    result = _resolve(tuple(periods), sources=sources)
    assert len(result.series.segments) == 2
    assert result.series.observations[-1].observation.restatement_profile is TrendRestatementProfile.RESTATED
    assert all(item.observation.one_off_status is TrendOneOffStatus.UNKNOWN for item in result.series.observations)


@pytest.mark.parametrize(
    "metric_code,evidence,mode,reliability,expected",
    (
        ("bs.total_assets", TrendEvidenceLevel.EXACT, "direct_document", None, TrendEvidenceLevel.EXACT),
        ("is.net_sales", TrendEvidenceLevel.EXACT, "trial_balance_derived", None, TrendEvidenceLevel.DERIVED),
        ("cf.operating_cash_flow", TrendEvidenceLevel.DERIVED, None, None, TrendEvidenceLevel.DERIVED),
        ("cf.free_cash_flow", TrendEvidenceLevel.ESTIMATED, None, None, TrendEvidenceLevel.ESTIMATED),
        ("ratio.current_ratio", TrendEvidenceLevel.UNAVAILABLE, None, "not_calculable", TrendEvidenceLevel.UNAVAILABLE),
    ),
)
def test_observation_evidence_mapping(metric_code, evidence, mode, reliability, expected):
    periods = _periods_for(TrendPeriodFamily.ANNUAL, 3)
    sources = []
    for period in periods:
        value = None if expected is TrendEvidenceLevel.UNAVAILABLE else Decimal("123.4500")
        changes = {"source_evidence": evidence, "source_mode": mode}
        if metric_code.startswith("ratio."):
            changes.update(ratio_status="not_calculable", ratio_reliability=reliability, field_present=False)
        sources.append(_source(period, metric_code, value=value, **changes))
    result = _resolve(periods, metric_code, sources=tuple(sources))
    assert all(item.observation.evidence is expected for item in result.series.observations)
    assert all(item.observation.value == (None if expected is TrendEvidenceLevel.UNAVAILABLE else Decimal("123.4500")) for item in result.series.observations)


def test_undeclared_legacy_caps_evidence_without_assuming_no_restatement():
    periods = tuple(replace(item, restatement_profile=TrendRestatementProfile.UNDECLARED_LEGACY) for item in _periods_for(TrendPeriodFamily.ANNUAL, 3))
    result = _resolve(periods, sources=tuple(_source(p) for p in periods))
    assert all(item.observation.evidence is TrendEvidenceLevel.ESTIMATED for item in result.series.observations)


def test_resolution_digest_changes_for_period_source_digest_version_and_evidence():
    periods = _periods_for(TrendPeriodFamily.ANNUAL, 3)
    sources = tuple(_source(period) for period in periods)
    base = _resolve(periods, sources=sources).series.resolution_digest
    variants = (
        (periods, (replace(sources[0], canonical_digest="e" * 64, recomputed_digest="e" * 64),) + sources[1:]),
        (periods, (replace(sources[0], source_evidence=TrendEvidenceLevel.DERIVED),) + sources[1:]),
    )
    assert all(_resolve(ps, sources=ss).series.resolution_digest != base for ps, ss in variants)


def test_contracts_are_immutable_safe_and_do_not_leak_raw_payload():
    periods = _periods_for(TrendPeriodFamily.ANNUAL, 3)
    result = _resolve(periods)
    assert type(result.series) is ResolvedTrendSeries
    with pytest.raises(FrozenInstanceError):
        result.series.metric_code = "changed"
    assert repr(result.series) == "ResolvedTrendSeries()"
    assert "payload" not in ResolvedTrendSeries.__dataclass_fields__


def test_4_6c_engine_boundary_has_no_framework_persistence_or_trend_calculation():
    package = Path(__file__).parents[1] / "app" / "engines" / "multi_period_trend"
    files = (package / "resolution_contracts.py", package / "series_resolution.py")
    for file_path in files:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(name.split(".", 1)[0] in {"sqlalchemy", "fastapi", "pydantic"} for name in imports)
        assert "calculate_cagr" not in source
        assert "percentage_change" not in source
        assert "absolute_change" not in source
        assert "INSERT INTO" not in source
