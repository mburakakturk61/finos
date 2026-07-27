"""
Milestone 4.3D (Financial Health Score) / Adım 14: Property testleri.

Sabit (deterministik) tohum ile ÜRETİLEN çok sayıda rastgele girdi
kombinasyonu üzerinden, `compute_financial_health_score()`'un HER ZAMAN
doğru olması gereken değişmezlerini (invariant) doğrular:

  - Determinizm: aynı girdi -> bit-birebir aynı çıktı (her koşuda).
  - Clamp: final_score / kategori raw_score / score_after_override her
    zaman [0,100] aralığında (None hariç).
  - Confidence tavanı: confidence_score her zaman [0, 0.60] aralığında
    (BAĞLAYICI karar #13 -- tüm benchmark'lar provisional/internal_
    heuristic olduğu için v1 tavanı %60).
  - Ağırlık toplamı: COMPUTED/HARD_FAIL_CAPPED durumunda, tüm kategori
    `weight_applied` değerlerinin toplamı tam olarak 1.
  - Hard fail ceiling: bir hard-fail tetiklendiğinde final_score, o kuralın
    (registry'den okunan) ceiling'ini ASLA aşmaz.
  - Monotonicity garanti EDİLMEZ (Bölüm 22 karar #15): daha önce eksik olan
    bir oranın hesaplanır hale gelmesi, kategori/final skoru artırmak
    yerine DÜŞÜREBİLİR -- bu, gizlenen bir hata değil, açıkça kabul edilen
    bir davranıştır; burada somut bir örnekle kanıtlanır.
"""

import copy
import random
from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.health_score_registry import HARD_FAIL_RULES
from app.engines.common.health_score_types import HealthScoreComputationStatus
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score

_HARD_FAIL_CEILINGS = {rule.rule_code: rule.score_ceiling for rule in HARD_FAIL_RULES}


def _random_bs_facts(rng):
    current_assets = rng.uniform(200000, 5000000)
    non_current_assets = rng.uniform(200000, 5000000)
    short_term_liabilities = rng.uniform(100000, 4000000)
    long_term_liabilities = rng.uniform(50000, 2000000)
    total_assets = current_assets + non_current_assets
    equity = total_assets - short_term_liabilities - long_term_liabilities
    if rng.random() < 0.15:  # negatif özkaynak (hard fail) yolunu da örnekle
        equity = -abs(equity) - rng.uniform(1000, 500000)
    return {
        "current_assets": round(current_assets, 2),
        "short_term_liabilities": round(short_term_liabilities, 2),
        "long_term_liabilities": round(long_term_liabilities, 2),
        "total_assets": round(total_assets, 2),
        "equity": round(equity, 2),
        "inventory": round(current_assets * rng.uniform(0.05, 0.35), 2),
        "cash_and_equivalents": round(current_assets * rng.uniform(0.05, 0.4), 2),
        "trade_receivables": round(current_assets * rng.uniform(0.1, 0.4), 2),
        "trade_payables": round(short_term_liabilities * rng.uniform(0.2, 0.6), 2),
        "non_current_assets": round(non_current_assets, 2),
    }


def _random_is_facts(rng):
    net_sales = rng.uniform(1000000, 10000000)
    gross_margin = rng.uniform(0.15, 0.55)
    gross_profit = net_sales * gross_margin
    cost_of_sales = net_sales - gross_profit
    operating_margin = rng.uniform(0.02, gross_margin)
    operating_profit = net_sales * operating_margin
    operating_expenses = gross_profit - operating_profit
    financing_expenses = rng.uniform(10000, max(20000, net_sales * 0.05))
    other_operating_income = rng.uniform(0, 50000)
    other_operating_expenses = rng.uniform(0, 50000)
    ebit = operating_profit + other_operating_income - other_operating_expenses
    if rng.random() < 0.15:  # negatif faiz karşılama (hard fail) yolunu da örnekle
        ebit = -abs(ebit) - rng.uniform(1000, 200000)
    profit_before_tax = ebit - financing_expenses
    net_profit = profit_before_tax * rng.uniform(0.55, 0.85)
    ebitda = ebit + rng.uniform(50000, max(80000, net_sales * 0.08))
    return {
        "net_sales": round(net_sales, 2), "gross_profit": round(gross_profit, 2),
        "cost_of_sales": round(cost_of_sales, 2), "operating_profit": round(operating_profit, 2),
        "operating_expenses": round(operating_expenses, 2),
        "other_operating_income": round(other_operating_income, 2),
        "other_operating_expenses": round(other_operating_expenses, 2),
        "financing_expenses": round(financing_expenses, 2),
        "profit_before_tax": round(profit_before_tax, 2), "net_profit": round(net_profit, 2),
        "ebit": round(ebit, 2), "ebitda": round(ebitda, 2),
    }


def _random_case(rng, *, with_prior_period):
    bs_result = {"source_mode": "direct_document", "facts": _random_bs_facts(rng)}
    is_result = {"source_mode": "direct_document", "facts": _random_is_facts(rng)}
    prior_bs = prior_is = None
    if with_prior_period:
        prior_bs = {"source_mode": "direct_document", "facts": _random_bs_facts(rng)}
        prior_is = {"source_mode": "direct_document", "facts": _random_is_facts(rng)}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    return ratio_result, benchmark_result


_ITERATIONS = 40


def test_property_determinism_across_random_inputs():
    rng = random.Random(20260727)
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        first = compute_financial_health_score(ratio_result, benchmark_result)
        second = compute_financial_health_score(ratio_result, benchmark_result)
        assert first == second, f"iterasyon {i}: determinizm ihlali"


