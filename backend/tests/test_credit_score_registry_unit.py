"""
Milestone 4.3E (Credit Score Engine) / Adım 2: `app/engines/common/
credit_score_registry.py` için gerçek, çalıştırılabilir birim testleri.
"""

from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.credit_score_registry import (
    CREDIT_BANKING_LENS_SIGNAL_RULES,
    CREDIT_CATEGORY_WEIGHT_PROFILES,
    CREDIT_CRITICAL_OVERRIDE_RULES,
    CREDIT_HARD_FAIL_RULES,
    CREDIT_RATIO_SCORE_WEIGHTS,
    excluded_duplicate_ratio_codes_for_category,
    register_credit_ratio_score_weight,
    resolve_credit_category_weights,
    scoreable_ratio_codes_for_category,
)
from app.engines.common.credit_score_types import CreditRatioScoreWeight


_ACTIVE_CATEGORIES = (
    "liquidity", "leverage", "debt_service_capacity", "profitability", "activity", "growth",
)


def _real_benchmark_registry_codes() -> set:
    # bkz. test_health_score_registry_unit.py'deki AYNI izolasyon deseni --
    # paylaşılan process'te diğer test dosyalarının eklediği "_test_"
    # önekli geçici kayıtlar hariç tutulur.
    return {code for code in BENCHMARK_REGISTRY.keys() if not code.startswith("_")}


# --- Envanter / tamlık ------------------------------------------------------


def test_credit_ratio_score_weights_covers_every_benchmark_registry_entry():
    assert set(CREDIT_RATIO_SCORE_WEIGHTS.keys()) == _real_benchmark_registry_codes()


def test_every_category_ratio_weight_sums_to_exactly_one():
    for category in _ACTIVE_CATEGORIES:
        total = sum(
            w.ratio_weight for w in CREDIT_RATIO_SCORE_WEIGHTS.values() if w.category == category
        )
        assert total == Decimal("1"), f"{category}: {total}"


def test_scoreable_and_excluded_counts_per_category_match_design_doc_bolum_5_2():
    expected_scored = {
        "liquidity": 5, "leverage": 3, "debt_service_capacity": 3,
        "profitability": 17, "activity": 7, "growth": 6,
    }
    expected_excluded = {
        "liquidity": 1, "leverage": 3, "debt_service_capacity": 0,
        "profitability": 0, "activity": 3, "growth": 0,
    }
    for category in _ACTIVE_CATEGORIES:
        assert len(scoreable_ratio_codes_for_category(category)) == expected_scored[category], category
        assert len(excluded_duplicate_ratio_codes_for_category(category)) == expected_excluded[category], category


def test_total_scoreable_is_41_and_excluded_is_7():
    total_scoreable = sum(len(scoreable_ratio_codes_for_category(c)) for c in _ACTIVE_CATEGORIES)
    total_excluded = sum(len(excluded_duplicate_ratio_codes_for_category(c)) for c in _ACTIVE_CATEGORIES)
    assert total_scoreable == 41
    assert total_excluded == 7
    assert total_scoreable + total_excluded == len(_real_benchmark_registry_codes())


# --- Bölüm 7.2: equity_ratio / debt_to_equity politikası --------------------


def test_equity_ratio_is_scored_and_critical():
    w = CREDIT_RATIO_SCORE_WEIGHTS["equity_ratio"]
    assert w.ratio_weight > 0
    assert w.role == "critical"
    assert w.excluded_as_duplicate_of is None


def test_debt_to_equity_is_explainability_only_duplicate_of_equity_ratio():
    w = CREDIT_RATIO_SCORE_WEIGHTS["debt_to_equity"]
    assert w.ratio_weight == 0
    assert w.role == "explainability_only"
    assert w.excluded_as_duplicate_of == "equity_ratio"
    assert w.duplicate_relationship == "algebraic_complement"


