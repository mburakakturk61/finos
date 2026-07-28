"""
Milestone 4.3F (Recommendation Engine) -- Adım 2: `RECOMMENDATION_RULES`
(39 kural, Bölüm 20a) + diğer registry'lerin (`RECOMMENDATION_CATEGORY_
WEIGHT_PROFILES`/`RECOMMENDATION_CONFLICT_PAIRS`/`RECOMMENDATION_
MUTUALLY_EXCLUSIVE_GROUPS`/`BANKING_FLAG_TO_RATIO_OVERLAP`/
`RECOMMENDATION_INPUT_COMPATIBILITY`) gerçek kayıtları + 8 kapalı,
deklaratif strateji fonksiyonu (Bölüm 8.0).

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3F_RECOMMENDATION_
ENGINE_DESIGN.md Bölüm 8/13/14/16/17/18/20a/20b (son onay turu, Bölüm 33
"Onaylanmış Kararlar" + Bölüm 37 "Nihai Rapor").

**ZORUNLU import sırası (Bölüm 1.6):** bu modül `app.engines.common.
credit_score_registry`'den SONRA, HER ZAMAN EN SON import edilir --
yalnızca doğrulama amaçlı (hard_fail_code/banking_lens_flag katalog
kontrolü) `recommendation_types`'daki BİLİNEN sabit kümeleri kullanır,
`health_score_registry`/`credit_score_registry`'yi GERİYE DOĞRU
İMPORT ETMEZ (döngüsel import riski YAPISAL olarak yoktur).

`register_recommendation_rule` KAYIT ANINDA doğrular (Bölüm 8.2'nin 12
maddesi), çalışma zamanında sessizce yanlış üretmez -- mevcut `app/
engines/common/**` disipliniyle TUTARLI. sqlalchemy/fastapi/pydantic'e
SIFIR bağımlı.
"""

from decimal import Decimal
from typing import Any

from app.engines.common.ratio_formulas import RATIO_REGISTRY
from app.engines.common.recommendation_types import (
    CATEGORY_COVERAGE_GATE_THRESHOLD,
    KNOWN_BANKING_LENS_FLAGS,
    KNOWN_BENCHMARK_TIERS,
    KNOWN_CREDIT_SCORE_DATA_GAP_CODES,
    KNOWN_HARD_FAIL_CODES,
    EvidenceRule,
    RecommendationCategory,
    RecommendationCategoryWeightProfile,
    RecommendationDifficultyBand,
    RecommendationImpactBand,
    RecommendationMutuallyExclusiveGroup,
    RecommendationPriority,
    RecommendationRule,
    RecommendationSeverity,
    RecommendationTriggerStrategy,
    ResultBucket,
    category_to_result_bucket,
    resolve_disclaimer_tr,
)
from app.engines.common.health_score_types import normalize_weights


# --- Bölüm 18.1: gerçek 48 benchmark sinyalinin kategorilere dağılımı ---
# (register_recommendation_rule madde 2'nin çapraz doğrulama girdisi)

CATEGORY_RATIO_MAP: "dict[str, str]" = {}


def _register_category_ratios(category: str, ratio_codes: "tuple[str, ...]") -> None:
    for ratio_code in ratio_codes:
        CATEGORY_RATIO_MAP[ratio_code] = category


_register_category_ratios(
    RecommendationCategory.LIQUIDITY.value,
    (
        "current_ratio",
        "working_capital_ratio",
        "quick_ratio",
        "cash_ratio",
        "defensive_interval_ratio",
        "working_capital_to_total_assets",
    ),
)
_register_category_ratios(
    RecommendationCategory.WORKING_CAPITAL.value,
    (
        "days_sales_outstanding",
        "receivables_turnover",
        "days_inventory_outstanding",
        "inventory_turnover",
        "days_payables_outstanding",
        "payables_turnover",
        "cash_conversion_cycle",
        "working_capital_turnover",
    ),
)
_register_category_ratios(
    RecommendationCategory.LEVERAGE.value,
    (
        "debt_ratio",
        "equity_ratio",
        "debt_to_equity",
        "long_term_debt_to_equity",
        "short_term_debt_ratio",
        "financial_leverage_multiplier",
        "interest_coverage_ratio",
        "ebitda_coverage_ratio",
        "debt_to_ebitda",
    ),
)
_register_category_ratios(
    RecommendationCategory.PROFITABILITY.value,
    (
        "gross_profit_margin",
        "operating_profit_margin",
        "net_profit_margin",
        "ebit_margin",
        "ebitda_margin",
        "pretax_profit_margin",
        "return_on_capital_employed",
        "effective_tax_rate",
        "return_on_invested_capital",
        "return_on_assets",
        "return_on_equity",
        "operating_expense_ratio",
        "cost_of_sales_ratio",
        "overhead_ratio",
        "ebit_to_opex",
        "non_operating_income_dependency",
        "financing_expense_to_sales",
    ),
)
_register_category_ratios(
    RecommendationCategory.ACTIVITY.value,
    ("asset_turnover", "fixed_asset_turnover"),
)
_register_category_ratios(
    RecommendationCategory.GROWTH.value,
    (
        "sales_growth",
        "gross_profit_growth",
        "ebitda_growth",
        "net_profit_growth",
        "total_assets_growth",
        "equity_growth",
    ),
)


# --- Bölüm 8.0: 8 kapalı, saf, kayıtlı strateji fonksiyonu ---------------


def _evaluate_single_evidence_rule(evidence_rule: EvidenceRule, context: "dict[str, Any]") -> bool:
    """
    TEK bir `EvidenceRule`'un context üzerinde SAF değerlendirmesi --
    yan etkisiz, eval/exec İÇERMEZ, `context`'i MUTASYONA UĞRATMAZ.
    """

    signals = context["signals"]

    if evidence_rule.ratio_code is not None:
        signal = signals.get(evidence_rule.ratio_code)
        if signal is None or evidence_rule.tier_in is None:
            return False
        return signal.get("tier") in evidence_rule.tier_in

    if evidence_rule.hard_fail_code is not None:
        return (
            evidence_rule.hard_fail_code in context["health_score_hard_fails"]
            or evidence_rule.hard_fail_code in context["credit_score_hard_fails"]
        )

    if evidence_rule.critical_override_ratio_code is not None:
        return (
            evidence_rule.critical_override_ratio_code in context["health_score_critical_overrides"]
            or evidence_rule.critical_override_ratio_code in context["credit_score_critical_overrides"]
        )

    if evidence_rule.banking_lens_flag is not None:
        return evidence_rule.banking_lens_flag in context["banking_lens_flags"]

    if evidence_rule.category_coverage_below is not None:
        category_value = evidence_rule.category_coverage_below.value
        coverage = context["category_coverage"].get(category_value)
        threshold = (
            evidence_rule.coverage_threshold
            if evidence_rule.coverage_threshold is not None
            else CATEGORY_COVERAGE_GATE_THRESHOLD
        )
        if coverage is None:
            return False
        return coverage < threshold

    if evidence_rule.credit_score_data_gap_code is not None:
        return evidence_rule.credit_score_data_gap_code in context["credit_score_data_gaps"]

    return False


