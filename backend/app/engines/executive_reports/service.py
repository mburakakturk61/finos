"""
Milestone 4.4 (Executive Report Engine) -- Adım 3: `generate_executive_
report()`. Narrative Report Pipeline -- KESİN 17 adım (tasarım dokümanı
Bölüm 17.1 / kullanıcının implementasyon-onay mesajı madde 16).

Presentation-only: bu modül HİÇBİR yeni oran/benchmark/skor/öneri/roll-up
HESAPLAMAZ (`REPORT_ENGINE_PRESENTATION_ONLY`, Bölüm 16). 7 üst motor
fonksiyonu BURADAN ASLA ÇAĞRILMAZ.
"""

import copy
from dataclasses import dataclass
from typing import Any, Callable

from app.engines.common.credit_score_types import CreditScoreResult
from app.engines.common.health_score_types import HealthScoreResult
from app.engines.common.recommendation_types import (
    RECOMMENDATION_DISCLAIMER_TR,
    RecommendationPriority,
    RecommendationResult,
)
from app.engines.common.report_registry import (
    REPORT_EXPECTED_UPSTREAM_MODEL_VERSIONS,
    REPORT_INPUT_COMPATIBILITY,
    REPORT_REGISTRY_COMPATIBILITY_KEYS,
    REPORT_SCHEMA_COMPATIBILITY_KEYS,
    REPORT_SECTION_REGISTRY,
    REPORT_TYPE_LEGAL_PROFILES,
    REPORT_TYPE_REGISTRY,
    REPORT_TYPE_TITLES_TR,
    _is_full_detail,
)
from app.engines.common.report_types import (
    REPORT_MODEL_VERSION,
    REPORT_SCHEMA_VERSION,
    SWOT_BOUNDARY_STATEMENT_TR,
    SWOT_OPPORTUNITIES_UNAVAILABLE_REASON_TR,
    BuildPhase,
    ConfidentialityLevel,
    DetailLevel,
    ExecutiveReportResult,
    FieldInclusionPolicy,
    ReportBlockType,
    ReportCompanyMetadata,
    ReportComputationStatus,
    ReportContentBlock,
    ReportDisclaimerBlock,
    ReportSection,
    ReportSectionCode,
    ReportType,
    SectionSourceMappingEntry,
    SectionUsageDefinition,
    SourceConfidenceEntry,
    SourceCoverageEntry,
    SourceInventoryEntry,
    SwotQuadrant,
    SwotQuadrantItem,
    SwotSectionMetadata,
    UpstreamVersionEntry,
)

SC = ReportSectionCode
FIP = FieldInclusionPolicy


class UnsupportedLocaleError(ValueError):
    pass


# --- Bölüm 12: yalnızca "tr-TR" desteklenir (v1) ---------------------------

SUPPORTED_LOCALES: "tuple[str, ...]" = ("tr-TR",)


# --- Build context (immutable, salt-okunur girdi taşıyıcı) -----------------
# BİLEREK `report_type` İÇERMEZ -- builder fonksiyonları report_type'a
# HİÇBİR ŞEKİLDE erişemez (Bölüm 5.3 / madde 4).


@dataclass(frozen=True)
class _BuildContext:
    balance_sheet_result_json: "dict[str, Any]"
    income_statement_result_json: "dict[str, Any]"
    ratio_result_json: "dict[str, Any]"
    benchmark_result_json: "dict[str, Any]"
    health_score_result: HealthScoreResult
    credit_score_result: CreditScoreResult
    recommendation_result: RecommendationResult
    company_metadata: ReportCompanyMetadata
    reporting_period_label_tr: str


@dataclass(frozen=True)
class _ComplianceContext:
    """
    Compliance builder'lara geçirilen bağlam -- BİLEREK `report_type` İÇERMEZ
    (Bölüm 16.1 madde 6: "report_type builder içine gizli state olarak
    sızmaz"). Compliance section'lar YALNIZCA `included_codes` (bu
    çalıştırmada FİİLEN dahil edilen section kodları) ve önceden hesaplanmış
    confidence/coverage envanterini görür.
    """

    included_codes: "tuple[ReportSectionCode, ...]"
    confidence_inventory: "tuple[SourceConfidenceEntry, ...]"
    coverage_inventory: "tuple[SourceCoverageEntry, ...]"
    missing_confidence_sources: "tuple[str, ...]"
    missing_coverage_sources: "tuple[str, ...]"
    section_source_mapping: "tuple[SectionSourceMappingEntry, ...]"


# --- küçük, paylaşılan içerik-blok yardımcıları -----------------------------


def _kpi(label_tr: str, value: Any, source_field_path: str, source_confidence_ref: "str | None" = None) -> ReportContentBlock:
    return ReportContentBlock(ReportBlockType.KPI_CARD, {"label_tr": label_tr, "value": value}, source_field_path, source_confidence_ref)


def _table(rows: "list[dict[str, Any]]", columns: "tuple[str, ...]", source_field_path: str) -> ReportContentBlock:
    return ReportContentBlock(ReportBlockType.TABLE, {"columns": list(columns), "rows": rows}, source_field_path)


def _bullets(items: "list[Any]", source_field_path: str) -> ReportContentBlock:
    return ReportContentBlock(ReportBlockType.BULLET_LIST, {"items": items}, source_field_path)


def _paragraph(text_tr: str, source_field_path: str) -> ReportContentBlock:
    return ReportContentBlock(ReportBlockType.PARAGRAPH, {"text_tr": text_tr}, source_field_path)


def _find_kpi_value(section: "ReportSection | None", label_tr: str) -> Any:
    if section is None:
        return None
    for block in section.content_blocks:
        if block.block_type == ReportBlockType.KPI_CARD and block.payload.get("label_tr") == label_tr:
            return block.payload.get("value")
    return None


def _table_row_count(section: "ReportSection | None") -> int:
    if section is None:
        return 0
    for block in section.content_blocks:
        if block.block_type == ReportBlockType.TABLE:
            return len(block.payload.get("rows") or [])
    return 0


# --- Faz 1: 13 source_section builder'ı ------------------------------------
# HER builder YALNIZCA (ctx, usage) ALIR -- report_type YOK.


def _b_cover_page(ctx: _BuildContext, usage: SectionUsageDefinition):
    cm = ctx.company_metadata
    text = f"{cm.company_name} -- {ctx.reporting_period_label_tr}"
    return (_paragraph(text, "company_metadata"),), ()


