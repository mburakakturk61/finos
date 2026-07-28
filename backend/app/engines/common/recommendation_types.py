"""
Milestone 4.3F (Recommendation Engine) -- Adım 1: temel veri modeli,
enum'lar, sabitler.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3F_RECOMMENDATION_
ENGINE_DESIGN.md (3. tur/son onay, Bölüm 33 "Onaylanmış Kararlar" + Bölüm
37 "Nihai Rapor" + kullanıcının implementasyon-onay mesajındaki 19
maddelik bağlayıcı teknik kural seti). Bu modül `app/engines/common/
credit_score_types.py`'nin (4.3E) AYNI disipliniyle yazılmıştır: eval/
exec/dinamik expression YASAK, kapalı bir dataclass/enum kümesi,
sqlalchemy/fastapi/pydantic'e SIFIR bağımlı.

**Bağlayıcı sınır (Bölüm 2.1):** bu modül HİÇBİR `EngineAdapter`/
`AnalysisType`/DB kaydına bağlı DEĞİLDİR.

**Paylaşılan kod:** `HealthScoreTier`/`TIER_TO_POINTS` gibi ORTAK
kavramlar burada YENİDEN TANIMLANMAZ -- yalnızca Recommendation Engine'e
ÖZGÜ model verileri (kategori taksonomisi, öncelik/severity/impact/
difficulty bantları, deklaratif trigger modeli, confidence modeli) bu
modülde KENDİ, AYRI sabitleri olarak tanımlanır.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import enum
from typing import Any

# `BankingLensSignals`/`DataGapDisclosure` Credit Score'dan DOĞRUDAN
# import edilir -- ikinci bir kopya YAZILMAZ (Bölüm 6, "credit_score_
# result'tan DOĞRUDAN, yeniden hesaplanmadan taşınır").
from app.engines.common.credit_score_types import (  # noqa: F401
    BankingLensSignals,
    DataGapDisclosure,
)


# --- Versiyon eksenleri (Bölüm 16 -- sekiz BAĞIMSIZ eksen) --------------
#
# `recommendation_schema_version`/`recommendation_model_version` BURADA
# tanımlanır; `health_score_schema_version`/`health_score_model_version`/
# `credit_score_schema_version`/`credit_score_model_version`/
# `ratio_registry_version`/`benchmark_registry_version` girdi olarak
# OKUNAN sonuçlardan TAŞINIR, burada SABİT tanımlanmaz.

RECOMMENDATION_SCHEMA_VERSION = "1.0.0"
RECOMMENDATION_MODEL_VERSION = "1.0.0"


# --- Bölüm 6.2: nihai hesaplama durumu (5 değer) -------------------------


class RecommendationComputationStatus(str, enum.Enum):
    """
    Bölüm 6.2/16.2: bir Recommendation hesaplamasının nihai durumu.

    COMPUTED: en az bir kategori değerlendirilebildi.
    NO_RECOMMENDATIONS_TRIGGERED: veri yeterli ama hiçbir kural
        tetiklenmedi (şirket sağlıklı).
    INSUFFICIENT_DATA: TÜM kategorilerde coverage < eşik.
    SCHEMA_INCOMPATIBLE: üst motor şema versiyonu desteklenmiyor --
        HİÇBİR öneri üretilmez.
    VERSION_MISMATCH: ratio/benchmark registry versiyonu desteklenmiyor,
        YALNIZCA DATA_QUALITY üretilir.
    """

    COMPUTED = "computed"
    NO_RECOMMENDATIONS_TRIGGERED = "no_recommendations_triggered"
    INSUFFICIENT_DATA = "insufficient_data"
    SCHEMA_INCOMPATIBLE = "schema_incompatible"
    VERSION_MISMATCH = "version_mismatch"


# --- Bölüm 7: RecommendationType mimarisi --------------------------------


class RecommendationCategory(str, enum.Enum):
    """Bölüm 18 -- KİLİTLİ, 8 kategorilik nihai taksonomi (Madde 5)."""

    LIQUIDITY = "liquidity"
    WORKING_CAPITAL = "working_capital"
    LEVERAGE = "leverage"
    PROFITABILITY = "profitability"
    ACTIVITY = "activity"
    GROWTH = "growth"
    BANKING_READINESS = "banking_readiness"
    DATA_QUALITY = "data_quality"


# Bölüm 18 tablosundaki sıra -- stable sort'un `category_display_order`
# bileşeni İÇİN (kullanıcının implementasyon-onay mesajı madde 9).
CATEGORY_DISPLAY_ORDER: "dict[str, int]" = {
    RecommendationCategory.LIQUIDITY.value: 0,
    RecommendationCategory.WORKING_CAPITAL.value: 1,
    RecommendationCategory.LEVERAGE.value: 2,
    RecommendationCategory.PROFITABILITY.value: 3,
    RecommendationCategory.ACTIVITY.value: 4,
    RecommendationCategory.GROWTH.value: 5,
    RecommendationCategory.BANKING_READINESS.value: 6,
    RecommendationCategory.DATA_QUALITY.value: 7,
}


class RecommendationTriggerSource(str, enum.Enum):
    """Bölüm 7.2 -- hangi motor/mekanizma tetikledi."""

    HEALTH_SCORE_HARD_FAIL = "health_score_hard_fail"
    HEALTH_SCORE_CRITICAL_OVERRIDE = "health_score_critical_override"
    HEALTH_SCORE_WEAK_TIER = "health_score_weak_tier"
    CREDIT_SCORE_HARD_FAIL = "credit_score_hard_fail"
    CREDIT_SCORE_CRITICAL_OVERRIDE = "credit_score_critical_override"
    CREDIT_SCORE_WEAK_TIER = "credit_score_weak_tier"
    BANKING_LENS_SIGNAL = "banking_lens_signal"
    DATA_QUALITY_GAP = "data_quality_gap"


class ResultBucket(str, enum.Enum):
    """
    Bölüm 8.1/12 Aşama 17 -- `category`'den DETERMİNİSTİK türetilen
    3-yönlü ayrım. LIQUIDITY/WORKING_CAPITAL/LEVERAGE/PROFITABILITY/
    ACTIVITY/GROWTH -> FINANCIAL; BANKING_READINESS -> BANKING_READINESS;
    DATA_QUALITY -> DATA_QUALITY.
    """

    FINANCIAL = "financial"
    BANKING_READINESS = "banking_readiness"
    DATA_QUALITY = "data_quality"


_FINANCIAL_CATEGORIES: "frozenset[str]" = frozenset(
    {
        RecommendationCategory.LIQUIDITY.value,
        RecommendationCategory.WORKING_CAPITAL.value,
        RecommendationCategory.LEVERAGE.value,
        RecommendationCategory.PROFITABILITY.value,
        RecommendationCategory.ACTIVITY.value,
        RecommendationCategory.GROWTH.value,
    }
)


def category_to_result_bucket(category: "RecommendationCategory | str") -> ResultBucket:
    """Bölüm 8.2 madde 3'ün DETERMİNİSTİK eşlemesi -- serbest seçim DEĞİLDİR."""

    value = category.value if isinstance(category, RecommendationCategory) else category
    if value in _FINANCIAL_CATEGORIES:
        return ResultBucket.FINANCIAL
    if value == RecommendationCategory.BANKING_READINESS.value:
        return ResultBucket.BANKING_READINESS
    if value == RecommendationCategory.DATA_QUALITY.value:
        return ResultBucket.DATA_QUALITY
    raise ValueError(f"Bilinmeyen RecommendationCategory: {value!r}")


