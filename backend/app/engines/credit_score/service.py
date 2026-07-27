"""
Milestone 4.3E (Credit Score Engine) -- pipeline implementasyonu.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3E_CREDIT_SCORE_
ENGINE_DESIGN.md (2. tur, 15 bağlayıcı karar -- Bölüm 26 "Onaylanmış
Kararlar") + implementasyon direktifinin 14 "kesin ve değiştirilemez"
kuralı.

**Paylaşılan kod (implementasyon kuralı #12):** sinyal toplama
(`collect_ratio_signals`) VE tier-interpolasyon/oran-puanlama
(`compute_ratio_score` ve iç yardımcıları) `app.engines.health_score.
service`'ten DOĞRUDAN import edilip YENİDEN KULLANILIR -- bu fonksiyonlar
YALNIZCA `BENCHMARK_REGISTRY`'nin (evrensel, Credit Score'a ÖZGÜ
OLMAYAN) eşik metadatasını okur; Health Score'un 7-kategorili
taksonomisine BAĞIMLI DEĞİLDİR. Aynı matematiğin ikinci bir kopyası
BURADA YAZILMAZ.

Bu dosya Adım 4-11 boyunca aşama aşama İNŞA EDİLİYOR (TDD -- her
aşamanın kendi testleri tam yeşil olmadan bir sonrakine geçilmiyor).

sqlalchemy/fastapi/pydantic'e SIFIR bağımlı.
"""

import dataclasses
from decimal import Decimal
from typing import Any

from app.engines.common.credit_score_registry import (
    CREDIT_BANKING_LENS_SIGNAL_RULES,
    CREDIT_CRITICAL_OVERRIDE_RULES,
    CREDIT_HARD_FAIL_RULES,
    CREDIT_RATIO_SCORE_WEIGHTS,
    excluded_duplicate_ratio_codes_for_category,
    resolve_credit_category_weights,
    scoreable_ratio_codes_for_category,
)
from app.engines.common.credit_score_types import (
    CONFIDENCE_RELIABILITY_WEIGHT,
    CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR,
    CREDIT_INSUFFICIENT_DATA_COVERAGE_THRESHOLD,
    CREDIT_LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD,
    CREDIT_PROVISIONAL_CONFIDENCE_CEILING,
    CREDIT_SCORE_DATA_GAPS,
    CREDIT_SCORE_MODEL_VERSION,
    CREDIT_SCORE_SCHEMA_VERSION,
    STRENGTHS_WEAKNESSES_COUNT,
    BankingLensSignals,
    CreditCategoryBreakdown,
    CreditCategoryWeightProfile,
    CreditRatioContribution,
    CreditScoreComputationStatus,
    CreditScoreResult,
    DataGapDisclosure,
    HealthScoreReference,
    clamp_score,
    normalize_weights,
)
from app.engines.common.health_score_types import HealthScoreResult
from app.engines.common.ratio_formulas import RATIO_REGISTRY
from app.engines.health_score.service import (
    collect_all_warnings,
    collect_ratio_signals,
    compute_overall_data_coverage_ratio,
    compute_ratio_score,
)

ENGINE_VERSION = "1.0.0"

# Credit Score'un aktif olduğu 6 kategori (Bölüm 5.1/8) -- Health
# Score'un 7-kategorili natif taksonomisinden FARKLI bir yeniden
# gruplama: `leverage`/`debt_service_capacity` AYRI kategorilerdir,
# `profitability` Health Score'un `profitability`+`efficiency`'sinin
# BİRLEŞİMİDİR. `cash_flow` karşılığı yapısal olarak %0 ağırlıklı,
# bu listede YOKTUR (Health Score ile AYNI disiplin).
ACTIVE_CATEGORIES: tuple[str, ...] = (
    "liquidity", "leverage", "debt_service_capacity", "profitability", "activity", "growth",
)


# --- Aşama C: Duplicate/derived sinyalleri filtrele (Credit'in KENDİ ------
# registry'siyle) -----------------------------------------------------------


