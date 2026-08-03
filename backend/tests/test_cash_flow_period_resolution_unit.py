"""Milestone 4.5C pure comparable-period/source resolution tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import random
import uuid

import pytest

from app.engines.cash_flow import (
    CASH_FLOW_REQUIRED_SOURCE_ROLES_V1,
    CashFlowAccountingBasisCode,
    CashFlowComparabilityRow,
    CashFlowInputResolutionStatus,
    CashFlowPeriodResolutionRequest,
    CashFlowResolutionSnapshot,
    CashFlowResolvedPeriod,
    CashFlowResolvedSource,
    CashFlowSourceRole,
    CashFlowContractError,
    resolve_snapshot,
)
from app.engines.cash_flow.policy import CashFlowPresentationProfile
from app.engines.cash_flow.types import CashFlowErrorCode
from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    PeriodCoverageKind,
    PeriodStatus,
    PeriodType,
    SourceMode,
)


TENANT = uuid.UUID("00000000-0000-4000-8000-000000004501")
COMPANY = uuid.UUID("00000000-0000-4000-8000-000000004502")
CURRENT = uuid.UUID("00000000-0000-4000-8000-000000004503")
PRIOR = uuid.UUID("00000000-0000-4000-8000-000000004504")
DIGEST = "1" * 64


def _period(
    *,
    period_id=PRIOR,
    period_type=PeriodType.YEAR_END,
    start=date(2023, 1, 1),
    end=date(2023, 12, 31),
    annual_start=None,
    annual_end=None,
    months=12,
    coverage=PeriodCoverageKind.CUMULATIVE,
    status=PeriodStatus.CLOSED,
    company=COMPANY,
    tenant=TENANT,
    currency="TRY",
    basis=CashFlowAccountingBasisCode.TR_TDHP_ACCRUAL,
    policy="tr_tdhp_accrual/1.0.0",
    ifrs18=False,
):
    return CashFlowResolvedPeriod(
        period_id=period_id,
        tenant_id=tenant,
        company_id=company,
        currency_code=currency,
        period_type=period_type,
        period_number=4,
        start_date=start,
        end_date=end,
        months_covered=months,
        status=status,
        accounting_basis_code=basis,
        accounting_policy_version=policy,
        annual_reporting_period_start_date=annual_start or start,
        annual_reporting_period_end_date=annual_end or end,
        ifrs18_early_adopted=ifrs18,
        coverage_kind=coverage,
    )


def _annual_current():
    return _period(
        period_id=CURRENT,
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
    )


def _request(**changes):
    values = dict(
        tenant_id=TENANT,
        company_id=COMPANY,
        current_period_id=CURRENT,
        required_source_roles=CASH_FLOW_REQUIRED_SOURCE_ROLES_V1,
        expected_currency="TRY",
        expected_accounting_basis=CashFlowAccountingBasisCode.TR_TDHP_ACCRUAL,
        expected_accounting_policy_version="tr_tdhp_accrual/1.0.0",
        expected_presentation_profile=CashFlowPresentationProfile.TMS_TFRS_2024_INDIRECT_V1,
        expected_mapping_registry_version="1.0.0",
        correlation_id="cf-period-unit",
        resolved_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        explicit_prior_period_id=None,
    )
    values.update(changes)
    return CashFlowPeriodResolutionRequest(**values)


def _source(role, period_id, *, source_id=None, status=AnalysisStatus.COMPLETED, verified=True, digest=DIGEST):
    analysis_type = {
        CashFlowSourceRole.CURRENT_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
        CashFlowSourceRole.PRIOR_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
        CashFlowSourceRole.CURRENT_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
        CashFlowSourceRole.CURRENT_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
        CashFlowSourceRole.PRIOR_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    }[role]
    return CashFlowResolvedSource(
        source_role=role,
        analysis_result_id=source_id or uuid.uuid5(uuid.NAMESPACE_URL, role.value + str(period_id)),
        company_id=COMPANY,
        period_id=period_id,
        analysis_type=analysis_type,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED,
        status=status,
        canonical_digest=digest,
        recomputed_payload_digest=digest if verified else "2" * 64,
        engine_version="1.0.0",
        completed_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
        digest_verified=verified,
    )


def _sources(prior_id=PRIOR):
    return tuple(sorted((
        _source(CashFlowSourceRole.CURRENT_BALANCE_SHEET, CURRENT),
        _source(CashFlowSourceRole.PRIOR_BALANCE_SHEET, prior_id),
        _source(CashFlowSourceRole.CURRENT_INCOME_STATEMENT, CURRENT),
        _source(CashFlowSourceRole.CURRENT_TRIAL_BALANCE, CURRENT),
        _source(CashFlowSourceRole.PRIOR_TRIAL_BALANCE, prior_id),
    ), key=lambda item: (item.source_role.value, str(item.analysis_result_id))))


def _snapshot(current=None, priors=None, sources=None, digest="a" * 64):
    return CashFlowResolutionSnapshot(
        current_period=current or _annual_current(),
        prior_candidates=tuple(sorted(priors if priors is not None else (_period(),), key=lambda item: str(item.period_id))),
        source_candidates=tuple(sorted(sources if sources is not None else _sources(), key=lambda item: (item.source_role.value, str(item.analysis_result_id)))),
        candidate_set_digest=digest,
    )


def test_valid_annual_pair_resolves_with_exact_sources_and_digest():
    outcome = resolve_snapshot(_request(), _snapshot())
    assert outcome.success is True
    assert outcome.value.status is CashFlowInputResolutionStatus.RESOLVED
    assert outcome.value.comparability_row is CashFlowComparabilityRow.ANNUAL
    assert outcome.value.prior_period_id == PRIOR
    assert tuple(source.source_role for source in outcome.value.sources) == CASH_FLOW_REQUIRED_SOURCE_ROLES_V1
    assert len(outcome.value.resolution_digest) == 64


def test_same_input_produces_same_resolution_digest():
    request, snapshot = _request(), _snapshot()
    assert resolve_snapshot(request, snapshot).value == resolve_snapshot(request, snapshot).value


def test_candidate_input_order_is_rejected_at_contract_boundary():
    with pytest.raises(CashFlowContractError, match="canonical"):
        replace(_snapshot(), source_candidates=tuple(reversed(_sources())))


def test_valid_explicit_prior_must_equal_unique_discovered_candidate():
    outcome = resolve_snapshot(_request(explicit_prior_period_id=PRIOR), _snapshot())
    assert outcome.success and outcome.value.prior_period_id == PRIOR


def test_explicit_unknown_prior_fails_closed():
    outcome = resolve_snapshot(_request(explicit_prior_period_id=uuid.uuid4()), _snapshot())
    assert outcome.error.code is CashFlowErrorCode.SOURCE_NOT_FOUND


def test_no_prior_is_typed_insufficient_without_zero_opening():
    outcome = resolve_snapshot(_request(), _snapshot(priors=(), sources=()))
    assert outcome.success
    assert outcome.value.status is CashFlowInputResolutionStatus.INSUFFICIENT_DATA
    assert outcome.value.prior_period_id is None
    assert outcome.value.comparability_proof_digest is None
    assert not hasattr(outcome.value, "opening_cash")


def test_missing_authoritative_metadata_is_insufficient_not_defaulted():
    current = replace(
        _annual_current(),
        accounting_basis_code=None,
        accounting_policy_version=None,
        annual_reporting_period_start_date=None,
        annual_reporting_period_end_date=None,
        ifrs18_early_adopted=None,
        coverage_kind=None,
    )
    outcome = resolve_snapshot(_request(), _snapshot(current=current))
    assert outcome.success and outcome.value.status is CashFlowInputResolutionStatus.INSUFFICIENT_DATA
    assert outcome.value.current_period.accounting_basis_code is None


@pytest.mark.parametrize("missing_role", CASH_FLOW_REQUIRED_SOURCE_ROLES_V1)
def test_each_missing_required_source_role_is_reported(missing_role):
    sources = tuple(item for item in _sources() if item.source_role is not missing_role)
    outcome = resolve_snapshot(_request(), _snapshot(sources=sources))
    assert outcome.success
    assert outcome.value.status is CashFlowInputResolutionStatus.INSUFFICIENT_DATA
    assert outcome.value.missing_source_roles == (missing_role,)


def test_duplicate_approved_source_role_fails_closed():
    duplicate = _source(CashFlowSourceRole.CURRENT_BALANCE_SHEET, CURRENT, source_id=uuid.uuid4())
    outcome = resolve_snapshot(_request(), _snapshot(sources=_sources() + (duplicate,)))
    assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT


def test_source_status_invalid_fails_closed():
    bad = replace(_sources()[0], status=AnalysisStatus.FAILED)
    sources = tuple(bad if source.source_role is bad.source_role else source for source in _sources())
    outcome = resolve_snapshot(_request(), _snapshot(sources=sources))
    assert outcome.error.code is CashFlowErrorCode.SOURCE_STATUS_INVALID


def test_source_digest_mismatch_fails_closed():
    role = CashFlowSourceRole.CURRENT_BALANCE_SHEET
    sources = tuple(_source(role, CURRENT, verified=False) if source.source_role is role else source for source in _sources())
    outcome = resolve_snapshot(_request(), _snapshot(sources=sources))
    assert outcome.error.code is CashFlowErrorCode.SOURCE_DIGEST_MISMATCH


def test_two_equally_valid_prior_periods_are_ambiguous_not_tiebroken():
    second = replace(_period(), period_id=uuid.uuid4())
    outcome = resolve_snapshot(_request(), _snapshot(priors=(_period(), second)))
    assert outcome.error.code is CashFlowErrorCode.PERIOD_SELECTION_AMBIGUOUS


def test_adding_inferior_candidate_does_not_change_selection():
    inferior = replace(_period(), period_id=uuid.uuid4(), end_date=date(2022, 12, 31), start_date=date(2022, 1, 1), annual_reporting_period_start_date=date(2022, 1, 1), annual_reporting_period_end_date=date(2022, 12, 31))
    baseline = resolve_snapshot(_request(), _snapshot()).value
    expanded = resolve_snapshot(_request(), _snapshot(priors=(_period(), inferior))).value
    assert expanded.prior_period_id == baseline.prior_period_id


@pytest.mark.parametrize(
    "prior_change",
    (
        {"company_id": uuid.UUID("00000000-0000-4000-8000-000000004599")},
        {"currency_code": "USD"},
        {"accounting_policy_version": "other/1.0.0"},
        {"ifrs18_early_adopted": True},
        {"status": PeriodStatus.ACTIVE},
        {
            "end_date": date(2024, 1, 2),
            "annual_reporting_period_end_date": date(2024, 1, 2),
        },
    ),
)
def test_incompatible_prior_candidates_fail_closed(prior_change):
    prior = replace(_period(), **prior_change)
    outcome = resolve_snapshot(_request(), _snapshot(priors=(prior,)))
    assert outcome.error.code is CashFlowErrorCode.PERIOD_NOT_COMPARABLE


def test_current_currency_mismatch_has_typed_failure():
    outcome = resolve_snapshot(_request(), _snapshot(current=replace(_annual_current(), currency_code="USD")))
    assert outcome.error.code is CashFlowErrorCode.SOURCE_CURRENCY_MISMATCH


def test_current_policy_mismatch_has_typed_failure():
    request = _request(expected_accounting_policy_version="unsupported/1.0.0")
    outcome = resolve_snapshot(request, _snapshot())
    assert outcome.error.code is CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED


def test_ifrs18_profile_cutoff_fails_closed():
    current = replace(_annual_current(), start_date=date(2027, 1, 1), end_date=date(2027, 12, 31), annual_reporting_period_start_date=date(2027, 1, 1), annual_reporting_period_end_date=date(2027, 12, 31))
    outcome = resolve_snapshot(_request(), _snapshot(current=current))
    assert outcome.error.code is CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED


def test_valid_non_first_quarter_discrete_pair():
    prior = _period(period_type=PeriodType.QUARTER, start=date(2024, 1, 1), end=date(2024, 3, 31), annual_start=date(2024, 1, 1), annual_end=date(2024, 12, 31), months=3, coverage=PeriodCoverageKind.DISCRETE)
    current = _period(period_id=CURRENT, period_type=PeriodType.QUARTER, start=date(2024, 4, 1), end=date(2024, 6, 30), annual_start=date(2024, 1, 1), annual_end=date(2024, 12, 31), months=3, coverage=PeriodCoverageKind.DISCRETE)
    outcome = resolve_snapshot(_request(), _snapshot(current=current, priors=(prior,), sources=_sources(PRIOR)))
    assert outcome.success and outcome.value.comparability_row is CashFlowComparabilityRow.QUARTER_DISCRETE


def test_valid_first_fiscal_quarter_discrete_uses_prior_annual():
    current = _period(period_id=CURRENT, period_type=PeriodType.QUARTER, start=date(2024, 1, 1), end=date(2024, 3, 31), annual_start=date(2024, 1, 1), annual_end=date(2024, 12, 31), months=3, coverage=PeriodCoverageKind.DISCRETE)
    outcome = resolve_snapshot(_request(), _snapshot(current=current))
    assert outcome.success and outcome.value.comparability_row is CashFlowComparabilityRow.FIRST_FISCAL_QUARTER


def test_valid_cumulative_quarter_uses_prior_annual():
    current = _period(period_id=CURRENT, period_type=PeriodType.QUARTER, start=date(2024, 1, 1), end=date(2024, 6, 30), annual_start=date(2024, 1, 1), annual_end=date(2024, 12, 31), months=6, coverage=PeriodCoverageKind.CUMULATIVE)
    outcome = resolve_snapshot(_request(), _snapshot(current=current))
    assert outcome.success and outcome.value.comparability_row is CashFlowComparabilityRow.QUARTER_CUMULATIVE


def test_discrete_and_cumulative_quarter_are_not_interchangeable():
    prior = _period(period_type=PeriodType.QUARTER, start=date(2024, 1, 1), end=date(2024, 3, 31), annual_start=date(2024, 1, 1), annual_end=date(2024, 12, 31), months=3, coverage=PeriodCoverageKind.DISCRETE)
    current = _period(period_id=CURRENT, period_type=PeriodType.QUARTER, start=date(2024, 4, 1), end=date(2024, 6, 30), annual_start=date(2024, 1, 1), annual_end=date(2024, 12, 31), months=6, coverage=PeriodCoverageKind.CUMULATIVE)
    outcome = resolve_snapshot(_request(), _snapshot(current=current, priors=(prior,)))
    assert outcome.error.code is CashFlowErrorCode.PERIOD_NOT_COMPARABLE


def test_property_candidate_order_does_not_change_canonical_selection():
    rng = random.Random(4503)
    inferior = tuple(
        replace(_period(), period_id=uuid.uuid4(), start_date=date(2020 + year, 1, 1), end_date=date(2020 + year, 12, 31), annual_reporting_period_start_date=date(2020 + year, 1, 1), annual_reporting_period_end_date=date(2020 + year, 12, 31))
        for year in range(3)
    )
    candidates = list((_period(),) + inferior)
    expected = resolve_snapshot(_request(), _snapshot(priors=tuple(candidates))).value.prior_period_id
    for _ in range(20):
        rng.shuffle(candidates)
        canonical = tuple(sorted(candidates, key=lambda item: str(item.period_id)))
        assert resolve_snapshot(_request(), _snapshot(priors=canonical)).value.prior_period_id == expected


def test_resolution_contract_contains_no_monetary_calculation_or_lineage_persistence():
    fields = set(CashFlowInputResolutionStatus.__members__)
    assert fields == {"RESOLVED", "INSUFFICIENT_DATA"}
    result_fields = set(resolve_snapshot(_request(), _snapshot()).value.__dataclass_fields__)
    assert {"amount", "opening_cash", "working_capital", "reconciliation", "lineage_id"}.isdisjoint(result_fields)
