"""Execute an uploaded OpenSeesPy source as a model-building script only.

Uploaded files usually carry their own analysis block. Running such a file as-is
would solve the model while the user is merely importing it, and would solve it a
second time when the RUN button starts the real analysis - stacking the load
patterns and corrupting the reported reactions. The commands that belong to the
analysis stage are therefore replaced by inert stand-ins while the script runs, so
the script contributes the model, supports and loads while the application stays
in charge of when and how the structure is solved.
"""

import runpy
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

#: Analysis-stage commands the application owns. A script may still call them; the
#: call is recorded by OpenSees as a no-op instead of solving the structure.
SUPPRESSED_COMMANDS = (
    "system",
    "numberer",
    "constraints",
    "test",
    "algorithm",
    "integrator",
    "analysis",
    "analyze",
    "wipeAnalysis",
    "eigen",
    "modalProperties",
    "rayleigh",
    "reactions",
    "loadConst",
    "recorder",
    "record",
)


def _analyze_stand_in(*arguments: Any, **keywords: Any) -> int:
    """Report success so that ``if ops.analyze(1) != 0: ...`` guards stay quiet."""
    return 0


def _eigen_stand_in(*arguments: Any, **keywords: Any) -> list[float]:
    """Return as many non-zero eigenvalues as asked for.

    Scripts routinely divide by an eigenvalue to report periods, so zeros or an
    empty list would turn a suppressed command into a crash.
    """
    counts = [int(value) for value in arguments if isinstance(value, (int, float))]
    return [1.0] * (counts[-1] if counts else 1)


def _recorder_stand_in(*arguments: Any, **keywords: Any) -> int:
    """Return a recorder tag without opening any output file."""
    return 0


def _inert(*arguments: Any, **keywords: Any) -> None:
    return None


_STAND_INS: dict[str, Callable[..., Any]] = {
    "analyze": _analyze_stand_in,
    "eigen": _eigen_stand_in,
    "recorder": _recorder_stand_in,
}


class AnalysisStageSuppressor:
    """Swap the analysis-stage OpenSees commands for inert stand-ins."""

    def __init__(self) -> None:
        self._originals: dict[str, Callable[..., Any]] = {}

    def install(self) -> None:
        for name in SUPPRESSED_COMMANDS:
            original = getattr(ops, name, None)
            if original is None or name in self._originals:
                continue
            self._originals[name] = original
            setattr(ops, name, _STAND_INS.get(name, _inert))

    def restore(self) -> None:
        for name, original in self._originals.items():
            setattr(ops, name, original)
        self._originals.clear()


@contextmanager
def analysis_stage_suppressed() -> Iterator[None]:
    suppressor = AnalysisStageSuppressor()
    suppressor.install()
    try:
        yield
    finally:
        suppressor.restore()


def run_model_script(source: Path) -> None:
    """Build the model described by ``source`` without solving it."""
    with analysis_stage_suppressed():
        runpy.run_path(str(source), run_name="__main__")