def filter_scoreable_signals(
    signals: "dict[str, dict[str, Any]]", category: str
) -> "tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]":
    """
    Bölüm 7'nin nihai sınıflandırmasıyla (`CREDIT_RATIO_SCORE_WEIGHTS`),
    verilen kategorideki sinyalleri iki gruba ayırır:

    - `scored`: `ratio_weight > 0` -- sayısal skora KATKI VERİR.
    - `excluded`: `ratio_weight == 0` -- yalnızca explainability amaçlı
      görüntülenir, sayısal skora KATKI VERMEZ.

    `category`, Credit Score'un KENDİ 6-kategorili taksonomisidir
    (`ACTIVE_CATEGORIES`) -- Health Score'un `filter_scoreable_signals`'ı
    ile İMZASI AYNI ama Credit'in KENDİ registry'sini okur (bu yüzden
    Credit-özgü bir kopyası burada tutulur).
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


# --- Aşama D/E: Oran puanları + kategori ham skoru ------------------------
#
# `compute_ratio_score` (tier interpolasyonu dahil) Health Score'dan
# DOĞRUDAN yeniden kullanılır -- bkz. modül docstring'i.


def registry_ratio_weights_for_category(category: str) -> "dict[str, Decimal]":
    """
    Bir kategorideki scored (`ratio_weight>0`) oranların, `CREDIT_RATIO_
    SCORE_WEIGHTS`'te kayıtlı HAM (redistribute EDİLMEMİŞ) ağırlıkları.
    """

    return {
        code: w.ratio_weight
        for code, w in CREDIT_RATIO_SCORE_WEIGHTS.items()
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
) -> CreditCategoryBreakdown:
    """
    Aşama E: bir kategorinin `raw_score`'unu ve TAM `CreditRatioContribution`
    kırılımını üretir (Health Score'un `build_category_breakdown`'ıyla AYNI
    ağırlıklı-ortalama matematiği, ANCAK Credit'in KENDİ dataclass'larına
    -- `role` alanı DAHİL -- yazar).

    Yalnızca `benchmark_status == "evaluated"` olan scored oranlar
    ağırlıklı ortalamaya KATKI VERİR -- sıfır EVALUATED oran varsa
    `raw_score=None` kalır (asla fabrike edilmez).
    """

    contributions: "list[CreditRatioContribution]" = []
    weighted_sum = Decimal("0")
    weight_sum = Decimal("0")

    for ratio_code, signal in scored_signals.items():
        points, fallback_used = compute_ratio_score(ratio_code, signal)
        weight = ratio_weights.get(ratio_code, Decimal("0"))
        is_evaluated = signal.get("benchmark_status") == "evaluated" and points is not None
        role = CREDIT_RATIO_SCORE_WEIGHTS[ratio_code].role

        contributions.append(
            CreditRatioContribution(
                ratio_code=ratio_code,
                benchmark_status=signal.get("benchmark_status", "benchmark_not_registered"),
                tier=signal.get("tier"),
                ratio_score=points,
                ratio_weight_applied=weight if is_evaluated else Decimal("0"),
                role=role,
                tier_fallback_used=fallback_used,
                reliability=signal.get("benchmark_reliability", "not_calculable"),
                is_duplicate_excluded=False,
            )
        )

        if is_evaluated:
            weighted_sum += points * weight
            weight_sum += weight

    for ratio_code, signal in excluded_signals.items():
        role = CREDIT_RATIO_SCORE_WEIGHTS[ratio_code].role
        contributions.append(
            CreditRatioContribution(
                ratio_code=ratio_code,
                benchmark_status=signal.get("benchmark_status", "benchmark_not_registered"),
                tier=signal.get("tier"),
                ratio_score=None,
                ratio_weight_applied=Decimal("0"),
                role=role,
                tier_fallback_used=False,
                reliability=signal.get("benchmark_reliability", "not_calculable"),
                is_duplicate_excluded=True,
            )
        )

    raw_score = clamp_score(weighted_sum / weight_sum) if weight_sum > 0 else None
    total_scoreable = len(scored_signals)
    evaluated_count = sum(
        1 for s in scored_signals.values() if s.get("benchmark_status") == "evaluated"
    )
    coverage_ratio = (
        (Decimal(evaluated_count) / Decimal(total_scoreable))
        if total_scoreable > 0
        else Decimal("0")
    )

    return CreditCategoryBreakdown(
        category=category,
        raw_score=raw_score,
        score_after_override=None,
        weight_applied=category_weight,
        coverage_ratio=coverage_ratio,
        redistributed_weights=dict(ratio_weights),
        critical_overrides_applied=critical_overrides_applied,
        ratio_contributions=tuple(contributions),
    )


# --- Bölüm 11: Coverage normalization (Adım 5) ----------------------------
#
# `compute_overall_data_coverage_ratio` Health Score'dan DOĞRUDAN yeniden
# kullanılır (bkz. import) -- yalnızca `{category: scored_signals}` üzerinde
# çalışan, HERHANGİ bir registry'ye bağlı OLMAYAN saf bir toplama
# fonksiyonudur. `determine_insufficient_data_and_warning`/`resolve_cross_
# category_weights` ise Credit'in KENDİ, AYRI versiyonlanan model
# sabitlerini/dataclass'larını okuduğu için (Bölüm 15) burada KENDİ
# kopyaları tutulur -- matematik AYNI, sabitler/tipler Credit'e ÖZGÜ.


def redistribute_category_weights(
    category: str, scored_signals: "dict[str, dict[str, Any]]"
) -> "dict[str, Decimal]":
    """
    Bölüm 11 (kategori-içi yeniden ağırlıklandırma, 1. seviye): bir
    kategorideki EVALUATED olmayan (missing/not_calculable) scored
    oranların registry ağırlığı, EVALUATED olanlar arasında ORANTILI
    olarak yeniden dağıtılır.
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


