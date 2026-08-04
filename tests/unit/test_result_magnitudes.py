from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Element,
    ElementResult,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.magnitudes import magnitude_range, member_magnitudes


def _model() -> StructuralModel:
    return StructuralModel(
        nodes={
            1: Node(tag=1, x=0.0, y=0.0),
            2: Node(tag=2, x=4.0, y=0.0),
            3: Node(tag=3, x=8.0, y=0.0),
        },
        elements={
            1: Element(tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn"),
            2: Element(tag=2, node_i=2, node_j=3, element_type="elasticBeamColumn"),
        },
    )


def _result() -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(node_tag=1, displacement=(0.0, 0.0, 0.0)),
            2: NodeResult(node_tag=2, displacement=(0.003, -0.004, 0.0)),
            3: NodeResult(node_tag=3, displacement=(0.0, -0.02, 0.0)),
        },
        element_results={
            1: ElementResult(element_tag=1, local_forces=(0.0, 5.0, 0.0, 0.0, -5.0, 10.0)),
            2: ElementResult(element_tag=2, local_forces=(0.0, -5.0, -40.0, 0.0, 5.0, 0.0)),
        },
    )


def test_moment_magnitudes_use_each_member_peak() -> None:
    magnitudes = member_magnitudes(_model(), _result(), "moment")

    assert magnitudes == {1: 10.0, 2: 40.0}


def test_shear_magnitudes_use_each_member_peak() -> None:
    magnitudes = member_magnitudes(_model(), _result(), "shear")

    assert magnitudes == {1: 5.0, 2: 5.0}


def test_displacement_magnitudes_take_the_larger_end_node() -> None:
    magnitudes = member_magnitudes(_model(), _result(), "displacement")

    # Element 1 spans nodes 1 (0) and 2 (0.005); element 2 spans nodes 2 and 3 (0.02).
    assert magnitudes[1] == 0.005
    assert magnitudes[2] == 0.02


def test_result_types_without_a_scale_return_nothing_to_colour() -> None:
    assert member_magnitudes(_model(), _result(), "reaction") == {}
    assert member_magnitudes(_model(), _result(), "tables") == {}


def test_range_spans_the_smallest_and_largest_member() -> None:
    assert magnitude_range({1: 10.0, 2: 40.0}) == (10.0, 40.0)


def test_range_of_nothing_is_zero_rather_than_an_error() -> None:
    assert magnitude_range({}) == (0.0, 0.0)
