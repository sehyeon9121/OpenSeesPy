"""Story Manager CRUD + auto-detect (canvas_stories.py) and its wiring into
build_model()'s rigid_diaphragms (canvas_model_build.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas(ndm: int = 3) -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.ndm = ndm
    return canvas


def test_add_story_refuses_a_duplicate_name() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    assert canvas.add_story("1층", 3.0) is None
    assert len(canvas.stories) == 1


def test_update_story_can_rename_and_toggle_the_diaphragm() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)

    assert canvas.update_story("1층", name="지상1층", rigid_diaphragm=True)

    assert "1층" not in canvas.stories
    story = canvas.stories["지상1층"]
    assert story.rigid_diaphragm is True
    assert story.elevation == 0.0


def test_delete_story_removes_it() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    canvas.delete_story("1층")
    assert canvas.stories == {}


def test_nodes_at_story_matches_by_z_proximity() -> None:
    canvas = _canvas()
    n1 = canvas._add_node_at((0.0, 0.0, 3.0))
    n2 = canvas._add_node_at((4.0, 0.0, 3.0))
    canvas._add_node_at((0.0, 0.0, 0.0))  # a different level
    canvas.add_story("2층", 3.0)

    assert canvas.nodes_at_story("2층") == tuple(sorted((n1, n2)))


def test_auto_detect_stories_groups_nodes_by_elevation_with_korean_names() -> None:
    canvas = _canvas()
    canvas._add_node_at((0.0, 0.0, 0.0))
    canvas._add_node_at((4.0, 0.0, 0.0))
    canvas._add_node_at((0.0, 0.0, 3.0))
    canvas._add_node_at((0.0, 0.0, 6.0))
    canvas._add_node_at((0.0, 0.0, -3.0))

    created = canvas.auto_detect_stories()

    assert set(created) == {"1층", "2층", "3층", "지하1층"}
    assert canvas.stories["1층"].elevation == 0.0
    assert canvas.stories["2층"].elevation == 3.0
    assert canvas.stories["3층"].elevation == 6.0
    assert canvas.stories["지하1층"].elevation == -3.0


def test_auto_detect_stories_skips_elevations_already_covered() -> None:
    canvas = _canvas()
    canvas._add_node_at((0.0, 0.0, 0.0))
    canvas._add_node_at((0.0, 0.0, 3.0))
    canvas.add_story("바닥", 0.0)

    created = canvas.auto_detect_stories()

    assert created == ["1층"]
    assert canvas.stories["1층"].elevation == 3.0
    assert "바닥" in canvas.stories


def test_auto_detect_stories_is_a_noop_for_2d_models() -> None:
    canvas = _canvas(ndm=2)
    canvas.add_node(0.0, 0.0)

    assert canvas.auto_detect_stories() == []
    assert canvas.stories == {}


def test_build_model_ties_a_rigid_diaphragm_story_together() -> None:
    canvas = _canvas()
    n1 = canvas._add_node_at((0.0, 0.0, 3.0))
    n2 = canvas._add_node_at((4.0, 0.0, 3.0))
    canvas.add_story("2층", 3.0, rigid_diaphragm=True)

    model = canvas.build_model()

    assert len(model.rigid_diaphragms) == 1
    diaphragm = model.rigid_diaphragms[0]
    assert diaphragm.perp_dirn == 3
    assert diaphragm.master_tag == min(n1, n2)
    assert set(diaphragm.slave_tags) == {n1, n2} - {diaphragm.master_tag}


def test_build_model_skips_a_story_with_the_diaphragm_off() -> None:
    canvas = _canvas()
    canvas._add_node_at((0.0, 0.0, 3.0))
    canvas._add_node_at((4.0, 0.0, 3.0))
    canvas.add_story("2층", 3.0, rigid_diaphragm=False)

    model = canvas.build_model()

    assert model.rigid_diaphragms == ()


def test_build_model_skips_a_diaphragm_story_with_fewer_than_two_nodes() -> None:
    canvas = _canvas()
    canvas._add_node_at((0.0, 0.0, 3.0))
    canvas.add_story("2층", 3.0, rigid_diaphragm=True)

    model = canvas.build_model()

    assert model.rigid_diaphragms == ()
