"""
Milestone 4.3D (Financial Health Score) -- Adım 1: temel veri modeli,
enum'lar, sabitler.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3D_FINANCIAL_HEALTH_
SCORE_DESIGN.md (4. tur, 18 bağlayıcı karar). Bu modül `app/engines/
common/ratio_formulas.py` (4.3A/B) ve `app/engines/common/
benchmark_types.py`'nin (4.3C) AYNI disipliniyle yazılmıştır: eval/exec/
dinamik expression YASAK, kapalı bir dataclass/enum kümesi, sqlalchemy/
fastapi/pydantic'e SIFIR bağımlı.

**Bağlayıcı sınır (Bölüm 22 karar #10):** bu modül HİÇBİR
`EngineAdapter`/`AnalysisType`/DB kaydına bağlı DEĞİLDİR.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
import enum
from typing import Any, Callable


# --- Versiyon eksenleri (Bölüm 17 -- dört BAĞIMSIZ eksen) ---------------

HEALTH_SCORE_SCHEMA_VERSION = "1.0.0"
HEALTH_SCORE_MODEL_VERSION = "1.0.0"


class HealthScoreTier(str, enum.Enum):
    """Benchmark Engine'in tier sözlüğüyle BİREBİR aynı 5 değer."""

    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    WEAK = "weak"
    CRITICAL = "critical"


class HealthScoreComputationStatus(str, enum.Enum):
    """
    Bölüm 5/6/11: bir Financial Health Score hesaplamasının nihai durumu.

    COMPUTED: skor normal şekilde hesaplandı.
    HARD_FAIL_CAPPED: Bölüm 12'deki hard-fail kurallarından biri
        tetiklendi, `final_score` bir tavanla sınırlandı.
    INSUFFICIENT_DATA: `data_coverage_ratio < INSUFFICIENT_DATA_COVERAGE_
        THRESHOLD` (Bölüm 11, Aşama B.5) -- final_score/letter_rating
        HİÇBİR ZAMAN fabrike edilmez, ikisi de None kalır.
    """

    COMPUTED = "computed"
    HARD_FAIL_CAPPED = "hard_fail_capped"
    INSUFFICIENT_DATA = "insufficient_data"


# --- Bölüm 6.1: kontrollü sabit fallback referansı ----------------------

TIER_TO_POINTS: dict[str, Decimal] = {
    HealthScoreTier.EXCELLENT.value: Decimal("100"),
    HealthScoreTier.GOOD.value: Decimal("75"),
    HealthScoreTier.AVERAGE.value: Decimal("50"),
    HealthScoreTier.WEAK.value: Decimal("25"),
    HealthScoreTier.CRITICAL.value: Decimal("0"),
}


# --- Bölüm 9/10/11/13: 4. tur bağlayıcı sabitler ------------------------

# Bölüm 10, karar #15: BENCHMARK_REGISTRY'nin TAMAMI internal_heuristic/
# provisional olduğu için confidence HİÇBİR ZAMAN bu tavanın üzerine
# çıkamaz.
PROVISIONAL_CONFIDENCE_CEILING: Decimal = Decimal("0.60")

# Bölüm 9/11, karar #15: coverage üç bant -- < eşik: skor YOK,
# [eşik, uyarı_eşiği): skor VAR ama zorunlu uyarı, >= uyarı_eşiği: normal.
INSUFFICIENT_DATA_COVERAGE_THRESHOLD: Decimal = Decimal("0.50")
LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD: Decimal = Decimal("0.70")

# Bölüm 13, karar #10: oransal critical-override çarpanları + kategori
# başına taban (floor) -- çarpımın kendisi bu tabanın ALTINA düşürülmez.
CRITICAL_OVERRIDE_WEAK_MULTIPLIER: Decimal = Decimal("0.90")
CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER: Decimal = Decimal("0.70")
CRITICAL_OVERRIDE_CATEGORY_FLOOR: Decimal = Decimal("0.50")

# Bölüm 15, karar #13 (kullanıcı tarafından bu turda spesifik verilmedi,
# tasarımcı önerisi olarak kapatıldı): strengths/weaknesses aday sayısı.
STRENGTHS_WEAKNESSES_COUNT: int = 5

