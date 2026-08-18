import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.core.domain import AnalysisKind
from openframe.features.templates.catalog import load_template_catalog


def _window() -> MainWindow:
    QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    return window


_CANVAS_TEMPLATE_IDS = ["simple_beam", "three_hinge_arch", "simple_truss"]
_PRECISION_TEMPLATE_IDS = ["euler_buckling_column"]


def test_the_bundled_manifest_lists_every_template_with_readable_files() -> None:
    """Guards the packaging side, not just the catalog parser: every entry's
    ``path`` must actually resolve to an ``.ofsm`` file on disk (the same
    file ``pyproject.toml``'s package-data glob is responsible for shipping),
    and that file must parse as the canvas's own project-file format."""
    entries = load_template_catalog()
    assert [entry.id for entry in entries] == _CANVAS_TEMPLATE_IDS + _PRECISION_TEMPLATE_IDS
    for entry in entries:
        assert entry.path.exists(), f"{entry.id}: {entry.path} missing"
        data = json.loads(entry.path.read_text(encoding="utf-8"))
        assert data["format"] == "openframe-canvas"
        assert data["nodes"], f"{entry.id}: template has no nodes"
        assert entry.title and entry.hint
    canvas_entries = {e.id: e for e in entries if e.id in _CANVAS_TEMPLATE_IDS}
    for entry in canvas_entries.values():
        assert entry.analysis_kind is None
    precision_entries = {e.id: e for e in entries if e.id in _PRECISION_TEMPLATE_IDS}
    assert precision_entries["euler_buckling_column"].analysis_kind == "buckling"
    assert precision_entries["euler_buckling_column"].analysis_options == {"num_modes": 1}


def test_clicking_templates_on_the_home_hub_opens_the_gallery() -> None:
    window = _window()

    window.start_workspace.template_button.click()

    assert window.workspace_stack.currentWidget() is window.template_gallery_page
    assert len(window.template_gallery_page._entries) == 4


def test_the_galerys_back_button_returns_to_the_home_hub() -> None:
    window = _window()
    window.start_workspace.template_button.click()

    window.template_gallery_page.back_requested.emit()

    assert window.workspace_stack.currentWidget() is window.start_workspace


@pytest.mark.parametrize(
    "template_id,expected_nodes,expected_elements",
    [
        ("simple_beam", 2, 1),
        ("three_hinge_arch", 5, 4),
        ("simple_truss", 3, 3),
    ],
)
def test_opening_a_template_loads_its_geometry_onto_the_canvas(
    template_id: str, expected_nodes: int, expected_elements: int
) -> None:
    """Every bundled template must actually reach the canvas through the
    same ``open_project_dict`` path a user's own saved project takes - not
    just parse as valid JSON."""
    window = _window()
    entry = next(e for e in load_template_catalog() if e.id == template_id)
    data = json.loads(entry.path.read_text(encoding="utf-8"))

    window.template_gallery_page.template_opened.emit(data, entry)

    assert window.workspace_stack.currentWidget() is window.direct_model_workspace
    page = window.direct_model_workspace.geometry_page
    assert len(page.canvas.nodes) == expected_nodes
    assert len(page.canvas.elements) == expected_elements


@pytest.mark.parametrize("template_id", ["simple_beam", "three_hinge_arch", "simple_truss"])
def test_every_template_is_determinate_and_solves_without_material(template_id: str) -> None:
    """A template that fails on the very first click of its own solve button
    would be worse than no template - each one is meant to be openable and
    immediately solvable, exactly as its own manifest ``hint`` promises."""
    entry = next(e for e in load_template_catalog() if e.id == template_id)
    data = json.loads(entry.path.read_text(encoding="utf-8"))
    window = _window()

    window.template_gallery_page.template_opened.emit(data, entry)
    page = window.direct_model_workspace.geometry_page
    model = page.canvas.build_model()

    from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy

    check = check_determinacy(model)
    assert "정정" in check.message
    result = MaterialFreeStaticsSolver().solve(model)
    assert result.status.value == "completed"


def _window_with_import_service() -> MainWindow:
    """Only the precision-template path needs this - it goes through
    ``_start_model_load``, which pops a *blocking* ``QMessageBox.critical``
    (no ``open_model_service`` = nothing to load with) that hangs forever in
    an offscreen test with nobody to click it away. Every canvas-template
    test above never touches that code path, so ``_window()`` (no service)
    is correct there."""
    from openframe.features.model.application.open_model import OpenModelService
    from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

    QApplication.instance() or QApplication([])
    window = MainWindow(
        open_model_service=OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    )
    window.resize(1280, 800)
    window.show()
    return window


