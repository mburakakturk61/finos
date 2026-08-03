"""Trusted pre-run Cash Flow resolution used before pure V3 orchestration."""

from __future__ import annotations

from app.engines.cash_flow.contracts import CashFlowPreResolvedContext

from .contracts import CashFlowRequestDTOV2
from .ports import (
    CashFlowSourceResolverPort,
    ComparablePeriodResolutionStatus,
    ComparablePeriodResolverPort,
    VerifiedTenantScopeV3,
)


def resolve_cash_flow_pre_run_context_v2(
    request: CashFlowRequestDTOV2,
    verified_scope: VerifiedTenantScopeV3,
    *,
    comparable_periods: ComparablePeriodResolverPort,
    cash_flow_sources: CashFlowSourceResolverPort,
) -> CashFlowPreResolvedContext:
    """Resolve authoritative period/source state; caller IDs never select owners."""

    period = comparable_periods.resolve_exact_prior_period(
        tenant_id=verified_scope.tenant_id,
        company_id=verified_scope.company_id,
        current_period_id=request.current_period_id,
        required_currency_code="TRY",
        accounting_basis_code="tr_tdhp_accrual",
        accounting_policy_version=request.accounting_policy_version,
    )
    if period.current_period.period_id != request.current_period_id:
        raise ValueError("trusted current-period resolution differs from request")
    prior = period.prior_period if period.status is ComparablePeriodResolutionStatus.EXACT_MATCH else None
    if request.expected_prior_period_id is not None and (
        prior is None or prior.period_id != request.expected_prior_period_id
    ):
        raise ValueError("resolved prior period differs from caller assertion")
    sources = cash_flow_sources.resolve_pre_run_sources(
        tenant_id=verified_scope.tenant_id,
        company_id=verified_scope.company_id,
        current_period_id=request.current_period_id,
        prior_period_id=prior.period_id if prior else None,
    )
    return CashFlowPreResolvedContext(
        current_period=period.current_period,
        prior_period=prior,
        prior_balance_sheet=sources.prior_balance_sheet,
        current_trial_balance=sources.current_trial_balance,
        prior_trial_balance=sources.prior_trial_balance,
        account_evidence=sources.account_evidence,
        noncash_bridge_components=sources.noncash_bridge_components,
        pre_resolved_evidence_bundle_digest=sources.pre_resolved_evidence_bundle_digest,
        source_candidate_set_digest=sources.source_candidate_set_digest,
        opening_account_coverage_complete=sources.opening_account_coverage_complete,
        closing_account_coverage_complete=sources.closing_account_coverage_complete,
        comparability_proof_digest=period.comparability_proof_digest,
        mapping_registry_version=request.mapping_registry_version,
        accounting_policy_version=request.accounting_policy_version,
        presentation_policy=_presentation_policy(request),
    )


def _presentation_policy(request):
    from app.engines.cash_flow.policy import CashFlowPresentationProfile
    from app.engines.cash_flow.policy import presentation_policy_for

    return presentation_policy_for(CashFlowPresentationProfile(request.presentation_profile.value))
