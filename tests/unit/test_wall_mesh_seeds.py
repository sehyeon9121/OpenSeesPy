"""Story / USER-node seeds on a rectangular wall mesh."""

from __future__ import annotations

import pytest

from openframe.core.domain import (
    Element,
    Node,
    NodeOrigin,
    Story,
    StructuralModel,
    WallPanel,
)
from openframe.core.domain.story import STORY_Z_TOLERANCE
from openframe.features.model.surfaces import assemble_wall_meshes, wall_quad_payloads


def _wall_panel(nx: int, ny: int, height: float = 3.0, width: float = 2.0) -> WallPanel:
    return WallPanel(
        tag=1,
        node_1=1,
        node_2=2,
        node_3=3,
        node_4=4,
        thickness=0.2,
        nx=nx,
        ny=ny,
        elastic_modulus=30_000_000.0,
        poisson_ratio=0.2,
    )


def _base_nodes(height: float = 3.0, width: float = 2.0) -> dict[int, Node]:
    return {
        1: Node(1, 0.0, 0.0, 0.0, 6),
        2: Node(2, width, 0.0, 0.0, 6),
        3: Node(3, width, 0.0, height, 6),
        4: Node(4, 0.0, 0.0, height, 6),
    }


def _model(
    nx: int = 1,
    ny: int = 1,
    *,
    extra_nodes: dict[int, Node] | None = None,
    elements: dict[int, Element] | None = None,
    stories: tuple[Story, ...] = (),
    height: float = 3.0,
    width: float = 2.0,
) -> StructuralModel:
    nodes = _base_nodes(height=height, width=width)
    if extra_nodes:
        nodes.update(extra_nodes)
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes=nodes,
        elements=dict(elements or {}),
        walls={1: _wall_panel(nx, ny, height=height, width=width)},
        stories=stories,
    )


def _wall_node_zs(model: StructuralModel) -> list[float]:
    return sorted({round(node.z, 9) for node in model.nodes.values() if node.x <= 2.0 + 1e-9})


def _quad_tags_using(model: StructuralModel, node_tag: int) -> set[int]:
    return {
        quad.tag
        for quad in model.shell_quads.values()
        if node_tag in quad.node_tags()
    }


def _coincident_pairs(model: StructuralModel, tol: float = STORY_Z_TOLERANCE) -> list[tuple[int, int]]:
    nodes = list(model.nodes.values())
    pairs: list[tuple[int, int]] = []
    for index, first in enumerate(nodes):
        for second in nodes[index + 1 :]:
            dx = first.x - second.x
            dy = first.y - second.y
            dz = first.z - second.z
            if dx * dx + dy * dy + dz * dz <= tol * tol:
                pairs.append((first.tag, second.tag))
    return pairs


def test_story_levels_inside_the_wall_become_horizontal_mesh_rows() -> None:
    model = assemble_wall_meshes(
        _model(
            nx=1,
            ny=1,
            height=6.0,
            stories=(
                Story("s0", "1층", 0.0),
                Story("s1", "2층", 3.0),
                Story("s2", "3층", 6.0),
            ),
        )
    )

    assert _wall_node_zs(model) == [0.0, 3.0, 6.0]
    assert len(model.shell_quads) == 2
    mid_row = [
        node
        for node in model.nodes.values()
        if abs(node.z - 3.0) <= STORY_Z_TOLERANCE
    ]
    assert len(mid_row) == 2


def test_story_outside_the_wall_height_does_not_add_a_row() -> None:
    model = assemble_wall_meshes(
        _model(
            nx=1,
            ny=1,
            height=3.0,
            stories=(Story("roof", "지붕", 10.0), Story("basement", "지하", -3.0)),
        )
    )

    assert len(model.shell_quads) == 1
    assert _wall_node_zs(model) == [0.0, 3.0]


def test_story_that_coincides_with_uniform_subdivision_does_not_duplicate_a_row() -> None:
    model = assemble_wall_meshes(
        _model(
            nx=1,
            ny=2,
            height=3.0,
            stories=(Story("mid", "중간", 1.5),),
        )
    )

    assert len(model.shell_quads) == 2
    assert _wall_node_zs(model) == [0.0, 1.5, 3.0]


def test_top_edge_user_node_is_reused_instead_of_generating_wall_mesh() -> None:
    model = assemble_wall_meshes(
        _model(nx=1, ny=1, extra_nodes={5: Node(5, 1.0, 0.0, 3.0, 6)})
    )

    assert model.nodes[5].origin is NodeOrigin.USER
    assert _quad_tags_using(model, 5)
    generated_at_mid = [
        node
        for node in model.nodes.values()
        if node.is_wall_mesh
        and abs(node.x - 1.0) <= STORY_Z_TOLERANCE
        and abs(node.z - 3.0) <= STORY_Z_TOLERANCE
    ]
    assert generated_at_mid == []
    assert _coincident_pairs(model) == []
    assert len(model.shell_quads) == 2


