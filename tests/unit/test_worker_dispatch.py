"""``worker.run_analysis``'s kind->solver dispatch.

The dispatch is a plain if/elif chain that falls through to
``run_linear_static_analysis`` for anything it does not recognize - the
sharpest landmine in adding a new ``AnalysisKind``: forgetting a branch does
not crash, it silently runs the wrong (but plausible-looking) solver
instead. This pins every kind to its own solver function so that mistake
would fail loudly here instead.
"""

from pathlib import Path
from unittest.mock import patch

from openframe.infrastructure.opensees import worker

_SOURCE = Path("model.py")


def test_response_spectrum_dispatches_to_its_own_solver_not_linear_static() -> None:
    with (
        patch.object(worker, "run_response_spectrum_analysis") as response_spectrum_solver,
        patch.object(worker, "run_linear_static_analysis") as linear_static_solver,
    ):
        response_spectrum_solver.return_value = {"status": "completed"}
        worker.run_analysis(
            _SOURCE,
            "response_spectrum",
            {"periods": [0.1, 1.0], "spectral_accelerations": [0.5, 0.5]},
        )
    response_spectrum_solver.assert_called_once()
    linear_static_solver.assert_not_called()


def test_response_spectrum_directions_are_converted_to_a_tuple() -> None:
    with patch.object(worker, "run_response_spectrum_analysis") as response_spectrum_solver:
        response_spectrum_solver.return_value = {"status": "completed"}
        worker.run_analysis(
            _SOURCE,
            "response_spectrum",
            {
                "periods": [0.1, 1.0],
                "spectral_accelerations": [0.5, 0.5],
                "directions": ["X", "Y"],
            },
        )
    _, kwargs = response_spectrum_solver.call_args
    assert kwargs["directions"] == ("X", "Y")


def test_an_unrecognized_kind_falls_back_to_linear_static() -> None:
    """Documents the existing fallback behavior (not this feature's own) -
    kept as a named test so a future kind addition sees this exact landmine
    called out, rather than rediscovering it the hard way."""
    with patch.object(worker, "run_linear_static_analysis") as linear_static_solver:
        linear_static_solver.return_value = {"status": "completed"}
        worker.run_analysis(_SOURCE, "not_a_real_kind", {})
    linear_static_solver.assert_called_once_with(_SOURCE)
