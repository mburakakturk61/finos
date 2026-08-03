"""Immutable account-mapping values for Milestone 4.5B.

The contracts in this module classify accounts and describe evidence needs.
They deliberately contain no balance, movement, period, or cash-flow amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from .errors import CashFlowContractError
from .policy import CashFlowPresentationProfile
from .types import (
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


_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$", re.ASCII)
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$", re.ASCII)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class _SafeMappingValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _fail(message: str) -> None:
    raise CashFlowContractError(message)


def _require_identifier(value: object, field_name: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(f"{field_name} is not a canonical identifier")
    return value


def _require_version(value: object, field_name: str) -> str:
    if type(value) is not str or _VERSION_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be a semantic version")
    return value


def _require_enum(value: object, enum_type: type, field_name: str) -> None:
    if type(value) is not enum_type:
        _fail(f"{field_name} must use {enum_type.__name__}")


@dataclass(frozen=True, repr=False)
class CashFlowAccountMapping(_SafeMappingValue):
    mapping_id: str
    match_kind: CashFlowMappingMatchKind
    account_code_or_prefix: str | None
    explicit_account_role: CashFlowAccountRole | None
    resolved_account_role: CashFlowAccountRole
    code_normal_balance: CashFlowNormalBalance | None
    account_family_code: CashFlowAccountFamilyCode | None
    family_member_kind: CashFlowFamilyMemberKind | None
    model_version_introduced: str

    def __post_init__(self) -> None:
        _require_identifier(self.mapping_id, "mapping_id")
        _require_enum(self.match_kind, CashFlowMappingMatchKind, "match_kind")
        _require_enum(self.resolved_account_role, CashFlowAccountRole, "resolved_account_role")
        _require_version(self.model_version_introduced, "model_version_introduced")
        if self.match_kind in {
            CashFlowMappingMatchKind.EXACT_ACCOUNT_CODE,
            CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX,
        }:
            if (
                type(self.account_code_or_prefix) is not str
                or not 1 <= len(self.account_code_or_prefix) <= 64
                or not self.account_code_or_prefix.isascii()
                or not self.account_code_or_prefix.isdigit()
            ):
                _fail("code mapping must carry canonical ASCII digits")
            if self.explicit_account_role is not None:
                _fail("code mapping cannot carry an explicit role")
            _require_enum(self.code_normal_balance, CashFlowNormalBalance, "code_normal_balance")
        elif self.match_kind is CashFlowMappingMatchKind.EXPLICIT_ACCOUNT_ROLE:
            if self.account_code_or_prefix is not None or self.code_normal_balance is not None:
                _fail("explicit-role mapping cannot carry code metadata")
            if self.explicit_account_role is not self.resolved_account_role:
                _fail("explicit-role mapping must resolve its exact trusted role")
        else:
            _fail("UNCLASSIFIED is a resolution fallback, not a registry row")
        if (self.account_family_code is None) != (self.family_member_kind is None):
            _fail("family code and member kind must be present together")
        if self.account_family_code is not None:
            _require_enum(self.account_family_code, CashFlowAccountFamilyCode, "account_family_code")
            _require_enum(self.family_member_kind, CashFlowFamilyMemberKind, "family_member_kind")


@dataclass(frozen=True, repr=False)
class CashFlowRoleBehavior(_SafeMappingValue):
    role: CashFlowAccountRole
    selection_rule: CashFlowRoleSelectionRule
    static_activity: CashFlowActivity | None
    possible_activities: tuple[CashFlowActivity, ...]
    candidate_line_codes: tuple[CashFlowLineCode, ...]
    normal_balance: CashFlowNormalBalance | None
    working_capital_kind: CashFlowWorkingCapitalKind
    cash_eligibility_rule: CashEligibilityRule
    gross_movement_evidence_required: bool
    model_version_introduced: str

    def __post_init__(self) -> None:
        _require_enum(self.role, CashFlowAccountRole, "role")
        _require_enum(self.selection_rule, CashFlowRoleSelectionRule, "selection_rule")
        if self.static_activity is not None:
            _require_enum(self.static_activity, CashFlowActivity, "static_activity")
        if type(self.possible_activities) is not tuple or not self.possible_activities:
            _fail("possible_activities must be a non-empty tuple")
        if any(type(value) is not CashFlowActivity for value in self.possible_activities):
            _fail("possible_activities contains an invalid activity")
        if len(set(self.possible_activities)) != len(self.possible_activities):
            _fail("possible_activities must be unique")
        if type(self.candidate_line_codes) is not tuple:
            _fail("candidate_line_codes must be a tuple")
        if any(type(value) is not CashFlowLineCode for value in self.candidate_line_codes):
            _fail("candidate_line_codes contains an invalid line")
        if len(set(self.candidate_line_codes)) != len(self.candidate_line_codes):
            _fail("candidate_line_codes must be unique")
        if self.normal_balance is not None:
            _require_enum(self.normal_balance, CashFlowNormalBalance, "normal_balance")
        _require_enum(self.working_capital_kind, CashFlowWorkingCapitalKind, "working_capital_kind")
        _require_enum(self.cash_eligibility_rule, CashEligibilityRule, "cash_eligibility_rule")
        if type(self.gross_movement_evidence_required) is not bool:
            _fail("gross_movement_evidence_required must be bool")
        _require_version(self.model_version_introduced, "model_version_introduced")
        if self.selection_rule is CashFlowRoleSelectionRule.STATIC:
            if self.static_activity is None or self.possible_activities != (self.static_activity,):
                _fail("static behavior must expose its one exact activity")
        elif self.static_activity is not None:
            _fail("conditional behavior cannot carry a static activity")
        if self.working_capital_kind is not CashFlowWorkingCapitalKind.NOT_APPLICABLE:
            if self.static_activity is not CashFlowActivity.OPERATING:
                _fail("working-capital role must be statically operating")
            if self.cash_eligibility_rule in {
                CashEligibilityRule.AUTOMATIC_CASH,
                CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE,
            }:
                _fail("working-capital and cash eligibility cannot overlap")


@dataclass(frozen=True, repr=False)
class CashFlowAccountFamilyDefinition(_SafeMappingValue):
    family_code: CashFlowAccountFamilyCode
    domain: str
    balance_basis: CashFlowFamilyBalanceBasis
    members: tuple[tuple[str, CashFlowFamilyMemberKind], ...]
    model_version_introduced: str

    def __post_init__(self) -> None:
        _require_enum(self.family_code, CashFlowAccountFamilyCode, "family_code")
        _require_identifier(self.domain, "domain")
        _require_enum(self.balance_basis, CashFlowFamilyBalanceBasis, "balance_basis")
        if type(self.members) is not tuple or not self.members:
            _fail("family members must be a non-empty tuple")
        mapping_ids: list[str] = []
        for member in self.members:
            if type(member) is not tuple or len(member) != 2:
                _fail("family member must be an immutable pair")
            mapping_ids.append(_require_identifier(member[0], "family mapping_id"))
            _require_enum(member[1], CashFlowFamilyMemberKind, "family_member_kind")
        if len(mapping_ids) != len(set(mapping_ids)):
            _fail("family mapping IDs must be unique")
        _require_version(self.model_version_introduced, "model_version_introduced")


@dataclass(frozen=True, repr=False)
class CashFlowMappingEntry(_SafeMappingValue):
    mapping: CashFlowAccountMapping
    registry_version: str
    effective_from: date | None
    deprecated: bool
    replaced_by: str | None
    source_reference: str

    def __post_init__(self) -> None:
        if type(self.mapping) is not CashFlowAccountMapping:
            _fail("mapping entry must carry CashFlowAccountMapping")
        _require_version(self.registry_version, "registry_version")
        if self.effective_from is not None and type(self.effective_from) is not date:
            _fail("effective_from must be date or None")
        if type(self.deprecated) is not bool:
            _fail("deprecated must be bool")
        if self.replaced_by is not None:
            _require_identifier(self.replaced_by, "replaced_by")
            if not self.deprecated:
                _fail("replaced_by is valid only for deprecated mappings")
            if self.replaced_by == self.mapping.mapping_id:
                _fail("mapping cannot replace itself")
        _require_identifier(self.source_reference, "source_reference")


@dataclass(frozen=True, repr=False)
class CashFlowMappingResolution(_SafeMappingValue):
    registry_version: str
    registry_digest: str
    canonical_account_code: str
    match_kind: CashFlowMappingMatchKind
    mapping_id: str | None
    resolved_account_role: CashFlowAccountRole
    code_normal_balance: CashFlowNormalBalance | None
    role_behavior: CashFlowRoleBehavior
    account_family_code: CashFlowAccountFamilyCode | None
    family_member_kind: CashFlowFamilyMemberKind | None
    account_disposition: CashFlowAccountDisposition
    disposition_evidence_required: bool
    evidence_kind: CashFlowEvidenceKind
    source_reference: str | None

    def __post_init__(self) -> None:
        _require_version(self.registry_version, "registry_version")
        if type(self.registry_digest) is not str or _DIGEST_RE.fullmatch(self.registry_digest) is None:
            _fail("registry_digest must be lowercase SHA-256")
        if type(self.canonical_account_code) is not str or not self.canonical_account_code.isascii() or not self.canonical_account_code.isdigit():
            _fail("canonical_account_code must contain ASCII digits")
        _require_enum(self.match_kind, CashFlowMappingMatchKind, "match_kind")
        _require_enum(self.resolved_account_role, CashFlowAccountRole, "resolved_account_role")
        _require_enum(self.account_disposition, CashFlowAccountDisposition, "account_disposition")
        if type(self.disposition_evidence_required) is not bool:
            _fail("disposition_evidence_required must be bool")
        if type(self.role_behavior) is not CashFlowRoleBehavior or self.role_behavior.role is not self.resolved_account_role:
            _fail("role behavior must match the resolved role")
        _require_enum(self.evidence_kind, CashFlowEvidenceKind, "evidence_kind")
        if self.match_kind is CashFlowMappingMatchKind.UNCLASSIFIED:
            if self.mapping_id is not None or self.source_reference is not None:
                _fail("unclassified fallback cannot claim mapping evidence")
            if self.resolved_account_role is not CashFlowAccountRole.UNCLASSIFIED:
                _fail("unclassified fallback must resolve UNCLASSIFIED")
        else:
            _require_identifier(self.mapping_id, "mapping_id")
            _require_identifier(self.source_reference, "source_reference")
        if (self.account_family_code is None) != (self.family_member_kind is None):
            _fail("resolved family metadata must be present together")
        if self.account_disposition is CashFlowAccountDisposition.UNRESOLVED:
            if not self.disposition_evidence_required:
                _fail("UNRESOLVED disposition must remain evidence-required")
        elif self.disposition_evidence_required:
            _fail("resolved disposition cannot remain evidence-required")

    @property
    def cash_flow_activity(self) -> CashFlowActivity | None:
        return self.role_behavior.static_activity

    @property
    def line_codes(self) -> tuple[CashFlowLineCode, ...]:
        return self.role_behavior.candidate_line_codes

    @property
    def working_capital_behavior(self) -> CashFlowWorkingCapitalKind:
        return self.role_behavior.working_capital_kind

    @property
    def cash_equivalent_inclusion(self) -> CashEligibilityRule:
        return self.role_behavior.cash_eligibility_rule

    @property
    def non_cash_flag(self) -> bool:
        return self.resolved_account_role in {
            CashFlowAccountRole.NON_CASH_INVESTMENT_COMMITMENT,
            CashFlowAccountRole.NON_CASH_EQUITY,
            CashFlowAccountRole.DEFERRED_TAX_ACCRUAL,
            CashFlowAccountRole.NON_CASH_ADJUSTMENT,
        }

    @property
    def evidence_requirement(self) -> bool:
        return (
            self.role_behavior.gross_movement_evidence_required
            or self.role_behavior.selection_rule is not CashFlowRoleSelectionRule.STATIC
            or self.disposition_evidence_required
        )

    @property
    def presentation_policy_compatibility(self) -> tuple[CashFlowPresentationProfile, ...]:
        return tuple(CashFlowPresentationProfile)


@dataclass(frozen=True, repr=False)
class CashFlowBankAccountEvidence(_SafeMappingValue):
    authoritative_overdraft: bool = False
    is_repayable_on_demand: bool | None = None
    is_restricted: bool | None = None
    restriction_preserves_cash_nature: bool | None = None
    maturity_days_at_acquisition: int | None = None
    ready_convertible_to_known_cash: bool | None = None
    insignificant_value_change_risk: bool | None = None
    held_for_short_term_cash_commitments: bool | None = None
    authoritative_term_or_investment_purpose: bool = False

    def __post_init__(self) -> None:
        for name in (
            "authoritative_overdraft",
            "is_repayable_on_demand",
            "is_restricted",
            "restriction_preserves_cash_nature",
            "ready_convertible_to_known_cash",
            "insignificant_value_change_risk",
            "held_for_short_term_cash_commitments",
            "authoritative_term_or_investment_purpose",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                _fail(f"{name} must be bool or None")
        if self.maturity_days_at_acquisition is not None:
            if type(self.maturity_days_at_acquisition) is not int or not 0 <= self.maturity_days_at_acquisition <= 36500:
                _fail("maturity_days_at_acquisition is invalid")


@dataclass(frozen=True, repr=False)
class CashFlowBankAccountClassification(_SafeMappingValue):
    resolved_account_role: CashFlowAccountRole
    availability_classification: CashAvailabilityClassification | None
    evidence_kind: CashFlowEvidenceKind

    def __post_init__(self) -> None:
        _require_enum(self.resolved_account_role, CashFlowAccountRole, "resolved_account_role")
        if self.availability_classification is not None:
            _require_enum(self.availability_classification, CashAvailabilityClassification, "availability_classification")
        _require_enum(self.evidence_kind, CashFlowEvidenceKind, "evidence_kind")
        if self.resolved_account_role in {
            CashFlowAccountRole.BORROWING,
            CashFlowAccountRole.FINANCIAL_INVESTMENT,
        }:
            if self.availability_classification is not None:
                _fail("non-cash branches do not produce availability disclosure")
        elif self.availability_classification is None:
            _fail("cash eligibility branch must produce an availability classification")
