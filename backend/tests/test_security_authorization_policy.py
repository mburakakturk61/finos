from __future__ import annotations

import enum
import inspect
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.security.authorization_policy import (
    ACTION_TO_OPERATION, BUILT_IN_ROLE_MATRIX, BUILT_IN_ROLE_MATRIX_DIGEST,
    COMPILED_SECURITY_ACTIONS, PERMISSION_REGISTRY_MANIFEST_DIGEST,
    POLICY_REASON_METADATA, RESOURCE_SCOPE_MANIFESTS, SECURITY_ACTION_REGISTRY,
    STEP7_LITERAL_CASES, STEP7_PRECEDENCE, STEP10_LITERAL_CASES,
    STEP10_PRECEDENCE, TOP_LEVEL_PRECEDENCE, AuthorizationPolicyEngine,
    EffectivePermissionSet, OwnershipRequirement, PolicyAuthenticationStrength,
    PolicyAuditRequirement, PolicyEvaluationConstructionError,
    PolicyEvaluationRequest, PolicyExistenceHiding, PolicyOperationKind,
    PolicyOutcome, PolicyReasonCode, PolicyRepositoryError,
    PolicyRepositoryErrorCode, PolicyScopeType, ResourceOwnershipState,
    ResourceSecurityReference, ResourceSecurityScope,
    ResourceSecurityVersionCodec, SubjectPredicateKind,
    SubjectReferenceHashCodec,
)
from app.security.contracts import (
    PERMISSION_REGISTRY_VERSION, IdentityKind, SecurityEntityStatus,
    VerifiedLocalIdentity,
)
from app.security.policy import BUILT_IN_ROLE_PERMISSIONS, PERMISSION_REGISTRY


NOW = datetime(2026, 8, 2, 10, 11, 12, 123456, tzinfo=timezone.utc)
TENANT = "acme-prod"


def _identity(kind: IdentityKind = IdentityKind.HUMAN) -> VerifiedLocalIdentity:
    membership = uuid.UUID("00000000-0000-0000-0000-000000000010")
    digest = "1" * 64
    roles = ("FINANCE_ANALYST",) if kind is IdentityKind.HUMAN else ("SERVICE_OPERATOR",)
    return VerifiedLocalIdentity(
        principal_id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
        principal_kind=kind,
        provider_issuer="https://issuer.example",
        provider_subject="user-123" if kind is IdentityKind.HUMAN else "svc-001",
        tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        tenant_key=TENANT,
        membership_id=membership,
        principal_status=SecurityEntityStatus.ACTIVE,
        tenant_status=SecurityEntityStatus.ACTIVE,
        binding_status=SecurityEntityStatus.ACTIVE,
        membership_status=SecurityEntityStatus.ACTIVE,
        authentication_context_subject="user-123" if kind is IdentityKind.HUMAN else "svc-001",
        authentication_context_tenant_key=TENANT,
        roles=roles,
        permission_resolution_reference=f"policy-ref/v1:1:{membership}:1:{PERMISSION_REGISTRY_VERSION}:{digest}",
        role_set_digest=digest,
        permission_registry_version=PERMISSION_REGISTRY_VERSION,
        tenant_policy_version=1,
        tokens_valid_after=NOW,
        membership_valid_from=NOW,
        membership_valid_until=None,
        principal_version=1,
        membership_version=1,
        resolved_at=NOW,
    )


def _effective(identity: VerifiedLocalIdentity, *permissions: str) -> EffectivePermissionSet:
    return EffectivePermissionSet(
        tuple(sorted(permissions)), identity.roles, identity.principal_kind,
        identity.membership_id, PERMISSION_REGISTRY_VERSION, 1, 1,
        identity.role_set_digest, NOW,
    )


class _Resources:
    def __init__(self, scope=None, error=None): self.scope, self.error = scope, error
    def resolve_durable_scope(self, **kwargs):
        if self.error: raise self.error
        return self.scope


class _Synthetic:
    def __init__(self, scope): self.scope = scope
    def resolve_system_scope(self, **kwargs): return self.scope
    def resolve_tenant_scope(self, **kwargs): return self.scope
    def resolve_company_period_scope(self, **kwargs): return self.scope


