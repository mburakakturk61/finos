"""
Milestone 4.3D (Financial Health Score) -- Adım 2: `RATIO_SCORE_WEIGHTS`,
`CATEGORY_WEIGHT_PROFILES`, `HARD_FAIL_RULES`, `CRITICAL_OVERRIDE_RULES`'ın
gerçek kayıtları.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3D_FINANCIAL_HEALTH_
SCORE_DESIGN.md Bölüm 8/8.1/8.2/12/13 (4. tur, 18 bağlayıcı karar).

Bu modül `app/engines/common/benchmark_registry.py`'nin (4.3C) AYNI
disipliniyle yazılmıştır: `register_*` fonksiyonları KAYIT ANINDA
doğrular, çalışma zamanında sessizce yanlış üretmez. sqlalchemy/fastapi/
pydantic'e SIFIR bağımlı.
"""

from decimal import Decimal

from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.health_score_types import (
    CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
    CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
    CategoryWeightProfile,
    CriticalOverrideRule,
    HardFailRule,
    RatioScoreWeight,
    normalize_weights,
)


# --- Bölüm 8.1: nihai duplicate/derived sınıflandırma (BAĞLAYICI) -------
#
# "identical_formula": birebir aynı formül.
# "algebraic_complement": muhasebe özdeşliği nedeniyle KESİN cebirsel
#   tümleyen/türev (korelasyon DEĞİL, tam belirlenim).
# "reciprocal_via_period_constant": `days_in_period` (dönem-sabiti)
#   üzerinden ters-türetilmiş (`gün = days_in_period / devir_hızı`).
_DUPLICATE_RELATIONSHIPS: dict[str, tuple[str, str]] = {
    "working_capital_ratio": ("current_ratio", "identical_formula"),
    "debt_ratio": ("equity_ratio", "algebraic_complement"),
    "financial_leverage_multiplier": ("equity_ratio", "algebraic_complement"),
    "days_inventory_outstanding": ("inventory_turnover", "reciprocal_via_period_constant"),
    "days_sales_outstanding": ("receivables_turnover", "reciprocal_via_period_constant"),
    "payables_turnover": ("days_payables_outstanding", "reciprocal_via_period_constant"),
}

# "summary_signal_normalized": scoring'e DAHİL kalır (excluded DEĞİL) ama
# zaten sayılmış bileşenlerin bir bileşimi olduğu için ağırlığı bilinçli
# olarak DÜŞÜRÜLÜR (Bölüm 8.1 -- cash_conversion_cycle = DIO+DSO-DPO).
_SUMMARY_SIGNAL_RATIOS: dict[str, str] = {
    "cash_conversion_cycle": "summary_signal_normalized",
}

# Her kategorinin BENCHMARK_REGISTRY'deki TÜM oranları için ham ağırlık
# (raw_weight) -- 0 olanlar Bölüm 8.1'in duplicate/derived sınıflandırması,
# diğerleri v1 eşit-tabanlı ağırlık (cash_conversion_cycle hariç, bkz.
# yukarısı). Kayıt SIRASI ÖNEMLİ DEĞİL -- `_build_ratio_score_weights`
# önce TÜM pozitif (scored) girdileri, SONRA TÜM sıfır (duplicate) girdileri
# kaydeder (bkz. aşağısı) -- bu yüzden "hedef önce kayıtlı olmalı" kuralı
# hiçbir el-ile-sıralama gerektirmeden doğal olarak sağlanır.
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
        "debt_ratio": Decimal("0"),
        "equity_ratio": Decimal("1"),
        "debt_to_equity": Decimal("1"),
        "long_term_debt_to_equity": Decimal("1"),
        "short_term_debt_ratio": Decimal("1"),
        "financial_leverage_multiplier": Decimal("0"),
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
    "efficiency": {
        "operating_expense_ratio": Decimal("1"),
        "cost_of_sales_ratio": Decimal("1"),
        "overhead_ratio": Decimal("1"),
        "ebit_to_opex": Decimal("1"),
        "non_operating_income_dependency": Decimal("1"),
        "financing_expense_to_sales": Decimal("1"),
    },
    "growth": {
        "sales_growth": Decimal("1"),
        "gross_profit_growth": Decimal("1"),
        "ebitda_growth": Decimal("1"),
        "net_profit_growth": Decimal("1"),
        "total_assets_growth": Decimal("1"),
        "equity_growth": Decimal("1"),
    },
    # "cash_flow" BİLİNÇLİ OLARAK burada YOK -- kategori ağırlığı Bölüm
    # 8'de yapısal olarak %0 (Cash Flow Engine yok), hiçbir oranı
    # BENCHMARK_REGISTRY'de zaten kayıtlı değil (her zaman
    # benchmark_not_registered).
}


