"""Production tests for ``InstabilityDiagnosticService`` - promoted from the
now-retired validation spike (``test_instability_detection_spike.py``).

Covers the required structural case matrix (stable/unstable frame, truss,
hinges, rigidDiaphragm, unit-system invariance, MP slave-DOF reconstruction)
plus Gate 1 (in-process ``_build`` vs worker/export domain mismatch) - the
same live-domain-only guarantee ``InstabilityDiagnosticService`` itself
relies on (see its own docstring).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import openseespy.opensees as ops
import pytest

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    RigidDiaphragm,
    StructuralModel,
)
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.features.analysis.statics.solver import (
    MaterialFreeStaticsSolver,
    check_determinacy,
)
from openframe.infrastructure.opensees.instability_diagnostic import InstabilityDiagnosticService
from openframe.infrastructure.opensees.script_execution import run_model_script
from tests.integration.buckling_3d_hinge_diagnostics_helpers import (
    FRAME_PROPERTIES_3D,
    shared_hinge_cantilever,
    stable_portal_shared_hinge,
    vertical_cantilever,
)

_SERVICE = InstabilityDiagnosticService()


def _diagnose_in_process(model: StructuralModel):
    """Build via the in-process path (``_build``), leave the domain live,
    diagnose it, then clean up - mirrors what ``solve()`` does on a real
    ``analyze()`` failure, minus going through the exception path."""
    ops.wipe()
    system = check_determinacy(model).system
    MaterialFreeStaticsSolver._build(model, system)  # noqa: SLF001 - production parity
    result = _SERVICE.diagnose(model)
    ops.wipe()
    return result


def _diagnose_export(model: StructuralModel, tmp_path: Path):
    """Build via the worker/export path (``export_opensees_script``) instead
    - what the canvas-full-analysis path actually leaves live, not
    ``_build``'s ndf override."""
    source = tmp_path / "exported.py"
    source.write_text(export_opensees_script(model), encoding="utf-8")
    ops.wipe()
    run_model_script(source)
    result = _SERVICE.diagnose(model)
    ops.wipe()
    return result


# --------------------------------------------------------------------------- #
# Model factories (ported verbatim from the spike).                           #
# --------------------------------------------------------------------------- #


def free_portal_no_supports() -> StructuralModel:
    """A portal frame (2 columns + beam) with NO supports at all - stable in
    isolation, floating in space -> exactly 6 rigid-body modes."""
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 0.0, 0.0, 4.0),
            3: Node(3, 6.0, 0.0, 0.0),
            4: Node(4, 6.0, 0.0, 4.0),
        },
        elements={
            1: Element(1, 1, 2, "frame", properties=FRAME_PROPERTIES_3D),
            2: Element(2, 3, 4, "frame", properties=FRAME_PROPERTIES_3D),
            3: Element(3, 2, 4, "frame", properties=FRAME_PROPERTIES_3D),
        },
        boundaries=[],
    )


def single_sway_column(unit: str = "m-kN") -> StructuralModel:
    """A vertical column whose base is fully fixed EXCEPT global Ux -> the
    whole column can rigidly translate in X, exactly one mechanism, in a
    single known direction. Also the unit-system probe model."""
    if unit == "m-kN":
        props = dict(FRAME_PROPERTIES_3D)
        length = 4.0
    elif unit == "mm-N":
        props = {
            "E": 2.0e5, "A": 2.0e4, "G": 7.7e4,
            "J": 2.0e6, "Iy": 6.0e7, "Iz": 8.0e7,
        }
        length = 4000.0
    else:  # pragma: no cover - guard
        raise ValueError(unit)
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, length)},
        elements={1: Element(1, 1, 2, "frame", properties=props)},
        boundaries=[BoundaryCondition(1, (False, True, True, True, True, True))],
    )


