"""Validation for the conditional corotTruss + InitStrainMaterial prestress
export path (opensees_script_export.py) and the truss-aware ``_local_forces``
fallback it depends on (linear_static_solver.py).

Scope of this feature as of this test file: Linear Static and Nonlinear
Static analysis only. Every other analysis kind (Modal, Buckling, Response
Spectrum, Time History) happens to consume the same exported script text via
the same ``ModelCommandCollector``/``run_model_script`` machinery, but
whether a prestressed corotTruss element behaves correctly under THOSE
solvers has not been verified here and must not be assumed.

Sign convention (locked down first, per project decision): a POSITIVE
``Element.prestress`` is an installed TENSION - ``test_sign_convention_*``
below is the authority for this, verified against a fully axially-restrained
single truss (no possible length change), where InitStrainMaterial's wrapped
strain equals the initial strain exactly and the resulting axial force must
equal the input prestress value exactly, tension positive.
"""

import math
from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.core.domain.model import (
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
)
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.infrastructure.opensees.linear_static_solver import run_linear_static_analysis

_E = 2.0e8  # kPa (steel, kN/m^2 units)


def _run(model: StructuralModel, tmp_path: Path, name: str = "model.py") -> dict:
    script = export_opensees_script(model)
    script_path = tmp_path / name
    script_path.write_text(script, encoding="utf-8")
    try:
        return run_linear_static_analysis(script_path)
    finally:
        ops.wipe()


def _axial_forces(results: dict) -> dict[int, float]:
    """tag -> signed axial force (tension positive), from the padded
    (Fxi, Fyi, Fxj, Fyj)-shaped local_forces a 2-force member reports."""
    forces = {}
    for item in results["element_results"]:
        local = item["local_forces"]
        assert len(local) >= 4
        forces[item["element_tag"]] = local[2]  # Fxj: +tension on a 2-force member
    return forces


# ---------------------------------------------------------------------------
# 1. Sign convention (locked down first) - a fully axially-restrained truss
#    cannot change length, so InitStrainMaterial's wrapped strain equals the
#    prestress-implied initial strain exactly and the reported axial force
#    must equal the input prestress exactly (tension positive).
# ---------------------------------------------------------------------------

def _fully_restrained_model(prestress: float) -> StructuralModel:
    elastic, area = _E, 0.001
    nodes = {
        1: Node(1, 0.0, 0.0),
        2: Node(2, 3.0, 0.0),
        # Disconnected, triangulated padding component - keeps the global
        # system from being literally 0x0 free DOFs (which OpenSees'
        # BandGeneral solver errors on), without touching element 1's own
        # equilibrium at all (fully independent node/element set, unloaded).
        3: Node(3, 10.0, 0.0),
        4: Node(4, 13.0, 1.5),
        5: Node(5, 10.0, 3.0),
    }
    elements = {
        1: Element(1, 1, 2, "truss", properties={"E": elastic, "A": area}, prestress=prestress),
        2: Element(2, 3, 4, "truss", properties={"E": elastic, "A": area}),
        3: Element(3, 5, 4, "truss", properties={"E": elastic, "A": area}),
    }
    boundaries = [
        BoundaryCondition(1, (True, True)),
        BoundaryCondition(2, (True, True)),
        BoundaryCondition(3, (True, True)),
        BoundaryCondition(5, (True, True)),
    ]
    return StructuralModel(ndm=2, ndf=2, nodes=nodes, elements=elements, boundaries=boundaries)


def test_sign_convention_positive_prestress_reads_as_tension(tmp_path: Path) -> None:
    results = _run(_fully_restrained_model(50.0), tmp_path)
    assert results["status"] == "completed"
    assert _axial_forces(results)[1] == pytest.approx(50.0, abs=1e-6)


