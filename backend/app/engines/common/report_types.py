"""
Milestone 4.4 (Executive Report Engine) -- Adım 1: temel veri modeli,
enum'lar, sabitler.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_4_EXECUTIVE_REPORT_
ENGINE_DESIGN.md (3. tur/son karar turu, Bölüm 14 "Onaylanmış Kararlar" +
Bölüm 19 "Revizyon Raporu" + kullanıcının implementasyon-onay mesajındaki
21 maddelik bağlayıcı teknik kural seti).

Bu modül `app/engines/common/recommendation_types.py`'nin (4.3F) AYNI
disipliniyle yazılmıştır: eval/exec/dinamik expression YASAK, kapalı bir
dataclass/enum kümesi, sqlalchemy/fastapi/pydantic'e SIFIR bağımlı.

**Bağlayıcı sınır:** Bu modül HİÇBİR finansal hesaplama İÇERMEZ -- yalnızca
Executive Report Engine'in SUNUM sözleşmesini (Narrative Report'a özgü
tipler) tanımlar. Dashboard (`dashboard_types.py`) ve Render Contract
(`render_contract_types.py`) TAMAMEN AYRI modüllerdir (Bölüm 2/11.3).
"""

from dataclasses import dataclass
from decimal import Decimal
import enum
from typing import Any


# --- Versiyon eksenleri ----------------------------------------------------

REPORT_SCHEMA_VERSION = "1.0.0"
REPORT_MODEL_VERSION = "1.0.0"


# --- Bölüm 10: nihai hesaplama durumu (3 değer) -----------------------------


class ReportComputationStatus(str, enum.Enum):
    """
    Bölüm 10.2 -- merkezi immutable compatibility policy'nin 3 katmanlı
    davranışının doğrudan karşılığı.

    COMPUTED: şema+registry uyumlu, üretim normal tamamlandı (yalnızca
        model-version farkı varsa bir MODEL_VERSION_MISMATCH warning'i
        eklenir, status YİNE COMPUTED'DIR).
    SCHEMA_INCOMPATIBLE: bir üst motorun *_schema_version'ı desteklenmiyor
        -- `sections=()`, yalnızca warnings + upstream_version_inventory.
    VERSION_MISMATCH: şema okunabilir ama *_registry_version desteklenmiyor
        -- içerik varsayılan olarak bastırılır, yalnızca uyumluluk-ilgili
        compliance section'lar üretilir.
    """

    COMPUTED = "computed"
    SCHEMA_INCOMPATIBLE = "schema_incompatible"
    VERSION_MISMATCH = "version_mismatch"


# --- Bölüm 4.1: BuildPhase -- KAPALI, 3 değerli (Madde 3/7) -----------------


class BuildPhase(str, enum.Enum):
    SOURCE_SECTION = "source_section"
    AGGREGATION_SECTION = "aggregation_section"
    COMPLIANCE_SECTION = "compliance_section"


# --- Bölüm 5.1: DetailLevel -- KAPALI, 4 değerli ----------------------------


class DetailLevel(str, enum.Enum):
    FULL = "full"
    SUMMARY = "summary"
    COMPACT = "compact"
    DASHBOARD = "dashboard"  # narrative report'larda KULLANILMASI YASAK (Bölüm 5.1)


class FieldInclusionPolicy(str, enum.Enum):
    ALL_FIELDS = "all_fields"
    KEY_FIELDS_ONLY = "key_fields_only"
    HEADLINE_ONLY = "headline_only"


class TableDensity(str, enum.Enum):
    FULL = "full"
    TOP_N = "top_n"
    SUMMARY_ROW_ONLY = "summary_row_only"


# --- Render Contract ile PAYLAŞILAN kapalı block tipi (Bölüm 12.2) --------


class ReportBlockType(str, enum.Enum):
    KPI_CARD = "kpi_card"
    TABLE = "table"
    BULLET_LIST = "bullet_list"
    PARAGRAPH = "paragraph"
    CHART_DATA = "chart_data"
    BADGE = "badge"


# --- Bölüm 9.1: hukuki/gizlilik enum'ları -----------------------------------


