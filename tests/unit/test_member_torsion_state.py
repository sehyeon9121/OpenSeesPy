"""Unit tests for Saint-Venant twist marker state (Phase 3-C)."""

from __future__ import annotations

import math

import pytest

from openframe.core.domain import (
    AnalysisResult,
    Element,
    Node,
    NodeResult,
    StructuralModel,
    TimeHistoryStep,
)
from openframe.features.results.deformation.deformed_3d_state import build_deformed_3d_state
from openframe.features.results.deformation.member_torsion_state import (
    build_member_torsion_state,
)


def _beam_model(
    *,
    i: tuple[float, float, float],
    j: tuple[float, float, float],
    local_axis_angle: float = 0.0,
) -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, i[0], i[1], i[2]),
            2: Node(2, j[0], j[1], j[2]),
        },
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                local_axis_angle=local_axis_angle,
            )
        },
    )


def _history_result(
    model: StructuralModel,
    displacements: dict[int, tuple[float, ...]],
) -> AnalysisResult:
    node_results = {
        tag: NodeResult(tag, displacement=displacements.get(tag, (0.0,) * model.ndf))
        for tag in model.nodes
    }
    return AnalysisResult(time_history=(TimeHistoryStep(time=0.0, node_results=node_results),))


def _theta_at_marker(state, member_tag: int, marker_index: int) -> float:
    arms = [
        arm
        for arm in state.markers
        if arm.element_tag == member_tag and arm.axis_name == "y"
    ]
    arms.sort(key=lambda arm: arm.s)
    return arms[marker_index].theta_display