def determine_insufficient_data_and_warning(
    data_coverage_ratio: Decimal,
) -> "tuple[bool, bool]":
    """
    Bölüm 11 (Onaylanmış Karar #7): Credit Score'un KENDİ üç bantlı
    coverage davranışı -- sayısal olarak Health Score ile AYNI eşikler,
    ama Credit'in KENDİ, bağımsız model sabitleri (`CREDIT_INSUFFICIENT_
    DATA_COVERAGE_THRESHOLD`/`CREDIT_LOW_CONFIDENCE_WARNING_COVERAGE_
    THRESHOLD`) okunur.

    Dönüş: `(is_insufficient_data, low_confidence_warning)`.
    - `< 0.50`         -> (True, False)  -- skor HİÇ üretilmez.
    - `[0.50, 0.70)`   -> (False, True)  -- skor üretilir, zorunlu uyarı.
    - `>= 0.70`        -> (False, False) -- normal.
    """

    if data_coverage_ratio < CREDIT_INSUFFICIENT_DATA_COVERAGE_THRESHOLD:
        return True, False
    if data_coverage_ratio < CREDIT_LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD:
        return False, True
    return False, False


def resolve_cross_category_weights(
    category_breakdowns: "dict[str, CreditCategoryBreakdown]",
    category_weight_profile: CreditCategoryWeightProfile,
) -> "dict[str, Decimal]":
    """
    Bölüm 11 (kategoriler arası yeniden ağırlıklandırma, 2. seviye):
    `raw_score is None` (sıfır EVALUATED oran) olan kategoriler
    kategoriler arası ağırlıklandırmadan ÇIKARILIR, kalan AKTİF
    kategorilerin `CreditCategoryWeightProfile.category_weights`'i KENDİ
    ARALARINDA yeniden normalize edilir.

    Bu fonksiyon `score_after_override` HENÜZ hesaplanmamışken de (Adım
    5 aşamasında, critical override'dan ÖNCE) güvenle kullanılabilir --
    `raw_score is None` kontrolü yeterlidir.
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


# --- Bölüm 9: Critical Override (Adım 6) ----------------------------------
#
# Terminoloji netliği (implementasyon direktifi kural #6): bu ORANSAL
# ÇARPAN, kategorinin KENDİ ham skoruna, kategoriler arası ağırlıklan-
# dırmadan (Aşama H) ÖNCE uygulanır -- Bölüm 10'daki "hard-fail ceiling"
# (final skora üst sınır) ile KESİNLİKLE KARIŞTIRILMAZ, AYRI bir
# mekanizmadır (aşağıdaki `apply_hard_fail_rules`, Adım 7).


def apply_critical_override(
    category: str,
    raw_score: "Decimal | None",
    signals: "dict[str, dict[str, Any]]",
) -> "tuple[Decimal | None, tuple[str, ...]]":
    """
    Aşama F: `CREDIT_CRITICAL_OVERRIDE_RULES`'taki (5 kural) oransal
    çarpanı KATEGORİNİN KENDİ ham skoruna uygular.

    `raw_score=None` iken hiçbir şey yapılamaz -- `(None, ())` döner.

    Aynı kategoride birden fazla kural tetiklenirse çarpanlar ÇARPILIR,
    ama sonuç `CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR`'un (0.50) ALTINA
    düşürülMEZ. Sonuç HER ZAMAN `[0,100]` aralığına clamp edilir
    (paylaşılan `clamp_score`).

    `debt_to_equity` (Bölüm 7.2, Onaylanmış Karar #5) HİÇBİR kuralda YER
    ALMAZ -- bu garanti `CREDIT_CRITICAL_OVERRIDE_RULES`'ın kendi
    kayıt-anı doğrulamasıyla (credit_score_registry.py) ZATEN sağlanmıştır,
    burada AYRICA kontrol EDİLMEZ (tek bir doğrulama noktası).
    """

    if raw_score is None:
        return None, ()

    triggered: "list[str]" = []
    combined_multiplier = Decimal("1")

    for rule in CREDIT_CRITICAL_OVERRIDE_RULES:
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

    combined_multiplier = max(combined_multiplier, CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR)
    return clamp_score(raw_score * combined_multiplier), tuple(triggered)


# --- Bölüm 10: Hard-Fail Kuralları (Adım 7) --------------------------------
#
# Terminoloji netliği (implementasyon direktifi kural #7): bu, FİNAL
# skora, kategoriler arası ağırlıklandırmadan SONRA uygulanan bir üst
# sınırdır (ceiling) -- Bölüm 9'daki "critical override" (kategori
# skoruna oransal çarpan) ile KESİNLİKLE KARIŞTIRILMAZ, AYRI bir
# mekanizmadır.


def apply_hard_fail_rules(
    preliminary_score: "Decimal | None",
    signals: "dict[str, dict[str, Any]]",
) -> "tuple[Decimal | None, tuple[str, ...]]":
    """
    Aşama I: `CREDIT_HARD_FAIL_RULES`'taki (2 kural: NEGATIVE_EQUITY
    ceiling=15, SEVERE_DEBT_SERVICE_SHORTFALL ceiling=25) HER kural
    değerlendirilir. Herhangi biri tetiklenirse, TÜM tetiklenen
    kuralların `score_ceiling`'leri arasından EN DÜŞÜK olanı (en katı
    tavan) `preliminary_score` ile `min()` alınarak uygulanır.

    Eksik veri (`ratios.get(code) is None`) HER ZAMAN `False` predicate
    sonucu üretir -- eksik veri hard-fail olarak YORUMLANMAZ.

    `preliminary_score=None` iken hiçbir şey yapılamaz -- `(None, ())`.

    Skor HER ZAMAN üretilir (ikili kabul/red YOKTUR) -- bu fonksiyon
    yalnızca bir ÜST SINIR uygular, asla `None` döndürerek hesaplamayı
    İPTAL ETMEZ.
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
    for rule in CREDIT_HARD_FAIL_RULES:
        if rule.predicate(ratios, benchmarks):
            triggered.append(rule.rule_code)
            ceilings.append(rule.score_ceiling)

    if not triggered:
        return preliminary_score, ()

    final_score = min([preliminary_score, *ceilings])
    return clamp_score(final_score), tuple(triggered)


