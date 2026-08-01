"""
Milestone 5.0A -- Execution Plan Derivation (Bolum 37).

Denetim bulgusu D1'in kok-neden cozumu: `ENGINE_DEPENDENCY_REGISTRY` TEK
source of truth'tur. Calistirma sirasi, HER cagride bu registry'den
deterministik bir topological sort ile TURETILIR -- elle yazilmis,
registry'den bagimsiz IKINCI bir "plan" sabiti (ornegin EXECUTION_PLAN_
REGISTRY) v1'de YOKTUR.

Tie-break kurali (Bolum 37, kesin): esit-seviyeli (ayni anda "hazir")
dugumler arasindaki sira `EngineCode.value`'nun ALFABETIK sirasina gore
belirlenir -- bu, registry insertion-order'dan TAMAMEN bagimsiz,
deterministik bir kuraldir.
"""

from __future__ import annotations

from app.engines.analysis_orchestrator.registry import (
    ENGINE_DEPENDENCY_REGISTRY,
    DependencyCycleError,
)
from app.engines.analysis_orchestrator.types import EngineCode, EngineInvocationSpec


def _all_dependencies(spec: EngineInvocationSpec) -> "frozenset[EngineCode]":
    return frozenset(spec.dependency.all_of) | frozenset(spec.dependency.any_of) | frozenset(
        spec.dependency.optional
    )


def derive_execution_plan(
    registry: "dict[EngineCode, EngineInvocationSpec] | None" = None,
) -> "tuple[EngineCode, ...]":
    """
    Kahn algoritmasinin deterministik (alfabetik tie-break'li) versiyonu.
    v1 tamamen sirali oldugu icin (Bolum 6/7) sonuc DUZ bir tuple'dir --
    "asama" (stage/paralel grup) kavrami v1'de YOKTUR.
    """

    reg = ENGINE_DEPENDENCY_REGISTRY if registry is None else registry

    remaining_deps: "dict[EngineCode, set[EngineCode]]" = {
        code: set(_all_dependencies(spec)) for code, spec in reg.items()
    }
    plan: "list[EngineCode]" = []

    while remaining_deps:
        ready = sorted(
            (code for code, deps in remaining_deps.items() if not deps),
            key=lambda code: code.value,
        )
        if not ready:
            raise DependencyCycleError(
                "Execution plan turetilemedi -- ENGINE_DEPENDENCY_REGISTRY dongu iceriyor."
            )
        next_code = ready[0]
        plan.append(next_code)
        del remaining_deps[next_code]
        for deps in remaining_deps.values():
            deps.discard(next_code)

    return tuple(plan)


_CACHED_DEFAULT_PLAN: "tuple[EngineCode, ...] | None" = None


def get_execution_plan() -> "tuple[EngineCode, ...]":
    """Varsayilan (module-level `ENGINE_DEPENDENCY_REGISTRY`) plani
    onbellekten dondurur -- onbellek HER ZAMAN registry'den turetilmis
    sonucun bir performans optimizasyonudur, BAGIMSIZ bir ikinci kaynak
    DEGILDIR (Bolum 37)."""

    global _CACHED_DEFAULT_PLAN
    if _CACHED_DEFAULT_PLAN is None:
        _CACHED_DEFAULT_PLAN = derive_execution_plan()
    return _CACHED_DEFAULT_PLAN


def _reset_plan_cache_for_tests() -> None:
    """Yalnizca test izolasyonu icin -- ENGINE_DEPENDENCY_REGISTRY test
    icinde gecici olarak degistirildiginde onbellegin bayatlamamasi icin
    cagirilir."""

    global _CACHED_DEFAULT_PLAN
    _CACHED_DEFAULT_PLAN = None
