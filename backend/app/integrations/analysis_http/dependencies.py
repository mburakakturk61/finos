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

    def validate(self) -> None:
        validate_runtime_bindings(self.profile, ProductionIntegrationBindings(
            self.authentication_context_provider, self.authorization,
            self.security_audit, self.observability, self.clock,
            self.document_inputs, self.result_inputs, self.admission,
            self.cursor_codec,
        ))
        if self.profile is ApiRuntimeProfile.PRODUCTION and not self.trusted_issuers:
            raise ValueError("Production trusted issuer allowlist is required.")

    def application_service(self, *, session, subject_id: str):
        reads = SqlAlchemyAnalysisReadAdapter(session, self.blob_store)
        return AnalysisApplicationService(
            authorization=self.authorization, security_audit=self.security_audit,
            observability=self.observability, active_executions=self.active_executions,
            clock=self.clock,
            scope_claims=SqlAlchemyRunScopeClaimRepository(
                self.session_factory, initiating_subject_id=subject_id,
            ),
            persistence=SqlAlchemyRunPersistenceAdapter(session, self.blob_store),
            reads=reads,
        )

    def read_facade(self, *, session):
        return ApiAnalysisReadFacade(
            reads=SqlAlchemyAnalysisReadAdapter(session, self.blob_store),
            authorization=self.authorization, security_audit=self.security_audit,
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
