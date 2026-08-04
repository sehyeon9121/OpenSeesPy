from pathlib import Path

from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter


def _import(source: Path):
    return OpenSeesModelImporter(timeout_seconds=20).load(source)


def test_imports_an_uncalled_library_style_builder(tmp_path: Path) -> None:
    source = tmp_path / "library_model.py"
    source.write_text(
        """
from openseespy.opensees import *

def build_model():
    span = 5.0
    wipe()
    model('basic', '-ndm', 2, '-ndf', 3)
    node(1, 0.0, 0.0)
    node(2, span, 0.0)
    fix(1, 1, 1, 1)
    geomTransf('Linear', 1)
    element('elasticBeamColumn', 1, 1, 2, 1.0, 200000.0, 1.0, 1)
""",
        encoding="utf-8",
    )

    model = _import(source)

    assert len(model.nodes) == 2
    assert model.nodes[2].x == 5.0
    assert len(model.elements) == 1


def test_imports_a_main_file_that_delegates_to_a_local_helper(tmp_path: Path) -> None:
    helper = tmp_path / "frame_builder.py"
    helper.write_text(
        """
import openseespy.opensees as ops

def build():
    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 3)
    ops.node(1, 0.0, 0.0)
    ops.node(2, 0.0, 3.0)
    ops.fix(1, 1, 1, 1)
    ops.geomTransf('Linear', 1)
    ops.element('elasticBeamColumn', 1, 1, 2, 1.0, 200000.0, 1.0, 1)
""",
        encoding="utf-8",
    )
    source = tmp_path / "main_model.py"
    source.write_text("from frame_builder import build\nbuild()\n", encoding="utf-8")

    model = _import(source)

    assert len(model.nodes) == 2
    assert model.nodes[2].y == 3.0
    assert len(model.elements) == 1


def test_imports_a_legacy_cp949_python_source(tmp_path: Path) -> None:
    source = tmp_path / "legacy_korean_model.py"
    text = """
# 한글 주석이 포함된 기존 구조 모델
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 4.0, 0.0)
ops.fix(1, 1, 1, 0)
ops.geomTransf('Linear', 1)
ops.element('elasticBeamColumn', 1, 1, 2, 1.0, 200000.0, 1.0, 1)
"""
    source.write_bytes(text.encode("cp949"))

    model = _import(source)

    assert len(model.nodes) == 2
    assert len(model.elements) == 1
