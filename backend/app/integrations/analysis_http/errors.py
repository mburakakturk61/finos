"""Exhaustive application/boundary error to HTTP mapping."""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis_application.contracts import AnalysisErrorCode, ApplicationErrorCategory


@dataclass
class ApiBoundaryError(RuntimeError):
    code: str
    status_code: int
    message: str
    correlation_id: str
    retryable: bool = False
    safe_metadata: dict[str, object] | None = None
    retry_after: int | None = None


_STATUS = {
    AnalysisErrorCode.INVALID_COMMAND: 422,
    AnalysisErrorCode.INVALID_QUERY: 422,
    AnalysisErrorCode.UNAUTHORIZED: 403,
    AnalysisErrorCode.AUTHORIZATION_REVOKED: 403,
    AnalysisErrorCode.AUTHORIZATION_PROVIDER_UNAVAILABLE: 503,
    AnalysisErrorCode.NOT_FOUND: 404,
    AnalysisErrorCode.SCOPE_MISMATCH: 409,
    AnalysisErrorCode.RUN_ID_CONFLICT: 409,
    AnalysisErrorCode.FINGERPRINT_CONFLICT: 409,
    AnalysisErrorCode.SCOPE_CLAIM_CONFLICT: 409,
    AnalysisErrorCode.SCOPE_CLAIM_UNAVAILABLE: 503,
    AnalysisErrorCode.SCOPE_FINALIZATION_FAILED: 500,
    AnalysisErrorCode.RESUME_SOURCE_INVALID: 409,
    AnalysisErrorCode.RESUME_SOURCE_CORRUPTED: 500,
    AnalysisErrorCode.RESUME_SOURCE_UNAUTHORIZED: 403,
    AnalysisErrorCode.PERSISTENCE_CONFLICT: 409,
    AnalysisErrorCode.PERSISTENCE_INTEGRITY_ERROR: 500,
    AnalysisErrorCode.PERSISTENCE_UNAVAILABLE: 503,
    AnalysisErrorCode.EXECUTION_FAILED: 500,
    AnalysisErrorCode.DTO_PROJECTION_FAILED: 500,
    AnalysisErrorCode.SECURITY_AUDIT_FAILED: 503,
    AnalysisErrorCode.INTERNAL_INVARIANT_BREACH: 500,
}


if set(_STATUS) != set(AnalysisErrorCode):
    raise RuntimeError("Analysis HTTP error mapping is not exhaustive.")


def status_for_application_error(code: AnalysisErrorCode) -> int:
    return _STATUS[code]


def public_error_dict(error) -> dict[str, object]:
    return {
        "code": error.code.value,
        "category": error.category.value,
        "message": error.message,
        "retryable": error.retryable,
        "correlation_id": error.correlation_id,
        "safe_metadata": error.safe_metadata,
    }


def boundary_error_dict(error: ApiBoundaryError) -> dict[str, object]:
    return {
        "code": error.code,
        "category": ApplicationErrorCategory.VALIDATION.value if error.status_code < 500 else ApplicationErrorCategory.DEPENDENCY.value,
        "message": error.message,
        "retryable": error.retryable,
        "correlation_id": error.correlation_id,
        "safe_metadata": error.safe_metadata or {},
    }
