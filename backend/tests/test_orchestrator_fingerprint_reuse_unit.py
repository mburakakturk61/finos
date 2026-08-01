"""
Milestone 5.0A -- Kategori E: Fingerprint/Reuse testleri (Bolum 67-E).
Denetim bulgusu R1'in ("reuse yalnizca versiyon esitligine bakiyordu,
GERCEK girdi esitligine bakmiyordu") kok-neden cozumunun kaniti.
"""

from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.fingerprint import canonical_hash, compute_engine_input_fingerprint
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineExecutionStatus,
    FINGERPRINT_SCHEMA_VERSION,
    OrchestrationErrorCategory,
    PreviousEngineSnapshot,
    PreviousExecutionSnapshot,
    RunStatus,
)
from tests._orch_fakes import build_request, make_constant_fake_dispatch


def _run(request):
    fake = make_constant_fake_dispatch()
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        return run_orchestration(request)


def test_canonical_hash_is_deterministic_and_key_order_independent():
    a = canonical_hash({"x": 1, "y": {"b": 2, "a": 1}})
    b = canonical_hash({"y": {"a": 1, "b": 2}, "x": 1})
    assert a == b


def test_canonical_hash_preserves_tuple_order():
    a = canonical_hash({"seq": (1, 2, 3)})
    b = canonical_hash({"seq": (3, 2, 1)})
    assert a != b


def test_canonical_hash_of_decimal_and_enum_and_bytes_is_stable():
    from decimal import Decimal

    h1 = canonical_hash({"d": Decimal("1.50"), "content": b"abc"})
    h2 = canonical_hash({"d": Decimal("1.50"), "content": b"abc"})
    assert h1 == h2


def test_same_run_id_same_fingerprint_allows_full_reuse():
    request1 = build_request(run_id="run-A")
    result1, _ = _run(request1)

    snapshots = tuple(
        PreviousEngineSnapshot(
            engine_code=r.engine_code,
            execution_status=r.status,
            engine_schema_version_used=r.engine_schema_version_used,
            engine_model_version_used=r.engine_model_version_used,
            input_fingerprint=r.input_fingerprint,
            fingerprint_schema_version=r.fingerprint_schema_version,
            result_ref=r.result.result if r.result is not None else None,
        )
        for r in result1.engine_records
        if r.status in (EngineExecutionStatus.COMPLETED, EngineExecutionStatus.DEGRADED)
    )
    previous = PreviousExecutionSnapshot(
        previous_run_id="run-A",
        request_fingerprint=result1.request_fingerprint,
        orchestration_schema_version=result1.orchestration_schema_version,
        orchestration_model_version=result1.orchestration_model_version,
        execution_plan_version=result1.execution_plan_version,
        engine_snapshots=snapshots,
    )

    request2 = build_request(run_id="run-A", previous_execution_snapshot=previous)
    result2, _ = _run(request2)

    expected_codes = {r.engine_code for r in result1.engine_records}
    reused = {r.engine_code for r in result2.engine_records if r.status == EngineExecutionStatus.REUSED}
    assert reused == expected_codes
    assert set(result2.execution_provenance.reused_engine_codes) == expected_codes


def test_same_run_id_different_fingerprint_is_rejected():
    request1 = build_request(run_id="run-B")
    result1, _ = _run(request1)

    previous = PreviousExecutionSnapshot(
        previous_run_id="run-B",
        request_fingerprint="totally-different-fingerprint",
        orchestration_schema_version=result1.orchestration_schema_version,
        orchestration_model_version=result1.orchestration_model_version,
        execution_plan_version=result1.execution_plan_version,
        engine_snapshots=(),
    )
    request2 = build_request(run_id="run-B", previous_execution_snapshot=previous)
    result2, _ = _run(request2)

    assert result2.status == RunStatus.FAILED
    assert len(result2.structured_errors) == 1
    assert result2.structured_errors[0].category == OrchestrationErrorCategory.FINGERPRINT_MISMATCH_ON_REUSE
    assert result2.engine_records == ()


def test_reuse_rejected_when_engine_input_fingerprint_differs():
    request1 = build_request(run_id="run-C", requested_outputs=(EngineCode.HEALTH_SCORE,))
    result1, _ = _run(request1)

    snapshots = tuple(
        PreviousEngineSnapshot(
            engine_code=r.engine_code,
            execution_status=r.status,
            engine_schema_version_used=r.engine_schema_version_used,
            engine_model_version_used=r.engine_model_version_used,
            input_fingerprint="deliberately-wrong-fingerprint",
            fingerprint_schema_version=r.fingerprint_schema_version,
            result_ref=r.result.result if r.result is not None else None,
        )
        for r in result1.engine_records
    )
    previous = PreviousExecutionSnapshot(
        "run-C", result1.request_fingerprint, result1.orchestration_schema_version,
        result1.orchestration_model_version, result1.execution_plan_version, snapshots,
    )
    request2 = build_request(
        run_id="run-C", requested_outputs=(EngineCode.HEALTH_SCORE,), previous_execution_snapshot=previous
    )
    result2, _ = _run(request2)

    assert all(r.status != EngineExecutionStatus.REUSED for r in result2.engine_records)


