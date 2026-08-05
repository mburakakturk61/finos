"""Immutable V4 dependency graph; V3 registry remains untouched."""

from .types import (
    DependencyFailureBehaviorV4,
    DependencyRequirementV4,
    EngineInvocationSpecV4,
    OrchestrationEngineCodeV4 as E,
)

EXPECTED_NODE_COUNT_V4 = 12
EXPECTED_ALL_OF_EDGE_COUNT_V4 = 23
EXPECTED_ANY_OF_EDGE_COUNT_V4 = 2
EXPECTED_OPTIONAL_EDGE_COUNT_V4 = 4
EXPECTED_TOTAL_EDGE_COUNT_V4 = 29


def _spec(code, all_of=(), any_of=(), optional=(), produces="dict", critical=True, behavior=DependencyFailureBehaviorV4.SKIP):
    return EngineInvocationSpecV4(code, DependencyRequirementV4(all_of, any_of, optional), produces, critical, behavior)


ENGINE_DEPENDENCY_REGISTRY_V4 = {
    E.FS_BALANCE_SHEET: _spec(E.FS_BALANCE_SHEET, produces="BalanceSheetAnalysisOutcomeV3"),
    E.FS_INCOME_STATEMENT: _spec(E.FS_INCOME_STATEMENT, produces="IncomeStatementAnalysisOutcomeV3"),
    E.CASH_FLOW: _spec(E.CASH_FLOW, all_of=(E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT), produces="CashFlowResult", behavior=DependencyFailureBehaviorV4.INVOKE_DIAGNOSTIC_ONLY),
    E.RATIO: _spec(E.RATIO, any_of=(E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT), optional=(E.CASH_FLOW,)),
    E.BENCHMARK: _spec(E.BENCHMARK, all_of=(E.RATIO,)),
    E.HEALTH_SCORE: _spec(E.HEALTH_SCORE, all_of=(E.RATIO, E.BENCHMARK), produces="HealthScoreResult"),
    E.CREDIT_SCORE: _spec(E.CREDIT_SCORE, all_of=(E.RATIO, E.BENCHMARK, E.HEALTH_SCORE), produces="CreditScoreResult"),
    E.RECOMMENDATION: _spec(E.RECOMMENDATION, all_of=(E.RATIO, E.BENCHMARK, E.HEALTH_SCORE, E.CREDIT_SCORE), produces="RecommendationResult"),
    E.EXECUTIVE_REPORT: _spec(
        E.EXECUTIVE_REPORT,
        all_of=(E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT, E.RATIO, E.BENCHMARK, E.HEALTH_SCORE, E.CREDIT_SCORE, E.RECOMMENDATION),
        optional=(E.CASH_FLOW, E.MULTI_PERIOD_TREND),
        produces="ExecutiveReportResult",
        critical=False,
    ),
    E.DASHBOARD: _spec(E.DASHBOARD, all_of=(E.HEALTH_SCORE, E.CREDIT_SCORE, E.RECOMMENDATION), optional=(E.BENCHMARK,), produces="DashboardSnapshot", critical=False),
    E.RENDER_CONTRACT: _spec(E.RENDER_CONTRACT, all_of=(E.EXECUTIVE_REPORT,), produces="RenderContractPreview", critical=False),
    E.MULTI_PERIOD_TREND: _spec(E.MULTI_PERIOD_TREND, produces="TrendAnalysisResult"),
}


def validate_dependency_registry_v4(registry=ENGINE_DEPENDENCY_REGISTRY_V4) -> None:
    if tuple(registry) != tuple(E):
        raise ValueError("V4 graph engine manifest/order mismatch")
    for code, spec in registry.items():
        dependencies = spec.dependency.all_of + spec.dependency.any_of + spec.dependency.optional
        if code in dependencies or any(item not in registry for item in dependencies):
            raise ValueError("V4 graph contains invalid dependency")
    counts = (
        len(registry),
        sum(len(item.dependency.all_of) for item in registry.values()),
        sum(len(item.dependency.any_of) for item in registry.values()),
        sum(len(item.dependency.optional) for item in registry.values()),
    )
    if counts != (12, 23, 2, 4) or sum(counts[1:]) != 29:
        raise ValueError("V4 graph shape must be 12/23/2/4/29")


validate_dependency_registry_v4()
