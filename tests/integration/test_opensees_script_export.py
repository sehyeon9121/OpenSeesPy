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
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.analysis.statics.modal_solver import ModalStaticsSolver
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

_FRAME_PROPERTIES = {"E": 200.0e6, "A": 0.02, "I": 8.0e-5, "density": 5.0}


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


def test_export_rejects_a_3d_model() -> None:
    model = StructuralModel(ndm=3, ndf=6)
    with pytest.raises(ValueError, match="2D 모델만"):
        export_opensees_script(model)


def test_export_rejects_an_empty_model() -> None:
    with pytest.raises(ValueError, match="절점과 부재"):
        export_opensees_script(StructuralModel(ndm=2, ndf=3))


def test_export_rejects_a_member_missing_real_section_properties() -> None:
    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    with pytest.raises(ValueError, match=r"부재 1.*E/A/I"):
        export_opensees_script(model)
