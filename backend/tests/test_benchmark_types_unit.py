"""
Milestone 4.3C (Benchmark Engine) / Adım 1: `app/engines/common/
benchmark_types.py` ve `app/engines/common/reliability.py` için birim
testleri. `tests/test_ratio_formulas_unit.py`'nin (Milestone 4.3A/B)
disipliniyle -- sqlalchemy'siz, sandbox'ta gerçekten çalıştırılabilir.

NOT: `BENCHMARK_REGISTRY` modül-seviyesi bir singleton'dır. Bu test
dosyasındaki fixture'lar `_test_`/`_test-` ön ekli, GERÇEK 48 üretim
benchmark_code'uyla (Adım 3-6'da eklenecek, ratio_code'la aynı adı
taşıyacak) ÇAKIŞMAYACAK şekilde isimlendirilmiştir.
"""

from decimal import Decimal

from app.engines.common.benchmark_types import (
    BENCHMARK_REGISTRY,
    BenchmarkComputationStatus,
    BenchmarkIdealDirection,
    BenchmarkMetadata,
    BenchmarkThresholds,
    STATUTORY_CORPORATE_TAX_RATE_TR,
    effective_tax_rate_thresholds,
    evaluate_benchmark,
    get_benchmark,
    list_benchmarks_by_category,
    list_benchmarks_for_ratio,
    register_benchmark,
)
from app.engines.common.reliability import RELIABILITY_RANK, worse_reliability


# --- Fixture kayıtları (modül yüklenirken BİR KEZ) ----------------------

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="_test_higher",
        ratio_code="current_ratio",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("4"),
            average=Decimal("3"),
            weak=Decimal("2"),
            critical=Decimal("1"),
            warning_threshold=Decimal("2"),
        ),
        industry_overrides={
            "tekstil": BenchmarkThresholds(
                excellent=None,
                good=Decimal("5"),
                average=Decimal("4"),
                weak=Decimal("3"),
                critical=Decimal("2"),
                warning_threshold=Decimal("3"),
            )
        },
        company_size_overrides={
            "large": BenchmarkThresholds(
                excellent=None,
                good=Decimal("6"),
                average=Decimal("5"),
                weak=Decimal("4"),
                critical=Decimal("3"),
                warning_threshold=Decimal("4"),
            )
        },
    )
)

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="_test_lower",
        ratio_code="debt_ratio",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("1"),
            average=Decimal("2"),
            weak=Decimal("3"),
            critical=Decimal("4"),
            warning_threshold=Decimal("3"),
        ),
    )
)

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="_test_range",
        ratio_code="current_ratio",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=(Decimal("1.5"), Decimal("1.8")),
            good=(Decimal("1.3"), Decimal("2.0")),
            average=(Decimal("1.0"), Decimal("2.5")),
            weak=(Decimal("0.8"), Decimal("3.5")),
            critical=None,
            warning_threshold=Decimal("1.0"),
        ),
    )
)

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="_test_growth_ok",
        ratio_code="sales_growth",
        category="growth",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("40"),
            average=Decimal("20"),
            weak=Decimal("10"),
            critical=Decimal("0"),
            warning_threshold=Decimal("5"),
        ),
        inflation_adjusted=False,
        reliability_ceiling="medium_low",
    )
)


# --- register_benchmark doğrulama testleri ------------------------------


def test_duplicate_benchmark_code_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_higher",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("4"), average=Decimal("3"),
                    weak=Decimal("2"), critical=Decimal("1"),
                ),
            )
        )
        assert False, "yinelenen benchmark_code reddedilmeliydi"
    except ValueError:
        pass


def test_unknown_ratio_code_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_unknown_ratio",
                ratio_code="this_ratio_does_not_exist",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("4"), average=Decimal("3"),
                    weak=Decimal("2"), critical=Decimal("1"),
                ),
            )
        )
        assert False, "var olmayan ratio_code reddedilmeliydi"
    except ValueError:
        pass


def test_unit_mismatch_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_unit_mismatch",
                ratio_code="current_ratio",  # unit="ratio"
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="percentage",  # UYUŞMUYOR
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("4"), average=Decimal("3"),
                    weak=Decimal("2"), critical=Decimal("1"),
                ),
            )
        )
        assert False, "birim uyuşmazlığı reddedilmeliydi"
    except ValueError:
        pass


def test_currency_unit_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_currency",
                ratio_code="net_working_capital",  # unit="currency"
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="currency",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("4"), average=Decimal("3"),
                    weak=Decimal("2"), critical=Decimal("1"),
                ),
            )
        )
        assert False, "unit=currency reddedilmeliydi"
    except ValueError:
        pass


