from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import app.engines.cash_flow.types as cf_types

from app.engines.cash_flow import (
    CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1,
    CASH_FLOW_LINE_ITEM_MANIFEST_V1,
    CASH_FLOW_ERROR_SAFE_MESSAGE_V1,
    CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1,
    CASH_FLOW_INTEGRITY_ERROR_CODES_V1,
    CASH_FLOW_RETRYABLE_ERROR_CODES_V1,
    CASH_FLOW_MODEL_VERSION,
    CASH_FLOW_SIGN_CONVENTION_V1,
    CASH_FLOW_SCHEMA_VERSION,
    CashAvailabilityClassification,
    CashFlowAccountEvidence,
    CashFlowAccountDisposition,
    CashFlowAccountFamilyCode,
    CashFlowAccountRole,
    CashFlowAccountingBasisCode,
    CashFlowActivity,
    CashFlowActivityAllocation,
    CashFlowApplicability,
    CashFlowAvailabilityPeriodPosition,
    CashFlowBalanceSemantics,
    CashFlowCashAvailabilityDisclosure,
    CashFlowCashAvailabilityObservation,
    CashFlowCompleteness,
    CashFlowContractError,
    CashFlowDerivationCode,
    CashFlowEndpointReconciliation,
    CashFlowEndpointReconciliationStatus,
    CashFlowEngineFailure,
    CashFlowEngineOutcome,
    CashFlowErrorCode,
    CashFlowEvidenceKind,
    CashFlowEvidenceReference,
    CashFlowFamilyBalanceBasis,
    CashFlowFamilyMemberKind,
    CashFlowIssue,
    CashFlowJsonObject,
    CashFlowLineAggregationRole,
    CashFlowLineCode,
    CashFlowLineItem,
    CashFlowMethod,
    CashFlowNonCashBridgeComponent,
    CashFlowNonCashBridgeDomain,
    CashFlowNonCashBridgeKind,
    CashFlowPeriodDescriptor,
    CashFlowReconciliation,
    CashFlowReconciliationStatus,
    CashFlowResult,
    CashFlowResultStatus,
    CashFlowSourceLineageReference,
    CashFlowSourceMode,
    CashFlowSourceRole,
    CashFlowStatementBasis,
    CashFlowWarningCode,
    CashFlowZeroBalanceOmissionPolicy,
    canonical_cash_flow_bytes,
    canonical_cash_flow_digest,
    canonical_policy_bundle_digest,
    evidence_transition_allowed,
)
from app.models.enums import PeriodStatus, PeriodType


