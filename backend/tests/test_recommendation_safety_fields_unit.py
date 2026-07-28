"""
Milestone 4.3F (Recommendation Engine) -- kullanıcının implementasyon-
onay mesajı madde 11: decision-support safety fields + banned-language
taraması (`title_tr`/`explanation_tr`/`action_steps_tr` üzerinde).
"""

from datetime import date

import app.engines.common.benchmark_registry  # noqa: F401
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.common.recommendation_registry import RECOMMENDATION_RULES
from app.engines.credit_score.service import compute_credit_score
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.recommendation.service import generate_recommendations

# Kesin, TR banned-language kalıpları (kullanıcının implementasyon-onay
# mesajı madde 11'in listesi) -- büyük/küçük harf duyarsız aranır.
_BANNED_PATTERNS = (
    "garanti ederiz",
    "kesinlikle onaylanacak",
    "kredi puanınız kesinlikle",
    "mutlaka uygulanmalıdır",
    "kesin olarak uygulanmalıdır",
    "% azaltın",
    "% artırın",
    "puan artar",
    "puan yükselir",
    "skor şu kadar artar",
    "tl kredi",
    "kredi limitine hak kazanırsınız",
)


def _all_rule_texts():
    for rule in RECOMMENDATION_RULES:
        yield rule.title_tr
        yield rule.explanation_tr
        for step in rule.action_steps_tr:
            yield step
        for assumption in rule.assumptions_tr:
            yield assumption


def test_no_banned_language_in_any_registry_text():
    for text in _all_rule_texts():
        lowered = text.lower()
        for banned in _BANNED_PATTERNS:
            assert banned not in lowered, f"Yasaklı ifade bulundu: '{banned}' -- metin: {text!r}"


def test_banking_readiness_action_steps_never_promise_specific_credit_amounts():
    import re

    for rule in RECOMMENDATION_RULES:
        if rule.category.value != "banking_readiness":
            continue
        for step in rule.action_steps_tr:
            assert not re.search(r"\d[\d.,]*\s*(tl|try|usd|eur)\b", step, re.IGNORECASE)


def test_recommendation_result_carries_all_4_decision_support_safety_fields():
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
    result = generate_recommendations(ratio_result, benchmark_result, health_score_result, credit_score_result)

    assert result.decision_support_only is True
    assert result.not_financial_advice is True
    assert result.not_credit_approval is True
    assert result.not_investment_advice is True


def test_banking_readiness_rules_all_carry_banking_disclaimer_scope():
    for rule in RECOMMENDATION_RULES:
        if rule.category.value == "banking_readiness":
            assert rule.disclaimer_scope == "banking"
            assert "kredi limiti" in rule.disclaimer_tr
