"""
Milestone 5.0A -- Kategori G: Property/determinizm testleri (Bolum 67-G).
Bolum 29'daki iki ayri determinizm ozelliginin (`BUSINESS_PAYLOAD_
DETERMINISM` / `FULL_RESULT_DETERMINISM`) calisma-zamani kaniti.
"""

import dataclasses
from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import EngineCode
from tests._orch_fakes import build_request, make_constant_fake_dispatch


def _business_payload(result):
    """Run-kimligi (run_id/correlation_id/generated_at) ve rapor-basligi
    metadata'si (report_id/generated_at -- Bolum 29'un caginin kendisi
    izin verdigi tek fark) DISINDAKI TUM engine_records icerigini
    karsilastirmaya uygun, sabit bir forma indirger."""

    payload = []
    for record in result.engine_records:
        result_obj = record.result.result if record.result is not None else None
        payload.append(
            (
                record.engine_code.value,
                record.status.value,
                record.inner_status_value,
                _strip_identity_fields(result_obj),
            )
        )
    return tuple(payload)


def _strip_identity_fields(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        data = dataclasses.asdict(value)
        data.pop("report_id", None)
        data.pop("generated_at", None)
        return data
    return value


def test_business_payload_determinism_across_different_run_ids():
    fake = make_constant_fake_dispatch()
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        result_a, _ = run_orchestration(
            build_request(run_id="run-X", generated_at="2026-01-01T00:00:00+03:00")
        )
        result_b, _ = run_orchestration(
            build_request(run_id="run-Y", generated_at="2026-06-06T12:00:00+03:00")
        )

    assert result_a.run_id != result_b.run_id
    assert result_a.generated_at != result_b.generated_at
    # Ama is icerigi (business payload) AYNI olmalidir.
    assert _business_payload(result_a) == _business_payload(result_b)
    # request_fingerprint da run_id/generated_at'a bakmadigi icin AYNIDIR.
    assert result_a.request_fingerprint == result_b.request_fingerprint


def test_full_result_determinism_with_identical_request_25_iterations():
    fake = make_constant_fake_dispatch()
    request = build_request(run_id="run-Z", requested_outputs=(EngineCode.RECOMMENDATION,))
    results = []
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        for _ in range(25):
            result, _ = run_orchestration(request)
            results.append(result)

    first = results[0]
    for other in results[1:]:
        assert other.status == first.status
        assert other.request_fingerprint == first.request_fingerprint
        assert other.execution_provenance == first.execution_provenance
        assert _business_payload(other) == _business_payload(first)


def test_registry_insertion_order_independence_does_not_change_run_outcome():
    from app.engines.analysis_orchestrator.execution_plan import _reset_plan_cache_for_tests
    from app.engines.analysis_orchestrator.registry import ENGINE_DEPENDENCY_REGISTRY

    fake = make_constant_fake_dispatch()
    reversed_registry = dict(reversed(list(ENGINE_DEPENDENCY_REGISTRY.items())))

    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        with mock.patch.dict(ENGINE_DEPENDENCY_REGISTRY, reversed_registry, clear=True):
            _reset_plan_cache_for_tests()
            try:
                result_reversed, _ = run_orchestration(
                    build_request(run_id="run-W", requested_outputs=(EngineCode.RECOMMENDATION,))
                )
            finally:
                _reset_plan_cache_for_tests()

        result_forward, _ = run_orchestration(
            build_request(run_id="run-W", requested_outputs=(EngineCode.RECOMMENDATION,))
        )

    assert result_forward.execution_provenance.engine_call_sequence == (
        result_reversed.execution_provenance.engine_call_sequence
    )
