"""Milestone 5.0D synchronous analysis-run HTTP adapter."""

from __future__ import annotations

import dataclasses
import re
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from app.analysis_application.contracts import (
    ApplicationEngineCode, ApplicationEventType, ApplicationOperationKind,
    ApplicationOriginalOperation, ApplicationScopeDTO,
)
from app.analysis_application.ports import SecurityAuditEventDTO
from app.db.session import get_db
from app.integrations.analysis_http.contracts import (
    AuthenticationContextError, AuthenticationProviderUnavailable,
    InputResolutionCode, InputResolutionError,
)
from app.integrations.analysis_http.cursor import InvalidCursor
from app.integrations.analysis_http.dependencies import get_analysis_api_runtime
from app.integrations.analysis_http.errors import (
    ApiBoundaryError, boundary_error_dict, public_error_dict,
    status_for_application_error,
)
from app.integrations.analysis_http.mapping import (
    application_scope, audit_context, build_cancel_command,
    build_execution_command, build_history_query, build_run_query,
    resolve_inputs, to_wire,
)
from app.integrations.analysis_http.security import validate_authentication_context
from app.integrations.analysis_http.router_security import (
    RouterAuthenticationError,
    RouterAuthenticationErrorCode,
)
from app.security.authorization_adapter import AuthorizationCheckpoint
from app.security.authorization_policy import PolicyScopeType
from app.security.request_authentication import (
    RequestAuthorizationPlan,
    RequestAuthorizationTarget,
)
from app.schemas.analysis_runs_v1 import (
    AnalysisCommandResponseV1, AnalysisExecutionResponseV1,
    AnalysisHistoryPageResponseV1, AnalysisResultResponseV1,
    AnalysisRunStatusResponseV1, ApiErrorV1, ApiOutcomeResponseV1,
    ApiWarningV1, CancellationResponseV1, ResumeAnalysisRequestV1,
    RetryAnalysisRequestV1, StartAnalysisRequestV1,
)


_bearer_schema = HTTPBearer(auto_error=False, scheme_name="BearerAuth")
router = APIRouter(
    prefix="/api/v1/analysis-runs", tags=["analysis-runs"],
    dependencies=[Depends(_bearer_schema)],
)
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RAW_IDENTITY_HEADERS = frozenset({"x-user-id", "x-tenant-id", "x-subject-id"})


def require_analysis_runtime():
    try:
        return get_analysis_api_runtime()
    except Exception as exc:
        raise ApiBoundaryError(
            "API_RUNTIME_UNAVAILABLE", 503,
            "The analysis API runtime is unavailable.", "unavailable", True,
        ) from exc


def _headers(request, correlation_id, api_version, idempotency_key=None):
    if api_version != "1.0.0":
        raise ApiBoundaryError(
            "API_CONTRACT_VERSION_UNSUPPORTED", 400,
            "The requested API contract version is unsupported.", correlation_id,
        )
    if not _ID_PATTERN.fullmatch(correlation_id):
        raise ApiBoundaryError("INVALID_HEADER", 400, "A required header is invalid.", "invalid")
    if idempotency_key is not None and not _ID_PATTERN.fullmatch(idempotency_key):
        raise ApiBoundaryError("INVALID_HEADER", 400, "A required header is invalid.", correlation_id)
    if any(name in request.headers for name in _RAW_IDENTITY_HEADERS):
        raise ApiBoundaryError(
            "AUTHENTICATION_REQUIRED", 401, "Trusted authentication is required.", correlation_id,
        )


