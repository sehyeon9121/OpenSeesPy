"""Worker process that executes one OpenSeesPy source and writes JSON output."""

import argparse
import json
import traceback
from pathlib import Path

from openframe.infrastructure.opensees.linear_static_solver import run_linear_static_analysis
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import (
    AnalysisStageTracker,
    run_model_script,
)


def collect_model(source: Path) -> dict[str, object]:
    """Read the model out of ``source``. Importing a file never solves it."""
    tracker = AnalysisStageTracker()
    collector = ModelCommandCollector()
    collector.install(tracker)
    run_model_script(source, tracker)
    return collector.to_payload()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("model", "analysis"), default="model")
    arguments = parser.parse_args()

    try:
        if arguments.mode == "model":
            payload: dict[str, object] = {"ok": True, "model": collect_model(arguments.source)}
        else:
            payload = {"ok": True, "results": run_linear_static_analysis(arguments.source)}
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
