"""
Milestone 4.3D (Financial Health Score) / Adım 2: `app/engines/common/
health_score_registry.py` için gerçek, çalıştırılabilir birim testleri.
"""

from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.health_score_registry import (
    CATEGORY_WEIGHT_PROFILES,
    CRITICAL_OVERRIDE_RULES,
    HARD_FAIL_RULES,
    RATIO_SCORE_WEIGHTS,
    excluded_duplicate_ratio_codes_for_category,
    register_ratio_score_weight,
    resolve_category_weights,
    scoreable_ratio_codes_for_category,
)
from app.engines.common.health_score_types import RatioScoreWeight


_ACTIVE_CATEGORIES = (
    "liquidity", "leverage", "profitability", "activity", "efficiency", "growth",
)


# --- Envanter / tamlık ----------------------------------------------------


def _real_benchmark_registry_codes() -> set:
    # Diğer test dosyaları (ör. test_benchmark_types_unit.py), kendi
    # doğrulama testleri için GERÇEK global BENCHMARK_REGISTRY'ye "_test_"
    # önekli GEÇİCİ kodlar ekler (bkz. o dosyadaki "_test_higher" gibi
    # örnekler) -- bu sandbox test çalıştırıcısında TÜM test dosyaları AYNI
    # process'te, modül önbelleği paylaşılarak çalıştığı için bu geçici
    # kodlar test SIRASINA göre burada da görünebilir. Gerçek (4.3B/4.3C
    # onaylı) 48 kaydı izole etmek için alt çizgiyle başlayan test-only
    # kodlar HARİÇ tutulur -- health_score_registry.py'nin RATIO_SCORE_
    # WEIGHTS'i zaten yalnızca modül import ANINDAKİ 48 gerçek kaydı esas
    # alarak inşa edildi (bkz. _build_ratio_score_weights).
    return {code for code in BENCHMARK_REGISTRY.keys() if not code.startswith("_")}


def test_ratio_score_weights_covers_every_benchmark_registry_entry():
    assert set(RATIO_SCORE_WEIGHTS.keys()) == _real_benchmark_registry_codes()


def test_cash_flow_category_has_no_ratio_score_weight_entries():
    assert all(w.category != "cash_flow" for w in RATIO_SCORE_WEIGHTS.values())


def test_every_category_ratio_weight_sums_to_exactly_one():
    for category in _ACTIVE_CATEGORIES:
        total = sum(
            w.ratio_weight for w in RATIO_SCORE_WEIGHTS.values() if w.category == category
        )
        assert total == Decimal("1"), f"{category}: {total}"


# --- Bölüm 8.1 nihai sınıflandırma ----------------------------------------


def test_working_capital_ratio_is_duplicate_of_current_ratio():
    w = RATIO_SCORE_WEIGHTS["working_capital_ratio"]
    assert w.ratio_weight == 0
    assert w.excluded_as_duplicate_of == "current_ratio"
    assert w.duplicate_relationship == "identical_formula"


def test_debt_ratio_and_financial_leverage_multiplier_are_duplicates_of_equity_ratio():
    debt_ratio = RATIO_SCORE_WEIGHTS["debt_ratio"]
    flm = RATIO_SCORE_WEIGHTS["financial_leverage_multiplier"]
    assert debt_ratio.ratio_weight == 0
    assert debt_ratio.excluded_as_duplicate_of == "equity_ratio"
    assert debt_ratio.duplicate_relationship == "algebraic_complement"
    assert flm.ratio_weight == 0
    assert flm.excluded_as_duplicate_of == "equity_ratio"
    assert flm.duplicate_relationship == "algebraic_complement"
    assert RATIO_SCORE_WEIGHTS["equity_ratio"].ratio_weight > 0


def test_days_inventory_and_days_sales_outstanding_are_duplicates():
    dio = RATIO_SCORE_WEIGHTS["days_inventory_outstanding"]
    dso = RATIO_SCORE_WEIGHTS["days_sales_outstanding"]
    assert dio.ratio_weight == 0 and dio.excluded_as_duplicate_of == "inventory_turnover"
    assert dso.ratio_weight == 0 and dso.excluded_as_duplicate_of == "receivables_turnover"


def test_payables_turnover_is_duplicate_of_days_payables_outstanding():
    pt = RATIO_SCORE_WEIGHTS["payables_turnover"]
    assert pt.ratio_weight == 0
    assert pt.excluded_as_duplicate_of == "days_payables_outstanding"
    assert RATIO_SCORE_WEIGHTS["days_payables_outstanding"].ratio_weight > 0