def all_conditions(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """HER `evidence_rule` TRUE olmalı."""

    return all(_evaluate_single_evidence_rule(er, context) for er in evidence_rules)


def any_condition(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """EN AZ bir `evidence_rule` TRUE olmalı."""

    return any(_evaluate_single_evidence_rule(er, context) for er in evidence_rules)


def minimum_evidence(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """EN AZ `minimum_evidence_count` tanesi TRUE olmalı."""

    count = sum(1 for er in evidence_rules if _evaluate_single_evidence_rule(er, context))
    return count >= minimum_evidence_count


def debt_funded_growth(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """`banking_lens_flag=="DEBT_FUNDED_GROWTH"` kontrolüne özel-adlı sarmalayıcı."""

    return all_conditions(evidence_rules, context)


def hard_fail_present(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """`hard_fail_code` kontrolüne özel-adlı sarmalayıcı."""

    return all_conditions(evidence_rules, context)


def banking_flag_present(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """`banking_lens_flag` kontrolüne özel-adlı sarmalayıcı."""

    return all_conditions(evidence_rules, context)


def data_coverage_gap(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """`category_coverage_below` kontrolü (DATA_QUALITY)."""

    return all_conditions(evidence_rules, context)


def data_gap_present(
    evidence_rules: "tuple[EvidenceRule, ...]",
    context: "dict[str, Any]",
    *,
    minimum_evidence_count: int = 1,
) -> bool:
    """`credit_score_data_gap_code` kontrolü (DATA_QUALITY)."""

    return all_conditions(evidence_rules, context)


TRIGGER_STRATEGY_FUNCTIONS: "dict[str, Any]" = {
    RecommendationTriggerStrategy.ALL_CONDITIONS.value: all_conditions,
    RecommendationTriggerStrategy.ANY_CONDITION.value: any_condition,
    RecommendationTriggerStrategy.MINIMUM_EVIDENCE.value: minimum_evidence,
    RecommendationTriggerStrategy.DEBT_FUNDED_GROWTH.value: debt_funded_growth,
    RecommendationTriggerStrategy.HARD_FAIL_PRESENT.value: hard_fail_present,
    RecommendationTriggerStrategy.BANKING_FLAG_PRESENT.value: banking_flag_present,
    RecommendationTriggerStrategy.DATA_COVERAGE_GAP.value: data_coverage_gap,
    RecommendationTriggerStrategy.DATA_GAP_PRESENT.value: data_gap_present,
}


def evaluate_rule_eligibility(rule: RecommendationRule, context: "dict[str, Any]") -> bool:
    """Bölüm 12 Aşama 6 -- kapalı strateji dispatch'i (eval/exec YOK)."""

    strategy_fn = TRIGGER_STRATEGY_FUNCTIONS[rule.trigger_strategy.value]
    return strategy_fn(
        rule.evidence_rules, context, minimum_evidence_count=rule.minimum_evidence_count
    )


# --- Bölüm 8.2: kayıt anında doğrulama -----------------------------------

_VALID_COVERAGE_POLICIES = ("subject_to_gate", "exempt_hard_fail", "always_evaluated")
_VALID_DISCLAIMER_SCOPES = ("general", "banking")
_VALID_TRIGGER_MODES = ("all", "any")


def _validate_evidence_rule(evidence_rule: EvidenceRule, rule_code: str) -> None:
    filled_fields = [
        name
        for name, value in (
            ("ratio_code", evidence_rule.ratio_code),
            ("hard_fail_code", evidence_rule.hard_fail_code),
            ("critical_override_ratio_code", evidence_rule.critical_override_ratio_code),
            ("banking_lens_flag", evidence_rule.banking_lens_flag),
            ("category_coverage_below", evidence_rule.category_coverage_below),
            ("credit_score_data_gap_code", evidence_rule.credit_score_data_gap_code),
        )
        if value is not None
    ]
    if len(filled_fields) != 1:
        raise ValueError(
            f"'{rule_code}': her EvidenceRule TAM OLARAK bir koşul türü "
            f"doldurmalı (ratio_code+tier_in TEK tür sayılır) -- bulunan: "
            f"{filled_fields!r}"
        )

    if evidence_rule.ratio_code is not None:
        if evidence_rule.tier_in is None or len(evidence_rule.tier_in) == 0:
            raise ValueError(f"'{rule_code}': ratio_code dolu iken tier_in de dolu olmalı.")
        unknown_tiers = set(evidence_rule.tier_in) - KNOWN_BENCHMARK_TIERS
        if unknown_tiers:
            raise ValueError(f"'{rule_code}': bilinmeyen tier(lar): {unknown_tiers!r}")
    else:
        if evidence_rule.tier_in is not None:
            raise ValueError(f"'{rule_code}': tier_in yalnızca ratio_code ile birlikte dolu olabilir.")

    if evidence_rule.hard_fail_code is not None and evidence_rule.hard_fail_code not in KNOWN_HARD_FAIL_CODES:
        raise ValueError(f"'{rule_code}': bilinmeyen hard_fail_code {evidence_rule.hard_fail_code!r}")

    if (
        evidence_rule.banking_lens_flag is not None
        and evidence_rule.banking_lens_flag not in KNOWN_BANKING_LENS_FLAGS
    ):
        raise ValueError(f"'{rule_code}': bilinmeyen banking_lens_flag {evidence_rule.banking_lens_flag!r}")

    if (
        evidence_rule.credit_score_data_gap_code is not None
        and evidence_rule.credit_score_data_gap_code not in KNOWN_CREDIT_SCORE_DATA_GAP_CODES
    ):
        raise ValueError(
            f"'{rule_code}': bilinmeyen credit_score_data_gap_code "
            f"{evidence_rule.credit_score_data_gap_code!r}"
        )

    if evidence_rule.category_coverage_below is not None:
        if not isinstance(evidence_rule.category_coverage_below, RecommendationCategory):
            raise ValueError(f"'{rule_code}': category_coverage_below RecommendationCategory olmalı.")


RECOMMENDATION_RULES_BY_CODE: "dict[str, RecommendationRule]" = {}


def register_recommendation_rule(
    rule: RecommendationRule,
    *,
    registry: "dict[str, RecommendationRule] | None" = None,
) -> None:
    """
    Bölüm 8.2'nin 12 maddelik KAYIT ANINDA doğrulaması (madde 4/9/10 --
    çapraz-kural referans bütünlüğü -- bu fonksiyonda DEĞİL, TÜM registry
    inşa edildikten SONRA `_validate_cross_rule_references()`'ta kontrol
    edilir; bu, tek-kural sırasına bağlı OLMAYAN bir doğrulamadır).
    """

    target_registry = RECOMMENDATION_RULES_BY_CODE if registry is None else registry

    # Madde 1
    if rule.recommendation_code in target_registry:
        raise ValueError(f"recommendation_code zaten kayıtlı: {rule.recommendation_code!r}")

    # Madde 3
    if not isinstance(rule.category, RecommendationCategory):
        raise ValueError(f"'{rule.recommendation_code}': geçersiz category {rule.category!r}")
    expected_bucket = category_to_result_bucket(rule.category)
    if rule.result_bucket != expected_bucket:
        raise ValueError(
            f"'{rule.recommendation_code}': result_bucket {rule.result_bucket!r} "
            f"category={rule.category!r} ile UYUŞMUYOR (beklenen {expected_bucket!r})."
        )

    # Madde 2 -- yalnızca FINANCIAL bucket için category<->ratio tutarlılığı
    # ZORUNLUDUR (BANKING_READINESS/DATA_QUALITY'nin related_ratio_codes'u
    # BAĞLAMSAL referanslardır, KENDİ kategori-ratio eşlemesi DEĞİLDİR).
    for ratio_code in rule.related_ratio_codes:
        if ratio_code not in RATIO_REGISTRY:
            raise ValueError(
                f"'{rule.recommendation_code}': related_ratio_codes içindeki "
                f"'{ratio_code}' RATIO_REGISTRY'de kayıtlı değil."
            )
        if rule.result_bucket == ResultBucket.FINANCIAL:
            mapped_category = CATEGORY_RATIO_MAP.get(ratio_code)
            if mapped_category != rule.category.value:
                raise ValueError(
                    f"'{rule.recommendation_code}': '{ratio_code}' Bölüm 18.1'de "
                    f"'{mapped_category}' kategorisinde, kural ise "
                    f"'{rule.category.value}' bildiriyor -- TUTARSIZ."
                )

    # Madde 5
    if (rule.disclaimer_scope == "banking") != (rule.category == RecommendationCategory.BANKING_READINESS):
        raise ValueError(
            f"'{rule.recommendation_code}': disclaimer_scope='banking' <=> "
            "category=BANKING_READINESS eşdeğerliği İHLAL EDİLDİ."
        )
    if rule.disclaimer_scope not in _VALID_DISCLAIMER_SCOPES:
        raise ValueError(f"'{rule.recommendation_code}': bilinmeyen disclaimer_scope {rule.disclaimer_scope!r}")

    # Madde 6/7/8 -- evidence_rules
    if rule.trigger_mode not in _VALID_TRIGGER_MODES:
        raise ValueError(f"'{rule.recommendation_code}': bilinmeyen trigger_mode {rule.trigger_mode!r}")
    if len(rule.evidence_rules) == 0:
        raise ValueError(f"'{rule.recommendation_code}': evidence_rules BOŞ olamaz.")
    for evidence_rule in rule.evidence_rules:
        _validate_evidence_rule(evidence_rule, rule.recommendation_code)
        if evidence_rule.ratio_code is not None and evidence_rule.ratio_code not in rule.related_ratio_codes:
            raise ValueError(
                f"'{rule.recommendation_code}': evidence_rule.ratio_code "
                f"'{evidence_rule.ratio_code}' related_ratio_codes içinde YOK."
            )

    # Madde 11 -- registry-statik eşlemeler (kısmi, gerçekleştirilebilir kısım)
    if rule.trigger_strategy == RecommendationTriggerStrategy.HARD_FAIL_PRESENT:
        if rule.coverage_policy != "exempt_hard_fail":
            raise ValueError(
                f"'{rule.recommendation_code}': trigger_strategy=HARD_FAIL_PRESENT "
                "iken coverage_policy='exempt_hard_fail' OLMALI."
            )
        if rule.severity != RecommendationSeverity.CRITICAL:
            raise ValueError(
                f"'{rule.recommendation_code}': trigger_strategy=HARD_FAIL_PRESENT "
                "iken severity=CRITICAL OLMALI."
            )
    if rule.category == RecommendationCategory.DATA_QUALITY and rule.coverage_policy != "always_evaluated":
        raise ValueError(f"'{rule.recommendation_code}': DATA_QUALITY kuralları coverage_policy='always_evaluated' OLMALI.")
    if rule.coverage_policy not in _VALID_COVERAGE_POLICIES:
        raise ValueError(f"'{rule.recommendation_code}': bilinmeyen coverage_policy {rule.coverage_policy!r}")

    # Madde 12
    if rule.base_priority == RecommendationPriority.INFORMATIONAL and rule.result_bucket == ResultBucket.FINANCIAL:
        raise ValueError(
            f"'{rule.recommendation_code}': base_priority=INFORMATIONAL "
            "FINANCIAL bucket'ında İZİN VERİLMEZ."
        )

    target_registry[rule.recommendation_code] = rule


def _validate_cross_rule_references(rules: "tuple[RecommendationRule, ...]") -> None:
    """Bölüm 8.2 madde 4/9/10 -- TÜM registry inşa edildikten SONRA çapraz referans bütünlüğü."""

    codes = {rule.recommendation_code for rule in rules}

    # Madde 4 -- RECOMMENDATION_CONFLICT_PAIRS
    for left, right in RECOMMENDATION_CONFLICT_PAIRS:
        if left not in codes or right not in codes:
            raise ValueError(f"RECOMMENDATION_CONFLICT_PAIRS: ({left!r}, {right!r}) kayıtlı değil.")

    conflict_group_members: "dict[str, list[str]]" = {}
    for rule in rules:
        if rule.conflict_group is not None:
            conflict_group_members.setdefault(rule.conflict_group, []).append(rule.recommendation_code)
    for group_id, members in conflict_group_members.items():
        if len(members) < 2:
            raise ValueError(f"conflict_group={group_id!r}: en az 2 kural GEREKİR, bulunan: {members!r}")

    # Madde 9 -- mutually_exclusive_group
    mutually_exclusive_members: "dict[str, list[str]]" = {}
    for rule in rules:
        if rule.mutually_exclusive_group is not None:
            mutually_exclusive_members.setdefault(rule.mutually_exclusive_group, []).append(
                rule.recommendation_code
            )
    for group_id, members in mutually_exclusive_members.items():
        if len(members) < 2:
            raise ValueError(f"mutually_exclusive_group={group_id!r}: en az 2 kural GEREKİR.")
        member_set = frozenset(members)
        for conflict_pair in RECOMMENDATION_CONFLICT_PAIRS:
            if frozenset(conflict_pair) <= member_set:
                raise ValueError(
                    f"mutually_exclusive_group={group_id!r}: {conflict_pair!r} AYNI ZAMANDA "
                    "conflict pair OLAMAZ (Bölüm 13.3)."
                )

    # Madde 10 -- prerequisite_rules/blocking_rules referans bütünlüğü
    for rule in rules:
        for ref_code in (*rule.prerequisite_rules, *rule.blocking_rules):
            if ref_code not in codes:
                raise ValueError(
                    f"'{rule.recommendation_code}': prerequisite/blocking referansı "
                    f"'{ref_code}' RECOMMENDATION_RULES'ta kayıtlı değil."
                )

    # RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS registry'sinin rule alanlarıyla TUTARLILIĞI
    for group in RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS:
        for code in group.recommendation_codes:
            if code not in codes:
                raise ValueError(
                    f"RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS={group.mutually_exclusive_group_id!r}: "
                    f"'{code}' kayıtlı değil."
                )


# --- Bölüm 20a: 39 kuralın TAM envanteri ---------------------------------

_P = RecommendationPriority
_S = RecommendationSeverity
_I = RecommendationImpactBand
_D = RecommendationDifficultyBand
_TS = RecommendationTriggerStrategy
_RC = RecommendationCategory


def _rule(
    code: str,
    category: RecommendationCategory,
    base_priority: RecommendationPriority,
    severity: RecommendationSeverity,
    impact_band: RecommendationImpactBand,
    difficulty_band: RecommendationDifficultyBand,
    trigger_strategy: RecommendationTriggerStrategy,
    trigger_mode: str,
    evidence_rules: "tuple[EvidenceRule, ...]",
    minimum_evidence_count: int,
    merge_group: "str | None",
    evidence_group: str,
    underlying_risk_code: str,
    confidence_ceiling: str,
    coverage_policy: str,
    related_ratio_codes: "tuple[str, ...]",
    title_tr: str,
    explanation_tr: str,
    action_steps_tr: "tuple[str, ...]",
    assumptions_tr: "tuple[str, ...]",
    disclaimer_scope: str = "general",
    mutually_exclusive_group: "str | None" = None,
    conflict_group: "str | None" = None,
) -> RecommendationRule:
    return RecommendationRule(
        recommendation_code=code,
        category=category,
        result_bucket=category_to_result_bucket(category),
        base_priority=base_priority,
        severity=severity,
        impact_band=impact_band,
        difficulty_band=difficulty_band,
        trigger_strategy=trigger_strategy,
        trigger_mode=trigger_mode,
        evidence_rules=evidence_rules,
        minimum_evidence_count=minimum_evidence_count,
        prerequisite_rules=(),
        blocking_rules=(),
        merge_group=merge_group,
        evidence_group=evidence_group,
        underlying_risk_code=underlying_risk_code,
        conflict_group=conflict_group,
        mutually_exclusive_group=mutually_exclusive_group,
        confidence_ceiling=Decimal(confidence_ceiling),
        coverage_policy=coverage_policy,
        related_ratio_codes=related_ratio_codes,
        title_tr=title_tr,
        explanation_tr=explanation_tr,
        action_steps_tr=action_steps_tr,
        assumptions_tr=assumptions_tr,
        disclaimer_tr=resolve_disclaimer_tr(disclaimer_scope),
        disclaimer_scope=disclaimer_scope,
        model_version_introduced="1.0.0",
        deprecated_since=None,
        replacement_recommendation_code=None,
    )


_RULES_LIST: "list[RecommendationRule]" = [
    # --- WORKING_CAPITAL (6) ---------------------------------------------
    _rule(
        "WC_REDUCE_RECEIVABLES_DAYS", _RC.WORKING_CAPITAL, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.LOW_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="days_sales_outstanding", tier_in=("weak", "critical")),), 1,
        None, "working_capital_cycle_days", "RECEIVABLES_COLLECTION_DELAY_RISK", "0.75", "subject_to_gate",
        ("days_sales_outstanding",),
        "Alacak Tahsilat Süresini Kısaltın",
        "Alacaklarınızın nakde dönüşüm süresi, kayıtlı karşılaştırma bandına göre uzun görünmektedir; bu durum işletme sermayesi üzerinde baskı yaratabilir.",
        ("Tahsilat sıklığını ve vade takibini gözden geçirin.", "Erken ödeme teşviki gibi seçenekleri değerlendirin."),
        ("Değerlendirme mevcut dönem finansal tablo verisine dayanır; sektöre özgü ödeme alışkanlıkları ayrıca dikkate alınmamıştır.",),
    ),
    _rule(
        "WC_EXTEND_PAYABLES_DAYS", _RC.WORKING_CAPITAL, _P.MEDIUM, _S.LOW, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="days_payables_outstanding", tier_in=("weak",)),), 1,
        None, "working_capital_cycle_days", "SUPPLIER_FINANCING_UNDERUSE_RISK", "0.75", "subject_to_gate",
        ("days_payables_outstanding",),
        "Tedarikçi Ödeme Vadelerini Gözden Geçirin",
        "Tedarikçi ödeme vadeniz, kayıtlı karşılaştırma bandının erken-ödeme ucuna yakın görünmektedir; bu durum tedarikçi finansmanından yeterince yararlanılmadığına işaret edebilir.",
        ("Tedarikçilerle ödeme vadesi koşullarını yeniden görüşmeyi değerlendirin.",),
        ("Bant sınıflandırması RANGE_IS_BETTER metodolojisine dayanır; erken/geç ödeme ayrımı bu tasarımda ayrıştırılmamıştır.",),
    ),
    _rule(
        "WC_REDUCE_INVENTORY_DAYS", _RC.WORKING_CAPITAL, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="days_inventory_outstanding", tier_in=("weak", "critical")),), 1,
        None, "working_capital_cycle_days", "SLOW_INVENTORY_TURNOVER_RISK", "0.75", "subject_to_gate",
        ("days_inventory_outstanding",),
        "Stok Devir Hızını İyileştirin",
        "Envanterinizin elde tutulma süresi, kayıtlı karşılaştırma bandına göre uzun görünmektedir.",
        ("Stok seviyelerini ve sipariş sıklığını gözden geçirin.", "Yavaş hareket eden kalemleri ayrıca inceleyin."),
        ("Değerlendirme yalnızca dönem-sonu envanter verisine dayanır; mevsimsellik ayrıştırılmamıştır.",),
        mutually_exclusive_group="MEG_INVENTORY_LEVEL",
    ),
    _rule(
        "WC_MAINTAIN_INVENTORY_SAFETY_BUFFER", _RC.WORKING_CAPITAL, _P.LOW, _S.LOW, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="days_inventory_outstanding", tier_in=("good", "excellent")),), 1,
        None, "working_capital_cycle_days", "STOCKOUT_RISK", "0.75", "subject_to_gate",
        ("days_inventory_outstanding",),
        "Stok Güvenlik Tamponunu Koruyun",
        "Envanter seviyeniz kayıtlı karşılaştırma bandına göre oldukça yalın görünmektedir; bu durum tedarik kesintisi riskini artırabilir.",
        ("Kritik girdiler için minimum güvenlik stoku politikasını gözden geçirin.",),
        ("Bu öneri talep/tedarik değişkenliği verisine dayanmaz; yalnızca stok günü göstergesine dayanır.",),
        mutually_exclusive_group="MEG_INVENTORY_LEVEL",
    ),
    _rule(
        "WC_ADDRESS_CASH_CONVERSION_CYCLE", _RC.WORKING_CAPITAL, _P.MEDIUM, _S.MEDIUM, _I.HIGH, _D.STRUCTURAL_EFFORT,
        _TS.ANY_CONDITION, "any",
        (
            EvidenceRule(ratio_code="cash_conversion_cycle", tier_in=("weak", "critical")),
            EvidenceRule(critical_override_ratio_code="cash_conversion_cycle"),
        ), 1,
        "MG_WORKING_CAPITAL_STRAIN", "working_capital_cycle_days", "CASH_CONVERSION_CYCLE_RISK", "0.75", "subject_to_gate",
        ("cash_conversion_cycle",),
        "Nakit Dönüşüm Süresini Kısaltacak Bir Plan Oluşturun",
        "Nakit dönüşüm süreniz kayıtlı karşılaştırma bandına göre uzun görünmektedir; bu durum işletme sermayesi ihtiyacınızı artırabilir.",
        ("Tahsilat, stok ve ödeme süreçlerini birlikte değerlendiren bir iyileştirme planı hazırlayın.",),
        ("Tek dönem verisine dayanır; yapısal mı geçici mi olduğu ayrıca değerlendirilmelidir.",),
    ),
    _rule(
        "WC_REVIEW_WORKING_CAPITAL_TURNOVER", _RC.WORKING_CAPITAL, _P.LOW, _S.LOW, _I.LOW, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="working_capital_turnover", tier_in=("weak", "critical")),), 1,
        None, "working_capital_cycle_days", "WORKING_CAPITAL_EFFICIENCY_RISK", "0.75", "subject_to_gate",
        ("working_capital_turnover",),
        "İşletme Sermayesi Verimliliğini Gözden Geçirin",
        "İşletme sermayesi devir hızınız kayıtlı karşılaştırma bandına göre düşük görünmektedir.",
        ("Satış hacmi ile işletme sermayesi kullanımı arasındaki ilişkiyi gözden geçirin.",),
        ("Diğer working_capital göstergeleriyle (DSO/DPO/DIO/CCC) birlikte yorumlanması önerilir.",),
    ),
    # --- LIQUIDITY (4) -----------------------------------------------------
    _rule(
        "LIQ_IMPROVE_CURRENT_RATIO", _RC.LIQUIDITY, _P.HIGH, _S.HIGH, _I.HIGH, _D.STRUCTURAL_EFFORT,
        _TS.ANY_CONDITION, "any",
        (
            EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),
            EvidenceRule(critical_override_ratio_code="current_ratio"),
        ), 1,
        "MG_LIQUIDITY_STRAIN", "liquidity_balance_sheet_family", "SHORT_TERM_LIQUIDITY_RISK", "0.75", "subject_to_gate",
        ("current_ratio",),
        "Cari Oranınızı İyileştirin",
        "Kısa vadeli varlıklarınızın kısa vadeli yükümlülüklerinizi karşılama düzeyi kayıtlı karşılaştırma bandına göre zayıf görünmektedir.",
        ("Kısa vadeli finansman yapınızı ve nakit yönetimi politikanızı gözden geçirin.",),
        ("Bilanço-anı bir orandır; dönem içi dalgalanmalar yansımayabilir.",),
    ),
    _rule(
        "LIQ_IMPROVE_QUICK_RATIO", _RC.LIQUIDITY, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="quick_ratio", tier_in=("weak", "critical")),), 1,
        None, "liquidity_balance_sheet_family", "LIQUID_ASSET_ADEQUACY_RISK", "0.75", "subject_to_gate",
        ("quick_ratio",),
        "Likit Varlık Yeterliliğinizi Gözden Geçirin",
        "Stok hariç likit varlıklarınızın kısa vadeli yükümlülükleri karşılama düzeyi zayıf görünmektedir.",
        ("Nakit ve nakit benzeri varlık yönetiminizi gözden geçirin.",),
        ("quick_ratio hesaplaması platformun mevcut formülüne dayanır.",),
    ),
    _rule(
        "LIQ_BUILD_CASH_BUFFER", _RC.LIQUIDITY, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="cash_ratio", tier_in=("critical",)),), 1,
        None, "liquidity_balance_sheet_family", "CASH_BUFFER_ADEQUACY_RISK", "0.75", "subject_to_gate",
        ("cash_ratio",),
        "Nakit Tamponu Oluşturun",
        "Nakit ve nakit benzeri varlıklarınız kısa vadeli yükümlülüklerinize göre kritik seviyede düşük görünmektedir.",
        ("Asgari nakit tamponu politikası oluşturmayı değerlendirin.",),
        ("Dönem-sonu bakiyeye dayanır, günlük nakit pozisyonunu yansıtmayabilir.",),
    ),
    _rule(
        "LIQ_REVIEW_DEFENSIVE_INTERVAL", _RC.LIQUIDITY, _P.LOW, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="defensive_interval_ratio", tier_in=("critical",)),), 1,
        None, "liquidity_balance_sheet_family", "DEFENSIVE_INTERVAL_RISK", "0.75", "subject_to_gate",
        ("defensive_interval_ratio",),
        "Savunma Süresi Göstergenizi Gözden Geçirin",
        "Mevcut likit varlıklarınızla operasyonel giderlerinizi karşılayabileceğiniz süre kısa görünmektedir.",
        ("Operasyonel gider planlaması ile likidite yönetiminizi birlikte gözden geçirin.",),
        ("Geçmiş dönem operasyonel gider ortalamasına dayanır.",),
    ),
    # --- LEVERAGE (4) --------------------------------------------------------
    _rule(
        "LEV_STRENGTHEN_EQUITY_BASE", _RC.LEVERAGE, _P.CRITICAL, _S.CRITICAL, _I.HIGH, _D.STRUCTURAL_EFFORT,
        _TS.HARD_FAIL_PRESENT, "all",
        (EvidenceRule(hard_fail_code="NEGATIVE_EQUITY"),), 1,
        "MG_HIGH_LEVERAGE", "capital_structure_family", "OVERLEVERAGE_RISK", "0.75", "exempt_hard_fail",
        ("equity_ratio", "debt_to_equity"),
        "Sermaye Yapınızı Güçlendirin",
        "Özkaynak yapınızda platformun hard-fail eşiğini aşan ciddi bir zayıflık tespit edilmiştir.",
        ("Sermaye yapısı güçlendirme seçeneklerini (özkaynak enjeksiyonu, borç yeniden yapılandırması gibi) mali danışmanınızla değerlendirin.",),
        ("Bu değerlendirme platformun içsel hard-fail eşiğine dayanır; hukuki/vergisel sonuçlar ayrıca değerlendirilmelidir.",),
    ),
    _rule(
        "LEV_IMPROVE_INTEREST_COVERAGE", _RC.LEVERAGE, _P.CRITICAL, _S.CRITICAL, _I.HIGH, _D.STRUCTURAL_EFFORT,
        _TS.HARD_FAIL_PRESENT, "all",
        (EvidenceRule(hard_fail_code="SEVERE_DEBT_SERVICE_SHORTFALL"),), 1,
        "MG_DEBT_SERVICE_STRESS", "debt_service_family", "DEBT_SERVICE_RISK", "0.75", "exempt_hard_fail",
        ("interest_coverage_ratio",),
        "Borç Servisi Kapasitenizi Güçlendirin",
        "Faiz karşılama kapasitenizde platformun hard-fail eşiğini aşan ciddi bir zayıflık tespit edilmiştir.",
        ("Borç yeniden yapılandırma veya nakit akışı iyileştirme seçeneklerini değerlendirin.",),
        ("Bu değerlendirme platformun içsel hard-fail eşiğine dayanır.",),
    ),
    _rule(
        "LEV_REVIEW_DEBT_MATURITY_MIX", _RC.LEVERAGE, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="short_term_debt_ratio", tier_in=("critical",)),), 1,
        None, "capital_structure_family", "DEBT_MATURITY_CONCENTRATION_RISK", "0.75", "subject_to_gate",
        ("short_term_debt_ratio",),
        "Borç Vade Dağılımınızı Gözden Geçirin",
        "Kısa vadeli borç yükünüzün toplam borç içindeki payı yüksek görünmektedir.",
        ("Borç vade yapınızı uzun vadeye kaydırma seçeneklerini değerlendirin.",),
        ("Dönem-sonu bilanço verisine dayanır.",),
    ),
    _rule(
        "LEV_MONITOR_DEBT_TO_EBITDA", _RC.LEVERAGE, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="debt_to_ebitda", tier_in=("weak", "critical")),), 1,
        None, "debt_service_family", "DEBT_TO_EARNINGS_RISK", "0.75", "subject_to_gate",
        ("debt_to_ebitda",),
        "Borç/FAVÖK Oranınızı İzleyin",
        "Borcunuzun faaliyet kârlılığınıza oranı kayıtlı karşılaştırma bandına göre yüksek görünmektedir.",
        ("Borçlanma hızınızı faaliyet kârlılığı büyümenizle karşılaştırarak izleyin.",),
        ("FAVÖK hesaplaması platformun mevcut formülüne dayanır.",),
    ),
    # --- PROFITABILITY (4) ---------------------------------------------------
    _rule(
        "PROF_IMPROVE_NET_MARGIN", _RC.PROFITABILITY, _P.HIGH, _S.HIGH, _I.HIGH, _D.STRUCTURAL_EFFORT,
        _TS.ANY_CONDITION, "any",
        (
            EvidenceRule(ratio_code="net_profit_margin", tier_in=("critical",)),
            EvidenceRule(critical_override_ratio_code="net_profit_margin"),
        ), 1,
        "MG_WEAK_PROFIT_MARGIN", "profitability_margin_family", "WEAK_PROFITABILITY_RISK", "0.75", "subject_to_gate",
        ("net_profit_margin",),
        "Net Kâr Marjınızı İyileştirin",
        "Net kâr marjınız kayıtlı karşılaştırma bandına göre zayıf görünmektedir.",
        ("Maliyet yapınızı ve fiyatlandırma politikanızı birlikte gözden geçirin.",),
        ("Tek dönem verisine dayanır; mevsimsellik/tek seferlik kalemler ayrıştırılmamıştır.",),
    ),
    _rule(
        "PROF_REVIEW_COST_OF_SALES", _RC.PROFITABILITY, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ANY_CONDITION, "any",
        (
            EvidenceRule(ratio_code="cost_of_sales_ratio", tier_in=("weak", "critical")),
            EvidenceRule(ratio_code="gross_profit_margin", tier_in=("weak", "critical")),
        ), 1,
        None, "profitability_margin_family", "COST_STRUCTURE_RISK", "0.75", "subject_to_gate",
        ("cost_of_sales_ratio", "gross_profit_margin"),
        "Satışların Maliyeti Yapınızı Gözden Geçirin",
        "Satışların maliyetinin satışlara oranı kayıtlı karşılaştırma bandına göre yüksek görünmektedir.",
        ("Tedarik/üretim maliyet kalemlerini ayrıştırarak inceleyin.",),
        ("Muhasebe sınıflandırma tutarlılığı varsayılmıştır.",),
    ),
    _rule(
        "PROF_REVIEW_OPERATING_EXPENSES", _RC.PROFITABILITY, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="operating_expense_ratio", tier_in=("weak", "critical")),), 1,
        None, "profitability_margin_family", "OPERATING_EXPENSE_RISK", "0.75", "subject_to_gate",
        ("operating_expense_ratio",),
        "Operasyonel Giderlerinizi Gözden Geçirin",
        "Operasyonel giderlerinizin satışlara oranı kayıtlı karşılaştırma bandına göre yüksek görünmektedir.",
        ("Sabit ve değişken gider kalemlerini ayrıştırarak inceleyin.",),
        ("Muhasebe dönemleri arası tutarlılık varsayılmıştır.",),
    ),
    _rule(
        "PROF_IMPROVE_ASSET_RETURNS", _RC.PROFITABILITY, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.STRUCTURAL_EFFORT,
        _TS.ANY_CONDITION, "any",
        (
            EvidenceRule(ratio_code="return_on_assets", tier_in=("critical",)),
            EvidenceRule(ratio_code="return_on_equity", tier_in=("critical",)),
        ), 1,
        None, "profitability_return_family", "CAPITAL_RETURN_RISK", "0.75", "subject_to_gate",
        ("return_on_assets", "return_on_equity"),
        "Varlık/Özkaynak Getirinizi İyileştirin",
        "Varlıklarınızın veya özkaynağınızın getiri düzeyi kayıtlı karşılaştırma bandına göre zayıf görünmektedir.",
        ("Kârlılık ve varlık kullanım verimliliğini birlikte değerlendirin.",),
        ("Dönem-sonu bilanço büyüklükleri kullanılmıştır, ortalama bakiyeler DEĞİL.",),
    ),
    # --- ACTIVITY (2) ----------------------------------------------------------
    _rule(
        "ACT_IMPROVE_ASSET_TURNOVER", _RC.ACTIVITY, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.STRUCTURAL_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="asset_turnover", tier_in=("weak", "critical")),), 1,
        None, "asset_efficiency_family", "ASSET_UTILIZATION_RISK", "0.75", "subject_to_gate",
        ("asset_turnover",),
        "Varlık Devir Hızınızı İyileştirin",
        "Toplam varlıklarınızın satış üretme verimliliği kayıtlı karşılaştırma bandına göre düşük görünmektedir.",
        ("Az kullanılan varlıkları belirlemek için varlık envanterinizi gözden geçirin.",),
        ("Dönem-sonu toplam varlık büyüklüğü kullanılmıştır.",),
    ),
    _rule(
        "ACT_IMPROVE_FIXED_ASSET_TURNOVER", _RC.ACTIVITY, _P.LOW, _S.MEDIUM, _I.MEDIUM, _D.STRUCTURAL_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="fixed_asset_turnover", tier_in=("critical",)),), 1,
        None, "asset_efficiency_family", "FIXED_ASSET_UTILIZATION_RISK", "0.75", "subject_to_gate",
        ("fixed_asset_turnover",),
        "Sabit Kıymet Devir Hızınızı Gözden Geçirin",
        "Sabit kıymetlerinizin satış üretme verimliliği kayıtlı karşılaştırma bandına göre düşük görünmektedir.",
        ("Kullanım oranı düşük sabit kıymetleri gözden geçirin.",),
        ("Amortisman politikası farklılıkları ayrıştırılmamıştır.",),
    ),
    # --- GROWTH (3) --------------------------------------------------------------
    _rule(
        "GRW_REVIEW_DEBT_FUNDED_GROWTH", _RC.GROWTH, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.DEBT_FUNDED_GROWTH, "all",
        (EvidenceRule(banking_lens_flag="DEBT_FUNDED_GROWTH"),), 1,
        "MG_DEBT_FUNDED_GROWTH", "growth_financing_family", "DEBT_FUNDED_EXPANSION_RISK", "0.75", "subject_to_gate",
        ("total_assets_growth",),
        "Borçla Finanse Edilen Büyümeyi Gözden Geçirin",
        "Büyümenizin önemli ölçüde borç artışıyla birlikte gerçekleştiğine dair bir sinyal tespit edilmiştir.",
        ("Büyüme finansmanınızın kaynak dağılımını (özkaynak/borç) gözden geçirin.",),
        ("Bu sinyal Credit Score'un banking-lens değerlendirmesinden DOĞRUDAN alınır, yeniden hesaplanmaz.",),
    ),
    _rule(
        "GRW_STABILIZE_SALES_GROWTH", _RC.GROWTH, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.STRUCTURAL_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (EvidenceRule(ratio_code="sales_growth", tier_in=("critical",)),), 1,
        None, "growth_trend_family", "REVENUE_CONTRACTION_RISK", "0.75", "subject_to_gate",
        ("sales_growth",),
        "Satış Büyümenizi Stabilize Edin",
        "Satış büyümeniz kayıtlı karşılaştırma bandına göre sert bir daralma göstermektedir.",
        ("Daralmanın geçici mi yapısal mı olduğunu ayrıştırmak için pazar/müşteri analizini gözden geçirin.",),
        ("Nominal büyüme kullanılmıştır (TÜFE düzeltmesi YOK).",),
    ),
    _rule(
        "GRW_REVIEW_EQUITY_GROWTH_LAG", _RC.GROWTH, _P.LOW, _S.LOW, _I.LOW, _D.MODERATE_EFFORT,
        _TS.ALL_CONDITIONS, "all",
        (
            EvidenceRule(ratio_code="equity_growth", tier_in=("weak", "critical")),
            EvidenceRule(ratio_code="total_assets_growth", tier_in=("average", "good", "excellent")),
        ), 2,
        None, "growth_trend_family", "EQUITY_GROWTH_LAG_RISK", "0.75", "subject_to_gate",
        ("equity_growth", "total_assets_growth"),
        "Özkaynak Büyümesinin Varlık Büyümesine Göre Geride Kalmasını Gözden Geçirin",
        "Varlıklarınız büyürken özkaynağınızın aynı hızda büyümediği görülmektedir; bu durum kaldıraç artışına işaret edebilir.",
        ("Büyümenin finansman kaynağını (borç vs. özkaynak) gözden geçirin.",),
        ("Yalnızca tier-bazlı karşılaştırma kullanılmıştır; ham büyüme farkı HESAPLANMAMIŞTIR.",),
    ),
    # --- BANKING_READINESS (6) ----------------------------------------------------
    _rule(
        "BANK_PREPARE_LIQUIDITY_NARRATIVE", _RC.BANKING_READINESS, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.LOW_EFFORT,
        _TS.BANKING_FLAG_PRESENT, "all",
        (EvidenceRule(banking_lens_flag="SHORT_TERM_LIQUIDITY_STRAIN"),), 1,
        "MG_LIQUIDITY_STRAIN", "banking_readiness_family", "SHORT_TERM_LIQUIDITY_RISK", "0.65", "subject_to_gate",
        ("current_ratio", "quick_ratio", "cash_ratio"),
        "Banka Görüşmesi İçin Likidite Açıklaması Hazırlayın",
        "Kısa vadeli likidite göstergeleriniz, banka değerlendirmesinde dikkat çekebilecek bir zayıflık sinyali taşımaktadır.",
        ("Likidite durumunuzu açıklayan kısa bir not hazırlayın.", "Banka görüşmesi öncesinde nakit yönetim planınızı gözden geçirin."),
        ("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir, yeniden hesaplanmaz.",),
        disclaimer_scope="banking",
    ),
    _rule(
        "BANK_PREPARE_LEVERAGE_NARRATIVE", _RC.BANKING_READINESS, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.LOW_EFFORT,
        _TS.BANKING_FLAG_PRESENT, "all",
        (EvidenceRule(banking_lens_flag="HIGH_LEVERAGE"),), 1,
        "MG_HIGH_LEVERAGE", "banking_readiness_family", "OVERLEVERAGE_RISK", "0.65", "subject_to_gate",
        ("equity_ratio", "debt_to_equity"),
        "Kaldıraç Yapınızı Açıklayan Bir Not Hazırlayın",
        "Kaldıraç göstergeleriniz banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır.",
        ("Sermaye yapınızı ve borç kullanım gerekçenizi açıklayan bir not hazırlayın.",),
        ("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",),
        disclaimer_scope="banking",
    ),
    _rule(
        "BANK_DISCUSS_RESTRUCTURING_OPTIONS", _RC.BANKING_READINESS, _P.HIGH, _S.HIGH, _I.HIGH, _D.STRUCTURAL_EFFORT,
        _TS.BANKING_FLAG_PRESENT, "all",
        (EvidenceRule(banking_lens_flag="DEBT_SERVICE_STRESS"),), 1,
        "MG_DEBT_SERVICE_STRESS", "banking_readiness_family", "DEBT_SERVICE_RISK", "0.65", "subject_to_gate",
        ("interest_coverage_ratio",),
        "Banka İle Yeniden Yapılandırma Seçeneklerini Görüşün",
        "Borç servisi kapasitenize ilişkin göstergeler banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır.",
        ("Banka ile olası yeniden yapılandırma seçeneklerini görüşmeyi değerlendirin.",),
        ("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",),
        disclaimer_scope="banking",
    ),
    _rule(
        "BANK_PREPARE_PROFITABILITY_NARRATIVE", _RC.BANKING_READINESS, _P.LOW, _S.MEDIUM, _I.LOW, _D.LOW_EFFORT,
        _TS.BANKING_FLAG_PRESENT, "all",
        (EvidenceRule(banking_lens_flag="WEAK_PROFIT_BUFFER"),), 1,
        "MG_WEAK_PROFIT_MARGIN", "banking_readiness_family", "WEAK_PROFITABILITY_RISK", "0.65", "subject_to_gate",
        ("net_profit_margin",),
        "Kârlılık Trendini Açıklayan Bir Not Hazırlayın",
        "Kârlılık göstergeleriniz banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır.",
        ("Kârlılık trendinizi ve nedenlerini açıklayan bir not hazırlayın.",),
        ("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",),
        disclaimer_scope="banking",
    ),
    _rule(
        "BANK_DISCUSS_WORKING_CAPITAL_FACILITY", _RC.BANKING_READINESS, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.BANKING_FLAG_PRESENT, "all",
        (EvidenceRule(banking_lens_flag="WORKING_CAPITAL_STRAIN"),), 1,
        "MG_WORKING_CAPITAL_STRAIN", "banking_readiness_family", "CASH_CONVERSION_CYCLE_RISK", "0.65", "subject_to_gate",
        ("cash_conversion_cycle",),
        "İşletme Sermayesi Kredisi Seçeneklerini Araştırın",
        "İşletme sermayesi göstergeleriniz banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır.",
        ("İşletme sermayesi finansmanı seçeneklerini araştırmayı değerlendirin.",),
        ("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",),
        disclaimer_scope="banking",
    ),
    _rule(
        "BANK_REVIEW_GROWTH_FINANCING_MIX", _RC.BANKING_READINESS, _P.MEDIUM, _S.MEDIUM, _I.MEDIUM, _D.MODERATE_EFFORT,
        _TS.BANKING_FLAG_PRESENT, "all",
        (EvidenceRule(banking_lens_flag="DEBT_FUNDED_GROWTH"),), 1,
        "MG_DEBT_FUNDED_GROWTH", "banking_readiness_family", "DEBT_FUNDED_EXPANSION_RISK", "0.65", "subject_to_gate",
        ("total_assets_growth",),
        "Büyüme Finansmanı Karışımını Gözden Geçirin",
        "Büyümenizin finansman karışımı banka değerlendirmesinde dikkat çekebilecek bir sinyal taşımaktadır.",
        ("Büyüme finansmanınızın borç/özkaynak dağılımını banka ile görüşmeden önce gözden geçirin.",),
        ("Bu öneri Credit Score'un banking-lens sinyalinden DOĞRUDAN türetilir.",),
        disclaimer_scope="banking",
    ),
]