def _authenticate(request, runtime, correlation_id):
    _headers(request, correlation_id, request.headers.get("x-api-contract-version", ""))
    factory = getattr(runtime, "request_authentication_factory", None)
    if factory is not None or callable(getattr(runtime, "authenticate_request", None)) and not hasattr(runtime.authentication_context_provider, "context"):
        try:
            provider = runtime.authenticate_request(
                authorization_headers=tuple(request.headers.getlist("authorization")),
                correlation_id=correlation_id,
                request_id=request.headers.get("x-request-id", correlation_id),
            )
            context = provider.current_context()
        except RouterAuthenticationError as exc:
            if exc.code is RouterAuthenticationErrorCode.UNAVAILABLE:
                raise ApiBoundaryError(
                    "AUTHENTICATION_PROVIDER_UNAVAILABLE", 503,
                    "Authentication is temporarily unavailable.", correlation_id, True,
                ) from exc
            code = "AUTHENTICATION_REQUIRED" if exc.code is RouterAuthenticationErrorCode.MISSING else "INVALID_TOKEN"
            raise ApiBoundaryError(code, 401, "Trusted authentication is required.", correlation_id) from exc
        try:
            validated = validate_authentication_context(
                context, correlation_id=correlation_id,
                trusted_issuers=runtime.trusted_issuers,
                now=runtime.clock.now_audit_time(),
            )
        except AuthenticationContextError as exc:
            raise ApiBoundaryError(
                "INVALID_TOKEN", 401, "Trusted authentication is required.", correlation_id,
            ) from exc
        return validated, provider
    try:
        context = runtime.authentication_context_provider.current_context()
    except AuthenticationProviderUnavailable as exc:
        raise ApiBoundaryError(
            "AUTHENTICATION_PROVIDER_UNAVAILABLE", 503,
            "Authentication is temporarily unavailable.", correlation_id, True,
        ) from exc
    except Exception as exc:
        raise ApiBoundaryError(
            "AUTHENTICATION_REQUIRED", 401, "Trusted authentication is required.", correlation_id,
        ) from exc
    try:
        return validate_authentication_context(
            context, correlation_id=correlation_id,
            trusted_issuers=runtime.trusted_issuers,
            now=runtime.clock.now_audit_time(),
        ), None
    except AuthenticationContextError as exc:
        raise ApiBoundaryError(
            "AUTHENTICATION_REQUIRED", 401, "Trusted authentication is required.", correlation_id,
        ) from exc


def _scope_preflight(runtime, *, run_id, body, authentication, operation, original, previous):
    existing = runtime.ownership_inspector.load(run_id)
    if existing is None:
        return
    expected = (
        body.company_id, body.financial_period_id, authentication.tenant_id,
        operation.value, original.value, previous,
    )
    actual = (
        existing.company_id, existing.financial_period_id, existing.tenant_id,
        existing.operation_kind, existing.original_operation, existing.previous_run_id,
    )
    if actual != expected:
        raise ApiBoundaryError(
            "SCOPE_MISMATCH", 409, "The run identifier is bound to a different scope.",
            authentication.correlation_id,
        )
    if existing.initiating_subject_id is None:
        raise ApiBoundaryError(
            "RUN_SUBJECT_UNBOUND", 409, "The run has no replayable subject binding.",
            authentication.correlation_id,
        )
    if existing.initiating_subject_id != authentication.subject_id:
        raise ApiBoundaryError(
            "RUN_SUBJECT_MISMATCH", 409, "The run identifier is bound to a different subject.",
            authentication.correlation_id,
        )


def _authorize_source_resolution(runtime, *, body, authentication, operation, original, previous, run_id):
    scope = application_scope(
        request=body, authentication=authentication, operation_kind=operation,
        original_operation=original, previous_run_id=previous,
    )
    actor = audit_context(request=body, authentication=authentication, client_request_id=run_id)
    try:
        decision = runtime.authorization.authorize_read(scope, actor, include_payload=True)
    except Exception as exc:
        raise ApiBoundaryError(
            "AUTHORIZATION_PROVIDER_UNAVAILABLE", 503,
            "Authorization is temporarily unavailable.", authentication.correlation_id, True,
        ) from exc
    event = ApplicationEventType.AUTHORIZATION_GRANTED if decision.granted else ApplicationEventType.AUTHORIZATION_DENIED
    try:
        runtime.security_audit.record_required_event(SecurityAuditEventDTO(
            event, runtime.clock.now_audit_time(), authentication.correlation_id,
            scope, authentication.subject_id, run_id, decision.decision_code,
            safe_attributes=(("action", "INPUT_SOURCE_READ"),),
        ))
    except Exception as exc:
        raise ApiBoundaryError(
            "SECURITY_AUDIT_FAILED", 503,
            "Required security audit delivery failed.", authentication.correlation_id, True,
        ) from exc
    if not decision.granted:
        raise ApiBoundaryError(
            "UNAUTHORIZED", 403, "The analysis request is not authorized.",
            authentication.correlation_id,
        )


