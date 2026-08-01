"""Payload tier selection independent of engine and database schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.orchestration_persistence.codec import SERIALIZER_SCHEMA_VERSION, encode_artifact
from app.orchestration_persistence.types import ArtifactStorageBackend

DEFAULT_INLINE_LIMIT = 256 * 1024
DEFAULT_INLINE_WARNING_THRESHOLD = 128 * 1024
DEFAULT_RUN_INLINE_BUDGET = 1024 * 1024


@dataclass(frozen=True)
class PreparedArtifact:
    result_kind: str
    canonical_bytes: bytes
    content_digest: str
    byte_size: int
    storage_backend: ArtifactStorageBackend
    inline_payload: dict[str, Any] | list[Any] | None
    serializer_schema_version: str = SERIALIZER_SCHEMA_VERSION
    size_warning: bool = False


def prepare_artifact(result_kind: str, payload: object, *, current_inline_bytes: int = 0, inline_limit: int = DEFAULT_INLINE_LIMIT, inline_budget: int = DEFAULT_RUN_INLINE_BUDGET) -> PreparedArtifact:
    raw, digest = encode_artifact(result_kind, payload)
    inline = len(raw) <= inline_limit and current_inline_bytes + len(raw) <= inline_budget
    import json
    return PreparedArtifact(
        result_kind=result_kind,
        canonical_bytes=raw,
        content_digest=digest,
        byte_size=len(raw),
        storage_backend=ArtifactStorageBackend.INLINE_JSONB if inline else ArtifactStorageBackend.EXTERNAL_BLOB,
        inline_payload=json.loads(raw) if inline else None,
        size_warning=len(raw) >= DEFAULT_INLINE_WARNING_THRESHOLD,
    )