class _RouteSpy:
    def __init__(self, scope):
        self.scope = scope
        self.calls = []

    def resolve_durable_scope(self, **kwargs):
        self.calls.append(("durable", kwargs))
        return self.scope

    def resolve_system_scope(self, **kwargs):
        self.calls.append(("system", kwargs))
        return self.scope

    def resolve_tenant_scope(self, **kwargs):
        self.calls.append(("tenant", kwargs))
        return self.scope

    def resolve_company_period_scope(self, **kwargs):
        self.calls.append(("company_period", kwargs))
        return self.scope


def _scope(scope_type=PolicyScopeType.COMPANY, *, tenant=TENANT, owner=None, initiator=None):
    rid = uuid.UUID("00000000-0000-0000-0000-000000000002") if scope_type is not PolicyScopeType.ANALYSIS_RUN else "run-0001"
    ownership = ResourceOwnershipState.SUBJECT_OWNED if owner else ResourceOwnershipState.TENANT_OWNED
    return ResourceSecurityScope(scope_type, rid, tenant, uuid.UUID("00000000-0000-0000-0000-000000000002"), None, owner, initiator, "rsv1:" + "a" * 64, PolicyExistenceHiding.ALWAYS_HIDE_DENIAL, ownership, NOW)


def _request(action_code: str, identity: VerifiedLocalIdentity, scope: ResourceSecurityScope, *, strength=PolicyAuthenticationStrength.MFA, explicit=None, target=None):
    ref = ResourceSecurityReference(scope.resource_type, scope.resource_id, TENANT, None, None, None, "corr-0001", NOW)
    return PolicyEvaluationRequest(identity, strength, COMPILED_SECURITY_ACTIONS[action_code], ref, explicit, target, "corr-0001", NOW, PERMISSION_REGISTRY_VERSION, 1)


def _engine(scope, error=None):
    codec = SubjectReferenceHashCodec({"k1": bytes(range(32))}, active_key_version="k1")
    return AuthorizationPolicyEngine(resource_repository=_Resources(scope, error), synthetic_resolver=_Synthetic(scope), subject_codec=codec)


def test_closed_registry_and_manifest_counts():
    assert len(PERMISSION_REGISTRY) == len(COMPILED_SECURITY_ACTIONS) == 33
    assert SECURITY_ACTION_REGISTRY is COMPILED_SECURITY_ACTIONS
    assert len(PolicyScopeType) == 11
    assert len(PolicyReasonCode) == len(POLICY_REASON_METADATA) == 17
    assert len(PolicyRepositoryErrorCode) == 9
    assert len(BUILT_IN_ROLE_MATRIX) * len(PERMISSION_REGISTRY) == 198
    assert len(PERMISSION_REGISTRY_MANIFEST_DIGEST) == len(BUILT_IN_ROLE_MATRIX_DIGEST) == 64


@pytest.mark.parametrize("source,expected", tuple(ACTION_TO_OPERATION.items()))
def test_23_action_to_operation_mapping(source, expected):
    assert len(ACTION_TO_OPERATION) == 23
    assert ACTION_TO_OPERATION[source] is expected


@pytest.mark.parametrize("code,definition", tuple(PERMISSION_REGISTRY.items()))
def test_33_security_action_compiler(code, definition):
    action = COMPILED_SECURITY_ACTIONS[code]
    assert action.action_code == action.required_permission == code
    assert action.registry_version == PERMISSION_REGISTRY_VERSION
    assert action.operation_kind is ACTION_TO_OPERATION[definition.action]
    assert action.minimum_authentication_strength is {
        "BASIC": PolicyAuthenticationStrength.PASSWORD,
        "STRONG": PolicyAuthenticationStrength.MFA,
        "PHISHING_RESISTANT": PolicyAuthenticationStrength.PHISHING_RESISTANT,
    }[definition.minimum_authentication_strength.value]
    assert bool(action.allowed_principal_kinds)


def test_cancel_action_contract_is_exact():
    own = COMPILED_SECURITY_ACTIONS["analysis.cancel.own"]
    any_action = COMPILED_SECURITY_ACTIONS["analysis.cancel.any"]
    assert (own.ownership_requirement, own.subject_predicate_kind) == (OwnershipRequirement.RESOURCE_OWNER_REQUIRED, SubjectPredicateKind.NONE)
    assert (any_action.ownership_requirement, any_action.subject_predicate_kind) == (OwnershipRequirement.NONE, SubjectPredicateKind.NONE)