# Bölüm 10: confidence formülünün KENDİ reliability ağırlıklandırması --
# `app/engines/common/reliability.py::RELIABILITY_RANK` (high=3/medium=2/
# medium_low=1/low=1/not_calculable=0) İLE KARIŞTIRILMAMALI -- o modül
# Ratio/Benchmark Engine'in "iki güvenilirlikten kötüsünü seç" (worse_
# reliability) ihtiyacı için, TAMSAYI sıralama amaçlı. Bu sözlük ise
# Health Score'un KENDİ confidence ağırlıklı ortalaması için, 0-1
# ölçeğinde bir "ağırlık" -- farklı bir amaç, farklı bir sayı kümesi.
CONFIDENCE_RELIABILITY_WEIGHT: dict[str, Decimal] = {
    "high": Decimal("1.0"),
    "medium": Decimal("0.66"),
    "medium_low": Decimal("0.5"),
    "low": Decimal("0.33"),
    "not_calculable": Decimal("0"),
}


def normalize_weights(
    raw_weights: "dict[str, Decimal]", *, quantize_exp: str = "0.000001"
) -> "dict[str, Decimal]":
    """
    Bir ağırlık sözlüğünü (yalnızca `> 0` olan girdiler dikkate alınarak)
    toplamı TAM `Decimal("1")` olacak şekilde normalize eder -- Bölüm 9/11
    (kategori-içi missing-data yeniden ağırlıklandırması) ve Bölüm 8/11
    (registry ağırlık normalizasyonu)'nun PAYLAŞTIĞI TEK uygulama.

    `<= 0` olan girdiler `0` kalır (normalize edilmiş toplama katkısı
    yoktur). Toplam pozitif ağırlık `<= 0` ise (ör. sıfır EVALUATED oran)
    TÜM değerler `0` döner -- exception FIRLATILMAZ, bu geçerli bir iş
    durumudur (çağıran, `raw_score=None` gibi kontrollü bir sonuca
    yönlendirir). Yuvarlama artığı en büyük ham ağırlığa sahip girdiye
    eklenir/çıkarılır -- pozitif toplam varsa sonuç HER ZAMAN tam
    `Decimal("1")`'e ulaşır.
    """

    positive_total = sum(v for v in raw_weights.values() if v > 0)
    if positive_total <= 0:
        return {code: Decimal("0") for code in raw_weights}

    quant = Decimal(quantize_exp)
    normalized = {
        code: ((raw / positive_total).quantize(quant, rounding=ROUND_HALF_UP) if raw > 0 else Decimal("0"))
        for code, raw in raw_weights.items()
    }
    remainder = Decimal("1") - sum(normalized.values())
    if remainder != 0:
        target_code = max(
            (code for code, raw in raw_weights.items() if raw > 0),
            key=lambda code: raw_weights[code],
        )
        normalized[target_code] = normalized[target_code] + remainder
    return normalized


def clamp_score(value: "Decimal | None") -> "Decimal | None":
    """
    Bölüm 6'daki HER aşamada AÇIKÇA istenen `max(0, min(100, score))`
    kuralının TEK, paylaşılan uygulaması -- pipeline'ın her adımı bu
    fonksiyonu çağırır, aynı clamp mantığı birden fazla yerde elle
    TEKRARLANMAZ. `None` girdide `None` döner (fabrike bir sayı üretmez).
    """

    if value is None:
        return None
    return max(Decimal("0"), min(Decimal("100"), value))


# --- Bölüm 5: veri modeli -----------------------------------------------


@dataclass(frozen=True)
class CategoryWeightProfile:
    """Bölüm 8.2: kategori ağırlığı override mimarisinin veri modeli."""

    scope: str  # "global" | "industry" | "company_size" | "tenant"
    scope_key: "str | None"
    category_weights: "dict[str, Decimal]"


