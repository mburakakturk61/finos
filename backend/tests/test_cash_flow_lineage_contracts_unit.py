"""Milestone 4.5F framework-independent lineage acceptance."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import pytest

from app.engines.cash_flow import (
    CashFlowContractError,
    CashFlowErrorCode,
    CashFlowPortError,
    CashFlowResultStatus,
    CashFlowSourceRole,
    ResolvedCashFlowLineageEdge,
    canonical_cash_flow_lineage_set_digest,
    validate_cash_flow_lineage_role_set,
)
from app.models.cash_flow_cross_period_lineage import CashFlowCrossPeriodLineage
from app.models.enums import AnalysisType


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _edge(role: CashFlowSourceRole, *, source_id=None, current=None, prior=None):
    current = current or uuid4()
    prior = prior or uuid4()
    analysis_type = {
        CashFlowSourceRole.CURRENT_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
        CashFlowSourceRole.PRIOR_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
        CashFlowSourceRole.CURRENT_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
        CashFlowSourceRole.CURRENT_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
        CashFlowSourceRole.PRIOR_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    }[role]
    return ResolvedCashFlowLineageEdge(
        source_role=role,
        source_analysis_result_id=source_id or uuid4(),
        source_period_id=prior if role.value.startswith("prior_") else current,
        source_canonical_digest=DIGEST_A,
        source_provenance_digest=DIGEST_B,
        source_analysis_type=analysis_type,
        source_engine_version="1.0.0",
        current_period_descriptor_digest=DIGEST_C,
        prior_period_descriptor_digest=DIGEST_A,
        comparability_proof_digest=DIGEST_B,
    )


def _lineage():
    current, prior = uuid4(), uuid4()
    return tuple(
        _edge(role, current=current, prior=prior)
        for role in (
            CashFlowSourceRole.CURRENT_BALANCE_SHEET,
            CashFlowSourceRole.PRIOR_BALANCE_SHEET,
            CashFlowSourceRole.CURRENT_INCOME_STATEMENT,
            CashFlowSourceRole.CURRENT_TRIAL_BALANCE,
            CashFlowSourceRole.PRIOR_TRIAL_BALANCE,
        )
    )


def test_exact_source_role_taxonomy_is_closed():
    assert tuple(role.value for role in CashFlowSourceRole) == (
        "current_balance_sheet",
        "prior_balance_sheet",
        "current_income_statement",
        "current_trial_balance",
        "prior_trial_balance",
    )


def test_edge_is_frozen_and_safe():
    edge = _lineage()[0]
    assert repr(edge) == "ResolvedCashFlowLineageEdge()"
    with pytest.raises(FrozenInstanceError):
        edge.source_role = CashFlowSourceRole.CURRENT_TRIAL_BALANCE


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_canonical_digest", "A" * 64),
        ("source_provenance_digest", "x" * 64),
        ("current_period_descriptor_digest", "a" * 63),
        ("prior_period_descriptor_digest", None),
    ),
)
def test_edge_rejects_malformed_digest_and_unpaired_proof(field, value):
    with pytest.raises(CashFlowContractError):
        replace(_lineage()[0], **{field: value})


def test_role_type_matrix_is_fail_closed():
    with pytest.raises(CashFlowContractError):
        replace(_lineage()[0], source_analysis_type=AnalysisType.INCOME_STATEMENT)


def test_complete_and_partial_require_exact_base_role_subset():
    lineage = _lineage()
    for status in tuple(CashFlowResultStatus)[:4]:
        assert len(validate_cash_flow_lineage_role_set(status, lineage)) == 5
        with pytest.raises(CashFlowContractError):
            validate_cash_flow_lineage_role_set(status, lineage[1:])


def test_insufficient_accepts_only_the_verified_subset_or_empty():
    assert validate_cash_flow_lineage_role_set(CashFlowResultStatus.INSUFFICIENT_DATA, ()) == ()
    assert validate_cash_flow_lineage_role_set(
        CashFlowResultStatus.INSUFFICIENT_DATA, (_lineage()[0],)
    )


def test_duplicate_role_is_rejected_before_canonicalization():
    lineage = _lineage()
    with pytest.raises(CashFlowContractError):
        validate_cash_flow_lineage_role_set(
            CashFlowResultStatus.COMPLETE_RECONCILED,
            lineage + (replace(lineage[0], source_analysis_result_id=uuid4()),),
        )


def test_same_source_cannot_be_reused_for_conflicting_roles():
    lineage = _lineage()
    with pytest.raises(CashFlowContractError):
        validate_cash_flow_lineage_role_set(
            CashFlowResultStatus.COMPLETE_RECONCILED,
            lineage[:1] + (replace(lineage[1], source_analysis_result_id=lineage[0].source_analysis_result_id),) + lineage[2:],
        )


def test_source_set_digest_is_order_independent_and_deterministic():
    owner, current, prior = uuid4(), uuid4(), uuid4()
    lineage = _lineage()
    kwargs = dict(
        owner_analysis_result_id=owner,
        current_period_id=current,
        prior_period_id=prior,
        owner_payload_digest=DIGEST_A,
    )
    first = canonical_cash_flow_lineage_set_digest(lineage=lineage, **kwargs)
    second = canonical_cash_flow_lineage_set_digest(lineage=tuple(reversed(lineage)), **kwargs)
    assert first == second
    assert first == canonical_cash_flow_lineage_set_digest(lineage=lineage, **kwargs)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda values: {"owner_analysis_result_id": uuid4()},
        lambda values: {"current_period_id": uuid4()},
        lambda values: {"prior_period_id": uuid4()},
        lambda values: {"owner_payload_digest": DIGEST_B},
        lambda values: {"lineage": (replace(values["lineage"][0], source_canonical_digest=DIGEST_C),) + values["lineage"][1:]},
        lambda values: {"lineage": (replace(values["lineage"][0], source_period_id=uuid4()),) + values["lineage"][1:]},
    ),
)
def test_any_owner_period_or_source_mutation_changes_digest(mutation):
    values = dict(
        owner_analysis_result_id=uuid4(),
        current_period_id=uuid4(),
        prior_period_id=uuid4(),
        owner_payload_digest=DIGEST_A,
        lineage=_lineage(),
    )
    original = canonical_cash_flow_lineage_set_digest(**values)
    values.update(mutation(values))
    assert canonical_cash_flow_lineage_set_digest(**values) != original


def test_port_error_is_closed_safe_immutable_and_retryable_only_for_outage():
    integrity = CashFlowPortError(CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE)
    unavailable = CashFlowPortError(CashFlowErrorCode.PERSISTENCE_UNAVAILABLE)
    assert not integrity.retryable and unavailable.retryable
    assert "sql" not in repr(integrity).lower()
    with pytest.raises((AttributeError, TypeError)):
        integrity._code = CashFlowErrorCode.PERSISTENCE_UNAVAILABLE
    with pytest.raises(CashFlowContractError):
        CashFlowPortError(CashFlowErrorCode.SOURCE_NOT_FOUND)


def test_orm_table_manifest_has_single_payload_free_lineage_shape():
    table = CashFlowCrossPeriodLineage.__table__
    assert set(table.columns.keys()) == {
        "id", "cash_flow_analysis_result_id", "tenant_id", "company_id",
        "current_period_id", "prior_period_id", "source_period_id",
        "source_analysis_result_id", "source_role", "source_canonical_digest",
        "source_provenance_digest", "source_analysis_type", "source_engine_version",
        "current_period_descriptor_digest", "prior_period_descriptor_digest",
        "comparability_proof_digest", "lineage_schema_version",
        "lineage_policy_version", "created_at",
    }
    assert not {"result_json", "payload", "payload_json"}.intersection(table.columns)
    assert all(fk.ondelete == "RESTRICT" for fk in table.foreign_key_constraints)
    assert repr(CashFlowCrossPeriodLineage()).startswith("CashFlowCrossPeriodLineage(id=")