def _data_quality_coverage_rule(
    code: str, category: RecommendationCategory, title_category_tr: str
) -> RecommendationRule:
    return _rule(
        code, _RC.DATA_QUALITY, _P.INFORMATIONAL, _S.LOW, _I.LOW, _D.LOW_EFFORT,
        _TS.DATA_COVERAGE_GAP, "all",
        (EvidenceRule(category_coverage_below=category, coverage_threshold=CATEGORY_COVERAGE_GATE_THRESHOLD),), 1,
        None, "data_coverage_family", "DATA_COVERAGE_RISK", "1.00", "always_evaluated",
        (),
        f"{title_category_tr} Kategorisi İçin Veri Kapsamını İyileştirin",
        f"{title_category_tr} kategorisindeki oranların önemli bir kısmı hesaplanamıyor veya eksik; bu, bu alandaki değerlendirmenin güvenilirliğini sınırlamaktadır.",
        ("İlgili finansal tablo kalemlerinin eksiksiz girildiğini kontrol edin.",),
        ("Bu öneri kategori coverage oranına dayanır, ratio değerlerinin kendisine DEĞİL; skora/priority'ye ETKİMEZ.",),
    )


def _data_quality_gap_rule(code: str, gap_code: str, title_tr: str) -> RecommendationRule:
    return _rule(
        code, _RC.DATA_QUALITY, _P.INFORMATIONAL, _S.LOW, _I.LOW, _D.LOW_EFFORT,
        _TS.DATA_GAP_PRESENT, "all",
        (EvidenceRule(credit_score_data_gap_code=gap_code),), 1,
        None, "credit_readiness_data_gap_family", "CREDIT_READINESS_DATA_GAP", "1.00", "always_evaluated",
        (),
        title_tr,
        "Platform bu alanda ilgili veriye şu an sahip değildir; bu durum Credit Score'un ilgili boyutunu sınırlamaktadır.",
        ("Mümkünse ilgili veriyi platforma eklemeyi değerlendirin.",),
        ("Bu öneri, platformun ilgili veri türüne yapısal olarak SAHİP OLMADIĞI bilgisine dayanır; yeni bir hesaplama İÇERMEZ.",),
    )


