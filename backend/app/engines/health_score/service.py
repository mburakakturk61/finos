"""
Milestone 4.3D (Financial Health Score) -- pipeline implementasyonu.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3D_FINANCIAL_HEALTH_
SCORE_DESIGN.md Bölüm 6 (4. tur, 18 bağlayıcı karar) -- pipeline'ın NİHAİ
sırası: Ratio oku (A) -> Benchmark oku + coverage (B) -> INSUFFICIENT_DATA
kapısı (B.5) -> duplicate filtrele (C) -> oran puanları (D) -> kategori
ham skor (E) -> critical override (F) -> kategori clamp (G) -> kategori
ağırlıklandırma (H) -> hard fail (I) -> final clamp (J) -> rating/
confidence/coverage/explainability (K).

Bu dosya, `app/engines/benchmarks/service.py`'nin (4.3C) AYNI disipliniyle
yazılıyor -- SAF, BAĞIMSIZ bir kütüphane fonksiyonu kümesi, HİÇBİR
`EngineAdapter`/`AnalysisType`/DB kaydına BAĞLI DEĞİL (Bölüm 22 karar
#10). Adım 3-11 boyunca aşama aşama İNŞA EDİLİYOR (TDD -- her aşamanın
kendi testleri tam yeşil olmadan bir sonrakine geçilmiyor).

sqlalchemy/fastapi/pydantic'e SIFIR bağımlı.
"""

import dataclasses
from decimal import Decimal
from typing import Any

from app.engines.common.benchmark_types import (
    BENCHMARK_REGISTRY,
    BenchmarkIdealDirection,
)
from app.engines.common.health_score_registry import (
    CRITICAL_OVERRIDE_RULES,
    HARD_FAIL_RULES,
    RATIO_SCORE_WEIGHTS,
    excluded_duplicate_ratio_codes_for_category,
    resolve_category_weights,
    scoreable_ratio_codes_for_category,
)
from app.engines.common.health_score_types import (
    CONFIDENCE_RELIABILITY_WEIGHT,
    CRITICAL_OVERRIDE_CATEGORY_FLOOR,
    HEALTH_SCORE_MODEL_VERSION,
    HEALTH_SCORE_SCHEMA_VERSION,
    INSUFFICIENT_DATA_COVERAGE_THRESHOLD,
    LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD,
    PROVISIONAL_CONFIDENCE_CEILING,
    STRENGTHS_WEAKNESSES_COUNT,
    TIER_TO_POINTS,
    CategoryBreakdown,
    CategoryWeightProfile,
    HealthScoreComputationStatus,
    HealthScoreResult,
    RatioContribution,
    clamp_score,
    normalize_weights,
)
from app.engines.common.ratio_formulas import RATIO_REGISTRY, json_safe_to_decimal


ENGINE_VERSION = "1.0.0"

# Health Score'un aktif olduğu 6 kategori (Bölüm 8) -- `cash_flow`
# yapısal olarak %0 ağırlıklı, bu listede YOKTUR (Bölüm 22 karar #7).
ACTIVE_CATEGORIES: tuple[str, ...] = (
    "liquidity", "leverage", "profitability", "activity", "efficiency", "growth",
)


# --- Aşama A + B: Ratio + Benchmark sonuçlarını oku ----------------------


def collect_ratio_signals(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
) -> "dict[str, dict[str, Any]]":
    """
    Aşama A (Ratio oku) + Aşama B (Benchmark oku)'nin BİRLEŞİMİ -- her
    `ratio_code` için Ratio Engine'in ham değerini/reliability'sini VE
    Benchmark Engine'in status/tier'ını TEK bir düz (kategoriye göre
    nested OLMAYAN -- ratio_code'lar RATIO_REGISTRY'de global olarak
    tekil olduğu için güvenle düzleştirilir) sözlükte birleştirir.

    `ratio_result_json`/`benchmark_result_json` -- sırasıyla
    `analyze_financial_ratios()`/`evaluate_benchmarks()`'ın DOĞRUDAN
    çıktısı. Bu fonksiyon o yapıları YENİDEN HESAPLAMAZ, yalnızca OKUR.
    """

    signals: "dict[str, dict[str, Any]]" = {}

    for category, category_data in (ratio_result_json.get("categories") or {}).items():
        benchmark_category_data = (
            (benchmark_result_json.get("categories") or {}).get(category) or {}
        )
        benchmark_ratios = benchmark_category_data.get("ratios") or {}

        for ratio_code, ratio_data in (category_data.get("ratios") or {}).items():
            benchmark_data = benchmark_ratios.get(ratio_code) or {}

            signals[ratio_code] = {
                "category": category,
                "ratio_value": json_safe_to_decimal(ratio_data.get("value")),
                "ratio_status": ratio_data.get("status", "not_calculable"),
                "ratio_reliability": ratio_data.get("reliability", "not_calculable"),
                "benchmark_status": benchmark_data.get("status", "benchmark_not_registered"),
                "tier": benchmark_data.get("tier"),
                "benchmark_reliability": benchmark_data.get("reliability", "not_calculable"),
            }

    return signals


# --- Aşama C: Duplicate/derived sinyalleri filtrele ----------------------


