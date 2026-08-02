from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis_application.contracts import (
    ApplicationAuditContextDTO,
    ApplicationEventType,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
)
from app.analysis_application.ports import SecurityAuditReceiptDTO
from app.security.authorization_adapter import (
    AuditDeliveryState,
    AuthorizationAdapterDecisionCode,
    AuthorizationAuditDeliveryError,
    AuthorizationAuditDeliveryErrorCode,
    AuthorizationCheckpoint,
    AuthorizationDecisionReferenceCodec,
    LocalAuthorizationPolicyClient,
    TrustedAuthorizationContext,
    TrustedAuthorizationContextError,
    TrustedAuthorizationContextErrorCode,
)
from app.security.authorization_policy import (
    COMPILED_SECURITY_ACTIONS,
    PERMISSION_REGISTRY_VERSION,
    AuditIntent,
    EffectivePermissionSet,
    PolicyAuthenticationStrength,
    PolicyAuditRequirement,
    PolicyEvaluationResult,
    PolicyExistenceHiding,
    PolicyOutcome,
    PolicyReasonCode,
    PolicyScopeType,
    ResourceSecurityReference,
    SecuritySeverity,
    SubjectReferenceHashCodec,
)
from app.security.contracts import (
    IdentityKind,
    IdentityResolutionError,
    IdentityResolutionErrorCode,
    SecurityEntityStatus,
    VerifiedLocalIdentity,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 2, 10, 11, 13, 123456, tzinfo=UTC)
TOKEN_TIME = NOW - timedelta(minutes=1)
ISSUER = "https://issuer.adapter.example"
TENANT = "tenant-adapter"
SUBJECT = "user-adapter"
CORRELATION = "corr-adapter-0001"
COMPANY_ID = uuid.UUID(int=1)
PERIOD_ID = uuid.UUID(int=2)
MEMBERSHIP_ID = uuid.UUID(int=4)
SUBJECT_CODEC = SubjectReferenceHashCodec({"k1": bytes(range(32))}, active_key_version="k1")


def _identity() -> VerifiedLocalIdentity:
    digest = "a" * 64
    return VerifiedLocalIdentity(
        principal_id=uuid.UUID(int=3),
        principal_kind=IdentityKind.HUMAN,
        provider_issuer=ISSUER,
        provider_subject=SUBJECT,
        tenant_id=uuid.UUID(int=5),
        tenant_key=TENANT,
        membership_id=MEMBERSHIP_ID,
        principal_status=SecurityEntityStatus.ACTIVE,
        tenant_status=SecurityEntityStatus.ACTIVE,
        binding_status=SecurityEntityStatus.ACTIVE,
        membership_status=SecurityEntityStatus.ACTIVE,
        authentication_context_subject=SUBJECT,
        authentication_context_tenant_key=TENANT,
        roles=("FINANCE_ANALYST",),
        permission_resolution_reference=f"policy-ref/v1:7:{MEMBERSHIP_ID}:3:{PERMISSION_REGISTRY_VERSION}:{digest}",
        role_set_digest=digest,
        permission_registry_version=PERMISSION_REGISTRY_VERSION,
        tenant_policy_version=7,
        tokens_valid_after=TOKEN_TIME - timedelta(minutes=1),
        membership_valid_from=TOKEN_TIME - timedelta(days=1),
        membership_valid_until=None,
        principal_version=2,
        membership_version=3,
        resolved_at=NOW,
    )


IDENTITY = _identity()
SUBJECT_REF = SUBJECT_CODEC.encode(
    issuer=ISSUER, tenant_key=TENANT,
    principal_kind=IdentityKind.HUMAN, provider_subject=SUBJECT,
)


def _scope(kind=ApplicationOperationKind.START, previous=None):
    original = (
        ApplicationOriginalOperation.START if kind is ApplicationOperationKind.START
        else ApplicationOriginalOperation.RESUME if kind is ApplicationOperationKind.RESUME
        else ApplicationOriginalOperation.START
    )
    return ApplicationScopeDTO(COMPANY_ID, PERIOD_ID, TENANT, kind, original, previous)


