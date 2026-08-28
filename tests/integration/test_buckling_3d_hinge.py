"""Formal regression coverage for 3D hinge buckling after Phase 2-F.2."""

from __future__ import annotations

import pytest

from tests.integration.buckling_3d_hinge_diagnostics_helpers import (
    CANTILEVER_LENGTH,
    FRAME_PROPERTIES_3D,
    BucklingFailureStage,
    attempt_buckling,
    euler_cantilever_pcr,
    run_linear_static,
    stable_portal_shared_hinge,
    vertical_cantilever,
)
from openframe.core.domain.results import AnalysisStatus


def test_no_hinge_euler_buckling_closed_form() -> None:
    attempt = attempt_buckling(vertical_cantilever())
    assert attempt.stage == BucklingFailureStage.COMPLETED
    assert attempt.buckling_load_factor == pytest.approx(euler_cantilever_pcr(), rel=0.015)


def test_free_end_hinge_euler_matches_no_hinge_within_one_percent() -> None:
    """Tip release does not change the effective buckling length of a fixed-free column."""
    reference = attempt_buckling(vertical_cantilever()).buckling_load_factor
    released = attempt_buckling(vertical_cantilever(release_j=True)).buckling_load_factor
    assert released == pytest.approx(reference, rel=1.0e-6)
    tolerance = 0.015
    assert abs(released - euler_cantilever_pcr()) / euler_cantilever_pcr() < tolerance


def test_base_hinge_cantilever_is_reported_as_a_mechanism() -> None:
    attempt = attempt_buckling(vertical_cantilever(release_i=True))
    assert attempt.stage == BucklingFailureStage.MECHANISM


def test_both_end_hinge_member_is_reported_as_a_mechanism() -> None:
    attempt = attempt_buckling(vertical_cantilever(release_i=True, release_j=True))
    assert attempt.stage == BucklingFailureStage.MECHANISM


def test_stable_frame_shared_hinge_static_and_buckling_succeed() -> None:
    model = stable_portal_shared_hinge()
    assert run_linear_static(model) == AnalysisStatus.COMPLETED
    attempt = attempt_buckling(model)
    assert attempt.stage == BucklingFailureStage.COMPLETED
    assert attempt.buckling_load_factor is not None
    assert attempt.buckling_load_factor > 0.0


def test_offset_free_end_hinge_preserves_positive_buckling_load() -> None:
    attempt = attempt_buckling(vertical_cantilever(release_j=True, offset_i=(0.0, 0.0, 0.1)))
    assert attempt.stage == BucklingFailureStage.COMPLETED
    pcr = euler_cantilever_pcr()
    assert 0.5 * pcr < attempt.buckling_load_factor < 2.0 * pcr