class LegalReviewStatus(str, enum.Enum):
    NOT_REVIEWED = "not_reviewed"
    INTERNAL_USE_ONLY = "internal_use_only"
    LEGAL_REVIEW_REQUIRED = "legal_review_required"
    APPROVED = "approved"


class ConfidentialityLevel(str, enum.Enum):
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


# --- Bölüm 4.3: dependency wildcard (yalnızca compliance_section) ----------


class DependencyScope(str, enum.Enum):
    ALL_INCLUDED_UPSTREAM_SECTIONS = "all_included_upstream_sections"


# --- Bölüm 15.3: 18 kanonik section kodu -- KAPALI, KESİN -------------------


class ReportSectionCode(str, enum.Enum):
    SEC_COVER_PAGE = "SEC_COVER_PAGE"
    SEC_FINANCIAL_STATEMENTS_SUMMARY = "SEC_FINANCIAL_STATEMENTS_SUMMARY"
    SEC_RATIO_ANALYSIS_TABLE = "SEC_RATIO_ANALYSIS_TABLE"
    SEC_BENCHMARK_COMPARISON = "SEC_BENCHMARK_COMPARISON"
    SEC_HEALTH_SCORE_BREAKDOWN = "SEC_HEALTH_SCORE_BREAKDOWN"
    SEC_CREDIT_SCORE_BREAKDOWN = "SEC_CREDIT_SCORE_BREAKDOWN"
    SEC_BANKING_READINESS = "SEC_BANKING_READINESS"
    SEC_BANK_COLLATERAL_AND_DATA_GAPS = "SEC_BANK_COLLATERAL_AND_DATA_GAPS"
    SEC_RECOMMENDATIONS = "SEC_RECOMMENDATIONS"
    SEC_BOARD_DECISION_ITEMS = "SEC_BOARD_DECISION_ITEMS"
    SEC_RISK_FLAGS = "SEC_RISK_FLAGS"
    SEC_INVESTOR_KPI_SUMMARY = "SEC_INVESTOR_KPI_SUMMARY"
    SEC_PERIOD_COMPARISON_ANALYSIS = "SEC_PERIOD_COMPARISON_ANALYSIS"
    SEC_EXECUTIVE_SUMMARY = "SEC_EXECUTIVE_SUMMARY"
    SEC_SWOT = "SEC_SWOT"
    SEC_METHODOLOGY_APPENDIX = "SEC_METHODOLOGY_APPENDIX"
    SEC_DISCLAIMER_BLOCK = "SEC_DISCLAIMER_BLOCK"
    SEC_CONFIDENCE_AND_DATA_QUALITY = "SEC_CONFIDENCE_AND_DATA_QUALITY"


# --- Bölüm 1.1: 7 narrative ReportType -- KAPALI, KESİN (Madde 1) ----------


class ReportType(str, enum.Enum):
    CFO_EXECUTIVE_REPORT = "cfo_executive_report"
    BANK_CREDIT_ALLOCATION_REPORT = "bank_credit_allocation_report"
    BOARD_OF_DIRECTORS_REPORT = "board_of_directors_report"
    INVESTOR_REPORT = "investor_report"
    MANAGEMENT_SUMMARY = "management_summary"
    SWOT_REPORT = "swot_report"
    PERIOD_COMPARISON_REPORT = "period_comparison_report"


# --- Bölüm 4: section builder stratejisi -- KAPALI, deklaratif dispatch ---


class ReportSectionBuilderStrategy(str, enum.Enum):
    """
    Her section KENDİ, ayrı bir pure Python builder fonksiyonuna sahiptir
    (Recommendation Engine'in `TRIGGER_STRATEGY_FUNCTIONS` dispatch deseni
    ile AYNI disiplin) -- eval/exec/dinamik kod YOKTUR. Bu enum yalnızca
    registry kaydının HANGİ builder'a bağlı olduğunu KAYIT-ANI doğrulamak
    içindir.
    """

    COVER_PAGE = "cover_page"
    FINANCIAL_STATEMENTS_SUMMARY = "financial_statements_summary"
    RATIO_ANALYSIS_TABLE = "ratio_analysis_table"
    BENCHMARK_COMPARISON = "benchmark_comparison"
    HEALTH_SCORE_BREAKDOWN = "health_score_breakdown"
    CREDIT_SCORE_BREAKDOWN = "credit_score_breakdown"
    BANKING_READINESS = "banking_readiness"
    BANK_COLLATERAL_AND_DATA_GAPS = "bank_collateral_and_data_gaps"
    RECOMMENDATIONS = "recommendations"
    BOARD_DECISION_ITEMS = "board_decision_items"
    RISK_FLAGS = "risk_flags"
    INVESTOR_KPI_SUMMARY = "investor_kpi_summary"
    PERIOD_COMPARISON_ANALYSIS = "period_comparison_analysis"
    EXECUTIVE_SUMMARY = "executive_summary"
    SWOT = "swot"
    METHODOLOGY_APPENDIX = "methodology_appendix"
    DISCLAIMER_BLOCK = "disclaimer_block"
    CONFIDENCE_AND_DATA_QUALITY = "confidence_and_data_quality"


