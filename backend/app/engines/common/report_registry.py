"""
Milestone 4.4 (Executive Report Engine) -- Adım 2: 18 kanonik section +
7 narrative ReportType registry'si + dependency graph doğrulaması +
overlap/duplicate-content doğrulaması + compatibility/legal politikaları.

Onaylanan tasarım dokümanı Bölüm 4/5/6/9/10/15 birebir. Kayıt-anı
("registration-time") doğrulama disiplini `app/engines/common/
recommendation_registry.py` (4.3F) ile AYNIDIR: `ValueError` alt sınıfları,
eval/exec YOK, kapalı enum'lar.
"""

from app.engines.common.report_types import (
    BuildPhase,
    ConfidentialityLevel,
    DependencyScope,
    DetailLevel,
    FieldInclusionPolicy,
    LegalReviewStatus,
    ReportSectionBuilderStrategy,
    ReportSectionCode,
    ReportSectionDefinition,
    ReportType,
    SectionUsageDefinition,
    TableDensity,
)


# --- Bölüm 4.4: kayıt-anı doğrulama hata sınıfları -------------------------


class UnknownSectionDependencyError(ValueError):
    pass


class SelfDependencyError(ValueError):
    pass


class DependencyCycleError(ValueError):
    pass


class InvalidPhaseDependencyError(ValueError):
    pass


class InvalidDependencyScopeError(ValueError):
    pass


class InvalidDetailLevelForNarrativeReportError(ValueError):
    pass


class OverlappingFullDetailSectionsError(ValueError):
    pass


class UnknownSectionUsageError(ValueError):
    pass


# --- Bölüm 15.3: 18 kanonik section -- REGISTRY -----------------------------

REPORT_SECTION_REGISTRY: "dict[ReportSectionCode, ReportSectionDefinition]" = {}


def validate_dag(registry: "dict[ReportSectionCode, ReportSectionDefinition]") -> None:
    """
    Bölüm 4.4 madde 3 -- (section_code -> dependency_codes) grafiğinin bir
    DAG olduğunu, YALNIZCA literal (sabit-liste) bağımlılıkları kullanarak
    doğrular (wildcard/`DependencyScope` bir CYCLE OLUŞTURAMAZ -- yalnızca
    Faz 1+2'ye geriye dönük işaret eder, kendi fazına/ileri faza ASLA).
    Doğrudan, izole bir sözlükle de (unit test) çağrılabilir.
    """

    WHITE, GRAY, BLACK = 0, 1, 2
    color: "dict[ReportSectionCode, int]" = {code: WHITE for code in registry}

    def _visit(code: "ReportSectionCode") -> None:
        color[code] = GRAY
        definition = registry[code]
        deps = definition.dependency_codes
        if isinstance(deps, DependencyScope):
            color[code] = BLACK
            return
        for dep_code in deps:
            if dep_code not in registry:
                raise UnknownSectionDependencyError(
                    f"{code!r}: bilinmeyen dependency {dep_code!r}"
                )
            if dep_code == code:
                raise SelfDependencyError(f"{code!r}: kendi kendine bağımlı olamaz")
            if color.get(dep_code, WHITE) == GRAY:
                raise DependencyCycleError(f"{code!r} -> {dep_code!r} arasında DÖNGÜ tespit edildi")
            if color.get(dep_code, WHITE) == WHITE:
                _visit(dep_code)
        color[code] = BLACK

    for section_code in registry:
        if color[section_code] == WHITE:
            _visit(section_code)


