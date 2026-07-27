"""
Milestone 4.3E (Credit Score Engine) -- Adım 2: `CREDIT_RATIO_SCORE_
WEIGHTS`, `CREDIT_CATEGORY_WEIGHT_PROFILES`, `CREDIT_HARD_FAIL_RULES`,
`CREDIT_CRITICAL_OVERRIDE_RULES`, `CREDIT_BANKING_LENS_SIGNAL_RULES`'ın
gerçek kayıtları.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3E_CREDIT_SCORE_
ENGINE_DESIGN.md Bölüm 5.2/7/8/9/10/13.1/16 (2. tur onay, 15 bağlayıcı
karar).

Bu modül `app/engines/common/health_score_registry.py`'nin (4.3D) AYNI
disipliniyle yazılmıştır: `register_*` fonksiyonları KAYIT ANINDA
doğrular, çalışma zamanında sessizce yanlış üretmez. sqlalchemy/fastapi/
pydantic'e SIFIR bağımlı.

**ÖNEMLİ FARK (Bölüm 3/5.1):** Credit Score'un `category` alanı,
`BENCHMARK_REGISTRY`'nin NATİF 7-kategorili taksonomisi (liquidity/
leverage/profitability/activity/efficiency/growth/cash_flow) İLE AYNI
DEĞİLDİR -- bankacılık-lensli, YENİDEN GRUPLANMIŞ 6 kategoridir (Bölüm
5.1): `leverage` (Health Score'un `leverage`'ının SERMAYE YAPISI
alt-kümesi) ve `debt_service_capacity` (AYNI `leverage`'ın BORÇ SERVİSİ
alt-kümesi) AYRI kategorilerdir; `profitability`, Health Score'un
`profitability`+`efficiency`'sinin BİRLEŞİMİDİR. Bu yüzden `register_
credit_ratio_score_weight`, Health Score'un `register_ratio_score_
weight`'inin AKSİNE, `weight.category`'nin `BENCHMARK_REGISTRY`'nin natif
kategorisiyle eşleşmesini BEKLEMEZ/DOĞRULAMAZ -- yalnızca `ratio_code`'un
`BENCHMARK_REGISTRY`'de KAYITLI olduğunu doğrular (bir Credit Score
sinyali, benchmarklanabilir bir orandan TÜRETİLMELİDİR).
"""

from decimal import Decimal

from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.credit_score_types import (
    CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
    CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
    BankingLensSignalRule,
    CreditCategoryWeightProfile,
    CreditCriticalOverrideRule,
    CreditHardFailRule,
    CreditRatioScoreWeight,
)
from app.engines.common.health_score_types import normalize_weights

_VALID_ROLES = ("critical", "supporting", "explainability_only")


# --- Bölüm 7: nihai duplicate/derived sınıflandırma (BAĞLAYICI) ---------
#
# "identical_formula": birebir aynı formül.
# "algebraic_complement": muhasebe özdeşliği nedeniyle KESİN cebirsel
#   tümleyen/türev (Bölüm 7.2 -- `debt_to_equity = (1-equity_ratio)/
#   equity_ratio`, standart bilanço denkliğinden TÜRETİLMİŞTİR).
# "reciprocal_via_period_constant": `days_in_period` üzerinden
#   ters-türetilmiş.
_DUPLICATE_RELATIONSHIPS: dict[str, tuple[str, str]] = {
    "working_capital_ratio": ("current_ratio", "identical_formula"),
    "debt_ratio": ("equity_ratio", "algebraic_complement"),
    "financial_leverage_multiplier": ("equity_ratio", "algebraic_complement"),
    "debt_to_equity": ("equity_ratio", "algebraic_complement"),
    "payables_turnover": ("days_payables_outstanding", "reciprocal_via_period_constant"),
    "days_inventory_outstanding": ("inventory_turnover", "reciprocal_via_period_constant"),
    "days_sales_outstanding": ("receivables_turnover", "reciprocal_via_period_constant"),
}

