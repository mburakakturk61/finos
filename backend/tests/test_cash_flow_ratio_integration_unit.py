from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.engines.cash_flow import (
    CashFlowEvidenceKind,
    CashFlowLineCode,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
    canonical_cash_flow_digest,
    canonical_policy_bundle_digest,
)
from app.engines.analysis_orchestrator_v3.fingerprint import compute_engine_input_fingerprint_v3
from app.engines.analysis_orchestrator_v3.types import OrchestrationEngineCodeV3 as E
from app.engines.common.ratio_formulas import RATIO_REGISTRY, get_ratio_formula
from app.engines.financial_ratios.cash_flow_integration import (
    CASH_FLOW_RATIO_CODES_V1,
    analyze_financial_ratios_v3,
    project_cash_flow_ratio_facts_v1,
)
from app.engines.financial_ratios.service import analyze_financial_ratios

from test_cash_flow_contracts_unit import _line, _result
from test_cash_flow_orchestration_v3_unit import _context, _request


FIXTURE = json.loads(
    (Path(__file__).parent / "data/synthetic/cash_flow_ratio_integration_golden_v1.json").read_text()
)
BS = {
    "source_mode": "direct_document",
    "facts": {
        "total_assets": 200,
        "short_term_liabilities": 40,
        "long_term_liabilities": 60,
    },
}
IS = {"source_mode": "direct_document", "facts": {"net_sales": 240}}


def _cash_result(*, status=CashFlowResultStatus.COMPLETE_RECONCILED, estimated=False):
    source = _result(
        status=status,
        opening=Decimal("100.00"),
        closing=Decimal("220.00"),
        operating=Decimal("120.00"),
        difference=Decimal("0.00"),
        estimated_code=(CashFlowLineCode.OPERATING_CASH_FLOW if estimated else None),
    )
    lines = tuple(
        _line(
            item.line_code,
            amount=Decimal("-10.00"),
            kind=CashFlowEvidenceKind.EXACT,
        )
        if item.line_code is CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID
        else item
        for item in source.line_items
    )
    return replace(source, line_items=lines)


def _without_free_cash_flow(source):
    unavailable = {
        CashFlowLineCode.PROVEN_PPE_ACQUISITIONS,
        CashFlowLineCode.FREE_CASH_FLOW,
    }
    lines = tuple(
        _line(item.line_code, amount=None, kind=CashFlowEvidenceKind.UNAVAILABLE)
        if item.line_code in unavailable
        else item
        for item in source.line_items
    )
    completeness = replace(
        source.completeness,
        optional_analytics_available_count=0,
        optional_analytics_unavailable_count=1,
    )
    return replace(
        source, line_items=lines, free_cash_flow=None, completeness=completeness
    )


def _without_interest(source):
    lines = tuple(
        _line(item.line_code, amount=None, kind=CashFlowEvidenceKind.UNAVAILABLE)
        if item.line_code is CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID
        else item
        for item in source.line_items
    )
    return replace(source, line_items=lines)


def _ratio_result(source, *, bs=BS, inc=IS):
    return analyze_financial_ratios_v3(
        balance_sheet_result=bs,
        income_statement_result=inc,
        cash_flow_result=source,
    )


def test_exact_six_code_manifest_and_formula_registry_are_unchanged():
    assert list(CASH_FLOW_RATIO_CODES_V1) == FIXTURE["ratio_codes"]
    assert len(RATIO_REGISTRY) == len(set(RATIO_REGISTRY)) == 57
    assert tuple(
        (
            code,
            get_ratio_formula(code).calculation_strategy,
            get_ratio_formula(code).numerator_fields,
            get_ratio_formula(code).denominator_fields,
        )
        for code in CASH_FLOW_RATIO_CODES_V1
    ) == (
        ("operating_cash_flow_margin", "sum_division", ("operating_cash_flow",), ("net_sales",)),
        ("free_cash_flow_margin", "sum_division", ("free_cash_flow",), ("net_sales",)),
        ("cash_flow_to_debt", "sum_division", ("operating_cash_flow",), ("total_liabilities",)),
        ("cash_return_on_assets", "sum_division", ("operating_cash_flow",), ("average_total_assets",)),
        ("cash_interest_coverage", "sum_division", ("operating_cash_flow",), ("financing_expenses",)),
        ("operating_cash_flow_ratio", "sum_division", ("operating_cash_flow",), ("short_term_liabilities",)),
    )


