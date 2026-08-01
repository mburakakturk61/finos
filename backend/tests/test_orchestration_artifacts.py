import hashlib

import pytest

from app.engines.analysis_orchestrator.types import EngineCode
from app.orchestration_persistence.artifacts import prepare_artifact
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.codec import decode_artifact, encode_artifact
from app.orchestration_persistence.errors import OrchestrationPersistenceError
from app.orchestration_persistence.ownership import RESULT_OWNERSHIP_REGISTRY, ResultOwner
from app.orchestration_persistence.types import ArtifactStorageBackend


def test_ownership_registry_has_three_financial_and_seven_artifact_owners():
    assert set(RESULT_OWNERSHIP_REGISTRY) == set(EngineCode)
    owners = [entry.owner for entry in RESULT_OWNERSHIP_REGISTRY.values()]
    assert owners.count(ResultOwner.FINANCIAL_ANALYSIS_RESULT) == 3
    assert owners.count(ResultOwner.ORCHESTRATION_ARTIFACT) == 7


def test_codec_is_deterministic_and_digest_verified():
    payload = {"b": 2, "a": [1, 3]}
    raw, digest = encode_artifact("dict", payload)
    assert raw == b'{"a":[1,3],"b":2}'
    assert decode_artifact("dict", raw, digest, "1.0.0") == {"a": (1, 3), "b": 2}
    with pytest.raises(OrchestrationPersistenceError):
        decode_artifact("dict", raw + b" ", digest, "1.0.0")


def test_size_policy_both_sides_and_total_budget():
    small = prepare_artifact("dict", {"x": "a" * 10}, inline_limit=100)
    large = prepare_artifact("dict", {"x": "a" * 100}, inline_limit=100)
    budgeted = prepare_artifact("dict", {"x": "a" * 10}, current_inline_bytes=95, inline_budget=100)
    assert small.storage_backend is ArtifactStorageBackend.INLINE_JSONB
    assert large.storage_backend is ArtifactStorageBackend.EXTERNAL_BLOB
    assert budgeted.storage_backend is ArtifactStorageBackend.EXTERNAL_BLOB


def test_filesystem_blob_publish_is_verified_and_idempotent(tmp_path):
    store = FilesystemBlobStore(tmp_path)
    payload = b'{"large":true}'
    digest = hashlib.sha256(payload).hexdigest()
    first = store.verify_and_publish(store.stage("run/one", payload), digest=digest, byte_size=len(payload))
    second = store.verify_and_publish(store.stage("run/two", payload), digest=digest, byte_size=len(payload))
    assert first == second
    assert store.read_ready(first) == payload
