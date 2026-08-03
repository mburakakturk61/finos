"""Deterministic alphabetical-ready V3 execution planning."""

from .registry import ENGINE_DEPENDENCY_REGISTRY_V3, validate_dependency_registry_v3
from .types import OrchestrationEngineCodeV3


def get_execution_plan_v3(registry=ENGINE_DEPENDENCY_REGISTRY_V3) -> tuple[OrchestrationEngineCodeV3, ...]:
    validate_dependency_registry_v3(registry)
    remaining = set(registry)
    done: set[OrchestrationEngineCodeV3] = set()
    result = []
    while remaining:
        ready = sorted(
            (code for code in remaining if set(
                registry[code].dependency.all_of
                + registry[code].dependency.any_of
                + registry[code].dependency.optional
            ) <= done),
            key=lambda code: code.value,
        )
        if not ready:
            raise ValueError("V3 graph is cyclic")
        for code in ready:
            result.append(code)
            remaining.remove(code)
            done.add(code)
    return tuple(result)


EXECUTION_PLAN_V3 = get_execution_plan_v3()
