"""Integration coverage for Arc-Length Control in run_nonlinear_static_analysis.

The centerpiece is a von Mises (two-bar, shallow) truss snap-through benchmark: a
textbook problem with a closed-form load-factor/displacement relationship derivable
from total potential energy stationarity (see _lambda_closed below), whose response
has a genuine limit point - the one thing LoadControl/DisplacementControl cannot
trace but ArcLength is specifically added to handle. This is the "가장 중요한 검증"
in the same spirit as the P-Delta beam-column closed-form check the project already
has (see openframe-pdelta-feature memory): comparing simulated points against a hand-
derived formula, not just checking that something, anything, converged.
"""

import math
from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees.nonlinear_static_solver import (
    run_nonlinear_static_analysis,
)

# --- Von Mises truss geometry/material -------------------------------------------
_B = 100.0  # half-span
_H = 25.0  # apex rise above the ground line (shallow: H/B = 0.25)
_E = 1000.0
_A = 1.0
_L0 = math.sqrt(_B * _B + _H * _H)
_K = _E * _A / _L0  # EA/L0, the "axial spring constant" each bar behaves as

_VON_MISES_TRUSS_MODEL = f"""
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 2)
ops.node(1, {-_B}, 0.0)
ops.node(2, {_B}, 0.0)
ops.node(3, 0.0, {_H})
ops.fix(1, 1, 1)
ops.fix(2, 1, 1)
ops.uniaxialMaterial('Elastic', 1, {_E})
ops.element('corotTruss', 1, 1, 3, {_A}, 1)
ops.element('corotTruss', 2, 2, 3, {_A}, 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(3, 0.0, -1.0)
"""


def _write_von_mises_truss(tmp_path: Path) -> Path:
    source = tmp_path / "von_mises_truss.py"
    source.write_text(_VON_MISES_TRUSS_MODEL, encoding="utf-8")
    return source


def _lambda_closed(dy: float) -> float:
    """Closed-form load factor at apex vertical displacement ``dy`` (Y-up, so
    dy < 0 as the reference downward load - ops.load(3, 0.0, -1.0) - pushes the
    apex down), derived from stationarity of the total potential energy
    Pi(dy) = k*(L(dy)-L0)**2 - F*dy of the two symmetric corotational bars
    (k = EA/L0, engineering strain along the deformed chord - exactly what
    OpenSees' corotTruss element computes):

        F(dy) = 2*k*(L(dy)-L0)*(H+dy)/L(dy)

    and load_factor = -F (since the reference pattern applies Fy=-1.0, so the
    physical load at a given pseudo-time/load factor is Fy = -load_factor).
    """
    length = math.sqrt(_B * _B + (_H + dy) ** 2)
    force = 2.0 * _K * (length - _L0) * (_H + dy) / length
    return -force


def test_von_mises_truss_snap_through_matches_closed_form_past_the_limit_point(
    tmp_path: Path,
) -> None:
    source = _write_von_mises_truss(tmp_path)
    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=3,
            control_dof=2,
            integrator_type="ArcLength",
            arc_length_radius=0.1,
            arc_length_alpha=1.0,
            arc_length_max_steps=126,
            arc_length_min_radius=0.0001,
            arc_length_max_radius=0.1,
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    curve = result["load_displacement_curve"]
    assert len(curve) == 126

    # Every converged point - ascending branch and the one past the limit point
    # alike - must land on the closed-form equilibrium path to (near) machine
    # precision: ArcLength changes which algorithm traces the path, not the
    # physics a single corotTruss element represents exactly.
    for point in curve:
        expected = _lambda_closed(point["control_displacement"])
        assert point["load_factor"] == pytest.approx(expected, abs=1.0e-6)
        assert point["arc_length_radius"] is not None
        assert point["arc_length_radius"] > 0

    # The apex is pushed monotonically further down every step - Arc-Length
    # never had to backtrack to stay on the path.
    displacements = [point["control_displacement"] for point in curve]
    assert displacements == sorted(displacements, reverse=True)

    # The defining behavior under test: the curve's load factor is NOT
    # monotonic - it rises to a limit point, then the *last* step lands past
    # it, with load factor lower than the peak while displacement kept
    # growing. LoadControl/DisplacementControl cannot produce this; only the
    # arc-length constraint (letting the path itself choose the increment)
    # can. (Basic ops.integrator("ArcLength", ...) can oscillate between the
    # two roots straddling a limit point rather than continuing cleanly past
    # it - a known characteristic of OpenSees' own implementation, not fixed
    # here - so this benchmark stops at arc_length_max_steps=126, exactly the
    # first step that lands past the peak, before that oscillation would
    # start.)
    load_factors = [point["load_factor"] for point in curve]
    peak_index = max(range(len(load_factors)), key=load_factors.__getitem__)
    assert 0 < peak_index < len(curve) - 1
    assert load_factors[-1] < load_factors[peak_index]
    assert displacements[-1] < displacements[peak_index]


