"""
Milestone 4.3A (Ratio Calculation Foundation) / Milestone 4.3B (Core
Financial Ratios): Financial Ratio Engine'in orkestrasyon katmanı --
`analyze_financial_ratios`, Balance Sheet/Income Statement motorlarının
ZATEN ÜRETTİĞİ (kayıtlı) `result_json`'lardan (YENİDEN HESAPLAMA YOK, B.3)
kayıtlı oranları `compute_registered_ratio` üzerinden üretir.

Milestone 4.3B (onaylanan tasarım dokümanı, 2. tur onay) bu orkestrasyonu
genişletiyor:
  - `quick_assets`/`days_in_period` gibi ek türetilmiş alanlar facts
    dict'e enjekte edilir (Bölüm 2.1/4.1).
  - `direct_document_only_fields` dolu bir oran, ilgili BS sonucu
    `source_mode="direct_document"` DEĞİLSE, `compute_registered_ratio`
    HİÇ ÇAĞRILMADAN doğrudan `NOT_APPLICABLE` üretir (Bölüm 6).
  - `engine_dependency` dolu bir oran, ilgili motorun sonucu context'te
    YOKSA, aynı şekilde doğrudan `NOT_CALCULABLE` üretir (Bölüm 5.5,
    2. tur onay karar #3).

KAPSAM SINIRI (onaylanan Milestone 4.3B tasarım dokümanı, Bölüm 10):
Yatırım/Piyasa/Bankacılık/IFRS/Risk/Sermaye Yapısı/Çalışma Sermayesi
kategorileri bu fazın kapsamı DIŞINDA -- `missing_categories` altında
dürüstçe listelenmeye devam ediyor.

`app/trial_balance/**`'ten HİÇBİR import YOK.
"""

import dataclasses
from decimal import Decimal
from typing import Any

from app.engines.common.calculation_provenance import (
    ProvenanceEntry,
    provenance_list_to_dict_extended,
)
from app.engines.common.ratio_derived_facts import (
    compute_average_equity,
    compute_average_inventory,
    compute_average_total_assets,
    compute_average_trade_payables,
    compute_average_trade_receivables,
    compute_capital_employed,
    compute_days_in_period,
    compute_invested_capital,
    compute_quick_assets,
    compute_tax_expense,
    compute_total_liabilities,
)
from app.engines.common.ratio_formulas import (
    RATIO_REGISTRY_VERSION,
    ComputationOutcome,
    ComputationStatus,
    RatioFormulaMetadata,
    decimal_to_json_safe,
    get_ratio_formula,
    json_safe_to_decimal,
    compute_registered_ratio,
)


ENGINE_VERSION = "1.1.0"
SCHEMA_VERSION = "1.0"

