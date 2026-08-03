"""Additive, versioned application contracts for Cash Flow orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Generic, Literal, TypeVar
from uuid import UUID

from app.analysis_application.contracts import (
    AnalysisErrorCode,
    AnalysisInputsDTO,
    AnalysisRunOptionsDTO,
    ApplicationAuditContextDTO,
    ApplicationErrorCategory,
    ApplicationExecutionStatus,
    ApplicationScopeDTO,
    ApplicationStatus,
    ApplicationWarningCode,
    CancellationStatus,
    CompanyMetadataDTO,
    DashboardRequestDTO,
    ExecutionCategory,
    FinancialComputationStatus,
    PayloadOwnerType,
    PriorPeriodProjectionDTO,
    RenderContractRequestDTO,
    ReportRequestDTO,
    validate_application_json,
)

APPLICATION_DTO_SCHEMA_VERSION_V2 = "2.0.0"
SUPPORTED_APPLICATION_DTO_SCHEMA_VERSIONS = ("1.0.0", APPLICATION_DTO_SCHEMA_VERSION_V2)


class ApplicationEngineCodeV2(str, Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    CASH_FLOW = "cash_flow"
    RATIO = "ratio"
    BENCHMARK = "benchmark"
    HEALTH_SCORE = "health_score"
    CREDIT_SCORE = "credit_score"
    RECOMMENDATION = "recommendation"
    EXECUTIVE_REPORT = "executive_report"
    DASHBOARD = "dashboard"
    RENDER_CONTRACT = "render_contract"


class ApplicationFinancialSourceModeV2(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"


class ApplicationFinancialSourceRoleV2(str, Enum):
    PRIMARY_DOCUMENT = "primary_document"
    SUPPORTING_DOCUMENT = "supporting_document"
    PRIMARY_ANALYSIS = "primary_analysis"
    SUPPORTING_ANALYSIS = "supporting_analysis"
    TRIAL_BALANCE_FALLBACK = "trial_balance_fallback"
    PRIOR_PERIOD_REFERENCE = "prior_period_reference"


class ApplicationCashFlowMethodV2(str, Enum):
    INDIRECT = "indirect"


class ApplicationCashFlowPresentationProfileV2(str, Enum):
    TMS_TFRS_2024_INDIRECT_V1 = "tms_tfrs_2024_indirect_v1"
    BANK_CREDIT_V1 = "bank_credit_v1"
    MANAGEMENT_V1 = "management_v1"


@dataclass(frozen=True)
class FinancialSourceReferenceDTOV2:
    role: ApplicationFinancialSourceRoleV2
    source_document_id: UUID | None
    source_analysis_result_id: UUID | None
    source_engine_code: ApplicationEngineCodeV2 | None

    def __post_init__(self) -> None:
        if sum(x is not None for x in (self.source_document_id, self.source_analysis_result_id, self.source_engine_code)) != 1:
            raise ValueError("financial source locator must be exact XOR")


@dataclass(frozen=True)
class FinancialSourceIntentDTOV2:
    engine_code: ApplicationEngineCodeV2
    company_id: UUID
    financial_period_id: UUID
    primary_document_id: UUID | None
    source_bindings: tuple[FinancialSourceReferenceDTOV2, ...]
    requested_source_mode: ApplicationFinancialSourceModeV2
    allow_existing_canonical_owner: bool
    expected_existing_owner_id: UUID | None
    provenance_metadata: object
    caller_supplied_business_timestamp: datetime | None

    def __post_init__(self) -> None:
        if self.engine_code not in {ApplicationEngineCodeV2.FS_BALANCE_SHEET, ApplicationEngineCodeV2.FS_INCOME_STATEMENT, ApplicationEngineCodeV2.RATIO}:
            raise ValueError("Cash Flow owner assembly is not caller controlled")
        if self.expected_existing_owner_id is not None and not self.allow_existing_canonical_owner:
            raise ValueError("existing owner assertion requires reuse permission")
        validate_application_json(self.provenance_metadata)
        keys = tuple((x.role, x.source_document_id, x.source_analysis_result_id, x.source_engine_code) for x in self.source_bindings)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate source binding")


@dataclass(frozen=True)
class CashFlowRequestDTOV2:
    method: ApplicationCashFlowMethodV2
    current_period_id: UUID
    expected_prior_period_id: UUID | None
    presentation_profile: ApplicationCashFlowPresentationProfileV2
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    mapping_registry_version: str
    reconciliation_policy_version: str
    cash_flow_contract_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.method is not ApplicationCashFlowMethodV2.INDIRECT or self.cash_flow_contract_version != "1.0.0":
            raise ValueError("unsupported Cash Flow application request")
        if any(not x for x in (self.accounting_policy_version, self.cash_equivalent_policy_version, self.mapping_registry_version, self.reconciliation_policy_version)):
            raise ValueError("Cash Flow policy versions are required")


@dataclass(frozen=True)
class StartAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV2, ...]
    cash_flow_request: CashFlowRequestDTOV2 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "2.0.0"

    def __post_init__(self) -> None:
        _validate_execution_command(self)


@dataclass(frozen=True)
class ResumeAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV2, ...]
    cash_flow_request: CashFlowRequestDTOV2 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "2.0.0"

    def __post_init__(self) -> None:
        _validate_execution_command(self, previous=True)


@dataclass(frozen=True)
class RetryAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV2, ...]
    cash_flow_request: CashFlowRequestDTOV2 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "2.0.0"

    def __post_init__(self) -> None:
        _validate_execution_command(self, previous=True)


def _validate_execution_command(command: object, *, previous: bool = False) -> None:
    if getattr(command, "application_contract_version") != "2.0.0":
        raise ValueError("unknown application contract version")
    outputs = getattr(command, "requested_outputs")
    if type(outputs) is not tuple or not outputs or len(outputs) != len(set(outputs)) or any(type(x) is not ApplicationEngineCodeV2 for x in outputs):
        raise ValueError("requested outputs must be a unique V2 tuple")
    wants_cash_flow = ApplicationEngineCodeV2.CASH_FLOW in outputs
    if wants_cash_flow != (getattr(command, "cash_flow_request") is not None):
        raise ValueError("Cash Flow output and request must be present together")
    if wants_cash_flow and getattr(command, "cash_flow_request").current_period_id != getattr(command, "scope").financial_period_id:
        raise ValueError("Cash Flow current period differs from application scope")
    if previous and (not getattr(command, "scope").previous_run_id or getattr(command, "scope").previous_run_id == getattr(command, "run_id")):
        raise ValueError("resume/retry requires a distinct previous run")


@dataclass(frozen=True)
class CancelAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = "2.0.0"


@dataclass(frozen=True)
class GetAnalysisStatusQueryV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = "2.0.0"


@dataclass(frozen=True)
class GetAnalysisResultQueryV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    include_payloads: bool
    application_contract_version: str = "2.0.0"


@dataclass(frozen=True)
class GetExecutionDetailQueryV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    engine_code: ApplicationEngineCodeV2
    include_payload: bool
    application_contract_version: str = "2.0.0"


@dataclass(frozen=True)
class ListAnalysisHistoryQueryV2:
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    cursor: str | None
    limit: int
    application_contract_version: str = "2.0.0"


class ApplicationCashFlowStatusV2(str, Enum):
    COMPLETE_RECONCILED = "complete_reconciled"
    COMPLETE_UNRECONCILED = "complete_unreconciled"
    PARTIAL_RECONCILED = "partial_reconciled"
    PARTIAL_UNRECONCILED = "partial_unreconciled"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"


ApplicationCashFlowResultBearingStatusV2 = Literal[
    ApplicationCashFlowStatusV2.COMPLETE_RECONCILED,
    ApplicationCashFlowStatusV2.COMPLETE_UNRECONCILED,
    ApplicationCashFlowStatusV2.PARTIAL_RECONCILED,
    ApplicationCashFlowStatusV2.PARTIAL_UNRECONCILED,
    ApplicationCashFlowStatusV2.INSUFFICIENT_DATA,
]


class ApplicationCashFlowReconciliationStatusV2(str, Enum):
    RECONCILED = "reconciled"
    ROUNDING_DIFFERENCE = "rounding_difference"
    UNRECONCILED_NON_MATERIAL = "unreconciled_non_material"
    UNRECONCILED_MATERIAL = "unreconciled_material"
    NOT_PERFORMED_INCOMPLETE_COMPONENTS = "not_performed_incomplete_components"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"


class ApplicationCashFlowEvidenceKindV2(str, Enum):
    EXACT = "exact"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class ApplicationCashFlowApplicabilityV2(str, Enum):
    APPLICABLE = "applicable"
    PROVEN_NOT_APPLICABLE = "proven_not_applicable"
    UNKNOWN = "unknown"


class ApplicationCashFlowActivityV2(str, Enum):
    OPERATING = "operating"
    INVESTING = "investing"
    FINANCING = "financing"
    CASH_AND_CASH_EQUIVALENTS = "cash_and_cash_equivalents"
    FX_EFFECT = "fx_effect"
    RECLASSIFICATION_EFFECT = "reclassification_effect"
    RECONCILIATION = "reconciliation"
    UNCLASSIFIED = "unclassified"


class ApplicationCashAvailabilityClassificationV2(str, Enum):
    UNRESTRICTED_INCLUDED = "unrestricted_included"
    RESTRICTED_INCLUDED = "restricted_included"
    RESTRICTED_EXCLUDED = "restricted_excluded"
    ELIGIBILITY_UNRESOLVED = "eligibility_unresolved"


class ApplicationCashFlowLineAggregationRoleV2(str, Enum):
    PRESENTATION_CONTRIBUTOR = "presentation_contributor"
    SUBTOTAL = "subtotal"
    ANALYTIC = "analytic"
    RECONCILIATION = "reconciliation"


class ApplicationCashFlowAvailabilityPeriodPositionV2(str, Enum):
    OPENING = "opening"
    CLOSING = "closing"


class ApplicationCashFlowEndpointReconciliationStatusV2(str, Enum):
    MATCHED = "matched"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"


APPLICATION_CASH_FLOW_LINE_CODE_MEMBER_PAIRS_V2 = (
    ("OPENING_CASH_AND_CASH_EQUIVALENTS", "opening_cash_and_cash_equivalents"), ("NET_PROFIT", "net_profit"),
    ("DEPRECIATION_AND_AMORTIZATION", "depreciation_and_amortization"), ("OTHER_PROVEN_NON_CASH_ADJUSTMENTS", "other_proven_non_cash_adjustments"),
    ("NON_CASH_ADJUSTMENT_TOTAL", "non_cash_adjustment_total"), ("INVENTORY_MOVEMENT", "inventory_movement"),
    ("TRADE_RECEIVABLES_MOVEMENT", "trade_receivables_movement"), ("OTHER_OPERATING_ASSET_MOVEMENT", "other_operating_asset_movement"),
    ("TRADE_PAYABLES_MOVEMENT", "trade_payables_movement"), ("OTHER_OPERATING_LIABILITY_MOVEMENT", "other_operating_liability_movement"),
    ("WORKING_CAPITAL_MOVEMENT_TOTAL", "working_capital_movement_total"), ("OTHER_PROVEN_OPERATING_ADJUSTMENTS", "other_proven_operating_adjustments"),
    ("INTEREST_EXPENSE_ACCRUAL_REVERSAL", "interest_expense_accrual_reversal"), ("INTEREST_INCOME_ACCRUAL_REVERSAL", "interest_income_accrual_reversal"),
    ("DIVIDEND_INCOME_ACCRUAL_REVERSAL", "dividend_income_accrual_reversal"), ("CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL", "current_tax_expense_accrual_reversal"),
    ("OPERATING_CASH_FLOW", "operating_cash_flow"), ("PROVEN_PPE_ACQUISITIONS", "proven_ppe_acquisitions"),
    ("PROVEN_PPE_DISPOSALS", "proven_ppe_disposals"), ("PROVEN_INTANGIBLE_ACQUISITIONS", "proven_intangible_acquisitions"),
    ("PROVEN_INTANGIBLE_DISPOSALS", "proven_intangible_disposals"), ("PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS", "proven_financial_investment_movements"),
    ("ESTIMATED_NET_INVESTMENT_MOVEMENT", "estimated_net_investment_movement"), ("INVESTING_CASH_FLOW", "investing_cash_flow"),
    ("PROVEN_BORROWING_PROCEEDS", "proven_borrowing_proceeds"), ("PROVEN_DEBT_REPAYMENTS", "proven_debt_repayments"),
    ("ESTIMATED_NET_DEBT_MOVEMENT", "estimated_net_debt_movement"), ("PROVEN_EQUITY_CONTRIBUTIONS", "proven_equity_contributions"),
    ("PROVEN_DIVIDENDS_PAID", "proven_dividends_paid"), ("FINANCING_CASH_FLOW", "financing_cash_flow"),
    ("AUTHORITATIVE_INTEREST_PAID", "authoritative_interest_paid"), ("AUTHORITATIVE_INTEREST_RECEIVED", "authoritative_interest_received"),
    ("AUTHORITATIVE_DIVIDENDS_RECEIVED", "authoritative_dividends_received"), ("AUTHORITATIVE_INCOME_TAX_PAID", "authoritative_income_tax_paid"),
    ("AUTHORITATIVE_FX_EFFECT", "authoritative_fx_effect"), ("AUTHORITATIVE_RECLASSIFICATION_EFFECT", "authoritative_reclassification_effect"),
    ("CALCULATED_NET_CASH_CHANGE", "calculated_net_cash_change"), ("CLOSING_CASH_AND_CASH_EQUIVALENTS", "closing_cash_and_cash_equivalents"),
    ("BALANCE_SHEET_NET_CASH_CHANGE", "balance_sheet_net_cash_change"), ("RECONCILIATION_DIFFERENCE", "reconciliation_difference"),
    ("FREE_CASH_FLOW", "free_cash_flow"),
)
APPLICATION_CASH_FLOW_WARNING_CODE_MEMBER_PAIRS_V2 = (
    ("MINIMUM_DATA_INCOMPLETE", "minimum_data_incomplete"), ("ACCOUNT_UNCLASSIFIED", "account_unclassified"),
    ("CASH_EQUIVALENT_ELIGIBILITY_UNPROVEN", "cash_equivalent_eligibility_unproven"), ("NON_CASH_ADJUSTMENT_UNAVAILABLE", "non_cash_adjustment_unavailable"),
    ("GROSS_MOVEMENT_UNAVAILABLE", "gross_movement_unavailable"), ("ESTIMATED_NET_MOVEMENT_USED", "estimated_net_movement_used"),
    ("RECONCILIATION_DIFFERENCE", "reconciliation_difference"), ("MATERIAL_RECONCILIATION_DIFFERENCE", "material_reconciliation_difference"),
    ("PRESENTATION_EVIDENCE_UNAVAILABLE", "presentation_evidence_unavailable"), ("NEGATIVE_CASH_BALANCE", "negative_cash_balance"),
    ("OVERDRAFT_RECLASSIFIED_TO_FINANCING", "overdraft_reclassified_to_financing"),
)
APPLICATION_CASH_FLOW_ERROR_CODE_MEMBER_PAIRS_V2 = (
    ("INVALID_CONTRACT", "invalid_contract"), ("PERIOD_NOT_COMPARABLE", "period_not_comparable"),
    ("PERIOD_SELECTION_AMBIGUOUS", "period_selection_ambiguous"), ("SOURCE_NOT_FOUND", "source_not_found"),
    ("SOURCE_SCOPE_MISMATCH", "source_scope_mismatch"), ("SOURCE_STATUS_INVALID", "source_status_invalid"),
    ("SOURCE_DIGEST_MISMATCH", "source_digest_mismatch"), ("SOURCE_CURRENCY_MISMATCH", "source_currency_mismatch"),
    ("SOURCE_EVIDENCE_CONFLICT", "source_evidence_conflict"), ("POLICY_VERSION_UNSUPPORTED", "policy_version_unsupported"),
    ("MAPPING_REGISTRY_VERSION_UNSUPPORTED", "mapping_registry_version_unsupported"), ("MAPPING_CONFLICT", "mapping_conflict"),
    ("DECIMAL_NON_FINITE_OR_SCALE_INVALID", "decimal_non_finite_or_scale_invalid"), ("PERSISTENCE_INTEGRITY_FAILURE", "persistence_integrity_failure"),
    ("SOURCE_RESOLUTION_UNAVAILABLE", "source_resolution_unavailable"), ("PERSISTENCE_UNAVAILABLE", "persistence_unavailable"),
)
APPLICATION_CASH_FLOW_ACCOUNT_ROLE_MEMBER_PAIRS_V2 = (
    ("CASH_ON_HAND", "cash_on_hand"), ("BANK_ACCOUNT_CANDIDATE", "bank_account_candidate"), ("RESTRICTED_BANK_ASSET", "restricted_bank_asset"),
    ("DEMAND_DEPOSIT", "demand_deposit"), ("CASH_EQUIVALENT_INVESTMENT", "cash_equivalent_investment"), ("CHECK_RECEIVABLE", "check_receivable"),
    ("ISSUED_CHECK_OR_PAYMENT_ORDER", "issued_check_or_payment_order"), ("OTHER_LIQUID_ASSET_CANDIDATE", "other_liquid_asset_candidate"),
    ("POS_RECEIVABLE", "pos_receivable"), ("OPERATING_RECEIVABLE", "operating_receivable"), ("INVENTORY", "inventory"),
    ("OTHER_OPERATING_ASSET", "other_operating_asset"), ("OPERATING_PAYABLE", "operating_payable"),
    ("OTHER_OPERATING_LIABILITY", "other_operating_liability"), ("PPE", "ppe"), ("INTANGIBLE_ASSET", "intangible_asset"),
    ("FINANCIAL_INVESTMENT", "financial_investment"), ("EQUITY_FINANCIAL_INVESTMENT", "equity_financial_investment"),
    ("LONG_TERM_FINANCIAL_INVESTMENT", "long_term_financial_investment"), ("NON_CASH_INVESTMENT_COMMITMENT", "non_cash_investment_commitment"),
    ("BORROWING", "borrowing"), ("EQUITY", "equity"), ("NON_CASH_EQUITY", "non_cash_equity"), ("TAX_PAYABLE", "tax_payable"),
    ("TAX_RECEIVABLE", "tax_receivable"), ("INTEREST_PAYABLE", "interest_payable"), ("INTEREST_RECEIVABLE", "interest_receivable"),
    ("DIVIDEND_PAYABLE", "dividend_payable"), ("DIVIDEND_RECEIVABLE", "dividend_receivable"),
    ("INTEREST_EXPENSE_ACCRUAL", "interest_expense_accrual"), ("INTEREST_INCOME_ACCRUAL", "interest_income_accrual"),
    ("DIVIDEND_INCOME_ACCRUAL", "dividend_income_accrual"), ("CURRENT_TAX_EXPENSE_ACCRUAL", "current_tax_expense_accrual"),
    ("DEFERRED_TAX_ACCRUAL", "deferred_tax_accrual"), ("NON_CASH_ADJUSTMENT", "non_cash_adjustment"), ("UNCLASSIFIED", "unclassified"),
)
APPLICATION_CASH_FLOW_SOURCE_ROLE_MEMBER_PAIRS_V2 = (
    ("CURRENT_BALANCE_SHEET", "current_balance_sheet"), ("PRIOR_BALANCE_SHEET", "prior_balance_sheet"),
    ("CURRENT_INCOME_STATEMENT", "current_income_statement"), ("CURRENT_TRIAL_BALANCE", "current_trial_balance"),
    ("PRIOR_TRIAL_BALANCE", "prior_trial_balance"),
)
APPLICATION_CASH_FLOW_DERIVATION_CODE_MEMBER_PAIRS_V2 = (
    ("SOURCE_VALUE", "source_value"), ("BALANCE_DELTA", "balance_delta"),
    ("OPERATING_ASSET_SIGN_INVERSION", "operating_asset_sign_inversion"),
    ("OPERATING_LIABILITY_SIGN_PRESERVED", "operating_liability_sign_preserved"),
    ("NET_PROFIT_ACCRUAL_REVERSAL", "net_profit_accrual_reversal"), ("INDIRECT_OPERATING_SUBTOTAL", "indirect_operating_subtotal"),
    ("INVESTING_SUBTOTAL", "investing_subtotal"), ("FINANCING_SUBTOTAL", "financing_subtotal"),
    ("PRESENTATION_RECLASSIFICATION", "presentation_reclassification"), ("NET_CASH_CHANGE_SUM", "net_cash_change_sum"),
    ("BALANCE_SHEET_CASH_DELTA", "balance_sheet_cash_delta"), ("RECONCILIATION_DIFFERENCE", "reconciliation_difference"),
    ("FREE_CASH_FLOW_FROM_PROVEN_CAPEX", "free_cash_flow_from_proven_capex"),
)

ApplicationCashFlowLineCodeV2 = Enum("ApplicationCashFlowLineCodeV2", dict(APPLICATION_CASH_FLOW_LINE_CODE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowWarningCodeV2 = Enum("ApplicationCashFlowWarningCodeV2", dict(APPLICATION_CASH_FLOW_WARNING_CODE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowErrorCodeV2 = Enum("ApplicationCashFlowErrorCodeV2", dict(APPLICATION_CASH_FLOW_ERROR_CODE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowAccountRoleV2 = Enum("ApplicationCashFlowAccountRoleV2", dict(APPLICATION_CASH_FLOW_ACCOUNT_ROLE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowSourceRoleV2 = Enum("ApplicationCashFlowSourceRoleV2", dict(APPLICATION_CASH_FLOW_SOURCE_ROLE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowDerivationCodeV2 = Enum("ApplicationCashFlowDerivationCodeV2", dict(APPLICATION_CASH_FLOW_DERIVATION_CODE_MEMBER_PAIRS_V2), type=str)


@dataclass(frozen=True)
class ApplicationCashFlowActivityAllocationDTO:
    activity: ApplicationCashFlowActivityV2
    amount: Decimal


@dataclass(frozen=True)
class ApplicationCashFlowEvidenceReferenceDTO:
    evidence_kind: ApplicationCashFlowEvidenceKindV2
    source_role: ApplicationCashFlowSourceRoleV2
    financial_analysis_result_id: UUID
    source_canonical_digest: str
    source_provenance_digest: str
    account_codes: tuple[str, ...]
    mapping_ids: tuple[str, ...]
    derivation_code: ApplicationCashFlowDerivationCodeV2


@dataclass(frozen=True)
class ApplicationCashFlowLineItemDTO:
    line_code: ApplicationCashFlowLineCodeV2
    canonical_amount: Decimal | None
    aggregation_role: ApplicationCashFlowLineAggregationRoleV2
    presentation_allocations: tuple[ApplicationCashFlowActivityAllocationDTO, ...]
    applicability: ApplicationCashFlowApplicabilityV2
    evidence_kind: ApplicationCashFlowEvidenceKindV2
    evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]
    missing_inputs: tuple[str, ...]
    warning_codes: tuple[ApplicationCashFlowWarningCodeV2, ...]


@dataclass(frozen=True)
class ApplicationCashFlowCompletenessDTO:
    manifest_version: str
    required_line_count: int
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    available_ratio: Decimal
    optional_analytics_available_count: int
    optional_analytics_unavailable_count: int


@dataclass(frozen=True)
class ApplicationCashAvailabilityObservationDTO:
    period_position: ApplicationCashFlowAvailabilityPeriodPositionV2
    classification: ApplicationCashAvailabilityClassificationV2
    amount: Decimal | None
    restriction_preserves_cash_nature: bool | None
    evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]


@dataclass(frozen=True)
class ApplicationCashAvailabilityDisclosureDTO:
    component_reference_digest: str
    account_role: ApplicationCashFlowAccountRoleV2
    observations: tuple[ApplicationCashAvailabilityObservationDTO, ...]


@dataclass(frozen=True)
class ApplicationCashFlowEndpointReconciliationDTO:
    period_position: ApplicationCashFlowAvailabilityPeriodPositionV2
    policy_defined_cash_and_equivalents: Decimal | None
    reported_balance_sheet_cash_and_equivalents: Decimal | None
    difference: Decimal | None
    status: ApplicationCashFlowEndpointReconciliationStatusV2
    balance_sheet_evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]


@dataclass(frozen=True)
class ApplicationCashFlowIssueDTO:
    code: ApplicationCashFlowWarningCodeV2 | ApplicationCashFlowErrorCodeV2
    safe_metadata: object


@dataclass(frozen=True)
class ApplicationCashFlowLineageReferenceDTO:
    source_role: ApplicationCashFlowSourceRoleV2
    financial_analysis_result_id: UUID
    source_period_id: UUID
    canonical_digest: str
    source_provenance_digest: str


class ApplicationCashFlowPeriodTypeV2(str, Enum):
    YEAR_END = "year_end"
    QUARTER = "quarter"
    TEMPORARY_TAX = "temporary_tax"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class ApplicationCashFlowPeriodStatusV2(str, Enum):
    CLOSED = "closed"


class ApplicationCashFlowAccountingBasisCodeV2(str, Enum):
    TR_TDHP_ACCRUAL = "tr_tdhp_accrual"


@dataclass(frozen=True)
class ApplicationCashFlowPeriodDescriptorDTO:
    period_id: UUID
    company_id: UUID
    tenant_id: UUID
    currency_code: str
    monetary_unit_multiplier: Decimal
    period_type: ApplicationCashFlowPeriodTypeV2
    start_date: date
    end_date: date
    annual_reporting_period_start_date: date
    annual_reporting_period_end_date: date
    months_covered: int
    status: ApplicationCashFlowPeriodStatusV2
    accounting_basis_code: ApplicationCashFlowAccountingBasisCodeV2
    accounting_policy_version: str
    ifrs18_early_adopted: bool


@dataclass(frozen=True)
class CashFlowProjectionDTOV2:
    opening_cash_and_cash_equivalents: Decimal | None
    closing_cash_and_cash_equivalents: Decimal | None
    operating_cash_flow: Decimal | None
    investing_cash_flow: Decimal | None
    financing_cash_flow: Decimal | None
    authoritative_fx_effect: Decimal | None
    authoritative_reclassification_effect: Decimal | None
    calculated_net_cash_change: Decimal | None
    balance_sheet_net_cash_change: Decimal | None
    reconciliation_difference: Decimal | None
    free_cash_flow: Decimal | None
    status: ApplicationCashFlowResultBearingStatusV2
    reconciliation_status: ApplicationCashFlowReconciliationStatusV2
    completeness: ApplicationCashFlowCompletenessDTO
    currency_code: str
    monetary_scale: int
    policy_version: str
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    presentation_policy_version: str
    reconciliation_policy_version: str
    mapping_registry_version: str
    current_period_id: UUID
    prior_period_id: UUID | None
    current_period_descriptor: ApplicationCashFlowPeriodDescriptorDTO
    prior_period_descriptor: ApplicationCashFlowPeriodDescriptorDTO | None
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None
    line_items: tuple[ApplicationCashFlowLineItemDTO, ...]
    cash_availability_disclosures: tuple[ApplicationCashAvailabilityDisclosureDTO, ...]
    endpoint_reconciliations: tuple[ApplicationCashFlowEndpointReconciliationDTO, ...]
    evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]
    warnings: tuple[ApplicationCashFlowIssueDTO, ...]
    errors: tuple[ApplicationCashFlowIssueDTO, ...]
    source_lineage_references: tuple[ApplicationCashFlowLineageReferenceDTO, ...]
    cash_flow_schema_version: str
    cash_flow_model_version: str
    application_schema_version: str = "2.0.0"

    def __post_init__(self) -> None:
        if self.status not in tuple(ApplicationCashFlowStatusV2)[:5]:
            raise ValueError("failure-only Cash Flow status cannot be materialized")
        if len(self.endpoint_reconciliations) != 2 or tuple(x.period_position for x in self.endpoint_reconciliations) != tuple(ApplicationCashFlowAvailabilityPeriodPositionV2):
            raise ValueError("Cash Flow projection requires exact endpoint records")
        if self.errors:
            raise ValueError("result-bearing Cash Flow projection cannot carry errors")


class ApplicationPayloadKindV2(str, Enum):
    GENERIC_FINANCIAL = "generic_financial"
    CASH_FLOW = "cash_flow"
    ARTIFACT = "artifact"


@dataclass(frozen=True)
class ApplicationPayloadReferenceDTOV2:
    owner_type: PayloadOwnerType
    result_kind: str
    canonical_digest: str
    financial_analysis_result_id: UUID | None
    artifact_id: UUID | None
    artifact_serializer_schema_version: str | None

    def __post_init__(self) -> None:
        if self.owner_type is PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT:
            if self.financial_analysis_result_id is None or self.artifact_id is not None or self.artifact_serializer_schema_version is not None:
                raise ValueError("invalid financial payload reference")
        elif self.artifact_id is None or self.financial_analysis_result_id is not None or not self.artifact_serializer_schema_version:
            raise ValueError("invalid artifact payload reference")


@dataclass(frozen=True)
class ApplicationProjectedErrorDTOV2:
    category: ExecutionCategory
    engine_code: ApplicationEngineCodeV2 | None
    cash_flow_error_code: ApplicationCashFlowErrorCodeV2 | None
    message: str
    retryable: bool
    safe_metadata: object


@dataclass(frozen=True)
class ApplicationPayloadEnvelopeDTOV2:
    payload_reference: ApplicationPayloadReferenceDTOV2
    computation_status: FinancialComputationStatus
    source_mode: ApplicationFinancialSourceModeV2 | None
    payload_kind: ApplicationPayloadKindV2
    payload_materialized: bool
    generic_result_payload: object | None
    cash_flow_projection: CashFlowProjectionDTOV2 | None
    structured_error: ApplicationProjectedErrorDTOV2 | None
    message: str | None
    inner_status: str | None
    trial_balance_usage: object | None
    provenance_source_references: tuple[str, ...]
    engine_schema_version: str | None
    engine_model_version: str | None
    application_schema_version: str = "2.0.0"

    def __post_init__(self) -> None:
        validate_application_json(self.generic_result_payload)
        validate_application_json(self.trial_balance_usage)
        if self.payload_kind is ApplicationPayloadKindV2.CASH_FLOW:
            if self.payload_reference.result_kind != "CashFlowResult" or self.payload_reference.owner_type is not PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT:
                raise ValueError("Cash Flow payload requires financial CashFlowResult owner")
        if self.payload_materialized:
            if self.payload_kind is ApplicationPayloadKindV2.CASH_FLOW:
                if self.cash_flow_projection is None or self.generic_result_payload is not None:
                    raise ValueError("Cash Flow payload projection mismatch")
            elif self.generic_result_payload is None or self.cash_flow_projection is not None:
                raise ValueError("generic payload projection mismatch")
        elif self.generic_result_payload is not None or self.cash_flow_projection is not None:
            raise ValueError("unmaterialized payload cannot carry data")


@dataclass(frozen=True)
class AnalysisExecutionDTOV2:
    engine_code: ApplicationEngineCodeV2
    status: ApplicationExecutionStatus
    inner_status: str | None
    engine_schema_version: str | None
    engine_model_version: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    error: ApplicationProjectedErrorDTOV2 | None
    dependency_engine_codes: tuple[ApplicationEngineCodeV2, ...]
    payload: ApplicationPayloadEnvelopeDTOV2 | None
    reused_from_run_id: str | None
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class AnalysisCommandResultDTOV2:
    run_id: str
    status: ApplicationStatus
    request_fingerprint: str
    terminal_content_digest: str
    scope: ApplicationScopeDTO
    executions: tuple[AnalysisExecutionDTOV2, ...]
    persisted_at: datetime
    idempotent_replay: bool
    recovery_query_run_id: str
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class AnalysisRunSummaryDTOV2:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    finalized_at: datetime
    previous_run_id: str | None
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class AnalysisRunStatusDTOV2:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    finalized_at: datetime
    engine_statuses: tuple[tuple[ApplicationEngineCodeV2, ApplicationExecutionStatus], ...]
    terminal: bool
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class AnalysisResultDTOV2:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    request_fingerprint: str
    executions: tuple[AnalysisExecutionDTOV2, ...]
    warnings: tuple[object, ...]
    structured_errors: tuple[ApplicationProjectedErrorDTOV2, ...]
    execution_plan_version: str
    orchestration_schema_version: str
    orchestration_model_version: str
    finalized_at: datetime
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class AnalysisHistoryPageDTOV2:
    items: tuple[AnalysisRunSummaryDTOV2, ...]
    next_cursor: str | None
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class CancellationResultDTOV2:
    run_id: str
    status: CancellationStatus
    scope: ApplicationScopeDTO
    requested_at: datetime
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class AnalysisErrorDTOV2:
    code: AnalysisErrorCode
    cash_flow_error_code: ApplicationCashFlowErrorCodeV2 | None
    category: ApplicationErrorCategory
    message: str
    retryable: bool
    correlation_id: str
    safe_metadata: object
    application_schema_version: str = "2.0.0"


@dataclass(frozen=True)
class AnalysisWarningDTOV2:
    code: ApplicationWarningCode
    message: str
    retryable: bool


T = TypeVar("T")


@dataclass(frozen=True)
class ApplicationOutcomeV2(Generic[T]):
    success: bool
    value: T | None
    error: AnalysisErrorDTOV2 | None
    warnings: tuple[AnalysisWarningDTOV2, ...]
    correlation_id: str
    application_schema_version: str = "2.0.0"

    def __post_init__(self) -> None:
        if self.success:
            if self.value is None or self.error is not None:
                raise ValueError("successful outcome requires value only")
        elif self.value is not None or self.error is None:
            raise ValueError("failed outcome requires error only")
