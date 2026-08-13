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

    assert result["status"] == "partial"
    assert len(result["messages"]) == 1
    assert "수렴하지 않았습니다" in result["messages"][0]

    curve = result["load_displacement_curve"]
    # Load reaches Fy=100 at step 100/300*10 ≈ 3.33, so step 4 (load=120) is the
    # first step past capacity - only steps 1-3 converge.
    assert len(curve) == 3
    assert curve[-1]["base_shear"] == pytest.approx(90.0, rel=1e-6)
    assert result["convergence"]["requested_steps"] == 10
    assert result["convergence"]["completed_steps"] == 3
    assert result["convergence"]["failed_step"] == 4
    assert result["convergence"]["total_attempts"] > 3


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


def test_base_shear_includes_coincident_node_below_a_rotational_spring(
    tmp_path: Path,
) -> None:
    """An equalDOF-connected zeroLength hinge reports horizontal reaction on its
    coincident member node rather than the fixed joint. Both nodes define the same
    support location and their reactions must contribute to base shear."""
    source = tmp_path / "hinged_base_frame.py"
    source.write_text(
        """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0, 0.0)
ops.node(3, 0.0, 120.0)
ops.fix(1, 1, 1, 1)
ops.equalDOF(1, 2, 1, 2)
ops.uniaxialMaterial('Elastic', 1, 1.0e7)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 6)
ops.geomTransf('Linear', 1)
ops.element('elasticBeamColumn', 2, 2, 3, 10.0, 29000.0, 1000.0, 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(3, 10.0, 0.0, 0.0)
""",
        encoding="utf-8",
    )
    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=3,
            control_dof=1,
            num_steps=10,
            constraints_type="Plain",
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    assert result["load_displacement_curve"][-1]["base_shear"] == pytest.approx(10.0)


#: Two patterns on the same DOF - pattern 1 (80, "gravity") and pattern 2 (60,
#: "lateral") - so combined-ramp vs. gravity-held-constant produce a measurably
#: different curve even though both are just Steel01 in one direction.
_TWO_PATTERN_SPRING_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Steel01', 1, 100.0, 1000.0, 0.02)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 80.0)
ops.timeSeries('Linear', 2)
ops.pattern('Plain', 2, 2)
ops.load(2, 60.0)
"""

_THREE_PATTERN_SPRING_MODEL = _TWO_PATTERN_SPRING_MODEL + """
ops.timeSeries('Linear', 3)
ops.pattern('Plain', 3, 3)
ops.load(2, 40.0)
"""

#: A softening (strength-degrading) spring: rises to a peak at e=0.2, then the
#: backbone descends to a residual plateau at e=0.5 - LoadControl cannot trace the
#: descending branch (there's no load factor beyond the peak that has an equilibrium
#: solution), DisplacementControl can.
_SOFTENING_SPRING_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial(
    'Hysteretic', 1,
    100.0, 0.1, 120.0, 0.2, 40.0, 0.5,
    -100.0, -0.1, -120.0, -0.2, -40.0, -0.5,
    1.0, 1.0, 0.0, 0.0, 0.0,
)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 200.0)
"""


def test_gravity_pattern_is_held_constant_instead_of_ramping_with_the_push(
    tmp_path: Path,
) -> None:
    source = tmp_path / "two_pattern.py"
    source.write_text(_TWO_PATTERN_SPRING_MODEL, encoding="utf-8")

    try:
        combined = run_nonlinear_static_analysis(
            source, control_node=2, control_dof=1, num_steps=20
        )
        ops.wipe()
        separated = run_nonlinear_static_analysis(
            source,
            control_node=2,
            control_dof=1,
            num_steps=20,
            gravity_pattern=1,
            gravity_steps=5,
        )
    finally:
        ops.wipe()

    assert combined["messages"] == []
    assert separated["messages"] == []

    # Both patterns pushed together: base shear at the end is the full 80+60=140,
    # and since a monotonic single-direction push on a kinematic-hardening spring is
    # path-independent, the final displacement matches the separated run too.
    combined_last = combined["load_displacement_curve"][-1]
    assert combined_last["base_shear"] == pytest.approx(140.0, rel=1e-6)
    assert combined_last["control_displacement"] == pytest.approx(2.1, rel=1e-3)

    # Gravity (80) held constant, only the lateral pattern (60) is in the reported
    # curve - final base shear is just the lateral contribution, not the total.
    separated_last = separated["load_displacement_curve"][-1]
    assert separated_last["base_shear"] == pytest.approx(60.0, rel=1e-6)
    assert separated_last["control_displacement"] == pytest.approx(2.1, rel=1e-3)

    # The very first reported point already shows the difference: combined has both
    # patterns' first increment (140/20=7), separated has only the lateral one's
    # (60/20=3) - gravity never shows up in the curve at all once separated.
    assert combined["load_displacement_curve"][0]["base_shear"] == pytest.approx(7.0, rel=1e-6)
    assert separated["load_displacement_curve"][0]["base_shear"] == pytest.approx(3.0, rel=1e-6)