@dataclass(frozen=True)
class RatioScoreWeight:
    """
    Bölüm 8/8.1/11: bir oranın Health Score içindeki ağırlığı.

    `ratio_weight=0` -- Bölüm 8.1'in nihai sınıflandırmasıyla
    "explainability-only" (duplicate/derived) işaretli bir orandır;
    sayısal skora KATKI VERMEZ, yalnızca açıklama amaçlı görüntülenir.
    """

    ratio_code: str
    category: str
    ratio_weight: Decimal
    excluded_as_duplicate_of: "str | None" = None
    duplicate_relationship: "str | None" = None
    # "identical_formula" | "algebraic_complement" |
    # "reciprocal_via_period_constant" | "summary_signal_normalized"


@dataclass(frozen=True)
class HardFailRule:
    """
    Bölüm 12: ikili, yapısal, çok yüksek eşikli bir kural -- tetiklendiğinde
    `final_score`'un tavanını sert biçimde sınırlar.

    `predicate`, hem `ratio_result_json` DEĞERLERİNİ (ratios: dict[str,
    Decimal | None]) hem `benchmark_result_json` TIER'larını (benchmarks:
    dict[str, dict]) okuyabilir (Bölüm 4.1, 3. tur revizyonla genişletilen
    girdi sözleşmesi). Eksik veri (ilgili oran None/hesaplanamamış) HER
    ZAMAN `False` döndürmelidir -- eksik veri hard-fail olarak
    YORUMLANMAZ (Bölüm 11/12).
    """

    rule_code: str
    predicate: "Callable[[dict[str, Any], dict[str, Any]], bool]"
    score_ceiling: Decimal
    rationale_tr: str


@dataclass(frozen=True)
class CriticalOverrideRule:
    """
    Bölüm 13: oransal çarpan modeli -- `weak_multiplier`/`critical_
    multiplier`, ilgili oranın tier'ı sırasıyla "weak"/"critical" olduğunda
    KENDİ kategorisinin ham skoruna uygulanır (Aşama F, kategoriler arası
    ağırlıklandırmadan ÖNCE).
    """

    ratio_code: str
    category: str
    weak_multiplier: Decimal
    critical_multiplier: Decimal
    rationale_tr: str


@dataclass(frozen=True)
class RatioContribution:
    """Bölüm 14: bir oranın kategori kırılımındaki tam açıklaması."""

    ratio_code: str
    benchmark_status: str
    tier: "str | None"
    ratio_score: "Decimal | None"
    ratio_weight_applied: Decimal
    tier_fallback_used: bool
    reliability: str
    is_duplicate_excluded: bool


@dataclass(frozen=True)
class CategoryBreakdown:
    """Bölüm 6/14: bir kategorinin uçtan uca hesaplama izi."""

    category: str
    raw_score: "Decimal | None"
    score_after_override: "Decimal | None"
    weight_applied: Decimal
    coverage_ratio: Decimal
    redistributed_weights: "dict[str, Decimal]"
    critical_overrides_applied: "tuple[str, ...]"
    ratio_contributions: "tuple[RatioContribution, ...]"


@dataclass(frozen=True)
class HealthScoreResult:
    """Bölüm 5/14: `compute_financial_health_score()`'un TAM sonucu."""

    status: HealthScoreComputationStatus
    final_score: "Decimal | None"
    pre_hard_fail_score: "Decimal | None"
    letter_rating: "str | None"
    rating_disclaimer_tr: str
    confidence_score: Decimal
    data_coverage_ratio: Decimal
    low_confidence_warning: bool
    provisional: bool
    category_breakdown: "tuple[CategoryBreakdown, ...]"
    hard_fails_triggered: "tuple[str, ...]"
    critical_overrides_applied: "tuple[str, ...]"
    scoreable_ratio_codes: "tuple[str, ...]"
    excluded_duplicate_ratio_codes: "tuple[str, ...]"
    strengths: "tuple[dict[str, Any], ...]"
    weaknesses: "tuple[dict[str, Any], ...]"
    warnings: "tuple[dict[str, Any], ...]"
    health_score_schema_version: str
    health_score_model_version: str
    benchmark_registry_version: str
    ratio_registry_version: str
    category_weight_profile_used: str
