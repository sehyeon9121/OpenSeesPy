"""The rebuilt deflected shape must match closed-form beam deflections."""

from pathlib import Path

import pytest

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.features.results.deformation import member_deflection
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLES = Path(__file__).parents[2] / "examples"


def _load(name: str):
    source = EXAMPLES / name
    model = OpenSeesModelImporter(timeout_seconds=20).load(source)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=source))
    assert result.status == AnalysisStatus.COMPLETED, result.messages
    return model, result


def test_udl_beam_midspan_sag_matches_5wl4_over_384ei() -> None:
    model, result = _load("udl_beam_2d.py")

    # Both ends are supported, so every node has zero vertical displacement: the whole
    # deflection lives between them and only the rebuild can show it.
    assert result.node_results[1].displacement[1] == pytest.approx(0.0, abs=1e-12)
    assert result.node_results[2].displacement[1] == pytest.approx(0.0, abs=1e-12)

    stations = member_deflection(model, result, 1, samples=16)
    midspan = next(item for item in stations if item.position == pytest.approx(0.5))

    load, length = 10.0, 4.0
    rigidity = result.element_results[1].flexural_rigidity
    expected = -5.0 * load * length**4 / (384.0 * rigidity)
    assert midspan.uy == pytest.approx(expected, rel=1e-6)


def test_rebuilt_shape_starts_and_ends_at_the_node_displacements() -> None:
    model, result = _load("udl_beam_2d.py")

    stations = member_deflection(model, result, 1, samples=8)

    assert stations[0].position == 0.0
    assert stations[-1].position == 1.0
    assert stations[0].uy == pytest.approx(result.node_results[1].displacement[1], abs=1e-12)
    assert stations[-1].uy == pytest.approx(result.node_results[2].displacement[1], abs=1e-12)


def test_point_loaded_beam_midspan_matches_pl3_over_48ei() -> None:
    # examples/simply_supported_beam_2d.py has a node at midspan, so this checks the
    # rebuild agrees with the solver rather than inventing extra deflection.
    model, result = _load("simply_supported_beam_2d.py")

    stations = member_deflection(model, result, 1, samples=8)
    end = stations[-1]

    assert end.uy == pytest.approx(result.node_results[2].displacement[1], rel=1e-9)
    load, length, rigidity = 10.0, 4.0, result.element_results[1].flexural_rigidity
    assert end.uy == pytest.approx(-load * length**3 / (48.0 * rigidity), rel=1e-6)


def test_columns_of_the_textbook_frame_bow_between_their_nodes() -> None:
    model, result = _load("portal_frame_textbook_2d.py")

    stations = member_deflection(model, result, 1, samples=12)
    chord = [
        stations[0].ux + (stations[-1].ux - stations[0].ux) * item.position
        for item in stations
    ]
    bow = [item.ux - straight for item, straight in zip(stations, chord, strict=True)]

    # A member carrying moment cannot stay straight between its ends.
    assert max(abs(value) for value in bow) > 0.0