def _reference(checkpoint, scope, correlation=CORRELATION):
    if checkpoint in {AuthorizationCheckpoint.RESUME_SOURCE, AuthorizationCheckpoint.PRE_PERSIST_RESUME_SOURCE}:
        return ResourceSecurityReference(
            PolicyScopeType.ANALYSIS_RUN, scope.previous_run_id, TENANT,
            None, None, None, correlation, NOW,
        )
    if checkpoint in {AuthorizationCheckpoint.READ, AuthorizationCheckpoint.CANCEL}:
        return ResourceSecurityReference(
            PolicyScopeType.ANALYSIS_RUN, "run-target", TENANT,
            None, None, None, correlation, NOW,
        )
    return ResourceSecurityReference(
        PolicyScopeType.COMPANY_PERIOD,
        f"cp1:{COMPANY_ID}:{PERIOD_ID}", TENANT,
        COMPANY_ID, PERIOD_ID, None, correlation, NOW,
    )


def _context(checkpoint, scope, **overrides):
    values = dict(
        issuer=ISSUER,
        subject=SUBJECT,
        tenant_key=TENANT,
        token_issued_at=TOKEN_TIME,
        expires_at=NOW + timedelta(minutes=5),
        expected_principal_kind=IdentityKind.HUMAN,
        service_client_id=None,
        authentication_strength=PolicyAuthenticationStrength.MFA,
        correlation_id=CORRELATION,
        request_id="request-adapter-0001",
        authorization_context_reference=f"authz:v1:H:{MEMBERSHIP_ID}:3:7",
        checkpoint=checkpoint,
        resource_reference=_reference(checkpoint, scope),
        resolved_at=NOW,
    )
    values.update(overrides)
    return TrustedAuthorizationContext(**values)


class Contexts:
    is_fake = False
    def __init__(self, factory=_context): self.factory, self.calls = factory, []
    def resolve_context(self, *, checkpoint, application_scope, audit_context):
        self.calls.append(checkpoint)
        return self.factory(checkpoint, application_scope)


class Identities:
    def __init__(self, value=IDENTITY): self.value, self.calls = value, []
    def resolve_principal_and_membership(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.value, Exception): raise self.value
        return self.value


class Policies:
    def __init__(self, error=None): self.error, self.calls = error, []
    def resolve_effective_permissions(self, request):
        self.calls.append(request)
        if self.error: raise self.error
        return EffectivePermissionSet(
            tuple(sorted(COMPILED_SECURITY_ACTIONS)),
            IDENTITY.roles, IDENTITY.principal_kind, IDENTITY.membership_id,
            PERMISSION_REGISTRY_VERSION, IDENTITY.tenant_policy_version,
            IDENTITY.membership_version, IDENTITY.role_set_digest, NOW,
        )


class Engine:
    def __init__(self, reason=PolicyReasonCode.ALLOWED): self.reason, self.actions = reason, []
    def evaluate(self, *, request, effective_permissions):
        self.actions.append(request.action.action_code)
        reason = self.reason
        outcome = (
            PolicyOutcome.ALLOW if reason is PolicyReasonCode.ALLOWED
            else PolicyOutcome.INDETERMINATE if reason in {
                PolicyReasonCode.POLICY_STORE_UNAVAILABLE,
                PolicyReasonCode.POLICY_STORE_TIMEOUT,
                PolicyReasonCode.DATA_INTEGRITY_VIOLATION,
            } else PolicyOutcome.DENY
        )
        requirement = (
            PolicyAuditRequirement.SECURITY_CRITICAL
            if reason in {PolicyReasonCode.UNKNOWN_ACTION, PolicyReasonCode.UNKNOWN_PERMISSION, PolicyReasonCode.DATA_INTEGRITY_VIOLATION}
            else request.action.audit_requirement
        )
        required = (
            outcome is PolicyOutcome.INDETERMINATE
            or requirement in {PolicyAuditRequirement.SECURITY_CRITICAL, PolicyAuditRequirement.ALLOW_AND_DENY}
            or (outcome is PolicyOutcome.DENY and requirement is PolicyAuditRequirement.DENY_ONLY)
        )
        intent = AuditIntent(
            required, requirement,
            f"security.authorization.{outcome.value.lower()}.{reason.value.lower()}",
            outcome, reason, request.action.action_code, request.action.resource_type,
            request.correlation_id, SUBJECT_REF, TENANT, SecuritySeverity.HIGH,
        )
        return PolicyEvaluationResult(
            outcome, reason, request.action.action_code, IDENTITY.principal_id,
            TENANT, request.action.resource_type, request.resource_reference.resource_id,
            request.action.required_permission if outcome is PolicyOutcome.ALLOW else None,
            request.authentication_strength, IDENTITY.principal_kind,
            True if outcome is PolicyOutcome.ALLOW else None,
            True if outcome is PolicyOutcome.ALLOW else None,
            outcome is not PolicyOutcome.ALLOW,
            intent, PERMISSION_REGISTRY_VERSION, 7, NOW, CORRELATION,
        )