def test_cash_conversion_cycle_is_scored_but_deweighted_summary_signal():
    ccc = RATIO_SCORE_WEIGHTS["cash_conversion_cycle"]
    assert ccc.ratio_weight > 0
    assert ccc.excluded_as_duplicate_of is None
    assert ccc.duplicate_relationship == "summary_signal_normalized"
    other_activity_scored = [
        w for code, w in RATIO_SCORE_WEIGHTS.items()
        if w.category == "activity" and code != "cash_conversion_cycle" and w.ratio_weight > 0
    ]
    assert all(ccc.ratio_weight < w.ratio_weight for w in other_activity_scored)


def test_scoreable_and_excluded_counts_per_category_match_design_doc():
    expected_scored = {
        "liquidity": 5, "leverage": 7, "profitability": 11,
        "activity": 7, "efficiency": 6, "growth": 6,
    }
    expected_excluded = {
        "liquidity": 1, "leverage": 2, "profitability": 0,
        "activity": 3, "efficiency": 0, "growth": 0,
    }
    for category in _ACTIVE_CATEGORIES:
        assert len(scoreable_ratio_codes_for_category(category)) == expected_scored[category]
        assert len(excluded_duplicate_ratio_codes_for_category(category)) == expected_excluded[category]


def test_total_scoreable_and_excluded_counts_derived_dynamically():
    total_scoreable = sum(len(scoreable_ratio_codes_for_category(c)) for c in _ACTIVE_CATEGORIES)
    total_excluded = sum(len(excluded_duplicate_ratio_codes_for_category(c)) for c in _ACTIVE_CATEGORIES)
    assert total_scoreable + total_excluded == len(_real_benchmark_registry_codes())
    assert total_excluded == 6


# --- register_ratio_score_weight doğrulama testleri -----------------------


def test_duplicate_ratio_code_registration_rejected():
    try:
        register_ratio_score_weight(
            RatioScoreWeight(
                ratio_code="current_ratio", category="liquidity", ratio_weight=Decimal("0.5")
            )
        )
        assert False, "zaten kayıtlı ratio_code reddedilmeliydi"
    except ValueError:
        pass


def test_unknown_ratio_code_registration_rejected():
    try:
        register_ratio_score_weight(
            RatioScoreWeight(
                ratio_code="_not_a_real_ratio", category="liquidity", ratio_weight=Decimal("0.5")
            )
        )
        assert False, "BENCHMARK_REGISTRY'de olmayan ratio_code reddedilmeliydi"
    except ValueError:
        pass


def test_category_mismatch_registration_rejected():
    # İzole bir registry kullanılır -- gerçek "current_ratio" ratio_code'u
    # BENCHMARK_REGISTRY'de category="liquidity" olarak kayıtlı; burada
    # BİLEREK yanlış bir kategori (leverage) verilerek kategori-uyuşmazlığı
    # kontrolü İZOLE test edilir (already-registered kontrolü izole
    # registry boş olduğu için devreye girmez).
    try:
        register_ratio_score_weight(
            RatioScoreWeight(
                ratio_code="current_ratio", category="leverage", ratio_weight=Decimal("0.5")
            ),
            registry={},
        )
        assert False, "kategori uyuşmazlığı reddedilmeliydi"
    except ValueError:
        pass


def test_zero_weight_without_duplicate_marker_rejected():
    try:
        register_ratio_score_weight(
            RatioScoreWeight(
                ratio_code="current_ratio", category="liquidity", ratio_weight=Decimal("0")
            ),
            registry={},
        )
        assert False, "excluded_as_duplicate_of boşken ratio_weight=0 reddedilmeliydi"
    except ValueError:
        pass


def test_nonzero_weight_with_duplicate_marker_rejected():
    try:
        register_ratio_score_weight(
            RatioScoreWeight(
                ratio_code="working_capital_ratio",
                category="liquidity",
                ratio_weight=Decimal("0.1"),
                excluded_as_duplicate_of="current_ratio",
                duplicate_relationship="identical_formula",
            ),
            registry={"current_ratio": RATIO_SCORE_WEIGHTS["current_ratio"]},
        )
        assert False, "excluded_as_duplicate_of doluyken ratio_weight!=0 reddedilmeliydi"
    except ValueError:
        pass


def test_duplicate_target_must_be_registered_before_the_duplicate_itself():
    try:
        register_ratio_score_weight(
            RatioScoreWeight(
                ratio_code="working_capital_ratio",
                category="liquidity",
                ratio_weight=Decimal("0"),
                excluded_as_duplicate_of="current_ratio",
                duplicate_relationship="identical_formula",
            ),
            registry={},  # current_ratio HENÜZ kayıtlı değil
        )
        assert False, "kayıtlı olmayan hedefe işaret eden duplicate reddedilmeliydi"
    except ValueError:
        pass


