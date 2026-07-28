"""
Milestone 4.3F (Recommendation Engine) / Adım 2: `app/engines/common/
recommendation_registry.py` için gerçek, çalıştırılabilir birim testleri.

Bölüm 28 madde 2/3 -- Bölüm 8.2'nin 12 maddelik doğrulaması (registry
importunun KENDİSİ zaten bu doğrulamayı çalıştırır -- burada AYRICA,
izole `_test_*` kayıtlarıyla NEGATİF kontroller de yapılır).
"""

from collections import Counter
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.common.ratio_formulas import RATIO_REGISTRY
from app.engines.common.recommendation_registry import (
    BANKING_FLAG_TO_RATIO_OVERLAP,
    RECOMMENDATION_CONFLICT_PAIRS,
    RECOMMENDATION_INPUT_COMPATIBILITY,
    RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS,
    RECOMMENDATION_RULES,
    _validate_cross_rule_references,
    register_recommendation_rule,
)
from app.engines.common.recommendation_types import (
    EvidenceRule,
    RecommendationCategory,
    RecommendationDifficultyBand,
    RecommendationImpactBand,
    RecommendationPriority,
    RecommendationRule,
    RecommendationSeverity,
    RecommendationTriggerStrategy,
    ResultBucket,
    resolve_disclaimer_tr,
)


def _make_minimal_rule(**overrides) -> RecommendationRule:
    defaults = dict(
        recommendation_code="_test_rule",
        category=RecommendationCategory.LIQUIDITY,
        result_bucket=ResultBucket.FINANCIAL,
        base_priority=RecommendationPriority.MEDIUM,
        severity=RecommendationSeverity.MEDIUM,
        impact_band=RecommendationImpactBand.MEDIUM,
        difficulty_band=RecommendationDifficultyBand.MODERATE_EFFORT,
        trigger_strategy=RecommendationTriggerStrategy.ALL_CONDITIONS,
        trigger_mode="all",
        evidence_rules=(EvidenceRule(ratio_code="current_ratio", tier_in=("critical",)),),
        minimum_evidence_count=1,
        prerequisite_rules=(),
        blocking_rules=(),
        merge_group=None,
        evidence_group="_test_group",
        underlying_risk_code="_TEST_RISK",
        conflict_group=None,
        mutually_exclusive_group=None,
        confidence_ceiling=Decimal("0.75"),
        coverage_policy="subject_to_gate",
        related_ratio_codes=("current_ratio",),
        title_tr="Test",
        explanation_tr="Test",
        action_steps_tr=("Test",),
        assumptions_tr=("Test",),
        disclaimer_tr=resolve_disclaimer_tr("general"),
        disclaimer_scope="general",
        model_version_introduced="1.0.0",
        deprecated_since=None,
        replacement_recommendation_code=None,
    )
    defaults.update(overrides)
    return RecommendationRule(**defaults)


# --- Envanter / tamlık (Bölüm 20a/37.1) ------------------------------------


def test_exactly_39_rules_registered():
    assert len(RECOMMENDATION_RULES) == 39


def test_category_distribution_matches_bolum_37_1_exactly():
    counts = Counter(r.category.value for r in RECOMMENDATION_RULES)
    assert counts == Counter({
        "working_capital": 6, "liquidity": 4, "leverage": 4, "profitability": 4,
        "activity": 2, "growth": 3, "banking_readiness": 6, "data_quality": 10,
    })


def test_result_bucket_distribution_23_financial_6_banking_10_data_quality():
    counts = Counter(r.result_bucket.value for r in RECOMMENDATION_RULES)
    assert counts["financial"] == 23
    assert counts["banking_readiness"] == 6
    assert counts["data_quality"] == 10


def test_all_recommendation_codes_unique():
    codes = [r.recommendation_code for r in RECOMMENDATION_RULES]
    assert len(codes) == len(set(codes))


def test_no_placeholder_titles_or_explanations():
    for rule in RECOMMENDATION_RULES:
        assert rule.title_tr and rule.title_tr.strip() != ""
        assert rule.explanation_tr and rule.explanation_tr.strip() != ""
        assert len(rule.action_steps_tr) >= 1
        assert "TODO" not in rule.title_tr.upper()
        assert "PLACEHOLDER" not in rule.explanation_tr.upper()


def test_exactly_2_hard_fail_sourced_rules_exempt_from_coverage_gate():
    exempt = [r for r in RECOMMENDATION_RULES if r.coverage_policy == "exempt_hard_fail"]
    assert {r.recommendation_code for r in exempt} == {
        "LEV_STRENGTHEN_EQUITY_BASE", "LEV_IMPROVE_INTEREST_COVERAGE",
    }


def test_all_data_quality_rules_are_always_evaluated():
    for rule in RECOMMENDATION_RULES:
        if rule.category == RecommendationCategory.DATA_QUALITY:
            assert rule.coverage_policy == "always_evaluated"


def test_exactly_6_merge_groups_with_2_members_each():
    groups = Counter(r.merge_group for r in RECOMMENDATION_RULES if r.merge_group is not None)
    assert len(groups) == 6
    assert all(count == 2 for count in groups.values())
    assert sum(groups.values()) == 12


def test_conflict_pairs_intentionally_empty_in_v1():
    assert RECOMMENDATION_CONFLICT_PAIRS == ()


def test_exactly_1_mutually_exclusive_group():
    assert len(RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS) == 1
    group = RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS[0]
    assert group.mutually_exclusive_group_id == "MEG_INVENTORY_LEVEL"
    assert set(group.recommendation_codes) == {"WC_REDUCE_INVENTORY_DAYS", "WC_MAINTAIN_INVENTORY_SAFETY_BUFFER"}


