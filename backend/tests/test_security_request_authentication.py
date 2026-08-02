from __future__ import annotations

import asyncio
import dataclasses
import inspect
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis_application.contracts import (
    ApplicationAuditContextDTO,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationScopeDTO,
)
from app.integrations.analysis_http.contracts import (
    ApiRuntimeProfile,
    AuthenticationContext,
    AuthenticationProviderUnavailable,
    AuthenticationStrength,
)
from app.integrations.analysis_http.router_security import (
    AuthenticationAuditEventType,
    RequestAuthenticationFactory,
    RouterAuthenticationError,
    RouterAuthenticationErrorCode,
)
from app.security.authorization_adapter import (
    AuthorizationCheckpoint,
    TrustedAuthorizationContext,
    TrustedAuthorizationContextError,
    TrustedAuthorizationContextErrorCode,
)
from app.security.authorization_policy import (
    PolicyAuthenticationStrength,
    PolicyScopeType,
    SubjectReferenceHashCodec,
)
from app.security.contracts import (
    CLAIMS_VERSION,
    IdentityKind,
    JwtAlgorithm,
    SecurityEntityStatus,
    VerifiedJwt,
    VerifiedLocalIdentity,
)
from app.security.request_authentication import (
    RequestAuthorizationPlan,
    RequestAuthorizationTarget,
    RequestBoundAuthenticationContextProvider,
    RequestBoundTrustedAuthorizationContextProvider,
    TrustedRequestIdentityProfile,
)


NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
TENANT = "tenant-alpha"
COMPANY = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PERIOD = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PRINCIPAL = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
MEMBERSHIP = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
TENANT_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def now_audit_time(self):
        return self.now

    def readiness_check(self, deadline):
        return deadline.tzinfo is not None


def identity(*, kind=IdentityKind.HUMAN, **changes):
    values = dict(
        principal_id=PRINCIPAL,
        principal_kind=kind,
        provider_issuer="https://issuer.example",
        provider_subject="subject-alpha",
        tenant_id=TENANT_ID,
        tenant_key=TENANT,
        membership_id=MEMBERSHIP,
        principal_status=SecurityEntityStatus.ACTIVE,
        tenant_status=SecurityEntityStatus.ACTIVE,
        binding_status=SecurityEntityStatus.ACTIVE,
        membership_status=SecurityEntityStatus.ACTIVE,
        authentication_context_subject="subject-alpha",
        authentication_context_tenant_key=TENANT,
        roles=("ANALYST",),
        permission_resolution_reference=(
            f"policy-ref/v1:7:{MEMBERSHIP}:3:1.0.0:{'a' * 64}"
        ),
        role_set_digest="a" * 64,
        permission_registry_version="1.0.0",
        tenant_policy_version=7,
        tokens_valid_after=NOW - timedelta(minutes=10),
        membership_valid_from=NOW - timedelta(minutes=10),
        membership_valid_until=None,
        principal_version=2,
        membership_version=3,
        resolved_at=NOW - timedelta(minutes=1),
    )
    values.update(changes)
    return VerifiedLocalIdentity(**values)


def token(*, kind=IdentityKind.HUMAN, strength=AuthenticationStrength.STRONG, **changes):
    values = dict(
        issuer="https://issuer.example",
        subject="subject-alpha",
        tenant_key=TENANT,
        token_kind=kind,
        audience=("api",),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
        not_before=None,
        jti="1234567890abcdef",
        claims_version=CLAIMS_VERSION,
        authentication_strength=strength,
        kid="key-1",
        algorithm=JwtAlgorithm.RS256,
        service_client_id="service-client" if kind is IdentityKind.SERVICE else None,
    )
    values.update(changes)
    return VerifiedJwt(**values)


def auth_provider(*, kind=IdentityKind.HUMAN, strength=AuthenticationStrength.STRONG, profile=ApiRuntimeProfile.TEST):
    return RequestBoundAuthenticationContextProvider(
        verified_token=token(kind=kind, strength=strength),
        verified_identity=identity(kind=kind),
        correlation_id="corr-001",
        request_id="request-001",
        runtime_profile=profile,
    )


class AuthenticationVerifier:
    trusted_issuers = frozenset({"https://issuer.example"})

    def verify(self, _raw, *, now):
        assert now == NOW
        return token()

    def readiness_check(self, deadline):
        return deadline.tzinfo is not None