def _run_precision_template_to_completion(window: MainWindow, data: dict, entry) -> None:
    """Emits ``template_opened`` and pumps a bounded event loop until the
    background import thread ``_start_model_load`` kicked off actually
    finishes - every precision-template test needs this drain, not just the
    one checking the final SETUP state, or the thread outlives the test and
    can fire its completion signals against an already-torn-down window."""
    from PySide6.QtCore import QEventLoop, QTimer

    window.template_gallery_page.template_opened.emit(data, entry)
    thread = window._model_load_thread
    assert thread is not None, "precision template did not start a load thread"
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    QApplication.instance().processEvents()


def test_opening_the_buckling_template_exports_a_script_and_stages_the_preset() -> None:
    """The precision path never touches the canvas workspace at all - it
    exports straight to a script and queues the analysis preset for
    ``_model_loaded`` to apply once the import thread finishes."""
    entry = next(e for e in load_template_catalog() if e.id == "euler_buckling_column")
    data = json.loads(entry.path.read_text(encoding="utf-8"))
    window = _window_with_import_service()

    # _pending_analysis_preset is staged synchronously, before the thread
    # even starts - check it right after emit, before draining the thread.
    window.template_gallery_page.template_opened.emit(data, entry)
    assert window._pending_analysis_preset is not None
    kind, options, hint = window._pending_analysis_preset
    assert kind == AnalysisKind.BUCKLING
    assert options == {"num_modes": 1}
    assert hint == entry.hint
    # Went through the OpenSeesPy import pipeline, not the canvas one - the
    # direct_model_workspace's canvas must stay untouched.
    assert len(window.direct_model_workspace.geometry_page.canvas.nodes) == 0

    thread = window._model_load_thread
    assert thread is not None
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    window.close()


def test_opening_the_buckling_template_lands_on_setup_with_buckling_preselected() -> None:
    """End-to-end through the real import pipeline (OpenModelService parsing
    the generated script, same as test_model_load_ui.py's own pattern) -
    proves the preset survives the async round trip and actually reaches
    the SETUP widgets a user would see, not just the config store."""
    entry = next(e for e in load_template_catalog() if e.id == "euler_buckling_column")
    data = json.loads(entry.path.read_text(encoding="utf-8"))
    window = _window_with_import_service()

    _run_precision_template_to_completion(window, data, entry)

    assert window._pending_analysis_preset is None
    assert window.workspace_stack.currentWidget() is window.setup_workspace
    assert window.analysis_settings.selected_analysis_kind() == AnalysisKind.BUCKLING
    assert window.analysis_settings.buckling_num_modes.value() == 1
    assert window.config_store.kind == AnalysisKind.BUCKLING
    window.close()


def test_the_buckling_template_matches_the_euler_closed_form() -> None:
    """The template's own geometry/section/load must still converge to
    Pcr = pi^2 * E * I / L^2 for a pinned-pinned column - the same guarantee
    test_buckling_solver.py's Euler column already proves for the solver
    itself, checked here against this specific bundled file so a future
    edit to the template can't silently drift from the closed form.

    Exports the script directly (no MainWindow/UI trip needed - the export
    step is plain, synchronous code) so this test is independent of the
    precision-template pipeline's own async plumbing, covered separately
    above."""
    import tempfile
    from pathlib import Path

    from openframe.features.analysis.statics import export_opensees_script
    from openframe.features.model.presentation.statics_modeling_page import (
        StaticsDrawingCanvas,
    )
    from openframe.infrastructure.opensees.buckling_solver import run_buckling_analysis

    entry = next(e for e in load_template_catalog() if e.id == "euler_buckling_column")
    data = json.loads(entry.path.read_text(encoding="utf-8"))
    node = next(n for n in data["nodes"] if n["y"] == max(n["y"] for n in data["nodes"]))
    base_node = next(n for n in data["nodes"] if n["y"] == 0.0)
    element = next(e for e in data["elements"] if e["properties"])
    props = element["properties"]
    length = node["y"] - base_node["y"]
    pcr_closed_form = math.pi**2 * props["E"] * props["I"] / length**2

    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.load_dict(data)
    model = canvas.build_model()
    script = export_opensees_script(model, include_mass=False, length_unit="m")
    script_path = Path(tempfile.gettempdir()) / f"{entry.id}_closed_form_check.py"
    script_path.write_text(script, encoding="utf-8")

    result = run_buckling_analysis(script_path, num_modes=1, geometric_transform_type="PDelta")
    assert result["status"] == "completed"
    pcr_fe = result["buckling_modes"][0]["buckling_load_factor"]
    assert pcr_fe == pytest.approx(pcr_closed_form, rel=0.01)
