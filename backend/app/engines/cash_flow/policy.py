"""Versioned accounting-policy contracts for Milestone 4.5A.

Only immutable policy data and deterministic normalization helpers live here.
Account mapping and cash-flow calculation are intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, Inexact, InvalidOperation, Overflow, ROUND_HALF_EVEN, Rounded, localcontext
from enum import Enum
from hashlib import sha256
import json
from typing import Final

from .errors import CashFlowContractError
from .types import (
    CASH_FLOW_COMPLETENESS_SCALE_V1,
    CASH_FLOW_CURRENCY_CODE_V1,
    CASH_FLOW_MONETARY_SCALE_V1,
    CashEligibilityRule,
)


CASH_EQUIVALENT_POLICY_VERSION: Final = "1.0.0"
CASH_FLOW_RECONCILIATION_POLICY_VERSION: Final = "1.0.0"
CASH_FLOW_ACCOUNTING_POLICY_VERSION: Final = "tr_tdhp_accrual/1.0.0"
CASH_FLOW_MAPPING_REGISTRY_VERSION: Final = "1.0.0"
CASH_FLOW_POLICY_BUNDLE_VERSION: Final = "1.0.0"
CASH_FLOW_MONETARY_UNIT_MULTIPLIER_V1: Final = Decimal("1")
CASH_FLOW_MAX_ABSOLUTE_AMOUNT_V1: Final = Decimal("1e28")
CASH_FLOW_MAX_INPUT_SCALE_V1: Final = 8
CASH_FLOW_ROUNDING_TOLERANCE_ABS_V1: Final = Decimal("1.00")
CASH_FLOW_ROUNDING_TOLERANCE_REL_V1: Final = Decimal("0.0001")
CASH_FLOW_MATERIAL_THRESHOLD_ABS_V1: Final = Decimal("100.00")
CASH_FLOW_MATERIAL_THRESHOLD_REL_V1: Final = Decimal("0.005")


class _SafePolicyValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _require_non_empty_version(value: object, field_name: str) -> str:
    if type(value) is not str or not value or len(value) > 64:
        raise CashFlowContractError(f"invalid {field_name}")
    return value


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def require_input_decimal(value: object, *, field_name: str = "amount") -> Decimal:
    """Validate a pre-finalization Decimal without silently rounding it."""

    if type(value) is not Decimal or not value.is_finite():
        raise CashFlowContractError(f"{field_name} must be a finite Decimal")
    if value.copy_abs() >= CASH_FLOW_MAX_ABSOLUTE_AMOUNT_V1:
        raise CashFlowContractError(f"{field_name} magnitude is unsupported")
    scale = max(0, -value.as_tuple().exponent)
    if scale > CASH_FLOW_MAX_INPUT_SCALE_V1:
        raise CashFlowContractError(f"{field_name} scale is unsupported")
    return Decimal(0) if value == 0 else value


def quantize_money(value: object) -> Decimal:
    """Finalize a monetary leaf once with deterministic HALF_EVEN rounding."""

    decimal_value = require_input_decimal(value)
    quantum = Decimal(1).scaleb(-CASH_FLOW_MONETARY_SCALE_V1)
    try:
        with localcontext() as context:
            context.prec = 64
            context.rounding = ROUND_HALF_EVEN
            context.Emax = 999999
            context.Emin = -999999
            context.traps[InvalidOperation] = True
            context.traps[Overflow] = True
            context.traps[Inexact] = False
            context.traps[Rounded] = False
            result = decimal_value.quantize(quantum)
    except InvalidOperation as exc:
        raise CashFlowContractError("amount cannot be quantized") from exc
    return result.copy_abs() if result == 0 else result


def require_canonical_money(value: object, *, field_name: str = "amount") -> Decimal:
    if type(value) is not Decimal or value.as_tuple().exponent != -2:
        raise CashFlowContractError(f"{field_name} must use canonical scale 2")
    decimal_value = require_input_decimal(value, field_name=field_name)
    canonical = quantize_money(decimal_value)
    if decimal_value != canonical:
        raise CashFlowContractError(f"{field_name} must use canonical scale 2")
    return canonical


def quantize_completeness_ratio(value: object) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise CashFlowContractError("available_ratio must be a finite Decimal")
    decimal_value = value
    if not Decimal("0") <= decimal_value <= Decimal("1"):
        raise CashFlowContractError("available_ratio must be between zero and one")
    quantum = Decimal(1).scaleb(-CASH_FLOW_COMPLETENESS_SCALE_V1)
    with localcontext() as context:
        context.prec = 64
        context.rounding = ROUND_HALF_EVEN
        context.Emax = 999999
        context.Emin = -999999
        context.traps[InvalidOperation] = True
        context.traps[Overflow] = True
        context.traps[Inexact] = False
        context.traps[Rounded] = False
        result = decimal_value.quantize(quantum)
    return result.copy_abs() if result == 0 else result


def reconciliation_thresholds(reference: Decimal) -> tuple[Decimal, Decimal]:
    value = require_canonical_money(reference, field_name="reference")
    with localcontext() as context:
        context.prec = 64
        context.rounding = ROUND_HALF_EVEN
        context.Emax = 999999
        context.Emin = -999999
        context.traps[InvalidOperation] = True
        context.traps[Overflow] = True
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        rounding = max(
            CASH_FLOW_ROUNDING_TOLERANCE_ABS_V1,
            value.copy_abs() * CASH_FLOW_ROUNDING_TOLERANCE_REL_V1,
        )
        material = max(
            CASH_FLOW_MATERIAL_THRESHOLD_ABS_V1,
            value.copy_abs() * CASH_FLOW_MATERIAL_THRESHOLD_REL_V1,
        )
    return quantize_money(rounding), quantize_money(material)


def canonical_policy_bundle_digest(
    *,
    accounting_policy_version: str,
    cash_equivalent_policy_version: str,
    presentation_policy_version: str,
    reconciliation_policy_version: str,
    mapping_registry_version: str,
) -> str:
    values = (
        _require_non_empty_version(accounting_policy_version, "accounting_policy_version"),
        _require_non_empty_version(cash_equivalent_policy_version, "cash_equivalent_policy_version"),
        _require_non_empty_version(presentation_policy_version, "presentation_policy_version"),
        _require_non_empty_version(reconciliation_policy_version, "reconciliation_policy_version"),
        _require_non_empty_version(mapping_registry_version, "mapping_registry_version"),
    )
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return sha256(b"cash-flow/policy-bundle/v1\0" + payload).hexdigest()


@dataclass(frozen=True, repr=False)
class CashFlowPolicyVersion(_SafePolicyValue):
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    presentation_policy_version: str
    reconciliation_policy_version: str
    mapping_registry_version: str

    def __post_init__(self) -> None:
        for name in (
            "accounting_policy_version",
            "cash_equivalent_policy_version",
            "presentation_policy_version",
            "reconciliation_policy_version",
            "mapping_registry_version",
        ):
            _require_non_empty_version(getattr(self, name), name)

    @property
    def canonical_digest(self) -> str:
        return canonical_policy_bundle_digest(
            accounting_policy_version=self.accounting_policy_version,
            cash_equivalent_policy_version=self.cash_equivalent_policy_version,
            presentation_policy_version=self.presentation_policy_version,
            reconciliation_policy_version=self.reconciliation_policy_version,
            mapping_registry_version=self.mapping_registry_version,
        )


def _validate_prefix_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise CashFlowContractError(f"{field_name} must be a tuple")
    if value != tuple(sorted(value)) or len(value) != len(set(value)):
        raise CashFlowContractError(f"{field_name} must be unique and sorted")
    if any(type(prefix) is not str or not prefix or not prefix.isascii() or not prefix.isdigit() for prefix in value):
        raise CashFlowContractError(f"{field_name} contains an invalid prefix")
    return value


@dataclass(frozen=True, repr=False)
class CashAndCashEquivalentsPolicy(_SafePolicyValue):
    policy_version: str
    automatic_cash_prefixes: tuple[str, ...]
    evidence_required_prefixes: tuple[str, ...]
    explicitly_excluded_prefixes: tuple[str, ...]
    maximum_maturity_days_at_acquisition: int
    require_restriction_nature_assessment: bool
    require_ready_convertibility: bool
    require_insignificant_value_change_risk: bool
    require_short_term_cash_commitment_purpose: bool

    def __post_init__(self) -> None:
        _require_non_empty_version(self.policy_version, "policy_version")
        groups = tuple(
            _validate_prefix_tuple(getattr(self, name), name)
            for name in (
                "automatic_cash_prefixes",
                "evidence_required_prefixes",
                "explicitly_excluded_prefixes",
            )
        )
        flattened = tuple(prefix for group in groups for prefix in group)
        if len(flattened) != len(set(flattened)):
            raise CashFlowContractError("cash-equivalent prefix groups overlap")
        if type(self.maximum_maturity_days_at_acquisition) is not int or self.maximum_maturity_days_at_acquisition <= 0:
            raise CashFlowContractError("maximum maturity days must be positive")
        for name in (
            "require_restriction_nature_assessment",
            "require_ready_convertibility",
            "require_insignificant_value_change_risk",
            "require_short_term_cash_commitment_purpose",
        ):
            if type(getattr(self, name)) is not bool:
                raise CashFlowContractError(f"{name} must be bool")

    def exact_prefix_rule(self, account_code: str) -> CashEligibilityRule:
        """Return only the policy contract branch; it does not map accounts."""

        if type(account_code) is not str or not account_code.isascii() or not account_code.isdigit():
            raise CashFlowContractError("account code must contain ASCII digits")
        matches: list[tuple[int, str]] = []
        for branch, prefixes in (
            (CashEligibilityRule.AUTOMATIC_CASH, self.automatic_cash_prefixes),
            (CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE, self.evidence_required_prefixes),
            (CashEligibilityRule.EXCLUDED, self.explicitly_excluded_prefixes),
        ):
            matches.extend((len(prefix), branch) for prefix in prefixes if account_code.startswith(prefix))
        if not matches:
            return CashEligibilityRule.NOT_APPLICABLE
        longest = max(length for length, _ in matches)
        winners = {branch for length, branch in matches if length == longest}
        if len(winners) != 1:
            raise CashFlowContractError("cash-equivalent prefix rule is ambiguous")
        return winners.pop()


# Compatibility spelling retained inside the new 4.5A package only.
CashEquivalentPolicy = CashAndCashEquivalentsPolicy

CASH_AND_CASH_EQUIVALENTS_POLICY_V1: Final = CashAndCashEquivalentsPolicy(
    policy_version=CASH_EQUIVALENT_POLICY_VERSION,
    automatic_cash_prefixes=("100",),
    evidence_required_prefixes=("102",),
    explicitly_excluded_prefixes=(),
    maximum_maturity_days_at_acquisition=90,
    require_restriction_nature_assessment=True,
    require_ready_convertibility=True,
    require_insignificant_value_change_risk=True,
    require_short_term_cash_commitment_purpose=True,
)


class CashFlowPresentationProfile(str, Enum):
    TMS_TFRS_2024_INDIRECT_V1 = "tms_tfrs_2024_indirect_v1"
    BANK_CREDIT_V1 = "bank_credit_v1"
    MANAGEMENT_V1 = "management_v1"


class CashFlowPresentationRule(str, Enum):
    OPERATING = "operating"
    INVESTING = "investing"
    FINANCING = "financing"
    ATTRIBUTION_THEN_OPERATING = "attribution_then_operating"
    REQUIRES_EXPLICIT_EVIDENCE = "requires_explicit_evidence"


_PRESENTATION_ROWS: Final = {
    CashFlowPresentationProfile.TMS_TFRS_2024_INDIRECT_V1: (
        "tms_tfrs_2024_indirect/1.0.0",
        CashFlowPresentationRule.FINANCING,
        CashFlowPresentationRule.INVESTING,
        CashFlowPresentationRule.INVESTING,
        CashFlowPresentationRule.FINANCING,
        CashFlowPresentationRule.ATTRIBUTION_THEN_OPERATING,
        CashFlowPresentationRule.FINANCING,
        date(2027, 1, 1),
        False,
    ),
    CashFlowPresentationProfile.BANK_CREDIT_V1: (
        "bank_credit/1.0.0",
        CashFlowPresentationRule.FINANCING,
        CashFlowPresentationRule.INVESTING,
        CashFlowPresentationRule.INVESTING,
        CashFlowPresentationRule.FINANCING,
        CashFlowPresentationRule.ATTRIBUTION_THEN_OPERATING,
        CashFlowPresentationRule.FINANCING,
        None,
        True,
    ),
    CashFlowPresentationProfile.MANAGEMENT_V1: (
        "management/1.0.0",
        CashFlowPresentationRule.FINANCING,
        CashFlowPresentationRule.INVESTING,
        CashFlowPresentationRule.INVESTING,
        CashFlowPresentationRule.FINANCING,
        CashFlowPresentationRule.ATTRIBUTION_THEN_OPERATING,
        CashFlowPresentationRule.FINANCING,
        None,
        True,
    ),
}


@dataclass(frozen=True, repr=False)
class CashFlowPresentationPolicy(_SafePolicyValue):
    policy_version: str
    profile: CashFlowPresentationProfile
    interest_paid_rule: CashFlowPresentationRule
    interest_received_rule: CashFlowPresentationRule
    dividends_received_rule: CashFlowPresentationRule
    dividends_paid_rule: CashFlowPresentationRule
    income_tax_paid_rule: CashFlowPresentationRule
    demand_overdraft_rule: CashFlowPresentationRule
    applicable_period_start_before: date | None
    permits_ifrs18_early_adoption: bool

    def __post_init__(self) -> None:
        if type(self.profile) is not CashFlowPresentationProfile:
            raise CashFlowContractError("unknown cash-flow presentation profile")
        actual = (
            self.policy_version,
            self.interest_paid_rule,
            self.interest_received_rule,
            self.dividends_received_rule,
            self.dividends_paid_rule,
            self.income_tax_paid_rule,
            self.demand_overdraft_rule,
            self.applicable_period_start_before,
            self.permits_ifrs18_early_adoption,
        )
        if actual != _PRESENTATION_ROWS[self.profile]:
            raise CashFlowContractError("unsupported cash-flow presentation policy mutation")


def _build_presentation_policy(
    profile: CashFlowPresentationProfile,
) -> CashFlowPresentationPolicy:
    row = _PRESENTATION_ROWS[profile]
    return CashFlowPresentationPolicy(
        policy_version=row[0],
        profile=profile,
        interest_paid_rule=row[1],
        interest_received_rule=row[2],
        dividends_received_rule=row[3],
        dividends_paid_rule=row[4],
        income_tax_paid_rule=row[5],
        demand_overdraft_rule=row[6],
        applicable_period_start_before=row[7],
        permits_ifrs18_early_adoption=row[8],
    )


CASH_FLOW_PRESENTATION_POLICY_MANIFEST_V1: Final = tuple(
    _build_presentation_policy(profile) for profile in CashFlowPresentationProfile
)


def presentation_policy_for(
    profile: CashFlowPresentationProfile,
) -> CashFlowPresentationPolicy:
    if type(profile) is not CashFlowPresentationProfile:
        raise CashFlowContractError("unknown cash-flow presentation profile")
    return CASH_FLOW_PRESENTATION_POLICY_MANIFEST_V1[list(CashFlowPresentationProfile).index(profile)]


def normalized_decimal_text(value: Decimal) -> str:
    return _decimal_text(require_input_decimal(value))
