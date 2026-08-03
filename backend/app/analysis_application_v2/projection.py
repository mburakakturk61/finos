"""Field-by-field Cash Flow engine-to-application projection."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from uuid import UUID

from app.engines.cash_flow.contracts import (
    CashFlowCashAvailabilityDisclosure,
    CashFlowCashAvailabilityObservation,
    CashFlowEndpointReconciliation,
    CashFlowEvidenceReference,
    CashFlowLineItem,
    CashFlowPeriodDescriptor,
    CashFlowResult,
)
from app.engines.cash_flow.types import CashFlowJsonObject

from . import contracts as c


def _enum(target: type[Enum], value: Enum):
    return target(value.value)


def _json(value):
    if type(value) is CashFlowJsonObject:
        return {key: _json(item) for key, item in value.items}
    if type(value) is tuple:
        return tuple(_json(item) for item in value)
    return value


def _period(value: CashFlowPeriodDescriptor) -> c.ApplicationCashFlowPeriodDescriptorDTO:
    return c.ApplicationCashFlowPeriodDescriptorDTO(
        period_id=value.period_id,
        company_id=value.company_id,
        tenant_id=value.tenant_id,
        currency_code=value.currency_code,
        monetary_unit_multiplier=value.monetary_unit_multiplier,
        period_type=c.ApplicationCashFlowPeriodTypeV2(value.period_type.value),
        start_date=value.start_date,
        end_date=value.end_date,
        annual_reporting_period_start_date=value.annual_reporting_period_start_date,
        annual_reporting_period_end_date=value.annual_reporting_period_end_date,
        months_covered=value.months_covered,
        status=c.ApplicationCashFlowPeriodStatusV2(value.status.value),
        accounting_basis_code=c.ApplicationCashFlowAccountingBasisCodeV2(value.accounting_basis_code.value),
        accounting_policy_version=value.accounting_policy_version,
        ifrs18_early_adopted=value.ifrs18_early_adopted,
    )


def _evidence(
    value: CashFlowEvidenceReference,
    same_run_owner: Callable[[str], UUID],
) -> c.ApplicationCashFlowEvidenceReferenceDTO:
    owner_id = value.source_analysis_result_id
    if owner_id is None:
        owner_id = same_run_owner(value.same_run_engine_code)
    return c.ApplicationCashFlowEvidenceReferenceDTO(
        evidence_kind=c.ApplicationCashFlowEvidenceKindV2(value.evidence_kind.value),
        source_role=c.ApplicationCashFlowSourceRoleV2(value.source_role.value),
        financial_analysis_result_id=owner_id,
        source_canonical_digest=value.source_canonical_digest,
        source_provenance_digest=value.source_provenance_digest,
        account_codes=value.account_codes,
        mapping_ids=value.mapping_ids,
        derivation_code=c.ApplicationCashFlowDerivationCodeV2(value.derivation_code.value),
    )


def _line(value: CashFlowLineItem, same_run_owner) -> c.ApplicationCashFlowLineItemDTO:
    return c.ApplicationCashFlowLineItemDTO(
        line_code=c.ApplicationCashFlowLineCodeV2(value.line_code.value),
        canonical_amount=value.canonical_amount,
        aggregation_role=c.ApplicationCashFlowLineAggregationRoleV2(value.aggregation_role.value),
        presentation_allocations=tuple(
            c.ApplicationCashFlowActivityAllocationDTO(
                c.ApplicationCashFlowActivityV2(item.activity.value), item.amount,
            )
            for item in value.presentation_allocations
        ),
        applicability=c.ApplicationCashFlowApplicabilityV2(value.applicability.value),
        evidence_kind=c.ApplicationCashFlowEvidenceKindV2(value.evidence_kind.value),
        evidence=tuple(_evidence(item, same_run_owner) for item in value.evidence),
        missing_inputs=value.missing_inputs,
        warning_codes=tuple(c.ApplicationCashFlowWarningCodeV2(item.value) for item in value.warning_codes),
    )


def _observation(value: CashFlowCashAvailabilityObservation, same_run_owner):
    return c.ApplicationCashAvailabilityObservationDTO(
        c.ApplicationCashFlowAvailabilityPeriodPositionV2(value.period_position.value),
        c.ApplicationCashAvailabilityClassificationV2(value.classification.value),
        value.amount,
        value.restriction_preserves_cash_nature,
        tuple(_evidence(item, same_run_owner) for item in value.evidence),
    )


def _disclosure(value: CashFlowCashAvailabilityDisclosure, same_run_owner):
    return c.ApplicationCashAvailabilityDisclosureDTO(
        value.component_reference_digest,
        c.ApplicationCashFlowAccountRoleV2(value.account_role.value),
        tuple(_observation(item, same_run_owner) for item in value.observations),
    )


def _endpoint(value: CashFlowEndpointReconciliation, same_run_owner):
    return c.ApplicationCashFlowEndpointReconciliationDTO(
        c.ApplicationCashFlowAvailabilityPeriodPositionV2(value.period_position.value),
        value.policy_defined_cash_and_cash_equivalents,
        value.reported_balance_sheet_cash_and_cash_equivalents,
        value.difference,
        c.ApplicationCashFlowEndpointReconciliationStatusV2(value.status.value),
        tuple(_evidence(item, same_run_owner) for item in value.balance_sheet_evidence),
    )


def project_cash_flow_result_v2(
    result: CashFlowResult,
    *,
    same_run_owner: Callable[[str], UUID],
) -> c.CashFlowProjectionDTOV2:
    """Project a verified result without recalculation or engine type leakage."""

    if type(result) is not CashFlowResult:
        raise TypeError("Cash Flow projection requires exact CashFlowResult")
    completeness = result.completeness
    projected = c.CashFlowProjectionDTOV2(
        opening_cash_and_cash_equivalents=result.opening_cash_and_cash_equivalents,
        closing_cash_and_cash_equivalents=result.closing_cash_and_cash_equivalents,
        operating_cash_flow=result.operating_cash_flow,
        investing_cash_flow=result.investing_cash_flow,
        financing_cash_flow=result.financing_cash_flow,
        authoritative_fx_effect=result.authoritative_fx_effect,
        authoritative_reclassification_effect=result.authoritative_reclassification_effect,
        calculated_net_cash_change=result.calculated_net_cash_change,
        balance_sheet_net_cash_change=result.balance_sheet_net_cash_change,
        reconciliation_difference=result.reconciliation_difference,
        free_cash_flow=result.free_cash_flow,
        status=c.ApplicationCashFlowStatusV2(result.status.value),
        reconciliation_status=c.ApplicationCashFlowReconciliationStatusV2(result.reconciliation_status.value),
        completeness=c.ApplicationCashFlowCompletenessDTO(
            completeness.manifest_version,
            completeness.required_line_count,
            completeness.exact_count,
            completeness.derived_count,
            completeness.estimated_count,
            completeness.unavailable_count,
            completeness.available_ratio,
            completeness.optional_analytics_available_count,
            completeness.optional_analytics_unavailable_count,
        ),
        currency_code=result.currency_code,
        monetary_scale=result.monetary_scale,
        policy_version=result.policy_version,
        accounting_policy_version=result.accounting_policy_version,
        cash_equivalent_policy_version=result.cash_equivalent_policy_version,
        presentation_policy_version=result.presentation_policy_version,
        reconciliation_policy_version=result.reconciliation_policy_version,
        mapping_registry_version=result.mapping_registry_version,
        current_period_id=result.current_period_id,
        prior_period_id=result.prior_period_id,
        current_period_descriptor=_period(result.current_period_descriptor),
        prior_period_descriptor=_period(result.prior_period_descriptor) if result.prior_period_descriptor else None,
        current_period_descriptor_digest=result.current_period_descriptor_digest,
        prior_period_descriptor_digest=result.prior_period_descriptor_digest,
        comparability_proof_digest=result.comparability_proof_digest,
        line_items=tuple(_line(item, same_run_owner) for item in result.line_items),
        cash_availability_disclosures=tuple(_disclosure(item, same_run_owner) for item in result.cash_availability_disclosures),
        endpoint_reconciliations=tuple(_endpoint(item, same_run_owner) for item in result.endpoint_reconciliations),
        evidence=tuple(_evidence(item, same_run_owner) for item in result.evidence),
        warnings=tuple(
            c.ApplicationCashFlowIssueDTO(c.ApplicationCashFlowWarningCodeV2(item.code.value), _json(item.safe_metadata))
            for item in result.warnings
        ),
        errors=(),
        source_lineage_references=tuple(
            c.ApplicationCashFlowLineageReferenceDTO(
                c.ApplicationCashFlowSourceRoleV2(item.source_role.value),
                item.source_analysis_result_id if item.source_analysis_result_id is not None else same_run_owner(item.same_run_engine_code),
                item.source_period_id,
                item.canonical_digest,
                item.source_provenance_digest,
            )
            for item in result.source_lineage_references
        ),
        cash_flow_schema_version=result.cash_flow_schema_version,
        cash_flow_model_version=result.cash_flow_model_version,
    )
    return projected
