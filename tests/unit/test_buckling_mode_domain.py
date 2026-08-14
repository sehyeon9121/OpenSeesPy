"""Pins BucklingMode's deliberate separation from ModeShape (modal analysis).

A buckling factor is not a natural frequency, and buckling_solver.py never
forms a mass matrix - if a future change ever "helpfully" merges BucklingMode
into ModeShape (or adds period/frequency/mass_participation_ratio to
BucklingMode), this is the test that should catch it.
"""

import dataclasses

from openframe.core.domain import AnalysisResult, BucklingMode, ModeShape

_MODAL_ONLY_FIELDS = {"period", "frequency_hz", "angular_frequency", "mass_participation_ratio"}


def test_buckling_mode_does_not_carry_any_modal_only_field() -> None:
    field_names = {field.name for field in dataclasses.fields(BucklingMode)}
    assert field_names.isdisjoint(_MODAL_ONLY_FIELDS)


def test_buckling_mode_and_mode_shape_are_distinct_types() -> None:
    assert BucklingMode is not ModeShape


def test_analysis_result_keeps_buckling_and_modal_fields_independent() -> None:
    field_names = {field.name for field in dataclasses.fields(AnalysisResult)}
    assert "mode_shapes" in field_names
    assert "buckling_modes" in field_names
    # Defaults must be independently empty - populating one must never imply
    # anything about the other.
    result = AnalysisResult()
    assert result.mode_shapes == ()
    assert result.buckling_modes == ()
