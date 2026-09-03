"""Validation spike: is stiffness-matrix mechanism detection reliable?

NOT a product feature. No ``InstabilityDiagnosticService``, no UI, no result
types, no wiring into the normal solver. This file only *proves or disproves*
one hypothesis with tests:

    When a normal linear-static solve is singular, we can re-assemble the free
    stiffness matrix K under FullGeneral, take ``np.linalg.eigh((K+K.T)/2)``,
    and reliably (a) count the true structural mechanisms as near-zero
    eigenvalues and (b) recover each mechanism's shape - across unit systems,
    without false positives on legitimate hinges, and with equalDOF /
    rigidDiaphragm slave DOFs correctly reconstructed.

It re-uses the *production* assembly path (``MaterialFreeStaticsSolver._build``,
which applies the exact same hinge / orphan-rotation-pin policy the real solver
uses) and the *already validated* mapping helpers in ``buckling_solver`` - the
whole point is to test the pipeline we would actually ship, not a parallel one.

Run as a report:  ``python -m tests.integration.test_instability_detection_spike``
Run as tests:     ``pytest tests/integration/test_instability_detection_spike.py``
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

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
from openframe.features.analysis.statics.solver import (
    MaterialFreeStaticsSolver,
    check_determinacy,
)
from openframe.infrastructure.opensees.buckling_solver import (
    _correct_constrained_dof_values,
    _mode_shape_from_eigenvector,
    _normalize_mode_shape,
)
from tests.integration.buckling_3d_hinge_diagnostics_helpers import (
    FRAME_PROPERTIES_3D,
    shared_hinge_cantilever,
    stable_portal_shared_hinge,
    vertical_cantilever,
)

_DOF_NAMES = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")

#: The repo's current near-zero rule, lifted verbatim from
#: ``buckling_solver._count_near_zero_stiffness_modes`` /
#: ``buckling_3d_hinge_diagnostics_helpers.stiffness_diagnostics``:
#:     floor = max(1e-6 * max|eigenvalue|, 1e-6)
#: This spike's job is to decide whether *this* rule is trustworthy.
_CURRENT_RELATIVE_FLOOR = 1.0e-6


# --------------------------------------------------------------------------- #
# Core spike machinery: assemble free K two ways, symmetrize, eigen-decompose. #
# --------------------------------------------------------------------------- #


@dataclass
class Extraction:
    K: np.ndarray
    system_size: int
    node_tags: list[int]
    node_dof_equations: dict[int, list[int]]
    ndm: int


def _fullgeneral_static_stack() -> None:
    ops.wipeAnalysis()
    ops.system("FullGeneral")
    ops.numberer("RCM")
    # Transformation (not Plain) so equalDOF/rigidDiaphragm constraints are
    # actually condensed into K - required for Case F, and what a real
    # diagnostic must use anyway. buckling_solver uses the same handler.
    ops.constraints("Transformation")
    ops.algorithm("Linear")


def _extract_after_build(ndm: int) -> Extraction:
    size = ops.systemSize()
    flat = ops.printA("-ret")
    matrix = np.asarray(flat, dtype=float).reshape(size, size)
    node_tags = [int(t) for t in ops.getNodeTags()]
    node_dof_equations = {t: [int(v) for v in ops.nodeDOFs(t)] for t in node_tags}
    return Extraction(matrix, size, node_tags, node_dof_equations, ndm)


def assemble_K_current(model: StructuralModel) -> Extraction:
    """Method A - the buckling solver's existing recipe: FullGeneral +
    LoadControl(0) + one Static ``analyze(1)`` at zero load, then printA."""
    ops.wipe()
    system = check_determinacy(model).system
    MaterialFreeStaticsSolver._build(model, system)  # noqa: SLF001 - production parity
    _fullgeneral_static_stack()
    ops.integrator("LoadControl", 0.0)
    ops.analysis("Static")
    ops.analyze(1)  # printA still returns the assembled tangent even if solve is singular
    return _extract_after_build(model.ndm)


def assemble_K_gimme(model: StructuralModel) -> Extraction | None:
    """Method B - GimmeMCK(0, 0, 1) assembles A = 0*M + 0*C + 1*K under a
    Transient analysis, then printA. Returns None if GimmeMCK is unavailable in
    this OpenSeesPy build (itself a reportable finding)."""
    ops.wipe()
    system = check_determinacy(model).system
    MaterialFreeStaticsSolver._build(model, system)  # noqa: SLF001
    _fullgeneral_static_stack()
    try:
        ops.integrator("GimmeMCK", 0.0, 0.0, 1.0)
        ops.analysis("Transient")
        ops.analyze(1, 0.0)
    except Exception:  # noqa: BLE001 - availability probe
        return None
    return _extract_after_build(model.ndm)


def eig_symmetric(K: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    symmetric = (K + K.T) / 2.0
    return np.linalg.eigh(symmetric)  # ascending eigenvalues, orthonormal V


def mechanism_count(eigenvalues: np.ndarray, relative_floor: float = _CURRENT_RELATIVE_FLOOR) -> int:
    scale = float(np.max(np.abs(eigenvalues))) if eigenvalues.size else 0.0
    floor = max(relative_floor * scale, relative_floor)
    return int(np.sum(np.abs(eigenvalues) <= floor))


def dominant_dofs(
    eigenvector: np.ndarray, extraction: Extraction, threshold: float = 0.15
) -> list[str]:
    normalizer = float(np.max(np.abs(eigenvector))) or 1.0
    parts: list[str] = []
    for tag in extraction.node_tags:
        for dof_index, equation in enumerate(extraction.node_dof_equations[tag]):
            if 0 <= equation < extraction.system_size:
                value = eigenvector[equation] / normalizer
                if abs(value) > threshold:
                    name = _DOF_NAMES[dof_index] if dof_index < len(_DOF_NAMES) else f"d{dof_index}"
                    parts.append(f"n{tag}:{name}={value:+.2f}")
    return parts


def equilibrate(K: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Jacobi (diagonal) equilibration: Ks = D^-1 K D^-1 with D=diag(sqrt|Kii|).

    Makes the spectrum dimensionless and scale-free: every diagonal becomes 1,
    so neither the unit system nor a penalty stiffness (the 1e8 hinge material)
    can inflate max|lambda| and drag the relative floor over genuine soft modes.
    A true rigid-body / mechanism mode stays ~machine-eps; real modes become O(1).
    Returns (eigenvalues, Dinv) - multiply an eigenvector by Dinv to return it to
    physical DOF space.
    """
    diagonal = np.sqrt(np.abs(np.diag(K)))
    diagonal[diagonal == 0.0] = 1.0
    dinv = 1.0 / diagonal
    scaled = (K * dinv[None, :]) * dinv[:, None]
    eigenvalues = np.linalg.eigvalsh((scaled + scaled.T) / 2.0)
    return eigenvalues, dinv


