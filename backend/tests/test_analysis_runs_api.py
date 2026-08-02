from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest

from app.analysis_application.contracts import (
    AnalysisCommandResultDTO, AnalysisErrorCode, AnalysisErrorDTO,
    AnalysisExecutionDTO, AnalysisHistoryPageDTO, AnalysisResultDTO,
    AnalysisRunStatusDTO, AnalysisRunSummaryDTO, ApplicationErrorCategory,
    ApplicationExecutionStatus, ApplicationOutcome, ApplicationStatus,
    CancellationResultDTO, CancellationStatus,
)
from app.analysis_application.ports import AuthorizationDecision, SecurityAuditReceiptDTO
from app.api.v1.analysis_runs import require_analysis_runtime
from app.integrations.analysis_http.admission import ProcessLocalAnalysisAdmissionControl
from app.integrations.analysis_http.contracts import (
    ApiRuntimeProfile, AuthenticationContext, AuthenticationStrength,
    RunOwnershipView,
)
from app.integrations.analysis_http.cursor import CursorKeyring, HmacCursorCodec
from app.integrations.analysis_http.security import StaticAuthenticationContextProvider
from app.integrations.analysis_http.router_security import (
    RouterAuthenticationError, RouterAuthenticationErrorCode,
)
from app.main import app


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
COMPANY_ID = uuid.uuid4()
PERIOD_ID = uuid.uuid4()


class Clock:
    def now_audit_time(self): return NOW
    def resolve_business_time(self, value): return value or NOW


class Authorization:
    def __init__(self, granted=True): self.granted = granted
    def _decision(self): return AuthorizationDecision(self.granted, False, "grant" if self.granted else "deny", "ref", NOW)
    def authorize_start(self, scope, actor): return self._decision()
    def authorize_resume(self, scope, actor): return self._decision()
    def authorize_resume_source(self, source_run_id, target_scope, actor): return self._decision()
    def authorize_read(self, scope, actor, *, include_payload): return self._decision()
    def authorize_cancel(self, scope, actor): return self._decision()
    def authorize_retry(self, scope, actor): return self._decision()


class Audit:
    def record_required_event(self, event): return SecurityAuditReceiptDTO("receipt", event.event_type, NOW, "a" * 64)


class Resolver:
    def resolve_document_input(self, **kwargs): raise AssertionError("No document input expected")
    def resolve_trial_balance_input(self, **kwargs): raise AssertionError("No trial-balance input expected")


class Inspector:
    def __init__(self, view=None): self.view = view
    def load(self, run_id): return self.view


class Service:
    def __init__(self): self.commands = []
    def start(self, command): return self._command(command)
    def resume(self, command): return self._command(command)
    def retry(self, command): return self._command(command)
    def _command(self, command):
        self.commands.append(command)
        execution = AnalysisExecutionDTO(
            command.requested_outputs[-1], ApplicationExecutionStatus.COMPLETED,
            None, "1", "1", "a" * 64, "1",
        )
        value = AnalysisCommandResultDTO(
            command.run_id, ApplicationStatus.FULLY_COMPLETED, "b" * 64, "c" * 64,
            command.scope, (execution,), NOW, False, command.run_id,
        )
        return ApplicationOutcome(True, value, None, (), command.correlation_id)
    def cancel(self, command):
        return ApplicationOutcome(
            True, CancellationResultDTO(command.run_id, CancellationStatus.NOT_ACTIVE, command.scope, NOW),
            None, (), command.correlation_id,
        )


class ReadFacade:
    def get_status(self, query):
        return ApplicationOutcome(True, AnalysisRunStatusDTO(
            query.run_id, ApplicationStatus.FULLY_COMPLETED, query.scope, NOW, (), True,
        ), None, (), query.correlation_id)
    def get_result(self, query):
        return ApplicationOutcome(True, AnalysisResultDTO(
            query.run_id, ApplicationStatus.FULLY_COMPLETED, query.scope, "b" * 64,
            (), (), (), "1", "1", "1", NOW,
        ), None, (), query.correlation_id)
    def get_execution_detail(self, query):
        return ApplicationOutcome(True, AnalysisExecutionDTO(
            query.engine_code, ApplicationExecutionStatus.COMPLETED, None,
            "1", "1", "a" * 64, "1",
        ), None, (), query.correlation_id)
    def list_history(self, query):
        item = AnalysisRunSummaryDTO(
            "history-run", ApplicationStatus.FULLY_COMPLETED, query.scope,
            (), NOW, None,
        )
        return ApplicationOutcome(True, AnalysisHistoryPageDTO((item,), None), None, (), query.correlation_id)


