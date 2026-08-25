"""Save/reload round trip for Story Manager (stories), elastic spring
supports (BoundaryCondition.spring_stiffnesses), and rigid end offsets
(Element.offset_i/offset_j) through StaticsDrawingCanvas.to_dict()/
load_dict() - and backward compatibility with a project file saved before
these fields existed."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.ndm = 3
    return canvas


def test_stories_round_trip_through_to_dict() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    canvas.add_story("2층", 3.0, rigid_diaphragm=True)

    fresh = _canvas()
    fresh.load_dict(canvas.to_dict())

    assert fresh.stories.keys() == {"1층", "2층"}
    assert fresh.stories["2층"].elevation == 3.0
    assert fresh.stories["2층"].rigid_diaphragm is True
    assert fresh.stories["1층"].rigid_diaphragm is False


def test_spring_support_round_trips() -> None:
    canvas = _canvas()
    node = canvas._add_node_at((0.0, 0.0, 0.0))
    canvas.selected_nodes = {node}
    canvas.apply_support_to_selection(
        (True, False, True, True, True, True), spring_stiffnesses=(None, 500.0, None, None, None, None)
    )

    fresh = _canvas()
    fresh.load_dict(canvas.to_dict())

    boundary = fresh.boundaries[node]
    assert boundary.spring_stiffnesses == (None, 500.0, None, None, None, None)
    assert boundary.restraints[1] is False


def test_rigid_offset_round_trips() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    canvas.selected_elements = {member}
    canvas.apply_rigid_offset_lengths_to_selection(0.2, 0.3)

    fresh = _canvas()
    fresh.load_dict(canvas.to_dict())

    element = fresh.elements[member]
    assert element.offset_i == pytest.approx((0.2, 0.0, 0.0))
    assert element.offset_j == pytest.approx((-0.3, 0.0, 0.0))


def test_load_dict_defaults_new_fields_for_a_pre_feature_project_file() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(a, b)
    canvas.selected_nodes = {a}
    canvas.apply_support_to_selection((True,) * 6)
    legacy_data = canvas.to_dict()
    legacy_data.pop("stories", None)
    for boundary in legacy_data["boundaries"]:
        boundary.pop("spring_stiffnesses", None)
    for element in legacy_data["elements"]:
        element.pop("offset_i", None)
        element.pop("offset_j", None)

    fresh = _canvas()
    fresh.load_dict(legacy_data)

    assert fresh.stories == {}
    assert fresh.boundaries[a].spring_stiffnesses == ()
    assert fresh.elements[member].offset_i == (0.0, 0.0, 0.0)
    assert fresh.elements[member].offset_j == (0.0, 0.0, 0.0)
