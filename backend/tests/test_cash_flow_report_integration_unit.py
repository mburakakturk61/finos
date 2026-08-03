from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from enum import Enum

import pytest

from app.engines.analysis_orchestrator_v3.fingerprint import compute_engine_input_fingerprint_v3
from app.engines.analysis_orchestrator_v3.service import run_orchestration_v3
from app.engines.analysis_orchestrator_v3.types import (
    EngineExecutionStatusV3,
    OrchestrationEngineCodeV3 as E,
    OrchestrationRunOptionsV3,
)
from app.engines.balance_sheet.service import BalanceSheetAnalysisOutcome
from app.engines.cash_flow import (
    CashFlowEngineFailure,
    CashFlowEngineOutcome,
    CashFlowErrorCode,
    CashFlowEvidenceKind,
    CashFlowLineCode,
    CashFlowReconciliationStatus,
    CashFlowResultStatus,
    canonical_cash_flow_digest,
    canonical_policy_bundle_digest,
)
from app.engines.common.report_types import ReportSectionCode, ReportType
from app.engines.executive_reports.cash_flow_integration import (
    REPORT_MODEL_VERSION_V1_1_CASH_FLOW,
    REPORT_REGISTRY_V1_1_CASH_FLOW,
    REPORT_SCHEMA_VERSION_V1_1_CASH_FLOW,
    REPORT_SOURCE_ENGINE_INVENTORY_V1_1_CASH_FLOW,
    CashFlowReportSourceStatus,
    generate_executive_report_v1_1,
    project_cash_flow_report_source_v1,
)
from app.engines.income_statement.service import IncomeStatementAnalysisOutcome
from app.engines.render_contract.service import preview_render_contract
from app.models.enums import AnalysisStatus, SourceMode
from app.orchestration_persistence_v3.snapshot import snapshot_from_terminal_result_v3

from test_cash_flow_contracts_unit import _line, _result
from test_cash_flow_orchestration_v3_unit import _context, _request
from test_cash_flow_ratio_integration_unit import _without_free_cash_flow
from test_render_contract_unit import _FULL_RENDER_CONTRACT
from test_report_pipeline_unit import _build_upstream, _cm


def _cash_result(status: CashFlowResultStatus):
    partial = status in {
        CashFlowResultStatus.PARTIAL_RECONCILED,
        CashFlowResultStatus.PARTIAL_UNRECONCILED,
    }
    if status in {
        CashFlowResultStatus.COMPLETE_UNRECONCILED,
        CashFlowResultStatus.PARTIAL_UNRECONCILED,
    }:
        return _result(
            status=status,
            reconciliation_status=CashFlowReconciliationStatus.UNRECONCILED_NON_MATERIAL,
            opening=Decimal("0.00"),
            closing=Decimal("0.00"),
            operating=Decimal("-2.00"),
            difference=Decimal("2.00"),
            estimated_code=CashFlowLineCode.NET_PROFIT if partial else None,
        )
    if status is CashFlowResultStatus.INSUFFICIENT_DATA:
        return _result(
            status=status,
            reconciliation_status=CashFlowReconciliationStatus.NOT_PERFORMED_INSUFFICIENT_DATA,
            opening=None,
            closing=None,
            operating=None,
            difference=None,
        )
    return _result(
        status=status,
        estimated_code=CashFlowLineCode.NET_PROFIT if partial else None,
    )