# "summary_signal_normalized": scoring'e DAHİL kalır (excluded DEĞİL) ama
# zaten sayılmış bileşenlerin bir bileşimi olduğu için ağırlığı bilinçli
# olarak DÜŞÜRÜLÜR (cash_conversion_cycle = DIO+DSO-DPO).
_SUMMARY_SIGNAL_RATIOS: dict[str, str] = {
    "cash_conversion_cycle": "summary_signal_normalized",
}

# Hangi scored oranların "critical" (Bölüm 9/10 tetikleyicisi
# olabilecek), hangilerinin "supporting" (yalnızca kategori ortalaması)
# olduğu -- Bölüm 6/5.2 ile TAM eşleşir.
_CRITICAL_RATIO_CODES: frozenset[str] = frozenset({
    "current_ratio", "equity_ratio", "interest_coverage_ratio",
    "net_profit_margin", "cash_conversion_cycle",
})

# Her kategorinin ham ağırlığı (raw_weight) -- 0 olanlar Bölüm 7'nin
# duplicate/derived sınıflandırması, diğerleri v1 eşit-tabanlı ağırlık
# (cash_conversion_cycle hariç, bkz. yukarısı). Bölüm 5.2 ile BİREBİR
# aynı envanter.
_CATEGORY_RAW_WEIGHTS: dict[str, dict[str, Decimal]] = {
    "liquidity": {
        "current_ratio": Decimal("1"),
        "working_capital_ratio": Decimal("0"),
        "quick_ratio": Decimal("1"),
        "cash_ratio": Decimal("1"),
        "defensive_interval_ratio": Decimal("1"),
        "working_capital_to_total_assets": Decimal("1"),
    },
    "leverage": {
        "equity_ratio": Decimal("1"),
        "debt_ratio": Decimal("0"),
        "financial_leverage_multiplier": Decimal("0"),
        "debt_to_equity": Decimal("0"),
        "long_term_debt_to_equity": Decimal("1"),
        "short_term_debt_ratio": Decimal("1"),
    },
    "debt_service_capacity": {
        "interest_coverage_ratio": Decimal("1"),
        "ebitda_coverage_ratio": Decimal("1"),
        "debt_to_ebitda": Decimal("1"),
    },
    "profitability": {
        "gross_profit_margin": Decimal("1"),
        "operating_profit_margin": Decimal("1"),
        "net_profit_margin": Decimal("1"),
        "ebit_margin": Decimal("1"),
        "ebitda_margin": Decimal("1"),
        "pretax_profit_margin": Decimal("1"),
        "return_on_capital_employed": Decimal("1"),
        "effective_tax_rate": Decimal("1"),
        "return_on_invested_capital": Decimal("1"),
        "return_on_assets": Decimal("1"),
        "return_on_equity": Decimal("1"),
        "operating_expense_ratio": Decimal("1"),
        "cost_of_sales_ratio": Decimal("1"),
        "overhead_ratio": Decimal("1"),
        "ebit_to_opex": Decimal("1"),
        "non_operating_income_dependency": Decimal("1"),
        "financing_expense_to_sales": Decimal("1"),
    },
    "activity": {
        "asset_turnover": Decimal("1"),
        "inventory_turnover": Decimal("1"),
        "receivables_turnover": Decimal("1"),
        "payables_turnover": Decimal("0"),
        "fixed_asset_turnover": Decimal("1"),
        "working_capital_turnover": Decimal("1"),
        "days_inventory_outstanding": Decimal("0"),
        "days_sales_outstanding": Decimal("0"),
        "days_payables_outstanding": Decimal("1"),
        "cash_conversion_cycle": Decimal("0.5"),
    },
    "growth": {
        "sales_growth": Decimal("1"),
        "gross_profit_growth": Decimal("1"),
        "ebitda_growth": Decimal("1"),
        "net_profit_growth": Decimal("1"),
        "total_assets_growth": Decimal("1"),
        "equity_growth": Decimal("1"),
    },
    # "cash_flow" karşılığı BİLİNÇLİ OLARAK burada YOK -- kategori
    # ağırlığı Bölüm 8'de yapısal olarak %0 (Cash Flow Engine yok).
}


