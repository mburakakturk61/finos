"""
Milestone 4.3E (Credit Score Engine) -- Adım 1: temel veri modeli,
enum'lar, sabitler.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3E_CREDIT_SCORE_
ENGINE_DESIGN.md (2. tur, 15 bağlayıcı karar -- Bölüm 26 "Onaylanmış
Kararlar"). Bu modül `app/engines/common/health_score_types.py`'nin
(4.3D) AYNI disipliniyle yazılmıştır: eval/exec/dinamik expression
YASAK, kapalı bir dataclass/enum kümesi, sqlalchemy/fastapi/pydantic'e
SIFIR bağımlı.

**Bağlayıcı sınır (Bölüm 2/2.1):** bu modül HİÇBİR `EngineAdapter`/
`AnalysisType`/DB kaydına bağlı DEĞİLDİR.

**Paylaşılan kod (Bölüm 3.2/26 karar #3, implementasyon kuralı #12):**
`normalize_weights()`/`clamp_score()`/`TIER_TO_POINTS`/`HealthScoreTier`/
`CONFIDENCE_RELIABILITY_WEIGHT` BURADA YENİDEN TANIMLANMAZ --
`app.engines.common.health_score_types`'tan DOĞRUDAN import edilir (aynı
matematiğin ikinci bir kopyası YAZILMAZ). Yalnızca Credit Score'a ÖZGÜ
model verileri (kategori ağırlıkları, hard-fail ceiling'leri, critical
override çarpanları, risk tier bantları) bu modülde KENDİ, AYRI
sabitleri olarak tanımlanır -- Health Score'unkilerle SAYISAL olarak
aynı olsalar bile (ör. coverage eşikleri), bunlar KAVRAMSAL olarak
Credit Score'un KENDİ, bağımsız versiyonlanan model parametreleridir
(Bölüm 15).
"""

from dataclasses import dataclass, field
from decimal import Decimal
import enum
from typing import Any, Callable

# --- Paylaşılan yardımcılar (YENİDEN KULLANILIR, kopyalanmaz) -----------

from app.engines.common.health_score_types import (  # noqa: F401
    CONFIDENCE_RELIABILITY_WEIGHT,
    STRENGTHS_WEAKNESSES_COUNT,
    TIER_TO_POINTS,
    HealthScoreTier,
    clamp_score,
    normalize_weights,
)


# --- Versiyon eksenleri (Bölüm 15 -- altı BAĞIMSIZ eksen) ---------------
#
# `credit_score_schema_version`/`credit_score_model_version` BURADA
# tanımlanır; `health_score_schema_version`/`health_score_model_version`/
# `ratio_registry_version`/`benchmark_registry_version` girdi olarak
# OKUNAN sonuçlardan (HealthScoreResult/ratio_result_json/benchmark_
# result_json) TAŞINIR, burada SABİT tanımlanmaz.

CREDIT_SCORE_SCHEMA_VERSION = "1.0.0"
CREDIT_SCORE_MODEL_VERSION = "1.0.0"


class CreditScoreComputationStatus(str, enum.Enum):
    """
    Bölüm 4/7/11: bir Credit Score hesaplamasının nihai durumu -- Health
    Score'un `HealthScoreComputationStatus`'uyla AYNI 3 değer (paylaşılan
    vocabulary), ama Credit Score'un KENDİ, bağımsız şema ekseninin
    (Bölüm 15) parçası olduğu için AYRI bir enum olarak tanımlanır.

    COMPUTED: skor normal şekilde hesaplandı.
    HARD_FAIL_CAPPED: Bölüm 10'daki hard-fail kurallarından biri
        tetiklendi, `final_score` bir tavanla sınırlandı.
    INSUFFICIENT_DATA: `data_coverage_ratio < CREDIT_INSUFFICIENT_DATA_
        COVERAGE_THRESHOLD` -- final_score/risk_tier HİÇBİR ZAMAN
        fabrike edilmez, ikisi de None kalır.
    """

    COMPUTED = "computed"
    HARD_FAIL_CAPPED = "hard_fail_capped"
    INSUFFICIENT_DATA = "insufficient_data"