@pytest.mark.parametrize(
    "status",
    (
        CashFlowResultStatus.COMPLETE_RECONCILED,
        CashFlowResultStatus.COMPLETE_UNRECONCILED,
        CashFlowResultStatus.PARTIAL_RECONCILED,
        CashFlowResultStatus.PARTIAL_UNRECONCILED,
        CashFlowResultStatus.INSUFFICIENT_DATA,
    ),
)
def test_result_bearing_statuses_project_exactly_without_status_upgrade(status):
    source = _cash_result(status)
    projection = project_cash_flow_report_source_v1(requested=True, result=source)
    assert projection.status.value == status.value
    assert projection.reconciliation_status is source.reconciliation_status
    assert projection.operating_cash_flow is source.operating_cash_flow
    assert projection.result_digest == canonical_cash_flow_digest(source)
    assert projection.result_reference == f"cash-flow-result:sha256:{projection.result_digest}"
    if status is CashFlowResultStatus.INSUFFICIENT_DATA:
        assert all(item.amount is None and not item.available for item in projection.summary_lines)


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (CashFlowResultStatus.INVALID_INPUT, CashFlowErrorCode.INVALID_CONTRACT),
        (CashFlowResultStatus.INTEGRITY_FAILURE, CashFlowErrorCode.SOURCE_DIGEST_MISMATCH),
    ),
)
def test_failure_statuses_are_ownerless_non_financial_projections(status, code):
    projection = project_cash_flow_report_source_v1(
        requested=True, result=None, failure_status=status, failure_code=code,
    )
    assert projection.status.value == status.value
    assert projection.result_reference is None and projection.result_digest is None
    assert projection.completeness is None and projection.reconciliation_status is None
    assert projection.error_codes == (code.value,)
    assert all(item.amount is None for item in projection.summary_lines)


def test_failure_projection_rejects_missing_or_wrong_taxonomy_code():
    with pytest.raises(ValueError):
        project_cash_flow_report_source_v1(
            requested=True,
            result=None,
            failure_status=CashFlowResultStatus.INVALID_INPUT,
            failure_code=None,
        )
    with pytest.raises(ValueError):
        project_cash_flow_report_source_v1(
            requested=True,
            result=None,
            failure_status=CashFlowResultStatus.INVALID_INPUT,
            failure_code=CashFlowErrorCode.SOURCE_DIGEST_MISMATCH,
        )


def test_estimated_and_unavailable_evidence_are_preserved_with_decimal_values():
    estimated = _result(
        status=CashFlowResultStatus.PARTIAL_RECONCILED,
        estimated_code=CashFlowLineCode.OPERATING_CASH_FLOW,
    )
    estimated_projection = project_cash_flow_report_source_v1(requested=True, result=estimated)
    assert any(item.evidence_kind is CashFlowEvidenceKind.ESTIMATED for item in estimated_projection.summary_lines)
    assert estimated_projection.completeness.estimated_count == 1

    unavailable = _without_free_cash_flow(estimated)
    projection = project_cash_flow_report_source_v1(requested=True, result=unavailable)
    fcf = next(item for item in projection.summary_lines if item.line_code is CashFlowLineCode.FREE_CASH_FLOW)
    assert fcf.amount is None and fcf.evidence_kind is CashFlowEvidenceKind.UNAVAILABLE
    assert projection.operating_cash_flow is not None
    assert type(projection.operating_cash_flow) is Decimal


def test_projection_safe_reference_and_lineage_exclude_raw_evidence_details():
    projection = project_cash_flow_report_source_v1(
        requested=True, result=_cash_result(CashFlowResultStatus.COMPLETE_RECONCILED),
    )
    rendered = repr(projection)
    assert "account_codes" not in rendered
    assert "mapping_ids" not in rendered
    assert "result_payload" not in rendered
    assert projection.lineage_references[0].canonical_digest == "a" * 64


def _report(*, cash_flow_requested=True, cash_flow_result=None, **cash_kwargs):
    bs, inc, ratio, benchmark, health, credit, recommendation = _build_upstream()
    return generate_executive_report_v1_1(
        ReportType.CFO_EXECUTIVE_REPORT,
        bs,
        inc,
        ratio,
        benchmark,
        health,
        credit,
        recommendation,
        company_metadata=_cm(),
        reporting_period_label_tr="2024",
        cash_flow_requested=cash_flow_requested,
        cash_flow_result=cash_flow_result,
        **cash_kwargs,
    )


def _cash_blocks(report):
    section = next(
        item for item in report.sections
        if item.section_code is ReportSectionCode.SEC_FINANCIAL_STATEMENTS_SUMMARY
    )
    return tuple(block for block in section.content_blocks if block.source_field_path.startswith("cash_flow_result"))


