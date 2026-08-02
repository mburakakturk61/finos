"""Milestone 5.0E Step 14 exhaustive legacy route protection."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_application.ports import AuthorizationDecision
from app.db.session import get_db
from app.integrations.analysis_http.dependencies import get_analysis_api_runtime
from app.integrations.analysis_http.errors import ApiBoundaryError
from app.integrations.analysis_http.router_security import (
    RouterAuthenticationError,
    RouterAuthenticationErrorCode,
)
from app.integrations.analysis_http.security import validate_authentication_context
from app.integrations.analysis_http.contracts import AuthenticationContextError
from app.models.security import SecurityTenant


class RouteClassification(str, enum.Enum):
    PUBLIC = "PUBLIC"
    PROTECTED = "PROTECTED"


@dataclass(frozen=True)
class ProtectedRouteDefinition:
    method: str
    path: str
    classification: RouteClassification
    permission: str | None
    resource_scope: str
    rate_class: str
    envelope: str

    def __post_init__(self):
        if self.method not in {"GET", "POST", "PATCH"} or not self.path.startswith("/"):
            raise ValueError("route definition is invalid")
        if self.classification is RouteClassification.PUBLIC:
            if self.permission is not None or self.rate_class != "P0":
                raise ValueError("public route definition is invalid")
        elif not self.permission or self.rate_class not in {"P1", "P2", "P3"}:
            raise ValueError("protected route definition is invalid")


def _p(method, path, permission, scope, rate="P1", envelope="SEC"):
    return ProtectedRouteDefinition(method, path, RouteClassification.PROTECTED, permission, scope, rate, envelope)


class LegacyRouteAuthorizationPort(Protocol):
    """Trusted integration adapter; the router never resolves durable state."""

    is_fake: bool

    def authorize(
        self, *, definition: ProtectedRouteDefinition, request: Request,
        authentication_provider: object,
    ) -> AuthorizationDecision: ...

    def try_acquire(self, *, definition: ProtectedRouteDefinition, request: Request, acquired_at: object) -> object | None: ...

    def release(self, lease: object) -> None: ...

    def readiness_check(self, deadline: object) -> bool: ...


ROUTE_SECURITY_MANIFEST = (
    ProtectedRouteDefinition("GET", "/health/live", RouteClassification.PUBLIC, None, "GLOBAL", "P0", "MINIMAL"),
    ProtectedRouteDefinition("GET", "/health/ready", RouteClassification.PUBLIC, None, "GLOBAL", "P0", "MINIMAL"),
    _p("POST", "/api/v1/companies", "company.create", "TENANT"),
    _p("GET", "/api/v1/companies", "company.list", "TENANT"),
    _p("GET", "/api/v1/companies/{company_id}", "company.read", "COMPANY"),
    _p("POST", "/api/v1/companies/{company_id}/periods", "period.create", "COMPANY"),
    _p("GET", "/api/v1/companies/{company_id}/periods", "period.list", "COMPANY"),
    _p("GET", "/api/v1/periods/{period_id}", "period.read", "FINANCIAL_PERIOD"),
    _p("GET", "/api/v1/periods/{period_id}/documents", "document.list", "FINANCIAL_PERIOD"),
    _p("GET", "/api/v1/documents/{document_id}", "document.read", "DOCUMENT"),
    _p("GET", "/api/v1/documents/{document_id}/analyses", "analysis_result.list", "DOCUMENT"),
    _p("GET", "/api/v1/analyses/{analysis_id}", "analysis_result.read", "ANALYSIS_RESULT"),
    _p("POST", "/api/v1/periods/{period_id}/trial-balances", "trial_balance.upload", "FINANCIAL_PERIOD", "P3"),
    _p("POST", "/api/v1/trial-balance/validate", "trial_balance.validate", "TENANT", "P3"),
    _p("POST", "/api/v1/bulk-uploads", "bulk_upload.create", "TENANT", "P3"),
    _p("GET", "/api/v1/bulk-uploads/{batch_id}", "bulk_upload.read", "BULK_UPLOAD_BATCH"),
    _p("GET", "/api/v1/bulk-uploads/{batch_id}/items", "bulk_upload.read", "BULK_UPLOAD_BATCH"),
    _p("PATCH", "/api/v1/bulk-uploads/{batch_id}/items/{item_id}", "bulk_upload.update", "BULK_UPLOAD_BATCH"),
    _p("PATCH", "/api/v1/bulk-uploads/{batch_id}/items", "bulk_upload.update", "BULK_UPLOAD_BATCH"),
    _p("POST", "/api/v1/bulk-uploads/{batch_id}/confirm", "bulk_upload.confirm", "BULK_UPLOAD_BATCH", "P3"),
    _p("POST", "/api/v1/analysis-runs", "analysis.start", "COMPANY_PERIOD", "P2", "AN"),
    _p("POST", "/api/v1/analysis-runs/{previous_run_id}/resume", "analysis.resume", "ANALYSIS_RUN", "P2", "AN"),
    _p("POST", "/api/v1/analysis-runs/{previous_run_id}/retry", "analysis.retry", "ANALYSIS_RUN", "P2", "AN"),
    _p("POST", "/api/v1/analysis-runs/{run_id}/cancel", "analysis.cancel.own", "ANALYSIS_RUN", "P1", "AN"),
    _p("GET", "/api/v1/analysis-runs/{run_id}/status", "analysis.status.read", "ANALYSIS_RUN", "P1", "AN"),
    _p("GET", "/api/v1/analysis-runs/{run_id}/result", "analysis.result.read", "ANALYSIS_RUN", "P1", "AN"),
    _p("GET", "/api/v1/analysis-runs/{run_id}/executions/{engine_code}", "analysis.execution.read", "ANALYSIS_RUN", "P1", "AN"),
    _p("GET", "/api/v1/analysis-runs", "analysis.history.read", "COMPANY_PERIOD", "P1", "AN"),
)
def build_route_security_registry(definitions):
    registry = {}
    for item in definitions:
        key = (item.method, item.path)
        if key in registry:
            raise RuntimeError("Duplicate route security classification.")
        registry[key] = item
    return registry


ROUTE_SECURITY_REGISTRY = build_route_security_registry(ROUTE_SECURITY_MANIFEST)
PUBLIC_ROUTE_ALLOWLIST = frozenset(key for key, item in ROUTE_SECURITY_REGISTRY.items() if item.classification is RouteClassification.PUBLIC)


def resolve_legacy_tenant_id(
    request: Request,
    db: Session = Depends(get_db),
) -> uuid.UUID | None:
    """Resolve the authenticated tenant key to its authoritative internal UUID."""

    if getattr(request.state, "legacy_security_test_bypass", False):
        return None
    context = getattr(request.state, "authentication_context", None)
    tenant_key = getattr(context, "tenant_id", None)
    if not isinstance(tenant_key, str) or not tenant_key:
        raise ApiBoundaryError(
            "AUTHORIZATION_PROVIDER_UNAVAILABLE", 503,
            "Authorization is temporarily unavailable.",
            request.headers.get("x-correlation-id", "invalid"), True,
        )
    tenant_id = db.scalar(
        select(SecurityTenant.id).where(
            SecurityTenant.tenant_key == tenant_key,
            SecurityTenant.status == "ACTIVE",
        )
    )
    if not isinstance(tenant_id, uuid.UUID):
        raise ApiBoundaryError(
            "AUTHORIZATION_PROVIDER_UNAVAILABLE", 503,
            "Authorization is temporarily unavailable.",
            request.headers.get("x-correlation-id", "invalid"), True,
        )
    return tenant_id


def validate_registered_route_inventory(app) -> None:
    def collect(routes, prefix=""):
        inventory = set()
        for route in routes:
            original = getattr(route, "original_router", None)
            if original is not None:
                include_prefix = getattr(getattr(route, "include_context", None), "prefix", "")
                inventory.update(collect(original.routes, prefix + include_prefix))
                continue
            path = prefix + getattr(route, "path", "")
            inventory.update(
                (method, path)
                for method in getattr(route, "methods", ())
                if method in {"GET", "POST", "PATCH"}
            )
        return inventory

    registered = collect(app.routes)
    if registered != set(ROUTE_SECURITY_REGISTRY):
        missing = set(ROUTE_SECURITY_REGISTRY) - registered
        extra = registered - set(ROUTE_SECURITY_REGISTRY)
        raise RuntimeError(
            "Route security inventory mismatch: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )


async def require_legacy_route_security(request: Request):
    if any(name in request.headers for name in ("x-user-id", "x-tenant-id", "x-subject-id")):
        raise ApiBoundaryError("AUTHENTICATION_REQUIRED", 401, "Trusted authentication is required.", request.headers.get("x-correlation-id", "invalid"))
    correlation = request.headers.get("x-correlation-id", "invalid")
    route = request.scope.get("route")
    definition = ROUTE_SECURITY_REGISTRY.get((request.method, getattr(route, "path", "")))
    if definition is None or definition.classification is not RouteClassification.PROTECTED:
        raise ApiBoundaryError("SECURITY_ROUTE_UNCLASSIFIED", 503, "Route security is unavailable.", correlation, True)
    lease = None
    runtime = None
    try:
        try:
            runtime = get_analysis_api_runtime()
            lease = runtime.legacy_security.try_acquire(
                definition=definition, request=request,
                acquired_at=runtime.clock.now_audit_time(),
            )
            if lease is None:
                raise ApiBoundaryError(
                    "REQUEST_SATURATED", 429, "Request capacity is temporarily exhausted.",
                    correlation, True,
                    retry_after=runtime.legacy_security.retry_after_seconds,
                )
            provider = runtime.authenticate_request(
                authorization_headers=tuple(request.headers.getlist("authorization")),
                correlation_id=correlation,
                request_id=request.headers.get("x-request-id", correlation),
            )
            context = validate_authentication_context(
                provider.current_context(), correlation_id=correlation,
                trusted_issuers=runtime.trusted_issuers,
                now=runtime.clock.now_audit_time(),
            )
            decision = runtime.authorize_legacy_request(
                definition=definition, request=request,
                authentication_provider=provider,
            )
        except RouterAuthenticationError as error:
            if error.code is RouterAuthenticationErrorCode.UNAVAILABLE:
                raise ApiBoundaryError("AUTHENTICATION_PROVIDER_UNAVAILABLE", 503, "Authentication is temporarily unavailable.", correlation, True) from error
            code = "AUTHENTICATION_REQUIRED" if error.code is RouterAuthenticationErrorCode.MISSING else "INVALID_TOKEN"
            raise ApiBoundaryError(code, 401, "Trusted authentication is required.", correlation) from error
        except AuthenticationContextError as error:
            raise ApiBoundaryError("INVALID_TOKEN", 401, "Trusted authentication is required.", correlation) from error
        except ApiBoundaryError:
            raise
        except Exception as error:
            raise ApiBoundaryError("AUTHORIZATION_PROVIDER_UNAVAILABLE", 503, "Authorization is temporarily unavailable.", correlation, True) from error
        if not decision.granted:
            durable_scope = definition.resource_scope not in {"GLOBAL", "TENANT"}
            hidden = decision.decision_code in {
                "AUTHZ_RESOURCE_NOT_FOUND", "AUTHZ_RESOURCE_STATE_INVALID",
            } or (
                durable_scope and decision.decision_code in {
                    "AUTHZ_TENANT_MISMATCH", "AUTHZ_RESOURCE_OWNERSHIP_MISMATCH",
                }
            )
            if hidden:
                raise ApiBoundaryError("NOT_FOUND", 404, "The resource was not found.", correlation)
            if decision.decision_code in {"AUTHZ_PROVIDER_UNAVAILABLE", "AUTHZ_PROVIDER_TIMEOUT", "AUDIT_REQUIRED_BUT_UNAVAILABLE"}:
                raise ApiBoundaryError("AUTHORIZATION_PROVIDER_UNAVAILABLE", 503, "Authorization is temporarily unavailable.", correlation, True)
            raise ApiBoundaryError("UNAUTHORIZED", 403, "The request is not authorized.", correlation)
        request.state.authentication_context = context
        yield provider
    finally:
        if lease is not None and runtime is not None:
            runtime.legacy_security.release(lease)
