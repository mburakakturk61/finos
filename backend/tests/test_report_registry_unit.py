"""
Milestone 4.4 (Executive Report Engine) -- registry-seviyesi testler:
tam envanterler, dependency graph kayıt-anı doğrulaması, overlap/duplicate-
detail reddi, legal/confidentiality matrisi.
"""

from collections import Counter

import app.engines.common.report_registry as rr
from app.engines.common.report_registry import (
    DependencyCycleError,
    InvalidDependencyScopeError,
    InvalidDetailLevelForNarrativeReportError,
    InvalidPhaseDependencyError,
    OverlappingFullDetailSectionsError,
    REPORT_SECTION_REGISTRY,
    REPORT_TYPE_LEGAL_PROFILES,
    REPORT_TYPE_REGISTRY,
    SelfDependencyError,
    UnknownSectionDependencyError,
    UnknownSectionUsageError,
    register_report_section,
    register_report_type,
    validate_dag,
)
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


def test_exact_7_narrative_report_types():
    assert {rt.value for rt in ReportType} == {
        "cfo_executive_report", "bank_credit_allocation_report", "board_of_directors_report",
        "investor_report", "management_summary", "swot_report", "period_comparison_report",
    }
    assert len(REPORT_TYPE_REGISTRY) == 7


def test_render_contract_preview_and_dashboard_types_not_in_report_type():
    values = {rt.value for rt in ReportType}
    assert "render_contract_preview" not in values
    assert "executive_dashboard" not in values
    assert "risk_dashboard" not in values


def test_exact_18_canonical_sections():
    assert len(REPORT_SECTION_REGISTRY) == 18
    assert len(ReportSectionCode) == 18


def test_build_phase_distribution_13_2_3():
    dist = Counter(d.build_phase.value for d in REPORT_SECTION_REGISTRY.values())
    assert dist == {"source_section": 13, "aggregation_section": 2, "compliance_section": 3}


def test_section_definitions_carry_required_fields():
    for code, definition in REPORT_SECTION_REGISTRY.items():
        assert definition.section_code == code
        assert isinstance(definition.display_name_tr, str) and definition.display_name_tr
        assert isinstance(definition.build_phase, BuildPhase)
        assert isinstance(definition.data_domains, tuple)
        assert isinstance(definition.overlaps_with, tuple)
        assert isinstance(definition.primary_section_for_domain, dict)
        assert isinstance(definition.builder_strategy, ReportSectionBuilderStrategy)
        assert isinstance(definition.source_engine_codes, tuple)
        assert definition.model_version_introduced == "1.0.0"
        assert definition.deprecated_since is None
        assert definition.replacement_section_code is None


def test_section_usage_inventory_counts_match_design_doc():
    expected_counts = {
        ReportType.CFO_EXECUTIVE_REPORT: 16,
        ReportType.BANK_CREDIT_ALLOCATION_REPORT: 12,
        ReportType.BOARD_OF_DIRECTORS_REPORT: 10,
        ReportType.INVESTOR_REPORT: 9,
        ReportType.MANAGEMENT_SUMMARY: 7,
        ReportType.SWOT_REPORT: 7,
        ReportType.PERIOD_COMPARISON_REPORT: 5,
    }
    for rt, expected in expected_counts.items():
        assert len(REPORT_TYPE_REGISTRY[rt]) == expected, rt


def test_all_18_sections_used_in_at_least_one_report_type():
    used = set()
    for usages in REPORT_TYPE_REGISTRY.values():
        used.update(u.section_code for u in usages)
    assert used == set(REPORT_SECTION_REGISTRY.keys())


def test_narrative_reports_never_use_dashboard_detail_level():
    for usages in REPORT_TYPE_REGISTRY.values():
        for usage in usages:
            assert usage.detail_level != DetailLevel.DASHBOARD


def test_registering_dashboard_detail_level_in_narrative_report_is_rejected():
    isolated_types = {}
    usage = SectionUsageDefinition(
        section_code=ReportSectionCode.SEC_COVER_PAGE, detail_level=DetailLevel.DASHBOARD,
        field_inclusion_policy=FieldInclusionPolicy.ALL_FIELDS, maximum_items=None, table_density=None,
        include_provenance=True, include_confidence=False, include_disclaimer=False, display_order=1, optional=False,
    )
    try:
        register_report_type(ReportType.CFO_EXECUTIVE_REPORT, (usage,), registry=isolated_types)
        assert False, "InvalidDetailLevelForNarrativeReportError beklenirdi"
    except InvalidDetailLevelForNarrativeReportError:
        pass


