import ast
from pathlib import Path


def test_engine_layer_has_no_persistence_or_sqlalchemy_imports():
    root = Path(__file__).parents[1] / "app" / "engines"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        assert not any(module.startswith(("sqlalchemy", "app.orchestration_persistence")) for module in modules), path


def test_no_event_stream_or_full_run_payload_owner_was_added():
    root = Path(__file__).parents[1] / "app" / "models" / "orchestration_persistence.py"
    source = root.read_text(encoding="utf-8")
    assert "orchestration_events" not in source
    assert "full_run" not in source
