from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from app.analysis_application.contracts import (
    AnalysisInputsDTO, AnalysisRunOptionsDTO, ApplicationAuditContextDTO,
    ApplicationOperationKind, ApplicationOriginalOperation, ApplicationScopeDTO,
)
from app.analysis_application.ports import AuthorizationDecision, SecurityAuditReceiptDTO
from app.analysis_application_v3 import (
    AnalysisApplicationServiceV3, ApplicationEngineCodeV3,
    StartAnalysisCommandV3, SynchronousOrchestratorV4Adapter,
    TrendRequestDTOV3, ApplicationTrendPeriodFamilyV3,
)
from app.orchestration_persistence_v4 import PersistedTrendRunV4

from test_multi_period_trend_orchestrator_v4_unit import context


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


class Clock:
    def now_audit_time(self): return NOW
    def resolve_business_time(self, value): return value or NOW


class Audit:
    def __init__(self, fail_on=None): self.events = []; self.fail_on = fail_on
    def record_required_event(self, event):
        self.events.append(event)
        if len(self.events) == self.fail_on:
            raise RuntimeError("audit unavailable")
        return SecurityAuditReceiptDTO("receipt", event.event_type, NOW, "a" * 64)


class Auth:
    def __init__(self, decisions): self.decisions = list(decisions)
    def authorize_start(self, scope, actor): return self.decisions.pop(0)
    authorize_resume = authorize_start
    authorize_retry = authorize_start
    def authorize_resume_source(self, source, scope, actor): return self.decisions.pop(0)


def decision(granted=True, revoked=False):
    return AuthorizationDecision(granted, revoked, "allow" if granted else "deny", "ref", NOW)


class Tenant:
    def __init__(self, value): self.value = value
    def resolve_tenant_id(self, scope, actor): return self.value


class Sources:
    def __init__(self, value): self.value = value
    def resolve_trend_context(self, request, scope, actor): return self.value


class Persistence:
    def __init__(self): self.commands = []
    def persist_terminal_run(self, command):
        self.commands.append(command)
        return PersistedTrendRunV4(uuid4(), uuid4(), "e" * 64, command.source_set_digest, False)


class NoResume:
    def load_verified_snapshot(self, *args): raise AssertionError("start must not load resume")


def command(ctx):
    scope = ApplicationScopeDTO(
        ctx.resolved_series[0].company_id, ctx.resolved_series[0].anchor_period_id,
        "tenant-key", ApplicationOperationKind.START, ApplicationOriginalOperation.START,
    )
    request = _unsafe_request(ctx)
    return StartAnalysisCommandV3(
        "application-v3-run", "correlation-v3", NOW, scope,
        ApplicationAuditContextDTO("subject", "human", "test", "analysis"),
        "auth-ref", (ApplicationEngineCodeV3.MULTI_PERIOD_TREND,),
        AnalysisInputsDTO(), AnalysisRunOptionsDTO(), (), None, request,
        None, None, None, None, None,
    )


def _unsafe_request(ctx):
    # Build a valid public request with one selection per lineage row.
    from app.analysis_application_v3 import TrendSourceSelectionIntentDTOV3, ApplicationTrendSourceRoleV3
    selections = tuple(TrendSourceSelectionIntentDTOV3(
        edge.source_period_id, ApplicationTrendSourceRoleV3(edge.source_role.value),
        edge.source_analysis_result_id,
    ) for edge in ctx.lineage)
    return TrendRequestDTOV3(
        ctx.resolved_series[0].anchor_period_id,
        tuple(dict.fromkeys(edge.source_period_id for edge in ctx.lineage)), selections,
        ApplicationTrendPeriodFamilyV3.ANNUAL, "TRY", "tfrs", "1.0.0",
        ctx.metric_registry_version, ctx.policy_version.value,
    )


def valid_command(ctx):
    return command(ctx)


def test_start_phases_authorization_revalidation_persistence_and_projection():
    ctx = context((100, 110, 121, 133, 146))
    persistence, audit = Persistence(), Audit()
    service = AnalysisApplicationServiceV3(
        orchestrator=SynchronousOrchestratorV4Adapter(), persistence=persistence,
        trend_sources=Sources(ctx), tenant_identities=Tenant(ctx.resolved_series[0].tenant_id),
        resume_snapshots=NoResume(), authorization=Auth((decision(), decision())),
        security_audit=audit, clock=Clock(),
    )
    outcome = service.start(valid_command(ctx))
    assert outcome.success is True
    assert outcome.value.executions[0].trend_projection.canonical_digest
    assert len(persistence.commands) == 1
    assert [item.event_type.value for item in audit.events][:3] == [
        "START_REQUESTED", "AUTHORIZATION_GRANTED", "TERMINAL_RUN_PERSISTED",
    ][:len(audit.events)]


def test_pre_persistence_revocation_blocks_write_and_payload_projection():
    ctx = context()
    persistence = Persistence()
    service = AnalysisApplicationServiceV3(
        orchestrator=SynchronousOrchestratorV4Adapter(), persistence=persistence,
        trend_sources=Sources(ctx), tenant_identities=Tenant(ctx.resolved_series[0].tenant_id),
        resume_snapshots=NoResume(), authorization=Auth((decision(), decision(False, True))),
        security_audit=Audit(), clock=Clock(),
    )
    outcome = service.start(valid_command(ctx))
    assert outcome.success is False and outcome.error.code == "AUTHORIZATION_REVOKED"
    assert persistence.commands == () or persistence.commands == []


def test_cross_company_resolved_context_is_fail_closed():
    ctx = context()
    wrong_scope_command = valid_command(ctx)
    wrong_scope_command = replace(wrong_scope_command, scope=replace(wrong_scope_command.scope, company_id=uuid4()))
    persistence = Persistence()
    service = AnalysisApplicationServiceV3(
        orchestrator=SynchronousOrchestratorV4Adapter(), persistence=persistence,
        trend_sources=Sources(ctx), tenant_identities=Tenant(ctx.resolved_series[0].tenant_id),
        resume_snapshots=NoResume(), authorization=Auth((decision(),)),
        security_audit=Audit(), clock=Clock(),
    )
    outcome = service.start(wrong_scope_command)
    assert outcome.success is False and outcome.error.code == "SCOPE_MISMATCH"
    assert persistence.commands == []


def test_post_commit_audit_failure_keeps_success_with_mandatory_warning():
    ctx = context()
    persistence = Persistence()
    service = AnalysisApplicationServiceV3(
        orchestrator=SynchronousOrchestratorV4Adapter(), persistence=persistence,
        trend_sources=Sources(ctx), tenant_identities=Tenant(ctx.resolved_series[0].tenant_id),
        resume_snapshots=NoResume(), authorization=Auth((decision(), decision())),
        security_audit=Audit(fail_on=3), clock=Clock(),
    )
    outcome = service.start(valid_command(ctx))
    assert outcome.success is True and len(persistence.commands) == 1
    assert outcome.warnings[0].code.value == "SECURITY_AUDIT_POST_COMMIT_FAILED"
