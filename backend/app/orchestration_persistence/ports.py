"""Framework-independent persistence and blob ports."""

from __future__ import annotations

from typing import Protocol

from app.orchestration_persistence.types import (
    ArtifactRef,
    PersistedRun,
    PersistTerminalRunCommand,
    PersistenceRunScope,
    RunHistoryPage,
    SnapshotLoadResult,
)


class RunStorePort(Protocol):
    def load_run(self, run_id: str) -> PersistedRun | None: ...

    def persist_terminal_run(self, command: PersistTerminalRunCommand) -> PersistedRun: ...

    def list_run_history(
        self, scope: PersistenceRunScope, cursor: str | None, limit: int
    ) -> RunHistoryPage: ...


class SnapshotReaderPort(Protocol):
    def build_previous_execution_snapshot(
        self, run_id: str, target_scope: PersistenceRunScope
    ) -> SnapshotLoadResult: ...


class ArtifactStorePort(Protocol):
    def store_owned_artifact(self, result_kind: str, payload: object) -> ArtifactRef: ...

    def load_owned_artifact(self, ref: ArtifactRef) -> object: ...


class BlobStorePort(Protocol):
    def stage(self, key: str, payload: bytes) -> str: ...

    def verify_and_publish(
        self, staging_locator: str, *, digest: str, byte_size: int
    ) -> str: ...

    def read_ready(self, locator: str) -> bytes: ...
