"""Cash Flow aware ratio projection for the additive V3 orchestration path.

The legacy ``analyze_financial_ratios`` entry point remains untouched.  This
module projects a verified ``CashFlowResult`` into the six already-registered
cash-flow ratios without copying their formulas or exposing the source payload.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.engines.cash_flow.contracts import CashFlowResult, canonical_cash_flow_digest
from app.engines.cash_flow.types import (
    CASH_FLOW_MODEL_VERSION,
    CASH_FLOW_SCHEMA_VERSION,
    CashFlowEvidenceKind,
    CashFlowLineCode,
    CashFlowResultStatus,
)
from app.engines.common.calculation_provenance import provenance_to_dict_extended
from app.engines.common.ratio_formulas import (
    ComputationStatus,
    compute_registered_ratio,
    decimal_to_json_safe,
    get_ratio_formula,
)

from .service import (
    _build_facts_dict,
    _reliability_for_category,
    _worse_reliability,
    analyze_financial_ratios,
)


CASH_FLOW_RATIO_CODES_V1 = (
    "operating_cash_flow_margin",
    "free_cash_flow_margin",
    "cash_flow_to_debt",
    "cash_return_on_assets",
    "cash_interest_coverage",
    "operating_cash_flow_ratio",
)

_RESULT_USABLE_STATUSES = {
    CashFlowResultStatus.COMPLETE_RECONCILED,
    CashFlowResultStatus.COMPLETE_UNRECONCILED,
    CashFlowResultStatus.PARTIAL_RECONCILED,
    CashFlowResultStatus.PARTIAL_UNRECONCILED,
}
_EVIDENCE_RELIABILITY = {
    CashFlowEvidenceKind.EXACT: "high",
    CashFlowEvidenceKind.DERIVED: "medium",
    CashFlowEvidenceKind.ESTIMATED: "low",
    CashFlowEvidenceKind.UNAVAILABLE: "not_calculable",
}


@dataclass(frozen=True, repr=False)
class CashFlowRatioFactsV1:
    operating_cash_flow: Decimal | None
    free_cash_flow: Decimal | None
    cash_interest_paid: Decimal | None
    operating_cash_flow_evidence: CashFlowEvidenceKind
    free_cash_flow_evidence: CashFlowEvidenceKind
    cash_interest_paid_evidence: CashFlowEvidenceKind
    status: CashFlowResultStatus
    reconciliation_status: str
    completeness_ratio: Decimal
    policy_version: str
    cash_flow_schema_version: str
    cash_flow_model_version: str
    result_digest: str
    result_reference: str


def project_cash_flow_ratio_facts_v1(result: CashFlowResult) -> CashFlowRatioFactsV1:
    """Map canonical fields only; no cash-flow amount is recomputed here."""

    if type(result) is not CashFlowResult:
        raise TypeError("cash-flow ratio projection requires exact CashFlowResult")
    if (
        result.cash_flow_schema_version != CASH_FLOW_SCHEMA_VERSION
        or result.cash_flow_model_version != CASH_FLOW_MODEL_VERSION
    ):
        raise ValueError("unsupported Cash Flow result version")

    lines = {item.line_code: item for item in result.line_items}
    operating = lines[CashFlowLineCode.OPERATING_CASH_FLOW]
    free = lines[CashFlowLineCode.FREE_CASH_FLOW]
    interest = lines[CashFlowLineCode.AUTHORITATIVE_INTEREST_PAID]
    if operating.canonical_amount != result.operating_cash_flow:
        raise ValueError("operating cash-flow summary/evidence mismatch")
    if free.canonical_amount != result.free_cash_flow:
        raise ValueError("free cash-flow summary/evidence mismatch")

    usable = result.status in _RESULT_USABLE_STATUSES
    digest = canonical_cash_flow_digest(result)
    return CashFlowRatioFactsV1(
        operating_cash_flow=operating.canonical_amount if usable else None,
        free_cash_flow=free.canonical_amount if usable else None,
        cash_interest_paid=interest.canonical_amount if usable else None,
        operating_cash_flow_evidence=(
            operating.evidence_kind if usable else CashFlowEvidenceKind.UNAVAILABLE
        ),
        free_cash_flow_evidence=(
            free.evidence_kind if usable else CashFlowEvidenceKind.UNAVAILABLE
        ),
        cash_interest_paid_evidence=(
            interest.evidence_kind if usable else CashFlowEvidenceKind.UNAVAILABLE
        ),
        status=result.status,
        reconciliation_status=result.reconciliation_status.value,
        completeness_ratio=result.completeness.available_ratio,
        policy_version=result.policy_version,
        cash_flow_schema_version=result.cash_flow_schema_version,
        cash_flow_model_version=result.cash_flow_model_version,
        result_digest=digest,
        result_reference=f"cash-flow-result:sha256:{digest}",
    )


def _cash_evidence_for_ratio(code: str, facts: CashFlowRatioFactsV1) -> tuple[CashFlowEvidenceKind, ...]:
    if code == "free_cash_flow_margin":
        return (facts.free_cash_flow_evidence,)
    if code == "cash_interest_coverage":
        return (facts.operating_cash_flow_evidence, facts.cash_interest_paid_evidence)
    return (facts.operating_cash_flow_evidence,)


def _base_reliability(
    code: str,
    balance_sheet_result,
    income_statement_result,
    average_meta,
) -> str:
    if code in {"operating_cash_flow_margin", "free_cash_flow_margin"}:
        return _reliability_for_category(
            "profitability", balance_sheet_result, income_statement_result
        )
    if code == "cash_interest_coverage":
        return "high"
    base = _reliability_for_category(
        "liquidity", balance_sheet_result, income_statement_result
    )
    if code == "cash_return_on_assets" and "average_total_assets" in average_meta:
        return _worse_reliability(base, average_meta["average_total_assets"][0])
    return base


def _ratio_warning(evidence: tuple[CashFlowEvidenceKind, ...], *, missing_cash: bool):
    if missing_cash:
        return ({
            "code": "CASH_FLOW_INPUT_UNAVAILABLE",
            "severity": "medium",
            "message": "Gerekli kanonik nakit akışı alanı kullanılamıyor.",
        },)
    if CashFlowEvidenceKind.ESTIMATED in evidence:
        return ({
            "code": "CASH_FLOW_ESTIMATED_INPUT",
            "severity": "medium",
            "message": "Oran, tahmini kanıt taşıyan nakit akışı girdisi içeriyor.",
        },)
    return ()


def analyze_financial_ratios_v3(
    *,
    balance_sheet_result,
    income_statement_result,
    prior_period_balance_sheet_result=None,
    prior_period_income_statement_result=None,
    period_start_date=None,
    period_end_date=None,
    period_months_covered: int | None = None,
    cash_flow_result: CashFlowResult | None = None,
):
    """Run the frozen ratio service, then replace only its cash-flow category."""

    legacy = analyze_financial_ratios(
        balance_sheet_result=balance_sheet_result,
        income_statement_result=income_statement_result,
        prior_period_balance_sheet_result=prior_period_balance_sheet_result,
        prior_period_income_statement_result=prior_period_income_statement_result,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        period_months_covered=period_months_covered,
    )
    if cash_flow_result is None:
        return legacy

    cash = project_cash_flow_ratio_facts_v1(cash_flow_result)
    values, _warnings, average_meta = _build_facts_dict(
        balance_sheet_result,
        income_statement_result,
        prior_period_balance_sheet_result=prior_period_balance_sheet_result,
        prior_period_income_statement_result=prior_period_income_statement_result,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        period_months_covered=period_months_covered,
    )
    values["operating_cash_flow"] = cash.operating_cash_flow
    values["free_cash_flow"] = cash.free_cash_flow
    # The registry key is frozen.  In the V3 overlay it is populated only by
    # the authoritative cash-payment line; IS financing expense is never used
    # as a fallback and the signed canonical amount is preserved.
    values["financing_expenses"] = cash.cash_interest_paid

    ratios = {}
    provenance_by_metric = {
        item["metric"]: item for item in legacy["calculation_provenance"]
    }
    for code in CASH_FLOW_RATIO_CODES_V1:
        metadata = get_ratio_formula(code)
        if metadata is None or metadata.category != "cash_flow":
            raise ValueError("cash-flow ratio registry manifest mismatch")
        evidence = _cash_evidence_for_ratio(code, cash)
        cash_reliability = "high"
        for kind in evidence:
            cash_reliability = _worse_reliability(
                cash_reliability, _EVIDENCE_RELIABILITY[kind]
            )
        reliability = _worse_reliability(
            cash_reliability,
            _base_reliability(
                code, balance_sheet_result, income_statement_result, average_meta
            ),
        )
        outcome = compute_registered_ratio(code, values, reliability=reliability)
        cash_fields = (
            ("free_cash_flow",)
            if code == "free_cash_flow_margin"
            else ("operating_cash_flow", "financing_expenses")
            if code == "cash_interest_coverage"
            else ("operating_cash_flow",)
        )
        missing_cash = any(name in outcome.missing_inputs for name in cash_fields)
        warning = _ratio_warning(evidence, missing_cash=missing_cash)
        if warning:
            outcome = replace(outcome, warnings=outcome.warnings + warning)
        entry = {
            "value": decimal_to_json_safe(outcome.value),
            "unit": metadata.unit,
            "status": outcome.status.value,
            "reliability": outcome.reliability,
            "missing_inputs": list(outcome.missing_inputs),
            "warnings": list(outcome.warnings),
            "cash_flow_provenance": {
                "result_digest": cash.result_digest,
                "result_reference": cash.result_reference,
                "status": cash.status.value,
                "evidence_levels": [item.value for item in evidence],
                "completeness_ratio": str(cash.completeness_ratio),
                "reconciliation_status": cash.reconciliation_status,
                "policy_version": cash.policy_version,
                "cash_flow_schema_version": cash.cash_flow_schema_version,
                "cash_flow_model_version": cash.cash_flow_model_version,
            },
        }
        if code == "cash_return_on_assets" and "average_total_assets" in average_meta:
            entry["calculation_basis"] = average_meta["average_total_assets"][1]
        ratios[code] = entry
        provenance_by_metric[code] = provenance_to_dict_extended(outcome.provenance)

    calculated = sum(
        item["status"] == ComputationStatus.CALCULATED.value for item in ratios.values()
    )
    legacy["categories"]["cash_flow"] = {
        "status": (
            "calculated" if calculated == len(ratios)
            else "not_calculable" if calculated == 0
            else "partial"
        ),
        "ratios": ratios,
    }
    legacy["calculation_provenance"] = [
        provenance_by_metric[item["metric"]]
        for item in legacy["calculation_provenance"]
    ]
    legacy["cash_flow_dependency"] = {
        "result_digest": cash.result_digest,
        "result_reference": cash.result_reference,
        "status": cash.status.value,
        "policy_version": cash.policy_version,
        "cash_flow_schema_version": cash.cash_flow_schema_version,
        "cash_flow_model_version": cash.cash_flow_model_version,
    }
    return legacy
