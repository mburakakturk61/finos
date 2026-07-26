"""
Milestone 4.2: `BalanceSheetFacts` (+ opsiyonel önceki dönem) üzerinde
dikey analiz, yatay analiz, çalışma sermayesi ve BS-tek-başına
hesaplanabilen "ön izleme" yapısal oranlar.

Bu oranlar Financial Ratio Engine'in (Milestone 4.3) NİHAİ, çapraz-tablo
sonucunun YERİNE GEÇMEZ -- `result_json["preliminary_structural_ratios"]`
altında AÇIKÇA "ön izleme" olarak etiketlenir (bkz. app/engines/balance_sheet/
service.py). Formüller `app.engines.common.ratio_formulas.safe_divide`
(4.1) üzerinden -- tek formül kaynağı, iki yerde ayrı "current_ratio"
tanımı yok.
"""

from decimal import Decimal

from app.engines.common.calculation_provenance import ProvenanceEntry
from app.engines.common.canonical_facts import BalanceSheetFacts
from app.engines.common.ratio_formulas import safe_divide


VERTICAL_FIELDS = [
    "current_assets",
    "non_current_assets",
    "short_term_liabilities",
    "long_term_liabilities",
    "equity",
    "cash_and_equivalents",
    "inventory",
    "trade_receivables",
    "trade_payables",
]

HORIZONTAL_FIELDS = VERTICAL_FIELDS + ["total_assets", "total_liabilities_and_equity"]


def compute_vertical_analysis(
    facts: BalanceSheetFacts,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    result: dict[str, Decimal | None] = {}
    provenance: list[ProvenanceEntry] = []
    total = facts.total_assets

    for field_name in VERTICAL_FIELDS:
        value = getattr(facts, field_name)
        pct = safe_divide(value, total)
        if pct is not None:
            pct = pct * Decimal("100")

        metric = f"{field_name}_pct_of_total_assets"
        result[metric] = pct

        missing = []
        if value is None:
            missing.append(field_name)
        if total is None:
            missing.append("total_assets")

        provenance.append(
            ProvenanceEntry(
                metric=metric,
                derivation_rule=f"{field_name} / total_assets * 100",
                input_fields=(field_name, "total_assets"),
                missing_inputs=tuple(missing),
                calculated=pct is not None,
            )
        )

    return result, provenance


def compute_horizontal_analysis(
    current: BalanceSheetFacts,
    prior: BalanceSheetFacts | None,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    result: dict[str, Decimal | None] = {}
    provenance: list[ProvenanceEntry] = []

    for field_name in HORIZONTAL_FIELDS:
        current_value = getattr(current, field_name)
        prior_value = getattr(prior, field_name) if prior is not None else None

        missing = []
        if current_value is None:
            missing.append(f"current.{field_name}")
        if prior is None:
            missing.append("prior_period")
        elif prior_value is None:
            missing.append(f"prior.{field_name}")

        change_pct = None
        if current_value is not None and prior_value is not None and prior_value != 0:
            change_pct = ((current_value - prior_value) / abs(prior_value)) * Decimal("100")

        metric = f"{field_name}_change_pct"
        result[metric] = change_pct
        provenance.append(
            ProvenanceEntry(
                metric=metric,
                derivation_rule=(
                    f"(current.{field_name} - prior.{field_name}) / "
                    f"abs(prior.{field_name}) * 100"
                ),
                input_fields=(f"current.{field_name}", f"prior.{field_name}"),
                missing_inputs=tuple(missing),
                calculated=change_pct is not None,
            )
        )

    return result, provenance


def compute_working_capital(
    facts: BalanceSheetFacts,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    missing = []
    if facts.current_assets is None:
        missing.append("current_assets")
    if facts.short_term_liabilities is None:
        missing.append("short_term_liabilities")

    net_working_capital = (
        facts.current_assets - facts.short_term_liabilities if not missing else None
    )
    working_capital_ratio = safe_divide(facts.current_assets, facts.short_term_liabilities)

    provenance = [
        ProvenanceEntry(
            metric="net_working_capital",
            derivation_rule="current_assets - short_term_liabilities",
            input_fields=("current_assets", "short_term_liabilities"),
            missing_inputs=tuple(missing),
            calculated=net_working_capital is not None,
        ),
        ProvenanceEntry(
            metric="working_capital_ratio",
            derivation_rule="current_assets / short_term_liabilities",
            input_fields=("current_assets", "short_term_liabilities"),
            missing_inputs=tuple(missing),
            calculated=working_capital_ratio is not None,
        ),
    ]

    return {
        "net_working_capital": net_working_capital,
        "working_capital_ratio": working_capital_ratio,
    }, provenance


def compute_preliminary_structural_ratios(
    facts: BalanceSheetFacts,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    total_liabilities = None
    total_liabilities_missing: tuple[str, ...] = ()
    if facts.short_term_liabilities is not None and facts.long_term_liabilities is not None:
        total_liabilities = facts.short_term_liabilities + facts.long_term_liabilities
    else:
        total_liabilities_missing = ("short_term_liabilities", "long_term_liabilities")

    current_ratio = safe_divide(facts.current_assets, facts.short_term_liabilities)
    debt_ratio = safe_divide(total_liabilities, facts.total_assets)
    equity_ratio = safe_divide(facts.equity, facts.total_assets)
    debt_to_equity = safe_divide(total_liabilities, facts.equity)

    provenance = [
        ProvenanceEntry(
            "current_ratio",
            "current_assets / short_term_liabilities",
            ("current_assets", "short_term_liabilities"),
            (),
            current_ratio is not None,
        ),
        ProvenanceEntry(
            "debt_ratio",
            "(short_term_liabilities + long_term_liabilities) / total_assets",
            ("short_term_liabilities", "long_term_liabilities", "total_assets"),
            total_liabilities_missing if debt_ratio is None else (),
            debt_ratio is not None,
        ),
        ProvenanceEntry(
            "equity_ratio",
            "equity / total_assets",
            ("equity", "total_assets"),
            (),
            equity_ratio is not None,
        ),
        ProvenanceEntry(
            "debt_to_equity",
            "(short_term_liabilities + long_term_liabilities) / equity",
            ("short_term_liabilities", "long_term_liabilities", "equity"),
            total_liabilities_missing if debt_to_equity is None else (),
            debt_to_equity is not None,
        ),
    ]

    return {
        "current_ratio": current_ratio,
        "debt_ratio": debt_ratio,
        "equity_ratio": equity_ratio,
        "debt_to_equity": debt_to_equity,
    }, provenance
