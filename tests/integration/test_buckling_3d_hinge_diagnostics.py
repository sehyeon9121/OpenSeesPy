"""Phase 2-F.1 diagnostics: 3D moment-release hinges vs elastic buckling.

These tests document a known defect - buckling extraction uses FullGeneral and
fails when the hinge zeroLength leaves zero-stiffness bending DOFs in the
tangent matrix. Product code is intentionally untouched here; this file only
records reproduction cases and topology parity between exporter and in-process
solver builds.
"""

from __future__ import annotations

import re

import openseespy.opensees as ops
import pytest

from openframe.core.domain.results import AnalysisStatus
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver, _HINGE_MATERIAL_TAG
from tests.integration.buckling_3d_hinge_diagnostics_helpers import (
    MINIMAL_REPRODUCTION_MODELS,
    BucklingFailureStage,
    attempt_buckling,
    export_script,
    run_linear_static,
    shared_hinge_cantilever,
    stiffness_diagnostics,
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


@pytest.mark.parametrize("case_name", ["no_hinge"])
def test_buckling_succeeds_without_hinges(case_name: str) -> None:
    attempt = attempt_buckling(MINIMAL_REPRODUCTION_MODELS[case_name]())
    assert attempt.stage == BucklingFailureStage.COMPLETED
    assert attempt.buckling_load_factor is not None
    assert attempt.buckling_load_factor > 0.0


@pytest.mark.parametrize(
    "case_name",
    [
        "top_release",
        "base_release",
        "both_ends",
        "shared_hinge",
        "local_axis_angle_plus_hinge",
        "offset_plus_hinge",
    ],
)
def test_buckling_currently_fails_when_hinges_are_present(case_name: str) -> None:
    """Every hinge topology today dies before K_loaded - at zero-load K_material."""
    attempt = attempt_buckling(MINIMAL_REPRODUCTION_MODELS[case_name]())
    assert attempt.stage == BucklingFailureStage.K_MATERIAL
    assert "무하중 상태" in attempt.message


def test_top_release_linear_static_also_fails_on_singular_stiffness() -> None:
    """A tip release leaves a free global Rx on the real top node (orphan fix pins
    Ry/Rz only) - BandGeneral cannot factorize K even at full load."""
    status = run_linear_static(vertical_cantilever(release_j=True))
    assert status == AnalysisStatus.FAILED


def test_base_release_linear_static_still_converges_with_band_general() -> None:
    """Same hinge topology, but the fixed base keeps the real node rigid so only
    the dummy node's two released bending DOFs are zero-energy - BandGeneral still
    finds a particular static solution even though FullGeneral buckling cannot."""
    status = run_linear_static(vertical_cantilever(release_i=True))
    assert status == AnalysisStatus.COMPLETED


def test_exporter_and_in_process_hinge_topology_match() -> None:
    """Duplicate-node tags and zeroLength count from export must mirror _build."""
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


def test_top_release_zero_energy_mode_is_free_global_rx_at_tip() -> None:
    diag = stiffness_diagnostics(vertical_cantilever(release_j=True))
    assert diag.zero_eigenvalue_count >= 1
    assert any("n5:Rx" in mode for mode in diag.zero_energy_modes)


def test_base_release_zero_energy_modes_live_on_dummy_hinge_node() -> None:
    dummy_tag = MaterialFreeStaticsSolver._hinge_node_tag(1, "i")
    diag = stiffness_diagnostics(vertical_cantilever(release_i=True))
    assert diag.zero_eigenvalue_count >= 2
    assert any(f"n{dummy_tag}:" in mode for mode in diag.zero_energy_modes)


def test_shared_hinge_applies_orphan_rotation_fix_on_internal_node() -> None:
    model = shared_hinge_cantilever()
    script = export_script(model)
    exported = topology_from_script(script, model)
    assert exported.orphaned_rotation_fixes == (2,)
    assert "ops.fix(2," in script
    assert "0, 0, 0, 0, 1, 1)" in script


def test_hinge_zeroLength_orientation_ignores_local_axis_angle() -> None:
    """Documented mismatch: geomTransf uses local_axis_angle, _hinge_local_axes does not."""
    model = vertical_cantilever(release_j=True, local_axis_angle=15.0)
    script = export_script(model)
    orient_match = re.search(r"ops\.geomTransf\('Linear', 4, ([^)]+)\)", script)
    hinge_match = re.search(r"ops\.element\('zeroLength', 8000041, 5, 8000041, .*'-orient', ([^)]+)\)", script)
    assert orient_match is not None
    assert hinge_match is not None
    # vecxz for the beam (first three numbers after tag) differs from hinge vecx.
    beam_vecxz = tuple(float(part) for part in orient_match.group(1).split(",")[:3])
    hinge_vecx = tuple(float(part) for part in hinge_match.group(1).split(",")[:3])
    assert beam_vecxz != pytest.approx(hinge_vecx, abs=1.0e-6)


@pytest.mark.xfail(strict=True, reason="Known defect: hinge models are singular at K_material.")
def test_top_release_buckling_should_eventually_succeed() -> None:
    attempt = attempt_buckling(vertical_cantilever(release_j=True))
    assert attempt.stage == BucklingFailureStage.COMPLETED
