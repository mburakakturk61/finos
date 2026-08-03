"""Unit/property acceptance for Milestone 4.5D indirect cash-flow core."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal, localcontext
import json
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from app.engines.cash_flow import (
    CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1,
    CASH_FLOW_LINE_ITEM_MANIFEST_V1,
    CASH_FLOW_MAPPING_REGISTRY_VERSION,
    CashFlowAccountDisposition,
    CashFlowAccountEvidence,
    CashFlowAccountFamilyCode,
    CashFlowAccountRole,
    CashFlowAccountingBasisCode,
    CashFlowApplicability,
    CashFlowBalanceSemantics,
    CashFlowContractError,
    CashFlowErrorCode,
    CashFlowEvidenceKind,
    CashFlowFamilyBalanceBasis,
    CashFlowJsonObject,
    CashFlowLineCode,
    CashFlowNonCashBridgeComponent,
    CashFlowNonCashBridgeDomain,
    CashFlowNonCashBridgeKind,
    CashFlowSourceMode,
    CashFlowSourceRole,
    CashFlowSourceSnapshot,
    CashFlowStatementBasis,
    CashFlowWarningCode,
    CashFlowZeroBalanceOmissionPolicy,
    IndirectCashFlowCoreService,
    IndirectCashFlowInput,
    canonical_cash_flow_digest,
    canonical_evidence_bundle_digest,
    computation_draft_digest,
    presentation_policy_for,
)
from app.engines.cash_flow.policy import CashFlowPresentationProfile
from app.engines.cash_flow.types import CashAvailabilityClassification
from app.models.enums import AnalysisStatus, AnalysisType, PeriodStatus, PeriodType
from app.engines.cash_flow.contracts import CashFlowPeriodDescriptor


NS = UUID("00000000-0000-0000-0000-00000000450d")
COMPANY = uuid5(NS, "company")
TENANT = uuid5(NS, "tenant")
CURRENT = uuid5(NS, "current")
PRIOR = uuid5(NS, "prior")


def _digest(label: str) -> str:
    import hashlib
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _period(period_id, year):
    return CashFlowPeriodDescriptor(
        period_id=period_id,
        company_id=COMPANY,
        tenant_id=TENANT,
        currency_code="TRY",
        monetary_unit_multiplier=Decimal("1"),
        period_type=PeriodType.YEAR_END,
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        annual_reporting_period_start_date=date(year, 1, 1),
        annual_reporting_period_end_date=date(year, 12, 31),
        months_covered=12,
        status=PeriodStatus.CLOSED,
        accounting_basis_code=CashFlowAccountingBasisCode.TR_TDHP_ACCRUAL,
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        ifrs18_early_adopted=False,
    )


def _source(role, payload=()):
    period_id = PRIOR if role in {CashFlowSourceRole.PRIOR_BALANCE_SHEET, CashFlowSourceRole.PRIOR_TRIAL_BALANCE} else CURRENT
    analysis_type = {
        CashFlowSourceRole.CURRENT_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
        CashFlowSourceRole.PRIOR_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
        CashFlowSourceRole.CURRENT_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
        CashFlowSourceRole.CURRENT_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
        CashFlowSourceRole.PRIOR_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    }[role]
    flow = role is CashFlowSourceRole.CURRENT_INCOME_STATEMENT
    digest = _digest(role.value)
    return CashFlowSourceSnapshot(
        source_role=role,
        analysis_result_id=uuid5(NS, role.value),
        same_run_engine_code=None,
        analysis_type=analysis_type,
        source_mode=CashFlowSourceMode.MULTI_SOURCE_DERIVED,
        company_id=COMPANY,
        period_id=period_id,
        primary_document_id=None,
        canonical_digest=digest,
        recomputed_result_payload_digest=digest,
        source_provenance_digest=_digest(role.value + ":provenance"),
        engine_schema_version="1.0.0",
        engine_model_version="1.0.0",
        status=AnalysisStatus.COMPLETED,
        error_message_is_null=True,
        statement_basis=CashFlowStatementBasis.FLOW_INTERVAL if flow else CashFlowStatementBasis.AS_OF,
        coverage_start_date=date(2025, 1, 1) if flow else None,
        coverage_end_date=date(2025, 12, 31) if period_id == CURRENT else date(2024, 12, 31),
        currency_code="TRY",
        monetary_unit_multiplier=Decimal("1"),
        result_payload=CashFlowJsonObject(items=tuple(sorted(payload))),
    )


def _disposition(role, resolved):
    if resolved.account_disposition is not CashFlowAccountDisposition.UNRESOLVED:
        return resolved.account_disposition
    if role is CashFlowAccountRole.UNCLASSIFIED:
        return CashFlowAccountDisposition.UNRESOLVED
    if role in {
        CashFlowAccountRole.INTEREST_EXPENSE_ACCRUAL,
        CashFlowAccountRole.INTEREST_INCOME_ACCRUAL,
        CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL,
        CashFlowAccountRole.CURRENT_TAX_EXPENSE_ACCRUAL,
    }:
        return CashFlowAccountDisposition.PNL_CAPTURED_IN_NET_PROFIT
    return CashFlowAccountDisposition.PROVEN_NOT_RELEVANT


def _account(role, code, source_role, balance, debit=Decimal("0"), credit=Decimal("0")):
    resolved = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.resolve(code, explicit_account_role=role)
    disposition = _disposition(role, resolved)
    period_id = PRIOR if source_role is CashFlowSourceRole.PRIOR_TRIAL_BALANCE else CURRENT
    source = _source(source_role)
    family_digest = (
        CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.family_reference_digest(resolved.account_family_code)
        if resolved.account_family_code else None
    )
    return CashFlowAccountEvidence(
        source_role=source_role,
        source_analysis_result_id=source.analysis_result_id,
        same_run_engine_code=None,
        source_canonical_digest=source.canonical_digest,
        source_provenance_digest=source.source_provenance_digest,
        account_code=code,
        canonical_account_role=role,
        account_disposition=disposition,
        disposition_proof_digest=(
            None
            if disposition is CashFlowAccountDisposition.UNRESOLVED
            else _digest(f"disposition:{source_role.value}:{code}")
        ),
        account_family_code=resolved.account_family_code,
        account_family_reference_digest=family_digest,
        family_member_kind=resolved.family_member_kind,
        source_balance=balance,
        source_debit_movement=debit,
        source_credit_movement=credit,
        source_currency_code="TRY",
        source_unit_multiplier=Decimal("1"),
        functional_currency_code="TRY",
        normalized_functional_currency_balance=balance,
        normalized_functional_currency_debit_movement=debit,
        normalized_functional_currency_credit_movement=credit,
        translation_provenance_digest=None,
        balance_semantics=CashFlowBalanceSemantics.CLOSING_BALANCE,
        as_of_date=date(2024, 12, 31) if period_id == PRIOR else date(2025, 12, 31),
        complete_snapshot=True,
        zero_balance_omission_policy=CashFlowZeroBalanceOmissionPolicy.EXPLICIT_ZERO_ROWS,
        maturity_days_at_acquisition=None,
        is_restricted=False,
        is_repayable_on_demand=None,
        readily_convertible_to_known_amount=None,
        insignificant_value_change_risk=None,
        held_for_short_term_cash_commitments=None,
        integral_to_cash_management=None,
        restriction_preserves_cash_nature=None,
    )


def _pair(role, code, opening, closing, debit=Decimal("0"), credit=Decimal("0")):
    return (
        _account(role, code, CashFlowSourceRole.PRIOR_TRIAL_BALANCE, opening),
        _account(role, code, CashFlowSourceRole.CURRENT_TRIAL_BALANCE, closing, debit, credit),
    )


def _base_evidence():
    rows = []
    rows += _pair(CashFlowAccountRole.CASH_ON_HAND, "100", Decimal("1000"), Decimal("1200"))
    rows += _pair(CashFlowAccountRole.INVENTORY, "150", Decimal("200"), Decimal("250"))
    rows += _pair(CashFlowAccountRole.OPERATING_RECEIVABLE, "120", Decimal("300"), Decimal("280"))
    rows += _pair(CashFlowAccountRole.OTHER_OPERATING_ASSET, "180", Decimal("50"), Decimal("60"))
    rows += _pair(CashFlowAccountRole.OPERATING_PAYABLE, "320", Decimal("150"), Decimal("180"))
    rows += _pair(CashFlowAccountRole.OTHER_OPERATING_LIABILITY, "340", Decimal("20"), Decimal("15"))
    rows += _pair(CashFlowAccountRole.PPE, "250", Decimal("1000"), Decimal("1080"), Decimal("100"), Decimal("20"))
    rows += _pair(CashFlowAccountRole.INTANGIBLE_ASSET, "260", Decimal("200"), Decimal("240"), Decimal("40"), Decimal("0"))
    rows += _pair(CashFlowAccountRole.EQUITY_FINANCIAL_INVESTMENT, "110", Decimal("100"), Decimal("120"), Decimal("30"), Decimal("10"))
    rows += _pair(CashFlowAccountRole.BORROWING, "300", Decimal("500"), Decimal("700"), Decimal("100"), Decimal("300"))
    rows.append(_account(CashFlowAccountRole.EQUITY, "500", CashFlowSourceRole.CURRENT_TRIAL_BALANCE, Decimal("50"), Decimal("0"), Decimal("50")))
    rows.append(_account(CashFlowAccountRole.DIVIDEND_PAYABLE, "99101", CashFlowSourceRole.CURRENT_TRIAL_BALANCE, Decimal("0"), Decimal("20"), Decimal("0")))
    bridge_rows = (
        (CashFlowAccountRole.INTEREST_EXPENSE_ACCRUAL, "99110", Decimal("10"), Decimal("0")),
        (CashFlowAccountRole.INTEREST_INCOME_ACCRUAL, "99120", Decimal("0"), Decimal("4")),
        (CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL, "99130", Decimal("0"), Decimal("3")),
        (CashFlowAccountRole.CURRENT_TAX_EXPENSE_ACCRUAL, "99140", Decimal("12"), Decimal("0")),
    )
    for role, code, debit, credit in bridge_rows:
        rows.append(_account(role, code, CashFlowSourceRole.CURRENT_TRIAL_BALANCE, Decimal("0"), debit, credit))
    rows += _pair(CashFlowAccountRole.INTEREST_PAYABLE, "99210", Decimal("5"), Decimal("7"))
    rows += _pair(CashFlowAccountRole.INTEREST_RECEIVABLE, "99220", Decimal("1"), Decimal("2"))
    rows += _pair(CashFlowAccountRole.DIVIDEND_RECEIVABLE, "99230", Decimal("0"), Decimal("1"))
    rows += _pair(CashFlowAccountRole.TAX_PAYABLE, "99240", Decimal("3"), Decimal("5"))
    return tuple(sorted(rows, key=canonical_cash_flow_digest))


def _input(*, evidence=None, net_profit=Decimal("100"), depreciation=Decimal("25"), prior=True):
    evidence = _base_evidence() if evidence is None else tuple(sorted(evidence, key=canonical_cash_flow_digest))
    if not prior:
        evidence = tuple(
            row for row in evidence
            if row.source_role is not CashFlowSourceRole.PRIOR_TRIAL_BALANCE
        )
    components = ()
    payload = []
    if net_profit is not None:
        payload.append(("net_profit", net_profit))
    if depreciation is not None:
        payload.append(("depreciation_and_amortization", depreciation))
    return IndirectCashFlowInput(
        current_period=_period(CURRENT, 2025),
        prior_period=_period(PRIOR, 2024) if prior else None,
        current_balance_sheet=_source(CashFlowSourceRole.CURRENT_BALANCE_SHEET),
        prior_balance_sheet=_source(CashFlowSourceRole.PRIOR_BALANCE_SHEET) if prior else None,
        current_income_statement=_source(CashFlowSourceRole.CURRENT_INCOME_STATEMENT, tuple(payload)),
        current_trial_balance=_source(CashFlowSourceRole.CURRENT_TRIAL_BALANCE),
        prior_trial_balance=_source(CashFlowSourceRole.PRIOR_TRIAL_BALANCE) if prior else None,
        account_evidence=evidence,
        noncash_bridge_components=components,
        account_evidence_bundle_digest=canonical_evidence_bundle_digest(evidence, components),
        opening_account_coverage_complete=True,
        closing_account_coverage_complete=True,
        mapping_registry_version=CASH_FLOW_MAPPING_REGISTRY_VERSION,
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        presentation_policy=presentation_policy_for(CashFlowPresentationProfile.TMS_TFRS_2024_INDIRECT_V1),
    )


def _component(family, kind, *, domain=CashFlowNonCashBridgeDomain.INVESTING_ASSET, amount=Decimal("0")):
    source = _source(CashFlowSourceRole.CURRENT_TRIAL_BALANCE)
    family_digest = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.family_reference_digest(family)
    label = f"{family.value}:{domain.value}:{kind.value}"
    return CashFlowNonCashBridgeComponent(
        component_reference_digest=_digest("component:" + label),
        economic_event_reference_digest=_digest("event:" + label),
        account_family_reference_digest=family_digest,
        account_family_code=family,
        family_balance_basis=(
            CashFlowFamilyBalanceBasis.GROSS_LIABILITY_OBLIGATION
            if family.value == "borrowing_gross"
            else CashFlowFamilyBalanceBasis.NET_CARRYING_ASSET
        ),
        domain=domain,
        bridge_kind=kind,
        source_role=CashFlowSourceRole.CURRENT_TRIAL_BALANCE,
        source_analysis_result_id=source.analysis_result_id,
        same_run_engine_code=None,
        source_canonical_digest=source.canonical_digest,
        source_provenance_digest=source.source_provenance_digest,
        statement_basis=CashFlowStatementBasis.FLOW_INTERVAL,
        coverage_start_date=date(2025, 1, 1),
        coverage_end_date=date(2025, 12, 31),
        applicability=CashFlowApplicability.PROVEN_NOT_APPLICABLE if amount == 0 else CashFlowApplicability.APPLICABLE,
        evidence_kind=CashFlowEvidenceKind.EXACT,
        source_signed_residual_adjustment=amount,
        source_currency_code="TRY",
        source_unit_multiplier=Decimal("1"),
        functional_currency_code="TRY",
        signed_residual_adjustment=amount,
        translation_provenance_digest=None,
        paired_transfer_reference_digest=None,
        supporting_evidence_reference_digests=(),
    )


def _estimated_input():
    rows = tuple(
        replace(
            row,
            source_debit_movement=None,
            source_credit_movement=None,
            normalized_functional_currency_debit_movement=None,
            normalized_functional_currency_credit_movement=None,
        )
        if row.canonical_account_role in {
            CashFlowAccountRole.PPE,
            CashFlowAccountRole.INTANGIBLE_ASSET,
            CashFlowAccountRole.EQUITY_FINANCIAL_INVESTMENT,
            CashFlowAccountRole.BORROWING,
        }
        else row
        for row in _base_evidence()
    )
    investing_kinds = (
        CashFlowNonCashBridgeKind.DEPRECIATION_OR_AMORTIZATION,
        CashFlowNonCashBridgeKind.IMPAIRMENT,
        CashFlowNonCashBridgeKind.REVALUATION,
        CashFlowNonCashBridgeKind.TRANSFER_OR_RECLASSIFICATION,
        CashFlowNonCashBridgeKind.DISPOSAL_GAIN_OR_LOSS,
        CashFlowNonCashBridgeKind.FX_OR_TRANSLATION,
        CashFlowNonCashBridgeKind.NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION,
        CashFlowNonCashBridgeKind.CAPITALIZED_INTEREST,
    )
    financing_kinds = (
        CashFlowNonCashBridgeKind.TRANSFER_OR_RECLASSIFICATION,
        CashFlowNonCashBridgeKind.FX_OR_TRANSLATION,
        CashFlowNonCashBridgeKind.NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION,
        CashFlowNonCashBridgeKind.LEASE_MODIFICATION,
        CashFlowNonCashBridgeKind.DEBT_TO_EQUITY_CONVERSION,
        CashFlowNonCashBridgeKind.CAPITALIZED_INTEREST,
    )
    components = tuple(
        _component(family, kind)
        for family in (
            CashFlowAccountFamilyCode.PPE_NET,
            CashFlowAccountFamilyCode.INTANGIBLE_NET,
            CashFlowAccountFamilyCode.FINANCIAL_INVESTMENT_NET,
        )
        for kind in investing_kinds
    ) + tuple(
        _component(
            CashFlowAccountFamilyCode.BORROWING_GROSS,
            kind,
            domain=CashFlowNonCashBridgeDomain.FINANCING_DEBT,
        )
        for kind in financing_kinds
    )
    rows = tuple(sorted(rows, key=canonical_cash_flow_digest))
    components = tuple(sorted(components, key=canonical_cash_flow_digest))
    base = _input(evidence=rows)
    return replace(
        base,
        noncash_bridge_components=components,
        account_evidence_bundle_digest=canonical_evidence_bundle_digest(rows, components),
    )


def _draft(inputs=None):
    outcome = IndirectCashFlowCoreService().analyze(_input() if inputs is None else inputs)
    assert outcome.success, outcome.error
    return outcome.draft


def _line(draft, code):
    return draft.line_items[list(CashFlowLineCode).index(code)]


def _golden_input(scenario):
    if scenario == "complete_two_period":
        return _input()
    if scenario == "partial_investing_financing":
        excluded = {
            CashFlowAccountRole.PPE,
            CashFlowAccountRole.INTANGIBLE_ASSET,
            CashFlowAccountRole.EQUITY_FINANCIAL_INVESTMENT,
            CashFlowAccountRole.BORROWING,
            CashFlowAccountRole.EQUITY,
            CashFlowAccountRole.DIVIDEND_PAYABLE,
        }
        return _input(evidence=tuple(
            row for row in _base_evidence()
            if row.canonical_account_role not in excluded
        ))
    if scenario == "insufficient_data":
        return _input(prior=False)
    if scenario == "loss_period":
        return _input(net_profit=Decimal("-100"))
    if scenario == "working_capital_reversal":
        rows = []
        for row in _base_evidence():
            if row.account_code == "150" and row.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE:
                row = replace(row, source_balance=Decimal("150"), normalized_functional_currency_balance=Decimal("150"))
            elif row.account_code == "320" and row.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE:
                row = replace(row, source_balance=Decimal("120"), normalized_functional_currency_balance=Decimal("120"))
            rows.append(row)
        return _input(evidence=rows)
    if scenario == "estimated_net_investing":
        return _estimated_input()
    raise AssertionError(f"unknown synthetic golden scenario: {scenario}")


@pytest.mark.parametrize(
    "fixture",
    json.loads(
        (Path(__file__).parent / "data" / "synthetic" / "cash_flow_indirect_core_golden_v1.json")
        .read_text(encoding="utf-8")
    )["scenarios"],
    ids=lambda fixture: fixture["scenario"],
)
def test_versioned_synthetic_indirect_core_golden_fixtures(fixture):
    draft = _draft(_golden_input(fixture["scenario"]))
    for line_code, expected in fixture["expected_lines"].items():
        actual = _line(draft, CashFlowLineCode(line_code)).canonical_amount
        assert actual == (None if expected is None else Decimal(expected))


def test_complete_two_period_indirect_core_golden_amounts():
    draft = _draft()
    expected = {
        CashFlowLineCode.NET_PROFIT: Decimal("100.00"),
        CashFlowLineCode.DEPRECIATION_AND_AMORTIZATION: Decimal("25.00"),
        CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL: Decimal("-15.00"),
        CashFlowLineCode.OPERATING_CASH_FLOW: Decimal("115.00"),
        CashFlowLineCode.INVESTING_CASH_FLOW: Decimal("-135.00"),
        CashFlowLineCode.FINANCING_CASH_FLOW: Decimal("222.00"),
        CashFlowLineCode.FREE_CASH_FLOW: Decimal("-25.00"),
        CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS: Decimal("1000.00"),
        CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS: Decimal("1200.00"),
    }
    assert {code: _line(draft, code).canonical_amount for code in expected} == expected
    assert tuple(item.line_code for item in draft.line_items) == CASH_FLOW_LINE_ITEM_MANIFEST_V1


@pytest.mark.parametrize(
    ("code", "expected"),
    (
        (CashFlowLineCode.INVENTORY_MOVEMENT, Decimal("-50.00")),
        (CashFlowLineCode.TRADE_RECEIVABLES_MOVEMENT, Decimal("20.00")),
        (CashFlowLineCode.OTHER_OPERATING_ASSET_MOVEMENT, Decimal("-10.00")),
        (CashFlowLineCode.TRADE_PAYABLES_MOVEMENT, Decimal("30.00")),
        (CashFlowLineCode.OTHER_OPERATING_LIABILITY_MOVEMENT, Decimal("-5.00")),
    ),
)
def test_working_capital_signs(code, expected):
    assert _line(_draft(), code).canonical_amount == expected


def test_working_capital_asset_and_liability_property_reversal():
    base = list(_base_evidence())
    changed = []
    for row in base:
        if row.account_code == "150" and row.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE:
            changed.append(replace(row, source_balance=Decimal("150"), normalized_functional_currency_balance=Decimal("150")))
        elif row.account_code == "320" and row.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE:
            changed.append(replace(row, source_balance=Decimal("120"), normalized_functional_currency_balance=Decimal("120")))
        else:
            changed.append(row)
    draft = _draft(_input(evidence=changed))
    assert _line(draft, CashFlowLineCode.INVENTORY_MOVEMENT).canonical_amount == Decimal("50.00")
    assert _line(draft, CashFlowLineCode.TRADE_PAYABLES_MOVEMENT).canonical_amount == Decimal("-30.00")


@pytest.mark.parametrize("missing_role", (CashFlowAccountRole.INVENTORY, CashFlowAccountRole.OPERATING_PAYABLE))
@pytest.mark.parametrize("missing_source_role", (CashFlowSourceRole.PRIOR_TRIAL_BALANCE, CashFlowSourceRole.CURRENT_TRIAL_BALANCE))
def test_missing_period_balance_never_becomes_zero(missing_role, missing_source_role):
    rows = tuple(row for row in _base_evidence() if not (row.canonical_account_role is missing_role and row.source_role is missing_source_role))
    draft = _draft(_input(evidence=rows))
    code = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.behavior_for(missing_role).candidate_line_codes[0]
    assert _line(draft, code).canonical_amount is None
    assert _line(draft, CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL).canonical_amount is None


def test_cash_and_unclassified_accounts_do_not_change_working_capital():
    baseline = _line(_draft(), CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL).canonical_amount
    rows = list(_base_evidence())
    rows += _pair(CashFlowAccountRole.UNCLASSIFIED, "999999", Decimal("500"), Decimal("999"))
    assert _line(_draft(_input(evidence=rows)), CashFlowLineCode.WORKING_CAPITAL_MOVEMENT_TOTAL).canonical_amount == baseline


def test_restricted_cash_is_classified_per_period_and_excluded_from_endpoint_total():
    rows = []
    for row in _base_evidence():
        if row.account_code == "100" and row.source_role is CashFlowSourceRole.CURRENT_TRIAL_BALANCE:
            row = replace(
                row,
                is_restricted=True,
                restriction_preserves_cash_nature=False,
            )
        rows.append(row)
    draft = _draft(_input(evidence=rows))
    disclosure = draft.cash_availability_disclosures[0]
    assert tuple(item.classification for item in disclosure.observations) == (
        CashAvailabilityClassification.UNRESTRICTED_INCLUDED,
        CashAvailabilityClassification.RESTRICTED_EXCLUDED,
    )
    assert _line(draft, CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS).canonical_amount == Decimal("1000.00")
    assert _line(draft, CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS).canonical_amount == Decimal("0.00")


def test_missing_cash_ground_stops_all_monetary_core_calculation():
    rows = tuple(
        row for row in _base_evidence()
        if row.canonical_account_role is not CashFlowAccountRole.CASH_ON_HAND
    )
    draft = _draft(_input(evidence=rows))
    assert all(item.canonical_amount is None for item in draft.line_items)
    assert any(issue.code is CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE for issue in draft.warnings)


def test_loss_period_preserves_negative_net_profit_sign():
    draft = _draft(_input(net_profit=Decimal("-100")))
    assert _line(draft, CashFlowLineCode.NET_PROFIT).canonical_amount == Decimal("-100.00")


def test_missing_net_profit_produces_minimum_data_draft_without_zero():
    draft = _draft(_input(net_profit=None))
    assert _line(draft, CashFlowLineCode.NET_PROFIT).canonical_amount is None
    assert any(issue.code is CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE for issue in draft.warnings)


def test_missing_prior_period_produces_insufficient_draft():
    draft = _draft(_input(prior=False))
    assert all(item.canonical_amount is None for item in draft.line_items)
    assert any(issue.code is CashFlowWarningCode.MINIMUM_DATA_INCOMPLETE for issue in draft.warnings)


def test_financing_expenses_payload_is_not_interest_paid():
    inputs = _input()
    payload = CashFlowJsonObject(items=(("depreciation_and_amortization", Decimal("25")), ("financing_expenses", Decimal("999")), ("net_profit", Decimal("100"))))
    inputs = replace(inputs, current_income_statement=replace(inputs.current_income_statement, result_payload=payload))
    assert _line(_draft(inputs), CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID).canonical_amount == Decimal("-8.00")


def test_unsupported_provision_payload_is_not_silently_added_back():
    inputs = _input()
    payload = CashFlowJsonObject(items=(
        ("depreciation_and_amortization", Decimal("25")),
        ("net_profit", Decimal("100")),
        ("provision_expense", Decimal("999")),
    ))
    inputs = replace(inputs, current_income_statement=replace(inputs.current_income_statement, result_payload=payload))
    assert _line(_draft(inputs), CashFlowLineCode.OTHER_PROVEN_NON_CASH_ADJUSTMENTS).canonical_amount == Decimal("0.00")


@pytest.mark.parametrize(
    ("code", "expected"),
    (
        (CashFlowLineCode.PROVEN_PPE_ACQUISITIONS, Decimal("-100.00")),
        (CashFlowLineCode.PROVEN_PPE_DISPOSALS, Decimal("20.00")),
        (CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS, Decimal("-40.00")),
        (CashFlowLineCode.PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS, Decimal("-20.00")),
        (CashFlowLineCode.PROVEN_BORROWING_PROCEEDS, Decimal("300.00")),
        (CashFlowLineCode.PROVEN_DEBT_REPAYMENTS, Decimal("-100.00")),
        (CashFlowLineCode.PROVEN_EQUITY_CONTRIBUTIONS, Decimal("50.00")),
        (CashFlowLineCode.PROVEN_DIVIDENDS_PAID, Decimal("-20.00")),
    ),
)
def test_authoritative_investing_and_financing_movements(code, expected):
    assert _line(_draft(), code).canonical_amount == expected


def test_noncash_debt_conversion_is_not_a_cash_contributor():
    inputs = _estimated_input()
    components = tuple(sorted([
            _component(
                component.account_family_code,
                component.bridge_kind,
                domain=component.domain,
                amount=Decimal("-50"),
            )
            if component.bridge_kind is CashFlowNonCashBridgeKind.DEBT_TO_EQUITY_CONVERSION
            else component
        for component in inputs.noncash_bridge_components
    ], key=canonical_cash_flow_digest))
    inputs = replace(
        inputs,
        noncash_bridge_components=components,
        account_evidence_bundle_digest=canonical_evidence_bundle_digest(inputs.account_evidence, components),
    )
    draft = _draft(inputs)
    assert _line(draft, CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT).canonical_amount == Decimal("250.00")
    assert _line(draft, CashFlowLineCode.PROVEN_BORROWING_PROCEEDS).canonical_amount is None
    assert _line(draft, CashFlowLineCode.PROVEN_DEBT_REPAYMENTS).canonical_amount is None


def test_interest_tax_and_dividend_accrual_bridges_do_not_double_count():
    draft = _draft()
    expected = {
        CashFlowLineCode.INTEREST_EXPENSE_ACCRUAL_REVERSAL: Decimal("10.00"),
        CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID: Decimal("-8.00"),
        CashFlowLineCode.INTEREST_INCOME_ACCRUAL_REVERSAL: Decimal("-4.00"),
        CashFlowLineCode.AUTHORITATIVE_INTEREST_RECEIVED: Decimal("3.00"),
        CashFlowLineCode.DIVIDEND_INCOME_ACCRUAL_REVERSAL: Decimal("-3.00"),
        CashFlowLineCode.AUTHORITATIVE_DIVIDENDS_RECEIVED: Decimal("2.00"),
        CashFlowLineCode.CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL: Decimal("12.00"),
        CashFlowLineCode.AUTHORITATIVE_INCOME_TAX_PAID: Decimal("-10.00"),
    }
    assert {code: _line(draft, code).canonical_amount for code in expected} == expected


def test_free_cash_flow_excludes_financial_investment_and_disposals():
    draft = _draft()
    assert _line(draft, CashFlowLineCode.FREE_CASH_FLOW).canonical_amount == Decimal("-25.00")


def test_unavailable_capex_makes_free_cash_flow_unavailable():
    rows = tuple(row for row in _base_evidence() if row.canonical_account_role is not CashFlowAccountRole.INTANGIBLE_ASSET)
    draft = _draft(_input(evidence=rows))
    assert _line(draft, CashFlowLineCode.PROVEN_INTANGIBLE_ACQUISITIONS).canonical_amount is None
    assert _line(draft, CashFlowLineCode.FREE_CASH_FLOW).canonical_amount is None


def test_closed_bridge_ledger_produces_estimated_net_investing_and_debt_only():
    draft = _draft(_estimated_input())
    investing = _line(draft, CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT)
    debt = _line(draft, CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT)
    assert investing.canonical_amount == Decimal("-140.00")
    assert debt.canonical_amount == Decimal("200.00")
    assert investing.evidence_kind is CashFlowEvidenceKind.ESTIMATED
    assert debt.evidence_kind is CashFlowEvidenceKind.ESTIMATED
    assert _line(draft, CashFlowLineCode.PROVEN_PPE_ACQUISITIONS).canonical_amount is None
    assert _line(draft, CashFlowLineCode.PROVEN_BORROWING_PROCEEDS).canonical_amount is None
    assert _line(draft, CashFlowLineCode.FREE_CASH_FLOW).canonical_amount is None


def test_unknown_bridge_component_makes_estimate_unavailable():
    inputs = _estimated_input()
    components = tuple(
        component
        for component in inputs.noncash_bridge_components
        if not (
            component.account_family_code is CashFlowAccountFamilyCode.BORROWING_GROSS
            and component.bridge_kind is CashFlowNonCashBridgeKind.FX_OR_TRANSLATION
        )
    )
    inputs = replace(
        inputs,
        noncash_bridge_components=components,
        account_evidence_bundle_digest=canonical_evidence_bundle_digest(inputs.account_evidence, components),
    )
    draft = _draft(inputs)
    assert _line(draft, CashFlowLineCode.ESTIMATED_NET_DEBT_MOVEMENT).canonical_amount is None


def test_family_contra_member_is_netted_once_in_estimated_residual():
    inputs = _estimated_input()
    contra_rows = tuple(
        replace(
            row,
            source_debit_movement=None,
            source_credit_movement=None,
            normalized_functional_currency_debit_movement=None,
            normalized_functional_currency_credit_movement=None,
        )
        for row in _pair(CashFlowAccountRole.NON_CASH_ADJUSTMENT, "257", Decimal("200"), Decimal("225"))
    )
    rows = tuple(sorted(inputs.account_evidence + contra_rows, key=canonical_cash_flow_digest))
    inputs = replace(
        inputs,
        account_evidence=rows,
        account_evidence_bundle_digest=canonical_evidence_bundle_digest(rows, inputs.noncash_bridge_components),
    )
    assert _line(_draft(inputs), CashFlowLineCode.ESTIMATED_NET_INVESTMENT_MOVEMENT).canonical_amount == Decimal("-115.00")


def test_nonzero_unclassified_account_forces_activity_subtotals_unavailable():
    rows = list(_base_evidence())
    rows += _pair(CashFlowAccountRole.UNCLASSIFIED, "999999", Decimal("0"), Decimal("1"))
    draft = _draft(_input(evidence=rows))
    assert all(
        _line(draft, code).canonical_amount is None
        for code in (
            CashFlowLineCode.OPERATING_CASH_FLOW,
            CashFlowLineCode.INVESTING_CASH_FLOW,
            CashFlowLineCode.FINANCING_CASH_FLOW,
        )
    )
    assert any(issue.code is CashFlowWarningCode.ACCOUNT_UNCLASSIFIED for issue in draft.warnings)


def test_unsupported_revaluation_is_not_silently_non_cash_or_other():
    draft = _draft()
    assert all(
        reference.derivation_code.value != "reconciliation_difference"
        for item in draft.line_items
        for reference in item.evidence
    )
    assert _line(draft, CashFlowLineCode.AUTHORITATIVE_FX_EFFECT).canonical_amount is None
    assert _line(draft, CashFlowLineCode.AUTHORITATIVE_RECLASSIFICATION_EFFECT).canonical_amount is None


def test_calculated_net_change_requires_all_activity_fx_and_reclassification_lines():
    draft = _draft()
    assert _line(draft, CashFlowLineCode.CALCULATED_NET_CASH_CHANGE).canonical_amount is None


def test_half_even_and_negative_zero_are_canonical():
    draft = _draft(_input(net_profit=Decimal("1.005"), depreciation=Decimal("0")))
    assert _line(draft, CashFlowLineCode.NET_PROFIT).canonical_amount == Decimal("1.00")
    zero = _line(draft, CashFlowLineCode.DEPRECIATION_AND_AMORTIZATION).canonical_amount
    assert zero == Decimal("0.00") and not zero.is_signed()


def test_same_input_same_draft_digest_and_input_order_independence():
    inputs = _input()
    first = _draft(inputs)
    second = _draft(inputs)
    assert computation_draft_digest(first) == computation_draft_digest(second)
    assert computation_draft_digest(_draft(_input(evidence=reversed(inputs.account_evidence)))) == computation_draft_digest(first)
    reordered = tuple(reversed(inputs.account_evidence))
    with pytest.raises(CashFlowContractError):
        replace(inputs, account_evidence=reordered)


def test_account_evidence_must_bind_to_the_exact_source_snapshot():
    rows = list(_base_evidence())
    rows[0] = replace(rows[0], source_provenance_digest=_digest("spoofed-provenance"))
    rows = tuple(sorted(rows, key=canonical_cash_flow_digest))
    inputs = replace(
        _input(),
        account_evidence=rows,
        account_evidence_bundle_digest=canonical_evidence_bundle_digest(rows, ()),
    )
    outcome = IndirectCashFlowCoreService().analyze(inputs)
    assert not outcome.success
    assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT


def test_bridge_component_must_bind_to_the_exact_source_snapshot():
    inputs = _estimated_input()
    components = list(inputs.noncash_bridge_components)
    components[0] = replace(components[0], source_canonical_digest=_digest("spoofed-source"))
    components = tuple(sorted(components, key=canonical_cash_flow_digest))
    inputs = replace(
        inputs,
        noncash_bridge_components=components,
        account_evidence_bundle_digest=canonical_evidence_bundle_digest(inputs.account_evidence, components),
    )
    outcome = IndirectCashFlowCoreService().analyze(inputs)
    assert not outcome.success
    assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT


def test_decimal_context_does_not_change_result():
    with localcontext() as context:
        context.prec = 8
        low = computation_draft_digest(_draft())
    with localcontext() as context:
        context.prec = 50
        high = computation_draft_digest(_draft())
    assert low == high


def test_duplicate_account_evidence_is_fail_closed():
    rows = _base_evidence()
    duplicate = tuple(sorted(rows + (rows[0],), key=canonical_cash_flow_digest))
    with pytest.raises(CashFlowContractError):
        _input(evidence=duplicate)


def test_tampered_bundle_digest_is_safe_integrity_failure():
    outcome = IndirectCashFlowCoreService().analyze(replace(_input(), account_evidence_bundle_digest="f" * 64))
    assert not outcome.success
    assert outcome.error.code is CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT
    assert "f" * 64 not in repr(outcome)


def test_wrong_input_type_is_safe_invalid_contract():
    outcome = IndirectCashFlowCoreService().analyze({"net_profit": "secret"})
    assert not outcome.success
    assert outcome.error.code is CashFlowErrorCode.INVALID_CONTRACT
    assert "secret" not in repr(outcome.error)


def test_core_values_are_immutable_and_decimal_only():
    outcome = IndirectCashFlowCoreService().analyze(_input())
    with pytest.raises(FrozenInstanceError):
        outcome.success = False
    assert all(item.canonical_amount is None or type(item.canonical_amount) is Decimal for item in outcome.draft.line_items)


def test_final_reconciliation_is_not_performed_in_45d():
    draft = _draft()
    assert _line(draft, CashFlowLineCode.RECONCILIATION_DIFFERENCE).canonical_amount is None
    assert not hasattr(draft, "reconciliation_status")


def test_no_persistence_or_framework_dependency_in_core_modules():
    import ast
    from pathlib import Path
    package = Path(__file__).parents[1] / "app" / "engines" / "cash_flow"
    for name in ("analyzer.py", "calculation.py", "service.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert imports.isdisjoint({"sqlalchemy", "fastapi", "pydantic"})


def test_no_float_or_final_result_in_draft():
    draft = _draft()
    assert "float" not in canonical_cash_flow_digest(draft)
    assert not hasattr(draft, "status")
