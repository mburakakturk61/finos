from dataclasses import fields
from decimal import Decimal

import pytest

from app.analysis_application_v3.contracts import (
    APPLICATION_DTO_SCHEMA_VERSION_V3, ApplicationEngineCodeV3,
    ApplicationTrendStatusV3,
)
from app.analysis_application_v3.projection import project_trend_result_v3
from app.engines.analysis_orchestrator_v4.types import OrchestrationEngineCodeV4
from app.engines.multi_period_trend import assemble_multi_period_trend_result
from app.orchestration_persistence_v4 import (
    RESULT_OWNERSHIP_REGISTRY_V4, ResultOwnerV4,
    TrendFinancialResultCodecError, decode_trend_financial_result,
    encode_trend_financial_result,
)

from test_multi_period_trend_orchestrator_v4_unit import _profile, context


def result():
    ctx = context((100, 110, 121, 133, 146))
    return ctx, assemble_multi_period_trend_result(
        ctx.resolved_series, ctx.comparability_profile,
        expected_metric_codes=ctx.expected_metric_codes,
    )


def _walk(value):
    if type(value) is tuple:
        for item in value: yield from _walk(item)
    elif hasattr(value, "__dataclass_fields__"):
        yield value
        for item in fields(value): yield from _walk(getattr(value, item.name))
    else:
        yield value


def test_application_v3_projection_is_lossless_framework_free_and_decimal_typed():
    _, engine_result = result()
    projected = project_trend_result_v3(engine_result)
    assert projected.application_schema_version == APPLICATION_DTO_SCHEMA_VERSION_V3
    assert projected.status is ApplicationTrendStatusV3.COMPLETE
    assert projected.canonical_digest == engine_result.canonical_digest
    assert any(isinstance(item, Decimal) for item in _walk(projected))
    assert not any(type(item).__module__.startswith("app.engines.") for item in _walk(projected))
    assert projected.metrics[0].observations and projected.metrics[0].transitions
    assert projected.nominal_analysis_disclosure
    assert projected.lineage_references and projected.source_references


def test_application_and_owner_registries_are_exact_additive_families():
    assert tuple(item.value for item in ApplicationEngineCodeV3)[-1] == "multi_period_trend"
    spec = RESULT_OWNERSHIP_REGISTRY_V4[OrchestrationEngineCodeV4.MULTI_PERIOD_TREND]
    assert spec.owner is ResultOwnerV4.FINANCIAL_ANALYSIS_RESULT
    assert spec.result_kind == "TrendAnalysisResult"
    assert spec.analysis_type.value == "multi_period_trend"
    assert len(RESULT_OWNERSHIP_REGISTRY_V4) == 12


def test_strict_trend_codec_round_trip_digest_and_corruption_rejection():
    ctx, engine_result = result()
    node, digest = encode_trend_financial_result(
        engine_result, source_set_digest=ctx.source_set_digest,
        resolution_digest=ctx.resolution_digest,
        lineage_count=len(ctx.lineage), metric_registry_version=ctx.metric_registry_version,
        metric_registry_digest=ctx.metric_registry_digest,
        policy_version=ctx.policy_version.value, contract_version=ctx.contract_version.value,
    )
    decoded = decode_trend_financial_result(node, digest)
    assert decoded == engine_result
    assert decoded.canonical_digest == engine_result.canonical_digest
    with pytest.raises(TrendFinancialResultCodecError):
        decode_trend_financial_result({**node, "serializer_schema_version": "9.0.0"}, digest)
    with pytest.raises(TrendFinancialResultCodecError):
        decode_trend_financial_result(node, "0" * 64)
    corrupted = {**node, "unknown": True}
    with pytest.raises(TrendFinancialResultCodecError):
        decode_trend_financial_result(corrupted, digest)