def _b_financial_statements_summary(ctx: _BuildContext, usage: SectionUsageDefinition):
    bs_facts = dict(ctx.balance_sheet_result_json.get("facts") or {})
    is_facts = dict(ctx.income_statement_result_json.get("facts") or {})
    rows = [{"field": k, "value": v, "source": "balance_sheet"} for k, v in bs_facts.items()]
    rows += [{"field": k, "value": v, "source": "income_statement"} for k, v in is_facts.items()]
    if usage.maximum_items is not None:
        rows = rows[: usage.maximum_items]
    block = _table(rows, ("field", "value", "source"), "balance_sheet_result_json.facts / income_statement_result_json.facts")
    return (block,), ()


def _b_ratio_analysis_table(ctx: _BuildContext, usage: SectionUsageDefinition):
    categories = ctx.ratio_result_json.get("categories") or {}
    rows = []
    for cat_name in sorted(categories.keys()):
        ratios = (categories[cat_name] or {}).get("ratios") or {}
        for ratio_key in sorted(ratios.keys()):
            r = ratios[ratio_key] or {}
            row = {"category": cat_name, "ratio_code": ratio_key, "value": r.get("value"), "status": r.get("status")}
            if usage.field_inclusion_policy == FIP.ALL_FIELDS:
                row["reliability"] = r.get("reliability")
            rows.append(row)
    if usage.maximum_items is not None:
        rows = rows[: usage.maximum_items]
    columns = ("category", "ratio_code", "value", "status", "reliability") if usage.field_inclusion_policy == FIP.ALL_FIELDS else ("category", "ratio_code", "value", "status")
    return (_table(rows, columns, "ratio_result_json.categories"),), ()


def _b_benchmark_comparison(ctx: _BuildContext, usage: SectionUsageDefinition):
    categories = ctx.benchmark_result_json.get("categories") or {}
    rows = []
    for cat_name in sorted(categories.keys()):
        ratios = (categories[cat_name] or {}).get("ratios") or {}
        for ratio_key in sorted(ratios.keys()):
            r = ratios[ratio_key] or {}
            row = {"category": cat_name, "ratio_code": ratio_key, "tier": r.get("tier"), "status": r.get("status")}
            if usage.field_inclusion_policy == FIP.ALL_FIELDS:
                row["reliability"] = r.get("reliability")
                row["provisional"] = r.get("provisional")
            rows.append(row)
    if usage.maximum_items is not None:
        rows = rows[: usage.maximum_items]
    columns = ("category", "ratio_code", "tier", "status", "reliability", "provisional") if usage.field_inclusion_policy == FIP.ALL_FIELDS else ("category", "ratio_code", "tier", "status")
    return (_table(rows, columns, "benchmark_result_json.categories"),), ()


def _b_health_score_breakdown(ctx: _BuildContext, usage: SectionUsageDefinition):
    hs = ctx.health_score_result
    blocks = [
        _kpi("Nihai Skor", hs.final_score, "health_score_result.final_score", "health_score"),
        _kpi("Harf Notu", hs.letter_rating, "health_score_result.letter_rating", "health_score"),
    ]
    if usage.field_inclusion_policy == FIP.ALL_FIELDS:
        rows = [
            {"category": cb.category, "raw_score": cb.raw_score, "weight_applied": cb.weight_applied, "coverage_ratio": cb.coverage_ratio}
            for cb in hs.category_breakdown
        ]
        blocks.append(_table(rows, ("category", "raw_score", "weight_applied", "coverage_ratio"), "health_score_result.category_breakdown"))
    return tuple(blocks), tuple(hs.warnings)


def _b_credit_score_breakdown(ctx: _BuildContext, usage: SectionUsageDefinition):
    cs = ctx.credit_score_result
    blocks = [
        _kpi("Nihai Skor", cs.final_score, "credit_score_result.final_score", "credit_score"),
        _kpi("Risk Kademesi", cs.risk_tier, "credit_score_result.risk_tier", "credit_score"),
    ]
    if usage.field_inclusion_policy == FIP.ALL_FIELDS:
        rows = [
            {"category": cb.category, "raw_score": cb.raw_score, "weight_applied": cb.weight_applied, "coverage_ratio": cb.coverage_ratio}
            for cb in cs.category_breakdown
        ]
        blocks.append(_table(rows, ("category", "raw_score", "weight_applied", "coverage_ratio"), "credit_score_result.category_breakdown"))
    return tuple(blocks), tuple(cs.warnings)


def _b_banking_readiness(ctx: _BuildContext, usage: SectionUsageDefinition):
    bls = ctx.credit_score_result.banking_lens_signals
    blocks = [
        _kpi("Maruziyet Duyarlılığı", bls.exposure_sensitivity, "credit_score_result.banking_lens_signals.exposure_sensitivity"),
        _bullets(list(bls.flags), "credit_score_result.banking_lens_signals.flags"),
    ]
    banking_codes = set(ctx.recommendation_result.banking_readiness_recommendation_codes)
    items = [i for i in ctx.recommendation_result.recommendations if i.recommendation_code in banking_codes]
    if usage.maximum_items is not None:
        items = items[: usage.maximum_items]
    rows = [{"recommendation_code": i.recommendation_code, "title_tr": i.title_tr, "priority": i.priority.value} for i in items]
    blocks.append(_table(rows, ("recommendation_code", "title_tr", "priority"), "recommendation_result.banking_readiness_recommendation_codes"))
    return tuple(blocks), ()


def _b_bank_collateral_and_data_gaps(ctx: _BuildContext, usage: SectionUsageDefinition):
    rows = [
        {"gap_code": g.gap_code, "description_tr": g.description_tr, "excluded_from_score": g.excluded_from_score}
        for g in ctx.credit_score_result.data_gap_disclosures
    ]
    if usage.maximum_items is not None:
        rows = rows[: usage.maximum_items]
    return (_table(rows, ("gap_code", "description_tr", "excluded_from_score"), "credit_score_result.data_gap_disclosures"),), ()


def _b_recommendations(ctx: _BuildContext, usage: SectionUsageDefinition):
    items = list(ctx.recommendation_result.recommendations)
    if usage.field_inclusion_policy != FIP.ALL_FIELDS:
        items = [i for i in items if i.priority in (RecommendationPriority.CRITICAL, RecommendationPriority.HIGH, RecommendationPriority.MEDIUM)]
    if usage.maximum_items is not None:
        items = items[: usage.maximum_items]
    rows = []
    for item in items:
        row = {"recommendation_code": item.recommendation_code, "category": item.category.value, "priority": item.priority.value, "title_tr": item.title_tr}
        if usage.field_inclusion_policy == FIP.ALL_FIELDS:
            row["explanation_tr"] = item.explanation_tr
            row["action_steps_tr"] = list(item.action_steps_tr)
            row["confidence"] = item.confidence
            row["disclaimer_tr"] = item.disclaimer_tr
        rows.append(row)
    columns = tuple(rows[0].keys()) if rows else ("recommendation_code", "category", "priority", "title_tr")
    return (_table(rows, columns, "recommendation_result.recommendations"),), tuple(ctx.recommendation_result.warnings)


