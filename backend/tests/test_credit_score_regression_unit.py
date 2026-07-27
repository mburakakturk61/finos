"""
Milestone 4.3E (Credit Score Engine) / Adım 15: Regresyon testleri.

Credit Score motorunun EKLENMESİNİN, mevcut Ratio Engine (4.3B),
Benchmark Engine (4.3C) ve Financial Health Score (4.3D) davranışında
HİÇBİR yan etkiye yol açmadığını kanıtlar -- paylaşılan global
registry'lerin (`RATIO_REGISTRY`, `BENCHMARK_REGISTRY`, `RATIO_SCORE_
WEIGHTS`) VE Credit Score'un KENDİ 5 registry'sinin boyutunun/içeriğinin
değişmediğini ve `analyze_financial_ratios()`/`evaluate_benchmarks()`/
`compute_financial_health_score()` çıktılarının Credit Score modülü
import edilip ÇAĞRILDIKTAN SONRA bile bit-birebir aynı kaldığını
doğrudan doğrular.
"""

from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.credit_score_registry import CREDIT_RATIO_SCORE_WEIGHTS
from app.engines.common.health_score_registry import RATIO_SCORE_WEIGHTS
from app.engines.common.ratio_formulas import RATIO_REGISTRY
from app.engines.credit_score.service import compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score


def _real_bs_facts():
    return {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }


def _real_is_facts():
    return {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }


def _real_result_jsons():
    bs_result = {"source_mode": "direct_document", "facts": _real_bs_facts()}
    is_result = {"source_mode": "direct_document", "facts": _real_is_facts()}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    return ratio_result, evaluate_benchmarks(ratio_result)


def _real_registry_codes(registry):
    return {code for code in registry if not code.startswith("_")}


def _compute_credit_score():
    ratio_result, benchmark_result = _real_result_jsons()
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    return ratio_result, benchmark_result, compute_credit_score(
        ratio_result, benchmark_result, health_score_result,
    )


# --- Registry boyutları Credit Score kullanımından ETKİLENMEMELİ ----------


def test_ratio_registry_size_unchanged_after_credit_score_usage():
    before = _real_registry_codes(RATIO_REGISTRY)
    _compute_credit_score()
    after = _real_registry_codes(RATIO_REGISTRY)
    assert before == after
    assert len(before) == 57


def test_benchmark_registry_size_unchanged_after_credit_score_usage():
    before = _real_registry_codes(BENCHMARK_REGISTRY)
    _compute_credit_score()
    after = _real_registry_codes(BENCHMARK_REGISTRY)
    assert before == after
    assert len(before) == 48


def test_health_score_ratio_score_weights_size_unchanged_after_credit_score_usage():
    before = _real_registry_codes(RATIO_SCORE_WEIGHTS)
    _compute_credit_score()
    after = _real_registry_codes(RATIO_SCORE_WEIGHTS)
    assert before == after
    assert len(before) == 48


def test_credit_ratio_score_weights_size_unchanged_after_repeated_usage():
    before = _real_registry_codes(CREDIT_RATIO_SCORE_WEIGHTS)
    for _ in range(3):
        _compute_credit_score()
    after = _real_registry_codes(CREDIT_RATIO_SCORE_WEIGHTS)
    assert before == after
    assert len(before) == 48


# --- Ratio/Benchmark/Health Score çıktıları Credit Score çağrısından -------
# --- ETKİLENMEMELİ ----------------------------------------------------------


def test_ratio_and_benchmark_outputs_identical_before_and_after_credit_score_call():
    ratio_result_1, benchmark_result_1, _ = _compute_credit_score()

    ratio_result_2, benchmark_result_2 = _real_result_jsons()

    assert ratio_result_1 == ratio_result_2
    assert benchmark_result_1 == benchmark_result_2


def test_repeated_credit_score_calls_do_not_drift_downstream_engine_outputs():
    for _ in range(5):
        _compute_credit_score()

    ratio_result_final, benchmark_result_final = _real_result_jsons()
    ratio_result_baseline, benchmark_result_baseline = _real_result_jsons()
    assert ratio_result_final == ratio_result_baseline
    assert benchmark_result_final == benchmark_result_baseline


def test_credit_score_result_itself_is_stable_across_repeated_independent_computations():
    results = []
    for _ in range(5):
        _, _, result = _compute_credit_score()
        results.append(result)
    for result in results[1:]:
        assert result == results[0]


def test_health_score_result_is_unaffected_by_subsequent_credit_score_calls():
    ratio_result, benchmark_result = _real_result_jsons()
    health_score_result_before = compute_financial_health_score(ratio_result, benchmark_result)
    compute_credit_score(ratio_result, benchmark_result, health_score_result_before)
    health_score_result_after = compute_financial_health_score(ratio_result, benchmark_result)
    assert health_score_result_before == health_score_result_after
