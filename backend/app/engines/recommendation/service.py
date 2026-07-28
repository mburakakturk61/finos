"""
Milestone 4.3F (Recommendation Engine) -- `generate_recommendations()`:
Bölüm 12'nin 20 adımlık KESİN pipeline'ının TAM implementasyonu.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3F_RECOMMENDATION_
ENGINE_DESIGN.md Bölüm 5/6/9/12/13/14/15/16/18/19/20a (son onay turu) +
kullanıcının implementasyon-onay mesajındaki 19 maddelik bağlayıcı
teknik kural seti.

**INVARIANT: RECOMMENDATION_ENGINE_READ_ONLY** (Bölüm 12, HER 20 adımda
geçerli): `ratio_result_json`/`benchmark_result_json`/`health_score_
result`/`credit_score_result` HİÇBİR ADIMDA MUTASYONA UĞRAMAZ;
`RATIO_REGISTRY`/`BENCHMARK_REGISTRY`/`RATIO_SCORE_WEIGHTS`/`CREDIT_
RATIO_SCORE_WEIGHTS`/`RECOMMENDATION_RULES` boyutu/içeriği DEĞİŞMEZ;
`analyze_financial_ratios`/`evaluate_benchmarks`/`compute_financial_
health_score`/`compute_credit_score` HİÇBİRİ İÇERİDEN ÇAĞRILMAZ. Bu
invariant Adım 19'da (`_verify_read_only_invariant`) KANITLANIR.

sqlalchemy/fastapi/pydantic'e SIFIR bağımlı, sıfır API/adapter/DB
persistence -- Bölüm 2.1 ile AYNI disiplin.
"""

import copy
from decimal import Decimal
from typing import Any

from app.engines.common.benchmark_types import BENCHMARK_REGISTRY, BENCHMARK_REGISTRY_VERSION
from app.engines.common.credit_score_registry import CREDIT_RATIO_SCORE_WEIGHTS
from app.engines.common.credit_score_types import CreditScoreResult
from app.engines.common.health_score_registry import RATIO_SCORE_WEIGHTS
from app.engines.common.health_score_types import HealthScoreResult
from app.engines.health_score.service import collect_ratio_signals
from app.engines.common.ratio_formulas import RATIO_REGISTRY, RATIO_REGISTRY_VERSION
from app.engines.common.recommendation_registry import (
    CATEGORY_RATIO_MAP,
    RECOMMENDATION_CONFLICT_PAIRS,
    RECOMMENDATION_INPUT_COMPATIBILITY,
    RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS,
    RECOMMENDATION_RULES,
    evaluate_rule_eligibility,
    resolve_recommendation_category_weights,
)
from app.engines.common.recommendation_types import (
    CATEGORY_COVERAGE_GATE_THRESHOLD,
    COVERAGE_CEILING_HIGH_THRESHOLD,
    COVERAGE_CEILING_HIGH_VALUE,
    COVERAGE_CEILING_LOW_VALUE,
    COVERAGE_CEILING_MID_THRESHOLD,
    COVERAGE_CEILING_MID_VALUE,
    DATA_QUALITY_CONFIDENCE_BASIS,
    DATA_QUALITY_FIXED_CONFIDENCE,
    IMPROVEMENT_DIRECTION_TR,
    LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD,
    PRIORITY_RANK,
    PROVISIONAL_EVIDENCE_CONFIDENCE_CEILING,
    RECOMMENDATION_MODEL_VERSION,
    RECOMMENDATION_SCHEMA_VERSION,
    RELIABILITY_TO_CONFIDENCE_CEILING,
    SEVERITY_RANK,
    CATEGORY_DISPLAY_ORDER,
    RecommendationCategory,
    RecommendationComputationStatus,
    RecommendationConflictGroup,
    RecommendationCreditScoreReference,
    RecommendationDirectionalContext,
    RecommendationHealthScoreReference,
    RecommendationItem,
    RecommendationMutuallyExclusiveGroup,
    RecommendationPriority,
    RecommendationResult,
    RecommendationTriggerSource,
    ResultBucket,
    next_better_tier_name,
)
from app.engines.common.reliability import worse_reliability

_FUNCTIONAL_CATEGORIES: "tuple[RecommendationCategory, ...]" = (
    RecommendationCategory.LIQUIDITY,
    RecommendationCategory.WORKING_CAPITAL,
    RecommendationCategory.LEVERAGE,
    RecommendationCategory.PROFITABILITY,
    RecommendationCategory.ACTIVITY,
    RecommendationCategory.GROWTH,
)


# --- Aşama 1: Upstream schema/version compatibility kontrolü -------------


def _check_input_compatibility(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
) -> "RecommendationComputationStatus | None":
    """`None` dönerse uyumlu -- pipeline DEVAM EDER. Aksi halde durduran status."""

    if (
        health_score_result.health_score_schema_version
        not in RECOMMENDATION_INPUT_COMPATIBILITY["health_score_schema_versions"]
        or credit_score_result.credit_score_schema_version
        not in RECOMMENDATION_INPUT_COMPATIBILITY["credit_score_schema_versions"]
    ):
        return RecommendationComputationStatus.SCHEMA_INCOMPATIBLE

    if (
        ratio_result_json.get("ratio_registry_version")
        not in RECOMMENDATION_INPUT_COMPATIBILITY["ratio_registry_versions"]
        or benchmark_result_json.get("benchmark_registry_version")
        not in RECOMMENDATION_INPUT_COMPATIBILITY["benchmark_registry_versions"]
    ):
        return RecommendationComputationStatus.VERSION_MISMATCH

    return None


# --- Aşama 2: girdileri immutable şekilde doğrula -------------------------


def _validate_inputs(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
) -> None:
    if not isinstance(ratio_result_json, dict):
        raise ValueError("ratio_result_json bir dict olmalı.")
    if not isinstance(benchmark_result_json, dict):
        raise ValueError("benchmark_result_json bir dict olmalı.")
    if not isinstance(health_score_result, HealthScoreResult):
        raise ValueError("health_score_result bir HealthScoreResult örneği olmalı.")
    if not isinstance(credit_score_result, CreditScoreResult):
        raise ValueError("credit_score_result bir CreditScoreResult örneği olmalı.")


# --- Aşama 3-5: context inşası --------------------------------------------


