"""
Milestone 4.3E (Credit Score Engine) / Adım 11: `app/engines/credit_
score/service.py::compute_credit_score` (tam pipeline orkestrasyonu)
için gerçek, çalıştırılabilir birim testleri. Gerçek
`analyze_financial_ratios()` + `evaluate_benchmarks()` +
`compute_financial_health_score()` çıktısı üzerinde çalıştırılır.
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.credit_score_registry import scoreable_ratio_codes_for_category
from app.engines.common.credit_score_types import (
    CREDIT_SCORE_MODEL_VERSION,
    CREDIT_SCORE_SCHEMA_VERSION,
    CreditScoreComputationStatus,
)
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


def _health_score_result(ratio_result, benchmark_result):
    return compute_financial_health_score(ratio_result, benchmark_result)


# --- Mutlu yol (sağlıklı şirket, tam coverage) ------------------------------


def test_healthy_company_full_coverage_produces_computed_status():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    assert result.status in (
        CreditScoreComputationStatus.COMPUTED, CreditScoreComputationStatus.HARD_FAIL_CAPPED,
    )
    assert result.final_score is not None
    assert Decimal("0") <= result.final_score <= Decimal("100")
    assert result.risk_tier is not None
    assert result.data_coverage_ratio == Decimal("1")
    assert result.confidence_score <= Decimal("0.50")
    assert len(result.category_breakdown) == len(ACTIVE_CATEGORIES)
    assert result.category_weight_profile_used == "global"
    assert result.credit_score_schema_version == CREDIT_SCORE_SCHEMA_VERSION
    assert result.credit_score_model_version == CREDIT_SCORE_MODEL_VERSION
    assert result.ratio_registry_version == ratio_result["ratio_registry_version"]
    assert result.benchmark_registry_version == benchmark_result["benchmark_registry_version"]
    assert result.provisional is True
    assert len(result.scoreable_ratio_codes) == 41
    assert len(result.excluded_duplicate_ratio_codes) == 7


def test_healthy_company_has_strengths_and_weaknesses():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    assert len(result.strengths) > 0
    assert len(result.weaknesses) > 0


def test_override_parameters_fall_back_to_global_profile():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(
        ratio_result, benchmark_result, health_score_result,
        industry_code="tekstil", company_size_bucket="small", tenant_id="banka_x",
    )
    assert result.category_weight_profile_used == "global"


def test_health_score_reference_is_populated_from_real_health_score_result():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    assert result.health_score_reference.health_score_final_score == health_score_result.final_score
    assert result.health_score_reference.health_score_status == health_score_result.status.value


def test_banking_lens_signals_and_data_gap_disclosures_are_always_present():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    assert result.banking_lens_signals is not None
    assert result.banking_lens_signals.not_a_credit_limit_recommendation is True
    assert len(result.data_gap_disclosures) == 4
    assert all(d.excluded_from_score for d in result.data_gap_disclosures)


def test_risk_tier_disclaimer_present_and_generic_no_brand_name():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)
    assert "resmî bir kredi derecelendirmesi" in result.risk_tier_disclaimer_tr
    assert "FINOS" not in result.risk_tier_disclaimer_tr


# --- Hard fail senaryosu: negatif özkaynak (Credit'in KENDİ ceiling'i: 15) --


def test_negative_equity_triggers_hard_fail_capped_status_with_credit_own_ceiling():
    ratio_result, benchmark_result = _real_result_jsons(
        with_prior_period=True, bs_overrides={"equity": -400000.0},
    )
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    assert result.status == CreditScoreComputationStatus.HARD_FAIL_CAPPED
    assert "NEGATIVE_EQUITY" in result.hard_fails_triggered
    assert result.final_score is not None
    assert result.final_score <= Decimal("15")
    assert result.pre_hard_fail_score is not None
    assert result.pre_hard_fail_score >= result.final_score


# --- INSUFFICIENT_DATA senaryosu (sentetik, kontrollü düşük coverage) ------


def _make_minimal_signal(status, value=None, reliability="high"):
    return {"value": value, "status": status, "reliability": reliability}


def _make_minimal_benchmark_signal(status, tier=None, reliability="not_calculable"):
    return {"status": status, "tier": tier, "reliability": reliability, "warnings": []}


def _synthetic_low_coverage_jsons():
    # Her aktif kategoride, scoreable oranların NEREDEYSE TAMAMI
    # ratio_status_not_calculated -- yalnızca current_ratio EVALUATED.
    ratio_categories = {}
    benchmark_categories = {}
    for category in ACTIVE_CATEGORIES:
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


def _minimal_health_score_result():
    from app.engines.common.health_score_types import HealthScoreComputationStatus, HealthScoreResult
    return HealthScoreResult(
        status=HealthScoreComputationStatus.INSUFFICIENT_DATA,
        final_score=None, pre_hard_fail_score=None, letter_rating=None,
        rating_disclaimer_tr="x", confidence_score=Decimal("0"),
        data_coverage_ratio=Decimal("0.3"), low_confidence_warning=False,
        provisional=True, category_breakdown=(), hard_fails_triggered=(),
        critical_overrides_applied=(), scoreable_ratio_codes=(),
        excluded_duplicate_ratio_codes=(), strengths=(), weaknesses=(),
        warnings=(), health_score_schema_version="1.0.0",
        health_score_model_version="1.0.0", benchmark_registry_version="1.0.0",
        ratio_registry_version="1.0.0", category_weight_profile_used="global",
    )


def test_low_coverage_synthetic_scenario_produces_insufficient_data():
    ratio_result, benchmark_result = _synthetic_low_coverage_jsons()
    health_score_result = _minimal_health_score_result()
    result = compute_credit_score(ratio_result, benchmark_result, health_score_result)

    assert result.status == CreditScoreComputationStatus.INSUFFICIENT_DATA
    assert result.final_score is None
    assert result.risk_tier is None
    assert result.pre_hard_fail_score is None
    assert result.data_coverage_ratio < Decimal("0.50")
    assert len(result.category_breakdown) == len(ACTIVE_CATEGORIES)  # teşhis bilgisi HÂLÂ döner
    any_insufficient_warning = any(w.get("code") == "INSUFFICIENT_DATA" for w in result.warnings)
    assert any_insufficient_warning


# --- Determinizm -------------------------------------------------------------


def test_pipeline_is_fully_deterministic_across_repeated_calls():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    results = [
        compute_credit_score(ratio_result, benchmark_result, health_score_result) for _ in range(5)
    ]
    for result in results[1:]:
        assert result == results[0]


def test_pipeline_does_not_mutate_input_result_jsons():
    ratio_result, benchmark_result = _real_result_jsons(with_prior_period=True)
    health_score_result = _health_score_result(ratio_result, benchmark_result)
    import copy

    ratio_snapshot = copy.deepcopy(ratio_result)
    benchmark_snapshot = copy.deepcopy(benchmark_result)
    compute_credit_score(ratio_result, benchmark_result, health_score_result)
    assert ratio_result == ratio_snapshot
    assert benchmark_result == benchmark_snapshot
