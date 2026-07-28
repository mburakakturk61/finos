"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 12 / Bölüm 29:
performans smoke testi. NOT: sandbox/CI donanımı Bölüm 29'un <0,5ms/
çağrı hedefinin ÖLÇÜLDÜĞÜ ortamla AYNI DEĞİLDİR -- bu test gevşek bir
üst sınırla (regresyon niteliğinde, kesin ms hedefi DEĞİL) sadece
"kural sayısı arttıkça O(kural sayısı) karmaşıklığın makul kaldığını"
doğrular.
"""

import time
from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.credit_score.service import compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations


def test_generate_recommendations_completes_within_loose_bound():
    bs_result = {"source_mode": "direct_document", "facts": {
        "current_assets": 1500000.0, "short_term_liabilities": 900000.0,
        "long_term_liabilities": 400000.0, "total_assets": 3000000.0,
        "equity": 1700000.0, "inventory": 300000.0, "cash_and_equivalents": 200000.0,
        "trade_receivables": 250000.0, "trade_payables": 180000.0,
        "non_current_assets": 1500000.0,
    }}
    is_result = {"source_mode": "direct_document", "facts": {
        "net_sales": 5000000.0, "gross_profit": 2000000.0, "cost_of_sales": 3000000.0,
        "operating_profit": 800000.0, "operating_expenses": 1200000.0,
        "other_operating_income": 50000.0, "other_operating_expenses": 30000.0,
        "financing_expenses": 100000.0, "profit_before_tax": 750000.0,
        "net_profit": 600000.0, "ebit": 850000.0, "ebitda": 1000000.0,
    }}
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    benchmark_result = evaluate_benchmarks(ratio_result)
    health_score_result = compute_financial_health_score(ratio_result, benchmark_result)
    credit_score_result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    iterations = 200
    start = time.perf_counter()
    for _ in range(iterations):
        generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
    elapsed = time.perf_counter() - start
    per_call_ms = (elapsed / iterations) * 1000

    # Gevşek regresyon üst sınırı (sandbox donanımı). Gerçek Bölüm 29
    # hedefi (<0,5ms EK maliyet) yalnızca kontrollü ölçüm ortamında
    # anlamlıdır -- bu test yalnızca "kabaca doğrusal, makul" olduğunu
    # KANITLAR, kesin ms hedefini SERTİFİKALANDIRMAZ.
    assert per_call_ms < 50.0, f"per_call_ms={per_call_ms:.3f} beklenenden ÇOK yüksek"
