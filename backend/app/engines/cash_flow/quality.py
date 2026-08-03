"""Deterministic data-quality projection for the Cash Flow v1 result."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import final

from .contracts import (
    CashFlowCompleteness,
    CashFlowIssue,
    CashFlowLineItem,
    IndirectCashFlowInput,
    canonical_cash_flow_digest,
)
from .policy import quantize_completeness_ratio
from .types import (
    CASH_FLOW_OPTIONAL_ANALYTICS_MANIFEST_V1,
    CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1,
    CashFlowAccountDisposition,
    CashFlowErrorCode,
    CashFlowEvidenceKind,
    CashFlowLineCode,
    CashFlowReconciliationStatus,
    CashFlowSourceRole,
    CashFlowWarningCode,
)


CASH_FLOW_COMPLETENESS_MANIFEST_VERSION = "1.0.0"


@final
@dataclass(frozen=True, repr=False)
class CashFlowDataQualitySummary:
    """Internal deterministic quality inventory; it is not a confidence score."""

    missing_source_roles: tuple[CashFlowSourceRole, ...]
    missing_line_inputs: tuple[tuple[CashFlowLineCode, tuple[str, ...]], ...]
    estimated_line_codes: tuple[CashFlowLineCode, ...]
    unavailable_line_codes: tuple[CashFlowLineCode, ...]
    unclassified_account_count: int
    unclassified_account_reference_digests: tuple[str, ...]
    material_reconciliation_difference: bool
    policy_version_mismatches: tuple[str, ...]
    warning_codes: tuple[CashFlowWarningCode, ...]
    error_codes: tuple[CashFlowErrorCode, ...]

    def __repr__(self) -> str:
        return "CashFlowDataQualitySummary()"

    __str__ = __repr__


def build_completeness(line_items: tuple[CashFlowLineItem, ...]) -> CashFlowCompleteness:
    line_by_code = {item.line_code: item for item in line_items}
    statement_kinds = tuple(
        line_by_code[code].evidence_kind
        for code in CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1
    )
    counts = {kind: statement_kinds.count(kind) for kind in CashFlowEvidenceKind}
    available = sum(counts[kind] for kind in (
        CashFlowEvidenceKind.EXACT,
        CashFlowEvidenceKind.DERIVED,
        CashFlowEvidenceKind.ESTIMATED,
    ))
    optional_available = sum(
        line_by_code[code].canonical_amount is not None
        for code in CASH_FLOW_OPTIONAL_ANALYTICS_MANIFEST_V1
    )
    return CashFlowCompleteness(
        manifest_version=CASH_FLOW_COMPLETENESS_MANIFEST_VERSION,
        required_line_count=len(CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1),
        exact_count=counts[CashFlowEvidenceKind.EXACT],
        derived_count=counts[CashFlowEvidenceKind.DERIVED],
        estimated_count=counts[CashFlowEvidenceKind.ESTIMATED],
        unavailable_count=counts[CashFlowEvidenceKind.UNAVAILABLE],
        available_ratio=quantize_completeness_ratio(
            Decimal(available) / Decimal(len(CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1))
        ),
        optional_analytics_available_count=optional_available,
        optional_analytics_unavailable_count=(
            len(CASH_FLOW_OPTIONAL_ANALYTICS_MANIFEST_V1) - optional_available
        ),
    )


def assess_data_quality(
    *,
    inputs: IndirectCashFlowInput,
    line_items: tuple[CashFlowLineItem, ...],
    warnings: tuple[CashFlowIssue, ...],
    reconciliation_status: CashFlowReconciliationStatus,
    policy_version_mismatches: tuple[str, ...] = (),
    error_codes: tuple[CashFlowErrorCode, ...] = (),
) -> CashFlowDataQualitySummary:
    source_roles = {
        source.source_role
        for source in (
            inputs.current_balance_sheet,
            inputs.prior_balance_sheet,
            inputs.current_income_statement,
            inputs.current_trial_balance,
            inputs.prior_trial_balance,
        )
        if source is not None
    }
    unresolved = tuple(
        item for item in inputs.account_evidence
        if item.account_disposition is CashFlowAccountDisposition.UNRESOLVED
    )
    return CashFlowDataQualitySummary(
        missing_source_roles=tuple(role for role in CashFlowSourceRole if role not in source_roles),
        missing_line_inputs=tuple(
            (item.line_code, item.missing_inputs)
            for item in line_items
            if item.missing_inputs
        ),
        estimated_line_codes=tuple(
            item.line_code for item in line_items
            if item.evidence_kind is CashFlowEvidenceKind.ESTIMATED
        ),
        unavailable_line_codes=tuple(
            item.line_code for item in line_items
            if item.evidence_kind is CashFlowEvidenceKind.UNAVAILABLE
        ),
        unclassified_account_count=len(unresolved),
        unclassified_account_reference_digests=tuple(sorted(
            canonical_cash_flow_digest(item) for item in unresolved
        )),
        material_reconciliation_difference=(
            reconciliation_status is CashFlowReconciliationStatus.UNRECONCILED_MATERIAL
        ),
        policy_version_mismatches=tuple(sorted(policy_version_mismatches)),
        warning_codes=tuple(sorted(
            {issue.code for issue in warnings if type(issue.code) is CashFlowWarningCode},
            key=lambda code: code.value,
        )),
        error_codes=tuple(sorted(set(error_codes), key=lambda code: code.value)),
    )
