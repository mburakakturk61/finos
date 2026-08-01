"""Pure post-result financial ownership planning; no persistence imports."""

from __future__ import annotations

from app.analysis_application.contracts import (
    ApplicationEngineCode,
    ApplicationScopeDTO,
    FinancialSourceIntentDTO,
)
from app.analysis_application.internal_types import (
    ResolvedFinancialLineageEdge,
    ResolvedFinancialOwnerNode,
    ResolvedFinancialOwnershipPlan,
    OwnerAuditTimes,
)
from app.engines.analysis_orchestrator.types import EngineExecutionStatus, OrchestrationRunResult

_OWNER_STATUSES = frozenset({EngineExecutionStatus.COMPLETED, EngineExecutionStatus.DEGRADED})


def resolve_financial_ownership_plan(
    run_result: OrchestrationRunResult,
    source_intents: tuple[FinancialSourceIntentDTO, ...],
    scope: ApplicationScopeDTO,
    audit_times: OwnerAuditTimes,
) -> ResolvedFinancialOwnershipPlan:
    intents = {intent.engine_code: intent for intent in source_intents}
    if len(intents) != len(source_intents):
        raise ValueError("Duplicate financial source intent.")
    nodes = []
    result_codes = {ApplicationEngineCode(record.engine_code.value) for record in run_result.engine_records}
    if not set(intents) <= result_codes:
        raise ValueError("Financial intent has no corresponding execution record.")
    for record in run_result.engine_records:
        code = ApplicationEngineCode(record.engine_code.value)
        if code not in intents:
            if code in _financial_codes() and record.status in _OWNER_STATUSES and record.result is not None:
                raise ValueError("Successful financial execution is missing source intent.")
            continue
        intent = intents[code]
        if (intent.company_id, intent.financial_period_id) != (scope.company_id, scope.financial_period_id):
            raise ValueError("Financial source intent scope mismatch.")
        if record.status not in _OWNER_STATUSES or record.result is None:
            continue
        nodes.append(ResolvedFinancialOwnerNode(
            engine_code=code,
            expected_existing_owner_id=intent.expected_existing_owner_id,
            allow_existing_canonical_owner=intent.allow_existing_canonical_owner,
            create_new_owner=intent.expected_existing_owner_id is None,
            primary_document_id=intent.primary_document_id,
            source_mode=intent.requested_source_mode,
            lineage=tuple(ResolvedFinancialLineageEdge(
                item.role, item.source_document_id,
                item.source_analysis_result_id, item.source_engine_code,
            ) for item in intent.source_bindings),
        ))
    order = {
        ApplicationEngineCode.FS_BALANCE_SHEET: 0,
        ApplicationEngineCode.FS_INCOME_STATEMENT: 1,
        ApplicationEngineCode.RATIO: 2,
    }
    return ResolvedFinancialOwnershipPlan(
        tuple(sorted(nodes, key=lambda node: order[node.engine_code])), audit_times
    )


def _financial_codes() -> frozenset[ApplicationEngineCode]:
    return frozenset({
        ApplicationEngineCode.FS_BALANCE_SHEET,
        ApplicationEngineCode.FS_INCOME_STATEMENT,
        ApplicationEngineCode.RATIO,
    })
