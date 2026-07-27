"""
Milestone 4.3D (Financial Health Score) / Adım 10: `app/engines/health_
score/service.py`'nin explainability fonksiyonları (`determine_letter_
rating` / `generate_strengths_weaknesses` / `collect_all_warnings`) için
gerçek, çalıştırılabilir birim testleri.
"""

from decimal import Decimal

from app.engines.common.health_score_types import CategoryBreakdown, RatioContribution
from app.engines.health_score.service import (
    RATING_DISCLAIMER_TR,
    collect_all_warnings,
    determine_letter_rating,
    generate_strengths_weaknesses,
)


# --- determine_letter_rating -----------------------------------------------


def test_letter_rating_none_score_returns_none():
    assert determine_letter_rating(None) is None


def test_letter_rating_boundaries_match_design_doc_bolum_16():
    assert determine_letter_rating(Decimal("100")) == "Çok Güçlü"
    assert determine_letter_rating(Decimal("85")) == "Çok Güçlü"
    assert determine_letter_rating(Decimal("84.9")) == "Güçlü"
    assert determine_letter_rating(Decimal("70")) == "Güçlü"
    assert determine_letter_rating(Decimal("69.9")) == "Sağlıklı"
    assert determine_letter_rating(Decimal("55")) == "Sağlıklı"
    assert determine_letter_rating(Decimal("54.9")) == "İzlenmeli"
    assert determine_letter_rating(Decimal("40")) == "İzlenmeli"
    assert determine_letter_rating(Decimal("39.9")) == "Zayıf"
    assert determine_letter_rating(Decimal("25")) == "Zayıf"
    assert determine_letter_rating(Decimal("24.9")) == "Kritik"
    assert determine_letter_rating(Decimal("0")) == "Kritik"


def test_rating_disclaimer_mentions_not_official():
    assert "resmî" in RATING_DISCLAIMER_TR.lower() or "resmi" in RATING_DISCLAIMER_TR.lower()
    assert "DEĞİLDİR" in RATING_DISCLAIMER_TR


# --- generate_strengths_weaknesses -----------------------------------------


def _contribution(ratio_code, tier, score, *, excluded=False):
    return RatioContribution(
        ratio_code=ratio_code, benchmark_status=("evaluated" if not excluded else "benchmark_not_registered"),
        tier=(None if excluded else tier),
        ratio_score=(None if excluded else score),
        ratio_weight_applied=Decimal("0.2"), tier_fallback_used=False,
        reliability="medium", is_duplicate_excluded=excluded,
    )


def _breakdown(category, contributions):
    return CategoryBreakdown(
        category=category, raw_score=Decimal("60"), score_after_override=Decimal("60"),
        weight_applied=Decimal("0.2"), coverage_ratio=Decimal("1"),
        redistributed_weights={}, critical_overrides_applied=(),
        ratio_contributions=tuple(contributions),
    )


def test_strengths_are_highest_tier_and_score_first():
    breakdowns = {
        "liquidity": _breakdown("liquidity", [
            _contribution("current_ratio", "excellent", Decimal("100")),
            _contribution("quick_ratio", "weak", Decimal("20")),
        ]),
    }
    strengths, weaknesses = generate_strengths_weaknesses(breakdowns, {}, count=1)
    assert strengths[0]["ratio_code"] == "current_ratio"
    assert weaknesses[0]["ratio_code"] == "quick_ratio"


def test_excluded_duplicate_ratios_never_appear_as_strengths_or_weaknesses():
    breakdowns = {
        "liquidity": _breakdown("liquidity", [
            _contribution("current_ratio", "good", Decimal("75")),
            _contribution("working_capital_ratio", "good", Decimal("75"), excluded=True),
        ]),
    }
    strengths, weaknesses = generate_strengths_weaknesses(breakdowns, {}, count=5)
    codes = {s["ratio_code"] for s in strengths} | {w["ratio_code"] for w in weaknesses}
    assert "working_capital_ratio" not in codes


def test_count_limits_number_of_strengths_and_weaknesses():
    contributions = [
        _contribution(f"_test_ratio_{i}", "good", Decimal(str(50 + i))) for i in range(10)
    ]
    breakdowns = {"liquidity": _breakdown("liquidity", contributions)}
    strengths, weaknesses = generate_strengths_weaknesses(breakdowns, {}, count=3)
    assert len(strengths) == 3
    assert len(weaknesses) == 3


def test_tie_break_is_alphabetical_by_ratio_code():
    breakdowns = {
        "liquidity": _breakdown("liquidity", [
            _contribution("zzz_ratio", "good", Decimal("75")),
            _contribution("aaa_ratio", "good", Decimal("75")),
        ]),
    }
    strengths, _ = generate_strengths_weaknesses(breakdowns, {}, count=2)
    assert [s["ratio_code"] for s in strengths] == ["aaa_ratio", "zzz_ratio"]


def test_strength_text_includes_formatted_value_and_tier():
    breakdowns = {
        "liquidity": _breakdown("liquidity", [_contribution("current_ratio", "good", Decimal("75"))]),
    }
    signals = {"current_ratio": {"ratio_value": Decimal("1.65")}}
    strengths, _ = generate_strengths_weaknesses(breakdowns, signals, count=1)
    assert "good" in strengths[0]["text_tr"]
    assert "1.65" in strengths[0]["text_tr"]


def test_empty_breakdowns_produce_empty_strengths_and_weaknesses():
    strengths, weaknesses = generate_strengths_weaknesses({}, {})
    assert strengths == ()
    assert weaknesses == ()


# --- collect_all_warnings ---------------------------------------------------


def test_collect_all_warnings_merges_ratio_and_benchmark_and_extra():
    ratio_result = {"warnings": [{"code": "RATIO_WARNING"}]}
    benchmark_result = {
        "categories": {
            "liquidity": {
                "ratios": {
                    "current_ratio": {"warnings": [{"code": "BENCHMARK_WARNING"}]},
                    "quick_ratio": {"warnings": []},
                }
            }
        }
    }
    warnings = collect_all_warnings(
        ratio_result, benchmark_result, extra_warnings=({"code": "HEALTH_SCORE_WARNING"},)
    )
    codes = {w["code"] for w in warnings}
    assert codes == {"RATIO_WARNING", "BENCHMARK_WARNING", "HEALTH_SCORE_WARNING"}


def test_collect_all_warnings_handles_missing_keys_gracefully():
    warnings = collect_all_warnings({}, {})
    assert warnings == ()