class Runtime:
    profile = ApiRuntimeProfile.TEST
    trusted_issuers = frozenset({"issuer"})
    def __init__(self, *, subject="subject", authorization=True, inspector=None, admission=None, issued_at=None):
        context = AuthenticationContext(
            subject, "tenant", "test", AuthenticationStrength.STRONG,
            issued_at or NOW - timedelta(minutes=1), NOW + timedelta(minutes=5),
            "corr", "1", "issuer", "auth-ref",
        )
        self.authentication_context_provider = StaticAuthenticationContextProvider(context, ApiRuntimeProfile.TEST)
        self.authorization = Authorization(authorization)
        self.security_audit = Audit()
        self.clock = Clock()
        self.document_inputs = Resolver()
        self.result_inputs = Resolver()
        self.admission = admission or ProcessLocalAnalysisAdmissionControl(global_limit=2, tenant_limit=2, subject_limit=2, retry_after_seconds=5)
        self.ownership_inspector = inspector or Inspector()
        self.cursor_codec = HmacCursorCodec(CursorKeyring("active", {"active": b"a" * 32}))
        self.service = Service()
        self.facade = ReadFacade()
    def application_service(self, *, session, subject_id): return self.service
    def read_facade(self, *, session): return self.facade


def _body():
    base = {
        "generated_at": NOW.isoformat(), "company_id": str(COMPANY_ID),
        "financial_period_id": str(PERIOD_ID), "purpose": "analysis",
        "requested_outputs": ["benchmark"], "inputs": {}, "run_options": {},
        "source_intents": [
            {"engine_code": "fs_balance_sheet", "company_id": str(COMPANY_ID), "financial_period_id": str(PERIOD_ID), "source_bindings": [], "requested_source_mode": "multi_source_derived", "allow_existing_canonical_owner": False},
            {"engine_code": "fs_income_statement", "company_id": str(COMPANY_ID), "financial_period_id": str(PERIOD_ID), "source_bindings": [], "requested_source_mode": "multi_source_derived", "allow_existing_canonical_owner": False},
            {"engine_code": "ratio", "company_id": str(COMPANY_ID), "financial_period_id": str(PERIOD_ID), "source_bindings": [
                {"role": "primary_analysis", "source_engine_code": "fs_balance_sheet"},
                {"role": "supporting_analysis", "source_engine_code": "fs_income_statement"},
            ], "requested_source_mode": "multi_source_derived", "allow_existing_canonical_owner": False},
        ],
    }
    return base


def _headers(**extra):
    values = {"Idempotency-Key": "run-1", "X-Correlation-ID": "corr", "X-API-Contract-Version": "1.0.0"}
    values.update(extra)
    return values


@pytest.fixture(autouse=True)
def runtime_override():
    runtime = Runtime()
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    yield runtime
    app.dependency_overrides.pop(require_analysis_runtime, None)


def test_start_maps_exact_command_and_returns_201(client, runtime_override):
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers())
    assert response.status_code == 201, response.text
    assert response.json()["data"]["run_id"] == "run-1"
    command = runtime_override.service.commands[0]
    assert command.scope.tenant_id == "tenant"
    assert command.audit_context.actor_id == "subject"
    assert command.authorization_context_reference == "auth-ref"


def test_raw_identity_headers_and_authorization_deny_are_fail_closed(client, runtime_override):
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers(**{"X-User-Id": "attacker"}))
    assert response.status_code == 401
    denied = Runtime(authorization=False)
    app.dependency_overrides[require_analysis_runtime] = lambda: denied
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers())
    assert response.status_code == 403
    assert denied.service.commands == []


def test_expired_authentication_and_saturation_are_exact(client):
    expired = Runtime(issued_at=NOW - timedelta(minutes=16))
    app.dependency_overrides[require_analysis_runtime] = lambda: expired
    assert client.post("/api/v1/analysis-runs", json=_body(), headers=_headers()).status_code == 401
    admission = ProcessLocalAnalysisAdmissionControl(global_limit=1, tenant_limit=1, subject_limit=1, retry_after_seconds=5)
    admission.try_acquire(tenant_id="tenant", subject_id="subject", run_id="other", acquired_at=NOW)
    saturated = Runtime(admission=admission)
    app.dependency_overrides[require_analysis_runtime] = lambda: saturated
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers())
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "5"


def test_admission_lease_is_released_and_raw_service_error_is_redacted(client):
    admission = ProcessLocalAnalysisAdmissionControl(
        global_limit=1, tenant_limit=1, subject_limit=1, retry_after_seconds=5,
    )
    runtime = Runtime(admission=admission)

    class ExplodingService(Service):
        def start(self, command):
            raise RuntimeError("secret upstream detail")

    runtime.service = ExplodingService()
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    failed = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers())
    assert failed.status_code == 500
    assert "secret upstream detail" not in failed.text
    runtime.service = Service()
    retried = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers())
    assert retried.status_code == 201