def filter_scoreable_signals(
    signals: "dict[str, dict[str, Any]]", category: str
) -> "tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]":
    """
    Bölüm 8.1'in nihai sınıflandırmasıyla (`RATIO_SCORE_WEIGHTS`), verilen
    kategorideki sinyalleri iki gruba ayırır:

    - `scored`: `ratio_weight > 0` -- sayısal skora KATKI VERİR.
    - `excluded`: `ratio_weight == 0` -- yalnızca explainability amaçlı
      görüntülenir, sayısal skora KATKI VERMEZ.

    `signals` -- `collect_ratio_signals()`'ın çıktısı (düz, ratio_code'a
    göre anahtarlanmış). Bu fonksiyon o sözlüğü YENİDEN HESAPLAMAZ.
    """

    scoreable_codes = scoreable_ratio_codes_for_category(category)
    excluded_codes = excluded_duplicate_ratio_codes_for_category(category)

    scored = {
        ratio_code: signal
        for ratio_code, signal in signals.items()
        if ratio_code in scoreable_codes
    }
    excluded = {
        ratio_code: signal
        for ratio_code, signal in signals.items()
        if ratio_code in excluded_codes
    }
    return scored, excluded


# --- Aşama D: Oran puanlarını üret (Bölüm 6.2 -- BAĞLAYICI karar #11) ---
#
# Varsayılan strateji: tier SINIRLARI arasında DOĞRUSAL İNTERPOLASYON.
# `excellent`/`critical` bandının doğal bir "daha da mükemmel/daha da
# kötü" referansı olmadığı için, o uçlarda değer sabit 100/0'da kilitlenir
# (yeni bir "süper-mükemmel" referans noktası İCAT EDİLMEZ). Gerekli iki
# sınır noktası (herhangi bir ANCHOR'ın None olması) mevcut DEĞİLSE
# kontrollü sabit `TIER_TO_POINTS` fallback'ine düşülür -- bu, çağıran
# tarafından `tier_fallback_used=True` ile AÇIKÇA işaretlenmelidir.
#
# Not (Bölüm 4.1, girdi sözleşmesinin derinleşmesi): bu fonksiyonlar
# `BENCHMARK_REGISTRY`'nin `default_thresholds`'ını okur -- 4.3D'de
# industry/company_size override'ları GERÇEKTE hâlâ BOŞ olduğu için
# (4.3C, Bölüm 22 karar #12) bu her zaman fiilen "resolved" sınırla
# AYNIDIR. Override'lar ileride doldurulursa, bu fonksiyonun da resolved
# thresholds'u kullanacak şekilde güncellenmesi GEREKECEKTİR -- bilinen,
# kayıtlı bir sınırlama (bkz. Bölüm 22 karar #12).


def _interpolate_between(
    value: Decimal, lo_v: Decimal, lo_p: Decimal, hi_v: Decimal, hi_p: Decimal
) -> Decimal:
    fraction = (value - lo_v) / (hi_v - lo_v)
    return lo_p + fraction * (hi_p - lo_p)


def _continuous_points_higher_is_better(
    value: Decimal, critical: "Decimal | None", weak: "Decimal | None",
    average: "Decimal | None", good: "Decimal | None",
) -> "Decimal | None":
    if None in (critical, weak, average, good):
        return None
    if value < critical:
        return TIER_TO_POINTS["critical"]
    if value >= good:
        return TIER_TO_POINTS["excellent"]
    anchors = [
        (critical, TIER_TO_POINTS["critical"]), (weak, TIER_TO_POINTS["weak"]),
        (average, TIER_TO_POINTS["average"]), (good, TIER_TO_POINTS["good"]),
    ]
    for (lo_v, lo_p), (hi_v, hi_p) in zip(anchors, anchors[1:]):
        if lo_v <= value < hi_v:
            return _interpolate_between(value, lo_v, lo_p, hi_v, hi_p)
    return None  # kurami geregi ulasilmamali -- guvenlik fallback


def _continuous_points_lower_is_better(
    value: Decimal, critical: "Decimal | None", weak: "Decimal | None",
    average: "Decimal | None", good: "Decimal | None",
) -> "Decimal | None":
    if None in (critical, weak, average, good):
        return None
    if value > critical:
        return TIER_TO_POINTS["critical"]
    if value <= good:
        return TIER_TO_POINTS["excellent"]
    # Değerler AZALAN kalite yönünde ARTAR (good < average < weak < critical)
    # -- artan değer sırasıyla ilerleyip fraction=(value-lo_v)/(hi_v-lo_v)
    # ile lo_p'den hi_p'ye (AZALAN puan) interpolasyon yapılır.
    anchors = [
        (good, TIER_TO_POINTS["good"]), (average, TIER_TO_POINTS["average"]),
        (weak, TIER_TO_POINTS["weak"]), (critical, TIER_TO_POINTS["critical"]),
    ]
    for (lo_v, lo_p), (hi_v, hi_p) in zip(anchors, anchors[1:]):
        if lo_v < value <= hi_v:
            return _interpolate_between(value, lo_v, lo_p, hi_v, hi_p)
    return None  # kurami geregi ulasilmamali -- guvenlik fallback


def _in_band(value: Decimal, band: "tuple[Decimal, Decimal] | None") -> bool:
    if band is None:
        return False
    lo, hi = band
    return lo <= value <= hi