#: A 3D cantilever (fixed at node 1, free at node 2, 4m along global X). The gravity
#: pattern carries a tiny axial nudge only (decoupled from Z-bending, so it cannot
#: mask the effect under test); the push pattern carries a pure local-Wz distributed
#: load. geomTransf's vecxz=(0,0,1) makes local z coincide with global Z, so bending
#: is governed by Iy and the tip deflects along global DOF 3 (Uz).
_CANTILEVER_3D_TRANSVERSE_Z_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 4.0, 0.0, 0.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)
ops.geomTransf('Linear', 1, 0.0, 0.0, 1.0)
ops.element(
    'elasticBeamColumn', 1, 1, 2,
    0.01, 200000000.0, 80000000.0, 0.0001, 0.0002, 0.0002, 1,
)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, -0.001, 0.0, 0.0, 0.0, 0.0, 0.0)
ops.timeSeries('Linear', 2)
ops.pattern('Plain', 2, 2)
ops.eleLoad('-ele', 1, '-type', '-beamUniform', 0.0, 6.0, 0.0)
"""


def test_replaying_a_3d_pattern_after_a_gravity_phase_reapplies_the_right_component(
    tmp_path: Path,
) -> None:
    """Regression for the ndm-tracking bug: whenever gravity_pattern is set, the push
    pattern is torn down and replayed from the collector's recorded uniform_load_cases.
    A collector that always assumed ndm=2 read the 3D form (Wy, Wz, Wx) as if it were
    2D's (Wy, Wx) - a pure Wz transverse load got replayed as Wx (axial) instead, which
    barely moves the tip. With ndm tracked correctly, the replayed load is still a pure
    Wz UDL, so the tip deflection at full load must match the closed-form cantilever
    formula w*L**4/(8*E*Iy), not the near-zero axial-stretch value the bug produced."""
    source = tmp_path / "cantilever_3d.py"
    source.write_text(_CANTILEVER_3D_TRANSVERSE_Z_MODEL, encoding="utf-8")

    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=2,
            control_dof=3,
            num_steps=4,
            gravity_pattern=1,
            gravity_steps=2,
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    # elasticBeamColumn has no nonlinear material to detect - the solver correctly
    # flags that it cannot tell this apart from a linear-elastic model, which is
    # exactly what this model is; that diagnostic is expected here, not a failure.
    assert len(result["messages"]) == 1
    curve = result["load_displacement_curve"]
    assert len(curve) == 4

    w, length, e, iy = 6.0, 4.0, 200000000.0, 0.0002
    expected_tip_deflection = w * length**4 / (8 * e * iy)

    assert curve[-1]["control_displacement"] == pytest.approx(expected_tip_deflection, rel=1e-3)


def test_3d_six_dof_pushover_traces_biaxial_hinges_and_pdelta_descending_branch() -> None:
    """The application must solve a genuinely spatial nonlinear model, not merely
    accept ndm=3 syntax.  The example combines six-DOF nodes, two yielding
    rotational hinges, a 3D PDelta column, gravity, and a diagonal X/Y push."""
    source = Path(__file__).parents[2] / "examples" / "nonlinear_cantilever_3d.py"

    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=20,
            control_dof=1,
            num_steps=80,
            gravity_pattern=101,
            lateral_pattern=201,
            gravity_steps=10,
            integrator_type="DisplacementControl",
            target_displacement=0.4,
            geometric_transform_type="PDelta",
            constraints_type="Transformation",
            test_type="NormUnbalance",
            tolerance=1.0e-8,
            max_iterations=100,
            max_bisections=6,
        )

        # Equal X/Y loading and properties make the spatial diagonal response
        # symmetric.  Both hinge rotations are well beyond My/K0=0.003 rad.
        assert ops.nodeDisp(20, 1) == pytest.approx(0.4, rel=1e-9)
        assert ops.nodeDisp(20, 2) == pytest.approx(0.4, rel=1e-9)
        hinge_rotations = ops.eleResponse(101, "deformation")
        assert abs(hinge_rotations[0]) > 0.003
        assert abs(hinge_rotations[1]) > 0.003
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    assert result["messages"] == []
    curve = result["load_displacement_curve"]
    assert len(curve) == 80
    assert result["convergence"]["recovered_steps"] == []

    # Heavy gravity plus yielded hinges produces negative post-peak tangent
    # stiffness.  DisplacementControl must retain the complete descending branch.
    peak_shear = max(point["base_shear"] for point in curve)
    assert peak_shear > curve[-1]["base_shear"]
    assert curve[-1]["control_displacement"] == pytest.approx(0.4, rel=1e-9)


def test_rejects_unknown_gravity_pattern(tmp_path: Path) -> None:
    source = tmp_path / "spring.py"
    source.write_text(_TWO_PATTERN_SPRING_MODEL, encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="GRAVITY PATTERN"):
            run_nonlinear_static_analysis(
                source, control_node=2, control_dof=1, gravity_pattern=999
            )
    finally:
        ops.wipe()


def test_selected_lateral_pattern_excludes_other_non_gravity_patterns(
    tmp_path: Path,
) -> None:
    source = tmp_path / "three_pattern.py"
    source.write_text(_THREE_PATTERN_SPRING_MODEL, encoding="utf-8")

    try:
        all_lateral = run_nonlinear_static_analysis(
            source,
            control_node=2,
            gravity_pattern=1,
            num_steps=20,
        )
        ops.wipe()
        selected = run_nonlinear_static_analysis(
            source,
            control_node=2,
            gravity_pattern=1,
            lateral_pattern=2,
            num_steps=20,
        )
    finally:
        ops.wipe()

    assert all_lateral["status"] == "completed"
    assert selected["status"] == "completed"
    assert all_lateral["load_displacement_curve"][-1]["base_shear"] == pytest.approx(
        100.0, rel=1e-6
    )
    assert selected["load_displacement_curve"][-1]["base_shear"] == pytest.approx(
        60.0, rel=1e-6
    )


def test_load_control_cannot_trace_the_post_peak_softening_branch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "softening.py"
    source.write_text(_SOFTENING_SPRING_MODEL, encoding="utf-8")

    try:
        result = run_nonlinear_static_analysis(
            source, control_node=2, control_dof=1, num_steps=20
        )
    finally:
        ops.wipe()

    # Pushed toward 200 (well past the 120 peak), LoadControl must fail to converge
    # somewhere on or after the descending branch - it cannot express "more
    # displacement for less load" at a fixed load factor.
    assert result["messages"] != []
    assert any("수렴하지 않았습니다" in message for message in result["messages"])


def test_displacement_control_traces_the_post_peak_softening_branch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "softening.py"
    source.write_text(_SOFTENING_SPRING_MODEL, encoding="utf-8")

    try:
        result = run_nonlinear_static_analysis(
            source,
            control_node=2,
            control_dof=1,
            num_steps=30,
            integrator_type="DisplacementControl",
            target_displacement=0.6,
        )
    finally:
        ops.wipe()

    assert result["messages"] == []
    curve = result["load_displacement_curve"]
    assert len(curve) == 30
    assert curve[-1]["control_displacement"] == pytest.approx(0.6, rel=1e-6)

    # The peak (120 at e=0.2) is at step 10 of 30 (0.02 per step) - after it, base
    # shear must actually decrease for a run of steps, which LoadControl cannot do.
    peak_step = max(range(len(curve)), key=lambda index: curve[index]["base_shear"])
    assert curve[peak_step]["base_shear"] == pytest.approx(120.0, rel=1e-3)
    descending = curve[peak_step + 1 :]
    assert all(
        later["base_shear"] < earlier["base_shear"]
        for earlier, later in pairwise(descending[:14])
    )
    # Backbone flattens to the residual 40 beyond e=0.5 - final point sits on that
    # plateau, not still sliding down.
    assert curve[-1]["base_shear"] == pytest.approx(40.0, rel=1e-3)


def test_displacement_control_requires_a_nonzero_target(tmp_path: Path) -> None:
    source = _write_spring_model(tmp_path, load=150.0)
    try:
        with pytest.raises(RuntimeError, match="TARGET DISPLACEMENT"):
            run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                integrator_type="DisplacementControl",
            )
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


#: A single elasticBeamColumn cantilever with a constant compressive axial load
#: (gravity_pattern, held constant) plus a small lateral push (lateral_pattern).
#: Euler buckling load for a fixed-free cantilever is pi**2*E*I/(2L)**2 =
#: 9.8696*200000*0.0002/36 ~= 10.97; the P=3.0 axial load is ~27% of that, high
#: enough for P-Delta's amplification to be clearly measurable but far from
#: instability. The script's own ops.geomTransf('Linear', 1) is deliberately
#: "wrong" for the PDelta/Corotational cases below - proving Setup's own
#: selection, not the script's, is what actually reaches OpenSees.
_PDELTA_CANTILEVER_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0, 3.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf('Linear', 1)
ops.element('elasticBeamColumn', 1, 1, 2, 0.01, 200000.0, 0.0002, 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 0.0, -3.0, 0.0)
ops.timeSeries('Linear', 2)
ops.pattern('Plain', 2, 2)
ops.load(2, 1.0, 0.0, 0.0)
"""


