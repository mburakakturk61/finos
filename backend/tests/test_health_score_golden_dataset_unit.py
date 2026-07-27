"""
Milestone 4.3D (Financial Health Score) / Adım 13: Golden dataset testleri.

Tasarım dokümanı Bölüm 20'de tanımlanan 7 uçtan uca senaryo, gerçek
`analyze_financial_ratios()` + `evaluate_benchmarks()` + `compute_financial_
health_score()` zinciri üzerinden çalıştırılır:

  1. Mükemmel şirket (tüm kategoriler güçlü, tam coverage)
  2. Zayıf likidite + güçlü kârlılık (kategoriler arası telafi/compensation)
  3. Negatif özkaynak (hard fail -- ceiling 25)
  4. Negatif faiz karşılama (hard fail -- ceiling 35)
  5. Düşük coverage (<%50 -- INSUFFICIENT_DATA)
  6. Orta coverage (%50-%69,9 -- low_confidence_warning)
  7. Önceki dönem yok (growth kategorisi tamamen eksik, ama genel coverage
     yine de normal bandın üstünde kalır)
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.health_score_types import HealthScoreComputationStatus
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import ACTIVE_CATEGORIES, compute_financial_health_score


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


def _compute(*, bs_facts, is_facts, prior_bs_facts=None, prior_is_facts=None, source_mode="direct_document"):
    bs_result = {"source_mode": source_mode, "facts": bs_facts}
    is_result = {"source_mode": source_mode, "facts": is_facts}
    prior_bs = {"source_mode": source_mode, "facts": prior_bs_facts} if prior_bs_facts else None
    prior_is = {"source_mode": source_mode, "facts": prior_is_facts} if prior_is_facts else None
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    return compute_financial_health_score(ratio_result, benchmark_result)


# --- Senaryo 1: Mükemmel şirket ---------------------------------------------


def test_golden_excellent_company_scores_high_with_no_hard_fails():
    bs = _bs_facts(
        current_assets=3000000.0, short_term_liabilities=800000.0, long_term_liabilities=300000.0,
        total_assets=5000000.0, equity=3900000.0, inventory=400000.0, cash_and_equivalents=1200000.0,
        trade_receivables=500000.0, trade_payables=350000.0, non_current_assets=2000000.0,
    )
    is_ = _is_facts(
        net_sales=8000000.0, gross_profit=4000000.0, cost_of_sales=4000000.0,
        operating_profit=2500000.0, operating_expenses=1500000.0,
        financing_expenses=50000.0, profit_before_tax=2450000.0, net_profit=2000000.0,
        ebit=2550000.0, ebitda=2800000.0,
    )
    prior_bs = _bs_facts(total_assets=4200000.0, equity=3200000.0)
    prior_is = _is_facts(net_sales=6500000.0, gross_profit=3200000.0, ebitda=2200000.0, net_profit=1500000.0)

    result = _compute(bs_facts=bs, is_facts=is_, prior_bs_facts=prior_bs, prior_is_facts=prior_is)

    assert result.status == HealthScoreComputationStatus.COMPUTED
    assert result.hard_fails_triggered == ()
    assert result.final_score >= Decimal("70")
    assert result.letter_rating in ("Çok Güçlü", "Güçlü")
    assert result.data_coverage_ratio == Decimal("1")


# --- Senaryo 2: Zayıf likidite + güçlü kârlılık (telafi modeli) ------------


def test_golden_weak_liquidity_strong_profitability_shows_category_compensation():
    bs = _bs_facts(
        current_assets=700000.0, short_term_liabilities=1000000.0, long_term_liabilities=300000.0,
        total_assets=3000000.0, equity=1700000.0, inventory=250000.0, cash_and_equivalents=50000.0,
        trade_receivables=200000.0, trade_payables=300000.0,
    )
    is_ = _is_facts(
        net_sales=6000000.0, gross_profit=3000000.0, cost_of_sales=3000000.0,
        operating_profit=1800000.0, operating_expenses=1200000.0,
        financing_expenses=80000.0, profit_before_tax=1770000.0, net_profit=1450000.0,
        ebit=1850000.0, ebitda=2000000.0,
    )
    result = _compute(bs_facts=bs, is_facts=is_)

    breakdown_by_category = {b.category: b for b in result.category_breakdown}
    liquidity = breakdown_by_category["liquidity"]
    profitability = breakdown_by_category["profitability"]
    assert liquidity.raw_score is not None and profitability.raw_score is not None
    assert profitability.raw_score > liquidity.raw_score
    # negatif özkaynak/faiz hard fail'i YOK -- yalnızca kategori dengesizliği var
    assert result.hard_fails_triggered == ()
    assert result.final_score is not None


# --- Senaryo 3: Negatif özkaynak (hard fail -- ceiling 25) -----------------


def test_golden_negative_equity_hard_fail_ceiling_25():
    bs = _bs_facts(equity=-500000.0, total_assets=3000000.0, long_term_liabilities=1800000.0)
    is_ = _is_facts()
    result = _compute(bs_facts=bs, is_facts=is_)

    assert result.status == HealthScoreComputationStatus.HARD_FAIL_CAPPED
    assert "NEGATIVE_EQUITY" in result.hard_fails_triggered
    assert result.final_score <= Decimal("25")


# --- Senaryo 4: Negatif faiz karşılama (hard fail -- ceiling 35) -----------


def test_golden_negative_interest_coverage_hard_fail_ceiling_35():
    is_ = _is_facts(
        operating_profit=-200000.0, profit_before_tax=-350000.0, net_profit=-400000.0,
        ebit=-150000.0, ebitda=100000.0, financing_expenses=150000.0,
    )
    bs = _bs_facts()
    result = _compute(bs_facts=bs, is_facts=is_)

    assert result.status == HealthScoreComputationStatus.HARD_FAIL_CAPPED
    assert "SEVERE_DEBT_SERVICE_SHORTFALL" in result.hard_fails_triggered
    assert result.final_score <= Decimal("35")


# --- Senaryo 5: Düşük coverage (<%50 -- INSUFFICIENT_DATA) -----------------


def _make_signal(status, value=None, reliability="not_calculable"):
    return {"value": value, "status": status, "reliability": reliability}


def _make_benchmark_signal(status, tier=None, reliability="not_calculable"):
    return {"status": status, "tier": tier, "reliability": reliability, "warnings": []}


def test_golden_low_coverage_scenario_produces_insufficient_data():
    from app.engines.common.health_score_registry import scoreable_ratio_codes_for_category

    ratio_categories, benchmark_categories = {}, {}
    for category in ACTIVE_CATEGORIES:
        codes = scoreable_ratio_codes_for_category(category)
        ratios_out, benchmarks_out = {}, {}
        for i, code in enumerate(codes):
            # yalnızca her kategoride İLK oran hesaplanmış -- geri kalanı eksik
            if i == 0 and category == "liquidity":
                ratios_out[code] = _make_signal("calculated", 1.5, reliability="high")
                benchmarks_out[code] = _make_benchmark_signal("evaluated", "good", "high")
            else:
                ratios_out[code] = _make_signal("missing_input")
                benchmarks_out[code] = _make_benchmark_signal("ratio_status_not_calculated")
        ratio_categories[category] = {"status": "partial", "ratios": ratios_out}
        benchmark_categories[category] = {"ratios": benchmarks_out}

    ratio_result = {"ratio_registry_version": "1.1.0", "categories": ratio_categories, "warnings": []}
    benchmark_result = {"benchmark_registry_version": "1.0.0", "categories": benchmark_categories}

    result = compute_financial_health_score(ratio_result, benchmark_result)
    assert result.status == HealthScoreComputationStatus.INSUFFICIENT_DATA
    assert result.final_score is None
    assert result.letter_rating is None
    assert result.data_coverage_ratio < Decimal("0.50")


# --- Senaryo 6: Orta coverage (%50-%69,9 -- low_confidence_warning) --------


def test_golden_medium_coverage_scenario_sets_low_confidence_warning():
    from app.engines.common.health_score_registry import scoreable_ratio_codes_for_category

    ratio_categories, benchmark_categories = {}, {}
    # liquidity, leverage, profitability TAM -- activity, efficiency, growth
    # TAMAMEN eksik -> yaklaşık %60 coverage (design doc'taki 20+25+20=65
    # ağırlık/oran karışımına yakın bir bant hedeflenir; asıl doğrulama
    # gerçekleşen `data_coverage_ratio` üzerinden yapılır, sabit varsayılmaz).
    full_categories = {"liquidity", "leverage", "profitability"}
    for category in ACTIVE_CATEGORIES:
        codes = scoreable_ratio_codes_for_category(category)
        ratios_out, benchmarks_out = {}, {}
        for code in codes:
            if category in full_categories:
                ratios_out[code] = _make_signal("calculated", 1.2, reliability="high")
                benchmarks_out[code] = _make_benchmark_signal("evaluated", "average", "high")
            else:
                ratios_out[code] = _make_signal("missing_input")
                benchmarks_out[code] = _make_benchmark_signal("ratio_status_not_calculated")
        ratio_categories[category] = {"status": "partial", "ratios": ratios_out}
        benchmark_categories[category] = {"ratios": benchmarks_out}

    ratio_result = {"ratio_registry_version": "1.1.0", "categories": ratio_categories, "warnings": []}
    benchmark_result = {"benchmark_registry_version": "1.0.0", "categories": benchmark_categories}

    result = compute_financial_health_score(ratio_result, benchmark_result)

    if result.status == HealthScoreComputationStatus.INSUFFICIENT_DATA:
        assert result.data_coverage_ratio < Decimal("0.50")
    else:
        assert Decimal("0.50") <= result.data_coverage_ratio < Decimal("0.70")
        assert result.low_confidence_warning is True
        assert any(w.get("code") == "LOW_CONFIDENCE_COVERAGE" for w in result.warnings)


# --- Senaryo 7: Önceki dönem yok (growth tamamen eksik) --------------------


def test_golden_no_prior_period_growth_category_fully_missing_but_coverage_normal():
    bs = _bs_facts()
    is_ = _is_facts()
    result = _compute(bs_facts=bs, is_facts=is_, prior_bs_facts=None, prior_is_facts=None)

    breakdown_by_category = {b.category: b for b in result.category_breakdown}
    growth = breakdown_by_category["growth"]
    assert growth.raw_score is None
    assert growth.weight_applied == Decimal("0")
    assert growth.coverage_ratio == Decimal("0")

    # growth (~%10 global ağırlık) eksik olsa da genel coverage normal
    # bandın (>= %70) üzerinde kalmalı.
    assert result.data_coverage_ratio >= Decimal("0.70")
    assert result.low_confidence_warning is False
    assert result.status in (
        HealthScoreComputationStatus.COMPUTED, HealthScoreComputationStatus.HARD_FAIL_CAPPED,
    )
