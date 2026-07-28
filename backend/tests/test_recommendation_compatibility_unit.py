"""
Milestone 4.3F (Recommendation Engine) -- Bölüm 28 madde 8a (ZORUNLU):
`SCHEMA_INCOMPATIBLE`/`VERSION_MISMATCH`/`MODEL_VERSION_MISMATCH`
davranışları (Bölüm 16.2).
"""

import copy
import dataclasses
from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.recommendation_types import RecommendationComputationStatus
from app.engines.credit_score.service import compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations


def _build_inputs():
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
    return ratio_result, benchmark_result, health_score_result, credit_score_result


def test_unsupported_health_score_schema_version_yields_schema_incompatible_and_zero_recommendations():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs()
    incompatible_health_score_result = dataclasses.replace(
        health_score_result, health_score_schema_version="9.9.9"
    )
    result = generate_recommendations(
        ratio_result, benchmark_result, incompatible_health_score_result, credit_score_result
    )
    assert result.status == RecommendationComputationStatus.SCHEMA_INCOMPATIBLE
    assert result.recommendations == ()
    assert result.financial_recommendation_codes == ()
    assert result.banking_readiness_recommendation_codes == ()
    assert result.data_quality_recommendation_codes == ()
    assert any(w["code"] == "SCHEMA_VERSION_UNSUPPORTED" for w in result.warnings)


def test_unsupported_credit_score_schema_version_yields_schema_incompatible():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs()
    incompatible_credit_score_result = dataclasses.replace(
        credit_score_result, credit_score_schema_version="9.9.9"
    )
    result = generate_recommendations(
        ratio_result, benchmark_result, health_score_result, incompatible_credit_score_result
    )
    assert result.status == RecommendationComputationStatus.SCHEMA_INCOMPATIBLE
    assert result.recommendations == ()


def test_unsupported_ratio_registry_version_yields_version_mismatch_data_quality_only():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs()
    mismatched_ratio_result = copy.deepcopy(ratio_result)
    mismatched_ratio_result["ratio_registry_version"] = "9.9.9"

    result = generate_recommendations(
        mismatched_ratio_result, benchmark_result, health_score_result, credit_score_result
    )
    assert result.status == RecommendationComputationStatus.VERSION_MISMATCH
    assert result.financial_recommendation_codes == ()
    assert result.banking_readiness_recommendation_codes == ()
    for item in result.recommendations:
        assert item.category.value == "data_quality"
    assert any(w["code"] == "RATIO_OR_BENCHMARK_VERSION_UNSUPPORTED" for w in result.warnings)


def test_unsupported_benchmark_registry_version_yields_version_mismatch():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs()
    mismatched_benchmark_result = copy.deepcopy(benchmark_result)
    mismatched_benchmark_result["benchmark_registry_version"] = "9.9.9"

    result = generate_recommendations(
        ratio_result, mismatched_benchmark_result, health_score_result, credit_score_result
    )
    assert result.status == RecommendationComputationStatus.VERSION_MISMATCH


def test_matching_schema_and_registry_versions_compute_normally():
    ratio_result, benchmark_result, health_score_result, credit_score_result = _build_inputs()
    result = generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)
    assert result.status in (
        RecommendationComputationStatus.COMPUTED,
        RecommendationComputationStatus.NO_RECOMMENDATIONS_TRIGGERED,
    )
    assert not any(w["code"] == "SCHEMA_VERSION_UNSUPPORTED" for w in result.warnings)
    assert not any(w["code"] == "RATIO_OR_BENCHMARK_VERSION_UNSUPPORTED" for w in result.warnings)
