"""Quick3DSceneBridge's per-shape member cross-section rendering: real B(width)
x H(height) boxes instead of the old uniform sqrt(area) square, an H/I
section as three flat parts (web + two flanges), and - most importantly -
the member's own roll around its axis matching the exact same
local_y_z_axes/auto_reference_vector/local_axis_angle math the local-axis
preview gizmo already uses, so the rendered width/height (and an H-section's
flanges) land on the member's *real* structural y/z axes instead of an
arbitrary minimal-rotation roll.

Each member contributes one or more flat, fully self-contained parts to
``bridge.members`` (own position/rotation/width_b/width_h) - the same
flat-list-of-parts shape loadArrows/supportSymbols use in the QML, adopted
here after a nested Node-group-of-children delegate turned out not to keep
Repeater3D's rendered geometry reliably in sync with model changes (a copied
member intermittently rendered as a bare hairline instead of its real
cross-section).

These are pure Quick3DSceneBridge/dict-level tests - no QQuickWidget/QML
needed, since the geometry is fully determined before it ever reaches QML.
"""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, Node, StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge


def _bridge() -> Quick3DSceneBridge:
    QApplication.instance() or QApplication([])
    return Quick3DSceneBridge()


def _rotate(scalar: float, qx: float, qy: float, qz: float, v: tuple[float, float, float]):
    """Rotate ``v`` by the quaternion (scalar, qx, qy, qz) - the same
    operation Qt.quaternion(...) applies to a Model's local axes in QML."""
    w, x, y, z = scalar, qx, qy, qz
    vx, vy, vz = v
    cross1 = (y * vz - z * vy, z * vx - x * vz, x * vy - y * vx)
    cross2 = (
        y * cross1[2] - z * cross1[1],
        z * cross1[0] - x * cross1[2],
        x * cross1[1] - y * cross1[0],
    )
    return (
        vx + 2 * w * cross1[0] + 2 * cross2[0],
        vy + 2 * w * cross1[1] + 2 * cross2[1],
        vz + 2 * w * cross1[2] + 2 * cross2[2],
    )


def _member_parts(
    properties: dict[str, float | str], *, start=(0.0, 0.0, 0.0), end=(4.0, 0.0, 0.0)
) -> list[dict[str, float | int | str]]:
    """Every rendered part for a single 3D beam-column member, rendered
    through a full set_model() so extent-based clamping matches real usage."""
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, *start), 2: Node(2, *end)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=properties)},
    )
    bridge = _bridge()
    bridge.set_model(model)
    return bridge.members


def _member(properties: dict[str, float | str], *, start=(0.0, 0.0, 0.0), end=(4.0, 0.0, 0.0)):
    """The single rendered part for a member that never splits into more
    than one (anything but a "visible" H/I section)."""
    parts = _member_parts(properties, start=start, end=end)
    assert len(parts) == 1, "expected exactly one rendered part"
    return parts[0]


#: Deliberately small relative to every test member's span below (the
#: renderer caps a section's visual size at extent * 0.055 so one absurd
#: input can never swallow the whole scene - extent here is a lone 2-node
#: model's own span, as low as 3 in the inclined-member test, so these must
#: comfortably clear 3 * 0.055 = 0.165 to avoid the cap distorting the shape
#: this test is actually trying to check).
_RECT_PROPERTIES = {
    "section_shape": "Rectangle",
    "width": 0.06,
    "height": 0.12,
    "A": 0.0072,
}

#: tw/tf deliberately well above the 8%-of-envelope visibility floor (see
#: test_h_section_thin_web_and_flange_are_floored_to_stay_visible below), so
#: this fixture exercises the plain pass-through path, not the floor.
_H_PROPERTIES = {
    "section_shape": "H/I Section",
    "dim_H": 0.12,
    "dim_B": 0.06,
    "dim_tw": 0.02,
    "dim_tf": 0.025,
    "A": 0.0018,
}


def test_rectangle_width_and_height_are_not_swapped() -> None:
    """B (width) always maps to width_b, H (height) to width_h - never
    swapped - regardless of which one is larger. A non-H/I shape is exactly
    one rendered part, using the plain #Cube primitive."""
    member = _member(_RECT_PROPERTIES)
    assert member["width_b"] == pytest.approx(0.06)
    assert member["width_h"] == pytest.approx(0.12)
    assert member["source"] == "#Cube"


