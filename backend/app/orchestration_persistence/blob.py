"""Durable filesystem reference implementation of BlobStorePort."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.orchestration_persistence.errors import OrchestrationPersistenceError, PersistenceErrorCategory


class FilesystemBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._staging = self._root / "staging"
        self._ready = self._root / "ready"
        self._staging.mkdir(parents=True, exist_ok=True)
        self._ready.mkdir(parents=True, exist_ok=True)

    def _safe(self, base: Path, key: str) -> Path:
        path = (base / key).resolve()
        if base.resolve() not in path.parents:
            raise ValueError("Blob key escapes configured storage root.")
        return path

    def stage(self, key: str, payload: bytes) -> str:
        target = self._safe(self._staging, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return f"staging/{key}"

    def verify_and_publish(self, staging_locator: str, *, digest: str, byte_size: int) -> str:
        prefix = "staging/"
        if not staging_locator.startswith(prefix):
            raise ValueError("Only staging locators can be published.")
        source = self._safe(self._staging, staging_locator[len(prefix):])
        payload = source.read_bytes()
        if len(payload) != byte_size or hashlib.sha256(payload).hexdigest() != digest:
            raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE, "Staged artifact integrity verification failed.")
        key = f"sha256/{digest[:2]}/{digest}-{byte_size}.json"
        target = self._safe(self._ready, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != payload:
                raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_INTEGRITY_FAILURE, "Content-addressed artifact collision.")
            source.unlink(missing_ok=True)
        else:
            os.replace(source, target)
        return f"ready/{key}"

    def read_ready(self, locator: str) -> bytes:
        prefix = "ready/"
        if not locator.startswith(prefix):
            raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_MISSING, "Artifact is not ready.")
        path = self._safe(self._ready, locator[len(prefix):])
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise OrchestrationPersistenceError(PersistenceErrorCategory.ARTIFACT_MISSING, "Artifact is missing.") from exc