# --- Bölüm 9: Priority/Severity sistemi -- KİLİTLİ (Madde 4) -------------


class RecommendationPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


PRIORITY_RANK: "dict[str, int]" = {
    RecommendationPriority.CRITICAL.value: 0,
    RecommendationPriority.HIGH.value: 1,
    RecommendationPriority.MEDIUM.value: 2,
    RecommendationPriority.LOW.value: 3,
    RecommendationPriority.INFORMATIONAL.value: 4,
}


class RecommendationSeverity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_RANK: "dict[str, int]" = {
    RecommendationSeverity.CRITICAL.value: 0,
    RecommendationSeverity.HIGH.value: 1,
    RecommendationSeverity.MEDIUM.value: 2,
    RecommendationSeverity.LOW.value: 3,
}


# --- Bölüm 10/11: Impact/Difficulty sistemi ------------------------------


class RecommendationImpactBand(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationDifficultyBand(str, enum.Enum):
    LOW_EFFORT = "low_effort"
    MODERATE_EFFORT = "moderate_effort"
    STRUCTURAL_EFFORT = "structural_effort"


# --- Bölüm 8.0: kapalı, deklaratif trigger modeli -- KİLİTLİ (Madde 6) ---


class RecommendationTriggerStrategy(str, enum.Enum):
    ALL_CONDITIONS = "all_conditions"
    ANY_CONDITION = "any_condition"
    MINIMUM_EVIDENCE = "minimum_evidence"
    DEBT_FUNDED_GROWTH = "debt_funded_growth"
    HARD_FAIL_PRESENT = "hard_fail_present"
    BANKING_FLAG_PRESENT = "banking_flag_present"
    DATA_COVERAGE_GAP = "data_coverage_gap"
    DATA_GAP_PRESENT = "data_gap_present"


# Bölüm 8.2 madde 8 -- katalog kontrolü için bilinen bantlar.
KNOWN_BENCHMARK_TIERS: "frozenset[str]" = frozenset(
    {"critical", "weak", "average", "good", "excellent"}
)

# Bölüm 8.2 madde 8 -- Health/Credit Score'un bilinen hard-fail kataloğu
# (health_score_registry.py/credit_score_registry.py'deki HARD_FAIL_RULES'
# ın rule_code'ları -- İKİ motor da AYNI 2 kodu kullanır).
KNOWN_HARD_FAIL_CODES: "frozenset[str]" = frozenset(
    {"NEGATIVE_EQUITY", "SEVERE_DEBT_SERVICE_SHORTFALL"}
)

# Bölüm 8.2 madde 8 -- Credit Score'un 6 bilinen BankingLensSignal bayrağı.
KNOWN_BANKING_LENS_FLAGS: "frozenset[str]" = frozenset(
    {
        "SHORT_TERM_LIQUIDITY_STRAIN",
        "HIGH_LEVERAGE",
        "DEBT_SERVICE_STRESS",
        "WEAK_PROFIT_BUFFER",
        "WORKING_CAPITAL_STRAIN",
        "DEBT_FUNDED_GROWTH",
    }
)

# Bölüm 8.2 madde 8 -- Credit Score'un 4 bilinen DataGapDisclosure kodu.
KNOWN_CREDIT_SCORE_DATA_GAP_CODES: "frozenset[str]" = frozenset(
    {"FORWARD_CASH_FLOW", "COLLATERAL", "PAYMENT_HISTORY", "MANAGEMENT_QUALITY"}
)


@dataclass(frozen=True)
class EvidenceRule:
    """
    Bölüm 8.0 -- TEK bir atomik kanıt koşulu. Alanlardan YALNIZCA biri
    (`ratio_code`+`tier_in` ÇİFTİ HARİÇ, o ikisi TEK bir tür sayılır)
    dolu olabilir -- kayıt anında MUTUAL EXCLUSIVITY doğrulanır (Bölüm
    8.2 madde 6).
    """

    ratio_code: "str | None" = None
    tier_in: "tuple[str, ...] | None" = None
    hard_fail_code: "str | None" = None
    critical_override_ratio_code: "str | None" = None
    banking_lens_flag: "str | None" = None
    category_coverage_below: "RecommendationCategory | None" = None
    coverage_threshold: "Decimal | None" = None
    credit_score_data_gap_code: "str | None" = None


@dataclass(frozen=True)
class RecommendationRule:
    """Bölüm 8.1 -- TAM, 29 alanlı registry kaydı (son onay turu)."""

    recommendation_code: str
    category: RecommendationCategory
    result_bucket: ResultBucket
    base_priority: RecommendationPriority
    severity: RecommendationSeverity
    impact_band: RecommendationImpactBand
    difficulty_band: RecommendationDifficultyBand
    trigger_strategy: RecommendationTriggerStrategy
    trigger_mode: str  # "all" | "any"
    evidence_rules: "tuple[EvidenceRule, ...]"
    minimum_evidence_count: int
    prerequisite_rules: "tuple[str, ...]"
    blocking_rules: "tuple[str, ...]"
    merge_group: "str | None"
    evidence_group: str
    underlying_risk_code: str
    conflict_group: "str | None"
    mutually_exclusive_group: "str | None"
    confidence_ceiling: Decimal
    coverage_policy: str  # "subject_to_gate" | "exempt_hard_fail" | "always_evaluated"
    related_ratio_codes: "tuple[str, ...]"
    title_tr: str
    explanation_tr: str
    action_steps_tr: "tuple[str, ...]"
    assumptions_tr: "tuple[str, ...]"
    disclaimer_tr: str
    disclaimer_scope: str  # "general" | "banking"
    model_version_introduced: str
    deprecated_since: "str | None"
    replacement_recommendation_code: "str | None"


# --- Bölüm 13: çakışma / mutually-exclusive yönetimi ---------------------


@dataclass(frozen=True)
class RecommendationConflictGroup:
    """Bölüm 13.1 -- v1'de `RECOMMENDATION_CONFLICT_PAIRS` BOŞ (Bölüm 13.2)."""

    conflict_group_id: str
    recommendation_codes: "tuple[str, ...]"
    explanation_tr: str


@dataclass(frozen=True)
class RecommendationMutuallyExclusiveGroup:
    """Bölüm 13.3 -- conflict'ten YAPISAL OLARAK AYRI (Madde 9)."""

    mutually_exclusive_group_id: str
    recommendation_codes: "tuple[str, ...]"
    explanation_tr: str


# Geriye dönük/dış tüketici uyumluluğu için: kullanıcının implementasyon-
# onay mesajı madde 8'in istediği "conflict için bir RecommendationConflict
# nesnesi üretilmeli" gereksinimi -- `RecommendationConflictGroup`'un
# KENDİSİ bu nesnedir (ikinci, paralel bir tip İCAT EDİLMEZ, Bölüm 13.1'in
# TEK doğruluk kaynağı korunur).
RecommendationConflict = RecommendationConflictGroup


# --- Bölüm 19.2: Directional Threshold Context -- TAMAMEN NİTELİKSEL ----


IMPROVEMENT_DIRECTION_TR: "dict[str, str]" = {
    "higher_is_better": "Bu göstergenin YÜKSELMESİ istenen yöndür.",
    "lower_is_better": "Bu göstergenin DÜŞMESİ istenen yöndür.",
    "range_is_better": "Bu gösterge belirli bir ARALIKTA kalmalıdır.",
}

# Bant sıralaması (kötüden iyiye) -- `next_better_tier_name` hesaplaması
# için, SAYISAL bir eşik DEĞİL, yalnızca bant İSİMLERİNİN sırası.
_TIER_ORDER: "tuple[str, ...]" = ("critical", "weak", "average", "good", "excellent")


@dataclass(frozen=True)
class RecommendationDirectionalContext:
    """
    Bölüm 19.2 -- KİLİTLİ (Madde 1). Gerçek simülasyon/sayısal hedef/oran
    farkı KESİNLİKLE İÇERMEZ; yalnızca ZATEN hesaplanmış tier/ideal_
    direction'ın niteliksel okumasıdır.
    """

    ratio_code: str
    current_tier: str
    ideal_direction: str
    improvement_direction_tr: str
    next_better_tier_name: "str | None"


def next_better_tier_name(current_tier: "str | None") -> "str | None":
    """`_TIER_ORDER`'daki bir sonraki (daha iyi) bandın YALNIZCA İSMİ."""

    if current_tier not in _TIER_ORDER:
        return None
    index = _TIER_ORDER.index(current_tier)
    if index >= len(_TIER_ORDER) - 1:
        return None
    return _TIER_ORDER[index + 1]


# --- Bölüm 15: Explainability yapısı -------------------------------------


@dataclass(frozen=True)
class RecommendationItem:
    """Bölüm 15.1 -- TAM, son onay turu alan seti."""

    recommendation_code: str
    category: RecommendationCategory
    result_bucket: ResultBucket
    severity: RecommendationSeverity
    title_tr: str
    explanation_tr: str
    action_steps_tr: "tuple[str, ...]"
    assumptions_tr: "tuple[str, ...]"
    priority: RecommendationPriority
    priority_rank: int
    blocked: bool
    impact_band: RecommendationImpactBand
    difficulty_band: RecommendationDifficultyBand
    triggered_by: "tuple[str, ...]"
    related_ratio_codes: "tuple[str, ...]"
    supporting_evidence: "tuple[dict[str, Any], ...]"
    conflict_group_id: "str | None"
    conflicting_with: "tuple[str, ...]"
    mutually_exclusive_group_id: "str | None"
    merge_group: "str | None"
    underlying_risk_code: str
    directional_context: "RecommendationDirectionalContext | None"
    confidence: Decimal
    reliability: str
    confidence_ceiling: Decimal
    coverage: Decimal
    provisional: bool
    confidence_basis: str
    evidence_reliabilities: "tuple[str, ...]"
    missing_inputs: "tuple[str, ...]"
    warnings: "tuple[dict[str, Any], ...]"
    disclaimer_tr: str


# --- Bölüm 15.3: disclaimer metinleri (marka adı hardcode YOK) ----------

RECOMMENDATION_DISCLAIMER_TR = (
    "Bu öneriler platformun içsel, heuristik göstergelerine dayanır -- "
    "profesyonel mali/hukuki/vergi danışmanlığı YERİNE GEÇMEZ ve resmî "
    "bir tavsiye niteliği TAŞIMAZ. Nihai karar şirketinizin kendi mali "
    "danışmanına AİTTİR."
)

RECOMMENDATION_BANKING_DISCLAIMER_TR = (
    "Bu öneri bir kredi limiti, tahsis tutarı veya banka onayı GARANTİ "
    "ETMEZ -- yalnızca bankayla görüşme öncesinde hangi konuların "
    "hazırlanmasının faydalı olabileceğine dair niteliksel bir "
    "işarettir."
)


def resolve_disclaimer_tr(disclaimer_scope: str) -> str:
    if disclaimer_scope == "banking":
        return f"{RECOMMENDATION_DISCLAIMER_TR} {RECOMMENDATION_BANKING_DISCLAIMER_TR}"
    return RECOMMENDATION_DISCLAIMER_TR


# --- Bölüm 15.4: confidence modeli -- KİLİTLİ (Madde 8) -------------------

RELIABILITY_TO_CONFIDENCE_CEILING: "dict[str, Decimal]" = {
    "high": Decimal("1.00"),
    "medium": Decimal("0.75"),
    "medium_low": Decimal("0.60"),
    "low": Decimal("0.50"),
    "not_calculable": Decimal("0.00"),
}

# Bölüm 15.4 madde 4 -- herhangi bir tetikleyici kanıt provisional=True
# taşıyorsa uygulanan ceiling.
PROVISIONAL_EVIDENCE_CONFIDENCE_CEILING: Decimal = Decimal("0.75")

# Bölüm 15.4 madde 5 -- kategori coverage'a göre ceiling bantları.
COVERAGE_CEILING_HIGH_THRESHOLD: Decimal = Decimal("0.80")  # >= -> ceiling YOK (1.00)
COVERAGE_CEILING_MID_THRESHOLD: Decimal = Decimal("0.50")  # [0.50,0.80) -> 0.75; <0.50 -> 0.50
COVERAGE_CEILING_HIGH_VALUE: Decimal = Decimal("1.00")
COVERAGE_CEILING_MID_VALUE: Decimal = Decimal("0.75")
COVERAGE_CEILING_LOW_VALUE: Decimal = Decimal("0.50")

# Bölüm 12 Aşama 7 -- kategori coverage gate eşiği (`coverage_policy=
# subject_to_gate` kuralları BU eşiğin ALTINDA elenir).
CATEGORY_COVERAGE_GATE_THRESHOLD: Decimal = Decimal("0.50")

# Kullanıcının implementasyon-onay mesajı madde 6 -- 3 bantlı coverage
# davranışı: <0.50 / [0.50,0.6999] / >=0.70. Orta bant, DÜŞÜK-CONFIDENCE
# uyarısını (LOW_CONFIDENCE_ON_LOW_COVERAGE) TETİKLER -- Bölüm 15.4'ün
# ceiling bantlarından (0.50/0.80) AYRI, TAMAMLAYICI bir eşiktir.
LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD: Decimal = Decimal("0.70")

# `DATA_QUALITY` kategorisi için sabit confidence (Bölüm 15.4 madde 8).
DATA_QUALITY_FIXED_CONFIDENCE: Decimal = Decimal("1.00")
DATA_QUALITY_CONFIDENCE_BASIS = "data_coverage_fact"


# --- Bölüm 17: override mimarisi (v1'de yalnızca "global" dolu) ---------


@dataclass(frozen=True)
class RecommendationCategoryWeightProfile:
    """
    Bölüm 17 -- `resolve_recommendation_category_weights()`'in dönüş tipi.
    Bölüm 8.3'ün notu: bu ağırlıklar Bölüm 9'daki öncelik hesaplamasında
    KULLANILMAZ -- yalnızca `category_coverage` raporlamasında tie-break
    referansıdır.
    """

    scope: str
    scope_key: "str | None"
    category_weights: "dict[str, Decimal]"


# --- Bölüm 6.1: yardımcı struct'lar ---------------------------------------


@dataclass(frozen=True)
class RecommendationHealthScoreReference:
    health_score_final_score: "Decimal | None"
    health_score_letter_rating: "str | None"
    health_score_status: str
    note_tr: str = (
        "Bu alan yalnızca Financial Health Score'un ÖZETİDİR -- "
        "Recommendation Engine'in öneri metinleri bu alandan DOĞRUDAN "
        "ÜRETİLMEZ, yalnızca bağlam sağlar."
    )


@dataclass(frozen=True)
class RecommendationCreditScoreReference:
    credit_score_final_score: "Decimal | None"
    credit_score_risk_tier: "str | None"
    credit_score_status: str
    note_tr: str = (
        "Bu alan yalnızca Credit Score'un ÖZETİDİR -- öneri metinleri bu "
        "alandan DOĞRUDAN ÜRETİLMEZ, yalnızca bağlam sağlar."
    )


# --- Bölüm 6: RecommendationResult ----------------------------------------


@dataclass(frozen=True)
class RecommendationResult:
    """Bölüm 6 -- `generate_recommendations()`'ın TAM sonucu."""

    status: RecommendationComputationStatus
    recommendations: "tuple[RecommendationItem, ...]"
    financial_recommendation_codes: "tuple[str, ...]"
    banking_readiness_recommendation_codes: "tuple[str, ...]"
    data_quality_recommendation_codes: "tuple[str, ...]"
    category_coverage: "dict[str, Decimal]"
    uncovered_signal_codes: "tuple[str, ...]"
    health_score_reference: RecommendationHealthScoreReference
    credit_score_reference: RecommendationCreditScoreReference
    banking_lens_signals_reference: BankingLensSignals
    data_gap_disclosures: "tuple[DataGapDisclosure, ...]"
    conflict_groups: "tuple[RecommendationConflictGroup, ...]"
    mutually_exclusive_groups: "tuple[RecommendationMutuallyExclusiveGroup, ...]"
    blocked_recommendation_codes: "tuple[str, ...]"
    warnings: "tuple[dict[str, Any], ...]"
    disclaimer_tr: str
    provisional: bool
    decision_support_only: bool
    not_financial_advice: bool
    not_credit_approval: bool
    not_investment_advice: bool
    recommendation_schema_version: str
    recommendation_model_version: str
    health_score_schema_version: str
    health_score_model_version: str
    credit_score_schema_version: str
    credit_score_model_version: str
    benchmark_registry_version: str
    ratio_registry_version: str
    category_weight_profile_used: str
