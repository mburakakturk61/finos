"""Strict provider-neutral compact-JWS access-token verification."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone

import jwt

from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.security.contracts import (
    CLAIMS_VERSION,
    JTI_PATTERN,
    SERVICE_CLIENT_PATTERN,
    SUBJECT_PATTERN,
    TENANT_KEY_PATTERN,
    IdentityKind,
    IssuerRegistry,
    JwtAlgorithm,
    OidcIssuerProfile,
    VerificationKeyProviderPort,
    VerifiedJwt,
)


_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_FORBIDDEN_HEADERS = frozenset({"jwk", "jku", "x5u", "x5c", "x5t", "x5t#S256", "b64", "crit"})
_MAX_TOKEN_BYTES = 16 * 1024
_MAX_TIME = 2**63 - 1


class JwtValidationError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__("Access token is invalid.")
        self.reason = reason


class JwtProviderUnavailable(RuntimeError):
    pass


def extract_bearer_token(headers: tuple[str, ...]) -> str:
    if len(headers) != 1:
        raise JwtValidationError("BEARER_HEADER_COUNT")
    value = headers[0]
    if "," in value or "\r" in value or "\n" in value:
        raise JwtValidationError("BEARER_HEADER_MALFORMED")
    parts = value.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1]:
        raise JwtValidationError("BEARER_HEADER_MALFORMED")
    return parts[1]


def _pairs_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise JwtValidationError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _decode_segment(segment: str) -> dict[str, object]:
    if not segment or "=" in segment or not _BASE64URL.fullmatch(segment):
        raise JwtValidationError("NON_CANONICAL_BASE64URL")
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != segment:
            raise JwtValidationError("NON_CANONICAL_BASE64URL")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_object)
    except JwtValidationError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise JwtValidationError("MALFORMED_JSON") from exc
    if not isinstance(value, dict):
        raise JwtValidationError("JSON_OBJECT_REQUIRED")
    return value


def _string(value: object, reason: str, *, minimum: int = 1, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise JwtValidationError(reason)
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise JwtValidationError(reason) from exc
    return value


def _numeric_date(claims: dict[str, object], name: str, *, required: bool) -> int | None:
    value = claims.get(name)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not -(2**63) <= value <= _MAX_TIME:
        raise JwtValidationError(f"INVALID_{name.upper()}")
    return value


def _audiences(value: object) -> tuple[str, ...]:
    values = (value,) if isinstance(value, str) else value
    if not isinstance(values, list | tuple) or not values:
        raise JwtValidationError("INVALID_AUDIENCE")
    if any(not isinstance(item, str) or not item for item in values):
        raise JwtValidationError("INVALID_AUDIENCE")
    if len(values) != len(set(values)):
        raise JwtValidationError("DUPLICATE_AUDIENCE")
    return tuple(values)


class ProviderNeutralJwtVerifier:
    def __init__(self, issuers: IssuerRegistry, keys: VerificationKeyProviderPort) -> None:
        self._issuers = issuers
        self._keys = keys

    @property
    def trusted_issuers(self) -> frozenset[str]:
        return self._issuers.issuers

    def readiness_check(self, deadline: datetime) -> bool:
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            return False
        try:
            return bool(self._issuers.issuers) and bool(self._keys.readiness_check(deadline))
        except Exception:
            return False

    def verify(self, token: str, *, now: datetime) -> VerifiedJwt:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("JWT verification clock must be timezone-aware.")
        if not isinstance(token, str) or not token or len(token.encode("ascii", "ignore")) > _MAX_TOKEN_BYTES:
            raise JwtValidationError("TOKEN_SIZE")
        segments = token.split(".")
        if len(segments) != 3 or not segments[2]:
            raise JwtValidationError("COMPACT_JWS_REQUIRED")
        header = _decode_segment(segments[0])
        claims = _decode_segment(segments[1])
        if _FORBIDDEN_HEADERS & header.keys():
            raise JwtValidationError("FORBIDDEN_JOSE_HEADER")
        if set(header) - {"alg", "kid", "typ"}:
            raise JwtValidationError("UNKNOWN_JOSE_HEADER")
        algorithm_raw = _string(header.get("alg"), "INVALID_ALGORITHM", maximum=16)
        kid = _string(header.get("kid"), "INVALID_KID", maximum=128)
        typ = _string(header.get("typ"), "INVALID_TYPE", maximum=32)
        try:
            algorithm = JwtAlgorithm(algorithm_raw)
        except ValueError as exc:
            raise JwtValidationError("DISALLOWED_ALGORITHM") from exc
        issuer = _string(claims.get("iss"), "INVALID_ISSUER", maximum=512)
        profile = self._issuers.get(issuer)
        if profile is None:
            raise JwtValidationError("UNTRUSTED_ISSUER")
        if algorithm not in profile.allowed_algorithms or typ not in profile.allowed_types:
            raise JwtValidationError("ISSUER_PROFILE_MISMATCH")
        key = self._keys.get_key(profile, kid, algorithm, now=now)
        if key.issuer != issuer or key.kid != kid or key.algorithm is not algorithm:
            raise JwtValidationError("KEY_BINDING_MISMATCH")
        try:
            jwt.decode(
                token,
                key.key,
                algorithms=[algorithm.value],
                options={
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "verify_aud": False,
                    "verify_iss": False,
                    "require": ["iss", "sub", "aud", "exp", "iat", "jti", profile.tenant_claim, profile.claims_version_claim],
                },
            )
        except jwt.PyJWTError as exc:
            raise JwtValidationError("SIGNATURE_REJECTED") from exc
        return self._validate_claims(profile, header, claims, now)

    def _validate_claims(
        self, profile: OidcIssuerProfile, header: dict[str, object],
        claims: dict[str, object], now: datetime,
    ) -> VerifiedJwt:
        issuer = str(claims["iss"])
        subject = _string(claims.get("sub"), "INVALID_SUBJECT", maximum=255)
        if not SUBJECT_PATTERN.fullmatch(subject):
            raise JwtValidationError("INVALID_SUBJECT")
        if any(alias in claims for alias in {"tenant", "tid"}):
            raise JwtValidationError("AMBIGUOUS_TENANT_CLAIM")
        tenant = _string(claims.get(profile.tenant_claim), "INVALID_TENANT", maximum=63)
        if not TENANT_KEY_PATTERN.fullmatch(tenant):
            raise JwtValidationError("INVALID_TENANT")
        jti = _string(claims.get("jti"), "INVALID_JTI", minimum=16, maximum=128)
        if not JTI_PATTERN.fullmatch(jti):
            raise JwtValidationError("INVALID_JTI")
        version = claims.get(profile.claims_version_claim)
        if version != CLAIMS_VERSION:
            raise JwtValidationError("UNSUPPORTED_CLAIMS_VERSION")
        audiences = _audiences(claims.get("aud"))
        audience_set = set(audiences)
        human = audience_set & profile.human_audiences
        service = audience_set & profile.service_audiences
        if bool(human) == bool(service) or not audience_set <= (profile.human_audiences | profile.service_audiences):
            raise JwtValidationError("INVALID_AUDIENCE")
        token_kind = IdentityKind.HUMAN if human else IdentityKind.SERVICE
        hint = claims.get("principal_kind")
        if hint is not None and hint != token_kind.value:
            raise JwtValidationError("PRINCIPAL_KIND_MISMATCH")
        iat = _numeric_date(claims, "iat", required=True)
        exp = _numeric_date(claims, "exp", required=True)
        nbf = _numeric_date(claims, "nbf", required=False)
        assert iat is not None and exp is not None
        now_seconds = int(now.timestamp())
        if exp <= iat or not 1 <= exp - iat <= 900:
            raise JwtValidationError("INVALID_TOKEN_LIFETIME")
        if iat > now_seconds + 60 or exp <= now_seconds - 60 or (nbf is not None and nbf > now_seconds + 60):
            raise JwtValidationError("TOKEN_TIME_REJECTED")
        strength, client_id = self._identity_profile(profile, claims, token_kind)
        return VerifiedJwt(
            issuer=issuer, subject=subject, tenant_key=tenant, token_kind=token_kind,
            audience=tuple(sorted(audiences)), issued_at=datetime.fromtimestamp(iat, timezone.utc),
            expires_at=datetime.fromtimestamp(exp, timezone.utc),
            not_before=datetime.fromtimestamp(nbf, timezone.utc) if nbf is not None else None,
            jti=jti, claims_version=CLAIMS_VERSION, authentication_strength=strength,
            kid=str(header["kid"]), algorithm=JwtAlgorithm(str(header["alg"])),
            service_client_id=client_id,
        )

    @staticmethod
    def _identity_profile(
        profile: OidcIssuerProfile, claims: dict[str, object], kind: IdentityKind,
    ) -> tuple[AuthenticationStrength, str | None]:
        if kind is IdentityKind.SERVICE:
            client_id = claims.get("client_id")
            if not isinstance(client_id, str) or not SERVICE_CLIENT_PATTERN.fullmatch(client_id):
                raise JwtValidationError("INVALID_SERVICE_CLIENT")
            return AuthenticationStrength.STRONG, client_id
        client_id = claims.get("client_id")
        if client_id is not None:
            raise JwtValidationError("HUMAN_CLIENT_ID_FORBIDDEN")
        acr = claims.get("acr")
        amr = claims.get("amr")
        if acr is not None and not isinstance(acr, str):
            raise JwtValidationError("INVALID_ACR")
        if amr is not None and (
            not isinstance(amr, list) or not amr
            or any(not isinstance(value, str) or not value for value in amr)
            or len(amr) != len(set(amr))
        ):
            raise JwtValidationError("INVALID_AMR")
        evidence = ({("acr", acr)} if acr else set()) | {("amr", value) for value in (amr or [])}
        matches = {rule.strength for rule in profile.strength_mapping if (rule.evidence_type, rule.evidence_value) in evidence}
        if not matches:
            raise JwtValidationError("AUTHENTICATION_STRENGTH_UNKNOWN")
        return max(matches, key=lambda item: list(AuthenticationStrength).index(item)), None