# Milestone 4.3B: 4.3A'nın 9 oranı + Step 3'te eklenen 9 yeni oran (Likidite
# + Borçluluk'un kalanı, onaylanan tasarım dokümanı Bölüm 2.1/2.3, Bölüm 9
# Step 3). Kalan kategoriler (activity/profitability'nin kalanı/efficiency/
# growth/cash_flow) sonraki adımlarda eklenecek; diğer 7 kategori (Bölüm 10)
# `missing_categories`'de kalmaya devam ediyor.
_CATEGORY_RATIO_KEYS: dict[str, tuple[str, ...]] = {
    "liquidity": (
        "current_ratio",
        "working_capital_ratio",
        "net_working_capital",
        "quick_ratio",
        "cash_ratio",
        "defensive_interval_ratio",
        # Milestone 4.3B / Step 6: net_working_capital'DAN SONRA gelmeli --
        # depends_on_ratios ile ZATEN HESAPLANMIŞ değerini okur.
        "working_capital_to_total_assets",
    ),
    "leverage": (
        "debt_ratio",
        "equity_ratio",
        "debt_to_equity",
        "long_term_debt_to_equity",
        "short_term_debt_ratio",
        "financial_leverage_multiplier",
        "interest_coverage_ratio",
        "ebitda_coverage_ratio",
        "debt_to_ebitda",
        "fixed_charge_coverage",
    ),
    "profitability": (
        "gross_profit_margin",
        "operating_profit_margin",
        "net_profit_margin",
        "ebit_margin",
        "ebitda_margin",
        "pretax_profit_margin",
        "return_on_capital_employed",
        # effective_tax_rate, return_on_invested_capital'DAN ÖNCE
        # hesaplanmalı -- ROIC, effective_tax_rate'in ZATEN HESAPLANMIŞ
        # değerine (depends_on_ratios) ihtiyaç duyar (Bölüm 3.5).
        "effective_tax_rate",
        "return_on_invested_capital",
        # Milestone 4.3B / Step 5: ortalama-bakiye bağımlı kârlılık oranları.
        "return_on_assets",
        "return_on_equity",
    ),
    # Milestone 4.3B / Step 5: Faaliyet kategorisinin ortalama-bakiye
    # bağımlı ilk 4 oranı (kalan 6'sı -- fixed_asset_turnover/working_
    # capital_turnover/days_*/cash_conversion_cycle -- Step 6'da eklenecek).
    "activity": (
        "asset_turnover",
        "inventory_turnover",
        "receivables_turnover",
        "payables_turnover",
        # Milestone 4.3B / Step 6: bağımlılığı OLMAYAN oran -- sıra
        # önemsiz, ama okunabilirlik için turnover'lardan sonra.
        "fixed_asset_turnover",
        # working_capital_turnover, "liquidity" kategorisinde ZATEN
        # hesaplanmış net_working_capital'ı okur (kategoriler arası
        # depends_on_ratios -- liquidity, activity'DEN ÖNCE işlenir).
        "working_capital_turnover",
        # days_* kendi turnover'larından SONRA gelmeli.
        "days_inventory_outstanding",
        "days_sales_outstanding",
        "days_payables_outstanding",
        # cash_conversion_cycle, üç days_* oranından SONRA gelmeli.
        "cash_conversion_cycle",
    ),
    # Milestone 4.3B / Step 7: Verimlilik kategorisi (6 oran, bağımlılık YOK,
    # tamamen IS alanlarına dayalı).
    "efficiency": (
        "operating_expense_ratio",
        "cost_of_sales_ratio",
        "overhead_ratio",
        "ebit_to_opex",
        "non_operating_income_dependency",
        "financing_expense_to_sales",
    ),
    # Milestone 4.3B / Step 8: Büyüme kategorisi -- "profitability"'DEN
    # SONRA işlenmeli (sustainable_growth_rate, return_on_equity'nin ZATEN
    # HESAPLANMIŞ değerini okur -- dict sırası profitability'yi önce
    # işliyor).
    "growth": (
        "sales_growth",
        "gross_profit_growth",
        "ebitda_growth",
        "net_profit_growth",
        "total_assets_growth",
        "equity_growth",
        "sustainable_growth_rate",
    ),
    # Milestone 4.3B / Step 9: Nakit Akışı kategorisi -- Cash Flow Engine
    # (Milestone 4.4) henüz YOK, hepsi `engine_dependency="cash_flow"` ile
    # işaretli, HER ZAMAN not_calculable (bkz. service.py::
    # _engine_dependency_not_calculable_outcome).
    "cash_flow": (
        "operating_cash_flow_margin",
        "free_cash_flow_margin",
        "cash_flow_to_debt",
        "cash_return_on_assets",
        "cash_interest_coverage",
        "operating_cash_flow_ratio",
    ),
}

# Milestone 4.3B / Step 5: bir oranın hangi `average_*` facts-dict anahtarına
# bağımlı olduğu -- Bölüm 8 "average hesaplarının tutarsızlığı" riskinin
# giderilmesi için TEK bir yerde (bkz. `_inject_average_facts`) hesaplanan
# değerin doğru `calculation_basis`/`reliability` bilgisiyle
# `ratios[ratio_key]` çıktısına yansıtılması amacıyla kullanılır.
_RATIO_TO_AVERAGE_FACT: dict[str, str] = {
    "return_on_assets": "average_total_assets",
    "asset_turnover": "average_total_assets",
    "return_on_equity": "average_equity",
    "inventory_turnover": "average_inventory",
    "receivables_turnover": "average_trade_receivables",
    "payables_turnover": "average_trade_payables",
}

