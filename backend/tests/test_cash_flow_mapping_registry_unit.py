"""Milestone 4.5B immutable registry, precedence, and determinism tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import random

import pytest

from app.engines.cash_flow import (
    CASH_FLOW_ACCOUNT_FAMILY_MANIFEST_V1,
    CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1,
    CASH_FLOW_CODE_MAPPING_MANIFEST_V1,
    CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1,
    CASH_FLOW_MAPPING_REGISTRY_DIGEST_V1,
    CASH_FLOW_ROLE_BEHAVIOR_MANIFEST_V1,
    CashFlowAccountMapping,
    CashFlowAccountMappingRegistry,
    CashFlowAccountDisposition,
    CashFlowAccountFamilyCode,
    CashFlowAccountRole,
    CashFlowActivity,
    CashFlowBankAccountEvidence,
    CashFlowContractError,
    CashFlowEvidenceKind,
    CashFlowMappingEntry,
    CashFlowMappingMatchKind,
    CashFlowNormalBalance,
    CashFlowRoleBehavior,
    CashFlowWorkingCapitalKind,
    CashEligibilityRule,
    classify_bank_account_evidence,
    normalize_account_code,
)


REGISTRY = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1


def _entry(
    mapping_id: str,
    pattern: str,
    role: CashFlowAccountRole,
    *,
    kind: CashFlowMappingMatchKind,
    normal: CashFlowNormalBalance = CashFlowNormalBalance.DEBIT,
    deprecated: bool = False,
    replaced_by: str | None = None,
) -> CashFlowMappingEntry:
    return CashFlowMappingEntry(
        mapping=CashFlowAccountMapping(
            mapping_id=mapping_id,
            match_kind=kind,
            account_code_or_prefix=pattern,
            explicit_account_role=None,
            resolved_account_role=role,
            code_normal_balance=normal,
            account_family_code=None,
            family_member_kind=None,
            model_version_introduced="1.0.0",
        ),
        registry_version="1.0.0",
        effective_from=None,
        deprecated=deprecated,
        replaced_by=replaced_by,
        source_reference="test.registry",
    )


def _registry(extra: tuple[CashFlowMappingEntry, ...] = (), *, entries=None, version="1.0.0"):
    selected = CASH_FLOW_CODE_MAPPING_MANIFEST_V1 + CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1 + extra if entries is None else entries
    return CashFlowAccountMappingRegistry(
        registry_version=version,
        entries=selected,
        role_behaviors=CASH_FLOW_ROLE_BEHAVIOR_MANIFEST_V1,
        account_families=CASH_FLOW_ACCOUNT_FAMILY_MANIFEST_V1,
    )


@pytest.mark.parametrize(
    ("raw", "canonical"),
    (("100", "100"), ("00100", "00100"), ("100.01", "10001"), ("100-01", "10001"), ("100/01", "10001"), ("100 01", "10001")),
)
def test_account_code_closed_normalization(raw, canonical):
    assert normalize_account_code(raw) == canonical


@pytest.mark.parametrize(
    "raw",
    ("", " 100", "100 ", "100..01", "100_01", "100A", "١٠٠", "１００", ".100", "100/", "1\t00", None, 100),
)
def test_account_code_rejects_trim_fuzzy_unicode_and_non_string(raw):
    with pytest.raises(CashFlowContractError):
        normalize_account_code(raw)


def test_production_registry_shape_and_golden_digest():
    assert len(CASH_FLOW_CODE_MAPPING_MANIFEST_V1) == 61
    assert len(CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1) == 36
    assert len(CASH_FLOW_ROLE_BEHAVIOR_MANIFEST_V1) == 36
    assert len(CASH_FLOW_ACCOUNT_FAMILY_MANIFEST_V1) == 4
    assert CASH_FLOW_MAPPING_REGISTRY_DIGEST_V1 == "8164df2463ec6da91c57496e55cc2d34f59f2835e06a6f78c9bb591558172f5a"


def test_exact_mapping_always_wins_over_prefix():
    exact = _entry("exact:10001", "10001", CashFlowAccountRole.OTHER_OPERATING_ASSET, kind=CashFlowMappingMatchKind.EXACT_ACCOUNT_CODE)
    result = _registry((exact,)).resolve("100.01")
    assert result.mapping_id == "exact:10001"
    assert result.match_kind is CashFlowMappingMatchKind.EXACT_ACCOUNT_CODE


def test_longest_prefix_always_wins_over_parent_prefix():
    child = _entry("prefix:1001", "1001", CashFlowAccountRole.OTHER_OPERATING_ASSET, kind=CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX)
    result = _registry((child,)).resolve("100.10.25")
    assert result.mapping_id == "prefix:1001"


def test_code_mapping_wins_over_explicit_role_fallback():
    result = REGISTRY.resolve("120", explicit_account_role=CashFlowAccountRole.BORROWING)
    assert result.mapping_id == "cf120"
    assert result.resolved_account_role is CashFlowAccountRole.OPERATING_RECEIVABLE


def test_explicit_trusted_role_is_fallback_only():
    result = REGISTRY.resolve("777", explicit_account_role=CashFlowAccountRole.BORROWING)
    assert result.mapping_id == "role:borrowing"
    assert result.match_kind is CashFlowMappingMatchKind.EXPLICIT_ACCOUNT_ROLE
    assert result.resolved_account_role is CashFlowAccountRole.BORROWING


def test_unknown_account_is_unclassified_without_mapping_evidence():
    result = REGISTRY.resolve("777")
    assert result.match_kind is CashFlowMappingMatchKind.UNCLASSIFIED
    assert result.resolved_account_role is CashFlowAccountRole.UNCLASSIFIED
    assert result.mapping_id is None
    assert result.source_reference is None
    assert result.evidence_kind is CashFlowEvidenceKind.UNAVAILABLE
    assert result.account_disposition is CashFlowAccountDisposition.UNRESOLVED
    assert result.disposition_evidence_required is True
    assert not hasattr(result, "amount")


def test_account_name_is_not_an_accepted_resolution_input():
    with pytest.raises(TypeError):
        REGISTRY.resolve("777", account_name="KASA")


@pytest.mark.parametrize(
    ("code", "mapping_id", "role", "normal"),
    (
        ("100.01", "cf100", CashFlowAccountRole.CASH_ON_HAND, CashFlowNormalBalance.DEBIT),
        ("120.01", "cf120", CashFlowAccountRole.OPERATING_RECEIVABLE, CashFlowNormalBalance.DEBIT),
        ("153", "cf15", CashFlowAccountRole.INVENTORY, CashFlowNormalBalance.DEBIT),
        ("320", "cf32", CashFlowAccountRole.OPERATING_PAYABLE, CashFlowNormalBalance.CREDIT),
        ("257", "cf257", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
        ("268", "cf268", CashFlowAccountRole.NON_CASH_ADJUSTMENT, CashFlowNormalBalance.CREDIT),
        ("400", "cf400", CashFlowAccountRole.BORROWING, CashFlowNormalBalance.CREDIT),
        ("500", "cf500", CashFlowAccountRole.EQUITY, CashFlowNormalBalance.CREDIT),
        ("640", "cf640", CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL, CashFlowNormalBalance.CREDIT),
    ),
)
def test_authoritative_prefix_manifest(code, mapping_id, role, normal):
    result = REGISTRY.resolve(code)
    assert (result.mapping_id, result.resolved_account_role, result.code_normal_balance) == (mapping_id, role, normal)


def test_resolution_exposes_required_registry_metadata_without_amounts():
    result = REGISTRY.resolve("257")
    assert result.cash_flow_activity is CashFlowActivity.OPERATING
    assert result.line_codes
    assert result.working_capital_behavior is CashFlowWorkingCapitalKind.NOT_APPLICABLE
    assert result.cash_equivalent_inclusion is CashEligibilityRule.NOT_APPLICABLE
    assert result.non_cash_flag is True
    assert result.evidence_requirement is True
    assert len(result.presentation_policy_compatibility) == 3
    assert result.source_reference == "design.section10"
    assert not hasattr(result, "amount")


@pytest.mark.parametrize("code", ("302", "308", "402", "408", "335", "360", "381", "481", "600", "660", "661", "999999"))
def test_non_manifest_codes_never_gain_a_silent_role(code):
    assert REGISTRY.resolve(code).resolved_account_role is CashFlowAccountRole.UNCLASSIFIED


def test_cash_and_working_capital_roles_are_disjoint():
    for behavior in REGISTRY.role_behaviors:
        if behavior.working_capital_kind is not CashFlowWorkingCapitalKind.NOT_APPLICABLE:
            assert behavior.cash_eligibility_rule not in {
                CashEligibilityRule.AUTOMATIC_CASH,
                CashEligibilityRule.REQUIRES_ELIGIBILITY_EVIDENCE,
            }


def test_all_role_behaviors_are_exhaustive_and_normal_balance_is_preserved():
    assert {item.role for item in REGISTRY.role_behaviors} == set(CashFlowAccountRole)
    for entry in CASH_FLOW_CODE_MAPPING_MANIFEST_V1:
        behavior = REGISTRY.behavior_for(entry.mapping.resolved_account_role)
        if behavior.normal_balance is not None:
            assert entry.mapping.code_normal_balance is behavior.normal_balance


def test_family_manifest_is_exact_and_longest_prefix_protects_contra_rows():
    ppe_gross = REGISTRY.resolve("250")
    ppe_contra = REGISTRY.resolve("257")
    assert ppe_gross.account_family_code.value == "ppe_net"
    assert ppe_gross.family_member_kind.value == "asset_gross"
    assert ppe_contra.mapping_id == "cf257"
    assert ppe_contra.account_family_code.value == "ppe_net"
    assert ppe_contra.family_member_kind.value == "asset_contra"
    assert ppe_gross.account_disposition is CashFlowAccountDisposition.INVESTING_FAMILY
    assert ppe_contra.account_disposition is CashFlowAccountDisposition.INVESTING_FAMILY


def test_family_reference_digests_are_deterministic_and_distinct():
    digests = tuple(
        REGISTRY.family_reference_digest(code)
        for code in CashFlowAccountFamilyCode
    )
    assert len(set(digests)) == 4
    assert all(len(digest) == 64 for digest in digests)
    assert digests == tuple(
        REGISTRY.family_reference_digest(code)
        for code in CashFlowAccountFamilyCode
    )


def test_every_authoritative_mapping_has_one_exhaustive_initial_disposition():
    samples = {
        entry.mapping.mapping_id: REGISTRY.resolve(
            entry.mapping.account_code_or_prefix
            if entry.mapping.account_code_or_prefix is not None
            else "999999",
            explicit_account_role=(
                entry.mapping.explicit_account_role
                if entry.mapping.match_kind is CashFlowMappingMatchKind.EXPLICIT_ACCOUNT_ROLE
                else None
            ),
        )
        for entry in REGISTRY.entries
    }
    assert len(samples) == len(REGISTRY.entries)
    assert all(type(result.account_disposition) is CashFlowAccountDisposition for result in samples.values())
    assert all(
        result.disposition_evidence_required
        is (result.account_disposition is CashFlowAccountDisposition.UNRESOLVED)
        for result in samples.values()
    )


def test_cash_and_working_capital_initial_dispositions_are_mutually_exclusive():
    cash = REGISTRY.resolve("100")
    receivable = REGISTRY.resolve("120")
    payable = REGISTRY.resolve("320")
    assert cash.account_disposition is CashFlowAccountDisposition.CASH_OR_CASH_EQUIVALENT
    assert receivable.account_disposition is CashFlowAccountDisposition.OPERATING_WORKING_CAPITAL
    assert payable.account_disposition is CashFlowAccountDisposition.OPERATING_WORKING_CAPITAL


def test_registry_and_nested_values_are_immutable():
    with pytest.raises(FrozenInstanceError):
        REGISTRY.registry_version = "2.0.0"
    with pytest.raises(FrozenInstanceError):
        REGISTRY.entries[0].deprecated = True


def test_registry_digest_and_resolution_are_input_order_independent():
    rng = random.Random(4502)
    entries = list(REGISTRY.entries)
    behaviors = list(REGISTRY.role_behaviors)
    families = list(REGISTRY.account_families)
    rng.shuffle(entries)
    rng.shuffle(behaviors)
    rng.shuffle(families)
    shuffled = CashFlowAccountMappingRegistry("1.0.0", tuple(entries), tuple(behaviors), tuple(families))
    assert shuffled.canonical_digest == REGISTRY.canonical_digest
    assert shuffled.resolve("257") == REGISTRY.resolve("257")
    assert shuffled.resolve("999") == REGISTRY.resolve("999")


def test_semantic_version_change_changes_registry_digest():
    entries = tuple(replace(entry, registry_version="1.0.1") for entry in REGISTRY.entries)
    changed = CashFlowAccountMappingRegistry("1.0.1", entries, REGISTRY.role_behaviors, REGISTRY.account_families)
    assert changed.canonical_digest != REGISTRY.canonical_digest


def test_expected_registry_version_mismatch_fails_closed():
    with pytest.raises(CashFlowContractError, match="version mismatch"):
        REGISTRY.resolve("100", expected_registry_version="2.0.0")


def test_duplicate_exact_mapping_is_rejected():
    entries = REGISTRY.entries + (
        _entry("exact:a", "777", CashFlowAccountRole.PPE, kind=CashFlowMappingMatchKind.EXACT_ACCOUNT_CODE),
        _entry("exact:b", "777", CashFlowAccountRole.BORROWING, kind=CashFlowMappingMatchKind.EXACT_ACCOUNT_CODE, normal=CashFlowNormalBalance.CREDIT),
    )
    with pytest.raises(CashFlowContractError, match="duplicate account mapping pattern"):
        _registry(entries=entries)


def test_duplicate_prefix_mapping_is_rejected():
    entries = REGISTRY.entries + (
        _entry("prefix:a", "777", CashFlowAccountRole.PPE, kind=CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX),
        _entry("prefix:b", "777", CashFlowAccountRole.BORROWING, kind=CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX, normal=CashFlowNormalBalance.CREDIT),
    )
    with pytest.raises(CashFlowContractError, match="duplicate account mapping pattern"):
        _registry(entries=entries)


def test_duplicate_explicit_role_mapping_is_rejected():
    duplicate = replace(CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1[0], mapping=replace(CASH_FLOW_EXPLICIT_ROLE_MAPPING_MANIFEST_V1[0].mapping, mapping_id="duplicate:role"))
    with pytest.raises(CashFlowContractError, match="duplicate explicit role"):
        _registry((duplicate,))


def test_code_and_role_normal_balance_conflict_is_rejected():
    conflicting = _entry("prefix:conflict", "777", CashFlowAccountRole.CASH_ON_HAND, kind=CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX, normal=CashFlowNormalBalance.CREDIT)
    with pytest.raises(CashFlowContractError, match="normal balance conflict"):
        _registry((conflicting,))


def test_deprecated_mapping_is_never_silently_used():
    replacement = _entry("prefix:new", "778", CashFlowAccountRole.PPE, kind=CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX)
    deprecated = _entry("prefix:old", "777", CashFlowAccountRole.PPE, kind=CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX, deprecated=True, replaced_by="prefix:new")
    registry = _registry((replacement, deprecated))
    with pytest.raises(CashFlowContractError, match="deprecated"):
        registry.resolve("77701")


def test_deprecated_mapping_without_replacement_is_rejected():
    mapping = _entry("prefix:old", "777", CashFlowAccountRole.PPE, kind=CashFlowMappingMatchKind.LONGEST_ACCOUNT_CODE_PREFIX)
    with pytest.raises(CashFlowContractError):
        _registry((replace(mapping, deprecated=True),))


@pytest.mark.parametrize(
    ("evidence", "role", "availability"),
    (
        (CashFlowBankAccountEvidence(authoritative_overdraft=True), CashFlowAccountRole.BORROWING, None),
        (CashFlowBankAccountEvidence(is_repayable_on_demand=True, is_restricted=False), CashFlowAccountRole.DEMAND_DEPOSIT, "unrestricted_included"),
        (CashFlowBankAccountEvidence(is_repayable_on_demand=True, is_restricted=True, restriction_preserves_cash_nature=True), CashFlowAccountRole.DEMAND_DEPOSIT, "restricted_included"),
        (CashFlowBankAccountEvidence(is_repayable_on_demand=False, is_restricted=False, maturity_days_at_acquisition=90, ready_convertible_to_known_cash=True, insignificant_value_change_risk=True, held_for_short_term_cash_commitments=True), CashFlowAccountRole.CASH_EQUIVALENT_INVESTMENT, "unrestricted_included"),
        (CashFlowBankAccountEvidence(authoritative_term_or_investment_purpose=True), CashFlowAccountRole.FINANCIAL_INVESTMENT, None),
        (CashFlowBankAccountEvidence(is_repayable_on_demand=False, is_restricted=True, restriction_preserves_cash_nature=False), CashFlowAccountRole.RESTRICTED_BANK_ASSET, "restricted_excluded"),
        (CashFlowBankAccountEvidence(), CashFlowAccountRole.BANK_ACCOUNT_CANDIDATE, "eligibility_unresolved"),
    ),
)
def test_bank_and_cash_equivalent_closed_branches(evidence, role, availability):
    result = classify_bank_account_evidence(evidence)
    assert result.resolved_account_role is role
    assert (result.availability_classification.value if result.availability_classification else None) == availability


def test_maturity_above_policy_limit_is_not_cash_equivalent():
    result = classify_bank_account_evidence(CashFlowBankAccountEvidence(
        is_repayable_on_demand=False,
        is_restricted=False,
        maturity_days_at_acquisition=91,
        ready_convertible_to_known_cash=True,
        insignificant_value_change_risk=True,
        held_for_short_term_cash_commitments=True,
    ))
    assert result.resolved_account_role is CashFlowAccountRole.BANK_ACCOUNT_CANDIDATE
    assert result.evidence_kind is CashFlowEvidenceKind.UNAVAILABLE


def test_negative_balance_is_not_a_registry_or_bank_branch_input():
    assert "balance" not in CashFlowBankAccountEvidence.__dataclass_fields__
    assert "amount" not in CashFlowAccountMapping.__dataclass_fields__


def test_contradictory_bank_branch_evidence_fails_closed():
    with pytest.raises(CashFlowContractError, match="contradictory branches"):
        classify_bank_account_evidence(CashFlowBankAccountEvidence(
            authoritative_overdraft=True,
            is_repayable_on_demand=True,
            is_restricted=False,
        ))


def test_role_behavior_rejects_cash_and_working_capital_conflict():
    with pytest.raises(CashFlowContractError, match="cannot overlap"):
        replace(
            REGISTRY.behavior_for(CashFlowAccountRole.OPERATING_RECEIVABLE),
            cash_eligibility_rule=CashEligibilityRule.AUTOMATIC_CASH,
        )


def test_conditional_role_cannot_claim_static_activity():
    behavior = REGISTRY.behavior_for(CashFlowAccountRole.BORROWING)
    with pytest.raises(CashFlowContractError, match="conditional behavior"):
        replace(behavior, static_activity=CashFlowActivity.FINANCING)


def test_resolution_is_deterministic_for_many_codes():
    rng = random.Random(4503)
    codes = tuple(str(rng.randrange(1, 999999)) for _ in range(500))
    first = tuple(REGISTRY.resolve(code) for code in codes)
    second = tuple(REGISTRY.resolve(code) for code in codes)
    assert first == second
    assert all(not hasattr(result, "amount") for result in first)
