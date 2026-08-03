"""Executable immutable contracts for Milestone 4.5A.

The objects in this module describe inputs, evidence, result payloads and
deterministic serialization.  They do not resolve sources or calculate cash
flow amounts.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from decimal import Decimal, Inexact, InvalidOperation, Overflow, Rounded, localcontext
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Final
from uuid import UUID

from app.models.enums import AnalysisStatus, AnalysisType, PeriodStatus, PeriodType

from .errors import (
    CASH_FLOW_INTEGRITY_ERROR_CODES_V1,
    CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1,
    CashFlowContractError,
    CashFlowEngineFailure,
)
from .policy import (
    CashAndCashEquivalentsPolicy,
    CashFlowPolicyVersion,
    CashFlowPresentationPolicy,
    CashFlowPresentationProfile,
    CashFlowPresentationRule,
    canonical_policy_bundle_digest,
    quantize_completeness_ratio,
    reconciliation_thresholds,
    require_canonical_money,
    require_input_decimal,
)
from .types import (
    CASH_FLOW_CURRENCY_CODE_V1,
    CASH_FLOW_FAILURE_STATUS_MANIFEST,
    CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1,
    CASH_FLOW_LINE_ITEM_MANIFEST_V1,
    CASH_FLOW_MODEL_VERSION,
    CASH_FLOW_MONETARY_SCALE_V1,
    CASH_FLOW_NON_NEGATIVE_LINE_CODES_V1,
    CASH_FLOW_NON_POSITIVE_LINE_CODES_V1,
    CASH_FLOW_OPTIONAL_ANALYTICS_MANIFEST_V1,
    CASH_FLOW_RESULT_BEARING_STATUS_MANIFEST,
    CASH_FLOW_SCHEMA_VERSION,
    CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1,
    CashAvailabilityClassification,
    CashFlowAccountDisposition,
    CashFlowAccountFamilyCode,
    CashFlowAccountRole,
    CashFlowAccountingBasisCode,
    CashFlowActivity,
    CashFlowApplicability,
    CashFlowAvailabilityPeriodPosition,
    CashFlowBalanceSemantics,
    CashFlowDerivationCode,
    CashFlowEndpointReconciliationStatus,
    CashFlowErrorCode,
    CashFlowEvidenceKind,
    CashFlowFamilyBalanceBasis,
    CashFlowFamilyMemberKind,
    CashFlowNormalBalance,
    CashFlowWorkingCapitalKind,
    CashEligibilityRule,
    CashFlowMappingMatchKind,
    CashFlowRoleSelectionRule,
    CashFlowJsonObject,
    CashFlowLineAggregationRole,
    CashFlowLineCode,
    CashFlowMethod,
    CashFlowNonCashBridgeDomain,
    CashFlowNonCashBridgeKind,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
    CashFlowSourceMode,
    CashFlowSourceRole,
    CashFlowStatementBasis,
    CashFlowWarningCode,
    CashFlowZeroBalanceOmissionPolicy,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class _SafeContractValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _fail(message: str) -> None:
    raise CashFlowContractError(message)


def _require_tuple(value: object, field_name: str) -> tuple:
    if type(value) is not tuple:
        _fail(f"{field_name} must be a tuple")
    return value


def _require_uuid(value: object, field_name: str) -> UUID:
    if type(value) is not UUID:
        _fail(f"{field_name} must be UUID")
    return value


def _require_digest(value: object, field_name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be lowercase SHA-256")
    return value


def _require_non_empty_text(value: object, field_name: str, *, maximum: int = 128) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        _fail(f"{field_name} must be a bounded non-empty string")
    return value


def _require_sorted_unique_strings(value: object, field_name: str) -> tuple[str, ...]:
    values = _require_tuple(value, field_name)
    if any(type(item) is not str or not item for item in values):
        _fail(f"{field_name} must contain non-empty strings")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        _fail(f"{field_name} must be unique and sorted")
    return values


def _locator_key(owner_id: UUID | None, engine_code: str | None) -> tuple[str, str]:
    if (owner_id is None) == (engine_code is None):
        _fail("source locator must satisfy owner-id XOR same-run engine-code")
    if owner_id is not None:
        _require_uuid(owner_id, "source_analysis_result_id")
        return ("existing", str(owner_id))
    _require_non_empty_text(engine_code, "same_run_engine_code", maximum=64)
    return ("same_run", engine_code)


def _set_canonical_money(instance: object, field_name: str) -> None:
    value = getattr(instance, field_name)
    if value is not None:
        object.__setattr__(
            instance,
            field_name,
            require_canonical_money(value, field_name=field_name),
        )


def _exact_sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext() as context:
        context.prec = 64
        context.Emax = 999999
        context.Emin = -999999
        context.traps[InvalidOperation] = True
        context.traps[Overflow] = True
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        return sum(values, Decimal("0.00"))


def _exact_subtract(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 64
        context.Emax = 999999
        context.Emin = -999999
        context.traps[InvalidOperation] = True
        context.traps[Overflow] = True
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        return left - right


@dataclass(frozen=True, repr=False)
class CashFlowIssue(_SafeContractValue):
    code: CashFlowWarningCode | CashFlowErrorCode
    safe_metadata: CashFlowJsonObject

    def __post_init__(self) -> None:
        if type(self.code) not in {CashFlowWarningCode, CashFlowErrorCode}:
            _fail("issue code must be a closed cash-flow code")
        if type(self.safe_metadata) is not CashFlowJsonObject:
            _fail("issue metadata must use the immutable cash-flow JSON object")


@dataclass(frozen=True, repr=False)
class CashFlowPeriodDescriptor(_SafeContractValue):
    period_id: UUID
    company_id: UUID
    tenant_id: UUID
    currency_code: str
    monetary_unit_multiplier: Decimal
    period_type: PeriodType
    start_date: date
    end_date: date
    annual_reporting_period_start_date: date
    annual_reporting_period_end_date: date
    months_covered: int
    status: PeriodStatus
    accounting_basis_code: CashFlowAccountingBasisCode
    accounting_policy_version: str
    ifrs18_early_adopted: bool

    def __post_init__(self) -> None:
        for name in ("period_id", "company_id", "tenant_id"):
            _require_uuid(getattr(self, name), name)
        if self.currency_code != CASH_FLOW_CURRENCY_CODE_V1:
            _fail("cash-flow v1 supports TRY only")
        multiplier = require_input_decimal(
            self.monetary_unit_multiplier, field_name="monetary_unit_multiplier"
        )
        if multiplier != Decimal("1"):
            _fail("cash-flow v1 monetary unit multiplier must be one")
        object.__setattr__(self, "monetary_unit_multiplier", Decimal("1"))
        if type(self.period_type) is not PeriodType or type(self.status) is not PeriodStatus:
            _fail("period type/status must use the closed repository enums")
        if any(type(getattr(self, name)) is not date for name in (
            "start_date", "end_date", "annual_reporting_period_start_date",
            "annual_reporting_period_end_date",
        )):
            _fail("period dates must be date values")
        if not (
            self.annual_reporting_period_start_date
            <= self.start_date
            <= self.end_date
            <= self.annual_reporting_period_end_date
        ):
            _fail("period interval is outside the annual reporting interval")
        if type(self.months_covered) is not int or not 1 <= self.months_covered <= 12:
            _fail("months_covered must be between 1 and 12")
        if type(self.accounting_basis_code) is not CashFlowAccountingBasisCode:
            _fail("unsupported accounting basis")
        _require_non_empty_text(self.accounting_policy_version, "accounting_policy_version")
        if type(self.ifrs18_early_adopted) is not bool:
            _fail("ifrs18_early_adopted must be bool")


@dataclass(frozen=True, repr=False)
class CashFlowSourceSnapshot(_SafeContractValue):
    source_role: CashFlowSourceRole
    analysis_result_id: UUID | None
    same_run_engine_code: str | None
    analysis_type: AnalysisType
    source_mode: CashFlowSourceMode
    company_id: UUID
    period_id: UUID
    primary_document_id: UUID | None
    canonical_digest: str
    recomputed_result_payload_digest: str
    source_provenance_digest: str
    engine_schema_version: str | None
    engine_model_version: str
    status: AnalysisStatus
    error_message_is_null: bool
    statement_basis: CashFlowStatementBasis
    coverage_start_date: date | None
    coverage_end_date: date
    currency_code: str
    monetary_unit_multiplier: Decimal
    result_payload: CashFlowJsonObject

    def __post_init__(self) -> None:
        if type(self.source_role) is not CashFlowSourceRole:
            _fail("invalid source role")
        _locator_key(self.analysis_result_id, self.same_run_engine_code)
        if type(self.analysis_type) is not AnalysisType:
            _fail("invalid analysis type")
        if type(self.source_mode) is not CashFlowSourceMode:
            _fail("invalid source mode")
        _require_uuid(self.company_id, "company_id")
        _require_uuid(self.period_id, "period_id")
        if self.primary_document_id is not None:
            _require_uuid(self.primary_document_id, "primary_document_id")
        for name in (
            "canonical_digest", "recomputed_result_payload_digest", "source_provenance_digest"
        ):
            _require_digest(getattr(self, name), name)
        if self.canonical_digest != self.recomputed_result_payload_digest:
            _fail("stored and recomputed source digests differ")
        if self.engine_schema_version is not None:
            _require_non_empty_text(self.engine_schema_version, "engine_schema_version")
        _require_non_empty_text(self.engine_model_version, "engine_model_version")
        if self.status is not AnalysisStatus.COMPLETED or self.error_message_is_null is not True:
            _fail("cash-flow source must be a completed error-free analysis result")
        if type(self.statement_basis) is not CashFlowStatementBasis:
            _fail("invalid statement basis")
        if type(self.coverage_end_date) is not date:
            _fail("coverage_end_date must be date")
        if self.statement_basis is CashFlowStatementBasis.AS_OF:
            if self.coverage_start_date is not None:
                _fail("AS_OF source cannot have coverage_start_date")
        elif type(self.coverage_start_date) is not date or self.coverage_start_date > self.coverage_end_date:
            _fail("FLOW_INTERVAL source requires a valid coverage interval")
        if self.currency_code != CASH_FLOW_CURRENCY_CODE_V1:
            _fail("cash-flow v1 source currency must be TRY")
        if require_input_decimal(self.monetary_unit_multiplier) != Decimal("1"):
            _fail("cash-flow v1 source multiplier must be one")
        if type(self.result_payload) is not CashFlowJsonObject:
            _fail("source payload must use immutable cash-flow JSON algebra")


@dataclass(frozen=True, repr=False)
class CashFlowAccountEvidence(_SafeContractValue):
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: str | None
    source_canonical_digest: str
    source_provenance_digest: str
    account_code: str
    canonical_account_role: CashFlowAccountRole | None
    account_disposition: CashFlowAccountDisposition
    disposition_proof_digest: str | None
    account_family_code: CashFlowAccountFamilyCode | None
    account_family_reference_digest: str | None
    family_member_kind: CashFlowFamilyMemberKind | None
    source_balance: Decimal | None
    source_debit_movement: Decimal | None
    source_credit_movement: Decimal | None
    source_currency_code: str
    source_unit_multiplier: Decimal
    functional_currency_code: str
    normalized_functional_currency_balance: Decimal | None
    normalized_functional_currency_debit_movement: Decimal | None
    normalized_functional_currency_credit_movement: Decimal | None
    translation_provenance_digest: str | None
    balance_semantics: CashFlowBalanceSemantics
    as_of_date: date
    complete_snapshot: bool
    zero_balance_omission_policy: CashFlowZeroBalanceOmissionPolicy
    maturity_days_at_acquisition: int | None
    is_restricted: bool | None
    is_repayable_on_demand: bool | None
    readily_convertible_to_known_amount: bool | None
    insignificant_value_change_risk: bool | None
    held_for_short_term_cash_commitments: bool | None
    integral_to_cash_management: bool | None
    restriction_preserves_cash_nature: bool | None

    def __post_init__(self) -> None:
        if type(self.source_role) is not CashFlowSourceRole:
            _fail("invalid account-evidence source role")
        _locator_key(self.source_analysis_result_id, self.same_run_engine_code)
        _require_digest(self.source_canonical_digest, "source_canonical_digest")
        _require_digest(self.source_provenance_digest, "source_provenance_digest")
        if type(self.account_code) is not str or not self.account_code or not self.account_code.isascii():
            _fail("account_code must be a non-empty ASCII string")
        if self.canonical_account_role is not None and type(self.canonical_account_role) is not CashFlowAccountRole:
            _fail("invalid canonical account role")
        if type(self.account_disposition) is not CashFlowAccountDisposition:
            _fail("invalid account disposition")
        if self.account_disposition is CashFlowAccountDisposition.UNRESOLVED:
            if self.disposition_proof_digest is not None:
                _fail("UNRESOLVED disposition cannot claim a proof digest")
        else:
            _require_digest(self.disposition_proof_digest, "disposition_proof_digest")
        family_values = (
            self.account_family_code,
            self.account_family_reference_digest,
            self.family_member_kind,
        )
        if any(value is not None for value in family_values) and not all(value is not None for value in family_values):
            _fail("account family fields must be all-null or all-present")
        if self.account_family_code is not None:
            if type(self.account_family_code) is not CashFlowAccountFamilyCode or type(self.family_member_kind) is not CashFlowFamilyMemberKind:
                _fail("invalid account family contract")
            _require_digest(self.account_family_reference_digest, "account_family_reference_digest")
        for name in (
            "source_balance",
            "source_debit_movement",
            "source_credit_movement",
            "normalized_functional_currency_balance",
            "normalized_functional_currency_debit_movement",
            "normalized_functional_currency_credit_movement",
        ):
            value = getattr(self, name)
            if value is not None:
                normalized = require_input_decimal(value, field_name=name)
                object.__setattr__(self, name, normalized)
        if self.source_currency_code != CASH_FLOW_CURRENCY_CODE_V1 or self.functional_currency_code != CASH_FLOW_CURRENCY_CODE_V1:
            _fail("cash-flow v1 evidence currency must be TRY")
        if require_input_decimal(self.source_unit_multiplier) != Decimal("1"):
            _fail("cash-flow v1 evidence multiplier must be one")
        for source_name, normalized_name in (
            ("source_balance", "normalized_functional_currency_balance"),
            ("source_debit_movement", "normalized_functional_currency_debit_movement"),
            ("source_credit_movement", "normalized_functional_currency_credit_movement"),
        ):
            if getattr(self, source_name) != getattr(self, normalized_name):
                _fail("TRY source and normalized evidence amounts must match exactly")
        if self.translation_provenance_digest is not None:
            _fail("cash-flow v1 does not accept translation provenance")
        if type(self.balance_semantics) is not CashFlowBalanceSemantics or type(self.as_of_date) is not date:
            _fail("invalid account balance semantics/date")
        if type(self.complete_snapshot) is not bool or type(self.zero_balance_omission_policy) is not CashFlowZeroBalanceOmissionPolicy:
            _fail("invalid snapshot coverage contract")
        if self.maturity_days_at_acquisition is not None and (
            type(self.maturity_days_at_acquisition) is not int or self.maturity_days_at_acquisition < 0
        ):
            _fail("maturity days must be a non-negative integer or None")
        for name in (
            "is_restricted",
            "is_repayable_on_demand",
            "readily_convertible_to_known_amount",
            "insignificant_value_change_risk",
            "held_for_short_term_cash_commitments",
            "integral_to_cash_management",
            "restriction_preserves_cash_nature",
        ):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                _fail(f"{name} must be bool or None")


@dataclass(frozen=True, repr=False)
class CashFlowNonCashBridgeComponent(_SafeContractValue):
    component_reference_digest: str
    economic_event_reference_digest: str
    account_family_reference_digest: str
    account_family_code: CashFlowAccountFamilyCode
    family_balance_basis: CashFlowFamilyBalanceBasis
    domain: CashFlowNonCashBridgeDomain
    bridge_kind: CashFlowNonCashBridgeKind
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: str | None
    source_canonical_digest: str
    source_provenance_digest: str
    statement_basis: CashFlowStatementBasis
    coverage_start_date: date
    coverage_end_date: date
    applicability: CashFlowApplicability
    evidence_kind: CashFlowEvidenceKind
    source_signed_residual_adjustment: Decimal | None
    source_currency_code: str
    source_unit_multiplier: Decimal
    functional_currency_code: str
    signed_residual_adjustment: Decimal | None
    translation_provenance_digest: str | None
    paired_transfer_reference_digest: str | None
    supporting_evidence_reference_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "component_reference_digest",
            "economic_event_reference_digest",
            "account_family_reference_digest",
            "source_canonical_digest",
            "source_provenance_digest",
        ):
            _require_digest(getattr(self, name), name)
        if type(self.account_family_code) is not CashFlowAccountFamilyCode or type(self.family_balance_basis) is not CashFlowFamilyBalanceBasis:
            _fail("invalid bridge family contract")
        if type(self.domain) is not CashFlowNonCashBridgeDomain or type(self.bridge_kind) is not CashFlowNonCashBridgeKind:
            _fail("invalid bridge domain/kind")
        if type(self.source_role) is not CashFlowSourceRole:
            _fail("invalid bridge source role")
        _locator_key(self.source_analysis_result_id, self.same_run_engine_code)
        if self.statement_basis is not CashFlowStatementBasis.FLOW_INTERVAL:
            _fail("bridge component must use FLOW_INTERVAL evidence")
        if type(self.coverage_start_date) is not date or type(self.coverage_end_date) is not date or self.coverage_start_date > self.coverage_end_date:
            _fail("bridge component requires a valid coverage interval")
        if type(self.applicability) is not CashFlowApplicability or type(self.evidence_kind) is not CashFlowEvidenceKind:
            _fail("invalid bridge applicability/evidence")
        for name in ("source_signed_residual_adjustment", "signed_residual_adjustment"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_input_decimal(value, field_name=name))
        if self.source_currency_code != CASH_FLOW_CURRENCY_CODE_V1 or self.functional_currency_code != CASH_FLOW_CURRENCY_CODE_V1:
            _fail("cash-flow v1 bridge currency must be TRY")
        if require_input_decimal(self.source_unit_multiplier) != Decimal("1"):
            _fail("cash-flow v1 bridge multiplier must be one")
        if self.source_signed_residual_adjustment != self.signed_residual_adjustment:
            _fail("TRY source and normalized bridge amounts must match")
        if self.translation_provenance_digest is not None:
            _fail("cash-flow v1 does not accept bridge translation provenance")
        if self.paired_transfer_reference_digest is not None:
            _require_digest(self.paired_transfer_reference_digest, "paired_transfer_reference_digest")
        for digest in _require_sorted_unique_strings(
            self.supporting_evidence_reference_digests,
            "supporting_evidence_reference_digests",
        ):
            _require_digest(digest, "supporting_evidence_reference_digest")
        if self.applicability is CashFlowApplicability.APPLICABLE:
            if self.signed_residual_adjustment is None or self.evidence_kind not in {CashFlowEvidenceKind.EXACT, CashFlowEvidenceKind.DERIVED}:
                _fail("applicable bridge requires an exact/derived amount")
        elif self.applicability is CashFlowApplicability.PROVEN_NOT_APPLICABLE:
            if self.signed_residual_adjustment != Decimal("0") or self.evidence_kind is not CashFlowEvidenceKind.EXACT:
                _fail("proven-not-applicable bridge must be exact zero")
        elif self.signed_residual_adjustment is not None or self.evidence_kind is not CashFlowEvidenceKind.UNAVAILABLE:
            _fail("unknown bridge must carry no amount and unavailable evidence")


@dataclass(frozen=True, repr=False)
class IndirectCashFlowInput(_SafeContractValue):
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    current_balance_sheet: CashFlowSourceSnapshot | None
    prior_balance_sheet: CashFlowSourceSnapshot | None
    current_income_statement: CashFlowSourceSnapshot | None
    current_trial_balance: CashFlowSourceSnapshot | None
    prior_trial_balance: CashFlowSourceSnapshot | None
    account_evidence: tuple[CashFlowAccountEvidence, ...]
    noncash_bridge_components: tuple[CashFlowNonCashBridgeComponent, ...]
    account_evidence_bundle_digest: str
    opening_account_coverage_complete: bool
    closing_account_coverage_complete: bool
    mapping_registry_version: str
    accounting_policy_version: str
    presentation_policy: CashFlowPresentationPolicy

    def __post_init__(self) -> None:
        if type(self.current_period) is not CashFlowPeriodDescriptor:
            _fail("current period descriptor is required")
        if self.prior_period is not None and type(self.prior_period) is not CashFlowPeriodDescriptor:
            _fail("invalid prior period descriptor")
        for name in (
            "current_balance_sheet", "prior_balance_sheet", "current_income_statement",
            "current_trial_balance", "prior_trial_balance",
        ):
            if getattr(self, name) is not None and type(getattr(self, name)) is not CashFlowSourceSnapshot:
                _fail(f"invalid {name}")
        _canonical_object_tuple(self.account_evidence, "account_evidence")
        _canonical_object_tuple(self.noncash_bridge_components, "noncash_bridge_components")
        _require_digest(self.account_evidence_bundle_digest, "account_evidence_bundle_digest")
        if type(self.opening_account_coverage_complete) is not bool or type(self.closing_account_coverage_complete) is not bool:
            _fail("coverage flags must be bool")
        _require_non_empty_text(self.mapping_registry_version, "mapping_registry_version")
        _require_non_empty_text(self.accounting_policy_version, "accounting_policy_version")
        if type(self.presentation_policy) is not CashFlowPresentationPolicy:
            _fail("invalid presentation policy")


@dataclass(frozen=True, repr=False)
class CashFlowPreResolvedContext(_SafeContractValue):
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    prior_balance_sheet: CashFlowSourceSnapshot | None
    current_trial_balance: CashFlowSourceSnapshot | None
    prior_trial_balance: CashFlowSourceSnapshot | None
    account_evidence: tuple[CashFlowAccountEvidence, ...]
    noncash_bridge_components: tuple[CashFlowNonCashBridgeComponent, ...]
    pre_resolved_evidence_bundle_digest: str
    source_candidate_set_digest: str
    opening_account_coverage_complete: bool
    closing_account_coverage_complete: bool
    comparability_proof_digest: str | None
    mapping_registry_version: str
    accounting_policy_version: str
    presentation_policy: CashFlowPresentationPolicy

    def __post_init__(self) -> None:
        if type(self.current_period) is not CashFlowPeriodDescriptor:
            _fail("current period descriptor is required")
        if self.prior_period is not None and type(self.prior_period) is not CashFlowPeriodDescriptor:
            _fail("invalid prior period descriptor")
        for name in ("prior_balance_sheet", "current_trial_balance", "prior_trial_balance"):
            if getattr(self, name) is not None and type(getattr(self, name)) is not CashFlowSourceSnapshot:
                _fail(f"invalid {name}")
        _canonical_object_tuple(self.account_evidence, "account_evidence")
        _canonical_object_tuple(self.noncash_bridge_components, "noncash_bridge_components")
        _require_digest(self.pre_resolved_evidence_bundle_digest, "pre_resolved_evidence_bundle_digest")
        _require_digest(self.source_candidate_set_digest, "source_candidate_set_digest")
        if self.comparability_proof_digest is not None:
            _require_digest(self.comparability_proof_digest, "comparability_proof_digest")
        if type(self.opening_account_coverage_complete) is not bool or type(self.closing_account_coverage_complete) is not bool:
            _fail("coverage flags must be bool")
        _require_non_empty_text(self.mapping_registry_version, "mapping_registry_version")
        _require_non_empty_text(self.accounting_policy_version, "accounting_policy_version")
        if type(self.presentation_policy) is not CashFlowPresentationPolicy:
            _fail("invalid presentation policy")


@dataclass(frozen=True, repr=False)
class CashFlowEvidenceReference(_SafeContractValue):
    evidence_kind: CashFlowEvidenceKind
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: str | None
    source_canonical_digest: str
    source_provenance_digest: str
    account_codes: tuple[str, ...]
    mapping_ids: tuple[str, ...]
    derivation_code: CashFlowDerivationCode

    def __post_init__(self) -> None:
        if type(self.evidence_kind) is not CashFlowEvidenceKind:
            _fail("invalid evidence kind")
        if type(self.source_role) is not CashFlowSourceRole:
            _fail("invalid source role")
        _locator_key(self.source_analysis_result_id, self.same_run_engine_code)
        _require_digest(self.source_canonical_digest, "source_canonical_digest")
        _require_digest(self.source_provenance_digest, "source_provenance_digest")
        _require_sorted_unique_strings(self.account_codes, "account_codes")
        _require_sorted_unique_strings(self.mapping_ids, "mapping_ids")
        if type(self.derivation_code) is not CashFlowDerivationCode:
            _fail("invalid derivation code")


@dataclass(frozen=True, repr=False)
class CashFlowActivityAllocation(_SafeContractValue):
    activity: CashFlowActivity
    amount: Decimal

    def __post_init__(self) -> None:
        if type(self.activity) is not CashFlowActivity or self.activity is CashFlowActivity.UNCLASSIFIED:
            _fail("allocation activity must be a classified closed value")
        object.__setattr__(self, "amount", require_canonical_money(self.amount))


def _canonical_object_tuple(value: object, field_name: str) -> tuple:
    values = _require_tuple(value, field_name)
    digests = tuple(canonical_cash_flow_digest(item) for item in values)
    if digests != tuple(sorted(digests)) or len(digests) != len(set(digests)):
        _fail(f"{field_name} must be unique and canonically ordered")
    return values


@dataclass(frozen=True, repr=False)
class CashFlowLineItem(_SafeContractValue):
    line_code: CashFlowLineCode
    canonical_amount: Decimal | None
    aggregation_role: CashFlowLineAggregationRole
    presentation_allocations: tuple[CashFlowActivityAllocation, ...]
    applicability: CashFlowApplicability
    evidence_kind: CashFlowEvidenceKind
    evidence: tuple[CashFlowEvidenceReference, ...]
    missing_inputs: tuple[str, ...]
    warning_codes: tuple[CashFlowWarningCode, ...]

    def __post_init__(self) -> None:
        if type(self.line_code) is not CashFlowLineCode:
            _fail("invalid line code")
        expected_role = dict(CASH_FLOW_LINE_AGGREGATION_MANIFEST_V1)[self.line_code]
        if self.aggregation_role is not expected_role:
            _fail("line aggregation role conflicts with the closed manifest")
        _set_canonical_money(self, "canonical_amount")
        allocations = _require_tuple(self.presentation_allocations, "presentation_allocations")
        if any(type(item) is not CashFlowActivityAllocation for item in allocations):
            _fail("invalid activity allocation")
        allocation_keys = tuple(item.activity.value for item in allocations)
        if allocation_keys != tuple(sorted(allocation_keys)) or len(allocation_keys) != len(set(allocation_keys)):
            _fail("activity allocations must be unique and sorted")
        if type(self.applicability) is not CashFlowApplicability:
            _fail("invalid applicability")
        if type(self.evidence_kind) is not CashFlowEvidenceKind:
            _fail("invalid evidence kind")
        _canonical_object_tuple(self.evidence, "evidence")
        missing = _require_sorted_unique_strings(self.missing_inputs, "missing_inputs")
        warnings = _require_tuple(self.warning_codes, "warning_codes")
        if any(type(item) is not CashFlowWarningCode for item in warnings):
            _fail("invalid warning code")
        if tuple(item.value for item in warnings) != tuple(sorted(item.value for item in warnings)) or len(warnings) != len(set(warnings)):
            _fail("warning codes must be unique and sorted")
        if self.canonical_amount is None:
            if allocations or self.evidence_kind is not CashFlowEvidenceKind.UNAVAILABLE:
                _fail("missing line amount must be UNAVAILABLE with no allocations")
            if self.applicability is not CashFlowApplicability.UNKNOWN or not missing:
                _fail("missing line amount requires UNKNOWN applicability and missing inventory")
        else:
            if self.evidence_kind is CashFlowEvidenceKind.UNAVAILABLE or missing:
                _fail("available line cannot carry unavailable evidence or missing inputs")
            if not self.evidence:
                _fail("available line requires at least one evidence reference")
            if self.applicability is CashFlowApplicability.UNKNOWN:
                _fail("UNKNOWN line cannot carry a monetary amount")
            if self.applicability is CashFlowApplicability.PROVEN_NOT_APPLICABLE:
                if self.canonical_amount != Decimal("0.00") or self.evidence_kind is not CashFlowEvidenceKind.EXACT:
                    _fail("proven-not-applicable line must be exact zero")
            if self.aggregation_role is CashFlowLineAggregationRole.PRESENTATION_CONTRIBUTOR:
                if not allocations or _exact_sum(tuple(item.amount for item in allocations)) != self.canonical_amount:
                    _fail("contributor allocations must sum exactly to the canonical amount")
                nonzero = [item.amount for item in allocations if item.amount != 0]
                if nonzero and any((item > 0) != (self.canonical_amount > 0) for item in nonzero):
                    _fail("offsetting presentation allocations are forbidden")
            elif allocations:
                _fail("non-contributor lines cannot carry presentation allocations")
            if self.line_code in CASH_FLOW_NON_POSITIVE_LINE_CODES_V1 and self.canonical_amount > 0:
                _fail("line amount violates the non-positive sign contract")
            if self.line_code in CASH_FLOW_NON_NEGATIVE_LINE_CODES_V1 and self.canonical_amount < 0:
                _fail("line amount violates the non-negative sign contract")


@dataclass(frozen=True, repr=False)
class CashFlowCashAvailabilityObservation(_SafeContractValue):
    period_position: CashFlowAvailabilityPeriodPosition
    classification: CashAvailabilityClassification
    amount: Decimal | None
    restriction_preserves_cash_nature: bool | None
    evidence: tuple[CashFlowEvidenceReference, ...]

    def __post_init__(self) -> None:
        if type(self.period_position) is not CashFlowAvailabilityPeriodPosition:
            _fail("invalid cash availability position")
        if type(self.classification) is not CashAvailabilityClassification:
            _fail("invalid cash availability classification")
        _set_canonical_money(self, "amount")
        _canonical_object_tuple(self.evidence, "evidence")
        if self.restriction_preserves_cash_nature is not None and type(self.restriction_preserves_cash_nature) is not bool:
            _fail("restriction flag must be bool or None")
        if self.classification is CashAvailabilityClassification.RESTRICTED_INCLUDED:
            if self.restriction_preserves_cash_nature is not True or self.amount is None or not self.evidence:
                _fail("restricted included cash requires amount, proof and evidence")


@dataclass(frozen=True, repr=False)
class CashFlowCashAvailabilityDisclosure(_SafeContractValue):
    component_reference_digest: str
    account_role: CashFlowAccountRole
    observations: tuple[CashFlowCashAvailabilityObservation, ...]

    def __post_init__(self) -> None:
        _require_digest(self.component_reference_digest, "component_reference_digest")
        if type(self.account_role) is not CashFlowAccountRole:
            _fail("invalid account role")
        observations = _require_tuple(self.observations, "observations")
        if tuple(item.period_position for item in observations) != tuple(CashFlowAvailabilityPeriodPosition):
            _fail("cash availability disclosure requires opening and closing observations")


@dataclass(frozen=True, repr=False)
class CashFlowEndpointReconciliation(_SafeContractValue):
    period_position: CashFlowAvailabilityPeriodPosition
    policy_defined_cash_and_cash_equivalents: Decimal | None
    reported_balance_sheet_cash_and_cash_equivalents: Decimal | None
    difference: Decimal | None
    status: CashFlowEndpointReconciliationStatus
    balance_sheet_evidence: tuple[CashFlowEvidenceReference, ...]

    def __post_init__(self) -> None:
        if type(self.period_position) is not CashFlowAvailabilityPeriodPosition:
            _fail("invalid endpoint period position")
        for name in (
            "policy_defined_cash_and_cash_equivalents",
            "reported_balance_sheet_cash_and_cash_equivalents",
            "difference",
        ):
            _set_canonical_money(self, name)
        _canonical_object_tuple(self.balance_sheet_evidence, "balance_sheet_evidence")
        if self.status is CashFlowEndpointReconciliationStatus.MATCHED:
            if (
                self.policy_defined_cash_and_cash_equivalents is None
                or self.reported_balance_sheet_cash_and_cash_equivalents is None
                or self.policy_defined_cash_and_cash_equivalents
                != self.reported_balance_sheet_cash_and_cash_equivalents
                or self.difference != Decimal("0.00")
                or not self.balance_sheet_evidence
            ):
                _fail("matched endpoint requires equal values, zero difference and evidence")
        elif self.status is CashFlowEndpointReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA:
            if self.difference is not None:
                _fail("not-performed endpoint cannot carry a difference")
        else:
            _fail("invalid endpoint reconciliation status")


@dataclass(frozen=True, repr=False)
class CashFlowReconciliation(_SafeContractValue):
    balance_sheet_net_cash_change: Decimal | None
    calculated_net_cash_change: Decimal | None
    difference: Decimal | None
    rounding_tolerance: Decimal | None
    material_threshold: Decimal | None
    status: CashFlowReconciliationStatus

    def __post_init__(self) -> None:
        for name in (
            "balance_sheet_net_cash_change",
            "calculated_net_cash_change",
            "difference",
            "rounding_tolerance",
            "material_threshold",
        ):
            _set_canonical_money(self, name)
        if type(self.status) is not CashFlowReconciliationStatus:
            _fail("invalid reconciliation status")
        if self.status in {
            CashFlowReconciliationStatus.NOT_PERFORMED_INCOMPLETE_COMPONENTS,
            CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
        }:
            if self.difference is not None or self.rounding_tolerance is not None or self.material_threshold is not None:
                _fail("not-performed reconciliation cannot carry a difference or thresholds")
            return
        if self.balance_sheet_net_cash_change is None or self.calculated_net_cash_change is None:
            _fail("performed reconciliation requires both net-change values")
        expected_difference = _exact_subtract(
            self.balance_sheet_net_cash_change, self.calculated_net_cash_change
        )
        if self.difference != expected_difference:
            _fail("reconciliation difference does not match its operands")
        expected_rounding, expected_material = reconciliation_thresholds(
            self.balance_sheet_net_cash_change
        )
        if self.rounding_tolerance != expected_rounding or self.material_threshold != expected_material:
            _fail("reconciliation thresholds are not canonical")
        absolute = self.difference.copy_abs()
        if self.status is CashFlowReconciliationStatus.RECONCILED and absolute != 0:
            _fail("RECONCILED requires zero difference")
        if self.status is CashFlowReconciliationStatus.ROUNDING_DIFFERENCE and not (0 < absolute <= expected_rounding):
            _fail("ROUNDING_DIFFERENCE is outside tolerance")
        if self.status is CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL and not (expected_rounding < absolute <= expected_material):
            _fail("UNRECONCILED_NON_MATERIAL is outside its threshold band")
        if self.status is CashFlowReconciliationStatus.UNRECONCILED_MATERIAL and absolute <= expected_material:
            _fail("UNRECONCILED_MATERIAL does not exceed the material threshold")


@dataclass(frozen=True, repr=False)
class CashFlowCompleteness(_SafeContractValue):
    manifest_version: str
    required_line_count: int
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    available_ratio: Decimal
    optional_analytics_available_count: int
    optional_analytics_unavailable_count: int

    def __post_init__(self) -> None:
        _require_non_empty_text(self.manifest_version, "manifest_version")
        counts = (
            self.required_line_count,
            self.exact_count,
            self.derived_count,
            self.estimated_count,
            self.unavailable_count,
            self.optional_analytics_available_count,
            self.optional_analytics_unavailable_count,
        )
        if any(type(item) is not int or item < 0 for item in counts):
            _fail("completeness counts must be non-negative integers")
        if self.required_line_count != len(CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1):
            _fail("required_line_count conflicts with the statement manifest")
        if sum(counts[1:5]) != self.required_line_count:
            _fail("statement evidence counts do not sum to required_line_count")
        if sum(counts[5:]) != len(CASH_FLOW_OPTIONAL_ANALYTICS_MANIFEST_V1):
            _fail("optional analytics counts conflict with the optional manifest")
        expected = quantize_completeness_ratio(
            Decimal(sum(counts[1:4])) / Decimal(self.required_line_count)
        )
        actual = quantize_completeness_ratio(self.available_ratio)
        if actual != expected or self.available_ratio.as_tuple().exponent != -4:
            _fail("available_ratio is not the canonical manifest ratio")
        object.__setattr__(self, "available_ratio", actual)


@dataclass(frozen=True, repr=False)
class CashFlowSourceLineageReference(_SafeContractValue):
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: str | None
    source_period_id: UUID
    canonical_digest: str
    source_provenance_digest: str

    def __post_init__(self) -> None:
        if type(self.source_role) is not CashFlowSourceRole:
            _fail("invalid source role")
        _locator_key(self.source_analysis_result_id, self.same_run_engine_code)
        _require_uuid(self.source_period_id, "source_period_id")
        _require_digest(self.canonical_digest, "canonical_digest")
        _require_digest(self.source_provenance_digest, "source_provenance_digest")


_SUMMARY_LINE_MAP: Final = (
    ("opening_cash_and_cash_equivalents", CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS),
    ("closing_cash_and_cash_equivalents", CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS),
    ("operating_cash_flow", CashFlowLineCode.OPERATING_CASH_FLOW),
    ("investing_cash_flow", CashFlowLineCode.INVESTING_CASH_FLOW),
    ("financing_cash_flow", CashFlowLineCode.FINANCING_CASH_FLOW),
    ("authoritative_fx_effect", CashFlowLineCode.AUTHORITATIVE_FX_EFFECT),
    ("authoritative_reclassification_effect", CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT),
    ("calculated_net_cash_change", CashFlowLineCode.CALCULATED_NET_CASH_CHANGE),
    ("balance_sheet_net_cash_change", CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE),
    ("reconciliation_difference", CashFlowLineCode.RECONCILIATION_DIFFERENCE),
    ("free_cash_flow", CashFlowLineCode.FREE_CASH_FLOW),
)


@dataclass(frozen=True, repr=False)
class CashFlowResult(_SafeContractValue):
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
    status: CashFlowResultStatus
    completeness: CashFlowCompleteness
    reconciliation_status: CashFlowReconciliationStatus
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
    current_period_descriptor: CashFlowPeriodDescriptor
    prior_period_descriptor: CashFlowPeriodDescriptor | None
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None
    line_items: tuple[CashFlowLineItem, ...]
    cash_availability_disclosures: tuple[CashFlowCashAvailabilityDisclosure, ...]
    endpoint_reconciliations: tuple[CashFlowEndpointReconciliation, ...]
    evidence: tuple[CashFlowEvidenceReference, ...]
    warnings: tuple[CashFlowIssue, ...]
    errors: tuple[CashFlowIssue, ...]
    source_lineage_references: tuple[CashFlowSourceLineageReference, ...]
    cash_flow_schema_version: str
    cash_flow_model_version: str

    def __post_init__(self) -> None:
        if self.status not in CASH_FLOW_RESULT_BEARING_STATUS_MANIFEST:
            _fail("CashFlowResult cannot carry a failure-only status")
        for field_name, _ in _SUMMARY_LINE_MAP:
            _set_canonical_money(self, field_name)
        if type(self.completeness) is not CashFlowCompleteness:
            _fail("invalid completeness contract")
        if type(self.reconciliation_status) is not CashFlowReconciliationStatus:
            _fail("invalid reconciliation status")
        if self.currency_code != CASH_FLOW_CURRENCY_CODE_V1 or self.monetary_scale != CASH_FLOW_MONETARY_SCALE_V1:
            _fail("cash-flow v1 result must use TRY scale 2")
        expected_policy_digest = canonical_policy_bundle_digest(
            accounting_policy_version=self.accounting_policy_version,
            cash_equivalent_policy_version=self.cash_equivalent_policy_version,
            presentation_policy_version=self.presentation_policy_version,
            reconciliation_policy_version=self.reconciliation_policy_version,
            mapping_registry_version=self.mapping_registry_version,
        )
        if self.policy_version != expected_policy_digest:
            _fail("policy bundle digest mismatch")
        _require_uuid(self.current_period_id, "current_period_id")
        if type(self.current_period_descriptor) is not CashFlowPeriodDescriptor:
            _fail("invalid current period descriptor")
        if self.current_period_descriptor.period_id != self.current_period_id:
            _fail("current period descriptor identity mismatch")
        if self.current_period_descriptor_digest != canonical_cash_flow_digest(self.current_period_descriptor):
            _fail("current period descriptor digest mismatch")
        if self.status is CashFlowResultStatus.INSUFFICIENT_DATA:
            if any(value is not None for value in (getattr(self, name) for name, _ in _SUMMARY_LINE_MAP)):
                _fail("insufficient-data result cannot carry monetary output")
            if any((self.prior_period_id, self.prior_period_descriptor, self.prior_period_descriptor_digest, self.comparability_proof_digest)):
                _fail("insufficient-data result cannot claim a complete prior-period proof")
        else:
            if self.prior_period_id is None or self.prior_period_descriptor is None:
                _fail("complete/partial result requires prior-period identity and descriptor")
            _require_uuid(self.prior_period_id, "prior_period_id")
            if self.prior_period_descriptor.period_id != self.prior_period_id:
                _fail("prior period descriptor identity mismatch")
            if self.prior_period_descriptor_digest != canonical_cash_flow_digest(self.prior_period_descriptor):
                _fail("prior period descriptor digest mismatch")
            _require_digest(self.comparability_proof_digest, "comparability_proof_digest")
        line_items = _require_tuple(self.line_items, "line_items")
        if tuple(item.line_code for item in line_items) != CASH_FLOW_LINE_ITEM_MANIFEST_V1:
            _fail("line_items must match the closed line manifest exactly")
        line_by_code = {item.line_code: item for item in line_items}
        for field_name, line_code in _SUMMARY_LINE_MAP:
            if getattr(self, field_name) != line_by_code[line_code].canonical_amount:
                _fail("result summary is not an exact line-item projection")
        if self.opening_cash_and_cash_equivalents is not None and self.closing_cash_and_cash_equivalents is not None:
            if self.balance_sheet_net_cash_change != _exact_subtract(
                self.closing_cash_and_cash_equivalents,
                self.opening_cash_and_cash_equivalents,
            ):
                _fail("balance-sheet net cash change violates closing-minus-opening identity")
        calculation_operands = (
            self.operating_cash_flow,
            self.investing_cash_flow,
            self.financing_cash_flow,
            self.authoritative_fx_effect,
            self.authoritative_reclassification_effect,
        )
        if all(value is not None for value in calculation_operands):
            if self.calculated_net_cash_change != _exact_sum(calculation_operands):
                _fail("calculated net cash change violates the closed component sum")
        elif self.calculated_net_cash_change is not None:
            _fail("calculated net cash change cannot treat a missing component as zero")
        if self.balance_sheet_net_cash_change is not None and self.calculated_net_cash_change is not None:
            if self.reconciliation_difference != _exact_subtract(
                self.balance_sheet_net_cash_change,
                self.calculated_net_cash_change,
            ):
                _fail("reconciliation difference violates the closed identity")
        elif self.reconciliation_difference is not None:
            _fail("reconciliation difference requires both net-change values")
        fcf_operands = (
            self.operating_cash_flow,
            line_by_code[CashFlowLineCode.PROVEN_PPE_ACQUISITIONS].canonical_amount,
            line_by_code[CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS].canonical_amount,
        )
        if all(value is not None for value in fcf_operands):
            if self.free_cash_flow != _exact_sum(fcf_operands):
                _fail("free cash flow violates the proven-capex identity")
        elif self.free_cash_flow is not None:
            _fail("free cash flow cannot be fabricated from missing operands")
        statement_kinds = tuple(line_by_code[code].evidence_kind for code in CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1)
        expected_counts = {
            kind: statement_kinds.count(kind) for kind in CashFlowEvidenceKind
        }
        if (
            self.completeness.exact_count != expected_counts[CashFlowEvidenceKind.EXACT]
            or self.completeness.derived_count != expected_counts[CashFlowEvidenceKind.DERIVED]
            or self.completeness.estimated_count != expected_counts[CashFlowEvidenceKind.ESTIMATED]
            or self.completeness.unavailable_count != expected_counts[CashFlowEvidenceKind.UNAVAILABLE]
        ):
            _fail("completeness counts do not match statement evidence")
        if self.status in {CashFlowResultStatus.COMPLETE_RECONCILED, CashFlowResultStatus.COMPLETE_UNRECONCILED}:
            if self.completeness.estimated_count or self.completeness.unavailable_count:
                _fail("COMPLETE status cannot include estimated or unavailable statement lines")
        if self.status in {CashFlowResultStatus.PARTIAL_RECONCILED, CashFlowResultStatus.PARTIAL_UNRECONCILED}:
            if not (self.completeness.estimated_count or self.completeness.unavailable_count):
                _fail("PARTIAL status requires estimated or unavailable statement lines")
        endpoints = _require_tuple(self.endpoint_reconciliations, "endpoint_reconciliations")
        if tuple(item.period_position for item in endpoints) != tuple(CashFlowAvailabilityPeriodPosition):
            _fail("result requires exactly opening and closing endpoint records")
        if self.status is CashFlowResultStatus.INSUFFICIENT_DATA:
            if any(item.status is not CashFlowEndpointReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA for item in endpoints):
                _fail("insufficient-data endpoint reconciliation must be not-performed")
            if self.reconciliation_status is not CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA:
                _fail("insufficient-data result requires not-performed reconciliation")
        else:
            if any(item.status is not CashFlowEndpointReconciliationStatus.MATCHED for item in endpoints):
                _fail("complete/partial result requires matched endpoint records")
            if self.opening_cash_and_cash_equivalents != endpoints[0].policy_defined_cash_and_cash_equivalents:
                _fail("opening cash does not match endpoint evidence")
            if self.closing_cash_and_cash_equivalents != endpoints[1].policy_defined_cash_and_cash_equivalents:
                _fail("closing cash does not match endpoint evidence")
        self._validate_reconciliation_status()
        _canonical_object_tuple(self.cash_availability_disclosures, "cash_availability_disclosures")
        _canonical_object_tuple(self.evidence, "evidence")
        _canonical_object_tuple(self.warnings, "warnings")
        if any(type(issue.code) is not CashFlowWarningCode for issue in self.warnings):
            _fail("result warnings can contain warning codes only")
        if _require_tuple(self.errors, "errors"):
            _fail("v1 result-bearing payload cannot carry fatal errors")
        _canonical_object_tuple(self.source_lineage_references, "source_lineage_references")
        if self.status is not CashFlowResultStatus.INSUFFICIENT_DATA and not self.source_lineage_references:
            _fail("complete/partial result requires source lineage references")
        if self.cash_flow_schema_version != CASH_FLOW_SCHEMA_VERSION or self.cash_flow_model_version != CASH_FLOW_MODEL_VERSION:
            _fail("unsupported cash-flow schema/model version")

    def _validate_reconciliation_status(self) -> None:
        reconciled_family = {
            CashFlowReconciliationStatus.RECONCILED,
            CashFlowReconciliationStatus.ROUNDING_DIFFERENCE,
        }
        if self.status in {CashFlowResultStatus.COMPLETE_RECONCILED, CashFlowResultStatus.PARTIAL_RECONCILED}:
            if self.reconciliation_status not in reconciled_family:
                _fail("reconciled result status conflicts with reconciliation status")
        if self.status in {CashFlowResultStatus.COMPLETE_UNRECONCILED, CashFlowResultStatus.PARTIAL_UNRECONCILED}:
            if self.reconciliation_status in reconciled_family or self.reconciliation_status is CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA:
                _fail("unreconciled result status conflicts with reconciliation status")
        difference = self.reconciliation_difference
        if self.reconciliation_status is CashFlowReconciliationStatus.RECONCILED:
            if difference != Decimal("0.00"):
                _fail("RECONCILED requires exact zero difference")
        elif self.reconciliation_status in {
            CashFlowReconciliationStatus.ROUNDING_DIFFERENCE,
            CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL,
            CashFlowReconciliationStatus.UNRECONCILED_MATERIAL,
        }:
            if difference is None or difference == 0 or self.balance_sheet_net_cash_change is None:
                _fail("performed non-zero reconciliation requires a difference and reference")
            rounding, material = reconciliation_thresholds(self.balance_sheet_net_cash_change)
            absolute = difference.copy_abs()
            if self.reconciliation_status is CashFlowReconciliationStatus.ROUNDING_DIFFERENCE and absolute > rounding:
                _fail("rounding difference exceeds tolerance")
            if self.reconciliation_status is CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL and not (rounding < absolute <= material):
                _fail("non-material difference is outside its closed threshold band")
            if self.reconciliation_status is CashFlowReconciliationStatus.UNRECONCILED_MATERIAL and absolute <= material:
                _fail("material difference does not exceed the material threshold")
        elif self.reconciliation_status is CashFlowReconciliationStatus.NOT_PERFORMED_INCOMPLETE_COMPONENTS:
            if difference is not None:
                _fail("incomplete reconciliation cannot carry a difference")


@dataclass(frozen=True, repr=False)
class CashFlowComputationDraft(_SafeContractValue):
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    line_items: tuple[CashFlowLineItem, ...]
    cash_availability_disclosures: tuple[CashFlowCashAvailabilityDisclosure, ...]
    evidence: tuple[CashFlowEvidenceReference, ...]
    source_lineage_references: tuple[CashFlowSourceLineageReference, ...]
    warnings: tuple[CashFlowIssue, ...]
    policy_version: str
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    presentation_policy_version: str
    reconciliation_policy_version: str
    mapping_registry_version: str

    def __post_init__(self) -> None:
        if type(self.current_period) is not CashFlowPeriodDescriptor:
            _fail("draft requires current period descriptor")
        if self.prior_period is not None and type(self.prior_period) is not CashFlowPeriodDescriptor:
            _fail("invalid draft prior period descriptor")
        if tuple(item.line_code for item in _require_tuple(self.line_items, "line_items")) != CASH_FLOW_LINE_ITEM_MANIFEST_V1:
            _fail("draft line items must match the closed line manifest")
        _canonical_object_tuple(self.cash_availability_disclosures, "cash_availability_disclosures")
        _canonical_object_tuple(self.evidence, "evidence")
        _canonical_object_tuple(self.source_lineage_references, "source_lineage_references")
        _canonical_object_tuple(self.warnings, "warnings")
        if any(type(issue.code) is not CashFlowWarningCode for issue in self.warnings):
            _fail("draft warnings can contain warning codes only")
        expected = canonical_policy_bundle_digest(
            accounting_policy_version=self.accounting_policy_version,
            cash_equivalent_policy_version=self.cash_equivalent_policy_version,
            presentation_policy_version=self.presentation_policy_version,
            reconciliation_policy_version=self.reconciliation_policy_version,
            mapping_registry_version=self.mapping_registry_version,
        )
        if self.policy_version != expected:
            _fail("draft policy bundle digest mismatch")


@dataclass(frozen=True, repr=False)
class CashFlowEngineOutcome(_SafeContractValue):
    status: CashFlowResultStatus
    success: bool
    value: CashFlowResult | None
    error: CashFlowEngineFailure | None

    def __post_init__(self) -> None:
        if type(self.status) is not CashFlowResultStatus or type(self.success) is not bool:
            _fail("invalid engine outcome discriminator")
        if self.success:
            if self.value is None or self.error is not None or self.status is not self.value.status:
                _fail("successful outcome requires matching value and no error")
            if self.status not in CASH_FLOW_RESULT_BEARING_STATUS_MANIFEST:
                _fail("successful outcome cannot carry failure status")
        else:
            if self.value is not None or type(self.error) is not CashFlowEngineFailure:
                _fail("failed outcome requires error and no value")
            if self.status not in CASH_FLOW_FAILURE_STATUS_MANIFEST:
                _fail("failed outcome requires a failure-only status")
            if (
                self.status is CashFlowResultStatus.INVALID_INPUT
                and self.error.code not in CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1
            ):
                _fail("INVALID_INPUT status conflicts with the closed error mapping")
            if (
                self.status is CashFlowResultStatus.INTEGRITY_FAILURE
                and self.error.code not in CASH_FLOW_INTEGRITY_ERROR_CODES_V1
            ):
                _fail("INTEGRITY_FAILURE status conflicts with the closed error mapping")


_LOGICAL_TAGS: dict[type, str] = {
    CashFlowJsonObject: "cf.json_object.v1",
    CashFlowIssue: "cf.issue.v1",
    CashFlowPeriodDescriptor: "cf.period_descriptor.v1",
    CashFlowSourceSnapshot: "cf.source_snapshot.v1",
    CashFlowAccountEvidence: "cf.account_evidence.v1",
    CashFlowNonCashBridgeComponent: "cf.noncash_bridge_component.v1",
    IndirectCashFlowInput: "cf.indirect_input.v1",
    CashFlowPreResolvedContext: "cf.pre_resolved_context.v1",
    CashFlowEvidenceReference: "cf.evidence_reference.v1",
    CashFlowActivityAllocation: "cf.activity_allocation.v1",
    CashFlowLineItem: "cf.line_item.v1",
    CashFlowCashAvailabilityObservation: "cf.cash_availability_observation.v1",
    CashFlowCashAvailabilityDisclosure: "cf.cash_availability_disclosure.v1",
    CashFlowEndpointReconciliation: "cf.endpoint_reconciliation.v1",
    CashFlowReconciliation: "cf.reconciliation.v1",
    CashFlowCompleteness: "cf.completeness.v1",
    CashFlowSourceLineageReference: "cf.source_lineage_reference.v1",
    CashFlowResult: "cf.result.v1",
    CashFlowComputationDraft: "cf.computation_draft.v1",
    CashFlowPolicyVersion: "cf.policy_bundle.v1",
    CashAndCashEquivalentsPolicy: "cf.cash_equivalent_policy.v1",
    CashFlowPresentationPolicy: "cf.presentation_policy.v1",
}

_ENUM_LOGICAL_TAGS: dict[type[Enum], str] = {
    CashFlowMethod: "cf.method.v1",
    CashFlowActivity: "cf.activity.v1",
    CashAvailabilityClassification: "cf.cash_availability_classification.v1",
    CashFlowAvailabilityPeriodPosition: "cf.availability_period_position.v1",
    CashFlowLineAggregationRole: "cf.aggregation_role.v1",
    CashFlowEvidenceKind: "cf.evidence_kind.v1",
    CashFlowApplicability: "cf.applicability.v1",
    CashFlowResultStatus: "cf.status.v1",
    CashFlowReconciliationStatus: "cf.reconciliation_status.v1",
    CashFlowEndpointReconciliationStatus: "cf.endpoint_reconciliation_status.v1",
    CashFlowLineCode: "cf.line_code.v1",
    CashFlowSourceRole: "cf.source_role.v1",
    CashFlowSourceMode: "cf.source_mode.v1",
    CashFlowMappingMatchKind: "cf.mapping_match_kind.v1",
    CashFlowAccountRole: "cf.account_role.v1",
    CashFlowAccountDisposition: "cf.account_disposition.v1",
    CashFlowAccountFamilyCode: "cf.account_family_code.v1",
    CashFlowFamilyBalanceBasis: "cf.family_balance_basis.v1",
    CashFlowFamilyMemberKind: "cf.family_member_kind.v1",
    CashFlowNormalBalance: "cf.normal_balance.v1",
    CashFlowWorkingCapitalKind: "cf.working_capital_kind.v1",
    CashEligibilityRule: "cf.cash_eligibility_rule.v1",
    CashFlowStatementBasis: "cf.statement_basis.v1",
    CashFlowAccountingBasisCode: "cf.accounting_basis_code.v1",
    CashFlowBalanceSemantics: "cf.balance_semantics.v1",
    CashFlowZeroBalanceOmissionPolicy: "cf.zero_omission_policy.v1",
    CashFlowDerivationCode: "cf.derivation_code.v1",
    CashFlowNonCashBridgeDomain: "cf.noncash_bridge_domain.v1",
    CashFlowNonCashBridgeKind: "cf.noncash_bridge_kind.v1",
    CashFlowWarningCode: "cf.warning_code.v1",
    CashFlowErrorCode: "cf.error_code.v1",
    CashFlowPresentationProfile: "cf.presentation_profile.v1",
    CashFlowPresentationRule: "cf.presentation_rule.v1",
    CashFlowRoleSelectionRule: "cf.role_selection_rule.v1",
    PeriodType: "cf.period_type.v1",
    PeriodStatus: "cf.period_status.v1",
    AnalysisType: "fin.analysis_type.v1",
    AnalysisStatus: "fin.analysis_status.v1",
}


CashFlowEvidence = CashFlowEvidenceReference


def _enum_tag(value: Enum) -> str:
    tag = _ENUM_LOGICAL_TAGS.get(type(value))
    if tag is None:
        _fail("unregistered cash-flow enum type")
    return tag


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        _fail("non-finite Decimal is not canonical")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _canonical_node(value: object) -> object:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is Decimal:
        return {"$type": "decimal", "value": _decimal_text(value)}
    if type(value) is UUID:
        return {"$type": "uuid", "value": str(value)}
    if type(value) is date:
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, Enum):
        return {"$type": "enum", "name": _enum_tag(value), "value": value.value}
    if type(value) is tuple:
        return {"$type": "tuple", "items": [_canonical_node(item) for item in value]}
    if is_dataclass(value) and not isinstance(value, type):
        tag = _LOGICAL_TAGS.get(type(value))
        if tag is None:
            _fail("unregistered cash-flow record type")
        return {
            "$type": "record",
            "name": tag,
            "fields": [[field.name, _canonical_node(getattr(value, field.name))] for field in fields(value)],
        }
    _fail("unsupported value in cash-flow canonical serialization")


def canonical_cash_flow_bytes(value: object) -> bytes:
    return json.dumps(
        _canonical_node(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_cash_flow_digest(value: object) -> str:
    return sha256(b"cash-flow/contracts/v1\0" + canonical_cash_flow_bytes(value)).hexdigest()