# --- Bölüm 11: Confidence modeli (Adım 8) ---------------------------------


def weighted_reliabilities_for_category(
    breakdown: CreditCategoryBreakdown, category_weight: Decimal
) -> "list[tuple[str, Decimal]]":
    """
    Bir `CreditCategoryBreakdown`'ın EVALUATED (`ratio_score is not None`,
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
    Bölüm 11 (Onaylanmış Karar #8): `confidence_score = min(weighted_
    average(reliability_weight), CREDIT_PROVISIONAL_CONFIDENCE_CEILING)`
    -- Health Score'un 0.60 tavanından DAHA SIKI (0.50), coverage'dan
    BAĞIMSIZ olarak hesaplanır.

    Boş girdide (hiçbir EVALUATED oran yok -- ör. INSUFFICIENT_DATA
    durumu) `0` döner -- fabrike bir güven değeri ÜRETİLMEZ.
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
    return min(raw_confidence, CREDIT_PROVISIONAL_CONFIDENCE_CEILING)


# --- Bölüm 3.2/14: HealthScoreReference entegrasyonu (Adım 9) -------------
#
# **INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE** (implementasyon
# direktifi kural #1, tasarım dokümanı Bölüm 3.2): bu fonksiyon
# `HealthScoreResult`'ı YALNIZCA OKUR ve bir `HealthScoreReference`
# ÖZETİNE dönüştürür -- Credit Score'un SAYISAL hesaplamasına (final_
# score/pre_hard_fail_score/category_breakdown/ratio-katkıları/coverage/
# confidence/critical-override/hard-fail sonuçları) HİÇBİR GİRDİ
# SAĞLAMAZ. Bu değişmezliğin KANITI, Adım 14'teki property testinde
# (farklı/adversarial `HealthScoreResult` girdileriyle BİT-BİRE-BİT AYNI
# `CreditScoreResult` sayısal alanları) yapılır.


def build_health_score_reference(health_score_result: HealthScoreResult) -> HealthScoreReference:
    """
    `HealthScoreResult`'tan `HealthScoreReference`'a dönüşüm -- salt
    referans/tutarlılık/explainability amaçlı, KOPYALAMA/HESAPLAMA
    İÇERMEZ.
    """

    status = health_score_result.status
    status_value = status.value if hasattr(status, "value") else str(status)

    return HealthScoreReference(
        health_score_final_score=health_score_result.final_score,
        health_score_letter_rating=health_score_result.letter_rating,
        health_score_confidence=health_score_result.confidence_score,
        health_score_coverage=health_score_result.data_coverage_ratio,
        health_score_status=status_value,
    )


# --- Bölüm 13/13.1: BankingLensSignals (Adım 10) --------------------------


def build_banking_lens_signals(
    signals: "dict[str, dict[str, Any]]",
) -> "tuple[BankingLensSignals, tuple[dict[str, Any], ...]]":
    """
    Bölüm 13.1: `CREDIT_BANKING_LENS_SIGNAL_RULES`'taki (6 deterministik
    kural) HER BİRİ değerlendirilir. `predicate(signals)`:

    - `True`  -> bayrak TETİKLENDİ, `flags`'e eklenir.
    - `False` -> bayrak tetiklenMEDİ, hiçbir şey eklenmez.
    - `None`  -> yetersiz/güvenilmez veri -- bayrak ÜRETİLMEZ, bunun
      yerine `missing_input_note_tr`'den bir veri-boşluğu uyarısı üretilir
      (dönüşün 2. elemanı -- çağıran bunu `warnings`'e EKLEMELİDİR).

    `exposure_sensitivity` -- İCAT EDİLEN bir formül DEĞİL, tetiklenen
    bayrak SAYISINA dayalı basit, deterministik, provisional bir eşik
    (implementasyon detayı -- tasarım dokümanı Bölüm 13, `str` tipini
    sabitler ama SAYISAL eşiği KİLİTLEMEZ): 0 bayrak -> "low", 1-2 bayrak
    -> "medium", 3+ bayrak -> "high". Bayraklar sayısal skoru ASLA
    ETKİLEMEZ -- bu yalnızca niteliksel bir özet alanıdır.
    """

    triggered_flags: "list[str]" = []
    missing_input_warnings: "list[dict[str, Any]]" = []

    for rule in CREDIT_BANKING_LENS_SIGNAL_RULES:
        result = rule.predicate(signals)
        if result is True:
            triggered_flags.append(rule.flag_code)
        elif result is None:
            missing_input_warnings.append(
                {
                    "code": f"BANKING_LENS_{rule.flag_code}_DATA_GAP",
                    "severity": "low",
                    "message": rule.missing_input_note_tr,
                }
            )
        # result is False -> hicbir sey eklenmez.

    flag_count = len(triggered_flags)
    if flag_count == 0:
        exposure_sensitivity = "low"
    elif flag_count <= 2:
        exposure_sensitivity = "medium"
    else:
        exposure_sensitivity = "high"

    banking_lens_signals = BankingLensSignals(
        exposure_sensitivity=exposure_sensitivity,
        flags=tuple(triggered_flags),
    )
    return banking_lens_signals, tuple(missing_input_warnings)


# --- Bölüm 19: DataGapDisclosure (Adım 10) ---------------------------------


def build_data_gap_disclosures() -> "tuple[DataGapDisclosure, ...]":
    """
    Bölüm 19: platformun BUGÜNKÜ, YAPISAL 4 veri boşluğu (FORWARD_CASH_
    FLOW/COLLATERAL/PAYMENT_HISTORY/MANAGEMENT_QUALITY) -- HER `CreditScoreResult`'ta
    SABİT olarak bulunur, girdiye BAĞLI DEĞİLDİR (`excluded_from_score=
    True` HER ZAMAN).
    """

    return CREDIT_SCORE_DATA_GAPS


# --- Bölüm 12: Risk kademesi (Adım 11) -------------------------------------

CREDIT_RISK_TIER_DISCLAIMER_TR = (
    "Bu sınıflandırma platformun içsel, heuristik bir risk göstergesidir "
    "-- resmî bir kredi derecelendirmesi (KKB/Findeks/uluslararası "
    "derecelendirme kuruluşu notu) DEĞİLDİR ve böyle KULLANILMAMALIDIR."
)

# Sıra ÖNEMLİ: yüksekten düşüğe, ilk uyan bant kullanılır (Bölüm 12,
# Onaylanmış Karar #2). AAA/AA/A gibi uluslararası derecelendirme
# notları KULLANILMAZ, Health Score'un "sağlık sınıfı" dili de TEKRAR
# KULLANILMAZ -- kasıtlı olarak FARKLI, RİSK-odaklı Türkçe kelimeler.
_RISK_TIER_BANDS: "tuple[tuple[Decimal, str], ...]" = (
    (Decimal("80"), "Düşük Risk"),
    (Decimal("65"), "Sınırlı Risk"),
    (Decimal("50"), "İzlenmesi Gereken Risk"),
    (Decimal("35"), "Yükselen Risk"),
    (Decimal("20"), "Yüksek Risk"),
    (Decimal("0"), "Kritik Risk"),
)


def determine_risk_tier(final_score: "Decimal | None") -> "str | None":
    """
    Bölüm 12 (Onaylanmış Karar #2): 6 kademeli Türkçe RİSK skalası.
    `final_score=None` (ör. `INSUFFICIENT_DATA`) iken `None` döner --
    fabrike bir kademe ÜRETİLMEZ.
    """

    if final_score is None:
        return None
    for threshold, label in _RISK_TIER_BANDS:
        if final_score >= threshold:
            return label
    return _RISK_TIER_BANDS[-1][1]  # kurami geregi ulasilmamali (0 zaten en alt bant)


# --- Bölüm 15: Strengths / Weaknesses üretimi (Adım 11) --------------------
#
# `_TIER_RANK`/`_format_ratio_value_tr` mantığı Health Score'unkiyle AYNI
# (generic, RATIO_REGISTRY metadata'sına dayalı) -- ama Credit'in KENDİ
# `CreditRatioContribution`/`role` alanını okuduğu için burada KENDİ,
# ayrı (kısa) bir kopyası tutulur.

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
    category_breakdowns: "dict[str, CreditCategoryBreakdown]",
    all_signals: "dict[str, dict[str, Any]]",
    *,
    count: int = STRENGTHS_WEAKNESSES_COUNT,
) -> "tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]":
    """
    Bölüm 14/15: aday havuzu yalnızca EVALUATED, scored (duplicate
    OLMAYAN) oranlardır -- `(tier_rank, ratio_score)` ile sıralanır, ilk
    `count` tanesi strengths/weaknesses olur. Deterministik Türkçe string
    template'ler, `ratio_code` alfabetik tie-break.
    """

    candidates: "list[tuple[str, CreditRatioContribution]]" = []
    for category, breakdown in category_breakdowns.items():
        for contribution in breakdown.ratio_contributions:
            if contribution.is_duplicate_excluded or contribution.ratio_score is None:
                continue
            candidates.append((category, contribution))

    def _entry(category: str, contribution: CreditRatioContribution) -> "dict[str, Any]":
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
            "role": contribution.role,
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


# --- Adım 11: Service orchestration -- compute_credit_score() --------------


def compute_credit_score(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
    tenant_id: "str | None" = None,
) -> CreditScoreResult:
    """
    Bölüm 4'ün TAM pipeline'ı -- saf, bağımsız bir kütüphane fonksiyonu
    (HİÇBİR `EngineAdapter`/`AnalysisType`/DB kaydına bağlı DEĞİL).

    **INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE** -- `health_score_
    result` SADECE `build_health_score_reference()` üzerinden `health_
    score_reference` alanına OKUNUR; `final_score`/`pre_hard_fail_score`/
    `category_breakdown`/`confidence_score`/`data_coverage_ratio`/
    `hard_fails_triggered`/`critical_overrides_applied` -- yani TÜM
    sayısal hesaplama -- YALNIZCA `ratio_result_json`/`benchmark_result_
    json`'dan türetilir. Bu değişmezliğin property-test KANITI Adım
    14'tedir.
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

    profile = resolve_credit_category_weights(
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

    health_score_reference = build_health_score_reference(health_score_result)
    banking_lens_signals, banking_lens_missing_warnings = build_banking_lens_signals(signals)
    data_gap_disclosures = build_data_gap_disclosures()

    # Aşama C-E: her kategori için ham skor -- Bölüm 11'in redistribute
    # edilmiş ağırlıklarıyla.
    category_breakdowns: "dict[str, CreditCategoryBreakdown]" = {}
    for category in ACTIVE_CATEGORIES:
        redistributed = redistribute_category_weights(category, all_scored[category])
        category_breakdowns[category] = build_category_breakdown(
            category, all_scored[category], all_excluded[category], redistributed,
        )

    if is_insufficient:
        # Pipeline BURADA DURUR -- critical override/hard-fail/cross-
        # category ağırlıklandırma HİÇ ÇALIŞMAZ. Kategori kırılımları
        # (teşhis bilgisi) YİNE DE döner -- yalnızca NİHAİ, tek bir
        # toplu skor FABRİKE EDİLMEZ.
        warnings = collect_all_warnings(
            ratio_result_json,
            benchmark_result_json,
            extra_warnings=(
                {
                    "code": "INSUFFICIENT_DATA",
                    "severity": "high",
                    "message": (
                        "Veri kapsamı yetersiz "
                        f"(coverage={data_coverage_ratio}) -- Credit Score "
                        "üretilmedi."
                    ),
                },
                *banking_lens_missing_warnings,
            ),
        )
        return CreditScoreResult(
            status=CreditScoreComputationStatus.INSUFFICIENT_DATA,
            final_score=None,
            pre_hard_fail_score=None,
            risk_tier=None,
            risk_tier_disclaimer_tr=CREDIT_RISK_TIER_DISCLAIMER_TR,
            confidence_score=Decimal("0"),
            data_coverage_ratio=data_coverage_ratio,
            low_confidence_warning=False,
            provisional=True,
            category_breakdown=tuple(category_breakdowns[c] for c in ACTIVE_CATEGORIES),
            hard_fails_triggered=(),
            critical_overrides_applied=(),
            scoreable_ratio_codes=scoreable_ratio_codes,
            excluded_duplicate_ratio_codes=excluded_duplicate_ratio_codes,
            health_score_reference=health_score_reference,
            banking_lens_signals=banking_lens_signals,
            data_gap_disclosures=data_gap_disclosures,
            strengths=(),
            weaknesses=(),
            warnings=warnings,
            credit_score_schema_version=CREDIT_SCORE_SCHEMA_VERSION,
            credit_score_model_version=CREDIT_SCORE_MODEL_VERSION,
            health_score_schema_version=health_score_result.health_score_schema_version,
            health_score_model_version=health_score_result.health_score_model_version,
            benchmark_registry_version=benchmark_registry_version,
            ratio_registry_version=ratio_registry_version,
            category_weight_profile_used=profile_label,
        )

    # Aşama F/G: critical override, KATEGORİNİN KENDİ ham skoruna --
    # kategoriler arası ağırlıklandırmadan ÖNCE.
    overridden_breakdowns: "dict[str, CreditCategoryBreakdown]" = {}
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

    # Aşama H: kategoriler arası ağırlıklandırma (Bölüm 11, 2. seviye
    # yeniden dağıtım -- tamamen eksik kategoriler dışlanır).
    resolved_weights = resolve_cross_category_weights(overridden_breakdowns, profile)
    final_breakdowns: "dict[str, CreditCategoryBreakdown]" = {}
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

    # Confidence/coverage/explainability.
    weighted_reliabilities: "list[tuple[str, Decimal]]" = []
    for category in ACTIVE_CATEGORIES:
        breakdown = final_breakdowns[category]
        weighted_reliabilities.extend(
            weighted_reliabilities_for_category(breakdown, breakdown.weight_applied)
        )
    confidence_score = compute_confidence_score(weighted_reliabilities)

    risk_tier = determine_risk_tier(final_score)
    strengths, weaknesses = generate_strengths_weaknesses(final_breakdowns, signals)

    extra_warnings: "list[dict[str, Any]]" = list(banking_lens_missing_warnings)
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
        CreditScoreComputationStatus.HARD_FAIL_CAPPED
        if hard_fails_triggered
        else CreditScoreComputationStatus.COMPUTED
    )

    return CreditScoreResult(
        status=status,
        final_score=final_score,
        pre_hard_fail_score=pre_hard_fail_score,
        risk_tier=risk_tier,
        risk_tier_disclaimer_tr=CREDIT_RISK_TIER_DISCLAIMER_TR,
        confidence_score=confidence_score,
        data_coverage_ratio=data_coverage_ratio,
        low_confidence_warning=low_confidence_warning,
        provisional=True,
        category_breakdown=tuple(final_breakdowns[c] for c in ACTIVE_CATEGORIES),
        hard_fails_triggered=hard_fails_triggered,
        critical_overrides_applied=tuple(all_critical_overrides),
        scoreable_ratio_codes=scoreable_ratio_codes,
        excluded_duplicate_ratio_codes=excluded_duplicate_ratio_codes,
        health_score_reference=health_score_reference,
        banking_lens_signals=banking_lens_signals,
        data_gap_disclosures=data_gap_disclosures,
        strengths=strengths,
        weaknesses=weaknesses,
        warnings=warnings,
        credit_score_schema_version=CREDIT_SCORE_SCHEMA_VERSION,
        credit_score_model_version=CREDIT_SCORE_MODEL_VERSION,
        health_score_schema_version=health_score_result.health_score_schema_version,
        health_score_model_version=health_score_result.health_score_model_version,
        benchmark_registry_version=benchmark_registry_version,
        ratio_registry_version=ratio_registry_version,
        category_weight_profile_used=profile_label,
    )