def _b_board_decision_items(ctx: _BuildContext, usage: SectionUsageDefinition):
    items = list(ctx.recommendation_result.recommendations)
    if usage.field_inclusion_policy != FIP.ALL_FIELDS:
        items = [i for i in items if i.priority in (RecommendationPriority.CRITICAL, RecommendationPriority.HIGH)]
    if usage.maximum_items is not None:
        items = items[: usage.maximum_items]
    rows = [{"recommendation_code": i.recommendation_code, "title_tr": i.title_tr, "priority": i.priority.value, "category": i.category.value} for i in items]
    return (_table(rows, ("recommendation_code", "title_tr", "priority", "category"), "recommendation_result.recommendations"),), ()


def _b_risk_flags(ctx: _BuildContext, usage: SectionUsageDefinition):
    rows = []
    for code in ctx.health_score_result.hard_fails_triggered:
        rows.append({"source": "health_score", "flag_code": code, "severity": "critical"})
    for code in ctx.credit_score_result.hard_fails_triggered:
        rows.append({"source": "credit_score", "flag_code": code, "severity": "critical"})
    for flag in ctx.credit_score_result.banking_lens_signals.flags:
        rows.append({"source": "credit_score_banking_lens", "flag_code": flag, "severity": "informational"})
    for item in ctx.recommendation_result.recommendations:
        if item.priority == RecommendationPriority.CRITICAL:
            rows.append({"source": "recommendation", "flag_code": item.recommendation_code, "severity": "critical"})
    if usage.maximum_items is not None:
        rows = rows[: usage.maximum_items]
    return (_table(rows, ("source", "flag_code", "severity"), "health_score_result / credit_score_result / recommendation_result"),), ()


def _b_investor_kpi_summary(ctx: _BuildContext, usage: SectionUsageDefinition):
    categories = ctx.ratio_result_json.get("categories") or {}
    rows = []
    for cat_name in ("growth", "profitability"):
        ratios = (categories.get(cat_name) or {}).get("ratios") or {}
        for ratio_key in sorted(ratios.keys()):
            r = ratios[ratio_key] or {}
            rows.append({"category": cat_name, "ratio_code": ratio_key, "value": r.get("value"), "status": r.get("status")})
    if usage.maximum_items is not None:
        rows = rows[: usage.maximum_items]
    return (_table(rows, ("category", "ratio_code", "value", "status"), "ratio_result_json.categories[growth|profitability]"),), ()


def _b_period_comparison_analysis(ctx: _BuildContext, usage: SectionUsageDefinition):
    bs_h = dict(ctx.balance_sheet_result_json.get("horizontal_analysis") or {})
    is_h = dict(ctx.income_statement_result_json.get("horizontal_analysis") or {})
    growth_ratios = ((ctx.ratio_result_json.get("categories") or {}).get("growth") or {}).get("ratios") or {}
    rows = [{"field": k, "value": v, "source": "balance_sheet.horizontal_analysis"} for k, v in bs_h.items()]
    rows += [{"field": k, "value": v, "source": "income_statement.horizontal_analysis"} for k, v in is_h.items()]
    for ratio_key in sorted(growth_ratios.keys()):
        rows.append({"field": ratio_key, "value": (growth_ratios[ratio_key] or {}).get("value"), "source": "ratio_result_json.categories.growth"})
    if usage.maximum_items is not None:
        rows = rows[: usage.maximum_items]
    warnings = (
        {
            "code": "SINGLE_PERIOD_COMPARISON_ONLY",
            "note_tr": "Bu bölüm yalnızca TEK önceki döneme göre karşılaştırma sunar; uzun dönem trend/momentum/tahmin/bozulma modeli/istatistiksel eğilim İDDİA ETMEZ.",
        },
    )
    block = _table(rows, ("field", "value", "source"), "balance_sheet_result_json.horizontal_analysis / income_statement_result_json.horizontal_analysis / ratio_result_json.categories.growth")
    return (block,), warnings


SOURCE_BUILDERS: "dict[ReportSectionCode, Callable]" = {
    SC.SEC_COVER_PAGE: _b_cover_page,
    SC.SEC_FINANCIAL_STATEMENTS_SUMMARY: _b_financial_statements_summary,
    SC.SEC_RATIO_ANALYSIS_TABLE: _b_ratio_analysis_table,
    SC.SEC_BENCHMARK_COMPARISON: _b_benchmark_comparison,
    SC.SEC_HEALTH_SCORE_BREAKDOWN: _b_health_score_breakdown,
    SC.SEC_CREDIT_SCORE_BREAKDOWN: _b_credit_score_breakdown,
    SC.SEC_BANKING_READINESS: _b_banking_readiness,
    SC.SEC_BANK_COLLATERAL_AND_DATA_GAPS: _b_bank_collateral_and_data_gaps,
    SC.SEC_RECOMMENDATIONS: _b_recommendations,
    SC.SEC_BOARD_DECISION_ITEMS: _b_board_decision_items,
    SC.SEC_RISK_FLAGS: _b_risk_flags,
    SC.SEC_INVESTOR_KPI_SUMMARY: _b_investor_kpi_summary,
    SC.SEC_PERIOD_COMPARISON_ANALYSIS: _b_period_comparison_analysis,
}


# --- Faz 2: 2 aggregation_section builder'ı --------------------------------
# YALNIZCA (ctx, usage, deps) ALIR -- `deps` o ÇALIŞTIRMADA FİİLEN
# TAMAMLANMIŞ (mevcut) dependency section'larının alt kümesidir (Bölüm 4,
# "aggregation section yalnızca tamamlanmış dependency outputlarını
# okuyabilmeli"). Bir bağımlılık bu raporda hiç dahil edilmediyse
# (opsiyonel ve dışlanmışsa), builder bunu SESSİZCE atlamaz -- bir
# warning ile GÖRÜNÜR kılar.


