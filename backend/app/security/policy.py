"""Closed, versioned permission and built-in-role registry."""

from __future__ import annotations

from types import MappingProxyType

from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.security.contracts import ExistenceHidingPolicy, PermissionDefinition


def _permission(
    code: str, resource: str, action: str, scope: str,
    strength: AuthenticationStrength, human: bool, service: bool,
    hiding: ExistenceHidingPolicy,
) -> PermissionDefinition:
    return PermissionDefinition(code, resource, action, scope, strength, human, service, hiding)


B = AuthenticationStrength.BASIC
S = AuthenticationStrength.STRONG
P = AuthenticationStrength.PHISHING_RESISTANT
D403 = ExistenceHidingPolicy.DENY_403
H404 = ExistenceHidingPolicy.HIDE_404
C409 = ExistenceHidingPolicy.RUN_CONFLICT_409

_DEFINITIONS = (
    _permission("system.metadata.read", "SYSTEM", "READ", "GLOBAL", B, True, True, D403),
    _permission("company.create", "COMPANY", "CREATE", "TENANT", S, True, False, D403),
    _permission("company.list", "COMPANY", "LIST", "TENANT", B, True, True, D403),
    _permission("company.read", "COMPANY", "READ", "COMPANY", B, True, True, H404),
    _permission("period.create", "PERIOD", "CREATE", "COMPANY", S, True, False, H404),
    _permission("period.list", "PERIOD", "LIST", "COMPANY", B, True, True, H404),
    _permission("period.read", "PERIOD", "READ", "PERIOD", B, True, True, H404),
    _permission("document.list", "DOCUMENT", "LIST", "PERIOD", B, True, True, H404),
    _permission("document.read", "DOCUMENT", "READ", "DOCUMENT", B, True, True, H404),
    _permission("analysis_result.list", "ANALYSIS_RESULT", "LIST", "DOCUMENT", B, True, True, H404),
    _permission("analysis_result.read", "ANALYSIS_RESULT", "READ", "ANALYSIS_RESULT", B, True, True, H404),
    _permission("trial_balance.validate", "TRIAL_BALANCE", "VALIDATE", "TENANT", S, True, True, D403),
    _permission("trial_balance.upload", "TRIAL_BALANCE", "UPLOAD", "PERIOD", S, True, True, H404),
    _permission("bulk_upload.create", "BULK_UPLOAD", "CREATE", "TENANT", S, True, False, D403),
    _permission("bulk_upload.read", "BULK_UPLOAD", "READ", "BULK_BATCH", B, True, False, H404),
    _permission("bulk_upload.update", "BULK_UPLOAD", "UPDATE", "BULK_BATCH", S, True, False, H404),
    _permission("bulk_upload.confirm", "BULK_UPLOAD", "CONFIRM", "BULK_BATCH", S, True, False, H404),
    _permission("analysis.start", "ANALYSIS_RUN", "START", "COMPANY_PERIOD", S, True, True, D403),
    _permission("analysis.resume", "ANALYSIS_RUN", "RESUME", "COMPANY_PERIOD", S, True, True, C409),
    _permission("analysis.resume_source", "ANALYSIS_RUN", "RESUME_SOURCE", "ANALYSIS_RUN", S, True, True, H404),
    _permission("analysis.retry", "ANALYSIS_RUN", "RETRY", "COMPANY_PERIOD", S, True, True, C409),
    _permission("analysis.cancel.own", "ANALYSIS_RUN", "CANCEL_OWN", "ANALYSIS_RUN", S, True, True, H404),
    _permission("analysis.cancel.any", "ANALYSIS_RUN", "CANCEL_ANY", "ANALYSIS_RUN", S, True, False, H404),
    _permission("analysis.read", "ANALYSIS_RUN", "APPLICATION_READ_GUARD", "ANALYSIS_RUN", B, True, True, H404),
    _permission("analysis.payload.read", "ANALYSIS_RUN", "APPLICATION_PAYLOAD_GUARD", "ANALYSIS_RUN", B, True, True, H404),
    _permission("analysis.status.read", "ANALYSIS_RUN", "STATUS_READ", "ANALYSIS_RUN", B, True, True, H404),
    _permission("analysis.result.read", "ANALYSIS_RUN", "RESULT_METADATA_READ", "ANALYSIS_RUN", B, True, True, H404),
    _permission("analysis.result.payload.read", "ANALYSIS_RUN", "RESULT_PAYLOAD_READ", "ANALYSIS_RUN", B, True, True, H404),
    _permission("analysis.history.read", "ANALYSIS_RUN", "HISTORY_READ", "COMPANY_PERIOD", B, True, True, D403),
    _permission("analysis.execution.read", "ANALYSIS_RUN", "EXECUTION_METADATA_READ", "ANALYSIS_RUN", B, True, True, H404),
    _permission("analysis.execution.payload.read", "ANALYSIS_RUN", "EXECUTION_PAYLOAD_READ", "ANALYSIS_RUN", B, True, True, H404),
    _permission("security.membership.manage", "SECURITY_MEMBERSHIP", "MANAGE", "TENANT", P, True, False, H404),
    _permission("security.role.assign", "SECURITY_ROLE", "ASSIGN", "TENANT", P, True, False, H404),
)