def test_complete_projection_preserves_decimal_evidence_policy_and_reference():
    source = _cash_result()
    facts = project_cash_flow_ratio_facts_v1(source)
    assert facts.operating_cash_flow == Decimal("120.00")
    assert facts.free_cash_flow == Decimal("120.00")
    assert facts.cash_interest_paid == Decimal("-10.00")
    assert facts.operating_cash_flow_evidence is CashFlowEvidenceKind.EXACT
    assert facts.completeness_ratio == source.completeness.available_ratio
    assert facts.result_digest == canonical_cash_flow_digest(source)
    assert facts.result_reference.endswith(facts.result_digest)
    assert facts.policy_version == source.policy_version


@pytest.mark.parametrize(
    "status",
    (
        CashFlowResultStatus.COMPLETE_RECONCILED,
        CashFlowResultStatus.COMPLETE_UNRECONCILED,
        CashFlowResultStatus.PARTIAL_RECONCILED,
        CashFlowResultStatus.PARTIAL_UNRECONCILED,
    ),
)
def test_result_bearing_statuses_project_available_canonical_fields(status):
    if "unreconciled" in status.value:
        source = _result(
            status=status,
            reconciliation_status=CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL,
            opening=Decimal("0.00"),
            closing=Decimal("0.00"),
            operating=Decimal("-2.00"),
            difference=Decimal("2.00"),
            estimated_code=(CashFlowLineCode.NET_PROFIT if "partial" in status.value else None),
        )
    else:
        source = _result(
            status=status,
            estimated_code=(CashFlowLineCode.NET_PROFIT if "partial" in status.value else None),
        )
    assert project_cash_flow_ratio_facts_v1(source).operating_cash_flow is not None


def test_complete_golden_all_six_calculate_and_keep_exact_provenance():
    body = _ratio_result(_cash_result())
    category = body["categories"]["cash_flow"]
    assert category["status"] == "calculated"
    assert {code: item["value"] for code, item in category["ratios"].items()} == FIXTURE["complete_values"]
    digest = body["cash_flow_dependency"]["result_digest"]
    assert len(digest) == 64
    for code, item in category["ratios"].items():
        assert item["status"] == "calculated", code
        assert item["cash_flow_provenance"]["result_digest"] == digest
        assert "line_items" not in item["cash_flow_provenance"]


def test_partial_result_calculates_subset_and_never_fabricates_free_cash_flow():
    source = _without_free_cash_flow(
        _cash_result(status=CashFlowResultStatus.PARTIAL_RECONCILED, estimated=True)
    )
    ratios = _ratio_result(source)["categories"]["cash_flow"]["ratios"]
    assert ratios["free_cash_flow_margin"]["status"] == FIXTURE["partial_missing_free_cash_flow"]
    assert ratios["free_cash_flow_margin"]["value"] is None
    assert ratios["operating_cash_flow_margin"]["status"] == "calculated"
    assert ratios["operating_cash_flow_margin"]["reliability"] == FIXTURE["estimated_reliability"]
    assert any(
        item["code"] == "CASH_FLOW_ESTIMATED_INPUT"
        for item in ratios["operating_cash_flow_margin"]["warnings"]
    )


def test_insufficient_data_keeps_all_six_missing_input_not_zero():
    source = _result(
        status=CashFlowResultStatus.INSUFFICIENT_DATA,
        reconciliation_status=CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
        opening=None,
        closing=None,
        operating=None,
        difference=None,
    )
    category = _ratio_result(source)["categories"]["cash_flow"]
    assert category["status"] == FIXTURE["insufficient_status"]
    assert all(item["status"] == "missing_input" for item in category["ratios"].values())
    assert all(item["value"] is None for item in category["ratios"].values())


def test_missing_interest_never_falls_back_to_income_statement_financing_expense():
    inc = {"source_mode": "direct_document", "facts": {"net_sales": 240, "financing_expenses": 999}}
    ratios = _ratio_result(_without_interest(_cash_result()), inc=inc)["categories"]["cash_flow"]["ratios"]
    item = ratios["cash_interest_coverage"]
    assert item["status"] == FIXTURE["missing_interest_status"]
    assert item["value"] is None
    assert "financing_expenses" in item["missing_inputs"]