#: Absolute floor in EQUILIBRATED space. The spike shows true mechanisms /
#: rigid-body modes land at ~1e-14..1e-16 there, while the softest genuine
#: structural mode observed (a penalty-hinge out-of-plane mode) stays >= ~1e-8 -
#: so a fixed 1e-10 sits squarely in that 6-8 order gap and is unit-invariant
#: (equilibration already removed the scale). NOT relative to max: relative is
#: exactly what the penalty stiffness and unit system break.
_EQUILIBRATED_ABSOLUTE_FLOOR = 1.0e-10


def mechanism_count_equilibrated(
    K: np.ndarray, absolute_floor: float = _EQUILIBRATED_ABSOLUTE_FLOOR
) -> int:
    eigenvalues, _ = equilibrate(K)
    return int(np.sum(np.abs(eigenvalues) <= absolute_floor))


def analyze_model(model: StructuralModel) -> dict:
    extraction = assemble_K_current(model)
    eigenvalues, eigenvectors = eig_symmetric(extraction.K)
    count = mechanism_count(eigenvalues)
    scale = float(np.max(np.abs(eigenvalues)))
    floor = max(_CURRENT_RELATIVE_FLOOR * scale, _CURRENT_RELATIVE_FLOOR)
    near_zero_idx = [i for i, v in enumerate(eigenvalues) if abs(v) <= floor]
    smallest_real = next(
        (float(eigenvalues[i]) for i in range(len(eigenvalues)) if i not in near_zero_idx),
        float("nan"),
    )
    shapes = [dominant_dofs(eigenvectors[:, i], extraction) for i in near_zero_idx[:8]]
    return {
        "extraction": extraction,
        "eigenvalues": eigenvalues,
        "eigenvectors": eigenvectors,
        "count": count,
        "count_eq": mechanism_count_equilibrated(extraction.K),
        "max_eig": scale,
        "floor": floor,
        "near_zero_eigs": [float(eigenvalues[i]) for i in near_zero_idx],
        "smallest_real_eig": smallest_real,
        "shapes": shapes,
    }