def _continuous_points_range_is_better(
    value: Decimal,
    excellent: "tuple[Decimal, Decimal] | None",
    good: "tuple[Decimal, Decimal] | None",
    average: "tuple[Decimal, Decimal] | None",
    weak: "tuple[Decimal, Decimal] | None",
) -> "Decimal | None":
    if None in (excellent, good, average, weak):
        return None
    if _in_band(value, excellent):
        return TIER_TO_POINTS["excellent"]
    if not _in_band(value, weak):
        return TIER_TO_POINTS["critical"]

    # İç içe geçmiş bantlar -- KÖTÜden İYİye sıra: weak -> average -> good
    # -> excellent. Değer, "dış" bandın İÇİNDE ama "iç" bandın DIŞINDAYSA,
    # o iki bandın kabuğu (shell) içindeki konumuna göre interpolasyon
    # yapılır (düşük taraf VEYA yüksek taraf -- hangisine yakınsa).
    ordered_worst_to_best = [
        (weak, TIER_TO_POINTS["weak"]), (average, TIER_TO_POINTS["average"]),
        (good, TIER_TO_POINTS["good"]), (excellent, TIER_TO_POINTS["excellent"]),
    ]
    for (outer_band, outer_points), (inner_band, inner_points) in zip(
        ordered_worst_to_best, ordered_worst_to_best[1:]
    ):
        if _in_band(value, outer_band) and not _in_band(value, inner_band):
            outer_lo, outer_hi = outer_band
            inner_lo, inner_hi = inner_band
            if value < inner_lo:
                fraction = (value - outer_lo) / (inner_lo - outer_lo)
            else:
                fraction = (outer_hi - value) / (outer_hi - inner_hi)
            return outer_points + fraction * (inner_points - outer_points)
    return None  # kurami geregi ulasilmamali -- guvenlik fallback


def compute_ratio_score(ratio_code: str, signal: "dict[str, Any]") -> "tuple[Decimal | None, bool]":
    """
    Bölüm 6.2: bir oranın `ratio_score`'unu (0-100, sürekli interpolasyon)
    üretir. Dönüş: `(points, tier_fallback_used)`.

    Yalnızca `benchmark_status == "evaluated"` (değer VE tier mevcut) iken
    anlamlıdır -- aksi halde `(None, False)` döner (fabrike bir puan
    üretilmez, çağıran zaten EVALUATED olmayanları filtrelemiş olmalı).
    """

    if signal.get("benchmark_status") != "evaluated" or signal.get("ratio_value") is None:
        return None, False

    metadata = BENCHMARK_REGISTRY.get(ratio_code)
    if metadata is None:
        return None, False

    value = signal["ratio_value"]
    thresholds = metadata.default_thresholds
    tier = signal.get("tier")

    if metadata.ideal_direction == BenchmarkIdealDirection.HIGHER_IS_BETTER:
        points = _continuous_points_higher_is_better(
            value, thresholds.critical, thresholds.weak, thresholds.average, thresholds.good
        )
    elif metadata.ideal_direction == BenchmarkIdealDirection.LOWER_IS_BETTER:
        points = _continuous_points_lower_is_better(
            value, thresholds.critical, thresholds.weak, thresholds.average, thresholds.good
        )
    else:
        points = _continuous_points_range_is_better(
            value, thresholds.excellent, thresholds.good, thresholds.average, thresholds.weak
        )

    if points is not None:
        return points, False

    # Fallback: iki sınır noktası eksik/yetersiz -- kontrollü sabit tier
    # puanına düşülür, Explainability'de `tier_fallback_used=True` ile
    # AÇIKÇA işaretlenir (Bölüm 6.2, karar #11).
    if tier is not None and tier in TIER_TO_POINTS:
        return TIER_TO_POINTS[tier], True
    return None, True


# --- Aşama E: Kategori ham skorlarını üret (Bölüm 6/8/9) -----------------


def registry_ratio_weights_for_category(category: str) -> "dict[str, Decimal]":
    """
    Bir kategorideki scored (`ratio_weight>0`) oranların, registry'de
    kayıtlı HAM (redistribute EDİLMEMİŞ) ağırlıkları. Tam coverage
    (kategorideki TÜM scored oranlar EVALUATED) durumunda bu, doğrudan
    kullanılacak etkin ağırlıktır -- eksik veri varsa Adım 6'nın (Bölüm 9)
    yeniden dağıtımı bu sözlüğü GÜNCEL bir sürümle DEĞİŞTİRİR (bkz.
    `redistribute_category_weights`).
    """

    return {
        code: w.ratio_weight
        for code, w in RATIO_SCORE_WEIGHTS.items()
        if w.category == category and w.ratio_weight > 0
    }


