"""End-to-end: 3D canvas -> Analysis tab -> Nonlinear Static (Pushover) ->
해석하기 actually solves now (see modeling_interface_page.py's
``_solve_nonlinear_static`` and solver.py's ``solve_nonlinear_static``/
``_build_plastic_hinge``). Numerical correctness of the lumped-plasticity
hinge itself is covered by
``tests/unit/test_material_free_statics_plastic_hinge.py`` (closed-form) -
this only checks the UI wiring: picking the method, staging settings the way
the dialog would, and clicking 해석하기 actually runs a real solve and
populates the results view, the same as Linear Static already does.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind, AnalysisStatus
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage

from _solve_helpers import solve_and_wait


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1280, 800)
    page.show()
    page._show_category("analysis")
    return page


def _build_steel_cantilever(page: ModelingInterfacePage) -> tuple[int, int]:
    base = page.canvas._add_node_at((0.0, 0.0, 0.0))
    tip = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(base, tip)

    page.canvas.selected_elements = {member}
    page.canvas.apply_full_section_to_selection(
        shape="Rectangle",
        source="custom",
        dimensions={"b": 0.2, "h": 0.4},
        area=0.08,
        iy=0.0002,
        iz=0.0002,
        j=0.0003,
        elastic=200000.0,
        density=0.0,
        fy=2000.0,
        strain_hardening_ratio=0.02,
        zy=1.0,
        zz=1.0,
    )

    page.canvas.selected_nodes = {base}
    page.canvas.apply_support_to_selection((True,) * 6)

    page.canvas.selected_nodes = {tip}
    page.canvas.apply_nodal_load_to_selection((0.0, 0.0, -750.0, 0.0, 0.0, 0.0))
    return base, tip


def test_clicking_해석하기_under_nonlinear_static_runs_a_real_pushover() -> None:
    page = _page()
    _base, tip = _build_steel_cantilever(page)

    index = page.analysis_method_selector.findData(AnalysisKind.NONLINEAR_STATIC.value)
    page.analysis_method_selector.setCurrentIndex(index)
    assert page.analysis_run_button.isEnabled() is True

    page._analysis_settings[AnalysisKind.NONLINEAR_STATIC.value] = {
        "control_node": tip,
        "control_dof": 3,
        "integrator_type": "LoadControl",
        "num_steps": 20,
        "tolerance": 1.0e-8,
        "max_iterations": 50,
    }

    solve_and_wait(page)

    assert page.view_results_button.isEnabled() is True
    assert tip in page.canvas.build_model().nodes


def test_clicking_해석하기_without_settings_reports_a_status_message_not_a_crash() -> None:
    page = _page()
    _build_steel_cantilever(page)
    index = page.analysis_method_selector.findData(AnalysisKind.NONLINEAR_STATIC.value)
    page.analysis_method_selector.setCurrentIndex(index)

    page.analysis_run_button.click()

    assert "설정" in page.determinacy_status.text()
    assert page._solve_thread is None
