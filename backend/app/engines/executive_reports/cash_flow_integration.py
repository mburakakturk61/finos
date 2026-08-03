"""Presentation-only Cash Flow projection for Executive Report v1.1.

The legacy report generator remains the sole builder of the canonical
18-section report.  This module only augments the existing financial
statements summary with values already present in ``CashFlowResult``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from app.engines.cash_flow.contracts import CashFlowResult, canonical_cash_flow_digest
from app.engines.cash_flow.errors import (
    CASH_FLOW_INTEGRITY_ERROR_CODES_V1,
    CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1,
)
from app.engines.cash_flow.types import (
    CashFlowErrorCode,
    CashFlowEvidenceKind,
    CashFlowLineCode,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
)
from app.engines.common.report_types import (
    ExecutiveReportResult,
    ReportBlockType,
    ReportContentBlock,
    ReportSection,
    ReportSectionCode,
    SectionSourceMappingEntry,
    SourceConfidenceEntry,
    SourceCoverageEntry,
    SourceInventoryEntry,
    UpstreamVersionEntry,
)

from .service import generate_executive_report


REPORT_SCHEMA_VERSION_V1_1_CASH_FLOW = "1.1.0"
REPORT_MODEL_VERSION_V1_1_CASH_FLOW = "1.1.0"

# Deliberately literal and independent from REPORT_SECTION_REGISTRY.  Runtime
# mutation of the legacy registry cannot change the cash-aware contract.
REPORT_REGISTRY_V1_1_CASH_FLOW = (
    ReportSectionCode.SEC_COVER_PAGE,
    ReportSectionCode.SEC_FINANCIAL_STATEMENTS_SUMMARY,
    ReportSectionCode.SEC_RATIO_ANALYSIS_TABLE,
    ReportSectionCode.SEC_BENCHMARK_COMPARISON,
    ReportSectionCode.SEC_HEALTH_SCORE_BREAKDOWN,
    ReportSectionCode.SEC_CREDIT_SCORE_BREAKDOWN,
    ReportSectionCode.SEC_BANKING_READINESS,
    ReportSectionCode.SEC_BANK_COLLATERAL_AND_DATA_GAPS,
    ReportSectionCode.SEC_RECOMMENDATIONS,
    ReportSectionCode.SEC_BOARD_DECISION_ITEMS,
    ReportSectionCode.SEC_RISK_FLAGS,
    ReportSectionCode.SEC_INVESTOR_KPI_SUMMARY,
    ReportSectionCode.SEC_PERIOD_COMPARISON_ANALYSIS,
    ReportSectionCode.SEC_EXECUTIVE_SUMMARY,
    ReportSectionCode.SEC_SWOT,
    ReportSectionCode.SEC_METHODOLOGY_APPENDIX,
    ReportSectionCode.SEC_DISCLAIMER_BLOCK,
    ReportSectionCode.SEC_CONFIDENCE_AND_DATA_QUALITY,
)

REPORT_SOURCE_ENGINE_INVENTORY_V1_1_CASH_FLOW = (
    "balance_sheet",
    "income_statement",
    "financial_ratios",
    "benchmarks",
    "health_score",
    "credit_score",
    "recommendation",
    "cash_flow",
)


class CashFlowReportSourceStatus(str, Enum):
    COMPLETE_RECONCILED = "complete_reconciled"
    COMPLETE_UNRECONCILED = "complete_unreconciled"
    PARTIAL_RECONCILED = "partial_reconciled"
    PARTIAL_UNRECONCILED = "partial_unreconciled"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CashFlowReportLineV1:
    line_code: CashFlowLineCode
    amount: Decimal | None
    evidence_kind: CashFlowEvidenceKind
    available: bool


@dataclass(frozen=True)
class CashFlowReportCompletenessV1:
    manifest_version: str
    required_line_count: int
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    available_ratio: Decimal
    optional_analytics_available_count: int
    optional_analytics_unavailable_count: int


@dataclass(frozen=True)
class CashFlowReportLineageReferenceV1:
    source_role: str
    source_analysis_result_id: UUID | None
    same_run_engine_code: str | None
    source_period_id: UUID
    canonical_digest: str
    source_provenance_digest: str


@dataclass(frozen=True)
class CashFlowReportAvailabilityObservationV1:
    period_position: str
    classification: str
    amount: Decimal | None
    evidence_kinds: tuple[CashFlowEvidenceKind, ...]


@dataclass(frozen=True)
class CashFlowReportProjectionV1:
    operating_cash_flow: Decimal | None
    investing_cash_flow: Decimal | None
    financing_cash_flow: Decimal | None
    calculated_net_cash_change: Decimal | None
    balance_sheet_net_cash_change: Decimal | None
    reconciliation_difference: Decimal | None
    opening_cash_and_cash_equivalents: Decimal | None
    closing_cash_and_cash_equivalents: Decimal | None
    free_cash_flow: Decimal | None
    status: CashFlowReportSourceStatus
    completeness: CashFlowReportCompletenessV1 | None
    reconciliation_status: CashFlowReconciliationStatus | None
    summary_lines: tuple[CashFlowReportLineV1, ...]
    warning_codes: tuple[str, ...]
    error_codes: tuple[str, ...]
    policy_version: str | None
    accounting_policy_version: str | None
    cash_equivalent_policy_version: str | None
    presentation_policy_version: str | None
    reconciliation_policy_version: str | None
    mapping_registry_version: str | None
    result_reference: str | None
    result_digest: str | None
    lineage_references: tuple[CashFlowReportLineageReferenceV1, ...]
    availability_observations: tuple[CashFlowReportAvailabilityObservationV1, ...]
    cash_flow_schema_version: str | None
    cash_flow_model_version: str | None


_SUMMARY_LINE_CODES = (
    CashFlowLineCode.OPERATING_CASH_FLOW,
    CashFlowLineCode.INVESTING_CASH_FLOW,
    CashFlowLineCode.FINANCING_CASH_FLOW,
    CashFlowLineCode.CALCULATED_NET_CASH_CHANGE,
    CashFlowLineCode.BALANCE_SHEET_NET_CASH_CHANGE,
    CashFlowLineCode.RECONCILIATION_DIFFERENCE,
    CashFlowLineCode.OPENING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.CLOSING_CASH_AND_CASH_EQUIVALENTS,
    CashFlowLineCode.FREE_CASH_FLOW,
)

_REPORT_WARNING_ORDER = (
    "CASH_FLOW_PARTIAL_RESULT",
    "CASH_FLOW_UNRECONCILED",
    "CASH_FLOW_MATERIAL_RECONCILIATION_DIFFERENCE",
    "CASH_FLOW_ESTIMATED_EVIDENCE",
    "CASH_FLOW_UNAVAILABLE_EVIDENCE",
    "CASH_FLOW_INSUFFICIENT_DATA",
    "CASH_FLOW_SOURCE_FAILURE",
    "CASH_FLOW_SOURCE_UNAVAILABLE",
)


def _empty_projection(
    status: CashFlowReportSourceStatus,
    error_code: CashFlowErrorCode | None,
) -> CashFlowReportProjectionV1:
    lines = tuple(
        CashFlowReportLineV1(code, None, CashFlowEvidenceKind.UNAVAILABLE, False)
        for code in _SUMMARY_LINE_CODES
    )
    return CashFlowReportProjectionV1(
        None, None, None, None, None, None, None, None, None,
        status, None, None, lines, (), (() if error_code is None else (error_code.value,)),
        None, None, None, None, None, None, None, None, (), (), None, None,
    )


def project_cash_flow_report_source_v1(
    *,
    requested: bool,
    result: CashFlowResult | None,
    failure_status: CashFlowResultStatus | None = None,
    failure_code: CashFlowErrorCode | None = None,
) -> CashFlowReportProjectionV1:
    """Project the canonical result without calculation or coercion."""
    if not requested:
        raise ValueError("cash-flow report projection requires an explicit request")
    if result is None:
        if failure_status is CashFlowResultStatus.INVALID_INPUT:
            if failure_code not in CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1:
                raise ValueError("invalid-input report projection requires its closed error code")
            return _empty_projection(CashFlowReportSourceStatus.INVALID_INPUT, failure_code)
        if failure_status is CashFlowResultStatus.INTEGRITY_FAILURE:
            if failure_code not in CASH_FLOW_INTEGRITY_ERROR_CODES_V1:
                raise ValueError("integrity-failure report projection requires its closed error code")
            return _empty_projection(CashFlowReportSourceStatus.INTEGRITY_FAILURE, failure_code)
        if failure_status is not None or failure_code is not None:
            raise ValueError("cash-flow failure status/code pair is inconsistent")
        return _empty_projection(CashFlowReportSourceStatus.UNAVAILABLE, None)
    if type(result) is not CashFlowResult or failure_status is not None or failure_code is not None:
        raise ValueError("cash-flow result projection accepts exactly one canonical result")

    lines_by_code = {item.line_code: item for item in result.line_items}
    lines = tuple(
        CashFlowReportLineV1(
            code,
            lines_by_code[code].canonical_amount,
            lines_by_code[code].evidence_kind,
            lines_by_code[code].canonical_amount is not None,
        )
        for code in _SUMMARY_LINE_CODES
    )
    completeness = CashFlowReportCompletenessV1(
        result.completeness.manifest_version,
        result.completeness.required_line_count,
        result.completeness.exact_count,
        result.completeness.derived_count,
        result.completeness.estimated_count,
        result.completeness.unavailable_count,
        result.completeness.available_ratio,
        result.completeness.optional_analytics_available_count,
        result.completeness.optional_analytics_unavailable_count,
    )
    digest = canonical_cash_flow_digest(result)
    lineage = tuple(
        CashFlowReportLineageReferenceV1(
            item.source_role.value,
            item.source_analysis_result_id,
            item.same_run_engine_code,
            item.source_period_id,
            item.canonical_digest,
            item.source_provenance_digest,
        )
        for item in result.source_lineage_references
    )
    observations = tuple(
        CashFlowReportAvailabilityObservationV1(
            observation.period_position.value,
            disclosure.observations[index].classification.value,
            observation.amount,
            tuple(sorted((item.evidence_kind for item in observation.evidence), key=lambda item: item.value)),
        )
        for disclosure in result.cash_availability_disclosures
        for index, observation in enumerate(disclosure.observations)
    )
    return CashFlowReportProjectionV1(
        result.operating_cash_flow,
        result.investing_cash_flow,
        result.financing_cash_flow,
        result.calculated_net_cash_change,
        result.balance_sheet_net_cash_change,
        result.reconciliation_difference,
        result.opening_cash_and_cash_equivalents,
        result.closing_cash_and_cash_equivalents,
        result.free_cash_flow,
        CashFlowReportSourceStatus(result.status.value),
        completeness,
        result.reconciliation_status,
        lines,
        tuple(sorted(item.code.value for item in result.warnings)),
        tuple(sorted(item.code.value for item in result.errors)),
        result.policy_version,
        result.accounting_policy_version,
        result.cash_equivalent_policy_version,
        result.presentation_policy_version,
        result.reconciliation_policy_version,
        result.mapping_registry_version,
        f"cash-flow-result:sha256:{digest}",
        digest,
        lineage,
        observations,
        result.cash_flow_schema_version,
        result.cash_flow_model_version,
    )


def _projection_warning_codes(projection: CashFlowReportProjectionV1) -> tuple[str, ...]:
    present: set[str] = set()
    if projection.status in {
        CashFlowReportSourceStatus.PARTIAL_RECONCILED,
        CashFlowReportSourceStatus.PARTIAL_UNRECONCILED,
    }:
        present.add("CASH_FLOW_PARTIAL_RESULT")
    if projection.status in {
        CashFlowReportSourceStatus.COMPLETE_UNRECONCILED,
        CashFlowReportSourceStatus.PARTIAL_UNRECONCILED,
    }:
        present.add("CASH_FLOW_UNRECONCILED")
    if projection.reconciliation_status is CashFlowReconciliationStatus.UNRECONCILED_MATERIAL:
        present.add("CASH_FLOW_MATERIAL_RECONCILIATION_DIFFERENCE")
    if (
        any(item.evidence_kind is CashFlowEvidenceKind.ESTIMATED for item in projection.summary_lines)
        or (projection.completeness is not None and projection.completeness.estimated_count > 0)
    ):
        present.add("CASH_FLOW_ESTIMATED_EVIDENCE")
    if any(item.evidence_kind is CashFlowEvidenceKind.UNAVAILABLE for item in projection.summary_lines):
        present.add("CASH_FLOW_UNAVAILABLE_EVIDENCE")
    if projection.status is CashFlowReportSourceStatus.INSUFFICIENT_DATA:
        present.add("CASH_FLOW_INSUFFICIENT_DATA")
    if projection.status in {
        CashFlowReportSourceStatus.INVALID_INPUT,
        CashFlowReportSourceStatus.INTEGRITY_FAILURE,
    }:
        present.add("CASH_FLOW_SOURCE_FAILURE")
    if projection.status is CashFlowReportSourceStatus.UNAVAILABLE:
        present.add("CASH_FLOW_SOURCE_UNAVAILABLE")
    return tuple(code for code in _REPORT_WARNING_ORDER if code in present)


def _projection_blocks(projection: CashFlowReportProjectionV1) -> tuple[ReportContentBlock, ...]:
    line_rows = tuple(
        {
            "field": item.line_code.value,
            "value": item.amount,
            "evidence_kind": item.evidence_kind.value,
            "available": item.available,
            "source": "cash_flow",
        }
        for item in projection.summary_lines
    )
    completeness = projection.completeness
    status_row: dict[str, Any] = {
        "computation_status": projection.status.value,
        "reconciliation_status": (
            None if projection.reconciliation_status is None else projection.reconciliation_status.value
        ),
        "required_line_count": None if completeness is None else completeness.required_line_count,
        "exact_count": None if completeness is None else completeness.exact_count,
        "derived_count": None if completeness is None else completeness.derived_count,
        "estimated_count": None if completeness is None else completeness.estimated_count,
        "unavailable_count": None if completeness is None else completeness.unavailable_count,
        "available_ratio": None if completeness is None else completeness.available_ratio,
        "policy_version": projection.policy_version,
        "accounting_policy_version": projection.accounting_policy_version,
        "cash_equivalent_policy_version": projection.cash_equivalent_policy_version,
        "presentation_policy_version": projection.presentation_policy_version,
        "reconciliation_policy_version": projection.reconciliation_policy_version,
        "mapping_registry_version": projection.mapping_registry_version,
        "safe_result_reference": projection.result_reference,
    }
    warning_items = tuple(
        {"kind": "warning", "code": code} for code in projection.warning_codes
    ) + tuple(
        {"kind": "error", "code": code} for code in projection.error_codes
    )
    lineage_rows = tuple(
        {
            "source_role": item.source_role,
            "source_analysis_result_id": None if item.source_analysis_result_id is None else str(item.source_analysis_result_id),
            "same_run_engine_code": item.same_run_engine_code,
            "source_period_id": str(item.source_period_id),
            "canonical_digest": item.canonical_digest,
            "source_provenance_digest": item.source_provenance_digest,
        }
        for item in projection.lineage_references
    )
    availability_rows = tuple(
        {
            "period_position": item.period_position,
            "classification": item.classification,
            "amount": item.amount,
            "evidence_kinds": tuple(kind.value for kind in item.evidence_kinds),
        }
        for item in projection.availability_observations
    )
    return (
        ReportContentBlock(
            ReportBlockType.TABLE,
            {"columns": ["field", "value", "evidence_kind", "available", "source"], "rows": line_rows},
            "cash_flow_result.summary_lines",
            "cash_flow.line_evidence",
        ),
        ReportContentBlock(
            ReportBlockType.TABLE,
            {"columns": list(status_row), "rows": (status_row,)},
            "cash_flow_result.status/completeness/reconciliation/policy",
            "cash_flow.completeness",
        ),
        ReportContentBlock(
            ReportBlockType.BULLET_LIST,
            {"items": warning_items},
            "cash_flow_result.warnings/errors",
            "cash_flow.issue_inventory",
        ),
        ReportContentBlock(
            ReportBlockType.TABLE,
            {
                "columns": [
                    "source_role", "source_analysis_result_id", "same_run_engine_code",
                    "source_period_id", "canonical_digest", "source_provenance_digest",
                ],
                "rows": lineage_rows,
            },
            "cash_flow_result.source_lineage_references",
            "cash_flow.lineage",
        ),
        ReportContentBlock(
            ReportBlockType.TABLE,
            {"columns": ["period_position", "classification", "amount", "evidence_kinds"], "rows": availability_rows},
            "cash_flow_result.cash_availability_disclosures",
            "cash_flow.restricted_cash_availability",
        ),
    )


def generate_executive_report_v1_1(
    *args: Any,
    cash_flow_requested: bool = False,
    cash_flow_result: CashFlowResult | None = None,
    cash_flow_failure_status: CashFlowResultStatus | None = None,
    cash_flow_error_code: CashFlowErrorCode | None = None,
    **kwargs: Any,
) -> ExecutiveReportResult:
    """Select legacy v1 or the immutable Cash Flow-aware v1.1 path."""
    legacy = generate_executive_report(*args, **kwargs)
    if not cash_flow_requested:
        if cash_flow_result is not None or cash_flow_failure_status is not None or cash_flow_error_code is not None:
            raise ValueError("unrequested cash-flow state cannot enter the report")
        return legacy

    projection = project_cash_flow_report_source_v1(
        requested=True,
        result=cash_flow_result,
        failure_status=cash_flow_failure_status,
        failure_code=cash_flow_error_code,
    )
    cash_warnings = _projection_warning_codes(projection)
    summary_code = ReportSectionCode.SEC_FINANCIAL_STATEMENTS_SUMMARY
    projection_used = summary_code in legacy.included_section_codes
    sections: list[ReportSection] = []
    for section in legacy.sections:
        if section.section_code is summary_code:
            section = replace(
                section,
                content_blocks=section.content_blocks + _projection_blocks(projection),
                source_engines=section.source_engines + ("cash_flow",),
                explainability_note_tr=(
                    section.explainability_note_tr
                    + " Cash Flow alanları canonical CashFlowResult'tan hesaplama yapılmadan yansıtılmıştır."
                ),
                warnings=section.warnings + tuple({"code": code} for code in cash_warnings),
            )
        sections.append(section)

    mapping = tuple(
        replace(item, source_engines=item.source_engines + ("cash_flow",))
        if item.section_code is summary_code else item
        for item in legacy.section_source_mapping
    )
    used_sections = (summary_code,) if projection_used else ()
    source_status = "used" if projection_used and cash_flow_result is not None else "unavailable"
    confidence = SourceConfidenceEntry(
        "cash_flow", False, None, None, "PER_LINE_EVIDENCE_NOT_ENGINE_LEVEL",
        "Cash Flow güvenilirliği satır bazında EXACT/DERIVED/ESTIMATED/UNAVAILABLE olarak sunulur.",
        used_sections,
    )
    coverage_available = projection.completeness is not None
    coverage = SourceCoverageEntry(
        "cash_flow",
        coverage_available,
        None if projection.completeness is None else projection.completeness.available_ratio,
        None if coverage_available else "CASH_FLOW_RESULT_UNAVAILABLE",
        None if coverage_available else "Cash Flow completeness bilgisi kullanılamıyor.",
        used_sections,
    )
    upstream = UpstreamVersionEntry(
        "cash_flow", projection.cash_flow_schema_version, projection.cash_flow_model_version,
    )
    new_warnings = tuple({"code": code} for code in cash_warnings)
    provisional = legacy.provisional or projection.status is not CashFlowReportSourceStatus.COMPLETE_RECONCILED
    return replace(
        legacy,
        sections=tuple(sections),
        warnings=legacy.warnings + new_warnings,
        source_inventory=legacy.source_inventory + (SourceInventoryEntry("cash_flow", source_status, used_sections),),
        source_confidence_inventory=legacy.source_confidence_inventory + (confidence,),
        source_coverage_inventory=legacy.source_coverage_inventory + (coverage,),
        missing_confidence_sources=legacy.missing_confidence_sources + ("cash_flow",),
        missing_coverage_sources=(
            legacy.missing_coverage_sources if coverage_available
            else legacy.missing_coverage_sources + ("cash_flow",)
        ),
        section_source_mapping=mapping,
        provisional=provisional,
        report_schema_version=REPORT_SCHEMA_VERSION_V1_1_CASH_FLOW,
        report_model_version=REPORT_MODEL_VERSION_V1_1_CASH_FLOW,
        upstream_version_inventory=legacy.upstream_version_inventory + (upstream,),
    )
