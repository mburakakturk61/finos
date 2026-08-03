"""Versioned deterministic account registry for Milestone 4.5B.

Resolution stops at classification and evidence requirements.  This module
does not accept balances and cannot calculate a cash-flow amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Final

from .account_codes import normalize_account_code
from .errors import CashFlowContractError
from .mapping import (
    CashFlowAccountFamilyDefinition,
    CashFlowAccountMapping,
    CashFlowBankAccountClassification,
    CashFlowBankAccountEvidence,
    CashFlowMappingEntry,
    CashFlowMappingResolution,
    CashFlowRoleBehavior,
)
from .policy import (
    CASH_AND_CASH_EQUIVALENTS_POLICY_V1,
    CASH_FLOW_MAPPING_REGISTRY_VERSION,
)
from .types import (
    CASH_FLOW_MODEL_VERSION,
    CashAvailabilityClassification,
    CashEligibilityRule,
    CashFlowAccountFamilyCode,
    CashFlowAccountDisposition,
    CashFlowAccountRole,
    CashFlowActivity,
    CashFlowEvidenceKind,
    CashFlowFamilyBalanceBasis,
    CashFlowFamilyMemberKind,
    CashFlowLineCode,
    CashFlowMappingMatchKind,
    CashFlowNormalBalance,
    CashFlowRoleSelectionRule,
    CashFlowWorkingCapitalKind,
)


NO_LINES: Final = ()
OPENING_CLOSING: Final = (
    CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS,
)
BANK_BRANCH_LINES: Final = (
    CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,
    CashFlowLineCode.PROVEN_BORROWING_PROCEEDS,
    CashFlowLineCode.PROVEN_DEBT_REPAYMENTS,
    CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT,
)
ELIGIBILITY_BRANCH_LINES: Final = (
    CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,
)
PPE_GROSS_LINES: Final = (
    CashFlowLineCode.PROVEN_PPE_ACQUISITIONS,
    CashFlowLineCode.PROVEN_PPE_DISPOSALS,
)
INTANGIBLE_GROSS_LINES: Final = (
    CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS,
    CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS,
)
BORROWING_GROSS_LINES: Final = (
    CashFlowLineCode.PROVEN_BORROWING_PROCEEDS,
    CashFlowLineCode.PROVEN_DEBT_REPAYMENTS,
)
TAX_BRIDGE_LINES: Final = (CashFlowLineCode.AUTHORITATIVE_INCOME_TAX_PAID,)
INTEREST_PAYABLE_BRIDGE_LINES: Final = (CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID,)
INTEREST_RECEIVABLE_BRIDGE_LINES: Final = (CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED,)
DIVIDEND_PAYABLE_BRIDGE_LINES: Final = (CashFlowLineCode.PROVEN_DIVIDENDS_PAID,)
DIVIDEND_RECEIVABLE_BRIDGE_LINES: Final = (CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED,)


_STATIC = CashFlowRoleSelectionRule.STATIC
_NO_CASH = CashFlowRoleSelectionRule.NO_CASH_FLOW_V1
_NA_WC = CashFlowWorkingCapitalKind.NOT_APPLICABLE
_NA_CASH = CashEligibilityRule.NOT_APPLICABLE
_UNCLASSIFIED_ACTIVITY = (CashFlowActivity.UNCLASSIFIED,)


def _behavior(
    role: CashFlowAccountRole,
    rule: CashFlowRoleSelectionRule,
    activity: CashFlowActivity | None,
    possible: tuple[CashFlowActivity, ...],
    lines: tuple[CashFlowLineCode, ...],
    normal: CashFlowNormalBalance | None,
    wc: CashFlowWorkingCapitalKind = _NA_WC,
    cash: CashEligibilityRule = _NA_CASH,
    gross: bool = False,
) -> CashFlowRoleBehavior:
    return CashFlowRoleBehavior(
        role=role,
        selection_rule=rule,
        static_activity=activity,
        possible_activities=possible,
        candidate_line_codes=lines,
        normal_balance=normal,
        working_capital_kind=wc,
        cash_eligibility_rule=cash,
        gross_movement_evidence_required=gross,
        model_version_introduced=CASH_FLOW_MODEL_VERSION,
    )


def _static(
    role: CashFlowAccountRole,
    activity: CashFlowActivity,
    lines: tuple[CashFlowLineCode, ...],
    normal: CashFlowNormalBalance | None,
    *,
    wc: CashFlowWorkingCapitalKind = _NA_WC,
    cash: CashEligibilityRule = _NA_CASH,
    gross: bool = False,
) -> CashFlowRoleBehavior:
    return _behavior(role, _STATIC, activity, (activity,), lines, normal, wc, cash, gross)


_BANK_ACTIVITIES = (
    CashFlowActivity.CASH_AND_CASH_EQUIVALENTS,
    CashFlowActivity.INVESTING,
    CashFlowActivity.FINANCING,
    CashFlowActivity.RECLASSIFICATION_EFFECT,
    CashFlowActivity.UNCLASSIFIED,
)
_ELIGIBILITY_ACTIVITIES = (
    CashFlowActivity.CASH_AND_CASH_EQUIVALENTS,
    CashFlowActivity.INVESTING,
)
_BRIDGE_ACTIVITIES = (
    CashFlowActivity.OPERATING,
    CashFlowActivity.INVESTING,
    CashFlowActivity.FINANCING,
)


CASH_FLOW_ROLE_BEHAVIOR_MANIFEST_V1: Final = (
    _static(CashFlowAccountRole.CASH_ON_HAND, CashFlowActivity.CASH_AND_CASH_EQUIVALENTS, OPENING_CLOSING, CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.AUTOMATIC_CASH),
    _behavior(CashFlowAccountRole.BANK_ACCOUNT_CANDIDATE, CashFlowRoleSelectionRule.BANK_ACCOUNT_BRANCH_V1, None, _BANK_ACTIVITIES, BANK_BRANCH_LINES, None, cash=CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE, gross=True),
    _behavior(CashFlowAccountRole.RESTRICTED_BANK_ASSET, CashFlowRoleSelectionRule.RESTRICTED_RECLASSIFICATION_V1, None, (CashFlowActivity.RECLASSIFICATION_EFFECT, CashFlowActivity.UNCLASSIFIED), (CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT,), CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.EXCLUDED, gross=True),
    _static(CashFlowAccountRole.DEMAND_DEPOSIT, CashFlowActivity.CASH_AND_CASH_EQUIVALENTS, OPENING_CLOSING, CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE),
    _behavior(CashFlowAccountRole.CASH_EQUIVALENT_INVESTMENT, CashFlowRoleSelectionRule.CASH_ELIGIBILITY_BRANCH_V1, None, _ELIGIBILITY_ACTIVITIES, ELIGIBILITY_BRANCH_LINES, CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE, gross=True),
    _static(CashFlowAccountRole.CHECK_RECEIVABLE, CashFlowActivity.OPERATING, (CashFlowLineCode.OTHER_OPERATING_ASSET_MOVEMENT,), CashFlowNormalBalance.DEBIT, wc=CashFlowWorkingCapitalKind.OPERATING_ASSET, cash=CashEligibilityRule.EXCLUDED),
    _static(CashFlowAccountRole.ISSUED_CHECK_OR_PAYMENT_ORDER, CashFlowActivity.UNCLASSIFIED, NO_LINES, CashFlowNormalBalance.CREDIT, cash=CashEligibilityRule.EXCLUDED),
    _static(CashFlowAccountRole.OTHER_LIQUID_ASSET_CANDIDATE, CashFlowActivity.UNCLASSIFIED, NO_LINES, CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.EXCLUDED),
    _static(CashFlowAccountRole.POS_RECEIVABLE, CashFlowActivity.OPERATING, (CashFlowLineCode.OTHER_OPERATING_ASSET_MOVEMENT,), CashFlowNormalBalance.DEBIT, wc=CashFlowWorkingCapitalKind.OPERATING_ASSET, cash=CashEligibilityRule.EXCLUDED),
    _static(CashFlowAccountRole.OPERATING_RECEIVABLE, CashFlowActivity.OPERATING, (CashFlowLineCode.TRADE_RECEIVABLES_MOVEMENT,), CashFlowNormalBalance.DEBIT, wc=CashFlowWorkingCapitalKind.OPERATING_ASSET),
    _static(CashFlowAccountRole.INVENTORY, CashFlowActivity.OPERATING, (CashFlowLineCode.INVENTORY_MOVEMENT,), CashFlowNormalBalance.DEBIT, wc=CashFlowWorkingCapitalKind.OPERATING_ASSET),
    _static(CashFlowAccountRole.OTHER_OPERATING_ASSET, CashFlowActivity.OPERATING, (CashFlowLineCode.OTHER_OPERATING_ASSET_MOVEMENT,), CashFlowNormalBalance.DEBIT, wc=CashFlowWorkingCapitalKind.OPERATING_ASSET),
    _static(CashFlowAccountRole.OPERATING_PAYABLE, CashFlowActivity.OPERATING, (CashFlowLineCode.TRADE_PAYABLES_MOVEMENT,), CashFlowNormalBalance.CREDIT, wc=CashFlowWorkingCapitalKind.OPERATING_LIABILITY),
    _static(CashFlowAccountRole.OTHER_OPERATING_LIABILITY, CashFlowActivity.OPERATING, (CashFlowLineCode.OTHER_OPERATING_LIABILITY_MOVEMENT,), CashFlowNormalBalance.CREDIT, wc=CashFlowWorkingCapitalKind.OPERATING_LIABILITY),
    _behavior(CashFlowAccountRole.PPE, CashFlowRoleSelectionRule.GROSS_OR_RESIDUAL_INVESTING_V1, None, (CashFlowActivity.INVESTING,), PPE_GROSS_LINES, CashFlowNormalBalance.DEBIT, gross=True),
    _behavior(CashFlowAccountRole.INTANGIBLE_ASSET, CashFlowRoleSelectionRule.GROSS_OR_RESIDUAL_INVESTING_V1, None, (CashFlowActivity.INVESTING,), INTANGIBLE_GROSS_LINES, CashFlowNormalBalance.DEBIT, gross=True),
    _behavior(CashFlowAccountRole.FINANCIAL_INVESTMENT, CashFlowRoleSelectionRule.CASH_ELIGIBILITY_BRANCH_V1, None, _ELIGIBILITY_ACTIVITIES, ELIGIBILITY_BRANCH_LINES, CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE, gross=True),
    _static(CashFlowAccountRole.EQUITY_FINANCIAL_INVESTMENT, CashFlowActivity.INVESTING, (CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,), CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.EXCLUDED, gross=True),
    _static(CashFlowAccountRole.LONG_TERM_FINANCIAL_INVESTMENT, CashFlowActivity.INVESTING, (CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,), CashFlowNormalBalance.DEBIT, cash=CashEligibilityRule.EXCLUDED, gross=True),
    _static(CashFlowAccountRole.NON_CASH_INVESTMENT_COMMITMENT, CashFlowActivity.UNCLASSIFIED, NO_LINES, CashFlowNormalBalance.CREDIT, cash=CashEligibilityRule.EXCLUDED),
    _behavior(CashFlowAccountRole.BORROWING, CashFlowRoleSelectionRule.GROSS_OR_RESIDUAL_FINANCING_V1, None, (CashFlowActivity.FINANCING,), BORROWING_GROSS_LINES, CashFlowNormalBalance.CREDIT, gross=True),
    _behavior(CashFlowAccountRole.EQUITY, CashFlowRoleSelectionRule.ACTUAL_CASH_EVIDENCE_V1, None, (CashFlowActivity.FINANCING,), (CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS,), CashFlowNormalBalance.CREDIT, gross=True),
    _static(CashFlowAccountRole.NON_CASH_EQUITY, CashFlowActivity.UNCLASSIFIED, NO_LINES, None),
    _behavior(CashFlowAccountRole.TAX_PAYABLE, CashFlowRoleSelectionRule.ACCRUAL_CASH_BRIDGE_V1, None, _BRIDGE_ACTIVITIES, TAX_BRIDGE_LINES, CashFlowNormalBalance.CREDIT, gross=True),
    _behavior(CashFlowAccountRole.TAX_RECEIVABLE, CashFlowRoleSelectionRule.ACCRUAL_CASH_BRIDGE_V1, None, _BRIDGE_ACTIVITIES, TAX_BRIDGE_LINES, CashFlowNormalBalance.DEBIT, gross=True),
    _behavior(CashFlowAccountRole.INTEREST_PAYABLE, CashFlowRoleSelectionRule.ACCRUAL_CASH_BRIDGE_V1, None, _BRIDGE_ACTIVITIES, INTEREST_PAYABLE_BRIDGE_LINES, CashFlowNormalBalance.CREDIT, gross=True),
    _behavior(CashFlowAccountRole.INTEREST_RECEIVABLE, CashFlowRoleSelectionRule.ACCRUAL_CASH_BRIDGE_V1, None, _BRIDGE_ACTIVITIES, INTEREST_RECEIVABLE_BRIDGE_LINES, CashFlowNormalBalance.DEBIT, gross=True),
    _behavior(CashFlowAccountRole.DIVIDEND_PAYABLE, CashFlowRoleSelectionRule.ACCRUAL_CASH_BRIDGE_V1, None, _BRIDGE_ACTIVITIES, DIVIDEND_PAYABLE_BRIDGE_LINES, CashFlowNormalBalance.CREDIT, gross=True),
    _behavior(CashFlowAccountRole.DIVIDEND_RECEIVABLE, CashFlowRoleSelectionRule.ACCRUAL_CASH_BRIDGE_V1, None, _BRIDGE_ACTIVITIES, DIVIDEND_RECEIVABLE_BRIDGE_LINES, CashFlowNormalBalance.DEBIT, gross=True),
    _behavior(CashFlowAccountRole.INTEREST_EXPENSE_ACCRUAL, CashFlowRoleSelectionRule.ACCRUAL_REVERSAL_V1, None, (CashFlowActivity.OPERATING,), (CashFlowLineCode.INTEREST_EXPENSE_ACCRUAL_REVERSAL,), None, gross=True),
    _behavior(CashFlowAccountRole.INTEREST_INCOME_ACCRUAL, CashFlowRoleSelectionRule.ACCRUAL_REVERSAL_V1, None, (CashFlowActivity.OPERATING,), (CashFlowLineCode.INTEREST_INCOME_ACCRUAL_REVERSAL,), None, gross=True),
    _behavior(CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL, CashFlowRoleSelectionRule.ACCRUAL_REVERSAL_V1, None, (CashFlowActivity.OPERATING,), (CashFlowLineCode.DIVIDEND_INCOME_ACCRUAL_REVERSAL,), None, gross=True),
    _behavior(CashFlowAccountRole.CURRENT_TAX_EXPENSE_ACCRUAL, CashFlowRoleSelectionRule.ACCRUAL_REVERSAL_V1, None, (CashFlowActivity.OPERATING,), (CashFlowLineCode.CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL,), None, gross=True),
    _static(CashFlowAccountRole.DEFERRED_TAX_ACCRUAL, CashFlowActivity.OPERATING, (CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS,), None, gross=True),
    _static(CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowActivity.OPERATING, (CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS,), None, gross=True),
    _static(CashFlowAccountRole.UNCLASSIFIED, CashFlowActivity.UNCLASSIFIED, NO_LINES, None),
)


_CODE_ROWS: Final = (
    ("cf100", "100", CashFlowAccountRole.CASH_ON_HAND, CashFlowNormalBalance.DEBIT),
    ("cf101", "101", CashFlowAccountRole.CHECK_RECEIVABLE, CashFlowNormalBalance.DEBIT),
    ("cf102", "102", CashFlowAccountRole.BANK_ACCOUNT_CANDIDATE, CashFlowNormalBalance.DEBIT),
    ("cf103", "103", CashFlowAccountRole.ISSUED_CHECK_OR_PAYMENT_ORDER, CashFlowNormalBalance.CREDIT),
    ("cf108", "108", CashFlowAccountRole.OTHER_LIQUID_ASSET_CANDIDATE, CashFlowNormalBalance.DEBIT),
    ("cf110", "110", CashFlowAccountRole.EQUITY_FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf111", "111", CashFlowAccountRole.FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf112", "112", CashFlowAccountRole.FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf118", "118", CashFlowAccountRole.FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf119", "119", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf120", "120", CashFlowAccountRole.OPERATING_RECEIVABLE, CashFlowNormalBalance.DEBIT),
    ("cf121", "121", CashFlowAccountRole.OPERATING_RECEIVABLE, CashFlowNormalBalance.DEBIT),
    ("cf15", "15", CashFlowAccountRole.INVENTORY, CashFlowNormalBalance.DEBIT),
    ("cf158", "158", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf159", "159", CashFlowAccountRole.OTHER_OPERATING_ASSET, CashFlowNormalBalance.DEBIT),
    ("cf180", "180", CashFlowAccountRole.OTHER_OPERATING_ASSET, CashFlowNormalBalance.DEBIT),
    ("cf190", "190", CashFlowAccountRole.OTHER_OPERATING_ASSET, CashFlowNormalBalance.DEBIT),
    ("cf191", "191", CashFlowAccountRole.OTHER_OPERATING_ASSET, CashFlowNormalBalance.DEBIT),
    ("cf192", "192", CashFlowAccountRole.OTHER_OPERATING_ASSET, CashFlowNormalBalance.DEBIT),
    ("cf240", "240", CashFlowAccountRole.LONG_TERM_FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf241", "241", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf242", "242", CashFlowAccountRole.LONG_TERM_FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf243", "243", CashFlowAccountRole.NON_CASH_INVESTMENT_COMMITMENT, CashFlowNormalBalance.CREDIT),
    ("cf244", "244", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf245", "245", CashFlowAccountRole.LONG_TERM_FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf246", "246", CashFlowAccountRole.NON_CASH_INVESTMENT_COMMITMENT, CashFlowNormalBalance.CREDIT),
    ("cf247", "247", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf248", "248", CashFlowAccountRole.LONG_TERM_FINANCIAL_INVESTMENT, CashFlowNormalBalance.DEBIT),
    ("cf249", "249", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf25", "25", CashFlowAccountRole.PPE, CashFlowNormalBalance.DEBIT),
    ("cf257", "257", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf26", "26", CashFlowAccountRole.INTANGIBLE_ASSET, CashFlowNormalBalance.DEBIT),
    ("cf268", "268", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
    ("cf300", "300", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf301", "301", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf303", "303", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf304", "304", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf305", "305", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf306", "306", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf309", "309", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf32", "32", CashFlowAccountRole.OPERATING_PAYABLE, CashFlowNormalBalance.CREDIT),
    ("cf322", "322", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.DEBIT),
    ("cf34", "34", CashFlowAccountRole.OTHER_OPERATING_LIABILITY, CashFlowNormalBalance.CREDIT),
    ("cf361", "361", CashFlowAccountRole.OTHER_OPERATING_LIABILITY, CashFlowNormalBalance.CREDIT),
    ("cf370", "370", CashFlowAccountRole.TAX_PAYABLE, CashFlowNormalBalance.CREDIT),
    ("cf371", "371", CashFlowAccountRole.TAX_RECEIVABLE, CashFlowNormalBalance.DEBIT),
    ("cf400", "400", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf401", "401", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf405", "405", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf407", "407", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf409", "409", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
    ("cf500", "500", CashFlowAccountRole.EQUITY, CashFlowNormalBalance.CREDIT),
    ("cf520", "520", CashFlowAccountRole.EQUITY, CashFlowNormalBalance.CREDIT),
    ("cf570", "570", CashFlowAccountRole.NON_CASH_EQUITY, CashFlowNormalBalance.CREDIT),
    ("cf580", "580", CashFlowAccountRole.NON_CASH_EQUITY, CashFlowNormalBalance.DEBIT),
    ("cf590", "590", CashFlowAccountRole.NON_CASH_EQUITY, CashFlowNormalBalance.CREDIT),
    ("cf591", "591", CashFlowAccountRole.NON_CASH_EQUITY, CashFlowNormalBalance.DEBIT),
    ("cf640", "640", CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL, CashFlowNormalBalance.CREDIT),
    ("cf641", "641", CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL, CashFlowNormalBalance.CREDIT),
    ("cf642", "642", CashFlowAccountRole.INTEREST_INCOME_ACCRUAL, CashFlowNormalBalance.CREDIT),
    ("cf691", "691", CashFlowAccountRole.CURRENT_TAX_EXPENSE_ACCRUAL, CashFlowNormalBalance.DEBIT),
)


_FAMILY_ROWS: Final = (
    (CashFlowAccountFamilyCode.PPE_NET, "investing_asset", CashFlowFamilyBalanceBasis.NET_CARRYING_ASSET, (("cf25", CashFlowFamilyMemberKind.ASSET_GROSS), ("cf257", CashFlowFamilyMemberKind.ASSET_CONTRA))),
    (CashFlowAccountFamilyCode.INTANGIBLE_NET, "investing_asset", CashFlowFamilyBalanceBasis.NET_CARRYING_ASSET, (("cf26", CashFlowFamilyMemberKind.ASSET_GROSS), ("cf268", CashFlowFamilyMemberKind.ASSET_CONTRA))),
    (CashFlowAccountFamilyCode.FINANCIAL_INVESTMENT_NET, "investing_asset", CashFlowFamilyBalanceBasis.NET_CARRYING_ASSET, tuple((mapping_id, CashFlowFamilyMemberKind.ASSET_GROSS) for mapping_id in ("cf110", "cf111", "cf112", "cf118", "cf240", "cf242", "cf245", "cf248")) + tuple((mapping_id, CashFlowFamilyMemberKind.ASSET_CONTRA) for mapping_id in ("cf119", "cf241", "cf244", "cf247", "cf249"))),
    (CashFlowAccountFamilyCode.BORROWING_GROSS, "financing_debt", CashFlowFamilyBalanceBasis.GROSS_LIABILITY_OBLIGATION, tuple((mapping_id, CashFlowFamilyMemberKind.LIABILITY_PRINCIPAL) for mapping_id in ("cf300", "cf301", "cf303", "cf304", "cf305", "cf306", "cf309", "cf400", "cf401", "cf405", "cf407", "cf409"))),
)


CASH_FLOW_ACCOUNT_FAMILY_MANIFEST_V1: Final = tuple(
    CashFlowAccountFamilyDefinition(
        family_code=family_code,
        domain=domain,
        balance_basis=balance_basis,
        members=members,
        model_version_introduced=CASH_FLOW_MODEL_VERSION,
    )
    for family_code, domain, balance_basis, members in _FAMILY_ROWS
)

_FAMILY_BY_MAPPING_ID = {
    mapping_id: (family_code, member_kind)
    for family_code, _domain, _basis, members in _FAMILY_ROWS
    for mapping_id, member_kind in members
}


def _mapping_entry(
    mapping_id: str,
    pattern: str | None,
    role: CashFlowAccountRole,
    normal: CashFlowNormalBalance | None,
    match_kind: CashFlowMappingMatchKind,
) -> CashFlowMappingEntry:
    family_code, member_kind = _FAMILY_BY_MAPPING_ID.get(mapping_id, (None, None))
    return CashFlowMappingEntry(
        mapping=CashFlowAccountMapping(
            mapping_id=mapping_id,
            match_kind=match_kind,
            account_code_or_prefix=pattern,
            explicit_account_role=role if match_kind is CashFlowMappingMatchKind.EXPLICIT_ACCOUNT_ROLE else None,
            resolved_account_role=role,
            code_normal_balance=normal,
            account_family_code=family_code,
            family_member_kind=member_kind,
            model_version_introduced=CASH_FLOW_MODEL_VERSION,
        ),
        registry_version=CASH_FLOW_MAPPING_REGISTRY_VERSION,
        effective_from=None,
        deprecated=False,
        replaced_by=None,
        source_reference="design.section10",
    )


CASH_FLOW_CODE_MAPPING_MANIFEST_V1: Final = tuple(
    _mapping_entry(mapping_id, pattern, role, normal, CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX)
    for mapping_id, pattern, role, normal in _CODE_ROWS
)
CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1: Final = tuple(
    _mapping_entry(
        f"role:{role.value}",
        None,
        role,
        None,
        CashFlowMappingMatchKind.EXPLICIT_ACCOUNT_ROLE,
    )
    for role in CashFlowAccountRole
)


def _canonical_entry(entry: CashFlowMappingEntry) -> dict[str, object]:
    mapping = entry.mapping
    return {
        "mapping_id": mapping.mapping_id,
        "match_kind": mapping.match_kind.value,
        "account_code_or_prefix": mapping.account_code_or_prefix,
        "explicit_account_role": mapping.explicit_account_role.value if mapping.explicit_account_role else None,
        "resolved_account_role": mapping.resolved_account_role.value,
        "code_normal_balance": mapping.code_normal_balance.value if mapping.code_normal_balance else None,
        "account_family_code": mapping.account_family_code.value if mapping.account_family_code else None,
        "family_member_kind": mapping.family_member_kind.value if mapping.family_member_kind else None,
        "model_version_introduced": mapping.model_version_introduced,
        "registry_version": entry.registry_version,
        "effective_from": entry.effective_from.isoformat() if entry.effective_from else None,
        "deprecated": entry.deprecated,
        "replaced_by": entry.replaced_by,
        "source_reference": entry.source_reference,
    }


def _canonical_behavior(behavior: CashFlowRoleBehavior) -> dict[str, object]:
    return {
        "role": behavior.role.value,
        "selection_rule": behavior.selection_rule.value,
        "static_activity": behavior.static_activity.value if behavior.static_activity else None,
        "possible_activities": [item.value for item in behavior.possible_activities],
        "candidate_line_codes": [item.value for item in behavior.candidate_line_codes],
        "normal_balance": behavior.normal_balance.value if behavior.normal_balance else None,
        "working_capital_kind": behavior.working_capital_kind.value,
        "cash_eligibility_rule": behavior.cash_eligibility_rule.value,
        "gross_movement_evidence_required": behavior.gross_movement_evidence_required,
        "model_version_introduced": behavior.model_version_introduced,
    }


def _canonical_family(family: CashFlowAccountFamilyDefinition) -> dict[str, object]:
    return {
        "family_code": family.family_code.value,
        "domain": family.domain,
        "balance_basis": family.balance_basis.value,
        "members": [[mapping_id, kind.value] for mapping_id, kind in family.members],
        "model_version_introduced": family.model_version_introduced,
    }


@dataclass(frozen=True, repr=False)
class CashFlowAccountMappingRegistry:
    registry_version: str
    entries: tuple[CashFlowMappingEntry, ...]
    role_behaviors: tuple[CashFlowRoleBehavior, ...]
    account_families: tuple[CashFlowAccountFamilyDefinition, ...]

    def __post_init__(self) -> None:
        if type(self.registry_version) is not str or not self.registry_version:
            raise CashFlowContractError("registry_version must be non-empty")
        if type(self.entries) is not tuple or type(self.role_behaviors) is not tuple or type(self.account_families) is not tuple:
            raise CashFlowContractError("registry manifests must be tuples")
        if any(type(item) is not CashFlowMappingEntry for item in self.entries):
            raise CashFlowContractError("registry contains an invalid mapping entry")
        if any(type(item) is not CashFlowRoleBehavior for item in self.role_behaviors):
            raise CashFlowContractError("registry contains an invalid role behavior")
        if any(type(item) is not CashFlowAccountFamilyDefinition for item in self.account_families):
            raise CashFlowContractError("registry contains an invalid family")

        entries = tuple(sorted(self.entries, key=lambda item: item.mapping.mapping_id))
        behaviors = tuple(sorted(self.role_behaviors, key=lambda item: item.role.value))
        families = tuple(sorted(self.account_families, key=lambda item: item.family_code.value))
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "role_behaviors", behaviors)
        object.__setattr__(self, "account_families", families)
        self._validate()

    def __repr__(self) -> str:
        return "CashFlowAccountMappingRegistry()"

    __str__ = __repr__

    def _validate(self) -> None:
        if any(entry.registry_version != self.registry_version for entry in self.entries):
            raise CashFlowContractError("mapping entry registry version mismatch")
        ids = [entry.mapping.mapping_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise CashFlowContractError("duplicate mapping_id")
        exact_patterns: set[str] = set()
        prefix_patterns: set[str] = set()
        explicit_roles: set[CashFlowAccountRole] = set()
        for entry in self.entries:
            mapping = entry.mapping
            if mapping.match_kind is CashFlowMappingMatchKind.EXACT_ACCOUNT_CODE:
                target = exact_patterns
            elif mapping.match_kind is CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX:
                target = prefix_patterns
            else:
                target = None
                role = mapping.explicit_account_role
                if role in explicit_roles:
                    raise CashFlowContractError("duplicate explicit role mapping")
                explicit_roles.add(role)
            if target is not None:
                pattern = mapping.account_code_or_prefix
                if pattern in target:
                    raise CashFlowContractError("duplicate account mapping pattern")
                target.add(pattern)
            if entry.deprecated and entry.replaced_by is None:
                raise CashFlowContractError("deprecated mapping requires replaced_by")
        id_set = set(ids)
        if any(entry.replaced_by not in id_set for entry in self.entries if entry.replaced_by is not None):
            raise CashFlowContractError("deprecated replacement target is missing")

        behavior_roles = [behavior.role for behavior in self.role_behaviors]
        if len(behavior_roles) != len(set(behavior_roles)):
            raise CashFlowContractError("duplicate role behavior")
        if set(behavior_roles) != set(CashFlowAccountRole):
            raise CashFlowContractError("role behavior manifest is not exhaustive")
        behavior_by_role = {behavior.role: behavior for behavior in self.role_behaviors}
        for entry in self.entries:
            mapping = entry.mapping
            behavior = behavior_by_role[mapping.resolved_account_role]
            if behavior.normal_balance is not None and mapping.code_normal_balance is not None:
                if behavior.normal_balance is not mapping.code_normal_balance:
                    raise CashFlowContractError("code and role normal balance conflict")

        family_codes = [family.family_code for family in self.account_families]
        if len(family_codes) != len(set(family_codes)):
            raise CashFlowContractError("duplicate account family")
        member_owner: dict[str, tuple[CashFlowAccountFamilyCode, CashFlowFamilyMemberKind]] = {}
        for family in self.account_families:
            for mapping_id, member_kind in family.members:
                if mapping_id in member_owner:
                    raise CashFlowContractError("mapping belongs to multiple family rows")
                member_owner[mapping_id] = (family.family_code, member_kind)
        if not set(member_owner).issubset(id_set):
            raise CashFlowContractError("family references an unknown mapping")
        for entry in self.entries:
            mapping = entry.mapping
            expected = member_owner.get(mapping.mapping_id)
            actual = (mapping.account_family_code, mapping.family_member_kind) if mapping.account_family_code else None
            if expected != actual:
                raise CashFlowContractError("mapping family metadata conflicts with family manifest")

    @property
    def canonical_bytes(self) -> bytes:
        payload = {
            "schema": "cf.account_mapping_registry.v1",
            "registry_version": self.registry_version,
            "entries": [_canonical_entry(entry) for entry in self.entries],
            "role_behaviors": [_canonical_behavior(behavior) for behavior in self.role_behaviors],
            "account_families": [_canonical_family(family) for family in self.account_families],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def canonical_digest(self) -> str:
        return sha256(b"cash-flow/account-mapping-registry/v1\0" + self.canonical_bytes).hexdigest()

    def behavior_for(self, role: CashFlowAccountRole) -> CashFlowRoleBehavior:
        if type(role) is not CashFlowAccountRole:
            raise CashFlowContractError("role must use CashFlowAccountRole")
        return next(behavior for behavior in self.role_behaviors if behavior.role is role)

    def family_reference_digest(self, family_code: CashFlowAccountFamilyCode) -> str:
        if type(family_code) is not CashFlowAccountFamilyCode:
            raise CashFlowContractError("family_code must use CashFlowAccountFamilyCode")
        family = next(
            (candidate for candidate in self.account_families if candidate.family_code is family_code),
            None,
        )
        if family is None:
            raise CashFlowContractError("account family is not registered")
        payload = {
            "schema": "cf.account_family.v1",
            "family_code": family.family_code.value,
            "domain": family.domain,
            "balance_basis": family.balance_basis.value,
            "mapping_registry_version": self.registry_version,
            "ordered_members": [[mapping_id, kind.value] for mapping_id, kind in family.members],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(b"cash-flow/account-family/v1\0" + encoded).hexdigest()

    @staticmethod
    def _initial_disposition(
        mapping: CashFlowAccountMapping | None,
        behavior: CashFlowRoleBehavior,
    ) -> CashFlowAccountDisposition:
        if behavior.role is CashFlowAccountRole.CASH_ON_HAND:
            return CashFlowAccountDisposition.CASH_OR_CASH_EQUIVALENT
        if behavior.working_capital_kind is not CashFlowWorkingCapitalKind.NOT_APPLICABLE:
            return CashFlowAccountDisposition.OPERATING_WORKING_CAPITAL
        if mapping is not None and mapping.account_family_code is not None:
            if mapping.account_family_code is CashFlowAccountFamilyCode.BORROWING_GROSS:
                return CashFlowAccountDisposition.FINANCING_FAMILY
            return CashFlowAccountDisposition.INVESTING_FAMILY
        return CashFlowAccountDisposition.UNRESOLVED

    def resolve(
        self,
        raw_account_code: str,
        *,
        explicit_account_role: CashFlowAccountRole | None = None,
        expected_registry_version: str | None = None,
    ) -> CashFlowMappingResolution:
        if expected_registry_version is not None and expected_registry_version != self.registry_version:
            raise CashFlowContractError("mapping registry version mismatch")
        if explicit_account_role is not None and type(explicit_account_role) is not CashFlowAccountRole:
            raise CashFlowContractError("explicit account role is invalid")
        code = normalize_account_code(raw_account_code)
        exact = tuple(
            entry for entry in self.entries
            if entry.mapping.match_kind is CashFlowMappingMatchKind.EXACT_ACCOUNT_CODE
            and entry.mapping.account_code_or_prefix == code
        )
        if exact:
            entry = exact[0]
        else:
            prefixes = tuple(
                entry for entry in self.entries
                if entry.mapping.match_kind is CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX
                and code.startswith(entry.mapping.account_code_or_prefix)
            )
            entry = max(prefixes, key=lambda item: len(item.mapping.account_code_or_prefix)) if prefixes else None
            if entry is None and explicit_account_role is not None:
                entry = next(
                    (candidate for candidate in self.entries
                     if candidate.mapping.match_kind is CashFlowMappingMatchKind.EXPLICIT_ACCOUNT_ROLE
                     and candidate.mapping.explicit_account_role is explicit_account_role),
                    None,
                )
        if entry is None:
            role = CashFlowAccountRole.UNCLASSIFIED
            behavior = self.behavior_for(role)
            return CashFlowMappingResolution(
                registry_version=self.registry_version,
                registry_digest=self.canonical_digest,
                canonical_account_code=code,
                match_kind=CashFlowMappingMatchKind.UNCLASSIFIED,
                mapping_id=None,
                resolved_account_role=role,
                code_normal_balance=None,
                role_behavior=behavior,
                account_family_code=None,
                family_member_kind=None,
                account_disposition=CashFlowAccountDisposition.UNRESOLVED,
                disposition_evidence_required=True,
                evidence_kind=CashFlowEvidenceKind.UNAVAILABLE,
                source_reference=None,
            )
        if entry.deprecated:
            raise CashFlowContractError("deprecated mapping cannot resolve")
        mapping = entry.mapping
        behavior = self.behavior_for(mapping.resolved_account_role)
        disposition = self._initial_disposition(mapping, behavior)
        return CashFlowMappingResolution(
            registry_version=self.registry_version,
            registry_digest=self.canonical_digest,
            canonical_account_code=code,
            match_kind=mapping.match_kind,
            mapping_id=mapping.mapping_id,
            resolved_account_role=mapping.resolved_account_role,
            code_normal_balance=mapping.code_normal_balance,
            role_behavior=behavior,
            account_family_code=mapping.account_family_code,
            family_member_kind=mapping.family_member_kind,
            account_disposition=disposition,
            disposition_evidence_required=disposition is CashFlowAccountDisposition.UNRESOLVED,
            evidence_kind=CashFlowEvidenceKind.EXACT,
            source_reference=entry.source_reference,
        )


def classify_bank_account_evidence(
    evidence: CashFlowBankAccountEvidence,
) -> CashFlowBankAccountClassification:
    """Apply the closed branch manifest without inspecting amount or account name."""

    if type(evidence) is not CashFlowBankAccountEvidence:
        raise CashFlowContractError("bank classification requires immutable evidence")
    maturity_limit = CASH_AND_CASH_EQUIVALENTS_POLICY_V1.maximum_maturity_days_at_acquisition
    demand = evidence.is_repayable_on_demand is True and evidence.is_restricted is False
    restricted_demand = (
        evidence.is_repayable_on_demand is True
        and evidence.is_restricted is True
        and evidence.restriction_preserves_cash_nature is True
    )
    equivalent = (
        evidence.is_repayable_on_demand is False
        and evidence.maturity_days_at_acquisition is not None
        and evidence.maturity_days_at_acquisition <= maturity_limit
        and evidence.ready_convertible_to_known_cash is True
        and evidence.insignificant_value_change_risk is True
        and evidence.held_for_short_term_cash_commitments is True
        and evidence.is_restricted is not None
        and (evidence.is_restricted is False or evidence.restriction_preserves_cash_nature is True)
    )
    restricted_excluded = (
        evidence.is_restricted is True
        and evidence.restriction_preserves_cash_nature is False
    )
    candidates = tuple(
        name for name, matched in (
            ("overdraft", evidence.authoritative_overdraft),
            ("demand", demand),
            ("restricted_demand", restricted_demand),
            ("cash_equivalent", equivalent),
            ("term", evidence.authoritative_term_or_investment_purpose),
            ("restricted_excluded", restricted_excluded),
        )
        if matched
    )
    if len(candidates) > 1:
        raise CashFlowContractError("bank evidence proves contradictory branches")
    if not candidates:
        return CashFlowBankAccountClassification(
            resolved_account_role=CashFlowAccountRole.BANK_ACCOUNT_CANDIDATE,
            availability_classification=CashAvailabilityClassification.ELIGIBILITY_UNRESOLVED,
            evidence_kind=CashFlowEvidenceKind.UNAVAILABLE,
        )
    branch = candidates[0]
    if branch == "overdraft":
        role = CashFlowAccountRole.BORROWING
        availability = None
    elif branch in {"demand", "restricted_demand"}:
        role = CashFlowAccountRole.DEMAND_DEPOSIT
        availability = (
            CashAvailabilityClassification.RESTRICTED_INCLUDED
            if branch == "restricted_demand"
            else CashAvailabilityClassification.UNRESTRICTED_INCLUDED
        )
    elif branch == "cash_equivalent":
        role = CashFlowAccountRole.CASH_EQUIVALENT_INVESTMENT
        availability = (
            CashAvailabilityClassification.RESTRICTED_INCLUDED
            if evidence.is_restricted
            else CashAvailabilityClassification.UNRESTRICTED_INCLUDED
        )
    elif branch == "term":
        role = CashFlowAccountRole.FINANCIAL_INVESTMENT
        availability = None
    else:
        role = CashFlowAccountRole.RESTRICTED_BANK_ASSET
        availability = CashAvailabilityClassification.RESTRICTED_EXCLUDED
    return CashFlowBankAccountClassification(
        resolved_account_role=role,
        availability_classification=availability,
        evidence_kind=CashFlowEvidenceKind.EXACT,
    )


CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1: Final = CashFlowAccountMappingRegistry(
    registry_version=CASH_FLOW_MAPPING_REGISTRY_VERSION,
    entries=CASH_FLOW_CODE_MAPPING_MANIFEST_V1 + CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1,
    role_behaviors=CASH_FLOW_ROLE_BEHAVIOR_MANIFEST_V1,
    account_families=CASH_FLOW_ACCOUNT_FAMILY_MANIFEST_V1,
)
CASH_FLOW_MAPPING_REGISTRY_DIGEST_V1: Final = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.canonical_digest
