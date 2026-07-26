"""
Milestone 4.2: Income Statement Engine orkestrasyon katmanı -- extractor,
trial_balance fallback, analyzer (EBIT/EBITDA dahil) ve reconciliation'ı
birleştiren tek giriş noktası `analyze_income_statement`.

Hibrit kaynak modeli `app.engines.balance_sheet.service` ile AYNI (bkz. o
dosyanın docstring'i). `app/trial_balance/**`'ten HİÇBİR import YOK.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.engines.common.calculation_provenance import provenance_list_to_dict
from app.engines.common.canonical_facts import IncomeStatementFacts
from app.engines.common.ratio_formulas import decimal_to_json_safe
from app.engines.common.reconciliation import build_reconciliation_summary, compare_with_tolerance, finding_to_dict
from app.engines.common.trial_balance_fallback import (
    extract_income_statement_facts_from_trial_balance,
)
from app.engines.income_statement.analyzer import (
    compute_horizontal_analysis,
    compute_margins,
    compute_vertical_analysis,
    resolve_ebit,
    resolve_ebitda,
)
from app.engines.income_statement.extractor import (
    IncomeStatementExtractionError,
    extract_income_statement_facts,
)
from app.models.enums import AnalysisStatus, SourceMode


ENGINE_VERSION = "1.0.0"

RECONCILIATION_FIELDS = ["net_sales", "gross_profit", "operating_profit"]

ALL_FACT_FIELDS = [
    "gross_sales", "sales_deductions", "net_sales", "cost_of_sales",
    "gross_profit", "operating_expenses", "other_operating_income",
    "other_operating_expenses", "operating_profit",
    "depreciation_and_amortization", "ebit", "ebitda", "financing_expenses",
    "extraordinary_income", "extraordinary_expenses", "profit_before_tax",
    "net_profit",
]


@dataclass
class IncomeStatementAnalysisOutcome:
    status: AnalysisStatus
    source_mode: SourceMode | None
    result_json: dict[str, Any] | None
    error_message: str | None
    trial_balance_usage: str | None  # "fallback_source" | "reconciliation_reference" | None


def _facts_to_dict(facts: IncomeStatementFacts, ebit: Decimal | None, ebitda: Decimal | None) -> dict[str, Any]:
    values = {field_name: getattr(facts, field_name) for field_name in ALL_FACT_FIELDS}
    values["ebit"] = ebit
    values["ebitda"] = ebitda
    return {key: decimal_to_json_safe(value) for key, value in values.items()}


def _serialize_dict(values: dict[str, Decimal | None]) -> dict[str, Any]:
    return {key: decimal_to_json_safe(value) for key, value in values.items()}


def analyze_income_statement(
    *,
    content: bytes | None,
    filename: str | None,
    trial_balance_result: dict[str, Any] | None,
    prior_period_facts: IncomeStatementFacts | None = None,
) -> IncomeStatementAnalysisOutcome:
    warnings: list[dict[str, Any]] = []
    direct_facts: IncomeStatementFacts | None = None
    direct_extraction_warnings: list[str] = []
    direct_extraction_failed_message: str | None = None

    if content is not None:
        try:
            direct_facts, direct_extraction_warnings = extract_income_statement_facts(content, filename)
        except IncomeStatementExtractionError as error:
            direct_extraction_failed_message = str(error)

    reconciliation: dict[str, Any] = build_reconciliation_summary(
        performed=False, compared_against=None, findings=[]
    )
    trial_balance_usage: str | None = None

    if direct_facts is not None:
        source_mode = SourceMode.DIRECT_DOCUMENT
        facts = direct_facts
        for message in direct_extraction_warnings:
            warnings.append({"code": "FIELD_NOT_DETECTED", "severity": "warning", "message": message})

        if trial_balance_result is not None:
            reference_facts = extract_income_statement_facts_from_trial_balance(trial_balance_result)
            findings = []
            for field_name in RECONCILIATION_FIELDS:
                finding = compare_with_tolerance(
                    compared_field=field_name,
                    direct_value=getattr(facts, field_name),
                    reference_value=getattr(reference_facts, field_name),
                )
                if finding is not None:
                    findings.append(finding)
                    warnings.append(finding_to_dict(finding))
            reconciliation = build_reconciliation_summary(
                performed=True, compared_against="trial_balance", findings=findings
            )
            trial_balance_usage = "reconciliation_reference"

    elif trial_balance_result is not None:
        source_mode = SourceMode.TRIAL_BALANCE_DERIVED
        facts = extract_income_statement_facts_from_trial_balance(trial_balance_result)
        trial_balance_usage = "fallback_source"
        if direct_extraction_failed_message:
            warnings.append(
                {
                    "code": "DIRECT_EXTRACTION_FAILED_USED_FALLBACK",
                    "severity": "warning",
                    "message": (
                        "Doğrudan belge ayrıştırılamadı; mizandan türetilen "
                        "sonuç fallback olarak kullanıldı."
                    ),
                }
            )
    else:
        message = (
            direct_extraction_failed_message
            or "Doğrudan belge sağlanmadı ve trial_balance fallback bulunamadı."
        )
        return IncomeStatementAnalysisOutcome(
            status=AnalysisStatus.FAILED,
            source_mode=None,
            result_json=None,
            error_message=message,
            trial_balance_usage=None,
        )

    ebit, ebit_provenance, ebit_warning = resolve_ebit(facts)
    if ebit_warning is not None:
        warnings.append(ebit_warning)

    ebitda, ebitda_provenance = resolve_ebitda(ebit, facts.depreciation_and_amortization)

    margins, margins_provenance = compute_margins(facts, ebit, ebitda)
    vertical, vertical_provenance = compute_vertical_analysis(facts)
    horizontal, horizontal_provenance = compute_horizontal_analysis(facts, prior_period_facts)

    all_provenance = (
        [ebit_provenance, ebitda_provenance]
        + margins_provenance
        + vertical_provenance
        + horizontal_provenance
    )

    missing_fields = [
        field_name for field_name in ALL_FACT_FIELDS
        if field_name not in ("ebit", "ebitda") and getattr(facts, field_name) is None
    ]
    if ebit is None:
        missing_fields.append("ebit")
    if ebitda is None:
        missing_fields.append("ebitda")

    result_json = {
        "engine": "income_statement",
        "engine_version": ENGINE_VERSION,
        "analysis_type": "income_statement",
        "source_mode": source_mode.value,
        "facts": _facts_to_dict(facts, ebit, ebitda),
        "vertical_analysis": _serialize_dict(vertical),
        "horizontal_analysis": _serialize_dict(horizontal),
        "margins": _serialize_dict(margins),
        "reconciliation": reconciliation,
        "warnings": warnings,
        "missing_fields": missing_fields,
        "calculation_provenance": provenance_list_to_dict(all_provenance),
    }

    return IncomeStatementAnalysisOutcome(
        status=AnalysisStatus.COMPLETED,
        source_mode=source_mode,
        result_json=result_json,
        error_message=None,
        trial_balance_usage=trial_balance_usage,
    )