def test_post_persistence_projection_failure_returns_safe_recovery_metadata(client):
    runtime = Runtime()

    class ProjectionFailureService(Service):
        def start(self, command):
            value = SimpleNamespace(run_id=command.run_id)
            return ApplicationOutcome(True, value, None, (), command.correlation_id)

    runtime.service = ProjectionFailureService()
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers())
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "RESPONSE_SERIALIZATION_FAILED"
    assert error["safe_metadata"] == {
        "run_id": "run-1", "correlation_id": "corr", "persisted": True,
        "recovery_endpoint": "/api/v1/analysis-runs/run-1/result",
        "recovery_reference": "run-1",
    }


def test_same_scope_different_subject_replay_is_409(client):
    view = RunOwnershipView(
        "run-1", COMPANY_ID, PERIOD_ID, "tenant", "START", "START", None,
        "other-subject", "FINALIZED",
    )
    runtime = Runtime(inspector=Inspector(view))
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_headers())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_SUBJECT_MISMATCH"


def test_status_result_execution_history_and_cancel_routes(client):
    view = RunOwnershipView(
        "run-1", COMPANY_ID, PERIOD_ID, "tenant", "START", "START", None,
        "subject", "FINALIZED",
    )
    runtime = Runtime(inspector=Inspector(view))
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    base = f"?company_id={COMPANY_ID}&financial_period_id={PERIOD_ID}"
    read_headers = {"X-Correlation-ID": "corr", "X-API-Contract-Version": "1.0.0"}
    assert client.get(f"/api/v1/analysis-runs/run-1/status{base}", headers=read_headers).status_code == 200
    assert client.get(f"/api/v1/analysis-runs/run-1/result{base}", headers=read_headers).status_code == 200
    assert client.get(f"/api/v1/analysis-runs/run-1/executions/benchmark{base}", headers=read_headers).status_code == 200
    assert client.get(f"/api/v1/analysis-runs{base}", headers=read_headers).status_code == 200
    assert client.post(f"/api/v1/analysis-runs/run-1/cancel{base}", headers=read_headers).status_code == 200


def test_openapi_has_eight_stable_operation_ids():
    operation_ids = {
        operation["operationId"]
        for path in app.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and operation.get("tags") == ["analysis-runs"]
    }
    assert operation_ids == {
        "start_analysis_run_v1", "resume_analysis_run_v1", "retry_analysis_run_v1",
        "cancel_analysis_run_v1", "get_analysis_run_status_v1",
        "get_analysis_run_result_v1", "get_analysis_execution_v1",
        "list_analysis_run_history_v1",
    }


class BoundSecurity(Authorization):
    actor_reference = "srh1:k1:" + "a" * 64
    requires_same_revalidation_instance = True

    def __init__(self, denied_code=None):
        super().__init__(True)
        self.denied_code = denied_code
        self.actions = []

    def _for(self, action):
        self.actions.append(action)
        granted = self.denied_code is None
        return AuthorizationDecision(granted, False, self.denied_code or "AUTHZ_ALLOWED", "ref", NOW)

    def authorize_start(self, scope, actor): return self._for("analysis.start")
    def authorize_resume(self, scope, actor): return self._for("analysis.resume")
    def authorize_resume_source(self, source_run_id, target_scope, actor): return self._for("analysis.resume_source")
    def authorize_retry(self, scope, actor): return self._for("analysis.retry")
    def authorize_cancel(self, scope, actor): return self._for("analysis.cancel")
    def authorize_read(self, scope, actor, *, include_payload): return self._for("analysis.payload.read" if include_payload else "analysis.read")
    def authorize_endpoint(self, action, scope, actor): return self._for(action)
    def cache_read_guard(self, scope, actor, decision): pass
    def cache_cancel_guard(self, scope, actor, decision): pass
    def revalidate_start(self, scope, actor): return self._for("revalidate.start")
    def revalidate_resume(self, scope, actor): return self._for("revalidate.resume")
    def revalidate_retry(self, scope, actor): return self._for("revalidate.retry")
    def revalidate_resume_source(self, source, scope, actor): return self._for("revalidate.source")


class SecureRuntime(Runtime):
    request_authentication_factory = object()

    def __init__(self, *, denied_code=None, authentication_error=None, **kwargs):
        super().__init__(**kwargs)
        self.bound = BoundSecurity(denied_code)
        self.authentication_error = authentication_error

    def authenticate_request(self, *, authorization_headers, correlation_id, request_id):
        if self.authentication_error is not None:
            raise RouterAuthenticationError(self.authentication_error)
        if not authorization_headers:
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.MISSING)
        if authorization_headers != ("Bearer valid-token",):
            raise RouterAuthenticationError(RouterAuthenticationErrorCode.INVALID)
        return self.authentication_context_provider

    def bind_request_security(self, **kwargs): return self.bound
    def application_service(self, *, session, subject_id, authorization=None): return self.service
    def read_facade(self, *, session, authorization=None): return self.facade