def test_debt_ratio_and_financial_leverage_multiplier_are_also_duplicates_of_equity_ratio():
    debt_ratio = CREDIT_RATIO_SCORE_WEIGHTS["debt_ratio"]
    flm = CREDIT_RATIO_SCORE_WEIGHTS["financial_leverage_multiplier"]
    assert debt_ratio.ratio_weight == 0
    assert debt_ratio.excluded_as_duplicate_of == "equity_ratio"
    assert debt_ratio.role == "explainability_only"
    assert flm.ratio_weight == 0
    assert flm.excluded_as_duplicate_of == "equity_ratio"
    assert flm.role == "explainability_only"


def test_leverage_category_has_exactly_three_explainability_only_entries_all_pointing_to_equity_ratio():
    excluded = excluded_duplicate_ratio_codes_for_category("leverage")
    assert set(excluded) == {"debt_ratio", "financial_leverage_multiplier", "debt_to_equity"}
    for code in excluded:
        assert CREDIT_RATIO_SCORE_WEIGHTS[code].excluded_as_duplicate_of == "equity_ratio"


def test_long_term_debt_to_equity_and_short_term_debt_ratio_are_scored_supporting():
    ltde = CREDIT_RATIO_SCORE_WEIGHTS["long_term_debt_to_equity"]
    stdr = CREDIT_RATIO_SCORE_WEIGHTS["short_term_debt_ratio"]
    assert ltde.ratio_weight > 0 and ltde.role == "supporting"
    assert stdr.ratio_weight > 0 and stdr.role == "supporting"


def test_debt_to_equity_never_appears_in_critical_override_rules():
    assert all(rule.ratio_code != "debt_to_equity" for rule in CREDIT_CRITICAL_OVERRIDE_RULES)


def test_debt_to_equity_never_appears_in_hard_fail_predicates_source():
    # predicate'ler yalnızca equity_ratio/interest_coverage_ratio okur --
    # kaynak string denetimiyle (fonksiyonların KENDİ closure/global
    # referanslarına eriştiği anahtarlar) dolaylı ama gerçek bir kanıt.
    import inspect

    for rule in CREDIT_HARD_FAIL_RULES:
        source = inspect.getsource(rule.predicate)
        assert "debt_to_equity" not in source


# --- Diğer duplicate ilişkileri (kullanıcı rule #3) -------------------------


def test_working_capital_ratio_is_duplicate_of_current_ratio():
    w = CREDIT_RATIO_SCORE_WEIGHTS["working_capital_ratio"]
    assert w.ratio_weight == 0
    assert w.excluded_as_duplicate_of == "current_ratio"
    assert w.duplicate_relationship == "identical_formula"


def test_payables_turnover_is_duplicate_of_days_payables_outstanding():
    w = CREDIT_RATIO_SCORE_WEIGHTS["payables_turnover"]
    assert w.ratio_weight == 0
    assert w.excluded_as_duplicate_of == "days_payables_outstanding"
    assert CREDIT_RATIO_SCORE_WEIGHTS["days_payables_outstanding"].ratio_weight > 0


def test_days_inventory_and_days_sales_outstanding_are_duplicates():
    dio = CREDIT_RATIO_SCORE_WEIGHTS["days_inventory_outstanding"]
    dso = CREDIT_RATIO_SCORE_WEIGHTS["days_sales_outstanding"]
    assert dio.ratio_weight == 0 and dio.excluded_as_duplicate_of == "inventory_turnover"
    assert dso.ratio_weight == 0 and dso.excluded_as_duplicate_of == "receivables_turnover"


def test_cash_conversion_cycle_is_scored_critical_but_deweighted_summary_signal():
    ccc = CREDIT_RATIO_SCORE_WEIGHTS["cash_conversion_cycle"]
    assert ccc.ratio_weight > 0
    assert ccc.role == "critical"
    assert ccc.duplicate_relationship == "summary_signal_normalized"
    other_activity_scored = [
        w for code, w in CREDIT_RATIO_SCORE_WEIGHTS.items()
        if w.category == "activity" and code != "cash_conversion_cycle" and w.ratio_weight > 0
    ]
    assert all(ccc.ratio_weight < w.ratio_weight for w in other_activity_scored)