def _normalize_category_weights(raw_weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """
    Bölüm 11 (kategori-içi oran ağırlıkları) kararının, KAYIT ANINDAKİ
    (registry inşası) uygulaması -- `app.engines.common.health_score_
    types.normalize_weights`'in ince bir sarmalayıcısı: burada, tüm ham
    ağırlıkların toplamının `0`'ın altında/eşit olması bir REGISTRY
    TANIM HATASIDIR (çalışma zamanındaki "sıfır EVALUATED oran" geçerli
    iş durumundan FARKLI olarak) -- bu yüzden `normalize_weights`'in
    "sessizce tüm sıfır döndür" davranışı YERİNE burada AÇIKÇA
    `ValueError` fırlatılır.
    """

    if sum(raw_weights.values()) <= 0:
        raise ValueError("Bir kategorinin ham ağırlıklarının toplamı > 0 olmalı.")
    return normalize_weights(raw_weights)


RATIO_SCORE_WEIGHTS: dict[str, RatioScoreWeight] = {}


def register_ratio_score_weight(
    weight: RatioScoreWeight,
    *,
    registry: "dict[str, RatioScoreWeight] | None" = None,
) -> None:
    """
    `RATIO_SCORE_WEIGHTS`'e (veya -- testler için -- verilen izole bir
    `registry` sözlüğüne) bir girdi ekler. `register_benchmark`
    (benchmark_types.py) ile AYNI "kayıt anında doğrula" disiplini.
    `registry=None` iken gerçek, modül-seviyeli `RATIO_SCORE_WEIGHTS`
    kullanılır (varsayılan/gerçek davranış).
    """

    target_registry = RATIO_SCORE_WEIGHTS if registry is None else registry

    if weight.ratio_code in target_registry:
        raise ValueError(f"ratio_code zaten kayıtlı: {weight.ratio_code!r}")

    benchmark_metadata = BENCHMARK_REGISTRY.get(weight.ratio_code)
    if benchmark_metadata is None:
        raise ValueError(
            f"'{weight.ratio_code}', BENCHMARK_REGISTRY'de kayıtlı değil -- "
            "yalnızca benchmarklanabilir oranlar Health Score'da "
            "ağırlıklandırılabilir."
        )
    if benchmark_metadata.category != weight.category:
        raise ValueError(
            f"'{weight.ratio_code}' kategorisi ({weight.category!r}), "
            f"BENCHMARK_REGISTRY'deki kategoriyle ({benchmark_metadata.category!r}) "
            "UYUŞMUYOR."
        )

    if weight.excluded_as_duplicate_of is not None:
        if weight.ratio_weight != 0:
            raise ValueError(
                f"'{weight.ratio_code}': excluded_as_duplicate_of dolu iken "
                "ratio_weight KESİNLİKLE 0 olmalı."
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
    elif weight.ratio_weight <= 0:
        raise ValueError(
            f"'{weight.ratio_code}': excluded_as_duplicate_of BOŞ iken "
            "ratio_weight > 0 olmalı (scored bir orandır)."
        )

    target_registry[weight.ratio_code] = weight


def _build_ratio_score_weights() -> None:
    for category, raw_weights in _CATEGORY_RAW_WEIGHTS.items():
        normalized = _normalize_category_weights(raw_weights)

        # Geçiş 1: TÜM scored (ratio_weight > 0) girdiler -- duplicate
        # hedefleri, kendilerine bakan duplicate'lerden ÖNCE kayıtlı olsun.
        for ratio_code, ratio_weight in normalized.items():
            if ratio_weight <= 0:
                continue
            duplicate_relationship = _SUMMARY_SIGNAL_RATIOS.get(ratio_code)
            register_ratio_score_weight(
                RatioScoreWeight(
                    ratio_code=ratio_code,
                    category=category,
                    ratio_weight=ratio_weight,
                    excluded_as_duplicate_of=None,
                    duplicate_relationship=duplicate_relationship,
                )
            )

        # Geçiş 2: TÜM duplicate (ratio_weight == 0) girdiler -- hedefleri
        # artık kayıtlı.
        for ratio_code, ratio_weight in normalized.items():
            if ratio_weight > 0:
                continue
            target_ratio_code, relationship = _DUPLICATE_RELATIONSHIPS[ratio_code]
            register_ratio_score_weight(
                RatioScoreWeight(
                    ratio_code=ratio_code,
                    category=category,
                    ratio_weight=Decimal("0"),
                    excluded_as_duplicate_of=target_ratio_code,
                    duplicate_relationship=relationship,
                )
            )


_build_ratio_score_weights()


def scoreable_ratio_codes_for_category(category: str) -> tuple[str, ...]:
    """Bölüm 0.1: bir kategorideki `ratio_weight>0` (scored) oranlar."""

    return tuple(
        code
        for code, w in RATIO_SCORE_WEIGHTS.items()
        if w.category == category and w.ratio_weight > 0
    )


def excluded_duplicate_ratio_codes_for_category(category: str) -> tuple[str, ...]:
    """Bölüm 0.1: bir kategorideki `ratio_weight==0` (duplicate) oranlar."""

    return tuple(
        code
        for code, w in RATIO_SCORE_WEIGHTS.items()
        if w.category == category and w.ratio_weight == 0
    )


# --- Bölüm 8: v1 GLOBAL kategori ağırlıkları (BAĞLAYICI karar #7) -------

CATEGORY_WEIGHT_PROFILES: dict[tuple[str, "str | None"], CategoryWeightProfile] = {
    ("global", None): CategoryWeightProfile(
        scope="global",
        scope_key=None,
        category_weights={
            "liquidity": Decimal("0.20"),
            "leverage": Decimal("0.25"),
            "profitability": Decimal("0.20"),
            "activity": Decimal("0.15"),
            "efficiency": Decimal("0.10"),
            "growth": Decimal("0.10"),
        },
    ),
    # Bölüm 8.2, Bölüm 22 karar #17: industry/company_size/tenant
    # seviyeleri BU TURDA TAMAMEN BOŞ -- yalnızca `resolve_category_
    # weights()`'in çözümleme SIRASI (aşağısı) tasarlanır/implemente
    # edilir, gerçek veri KAYDEDİLMEZ (boş placeholder kod YOK).
}

_global_weight_sum = sum(CATEGORY_WEIGHT_PROFILES[("global", None)].category_weights.values())
if _global_weight_sum != 1:
    raise ValueError(
        f"Global kategori ağırlıklarının toplamı 1 olmalı, bulundu: {_global_weight_sum}"
    )


def resolve_category_weights(
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
    tenant_id: "str | None" = None,
) -> CategoryWeightProfile:
    """
    Bölüm 8.2: çözümleme sırası `tenant > industry > company_size >
    global`. 4.3D'de yalnızca `global` DOLU olduğu için, üçü de argüman
    olarak kabul edilir ama gerçek bir kayıt bulunamayacağı için HER ZAMAN
    `global`'a düşer -- Benchmark Engine'in `industry > company_size >
    default` deseniyle UYUMLU, `tenant` onun ÜZERİNE eklenen en spesifik
    (ve bu fazda tamamen boş) katman.
    """

    if tenant_id is not None:
        profile = CATEGORY_WEIGHT_PROFILES.get(("tenant", tenant_id))
        if profile is not None:
            return profile
    if industry_code is not None:
        profile = CATEGORY_WEIGHT_PROFILES.get(("industry", industry_code))
        if profile is not None:
            return profile
    if company_size_bucket is not None:
        profile = CATEGORY_WEIGHT_PROFILES.get(("company_size", company_size_bucket))
        if profile is not None:
            return profile
    return CATEGORY_WEIGHT_PROFILES[("global", None)]


# --- Bölüm 12: Hard Fail kuralları v1 (BAĞLAYICI karar #4/#5/#9) --------


def _negative_equity_predicate(ratios: dict, benchmarks: dict) -> bool:
    value = ratios.get("equity_ratio")
    return value is not None and value < 0


def _severe_debt_service_shortfall_predicate(ratios: dict, benchmarks: dict) -> bool:
    value = ratios.get("interest_coverage_ratio")
    return value is not None and value < 0


HARD_FAIL_RULES: tuple[HardFailRule, ...] = (
    HardFailRule(
        rule_code="NEGATIVE_EQUITY",
        predicate=_negative_equity_predicate,
        score_ceiling=Decimal("25"),
        rationale_tr=(
            "Özkaynak negatif -- TTK madde 376 kapsamında 'sermaye "
            "kaybı/borca batıklık' bölgesine işaret eder. Diğer "
            "kategorilerdeki güçlü performansla TELAFİ EDİLEMEZ."
        ),
    ),
    HardFailRule(
        rule_code="SEVERE_DEBT_SERVICE_SHORTFALL",
        predicate=_severe_debt_service_shortfall_predicate,
        score_ceiling=Decimal("35"),
        rationale_tr=(
            "Faiz karşılama oranı HESAPLANMIŞ ve NEGATİF -- şirket "
            "faaliyet kârıyla faiz giderini dahi karşılayamıyor. Ciddi "
            "bir borç servis riski sinyalidir, diğer kategorilerle TAM "
            "telafi edilemez."
        ),
    ),
)

for _rule in HARD_FAIL_RULES:
    if _rule.rule_code not in ("NEGATIVE_EQUITY", "SEVERE_DEBT_SERVICE_SHORTFALL"):
        raise ValueError(f"Bilinmeyen hard-fail kuralı: {_rule.rule_code!r}")


# --- Bölüm 13: Critical Override kuralları v1 (BAĞLAYICI karar #10) -----

CRITICAL_OVERRIDE_RULES: tuple[CriticalOverrideRule, ...] = (
    CriticalOverrideRule(
        ratio_code="current_ratio",
        category="liquidity",
        weak_multiplier=CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Temel ödeme gücü sinyali.",
    ),
    CriticalOverrideRule(
        ratio_code="debt_to_equity",
        category="leverage",
        weak_multiplier=CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Klasik kaldıraç red flag'i.",
    ),
    CriticalOverrideRule(
        ratio_code="interest_coverage_ratio",
        category="leverage",
        weak_multiplier=CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Borç servisi yetersizliği -- Hard Fail Kural 2 ile tamamlayıcı, kesişmeyen erken-uyarı sinyali.",
    ),
    CriticalOverrideRule(
        ratio_code="net_profit_margin",
        category="profitability",
        weak_multiplier=CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="Temel kârlılık sinyali.",
    ),
    CriticalOverrideRule(
        ratio_code="cash_conversion_cycle",
        category="activity",
        weak_multiplier=CRITICAL_OVERRIDE_WEAK_MULTIPLIER,
        critical_multiplier=CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER,
        rationale_tr="CCC scored bir sinyal olduğu için activity kategorisinin critical-override temsilcisi.",
    ),
)

for _override_rule in CRITICAL_OVERRIDE_RULES:
    _weight = RATIO_SCORE_WEIGHTS.get(_override_rule.ratio_code)
    if _weight is None or _weight.ratio_weight <= 0:
        raise ValueError(
            f"Critical override kuralı '{_override_rule.ratio_code}' "
            "scored (ratio_weight>0) bir orana bağlı OLMALI."
        )
    if _weight.category != _override_rule.category:
        raise ValueError(
            f"Critical override kuralı '{_override_rule.ratio_code}' "
            f"kategorisi ({_override_rule.category!r}) RATIO_SCORE_WEIGHTS "
            f"kategorisiyle ({_weight.category!r}) UYUŞMUYOR."
        )