# --- Bölüm 11: coverage/confidence sabitleri (BAĞLAYICI karar #7/#8) ---

# Onaylanmış Karar #8: Health Score'un 0.60'ından DAHA SIKI -- Credit
# Score, Health Score'un TÜM belirsizliğini miras alır VE Bölüm 19'daki
# yapısal veri boşluklarını (KKB/teminat/ödeme geçmişi/nakit akışı) taşır.
CREDIT_PROVISIONAL_CONFIDENCE_CEILING: Decimal = Decimal("0.50")

# Onaylanmış Karar #7: Health Score ile AYNI üç bant (sayısal olarak aynı,
# ama Credit Score'un KENDİ, bağımsız model sabiti).
CREDIT_INSUFFICIENT_DATA_COVERAGE_THRESHOLD: Decimal = Decimal("0.50")
CREDIT_LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD: Decimal = Decimal("0.70")

# --- Bölüm 9: critical override sabitleri (BAĞLAYICI karar #6) ---------
#
# Terminoloji netliği: bu ORANSAL ÇARPAN, kategori skoruna, kategoriler
# arası ağırlıklandırmadan ÖNCE uygulanır -- Bölüm 10'daki "hard-fail
# ceiling" (final skora üst sınır) ile KARIŞTIRILMAZ, AYRI bir
# mekanizmadır.
CREDIT_CRITICAL_OVERRIDE_WEAK_MULTIPLIER: Decimal = Decimal("0.90")
CREDIT_CRITICAL_OVERRIDE_CRITICAL_MULTIPLIER: Decimal = Decimal("0.65")
CREDIT_CRITICAL_OVERRIDE_CATEGORY_FLOOR: Decimal = Decimal("0.50")

# `CONFIDENCE_RELIABILITY_WEIGHT` (yukarıda import edilen, PAYLAŞILAN
# sözlük) buradan tekrar dışa aktarılır -- yeniden TANIMLANMAZ.


# --- Bölüm 5: veri modeli -----------------------------------------------


@dataclass(frozen=True)
class CreditCategoryWeightProfile:
    """Bölüm 16: kategori ağırlığı override mimarisinin veri modeli."""

    scope: str  # "global" | "industry" | "company_size" | "tenant"
    scope_key: "str | None"
    category_weights: "dict[str, Decimal]"


@dataclass(frozen=True)
class CreditRatioScoreWeight:
    """
    Bölüm 5.2/6: bir oranın Credit Score içindeki ağırlığı VE rolü.

    `ratio_weight=0` -- Bölüm 7'nin nihai sınıflandırmasıyla
    "explainability-only" (duplicate/derived) işaretli bir orandır;
    sayısal skora KATKI VERMEZ.

    `role`:
      - "critical": kategori ortalamasına katkı verir + Bölüm 9/10
        (critical override/hard-fail) kurallarının TETİKLEYİCİSİ
        olabilir.
      - "supporting": yalnızca kategori ortalamasına katkı verir.
      - "explainability_only": `ratio_weight=0`, sayısal katkı YOK --
        KAYIT ANINDA (kayıt validasyonu) hiçbir critical-override/
        hard-fail kuralında yer ALAMAZ (Bölüm 7.2, Onaylanmış Karar #5).
    """

    ratio_code: str
    category: str
    ratio_weight: Decimal
    role: str  # "critical" | "supporting" | "explainability_only"
    excluded_as_duplicate_of: "str | None" = None
    duplicate_relationship: "str | None" = None
    # "identical_formula" | "algebraic_complement" |
    # "reciprocal_via_period_constant" | "summary_signal_normalized"


