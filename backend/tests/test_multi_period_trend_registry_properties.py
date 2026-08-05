from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from random import Random

import pytest

from app.engines.multi_period_trend import (
    TREND_METRIC_DEFINITIONS_V1,
    TREND_METRIC_REGISTRY_V1,
    TREND_METRIC_REGISTRY_VERSION,
    TrendEvidenceLevel,
    TrendMetricRegistry,
    TrendMetricRegistryError,
    TrendSourceEngineType,
    TrendSourceMetricProjection,
    TrendSourceMetricStatus,
    TrendSourceMode,
    map_source_metric_evidence,
)
from decimal import Decimal


@pytest.mark.parametrize("seed", range(20))
def test_registry_permutation_property_preserves_digest_order_and_lookup(seed):
    shuffled = list(TREND_METRIC_DEFINITIONS_V1)
    Random(seed).shuffle(shuffled)
    registry = TrendMetricRegistry(TREND_METRIC_REGISTRY_VERSION, tuple(shuffled))
    assert registry.digest == TREND_METRIC_REGISTRY_V1.digest
    assert registry.metric_codes == TREND_METRIC_REGISTRY_V1.metric_codes
    assert all(registry.get(code).metric_code == code for code in registry.metric_codes)


@pytest.mark.parametrize("definition", TREND_METRIC_DEFINITIONS_V1, ids=lambda item: item.metric_code)
def test_each_metric_has_exactly_one_source_and_deterministic_eligibility(definition):
    matches = tuple(
        item for item in TREND_METRIC_DEFINITIONS_V1
        if item.authoritative_source_key == definition.authoritative_source_key
    )
    assert matches == (definition,)
    assert definition.measurement_basis_by_period_family == tuple(
        (family, definition.measurement_basis_for(family))
        for family in definition.eligible_period_families
    )


@pytest.mark.parametrize(
    "source_evidence",
    (TrendEvidenceLevel.EXACT, TrendEvidenceLevel.DERIVED, TrendEvidenceLevel.ESTIMATED),
)
def test_output_evidence_rank_never_exceeds_source_evidence(source_evidence):
    definition = TREND_METRIC_REGISTRY_V1.get("bs.total_assets")
    outcome = map_source_metric_evidence(
        definition,
        TrendSourceMetricProjection(
            source_engine_type=TrendSourceEngineType.BALANCE_SHEET,
            schema_version=None,
            model_version="1.0.0",
            status=TrendSourceMetricStatus.RESULT_BEARING,
            digest_verified=True,
            provenance_verified=True,
            field_present=True,
            value=Decimal("1"),
            source_evidence=source_evidence,
            source_mode=TrendSourceMode.DIRECT_DOCUMENT,
        ),
    )
    rank = {
        TrendEvidenceLevel.UNAVAILABLE: 0,
        TrendEvidenceLevel.ESTIMATED: 1,
        TrendEvidenceLevel.DERIVED: 2,
        TrendEvidenceLevel.EXACT: 3,
    }
    assert rank[outcome.evidence] <= rank[source_evidence]


def test_same_code_with_changed_semantics_is_rejected_by_successor_contract():
    changed = replace(
        TREND_METRIC_DEFINITIONS_V1[0],
        source_field_path=("facts", "different_current_assets"),
        registry_version="trend-metric-registry/2.0.0",
    )
    successor = TrendMetricRegistry(
        "trend-metric-registry/2.0.0",
        (changed,) + tuple(
            replace(item, registry_version="trend-metric-registry/2.0.0")
            for item in TREND_METRIC_DEFINITIONS_V1[1:]
        ),
    )
    with pytest.raises(TrendMetricRegistryError, match="semantic reuse"):
        TREND_METRIC_REGISTRY_V1.assert_compatible_successor(successor)


def test_4_6b_modules_are_framework_persistence_and_calculation_isolated():
    package = Path(__file__).parents[1] / "app" / "engines" / "multi_period_trend"
    files = (package / "registry.py", package / "compatibility.py", package / "evidence_mapping.py")
    forbidden_roots = {"fastapi", "pydantic", "sqlalchemy", "alembic"}
    forbidden_internal = {
        "app.models", "app.repositories", "app.integrations",
        "app.analysis_application", "app.analysis_application_v2",
    }
    for file_path in files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(name.split(".", 1)[0] in forbidden_roots for name in imports)
        assert not any(any(name.startswith(prefix) for prefix in forbidden_internal) for name in imports)
        source = file_path.read_text(encoding="utf-8")
        assert "def calculate_cagr" not in source
        assert "def calculate_direction" not in source
        assert "Session" not in source