def test_unknown_benchmark_type_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_unknown_type",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="peer_relative_not_implemented",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("4"), average=Decimal("3"),
                    weak=Decimal("2"), critical=Decimal("1"),
                ),
            )
        )
        assert False, "bilinmeyen benchmark_type reddedilmeliydi"
    except ValueError:
        pass


def test_provisional_with_high_ceiling_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_provisional_high",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("4"), average=Decimal("3"),
                    weak=Decimal("2"), critical=Decimal("1"),
                ),
                provisional=True,
                reliability_ceiling="high",
            )
        )
        assert False, "provisional=True + reliability_ceiling=high reddedilmeliydi"
    except ValueError:
        pass


def test_growth_without_inflation_adjusted_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_growth_missing_flag",
                ratio_code="sales_growth",
                category="growth",
                benchmark_type="threshold_bands",
                unit="percentage",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("40"), average=Decimal("20"),
                    weak=Decimal("10"), critical=Decimal("0"),
                ),
                reliability_ceiling="medium_low",
                # inflation_adjusted BİLİNÇLİ OLARAK verilmedi -> None
            )
        )
        assert False, "growth kategorisinde inflation_adjusted=None reddedilmeliydi"
    except ValueError:
        pass


def test_growth_with_wrong_reliability_ceiling_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_growth_wrong_ceiling",
                ratio_code="sales_growth",
                category="growth",
                benchmark_type="threshold_bands",
                unit="percentage",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("40"), average=Decimal("20"),
                    weak=Decimal("10"), critical=Decimal("0"),
                ),
                inflation_adjusted=False,
                reliability_ceiling="medium",  # "medium_low" OLMALIYDI
            )
        )
        assert False, "growth kategorisinde reliability_ceiling=medium reddedilmeliydi"
    except ValueError:
        pass


def test_range_is_better_scalar_threshold_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_range_scalar_bad",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=Decimal("1.5"),  # tuple OLMALIYDI
                    good=(Decimal("1.3"), Decimal("2.0")),
                    average=(Decimal("1.0"), Decimal("2.5")),
                    weak=(Decimal("0.8"), Decimal("3.5")),
                    critical=None,
                ),
            )
        )
        assert False, "RANGE_IS_BETTER'da skaler eşik reddedilmeliydi"
    except ValueError:
        pass


def test_higher_is_better_tuple_threshold_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_higher_tuple_bad",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None,
                    good=(Decimal("1"), Decimal("2")),  # skaler OLMALIYDI
                    average=Decimal("3"),
                    weak=Decimal("2"),
                    critical=Decimal("1"),
                ),
            )
        )
        assert False, "HIGHER_IS_BETTER'da tuple eşik reddedilmeliydi"
    except ValueError:
        pass


def test_higher_is_better_missing_critical_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_higher_no_critical",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None, good=Decimal("4"), average=Decimal("3"),
                    weak=Decimal("2"), critical=None,
                ),
            )
        )
        assert False, "HIGHER_IS_BETTER'da critical=None reddedilmeliydi"
    except ValueError:
        pass


def test_range_is_better_with_critical_set_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_range_critical_set",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=(Decimal("1.5"), Decimal("1.8")),
                    good=(Decimal("1.3"), Decimal("2.0")),
                    average=(Decimal("1.0"), Decimal("2.5")),
                    weak=(Decimal("0.8"), Decimal("3.5")),
                    critical=Decimal("0"),  # None OLMALIYDI
                ),
            )
        )
        assert False, "RANGE_IS_BETTER'da critical dolu olması reddedilmeliydi"
    except ValueError:
        pass


def test_monotonic_violation_higher_is_better_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_monotonic_bad",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=None,
                    good=Decimal("2"),      # good < average -- BOZUK sıra
                    average=Decimal("3"),
                    weak=Decimal("1"),
                    critical=Decimal("0"),
                ),
            )
        )
        assert False, "monotonik olmayan sıra reddedilmeliydi"
    except ValueError:
        pass


def test_range_nesting_violation_rejected():
    try:
        register_benchmark(
            BenchmarkMetadata(
                benchmark_code="_test_range_nesting_bad",
                ratio_code="current_ratio",
                category="liquidity",
                benchmark_type="threshold_bands",
                unit="ratio",
                ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
                default_thresholds=BenchmarkThresholds(
                    excellent=(Decimal("1.0"), Decimal("2.0")),  # good'u AŞIYOR
                    good=(Decimal("1.3"), Decimal("1.8")),
                    average=(Decimal("1.0"), Decimal("2.5")),
                    weak=(Decimal("0.8"), Decimal("3.5")),
                    critical=None,
                ),
            )
        )
        assert False, "iç içe geçmeyen (nesting ihlali) bantlar reddedilmeliydi"
    except ValueError:
        pass