def test_circle_and_pipe_use_the_diameter_for_both_axes_and_a_cylinder() -> None:
    circle = _member({"section_shape": "Circle", "dim_D": 0.1, "A": 0.00785})
    pipe = _member({"section_shape": "Pipe", "dim_D": 0.1, "dim_t": 0.006, "A": 0.00177})
    assert circle["width_b"] == pytest.approx(circle["width_h"]) == pytest.approx(0.1)
    assert pipe["width_b"] == pytest.approx(pipe["width_h"]) == pytest.approx(0.1)
    assert circle["source"] == "#Cylinder"
    assert pipe["source"] == "#Cylinder"


def test_h_section_renders_as_three_parts_reading_dim_keys() -> None:
    """An H/I section is exactly three flat parts - web, top flange, bottom
    flange - each its own independent entry in bridge.members, all sharing
    the member's tag/start/end/rotation but each with its own width_b x
    width_h and its own baked-in world position."""
    parts = _member_parts(_H_PROPERTIES)
    assert len(parts) == 3
    assert all(part["tag"] == 1 for part in parts)
    assert all(part["source"] == "#Cube" for part in parts)

    by_width_h = sorted(parts, key=lambda part: part["width_h"])
    flange_a, flange_b, web = by_width_h[0], by_width_h[1], by_width_h[2]
    # The web is the one part whose width_h is the full (near-)H extent;
    # the two flanges share the same (smaller) width_h = flange thickness.
    assert flange_a["width_h"] == pytest.approx(flange_b["width_h"])
    assert flange_a["width_h"] == pytest.approx(0.025)  # dim_tf
    assert flange_a["width_b"] == pytest.approx(0.06)  # dim_B, full flange width
    assert web["width_b"] == pytest.approx(0.02)  # dim_tw
    assert web["width_h"] == pytest.approx(0.12 - 2 * 0.025)  # dim_H - 2*dim_tf

    # The web sits on the member's own centreline; the flanges are offset
    # symmetrically off it along the member's true local Z (rotated into
    # view space) by (H - tf) / 2.
    mid = (2.0, 0.0, 0.0)  # midpoint of (0,0,0)-(4,0,0) in view space
    assert web["x"] == pytest.approx(mid[0])
    assert web["y"] == pytest.approx(mid[1])
    assert web["z"] == pytest.approx(mid[2])
    expected_offset = (0.12 - 0.025) / 2.0
    flange_offsets = sorted(
        math.sqrt(sum((flange[axis] - mid[i]) ** 2 for i, axis in enumerate("xyz")))
        for flange in (flange_a, flange_b)
    )
    assert flange_offsets[0] == pytest.approx(expected_offset, abs=1e-6)
    assert flange_offsets[1] == pytest.approx(expected_offset, abs=1e-6)
    # The two flanges must be on opposite sides of the web, not stacked.
    delta = tuple(flange_a[axis] - flange_b[axis] for axis in "xyz")
    assert math.sqrt(sum(c * c for c in delta)) == pytest.approx(2.0 * expected_offset, abs=1e-6)


def test_h_section_thin_web_and_flange_are_floored_to_stay_visible() -> None:
    """A real steel H-beam's web/flange (millimetres) would be an
    imperceptible hairline next to a member several metres long if rendered
    strictly to scale - both must be floored at a visible fraction (8%) of
    the section's own outer envelope, and the flange offset must be derived
    from that *same* floored value so the three parts still meet exactly
    (no gap, no overlap) instead of the web silently reverting to its
    unfloored, thinner true thickness."""
    thin = {
        "section_shape": "H/I Section",
        "dim_H": 0.12,
        "dim_B": 0.06,
        "dim_tw": 0.001,  # 1mm - genuinely tiny next to a 4m member
        "dim_tf": 0.0015,
        "A": 0.0006,
    }
    parts = _member_parts(thin)
    assert len(parts) == 3
    web = max(parts, key=lambda part: part["width_h"])
    flanges = [part for part in parts if part is not web]
    outer_h = web["width_h"] + 2.0 * flanges[0]["width_h"]  # unclamped at this extent: 0.12
    expected_floor = pytest.approx(max(outer_h, 0.06) * 0.08)
    assert flanges[0]["width_h"] == expected_floor
    assert flanges[1]["width_h"] == expected_floor
    assert web["width_b"] == expected_floor


