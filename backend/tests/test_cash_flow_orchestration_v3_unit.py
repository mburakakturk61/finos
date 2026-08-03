from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.engines.analysis_orchestrator.fingerprint import canonical_hash
from app.engines.analysis_orchestrator.types import EngineCode, EngineRawInputs, OrchestrationRunOptions
from app.engines.analysis_orchestrator_v3.execution_plan import EXECUTION_PLAN_V3
from app.engines.analysis_orchestrator_v3.fingerprint import compute_request_fingerprint_v3
from app.engines.analysis_orchestrator_v3.registry import ENGINE_DEPENDENCY_REGISTRY_V3
from app.engines.analysis_orchestrator_v3.service import run_orchestration_v3
from app.engines.analysis_orchestrator_v3.types import (
    EngineRawInputsV3,
    OrchestrationEngineCodeV3 as E,
    OrchestrationRunOptionsV3,
    OrchestrationRunRequestV3,
)
from app.engines.balance_sheet.service import BalanceSheetAnalysisOutcome
from app.engines.income_statement.service import IncomeStatementAnalysisOutcome
from app.engines.cash_flow import (
    CashFlowEngineFailure,
    CashFlowErrorCode,
    CashFlowLineCode,
    CashFlowEngineOutcome,
    CashFlowPreResolvedContext,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
    canonical_cash_flow_digest,
    presentation_policy_for,
)
from app.engines.cash_flow.policy import CashFlowPresentationProfile
from app.models.enums import AnalysisStatus, SourceMode
from app.orchestration_persistence_v3.snapshot import snapshot_from_terminal_result_v3

from test_cash_flow_contracts_unit import _descriptor, _result, CURRENT_ID, PRIOR_ID


def _context():
    current = _descriptor(CURRENT_ID, date(2025, 2, 1), date(2025, 2, 28))
    prior = _descriptor(PRIOR_ID, date(2025, 1, 1), date(2025, 1, 31))
    return CashFlowPreResolvedContext(
        current_period=current,
        prior_period=prior,
        prior_balance_sheet=None,
        current_trial_balance=None,
        prior_trial_balance=None,
        account_evidence=(),
        noncash_bridge_components=(),
        pre_resolved_evidence_bundle_digest="a" * 64,
        source_candidate_set_digest="b" * 64,
        opening_account_coverage_complete=False,
        closing_account_coverage_complete=False,
        comparability_proof_digest="a" * 64,
        mapping_registry_version="1.0.0",
        accounting_policy_version="tr_tdhp_accrual/1.0.0",
        presentation_policy=presentation_policy_for(CashFlowPresentationProfile.MANAGEMENT_V1),
    )


def _request(outputs, *, context=None):
    return OrchestrationRunRequestV3(
        run_id="run-v3",
        correlation_id="corr-v3",
        generated_at="2026-01-01T00:00:00+00:00",
        requested_outputs=outputs,
        engine_inputs=EngineRawInputsV3(cash_flow_pre_resolved_context=context),
        run_options=OrchestrationRunOptionsV3(),
    )


def _statement(outcome_cls):
    return outcome_cls(
        status=AnalysisStatus.COMPLETED,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED,
        result_json={"engine_version": "1.0.0", "value": "1.00"},
        error_message=None,
        trial_balance_usage=None,
    )


def test_v3_graph_exact_shape_plan_and_cash_flow_policy():
    assert tuple(ENGINE_DEPENDENCY_REGISTRY_V3) == tuple(E)
    assert (
        len(ENGINE_DEPENDENCY_REGISTRY_V3),
        sum(len(x.dependency.all_of) for x in ENGINE_DEPENDENCY_REGISTRY_V3.values()),
        sum(len(x.dependency.any_of) for x in ENGINE_DEPENDENCY_REGISTRY_V3.values()),
        sum(len(x.dependency.optional) for x in ENGINE_DEPENDENCY_REGISTRY_V3.values()),
    ) == (11, 23, 2, 3)
    assert sum(
        len(x.dependency.all_of) + len(x.dependency.any_of) + len(x.dependency.optional)
        for x in ENGINE_DEPENDENCY_REGISTRY_V3.values()
    ) == 28
    assert tuple(item.value for item in EXECUTION_PLAN_V3) == (
        "fs_balance_sheet", "fs_income_statement", "cash_flow", "ratio", "benchmark",
        "health_score", "credit_score", "recommendation", "dashboard", "executive_report",
        "render_contract",
    )
    cash = ENGINE_DEPENDENCY_REGISTRY_V3[E.CASH_FLOW]
    assert cash.dependency.all_of == (E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT)
    assert cash.dependency_failure_behavior.value == "invoke_diagnostic_only"


def test_legacy_engine_manifest_and_registry_are_unchanged():
    assert len(tuple(EngineCode)) == 10
    assert "cash_flow" not in {item.value for item in EngineCode}