def register_report_section(
    definition: ReportSectionDefinition,
    *,
    registry: "dict[ReportSectionCode, ReportSectionDefinition] | None" = None,
) -> None:
    target = REPORT_SECTION_REGISTRY if registry is None else registry

    if definition.section_code in target:
        raise ValueError(f"section_code zaten kayıtlı: {definition.section_code!r}")

    if definition.build_phase == BuildPhase.SOURCE_SECTION:
        if definition.dependency_codes != () or definition.consumes_section_outputs != ():
            raise InvalidPhaseDependencyError(
                f"{definition.section_code!r}: source_section dependency_codes=() OLMALI"
            )
        if not definition.source_engine_codes:
            raise ValueError(f"{definition.section_code!r}: source_section source_engine_codes BOŞ olamaz")

    elif definition.build_phase == BuildPhase.AGGREGATION_SECTION:
        deps = definition.dependency_codes
        if isinstance(deps, DependencyScope):
            raise InvalidDependencyScopeError(
                f"{definition.section_code!r}: aggregation_section wildcard KULLANAMAZ"
            )
        if not deps:
            raise ValueError(f"{definition.section_code!r}: aggregation_section en az 1 bağımlılık taşımalı")
        seen: "set[ReportSectionCode]" = set()
        for dep_code in deps:
            if dep_code == definition.section_code:
                raise SelfDependencyError(f"{definition.section_code!r}: kendi kendine bağımlı olamaz")
            if dep_code not in target:
                raise UnknownSectionDependencyError(
                    f"{definition.section_code!r}: bilinmeyen dependency {dep_code!r}"
                )
            if target[dep_code].build_phase != BuildPhase.SOURCE_SECTION:
                raise InvalidPhaseDependencyError(
                    f"{definition.section_code!r}: aggregation_section yalnızca source_section'a bağımlı olabilir "
                    f"(bulunan: {dep_code!r} -> {target[dep_code].build_phase!r})"
                )
            if dep_code in seen:
                raise ValueError(f"{definition.section_code!r}: yinelenen dependency {dep_code!r}")
            seen.add(dep_code)
        if isinstance(definition.consumes_section_outputs, DependencyScope):
            raise InvalidDependencyScopeError(
                f"{definition.section_code!r}: aggregation_section consumes_section_outputs wildcard KULLANAMAZ"
            )
        if set(definition.consumes_section_outputs) - set(deps):
            raise ValueError(
                f"{definition.section_code!r}: consumes_section_outputs, dependency_codes'un ALT KÜMESİ olmalı"
            )
        if definition.source_engine_codes:
            raise ValueError(
                f"{definition.section_code!r}: aggregation_section source_engine_codes BOŞ olmalı "
                "(yalnızca Faz 1 çıktısını okur)"
            )

    elif definition.build_phase == BuildPhase.COMPLIANCE_SECTION:
        if definition.dependency_codes != DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS:
            raise InvalidDependencyScopeError(
                f"{definition.section_code!r}: compliance_section dependency_codes yalnızca "
                "DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS olabilir"
            )
        if definition.consumes_section_outputs != DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS:
            raise InvalidDependencyScopeError(
                f"{definition.section_code!r}: compliance_section consumes_section_outputs yalnızca "
                "DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS olabilir"
            )
    else:
        raise ValueError(f"{definition.section_code!r}: bilinmeyen build_phase {definition.build_phase!r}")

    target[definition.section_code] = definition
    # Kayıt-anı DAG doğrulaması -- her yeni kayıttan SONRA, TÜM registry
    # (o ana kadar kayıtlı olan) yeniden doğrulanır (Bölüm 4.4 madde 3).
    validate_dag(target)


def _section(
    section_code: ReportSectionCode,
    display_name_tr: str,
    build_phase: BuildPhase,
    data_domains: "tuple[str, ...]",
    builder_strategy: ReportSectionBuilderStrategy,
    source_engine_codes: "tuple[str, ...]" = (),
    dependency_codes: "tuple[ReportSectionCode, ...] | DependencyScope" = (),
) -> ReportSectionDefinition:
    consumes = dependency_codes
    return ReportSectionDefinition(
        section_code=section_code,
        display_name_tr=display_name_tr,
        build_phase=build_phase,
        dependency_codes=dependency_codes,
        consumes_section_outputs=consumes,
        data_domains=data_domains,
        overlaps_with=(),  # aşağıda `_finalize_overlaps()` ile doldurulur
        primary_section_for_domain={},  # aşağıda `_finalize_overlaps()` ile doldurulur
        builder_strategy=builder_strategy,
        source_engine_codes=source_engine_codes,
        model_version_introduced="1.0.0",
        deprecated_since=None,
        replacement_section_code=None,
    )


def _finalize_overlaps(
    registry: "dict[ReportSectionCode, ReportSectionDefinition]",
    primary_map: "dict[str, ReportSectionCode]",
) -> None:
    """
    Bölüm 15.3.1'in GLOBAL `primary_section_for_domain` haritasını ve
    `overlaps_with`'i registry'ye İŞLER (immutable dataclass olduğu için
    `dataclasses.replace` ile YENİDEN oluşturulur).
    """

    domain_to_sections: "dict[str, list[ReportSectionCode]]" = {}
    for code, definition in registry.items():
        for domain in definition.data_domains:
            domain_to_sections.setdefault(domain, []).append(code)

    for code, definition in list(registry.items()):
        overlaps: "set[ReportSectionCode]" = set()
        domain_primary: "dict[str, ReportSectionCode]" = {}
        for domain in definition.data_domains:
            siblings = [c for c in domain_to_sections.get(domain, ()) if c != code]
            overlaps.update(siblings)
            if domain in primary_map:
                domain_primary[domain] = primary_map[domain]
        import dataclasses

        registry[code] = dataclasses.replace(
            definition,
            overlaps_with=tuple(sorted(overlaps, key=lambda c: c.value)),
            primary_section_for_domain=domain_primary,
        )