def _b_executive_summary(ctx: _BuildContext, usage: SectionUsageDefinition, deps: "dict[ReportSectionCode, ReportSection]"):
    warnings = []
    items = []
    hs_section = deps.get(SC.SEC_HEALTH_SCORE_BREAKDOWN)
    cs_section = deps.get(SC.SEC_CREDIT_SCORE_BREAKDOWN)
    rec_section = deps.get(SC.SEC_RECOMMENDATIONS)
    risk_section = deps.get(SC.SEC_RISK_FLAGS)

    for code, section in (
        (SC.SEC_HEALTH_SCORE_BREAKDOWN, hs_section),
        (SC.SEC_CREDIT_SCORE_BREAKDOWN, cs_section),
        (SC.SEC_RECOMMENDATIONS, rec_section),
        (SC.SEC_RISK_FLAGS, risk_section),
    ):
        if section is None:
            warnings.append({"code": "EXECUTIVE_SUMMARY_DEPENDENCY_UNAVAILABLE", "dependency_section_code": code.value})

    if hs_section is not None:
        items.append(f"Finansal Sağlık Skoru: {_find_kpi_value(hs_section, 'Nihai Skor')} ({_find_kpi_value(hs_section, 'Harf Notu')})")
    if cs_section is not None:
        items.append(f"Kredi Skoru: {_find_kpi_value(cs_section, 'Nihai Skor')} ({_find_kpi_value(cs_section, 'Risk Kademesi')})")
    if rec_section is not None:
        items.append(f"Öneri sayısı: {_table_row_count(rec_section)}")
    if risk_section is not None:
        items.append(f"Risk bayrağı sayısı: {_table_row_count(risk_section)}")

    block = _bullets(items, "SEC_HEALTH_SCORE_BREAKDOWN + SEC_CREDIT_SCORE_BREAKDOWN + SEC_RECOMMENDATIONS + SEC_RISK_FLAGS (section outputs)")
    return (block,), tuple(warnings)


def _b_swot(ctx: _BuildContext, usage: SectionUsageDefinition, deps: "dict[ReportSectionCode, ReportSection]"):
    warnings = []
    hs_section = deps.get(SC.SEC_HEALTH_SCORE_BREAKDOWN)
    rec_section = deps.get(SC.SEC_RECOMMENDATIONS)
    if hs_section is None:
        warnings.append({"code": "SWOT_DEPENDENCY_UNAVAILABLE", "dependency_section_code": SC.SEC_HEALTH_SCORE_BREAKDOWN.value})
    if rec_section is None:
        warnings.append({"code": "SWOT_DEPENDENCY_UNAVAILABLE", "dependency_section_code": SC.SEC_RECOMMENDATIONS.value})

    strengths_items = tuple(
        SwotQuadrantItem(
            text_tr=s.get("text_tr", ""), source_engine="health_score",
            source_field_path="health_score_result.strengths", source_code=s.get("ratio_code"),
            provenance_note_tr="Financial Health Score'un strengths alanından DOĞRUDAN kopyalanmıştır.",
        )
        for s in ctx.health_score_result.strengths
    ) if hs_section is not None else ()
    weaknesses_items = tuple(
        SwotQuadrantItem(
            text_tr=w.get("text_tr", ""), source_engine="health_score",
            source_field_path="health_score_result.weaknesses", source_code=w.get("ratio_code"),
            provenance_note_tr="Financial Health Score'un weaknesses alanından DOĞRUDAN kopyalanmıştır.",
        )
        for w in ctx.health_score_result.weaknesses
    ) if hs_section is not None else ()
    threats_items = tuple(
        SwotQuadrantItem(
            text_tr=r.title_tr, source_engine="recommendation",
            source_field_path="recommendation_result.recommendations", source_code=r.recommendation_code,
            provenance_note_tr="Recommendation Engine'in CRITICAL/HIGH öncelikli önerisinden DOĞRUDAN alınmıştır.",
        )
        for r in ctx.recommendation_result.recommendations
        if r.priority in (RecommendationPriority.CRITICAL, RecommendationPriority.HIGH)
    ) if rec_section is not None else ()

    quadrants = (
        SwotQuadrant("strengths", strengths_items, hs_section is not None, None if hs_section is not None else "Kaynak bölüm (SEC_HEALTH_SCORE_BREAKDOWN) bu raporda dahil değildir."),
        SwotQuadrant("weaknesses", weaknesses_items, hs_section is not None, None if hs_section is not None else "Kaynak bölüm (SEC_HEALTH_SCORE_BREAKDOWN) bu raporda dahil değildir."),
        SwotQuadrant("threats", threats_items, rec_section is not None, None if rec_section is not None else "Kaynak bölüm (SEC_RECOMMENDATIONS) bu raporda dahil değildir."),
        SwotQuadrant("opportunities", (), False, SWOT_OPPORTUNITIES_UNAVAILABLE_REASON_TR),
    )
    metadata = SwotSectionMetadata()

    payload = {
        "is_reformatted_source_content": metadata.is_reformatted_source_content,
        "is_independent_strategic_analysis": metadata.is_independent_strategic_analysis,
        "quadrants": [
            {
                "quadrant": q.quadrant,
                "is_available": q.is_available,
                "unavailable_reason_tr": q.unavailable_reason_tr,
                "items": [
                    {"text_tr": i.text_tr, "source_engine": i.source_engine, "source_code": i.source_code}
                    for i in q.items
                ],
            }
            for q in quadrants
        ],
    }
    blocks = (
        _paragraph(metadata.boundary_statement_tr, "swot_section_metadata.boundary_statement_tr"),
        ReportContentBlock(ReportBlockType.BULLET_LIST, payload, "health_score_result.strengths/weaknesses + recommendation_result.recommendations"),
    )
    return blocks, tuple(warnings)


AGGREGATION_BUILDERS: "dict[ReportSectionCode, Callable]" = {
    SC.SEC_EXECUTIVE_SUMMARY: _b_executive_summary,
    SC.SEC_SWOT: _b_swot,
}


# --- Faz 3: 3 compliance_section builder'ı ---------------------------------


def _b_methodology_appendix(ctx: _BuildContext, usage: SectionUsageDefinition, deps: "dict[ReportSectionCode, ReportSection]", cc: _ComplianceContext):
    text = (
        "Bu rapor, Financial Statements/Ratio/Benchmark/Health Score/Credit Score/"
        "Recommendation motorlarının ZATEN hesaplanmış çıktılarının sunum-katmanı "
        "birleşimidir. Report Engine hiçbir yeni oran/skor/öneri/roll-up HESAPLAMAZ; "
        "yalnızca mevcut motor çıktılarını okur ve biçimlendirir."
    )
    section_list = ", ".join(c.value for c in cc.included_codes)
    blocks = (
        _paragraph(text, "methodology"),
        _paragraph(f"Bu raporda dahil edilen bölümler: {section_list}", "included_section_codes"),
    )
    return blocks, ()


