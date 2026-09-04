import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog

from openframe.app.shell.direct_model_workspace import DirectModelWorkspace
from openframe.core.domain import UnitSystem
from openframe.features.analysis.statics import MaterialFreeStaticsSolver
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    return ModelingInterfacePage()


def _build_sample_model(page: ModelingInterfacePage) -> None:
    """A model that exercises every field a save/load round-trip could drop:
    a trapezoidal element load, a hinge node, an embedded (mid-span) node, a
    non-default unit system, and a self-weight-bearing member. Not
    necessarily *stable* (the hinge plus only two supports leaves it a
    mechanism) - this builder is for data-fidelity checks only; the solve
    correctness test below uses its own, deliberately determinate model.
    """
    canvas = page.canvas
    left = canvas.add_node(0.0, 0.0)
    mid = canvas.add_node(4.0, 0.0)
    right = canvas.add_node(8.0, 0.0)
    beam = canvas.add_member(left, mid)
    canvas.add_member(mid, right)
    canvas.add_member_midpoint_node(beam)
    canvas.set_support(left, (True, True, False))
    canvas.set_support(right, (False, True, False))
    canvas.selected_elements = {beam}
    canvas.apply_uniform_load_to_selection((0.0, -5.0, 0.0, -15.0))
    canvas.selected_nodes = {mid}
    canvas.set_selected_node_kind(True)
    canvas.elements[beam].properties["A"] = 2.0
    canvas.elements[beam].properties["density"] = 1.0
    page.self_weight_toggle.setChecked(True)
    page.set_unit_system(UnitSystem(force="N", length="mm"))


def test_project_dict_round_trip_reproduces_identical_canvas_state() -> None:
    page = _page()
    _build_sample_model(page)

    data = json.loads(json.dumps(page.to_project_dict()))
    reloaded = _page()
    reloaded.load_project_dict(data)

    assert reloaded.canvas.nodes == page.canvas.nodes
    assert reloaded.canvas.elements == page.canvas.elements
    assert reloaded.canvas.boundaries == page.canvas.boundaries
    assert reloaded.canvas.element_loads == page.canvas.element_loads
    assert reloaded.canvas.hinge_nodes == page.canvas.hinge_nodes
    assert reloaded.canvas.embedded_nodes == page.canvas.embedded_nodes
    assert reloaded.canvas.include_self_weight == page.canvas.include_self_weight
    assert reloaded._unit_system == page._unit_system
    assert reloaded.truss_mode_toggle.isChecked() == page.truss_mode_toggle.isChecked()
    assert reloaded.self_weight_toggle.isChecked() == page.self_weight_toggle.isChecked()


def test_project_round_trip_solves_to_identical_reactions() -> None:
    """The correctness-critical check: a reloaded project must analyse to
    exactly the same numbers as the original, not just look the same. Uses a
    deliberately determinate model (unlike ``_build_sample_model``, whose
    hinge plus two supports is a mechanism) so the solve itself succeeds and
    the reactions are meaningful to compare."""
    page = _page()
    canvas = page.canvas
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    beam = canvas.add_member(left, right)
    canvas.set_support(left, (True, True, False))
    canvas.set_support(right, (False, True, False))
    canvas.selected_elements = {beam}
    canvas.apply_uniform_load_to_selection((0.0, -5.0, 0.0, -15.0))
    canvas.elements[beam].properties["A"] = 2.0
    canvas.elements[beam].properties["density"] = 1.0
    page.self_weight_toggle.setChecked(True)
    page.set_unit_system(UnitSystem(force="N", length="mm"))
    solver = MaterialFreeStaticsSolver()

    before = solver.solve(page.canvas.build_model())
    assert before.status.value == "completed"

    data = json.loads(json.dumps(page.to_project_dict()))
    reloaded = _page()
    reloaded.load_project_dict(data)
    after = solver.solve(reloaded.canvas.build_model())

    assert after.status.value == "completed"
    reactions_before = {tag: node.reaction for tag, node in before.node_results.items()}
    reactions_after = {tag: node.reaction for tag, node in after.node_results.items()}
    assert reactions_before == reactions_after


def test_save_and_load_from_an_actual_file_round_trips(tmp_path: Path) -> None:
    page = _page()
    _build_sample_model(page)
    path = tmp_path / "sample.ofsm"

    page.save_to_file(path)
    assert path.exists()

    reloaded = _page()
    reloaded.load_from_file(path)
    assert reloaded.canvas.nodes == page.canvas.nodes
    assert reloaded.canvas.elements == page.canvas.elements