# --- Bölüm 8: kategori ağırlıkları -------------------------------------------


def test_global_category_weight_profile_matches_design_doc_bolum_8():
    profile = CREDIT_CATEGORY_WEIGHT_PROFILES[("global", None)]
    assert profile.category_weights == {
        "liquidity": Decimal("0.20"),
        "leverage": Decimal("0.25"),
        "debt_service_capacity": Decimal("0.25"),
        "profitability": Decimal("0.15"),
        "activity": Decimal("0.10"),
        "growth": Decimal("0.05"),
    }
    assert sum(profile.category_weights.values()) == Decimal("1")


def test_resolve_credit_category_weights_always_falls_back_to_global():
    profile = resolve_credit_category_weights(
        industry_code="tekstil", company_size_bucket="small", tenant_id="banka_x",
    )
    assert profile.scope == "global"
    assert profile.scope_key is None


# --- Bölüm 10: hard-fail kuralları -------------------------------------------


def test_hard_fail_rules_have_correct_ceilings():
    by_code = {r.rule_code: r for r in CREDIT_HARD_FAIL_RULES}
    assert by_code["NEGATIVE_EQUITY"].score_ceiling == Decimal("15")
    assert by_code["SEVERE_DEBT_SERVICE_SHORTFALL"].score_ceiling == Decimal("25")


def test_hard_fail_predicates_return_false_on_missing_data():
    for rule in CREDIT_HARD_FAIL_RULES:
        assert rule.predicate({}, {}) is False


def test_hard_fail_predicates_trigger_correctly():
    by_code = {r.rule_code: r for r in CREDIT_HARD_FAIL_RULES}
    assert by_code["NEGATIVE_EQUITY"].predicate({"equity_ratio": Decimal("-0.1")}, {}) is True
    assert by_code["NEGATIVE_EQUITY"].predicate({"equity_ratio": Decimal("0.1")}, {}) is False
    assert by_code["SEVERE_DEBT_SERVICE_SHORTFALL"].predicate(
        {"interest_coverage_ratio": Decimal("-1")}, {}
    ) is True


# --- Bölüm 9: critical override kuralları ------------------------------------


def test_critical_override_rules_have_exactly_5_entries_with_correct_multipliers():
    assert len(CREDIT_CRITICAL_OVERRIDE_RULES) == 5
    for rule in CREDIT_CRITICAL_OVERRIDE_RULES:
        assert rule.weak_multiplier == Decimal("0.90")
        assert rule.critical_multiplier == Decimal("0.65")
    assert {r.ratio_code for r in CREDIT_CRITICAL_OVERRIDE_RULES} == {
        "current_ratio", "equity_ratio", "interest_coverage_ratio",
        "net_profit_margin", "cash_conversion_cycle",
    }


def test_all_critical_override_ratios_are_role_critical_in_registry():
    for rule in CREDIT_CRITICAL_OVERRIDE_RULES:
        weight = CREDIT_RATIO_SCORE_WEIGHTS[rule.ratio_code]
        assert weight.role == "critical"
        assert weight.ratio_weight > 0


# --- Bölüm 13.1: BankingLensSignals kuralları --------------------------------


def test_banking_lens_signal_rules_has_exactly_6_expected_flags():
    assert len(CREDIT_BANKING_LENS_SIGNAL_RULES) == 6
    assert {r.flag_code for r in CREDIT_BANKING_LENS_SIGNAL_RULES} == {
        "SHORT_TERM_LIQUIDITY_STRAIN", "HIGH_LEVERAGE", "DEBT_SERVICE_STRESS",
        "WEAK_PROFIT_BUFFER", "WORKING_CAPITAL_STRAIN", "DEBT_FUNDED_GROWTH",
    }


def test_banking_lens_predicates_return_none_on_missing_data():
    for rule in CREDIT_BANKING_LENS_SIGNAL_RULES:
        assert rule.predicate({}) is None