def _build_context(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
) -> "tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, bool]]":
    """
    Aşama 3-5'in BİRLEŞİMİ. `collect_ratio_signals` (Health Score'dan
    REUSE) ile ratio/benchmark birleşimi düzleştirilir; `context` YENİ,
    BAĞIMSIZ bir sözlüktür (girdi nesnelerinin İÇİNE yazmaz).

    NOT (implementasyon gerekliliği, tasarım sapması DEĞİL): Bölüm 12
    Aşama 7'nin `category_coverage` hesaplaması, Aşama 6'nın DATA_QUALITY
    kapsam-boşluğu kurallarının (`category_coverage_below`) eligibility
    değerlendirmesi İÇİN gereklidir -- bu yüzden `category_coverage`
    burada (context inşası sırasında) hesaplanıp `context` içine
    eklenir; GATE'in KENDİSİNİN uygulanması (adayların elenmesi) yine
    Aşama 7-8'de, eligibility'den SONRA gerçekleşir (bkz. `_apply_
    coverage_gate`).
    """

    signals = collect_ratio_signals(ratio_result_json, benchmark_result_json)

    # Benchmark'ın "provisional" bayrağı `collect_ratio_signals`'ın DÜZ
    # çıktısında YOK (yalnızca tier/reliability taşır) -- Bölüm 15.4
    # madde 4'ün confidence modeli için AYRICA, doğrudan `benchmark_
    # result_json`'dan okunur (ikinci bir `collect_ratio_signals` KOPYASI
    # YAZILMAZ, yalnızca TEK bir ek alan okunur).
    provisional_by_ratio: "dict[str, bool]" = {}
    for category_data in (benchmark_result_json.get("categories") or {}).values():
        for ratio_code, ratio_data in (category_data.get("ratios") or {}).items():
            provisional_by_ratio[ratio_code] = bool(ratio_data.get("provisional", True))

    category_coverage = _compute_category_coverage(signals)

    context: "dict[str, Any]" = {
        "signals": signals,
        "health_score_hard_fails": set(health_score_result.hard_fails_triggered),
        "health_score_critical_overrides": set(health_score_result.critical_overrides_applied),
        "credit_score_hard_fails": set(credit_score_result.hard_fails_triggered),
        "credit_score_critical_overrides": set(credit_score_result.critical_overrides_applied),
        "banking_lens_flags": set(credit_score_result.banking_lens_signals.flags),
        "credit_score_data_gaps": set(dg.gap_code for dg in credit_score_result.data_gap_disclosures),
        "health_score_status": health_score_result.status,
        "credit_score_status": credit_score_result.status,
        "category_coverage": category_coverage,
    }
    return context, signals, provisional_by_ratio


def _compute_category_coverage(signals: "dict[str, dict[str, Any]]") -> "dict[str, Decimal]":
    """
    Recommendation Engine'in KENDİ 8-kategorili taksonomisi üzerinden
    HER kategori için coverage -- Health Score'un `compute_overall_data_
    coverage_ratio` YAPISININ KENDİ, kısa bir kopyası (Bölüm 12 Aşama 7).
    """

    per_category_total: "dict[str, int]" = {cat.value: 0 for cat in _FUNCTIONAL_CATEGORIES}
    per_category_evaluated: "dict[str, int]" = {cat.value: 0 for cat in _FUNCTIONAL_CATEGORIES}

    for ratio_code, category_value in CATEGORY_RATIO_MAP.items():
        if category_value not in per_category_total:
            continue
        per_category_total[category_value] += 1
        signal = signals.get(ratio_code)
        if signal is not None and signal.get("benchmark_status") == "evaluated":
            per_category_evaluated[category_value] += 1

    coverage: "dict[str, Decimal]" = {}
    for category in _FUNCTIONAL_CATEGORIES:
        total = per_category_total[category.value]
        evaluated = per_category_evaluated[category.value]
        coverage[category.value] = (
            Decimal(evaluated) / Decimal(total) if total > 0 else Decimal("0")
        )

    # BANKING_READINESS/DATA_QUALITY, ratio-tabanlı coverage gate'inden
    # YAPISAL olarak BAĞIMSIZDIR (`coverage_policy != subject_to_gate`
    # olan TEK kategoriler) -- raporlama tutarlılığı için 1 (tam) atanır.
    coverage[RecommendationCategory.BANKING_READINESS.value] = Decimal("1")
    coverage[RecommendationCategory.DATA_QUALITY.value] = Decimal("1")
    return coverage


def passes_coverage_gate(rule: Any, category_coverage: "dict[str, Decimal]") -> bool:
    """
    Bölüm 12 Aşama 7-8 -- `coverage_policy="subject_to_gate"` olan
    kurallar KENDİ kategorisinin coverage'ı `CATEGORY_COVERAGE_GATE_
    THRESHOLD`'un ALTINDAYSA elenir; `exempt_hard_fail`/`always_
    evaluated` KOŞULSUZ MUAFTIR (Madde 1'in bağlayıcı kararı, ayrı test
    edilebilir bir saf fonksiyon olarak çıkarılmıştır).
    """

    if rule.coverage_policy != "subject_to_gate":
        return True
    return category_coverage.get(rule.category.value, Decimal("0")) >= CATEGORY_COVERAGE_GATE_THRESHOLD


# --- Aşama 6-9: eligibility + coverage gate + aday üretimi ----------------


def _evidence_reliability_and_provisional(
    evidence_rule: Any, signals: "dict[str, dict[str, Any]]", provisional_by_ratio: "dict[str, bool]"
) -> "tuple[str, bool]":
    """Bir `EvidenceRule`'un (TETİKLENMİŞ) reliability/provisional çifti."""

    if evidence_rule.ratio_code is not None:
        signal = signals.get(evidence_rule.ratio_code, {})
        reliability = worse_reliability(
            signal.get("ratio_reliability", "not_calculable"),
            signal.get("benchmark_reliability", "not_calculable"),
        )
        provisional = provisional_by_ratio.get(evidence_rule.ratio_code, True)
        return reliability, provisional

    if evidence_rule.critical_override_ratio_code is not None:
        signal = signals.get(evidence_rule.critical_override_ratio_code, {})
        reliability = worse_reliability(
            signal.get("ratio_reliability", "not_calculable"),
            signal.get("benchmark_reliability", "not_calculable"),
        )
        provisional = provisional_by_ratio.get(evidence_rule.critical_override_ratio_code, True)
        return reliability, provisional

    if evidence_rule.hard_fail_code is not None:
        # Hard-fail, motorun KENDİ hesaplamasından gelen deterministik bir
        # OLGUDUR -- ratio-seviyeli bir "ölçüm" değil, "high" reliability.
        return "high", False

    if evidence_rule.banking_lens_flag is not None:
        # BankingLensSignalRule predicate'i bool/None döner (Credit Score
        # tasarımı) -- item-seviyesinde ayrıştırılmış reliability BURADA
        # taşınmaz, bu yüzden orta bir sabit ("medium") kullanılır.
        return "medium", False

    # category_coverage_below / credit_score_data_gap_code -- DATA_QUALITY
    # kuralları zaten SABİT confidence=1.00 taşır (Bölüm 15.4 madde 8),
    # bu değerler dispatch'te KULLANILMAZ ama tutarlılık için "high" döner.
    return "high", False