def _write_pdelta_cantilever(tmp_path: Path) -> Path:
    source = tmp_path / "pdelta_cantilever.py"
    source.write_text(_PDELTA_CANTILEVER_MODEL, encoding="utf-8")
    return source


class TestGeometricTransformType:
    """Setup's GEOMETRIC TRANSFORMATION selection must override every
    ops.geomTransf(...) call the model script makes (see
    ModelCommandCollector.install(geom_transf_override=...)), not merely be
    displayed - these compare the same script run under different selections."""

    def test_default_is_linear_and_overrides_the_scripts_own_choice(
        self, tmp_path: Path
    ) -> None:
        source = _write_pdelta_cantilever(tmp_path)
        try:
            result = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
            )
        finally:
            ops.wipe()

        assert result["status"] == "completed"
        assert result["nonlinearity"]["geometric_transform_type"] == "Linear"
        # The lack of geometric nonlinearity is exactly why this otherwise-elastic
        # model still gets the "might behave elastically" advisory - proof the
        # override, not the script's own PDelta-shaped intent, is what ran.
        assert any("탄성 증분해석" in message for message in result["messages"])

    def test_pdelta_amplifies_lateral_displacement_versus_linear(
        self, tmp_path: Path
    ) -> None:
        source = _write_pdelta_cantilever(tmp_path)
        try:
            linear = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
                geometric_transform_type="Linear",
            )
            ops.wipe()
            pdelta = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
                geometric_transform_type="PDelta",
            )
        finally:
            ops.wipe()

        assert linear["status"] == pdelta["status"] == "completed"
        assert pdelta["nonlinearity"]["geometric_transform_type"] == "PDelta"
        # PDelta correctly registers as real geometric nonlinearity - the
        # "might behave elastically" advisory must not fire for it.
        assert pdelta["messages"] == []

        linear_tip = linear["load_displacement_curve"][-1]["control_displacement"]
        pdelta_tip = pdelta["load_displacement_curve"][-1]["control_displacement"]
        # Same script, same lateral load - only Setup's selection differs. The
        # classic P-Delta amplification factor here is ~1/(1-0.27) ~= 1.37;
        # asserting a conservative >=10% increase keeps this robust while still
        # being a real, direction-correct physical check, not just "it ran".
        assert pdelta_tip > linear_tip * 1.10

    def test_corotational_is_accepted_and_also_amplifies_versus_linear(
        self, tmp_path: Path
    ) -> None:
        source = _write_pdelta_cantilever(tmp_path)
        try:
            linear = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
                geometric_transform_type="Linear",
            )
            ops.wipe()
            corotational = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
                geometric_transform_type="Corotational",
            )
        finally:
            ops.wipe()

        assert linear["status"] == "completed"
        assert corotational["status"] == "completed"
        assert corotational["nonlinearity"]["geometric_transform_type"] == "Corotational"
        assert corotational["messages"] == []
        linear_tip = linear["load_displacement_curve"][-1]["control_displacement"]
        corotational_tip = corotational["load_displacement_curve"][-1]["control_displacement"]
        assert corotational_tip > linear_tip * 1.10

    def test_rejects_unsupported_geometric_transform_type(self, tmp_path: Path) -> None:
        source = _write_pdelta_cantilever(tmp_path)
        try:
            with pytest.raises(RuntimeError, match="GEOMETRIC TRANSFORMATION"):
                run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=1,
                    geometric_transform_type="Buckling",
                )
        finally:
            ops.wipe()

    def test_use_model_definition_installs_no_override_and_keeps_the_scripts_choice(
        self, tmp_path: Path
    ) -> None:
        """"UseModelDefinition" must behave exactly like the script's own
        geomTransf('Linear', 1) - no override installed at all - so this
        otherwise-elastic model still gets the "might behave elastically"
        advisory, exactly as the explicit-Linear default case does."""
        source = _write_pdelta_cantilever(tmp_path)
        try:
            result = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
                geometric_transform_type="UseModelDefinition",
            )
        finally:
            ops.wipe()

        assert result["status"] == "completed"
        assert result["nonlinearity"]["geometric_transform_type"] == "UseModelDefinition"
        assert result["nonlinearity"]["geometric_transform_override_applied"] is False
        assert any("탄성 증분해석" in message for message in result["messages"])

    def test_use_model_definition_preserves_a_pdelta_choice_the_script_itself_made(
        self, tmp_path: Path
    ) -> None:
        """Proof "Use model definition" reflects the *model's own* transform,
        not a hardcoded default: a script whose own geomTransf is PDelta must
        show the same P-Delta amplification under "UseModelDefinition" as it
        does under an explicit PDelta override, with no override installed."""
        source = tmp_path / "pdelta_by_script.py"
        source.write_text(
            _PDELTA_CANTILEVER_MODEL.replace("ops.geomTransf('Linear', 1)", "ops.geomTransf('PDelta', 1)"),
            encoding="utf-8",
        )
        try:
            linear = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
                geometric_transform_type="Linear",
            )
            ops.wipe()
            model_defined = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                gravity_pattern=1,
                lateral_pattern=2,
                gravity_steps=5,
                geometric_transform_type="UseModelDefinition",
            )
        finally:
            ops.wipe()

        assert model_defined["nonlinearity"]["geometric_transform_override_applied"] is False
        # No "might behave elastically" advisory - the script's own PDelta is
        # real geometric nonlinearity, correctly detected without any override.
        assert model_defined["messages"] == []
        linear_tip = linear["load_displacement_curve"][-1]["control_displacement"]
        model_defined_tip = model_defined["load_displacement_curve"][-1]["control_displacement"]
        assert model_defined_tip > linear_tip * 1.10

    def test_override_atomically_rejects_a_model_containing_any_unsupported_transform(
        self, tmp_path: Path
    ) -> None:
        """A second, unsupported geomTransf tag (never even referenced by any
        element) must block the override for the *entire* model - the
        unsupported call itself raises before reaching real OpenSeesPy at
        all, so nothing partial is ever built or analyzed."""
        source = tmp_path / "mixed_transform.py"
        source.write_text(
            """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0, 3.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf('Linear', 1)
ops.geomTransf('Corotational02', 2)
ops.element('elasticBeamColumn', 1, 1, 2, 0.01, 200000.0, 0.0002, 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 1.0, 0.0, 0.0)
""",
            encoding="utf-8",
        )
        try:
            with pytest.raises(RuntimeError, match="GEOMETRIC TRANSFORMATION"):
                run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=1,
                    geometric_transform_type="PDelta",
                )
        finally:
            ops.wipe()

    def test_use_model_definition_does_not_reject_the_same_mixed_model(
        self, tmp_path: Path
    ) -> None:
        """The atomic override guard only ever fires when an override is
        actually requested - "Use model definition" installs none at all, so
        a real, valid geomTransf type this project simply does not offer as
        an override target must still build and analyze normally."""
        source = tmp_path / "unreferenced_transform.py"
        source.write_text(
            """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0, 3.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf('Corotational', 1)
ops.element('elasticBeamColumn', 1, 1, 2, 0.01, 200000.0, 0.0002, 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 1.0, 0.0, 0.0)
""",
            encoding="utf-8",
        )
        try:
            result = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                geometric_transform_type="UseModelDefinition",
            )
        finally:
            ops.wipe()

        assert result["status"] == "completed"


