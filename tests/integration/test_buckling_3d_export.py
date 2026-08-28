"""3D canvas -> exported OpenSeesPy script -> elastic buckling (Phase 2-D).

Companion to ``tests/integration/test_buckling_solver.py`` (the existing 2D
Euler-column suite, all hand-written script text) - these build the model
through the domain objects (``StructuralModel``/``Element``/...) and
``export_opensees_script`` instead, the same way the 3D canvas actually
produces a script, then feed it to ``run_buckling_analysis`` exactly as
``buckling_solver.py`` expects. Nothing here modifies the exporter's default
behavior for any other analysis kind - see ``opensees_script_export.py``'s
own module docstring: ``geomTransf('Linear', ...)`` is always emitted as
before, and ``run_buckling_analysis`` alone is what substitutes 'PDelta' at
execution time (``ModelCommandCollector.install(geom_transf_override=...)``,
already the same mechanism ``run_nonlinear_static_analysis`` uses) - so no
``analysis_kind``-specific export profile was needed or added.
"""

import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openseespy.opensees as ops
import pytest

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    Node,
    NodalLoad,
    PointElementLoad,
    StructuralModel,
)
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.infrastructure.opensees.buckling_solver import run_buckling_analysis

#: Weak-axis (Iy) < strong-axis (Iz) on purpose, matching the exporter's own
#: 3D test fixtures (test_opensees_script_export.py) - the first buckling
#: mode of an otherwise-unbraced column governs about whichever axis is
#: weaker, so this pins down which one the closed form below must use.
_PROPERTIES_3D = {"E": 200.0e6, "A": 0.02, "G": 77.0e6, "J": 2.0e-6, "Iy": 6.0e-5, "Iz": 8.0e-5}
_LENGTH = 4.0
#: Effective length factor for a fixed-free (cantilever) column - the
#: boundary condition every test below uses (base fully fixed, everything
#: else free).
_K_CANTILEVER = 2.0
_EULER_PCR = math.pi**2 * _PROPERTIES_3D["E"] * _PROPERTIES_3D["Iy"] / (_K_CANTILEVER * _LENGTH) ** 2


def _run(model: StructuralModel, tmp_path: Path, name: str, **kwargs) -> dict:
    script = export_opensees_script(model, include_mass=False, length_unit="m")
    source = tmp_path / name
    source.write_text(script, encoding="utf-8")
    try:
        return run_buckling_analysis(source, geometric_transform_type="PDelta", **kwargs)
    finally:
        ops.wipe()


def _cantilever_column(n_elements: int) -> StructuralModel:
    """Vertical column along global Z (so ``auto_reference_vector`` falls
    back to its "vertical member" branch, global X - see
    ``core/domain/geometric_transform.py``), subdivided into ``n_elements``
    equal ``elasticBeamColumn`` segments, base (node 1) fully fixed, top node
    carrying a unit axial (compressive) nodal load - the "수직 beam-column,
    하단 고정, 상단 압축축력" scenario from the session's own verification
    spec."""
    nodes = {
        i + 1: Node(i + 1, 0.0, 0.0, _LENGTH * i / n_elements) for i in range(n_elements + 1)
    }
    elements = {
        i + 1: Element(i + 1, i + 1, i + 2, "elasticBeamColumn", properties=_PROPERTIES_3D)
        for i in range(n_elements)
    }
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes=nodes,
        elements=elements,
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(n_elements + 1, (0.0, 0.0, -1.0, 0.0, 0.0, 0.0))],
    )


def test_3d_cantilever_buckling_converges_to_euler_closed_form(tmp_path: Path) -> None:
    """Mirrors test_buckling_solver.py's own 2D convergence study exactly
    (same 4/8/16/32 progression, same monotonic-improvement + <0.5%-at-32
    criteria) - through the real exporter this time, proving the 3D
    geomTransf('Linear', ...) -> PDelta override path (vecxz preserved,
    weak-axis Iy governing) produces the textbook answer, not just "some
    positive number"."""
    element_counts = (4, 8, 16, 32)
    relative_errors = []
    for n_elements in element_counts:
        result = _run(
            _cantilever_column(n_elements),
            tmp_path,
            f"cantilever_{n_elements}.py",
            num_modes=1,
        )
        assert result["status"] == "completed"
        factor = result["buckling_modes"][0]["buckling_load_factor"]
        relative_errors.append(abs(factor - _EULER_PCR) / _EULER_PCR)

    for coarser, finer in zip(relative_errors, relative_errors[1:]):
        assert finer <= coarser * 1.01
    assert relative_errors[-1] < 0.005  # < 0.5% at 32 elements, same bar as the 2D suite


