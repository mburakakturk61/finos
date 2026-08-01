"""
Milestone 5.0A -- ENGINE_DEPENDENCY_REGISTRY (Bolum 35).

TEK sorumlulugu: hangi motorun hangi motora (all_of/any_of/optional
olarak) bagimli oldugunu tanimlamak. Bu modul HICBIR calistirilabilir
referans (Callable) TASIMAZ -- gercek motor cagirimlari dispatch.py'dedir
(Bolum 18/36, denetim bulgusu H1'in kok-neden cozumu).

Kayit deseni, diger app.engines.common.*_registry moduleriyle AYNIDIR
(register_* + opsiyonel registry= parametresi + _build_registry()) --
boylece tests/conftest.py'nin mevcut snapshot/restore LIFO zincirine ayni
disiplinle eklenebilir (Bolum 65).
"""

from __future__ import annotations

from app.engines.analysis_orchestrator.types import (
    DependencyRequirement,
    EngineCode,
    EngineInvocationSpec,
)


class UnknownEngineDependencyError(ValueError):
    pass


class SelfDependencyError(ValueError):
    pass


class DependencyCycleError(ValueError):
    pass


class DependencyRegistryShapeError(ValueError):
    """Bolum 4 checklist'indeki sabit dugum/kenar sayilarindan biri
    saglanmadiginda firlatilir."""


ENGINE_DEPENDENCY_REGISTRY: "dict[EngineCode, EngineInvocationSpec]" = {}

# Bolum 4 -- kayit-ani doguelanmasi gereken sabit sayilar.
EXPECTED_NODE_COUNT = 10
EXPECTED_ALL_OF_EDGE_COUNT = 21
EXPECTED_ANY_OF_EDGE_COUNT = 2
EXPECTED_OPTIONAL_EDGE_COUNT = 1
EXPECTED_TOTAL_EDGE_COUNT = (
    EXPECTED_ALL_OF_EDGE_COUNT + EXPECTED_ANY_OF_EDGE_COUNT + EXPECTED_OPTIONAL_EDGE_COUNT
)


def register_engine_invocation_spec(
    spec: EngineInvocationSpec,
    *,
    registry: "dict[EngineCode, EngineInvocationSpec] | None" = None,
) -> None:
    target = ENGINE_DEPENDENCY_REGISTRY if registry is None else registry
    if spec.engine_code in target:
        raise ValueError(f"engine_code zaten kayitli: {spec.engine_code!r}")

    all_deps = spec.dependency.all_of + spec.dependency.any_of + spec.dependency.optional
    if spec.engine_code in all_deps:
        raise SelfDependencyError(
            f"{spec.engine_code!r} kendi bagimliligi olamaz (self-dependency)."
        )

    target[spec.engine_code] = spec


def _topologically_sortable(registry: "dict[EngineCode, EngineInvocationSpec]") -> bool:
    """Kahn algoritmasiyla dongu tespiti -- yalnizca dogru/yanlis doner,
    siralamayi URETMEZ (siralama execution_plan.py'nin sorumlulugu)."""

    in_degree: "dict[EngineCode, int]" = {code: 0 for code in registry}
    for code, spec in registry.items():
        deps = spec.dependency.all_of + spec.dependency.any_of + spec.dependency.optional
        in_degree[code] = len(set(deps))

    ready = [code for code, deg in in_degree.items() if deg == 0]
    visited = 0
    remaining_in_degree = dict(in_degree)
    while ready:
        current = ready.pop()
        visited += 1
        for code, spec in registry.items():
            deps = set(spec.dependency.all_of + spec.dependency.any_of + spec.dependency.optional)
            if current in deps:
                remaining_in_degree[code] -= 1
                if remaining_in_degree[code] == 0:
                    ready.append(code)
    return visited == len(registry)


