"""Worker process that executes one OpenSeesPy source and writes JSON output."""

import argparse
import json
import runpy
import traceback
from pathlib import Path

from openframe.infrastructure.opensees.model_collector import ModelCommandCollector


def collect_model(source: Path) -> dict[str, object]:
    collector = ModelCommandCollector()
    collector.install()
    runpy.run_path(str(source), run_name="__main__")
    return collector.to_payload()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    try:
        payload: dict[str, object] = {"ok": True, "model": collect_model(arguments.source)}
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