# --------------------------------------------------------------------------- #
# Test models (A-F). Frame models re-use FRAME_PROPERTIES_3D from the helper.  #
# --------------------------------------------------------------------------- #


def free_portal_no_supports() -> StructuralModel:
    """Case B: a portal frame (2 columns + beam) with NO supports at all.
    A stable structure floating in space -> exactly 6 rigid-body modes."""
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
    """Case C: a vertical column whose base is fully fixed EXCEPT global Ux.
    The whole column can rigidly translate in X and nothing resists it ->
    exactly one mechanism, in a single, known direction. Also the unit-system
    probe model (section 4)."""
    if unit == "m-kN":
        props = dict(FRAME_PROPERTIES_3D)  # E=2e8 kN/m2, A=0.02 m2, Iy=6e-5 m4 ...
        length = 4.0
    elif unit == "mm-N":
        props = {  # same physical column, N-mm units
            "E": 2.0e5,   # 2e8 kN/m2  -> N/mm2
            "A": 2.0e4,   # 0.02 m2    -> mm2
            "G": 7.7e4,   # 7.7e7 kN/m2-> N/mm2
            "J": 2.0e6,   # 2e-6 m4    -> mm4
            "Iy": 6.0e7,  # 6e-5 m4    -> mm4
            "Iz": 8.0e7,  # 8e-5 m4    -> mm4
        }
        length = 4000.0
    else:  # pragma: no cover - guard
        raise ValueError(unit)
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, length)},
        elements={1: Element(1, 1, 2, "frame", properties=props)},
        # base fixed in Uy,Uz,Rx,Ry,Rz ; FREE in Ux -> one sway/translation DOF
        boundaries=[BoundaryCondition(1, (False, True, True, True, True, True))],
    )


def tetrahedral_truss() -> StructuralModel:
    """Case D: a stable space truss (ndf=3). Apex held by 3 non-coplanar bars,
    3 base joints pinned -> 0 mechanisms."""
    props = {"E": 2.0e8, "A": 0.01}
    nodes = {
        1: Node(1, 0.0, 0.0, 0.0),
        2: Node(2, 4.0, 0.0, 0.0),
        3: Node(3, 2.0, 3.5, 0.0),
        4: Node(4, 2.0, 1.2, 3.0),  # apex
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
        ndm=3,
        ndf=3,
        nodes=nodes,
        elements=elements,
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (True, True, True)),
            BoundaryCondition(3, (True, True, True)),
        ],
    )