@dataclass(frozen=True)
class CreditHardFailRule:
    """
    Bölüm 10: final skora, kategoriler arası ağırlıklandırmadan SONRA
    uygulanan sert bir üst sınır (ceiling). "Critical override" (Bölüm 9)
    ile KARIŞTIRILMAZ -- AYRI bir mekanizmadır.

    `predicate`, hem `ratio_result_json` DEĞERLERİNİ hem `benchmark_
    result_json` TIER'larını okuyabilir. Eksik veri (ilgili oran None/
    hesaplanamamış) HER ZAMAN `False` döndürmelidir -- eksik veri
    hard-fail olarak YORUMLANMAZ.
    """

    rule_code: str
    predicate: "Callable[[dict[str, Any], dict[str, Any]], bool]"
    score_ceiling: Decimal
    rationale_tr: str


@dataclass(frozen=True)
class CreditCriticalOverrideRule:
    """
    Bölüm 9: oransal çarpan modeli -- `weak_multiplier`/`critical_
    multiplier`, ilgili oranın tier'ı sırasıyla "weak"/"critical"
    olduğunda KENDİ kategorisinin ham skoruna uygulanır (kategoriler
    arası ağırlıklandırmadan ÖNCE).
    """

    ratio_code: str
    category: str
    weak_multiplier: Decimal
    critical_multiplier: Decimal
    rationale_tr: str


@dataclass(frozen=True)
class BankingLensSignalRule:
    """
    Bölüm 13.1: `BankingLensSignals.flags`'i üreten 6 deterministik
    kuraldan biri. `predicate`, sinyal sözlüğünü (ratio_code -> signal)
    alır ve `True` (bayrak tetiklendi) / `False` (tetiklenmedi) / `None`
    (yetersiz/güvenilmez veri -- bayrak ÜRETİLMEZ, yalnızca warning/
    data-gap notu düşülür) döner. Bayraklar sayısal skoru DEĞİŞTİRMEZ.
    """

    flag_code: str
    category: str
    rationale_tr: str
    predicate: "Callable[[dict[str, Any]], Any]"
    text_template_tr: str
    missing_input_note_tr: str


@dataclass(frozen=True)
class CreditRatioContribution:
    """Bölüm 14: bir oranın kategori kırılımındaki tam açıklaması."""

    ratio_code: str
    benchmark_status: str
    tier: "str | None"
    ratio_score: "Decimal | None"
    ratio_weight_applied: Decimal
    role: str
    tier_fallback_used: bool
    reliability: str
    is_duplicate_excluded: bool


@dataclass(frozen=True)
class CreditCategoryBreakdown:
    """Bölüm 5/14: bir kategorinin uçtan uca hesaplama izi."""

    category: str
    raw_score: "Decimal | None"
    score_after_override: "Decimal | None"
    weight_applied: Decimal
    coverage_ratio: Decimal
    redistributed_weights: "dict[str, Decimal]"
    critical_overrides_applied: "tuple[str, ...]"
    ratio_contributions: "tuple[CreditRatioContribution, ...]"


@dataclass(frozen=True)
class HealthScoreReference:
    """
    Bölüm 3.2/14: `HealthScoreResult`'tan okunan ÖZET (KOPYALANMAYAN)
    bilgi -- `INVARIANT: HEALTH_SCORE_INPUT_INDEPENDENCE`'ın veri
    modelindeki karşılığı. Bu alan Credit Score'un SAYISAL hesaplamasına
    HİÇBİR GİRDİ SAĞLAMAZ.
    """

    health_score_final_score: "Decimal | None"
    health_score_letter_rating: "str | None"
    health_score_confidence: Decimal
    health_score_coverage: Decimal
    health_score_status: str
    note_tr: str = (
        "Bu alan yalnızca Financial Health Score'un ÖZETİDİR -- Credit "
        "Score'un kendisi DEĞİLDİR, doğrudan kopyalanmamıştır ve Credit "
        "Score'un final_score hesaplamasına HİÇBİR GİRDİ SAĞLAMAZ."
    )


