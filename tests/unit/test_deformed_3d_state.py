import math

import pytest

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Element,
    Node,
    NodeResult,
    StructuralModel,
    TimeHistoryStep,
)
from openframe.features.results.deformation.deformed_3d_state import (
    build_deformed_3d_state,
    compute_3d_translation_auto_scale,
    member_deformed_endpoints,
)


def _two_node_model() -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


def _translation_result() -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(
            time=float(index) * 0.1,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                2: NodeResult(
                    2,
                    displacement=(index * 0.01, index * 0.005, index * 0.002),
                ),
            },
        )
        for index in range(3)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def test_step_zero_middle_and_last_coordinates() -> None:
    model = _two_node_model()
    result = _translation_result()

    state0 = build_deformed_3d_state(model, result, 0, 10.0)
    state1 = build_deformed_3d_state(model, result, 1, 10.0)
    state_last = build_deformed_3d_state(model, result, 99, 10.0)

    assert state0 is not None and state1 is not None and state_last is not None
    assert state0.step_index == 0
    assert state1.step_index == 1
    assert state_last.step_index == 2

    node2_0 = state0.node_lookup[2]
    node2_1 = state1.node_lookup[2]
    assert node2_0.deformed_x == pytest.approx(4.0)
    assert node2_1.deformed_x == pytest.approx(4.0 + 0.01 * 10.0)
    assert node2_1.deformed_y == pytest.approx(0.0 + 0.005 * 10.0)
    assert node2_1.deformed_z == pytest.approx(0.0 + 0.002 * 10.0)


def test_translation_scale_zero_keeps_original_positions() -> None:
    model = _two_node_model()
    result = _translation_result()
    state = build_deformed_3d_state(model, result, 2, 0.0)

    assert state is not None
    node2 = state.node_lookup[2]
    assert node2.deformed_x == pytest.approx(node2.original_x)
    assert node2.deformed_y == pytest.approx(node2.original_y)
    assert node2.deformed_z == pytest.approx(node2.original_z)


def test_missing_node_result_is_invalid_at_original_position() -> None:
    model = _two_node_model()
    steps = (
        TimeHistoryStep(
            time=0.0,
            node_results={2: NodeResult(2, displacement=(0.1, 0.0, 0.0))},
        ),
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)
    state = build_deformed_3d_state(model, result, 0, 5.0)

    assert state is not None
    node1 = state.node_lookup[1]
    assert node1.valid is False
    assert node1.deformed_x == pytest.approx(0.0)


def test_unknown_result_node_tag_is_ignored() -> None:
    model = _two_node_model()
    steps = (
        TimeHistoryStep(
            time=0.0,
            node_results={99: NodeResult(99, displacement=(1.0, 1.0, 1.0))},
        ),
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)
    state = build_deformed_3d_state(model, result, 0, 1.0)

    assert state is not None
    assert set(state.node_lookup) == {1, 2}


def test_nan_inf_displacement_falls_back_to_original() -> None:
    model = _two_node_model()
    steps = (
        TimeHistoryStep(
            time=0.0,
            node_results={2: NodeResult(2, displacement=(math.nan, 0.0, 0.0))},
        ),
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)
    state = build_deformed_3d_state(model, result, 0, 10.0)

    assert state is not None
    node2 = state.node_lookup[2]
    assert node2.deformed_x == pytest.approx(4.0)


def test_original_model_coordinates_are_not_mutated() -> None:
    model = _two_node_model()
    original = (model.nodes[2].x, model.nodes[2].y, model.nodes[2].z)
    result = _translation_result()
    build_deformed_3d_state(model, result, 2, 50.0)
    assert (model.nodes[2].x, model.nodes[2].y, model.nodes[2].z) == original


def test_member_endpoints_connect_deformed_nodes() -> None:
    model = _two_node_model()
    result = _translation_result()
    state = build_deformed_3d_state(model, result, 2, 10.0)
    assert state is not None
    endpoints = member_deformed_endpoints(model, state, 1)
    assert endpoints is not None
    start, end = endpoints
    assert start == pytest.approx((state.node_lookup[1].deformed_x, state.node_lookup[1].deformed_y, state.node_lookup[1].deformed_z))
    assert end == pytest.approx((state.node_lookup[2].deformed_x, state.node_lookup[2].deformed_y, state.node_lookup[2].deformed_z))


def test_auto_scale_zero_displacement_returns_default() -> None:
    model = _two_node_model()
    steps = (
        TimeHistoryStep(
            time=0.0,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                2: NodeResult(2, displacement=(0.0, 0.0, 0.0)),
            },
        ),
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)
    assert compute_3d_translation_auto_scale(model, result) == 1.0


def test_auto_scale_positive_displacement_is_clamped() -> None:
    model = _two_node_model()
    result = _translation_result()
    scale = compute_3d_translation_auto_scale(model, result)
    assert 1.0 <= scale <= 10_000.0