def tetrahedral_truss() -> StructuralModel:
    """A stable space truss (ndf=3). Apex held by 3 non-coplanar bars, 3 base
    joints pinned -> 0 mechanisms."""
    props = {"E": 2.0e8, "A": 0.01}
    nodes = {
        1: Node(1, 0.0, 0.0, 0.0),
        2: Node(2, 4.0, 0.0, 0.0),
        3: Node(3, 2.0, 3.5, 0.0),
        4: Node(4, 2.0, 1.2, 3.0),
    }
    elements = {
        1: Element(1, 1, 2, "truss", properties=props),
        2: Element(2, 2, 3, "truss", properties=props),
        3: Element(3, 3, 1, "truss", properties=props),
        4: Element(4, 1, 4, "truss", properties=props),
        5: Element(5, 2, 4, "truss", properties=props),
        6: Element(6, 3, 4, "truss", properties=props),
    }
    return StructuralModel(
        ndm=3, ndf=3, nodes=nodes, elements=elements,
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (True, True, True)),
            BoundaryCondition(3, (True, True, True)),
        ],
    )


def canvas_style_3d_truss() -> StructuralModel:
    """Same tetrahedron the 3D canvas would export: ``ndf=6`` even though
    every member is a truss. ``_build`` still drops to ndf=3; export keeps 6."""
    model = tetrahedral_truss()
    model.ndf = 6
    model.nodes = {tag: replace(node, ndf=6) for tag, node in model.nodes.items()}
    return model


def guyed_mast() -> StructuralModel:
    """Mixed frame column + truss stay. ``_build``'s mixed path pins the
    stay-only node's rotations; export does not."""
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, ndf=6),
            2: Node(2, 0.0, 0.0, 4.0, ndf=6),
            3: Node(3, 3.0, 0.0, 0.0, ndf=6),
        },
        elements={
            1: Element(1, 1, 2, "frame", properties=dict(FRAME_PROPERTIES_3D)),
            2: Element(2, 2, 3, "truss", properties={"E": 2.0e8, "A": 0.01}),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(3, (True, True, True, False, False, False)),
        ],
        nodal_loads=[NodalLoad(2, (1.0, 0.0, 0.0, 0.0, 0.0, 0.0))],
    )


def diaphragm_two_column(*, unstable: bool) -> StructuralModel:
    """Two columns tied at the top by a rigidDiaphragm. ``unstable=False`` ->
    fixed bases, stable, 0 mechanisms (used for slave-DOF reconstruction).
    ``unstable=True`` -> bases free to rotate about Y, both tops sway
    together in X -> the tied Ux is part of the mechanism."""
    props = {"E": 2.0e8, "A": 0.02, "G": 7.7e7, "J": 2.0e-6, "Iy": 6.0e-5, "Iz": 8.0e-5}
    base = (True, True, True, True, False, True) if unstable else (True,) * 6
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 0.0, 0.0, 4.0),
            3: Node(3, 5.0, 0.0, 0.0),
            4: Node(4, 5.0, 0.0, 4.0),
        },
        elements={
            1: Element(1, 1, 2, "frame", properties=props),
            2: Element(2, 3, 4, "frame", properties=props),
        },
        boundaries=[BoundaryCondition(1, base), BoundaryCondition(3, base)],
        nodal_loads=[NodalLoad(2, (1.0, 0.0, 0.0, 0.0, 0.0, 0.0))],
        rigid_diaphragms=(RigidDiaphragm(perp_dirn=3, master_tag=2, slave_tags=(4,)),),
    )


# --------------------------------------------------------------------------- #
# 1-9. Required structural case matrix.                                       #
# --------------------------------------------------------------------------- #


def test_case_1_stable_3d_cantilever_zero_mechanisms() -> None:
    result = _diagnose_in_process(vertical_cantilever())
    assert result.diagnostic_success is True
    assert result.mechanism_count == 0
    assert result.modes == ()


def test_case_2_unsupported_free_3d_frame_six_rigid_body_modes() -> None:
    result = _diagnose_in_process(free_portal_no_supports())
    assert result.mechanism_count == 6, result.modes


def test_case_3_one_direction_sway_one_mechanism() -> None:
    result = _diagnose_in_process(single_sway_column())
    assert result.mechanism_count == 1, result.modes
    dominant = " ".join(result.modes[0].dominant_dofs)
    assert "Ux" in dominant
    assert "Uy" not in dominant and "Uz" not in dominant