def test_chained_duplicate_target_rejected():
    isolated_registry = {
        "current_ratio": RATIO_SCORE_WEIGHTS["current_ratio"],
        "working_capital_ratio": RATIO_SCORE_WEIGHTS["working_capital_ratio"],
    }
    try:
        register_ratio_score_weight(
            RatioScoreWeight(
                ratio_code="quick_ratio",
                category="liquidity",
                ratio_weight=Decimal("0"),
                excluded_as_duplicate_of="working_capital_ratio",  # bu KENDİSİ duplicate
                duplicate_relationship="identical_formula",
            ),
            registry=isolated_registry,
        )
        assert False, "zincirleme duplicate (duplicate'in duplicate'i) reddedilmeliydi"
    except ValueError:
        pass


# --- CATEGORY_WEIGHT_PROFILES / resolve_category_weights ------------------


def test_global_category_weight_profile_sums_to_one_and_has_6_active_categories():
    profile = CATEGORY_WEIGHT_PROFILES[("global", None)]
    assert set(profile.category_weights.keys()) == set(_ACTIVE_CATEGORIES)
    assert sum(profile.category_weights.values()) == Decimal("1")
    assert "cash_flow" not in profile.category_weights


def test_global_category_weights_match_design_doc_bolum_8():
    weights = CATEGORY_WEIGHT_PROFILES[("global", None)].category_weights
    assert weights["liquidity"] == Decimal("0.20")
    assert weights["leverage"] == Decimal("0.25")
    assert weights["profitability"] == Decimal("0.20")
    assert weights["activity"] == Decimal("0.15")
    assert weights["efficiency"] == Decimal("0.10")
    assert weights["growth"] == Decimal("0.10")


def test_resolve_category_weights_falls_back_to_global_when_no_overrides_registered():
    profile = resolve_category_weights(
        industry_code="tekstil", company_size_bucket="small", tenant_id="banka_x"
    )
    assert profile.scope == "global"
    assert profile.scope_key is None


def test_resolve_category_weights_with_no_arguments_returns_global():
    profile = resolve_category_weights()
    assert profile.scope == "global"


# --- HARD_FAIL_RULES -------------------------------------------------------


def test_hard_fail_rules_has_exactly_2_rules_with_expected_ceilings():
    assert len(HARD_FAIL_RULES) == 2
    by_code = {rule.rule_code: rule for rule in HARD_FAIL_RULES}
    assert by_code["NEGATIVE_EQUITY"].score_ceiling == Decimal("25")
    assert by_code["SEVERE_DEBT_SERVICE_SHORTFALL"].score_ceiling == Decimal("35")


def test_negative_equity_predicate_triggers_only_on_negative_value():
    rule = next(r for r in HARD_FAIL_RULES if r.rule_code == "NEGATIVE_EQUITY")
    assert rule.predicate({"equity_ratio": Decimal("-0.1")}, {}) is True
    assert rule.predicate({"equity_ratio": Decimal("0.3")}, {}) is False
    assert rule.predicate({"equity_ratio": None}, {}) is False
    assert rule.predicate({}, {}) is False


def test_severe_debt_service_shortfall_predicate_triggers_only_on_negative_value():
    rule = next(r for r in HARD_FAIL_RULES if r.rule_code == "SEVERE_DEBT_SERVICE_SHORTFALL")
    assert rule.predicate({"interest_coverage_ratio": Decimal("-2")}, {}) is True
    assert rule.predicate({"interest_coverage_ratio": Decimal("3")}, {}) is False
    assert rule.predicate({"interest_coverage_ratio": None}, {}) is False


# --- CRITICAL_OVERRIDE_RULES ------------------------------------------------


def test_critical_override_rules_has_exactly_5_rules():
    assert len(CRITICAL_OVERRIDE_RULES) == 5
    codes = {r.ratio_code for r in CRITICAL_OVERRIDE_RULES}
    assert codes == {
        "current_ratio", "debt_to_equity", "interest_coverage_ratio",
        "net_profit_margin", "cash_conversion_cycle",
    }


def test_critical_override_rules_use_binding_multipliers():
    for rule in CRITICAL_OVERRIDE_RULES:
        assert rule.weak_multiplier == Decimal("0.90")
        assert rule.critical_multiplier == Decimal("0.70")


def test_critical_override_rules_reference_only_scored_ratios():
    for rule in CRITICAL_OVERRIDE_RULES:
        weight = RATIO_SCORE_WEIGHTS[rule.ratio_code]
        assert weight.ratio_weight > 0
        assert weight.category == rule.category
