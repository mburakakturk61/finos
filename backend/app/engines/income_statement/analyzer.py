"""
Milestone 4.2: `IncomeStatementFacts` (+ opsiyonel önceki dönem) üzerinde
dikey analiz, yatay analiz, marj analizleri ve EBIT/EBITDA çözümlemesi.

EBIT politikası (onaylanan Milestone 4.2 kararı #3 -- KRİTİK): `operating_profit`
ayrı bir canonical fact olarak korunur ve EBIT'e ASLA otomatik/sessizce
kopyalanmaz. `ebit` yalnızca belgede AÇIKÇA raporlanmışsa (extractor/fallback
`facts.ebit`'i doldurmuşsa) dolar; aksi halde `None` + `EBIT_NOT_DETERMINABLE`
warning'i. `ebitda` yalnızca `ebit` VE `depreciation_and_amortization` İKİSİ
DE doluysa hesaplanır.
"""

import dataclasses
from decimal import Decimal

from app.engines.common.calculation_provenance import ProvenanceEntry
from app.engines.common.canonical_facts import IncomeStatementFacts
from app.engines.common.ratio_formulas import compute_registered_ratio, safe_divide


EBIT_NOT_DETERMINABLE_CODE = "EBIT_NOT_DETERMINABLE"
EBIT_NOT_DETERMINABLE_MESSAGE = (
    "EBIT, mevcut verilerden güvenilir şekilde hesaplanamadı."
)

VERTICAL_FIELDS = [
    "gross_sales", "sales_deductions", "cost_of_sales", "gross_profit",
    "operating_expenses", "other_operating_income", "other_operating_expenses",
    "operating_profit", "financing_expenses", "extraordinary_income",
    "extraordinary_expenses", "profit_before_tax", "net_profit",
]


def resolve_ebit(facts: IncomeStatementFacts) -> tuple[Decimal | None, ProvenanceEntry, dict | None]:
    """
    Döner: (ebit, provenance, warning_dict_or_None).

    v1 politikası (onaylanan karar #3): yalnızca yol (a) -- belgede AÇIKÇA
    "faiz ve vergi öncesi kâr" olarak raporlanmış bir değer -- uygulanır.
    Yol (b) (bileşenlerden deterministik formülle hesaplama) için, farklı
    finansal tablo formatlarında (diğer faaliyet gelir/gider sınıflandırma
    farkları nedeniyle) TUTARLI ve güvenilir tek bir formül bu milestone'da
    tanımlanamadı -- bu, "sessiz eşitleme yapma" ilkesine en temkinli uyan
    yorumdur. `operating_profit` HİÇBİR ZAMAN `ebit`'e kopyalanmaz.
    """

    if facts.ebit is not None:
        provenance = ProvenanceEntry(
            metric="ebit",
            derivation_rule="doğrudan belgede raporlanan değer",
            input_fields=("ebit",),
            missing_inputs=(),
            calculated=True,
        )
        return facts.ebit, provenance, None

    provenance = ProvenanceEntry(
        metric="ebit",
        derivation_rule=(
            "belgede doğrudan raporlanmadı; farklı tablo formatları arasında "
            "tutarlı, güvenilir bir deterministik türetim formülü bu "
            "milestone'da tanımlanmadı"
        ),
        input_fields=(),
        missing_inputs=("ebit",),
        calculated=False,
    )
    warning = {
        "code": EBIT_NOT_DETERMINABLE_CODE,
        "severity": "warning",
        "message": EBIT_NOT_DETERMINABLE_MESSAGE,
    }
    return None, provenance, warning


def resolve_ebitda(
    ebit: Decimal | None, depreciation_and_amortization: Decimal | None
) -> tuple[Decimal | None, ProvenanceEntry]:
    missing = []
    if ebit is None:
        missing.append("ebit")
    if depreciation_and_amortization is None:
        missing.append("depreciation_and_amortization")

    ebitda = ebit + depreciation_and_amortization if not missing else None

    provenance = ProvenanceEntry(
        metric="ebitda",
        derivation_rule="ebit + depreciation_and_amortization",
        input_fields=("ebit", "depreciation_and_amortization"),
        missing_inputs=tuple(missing),
        calculated=ebitda is not None,
    )
    return ebitda, provenance


