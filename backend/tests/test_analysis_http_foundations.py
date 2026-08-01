from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app.integrations.analysis_http.admission import ProcessLocalAnalysisAdmissionControl
from app.integrations.analysis_http.contracts import (
    ApiRuntimeProfile,
    AuthenticationContext,
    AuthenticationContextError,
    AuthenticationStrength,
)
from app.integrations.analysis_http.cursor import CursorKeyring, HmacCursorCodec, InvalidCursor
from app.integrations.analysis_http.runtime import (
    ProductionCompositionError,
    ProductionIntegrationBindings,
    validate_runtime_bindings,
)
from app.integrations.analysis_http.security import (
    StaticAuthenticationContextProvider,
    validate_authentication_context,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _context(**changes):
    values = dict(
        subject_id="subject-a", tenant_id="tenant-a", authentication_method="oidc",
        authentication_strength=AuthenticationStrength.STRONG,
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=5),
        correlation_id="corr-a", claims_version="1", trusted_issuer="issuer-a",
        authorization_context_reference="auth-ref",
    )
    values.update(changes)
    return AuthenticationContext(**values)


def test_authentication_context_freshness_and_trust_are_fail_closed():
    assert validate_authentication_context(
        _context(), correlation_id="corr-a", trusted_issuers=frozenset({"issuer-a"}), now=NOW,
    ).subject_id == "subject-a"
    invalid = (
        _context(issued_at=NOW + timedelta(seconds=61)),
        _context(issued_at=NOW - timedelta(minutes=16)),
        _context(expires_at=NOW),
        _context(trusted_issuer="attacker"),
        _context(correlation_id="wrong"),
    )
    for context in invalid:
        with pytest.raises(AuthenticationContextError):
            validate_authentication_context(
                context, correlation_id="corr-a", trusted_issuers=frozenset({"issuer-a"}), now=NOW,
            )


def test_static_authentication_adapter_is_forbidden_in_production():
    with pytest.raises(ValueError):
        StaticAuthenticationContextProvider(_context(), ApiRuntimeProfile.PRODUCTION)


def test_admission_enforces_global_tenant_and_releases_idempotently():
    admission = ProcessLocalAnalysisAdmissionControl(
        global_limit=2, tenant_limit=1, subject_limit=1, retry_after_seconds=5,
    )
    first = admission.try_acquire(
        tenant_id="tenant-a", subject_id="subject-a", run_id="run-a", acquired_at=NOW,
    )
    assert first is not None
    assert admission.try_acquire(
        tenant_id="tenant-a", subject_id="subject-b", run_id="run-b", acquired_at=NOW,
    ) is None
    second = admission.try_acquire(
        tenant_id="tenant-b", subject_id="subject-b", run_id="run-c", acquired_at=NOW,
    )
    assert second is not None
    assert admission.try_acquire(
        tenant_id="tenant-c", subject_id="subject-c", run_id="run-d", acquired_at=NOW,
    ) is None
    admission.release(first)
    admission.release(first)
    assert admission.try_acquire(
        tenant_id="tenant-a", subject_id="subject-b", run_id="run-e", acquired_at=NOW,
    ) is not None


def test_hmac_cursor_is_scope_bound_expiring_and_rotation_safe():
    company_id, period_id = uuid.uuid4(), uuid.uuid4()
    keys = {"active": b"a" * 32, "retired": b"b" * 32}
    codec = HmacCursorCodec(CursorKeyring("active", keys, frozenset({"retired"})))
    cursor = codec.encode(
        internal_cursor="internal", tenant_id="tenant-a", company_id=company_id,
        financial_period_id=period_id, now=NOW,
    )
    assert codec.decode(
        cursor, tenant_id="tenant-a", company_id=company_id,
        financial_period_id=period_id, now=NOW,
    ) == "internal"
    for kwargs in (
        {"tenant_id": "tenant-b", "now": NOW},
        {"tenant_id": "tenant-a", "now": NOW + timedelta(hours=25)},
    ):
        with pytest.raises(InvalidCursor):
            codec.decode(
                cursor, company_id=company_id, financial_period_id=period_id, **kwargs,
            )
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    with pytest.raises(InvalidCursor):
        codec.decode(
            tampered, tenant_id="tenant-a", company_id=company_id,
            financial_period_id=period_id, now=NOW,
        )


class _Unsafe:
    is_fake = True


def test_production_composition_rejects_fake_or_missing_binding():
    bindings = ProductionIntegrationBindings(*([object()] * 9))
    with pytest.raises(ProductionCompositionError):
        validate_runtime_bindings(ApiRuntimeProfile.PRODUCTION, bindings)
    unsafe = ProductionIntegrationBindings(_Unsafe(), *([object()] * 8))
    with pytest.raises(ProductionCompositionError):
        validate_runtime_bindings(ApiRuntimeProfile.PRODUCTION, unsafe)