def test_h_section_web_stays_inside_a_clamped_outer_height() -> None:
    """A section large enough to hit the visual-size clamp must scale tw/tf
    down by the same ratio as H/B, or the web/flange parts would stay sized
    for the real (unclamped) H and the flanges would land outside the
    clamped outer footprint - regression coverage for that exact bug."""
    huge = {
        "section_shape": "H/I Section",
        "dim_H": 4.0,
        "dim_B": 2.0,
        "dim_tw": 0.1,
        "dim_tf": 0.15,
        "A": 1.0,
    }
    parts = _member_parts(huge, start=(0.0, 0.0, 0.0), end=(4.0, 0.0, 0.0))
    web = max(parts, key=lambda part: part["width_h"])
    flanges = [part for part in parts if part is not web]
    outer_h = web["width_h"] + 2.0 * flanges[0]["width_h"]
    assert outer_h < 4.0  # actually clamped, or this test proves nothing
    mid = (2.0, 0.0, 0.0)
    offsets = [
        math.sqrt(sum((flange[axis] - mid[i]) ** 2 for i, axis in enumerate("xyz")))
        for flange in flanges
    ]
    assert all(offset + flanges[0]["width_h"] / 2.0 <= outer_h / 2.0 + 1e-9 for offset in offsets)


def test_box_channel_and_angle_use_overall_h_and_b_as_a_single_plain_box() -> None:
    """Box/Channel/Angle get their real outer H x B footprint as a single
    part (no web/flange split - those three fall back to a solid box)."""
    for shape in ("Box", "Channel", "Angle"):
        member = _member(
            {"section_shape": shape, "dim_H": 0.1, "dim_B": 0.05, "dim_t": 0.004, "A": 0.002}
        )
        assert member["width_b"] == pytest.approx(0.05), shape
        assert member["width_h"] == pytest.approx(0.1), shape


def test_user_defined_section_without_dimensions_falls_back_to_the_old_square() -> None:
    """A custom/legacy section with only A (no shape, no width/height, no
    dim_* keys) keeps the old uniform sqrt(area) square - unchanged."""
    member = _member({"A": 0.0025})
    assert member["width_b"] == pytest.approx(member["width_h"])
    assert member["width_b"] == pytest.approx(0.05, rel=0.05)  # sqrt(0.0025)


def test_truss_member_ignores_section_shape_and_keeps_the_old_square() -> None:
    """A truss has no bending orientation at all (matches
    _build_local_axis_preview's own truss exclusion) - even if it somehow
    carries an H/I section_shape, it must render as one plain square part,
    never the three-part split."""
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "truss", properties=_H_PROPERTIES)},
    )
    bridge = _bridge()
    bridge.set_model(model)
    assert len(bridge.members) == 1
    member = bridge.members[0]
    assert member["width_b"] == pytest.approx(member["width_h"])


def test_horizontal_member_at_zero_angle_orients_height_along_the_vertical_screen_axis() -> None:
    """A horizontal member (angle=0) uses the default vertical reference, so
    its H (height) dimension - carried by the box's local Z - lands on the
    view's vertical (Y) axis, and its B (width) - local X - lands on the
    view's horizontal depth (Z) axis. Exactly one component may land near
    +/-1 for each; the sign is not meaningful (a box is symmetric about its
    own centre either way) so only the axis identity is checked."""
    member = _member(_RECT_PROPERTIES)  # Element.local_axis_angle defaults to 0.0
    height_dir = _rotate(member["qscalar"], member["qx"], member["qy"], member["qz"], (0.0, 0.0, 1.0))
    width_dir = _rotate(member["qscalar"], member["qx"], member["qy"], member["qz"], (1.0, 0.0, 0.0))
    assert abs(height_dir[1]) == pytest.approx(1.0, abs=1e-6)
    assert abs(height_dir[0]) == pytest.approx(0.0, abs=1e-6)
    assert abs(width_dir[1]) == pytest.approx(0.0, abs=1e-6)


