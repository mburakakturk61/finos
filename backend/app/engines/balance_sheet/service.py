"""
Milestone 4.2: Balance Sheet Engine orkestrasyon katmanı -- extractor,
trial_balance fallback, analyzer ve reconciliation'ı birleştiren tek giriş
noktası `analyze_balance_sheet`.

Hibrit kaynak modeli (onaylanan Milestone 4 mimari kararı, B.2 / Alternatif
3): doğrudan belge (`content`) varsa VE ayrıştırılabiliyorsa o AUTHORITATIVE
kaynaktır; `trial_balance_result` bu durumda yalnızca RECONCILIATION için
kullanılır (asla sessizce üzerine yazmaz). Doğrudan belge yoksa veya
ayrıştırılamazsa `trial_balance_result` fallback OLARAK kullanılır.

`app/trial_balance/**`'ten HİÇBİR import YOK.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.engines.balance_sheet.analyzer import (
    compute_horizontal_analysis,
    compute_preliminary_structural_ratios,
    compute_vertical_analysis,
    compute_working_capital,
)
from app.engines.balance_sheet.extractor import (
    BalanceSheetExtractionError,
    extract_balance_sheet_facts,
)
from app.engines.common.calculation_provenance import provenance_list_to_dict
from app.engines.common.canonical_facts import BalanceSheetFacts
from app.engines.common.ratio_formulas import decimal_to_json_safe
from app.engines.common.reconciliation import build_reconciliation_summary, compare_with_tolerance, finding_to_dict
from app.engines.common.trial_balance_fallback import (
    extract_balance_sheet_facts_from_trial_balance,
)
from app.models.enums import AnalysisStatus, SourceMode


ENGINE_VERSION = "1.0.0"

# Reconciliation yalnızca YÜKSEK-SEVİYE toplamlar üzerinde yapılır --
# alt kalem detayı (cash_and_equivalents vb.) trial_balance motorunda hiç
# üretilmediği için karşılaştırılamaz.
RECONCILIATION_FIELDS = ["total_assets", "current_assets", "short_term_liabilities", "equity"]

ALL_FACT_FIELDS = [
    "current_assets", "non_current_assets", "total_assets",
    "short_term_liabilities", "long_term_liabilities", "equity",
    "total_liabilities_and_equity", "cash_and_equivalents", "inventory",
    "trade_receivables", "trade_payables",
]


@dataclass
class BalanceSheetAnalysisOutcome:
    status: AnalysisStatus
    source_mode: SourceMode | None
    result_json: dict[str, Any] | None
    error_message: str | None
    # "fallback_source": trial_balance TEK kaynak olarak kullanıldı (role=
    #   trial_balance_fallback). "reconciliation_reference": doğrudan belge
    #   authoritative, trial_balance yalnızca çapraz doğrulama için kaynak
    #   olarak eklendi (role=supporting_analysis). None: trial_balance hiç
    #   kullanılmadı.
    trial_balance_usage: str | None


def _facts_to_dict(facts: BalanceSheetFacts) -> dict[str, Any]:
    return {field_name: decimal_to_json_safe(getattr(facts, field_name)) for field_name in ALL_FACT_FIELDS}


def _serialize_dict(values: dict[str, Decimal | None]) -> dict[str, Any]:
    return {key: decimal_to_json_safe(value) for key, value in values.items()}


def analyze_balance_sheet(
    *,
    content: bytes | None,
    filename: str | None,
    trial_balance_result: dict[str, Any] | None,
    prior_period_facts: BalanceSheetFacts | None = None,
) -> BalanceSheetAnalysisOutcome:
    warnings: list[dict[str, Any]] = []
    direct_facts: BalanceSheetFacts | None = None
    direct_extraction_warnings: list[str] = []
    direct_extraction_failed_message: str | None = None

    if content is not None:
        try:
            direct_facts, direct_extraction_warnings = extract_balance_sheet_facts(content, filename)
        except BalanceSheetExtractionError as error:
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
            reference_facts = extract_balance_sheet_facts_from_trial_balance(trial_balance_result)
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
        facts = extract_balance_sheet_facts_from_trial_balance(trial_balance_result)
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
        return BalanceSheetAnalysisOutcome(
            status=AnalysisStatus.FAILED,
            source_mode=None,
            result_json=None,
            error_message=message,
            trial_balance_usage=None,
        )

    vertical, vertical_provenance = compute_vertical_analysis(facts)
    horizontal, horizontal_provenance = compute_horizontal_analysis(facts, prior_period_facts)
    working_capital, working_capital_provenance = compute_working_capital(facts)
    structural_ratios, structural_provenance = compute_preliminary_structural_ratios(facts)

    all_provenance = (
        vertical_provenance + horizontal_provenance + working_capital_provenance + structural_provenance
    )

    missing_fields = [
        field_name for field_name in ALL_FACT_FIELDS if getattr(facts, field_name) is None
    ]

    result_json = {
        "engine": "balance_sheet",
        "engine_version": ENGINE_VERSION,
        "analysis_type": "balance_sheet",
        "source_mode": source_mode.value,
        "facts": _facts_to_dict(facts),
        "vertical_analysis": _serialize_dict(vertical),
        "horizontal_analysis": _serialize_dict(horizontal),
        "working_capital": _serialize_dict(working_capital),
        "preliminary_structural_ratios": _serialize_dict(structural_ratios),
        "reconciliation": reconciliation,
        "warnings": warnings,
        "missing_fields": missing_fields,
        "calculation_provenance": provenance_list_to_dict(all_provenance),
    }

    return BalanceSheetAnalysisOutcome(
        status=AnalysisStatus.COMPLETED,
        source_mode=source_mode,
        result_json=result_json,
        error_message=None,
        trial_balance_usage=trial_balance_usage,
    )
