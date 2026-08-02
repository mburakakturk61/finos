from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import uuid

from app.analysis_application.active import LocalActiveExecutionRegistry
from app.analysis_application.contracts import (
    AnalysisExecutionDTO, AnalysisInputsDTO, AnalysisResultDTO,
    AnalysisRunOptionsDTO, ApplicationAuditContextDTO, ApplicationEngineCode,
    ApplicationExecutionStatus, ApplicationOperationKind, ApplicationOriginalOperation,
    ApplicationScopeDTO, ApplicationStatus, ApplicationEventType,
    ResumeAnalysisCommand, StartAnalysisCommand,
    CancelAnalysisCommand, GetAnalysisResultQuery, ListAnalysisHistoryQuery,
    AnalysisHistoryPageDTO,
    FinancialSourceIntentDTO, FinancialSourceMode,
    FinancialSourceReferenceDTO, FinancialSourceRole,
)
from app.analysis_application.internal_types import InternalRunView, RunScopeClaim, TerminalPersistenceResult
from app.analysis_application.ports import AuthorizationDecision, SecurityAuditReceiptDTO
from app.analysis_application.service import AnalysisApplicationService
from app.analysis_application.query_service import AnalysisQueryService
from app.engines.analysis_orchestrator.types import (
    EngineCode, EngineExecutionStatus, EngineResultEnvelope, ExecutionProvenance,
    OrchestrationRunResult, PerEngineExecutionRecord, RunStatus,
)
from app.orchestration_persistence.types import PersistedRun, PersistenceRunScope
from app.analysis_application.contracts import RunScopeClaimStatus, AnalysisErrorCode, ApplicationWarningCode
from app.orchestration_persistence.errors import OrchestrationPersistenceError, PersistenceErrorCategory

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Clock:
    def now_audit_time(self): return NOW
    def resolve_business_time(self, value): return value or NOW


class Authorization:
    def __init__(self, decisions=None, events=None):
        self.decisions = list(decisions or [True, True])
        self.events = events
    def _decision(self, name):
        if self.events is not None: self.events.append(name)
        value = self.decisions.pop(0) if self.decisions else True
        if isinstance(value, Exception): raise value
        return AuthorizationDecision(bool(value) and value != "revoked", value == "revoked", str(value), "ref", NOW)
    def authorize_start(self, scope, actor): return self._decision("authorize_start")
    def authorize_resume(self, scope, actor): return self._decision("authorize_resume")
    def authorize_resume_source(self, source_run_id, target_scope, actor): return self._decision("authorize_source")
    def authorize_retry(self, scope, actor): return self._decision("authorize_retry")
    def authorize_cancel(self, scope, actor): return self._decision("authorize_cancel")
    def authorize_read(self, scope, actor, *, include_payload): return self._decision("authorize_read")


class Revalidation:
    def __init__(self, decisions, events=None): self.decisions, self.events = list(decisions), events
    def _decision(self, name):
        if self.events is not None: self.events.append(name)
        value = self.decisions.pop(0) if self.decisions else True
        if isinstance(value, Exception): raise value
        return AuthorizationDecision(bool(value) and value != "revoked", value == "revoked", str(value), "ref", NOW)
    def revalidate_start(self, scope, actor): return self._decision("revalidate_start")
    def revalidate_resume(self, scope, actor): return self._decision("revalidate_resume")
    def revalidate_retry(self, scope, actor): return self._decision("revalidate_retry")
    def revalidate_resume_source(self, source_run_id, target_scope, actor): return self._decision("revalidate_source")


class Audit:
    def __init__(self, fail_event=None, events=None): self.fail_event, self.events = fail_event, events
    def record_required_event(self, event):
        if self.events is not None: self.events.append(f"audit:{event.event_type.value}")
        if event.event_type is self.fail_event: raise RuntimeError("sink details must not escape")
        return SecurityAuditReceiptDTO("receipt", event.event_type, NOW, "a" * 64)


class Observability:
    def __init__(self): self.events = []
    def emit_best_effort_event(self, event): self.events.append(event.event_name)
    def increment_metric(self, name, value, tags): pass
    def record_timing(self, name, duration_ms, tags): pass