def _triggering_evidence_rules(rule: Any, context: "dict[str, Any]") -> "tuple[Any, ...]":
    """
    `trigger_mode` "all" ise TÜM evidence_rules (hepsi zaten True olmalı);
    "any" ise yalnızca GERÇEKTEN True dönen(ler).
    """

    from app.engines.common.recommendation_registry import _evaluate_single_evidence_rule

    if rule.trigger_mode == "all":
        return rule.evidence_rules
    return tuple(er for er in rule.evidence_rules if _evaluate_single_evidence_rule(er, context))


def _build_supporting_evidence_entry(
    evidence_rule: Any,
    signals: "dict[str, dict[str, Any]]",
    reliability: str,
    source: str,
) -> "dict[str, Any]":
    ratio_code = evidence_rule.ratio_code or evidence_rule.critical_override_ratio_code
    if ratio_code is not None:
        signal = signals.get(ratio_code, {})
        ratio_metadata = RATIO_REGISTRY.get(ratio_code)
        return {
            "ratio_code": ratio_code,
            "display_name_tr": ratio_metadata.display_name_tr if ratio_metadata else ratio_code,
            "tier": signal.get("tier"),
            "ratio_value": signal.get("ratio_value"),
            "reliability": reliability,
            "benchmark_status": signal.get("benchmark_status"),
            "source": source,
        }
    if evidence_rule.hard_fail_code is not None:
        return {
            "hard_fail_code": evidence_rule.hard_fail_code,
            "reliability": reliability,
            "source": source,
        }
    if evidence_rule.banking_lens_flag is not None:
        return {
            "banking_lens_flag": evidence_rule.banking_lens_flag,
            "reliability": reliability,
            "source": source,
        }
    if evidence_rule.category_coverage_below is not None:
        return {
            "category_coverage_below": evidence_rule.category_coverage_below.value,
            "reliability": reliability,
            "source": source,
        }
    if evidence_rule.credit_score_data_gap_code is not None:
        return {
            "credit_score_data_gap_code": evidence_rule.credit_score_data_gap_code,
            "reliability": reliability,
            "source": source,
        }
    return {"reliability": reliability, "source": source}


def _trigger_source_for_evidence_rule(evidence_rule: Any, context: "dict[str, Any]") -> str:
    if evidence_rule.hard_fail_code is not None:
        if evidence_rule.hard_fail_code in context["health_score_hard_fails"]:
            return RecommendationTriggerSource.HEALTH_SCORE_HARD_FAIL.value
        return RecommendationTriggerSource.CREDIT_SCORE_HARD_FAIL.value
    if evidence_rule.critical_override_ratio_code is not None:
        if evidence_rule.critical_override_ratio_code in context["health_score_critical_overrides"]:
            return RecommendationTriggerSource.HEALTH_SCORE_CRITICAL_OVERRIDE.value
        return RecommendationTriggerSource.CREDIT_SCORE_CRITICAL_OVERRIDE.value
    if evidence_rule.banking_lens_flag is not None:
        return RecommendationTriggerSource.BANKING_LENS_SIGNAL.value
    if evidence_rule.category_coverage_below is not None or evidence_rule.credit_score_data_gap_code is not None:
        return RecommendationTriggerSource.DATA_QUALITY_GAP.value
    # ratio_code + tier_in -- hangi motorun sinyali olduğu context'ten
    # AYIRT EDİLEMEZ (her iki motor da AYNI signals'ı okur) -- Health
    # Score kaynaklı kabul edilir (v1'in basitleştirici, dürüstçe
    # belgelenmiş kararı).
    return RecommendationTriggerSource.HEALTH_SCORE_WEAK_TIER.value


def _compute_confidence(
    rule: Any,
    triggering_evidence: "tuple[Any, ...]",
    signals: "dict[str, dict[str, Any]]",
    provisional_by_ratio: "dict[str, bool]",
    category_coverage: "dict[str, Decimal]",
) -> "dict[str, Any]":
    """Bölüm 15.4 madde a-h -- TAM confidence modeli, min-ceiling."""

    if rule.category == RecommendationCategory.DATA_QUALITY:
        return {
            "confidence": DATA_QUALITY_FIXED_CONFIDENCE,
            "reliability": "high",
            "confidence_basis": DATA_QUALITY_CONFIDENCE_BASIS,
            "evidence_reliabilities": (),
            "provisional": False,
            "missing_inputs": (),
        }

    evidence_reliabilities: "list[str]" = []
    any_provisional = False
    for evidence_rule in triggering_evidence:
        reliability, provisional = _evidence_reliability_and_provisional(
            evidence_rule, signals, provisional_by_ratio
        )
        evidence_reliabilities.append(reliability)
        any_provisional = any_provisional or provisional

    worst_reliability = "high"
    for reliability in evidence_reliabilities:
        worst_reliability = worse_reliability(worst_reliability, reliability)

    evidence_ceiling = RELIABILITY_TO_CONFIDENCE_CEILING.get(worst_reliability, Decimal("0.00"))
    rule_ceiling = rule.confidence_ceiling
    provisional_ceiling = (
        PROVISIONAL_EVIDENCE_CONFIDENCE_CEILING if any_provisional else Decimal("1.00")
    )

    category_cov = category_coverage.get(rule.category.value, Decimal("0"))
    if category_cov >= COVERAGE_CEILING_HIGH_THRESHOLD:
        coverage_ceiling = COVERAGE_CEILING_HIGH_VALUE
    elif category_cov >= COVERAGE_CEILING_MID_THRESHOLD:
        coverage_ceiling = COVERAGE_CEILING_MID_VALUE
    else:
        coverage_ceiling = COVERAGE_CEILING_LOW_VALUE

    ceilings = {
        "evidence_reliability": evidence_ceiling,
        "rule_confidence_ceiling": rule_ceiling,
        "provisional_evidence": provisional_ceiling,
        "category_coverage": coverage_ceiling,
    }
    confidence_basis = min(ceilings, key=lambda key: ceilings[key])
    final_confidence = min(ceilings.values()).quantize(Decimal("0.01"))

    missing_inputs = tuple(
        sorted(
            {
                (er.ratio_code or er.critical_override_ratio_code)
                for er in triggering_evidence
                if (er.ratio_code or er.critical_override_ratio_code)
                and signals.get(er.ratio_code or er.critical_override_ratio_code, {}).get(
                    "benchmark_status"
                )
                != "evaluated"
            }
        )
    )

    return {
        "confidence": final_confidence,
        "reliability": worst_reliability,
        "confidence_basis": confidence_basis,
        "evidence_reliabilities": tuple(evidence_reliabilities),
        "provisional": any_provisional,
        "missing_inputs": missing_inputs,
    }