def test_loading_a_project_with_only_the_required_fields_falls_back_to_defaults() -> None:
    """Forward/backward compatibility: a minimal project (e.g. one written by
    an older or trimmed-down version of the format) should still load using
    sane defaults for anything missing, not raise."""
    page = _page()
    minimal = {
        "ndm": 2,
        "nodes": [{"tag": 1, "x": 0.0, "y": 0.0}, {"tag": 2, "x": 4.0, "y": 0.0}],
        "elements": [
            {"tag": 1, "node_i": 1, "node_j": 2, "element_type": "frame"},
        ],
    }
    page.load_project_dict(minimal)
    assert len(page.canvas.nodes) == 2
    assert len(page.canvas.elements) == 1
    assert page.canvas.include_self_weight is False
    assert page.canvas.element_family == "frame"


def test_open_project_file_routes_2d_and_3d_projects_to_their_own_page(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()

    workspace.geometry_page.canvas.add_node(1.0, 2.0)
    path_2d = tmp_path / "flat.ofsm"
    workspace.geometry_page.save_to_file(path_2d)

    workspace.geometry_page_3d.canvas.add_node(1.0, 2.0)
    path_3d = tmp_path / "space.ofsm"
    workspace.geometry_page_3d.save_to_file(path_3d)

    fresh = DirectModelWorkspace()
    fresh.open_project_file(path_2d)
    assert fresh.stage_stack.currentWidget() is fresh.geometry_page
    assert len(fresh.geometry_page.canvas.nodes) == 1

    fresh.open_project_file(path_3d)
    assert fresh.stage_stack.currentWidget() is fresh.geometry_page_3d
    assert len(fresh.geometry_page_3d.canvas.nodes) == 1


def _fail_if_save_dialog(*_args, **_kwargs):
    raise AssertionError("save dialog should not open when a project path is already known")


def test_save_project_overwrites_the_opened_file_without_a_dialog(
    tmp_path: Path, monkeypatch
) -> None:
    """Ctrl+S / 저장 after Open (or a first Save As) must write the same
    .ofsm immediately. Re-prompting every time is what made the shortcut
    useless - the path is already known from open_project_file."""
    QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()
    path = tmp_path / "live.ofsm"
    workspace.geometry_page.canvas.add_node(1.0, 2.0)
    workspace.geometry_page.save_to_file(path)

    workspace.open_project_file(path)
    workspace.geometry_page.canvas.add_node(3.0, 4.0)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _fail_if_save_dialog)

    workspace._save_project()

    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert len(reloaded["nodes"]) == 2
    assert workspace._project_path == path.resolve()


def test_new_model_forgets_the_previous_save_path(tmp_path: Path, monkeypatch) -> None:
    """A New 2D/3D session must not keep writing into the last .ofsm - that
    would silently clobber a finished project the moment the user hits
    Ctrl+S on a blank canvas."""
    QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()
    path = tmp_path / "previous.ofsm"
    workspace.geometry_page.canvas.add_node(1.0, 2.0)
    workspace.geometry_page.save_to_file(path)
    workspace.open_project_file(path)

    workspace.start_2d_model()
    dialogs: list[object] = []

    def _cancel_dialog(*_args, **_kwargs):
        dialogs.append(True)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _cancel_dialog)
    workspace._save_project()

    assert dialogs
    assert json.loads(path.read_text(encoding="utf-8"))["nodes"]


def test_restoring_a_saved_session_keeps_the_file_path_for_ctrl_s(
    tmp_path: Path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()
    path = tmp_path / "resume.ofsm"
    workspace.geometry_page.canvas.add_node(1.0, 2.0)
    data = workspace.geometry_page.to_project_dict()
    workspace.geometry_page.save_to_file(path)

    workspace.restore_project(data, path=path)
    workspace.geometry_page.canvas.add_node(5.0, 6.0)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _fail_if_save_dialog)

    workspace._save_project()

    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert len(reloaded["nodes"]) == 2


def test_first_save_asks_for_a_path_and_later_saves_reuse_it(
    tmp_path: Path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()
    workspace.start_2d_model()
    workspace.geometry_page.canvas.add_node(1.0, 2.0)
    path = tmp_path / "first.ofsm"

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(path), "")
    )
    workspace._save_project()
    assert path.exists()
    assert workspace._project_path == path.resolve()

    workspace.geometry_page.canvas.add_node(3.0, 4.0)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _fail_if_save_dialog)
    workspace._save_project()

    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert len(reloaded["nodes"]) == 2
