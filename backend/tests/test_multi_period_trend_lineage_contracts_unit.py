from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from itertools import permutations
from uuid import UUID

import pytest

from app.engines.multi_period_trend import (
    TREND_LINEAGE_REFERENCE_PREFIX,
    TREND_LINEAGE_SCHEMA_VERSION,
    TREND_METRIC_REGISTRY_V1,
    TrendContractError,
    TrendContractVersion,
    TrendEvidenceLevel,
    TrendLineageEdge,
    TrendLineagePortError,
    TrendLineagePortErrorCode,
    TrendLineageSourceAnalysisType,
    TrendLineageSourceEngineCode,
    TrendLineageSourceRole,
    TrendPolicyVersion,
    build_trend_lineage_set,
    canonical_trend_lineage_set_digest,
)


OWNER = UUID("10000000-0000-4000-8000-000000000001")
TENANT = UUID("20000000-0000-4000-8000-000000000001")
COMPANY = UUID("30000000-0000-4000-8000-000000000001")
PERIODS = tuple(UUID(f"40000000-0000-4000-8000-{index:012d}") for index in range(1, 7))
SOURCES = tuple(UUID(f"50000000-0000-4000-8000-{index:012d}") for index in range(1, 7))


def _edge(index: int, *, role=TrendLineageSourceRole.BALANCE_SHEET, **changes):
    bindings = {
        TrendLineageSourceRole.BALANCE_SHEET: (
            TrendLineageSourceEngineCode.FS_BALANCE_SHEET,
            TrendLineageSourceAnalysisType.BALANCE_SHEET,
            None,
            "1.0.0",
        ),
        TrendLineageSourceRole.INCOME_STATEMENT: (
            TrendLineageSourceEngineCode.FS_INCOME_STATEMENT,
            TrendLineageSourceAnalysisType.INCOME_STATEMENT,
            None,
            "1.0.0",
        ),
        TrendLineageSourceRole.CASH_FLOW: (
            TrendLineageSourceEngineCode.CASH_FLOW,
            TrendLineageSourceAnalysisType.CASH_FLOW,
            "1.0.0",
            "1.0.0",
        ),
        TrendLineageSourceRole.FINANCIAL_RATIOS: (
            TrendLineageSourceEngineCode.RATIO,
            TrendLineageSourceAnalysisType.FINANCIAL_RATIOS,
            "1.0",
            "1.1.0",
        ),
    }
    engine, analysis_type, schema, model = bindings[role]
    values = dict(
        ordinal=index,
        source_period_id=PERIODS[index],
        source_analysis_result_id=SOURCES[index],
        source_role=role,
        source_engine_code=engine,
        source_analysis_type=analysis_type,
        source_canonical_digest=f"{index + 1:x}" * 64,
        source_schema_version=schema,
        source_model_version=model,
        observation_evidence=TrendEvidenceLevel.EXACT,
        comparability_proof_digest=f"{index + 7:x}"[-1] * 64,
        resolution_proof_reference="trend:v1:sha256:" + f"{index + 10:x}"[-1] * 64,
        lineage_schema_version=TREND_LINEAGE_SCHEMA_VERSION,
    )
    values.update(changes)
    return TrendLineageEdge(**values)


def _set(edges=None):
    edges = edges or (_edge(0), _edge(1), _edge(2))
    return build_trend_lineage_set(
        trend_analysis_result_id=OWNER,
        tenant_id=TENANT,
        company_id=COMPANY,
        anchor_period_id=PERIODS[2],
        metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        policy_version=TrendPolicyVersion.V1,
        contract_version=TrendContractVersion.V1,
        lineage=edges,
    )


def test_exact_lineage_enum_and_version_snapshot():
    assert tuple(item.value for item in TrendLineageSourceRole) == (
        "balance_sheet", "income_statement", "cash_flow", "financial_ratios"
    )
    assert tuple(item.value for item in TrendLineageSourceEngineCode) == (
        "fs_balance_sheet", "fs_income_statement", "cash_flow", "ratio"
    )
    assert tuple(item.value for item in TrendLineagePortErrorCode) == (
        "conflict", "integrity_failure", "lock_timeout", "persistence_unavailable"
    )
    assert TREND_LINEAGE_SCHEMA_VERSION == "1.0.0"


def test_lineage_contract_is_immutable_safe_and_canonical():
    value = _set()
    assert value.lineage == (_edge(0), _edge(1), _edge(2))
    assert value.source_set_reference == TREND_LINEAGE_REFERENCE_PREFIX + value.source_set_digest
    assert repr(value) == "TrendLineageSet()"
    assert str(OWNER) not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.company_id = TENANT  # type: ignore[misc]


