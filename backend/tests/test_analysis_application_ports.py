import ast
import inspect
from pathlib import Path

from app.analysis_application.contracts import AnalysisErrorCode
from app.analysis_application.errors import ERROR_POLICIES
from app.analysis_application.ports import (
    ActiveExecutionPort, AnalysisExecutionGatewayPort, AnalysisReadPort,
    ApplicationClockPort, AuthorizationPort, ObservabilityPort,
    RunPersistencePort, RunScopeClaimPort, SecurityAuditPort,
)


def test_error_policy_is_exhaustive_and_conflicts_are_not_retryable():
    assert set(ERROR_POLICIES) == set(AnalysisErrorCode)
    assert ERROR_POLICIES[AnalysisErrorCode.PERSISTENCE_CONFLICT].retryable is False
    assert ERROR_POLICIES[AnalysisErrorCode.EXECUTION_FAILED].retryable is False
    assert ERROR_POLICIES[AnalysisErrorCode.PERSISTENCE_UNAVAILABLE].retryable is True


def test_exact_port_methods():
    expected = {
        AnalysisExecutionGatewayPort: {"start", "resume", "retry"},
        AnalysisReadPort: {"get_status", "get_result", "get_execution_detail", "list_history", "load_scope", "load_resume_source"},
        AuthorizationPort: {"authorize_start", "authorize_resume", "authorize_resume_source", "authorize_read", "authorize_cancel", "authorize_retry"},
        ActiveExecutionPort: {"register", "unregister", "request_cancel", "is_active", "get_local_diagnostics"},
        SecurityAuditPort: {"record_required_event"},
        ObservabilityPort: {"emit_best_effort_event", "increment_metric", "record_timing"},
        ApplicationClockPort: {"now_audit_time", "resolve_business_time"},
        RunScopeClaimPort: {"claim", "verify", "finalize", "load"},
        RunPersistencePort: {"persist_terminal_run", "build_previous_execution_snapshot", "resolve_financial_ownership_plan", "resolve_payload_references"},
    }
    for protocol, methods in expected.items():
        assert methods <= {name for name, value in inspect.getmembers(protocol, inspect.isfunction)}


def test_application_core_has_no_forbidden_transitive_imports():
    root = Path("/app/app/analysis_application")
    forbidden = {"fastapi", "starlette", "pydantic", "sqlalchemy", "alembic"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        assert not (imports & forbidden), (path, imports & forbidden)
