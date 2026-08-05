"""Executable V4 dispatch; legacy callable references remain unchanged."""

from typing import Any, Callable

from app.engines.analysis_orchestrator_v3.dispatch import ORCHESTRATOR_ENGINE_DISPATCH_V3
from app.engines.executive_reports.trend_integration import generate_executive_report_v1_2
from app.engines.multi_period_trend import assemble_multi_period_trend_result

from .registry import ENGINE_DEPENDENCY_REGISTRY_V4
from .types import OrchestrationEngineCodeV4 as E, TrendPreResolvedContextV1


def analyze_multi_period_trend_v4(*, pre_resolved_context: TrendPreResolvedContextV1):
    if type(pre_resolved_context) is not TrendPreResolvedContextV1:
        raise TypeError("Trend dispatch requires exact trusted V4 context")
    return assemble_multi_period_trend_result(
        pre_resolved_context.resolved_series,
        pre_resolved_context.comparability_profile,
        expected_metric_codes=pre_resolved_context.expected_metric_codes,
        unavailable_metrics=pre_resolved_context.unavailable_metrics,
    )


ORCHESTRATOR_ENGINE_DISPATCH_V4: dict[E, Callable[..., Any]] = {
    code: (
        analyze_multi_period_trend_v4
        if code is E.MULTI_PERIOD_TREND
        else generate_executive_report_v1_2
        if code is E.EXECUTIVE_REPORT
        else ORCHESTRATOR_ENGINE_DISPATCH_V3[next(item for item in ORCHESTRATOR_ENGINE_DISPATCH_V3 if item.value == code.value)]
    )
    for code in ENGINE_DEPENDENCY_REGISTRY_V4
}


def validate_dispatch_v4(dispatch=ORCHESTRATOR_ENGINE_DISPATCH_V4) -> None:
    if tuple(dispatch) != tuple(ENGINE_DEPENDENCY_REGISTRY_V4):
        raise ValueError("V4 dispatch and graph manifests/order differ")
    if len(dispatch) != len(set(dispatch)) or any(not callable(item) for item in dispatch.values()):
        raise ValueError("V4 dispatch contains duplicate/non-callable entry")


validate_dispatch_v4()
