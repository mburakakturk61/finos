"""Closed error taxonomy owned by the 5.0B persistence boundary."""

from __future__ import annotations

import enum


class PersistenceErrorCategory(str, enum.Enum):
    RUN_NOT_FOUND = "run_not_found"
    RUN_ID_CONFLICT = "run_id_conflict"
    SCOPE_MISMATCH = "scope_mismatch"
    PREVIOUS_RUN_NOT_FINALIZED = "previous_run_not_finalized"
    IMMUTABLE_RECORD_CONFLICT = "immutable_record_conflict"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_INTEGRITY_FAILURE = "artifact_integrity_failure"
    UNSUPPORTED_SERIALIZER_OR_RESULT_KIND = "unsupported_serializer_or_result_kind"
    TRANSACTION_FAILURE = "transaction_failure"
    PERSISTENCE_INVARIANT_VIOLATION = "persistence_invariant_violation"


class OrchestrationPersistenceError(RuntimeError):
    """Safe, caller-facing persistence failure without raw exception details."""

    def __init__(self, category: PersistenceErrorCategory, message: str) -> None:
        super().__init__(message)
        self.category = category