def _write_3d_cantilever_with_transform(tmp_path: Path, geom_transf_call: str) -> Path:
    source = tmp_path / "cantilever_3d_orientation.py"
    source.write_text(
        f"""
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 4.0, 0.0, 0.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)
{geom_transf_call}
ops.element(
    'elasticBeamColumn', 1, 1, 2,
    0.01, 200000000.0, 80000000.0, 0.0001, 0.0002, 0.0002, 1,
)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 0.0, 0.0, -0.001, 0.0, 0.0, 0.0)
""",
        encoding="utf-8",
    )
    return source


class TestThreeDOrientationValidation:
    """Every 3D beam-column's orientation vector must be checked before the
    analysis starts, regardless of GEOMETRIC TRANSFORMATION policy - this is
    unconditional, not something "Use model definition" vs. an explicit
    override changes."""

    def test_missing_orientation_vector_blocks_the_run(self, tmp_path: Path) -> None:
        source = _write_3d_cantilever_with_transform(tmp_path, "ops.geomTransf('Linear', 1)")
        try:
            with pytest.raises(RuntimeError, match="orientation"):
                run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=3,
                    geometric_transform_type="UseModelDefinition",
                )
        finally:
            ops.wipe()

    def test_zero_orientation_vector_blocks_the_run(self, tmp_path: Path) -> None:
        source = _write_3d_cantilever_with_transform(
            tmp_path, "ops.geomTransf('Linear', 1, 0.0, 0.0, 0.0)"
        )
        try:
            with pytest.raises(RuntimeError, match="orientation"):
                run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=3,
                    geometric_transform_type="UseModelDefinition",
                )
        finally:
            ops.wipe()

    def test_orientation_vector_parallel_to_member_axis_blocks_the_run(
        self, tmp_path: Path
    ) -> None:
        # The member runs along global X (node 1 -> node 2); a vecxz also
        # along X is degenerate - it cannot define a local z axis.
        source = _write_3d_cantilever_with_transform(
            tmp_path, "ops.geomTransf('Linear', 1, 1.0, 0.0, 0.0)"
        )
        try:
            with pytest.raises(RuntimeError, match="orientation"):
                run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=3,
                    geometric_transform_type="UseModelDefinition",
                )
        finally:
            ops.wipe()

    def test_valid_orientation_vector_does_not_block_the_run(self, tmp_path: Path) -> None:
        source = _write_3d_cantilever_with_transform(
            tmp_path, "ops.geomTransf('Linear', 1, 0.0, 0.0, 1.0)"
        )
        try:
            result = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=3,
                geometric_transform_type="UseModelDefinition",
            )
        finally:
            ops.wipe()

        assert result["status"] == "completed"

    def test_orientation_is_blocked_even_under_an_explicit_override(
        self, tmp_path: Path
    ) -> None:
        """Overriding the transform *type* (Linear/PDelta/Corotational) never
        touches the vecxz arguments, which still come from the model's own
        geomTransf call - so a bad vector blocks the run even when Setup asks
        for an explicit override, exactly as it does under "Use model
        definition"."""
        source = _write_3d_cantilever_with_transform(
            tmp_path, "ops.geomTransf('Linear', 1, 0.0, 0.0, 0.0)"
        )
        try:
            with pytest.raises(RuntimeError, match="orientation"):
                run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=3,
                    geometric_transform_type="PDelta",
                )
        finally:
            ops.wipe()


