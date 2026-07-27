"""
Milestone 4.3D (Financial Health Score) / Adım 4: `app/engines/health_
score/service.py`'nin tier interpolation fonksiyonları (`_continuous_
points_higher_is_better` / `_continuous_points_lower_is_better` /
`_continuous_points_range_is_better` / `compute_ratio_score`) için
gerçek, çalıştırılabilir birim testleri. Gerçek `BENCHMARK_REGISTRY`
girdilerinin (equity_ratio/debt_ratio/current_ratio) GERÇEK sınır
değerleriyle test edilir.
"""

from decimal import Decimal

import app.engines.common.benchmark_registry  # noqa: F401 -- 48 kaydı tetikler
from app.engines.common.benchmark_types import (
    BENCHMARK_REGISTRY,
    BenchmarkIdealDirection,
    BenchmarkMetadata,
    BenchmarkThresholds,
    register_benchmark,
)
from app.engines.common.ratio_formulas import (
    RATIO_REGISTRY,
    RatioFormulaMetadata,
    register_ratio_formula,
)
from app.engines.health_score.service import (
    _continuous_points_higher_is_better,
    _continuous_points_lower_is_better,
    _continuous_points_range_is_better,
    compute_ratio_score,
)


# --- HIGHER_IS_BETTER (gerçek equity_ratio sınırları: critical=0.2, ------
# weak=0.35, average=0.5, good=0.6) ----------------------------------------


def test_higher_is_better_below_critical_locks_at_zero():
    assert _continuous_points_higher_is_better(
        Decimal("0.1"), Decimal("0.2"), Decimal("0.35"), Decimal("0.5"), Decimal("0.6")
    ) == Decimal("0")


def test_higher_is_better_at_or_above_good_locks_at_100():
    assert _continuous_points_higher_is_better(
        Decimal("0.6"), Decimal("0.2"), Decimal("0.35"), Decimal("0.5"), Decimal("0.6")
    ) == Decimal("100")
    assert _continuous_points_higher_is_better(
        Decimal("0.9"), Decimal("0.2"), Decimal("0.35"), Decimal("0.5"), Decimal("0.6")
    ) == Decimal("100")


def test_higher_is_better_interpolates_midpoints():
    # critical=0.2 -> weak=0.35 orta noktası (0.275) -> 12.5 puan
    assert _continuous_points_higher_is_better(
        Decimal("0.275"), Decimal("0.2"), Decimal("0.35"), Decimal("0.5"), Decimal("0.6")
    ) == Decimal("12.5")
    # weak=0.35 -> average=0.5 orta noktası (0.425) -> 37.5 puan
    assert _continuous_points_higher_is_better(
        Decimal("0.425"), Decimal("0.2"), Decimal("0.35"), Decimal("0.5"), Decimal("0.6")
    ) == Decimal("37.5")
    # average=0.5 -> good=0.6 orta noktası (0.55) -> 62.5 puan
    assert _continuous_points_higher_is_better(
        Decimal("0.55"), Decimal("0.2"), Decimal("0.35"), Decimal("0.5"), Decimal("0.6")
    ) == Decimal("62.5")


def test_higher_is_better_is_continuous_at_every_boundary():
    critical, weak, average, good = Decimal("0.2"), Decimal("0.35"), Decimal("0.5"), Decimal("0.6")
    assert _continuous_points_higher_is_better(critical, critical, weak, average, good) == Decimal("0")
    assert _continuous_points_higher_is_better(weak, critical, weak, average, good) == Decimal("25")
    assert _continuous_points_higher_is_better(average, critical, weak, average, good) == Decimal("50")
    assert _continuous_points_higher_is_better(good, critical, weak, average, good) == Decimal("100")


def test_higher_is_better_returns_none_when_a_boundary_is_missing():
    assert _continuous_points_higher_is_better(
        Decimal("0.4"), Decimal("0.2"), None, Decimal("0.5"), Decimal("0.6")
    ) is None


# --- LOWER_IS_BETTER (gerçek debt_ratio sınırları: good=0.3, ------------
# average=0.4, weak=0.6, critical=0.75) -------------------------------------