def _build_directional_context(
    rule: Any, triggering_evidence: "tuple[Any, ...]", signals: "dict[str, dict[str, Any]]"
) -> "RecommendationDirectionalContext | None":
    """Bölüm 19.2 -- TAMAMEN niteliksel, SIFIR sayısal değer."""

    ratio_evidence = next(
        (er for er in triggering_evidence if er.ratio_code is not None), None
    )
    if ratio_evidence is None:
        return None
    signal = signals.get(ratio_evidence.ratio_code)
    if signal is None or signal.get("tier") is None:
        return None
    benchmark_metadata = BENCHMARK_REGISTRY.get(ratio_evidence.ratio_code)
    if benchmark_metadata is None:
        return None
    ideal_direction = benchmark_metadata.ideal_direction.value
    current_tier = signal["tier"]
    return RecommendationDirectionalContext(
        ratio_code=ratio_evidence.ratio_code,
        current_tier=current_tier,
        ideal_direction=ideal_direction,
        improvement_direction_tr=IMPROVEMENT_DIRECTION_TR.get(ideal_direction, ""),
        next_better_tier_name=next_better_tier_name(current_tier),
    )


def _build_candidate(
    rule: Any,
    context: "dict[str, Any]",
    signals: "dict[str, dict[str, Any]]",
    provisional_by_ratio: "dict[str, bool]",
    category_coverage: "dict[str, Decimal]",
) -> "dict[str, Any]":
    triggering_evidence = _triggering_evidence_rules(rule, context)

    supporting_evidence = []
    triggered_by: "list[str]" = []
    for evidence_rule in triggering_evidence:
        source = _trigger_source_for_evidence_rule(evidence_rule, context)
        reliability, _ = _evidence_reliability_and_provisional(
            evidence_rule, signals, provisional_by_ratio
        )
        supporting_evidence.append(
            _build_supporting_evidence_entry(evidence_rule, signals, reliability, source)
        )
        if source not in triggered_by:
            triggered_by.append(source)

    confidence_data = _compute_confidence(
        rule, triggering_evidence, signals, provisional_by_ratio, category_coverage
    )

    category_cov = category_coverage.get(rule.category.value, Decimal("0"))

    warnings: "list[dict[str, Any]]" = []
    if rule.coverage_policy == "exempt_hard_fail" and category_cov < CATEGORY_COVERAGE_GATE_THRESHOLD:
        warnings.append(
            {
                "code": "LOW_COVERAGE_ON_HARD_FAIL_RECOMMENDATION",
                "message_tr": (
                    "Bu öneri, kendi kategorisinin veri kapsamı düşük olmasına "
                    "rağmen hard-fail muafiyeti nedeniyle üretilmiştir."
                ),
            }
        )
    elif category_cov < LOW_CONFIDENCE_WARNING_COVERAGE_THRESHOLD:
        warnings.append(
            {
                "code": "LOW_CONFIDENCE_ON_LOW_COVERAGE",
                "message_tr": (
                    "Bu kategorideki veri kapsamı sınırlı olduğu için bu "
                    "önerinin güvenilirliği DÜŞÜK olarak işaretlenmiştir."
                ),
            }
        )

    return {
        "recommendation_code": rule.recommendation_code,
        "category": rule.category,
        "result_bucket": rule.result_bucket,
        "severity": rule.severity,
        "title_tr": rule.title_tr,
        "explanation_tr": rule.explanation_tr,
        "action_steps_tr": rule.action_steps_tr,
        "assumptions_tr": rule.assumptions_tr,
        "base_priority": rule.base_priority,
        "priority": rule.base_priority,
        "blocked": False,
        "impact_band": rule.impact_band,
        "difficulty_band": rule.difficulty_band,
        "triggered_by": tuple(triggered_by),
        "related_ratio_codes": rule.related_ratio_codes,
        "supporting_evidence": tuple(supporting_evidence),
        "conflict_group_id": None,
        "conflicting_with": (),
        "mutually_exclusive_group_id": None,
        "merge_group": rule.merge_group,
        "underlying_risk_code": rule.underlying_risk_code,
        "directional_context": _build_directional_context(rule, triggering_evidence, signals),
        "confidence": confidence_data["confidence"],
        "reliability": confidence_data["reliability"],
        "confidence_ceiling": rule.confidence_ceiling,
        "coverage": category_cov,
        "provisional": confidence_data["provisional"],
        "confidence_basis": confidence_data["confidence_basis"],
        "evidence_reliabilities": confidence_data["evidence_reliabilities"],
        "missing_inputs": confidence_data["missing_inputs"],
        "warnings": tuple(warnings),
        "disclaimer_tr": rule.disclaimer_tr,
        "source_recommendation_codes": (rule.recommendation_code,),
        "prerequisite_rules": rule.prerequisite_rules,
        "blocking_rules": rule.blocking_rules,
    }


# --- Aşama 11: duplicate/merge -------------------------------------------


