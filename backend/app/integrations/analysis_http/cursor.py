"""Scope-bound canonical HMAC cursor envelope."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class InvalidCursor(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or "=" in value:
        raise InvalidCursor("Invalid cursor encoding.")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise InvalidCursor("Invalid cursor encoding.") from exc


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _tenant_hash(tenant_id: str | None) -> str:
    value = tenant_id if tenant_id is not None else "<none>"
    return hashlib.sha256(f"tenant:v1:{value}".encode()).hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Cursor timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or len(value) != 20 or not value.endswith("Z"):
        raise InvalidCursor("Invalid cursor timestamp.")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise InvalidCursor("Invalid cursor timestamp.") from exc


def _no_duplicate_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCursor("Duplicate cursor field.")
        result[key] = value
    return result


@dataclass(frozen=True)
class CursorKeyring:
    active_key_id: str
    keys: dict[str, bytes]
    retired_verify_only: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.active_key_id not in self.keys or len(self.keys[self.active_key_id]) < 32:
            raise ValueError("An active cursor key of at least 256 bits is required.")
        if not self.retired_verify_only.issubset(self.keys):
            raise ValueError("Retired cursor keys must exist in the keyring.")


class HmacCursorCodec:
    _FIELDS = frozenset({
        "version", "tenant_scope_hash", "company_id", "financial_period_id",
        "internal_cursor", "key_id", "issued_at", "expires_at", "signature",
    })

    def __init__(self, keyring: CursorKeyring, *, ttl: timedelta = timedelta(hours=24)) -> None:
        if ttl <= timedelta(0):
            raise ValueError("Cursor TTL must be positive.")
        self.keyring = keyring
        self.ttl = ttl

    def encode(self, *, internal_cursor: str, tenant_id: str | None, company_id, financial_period_id, now: datetime) -> str:
        payload = {
            "version": 1,
            "tenant_scope_hash": _tenant_hash(tenant_id),
            "company_id": str(company_id).lower(),
            "financial_period_id": str(financial_period_id).lower(),
            "internal_cursor": internal_cursor,
            "key_id": self.keyring.active_key_id,
            "issued_at": _timestamp(now),
            "expires_at": _timestamp(now + self.ttl),
        }
        signature = hmac.new(
            self.keyring.keys[self.keyring.active_key_id], _canonical_bytes(payload), hashlib.sha256,
        ).digest()
        return _b64encode(_canonical_bytes({**payload, "signature": _b64encode(signature)}))

    def decode(self, value: str, *, tenant_id: str | None, company_id, financial_period_id, now: datetime) -> str:
        try:
            envelope = json.loads(_b64decode(value), object_pairs_hook=_no_duplicate_object)
        except InvalidCursor:
            raise
        except Exception as exc:
            raise InvalidCursor("Invalid cursor envelope.") from exc
        if not isinstance(envelope, dict) or frozenset(envelope) != self._FIELDS:
            raise InvalidCursor("Invalid cursor fields.")
        signature_text = envelope.pop("signature")
        key_id = envelope.get("key_id")
        allowed = {self.keyring.active_key_id, *self.keyring.retired_verify_only}
        if not isinstance(key_id, str) or key_id not in allowed:
            raise InvalidCursor("Invalid cursor key.")
        expected = hmac.new(self.keyring.keys[key_id], _canonical_bytes(envelope), hashlib.sha256).digest()
        supplied = _b64decode(signature_text) if isinstance(signature_text, str) else b""
        if len(supplied) != len(expected) or not hmac.compare_digest(supplied, expected):
            raise InvalidCursor("Invalid cursor signature.")
        issued_at = _parse_timestamp(envelope["issued_at"])
        expires_at = _parse_timestamp(envelope["expires_at"])
        if issued_at > now + timedelta(seconds=60) or expires_at <= now or expires_at != issued_at + self.ttl:
            raise InvalidCursor("Expired or future cursor.")
        expected_scope = (
            _tenant_hash(tenant_id), str(company_id).lower(), str(financial_period_id).lower(),
        )
        actual_scope = (
            envelope.get("tenant_scope_hash"), envelope.get("company_id"),
            envelope.get("financial_period_id"),
        )
        if envelope.get("version") != 1 or actual_scope != expected_scope:
            raise InvalidCursor("Cursor scope mismatch.")
        internal = envelope.get("internal_cursor")
        if not isinstance(internal, str) or not internal:
            raise InvalidCursor("Invalid internal cursor.")
        return internal

    def readiness_check(self, deadline: datetime) -> bool:
        return (
            deadline.tzinfo is not None
            and self.keyring.active_key_id in self.keyring.keys
            and len(self.keyring.keys[self.keyring.active_key_id]) >= 32
        )
