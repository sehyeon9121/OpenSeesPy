"""Load-compiler edge cases the main suite does not pin down.

Closed-form expected values are derived from resultant and first-moment
balance about the origin. These tests call ``compile_loads``; they do not
re-implement ``integrate_two_node_load``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

import pytest

from openframe.core.domain.load_entry import (
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    SelfWeightEntry,
)
from openframe.core.domain.model import (
    Element,
    Node,
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.analysis.loads import LoadCompileError, compile_loads
from tests.unit.test_load_compiler import cross, line_model, resultant, wall_model


def _global_distributed(tag: int, direction: str, w1: float, w2: float, a=0.0, b=1.0, entry_id=1):
    return LoadEntry(
        entry_id,
        "Q",
        "member_partial",
        (tag,),
        MemberDistributedLoadEntry(
            coordinate_system="global",
            direction=direction,
            start_value=w1,
            end_value=w2,
            start_position=a,
            end_position=b,
        ),
    )


def test_reversed_connectivity_preserves_global_resultant_and_origin_moment():
    """a,b are measured from node i, not from the smaller global coordinate.

    Reversing i/j flips the parameterisation. A global uniform load on the
    same physical chord must still produce the same total force; the first
    moment about the origin follows the loaded interval in space, which
    moves when the interval is defined from the opposite end.
    """
    model = line_model()
    model.elements[1] = replace(model.elements[1], node_i=2, node_j=1)
    plan = compile_loads(model, entries=[_global_distributed(1, "y", -3, -3)])
    force, moment = resultant(model, plan)
    assert force == pytest.approx((0.0, -30.0, 0.0), abs=1e-12)
    assert moment == pytest.approx((0.0, 0.0, -150.0), abs=1e-12)

    partial = compile_loads(
        model, entries=[_global_distributed(1, "y", -2, -8, a=0.2, b=0.7)]
    )
    length = 10.0
    a, b = 0.2, 0.7
    total = (b - a) * length * (-2 + -8) / 2
    # Position along the reversed member: x(s) = L*(1-s). First moment about
    # the origin is wy * L^2 * integral_a^b (1-s) * intensity_shape, which for
    # a trapezoid with end intensities at s=a and s=b reduces to sampling
    # x(s) against the linear intensity.
    d = (b - a) * length
    # s runs i->j, x = L(1-s). Trapezoid centroid is measured along +s from i.
    centroid_from_i = a * length + d * (-2 + 2 * -8) / (3 * (-2 + -8))
    centroid_x = length - centroid_from_i
    force, moment = resultant(model, partial)
    assert force == pytest.approx((0.0, total, 0.0), abs=1e-12)
    assert moment[2] == pytest.approx(centroid_x * total, abs=1e-12)


def test_vertical_and_inclined_3d_truss_global_load_conserves_force_and_moment():
    vertical = line_model(ndm=3, end=(0.0, 0.0, 10.0))
    plan = compile_loads(vertical, entries=[_global_distributed(1, "y", -4, -4)])
    force, moment = resultant(vertical, plan)
    assert force == pytest.approx((0.0, -40.0, 0.0), abs=1e-12)
    # Centroid at (0, 0, L/2). r × F with F along -Y gives Mx = -z * Fy > 0.
    assert moment == pytest.approx((200.0, 0.0, 0.0), abs=1e-12)

    inclined = line_model(ndm=3, end=(3.0, 4.0, 12.0))
    plan = compile_loads(inclined, entries=[_global_distributed(1, "z", -1, -3, a=0.1, b=0.6)])
    length = 13.0
    d = 0.5 * length
    total = d * (-1 + -3) / 2
    first = 0.1 * length * total + d * d * (-1 + 2 * -3) / 6
    axis = (3.0 / length, 4.0 / length, 12.0 / length)
    expected_moment = cross(tuple(c * first for c in axis), (0.0, 0.0, 1.0))
    force, moment = resultant(inclined, plan)
    assert force == pytest.approx((0.0, 0.0, total), abs=1e-12)
    assert moment == pytest.approx(expected_moment, abs=1e-12)


def test_vertical_self_weight_is_axial_and_splits_equally_without_extra_g():
    model = line_model(ndm=3, end=(0.0, 0.0, 8.0))
    plan = compile_loads(model, self_weight=SelfWeightEntry(), gravity_acceleration=9.81)
    weight = 25.0 * 0.2 * 8.0
    force, moment = resultant(model, plan)
    assert force == pytest.approx((0.0, 0.0, -weight), abs=1e-12)
    assert moment == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    by_node = {load.node_tag: load.force for load in plan.nodal_loads}
    assert by_node[1] == pytest.approx((0.0, 0.0, -weight / 2))
    assert by_node[2] == pytest.approx((0.0, 0.0, -weight / 2))


def test_near_zero_length_still_conserves_a_tiny_resultant():
    """Zero length is rejected; a still-finite sliver must not be clipped to
    nothing, because that would drop a physically small but nonzero load."""
    model = line_model(end=(1e-9, 0.0, 0.0))
    plan = compile_loads(model, entries=[_global_distributed(1, "y", -3, -3)])
    assert resultant(model, plan)[0][1] == pytest.approx(-3e-9, rel=1e-9, abs=1e-18)


def test_zero_length_is_rejected_before_integration():
    model = line_model()
    model.nodes[2] = replace(model.nodes[2], x=0.0)
    with pytest.raises(LoadCompileError, match="invalid_length"):
        compile_loads(model, entries=[_global_distributed(1, "y", -3, -3)])


def test_multiple_distributed_loads_on_one_truss_accumulate():
    model = line_model()
    model.element_loads = [
        UniformElementLoad(1, wy=-2),
        UniformElementLoad(1, wy=-5, xL1=0.2, xL2=0.6),
    ]
    plan = compile_loads(model)
    assert len(plan.nodal_loads) == 4
    force, moment = resultant(model, plan)
    assert force[1] == pytest.approx(-20.0 + -20.0)
    # Full uniform -2 on L=10: Mz = -20*5 = -100.
    # Partial uniform -5 on [2, 6]: total -20, centroid at 4, Mz = -80.
    assert moment[2] == pytest.approx(-180.0)


def test_shared_node_contributions_from_two_trusses_add_when_summed():
    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodes={
            1: Node(1, 0, 0, 0),
            2: Node(2, 10, 0, 0),
            3: Node(3, 10, 6, 0),
        },
        elements={
            1: Element(1, 1, 2, "truss", {"behavior": "truss", "A": 0.2, "density": 25.0}),
            2: Element(2, 2, 3, "truss", {"behavior": "truss", "A": 0.2, "density": 25.0}),
        },
    )
    plan = compile_loads(
        model,
        entries=[
            _global_distributed(1, "y", -3, -3, entry_id=1),
            _global_distributed(2, "y", -3, -3, entry_id=2),
        ],
    )
    summed: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for load in plan.nodal_loads:
        for axis in range(3):
            summed[load.node_tag][axis] += load.force[axis]
    # Horizontal 10 m: 30 kN split 15/15. Vertical 6 m: 18 kN split 9/9 at
    # nodes 2 and 3. Shared node 2 therefore carries 15+9.
    assert summed[1][1] == pytest.approx(-15.0)
    assert summed[2][1] == pytest.approx(-24.0)
    assert summed[3][1] == pytest.approx(-9.0)
    force, moment = resultant(model, plan)
    assert force == pytest.approx((0.0, -48.0, 0.0), abs=1e-12)
    assert moment[2] == pytest.approx(-15.0 * 0 + -24.0 * 10 + -9.0 * 10, abs=1e-12)


def test_shell_quad_shared_nodes_accumulate_to_rectangular_tributary_areas():
    """The plan keeps one contribution per quad corner (adapters sum).

    On a 2x1 rectangular mesh the shared-edge nodes must receive 2*(A/4)
    once grouped, corners 1*(A/4), matching tributary area not a unique
    count of CompiledNodalLoad records.
    """
    model = wall_model(nx=2, ny=1)
    plan = compile_loads(model, self_weight=SelfWeightEntry(), gravity_acceleration=9.81)
    weight = 2.5 * 0.2 * 8.0 * 9.81
    quad_count = 2
    assert len(plan.nodal_loads) == quad_count * 4
    summed: dict[int, float] = defaultdict(float)
    for load in plan.nodal_loads:
        summed[load.node_tag] += load.force[2]
    assert sum(summed.values()) == pytest.approx(-weight)
    magnitudes = sorted((-value for value in summed.values()), reverse=True)
    corner = weight / (quad_count * 4)
    # Two shared-edge nodes get 2*corner; four unique corners get corner.
    assert magnitudes[0] == pytest.approx(2 * corner)
    assert magnitudes[1] == pytest.approx(2 * corner)
    assert magnitudes[-1] == pytest.approx(corner)
    assert len(summed) == 6


def test_point_load_at_both_truss_ends_is_not_clipped_or_swapped():
    model = line_model()
    at_i = compile_loads(
        model,
        entries=[
            LoadEntry(1, "Q", "member_point", (1,), MemberPointLoadEntry(value=-5, position=0.0))
        ],
    )
    at_j = compile_loads(
        model,
        entries=[
            LoadEntry(2, "Q", "member_point", (1,), MemberPointLoadEntry(value=-5, position=1.0))
        ],
    )
    assert resultant(model, at_i) == ((0.0, -5.0, 0.0), (0.0, 0.0, 0.0))
    assert resultant(model, at_j) == ((0.0, -5.0, 0.0), (0.0, 0.0, -50.0))


def test_local_transverse_load_on_vertical_3d_truss_uses_auto_x_reference():
    """A vertical member's auto vecxz is global X, so local y is -global Y."""
    model = line_model(ndm=3, end=(0.0, 0.0, 10.0))
    model.element_loads = [UniformElementLoad(1, wy=2)]
    force, moment = resultant(model, compile_loads(model))
    assert force == pytest.approx((0.0, -20.0, 0.0), abs=1e-12)
    assert moment == pytest.approx((100.0, 0.0, 0.0), abs=1e-12)