def diaphragm_two_column(*, unstable: bool) -> StructuralModel:
    """Case F: two columns tied at the top by a rigidDiaphragm (perp_dirn=3,
    master=2, slave=4). ``unstable=False`` -> fixed bases, stable, 0 mechanisms
    (used to verify slave-DOF reconstruction on an eigenvector). ``unstable=True``
    -> bases free to rotate about Y, so both tops sway together in X -> the tied
    Ux is part of the mechanism, the sharpest possible reconstruction test."""
    props = {"E": 2.0e8, "A": 0.02, "G": 7.7e7, "J": 2.0e-6, "Iy": 6.0e-5, "Iz": 8.0e-5}
    if unstable:
        base = (True, True, True, True, False, True)  # free Ry -> inverted-pendulum sway in X
    else:
        base = (True, True, True, True, True, True)
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
# 1. K extraction comparison: current (LoadControl) vs GimmeMCK.               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "factory",
    [single_sway_column, free_portal_no_supports, lambda: vertical_cantilever()],
    ids=["sway_column", "free_portal", "stable_cantilever"],
)
def test_current_and_gimme_extract_the_same_K(factory) -> None:
    model = factory()
    a = assemble_K_current(model)
    b = assemble_K_gimme(model)
    if b is None:
        pytest.skip("GimmeMCK integrator unavailable in this OpenSeesPy build")
    assert a.K.shape == b.K.shape
    denom = float(np.max(np.abs(a.K))) or 1.0
    rel_diff = float(np.max(np.abs(a.K - b.K))) / denom
    assert rel_diff < 1.0e-9, f"K differs between methods by relative {rel_diff:.2e}"
    # Same mechanism verdict from both matrices.
    assert mechanism_count(eig_symmetric(a.K)[0]) == mechanism_count(eig_symmetric(b.K)[0])
    ops.wipe()


# --------------------------------------------------------------------------- #
# 2 & 3. Mechanism counts for the required structural cases.                   #
# --------------------------------------------------------------------------- #


def test_case_A_stable_cantilever_zero_mechanisms() -> None:
    result = analyze_model(vertical_cantilever())
    assert result["count"] == 0
    ops.wipe()


def test_case_B_free_frame_six_rigid_body_modes() -> None:
    result = analyze_model(free_portal_no_supports())
    assert result["count"] == 6, result["near_zero_eigs"]
    ops.wipe()


def test_case_C_single_sway_one_mechanism_in_x() -> None:
    result = analyze_model(single_sway_column())
    assert result["count"] == 1, result["near_zero_eigs"]
    # The one mechanism must be the global X translation.
    dominant = " ".join(result["shapes"][0])
    assert "Ux" in dominant
    assert "Uy" not in dominant and "Uz" not in dominant
    ops.wipe()


def test_case_D_tetrahedral_truss_zero_mechanisms() -> None:
    result = analyze_model(tetrahedral_truss())
    assert result["count"] == 0, result["near_zero_eigs"]
    ops.wipe()


@pytest.mark.parametrize(
    "factory,expected",
    [
        (stable_portal_shared_hinge, 0),                 # legit shared hinge, stable
        (lambda: vertical_cantilever(release_j=True), 0),  # hinge at free tip, stable
        # A 3D moment release frees BOTH bending axes (My AND Mz) - a spherical
        # pin - so a destabilizing 3D hinge yields TWO rigid-rotation mechanisms,
        # not one. (Confirmed empirically: equilibrated eigs sit at ~1e-16 x2.)
        (lambda: vertical_cantilever(release_i=True), 2),  # base hinge = 2 rotation mechanisms
        (shared_hinge_cantilever, 2),                    # mid-height hinge = 2 rotation mechanisms
    ],
    ids=["stable_shared_hinge", "tip_hinge", "base_hinge_mechanism", "midheight_hinge_mechanism"],
)
def test_case_E_hinges_no_false_positive_but_catch_real_ones(factory, expected) -> None:
    """The orphan-rotation-pin policy (applied by _build) must NOT be counted as
    a mechanism, yet a genuinely destabilizing hinge still must be. Uses the
    equilibrated criterion - the raw relative floor fails every row here."""
    result = analyze_model(factory())
    assert result["count_eq"] == expected, {
        "raw": result["count"],
        "near_zero_raw": result["near_zero_eigs"],
        "smallest_real": result["smallest_real_eig"],
    }
    ops.wipe()


# --------------------------------------------------------------------------- #
# Case F. rigidDiaphragm: slave DOF reconstruction on an eigenvector.          #
# --------------------------------------------------------------------------- #