CURRENT_ID = UUID("10000000-0000-0000-0000-000000000001")
PRIOR_ID = UUID("10000000-0000-0000-0000-000000000002")
COMPANY_ID = UUID("20000000-0000-0000-0000-000000000001")
TENANT_ID = UUID("30000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("40000000-0000-0000-0000-000000000001")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _descriptor(period_id: UUID, start: date, end: date) -> CashFlowPeriodDescriptor:
    return CashFlowPeriodDescriptor(
        period_id=period_id,
        company_id=COMPANY_ID,
        tenant_id=TENANT_ID,
        currency_code="TRY",
        monetary_unit_multiplier=Decimal("1"),
        period_type=PeriodType.MONTHLY,
        start_date=start,
        end_date=end,
        annual_reporting_period_start_date=date(2025, 1, 1),
        annual_reporting_period_end_date=date(2025, 12, 31),
        months_covered=1,
        status=PeriodStatus.CLOSED,
        accounting_basis_code=CashFlowAccountingBasisCode.TR_TDHP_ACCRUAL,
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        ifrs18_early_adopted=False,
    )


def _evidence(kind: CashFlowEvidenceKind = CashFlowEvidenceKind.EXACT) -> CashFlowEvidenceReference:
    return CashFlowEvidenceReference(
        evidence_kind=kind,
        source_role=CashFlowSourceRole.CURRENT_BALANCE_SHEET,
        source_analysis_result_id=OWNER_ID,
        same_run_engine_code=None,
        source_canonical_digest=DIGEST_A,
        source_provenance_digest=DIGEST_B,
        account_codes=("100",),
        mapping_ids=("cf100",),
        derivation_code=CashFlowDerivationCode.SOURCE_VALUE,
    )


def _account_evidence() -> CashFlowAccountEvidence:
    return CashFlowAccountEvidence(
        source_role=CashFlowSourceRole.CURRENT_TRIAL_BALANCE,
        source_analysis_result_id=OWNER_ID,
        same_run_engine_code=None,
        source_canonical_digest=DIGEST_A,
        source_provenance_digest=DIGEST_B,
        account_code="100",
        canonical_account_role=CashFlowAccountRole.CASH_ON_HAND,
        account_disposition=CashFlowAccountDisposition.CASH_OR_CASH_EQUIVALENT,
        disposition_proof_digest="c" * 64,
        account_family_code=None,
        account_family_reference_digest=None,
        family_member_kind=None,
        source_balance=Decimal("10"),
        source_debit_movement=Decimal("1"),
        source_credit_movement=Decimal("2"),
        source_currency_code="TRY",
        source_unit_multiplier=Decimal("1"),
        functional_currency_code="TRY",
        normalized_functional_currency_balance=Decimal("10"),
        normalized_functional_currency_debit_movement=Decimal("1"),
        normalized_functional_currency_credit_movement=Decimal("2"),
        translation_provenance_digest=None,
        balance_semantics=CashFlowBalanceSemantics.CLOSING_BALANCE,
        as_of_date=date(2025, 2, 28),
        complete_snapshot=True,
        zero_balance_omission_policy=CashFlowZeroBalanceOmissionPolicy.EXPLICIT_ZERO_ROWS,
        maturity_days_at_acquisition=None,
        is_restricted=False,
        is_repayable_on_demand=None,
        readily_convertible_to_known_amount=None,
        insignificant_value_change_risk=None,
        held_for_short_term_cash_commitments=None,
        integral_to_cash_management=None,
        restriction_preserves_cash_nature=None,
    )


def _activity_for(code: CashFlowLineCode) -> CashFlowActivity:
    if code in {
        CashFlowLineCode.PROVEN_PPE_ACQUISITIONS,
        CashFlowLineCode.PROVEN_PPE_DISPOSALS,
        CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS,
        CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS,
        CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,
        CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT,
        CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED,
        CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED,
    }:
        return CashFlowActivity.INVESTING
    if code in {
        CashFlowLineCode.PROVEN_BORROWING_PROCEEDS,
        CashFlowLineCode.PROVEN_DEBT_REPAYMENTS,
        CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT,
        CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS,
        CashFlowLineCode.PROVEN_DIVIDENDS_PAID,
        CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID,
    }:
        return CashFlowActivity.FINANCING
    if code is CashFlowLineCode.AUTHORITATIVE_FX_EFFECT:
        return CashFlowActivity.FX_EFFECT
    if code is CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT:
        return CashFlowActivity.RECLASSIFICATION_EFFECT
    return CashFlowActivity.OPERATING


def _line(
    code: CashFlowLineCode,
    *,
    amount: Decimal | None,
    kind: CashFlowEvidenceKind,
) -> CashFlowLineItem:
    role = dict(CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1)[code]
    if amount is None:
        return CashFlowLineItem(
            line_code=code,
            canonical_amount=None,
            aggregation_role=role,
            presentation_allocations=(),
            applicability=CashFlowApplicability.UNKNOWN,
            evidence_kind=CashFlowEvidenceKind.UNAVAILABLE,
            evidence=(),
            missing_inputs=("missing_source",),
            warning_codes=(),
        )
    allocations = (
        (CashFlowActivityAllocation(activity=_activity_for(code), amount=amount),)
        if role is CashFlowLineAggregationRole.PRESENTATION_CONTRIBUTOR
        else ()
    )
    return CashFlowLineItem(
        line_code=code,
        canonical_amount=amount,
        aggregation_role=role,
        presentation_allocations=allocations,
        applicability=CashFlowApplicability.APPLICABLE,
        evidence_kind=kind,
        evidence=(_evidence(kind),),
        missing_inputs=(),
        warning_codes=(),
    )


def _warning(code: CashFlowWarningCode) -> CashFlowIssue:
    return CashFlowIssue(code=code, safe_metadata=CashFlowJsonObject(items=()))


def _result(
    *,
    status: CashFlowResultStatus = CashFlowResultStatus.COMPLETE_RECONCILED,
    reconciliation_status: CashFlowReconciliationStatus = CashFlowReconciliationStatus.RECONCILED,
    opening: Decimal | None = Decimal("0.00"),
    closing: Decimal | None = Decimal("0.00"),
    operating: Decimal | None = Decimal("0.00"),
    difference: Decimal | None = Decimal("0.00"),
    estimated_code: CashFlowLineCode | None = None,
) -> CashFlowResult:
    insufficient = status is CashFlowResultStatus.INSUFFICIENT_DATA
    amounts = {code: (None if insufficient else Decimal("0.00")) for code in CashFlowLineCode}
    if not insufficient:
        amounts.update(
            {
                CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS: opening,
                CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS: closing,
                CashFlowLineCode.OPERATING_CASH_FLOW: operating,
                CashFlowLineCode.CALCULATED_NET_CASH_CHANGE: operating,
                CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE: (
                    closing - opening if opening is not None and closing is not None else None
                ),
                CashFlowLineCode.RECONCILIATION_DIFFERENCE: difference,
                CashFlowLineCode.FREE_CASH_FLOW: operating,
            }
        )
    lines = tuple(
        _line(
            code,
            amount=amounts[code],
            kind=(CashFlowEvidenceKind.ESTIMATED if code is estimated_code else CashFlowEvidenceKind.EXACT),
        )
        for code in CashFlowLineCode
    )
    statement_kinds = [
        next(line for line in lines if line.line_code is code).evidence_kind
        for code in (
            CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS,
            CashFlowLineCode.NET_PROFIT,
            CashFlowLineCode.NON_CASH_ADJUSTMENT_TOTAL,
            CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL,
            CashFlowLineCode.OPERATING_CASH_FLOW,
            CashFlowLineCode.INVESTING_CASH_FLOW,
            CashFlowLineCode.FINANCING_CASH_FLOW,
            CashFlowLineCode.AUTHORITATIVE_FX_EFFECT,
            CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT,
            CashFlowLineCode.CALCULATED_NET_CASH_CHANGE,
            CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS,
            CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE,
            CashFlowLineCode.RECONCILIATION_DIFFERENCE,
        )
    ]
    counts = {kind: statement_kinds.count(kind) for kind in CashFlowEvidenceKind}
    available = counts[CashFlowEvidenceKind.EXACT] + counts[CashFlowEvidenceKind.DERIVED] + counts[CashFlowEvidenceKind.ESTIMATED]
    completeness = CashFlowCompleteness(
        manifest_version="1.0.0",
        required_line_count=13,
        exact_count=counts[CashFlowEvidenceKind.EXACT],
        derived_count=counts[CashFlowEvidenceKind.DERIVED],
        estimated_count=counts[CashFlowEvidenceKind.ESTIMATED],
        unavailable_count=counts[CashFlowEvidenceKind.UNAVAILABLE],
        available_ratio=(Decimal(available) / Decimal(13)).quantize(Decimal("0.0001")),
        optional_analytics_available_count=0 if insufficient else 1,
        optional_analytics_unavailable_count=1 if insufficient else 0,
    )
    current = _descriptor(CURRENT_ID, date(2025, 2, 1), date(2025, 2, 28))
    prior = None if insufficient else _descriptor(PRIOR_ID, date(2025, 1, 1), date(2025, 1, 31))
    endpoint_status = (
        CashFlowEndpointReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA
        if insufficient
        else CashFlowEndpointReconciliationStatus.MATCHED
    )
    endpoints = tuple(
        CashFlowEndpointReconciliation(
            period_position=position,
            policy_defined_cash_and_cash_equivalents=(None if insufficient else amount),
            reported_balance_sheet_cash_and_cash_equivalents=(None if insufficient else amount),
            difference=(None if insufficient else Decimal("0.00")),
            status=endpoint_status,
            balance_sheet_evidence=(() if insufficient else (_evidence(),)),
        )
        for position, amount in (
            (CashFlowAvailabilityPeriodPosition.OPENING, opening),
            (CashFlowAvailabilityPeriodPosition.CLOSING, closing),
        )
    )
    policy_versions = {
        "accounting_policy_version": "tr_tdhp_accrual/1.0.0",
        "cash_equivalent_policy_version": "1.0.0",
        "presentation_policy_version": "management/1.0.0",
        "reconciliation_policy_version": "1.0.0",
        "mapping_registry_version": "1.0.0",
    }
    warning_code = (
        CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE
        if insufficient
        else CashFlowWarningCode.ESTIMATED_NET_MOVEMENT_USED
        if estimated_code is not None
        else CashFlowWarningCode.RECONCILIATION_DIFFERENCE
        if "unreconciled" in status.value
        else None
    )
    return CashFlowResult(
        opening_cash_and_cash_equivalents=amounts[CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS],
        closing_cash_and_cash_equivalents=amounts[CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS],
        operating_cash_flow=amounts[CashFlowLineCode.OPERATING_CASH_FLOW],
        investing_cash_flow=amounts[CashFlowLineCode.INVESTING_CASH_FLOW],
        financing_cash_flow=amounts[CashFlowLineCode.FINANCING_CASH_FLOW],
        authoritative_fx_effect=amounts[CashFlowLineCode.AUTHORITATIVE_FX_EFFECT],
        authoritative_reclassification_effect=amounts[CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT],
        calculated_net_cash_change=amounts[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE],
        balance_sheet_net_cash_change=amounts[CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE],
        reconciliation_difference=amounts[CashFlowLineCode.RECONCILIATION_DIFFERENCE],
        free_cash_flow=amounts[CashFlowLineCode.FREE_CASH_FLOW],
        status=status,
        completeness=completeness,
        reconciliation_status=reconciliation_status,
        currency_code="TRY",
        monetary_scale=2,
        policy_version=canonical_policy_bundle_digest(**policy_versions),
        **policy_versions,
        current_period_id=CURRENT_ID,
        prior_period_id=None if insufficient else PRIOR_ID,
        current_period_descriptor=current,
        prior_period_descriptor=prior,
        current_period_descriptor_digest=canonical_cash_flow_digest(current),
        prior_period_descriptor_digest=None if prior is None else canonical_cash_flow_digest(prior),
        comparability_proof_digest=None if insufficient else DIGEST_A,
        line_items=lines,
        cash_availability_disclosures=(),
        endpoint_reconciliations=endpoints,
        evidence=(() if insufficient else (_evidence(),)),
        warnings=(() if warning_code is None else (_warning(warning_code),)),
        errors=(),
        source_lineage_references=(
            ()
            if insufficient
            else (
                CashFlowSourceLineageReference(
                    source_role=CashFlowSourceRole.CURRENT_BALANCE_SHEET,
                    source_analysis_result_id=OWNER_ID,
                    same_run_engine_code=None,
                    source_period_id=CURRENT_ID,
                    canonical_digest=DIGEST_A,
                    source_provenance_digest=DIGEST_B,
                ),
            )
        ),
        cash_flow_schema_version=CASH_FLOW_SCHEMA_VERSION,
        cash_flow_model_version=CASH_FLOW_MODEL_VERSION,
    )


ENUM_MANIFESTS = {
    CashFlowMethod: ["indirect"],
    CashFlowEvidenceKind: ["exact", "derived", "estimated", "unavailable"],
    CashFlowResultStatus: [
        "complete_reconciled", "complete_unreconciled", "partial_reconciled",
        "partial_unreconciled", "insufficient_data", "invalid_input", "integrity_failure",
    ],
    CashFlowReconciliationStatus: [
        "reconciled", "rounding_difference", "unreconciled_non_material",
        "unreconciled_material", "not_performed_incomplete_components",
        "not_performed_insufficient_data",
    ],
    CashFlowEndpointReconciliationStatus: ["matched", "not_performed_insufficient_data"],
    CashFlowActivity: [
        "operating", "investing", "financing", "cash_and_cash_equivalents",
        "fx_effect", "reclassification_effect", "reconciliation", "unclassified",
    ],
}

ALL_ENUM_MANIFESTS = {
    cf_types.CashAvailabilityClassification: ("unrestricted_included", "restricted_included", "restricted_excluded", "eligibility_unresolved"),
    cf_types.CashFlowAvailabilityPeriodPosition: ("opening", "closing"),
    cf_types.CashFlowLineAggregationRole: ("presentation_contributor", "subtotal", "analytic", "reconciliation"),
    cf_types.CashFlowApplicability: ("applicable", "proven_not_applicable", "unknown"),
    cf_types.CashFlowLineCode: tuple(code.value for code in CASH_FLOW_LINE_ITEM_MANIFEST_V1),
    cf_types.CashFlowSourceRole: ("current_balance_sheet", "prior_balance_sheet", "current_income_statement", "current_trial_balance", "prior_trial_balance"),
    cf_types.CashFlowSourceMode: ("direct_document", "trial_balance_derived", "multi_source_derived"),
    cf_types.CashFlowMappingMatchKind: ("exact_account_code", "longest_account_code_prefix", "explicit_account_role", "unclassified"),
    cf_types.CashFlowRoleSelectionRule: (
        "static", "bank_account_branch_v1", "cash_eligibility_branch_v1",
        "gross_or_residual_investing_v1", "gross_or_residual_financing_v1",
        "actual_cash_evidence_v1", "accrual_cash_bridge_v1", "accrual_reversal_v1",
        "restricted_reclassification_v1", "no_cash_flow_v1",
    ),
    cf_types.CashFlowAccountRole: (
        "cash_on_hand", "bank_account_candidate", "restricted_bank_asset", "demand_deposit",
        "cash_equivalent_investment", "check_receivable", "issued_check_or_payment_order",
        "other_liquid_asset_candidate", "pos_receivable", "operating_receivable", "inventory",
        "other_operating_asset", "operating_payable", "other_operating_liability", "ppe",
        "intangible_asset", "financial_investment", "equity_financial_investment",
        "long_term_financial_investment", "non_cash_investment_commitment", "borrowing", "equity",
        "non_cash_equity", "tax_payable", "tax_receivable", "interest_payable",
        "interest_receivable", "dividend_payable", "dividend_receivable",
        "interest_expense_accrual", "interest_income_accrual", "dividend_income_accrual",
        "current_tax_expense_accrual", "deferred_tax_accrual", "non_cash_adjustment", "unclassified",
    ),
    cf_types.CashFlowAccountDisposition: (
        "cash_or_cash_equivalent", "operating_working_capital", "investing_family",
        "financing_family", "pnl_captured_in_net_profit", "proven_non_cash",
        "proven_not_relevant", "unresolved",
    ),
    cf_types.CashFlowAccountFamilyCode: ("ppe_net", "intangible_net", "financial_investment_net", "borrowing_gross"),
    cf_types.CashFlowFamilyBalanceBasis: ("net_carrying_asset", "gross_liability_obligation"),
    cf_types.CashFlowFamilyMemberKind: ("asset_gross", "asset_contra", "liability_principal", "liability_contra"),
    cf_types.CashFlowNormalBalance: ("debit", "credit"),
    cf_types.CashFlowWorkingCapitalKind: ("operating_asset", "operating_liability", "not_applicable"),
    cf_types.CashEligibilityRule: ("automatic_cash", "requires_eligibility_evidence", "excluded", "not_applicable"),
    cf_types.CashFlowStatementBasis: ("as_of", "flow_interval"),
    cf_types.CashFlowAccountingBasisCode: ("tr_tdhp_accrual",),
    cf_types.CashFlowBalanceSemantics: ("closing_balance", "period_movement", "unknown"),
    cf_types.CashFlowZeroBalanceOmissionPolicy: ("explicit_zero_rows", "complete_snapshot_omits_zero", "unknown"),
    cf_types.CashFlowDerivationCode: (
        "source_value", "balance_delta", "operating_asset_sign_inversion",
        "operating_liability_sign_preserved", "net_profit_accrual_reversal",
        "indirect_operating_subtotal", "investing_subtotal", "financing_subtotal",
        "presentation_reclassification", "net_cash_change_sum", "balance_sheet_cash_delta",
        "reconciliation_difference", "free_cash_flow_from_proven_capex",
    ),
    cf_types.CashFlowNonCashBridgeDomain: ("investing_asset", "financing_debt"),
    cf_types.CashFlowNonCashBridgeKind: (
        "depreciation_or_amortization", "impairment", "revaluation", "transfer_or_reclassification",
        "disposal_gain_or_loss", "fx_or_translation", "non_cash_acquisition_or_lease_recognition",
        "lease_modification", "debt_to_equity_conversion", "capitalized_interest",
    ),
    cf_types.DependencyFailureBehavior: ("skip", "invoke_diagnostic_only"),
    cf_types.CashFlowWarningCode: (
        "minimum_data_incomplete", "account_unclassified", "cash_equivalent_eligibility_unproven",
        "non_cash_adjustment_unavailable", "gross_movement_unavailable", "estimated_net_movement_used",
        "reconciliation_difference", "material_reconciliation_difference",
        "presentation_evidence_unavailable", "negative_cash_balance", "overdraft_reclassified_to_financing",
    ),
    cf_types.CashFlowErrorCode: (
        "invalid_contract", "period_not_comparable", "period_selection_ambiguous", "source_not_found",
        "source_scope_mismatch", "source_status_invalid", "source_digest_mismatch",
        "source_currency_mismatch", "source_evidence_conflict", "policy_version_unsupported",
        "mapping_registry_version_unsupported", "mapping_conflict", "decimal_non_finite_or_scale_invalid",
        "persistence_integrity_failure", "source_resolution_unavailable", "persistence_unavailable",
    ),
}


@pytest.mark.parametrize(("enum_type", "values"), ENUM_MANIFESTS.items())
def test_exact_primary_enum_manifests(enum_type: type, values: list[str]) -> None:
    assert [member.value for member in enum_type] == values


@pytest.mark.parametrize(("enum_type", "values"), ALL_ENUM_MANIFESTS.items())
def test_all_auxiliary_enum_manifests_are_exact(enum_type: type, values: tuple[str, ...]) -> None:
    assert tuple(member.value for member in enum_type) == values


def test_line_code_and_aggregation_manifests_are_enum_exhaustive() -> None:
    assert CASH_FLOW_LINE_ITEM_MANIFEST_V1 == tuple(CashFlowLineCode)
    assert tuple(code for code, _ in CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1) == tuple(CashFlowLineCode)
    assert CASH_FLOW_SIGN_CONVENTION_V1 == "positive_inflow_negative_outflow"


def test_contract_values_are_frozen() -> None:
    descriptor = _descriptor(CURRENT_ID, date(2025, 2, 1), date(2025, 2, 28))
    with pytest.raises(FrozenInstanceError):
        descriptor.currency_code = "USD"  # type: ignore[misc]


def test_json_algebra_rejects_mutable_and_unsorted_values() -> None:
    with pytest.raises(ValueError):
        CashFlowJsonObject(items=(('b', 1), ('a', 2)))
    with pytest.raises(ValueError):
        CashFlowJsonObject(items=(("a", []),))  # type: ignore[arg-type]


def test_evidence_locator_requires_exact_xor() -> None:
    with pytest.raises(CashFlowContractError):
        replace(_evidence(), same_run_engine_code="balance_sheet")
    with pytest.raises(CashFlowContractError):
        replace(_evidence(), source_analysis_result_id=None)


def test_duplicate_evidence_reference_is_rejected() -> None:
    line = _line(CashFlowLineCode.NET_PROFIT, amount=Decimal("1.00"), kind=CashFlowEvidenceKind.EXACT)
    with pytest.raises(CashFlowContractError):
        replace(line, evidence=(line.evidence[0], line.evidence[0]))


def test_account_evidence_is_immutable_and_source_normalized() -> None:
    evidence = _account_evidence()
    assert evidence.source_balance == evidence.normalized_functional_currency_balance
    with pytest.raises(FrozenInstanceError):
        evidence.account_code = "102"  # type: ignore[misc]


def test_unresolved_account_evidence_cannot_claim_proof() -> None:
    with pytest.raises(CashFlowContractError):
        replace(
            _account_evidence(),
            account_disposition=CashFlowAccountDisposition.UNRESOLVED,
        )


def test_account_family_fields_are_all_or_none() -> None:
    with pytest.raises(CashFlowContractError):
        replace(
            _account_evidence(),
            account_family_code=CashFlowAccountFamilyCode.PPE_NET,
        )


def test_bridge_unknown_state_cannot_carry_amount() -> None:
    with pytest.raises(CashFlowContractError):
        CashFlowNonCashBridgeComponent(
            component_reference_digest="1" * 64,
            economic_event_reference_digest="2" * 64,
            account_family_reference_digest="3" * 64,
            account_family_code=CashFlowAccountFamilyCode.PPE_NET,
            family_balance_basis=CashFlowFamilyBalanceBasis.NET_CARRYING_ASSET,
            domain=CashFlowNonCashBridgeDomain.INVESTING_ASSET,
            bridge_kind=CashFlowNonCashBridgeKind.DEPRECIATION_OR_AMORTIZATION,
            source_role=CashFlowSourceRole.CURRENT_INCOME_STATEMENT,
            source_analysis_result_id=OWNER_ID,
            same_run_engine_code=None,
            source_canonical_digest=DIGEST_A,
            source_provenance_digest=DIGEST_B,
            statement_basis=CashFlowStatementBasis.FLOW_INTERVAL,
            coverage_start_date=date(2025, 2, 1),
            coverage_end_date=date(2025, 2, 28),
            applicability=CashFlowApplicability.UNKNOWN,
            evidence_kind=CashFlowEvidenceKind.UNAVAILABLE,
            source_signed_residual_adjustment=Decimal("1"),
            source_currency_code="TRY",
            source_unit_multiplier=Decimal("1"),
            functional_currency_code="TRY",
            signed_residual_adjustment=Decimal("1"),
            translation_provenance_digest=None,
            paired_transfer_reference_digest=None,
            supporting_evidence_reference_digests=(),
        )


def test_duplicate_line_code_is_rejected() -> None:
    result = _result()
    with pytest.raises(CashFlowContractError):
        replace(result, line_items=(result.line_items[0],) + result.line_items[:-1])


@pytest.mark.parametrize("bad", [1, 1.0, "1.00"])
def test_decimal_only_enforcement(bad: object) -> None:
    with pytest.raises(CashFlowContractError):
        CashFlowActivityAllocation(activity=CashFlowActivity.OPERATING, amount=bad)  # type: ignore[arg-type]


def test_negative_zero_is_normalized() -> None:
    allocation = CashFlowActivityAllocation(
        activity=CashFlowActivity.OPERATING,
        amount=Decimal("-0.00"),
    )
    assert allocation.amount == Decimal("0.00")
    assert allocation.amount.is_signed() is False


def test_unknown_line_cannot_carry_money() -> None:
    line = _line(CashFlowLineCode.NET_PROFIT, amount=Decimal("0.00"), kind=CashFlowEvidenceKind.EXACT)
    with pytest.raises(CashFlowContractError):
        replace(line, applicability=CashFlowApplicability.UNKNOWN)


def test_unclassified_allocation_is_rejected() -> None:
    with pytest.raises(CashFlowContractError):
        CashFlowActivityAllocation(activity=CashFlowActivity.UNCLASSIFIED, amount=Decimal("1.00"))


def test_wrong_fixed_sign_is_rejected() -> None:
    with pytest.raises(CashFlowContractError):
        _line(CashFlowLineCode.PROVEN_DEBT_REPAYMENTS, amount=Decimal("1.00"), kind=CashFlowEvidenceKind.EXACT)


def test_complete_reconciled_result_contract() -> None:
    result = _result()
    assert result.status is CashFlowResultStatus.COMPLETE_RECONCILED
    assert result.completeness.available_ratio == Decimal("1.0000")


def test_complete_unreconciled_result_contract() -> None:
    result = _result(
        status=CashFlowResultStatus.COMPLETE_UNRECONCILED,
        reconciliation_status=CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL,
        opening=Decimal("0.00"),
        closing=Decimal("10.00"),
        operating=Decimal("8.00"),
        difference=Decimal("2.00"),
    )
    assert result.reconciliation_difference == Decimal("2.00")


def test_partial_reconciled_result_contract() -> None:
    result = _result(
        status=CashFlowResultStatus.PARTIAL_RECONCILED,
        estimated_code=CashFlowLineCode.NET_PROFIT,
    )
    assert result.completeness.estimated_count == 1


def test_partial_unreconciled_result_contract() -> None:
    result = _result(
        status=CashFlowResultStatus.PARTIAL_UNRECONCILED,
        reconciliation_status=CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL,
        opening=Decimal("0.00"),
        closing=Decimal("10.00"),
        operating=Decimal("8.00"),
        difference=Decimal("2.00"),
        estimated_code=CashFlowLineCode.NET_PROFIT,
    )
    assert result.status is CashFlowResultStatus.PARTIAL_UNRECONCILED


def test_partial_without_estimated_or_unavailable_is_rejected() -> None:
    complete = _result()
    with pytest.raises(CashFlowContractError):
        replace(complete, status=CashFlowResultStatus.PARTIAL_RECONCILED)


def test_insufficient_data_has_no_monetary_outputs() -> None:
    result = _result(
        status=CashFlowResultStatus.INSUFFICIENT_DATA,
        reconciliation_status=CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
        opening=None,
        closing=None,
        operating=None,
        difference=None,
    )
    assert result.calculated_net_cash_change is None
    assert all(line.canonical_amount is None for line in result.line_items)


@pytest.mark.parametrize("failure_status", [CashFlowResultStatus.INVALID_INPUT, CashFlowResultStatus.INTEGRITY_FAILURE])
def test_failure_status_cannot_be_embedded_in_result(failure_status: CashFlowResultStatus) -> None:
    with pytest.raises(CashFlowContractError):
        replace(_result(), status=failure_status)


@pytest.mark.parametrize(
    ("status", "difference", "reference", "calculated"),
    [
        (CashFlowReconciliationStatus.RECONCILED, Decimal("0.00"), Decimal("10.00"), Decimal("10.00")),
        (CashFlowReconciliationStatus.ROUNDING_DIFFERENCE, Decimal("1.00"), Decimal("10.00"), Decimal("9.00")),
        (CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL, Decimal("2.00"), Decimal("10.00"), Decimal("8.00")),
        (CashFlowReconciliationStatus.UNRECONCILED_MATERIAL, Decimal("101.00"), Decimal("101.00"), Decimal("0.00")),
    ],
)
def test_reconciliation_status_matrix(
    status: CashFlowReconciliationStatus,
    difference: Decimal,
    reference: Decimal,
    calculated: Decimal,
) -> None:
    from app.engines.cash_flow import reconciliation_thresholds

    rounding, material = reconciliation_thresholds(reference)
    value = CashFlowReconciliation(
        balance_sheet_net_cash_change=reference,
        calculated_net_cash_change=calculated,
        difference=difference,
        rounding_tolerance=rounding,
        material_threshold=material,
        status=status,
    )
    assert value.status is status


def test_not_performed_reconciliation_rejects_difference() -> None:
    with pytest.raises(CashFlowContractError):
        CashFlowReconciliation(
            balance_sheet_net_cash_change=None,
            calculated_net_cash_change=None,
            difference=Decimal("0.00"),
            rounding_tolerance=None,
            material_threshold=None,
            status=CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
        )


@pytest.mark.parametrize("source", list(CashFlowEvidenceKind))
@pytest.mark.parametrize("target", list(CashFlowEvidenceKind))
def test_evidence_transition_is_monotonic(source: CashFlowEvidenceKind, target: CashFlowEvidenceKind) -> None:
    ranks = {kind: index for index, kind in enumerate(CashFlowEvidenceKind)}
    assert evidence_transition_allowed(source, target) is (ranks[target] >= ranks[source])


def test_cash_availability_disclosure_requires_opening_then_closing() -> None:
    observation = CashFlowCashAvailabilityObservation(
        period_position=CashFlowAvailabilityPeriodPosition.OPENING,
        classification=CashAvailabilityClassification.UNRESTRICTED_INCLUDED,
        amount=Decimal("0.00"),
        restriction_preserves_cash_nature=False,
        evidence=(_evidence(),),
    )
    with pytest.raises(CashFlowContractError):
        CashFlowCashAvailabilityDisclosure(
            component_reference_digest=DIGEST_A,
            account_role=CashFlowAccountRole.CASH_ON_HAND,
            observations=(observation,),
        )


def test_result_rejects_currency_and_scale_mismatch() -> None:
    result = _result()
    with pytest.raises(CashFlowContractError):
        replace(result, currency_code="USD")
    with pytest.raises(CashFlowContractError):
        replace(result, monetary_scale=3)


def test_result_rejects_summary_projection_mismatch() -> None:
    with pytest.raises(CashFlowContractError):
        replace(_result(), operating_cash_flow=Decimal("1.00"))


def test_engine_outcome_discriminator() -> None:
    result = _result()
    assert CashFlowEngineOutcome(
        status=result.status, success=True, value=result, error=None
    ).value is result
    failure = CashFlowEngineFailure(CashFlowErrorCode.INVALID_CONTRACT)
    assert CashFlowEngineOutcome(
        status=CashFlowResultStatus.INVALID_INPUT,
        success=False,
        value=None,
        error=failure,
    ).error is failure


def test_integrity_failure_outcome_has_no_result_payload() -> None:
    failure = CashFlowEngineFailure(CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT)
    outcome = CashFlowEngineOutcome(
        status=CashFlowResultStatus.INTEGRITY_FAILURE,
        success=False,
        value=None,
        error=failure,
    )
    assert outcome.value is None


def test_failure_status_and_error_category_cannot_cross() -> None:
    with pytest.raises(CashFlowContractError):
        CashFlowEngineOutcome(
            status=CashFlowResultStatus.INVALID_INPUT,
            success=False,
            value=None,
            error=CashFlowEngineFailure(CashFlowErrorCode.SOURCE_DIGEST_MISMATCH),
        )


def test_error_manifests_are_exhaustive_and_disjoint() -> None:
    assert set(CASH_FLOW_ERROR_SAFE_MESSAGE_V1) == set(CashFlowErrorCode)
    assert CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1.isdisjoint(CASH_FLOW_INTEGRITY_ERROR_CODES_V1)
    assert CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1 | CASH_FLOW_INTEGRITY_ERROR_CODES_V1 == set(CashFlowErrorCode)
    assert CASH_FLOW_RETRYABLE_ERROR_CODES_V1 == {
        CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE,
        CashFlowErrorCode.PERSISTENCE_UNAVAILABLE,
    }


@pytest.mark.parametrize("code", list(CashFlowErrorCode))
def test_every_engine_failure_has_safe_derived_metadata(code: CashFlowErrorCode) -> None:
    failure = CashFlowEngineFailure(code)
    assert failure.safe_message == CASH_FLOW_ERROR_SAFE_MESSAGE_V1[code]
    assert failure.safe_metadata == CashFlowJsonObject(items=())
    assert failure.retryable is (code in CASH_FLOW_RETRYABLE_ERROR_CODES_V1)


def test_engine_failure_is_immutable_final_and_safe() -> None:
    failure = CashFlowEngineFailure(CashFlowErrorCode.SOURCE_DIGEST_MISMATCH)
    with pytest.raises(AttributeError):
        failure._code = CashFlowErrorCode.SOURCE_NOT_FOUND  # type: ignore[misc]
    with pytest.raises(TypeError):
        class BadFailure(CashFlowEngineFailure):
            pass
    assert DIGEST_A not in repr(failure)
    assert "source_digest_mismatch" in str(failure)


def test_safe_repr_omits_identifiers_and_payload_values() -> None:
    evidence = _evidence()
    assert str(OWNER_ID) not in repr(evidence)
    assert DIGEST_A not in repr(evidence)
    assert "100" not in repr(evidence)


def test_canonical_serialization_and_digest_are_deterministic() -> None:
    first = _result()
    second = _result()
    assert canonical_cash_flow_bytes(first) == canonical_cash_flow_bytes(second)
    assert canonical_cash_flow_digest(first) == canonical_cash_flow_digest(second)
    assert len(canonical_cash_flow_digest(first)) == 64


def test_canonical_digest_changes_on_field_mutation() -> None:
    descriptor = _descriptor(CURRENT_ID, date(2025, 2, 1), date(2025, 2, 28))
    changed = replace(descriptor, months_covered=2)
    assert canonical_cash_flow_digest(descriptor) != canonical_cash_flow_digest(changed)


def test_canonical_serializer_rejects_mutable_payloads_and_float() -> None:
    with pytest.raises(CashFlowContractError):
        canonical_cash_flow_bytes({"amount": Decimal("1")})
    with pytest.raises(CashFlowContractError):
        canonical_cash_flow_bytes(1.0)


def test_cash_flow_package_has_no_forbidden_framework_imports() -> None:
    package = Path(__file__).parents[1] / "app" / "engines" / "cash_flow"
    forbidden = {"sqlalchemy", "fastapi", "pydantic"}
    for source_file in package.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported.isdisjoint(forbidden), source_file


def test_cash_flow_contract_does_not_store_raw_source_payload_types() -> None:
    result = _result()
    assert b"raw_payload" not in canonical_cash_flow_bytes(result)
    assert not any(field.name in {"raw_payload", "raw_document", "raw_exception"} for field in result.__dataclass_fields__.values())