def _normalize_category_weights(raw_weights: dict[str, Decimal]) -> dict[str, Decimal]:
    if sum(raw_weights.values()) <= 0:
        raise ValueError("Bir kategorinin ham ağırlıklarının toplamı > 0 olmalı.")
    return normalize_weights(raw_weights)


CREDIT_RATIO_SCORE_WEIGHTS: dict[str, CreditRatioScoreWeight] = {}


def register_credit_ratio_score_weight(
    weight: CreditRatioScoreWeight,
    *,
    registry: "dict[str, CreditRatioScoreWeight] | None" = None,
) -> None:
    """
    `CREDIT_RATIO_SCORE_WEIGHTS`'e (veya -- testler için -- verilen izole
    bir `registry` sözlüğüne) bir girdi ekler. `register_ratio_score_
    weight` (health_score_registry.py) ile AYNI "kayıt anında doğrula"
    disiplini -- ANCAK kategori-eşleşme kontrolü BİLEREK YOKTUR (bkz. bu
    modülün docstring'i).
    """

    target_registry = CREDIT_RATIO_SCORE_WEIGHTS if registry is None else registry

    if weight.ratio_code in target_registry:
        raise ValueError(f"ratio_code zaten kayıtlı: {weight.ratio_code!r}")

    if weight.role not in _VALID_ROLES:
        raise ValueError(f"'{weight.ratio_code}': bilinmeyen role {weight.role!r}")

    benchmark_metadata = BENCHMARK_REGISTRY.get(weight.ratio_code)
    if benchmark_metadata is None:
        raise ValueError(
            f"'{weight.ratio_code}', BENCHMARK_REGISTRY'de kayıtlı değil -- "
            "yalnızca benchmarklanabilir oranlar Credit Score'da "
            "ağırlıklandırılabilir."
        )

    if weight.excluded_as_duplicate_of is not None:
        if weight.ratio_weight != 0:
            raise ValueError(
                f"'{weight.ratio_code}': excluded_as_duplicate_of dolu iken "
                "ratio_weight KESİNLİKLE 0 olmalı."
            )
        if weight.role != "explainability_only":
            raise ValueError(
                f"'{weight.ratio_code}': excluded_as_duplicate_of dolu iken "
                "role KESİNLİKLE 'explainability_only' olmalı."
            )
        if weight.duplicate_relationship is None:
            raise ValueError(
                f"'{weight.ratio_code}': excluded_as_duplicate_of dolu iken "
                "duplicate_relationship de dolu olmalı (gerekçe zorunlu)."
            )
        target = target_registry.get(weight.excluded_as_duplicate_of)
        if target is None:
            raise ValueError(
                f"'{weight.ratio_code}': excluded_as_duplicate_of hedefi "
                f"'{weight.excluded_as_duplicate_of}' henüz kayıtlı değil -- "
                "hedef, kendisinden ÖNCE (scored olarak) kayıtlı olmalı."
            )
        if target.ratio_weight <= 0:
            raise ValueError(
                f"'{weight.ratio_code}': excluded_as_duplicate_of hedefi "
                f"'{weight.excluded_as_duplicate_of}' KENDİSİ de bir duplicate "
                "(ratio_weight<=0) -- zincirleme duplicate YASAKTIR."
            )
    else:
        if weight.ratio_weight <= 0:
            raise ValueError(
                f"'{weight.ratio_code}': excluded_as_duplicate_of BOŞ iken "
                "ratio_weight > 0 olmalı (scored bir orandır)."
            )
        if weight.role == "explainability_only":
            raise ValueError(
                f"'{weight.ratio_code}': ratio_weight>0 iken role "
                "'explainability_only' OLAMAZ."
            )

    target_registry[weight.ratio_code] = weight


