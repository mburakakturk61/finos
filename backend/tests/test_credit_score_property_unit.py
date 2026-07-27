"""
Milestone 4.3E (Credit Score Engine) / Adım 14: Property testleri.

Sabit (deterministik) tohum ile ÜRETİLEN çok sayıda rastgele girdi
kombinasyonu üzerinden, `compute_credit_score()`'un HER ZAMAN doğru
olması gereken değişmezlerini (invariant) doğrular:

  - Determinizm: aynı girdi -> bit-birebir aynı çıktı (her koşuda).
  - Clamp: final_score / kategori raw_score / score_after_override her
    zaman [0,100] aralığında (None hariç).
  - Confidence tavanı: confidence_score her zaman [0, 0.50] aralığında
    (Onaylanmış Karar #8 -- Credit Score'un KENDİ, Health Score'dan
    DAHA SIKI tavanı).
  - Ağırlık toplamı: COMPUTED/HARD_FAIL_CAPPED durumunda, tüm kategori
    `weight_applied` değerlerinin toplamı tam olarak 1.
  - Hard fail ceiling: bir hard-fail tetiklendiğinde final_score, o kuralın
    (registry'den okunan) ceiling'ini ASLA aşmaz.
  - Monotonicity garanti EDİLMEZ: daha önce eksik olan bir oranın
    hesaplanır hale gelmesi, kategori/final skoru artırmak yerine
    DÜŞÜREBİLİR.

**En kritik test (implementasyon direktifi kesin kural #1, tasarım
dokümanı Bölüm 3.2/21 madde 7, ZORUNLU):**
`test_invariant_health_score_input_independence_holds_across_adversarial_inputs`
-- AYNI `ratio_result_json`/`benchmark_result_json` çifti, EN AZ 5
FARKLI (bazıları bilinçli "adversarial") `HealthScoreResult` nesnesiyle
çağrıldığında, `compute_credit_score()`'un `final_score`'unun VE TÜM
`category_breakdown`'ının BİT-BİREBİR AYNI kaldığını kanıtlar. Bu test
YEŞİL olmadan Adım 14 TAMAMLANMIŞ SAYILMAZ.
"""

import copy
import random
from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.credit_score_registry import CREDIT_HARD_FAIL_RULES
from app.engines.common.credit_score_types import CreditScoreComputationStatus
from app.engines.common.health_score_types import HealthScoreComputationStatus, HealthScoreResult
from app.engines.credit_score.service import compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score

_HARD_FAIL_CEILINGS = {rule.rule_code: rule.score_ceiling for rule in CREDIT_HARD_FAIL_RULES}


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
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    return ratio_result, benchmark_result, health_score_result


_ITERATIONS = 40


def test_property_determinism_across_random_inputs():
    rng = random.Random(20260727)
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result, health_score_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        first = compute_credit_score(ratio_result, benchmark_result, health_score_result)
        second = compute_credit_score(ratio_result, benchmark_result, health_score_result)
        assert first == second, f"iterasyon {i}: determinizm ihlali"


def test_property_final_and_category_scores_always_clamped_0_100():
    rng = random.Random(20260727)
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result, health_score_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

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
        ratio_result, benchmark_result, health_score_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
        assert Decimal("0") <= result.confidence_score <= Decimal("0.50"), f"iterasyon {i}"


def test_property_category_weights_sum_to_one_when_score_produced():
    rng = random.Random(20260727)
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result, health_score_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
        if result.status in (
            CreditScoreComputationStatus.COMPUTED, CreditScoreComputationStatus.HARD_FAIL_CAPPED,
        ):
            total_weight = sum((b.weight_applied for b in result.category_breakdown), Decimal("0"))
            assert total_weight == Decimal("1"), f"iterasyon {i}: toplam={total_weight}"


def test_property_hard_fail_never_exceeds_registered_ceiling():
    rng = random.Random(20260727)
    triggered_at_least_once = False
    for i in range(_ITERATIONS):
        ratio_result, benchmark_result, health_score_result = _random_case(rng, with_prior_period=(i % 2 == 0))
        result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
        if result.hard_fails_triggered:
            triggered_at_least_once = True
            applicable_ceiling = min(
                _HARD_FAIL_CEILINGS[code] for code in result.hard_fails_triggered
            )
            assert result.final_score is not None
            assert result.final_score <= applicable_ceiling, f"iterasyon {i}"
    assert triggered_at_least_once, "40 iterasyonda hiç hard-fail tetiklenmedi -- rastgele üretim gözden geçirilmeli"


