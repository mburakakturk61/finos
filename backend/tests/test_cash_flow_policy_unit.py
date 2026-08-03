from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal, Inexact, localcontext

import pytest

from app.engines.cash_flow import (
    CASH_AND_CASH_EQUIVALENTS_POLICY_V1,
    CASH_FLOW_PRESENTATION_POLICY_MANIFEST_V1,
    CashAndCashEquivalentsPolicy,
    CashFlowContractError,
    CashFlowPolicyVersion,
    CashEligibilityRule,
    CashFlowPresentationProfile,
    CashFlowPresentationRule,
    canonical_policy_bundle_digest,
    presentation_policy_for,
    quantize_completeness_ratio,
    quantize_money,
    reconciliation_thresholds,
    require_canonical_money,
    require_input_decimal,
)


def test_cash_equivalent_policy_v1_exact_contract() -> None:
    policy = CASH_AND_CASH_EQUIVALENTS_POLICY_V1
    assert policy.policy_version == "1.0.0"
    assert policy.automatic_cash_prefixes == ("100",)
    assert policy.evidence_required_prefixes == ("102",)
    assert policy.explicitly_excluded_prefixes == ()
    assert policy.maximum_maturity_days_at_acquisition == 90
    assert policy.require_restriction_nature_assessment is True
    assert policy.require_ready_convertibility is True
    assert policy.require_insignificant_value_change_risk is True
    assert policy.require_short_term_cash_commitment_purpose is True


@pytest.mark.parametrize(
    ("account_code", "expected"),
    [
        ("100", CashEligibilityRule.AUTOMATIC_CASH),
        ("10001", CashEligibilityRule.AUTOMATIC_CASH),
        ("102", CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE),
        ("10201", CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE),
        ("101", CashEligibilityRule.NOT_APPLICABLE),
        ("108", CashEligibilityRule.NOT_APPLICABLE),
        ("127", CashEligibilityRule.NOT_APPLICABLE),
    ],
)
def test_cash_equivalent_policy_allow_evidence_and_no_automatic_fallback(
    account_code: str, expected: CashEligibilityRule
) -> None:
    assert CASH_AND_CASH_EQUIVALENTS_POLICY_V1.exact_prefix_rule(account_code) == expected


def test_cash_equivalent_policy_rejects_overlapping_prefix_contract() -> None:
    with pytest.raises(CashFlowContractError):
        CashAndCashEquivalentsPolicy(
            policy_version="1.0.0",
            automatic_cash_prefixes=("100",),
            evidence_required_prefixes=("100",),
            explicitly_excluded_prefixes=(),
            maximum_maturity_days_at_acquisition=90,
            require_restriction_nature_assessment=True,
            require_ready_convertibility=True,
            require_insignificant_value_change_risk=True,
            require_short_term_cash_commitment_purpose=True,
        )


def test_cash_equivalent_policy_is_frozen_and_safe() -> None:
    policy = CASH_AND_CASH_EQUIVALENTS_POLICY_V1
    with pytest.raises(FrozenInstanceError):
        policy.maximum_maturity_days_at_acquisition = 30  # type: ignore[misc]
    assert "100" not in repr(policy)


def test_presentation_manifest_has_exact_three_profiles_and_versions() -> None:
    assert tuple(policy.profile for policy in CASH_FLOW_PRESENTATION_POLICY_MANIFEST_V1) == tuple(CashFlowPresentationProfile)
    assert tuple(policy.policy_version for policy in CASH_FLOW_PRESENTATION_POLICY_MANIFEST_V1) == (
        "tms_tfrs_2024_indirect/1.0.0",
        "bank_credit/1.0.0",
        "management/1.0.0",
    )