class SequenceEngine(Engine):
    def __init__(self, reasons): super().__init__(); self.reasons = list(reasons)
    def evaluate(self, *, request, effective_permissions):
        self.reason = self.reasons.pop(0)
        return super().evaluate(request=request, effective_permissions=effective_permissions)


class Audit:
    def __init__(self, failure=None): self.failure, self.events, self.by_key = failure, [], {}
    def record_required_event(self, event):
        self.events.append(event)
        if self.failure: raise self.failure
        attrs = dict(event.safe_attributes)
        key, digest = attrs.get("audit_idempotency_key"), attrs.get("audit_event_digest")
        if key:
            if key in self.by_key and self.by_key[key] != digest:
                raise AuthorizationAuditDeliveryError(AuthorizationAuditDeliveryErrorCode.AUDIT_DELIVERY_CONFLICT)
            self.by_key[key] = digest
        return SecurityAuditReceiptDTO("receipt-adapter", event.event_type, NOW, "b" * 64)


class Clock:
    def now_audit_time(self): return NOW
    def resolve_business_time(self, value): return value or NOW


class Observability:
    def __init__(self): self.metrics = []
    def increment_metric(self, name, value, tags): self.metrics.append(name)
    def emit_best_effort_event(self, event): pass
    def record_timing(self, name, duration_ms, tags): pass


def _client(*, contexts=None, identities=None, policies=None, engine=None, audit=None, production=False):
    return LocalAuthorizationPolicyClient(
        context_provider=contexts or Contexts(),
        identity_repository=identities or Identities(),
        policy_repository=policies or Policies(),
        policy_engine=engine or Engine(),
        security_audit=audit or Audit(),
        observability=Observability(), clock=Clock(),
        subject_reference_hash_codec=SUBJECT_CODEC,
        production_mode=production,
    )


def _actor(value=SUBJECT_REF):
    return ApplicationAuditContextDTO(value, "test", "unit", "authorization")


def test_closed_taxonomy_sizes_and_frozen_public_decision_contract():
    assert len(AuthorizationAdapterDecisionCode) == 47
    assert len(TrustedAuthorizationContextErrorCode) == 8
    assert len(AuthorizationAuditDeliveryErrorCode) == 6
    from app.analysis_application.ports import AuthorizationDecision
    assert tuple(AuthorizationDecision.__dataclass_fields__) == (
        "granted", "revoked", "decision_code", "provider_decision_reference", "decided_at",
    )


@pytest.mark.parametrize("reason", tuple(PolicyReasonCode))
def test_all_17_policy_reasons_map_fail_closed_except_allowed(reason):
    result = _client(engine=Engine(reason)).authorize_start(_scope(), _actor())
    assert result.granted is (reason is PolicyReasonCode.ALLOWED)
    assert result.decision_code == _expected_policy_code(reason)
    assert result.provider_decision_reference.startswith("adr1:")


def _expected_policy_code(reason):
    from app.security.authorization_adapter import _POLICY_DECISIONS
    return _POLICY_DECISIONS[reason].value


@pytest.mark.parametrize("code", tuple(IdentityResolutionErrorCode))
def test_all_19_identity_errors_map_without_raw_exception(code):
    error = IdentityResolutionError(code, correlation_id=CORRELATION)
    result = _client(identities=Identities(error)).authorize_start(_scope(), _actor())
    assert result.granted is False
    assert result.decision_code in {item.value for item in AuthorizationAdapterDecisionCode}
    assert "raw" not in repr(result).lower()


@pytest.mark.parametrize("code", tuple(TrustedAuthorizationContextErrorCode))
def test_all_8_context_errors_are_fail_closed(code):
    def fail(checkpoint, scope):
        raise TrustedAuthorizationContextError(code)
    result = _client(contexts=Contexts(fail)).authorize_start(_scope(), _actor())
    assert result.granted is False
    assert result.decision_code in {item.value for item in AuthorizationAdapterDecisionCode}


