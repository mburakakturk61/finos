"""Immutable persistence-owned commands and projections for Milestone 5.0B."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.engines.analysis_orchestrator.types import (
    EngineCode,
    OrchestrationRunResult,
    PreviousExecutionSnapshot,
)
from app.models.enums import AnalysisSourceRole, AnalysisType, SourceMode


class ArtifactStorageBackend(str, enum.Enum):
    INLINE_JSONB = "inline_jsonb"
    EXTERNAL_BLOB = "external_blob"


@dataclass(frozen=True)
class PersistenceRunScope:
    company_id: uuid.UUID
    period_id: uuid.UUID


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: uuid.UUID
    result_kind: str
    content_digest: str
    serializer_schema_version: str
    byte_size: int
    storage_backend: ArtifactStorageBackend


@dataclass(frozen=True)
class ResumeEngineBinding:
    engine_code: EngineCode
    source_engine_execution_id: uuid.UUID
    artifact_id: uuid.UUID | None
    financial_analysis_result_id: uuid.UUID | None
    canonical_digest: str


@dataclass(frozen=True)
class ResumePersistenceContext:
    persisted_run_id: uuid.UUID
    previous_run_id: str
    scope: PersistenceRunScope
    engine_bindings: tuple[ResumeEngineBinding, ...]


@dataclass(frozen=True)
class SnapshotLoadResult:
    snapshot: PreviousExecutionSnapshot
    persistence_context: ResumePersistenceContext


@dataclass(frozen=True)
class FinancialResultSourceBinding:
    role: AnalysisSourceRole
    source_document_id: uuid.UUID | None = None
    source_analysis_result_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CreateFinancialResultOwner:
    analysis_type: AnalysisType
    source_mode: SourceMode
    document_id: uuid.UUID | None
    engine_version: str
    started_at: datetime
    completed_at: datetime
    source_bindings: tuple[FinancialResultSourceBinding, ...]


@dataclass(frozen=True)
class FinancialResultOwnerBinding:
    engine_code: EngineCode
    existing_owner_id: uuid.UUID | None = None
    create_owner: CreateFinancialResultOwner | None = None

    def __post_init__(self) -> None:
        if (self.existing_owner_id is None) == (self.create_owner is None):
            raise ValueError("Exactly one financial result owner mode is required.")


@dataclass(frozen=True)
class PersistTerminalRunCommand:
    scope: PersistenceRunScope
    run_result: OrchestrationRunResult
    requested_outputs: tuple[EngineCode, ...]
    resume_context: ResumePersistenceContext | None = None
    financial_owner_bindings: tuple[FinancialResultOwnerBinding, ...] = ()
    telemetry: Any | None = None


@dataclass(frozen=True)
class PersistedRun:
    id: uuid.UUID
    run_id: str
    request_fingerprint: str
    terminal_content_digest: str
    scope: PersistenceRunScope
    finalized_at: datetime


@dataclass(frozen=True)
class RunHistoryPage:
    items: tuple[PersistedRun, ...]
    next_cursor: str | None