class Claims:
    def __init__(self): self.lock, self.claims = threading.Lock(), {}
    def claim(self, run_id, scope, digest, claimed_at):
        with self.lock:
            current = self.claims.get(run_id)
            if current is None:
                current = RunScopeClaim(uuid.uuid4(), run_id, scope.company_id, scope.financial_period_id, scope.tenant_id, scope.operation_kind, scope.original_operation, scope.previous_run_id, digest, RunScopeClaimStatus.CLAIMED, 1, "token", None, None, None, claimed_at, None)
                self.claims[run_id] = current
            if current.application_command_digest != digest or not _same_scope(current, scope): raise RuntimeError("conflict")
            return current
    def verify(self, run_id, scope, claim_token, expected_version): return self.claims[run_id]
    def finalize(self, run_id, scope, claim_token, expected_version, persisted, finalized_at):
        with self.lock:
            current = self.claims[run_id]
            if current.status is RunScopeClaimStatus.FINALIZED: return current
            final = RunScopeClaim(current.claim_id, current.run_id, current.company_id, current.financial_period_id, current.tenant_id, current.operation_kind, current.original_operation, current.previous_run_id, current.application_command_digest, RunScopeClaimStatus.FINALIZED, 2, current.claim_token, persisted.id, persisted.request_fingerprint, persisted.terminal_content_digest, current.claimed_at, finalized_at)
            self.claims[run_id] = final
            return final
    def load(self, run_id): return self.claims.get(run_id)


class Persistence:
    def __init__(self, state, events=None): self.state, self.events, self.calls = state, events, 0
    def resolve_financial_ownership_plan(self, result, intents, scope, audit_times):
        from app.analysis_application.internal_types import ResolvedFinancialOwnershipPlan
        return ResolvedFinancialOwnershipPlan((), audit_times)
    def persist_terminal_run(self, request):
        with self.state["lock"]:
            self.calls += 1
            existing = self.state.get("persisted")
            if existing is None:
                persisted_scope = PersistenceRunScope(request.scope.company_id, request.scope.financial_period_id)
                if self.state.get("wrong_persisted_scope"):
                    persisted_scope = PersistenceRunScope(uuid.uuid4(), request.scope.financial_period_id)
                existing = PersistedRun(uuid.uuid4(), request.run_result.run_id, request.run_result.request_fingerprint, "e" * 64, persisted_scope, NOW)
                self.state["persisted"] = existing
                replay = False
            else: replay = True
            return TerminalPersistenceResult(existing, replay)
    def build_previous_execution_snapshot(self, run_id, target_scope):
        if self.events is not None: self.events.append("snapshot_materialized")
        raise AssertionError("snapshot must not materialize after source deny")
    def resolve_payload_references(self, run_id, scope, *, include_payloads): return ()


class Reads:
    def __init__(self, state):
        self.state = state
        self.fail_projection = False
    def get_run_by_id(self, run_id, scope):
        persisted = self.state.get("persisted")
        if not persisted: return None
        return InternalRunView(persisted.id, run_id, ApplicationStatus.FULLY_COMPLETED, persisted.scope, (ApplicationEngineCode.BENCHMARK,), persisted.request_fingerprint, persisted.terminal_content_digest, None, persisted.finalized_at)
    def get_result(self, run_id, scope, *, include_payloads):
        if self.fail_projection: raise ValueError("projection")
        persisted = self.state.get("persisted")
        if not persisted: return None
        execution = AnalysisExecutionDTO(ApplicationEngineCode.BENCHMARK, ApplicationExecutionStatus.COMPLETED, None, "1", "1", "b" * 64, "1")
        return AnalysisResultDTO(run_id, ApplicationStatus.FULLY_COMPLETED, scope, persisted.request_fingerprint, (execution,), (), (), "2", "2", "2", NOW)
    def load_resume_source(self, previous_run_id, target_scope, *, materialize_payloads):
        self.state.setdefault("events", []).append("resume_metadata")
        return object()
    def get_status(self, run_id, scope): return None
    def get_execution_detail(self, run_id, engine_code, scope, *, include_payload): return None
    def list_history(self, scope, cursor, limit): raise NotImplementedError
    def load_scope(self, run_id): return None


def _scope(kind=ApplicationOperationKind.START, original=ApplicationOriginalOperation.START, previous=None):
    return ApplicationScopeDTO(uuid.UUID(int=1), uuid.UUID(int=2), "tenant-a", kind, original, previous)


def _command(run_id="run", *, resume=False):
    scope = _scope(ApplicationOperationKind.RESUME, ApplicationOriginalOperation.RESUME, "previous") if resume else _scope()
    cls = ResumeAnalysisCommand if resume else StartAnalysisCommand
    intents = (
        FinancialSourceIntentDTO(ApplicationEngineCode.FS_BALANCE_SHEET, scope.company_id, scope.financial_period_id, None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {}),
        FinancialSourceIntentDTO(ApplicationEngineCode.FS_INCOME_STATEMENT, scope.company_id, scope.financial_period_id, None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {}),
        FinancialSourceIntentDTO(ApplicationEngineCode.RATIO, scope.company_id, scope.financial_period_id, None, (
            FinancialSourceReferenceDTO(FinancialSourceRole.PRIMARY_ANALYSIS, source_engine_code=ApplicationEngineCode.FS_BALANCE_SHEET),
            FinancialSourceReferenceDTO(FinancialSourceRole.SUPPORTING_ANALYSIS, source_engine_code=ApplicationEngineCode.FS_INCOME_STATEMENT),
        ), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {}),
    )
    return cls(run_id, "corr", NOW, scope, ApplicationAuditContextDTO("actor", "service", "test", "analysis"), "auth", (ApplicationEngineCode.BENCHMARK,), AnalysisInputsDTO(), AnalysisRunOptionsDTO(), intents)


