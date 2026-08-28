"""Phase 2-F hinge/buckling diagnostics - updated after orphan-DOF fix (2-F.2).

Stable free-end hinges and shared hinges in braced frames should converge;
true mechanisms (base release, both-end release on an isolated cantilever) must
fail with an explicit mechanism message, not a bare LAPACK singular warning.
"""

from __future__ import annotations

import openseespy.opensees as ops
import pytest

from openframe.core.domain.results import AnalysisStatus
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver, _HINGE_MATERIAL_TAG
from tests.integration.buckling_3d_hinge_diagnostics_helpers import (
    BucklingFailureStage,
    _write_temp_script,
    attempt_buckling,
    euler_cantilever_pcr,
    export_script,
    run_linear_static,
    shared_hinge_cantilever,
    stable_portal_shared_hinge,
    topology_from_script,
    vertical_cantilever,
)


def _expected_hinge_dummy_tags(model) -> set[int]:
    tags: set[int] = set()
    for element in model.elements.values():
        if element.moment_release_i:
            tags.add(MaterialFreeStaticsSolver._hinge_node_tag(element.tag, "i"))
        if element.moment_release_j:
            tags.add(MaterialFreeStaticsSolver._hinge_node_tag(element.tag, "j"))
    return tags


def _in_process_node_tags(model) -> set[int]:
    MaterialFreeStaticsSolver._build(model, "frame")  # noqa: SLF001
    tags = {int(tag) for tag in ops.getNodeTags()}
    ops.wipe()
    return tags


def test_buckling_succeeds_without_hinges() -> None:
    attempt = attempt_buckling(vertical_cantilever())
    assert attempt.stage == BucklingFailureStage.COMPLETED
    assert attempt.buckling_load_factor == pytest.approx(euler_cantilever_pcr(), rel=0.015)


def test_free_end_hinge_buckling_matches_the_pin_top_euler_column() -> None:
    """Fixed-base column with a tip release is still K=2 - same Pcr as the rigid-tip case."""
    no_hinge = attempt_buckling(vertical_cantilever()).buckling_load_factor
    tip_hinge = attempt_buckling(vertical_cantilever(release_j=True)).buckling_load_factor
    assert tip_hinge == pytest.approx(no_hinge, rel=1.0e-6)
    assert tip_hinge == pytest.approx(euler_cantilever_pcr(), rel=0.015)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: vertical_cantilever(release_i=True),
        lambda: vertical_cantilever(release_i=True, release_j=True),
        shared_hinge_cantilever,
    ],
)
def test_true_mechanisms_are_rejected_with_an_explicit_message(factory) -> None:
    attempt = attempt_buckling(factory())
    assert attempt.stage == BucklingFailureStage.MECHANISM
    assert "기구 상태" in attempt.message


def test_free_end_hinge_linear_static_converges() -> None:
    assert run_linear_static(vertical_cantilever(release_j=True)) == AnalysisStatus.COMPLETED


def test_stable_portal_shared_hinge_buckling_converges() -> None:
    attempt = attempt_buckling(stable_portal_shared_hinge())
    assert attempt.stage == BucklingFailureStage.COMPLETED
    assert attempt.buckling_load_factor is not None
    assert attempt.buckling_load_factor > 0.0


def test_exporter_and_in_process_hinge_topology_match() -> None:
    model = shared_hinge_cantilever()
    script = export_script(model)
    exported = topology_from_script(script, model)
    in_process_nodes = _in_process_node_tags(model)
    assert set(exported.node_tags) == in_process_nodes
    assert set(exported.node_tags) & _expected_hinge_dummy_tags(model) == _expected_hinge_dummy_tags(model)
    assert len(exported.zero_length_calls) == sum(
        int(element.moment_release_i) + int(element.moment_release_j)
        for element in model.elements.values()
    )
    for call in exported.zero_length_calls:
        assert "'-dir', 1, 2, 3, 4" in call
        assert "'-orient'" in call
        assert f"{_HINGE_MATERIAL_TAG}" in call


def test_free_end_hinge_passes_full_general_zero_load_analysis() -> None:
    """After orphan pins, K_material must factorize under the same solver stack as buckling."""
    from openframe.infrastructure.opensees.script_execution import run_model_script

    source = _write_temp_script(vertical_cantilever(release_j=True))
    run_model_script(source)
    ops.wipeAnalysis()
    ops.system("FullGeneral")
    ops.numberer("RCM")
    ops.constraints("Transformation")
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 0.0)
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    ops.wipe()


def test_shared_hinge_applies_full_orphan_rotation_pin_on_internal_node() -> None:
    model = shared_hinge_cantilever()
    script = export_script(model)
    exported = topology_from_script(script, model)
    assert exported.orphaned_rotation_fixes == (2,)
    assert "ops.fix(2," in script
    assert "0, 0, 0, 1, 1, 1)" in script


def test_hinge_zeroLength_orientation_uses_local_axis_angle() -> None:
    """Hinge vecy must rotate with ``local_axis_angle`` the same way geomTransf vecxz does."""
    model = vertical_cantilever(release_j=True, local_axis_angle=15.0)
    node_i = model.nodes[4]
    node_j = model.nodes[5]
    from openframe.features.analysis.statics.solver import _hinge_local_axes

    _, vecy_zero = _hinge_local_axes(node_i, node_j, 0.0)
    _, vecy_rotated = _hinge_local_axes(node_i, node_j, 15.0)
    assert vecy_rotated != pytest.approx(vecy_zero, abs=1.0e-6)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: vertical_cantilever(release_j=True, local_axis_angle=15.0),
        lambda: vertical_cantilever(release_j=True, offset_i=(0.0, 0.0, 0.1)),
    ],
)
def test_angled_and_offset_free_end_hinges_buckle_successfully(factory) -> None:
    attempt = attempt_buckling(factory())
    assert attempt.stage == BucklingFailureStage.COMPLETED
    assert attempt.buckling_load_factor is not None
    assert attempt.buckling_load_factor > 0.0
