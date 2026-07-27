"""
Milestone 4.3E (Credit Score Engine) / Adım 16: Performans testleri.

Tasarım dokümanı hedefi (Bölüm 22): Credit Score'un EK maliyeti <0,2 ms,
tam pipeline (Ratio + Benchmark + Health Score + Credit Score) toplam
<1,5 ms/çağrı.

Testlerdeki eşikler, donanım/sandbox değişkenliğine karşı KASITLI olarak
GENİŞ bir güvenlik payıyla belirlenmiştir -- amaç gerçek regresyonları
(ör. yanlışlıkla O(n²) karmaşıklığa dönen bir döngü) yakalamak, CI'da
gürültüden dolayı sahte-kırmızı (flaky) üretmek DEĞİLDİR.
"""

import time
from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.credit_score.service import compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score

_ITERATIONS = 300


def _real_result_jsons():
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
    prior_bs_facts = dict(bs_facts, total_assets=2500000.0, equity=1400000.0)
    prior_is_facts = dict(
        is_facts, net_sales=4000000.0, gross_profit=1600000.0, ebitda=800000.0, net_profit=400000.0
    )
    bs_result = {"source_mode": "direct_document", "facts": bs_facts}
    is_result = {"source_mode": "direct_document", "facts": is_facts}
    prior_bs = {"source_mode": "direct_document", "facts": prior_bs_facts}
    prior_is = {"source_mode": "direct_document", "facts": prior_is_facts}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    return bs_result, is_result, prior_bs, prior_is, ratio_result, benchmark_result, health_score_result


def test_credit_score_only_average_latency_within_generous_bound():
    _, _, _, _, ratio_result, benchmark_result, health_score_result = _real_result_jsons()

    for _ in range(20):
        compute_credit_score(ratio_result, benchmark_result, health_score_result)

    start = time.perf_counter()
    for _ in range(_ITERATIONS):
        compute_credit_score(ratio_result, benchmark_result, health_score_result)
    elapsed = time.perf_counter() - start
    avg_ms = elapsed / _ITERATIONS * 1000

    # Doküman hedefi ~0,2 ms; sandbox değişkenliğine karşı geniş pay (10x+).
    assert avg_ms < 3.0, f"Credit Score ortalama gecikmesi çok yüksek: {avg_ms:.4f} ms"


def test_full_pipeline_average_latency_within_generous_bound():
    bs_result, is_result, prior_bs, prior_is, _, _, _ = _real_result_jsons()

    def _run_once():
        ratio_result = analyze_financial_ratios(
            balance_sheet_result=bs_result, income_statement_result=is_result,
            prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
            period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
        )
        benchmark_result = evaluate_benchmarks(ratio_result)
        health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
        return compute_credit_score(ratio_result, benchmark_result, health_score_result)

    for _ in range(20):
        _run_once()

    start = time.perf_counter()
    for _ in range(_ITERATIONS):
        _run_once()
    elapsed = time.perf_counter() - start
    avg_ms = elapsed / _ITERATIONS * 1000

    # Doküman hedefi ~1,5 ms (Ratio+Benchmark+HealthScore+CreditScore
    # toplam); geniş pay.
    assert avg_ms < 12.0, f"Tam pipeline ortalama gecikmesi çok yüksek: {avg_ms:.4f} ms"


def test_credit_score_marginal_overhead_is_small_relative_to_downstream_engines():
    bs_result, is_result, prior_bs, prior_is, _, _, _ = _real_result_jsons()

    def _upstream_only():
        ratio_result = analyze_financial_ratios(
            balance_sheet_result=bs_result, income_statement_result=is_result,
            prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
            period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
        )
        benchmark_result = evaluate_benchmarks(ratio_result)
        return compute_financial_health_score(ratio_result, benchmark_result)

    for _ in range(20):
        _upstream_only()

    start = time.perf_counter()
    for _ in range(_ITERATIONS):
        _upstream_only()
    elapsed_upstream = time.perf_counter() - start
    avg_upstream_ms = elapsed_upstream / _ITERATIONS * 1000

    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    for _ in range(20):
        compute_credit_score(ratio_result, benchmark_result, health_score_result)
    start = time.perf_counter()
    for _ in range(_ITERATIONS):
        compute_credit_score(ratio_result, benchmark_result, health_score_result)
    elapsed_cs = time.perf_counter() - start
    avg_cs_ms = elapsed_cs / _ITERATIONS * 1000

    # Credit Score'un tek başına ortalaması, upstream (Ratio+Benchmark+
    # Health Score) ortalamasının birkaç katını (geniş pay: 5x) AŞMAMALI.
    assert avg_cs_ms < avg_upstream_ms * 5, (
        f"Credit Score marjinal maliyeti orantısız: cs={avg_cs_ms:.4f} ms, "
        f"upstream={avg_upstream_ms:.4f} ms"
    )