_RELIABILITY_RANK = {
    "high": 3,
    "medium": 2,
    "medium_low": 1,
    "low": 1,
    "not_calculable": 0,
}


def _worse_reliability(a: str, b: str) -> str:
    return a if _RELIABILITY_RANK.get(a, 0) <= _RELIABILITY_RANK.get(b, 0) else b

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
_IS_RATIO_CATEGORIES = ("profitability", "efficiency")
# Milestone 4.3B / Step 5+8: "activity"/"growth" kategorileri HEM BS
# (average_*/total_assets/equity alanları) HEM IS (net_sales/cost_of_sales/
# gross_profit/ebitda/net_profit alanları) alanlarına bağımlı -- reliability,
# ikisinin ARASINDAKİ DAHA DÜŞÜK olanı olmalıdır (Bölüm 8 tutarlılık ilkesi).
_BS_AND_IS_RATIO_CATEGORIES = ("activity", "growth")


def _facts_from_result(result: dict[str, Any] | None) -> dict[str, Decimal | None]:
    if result is None:
        return {}
    raw = result.get("facts") or {}
    return {key: json_safe_to_decimal(value) for key, value in raw.items()}


def _build_facts_dict(
    balance_sheet_result: dict[str, Any] | None,
    income_statement_result: dict[str, Any] | None,
    *,
    prior_period_balance_sheet_result: dict[str, Any] | None = None,
    prior_period_income_statement_result: dict[str, Any] | None = None,
    period_start_date=None,
    period_end_date=None,
    period_months_covered: int | None = None,
) -> tuple[dict[str, Decimal | None], list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """
    Döner: `(facts, extra_warnings, average_meta)`. Milestone 4.3B:
    `total_liabilities`e ek olarak `quick_assets` (Bölüm 2.1) ve
    `days_in_period` (Bölüm 4.1, `+1` kapsayıcı düzeltmesiyle) enjekte
    edilir. `days_in_period`'in fallback/geçersiz-sıra warning'i (varsa)
    `extra_warnings` üzerinden üst seviyeye taşınır -- SESSİZCE kaybolmaz.

    `average_meta`: Step 5 -- her `average_*` anahtarının
    `(reliability, calculation_basis)` çifti (Bölüm 6 "average
    hesaplanamaması" politikası, 2. tur onay karar #4) -- warning ÜRETMEZ,
    yalnızca bu açık alan çiftini taşır; `_RATIO_TO_AVERAGE_FACT` üzerinden
    ilgili oranın çıktısına yansıtılır.

    Step 8: `prior_*` önekli alanlar (Bölüm 3.3 isimlendirme kuralı) --
    `prior_net_sales`/`prior_gross_profit`/`prior_ebitda`/`prior_net_profit`
    (IS'ten) ve `prior_total_assets`/`prior_equity` (BS'ten) -- `growth_rate`
    stratejisinin `current_field`/`prior_field` sözleşmesini besler.
    """

    facts: dict[str, Decimal | None] = {}
    facts.update(_facts_from_result(balance_sheet_result))
    facts.update(_facts_from_result(income_statement_result))
    prior_bs_facts = _facts_from_result(prior_period_balance_sheet_result)
    prior_is_facts = _facts_from_result(prior_period_income_statement_result)

    for field_name in ("net_sales", "gross_profit", "ebitda", "net_profit"):
        facts[f"prior_{field_name}"] = prior_is_facts.get(field_name)
    for field_name in ("total_assets", "equity"):
        facts[f"prior_{field_name}"] = prior_bs_facts.get(field_name)

    facts["total_liabilities"] = compute_total_liabilities(
        facts.get("short_term_liabilities"), facts.get("long_term_liabilities")
    )
    facts["quick_assets"] = compute_quick_assets(
        facts.get("current_assets"), facts.get("inventory")
    )
    # Milestone 4.3B / Step 4: return_on_capital_employed / effective_tax_
    # rate / return_on_invested_capital için saf ara büyüklükler (Bölüm 5.3
    # kuralı -- kullanıcıya doğrudan sunulmayan bileşenler).
    facts["capital_employed"] = compute_capital_employed(
        facts.get("total_assets"), facts.get("short_term_liabilities")
    )
    facts["tax_expense"] = compute_tax_expense(
        facts.get("profit_before_tax"), facts.get("net_profit")
    )
    facts["invested_capital"] = compute_invested_capital(
        facts.get("equity"), facts.get("long_term_liabilities")
    )

    # Milestone 4.3B / Step 5: average_* -- Bölüm 8 riski gereği TEK
    # noktadan hesaplanıp enjekte edilir (return_on_assets/asset_turnover
    # gibi birden fazla oran AYNI değeri okur).
    average_meta: dict[str, tuple[str, str]] = {}
    for fact_key, compute_fn, current_field in (
        ("average_total_assets", compute_average_total_assets, "total_assets"),
        ("average_equity", compute_average_equity, "equity"),
        ("average_inventory", compute_average_inventory, "inventory"),
        ("average_trade_receivables", compute_average_trade_receivables, "trade_receivables"),
        ("average_trade_payables", compute_average_trade_payables, "trade_payables"),
    ):
        value, reliability, calculation_basis = compute_fn(
            facts.get(current_field), prior_bs_facts.get(current_field)
        )
        facts[fact_key] = value
        average_meta[fact_key] = (reliability, calculation_basis)

    days_value, _days_reliability, days_warning = compute_days_in_period(
        start_date=period_start_date,
        end_date=period_end_date,
        months_covered=period_months_covered,
    )
    facts["days_in_period"] = days_value

    extra_warnings: list[dict[str, Any]] = []
    if days_warning is not None:
        extra_warnings.append(days_warning)

    return facts, extra_warnings, average_meta


def _not_applicable_outcome(metadata: RatioFormulaMetadata) -> ComputationOutcome:
    """
    Milestone 4.3B (Bölüm 6): `direct_document_only_fields` dolu bir oran,
    ilgili BS sonucu `source_mode="direct_document"` DEĞİLKEN
    `compute_registered_ratio` HİÇ ÇAĞRILMADAN buraya yönlendirilir --
    "veri eksik" (missing_input) ile "bu kaynak modunda yapısal olarak
    imkansız" (not_applicable) AYRIMI, yalnızca orkestrasyonun
    `source_mode` bilgisine erişimi olduğu için BURADA yapılabilir.
    """

    warning = {
        "code": "NOT_APPLICABLE_SOURCE_MODE",
        "severity": "medium",
        "message": (
            f"'{metadata.key}' bu kaynak modunda yapısal olarak "
            f"uygulanamaz ({', '.join(metadata.direct_document_only_fields)} "
            "yalnızca source_mode=direct_document iken mevcuttur)."
        ),
    }
    return ComputationOutcome(
        status=ComputationStatus.NOT_APPLICABLE,
        value=None,
        warnings=(warning,),
        reliability="not_calculable",
        provenance=ProvenanceEntry(
            metric=metadata.key,
            derivation_rule="(yapısal olarak uygulanamaz -- kaynak modu)",
            input_fields=metadata.direct_document_only_fields,
            missing_inputs=(),
            calculated=False,
            reliability="not_calculable",
        ),
    )


def _apply_effective_tax_rate_range_check(outcome: ComputationOutcome) -> ComputationOutcome:
    """
    Milestone 4.3B (2. tur onay karar #7): `effective_tax_rate` [0, 1]
    aralığının DIŞINDA bir değer üretirse (ör. IS'teki olağandışı gelir/
    gider kalemleri nedeniyle negatif ya da 1'in üzerinde bir efektif vergi
    oranı çıkarsa), bu değer GİZLENMEZ -- yalnızca açık bir warning
    eklenir ve `reliability="low"`a düşürülür (kanuni vergi oranı
    varsayılmaz, GERÇEK IS verisinden türeyen bu olağandışı sonuç
    şeffafça raporlanır).
    """

    if outcome.status != ComputationStatus.CALCULATED or outcome.value is None:
        return outcome
    if Decimal("0") <= outcome.value <= Decimal("1"):
        return outcome

    range_warning = {
        "code": "EFFECTIVE_TAX_RATE_OUT_OF_EXPECTED_RANGE",
        "severity": "medium",
        "message": (
            f"effective_tax_rate [0, 1] aralığının dışında hesaplandı "
            f"(değer={outcome.value}) -- bu, GERÇEK IS verisinden "
            "(olağandışı gelir/gider kalemleri dahil) kaynaklanabilir; "
            "değer GİZLENMEDİ, yalnızca güvenilirlik düşürüldü."
        ),
    }
    return dataclasses.replace(
        outcome,
        warnings=outcome.warnings + (range_warning,),
        reliability="low",
    )


def _engine_dependency_not_calculable_outcome(metadata: RatioFormulaMetadata) -> ComputationOutcome:
    """
    Milestone 4.3B / Step 9 (Bölüm 5.5, 2. tur onay karar #3):
    `engine_dependency` dolu bir oran (ör. Nakit Akışı kategorisinin 6
    oranı, `engine_dependency="cash_flow"`), ilgili motorun sonucu bu
    fazda HİÇ MEVCUT DEĞİLKEN (Cash Flow Engine Milestone 4.4'ü bekliyor --
    `analyze_financial_ratios`'un bugünkü imzasında bir `cash_flow_result`
    parametresi bile YOK) `compute_registered_ratio` HİÇ ÇAĞRILMADAN
    NOT_CALCULABLE üretir -- "veri eksik" (missing_input) ile "bu YETENEK
    henüz yok" (not_calculable) ayrımı netleşir. Motor GERÇEKTEN mevcut
    olduğunda (Milestone 4.4), yalnızca o zaman bu kısayol kaldırılıp
    normal `compute_registered_ratio` akışına (missing_input dahil)
    dönülecektir.
    """

    warning = {
        "code": "ENGINE_DEPENDENCY_NOT_AVAILABLE",
        "severity": "medium",
        "message": (
            f"'{metadata.key}', '{metadata.engine_dependency}' motorunun "
            "sonucuna ihtiyaç duyuyor ancak bu motor bu Milestone'da henüz "
            "mevcut değil (veri eksik değil, YETENEK henüz yok)."
        ),
    }
    return ComputationOutcome(
        status=ComputationStatus.NOT_CALCULABLE,
        value=None,
        warnings=(warning,),
        reliability="not_calculable",
        provenance=ProvenanceEntry(
            metric=metadata.key,
            derivation_rule=f"(motor bağımlılığı henüz yok: {metadata.engine_dependency})",
            input_fields=metadata.numerator_fields + metadata.denominator_fields,
            missing_inputs=(),
            calculated=False,
            reliability="not_calculable",
        ),
    )


def _fixed_charge_coverage_not_calculable_outcome(
    metadata: RatioFormulaMetadata,
) -> ComputationOutcome:
    """
    Milestone 4.3B / Step 3 düzeltmesi (onaylanan tasarım Bölüm 2.3): kira/
    kiralama gideri (lease_payments) ayrıştırması HİÇBİR motorda/canonical_
    facts'te yok -- bu oran HER ZAMAN, `compute_registered_ratio` HİÇ
    ÇAĞRILMADAN, kontrollü `NOT_CALCULABLE` olarak kısa devre yaptırılır
    (sustainable_growth_rate ile AYNI desen).
    """

    warning = {
        "code": "FIXED_CHARGE_COVERAGE_DATA_UNAVAILABLE",
        "severity": "medium",
        "message": (
            "fixed_charge_coverage için gerekli kiralama gideri (lease_"
            "payments) ayrıştırması hiçbir motorda üretilmiyor -- oran "
            "kontrollü olarak not_calculable bırakıldı."
        ),
    }
    return ComputationOutcome(
        status=ComputationStatus.NOT_CALCULABLE,
        value=None,
        warnings=(warning,),
        reliability="not_calculable",
        provenance=ProvenanceEntry(
            metric=metadata.key,
            derivation_rule="(ebit + lease_payments) / (financing_expenses + lease_payments) -- veri yok",
            input_fields=("ebit", "financing_expenses", "lease_payments"),
            missing_inputs=("lease_payments",),
            calculated=False,
            reliability="not_calculable",
        ),
    )


def _sustainable_growth_rate_not_calculable_outcome(
    metadata: RatioFormulaMetadata,
) -> ComputationOutcome:
    """
    Milestone 4.3B / Step 8 (onaylanan tasarım Bölüm 2.6): kâr dağıtım/
    temettü verisi HİÇBİR motorda yok -- kanuni/varsayılan bir oran (ör.
    "%0 dağıtım varsayımı") FABRİKE EDİLMEZ. Bu oran HER ZAMAN,
    `compute_registered_ratio` HİÇ ÇAĞRILMADAN, kontrollü `NOT_CALCULABLE`
    olarak kısa devre yaptırılır (formülün ihtiyaç duyduğu alan hiçbir
    motorda tanımlı değil -- ComputationStatus.NOT_CALCULABLE'ın BİRİNCİ
    tanımı, Bölüm 1.3).
    """

    warning = {
        "code": "SUSTAINABLE_GROWTH_RATE_DATA_UNAVAILABLE",
        "severity": "medium",
        "message": (
            "sustainable_growth_rate için gerekli kâr dağıtım/temettü verisi "
            "hiçbir motorda üretilmiyor -- varsayılan bir dağıtım oranı "
            "FABRİKE EDİLMEDİ, oran kontrollü olarak not_calculable "
            "bırakıldı."
        ),
    }
    return ComputationOutcome(
        status=ComputationStatus.NOT_CALCULABLE,
        value=None,
        warnings=(warning,),
        reliability="not_calculable",
        provenance=ProvenanceEntry(
            metric=metadata.key,
            derivation_rule="ROE * (1 - kar_dagitim_orani) -- veri hicbir motorda yok",
            input_fields=("return_on_equity", "dividend_payout_ratio"),
            missing_inputs=("dividend_payout_ratio",),
            calculated=False,
            reliability="not_calculable",
        ),
    )


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
    def _reliability_from_source(source: dict[str, Any] | None) -> str:
        if source is None:
            return "not_calculable"
        source_mode = source.get("source_mode")
        if source_mode == "direct_document":
            return "high"
        if source_mode == "trial_balance_derived":
            return "medium"
        return "medium_low"

    if category in _BS_RATIO_CATEGORIES:
        return _reliability_from_source(balance_sheet_result)
    if category in _IS_RATIO_CATEGORIES:
        return _reliability_from_source(income_statement_result)
    if category in _BS_AND_IS_RATIO_CATEGORIES:
        return _worse_reliability(
            _reliability_from_source(balance_sheet_result),
            _reliability_from_source(income_statement_result),
        )
    return "not_calculable"


def analyze_financial_ratios(
    *,
    balance_sheet_result: dict[str, Any] | None,
    income_statement_result: dict[str, Any] | None,
    prior_period_balance_sheet_result: dict[str, Any] | None = None,
    prior_period_income_statement_result: dict[str, Any] | None = None,
    period_start_date=None,
    period_end_date=None,
    period_months_covered: int | None = None,
) -> dict[str, Any]:
    facts, extra_warnings, average_meta = _build_facts_dict(
        balance_sheet_result,
        income_statement_result,
        prior_period_balance_sheet_result=prior_period_balance_sheet_result,
        prior_period_income_statement_result=prior_period_income_statement_result,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        period_months_covered=period_months_covered,
    )

    categories: dict[str, Any] = {}
    all_provenance: list[ProvenanceEntry] = []
    warnings: list[dict[str, Any]] = list(extra_warnings)

    for category, ratio_keys in _CATEGORY_RATIO_KEYS.items():
        base_reliability = _reliability_for_category(
            category, balance_sheet_result, income_statement_result
        )
        ratios: dict[str, Any] = {}
        calculated_count = 0

        for ratio_key in ratio_keys:
            metadata = get_ratio_formula(ratio_key)

            # Milestone 4.3B / Step 5: bir oran average_* bağımlıysa,
            # nihai reliability BASE (kaynak-modu) ile AVERAGE'IN kendi
            # reliability'sinin (two_period_average="high" / ending_
            # balance_fallback="medium") DAHA DÜŞÜK olanıdır (Bölüm 8).
            average_fact_key = _RATIO_TO_AVERAGE_FACT.get(ratio_key)
            calculation_basis: str | None = None
            if average_fact_key is not None and average_fact_key in average_meta:
                average_reliability, calculation_basis = average_meta[average_fact_key]
                reliability = _worse_reliability(base_reliability, average_reliability)
            else:
                reliability = base_reliability

            if ratio_key == "sustainable_growth_rate":
                # Milestone 4.3B / Step 8: HER ZAMAN not_calculable --
                # compute_registered_ratio HİÇ ÇAĞRILMAZ (Bölüm 2.6).
                outcome = _sustainable_growth_rate_not_calculable_outcome(metadata)
            elif ratio_key == "fixed_charge_coverage":
                # Milestone 4.3B / Step 3 düzeltmesi: HER ZAMAN not_calculable.
                outcome = _fixed_charge_coverage_not_calculable_outcome(metadata)
            elif metadata is not None and metadata.engine_dependency is not None:
                # Milestone 4.3B / Step 9: engine_dependency dolu (ör. Nakit
                # Akışı kategorisi) -- ilgili motor bu fazda YOK.
                outcome = _engine_dependency_not_calculable_outcome(metadata)
            elif (
                metadata is not None
                and metadata.direct_document_only_fields
                and balance_sheet_result is not None
                and balance_sheet_result.get("source_mode") != "direct_document"
            ):
                outcome = _not_applicable_outcome(metadata)
            else:
                outcome = compute_registered_ratio(ratio_key, facts, reliability=reliability)
                if ratio_key == "effective_tax_rate":
                    outcome = _apply_effective_tax_rate_range_check(outcome)

            # Milestone 4.3B (Bölüm 3.2, madde 3): her oran hesaplandığında
            # KENDİ key'iyle facts dict'e enjekte edilir -- bağımlı oranlar
            # (ör. return_on_invested_capital -> effective_tax_rate,
            # Bölüm 9 Step 6'daki Faaliyet zinciri) bunu SIRADAN bir
            # facts-alanı gibi okuyabilir.
            facts[ratio_key] = outcome.value
            if ratio_key == "effective_tax_rate" and outcome.value is not None:
                # ROIC'in "(1 - effective_tax_rate)" çarpanı -- Bölüm 3.5.
                facts["one_minus_effective_tax_rate"] = Decimal("1") - outcome.value

            ratios[ratio_key] = {
                "value": decimal_to_json_safe(outcome.value),
                "unit": metadata.unit if metadata is not None else None,
                "status": outcome.status.value,
                "reliability": outcome.reliability,
                "missing_inputs": list(outcome.missing_inputs),
                "warnings": list(outcome.warnings),
            }
            # Milestone 4.3B / Step 5 (2. tur onay karar #4): average_*
            # bağımlı oranlarda `calculation_basis` HER ZAMAN açıkça
            # görünür ("two_period_average"/"ending_balance_fallback"/
            # "not_calculable") -- warning ÜRETİLMEZ, yalnızca bu alan.
            if calculation_basis is not None:
                ratios[ratio_key]["calculation_basis"] = calculation_basis

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
            "quick_assets": decimal_to_json_safe(facts.get("quick_assets")),
            "days_in_period": decimal_to_json_safe(facts.get("days_in_period")),
            "capital_employed": decimal_to_json_safe(facts.get("capital_employed")),
            "invested_capital": decimal_to_json_safe(facts.get("invested_capital")),
        },
        "warnings": warnings,
        "calculation_provenance": provenance_list_to_dict_extended(all_provenance),
    }