def test_reference_load_scale_invariance_on_exported_3d_script(tmp_path: Path) -> None:
    """Doubling REFERENCE LOAD SCALE halves the buckling load factor and
    leaves Critical Load (factor * scale) unchanged - same physical
    invariant test_buckling_solver.py's 2D suite already checks, run here
    against the exporter's own output."""
    model = _cantilever_column(16)
    result_1x = _run(model, tmp_path, "scale_1x.py", reference_load_scale=1.0, num_modes=1)
    result_2x = _run(model, tmp_path, "scale_2x.py", reference_load_scale=2.0, num_modes=1)

    factor_1x = result_1x["buckling_modes"][0]["buckling_load_factor"]
    factor_2x = result_2x["buckling_modes"][0]["buckling_load_factor"]
    assert factor_2x / factor_1x == pytest.approx(0.5, rel=1.0e-6)
    assert factor_2x * 2.0 == pytest.approx(factor_1x * 1.0, rel=1.0e-6)


def test_buckling_rejects_a_loaded_model_with_no_static_pattern(tmp_path: Path) -> None:
    """A populated, properly-supported model that simply has no load applied
    yet must be rejected with a clear Python error - never handed to
    OpenSeesPy's own native failure path. This is exactly the scenario
    test_direct_model_3d_analysis_run.py's own
    test_buckling_on_exported_3d_script_fails_without_pdelta_reference_load
    exercises via the canvas's ``_build_mass_cantilever`` helper (which never
    applies a load) - same rejection, reached here directly through the
    exporter instead of the full canvas/RunAnalysisService pipeline."""
    model = _cantilever_column(4)
    model.nodal_loads.clear()
    script = export_opensees_script(model, include_mass=False, length_unit="m")
    source = tmp_path / "no_load.py"
    source.write_text(script, encoding="utf-8")

    with pytest.raises(RuntimeError, match="REFERENCE LOAD"):
        try:
            run_buckling_analysis(source, geometric_transform_type="PDelta")
        finally:
            ops.wipe()


def test_point_load_reference_is_recognized_but_yields_no_geometric_stiffness(
    tmp_path: Path,
) -> None:
    """Regression for a real gap this session found and fixed:
    ``ElementLoadCollector`` used to only track ``-beamUniform`` loads, so a
    model whose only load was a concentrated member load (``-beamPoint``,
    ``PointElementLoad``) was entirely invisible to
    ``buckling_solver.py``'s reference-load collection - it failed with
    "REFERENCE LOAD로 사용할 정적 하중 패턴이 모델에 없습니다.", which is
    simply false (a load pattern *does* exist). After the fix, the pattern
    is found and the load is genuinely re-applied (confirmed independently:
    reactions/displacements respond correctly - see the session report) - but
    an *axial* ``-beamPoint`` component still produces zero net change to
    elasticBeamColumn+PDelta's own tangent stiffness in the installed
    OpenSeesPy (confirmed directly against plain OpenSeesPy, independent of
    this project's code: K_loaded == K_material to machine precision even
    though the analysis converges and reactions are correct). That is an
    OpenSeesPy-level characteristic, not a bug in this fix, and the run must
    still fail - but now with the *correct*, meaningful reason
    (K_geometric~=0), not the misleading "no load pattern" one."""
    model = _cantilever_column(1)
    model.nodal_loads.clear()
    model.point_loads.append(PointElementLoad(1, position=0.5, n=-1.0))
    script = export_opensees_script(model, include_mass=False, length_unit="m")
    source = tmp_path / "point_load_only.py"
    source.write_text(script, encoding="utf-8")

    with pytest.raises(RuntimeError, match="기하강성"):
        try:
            run_buckling_analysis(source, geometric_transform_type="PDelta")
        finally:
            ops.wipe()


def test_3d_buckling_preserves_offset_and_local_axis_angle(tmp_path: Path) -> None:
    """Buckling's required 3D geometry (필수 기능 1): a rigid end-zone offset
    and a rotated local axis (asymmetric Iy/Iz) survive the PDelta override
    unchanged - the override only ever substitutes the geomTransf *type*
    string, never its vecxz/-jntOffset arguments (see
    ModelCommandCollector._wrap_geom_transf), so a member whose orientation
    or offsets matter still buckles at a sensible (i.e. not garbage/near-
    zero/negative) load."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 0.0, 0.0, _LENGTH / 2),
            3: Node(3, 0.0, 0.0, _LENGTH),
        },
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties=_PROPERTIES_3D,
                offset_i=(0.0, 0.0, 0.1),
                local_axis_angle=15.0,
            ),
            2: Element(2, 2, 3, "elasticBeamColumn", properties=_PROPERTIES_3D),
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(3, (0.0, 0.0, -1.0, 0.0, 0.0, 0.0))],
    )

    result = _run(model, tmp_path, "offset_and_angle.py", num_modes=2)

    assert result["status"] in ("completed", "partial")
    assert result["buckling_modes"]
    factor = result["buckling_modes"][0]["buckling_load_factor"]
    assert factor > 0.0
    # Sanity band around the unoffset/unrotated closed form - not an exact
    # match (the offset/rotation genuinely change the answer), just proof
    # this is a real Euler-scale buckling load, not a stray/garbage root.
    assert 0.1 * _EULER_PCR < factor < 10.0 * _EULER_PCR