def test_input_order_does_not_change_lineage_or_digest():
    edges = (_edge(0), _edge(1), _edge(2))
    values = tuple(_set(tuple(order)) for order in permutations(edges))
    assert len({item.source_set_digest for item in values}) == 1
    assert len({item.lineage for item in values}) == 1


@pytest.mark.parametrize(
    "edges",
    (
        (_edge(0), _edge(0, source_analysis_result_id=SOURCES[4])),
        (_edge(0), _edge(1, source_period_id=PERIODS[0])),
        (_edge(0), _edge(1, source_analysis_result_id=SOURCES[0])),
        (_edge(0), _edge(2)),
    ),
)
def test_duplicate_or_non_gapless_lineage_is_rejected(edges):
    with pytest.raises(TrendContractError):
        _set(edges)


def test_same_period_multiple_roles_must_share_ordinal_and_unique_sources():
    edges = (
        _edge(0),
        _edge(
            0,
            role=TrendLineageSourceRole.INCOME_STATEMENT,
            source_analysis_result_id=SOURCES[3],
        ),
        _edge(1),
    )
    value = build_trend_lineage_set(
        trend_analysis_result_id=OWNER,
        tenant_id=TENANT,
        company_id=COMPANY,
        anchor_period_id=PERIODS[1],
        metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        policy_version=TrendPolicyVersion.V1,
        contract_version=TrendContractVersion.V1,
        lineage=edges,
    )
    assert tuple(item.ordinal for item in value.lineage) == (0, 0, 1)


def test_wrong_anchor_and_role_engine_type_are_rejected():
    with pytest.raises(TrendContractError):
        build_trend_lineage_set(
            trend_analysis_result_id=OWNER,
            tenant_id=TENANT,
            company_id=COMPANY,
            anchor_period_id=PERIODS[1],
            metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
            metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
            policy_version=TrendPolicyVersion.V1,
            contract_version=TrendContractVersion.V1,
            lineage=(_edge(0), _edge(1), _edge(2)),
        )
    with pytest.raises(TrendContractError):
        replace(_edge(0), source_engine_code=TrendLineageSourceEngineCode.RATIO)


@pytest.mark.parametrize(
    "field",
    (
        "source_period_id", "source_analysis_result_id", "source_canonical_digest",
        "source_schema_version", "source_model_version", "observation_evidence",
        "comparability_proof_digest", "resolution_proof_reference",
    ),
)
def test_any_source_semantic_mutation_changes_digest(field):
    original = _edge(1)
    replacements = {
        "source_period_id": PERIODS[4],
        "source_analysis_result_id": SOURCES[4],
        "source_canonical_digest": "f" * 64,
        "source_schema_version": "2.0.0",
        "source_model_version": "2.0.0",
        "observation_evidence": TrendEvidenceLevel.ESTIMATED,
        "comparability_proof_digest": "e" * 64,
        "resolution_proof_reference": "trend:v1:sha256:" + "f" * 64,
    }
    changed = replace(original, **{field: replacements[field]})
    left = canonical_trend_lineage_set_digest(
        company_id=COMPANY,
        anchor_period_id=PERIODS[2],
        metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        policy_version=TrendPolicyVersion.V1,
        contract_version=TrendContractVersion.V1,
        lineage=(_edge(0), original, _edge(2)),
    )
    right = canonical_trend_lineage_set_digest(
        company_id=COMPANY,
        anchor_period_id=PERIODS[2],
        metric_registry_version=TREND_METRIC_REGISTRY_V1.registry_version,
        metric_registry_digest=TREND_METRIC_REGISTRY_V1.digest,
        policy_version=TrendPolicyVersion.V1,
        contract_version=TrendContractVersion.V1,
        lineage=(_edge(0), changed, _edge(2)),
    )
    assert left != right


def test_digest_and_reference_mismatch_are_rejected():
    value = _set()
    with pytest.raises(TrendContractError):
        replace(value, source_set_digest="f" * 64)
    with pytest.raises(TrendContractError):
        replace(value, source_set_reference=TREND_LINEAGE_REFERENCE_PREFIX + "f" * 64)


def test_port_error_is_final_immutable_safe_and_retryable_is_closed():
    failure = TrendLineagePortError(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
    assert failure.args == ()
    assert failure.retryable is False
    assert failure.__cause__ is None and failure.__context__ is None
    with pytest.raises(AttributeError):
        failure._code = TrendLineagePortErrorCode.CONFLICT  # type: ignore[misc]
    with pytest.raises(TypeError):
        class InvalidPortError(TrendLineagePortError):
            pass
    assert TrendLineagePortError(TrendLineagePortErrorCode.LOCK_TIMEOUT).retryable is True
