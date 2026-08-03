"""Pure comparable-period and source-role resolution for Milestone 4.5C."""

from __future__ import annotations

from datetime import timedelta
from hmac import compare_digest

from app.models.enums import AnalysisStatus, AnalysisType, PeriodCoverageKind, PeriodStatus, PeriodType

from .contracts import CashFlowIssue
from .errors import CashFlowEngineFailure
from .policy import CASH_FLOW_ACCOUNTING_POLICY_VERSION, CASH_FLOW_MAPPING_REGISTRY_VERSION, CashFlowPresentationProfile
from .resolution_contracts import (
    CASH_FLOW_PERIOD_RESOLUTION_POLICY_VERSION,
    CashFlowComparabilityRow,
    CashFlowInputResolutionOutcome,
    CashFlowInputResolutionResult,
    CashFlowInputResolutionStatus,
    CashFlowPeriodResolutionRequest,
    CashFlowResolutionRepositoryError,
    CashFlowResolutionSnapshot,
    CashFlowResolvedPeriod,
    CashFlowResolvedSource,
    ComparablePeriodRepositoryPort,
    canonical_resolution_digest,
)
from .types import (
    CashFlowAccountingBasisCode,
    CashFlowErrorCode,
    CashFlowJsonObject,
    CashFlowSourceRole,
    CashFlowWarningCode,
)


CASH_FLOW_REQUIRED_SOURCE_ROLES_V1 = tuple(CashFlowSourceRole)

_ROLE_ANALYSIS_TYPE = {
    CashFlowSourceRole.CURRENT_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.PRIOR_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.CURRENT_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    CashFlowSourceRole.CURRENT_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    CashFlowSourceRole.PRIOR_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
}
_PRIOR_ROLES = {
    CashFlowSourceRole.PRIOR_BALANCE_SHEET,
    CashFlowSourceRole.PRIOR_TRIAL_BALANCE,
}


def _failure(code: CashFlowErrorCode) -> CashFlowInputResolutionOutcome:
    return CashFlowInputResolutionOutcome(False, None, CashFlowEngineFailure(code))


def _minimum_warning() -> tuple[CashFlowIssue, ...]:
    return (
        CashFlowIssue(
            code=CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE,
            safe_metadata=CashFlowJsonObject(items=()),
        ),
    )


def _period_digest(period: CashFlowResolvedPeriod) -> str:
    return canonical_resolution_digest("cash-flow/period-descriptor/v1", period)


def _metadata_compatible(current: CashFlowResolvedPeriod, prior: CashFlowResolvedPeriod) -> bool:
    return (
        current.tenant_id == prior.tenant_id
        and current.company_id == prior.company_id
        and current.currency_code == prior.currency_code
        and current.accounting_basis_code == prior.accounting_basis_code
        and current.accounting_policy_version == prior.accounting_policy_version
        and current.ifrs18_early_adopted == prior.ifrs18_early_adopted
    )


def _compatibility_row(
    current: CashFlowResolvedPeriod,
    prior: CashFlowResolvedPeriod,
) -> CashFlowComparabilityRow | None:
    if not current.metadata_complete or not prior.metadata_complete:
        return None
    if current.status is not PeriodStatus.CLOSED or prior.status is not PeriodStatus.CLOSED:
        return None
    if not _metadata_compatible(current, prior):
        return None
    if prior.end_date >= current.end_date or prior.end_date + timedelta(days=1) != current.start_date:
        return None
    first_fiscal = current.start_date == current.annual_reporting_period_start_date

    if current.period_type is PeriodType.YEAR_END:
        if (
            current.coverage_kind is PeriodCoverageKind.CUMULATIVE
            and current.start_date == current.annual_reporting_period_start_date
            and current.end_date == current.annual_reporting_period_end_date
            and prior.period_type is PeriodType.YEAR_END
            and prior.coverage_kind is PeriodCoverageKind.CUMULATIVE
        ):
            return CashFlowComparabilityRow.ANNUAL
        return None
    if current.period_type is PeriodType.MONTHLY:
        if current.coverage_kind is not PeriodCoverageKind.DISCRETE or current.months_covered != 1:
            return None
        if first_fiscal and prior.period_type is PeriodType.YEAR_END:
            return CashFlowComparabilityRow.FIRST_FISCAL_MONTH
        if not first_fiscal and prior.period_type is PeriodType.MONTHLY:
            return CashFlowComparabilityRow.MONTHLY_DISCRETE
        return None
    if current.period_type is PeriodType.QUARTER:
        if current.coverage_kind is PeriodCoverageKind.DISCRETE:
            if current.months_covered != 3:
                return None
            if first_fiscal and prior.period_type is PeriodType.YEAR_END:
                return CashFlowComparabilityRow.FIRST_FISCAL_QUARTER
            if not first_fiscal and prior.period_type is PeriodType.QUARTER:
                return CashFlowComparabilityRow.QUARTER_DISCRETE
            return None
        if (
            current.coverage_kind is PeriodCoverageKind.CUMULATIVE
            and first_fiscal
            and current.months_covered in {3, 6, 9}
            and prior.period_type is PeriodType.YEAR_END
        ):
            return CashFlowComparabilityRow.QUARTER_CUMULATIVE
        return None
    if current.period_type is PeriodType.TEMPORARY_TAX:
        if (
            current.coverage_kind is PeriodCoverageKind.CUMULATIVE
            and first_fiscal
            and prior.period_type is PeriodType.YEAR_END
        ):
            return CashFlowComparabilityRow.TEMPORARY_TAX_CUMULATIVE
        return None
    if current.period_type is PeriodType.CUSTOM:
        if prior.period_type is PeriodType.CUSTOM and prior.coverage_kind is current.coverage_kind:
            return CashFlowComparabilityRow.CUSTOM
    return None