def test_property_final_and_category_scores_always_clamped_0_100():
    rng = random.Random(20260727)
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_financial_health_score(ratio_result, benchmark_result)

        if result.final_score is not None:
            assert Decimal("0") <= result.final_score <= Decimal("100"), f"iterasyon {i}"
        for breakdown in result.category_breakdown:
            if breakdown.raw_score is not None:
                assert Decimal("0") <= breakdown.raw_score <= Decimal("100"), (i, breakdown.category)
            if breakdown.score_after_override is not None:
                assert Decimal("0") <= breakdown.score_after_override <= Decimal("100"), (i, breakdown.category)


def test_property_confidence_score_never_exceeds_v1_ceiling():
    rng = random.Random(20260727)
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_financial_health_score(ratio_result, benchmark_result)
        assert Decimal("0") <= result.confidence_score <= Decimal("0.60"), f"iterasyon {i}"


def test_property_category_weights_sum_to_one_when_score_produced():
    rng = random.Random(20260727)
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_financial_health_score(ratio_result, benchmark_result)
        if result.status in (
            HealthScoreComputationStatus.COMPUTED, HealthScoreComputationStatus.HARD_FAIL_CAPPED,
        ):
            total_weight = sum((b.weight_applied for b in result.category_breakdown), Decimal("0"))
            assert total_weight == Decimal("1"), f"iterasyon {i}: toplam={total_weight}"


def test_property_hard_fail_never_exceeds_registered_ceiling():
    rng = random.Random(20260727)
    triggered_at_least_once = False
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_financial_health_score(ratio_result, benchmark_result)
        if result.hard_fails_triggered:
            triggered_at_least_once = True
            applicable_ceiling = min(
                _HARD_FAIL_CEILINGS[code] for code in result.hard_fails_triggered
            )
            assert result.final_score is not None
            assert result.final_score <= applicable_ceiling, f"iterasyon {i}"
    # rastgele üretimin negatif özkaynak/negatif faiz karşılama yollarını
    # gerçekten örneklediğini doğrula -- aksi halde bu test hiçbir şeyi
    # kanıtlamadan yeşil geçebilir (sahte pozitif riskine karşı).
    assert triggered_at_least_once, "40 iterasyonda hiç hard-fail tetiklenmedi -- rastgele üretim gözden geçirilmeli"


# --- Monotonicity GARANTİ EDİLMEZ (Bölüm 22 karar #15) -- kabul testi ------


def test_property_more_data_can_decrease_score_monotonicity_not_guaranteed():
    # Diğer likidite oranları (current_ratio/cash_ratio/defensive_interval_
    # ratio/working_capital_to_total_assets) "good"/"excellent" bantta iyi
    # durumda; ama envanter ağırlıklı bir current_assets yapısı yüzünden
    # quick_ratio "critical" bantta (0.15 < critical eşiği 0.4) -- gerçek
    # registry eşikleriyle doğrulanmış somut bir sayısal fikstür (bkz.
    # diagnostic script çıktısı: current_ratio=good/87.5,
    # cash_ratio=good/52.5, defensive_interval_ratio=good/50.4,
    # working_capital_to_total_assets=excellent/100, quick_ratio=critical/0).
    bs_facts = {
        "current_assets": 1400000.0, "short_term_liabilities": 1000000.0,
        "long_term_liabilities": 300000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 1250000.0, "cash_and_equivalents": 550000.0,
        "trade_receivables": 500000.0, "trade_payables": 300000.0,
        "non_current_assets": 1600000.0,
    }
    is_facts = {
        "net_sales": 6000000.0, "gross_profit": 3000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 1800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 80000.0, "profit_before_tax": 1770000.0,
        "net_profit": 1450000.0, "ebit": 1850000.0, "ebitda": 2000000.0,
    }
    bs_result = {"source_mode": "direct_document", "facts": bs_facts}
    is_result = {"source_mode": "direct_document", "facts": is_facts}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result_full = evaluate_benchmarks(ratio_result)

    # "ÖNCE": quick_ratio henüz hesaplanamıyor (ör. envanter/nakit kırılımı
    # elde YENİ document'ta yoktu) -- yalnızca current_ratio scoreable.
    ratio_result_before = copy.deepcopy(ratio_result)
    benchmark_result_before = copy.deepcopy(benchmark_result_full)
    ratio_result_before["categories"]["liquidity"]["ratios"]["quick_ratio"] = {
        "value": None, "status": "missing_input", "reliability": "not_calculable",
    }
    benchmark_result_before["categories"]["liquidity"]["ratios"]["quick_ratio"] = {
        "status": "ratio_status_not_calculated", "tier": None,
        "reliability": "not_calculable", "warnings": [],
    }

    # "SONRA": aynı şirket, quick_ratio da ARTIK hesaplanabiliyor (DAHA
    # FAZLA veri geldi) -- ama gerçek değeri kritik bantta (0.15), bu yüzden
    # kategori/final skor DÜŞER (diğer 4 oranın ortalaması quick_ratio'nun
    # 0 puanından belirgin şekilde yüksek: ~72,6 -> ~58,1).
    result_before = compute_financial_health_score(ratio_result_before, benchmark_result_before)
    result_after = compute_financial_health_score(ratio_result, benchmark_result_full)

    before_liquidity = next(b for b in result_before.category_breakdown if b.category == "liquidity")
    after_liquidity = next(b for b in result_after.category_breakdown if b.category == "liquidity")
    assert before_liquidity.raw_score is not None
    assert after_liquidity.raw_score is not None
    # Daha fazla veri (quick_ratio artık scoreable) geldiği hâlde likidite
    # kategori skoru DÜŞTÜ -- monotonicity garanti edilmediğinin kanıtı.
    assert after_liquidity.raw_score < before_liquidity.raw_score
    assert result_after.final_score is not None and result_before.final_score is not None
    assert result_after.final_score <= result_before.final_score
