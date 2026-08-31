"""Builds the Windows installer "payload" - a self-contained folder holding a
real Python interpreter (the official python.org embeddable distribution)
plus this project and all its runtime dependencies already `pip install`-ed
into it.

Why not PyInstaller: this app relaunches itself as a subprocess for every
precision analysis (`infrastructure/opensees/runner.py`,
`model_importer.py`: ``[sys.executable, "-m",
"openframe.infrastructure.opensees.worker", ...]``), and also imports
openseespy directly inside the main GUI process (2D free-modeling's
determinacy solve, `features/analysis/statics/solver.py`). Both only work
because ``sys.executable`` is a genuine Python interpreter that understands
``-m``, not a frozen single-purpose exe - so this ships a real interpreter
instead of trying to freeze one. See `installer/README.md` for the full
rationale and the Inno Setup step this feeds into.

Usage::

    .venv\\Scripts\\python.exe scripts\\build_windows_payload.py

Produces ``build/payload/`` - not committed to git (see .gitignore's
``build/`` entry). Safe to rerun: deletes and rebuilds the target
site-packages each time, so it never accumulates stale packages from a
previous run.

Also cleans ``build/lib`` and ``build/bdist.*`` before installing - pip
defaults to an "in-tree build" for local directory installs (PEP 517,
pip>=21.3), so `setuptools` stages the wheel's files under this project's
own ``build/lib`` rather than a throwaway temp dir. setuptools only ever
*adds/overwrites* files there, never removes ones deleted from source since
the last build, so a stale ``build/lib`` silently leaks removed
package-data (an old template's ``.ofsm``, a since-deleted ground-motion
``.AT2``, ...) into every wheel built afterward unless it's wiped first.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = REPO_ROOT / "build"
PAYLOAD_DIR = BUILD_DIR / "payload"

PYTHON_VERSION = "3.12.7"
EMBED_ZIP_NAME = f"python-{PYTHON_VERSION}-embed-amd64.zip"
EMBED_ZIP_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{EMBED_ZIP_NAME}"
EMBED_ZIP_PATH = BUILD_DIR / EMBED_ZIP_NAME

#: The embeddable distribution ships python312._pth with site-packages
#: disabled and pip absent by design (see python.org's own docs on the
#: embeddable package) - this is the exact rewrite needed to make a
#: `pip install --target` payload importable at runtime.
PTH_CONTENT = "python312.zip\n.\nLib\\site-packages\n\nimport site\n"


def _download_embeddable_python() -> None:
    if EMBED_ZIP_PATH.exists():
        print(f"Using cached {EMBED_ZIP_PATH}")
        return
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {EMBED_ZIP_URL} ...")
    urllib.request.urlretrieve(EMBED_ZIP_URL, EMBED_ZIP_PATH)


def _extract_embeddable_python() -> None:
    if PAYLOAD_DIR.exists():
        shutil.rmtree(PAYLOAD_DIR)
    PAYLOAD_DIR.mkdir(parents=True)
    with zipfile.ZipFile(EMBED_ZIP_PATH) as archive:
        archive.extractall(PAYLOAD_DIR)
    pth_path = PAYLOAD_DIR / "python312._pth"
    pth_path.write_text(PTH_CONTENT, encoding="utf-8")


def _clean_stale_setuptools_build_artifacts() -> None:
    """Removes leftover in-tree build staging dirs from earlier runs - see
    the module docstring for why a stale one silently ships deleted files."""
    for name in ("lib", "bdist.win-amd64"):
        stale_dir = BUILD_DIR / name
        if stale_dir.exists():
            shutil.rmtree(stale_dir)


def _install_dependencies() -> None:
    _clean_stale_setuptools_build_artifacts()
    site_packages = PAYLOAD_DIR / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    # Uses *this* interpreter's own pip (the dev .venv) to resolve and
    # install into the payload's site-packages - the payload's own
    # python.exe never needs pip present at runtime, only at build time here.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(site_packages),
            "--no-warn-script-location",
            str(REPO_ROOT),
        ],
        check=True,
    )
    _verify_bundled_ground_motions(site_packages)


#: Matches ``test_ground_motion_catalog.py``'s assertion and the PEER
#: records under ``infrastructure/ground_motions/data/``. A payload with
#: fewer files produces an empty Built-in picker in the installed app,
#: which looks identical to "the installer dropped the earthquake data".
_EXPECTED_GROUND_MOTION_COUNT = 65


def _verify_bundled_ground_motions(site_packages: Path) -> None:
    """Fail the payload build if pip omitted the bundled .AT2 records.

    ``pyproject.toml`` already lists them in package-data, but a stale
    ``build/lib``, a missed glob, or an incomplete wheel still produces a
    runnable ``pythonw.exe -m openframe`` whose Built-in catalog is empty.
    Catch that here rather than after Inno Setup has already packaged it.
    """
    data_dir = (
        site_packages / "openframe" / "infrastructure" / "ground_motions" / "data"
    )
    at2_files = sorted(data_dir.glob("*.AT2")) if data_dir.is_dir() else []
    if len(at2_files) < _EXPECTED_GROUND_MOTION_COUNT:
        raise SystemExit(
            "Payload is missing built-in ground-motion records: "
            f"found {len(at2_files)} .AT2 files in {data_dir}, "
            f"expected {_EXPECTED_GROUND_MOTION_COUNT}. "
            "Refusing to produce an installer that would open the "
            "Built-in picker empty."
        )
    print(f"Bundled ground motions: {len(at2_files)} .AT2 files")


def main() -> None:
    _download_embeddable_python()
    _extract_embeddable_python()
    _install_dependencies()
    print(f"Payload ready at {PAYLOAD_DIR}")
    print(f'Smoke test: "{PAYLOAD_DIR / "python.exe"}" -m openframe')


if __name__ == "__main__":
    main()
