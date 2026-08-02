from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.security.contracts import (
    AuthenticationStrengthRule,
    IdentityKind,
    IssuerRegistry,
    JwtAlgorithm,
    OidcIssuerProfile,
    VerificationKey,
)
from app.security.jwt import JwtValidationError, ProviderNeutralJwtVerifier, extract_bearer_token


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


class _Keys:
    def __init__(self, key): self.key = key
    def get_key(self, profile, kid, algorithm, *, now):
        return VerificationKey(profile.issuer, kid, algorithm, self.key)
    def readiness_check(self, deadline): return True


@pytest.fixture
def jwt_setup():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    profile = OidcIssuerProfile(
        issuer="https://issuer.example.test",
        human_audiences=frozenset({"analysis-human"}),
        service_audiences=frozenset({"analysis-service"}),
        jwks_uri="https://keys.example.test/jwks.json",
        jwks_allowed_hosts=frozenset({"keys.example.test"}),
        allowed_algorithms=frozenset({JwtAlgorithm.RS256}),
        allowed_types=frozenset({"at+jwt"}),
        strength_mapping=(
            AuthenticationStrengthRule("amr", "pwd", AuthenticationStrength.BASIC),
            AuthenticationStrengthRule("amr", "mfa", AuthenticationStrength.STRONG),
            AuthenticationStrengthRule("amr", "webauthn", AuthenticationStrength.PHISHING_RESISTANT),
        ),
    )
    verifier = ProviderNeutralJwtVerifier(IssuerRegistry((profile,)), _Keys(private.public_key()))
    return private, profile, verifier


def _claims(profile, **overrides):
    values = {
        "iss": profile.issuer,
        "sub": "user:123",
        "tenant_id": "tenant-one",
        "aud": "analysis-human",
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(minutes=10)).timestamp()),
        "jti": "jwt-id-0000000001",
        "claims_version": "auth-claims/1",
        "amr": ["mfa"],
    }
    values.update(overrides)
    return values


def _token(private, claims, headers=None):
    return jwt.encode(claims, private, algorithm="RS256", headers=headers or {"kid": "key-1", "typ": "at+jwt"})


def _segment(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).rstrip(b"=").decode()


def test_valid_human_and_service_profiles(jwt_setup):
    private, profile, verifier = jwt_setup
    human = verifier.verify(_token(private, _claims(profile)), now=NOW)
    assert human.token_kind is IdentityKind.HUMAN
    assert human.authentication_strength is AuthenticationStrength.STRONG
    service_claims = _claims(
        profile, sub="service:etl", aud="analysis-service", client_id="etl-client",
        principal_kind="SERVICE",
    )
    service_claims.pop("amr")
    service = verifier.verify(_token(private, service_claims), now=NOW)
    assert service.token_kind is IdentityKind.SERVICE
    assert service.service_client_id == "etl-client"
    assert service.authentication_strength is AuthenticationStrength.STRONG


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"tenant_id": "Tenant-One"}, "INVALID_TENANT"),
        ({"sub": "user ü"}, "INVALID_SUBJECT"),
        ({"jti": "short"}, "INVALID_JTI"),
        ({"claims_version": "auth-claims/2"}, "UNSUPPORTED_CLAIMS_VERSION"),
        ({"aud": "wrong-audience"}, "INVALID_AUDIENCE"),
        ({"iat": int((NOW + timedelta(minutes=2)).timestamp())}, "TOKEN_TIME_REJECTED"),
    ],
)
def test_claim_profile_rejections_are_fail_closed(jwt_setup, change, reason):
    private, profile, verifier = jwt_setup
    with pytest.raises(JwtValidationError) as caught:
        verifier.verify(_token(private, _claims(profile, **change)), now=NOW)
    assert caught.value.reason == reason
    assert str(caught.value) == "Access token is invalid."


def test_duplicate_and_forbidden_jose_headers_are_rejected_before_crypto(jwt_setup):
    _private, profile, verifier = jwt_setup
    payload = json.dumps(_claims(profile), separators=(",", ":"))
    duplicate = _segment('{"alg":"RS256","alg":"RS256","kid":"key-1","typ":"at+jwt"}')
    with pytest.raises(JwtValidationError) as caught:
        verifier.verify(f"{duplicate}.{_segment(payload)}.signature", now=NOW)
    assert caught.value.reason == "DUPLICATE_JSON_KEY"
    forbidden = _segment('{"alg":"RS256","kid":"key-1","typ":"at+jwt","jku":"https://evil.test"}')
    with pytest.raises(JwtValidationError) as caught:
        verifier.verify(f"{forbidden}.{_segment(payload)}.signature", now=NOW)
    assert caught.value.reason == "FORBIDDEN_JOSE_HEADER"


def test_duplicate_claim_and_noncanonical_base64_are_rejected(jwt_setup):
    _private, profile, verifier = jwt_setup
    header = _segment('{"alg":"RS256","kid":"key-1","typ":"at+jwt"}')
    claims = _claims(profile)
    duplicate_payload = json.dumps(claims)[:-1] + ',"sub":"attacker"}'
    with pytest.raises(JwtValidationError) as caught:
        verifier.verify(f"{header}.{_segment(duplicate_payload)}.signature", now=NOW)
    assert caught.value.reason == "DUPLICATE_JSON_KEY"
    with pytest.raises(JwtValidationError) as caught:
        verifier.verify(f"{header}=.{_segment(json.dumps(claims))}.signature", now=NOW)
    assert caught.value.reason == "NON_CANONICAL_BASE64URL"


def test_signature_failure_never_exposes_upstream_error(jwt_setup):
    private, profile, verifier = jwt_setup
    token = _token(private, _claims(profile))[:-3] + "abc"
    with pytest.raises(JwtValidationError) as caught:
        verifier.verify(token, now=NOW)
    assert caught.value.reason == "SIGNATURE_REJECTED"
    assert "signature" not in str(caught.value).lower()


def test_bearer_transport_is_exact():
    assert extract_bearer_token(("Bearer abc.def.sig",)) == "abc.def.sig"
    for values in ((), ("bearer token",), ("Bearer a, Bearer b",), ("Bearer a", "Bearer b")):
        with pytest.raises(JwtValidationError):
            extract_bearer_token(values)