# --- Monotonicity GARANTİ EDİLMEZ -- kabul testi ----------------------------


def test_property_more_data_can_decrease_score_monotonicity_not_guaranteed():
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

    ratio_result_before = copy.deepcopy(ratio_result)
    benchmark_result_before = copy.deepcopy(benchmark_result_full)
    ratio_result_before["categories"]["liquidity"]["ratios"]["quick_ratio"] = {
        "value": None, "status": "missing_input", "reliability": "not_calculable",
    }
    benchmark_result_before["categories"]["liquidity"]["ratios"]["quick_ratio"] = {
        "status": "ratio_status_not_calculated", "tier": None,
        "reliability": "not_calculable", "warnings": [],
    }

    health_score_before = compute_financial_health_score(ratio_result_before, benchmark_result_before)
    health_score_after = compute_financial_health_score(ratio_result, benchmark_result_full)

    result_before = compute_credit_score(ratio_result_before, benchmark_result_before, health_score_before)
    result_after = compute_credit_score(ratio_result, benchmark_result_full, health_score_after)

    before_liquidity = next(b for b in result_before.category_breakdown if b.category == "liquidity")
    after_liquidity = next(b for b in result_after.category_breakdown if b.category == "liquidity")
    assert before_liquidity.raw_score is not None
    assert after_liquidity.raw_score is not None
    assert after_liquidity.raw_score < before_liquidity.raw_score
    assert result_after.final_score is not None and result_before.final_score is not None
    assert result_after.final_score <= result_before.final_score


# === INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE (ZORUNLU) ==================
#
# İmplementasyon direktifinin 1. kesin kuralı + tasarım dokümanı Bölüm
# 3.2/21 madde 7: AYNI ratio_result_json/benchmark_result_json çifti,
# FARKLI (bazıları adversarial) HealthScoreResult nesneleriyle
# çağrıldığında, final_score'un VE TÜM category_breakdown'ın
# BİT-BİREBİR AYNI kalması ZORUNLUDUR.


def _adversarial_health_score_results():
    """
    En az 5 FARKLI (bazıları bilinçli adversarial/bozuk) HealthScoreResult.
    Ortak alan: hepsi geçerli bir dataclass -- ama final_score/confidence/
    coverage/status DEĞERLERİ, Credit Score'un HİÇBİR sayısal alanını
    ETKİLEMEMELİDİR.
    """

    common_kwargs = dict(
        rating_disclaimer_tr="x", provisional=True, category_breakdown=(),
        hard_fails_triggered=(), critical_overrides_applied=(),
        scoreable_ratio_codes=(), excluded_duplicate_ratio_codes=(),
        strengths=(), weaknesses=(), warnings=(),
        health_score_schema_version="1.0.0", health_score_model_version="1.0.0",
        benchmark_registry_version="1.0.0", ratio_registry_version="1.0.0",
        category_weight_profile_used="global",
    )
    return (
        # 1. Normal, yuksek skorlu, COMPUTED.
        HealthScoreResult(
            status=HealthScoreComputationStatus.COMPUTED, final_score=Decimal("92.5"),
            pre_hard_fail_score=Decimal("92.5"), letter_rating="Çok Güçlü",
            confidence_score=Decimal("0.55"), data_coverage_ratio=Decimal("1"),
            low_confidence_warning=False, **common_kwargs,
        ),
        # 2. Adversarial: en dusuk mumkun skor, HARD_FAIL_CAPPED.
        HealthScoreResult(
            status=HealthScoreComputationStatus.HARD_FAIL_CAPPED, final_score=Decimal("0"),
            pre_hard_fail_score=Decimal("10"), letter_rating="Kritik",
            confidence_score=Decimal("0"), data_coverage_ratio=Decimal("1"),
            low_confidence_warning=False, **common_kwargs,
        ),
        # 3. Adversarial: INSUFFICIENT_DATA (Health Score'un TAMAMEN farkli
        # bir coverage esigi/veri setiyle skor URETEMEDIGI durum).
        HealthScoreResult(
            status=HealthScoreComputationStatus.INSUFFICIENT_DATA, final_score=None,
            pre_hard_fail_score=None, letter_rating=None,
            confidence_score=Decimal("0"), data_coverage_ratio=Decimal("0.1"),
            low_confidence_warning=False, **common_kwargs,
        ),
        # 4. Adversarial: maksimum confidence/coverage AMA orta final_score.
        HealthScoreResult(
            status=HealthScoreComputationStatus.COMPUTED, final_score=Decimal("50.0"),
            pre_hard_fail_score=Decimal("50.0"), letter_rating="İzlenmeli",
            confidence_score=Decimal("0.60"), data_coverage_ratio=Decimal("1"),
            low_confidence_warning=False, **common_kwargs,
        ),
        # 5. Adversarial: dusuk confidence + low_confidence_warning=True,
        # ama YUKSEK final_score (Health Score/Credit Score'un TUTARSIZ
        # gorunebilecegi -- ama BAGIMSIZ oldugu icin sorun OLMAYAN durum).
        HealthScoreResult(
            status=HealthScoreComputationStatus.COMPUTED, final_score=Decimal("88.0"),
            pre_hard_fail_score=Decimal("88.0"), letter_rating="Güçlü",
            confidence_score=Decimal("0.05"), data_coverage_ratio=Decimal("0.55"),
            low_confidence_warning=True, **common_kwargs,
        ),
        # 6. Extra adversarial: TAMAMEN None/sifir bir "bozuk" gorunum.
        HealthScoreResult(
            status=HealthScoreComputationStatus.INSUFFICIENT_DATA, final_score=None,
            pre_hard_fail_score=None, letter_rating=None,
            confidence_score=Decimal("0"), data_coverage_ratio=Decimal("0"),
            low_confidence_warning=False, **common_kwargs,
        ),
    )


