"""Canonical V4 request and engine fingerprints with cross-major isolation."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from uuid import UUID

from .types import (
    EXECUTION_PLAN_VERSION_V4,
    FINGERPRINT_SCHEMA_VERSION_V4,
    EngineRawInputsV4,
    OrchestrationEngineCodeV4,
    OrchestrationRunOptionsV4,
    OrchestrationRunRequestV4,
    TrendPreResolvedContextV1,
)


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite Decimal")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _node(value: object) -> object:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is bytes:
        return {"$type": "bytes_sha256", "value": sha256(value).hexdigest()}
    if type(value) is Decimal:
        return {"$type": "decimal", "value": _decimal(value)}
    if type(value) is UUID:
        return {"$type": "uuid", "value": str(value)}
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime is not canonical")
        return {"$type": "datetime", "value": value.isoformat()}
    if type(value) is date:
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, Enum):
        return {"$type": "enum", "name": type(value).__name__, "value": value.value}
    if type(value) in {tuple, list}:
        return {"$type": "tuple", "items": [_node(item) for item in value]}
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("V4 fingerprint mappings require string keys")
        return {"$type": "mapping", "items": [[key, _node(value[key])] for key in sorted(value)]}
    if type(value) is TrendPreResolvedContextV1:
        return {
            "$type": "TrendPreResolvedContextV1",
            "resolution_digest": value.resolution_digest,
            "source_set_digest": value.source_set_digest,
            "registry_version": value.metric_registry_version,
            "registry_digest": value.metric_registry_digest,
            "policy_version": value.policy_version.value,
            "contract_version": value.contract_version.value,
            "lineage_schema_version": value.lineage_schema_version,
        }
    if is_dataclass(value):
        return {
            "$type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [[field.name, _node(getattr(value, field.name))] for field in fields(value)],
        }
    raise TypeError(f"unsupported V4 fingerprint value: {type(value).__name__}")


def _bytes(value: object) -> bytes:
    return json.dumps(_node(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def compute_request_fingerprint_v4(request: OrchestrationRunRequestV4) -> str:
    if type(request) is not OrchestrationRunRequestV4:
        raise TypeError("V4 fingerprint requires exact V4 request")
    order = tuple(OrchestrationEngineCodeV4)
    requested = tuple(sorted(request.requested_outputs, key=order.index))
    projection = (
        request.contract_version,
        EXECUTION_PLAN_VERSION_V4,
        FINGERPRINT_SCHEMA_VERSION_V4,
        requested,
        request.engine_inputs,
        request.run_options,
    )
    return sha256(b"orchestration/request-fingerprint/v4\0" + _bytes(projection)).hexdigest()


def compute_engine_input_fingerprint_v4(
    engine_code: OrchestrationEngineCodeV4,
    request: OrchestrationRunRequestV4,
    upstream_fingerprints: dict[OrchestrationEngineCodeV4, str],
) -> str:
    if type(engine_code) is not OrchestrationEngineCodeV4 or type(request) is not OrchestrationRunRequestV4:
        raise TypeError("V4 engine fingerprint requires exact V4 contracts")
    context = request.engine_inputs.trend_pre_resolved_context if engine_code is OrchestrationEngineCodeV4.MULTI_PERIOD_TREND else request.engine_inputs
    projection = (
        engine_code,
        context,
        request.run_options,
        tuple(sorted(((item, digest) for item, digest in upstream_fingerprints.items()), key=lambda pair: pair[0].value)),
        EXECUTION_PLAN_VERSION_V4,
    )
    return sha256(b"orchestration/engine-input/v4\0" + _bytes(projection)).hexdigest()