def test_cash_aware_registry_is_separate_exact_18_and_source_inventory_is_extended():
    report = _report(cash_flow_result=_cash_result(CashFlowResultStatus.COMPLETE_RECONCILED))
    assert len(REPORT_REGISTRY_V1_1_CASH_FLOW) == len(set(REPORT_REGISTRY_V1_1_CASH_FLOW)) == 18
    assert REPORT_REGISTRY_V1_1_CASH_FLOW == tuple(ReportSectionCode)
    assert tuple(item.source_engine for item in report.source_inventory) == REPORT_SOURCE_ENGINE_INVENTORY_V1_1_CASH_FLOW
    assert report.report_schema_version == REPORT_SCHEMA_VERSION_V1_1_CASH_FLOW
    assert report.report_model_version == REPORT_MODEL_VERSION_V1_1_CASH_FLOW
    assert len(report.included_section_codes) <= 18


def test_report_summary_contains_all_nine_canonical_amounts_and_evidence_inventory():
    source = _cash_result(CashFlowResultStatus.COMPLETE_RECONCILED)
    report = _report(cash_flow_result=source)
    blocks = _cash_blocks(report)
    rows = blocks[0].payload["rows"]
    assert {row["field"] for row in rows} == {
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "calculated_net_cash_change", "balance_sheet_net_cash_change",
        "reconciliation_difference", "opening_cash_and_cash_equivalents",
        "closing_cash_and_cash_equivalents", "free_cash_flow",
    }
    assert all(type(row["value"]) is Decimal for row in rows)
    status = blocks[1].payload["rows"][0]
    assert status["computation_status"] == "complete_reconciled"
    assert type(status["available_ratio"]) is Decimal
    assert status["safe_result_reference"].endswith(canonical_cash_flow_digest(source))


@pytest.mark.parametrize(
    "status",
    (
        CashFlowResultStatus.COMPLETE_UNRECONCILED,
        CashFlowResultStatus.PARTIAL_RECONCILED,
        CashFlowResultStatus.PARTIAL_UNRECONCILED,
        CashFlowResultStatus.INSUFFICIENT_DATA,
    ),
)
def test_report_status_warning_behavior_is_explicit_and_deterministic(status):
    first = _report(cash_flow_result=_cash_result(status))
    second = _report(cash_flow_result=_cash_result(status))
    cash_codes = tuple(item["code"] for item in first.warnings if item["code"].startswith("CASH_FLOW_"))
    assert cash_codes
    assert first.warnings == second.warnings
    if status is CashFlowResultStatus.INSUFFICIENT_DATA:
        rows = _cash_blocks(first)[0].payload["rows"]
        assert all(item["value"] is None and item["available"] is False for item in rows)


def test_material_reconciliation_difference_is_explicit_warning():
    source = _result(
        status=CashFlowResultStatus.COMPLETE_UNRECONCILED,
        reconciliation_status=CashFlowReconciliationStatus.UNRECONCILED_MATERIAL,
        opening=Decimal("0.00"), closing=Decimal("0.00"),
        operating=Decimal("-101.00"), difference=Decimal("101.00"),
    )
    report = _report(cash_flow_result=source)
    assert any(item["code"] == "CASH_FLOW_MATERIAL_RECONCILIATION_DIFFERENCE" for item in report.warnings)


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (CashFlowResultStatus.INVALID_INPUT, CashFlowErrorCode.INVALID_CONTRACT),
        (CashFlowResultStatus.INTEGRITY_FAILURE, CashFlowErrorCode.SOURCE_DIGEST_MISMATCH),
    ),
)
def test_report_failure_projection_has_no_financial_payload(status, code):
    report = _report(
        cash_flow_result=None,
        cash_flow_failure_status=status,
        cash_flow_error_code=code,
    )
    rows = _cash_blocks(report)[0].payload["rows"]
    assert all(item["value"] is None for item in rows)
    assert any(item["code"] == "CASH_FLOW_SOURCE_FAILURE" for item in report.warnings)
    assert code.value in repr(_cash_blocks(report))


