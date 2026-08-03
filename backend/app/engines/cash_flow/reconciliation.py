"""Pure reconciliation and final CashFlowResult assembly for Milestone 4.5E."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from .calculation import (
    CashFlowCoreIntegrityError,
    canonical_references,
    exact_subtract,
    exact_sum,
    finalized_sum,
    weakest_evidence,
)
from .contracts import (
    CashFlowComputationDraft,
    CashFlowEndpointReconciliation,
    CashFlowEvidenceReference,
    CashFlowIssue,
    CashFlowLineItem,
    CashFlowReconciliation,
    CashFlowResult,
    CashFlowSourceSnapshot,
    IndirectCashFlowInput,
    canonical_cash_flow_digest,
)
from .errors import CashFlowContractError
from .policy import reconciliation_thresholds
from .quality import assess_data_quality, build_completeness
from .types import (
    CASH_FLOW_CURRENCY_CODE_V1,
    CASH_FLOW_LINE_ITEM_MANIFEST_V1,
    CASH_FLOW_MODEL_VERSION,
    CASH_FLOW_MONETARY_SCALE_V1,
    CASH_FLOW_SCHEMA_VERSION,
    CashFlowApplicability,
    CashFlowAvailabilityPeriodPosition,
    CashFlowDerivationCode,
    CashFlowEndpointReconciliationStatus,
    CashFlowEvidenceKind,
    CashFlowJsonObject,
    CashFlowLineCode,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
    CashFlowSourceRole,
    CashFlowWarningCode,
)


class CashFlowFinalizationIntegrityError(CashFlowCoreIntegrityError):
    """Safe internal signal for contradictory draft/finalization evidence."""


def cash_flow_result_digest(result: CashFlowResult) -> str:
    if type(result) is not CashFlowResult:
        raise CashFlowContractError("CashFlowResult is required")
    return canonical_cash_flow_digest(result)


def _issue(code: CashFlowWarningCode) -> CashFlowIssue:
    return CashFlowIssue(code=code, safe_metadata=CashFlowJsonObject(items=()))


def _canonical_issues(issues: tuple[CashFlowIssue, ...]) -> tuple[CashFlowIssue, ...]:
    keyed = {canonical_cash_flow_digest(issue): issue for issue in issues}
    return tuple(keyed[key] for key in sorted(keyed))


def _union_evidence(*groups: tuple[CashFlowEvidenceReference, ...]) -> tuple[CashFlowEvidenceReference, ...]:
    keyed = {
        canonical_cash_flow_digest(reference): reference
        for group in groups
        for reference in group
    }
    return tuple(keyed[key] for key in sorted(keyed))


def _source_reference(source: CashFlowSourceSnapshot) -> CashFlowEvidenceReference:
    return CashFlowEvidenceReference(
        evidence_kind=CashFlowEvidenceKind.EXACT,
        source_role=source.source_role,
        source_analysis_result_id=source.analysis_result_id,
        same_run_engine_code=source.same_run_engine_code,
        source_canonical_digest=source.canonical_digest,
        source_provenance_digest=source.source_provenance_digest,
        account_codes=(),
        mapping_ids=(),
        derivation_code=CashFlowDerivationCode.SOURCE_VALUE,
    )


def _source_money(source: CashFlowSourceSnapshot | None, key: str) -> Decimal | None:
    if source is None:
        return None
    value = dict(source.result_payload.items).get(key)
    if value is None:
        return None
    if type(value) is not Decimal:
        raise CashFlowContractError("balance-sheet cash projection must be Decimal")
    return finalized_sum((value,))


def _endpoint(
    *,
    position: CashFlowAvailabilityPeriodPosition,
    source: CashFlowSourceSnapshot | None,
    policy_amount: Decimal | None,
) -> CashFlowEndpointReconciliation:
    reported = _source_money(source, "cash_and_equivalents")
    evidence = () if source is None else canonical_references((_source_reference(source),))
    if reported is not None and policy_amount is not None and reported != policy_amount:
        raise CashFlowFinalizationIntegrityError("balance-sheet cash endpoint mismatch")
    matched = reported is not None and policy_amount is not None
    return CashFlowEndpointReconciliation(
        period_position=position,
        policy_defined_cash_and_cash_equivalents=policy_amount,
        reported_balance_sheet_cash_and_cash_equivalents=reported,
        difference=Decimal("0.00") if matched else None,
        status=(
            CashFlowEndpointReconciliationStatus.MATCHED
            if matched
            else CashFlowEndpointReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA
        ),
        balance_sheet_evidence=evidence,
    )


def evaluate_reconciliation(
    balance_sheet_net_cash_change: Decimal | None,
    calculated_net_cash_change: Decimal | None,
    *,
    insufficient: bool = False,
) -> CashFlowReconciliation:
    if insufficient:
        return CashFlowReconciliation(
            balance_sheet_net_cash_change,
            calculated_net_cash_change,
            None,
            None,
            None,
            CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
        )
    if balance_sheet_net_cash_change is None or calculated_net_cash_change is None:
        return CashFlowReconciliation(
            balance_sheet_net_cash_change,
            calculated_net_cash_change,
            None,
            None,
            None,
            CashFlowReconciliationStatus.NOT_PERFORMED_INCOMPLETE_COMPONENTS,
        )
    difference = exact_subtract(balance_sheet_net_cash_change, calculated_net_cash_change)
    rounding, material = reconciliation_thresholds(balance_sheet_net_cash_change)
    absolute = difference.copy_abs()
    if absolute == 0:
        status = CashFlowReconciliationStatus.RECONCILED
    elif absolute <= rounding:
        status = CashFlowReconciliationStatus.ROUNDING_DIFFERENCE
    elif absolute <= material:
        status = CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL
    else:
        status = CashFlowReconciliationStatus.UNRECONCILED_MATERIAL
    return CashFlowReconciliation(
        balance_sheet_net_cash_change,
        calculated_net_cash_change,
        difference,
        rounding,
        material,
        status,
    )


def _derived_line(
    base: CashFlowLineItem,
    amount: Decimal,
    contributors: tuple[CashFlowLineItem, ...],
    *,
    warning: CashFlowWarningCode | None = None,
) -> CashFlowLineItem:
    kind = weakest_evidence(tuple(item.evidence_kind for item in contributors))
    if kind is CashFlowEvidenceKind.EXACT:
        kind = CashFlowEvidenceKind.DERIVED
    evidence = _union_evidence(*(item.evidence for item in contributors))
    warning_codes = () if warning is None else (warning,)
    return replace(
        base,
        canonical_amount=amount,
        presentation_allocations=(),
        applicability=CashFlowApplicability.APPLICABLE,
        evidence_kind=kind,
        evidence=evidence,
        missing_inputs=(),
        warning_codes=warning_codes,
    )


def _missing_line(base: CashFlowLineItem, reason: str) -> CashFlowLineItem:
    return replace(
        base,
        canonical_amount=None,
        presentation_allocations=(),
        applicability=CashFlowApplicability.UNKNOWN,
        evidence_kind=CashFlowEvidenceKind.UNAVAILABLE,
        evidence=(),
        missing_inputs=(reason,),
        warning_codes=(),
    )


def _all_missing(lines: dict[CashFlowLineCode, CashFlowLineItem]) -> dict[CashFlowLineCode, CashFlowLineItem]:
    return {
        code: _missing_line(lines[code], "minimum_data")
        for code in CASH_FLOW_LINE_ITEM_MANIFEST_V1
    }


def _validate_finalization_inputs(
    draft: CashFlowComputationDraft,
    inputs: IndirectCashFlowInput,
) -> None:
    if type(draft) is not CashFlowComputationDraft or type(inputs) is not IndirectCashFlowInput:
        raise CashFlowContractError("cash-flow draft and input are required")
    if draft.current_period != inputs.current_period or draft.prior_period != inputs.prior_period:
        raise CashFlowFinalizationIntegrityError("draft period binding mismatch")
    version_pairs = (
        (draft.accounting_policy_version, inputs.accounting_policy_version),
        (draft.mapping_registry_version, inputs.mapping_registry_version),
        (draft.presentation_policy_version, inputs.presentation_policy.policy_version),
    )
    if any(left != right for left, right in version_pairs):
        raise CashFlowFinalizationIntegrityError("draft policy/version binding mismatch")


def finalize_cash_flow_result(
    *,
    draft: CashFlowComputationDraft,
    inputs: IndirectCashFlowInput,
    comparability_proof_digest: str | None,
) -> CashFlowResult:
    """Finalize one validated draft; the proof is trusted 4.5C internal output."""

    _validate_finalization_inputs(draft, inputs)
    lines = {item.line_code: item for item in draft.line_items}
    opening_endpoint = _endpoint(
        position=CashFlowAvailabilityPeriodPosition.OPENING,
        source=inputs.prior_balance_sheet,
        policy_amount=lines[CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS].canonical_amount,
    )
    closing_endpoint = _endpoint(
        position=CashFlowAvailabilityPeriodPosition.CLOSING,
        source=inputs.current_balance_sheet,
        policy_amount=lines[CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS].canonical_amount,
    )
    endpoints = (opening_endpoint, closing_endpoint)
    minimum_warning = any(
        issue.code is CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE
        for issue in draft.warnings
    )
    endpoint_incomplete = any(
        item.status is CashFlowEndpointReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA
        for item in endpoints
    )
    required_sources = (
        inputs.current_balance_sheet,
        inputs.prior_balance_sheet,
        inputs.current_income_statement,
        inputs.current_trial_balance,
        inputs.prior_trial_balance,
    )
    insufficient = (
        minimum_warning
        or inputs.prior_period is None
        or any(source is None for source in required_sources)
        or endpoint_incomplete
        or lines[CashFlowLineCode.NET_PROFIT].canonical_amount is None
    )
    if insufficient:
        lines = _all_missing(lines)
        endpoints = tuple(
            replace(
                endpoint,
                difference=None,
                status=CashFlowEndpointReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
            )
            for endpoint in endpoints
        )
        reconciliation = evaluate_reconciliation(None, None, insufficient=True)
        warnings = _canonical_issues(draft.warnings + (_issue(CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE),))
        status = CashFlowResultStatus.INSUFFICIENT_DATA
        prior_period_id = None
        prior_period = None
        prior_digest = None
        proof = None
    else:
        if comparability_proof_digest is None:
            raise CashFlowFinalizationIntegrityError("resolved input requires comparability proof")
        activity_codes = (
            CashFlowLineCode.OPERATING_CASH_FLOW,
            CashFlowLineCode.INVESTING_CASH_FLOW,
            CashFlowLineCode.FINANCING_CASH_FLOW,
            CashFlowLineCode.AUTHORITATIVE_FX_EFFECT,
            CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT,
        )
        activity_lines = tuple(lines[code] for code in activity_codes)
        if all(item.canonical_amount is not None for item in activity_lines):
            lines[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE] = _derived_line(
                lines[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE],
                exact_sum(tuple(item.canonical_amount for item in activity_lines)),
                activity_lines,
            )
        else:
            lines[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE] = _missing_line(
                lines[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE],
                "complete_activity_and_effect_components",
            )
        balance_line = lines[CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE]
        calculated_line = lines[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE]
        reconciliation = evaluate_reconciliation(
            balance_line.canonical_amount,
            calculated_line.canonical_amount,
        )
        warning = None
        if reconciliation.status in {
            CashFlowReconciliationStatus.ROUNDING_DIFFERENCE,
            CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL,
        }:
            warning = CashFlowWarningCode.RECONCILIATION_DIFFERENCE
        elif reconciliation.status is CashFlowReconciliationStatus.UNRECONCILED_MATERIAL:
            warning = CashFlowWarningCode.MATERIAL_RECONCILIATION_DIFFERENCE
        if reconciliation.difference is None:
            lines[CashFlowLineCode.RECONCILIATION_DIFFERENCE] = _missing_line(
                lines[CashFlowLineCode.RECONCILIATION_DIFFERENCE],
                "calculated_and_balance_sheet_net_cash_change",
            )
        else:
            lines[CashFlowLineCode.RECONCILIATION_DIFFERENCE] = _derived_line(
                lines[CashFlowLineCode.RECONCILIATION_DIFFERENCE],
                reconciliation.difference,
                (balance_line, calculated_line),
                warning=warning,
            )
        warnings = draft.warnings
        if reconciliation.status is CashFlowReconciliationStatus.NOT_PERFORMED_INCOMPLETE_COMPONENTS:
            warnings += (_issue(CashFlowWarningCode.PRESENTATION_EVIDENCE_UNAVAILABLE),)
        if warning is not None:
            warnings += (_issue(warning),)
        warnings += tuple(
            _issue(code)
            for item in lines.values()
            for code in item.warning_codes
        )
        warnings = _canonical_issues(warnings)
        completeness = build_completeness(tuple(lines[code] for code in CASH_FLOW_LINE_ITEM_MANIFEST_V1))
        complete = not completeness.estimated_count and not completeness.unavailable_count
        reconciled = reconciliation.status in {
            CashFlowReconciliationStatus.RECONCILED,
            CashFlowReconciliationStatus.ROUNDING_DIFFERENCE,
        }
        status = (
            CashFlowResultStatus.COMPLETE_RECONCILED
            if complete and reconciled
            else CashFlowResultStatus.COMPLETE_UNRECONCILED
            if complete
            else CashFlowResultStatus.PARTIAL_RECONCILED
            if reconciled
            else CashFlowResultStatus.PARTIAL_UNRECONCILED
        )
        prior_period_id = inputs.prior_period.period_id
        prior_period = inputs.prior_period
        prior_digest = canonical_cash_flow_digest(inputs.prior_period)
        proof = comparability_proof_digest

    ordered_lines = tuple(lines[code] for code in CASH_FLOW_LINE_ITEM_MANIFEST_V1)
    completeness = build_completeness(ordered_lines)
    endpoint_evidence = tuple(
        reference for endpoint in endpoints for reference in endpoint.balance_sheet_evidence
    )
    evidence = _union_evidence(
        draft.evidence,
        tuple(reference for item in ordered_lines for reference in item.evidence),
        endpoint_evidence,
    )
    result = CashFlowResult(
        opening_cash_and_cash_equivalents=lines[CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS].canonical_amount,
        closing_cash_and_cash_equivalents=lines[CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS].canonical_amount,
        operating_cash_flow=lines[CashFlowLineCode.OPERATING_CASH_FLOW].canonical_amount,
        investing_cash_flow=lines[CashFlowLineCode.INVESTING_CASH_FLOW].canonical_amount,
        financing_cash_flow=lines[CashFlowLineCode.FINANCING_CASH_FLOW].canonical_amount,
        authoritative_fx_effect=lines[CashFlowLineCode.AUTHORITATIVE_FX_EFFECT].canonical_amount,
        authoritative_reclassification_effect=lines[CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT].canonical_amount,
        calculated_net_cash_change=lines[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE].canonical_amount,
        balance_sheet_net_cash_change=lines[CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE].canonical_amount,
        reconciliation_difference=lines[CashFlowLineCode.RECONCILIATION_DIFFERENCE].canonical_amount,
        free_cash_flow=lines[CashFlowLineCode.FREE_CASH_FLOW].canonical_amount,
        status=status,
        completeness=completeness,
        reconciliation_status=reconciliation.status,
        currency_code=CASH_FLOW_CURRENCY_CODE_V1,
        monetary_scale=CASH_FLOW_MONETARY_SCALE_V1,
        policy_version=draft.policy_version,
        accounting_policy_version=draft.accounting_policy_version,
        cash_equivalent_policy_version=draft.cash_equivalent_policy_version,
        presentation_policy_version=draft.presentation_policy_version,
        reconciliation_policy_version=draft.reconciliation_policy_version,
        mapping_registry_version=draft.mapping_registry_version,
        current_period_id=inputs.current_period.period_id,
        prior_period_id=prior_period_id,
        current_period_descriptor=inputs.current_period,
        prior_period_descriptor=prior_period,
        current_period_descriptor_digest=canonical_cash_flow_digest(inputs.current_period),
        prior_period_descriptor_digest=prior_digest,
        comparability_proof_digest=proof,
        line_items=ordered_lines,
        cash_availability_disclosures=draft.cash_availability_disclosures,
        endpoint_reconciliations=endpoints,
        evidence=evidence,
        warnings=warnings,
        errors=(),
        source_lineage_references=draft.source_lineage_references,
        cash_flow_schema_version=CASH_FLOW_SCHEMA_VERSION,
        cash_flow_model_version=CASH_FLOW_MODEL_VERSION,
    )
    assess_data_quality(
        inputs=inputs,
        line_items=ordered_lines,
        warnings=warnings,
        reconciliation_status=reconciliation.status,
    )
    return result