def _input_error(error, correlation_id):
    mapping = {
        InputResolutionCode.SOURCE_NOT_FOUND: (404, False, "The input source was not found."),
        InputResolutionCode.SOURCE_SCOPE_MISMATCH: (409, False, "The input source belongs to a different scope."),
        InputResolutionCode.SOURCE_UNAUTHORIZED: (403, False, "The input source is not authorized."),
        InputResolutionCode.SOURCE_STATUS_INVALID: (422, False, "The input source status is invalid."),
        InputResolutionCode.SOURCE_TYPE_INVALID: (422, False, "The input source type is invalid."),
        InputResolutionCode.SOURCE_CONTENT_UNAVAILABLE: (503, True, "The input source content is unavailable."),
        InputResolutionCode.SOURCE_RESOLVER_UNAVAILABLE: (503, True, "The input resolver is unavailable."),
        InputResolutionCode.SOURCE_CHECKSUM_MISMATCH: (500, False, "The input source integrity check failed."),
        InputResolutionCode.SOURCE_CANONICAL_DIGEST_MISMATCH: (500, False, "The input source integrity check failed."),
    }
    status, retryable, message = mapping[error.code]
    return ApiBoundaryError(error.code.value, status, message, correlation_id, retryable)


def _security_error(decision, correlation_id):
    code = decision.decision_code
    if code in {
        "AUTHZ_CONTEXT_MISSING", "AUTHZ_CONTEXT_INVALID", "AUTHZ_CONTEXT_STALE",
        "AUTHZ_CONTEXT_EXPIRED", "AUTHZ_CONTEXT_SUBJECT_MISMATCH",
    }:
        return ApiBoundaryError("INVALID_TOKEN", 401, "Trusted authentication is required.", correlation_id)
    if code in {
        "AUTHZ_PROVIDER_UNAVAILABLE", "AUTHZ_PROVIDER_TIMEOUT",
        "AUDIT_REQUIRED_BUT_UNAVAILABLE", "AUTHZ_AUDIT_INTEGRITY_FAILURE",
    }:
        return ApiBoundaryError(
            "AUTHORIZATION_PROVIDER_UNAVAILABLE", 503,
            "Authorization is temporarily unavailable.", correlation_id, True,
        )
    if code in {"AUTHZ_RESOURCE_NOT_FOUND", "AUTHZ_RESOURCE_STATE_INVALID"}:
        return ApiBoundaryError("NOT_FOUND", 404, "The analysis resource was not found.", correlation_id)
    return ApiBoundaryError("UNAUTHORIZED", 403, "The analysis request is not authorized.", correlation_id)


def _plan(*targets):
    order = {value: index for index, value in enumerate(AuthorizationCheckpoint)}
    return RequestAuthorizationPlan(tuple(sorted(targets, key=lambda item: order[item.checkpoint])))


def _cp_target(checkpoint, scope):
    return RequestAuthorizationTarget(
        checkpoint, PolicyScopeType.COMPANY_PERIOD,
        f"cp1:{scope.company_id}:{scope.financial_period_id}", scope.tenant_id,
        scope.company_id, scope.financial_period_id,
    )


def _run_target(checkpoint, run_id, tenant_id):
    return RequestAuthorizationTarget(
        checkpoint, PolicyScopeType.ANALYSIS_RUN, run_id, tenant_id,
    )


def _bind_security(runtime, authentication_provider, authorization_plan):
    if authentication_provider is None:
        return runtime.authorization
    return runtime.bind_request_security(
        authentication_provider=authentication_provider,
        authorization_plan=authorization_plan,
    )


def _require_decision(decision, correlation_id):
    if not decision.granted:
        raise _security_error(decision, correlation_id)
    return decision


def _json(model, status, correlation_id, *, retry_after=None):
    headers = {
        "X-Correlation-ID": correlation_id, "X-API-Contract-Version": "1.0.0",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    }
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=headers)


def boundary_error_response(error: ApiBoundaryError):
    model = ApiOutcomeResponseV1[dict](
        success=False, data=None, error=ApiErrorV1(**boundary_error_dict(error)),
        warnings=(), correlation_id=error.correlation_id,
    )
    response = _json(model, error.status_code, error.correlation_id, retry_after=error.retry_after)
    if error.status_code == 401:
        response.headers["WWW-Authenticate"] = (
            'Bearer realm="api"' if error.code == "AUTHENTICATION_REQUIRED"
            else 'Bearer realm="api", error="invalid_token"'
        )
    return response