def _bearer_headers(**extra):
    return _headers(Authorization="Bearer valid-token", **extra)


def test_step13_missing_malformed_and_unavailable_authentication_are_exact(client):
    for error, expected, header in (
        (None, 401, None),
        (None, 401, "Basic invalid"),
        (RouterAuthenticationErrorCode.UNAVAILABLE, 503, "Bearer valid-token"),
    ):
        runtime = SecureRuntime(authentication_error=error)
        app.dependency_overrides[require_analysis_runtime] = lambda: runtime
        headers = _headers()
        if header is not None: headers["Authorization"] = header
        response = client.post("/api/v1/analysis-runs", json=_body(), headers=headers)
        assert response.status_code == expected
        if expected == 401:
            assert response.headers["WWW-Authenticate"].startswith("Bearer realm=")
        assert runtime.bound.actions == []
    stale = SecureRuntime(issued_at=NOW - timedelta(minutes=16))
    app.dependency_overrides[require_analysis_runtime] = lambda: stale
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_bearer_headers())
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="api", error="invalid_token"'
    assert stale.bound.actions == []


@pytest.mark.parametrize(
    ("decision_code", "status"),
    (
        ("AUTHZ_PERMISSION_NOT_GRANTED", 403),
        ("AUTHZ_STRENGTH_INSUFFICIENT", 403),
        ("AUTHZ_PRINCIPAL_KIND_NOT_ALLOWED", 403),
        ("AUTHZ_RESOURCE_NOT_FOUND", 404),
        ("AUTHZ_PROVIDER_TIMEOUT", 503),
        ("AUDIT_REQUIRED_BUT_UNAVAILABLE", 503),
    ),
)
def test_step13_authorization_http_mapping_is_closed(client, decision_code, status):
    runtime = SecureRuntime(denied_code=decision_code)
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    response = client.post("/api/v1/analysis-runs", json=_body(), headers=_bearer_headers())
    assert response.status_code == status
    assert runtime.service.commands == []
    assert decision_code not in response.text


def test_step13_eight_endpoint_action_matrix(client):
    view = RunOwnershipView(
        "run-1", COMPANY_ID, PERIOD_ID, "tenant", "START", "START", None,
        "subject", "FINALIZED",
    )
    class MatrixInspector:
        def load(self, run_id): return view if run_id == "run-1" else None
    runtime = SecureRuntime(inspector=MatrixInspector())
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    base = f"?company_id={COMPANY_ID}&financial_period_id={PERIOD_ID}"
    read = {"Authorization": "Bearer valid-token", "X-Correlation-ID": "corr", "X-API-Contract-Version": "1.0.0"}
    assert client.post("/api/v1/analysis-runs", json=_body(), headers=_bearer_headers()).status_code == 201
    resume = dict(_body())
    assert client.post("/api/v1/analysis-runs/source-run/resume", json=resume, headers=_bearer_headers(**{"Idempotency-Key": "run-2"})).status_code == 201
    retry = dict(_body()); retry["original_operation"] = "START"
    assert client.post("/api/v1/analysis-runs/source-run/retry", json=retry, headers=_bearer_headers(**{"Idempotency-Key": "run-3"})).status_code == 201
    assert client.post(f"/api/v1/analysis-runs/run-1/cancel{base}", headers=read).status_code == 200
    assert client.get(f"/api/v1/analysis-runs/run-1/status{base}", headers=read).status_code == 200
    assert client.get(f"/api/v1/analysis-runs/run-1/result{base}", headers=read).status_code == 200
    assert client.get(f"/api/v1/analysis-runs/run-1/executions/benchmark{base}", headers=read).status_code == 200
    assert client.get(f"/api/v1/analysis-runs{base}", headers=read).status_code == 200
    assert {
        "analysis.start", "analysis.resume", "analysis.retry", "analysis.resume_source",
        "analysis.cancel", "analysis.status.read", "analysis.result.read",
        "analysis.execution.read", "analysis.history.read",
    } <= set(runtime.bound.actions)


def test_step13_raw_identity_header_precedes_bearer_and_admission(client):
    runtime = SecureRuntime()
    app.dependency_overrides[require_analysis_runtime] = lambda: runtime
    response = client.post(
        "/api/v1/analysis-runs", json=_body(),
        headers=_bearer_headers(**{"X-Tenant-Id": "attacker"}),
    )
    assert response.status_code == 401
    assert runtime.bound.actions == []


def test_step13_openapi_declares_bearer_without_raw_identity_headers():
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    operation = schema["paths"]["/api/v1/analysis-runs"]["post"]
    assert operation["security"] == [{"BearerAuth": []}]
    rendered = str(operation).lower()
    assert "x-user-id" not in rendered and "x-tenant-id" not in rendered