@dataclass(frozen=True)
class BankingLensSignals:
    """
    Bölüm 13: yalnızca NİTELİKSEL bayraklar -- HİÇBİR ZAMAN belirli bir
    TRY tutarında kredi limiti/tahsis önerisi İÇERMEZ.
    """

    exposure_sensitivity: str  # "low" | "medium" | "high"
    flags: "tuple[str, ...]"
    not_a_credit_limit_recommendation: bool = True
    disclaimer_tr: str = (
        "Bu alan bir kredi limiti, tahsis tutarı veya teminat yeterliliği "
        "ÖNERMEZ -- yalnızca hangi risk boyutlarının daha yakından "
        "incelenmesi gerektiğine dair niteliksel işaretlerdir."
    )


@dataclass(frozen=True)
class DataGapDisclosure:
    """
    Bölüm 19: platformun BUGÜNKÜ, YAPISAL veri boşluğu -- dönemsel bir
    "eksik veri" DEĞİLDİR, bu yüzden `excluded_from_score` HER ZAMAN
    `True`'dur (bu dört boyut skora HİÇ GİRMEZ, ne 0 ne "iyi" varsayılır).
    """

    gap_code: str
    description_tr: str
    excluded_from_score: bool = True


# Bölüm 19: dört sabit veri boşluğu -- HER `CreditScoreResult.data_gap_
# disclosures`'ta SABİT olarak bulunur.
CREDIT_SCORE_DATA_GAPS: "tuple[DataGapDisclosure, ...]" = (
    DataGapDisclosure(
        gap_code="FORWARD_CASH_FLOW",
        description_tr=(
            "İleri dönem nakit akışı projeksiyonu bu platformda mevcut "
            "değildir -- skor yalnızca geçmiş dönem mali tablolarına "
            "dayanır."
        ),
    ),
    DataGapDisclosure(
        gap_code="COLLATERAL",
        description_tr=(
            "Teminat/collateral verisi mevcut değildir -- skor teminat "
            "yeterliliğini (LTV vb.) HİÇ değerlendirmez."
        ),
    ),
    DataGapDisclosure(
        gap_code="PAYMENT_HISTORY",
        description_tr=(
            "Bir kredi bürosu (KKB/Findeks vb.) ödeme geçmişi "
            "entegrasyonu YOKTUR -- skor, geçmiş ödeme davranışını HİÇ "
            "yansıtmaz."
        ),
    ),
    DataGapDisclosure(
        gap_code="MANAGEMENT_QUALITY",
        description_tr=(
            "Yönetim kalitesi, covenant uyumu veya kefil gücü gibi "
            "niteliksel faktörler bu skora DAHİL DEĞİLDİR."
        ),
    ),
)


@dataclass(frozen=True)
class CreditScoreResult:
    """Bölüm 4.2/14: `compute_credit_score()`'un TAM sonucu."""

    status: CreditScoreComputationStatus
    final_score: "Decimal | None"
    pre_hard_fail_score: "Decimal | None"
    risk_tier: "str | None"
    risk_tier_disclaimer_tr: str
    confidence_score: Decimal
    data_coverage_ratio: Decimal
    low_confidence_warning: bool
    provisional: bool
    category_breakdown: "tuple[CreditCategoryBreakdown, ...]"
    hard_fails_triggered: "tuple[str, ...]"
    critical_overrides_applied: "tuple[str, ...]"
    scoreable_ratio_codes: "tuple[str, ...]"
    excluded_duplicate_ratio_codes: "tuple[str, ...]"
    health_score_reference: HealthScoreReference
    banking_lens_signals: BankingLensSignals
    data_gap_disclosures: "tuple[DataGapDisclosure, ...]"
    strengths: "tuple[dict[str, Any], ...]"
    weaknesses: "tuple[dict[str, Any], ...]"
    warnings: "tuple[dict[str, Any], ...]"
    credit_score_schema_version: str
    credit_score_model_version: str
    health_score_schema_version: str
    health_score_model_version: str
    benchmark_registry_version: str
    ratio_registry_version: str
    category_weight_profile_used: str