def test_case_F_stable_diaphragm_zero_mechanisms() -> None:
    result = analyze_model(diaphragm_two_column(unstable=False))
    assert result["count"] == 0, result["near_zero_eigs"]
    ops.wipe()


def test_case_F_slave_dof_reconstructed_from_master() -> None:
    """Build the diaphragm model, pick the eigenvector with the largest master
    (node 2) Ux component, and show that node 4's tied Ux is (a) NOT recoverable
    by raw equation indexing but (b) correctly recovered by
    buckling_solver._correct_constrained_dof_values."""
    model = diaphragm_two_column(unstable=False)
    extraction = assemble_K_current(model)  # leaves the model built (needed by the corrector)
    eigenvalues, eigenvectors = eig_symmetric(extraction.K)

    master_ux_equation = extraction.node_dof_equations[2][0]
    assert master_ux_equation >= 0
    # Eigenvector whose master-Ux participation is largest.
    best = int(np.argmax(np.abs(eigenvectors[master_ux_equation, :])))
    vector = eigenvectors[:, best]

    raw_shape = _mode_shape_from_eigenvector(
        vector, extraction.node_tags, extraction.node_dof_equations, extraction.system_size
    )
    master_ux = raw_shape[2][0]
    assert abs(master_ux) > 1.0e-6, "chose an eigenvector with no master Ux - test setup wrong"
    # Raw indexing does NOT give the slave its physical (tied) value.
    assert abs(raw_shape[4][0]) < 1.0e-9 * abs(master_ux) or raw_shape[4][0] != pytest.approx(
        master_ux, rel=1.0e-6
    )

    corrected = copy.deepcopy(raw_shape)
    found = _correct_constrained_dof_values(extraction.node_tags, corrected, extraction.ndm)
    assert found, "no constrained node detected - diaphragm wiring missing"
    # After correction the slave's tied Ux equals the master's Ux (rigid tie).
    assert corrected[4][0] == pytest.approx(master_ux, rel=1.0e-9, abs=1.0e-12)
    # And normalization still runs on the reconstructed shape.
    _normalize_mode_shape(corrected, extraction.ndm)
    ops.wipe()


# --------------------------------------------------------------------------- #
# 4. Unit-system sensitivity of the mechanism verdict AND the tolerance.       #
# --------------------------------------------------------------------------- #


def test_raw_relative_floor_is_NOT_unit_invariant() -> None:
    """DEFECT, documented: the current 1e-6*max|lambda| rule gives a different
    mechanism verdict for the SAME physical column in different units - 1 in
    m-kN, but 3 in N-mm (two genuine soft bending modes drown under the inflated
    floor). This is the reason a raw relative floor cannot ship."""
    r_si = analyze_model(single_sway_column("m-kN"))
    ops.wipe()
    r_mm = analyze_model(single_sway_column("mm-N"))
    ops.wipe()
    assert r_si["count"] == 1
    assert r_mm["count"] == 3  # <-- wrong answer, but this IS what the raw rule returns
    assert r_si["count"] != r_mm["count"], "expected the raw floor to be unit-sensitive"


def test_equilibrated_count_IS_unit_invariant() -> None:
    """FIX, verified: diagonal equilibration + an absolute floor gives the
    correct single mechanism in BOTH unit systems."""
    for unit in ("m-kN", "mm-N"):
        model = single_sway_column(unit)
        extraction = assemble_K_current(model)
        ops.wipe()
        assert mechanism_count_equilibrated(extraction.K) == 1, unit