def test_sign_convention_negative_prestress_reads_as_compression(tmp_path: Path) -> None:
    results = _run(_fully_restrained_model(-50.0), tmp_path)
    assert results["status"] == "completed"
    assert _axial_forces(results)[1] == pytest.approx(-50.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 2. Regression: a truss element with prestress == 0.0 (every model that
#    existed before this feature) must keep emitting the exact same script
#    text and produce the exact same results as before - no corotTruss, no
#    InitStrainMaterial.
# ---------------------------------------------------------------------------

def _plain_two_bar_model(*, load: float) -> tuple[StructuralModel, float]:
    """A minimal determinate 2-bar truss under a point load - closed form:
    each bar carries load / (2 sin(theta))."""
    half_span, height = 3.0, 4.0
    length = math.hypot(half_span, height)
    sin_theta = height / length
    nodes = {
        1: Node(1, 0.0, 0.0),
        2: Node(2, 2 * half_span, 0.0),
        3: Node(3, half_span, height),
    }
    elements = {
        1: Element(1, 1, 3, "truss", properties={"E": _E, "A": 0.002}),
        2: Element(2, 2, 3, "truss", properties={"E": _E, "A": 0.002}),
    }
    boundaries = [
        BoundaryCondition(1, (True, True)),
        BoundaryCondition(2, (True, True)),
    ]
    nodal_loads = [NodalLoad(3, (0.0, -load))]
    model = StructuralModel(
        ndm=2, ndf=2, nodes=nodes, elements=elements,
        boundaries=boundaries, nodal_loads=nodal_loads,
    )
    return model, sin_theta


def test_zero_prestress_truss_keeps_emitting_plain_truss_element() -> None:
    model, _ = _plain_two_bar_model(load=0.0)
    script = export_opensees_script(model)
    assert "ops.element('Truss', 1," in script
    assert "ops.element('Truss', 2," in script
    assert "corotTruss" not in script
    assert "InitStrainMaterial" not in script


def test_zero_prestress_truss_results_match_closed_form(tmp_path: Path) -> None:
    load = 100.0
    model, sin_theta = _plain_two_bar_model(load=load)
    results = _run(model, tmp_path)
    assert results["status"] == "completed"

    forces = _axial_forces(results)
    expected = -load / (2 * sin_theta)  # compression, by symmetry
    assert forces[1] == pytest.approx(expected, rel=1e-6)
    assert forces[2] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# 3. Prestressed truss: corotTruss + InitStrainMaterial actually get emitted,
#    and (via the symmetric A-frame closed-form case) prestress and an
#    external load combine correctly through equilibrium.
# ---------------------------------------------------------------------------

_A_RAFTER = 0.005
_A_TIE = 0.001
_PRESTRESS = 50.0  # kN, installed tension in the tie
_HALF_SPAN = 3.0
_HEIGHT = 2.0
_RAFTER_LENGTH = math.hypot(_HALF_SPAN, _HEIGHT)
_SIN_THETA = _HEIGHT / _RAFTER_LENGTH


def _a_frame_model(*, load: float = 0.0) -> StructuralModel:
    """Symmetric "A-frame", all three bars ``element_type == "truss"`` - node
    1 a pin, node 2 a roller (vertical only), node 3 the free apex. A
    classic 3-bar determinate truss (m=3, r=3, n=3 joints => m+r=2n), which
    is what makes an exact closed-form check possible."""
    nodes = {
        1: Node(1, 0.0, 0.0),
        2: Node(2, 2 * _HALF_SPAN, 0.0),
        3: Node(3, _HALF_SPAN, _HEIGHT),
    }
    elements = {
        1: Element(1, 1, 3, "truss", properties={"E": _E, "A": _A_RAFTER}),
        2: Element(2, 2, 3, "truss", properties={"E": _E, "A": _A_RAFTER}),
        3: Element(
            3, 1, 2, "truss",
            properties={"E": _E, "A": _A_TIE},
            prestress=_PRESTRESS,
        ),
    }
    boundaries = [
        BoundaryCondition(1, (True, True)),
        BoundaryCondition(2, (False, True)),
    ]
    nodal_loads = [NodalLoad(3, (0.0, -load))] if load else []
    return StructuralModel(
        ndm=2, ndf=2, nodes=nodes, elements=elements,
        boundaries=boundaries, nodal_loads=nodal_loads,
    )


def test_prestressed_truss_emits_corottruss_and_init_strain_material() -> None:
    script = export_opensees_script(_a_frame_model())
    assert "ops.element('corotTruss', 3," in script
    assert "ops.uniaxialMaterial('InitStrainMaterial'" in script
    init_strain = _PRESTRESS / (_E * _A_TIE)
    assert repr(init_strain) in script
    # The two unprestressed rafters are untouched by the new code path.
    assert "ops.element('Truss', 1," in script
    assert "ops.element('Truss', 2," in script


def test_prestress_alone_produces_zero_force_in_a_determinate_structure(tmp_path: Path) -> None:
    """Textbook fact: a determinate structure cannot self-stress. Every member
    force should be ~0, and node 2 should shift by the tie's stress-free
    contraction (prestress/EA * length, toward node 1)."""
    results = _run(_a_frame_model(load=0.0), tmp_path)
    assert results["status"] == "completed"

    forces = _axial_forces(results)
    for tag, force in forces.items():
        # A single LinearStatic step through corotTruss's geometrically
        # nonlinear tangent leaves a small residual relative to a fully
        # iterated nonlinear equilibrium - 0.1 kN (~0.2% of the 50 kN
        # prestress) comfortably separates "expected geometric-nonlinearity
        # residual" from "prestress is not actually self-relieving".
        assert force == pytest.approx(0.0, abs=0.1), f"element {tag}: expected ~0, got {force}"

    node2 = next(n for n in results["node_results"] if n["node_tag"] == 2)
    # A tensile prestress means the tie's *unstressed* length is shorter than
    # its as-installed (node-to-node) length - InitStrainMaterial models this
    # by evaluating the base material at (mechanical_strain + initStrain), so
    # the zero-force equilibrium settles at mechanical_strain == -initStrain:
    # the tie physically contracts, pulling node 2 toward node 1 (-x).
    expected_dx = -_PRESTRESS / (_E * _A_TIE) * (2 * _HALF_SPAN)
    assert node2["displacement"][0] == pytest.approx(expected_dx, rel=1e-3)


def test_prestress_and_external_load_superpose_correctly(tmp_path: Path) -> None:
    """Load-only closed form (classic 2-bar apex-loaded truss) superposed with
    the zero-force prestress case above must match the combined FEM result."""
    load = 100.0
    results = _run(_a_frame_model(load=load), tmp_path)
    assert results["status"] == "completed"

    forces = _axial_forces(results)
    expected_rafter = -load / (2 * _SIN_THETA)  # compression
    expected_tie = load / (2 * math.tan(math.asin(_SIN_THETA)))  # tension

    assert forces[1] == pytest.approx(expected_rafter, rel=1e-3)
    assert forces[2] == pytest.approx(expected_rafter, rel=1e-3)
    assert forces[3] == pytest.approx(expected_tie, rel=1e-3)