def build_category_breakdown(
    category: str,
    scored_signals: "dict[str, dict[str, Any]]",
    excluded_signals: "dict[str, dict[str, Any]]",
    ratio_weights: "dict[str, Decimal]",
    *,
    category_weight: Decimal = Decimal("0"),
    critical_overrides_applied: "tuple[str, ...]" = (),
) -> CategoryBreakdown:
    """
    Aşama E: bir kategorinin `raw_score`'unu ve TAM `RatioContribution`
    kırılımını üretir.

    `ratio_weights` -- bu kategorideki scored oranlar için KULLANILACAK
    etkin ağırlıklar (Adım 5'te doğrudan `registry_ratio_weights_for_
    category()`'nin çıktısı verilebilir -- tam coverage varsayımıyla; Adım
    6'dan sonra bunun yerine `redistribute_category_weights()`'in çıktısı
    verilir). Yalnızca `benchmark_status == "evaluated"` olan scored
    oranlar ağırlıklı ortalamaya KATKI VERİR -- sıfır EVALUATED oran varsa
    `raw_score=None` kalır (asla fabrike edilmez).

    `category_weight`/`critical_overrides_applied` -- pipeline'ın SONRAKİ
    aşamalarında (Aşama F/H) doldurulacak alanlar; bu fonksiyon yalnızca
    KENDİ sorumluluğu olan `raw_score`/`ratio_contributions`/`coverage_
    ratio` alanlarını üretir, çağıran (orkestrasyon) bu iki alanı
    GEREKTİĞİNDE günceller.
    """

    contributions: "list[RatioContribution]" = []
    weighted_sum = Decimal("0")
    weight_sum = Decimal("0")
    evaluated_count = 0

    for ratio_code, signal in scored_signals.items():
        points, fallback_used = compute_ratio_score(ratio_code, signal)
        weight = ratio_weights.get(ratio_code, Decimal("0"))
        is_evaluated = signal.get("benchmark_status") == "evaluated" and points is not None

        contributions.append(
            RatioContribution(
                ratio_code=ratio_code,
                benchmark_status=signal.get("benchmark_status", "benchmark_not_registered"),
                tier=signal.get("tier"),
                ratio_score=points,
                ratio_weight_applied=weight if is_evaluated else Decimal("0"),
                tier_fallback_used=fallback_used,
                reliability=signal.get("benchmark_reliability", "not_calculable"),
                is_duplicate_excluded=False,
            )
        )

        if is_evaluated:
            weighted_sum += points * weight
            weight_sum += weight
            evaluated_count += 1

    for ratio_code, signal in excluded_signals.items():
        contributions.append(
            RatioContribution(
                ratio_code=ratio_code,
                benchmark_status=signal.get("benchmark_status", "benchmark_not_registered"),
                tier=signal.get("tier"),
                ratio_score=None,
                ratio_weight_applied=Decimal("0"),
                tier_fallback_used=False,
                reliability=signal.get("benchmark_reliability", "not_calculable"),
                is_duplicate_excluded=True,
            )
        )

    raw_score = clamp_score(weighted_sum / weight_sum) if weight_sum > 0 else None
    total_scoreable = len(scored_signals)
    coverage_ratio = (
        (Decimal(evaluated_count) / Decimal(total_scoreable))
        if total_scoreable > 0
        else Decimal("0")
    )

    return CategoryBreakdown(
        category=category,
        raw_score=raw_score,
        score_after_override=None,
        weight_applied=category_weight,
        coverage_ratio=coverage_ratio,
        redistributed_weights=dict(ratio_weights),
        critical_overrides_applied=critical_overrides_applied,
        ratio_contributions=tuple(contributions),
    )


# --- Bölüm 9/11: Coverage normalization (Adım 6) --------------------------


def redistribute_category_weights(
    category: str, scored_signals: "dict[str, dict[str, Any]]"
) -> "dict[str, Decimal]":
    """
    Bölüm 9 (kategori-içi yeniden ağırlıklandırma, 1. seviye): bir
    kategorideki EVALUATED olmayan (missing/not_calculable) scored
    oranların registry ağırlığı, EVALUATED olanlar arasında ORANTILI
    olarak yeniden dağıtılır -- `normalize_weights` yalnızca `> 0` ham
    ağırlıkları (burada: SADECE evaluated olanların registry ağırlığı)
    dikkate alarak toplamı tam `1`'e tamamlar.

    Sıfır EVALUATED oran varsa TÜM ağırlıklar `0` döner (`normalize_
    weights`'in "sessizce sıfır döndür" davranışı) -- bu, `build_category_
    breakdown`'ın `raw_score=None` üretmesiyle DOĞRU şekilde sonuçlanır.
    """

    registry_weights = registry_ratio_weights_for_category(category)
    raw_for_redistribution = {
        ratio_code: (
            registry_weights.get(ratio_code, Decimal("0"))
            if scored_signals.get(ratio_code, {}).get("benchmark_status") == "evaluated"
            else Decimal("0")
        )
        for ratio_code in registry_weights
    }
    return normalize_weights(raw_for_redistribution)


def compute_overall_data_coverage_ratio(
    all_scored_signals: "dict[str, dict[str, dict[str, Any]]]",
) -> Decimal:
    """
    Bölüm 11: `data_coverage_ratio = (toplam EVALUATED scored oran) /
    scoreable_ratio_count` -- TÜM aktif kategoriler ÜZERİNDEN, sabit sayı
    KULLANMADAN (Bölüm 0.1).

    `all_scored_signals` -- `{category: scored_signals_dict}` şeklinde,
    her aktif kategori için `filter_scoreable_signals()`'ın `scored`
    çıktısı.
    """

    total_scoreable = 0
    total_evaluated = 0
    for scored_signals in all_scored_signals.values():
        total_scoreable += len(scored_signals)
        total_evaluated += sum(
            1 for s in scored_signals.values() if s.get("benchmark_status") == "evaluated"
        )
    if total_scoreable == 0:
        return Decimal("0")
    return Decimal(total_evaluated) / Decimal(total_scoreable)


def determine_insufficient_data_and_warning(
    data_coverage_ratio: Decimal,
) -> "tuple[bool, bool]":
    """
    Bölüm 9/11 (Bölüm 22 karar #15): üç bantlı coverage davranışı.

    Dönüş: `(is_insufficient_data, low_confidence_warning)`.
    - `< 0.50`         -> (True, False)  -- skor HİÇ üretilmez.
    - `[0.50, 0.70)`   -> (False, True)  -- skor üretilir, zorunlu uyarı.
    - `>= 0.70`        -> (False, False) -- normal.
    """

    if data_coverage_ratio < INSUFFICIENT_DATA_COVERAGE_THRESHOLD:
        return True, False
    if data_coverage_ratio < LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD:
        return False, True
    return False, False


