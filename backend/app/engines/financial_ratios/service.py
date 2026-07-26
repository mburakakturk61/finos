"""
Milestone 4.3A (Ratio Calculation Foundation): Financial Ratio Engine'in
orkestrasyon katmanı -- `analyze_financial_ratios`, Balance Sheet/Income
Statement motorlarının ZATEN ÜRETTİĞİ (kayıtlı) `result_json`'lardan
(YENİDEN HESAPLAMA YOK, B.3) ilk 9 ortak oranı `compute_registered_ratio`
üzerinden üretir.

KAPSAM SINIRI (onaylanan Milestone 4.3A kararı): bu modül yalnızca
liquidity/leverage/profitability kategorilerindeki 9 oranı doldurur.
Kalan 11 kategori (activity/efficiency/growth/investment/cash_flow/market/
banking/ifrs/risk/capital_structure/working_capital) `missing_categories`
altında dürüstçe listelenir -- Milestone 4.3B+'yi bekliyor.

`app/trial_balance/**`'ten HİÇBİR import YOK.
"""

from decimal import Decimal
from typing import Any

from app.engines.common.calculation_provenance import (
    ProvenanceEntry,
    provenance_list_to_dict_extended,
)
from app.engines.common.ratio_derived_facts import compute_total_liabilities
from app.engines.common.ratio_formulas import (
    RATIO_REGISTRY_VERSION,
    ComputationStatus,
    decimal_to_json_safe,
    get_ratio_formula,
    json_safe_to_decimal,
    compute_registered_ratio,
)


ENGINE_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"

# Milestone 4.3A: yalnızca ilk 9 ortak oranın kategorilere gruplanmış hali
# (onaylanan mimari doküman, Bölüm R.5/S). Diğer 11 kategori 4.3B+'yi
# bekliyor -- bkz. `_ALL_CATEGORY_KEYS`/`missing_categories`.
_CATEGORY_RATIO_KEYS: dict[str, tuple[str, ...]] = {
    "liquidity": ("current_ratio", "working_capital_ratio", "net_working_capital"),
    "leverage": ("debt_ratio", "equity_ratio", "debt_to_equity"),
    "profitability": ("gross_profit_margin", "operating_profit_margin", "net_profit_margin"),
}

# Mimari dokümanın (Bölüm C) 14 kategorisinin TAMAMI -- yalnızca üçü
# Milestone 4.3A'da dolu, geri kalanı `missing_categories`'de dürüstçe
# raporlanır.
_ALL_CATEGORY_KEYS: tuple[str, ...] = (
    "liquidity",
    "profitability",
    "activity",
    "leverage",
    "efficiency",
    "growth",
    "investment",
    "cash_flow",
    "market",
    "banking",
    "ifrs",
    "risk",
    "capital_structure",
    "working_capital",
)

_BS_RATIO_CATEGORIES = ("liquidity", "leverage")
_IS_RATIO_CATEGORIES = ("profitability",)


def _facts_from_result(result: dict[str, Any] | None) -> dict[str, Decimal | None]:
    if result is None:
        return {}
    raw = result.get("facts") or {}
    return {key: json_safe_to_decimal(value) for key, value in raw.items()}


def _build_facts_dict(
    balance_sheet_result: dict[str, Any] | None,
    income_statement_result: dict[str, Any] | None,
) -> dict[str, Decimal | None]:
    facts: dict[str, Decimal | None] = {}
    facts.update(_facts_from_result(balance_sheet_result))
    facts.update(_facts_from_result(income_statement_result))

    facts["total_liabilities"] = compute_total_liabilities(
        facts.get("short_term_liabilities"), facts.get("long_term_liabilities")
    )
    return facts


def _reliability_for_category(
    category: str,
    balance_sheet_result: dict[str, Any] | None,
    income_statement_result: dict[str, Any] | None,
) -> str:
    """
    Milestone 4.3A: B.7'deki kaynak önceliğinin ilk, basit uygulaması --
    ilgili kategorinin girdisini sağlayan motorun `source_mode`'una göre
    `high`/`medium`/`medium_low` döner. Kaynak hiç yoksa `not_calculable`
    (bu durumda zaten hiçbir oran CALCULATED olmayacağı için
    `compute_registered_ratio` bu değeri kullanmayacaktır).
    """
    if category in _BS_RATIO_CATEGORIES:
        source = balance_sheet_result
    elif category in _IS_RATIO_CATEGORIES:
        source = income_statement_result
    else:
        source = None

    if source is None:
        return "not_calculable"
    source_mode = source.get("source_mode")
    if source_mode == "direct_document":
        return "high"
    if source_mode == "trial_balance_derived":
        return "medium"
    return "medium_low"


def analyze_financial_ratios(
    *,
    balance_sheet_result: dict[str, Any] | None,
    income_statement_result: dict[str, Any] | None,
) -> dict[str, Any]:
    facts = _build_facts_dict(balance_sheet_result, income_statement_result)

    categories: dict[str, Any] = {}
    all_provenance: list[ProvenanceEntry] = []
    warnings: list[dict[str, Any]] = []

    for category, ratio_keys in _CATEGORY_RATIO_KEYS.items():
        reliability = _reliability_for_category(
            category, balance_sheet_result, income_statement_result
        )
        ratios: dict[str, Any] = {}
        calculated_count = 0

        for ratio_key in ratio_keys:
            outcome = compute_registered_ratio(ratio_key, facts, reliability=reliability)
            metadata = get_ratio_formula(ratio_key)

            ratios[ratio_key] = {
                "value": decimal_to_json_safe(outcome.value),
                "unit": metadata.unit if metadata is not None else None,
                "status": outcome.status.value,
                "reliability": outcome.reliability,
                "missing_inputs": list(outcome.missing_inputs),
                "warnings": list(outcome.warnings),
            }

            if outcome.status == ComputationStatus.CALCULATED:
                calculated_count += 1
            if outcome.provenance is not None:
                all_provenance.append(outcome.provenance)
            warnings.extend(outcome.warnings)

        if calculated_count == len(ratio_keys):
            category_status = "calculated"
        elif calculated_count == 0:
            category_status = "not_calculable"
        else:
            category_status = "partial"

        categories[category] = {"status": category_status, "ratios": ratios}

    missing_categories = [c for c in _ALL_CATEGORY_KEYS if c not in categories]

    return {
        "engine": "financial_ratios",
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "analysis_type": "financial_ratios",
        "source_mode": "multi_source_derived",
        "ratio_registry_version": RATIO_REGISTRY_VERSION,
        "categories": categories,
        "missing_categories": missing_categories,
        "derived_base_figures": {
            "total_liabilities": decimal_to_json_safe(facts.get("total_liabilities")),
        },
        "warnings": warnings,
        "calculation_provenance": provenance_list_to_dict_extended(all_provenance),
    }
