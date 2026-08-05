"""Canonical serialization for immutable Milestone 4.6 trend values."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from .types import TREND_CANONICAL_REFERENCE_PREFIX_V1


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ALLOWED_MODULE = "app.engines.multi_period_trend"


class TrendCanonicalError(ValueError):
    __slots__ = ()


def normalize_decimal(value: Decimal) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise TrendCanonicalError("trend decimal must be finite Decimal")
    return Decimal(0) if value.is_zero() else value


def _decimal_text(value: Decimal) -> str:
    value = normalize_decimal(value)
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _node(value: object) -> object:
    if value is None:
        return {"$none": True}
    if type(value) is bool:
        return {"$bool": value}
    if type(value) is int:
        return {"$int": str(value)}
    if type(value) is str:
        return {"$str": value}
    if type(value) is Decimal:
        return {"$decimal": _decimal_text(value)}
    if type(value) is UUID:
        return {"$uuid": str(value)}
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise TrendCanonicalError("trend datetime must be timezone aware")
        normalized = value.astimezone(timezone.utc)
        return {"$datetime": normalized.isoformat(timespec="microseconds")}
    if type(value) is date:
        return {"$date": value.isoformat()}
    if isinstance(value, Enum):
        if not type(value).__module__.startswith(_ALLOWED_MODULE):
            raise TrendCanonicalError("unregistered external enum")
        return {"$enum": f"{type(value).__name__}:{value.value}"}
    if type(value) is tuple:
        return {"$tuple": [_node(item) for item in value]}
    if dataclasses.is_dataclass(value):
        if not type(value).__module__.startswith(_ALLOWED_MODULE):
            raise TrendCanonicalError("unregistered external dataclass")
        return {
            "$contract": f"trend.contract.{type(value).__name__}.v1",
            "$fields": [
                [field.name, _node(getattr(value, field.name))]
                for field in dataclasses.fields(value)
            ],
        }
    raise TrendCanonicalError("unsupported mutable or non-canonical trend value")


def canonical_trend_bytes(value: object) -> bytes:
    return json.dumps(
        _node(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_trend_digest(value: object) -> str:
    return hashlib.sha256(b"multi-period-trend/contract/v1\0" + canonical_trend_bytes(value)).hexdigest()


def canonical_trend_reference(value: object) -> str:
    return TREND_CANONICAL_REFERENCE_PREFIX_V1 + canonical_trend_digest(value)


def validate_sha256(value: object, field_name: str = "digest") -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise TrendCanonicalError(f"{field_name} must be lowercase SHA-256")
    return value


def validate_trend_reference(value: object) -> str:
    if type(value) is not str or not value.startswith(TREND_CANONICAL_REFERENCE_PREFIX_V1):
        raise TrendCanonicalError("trend canonical reference prefix is invalid")
    validate_sha256(value.removeprefix(TREND_CANONICAL_REFERENCE_PREFIX_V1), "reference digest")
    return value
