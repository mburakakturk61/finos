from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security.contracts import JwtAlgorithm, OidcIssuerProfile
from app.security.jwks import BoundedJwksProvider, JwksHttpResponse
from app.security.jwt import JwtProviderUnavailable, JwtValidationError


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _profile():
    return OidcIssuerProfile(
        issuer="https://issuer.example.test",
        human_audiences=frozenset({"human"}), service_audiences=frozenset({"service"}),
        jwks_uri="https://keys.example.test/jwks.json",
        jwks_allowed_hosts=frozenset({"keys.example.test"}),
        allowed_algorithms=frozenset({JwtAlgorithm.RS256}), allowed_types=frozenset({"at+jwt"}),
        jwks_fresh_ttl_seconds=30,
    )


def _jwk(kid="key-1", key_size=2048):
    public = rsa.generate_private_key(public_exponent=65537, key_size=key_size).public_key()
    value = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public))
    value.update({"kid": kid, "alg": "RS256", "use": "sig", "key_ops": ["verify"]})
    return value


def _response(keys):
    return JwksHttpResponse(200, "application/jwk-set+json", json.dumps({"keys": keys}).encode(), '"v1"')


def test_cache_hit_random_kid_suppression_and_negative_cache():
    calls = []
    metrics = []
    response = _response([_jwk()])
    provider = BoundedJwksProvider(
        lambda profile, etag: calls.append((profile.issuer, etag)) or response,
        metric=lambda name, issuer: metrics.append((name, issuer)),
    )
    profile = _profile()
    assert provider.get_key(profile, "key-1", JwtAlgorithm.RS256, now=NOW).kid == "key-1"
    assert provider.get_key(profile, "key-1", JwtAlgorithm.RS256, now=NOW + timedelta(seconds=1)).kid == "key-1"
    with pytest.raises(JwtValidationError):
        provider.get_key(profile, "random-1", JwtAlgorithm.RS256, now=NOW + timedelta(seconds=2))
    with pytest.raises(JwtValidationError):
        provider.get_key(profile, "random-1", JwtAlgorithm.RS256, now=NOW + timedelta(seconds=3))
    assert len(calls) == 1
    assert any(name == "refresh_suppressed" for name, _ in metrics)
    assert any(name == "negative_cache_hit" for name, _ in metrics)


def test_stale_known_key_is_bounded_and_hard_stale_fails_closed():
    response = _response([_jwk()])
    state = {"fail": False}
    def fetch(_profile, _etag):
        if state["fail"]:
            raise TimeoutError("provider unavailable")
        return response
    metrics = []
    provider = BoundedJwksProvider(fetch, metric=lambda name, issuer: metrics.append(name))
    profile = _profile()
    provider.get_key(profile, "key-1", JwtAlgorithm.RS256, now=NOW)
    state["fail"] = True
    assert provider.get_key(profile, "key-1", JwtAlgorithm.RS256, now=NOW + timedelta(seconds=31)).kid == "key-1"
    with pytest.raises(JwtProviderUnavailable):
        provider.get_key(profile, "key-1", JwtAlgorithm.RS256, now=NOW + timedelta(seconds=421))
    assert "stale_key_used" in metrics
    assert "hard_stale_rejection" in metrics


def test_unknown_kid_outage_never_uses_another_stale_key():
    response = _response([_jwk()])
    state = {"count": 0}
    def fetch(_profile, _etag):
        state["count"] += 1
        if state["count"] > 1:
            raise TimeoutError
        return response
    provider = BoundedJwksProvider(fetch)
    profile = _profile()
    provider.get_key(profile, "key-1", JwtAlgorithm.RS256, now=NOW)
    with pytest.raises(JwtProviderUnavailable):
        provider.get_key(profile, "new-key", JwtAlgorithm.RS256, now=NOW + timedelta(seconds=31))


def test_weak_duplicate_and_certificate_derived_keys_are_rejected():
    profile = _profile()
    for keys in ([_jwk(key_size=1024)], [_jwk(), _jwk()], [{**_jwk(), "x5c": ["cert"]}]):
        provider = BoundedJwksProvider(lambda _profile, _etag, keys=keys: _response(keys))
        with pytest.raises(JwtProviderUnavailable):
            provider.get_key(profile, "key-1", JwtAlgorithm.RS256, now=NOW)
