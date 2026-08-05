"""Strict tagged JSONB codec for the single Trend payload owner."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import hmac
from uuid import UUID

from app.engines.multi_period_trend import canonical as trend_canonical
from app.engines.multi_period_trend import contracts as trend_contracts
from app.engines.multi_period_trend import types as trend_types
from app.engines.multi_period_trend import MultiPeriodTrendResult, canonical_trend_bytes
from app.models.enums import AnalysisStatus, SourceMode
from app.orchestration_persistence.codec import canonical_json_bytes


TREND_FINANCIAL_RESULT_CODEC_VERSION = "1.0.0"
TREND_PAYLOAD_TAG = "multi_period_trend_result/v1"

_RECORDS = {
    value.__name__: value for value in vars(trend_contracts).values()
    if isinstance(value, type) and is_dataclass(value) and value.__module__.startswith("app.engines.multi_period_trend")
}
_ENUMS = {
    value.__name__: value for value in vars(trend_types).values()
    if isinstance(value, type) and issubclass(value, Enum)
}


class TrendFinancialResultCodecError(ValueError):
    pass


def encode_trend_financial_result(
    result: MultiPeriodTrendResult,
    *,
    source_set_digest: str,
    resolution_digest: str,
    lineage_count: int,
    metric_registry_version: str,
    metric_registry_digest: str,
    policy_version: str,
    contract_version: str,
) -> tuple[dict, str]:
    if type(result) is not MultiPeriodTrendResult:
        raise TrendFinancialResultCodecError("strict codec requires exact MultiPeriodTrendResult")
    if type(lineage_count) is not int or lineage_count < 2:
        raise TrendFinancialResultCodecError("Trend owner requires at least two lineage rows")
    payload = trend_canonical._node(result)
    node = {
        "serializer_format": TREND_PAYLOAD_TAG,
        "serializer_schema_version": TREND_FINANCIAL_RESULT_CODEC_VERSION,
        "source_set_digest": source_set_digest,
        "resolution_digest": resolution_digest,
        "lineage_count": lineage_count,
        "metric_registry_version": metric_registry_version,
        "metric_registry_digest": metric_registry_digest,
        "policy_version": policy_version,
        "contract_version": contract_version,
        "payload": payload,
    }
    return node, sha256(canonical_json_bytes(node)).hexdigest()


def trend_owner_content_digest(node: dict) -> str:
    projection = {
        "status": AnalysisStatus.COMPLETED,
        "source_mode": SourceMode.MULTI_SOURCE_DERIVED,
        "result_json": node,
        "error_message": None,
        "trial_balance_usage": None,
    }
    return sha256(canonical_json_bytes(projection)).hexdigest()


def decode_trend_financial_result(node: dict, expected_owner_digest: str) -> MultiPeriodTrendResult:
    exact = {
        "serializer_format", "serializer_schema_version", "source_set_digest", "resolution_digest",
        "lineage_count", "metric_registry_version", "metric_registry_digest",
        "policy_version", "contract_version", "payload",
    }
    if type(node) is not dict or set(node) != exact:
        raise TrendFinancialResultCodecError("strict Trend JSONB field set mismatch")
    if node["serializer_format"] != TREND_PAYLOAD_TAG or node["serializer_schema_version"] != TREND_FINANCIAL_RESULT_CODEC_VERSION:
        raise TrendFinancialResultCodecError("unknown Trend serializer version")
    if not hmac.compare_digest(sha256(canonical_json_bytes(node)).hexdigest(), expected_owner_digest):
        raise TrendFinancialResultCodecError("Trend owner canonical digest mismatch")
    value = _decode(node["payload"])
    if type(value) is not MultiPeriodTrendResult:
        raise TrendFinancialResultCodecError("Trend payload root type mismatch")
    if trend_canonical._node(value) != node["payload"]:
        raise TrendFinancialResultCodecError("Trend payload is non-canonical")
    return value


def _decode(node):
    if type(node) is not dict:
        raise TrendFinancialResultCodecError("unknown strict Trend codec node")
    if set(node) == {"$none"} and node["$none"] is True: return None
    if set(node) == {"$bool"} and type(node["$bool"]) is bool: return node["$bool"]
    if set(node) == {"$int"}:
        try: value = int(node["$int"])
        except Exception: raise TrendFinancialResultCodecError("invalid integer node") from None
        if str(value) != node["$int"]: raise TrendFinancialResultCodecError("non-canonical integer node")
        return value
    if set(node) == {"$str"} and type(node["$str"]) is str: return node["$str"]
    if set(node) == {"$decimal"}:
        try: value = Decimal(node["$decimal"])
        except Exception: raise TrendFinancialResultCodecError("invalid Decimal node") from None
        if not value.is_finite(): raise TrendFinancialResultCodecError("non-finite Decimal node")
        return value
    if set(node) == {"$uuid"}:
        try: value = UUID(node["$uuid"])
        except Exception: raise TrendFinancialResultCodecError("invalid UUID node") from None
        if str(value) != node["$uuid"]: raise TrendFinancialResultCodecError("non-canonical UUID node")
        return value
    if set(node) == {"$date"}:
        try: value = date.fromisoformat(node["$date"])
        except Exception: raise TrendFinancialResultCodecError("invalid date node") from None
        return value
    if set(node) == {"$datetime"}:
        try: value = datetime.fromisoformat(node["$datetime"])
        except Exception: raise TrendFinancialResultCodecError("invalid datetime node") from None
        if value.tzinfo is None: raise TrendFinancialResultCodecError("naive datetime node")
        return value
    if set(node) == {"$enum"}:
        if type(node["$enum"]) is not str or ":" not in node["$enum"]:
            raise TrendFinancialResultCodecError("invalid enum node")
        name, raw = node["$enum"].split(":", 1)
        enum_type = _ENUMS.get(name)
        if enum_type is None: raise TrendFinancialResultCodecError("unknown enum tag")
        try: return enum_type(raw)
        except ValueError: raise TrendFinancialResultCodecError("unknown enum value") from None
    if set(node) == {"$tuple"} and type(node["$tuple"]) is list:
        return tuple(_decode(item) for item in node["$tuple"])
    if set(node) == {"$contract", "$fields"}:
        tag = node["$contract"]
        if type(tag) is not str or not tag.startswith("trend.contract.") or not tag.endswith(".v1"):
            raise TrendFinancialResultCodecError("unknown Trend contract tag")
        cls = _RECORDS.get(tag[len("trend.contract."):-len(".v1")])
        if cls is None or type(node["$fields"]) is not list:
            raise TrendFinancialResultCodecError("unknown Trend contract type")
        expected = tuple(item.name for item in fields(cls))
        actual = tuple(item[0] for item in node["$fields"] if type(item) is list and len(item) == 2)
        if actual != expected or len(actual) != len(node["$fields"]):
            raise TrendFinancialResultCodecError("Trend contract field order mismatch")
        try:
            return cls(**{name: _decode(item[1]) for name, item in zip(expected, node["$fields"])})
        except Exception:
            raise TrendFinancialResultCodecError("Trend contract invariant failure") from None
    raise TrendFinancialResultCodecError("unknown strict Trend codec tag")
