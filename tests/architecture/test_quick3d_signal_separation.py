"""Architecture checks for Quick3D viewport signal separation (Phase P-1)."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "openframe"
    / "features"
    / "viewport"
    / "presentation"
    / "quick3d_scene_bridge.py"
)


def test_quick3d_bridge_declares_revision_signals() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    signal_names = {
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Signal"
    }
    required = {
        "topology_changed",
        "geometry_changed",
        "selection_changed",
        "preview_changed",
        "loads_changed",
        "visibility_changed",
    }
    missing = required - signal_names
    assert not missing, f"Quick3DSceneBridge missing signals: {sorted(missing)}"


def test_incremental_geometry_path_exists() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "_compute_topology_fingerprint" in source
    assert "_update_geometry_in_place" in source
    assert "geometryRevision" in source