def test_v3_contract_rejects_legacy_code_and_context_mismatch():
    with pytest.raises((TypeError, ValueError)):
        _request((EngineCode.FS_BALANCE_SHEET,))
    with pytest.raises(ValueError):
        _request((E.CASH_FLOW,), context=None)
    with pytest.raises(ValueError):
        _request((E.FS_BALANCE_SHEET,), context=_context())


def test_no_cash_flow_request_fingerprint_is_legacy_byte_equal():
    request = _request((E.FS_BALANCE_SHEET,))
    expected = canonical_hash({
        "requested_outputs": (EngineCode.FS_BALANCE_SHEET,),
        "engine_inputs": EngineRawInputs(),
        "run_options": OrchestrationRunOptions(),
    })
    assert compute_request_fingerprint_v3(request) == expected


def test_cash_flow_context_changes_request_fingerprint():
    first = _request((E.CASH_FLOW,), context=_context())
    changed = replace(_context(), source_candidate_set_digest="c" * 64)
    second = _request((E.CASH_FLOW,), context=changed)
    assert compute_request_fingerprint_v3(first) != compute_request_fingerprint_v3(second)


@pytest.mark.parametrize("mutation", ("source_set", "current_period", "prior_period", "mapping", "accounting"))
def test_cash_flow_fingerprint_changes_for_every_authoritative_input_family(mutation):
    context = _context()
    if mutation == "source_set":
        changed = replace(context, source_candidate_set_digest="c" * 64)
    elif mutation == "current_period":
        changed = replace(context, current_period=replace(context.current_period, period_id=UUID(int=91)))
    elif mutation == "prior_period":
        changed = replace(context, prior_period=replace(context.prior_period, period_id=UUID(int=92)))
    elif mutation == "mapping":
        changed = replace(context, mapping_registry_version="1.0.1")
    else:
        changed = replace(context, accounting_policy_version="tr_tdhp_accrual/1.0.1")
    assert compute_request_fingerprint_v3(_request((E.CASH_FLOW,), context=context)) != compute_request_fingerprint_v3(
        _request((E.CASH_FLOW,), context=changed)
    )


def test_v3_fingerprint_is_requested_output_order_independent_and_unknown_contract_is_rejected():
    context = _context()
    first = _request((E.CASH_FLOW, E.RATIO), context=context)
    second = _request((E.RATIO, E.CASH_FLOW), context=context)
    assert compute_request_fingerprint_v3(first) == compute_request_fingerprint_v3(second)
    with pytest.raises(ValueError):
        replace(first, contract_version="9.0.0")


def test_v3_cash_flow_dispatch_is_once_and_ratio_consumes_canonical_result(monkeypatch):
    from app.engines.analysis_orchestrator_v3 import service

    calls = {"cash_flow": 0, "ratio": 0}
    result = _result()
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_BALANCE_SHEET, lambda **_: _statement(BalanceSheetAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_INCOME_STATEMENT, lambda **_: _statement(IncomeStatementAnalysisOutcome))

    def cash_flow(**kwargs):
        calls["cash_flow"] += 1
        assert set(kwargs) == {"pre_resolved_context", "current_balance_sheet", "current_income_statement"}
        return CashFlowEngineOutcome(result.status, True, result, None)

    def ratio(**kwargs):
        calls["ratio"] += 1
        assert kwargs["cash_flow_result"] is result
        return {"schema_version": "1.0", "ratio_registry_version": "1.1.0", "ratios": {}}

    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.CASH_FLOW, cash_flow)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.RATIO, ratio)
    run, _ = run_orchestration_v3(_request((E.CASH_FLOW, E.RATIO), context=_context()))
    assert calls == {"cash_flow": 1, "ratio": 1}
    assert tuple(item.engine_code for item in run.engine_records) == (
        E.FS_BALANCE_SHEET, E.FS_INCOME_STATEMENT, E.CASH_FLOW, E.RATIO,
    )


def test_cash_flow_diagnostic_invocation_survives_domain_failed_statements(monkeypatch):
    from app.engines.analysis_orchestrator_v3 import service

    result = _result(
        status=CashFlowResultStatus.INSUFFICIENT_DATA,
        reconciliation_status=CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
        opening=None, closing=None, operating=None, difference=None,
    )
    failed_bs = BalanceSheetAnalysisOutcome(AnalysisStatus.FAILED, None, None, "safe", None)
    failed_is = IncomeStatementAnalysisOutcome(AnalysisStatus.FAILED, None, None, "safe", None)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_BALANCE_SHEET, lambda **_: failed_bs)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_INCOME_STATEMENT, lambda **_: failed_is)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.CASH_FLOW, lambda **_: CashFlowEngineOutcome(result.status, True, result, None))
    run, _ = run_orchestration_v3(_request((E.CASH_FLOW,), context=_context()))
    cash = next(item for item in run.engine_records if item.engine_code is E.CASH_FLOW)
    assert cash.status.value == "degraded"
    assert cash.result.result is result