def test_reuse_rejected_when_fingerprint_schema_version_differs():
    request1 = build_request(run_id="run-D", requested_outputs=(EngineCode.RATIO,))
    result1, _ = _run(request1)

    snapshots = tuple(
        PreviousEngineSnapshot(
            r.engine_code, r.status, r.engine_schema_version_used, r.engine_model_version_used,
            r.input_fingerprint, "0.0.1-old", r.result.result if r.result is not None else None,
        )
        for r in result1.engine_records
    )
    previous = PreviousExecutionSnapshot(
        "run-D", result1.request_fingerprint, result1.orchestration_schema_version,
        result1.orchestration_model_version, result1.execution_plan_version, snapshots,
    )
    request2 = build_request(
        run_id="run-D", requested_outputs=(EngineCode.RATIO,), previous_execution_snapshot=previous
    )
    result2, _ = _run(request2)

    assert all(r.status != EngineExecutionStatus.REUSED for r in result2.engine_records)


def test_transitive_invalidation_blocks_downstream_reuse_when_upstream_recomputed():
    # Bolum 31 madde 7: bir upstream BU run'da fiilen yeniden hesaplandiysa
    # (reuse edilmediyse), kendi fingerprint'i eslesse bile downstream
    # ARTIK reuse EDILEMEZ. Burada FS_BALANCE_SHEET icin bilerek EKSIK bir
    # (dolayisiyla reuse edilemeyen) PreviousEngineSnapshot birakiyoruz --
    # RATIO'nun kendi input_fingerprint'i (FS ciktilarindan turedigi icin)
    # otomatik olarak degisecek ve reuse zaten fingerprint uyumsuzlugundan
    # da REDDEDILECEKTIR -- bu, tasarimin iki savunma katmaninin (fingerprint
    # zinciri + transitif kural) TUTARLI calistigini kanitlar.
    request1 = build_request(run_id="run-E", requested_outputs=(EngineCode.RATIO,))
    result1, _ = _run(request1)
    records = {r.engine_code: r for r in result1.engine_records}

    snapshots = (
        PreviousEngineSnapshot(
            EngineCode.RATIO,
            records[EngineCode.RATIO].status,
            records[EngineCode.RATIO].engine_schema_version_used,
            records[EngineCode.RATIO].engine_model_version_used,
            records[EngineCode.RATIO].input_fingerprint,
            records[EngineCode.RATIO].fingerprint_schema_version,
            records[EngineCode.RATIO].result.result,
        ),
        # FS_BALANCE_SHEET/FS_INCOME_STATEMENT icin BILEREK snapshot YOK --
        # bu run'da yeniden hesaplanacaklar.
    )
    previous = PreviousExecutionSnapshot(
        "run-E", result1.request_fingerprint, result1.orchestration_schema_version,
        result1.orchestration_model_version, result1.execution_plan_version, snapshots,
    )
    request2 = build_request(
        run_id="run-E", requested_outputs=(EngineCode.RATIO,), previous_execution_snapshot=previous
    )
    result2, _ = _run(request2)
    records2 = {r.engine_code: r for r in result2.engine_records}

    assert records2[EngineCode.FS_BALANCE_SHEET].status != EngineExecutionStatus.REUSED
    assert records2[EngineCode.RATIO].status != EngineExecutionStatus.REUSED


def test_engine_input_fingerprint_changes_when_dependent_run_option_changes():
    from app.engines.analysis_orchestrator.types import EngineRawInputs, OrchestrationRunOptions

    fp_a = compute_engine_input_fingerprint(
        EngineCode.BENCHMARK,
        raw_inputs=EngineRawInputs(),
        run_options=OrchestrationRunOptions(industry_code="A"),
        upstream_fingerprints={EngineCode.RATIO: "same-ratio-fp"},
    )
    fp_b = compute_engine_input_fingerprint(
        EngineCode.BENCHMARK,
        raw_inputs=EngineRawInputs(),
        run_options=OrchestrationRunOptions(industry_code="B"),
        upstream_fingerprints={EngineCode.RATIO: "same-ratio-fp"},
    )
    assert fp_a != fp_b


def test_engine_input_fingerprint_unaffected_by_unrelated_run_option():
    from app.engines.analysis_orchestrator.types import EngineRawInputs, OrchestrationRunOptions

    fp_a = compute_engine_input_fingerprint(
        EngineCode.BENCHMARK,
        raw_inputs=EngineRawInputs(),
        run_options=OrchestrationRunOptions(industry_code="A", tenant_id="tenant-1"),
        upstream_fingerprints={EngineCode.RATIO: "same-ratio-fp"},
    )
    fp_b = compute_engine_input_fingerprint(
        EngineCode.BENCHMARK,
        raw_inputs=EngineRawInputs(),
        run_options=OrchestrationRunOptions(industry_code="A", tenant_id="tenant-2"),
        upstream_fingerprints={EngineCode.RATIO: "same-ratio-fp"},
    )
    # Benchmark tenant_id'yi TUKETMEZ (Bolum 41 tablosu) -- fingerprint
    # ETKILENMEMELIDIR.
    assert fp_a == fp_b


def test_fingerprint_schema_version_constant_is_used_by_default():
    result, _ = _run(build_request(run_id="run-F", requested_outputs=(EngineCode.RATIO,)))
    for record in result.engine_records:
        assert record.fingerprint_schema_version == FINGERPRINT_SCHEMA_VERSION