def select_comparable_period(
    request: CashFlowPeriodResolutionRequest,
    snapshot: CashFlowResolutionSnapshot,
) -> tuple[CashFlowResolvedPeriod | None, CashFlowComparabilityRow | None, CashFlowErrorCode | None]:
    current = snapshot.current_period
    if current.period_id != request.current_period_id or current.company_id != request.company_id or current.tenant_id != request.tenant_id:
        return None, None, CashFlowErrorCode.SOURCE_SCOPE_MISMATCH
    if current.status is not PeriodStatus.CLOSED:
        return None, None, CashFlowErrorCode.PERIOD_NOT_COMPARABLE
    if not current.metadata_complete:
        return None, None, None
    if current.currency_code != request.expected_currency:
        return None, None, CashFlowErrorCode.SOURCE_CURRENCY_MISMATCH
    if (
        current.accounting_basis_code is not request.expected_accounting_basis
        or current.accounting_policy_version != request.expected_accounting_policy_version
    ):
        return None, None, CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED
    if request.expected_mapping_registry_version != CASH_FLOW_MAPPING_REGISTRY_VERSION:
        return None, None, CashFlowErrorCode.MAPPING_REGISTRY_VERSION_UNSUPPORTED
    if request.expected_accounting_policy_version != CASH_FLOW_ACCOUNTING_POLICY_VERSION:
        return None, None, CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED
    if (
        request.expected_presentation_profile is CashFlowPresentationProfile.TMS_TFRS_2024_INDIRECT_V1
        and (
            current.annual_reporting_period_start_date.year >= 2027
            or current.ifrs18_early_adopted is True
        )
    ):
        return None, None, CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED

    eligible = tuple(
        (candidate, row)
        for candidate in snapshot.prior_candidates
        if (row := _compatibility_row(current, candidate)) is not None
    )
    if request.explicit_prior_period_id is not None:
        claimed = tuple(item for item in snapshot.prior_candidates if item.period_id == request.explicit_prior_period_id)
        if not claimed:
            return None, None, CashFlowErrorCode.SOURCE_NOT_FOUND
        if len(eligible) != 1 or eligible[0][0].period_id != request.explicit_prior_period_id:
            return None, None, CashFlowErrorCode.PERIOD_NOT_COMPARABLE
    if len(eligible) > 1:
        return None, None, CashFlowErrorCode.PERIOD_SELECTION_AMBIGUOUS
    if len(eligible) == 1:
        return eligible[0][0], eligible[0][1], None
    if snapshot.prior_candidates:
        return None, None, CashFlowErrorCode.PERIOD_NOT_COMPARABLE
    return None, None, None


def _select_sources(
    request: CashFlowPeriodResolutionRequest,
    snapshot: CashFlowResolutionSnapshot,
    prior: CashFlowResolvedPeriod,
) -> tuple[tuple[CashFlowResolvedSource, ...], tuple[CashFlowSourceRole, ...], CashFlowErrorCode | None]:
    selected: list[CashFlowResolvedSource] = []
    missing: list[CashFlowSourceRole] = []
    for role in request.required_source_roles:
        period_id = prior.period_id if role in _PRIOR_ROLES else request.current_period_id
        candidates = tuple(
            source for source in snapshot.source_candidates
            if source.source_role is role and source.period_id == period_id
        )
        if not candidates:
            missing.append(role)
            continue
        if len(candidates) != 1:
            return (), (), CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT
        source = candidates[0]
        if source.company_id != request.company_id:
            return (), (), CashFlowErrorCode.SOURCE_SCOPE_MISMATCH
        if source.analysis_type is not _ROLE_ANALYSIS_TYPE[role]:
            return (), (), CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT
        if source.status is not AnalysisStatus.COMPLETED:
            return (), (), CashFlowErrorCode.SOURCE_STATUS_INVALID
        if not source.digest_verified or not compare_digest(source.canonical_digest, source.recomputed_payload_digest):
            return (), (), CashFlowErrorCode.SOURCE_DIGEST_MISMATCH
        selected.append(source)
    return tuple(selected), tuple(missing), None