class AuthenticationIdentities:
    def resolve_principal_and_membership(self, **_kwargs):
        return identity()

    def readiness_check(self, deadline):
        return deadline.tzinfo is not None


class AuthenticationAudit:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.events = []

    def record_required_event(self, event):
        self.events.append(event)
        if self.fail:
            raise RuntimeError("secret audit outage")
        return object()

    def readiness_check(self, deadline):
        return not self.fail and deadline.tzinfo is not None


def authentication_factory(*, audit_sink=None):
    return RequestAuthenticationFactory(
        verifier=AuthenticationVerifier(),
        identity_repository=AuthenticationIdentities(),
        security_audit=audit_sink or AuthenticationAudit(),
        clock=Clock(),
        subject_codec=SubjectReferenceHashCodec(
            {"k1": b"s" * 32}, active_key_version="k1",
        ),
        runtime_profile=ApiRuntimeProfile.PRODUCTION,
    )


def test_request_authentication_success_and_failure_are_required_audited_and_redacted():
    success_audit = AuthenticationAudit()
    provider = authentication_factory(audit_sink=success_audit).authenticate(
        authorization_headers=("Bearer compact-token",),
        correlation_id="corr-001", request_id="request-001",
    )
    assert provider.current_context().subject_id == "subject-alpha"
    success = success_audit.events[0]
    assert success.event_type == AuthenticationAuditEventType.AUTHENTICATION_SUCCEEDED.value
    success_attributes = dict(success.safe_attributes)
    assert success_attributes["subject_reference"].startswith("srh1:k1:")
    assert "subject-alpha" not in repr(success)
    assert "compact-token" not in repr(success)

    failed_audit = AuthenticationAudit()
    with pytest.raises(RouterAuthenticationError) as caught:
        authentication_factory(audit_sink=failed_audit).authenticate(
            authorization_headers=(), correlation_id="corr-001",
            request_id="request-001",
        )
    assert caught.value.code is RouterAuthenticationErrorCode.MISSING
    failed = failed_audit.events[0]
    assert failed.event_type == AuthenticationAuditEventType.AUTHENTICATION_FAILED.value
    assert "subject_reference" not in dict(failed.safe_attributes)


def test_authentication_audit_outage_is_fail_closed_provider_unavailable():
    with pytest.raises(RouterAuthenticationError) as caught:
        authentication_factory(audit_sink=AuthenticationAudit(fail=True)).authenticate(
            authorization_headers=(), correlation_id="corr-001",
            request_id="request-001",
        )
    assert caught.value.code is RouterAuthenticationErrorCode.UNAVAILABLE


def cp_target(checkpoint=AuthorizationCheckpoint.START, **changes):
    values = dict(
        checkpoint=checkpoint,
        scope_type=PolicyScopeType.COMPANY_PERIOD,
        resource_id=f"cp1:{COMPANY}:{PERIOD}",
        tenant_key=TENANT,
        company_id=COMPANY,
        period_id=PERIOD,
    )
    values.update(changes)
    return RequestAuthorizationTarget(**values)


def run_target(checkpoint=AuthorizationCheckpoint.READ, run_id="run-001", **changes):
    values = dict(
        checkpoint=checkpoint,
        scope_type=PolicyScopeType.ANALYSIS_RUN,
        resource_id=run_id,
        tenant_key=TENANT,
    )
    values.update(changes)
    return RequestAuthorizationTarget(**values)


def scope(**changes):
    values = dict(
        company_id=COMPANY,
        financial_period_id=PERIOD,
        tenant_id=TENANT,
        operation_kind=ApplicationOperationKind.START,
        original_operation=ApplicationOriginalOperation.START,
    )
    values.update(changes)
    return ApplicationScopeDTO(**values)


def audit():
    return ApplicationAuditContextDTO("srh1:k1:" + "a" * 64, "HUMAN", "API", "analysis")


