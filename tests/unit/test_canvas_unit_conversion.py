"""StaticsDrawingCanvas.convert_units (canvas_units.py) - rescaling every
stored value when the app's force/length unit system changes, so a number
keeps meaning the same physical quantity instead of just wearing a new
label. Each dimension (length/area/inertia/stress/force_per_length/
unit_weight/moment) is checked against a hand-computed expected value, not
just "changed somehow" - see canvas_units.py's own docstring for why each
field maps to the dimension it does.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    BoundaryCondition,
    FloorLoadEntry,
    FloorLoadTypeRow,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoad,
    NodalLoadEntry,
    SelfWeightEntry,
    UnitSystem,
    UniformElementLoad,
    unit_conversion_factors,
)
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas

_KN_M = UnitSystem(force="kN", length="m")
_N_MM = UnitSystem(force="N", length="mm")
_FACTORS = unit_conversion_factors(_KN_M, _N_MM)  # length x1000, force x1000


def _canvas(ndm: int = 3) -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.ndm = ndm
    return canvas


def test_node_coordinates_scale_by_length_factor() -> None:
    canvas = _canvas()
    tag = canvas._add_node_at((1.0, 2.0, 3.0))

    canvas.convert_units(_FACTORS)

    node = canvas.nodes[tag]
    assert (node.x, node.y, node.z) == pytest.approx((1000.0, 2000.0, 3000.0))


def test_element_properties_scale_by_their_own_dimension() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    canvas.elements[member].properties.update(
        {
            "E": 200_000.0,  # kN/m^2
            "G": 80_000.0,
            "A": 0.02,  # m^2
            "Iy": 0.0004,  # m^4
            "Iz": 0.0004,
            "J": 0.0005,
            "width": 0.3,  # m
            "height": 0.5,
            "density": 25.0,  # kN/m^3
            "dim_H": 0.5,
            "section_shape": "Rectangle",  # non-numeric - must pass through untouched
        }
    )

    canvas.convert_units(_FACTORS)

    properties = canvas.elements[member].properties
    assert properties["E"] == pytest.approx(200_000.0 * _FACTORS.stress)
    assert properties["G"] == pytest.approx(80_000.0 * _FACTORS.stress)
    assert properties["A"] == pytest.approx(0.02 * _FACTORS.area)
    assert properties["Iy"] == pytest.approx(0.0004 * _FACTORS.inertia)
    assert properties["Iz"] == pytest.approx(0.0004 * _FACTORS.inertia)
    assert properties["J"] == pytest.approx(0.0005 * _FACTORS.inertia)
    assert properties["width"] == pytest.approx(0.3 * _FACTORS.length)
    assert properties["height"] == pytest.approx(0.5 * _FACTORS.length)
    assert properties["density"] == pytest.approx(25.0 * _FACTORS.unit_weight)
    assert properties["dim_H"] == pytest.approx(0.5 * _FACTORS.length)
    assert properties["section_shape"] == "Rectangle"


def test_rigid_offsets_scale_by_length_factor() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    canvas.selected_elements = {member}
    canvas.apply_rigid_offset_lengths_to_selection(0.2, 0.3)

    canvas.convert_units(_FACTORS)

    element = canvas.elements[member]
    assert element.offset_i == pytest.approx((200.0, 0.0, 0.0))
    assert element.offset_j == pytest.approx((-300.0, 0.0, 0.0))


def test_spring_stiffness_scales_translational_vs_rotational_in_3d() -> None:
    canvas = _canvas(ndm=3)
    node = canvas._add_node_at((0.0, 0.0, 0.0))
    canvas.boundaries[node] = BoundaryCondition(
        node, (False,) * 6, spring_stiffnesses=(500.0, None, None, None, None, 50.0)
    )

    canvas.convert_units(_FACTORS)

    stiffnesses = canvas.boundaries[node].spring_stiffnesses
    assert stiffnesses[0] == pytest.approx(500.0 * _FACTORS.force_per_length)
    assert stiffnesses[1] is None
    assert stiffnesses[5] == pytest.approx(50.0 * _FACTORS.moment)


def test_spring_stiffness_uses_the_2d_translation_rotation_split() -> None:
    canvas = _canvas(ndm=2)
    node = canvas.add_node(0.0, 0.0)
    canvas.boundaries[node] = BoundaryCondition(
        node, (False, False, False), spring_stiffnesses=(100.0, 200.0, 30.0)
    )

    canvas.convert_units(_FACTORS)

    stiffnesses = canvas.boundaries[node].spring_stiffnesses
    assert stiffnesses[0] == pytest.approx(100.0 * _FACTORS.force_per_length)
    assert stiffnesses[1] == pytest.approx(200.0 * _FACTORS.force_per_length)
    assert stiffnesses[2] == pytest.approx(30.0 * _FACTORS.moment)  # Rz


def test_nodal_load_force_and_moment_split_in_3d() -> None:
    canvas = _canvas(ndm=3)
    node = canvas._add_node_at((0.0, 0.0, 0.0))
    canvas.nodal_loads[node] = NodalLoad(node, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0))

    canvas.convert_units(_FACTORS)

    values = canvas.nodal_loads[node].values
    assert values[:3] == pytest.approx(tuple(v * _FACTORS.force for v in (1.0, 2.0, 3.0)))
    assert values[3:] == pytest.approx(tuple(v * _FACTORS.moment for v in (4.0, 5.0, 6.0)))


def test_nodal_load_force_and_moment_split_in_2d() -> None:
    canvas = _canvas(ndm=2)
    node = canvas.add_node(0.0, 0.0)
    canvas.nodal_loads[node] = NodalLoad(node, (1.0, 2.0, 3.0))  # Fx, Fy, Mz

    canvas.convert_units(_FACTORS)

    values = canvas.nodal_loads[node].values
    assert values[0] == pytest.approx(1.0 * _FACTORS.force)
    assert values[1] == pytest.approx(2.0 * _FACTORS.force)
    assert values[2] == pytest.approx(3.0 * _FACTORS.moment)


def test_uniform_element_load_scales_by_force_per_length() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    canvas.element_loads[member] = UniformElementLoad(member, wx=1.0, wy=2.0, wz=3.0, wx_j=1.5, wy_j=2.5, wz_j=3.5)

    canvas.convert_units(_FACTORS)

    load = canvas.element_loads[member]
    assert (load.wx, load.wy, load.wz) == pytest.approx(
        tuple(v * _FACTORS.force_per_length for v in (1.0, 2.0, 3.0))
    )
    assert (load.wx_j, load.wy_j, load.wz_j) == pytest.approx(
        tuple(v * _FACTORS.force_per_length for v in (1.5, 2.5, 3.5))
    )


def test_nodal_load_entry_scales_force_and_moment() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL")
    node = canvas._add_node_at((0.0, 0.0, 0.0))
    entry_id = canvas.add_load_entry("DL", "nodal", (node,), NodalLoadEntry(fz=-10.0, mx=5.0))

    canvas.convert_units(_FACTORS)

    payload = canvas.load_entries[entry_id].payload
    assert payload.fz == pytest.approx(-10.0 * _FACTORS.force)
    assert payload.mx == pytest.approx(5.0 * _FACTORS.moment)


def test_member_moment_entry_scales_by_moment_not_force() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL")
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    entry_id = canvas.add_load_entry(
        "DL", "member_moment", (member,), MemberPointLoadEntry(value=8.0, position=0.5)
    )

    canvas.convert_units(_FACTORS)

    payload = canvas.load_entries[entry_id].payload
    assert payload.value == pytest.approx(8.0 * _FACTORS.moment)
    assert payload.position == pytest.approx(0.5)  # ratio - untouched


def test_member_point_entry_position_converts_only_when_position_unit_is_length() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL")
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    entry_id = canvas.add_load_entry(
        "DL",
        "member_point",
        (member,),
        MemberPointLoadEntry(value=10.0, position=1.5, position_unit="length"),
    )

    canvas.convert_units(_FACTORS)

    payload = canvas.load_entries[entry_id].payload
    assert payload.value == pytest.approx(10.0 * _FACTORS.force)
    assert payload.position == pytest.approx(1.5 * _FACTORS.length)


def test_member_distributed_entry_scales_force_per_length() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL")
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    entry_id = canvas.add_load_entry(
        "DL", "member_uniform", (member,), MemberDistributedLoadEntry(start_value=-2.0, end_value=-2.0)
    )

    canvas.convert_units(_FACTORS)

    payload = canvas.load_entries[entry_id].payload
    assert payload.start_value == pytest.approx(-2.0 * _FACTORS.force_per_length)
    assert payload.end_value == pytest.approx(-2.0 * _FACTORS.force_per_length)
    assert payload.start_position == pytest.approx(0.0)  # ratio - untouched
    assert payload.end_position == pytest.approx(1.0)


def test_floor_load_entry_scales_by_stress() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL")
    n1, n2, n3 = canvas._add_node_at((0, 0, 0)), canvas._add_node_at((4, 0, 0)), canvas._add_node_at((4, 4, 0))
    entry_id = canvas.add_load_entry("DL", "floor", (n1, n2, n3), FloorLoadEntry(magnitude=5.0))

    canvas.convert_units(_FACTORS)

    assert canvas.load_entries[entry_id].payload.magnitude == pytest.approx(5.0 * _FACTORS.stress)


def test_self_weight_entry_factors_are_left_unconverted() -> None:
    """factor_x/y/z are dimensionless direction cosines, not a force."""
    canvas = _canvas()
    canvas.add_load_case("DL")
    entry_id = canvas.add_load_entry(
        "DL", "self_weight", (), SelfWeightEntry(factor_x=0.0, factor_y=0.0, factor_z=-1.0)
    )

    canvas.convert_units(_FACTORS)

    payload = canvas.load_entries[entry_id].payload
    assert (payload.factor_x, payload.factor_y, payload.factor_z) == (0.0, 0.0, -1.0)


def test_floor_load_type_rows_scale_by_stress() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL")
    canvas.add_floor_load_type("바닥1", rows=(FloorLoadTypeRow("DL", 2.0),))

    canvas.convert_units(_FACTORS)

    assert canvas.floor_load_types["바닥1"].rows[0].magnitude == pytest.approx(2.0 * _FACTORS.stress)


def test_story_elevation_scales_by_length() -> None:
    canvas = _canvas()
    canvas.add_story("2층", 3.0, rigid_diaphragm=True)

    canvas.convert_units(_FACTORS)

    story = canvas.stories["2층"]
    assert story.elevation == pytest.approx(3.0 * _FACTORS.length)
    assert story.rigid_diaphragm is True  # untouched


def test_work_plane_offset_scales_and_active_plane_stays_linked() -> None:
    canvas = _canvas()
    plane = canvas.add_level(3.5, "2F")
    canvas.set_active_plane(plane)
    active_before = canvas.work_plane

    canvas.convert_units(_FACTORS)

    assert canvas.work_plane is not active_before  # replaced with a converted copy
    assert canvas.work_plane.offset == pytest.approx(3.5 * _FACTORS.length)
    assert canvas.work_plane in canvas.levels


def test_grid_spacing_scales_by_length() -> None:
    canvas = _canvas()
    canvas.grid = 0.5

    canvas.convert_units(_FACTORS)

    assert canvas.grid == pytest.approx(0.5 * _FACTORS.length)


def test_identity_conversion_is_a_complete_no_op() -> None:
    canvas = _canvas()
    node = canvas._add_node_at((1.0, 2.0, 3.0))
    undo_depth_before = len(canvas._undo_stack)

    canvas.convert_units(unit_conversion_factors(_KN_M, _KN_M))

    assert canvas.nodes[node].x == 1.0
    assert len(canvas._undo_stack) == undo_depth_before  # no history entry for a no-op


def test_conversion_is_a_single_undo_step() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    node = canvas._add_node_at((1.0, 0.0, 0.0))

    canvas.convert_units(_FACTORS)
    assert canvas.nodes[node].x == pytest.approx(1000.0)

    canvas.undo()

    assert canvas.nodes[node].x == pytest.approx(1.0)
    assert canvas.stories["1층"].elevation == pytest.approx(0.0)
