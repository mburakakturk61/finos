"""Deterministic V4 execution plan."""

from .registry import ENGINE_DEPENDENCY_REGISTRY_V4, validate_dependency_registry_v4
from .types import OrchestrationEngineCodeV4


def get_execution_plan_v4(registry=ENGINE_DEPENDENCY_REGISTRY_V4) -> tuple[OrchestrationEngineCodeV4, ...]:
    validate_dependency_registry_v4(registry)
    remaining = set(registry)
    completed: set[OrchestrationEngineCodeV4] = set()
    result = []
    while remaining:
        ready = sorted(
            (
                code for code in remaining
                if set(
                    registry[code].dependency.all_of
                    + registry[code].dependency.any_of
                    + registry[code].dependency.optional
                ) <= completed
            ),
            key=lambda code: code.value,
        )
        if not ready:
            raise ValueError("V4 graph is cyclic")
        for code in ready:
            result.append(code)
            remaining.remove(code)
            completed.add(code)
    return tuple(result)


EXECUTION_PLAN_V4 = get_execution_plan_v4()
