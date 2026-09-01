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


def test_member_cross_sections_use_model_unit_dimensions() -> None:
    text = QML.read_text(encoding="utf-8")
    assert "memberCrossSectionScale" not in text
    assert text.count("modelData.width_b / 100") == 3
    assert text.count("modelData.width_h / 100") == 3


def test_selected_member_highlight_changes_color_without_changing_section_size() -> None:
    text = QML.read_text(encoding="utf-8")
    start = text.index("model: bridgeReady ? sceneBridge.selectedMemberHighlight : []")
    end = text.index("Repeater3D {", start + 1)
    block = text[start:end]

    assert "* 1.35" not in block
    assert "modelData.width_b / 100" in block
    assert "modelData.width_h / 100" in block
    assert 'baseColor: "#ef4444"' in block


def test_nodes_have_a_depth_independent_screen_marker_and_pick_radius() -> None:
    text = QML.read_text(encoding="utf-8")

    assert 'objectName: "nodeMarkerOverlay"' in text
    assert "readonly property real nodeMarkerRadiusPixels: 8" in text
    assert "readonly property real selectedNodeMarkerRadiusPixels: 10" in text
    assert "readonly property real nodePickRadiusPixels: 18" in text
    assert "view3d.mapFrom3DScene(" in text
    assert "let bestDistance = root.nodePickRadiusPixels" in text
    assert "if (!root.nodeVisible(node.tag))" in text
    assert "onTrackedTimeHistoryShowDeformedChanged: schedulePaint()" in text


def test_middle_drag_has_orbit_and_shift_pan_cursor_feedback() -> None:
    text = QML.read_text(encoding="utf-8")
    start = text.index('objectName: "navigationCursorFeedback"')
    end = text.index('objectName: "viewportMouseArea"', start)
    feedback = text[start:end]

    assert "function drawOrbit(" in feedback
    assert "function drawPan(" in feedback
    assert 'fillText("360"' not in feedback
    assert "cursorShape: root.navigationActive ? Qt.BlankCursor : Qt.ArrowCursor" in text
    assert "root.panning = Boolean(mouse.modifiers & Qt.ShiftModifier)" in text
    assert "root.navigationActive = true" in text
    assert "root.navigationActive = false" in text
    assert "return view3d.pick(mx, my)" in text