def _build_credit_ratio_score_weights() -> None:
    for category, raw_weights in _CATEGORY_RAW_WEIGHTS.items():
        normalized = _normalize_category_weights(raw_weights)

        # Geçiş 1: TÜM scored (ratio_weight > 0) girdiler -- duplicate
        # hedefleri, kendilerine bakan duplicate'lerden ÖNCE kayıtlı olsun.
        for ratio_code, ratio_weight in normalized.items():
            if ratio_weight <= 0:
                continue
            role = "critical" if ratio_code in _CRITICAL_RATIO_CODES else "supporting"
            duplicate_relationship = _SUMMARY_SIGNAL_RATIOS.get(ratio_code)
            register_credit_ratio_score_weight(
                CreditRatioScoreWeight(
                    ratio_code=ratio_code,
                    category=category,
                    ratio_weight=ratio_weight,
                    role=role,
                    excluded_as_duplicate_of=None,
                    duplicate_relationship=duplicate_relationship,
                )
            )

        # Geçiş 2: TÜM duplicate (ratio_weight == 0) girdiler.
        for ratio_code, ratio_weight in normalized.items():
            if ratio_weight > 0:
                continue
            target_ratio_code, relationship = _DUPLICATE_RELATIONSHIPS[ratio_code]
            register_credit_ratio_score_weight(
                CreditRatioScoreWeight(
                    ratio_code=ratio_code,
                    category=category,
                    ratio_weight=Decimal("0"),
                    role="explainability_only",
                    excluded_as_duplicate_of=target_ratio_code,
                    duplicate_relationship=relationship,
                )
            )


_build_credit_ratio_score_weights()


def scoreable_ratio_codes_for_category(category: str) -> tuple[str, ...]:
    """Bir kategorideki `ratio_weight>0` (scored) oranlar."""

    return tuple(
        code
        for code, w in CREDIT_RATIO_SCORE_WEIGHTS.items()
        if w.category == category and w.ratio_weight > 0
    )


def excluded_duplicate_ratio_codes_for_category(category: str) -> tuple[str, ...]:
    """Bir kategorideki `ratio_weight==0` (duplicate) oranlar."""

    return tuple(
        code
        for code, w in CREDIT_RATIO_SCORE_WEIGHTS.items()
        if w.category == category and w.ratio_weight == 0
    )


# --- Bölüm 8: v1 GLOBAL kategori ağırlıkları (BAĞLAYICI karar #4) -------

CREDIT_CATEGORY_WEIGHT_PROFILES: dict[tuple[str, "str | None"], CreditCategoryWeightProfile] = {
    ("global", None): CreditCategoryWeightProfile(
        scope="global",
        scope_key=None,
        category_weights={
            "liquidity": Decimal("0.20"),
            "leverage": Decimal("0.25"),
            "debt_service_capacity": Decimal("0.25"),
            "profitability": Decimal("0.15"),
            "activity": Decimal("0.10"),
            "growth": Decimal("0.05"),
        },
    ),
    # Bölüm 16, Onaylanmış Karar #11: industry/company_size/tenant
    # seviyeleri BU TURDA TAMAMEN BOŞ -- yalnızca `resolve_credit_
    # category_weights()`'in çözümleme SIRASI tasarlanır/implemente
    # edilir, gerçek veri KAYDEDİLMEZ (boş placeholder kod YOK).
}

_global_credit_weight_sum = sum(
    CREDIT_CATEGORY_WEIGHT_PROFILES[("global", None)].category_weights.values()
)
if _global_credit_weight_sum != 1:
    raise ValueError(
        f"Global kategori ağırlıklarının toplamı 1 olmalı, bulundu: {_global_credit_weight_sum}"
    )


def resolve_credit_category_weights(
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
    tenant_id: "str | None" = None,
) -> CreditCategoryWeightProfile:
    """
    Bölüm 16: çözümleme sırası `tenant > industry > company_size >
    global`. 4.3E'de yalnızca `global` DOLU olduğu için, üçü de argüman
    olarak kabul edilir ama gerçek bir kayıt bulunamayacağı için HER ZAMAN
    `global`'a düşer.
    """

    if tenant_id is not None:
        profile = CREDIT_CATEGORY_WEIGHT_PROFILES.get(("tenant", tenant_id))
        if profile is not None:
            return profile
    if industry_code is not None:
        profile = CREDIT_CATEGORY_WEIGHT_PROFILES.get(("industry", industry_code))
        if profile is not None:
            return profile
    if company_size_bucket is not None:
        profile = CREDIT_CATEGORY_WEIGHT_PROFILES.get(("company_size", company_size_bucket))
        if profile is not None:
            return profile
    return CREDIT_CATEGORY_WEIGHT_PROFILES[("global", None)]