@pytest.mark.parametrize("role", tuple(BUILT_IN_ROLE_MATRIX))
@pytest.mark.parametrize("permission", tuple(PERMISSION_REGISTRY))
def test_198_built_in_role_permission_cells(role, permission):
    assert BUILT_IN_ROLE_MATRIX[role][permission] is (permission in BUILT_IN_ROLE_PERMISSIONS[role])


@pytest.mark.parametrize("reason", tuple(PolicyReasonCode))
def test_17_reason_metadata_is_reachable_and_closed(reason):
    metadata = POLICY_REASON_METADATA[reason]
    assert isinstance(metadata.outcome, PolicyOutcome)
    assert metadata.metric.startswith("security.policy.")
    assert metadata.message.endswith(".")


def test_precedence_and_literal_case_contracts():
    assert TOP_LEVEL_PRECEDENCE == tuple(range(1, 19))
    assert STEP7_PRECEDENCE == tuple(f"7.{i}" for i in range(1, 12))
    assert STEP10_PRECEDENCE == tuple(f"10.{i}" for i in range(1, 12))
    assert tuple(STEP7_LITERAL_CASES) == tuple(f"S7-{i:02d}" for i in range(1, 12))
    assert tuple(STEP10_LITERAL_CASES) == tuple(f"S10-{i:02d}" for i in range(1, 18))
    assert STEP10_LITERAL_CASES["S10-10"] is PolicyReasonCode.DATA_INTEGRITY_VIOLATION
    assert STEP10_LITERAL_CASES["S10-17"] is PolicyReasonCode.RESOURCE_NOT_FOUND


@pytest.mark.parametrize("case_id,reason", tuple(STEP7_LITERAL_CASES.items()))
def test_step7_11_literal_terminal_results(case_id, reason):
    metadata = POLICY_REASON_METADATA[reason]
    assert case_id.startswith("S7-")
    assert metadata.outcome is not PolicyOutcome.ALLOW
    assert metadata.metric.startswith("security.policy.")


@pytest.mark.parametrize("case_id,reason", tuple(STEP10_LITERAL_CASES.items()))
def test_step10_17_literal_terminal_results(case_id, reason):
    metadata = POLICY_REASON_METADATA[reason]
    assert case_id.startswith("S10-")
    assert metadata.outcome is not PolicyOutcome.ALLOW
    assert metadata.metric.startswith("security.policy.")


@pytest.mark.parametrize("value,tag,expected", [
    ("alpha","s","4112e5785dbe0fb93c2aa13bcfca060b62a74b7aad7aa51c1b0dbe92fec37584"),
    (uuid.UUID(int=1),"u","6aacdb03605c07fbad2a9141e65f78553daf6f40273725893b4197d024126050"),
    (SecurityEntityStatus.ACTIVE,"e","a31f9050ec3ede7944db6850c3ef40b3d6967b71552bf83f8b05e7170361b6da"),
    (None,"n","89a4f338911c932fe4db4b6b3dd5be4222660acba371199da5421b4269c3f514"),
    (NOW,"t","00611490784b6f1a6aadca6a59d53525267b0bf0965b5e10999d258fe2f6404f"),
    (date(2026,8,2),"d","36ee68bf8569cbd8ce25f03d2d5d8f9ac3d0429569baa2757ff08c3ac7044985"),
    (Decimal("123.4500"),"m","55a23f0ec3ae4ad34c622941b57cbe0308698a54c8505b6e77fd6d8a34adf339"),
    (bytes.fromhex("00abff"),"x","94a99ce187077f29745582368b84542a9def95b872fc012c127c40196b74b9bd"),
    (("ADMIN","VIEWER"),"q","38402b2c976a7107fc08c71fbac293c01e11ad3097102d986955465c4ae3498c"),
    (True,"b","51df15f75b55418adbce836d66ef79ce8e4d52cefaee2dbd7b07299414225164"),
    (42,"i","c6b2ad830110aab4798843c26848952187d4b0f5ade4d02c0e7074fe570d6f80"),
])
def test_11_primitive_codec_vectors(value, tag, expected):
    import hashlib
    assert hashlib.sha256(ResourceSecurityVersionCodec().primitive_bytes(value, tag)).hexdigest() == expected


