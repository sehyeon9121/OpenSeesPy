"""Regression coverage for exporting a canvas ``StructuralModel`` as a runnable
OpenSeesPy script and feeding it through the independent "OpenSeesPy 파일
불러오기" pipeline (subprocess execution + ``ModelCommandCollector``).

The exporter's whole point is fidelity: running the same model through the
canvas's own in-process solvers (``MaterialFreeStaticsSolver``,
``ModalStaticsSolver``) and through the exported-script route must produce the
same numbers, since the exported script is meant to unlock nonlinear
static/time-history analysis (which the canvas solvers cannot do) without
silently changing what the model represents. Every test here therefore
round-trips through a real subprocess (``OpenSeesProcessRunner``), not just the
in-process exporter function - a text-generation bug (wrong argument order,
wrong sign) would only show up once OpenSeesPy actually parses the string.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from openframe.core.domain import (
    AnalysisKind,
    AnalysisRequest,
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    PointElementLoad,
    RigidDiaphragm,
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.analysis.statics.modal_solver import ModalStaticsSolver
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

_FRAME_PROPERTIES = {"E": 200.0e6, "A": 0.02, "I": 8.0e-5, "density": 5.0}
#: 3D equivalent of ``_FRAME_PROPERTIES`` - Iy != Iz on purpose so a
#: local_axis_angle test actually has something to be wrong about.
_FRAME_PROPERTIES_3D = {
    "E": 200.0e6,
    "A": 0.02,
    "G": 77.0e6,
    "J": 2.0e-6,
    "Iy": 6.0e-5,
    "Iz": 8.0e-5,
    "density": 5.0,
}


def _run_exported_script(model: StructuralModel, tmp_path: Path, **export_kwargs) -> tuple:
    script = export_opensees_script(model, **export_kwargs)
    source = tmp_path / "exported.py"
    source.write_text(script, encoding="utf-8")
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=source))
    return result, script


def _round_state(
    result, model: StructuralModel
) -> dict[int, tuple[tuple[float, ...], tuple[float, ...]]]:
    """Keyed only to the model's own node tags: the exported script's inclined-
    support ground nodes and trapezoid-discretization sub-nodes are real
    ``ops.node`` calls the file-import collector faithfully reports, but they
    have no counterpart in canvas's result (which only ever reports the
    original domain nodes) - comparing the full dicts would flag that
    structural difference as a mismatch instead of the numbers that matter."""
    return {
        tag: (
            tuple(round(v, 7) for v in result.node_results[tag].displacement),
            tuple(round(v, 5) for v in result.node_results[tag].reaction),
        )
        for tag in model.nodes
    }


def test_exported_portal_frame_matches_the_in_process_canvas_solver(tmp_path: Path) -> None:
    """An indeterminate portal frame with real E/A/I everywhere - the canvas
    solver only accepts this because every element carries real stiffness."""
    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodes={
            1: Node(1, 0.0, 0.0),
            2: Node(2, 6.0, 0.0),
            3: Node(3, 0.0, 3.0),
            4: Node(4, 6.0, 3.0),
        },
        elements={
            1: Element(1, 1, 3, "elasticBeamColumn", properties=_FRAME_PROPERTIES),
            2: Element(2, 2, 4, "elasticBeamColumn", properties=_FRAME_PROPERTIES),
            3: Element(3, 3, 4, "elasticBeamColumn", properties=_FRAME_PROPERTIES),
        },
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (True, True, True)),
        ],
        nodal_loads=[NodalLoad(3, (10.0, 0.0, 0.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_trapezoidal_load_matches_the_40_segment_discretization(tmp_path: Path) -> None:
    """OpenSeesPy has no native linearly-varying eleLoad - both the canvas
    solver and the exporter approximate it the same way (40 elasticBeamColumn
    sub-elements sampled at their own midpoint). If the exporter's segment
    tags/midpoint formula ever drift from solver.py's, this catches it."""
    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 6.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES)},
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (False, True, False)),
        ],
        element_loads=[UniformElementLoad(1, wx=0.0, wy=-5.0, wy_j=-15.0)],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_inclined_support_and_hinge_match_the_penalty_spring_technique(
    tmp_path: Path,
) -> None:
    """Inclined roller (zero-length spring rotated to the support angle) and a
    moment release (elasticBeamColumn's native -release) together - both are
    solver.py techniques the exporter must reproduce as text exactly."""
    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0), 3: Node(3, 8.0, 0.0)},
        elements={
            1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES),
            2: Element(
                2, 2, 3, "elasticBeamColumn", properties=_FRAME_PROPERTIES, moment_release_i=True
            ),
        },
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(3, (True, False, False), angle=45.0),
        ],
        nodal_loads=[NodalLoad(2, (0.0, -10.0, 0.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_truss_reactions_match_since_they_are_stiffness_independent(
    tmp_path: Path,
) -> None:
    """The canvas determinate-truss solver always uses unit-placeholder E=A=1
    (equilibrium alone fixes a determinate truss's reactions/forces, so the
    real value never mattered there) - so its own *displacements* are not
    physically real and must NOT be compared. Reactions, which genuinely are
    stiffness-independent for a determinate structure, must still match."""
    model = StructuralModel(
        ndm=2,
        ndf=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0), 3: Node(3, 2.0, 3.0)},
        elements={
            1: Element(1, 1, 2, "truss", properties={"E": 200.0e6, "A": 0.005}),
            2: Element(2, 1, 3, "truss", properties={"E": 200.0e6, "A": 0.005}),
            3: Element(3, 2, 3, "truss", properties={"E": 200.0e6, "A": 0.005}),
        },
        boundaries=[
            BoundaryCondition(1, (True, True)),
            BoundaryCondition(2, (False, True)),
        ],
        nodal_loads=[NodalLoad(3, (0.0, -10.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    for tag in model.nodes:
        exported_reaction = tuple(round(v, 5) for v in exported_result.node_results[tag].reaction)
        canvas_reaction = tuple(round(v, 5) for v in canvas_result.node_results[tag].reaction)
        assert exported_reaction == canvas_reaction


def test_exported_modal_analysis_matches_the_in_process_canvas_solver(tmp_path: Path) -> None:
    """Real E/A/I plus density-derived lumped mass, run through the file-import
    pipeline's own modal solver (a completely separate implementation from
    ModalStaticsSolver) - periods and mass participation ratios must agree."""
    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodes={
            1: Node(1, 0.0, 0.0),
            2: Node(2, 6.0, 0.0),
            3: Node(3, 0.0, 3.0),
            4: Node(4, 6.0, 3.0),
        },
        elements={
            1: Element(1, 1, 3, "elasticBeamColumn", properties=_FRAME_PROPERTIES),
            2: Element(2, 2, 4, "elasticBeamColumn", properties=_FRAME_PROPERTIES),
            3: Element(3, 3, 4, "elasticBeamColumn", properties=_FRAME_PROPERTIES),
        },
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (True, True, True)),
        ],
    )

    source = tmp_path / "exported_modal.py"
    source.write_text(
        export_opensees_script(model, include_mass=True, length_unit="m"), encoding="utf-8"
    )
    exported_result = OpenSeesProcessRunner(timeout_seconds=20).run(
        AnalysisRequest(source_path=source, kind=AnalysisKind.MODAL, options={"num_modes": 3})
    )
    canvas_result = ModalStaticsSolver().solve(model, num_modes=3, length_unit="m")

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert len(exported_result.mode_shapes) == len(canvas_result.mode_shapes) == 3
    for exported_mode, canvas_mode in zip(
        exported_result.mode_shapes, canvas_result.mode_shapes, strict=True
    ):
        assert exported_mode.period == pytest.approx(canvas_mode.period, rel=1e-6)
        assert exported_mode.mass_participation_ratio == pytest.approx(
            canvas_mode.mass_participation_ratio, abs=1e-6
        )


def test_export_rejects_an_unsupported_ndm() -> None:
    with pytest.raises(ValueError, match="2D 또는 3D"):
        export_opensees_script(StructuralModel(ndm=1, ndf=1))


def test_export_rejects_an_empty_model() -> None:
    with pytest.raises(ValueError, match="절점과 부재"):
        export_opensees_script(StructuralModel(ndm=2, ndf=3))


def test_export_rejects_an_empty_3d_model() -> None:
    with pytest.raises(ValueError, match="절점과 부재"):
        export_opensees_script(StructuralModel(ndm=3, ndf=6))


def test_export_rejects_a_member_missing_real_section_properties() -> None:
    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    with pytest.raises(ValueError, match=r"부재 1.*E/A/I"):
        export_opensees_script(model)


def test_export_rejects_a_3d_member_missing_real_section_properties() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    with pytest.raises(ValueError, match=r"부재 1.*E/A/G/J/Iy/Iz"):
        export_opensees_script(model)


def test_export_rejects_a_3d_trapezoidal_load() -> None:
    """MaterialFreeStaticsSolver._apply_loads rejects this too (a 3D member
    is never discretized into sub-elements the way a 2D one is) - the
    exporter must reproduce the same rejection, not silently emit a wrong
    (constant) load."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 6.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D)},
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(2, (True,) * 6),
        ],
        element_loads=[UniformElementLoad(1, wy=-5.0, wy_j=-15.0)],
    )
    with pytest.raises(ValueError, match="3D 모델의 선형 변화"):
        export_opensees_script(model)


def test_exported_3d_frame_matches_the_in_process_canvas_solver(tmp_path: Path) -> None:
    """Two orthogonal members meeting at a free corner: member 1 runs along
    global X (``_reference_vector``'s auto-picked reference is global Z),
    member 2 runs along global Z (falls back to global X, per that
    function's own docstring) - exercises both auto-orientation branches in
    one model, plus a combined 6-DOF nodal force+moment."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 0.0, 0.0),
            3: Node(3, 4.0, 0.0, 3.0),
        },
        elements={
            1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D),
            2: Element(2, 2, 3, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(3, (True,) * 6),
        ],
        nodal_loads=[NodalLoad(2, (5.0, -8.0, 3.0, 0.0, 2.0, -1.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_3d_local_axis_angle_matches_the_in_process_canvas_solver(
    tmp_path: Path,
) -> None:
    """A cantilever rotated 30 degrees about its own axis (local_axis_angle)
    with an asymmetric section (Iy != Iz, see _FRAME_PROPERTIES_3D) - the
    rotation only changes the answer once the section's strong/weak axis is
    no longer symmetric, per _reference_vector's own docstring."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 5.0, 0.0, 0.0)},
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties=_FRAME_PROPERTIES_3D,
                local_axis_angle=30.0,
            )
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (0.0, -4.0, 2.0, 0.0, 0.0, 0.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_3d_rigid_diaphragm_matches_the_in_process_canvas_solver(
    tmp_path: Path,
) -> None:
    """Two columns whose top nodes share the same elevation (z=3), tied by a
    rigid diaphragm (perp_dirn=3, Story Manager's own feature) - a lateral
    load applied only at the master node must still engage both columns
    through the diaphragm, both in the exported script and in-process."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 0.0, 0.0),
            3: Node(3, 0.0, 0.0, 3.0),
            4: Node(4, 4.0, 0.0, 3.0),
        },
        elements={
            1: Element(1, 1, 3, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D),
            2: Element(2, 2, 4, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(2, (True,) * 6),
        ],
        nodal_loads=[NodalLoad(3, (10.0, 0.0, 0.0, 0.0, 0.0, 0.0))],
        rigid_diaphragms=(RigidDiaphragm(perp_dirn=3, master_tag=3, slave_tags=(4,)),),
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_3d_spring_support_matches_the_in_process_canvas_solver(
    tmp_path: Path,
) -> None:
    """A cantilever whose far end is elastically (spring) supported in
    translation instead of rigidly fixed or left free - Story Manager's own
    feature, text form of ``MaterialFreeStaticsSolver._apply_springs``."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 5.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D)},
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(
                2,
                (False,) * 6,
                spring_stiffnesses=(1.0e5, 1.0e5, 1.0e5, 0.0, 0.0, 0.0),
            ),
        ],
        nodal_loads=[NodalLoad(2, (0.0, -6.0, 0.0, 0.0, 0.0, 0.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_3d_rigid_end_offset_matches_the_in_process_canvas_solver(
    tmp_path: Path,
) -> None:
    """A cantilever with a nonzero rigid end-zone (panel zone) offset at both
    ends - OpenSeesPy's own geomTransf ``-jntOffset``, text form of the same
    call MaterialFreeStaticsSolver._build makes for a 3D member."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 5.0, 0.0, 0.0)},
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties=_FRAME_PROPERTIES_3D,
                offset_i=(0.0, 0.0, 0.3),
                offset_j=(-0.2, 0.0, 0.0),
            )
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (0.0, -5.0, 0.0, 0.0, 0.0, 0.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_3d_member_hinge_matches_the_in_process_canvas_solver(tmp_path: Path) -> None:
    """A straight fixed-fixed beam with a full moment release at its
    midpoint (element 1 released at j, element 2 released at i, both ending
    at shared node 2) - both members release at that node, so it is a true
    shared hinge with nothing else anchoring its rotation there, exercising
    the orphaned-rotation ``ops.fix(node, 0,0,0,0,1,1)`` branch in
    ``_write_3d_frame_elements`` alongside a one-sided release on the same
    model (element 1's own i-end stays rigid)."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 0.0, 0.0),
            3: Node(3, 8.0, 0.0, 0.0),
        },
        elements={
            1: Element(
                1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D, moment_release_j=True
            ),
            2: Element(
                2,
                2,
                3,
                "elasticBeamColumn",
                properties=_FRAME_PROPERTIES_3D,
                moment_release_i=True,
                moment_release_j=True,
            ),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(3, (True,) * 6),
        ],
        nodal_loads=[NodalLoad(2, (0.0, -10.0, 0.0, 0.0, 0.0, 0.0))],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_3d_element_loads_match_the_in_process_canvas_solver(tmp_path: Path) -> None:
    """A cantilever carrying both a 3D uniform load (wy/wz/wx) and a 3D point
    load (py/pz/xL/n) together - the argument order for both differs from 2D
    (see _write_loads's own comments; the point-load order was a real bug
    until Phase 2-A.1 - see test_exported_3d_point_load_uses_py_pz_xl_n_order
    and test_solver_beam_point_argument_order.py for the independent checks
    that pin it down). Fixed at node 1 only (not also at node 2): a two-node,
    one-element model fixed at *both* ends has zero free DOFs anywhere in the
    structure, which crashes OpenSeesPy's banded solver outright (``DGBSV
    parameter number 9``) rather than raising a catchable Python error -
    confirmed independently of both this exporter and
    ``MaterialFreeStaticsSolver`` by reproducing it directly against
    OpenSeesPy. Not this exporter's bug (a real model always has other
    elements/nodes providing free DOFs elsewhere), so the fix here is simply
    not to hand the in-process solver a degenerate one-element structure."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 6.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        element_loads=[UniformElementLoad(1, wx=1.0, wy=-3.0, wz=2.0)],
        point_loads=[PointElementLoad(1, position=0.5, py=-4.0, pz=1.5, n=0.5)],
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    assert exported_result.status == AnalysisStatus.COMPLETED
    assert canvas_result.status == AnalysisStatus.COMPLETED
    assert _round_state(exported_result, model) == _round_state(canvas_result, model)


def test_exported_3d_point_load_uses_py_pz_xl_n_order() -> None:
    """Direct text check on the exported script, independent of executing
    anything - if the exporter and MaterialFreeStaticsSolver ever diverge
    again (or both drift back to the same wrong order together, which a
    round-trip comparison alone cannot catch - see
    test_solver_beam_point_argument_order.py for the equivalent check on the
    in-process solver side), this fails on the exporter half specifically.
    Four distinct values (py/pz/position/n) so a transposition shows up as a
    literal wrong-order substring, not just a wrong number."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 6.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        point_loads=[PointElementLoad(1, position=0.25, py=2.0, pz=7.0, n=0.5)],
    )

    script = export_opensees_script(model)

    assert "'-beamPoint', 2.0, 7.0, 0.25, 0.5)" in script


def test_exported_3d_point_load_matches_the_closed_form_fixed_end_reactions(
    tmp_path: Path,
) -> None:
    """Independent physics check, not just solver/exporter self-agreement:
    for a cantilever under a single 3D point load, the fixed-end reactions
    follow directly from global equilibrium alone (Fx=-N, Fy=-Py, Fz=-Pz,
    Mz=-Py*a, My=+Pz*a, a = position*L from the fixed end) and do not depend
    on E/A/G/J/Iy/Iz at all - reactions of a statically determinate structure
    never do. The sign/axis mapping here (Py <-> Fy/Mz, Pz <-> Fz/My) was
    confirmed empirically against plain OpenSeesPy directly, independent of
    both this exporter and MaterialFreeStaticsSolver (see the Phase 2-A.1
    session report) - so if py/pz/position were still swapped, these
    specific numbers would not come out right even though *some* analysis
    would still nominally "complete"."""
    length = 6.0
    distance_from_fixed_end = 0.25 * length
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, length, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        point_loads=[PointElementLoad(1, position=0.25, py=2.0, pz=7.0, n=0.5)],
    )
    expected_reaction = (
        -0.5,
        -2.0,
        -7.0,
        0.0,
        7.0 * distance_from_fixed_end,
        -2.0 * distance_from_fixed_end,
    )

    exported_result, _ = _run_exported_script(model, tmp_path)
    canvas_result = MaterialFreeStaticsSolver().solve(model)

    for result in (exported_result, canvas_result):
        assert result.status == AnalysisStatus.COMPLETED
        reaction = tuple(round(v, 6) for v in result.node_results[1].reaction)
        assert reaction == tuple(round(v, 6) for v in expected_reaction)


def test_exported_3d_mass_uses_six_component_ops_mass() -> None:
    """``ops.mass`` in 3D needs 6 components (3 translational + 3 rotational,
    the last three always zero - no rotational mass, the standard
    lumped-mass convention), unlike 2D's 3-component form. Checked directly
    against the generated text since there is no independent 3D modal ground
    truth to round-trip against - ``ModalStaticsSolver``, the in-process
    modal solver, is 2D-frame-only (see this module's own docstring)."""
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 6.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_FRAME_PROPERTIES_3D)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )

    script = export_opensees_script(model, include_mass=True, length_unit="m")

    expected_mass = (5.0 * 0.02 * 6.0 / 2.0) / 9.81
    assert f"ops.mass(2, {expected_mass!r}, {expected_mass!r}, {expected_mass!r}, 0.0, 0.0, 0.0)" in script
    assert f"ops.mass(1, {expected_mass!r}, {expected_mass!r}, {expected_mass!r}, 0.0, 0.0, 0.0)" in script