class TestTargetLoadFactor:
    """TARGET LOAD FACTOR scales LoadControl's per-step increment - a request
    for 2.0 must push every pattern to exactly twice its defined load."""

    def test_target_load_factor_scales_the_final_load_reached(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "elastic_spring.py"
        source.write_text(
            """
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
ops.load(2, 50.0)
""",
            encoding="utf-8",
        )
        try:
            default_factor = run_nonlinear_static_analysis(
                source, control_node=2, control_dof=1, num_steps=10
            )
            ops.wipe()
            doubled = run_nonlinear_static_analysis(
                source, control_node=2, control_dof=1, num_steps=10, target_load_factor=2.0
            )
        finally:
            ops.wipe()

        assert default_factor["load_displacement_curve"][-1]["base_shear"] == pytest.approx(
            50.0, rel=1e-9
        )
        assert doubled["load_displacement_curve"][-1]["base_shear"] == pytest.approx(
            100.0, rel=1e-9
        )

    def test_rejects_non_positive_target_load_factor(self, tmp_path: Path) -> None:
        source = _write_spring_model(tmp_path, load=150.0)
        try:
            with pytest.raises(RuntimeError, match="TARGET LOAD FACTOR"):
                run_nonlinear_static_analysis(
                    source, control_node=2, control_dof=1, target_load_factor=0.0
                )
        finally:
            ops.wipe()


class TestAutomaticRecoveryIntegration:
    """automatic_recovery=False ("Use Settings Only") must genuinely remove the
    safety net - a run that only completes because of algorithm fallback or
    bisection must fail earlier without it."""

    def test_disabling_recovery_stops_the_curve_earlier_than_the_default(
        self, tmp_path: Path
    ) -> None:
        # A perfectly-plastic spring pushed past its capacity: the default
        # (automatic_recovery=True) retries with fallback algorithms and a
        # halved increment before giving up (see the module-level test of the
        # same scenario); with recovery disabled, the very first non-converging
        # attempt must end the run, completing no more steps than the default.
        source = _write_spring_model(tmp_path, load=300.0, b_ratio=0.0)
        try:
            with_recovery = run_nonlinear_static_analysis(
                source, control_node=2, control_dof=1, num_steps=10, max_iterations=10
            )
            ops.wipe()
            without_recovery = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                max_iterations=10,
                automatic_recovery=False,
            )
        finally:
            ops.wipe()

        assert with_recovery["status"] == "partial"
        assert without_recovery["status"] == "partial"
        assert without_recovery["convergence"]["completed_steps"] <= (
            with_recovery["convergence"]["completed_steps"]
        )
        # No fallback algorithm and no bisection ever ran.
        assert without_recovery["convergence"]["total_attempts"] == (
            without_recovery["convergence"]["completed_steps"] + 1
        )
        assert without_recovery["convergence"]["automatic_recovery"] is False