_RULES_LIST.extend(
    [
        _data_quality_coverage_rule("DQ_IMPROVE_LIQUIDITY_DATA_COVERAGE", _RC.LIQUIDITY, "Likidite"),
        _data_quality_coverage_rule("DQ_IMPROVE_WORKING_CAPITAL_DATA_COVERAGE", _RC.WORKING_CAPITAL, "İşletme Sermayesi"),
        _data_quality_coverage_rule("DQ_IMPROVE_LEVERAGE_DATA_COVERAGE", _RC.LEVERAGE, "Kaldıraç"),
        _data_quality_coverage_rule("DQ_IMPROVE_PROFITABILITY_DATA_COVERAGE", _RC.PROFITABILITY, "Kârlılık"),
        _data_quality_coverage_rule("DQ_IMPROVE_ACTIVITY_DATA_COVERAGE", _RC.ACTIVITY, "Faaliyet"),
        _data_quality_coverage_rule("DQ_IMPROVE_GROWTH_DATA_COVERAGE", _RC.GROWTH, "Büyüme"),
        _data_quality_gap_rule(
            "DQ_ADDRESS_FORWARD_CASH_FLOW_GAP", "FORWARD_CASH_FLOW",
            "İleri Dönem Nakit Akışı Veri Boşluğunu Giderin",
        ),
        _data_quality_gap_rule(
            "DQ_ADDRESS_COLLATERAL_DATA_GAP", "COLLATERAL",
            "Teminat Veri Boşluğunu Giderin",
        ),
        _data_quality_gap_rule(
            "DQ_ADDRESS_PAYMENT_HISTORY_GAP", "PAYMENT_HISTORY",
            "Ödeme Geçmişi Veri Boşluğunu Giderin",
        ),
        _data_quality_gap_rule(
            "DQ_ADDRESS_MANAGEMENT_QUALITY_GAP", "MANAGEMENT_QUALITY",
            "Yönetim Kalitesi Veri Boşluğunu Giderin",
        ),
    ]
)


