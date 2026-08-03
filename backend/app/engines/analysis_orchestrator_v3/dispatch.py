"""Executable V3 dispatch kept separate from graph metadata."""

from typing import Any, Callable

from app.engines.analysis_orchestrator.dispatch import ORCHESTRATOR_ENGINE_DISPATCH
from app.engines.analysis_orchestrator.types import EngineCode
from app.engines.cash_flow.adapter import build_indirect_cash_flow_input
from app.engines.cash_flow.service import CashFlowEngineService
from app.engines.financial_ratios.cash_flow_integration import analyze_financial_ratios_v3
from app.engines.executive_reports.cash_flow_integration import generate_executive_report_v1_1

from .registry import ENGINE_DEPENDENCY_REGISTRY_V3
from .types import OrchestrationEngineCodeV3 as E


def analyze_cash_flow_v3(*, pre_resolved_context, current_balance_sheet, current_income_statement):
    inputs = build_indirect_cash_flow_input(
        pre_resolved_context, current_balance_sheet, current_income_statement,
    )
    return CashFlowEngineService().analyze(
        inputs,
        comparability_proof_digest=pre_resolved_context.comparability_proof_digest,
    )


ORCHESTRATOR_ENGINE_DISPATCH_V3: dict[E, Callable[..., Any]] = {
    E(code.value): callable_ for code, callable_ in ORCHESTRATOR_ENGINE_DISPATCH.items()
}
ORCHESTRATOR_ENGINE_DISPATCH_V3[E.CASH_FLOW] = analyze_cash_flow_v3
ORCHESTRATOR_ENGINE_DISPATCH_V3[E.RATIO] = analyze_financial_ratios_v3
ORCHESTRATOR_ENGINE_DISPATCH_V3[E.EXECUTIVE_REPORT] = generate_executive_report_v1_1


def validate_dispatch_v3(dispatch=ORCHESTRATOR_ENGINE_DISPATCH_V3) -> None:
    if set(dispatch) != set(ENGINE_DEPENDENCY_REGISTRY_V3):
        raise ValueError("V3 dispatch and graph manifests differ")
    if len(dispatch) != len(set(dispatch)) or any(not callable(item) for item in dispatch.values()):
        raise ValueError("V3 dispatch contains duplicate/non-callable entry")


validate_dispatch_v3()
