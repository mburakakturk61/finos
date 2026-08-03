"""Pure indirect cash-flow calculation core for Milestone 4.5D.

The module produces only ``CashFlowComputationDraft``.  It does not finalize
reconciliation/status, persist data, or call framework/application services.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import Final

from .calculation import (
    CashFlowCoreIntegrityError,
    CashFlowCoreMappingVersionError,
    CashFlowCorePolicyError,
    canonical_evidence_bundle_digest,
    canonical_references,
    exact_sum,
    finalize_leaves,
    finalized_sum,
    weakest_evidence,
)
from .contracts import (
    CashFlowAccountEvidence,
    CashFlowActivityAllocation,
    CashFlowCashAvailabilityDisclosure,
    CashFlowCashAvailabilityObservation,
    CashFlowComputationDraft,
    CashFlowEvidenceReference,
    CashFlowIssue,
    CashFlowLineItem,
    CashFlowSourceLineageReference,
    CashFlowSourceSnapshot,
    IndirectCashFlowInput,
    canonical_cash_flow_bytes,
    canonical_cash_flow_digest,
)
from .errors import CashFlowContractError
from .policy import (
    CASH_EQUIVALENT_POLICY_VERSION,
    CASH_FLOW_ACCOUNTING_POLICY_VERSION,
    CASH_FLOW_MAPPING_REGISTRY_VERSION,
    CASH_FLOW_RECONCILIATION_POLICY_VERSION,
    CashFlowPresentationRule,
    canonical_policy_bundle_digest,
)
from .registry import CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1
from .types import (
    CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1,
    CASH_FLOW_LINE_ITEM_MANIFEST_V1,
    CashAvailabilityClassification,
    CashFlowAccountDisposition,
    CashFlowAccountFamilyCode,
    CashFlowAccountRole,
    CashFlowActivity,
    CashFlowApplicability,
    CashFlowAvailabilityPeriodPosition,
    CashFlowBalanceSemantics,
    CashFlowDerivationCode,
    CashFlowEvidenceKind,
    CashFlowFamilyMemberKind,
    CashFlowLineAggregationRole,
    CashFlowLineCode,
    CashFlowNonCashBridgeDomain,
    CashFlowNonCashBridgeKind,
    CashFlowJsonObject,
    CashFlowSourceRole,
    CashFlowStatementBasis,
    CashFlowWarningCode,
    CashFlowWorkingCapitalKind,
)


_EMPTY_METADATA = CashFlowJsonObject(items=())

_CURRENT_ROLES: Final = {
    CashFlowSourceRole.CURRENT_TRIAL_BALANCE,
    CashFlowSourceRole.CURRENT_INCOME_STATEMENT,
}
_PRIOR_ROLES: Final = {CashFlowSourceRole.PRIOR_TRIAL_BALANCE}

_INVESTING_BRIDGE_KINDS: Final = (
    CashFlowNonCashBridgeKind.DEPRECIATION_OR_AMORTIZATION,
    CashFlowNonCashBridgeKind.IMPAIRMENT,
    CashFlowNonCashBridgeKind.REVALUATION,
    CashFlowNonCashBridgeKind.TRANSFER_OR_RECLASSIFICATION,
    CashFlowNonCashBridgeKind.DISPOSAL_GAIN_OR_LOSS,
    CashFlowNonCashBridgeKind.FX_OR_TRANSLATION,
    CashFlowNonCashBridgeKind.NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION,
    CashFlowNonCashBridgeKind.CAPITALIZED_INTEREST,
)
_FINANCING_BRIDGE_KINDS: Final = (
    CashFlowNonCashBridgeKind.TRANSFER_OR_RECLASSIFICATION,
    CashFlowNonCashBridgeKind.FX_OR_TRANSLATION,
    CashFlowNonCashBridgeKind.NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION,
    CashFlowNonCashBridgeKind.LEASE_MODIFICATION,
    CashFlowNonCashBridgeKind.DEBT_TO_EQUITY_CONVERSION,
    CashFlowNonCashBridgeKind.CAPITALIZED_INTEREST,
)


def _json_field(source: CashFlowSourceSnapshot | None, key: str) -> Decimal | None:
    if source is None:
        return None
    values = dict(source.result_payload.items)
    value = values.get(key)
    if value is None:
        return None
    if type(value) is not Decimal:
        raise CashFlowContractError("cash-flow monetary source field must be Decimal")
    return value


def _mapping(evidence: CashFlowAccountEvidence):
    resolution = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.resolve(
        evidence.account_code,
        explicit_account_role=evidence.canonical_account_role,
        expected_registry_version=CASH_FLOW_MAPPING_REGISTRY_VERSION,
    )
    if resolution.resolved_account_role is not evidence.canonical_account_role:
        raise CashFlowCoreIntegrityError("account role proof conflicts with registry")
    if resolution.account_family_code is not evidence.account_family_code:
        raise CashFlowCoreIntegrityError("account family proof conflicts with registry")
    if resolution.family_member_kind is not evidence.family_member_kind:
        raise CashFlowCoreIntegrityError("account family member proof conflicts with registry")
    if evidence.account_family_code is not None:
        expected = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.family_reference_digest(
            evidence.account_family_code
        )
        if expected != evidence.account_family_reference_digest:
            raise CashFlowCoreIntegrityError("account family reference digest mismatch")
    if evidence.account_disposition is CashFlowAccountDisposition.OPERATING_WORKING_CAPITAL:
        if resolution.role_behavior.working_capital_kind is CashFlowWorkingCapitalKind.NOT_APPLICABLE:
            raise CashFlowCoreIntegrityError("working-capital disposition is not registry-backed")
    elif evidence.account_disposition in {
        CashFlowAccountDisposition.INVESTING_FAMILY,
        CashFlowAccountDisposition.FINANCING_FAMILY,
    } and resolution.account_family_code is None:
        raise CashFlowCoreIntegrityError("family disposition is not registry-backed")
    return resolution


def _account_reference(
    evidence: CashFlowAccountEvidence,
    *,
    kind: CashFlowEvidenceKind,
    derivation: CashFlowDerivationCode,
) -> CashFlowEvidenceReference:
    resolution = _mapping(evidence)
    return CashFlowEvidenceReference(
        evidence_kind=kind,
        source_role=evidence.source_role,
        source_analysis_result_id=evidence.source_analysis_result_id,
        same_run_engine_code=evidence.same_run_engine_code,
        source_canonical_digest=evidence.source_canonical_digest,
        source_provenance_digest=evidence.source_provenance_digest,
        account_codes=(evidence.account_code,),
        mapping_ids=(resolution.mapping_id,) if resolution.mapping_id else (),
        derivation_code=derivation,
    )


def _source_reference(
    source: CashFlowSourceSnapshot,
    *,
    kind: CashFlowEvidenceKind,
    derivation: CashFlowDerivationCode,
) -> CashFlowEvidenceReference:
    return CashFlowEvidenceReference(
        evidence_kind=kind,
        source_role=source.source_role,
        source_analysis_result_id=source.analysis_result_id,
        same_run_engine_code=source.same_run_engine_code,
        source_canonical_digest=source.canonical_digest,
        source_provenance_digest=source.source_provenance_digest,
        account_codes=(),
        mapping_ids=(),
        derivation_code=derivation,
    )


def _bridge_reference(component, *, kind: CashFlowEvidenceKind) -> CashFlowEvidenceReference:
    return CashFlowEvidenceReference(
        evidence_kind=kind,
        source_role=component.source_role,
        source_analysis_result_id=component.source_analysis_result_id,
        same_run_engine_code=component.same_run_engine_code,
        source_canonical_digest=component.source_canonical_digest,
        source_provenance_digest=component.source_provenance_digest,
        account_codes=(),
        mapping_ids=(component.component_reference_digest,),
        derivation_code=CashFlowDerivationCode.BALANCE_DELTA,
    )


def _warning(code: CashFlowWarningCode) -> CashFlowIssue:
    return CashFlowIssue(code=code, safe_metadata=_EMPTY_METADATA)


def _unavailable(
    code: CashFlowLineCode,
    *missing: str,
    warning: CashFlowWarningCode | None = None,
) -> CashFlowLineItem:
    warnings = () if warning is None else (warning,)
    warnings = tuple(sorted(warnings, key=lambda value: value.value))
    return CashFlowLineItem(
        line_code=code,
        canonical_amount=None,
        aggregation_role=dict(CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1)[code],
        presentation_allocations=(),
        applicability=CashFlowApplicability.UNKNOWN,
        evidence_kind=CashFlowEvidenceKind.UNAVAILABLE,
        evidence=(),
        missing_inputs=tuple(sorted(set(missing or ("authoritative_evidence",)))),
        warning_codes=warnings,
    )


def _available(
    code: CashFlowLineCode,
    amount: Decimal,
    *,
    kind: CashFlowEvidenceKind,
    evidence: tuple[CashFlowEvidenceReference, ...],
    activity: CashFlowActivity | None = None,
    applicability: CashFlowApplicability = CashFlowApplicability.APPLICABLE,
    warning: CashFlowWarningCode | None = None,
) -> CashFlowLineItem:
    amount = finalized_sum((amount,))
    role = dict(CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1)[code]
    allocations = ()
    if role is CashFlowLineAggregationRole.PRESENTATION_CONTRIBUTOR:
        if activity is None:
            raise CashFlowContractError("contributor line requires an activity")
        allocations = (CashFlowActivityAllocation(activity=activity, amount=amount),)
    warnings = () if warning is None else (warning,)
    return CashFlowLineItem(
        line_code=code,
        canonical_amount=amount,
        aggregation_role=role,
        presentation_allocations=allocations,
        applicability=applicability,
        evidence_kind=kind,
        evidence=canonical_references(evidence),
        missing_inputs=(),
        warning_codes=tuple(sorted(warnings, key=lambda value: value.value)),
    )


def _subtotal(
    code: CashFlowLineCode,
    contributors: tuple[CashFlowLineItem, ...],
    *,
    derivation: CashFlowDerivationCode,
) -> CashFlowLineItem:
    if not contributors or any(item.canonical_amount is None for item in contributors):
        return _unavailable(code, "complete_contributor_set")
    evidence_by_digest = {
        canonical_cash_flow_digest(reference): reference
        for item in contributors
        for reference in item.evidence
    }
    evidence = tuple(evidence_by_digest[key] for key in sorted(evidence_by_digest))
    kind = weakest_evidence(tuple(item.evidence_kind for item in contributors))
    if kind is CashFlowEvidenceKind.EXACT:
        kind = CashFlowEvidenceKind.DERIVED
    return _available(
        code,
        exact_sum(tuple(item.canonical_amount for item in contributors)),
        kind=kind,
        evidence=evidence,
    )


def _presentation_activity(rule: CashFlowPresentationRule) -> CashFlowActivity:
    if rule is CashFlowPresentationRule.OPERATING or rule is CashFlowPresentationRule.ATTRIBUTION_THEN_OPERATING:
        return CashFlowActivity.OPERATING
    if rule is CashFlowPresentationRule.INVESTING:
        return CashFlowActivity.INVESTING
    if rule is CashFlowPresentationRule.FINANCING:
        return CashFlowActivity.FINANCING
    raise CashFlowContractError("unsupported presentation activity rule")


def _validate_input(inputs: IndirectCashFlowInput) -> None:
    if type(inputs) is not IndirectCashFlowInput:
        raise CashFlowContractError("indirect cash-flow input is required")
    if inputs.mapping_registry_version != CASH_FLOW_MAPPING_REGISTRY_VERSION:
        raise CashFlowCoreMappingVersionError("mapping registry version mismatch")
    if inputs.accounting_policy_version != CASH_FLOW_ACCOUNTING_POLICY_VERSION:
        raise CashFlowCorePolicyError("accounting policy version mismatch")
    if inputs.current_period.accounting_policy_version != inputs.accounting_policy_version:
        raise CashFlowCoreIntegrityError("current period accounting policy mismatch")
    if inputs.prior_period is not None:
        if (
            inputs.prior_period.company_id != inputs.current_period.company_id
            or inputs.prior_period.tenant_id != inputs.current_period.tenant_id
            or inputs.prior_period.currency_code != inputs.current_period.currency_code
            or inputs.prior_period.accounting_policy_version != inputs.accounting_policy_version
        ):
            raise CashFlowCoreIntegrityError("current/prior period scope or policy mismatch")
    source_manifest = (
        (inputs.current_balance_sheet, CashFlowSourceRole.CURRENT_BALANCE_SHEET, inputs.current_period),
        (inputs.prior_balance_sheet, CashFlowSourceRole.PRIOR_BALANCE_SHEET, inputs.prior_period),
        (inputs.current_income_statement, CashFlowSourceRole.CURRENT_INCOME_STATEMENT, inputs.current_period),
        (inputs.current_trial_balance, CashFlowSourceRole.CURRENT_TRIAL_BALANCE, inputs.current_period),
        (inputs.prior_trial_balance, CashFlowSourceRole.PRIOR_TRIAL_BALANCE, inputs.prior_period),
    )
    sources_by_role = {}
    for source, expected_role, period in source_manifest:
        if source is None:
            continue
        if period is None:
            raise CashFlowCoreIntegrityError("prior source exists without a prior period")
        if (
            source.source_role is not expected_role
            or source.company_id != inputs.current_period.company_id
            or source.period_id != period.period_id
            or source.currency_code != inputs.current_period.currency_code
            or source.coverage_end_date != period.end_date
        ):
            raise CashFlowCoreIntegrityError("source snapshot scope or period mismatch")
        if expected_role is CashFlowSourceRole.CURRENT_INCOME_STATEMENT:
            if (
                source.statement_basis is not CashFlowStatementBasis.FLOW_INTERVAL
                or source.coverage_start_date != period.start_date
            ):
                raise CashFlowCoreIntegrityError("income-statement flow window mismatch")
        elif source.statement_basis is not CashFlowStatementBasis.AS_OF:
            raise CashFlowCoreIntegrityError("balance source must use AS_OF semantics")
        sources_by_role[expected_role] = source
    expected_bundle = canonical_evidence_bundle_digest(
        inputs.account_evidence, inputs.noncash_bridge_components
    )
    if expected_bundle != inputs.account_evidence_bundle_digest:
        raise CashFlowCoreIntegrityError("account evidence bundle digest mismatch")
    seen: set[tuple[CashFlowSourceRole, str, CashFlowAccountRole | None]] = set()
    for evidence in inputs.account_evidence:
        key = (evidence.source_role, evidence.account_code, evidence.canonical_account_role)
        if key in seen:
            raise CashFlowCoreIntegrityError("duplicate account evidence")
        seen.add(key)
        _mapping(evidence)
        source = sources_by_role.get(evidence.source_role)
        if source is None or (
            evidence.source_analysis_result_id != source.analysis_result_id
            or evidence.same_run_engine_code != source.same_run_engine_code
            or evidence.source_canonical_digest != source.canonical_digest
            or evidence.source_provenance_digest != source.source_provenance_digest
            or evidence.as_of_date != source.coverage_end_date
        ):
            raise CashFlowCoreIntegrityError("account evidence source binding mismatch")
    component_keys = set()
    for component in inputs.noncash_bridge_components:
        key = (
            component.domain,
            component.account_family_code,
            component.account_family_reference_digest,
            component.bridge_kind,
        )
        if key in component_keys:
            raise CashFlowCoreIntegrityError("duplicate non-cash bridge component")
        component_keys.add(key)
        if component.source_role not in _CURRENT_ROLES:
            raise CashFlowCoreIntegrityError("bridge component uses a non-current source")
        if (
            component.coverage_start_date != inputs.current_period.start_date
            or component.coverage_end_date != inputs.current_period.end_date
        ):
            raise CashFlowCoreIntegrityError("bridge component flow window mismatch")
        expected_family = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.family_reference_digest(
            component.account_family_code
        )
        if expected_family != component.account_family_reference_digest:
            raise CashFlowCoreIntegrityError("bridge component family proof mismatch")
        source = sources_by_role.get(component.source_role)
        if source is None or (
            component.source_analysis_result_id != source.analysis_result_id
            or component.same_run_engine_code != source.same_run_engine_code
            or component.source_canonical_digest != source.canonical_digest
            or component.source_provenance_digest != source.source_provenance_digest
        ):
            raise CashFlowCoreIntegrityError("bridge component source binding mismatch")


def _minimum_cash_ground_available(inputs: IndirectCashFlowInput) -> bool:
    current = {}
    prior = {}
    for evidence in inputs.account_evidence:
        if evidence.account_disposition is not CashFlowAccountDisposition.CASH_OR_CASH_EQUIVALENT:
            continue
        target = (
            current
            if evidence.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE
            else prior
            if evidence.source_role is CashFlowSourceRole.PRIOR_TRIAL_BALANCE
            else None
        )
        if target is not None:
            target[(evidence.account_code, evidence.canonical_account_role)] = evidence
    if not current or set(current) != set(prior):
        return False
    return all(
        current[key].normalized_functional_currency_balance is not None
        and prior[key].normalized_functional_currency_balance is not None
        for key in current
    )


def _cash_lines(inputs, lines, disclosures):
    current = {}
    prior = {}
    for evidence in inputs.account_evidence:
        if evidence.account_disposition is not CashFlowAccountDisposition.CASH_OR_CASH_EQUIVALENT:
            continue
        target = current if evidence.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE else prior if evidence.source_role is CashFlowSourceRole.PRIOR_TRIAL_BALANCE else None
        if target is not None:
            target[(evidence.account_code, evidence.canonical_account_role)] = evidence
    keys = tuple(sorted(set(current) | set(prior), key=lambda item: (item[0], item[1].value)))
    if not keys or set(current) != set(prior):
        return
    opening_values = []
    closing_values = []
    opening_refs = []
    closing_refs = []
    for key in keys:
        opening, closing = prior[key], current[key]
        if opening.normalized_functional_currency_balance is None or closing.normalized_functional_currency_balance is None:
            return
        opening_ref = _account_reference(opening, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.SOURCE_VALUE)
        closing_ref = _account_reference(closing, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.SOURCE_VALUE)
        opening_refs.append(opening_ref)
        closing_refs.append(closing_ref)
        role = opening.canonical_account_role

        def classify(item):
            if item.is_restricted is not True:
                return CashAvailabilityClassification.UNRESTRICTED_INCLUDED
            if item.restriction_preserves_cash_nature is True:
                return CashAvailabilityClassification.RESTRICTED_INCLUDED
            if item.restriction_preserves_cash_nature is False:
                return CashAvailabilityClassification.RESTRICTED_EXCLUDED
            return CashAvailabilityClassification.ELIGIBILITY_UNRESOLVED

        opening_classification = classify(opening)
        closing_classification = classify(closing)
        included = {
            CashAvailabilityClassification.UNRESTRICTED_INCLUDED,
            CashAvailabilityClassification.RESTRICTED_INCLUDED,
        }
        if opening_classification in included:
            opening_values.append(opening.normalized_functional_currency_balance)
        if closing_classification in included:
            closing_values.append(closing.normalized_functional_currency_balance)
        observations = (
            CashFlowCashAvailabilityObservation(
                CashFlowAvailabilityPeriodPosition.OPENING,
                opening_classification,
                finalized_sum((opening.normalized_functional_currency_balance,)),
                opening.restriction_preserves_cash_nature if opening.is_restricted else None,
                canonical_references((opening_ref,)),
            ),
            CashFlowCashAvailabilityObservation(
                CashFlowAvailabilityPeriodPosition.CLOSING,
                closing_classification,
                finalized_sum((closing.normalized_functional_currency_balance,)),
                closing.restriction_preserves_cash_nature if closing.is_restricted else None,
                canonical_references((closing_ref,)),
            ),
        )
        disclosures.append(CashFlowCashAvailabilityDisclosure(
            component_reference_digest=sha256(
                b"cash-flow/cash-availability-component/v1\0"
                + canonical_cash_flow_bytes((key[0], role, observations))
            ).hexdigest(),
            account_role=role,
            observations=observations,
        ))
    lines[CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS] = _available(
        CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS,
        finalized_sum(tuple(opening_values)),
        kind=CashFlowEvidenceKind.EXACT,
        evidence=tuple(opening_refs),
    )
    lines[CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS] = _available(
        CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS,
        finalized_sum(tuple(closing_values)),
        kind=CashFlowEvidenceKind.EXACT,
        evidence=tuple(closing_refs),
    )
    lines[CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE] = _available(
        CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE,
        exact_sum((lines[CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS].canonical_amount, -lines[CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS].canonical_amount)),
        kind=CashFlowEvidenceKind.DERIVED,
        evidence=tuple(opening_refs + closing_refs),
    )


def _working_capital(inputs, lines):
    current = {}
    prior = {}
    for evidence in inputs.account_evidence:
        if evidence.account_disposition is not CashFlowAccountDisposition.OPERATING_WORKING_CAPITAL:
            continue
        target = current if evidence.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE else prior if evidence.source_role is CashFlowSourceRole.PRIOR_TRIAL_BALANCE else None
        if target is not None:
            target[(evidence.account_code, evidence.canonical_account_role)] = evidence
    grouped = defaultdict(list)
    grouped_refs = defaultdict(list)
    incomplete_codes = set()
    for key in set(current) | set(prior):
        if key not in current or key not in prior:
            role = (current.get(key) or prior.get(key)).canonical_account_role
            line_code = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.behavior_for(role).candidate_line_codes[0]
            incomplete_codes.add(line_code)
            continue
        opening, closing = prior[key], current[key]
        if opening.normalized_functional_currency_balance is None or closing.normalized_functional_currency_balance is None:
            incomplete_codes.add(CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.behavior_for(opening.canonical_account_role).candidate_line_codes[0])
            continue
        resolution = _mapping(closing)
        behavior = resolution.role_behavior
        line_code = behavior.candidate_line_codes[0]
        delta = exact_sum((closing.normalized_functional_currency_balance, -opening.normalized_functional_currency_balance))
        effect = -delta if behavior.working_capital_kind is CashFlowWorkingCapitalKind.OPERATING_ASSET else delta
        grouped[line_code].append(effect)
        grouped_refs[line_code].extend((
            _account_reference(opening, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.BALANCE_DELTA),
            _account_reference(closing, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.BALANCE_DELTA),
        ))
    wc_codes = (
        CashFlowLineCode.INVENTORY_MOVEMENT,
        CashFlowLineCode.TRADE_RECEIVABLES_MOVEMENT,
        CashFlowLineCode.OTHER_OPERATING_ASSET_MOVEMENT,
        CashFlowLineCode.TRADE_PAYABLES_MOVEMENT,
        CashFlowLineCode.OTHER_OPERATING_LIABILITY_MOVEMENT,
    )
    for code in wc_codes:
        if code in incomplete_codes or not grouped[code]:
            lines[code] = _unavailable(code, "opening_and_closing_account_balance")
        else:
            lines[code] = _available(
                code,
                finalized_sum(tuple(grouped[code])),
                kind=CashFlowEvidenceKind.DERIVED,
                evidence=tuple(grouped_refs[code]),
                activity=CashFlowActivity.OPERATING,
            )
    lines[CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL] = _subtotal(
        CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL,
        tuple(lines[code] for code in wc_codes),
        derivation=CashFlowDerivationCode.INDIRECT_OPERATING_SUBTOTAL,
    )


def _other_non_cash_adjustments(inputs, lines):
    rows = tuple(
        item for item in inputs.account_evidence
        if item.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE
        and item.canonical_account_role in {
            CashFlowAccountRole.NON_CASH_ADJUSTMENT,
            CashFlowAccountRole.DEFERRED_TAX_ACCRUAL,
        }
    )
    values = []
    references = []
    for row in rows:
        resolution = _mapping(row)
        debit = row.normalized_functional_currency_debit_movement
        credit = row.normalized_functional_currency_credit_movement
        if debit is None or credit is None or resolution.code_normal_balance is None:
            lines[CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS] = _unavailable(
                CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS,
                "authoritative_non_cash_period_movement",
                warning=CashFlowWarningCode.NON_CASH_ADJUSTMENT_UNAVAILABLE,
            )
            return
        value = (
            exact_sum((debit, -credit))
            if resolution.code_normal_balance.value == "debit"
            else exact_sum((credit, -debit))
        )
        values.append(value)
        references.append(_account_reference(
            row,
            kind=CashFlowEvidenceKind.DERIVED,
            derivation=CashFlowDerivationCode.NET_PROFIT_ACCRUAL_REVERSAL,
        ))
    if rows:
        lines[CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS] = _available(
            CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS,
            finalized_sum(tuple(values)),
            kind=CashFlowEvidenceKind.DERIVED,
            evidence=tuple(references),
            activity=CashFlowActivity.OPERATING,
        )
    elif inputs.current_trial_balance is not None and inputs.closing_account_coverage_complete:
        lines[CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS] = _available(
            CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS,
            Decimal("0"),
            kind=CashFlowEvidenceKind.EXACT,
            evidence=(_source_reference(
                inputs.current_trial_balance,
                kind=CashFlowEvidenceKind.EXACT,
                derivation=CashFlowDerivationCode.SOURCE_VALUE,
            ),),
            activity=CashFlowActivity.OPERATING,
            applicability=CashFlowApplicability.PROVEN_NOT_APPLICABLE,
        )


def _movement_amount(evidence: CashFlowAccountEvidence, *, credit_positive: bool) -> Decimal | None:
    debit = evidence.normalized_functional_currency_debit_movement
    credit = evidence.normalized_functional_currency_credit_movement
    if debit is None or credit is None:
        return None
    return exact_sum((credit, -debit)) if credit_positive else exact_sum((debit, -credit))


def _direct_movement_lines(inputs, lines):
    buckets = defaultdict(list)
    refs = defaultdict(list)
    for evidence in inputs.account_evidence:
        if evidence.source_role is not CashFlowSourceRole.CURRENT_TRIAL_BALANCE:
            continue
        role = evidence.canonical_account_role
        if role is None:
            continue
        amount = None
        targets = ()
        if role is CashFlowAccountRole.PPE:
            targets = (CashFlowLineCode.PROVEN_PPE_ACQUISITIONS, CashFlowLineCode.PROVEN_PPE_DISPOSALS)
        elif role is CashFlowAccountRole.INTANGIBLE_ASSET:
            targets = (CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS, CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS)
        elif role in {CashFlowAccountRole.FINANCIAL_INVESTMENT, CashFlowAccountRole.EQUITY_FINANCIAL_INVESTMENT, CashFlowAccountRole.LONG_TERM_FINANCIAL_INVESTMENT}:
            targets = (CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,)
        elif role is CashFlowAccountRole.BORROWING:
            targets = (CashFlowLineCode.PROVEN_BORROWING_PROCEEDS, CashFlowLineCode.PROVEN_DEBT_REPAYMENTS)
        elif role is CashFlowAccountRole.EQUITY:
            targets = (CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS,)
        elif role is CashFlowAccountRole.DIVIDEND_PAYABLE:
            targets = (CashFlowLineCode.PROVEN_DIVIDENDS_PAID,)
        if not targets:
            continue
        debit = evidence.normalized_functional_currency_debit_movement
        credit = evidence.normalized_functional_currency_credit_movement
        if debit is None or credit is None:
            continue
        reference = _account_reference(evidence, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.SOURCE_VALUE)
        if len(targets) == 2:
            first, second = targets
            if role is CashFlowAccountRole.BORROWING:
                values = ((first, credit), (second, -debit))
            else:
                values = ((first, -debit), (second, credit))
        elif targets[0] is CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS:
            values = ((targets[0], exact_sum((credit, -debit))),)
        elif targets[0] is CashFlowLineCode.PROVEN_DIVIDENDS_PAID:
            values = ((targets[0], -debit),)
        else:
            values = ((targets[0], credit),)
        for code, value in values:
            buckets[code].append(value)
            refs[code].append(reference)
    activity_by_code = {
        CashFlowLineCode.PROVEN_PPE_ACQUISITIONS: CashFlowActivity.INVESTING,
        CashFlowLineCode.PROVEN_PPE_DISPOSALS: CashFlowActivity.INVESTING,
        CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS: CashFlowActivity.INVESTING,
        CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS: CashFlowActivity.INVESTING,
        CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS: CashFlowActivity.INVESTING,
        CashFlowLineCode.PROVEN_BORROWING_PROCEEDS: CashFlowActivity.FINANCING,
        CashFlowLineCode.PROVEN_DEBT_REPAYMENTS: CashFlowActivity.FINANCING,
        CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS: CashFlowActivity.FINANCING,
        CashFlowLineCode.PROVEN_DIVIDENDS_PAID: CashFlowActivity.FINANCING,
    }
    for code, activity in activity_by_code.items():
        if buckets[code]:
            lines[code] = _available(
                code,
                finalized_sum(tuple(buckets[code])),
                kind=CashFlowEvidenceKind.EXACT,
                evidence=tuple(refs[code]),
                activity=activity,
            )


def _family_balance(inputs, family_code, source_role):
    rows = tuple(
        item for item in inputs.account_evidence
        if item.source_role is source_role and item.account_family_code is family_code
    )
    if not rows or any(item.normalized_functional_currency_balance is None for item in rows):
        return None, ()
    values = []
    refs = []
    for item in rows:
        value = item.normalized_functional_currency_balance
        if item.family_member_kind in {CashFlowFamilyMemberKind.ASSET_CONTRA, CashFlowFamilyMemberKind.LIABILITY_CONTRA}:
            value = -value
        values.append(value)
        refs.append(_account_reference(item, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.BALANCE_DELTA))
    return exact_sum(tuple(values)), tuple(refs)


def _bridge_ledger(inputs, family_code, domain, required_kinds):
    components = tuple(
        item for item in inputs.noncash_bridge_components
        if item.account_family_code is family_code and item.domain is domain
    )
    by_kind = {item.bridge_kind: item for item in components}
    if len(by_kind) != len(components) or set(by_kind) != set(required_kinds):
        return None, ()
    if any(item.signed_residual_adjustment is None for item in components):
        return None, ()
    return (
        exact_sum(tuple(item.signed_residual_adjustment for item in components)),
        tuple(_bridge_reference(item, kind=item.evidence_kind) for item in components),
    )


def _estimated_residuals(inputs, lines):
    investing_values = []
    investing_refs = []
    direct_by_family = {
        CashFlowAccountFamilyCode.PPE_NET: any(
            lines[code].canonical_amount is not None
            for code in (CashFlowLineCode.PROVEN_PPE_ACQUISITIONS, CashFlowLineCode.PROVEN_PPE_DISPOSALS)
        ),
        CashFlowAccountFamilyCode.INTANGIBLE_NET: any(
            lines[code].canonical_amount is not None
            for code in (CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS, CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS)
        ),
        CashFlowAccountFamilyCode.FINANCIAL_INVESTMENT_NET: (
            lines[CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS].canonical_amount is not None
        ),
    }
    for family in (
        CashFlowAccountFamilyCode.PPE_NET,
        CashFlowAccountFamilyCode.INTANGIBLE_NET,
        CashFlowAccountFamilyCode.FINANCIAL_INVESTMENT_NET,
    ):
        if direct_by_family[family]:
            continue
        opening, opening_refs = _family_balance(inputs, family, CashFlowSourceRole.PRIOR_TRIAL_BALANCE)
        closing, closing_refs = _family_balance(inputs, family, CashFlowSourceRole.CURRENT_TRIAL_BALANCE)
        bridge, bridge_refs = _bridge_ledger(inputs, family, CashFlowNonCashBridgeDomain.INVESTING_ASSET, _INVESTING_BRIDGE_KINDS)
        if opening is None or closing is None or bridge is None:
            investing_values = []
            investing_refs = []
            break
        investing_values.append(-exact_sum((closing, -opening, -bridge)))
        investing_refs.extend(opening_refs + closing_refs + bridge_refs)
    if investing_values:
        lines[CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT] = _available(
            CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT,
            finalized_sum(tuple(investing_values)),
            kind=CashFlowEvidenceKind.ESTIMATED,
            evidence=tuple(investing_refs),
            activity=CashFlowActivity.INVESTING,
            warning=CashFlowWarningCode.ESTIMATED_NET_MOVEMENT_USED,
        )
    direct_debt = any(
        lines[code].canonical_amount is not None
        for code in (CashFlowLineCode.PROVEN_BORROWING_PROCEEDS, CashFlowLineCode.PROVEN_DEBT_REPAYMENTS)
    )
    if not direct_debt:
        opening, opening_refs = _family_balance(inputs, CashFlowAccountFamilyCode.BORROWING_GROSS, CashFlowSourceRole.PRIOR_TRIAL_BALANCE)
        closing, closing_refs = _family_balance(inputs, CashFlowAccountFamilyCode.BORROWING_GROSS, CashFlowSourceRole.CURRENT_TRIAL_BALANCE)
        bridge, bridge_refs = _bridge_ledger(inputs, CashFlowAccountFamilyCode.BORROWING_GROSS, CashFlowNonCashBridgeDomain.FINANCING_DEBT, _FINANCING_BRIDGE_KINDS)
        if opening is not None and closing is not None and bridge is not None:
            lines[CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT] = _available(
                CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT,
                finalized_sum((exact_sum((closing, -opening, -bridge)),)),
                kind=CashFlowEvidenceKind.ESTIMATED,
                evidence=opening_refs + closing_refs + bridge_refs,
                activity=CashFlowActivity.FINANCING,
                warning=CashFlowWarningCode.ESTIMATED_NET_MOVEMENT_USED,
            )


def _accrual_cash_bridges(inputs, lines):
    pairs = (
        (CashFlowAccountRole.INTEREST_EXPENSE_ACCRUAL, CashFlowAccountRole.INTEREST_PAYABLE, CashFlowLineCode.INTEREST_EXPENSE_ACCRUAL_REVERSAL, CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID, inputs.presentation_policy.interest_paid_rule, True),
        (CashFlowAccountRole.INTEREST_INCOME_ACCRUAL, CashFlowAccountRole.INTEREST_RECEIVABLE, CashFlowLineCode.INTEREST_INCOME_ACCRUAL_REVERSAL, CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED, inputs.presentation_policy.interest_received_rule, False),
        (CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL, CashFlowAccountRole.DIVIDEND_RECEIVABLE, CashFlowLineCode.DIVIDEND_INCOME_ACCRUAL_REVERSAL, CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED, inputs.presentation_policy.dividends_received_rule, False),
        (CashFlowAccountRole.CURRENT_TAX_EXPENSE_ACCRUAL, CashFlowAccountRole.TAX_PAYABLE, CashFlowLineCode.CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL, CashFlowLineCode.AUTHORITATIVE_INCOME_TAX_PAID, inputs.presentation_policy.income_tax_paid_rule, True),
    )
    evidence_by = defaultdict(list)
    for item in inputs.account_evidence:
        evidence_by[(item.source_role, item.canonical_account_role)].append(item)
    for accrual_role, balance_role, reversal_code, cash_code, rule, expense in pairs:
        recognized_rows = evidence_by[(CashFlowSourceRole.CURRENT_TRIAL_BALANCE, accrual_role)]
        opening_rows = evidence_by[(CashFlowSourceRole.PRIOR_TRIAL_BALANCE, balance_role)]
        closing_rows = evidence_by[(CashFlowSourceRole.CURRENT_TRIAL_BALANCE, balance_role)]
        if not recognized_rows or not opening_rows or not closing_rows:
            continue
        recognized_values = []
        references = []
        for row in recognized_rows:
            value = _movement_amount(row, credit_positive=not expense)
            if value is None:
                break
            recognized_values.append(value)
            references.append(_account_reference(row, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.NET_PROFIT_ACCRUAL_REVERSAL))
        else:
            if len(opening_rows) != len(closing_rows):
                continue
            opening_by_code = {row.account_code: row for row in opening_rows}
            closing_by_code = {row.account_code: row for row in closing_rows}
            if set(opening_by_code) != set(closing_by_code):
                continue
            opening_values = []
            closing_values = []
            for code in sorted(opening_by_code):
                opening, closing = opening_by_code[code], closing_by_code[code]
                if opening.normalized_functional_currency_balance is None or closing.normalized_functional_currency_balance is None:
                    break
                opening_values.append(opening.normalized_functional_currency_balance)
                closing_values.append(closing.normalized_functional_currency_balance)
                references.extend((
                    _account_reference(opening, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.BALANCE_DELTA),
                    _account_reference(closing, kind=CashFlowEvidenceKind.EXACT, derivation=CashFlowDerivationCode.BALANCE_DELTA),
                ))
            else:
                recognized = exact_sum(tuple(recognized_values))
                opening = exact_sum(tuple(opening_values))
                closing = exact_sum(tuple(closing_values))
                cash_magnitude = exact_sum((opening, recognized, -closing))
                if cash_magnitude < 0:
                    raise CashFlowCoreIntegrityError("accrual-to-cash bridge produced negative magnitude")
                reversal_amount = recognized if expense else -recognized
                cash_amount = -cash_magnitude if expense else cash_magnitude
                lines[reversal_code] = _available(
                    reversal_code,
                    reversal_amount,
                    kind=CashFlowEvidenceKind.DERIVED,
                    evidence=tuple(references),
                    activity=CashFlowActivity.OPERATING,
                )
                lines[cash_code] = _available(
                    cash_code,
                    cash_amount,
                    kind=CashFlowEvidenceKind.DERIVED,
                    evidence=tuple(references),
                    activity=_presentation_activity(rule),
                )


def _aggregate_activities(lines):
    operating_codes = (
        CashFlowLineCode.NET_PROFIT,
        CashFlowLineCode.NON_CASH_ADJUSTMENT_TOTAL,
        CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL,
        CashFlowLineCode.OTHER_PROVEN_OPERATING_ADJUSTMENTS,
        CashFlowLineCode.INTEREST_EXPENSE_ACCRUAL_REVERSAL,
        CashFlowLineCode.INTEREST_INCOME_ACCRUAL_REVERSAL,
        CashFlowLineCode.DIVIDEND_INCOME_ACCRUAL_REVERSAL,
        CashFlowLineCode.CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL,
    )
    operating_extra = tuple(
        code for code in (
            CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID,
            CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED,
            CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED,
            CashFlowLineCode.AUTHORITATIVE_INCOME_TAX_PAID,
        )
        if any(allocation.activity is CashFlowActivity.OPERATING for allocation in lines[code].presentation_allocations)
    )
    lines[CashFlowLineCode.OPERATING_CASH_FLOW] = _subtotal(
        CashFlowLineCode.OPERATING_CASH_FLOW,
        tuple(lines[code] for code in operating_codes + operating_extra),
        derivation=CashFlowDerivationCode.INDIRECT_OPERATING_SUBTOTAL,
    )
    investing_codes = (
        CashFlowLineCode.PROVEN_PPE_ACQUISITIONS,
        CashFlowLineCode.PROVEN_PPE_DISPOSALS,
        CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS,
        CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS,
        CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,
    )
    direct_investing = tuple(lines[code] for code in investing_codes)
    estimate = lines[CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT]
    investing_base = direct_investing
    if estimate.canonical_amount is not None:
        investing_base = tuple(item for item in direct_investing if item.canonical_amount is not None) + (estimate,)
    investing_extra = tuple(
        lines[code] for code in (
            CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED,
            CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED,
        )
        if any(allocation.activity is CashFlowActivity.INVESTING for allocation in lines[code].presentation_allocations)
    )
    lines[CashFlowLineCode.INVESTING_CASH_FLOW] = _subtotal(
        CashFlowLineCode.INVESTING_CASH_FLOW,
        investing_base + investing_extra,
        derivation=CashFlowDerivationCode.INVESTING_SUBTOTAL,
    )
    debt_estimate = lines[CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT]
    debt_lines = (debt_estimate,) if debt_estimate.canonical_amount is not None else (
        lines[CashFlowLineCode.PROVEN_BORROWING_PROCEEDS],
        lines[CashFlowLineCode.PROVEN_DEBT_REPAYMENTS],
    )
    financing_base = debt_lines + (
        lines[CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS],
        lines[CashFlowLineCode.PROVEN_DIVIDENDS_PAID],
    )
    financing_extra = tuple(
        lines[code] for code in (CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID,)
        if any(allocation.activity is CashFlowActivity.FINANCING for allocation in lines[code].presentation_allocations)
    )
    lines[CashFlowLineCode.FINANCING_CASH_FLOW] = _subtotal(
        CashFlowLineCode.FINANCING_CASH_FLOW,
        financing_base + financing_extra,
        derivation=CashFlowDerivationCode.FINANCING_SUBTOTAL,
    )
    activity_totals = tuple(
        lines[code] for code in (
            CashFlowLineCode.OPERATING_CASH_FLOW,
            CashFlowLineCode.INVESTING_CASH_FLOW,
            CashFlowLineCode.FINANCING_CASH_FLOW,
            CashFlowLineCode.AUTHORITATIVE_FX_EFFECT,
            CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT,
        )
    )
    lines[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE] = _subtotal(
        CashFlowLineCode.CALCULATED_NET_CASH_CHANGE,
        activity_totals,
        derivation=CashFlowDerivationCode.NET_CASH_CHANGE_SUM,
    )


def _free_cash_flow(lines):
    operands = (
        lines[CashFlowLineCode.OPERATING_CASH_FLOW],
        lines[CashFlowLineCode.PROVEN_PPE_ACQUISITIONS],
        lines[CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS],
    )
    if any(item.canonical_amount is None or item.evidence_kind is CashFlowEvidenceKind.ESTIMATED for item in operands):
        lines[CashFlowLineCode.FREE_CASH_FLOW] = _unavailable(
            CashFlowLineCode.FREE_CASH_FLOW, "operating_cash_flow_and_proven_capex"
        )
        return
    capex_magnitude = exact_sum((-operands[1].canonical_amount, -operands[2].canonical_amount))
    lines[CashFlowLineCode.FREE_CASH_FLOW] = _available(
        CashFlowLineCode.FREE_CASH_FLOW,
        exact_sum((operands[0].canonical_amount, -capex_magnitude)),
        kind=weakest_evidence(tuple(item.evidence_kind for item in operands)),
        evidence=tuple(reference for item in operands for reference in item.evidence),
    )


def _lineage(inputs):
    sources = tuple(
        source for source in (
            inputs.current_balance_sheet,
            inputs.prior_balance_sheet,
            inputs.current_income_statement,
            inputs.current_trial_balance,
            inputs.prior_trial_balance,
        ) if source is not None
    )
    values = tuple(
        CashFlowSourceLineageReference(
            source_role=source.source_role,
            source_analysis_result_id=source.analysis_result_id,
            same_run_engine_code=source.same_run_engine_code,
            source_period_id=source.period_id,
            canonical_digest=source.canonical_digest,
            source_provenance_digest=source.source_provenance_digest,
        ) for source in sources
    )
    return tuple(sorted(values, key=canonical_cash_flow_digest))


def analyze_indirect_cash_flow(inputs: IndirectCashFlowInput) -> CashFlowComputationDraft:
    _validate_input(inputs)
    lines = {
        code: _unavailable(code, "authoritative_evidence")
        for code in CASH_FLOW_LINE_ITEM_MANIFEST_V1
    }
    disclosures = []
    warnings = set()
    minimum = (
        inputs.prior_period is not None
        and inputs.current_balance_sheet is not None
        and inputs.prior_balance_sheet is not None
        and inputs.current_income_statement is not None
        and inputs.current_trial_balance is not None
        and inputs.prior_trial_balance is not None
        and inputs.opening_account_coverage_complete
        and inputs.closing_account_coverage_complete
        and _minimum_cash_ground_available(inputs)
    )
    net_profit = _json_field(inputs.current_income_statement, "net_profit")
    if not minimum or net_profit is None:
        warnings.add(CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE)
    else:
        net_ref = _source_reference(
            inputs.current_income_statement,
            kind=CashFlowEvidenceKind.EXACT,
            derivation=CashFlowDerivationCode.SOURCE_VALUE,
        )
        lines[CashFlowLineCode.NET_PROFIT] = _available(
            CashFlowLineCode.NET_PROFIT,
            net_profit,
            kind=CashFlowEvidenceKind.EXACT,
            evidence=(net_ref,),
            activity=CashFlowActivity.OPERATING,
        )
        depreciation = _json_field(inputs.current_income_statement, "depreciation_and_amortization")
        if depreciation is not None:
            if depreciation < 0:
                raise CashFlowCoreIntegrityError("depreciation source amount has invalid sign")
            lines[CashFlowLineCode.DEPRECIATION_AND_AMORTIZATION] = _available(
                CashFlowLineCode.DEPRECIATION_AND_AMORTIZATION,
                depreciation,
                kind=CashFlowEvidenceKind.DERIVED,
                evidence=(_source_reference(inputs.current_income_statement, kind=CashFlowEvidenceKind.DERIVED, derivation=CashFlowDerivationCode.NET_PROFIT_ACCRUAL_REVERSAL),),
                activity=CashFlowActivity.OPERATING,
            )
        else:
            warnings.add(CashFlowWarningCode.NON_CASH_ADJUSTMENT_UNAVAILABLE)
        _other_non_cash_adjustments(inputs, lines)
        lines[CashFlowLineCode.NON_CASH_ADJUSTMENT_TOTAL] = _subtotal(
            CashFlowLineCode.NON_CASH_ADJUSTMENT_TOTAL,
            (
                lines[CashFlowLineCode.DEPRECIATION_AND_AMORTIZATION],
                lines[CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS],
            ),
            derivation=CashFlowDerivationCode.INDIRECT_OPERATING_SUBTOTAL,
        )
        _cash_lines(inputs, lines, disclosures)
        _working_capital(inputs, lines)
        _direct_movement_lines(inputs, lines)
        _estimated_residuals(inputs, lines)
        _accrual_cash_bridges(inputs, lines)
        lines[CashFlowLineCode.OTHER_PROVEN_OPERATING_ADJUSTMENTS] = _available(
            CashFlowLineCode.OTHER_PROVEN_OPERATING_ADJUSTMENTS,
            Decimal("0"),
            kind=CashFlowEvidenceKind.EXACT,
            evidence=(_source_reference(
                inputs.current_trial_balance,
                kind=CashFlowEvidenceKind.EXACT,
                derivation=CashFlowDerivationCode.SOURCE_VALUE,
            ),),
            activity=CashFlowActivity.OPERATING,
            applicability=CashFlowApplicability.PROVEN_NOT_APPLICABLE,
        )
        _aggregate_activities(lines)
        unresolved_nonzero = any(
            item.account_disposition is CashFlowAccountDisposition.UNRESOLVED
            and any(
                value is not None and value != 0
                for value in (
                    item.normalized_functional_currency_balance,
                    item.normalized_functional_currency_debit_movement,
                    item.normalized_functional_currency_credit_movement,
                )
            )
            for item in inputs.account_evidence
        )
        if unresolved_nonzero:
            warnings.add(CashFlowWarningCode.ACCOUNT_UNCLASSIFIED)
            for code in (
                CashFlowLineCode.OPERATING_CASH_FLOW,
                CashFlowLineCode.INVESTING_CASH_FLOW,
                CashFlowLineCode.FINANCING_CASH_FLOW,
                CashFlowLineCode.CALCULATED_NET_CASH_CHANGE,
            ):
                lines[code] = _unavailable(
                    code,
                    "nonzero_unresolved_account",
                    warning=CashFlowWarningCode.ACCOUNT_UNCLASSIFIED,
                )
        _free_cash_flow(lines)
        if lines[CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT].canonical_amount is not None or lines[CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT].canonical_amount is not None:
            warnings.add(CashFlowWarningCode.ESTIMATED_NET_MOVEMENT_USED)
        if lines[CashFlowLineCode.INVESTING_CASH_FLOW].canonical_amount is None or lines[CashFlowLineCode.FINANCING_CASH_FLOW].canonical_amount is None:
            warnings.add(CashFlowWarningCode.GROSS_MOVEMENT_UNAVAILABLE)

    evidence_by_digest = {
        canonical_cash_flow_digest(reference): reference
        for item in lines.values()
        for reference in item.evidence
    }
    evidence = tuple(evidence_by_digest[key] for key in sorted(evidence_by_digest))
    policy_version = canonical_policy_bundle_digest(
        accounting_policy_version=inputs.accounting_policy_version,
        cash_equivalent_policy_version=CASH_EQUIVALENT_POLICY_VERSION,
        presentation_policy_version=inputs.presentation_policy.policy_version,
        reconciliation_policy_version=CASH_FLOW_RECONCILIATION_POLICY_VERSION,
        mapping_registry_version=inputs.mapping_registry_version,
    )
    return CashFlowComputationDraft(
        current_period=inputs.current_period,
        prior_period=inputs.prior_period,
        line_items=tuple(lines[code] for code in CASH_FLOW_LINE_ITEM_MANIFEST_V1),
        cash_availability_disclosures=tuple(sorted(disclosures, key=canonical_cash_flow_digest)),
        evidence=evidence,
        source_lineage_references=_lineage(inputs),
        warnings=tuple(sorted((_warning(code) for code in warnings), key=canonical_cash_flow_digest)),
        policy_version=policy_version,
        accounting_policy_version=inputs.accounting_policy_version,
        cash_equivalent_policy_version=CASH_EQUIVALENT_POLICY_VERSION,
        presentation_policy_version=inputs.presentation_policy.policy_version,
        reconciliation_policy_version=CASH_FLOW_RECONCILIATION_POLICY_VERSION,
        mapping_registry_version=inputs.mapping_registry_version,
    )