def test_undefined_section_rejection_in_report_type_registration():
    isolated_types = {}
    fake_code_usage = SectionUsageDefinition(
        section_code="SEC_DOES_NOT_EXIST",  # type: ignore[arg-type]
        detail_level=DetailLevel.FULL, field_inclusion_policy=FieldInclusionPolicy.ALL_FIELDS,
        maximum_items=None, table_density=None, include_provenance=True, include_confidence=False,
        include_disclaimer=False, display_order=1, optional=False,
    )
    try:
        register_report_type(ReportType.CFO_EXECUTIVE_REPORT, (fake_code_usage,), registry=isolated_types)
        assert False, "UnknownSectionUsageError beklenirdi"
    except UnknownSectionUsageError:
        pass


def test_duplicate_full_detail_across_sections_rejected_at_registration():
    isolated_types = {}
    usages = (
        SectionUsageDefinition(ReportSectionCode.SEC_RATIO_ANALYSIS_TABLE, DetailLevel.FULL, FieldInclusionPolicy.ALL_FIELDS, None, TableDensity.FULL, True, True, True, 1, False),
        SectionUsageDefinition(ReportSectionCode.SEC_INVESTOR_KPI_SUMMARY, DetailLevel.FULL, FieldInclusionPolicy.ALL_FIELDS, None, TableDensity.FULL, True, True, True, 2, False),
    )
    try:
        register_report_type(ReportType.CFO_EXECUTIVE_REPORT, usages, registry=isolated_types)
        assert False, "OverlappingFullDetailSectionsError beklenirdi (growth_analysis/profitability_summary domain çakışması)"
    except OverlappingFullDetailSectionsError:
        pass


def test_real_registry_has_no_full_full_overlap_for_any_report_type():
    # Bölüm 6.3 -- gerçek 7 rapor tipinin TAMAMI zaten registration-time
    # doğrulamasından GEÇMİŞTİR (modül import edilirken); bu test yalnızca
    # bunu TEKRAR, açıkça DOĞRULAR (regresyon).
    for rt, usages in REPORT_TYPE_REGISTRY.items():
        domain_full_owner = {}
        for usage in usages:
            is_full = usage.table_density == TableDensity.FULL or usage.field_inclusion_policy == FieldInclusionPolicy.ALL_FIELDS
            if not is_full:
                continue
            for domain in REPORT_SECTION_REGISTRY[usage.section_code].data_domains:
                assert domain not in domain_full_owner, f"{rt}: '{domain}' iki full section'a sahip"
                domain_full_owner[domain] = usage.section_code


def test_unknown_dependency_rejection():
    isolated = dict(REPORT_SECTION_REGISTRY)
    bad_def = ReportSectionDefinition(
        section_code=ReportSectionCode.SEC_EXECUTIVE_SUMMARY,  # zaten kayıtlı -- farklı bir kod kullanalım
        display_name_tr="x", build_phase=BuildPhase.AGGREGATION_SECTION,
        dependency_codes=("SEC_DOES_NOT_EXIST",), consumes_section_outputs=("SEC_DOES_NOT_EXIST",),
        data_domains=(), overlaps_with=(), primary_section_for_domain={},
        builder_strategy=ReportSectionBuilderStrategy.EXECUTIVE_SUMMARY, source_engine_codes=(),
        model_version_introduced="1.0.0", deprecated_since=None, replacement_section_code=None,
    )
    isolated2 = {}
    try:
        register_report_section(bad_def, registry=isolated2)
        assert False, "UnknownSectionDependencyError beklenirdi"
    except UnknownSectionDependencyError:
        pass


