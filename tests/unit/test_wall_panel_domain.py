"""WallPanel / ShellQuad domain: empty by default, authoring vs mesh."""

from openframe.core.domain import (
    Element,
    Node,
    NodeOrigin,
    ShellQuad,
    StructuralModel,
    WallPanel,
)


def test_default_structural_model_has_empty_walls_and_shell_quads() -> None:
    model = StructuralModel()

    assert model.walls == {}
    assert model.shell_quads == {}
    assert model.elements == {}
    assert model.validate() == []


def test_existing_beam_model_constructor_does_not_need_wall_fields() -> None:
    """Adding walls/shell_quads last with defaults must not break beam-only
    construction — every existing test builds StructuralModel without them.
    """
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
    )

    assert model.walls == {}
    assert model.shell_quads == {}
    assert list(model.nodes) == [1, 2]
    assert 1 in model.elements


def test_rectangular_wall_panel_stores_four_corners_and_mesh_density() -> None:
    panel = WallPanel(
        tag=1,
        node_1=1,
        node_2=2,
        node_3=3,
        node_4=4,
        thickness=0.2,
        nx=2,
        ny=2,
        elastic_modulus=30_000_000.0,
        poisson_ratio=0.2,
    )
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 2.0, 0.0, 3.0, 6),
            4: Node(4, 0.0, 0.0, 3.0, 6),
        },
        walls={1: panel},
    )

    assert model.shell_quads == {}
    assert model.walls[1].nx == 2
    assert model.walls[1].ny == 2
    assert model.validate() == []
    assert all(not node.is_wall_mesh for node in model.nodes.values())
    assert NodeOrigin.USER.value == "user"


def test_validate_rejects_a_wall_that_points_at_a_missing_node() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0, 6)},
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

    errors = model.validate()
    assert any("존재하지 않는 절점" in message for message in errors)


def test_authored_node_origin_defaults_to_user() -> None:
    node = Node(1, 0.0, 0.0, 0.0)
    assert node.origin is NodeOrigin.USER
    assert not node.is_wall_mesh
    mesh_node = Node(9, 1.0, 0.0, 1.0, 6, NodeOrigin.WALL_MESH)
    assert mesh_node.is_wall_mesh
    assert ShellQuad(10, 1, 2, 3, 4, wall_tag=1).wall_tag == 1