for _rule_instance in _RULES_LIST:
    register_recommendation_rule(_rule_instance)

RECOMMENDATION_RULES: "tuple[RecommendationRule, ...]" = tuple(_RULES_LIST)

# --- Bölüm 13.2: v1'de KASITLI OLARAK BOŞ ---------------------------------
RECOMMENDATION_CONFLICT_PAIRS: "tuple[tuple[str, str], ...]" = ()

# --- Bölüm 13.3: TEK gerçek mutually-exclusive grup -----------------------
RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS: "tuple[RecommendationMutuallyExclusiveGroup, ...]" = (
    RecommendationMutuallyExclusiveGroup(
        mutually_exclusive_group_id="MEG_INVENTORY_LEVEL",
        recommendation_codes=("WC_REDUCE_INVENTORY_DAYS", "WC_MAINTAIN_INVENTORY_SAFETY_BUFFER"),
        explanation_tr=(
            "Bu iki öneri, aynı göstergenin (days_inventory_outstanding) "
            "birbirini dışlayan iki farklı bandına dayanır; aynı anda "
            "tetiklenmeleri mantıksal olarak mümkün değildir."
        ),
    ),
)

_validate_cross_rule_references(RECOMMENDATION_RULES)


# --- Bölüm 14.1: BANKING_READINESS <-> fonksiyonel kategori örtüşmesi ----
BANKING_FLAG_TO_RATIO_OVERLAP: "dict[str, tuple[str, ...]]" = {
    "SHORT_TERM_LIQUIDITY_STRAIN": ("current_ratio", "quick_ratio", "cash_ratio"),
    "HIGH_LEVERAGE": ("equity_ratio", "debt_to_equity"),
    "DEBT_SERVICE_STRESS": ("interest_coverage_ratio",),
    "WEAK_PROFIT_BUFFER": ("net_profit_margin",),
    "WORKING_CAPITAL_STRAIN": ("cash_conversion_cycle",),
    "DEBT_FUNDED_GROWTH": ("total_assets_growth",),
}