def _build_permissions() -> MappingProxyType[str, PermissionDefinition]:
    result: dict[str, PermissionDefinition] = {}
    triples: set[tuple[str, str, str]] = set()
    for definition in _DEFINITIONS:
        triple = (definition.resource_type, definition.action, definition.scope_type)
        if definition.permission_code in result or triple in triples:
            raise RuntimeError("Permission registry contains a duplicate definition.")
        result[definition.permission_code] = definition
        triples.add(triple)
    return MappingProxyType(result)


PERMISSION_REGISTRY = _build_permissions()

_TENANT_ADMIN = tuple(PERMISSION_REGISTRY)
_FINANCE_ADMIN = tuple(code for code in _TENANT_ADMIN if not code.startswith("security."))
_FINANCE_ANALYST_EXCLUDED = {
    "company.create", "period.create", "bulk_upload.confirm", "analysis.cancel.any",
}
_FINANCE_ANALYST = tuple(code for code in _FINANCE_ADMIN if code not in _FINANCE_ANALYST_EXCLUDED)
_REPORT_VIEWER = (
    "system.metadata.read", "company.list", "company.read", "period.list", "period.read",
    "analysis_result.list", "analysis_result.read", "analysis.read", "analysis.payload.read",
    "analysis.status.read", "analysis.result.read", "analysis.result.payload.read",
    "analysis.history.read", "analysis.execution.read", "analysis.execution.payload.read",
)
_AUDITOR = (
    "system.metadata.read", "company.list", "company.read", "period.list", "period.read",
    "document.list", "document.read", "analysis_result.list", "analysis_result.read",
    "bulk_upload.read", "analysis.read", "analysis.payload.read", "analysis.status.read",
    "analysis.result.read", "analysis.result.payload.read", "analysis.history.read",
    "analysis.execution.read", "analysis.execution.payload.read",
)
_SERVICE_OPERATOR = tuple(
    code for code in _FINANCE_ANALYST
    if PERMISSION_REGISTRY[code].service_allowed
)

BUILT_IN_ROLE_PERMISSIONS = MappingProxyType({
    "TENANT_ADMIN": _TENANT_ADMIN,
    "FINANCE_ADMIN": _FINANCE_ADMIN,
    "FINANCE_ANALYST": _FINANCE_ANALYST,
    "REPORT_VIEWER": _REPORT_VIEWER,
    "AUDITOR": _AUDITOR,
    "SERVICE_OPERATOR": _SERVICE_OPERATOR,
})

for _role, _codes in BUILT_IN_ROLE_PERMISSIONS.items():
    if len(_codes) != len(set(_codes)) or any(code not in PERMISSION_REGISTRY for code in _codes):
        raise RuntimeError(f"Built-in role registry is invalid: {_role}")