def bridge(*, provider=None, targets=None, clock=None, profile=ApiRuntimeProfile.TEST, issuers=None):
    return RequestBoundTrustedAuthorizationContextProvider(
        authentication_provider=provider or auth_provider(profile=profile),
        authorization_plan=RequestAuthorizationPlan(tuple(targets or (cp_target(),))),
        trusted_issuers=issuers or frozenset({"https://issuer.example"}),
        clock=clock or Clock(),
        runtime_profile=profile,
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (AuthenticationStrength.BASIC, PolicyAuthenticationStrength.PASSWORD),
        (AuthenticationStrength.STRONG, PolicyAuthenticationStrength.MFA),
        (AuthenticationStrength.PHISHING_RESISTANT, PolicyAuthenticationStrength.PHISHING_RESISTANT),
    ),
)
def test_valid_human_strength_mapping(source, expected):
    result = bridge(provider=auth_provider(strength=source)).resolve_context(
        checkpoint=AuthorizationCheckpoint.START,
        application_scope=scope(),
        audit_context=audit(),
    )
    assert isinstance(result, TrustedAuthorizationContext)
    assert result.expected_principal_kind is IdentityKind.HUMAN
    assert result.authentication_strength is expected
    assert result.service_client_id is None


def test_valid_service_mapping_is_separate_from_human_strength_axis():
    result = bridge(provider=auth_provider(kind=IdentityKind.SERVICE)).resolve_context(
        checkpoint=AuthorizationCheckpoint.START,
        application_scope=scope(),
        audit_context=audit(),
    )
    assert result.expected_principal_kind is IdentityKind.SERVICE
    assert result.authentication_strength is PolicyAuthenticationStrength.SERVICE_CREDENTIAL
    assert result.service_client_id == "service-client"


@pytest.mark.parametrize(
    "token_change",
    (
        {"issuer": "https://other.example"},
        {"subject": "other-subject"},
        {"tenant_key": "other-tenant"},
        {"token_kind": IdentityKind.SERVICE, "service_client_id": "service-client"},
    ),
)
def test_verified_token_and_local_identity_binding_is_exact(token_change):
    with pytest.raises(ValueError):
        RequestBoundAuthenticationContextProvider(
            verified_token=token(**token_change),
            verified_identity=identity(),
            correlation_id="corr-001",
            request_id="request-001",
            runtime_profile=ApiRuntimeProfile.TEST,
        )


def test_service_client_and_strength_are_fail_closed():
    for invalid in (
        token(kind=IdentityKind.SERVICE, service_client_id=None),
        token(kind=IdentityKind.SERVICE, strength=AuthenticationStrength.BASIC),
    ):
        with pytest.raises(ValueError):
            RequestBoundAuthenticationContextProvider(
                verified_token=invalid,
                verified_identity=identity(kind=IdentityKind.SERVICE),
                correlation_id="corr-001",
                request_id="request-001",
                runtime_profile=ApiRuntimeProfile.TEST,
            )


class ProviderDouble:
    runtime_profile = ApiRuntimeProfile.TEST
    is_fake = False
    is_request_bound = True

    def __init__(self, context, profile=None, error=None):
        self.context = context
        self.profile = profile or TrustedRequestIdentityProfile(IdentityKind.HUMAN, None, "request-001")
        self.error = error

    def current_context(self):
        if self.error:
            raise self.error
        return self.context

    def trusted_identity_profile(self):
        return self.profile

    def readiness_check(self, deadline):
        return self.error is None


@pytest.mark.parametrize(
    ("context", "expected"),
    (
        (None, TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_MISSING),
        (object(), TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID),
    ),
)
def test_missing_and_malformed_context_are_fail_closed(context, expected):
    with pytest.raises(TrustedAuthorizationContextError) as caught:
        bridge(provider=ProviderDouble(context)).resolve_context(
            checkpoint=AuthorizationCheckpoint.START,
            application_scope=scope(),
            audit_context=audit(),
        )
    assert caught.value.code is expected


@pytest.mark.parametrize("error", (AuthenticationProviderUnavailable("safe"), TimeoutError(), ConnectionError()))
def test_provider_outage_is_fail_closed_and_safe(error):
    with pytest.raises(TrustedAuthorizationContextError) as caught:
        bridge(provider=ProviderDouble(None, error=error)).resolve_context(
            checkpoint=AuthorizationCheckpoint.START,
            application_scope=scope(),
            audit_context=audit(),
        )
    assert caught.value.code is TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_PROVIDER_UNAVAILABLE
    assert "token" not in repr(caught.value).lower()