# --- evaluate_benchmark davranış testleri -------------------------------


def test_evaluate_not_registered():
    result = evaluate_benchmark(
        "_test_does_not_exist", "calculated", Decimal("1.5"), "high"
    )
    assert result.status == BenchmarkComputationStatus.BENCHMARK_NOT_REGISTERED
    assert result.tier is None
    assert result.value is None


def test_evaluate_ratio_status_not_calculated_passthrough():
    result = evaluate_benchmark("_test_higher", "missing_input", None, "not_calculable")
    assert result.status == BenchmarkComputationStatus.RATIO_STATUS_NOT_CALCULATED
    assert result.tier is None
    assert result.underlying_ratio_status == "missing_input"


def test_evaluate_no_obligation_passthrough_no_fabricated_tier():
    # NO_OBLIGATION -- olumlu bir iş durumu olsa da value=None olduğu için
    # sayısal bir tier FABRİKE EDİLMEZ (tasarım dokümanı Bölüm 16).
    result = evaluate_benchmark("_test_higher", "no_obligation", None, "not_calculable")
    assert result.status == BenchmarkComputationStatus.RATIO_STATUS_NOT_CALCULATED
    assert result.tier is None
    assert result.underlying_ratio_status == "no_obligation"


def test_higher_is_better_all_tiers_both_boundary_sides():
    cases = [
        (Decimal("0.5"), "critical"),
        (Decimal("0.999"), "critical"),
        (Decimal("1"), "weak"),      # sınırın TAM ÜZERİ -- weak (>=)
        (Decimal("1.999"), "weak"),
        (Decimal("2"), "average"),
        (Decimal("2.999"), "average"),
        (Decimal("3"), "good"),
        (Decimal("3.999"), "good"),
        (Decimal("4"), "excellent"),
        (Decimal("100"), "excellent"),
    ]
    for value, expected_tier in cases:
        result = evaluate_benchmark("_test_higher", "calculated", value, "high")
        assert result.status == BenchmarkComputationStatus.EVALUATED
        assert result.tier == expected_tier, f"value={value}: {result.tier} != {expected_tier}"


def test_lower_is_better_all_tiers_both_boundary_sides():
    cases = [
        (Decimal("5"), "critical"),
        (Decimal("4.001"), "critical"),
        (Decimal("4"), "weak"),
        (Decimal("3.001"), "weak"),
        (Decimal("3"), "average"),
        (Decimal("2.001"), "average"),
        (Decimal("2"), "good"),
        (Decimal("1.001"), "good"),
        (Decimal("1"), "excellent"),
        (Decimal("0"), "excellent"),
    ]
    for value, expected_tier in cases:
        result = evaluate_benchmark("_test_lower", "calculated", value, "high")
        assert result.status == BenchmarkComputationStatus.EVALUATED
        assert result.tier == expected_tier, f"value={value}: {result.tier} != {expected_tier}"


def test_range_is_better_nested_tiers():
    cases = [
        (Decimal("1.6"), "excellent"),   # [1.5,1.8] icinde
        (Decimal("1.5"), "excellent"),
        (Decimal("1.8"), "excellent"),
        (Decimal("1.4"), "good"),        # good[1.3,2.0] icinde, excellent disinda
        (Decimal("1.9"), "good"),
        (Decimal("1.1"), "average"),     # average[1.0,2.5] icinde, good disinda
        (Decimal("2.3"), "average"),
        (Decimal("0.9"), "weak"),        # weak[0.8,3.5] icinde, average disinda
        (Decimal("3.0"), "weak"),
        (Decimal("0.5"), "critical"),    # weak bandinin TAMAMEN disinda
        (Decimal("4.0"), "critical"),
    ]
    for value, expected_tier in cases:
        result = evaluate_benchmark("_test_range", "calculated", value, "high")
        assert result.status == BenchmarkComputationStatus.EVALUATED
        assert result.tier == expected_tier, f"value={value}: {result.tier} != {expected_tier}"


def test_warning_flag_higher_is_better():
    below = evaluate_benchmark("_test_higher", "calculated", Decimal("1.5"), "high")
    above = evaluate_benchmark("_test_higher", "calculated", Decimal("2.5"), "high")
    assert below.warning_flag is True
    assert above.warning_flag is False


def test_warning_flag_lower_is_better():
    above = evaluate_benchmark("_test_lower", "calculated", Decimal("3.5"), "high")
    below = evaluate_benchmark("_test_lower", "calculated", Decimal("2.5"), "high")
    assert above.warning_flag is True
    assert below.warning_flag is False


