"""Explicit trusted E1→E2 historical tenant ownership binding adapter."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.company import Company
from app.models.security import SecurityProvisioningOperation, SecurityTenant
from app.security.contracts import (
    AuthenticationAuditEvent,
    AuthenticationSecurityAuditPort,
    JTI_PATTERN,
    ProvisioningAuthority,
    TENANT_KEY_PATTERN,
)


@dataclass(frozen=True)
class HistoricalTenantBindingCommand:
    authority: ProvisioningAuthority
    idempotency_key: str
    tenant_key: str
    company_ids: tuple[uuid.UUID, ...]
    bulk_batch_ids: tuple[uuid.UUID, ...]
    run_claim_ids: tuple[uuid.UUID, ...]
    requested_at: datetime
    correlation_id: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.authority.authority_kind != "PLATFORM":
            raise ValueError("Historical binding requires platform authority.")
        if not JTI_PATTERN.fullmatch(self.idempotency_key):
            raise ValueError("Historical binding idempotency key is invalid.")
        if not TENANT_KEY_PATTERN.fullmatch(self.tenant_key):
            raise ValueError("Historical binding tenant key is invalid.")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Historical binding time must be timezone-aware.")
        for values in (self.company_ids, self.bulk_batch_ids, self.run_claim_ids):
            if len(values) != len(set(values)):
                raise ValueError("Historical binding resource list contains duplicates.")


@dataclass(frozen=True)
class HistoricalTenantBindingOutcome:
    operation_id: uuid.UUID
    tenant_key: str
    bound_company_count: int
    bound_batch_count: int
    bound_run_claim_count: int
    idempotent_replay: bool


class HistoricalTenantBindingConflict(RuntimeError):
    pass


class SqlAlchemyHistoricalTenantBindingService:
    def __init__(self, session_factory, audit: AuthenticationSecurityAuditPort) -> None:
        self._sessions = session_factory
        self._audit = audit

    def bind(self, command: HistoricalTenantBindingCommand) -> HistoricalTenantBindingOutcome:
        digest = self._digest(command)
        receipt = self._audit.record_required_event(AuthenticationAuditEvent(
            "HISTORICAL_TENANT_BINDING_AUTHORIZED", command.requested_at,
            command.correlation_id, command.authority.authority_id,
            (("tenant_key", command.tenant_key), ("payload_digest", digest)),
        ))
        try:
            with self._sessions() as session, session.begin():
                existing = session.scalar(select(SecurityProvisioningOperation).where(
                    SecurityProvisioningOperation.authority_id == command.authority.authority_id,
                    SecurityProvisioningOperation.idempotency_key == command.idempotency_key,
                ))
                if existing is not None:
                    if existing.payload_digest != digest:
                        raise HistoricalTenantBindingConflict("Historical binding idempotency conflict.")
                    return self._outcome(existing, replay=True)
                tenant = session.scalar(select(SecurityTenant).where(
                    SecurityTenant.tenant_key == command.tenant_key,
                    SecurityTenant.status == "ACTIVE",
                ))
                if tenant is None:
                    raise HistoricalTenantBindingConflict("Historical binding tenant is unavailable.")
                companies = self._load_exact(session, Company, Company.id, command.company_ids)
                batches = self._load_exact(session, BulkUploadBatch, BulkUploadBatch.id, command.bulk_batch_ids)
                claims = self._load_exact(session, AnalysisRunScopeClaim, AnalysisRunScopeClaim.claim_id, command.run_claim_ids)
                for row in companies + batches:
                    if row.tenant_id not in (None, tenant.id):
                        raise HistoricalTenantBindingConflict("Resource already belongs to another tenant.")
                    row.tenant_id = tenant.id
                if claims:
                    session.execute(text("SET LOCAL app.security_historical_binding = 'on'"))
                for row in claims:
                    if row.tenant_id not in (None, tenant.tenant_key):
                        raise HistoricalTenantBindingConflict("Run claim already belongs to another tenant.")
                    row.tenant_id = tenant.tenant_key
                result = {
                    "tenant_key": tenant.tenant_key,
                    "bound_company_count": len(companies),
                    "bound_batch_count": len(batches),
                    "bound_run_claim_count": len(claims),
                }
                operation = SecurityProvisioningOperation(
                    id=uuid.uuid4(), authority_id=command.authority.authority_id,
                    idempotency_key=command.idempotency_key,
                    operation_kind="BIND_HISTORICAL_RESOURCES",
                    payload_digest=digest, payload_schema_version=command.schema_version,
                    status="COMPLETED", audit_receipt_id=str(receipt), result_json=result,
                )
                session.add(operation)
                session.flush()
                return self._outcome(operation, replay=False)
        except IntegrityError as exc:
            raise HistoricalTenantBindingConflict("Historical binding persistence conflict.") from exc

    @staticmethod
    def _load_exact(session, model, key_column, identifiers):
        if not identifiers:
            return []
        rows = list(session.scalars(select(model).where(key_column.in_(identifiers)).with_for_update()))
        if len(rows) != len(identifiers):
            raise HistoricalTenantBindingConflict("Historical binding resource is missing.")
        return rows

    @staticmethod
    def _digest(command: HistoricalTenantBindingCommand) -> str:
        payload = {
            "schema": command.schema_version,
            "tenant_key": command.tenant_key,
            "company_ids": sorted(map(str, command.company_ids)),
            "batch_ids": sorted(map(str, command.bulk_batch_ids)),
            "run_claim_ids": sorted(map(str, command.run_claim_ids)),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _outcome(row: SecurityProvisioningOperation, *, replay: bool) -> HistoricalTenantBindingOutcome:
        result = row.result_json
        return HistoricalTenantBindingOutcome(
            row.id, str(result["tenant_key"]), int(result["bound_company_count"]),
            int(result["bound_batch_count"]), int(result["bound_run_claim_count"]), replay,
        )