def _build_report_section_registry() -> "dict[ReportSectionCode, ReportSectionDefinition]":
    reg: "dict[ReportSectionCode, ReportSectionDefinition]" = {}
    SC = ReportSectionCode
    BP = BuildPhase
    BS = ReportSectionBuilderStrategy

    # --- Faz 1: 13 source_section -------------------------------------
    register_report_section(
        _section(SC.SEC_COVER_PAGE, "Kapak Sayfası", BP.SOURCE_SECTION, (), BS.COVER_PAGE, ("company_metadata",)),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_FINANCIAL_STATEMENTS_SUMMARY, "Finansal Tablo Özeti", BP.SOURCE_SECTION,
            ("financial_statements",), BS.FINANCIAL_STATEMENTS_SUMMARY,
            ("balance_sheet", "income_statement"),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_RATIO_ANALYSIS_TABLE, "Finansal Oran Analizi Tablosu", BP.SOURCE_SECTION,
            ("liquidity_summary", "leverage_summary", "profitability_summary", "growth_analysis", "activity_summary"),
            BS.RATIO_ANALYSIS_TABLE, ("financial_ratios",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_BENCHMARK_COMPARISON, "Sektör Karşılaştırması", BP.SOURCE_SECTION,
            ("benchmark_positioning",), BS.BENCHMARK_COMPARISON, ("benchmarks",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_HEALTH_SCORE_BREAKDOWN, "Finansal Sağlık Skoru Detayı", BP.SOURCE_SECTION,
            ("health_score_summary",), BS.HEALTH_SCORE_BREAKDOWN, ("health_score",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_CREDIT_SCORE_BREAKDOWN, "Kredi Skoru Detayı", BP.SOURCE_SECTION,
            ("credit_score_summary",), BS.CREDIT_SCORE_BREAKDOWN, ("credit_score",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_BANKING_READINESS, "Bankacılık Hazırlığı", BP.SOURCE_SECTION,
            ("banking_readiness",), BS.BANKING_READINESS, ("credit_score",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_BANK_COLLATERAL_AND_DATA_GAPS, "Teminat ve Veri Eksikliği Bildirimleri", BP.SOURCE_SECTION,
            ("data_gaps",), BS.BANK_COLLATERAL_AND_DATA_GAPS, ("credit_score",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_RECOMMENDATIONS, "Öneriler", BP.SOURCE_SECTION,
            ("recommendation_actions",), BS.RECOMMENDATIONS, ("recommendation",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_BOARD_DECISION_ITEMS, "Yönetim Kurulu Karar Kalemleri", BP.SOURCE_SECTION,
            ("recommendation_actions",), BS.BOARD_DECISION_ITEMS, ("recommendation",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_RISK_FLAGS, "Risk Bayrakları", BP.SOURCE_SECTION,
            ("risk_signals",), BS.RISK_FLAGS, ("health_score", "credit_score", "recommendation"),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_INVESTOR_KPI_SUMMARY, "Yatırımcı KPI Özeti", BP.SOURCE_SECTION,
            ("growth_analysis", "profitability_summary"), BS.INVESTOR_KPI_SUMMARY, ("financial_ratios",),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_PERIOD_COMPARISON_ANALYSIS, "Dönem Karşılaştırma Analizi", BP.SOURCE_SECTION,
            ("growth_analysis", "financial_statements"), BS.PERIOD_COMPARISON_ANALYSIS,
            ("balance_sheet", "income_statement", "financial_ratios"),
        ),
        registry=reg,
    )

    # --- Faz 2: 2 aggregation_section ----------------------------------
    register_report_section(
        _section(
            SC.SEC_EXECUTIVE_SUMMARY, "Yönetici Özeti", BP.AGGREGATION_SECTION,
            ("health_score_summary", "credit_score_summary", "recommendation_actions", "risk_signals"),
            BS.EXECUTIVE_SUMMARY, (),
            dependency_codes=(
                SC.SEC_HEALTH_SCORE_BREAKDOWN, SC.SEC_CREDIT_SCORE_BREAKDOWN,
                SC.SEC_RECOMMENDATIONS, SC.SEC_RISK_FLAGS,
            ),
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_SWOT, "SWOT", BP.AGGREGATION_SECTION,
            ("health_score_summary", "recommendation_actions"), BS.SWOT, (),
            dependency_codes=(SC.SEC_HEALTH_SCORE_BREAKDOWN, SC.SEC_RECOMMENDATIONS),
        ),
        registry=reg,
    )

    # --- Faz 3: 3 compliance_section -----------------------------------
    register_report_section(
        _section(
            SC.SEC_METHODOLOGY_APPENDIX, "Metodoloji Eki", BP.COMPLIANCE_SECTION,
            (), BS.METHODOLOGY_APPENDIX, (),
            dependency_codes=DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS,
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_DISCLAIMER_BLOCK, "Yasal Uyarılar", BP.COMPLIANCE_SECTION,
            (), BS.DISCLAIMER_BLOCK, (),
            dependency_codes=DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS,
        ),
        registry=reg,
    )
    register_report_section(
        _section(
            SC.SEC_CONFIDENCE_AND_DATA_QUALITY, "Güvenilirlik ve Veri Kalitesi", BP.COMPLIANCE_SECTION,
            ("confidence_metadata",), BS.CONFIDENCE_AND_DATA_QUALITY, (),
            dependency_codes=DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS,
        ),
        registry=reg,
    )

    # Bölüm 15.3.1 -- GLOBAL primary_section_for_domain haritası (7 overlap domain).
    _finalize_overlaps(
        reg,
        primary_map={
            "growth_analysis": SC.SEC_RATIO_ANALYSIS_TABLE,
            "profitability_summary": SC.SEC_RATIO_ANALYSIS_TABLE,
            "financial_statements": SC.SEC_FINANCIAL_STATEMENTS_SUMMARY,
            "recommendation_actions": SC.SEC_RECOMMENDATIONS,
            "risk_signals": SC.SEC_RISK_FLAGS,
            "health_score_summary": SC.SEC_HEALTH_SCORE_BREAKDOWN,
            "credit_score_summary": SC.SEC_CREDIT_SCORE_BREAKDOWN,
        },
    )
    return reg


REPORT_SECTION_REGISTRY.update(_build_report_section_registry())


# --- Bölüm 9.2: legal/confidentiality NİHAİ matris (KAPALI, 7 satır) -------


class ReportTypeLegalProfile:
    __slots__ = (
        "legal_review_status", "confidentiality_level", "external_distribution_allowed",
        "intended_audience", "intended_use", "regulatory_disclaimer_required",
    )

    def __init__(
        self,
        legal_review_status: LegalReviewStatus,
        confidentiality_level: ConfidentialityLevel,
        external_distribution_allowed: bool,
        intended_audience: str,
        intended_use: str,
        regulatory_disclaimer_required: bool,
    ) -> None:
        self.legal_review_status = legal_review_status
        self.confidentiality_level = confidentiality_level
        self.external_distribution_allowed = external_distribution_allowed
        self.intended_audience = intended_audience
        self.intended_use = intended_use
        self.regulatory_disclaimer_required = regulatory_disclaimer_required


REPORT_TYPE_LEGAL_PROFILES: "dict[ReportType, ReportTypeLegalProfile]" = {
    ReportType.CFO_EXECUTIVE_REPORT: ReportTypeLegalProfile(
        LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.CONFIDENTIAL, False,
        "CFO ve üst düzey finans yönetimi", "internal_decision_support", True,
    ),
    ReportType.BANK_CREDIT_ALLOCATION_REPORT: ReportTypeLegalProfile(
        LegalReviewStatus.LEGAL_REVIEW_REQUIRED, ConfidentialityLevel.CONFIDENTIAL, False,
        "Kredi tahsis komitesi / banka risk analisti", "banking_decision_support", True,
    ),
    ReportType.BOARD_OF_DIRECTORS_REPORT: ReportTypeLegalProfile(
        LegalReviewStatus.LEGAL_REVIEW_REQUIRED, ConfidentialityLevel.CONFIDENTIAL, False,
        "Yönetim kurulu üyeleri", "board_decision_support", True,
    ),
    ReportType.INVESTOR_REPORT: ReportTypeLegalProfile(
        LegalReviewStatus.LEGAL_REVIEW_REQUIRED, ConfidentialityLevel.RESTRICTED, False,
        "Mevcut/potansiyel yatırımcılar", "investor_information", True,
    ),
    ReportType.MANAGEMENT_SUMMARY: ReportTypeLegalProfile(
        LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL, False,
        "Orta/üst düzey operasyonel yönetim", "internal_decision_support", False,
    ),
    ReportType.SWOT_REPORT: ReportTypeLegalProfile(
        LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL, False,
        "Stratejik değerlendirme yapan iç paydaşlar", "internal_strategic_reference", False,
    ),
    ReportType.PERIOD_COMPARISON_REPORT: ReportTypeLegalProfile(
        LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL, False,
        "Finans ekibi, tek-dönem karşılaştırma ihtiyacı olan iç paydaşlar",
        "internal_decision_support", False,
    ),
}

# Bölüm 9.2 kesin kural -- v1'de HİÇBİR rapor `approved` DEĞİLDİR.
assert all(
    profile.legal_review_status != LegalReviewStatus.APPROVED
    for profile in REPORT_TYPE_LEGAL_PROFILES.values()
), "v1'de HİÇBİR ReportType 'approved' OLAMAZ"
assert all(
    profile.external_distribution_allowed is False for profile in REPORT_TYPE_LEGAL_PROFILES.values()
), "v1'de HİÇBİR ReportType external_distribution_allowed=True OLAMAZ"


# --- Bölüm 15.4: 7 ReportType x SectionUsageDefinition -- TAM envanter -----

REPORT_TYPE_REGISTRY: "dict[ReportType, tuple[SectionUsageDefinition, ...]]" = {}
REPORT_TYPE_TITLES_TR: "dict[ReportType, str]" = {
    ReportType.CFO_EXECUTIVE_REPORT: "CFO Yönetici Raporu",
    ReportType.BANK_CREDIT_ALLOCATION_REPORT: "Banka Kredi Tahsis Raporu",
    ReportType.BOARD_OF_DIRECTORS_REPORT: "Yönetim Kurulu Raporu",
    ReportType.INVESTOR_REPORT: "Yatırımcı Raporu",
    ReportType.MANAGEMENT_SUMMARY: "Yönetim Özeti",
    ReportType.SWOT_REPORT: "SWOT Raporu",
    ReportType.PERIOD_COMPARISON_REPORT: "Dönem Karşılaştırma Raporu",
}


def _usage(
    section_code: ReportSectionCode,
    detail_level: DetailLevel,
    field_inclusion_policy: FieldInclusionPolicy,
    table_density: "TableDensity | None",
    display_order: int,
    optional: bool,
    maximum_items: "int | None" = None,
    include_provenance: bool = True,
    include_confidence: bool = True,
    include_disclaimer: bool = True,
) -> SectionUsageDefinition:
    return SectionUsageDefinition(
        section_code=section_code,
        detail_level=detail_level,
        field_inclusion_policy=field_inclusion_policy,
        maximum_items=maximum_items,
        table_density=table_density,
        include_provenance=include_provenance,
        include_confidence=include_confidence,
        include_disclaimer=include_disclaimer,
        display_order=display_order,
        optional=optional,
    )


def _is_full_detail(usage: SectionUsageDefinition) -> bool:
    return usage.table_density == TableDensity.FULL or usage.field_inclusion_policy == FieldInclusionPolicy.ALL_FIELDS


def register_report_type(
    report_type: ReportType,
    usage_definitions: "tuple[SectionUsageDefinition, ...]",
    *,
    section_registry: "dict[ReportSectionCode, ReportSectionDefinition] | None" = None,
    registry: "dict[ReportType, tuple[SectionUsageDefinition, ...]] | None" = None,
) -> None:
    sec_reg = REPORT_SECTION_REGISTRY if section_registry is None else section_registry
    target = REPORT_TYPE_REGISTRY if registry is None else registry

    seen_codes: "set[ReportSectionCode]" = set()
    seen_orders: "set[int]" = set()
    domain_full_owners: "dict[str, ReportSectionCode]" = {}

    for usage in usage_definitions:
        if usage.section_code not in sec_reg:
            raise UnknownSectionUsageError(f"{report_type!r}: bilinmeyen section_code {usage.section_code!r}")
        if usage.section_code in seen_codes:
            raise ValueError(f"{report_type!r}: yinelenen section_code {usage.section_code!r}")
        seen_codes.add(usage.section_code)
        if usage.display_order in seen_orders:
            raise ValueError(f"{report_type!r}: yinelenen display_order {usage.display_order!r}")
        seen_orders.add(usage.display_order)
        if usage.detail_level == DetailLevel.DASHBOARD:
            raise InvalidDetailLevelForNarrativeReportError(
                f"{report_type!r}/{usage.section_code!r}: narrative report DetailLevel.DASHBOARD KULLANAMAZ"
            )

        if _is_full_detail(usage):
            for domain in sec_reg[usage.section_code].data_domains:
                if domain in domain_full_owners:
                    raise OverlappingFullDetailSectionsError(
                        f"{report_type!r}: '{domain}' domain'i için birden fazla full-detail section "
                        f"({domain_full_owners[domain]!r} ve {usage.section_code!r})"
                    )
                domain_full_owners[domain] = usage.section_code

    target[report_type] = usage_definitions


DL, FIP, TD = DetailLevel, FieldInclusionPolicy, TableDensity
SC = ReportSectionCode

register_report_type(ReportType.CFO_EXECUTIVE_REPORT, (
    _usage(SC.SEC_COVER_PAGE, DL.FULL, FIP.ALL_FIELDS, None, 1, False, include_confidence=False, include_disclaimer=False),
    _usage(SC.SEC_EXECUTIVE_SUMMARY, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 2, False),
    _usage(SC.SEC_FINANCIAL_STATEMENTS_SUMMARY, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 3, False),
    _usage(SC.SEC_RATIO_ANALYSIS_TABLE, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 4, False),
    _usage(SC.SEC_BENCHMARK_COMPARISON, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 5, False),
    _usage(SC.SEC_HEALTH_SCORE_BREAKDOWN, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 6, False),
    _usage(SC.SEC_CREDIT_SCORE_BREAKDOWN, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 7, False),
    _usage(SC.SEC_RECOMMENDATIONS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 8, False),
    _usage(SC.SEC_RISK_FLAGS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 9, False),
    _usage(SC.SEC_BANKING_READINESS, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 10, True, maximum_items=10),
    _usage(SC.SEC_SWOT, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 11, True, include_confidence=False),
    _usage(SC.SEC_PERIOD_COMPARISON_ANALYSIS, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 12, True, maximum_items=10),
    _usage(SC.SEC_BANK_COLLATERAL_AND_DATA_GAPS, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 13, True, maximum_items=10),
    _usage(SC.SEC_CONFIDENCE_AND_DATA_QUALITY, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 14, False),
    _usage(SC.SEC_METHODOLOGY_APPENDIX, DL.FULL, FIP.ALL_FIELDS, None, 15, False, include_confidence=False),
    _usage(SC.SEC_DISCLAIMER_BLOCK, DL.FULL, FIP.ALL_FIELDS, None, 16, False, include_provenance=False, include_confidence=False),
))

register_report_type(ReportType.BANK_CREDIT_ALLOCATION_REPORT, (
    _usage(SC.SEC_COVER_PAGE, DL.FULL, FIP.ALL_FIELDS, None, 1, False, include_confidence=False, include_disclaimer=False),
    _usage(SC.SEC_EXECUTIVE_SUMMARY, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 2, False),
    _usage(SC.SEC_CREDIT_SCORE_BREAKDOWN, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 3, False),
    _usage(SC.SEC_BANKING_READINESS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 4, False),
    _usage(SC.SEC_BANK_COLLATERAL_AND_DATA_GAPS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 5, False),
    _usage(SC.SEC_RATIO_ANALYSIS_TABLE, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 6, False, maximum_items=15),
    _usage(SC.SEC_RISK_FLAGS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 7, False),
    _usage(SC.SEC_CONFIDENCE_AND_DATA_QUALITY, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 8, False),
    _usage(SC.SEC_DISCLAIMER_BLOCK, DL.FULL, FIP.ALL_FIELDS, None, 9, False, include_provenance=False, include_confidence=False),
    _usage(SC.SEC_FINANCIAL_STATEMENTS_SUMMARY, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 10, True),
    _usage(SC.SEC_BENCHMARK_COMPARISON, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 11, True, maximum_items=10),
    _usage(SC.SEC_METHODOLOGY_APPENDIX, DL.SUMMARY, FIP.HEADLINE_ONLY, None, 12, True, include_confidence=False),
))

register_report_type(ReportType.BOARD_OF_DIRECTORS_REPORT, (
    _usage(SC.SEC_COVER_PAGE, DL.FULL, FIP.ALL_FIELDS, None, 1, False, include_confidence=False, include_disclaimer=False),
    _usage(SC.SEC_EXECUTIVE_SUMMARY, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 2, False),
    _usage(SC.SEC_BOARD_DECISION_ITEMS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 3, False),
    _usage(SC.SEC_RISK_FLAGS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 4, False),
    _usage(SC.SEC_HEALTH_SCORE_BREAKDOWN, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 5, False),
    _usage(SC.SEC_CREDIT_SCORE_BREAKDOWN, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 6, False),
    _usage(SC.SEC_DISCLAIMER_BLOCK, DL.FULL, FIP.ALL_FIELDS, None, 7, False, include_provenance=False, include_confidence=False),
    _usage(SC.SEC_SWOT, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 8, True, include_confidence=False),
    _usage(SC.SEC_PERIOD_COMPARISON_ANALYSIS, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 9, True, maximum_items=10),
    _usage(SC.SEC_CONFIDENCE_AND_DATA_QUALITY, DL.COMPACT, FIP.HEADLINE_ONLY, TD.SUMMARY_ROW_ONLY, 10, True, include_provenance=False),
))

register_report_type(ReportType.INVESTOR_REPORT, (
    _usage(SC.SEC_COVER_PAGE, DL.FULL, FIP.ALL_FIELDS, None, 1, False, include_confidence=False, include_disclaimer=False),
    _usage(SC.SEC_EXECUTIVE_SUMMARY, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 2, False),
    _usage(SC.SEC_INVESTOR_KPI_SUMMARY, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 3, False),
    _usage(SC.SEC_HEALTH_SCORE_BREAKDOWN, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 4, False),
    _usage(SC.SEC_PERIOD_COMPARISON_ANALYSIS, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 5, False, maximum_items=10),
    _usage(SC.SEC_DISCLAIMER_BLOCK, DL.FULL, FIP.ALL_FIELDS, None, 6, False, include_provenance=False, include_confidence=False),
    _usage(SC.SEC_CREDIT_SCORE_BREAKDOWN, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 7, True),
    _usage(SC.SEC_SWOT, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 8, True, include_confidence=False),
    _usage(SC.SEC_BENCHMARK_COMPARISON, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 9, True, maximum_items=10),
))

register_report_type(ReportType.MANAGEMENT_SUMMARY, (
    _usage(SC.SEC_COVER_PAGE, DL.COMPACT, FIP.HEADLINE_ONLY, None, 1, False, include_provenance=False, include_confidence=False, include_disclaimer=False),
    _usage(SC.SEC_EXECUTIVE_SUMMARY, DL.COMPACT, FIP.HEADLINE_ONLY, TD.SUMMARY_ROW_ONLY, 2, False),
    _usage(SC.SEC_RISK_FLAGS, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 3, False, maximum_items=10),
    _usage(SC.SEC_RECOMMENDATIONS, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 4, False, maximum_items=10),
    _usage(SC.SEC_DISCLAIMER_BLOCK, DL.COMPACT, FIP.HEADLINE_ONLY, None, 5, False, include_provenance=False, include_confidence=False),
    _usage(SC.SEC_CONFIDENCE_AND_DATA_QUALITY, DL.COMPACT, FIP.HEADLINE_ONLY, TD.SUMMARY_ROW_ONLY, 6, True, include_provenance=False),
    _usage(SC.SEC_BANKING_READINESS, DL.COMPACT, FIP.HEADLINE_ONLY, TD.SUMMARY_ROW_ONLY, 7, True, maximum_items=5),
))

register_report_type(ReportType.SWOT_REPORT, (
    _usage(SC.SEC_COVER_PAGE, DL.FULL, FIP.ALL_FIELDS, None, 1, False, include_confidence=False, include_disclaimer=False),
    _usage(SC.SEC_SWOT, DL.FULL, FIP.ALL_FIELDS, None, 2, False),
    _usage(SC.SEC_METHODOLOGY_APPENDIX, DL.FULL, FIP.ALL_FIELDS, None, 3, False, include_confidence=False),
    _usage(SC.SEC_DISCLAIMER_BLOCK, DL.FULL, FIP.ALL_FIELDS, None, 4, False, include_provenance=False, include_confidence=False),
    _usage(SC.SEC_EXECUTIVE_SUMMARY, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.SUMMARY_ROW_ONLY, 5, True),
    # NOT (implementasyon düzeltmesi): SEC_SWOT (aggregation_section) kayıt-anında
    # SEC_HEALTH_SCORE_BREAKDOWN + SEC_RECOMMENDATIONS'a bağımlı OLARAK sabitlenmiştir
    # (Bölüm 4/15.3). "Aggregation section yalnızca TAMAMLANMIŞ dependency
    # outputlarını okuyabilmeli" kuralının SWOT_REPORT'ta anlamlı çalışabilmesi
    # için bu 2 kaynak section'ın da (düşük/compact ayrıntı seviyesiyle,
    # SWOT'un öne çıkarılmasını BOZMADAN) bu rapor tipine dahil edilmesi
    # ZORUNLUDUR -- aksi halde SEC_SWOT'un TÜM kadranları (Opportunities
    # HARİÇ) "dependency unavailable" nedeniyle BOŞ kalırdı, ki bu SWOT
    # Raporu'nun amacını YOK EDER. Tasarım dokümanının 1. onaylı sürümünde
    # (Bölüm 15.4.6) bu 2 kayıt SEHVEN atlanmıştı; bu, dokümanın onaylanan
    # MİMARİ kararlarını (Bölüm 4 dependency modeli) İHLAL ETMEYEN, salt
    # işlevsel bir düzeltmedir.
    _usage(SC.SEC_HEALTH_SCORE_BREAKDOWN, DL.COMPACT, FIP.HEADLINE_ONLY, TD.SUMMARY_ROW_ONLY, 6, False, include_provenance=False),
    _usage(SC.SEC_RECOMMENDATIONS, DL.COMPACT, FIP.HEADLINE_ONLY, TD.SUMMARY_ROW_ONLY, 7, False, maximum_items=5, include_provenance=False),
))

register_report_type(ReportType.PERIOD_COMPARISON_REPORT, (
    _usage(SC.SEC_COVER_PAGE, DL.FULL, FIP.ALL_FIELDS, None, 1, False, include_confidence=False, include_disclaimer=False),
    _usage(SC.SEC_PERIOD_COMPARISON_ANALYSIS, DL.FULL, FIP.ALL_FIELDS, TD.FULL, 2, False),
    _usage(SC.SEC_DISCLAIMER_BLOCK, DL.FULL, FIP.ALL_FIELDS, None, 3, False, include_provenance=False, include_confidence=False),
    _usage(SC.SEC_FINANCIAL_STATEMENTS_SUMMARY, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 4, True, maximum_items=10),
    _usage(SC.SEC_RATIO_ANALYSIS_TABLE, DL.SUMMARY, FIP.KEY_FIELDS_ONLY, TD.TOP_N, 5, True, maximum_items=10),
))


# --- Bölüm 10.1: merkezi immutable compatibility policy --------------------

REPORT_INPUT_COMPATIBILITY: "dict[str, tuple[str, ...]]" = {
    "health_score_schema_version": ("1.0.0",),
    "credit_score_schema_version": ("1.0.0",),
    "recommendation_schema_version": ("1.0.0",),
    "ratio_registry_version": ("1.1.0",),
    "benchmark_registry_version": ("1.0.0",),
    "balance_sheet_engine_version": ("1.0.0",),
    "income_statement_engine_version": ("1.0.0",),
}

# Bölüm 10.1 -- hangi anahtarlar "schema" (SCHEMA_INCOMPATIBLE'a yol açar)
# hangileri "registry/model version" (VERSION_MISMATCH/MODEL_VERSION_MISMATCH'e
# yol açar) katmanına AİTTİR.
REPORT_SCHEMA_COMPATIBILITY_KEYS: "tuple[str, ...]" = (
    "health_score_schema_version",
    "credit_score_schema_version",
    "recommendation_schema_version",
)
REPORT_REGISTRY_COMPATIBILITY_KEYS: "tuple[str, ...]" = (
    "ratio_registry_version",
    "benchmark_registry_version",
    "balance_sheet_engine_version",
    "income_statement_engine_version",
)

# Bölüm 10.2 madde 3 -- yalnızca *_model_version farkı (şema+registry
# UYUMLU iken) `MODEL_VERSION_MISMATCH` (non-blocking) warning'i üretir.
REPORT_EXPECTED_UPSTREAM_MODEL_VERSIONS: "dict[str, str]" = {
    "health_score_model_version": "1.0.0",
    "credit_score_model_version": "1.0.0",
    "recommendation_model_version": "1.0.0",
}