@pytest.mark.parametrize(
    ("change", "expected"),
    (
        ({"expires_at": NOW}, TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_EXPIRED),
        ({"issued_at": NOW - timedelta(minutes=15, microseconds=1)}, TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_STALE),
        ({"issued_at": NOW + timedelta(seconds=60, microseconds=1)}, TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID),
    ),
)
def test_freshness_expiry_and_future_skew_are_closed(change, expected):
    context = dataclasses.replace(auth_provider().current_context(), **change)
    with pytest.raises(TrustedAuthorizationContextError) as caught:
        bridge(provider=ProviderDouble(context)).resolve_context(
            checkpoint=AuthorizationCheckpoint.START,
            application_scope=scope(),
            audit_context=audit(),
        )
    assert caught.value.code is expected


def test_exact_freshness_and_future_skew_boundaries_are_accepted():
    for issued in (NOW - timedelta(minutes=15), NOW + timedelta(seconds=60)):
        context = dataclasses.replace(auth_provider().current_context(), issued_at=issued)
        result = bridge(provider=ProviderDouble(context)).resolve_context(
            checkpoint=AuthorizationCheckpoint.START,
            application_scope=scope(),
            audit_context=audit(),
        )
        assert result.token_issued_at == issued


def test_plan_is_unique_canonical_and_checkpoint_scoped():
    with pytest.raises(ValueError):
        RequestAuthorizationPlan((cp_target(), cp_target()))
    with pytest.raises(ValueError):
        RequestAuthorizationPlan((cp_target(AuthorizationCheckpoint.PRE_PERSIST_START), cp_target()))
    with pytest.raises(ValueError):
        run_target(AuthorizationCheckpoint.START)
    with pytest.raises(TrustedAuthorizationContextError) as caught:
        bridge().resolve_context(
            checkpoint=AuthorizationCheckpoint.PRE_PERSIST_START,
            application_scope=scope(),
            audit_context=audit(),
        )
    assert caught.value.code is TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_INVALID


def test_scope_and_target_binding_are_fail_closed():
    wrong_company = uuid.uuid4()
    cases = (
        (bridge(), scope(tenant_id="other-tenant")),
        (bridge(targets=(cp_target(
            company_id=wrong_company,
            resource_id=f"cp1:{wrong_company}:{PERIOD}",
        ),)), scope()),
    )
    for provider, application_scope in cases:
        with pytest.raises((TrustedAuthorizationContextError, ValueError)):
            provider.resolve_context(
                checkpoint=AuthorizationCheckpoint.START,
                application_scope=application_scope,
                audit_context=audit(),
            )


def test_same_checkpoint_is_deterministic_and_pre_persist_is_fresh():
    clock = Clock()
    provider = bridge(
        clock=clock,
        targets=(
            cp_target(AuthorizationCheckpoint.START),
            cp_target(AuthorizationCheckpoint.PRE_PERSIST_START),
        ),
    )
    initial = provider.resolve_context(
        checkpoint=AuthorizationCheckpoint.START, application_scope=scope(), audit_context=audit()
    )
    clock.now = NOW + timedelta(minutes=1)
    assert provider.resolve_context(
        checkpoint=AuthorizationCheckpoint.START, application_scope=scope(), audit_context=audit()
    ) is initial
    final = provider.resolve_context(
        checkpoint=AuthorizationCheckpoint.PRE_PERSIST_START,
        application_scope=scope(), audit_context=audit(),
    )
    assert final.resolved_at == NOW + timedelta(minutes=1)
    assert final is not initial


def test_changed_authentication_snapshot_is_integrity_failure():
    underlying = ProviderDouble(auth_provider().current_context())
    provider = bridge(
        provider=underlying,
        targets=(
            cp_target(AuthorizationCheckpoint.START),
            cp_target(AuthorizationCheckpoint.PRE_PERSIST_START),
        ),
    )
    provider.resolve_context(
        checkpoint=AuthorizationCheckpoint.START, application_scope=scope(), audit_context=audit()
    )
    underlying.context = dataclasses.replace(underlying.context, subject_id="other-subject")
    with pytest.raises(TrustedAuthorizationContextError) as caught:
        provider.resolve_context(
            checkpoint=AuthorizationCheckpoint.PRE_PERSIST_START,
            application_scope=scope(), audit_context=audit(),
        )
    assert caught.value.code is TrustedAuthorizationContextErrorCode.AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION


def test_concurrent_same_request_materializes_one_context():
    provider = bridge()
    barrier = threading.Barrier(12)
    results = []

    def resolve():
        barrier.wait()
        results.append(provider.resolve_context(
            checkpoint=AuthorizationCheckpoint.START,
            application_scope=scope(), audit_context=audit(),
        ))

    threads = [threading.Thread(target=resolve) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 12
    assert len({id(value) for value in results}) == 1


def test_async_tasks_share_only_the_explicit_request_provider():
    provider = bridge()

    async def run():
        return await asyncio.gather(*(
            asyncio.to_thread(
                provider.resolve_context,
                checkpoint=AuthorizationCheckpoint.START,
                application_scope=scope(),
                audit_context=audit(),
            )
            for _ in range(8)
        ))

    results = asyncio.run(run())
    assert len({id(value) for value in results}) == 1


def test_separate_request_providers_cannot_contaminate_each_other():
    first = bridge()
    second_auth = ProviderDouble(dataclasses.replace(
        auth_provider().current_context(),
        subject_id="subject-beta",
        correlation_id="corr-002",
    ))
    second = bridge(provider=second_auth)
    one = first.resolve_context(
        checkpoint=AuthorizationCheckpoint.START, application_scope=scope(), audit_context=audit()
    )
    two = second.resolve_context(
        checkpoint=AuthorizationCheckpoint.START, application_scope=scope(), audit_context=audit()
    )
    assert one.subject != two.subject
    assert "subject-alpha" not in repr(first)
    assert "subject-beta" not in repr(second)


class FakeProductionProvider(ProviderDouble):
    runtime_profile = ApiRuntimeProfile.PRODUCTION
    is_fake = True


def test_production_rejects_fake_or_non_request_bound_provider():
    context = auth_provider().current_context()
    with pytest.raises(ValueError):
        bridge(provider=FakeProductionProvider(context), profile=ApiRuntimeProfile.PRODUCTION)
    unsafe = ProviderDouble(context)
    unsafe.runtime_profile = ApiRuntimeProfile.PRODUCTION
    unsafe.is_request_bound = False
    with pytest.raises(ValueError):
        bridge(provider=unsafe, profile=ApiRuntimeProfile.PRODUCTION)


def test_production_provider_readiness_is_fail_closed():
    provider = auth_provider(profile=ApiRuntimeProfile.PRODUCTION)
    ready = bridge(provider=provider, profile=ApiRuntimeProfile.PRODUCTION)
    assert ready.readiness_check(NOW + timedelta(seconds=1)) is True
    unavailable = ProviderDouble(provider.current_context(), error=AuthenticationProviderUnavailable("safe"))
    unavailable.runtime_profile = ApiRuntimeProfile.PRODUCTION
    assert bridge(provider=unavailable, profile=ApiRuntimeProfile.PRODUCTION).readiness_check(NOW) is False


def test_context_plan_and_profile_are_immutable_and_redacted():
    provider = auth_provider()
    profile = provider.trusted_identity_profile()
    plan = RequestAuthorizationPlan((run_target(),))
    for value in (profile, plan, plan.targets[0]):
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            value.request_id = "changed"
    rendered = repr(provider) + repr(profile) + repr(plan.targets[0])
    assert "subject-alpha" not in rendered
    assert "service-client" not in rendered
    assert "run-001" not in rendered


def test_step12_contract_has_no_raw_credential_or_global_identity_surface():
    source = inspect.getsource(__import__(
        "app.security.request_authentication", fromlist=["request_authentication"]
    )).lower()
    for forbidden in ("contextvar", "threading.local", "x-user-id", "x-tenant-id", "authorization header"):
        assert forbidden not in source
    fields = {
        item.name
        for contract in (TrustedRequestIdentityProfile, RequestAuthorizationTarget)
        for item in dataclasses.fields(contract)
    }
    assert not fields & {"raw_token", "token", "claims", "headers", "email", "display_name"}


def test_correlation_request_and_resource_binding_match_step11_contract():
    result = bridge(targets=(run_target(),)).resolve_context(
        checkpoint=AuthorizationCheckpoint.READ,
        application_scope=scope(),
        audit_context=audit(),
    )
    assert isinstance(result, TrustedAuthorizationContext)
    assert result.correlation_id == "corr-001"
    assert result.request_id == "request-001"
    assert result.resource_reference.scope_type is PolicyScopeType.ANALYSIS_RUN
    assert result.resource_reference.resource_id == "run-001"
    assert result.authorization_context_reference == f"authz:v1:H:{MEMBERSHIP}:3:7"