def _ev(value):
    return enum.Enum("GoldenEnum", {"VALUE": value}).VALUE


@pytest.mark.parametrize("scope,values,expected", [
    (PolicyScopeType.SYSTEM,{"resource_type":PolicyScopeType.SYSTEM,"resource_id":"system"},"a3ecb7d79f55b74d888fcadd6d76ee9305e58db47a8e76f10e2d5d6ebece04a6"),
    (PolicyScopeType.TENANT,{"resource_type":PolicyScopeType.TENANT,"tenant_id":uuid.UUID(int=1),"tenant_key":TENANT,"tenant_policy_version":7},"93f4b52312fac4ad00c1bd053015b1b6a962e882721d8db0042926a4ad8cb0ef"),
    (PolicyScopeType.COMPANY,{"resource_type":PolicyScopeType.COMPANY,"id":uuid.UUID(int=2),"tenant_id":uuid.UUID(int=1),"updated_at":NOW},"a3db9c1b7cf50a6e6eeef3b40b6e776bf20c5fd26ce999c52882025186fbf619"),
    (PolicyScopeType.FINANCIAL_PERIOD,{"resource_type":PolicyScopeType.FINANCIAL_PERIOD,"id":uuid.UUID(int=3),"company_id":uuid.UUID(int=2),"status":_ev("active"),"updated_at":NOW.replace(second=13)},"f54c69b689d9e5964259a6c35c1a20bf2c93808ad30c643df8324605d0ad070c"),
    (PolicyScopeType.COMPANY_PERIOD,{"resource_type":PolicyScopeType.COMPANY_PERIOD,"resource_id":f"cp1:{uuid.UUID(int=2)}:{uuid.UUID(int=3)}","company_id":uuid.UUID(int=2),"period_id":uuid.UUID(int=3),"company_updated_at":NOW,"period_updated_at":NOW.replace(second=13)},"8f30f3ec03813156b2c34178d943c72e98f04d19ce6255ed97f379be593764eb"),
    (PolicyScopeType.DOCUMENT,{"resource_type":PolicyScopeType.DOCUMENT,"id":uuid.UUID(int=4),"company_id":uuid.UUID(int=2),"period_id":uuid.UUID(int=3),"checksum":bytes.fromhex("ab"*32),"processing_status":_ev("completed"),"processed_at":None},"0801567e7b6f0cc8dc3852559c43017ee0065ecd25b661a8684e418d61f7ae93"),
    (PolicyScopeType.ANALYSIS_RESULT,{"resource_type":PolicyScopeType.ANALYSIS_RESULT,"id":uuid.UUID(int=5),"company_id":uuid.UUID(int=2),"period_id":uuid.UUID(int=3),"status":_ev("completed"),"canonical_result_digest":bytes.fromhex("cd"*32),"completed_at":NOW.replace(second=13)},"342807b7d80b397780c4899d629626b5e0248646ff8c0c220bbc3b29b3ca4f50"),
    (PolicyScopeType.ANALYSIS_RUN,{"resource_type":PolicyScopeType.ANALYSIS_RUN,"claim_id":uuid.UUID(int=6),"run_id":"run-0001","company_id":uuid.UUID(int=2),"financial_period_id":uuid.UUID(int=3),"tenant_key":TENANT,"initiating_subject_reference":"srh1:k1:"+"1"*64,"claim_version":3,"claim_status":_ev("FINALIZED"),"terminal_content_digest":bytes.fromhex("de"*32)},"e3fd9fd4c37680fbc0a0c55fd8933d87361c7f9e0a794d0867790b3508165309"),
    (PolicyScopeType.EXECUTION,{"resource_type":PolicyScopeType.EXECUTION,"execution_id":uuid.UUID(int=7),"orchestration_run_id":uuid.UUID(int=5),"engine_code":_ev("ratio"),"status":_ev("completed"),"input_fingerprint":bytes.fromhex("ef"*32),"owner_content_digest":bytes.fromhex("12"*32),"claim_version":3},"614d4475e93d666f29c98126f11bde8e0e14433ba3897e9e4ecac7b2c3faa54a"),
    (PolicyScopeType.BULK_UPLOAD_BATCH,{"resource_type":PolicyScopeType.BULK_UPLOAD_BATCH,"id":uuid.UUID(int=8),"tenant_id":uuid.UUID(int=1),"status":_ev("confirmed"),"total_file_count":4,"classified_file_count":3,"unclassified_file_count":1,"duplicate_file_count":0,"completed_at":NOW,"confirmed_at":NOW.replace(second=13)},"5b8a92f2af244f261c8c92def8278a45a52eab2cadd315398cc0390c294b1ff1"),
    (PolicyScopeType.TRIAL_BALANCE,{"resource_type":PolicyScopeType.TRIAL_BALANCE,"id":uuid.UUID(int=9),"company_id":uuid.UUID(int=2),"period_id":uuid.UUID(int=3),"analysis_type":_ev("trial_balance"),"source_mode":_ev("direct_document"),"status":_ev("completed"),"canonical_result_digest":bytes.fromhex("34"*32),"completed_at":NOW.replace(second=13)},"baaf857709f5db9910435b5163e78a5beee7557efcc0f66c9f7fc3f9971d3614"),
])
def test_11_production_scope_codec_vectors(scope, values, expected):
    assert ResourceSecurityVersionCodec().scope_version(scope, values) == "rsv1:" + expected
    assert frozenset(RESOURCE_SCOPE_MANIFESTS) == frozenset(PolicyScopeType)