def test_corner_authored_nodes_stay_user_and_are_not_regenerated() -> None:
    model = assemble_wall_meshes(_model(nx=2, ny=2))

    for tag in (1, 2, 3, 4):
        assert model.nodes[tag].origin is NodeOrigin.USER
        assert _quad_tags_using(model, tag)
    assert all(not model.nodes[tag].is_wall_mesh for tag in (1, 2, 3, 4))


def test_story_beam_and_uniform_stations_merge_within_tolerance() -> None:
    model = assemble_wall_meshes(
        _model(
            nx=2,
            ny=2,
            extra_nodes={5: Node(5, 1.0, 0.0, 1.5 + STORY_Z_TOLERANCE / 2.0, 6)},
            stories=(Story("mid", "중간", 1.5),),
        )
    )

    clustered_z: list[float] = []
    for z in sorted(node.z for node in model.nodes.values()):
        if not clustered_z or z - clustered_z[-1] > STORY_Z_TOLERANCE:
            clustered_z.append(z)
    assert clustered_z == pytest.approx([0.0, 1.5, 3.0])
    assert model.nodes[5].origin is NodeOrigin.USER
    assert _quad_tags_using(model, 5)
    assert _coincident_pairs(model) == []
    # nx=2, ny=2 already has the mid column and mid row; seeds must not
    # inflate that 2×2 tensor product into extra sliver quads.
    assert len(model.shell_quads) == 4


def test_node_outside_tolerance_is_not_connected() -> None:
    model = assemble_wall_meshes(
        _model(nx=1, ny=1, extra_nodes={5: Node(5, 1.0, 0.01, 3.0, 6)})
    )

    assert len(model.shell_quads) == 1
    assert _quad_tags_using(model, 5) == set()
    assert model.nodes[5].origin is NodeOrigin.USER


def test_remesh_keeps_user_beam_tags_and_element_connectivity() -> None:
    beam = Element(20, 5, 6, "elasticBeamColumn")
    model = _model(
        nx=1,
        ny=1,
        extra_nodes={
            5: Node(5, 1.0, 0.0, 3.0, 6),
            6: Node(6, 4.0, 0.0, 3.0, 6),
        },
        elements={20: beam},
    )
    assemble_wall_meshes(model)
    assert _quad_tags_using(model, 5)
    connectivity_before = [(element.tag, element.node_i, element.node_j) for element in model.elements.values()]

    model.walls[1] = _wall_panel(4, 2)
    assemble_wall_meshes(model)

    assert model.nodes[5].origin is NodeOrigin.USER
    assert model.nodes[6].origin is NodeOrigin.USER
    assert _quad_tags_using(model, 5)
    assert [(element.tag, element.node_i, element.node_j) for element in model.elements.values()] == (
        connectivity_before
    )
    assert model.elements[20].node_i == 5
    assert model.elements[20].node_j == 6


def test_column_endpoint_on_a_wall_edge_is_reused() -> None:
    model = assemble_wall_meshes(
        _model(
            nx=1,
            ny=1,
            extra_nodes={10: Node(10, 0.0, 0.0, 1.5, 6)},
            elements={
                11: Element(11, 1, 10, "elasticBeamColumn"),
                12: Element(12, 10, 4, "elasticBeamColumn"),
            },
        )
    )

    assert model.nodes[10].origin is NodeOrigin.USER
    assert _quad_tags_using(model, 10)
    assert model.elements[11].node_i == 1
    assert model.elements[11].node_j == 10
    assert model.elements[12].node_j == 4


def test_seeded_mesh_payload_has_no_duplicate_corners_or_cracked_faces() -> None:
    model = assemble_wall_meshes(
        _model(nx=1, ny=1, extra_nodes={5: Node(5, 1.0, 0.0, 3.0, 6)})
    )
    payloads = wall_quad_payloads(model)
    quads = sorted(model.shell_quads.values(), key=lambda item: item.tag)

    assert len(payloads) == 2
    shared = set(quads[0].node_tags()) & set(quads[1].node_tags())
    # Two quads that share a vertical grid line must share exactly two
    # node tags. A generated duplicate at the beam node would make the
    # faces miss each other and show up as a crack.
    assert len(shared) == 2
    assert 5 in shared
    corner_coords = [corner for payload in payloads for corner in payload.corners]
    unique_xyz = {(round(x, 9), round(y, 9), round(z, 9)) for x, y, z in corner_coords}
    # 3×2 grid → 6 unique corners, 8 payload corners (shared edge counted twice).
    assert len(unique_xyz) == 6
    assert len(corner_coords) == 8
    assert _coincident_pairs(model) == []