@pytest.mark.parametrize("code", tuple(AuthorizationAuditDeliveryErrorCode))
def test_all_6_audit_errors_block_required_allow(code):
    result = _client(audit=Audit(AuthorizationAuditDeliveryError(code))).authorize_start(_scope(), _actor())
    assert result.granted is False
    assert result.decision_code in {
        AuthorizationAdapterDecisionCode.AUDIT_REQUIRED_BUT_UNAVAILABLE.value,
        AuthorizationAdapterDecisionCode.AUTHZ_AUDIT_INTEGRITY_FAILURE.value,
    }


def test_missing_invalid_stale_expired_subject_tenant_and_provider_fail_closed():
    cases = [
        Contexts(lambda checkpoint, scope: None),
        Contexts(lambda checkpoint, scope: object()),
        Contexts(lambda checkpoint, scope: _context(checkpoint, scope, token_issued_at=NOW - timedelta(minutes=16))),
        Contexts(lambda checkpoint, scope: _context(checkpoint, scope, expires_at=NOW)),
        Contexts(),
        Contexts(lambda checkpoint, scope: _context(checkpoint, scope, tenant_key="wrong-tenant")),
        Contexts(lambda checkpoint, scope: (_ for _ in ()).throw(ConnectionError("raw provider"))),
    ]
    actors = [_actor(), _actor(), _actor(), _actor(), _actor("srh1:k1:" + "0" * 64), _actor(), _actor()]
    for contexts, actor in zip(cases, actors):
        assert not _client(contexts=contexts).authorize_start(_scope(), actor).granted


def test_fake_context_provider_is_rejected_in_production_mode():
    contexts = Contexts()
    contexts.is_fake = True
    with pytest.raises(ValueError, match="fake"):
        _client(contexts=contexts, production=True)


def test_six_public_methods_and_four_revalidation_methods_use_exact_actions():
    engine = Engine()
    client = _client(engine=engine)
    start = _scope()
    resume = _scope(ApplicationOperationKind.RESUME, "source-run")
    retry = _scope(ApplicationOperationKind.RETRY, "source-run")
    assert client.authorize_start(start, _actor()).granted
    assert client.authorize_resume(resume, _actor()).granted
    assert client.authorize_resume_source("source-run", resume, _actor()).granted
    assert client.authorize_read(start, _actor(), include_payload=True).granted
    assert client.authorize_cancel(start, _actor()).granted
    assert client.authorize_retry(retry, _actor()).granted
    assert client.revalidate_start(start, _actor()).granted
    assert client.revalidate_resume(resume, _actor()).granted
    assert client.revalidate_retry(retry, _actor()).granted
    assert client.revalidate_resume_source("source-run", resume, _actor()).granted
    assert set(engine.actions) >= {
        "analysis.start", "analysis.resume", "analysis.resume_source",
        "analysis.read", "analysis.payload.read", "analysis.cancel.own", "analysis.retry",
    }


def test_resume_source_wrong_binding_and_destination_context_mismatch_fail_closed():
    resume = _scope(ApplicationOperationKind.RESUME, "source-run")
    wrong_source = Contexts(lambda checkpoint, scope: dataclasses.replace(
        _context(checkpoint, scope),
        resource_reference=ResourceSecurityReference(
            PolicyScopeType.ANALYSIS_RUN, "spoofed", TENANT,
            None, None, None, CORRELATION, NOW,
        ),
    ))
    assert not _client(contexts=wrong_source).authorize_resume_source("source-run", resume, _actor()).granted
    wrong_tenant = Contexts(lambda checkpoint, scope: dataclasses.replace(
        _context(checkpoint, scope), tenant_key="other-tenant",
    ))
    assert not _client(contexts=wrong_tenant).revalidate_resume(resume, _actor()).granted


@pytest.mark.parametrize(
    ("second_reason", "expected_code", "revoked"),
    (
        (PolicyReasonCode.PERMISSION_NOT_GRANTED, "AUTHZ_REVALIDATION_REVOKED_POLICY", True),
        (PolicyReasonCode.RESOURCE_OWNERSHIP_MISMATCH, "AUTHZ_REVALIDATION_REVOKED_RESOURCE", True),
        (PolicyReasonCode.RESOURCE_NOT_FOUND, "AUTHZ_RESOURCE_NOT_FOUND", False),
    ),
)
def test_resume_source_is_freshly_revalidated_for_permission_ownership_and_hiding(second_reason, expected_code, revoked):
    resume = _scope(ApplicationOperationKind.RESUME, "source-run")
    engine = SequenceEngine((PolicyReasonCode.ALLOWED, second_reason))
    client = _client(engine=engine)
    assert client.authorize_resume_source("source-run", resume, _actor()).granted
    final = client.revalidate_resume_source("source-run", resume, _actor())
    assert (final.granted, final.revoked, final.decision_code) == (False, revoked, expected_code)


