"""
Milestone 4.3D (Financial Health Score) / Adım 11: `app/engines/health_
score/service.py::compute_financial_health_score` (tam pipeline
orkestrasyonu) için gerçek, çalıştırılabilir birim testleri. Gerçek
`analyze_financial_ratios()` + `evaluate_benchmarks()` çıktısı üzerinde
çalıştırılır.
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.health_score_types import (
    HEALTH_SCORE_MODEL_VERSION,
    HEALTH_SCORE_SCHEMA_VERSION,
    HealthScoreComputationStatus,
)
from app.engines.common.health_score_registry import scoreable_ratio_codes_for_category
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


def _real_result_jsons(*, with_prior_period=True, bs_overrides=None, is_overrides=None):
    bs_result = {"source_mode": "direct_document", "facts": _bs_facts(**(bs_overrides or {}))}
    is_result = {"source_mode": "direct_document", "facts": _is_facts(**(is_overrides or {}))}
    prior_bs = prior_is = None
    if with_prior_period:
        prior_bs = {
            "source_mode": "direct_document",
            "facts": _bs_facts(total_assets=2500000.0, equity=1400000.0),
        }
        prior_is = {
            "source_mode": "direct_document",
            "facts": _is_facts(net_sales=4000000.0, gross_profit=1600000.0, ebitda=800000.0, net_profit=400000.0),
        }
    ratio_result = analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=prior_bs, prior_period_income_statement_result=prior_is,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )
    return ratio_result, evaluate_benchmarks(ratio_result)


# --- Mutlu yol (sağlıklı şirket, tam coverage) ------------------------------


def test_healthy_company_full_coverage_produces_computed_status():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    result = compute_financial_health_score(ratio_result, benchmark_result)

    assert result.status in (
        HealthScoreComputationStatus.COMPUTED, HealthScoreComputationStatus.HARD_FAIL_CAPPED,
    )
    assert result.final_score is not None
    assert Decimal("0") <= result.final_score <= Decimal("100")
    assert result.letter_rating is not None
    assert result.data_coverage_ratio == Decimal("1")
    assert result.confidence_score <= Decimal("0.60")
    assert len(result.category_breakdown) == len(ACTIVE_CATEGORIES)
    assert result.category_weight_profile_used == "global"
    assert result.health_score_schema_version == HEALTH_SCORE_SCHEMA_VERSION
    assert result.health_score_model_version == HEALTH_SCORE_MODEL_VERSION
    assert result.ratio_registry_version == ratio_result["ratio_registry_version"]
    assert result.benchmark_registry_version == benchmark_result["benchmark_registry_version"]
    assert result.provisional is True
    assert len(result.scoreable_ratio_codes) > 0
    assert len(result.excluded_duplicate_ratio_codes) == 6


def test_healthy_company_has_strengths_and_weaknesses():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    result = compute_financial_health_score(ratio_result, benchmark_result)
    assert len(result.strengths) > 0
    assert len(result.weaknesses) > 0


def test_override_parameters_fall_back_to_global_profile():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    result = compute_financial_health_score(
        ratio_result, benchmark_result,
        industry_code="tekstil", company_size_bucket="small", tenant_id="banka_x",
    )
    assert result.category_weight_profile_used == "global"


# --- Hard fail senaryosu: negatif özkaynak ----------------------------------


def test_negative_equity_triggers_hard_fail_capped_status():
    ratio_result, benchmark_result = _real_result_jsons(
        with_prior_period=True, bs_overrides={"equity": -400000.0},
    )
    result = compute_financial_health_score(ratio_result, benchmark_result)

    assert result.status == HealthScoreComputationStatus.HARD_FAIL_CAPPED
    assert "NEGATIVE_EQUITY" in result.hard_fails_triggered
    assert result.final_score is not None
    assert result.final_score <= Decimal("25")
    assert result.pre_hard_fail_score is not None
    assert result.pre_hard_fail_score >= result.final_score


# --- INSUFFICIENT_DATA senaryosu (sentetik, kontrollü düşük coverage) ------


def _make_minimal_signal(status, value=None, tier=None, reliability="high"):
    return {"value": value, "status": status, "reliability": reliability}


def _make_minimal_benchmark_signal(status, tier=None, reliability="not_calculable"):
    return {"status": status, "tier": tier, "reliability": reliability, "warnings": []}


def _synthetic_low_coverage_jsons():
    # Her aktif kategoride, scoreable oranların NEREDEYSE TAMAMI
    # ratio_status_not_calculated -- yalnızca current_ratio EVALUATED.
    ratio_categories = {}
    benchmark_categories = {}
    for category in ACTIVE_CATEGORIES:
        from app.engines.health_score.service import scoreable_ratio_codes_for_category
        ratios_out = {}
        benchmarks_out = {}
        codes = scoreable_ratio_codes_for_category(category)
        for code in codes:
            if category == "liquidity" and code == "current_ratio":
                ratios_out[code] = _make_minimal_signal("calculated", 1.5, reliability="high")
                benchmarks_out[code] = _make_minimal_benchmark_signal("evaluated", "good", "high")
            else:
                ratios_out[code] = _make_minimal_signal("missing_input")
                benchmarks_out[code] = _make_minimal_benchmark_signal("ratio_status_not_calculated")
        ratio_categories[category] = {"status": "partial", "ratios": ratios_out}
        benchmark_categories[category] = {"ratios": benchmarks_out}

    ratio_result = {
        "engine": "financial_ratios", "ratio_registry_version": "1.1.0",
        "categories": ratio_categories, "warnings": [],
    }
    benchmark_result = {
        "engine": "benchmarks", "benchmark_registry_version": "1.0.0",
        "categories": benchmark_categories,
    }
    return ratio_result, benchmark_result


def test_low_coverage_synthetic_scenario_produces_insufficient_data():
    ratio_result, benchmark_result = _synthetic_low_coverage_jsons()
    result = compute_financial_health_score(ratio_result, benchmark_result)

    assert result.status == HealthScoreComputationStatus.INSUFFICIENT_DATA
    assert result.final_score is None
    assert result.letter_rating is None
    assert result.pre_hard_fail_score is None
    assert result.data_coverage_ratio < Decimal("0.50")
    assert len(result.category_breakdown) == len(ACTIVE_CATEGORIES)  # teşhis bilgisi HÂLÂ döner
    any_insufficient_warning = any(w.get("code") == "INSUFFICIENT_DATA" for w in result.warnings)
    assert any_insufficient_warning


# --- Determinizm -------------------------------------------------------------


def test_pipeline_is_fully_deterministic_across_repeated_calls():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    results = [compute_financial_health_score(ratio_result, benchmark_result) for _ in range(5)]
    for result in results[1:]:
        assert result == results[0]


def test_pipeline_does_not_mutate_input_result_jsons():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    import copy

    ratio_snapshot = copy.deepcopy(ratio_result)
    benchmark_snapshot = copy.deepcopy(benchmark_result)
    compute_financial_health_score(ratio_result, benchmark_result)
    assert ratio_result == ratio_snapshot
    assert benchmark_result == benchmark_snapshot