def _executor(counter):
    def execute(request, cancellation_probe=None):
        counter.append(request.run_id)
        record = PerEngineExecutionRecord(EngineCode.BENCHMARK, EngineExecutionStatus.COMPLETED, EngineResultEnvelope(EngineCode.BENCHMARK, "dict", {"ok": True}), "computed", None, (), "1", "1", "b" * 64, "1")
        result = OrchestrationRunResult(request.run_id, request.correlation_id, request.generated_at, RunStatus.FULLY_COMPLETED, (record,), (), (), ExecutionProvenance("2", (EngineCode.BENCHMARK,), (), ()), {}, "2", "2", "2", "d" * 64)
        return result, None
    return execute


def _service(state=None, *, authorization=None, revalidation=None, audit=None, active=None, executor=None, events=None):
    state = state or {"lock": threading.Lock()}
    reads = Reads(state)
    service = AnalysisApplicationService(
        authorization=authorization or Authorization(events=events), security_audit=audit or Audit(events=events),
        observability=Observability(), active_executions=active or LocalActiveExecutionRegistry(),
        clock=Clock(), scope_claims=state.setdefault("claims", Claims()),
        persistence=Persistence(state, events), reads=reads, executor=executor or _executor([]),
        authorization_revalidation=revalidation,
    )
    return service, reads


def test_same_process_and_cross_process_duplicates_share_terminal_semantics():
    for shared_active in (True, False):
        state = {"lock": threading.Lock()}
        counter = []
        common_active = LocalActiveExecutionRegistry()
        services = tuple(_service(state, active=common_active if shared_active else LocalActiveExecutionRegistry(), executor=_executor(counter))[0] for _ in range(2))
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(lambda service: service.start(_command()), services))
        assert all(item.success for item in outcomes)
        assert outcomes[0].value.terminal_content_digest == outcomes[1].value.terminal_content_digest
        assert len(counter) >= 1


def test_pre_persistence_authorization_revocation_is_fail_closed():
    state = {"lock": threading.Lock()}
    service, _ = _service(state, authorization=Authorization([True, "revoked"]))
    outcome = service.start(_command())
    assert outcome.error.code is AnalysisErrorCode.AUTHORIZATION_REVOKED
    assert "persisted" not in state


def test_explicit_step11_revalidation_port_blocks_persistence_without_reusing_initial_decision():
    events = []
    state = {"lock": threading.Lock()}
    service, _ = _service(
        state,
        authorization=Authorization([True], events),
        revalidation=Revalidation(["revoked"], events),
        events=events,
    )
    outcome = service.start(_command())
    assert outcome.error.code is AnalysisErrorCode.AUTHORIZATION_REVOKED
    assert "persisted" not in state
    assert events.index("authorize_start") < events.index("revalidate_start")


def test_explicit_step11_final_allow_persists_exactly_once():
    state = {"lock": threading.Lock()}
    service, _ = _service(
        state,
        authorization=Authorization([True]),
        revalidation=Revalidation([True]),
    )
    outcome = service.start(_command())
    assert outcome.success
    assert service.persistence.calls == 1


def test_required_pre_execution_audit_failure_blocks_execution():
    counter = []
    service, _ = _service(audit=Audit(ApplicationEventType.START_REQUESTED), executor=_executor(counter))
    outcome = service.start(_command())
    assert outcome.error.code is AnalysisErrorCode.SECURITY_AUDIT_FAILED
    assert counter == []


def test_post_commit_audit_failure_keeps_success_with_mandatory_warning():
    service, _ = _service(audit=Audit(ApplicationEventType.TERMINAL_RUN_PERSISTED))
    outcome = service.start(_command())
    assert outcome.success
    assert outcome.warnings[0].code is ApplicationWarningCode.SECURITY_AUDIT_POST_COMMIT_FAILED


def test_projection_failure_is_recoverable_without_reexecution():
    counter = []
    service, reads = _service(executor=_executor(counter))
    reads.fail_projection = True
    failed = service.start(_command())
    assert failed.error.code is AnalysisErrorCode.DTO_PROJECTION_FAILED
    reads.fail_projection = False
    recovered = service.start(_command())
    assert recovered.success and recovered.value.idempotent_replay
    assert counter == ["run"]