def _b_disclaimer_block(ctx: _BuildContext, usage: SectionUsageDefinition, deps: "dict[ReportSectionCode, ReportSection]", cc: _ComplianceContext):
    texts = [
        RECOMMENDATION_DISCLAIMER_TR,
        ctx.health_score_result.rating_disclaimer_tr,
        ctx.credit_score_result.risk_tier_disclaimer_tr,
    ]
    if SC.SEC_BANKING_READINESS in cc.included_codes or SC.SEC_BANK_COLLATERAL_AND_DATA_GAPS in cc.included_codes:
        texts.append(ctx.credit_score_result.banking_lens_signals.disclaimer_tr)
    if SC.SEC_SWOT in cc.included_codes:
        texts.append(SWOT_BOUNDARY_STATEMENT_TR)
    texts.append(
        "Bu rapor bir karar-destek belgesidir; resmi bir mali tablo, kredi onayı veya "
        "yatırım tavsiyesi DEĞİLDİR."
    )
    blocks = tuple(_paragraph(t, "disclaimer") for t in texts if t)
    return blocks, ()


def _b_confidence_and_data_quality(ctx: _BuildContext, usage: SectionUsageDefinition, deps: "dict[ReportSectionCode, ReportSection]", cc: _ComplianceContext):
    conf_rows = [
        {"source_engine": e.source_engine, "confidence_available": e.confidence_available, "confidence_value": e.confidence_value, "reason_code": e.reason_code}
        for e in cc.confidence_inventory
    ]
    cov_rows = [
        {"source_engine": e.source_engine, "coverage_available": e.coverage_available, "coverage_value": e.coverage_value, "reason_code": e.reason_code}
        for e in cc.coverage_inventory
    ]
    mapping_rows = [
        {"section_code": m.section_code.value, "source_engines": list(m.source_engines)}
        for m in cc.section_source_mapping
    ]
    blocks = (
        _table(conf_rows, ("source_engine", "confidence_available", "confidence_value", "reason_code"), "source_confidence_inventory"),
        _table(cov_rows, ("source_engine", "coverage_available", "coverage_value", "reason_code"), "source_coverage_inventory"),
        _bullets(list(cc.missing_confidence_sources), "missing_confidence_sources"),
        _bullets(list(cc.missing_coverage_sources), "missing_coverage_sources"),
        _table(mapping_rows, ("section_code", "source_engines"), "section_source_mapping"),
    )
    return blocks, ()


COMPLIANCE_BUILDERS: "dict[ReportSectionCode, Callable]" = {
    SC.SEC_METHODOLOGY_APPENDIX: _b_methodology_appendix,
    SC.SEC_DISCLAIMER_BLOCK: _b_disclaimer_block,
    SC.SEC_CONFIDENCE_AND_DATA_QUALITY: _b_confidence_and_data_quality,
}


# --- Bölüm 7: presentation-only confidence/coverage envanteri -------------
# YALNIZCA upstream sonuçların KENDİ alanlarını okur -- HİÇBİR roll-up
# HESAPLAMAZ. Yalnızca `health_score`/`credit_score` motor-seviyesinde
# GERÇEK bir confidence/coverage alanı taşır; diğer 5 kaynak (balance_
# sheet/income_statement/financial_ratios/benchmarks/recommendation)
# motor-seviyesinde BÖYLE bir alan TAŞIMAZ (yalnızca oran/öneri BAZINDA
# reliability/confidence vardır) -- bu YÜZDEN `confidence_available=False`
# İLE dürüstçe işaretlenir, SIFIR/ORTALAMA VARSAYILMAZ.

_SOURCE_ENGINES: "tuple[str, ...]" = (
    "balance_sheet", "income_statement", "financial_ratios", "benchmarks",
    "health_score", "credit_score", "recommendation",
)


def _build_confidence_and_coverage_inventory(ctx: _BuildContext, included_codes: "tuple[ReportSectionCode, ...]"):
    used_in: "dict[str, list[ReportSectionCode]]" = {}
    for code in included_codes:
        for engine in REPORT_SECTION_REGISTRY[code].source_engine_codes:
            used_in.setdefault(engine, []).append(code)

    confidence_entries: "list[SourceConfidenceEntry]" = []
    coverage_entries: "list[SourceCoverageEntry]" = []
    missing_conf: "list[str]" = []
    missing_cov: "list[str]" = []

    def _conf(engine, available, value, reliability, reason, warning):
        sections = tuple(used_in.get(engine, ()))
        confidence_entries.append(SourceConfidenceEntry(engine, available, value, reliability, reason, warning, sections))
        if not available:
            missing_conf.append(engine)

    def _cov(engine, available, value, reason, warning):
        sections = tuple(used_in.get(engine, ()))
        coverage_entries.append(SourceCoverageEntry(engine, available, value, reason, warning, sections))
        if not available:
            missing_cov.append(engine)

    _conf("balance_sheet", False, None, None, "NO_RELIABILITY_FIELD_IN_SOURCE_CONTRACT", "horizontal_analysis/facts bir güvenilirlik alanı taşımaz.")
    _cov("balance_sheet", False, None, "NO_RELIABILITY_FIELD_IN_SOURCE_CONTRACT", "horizontal_analysis/facts bir coverage alanı taşımaz.")

    _conf("income_statement", False, None, None, "NO_RELIABILITY_FIELD_IN_SOURCE_CONTRACT", "horizontal_analysis/facts bir güvenilirlik alanı taşımaz.")
    _cov("income_statement", False, None, "NO_RELIABILITY_FIELD_IN_SOURCE_CONTRACT", "horizontal_analysis/facts bir coverage alanı taşımaz.")

    _conf("financial_ratios", False, None, None, "PER_RATIO_RELIABILITY_NOT_ENGINE_LEVEL", "Güvenilirlik yalnızca oran bazında mevcuttur (bkz. SEC_RATIO_ANALYSIS_TABLE); motor seviyesinde TEK bir değer YOKTUR.")
    _cov("financial_ratios", False, None, "PER_RATIO_RELIABILITY_NOT_ENGINE_LEVEL", "Coverage yalnızca oran bazında mevcuttur; motor seviyesinde TEK bir değer YOKTUR.")

    _conf("benchmarks", False, None, None, "PER_RATIO_RELIABILITY_NOT_ENGINE_LEVEL", "Güvenilirlik yalnızca oran bazında mevcuttur (bkz. SEC_BENCHMARK_COMPARISON).")
    _cov("benchmarks", False, None, "PER_RATIO_RELIABILITY_NOT_ENGINE_LEVEL", "Coverage yalnızca oran bazında mevcuttur.")

    hs = ctx.health_score_result
    _conf("health_score", True, hs.confidence_score, None, None, None)
    _cov("health_score", True, hs.data_coverage_ratio, None, None)

    cs = ctx.credit_score_result
    _conf("credit_score", True, cs.confidence_score, None, None, None)
    _cov("credit_score", True, cs.data_coverage_ratio, None, None)

    _conf("recommendation", False, None, None, "RECOMMENDATION_CONFIDENCE_IS_PER_ITEM_NOT_ENGINE_LEVEL", "Her öneri KENDİ confidence/coverage alanını taşır (bkz. SEC_RECOMMENDATIONS); motor seviyesinde roll-up ÜRETİLMEZ.")
    _cov("recommendation", False, None, "RECOMMENDATION_CONFIDENCE_IS_PER_ITEM_NOT_ENGINE_LEVEL", "Her öneri KENDİ coverage alanını taşır.")

    section_source_mapping = tuple(
        SectionSourceMappingEntry(code, tuple(REPORT_SECTION_REGISTRY[code].source_engine_codes)) for code in included_codes
    )
    source_inventory = tuple(
        SourceInventoryEntry(engine, "used" if engine in used_in else "not_used", tuple(used_in.get(engine, ())))
        for engine in _SOURCE_ENGINES
    )
    return tuple(confidence_entries), tuple(coverage_entries), tuple(missing_conf), tuple(missing_cov), section_source_mapping, source_inventory


