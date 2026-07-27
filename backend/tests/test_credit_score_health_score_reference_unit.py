"""
Milestone 4.3E (Credit Score Engine) / Adım 9: `app/engines/credit_
score/service.py::build_health_score_reference` (Bölüm 3.2/14) için
gerçek, çalıştırılabilir birim testleri.

**INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE** -- bu adımda yalnızca
`HealthScoreResult -> HealthScoreReference` dönüşümünün DOĞRU
alan-eşlemesi test edilir. Değişmezliğin asıl KANITI (farklı/adversarial
`HealthScoreResult` girdileriyle Credit Score'un SAYISAL alanlarının
BİT-BİRE-BİT AYNI kaldığı) Adım 14'ün property testinde yapılır.
"""

from datetime import date
from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.health_score_types import HealthScoreComputationStatus, HealthScoreResult
from app.engines.credit_score.service import build_health_score_reference
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


def _real_health_score_result():
    bs_result = {"source_mode": "direct_document", "facts": _bs_facts()}
    is_result = {"source_mode": "direct_document", "facts": _is_facts()}
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
    benchmark_result = evaluate_benchmarks(ratio_result)
    return compute_financial_health_score(ratio_result, benchmark_result)


def test_reference_maps_final_score_from_real_health_score_result():
    health_score_result = _real_health_score_result()
    reference = build_health_score_reference(health_score_result)
    assert reference.health_score_final_score == health_score_result.final_score


def test_reference_maps_letter_rating():
    health_score_result = _real_health_score_result()
    reference = build_health_score_reference(health_score_result)
    assert reference.health_score_letter_rating == health_score_result.letter_rating


def test_reference_maps_confidence_and_coverage():
    health_score_result = _real_health_score_result()
    reference = build_health_score_reference(health_score_result)
    assert reference.health_score_confidence == health_score_result.confidence_score
    assert reference.health_score_coverage == health_score_result.data_coverage_ratio


def test_reference_maps_status_as_string_value():
    health_score_result = _real_health_score_result()
    reference = build_health_score_reference(health_score_result)
    assert reference.health_score_status == health_score_result.status.value


def test_reference_carries_the_fixed_disclaimer_note():
    health_score_result = _real_health_score_result()
    reference = build_health_score_reference(health_score_result)
    assert "Credit Score" in reference.note_tr
    assert "hesaplamasına HİÇBİR GİRDİ SAĞLAMAZ" in reference.note_tr


def _minimal_insufficient_data_result():
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


def test_reference_handles_none_final_score_and_letter_rating_insufficient_data():
    health_score_result = _minimal_insufficient_data_result()
    reference = build_health_score_reference(health_score_result)
    assert reference.health_score_final_score is None
    assert reference.health_score_letter_rating is None
    assert reference.health_score_status == "insufficient_data"
    assert reference.health_score_coverage == Decimal("0.3")


def test_reference_is_a_read_only_snapshot_not_the_original_object():
    health_score_result = _real_health_score_result()
    reference = build_health_score_reference(health_score_result)
    assert reference is not health_score_result
    # HealthScoreReference'in KENDİ, AYRI bir dataclass olduğu -- Credit
    # Score'un sonucuna (CreditScoreResult) health_score_result'in
    # KENDİSİ değil, yalnızca bu ÖZET yerleştirilir.
    assert not hasattr(reference, "category_breakdown")