@pytest.mark.parametrize("version,key,issuer,tenant,kind,subject,expected", [
    ("k1",bytes(range(32)),"https://issuer.example",TENANT,IdentityKind.HUMAN,"user-123","b19854288ee4a03e964ef11d415fde4686984af36061d35ca3771409d85da075"),
    ("k1",bytes(range(32)),"https://issuer.example",TENANT,IdentityKind.SERVICE,"svc-001","60ebe899eda7444cddd848bab133e634f9641221e87c372c4dc94d11aef73706"),
    ("k1",bytes(range(32)),"https://issuer-2.example",TENANT,IdentityKind.HUMAN,"user-123","89228d9dedf55708c92d12a4f4a4ea6458b0ea9ee7c1d6424b6bfbeef7dab0f8"),
    ("k1",bytes(range(32)),"https://issuer.example","beta-prod",IdentityKind.HUMAN,"user-123","89d5323c398fc4240dc9919404dd1bf835d519b6435374a24e94094ccbadcdd1"),
    ("k2",bytes(range(32,64)),"https://issuer.example",TENANT,IdentityKind.HUMAN,"user-123","d32d5f23f8da4e1c0fd5ba4772afe0cd520740ae88b4fe26520fd110790892b7"),
])
def test_subject_reference_golden_vectors(version,key,issuer,tenant,kind,subject,expected):
    codec=SubjectReferenceHashCodec({version:key},active_key_version=version)
    assert codec.encode(issuer=issuer,tenant_key=tenant,principal_kind=kind,provider_subject=subject)==f"srh1:{version}:{expected}"


@pytest.mark.parametrize("code", tuple(PolicyRepositoryErrorCode))
def test_policy_repository_error_metadata_and_safety(code):
    error=PolicyRepositoryError(code=code,correlation_id="corr-0001",internal_cause=RuntimeError("postgres://secret token"))
    assert error.args==(error.safe_message,)
    assert "secret" not in str(error) and "secret" not in repr(error)
    assert "corr-0001" not in repr(error)
    with pytest.raises(AttributeError): error.code=code
    with pytest.raises(AttributeError): error.new_field=True
    with pytest.raises(AttributeError): del error._code


def test_policy_repository_error_is_final_and_signature_exact():
    assert tuple(inspect.signature(PolicyRepositoryError).parameters)==("code","correlation_id","internal_cause")
    with pytest.raises(TypeError):
        class Invalid(PolicyRepositoryError): pass
    with pytest.raises(TypeError): PolicyRepositoryError(code="STORE_TIMEOUT",correlation_id="corr-0001")