# --- Bölüm 4.2/15.3: section TANIM sözleşmesi (registry kaydı) -------------


@dataclass(frozen=True)
class ReportSectionDefinition:
    """
    Kullanıcının implementasyon-onay mesajı madde 3'ün BİREBİR 13 alanı.
    `dependency_codes`/`consumes_section_outputs`, SOURCE_SECTION için
    HER ZAMAN `()`; AGGREGATION_SECTION için SABİT bir `tuple[Report
    SectionCode,...]`; COMPLIANCE_SECTION için `DependencyScope.ALL_
    INCLUDED_UPSTREAM_SECTIONS` (Bölüm 4.3).
    """

    section_code: ReportSectionCode
    display_name_tr: str
    build_phase: BuildPhase
    dependency_codes: "tuple[ReportSectionCode, ...] | DependencyScope"
    consumes_section_outputs: "tuple[ReportSectionCode, ...] | DependencyScope"
    data_domains: "tuple[str, ...]"
    overlaps_with: "tuple[ReportSectionCode, ...]"
    primary_section_for_domain: "dict[str, ReportSectionCode]"
    builder_strategy: ReportSectionBuilderStrategy
    source_engine_codes: "tuple[str, ...]"
    model_version_introduced: str
    deprecated_since: "str | None"
    replacement_section_code: "ReportSectionCode | None"


# --- Bölüm 5.2: SectionUsageDefinition -- KESİN 10 alan ---------------------


@dataclass(frozen=True)
class SectionUsageDefinition:
    section_code: ReportSectionCode
    detail_level: DetailLevel
    field_inclusion_policy: FieldInclusionPolicy
    maximum_items: "int | None"
    table_density: "TableDensity | None"
    include_provenance: bool
    include_confidence: bool
    include_disclaimer: bool
    display_order: int
    optional: bool


# --- Bölüm 7.4/13/14: küçük, paylaşılan value object'ler -------------------


@dataclass(frozen=True)
class ReportCompanyMetadata:
    company_name: str
    industry_label_tr: "str | None" = None
    company_size_label_tr: "str | None" = None
    fiscal_year_label_tr: "str | None" = None
    tax_id_masked: "str | None" = None


@dataclass(frozen=True)
class ReportDisclaimerBlock:
    disclaimer_code: str
    text_tr: str
    source_engine: str


@dataclass(frozen=True)
class ReportContentBlock:
    block_type: ReportBlockType
    payload: "dict[str, Any]"
    source_field_path: str
    source_confidence_ref: "str | None" = None


@dataclass(frozen=True)
class SourceConfidenceEntry:
    source_engine: str
    confidence_available: bool
    confidence_value: "Decimal | None"
    reliability_label_tr: "str | None"
    reason_code: "str | None"
    source_warning: "str | None"
    used_in_section_codes: "tuple[ReportSectionCode, ...]"


@dataclass(frozen=True)
class SourceCoverageEntry:
    source_engine: str
    coverage_available: bool
    coverage_value: "Decimal | None"
    reason_code: "str | None"
    source_warning: "str | None"
    used_in_section_codes: "tuple[ReportSectionCode, ...]"


@dataclass(frozen=True)
class SectionSourceMappingEntry:
    section_code: ReportSectionCode
    source_engines: "tuple[str, ...]"