def test_warning_flag_range_is_better_single_sided():
    low = evaluate_benchmark("_test_range", "calculated", Decimal("0.9"), "high")
    high = evaluate_benchmark("_test_range", "calculated", Decimal("3.0"), "high")
    assert low.warning_flag is True   # yalnizca dusuk taraf isaretlenir
    assert high.warning_flag is False


def test_reliability_ceiling_caps_result():
    # ratio kendi reliability'si "high" olsa bile, ceiling "medium" ise
    # nihai sonuc "medium" olmali (_test_higher ceiling="medium" varsayilan).
    result = evaluate_benchmark("_test_higher", "calculated", Decimal("4.5"), "high")
    assert result.reliability == "medium"


def test_ratio_reliability_worse_than_ceiling_wins():
    result = evaluate_benchmark("_test_higher", "calculated", Decimal("4.5"), "medium_low")
    assert result.reliability == "medium_low"


def test_growth_entry_carries_inflation_adjusted_false():
    result = evaluate_benchmark("_test_growth_ok", "calculated", Decimal("25"), "high")
    assert result.status == BenchmarkComputationStatus.EVALUATED
    assert result.inflation_adjusted is False
    assert result.reliability == "medium_low"


def test_override_resolution_order_industry_beats_company_size_beats_default():
    # deger=4.5: default'ta good(<4? hayir >=4 excellent... let's pick a
    # value that differentiates all three scope'lari acikca.
    value = Decimal("4.5")

    default_only = evaluate_benchmark(
        "_test_higher", "calculated", value, "high"
    )
    assert default_only.tier == "excellent"  # default: >=4 -> excellent
    assert default_only.resolved_scope == "default"

    company_size_only = evaluate_benchmark(
        "_test_higher", "calculated", value, "high", company_size_bucket="large"
    )
    # company_size bandinda (critical=3,weak=4,average=5,good=6): 4.5 -> average
    assert company_size_only.resolved_scope == "company_size"
    assert company_size_only.tier == "average"

    industry_wins = evaluate_benchmark(
        "_test_higher", "calculated", value, "high",
        industry_code="tekstil", company_size_bucket="large",
    )
    # industry bandinda (critical=2,weak=3,average=4,good=5): 4.5 -> good
    assert industry_wins.resolved_scope == "industry"
    assert industry_wins.tier == "good"


def test_unknown_override_keys_fall_back_to_default():
    result = evaluate_benchmark(
        "_test_higher", "calculated", Decimal("4.5"), "high",
        industry_code="bilinmeyen_sektor", company_size_bucket="bilinmeyen_olcek",
    )
    assert result.resolved_scope == "default"
    assert result.tier == "excellent"


def test_list_and_get_helpers():
    assert get_benchmark("_test_higher") is not None
    assert get_benchmark("_test_does_not_exist") is None
    assert any(m.benchmark_code == "_test_higher" for m in list_benchmarks_for_ratio("current_ratio"))
    assert any(m.benchmark_code == "_test_range" for m in list_benchmarks_for_ratio("current_ratio"))
    assert any(m.benchmark_code == "_test_higher" for m in list_benchmarks_by_category("liquidity"))


# --- effective_tax_rate_thresholds / statutory rate merkezileştirme -----


def test_effective_tax_rate_thresholds_default_statutory_rate():
    thresholds = effective_tax_rate_thresholds()
    assert thresholds.excellent == (Decimal("0.20"), Decimal("0.28"))
    assert thresholds.good == (Decimal("0.15"), Decimal("0.33"))
    assert thresholds.average == (Decimal("0.10"), Decimal("0.40"))
    assert thresholds.weak == (Decimal("0"), Decimal("0.60"))
    assert thresholds.critical is None
    assert thresholds.warning_threshold == (Decimal("0.15"), Decimal("0.35"))


def test_effective_tax_rate_thresholds_shift_with_different_statutory_rate():
    # Mevzuat degisirse (ornek: %30) TUM bant TEK parametreden kayar --
    # baska hicbir yerde ham sayi tekrar edilmez (2. tur onay karar #9).
    thresholds = effective_tax_rate_thresholds(Decimal("0.30"))
    assert thresholds.excellent == (Decimal("0.25"), Decimal("0.33"))
    assert thresholds.good == (Decimal("0.20"), Decimal("0.38"))


def test_statutory_rate_constant_is_a_quarter():
    # bugunku Turkiye kurumlar vergisi oranina yakin bir sabit --
    # dokumante edilen tek merkezi kaynak.
    assert STATUTORY_CORPORATE_TAX_RATE_TR == Decimal("0.25")


