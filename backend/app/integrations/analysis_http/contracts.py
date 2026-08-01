"""Framework-independent HTTP integration contracts."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


ANALYSIS_HTTP_SCHEMA_VERSION = "1.0.0"


class ApiRuntimeProfile(str, enum.Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AuthenticationStrength(str, enum.Enum):
    BASIC = "BASIC"
    STRONG = "STRONG"
    PHISHING_RESISTANT = "PHISHING_RESISTANT"


@dataclass(frozen=True)
class AuthenticationContext:
    subject_id: str
    tenant_id: str | None
    authentication_method: str
    authentication_strength: AuthenticationStrength
    issued_at: datetime
    expires_at: datetime | None
    correlation_id: str
    claims_version: str
    trusted_issuer: str
    authorization_context_reference: str


class AuthenticationContextError(RuntimeError):
    pass


class AuthenticationProviderUnavailable(AuthenticationContextError):
    pass


class TrustedAuthenticationContextProviderPort(Protocol):
    runtime_profile: ApiRuntimeProfile
    is_fake: bool

    def current_context(self) -> AuthenticationContext: ...
    def readiness_check(self, deadline: datetime) -> bool: ...


class DocumentContentStorePort(Protocol):
    def read_document_content(self, document_id: uuid.UUID, checksum: str) -> bytes: ...


@dataclass(frozen=True)
class ResolvedDocumentInput:
    document_id: uuid.UUID
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    content: bytes
    original_filename: str
    mime_type: str
    sha256_checksum: str
    document_type: str


@dataclass(frozen=True)
class ResolvedTrialBalanceInput:
    analysis_result_id: uuid.UUID
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    result_payload: dict[str, object]
    canonical_digest: str
    analysis_type: str
    status: str


class InputResolutionCode(str, enum.Enum):
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_SCOPE_MISMATCH = "SOURCE_SCOPE_MISMATCH"
    SOURCE_UNAUTHORIZED = "SOURCE_UNAUTHORIZED"
    SOURCE_STATUS_INVALID = "SOURCE_STATUS_INVALID"
    SOURCE_TYPE_INVALID = "SOURCE_TYPE_INVALID"
    SOURCE_CONTENT_UNAVAILABLE = "SOURCE_CONTENT_UNAVAILABLE"
    SOURCE_CHECKSUM_MISMATCH = "SOURCE_CHECKSUM_MISMATCH"
    SOURCE_CANONICAL_DIGEST_MISMATCH = "SOURCE_CANONICAL_DIGEST_MISMATCH"
    SOURCE_RESOLVER_UNAVAILABLE = "SOURCE_RESOLVER_UNAVAILABLE"


class InputResolutionError(RuntimeError):
    def __init__(self, code: InputResolutionCode) -> None:
        super().__init__(code.value)
        self.code = code


class DocumentInputResolverPort(Protocol):
    def resolve_document_input(
        self, *, document_id: uuid.UUID, company_id: uuid.UUID,
        financial_period_id: uuid.UUID, expected_engine_code: str,
        authentication: AuthenticationContext,
    ) -> ResolvedDocumentInput: ...
    def readiness_check(self, deadline: datetime) -> bool: ...


class AnalysisResultInputResolverPort(Protocol):
    def resolve_trial_balance_input(
        self, *, analysis_result_id: uuid.UUID, company_id: uuid.UUID,
        financial_period_id: uuid.UUID, authentication: AuthenticationContext,
    ) -> ResolvedTrialBalanceInput: ...
    def readiness_check(self, deadline: datetime) -> bool: ...


@dataclass(frozen=True)
class AdmissionLease:
    lease_id: str
    tenant_key: str
    subject_id: str
    acquired_at: datetime


class AnalysisAdmissionControlPort(Protocol):
    retry_after_seconds: int

    def try_acquire(
        self, *, tenant_id: str | None, subject_id: str,
        run_id: str, acquired_at: datetime,
    ) -> AdmissionLease | None: ...

    def release(self, lease: AdmissionLease) -> None: ...
    def readiness_check(self, deadline: datetime) -> bool: ...


@dataclass(frozen=True)
class RunOwnershipView:
    run_id: str
    company_id: uuid.UUID
    financial_period_id: uuid.UUID
    tenant_id: str | None
    operation_kind: str
    original_operation: str
    previous_run_id: str | None
    initiating_subject_id: str | None
    status: str


class RunOwnershipInspectorPort(Protocol):
    def load(self, run_id: str) -> RunOwnershipView | None: ...