def _merge_candidates(candidates: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """Bölüm 14 -- AYNI, BOŞ-OLMAYAN `merge_group` taşıyan adaylar TEK item'a birleşir."""

    merged: "list[dict[str, Any]]" = []
    by_group: "dict[str, list[dict[str, Any]]]" = {}
    order: "list[str]" = []

    for candidate in candidates:
        group = candidate["merge_group"]
        if group is None:
            merged.append(candidate)
            continue
        if group not in by_group:
            by_group[group] = []
            order.append(group)
        by_group[group].append(candidate)

    for group in order:
        members = by_group[group]
        if len(members) == 1:
            merged.append(members[0])
            continue
        primary = members[0]
        combined_triggered_by = list(primary["triggered_by"])
        combined_related_ratio_codes = list(primary["related_ratio_codes"])
        combined_supporting_evidence = list(primary["supporting_evidence"])
        combined_missing_inputs = set(primary["missing_inputs"])
        combined_warnings = list(primary["warnings"])
        combined_source_codes = list(primary["source_recommendation_codes"])
        best_priority = primary["priority"]
        min_confidence = primary["confidence"]
        disclaimer_scope_general = primary["disclaimer_tr"]

        for other in members[1:]:
            for source in other["triggered_by"]:
                if source not in combined_triggered_by:
                    combined_triggered_by.append(source)
            for code in other["related_ratio_codes"]:
                if code not in combined_related_ratio_codes:
                    combined_related_ratio_codes.append(code)
            combined_supporting_evidence.extend(other["supporting_evidence"])
            combined_missing_inputs.update(other["missing_inputs"])
            combined_warnings.extend(other["warnings"])
            combined_source_codes.extend(other["source_recommendation_codes"])
            if PRIORITY_RANK[other["priority"].value] < PRIORITY_RANK[best_priority.value]:
                best_priority = other["priority"]
            if other["confidence"] < min_confidence:
                min_confidence = other["confidence"]
            if "banking" in other["disclaimer_tr"] or "kredi limiti" in other["disclaimer_tr"]:
                disclaimer_scope_general = other["disclaimer_tr"]

        merged_candidate = dict(primary)
        merged_candidate["triggered_by"] = tuple(combined_triggered_by)
        merged_candidate["related_ratio_codes"] = tuple(combined_related_ratio_codes)
        merged_candidate["supporting_evidence"] = tuple(combined_supporting_evidence)
        merged_candidate["missing_inputs"] = tuple(sorted(combined_missing_inputs))
        merged_candidate["warnings"] = tuple(combined_warnings)
        merged_candidate["source_recommendation_codes"] = tuple(combined_source_codes)
        merged_candidate["priority"] = best_priority
        merged_candidate["base_priority"] = best_priority
        merged_candidate["confidence"] = min_confidence
        merged_candidate["disclaimer_tr"] = disclaimer_scope_general
        merged.append(merged_candidate)

    return merged


# --- Aşama 13: conflict / mutually-exclusive ------------------------------


def _apply_conflicts_and_mutual_exclusion(candidates: "list[dict[str, Any]]") -> "tuple[list[dict[str, Any]], tuple[RecommendationConflictGroup, ...], tuple[RecommendationMutuallyExclusiveGroup, ...]]":
    by_code = {c["recommendation_code"]: c for c in candidates}
    active_conflict_groups: "list[RecommendationConflictGroup]" = []

    for left, right in RECOMMENDATION_CONFLICT_PAIRS:
        if left in by_code and right in by_code:
            group_id = f"CONFLICT_{left}_{right}"
            by_code[left]["conflict_group_id"] = group_id
            by_code[right]["conflict_group_id"] = group_id
            left_conflicting = set(by_code[left]["conflicting_with"])
            left_conflicting.add(right)
            by_code[left]["conflicting_with"] = tuple(sorted(left_conflicting))
            right_conflicting = set(by_code[right]["conflicting_with"])
            right_conflicting.add(left)
            by_code[right]["conflicting_with"] = tuple(sorted(right_conflicting))
            active_conflict_groups.append(
                RecommendationConflictGroup(
                    conflict_group_id=group_id,
                    recommendation_codes=(left, right),
                    explanation_tr=(
                        "Bu iki öneri aynı çalıştırmada birlikte tetiklenmiştir "
                        "ve kısmen zıt aksiyonlar önerebilir."
                    ),
                )
            )

    active_mutually_exclusive_groups: "list[RecommendationMutuallyExclusiveGroup]" = []
    for group in RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS:
        present_codes = tuple(code for code in group.recommendation_codes if code in by_code)
        if len(present_codes) >= 1:
            for code in present_codes:
                by_code[code]["mutually_exclusive_group_id"] = group.mutually_exclusive_group_id
        if len(present_codes) >= 2:
            active_mutually_exclusive_groups.append(group)

    return list(by_code.values()), tuple(active_conflict_groups), tuple(active_mutually_exclusive_groups)


# --- Aşama 14: prerequisite/blocking --------------------------------------


def _apply_prerequisite_blocking(candidates: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    active_codes = {c["recommendation_code"] for c in candidates}
    for candidate in candidates:
        blocking_rules = candidate.get("blocking_rules", ())
        if any(code in active_codes for code in blocking_rules):
            candidate["blocked"] = True

        prerequisite_rules = candidate.get("prerequisite_rules", ())
        if prerequisite_rules and not all(code in active_codes for code in prerequisite_rules):
            warnings = list(candidate["warnings"])
            warnings.append(
                {
                    "code": "PREREQUISITE_NOT_MET",
                    "message_tr": "Bu önerinin ön koşullarından biri veya birden fazlası bu çalıştırmada aktif değil.",
                }
            )
            candidate["warnings"] = tuple(warnings)
    return candidates


# --- Aşama 15: priority escalation ----------------------------------------


def _apply_priority_escalation(candidate: "dict[str, Any]", context: "dict[str, Any]") -> None:
    """Bölüm 9.2 -- `base_priority` registry değeri MUTASYONA UĞRAMAZ (rule'daki
    değer zaten değişmiyor); yalnızca candidate['priority'] (item-seviyesi) bu
    katmanın SONUCUNU taşır."""

    triggered_by = set(candidate["triggered_by"])
    priority = candidate["base_priority"]

    hard_fail_escalated = bool(
        triggered_by
        & {
            RecommendationTriggerSource.HEALTH_SCORE_HARD_FAIL.value,
            RecommendationTriggerSource.CREDIT_SCORE_HARD_FAIL.value,
        }
    )
    critical_override_escalated = bool(
        triggered_by
        & {
            RecommendationTriggerSource.HEALTH_SCORE_CRITICAL_OVERRIDE.value,
            RecommendationTriggerSource.CREDIT_SCORE_CRITICAL_OVERRIDE.value,
        }
    )

    if hard_fail_escalated:
        priority = RecommendationPriority.CRITICAL
    elif critical_override_escalated:
        if PRIORITY_RANK[priority.value] > PRIORITY_RANK[RecommendationPriority.HIGH.value]:
            priority = RecommendationPriority.HIGH
    else:
        severity_is_critical = candidate["severity"].value == "critical"
        confidence_ok = candidate["confidence"] >= Decimal("0.50")
        if severity_is_critical and confidence_ok:
            current_rank = PRIORITY_RANK[priority.value]
            if current_rank > 0:
                nudged_rank = current_rank - 1
                nudged_priority = next(
                    p for p, rank in PRIORITY_RANK.items() if rank == nudged_rank
                )
                priority = RecommendationPriority(nudged_priority)

    candidate["priority"] = priority
    candidate["priority_rank"] = PRIORITY_RANK[priority.value]


# --- Aşama 16: stable deterministic sorting -------------------------------


def _sort_key(candidate: "dict[str, Any]") -> "tuple[int, int, Decimal, int, str]":
    return (
        candidate["priority_rank"],
        SEVERITY_RANK[candidate["severity"].value],
        -candidate["confidence"],
        CATEGORY_DISPLAY_ORDER[candidate["category"].value],
        candidate["recommendation_code"],
    )


# --- Aşama 18: uncovered_signal_codes -------------------------------------


def _compute_uncovered_signal_codes() -> "tuple[str, ...]":
    covered: "set[str]" = set()
    for rule in RECOMMENDATION_RULES:
        covered.update(rule.related_ratio_codes)
    uncovered = sorted(set(CATEGORY_RATIO_MAP.keys()) - covered)
    return tuple(uncovered)


_UNCOVERED_SIGNAL_CODES = _compute_uncovered_signal_codes()


# --- Aşama 19: read-only invariant doğrulaması ----------------------------


def _verify_read_only_invariant(
    ratio_result_json_before: "dict[str, Any]",
    ratio_result_json_after: "dict[str, Any]",
    benchmark_result_json_before: "dict[str, Any]",
    benchmark_result_json_after: "dict[str, Any]",
    ratio_registry_size_before: int,
    benchmark_registry_size_before: int,
    health_score_weights_size_before: int,
    credit_score_weights_size_before: int,
    recommendation_rules_size_before: int,
) -> None:
    if ratio_result_json_before != ratio_result_json_after:
        raise RuntimeError("INVARIANT İHLALİ: ratio_result_json MUTASYONA UĞRADI.")
    if benchmark_result_json_before != benchmark_result_json_after:
        raise RuntimeError("INVARIANT İHLALİ: benchmark_result_json MUTASYONA UĞRADI.")
    if len(RATIO_REGISTRY) != ratio_registry_size_before:
        raise RuntimeError("INVARIANT İHLALİ: RATIO_REGISTRY boyutu DEĞİŞTİ.")
    if len(BENCHMARK_REGISTRY) != benchmark_registry_size_before:
        raise RuntimeError("INVARIANT İHLALİ: BENCHMARK_REGISTRY boyutu DEĞİŞTİ.")
    if len(RATIO_SCORE_WEIGHTS) != health_score_weights_size_before:
        raise RuntimeError("INVARIANT İHLALİ: RATIO_SCORE_WEIGHTS boyutu DEĞİŞTİ.")
    if len(CREDIT_RATIO_SCORE_WEIGHTS) != credit_score_weights_size_before:
        raise RuntimeError("INVARIANT İHLALİ: CREDIT_RATIO_SCORE_WEIGHTS boyutu DEĞİŞTİ.")
    if len(RECOMMENDATION_RULES) != recommendation_rules_size_before:
        raise RuntimeError("INVARIANT İHLALİ: RECOMMENDATION_RULES boyutu DEĞİŞTİ.")


# --- Yardımcı: SCHEMA_INCOMPATIBLE/VERSION_MISMATCH için minimal sonuç ---


def _build_short_circuit_result(
    status: RecommendationComputationStatus,
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    *,
    data_quality_only: bool = False,
    context: "dict[str, Any] | None" = None,
    signals: "dict[str, dict[str, Any]] | None" = None,
    provisional_by_ratio: "dict[str, bool] | None" = None,
) -> RecommendationResult:
    warnings: "list[dict[str, Any]]" = []
    recommendations: "tuple[RecommendationItem, ...]" = ()
    financial_codes: "tuple[str, ...]" = ()
    banking_codes: "tuple[str, ...]" = ()
    data_quality_codes: "tuple[str, ...]" = ()
    category_coverage: "dict[str, Decimal]" = {}

    if status == RecommendationComputationStatus.SCHEMA_INCOMPATIBLE:
        warnings.append(
            {
                "code": "SCHEMA_VERSION_UNSUPPORTED",
                "message_tr": (
                    "Health Score veya Credit Score şema versiyonu bu Recommendation "
                    "Engine sürümü tarafından desteklenmiyor -- hiçbir öneri üretilmedi."
                ),
                "health_score_schema_version": health_score_result.health_score_schema_version,
                "credit_score_schema_version": credit_score_result.credit_score_schema_version,
            }
        )
    elif status == RecommendationComputationStatus.VERSION_MISMATCH and context is not None:
        warnings.append(
            {
                "code": "RATIO_OR_BENCHMARK_VERSION_UNSUPPORTED",
                "message_tr": (
                    "Ratio veya Benchmark registry versiyonu desteklenmiyor -- "
                    "yalnızca DATA_QUALITY önerileri üretildi."
                ),
                "ratio_registry_version": ratio_result_json.get("ratio_registry_version"),
                "benchmark_registry_version": benchmark_result_json.get("benchmark_registry_version"),
            }
        )
        category_coverage = context["category_coverage"]
        dq_candidates = []
        for rule in RECOMMENDATION_RULES:
            if rule.category != RecommendationCategory.DATA_QUALITY:
                continue
            if not evaluate_rule_eligibility(rule, context):
                continue
            candidate = _build_candidate(rule, context, signals, provisional_by_ratio, category_coverage)
            candidate["priority_rank"] = PRIORITY_RANK[candidate["priority"].value]
            dq_candidates.append(candidate)
        dq_candidates.sort(key=_sort_key)
        recommendations = tuple(_candidate_to_item(c) for c in dq_candidates)
        data_quality_codes = tuple(c["recommendation_code"] for c in dq_candidates)

    return RecommendationResult(
        status=status,
        recommendations=recommendations,
        financial_recommendation_codes=financial_codes,
        banking_readiness_recommendation_codes=banking_codes,
        data_quality_recommendation_codes=data_quality_codes,
        category_coverage=category_coverage,
        uncovered_signal_codes=_UNCOVERED_SIGNAL_CODES,
        health_score_reference=RecommendationHealthScoreReference(
            health_score_final_score=health_score_result.final_score,
            health_score_letter_rating=health_score_result.letter_rating,
            health_score_status=health_score_result.status.value,
        ),
        credit_score_reference=RecommendationCreditScoreReference(
            credit_score_final_score=credit_score_result.final_score,
            credit_score_risk_tier=credit_score_result.risk_tier,
            credit_score_status=credit_score_result.status.value,
        ),
        banking_lens_signals_reference=credit_score_result.banking_lens_signals,
        data_gap_disclosures=credit_score_result.data_gap_disclosures,
        conflict_groups=(),
        mutually_exclusive_groups=(),
        blocked_recommendation_codes=(),
        warnings=tuple(warnings),
        disclaimer_tr="",
        provisional=True,
        decision_support_only=True,
        not_financial_advice=True,
        not_credit_approval=True,
        not_investment_advice=True,
        recommendation_schema_version=RECOMMENDATION_SCHEMA_VERSION,
        recommendation_model_version=RECOMMENDATION_MODEL_VERSION,
        health_score_schema_version=health_score_result.health_score_schema_version,
        health_score_model_version=health_score_result.health_score_model_version,
        credit_score_schema_version=credit_score_result.credit_score_schema_version,
        credit_score_model_version=credit_score_result.credit_score_model_version,
        benchmark_registry_version=benchmark_result_json.get("benchmark_registry_version", ""),
        ratio_registry_version=ratio_result_json.get("ratio_registry_version", ""),
        category_weight_profile_used="global",
    )


def _candidate_to_item(candidate: "dict[str, Any]") -> RecommendationItem:
    return RecommendationItem(
        recommendation_code=candidate["recommendation_code"],
        category=candidate["category"],
        result_bucket=candidate["result_bucket"],
        severity=candidate["severity"],
        title_tr=candidate["title_tr"],
        explanation_tr=candidate["explanation_tr"],
        action_steps_tr=candidate["action_steps_tr"],
        assumptions_tr=candidate["assumptions_tr"],
        priority=candidate["priority"],
        priority_rank=candidate["priority_rank"],
        blocked=candidate["blocked"],
        impact_band=candidate["impact_band"],
        difficulty_band=candidate["difficulty_band"],
        triggered_by=candidate["triggered_by"],
        related_ratio_codes=candidate["related_ratio_codes"],
        supporting_evidence=candidate["supporting_evidence"],
        conflict_group_id=candidate["conflict_group_id"],
        conflicting_with=candidate["conflicting_with"],
        mutually_exclusive_group_id=candidate["mutually_exclusive_group_id"],
        merge_group=candidate["merge_group"],
        underlying_risk_code=candidate["underlying_risk_code"],
        directional_context=candidate["directional_context"],
        confidence=candidate["confidence"],
        reliability=candidate["reliability"],
        confidence_ceiling=candidate["confidence_ceiling"],
        coverage=candidate["coverage"],
        provisional=candidate["provisional"],
        confidence_basis=candidate["confidence_basis"],
        evidence_reliabilities=candidate["evidence_reliabilities"],
        missing_inputs=candidate["missing_inputs"],
        warnings=candidate["warnings"],
        disclaimer_tr=candidate["disclaimer_tr"],
    )


# --- Ana orkestrasyon: generate_recommendations() -------------------------


def generate_recommendations(
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
    tenant_id: "str | None" = None,
) -> RecommendationResult:
    """Bölüm 5.1/12 -- Bölüm 12'nin 20 adımlık KESİN pipeline'ının orkestrasyonu."""

    # Aşama 2
    _validate_inputs(ratio_result_json, benchmark_result_json, health_score_result, credit_score_result)

    # Read-only invariant için "önce" anlık görüntüleri.
    ratio_result_json_before = copy.deepcopy(ratio_result_json)
    benchmark_result_json_before = copy.deepcopy(benchmark_result_json)
    ratio_registry_size_before = len(RATIO_REGISTRY)
    benchmark_registry_size_before = len(BENCHMARK_REGISTRY)
    health_score_weights_size_before = len(RATIO_SCORE_WEIGHTS)
    credit_score_weights_size_before = len(CREDIT_RATIO_SCORE_WEIGHTS)
    recommendation_rules_size_before = len(RECOMMENDATION_RULES)

    # Aşama 1
    compatibility_status = _check_input_compatibility(
        ratio_result_json, benchmark_result_json, health_score_result, credit_score_result
    )

    if compatibility_status == RecommendationComputationStatus.SCHEMA_INCOMPATIBLE:
        result = _build_short_circuit_result(
            RecommendationComputationStatus.SCHEMA_INCOMPATIBLE,
            ratio_result_json, benchmark_result_json, health_score_result, credit_score_result,
        )
        _verify_read_only_invariant(
            ratio_result_json_before, ratio_result_json,
            benchmark_result_json_before, benchmark_result_json,
            ratio_registry_size_before, benchmark_registry_size_before,
            health_score_weights_size_before, credit_score_weights_size_before,
            recommendation_rules_size_before,
        )
        return result

    # Aşama 3-5 (+ Aşama 7'nin coverage sayılarının ÖNDEN hesaplanması --
    # implementasyon gerekliliği, yukarıdaki docstring'te açıklanmıştır)
    context, signals, provisional_by_ratio = _build_context(
        ratio_result_json, benchmark_result_json, health_score_result, credit_score_result
    )
    category_coverage = context["category_coverage"]

    if compatibility_status == RecommendationComputationStatus.VERSION_MISMATCH:
        result = _build_short_circuit_result(
            RecommendationComputationStatus.VERSION_MISMATCH,
            ratio_result_json, benchmark_result_json, health_score_result, credit_score_result,
            context=context, signals=signals, provisional_by_ratio=provisional_by_ratio,
        )
        _verify_read_only_invariant(
            ratio_result_json_before, ratio_result_json,
            benchmark_result_json_before, benchmark_result_json,
            ratio_registry_size_before, benchmark_registry_size_before,
            health_score_weights_size_before, credit_score_weights_size_before,
            recommendation_rules_size_before,
        )
        return result

    # Aşama 6-9: eligibility + coverage gate (+ hard-fail istisnası) + aday üretimi
    candidates: "list[dict[str, Any]]" = []
    for rule in RECOMMENDATION_RULES:
        if not evaluate_rule_eligibility(rule, context):
            continue
        if not passes_coverage_gate(rule, category_coverage):
            continue
        # exempt_hard_fail / always_evaluated: gate'ten KOŞULSUZ MUAF.
        candidates.append(
            _build_candidate(rule, context, signals, provisional_by_ratio, category_coverage)
        )

    # Aşama 11
    candidates = _merge_candidates(candidates)

    # Aşama 12 -- yalnızca explainability amaçlı, `supporting_evidence`
    # içindeki `source` alanı ile ZATEN görünür (Bölüm 12 Aşama 12 notu),
    # AYRI bir veri mutasyonu GEREKMEZ.

    # Aşama 13
    candidates, active_conflict_groups, active_mutually_exclusive_groups = (
        _apply_conflicts_and_mutual_exclusion(candidates)
    )

    # Aşama 14
    candidates = _apply_prerequisite_blocking(candidates)

    # Aşama 15
    for candidate in candidates:
        _apply_priority_escalation(candidate, context)

    # Aşama 16
    candidates.sort(key=_sort_key)

    # Aşama 17
    financial_codes = tuple(
        c["recommendation_code"] for c in candidates if c["result_bucket"] == ResultBucket.FINANCIAL
    )
    banking_codes = tuple(
        c["recommendation_code"] for c in candidates if c["result_bucket"] == ResultBucket.BANKING_READINESS
    )
    data_quality_codes = tuple(
        c["recommendation_code"] for c in candidates if c["result_bucket"] == ResultBucket.DATA_QUALITY
    )
    blocked_codes = tuple(c["recommendation_code"] for c in candidates if c["blocked"])

    # Aşama 18
    warnings: "list[dict[str, Any]]" = []
    for category in _FUNCTIONAL_CATEGORIES:
        if category_coverage.get(category.value, Decimal("0")) < CATEGORY_COVERAGE_GATE_THRESHOLD:
            warnings.append(
                {
                    "code": "CATEGORY_INSUFFICIENT_DATA",
                    "message_tr": f"'{category.value}' kategorisinde veri kapsamı yetersiz.",
                    "category": category.value,
                }
            )
    if active_conflict_groups:
        warnings.append(
            {
                "code": "CONFLICTING_RECOMMENDATIONS",
                "message_tr": "Bu çalıştırmada birbiriyle çakışan öneriler tespit edildi.",
            }
        )
    if (
        health_score_result.health_score_model_version != "1.0.0"
        or credit_score_result.credit_score_model_version != "1.0.0"
    ):
        warnings.append(
            {
                "code": "MODEL_VERSION_MISMATCH",
                "message_tr": "Health/Credit Score model versiyonu bu Recommendation Engine sürümünden farklı.",
            }
        )

    items = tuple(_candidate_to_item(c) for c in candidates)

    if len(items) == 0:
        overall_coverage = (
            max(category_coverage.get(cat.value, Decimal("0")) for cat in _FUNCTIONAL_CATEGORIES)
            if category_coverage
            else Decimal("0")
        )
        status = (
            RecommendationComputationStatus.INSUFFICIENT_DATA
            if overall_coverage < CATEGORY_COVERAGE_GATE_THRESHOLD
            else RecommendationComputationStatus.NO_RECOMMENDATIONS_TRIGGERED
        )
    else:
        status = RecommendationComputationStatus.COMPUTED

    # Aşama 19
    _verify_read_only_invariant(
        ratio_result_json_before, ratio_result_json,
        benchmark_result_json_before, benchmark_result_json,
        ratio_registry_size_before, benchmark_registry_size_before,
        health_score_weights_size_before, credit_score_weights_size_before,
        recommendation_rules_size_before,
    )

    # Aşama 20
    return RecommendationResult(
        status=status,
        recommendations=items,
        financial_recommendation_codes=financial_codes,
        banking_readiness_recommendation_codes=banking_codes,
        data_quality_recommendation_codes=data_quality_codes,
        category_coverage=category_coverage,
        uncovered_signal_codes=_UNCOVERED_SIGNAL_CODES,
        health_score_reference=RecommendationHealthScoreReference(
            health_score_final_score=health_score_result.final_score,
            health_score_letter_rating=health_score_result.letter_rating,
            health_score_status=health_score_result.status.value,
        ),
        credit_score_reference=RecommendationCreditScoreReference(
            credit_score_final_score=credit_score_result.final_score,
            credit_score_risk_tier=credit_score_result.risk_tier,
            credit_score_status=credit_score_result.status.value,
        ),
        banking_lens_signals_reference=credit_score_result.banking_lens_signals,
        data_gap_disclosures=credit_score_result.data_gap_disclosures,
        conflict_groups=active_conflict_groups,
        mutually_exclusive_groups=active_mutually_exclusive_groups,
        blocked_recommendation_codes=blocked_codes,
        warnings=tuple(warnings),
        disclaimer_tr=(
            "Bu sonuçlar platformun içsel, heuristik göstergelerine dayanır -- "
            "profesyonel mali/hukuki/vergi danışmanlığı YERİNE GEÇMEZ."
        ),
        provisional=True,
        decision_support_only=True,
        not_financial_advice=True,
        not_credit_approval=True,
        not_investment_advice=True,
        recommendation_schema_version=RECOMMENDATION_SCHEMA_VERSION,
        recommendation_model_version=RECOMMENDATION_MODEL_VERSION,
        health_score_schema_version=health_score_result.health_score_schema_version,
        health_score_model_version=health_score_result.health_score_model_version,
        credit_score_schema_version=credit_score_result.credit_score_schema_version,
        credit_score_model_version=credit_score_result.credit_score_model_version,
        benchmark_registry_version=benchmark_result_json.get("benchmark_registry_version", ""),
        ratio_registry_version=ratio_result_json.get("ratio_registry_version", ""),
        category_weight_profile_used=resolve_recommendation_category_weights(
            industry_code=industry_code,
            company_size_bucket=company_size_bucket,
            tenant_id=tenant_id,
        ).scope,
    )
