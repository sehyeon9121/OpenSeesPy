from openframe.core.domain import BoundaryCondition, Element, Node, StructuralModel, SupportKind


def test_model_reports_missing_element_node() -> None:
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )

    assert model.validate() == ["부재 1가 존재하지 않는 절점을 참조합니다."]


def test_2d_model_is_valid_by_default() -> None:
    model = StructuralModel(nodes={1: Node(1, 0.0, 0.0)})

    assert model.validate() == []


def test_3d_model_and_six_dof_support_are_valid() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, z=2.0, ndf=6)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )

    assert model.validate() == []
    assert model.nodes[1].z == 2.0
    assert model.boundaries[0].support_kind == SupportKind.FIXED


def test_support_kind_is_classified_from_2d_restraints() -> None:
    assert BoundaryCondition(1, (True, True, True)).support_kind == SupportKind.FIXED
    assert BoundaryCondition(2, (True, True, False)).support_kind == SupportKind.PINNED
    assert (
        BoundaryCondition(3, (False, True, False)).support_kind
        == SupportKind.ROLLER_VERTICAL
    )
    assert (
        BoundaryCondition(4, (True, False, False)).support_kind
        == SupportKind.ROLLER_HORIZONTAL
    )
    assert BoundaryCondition(5, (False, False, True)).support_kind == SupportKind.CUSTOM