# --- app/engines/common/reliability.py ----------------------------------


def test_worse_reliability_basic_ranking():
    assert worse_reliability("high", "medium") == "medium"
    assert worse_reliability("medium", "high") == "medium"
    assert worse_reliability("medium_low", "medium") == "medium_low"
    assert worse_reliability("not_calculable", "high") == "not_calculable"


def test_worse_reliability_equal_returns_first():
    assert worse_reliability("medium", "medium") == "medium"


def test_reliability_rank_contains_expected_keys():
    for key in ("high", "medium", "medium_low", "low", "not_calculable"):
        assert key in RELIABILITY_RANK


# --- BENCHMARK_REGISTRY sözleşme (gerçek üretim girdileriyle çakışmama) -


_KNOWN_TEST_FIXTURE_CODES = {
    "_test_higher",
    "_test_lower",
    "_test_range",
    "_test_growth_ok",
}


def test_test_fixtures_are_prefixed_and_do_not_collide_with_real_benchmark_codes():
    """
    DÜZELTME (bu test eskiydi): önceki hâli, bu dosyanın test edildiği ANDA
    `BENCHMARK_REGISTRY`'de bu dosyanın `_test_*` fixture'ları DIŞINDA
    HİÇBİR gerçek kayıt olmadığını varsayıyordu. Bu varsayım yalnızca
    `run_tests.py`'nin SABİT dosya sırasında (bu dosya, `benchmark_
    registry.py`'yi import eden dosyalardan ÖNCE çalıştığı sürece) doğruydu.
    `pytest` gibi dosyaları ALFABETİK sıralayan bir test collector'da
    `test_benchmark_registry_unit.py` ("r" < "t") bu dosyadan ÖNCE çalışır
    ve `BENCHMARK_REGISTRY`'ye 48 GERÇEK girdiyi ZATEN kaydetmiş olur --
    bu, implementasyonun bir HATASI değil, tam olarak Milestone 4.3C'nin
    AMACIDIR (gerçek benchmark kayıtlarının var olması beklenir ve
    serbesttir).

    Bu test artık registry BÜYÜKLÜĞÜNÜ kısıtlamıyor -- yalnızca ORİJİNAL
    NİYETİ doğruluyor:
      - bu dosyanın fixture'ları HER ZAMAN "_test" ile başlar,
      - fixture kodları GERÇEK ratio_code/benchmark_code adlarıyla ASLA
        çakışmaz (hiçbir RATIO_REGISTRY anahtarı "_test" ile başlamadığı
        için bu yapısal olarak garanti edilir),
      - gerçek (üretim) benchmark kayıtlarının BENCHMARK_REGISTRY'de
        bulunması TAMAMEN İZİNLİDİR ve beklenir.
    """

    from app.engines.common.ratio_formulas import RATIO_REGISTRY

    # 1) Bu dosyanın bilinen fixture'ları gerçekten kayıtlı VE "_test" ile
    #    başlıyor.
    for code in _KNOWN_TEST_FIXTURE_CODES:
        assert code in BENCHMARK_REGISTRY, f"beklenen fixture kayıtlı değil: {code}"
        assert code.startswith("_test"), f"fixture kodu '_test' ile başlamalı: {code}"

    # 2) Fixture kodları hiçbir gerçek ratio_code ile ÇAKIŞMIYOR (yapısal
    #    garanti: hiçbir gerçek RATIO_REGISTRY anahtarı "_test" ile
    #    BAŞLAMAZ).
    for ratio_code in RATIO_REGISTRY:
        assert not ratio_code.startswith("_test"), (
            f"beklenmeyen: gerçek bir ratio_code '_test' ile başlıyor: {ratio_code}"
        )
    assert _KNOWN_TEST_FIXTURE_CODES.isdisjoint(RATIO_REGISTRY)

    # 3) Gerçek (üretim) benchmark kayıtları SERBESTÇE var olabilir --
    #    registry büyüklüğü ARTIK KISITLANMIYOR. Bu, yalnızca bir
    #    bilgilendirme/dokümantasyon amaçlı sayımdır, bir assertion DEĞİL.
    real_entries = [c for c in BENCHMARK_REGISTRY if c not in _KNOWN_TEST_FIXTURE_CODES]
    # (gerçek girdi sayısı 0 da olabilir, 48 de olabilir -- ikisi de GEÇERLİ,
    # çalışma sırasına bağlıdır; bu test bunu KISITLAMAZ.)
    assert isinstance(real_entries, list)