def test_load_control_cannot_converge_past_the_same_limit_point(tmp_path: Path) -> None:
    """Contrast case: the same model, same peak, but LoadControl - which can only
    scale every pattern to a fixed target load factor, never trace a softening
    branch - fails outright once that target exceeds the structure's capacity,
    instead of finding the equilibrium point past the limit point Arc-Length did
    in the test above."""
    source = _write_von_mises_truss(tmp_path)
    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=3,
            control_dof=2,
            integrator_type="LoadControl",
            num_steps=20,
            target_load_factor=5.9,
            automatic_recovery=False,
        )
    finally:
        ops.wipe()

    assert result["status"] == "partial"
    curve = result["load_displacement_curve"]
    max_load_factor_reached = max(point["load_factor"] for point in curve)
    # Never gets anywhere near the true peak (~5.6591) Arc-Length traced past above.
    assert max_load_factor_reached < 5.66
    assert result["convergence"]["completed_steps"] < result["convergence"]["requested_steps"]


#: A single yielding-material spring - reused from the retry/accuracy solver tests'
#: own pattern (see test_nonlinear_static_solver.py) for the simpler, non-benchmark
#: Arc-Length checks below, where the point is plumbing/validation, not accuracy.
_SPRING_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Elastic', 1, 1000.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 10.0)
"""


def _write_spring_model(tmp_path: Path) -> Path:
    source = tmp_path / "spring.py"
    source.write_text(_SPRING_MODEL, encoding="utf-8")
    return source


def test_arc_length_basic_run_reports_the_new_curve_fields(tmp_path: Path) -> None:
    source = _write_spring_model(tmp_path)
    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=2,
            control_dof=1,
            integrator_type="ArcLength",
            arc_length_radius=0.01,
            arc_length_max_steps=10,
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    curve = result["load_displacement_curve"]
    assert len(curve) == 10
    for point in curve:
        assert point["arc_length_radius"] == pytest.approx(0.01)
        assert point["converged"] is True
        assert point["algorithm_used"] == "Newton"
        assert point["recovered"] is False
        assert point["retry_count"] == 0
        assert point["load_factor"] > 0
    assert result["convergence"]["requested_steps"] == 10


def test_arc_length_max_displacement_terminates_the_run_early(tmp_path: Path) -> None:
    source = _write_spring_model(tmp_path)
    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=2,
            control_dof=1,
            integrator_type="ArcLength",
            arc_length_radius=0.01,
            arc_length_max_steps=50,
            arc_length_max_displacement=0.0025,
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    curve = result["load_displacement_curve"]
    assert len(curve) < 50
    assert abs(curve[-1]["control_displacement"]) >= 0.0025
    assert any("MAXIMUM ABSOLUTE DISPLACEMENT" in message for message in result["messages"])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"arc_length_radius": 0.0}, "ARC-LENGTH RADIUS"),
        ({"arc_length_radius": -1.0}, "ARC-LENGTH RADIUS"),
        ({"arc_length_alpha": 0.0}, "ALPHA"),
        ({"arc_length_max_steps": 0}, "MAXIMUM STEPS"),
        ({"arc_length_min_radius": 0.0}, "MINIMUM RADIUS"),
        (
            {"arc_length_min_radius": 1.0, "arc_length_radius": 0.01, "arc_length_max_radius": 0.5},
            "MINIMUM RADIUS",
        ),
        ({"arc_length_max_displacement": 0.0}, "MAXIMUM ABSOLUTE DISPLACEMENT"),
    ],
)
def test_arc_length_pre_check_rejects_invalid_settings(
    tmp_path: Path, kwargs: dict[str, float], match: str
) -> None:
    source = _write_spring_model(tmp_path)
    try:
        with pytest.raises(RuntimeError, match=match):
            run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                integrator_type="ArcLength",
                **kwargs,
            )
    finally:
        ops.wipe()


def test_arc_length_rejects_unknown_monitor_node(tmp_path: Path) -> None:
    source = _write_spring_model(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="999"):
            run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                integrator_type="ArcLength",
                arc_length_control_node=999,
            )
    finally:
        ops.wipe()


def test_arc_length_rejects_out_of_range_monitor_dof(tmp_path: Path) -> None:
    source = _write_spring_model(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="MONITOR DOF"):
            run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                integrator_type="ArcLength",
                arc_length_control_node=2,
                arc_length_control_dof=2,
            )
    finally:
        ops.wipe()
