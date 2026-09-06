"""Rectangular WallPanel → structured quad mesh."""

import pytest

from openframe.core.domain import Node, NodeOrigin, StructuralModel, WallPanel
from openframe.features.model.surfaces import (
    WallMeshError,
    assemble_wall_meshes,
    wall_quad_payloads,
)


def _rectangle_nodes() -> dict[int, Node]:
    return {
        1: Node(1, 0.0, 0.0, 0.0, 6),
        2: Node(2, 2.0, 0.0, 0.0, 6),
        3: Node(3, 2.0, 0.0, 3.0, 6),
        4: Node(4, 0.0, 0.0, 3.0, 6),
    }


def _wall_model(nx: int, ny: int) -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes=_rectangle_nodes(),
        walls={
            1: WallPanel(
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
        },
    )


def test_2x2_mesh_produces_exactly_four_quads() -> None:
    model = assemble_wall_meshes(_wall_model(2, 2))

    assert len(model.shell_quads) == 4
    authored = {1, 2, 3, 4}
    generated = {tag for tag, node in model.nodes.items() if node.is_wall_mesh}
    assert authored.isdisjoint(generated)
    assert len(generated) == 5  # 3×3 grid minus the four authored corners
    assert all(model.nodes[tag].origin is NodeOrigin.USER for tag in authored)


def test_generated_node_and_quad_ordering_is_deterministic() -> None:
    first = assemble_wall_meshes(_wall_model(2, 2))
    second = assemble_wall_meshes(_wall_model(2, 2))

    assert list(first.shell_quads) == list(second.shell_quads)
    first_quads = [
        (quad.tag, quad.node_tags(), quad.wall_tag) for quad in first.shell_quads.values()
    ]
    second_quads = [
        (quad.tag, quad.node_tags(), quad.wall_tag) for quad in second.shell_quads.values()
    ]
    assert first_quads == second_quads
    first_generated = [
        (tag, node.x, node.y, node.z)
        for tag, node in sorted(first.nodes.items())
        if node.is_wall_mesh
    ]
    second_generated = [
        (tag, node.x, node.y, node.z)
        for tag, node in sorted(second.nodes.items())
        if node.is_wall_mesh
    ]
    assert first_generated == second_generated


def test_remesh_drops_previous_generated_nodes_and_quads() -> None:
    model = assemble_wall_meshes(_wall_model(2, 2))
    first_generated = {tag for tag, node in model.nodes.items() if node.is_wall_mesh}
    model.walls[1] = WallPanel(
        tag=1,
        node_1=1,
        node_2=2,
        node_3=3,
        node_4=4,
        thickness=0.2,
        nx=4,
        ny=4,
        elastic_modulus=30_000_000.0,
        poisson_ratio=0.2,
    )
    assemble_wall_meshes(model)

    assert len(model.shell_quads) == 16
    leftover = first_generated - {tag for tag, node in model.nodes.items() if node.is_wall_mesh}
    # 2×2 generated tags that a 4×4 grid no longer needs must be gone, not
    # left as orphan user-looking nodes that a later remesh cannot classify.
    assert leftover <= first_generated
    assert all(node.origin is NodeOrigin.USER or node.is_wall_mesh for node in model.nodes.values())
    assert {1, 2, 3, 4}.issubset(model.nodes)


def test_degenerate_zero_area_wall_is_rejected() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 0.0, 0.0, 0.0, 6),
            3: Node(3, 0.0, 0.0, 3.0, 6),
            4: Node(4, 0.0, 0.0, 3.0, 6),
        },
        walls={
            1: WallPanel(
                tag=1,
                node_1=1,
                node_2=2,
                node_3=3,
                node_4=4,
                thickness=0.2,
                nx=1,
                ny=1,
                elastic_modulus=1.0,
                poisson_ratio=0.2,
            )
        },
    )
    with pytest.raises(WallMeshError, match="퇴화"):
        assemble_wall_meshes(model)


def test_non_planar_wall_is_rejected() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 2.0, 1.0, 3.0, 6),
            4: Node(4, 0.0, 0.0, 3.0, 6),
        },
        walls={
            1: WallPanel(
                tag=1,
                node_1=1,
                node_2=2,
                node_3=3,
                node_4=4,
                thickness=0.2,
                nx=1,
                ny=1,
                elastic_modulus=1.0,
                poisson_ratio=0.2,
            )
        },
    )
    with pytest.raises(WallMeshError, match="직사각형"):
        assemble_wall_meshes(model)


def test_non_orthogonal_parallelogram_is_rejected() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 3.0, 0.0, 3.0, 6),
            4: Node(4, 1.0, 0.0, 3.0, 6),
        },
        walls={
            1: WallPanel(
                tag=1,
                node_1=1,
                node_2=2,
                node_3=3,
                node_4=4,
                thickness=0.2,
                nx=1,
                ny=1,
                elastic_modulus=1.0,
                poisson_ratio=0.2,
            )
        },
    )
    with pytest.raises(WallMeshError, match="직교"):
        assemble_wall_meshes(model)


def test_wall_quad_payload_matches_undeformed_corner_coordinates() -> None:
    model = assemble_wall_meshes(_wall_model(1, 1))
    payloads = wall_quad_payloads(model)

    assert len(payloads) == 1
    assert payloads[0].corners[0] == pytest.approx((0.0, 0.0, 0.0))
    assert payloads[0].corners[1] == pytest.approx((2.0, 0.0, 0.0))
    assert payloads[0].corners[2] == pytest.approx((2.0, 0.0, 3.0))
    assert payloads[0].corners[3] == pytest.approx((0.0, 0.0, 3.0))


def test_deformed_payload_moves_corners_along_displacement() -> None:
    model = assemble_wall_meshes(_wall_model(1, 1))
    displacements = {
        1: (0.0, 0.0, 0.0),
        2: (0.0, 0.0, 0.0),
        3: (0.01, 0.0, 0.0),
        4: (0.01, 0.0, 0.0),
    }
    payloads = wall_quad_payloads(model, displacements=displacements, scale=10.0)
    n1, n2, n3, n4 = payloads[0].corners

    assert n1 == pytest.approx((0.0, 0.0, 0.0))
    assert n2 == pytest.approx((2.0, 0.0, 0.0))
    assert n3 == pytest.approx((2.1, 0.0, 3.0))
    assert n4 == pytest.approx((0.1, 0.0, 3.0))