def test_report_does_not_recompute_cash_flow_or_leak_raw_source_payload(monkeypatch):
    from app.engines.cash_flow.service import CashFlowEngineService

    monkeypatch.setattr(CashFlowEngineService, "analyze", lambda *_args, **_kwargs: pytest.fail("recompute"))
    report = _report(cash_flow_result=_cash_result(CashFlowResultStatus.COMPLETE_RECONCILED))
    rendered = repr(_cash_blocks(report))
    assert "account_codes" not in rendered
    assert "mapping_ids" not in rendered
    assert "trial_balance" not in rendered


def test_legacy_report_path_is_exact_same_object_shape_and_versions():
    report = _report(cash_flow_requested=False)
    assert report.report_schema_version == "1.0.0"
    assert report.report_model_version == "1.0.0"
    assert all(item.source_engine != "cash_flow" for item in report.source_inventory)
    assert not _cash_blocks(report)


def test_cash_aware_report_is_render_contract_compatible():
    report = _report(cash_flow_result=_cash_result(CashFlowResultStatus.COMPLETE_RECONCILED))
    preview = preview_render_contract(report, _FULL_RENDER_CONTRACT)
    assert preview.section_render_order == tuple(item.section_code for item in report.sections)


def _statement(outcome_cls, result_json):
    return outcome_cls(
        AnalysisStatus.COMPLETED,
        SourceMode.MULTI_SOURCE_DERIVED,
        result_json,
        None,
        None,
    )


def _report_request():
    base = _request((E.CASH_FLOW, E.EXECUTIVE_REPORT), context=_context())
    return replace(
        base,
        run_options=OrchestrationRunOptionsV3(
            report_type=ReportType.CFO_EXECUTIVE_REPORT,
            company_metadata=_cm(),
            reporting_period_label_tr="2024",
        ),
    )


def _wire_report_pipeline(monkeypatch, cash_result, calls):
    from app.engines.analysis_orchestrator_v3 import service

    bs, inc, ratio, benchmark, health, credit, recommendation = _build_upstream()

    def canonical(value):
        if type(value) is float:
            return Decimal(str(value))
        if isinstance(value, Enum):
            return value
        if is_dataclass(value):
            return replace(
                value,
                **{field.name: canonical(getattr(value, field.name)) for field in fields(value)},
            )
        if type(value) is dict:
            return {key: canonical(item) for key, item in value.items()}
        if type(value) is list:
            return [canonical(item) for item in value]
        if type(value) is tuple:
            return tuple(canonical(item) for item in value)
        return value

    bs, inc, ratio, benchmark, health, credit, recommendation = tuple(
        canonical(item)
        for item in (bs, inc, ratio, benchmark, health, credit, recommendation)
    )
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_BALANCE_SHEET, lambda **_: _statement(BalanceSheetAnalysisOutcome, bs))
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.FS_INCOME_STATEMENT, lambda **_: _statement(IncomeStatementAnalysisOutcome, inc))

    def cash(**_):
        calls["cash"] += 1
        return CashFlowEngineOutcome(cash_result.status, True, cash_result, None)

    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.CASH_FLOW, cash)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.RATIO, lambda **_: ratio)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.BENCHMARK, lambda *_args, **_kwargs: benchmark)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.HEALTH_SCORE, lambda *_args, **_kwargs: health)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.CREDIT_SCORE, lambda *_args, **_kwargs: credit)
    monkeypatch.setitem(service.ORCHESTRATOR_ENGINE_DISPATCH_V3, E.RECOMMENDATION, lambda *_args, **_kwargs: recommendation)


def test_v3_report_consumes_same_canonical_cash_result_and_uses_v1_1_versions(monkeypatch):
    source = _cash_result(CashFlowResultStatus.COMPLETE_RECONCILED)
    calls = {"cash": 0}
    _wire_report_pipeline(monkeypatch, source, calls)
    run, _ = run_orchestration_v3(_report_request())
    cash = next(item for item in run.engine_records if item.engine_code is E.CASH_FLOW)
    report = next(item for item in run.engine_records if item.engine_code is E.EXECUTIVE_REPORT)
    assert calls["cash"] == 1
    assert cash.result.result is source
    assert report.result.result.report_schema_version == "1.1.0"
    assert (report.engine_schema_version_used, report.engine_model_version_used) == ("1.1.0", "1.1.0")
    assert report.status is EngineExecutionStatusV3.COMPLETED