# --- Bölüm 10: Hard Fail kuralları v1 (BAĞLAYICI karar #7) --------------


def _negative_equity_predicate(ratios: dict, benchmarks: dict) -> bool:
    value = ratios.get("equity_ratio")
    return value is not None and value < 0


def _severe_debt_service_shortfall_predicate(ratios: dict, benchmarks: dict) -> bool:
    value = ratios.get("interest_coverage_ratio")
    return value is not None and value < 0


CREDIT_HARD_FAIL_RULES: tuple[CreditHardFailRule, ...] = (
    CreditHardFailRule(
        rule_code="NEGATIVE_EQUITY",
        predicate=_negative_equity_predicate,
        score_ceiling=Decimal("15"),
        rationale_tr=(
            "Özkaynak negatif -- TTK madde 376 kapsamında 'sermaye "
            "kaybı/borca batıklık' bölgesine işaret eder. Bir bankanın "
            "yeni kredi tahsisi bu durumda tipik olarak İSTİSNAİ/güvence "
            "gerektirir. Diğer kategorilerdeki güçlü performansla "
            "TELAFİ EDİLEMEZ."
        ),
    ),
    CreditHardFailRule(
        rule_code="SEVERE_DEBT_SERVICE_SHORTFALL",
        predicate=_severe_debt_service_shortfall_predicate,
        score_ceiling=Decimal("25"),
        rationale_tr=(
            "Faiz karşılama oranı HESAPLANMIŞ ve NEGATİF -- şirket "
            "faaliyet kârıyla faiz giderini dahi karşılayamıyor. Ciddi "
            "bir borç servis riski sinyalidir, diğer kategorilerle TAM "
            "telafi edilemez."
        ),
    ),
)

for _rule in CREDIT_HARD_FAIL_RULES:
    if _rule.rule_code not in ("NEGATIVE_EQUITY", "SEVERE_DEBT_SERVICE_SHORTFALL"):
        raise ValueError(f"Bilinmeyen hard-fail kuralı: {_rule.rule_code!r}")


# --- Bölüm 9: Critical Override kuralları v1 (BAĞLAYICI karar #6) -------

CREDIT_CRITICAL_OVERRIDE_RULES: tuple[CreditCriticalOverrideRule, ...] = (
    CreditCriticalOverrideRule(
        ratio_code="current_ratio",
        category="liquidity",
        weak_multiplier=CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Temel ödeme gücü sinyali.",
    ),
    CreditCriticalOverrideRule(
        ratio_code="equity_ratio",
        category="leverage",
        weak_multiplier=CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr=(
            "Sermaye yapısının temel sinyali -- hard-fail (Bölüm 10) "
            "EKSTREM (negatif) durumu, bu override ORTA-şiddetli "
            "(weak/critical ama henüz negatif olmayan) durumu yakalar."
        ),
    ),
    CreditCriticalOverrideRule(
        ratio_code="interest_coverage_ratio",
        category="debt_service_capacity",
        weak_multiplier=CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Borç servisi yetersizliği -- Hard Fail Kural 2 ile tamamlayıcı.",
    ),
    CreditCriticalOverrideRule(
        ratio_code="net_profit_margin",
        category="profitability",
        weak_multiplier=CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Temel kârlılık sinyali.",
    ),
    CreditCriticalOverrideRule(
        ratio_code="cash_conversion_cycle",
        category="activity",
        weak_multiplier=CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Çalışma sermayesi/nakit döngüsü sinyali.",
    ),
)