def test_resume_source_initial_allow_then_principal_revoke_is_fail_closed():
    class SequenceIdentities:
        def __init__(self): self.calls = 0
        def resolve_principal_and_membership(self, **kwargs):
            self.calls += 1
            if self.calls == 1: return IDENTITY
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.PRINCIPAL_INACTIVE,
                correlation_id=CORRELATION,
            )
    resume = _scope(ApplicationOperationKind.RESUME, "source-run")
    client = _client(identities=SequenceIdentities())
    assert client.authorize_resume_source("source-run", resume, _actor()).granted
    final = client.revalidate_resume_source("source-run", resume, _actor())
    assert (final.granted, final.revoked, final.decision_code) == (
        False, True, "AUTHZ_REVALIDATION_REVOKED_PRINCIPAL",
    )


def test_cancel_any_fallback_is_human_only_and_never_opens_on_hidden_failure():
    permission_then_allow = SequenceEngine((
        PolicyReasonCode.PERMISSION_NOT_GRANTED, PolicyReasonCode.ALLOWED,
    ))
    client = _client(engine=permission_then_allow)
    assert client.authorize_cancel(_scope(), _actor()).granted
    assert permission_then_allow.actions == ["analysis.cancel.own", "analysis.cancel.any"]
    hidden = SequenceEngine((PolicyReasonCode.RESOURCE_NOT_FOUND, PolicyReasonCode.ALLOWED))
    denied = _client(engine=hidden).authorize_cancel(_scope(), _actor())
    assert not denied.granted
    assert hidden.actions == ["analysis.cancel.own"]


def test_unknown_policy_result_type_is_safe_terminal_integrity_failure():
    class InvalidEngine:
        def evaluate(self, **kwargs): return object()
    result = _client(engine=InvalidEngine()).authorize_start(_scope(), _actor())
    assert (result.granted, result.revoked, result.decision_code) == (
        False, False, "AUTHZ_ADAPTER_INTEGRITY_FAILURE",
    )


def test_revalidation_distinguishes_policy_and_resource_revocation_from_normal_deny():
    normal = _client(engine=Engine(PolicyReasonCode.PERMISSION_NOT_GRANTED)).authorize_start(_scope(), _actor())
    policy = _client(engine=Engine(PolicyReasonCode.PERMISSION_NOT_GRANTED)).revalidate_start(_scope(), _actor())
    resource = _client(engine=Engine(PolicyReasonCode.RESOURCE_OWNERSHIP_MISMATCH)).revalidate_start(_scope(), _actor())
    assert (normal.revoked, normal.decision_code) == (False, "AUTHZ_PERMISSION_NOT_GRANTED")
    assert (policy.revoked, policy.decision_code) == (True, "AUTHZ_REVALIDATION_REVOKED_POLICY")
    assert (resource.revoked, resource.decision_code) == (True, "AUTHZ_REVALIDATION_REVOKED_RESOURCE")


@pytest.mark.parametrize("field", ("membership_version", "tenant_policy_version"))
def test_revalidation_version_proof_change_is_policy_revocation(field):
    values = dict(IDENTITY.__dict__)
    values[field] += 1
    values["permission_resolution_reference"] = (
        f"policy-ref/v1:{values['tenant_policy_version']}:{values['membership_id']}:"
        f"{values['membership_version']}:{values['permission_registry_version']}:{values['role_set_digest']}"
    )
    changed = VerifiedLocalIdentity(**values)
    result = _client(identities=Identities(changed)).revalidate_start(_scope(), _actor())
    assert (result.granted, result.revoked, result.decision_code) == (
        False, True, "AUTHZ_REVALIDATION_REVOKED_POLICY",
    )


def test_deny_only_audit_failure_never_becomes_grant():
    result = _client(
        engine=Engine(PolicyReasonCode.PERMISSION_NOT_GRANTED),
        audit=Audit(ConnectionError("raw audit endpoint")),
    ).authorize_read(_scope(), _actor(), include_payload=False)
    assert result.granted is False
    assert result.decision_code == "AUTHZ_PERMISSION_NOT_GRANTED"


