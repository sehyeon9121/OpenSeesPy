from pathlib import Path

import pytest

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    Node,
    StructuralModel,
    SupportKind,
)
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "cantilever_frame_3d.py"


def test_imported_3d_fixed_support_is_rendered_as_an_anchored_socket() -> None:
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    assert bridge.supportSymbols
    assert {part["tag"] for part in bridge.supportSymbols} == {1}
    assert {part["kind"] for part in bridge.supportSymbols} == {SupportKind.FIXED.value}
    assert {part["role"] for part in bridge.supportSymbols} == {
        "fixed_socket",
        "fixed_base_plate",
        "fixed_anchor",
    }
    assert {part["shape"] for part in bridge.supportSymbols} == {"#Cylinder", "#Cube"}
    assert {part["color"] for part in bridge.supportSymbols} == {"#00856a", "#d7f7f0"}
    assert bridge.supportSymbols[0]["y"] < bridge.nodes[0]["y"]
    support_bottom = min(
        part["y"] - part["scale_y"] / 2 for part in bridge.supportSymbols
    )
    ground_top = bridge.ground_y + max(bridge.extent * 0.012, 0.01) / 2
    assert support_bottom >= ground_top

    bridge.set_supports_visible(False)
    assert bridge.supportsVisible is False
    # Visibility is a QML-side switch; keeping the stable part list avoids a
    # costly topology rebuild when supports are shown again.
    assert bridge.supportSymbols
    bridge.set_supports_visible(True)
    assert bridge.supportsVisible is True
    assert bridge.supportSymbols


def test_support_is_separated_below_section_aware_node_sphere() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 0.0, 0.0, 3.0, 6),
        },
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties={
                    "behavior": "general_beam",
                    "section_shape": "Rectangle",
                    "width": 0.4,
                    "height": 0.6,
                },
            )
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    node = next(item for item in bridge.nodes if item["tag"] == 1)
    socket = next(
        item for item in bridge.supportSymbols if item["role"] == "fixed_socket"
    )
    socket_top = float(socket["y"]) + float(socket["scale_y"]) / 2.0
    node_bottom = float(node["y"]) - float(node["radius"])

    assert float(node["radius"]) > bridge._node_radius
    gap = node_bottom - socket_top
    assert gap == pytest.approx(float(node["radius"]) * 0.30)


def test_fixed_pin_and_custom_restraints_use_distinct_mechanical_glyphs() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 4.0, 0.0, 0.0, 6),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(2, (True, True, True, False, False, False)),
            BoundaryCondition(3, (True, False, False, False, False, False)),
        ],
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    by_tag: dict[int, list[dict]] = {}
    for part in bridge.supportSymbols:
        by_tag.setdefault(int(part["tag"]), []).append(part)

    assert {part["role"] for part in by_tag[1]} == {
        "fixed_socket",
        "fixed_base_plate",
        "fixed_anchor",
    }
    assert {part["role"] for part in by_tag[2]} == {
        "pin_joint",
        "pin_cone",
        "ground_plate",
    }
    assert {part["role"] for part in by_tag[3]} == {
        "custom_joint",
        "constraint_ux",
        "constraint_ux_cap",
    }
    assert {part["color"] for part in by_tag[1]} == {"#00856a", "#d7f7f0"}
    assert {part["color"] for part in by_tag[2]} == {"#00a6a6"}
    assert {part["color"] for part in by_tag[3]} == {"#f59e0b"}
    nodes_by_tag = {int(node["tag"]): node for node in bridge.nodes}
    for tag, role in ((2, "pin_joint"), (3, "custom_joint")):
        joint = next(part for part in by_tag[tag] if part["role"] == role)
        joint_top = float(joint["y"]) + float(joint["scale_y"]) / 2.0
        node = nodes_by_tag[tag]
        expected_top = float(node["y"]) - float(node["radius"]) * 1.30
        assert joint_top == pytest.approx(expected_top)