# --- Bölüm 6: duplicate/overlap warning'leri (registry ZATEN full/full'u
# REDDETMİŞTİR -- burada yalnızca GÖRÜNÜR bir warning ÜRETİLİR) -----------


def _compute_duplicate_warnings(included_usages: "tuple[SectionUsageDefinition, ...]") -> "tuple[dict[str, Any], ...]":
    usage_by_code = {u.section_code: u for u in included_usages}
    domain_sections: "dict[str, list[ReportSectionCode]]" = {}
    for code in usage_by_code:
        for domain in REPORT_SECTION_REGISTRY[code].data_domains:
            domain_sections.setdefault(domain, []).append(code)

    warnings = []
    for domain, codes in domain_sections.items():
        if len(codes) < 2:
            continue
        full_codes = [c for c in codes if _is_full_detail(usage_by_code[c])]
        full_code = full_codes[0] if full_codes else codes[0]
        reference_codes = tuple(c.value for c in codes if c != full_code)
        warnings.append({
            "code": "DUPLICATE_DATA_ACROSS_SECTIONS",
            "data_domain": domain,
            "full_detail_section_code": full_code.value,
            "reference_only_section_codes": reference_codes,
            "note_tr": "Bu veri alanı birden fazla bölümde farklı ayrıntı seviyeleriyle sunulmaktadır; hiçbir veri sessizce silinmemiştir.",
        })
    return tuple(warnings)


# --- Bölüm 4.5: stable topological build order ------------------------------


def _compute_build_order(included_codes: "tuple[ReportSectionCode, ...]") -> "list[ReportSectionCode]":
    def _phase_codes(phase: BuildPhase) -> "list[ReportSectionCode]":
        return sorted((c for c in included_codes if REPORT_SECTION_REGISTRY[c].build_phase == phase), key=lambda c: c.value)

    return _phase_codes(BuildPhase.SOURCE_SECTION) + _phase_codes(BuildPhase.AGGREGATION_SECTION) + _phase_codes(BuildPhase.COMPLIANCE_SECTION)


# --- Bölüm 10: compatibility ------------------------------------------------


def _check_compatibility(ctx: _BuildContext):
    warnings: "list[dict[str, Any]]" = []
    upstream_version_inventory: "list[UpstreamVersionEntry]" = []

    schema_values = {
        "health_score_schema_version": ctx.health_score_result.health_score_schema_version,
        "credit_score_schema_version": ctx.credit_score_result.credit_score_schema_version,
        "recommendation_schema_version": ctx.recommendation_result.recommendation_schema_version,
    }
    registry_values = {
        "ratio_registry_version": ctx.ratio_result_json.get("ratio_registry_version"),
        "benchmark_registry_version": ctx.benchmark_result_json.get("benchmark_registry_version"),
        "balance_sheet_engine_version": ctx.balance_sheet_result_json.get("engine_version"),
        "income_statement_engine_version": ctx.income_statement_result_json.get("engine_version"),
    }
    model_values = {
        "health_score_model_version": ctx.health_score_result.health_score_model_version,
        "credit_score_model_version": ctx.credit_score_result.credit_score_model_version,
        "recommendation_model_version": ctx.recommendation_result.recommendation_model_version,
    }

    engine_of = {
        "health_score_schema_version": "health_score", "credit_score_schema_version": "credit_score",
        "recommendation_schema_version": "recommendation", "ratio_registry_version": "financial_ratios",
        "benchmark_registry_version": "benchmarks", "balance_sheet_engine_version": "balance_sheet",
        "income_statement_engine_version": "income_statement",
    }

    for key in REPORT_SCHEMA_COMPATIBILITY_KEYS:
        value = schema_values[key]
        upstream_version_inventory.append(UpstreamVersionEntry(engine_of[key], value, None))
        if value not in REPORT_INPUT_COMPATIBILITY[key]:
            warnings.append({"code": "SCHEMA_VERSION_UNSUPPORTED", "field": key, "value": value, "supported": REPORT_INPUT_COMPATIBILITY[key]})

    if any(w["code"] == "SCHEMA_VERSION_UNSUPPORTED" for w in warnings):
        return ReportComputationStatus.SCHEMA_INCOMPATIBLE, tuple(warnings), tuple(upstream_version_inventory)

    for key in REPORT_REGISTRY_COMPATIBILITY_KEYS:
        value = registry_values[key]
        upstream_version_inventory.append(UpstreamVersionEntry(engine_of[key], None, value))
        if value not in REPORT_INPUT_COMPATIBILITY[key]:
            warnings.append({"code": "REGISTRY_VERSION_UNSUPPORTED", "field": key, "value": value, "supported": REPORT_INPUT_COMPATIBILITY[key]})

    if any(w["code"] == "REGISTRY_VERSION_UNSUPPORTED" for w in warnings):
        return ReportComputationStatus.VERSION_MISMATCH, tuple(warnings), tuple(upstream_version_inventory)

    for key, expected in REPORT_EXPECTED_UPSTREAM_MODEL_VERSIONS.items():
        value = model_values[key]
        if value != expected:
            warnings.append({"code": "MODEL_VERSION_MISMATCH", "field": key, "value": value, "expected": expected})

    return ReportComputationStatus.COMPUTED, tuple(warnings), tuple(upstream_version_inventory)


# --- Adım 15: disclaimer bloklarının toplanması ----------------------------


def _collect_disclaimer_blocks(sections: "tuple[ReportSection, ...]") -> "tuple[ReportDisclaimerBlock, ...]":
    blocks: "list[ReportDisclaimerBlock]" = []
    for section in sections:
        if section.section_code != SC.SEC_DISCLAIMER_BLOCK:
            continue
        for i, block in enumerate(section.content_blocks):
            if block.block_type == ReportBlockType.PARAGRAPH:
                blocks.append(ReportDisclaimerBlock(f"DISC_{i:02d}", block.payload.get("text_tr", ""), "report_engine"))
    return tuple(blocks)


