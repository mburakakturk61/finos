import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request

from app.analysis_application.ports import AuthorizationDecision
from app.integrations.analysis_http.contracts import AuthenticationContext, AuthenticationStrength
from app.integrations.analysis_http.legacy_security import (
    PUBLIC_ROUTE_ALLOWLIST,
    ROUTE_SECURITY_MANIFEST,
    ROUTE_SECURITY_REGISTRY,
    RouteClassification,
    build_route_security_registry,
    require_legacy_route_security,
    resolve_legacy_tenant_id,
    validate_registered_route_inventory,
)
from app.integrations.analysis_http.router_security import (
    RouterAuthenticationError,
    RouterAuthenticationErrorCode,
)
from app.main import app
from app.models.company import Company
from app.models.security import SecurityTenant


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CORRELATION = "legacy-correlation"


class _Clock:
    def now_audit_time(self):
        return NOW


class _Provider:
    def __init__(self, subject: str, *, stale: bool = False):
        self._context = AuthenticationContext(
            subject_id=subject,
            tenant_id="tenant-a",
            authentication_method="oidc_bearer_jwt",
            authentication_strength=AuthenticationStrength.STRONG,
            issued_at=NOW - (timedelta(minutes=16) if stale else timedelta(minutes=1)),
            expires_at=NOW + timedelta(minutes=5),
            correlation_id=CORRELATION,
            claims_version="1",
            trusted_issuer="issuer",
            authorization_context_reference="authz:v1:H:00000000-0000-4000-8000-000000000001:1:1",
        )

    def current_context(self):
        return self._context


class _LegacySecurity:
    is_fake = False
    retry_after_seconds = 3

    def __init__(self, decision_code="AUTHZ_ALLOWED", *, saturated=False):
        self.decision_code = decision_code
        self.saturated = saturated
        self.acquired = 0
        self.released = 0
        self.calls = []
        self._lock = threading.Lock()

    def try_acquire(self, **_kwargs):
        if self.saturated:
            return None
        with self._lock:
            self.acquired += 1
        return object()

    def release(self, _lease):
        with self._lock:
            self.released += 1

    def authorize(self, *, definition, request, authentication_provider):
        with self._lock:
            self.calls.append(
                (definition.permission, authentication_provider.current_context().subject_id)
            )
        granted = self.decision_code == "AUTHZ_ALLOWED"
        return AuthorizationDecision(granted, False, self.decision_code, "adr1:" + "a" * 64, NOW)

    def readiness_check(self, _deadline):
        return True


class _Runtime:
    trusted_issuers = frozenset({"issuer"})

    def __init__(self, *, decision_code="AUTHZ_ALLOWED", saturated=False):
        self.clock = _Clock()
        self.legacy_security = _LegacySecurity(decision_code, saturated=saturated)

    def authenticate_request(self, *, authorization_headers, **_kwargs):
        if not authorization_headers:
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.MISSING)
        token = authorization_headers[0]
        if token == "Bearer invalid":
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.INVALID)
        if token == "Bearer unavailable":
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.UNAVAILABLE)
        if not token.startswith("Bearer subject-") and token != "Bearer stale":
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.INVALID)
        return _Provider(
            "stale-subject" if token == "Bearer stale" else token.removeprefix("Bearer "),
            stale=token == "Bearer stale",
        )

    def authorize_legacy_request(self, **kwargs):
        return self.legacy_security.authorize(**kwargs)


@pytest.fixture()
def secured_client(client):
    app.dependency_overrides.pop(require_legacy_route_security, None)
    yield client
    app.dependency_overrides[require_legacy_route_security] = lambda: None


def _headers(token="Bearer subject-a"):
    return {"Authorization": token, "X-Correlation-ID": CORRELATION}


def test_route_manifest_is_exact_complete_and_public_allowlist_is_exhaustive():
    assert len(ROUTE_SECURITY_MANIFEST) == 28
    assert len(ROUTE_SECURITY_REGISTRY) == 28
    assert PUBLIC_ROUTE_ALLOWLIST == {
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
    }
    assert sum(item.classification is RouteClassification.PROTECTED for item in ROUTE_SECURITY_MANIFEST) == 26
    validate_registered_route_inventory(app)


