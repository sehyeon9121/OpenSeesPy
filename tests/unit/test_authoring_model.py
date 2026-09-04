"""Authoring refresh must not pay analysis-mesh cost on every click.

``build_model()`` splits members at embedded nodes and synthesises
self-weight/point-load segments for OpenSees. Status and the 3D preview
used to call it on every ``model_changed`` (twice in 3D). They now use
``authoring_model()`` — the drawn geometry — and ``build_model()`` stays
on the solve/export path.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_authoring_model_keeps_the_drawn_member_when_build_model_splits() -> None:
    canvas = _canvas()
    left = canvas.add_node(0.0, 0.0)
    middle = canvas.add_node(2.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    canvas.add_member(left, right)

    authoring = canvas.authoring_model()
    analysis = canvas.build_model()

    assert len(canvas.elements) == 1
    assert canvas.embedded_nodes[middle] == (next(iter(canvas.elements)), 0.5)
    assert len(authoring.elements) == 1
    assert set(authoring.elements) == set(canvas.elements)
    assert len(analysis.elements) == 2


def test_status_and_3d_preview_do_not_call_build_model_while_drawing() -> None:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    calls = {"n": 0}
    original = page.canvas.build_model

    def wrapped() -> object:
        calls["n"] += 1
        return original()

    page.canvas.build_model = wrapped  # type: ignore[method-assign]
    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(3.0, 0.0)
    page.canvas.add_member(a, b)

    assert calls["n"] == 0
    assert "부재 1" in page.model_status.text()
    assert "노드 2" in page.model_status.text()