for _override_rule in CREDIT_CRITICAL_OVERRIDE_RULES:
    _weight = CREDIT_RATIO_SCORE_WEIGHTS.get(_override_rule.ratio_code)
    if _weight is None or _weight.ratio_weight <= 0:
        raise ValueError(
            f"Critical override kuralı '{_override_rule.ratio_code}' "
            "scored (ratio_weight>0) bir orana bağlı OLMALI."
        )
    if _weight.role != "critical":
        raise ValueError(
            f"Critical override kuralı '{_override_rule.ratio_code}' "
            f"role='critical' bir orana bağlı OLMALI, bulunan: {_weight.role!r}."
        )
    if _weight.category != _override_rule.category:
        raise ValueError(
            f"Critical override kuralı '{_override_rule.ratio_code}' "
            f"kategorisi ({_override_rule.category!r}) CREDIT_RATIO_SCORE_WEIGHTS "
            f"kategorisiyle ({_weight.category!r}) UYUŞMUYOR."
        )

# Onaylanmış Karar #5/Bölüm 7.2 -- KESİN garanti: `debt_to_equity`
# hiçbir critical-override kuralında YER ALAMAZ (registry kayıt-anı
# doğrulaması).
if any(rule.ratio_code == "debt_to_equity" for rule in CREDIT_CRITICAL_OVERRIDE_RULES):
    raise ValueError(
        "'debt_to_equity', Onaylanmış Karar #5 gereği hiçbir critical "
        "override kuralında YER ALAMAZ."
    )
# Not: `debt_to_equity`'nin HİÇBİR hard-fail predicate'inde
# KULLANILMADIĞI -- predicate'ler yalnızca `equity_ratio`/`interest_
# coverage_ratio` okur (yukarıdaki `_negative_equity_predicate`/
# `_severe_debt_service_shortfall_predicate` kaynak koduyla SABİT,
# ayrıca bkz. Adım 3 testleri).


# --- Bölüm 13.1: BankingLensSignals kuralları (BAĞLAYICI karar #9) ------


def _tier_of(signal: "dict | None") -> "str | None":
    if signal is None:
        return None
    if signal.get("benchmark_status") != "evaluated":
        return None
    return signal.get("tier")


def _short_term_liquidity_strain_predicate(signals: dict) -> "bool | None":
    tier = _tier_of(signals.get("current_ratio"))
    if tier is None:
        return None
    return tier in ("weak", "critical")


def _high_leverage_predicate(signals: dict) -> "bool | None":
    tier = _tier_of(signals.get("equity_ratio"))
    if tier is None:
        return None
    return tier in ("weak", "critical")


def _debt_service_stress_predicate(signals: dict) -> "bool | None":
    signal = signals.get("interest_coverage_ratio")
    if signal is None or signal.get("benchmark_status") != "evaluated":
        return None
    tier = signal.get("tier")
    value = signal.get("ratio_value")
    if tier in ("weak", "critical"):
        return True
    if value is not None and value < 0:
        return True
    return False


def _weak_profit_buffer_predicate(signals: dict) -> "bool | None":
    tier = _tier_of(signals.get("net_profit_margin"))
    if tier is None:
        return None
    return tier in ("weak", "critical")


def _working_capital_strain_predicate(signals: dict) -> "bool | None":
    tier = _tier_of(signals.get("cash_conversion_cycle"))
    if tier is None:
        return None
    return tier in ("weak", "critical")


def _debt_funded_growth_predicate(signals: dict) -> "bool | None":
    total_assets_growth_signal = signals.get("total_assets_growth")
    equity_growth_signal = signals.get("equity_growth")
    if (
        total_assets_growth_signal is None
        or equity_growth_signal is None
        or total_assets_growth_signal.get("benchmark_status") != "evaluated"
        or equity_growth_signal.get("benchmark_status") != "evaluated"
    ):
        return None
    total_assets_growth = total_assets_growth_signal.get("ratio_value")
    equity_growth = equity_growth_signal.get("ratio_value")
    if total_assets_growth is None or equity_growth is None:
        return None
    return total_assets_growth > equity_growth and total_assets_growth > 0