def test_self_dependency_rejection():
    isolated = {}
    source = ReportSectionDefinition(
        ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN, "x", BuildPhase.SOURCE_SECTION, (), (), (), (), {},
        ReportSectionBuilderStrategy.HEALTH_SCORE_BREAKDOWN, ("health_score",), "1.0.0", None, None,
    )
    register_report_section(source, registry=isolated)
    self_dep = ReportSectionDefinition(
        ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN, "x2", BuildPhase.AGGREGATION_SECTION,
        (ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN,), (ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN,),
        (), (), {}, ReportSectionBuilderStrategy.EXECUTIVE_SUMMARY, (), "1.0.0", None, None,
    )
    isolated2 = {ReportSectionCode.SEC_CREDIT_SCORE_BREAKDOWN: ReportSectionDefinition(
        ReportSectionCode.SEC_CREDIT_SCORE_BREAKDOWN, "y", BuildPhase.SOURCE_SECTION, (), (), (), (), {},
        ReportSectionBuilderStrategy.CREDIT_SCORE_BREAKDOWN, ("credit_score",), "1.0.0", None, None,
    )}
    isolated2[ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN] = source
    try:
        register_report_section(self_dep, registry=isolated2)
        assert False, "self-dependency zaten kayıtlı section_code ile çakışıp ValueError vermeli"
    except ValueError:
        pass


def test_wrong_phase_dependency_rejection():
    isolated = {}
    source = ReportSectionDefinition(
        ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN, "x", BuildPhase.SOURCE_SECTION, (), (), (), (), {},
        ReportSectionBuilderStrategy.HEALTH_SCORE_BREAKDOWN, ("health_score",), "1.0.0", None, None,
    )
    register_report_section(source, registry=isolated)
    agg1 = ReportSectionDefinition(
        ReportSectionCode.SEC_EXECUTIVE_SUMMARY, "y", BuildPhase.AGGREGATION_SECTION,
        (ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN,), (ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN,),
        (), (), {}, ReportSectionBuilderStrategy.EXECUTIVE_SUMMARY, (), "1.0.0", None, None,
    )
    register_report_section(agg1, registry=isolated)
    agg2_depends_on_agg1 = ReportSectionDefinition(
        ReportSectionCode.SEC_SWOT, "z", BuildPhase.AGGREGATION_SECTION,
        (ReportSectionCode.SEC_EXECUTIVE_SUMMARY,), (ReportSectionCode.SEC_EXECUTIVE_SUMMARY,),
        (), (), {}, ReportSectionBuilderStrategy.SWOT, (), "1.0.0", None, None,
    )
    try:
        register_report_section(agg2_depends_on_agg1, registry=isolated)
        assert False, "InvalidPhaseDependencyError beklenirdi (aggregation->aggregation yasak)"
    except InvalidPhaseDependencyError:
        pass


def test_compliance_section_wildcard_required():
    isolated = {}
    bad_compliance = ReportSectionDefinition(
        ReportSectionCode.SEC_DISCLAIMER_BLOCK, "x", BuildPhase.COMPLIANCE_SECTION,
        (ReportSectionCode.SEC_COVER_PAGE,), (ReportSectionCode.SEC_COVER_PAGE,),
        (), (), {}, ReportSectionBuilderStrategy.DISCLAIMER_BLOCK, (), "1.0.0", None, None,
    )
    try:
        register_report_section(bad_compliance, registry=isolated)
        assert False, "InvalidDependencyScopeError beklenirdi"
    except InvalidDependencyScopeError:
        pass


def test_dependency_cycle_rejection_via_validate_dag():
    a = ReportSectionCode.SEC_COVER_PAGE
    b = ReportSectionCode.SEC_EXECUTIVE_SUMMARY
    cyclic_registry = {
        a: ReportSectionDefinition(a, "a", BuildPhase.AGGREGATION_SECTION, (b,), (b,), (), (), {}, ReportSectionBuilderStrategy.EXECUTIVE_SUMMARY, (), "1.0.0", None, None),
        b: ReportSectionDefinition(b, "b", BuildPhase.AGGREGATION_SECTION, (a,), (a,), (), (), {}, ReportSectionBuilderStrategy.SWOT, (), "1.0.0", None, None),
    }
    try:
        validate_dag(cyclic_registry)
        assert False, "DependencyCycleError beklenirdi"
    except DependencyCycleError:
        pass