def resolve_cross_category_weights(
    category_breakdowns: "dict[str, CategoryBreakdown]",
    category_weight_profile: CategoryWeightProfile,
) -> "dict[str, Decimal]":
    """
    Bölüm 9 (kategoriler arası yeniden ağırlıklandırma, 2. seviye) + Aşama
    H (Bölüm 6): `score_after_override=None` (ki bu yalnızca `raw_score=
    None` iken mümkündür -- sıfır EVALUATED oran) olan kategoriler
    kategoriler arası ağırlıklandırmadan ÇIKARILIR, kalan AKTİF
    kategorilerin `CategoryWeightProfile.category_weights`'i KENDİ
    ARALARINDA yeniden normalize edilir.

    Bu fonksiyon `score_after_override` HENÜZ hesaplanmamışken de
    (Adım 6 aşamasında, critical override'dan ÖNCE) güvenle kullanılabilir
    -- `raw_score is None` kontrolü yeterlidir, çünkü `score_after_
    override`, `raw_score=None` olan bir kategoride HER ZAMAN `None`
    kalacaktır (Aşama F, Bölüm 6).
    """

    raw_for_redistribution = {
        category: (
            category_weight_profile.category_weights.get(category, Decimal("0"))
            if breakdown.raw_score is not None
            else Decimal("0")
        )
        for category, breakdown in category_breakdowns.items()
    }
    return normalize_weights(raw_for_redistribution)


# --- Aşama F: Critical Override (Bölüm 13, Bölüm 22 karar #10) -----------


def apply_critical_override(
    category: str,
    raw_score: "Decimal | None",
    signals: "dict[str, dict[str, Any]]",
) -> "tuple[Decimal | None, tuple[str, ...]]":
    """
    Aşama F: oransal critical-override çarpanını KATEGORİNİN KENDİ ham
    skoruna uygular -- kategoriler arası ağırlıklandırmadan (Aşama H)
    ÖNCE (2. tur incelemenin bulduğu sıralama hatasının KESİN çözümü).

    `raw_score=None` iken hiçbir şey yapılamaz (var olmayan bir skora
    override uygulanamaz) -- `(None, ())` döner.

    Aynı kategoride birden fazla `CRITICAL_OVERRIDE_RULES` kuralı
    tetiklenirse çarpanlar ÇARPILIR, ama sonuç `CRITICAL_OVERRIDE_
    CATEGORY_FLOOR`'un ALTINA düşürülMEZ. Sonuç HER ZAMAN `[0,100]`
    aralığına clamp edilir (Aşama G, burada da uygulanır -- tek, paylaşılan
    `clamp_score`).

    `signals` -- `collect_ratio_signals()`'ın çıktısı (düz, TÜM ratio_
    code'ları içerir) -- critical-override kuralları yalnızca scored
    oranlara bağlı olduğu için (registry kayıt-anı doğrulaması, Bölüm 13)
    ayrıca bir `scored`/`excluded` ayrımı GEREKMEZ.
    """

    if raw_score is None:
        return None, ()

    triggered: "list[str]" = []
    combined_multiplier = Decimal("1")

    for rule in CRITICAL_OVERRIDE_RULES:
        if rule.category != category:
            continue
        signal = signals.get(rule.ratio_code)
        if signal is None:
            continue
        tier = signal.get("tier")
        if tier == "critical":
            combined_multiplier *= rule.critical_multiplier
            triggered.append(f"{rule.ratio_code}:critical")
        elif tier == "weak":
            combined_multiplier *= rule.weak_multiplier
            triggered.append(f"{rule.ratio_code}:weak")

    if not triggered:
        return clamp_score(raw_score), ()

    combined_multiplier = max(combined_multiplier, CRITICAL_OVERRIDE_CATEGORY_FLOOR)
    return clamp_score(raw_score * combined_multiplier), tuple(triggered)


# --- Aşama I: Hard Fail (Bölüm 12) ----------------------------------------


def apply_hard_fail_rules(
    preliminary_score: "Decimal | None",
    signals: "dict[str, dict[str, Any]]",
) -> "tuple[Decimal | None, tuple[str, ...]]":
    """
    Aşama I: `HARD_FAIL_RULES`'taki HER kural değerlendirilir (Bölüm 4.1'in
    genişletilmiş girdi sözleşmesiyle -- predicate'ler hem ham `ratio`
    değerlerini hem `benchmark` tier/status'unu okuyabilir). Herhangi biri
    tetiklenirse, TÜM tetiklenen kuralların `score_ceiling`'leri arasından
    EN DÜŞÜK olanı (en katı tavan) `preliminary_score` ile `min()`
    alınarak uygulanır -- `pre_hard_fail_score`'un (Aşama H çıktısı,
    burada `preliminary_score` parametresi) KENDİSİ bu fonksiyonun
    DIŞINDA, orkestrasyon tarafından AYRICA saklanır (şeffaflık, Bölüm
    12).

    Eksik veri (`ratios.get(code) is None`) HER ZAMAN `False` predicate
    sonucu üretir -- eksik veri hard-fail olarak YORUMLANMAZ (Bölüm
    11/12).

    `preliminary_score=None` iken hiçbir şey yapılamaz -- `(None, ())`.
    """

    if preliminary_score is None:
        return None, ()

    ratios = {code: signal.get("ratio_value") for code, signal in signals.items()}
    benchmarks = {
        code: {"tier": signal.get("tier"), "status": signal.get("benchmark_status")}
        for code, signal in signals.items()
    }

    triggered: "list[str]" = []
    ceilings: "list[Decimal]" = []
    for rule in HARD_FAIL_RULES:
        if rule.predicate(ratios, benchmarks):
            triggered.append(rule.rule_code)
            ceilings.append(rule.score_ceiling)

    if not triggered:
        return preliminary_score, ()

    final_score = min([preliminary_score, *ceilings])
    return clamp_score(final_score), tuple(triggered)


# --- Bölüm 10: Confidence modeli (Adım 9) ---------------------------------