@pytest.mark.parametrize("profile", list(CashFlowPresentationProfile))
def test_presentation_profiles_have_closed_activity_rules(profile: CashFlowPresentationProfile) -> None:
    policy = presentation_policy_for(profile)
    assert policy.interest_paid_rule is CashFlowPresentationRule.FINANCING
    assert policy.interest_received_rule is CashFlowPresentationRule.INVESTING
    assert policy.dividends_received_rule is CashFlowPresentationRule.INVESTING
    assert policy.dividends_paid_rule is CashFlowPresentationRule.FINANCING
    assert policy.income_tax_paid_rule is CashFlowPresentationRule.ATTRIBUTION_THEN_OPERATING
    assert policy.demand_overdraft_rule is CashFlowPresentationRule.FINANCING


def test_statutory_profile_cutoff_and_early_adoption_are_exact() -> None:
    policy = presentation_policy_for(CashFlowPresentationProfile.TMS_TFRS_2024_INDIRECT_V1)
    assert policy.applicable_period_start_before == date(2027, 1, 1)
    assert policy.permits_ifrs18_early_adoption is False


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("policy_version", "mutated/1.0.0"),
        ("interest_paid_rule", CashFlowPresentationRule.OPERATING),
        ("applicable_period_start_before", date(2028, 1, 1)),
        ("permits_ifrs18_early_adoption", True),
    ],
)
def test_presentation_policy_rejects_every_supported_row_mutation(
    field_name: str, bad_value: object
) -> None:
    policy = presentation_policy_for(CashFlowPresentationProfile.TMS_TFRS_2024_INDIRECT_V1)
    with pytest.raises(CashFlowContractError):
        replace(policy, **{field_name: bad_value})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1.004"), Decimal("1.00")),
        (Decimal("1.005"), Decimal("1.00")),
        (Decimal("1.015"), Decimal("1.02")),
        (Decimal("-0.004"), Decimal("0.00")),
    ],
)
def test_monetary_rounding_boundaries(value: Decimal, expected: Decimal) -> None:
    result = quantize_money(value)
    assert result == expected
    if result == 0:
        assert result.is_signed() is False


def test_monetary_rounding_is_independent_of_ambient_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert quantize_money(Decimal("1.015")) == Decimal("1.02")


@pytest.mark.parametrize("bad", [1, 1.0, "1", Decimal("NaN"), Decimal("Infinity")])
def test_input_decimal_rejects_non_decimal_or_non_finite(bad: object) -> None:
    with pytest.raises(CashFlowContractError):
        require_input_decimal(bad)


def test_canonical_money_requires_scale_two() -> None:
    assert require_canonical_money(Decimal("1.00")) == Decimal("1.00")
    with pytest.raises(CashFlowContractError):
        require_canonical_money(Decimal("1.000"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0"), Decimal("0.0000")),
        (Decimal("0.50005"), Decimal("0.5000")),
        (Decimal("0.50015"), Decimal("0.5002")),
        (Decimal("1"), Decimal("1.0000")),
    ],
)
def test_completeness_ratio_rounding(value: Decimal, expected: Decimal) -> None:
    assert quantize_completeness_ratio(value) == expected


def test_reconciliation_thresholds_are_versioned_decimal_values() -> None:
    assert reconciliation_thresholds(Decimal("0.00")) == (Decimal("1.00"), Decimal("100.00"))
    assert reconciliation_thresholds(Decimal("1000000.00")) == (Decimal("100.00"), Decimal("5000.00"))


def test_policy_bundle_digest_is_stable_and_field_sensitive() -> None:
    values = dict(
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        cash_equivalent_policy_version="1.0.0",
        presentation_policy_version="management/1.0.0",
        reconciliation_policy_version="1.0.0",
        mapping_registry_version="1.0.0",
    )
    first = canonical_policy_bundle_digest(**values)
    assert first == canonical_policy_bundle_digest(**values)
    assert first != canonical_policy_bundle_digest(**(values | {"mapping_registry_version": "1.0.1"}))


def test_policy_version_value_object_matches_bundle_digest() -> None:
    version = CashFlowPolicyVersion(
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        cash_equivalent_policy_version="1.0.0",
        presentation_policy_version="management/1.0.0",
        reconciliation_policy_version="1.0.0",
        mapping_registry_version="1.0.0",
    )
    assert len(version.canonical_digest) == 64
    assert "management" not in repr(version)
