"""Immutable V3 dependency graph; legacy registry remains untouched."""

from .types import (
    DependencyFailureBehaviorV3,
    DependencyRequirementV3,
    EngineInvocationSpecV3,
    OrchestrationEngineCodeV3 as E,
)

EXPECTED_NODE_COUNT_V3 = 11
EXPECTED_ALL_OF_EDGE_COUNT_V3 = 23
EXPECTED_ANY_OF_EDGE_COUNT_V3 = 2
EXPECTED_OPTIONAL_EDGE_COUNT_V3 = 3
EXPECTED_TOTAL_EDGE_COUNT_V3 = 28


class DependencyRegistryV3Error(ValueError):
    pass


def _spec(code, all_of=(), any_of=(), optional=(), produces="dict", critical=True, behavior=DependencyFailureBehaviorV3.SKIP):
    return EngineInvocationSpecV3(code, DependencyRequirementV3(all_of, any_of, optional), produces, critical, behavior)


ENGINE_DEPENDENCY_REGISTRY_V3 = {
    E.FS_BALANCE_SHEET: _spec(E.FS_BALANCE_SHEET, produces="BalanceSheetAnalysisOutcomeV3"),
    E.FS_INCOME_STATEMENT: _spec(E.FS_INCOME_STATEMENT, produces="IncomeStatementAnalysisOutcomeV3"),
    E.CASH_FLOW: _spec(
        E.CASH_FLOW,
        all_of=(E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT),
        produces="CashFlowResult",
        behavior=DependencyFailureBehaviorV3.INVOKE_DIAGNOSTIC_ONLY,
    ),
    E.RATIO: _spec(E.RATIO, any_of=(E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT), optional=(E.CASH_FLOW,)),
    E.BENCHMARK: _spec(E.BENCHMARK, all_of=(E.RATIO,)),
    E.HEALTH_SCORE: _spec(E.HEALTH_SCORE, all_of=(E.RATIO, E.BENCHMARK), produces="HealthScoreResult"),
    E.CREDIT_SCORE: _spec(E.CREDIT_SCORE, all_of=(E.RATIO, E.BENCHMARK, E.HEALTH_SCORE), produces="CreditScoreResult"),
    E.RECOMMENDATION: _spec(E.RECOMMENDATION, all_of=(E.RATIO, E.BENCHMARK, E.HEALTH_SCORE, E.CREDIT_SCORE), produces="RecommendationResult"),
    E.EXECUTIVE_REPORT: _spec(
        E.EXECUTIVE_REPORT,
        all_of=(E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT, E.RATIO, E.BENCHMARK, E.HEALTH_SCORE, E.CREDIT_SCORE, E.RECOMMENDATION),
        optional=(E.CASH_FLOW,), produces="ExecutiveReportResult", critical=False,
    ),
    E.DASHBOARD: _spec(E.DASHBOARD, all_of=(E.HEALTH_SCORE, E.CREDIT_SCORE, E.RECOMMENDATION), optional=(E.BENCHMARK,), produces="DashboardSnapshot", critical=False),
    E.RENDER_CONTRACT: _spec(E.RENDER_CONTRACT, all_of=(E.EXECUTIVE_REPORT,), produces="RenderContractPreview", critical=False),
}


def validate_dependency_registry_v3(registry=ENGINE_DEPENDENCY_REGISTRY_V3) -> None:
    if set(registry) != set(E):
        raise DependencyRegistryV3Error("V3 graph engine manifest mismatch")
    for code, spec in registry.items():
        deps = spec.dependency.all_of + spec.dependency.any_of + spec.dependency.optional
        if code in deps or any(dep not in registry for dep in deps):
            raise DependencyRegistryV3Error("V3 graph contains invalid dependency")
    counts = (
        len(registry),
        sum(len(s.dependency.all_of) for s in registry.values()),
        sum(len(s.dependency.any_of) for s in registry.values()),
        sum(len(s.dependency.optional) for s in registry.values()),
    )
    if counts != (11, 23, 2, 3) or sum(counts[1:]) != 28:
        raise DependencyRegistryV3Error("V3 graph shape must be 11/23/2/3/28")


validate_dependency_registry_v3()