def compute_margins(
    facts: IncomeStatementFacts, ebit: Decimal | None, ebitda: Decimal | None
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    """
    Milestone 4.3A (onaylanan mimari doküman Bölüm D.2 Karar 1/2, R.5 madde
    10) + Milestone 4.3B / Step 4 (onaylanan tasarım Bölüm 8 "registry
    duplication" riskinin kapatılması): TÜM BEŞ marj artık RATIO_REGISTRY'ye
    kayıtlı (`gross_profit_margin`/`operating_profit_margin`/
    `net_profit_margin`/`ebit_margin`/`ebitda_margin`),
    `compute_registered_ratio()` üzerinden hesaplanıyor -- üretilen sayısal
    değerler Milestone 4.2'deki `safe_divide` tabanlı hesaplamayla bit-bir
    aynıdır. Artık BS/IS motorlarında BAĞIMSIZ ikinci bir aritmetik formül
    KALMADI (D.2 Karar 1'in tam uygulanması). `result_json["margins"]`
    şekli (beş anahtar) DEĞİŞMEDİ.
    """
    net_sales = facts.net_sales

    facts_dict = {
        "gross_profit": facts.gross_profit,
        "operating_profit": facts.operating_profit,
        "net_profit": facts.net_profit,
        "net_sales": net_sales,
        "ebit": ebit,
        "ebitda": ebitda,
    }

    gross_outcome = compute_registered_ratio("gross_profit_margin", facts_dict)
    operating_outcome = compute_registered_ratio("operating_profit_margin", facts_dict)
    net_outcome = compute_registered_ratio("net_profit_margin", facts_dict)
    ebit_outcome = compute_registered_ratio("ebit_margin", facts_dict)
    ebitda_outcome = compute_registered_ratio("ebitda_margin", facts_dict)

    margins = {
        "gross_margin_pct": gross_outcome.value,
        "operating_margin_pct": operating_outcome.value,
        "ebit_margin_pct": ebit_outcome.value,
        "ebitda_margin_pct": ebitda_outcome.value,
        "net_margin_pct": net_outcome.value,
    }

    # compute_registered_ratio'nun ürettiği ProvenanceEntry.metric, RATIO_
    # REGISTRY anahtarını (ör. "gross_profit_margin"/"ebit_margin") taşır --
    # bu fonksiyonun YEREL alan adıyla (ör. "gross_margin_pct"/
    # "ebit_margin_pct") eşleşmesi için dataclasses.replace ile yeniden
    # adlandırılır (result_json["margins"] şeklinin AYNI kalması, Milestone
    # 4.3A onayı madde 5 -- 4.3B'de de BOZULMADI).
    gross_provenance = dataclasses.replace(gross_outcome.provenance, metric="gross_margin_pct")
    operating_provenance = dataclasses.replace(
        operating_outcome.provenance, metric="operating_margin_pct"
    )
    net_provenance = dataclasses.replace(net_outcome.provenance, metric="net_margin_pct")
    ebit_provenance = dataclasses.replace(ebit_outcome.provenance, metric="ebit_margin_pct")
    ebitda_provenance = dataclasses.replace(ebitda_outcome.provenance, metric="ebitda_margin_pct")

    provenance = [
        gross_provenance,
        operating_provenance,
        ebit_provenance,
        ebitda_provenance,
        net_provenance,
    ]

    return margins, provenance


def compute_vertical_analysis(
    facts: IncomeStatementFacts,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    result: dict[str, Decimal | None] = {}
    provenance: list[ProvenanceEntry] = []
    net_sales = facts.net_sales

    for field_name in VERTICAL_FIELDS:
        value = getattr(facts, field_name)
        pct = safe_divide(value, net_sales)
        if pct is not None:
            pct = pct * Decimal("100")

        metric = f"{field_name}_pct_of_net_sales"
        result[metric] = pct

        missing = []
        if value is None:
            missing.append(field_name)
        if net_sales is None:
            missing.append("net_sales")

        provenance.append(
            ProvenanceEntry(
                metric=metric,
                derivation_rule=f"{field_name} / net_sales * 100",
                input_fields=(field_name, "net_sales"),
                missing_inputs=tuple(missing),
                calculated=pct is not None,
            )
        )

    return result, provenance


def compute_horizontal_analysis(
    current: IncomeStatementFacts,
    prior: IncomeStatementFacts | None,
) -> tuple[dict[str, Decimal | None], list[ProvenanceEntry]]:
    result: dict[str, Decimal | None] = {}
    provenance: list[ProvenanceEntry] = []

    for field_name in VERTICAL_FIELDS:
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