class TestAdaptiveStepAndMinIncrement:
    def test_adaptive_step_does_not_change_the_final_target_reached(
        self, tmp_path: Path
    ) -> None:
        """Adaptive Step changes how a step's own increment is discovered, never
        how many reporting steps exist or what total range they cover - this is
        the invariant the rest of this program's contract (exactly num_steps
        points, ending at the requested target) depends on."""
        source = _write_spring_model(tmp_path, load=150.0)
        try:
            result = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=15,
                adaptive_step=True,
                min_increment=1.0e-6,
                max_increment=1.0,
            )
        finally:
            ops.wipe()

        assert result["status"] == "completed"
        assert len(result["load_displacement_curve"]) == 15

    def test_min_increment_ends_the_run_without_crashing(self, tmp_path: Path) -> None:
        source = _write_spring_model(tmp_path, load=300.0, b_ratio=0.0)
        try:
            result = run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                num_steps=10,
                max_iterations=10,
                min_increment=0.05,
            )
        finally:
            ops.wipe()

        assert result["status"] == "partial"
        assert result["load_displacement_curve"]

    def test_rejects_min_increment_greater_than_max_increment(self, tmp_path: Path) -> None:
        source = _write_spring_model(tmp_path, load=150.0)
        try:
            with pytest.raises(RuntimeError, match="MIN INCREMENT"):
                run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=1,
                    min_increment=1.0,
                    max_increment=0.5,
                )
        finally:
            ops.wipe()
