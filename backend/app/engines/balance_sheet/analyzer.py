"""
Milestone 4.2: `BalanceSheetFacts` (+ opsiyonel önceki dönem) üzerinde
dikey analiz, yatay analiz, çalışma sermayesi ve BS-tek-başına
hesaplanabilen "ön izleme" yapısal oranlar.

Bu oranlar Financial Ratio Engine'in (Milestone 4.3) NİHAİ, çapraz-tablo
sonucunun YERİNE GEÇMEZ -- `result_json["preliminary_structural_ratios"]`
altında AÇIKÇA "ön izleme" olarak etiketlenir (bkz. app/engines/balance_sheet/
service.py). `result_json` ŞEKLİ (anahtar adları) Milestone 4.3A'da
DEĞİŞMEDİ -- yalnızca iç hesaplama kaynağı merkezileşti.

Milestone 4.3A (Ratio Calculation Foundation, onaylanan mimari doküman
Bölüm D.2 Karar 1/2, R.5 madde 10): `compute_preliminary_structural_ratios`
ve `compute_working_capital` artık KENDİ Decimal aritmetiğini YAPMIYOR --
`app.engines.common.ratio_formulas.compute_registered_ratio()`'ya
yönlendiriliyor (current_ratio/debt_ratio/equity_ratio/debt_to_equity/
net_working_capital/working_capital_ratio, RATIO_REGISTRY'de kayıtlı TEK
formül kaynağından okunuyor). Üretilen sayısal DEĞERLER Milestone 4.2'deki
`safe_divide` tabanlı eski hesaplamayla BİT-BİR AYNIDIR (bkz.
tests/test_ratio_formulas_unit.py'deki D.3 invariant testleri).
"""

from decimal import Decimal

from app.engines.common.calculation_provenance import ProvenanceEntry
from app.engines.common.canonical_facts import BalanceSheetFacts
from app.engines.common.ratio_derived_facts import compute_total_liabilities
from app.engines.common.ratio_formulas import compute_registered_ratio, safe_divide


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


def _build_structural_facts_dict(facts: BalanceSheetFacts) -> dict[str, Decimal | None]:
    """
    `BalanceSheetFacts` -> `compute_registered_ratio()`'nun beklediği düz
    (flat) `dict[str, Decimal | None]` şekli. `total_liabilities`, TEK
    üretim noktası olan `ratio_derived_facts.compute_total_liabilities()`
    üzerinden türetilir (Milestone 4.3A, D.2 Karar 1) -- bu fonksiyonun
    kendisi artık short_term/long_term toplamını YENİDEN YAZMAZ.
    """
    return {
        "current_assets": facts.current_assets,
        "short_term_liabilities": facts.short_term_liabilities,
        "long_term_liabilities": facts.long_term_liabilities,
        "total_assets": facts.total_assets,
        "equity": facts.equity,
        "total_liabilities": compute_total_liabilities(
            facts.short_term_liabilities, facts.long_term_liabilities
        ),
    }


def compute_working_capital(
    facts: BalanceSheetFacts,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    """
    Milestone 4.3A: `net_working_capital`/`working_capital_ratio` artık
    RATIO_REGISTRY'ye kayıtlı, `compute_registered_ratio()` üzerinden
    hesaplanıyor -- `result_json["working_capital"]` şekli (iki anahtar)
    DEĞİŞMEDİ.
    """
    facts_dict = _build_structural_facts_dict(facts)

    result: dict[str, Decimal | None] = {}
    provenance: list[ProvenanceEntry] = []
    for key in ("net_working_capital", "working_capital_ratio"):
        outcome = compute_registered_ratio(key, facts_dict)
        result[key] = outcome.value
        if outcome.provenance is not None:
            provenance.append(outcome.provenance)

    return result, provenance


def compute_preliminary_structural_ratios(
    facts: BalanceSheetFacts,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    """
    Milestone 4.3A: `current_ratio`/`debt_ratio`/`equity_ratio`/
    `debt_to_equity` artık RATIO_REGISTRY'ye kayıtlı, tek formül
    kaynağından (`compute_registered_ratio`) hesaplanıyor --
    `result_json["preliminary_structural_ratios"]` şekli (dört anahtar)
    DEĞİŞMEDİ. Üretilen değerler Milestone 4.2'deki `safe_divide` tabanlı
    hesaplamayla bit-bir aynıdır.
    """
    facts_dict = _build_structural_facts_dict(facts)

    result: dict[str, Decimal | None] = {}
    provenance: list[ProvenanceEntry] = []
    for key in ("current_ratio", "debt_ratio", "equity_ratio", "debt_to_equity"):
        outcome = compute_registered_ratio(key, facts_dict)
        result[key] = outcome.value
        if outcome.provenance is not None:
            provenance.append(outcome.provenance)

    return result, provenance