def test_lower_is_better_above_critical_locks_at_zero():
    assert _continuous_points_lower_is_better(
        Decimal("0.8"), Decimal("0.75"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")
    ) == Decimal("0")


def test_lower_is_better_at_or_below_good_locks_at_100():
    assert _continuous_points_lower_is_better(
        Decimal("0.3"), Decimal("0.75"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")
    ) == Decimal("100")
    assert _continuous_points_lower_is_better(
        Decimal("0.1"), Decimal("0.75"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")
    ) == Decimal("100")


def test_lower_is_better_interpolates_midpoints():
    # good=0.3 -> average=0.4 orta nokta (0.35) -> 62.5 puan
    assert _continuous_points_lower_is_better(
        Decimal("0.35"), Decimal("0.75"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")
    ) == Decimal("62.5")
    # average=0.4 -> weak=0.6 orta nokta (0.5) -> 37.5 puan
    assert _continuous_points_lower_is_better(
        Decimal("0.5"), Decimal("0.75"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")
    ) == Decimal("37.5")
    # weak=0.6 -> critical=0.75 orta nokta (0.675) -> 12.5 puan
    assert _continuous_points_lower_is_better(
        Decimal("0.675"), Decimal("0.75"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")
    ) == Decimal("12.5")


def test_lower_is_better_is_continuous_at_every_boundary():
    critical, weak, average, good = Decimal("0.75"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")
    assert _continuous_points_lower_is_better(good, critical, weak, average, good) == Decimal("100")
    assert _continuous_points_lower_is_better(average, critical, weak, average, good) == Decimal("50")
    assert _continuous_points_lower_is_better(weak, critical, weak, average, good) == Decimal("25")
    assert _continuous_points_lower_is_better(critical, critical, weak, average, good) == Decimal("0")


# --- RANGE_IS_BETTER (gerçek current_ratio sınırları) -----------------------


_CR_EXCELLENT = (Decimal("1.5"), Decimal("1.8"))
_CR_GOOD = (Decimal("1.3"), Decimal("2.0"))
_CR_AVERAGE = (Decimal("1.0"), Decimal("2.5"))
_CR_WEAK = (Decimal("0.8"), Decimal("3.5"))


def test_range_is_better_inside_excellent_band_locks_at_100():
    assert _continuous_points_range_is_better(
        Decimal("1.65"), _CR_EXCELLENT, _CR_GOOD, _CR_AVERAGE, _CR_WEAK
    ) == Decimal("100")


def test_range_is_better_outside_weak_band_locks_at_zero_either_side():
    assert _continuous_points_range_is_better(
        Decimal("0.5"), _CR_EXCELLENT, _CR_GOOD, _CR_AVERAGE, _CR_WEAK
    ) == Decimal("0")
    assert _continuous_points_range_is_better(
        Decimal("4.0"), _CR_EXCELLENT, _CR_GOOD, _CR_AVERAGE, _CR_WEAK
    ) == Decimal("0")


def test_range_is_better_interpolates_symmetrically_on_low_and_high_side():
    # good bandinda (1.3,2.0), excellent (1.5,1.8) disinda, dusuk taraf
    low_side = _continuous_points_range_is_better(
        Decimal("1.4"), _CR_EXCELLENT, _CR_GOOD, _CR_AVERAGE, _CR_WEAK
    )
    high_side = _continuous_points_range_is_better(
        Decimal("1.9"), _CR_EXCELLENT, _CR_GOOD, _CR_AVERAGE, _CR_WEAK
    )
    assert low_side == Decimal("87.5")
    assert high_side == Decimal("87.5")


def test_range_is_better_is_continuous_at_band_boundaries():
    # good bandinin alt siniri (1.3) -- hem "average" hem "good" tarafindan
    # ayni degere yakinsamali.
    just_inside_good = _continuous_points_range_is_better(
        Decimal("1.3"), _CR_EXCELLENT, _CR_GOOD, _CR_AVERAGE, _CR_WEAK
    )
    just_below_good = _continuous_points_range_is_better(
        Decimal("1.299999"), _CR_EXCELLENT, _CR_GOOD, _CR_AVERAGE, _CR_WEAK
    )
    assert just_inside_good == Decimal("75")
    assert abs(just_below_good - Decimal("75")) < Decimal("0.001")


def test_range_is_better_returns_none_when_a_band_is_missing():
    assert _continuous_points_range_is_better(
        Decimal("1.4"), _CR_EXCELLENT, None, _CR_AVERAGE, _CR_WEAK
    ) is None


# --- compute_ratio_score (üst seviye orkestrasyon) -------------------------


def test_compute_ratio_score_returns_none_for_non_evaluated_signal():
    points, fallback = compute_ratio_score(
        "current_ratio", {"benchmark_status": "ratio_status_not_calculated", "ratio_value": None}
    )
    assert points is None and fallback is False


def test_compute_ratio_score_uses_real_equity_ratio_thresholds():
    points, fallback = compute_ratio_score(
        "equity_ratio",
        {"benchmark_status": "evaluated", "ratio_value": Decimal("0.55"), "tier": "good"},
    )
    assert points == Decimal("62.5")
    assert fallback is False


def test_compute_ratio_score_uses_real_current_ratio_range_thresholds():
    points, fallback = compute_ratio_score(
        "current_ratio",
        {"benchmark_status": "evaluated", "ratio_value": Decimal("1.65"), "tier": "excellent"},
    )
    assert points == Decimal("100")
    assert fallback is False


def test_compute_ratio_score_falls_back_to_tier_constant_when_thresholds_incomplete():
    # Sandbox-only sentetik kayıt (tests/test_ratio_formulas_unit.py'deki
    # ::test_register_ratio_formula_accepts_already_registered_dependency
    # test'inde kurulu try/finally + del RATIO_REGISTRY/BENCHMARK_REGISTRY
    # konvansiyonuyla AYNI teknik) -- eksik bir sinirla (weak=None) fallback
    # yolunu izole test eder. GERÇEK Docker/pytest ortamında (Milestone
    # 4.3D final doğrulama) bu kaydın GERİ ALINMAMASI, tüm test dosyalarının
    # TEK process'te ve pytest'in alfabetik toplama sırasına göre çalıştığı
    # ortamda test_ratio_formulas_unit.py::test_list_ratio_formulas_by_
    # category'yi kirletip BAŞARISIZ etmişti -- bu yüzden try/finally ile
    # KAYITSIZ ŞARTSIZ (test başarılı da olsa, assertion patlasa da) geri
    # alınır.
    register_ratio_formula(
        RatioFormulaMetadata(
            key="_test_hs_incomplete_thresholds_ratio",
            category="liquidity",
            display_name_tr="Test",
            unit="ratio",
            calculation_strategy="sum_division",
            numerator_fields=("current_assets",),
            denominator_fields=("short_term_liabilities",),
        )
    )
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_hs_incomplete_thresholds_ratio",
                ratio_code="_test_hs_incomplete_thresholds_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("2"), average=None,
                    weak=Decimal("1"), critical=Decimal("0.5"),
                ),
            )
        )
        try:
            points, fallback = compute_ratio_score(
                "_test_hs_incomplete_thresholds_ratio",
                {"benchmark_status": "evaluated", "ratio_value": Decimal("1.2"), "tier": "weak"},
            )
            assert fallback is True
            assert points == Decimal("25")  # TIER_TO_POINTS["weak"]
        finally:
            del BENCHMARK_REGISTRY["_test_hs_incomplete_thresholds_ratio"]
    finally:
        del RATIO_REGISTRY["_test_hs_incomplete_thresholds_ratio"]


def test_ratio_registry_size_restored_after_incomplete_thresholds_test():
    # BAĞLAYICI regresyon testi (Milestone 4.3D final doğrulama, madde 7):
    # yukarıdaki test kendi geçici kaydını try/finally ile geri aldığı için,
    # bu test AYRI ÇALIŞTIRILDIĞINDA DAHİ RATIO_REGISTRY'nin gerçek boyutu
    # (57) hiçbir "_test_*" kalıntısı OLMADAN korunmalıdır. "tests/test_
    # ratio_formulas_unit.py::test_list_ratio_formulas_by_category" tam
    # bu sızıntı yüzünden gerçek Docker/pytest koşusunda başarısız olmuştu.
    leaked_test_keys = {code for code in RATIO_REGISTRY if code.startswith("_test")}
    assert leaked_test_keys == set(), f"RATIO_REGISTRY'de kalıntı test kaydı bulundu: {leaked_test_keys}"
    assert len(RATIO_REGISTRY) == 57
