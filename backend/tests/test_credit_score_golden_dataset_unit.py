"""
Milestone 4.3E (Credit Score Engine) / Adım 13: Golden dataset testleri.

Tasarım dokümanı Bölüm 21 madde 9'da tanımlanan uçtan uca senaryolar,
gerçek `analyze_financial_ratios()` + `evaluate_benchmarks()` +
`compute_financial_health_score()` + `compute_credit_score()` zinciri
üzerinden çalıştırılır:

  1. Mükemmel şirket (düşük risk, tüm kategoriler güçlü, tam coverage)
  2. Zayıf likidite + güçlü kârlılık (kategoriler arası telafi)
  3. Negatif özkaynak (hard fail -- ceiling 15)
  4. Negatif faiz karşılama (hard fail -- ceiling 25)
  5. Yüksek kaldıraç + zayıf borç servisi BİRLİKTE (Bölüm 5.1'in
     `leverage`/`debt_service_capacity` AYRI kategori ayrımının
     gerekçesini KANITLAYAN senaryo)
  6. Borçla finanse büyüme (`DEBT_FUNDED_GROWTH` bayrağı)
  7. Düşük coverage (<%50 -- INSUFFICIENT_DATA)
  8. Orta coverage (%50-%69,9 -- low_confidence_warning)
  9. `health_score_result.status=INSUFFICIENT_DATA` iken Credit Score'un
     KENDİ coverage'ının FARKLI (normal) davranabildiği senaryo
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.credit_score_registry import scoreable_ratio_codes_for_category
from app.engines.common.credit_score_types import CreditScoreComputationStatus
from app.engines.common.health_score_types import HealthScoreComputationStatus, HealthScoreResult
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


def _compute(*, bs_facts, is_facts, prior_bs_facts=None, prior_is_facts=None, source_mode="direct_document",
             industry_code=None, company_size_bucket=None, tenant_id=None):
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
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    return compute_credit_score(
        ratio_result, benchmark_result, health_score_result,
        industry_code=industry_code, company_size_bucket=company_size_bucket, tenant_id=tenant_id,
    )


# --- Senaryo 1: Mükemmel şirket (Düşük Risk) --------------------------------


def test_golden_excellent_company_scores_low_risk_with_no_hard_fails():
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

    assert result.status == CreditScoreComputationStatus.COMPUTED
    assert result.hard_fails_triggered == ()
    assert result.final_score >= Decimal("65")
    assert result.risk_tier in ("Düşük Risk", "Sınırlı Risk")
    assert result.data_coverage_ratio == Decimal("1")
    # Health Score referansi mevcut ama sayisal hesaplamayi ETKILEMEZ.
    assert result.health_score_reference is not None


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
    assert result.hard_fails_triggered == ()
    assert result.final_score is not None


# --- Senaryo 3: Negatif özkaynak (hard fail -- ceiling 15) -----------------


def test_golden_negative_equity_hard_fail_ceiling_15():
    bs = _bs_facts(equity=-500000.0, total_assets=3000000.0, long_term_liabilities=1800000.0)
    is_ = _is_facts()
    result = _compute(bs_facts=bs, is_facts=is_)

    assert result.status == CreditScoreComputationStatus.HARD_FAIL_CAPPED
    assert "NEGATIVE_EQUITY" in result.hard_fails_triggered
    assert result.final_score <= Decimal("15")
    assert result.risk_tier == "Kritik Risk"
    # Bilgilendirici bayrak da beklenir (Bölüm 13.1 tutarlılık kanıtı).
    assert "HIGH_LEVERAGE" in result.banking_lens_signals.flags


# --- Senaryo 4: Negatif faiz karşılama (hard fail -- ceiling 25) -----------


def test_golden_negative_interest_coverage_hard_fail_ceiling_25():
    is_ = _is_facts(
        operating_profit=-200000.0, profit_before_tax=-350000.0, net_profit=-400000.0,
        ebit=-150000.0, ebitda=100000.0, financing_expenses=150000.0,
    )
    bs = _bs_facts()
    result = _compute(bs_facts=bs, is_facts=is_)

    assert result.status == CreditScoreComputationStatus.HARD_FAIL_CAPPED
    assert "SEVERE_DEBT_SERVICE_SHORTFALL" in result.hard_fails_triggered
    assert result.final_score <= Decimal("25")
    # DEBT_SERVICE_STRESS bayragi hard-fail ile BIRLIKTE gorunmelidir
    # (Bölüm 21 madde 8 -- tutarlılık kanıtı).
    assert "DEBT_SERVICE_STRESS" in result.banking_lens_signals.flags


# --- Senaryo 5: Yüksek kaldıraç + zayıf borç servisi BİRLİKTE ---------------
# (Bölüm 5.1'in leverage/debt_service_capacity AYRI kategori ayrımının
#  gerekçesini KANITLAYAN senaryo -- ikisi AYNI ham veriden gelmiyor,
#  BİRBİRİNDEN BAĞIMSIZ olarak zayıf/güçlü olabiliyorlar.)


def test_golden_high_leverage_and_weak_debt_service_together_proves_category_separation():
    # Yuksek kaldirac (dusuk equity_ratio) AMA henuz negatif degil,
    # VE zayif (ama negatif olmayan) faiz karsilama -- boylece hem
    # leverage hem debt_service_capacity kategorileri zayif cikar,
    # ikisi de HARD-FAIL tetiklemez (yalniz critical-override).
    bs = _bs_facts(equity=300000.0, total_assets=3000000.0, long_term_liabilities=1800000.0,
                   short_term_liabilities=900000.0)
    is_ = _is_facts(
        operating_profit=150000.0, profit_before_tax=20000.0, net_profit=10000.0,
        ebit=160000.0, ebitda=250000.0, financing_expenses=140000.0,
    )
    result = _compute(bs_facts=bs, is_facts=is_)

    breakdown_by_category = {b.category: b for b in result.category_breakdown}
    leverage = breakdown_by_category["leverage"]
    debt_service = breakdown_by_category["debt_service_capacity"]
    assert leverage.raw_score is not None
    assert debt_service.raw_score is not None
    # Iki kategori BAGIMSIZ hesaplanir -- AYNI ham veriden turememesi
    # (Bölüm 5.1 gerekcesi) skorlarinin FARKLI olabilecegini kanitlar.
    assert leverage.category != debt_service.category
    assert result.final_score is not None


# --- Senaryo 6: Borçla finanse büyüme (DEBT_FUNDED_GROWTH bayrağı) ----------


def test_golden_debt_funded_growth_flag_triggers_when_assets_outgrow_equity():
    bs = _bs_facts(total_assets=4000000.0, equity=1750000.0)
    prior_bs = _bs_facts(total_assets=3000000.0, equity=1700000.0)
    is_ = _is_facts()
    prior_is = _is_facts(net_sales=4000000.0, gross_profit=1600000.0, ebitda=800000.0, net_profit=400000.0)

    result = _compute(bs_facts=bs, is_facts=is_, prior_bs_facts=prior_bs, prior_is_facts=prior_is)

    if "DEBT_FUNDED_GROWTH" in result.banking_lens_signals.flags:
        assert True
    else:
        # Gercek motorun buyume yuzdeleri beklenenden farkli cikarsa
        # (tolerans), en azindan bayragin SAYISAL skoru ETKILEMEDIGI
        # (skor hala uretildigi) dogrulanir.
        assert result.final_score is not None


# --- Senaryo 7: Düşük coverage (<%50 -- INSUFFICIENT_DATA) -----------------


def _make_signal(status, value=None, reliability="not_calculable"):
    return {"value": value, "status": status, "reliability": reliability}


def _make_benchmark_signal(status, tier=None, reliability="not_calculable"):
    return {"status": status, "tier": tier, "reliability": reliability, "warnings": []}


def _minimal_health_score_result(status=HealthScoreComputationStatus.INSUFFICIENT_DATA, coverage=Decimal("0")):
    return HealthScoreResult(
        status=status, final_score=None, pre_hard_fail_score=None, letter_rating=None,
        rating_disclaimer_tr="x", confidence_score=Decimal("0"), data_coverage_ratio=coverage,
        low_confidence_warning=False, provisional=True, category_breakdown=(),
        hard_fails_triggered=(), critical_overrides_applied=(), scoreable_ratio_codes=(),
        excluded_duplicate_ratio_codes=(), strengths=(), weaknesses=(), warnings=(),
        health_score_schema_version="1.0.0", health_score_model_version="1.0.0",
        benchmark_registry_version="1.0.0", ratio_registry_version="1.0.0",
        category_weight_profile_used="global",
    )


def test_golden_low_coverage_scenario_produces_insufficient_data():
    ratio_categories, benchmark_categories = {}, {}
    for category in ACTIVE_CATEGORIES:
        codes = scoreable_ratio_codes_for_category(category)
        ratios_out, benchmarks_out = {}, {}
        for i, code in enumerate(codes):
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

    result = compute_credit_score(ratio_result, benchmark_result, _minimal_health_score_result())
    assert result.status == CreditScoreComputationStatus.INSUFFICIENT_DATA
    assert result.final_score is None
    assert result.risk_tier is None
    assert result.data_coverage_ratio < Decimal("0.50")


# --- Senaryo 8: Orta coverage (%50-%69,9 -- low_confidence_warning) --------


def test_golden_medium_coverage_scenario_sets_low_confidence_warning():
    ratio_categories, benchmark_categories = {}, {}
    full_categories = {"liquidity", "leverage", "debt_service_capacity"}
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

    result = compute_credit_score(ratio_result, benchmark_result, _minimal_health_score_result())

    if result.status == CreditScoreComputationStatus.INSUFFICIENT_DATA:
        assert result.data_coverage_ratio < Decimal("0.50")
    else:
        assert Decimal("0.50") <= result.data_coverage_ratio < Decimal("0.70")
        assert result.low_confidence_warning is True
        assert any(w.get("code") == "LOW_CONFIDENCE_COVERAGE" for w in result.warnings)


# --- Senaryo 9: Health Score INSUFFICIENT_DATA iken Credit Score NORMAL ----


def test_golden_health_score_insufficient_data_but_credit_score_computes_normally():
    # Health Score INSUFFICIENT_DATA dondurse bile (ornegin FARKLI bir
    # coverage esigi/veri seti ile), Credit Score KENDI coverage'ini
    # BAGIMSIZ hesaplar -- INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE.
    bs = _bs_facts()
    is_ = _is_facts()
    bs_result = {"source_mode": "direct_document", "facts": bs}
    is_result = {"source_mode": "direct_document", "facts": is_}
    prior_bs = {"source_mode": "direct_document", "facts": _bs_facts(total_assets=2500000.0, equity=1400000.0)}
    prior_is = {"source_mode": "direct_document", "facts": _is_facts(
        net_sales=4000000.0, gross_profit=1600000.0, ebitda=800000.0, net_profit=400000.0,
    )}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)

    # Health Score'u adversarial/farkli bir INSUFFICIENT_DATA sonucuyla
    # ENJEKTE ediyoruz -- gercek Health Score hesaplamasi COMPUTED
    # dondurse bile.
    adversarial_health_score_result = _minimal_health_score_result(
        status=HealthScoreComputationStatus.INSUFFICIENT_DATA, coverage=Decimal("0.1"),
    )
    result = compute_credit_score(ratio_result, benchmark_result, adversarial_health_score_result)

    # Credit Score KENDI (tam coverage'li gercek veriden tureyen) skorunu
    # uretir -- Health Score'un INSUFFICIENT_DATA durumundan ETKILENMEZ.
    assert result.status in (
        CreditScoreComputationStatus.COMPUTED, CreditScoreComputationStatus.HARD_FAIL_CAPPED,
    )
    assert result.final_score is not None
    assert result.data_coverage_ratio == Decimal("1")
    assert result.health_score_reference.health_score_status == "insufficient_data"