@pytest.mark.parametrize(
    ("code", "missing_fact"),
    (
        ("operating_cash_flow_margin", "net_sales"),
        ("free_cash_flow_margin", "net_sales"),
        ("cash_flow_to_debt", "long_term_liabilities"),
        ("cash_return_on_assets", "total_assets"),
        ("operating_cash_flow_ratio", "short_term_liabilities"),
    ),
)
def test_missing_denominator_is_distinct_from_missing_engine(code, missing_fact):
    bs = {"source_mode": "direct_document", "facts": dict(BS["facts"])}
    inc = {"source_mode": "direct_document", "facts": dict(IS["facts"])}
    bs["facts"].pop(missing_fact, None)
    inc["facts"].pop(missing_fact, None)
    item = _ratio_result(_cash_result(), bs=bs, inc=inc)["categories"]["cash_flow"]["ratios"][code]
    assert item["status"] == "missing_input"
    legacy = analyze_financial_ratios(balance_sheet_result=bs, income_statement_result=inc)
    missing_engine = legacy["categories"]["cash_flow"]["ratios"][code]
    assert missing_engine["status"] == "not_calculable"
    assert any(w["code"] == "ENGINE_DEPENDENCY_NOT_AVAILABLE" for w in missing_engine["warnings"])


@pytest.mark.parametrize("denominator", (Decimal("0"), Decimal("-40")))
def test_zero_and_negative_denominator_keep_existing_formula_policy(denominator):
    bs = {
        "source_mode": "direct_document",
        "facts": {
            "total_assets": 200,
            "short_term_liabilities": denominator,
            "long_term_liabilities": 0,
        },
    }
    item = _ratio_result(_cash_result(), bs=bs)["categories"]["cash_flow"]["ratios"]["operating_cash_flow_ratio"]
    if denominator == 0:
        assert item["status"] == "undefined_zero_denominator" and item["value"] is None
    else:
        assert item["status"] == "calculated" and item["value"] == -3.0


def test_legacy_no_cash_flow_call_is_exactly_unchanged_and_input_order_is_irrelevant():
    expected = analyze_financial_ratios(balance_sheet_result=BS, income_statement_result=IS)
    assert analyze_financial_ratios_v3(
        balance_sheet_result=BS, income_statement_result=IS, cash_flow_result=None
    ) == expected
    reversed_bs = {"facts": dict(reversed(tuple(BS["facts"].items()))), "source_mode": "direct_document"}
    assert _ratio_result(_cash_result(), bs=reversed_bs) == _ratio_result(_cash_result())


def test_failure_outcomes_and_non_contract_payloads_are_not_projected_as_facts():
    with pytest.raises(TypeError):
        project_cash_flow_ratio_facts_v1(object())
    with pytest.raises(TypeError):
        analyze_financial_ratios_v3(
            balance_sheet_result=BS, income_statement_result=IS, cash_flow_result={}
        )


def test_same_canonical_input_is_deterministic_and_raw_payload_is_not_embedded():
    source = _cash_result()
    first = _ratio_result(source)
    second = _ratio_result(source)
    assert first == second
    assert '"line_items"' not in json.dumps(first, sort_keys=True)


def test_ratio_fingerprint_tracks_cash_flow_digest_and_policy_version():
    source = _result()
    changed_versions = {
        "accounting_policy_version": source.accounting_policy_version,
        "cash_equivalent_policy_version": source.cash_equivalent_policy_version,
        "presentation_policy_version": "management/1.0.1",
        "reconciliation_policy_version": source.reconciliation_policy_version,
        "mapping_registry_version": source.mapping_registry_version,
    }
    changed = replace(
        source,
        policy_version=canonical_policy_bundle_digest(**changed_versions),
        **changed_versions,
    )
    request = _request((E.CASH_FLOW, E.RATIO), context=_context())
    upstream = {
        E.FS_BALANCE_SHEET: "b" * 64,
        E.FS_INCOME_STATEMENT: "c" * 64,
        E.CASH_FLOW: canonical_cash_flow_digest(source),
    }
    first = compute_engine_input_fingerprint_v3(E.RATIO, request, upstream)
    second = compute_engine_input_fingerprint_v3(
        E.RATIO,
        request,
        {**upstream, E.CASH_FLOW: canonical_cash_flow_digest(changed)},
    )
    assert first != second