def _incompatible_result(
    report_type: ReportType, status: ReportComputationStatus, warnings: "tuple[dict[str, Any], ...]",
    upstream_version_inventory: "tuple[UpstreamVersionEntry, ...]", company_metadata: ReportCompanyMetadata,
    reporting_period_label_tr: str, report_id: "str | None", generated_at: "str | None", locale: str,
    currency_display_policy: "str | None",
) -> ExecutiveReportResult:
    legal_profile = REPORT_TYPE_LEGAL_PROFILES[report_type]
    return ExecutiveReportResult(
        status=status, report_type=report_type, report_title_tr=REPORT_TYPE_TITLES_TR[report_type],
        sections=(), included_section_codes=(),
        omitted_section_codes=tuple(u.section_code for u in REPORT_TYPE_REGISTRY[report_type]),
        company_metadata=company_metadata, reporting_period_label_tr=reporting_period_label_tr,
        warnings=warnings, source_inventory=(), source_confidence_inventory=(), source_coverage_inventory=(),
        missing_confidence_sources=(), missing_coverage_sources=(), section_source_mapping=(),
        duplicate_content_warnings=(), disclaimer_blocks=(), provisional=True,
        decision_support_only=True, not_a_statutory_report=True, not_a_credit_approval=True, not_investment_advice=True,
        legal_review_status=legal_profile.legal_review_status, confidentiality_level=legal_profile.confidentiality_level,
        intended_audience=legal_profile.intended_audience, intended_use=legal_profile.intended_use,
        external_distribution_allowed=legal_profile.external_distribution_allowed,
        regulatory_disclaimer_required=legal_profile.regulatory_disclaimer_required,
        contains_sensitive_financial_data=True,
        redaction_required=legal_profile.confidentiality_level != ConfidentialityLevel.INTERNAL,
        source_document_identifiers_included=False, report_id=report_id, generated_at=generated_at, locale=locale,
        currency_display_policy=currency_display_policy, report_schema_version=REPORT_SCHEMA_VERSION,
        report_model_version=REPORT_MODEL_VERSION, upstream_version_inventory=upstream_version_inventory,
    )


# --- Ana orkestratör: generate_executive_report() -- 17 adım ---------------