def test_resume_source_deny_precedes_snapshot_materialization_and_execution():
    events, counter = [], []
    authorization = Authorization([True, False], events)
    state = {"lock": threading.Lock(), "events": events}
    service, _ = _service(state, authorization=authorization, executor=_executor(counter), events=events)
    outcome = service.resume(_command("resume", resume=True))
    assert outcome.error.code is AnalysisErrorCode.RESUME_SOURCE_UNAUTHORIZED
    assert "snapshot_materialized" not in events
    assert counter == []


def test_same_run_same_scope_different_command_is_rejected_without_reexecution():
    from dataclasses import replace
    counter = []
    service, _ = _service(executor=_executor(counter))
    assert service.start(_command()).success
    changed = replace(_command(), inputs=AnalysisInputsDTO(balance_sheet_content=b"different"))
    outcome = service.start(changed)
    assert outcome.error.code is AnalysisErrorCode.RUN_ID_CONFLICT
    assert counter == ["run"]


def test_corrupted_resume_source_never_falls_back_to_clean_start():
    counter = []
    service, _ = _service(executor=_executor(counter))
    def corrupted(run_id, target_scope):
        raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE, "safe")
    service.persistence.build_previous_execution_snapshot = corrupted
    outcome = service.resume(_command("resume-corrupt", resume=True))
    assert outcome.error.code is AnalysisErrorCode.RESUME_SOURCE_CORRUPTED
    assert counter == []


def test_cancel_is_a_normal_business_result_and_not_idempotency_state():
    state = {"lock": threading.Lock()}
    active = LocalActiveExecutionRegistry()
    service, _ = _service(state, active=active)
    command = _command()
    token = active.register(command.run_id, command.scope, command.correlation_id)
    cancel = CancelAnalysisCommand(command.run_id, command.correlation_id, NOW, command.scope, command.audit_context, "auth")
    assert service.cancel(cancel).value.status.value == "ACCEPTED"
    assert service.cancel(cancel).value.status.value == "ALREADY_REQUESTED"
    active.unregister(token)
    assert service.cancel(cancel).value.status.value == "NOT_FOUND"


def test_query_authorization_and_required_audit_precede_materialization():
    state = {"lock": threading.Lock()}
    persisted = PersistedRun(uuid.uuid4(), "run", "d" * 64, "e" * 64, PersistenceRunScope(uuid.UUID(int=1), uuid.UUID(int=2)), NOW)
    state["persisted"] = persisted
    reads = Reads(state)
    events = []
    service = AnalysisQueryService(
        authorization=Authorization([True], events), security_audit=Audit(events=events),
        observability=Observability(), clock=Clock(), reads=reads,
    )
    command = _command()
    query = GetAnalysisResultQuery(command.run_id, command.correlation_id, NOW, command.scope, command.audit_context, "auth", include_payloads=True)
    outcome = service.get_result(query)
    assert outcome.success
    assert events[:3] == ["authorize_read", "audit:AUTHORIZATION_GRANTED", "audit:RESULT_READ"]


def test_query_deny_and_audit_failure_are_fail_closed():
    command = _command()
    query = GetAnalysisResultQuery(command.run_id, command.correlation_id, NOW, command.scope, command.audit_context, "auth", include_payloads=True)
    denied = AnalysisQueryService(
        authorization=Authorization([False]), security_audit=Audit(), observability=Observability(),
        clock=Clock(), reads=Reads({"lock": threading.Lock()}),
    ).get_result(query)
    assert denied.error.code is AnalysisErrorCode.UNAUTHORIZED
    audit_failed = AnalysisQueryService(
        authorization=Authorization([True]), security_audit=Audit(ApplicationEventType.RESULT_READ),
        observability=Observability(), clock=Clock(), reads=Reads({"lock": threading.Lock()}),
    ).get_result(query)
    assert audit_failed.error.code is AnalysisErrorCode.SECURITY_AUDIT_FAILED


def test_post_persist_returned_scope_mismatch_never_projects_success():
    state = {"lock": threading.Lock(), "wrong_persisted_scope": True}
    service, _ = _service(state)
    outcome = service.start(_command())
    assert outcome.error.code is AnalysisErrorCode.SCOPE_MISMATCH


def _same_scope(claim, scope):
    return (claim.company_id, claim.financial_period_id, claim.tenant_id, claim.operation_kind, claim.original_operation, claim.previous_run_id) == (scope.company_id, scope.financial_period_id, scope.tenant_id, scope.operation_kind, scope.original_operation, scope.previous_run_id)