def test_each_3d_roller_aligns_its_cylinders_with_the_free_axis() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 4.0, 0.0, 0.0, 6),
        },
        boundaries=[
            BoundaryCondition(1, (False, True, True, False, False, False)),
            BoundaryCondition(2, (True, False, True, False, False, False)),
            BoundaryCondition(3, (True, True, False, False, False, False)),
        ],
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    by_tag: dict[int, list[dict]] = {}
    for part in bridge.supportSymbols:
        by_tag.setdefault(int(part["tag"]), []).append(part)

    expected = {
        1: (SupportKind.ROLLER_X, "roller_x_cylinder"),
        2: (SupportKind.ROLLER_Y, "roller_y_cylinder"),
        3: (SupportKind.ROLLER_Z, "roller_z_cylinder"),
    }
    for tag, (kind, cylinder_role) in expected.items():
        support_parts = by_tag[tag]
        assert {part["kind"] for part in support_parts} == {kind.value}
        assert {part["role"] for part in support_parts} == {
            "roller_joint",
            "roller_saddle",
            cylinder_role,
            "roller_base_plate",
        }
        assert sum(part["role"] == cylinder_role for part in support_parts) == 2
        assert {part["color"] for part in support_parts} == {"#6366f1"}
        joint = next(part for part in support_parts if part["role"] == "roller_joint")
        node = next(item for item in bridge.nodes if int(item["tag"]) == tag)
        joint_top = float(joint["y"]) + float(joint["scale_y"]) / 2.0
        expected_top = float(node["y"]) - float(node["radius"]) * 1.30
        assert joint_top == pytest.approx(expected_top)


def test_elastic_restraints_render_translation_coil_and_rotation_marker() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0, 6)},
        boundaries=[
            BoundaryCondition(
                1,
                (False,) * 6,
                spring_stiffnesses=(1000.0, None, None, 25.0, None, None),
            )
        ],
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    roles = [part["role"] for part in bridge.supportSymbols]
    assert "custom_joint" in roles
    assert {role for role in roles if role.startswith("spring_ux_")} == {
        f"spring_ux_{index}" for index in range(6)
    }
    assert roles.count("rotational_spring_rx") == 2
    spring_parts = [
        part
        for part in bridge.supportSymbols
        if part["role"].startswith(("spring_", "rotational_spring_"))
    ]
    assert {part["color"] for part in spring_parts} == {"#a855f7"}


def test_rotated_standard_supports_keep_their_shape_and_rotate_as_assemblies() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 4.0, 0.0, 0.0, 6),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6, angle=90.0, angle_axis="x"),
            BoundaryCondition(
                2,
                (True, True, True, False, False, False),
                angle=35.0,
                angle_axis="y",
            ),
            BoundaryCondition(
                3,
                (False, True, True, False, False, False),
                angle=25.0,
                angle_axis="z",
            ),
        ],
    )
    # The domain correctly treats inclined supports as CUSTOM for solver DOF
    # transformation; the renderer must still recover the underlying
    # mechanical family from the restraint tuple.
    assert {boundary.support_kind for boundary in model.boundaries} == {SupportKind.CUSTOM}

    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    by_tag: dict[int, list[dict]] = {}
    for part in bridge.supportSymbols:
        by_tag.setdefault(int(part["tag"]), []).append(part)

    assert {part["role"] for part in by_tag[1]} == {
        "fixed_socket",
        "fixed_base_plate",
        "fixed_anchor",
    }
    assert {part["kind"] for part in by_tag[1]} == {SupportKind.FIXED.value}
    assert {part["role"] for part in by_tag[2]} == {
        "pin_joint",
        "pin_cone",
        "ground_plate",
    }
    assert {part["kind"] for part in by_tag[2]} == {SupportKind.PINNED.value}
    assert "roller_x_cylinder" in {part["role"] for part in by_tag[3]}
    assert {part["kind"] for part in by_tag[3]} == {SupportKind.ROLLER_X.value}

    # A 90-degree X rotation sends the fixed socket's original downward
    # offset into depth. Its centre must move with the assembly instead of
    # staying below the node while only the cylinder itself rotates.
    socket = next(part for part in by_tag[1] if part["role"] == "fixed_socket")
    assert abs(float(socket["y"])) < 1.0e-9
    assert float(socket["z"]) < 0.0
