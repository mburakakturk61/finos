"""
Milestone 5.0A -- Kategori A: Registry/DAG testleri (Bolum 67-A).

Bolum 4/35'teki sabit sayilarin (10 dugum, 24 kenar = 21 all_of + 2 any_of
+ 1 optional) ve kayit-ani doguelanmasinin (bilinmeyen bagimlilik, self-
dependency, dongu) gercekten uygulandigini kanitlar. Ayrica execution
plan'in registry insertion-order'dan bagimsiz oldugunu ve alfabetik
tie-break kuralinin deterministik oldugunu dogrular.
"""

from app.engines.analysis_orchestrator.dispatch import (
    ORCHESTRATOR_ENGINE_DISPATCH,
    validate_dispatch_completeness,
)
from app.engines.analysis_orchestrator.execution_plan import derive_execution_plan
from app.engines.analysis_orchestrator.registry import (
    ENGINE_DEPENDENCY_REGISTRY,
    DependencyCycleError,
    DependencyRegistryShapeError,
    SelfDependencyError,
    UnknownEngineDependencyError,
    register_engine_invocation_spec,
    validate_dependency_registry,
)
from app.engines.analysis_orchestrator.types import DependencyRequirement, EngineCode, EngineInvocationSpec


def test_registry_has_exactly_10_nodes():
    assert len(ENGINE_DEPENDENCY_REGISTRY) == 10
    assert set(ENGINE_DEPENDENCY_REGISTRY) == set(EngineCode)


def test_registry_edge_counts_match_bolum_4():
    all_of_edges = sum(len(spec.dependency.all_of) for spec in ENGINE_DEPENDENCY_REGISTRY.values())
    any_of_edges = sum(len(spec.dependency.any_of) for spec in ENGINE_DEPENDENCY_REGISTRY.values())
    optional_edges = sum(len(spec.dependency.optional) for spec in ENGINE_DEPENDENCY_REGISTRY.values())
    assert all_of_edges == 21
    assert any_of_edges == 2
    assert optional_edges == 1
    assert all_of_edges + any_of_edges + optional_edges == 24


def test_registry_validation_passes_for_default_registry():
    # Firlatmamasi yeterli kanit.
    validate_dependency_registry(ENGINE_DEPENDENCY_REGISTRY)


def test_unknown_dependency_is_rejected_at_registration_time():
    reg2 = {
        EngineCode.RATIO: EngineInvocationSpec(
            EngineCode.RATIO,
            DependencyRequirement(all_of=(EngineCode.BENCHMARK,)),
            "dict",
            is_critical=True,
        )
    }
    try:
        validate_dependency_registry(reg2, enforce_fixed_shape=False)
        raised = False
    except UnknownEngineDependencyError:
        raised = True
    assert raised


def test_self_dependency_is_rejected_at_registration_time():
    reg: "dict" = {}
    try:
        register_engine_invocation_spec(
            EngineInvocationSpec(
                EngineCode.RATIO, DependencyRequirement(all_of=(EngineCode.RATIO,)), "dict", is_critical=True
            ),
            registry=reg,
        )
        raised = False
    except SelfDependencyError:
        raised = True
    assert raised


def test_cycle_is_rejected():
    reg = {
        EngineCode.RATIO: EngineInvocationSpec(
            EngineCode.RATIO, DependencyRequirement(all_of=(EngineCode.BENCHMARK,)), "dict", True
        ),
        EngineCode.BENCHMARK: EngineInvocationSpec(
            EngineCode.BENCHMARK, DependencyRequirement(all_of=(EngineCode.RATIO,)), "dict", True
        ),
    }
    try:
        validate_dependency_registry(reg, enforce_fixed_shape=False)
        raised = False
    except DependencyCycleError:
        raised = True
    assert raised


def test_shape_mismatch_is_rejected_when_enforced():
    reg = {
        EngineCode.RATIO: EngineInvocationSpec(EngineCode.RATIO, DependencyRequirement(), "dict", True),
    }
    try:
        validate_dependency_registry(reg, enforce_fixed_shape=True)
        raised = False
    except DependencyRegistryShapeError:
        raised = True
    assert raised


def test_dispatch_completeness_matches_registry():
    # Firlatmamasi yeterli -- gercek dispatch modulunun kendi kayit-ani
    # dogulamasinin (import zamaninda zaten calisti) burada da tutarli
    # oldugunu teyit eder.
    validate_dispatch_completeness(ORCHESTRATOR_ENGINE_DISPATCH, ENGINE_DEPENDENCY_REGISTRY)
    assert set(ORCHESTRATOR_ENGINE_DISPATCH) == set(ENGINE_DEPENDENCY_REGISTRY)


def test_execution_plan_is_independent_of_registry_insertion_order():
    forward_order = list(ENGINE_DEPENDENCY_REGISTRY.items())
    reversed_registry = dict(reversed(forward_order))
    plan_forward = derive_execution_plan(dict(forward_order))
    plan_reversed = derive_execution_plan(reversed_registry)
    assert plan_forward == plan_reversed


def test_execution_plan_respects_dependency_order():
    plan = derive_execution_plan()
    index = {code: i for i, code in enumerate(plan)}
    for code, spec in ENGINE_DEPENDENCY_REGISTRY.items():
        for dep in spec.dependency.all_of + spec.dependency.any_of + spec.dependency.optional:
            assert index[dep] < index[code], f"{dep} once gelmeli: {code}"


def test_execution_plan_tie_break_is_alphabetical_engine_code_value():
    # FS_BALANCE_SHEET ve FS_INCOME_STATEMENT'in ikisi de bagimliliksizdir
    # (ayni anda "hazir") -- alfabetik siraya gore fs_balance_sheet <
    # fs_income_statement, bu yuzden BS her zaman ONCE gelmelidir.
    plan = derive_execution_plan()
    assert plan.index(EngineCode.FS_BALANCE_SHEET) < plan.index(EngineCode.FS_INCOME_STATEMENT)


def test_execution_plan_has_all_10_codes_exactly_once():
    plan = derive_execution_plan()
    assert len(plan) == 10
    assert len(set(plan)) == 10