def test_rotating_local_axis_angle_by_90_degrees_swaps_which_dimension_is_vertical() -> None:
    """The single most important behaviour this feature exists for: turning
    local_axis_angle from 0 to 90 must swap B and H between the vertical and
    horizontal screen axes - proof the box's roll actually reflects
    local_axis_angle instead of an arbitrary minimal-rotation roll."""
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={
            1: Element(
                1, 1, 2, "elasticBeamColumn", properties=_RECT_PROPERTIES, local_axis_angle=90.0
            )
        },
    )
    bridge = _bridge()
    bridge.set_model(model)
    member = bridge.members[0]
    height_dir = _rotate(member["qscalar"], member["qx"], member["qy"], member["qz"], (0.0, 0.0, 1.0))
    width_dir = _rotate(member["qscalar"], member["qx"], member["qy"], member["qz"], (1.0, 0.0, 0.0))
    # Now B (width) is vertical, H (height) is horizontal - the reverse of angle=0.
    assert abs(width_dir[1]) == pytest.approx(1.0, abs=1e-6)
    assert abs(height_dir[1]) == pytest.approx(0.0, abs=1e-6)


def test_vertical_member_keeps_width_and_height_in_the_horizontal_plane() -> None:
    """A vertical member's cross-section is horizontal end to end - both B
    and H must land in the horizontal (X/Z) plane, never pick up a vertical
    (Y) component, regardless of the auto-reference fallback used for a
    member parallel to the vertical axis."""
    # ndm=3 uses structural Z as vertical (see _vertical_axis in
    # modeling_interface_page.py) - a member along Z is the vertical case
    # auto_reference_vector's own fallback (global X instead of global Z) exists for.
    member = _member(_RECT_PROPERTIES, start=(0.0, 0.0, 0.0), end=(0.0, 0.0, 4.0))
    height_dir = _rotate(member["qscalar"], member["qx"], member["qy"], member["qz"], (0.0, 0.0, 1.0))
    width_dir = _rotate(member["qscalar"], member["qx"], member["qy"], member["qz"], (1.0, 0.0, 0.0))
    assert height_dir[1] == pytest.approx(0.0, abs=1e-6)
    assert width_dir[1] == pytest.approx(0.0, abs=1e-6)


def test_inclined_member_orientation_stays_orthonormal_and_preserves_the_axis() -> None:
    """A diagonal member has no 'obvious' vertical/horizontal answer to check
    against - what must hold for any member is that the rendered frame is a
    genuine right-angled, unit-length triad, and that the box's local Y
    really is the member's own axial direction (not some other member's)."""
    length = math.sqrt(3.0 * 3.0 + 3.0 * 3.0 + 3.0 * 3.0)
    member = _member(_RECT_PROPERTIES, start=(0.0, 0.0, 0.0), end=(3.0, 3.0, 3.0))
    q = (member["qscalar"], member["qx"], member["qy"], member["qz"])
    local_x = _rotate(*q, (1.0, 0.0, 0.0))
    local_y = _rotate(*q, (0.0, 1.0, 0.0))
    local_z = _rotate(*q, (0.0, 0.0, 1.0))
    for axis in (local_x, local_y, local_z):
        assert math.sqrt(sum(c * c for c in axis)) == pytest.approx(1.0, abs=1e-6)
    assert sum(a * b for a, b in zip(local_x, local_y)) == pytest.approx(0.0, abs=1e-6)
    assert sum(a * b for a, b in zip(local_y, local_z)) == pytest.approx(0.0, abs=1e-6)
    assert sum(a * b for a, b in zip(local_x, local_z)) == pytest.approx(0.0, abs=1e-6)
    # The 3D view maps structural (x, y, z) -> view (x, z, -y); a member
    # from (0,0,0) to (3,3,3) therefore points along view (3, 3, -3)/length.
    expected_direction = (3.0 / length, 3.0 / length, -3.0 / length)
    assert local_y == pytest.approx(expected_direction, abs=1e-6)


def test_selection_highlight_scales_every_part_of_a_member_together() -> None:
    """The red selection highlight scales width_b/width_h; for an H-section
    that must apply to *every* one of its three parts (web + both flanges),
    all sharing the member's tag, not just whichever part happens to be
    first in the list."""
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_H_PROPERTIES)},
    )
    bridge = _bridge()
    bridge.set_model(model)
    plain_parts = list(bridge.members)
    assert len(plain_parts) == 3

    bridge.set_selection(set(), {1})
    selected_parts = list(bridge.members)
    assert len(selected_parts) == 3

    for plain, selected in zip(plain_parts, selected_parts):
        assert selected["color"] != plain["color"]
        scale_b = selected["width_b"] / plain["width_b"] if plain["width_b"] else 1.0
        scale_h = selected["width_h"] / plain["width_h"] if plain["width_h"] else 1.0
        assert scale_b > 1.0 or scale_h > 1.0
