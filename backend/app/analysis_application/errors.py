"""Closed public error policy and safe constructors."""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis_application.contracts import AnalysisErrorCode, ApplicationErrorCategory


@dataclass(frozen=True)
class ErrorPolicy:
    category: ApplicationErrorCategory
    retryable: bool
    fail_closed: bool = True


ERROR_POLICIES = {
    AnalysisErrorCode.INVALID_COMMAND: ErrorPolicy(ApplicationErrorCategory.VALIDATION, False),
    AnalysisErrorCode.INVALID_QUERY: ErrorPolicy(ApplicationErrorCategory.VALIDATION, False),
    AnalysisErrorCode.UNAUTHORIZED: ErrorPolicy(ApplicationErrorCategory.AUTHORIZATION, False),
    AnalysisErrorCode.AUTHORIZATION_REVOKED: ErrorPolicy(ApplicationErrorCategory.AUTHORIZATION, False),
    AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE: ErrorPolicy(ApplicationErrorCategory.DEPENDENCY, True),
    AnalysisErrorCode.NOT_FOUND: ErrorPolicy(ApplicationErrorCategory.NOT_FOUND, False),
    AnalysisErrorCode.SCOPE_MISMATCH: ErrorPolicy(ApplicationErrorCategory.CONFLICT, False),
    AnalysisErrorCode.RUN_ID_CONFLICT: ErrorPolicy(ApplicationErrorCategory.CONFLICT, False),
    AnalysisErrorCode.FINGERPRINT_CONFLICT: ErrorPolicy(ApplicationErrorCategory.CONFLICT, False),
    AnalysisErrorCode.SCOPE_CLAIM_CONFLICT: ErrorPolicy(ApplicationErrorCategory.CONFLICT, False),
    AnalysisErrorCode.SCOPE_CLAIM_UNAVAILABLE: ErrorPolicy(ApplicationErrorCategory.DEPENDENCY, True),
    AnalysisErrorCode.SCOPE_FINALIZATION_FAILED: ErrorPolicy(ApplicationErrorCategory.RECOVERY, True),
    AnalysisErrorCode.RESUME_SOURCE_INVALID: ErrorPolicy(ApplicationErrorCategory.VALIDATION, False),
    AnalysisErrorCode.RESUME_SOURCE_CORRUPTED: ErrorPolicy(ApplicationErrorCategory.INTEGRITY, False),
    AnalysisErrorCode.RESUME_SOURCE_UNAUTHORIZED: ErrorPolicy(ApplicationErrorCategory.AUTHORIZATION, False),
    AnalysisErrorCode.PERSISTENCE_CONFLICT: ErrorPolicy(ApplicationErrorCategory.CONFLICT, False),
    AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR: ErrorPolicy(ApplicationErrorCategory.INTEGRITY, False),
    AnalysisErrorCode.PERSISTENCE_UNAVAILABLE: ErrorPolicy(ApplicationErrorCategory.DEPENDENCY, True),
    AnalysisErrorCode.EXECUTION_FAILED: ErrorPolicy(ApplicationErrorCategory.EXECUTION, False),
    AnalysisErrorCode.DTO_PROJECTION_FAILED: ErrorPolicy(ApplicationErrorCategory.RECOVERY, True),
    AnalysisErrorCode.SECURITY_AUDIT_FAILED: ErrorPolicy(ApplicationErrorCategory.SECURITY_DEPENDENCY, True),
    AnalysisErrorCode.INTERNAL_INVARIANT_BREACH: ErrorPolicy(ApplicationErrorCategory.INTERNAL, False),
}

if set(ERROR_POLICIES) != set(AnalysisErrorCode):
    raise RuntimeError("Application error policy must be exhaustive.")
