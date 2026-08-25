"""The 3D MODEL workspace must show loads before any analysis is run."""

from pathlib import Path

import pytest

from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

SOURCE = Path(__file__).parents[2] / "examples" / "frame_4bay_4story_3d.py"


def _rotate_unit_y(qscalar: float, qx: float, qy: float, qz: float) -> tuple[float, float, float]:
    """Rotate the +Y axis by (qscalar, qx, qy, qz) - mirrors what Qt.quaternion(...)
    does to a Model's local Y axis in the QML scene."""
    w, x, y, z = qscalar, qx, qy, qz
    # v' = q * (0,1,0) * q^-1, expanded for a unit quaternion and v=(0,1,0).
    return (
        2 * (x * y - w * z),
        1 - 2 * (x * x + z * z),
        2 * (w * x + y * z),
    )


def test_3d_nodal_and_vertical_beam_loads_are_imported_and_drawn() -> None:
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)

    assert len(model.nodal_loads) == 100
    assert len(model.element_loads) == 160
    assert (model.element_loads[0].wx, model.element_loads[0].wy) == pytest.approx(
        (0.0, 0.0)
    )
    assert model.element_loads[0].wz == pytest.approx(-20.0)

    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    arrows = bridge.loadArrows
    assert {part["kind"] for part in arrows} == {"nodal", "element"}
    # Nodal loads use one arrow; a uniform member load is deliberately compact:
    # one representative arrow plus a thin distribution line.
    assert len(arrows) == 2 * len(model.nodal_loads) + 3 * len(model.element_loads)

    first_loaded_element = model.element_loads[0].element_tag
    element_parts = [
        part
        for part in arrows
        if part["kind"] == "element" and part["tag"] == first_loaded_element
    ]
    assert sum(part["role"] == "shaft" for part in element_parts) == 1
    assert sum(part["role"] == "head" for part in element_parts) == 1
    assert sum(part["role"] == "distribution_line" for part in element_parts) == 1
    assert {part["color"] for part in element_parts} == {"#f59e0b"}
    shaft = next(part for part in element_parts if part["role"] == "shaft")
    head = next(part for part in element_parts if part["role"] == "head")
    # Structural global -Z maps to Quick3D -Y: the arrowhead is below its shaft.
    assert head["y"] < shaft["y"]

    # The cone's tip must stop above the rendered member surface, with a small
    # clearance, rather than ending on the analytical centreline and looking buried.
    element = model.elements[first_loaded_element]
    member_center_y = 0.5 * (
        model.nodes[element.node_i].z + model.nodes[element.node_j].z
    )
    direction = _rotate_unit_y(
        head["qscalar"], head["qx"], head["qy"], head["qz"]
    )
    arrow_tip_y = head["y"] + direction[1] * head["length"]
    rendered_member = next(
        member for member in bridge.members if member["tag"] == first_loaded_element
    )
    footprint = max(rendered_member["width_b"], rendered_member["width_h"])
    assert arrow_tip_y > member_center_y + footprint / 2

    bridge.set_loads_visible(False)
    assert bridge.loadArrows == []
    bridge.set_loads_visible(True)
    assert len(bridge.loadArrows) == len(arrows)

    bridge.set_load_filter("nodal")
    assert {part["kind"] for part in bridge.loadArrows} == {"nodal"}
    bridge.set_load_filter("element")
    assert {part["kind"] for part in bridge.loadArrows} == {"element"}
    bridge.set_load_filter("all")
    assert len(bridge.loadArrows) == len(arrows)


def test_arrow_shaft_and_head_meet_with_no_gap() -> None:
    """Regression test for the '#Cone' primitive being pivoted at its BASE (local Y
    spans [0, 100]) rather than centred like '#Cylinder' - a wrong "centred" position
    for the head left a visible gap after the shaft and made the tip overshoot into
    whatever it was pointing at. Every shaft's far end must exactly equal its head's
    base, for both nodal and distributed member loads.
    """
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    by_arrow: dict[tuple[int, str, int], dict[str, dict]] = {}
    for part in bridge.loadArrows:
        if part["role"] == "distribution_line":
            continue
        key = (part["tag"], part["kind"], part["arrow_index"])
        by_arrow.setdefault(key, {})[part["role"]] = part

    assert by_arrow
    for parts in by_arrow.values():
        shaft = parts["shaft"]
        head = parts["head"]
        direction = _rotate_unit_y(shaft["qscalar"], shaft["qx"], shaft["qy"], shaft["qz"])
        # Shaft ("#Cylinder") IS centred on its own position, so its far end is
        # position + direction * length / 2.
        shaft_end = tuple(
            shaft[axis] + direction[index] * shaft["length"] / 2
            for index, axis in enumerate("xyz")
        )
        head_base = (head["x"], head["y"], head["z"])
        for index in range(3):
            assert shaft_end[index] == pytest.approx(head_base[index], abs=1e-9)


def test_load_arrow_length_scales_with_magnitude_within_its_load_type() -> None:
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    nodal_shafts = [
        part
        for part in bridge.loadArrows
        if part["load_type"] == "nodal_force" and part["role"] == "shaft"
    ]
    lengths_by_magnitude = {
        float(part["magnitude"]): float(part["length"]) for part in nodal_shafts
    }
    ordered = sorted(lengths_by_magnitude.items())
    assert len(ordered) == 4
    assert [length for _, length in ordered] == sorted(
        length for _, length in ordered
    )
    assert ordered[0][1] < ordered[-1][1]