def _json_outcome(outcome, *, data_model, success_status=200):
    if not outcome.success:
        model = ApiOutcomeResponseV1[data_model](
            success=False, data=None, error=ApiErrorV1(**public_error_dict(outcome.error)),
            warnings=tuple(ApiWarningV1(**to_wire(item)) for item in outcome.warnings),
            correlation_id=outcome.correlation_id,
        )
        return _json(model, status_for_application_error(outcome.error.code), outcome.correlation_id)
    try:
        data = data_model(**to_wire(outcome.value))
        model = ApiOutcomeResponseV1[data_model](
            success=True, data=data, error=None,
            warnings=tuple(ApiWarningV1(**to_wire(item)) for item in outcome.warnings),
            correlation_id=outcome.correlation_id,
        )
        status = success_status(outcome.value) if callable(success_status) else success_status
        return _json(model, status, outcome.correlation_id)
    except Exception:
        run_id = getattr(outcome.value, "run_id", None)
        safe = {
            "run_id": run_id, "correlation_id": outcome.correlation_id,
            "persisted": True,
            "recovery_endpoint": f"/api/v1/analysis-runs/{run_id}/result",
            "recovery_reference": run_id,
        }
        error = ApiErrorV1(
            code="RESPONSE_SERIALIZATION_FAILED", category="internal",
            message="The persisted result could not be serialized.", retryable=True,
            correlation_id=outcome.correlation_id, safe_metadata=safe,
        )
        model = ApiOutcomeResponseV1[data_model](
            success=False, data=None, error=error, warnings=(),
            correlation_id=outcome.correlation_id,
        )
        return _json(model, 500, outcome.correlation_id)


def _execute_write(http_request, body, run_id, correlation_id, operation, original, previous, db, runtime):
    _headers(http_request, correlation_id, http_request.headers.get("x-api-contract-version", ""), run_id)
    authentication, authentication_provider = _authenticate(http_request, runtime, correlation_id)
    requested_scope = application_scope(
        request=body, authentication=authentication, operation_kind=operation,
        original_operation=original, previous_run_id=previous,
    )
    targets = [
        _cp_target({
            ApplicationOperationKind.START: AuthorizationCheckpoint.START,
            ApplicationOperationKind.RESUME: AuthorizationCheckpoint.RESUME,
            ApplicationOperationKind.RETRY: AuthorizationCheckpoint.RETRY,
        }[operation], requested_scope),
        _cp_target({
            ApplicationOperationKind.START: AuthorizationCheckpoint.PRE_PERSIST_START,
            ApplicationOperationKind.RESUME: AuthorizationCheckpoint.PRE_PERSIST_RESUME,
            ApplicationOperationKind.RETRY: AuthorizationCheckpoint.PRE_PERSIST_RETRY,
        }[operation], requested_scope),
    ]
    if previous is not None:
        targets.extend((
            _run_target(AuthorizationCheckpoint.RESUME_SOURCE, previous, authentication.tenant_id),
            _run_target(AuthorizationCheckpoint.PRE_PERSIST_RESUME_SOURCE, previous, authentication.tenant_id),
        ))
    security = _bind_security(runtime, authentication_provider, _plan(*targets))
    actor_id = getattr(security, "actor_reference", authentication.subject_id)
    actor = audit_context(
        request=body, authentication=authentication,
        client_request_id=run_id, actor_id=actor_id,
    )
    _scope_preflight(
        runtime, run_id=run_id, body=body, authentication=authentication,
        operation=operation, original=original, previous=previous,
    )
    lease = runtime.admission.try_acquire(
        tenant_id=authentication.tenant_id, subject_id=authentication.subject_id,
        run_id=run_id, acquired_at=runtime.clock.now_audit_time(),
    )
    if lease is None:
        raise ApiBoundaryError(
            "ADMISSION_LIMIT_REACHED", 429, "Analysis capacity is temporarily saturated.",
            correlation_id, True, retry_after=runtime.admission.retry_after_seconds,
        )
    try:
        initial = {
            ApplicationOperationKind.START: security.authorize_start,
            ApplicationOperationKind.RESUME: security.authorize_resume,
            ApplicationOperationKind.RETRY: security.authorize_retry,
        }[operation](requested_scope, actor)
        _require_decision(initial, correlation_id)
        if previous is not None:
            _require_decision(
                security.authorize_resume_source(previous, requested_scope, actor),
                correlation_id,
            )
        if authentication_provider is None:
            _authorize_source_resolution(
                runtime, body=body, authentication=authentication,
                operation=operation, original=original, previous=previous, run_id=run_id,
            )
        try:
            inputs = resolve_inputs(
                request=body, authentication=authentication,
                document_resolver=runtime.document_inputs,
                result_resolver=runtime.result_inputs,
            )
        except InputResolutionError as exc:
            raise _input_error(exc, correlation_id) from exc
        try:
            command = build_execution_command(
                request=body, run_id=run_id, correlation_id=correlation_id,
                authentication=authentication, operation_kind=operation,
                original_operation=original, previous_run_id=previous,
                resolved_inputs=inputs, actor_id=actor_id,
            )
        except (TypeError, ValueError) as exc:
            raise ApiBoundaryError(
                "INVALID_COMMAND", 422, "The analysis command is invalid.", correlation_id,
            ) from exc
        service = (
            runtime.application_service(session=db, subject_id=authentication.subject_id)
            if authentication_provider is None else
            runtime.application_service(
                session=db, subject_id=authentication.subject_id,
                authorization=security,
            )
        )
        method = {
            ApplicationOperationKind.START: service.start,
            ApplicationOperationKind.RESUME: service.resume,
            ApplicationOperationKind.RETRY: service.retry,
        }[operation]
        try:
            outcome = method(command)
        except ApiBoundaryError:
            raise
        except Exception as exc:
            raise ApiBoundaryError(
                "INTERNAL_INVARIANT_BREACH", 500,
                "The analysis request could not be completed.", correlation_id,
            ) from exc
        return _json_outcome(
            outcome, data_model=AnalysisCommandResponseV1,
            success_status=lambda value: 200 if value.idempotent_replay else 201,
        )
    finally:
        runtime.admission.release(lease)