def test_horizontal_pure_torsion_linear_interpolation() -> None:
    """Case A/F: horizontal member, zero translation, end twist only."""
    model = _beam_model(i=(0.0, 0.0, 0.0), j=(10.0, 0.0, 0.0))
    result = _history_result(
        model,
        {
            1: (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            2: (0.0, 0.0, 0.0, 0.1, 0.0, 0.0),
        },
    )
    deformed = build_deformed_3d_state(model, result, 0, 1.0)
    assert deformed is not None
    state = build_member_torsion_state(
        model,
        result,
        deformed,
        0,
        rotation_scale=1.0,
        marker_count=5,
    )
    assert state is not None
    assert state.has_torsion
    assert deformed.max_translation_magnitude == pytest.approx(0.0)
    assert _theta_at_marker(state, 1, 0) == pytest.approx(0.0)
    assert _theta_at_marker(state, 1, 2) == pytest.approx(0.05)
    assert _theta_at_marker(state, 1, 4) == pytest.approx(0.1)

    scaled = build_member_torsion_state(
        model,
        result,
        deformed,
        0,
        rotation_scale=2.0,
        marker_count=5,
    )
    assert scaled is not None
    assert _theta_at_marker(scaled, 1, 4) == pytest.approx(0.2)


def test_vertical_member_global_z_rotation_projects_to_torsion() -> None:
    """Case B: local x aligned with global Z."""
    model = _beam_model(i=(0.0, 0.0, 0.0), j=(0.0, 0.0, 5.0))
    result = _history_result(
        model,
        {
            1: (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            2: (0.0, 0.0, 0.0, 0.0, 0.0, 0.1),
        },
    )
    deformed = build_deformed_3d_state(model, result, 0, 1.0)
    assert deformed is not None
    state = build_member_torsion_state(
        model,
        result,
        deformed,
        0,
        rotation_scale=1.0,
        marker_count=3,
    )
    assert state is not None
    assert _theta_at_marker(state, 1, 2) == pytest.approx(0.1)


def test_diagonal_member_dot_product_projection() -> None:
    """Case C: twist equals rotation projected onto member axis."""
    model = _beam_model(i=(0.0, 0.0, 0.0), j=(3.0, 4.0, 0.0))
    rotation = (0.2, 0.1, 0.0)
    ex = (3.0 / 5.0, 4.0 / 5.0, 0.0)
    expected = rotation[0] * ex[0] + rotation[1] * ex[1] + rotation[2] * ex[2]
    result = _history_result(
        model,
        {
            1: (0.0, 0.0, 0.0, *rotation),
            2: (0.0, 0.0, 0.0, *rotation),
        },
    )
    deformed = build_deformed_3d_state(model, result, 0, 1.0)
    assert deformed is not None
    state = build_member_torsion_state(
        model,
        result,
        deformed,
        0,
        rotation_scale=1.0,
        marker_count=3,
    )
    assert state is not None
    assert _theta_at_marker(state, 1, 1) == pytest.approx(expected)


def test_bending_rotation_perpendicular_to_axis_gives_zero_torsion() -> None:
    """Case D: rotation orthogonal to local x -> no twist marker."""
    model = _beam_model(i=(0.0, 0.0, 0.0), j=(10.0, 0.0, 0.0))
    result = _history_result(
        model,
        {
            1: (0.0, 0.0, 0.0, 0.0, 0.2, 0.0),
            2: (0.0, 0.0, 0.0, 0.0, 0.3, 0.0),
        },
    )
    deformed = build_deformed_3d_state(model, result, 0, 1.0)
    assert deformed is not None
    state = build_member_torsion_state(
        model,
        result,
        deformed,
        0,
        rotation_scale=1.0,
        marker_count=3,
    )
    assert state is not None
    assert not state.has_torsion
    for arm in state.markers:
        assert abs(arm.theta_display) < 1e-12


def test_local_axis_angle_sets_initial_orientation() -> None:
    """Case E: initial cross-section rotated before twist is applied."""
    angle = 30.0
    model = _beam_model(
        i=(0.0, 0.0, 0.0),
        j=(10.0, 0.0, 0.0),
        local_axis_angle=angle,
    )
    zero = _history_result(
        model,
        {
            1: (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            2: (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        },
    )
    twisted = _history_result(
        model,
        {
            1: (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            2: (0.0, 0.0, 0.0, 0.05, 0.0, 0.0),
        },
    )
    deformed_zero = build_deformed_3d_state(model, zero, 0, 1.0)
    deformed_twisted = build_deformed_3d_state(model, twisted, 0, 1.0)
    assert deformed_zero is not None and deformed_twisted is not None
    zero_state = build_member_torsion_state(
        model,
        zero,
        deformed_zero,
        0,
        rotation_scale=1.0,
        marker_count=2,
    )
    twist_state = build_member_torsion_state(
        model,
        twisted,
        deformed_twisted,
        0,
        rotation_scale=1.0,
        marker_count=2,
    )
    assert zero_state is not None and twist_state is not None
    z0 = next(
        arm
        for arm in zero_state.markers
        if arm.axis_name == "y" and arm.marker_index == 1
    )
    z1 = next(
        arm
        for arm in twist_state.markers
        if arm.axis_name == "y" and arm.marker_index == 1
    )
    assert (z0.direction_x, z0.direction_y, z0.direction_z) != (
        z1.direction_x,
        z1.direction_y,
        z1.direction_z,
    )
    assert z1.theta_display == pytest.approx(0.05)


def test_missing_rotations_do_not_crash() -> None:
    """Case G: 3DOF-style displacement tuples treated as zero rotation."""
    model = _beam_model(i=(0.0, 0.0, 0.0), j=(5.0, 0.0, 0.0))
    node_results = {
        tag: NodeResult(tag, displacement=(0.1, 0.0, 0.0)) for tag in model.nodes
    }
    result = AnalysisResult(time_history=(TimeHistoryStep(time=0.0, node_results=node_results),))
    deformed = build_deformed_3d_state(model, result, 0, 1.0)
    assert deformed is not None
    state = build_member_torsion_state(
        model,
        result,
        deformed,
        0,
        rotation_scale=1.0,
        marker_count=3,
    )
    assert state is not None
    assert not state.has_torsion


def test_nan_rotation_is_sanitized() -> None:
    """Case H: invalid rotations become zero twist."""
    model = _beam_model(i=(0.0, 0.0, 0.0), j=(5.0, 0.0, 0.0))
    result = _history_result(
        model,
        {
            1: (0.0, 0.0, 0.0, float("nan"), 0.0, 0.0),
            2: (0.0, 0.0, 0.0, 0.1, 0.0, 0.0),
        },
    )
    deformed = build_deformed_3d_state(model, result, 0, 1.0)
    assert deformed is not None
    state = build_member_torsion_state(
        model,
        result,
        deformed,
        0,
        rotation_scale=1.0,
        marker_count=3,
    )
    assert state is not None
    assert math.isfinite(state.markers[0].direction_x)
    assert math.isfinite(state.markers[-1].theta_display)