def test_equilibrated_spectrum_separates_true_zeros_from_soft_real_modes() -> None:
    """The property the absolute floor relies on: in equilibrated space a true
    mechanism sits at ~machine-eps (<=1e-12) while the softest genuine structural
    mode stays well above the 1e-10 floor - a multi-order gap, in every unit
    system. Checked on a model WITH a true mechanism (base hinge, 2 zeros) and a
    fully stable hinged frame (no zeros, softest mode ~1e-8)."""
    # True mechanisms cluster at machine-eps, far below the floor.
    for unit in ("m-kN", "mm-N"):
        extraction = assemble_K_current(single_sway_column(unit))
        ops.wipe()
        eq, _ = equilibrate(extraction.K)
        smallest = np.sort(np.abs(eq))
        assert smallest[0] < 1.0e-12, (unit, smallest[0])          # the mechanism
        assert smallest[1] > 1.0e-6, (unit, smallest[1])           # first real mode

    # A stable hinged frame has NO machine-eps mode; its softest is ~1e-8,
    # comfortably above the 1e-10 floor (so it is NOT miscounted).
    extraction = assemble_K_current(stable_portal_shared_hinge())
    ops.wipe()
    eq, _ = equilibrate(extraction.K)
    assert float(np.min(np.abs(eq))) > _EQUILIBRATED_ABSOLUTE_FLOOR


# --------------------------------------------------------------------------- #
# Report entry point (not a test).                                            #
# --------------------------------------------------------------------------- #


def _report() -> None:
    def line(title: str, model: StructuralModel, expected) -> None:
        result = analyze_model(model)
        ops.wipe()
        nz = ", ".join(f"{e:+.2e}" for e in result["near_zero_eigs"]) or "-"
        shape0 = "; ".join(result["shapes"][0]) if result["shapes"] else "-"
        raw_ok = result["count"] == expected
        eq_ok = result["count_eq"] == expected
        verdict = ("OK " if raw_ok else "!! ") + ("EQ:ok " if eq_ok else "EQ:BAD")
        print(
            f"{verdict} {title:<34} n={result['extraction'].system_size:<3} "
            f"raw={result['count']} eq={result['count_eq']} (exp {expected})  "
            f"max|λ|={result['max_eig']:.2e} floor={result['floor']:.2e}  "
            f"smallest_real={result['smallest_real_eig']:.2e}"
        )
        print(f"     near-zero λ (raw): [{nz}]")
        print(f"     mode[0] dominant: {shape0}")

    print("\n=== Instability detection validation spike ===\n")
    line("A stable 3D cantilever", vertical_cantilever(), 0)
    line("B free frame (no supports)", free_portal_no_supports(), 6)
    line("C single sway column", single_sway_column("m-kN"), 1)
    line("C single sway column (mm-N)", single_sway_column("mm-N"), 1)
    line("D tetrahedral truss", tetrahedral_truss(), 0)
    line("E stable shared hinge", stable_portal_shared_hinge(), 0)
    line("E tip hinge (stable)", vertical_cantilever(release_j=True), 0)
    line("E base hinge (mechanism)", vertical_cantilever(release_i=True), 2)
    line("E mid-height hinge (mechanism)", shared_hinge_cantilever(), 2)
    line("F stable diaphragm", diaphragm_two_column(unstable=False), 0)
    line("F unstable diaphragm", diaphragm_two_column(unstable=True), 1)

    print("\n--- K extraction: current (LoadControl) vs GimmeMCK ---")
    for name, factory in [
        ("sway_column", single_sway_column),
        ("free_portal", free_portal_no_supports),
        ("stable_cantilever", lambda: vertical_cantilever()),
    ]:
        model = factory()
        a = assemble_K_current(model)
        b = assemble_K_gimme(model)
        if b is None:
            print(f"  {name:<18} GimmeMCK unavailable")
            ops.wipe()
            continue
        denom = float(np.max(np.abs(a.K))) or 1.0
        rel = float(np.max(np.abs(a.K - b.K))) / denom
        sym_a = float(np.max(np.abs(a.K - a.K.T))) / denom
        print(
            f"  {name:<18} shape={a.K.shape} relΔ={rel:.2e} "
            f"asym(A)={sym_a:.2e} finite={np.all(np.isfinite(a.K)) and np.all(np.isfinite(b.K))} "
            f"mech(A)={mechanism_count(eig_symmetric(a.K)[0])} mech(B)={mechanism_count(eig_symmetric(b.K)[0])}"
        )
        ops.wipe()
    print()


if __name__ == "__main__":
    _report()