def test_policy_evaluation_construction_error_is_non_recursive_and_final():
    error=PolicyEvaluationConstructionError(correlation_id="corr-0001",internal_cause=RuntimeError("secret"))
    assert error.code=="POLICY_EVALUATION_CONSTRUCTION_FAILED" and "secret" not in repr(error)
    with pytest.raises(AttributeError): error.code="other"
    with pytest.raises(AttributeError): del error._code
    with pytest.raises(TypeError):
        class Invalid(PolicyEvaluationConstructionError): pass


def test_engine_allow_is_deterministic_and_only_emits_audit_intent():
    identity=_identity(); scope=_scope(); request=_request("company.read",identity,scope,strength=PolicyAuthenticationStrength.PASSWORD)
    engine=_engine(scope); permissions=_effective(identity,"company.read")
    first=engine.evaluate(request=request,effective_permissions=permissions)
    second=engine.evaluate(request=request,effective_permissions=permissions)
    assert first==second and first.outcome is PolicyOutcome.ALLOW
    assert first.audit_intent.event_name=="security.authorization.allow.allowed"
    assert not hasattr(engine,"security_audit_port")
    assert TENANT not in repr(first) and str(scope.resource_id) not in repr(first)
    assert TENANT not in repr(first.audit_intent)
    assert identity.provider_subject not in repr(first.audit_intent)


def test_engine_human_service_strength_axes_and_permission_safety():
    human=_identity(); scope=_scope(); action="company.read"
    assert _engine(scope).evaluate(request=_request(action,human,scope,strength=PolicyAuthenticationStrength.SERVICE_CREDENTIAL),effective_permissions=_effective(human,action)).reason_code is PolicyReasonCode.INSUFFICIENT_AUTHENTICATION_STRENGTH
    service=_identity(IdentityKind.SERVICE)
    result=_engine(scope).evaluate(request=_request(action,service,scope,strength=PolicyAuthenticationStrength.SERVICE_CREDENTIAL),effective_permissions=_effective(service,action))
    assert result.outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize(
    "predicate,explicit,target,owner,initiator,expected",
    [
        (SubjectPredicateKind.NONE, None, None, None, None, True),
        (SubjectPredicateKind.NONE, "user-123", None, None, None, None),
        (SubjectPredicateKind.SELF, None, "user-123", None, None, True),
        (SubjectPredicateKind.SELF, None, "other-user", None, None, False),
        (SubjectPredicateKind.SELF, None, None, None, None, None),
        (SubjectPredicateKind.INITIATOR, None, None, None, "user-123", True),
        (SubjectPredicateKind.INITIATOR, None, None, None, "other-user", False),
        (SubjectPredicateKind.INITIATOR, None, None, None, None, None),
        (SubjectPredicateKind.SAME_TENANT, None, None, None, None, True),
        (SubjectPredicateKind.SAME_TENANT, "user-123", None, None, None, None),
        (SubjectPredicateKind.EXPLICIT_SUBJECT_MATCH, "user-123", None, None, None, True),
        (SubjectPredicateKind.EXPLICIT_SUBJECT_MATCH, "other-user", None, None, None, False),
        (SubjectPredicateKind.EXPLICIT_SUBJECT_MATCH, None, None, None, None, None),
    ],
)
def test_subject_predicate_contract_is_closed(
    predicate, explicit, target, owner, initiator, expected
):
    identity = _identity()
    scope = _scope(owner=owner, initiator=initiator)
    base = _request("company.read", identity, scope, explicit=explicit, target=target)
    request = replace(base, action=replace(base.action, subject_predicate_kind=predicate))
    assert AuthorizationPolicyEngine._predicate(request, scope) is expected