@dataclass(frozen=True)
class SourceInventoryEntry:
    source_engine: str
    status: str  # "used" | "not_used" | "unavailable"
    used_in_section_codes: "tuple[ReportSectionCode, ...]"


@dataclass(frozen=True)
class UpstreamVersionEntry:
    source_engine: str
    schema_version: "str | None"
    model_or_registry_version: "str | None"


# --- Bölüm 8: SWOT -- KİLİTLİ (Madde 9) -------------------------------------


SWOT_BOUNDARY_STATEMENT_TR = (
    "Bu bölüm bağımsız stratejik SWOT analizi DEĞİLDİR; mevcut motor "
    "çıktılarının yeniden biçimlendirilmiş sunumudur."
)

SWOT_OPPORTUNITIES_UNAVAILABLE_REASON_TR = (
    "Mevcut kaynak motorlar doğrulanmış bağımsız fırsat sinyali "
    "üretmediği için bu alan otomatik olarak doldurulmamıştır."
)


@dataclass(frozen=True)
class SwotQuadrantItem:
    text_tr: str
    source_engine: str
    source_field_path: str
    source_code: "str | None"
    provenance_note_tr: str


@dataclass(frozen=True)
class SwotQuadrant:
    quadrant: str  # "strengths" | "weaknesses" | "threats" | "opportunities"
    items: "tuple[SwotQuadrantItem, ...]"
    is_available: bool
    unavailable_reason_tr: "str | None"


@dataclass(frozen=True)
class SwotSectionMetadata:
    is_reformatted_source_content: bool = True
    is_independent_strategic_analysis: bool = False
    boundary_statement_tr: str = SWOT_BOUNDARY_STATEMENT_TR


# --- Bölüm 7.2: inşa edilmiş section çıktısı --------------------------------


@dataclass(frozen=True)
class ReportSection:
    section_code: ReportSectionCode
    title_tr: str
    build_phase: BuildPhase
    is_mandatory_for_report_type: bool
    content_blocks: "tuple[ReportContentBlock, ...]"
    source_engines: "tuple[str, ...]"
    consumed_section_codes: "tuple[ReportSectionCode, ...]"
    data_domains: "tuple[str, ...]"
    explainability_note_tr: str
    disclaimer_scope: "str | None"
    is_reformatted_source_content: bool
    is_independent_strategic_analysis: bool
    warnings: "tuple[dict[str, Any], ...]"


# --- Bölüm 11.1: ExecutiveReportResult -- NİHAİ, TAM alan listesi ----------


@dataclass(frozen=True)
class ExecutiveReportResult:
    status: ReportComputationStatus
    report_type: ReportType
    report_title_tr: str
    sections: "tuple[ReportSection, ...]"
    included_section_codes: "tuple[ReportSectionCode, ...]"
    omitted_section_codes: "tuple[ReportSectionCode, ...]"
    company_metadata: ReportCompanyMetadata
    reporting_period_label_tr: str
    warnings: "tuple[dict[str, Any], ...]"
    source_inventory: "tuple[SourceInventoryEntry, ...]"
    source_confidence_inventory: "tuple[SourceConfidenceEntry, ...]"
    source_coverage_inventory: "tuple[SourceCoverageEntry, ...]"
    missing_confidence_sources: "tuple[str, ...]"
    missing_coverage_sources: "tuple[str, ...]"
    section_source_mapping: "tuple[SectionSourceMappingEntry, ...]"
    duplicate_content_warnings: "tuple[dict[str, Any], ...]"
    disclaimer_blocks: "tuple[ReportDisclaimerBlock, ...]"
    provisional: bool
    decision_support_only: bool
    not_a_statutory_report: bool
    not_a_credit_approval: bool
    not_investment_advice: bool
    legal_review_status: LegalReviewStatus
    confidentiality_level: ConfidentialityLevel
    intended_audience: str
    intended_use: str
    external_distribution_allowed: bool
    regulatory_disclaimer_required: bool
    contains_sensitive_financial_data: bool
    redaction_required: bool
    source_document_identifiers_included: bool
    report_id: "str | None"
    generated_at: "str | None"
    locale: str
    currency_display_policy: "str | None"
    report_schema_version: str
    report_model_version: str
    upstream_version_inventory: "tuple[UpstreamVersionEntry, ...]"
