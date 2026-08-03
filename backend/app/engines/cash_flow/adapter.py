"""Pure boundary adapter from V3 resolved context to the 4.5 engine input."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

from app.models.enums import AnalysisStatus, AnalysisType

from .contracts import (
    CashFlowPreResolvedContext,
    CashFlowSourceSnapshot,
    IndirectCashFlowInput,
    canonical_cash_flow_bytes,
)
from .errors import CashFlowContractError
from .types import (
    CashFlowJsonObject,
    CashFlowSourceMode,
    CashFlowSourceRole,
    CashFlowStatementBasis,
)


def _json_object(value: object) -> CashFlowJsonObject:
    if type(value) is CashFlowJsonObject:
        return value
    if type(value) is not dict:
        raise CashFlowContractError("financial statement payload must be an object")
    items = []
    for key in sorted(value):
        item = value[key]
        if type(item) is float:
            raise CashFlowContractError("float is not accepted at Cash Flow boundary")
        if type(item) is dict:
            item = _json_object(item)
        elif type(item) is list:
            raise CashFlowContractError("mutable list is not accepted at Cash Flow boundary")
        items.append((key, item))
    return CashFlowJsonObject(tuple(items))


def _snapshot(context, outcome, *, role, analysis_type, engine_code, basis):
    if outcome is None or getattr(outcome, "result_json", None) is None:
        return None
    payload = _json_object(outcome.result_json)
    digest = sha256(canonical_cash_flow_bytes(payload)).hexdigest()
    source_mode = CashFlowSourceMode(getattr(outcome.source_mode, "value", outcome.source_mode))
    start = context.current_period.start_date if basis is CashFlowStatementBasis.FLOW_INTERVAL else None
    return CashFlowSourceSnapshot(
        source_role=role,
        analysis_result_id=None,
        same_run_engine_code=engine_code,
        analysis_type=analysis_type,
        source_mode=source_mode,
        company_id=context.current_period.company_id,
        period_id=context.current_period.period_id,
        primary_document_id=None,
        canonical_digest=digest,
        recomputed_result_payload_digest=digest,
        source_provenance_digest=context.pre_resolved_evidence_bundle_digest,
        engine_schema_version=None,
        engine_model_version=str(dict(payload.items).get("engine_version", "1.0.0")),
        status=AnalysisStatus.COMPLETED,
        error_message_is_null=getattr(outcome, "error_message", None) is None,
        statement_basis=basis,
        coverage_start_date=start,
        coverage_end_date=context.current_period.end_date,
        currency_code="TRY",
        monetary_unit_multiplier=Decimal("1"),
        result_payload=payload,
    )


def build_indirect_cash_flow_input(
    pre_resolved: CashFlowPreResolvedContext,
    current_balance_sheet: object,
    current_income_statement: object,
) -> IndirectCashFlowInput:
    if type(pre_resolved) is not CashFlowPreResolvedContext:
        raise CashFlowContractError("pre-resolved Cash Flow context is required")
    current_bs = _snapshot(
        pre_resolved, current_balance_sheet,
        role=CashFlowSourceRole.CURRENT_BALANCE_SHEET,
        analysis_type=AnalysisType.BALANCE_SHEET,
        engine_code="fs_balance_sheet",
        basis=CashFlowStatementBasis.AS_OF,
    )
    current_is = _snapshot(
        pre_resolved, current_income_statement,
        role=CashFlowSourceRole.CURRENT_INCOME_STATEMENT,
        analysis_type=AnalysisType.INCOME_STATEMENT,
        engine_code="fs_income_statement",
        basis=CashFlowStatementBasis.FLOW_INTERVAL,
    )
    return IndirectCashFlowInput(
        current_period=pre_resolved.current_period,
        prior_period=pre_resolved.prior_period,
        current_balance_sheet=current_bs,
        prior_balance_sheet=pre_resolved.prior_balance_sheet,
        current_income_statement=current_is,
        current_trial_balance=pre_resolved.current_trial_balance,
        prior_trial_balance=pre_resolved.prior_trial_balance,
        account_evidence=pre_resolved.account_evidence,
        noncash_bridge_components=pre_resolved.noncash_bridge_components,
        account_evidence_bundle_digest=pre_resolved.pre_resolved_evidence_bundle_digest,
        opening_account_coverage_complete=pre_resolved.opening_account_coverage_complete,
        closing_account_coverage_complete=pre_resolved.closing_account_coverage_complete,
        mapping_registry_version=pre_resolved.mapping_registry_version,
        accounting_policy_version=pre_resolved.accounting_policy_version,
        presentation_policy=pre_resolved.presentation_policy,
    )
