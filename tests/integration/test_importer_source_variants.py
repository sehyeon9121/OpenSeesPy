from pathlib import Path

import pytest

from openframe.core.errors import ModelImportError
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


def test_imports_explicit_native_unit_declaration_into_model_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "declared_units.py"
    source.write_text(
        """
import openseespy.opensees as ops
OPENFRAME_UNITS = {'force': 'kip', 'length': 'inch', 'time': 'sec'}
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Elastic', 1, 1.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
""",
        encoding="utf-8",
    )

    model = _import(source)

    assert model.metadata["unit_force"] == "kip"
    assert model.metadata["unit_length"] == "in"
    assert model.metadata["unit_time"] == "s"
    assert model.metadata["unit_source"] == "OPENFRAME_UNITS"


def test_rejects_unsupported_explicit_native_unit(tmp_path: Path) -> None:
    source = tmp_path / "bad_units.py"
    source.write_text(
        """
import openseespy.opensees as ops
OPENFRAME_UNITS = {'force': 'kgf', 'length': 'cm'}
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Elastic', 1, 1.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
""",
        encoding="utf-8",
    )

    with pytest.raises(ModelImportError, match="kgf"):
        _import(source)


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


def test_imports_nodes_defined_with_inline_mass_flag_arguments(tmp_path: Path) -> None:
    """ops.node() may carry trailing '-mass', m1, m2, ... flag arguments after the
    real coordinates - a very common idiom for lumped-mass models. Only the leading
    `ndm` values are coordinates; the collector must not try to parse '-mass' itself
    as a float.
    """
    source = tmp_path / "mass_flagged_nodes.py"
    source.write_text(
        """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0, '-mass', 1.0, 1.0, 0.0)
ops.node(2, 5.0, 0.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf('Linear', 1)
ops.element('elasticBeamColumn', 1, 1, 2, 1.0, 200000.0, 1.0, 1)
""",
        encoding="utf-8",
    )

    model = _import(source)

    assert (model.nodes[1].x, model.nodes[1].y) == (0.0, 0.0)
    assert (model.nodes[2].x, model.nodes[2].y) == (5.0, 0.0)
    assert len(model.elements) == 1


def test_imports_a_1d_shear_building_model(tmp_path: Path) -> None:
    """ndm=1 models (single-DOF-per-floor shear buildings) pass exactly one
    coordinate to ops.node() - the collector used to require at least two and
    StructuralModel.validate() used to reject ndm=1 outright."""
    source = tmp_path / "shear_building_1d.py"
    source.write_text(
        """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(0, 0.0)
for i in range(1, 4):
    ops.node(i, 0.0, '-mass', 1.0)
ops.fix(0, 1)
ops.uniaxialMaterial('Elastic', 1, 1000.0)
for i in range(1, 4):
    ops.element('zeroLength', i, i - 1, i, '-mat', 1, '-dir', 1)
""",
        encoding="utf-8",
    )

    model = _import(source)

    assert model.ndm == 1
    assert model.validate() == []
    assert len(model.nodes) == 4
    assert len(model.elements) == 3


def test_fallback_model_slice_ignores_code_after_the_suppressed_cutoff(
    tmp_path: Path,
) -> None:
    """Regression test: the AST fallback used when the full script fails to run
    (e.g. a missing ground-motion file checked before ops.model()) used to scan the
    *whole* file for assignments to keep as a "prelude", including ones written
    *after* the first suppressed analysis command - real post-processing code that
    depends on an analysis that was never actually run. That code must never
    execute during a model-only import, even though the model itself is valid.
    """
    source = tmp_path / "flaky_report_model.py"
    source.write_text(
        """
from pathlib import Path
import openseespy.opensees as ops

missing = Path(__file__).parent / "definitely_missing.txt"
if not missing.exists():
    raise FileNotFoundError(str(missing))

ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 4.0, 0.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf('Linear', 1)
ops.element('elasticBeamColumn', 1, 1, 2, 1.0, 200000.0, 1.0, 1)

eigenvalues = ops.eigen(1)
# Stands in for real post-processing that only makes sense once the (suppressed)
# analysis has actually run - it must never execute during model import.
boom = 1 / 0
""",
        encoding="utf-8",
    )

    model = _import(source)

    assert len(model.nodes) == 2
    assert len(model.elements) == 1


def test_rejects_a_script_with_no_opensees_model_at_all(tmp_path: Path) -> None:
    """A file that never calls ops.model() (e.g. a plain matplotlib diagram script)
    is not an OpenSeesPy model - it must fail fast with a clear message instead of
    running to completion and reporting a confusing "no nodes" error."""
    source = tmp_path / "not_a_model.py"
    source.write_text(
        """
import matplotlib.pyplot as plt
figure, axes = plt.subplots()
axes.plot([0, 1], [0, 1])
plt.savefig("ignored.png")
""",
        encoding="utf-8",
    )

    with pytest.raises(ModelImportError, match="ops.model"):
        _import(source)


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