CREDIT_BANKING_LENS_SIGNAL_RULES: tuple[BankingLensSignalRule, ...] = (
    BankingLensSignalRule(
        flag_code="SHORT_TERM_LIQUIDITY_STRAIN",
        category="liquidity",
        rationale_tr="Kısa vadeli ödeme gücü zayıf/kritik bantta.",
        predicate=_short_term_liquidity_strain_predicate,
        text_template_tr="Kısa vadeli ödeme gücü {tier} bantta (current_ratio).",
        missing_input_note_tr=(
            "current_ratio değerlendirilemediği için likidite gerilimi "
            "işareti üretilemedi."
        ),
    ),
    BankingLensSignalRule(
        flag_code="HIGH_LEVERAGE",
        category="leverage",
        rationale_tr="Sermaye yapısı zayıf/kritik bantta.",
        predicate=_high_leverage_predicate,
        text_template_tr="Sermaye yapısı {tier} bantta (equity_ratio).",
        missing_input_note_tr=(
            "equity_ratio değerlendirilemediği için kaldıraç işareti "
            "üretilemedi."
        ),
    ),
    BankingLensSignalRule(
        flag_code="DEBT_SERVICE_STRESS",
        category="debt_service_capacity",
        rationale_tr="Faiz/borç servis karşılama zayıf/kritik bantta veya negatif.",
        predicate=_debt_service_stress_predicate,
        text_template_tr=(
            "Faiz/borç servis karşılama {tier} bantta veya negatif "
            "(interest_coverage_ratio)."
        ),
        missing_input_note_tr=(
            "interest_coverage_ratio değerlendirilemediği için borç "
            "servisi işareti üretilemedi."
        ),
    ),
    BankingLensSignalRule(
        flag_code="WEAK_PROFIT_BUFFER",
        category="profitability",
        rationale_tr="Kârlılık tamponu zayıf/kritik bantta.",
        predicate=_weak_profit_buffer_predicate,
        text_template_tr="Kârlılık tamponu {tier} bantta (net_profit_margin).",
        missing_input_note_tr=(
            "net_profit_margin değerlendirilemediği için kârlılık "
            "tamponu işareti üretilemedi."
        ),
    ),
    BankingLensSignalRule(
        flag_code="WORKING_CAPITAL_STRAIN",
        category="activity",
        rationale_tr="Çalışma sermayesi/nakit döngüsü zayıf/kritik bantta.",
        predicate=_working_capital_strain_predicate,
        text_template_tr=(
            "Çalışma sermayesi/nakit döngüsü {tier} bantta "
            "(cash_conversion_cycle)."
        ),
        missing_input_note_tr=(
            "cash_conversion_cycle değerlendirilemediği için çalışma "
            "sermayesi işareti üretilemedi."
        ),
    ),
    BankingLensSignalRule(
        flag_code="DEBT_FUNDED_GROWTH",
        category="growth",
        rationale_tr=(
            "Toplam varlık büyümesi özkaynak büyümesinin üzerinde -- "
            "büyümenin borçla finanse edilmiş olma olasılığı."
        ),
        predicate=_debt_funded_growth_predicate,
        text_template_tr=(
            "Toplam varlık büyümesi (%{total_assets_growth}) özkaynak "
            "büyümesinin (%{equity_growth}) üzerinde -- büyümenin borçla "
            "finanse edilmiş olma olasılığı."
        ),
        missing_input_note_tr=(
            "total_assets_growth/equity_growth değerlendirilemediği için "
            "borçla finanse büyüme işareti üretilemedi."
        ),
    ),
)

_EXPECTED_FLAG_CODES = frozenset({
    "SHORT_TERM_LIQUIDITY_STRAIN", "HIGH_LEVERAGE", "DEBT_SERVICE_STRESS",
    "WEAK_PROFIT_BUFFER", "WORKING_CAPITAL_STRAIN", "DEBT_FUNDED_GROWTH",
})
if {r.flag_code for r in CREDIT_BANKING_LENS_SIGNAL_RULES} != _EXPECTED_FLAG_CODES:
    raise ValueError("CREDIT_BANKING_LENS_SIGNAL_RULES beklenen 6 bayrağı TAM karşılamıyor.")
