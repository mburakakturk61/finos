"""Post-result financial owner planning for the V3 phased persistence path."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from app.engines.analysis_orchestrator_v3.types import (
    EngineExecutionStatusV3,
    OrchestrationEngineCodeV3,
    OrchestrationJsonObjectV3,
    OrchestrationRunResultV3,
)
from app.engines.cash_flow.contracts import CashFlowPreResolvedContext, CashFlowResult
from app.engines.cash_flow.types import CashFlowSourceRole
from app.models.enums import AnalysisSourceRole, AnalysisType
from app.orchestration_persistence.codec import canonical_json_bytes
from app.orchestration_persistence_v3.cash_flow_codec import (
    cash_flow_owner_content_digest,
    encode_cash_flow_financial_result,
)

from .contracts import ApplicationEngineCodeV2, ApplicationFinancialSourceModeV2, FinancialSourceIntentDTOV2
from .ports import (
    PlannedCashFlowLineageEdgeV3,
    PlannedSamePeriodSourceEdgeV3,
    ResolvedFinancialOwnerNodeV3,
    ResolvedFinancialOwnershipPlanV3,
)

_ALIVE = {EngineExecutionStatusV3.COMPLETED, EngineExecutionStatusV3.DEGRADED, EngineExecutionStatusV3.REUSED}
_ROLE_TYPE = {
    CashFlowSourceRole.CURRENT_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.PRIOR_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.CURRENT_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    CashFlowSourceRole.CURRENT_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    CashFlowSourceRole.PRIOR_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
}


def _plain_payload(value):
    if type(value) is OrchestrationJsonObjectV3:
        return {key: _plain_payload(item) for key, item in value.items}
    if type(value) is tuple:
        return [_plain_payload(item) for item in value]
    return value


def _owner_content_digest(engine_code: OrchestrationEngineCodeV3, result: object) -> str:
    if type(result) is CashFlowResult:
        return cash_flow_owner_content_digest(result)
    if engine_code in {
        OrchestrationEngineCodeV3.FS_BALANCE_SHEET,
        OrchestrationEngineCodeV3.FS_INCOME_STATEMENT,
    }:
        projection = {
            "status": result.status,
            "source_mode": result.source_mode,
            "result_json": _plain_payload(result.result_json),
            "error_message": result.error_message,
            "trial_balance_usage": result.trial_balance_usage,
        }
        return sha256(canonical_json_bytes(projection)).hexdigest()
    if engine_code is OrchestrationEngineCodeV3.RATIO:
        return sha256(canonical_json_bytes(_plain_payload(result))).hexdigest()
    raise ValueError("financial owner digest requested for artifact engine")


def _same_period(intent: FinancialSourceIntentDTOV2) -> tuple[PlannedSamePeriodSourceEdgeV3, ...]:
    return tuple(
        PlannedSamePeriodSourceEdgeV3(
            role=AnalysisSourceRole(item.role.value),
            source_document_id=item.source_document_id,
            existing_source_analysis_result_id=item.source_analysis_result_id,
            same_run_source_engine_code=item.source_engine_code,
        )
        for item in intent.source_bindings
    )


def _snapshot_index(context: CashFlowPreResolvedContext) -> dict:
    values = (
        context.prior_balance_sheet,
        context.current_trial_balance,
        context.prior_trial_balance,
    )
    return {
        item.analysis_result_id: item
        for item in values
        if item is not None and item.analysis_result_id is not None
    }


def _cash_flow_lineage(result: CashFlowResult, context: CashFlowPreResolvedContext, records) -> tuple[PlannedCashFlowLineageEdgeV3, ...]:
    snapshots = _snapshot_index(context)
    engine_versions = {
        item.engine_code.value: item.engine_model_version_used
        for item in records
        if item.engine_model_version_used is not None
    }
    edges = []
    for item in result.source_lineage_references:
        same_run = ApplicationEngineCodeV2(item.same_run_engine_code) if item.same_run_engine_code else None
        existing = item.source_analysis_result_id
        if same_run is not None:
            source_engine_version = engine_versions.get(same_run.value)
        else:
            snapshot = snapshots.get(existing)
            source_engine_version = snapshot.engine_model_version if snapshot is not None else None
        if not source_engine_version:
            raise ValueError("Cash Flow lineage engine version cannot be resolved")
        edges.append(PlannedCashFlowLineageEdgeV3(
            source_role=item.source_role,
            existing_source_analysis_result_id=existing,
            same_run_source_engine_code=same_run,
            source_period_id=item.source_period_id,
            source_canonical_digest=item.canonical_digest,
            source_provenance_digest=item.source_provenance_digest,
            source_analysis_type=_ROLE_TYPE[item.source_role],
            source_engine_version=source_engine_version,
            current_period_descriptor_digest=result.current_period_descriptor_digest,
            prior_period_descriptor_digest=result.prior_period_descriptor_digest,
            comparability_proof_digest=result.comparability_proof_digest,
        ))
    return tuple(edges)


def resolve_financial_ownership_plan_v3(
    run_result: OrchestrationRunResultV3,
    source_intents: tuple[FinancialSourceIntentDTOV2, ...],
    pre_resolved_context: CashFlowPreResolvedContext | None,
    *,
    started_at: datetime,
    completed_at: datetime,
) -> ResolvedFinancialOwnershipPlanV3:
    """Create owner intent only from actual post-execution V3 records."""

    if type(run_result) is not OrchestrationRunResultV3:
        raise TypeError("ownership planning requires exact V3 run result")
    intents = {item.engine_code: item for item in source_intents}
    if len(intents) != len(source_intents):
        raise ValueError("duplicate financial source intent")
    nodes = []
    for record in run_result.engine_records:
        if record.engine_code not in {
            OrchestrationEngineCodeV3.FS_BALANCE_SHEET,
            OrchestrationEngineCodeV3.FS_INCOME_STATEMENT,
            OrchestrationEngineCodeV3.CASH_FLOW,
            OrchestrationEngineCodeV3.RATIO,
        } or record.status not in _ALIVE or record.result is None:
            continue
        code = ApplicationEngineCodeV2(record.engine_code.value)
        value = record.result.result
        if record.engine_code is OrchestrationEngineCodeV3.CASH_FLOW:
            if type(value) is not CashFlowResult or pre_resolved_context is None:
                raise ValueError("Cash Flow owner requires result and trusted pre-resolution context")
            _node, canonical = encode_cash_flow_financial_result(value)
            lineage = _cash_flow_lineage(value, pre_resolved_context, run_result.engine_records)
            nodes.append(ResolvedFinancialOwnerNodeV3(
                engine_code=code,
                expected_existing_owner_id=None,
                allow_existing_canonical_owner=True,
                create_new_owner=True,
                primary_document_id=None,
                source_mode=ApplicationFinancialSourceModeV2.MULTI_SOURCE_DERIVED,
                same_period_lineage_plan=(),
                cash_flow_lineage_plan=lineage,
                expected_canonical_result_digest=canonical,
                expected_owner_content_digest=_owner_content_digest(record.engine_code, value),
                expected_current_period_descriptor_digest=value.current_period_descriptor_digest,
                expected_prior_period_descriptor_digest=value.prior_period_descriptor_digest,
                expected_comparability_proof_digest=value.comparability_proof_digest,
            ))
            continue
        intent = intents.get(code)
        if intent is None:
            raise ValueError("successful financial execution has no source intent")
        same_period_lineage = _same_period(intent)
        if record.engine_code is OrchestrationEngineCodeV3.RATIO:
            cash_record = next(
                (
                    item
                    for item in run_result.engine_records
                    if item.engine_code is OrchestrationEngineCodeV3.CASH_FLOW
                ),
                None,
            )
            if (
                cash_record is not None
                and cash_record.status in _ALIVE
                and cash_record.result is not None
                and type(cash_record.result.result) is CashFlowResult
            ):
                same_period_lineage += (PlannedSamePeriodSourceEdgeV3(
                    role=AnalysisSourceRole.SUPPORTING_ANALYSIS,
                    source_document_id=None,
                    existing_source_analysis_result_id=None,
                    same_run_source_engine_code=ApplicationEngineCodeV2.CASH_FLOW,
                ),)
        result_payload = getattr(value, "result_json", value)
        canonical = (
            sha256(canonical_json_bytes(_plain_payload(result_payload))).hexdigest()
            if result_payload is not None else None
        )
        nodes.append(ResolvedFinancialOwnerNodeV3(
            engine_code=code,
            expected_existing_owner_id=intent.expected_existing_owner_id,
            allow_existing_canonical_owner=intent.allow_existing_canonical_owner,
            create_new_owner=intent.expected_existing_owner_id is None,
            primary_document_id=intent.primary_document_id,
            source_mode=intent.requested_source_mode,
            same_period_lineage_plan=same_period_lineage,
            cash_flow_lineage_plan=(),
            expected_canonical_result_digest=canonical,
            expected_owner_content_digest=_owner_content_digest(record.engine_code, value),
            expected_current_period_descriptor_digest=None,
            expected_prior_period_descriptor_digest=None,
            expected_comparability_proof_digest=None,
        ))
    return ResolvedFinancialOwnershipPlanV3(tuple(nodes), started_at, completed_at)
