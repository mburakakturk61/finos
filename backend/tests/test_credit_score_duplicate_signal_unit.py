"""
Milestone 4.3E (Credit Score Engine) / Adım 3: Duplicate/correlated
signal validasyonu -- `equity_ratio`/`debt_to_equity` cebirsel
ilişkisinin (Bölüm 7.2) GERÇEK `analyze_financial_ratios()` çıktısı
üzerinden sayısal olarak doğrulanması + `long_term_debt_to_equity`/
`short_term_debt_ratio`'nun `equity_ratio`'dan BAĞIMSIZ bir serbestlik
derecesi taşıdığının kanıtlanması.
"""

from datetime import date
from decimal import Decimal

from app.engines.common.credit_score_registry import CREDIT_RATIO_SCORE_WEIGHTS
from app.engines.financial_ratios.service import analyze_financial_ratios


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


def _ratio_result(bs_facts_overrides=None, is_facts_overrides=None):
    bs_result = {"source_mode": "direct_document", "facts": _bs_facts(**(bs_facts_overrides or {}))}
    is_result = {"source_mode": "direct_document", "facts": _is_facts(**(is_facts_overrides or {}))}
    return analyze_financial_ratios(
        balance_sheet_result=bs_result, income_statement_result=is_result,
        prior_period_balance_sheet_result=None, prior_period_income_statement_result=None,
        period_start_date=date(2024, 1, 1), period_end_date=date(2024, 12, 31),
    )


def _ratio_value(ratio_result, category, code):
    return ratio_result["categories"][category]["ratios"][code]["value"]


# --- Bölüm 7.2: equity_ratio / debt_to_equity CEBİRSEL İLİŞKİSİ ------------


def test_debt_to_equity_equals_algebraic_transform_of_equity_ratio_on_real_engine_output():
    ratio_result = _ratio_result()
    equity_ratio = Decimal(str(_ratio_value(ratio_result, "leverage", "equity_ratio")))
    debt_to_equity = Decimal(str(_ratio_value(ratio_result, "leverage", "debt_to_equity")))

    expected_debt_to_equity = (Decimal("1") - equity_ratio) / equity_ratio
    # Motorun kendi yuvarlama hassasiyetine (4 ondalık) tolerans tanı.
    assert abs(debt_to_equity - expected_debt_to_equity) < Decimal("0.001"), (
        f"debt_to_equity={debt_to_equity}, beklenen (1-equity_ratio)/equity_ratio="
        f"{expected_debt_to_equity}"
    )


def test_debt_to_equity_relationship_holds_across_multiple_synthetic_companies():
    # `total_liabilities` (= short_term_liabilities + long_term_liabilities)
    # `equity` + `total_assets` ile TUTARLI (bilanço denkliğini sağlayacak
    # şekilde) AYARLANMALIDIR -- aksi halde `debt_to_equity` motor
    # tarafından `total_assets - equity`'DEN DEĞİL, ayrı bir fact'ten
    # (gerçek short/long_term_liabilities toplamından) hesaplanır ve
    # senaryo tutarsızsa cebirsel özdeşlik GEÇERSİZ hale gelir (bu, motorun
    # bir hatası DEĞİL, dengesiz bir sentetik girdinin doğal sonucudur).
    scenarios = [
        {"equity": 1700000.0, "total_assets": 3000000.0,
         "short_term_liabilities": 900000.0, "long_term_liabilities": 400000.0},
        {"equity": 500000.0, "total_assets": 2000000.0,
         "short_term_liabilities": 900000.0, "long_term_liabilities": 600000.0},
        {"equity": 2800000.0, "total_assets": 3200000.0,
         "short_term_liabilities": 200000.0, "long_term_liabilities": 200000.0},
    ]
    for scenario in scenarios:
        ratio_result = _ratio_result(bs_facts_overrides=scenario)
        equity_ratio = Decimal(str(_ratio_value(ratio_result, "leverage", "equity_ratio")))
        debt_to_equity = Decimal(str(_ratio_value(ratio_result, "leverage", "debt_to_equity")))
        expected = (Decimal("1") - equity_ratio) / equity_ratio
        assert abs(debt_to_equity - expected) < Decimal("0.001"), scenario


