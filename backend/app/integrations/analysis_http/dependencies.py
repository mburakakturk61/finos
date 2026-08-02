"""Request-safe composition boundary for the analysis API."""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis_application.active import LocalActiveExecutionRegistry
from app.analysis_application.adapters.persistence import SqlAlchemyRunPersistenceAdapter
from app.analysis_application.adapters.read import SqlAlchemyAnalysisReadAdapter
from app.analysis_application.adapters.scope_claim import SqlAlchemyRunScopeClaimRepository
from app.analysis_application.service import AnalysisApplicationService
from app.integrations.analysis_http.contracts import ApiRuntimeProfile
from app.integrations.analysis_http.read_facade import ApiAnalysisReadFacade
from app.integrations.analysis_http.runtime import ProductionIntegrationBindings, validate_runtime_bindings


@dataclass(frozen=True)
class AnalysisApiRuntime:
    profile: ApiRuntimeProfile
    trusted_issuers: frozenset[str]
    authentication_context_provider: object
    authorization: object
    security_audit: object
    observability: object
    clock: object
    document_inputs: object
    result_inputs: object
    admission: object
    cursor_codec: object
    ownership_inspector: object
    session_factory: object
    blob_store: object
    active_executions: object
    request_authentication_factory: object | None = None
    request_security_factory: object | None = None
    legacy_security: object | None = None

    def validate(self) -> None:
        validate_runtime_bindings(self.profile, ProductionIntegrationBindings(
            self.authentication_context_provider, self.authorization,
            self.security_audit, self.observability, self.clock,
            self.document_inputs, self.result_inputs, self.admission,
            self.cursor_codec,
        ))
        if self.profile is ApiRuntimeProfile.PRODUCTION and not self.trusted_issuers:
            raise ValueError("Production trusted issuer allowlist is required.")
        if self.profile is ApiRuntimeProfile.PRODUCTION:
            for binding in (
                self.request_authentication_factory,
                self.request_security_factory,
                self.legacy_security,
            ):
                if binding is None or getattr(binding, "is_fake", False) or not callable(getattr(binding, "readiness_check", None)):
                    raise ValueError("Production request security binding is unavailable.")
            legacy_methods = ("authorize", "try_acquire", "release")
            if any(not callable(getattr(self.legacy_security, method, None)) for method in legacy_methods):
                raise ValueError("Production legacy security binding is incomplete.")
            factory_issuers = getattr(self.request_authentication_factory, "trusted_issuers", None)
            if factory_issuers != self.trusted_issuers:
                raise ValueError("Production authentication issuer registry is inconsistent.")
        if any(value is None for value in (
            self.ownership_inspector, self.session_factory, self.blob_store,
            self.active_executions,
        )):
            raise ValueError("Required analysis runtime binding is missing.")

    def readiness_check(self) -> bool:
        try:
            self.validate()
            deadline = self.clock.now_audit_time()
            authentication = (
                self.request_authentication_factory
                if self.request_authentication_factory is not None
                else self.authentication_context_provider
            )
            required = (
                authentication, self.authorization, self.security_audit, self.clock,
                self.document_inputs, self.result_inputs, self.admission,
                self.cursor_codec, self.request_security_factory,
                self.legacy_security,
            )
            return all(
                callable(getattr(binding, "readiness_check", None))
                and bool(binding.readiness_check(deadline))
                for binding in required
            )
        except Exception:
            return False

    def authenticate_request(self, *, authorization_headers, correlation_id, request_id):
        if self.request_authentication_factory is None:
            raise RuntimeError("Request authentication factory is unavailable.")
        return self.request_authentication_factory.authenticate(
            authorization_headers=authorization_headers,
            correlation_id=correlation_id, request_id=request_id,
        )

    def bind_request_security(self, *, authentication_provider, authorization_plan):
        if self.request_security_factory is None:
            raise RuntimeError("Request security factory is unavailable.")
        return self.request_security_factory.bind(
            authentication_provider=authentication_provider,
            authorization_plan=authorization_plan,
            trusted_issuers=self.trusted_issuers,
        )

    def authorize_legacy_request(self, *, definition, request, authentication_provider):
        if self.legacy_security is None:
            raise RuntimeError("Legacy route security adapter is unavailable.")
        return self.legacy_security.authorize(
            definition=definition, request=request,
            authentication_provider=authentication_provider,
        )

    def application_service(self, *, session, subject_id: str, authorization=None):
        bound_authorization = authorization or self.authorization
        reads = SqlAlchemyAnalysisReadAdapter(session, self.blob_store)
        return AnalysisApplicationService(
            authorization=bound_authorization,
            authorization_revalidation=(bound_authorization if getattr(bound_authorization, "requires_same_revalidation_instance", False) else None),
            security_audit=self.security_audit,
            observability=self.observability, active_executions=self.active_executions,
            clock=self.clock,
            scope_claims=SqlAlchemyRunScopeClaimRepository(
                self.session_factory, initiating_subject_id=subject_id,
            ),
            persistence=SqlAlchemyRunPersistenceAdapter(session, self.blob_store),
            reads=reads,
        )

    def read_facade(self, *, session, authorization=None):
        return ApiAnalysisReadFacade(
            reads=SqlAlchemyAnalysisReadAdapter(session, self.blob_store),
            authorization=authorization or self.authorization, security_audit=self.security_audit,
            observability=self.observability, clock=self.clock,
        )


_runtime: AnalysisApiRuntime | None = None


def configure_analysis_api_runtime(runtime: AnalysisApiRuntime) -> None:
    runtime.validate()
    global _runtime
    _runtime = runtime


def clear_analysis_api_runtime() -> None:
    global _runtime
    _runtime = None


def get_analysis_api_runtime() -> AnalysisApiRuntime:
    if _runtime is None:
        raise RuntimeError("Analysis API production composition is unavailable.")
    return _runtime


def default_active_execution_registry():
    return LocalActiveExecutionRegistry()
