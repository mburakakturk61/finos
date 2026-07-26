"""
Milestone 4.3C (Benchmark Engine) -- Adım 1: temel veri modeli, kapalı
`threshold_bands` stratejisi, `register_benchmark`/`evaluate_benchmark`.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3C_BENCHMARK_ENGINE_DESIGN.md
(2. tur onay, 9 bağlayıcı karar). Bu modül `app/engines/common/
ratio_formulas.py`'nin (Milestone 4.3A/B) BİREBİR aynı disipliniyle
yazılmıştır: eval/exec/dinamik expression KESİNLİKLE YASAK, kapalı bir
strateji kümesi, kayıt anında (register_ ANINDA, çalışma zamanında değil)
doğrulama, hiçbir ham exception dışarı sızmaz.

**Bağlayıcı sınır (2. tur onay karar #6):** bu modül HİÇBİR
`EngineAdapter`/`AnalysisType`/DB kaydına bağlı DEĞİLDİR -- yalnızca saf,
bağımsız bir Python kütüphanesidir. `app/engines/financial_ratios/**`
dosyalarının MEVCUT içeriğine HİÇ dokunulmadı (Bölüm 3 -- "mevcut
mantıkta değişiklik yok" kısıtı, tasarım dokümanının Bölüm 15'inde
önerilen "_worse_reliability iki motor da import eder" notundan DAHA
KATI/güvenli bir yorumla uygulanmıştır: `financial_ratios/service.py`
DEĞİŞTİRİLMEDİ, yalnızca YENİ `app/engines/common/reliability.py`
Benchmark Engine tarafından kullanılıyor -- bu, zaten test edilmiş/
onaylı 4.3B kodunu gereksiz yere yeniden açmamak için BİLİNÇLİ bir
sapmadır, final raporda ayrıca belirtilecektir).

sqlalchemy/fastapi/pydantic'e SIFIR bağımlı (mevcut `app/engines/
common/**` deseniyle tutarlı, sandbox'ta gerçekten çalıştırılabilir).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
import enum
from typing import Any, Callable

from app.engines.common.ratio_formulas import RATIO_REGISTRY, get_ratio_formula
from app.engines.common.reliability import RELIABILITY_RANK, worse_reliability


# --- Bölüm 5/9: merkezi kaynak sabitleri --------------------------------

# 2. tur onay karar #9: yasal kurumlar vergisi oranı TEK bir merkezi
# yerden okunur -- başka HİÇBİR dosyada ham sayı olarak TEKRAR EDİLMEZ.
# Değiştiğinde (mevzuat değişikliği) yalnızca bu satır güncellenir,
# effective_tax_rate benchmark'ının TÜM bantları otomatik kayar (bkz.
# `_effective_tax_rate_thresholds` ve app/engines/common/
# benchmark_registry.py::register kaydı).
STATUTORY_CORPORATE_TAX_RATE_TR: Decimal = Decimal("0.25")


class BenchmarkIdealDirection(str, enum.Enum):
    """
    Bir oranın "iyi" yönü. `RANGE_IS_BETTER`, iki ucun da (çok düşük VEYA
    çok yüksek) riskli olabileceği oranlar için (ör. `current_ratio`,
    `payables_turnover` -- 2. tur onay karar #3) kullanılır; bantlar İÇ
    İÇE (excellent en dar/merkez, critical en geniş/dış) modellenir --
    bkz. `BenchmarkThresholds` docstring'i.
    """

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    RANGE_IS_BETTER = "range_is_better"


class BenchmarkComputationStatus(str, enum.Enum):
    """
    `ComputationStatus`'un (ratio_formulas.py) benchmark karşılığı --
    "hesaplanamadı" ile "hesaplandı ama X tier'ına düştü" KESİNLİKLE
    karıştırılmaz.

    EVALUATED: ratio CALCULATED VE value dolu VE ilgili benchmark
        kayıtlı -- tier ataması yapıldı.
    RATIO_STATUS_NOT_CALCULATED: ratio `status != calculated`
        (missing_input/undefined_zero_denominator/no_obligation/
        not_applicable/not_calculable) -- benchmark DEĞERLENDİRİLMEZ,
        orijinal ratio status'u şeffafça taşınır, HİÇBİR tier FABRİKE
        EDİLMEZ.
    BENCHMARK_NOT_REGISTERED: `benchmark_code`, `BENCHMARK_REGISTRY`'de
        yok (ör. cash_flow kategorisinin 6 oranı, veya `net_working_capital`
        gibi unit=currency bir oran).
    PERCENTILE_DATA_UNAVAILABLE: rezerve (4.3C'de `supports_percentile`
        her yerde `False` olduğu için ASLA tetiklenmez).
    STALE_BENCHMARK_DATA: rezerve (tasarım dokümanı Bölüm 17 --
        `compatible_ratio_registry_version` uyuşmazlığı senaryosu için;
        bu alan henüz `BenchmarkMetadata`'ya eklenmedi, 4.3C'de
        tetiklenmez).
    """

    EVALUATED = "evaluated"
    RATIO_STATUS_NOT_CALCULATED = "ratio_status_not_calculated"
    BENCHMARK_NOT_REGISTERED = "benchmark_not_registered"
    PERCENTILE_DATA_UNAVAILABLE = "percentile_data_unavailable"
    STALE_BENCHMARK_DATA = "stale_benchmark_data"


# `warning_threshold` VE her tier alanı için iki olası şekil:
#   - HIGHER_IS_BETTER / LOWER_IS_BETTER: tek bir Decimal skaler (tier'ın
#     sınır noktası).
#   - RANGE_IS_BETTER: bir (min, max) Decimal çifti (tier'ın kapsayıcı
#     bandı) -- İÇ İÇE geçmiş (excellent ⊆ good ⊆ average ⊆ weak),
#     `critical` alanı bu modda kullanılmaz/None kalır (weak bandının
#     DIŞI otomatik olarak critical sayılır).
#   `warning_threshold` AYRICA tek taraflı bir skaler de olabilir (ör.
#   `current_ratio` -- yalnızca DÜŞÜK tarafı erken uyarı olarak
#   işaretlenir, yüksek taraf yalnızca tier bantlarına yansır).
ThresholdValue = "Decimal | tuple[Decimal, Decimal] | None"


@dataclass(frozen=True)
class BenchmarkThresholds:
    """
    Bkz. modül docstring'i ve yukarıdaki `ThresholdValue` açıklaması.

    HIGHER_IS_BETTER: `critical < weak < average < good` (skaler sınır
    noktaları) -- `value < critical` ise "critical", `value < weak` ise
    "weak", ..., `value >= good` ise "excellent".
    LOWER_IS_BETTER: ters yön (`value > critical` ise "critical", vb.).
    RANGE_IS_BETTER: her alan (`excellent`/`good`/`average`/`weak`) bir
    `(min, max)` tuple'ı, İÇ İÇE geçmiş kümülatif bantlar -- `value`,
    `excellent` bandındaysa "excellent", değilse `good` bandındaysa
    "good", ... `weak` bandının DIŞINDAYSA "critical". `critical` alanı
    bu modda `None` kalır (ayrı bir sınır GEREKMEZ).
    """

    excellent: ThresholdValue
    good: ThresholdValue
    average: ThresholdValue
    weak: ThresholdValue
    critical: ThresholdValue
    warning_threshold: ThresholdValue = None


@dataclass(frozen=True)
class BenchmarkMetadata:
    """
    Bir benchmark girdisinin kimliği ve sözleşmesi -- `RatioFormulaMetadata`
    (ratio_formulas.py) ile AYNI disiplin.

    2. tur onay kararlarıyla NİHAİLEŞEN alan kümesi (tasarım dokümanı
    Bölüm 5): `country_overrides`/`supports_country_override` alanları
    BİLİNÇLİ OLARAK MODELDE YOKTUR (karar #5 -- YAGNI, hiçbir iskelet
    bile eklenmez).
    """

    benchmark_code: str
    ratio_code: str          # RATIO_REGISTRY'de kayıt ANINDA var olmalı
    category: str            # ratio'nun kategorisiyle AYNI
    benchmark_type: str      # kapalı küme -- bkz. BENCHMARK_STRATEGIES
    unit: str                # RATIO_REGISTRY[ratio_code].unit ile AYNI olmalı
    ideal_direction: BenchmarkIdealDirection
    default_thresholds: BenchmarkThresholds

    # Karar #1: bu üçü HER ZAMAN BİRLİKTE, tutarlı taşınır -- 4.3C'nin
    # TÜM girdilerinde source="internal_heuristic", provisional=True,
    # reliability_ceiling="medium" (büyüme kategorisinde "medium_low",
    # karar #7).
    source: str = "internal_heuristic"
    provisional: bool = True
    reliability_ceiling: str = "medium"

    # Karar #7: yalnızca category="growth" girdilerinde anlamlıdır.
    inflation_adjusted: "bool | None" = None

    version: str = "1.0.0"
    last_reviewed_at: "date | None" = None

    supports_percentile: bool = False
    supports_industry_override: bool = False
    supports_company_size_override: bool = False

    industry_overrides: "dict[str, BenchmarkThresholds]" = field(default_factory=dict)
    company_size_overrides: "dict[str, BenchmarkThresholds]" = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkEvaluation:
    """
    `evaluate_benchmark()`'ın TAM sonucu -- `ComputationOutcome`
    (ratio_formulas.py) ile AYNI "her zaman birlikte, tutarlı üretilir"
    ilkesi.
    """

    status: BenchmarkComputationStatus
    tier: "str | None"                 # excellent/good/average/weak/critical
    value: "Decimal | None"            # değerlendirilen ratio değeri (passthrough)
    reliability: str
    warning_flag: bool = False
    underlying_ratio_status: "str | None" = None
    resolved_scope: str = "default"    # "default" | "industry" | "company_size"
    provisional: bool = True
    inflation_adjusted: "bool | None" = None
    warnings: "tuple[dict[str, Any], ...]" = ()


BENCHMARK_REGISTRY: dict[str, BenchmarkMetadata] = {}
BENCHMARK_REGISTRY_VERSION = "1.0.0"

_ELIGIBLE_UNITS = ("ratio", "percentage", "days")
_VALID_RELIABILITY_CEILINGS = ("high", "medium", "medium_low")


def _is_range_shaped(value: Any) -> bool:
    return isinstance(value, tuple) and len(value) == 2


def _validate_threshold_shape(
    thresholds: BenchmarkThresholds, ideal_direction: BenchmarkIdealDirection
) -> None:
    tier_fields = (thresholds.excellent, thresholds.good, thresholds.average, thresholds.weak)
    if ideal_direction == BenchmarkIdealDirection.RANGE_IS_BETTER:
        for tier_value in tier_fields:
            if tier_value is not None and not _is_range_shaped(tier_value):
                raise ValueError(
                    "RANGE_IS_BETTER için her tier eşiği bir (min, max) "
                    f"tuple'ı olmalı, alındı: {tier_value!r}"
                )
        if thresholds.critical is not None:
            raise ValueError(
                "RANGE_IS_BETTER modelinde 'critical' alanı kullanılmaz "
                "(weak bandının dışı otomatik olarak critical sayılır); "
                "None bırakılmalı."
            )
    else:
        for tier_value in tier_fields + (thresholds.critical,):
            if tier_value is not None and _is_range_shaped(tier_value):
                raise ValueError(
                    "HIGHER_IS_BETTER/LOWER_IS_BETTER için tier eşikleri "
                    f"tek bir skaler olmalı, tuple alındı: {tier_value!r}"
                )
        if thresholds.critical is None:
            raise ValueError(
                "HIGHER_IS_BETTER/LOWER_IS_BETTER için 'critical' alanı "
                "zorunludur (None olamaz)."
            )


def _validate_monotonic_order(
    thresholds: BenchmarkThresholds, ideal_direction: BenchmarkIdealDirection
) -> None:
    if ideal_direction == BenchmarkIdealDirection.RANGE_IS_BETTER:
        # İç içe geçme kontrolü: excellent ⊆ good ⊆ average ⊆ weak.
        bands = [
            b
            for b in (thresholds.excellent, thresholds.good, thresholds.average, thresholds.weak)
            if b is not None
        ]
        for inner, outer in zip(bands, bands[1:]):
            inner_lo, inner_hi = inner
            outer_lo, outer_hi = outer
            if not (outer_lo <= inner_lo and inner_hi <= outer_hi):
                raise ValueError(
                    "RANGE_IS_BETTER bantları iç içe geçmeli (her dış bant, "
                    f"iç bandı tamamen kapsamalı): {inner!r} ⊄ {outer!r}"
                )
        return

    values = [
        v
        for v in (
            thresholds.critical,
            thresholds.weak,
            thresholds.average,
            thresholds.good,
            thresholds.excellent,
        )
        if v is not None
    ]
    if ideal_direction == BenchmarkIdealDirection.HIGHER_IS_BETTER:
        ordered = values
    else:
        ordered = list(reversed(values))
    for a, b in zip(ordered, ordered[1:]):
        if not (a < b):
            raise ValueError(
                "Tier sınırları monoton sırayla artmalı/azalmalı "
                f"(ideal_direction={ideal_direction.value}): {values!r}"
            )


def register_benchmark(metadata: BenchmarkMetadata) -> None:
    """
    Bir `BenchmarkMetadata`'yı `BENCHMARK_REGISTRY`'ye ekler.
    `register_ratio_formula` (ratio_formulas.py) ile AYNI "kayıt anında
    doğrula, çalışma zamanında sessizce yanlış üretme" disiplini.
    """

    if metadata.benchmark_code in BENCHMARK_REGISTRY:
        raise ValueError(f"Benchmark zaten kayıtlı: {metadata.benchmark_code!r}")

    ratio_metadata = get_ratio_formula(metadata.ratio_code)
    if ratio_metadata is None:
        raise ValueError(
            f"'{metadata.benchmark_code}' benchmark'ı, RATIO_REGISTRY'de "
            f"kayıtlı olmayan '{metadata.ratio_code}' oranına bağlanmaya "
            "çalışıyor. Bağımlılıklar KENDİLERİNDEN ÖNCE kayıtlı olmalı."
        )

    if metadata.unit != ratio_metadata.unit:
        raise ValueError(
            f"'{metadata.benchmark_code}' birimi ({metadata.unit!r}), "
            f"bağlı olduğu '{metadata.ratio_code}' oranının birimiyle "
            f"({ratio_metadata.unit!r}) UYUŞMUYOR."
        )

    if metadata.unit not in _ELIGIBLE_UNITS:
        raise ValueError(
            f"unit={metadata.unit!r} olan oranlar benchmarklanamaz "
            f"(yalnızca {_ELIGIBLE_UNITS} uygundur -- ör. unit='currency' "
            "şirket ölçeğine göre doğal olarak farklılaşır, evrensel bir "
            "eşikle kıyaslanamaz)."
        )

    if metadata.benchmark_type not in BENCHMARK_STRATEGIES:
        raise ValueError(
            f"Bilinmeyen benchmark_type: {metadata.benchmark_type!r} "
            f"(benchmark: {metadata.benchmark_code!r})."
        )

    if metadata.reliability_ceiling not in _VALID_RELIABILITY_CEILINGS:
        raise ValueError(
            f"Geçersiz reliability_ceiling: {metadata.reliability_ceiling!r}"
        )
    if metadata.provisional and metadata.reliability_ceiling == "high":
        raise ValueError(
            f"'{metadata.benchmark_code}': provisional=True iken "
            "reliability_ceiling='high' OLAMAZ (2. tur onay karar #1)."
        )

    if metadata.category == "growth":
        if metadata.inflation_adjusted is None:
            raise ValueError(
                f"'{metadata.benchmark_code}': category='growth' iken "
                "inflation_adjusted None OLAMAZ (2. tur onay karar #7)."
            )
        if metadata.reliability_ceiling != "medium_low":
            raise ValueError(
                f"'{metadata.benchmark_code}': category='growth' iken "
                "reliability_ceiling='medium_low' OLMAK ZORUNDADIR "
                "(2. tur onay karar #7)."
            )

    _validate_threshold_shape(metadata.default_thresholds, metadata.ideal_direction)
    _validate_monotonic_order(metadata.default_thresholds, metadata.ideal_direction)
    for override_thresholds in (
        *metadata.industry_overrides.values(),
        *metadata.company_size_overrides.values(),
    ):
        _validate_threshold_shape(override_thresholds, metadata.ideal_direction)
        _validate_monotonic_order(override_thresholds, metadata.ideal_direction)

    BENCHMARK_REGISTRY[metadata.benchmark_code] = metadata


def get_benchmark(benchmark_code: str) -> "BenchmarkMetadata | None":
    return BENCHMARK_REGISTRY.get(benchmark_code)


def list_benchmarks_for_ratio(ratio_code: str) -> list[BenchmarkMetadata]:
    return [m for m in BENCHMARK_REGISTRY.values() if m.ratio_code == ratio_code]


def list_benchmarks_by_category(category: str) -> list[BenchmarkMetadata]:
    return [m for m in BENCHMARK_REGISTRY.values() if m.category == category]


def _resolve_thresholds(
    metadata: BenchmarkMetadata,
    *,
    industry_code: "str | None",
    company_size_bucket: "str | None",
) -> tuple[BenchmarkThresholds, str]:
    """
    Override çözümleme sırası (2. tur onay karar #2, tasarım dokümanı
    Bölüm 6.1): industry_overrides > company_size_overrides >
    default_thresholds. `country` bu zincire HİÇ DAHİL DEĞİLDİR (karar #5).
    """

    if industry_code is not None and industry_code in metadata.industry_overrides:
        return metadata.industry_overrides[industry_code], "industry"
    if (
        company_size_bucket is not None
        and company_size_bucket in metadata.company_size_overrides
    ):
        return metadata.company_size_overrides[company_size_bucket], "company_size"
    return metadata.default_thresholds, "default"


def _tier_for_scalar(
    value: Decimal, thresholds: BenchmarkThresholds, ideal_direction: BenchmarkIdealDirection
) -> str:
    if ideal_direction == BenchmarkIdealDirection.HIGHER_IS_BETTER:
        if value < thresholds.critical:
            return "critical"
        if value < thresholds.weak:
            return "weak"
        if value < thresholds.average:
            return "average"
        if value < thresholds.good:
            return "good"
        return "excellent"
    # LOWER_IS_BETTER
    if value > thresholds.critical:
        return "critical"
    if value > thresholds.weak:
        return "weak"
    if value > thresholds.average:
        return "average"
    if value > thresholds.good:
        return "good"
    return "excellent"


def _in_band(value: Decimal, band: "tuple[Decimal, Decimal] | None") -> bool:
    if band is None:
        return False
    lo, hi = band
    return lo <= value <= hi


def _tier_for_range(value: Decimal, thresholds: BenchmarkThresholds) -> str:
    if _in_band(value, thresholds.excellent):
        return "excellent"
    if _in_band(value, thresholds.good):
        return "good"
    if _in_band(value, thresholds.average):
        return "average"
    if _in_band(value, thresholds.weak):
        return "weak"
    return "critical"


def _is_warning(
    value: Decimal, ideal_direction: BenchmarkIdealDirection, warning_threshold: ThresholdValue
) -> bool:
    if warning_threshold is None:
        return False
    if _is_range_shaped(warning_threshold):
        lo, hi = warning_threshold
        return value < lo or value > hi
    if ideal_direction == BenchmarkIdealDirection.LOWER_IS_BETTER:
        return value > warning_threshold
    # HIGHER_IS_BETTER veya tek taraflı (düşük tarafı işaretleyen)
    # RANGE_IS_BETTER warning_threshold -- yalnızca düşük tarafı kontrol eder.
    return value < warning_threshold


def evaluate_threshold_bands(
    metadata: BenchmarkMetadata,
    ratio_status: str,
    ratio_value: "Decimal | None",
    ratio_reliability: str,
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
) -> BenchmarkEvaluation:
    """
    4.3C'nin TEK stratejisi: `"threshold_bands"`. Hiçbir ham exception
    dışarı sızmaz -- beklenmeyen bir durum kontrollü bir status'a
    dönüştürülür (ratio_formulas.py'nin `compute_sum_division` deseniyle
    AYNI güvenlik ilkesi).
    """

    if ratio_status != "calculated" or ratio_value is None:
        return BenchmarkEvaluation(
            status=BenchmarkComputationStatus.RATIO_STATUS_NOT_CALCULATED,
            tier=None,
            value=None,
            reliability="not_calculable",
            underlying_ratio_status=ratio_status,
            provisional=metadata.provisional,
            inflation_adjusted=metadata.inflation_adjusted,
        )

    try:
        thresholds, resolved_scope = _resolve_thresholds(
            metadata, industry_code=industry_code, company_size_bucket=company_size_bucket
        )

        if metadata.ideal_direction == BenchmarkIdealDirection.RANGE_IS_BETTER:
            tier = _tier_for_range(ratio_value, thresholds)
        else:
            tier = _tier_for_scalar(ratio_value, thresholds, metadata.ideal_direction)

        warning_flag = _is_warning(
            ratio_value, metadata.ideal_direction, thresholds.warning_threshold
        )

        final_reliability = worse_reliability(ratio_reliability, metadata.reliability_ceiling)

        return BenchmarkEvaluation(
            status=BenchmarkComputationStatus.EVALUATED,
            tier=tier,
            value=ratio_value,
            reliability=final_reliability,
            warning_flag=warning_flag,
            resolved_scope=resolved_scope,
            provisional=metadata.provisional,
            inflation_adjusted=metadata.inflation_adjusted,
        )
    except (InvalidOperation, OverflowError, ArithmeticError, TypeError) as error:
        return BenchmarkEvaluation(
            status=BenchmarkComputationStatus.BENCHMARK_NOT_REGISTERED,
            tier=None,
            value=None,
            reliability="not_calculable",
            provisional=metadata.provisional,
            inflation_adjusted=metadata.inflation_adjusted,
            warnings=(
                {
                    "code": "BENCHMARK_STRATEGY_INTERNAL_ERROR",
                    "severity": "high",
                    "message": (
                        f"'{metadata.benchmark_code}' değerlendirilirken "
                        f"beklenmeyen bir hata oluştu: {error}"
                    ),
                },
            ),
        )


# Kapalı strateji kümesi -- eval/exec YOK. 4.3C yalnızca "threshold_bands"
# implemente eder (tasarım dokümanı Bölüm 6).
BENCHMARK_STRATEGIES: dict[
    str,
    Callable[..., BenchmarkEvaluation],
] = {
    "threshold_bands": evaluate_threshold_bands,
}


def evaluate_benchmark(
    benchmark_code: str,
    ratio_status: str,
    ratio_value: "Decimal | None",
    ratio_reliability: str,
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
) -> BenchmarkEvaluation:
    """
    Financial Ratio Engine'in `compute_registered_ratio(key, facts)`'ıyla
    AYNI rolü oynayan TEK giriş noktası -- `BENCHMARK_REGISTRY[
    benchmark_code]`'i okur, kayıtlı `benchmark_type`'a karşılık gelen
    stratejiyi çağırır. `benchmark_code` kayıtlı değilse (ör. cash_flow
    kategorisi veya `net_working_capital`) kontrollü
    `BENCHMARK_NOT_REGISTERED` döner, ASLA exception fırlatmaz.
    """

    metadata = BENCHMARK_REGISTRY.get(benchmark_code)
    if metadata is None:
        return BenchmarkEvaluation(
            status=BenchmarkComputationStatus.BENCHMARK_NOT_REGISTERED,
            tier=None,
            value=None,
            reliability="not_calculable",
            provisional=True,
            warnings=(
                {
                    "code": "BENCHMARK_NOT_REGISTERED",
                    "severity": "medium",
                    "message": f"'{benchmark_code}' BENCHMARK_REGISTRY'de kayıtlı değil.",
                },
            ),
        )

    strategy_fn = BENCHMARK_STRATEGIES.get(metadata.benchmark_type)
    if strategy_fn is None:
        return BenchmarkEvaluation(
            status=BenchmarkComputationStatus.BENCHMARK_NOT_REGISTERED,
            tier=None,
            value=None,
            reliability="not_calculable",
            provisional=metadata.provisional,
            warnings=(
                {
                    "code": "UNSUPPORTED_BENCHMARK_TYPE",
                    "severity": "high",
                    "message": (
                        f"'{metadata.benchmark_type}' stratejisi kayıtlı "
                        f"değil (benchmark: {benchmark_code!r})."
                    ),
                },
            ),
        )

    return strategy_fn(
        metadata,
        ratio_status,
        ratio_value,
        ratio_reliability,
        industry_code=industry_code,
        company_size_bucket=company_size_bucket,
    )


def effective_tax_rate_thresholds(
    statutory_rate: Decimal = STATUTORY_CORPORATE_TAX_RATE_TR,
) -> BenchmarkThresholds:
    """
    2. tur onay karar #9: `effective_tax_rate` benchmark'ının bantları
    TEK bir `statutory_rate` parametresinden türetilir -- ham sayısal
    sınırlar (0.20/0.28 vb.) başka HİÇBİR dosyada sabit olarak
    TEKRARLANMAZ. Mevzuat değiştiğinde yalnızca
    `STATUTORY_CORPORATE_TAX_RATE_TR` güncellenir, bu fonksiyon
    çağrıldığında TÜM bant otomatik kayar.
    """

    return BenchmarkThresholds(
        excellent=(statutory_rate - Decimal("0.05"), statutory_rate + Decimal("0.03")),
        good=(statutory_rate - Decimal("0.10"), statutory_rate + Decimal("0.08")),
        average=(statutory_rate - Decimal("0.15"), statutory_rate + Decimal("0.15")),
        weak=(Decimal("0"), statutory_rate + Decimal("0.35")),
        critical=None,
        warning_threshold=(statutory_rate - Decimal("0.10"), statutory_rate + Decimal("0.10")),
    )
