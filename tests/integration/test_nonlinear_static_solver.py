from itertools import pairwise
from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees.nonlinear_static_solver import (
    run_nonlinear_static_analysis,
)

#: A single yielding spring: node 1 fixed, node 2 free, Steel01 bilinear material.
#: Fy=100, E0=1000 (initial stiffness), b (post-yield stiffness ratio) is parameterised.
_SPRING_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Steel01', 1, 100.0, 1000.0, {b_ratio})
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, {load})
"""


def _write_spring_model(tmp_path: Path, *, load: float, b_ratio: float = 0.02) -> Path:
    source = tmp_path / "spring.py"
    source.write_text(_SPRING_MODEL.format(load=load, b_ratio=b_ratio), encoding="utf-8")
    return source


def test_pushover_curve_matches_bilinear_hand_calculation(tmp_path: Path) -> None:
    """Below yield the curve must trace the material's initial stiffness E0=1000;
    above yield it must trace the post-yield stiffness b*E0=20 - exactly what a
    hand-calculated bilinear spring predicts, so this is a real accuracy check, not
    just a smoke test."""
    source = _write_spring_model(tmp_path, load=150.0)
    try:
        result = run_nonlinear_static_analysis(
            source, control_node=2, control_dof=1, num_steps=15
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    assert result["messages"] == []
    curve = result["load_displacement_curve"]
    assert len(curve) == 15

    displacements = [point["control_displacement"] for point in curve]
    assert displacements == sorted(displacements)
    assert all(later > earlier for earlier, later in pairwise(displacements))

    # Step 10 lands exactly at yield (load = 150 * 10/15 = 100 = Fy).
    elastic_point = curve[4]  # load = 50, well below Fy
    assert elastic_point["base_shear"] / elastic_point["control_displacement"] == pytest.approx(
        1000.0, rel=1e-6
    )

    last = curve[-1]
    yield_point = curve[9]
    post_yield_stiffness = (last["base_shear"] - yield_point["base_shear"]) / (
        last["control_displacement"] - yield_point["control_displacement"]
    )
    assert post_yield_stiffness == pytest.approx(0.02 * 1000.0, rel=1e-3)


def test_stops_at_first_non_convergent_step_and_keeps_partial_curve(
    tmp_path: Path,
) -> None:
    """A perfectly-plastic spring (b=0) pushed past its capacity makes the tangent
    stiffness singular - LoadControl must fail to converge there, and the solver must
    report a partial curve plus a clear message instead of raising."""
    source = _write_spring_model(tmp_path, load=300.0, b_ratio=0.0)
    try:
        result = run_nonlinear_static_analysis(
            source, control_node=2, control_dof=1, num_steps=10, max_iterations=10
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    assert len(result["messages"]) == 1
    assert "수렴하지 않았습니다" in result["messages"][0]

    curve = result["load_displacement_curve"]
    # Load reaches Fy=100 at step 100/300*10 ≈ 3.33, so step 4 (load=120) is the
    # first step past capacity - only steps 1-3 converge.
    assert len(curve) == 3
    assert curve[-1]["base_shear"] == pytest.approx(90.0, rel=1e-6)


def test_rejects_unknown_control_node(tmp_path: Path) -> None:
    source = _write_spring_model(tmp_path, load=150.0)
    try:
        with pytest.raises(RuntimeError, match="999"):
            run_nonlinear_static_analysis(source, control_node=999, control_dof=1)
    finally:
        ops.wipe()


#: OpenSeesPy docs' nonlinearTruss example: ndf=2 (translation only, no RZ) - a
#: control_dof of 3 doesn't exist on this model and used to crash the solver with a
#: raw IndexError instead of a validation message.
_TRUSS_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 2)
ops.node(1, 0.0, 0.0)
ops.node(2, 72.0, 0.0)
ops.node(3, 168.0, 0.0)
ops.node(4, 48.0, 144.0)
ops.fix(1, 1, 1)
ops.fix(2, 1, 1)
ops.fix(3, 1, 1)
ops.uniaxialMaterial('Hardening', 1, 29000.0, 36.0, 0.0, 0.05/(1-0.05)*29000.0)
ops.element('Truss', 1, 1, 4, 4.0, 1)
ops.element('Truss', 2, 2, 4, 4.0, 1)
ops.element('Truss', 3, 3, 4, 4.0, 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(4, 160.0, 0.0)
"""


def _write_truss_model(tmp_path: Path) -> Path:
    source = tmp_path / "truss.py"
    source.write_text(_TRUSS_MODEL, encoding="utf-8")
    return source


def test_rejects_control_dof_beyond_the_model_ndf(tmp_path: Path) -> None:
    """control_dof=3 (RZ) doesn't exist on an ndf=2 truss model - this must be a
    validated RuntimeError, not an IndexError out of ops.nodeReaction()."""
    source = _write_truss_model(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="CONTROL DOF"):
            run_nonlinear_static_analysis(source, control_node=4, control_dof=3)
    finally:
        ops.wipe()


def test_truss_pushover_reaches_full_applied_load(tmp_path: Path) -> None:
    """At the final load step the sum of reactions must equal the fully-applied
    Px=160 (the OpenSeesPy docs' own example plots exactly this curve)."""
    source = _write_truss_model(tmp_path)
    try:
        result = run_nonlinear_static_analysis(
            source, control_node=4, control_dof=1, num_steps=20
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    assert result["messages"] == []
    curve = result["load_displacement_curve"]
    assert len(curve) == 20
    assert curve[-1]["base_shear"] == pytest.approx(160.0, rel=1e-6)
    displacements = [point["control_displacement"] for point in curve]
    assert all(later > earlier for earlier, later in pairwise(displacements))
