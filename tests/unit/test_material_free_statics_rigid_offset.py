"""Rigid end-zone offset (``Element.offset_i``/``offset_j``) - solver.py's
``-jntOffset`` wiring on the element's own ``geomTransf``.

Closed form: only the *far* (loaded) end's offset needs deriving by hand -
the near end sits at a zero-rotation fixed base, so its own rigid zone
carries no rotation and simply shortens the flexible span. The loaded end's
rigid arm, though, transmits the tip force as a force *and* a moment onto
the flexible beam - a classic eccentric-load-through-a-rigid-arm case:

    delta = (P / EI) * (Leff**3/3 + a*Leff**2 + a**2*Leff)

where ``Leff = L - a`` is the flexible span and ``a`` is the tip-side
offset. Independently verified against a hand-rotation-kinematics derivation
before being written here (superposing a tip force P and tip moment P*a on
a plain cantilever of length Leff, then carrying that end's slope through
the rigid arm) - both match to 1e-9.
"""

import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy


def test_rigid_offset_at_the_loaded_end_matches_the_eccentric_arm_closed_form() -> None:
    length = 4.0
    offset = 1.0
    load = 1000.0
    elastic = 200000.0
    inertia = 0.0002
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, length, 0.0, 0.0)},
        elements={
            1: Element(
                1,
                1,
                2,
                "frame",
                properties={"E": elastic, "A": 0.02, "G": 80000.0, "J": 0.0005, "Iy": inertia, "Iz": inertia},
                offset_j=(-offset, 0.0, 0.0),
            )
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (0.0, 0.0, -load, 0.0, 0.0, 0.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    effective_length = length - offset
    ei = elastic * inertia
    expected = (load / ei) * (
        effective_length**3 / 3 + offset * effective_length**2 + offset**2 * effective_length
    )
    assert result.node_results[2].displacement[2] == pytest.approx(-expected, rel=1.0e-6)


def test_zero_offset_reproduces_the_plain_cantilever_exactly() -> None:
    """(0, 0, 0) at both ends must change nothing - every element drawn
    before this feature existed keeps behaving identically."""
    length = 4.0
    load = 1000.0
    elastic = 200000.0
    inertia = 0.0002
    properties = {"E": elastic, "A": 0.02, "G": 80000.0, "J": 0.0005, "Iy": inertia, "Iz": inertia}
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, length, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame", properties=properties)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (0.0, 0.0, -load, 0.0, 0.0, 0.0))],
    )

    result = MaterialFreeStaticsSolver().solve(model)

    expected = load * length**3 / (3 * elastic * inertia)
    assert result.node_results[2].displacement[2] == pytest.approx(-expected, rel=1.0e-9)