@router.post("", operation_id="start_analysis_run_v1")
def start_analysis_run(request: Request, body: StartAnalysisRequestV1, idempotency_key: str = Header(alias="Idempotency-Key"), correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    return _execute_write(request, body, idempotency_key, correlation_id, ApplicationOperationKind.START, ApplicationOriginalOperation.START, None, db, runtime)


@router.post("/{previous_run_id}/resume", operation_id="resume_analysis_run_v1")
def resume_analysis_run(previous_run_id: str, request: Request, body: ResumeAnalysisRequestV1, idempotency_key: str = Header(alias="Idempotency-Key"), correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    if previous_run_id == idempotency_key:
        raise ApiBoundaryError("INVALID_COMMAND", 422, "Source and target run identifiers must differ.", correlation_id)
    return _execute_write(request, body, idempotency_key, correlation_id, ApplicationOperationKind.RESUME, ApplicationOriginalOperation.RESUME, previous_run_id, db, runtime)


@router.post("/{previous_run_id}/retry", operation_id="retry_analysis_run_v1")
def retry_analysis_run(previous_run_id: str, request: Request, body: RetryAnalysisRequestV1, idempotency_key: str = Header(alias="Idempotency-Key"), correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    if previous_run_id == idempotency_key:
        raise ApiBoundaryError("INVALID_COMMAND", 422, "Source and target run identifiers must differ.", correlation_id)
    return _execute_write(request, body, idempotency_key, correlation_id, ApplicationOperationKind.RETRY, body.original_operation, previous_run_id, db, runtime)


def _read_scope(runtime, *, run_id, company_id, period_id, authentication, correlation_id):
    owner = runtime.ownership_inspector.load(run_id)
    if owner is None or owner.company_id != company_id or owner.financial_period_id != period_id or owner.tenant_id != authentication.tenant_id:
        raise ApiBoundaryError("NOT_FOUND", 404, "The analysis resource was not found.", correlation_id)
    return ApplicationScopeDTO(
        owner.company_id, owner.financial_period_id, owner.tenant_id,
        ApplicationOperationKind(owner.operation_kind),
        ApplicationOriginalOperation(owner.original_operation), owner.previous_run_id,
    )


@router.post("/{run_id}/cancel", operation_id="cancel_analysis_run_v1")
def cancel_analysis_run(run_id: str, request: Request, company_id: str = Query(), financial_period_id: str = Query(), correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    authentication, authentication_provider = _authenticate(request, runtime, correlation_id)
    try:
        company_uuid, period_uuid = uuid.UUID(company_id), uuid.UUID(financial_period_id)
    except ValueError as exc:
        raise ApiBoundaryError("INVALID_QUERY", 422, "The analysis query is invalid.", correlation_id) from exc
    claimed_scope = ApplicationScopeDTO(company_uuid, period_uuid, authentication.tenant_id, ApplicationOperationKind.START, ApplicationOriginalOperation.START)
    security = _bind_security(runtime, authentication_provider, _plan(
        _run_target(AuthorizationCheckpoint.CANCEL, run_id, authentication.tenant_id)
    ))
    actor_id = getattr(security, "actor_reference", authentication.subject_id)
    claimed_command = build_cancel_command(run_id=run_id, correlation_id=correlation_id, generated_at=runtime.clock.now_audit_time(), scope=claimed_scope, authentication=authentication, actor_id=actor_id)
    decision = _require_decision(security.authorize_cancel(claimed_scope, claimed_command.audit_context), correlation_id)
    scope = _read_scope(runtime, run_id=run_id, company_id=company_uuid, period_id=period_uuid, authentication=authentication, correlation_id=correlation_id)
    command = build_cancel_command(run_id=run_id, correlation_id=correlation_id, generated_at=runtime.clock.now_audit_time(), scope=scope, authentication=authentication, actor_id=actor_id)
    if authentication_provider is not None:
        security.cache_cancel_guard(scope, command.audit_context, decision)
    try:
        service = (
            runtime.application_service(session=db, subject_id=authentication.subject_id)
            if authentication_provider is None else
            runtime.application_service(session=db, subject_id=authentication.subject_id, authorization=security)
        )
        outcome = service.cancel(command)
    except Exception as exc:
        raise ApiBoundaryError(
            "INTERNAL_INVARIANT_BREACH", 500,
            "The cancellation request could not be completed.", correlation_id,
        ) from exc
    return _json_outcome(outcome, data_model=CancellationResponseV1)


def _run_read(kind, *, run_id, request, company_id, period_id, include_payload, engine_code, correlation_id, db, runtime):
    authentication, authentication_provider = _authenticate(request, runtime, correlation_id)
    try:
        company_uuid, period_uuid = uuid.UUID(str(company_id)), uuid.UUID(str(period_id))
    except ValueError as exc:
        raise ApiBoundaryError("INVALID_QUERY", 422, "The analysis query is invalid.", correlation_id) from exc
    claimed_scope = ApplicationScopeDTO(company_uuid, period_uuid, authentication.tenant_id, ApplicationOperationKind.START, ApplicationOriginalOperation.START)
    security = _bind_security(runtime, authentication_provider, _plan(
        _run_target(AuthorizationCheckpoint.READ, run_id, authentication.tenant_id)
    ))
    actor_id = getattr(security, "actor_reference", authentication.subject_id)
    claimed_query = build_run_query(kind=kind, run_id=run_id, correlation_id=correlation_id, generated_at=runtime.clock.now_audit_time(), scope=claimed_scope, authentication=authentication, include_payload=include_payload, engine_code=engine_code, actor_id=actor_id)
    generic = _require_decision(security.authorize_read(claimed_scope, claimed_query.audit_context, include_payload=include_payload), correlation_id)
    endpoint_action = {
        "status": "analysis.status.read",
        "result": "analysis.result.payload.read" if include_payload else "analysis.result.read",
        "execution": "analysis.execution.payload.read" if include_payload else "analysis.execution.read",
    }[kind]
    endpoint = _require_decision(security.authorize_endpoint(endpoint_action, claimed_scope, claimed_query.audit_context), correlation_id) if authentication_provider is not None else generic
    scope = _read_scope(runtime, run_id=run_id, company_id=company_uuid, period_id=period_uuid, authentication=authentication, correlation_id=correlation_id)
    query = build_run_query(kind=kind, run_id=run_id, correlation_id=correlation_id, generated_at=runtime.clock.now_audit_time(), scope=scope, authentication=authentication, include_payload=include_payload, engine_code=engine_code, actor_id=actor_id)
    if authentication_provider is not None:
        security.cache_read_guard(scope, query.audit_context, endpoint)
    facade = runtime.read_facade(session=db) if authentication_provider is None else runtime.read_facade(session=db, authorization=security)
    outcome = {"status": facade.get_status, "result": facade.get_result, "execution": facade.get_execution_detail}[kind](query)
    model = {"status": AnalysisRunStatusResponseV1, "result": AnalysisResultResponseV1, "execution": AnalysisExecutionResponseV1}[kind]
    return _json_outcome(outcome, data_model=model)


@router.get("/{run_id}/status", operation_id="get_analysis_run_status_v1")
def get_analysis_run_status(run_id: str, request: Request, company_id: str, financial_period_id: str, correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    return _run_read("status", run_id=run_id, request=request, company_id=company_id, period_id=financial_period_id, include_payload=False, engine_code=None, correlation_id=correlation_id, db=db, runtime=runtime)


@router.get("/{run_id}/result", operation_id="get_analysis_run_result_v1")
def get_analysis_run_result(run_id: str, request: Request, company_id: str, financial_period_id: str, include_payloads: bool = False, correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    return _run_read("result", run_id=run_id, request=request, company_id=company_id, period_id=financial_period_id, include_payload=include_payloads, engine_code=None, correlation_id=correlation_id, db=db, runtime=runtime)


@router.get("/{run_id}/executions/{engine_code}", operation_id="get_analysis_execution_v1")
def get_analysis_execution(run_id: str, engine_code: ApplicationEngineCode, request: Request, company_id: str, financial_period_id: str, include_payload: bool = False, correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    return _run_read("execution", run_id=run_id, request=request, company_id=company_id, period_id=financial_period_id, include_payload=include_payload, engine_code=engine_code, correlation_id=correlation_id, db=db, runtime=runtime)


@router.get("", operation_id="list_analysis_run_history_v1")
def list_analysis_run_history(request: Request, company_id: str, financial_period_id: str, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), correlation_id: str = Header(alias="X-Correlation-ID"), db: Session = Depends(get_db), runtime=Depends(require_analysis_runtime)):
    authentication, authentication_provider = _authenticate(request, runtime, correlation_id)
    try:
        company_uuid, period_uuid = uuid.UUID(company_id), uuid.UUID(financial_period_id)
    except ValueError as exc:
        raise ApiBoundaryError("INVALID_QUERY", 422, "The analysis query is invalid.", correlation_id) from exc
    internal_cursor = None
    if cursor:
        try:
            internal_cursor = runtime.cursor_codec.decode(cursor, tenant_id=authentication.tenant_id, company_id=company_uuid, financial_period_id=period_uuid, now=runtime.clock.now_audit_time())
        except InvalidCursor as exc:
            raise ApiBoundaryError("INVALID_CURSOR", 422, "The pagination cursor is invalid.", correlation_id) from exc
    scope = ApplicationScopeDTO(company_uuid, period_uuid, authentication.tenant_id, ApplicationOperationKind.START, ApplicationOriginalOperation.START)
    security = _bind_security(runtime, authentication_provider, _plan(
        _cp_target(AuthorizationCheckpoint.READ, scope)
    ))
    actor_id = getattr(security, "actor_reference", authentication.subject_id)
    query = build_history_query(correlation_id=correlation_id, generated_at=runtime.clock.now_audit_time(), scope=scope, authentication=authentication, cursor=internal_cursor, limit=limit, actor_id=actor_id)
    if authentication_provider is not None:
        endpoint = _require_decision(security.authorize_endpoint("analysis.history.read", scope, query.audit_context), correlation_id)
        security.cache_read_guard(scope, query.audit_context, endpoint)
    outcome = (runtime.read_facade(session=db) if authentication_provider is None else runtime.read_facade(session=db, authorization=security)).list_history(query)
    if outcome.success and outcome.value.next_cursor:
        encoded = runtime.cursor_codec.encode(internal_cursor=outcome.value.next_cursor, tenant_id=authentication.tenant_id, company_id=company_uuid, financial_period_id=period_uuid, now=runtime.clock.now_audit_time())
        outcome = dataclasses.replace(outcome, value=dataclasses.replace(outcome.value, next_cursor=encoded))
    return _json_outcome(outcome, data_model=AnalysisHistoryPageResponseV1)