def validate_dependency_registry(
    registry: "dict[EngineCode, EngineInvocationSpec]",
    *,
    enforce_fixed_shape: bool = True,
) -> None:
    """
    Bolum 4/35 kayit-ani doguelanma checklist'i:
      - Her bagimlilik registry'de gercekten var (bilinmeyen dugum yasagi).
      - Graf dongusuz.
      - (enforce_fixed_shape=True ise) dugum/kenar sayilari Bolum 4'teki
        sabit sayilarla (10/21/2/1/24) birebir eslesiyor.
    """

    for code, spec in registry.items():
        for dep in spec.dependency.all_of + spec.dependency.any_of + spec.dependency.optional:
            if dep not in registry:
                raise UnknownEngineDependencyError(
                    f"{code!r} bilinmeyen bir bagimliliga isaret ediyor: {dep!r}"
                )

    if not _topologically_sortable(registry):
        raise DependencyCycleError("ENGINE_DEPENDENCY_REGISTRY dongu iceriyor.")

    if not enforce_fixed_shape:
        return

    node_count = len(registry)
    all_of_edges = sum(len(spec.dependency.all_of) for spec in registry.values())
    any_of_edges = sum(len(spec.dependency.any_of) for spec in registry.values())
    optional_edges = sum(len(spec.dependency.optional) for spec in registry.values())
    total_edges = all_of_edges + any_of_edges + optional_edges

    if node_count != EXPECTED_NODE_COUNT:
        raise DependencyRegistryShapeError(
            f"Dugum sayisi {node_count}, beklenen {EXPECTED_NODE_COUNT}."
        )
    if all_of_edges != EXPECTED_ALL_OF_EDGE_COUNT:
        raise DependencyRegistryShapeError(
            f"all_of kenar sayisi {all_of_edges}, beklenen {EXPECTED_ALL_OF_EDGE_COUNT}."
        )
    if any_of_edges != EXPECTED_ANY_OF_EDGE_COUNT:
        raise DependencyRegistryShapeError(
            f"any_of kenar sayisi {any_of_edges}, beklenen {EXPECTED_ANY_OF_EDGE_COUNT}."
        )
    if optional_edges != EXPECTED_OPTIONAL_EDGE_COUNT:
        raise DependencyRegistryShapeError(
            f"optional kenar sayisi {optional_edges}, beklenen {EXPECTED_OPTIONAL_EDGE_COUNT}."
        )
    if total_edges != EXPECTED_TOTAL_EDGE_COUNT:
        raise DependencyRegistryShapeError(
            f"Toplam kenar sayisi {total_edges}, beklenen {EXPECTED_TOTAL_EDGE_COUNT}."
        )


def _build_registry() -> "dict[EngineCode, EngineInvocationSpec]":
    reg: "dict[EngineCode, EngineInvocationSpec]" = {}
    EC = EngineCode

    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.FS_BALANCE_SHEET,
            DependencyRequirement(),
            "BalanceSheetAnalysisOutcome",
            is_critical=True,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.FS_INCOME_STATEMENT,
            DependencyRequirement(),
            "IncomeStatementAnalysisOutcome",
            is_critical=True,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.RATIO,
            DependencyRequirement(any_of=(EC.FS_BALANCE_SHEET, EC.FS_INCOME_STATEMENT)),
            "dict",
            is_critical=True,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.BENCHMARK, DependencyRequirement(all_of=(EC.RATIO,)), "dict", is_critical=True
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.HEALTH_SCORE,
            DependencyRequirement(all_of=(EC.RATIO, EC.BENCHMARK)),
            "HealthScoreResult",
            is_critical=True,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.CREDIT_SCORE,
            DependencyRequirement(all_of=(EC.RATIO, EC.BENCHMARK, EC.HEALTH_SCORE)),
            "CreditScoreResult",
            is_critical=True,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.RECOMMENDATION,
            DependencyRequirement(all_of=(EC.RATIO, EC.BENCHMARK, EC.HEALTH_SCORE, EC.CREDIT_SCORE)),
            "RecommendationResult",
            is_critical=True,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.EXECUTIVE_REPORT,
            DependencyRequirement(
                all_of=(
                    EC.FS_BALANCE_SHEET,
                    EC.FS_INCOME_STATEMENT,
                    EC.RATIO,
                    EC.BENCHMARK,
                    EC.HEALTH_SCORE,
                    EC.CREDIT_SCORE,
                    EC.RECOMMENDATION,
                )
            ),
            "ExecutiveReportResult",
            is_critical=False,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.DASHBOARD,
            DependencyRequirement(
                all_of=(EC.HEALTH_SCORE, EC.CREDIT_SCORE, EC.RECOMMENDATION),
                optional=(EC.BENCHMARK,),
            ),
            "DashboardSnapshot",
            is_critical=False,
        ),
        registry=reg,
    )
    register_engine_invocation_spec(
        EngineInvocationSpec(
            EC.RENDER_CONTRACT,
            DependencyRequirement(all_of=(EC.EXECUTIVE_REPORT,)),
            "RenderContractPreview",
            is_critical=False,
        ),
        registry=reg,
    )
    return reg


ENGINE_DEPENDENCY_REGISTRY.update(_build_registry())
validate_dependency_registry(ENGINE_DEPENDENCY_REGISTRY)
