import uuid

import pytest

from app.db.session import SessionLocal
from app.models.orchestration_persistence import OrchestrationRun
from app.orchestration_persistence.blob import FilesystemBlobStore
from app.orchestration_persistence.errors import OrchestrationPersistenceError
from app.orchestration_persistence.snapshot import SqlAlchemySnapshotBuilder
from app.orchestration_persistence.types import PersistenceRunScope


def test_snapshot_materializes_canonical_run_and_rejects_wrong_scope(tmp_path):
    session = SessionLocal()
    run = session.query(OrchestrationRun).order_by(OrchestrationRun.created_at.desc()).first()
    assert run is not None
    builder = SqlAlchemySnapshotBuilder(session, FilesystemBlobStore(tmp_path))
    loaded = builder.build_previous_execution_snapshot(run.run_id, PersistenceRunScope(run.company_id, run.period_id))
    assert loaded.snapshot.previous_run_id == run.run_id
    assert loaded.persistence_context.persisted_run_id == run.id
    assert len(loaded.snapshot.engine_snapshots) == len(loaded.persistence_context.engine_bindings)
    with pytest.raises(OrchestrationPersistenceError):
        builder.build_previous_execution_snapshot(run.run_id, PersistenceRunScope(uuid.uuid4(), run.period_id))
    session.close()