def test_registry_insertion_order_independence_of_dag_validation():
    a, b, c = ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN, ReportSectionCode.SEC_EXECUTIVE_SUMMARY, ReportSectionCode.SEC_SWOT
    source_a = ReportSectionDefinition(a, "a", BuildPhase.SOURCE_SECTION, (), (), (), (), {}, ReportSectionBuilderStrategy.HEALTH_SCORE_BREAKDOWN, ("health_score",), "1.0.0", None, None)
    agg_b = ReportSectionDefinition(b, "b", BuildPhase.AGGREGATION_SECTION, (a,), (a,), (), (), {}, ReportSectionBuilderStrategy.EXECUTIVE_SUMMARY, (), "1.0.0", None, None)
    agg_c = ReportSectionDefinition(c, "c", BuildPhase.AGGREGATION_SECTION, (a,), (a,), (), (), {}, ReportSectionBuilderStrategy.SWOT, (), "1.0.0", None, None)

    order1 = {a: source_a, b: agg_b, c: agg_c}
    order2 = {c: agg_c, b: agg_b, a: source_a}
    validate_dag(order1)
    validate_dag(order2)  # HATA VERMEMELİ -- dict insertion order sonucu ETKİLEMEZ


def test_legal_review_matrix_matches_final_design():
    expected = {
        ReportType.CFO_EXECUTIVE_REPORT: (LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.CONFIDENTIAL),
        ReportType.BANK_CREDIT_ALLOCATION_REPORT: (LegalReviewStatus.LEGAL_REVIEW_REQUIRED, ConfidentialityLevel.CONFIDENTIAL),
        ReportType.BOARD_OF_DIRECTORS_REPORT: (LegalReviewStatus.LEGAL_REVIEW_REQUIRED, ConfidentialityLevel.CONFIDENTIAL),
        ReportType.INVESTOR_REPORT: (LegalReviewStatus.LEGAL_REVIEW_REQUIRED, ConfidentialityLevel.RESTRICTED),
        ReportType.MANAGEMENT_SUMMARY: (LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL),
        ReportType.SWOT_REPORT: (LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL),
        ReportType.PERIOD_COMPARISON_REPORT: (LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL),
    }
    for rt, (status, level) in expected.items():
        profile = REPORT_TYPE_LEGAL_PROFILES[rt]
        assert profile.legal_review_status == status, rt
        assert profile.confidentiality_level == level, rt


def test_no_report_type_is_approved_in_v1():
    for profile in REPORT_TYPE_LEGAL_PROFILES.values():
        assert profile.legal_review_status != LegalReviewStatus.APPROVED


def test_external_distribution_never_allowed_in_v1():
    for profile in REPORT_TYPE_LEGAL_PROFILES.values():
        assert profile.external_distribution_allowed is False


def test_legal_review_required_count_is_3_and_internal_use_only_count_is_4():
    statuses = [p.legal_review_status for p in REPORT_TYPE_LEGAL_PROFILES.values()]
    assert statuses.count(LegalReviewStatus.LEGAL_REVIEW_REQUIRED) == 3
    assert statuses.count(LegalReviewStatus.INTERNAL_USE_ONLY) == 4


def test_overlap_domain_count_is_7():
    domain_to_sections = {}
    for code, definition in REPORT_SECTION_REGISTRY.items():
        for domain in definition.data_domains:
            domain_to_sections.setdefault(domain, set()).add(code)
    overlap_domains = [d for d, codes in domain_to_sections.items() if len(codes) > 1]
    assert len(overlap_domains) == 7


def test_dependency_relationship_counts():
    exec_summary = REPORT_SECTION_REGISTRY[ReportSectionCode.SEC_EXECUTIVE_SUMMARY]
    swot = REPORT_SECTION_REGISTRY[ReportSectionCode.SEC_SWOT]
    assert len(exec_summary.dependency_codes) == 4
    assert len(swot.dependency_codes) == 2
    for code in (ReportSectionCode.SEC_METHODOLOGY_APPENDIX, ReportSectionCode.SEC_DISCLAIMER_BLOCK, ReportSectionCode.SEC_CONFIDENCE_AND_DATA_QUALITY):
        assert REPORT_SECTION_REGISTRY[code].dependency_codes == DependencyScope.ALL_INCLUDED_UPSTREAM_SECTIONS