def test_case_4_unit_system_invariance() -> None:
    """N-mm and m-kN models of the SAME physical column must agree on the
    mechanism count - the whole point of equilibration over a raw relative
    floor (see the raw-floor regression test below)."""
    counts = {
        unit: _diagnose_in_process(single_sway_column(unit)).mechanism_count
        for unit in ("m-kN", "mm-N")
    }
    assert counts["m-kN"] == 1
    assert counts["mm-N"] == 1


def test_case_5_stable_tetrahedral_truss_zero_mechanisms() -> None:
    result = _diagnose_in_process(tetrahedral_truss())
    assert result.mechanism_count == 0, result.modes


@pytest.mark.parametrize(
    "factory,expected",
    [
        (stable_portal_shared_hinge, 0),
        (lambda: vertical_cantilever(release_j=True), 0),
        # A 3D moment release frees BOTH bending axes (My AND Mz) - a
        # spherical pin - so a destabilizing 3D hinge yields TWO rigid-
        # rotation mechanisms, not one.
        (lambda: vertical_cantilever(release_i=True), 2),
        (shared_hinge_cantilever, 2),
    ],
    ids=["stable_shared_hinge", "tip_hinge_stable", "base_hinge_mechanism", "midheight_hinge_mechanism"],
)
def test_case_6_and_7_hinge_frames_no_false_positive_but_catch_real_ones(factory, expected) -> None:
    result = _diagnose_in_process(factory())
    assert result.mechanism_count == expected, result.modes


def test_case_8_rigid_diaphragm_stable_zero_mechanisms() -> None:
    result = _diagnose_in_process(diaphragm_two_column(unstable=False))
    assert result.mechanism_count == 0, result.modes


def test_case_9_rigid_diaphragm_sway_one_mechanism() -> None:
    result = _diagnose_in_process(diaphragm_two_column(unstable=True))
    assert result.mechanism_count == 1, result.modes


# --------------------------------------------------------------------------- #
# 10. MP (rigidDiaphragm) slave DOF physical-shape reconstruction.            #
# --------------------------------------------------------------------------- #


def test_case_10_diaphragm_slave_dof_reconstructed_in_physical_shape() -> None:
    """The stable diaphragm model has 0 mechanisms, so instead force a
    mechanism through it (unstable=True) and confirm the reported mode shape
    ties node 4's Ux to node 2's (master) Ux via the rigid relation, not the
    ~0.0 a raw equation-indexed eigenvector would give (see
    stiffness_analysis.correct_constrained_dof_values's own docstring)."""
    result = _diagnose_in_process(diaphragm_two_column(unstable=True))
    assert result.mechanism_count == 1
    mode = result.modes[0]
    master_ux = mode.mode_shape[2][0]
    slave_ux = mode.mode_shape[4][0]
    assert abs(master_ux) > 1.0e-6
    assert slave_ux == pytest.approx(master_ux, rel=1.0e-6)


# --------------------------------------------------------------------------- #
# 11. Near-zero diagonal equilibration regression (Gate 2).                   #
# --------------------------------------------------------------------------- #


def test_case_11_exact_and_roundoff_diagonals_are_treated_as_empty() -> None:
    from openframe.infrastructure.opensees.instability_diagnostic import _diagonal_scale

    k = np.diag([1.0e8, 1.0, 0.0, 1.0e-20])
    scale = _diagonal_scale(k)
    assert scale[0] == pytest.approx(1.0e4)
    assert scale[1] == pytest.approx(1.0)
    assert scale[2] == 1.0
    assert scale[3] == 1.0
    dinv = 1.0 / scale
    assert np.all(np.isfinite(dinv))
    assert float(np.max(np.abs(dinv))) < 10.0