@pytest.mark.parametrize(
    ("result", "expected_execution"),
    (
        (_result(), "completed"),
        (_result(
            status=CashFlowResultStatus.PARTIAL_RECONCILED,
            estimated_code=CashFlowLineCode.NET_PROFIT,
        ), "degraded"),
        (_result(
            status=CashFlowResultStatus.INSUFFICIENT_DATA,
            reconciliation_status=CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
            opening=None, closing=None, operating=None, difference=None,
        ), "degraded"),
    ),
)
def test_cash_flow_result_bearing_statuses_preserve_domain_result_without_technical_failure(monkeypatch, result, expected_execution):
    from app.engines.analysis_orchestrator_v3 import service
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_BALANCE_SHEET, lambda **_: _statement(BalanceSheetAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_INCOME_STATEMENT, lambda **_: _statement(IncomeStatementAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.CASH_FLOW, lambda **_: CashFlowEngineOutcome(result.status, True, result, None))
    run, _ = run_orchestration_v3(_request((E.CASH_FLOW,), context=_context()))
    cash = next(item for item in run.engine_records if item.engine_code is E.CASH_FLOW)
    assert cash.status.value == expected_execution
    assert cash.inner_status_value == result.status.value
    assert cash.result.result is result


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    (
        (CashFlowResultStatus.INVALID_INPUT, CashFlowErrorCode.INVALID_CONTRACT, False),
        (CashFlowResultStatus.INTEGRITY_FAILURE, CashFlowErrorCode.SOURCE_DIGEST_MISMATCH, False),
        (CashFlowResultStatus.INTEGRITY_FAILURE, CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE, True),
    ),
)
def test_cash_flow_failure_outcomes_are_safe_ownerless_failed_executions(monkeypatch, status, code, retryable):
    from app.engines.analysis_orchestrator_v3 import service
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_BALANCE_SHEET, lambda **_: _statement(BalanceSheetAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_INCOME_STATEMENT, lambda **_: _statement(IncomeStatementAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.CASH_FLOW, lambda **_: CashFlowEngineOutcome(status, False, None, CashFlowEngineFailure(code)))
    run, _ = run_orchestration_v3(_request((E.CASH_FLOW,), context=_context()))
    cash = next(item for item in run.engine_records if item.engine_code is E.CASH_FLOW)
    assert cash.status.value == "failed" and cash.result is None
    assert cash.error.cash_flow_error_code is code
    assert cash.error.retryable is retryable
    assert cash.error.original_exception_type is None


def test_unexpected_cash_flow_exception_is_redacted(monkeypatch):
    from app.engines.analysis_orchestrator_v3 import service
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_BALANCE_SHEET, lambda **_: _statement(BalanceSheetAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_INCOME_STATEMENT, lambda **_: _statement(IncomeStatementAnalysisOutcome))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.CASH_FLOW, lambda **_: (_ for _ in ()).throw(RuntimeError("customer-secret")))
    run, _ = run_orchestration_v3(_request((E.CASH_FLOW,), context=_context()))
    cash = next(item for item in run.engine_records if item.engine_code is E.CASH_FLOW)
    assert cash.status.value == "failed" and cash.result is None
    assert "customer-secret" not in cash.error.message_tr
    assert cash.error.original_exception_type == "unexpected_engine_failure"


def test_v3_contracts_are_immutable():
    with pytest.raises(FrozenInstanceError):
        _request((E.FS_BALANCE_SHEET,)).run_id = "other"


def test_v3_only_resume_reuses_exact_snapshot_and_rejects_version_corruption(monkeypatch):
    from app.engines.analysis_orchestrator_v3 import service

    calls = {"balance": 0}

    def balance(**kwargs):
        calls["balance"] += 1
        return _statement(BalanceSheetAnalysisOutcome)

    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_BALANCE_SHEET, balance)
    request = _request((E.FS_BALANCE_SHEET,))
    first, _ = run_orchestration_v3(request)
    snapshot = snapshot_from_terminal_result_v3(first)
    resumed, _ = run_orchestration_v3(replace(request, previous_execution_snapshot=snapshot))
    assert calls["balance"] == 1
    assert resumed.engine_records[0].status.value == "reused"

    bad_engine = replace(snapshot.engine_snapshots[0], engine_model_version_used="9.9.9")
    corrupted = replace(snapshot, engine_snapshots=(bad_engine,))
    rejected, _ = run_orchestration_v3(replace(request, previous_execution_snapshot=corrupted))
    assert calls["balance"] == 1
    assert rejected.engine_records[0].status.value == "failed"
    assert rejected.structured_errors[0].category.value == "version_incompatible_on_reuse"