def generate_executive_report(
    report_type: ReportType,
    balance_sheet_result_json: "dict[str, Any]",
    income_statement_result_json: "dict[str, Any]",
    ratio_result_json: "dict[str, Any]",
    benchmark_result_json: "dict[str, Any]",
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    recommendation_result: RecommendationResult,
    *,
    company_metadata: ReportCompanyMetadata,
    reporting_period_label_tr: str,
    optional_sections: "tuple[ReportSectionCode, ...] | None" = None,
    report_id: "str | None" = None,
    generated_at: "str | None" = None,
    locale: str = "tr-TR",
    currency_display_policy: "str | None" = None,
) -> ExecutiveReportResult:
    # Adım 1: Compatibility validation (bkz. `_check_compatibility` -- aşağıda çağrılır)
    if locale not in SUPPORTED_LOCALES:
        raise UnsupportedLocaleError(f"Desteklenmeyen locale: {locale!r} (yalnızca {SUPPORTED_LOCALES} desteklenir)")

    # Adım 2: Immutable input validation -- read-only invariant kanıtı için ÖNCE/SONRA deep-copy snapshot'ı.
    _bs_before = copy.deepcopy(balance_sheet_result_json)
    _is_before = copy.deepcopy(income_statement_result_json)
    _ratio_before = copy.deepcopy(ratio_result_json)
    _bench_before = copy.deepcopy(benchmark_result_json)

    ctx = _BuildContext(
        balance_sheet_result_json=balance_sheet_result_json,
        income_statement_result_json=income_statement_result_json,
        ratio_result_json=ratio_result_json,
        benchmark_result_json=benchmark_result_json,
        health_score_result=health_score_result,
        credit_score_result=credit_score_result,
        recommendation_result=recommendation_result,
        company_metadata=company_metadata,
        reporting_period_label_tr=reporting_period_label_tr,
    )

    status, compat_warnings, upstream_version_inventory = _check_compatibility(ctx)

    if status == ReportComputationStatus.SCHEMA_INCOMPATIBLE:
        result = _incompatible_result(
            report_type, status, compat_warnings, upstream_version_inventory, company_metadata,
            reporting_period_label_tr, report_id, generated_at, locale, currency_display_policy,
        )
        assert balance_sheet_result_json == _bs_before and income_statement_result_json == _is_before
        assert ratio_result_json == _ratio_before and benchmark_result_json == _bench_before
        return result

    # Adım 3: Report type resolution
    usage_definitions = REPORT_TYPE_REGISTRY[report_type]

    # Adım 4: Section usage resolution (optional_sections kesişimi)
    included_usages = [
        u for u in usage_definitions
        if not u.optional or (optional_sections is not None and u.section_code in optional_sections)
    ]
    included_usages.sort(key=lambda u: u.display_order)

    # Adım 5: Detail-level validation (defense-in-depth -- registry kaydı ZATEN garanti eder)
    for usage in included_usages:
        if usage.detail_level == DetailLevel.DASHBOARD:
            raise ValueError(f"{usage.section_code!r}: narrative report DetailLevel.DASHBOARD KULLANAMAZ")

    included_codes = tuple(u.section_code for u in included_usages)

    if status == ReportComputationStatus.VERSION_MISMATCH:
        allowed = {SC.SEC_DISCLAIMER_BLOCK, SC.SEC_CONFIDENCE_AND_DATA_QUALITY}
        included_usages = [u for u in included_usages if u.section_code in allowed]
        included_codes = tuple(u.section_code for u in included_usages)

    # Adım 6: Overlap/domain validation -- REPORT_TYPE_REGISTRY kaydı BU rapor tipinin TÜM
    # usage_definitions'ı için ZATEN doğrulanmıştır (kayıt anında); bu çalıştırmanın dahil
    # ettiği alt küme, o ÜST kümenin bir alt kümesi olduğu için full/full çakışması YAPISAL
    # OLARAK MÜMKÜN DEĞİLDİR (bir alt küme, üst kümede olmayan yeni bir çakışma ÜRETEMEZ).

    # Adım 7: Dependency graph validation + stable topological order
    build_order = [c for c in _compute_build_order(included_codes) if c in included_codes]

    # Confidence/coverage envanteri -- Bölüm 16.2/16.3 gerekçesiyle burada hesaplanır
    # (SEC_CONFIDENCE_AND_DATA_QUALITY Faz 3'te bu veriyi TÜKETİR; envanterin KENDİSİ
    # yalnızca 7 ham girdinin KENDİ alanlarından türetildiği için Faz 1-3 inşasından
    # BAĞIMSIZDIR -- "Adım 11: Confidence/coverage inventory presentation" bu envanterin
    # ExecutiveReportResult'a NİHAİ OLARAK İŞLENMESİDİR).
    confidence_inventory, coverage_inventory, missing_conf, missing_cov, section_source_mapping, source_inventory = (
        _build_confidence_and_coverage_inventory(ctx, included_codes)
    )
    compliance_context = _ComplianceContext(
        included_codes=included_codes, confidence_inventory=confidence_inventory,
        coverage_inventory=coverage_inventory, missing_confidence_sources=missing_conf,
        missing_coverage_sources=missing_cov, section_source_mapping=section_source_mapping,
    )

    usage_by_code = {u.section_code: u for u in included_usages}
    built: "dict[ReportSectionCode, ReportSection]" = {}
    all_warnings: "list[dict[str, Any]]" = list(compat_warnings)

    for code in build_order:
        definition = REPORT_SECTION_REGISTRY[code]
        usage = usage_by_code[code]

        # Adım 8/9/10: Faz 1/2/3 build
        if definition.build_phase == BuildPhase.SOURCE_SECTION:
            blocks, warns = SOURCE_BUILDERS[code](ctx, usage)
            consumed: "tuple[ReportSectionCode, ...]" = ()
        elif definition.build_phase == BuildPhase.AGGREGATION_SECTION:
            available_deps = {c: built[c] for c in definition.dependency_codes if c in built}
            blocks, warns = AGGREGATION_BUILDERS[code](ctx, usage, available_deps)
            consumed = tuple(available_deps.keys())
        else:
            available_deps = dict(built)  # DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS -- bu ana kadar inşa edilmiş TÜMÜ
            blocks, warns = COMPLIANCE_BUILDERS[code](ctx, usage, available_deps, compliance_context)
            consumed = tuple(available_deps.keys())

        section = ReportSection(
            section_code=code, title_tr=definition.display_name_tr, build_phase=definition.build_phase,
            is_mandatory_for_report_type=not usage.optional, content_blocks=blocks,
            source_engines=definition.source_engine_codes, consumed_section_codes=consumed,
            data_domains=definition.data_domains,
            explainability_note_tr=(
                f"Bu bölüm {', '.join(definition.source_engine_codes)} motorunun çıktısının doğrudan sunumudur."
                if definition.source_engine_codes else
                "Bu bölüm diğer bölümlerin (Faz 1/2) ZATEN inşa edilmiş çıktılarının yeniden biçimlendirilmiş sunumudur."
            ),
            disclaimer_scope="banking" if code in (SC.SEC_BANKING_READINESS, SC.SEC_BANK_COLLATERAL_AND_DATA_GAPS) else "general",
            is_reformatted_source_content=True, is_independent_strategic_analysis=False, warnings=tuple(warns),
        )
        built[code] = section
        all_warnings.extend(warns)

    # Adım 12: Duplicate-content warnings
    duplicate_warnings = _compute_duplicate_warnings(tuple(included_usages))
    all_warnings.extend(duplicate_warnings)

    # Adım 13: Stable ordering (display_order)
    ordered_sections = tuple(built[c] for c in included_codes)

    # Adım 14: Legal/confidentiality metadata
    legal_profile = REPORT_TYPE_LEGAL_PROFILES[report_type]

    # Adım 15: Explainability/provenance -- HER section zaten `explainability_note_tr`/
    # `source_engines`/`consumed_section_codes` taşıyor (yukarıda inşa edildi); burada
    # yalnızca disclaimer bloklarının toplanması YAPILIR.
    disclaimer_blocks = _collect_disclaimer_blocks(ordered_sections)

    omitted_codes = tuple(u.section_code for u in usage_definitions if u.section_code not in included_codes)

    result = ExecutiveReportResult(
        status=status, report_type=report_type, report_title_tr=REPORT_TYPE_TITLES_TR[report_type],
        sections=ordered_sections, included_section_codes=included_codes, omitted_section_codes=omitted_codes,
        company_metadata=company_metadata, reporting_period_label_tr=reporting_period_label_tr,
        warnings=tuple(all_warnings), source_inventory=source_inventory,
        source_confidence_inventory=confidence_inventory, source_coverage_inventory=coverage_inventory,
        missing_confidence_sources=missing_conf, missing_coverage_sources=missing_cov,
        section_source_mapping=section_source_mapping, duplicate_content_warnings=duplicate_warnings,
        disclaimer_blocks=disclaimer_blocks,
        provisional=bool(health_score_result.provisional or credit_score_result.provisional or recommendation_result.provisional),
        decision_support_only=True, not_a_statutory_report=True, not_a_credit_approval=True, not_investment_advice=True,
        legal_review_status=legal_profile.legal_review_status, confidentiality_level=legal_profile.confidentiality_level,
        intended_audience=legal_profile.intended_audience, intended_use=legal_profile.intended_use,
        external_distribution_allowed=legal_profile.external_distribution_allowed,
        regulatory_disclaimer_required=legal_profile.regulatory_disclaimer_required,
        contains_sensitive_financial_data=True,
        redaction_required=legal_profile.confidentiality_level != ConfidentialityLevel.INTERNAL,
        source_document_identifiers_included=False, report_id=report_id, generated_at=generated_at, locale=locale,
        currency_display_policy=currency_display_policy, report_schema_version=REPORT_SCHEMA_VERSION,
        report_model_version=REPORT_MODEL_VERSION, upstream_version_inventory=upstream_version_inventory,
    )

    # Adım 16: Presentation-only invariant kontrolü -- REPORT_ENGINE_PRESENTATION_ONLY
    # (Bölüm 16.1 madde 1): 4 ham JSON girdisi HİÇBİR ADIMDA MUTASYONA UĞRAMADI.
    assert balance_sheet_result_json == _bs_before, "READ-ONLY INVARIANT İHLALİ: balance_sheet_result_json mutasyona uğradı"
    assert income_statement_result_json == _is_before, "READ-ONLY INVARIANT İHLALİ: income_statement_result_json mutasyona uğradı"
    assert ratio_result_json == _ratio_before, "READ-ONLY INVARIANT İHLALİ: ratio_result_json mutasyona uğradı"
    assert benchmark_result_json == _bench_before, "READ-ONLY INVARIANT İHLALİ: benchmark_result_json mutasyona uğradı"

    # Adım 17: ExecutiveReportResult
    return result
