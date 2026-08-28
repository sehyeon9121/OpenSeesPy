"""Ensure modeling delegates bind transforms to geometryRevision."""

from __future__ import annotations

from pathlib import Path

QML = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "openframe"
    / "features"
    / "viewport"
    / "presentation"
    / "qml"
    / "structural_view.qml"
)

# Repeater blocks that must react to coordinate-only bridge updates.
_DELEGATES = (
    "sceneBridge.nodes",
    "sceneBridge.members",
    "sceneBridge.supportSymbols",
    "sceneBridge.selectedNodeHalo",
    "sceneBridge.loadArrows",
    "sceneBridge.loadEntryGlyphs",
    "sceneBridge.localAxisGizmos",
)


def test_geometry_revision_in_each_modeling_delegate_block() -> None:
    text = QML.read_text(encoding="utf-8")
    for model_binding in _DELEGATES:
        start = text.find(f"model: bridgeReady ? {model_binding}")
        assert start != -1, f"missing Repeater for {model_binding}"
        # Scan forward until the next Repeater3D block (or EOF).
        next_rep = text.find("Repeater3D {", start + 1)
        block = text[start:] if next_rep == -1 else text[start:next_rep]
        assert "geometryRevision" in block, f"{model_binding} block lacks geometryRevision binding"