@pytest.mark.parametrize("scope_type", tuple(PolicyScopeType))
def test_all_11_scopes_use_exact_engine_selected_resolver(scope_type):
    identity = _identity()
    company_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    period_id = uuid.UUID("00000000-0000-0000-0000-000000000003")
    if scope_type is PolicyScopeType.SYSTEM:
        resource_id, tenant_key, company, period, expected = (
            "system", None, None, None, "system"
        )
    elif scope_type is PolicyScopeType.TENANT:
        resource_id, tenant_key, company, period, expected = (
            TENANT, TENANT, None, None, "tenant"
        )
    elif scope_type is PolicyScopeType.COMPANY_PERIOD:
        resource_id, tenant_key, company, period, expected = (
            f"cp1:{company_id}:{period_id}", TENANT, company_id, period_id,
            "company_period",
        )
    elif scope_type is PolicyScopeType.ANALYSIS_RUN:
        resource_id, tenant_key, company, period, expected = (
            "run-0001", TENANT, None, None, "durable"
        )
    else:
        resource_id, tenant_key, company, period, expected = (
            uuid.UUID(int=20 + list(PolicyScopeType).index(scope_type)),
            TENANT, None, None, "durable",
        )
    reference = ResourceSecurityReference(
        scope_type, resource_id, tenant_key, company, period, None,
        "corr-0001", NOW,
    )
    request = PolicyEvaluationRequest(
        identity, PolicyAuthenticationStrength.MFA,
        COMPILED_SECURITY_ACTIONS["company.read"], reference,
        None, None, "corr-0001", NOW, PERMISSION_REGISTRY_VERSION, 1,
    )
    resolved = ResourceSecurityScope(
        scope_type, resource_id, tenant_key, company, period, None, None,
        "rsv1:" + "a" * 64, PolicyExistenceHiding.ALWAYS_HIDE_DENIAL,
        ResourceOwnershipState.SYSTEM_OWNED if scope_type is PolicyScopeType.SYSTEM
        else ResourceOwnershipState.TENANT_OWNED,
        NOW,
    )
    spy = _RouteSpy(resolved)
    engine = AuthorizationPolicyEngine(
        resource_repository=spy, synthetic_resolver=spy,
        subject_codec=SubjectReferenceHashCodec(
            {"k1": bytes(range(32))}, active_key_version="k1"
        ),
    )
    assert engine._resolve(request) is resolved
    assert [name for name, _kwargs in spy.calls] == [expected]


@pytest.mark.parametrize("reason", tuple(PolicyReasonCode))
def test_all_17_reasons_construct_deterministic_terminal_results(reason):
    identity = _identity()
    scope = _scope()
    request = _request(
        "company.read", identity, scope,
        strength=PolicyAuthenticationStrength.PASSWORD,
    )
    engine = _engine(scope)
    kwargs = {"scope": scope, "ownership": False, "predicate": False}
    if reason is PolicyReasonCode.ALLOWED:
        kwargs.update(ownership=True, predicate=True)
    first = engine._result(request, reason, **kwargs)
    second = engine._result(request, reason, **kwargs)
    assert first == second
    assert first.reason_code is reason
    assert first.outcome is POLICY_REASON_METADATA[reason].outcome
    assert first.audit_intent.event_name.endswith(reason.value.lower())


def test_owner_and_initiator_never_fallback():
    identity=_identity(); scope=_scope(PolicyScopeType.ANALYSIS_RUN,owner="other-user",initiator=identity.provider_subject)
    result=_engine(scope).evaluate(request=_request("analysis.cancel.own",identity,scope),effective_permissions=_effective(identity,"analysis.cancel.own"))
    assert result.reason_code is PolicyReasonCode.RESOURCE_OWNERSHIP_MISMATCH
    any_result=_engine(scope).evaluate(request=_request("analysis.cancel.any",identity,scope),effective_permissions=_effective(identity,"analysis.cancel.any"))
    assert any_result.outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize("error_code,reason", [
    (PolicyRepositoryErrorCode.STORE_TIMEOUT,PolicyReasonCode.POLICY_STORE_TIMEOUT),
    (PolicyRepositoryErrorCode.STORE_UNAVAILABLE,PolicyReasonCode.POLICY_STORE_UNAVAILABLE),
    (PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,PolicyReasonCode.DATA_INTEGRITY_VIOLATION),
    (PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND,PolicyReasonCode.RESOURCE_NOT_FOUND),
])
def test_store_and_model_a_fail_closed(error_code,reason):
    identity=_identity(); scope=_scope(); request=_request("company.read",identity,scope,strength=PolicyAuthenticationStrength.PASSWORD)
    error=PolicyRepositoryError(code=error_code,correlation_id="corr-0001")
    result=_engine(scope,error).evaluate(request=request,effective_permissions=_effective(identity,"company.read"))
    assert result.reason_code is reason and result.outcome is not PolicyOutcome.ALLOW
