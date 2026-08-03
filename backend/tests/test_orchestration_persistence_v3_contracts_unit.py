from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.engines.analysis_orchestrator.types import OrchestrationRunResult as LegacyRunResult
from app.engines.analysis_orchestrator_v3.types import (
    EngineExecutionStatusV3,
    EngineResultEnvelopeV3,
    ExecutionProvenanceV3,
    OrchestrationEngineCodeV3,
    OrchestrationJsonObjectV3,
    OrchestrationRunResultV3,
    PerEngineExecutionRecordV3,
    RunStatusV3,
)
from app.orchestration_persistence_v3.snapshot import snapshot_from_terminal_result_v3
from app.orchestration_persistence_v3.cash_flow_codec import (
    CashFlowFinancialResultCodecError,
    cash_flow_owner_content_digest,
    decode_cash_flow_financial_result,
    encode_cash_flow_financial_result,
)
from app.orchestration_persistence_v3.types import (
    FinancialResultOwnerBindingV3,
    PersistenceRunScopeV3,
    ResumeEngineBindingV3,
)
from test_cash_flow_contracts_unit import _result


def _run():
    envelope = EngineResultEnvelopeV3(
        OrchestrationEngineCodeV3.FS_BALANCE_SHEET,
        "BalanceSheetAnalysisOutcomeV3",
        OrchestrationJsonObjectV3((("engine_version", "1.0.0"),)),
    )
    record = PerEngineExecutionRecordV3(
        engine_code=OrchestrationEngineCodeV3.FS_BALANCE_SHEET,
        status=EngineExecutionStatusV3.COMPLETED,
        result=envelope,
        inner_status_value="completed",
        error=None,
        dependency_engine_codes=(),
        engine_schema_version_used=None,
        engine_model_version_used="1.0.0",
        input_fingerprint="a" * 64,
        fingerprint_schema_version="1.0.0",
    )
    return OrchestrationRunResultV3(
        run_id="run-v3",
        correlation_id="corr",
        generated_at="2026-01-01T00:00:00+00:00",
        status=RunStatusV3.FULLY_COMPLETED,
        engine_records=(record,),
        warnings=(),
        structured_errors=(),
        execution_provenance=ExecutionProvenanceV3("3.0.0", (record.engine_code,), (), ()),
        input_version_inventory=OrchestrationJsonObjectV3((("fs_balance_sheet_model_version", "1.0.0"),)),
        orchestration_schema_version="3.0.0",
        orchestration_model_version="3.0.0",
        execution_plan_version="3.0.0",
        request_fingerprint="b" * 64,
    )


def test_snapshot_v3_round_trip_preserves_engine_result_envelope_result():
    run = _run()
    snapshot = snapshot_from_terminal_result_v3(run)
    assert snapshot.previous_run_id == run.run_id
    assert snapshot.engine_snapshots[0].result is run.engine_records[0].result
    assert snapshot.engine_snapshots[0].result.result is run.engine_records[0].result.result


def test_snapshot_v3_rejects_legacy_result_without_upcast():
    with pytest.raises(TypeError):
        snapshot_from_terminal_result_v3(object())


def test_resume_binding_owner_xor_and_digest_rules_are_fail_closed():
    execution_id = UUID("10000000-0000-0000-0000-000000000001")
    owner_id = UUID("20000000-0000-0000-0000-000000000001")
    valid = ResumeEngineBindingV3(
        OrchestrationEngineCodeV3.CASH_FLOW, execution_id, None, owner_id,
        "a" * 64, "b" * 64, "c" * 64, "1.0.0", "1.0.0",
    )
    assert valid.financial_analysis_result_id == owner_id
    with pytest.raises(ValueError):
        ResumeEngineBindingV3(
            OrchestrationEngineCodeV3.CASH_FLOW, execution_id, owner_id, owner_id,
            "a" * 64, "b" * 64, "c" * 64, "1.0.0", "1.0.0",
        )
    with pytest.raises(ValueError):
        ResumeEngineBindingV3(
            OrchestrationEngineCodeV3.CASH_FLOW, execution_id, None, owner_id,
            None, "b" * 64, "c" * 64, "1.0.0", "1.0.0",
        )


def test_v3_scope_and_contracts_are_immutable():
    scope = PersistenceRunScopeV3(
        UUID("10000000-0000-0000-0000-000000000001"),
        UUID("20000000-0000-0000-0000-000000000001"),
        UUID("30000000-0000-0000-0000-000000000001"),
    )
    with pytest.raises(FrozenInstanceError):
        scope.period_id = UUID("40000000-0000-0000-0000-000000000001")


def test_cash_flow_financial_owner_codec_round_trip_is_strict_and_deterministic():
    source = _result()
    node, digest = encode_cash_flow_financial_result(source)
    assert decode_cash_flow_financial_result(node, digest) == source
    assert encode_cash_flow_financial_result(source) == (node, digest)
    assert len(cash_flow_owner_content_digest(source)) == 64


def test_cash_flow_financial_owner_codec_rejects_payload_and_digest_corruption():
    node, digest = encode_cash_flow_financial_result(_result())
    corrupted = dict(node)
    corrupted["name"] = "cf.period_descriptor.v1"
    with pytest.raises(CashFlowFinancialResultCodecError):
        decode_cash_flow_financial_result(corrupted, digest)
    with pytest.raises(CashFlowFinancialResultCodecError):
        decode_cash_flow_financial_result(node, "f" * 64)


def test_cash_flow_financial_owner_codec_rejects_noncanonical_extra_fields():
    node, digest = encode_cash_flow_financial_result(_result())
    with pytest.raises(CashFlowFinancialResultCodecError):
        decode_cash_flow_financial_result({**node, "unexpected": None}, digest)