def _insufficient(
    request: CashFlowPeriodResolutionRequest,
    snapshot: CashFlowResolutionSnapshot,
    missing_roles: tuple[CashFlowSourceRole, ...],
    sources: tuple[CashFlowResolvedSource, ...] = (),
) -> CashFlowInputResolutionOutcome:
    projection = (
        CashFlowInputResolutionStatus.INSUFFICIENT_DATA.value,
        request.tenant_id,
        request.company_id,
        request.current_period_id,
        snapshot.candidate_set_digest,
        tuple(role.value for role in missing_roles),
    )
    result = CashFlowInputResolutionResult(
        status=CashFlowInputResolutionStatus.INSUFFICIENT_DATA,
        tenant_id=request.tenant_id,
        company_id=request.company_id,
        current_period_id=request.current_period_id,
        prior_period_id=None,
        current_period=snapshot.current_period,
        prior_period=None,
        sources=sources,
        comparability_row=None,
        comparability_proof_digest=None,
        missing_source_roles=missing_roles,
        warnings=_minimum_warning(),
        errors=(),
        candidate_set_digest=snapshot.candidate_set_digest,
        resolution_policy_version=CASH_FLOW_PERIOD_RESOLUTION_POLICY_VERSION,
        resolution_digest=canonical_resolution_digest("cash-flow/input-resolution/v1", projection),
    )
    return CashFlowInputResolutionOutcome(True, result, None)


def resolve_snapshot(
    request: CashFlowPeriodResolutionRequest,
    snapshot: CashFlowResolutionSnapshot,
) -> CashFlowInputResolutionOutcome:
    prior, row, period_error = select_comparable_period(request, snapshot)
    if period_error is not None:
        return _failure(period_error)
    if prior is None or row is None:
        return _insufficient(request, snapshot, tuple(
            role for role in request.required_source_roles if role in _PRIOR_ROLES
        ))
    sources, missing, source_error = _select_sources(request, snapshot, prior)
    if source_error is not None:
        return _failure(source_error)
    if missing:
        return _insufficient(request, snapshot, missing, sources)
    source_by_role = {source.source_role: source for source in sources}
    comparability_projection = (
        CASH_FLOW_PERIOD_RESOLUTION_POLICY_VERSION,
        _period_digest(snapshot.current_period),
        _period_digest(prior),
        prior.end_date,
        snapshot.current_period.start_date,
        snapshot.current_period.end_date,
        snapshot.current_period.end_date,
        source_by_role[CashFlowSourceRole.CURRENT_INCOME_STATEMENT].canonical_digest,
        source_by_role[CashFlowSourceRole.CURRENT_BALANCE_SHEET].canonical_digest,
        source_by_role[CashFlowSourceRole.PRIOR_BALANCE_SHEET].canonical_digest,
        row.value,
    )
    proof = canonical_resolution_digest("cash-flow/comparability-proof/v1", comparability_projection)
    resolution_projection = (
        request.tenant_id,
        request.company_id,
        request.current_period_id,
        prior.period_id,
        tuple((source.source_role.value, source.analysis_result_id, source.canonical_digest) for source in sources),
        proof,
        snapshot.candidate_set_digest,
        CASH_FLOW_PERIOD_RESOLUTION_POLICY_VERSION,
    )
    result = CashFlowInputResolutionResult(
        status=CashFlowInputResolutionStatus.RESOLVED,
        tenant_id=request.tenant_id,
        company_id=request.company_id,
        current_period_id=request.current_period_id,
        prior_period_id=prior.period_id,
        current_period=snapshot.current_period,
        prior_period=prior,
        sources=sources,
        comparability_row=row,
        comparability_proof_digest=proof,
        missing_source_roles=(),
        warnings=(),
        errors=(),
        candidate_set_digest=snapshot.candidate_set_digest,
        resolution_policy_version=CASH_FLOW_PERIOD_RESOLUTION_POLICY_VERSION,
        resolution_digest=canonical_resolution_digest("cash-flow/input-resolution/v1", resolution_projection),
    )
    return CashFlowInputResolutionOutcome(True, result, None)


class CashFlowMultiPeriodInputResolver:
    def __init__(self, repository: ComparablePeriodRepositoryPort) -> None:
        self._repository = repository

    def resolve(self, request: CashFlowPeriodResolutionRequest) -> CashFlowInputResolutionOutcome:
        try:
            snapshot = self._repository.load_resolution_snapshot(request)
        except CashFlowResolutionRepositoryError as exc:
            return _failure(exc.code)
        return resolve_snapshot(request, snapshot)
