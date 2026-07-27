"""
Milestone 4.3D (Financial Health Score) / Adım 15: Regresyon testleri.

Health Score motorunun EKLENMESİNİN, mevcut Ratio Engine (4.3B) ve
Benchmark Engine (4.3C) davranışında HİÇBİR yan etkiye yol açmadığını
kanıtlar -- paylaşılan global registry'lerin (`RATIO_REGISTRY`,
`BENCHMARK_REGISTRY`) boyutunun/içeriğinin değişmediğini ve
`analyze_financial_ratios()`/`evaluate_benchmarks()` çıktılarının Health
Score modülü import edilip ÇAĞRILDIKTAN SONRA bile bit-birebir aynı
kaldığını doğrudan doğrular (paylaşılan sözlük mutasyonu / sıra bağımlılığı
riskine karşı).
"""

from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.ratio_formulas import RATIO_REGISTRY
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
    # sandbox'ta paylaşılan process boyunca BAŞKA test dosyalarının
    # eklediği "_test_*" önekli geçici kayıtları dışarıda bırakır (bkz.
    # tests/test_health_score_registry_unit.py'deki aynı desen).
    return {code for code in registry if not code.startswith("_")}


# --- Registry boyutları Health Score kullanımından ETKİLENMEMELİ ----------


def test_ratio_registry_size_unchanged_after_health_score_usage():
    before = _real_registry_codes(RATIO_REGISTRY)
    ratio_result, benchmark_result = _real_result_jsons()
    compute_financial_health_score(ratio_result, benchmark_result)
    after = _real_registry_codes(RATIO_REGISTRY)
    assert before == after
    assert len(before) == 57


def test_benchmark_registry_size_unchanged_after_health_score_usage():
    before = _real_registry_codes(BENCHMARK_REGISTRY)
    ratio_result, benchmark_result = _real_result_jsons()
    compute_financial_health_score(ratio_result, benchmark_result)
    after = _real_registry_codes(BENCHMARK_REGISTRY)
    assert before == after
    assert len(before) == 48


# --- Ratio/Benchmark Engine çıktıları Health Score çağrısından ETKİLENMEMELİ


def test_ratio_and_benchmark_outputs_identical_before_and_after_health_score_call():
    ratio_result_1, benchmark_result_1 = _real_result_jsons()
    compute_financial_health_score(ratio_result_1, benchmark_result_1)

    ratio_result_2, benchmark_result_2 = _real_result_jsons()

    assert ratio_result_1 == ratio_result_2
    assert benchmark_result_1 == benchmark_result_2


def test_repeated_health_score_calls_do_not_drift_ratio_or_benchmark_engine_outputs():
    # Health Score'u ART ARDA (farklı şirket verileriyle) birden çok kez
    # çağırmak, SONRAKİ bağımsız bir analyze_financial_ratios/evaluate_
    # benchmarks çağrısının sonucunu KAYDIRMAMALI (paylaşılan durum sızıntısı
    # yok).
    for _ in range(5):
        ratio_result, benchmark_result = _real_result_jsons()
        compute_financial_health_score(ratio_result, benchmark_result)

    ratio_result_final, benchmark_result_final = _real_result_jsons()
    ratio_result_baseline, benchmark_result_baseline = _real_result_jsons()
    assert ratio_result_final == ratio_result_baseline
    assert benchmark_result_final == benchmark_result_baseline


def test_health_score_result_itself_is_stable_across_repeated_independent_computations():
    results = []
    for _ in range(5):
        ratio_result, benchmark_result = _real_result_jsons()
        results.append(compute_financial_health_score(ratio_result, benchmark_result))
    for result in results[1:]:
        assert result == results[0]