def test_detailed_audit_is_safe_and_idempotent_for_same_evaluation():
    audit = Audit()
    client = _client(audit=audit)
    first = client.authorize_start(_scope(), _actor())
    second = client.authorize_start(_scope(), _actor())
    assert first.provider_decision_reference == second.provider_decision_reference
    assert len(audit.by_key) == 1
    text = repr(audit.events)
    assert SUBJECT not in text and ISSUER not in text
    assert all(event.actor_id == SUBJECT_REF for event in audit.events)


def test_context_and_error_repr_are_redacted_and_immutable():
    context = _context(AuthorizationCheckpoint.START, _scope())
    error = TrustedAuthorizationContextError(TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID)
    assert SUBJECT not in repr(context) and TENANT not in repr(context)
    assert "raw" not in repr(error)
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        context.subject = "changed"
    with pytest.raises(AttributeError):
        error._code = TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_MISSING


def test_authorization_decision_reference_codec_matches_4_golden_vectors():
    codec = AuthorizationDecisionReferenceCodec()
    common = dict(
        policy_registry_version="1.0.0",
        tenant_policy_version=7,
        action_code="analysis.start",
        resource_version="rsv1:" + "a" * 64,
        principal_reference="srh1:k1:" + "b" * 64,
        membership_version=3,
        identity_resolved_at=datetime(2026, 8, 2, 10, 11, 12, 123456, tzinfo=UTC),
        policy_evaluated_at=datetime(2026, 8, 2, 10, 11, 13, 123456, tzinfo=UTC),
        audit_receipt_reference="ar1:" + "c" * 64,
        correlation_reference="cr1:" + "d" * 64,
    )
    vectors = (
        (AuthorizationAdapterDecisionCode.AUTHZ_ALLOWED, PolicyReasonCode.ALLOWED, AuditDeliveryState.DELIVERED, common["resource_version"], common["audit_receipt_reference"], "452ed9e0f9ede5b0c50aac48d9aacab07d497a769529de6bded94354b7b1ea8f"),
        (AuthorizationAdapterDecisionCode.AUTHZ_PERMISSION_NOT_GRANTED, PolicyReasonCode.PERMISSION_NOT_GRANTED, AuditDeliveryState.DELIVERED, common["resource_version"], common["audit_receipt_reference"], "61784854978384a5f9af72ee13eb34a55ddfb285c455bdb2ed6d2a344e8782d6"),
        (AuthorizationAdapterDecisionCode.AUDIT_REQUIRED_BUT_UNAVAILABLE, PolicyReasonCode.ALLOWED, AuditDeliveryState.FAILED_REQUIRED, common["resource_version"], None, "ef85e717b6c66ad123db259a159ff8dbdacbc70be2d1dc8c7a5566937d4f3364"),
        (AuthorizationAdapterDecisionCode.AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP, None, AuditDeliveryState.DELIVERED, None, common["audit_receipt_reference"], "105d9d963b13207ba4279690cd0ef08c725b9c6d06a53a815bb46196b0ed3151"),
    )
    for code, reason, audit_state, resource, receipt, digest in vectors:
        values = dict(common)
        values.update(decision_code=code, policy_reason=reason, audit_delivery=audit_state, resource_version=resource, audit_receipt_reference=receipt)
        assert codec.encode(**values) == "adr1:" + digest


def test_codec_is_deterministic_rejects_malformed_and_changes_with_audit_state():
    codec = AuthorizationDecisionReferenceCodec()
    values = dict(
        policy_registry_version="1.0.0", tenant_policy_version=None,
        action_code="analysis.start", decision_code=AuthorizationAdapterDecisionCode.AUTHZ_ALLOWED,
        policy_reason=PolicyReasonCode.ALLOWED, resource_version=None,
        principal_reference=None, membership_version=None, identity_resolved_at=None,
        policy_evaluated_at=NOW, audit_delivery=AuditDeliveryState.NOT_REQUIRED,
        audit_receipt_reference=None, correlation_reference="cr1:" + "d" * 64,
    )
    assert codec.encode(**values) == codec.encode(**values)
    changed = dict(values, audit_delivery=AuditDeliveryState.FAILED_REQUIRED)
    assert codec.encode(**values) != codec.encode(**changed)
    with pytest.raises(ValueError):
        codec.encode(**{**values, "unknown": "field"})
