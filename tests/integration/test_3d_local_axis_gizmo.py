"""The 3D viewport's local-axis gizmo: a per-member preview of what
``Element.local_axis_angle`` does, built by ``Quick3DSceneBridge``. Off by
default (an authoring aid, not something the imported-model/results viewers
that share this same bridge class should ever show unasked).
"""

import pytest

from openframe.core.domain import Element, Node, StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)


def _rotate_unit_y(qscalar: float, qx: float, qy: float, qz: float) -> tuple[float, float, float]:
    """Rotate the +Y axis by (qscalar, qx, qy, qz) - mirrors what Qt.quaternion(...)
    does to a Model's local Y axis in the QML scene (same helper as
    test_3d_model_load_display.py)."""
    w, x, y, z = qscalar, qx, qy, qz
    return (
        2 * (x * y - w * z),
        1 - 2 * (x * x + z * z),
        2 * (w * x + y * z),
    )


def _view_to_model(view: tuple[float, float, float]) -> tuple[float, float, float]:
    """Inverse of Quick3DSceneBridge._view_coordinates: view = (x, z, -y)."""
    return (view[0], -view[2], view[1])


def _horizontal_member_model(local_axis_angle: float = 0.0) -> StructuralModel:
    return StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame", local_axis_angle=local_axis_angle)},
    )


def test_local_axis_gizmos_are_empty_until_visibility_is_turned_on() -> None:
    bridge = Quick3DSceneBridge()
    bridge.set_model(_horizontal_member_model())
    assert bridge.localAxisGizmos == []

    bridge.set_local_axes_visible(True)
    assert len(bridge.localAxisGizmos) == 2  # one local-y, one local-z entry

    bridge.set_local_axes_visible(False)
    assert bridge.localAxisGizmos == []


def test_local_axis_gizmos_skip_truss_elements_and_2d_models() -> None:
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0), 3: Node(3, 0.0, 4.0, 0.0)},
        elements={
            1: Element(1, 1, 2, "frame"),
            2: Element(2, 1, 3, "truss"),
        },
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    bridge.set_local_axes_visible(True)
    assert len(bridge.localAxisGizmos) == 2  # only the frame member's y/z, not the truss's
    assert {part["tag"] for part in bridge.localAxisGizmos} == {1}

    bridge_2d = Quick3DSceneBridge()
    bridge_2d.set_model(
        StructuralModel(
            ndm=2,
            nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
            elements={1: Element(1, 1, 2, "frame")},
        )
    )
    bridge_2d.set_local_axes_visible(True)
    assert bridge_2d.localAxisGizmos == []


def test_local_axis_gizmo_directions_rotate_with_local_axis_angle() -> None:
    """A 90-degree local_axis_angle must rotate the rendered y/z gizmo lines
    by the same 90 degrees about the member's own axis - the whole point of
    the gizmo being a faithful preview of what the solver will actually do
    (both are built from the same core.domain.geometric_transform functions)."""
    bridge_unrotated = Quick3DSceneBridge()
    bridge_unrotated.set_model(_horizontal_member_model(local_axis_angle=0.0))
    bridge_unrotated.set_local_axes_visible(True)

    bridge_rotated = Quick3DSceneBridge()
    bridge_rotated.set_model(_horizontal_member_model(local_axis_angle=90.0))
    bridge_rotated.set_local_axes_visible(True)

    def directions(bridge: Quick3DSceneBridge) -> dict[str, tuple[float, float, float]]:
        result = {}
        for part in bridge.localAxisGizmos:
            direction_view = _rotate_unit_y(part["qscalar"], part["qx"], part["qy"], part["qz"])
            result[part["color"]] = _view_to_model(direction_view)
        return result

    unrotated = directions(bridge_unrotated)
    rotated = directions(bridge_rotated)

    # Member is horizontal along +X, so the default (unrotated) local y axis
    # is global Y and local z is global Z - matching auto_reference_vector's
    # own rule (global Z reference for a non-vertical member).
    assert unrotated["#22c55e"] == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
    assert unrotated["#ec4899"] == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)

    # 90 degrees about the member's own (X) axis swaps y and z (up to sign).
    assert rotated["#22c55e"] == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)
    assert rotated["#ec4899"] == pytest.approx((0.0, -1.0, 0.0), abs=1e-6)
