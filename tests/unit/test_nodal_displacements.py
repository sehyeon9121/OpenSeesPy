from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.deformation import largest_displacement, nodal_displacements


def _model() -> StructuralModel:
    return StructuralModel(
        nodes={
            1: Node(tag=1, x=0.0, y=0.0),
            2: Node(tag=2, x=4.0, y=0.0),
            3: Node(tag=3, x=2.0, y=3.0),
        }
    )


def _result() -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(node_tag=1, displacement=(0.0, 0.0, 0.0)),
            2: NodeResult(node_tag=2, displacement=(0.003, -0.004, 0.001)),
            3: NodeResult(node_tag=3, displacement=(0.01, 0.0, 0.0)),
        },
    )


def test_pairs_each_node_with_its_coordinates_and_displacement() -> None:
    displacements = nodal_displacements(_model(), _result())

    assert [item.node_tag for item in displacements] == [1, 2, 3]
    second = displacements[1]
    assert (second.x, second.y) == (4.0, 0.0)
    assert (second.ux, second.uy, second.rz) == (0.003, -0.004, 0.001)


def test_magnitude_is_the_resultant_translation() -> None:
    displacements = nodal_displacements(_model(), _result())

    # 3-4-5 triangle: sqrt(0.003^2 + 0.004^2) = 0.005
    assert displacements[1].magnitude == 0.005
    assert displacements[0].moves is False
    assert displacements[1].moves is True


def test_largest_displacement_picks_the_biggest_resultant() -> None:
    peak = largest_displacement(nodal_displacements(_model(), _result()))

    assert peak is not None
    assert peak.node_tag == 3  # 0.01 beats 0.005


def test_largest_displacement_is_none_when_nothing_moved() -> None:
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={1: NodeResult(node_tag=1, displacement=(0.0, 0.0, 0.0))},
    )

    assert largest_displacement(nodal_displacements(_model(), result)) is None


def test_nodes_without_a_result_are_skipped() -> None:
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, node_results={})

    assert nodal_displacements(_model(), result) == ()
