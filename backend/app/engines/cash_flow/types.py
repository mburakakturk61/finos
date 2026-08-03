"""Milestone 4.5A cash-flow closed vocabularies and manifests.

This module is deliberately framework-free.  It contains no calculation,
source resolution, persistence, or account-mapping implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final, Literal, TypeAlias, Union
import unicodedata


CASH_FLOW_SCHEMA_VERSION: Final = "1.0.0"
CASH_FLOW_MODEL_VERSION: Final = "1.0.0"
CASH_FLOW_CURRENCY_CODE_V1: Final = "TRY"
CASH_FLOW_MONETARY_SCALE_V1: Final = 2
CASH_FLOW_COMPLETENESS_SCALE_V1: Final = 4
CASH_FLOW_SIGN_CONVENTION_V1: Final = "positive_inflow_negative_outflow"


class _SafeValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


CashFlowJsonScalar: TypeAlias = None | bool | str | int | Decimal
CashFlowJsonValue: TypeAlias = Union[
    CashFlowJsonScalar,
    tuple["CashFlowJsonValue", ...],
    "CashFlowJsonObject",
]


@dataclass(frozen=True, repr=False)
class CashFlowJsonObject(_SafeValue):
    items: tuple[tuple[str, CashFlowJsonValue], ...]

    def __post_init__(self) -> None:
        if type(self.items) is not tuple:
            raise ValueError("cash-flow JSON object items must be a tuple")
        keys: list[str] = []
        for item in self.items:
            if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str:
                raise ValueError("cash-flow JSON object entries must be (str, value) tuples")
            key = item[0]
            if not key or unicodedata.normalize("NFC", key) != key:
                raise ValueError("cash-flow JSON object keys must be non-empty NFC strings")
            _validate_json_value(item[1])
            keys.append(key)
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("cash-flow JSON object keys must be unique and sorted")


def _validate_json_value(value: CashFlowJsonValue) -> None:
    if value is None or type(value) in {bool, str, int}:
        return
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("cash-flow Decimal must be finite")
        return
    if type(value) is tuple:
        for item in value:
            _validate_json_value(item)
        return
    if type(value) is CashFlowJsonObject:
        return
    raise ValueError("unsupported mutable or non-canonical cash-flow JSON value")


class CashFlowMethod(str, Enum):
    INDIRECT = "indirect"


class CashFlowActivity(str, Enum):
    OPERATING = "operating"
    INVESTING = "investing"
    FINANCING = "financing"
    CASH_AND_CASH_EQUIVALENTS = "cash_and_cash_equivalents"
    FX_EFFECT = "fx_effect"
    RECLASSIFICATION_EFFECT = "reclassification_effect"
    RECONCILIATION = "reconciliation"
    UNCLASSIFIED = "unclassified"


class CashAvailabilityClassification(str, Enum):
    UNRESTRICTED_INCLUDED = "unrestricted_included"
    RESTRICTED_INCLUDED = "restricted_included"
    RESTRICTED_EXCLUDED = "restricted_excluded"
    ELIGIBILITY_UNRESOLVED = "eligibility_unresolved"


class CashFlowAvailabilityPeriodPosition(str, Enum):
    OPENING = "opening"
    CLOSING = "closing"


class CashFlowLineAggregationRole(str, Enum):
    PRESENTATION_CONTRIBUTOR = "presentation_contributor"
    SUBTOTAL = "subtotal"
    ANALYTIC = "analytic"
    RECONCILIATION = "reconciliation"


class CashFlowEvidenceKind(str, Enum):
    EXACT = "exact"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


# The approved Turkish task vocabulary uses "level" while the design's
# canonical schema name is "kind".  Both spellings identify the same closed
# enum; no second taxonomy is created.
CashFlowEvidenceLevel = CashFlowEvidenceKind


class CashFlowApplicability(str, Enum):
    APPLICABLE = "applicable"
    PROVEN_NOT_APPLICABLE = "proven_not_applicable"
    UNKNOWN = "unknown"


class CashFlowResultStatus(str, Enum):
    COMPLETE_RECONCILED = "complete_reconciled"
    COMPLETE_UNRECONCILED = "complete_unreconciled"
    PARTIAL_RECONCILED = "partial_reconciled"
    PARTIAL_UNRECONCILED = "partial_unreconciled"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"


CashFlowComputationStatus = CashFlowResultStatus


CashFlowResultBearingStatus: TypeAlias = Literal[
    CashFlowResultStatus.COMPLETE_RECONCILED,
    CashFlowResultStatus.COMPLETE_UNRECONCILED,
    CashFlowResultStatus.PARTIAL_RECONCILED,
    CashFlowResultStatus.PARTIAL_UNRECONCILED,
    CashFlowResultStatus.INSUFFICIENT_DATA,
]

CASH_FLOW_RESULT_BEARING_STATUS_MANIFEST: Final = tuple(CashFlowResultStatus)[:5]
CASH_FLOW_FAILURE_STATUS_MANIFEST: Final = tuple(CashFlowResultStatus)[5:]


class CashFlowReconciliationStatus(str, Enum):
    RECONCILED = "reconciled"
    ROUNDING_DIFFERENCE = "rounding_difference"
    UNRECONCILED_NON_MATERIAL = "unreconciled_non_material"
    UNRECONCILED_MATERIAL = "unreconciled_material"
    NOT_PERFORMED_INCOMPLETE_COMPONENTS = "not_performed_incomplete_components"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"


class CashFlowEndpointReconciliationStatus(str, Enum):
    MATCHED = "matched"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"


class CashFlowLineCode(str, Enum):
    OPENING_CASH_AND_CASH_EQUIVALENTS = "opening_cash_and_cash_equivalents"
    NET_PROFIT = "net_profit"
    DEPRECIATION_AND_AMORTIZATION = "depreciation_and_amortization"
    OTHER_PROVEN_NON_CASH_ADJUSTMENTS = "other_proven_non_cash_adjustments"
    NON_CASH_ADJUSTMENT_TOTAL = "non_cash_adjustment_total"
    INVENTORY_MOVEMENT = "inventory_movement"
    TRADE_RECEIVABLES_MOVEMENT = "trade_receivables_movement"
    OTHER_OPERATING_ASSET_MOVEMENT = "other_operating_asset_movement"
    TRADE_PAYABLES_MOVEMENT = "trade_payables_movement"
    OTHER_OPERATING_LIABILITY_MOVEMENT = "other_operating_liability_movement"
    WORKING_CAPITAL_MOVEMENT_TOTAL = "working_capital_movement_total"
    OTHER_PROVEN_OPERATING_ADJUSTMENTS = "other_proven_operating_adjustments"
    INTEREST_EXPENSE_ACCRUAL_REVERSAL = "interest_expense_accrual_reversal"
    INTEREST_INCOME_ACCRUAL_REVERSAL = "interest_income_accrual_reversal"
    DIVIDEND_INCOME_ACCRUAL_REVERSAL = "dividend_income_accrual_reversal"
    CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL = "current_tax_expense_accrual_reversal"
    OPERATING_CASH_FLOW = "operating_cash_flow"
    PROVEN_PPE_ACQUISITIONS = "proven_ppe_acquisitions"
    PROVEN_PPE_DISPOSALS = "proven_ppe_disposals"
    PROVEN_INTANGIBLE_ACQUISITIONS = "proven_intangible_acquisitions"
    PROVEN_INTANGIBLE_DISPOSALS = "proven_intangible_disposals"
    PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS = "proven_financial_investment_movements"
    ESTIMATED_NET_INVESTMENT_MOVEMENT = "estimated_net_investment_movement"
    INVESTING_CASH_FLOW = "investing_cash_flow"
    PROVEN_BORROWING_PROCEEDS = "proven_borrowing_proceeds"
    PROVEN_DEBT_REPAYMENTS = "proven_debt_repayments"
    ESTIMATED_NET_DEBT_MOVEMENT = "estimated_net_debt_movement"
    PROVEN_EQUITY_CONTRIBUTIONS = "proven_equity_contributions"
    PROVEN_DIVIDENDS_PAID = "proven_dividends_paid"
    FINANCING_CASH_FLOW = "financing_cash_flow"
    AUTHORITATIVE_INTEREST_PAID = "authoritative_interest_paid"
    AUTHORITATIVE_INTEREST_RECEIVED = "authoritative_interest_received"
    AUTHORITATIVE_DIVIDENDS_RECEIVED = "authoritative_dividends_received"
    AUTHORITATIVE_INCOME_TAX_PAID = "authoritative_income_tax_paid"
    AUTHORITATIVE_FX_EFFECT = "authoritative_fx_effect"
    AUTHORITATIVE_RECLASSIFICATION_EFFECT = "authoritative_reclassification_effect"
    CALCULATED_NET_CASH_CHANGE = "calculated_net_cash_change"
    CLOSING_CASH_AND_CASH_EQUIVALENTS = "closing_cash_and_cash_equivalents"
    BALANCE_SHEET_NET_CASH_CHANGE = "balance_sheet_net_cash_change"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"
    FREE_CASH_FLOW = "free_cash_flow"


class CashFlowSourceRole(str, Enum):
    CURRENT_BALANCE_SHEET = "current_balance_sheet"
    PRIOR_BALANCE_SHEET = "prior_balance_sheet"
    CURRENT_INCOME_STATEMENT = "current_income_statement"
    CURRENT_TRIAL_BALANCE = "current_trial_balance"
    PRIOR_TRIAL_BALANCE = "prior_trial_balance"


class CashFlowSourceMode(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"


class CashFlowMappingMatchKind(str, Enum):
    EXACT_ACCOUNT_CODE = "exact_account_code"
    LONGEST_ACCOUNT_CODE_PREFIX = "longest_account_code_prefix"
    EXPLICIT_ACCOUNT_ROLE = "explicit_account_role"
    UNCLASSIFIED = "unclassified"


class CashFlowRoleSelectionRule(str, Enum):
    STATIC = "static"
    BANK_ACCOUNT_BRANCH_V1 = "bank_account_branch_v1"
    CASH_ELIGIBILITY_BRANCH_V1 = "cash_eligibility_branch_v1"
    GROSS_OR_RESIDUAL_INVESTING_V1 = "gross_or_residual_investing_v1"
    GROSS_OR_RESIDUAL_FINANCING_V1 = "gross_or_residual_financing_v1"
    ACTUAL_CASH_EVIDENCE_V1 = "actual_cash_evidence_v1"
    ACCRUAL_CASH_BRIDGE_V1 = "accrual_cash_bridge_v1"
    ACCRUAL_REVERSAL_V1 = "accrual_reversal_v1"
    RESTRICTED_RECLASSIFICATION_V1 = "restricted_reclassification_v1"
    NO_CASH_FLOW_V1 = "no_cash_flow_v1"


class CashFlowAccountRole(str, Enum):
    CASH_ON_HAND = "cash_on_hand"
    BANK_ACCOUNT_CANDIDATE = "bank_account_candidate"
    RESTRICTED_BANK_ASSET = "restricted_bank_asset"
    DEMAND_DEPOSIT = "demand_deposit"
    CASH_EQUIVALENT_INVESTMENT = "cash_equivalent_investment"
    CHECK_RECEIVABLE = "check_receivable"
    ISSUED_CHECK_OR_PAYMENT_ORDER = "issued_check_or_payment_order"
    OTHER_LIQUID_ASSET_CANDIDATE = "other_liquid_asset_candidate"
    POS_RECEIVABLE = "pos_receivable"
    OPERATING_RECEIVABLE = "operating_receivable"
    INVENTORY = "inventory"
    OTHER_OPERATING_ASSET = "other_operating_asset"
    OPERATING_PAYABLE = "operating_payable"
    OTHER_OPERATING_LIABILITY = "other_operating_liability"
    PPE = "ppe"
    INTANGIBLE_ASSET = "intangible_asset"
    FINANCIAL_INVESTMENT = "financial_investment"
    EQUITY_FINANCIAL_INVESTMENT = "equity_financial_investment"
    LONG_TERM_FINANCIAL_INVESTMENT = "long_term_financial_investment"
    NON_CASH_INVESTMENT_COMMITMENT = "non_cash_investment_commitment"
    BORROWING = "borrowing"
    EQUITY = "equity"
    NON_CASH_EQUITY = "non_cash_equity"
    TAX_PAYABLE = "tax_payable"
    TAX_RECEIVABLE = "tax_receivable"
    INTEREST_PAYABLE = "interest_payable"
    INTEREST_RECEIVABLE = "interest_receivable"
    DIVIDEND_PAYABLE = "dividend_payable"
    DIVIDEND_RECEIVABLE = "dividend_receivable"
    INTEREST_EXPENSE_ACCRUAL = "interest_expense_accrual"
    INTEREST_INCOME_ACCRUAL = "interest_income_accrual"
    DIVIDEND_INCOME_ACCRUAL = "dividend_income_accrual"
    CURRENT_TAX_EXPENSE_ACCRUAL = "current_tax_expense_accrual"
    DEFERRED_TAX_ACCRUAL = "deferred_tax_accrual"
    NON_CASH_ADJUSTMENT = "non_cash_adjustment"
    UNCLASSIFIED = "unclassified"


class CashFlowAccountDisposition(str, Enum):
    CASH_OR_CASH_EQUIVALENT = "cash_or_cash_equivalent"
    OPERATING_WORKING_CAPITAL = "operating_working_capital"
    INVESTING_FAMILY = "investing_family"
    FINANCING_FAMILY = "financing_family"
    PNL_CAPTURED_IN_NET_PROFIT = "pnl_captured_in_net_profit"
    PROVEN_NON_CASH = "proven_non_cash"
    PROVEN_NOT_RELEVANT = "proven_not_relevant"
    UNRESOLVED = "unresolved"


class CashFlowAccountFamilyCode(str, Enum):
    PPE_NET = "ppe_net"
    INTANGIBLE_NET = "intangible_net"
    FINANCIAL_INVESTMENT_NET = "financial_investment_net"
    BORROWING_GROSS = "borrowing_gross"


class CashFlowFamilyBalanceBasis(str, Enum):
    NET_CARRYING_ASSET = "net_carrying_asset"
    GROSS_LIABILITY_OBLIGATION = "gross_liability_obligation"


class CashFlowFamilyMemberKind(str, Enum):
    ASSET_GROSS = "asset_gross"
    ASSET_CONTRA = "asset_contra"
    LIABILITY_PRINCIPAL = "liability_principal"
    LIABILITY_CONTRA = "liability_contra"


class CashFlowNormalBalance(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class CashFlowWorkingCapitalKind(str, Enum):
    OPERATING_ASSET = "operating_asset"
    OPERATING_LIABILITY = "operating_liability"
    NOT_APPLICABLE = "not_applicable"


class CashEligibilityRule(str, Enum):
    AUTOMATIC_CASH = "automatic_cash"
    REQUIRES_ELIGIBILITY_EVIDENCE = "requires_eligibility_evidence"
    EXCLUDED = "excluded"
    NOT_APPLICABLE = "not_applicable"


class CashFlowStatementBasis(str, Enum):
    AS_OF = "as_of"
    FLOW_INTERVAL = "flow_interval"


class CashFlowAccountingBasisCode(str, Enum):
    TR_TDHP_ACCRUAL = "tr_tdhp_accrual"


class CashFlowBalanceSemantics(str, Enum):
    CLOSING_BALANCE = "closing_balance"
    PERIOD_MOVEMENT = "period_movement"
    UNKNOWN = "unknown"


class CashFlowZeroBalanceOmissionPolicy(str, Enum):
    EXPLICIT_ZERO_ROWS = "explicit_zero_rows"
    COMPLETE_SNAPSHOT_OMITS_ZERO = "complete_snapshot_omits_zero"
    UNKNOWN = "unknown"


class CashFlowDerivationCode(str, Enum):
    SOURCE_VALUE = "source_value"
    BALANCE_DELTA = "balance_delta"
    OPERATING_ASSET_SIGN_INVERSION = "operating_asset_sign_inversion"
    OPERATING_LIABILITY_SIGN_PRESERVED = "operating_liability_sign_preserved"
    NET_PROFIT_ACCRUAL_REVERSAL = "net_profit_accrual_reversal"
    INDIRECT_OPERATING_SUBTOTAL = "indirect_operating_subtotal"
    INVESTING_SUBTOTAL = "investing_subtotal"
    FINANCING_SUBTOTAL = "financing_subtotal"
    PRESENTATION_RECLASSIFICATION = "presentation_reclassification"
    NET_CASH_CHANGE_SUM = "net_cash_change_sum"
    BALANCE_SHEET_CASH_DELTA = "balance_sheet_cash_delta"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"
    FREE_CASH_FLOW_FROM_PROVEN_CAPEX = "free_cash_flow_from_proven_capex"


class CashFlowNonCashBridgeDomain(str, Enum):
    INVESTING_ASSET = "investing_asset"
    FINANCING_DEBT = "financing_debt"


class CashFlowNonCashBridgeKind(str, Enum):
    DEPRECIATION_OR_AMORTIZATION = "depreciation_or_amortization"
    IMPAIRMENT = "impairment"
    REVALUATION = "revaluation"
    TRANSFER_OR_RECLASSIFICATION = "transfer_or_reclassification"
    DISPOSAL_GAIN_OR_LOSS = "disposal_gain_or_loss"
    FX_OR_TRANSLATION = "fx_or_translation"
    NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION = "non_cash_acquisition_or_lease_recognition"
    LEASE_MODIFICATION = "lease_modification"
    DEBT_TO_EQUITY_CONVERSION = "debt_to_equity_conversion"
    CAPITALIZED_INTEREST = "capitalized_interest"


class DependencyFailureBehavior(str, Enum):
    SKIP = "skip"
    INVOKE_DIAGNOSTIC_ONLY = "invoke_diagnostic_only"


class CashFlowWarningCode(str, Enum):
    MINIMUM_DATA_INCOMPLETE = "minimum_data_incomplete"
    ACCOUNT_UNCLASSIFIED = "account_unclassified"
    CASH_EQUIVALENT_ELIGIBILITY_UNPROVEN = "cash_equivalent_eligibility_unproven"
    NON_CASH_ADJUSTMENT_UNAVAILABLE = "non_cash_adjustment_unavailable"
    GROSS_MOVEMENT_UNAVAILABLE = "gross_movement_unavailable"
    ESTIMATED_NET_MOVEMENT_USED = "estimated_net_movement_used"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"
    MATERIAL_RECONCILIATION_DIFFERENCE = "material_reconciliation_difference"
    PRESENTATION_EVIDENCE_UNAVAILABLE = "presentation_evidence_unavailable"
    NEGATIVE_CASH_BALANCE = "negative_cash_balance"
    OVERDRAFT_RECLASSIFIED_TO_FINANCING = "overdraft_reclassified_to_financing"


class CashFlowErrorCode(str, Enum):
    INVALID_CONTRACT = "invalid_contract"
    PERIOD_NOT_COMPARABLE = "period_not_comparable"
    PERIOD_SELECTION_AMBIGUOUS = "period_selection_ambiguous"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_SCOPE_MISMATCH = "source_scope_mismatch"
    SOURCE_STATUS_INVALID = "source_status_invalid"
    SOURCE_DIGEST_MISMATCH = "source_digest_mismatch"
    SOURCE_CURRENCY_MISMATCH = "source_currency_mismatch"
    SOURCE_EVIDENCE_CONFLICT = "source_evidence_conflict"
    POLICY_VERSION_UNSUPPORTED = "policy_version_unsupported"
    MAPPING_REGISTRY_VERSION_UNSUPPORTED = "mapping_registry_version_unsupported"
    MAPPING_CONFLICT = "mapping_conflict"
    DECIMAL_NON_FINITE_OR_SCALE_INVALID = "decimal_non_finite_or_scale_invalid"
    PERSISTENCE_INTEGRITY_FAILURE = "persistence_integrity_failure"
    SOURCE_RESOLUTION_UNAVAILABLE = "source_resolution_unavailable"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"


CASH_FLOW_LINE_ITEM_MANIFEST_V1: Final = tuple(CashFlowLineCode)
CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1: Final = (
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
CASH_FLOW_OPTIONAL_ANALYTICS_MANIFEST_V1: Final = (CashFlowLineCode.FREE_CASH_FLOW,)


_CONTRIBUTOR_CODES = {
    CashFlowLineCode.NET_PROFIT,
    CashFlowLineCode.DEPRECIATION_AND_AMORTIZATION,
    CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS,
    CashFlowLineCode.INVENTORY_MOVEMENT,
    CashFlowLineCode.TRADE_RECEIVABLES_MOVEMENT,
    CashFlowLineCode.OTHER_OPERATING_ASSET_MOVEMENT,
    CashFlowLineCode.TRADE_PAYABLES_MOVEMENT,
    CashFlowLineCode.OTHER_OPERATING_LIABILITY_MOVEMENT,
    CashFlowLineCode.OTHER_PROVEN_OPERATING_ADJUSTMENTS,
    CashFlowLineCode.INTEREST_EXPENSE_ACCRUAL_REVERSAL,
    CashFlowLineCode.INTEREST_INCOME_ACCRUAL_REVERSAL,
    CashFlowLineCode.DIVIDEND_INCOME_ACCRUAL_REVERSAL,
    CashFlowLineCode.CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL,
    CashFlowLineCode.PROVEN_PPE_ACQUISITIONS,
    CashFlowLineCode.PROVEN_PPE_DISPOSALS,
    CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS,
    CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS,
    CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,
    CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT,
    CashFlowLineCode.PROVEN_BORROWING_PROCEEDS,
    CashFlowLineCode.PROVEN_DEBT_REPAYMENTS,
    CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT,
    CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS,
    CashFlowLineCode.PROVEN_DIVIDENDS_PAID,
    CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID,
    CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED,
    CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED,
    CashFlowLineCode.AUTHORITATIVE_INCOME_TAX_PAID,
    CashFlowLineCode.AUTHORITATIVE_FX_EFFECT,
    CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT,
}
_SUBTOTAL_CODES = {
    CashFlowLineCode.NON_CASH_ADJUSTMENT_TOTAL,
    CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL,
    CashFlowLineCode.OPERATING_CASH_FLOW,
    CashFlowLineCode.INVESTING_CASH_FLOW,
    CashFlowLineCode.FINANCING_CASH_FLOW,
    CashFlowLineCode.CALCULATED_NET_CASH_CHANGE,
    CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE,
}
_RECONCILIATION_CODES = {
    CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.RECONCILIATION_DIFFERENCE,
}
CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1: Final = tuple(
    (
        code,
        CashFlowLineAggregationRole.PRESENTATION_CONTRIBUTOR
        if code in _CONTRIBUTOR_CODES
        else CashFlowLineAggregationRole.SUBTOTAL
        if code in _SUBTOTAL_CODES
        else CashFlowLineAggregationRole.RECONCILIATION
        if code in _RECONCILIATION_CODES
        else CashFlowLineAggregationRole.ANALYTIC,
    )
    for code in CashFlowLineCode
)


CASH_FLOW_NON_POSITIVE_LINE_CODES_V1: Final = frozenset(
    {
        CashFlowLineCode.PROVEN_PPE_ACQUISITIONS,
        CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS,
        CashFlowLineCode.PROVEN_DEBT_REPAYMENTS,
        CashFlowLineCode.PROVEN_DIVIDENDS_PAID,
        CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID,
    }
)
CASH_FLOW_NON_NEGATIVE_LINE_CODES_V1: Final = frozenset(
    {
        CashFlowLineCode.PROVEN_PPE_DISPOSALS,
        CashFlowLineCode.PROVEN_INTANGIBLE_DISPOSALS,
        CashFlowLineCode.PROVEN_BORROWING_PROCEEDS,
        CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS,
        CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED,
        CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED,
    }
)

CASH_FLOW_EVIDENCE_RANK_V1: Final = {
    CashFlowEvidenceKind.EXACT: 0,
    CashFlowEvidenceKind.DERIVED: 1,
    CashFlowEvidenceKind.ESTIMATED: 2,
    CashFlowEvidenceKind.UNAVAILABLE: 3,
}


def evidence_transition_allowed(
    source: CashFlowEvidenceKind, target: CashFlowEvidenceKind
) -> bool:
    """Return true only when reliability is preserved or degraded."""

    return CASH_FLOW_EVIDENCE_RANK_V1[target] >= CASH_FLOW_EVIDENCE_RANK_V1[source]
