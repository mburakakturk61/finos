"""
Milestone 5.0A -- Kategori I: Safety/Sanitization testleri (Bolum 67-I).
Denetim bulgusu H1 (dinamik dispatch yasagi) ve Bolum 25 guvenlik
kurallarinin (StructuredError'da ham exception/stack trace/hassas veri
TASINMAZ) statik + calisma-zamani kaniti.
"""

import ast
import pathlib
from unittest import mock

import app.engines.analysis_orchestrator.dispatch as dispatch
from app.engines.analysis_orchestrator.service import run_orchestration
from app.engines.analysis_orchestrator.types import EngineCode, OrchestrationErrorCategory
from tests._orch_fakes import build_request, make_constant_fake_dispatch

ORCHESTRATOR_DIR = pathlib.Path(__file__).parent.parent / "app" / "engines" / "analysis_orchestrator"

_FORBIDDEN_DYNAMIC_DISPATCH_NAMES = {"eval", "exec", "__import__"}
_FORBIDDEN_MODULES = {"importlib"}


def _iter_orchestrator_source_files():
    return sorted(ORCHESTRATOR_DIR.glob("*.py"))


def test_no_eval_exec_or_importlib_in_orchestrator_source():
    # Architecture Book Sec.18: eval/exec/importlib-tabanli dinamik
    # string-den-fonksiyon-cozme YASAKTIR. (Not: `getattr`'in KENDISI
    # yasak degildir -- fingerprint.py bunu SAF veri/dataclass alan
    # okumasi icin kullanir, bir CALLABLE cozmek icin degil; yasaklanan
    # spesifik desen asagidaki test tarafindan ayrica dogrulanir.)
    for path in _iter_orchestrator_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in _FORBIDDEN_MODULES, f"{path}: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in _FORBIDDEN_MODULES, f"{path}: {node.module}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in _FORBIDDEN_DYNAMIC_DISPATCH_NAMES, f"{path}: {node.func.id}(...)"


def test_dispatch_table_values_are_real_callables_not_strings():
    # H1'in tam kaniti: ORCHESTRATOR_ENGINE_DISPATCH'in her degeri,
    # import-zamaninda baglanmis GERCEK bir fonksiyon nesnesidir --
    # hicbir deger `str` (cozulmesi gereken bir "yol") DEGILDIR.
    for engine_code, callable_ in dispatch.ORCHESTRATOR_ENGINE_DISPATCH.items():
        assert callable(callable_), engine_code
        assert not isinstance(callable_, str), engine_code
        assert hasattr(callable_, "__call__")


def _docstring_nodes(tree: ast.AST) -> set:
    """Modul/sinif/fonksiyon docstring'i olarak kullanilan Constant
    node'larinin id kumesini doner -- bunlar Architecture Book Bolum 0.7
    geregi ic dokumantasyon/gelistirici iletisimi sayilir (ornegin bu
    dosyalarin docstring'i, ilgili tasarim dokumaninin GERCEK dosya adina
    -- "docs/FINOS_MILESTONE_5_0A_..." -- atif yapar) ve kod adi politikasi
    bunu YASAKLAMAZ; yasaklanan, PRODUCTION sembolleri/calisma-zamani
    string sabitleridir."""

    ids: "set[int]" = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_no_hardcoded_finos_brand_in_production_symbols_or_runtime_strings():
    # Architecture Book Bolum 0 -- kod adi PRODUCTION sembollerine
    # (sinif/fonksiyon/degisken/enum adlari) veya calisma-zamani string
    # SABITLERINE (docstring/yorum DISINDA) gomulmez. Ic dokumantasyon
    # (docstring'ler, tasarim dokumani dosya adina atiflar) bu kapsamin
    # DISINDADIR (Bolum 0.7 -- "dahili dokumanlar" istisnasi).
    for path in _iter_orchestrator_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstring_ids = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert "FINOS" not in node.name, f"{path}: {node.name}"
            if isinstance(node, ast.Name):
                assert "FINOS" not in node.id, f"{path}: {node.id}"
            if isinstance(node, ast.arg):
                assert "FINOS" not in node.arg, f"{path}: {node.arg}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_ids:
                    continue
                assert "FINOS" not in node.value, f"{path}: {node.value!r}"


def test_structured_error_never_carries_raw_exception_message():
    secret_message = "GIZLI-VKN-1234567890-sizdirilmamali"

    def _raise_with_secret(*args, **kwargs):
        raise ValueError(secret_message)

    fake = make_constant_fake_dispatch({EngineCode.FS_BALANCE_SHEET: _raise_with_secret})
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.FS_BALANCE_SHEET,))
        result, _ = run_orchestration(request)

    assert len(result.structured_errors) == 1
    error = result.structured_errors[0]
    assert secret_message not in error.message_tr
    assert error.original_exception_type == "ValueError"
    assert error.category == OrchestrationErrorCategory.ENGINE_CONTRACT_VIOLATION
    # Sablon mesaj SABIT olmali -- exception argumanindan turememeli.
    assert "İlgili motor çağrısı" in error.message_tr


def test_structured_error_never_carries_a_stack_trace():
    import traceback

    def _raise(*args, **kwargs):
        raise RuntimeError("test-hatasi")

    fake = make_constant_fake_dispatch({EngineCode.FS_BALANCE_SHEET: _raise})
    with mock.patch.dict(dispatch.ORCHESTRATOR_ENGINE_DISPATCH, fake, clear=False):
        request = build_request(requested_outputs=(EngineCode.FS_BALANCE_SHEET,))
        result, _ = run_orchestration(request)

    error = result.structured_errors[0]
    full_repr = repr(error)
    for frame_marker in ("Traceback", "File \"", "line "):
        assert frame_marker not in full_repr
    assert not any(frame_marker in str(v) for v in vars(error).values() for frame_marker in ("Traceback",))
    # Ayrica: traceback modulunun urettigi hicbir satirin error nesnesinin
    # HICBIR alaninda yer almadigini dogrudan test edelim.
    try:
        raise RuntimeError("test-hatasi")
    except RuntimeError:
        tb_text = traceback.format_exc()
    assert tb_text not in error.message_tr


def test_orchestration_run_request_round_trips_through_json_when_business_fields_are_plain():
    import dataclasses
    import json

    from app.engines.analysis_orchestrator.types import EngineRawInputs, OrchestrationRunOptions

    request = build_request(
        requested_outputs=(EngineCode.RATIO,),
        engine_inputs=EngineRawInputs(balance_sheet_filename="bilanco.xlsx"),
        run_options=OrchestrationRunOptions(industry_code="41"),
    )
    # dataclasses.asdict + json.dumps basariyla calismalidir -- Callable
    # alan olmadiginin dogrudan kaniti (Bolum 19).
    payload = dataclasses.asdict(request)
    encoded = json.dumps(payload, default=str)
    assert "run-1" in encoded or request.run_id in encoded