def test_case_11_physically_soft_diagonal_is_not_treated_as_empty() -> None:
    from openframe.infrastructure.opensees.instability_diagnostic import (
        DEFAULT_MECHANISM_TOLERANCE,
        _diagonal_scale,
        equilibrate,
    )

    k = np.diag([1.0e8, 1.0e-4])
    scale = _diagonal_scale(k)
    assert scale[1] == pytest.approx(1.0e-2)
    evals, _, dinv = equilibrate(k)
    assert np.all(np.isfinite(dinv))
    assert float(np.min(np.abs(evals))) > DEFAULT_MECHANISM_TOLERANCE


def test_case_11_raw_relative_floor_is_not_unit_invariant_but_equilibrated_is() -> None:
    """Documents the defect equilibration exists to fix: a raw
    1e-6*max|eigenvalue| floor (the pre-existing buckling_solver rule) is
    unit-sensitive for this exact model."""
    from openframe.infrastructure.opensees.stiffness_analysis import symmetrize

    def raw_relative_count(model: StructuralModel) -> int:
        ops.wipe()
        MaterialFreeStaticsSolver._build(model, "frame")  # noqa: SLF001
        ops.wipeAnalysis()
        ops.system("FullGeneral")
        ops.numberer("RCM")
        ops.constraints("Transformation")
        ops.algorithm("Linear")
        ops.integrator("LoadControl", 0.0)
        ops.analysis("Static")
        ops.analyze(1)
        size = ops.systemSize()
        matrix = np.array(ops.printA("-ret"), dtype=float).reshape(size, size)
        eigenvalues = np.linalg.eigvalsh(symmetrize(matrix))
        scale = float(np.max(np.abs(eigenvalues)))
        floor = max(1.0e-6 * scale, 1.0e-6)
        ops.wipe()
        return int(np.sum(np.abs(eigenvalues) <= floor))

    raw_si = raw_relative_count(single_sway_column("m-kN"))
    raw_mm = raw_relative_count(single_sway_column("mm-N"))
    assert raw_si == 1
    assert raw_mm == 3  # wrong answer - exactly why equilibration replaces this rule

    eq_si = _diagnose_in_process(single_sway_column("m-kN")).mechanism_count
    eq_mm = _diagnose_in_process(single_sway_column("mm-N")).mechanism_count
    assert eq_si == 1
    assert eq_mm == 1


# --------------------------------------------------------------------------- #
# 12. K*phi residual sanity check.                                            #
# --------------------------------------------------------------------------- #


def test_case_12_kphi_residual_is_near_zero_for_every_reported_mode() -> None:
    for factory in (single_sway_column, free_portal_no_supports, lambda: diaphragm_two_column(unstable=True)):
        result = _diagnose_in_process(factory())
        for mode in result.modes:
            assert mode.residual < 1.0e-8, (factory, mode)


# --------------------------------------------------------------------------- #
# Gate 1. _build vs export/worker assembly - diagnostic follows the live      #
# domain that actually failed, never rebuilds with the other path.           #
# --------------------------------------------------------------------------- #


def test_gate1_truss_ndf_mismatch_between_build_and_export(tmp_path: Path) -> None:
    """3D canvas always stamps ndf=6. In-process ``_build`` overrides to
    ndf=3 for a pure truss (base rotations never enter K). Export/worker
    keep ndf=6, so base-node rotations stay free -> a different (and here,
    singular) system. The diagnostic must reflect whichever domain actually
    failed, not silently agree with the other builder."""
    model = canvas_style_3d_truss()
    assert check_determinacy(model).system == "truss"

    built = _diagnose_in_process(model)
    exported = _diagnose_export(model, tmp_path)

    assert built.matrix_size < exported.matrix_size
    assert built.mechanism_count == 0
    assert exported.mechanism_count > 0


def test_gate1_mixed_orphan_rotation_pin_mismatch(tmp_path: Path) -> None:
    """``_build``'s mixed-family path pins a truss-only joint's orphan
    rotations; export does not call that pinning step at all."""
    built = _diagnose_in_process(guyed_mast())
    exported = _diagnose_export(guyed_mast(), tmp_path)

    assert built.matrix_size == exported.matrix_size - 3
    assert built.mechanism_count == 0
    assert exported.mechanism_count >= 3
