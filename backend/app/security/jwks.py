"""Bounded per-issuer JWKS cache and key-profile validation."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import jwt

from app.security.contracts import JwtAlgorithm, OidcIssuerProfile, VerificationKey
from app.security.jwt import JwtProviderUnavailable, JwtValidationError


MAX_JWKS_BYTES = 256 * 1024
MAX_JWKS_KEYS = 32


@dataclass(frozen=True)
class JwksHttpResponse:
    status_code: int
    content_type: str
    body: bytes
    etag: str | None = None


@dataclass
class _IssuerCache:
    keys: dict[str, VerificationKey]
    fetched_at: datetime | None
    etag: str | None
    last_refresh_attempt: datetime | None
    negative: OrderedDict[str, datetime]
    lock: threading.Lock


class BoundedJwksProvider:
    def __init__(
        self,
        fetch: Callable[[OidcIssuerProfile, str | None], JwksHttpResponse],
        *, stale_seconds: int = 120, hard_stale_seconds: int = 420,
        refresh_interval_seconds: int = 30, negative_ttl_seconds: int = 60,
        negative_cache_size: int = 256,
        metric: Callable[[str, str], None] | None = None,
    ) -> None:
        if not 0 <= stale_seconds <= 300 or not 1 <= hard_stale_seconds <= 1200:
            raise ValueError("JWKS stale bounds are invalid.")
        if not 10 <= refresh_interval_seconds <= 120:
            raise ValueError("JWKS refresh interval is invalid.")
        if not 10 <= negative_ttl_seconds <= 120 or not 32 <= negative_cache_size <= 1024:
            raise ValueError("JWKS negative-cache bounds are invalid.")
        self._fetch = fetch
        self._stale = timedelta(seconds=stale_seconds)
        self._hard_stale = timedelta(seconds=hard_stale_seconds)
        self._refresh_interval = timedelta(seconds=refresh_interval_seconds)
        self._negative_ttl = timedelta(seconds=negative_ttl_seconds)
        self._negative_size = negative_cache_size
        self._metric = metric or (lambda _name, _issuer: None)
        self._caches: dict[str, _IssuerCache] = {}
        self._global_lock = threading.Lock()

    def _cache(self, issuer: str) -> _IssuerCache:
        with self._global_lock:
            return self._caches.setdefault(
                issuer, _IssuerCache({}, None, None, None, OrderedDict(), threading.Lock())
            )

    def get_key(
        self, profile: OidcIssuerProfile, kid: str, algorithm: JwtAlgorithm,
        *, now: datetime,
    ) -> VerificationKey:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("JWKS clock must be timezone-aware.")
        if not kid or len(kid) > 128 or not kid.isascii():
            raise JwtValidationError("INVALID_KID")
        cache = self._cache(profile.issuer)
        with cache.lock:
            self._purge_negative(cache, now)
            age = now - cache.fetched_at if cache.fetched_at is not None else None
            known = cache.keys.get(kid)
            if known is not None and age is not None and age <= timedelta(seconds=profile.jwks_fresh_ttl_seconds):
                return self._match(known, algorithm)
            if kid in cache.negative:
                self._metric("negative_cache_hit", profile.issuer)
                raise JwtValidationError("UNKNOWN_KID")
            if (
                cache.last_refresh_attempt is not None
                and now - cache.last_refresh_attempt < self._refresh_interval
            ):
                self._remember_negative(cache, kid, now)
                self._metric("refresh_suppressed", profile.issuer)
                raise JwtValidationError("UNKNOWN_KID")
            stale_known = known
            cache.last_refresh_attempt = now
            self._metric("refresh_attempt", profile.issuer)
            try:
                self._refresh(profile, cache, now)
            except JwtProviderUnavailable:
                self._metric("refresh_failure", profile.issuer)
                if stale_known is not None and age is not None and age <= self._hard_stale:
                    self._metric("stale_key_used", profile.issuer)
                    return self._match(stale_known, algorithm)
                if age is not None and age > self._hard_stale:
                    self._metric("hard_stale_rejection", profile.issuer)
                raise
            found = cache.keys.get(kid)
            if found is None:
                self._remember_negative(cache, kid, now)
                self._metric("unknown_kid", profile.issuer)
                raise JwtValidationError("UNKNOWN_KID")
            return self._match(found, algorithm)

    def _refresh(self, profile: OidcIssuerProfile, cache: _IssuerCache, now: datetime) -> None:
        try:
            response = self._fetch(profile, cache.etag)
        except Exception as exc:
            raise JwtProviderUnavailable("JWKS provider is unavailable.") from exc
        if response.status_code == 304 and cache.fetched_at is not None:
            cache.fetched_at = now
            return
        if (
            response.status_code != 200
            or response.content_type.split(";", 1)[0].strip().lower() not in {"application/json", "application/jwk-set+json"}
            or len(response.body) > MAX_JWKS_BYTES
        ):
            raise JwtProviderUnavailable("JWKS provider returned an invalid response.")
        try:
            document = json.loads(response.body, object_pairs_hook=self._unique_object)
        except (ValueError, TypeError) as exc:
            raise JwtProviderUnavailable("JWKS provider returned invalid JSON.") from exc
        values = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(values, list) or not values or len(values) > MAX_JWKS_KEYS:
            raise JwtProviderUnavailable("JWKS key count is invalid.")
        parsed: dict[str, VerificationKey] = {}
        for value in values:
            key = self._parse_key(profile, value)
            if key.kid in parsed:
                raise JwtProviderUnavailable("JWKS contains duplicate key identifiers.")
            parsed[key.kid] = key
        cache.keys = parsed
        cache.fetched_at = now
        cache.etag = response.etag
        cache.negative.clear()

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    @staticmethod
    def _parse_key(profile: OidcIssuerProfile, value: object) -> VerificationKey:
        if not isinstance(value, dict):
            raise JwtProviderUnavailable("JWKS key must be an object.")
        if any(field in value for field in ("x5c", "x5t", "x5t#S256")):
            raise JwtProviderUnavailable("Certificate-derived JWKS keys are forbidden.")
        kid = value.get("kid")
        alg_raw = value.get("alg")
        if not isinstance(kid, str) or not kid or len(kid) > 128 or not kid.isascii():
            raise JwtProviderUnavailable("JWKS kid is invalid.")
        try:
            algorithm = JwtAlgorithm(alg_raw)
        except (ValueError, TypeError) as exc:
            raise JwtProviderUnavailable("JWKS algorithm is invalid.") from exc
        if algorithm not in profile.allowed_algorithms or value.get("use") != "sig":
            raise JwtProviderUnavailable("JWKS key profile is invalid.")
        operations = value.get("key_ops")
        if operations is not None and (
            not isinstance(operations, list) or "verify" not in operations
        ):
            raise JwtProviderUnavailable("JWKS key operations are invalid.")
        try:
            if algorithm in {JwtAlgorithm.RS256, JwtAlgorithm.PS256}:
                if value.get("kty") != "RSA":
                    raise ValueError("RSA key required")
                modulus = int.from_bytes(_b64int(value.get("n")), "big")
                exponent = int.from_bytes(_b64int(value.get("e")), "big")
                if modulus.bit_length() < 2048 or exponent < 65537 or exponent % 2 == 0:
                    raise ValueError("Weak RSA key")
                key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(value))
            else:
                if value.get("kty") != "EC" or value.get("crv") != "P-256":
                    raise ValueError("P-256 key required")
                key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(value))
        except (ValueError, TypeError, jwt.PyJWTError) as exc:
            raise JwtProviderUnavailable("JWKS public key is invalid.") from exc
        return VerificationKey(profile.issuer, kid, algorithm, key)

    @staticmethod
    def _match(key: VerificationKey, algorithm: JwtAlgorithm) -> VerificationKey:
        if key.algorithm is not algorithm:
            raise JwtValidationError("KEY_ALGORITHM_MISMATCH")
        return key

    def _remember_negative(self, cache: _IssuerCache, kid: str, now: datetime) -> None:
        cache.negative[kid] = now
        cache.negative.move_to_end(kid)
        while len(cache.negative) > self._negative_size:
            cache.negative.popitem(last=False)

    def _purge_negative(self, cache: _IssuerCache, now: datetime) -> None:
        expired = [kid for kid, seen in cache.negative.items() if now - seen >= self._negative_ttl]
        for kid in expired:
            del cache.negative[kid]

    def readiness_check(self, deadline: datetime) -> bool:
        return bool(self._caches) and all(cache.fetched_at is not None for cache in self._caches.values())


def _b64int(value: object) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise ValueError("Invalid base64url integer")
    return __import__("base64").urlsafe_b64decode(value + "=" * (-len(value) % 4))
