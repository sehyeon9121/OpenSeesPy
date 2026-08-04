"""Execute an uploaded OpenSeesPy source as a model-building script only.

Uploaded files usually carry their own analysis block. Running such a file as-is
would solve the model while the user is merely importing it, and would solve it a
second time when the RUN button starts the real analysis - stacking the load
patterns and corrupting the reported reactions. The commands that belong to the
analysis stage are therefore replaced by inert stand-ins while the script runs, so
the script contributes the model, supports and loads while the application stays
in charge of when and how the structure is solved.
"""

import ast
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.features.model.importers.python_source import read_python_source

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


class AnalysisStageTracker:
    """Records whether the script has reached its analysis stage.

    Many scripts call ``wipe()`` again at the very end to free memory, after the model
    is already built and (suppressed) analysis commands have run. A collector watching
    this flag can tell that cleanup call apart from a genuine "start the model over"
    wipe that happens while nodes and elements are still being defined.
    """

    def __init__(self) -> None:
        self.started = False


class AnalysisStageSuppressor:
    """Swap the analysis-stage OpenSees commands for inert stand-ins."""

    def __init__(self) -> None:
        self._originals: dict[str, Callable[..., Any]] = {}

    def install(self, tracker: AnalysisStageTracker | None = None) -> None:
        for name in SUPPRESSED_COMMANDS:
            original = getattr(ops, name, None)
            if original is None or name in self._originals:
                continue
            self._originals[name] = original
            setattr(ops, name, self._tracked(_STAND_INS.get(name, _inert), tracker))

    def restore(self) -> None:
        for name, original in self._originals.items():
            setattr(ops, name, original)
        self._originals.clear()

    @staticmethod
    def _tracked(
        stand_in: Callable[..., Any], tracker: AnalysisStageTracker | None
    ) -> Callable[..., Any]:
        if tracker is None:
            return stand_in

        def wrapped(*arguments: Any, **keywords: Any) -> Any:
            tracker.started = True
            return stand_in(*arguments, **keywords)

        return wrapped


@contextmanager
def analysis_stage_suppressed(
    tracker: AnalysisStageTracker | None = None,
) -> Iterator[None]:
    suppressor = AnalysisStageSuppressor()
    suppressor.install(tracker)
    try:
        yield
    finally:
        suppressor.restore()


def run_model_script(source: Path, tracker: AnalysisStageTracker | None = None) -> None:
    """Build the model described by ``source`` without solving it.

    Full engineering scripts often validate recorder or ground-motion files before
    creating the OpenSees model. If that surrounding workflow fails, retry only the
    model-building portion instead of rejecting an otherwise readable structure.
    """
    effective_tracker = tracker or AnalysisStageTracker()
    with analysis_stage_suppressed(effective_tracker):
        try:
            _execute_source(source)
        except Exception as original_error:  # noqa: BLE001 - retry a safe model slice.
            if effective_tracker.started:
                # The model and loads are already complete. Errors in recorders,
                # dynamic inputs, or result-printing code do not invalidate import.
                return
            try:
                ops.wipe()
                run_model_definition_only(source)
            except Exception:  # noqa: BLE001 - preserve the user's original failure.
                raise original_error


def run_model_definition_only(source: Path) -> None:
    """Execute the model-building slice of a full analysis script.

    This fallback keeps imports and simple parameter assignments, starts at the last
    ``wipe()`` before ``model()``, and stops at the first analysis-stage command.
    """
    source_text = read_python_source(source)
    tree = ast.parse(source_text, filename=str(source))
    body = _model_body(tree)
    model_index = next(
        (index for index, statement in enumerate(body) if _calls_command(statement, {"model"})),
        None,
    )
    if model_index is None:
        raise RuntimeError("No ops.model() command was found.")

    start_index = model_index
    for index in range(model_index, -1, -1):
        if _calls_command(body[index], {"wipe"}):
            start_index = index
            break

    stop_index = len(body)
    for index in range(start_index + 1, len(body)):
        if _calls_command(body[index], set(SUPPRESSED_COMMANDS)):
            stop_index = index
            break

    module_prelude = [
        statement
        for statement in tree.body
        if isinstance(
            statement,
            (
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        )
    ]
    local_parameters = [
        statement
        for statement in body[:start_index]
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
    ]
    fallback_tree = ast.Module(
        body=[*module_prelude, *local_parameters, *body[start_index:stop_index]],
        type_ignores=[],
    )
    ast.fix_missing_locations(fallback_tree)
    namespace = {
        "__file__": str(source),
        "__name__": "__openframe_model_import__",
        "__package__": None,
    }
    exec(compile(fallback_tree, str(source), "exec"), namespace)  # noqa: S102


def _model_body(tree: ast.Module) -> list[ast.stmt]:
    top_level_commands = [
        statement
        for statement in tree.body
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if any(_calls_command(statement, {"model"}) for statement in top_level_commands):
        return tree.body
    for statement in ast.walk(tree):
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            _calls_command(child, {"model"}) for child in statement.body
        ):
            return statement.body
    raise RuntimeError("No function containing ops.model() was found.")


def _calls_command(statement: ast.AST, command_names: set[str]) -> bool:
    return any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in command_names
            or isinstance(node.func, ast.Name)
            and node.func.id in command_names
        )
        for node in ast.walk(statement)
    )


def _execute_source(source: Path) -> None:
    """Execute a Python model with tolerant source decoding and local imports."""
    source_text = read_python_source(source)
    namespace = {
        "__file__": str(source),
        "__name__": "__main__",
        "__package__": None,
        "__cached__": None,
    }
    source_directory = str(source.parent)
    inserted_path = not sys.path or sys.path[0] != source_directory
    if inserted_path:
        sys.path.insert(0, source_directory)
    try:
        exec(compile(source_text, str(source), "exec"), namespace)  # noqa: S102
    finally:
        if inserted_path:
            sys.path.remove(source_directory)