def test_duplicate_or_unclassified_route_fails_closed():
    with pytest.raises(RuntimeError, match="Duplicate route"):
        build_route_security_registry((ROUTE_SECURITY_MANIFEST[0], ROUTE_SECURITY_MANIFEST[0]))
    rogue = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @rogue.get("/rogue")
    def rogue_route():
        return None

    with pytest.raises(RuntimeError, match="inventory mismatch"):
        validate_registered_route_inventory(rogue)


def test_public_and_disabled_production_routes_are_exact(client):
    assert client.get("/health/live").json() == {"status": "live"}
    ready = client.get("/health/ready")
    assert set(ready.json()) == {"ready", "status"}
    for path in ("/", "/health", "/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        (item.method, item.path.replace("{company_id}", "00000000-0000-4000-8000-000000000001")
         .replace("{period_id}", "00000000-0000-4000-8000-000000000002")
         .replace("{document_id}", "00000000-0000-4000-8000-000000000003")
         .replace("{analysis_id}", "00000000-0000-4000-8000-000000000004")
         .replace("{batch_id}", "00000000-0000-4000-8000-000000000005")
         .replace("{item_id}", "00000000-0000-4000-8000-000000000006"))
        for item in ROUTE_SECURITY_MANIFEST
        if item.classification is RouteClassification.PROTECTED
        and not item.path.startswith("/api/v1/analysis-runs")
    ],
)
def test_every_legacy_route_requires_bearer(secured_client, monkeypatch, method, path):
    runtime = _Runtime()
    monkeypatch.setattr(
        "app.integrations.analysis_http.legacy_security.get_analysis_api_runtime",
        lambda: runtime,
    )
    response = secured_client.request(method, path, json={})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="api"'
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert runtime.legacy_security.acquired == runtime.legacy_security.released == 1


@pytest.mark.parametrize(
    ("token", "expected_status", "expected_code", "www"),
    [
        ("Bearer invalid", 401, "INVALID_TOKEN", 'Bearer realm="api", error="invalid_token"'),
        ("Bearer stale", 401, "INVALID_TOKEN", 'Bearer realm="api", error="invalid_token"'),
        ("Bearer unavailable", 503, "AUTHENTICATION_PROVIDER_UNAVAILABLE", None),
    ],
)
def test_authentication_failures_are_closed_and_redacted(secured_client, monkeypatch, token, expected_status, expected_code, www):
    runtime = _Runtime()
    monkeypatch.setattr("app.integrations.analysis_http.legacy_security.get_analysis_api_runtime", lambda: runtime)
    response = secured_client.get("/api/v1/companies", headers=_headers(token))
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert response.headers.get("WWW-Authenticate") == www
    assert token not in response.text
    assert runtime.legacy_security.acquired == runtime.legacy_security.released == 1