def test_report_fingerprint_changes_with_cash_digest_policy_and_status():
    request = _report_request()
    complete = _cash_result(CashFlowResultStatus.COMPLETE_RECONCILED)
    partial = _cash_result(CashFlowResultStatus.PARTIAL_RECONCILED)
    first = compute_engine_input_fingerprint_v3(E.EXECUTIVE_REPORT, request, {E.CASH_FLOW: canonical_cash_flow_digest(complete)})
    second = compute_engine_input_fingerprint_v3(E.EXECUTIVE_REPORT, request, {E.CASH_FLOW: canonical_cash_flow_digest(partial)})
    changed_policy = replace(
        complete,
        mapping_registry_version="1.0.1",
        policy_version=canonical_policy_bundle_digest(
            accounting_policy_version=complete.accounting_policy_version,
            cash_equivalent_policy_version=complete.cash_equivalent_policy_version,
            presentation_policy_version=complete.presentation_policy_version,
            reconciliation_policy_version=complete.reconciliation_policy_version,
            mapping_registry_version="1.0.1",
        ),
    )
    third = compute_engine_input_fingerprint_v3(
        E.EXECUTIVE_REPORT,
        request,
        {E.CASH_FLOW: canonical_cash_flow_digest(changed_policy)},
    )
    assert first != second
    assert first != third


def test_v3_cash_aware_report_resume_reuses_v1_1_snapshot(monkeypatch):
    source = _cash_result(CashFlowResultStatus.COMPLETE_RECONCILED)
    calls = {"cash": 0}
    _wire_report_pipeline(monkeypatch, source, calls)
    request = _report_request()
    first, _ = run_orchestration_v3(request)
    snapshot = snapshot_from_terminal_result_v3(first)
    resumed, _ = run_orchestration_v3(replace(request, previous_execution_snapshot=snapshot))
    report = next(item for item in resumed.engine_records if item.engine_code is E.EXECUTIVE_REPORT)
    assert report.status is EngineExecutionStatusV3.REUSED
    assert report.engine_schema_version_used == "1.1.0"
    assert calls["cash"] == 1


def test_v3_corrupt_cash_snapshot_fails_closed_before_report_reuse(monkeypatch):
    source = _cash_result(CashFlowResultStatus.COMPLETE_RECONCILED)
    calls = {"cash": 0}
    _wire_report_pipeline(monkeypatch, source, calls)
    request = _report_request()
    first, _ = run_orchestration_v3(request)
    snapshot = snapshot_from_terminal_result_v3(first)
    corrupted = tuple(
        replace(item, engine_model_version_used="9.9.9") if item.engine_code is E.CASH_FLOW else item
        for item in snapshot.engine_snapshots
    )
    rejected, _ = run_orchestration_v3(
        replace(request, previous_execution_snapshot=replace(snapshot, engine_snapshots=corrupted))
    )
    cash = next(item for item in rejected.engine_records if item.engine_code is E.CASH_FLOW)
    assert cash.status is EngineExecutionStatusV3.FAILED
    assert calls["cash"] == 1


def test_v3_failure_status_is_presented_without_fabricated_cash_payload(monkeypatch):
    from app.engines.analysis_orchestrator_v3 import service

    source = _cash_result(CashFlowResultStatus.COMPLETE_RECONCILED)
    calls = {"cash": 0}
    _wire_report_pipeline(monkeypatch, source, calls)
    monkeypatch.setitem(
        service.ORCHESTRATOR_ENGINE_DISPATCH_V3,
        E.CASH_FLOW,
        lambda **_: CashFlowEngineOutcome(
            CashFlowResultStatus.INTEGRITY_FAILURE,
            False,
            None,
            CashFlowEngineFailure(CashFlowErrorCode.SOURCE_DIGEST_MISMATCH),
        ),
    )
    run, _ = run_orchestration_v3(_report_request())
    report = next(item for item in run.engine_records if item.engine_code is E.EXECUTIVE_REPORT)
    assert report.result.result.report_schema_version == "1.1.0"
    rows = _cash_blocks(report.result.result)[0].payload["rows"]
    assert all(item["value"] is None for item in rows)