def weighted_reliabilities_for_category(
    breakdown: CategoryBreakdown, category_weight: Decimal
) -> "list[tuple[str, Decimal]]":
    """
    Bir `CategoryBreakdown`'ın EVALUATED (`ratio_score is not None`,
    `is_duplicate_excluded=False`) katkılarından, confidence hesaplaması
    için `(reliability, etkin_ağırlık)` çiftleri üretir. `etkin_ağırlık
    = ratio_weight_applied * category_weight` -- kategori-içi VE
    kategoriler-arası ağırlıkların BİRLEŞİMİ, tek bir GLOBAL ölçekte.
    """

    return [
        (contribution.reliability, contribution.ratio_weight_applied * category_weight)
        for contribution in breakdown.ratio_contributions
        if not contribution.is_duplicate_excluded and contribution.ratio_score is not None
    ]


def compute_confidence_score(
    weighted_reliabilities: "list[tuple[str, Decimal]]",
) -> Decimal:
    """
    Bölüm 10: `confidence_score = min(weighted_average(reliability_
    weight), PROVISIONAL_CONFIDENCE_CEILING)`.

    `weighted_reliabilities` -- `[(reliability_str, etkin_ağırlık), ...]`
    (bkz. `weighted_reliabilities_for_category`, orkestrasyon TÜM
    kategorilerden gelen listeleri birleştirir). Boş girdide (hiçbir
    EVALUATED oran yok -- ör. INSUFFICIENT_DATA durumu) `0` döner --
    fabrike bir güven değeri ÜRETİLMEZ.
    """

    if not weighted_reliabilities:
        return Decimal("0")

    weighted_sum = Decimal("0")
    total_weight = Decimal("0")
    for reliability, weight in weighted_reliabilities:
        rank = CONFIDENCE_RELIABILITY_WEIGHT.get(reliability, Decimal("0"))
        weighted_sum += rank * weight
        total_weight += weight

    if total_weight <= 0:
        return Decimal("0")

    raw_confidence = weighted_sum / total_weight
    return min(raw_confidence, PROVISIONAL_CONFIDENCE_CEILING)


# --- Bölüm 16: Rating harf sistemi (Adım 10) ------------------------------

RATING_DISCLAIMER_TR = (
    "Bu sınıflandırma platformun içsel, heuristik bir göstergesidir -- "
    "resmî bir kredi derecelendirmesi DEĞİLDİR."
)

# Sıra ÖNEMLİ: yüksekten düşüğe, ilk uyan bant kullanılır (Bölüm 16).
_RATING_BANDS: "tuple[tuple[Decimal, str], ...]" = (
    (Decimal("85"), "Çok Güçlü"),
    (Decimal("70"), "Güçlü"),
    (Decimal("55"), "Sağlıklı"),
    (Decimal("40"), "İzlenmeli"),
    (Decimal("25"), "Zayıf"),
    (Decimal("0"), "Kritik"),
)


def determine_letter_rating(final_score: "Decimal | None") -> "str | None":
    """
    Bölüm 16 (Bölüm 22 karar #2 ile KİLİTLENDİ): 6 kademeli Türkçe skala.
    `final_score=None` (ör. `INSUFFICIENT_DATA`) iken `None` döner --
    fabrike bir derece ÜRETİLMEZ.
    """

    if final_score is None:
        return None
    for threshold, label in _RATING_BANDS:
        if final_score >= threshold:
            return label
    return _RATING_BANDS[-1][1]  # kurami geregi ulasilmamali (0 zaten en alt bant)


# --- Bölüm 15: Strengths / Weaknesses üretimi (Adım 10) -------------------

_TIER_RANK: "dict[str, int]" = {
    "excellent": 4, "good": 3, "average": 2, "weak": 1, "critical": 0,
}


def _format_ratio_value_tr(value: "Decimal | None", unit: "str | None") -> str:
    if value is None:
        return "n/a"
    if unit == "percentage":
        return f"%{value}"
    if unit == "days":
        return f"{value} gün"
    return str(value)


def generate_strengths_weaknesses(
    category_breakdowns: "dict[str, CategoryBreakdown]",
    all_signals: "dict[str, dict[str, Any]]",
    *,
    count: int = STRENGTHS_WEAKNESSES_COUNT,
) -> "tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]":
    """
    Bölüm 15: aday havuzu yalnızca EVALUATED, scored (duplicate OLMAYAN)
    oranlardır -- `(tier_rank, |points-50|-benzeri sıralama)` ile
    sıralanır, ilk `count` tanesi strengths/weaknesses olur. Deterministik
    Türkçe string template'ler, `ratio_code` alfabetik tie-break.
    """

    candidates: "list[tuple[str, RatioContribution]]" = []
    for category, breakdown in category_breakdowns.items():
        for contribution in breakdown.ratio_contributions:
            if contribution.is_duplicate_excluded or contribution.ratio_score is None:
                continue
            candidates.append((category, contribution))

    def _entry(category: str, contribution: RatioContribution) -> "dict[str, Any]":
        ratio_metadata = RATIO_REGISTRY.get(contribution.ratio_code)
        display_name = ratio_metadata.display_name_tr if ratio_metadata else contribution.ratio_code
        unit = ratio_metadata.unit if ratio_metadata else None
        signal = all_signals.get(contribution.ratio_code, {})
        value_text = _format_ratio_value_tr(signal.get("ratio_value"), unit)
        return {
            "ratio_code": contribution.ratio_code,
            "category": category,
            "tier": contribution.tier,
            "ratio_score": contribution.ratio_score,
            "display_name_tr": display_name,
            "text_tr": f"{display_name} '{contribution.tier}' seviyesinde ({value_text}).",
        }

    strengths_sorted = sorted(
        candidates,
        key=lambda pair: (
            -_TIER_RANK.get(pair[1].tier, 0), -pair[1].ratio_score, pair[1].ratio_code,
        ),
    )
    weaknesses_sorted = sorted(
        candidates,
        key=lambda pair: (
            _TIER_RANK.get(pair[1].tier, 0), pair[1].ratio_score, pair[1].ratio_code,
        ),
    )

    strengths = tuple(_entry(category, contribution) for category, contribution in strengths_sorted[:count])
    weaknesses = tuple(_entry(category, contribution) for category, contribution in weaknesses_sorted[:count])
    return strengths, weaknesses