def test_raw_identity_headers_are_rejected_before_runtime(secured_client):
    response = secured_client.get(
        "/api/v1/companies",
        headers={"X-User-Id": "forged", "X-Tenant-Id": "forged", "X-Correlation-ID": CORRELATION},
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="api"'


@pytest.mark.parametrize(
    ("decision_code", "status", "public_code"),
    [
        ("AUTHZ_PERMISSION_NOT_GRANTED", 403, "UNAUTHORIZED"),
        ("AUTHZ_STRENGTH_INSUFFICIENT", 403, "UNAUTHORIZED"),
        ("AUTHZ_PRINCIPAL_KIND_NOT_ALLOWED", 403, "UNAUTHORIZED"),
        ("AUTHZ_TENANT_MISMATCH", 403, "UNAUTHORIZED"),
        ("AUTHZ_RESOURCE_NOT_FOUND", 404, "NOT_FOUND"),
        ("AUTHZ_RESOURCE_STATE_INVALID", 404, "NOT_FOUND"),
        ("AUTHZ_PROVIDER_UNAVAILABLE", 503, "AUTHORIZATION_PROVIDER_UNAVAILABLE"),
        ("AUTHZ_PROVIDER_TIMEOUT", 503, "AUTHORIZATION_PROVIDER_UNAVAILABLE"),
        ("AUDIT_REQUIRED_BUT_UNAVAILABLE", 503, "AUTHORIZATION_PROVIDER_UNAVAILABLE"),
    ],
)
def test_authorization_mapping_is_closed(secured_client, monkeypatch, decision_code, status, public_code):
    runtime = _Runtime(decision_code=decision_code)
    monkeypatch.setattr("app.integrations.analysis_http.legacy_security.get_analysis_api_runtime", lambda: runtime)
    response = secured_client.get("/api/v1/companies", headers=_headers())
    assert response.status_code == status
    assert response.json()["error"]["code"] == public_code
    assert decision_code not in response.text
    assert "WWW-Authenticate" not in response.headers
    assert runtime.legacy_security.acquired == runtime.legacy_security.released == 1


@pytest.mark.parametrize(
    ("route_path", "request_path", "permission"),
    [
        ("/api/v1/companies/{company_id}", "/api/v1/companies/00000000-0000-4000-8000-000000000001", "company.read"),
        ("/api/v1/periods/{period_id}", "/api/v1/periods/00000000-0000-4000-8000-000000000002", "period.read"),
        ("/api/v1/documents/{document_id}", "/api/v1/documents/00000000-0000-4000-8000-000000000003", "document.read"),
        ("/api/v1/analyses/{analysis_id}", "/api/v1/analyses/00000000-0000-4000-8000-000000000004", "analysis_result.read"),
        ("/api/v1/bulk-uploads/{batch_id}", "/api/v1/bulk-uploads/00000000-0000-4000-8000-000000000005", "bulk_upload.read"),
        ("/api/v1/periods/{period_id}/trial-balances", "/api/v1/periods/00000000-0000-4000-8000-000000000002/trial-balances", "trial_balance.upload"),
    ],
)
def test_legacy_resource_groups_use_exact_authorization_manifest(monkeypatch, route_path, request_path, permission):
    runtime = _Runtime()
    monkeypatch.setattr("app.integrations.analysis_http.legacy_security.get_analysis_api_runtime", lambda: runtime)

    async def invoke():
        request = Request({
            "type": "http",
            "method": "POST" if permission == "trial_balance.upload" else "GET",
            "path": request_path,
            "headers": [
                (b"authorization", b"Bearer subject-a"),
                (b"x-correlation-id", CORRELATION.encode()),
            ],
            "route": SimpleNamespace(path=route_path),
        })
        dependency = require_legacy_route_security(request)
        await dependency.__anext__()
        await dependency.aclose()

    asyncio.run(invoke())
    assert runtime.legacy_security.calls == [(permission, "subject-a")]
    assert runtime.legacy_security.acquired == runtime.legacy_security.released == 1


def test_model_a_cross_tenant_durable_resource_is_hidden(secured_client, monkeypatch):
    runtime = _Runtime(decision_code="AUTHZ_TENANT_MISMATCH")
    monkeypatch.setattr("app.integrations.analysis_http.legacy_security.get_analysis_api_runtime", lambda: runtime)
    response = secured_client.get(
        "/api/v1/companies/00000000-0000-4000-8000-000000000001",
        headers=_headers(),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_allow_uses_exact_permission_and_releases_lease(secured_client, monkeypatch):
    runtime = _Runtime()
    monkeypatch.setattr("app.integrations.analysis_http.legacy_security.get_analysis_api_runtime", lambda: runtime)
    response = secured_client.get("/api/v1/companies", headers=_headers())
    assert response.status_code == 200
    assert runtime.legacy_security.calls == [("company.list", "subject-a")]
    assert runtime.legacy_security.acquired == runtime.legacy_security.released == 1


def test_saturation_is_429_with_retry_after_and_no_authentication(secured_client, monkeypatch):
    runtime = _Runtime(saturated=True)
    monkeypatch.setattr("app.integrations.analysis_http.legacy_security.get_analysis_api_runtime", lambda: runtime)
    response = secured_client.get("/api/v1/companies", headers=_headers())
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3"
    assert runtime.legacy_security.calls == []


def test_concurrent_requests_have_no_subject_leakage(monkeypatch):
    runtime = _Runtime()
    monkeypatch.setattr("app.integrations.analysis_http.legacy_security.get_analysis_api_runtime", lambda: runtime)

    async def invoke(index):
        headers = [
            (b"authorization", f"Bearer subject-{index}".encode()),
            (b"x-correlation-id", CORRELATION.encode()),
        ]
        request = Request({
            "type": "http", "method": "GET", "path": "/api/v1/companies",
            "headers": headers,
            "route": SimpleNamespace(path="/api/v1/companies"),
        })
        dependency = require_legacy_route_security(request)
        provider = await dependency.__anext__()
        subject = request.state.authentication_context.subject_id
        assert provider.current_context().subject_id == subject
        await dependency.aclose()
        return subject

    with ThreadPoolExecutor(max_workers=8) as executor:
        subjects = tuple(executor.map(lambda index: asyncio.run(invoke(index)), range(16)))
    assert subjects == tuple(f"subject-{index}" for index in range(16))
    assert sorted(runtime.legacy_security.calls) == sorted(("company.list", value) for value in subjects)
    assert runtime.legacy_security.acquired == runtime.legacy_security.released == 16


def test_legacy_list_get_and_write_paths_are_tenant_isolated(client, db_session):
    tenant_a = SecurityTenant(tenant_key="tenant-a", status="ACTIVE")
    tenant_b = SecurityTenant(tenant_key="tenant-b", status="ACTIVE")
    db_session.add_all((tenant_a, tenant_b))
    db_session.commit()
    current = {"tenant": "tenant-b"}

    async def trusted_security(request: Request):
        request.state.authentication_context = SimpleNamespace(tenant_id=current["tenant"])
        yield object()

    app.dependency_overrides[require_legacy_route_security] = trusted_security
    app.dependency_overrides.pop(resolve_legacy_tenant_id, None)

    company_body = {
        "legal_name": "Tenant B Company",
        "tax_number": "TENANT-B-001",
        "currency": "TRY",
    }
    company_b = client.post("/api/v1/companies", json=company_body)
    assert company_b.status_code == 201, company_b.text
    company_b_id = company_b.json()["id"]
    period_b = client.post(
        f"/api/v1/companies/{company_b_id}/periods",
        json={
            "year": 2026, "period_type": "year_end", "period_number": 4,
            "start_date": "2026-01-01", "end_date": "2026-12-31",
            "months_covered": 12, "is_year_end": True,
        },
    )
    assert period_b.status_code == 201, period_b.text
    period_b_id = period_b.json()["id"]
    batch_b = client.post(
        "/api/v1/bulk-uploads",
        files=[("files", ("opaque.txt", b"opaque", "text/plain"))],
    )
    assert batch_b.status_code == 201, batch_b.text
    batch_b_id = batch_b.json()["batch"]["id"]

    current["tenant"] = "tenant-a"
    listed = client.get("/api/v1/companies")
    assert listed.status_code == 200
    assert listed.json()["total"] == 0
    assert client.get(f"/api/v1/companies/{company_b_id}").status_code == 404
    assert client.get(f"/api/v1/companies/{company_b_id}/periods").status_code == 404
    assert client.get(f"/api/v1/periods/{period_b_id}").status_code == 404
    assert client.get(f"/api/v1/bulk-uploads/{batch_b_id}").status_code == 404

    batch_a = client.post(
        "/api/v1/bulk-uploads",
        files=[("files", ("opaque.txt", b"opaque", "text/plain"))],
    )
    assert batch_a.status_code == 201, batch_a.text
    item_a = batch_a.json()["items"][0]
    assert item_a["classification_status"] == "unrecognized"
    cross_tenant_resolution = client.patch(
        f"/api/v1/bulk-uploads/{batch_a.json()['batch']['id']}/items/{item_a['id']}",
        json={"company": {"mode": "existing", "id": company_b_id}},
    )
    assert cross_tenant_resolution.status_code == 422

    company_a = client.post(
        "/api/v1/companies",
        json={**company_body, "legal_name": "Tenant A Company", "tax_number": "TENANT-A-001"},
    )
    assert company_a.status_code == 201
    stored_tenant = db_session.get(Company, uuid.UUID(company_a.json()["id"])).tenant_id
    assert stored_tenant == tenant_a.id
