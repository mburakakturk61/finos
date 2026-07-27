"""
Milestone 4.3E (Credit Score Engine) / Adım 8: `app/engines/credit_
score/service.py::compute_confidence_score` / `weighted_reliabilities_
for_category` (Bölüm 11, Onaylanmış Karar #8) için gerçek,
çalıştırılabilir birim testleri.

Credit Score'un confidence tavanı 0.50'dir -- Health Score'un
0.60'ından DAHA SIKI (Credit Score'un yapısal veri boşluklarını --
Bölüm 19 -- de taşıdığı için).
"""

from decimal import Decimal

from app.engines.common.credit_score_types import CreditCategoryBreakdown, CreditRatioContribution
from app.engines.credit_score.service import (
    compute_confidence_score,
    weighted_reliabilities_for_category,
)


def test_empty_input_returns_zero_confidence():
    assert compute_confidence_score([]) == Decimal("0")


def test_all_high_reliability_is_capped_at_provisional_ceiling():
    result = compute_confidence_score([("high", Decimal("1"))])
    assert result == Decimal("0.50")


def test_all_medium_reliability_is_also_capped_since_above_ceiling():
    # medium=0.66 ham degeri, tavan 0.50'nin UZERINDE -> tavana cekilir.
    result = compute_confidence_score([("medium", Decimal("1"))])
    assert result == Decimal("0.50")


def test_all_medium_low_reliability_exactly_at_ceiling():
    # medium_low=0.5 ham degeri, tavan 0.50'ye TAM esit -> min() degismez.
    result = compute_confidence_score([("medium_low", Decimal("1"))])
    assert result == Decimal("0.5")


def test_all_low_reliability_stays_below_ceiling_uncapped():
    result = compute_confidence_score([("low", Decimal("1"))])
    assert result == Decimal("0.33")


def test_mixed_weighted_reliabilities_computed_correctly():
    # 0.5 agirlik high(1.0) + 0.5 agirlik medium_low(0.5) -> ham=0.75 -> tavan 0.50
    result = compute_confidence_score(
        [("high", Decimal("0.5")), ("medium_low", Decimal("0.5"))]
    )
    assert result == Decimal("0.50")


def test_uncapped_mixed_result_below_ceiling():
    # 0.5 agirlik low(0.33) + 0.5 agirlik not_calculable(0.0) -> ham=0.165
    result = compute_confidence_score(
        [("low", Decimal("0.5")), ("not_calculable", Decimal("0.5"))]
    )
    assert result == Decimal("0.165")


def test_zero_total_weight_returns_zero_not_exception():
    result = compute_confidence_score([("high", Decimal("0"))])
    assert result == Decimal("0")


def test_unknown_reliability_string_treated_as_zero():
    result = compute_confidence_score([("_unknown_reliability_", Decimal("1"))])
    assert result == Decimal("0")


# --- weighted_reliabilities_for_category ------------------------------------


def _contribution(ratio_code, reliability, weight_applied, *, role="supporting", score=Decimal("70"), excluded=False):
    return CreditRatioContribution(
        ratio_code=ratio_code, benchmark_status="evaluated", tier="good",
        ratio_score=(None if excluded else score),
        ratio_weight_applied=weight_applied, role=role, tier_fallback_used=False,
        reliability=reliability, is_duplicate_excluded=excluded,
    )


def test_weighted_reliabilities_skips_excluded_and_non_evaluated():
    breakdown = CreditCategoryBreakdown(
        category="liquidity", raw_score=Decimal("70"), score_after_override=Decimal("70"),
        weight_applied=Decimal("0.20"), coverage_ratio=Decimal("0.8"),
        redistributed_weights={}, critical_overrides_applied=(),
        ratio_contributions=(
            _contribution("current_ratio", "high", Decimal("0.5"), role="critical"),
            _contribution("quick_ratio", "medium", Decimal("0.5")),
            _contribution("working_capital_ratio", "high", Decimal("0"), role="explainability_only", excluded=True),
            CreditRatioContribution(
                ratio_code="cash_ratio", benchmark_status="ratio_status_not_calculated",
                tier=None, ratio_score=None, ratio_weight_applied=Decimal("0"),
                role="supporting", tier_fallback_used=False, reliability="not_calculable",
                is_duplicate_excluded=False,
            ),
        ),
    )
    result = weighted_reliabilities_for_category(breakdown, Decimal("0.20"))
    assert len(result) == 2
    assert ("high", Decimal("0.5") * Decimal("0.20")) in result
    assert ("medium", Decimal("0.5") * Decimal("0.20")) in result


def test_weighted_reliabilities_applies_category_weight_multiplier():
    breakdown = CreditCategoryBreakdown(
        category="leverage", raw_score=Decimal("80"), score_after_override=Decimal("80"),
        weight_applied=Decimal("0.25"), coverage_ratio=Decimal("1"),
        redistributed_weights={}, critical_overrides_applied=(),
        ratio_contributions=(_contribution("equity_ratio", "high", Decimal("1"), role="critical"),),
    )
    result = weighted_reliabilities_for_category(breakdown, Decimal("0.25"))
    assert result == [("high", Decimal("0.25"))]
