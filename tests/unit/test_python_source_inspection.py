from pathlib import Path

from openframe.features.model.importers.python_source import inspect_python_source


def test_detects_openseespy_import(tmp_path: Path) -> None:
    source = tmp_path / "model.py"
    source.write_text("import openseespy.opensees as ops\n", encoding="utf-8")

    inspection = inspect_python_source(source)

    assert inspection.imports_openseespy is True
    assert inspection.syntax_errors == ()
