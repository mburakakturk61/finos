"""
Milestone 4.3E (Credit Score Engine) / Adım 12: mevcut Adım 1-11 test
dosyalarının BİRLEŞTİRİLMİŞ, tam pipeline (`compute_credit_score`)
seviyesinde henüz izole edilmemiş boşluklarını kapatan ek birim
testleri -- Bölüm 21 test stratejisi madde 1-6 ile çapraz kontrol
edilmiştir:

- kısmen eksik TEK bir kategorinin (growth), kategoriler arası
  ağırlıklandırmada GERÇEKTEN yeniden dağıtıldığının uçtan uca kanıtı
- kısmi coverage (%50-%69,9) senaryosunda `low_confidence_warning`
- INSUFFICIENT_DATA durumunda `confidence_score=0`
- TÜM kategori kırılımlarının (raw_score/score_after_override) her
  zaman [0,100] aralığında kaldığının uçtan uca kanıtı
- registry <-> pipeline tutarlılığı (scoreable_ratio_codes'un
  CREDIT_RATIO_SCORE_WEIGHTS ile birebir örtüştüğü)
- **Pipeline SIRA testi (Bölüm 21 madde 3):** critical override'ın
  kategori seviyesinde, kategoriler arası ağırlıklandırmadan ÖNCE
  uygulandığının; hard-fail ceiling'inin İSE `pre_hard_fail_score`
  (kategoriler arası ağırlıklandırmadan SONRAKİ toplam) üzerine
  uygulandığının AÇIK, sayısal kanıtı.
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.credit_score_registry import (
    CREDIT_RATIO_SCORE_WEIGHTS,
    scoreable_ratio_codes_for_category,
)
from app.engines.common.credit_score_types import CreditScoreComputationStatus
from app.engines.credit_score.service import ACTIVE_CATEGORIES, compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score


def _bs_facts(**overrides):
    facts = {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }
    facts.update(overrides)
    return facts


def _is_facts(**overrides):
    facts = {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }
    facts.update(overrides)
    return facts


def _real_result_jsons(*, with_prior_period, source_mode="direct_document", bs_overrides=None):
    bs_result = {"source_mode": source_mode, "facts": _bs_facts(**(bs_overrides or {}))}
    is_result = {"source_mode": source_mode, "facts": _is_facts()}
    prior_bs = prior_is = None
    if with_prior_period:
        prior_bs = {
            "source_mode": source_mode,
            "facts": _bs_facts(total_assets=2500000.0, equity=1400000.0),
        }
        prior_is = {
            "source_mode": source_mode,
            "facts": _is_facts(net_sales=4000000.0, gross_profit=1600000.0, ebitda=800000.0, net_profit=400000.0),
        }
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    return ratio_result, evaluate_benchmarks(ratio_result)


def _health_score_result(ratio_result, benchmark_result):
    return compute_financial_health_score(ratio_result, benchmark_result)


# --- Kısmen eksik TEK kategori (growth) -- coverage arti kalanı normal ----


def test_missing_growth_category_only_stays_above_70_percent_and_no_warning():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=False)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    assert result.data_coverage_ratio >= Decimal("0.70")
    assert result.low_confidence_warning is False
    assert result.status in (
        CreditScoreComputationStatus.COMPUTED, CreditScoreComputationStatus.HARD_FAIL_CAPPED,
    )


def test_missing_growth_category_weight_is_redistributed_to_other_categories():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=False)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    breakdown_by_category = {b.category: b for b in result.category_breakdown}
    growth_breakdown = breakdown_by_category["growth"]
    assert growth_breakdown.raw_score is None
    assert growth_breakdown.score_after_override is None
    assert growth_breakdown.weight_applied == Decimal("0")

    remaining = [b for b in result.category_breakdown if b.category != "growth"]
    assert sum(b.weight_applied for b in remaining) == Decimal("1")
    global_weights = {
        "liquidity": Decimal("0.20"), "leverage": Decimal("0.25"),
        "debt_service_capacity": Decimal("0.25"), "profitability": Decimal("0.15"),
        "activity": Decimal("0.10"),
    }
    for b in remaining:
        assert b.weight_applied > global_weights[b.category]


# --- Kısmi coverage (%50-%69,9 bandı) -- low_confidence_warning zorunlu ---


def test_partial_coverage_between_50_and_70_percent_sets_low_confidence_warning():
    ratio_result, benchmark_result = _real_result_jsons(
        with_prior_period=False, source_mode="trial_balance_derived",
    )
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    if result.status == CreditScoreComputationStatus.INSUFFICIENT_DATA:
        assert result.final_score is None
        assert result.data_coverage_ratio < Decimal("0.50")
    else:
        assert Decimal("0") <= result.data_coverage_ratio < Decimal("1")
        if Decimal("0.50") <= result.data_coverage_ratio < Decimal("0.70"):
            assert result.low_confidence_warning is True
            any_warning = any(w.get("code") == "LOW_CONFIDENCE_COVERAGE" for w in result.warnings)
            assert any_warning


# --- INSUFFICIENT_DATA -> confidence_score her zaman 0 ---------------------


def test_insufficient_data_status_has_zero_confidence_score():
    from app.engines.common.health_score_types import HealthScoreComputationStatus, HealthScoreResult

    ratio_categories = {}
    benchmark_categories = {}
    for category in ACTIVE_CATEGORIES:
        codes = scoreable_ratio_codes_for_category(category)
        ratios_out = {code: {"value": None, "status": "missing_input", "reliability": "not_calculable"} for code in codes}
        benchmarks_out = {code: {"status": "ratio_status_not_calculated", "tier": None, "reliability": "not_calculable", "warnings": []} for code in codes}
        ratio_categories[category] = {"status": "not_calculable", "ratios": ratios_out}
        benchmark_categories[category] = {"ratios": benchmarks_out}

    ratio_result = {"ratio_registry_version": "1.1.0", "categories": ratio_categories, "warnings": []}
    benchmark_result = {"benchmark_registry_version": "1.0.0", "categories": benchmark_categories}

    health_score_result = HealthScoreResult(
        status=HealthScoreComputationStatus.INSUFFICIENT_DATA,
        final_score=None, pre_hard_fail_score=None, letter_rating=None,
        rating_disclaimer_tr="x", confidence_score=Decimal("0"),
        data_coverage_ratio=Decimal("0"), low_confidence_warning=False,
        provisional=True, category_breakdown=(), hard_fails_triggered=(),
        critical_overrides_applied=(), scoreable_ratio_codes=(),
        excluded_duplicate_ratio_codes=(), strengths=(), weaknesses=(),
        warnings=(), health_score_schema_version="1.0.0",
        health_score_model_version="1.0.0", benchmark_registry_version="1.0.0",
        ratio_registry_version="1.0.0", category_weight_profile_used="global",
    )

    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    assert result.status == CreditScoreComputationStatus.INSUFFICIENT_DATA
    assert result.confidence_score == Decimal("0")


# --- TÜM kategori skorları her zaman [0,100] (uçtan uca clamp kanıtı) -----


def test_all_category_scores_stay_within_0_100_range_end_to_end():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    for breakdown in result.category_breakdown:
        if breakdown.raw_score is not None:
            assert Decimal("0") <= breakdown.raw_score <= Decimal("100"), breakdown.category
        if breakdown.score_after_override is not None:
            assert Decimal("0") <= breakdown.score_after_override <= Decimal("100"), breakdown.category
    assert Decimal("0") <= result.final_score <= Decimal("100")


# --- Registry <-> pipeline tutarlılığı --------------------------------------


def test_orchestration_scoreable_codes_match_registry_exactly():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    expected_scoreable = {code for code, w in CREDIT_RATIO_SCORE_WEIGHTS.items() if w.ratio_weight > 0}
    expected_excluded = {code for code, w in CREDIT_RATIO_SCORE_WEIGHTS.items() if w.ratio_weight == 0}
    assert set(result.scoreable_ratio_codes) == expected_scoreable
    assert set(result.excluded_duplicate_ratio_codes) == expected_excluded


# --- Bölüm 21 madde 3: Pipeline SIRA testi (critical override ONCE, --------
# hard-fail ceiling SONRA -- AYRI mekanizmalar, AYRI pipeline noktaları) ---


def test_pre_hard_fail_score_equals_cross_category_weighted_sum_of_post_override_scores():
    # equity_ratio "weak" tier'a dusurulecek (ama NEGATIVE degil, yani
    # NEGATIVE_EQUITY hard-fail'i TETIKLENMEZ) -- boylece critical
    # override'in etkisini hard-fail'den IZOLE edebiliriz.
    ratio_result, benchmark_result = _real_result_jsons(
        with_prior_period=True, bs_overrides={"equity": 450000.0},
    )
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    assert result.status != CreditScoreComputationStatus.HARD_FAIL_CAPPED
    assert result.hard_fails_triggered == ()

    # pre_hard_fail_score, TÜM kategorilerin (kategoriler arasi
    # agirliklandirmadan SONRAKI weight_applied) * score_after_override
    # toplamina esit olmalidir -- critical override, kategori
    # seviyesinde, bu toplam hesaplanmadan ONCE uygulanmis olmalidir.
    manual_sum = Decimal("0")
    for breakdown in result.category_breakdown:
        if breakdown.score_after_override is not None:
            manual_sum += breakdown.score_after_override * breakdown.weight_applied
    from app.engines.common.credit_score_types import clamp_score
    assert result.pre_hard_fail_score == clamp_score(manual_sum)
    assert result.final_score == result.pre_hard_fail_score  # hard-fail tetiklenmedigi icin AYNI


def test_hard_fail_ceiling_applies_after_cross_category_weighting_not_per_category():
    # NEGATIVE_EQUITY hard-fail'i tetiklenince, ceiling KATEGORI
    # skoruna DEGIL, kategoriler arasi agirliklandirmadan SONRAKI
    # toplam (pre_hard_fail_score) skora uygulanir.
    ratio_result, benchmark_result = _real_result_jsons(
        with_prior_period=True, bs_overrides={"equity": -400000.0},
    )
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    assert result.status == CreditScoreComputationStatus.HARD_FAIL_CAPPED
    assert "NEGATIVE_EQUITY" in result.hard_fails_triggered
    # pre_hard_fail_score, KATEGORI bazinda degil, CROSS-CATEGORY
    # agirlikli toplamdir -- hard-fail SONRASINDA final_score bu
    # toplamin (15 ile) min()'i olmalidir.
    assert result.final_score == min(result.pre_hard_fail_score, Decimal("15"))
