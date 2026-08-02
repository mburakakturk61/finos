"""Authoritative PostgreSQL identity resolution for Milestone 5.0E Step 9."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select, text
from sqlalchemy.exc import (
    DataError,
    DisconnectionError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SqlAlchemyTimeoutError,
)

from app.models.security import (
    SecurityMembership,
    SecurityMembershipRole,
    SecurityPermission,
    SecurityPrincipal,
    SecurityRole,
    SecurityRolePermission,
    SecuritySubjectBinding,
    SecurityTenant,
)
from app.security.contracts import (
    PERMISSION_REGISTRY_VERSION,
    SAFE_CORRELATION_PATTERN,
    SERVICE_CLIENT_PATTERN,
    SUBJECT_PATTERN,
    TENANT_KEY_PATTERN,
    IdentityKind,
    IdentityResolutionError,
    IdentityResolutionErrorCode,
    SecurityEntityStatus,
    VerifiedLocalIdentity,
)


class SqlAlchemySecurityIdentityRepository:
    """Resolve one identity from one short read-only PostgreSQL snapshot."""

    def __init__(self, session_factory, *, statement_timeout_seconds: float = 2.0) -> None:
        if not 0 < statement_timeout_seconds <= 3:
            raise ValueError("Identity repository timeout must be in (0, 3] seconds.")
        self._sessions = session_factory
        self._statement_timeout_ms = max(1, int(statement_timeout_seconds * 1000))

    def resolve_principal_and_membership(
        self,
        *,
        issuer: str,
        subject: str,
        tenant_key: str,
        token_issued_at: datetime,
        expected_principal_kind: IdentityKind,
        expected_service_client_id: str | None,
        correlation_id: str,
        request_id: str,
        now: datetime,
    ) -> VerifiedLocalIdentity:
        safe_correlation = correlation_id if _safe_id(correlation_id) else None
        try:
            token_time, resolution_time = self._validate_input(
                issuer=issuer,
                subject=subject,
                tenant_key=tenant_key,
                token_issued_at=token_issued_at,
                expected_principal_kind=expected_principal_kind,
                expected_service_client_id=expected_service_client_id,
                correlation_id=correlation_id,
                request_id=request_id,
                now=now,
            )
        except (TypeError, ValueError):
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.NONCANONICAL_IDENTITY_INPUT,
                correlation_id=safe_correlation,
            ) from None

        try:
            with self._sessions() as session, session.begin():
                session.execute(text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                ))
                session.execute(
                    text("SELECT set_config('statement_timeout', :value, true)"),
                    {"value": f"{self._statement_timeout_ms}ms"},
                )
                return self._resolve_snapshot(
                    session,
                    issuer=issuer,
                    subject=subject,
                    tenant_key=tenant_key,
                    token_issued_at=token_time,
                    expected_principal_kind=expected_principal_kind,
                    expected_service_client_id=expected_service_client_id,
                    correlation_id=safe_correlation,
                    now=resolution_time,
                )
        except IdentityResolutionError:
            raise
        except SqlAlchemyTimeoutError:
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.IDENTITY_STORE_TIMEOUT,
                correlation_id=safe_correlation,
            ) from None
        except (DataError, IntegrityError):
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION,
                correlation_id=safe_correlation,
            ) from None
        except (OperationalError, InterfaceError, DisconnectionError, SQLAlchemyError):
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.IDENTITY_STORE_UNAVAILABLE,
                correlation_id=safe_correlation,
            ) from None
        except (KeyError, TypeError, ValueError):
            raise IdentityResolutionError(
                IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION,
                correlation_id=safe_correlation,
            ) from None

    def readiness_check(self, deadline: datetime) -> bool:
        if not isinstance(deadline, datetime) or deadline.tzinfo is None or deadline.utcoffset() is None:
            return False
        try:
            with self._sessions() as session, session.begin():
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(
                    text("SELECT set_config('statement_timeout', :value, true)"),
                    {"value": f"{self._statement_timeout_ms}ms"},
                )
                return session.scalar(text("SELECT 1")) == 1
        except Exception:
            return False

    @staticmethod
    def _validate_input(
        *,
        issuer: str,
        subject: str,
        tenant_key: str,
        token_issued_at: datetime,
        expected_principal_kind: IdentityKind,
        expected_service_client_id: str | None,
        correlation_id: str,
        request_id: str,
        now: datetime,
    ) -> tuple[datetime, datetime]:
        if not _canonical_issuer(issuer):
            raise ValueError("issuer")
        if not isinstance(subject, str) or not SUBJECT_PATTERN.fullmatch(subject):
            raise ValueError("subject")
        if not isinstance(tenant_key, str) or not TENANT_KEY_PATTERN.fullmatch(tenant_key):
            raise ValueError("tenant")
        if not isinstance(expected_principal_kind, IdentityKind):
            raise ValueError("kind")
        if not _safe_id(correlation_id) or not _safe_id(request_id):
            raise ValueError("request")
        if expected_principal_kind is IdentityKind.HUMAN:
            if expected_service_client_id is not None:
                raise ValueError("client")
        elif (
            not isinstance(expected_service_client_id, str)
            or not SERVICE_CLIENT_PATTERN.fullmatch(expected_service_client_id)
        ):
            raise ValueError("client")
        return _to_utc(token_issued_at), _to_utc(now)

    def _resolve_snapshot(
        self,
        session,
        *,
        issuer: str,
        subject: str,
        tenant_key: str,
        token_issued_at: datetime,
        expected_principal_kind: IdentityKind,
        expected_service_client_id: str | None,
        correlation_id: str | None,
        now: datetime,
    ) -> VerifiedLocalIdentity:
        # 2. Canonical tenant resolution.
        tenants = tuple(session.scalars(
            select(SecurityTenant).where(SecurityTenant.tenant_key == tenant_key)
        ))
        if not tenants:
            self._fail(IdentityResolutionErrorCode.TENANT_NOT_FOUND, correlation_id)
        if len(tenants) != 1:
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)
        tenant = tenants[0]

        # 3. Exact issuer + subject binding resolution, including revoked rows.
        bindings = tuple(session.scalars(select(SecuritySubjectBinding).where(
            SecuritySubjectBinding.issuer == issuer,
            SecuritySubjectBinding.subject == subject,
        )))
        if not bindings:
            self._fail(IdentityResolutionErrorCode.IDENTITY_NOT_FOUND, correlation_id)
        if len(bindings) != 1:
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)
        binding = bindings[0]

        # 4. Binding FK principal resolution.
        principal = session.get(SecurityPrincipal, binding.principal_id)
        if principal is None:
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)

        # 5. Token profile/client versus authoritative local principal kind.
        try:
            principal_kind = IdentityKind(principal.kind)
        except (TypeError, ValueError):
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)
        if principal_kind is not expected_principal_kind:
            self._fail(IdentityResolutionErrorCode.PRINCIPAL_KIND_MISMATCH, correlation_id)
        if principal_kind is IdentityKind.HUMAN:
            if binding.service_client_id is not None:
                self._fail(IdentityResolutionErrorCode.PRINCIPAL_KIND_MISMATCH, correlation_id)
        elif binding.service_client_id != expected_service_client_id:
            self._fail(IdentityResolutionErrorCode.PRINCIPAL_KIND_MISMATCH, correlation_id)

        # 6-8. State precedence is tenant, principal, then binding.
        if tenant.status != SecurityEntityStatus.ACTIVE.value:
            self._fail(IdentityResolutionErrorCode.TENANT_INACTIVE, correlation_id)
        if principal.status != SecurityEntityStatus.ACTIVE.value:
            self._fail(IdentityResolutionErrorCode.PRINCIPAL_INACTIVE, correlation_id)
        if binding.status != SecurityEntityStatus.ACTIVE.value:
            self._fail(IdentityResolutionErrorCode.SUBJECT_BINDING_INACTIVE, correlation_id)

        # 9-10. Relational scope integrity and exact membership resolution.
        memberships = tuple(session.scalars(select(SecurityMembership).where(
            SecurityMembership.principal_id == principal.id
        )))
        target_memberships = tuple(item for item in memberships if item.tenant_id == tenant.id)
        if len(target_memberships) > 1:
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)
        if not target_memberships:
            if memberships:
                self._fail(IdentityResolutionErrorCode.TENANT_MISMATCH, correlation_id)
            self._fail(IdentityResolutionErrorCode.MEMBERSHIP_NOT_FOUND, correlation_id)
        membership = target_memberships[0]

        # 11-12. Membership state precedes validity and all token boundaries.
        if membership.status != SecurityEntityStatus.ACTIVE.value:
            self._fail(IdentityResolutionErrorCode.MEMBERSHIP_INACTIVE, correlation_id)
        membership_valid_from = _persisted_utc(membership.valid_from)
        membership_valid_until = (
            _persisted_utc(membership.valid_until)
            if membership.valid_until is not None else None
        )
        if now < membership_valid_from:
            self._fail(IdentityResolutionErrorCode.MEMBERSHIP_NOT_YET_VALID, correlation_id)
        if membership_valid_until is not None and now > membership_valid_until:
            self._fail(IdentityResolutionErrorCode.MEMBERSHIP_EXPIRED, correlation_id)

        # 13. Active assignments, principal-kind permission safety, and proof.
        roles, digest, registry_version = self._resolve_role_proof(
            session,
            tenant=tenant,
            membership=membership,
            principal_kind=principal_kind,
            correlation_id=correlation_id,
        )

        # 14. Effective issuance/revocation boundary at microsecond precision.
        tokens_valid_after = _persisted_utc(principal.tokens_valid_after)
        if token_issued_at < max(tokens_valid_after, membership_valid_from):
            code = (
                IdentityResolutionErrorCode.TOKEN_REVOKED_BY_PRINCIPAL
                if tokens_valid_after >= membership_valid_from
                else IdentityResolutionErrorCode.TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY
            )
            self._fail(code, correlation_id)

        # 15. DTO-local invariant construction. No ORM object escapes.
        reference = (
            f"policy-ref/v1:{tenant.policy_version}:{membership.id}:"
            f"{membership.version}:{registry_version}:{digest}"
        )
        try:
            return VerifiedLocalIdentity(
                principal_id=principal.id,
                principal_kind=principal_kind,
                provider_issuer=binding.issuer,
                provider_subject=binding.subject,
                tenant_id=tenant.id,
                tenant_key=tenant.tenant_key,
                membership_id=membership.id,
                principal_status=SecurityEntityStatus(principal.status),
                tenant_status=SecurityEntityStatus(tenant.status),
                binding_status=SecurityEntityStatus(binding.status),
                membership_status=SecurityEntityStatus(membership.status),
                authentication_context_subject=subject,
                authentication_context_tenant_key=tenant_key,
                roles=roles,
                permission_resolution_reference=reference,
                role_set_digest=digest,
                permission_registry_version=registry_version,
                tenant_policy_version=tenant.policy_version,
                tokens_valid_after=tokens_valid_after,
                membership_valid_from=membership_valid_from,
                membership_valid_until=membership_valid_until,
                principal_version=principal.version,
                membership_version=membership.version,
                resolved_at=now,
            )
        except (TypeError, ValueError):
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)

    def _resolve_role_proof(
        self,
        session,
        *,
        tenant: SecurityTenant,
        membership: SecurityMembership,
        principal_kind: IdentityKind,
        correlation_id: str | None,
    ) -> tuple[tuple[str, ...], str, str]:
        assigned_roles = tuple(session.scalars(
            select(SecurityRole)
            .join(SecurityMembershipRole, SecurityMembershipRole.role_id == SecurityRole.id)
            .where(SecurityMembershipRole.membership_id == membership.id)
        ))
        if any(role.tenant_id != tenant.id for role in assigned_roles):
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)
        active_roles = tuple(
            sorted(
                (role for role in assigned_roles if role.status == "ACTIVE"),
                key=lambda role: role.role_code,
            )
        )
        if not active_roles:
            code = (
                IdentityResolutionErrorCode.SERVICE_SAFE_ROLE_NOT_FOUND
                if principal_kind is IdentityKind.SERVICE
                else IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION
            )
            self._fail(code, correlation_id)
        if len({role.role_code for role in active_roles}) != len(active_roles):
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)

        role_ids = tuple(role.id for role in active_roles)
        permission_rows = tuple(session.execute(
            select(SecurityRolePermission.role_id, SecurityPermission)
            .join(
                SecurityPermission,
                SecurityPermission.permission_code == SecurityRolePermission.permission_code,
                isouter=True,
            )
            .where(SecurityRolePermission.role_id.in_(role_ids))
        ))
        permissions_by_role: dict[object, list[SecurityPermission]] = {
            role_id: [] for role_id in role_ids
        }
        for role_id, permission in permission_rows:
            if permission is None or role_id not in permissions_by_role:
                self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)
            permissions_by_role[role_id].append(permission)
        if any(not permissions_by_role[role_id] for role_id in role_ids):
            code = (
                IdentityResolutionErrorCode.SERVICE_SAFE_ROLE_NOT_FOUND
                if principal_kind is IdentityKind.SERVICE
                else IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION
            )
            self._fail(code, correlation_id)

        all_permissions = tuple(
            permission
            for role_id in role_ids
            for permission in permissions_by_role[role_id]
        )
        versions = {permission.permission_registry_version for permission in all_permissions}
        if versions != {PERMISSION_REGISTRY_VERSION}:
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)
        if principal_kind is IdentityKind.SERVICE:
            if any(not permission.service_allowed for permission in all_permissions):
                self._fail(IdentityResolutionErrorCode.SERVICE_ROLE_PERMISSION_INVALID, correlation_id)
        elif (
            any(role.role_code == "SERVICE_OPERATOR" for role in active_roles)
            or any(not permission.human_allowed for permission in all_permissions)
        ):
            self._fail(IdentityResolutionErrorCode.DATA_INTEGRITY_VIOLATION, correlation_id)

        canonical_records = tuple({
            "role_id": str(role.id),
            "role_code": role.role_code,
            "role_version": role.version,
            "permission_codes": tuple(sorted({
                permission.permission_code
                for permission in permissions_by_role[role.id]
            })),
        } for role in active_roles)
        serialized = json.dumps(
            canonical_records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest = hashlib.sha256(serialized).hexdigest()
        return tuple(role.role_code for role in active_roles), digest, PERMISSION_REGISTRY_VERSION

    @staticmethod
    def _fail(code: IdentityResolutionErrorCode, correlation_id: str | None) -> None:
        raise IdentityResolutionError(code, correlation_id=correlation_id)


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and bool(SAFE_CORRELATION_PATTERN.fullmatch(value))


def _canonical_issuer(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.netloc == parsed.netloc.lower()
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _to_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime")
    return value.astimezone(timezone.utc)


def _persisted_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("persisted datetime")
    return value.astimezone(timezone.utc)