def test_invariant_health_score_input_independence_holds_across_adversarial_inputs():
    bs_facts = {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }
    is_facts = {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }
    bs_result = {"source_mode": "direct_document", "facts": bs_facts}
    is_result = {"source_mode": "direct_document", "facts": is_facts}
    prior_bs = {
        "source_mode": "direct_document",
        "facts": {**bs_facts, "total_assets": 2500000.0, "equity": 1400000.0},
    }
    prior_is = {
        "source_mode": "direct_document",
        "facts": {**is_facts, "net_sales": 4000000.0, "gross_profit": 1600000.0, "ebitda": 800000.0, "net_profit": 400000.0},
    }
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)

    adversarial_results = _adversarial_health_score_results()
    assert len(adversarial_results) >= 5, "en az 5 farkli HealthScoreResult gereklidir"

    credit_score_results = [
        compute_credit_score(ratio_result, benchmark_result, health_score_result)
        for health_score_result in adversarial_results
    ]

    reference = credit_score_results[0]
    for i, result in enumerate(credit_score_results[1:], start=1):
        assert result.final_score == reference.final_score, (
            f"HealthScoreResult varyantı {i}: final_score DEĞİŞTİ -- "
            "INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE İHLAL EDİLDİ"
        )
        assert result.pre_hard_fail_score == reference.pre_hard_fail_score, i
        assert result.category_breakdown == reference.category_breakdown, (
            f"HealthScoreResult varyantı {i}: category_breakdown DEĞİŞTİ"
        )
        assert result.confidence_score == reference.confidence_score, i
        assert result.data_coverage_ratio == reference.data_coverage_ratio, i
        assert result.hard_fails_triggered == reference.hard_fails_triggered, i
        assert result.critical_overrides_applied == reference.critical_overrides_applied, i
        assert result.status == reference.status, i
        assert result.risk_tier == reference.risk_tier, i
        assert result.banking_lens_signals == reference.banking_lens_signals, i

    # Ama health_score_reference'IN KENDİSİ (yalnizca REFERANS alani)
    # GİRDİYE GÖRE DEĞİŞMELİDİR -- bu, invariant'in ihlali DEĞİL, tam
    # tersine dogru calistiginin (okunuyor ama hesaplamaya KARISMIYOR)
    # kanitidir.
    reference_statuses = {r.health_score_reference.health_score_status for r in credit_score_results}
    assert len(reference_statuses) > 1, (
        "adversarial HealthScoreResult'lar birbirinden yeterince FARKLI degil"
    )