# --- Explainability: uyarıların birleştirilmesi (Adım 10) -----------------


def collect_all_warnings(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    *,
    extra_warnings: "tuple[dict[str, Any], ...]" = (),
) -> "tuple[dict[str, Any], ...]":
    """
    Bölüm 14: `warnings`, Ratio Engine + Benchmark Engine + Health
    Score'un KENDİ (ör. `low_confidence_warning`) uyarılarının
    BİRLEŞİMİDİR.
    """

    warnings: "list[dict[str, Any]]" = list(ratio_result_json.get("warnings") or [])
    for category_data in (benchmark_result_json.get("categories") or {}).values():
        for ratio_data in (category_data.get("ratios") or {}).values():
            warnings.extend(ratio_data.get("warnings") or [])
    warnings.extend(extra_warnings)
    return tuple(warnings)


# --- Adım 11: Service orchestration -- compute_financial_health_score() --


def compute_financial_health_score(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
    tenant_id: "str | None" = None,
) -> HealthScoreResult:
    """
    Bölüm 6'nın TAM pipeline'ı (Aşama A-K) -- saf, bağımsız bir kütüphane
    fonksiyonu (Bölüm 22 karar #10, HİÇBİR `EngineAdapter`/`AnalysisType`/
    DB kaydına bağlı DEĞİL). Girdiler `analyze_financial_ratios()` ve
    `evaluate_benchmarks()`'ın DOĞRUDAN çıktısıdır -- hiçbir oran YENİDEN
    HESAPLANMAZ.

    `industry_code`/`company_size_bucket`/`tenant_id` -- Bölüm 8.2'nin
    çözümleme sırası için (4.3D'de yalnızca `global` profili DOLU
    olduğundan, bu üçü de PRATİKTE her zaman `global`'a düşer -- Bölüm
    22 karar #17).
    """

    signals = collect_ratio_signals(ratio_result_json, benchmark_result_json)

    all_scored: "dict[str, dict[str, dict[str, Any]]]" = {}
    all_excluded: "dict[str, dict[str, dict[str, Any]]]" = {}
    for category in ACTIVE_CATEGORIES:
        scored, excluded = filter_scoreable_signals(signals, category)
        all_scored[category] = scored
        all_excluded[category] = excluded

    data_coverage_ratio = compute_overall_data_coverage_ratio(all_scored)
    is_insufficient, low_confidence_warning = determine_insufficient_data_and_warning(
        data_coverage_ratio
    )

    profile = resolve_category_weights(
        industry_code=industry_code,
        company_size_bucket=company_size_bucket,
        tenant_id=tenant_id,
    )
    profile_label = (
        profile.scope if profile.scope_key is None else f"{profile.scope}:{profile.scope_key}"
    )

    ratio_registry_version = ratio_result_json.get("ratio_registry_version") or ""
    benchmark_registry_version = benchmark_result_json.get("benchmark_registry_version") or ""

    scoreable_ratio_codes = tuple(
        code for category in ACTIVE_CATEGORIES for code in all_scored[category]
    )
    excluded_duplicate_ratio_codes = tuple(
        code for category in ACTIVE_CATEGORIES for code in all_excluded[category]
    )

    # Aşama C-E: her kategori için ham skor -- Bölüm 9/Adım 6'nın
    # redistribute edilmiş ağırlıklarıyla.
    category_breakdowns: "dict[str, CategoryBreakdown]" = {}
    for category in ACTIVE_CATEGORIES:
        redistributed = redistribute_category_weights(category, all_scored[category])
        category_breakdowns[category] = build_category_breakdown(
            category, all_scored[category], all_excluded[category], redistributed,
        )

    if is_insufficient:
        # Aşama B.5: pipeline BURADA DURUR -- Aşama F-J HİÇ ÇALIŞMAZ.
        # Kategori kırılımları (Aşama B/C/D/E'nin teşhis bilgisi) YİNE DE
        # döner (şeffaflık -- "neden skor üretilmedi" sorusuna cevap
        # verir); yalnızca NİHAİ, tek bir toplu skor FABRİKE EDİLMEZ.
        warnings = collect_all_warnings(
            ratio_result_json,
            benchmark_result_json,
            extra_warnings=(
                {
                    "code": "INSUFFICIENT_DATA",
                    "severity": "high",
                    "message": (
                        "Veri kapsamı yetersiz "
                        f"(coverage={data_coverage_ratio}) -- Financial Health "
                        "Score üretilmedi."
                    ),
                },
            ),
        )
        return HealthScoreResult(
            status=HealthScoreComputationStatus.INSUFFICIENT_DATA,
            final_score=None,
            pre_hard_fail_score=None,
            letter_rating=None,
            rating_disclaimer_tr=RATING_DISCLAIMER_TR,
            confidence_score=Decimal("0"),
            data_coverage_ratio=data_coverage_ratio,
            low_confidence_warning=False,
            provisional=True,
            category_breakdown=tuple(category_breakdowns[c] for c in ACTIVE_CATEGORIES),
            hard_fails_triggered=(),
            critical_overrides_applied=(),
            scoreable_ratio_codes=scoreable_ratio_codes,
            excluded_duplicate_ratio_codes=excluded_duplicate_ratio_codes,
            strengths=(),
            weaknesses=(),
            warnings=warnings,
            health_score_schema_version=HEALTH_SCORE_SCHEMA_VERSION,
            health_score_model_version=HEALTH_SCORE_MODEL_VERSION,
            benchmark_registry_version=benchmark_registry_version,
            ratio_registry_version=ratio_registry_version,
            category_weight_profile_used=profile_label,
        )

    # Aşama F/G: critical override, KATEGORİNİN KENDİ ham skoruna --
    # kategoriler arası ağırlıklandırmadan ÖNCE (2. tur incelemenin
    # bulduğu sıralama hatasının KESİN çözümü).
    overridden_breakdowns: "dict[str, CategoryBreakdown]" = {}
    all_critical_overrides: "list[str]" = []
    for category in ACTIVE_CATEGORIES:
        breakdown = category_breakdowns[category]
        score_after_override, triggered = apply_critical_override(
            category, breakdown.raw_score, signals,
        )
        overridden_breakdowns[category] = dataclasses.replace(
            breakdown,
            score_after_override=score_after_override,
            critical_overrides_applied=triggered,
        )
        all_critical_overrides.extend(triggered)

    # Aşama H: kategoriler arası ağırlıklandırma (Bölüm 9, 2. seviye
    # yeniden dağıtım -- tamamen eksik kategoriler dışlanır).
    resolved_weights = resolve_cross_category_weights(overridden_breakdowns, profile)
    final_breakdowns: "dict[str, CategoryBreakdown]" = {}
    weighted_sum = Decimal("0")
    any_category_scored = False
    for category in ACTIVE_CATEGORIES:
        breakdown = overridden_breakdowns[category]
        weight = resolved_weights.get(category, Decimal("0"))
        final_breakdowns[category] = dataclasses.replace(breakdown, weight_applied=weight)
        if breakdown.score_after_override is not None:
            weighted_sum += breakdown.score_after_override * weight
            any_category_scored = True

    preliminary_score = clamp_score(weighted_sum) if any_category_scored else None

    # Aşama I/J: hard fail + final clamp.
    final_score, hard_fails_triggered = apply_hard_fail_rules(preliminary_score, signals)
    pre_hard_fail_score = preliminary_score

    # Aşama K: confidence/coverage/explainability.
    weighted_reliabilities: "list[tuple[str, Decimal]]" = []
    for category in ACTIVE_CATEGORIES:
        breakdown = final_breakdowns[category]
        weighted_reliabilities.extend(
            weighted_reliabilities_for_category(breakdown, breakdown.weight_applied)
        )
    confidence_score = compute_confidence_score(weighted_reliabilities)

    letter_rating = determine_letter_rating(final_score)
    strengths, weaknesses = generate_strengths_weaknesses(final_breakdowns, signals)

    extra_warnings: "list[dict[str, Any]]" = []
    if low_confidence_warning:
        extra_warnings.append(
            {
                "code": "LOW_CONFIDENCE_COVERAGE",
                "severity": "medium",
                "message": (
                    "Veri kapsamı %50-%70 bandında "
                    f"(coverage={data_coverage_ratio}) -- skor üretildi ancak "
                    "düşük güven uyarısı geçerlidir."
                ),
            }
        )
    for breakdown in final_breakdowns.values():
        for contribution in breakdown.ratio_contributions:
            if contribution.tier_fallback_used:
                extra_warnings.append(
                    {
                        "code": "TIER_INTERPOLATION_FALLBACK",
                        "severity": "low",
                        "message": (
                            f"'{contribution.ratio_code}' için sürekli "
                            "interpolasyon yapılamadı, kontrollü sabit tier "
                            "puanına (fallback) düşüldü."
                        ),
                    }
                )

    warnings = collect_all_warnings(
        ratio_result_json, benchmark_result_json, extra_warnings=tuple(extra_warnings)
    )

    status = (
        HealthScoreComputationStatus.HARD_FAIL_CAPPED
        if hard_fails_triggered
        else HealthScoreComputationStatus.COMPUTED
    )

    return HealthScoreResult(
        status=status,
        final_score=final_score,
        pre_hard_fail_score=pre_hard_fail_score,
        letter_rating=letter_rating,
        rating_disclaimer_tr=RATING_DISCLAIMER_TR,
        confidence_score=confidence_score,
        data_coverage_ratio=data_coverage_ratio,
        low_confidence_warning=low_confidence_warning,
        provisional=True,
        category_breakdown=tuple(final_breakdowns[c] for c in ACTIVE_CATEGORIES),
        hard_fails_triggered=hard_fails_triggered,
        critical_overrides_applied=tuple(all_critical_overrides),
        scoreable_ratio_codes=scoreable_ratio_codes,
        excluded_duplicate_ratio_codes=excluded_duplicate_ratio_codes,
        strengths=strengths,
        weaknesses=weaknesses,
        warnings=warnings,
        health_score_schema_version=HEALTH_SCORE_SCHEMA_VERSION,
        health_score_model_version=HEALTH_SCORE_MODEL_VERSION,
        benchmark_registry_version=benchmark_registry_version,
        ratio_registry_version=ratio_registry_version,
        category_weight_profile_used=profile_label,
    )
