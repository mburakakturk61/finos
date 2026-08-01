"""Deterministic allowlisted JSON codecs; no pickle or persisted class paths."""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from app.engines.common.credit_score_types import CreditScoreResult
from app.engines.common.dashboard_types import DashboardSnapshot
from app.engines.common.health_score_types import HealthScoreResult
from app.engines.common.recommendation_types import RecommendationResult
from app.engines.common.render_contract_types import RenderContractPreview
from app.engines.common.report_types import ExecutiveReportResult
from app.orchestration_persistence.errors import OrchestrationPersistenceError, PersistenceErrorCategory

SERIALIZER_FORMAT = "canonical_json"
SERIALIZER_SCHEMA_VERSION = "1.0.0"

RESULT_KIND_TYPES: dict[str, Any] = {
    "dict": dict[str, Any],
    "HealthScoreResult": HealthScoreResult,
    "CreditScoreResult": CreditScoreResult,
    "RecommendationResult": RecommendationResult,
    "ExecutiveReportResult": ExecutiveReportResult,
    "DashboardSnapshot": DashboardSnapshot,
    "RenderContractPreview": RenderContractPreview,
}


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (date, datetime)):
        return {"$iso8601": value.isoformat()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise OrchestrationPersistenceError(
        PersistenceErrorCategory.UNSUPPORTED_SERIALIZER_OR_RESULT_KIND,
        "Artifact payload contains an unsupported value.",
    )


def encode_artifact(result_kind: str, payload: object) -> tuple[bytes, str]:
    expected = RESULT_KIND_TYPES.get(result_kind)
    if expected is None:
        raise OrchestrationPersistenceError(
            PersistenceErrorCategory.UNSUPPORTED_SERIALIZER_OR_RESULT_KIND,
            "Unsupported orchestration result kind.",
        )
    if result_kind != "dict" and not isinstance(payload, expected):
        raise OrchestrationPersistenceError(
            PersistenceErrorCategory.UNSUPPORTED_SERIALIZER_OR_RESULT_KIND,
            "Artifact payload does not match its result kind.",
        )
    raw = json.dumps(_json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    """Canonical projection helper for persistence-owned digests."""
    return json.dumps(_json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode(value: Any, expected: Any) -> Any:
    if expected is Any:
        if isinstance(value, dict) and set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])
        if isinstance(value, list):
            return tuple(_decode(item, Any) for item in value)
        if isinstance(value, dict):
            return {key: _decode(item, Any) for key, item in value.items()}
        return value
    origin = get_origin(expected)
    args = get_args(expected)
    if origin in (Union, UnionType):
        if value is None and type(None) in args:
            return None
        candidates = [arg for arg in args if arg is not type(None)]
        return _decode(value, candidates[0])
    if origin in (tuple,):
        item_type = args[0] if args else Any
        return tuple(_decode(item, item_type) for item in value)
    if origin in (list,):
        item_type = args[0] if args else Any
        return [_decode(item, item_type) for item in value]
    if origin in (dict,):
        value_type = args[1] if len(args) > 1 else Any
        return {key: _decode(item, value_type) for key, item in value.items()}
    if isinstance(expected, type) and issubclass(expected, enum.Enum):
        return expected(value)
    if expected is Decimal:
        return Decimal(value["$decimal"])
    if expected in (date, datetime):
        return expected.fromisoformat(value["$iso8601"])
    if isinstance(expected, type) and dataclasses.is_dataclass(expected):
        hints = get_type_hints(expected)
        return expected(**{field.name: _decode(value[field.name], hints.get(field.name, Any)) for field in dataclasses.fields(expected)})
    return value


def decode_artifact(result_kind: str, raw: bytes, expected_digest: str, serializer_version: str) -> object:
    if serializer_version != SERIALIZER_SCHEMA_VERSION or result_kind not in RESULT_KIND_TYPES:
        raise OrchestrationPersistenceError(PersistenceErrorCategory.UNSUPPORTED_SERIALIZER_OR_RESULT_KIND, "Unsupported artifact serializer contract.")
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE, "Artifact integrity verification failed.")
    return _decode(json.loads(raw.decode("utf-8")), RESULT_KIND_TYPES[result_kind])
