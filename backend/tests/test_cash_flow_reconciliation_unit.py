"""Unit/property/golden acceptance for Milestone 4.5E reconciliation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.engines.cash_flow import (
    CashFlowAccountDisposition,
    CashFlowAccountRole,
    CashFlowActivity,
    CashFlowActivityAllocation,
    CashFlowApplicability,
    CashFlowDataQualitySummary,
    CashFlowDerivationCode,
    CashFlowEngineService,
    CashFlowEndpointReconciliationStatus,
    CashFlowErrorCode,
    CashFlowEvidenceKind,
    CashFlowJsonObject,
    CashFlowIssue,
    CashFlowLineCode,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
    CashFlowSourceRole,
    CashFlowWarningCode,
    assess_data_quality,
    canonical_cash_flow_digest,
    cash_flow_result_digest,
    evaluate_reconciliation,
    finalize_cash_flow_result,
    quantize_money,
)
from app.engines.cash_flow.errors import CashFlowContractError
from app.engines.cash_flow.reconciliation import CashFlowFinalizationIntegrityError
from test_cash_flow_indirect_core_unit import (
    _base_evidence,
    _digest,
    _draft,
    _estimated_input,
    _input,
    _line,
)


PROOF = _digest("cash-flow-comparability-proof-45e")


def _with_bs_endpoints(inputs, *, opening=Decimal("1000"), closing=Decimal("1200")):
    current = inputs.current_balance_sheet
    prior = inputs.prior_balance_sheet
    if current is not None:
        current = replace(
            current,
            result_payload=CashFlowJsonObject(items=(("cash_and_equivalents", closing),)),
        )
    if prior is not None:
        prior = replace(
            prior,
            result_payload=CashFlowJsonObject(items=(("cash_and_equivalents", opening),)),
        )
    return replace(inputs, current_balance_sheet=current, prior_balance_sheet=prior)


def _effect_line(draft, code, amount):
    amount = quantize_money(amount)
    base = _line(draft, code)
    reference = replace(
        _line(draft, CashFlowLineCode.NET_PROFIT).evidence[0],
        derivation_code=(
            CashFlowDerivationCode.PRESENTATION_RECLASSIFICATION
            if code is CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT
            else CashFlowDerivationCode.SOURCE_VALUE
        ),
    )
    activity = (
        CashFlowActivity.RECLASSIFICATION_EFFECT
        if code is CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT
        else CashFlowActivity.FX_EFFECT
    )
    return replace(
        base,
        canonical_amount=amount,
        presentation_allocations=(CashFlowActivityAllocation(activity, amount),),
        applicability=(
            CashFlowApplicability.PROVEN_NOT_APPLICABLE
            if amount == 0
            else CashFlowApplicability.APPLICABLE
        ),
        evidence_kind=CashFlowEvidenceKind.EXACT,
        evidence=(reference,),
        missing_inputs=(),
        warning_codes=(),
    )


def _with_effects(draft, *, fx=Decimal("-2"), reclassification=Decimal("0")):
    replacements = {
        CashFlowLineCode.AUTHORITATIVE_FX_EFFECT: fx,
        CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT: reclassification,
    }
    lines = tuple(
        _effect_line(draft, item.line_code, replacements[item.line_code])
        if item.line_code in replacements
        else item
        for item in draft.line_items
    )
    return replace(draft, line_items=lines)


def _final(*, fx=Decimal("-2"), estimated=False):
    inputs = _with_bs_endpoints(_estimated_input() if estimated else _input())
    draft = _with_effects(_draft(inputs), fx=fx)
    return inputs, finalize_cash_flow_result(
        draft=draft,
        inputs=inputs,
        comparability_proof_digest=PROOF,
    )


@pytest.mark.parametrize(
    "fixture",
    json.loads(
        (Path(__file__).parent / "data" / "synthetic" / "cash_flow_reconciliation_golden_v1.json")
        .read_text(encoding="utf-8")
    )["scenarios"],
    ids=lambda fixture: fixture["scenario"],
)
def test_versioned_synthetic_reconciliation_golden_fixtures(fixture):
    if fixture.get("insufficient"):
        inputs = _with_bs_endpoints(_input(prior=False))
        outcome = CashFlowEngineService().analyze(inputs, comparability_proof_digest=None)
        assert outcome.success
        result = outcome.value
    elif fixture.get("integrity_failure"):
        inputs = _with_bs_endpoints(_input(), closing=Decimal("1201"))
        outcome = CashFlowEngineService().analyze(inputs, comparability_proof_digest=PROOF)
        assert not outcome.success
        assert outcome.status.value == fixture["expected_status"]
        assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT
        return
    else:
        _inputs, result = _final(
            fx=Decimal(fixture["fx"]),
            estimated=fixture.get("estimated", False),
        )
    assert result.status.value == fixture["expected_status"]
    assert result.reconciliation_status.value == fixture["expected_reconciliation"]
    expected = fixture["expected_difference"]
    assert result.reconciliation_difference == (None if expected is None else Decimal(expected))


@pytest.mark.parametrize(
    ("balance", "calculated", "expected"),
    (
        ("200.00", "200.00", CashFlowReconciliationStatus.RECONCILED),
        ("200.00", "199.00", CashFlowReconciliationStatus.ROUNDING_DIFFERENCE),
        ("200.00", "198.99", CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL),
        ("200.00", "100.00", CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL),
        ("200.00", "99.99", CashFlowReconciliationStatus.UNRECONCILED_MATERIAL),
        ("200.00", "201.00", CashFlowReconciliationStatus.ROUNDING_DIFFERENCE),
        ("0.00", "-1.00", CashFlowReconciliationStatus.ROUNDING_DIFFERENCE),
        ("0.00", "-100.00", CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL),
        ("0.00", "-100.01", CashFlowReconciliationStatus.UNRECONCILED_MATERIAL),
        ("2000000.00", "1999800.00", CashFlowReconciliationStatus.ROUNDING_DIFFERENCE),
        ("2000000.00", "1989999.99", CashFlowReconciliationStatus.UNRECONCILED_MATERIAL),
    ),
)
def test_reconciliation_threshold_boundaries(balance, calculated, expected):
    value = evaluate_reconciliation(Decimal(balance), Decimal(calculated))
    assert value.status is expected
    assert value.difference == Decimal(balance) - Decimal(calculated)


@pytest.mark.parametrize(
    ("balance", "calculated", "expected"),
    (
        ("-2000000.00", "-1999800.00", CashFlowReconciliationStatus.ROUNDING_DIFFERENCE),
        ("-2000000.00", "-1989999.99", CashFlowReconciliationStatus.UNRECONCILED_MATERIAL),
    ),
)
def test_negative_large_reference_uses_absolute_thresholds(balance, calculated, expected):
    assert evaluate_reconciliation(Decimal(balance), Decimal(calculated)).status is expected


def test_complete_result_assembles_exact_endpoint_and_formula_projections():
    _inputs, result = _final()
    assert result.status is CashFlowResultStatus.COMPLETE_RECONCILED
    assert result.opening_cash_and_cash_equivalents == Decimal("1000.00")
    assert result.closing_cash_and_cash_equivalents == Decimal("1200.00")
    assert result.balance_sheet_net_cash_change == Decimal("200.00")
    assert result.calculated_net_cash_change == Decimal("200.00")
    assert result.reconciliation_difference == Decimal("0.00")
    assert all(
        endpoint.status is CashFlowEndpointReconciliationStatus.MATCHED
        for endpoint in result.endpoint_reconciliations
    )
    assert result.completeness.estimated_count == 0
    assert result.completeness.unavailable_count == 0


def test_missing_fx_or_reclassification_never_becomes_a_balancing_plug():
    inputs = _with_bs_endpoints(_input())
    result = finalize_cash_flow_result(
        draft=_draft(inputs),
        inputs=inputs,
        comparability_proof_digest=PROOF,
    )
    assert result.authoritative_fx_effect is None
    assert result.authoritative_reclassification_effect is None
    assert result.calculated_net_cash_change is None
    assert result.reconciliation_difference is None
    assert result.reconciliation_status is CashFlowReconciliationStatus.NOT_PERFORMED_INCOMPLETE_COMPONENTS
    assert result.status is CashFlowResultStatus.PARTIAL_UNRECONCILED
    assert any(
        warning.code is CashFlowWarningCode.PRESENTATION_EVIDENCE_UNAVAILABLE
        for warning in result.warnings
    )


def test_authoritative_reclassification_is_an_explicit_formula_component():
    inputs = _with_bs_endpoints(_input())
    result = finalize_cash_flow_result(
        draft=_with_effects(_draft(inputs), fx=Decimal("-2"), reclassification=Decimal("5")),
        inputs=inputs,
        comparability_proof_digest=PROOF,
    )
    assert result.authoritative_reclassification_effect == Decimal("5.00")
    assert result.calculated_net_cash_change == sum(
        (
            result.operating_cash_flow,
            result.investing_cash_flow,
            result.financing_cash_flow,
            result.authoritative_fx_effect,
            result.authoritative_reclassification_effect,
        ),
        Decimal("0.00"),
    )


def test_rounding_difference_is_preserved_and_maps_to_reconciled_family():
    _inputs, result = _final(fx=Decimal("-1"))
    assert result.reconciliation_status is CashFlowReconciliationStatus.ROUNDING_DIFFERENCE
    assert result.reconciliation_difference == Decimal("-1.00")
    assert result.status is CashFlowResultStatus.COMPLETE_RECONCILED
    assert any(
        warning.code is CashFlowWarningCode.RECONCILIATION_DIFFERENCE
        for warning in result.warnings
    )


def test_reconciled_estimated_result_remains_partial_and_estimated():
    inputs, result = _final(estimated=True)
    assert result.status is CashFlowResultStatus.PARTIAL_RECONCILED
    assert result.reconciliation_status is CashFlowReconciliationStatus.RECONCILED
    assert result.completeness.estimated_count > 0
    quality = assess_data_quality(
        inputs=inputs,
        line_items=result.line_items,
        warnings=result.warnings,
        reconciliation_status=result.reconciliation_status,
    )
    assert CashFlowLineCode.INVESTING_CASH_FLOW in quality.estimated_line_codes
    assert type(quality) is CashFlowDataQualitySummary


def test_insufficient_result_has_no_monetary_summary_or_fabricated_prior_proof():
    inputs = _with_bs_endpoints(_input(prior=False))
    outcome = CashFlowEngineService().analyze(inputs, comparability_proof_digest=None)
    assert outcome.success
    result = outcome.value
    assert result.status is CashFlowResultStatus.INSUFFICIENT_DATA
    assert all(item.canonical_amount is None for item in result.line_items)
    assert result.prior_period_id is None
    assert result.comparability_proof_digest is None


@pytest.mark.parametrize("missing_position", ("opening", "closing"))
def test_missing_balance_sheet_cash_endpoint_is_insufficient_not_zero(missing_position):
    inputs = _with_bs_endpoints(_input())
    source_field = "prior_balance_sheet" if missing_position == "opening" else "current_balance_sheet"
    inputs = replace(
        inputs,
        **{
            source_field: replace(
                getattr(inputs, source_field),
                result_payload=CashFlowJsonObject(items=()),
            )
        },
    )
    outcome = CashFlowEngineService().analyze(inputs, comparability_proof_digest=PROOF)
    assert outcome.success
    assert outcome.value.status is CashFlowResultStatus.INSUFFICIENT_DATA
    assert all(item.canonical_amount is None for item in outcome.value.line_items)
    assert outcome.value.comparability_proof_digest is None


def test_restricted_cash_classification_change_is_reconciled_to_exact_endpoints():
    rows = tuple(
        replace(row, is_restricted=True, restriction_preserves_cash_nature=False)
        if row.account_code == "100" and row.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE
        else row
        for row in _base_evidence()
    )
    inputs = _with_bs_endpoints(
        _input(evidence=rows),
        opening=Decimal("1000"),
        closing=Decimal("0"),
    )
    result = finalize_cash_flow_result(
        draft=_with_effects(_draft(inputs)),
        inputs=inputs,
        comparability_proof_digest=PROOF,
    )
    assert result.opening_cash_and_cash_equivalents == Decimal("1000.00")
    assert result.closing_cash_and_cash_equivalents == Decimal("0.00")
    assert all(
        endpoint.status is CashFlowEndpointReconciliationStatus.MATCHED
        for endpoint in result.endpoint_reconciliations
    )


def test_endpoint_mismatch_is_fail_closed_integrity_failure():
    inputs = _with_bs_endpoints(_input(), closing=Decimal("1200.01"))
    outcome = CashFlowEngineService().analyze(inputs, comparability_proof_digest=PROOF)
    assert not outcome.success
    assert outcome.status is CashFlowResultStatus.INTEGRITY_FAILURE
    assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT


def test_draft_policy_binding_mismatch_is_fail_closed():
    inputs = _with_bs_endpoints(_input())
    draft = _with_effects(_draft(inputs))
    other = replace(inputs, accounting_policy_version="different/1.0.0")
    with pytest.raises(CashFlowFinalizationIntegrityError):
        finalize_cash_flow_result(
            draft=draft,
            inputs=other,
            comparability_proof_digest=PROOF,
        )


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("accounting_policy_version", CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED),
        ("mapping_registry_version", CashFlowErrorCode.MAPPING_REGISTRY_VERSION_UNSUPPORTED),
    ),
)
def test_unsupported_policy_and_mapping_versions_have_exact_safe_errors(field, expected):
    inputs = replace(_input(), **{field: "unsupported/9.9.9"})
    outcome = CashFlowEngineService().analyze(inputs, comparability_proof_digest=PROOF)
    assert not outcome.success
    assert outcome.status is CashFlowResultStatus.INVALID_INPUT
    assert outcome.error.code is expected


def test_data_quality_inventory_is_deterministic_and_has_no_opaque_score():
    unclassified = replace(
        _base_evidence()[0],
        account_code="999999",
        canonical_account_role=CashFlowAccountRole.UNCLASSIFIED,
        account_disposition=CashFlowAccountDisposition.UNRESOLVED,
        disposition_proof_digest=None,
        account_family_code=None,
        account_family_reference_digest=None,
        family_member_kind=None,
    )
    inputs = _input(evidence=_base_evidence() + (unclassified,))
    draft = _draft(inputs)
    arguments = dict(
        inputs=inputs,
        line_items=draft.line_items,
        warnings=draft.warnings,
        reconciliation_status=CashFlowReconciliationStatus.NOT_PERFORMED_INCOMPLETE_COMPONENTS,
    )
    first = assess_data_quality(**arguments)
    second = assess_data_quality(**arguments)
    assert first == second
    assert first.unclassified_account_count == 1
    assert len(first.unclassified_account_reference_digests) == 1
    assert not hasattr(first, "confidence_score")


def test_reconciled_result_never_upgrades_estimated_contributor_evidence():
    _inputs, result = _final(estimated=True)
    by_code = {item.line_code: item for item in result.line_items}
    assert by_code[CashFlowLineCode.INVESTING_CASH_FLOW].evidence_kind is CashFlowEvidenceKind.ESTIMATED
    assert by_code[CashFlowLineCode.FINANCING_CASH_FLOW].evidence_kind is CashFlowEvidenceKind.ESTIMATED
    assert by_code[CashFlowLineCode.CALCULATED_NET_CASH_CHANGE].evidence_kind is CashFlowEvidenceKind.ESTIMATED
    assert by_code[CashFlowLineCode.RECONCILIATION_DIFFERENCE].evidence_kind is CashFlowEvidenceKind.ESTIMATED


def test_duplicate_evidence_and_bundle_digest_mismatch_are_rejected_before_calculation():
    inputs = _input()
    with pytest.raises(CashFlowContractError):
        replace(inputs, account_evidence=inputs.account_evidence + (inputs.account_evidence[0],))
    outcome = CashFlowEngineService().analyze(
        replace(inputs, account_evidence_bundle_digest=_digest("wrong-bundle")),
        comparability_proof_digest=PROOF,
    )
    assert not outcome.success
    assert outcome.status is CashFlowResultStatus.INTEGRITY_FAILURE
    assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT


def test_final_digest_is_deterministic_and_changes_with_amount_status_and_warning():
    _inputs, exact = _final()
    _inputs, repeated = _final()
    _inputs, mismatch = _final(fx=Decimal("0"))
    assert cash_flow_result_digest(exact) == cash_flow_result_digest(repeated)
    assert cash_flow_result_digest(exact) != cash_flow_result_digest(mismatch)
    extra = CashFlowIssue(
        code=CashFlowWarningCode.NEGATIVE_CASH_BALANCE,
        safe_metadata=CashFlowJsonObject(items=()),
    )
    warnings = tuple(sorted(exact.warnings + (extra,), key=canonical_cash_flow_digest))
    warned = replace(exact, warnings=warnings)
    assert cash_flow_result_digest(exact) != cash_flow_result_digest(warned)


def test_material_warning_and_global_warning_order_are_canonical():
    _inputs, result = _final(fx=Decimal("101"))
    assert result.reconciliation_status is CashFlowReconciliationStatus.UNRECONCILED_MATERIAL
    assert any(
        warning.code is CashFlowWarningCode.MATERIAL_RECONCILIATION_DIFFERENCE
        for warning in result.warnings
    )
    assert tuple(map(canonical_cash_flow_digest, result.warnings)) == tuple(
        sorted(map(canonical_cash_flow_digest, result.warnings))
    )


def test_reordered_source_evidence_canonicalizes_to_same_final_digest():
    inputs = _with_bs_endpoints(_input())
    reordered = _with_bs_endpoints(_input(evidence=reversed(inputs.account_evidence)))
    first = finalize_cash_flow_result(
        draft=_with_effects(_draft(inputs)),
        inputs=inputs,
        comparability_proof_digest=PROOF,
    )
    second = finalize_cash_flow_result(
        draft=_with_effects(_draft(reordered)),
        inputs=reordered,
        comparability_proof_digest=PROOF,
    )
    assert cash_flow_result_digest(first) == cash_flow_result_digest(second)


def test_safe_outcome_and_result_repr_never_leak_raw_input():
    outcome = CashFlowEngineService().analyze(
        {"secret": "raw-customer-payload"},
        comparability_proof_digest=PROOF,
    )
    assert not outcome.success
    assert outcome.status is CashFlowResultStatus.INVALID_INPUT
    assert "raw-customer-payload" not in repr(outcome.error)
    _inputs, result = _final()
    assert repr(result) == "CashFlowResult()"
    with pytest.raises(FrozenInstanceError):
        result.status = CashFlowResultStatus.PARTIAL_RECONCILED


def test_no_persistence_framework_or_45f_dependency_in_finalization_modules():
    import ast

    package = Path(__file__).parents[1] / "app" / "engines" / "cash_flow"
    for name in ("reconciliation.py", "quality.py", "service.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert imports.isdisjoint({"sqlalchemy", "fastapi", "pydantic"})
