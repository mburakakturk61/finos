"""
Milestone 5.0A -- Analysis Orchestrator test suite icin paylasilan sahte
(fake) motor sonucu fabrikalari.

Bu modul, orchestrator testlerinin `ORCHESTRATOR_ENGINE_DISPATCH`'teki
GERCEK motor callable'larini `unittest.mock.patch`/dogrudan sozluk atamasi
ile SAHTE, testte kontrol edilebilen fonksiyonlarla degistirmesini
kolaylastirir (bkz. tasarim dokumani Bolum 65 -- "testlerde tek tek
callable'larin degistirilmesi yeterlidir, registry'ye dokunulmaz").

Her `fake_result_for(engine_code, ...)` cagrisi, `app.engines.analysis_
orchestrator.service`'in `_map_inner_status`/`_extract_versions`
fonksiyonlarinin BEKLEDIGI TAM sekli (attribute/dict anahtar adlari) taklit
eden, GERCEK motor dataclass'larina ihtiyac duymayan hafif nesneler uretir.
"""

from __future__ import annotations

import types
from typing import Any

from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineRawInputs,
    OrchestrationRunOptions,
    OrchestrationRunRequest,
)


def _ns(**kwargs: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kwargs)


def fs_outcome(*, status: str = "completed", facts: "dict | None" = None) -> Any:
    result_json = None
    if status == "completed":
        result_json = {"engine": "fs", "engine_version": "1.0", "facts": facts or {"x": 1.0}}
    return _ns(status=_ns(value=status), result_json=result_json, source_mode=None, error_message=None)


def ratio_result(*, all_not_calculable: bool = False) -> "dict[str, Any]":
    if all_not_calculable:
        categories = {"liquidity": {"status": "not_calculable", "ratios": {}}}
    else:
        categories = {
            "liquidity": {
                "status": "calculated",
                "ratios": {"current_ratio": {"status": "calculated", "value": 1.5}},
            }
        }
    return {
        "engine": "financial_ratios",
        "engine_version": "1.0",
        "schema_version": "1.0",
        "ratio_registry_version": "1.1.0",
        "categories": categories,
        "missing_categories": [],
    }


def benchmark_result(*, any_evaluated: bool = True) -> "dict[str, Any]":
    status = "evaluated" if any_evaluated else "not_calculable"
    return {
        "engine": "benchmarks",
        "engine_version": "1.0",
        "benchmark_registry_version": "1.0.0",
        "ratio_registry_version": "1.1.0",
        "categories": {"liquidity": {"ratios": {"current_ratio": {"status": status}}}},
    }


def health_score_result(*, status: str = "computed") -> Any:
    return _ns(
        status=_ns(value=status),
        final_score=80.0 if status == "computed" else None,
        health_score_schema_version="1.0",
        health_score_model_version="1.0",
    )


def credit_score_result(*, status: str = "computed") -> Any:
    return _ns(
        status=_ns(value=status),
        final_score=70.0 if status == "computed" else None,
        credit_score_schema_version="1.0",
        credit_score_model_version="1.0",
    )


def recommendation_result(*, status: str = "computed") -> Any:
    return _ns(
        status=_ns(value=status),
        recommendations=(),
        recommendation_schema_version="1.0",
        recommendation_model_version="1.0",
    )


def executive_report_result(*, status: str = "computed") -> Any:
    return _ns(
        status=_ns(value=status),
        sections=(),
        report_schema_version="1.0",
        report_model_version="1.0",
    )


def dashboard_snapshot(*, widgets: "tuple | None" = ()) -> Any:
    return _ns(
        widgets=widgets if widgets is not None else (),
        dashboard_schema_version="1.0",
        dashboard_model_version="1.0",
    )


def render_contract_preview() -> Any:
    return _ns(render_metadata=_ns(render_contract_schema_version="1.0"))


def default_success_result(engine_code: EngineCode) -> Any:
    """Verilen engine_code icin, motor gercekten cagirilsaydi URETECEGI
    turden, "her sey basarili" bir sahte sonuc doner."""

    EC = EngineCode
    mapping = {
        EC.FS_BALANCE_SHEET: lambda: fs_outcome(status="completed"),
        EC.FS_INCOME_STATEMENT: lambda: fs_outcome(status="completed"),
        EC.RATIO: lambda: ratio_result(all_not_calculable=False),
        EC.BENCHMARK: lambda: benchmark_result(any_evaluated=True),
        EC.HEALTH_SCORE: lambda: health_score_result(status="computed"),
        EC.CREDIT_SCORE: lambda: credit_score_result(status="computed"),
        EC.RECOMMENDATION: lambda: recommendation_result(status="computed"),
        EC.EXECUTIVE_REPORT: lambda: executive_report_result(status="computed"),
        EC.DASHBOARD: lambda: dashboard_snapshot(widgets=({"w": 1},)),
        EC.RENDER_CONTRACT: lambda: render_contract_preview(),
    }
    return mapping[engine_code]()


def make_constant_fake_dispatch(overrides: "dict[EngineCode, Any] | None" = None):
    """
    HER motor icin "basarili" bir sahte sonuc doren, argumanlari yok sayan
    callable'lardan olusan tam bir dispatch sozlugu uretir. `overrides`
    ile belirli motor kodlari icin farkli bir sabit deger (veya bir
    exception firlatan callable) enjekte edilebilir.

    Donen sozluk, `ORCHESTRATOR_ENGINE_DISPATCH`'in TEK TEK anahtarlarinin
    `unittest.mock.patch.dict` ile gecici olarak degistirilmesinde
    kullanilir -- registry.py'ye HIC DOKUNULMAZ (Bolum 65).
    """

    overrides = overrides or {}
    fake: "dict[EngineCode, Any]" = {}
    for code in EngineCode:
        if code in overrides:
            value = overrides[code]
            if callable(value) and not isinstance(value, (dict, tuple)):
                fake[code] = value
            else:
                fake[code] = (lambda v=value: (lambda *a, **kw: v))()
        else:
            fake[code] = (lambda c=code: (lambda *a, **kw: default_success_result(c)))()
    return fake


def build_request(
    *,
    run_id: str = "run-1",
    correlation_id: "str | None" = "corr-1",
    generated_at: "str | None" = "2026-01-01T00:00:00+03:00",
    requested_outputs=(EngineCode.RECOMMENDATION,),
    engine_inputs: "EngineRawInputs | None" = None,
    run_options: "OrchestrationRunOptions | None" = None,
    previous_execution_snapshot=None,
) -> OrchestrationRunRequest:
    """Orkestrator testleri icin makul varsayilanlarla bir
    `OrchestrationRunRequest` insa eder. `engine_inputs`/`run_options`
    verilmezse, sahte motorlarin (bkz. yukarisi) argumanlari YOK SAYMASI
    sayesinde bos/varsayilan degerler yeterlidir."""

    return OrchestrationRunRequest(
        run_id=run_id,
        correlation_id=correlation_id,
        generated_at=generated_at,
        requested_outputs=tuple(requested_outputs),
        engine_inputs=engine_inputs if engine_inputs is not None else EngineRawInputs(),
        run_options=run_options if run_options is not None else OrchestrationRunOptions(),
        previous_execution_snapshot=previous_execution_snapshot,
    )