# --- register_credit_ratio_score_weight validasyonu --------------------------


def test_duplicate_ratio_code_registration_rejected():
    try:
        register_credit_ratio_score_weight(
            CreditRatioScoreWeight(
                ratio_code="current_ratio", category="liquidity",
                ratio_weight=Decimal("0.5"), role="critical",
            )
        )
        assert False, "zaten kayıtlı ratio_code reddedilmeliydi"
    except ValueError:
        pass


def test_unknown_ratio_code_registration_rejected():
    try:
        register_credit_ratio_score_weight(
            CreditRatioScoreWeight(
                ratio_code="_not_a_real_ratio", category="liquidity",
                ratio_weight=Decimal("0.5"), role="supporting",
            )
        )
        assert False, "BENCHMARK_REGISTRY'de olmayan ratio_code reddedilmeliydi"
    except ValueError:
        pass


def test_zero_weight_without_duplicate_marker_rejected():
    try:
        register_credit_ratio_score_weight(
            CreditRatioScoreWeight(
                ratio_code="current_ratio", category="liquidity",
                ratio_weight=Decimal("0"), role="supporting",
            ),
            registry={},
        )
        assert False, "excluded_as_duplicate_of boşken ratio_weight=0 reddedilmeliydi"
    except ValueError:
        pass


def test_explainability_only_role_with_positive_weight_rejected():
    try:
        register_credit_ratio_score_weight(
            CreditRatioScoreWeight(
                ratio_code="current_ratio", category="liquidity",
                ratio_weight=Decimal("0.5"), role="explainability_only",
            ),
            registry={},
        )
        assert False, "ratio_weight>0 iken role=explainability_only reddedilmeliydi"
    except ValueError:
        pass


def test_critical_role_with_duplicate_marker_and_positive_weight_rejected():
    try:
        register_credit_ratio_score_weight(
            CreditRatioScoreWeight(
                ratio_code="working_capital_ratio", category="liquidity",
                ratio_weight=Decimal("0.1"), role="critical",
                excluded_as_duplicate_of="current_ratio",
                duplicate_relationship="identical_formula",
            ),
            registry={"current_ratio": CreditRatioScoreWeight(
                ratio_code="current_ratio", category="liquidity",
                ratio_weight=Decimal("1"), role="critical",
            )},
        )
        assert False, "excluded_as_duplicate_of dolu iken ratio_weight>0 reddedilmeliydi"
    except ValueError:
        pass


def test_chained_duplicate_rejected():
    isolated_registry = {
        "current_ratio": CreditRatioScoreWeight(
            ratio_code="current_ratio", category="liquidity",
            ratio_weight=Decimal("1"), role="critical",
        ),
    }
    register_credit_ratio_score_weight(
        CreditRatioScoreWeight(
            ratio_code="working_capital_ratio", category="liquidity",
            ratio_weight=Decimal("0"), role="explainability_only",
            excluded_as_duplicate_of="current_ratio",
            duplicate_relationship="identical_formula",
        ),
        registry=isolated_registry,
    )
    try:
        register_credit_ratio_score_weight(
            CreditRatioScoreWeight(
                ratio_code="quick_ratio", category="liquidity",
                ratio_weight=Decimal("0"), role="explainability_only",
                excluded_as_duplicate_of="working_capital_ratio",
                duplicate_relationship="identical_formula",
            ),
            registry=isolated_registry,
        )
        assert False, "zincirleme duplicate (kendisi de duplicate olan bir hedef) reddedilmeliydi"
    except ValueError:
        pass


def test_unknown_role_rejected():
    try:
        register_credit_ratio_score_weight(
            CreditRatioScoreWeight(
                ratio_code="current_ratio", category="liquidity",
                ratio_weight=Decimal("0.5"), role="not_a_real_role",
            ),
            registry={},
        )
        assert False, "bilinmeyen role reddedilmeliydi"
    except ValueError:
        pass