# --- Bölüm 16.1: RECOMMENDATION_INPUT_COMPATIBILITY -----------------------
# Health/Credit Score'un GÜNCEL şema/registry versiyonlarıyla senkron
# tutulması implementasyon bakım sorumluluğudur (Bölüm 33 madde 11).
RECOMMENDATION_INPUT_COMPATIBILITY: "dict[str, frozenset[str]]" = {
    "health_score_schema_versions": frozenset({"1.0.0"}),
    "credit_score_schema_versions": frozenset({"1.0.0"}),
    "ratio_registry_versions": frozenset({"1.1.0"}),
    "benchmark_registry_versions": frozenset({"1.0.0"}),
}


# --- Bölüm 17: override mimarisi (v1'de yalnızca "global" dolu) ----------
_FUNCTIONAL_CATEGORY_RAW_WEIGHTS: "dict[str, Decimal]" = {
    RecommendationCategory.LIQUIDITY.value: Decimal("1"),
    RecommendationCategory.WORKING_CAPITAL.value: Decimal("1"),
    RecommendationCategory.LEVERAGE.value: Decimal("1"),
    RecommendationCategory.PROFITABILITY.value: Decimal("1"),
    RecommendationCategory.ACTIVITY.value: Decimal("1"),
    RecommendationCategory.GROWTH.value: Decimal("1"),
}

RECOMMENDATION_CATEGORY_WEIGHT_PROFILES: "dict[tuple[str, str | None], RecommendationCategoryWeightProfile]" = {
    ("global", None): RecommendationCategoryWeightProfile(
        scope="global",
        scope_key=None,
        category_weights=normalize_weights(_FUNCTIONAL_CATEGORY_RAW_WEIGHTS),
    ),
}


def resolve_recommendation_category_weights(
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
    tenant_id: "str | None" = None,
) -> RecommendationCategoryWeightProfile:
    """
    Bölüm 17 -- `tenant > industry > company_size > global` çözümleme
    sırası, v1'de yalnızca `global` DOLU (gerçek override verisi
    KAYDEDİLMEZ, Bölüm 2.1 madde 13).
    """

    return RECOMMENDATION_CATEGORY_WEIGHT_PROFILES[("global", None)]