# --- long_term_debt_to_equity / short_term_debt_ratio BAĞIMSIZLIĞI ---------


def test_long_term_debt_to_equity_varies_independently_of_equity_ratio():
    # equity/total_assets SABİT (equity_ratio AYNI kalır) -- yalnızca
    # long_term_liabilities/short_term_liabilities DAĞILIMI değişir.
    common = {"equity": 1700000.0, "total_assets": 3000000.0}

    ratio_result_a = _ratio_result(bs_facts_overrides={
        **common, "long_term_liabilities": 200000.0, "short_term_liabilities": 1100000.0,
    })
    ratio_result_b = _ratio_result(bs_facts_overrides={
        **common, "long_term_liabilities": 1000000.0, "short_term_liabilities": 300000.0,
    })

    equity_ratio_a = _ratio_value(ratio_result_a, "leverage", "equity_ratio")
    equity_ratio_b = _ratio_value(ratio_result_b, "leverage", "equity_ratio")
    assert equity_ratio_a == equity_ratio_b, "equity_ratio SABİT kalmalıydı"

    ltde_a = _ratio_value(ratio_result_a, "leverage", "long_term_debt_to_equity")
    ltde_b = _ratio_value(ratio_result_b, "leverage", "long_term_debt_to_equity")
    assert ltde_a != ltde_b, (
        "long_term_debt_to_equity, equity_ratio SABİT kalsa bile DEĞİŞMELİYDİ "
        "-- bu, equity_ratio'dan BAĞIMSIZ bir serbestlik derecesi taşıdığının kanıtıdır"
    )


def test_short_term_debt_ratio_varies_independently_of_equity_ratio():
    common = {"equity": 1700000.0, "total_assets": 3000000.0}

    ratio_result_a = _ratio_result(bs_facts_overrides={
        **common, "long_term_liabilities": 200000.0, "short_term_liabilities": 1100000.0,
    })
    ratio_result_b = _ratio_result(bs_facts_overrides={
        **common, "long_term_liabilities": 1000000.0, "short_term_liabilities": 300000.0,
    })

    equity_ratio_a = _ratio_value(ratio_result_a, "leverage", "equity_ratio")
    equity_ratio_b = _ratio_value(ratio_result_b, "leverage", "equity_ratio")
    assert equity_ratio_a == equity_ratio_b

    stdr_a = _ratio_value(ratio_result_a, "leverage", "short_term_debt_ratio")
    stdr_b = _ratio_value(ratio_result_b, "leverage", "short_term_debt_ratio")
    assert stdr_a != stdr_b, (
        "short_term_debt_ratio, equity_ratio SABİT kalsa bile DEĞİŞMELİYDİ"
    )


# --- Registry sınıflandırmasının bu kanıtla TUTARLI olduğu -----------------


def test_registry_classification_matches_mathematical_proof():
    # debt_to_equity: KESİN cebirsel dönüşüm oldugu icin explainability-only.
    assert CREDIT_RATIO_SCORE_WEIGHTS["debt_to_equity"].ratio_weight == 0
    assert CREDIT_RATIO_SCORE_WEIGHTS["debt_to_equity"].duplicate_relationship == "algebraic_complement"
    # long_term_debt_to_equity / short_term_debt_ratio: BAĞIMSIZ oldukları
    # icin scored (supporting).
    assert CREDIT_RATIO_SCORE_WEIGHTS["long_term_debt_to_equity"].ratio_weight > 0
    assert CREDIT_RATIO_SCORE_WEIGHTS["short_term_debt_ratio"].ratio_weight > 0