def test_zero_prerequisite_and_blocking_relationships_in_v1():
    for rule in RECOMMENDATION_RULES:
        assert rule.prerequisite_rules == ()
        assert rule.blocking_rules == ()


def test_informational_priority_only_in_banking_readiness_or_data_quality():
    for rule in RECOMMENDATION_RULES:
        if rule.base_priority == RecommendationPriority.INFORMATIONAL:
            assert rule.result_bucket in (ResultBucket.BANKING_READINESS, ResultBucket.DATA_QUALITY)


def test_all_related_ratio_codes_exist_in_ratio_registry():
    for rule in RECOMMENDATION_RULES:
        for ratio_code in rule.related_ratio_codes:
            assert ratio_code in RATIO_REGISTRY, f"{rule.recommendation_code}: {ratio_code}"


def test_banking_disclaimer_scope_equivalence():
    for rule in RECOMMENDATION_RULES:
        assert (rule.disclaimer_scope == "banking") == (rule.category == RecommendationCategory.BANKING_READINESS)


def test_all_model_versions_are_1_0_0_and_none_deprecated():
    for rule in RECOMMENDATION_RULES:
        assert rule.model_version_introduced == "1.0.0"
        assert rule.deprecated_since is None
        assert rule.replacement_recommendation_code is None


def test_banking_flag_to_ratio_overlap_covers_all_6_known_flags():
    assert set(BANKING_FLAG_TO_RATIO_OVERLAP.keys()) == {
        "SHORT_TERM_LIQUIDITY_STRAIN", "HIGH_LEVERAGE", "DEBT_SERVICE_STRESS",
        "WEAK_PROFIT_BUFFER", "WORKING_CAPITAL_STRAIN", "DEBT_FUNDED_GROWTH",
    }


def test_recommendation_input_compatibility_has_4_axes():
    assert set(RECOMMENDATION_INPUT_COMPATIBILITY.keys()) == {
        "health_score_schema_versions", "credit_score_schema_versions",
        "ratio_registry_versions", "benchmark_registry_versions",
    }
    for value in RECOMMENDATION_INPUT_COMPATIBILITY.values():
        assert isinstance(value, frozenset)


# --- Negatif kontroller (Bölüm 8.2'nin kayıt-anı reddi) --------------------


def test_duplicate_recommendation_code_rejected():
    registry = {}
    register_recommendation_rule(_make_minimal_rule(), registry=registry)
    try:
        register_recommendation_rule(_make_minimal_rule(), registry=registry)
        assert False, "İkinci kayıt REDDEDİLMELİYDİ."
    except ValueError:
        pass


def test_unregistered_related_ratio_code_rejected():
    registry = {}
    try:
        register_recommendation_rule(
            _make_minimal_rule(related_ratio_codes=("_totally_unknown_ratio_code",)),
            registry=registry,
        )
        assert False, "Bilinmeyen ratio_code REDDEDİLMELİYDİ."
    except ValueError:
        pass


def test_category_ratio_mismatch_rejected_for_financial_bucket():
    registry = {}
    try:
        # net_profit_margin PROFITABILITY'de, kural LIQUIDITY iddia ediyor.
        register_recommendation_rule(
            _make_minimal_rule(
                related_ratio_codes=("net_profit_margin",),
                evidence_rules=(EvidenceRule(ratio_code="net_profit_margin", tier_in=("critical",)),),
            ),
            registry=registry,
        )
        assert False, "Kategori/ratio tutarsızlığı REDDEDİLMELİYDİ."
    except ValueError:
        pass


def test_evidence_rule_must_fill_exactly_one_condition_type():
    registry = {}
    try:
        register_recommendation_rule(
            _make_minimal_rule(
                evidence_rules=(EvidenceRule(ratio_code="current_ratio", hard_fail_code="NEGATIVE_EQUITY"),),
            ),
            registry=registry,
        )
        assert False, "Çoklu koşul türü REDDEDİLMELİYDİ."
    except ValueError:
        pass


def test_informational_priority_rejected_for_financial_bucket():
    registry = {}
    try:
        register_recommendation_rule(
            _make_minimal_rule(base_priority=RecommendationPriority.INFORMATIONAL),
            registry=registry,
        )
        assert False, "FINANCIAL bucket'ında INFORMATIONAL REDDEDİLMELİYDİ."
    except ValueError:
        pass


def test_disclaimer_scope_banking_requires_banking_readiness_category():
    registry = {}
    try:
        register_recommendation_rule(
            _make_minimal_rule(disclaimer_scope="banking"),
            registry=registry,
        )
        assert False, "disclaimer_scope='banking' + category != BANKING_READINESS REDDEDİLMELİYDİ."
    except ValueError:
        pass


def test_hard_fail_present_requires_exempt_hard_fail_and_critical_severity():
    registry = {}
    try:
        register_recommendation_rule(
            _make_minimal_rule(
                trigger_strategy=RecommendationTriggerStrategy.HARD_FAIL_PRESENT,
                evidence_rules=(EvidenceRule(hard_fail_code="NEGATIVE_EQUITY"),),
                related_ratio_codes=(),
                coverage_policy="subject_to_gate",
            ),
            registry=registry,
        )
        assert False, "HARD_FAIL_PRESENT + subject_to_gate REDDEDİLMELİYDİ."
    except ValueError:
        pass


def test_mutually_exclusive_group_requires_at_least_2_members():
    try:
        _validate_cross_rule_references(
            (_make_minimal_rule(mutually_exclusive_group="_TEST_SOLO_GROUP"),)
        )
        assert False, "Tek üyeli mutually_exclusive_group REDDEDİLMELİYDİ."
    except ValueError:
        pass
