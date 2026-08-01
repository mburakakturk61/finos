import dataclasses
import enum
import uuid

import pytest

from app.engines.analysis_orchestrator.types import EngineCode
from app.orchestration_persistence.errors import PersistenceErrorCategory
from app.orchestration_persistence.types import (
    FinancialResultOwnerBinding,
    PersistenceRunScope,
)


def test_persistence_error_taxonomy_is_closed_and_separate_from_5_0a():
    assert issubclass(PersistenceErrorCategory, enum.Enum)
    assert {member.value for member in PersistenceErrorCategory} == {
        "run_not_found",
        "run_id_conflict",
        "scope_mismatch",
        "previous_run_not_finalized",
        "immutable_record_conflict",
        "artifact_missing",
        "artifact_integrity_failure",
        "unsupported_serializer_or_result_kind",
        "transaction_failure",
        "persistence_invariant_violation",
    }


def test_scope_is_immutable_and_never_unscoped():
    scope = PersistenceRunScope(uuid.uuid4(), uuid.uuid4())
    assert dataclasses.is_dataclass(scope)
    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.company_id = uuid.uuid4()


def test_financial_owner_binding_requires_exactly_one_mode():
    with pytest.raises(ValueError):
        FinancialResultOwnerBinding(engine_code=EngineCode.RATIO)
    with pytest.raises(ValueError):
        FinancialResultOwnerBinding(
            engine_code=EngineCode.RATIO,
            existing_owner_id=uuid.uuid4(),
            create_owner=object(),
        )
