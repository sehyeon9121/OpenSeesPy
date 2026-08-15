"""Worker process that executes one OpenSeesPy source and writes JSON output."""

import argparse
import json
import os
import traceback
from collections.abc import Callable
from pathlib import Path

# Set before any user script gets a chance to `import matplotlib.pyplot`: this
# process has no display, so an uploaded script's own plt.show() would otherwise
# block waiting for an interactive backend instead of being a harmless no-op.
os.environ.setdefault("MPLBACKEND", "Agg")

import openseespy.opensees as ops

from openframe.infrastructure.opensees.buckling_solver import run_buckling_analysis
from openframe.infrastructure.opensees.linear_static_solver import run_linear_static_analysis
from openframe.infrastructure.opensees.modal_solver import run_modal_analysis
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.nonlinear_static_solver import (
    run_nonlinear_static_analysis,
)
from openframe.infrastructure.opensees.script_execution import (
    AnalysisStageTracker,
    run_model_definition_only,
    run_model_script,
)
from openframe.infrastructure.opensees.time_history_solver import run_time_history_analysis


def collect_model(source: Path) -> dict[str, object]:
    """Read the model out of ``source``. Importing a file never solves it."""
    tracker = AnalysisStageTracker()
    collector = ModelCommandCollector()
    collector.install(tracker)
    try:
        run_model_script(source, tracker)
        if not collector.nodes or not collector.elements:
            tracker.started = False
            ops.wipe()
            run_model_definition_only(source)
        return collector.to_payload()
    finally:
        collector.restore()


def _progress_writer(path: Path | None) -> Callable[[int | None, str], None] | None:
    if path is None:
        return None

    def write(value: int | None, stage: str) -> None:
        # A partially-read JSON update is harmless (the runner retries on its next
        # poll); direct writes avoid Windows replace failures if the runner happens
        # to have the previous update open at the same instant.
        path.write_text(
            json.dumps({"value": value, "stage": stage}, ensure_ascii=False),
            encoding="utf-8",
        )

    return write


def run_analysis(
    source: Path,
    kind: str,
    options: dict[str, object],
    progress_callback: Callable[[int | None, str], None] | None = None,
) -> dict[str, object]:
    if kind == "nonlinear_static":
        return run_nonlinear_static_analysis(
            source,
            **options,
            progress_callback=progress_callback,
        )
    if kind == "modal":
        return run_modal_analysis(source, **options)
    if kind == "buckling":
        return run_buckling_analysis(source, **options)
    if kind == "time_history":
        time_history_options = dict(options)
        # Each direction's "path" arrives as a JSON string (round-tripped
        # through AnalysisRequest.options -> subprocess --options) - the
        # solver itself works with Path objects, same as every other kind's
        # source path.
        time_history_options["directions"] = [
            {**direction, "path": Path(direction["path"])}
            for direction in time_history_options.get("directions", [])
        ]
        return run_time_history_analysis(
            source,
            **time_history_options,
            progress_callback=progress_callback,
        )
    return run_linear_static_analysis(source)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("model", "analysis"), default="model")
    parser.add_argument("--kind", default="linear_static")
    parser.add_argument("--options", default="{}")
    parser.add_argument("--progress", type=Path)
    arguments = parser.parse_args()

    try:
        if arguments.mode == "model":
            payload: dict[str, object] = {"ok": True, "model": collect_model(arguments.source)}
        else:
            options = json.loads(arguments.options)
            payload = {
                "ok": True,
                "results": run_analysis(
                    arguments.source,
                    arguments.kind,
                    options,
                    _progress_writer(arguments.progress),
                ),
            }
        exit_code = 0
    except BaseException as error:  # noqa: BLE001 - user-script failures become JSON data.
        payload = {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(limit=8),
        }
        exit_code = 1

    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
