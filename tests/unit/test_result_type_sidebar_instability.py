"""INSTABILITY section visibility on ResultTypeSidebar.

The section must only ever appear for AnalysisKind.LINEAR_STATIC, and only
once set_instability_available(True) has been called - never for any other
analysis kind regardless of the flag, and never by default.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind
from openframe.features.results.presentation.result_type_sidebar import ResultTypeSidebar


def _sidebar() -> ResultTypeSidebar:
    QApplication.instance() or QApplication([])
    return ResultTypeSidebar()


def test_instability_section_hidden_by_default() -> None:
    sidebar = _sidebar()
    assert sidebar.sections["instability"].isHidden()


def test_instability_section_visible_after_available_on_linear_static() -> None:
    sidebar = _sidebar()
    sidebar.set_analysis_kind(AnalysisKind.LINEAR_STATIC)
    sidebar.set_instability_available(True)
    assert not sidebar.sections["instability"].isHidden()


def test_instability_section_hidden_again_when_availability_cleared() -> None:
    sidebar = _sidebar()
    sidebar.set_analysis_kind(AnalysisKind.LINEAR_STATIC)
    sidebar.set_instability_available(True)
    sidebar.set_instability_available(False)
    assert sidebar.sections["instability"].isHidden()


def test_instability_section_never_shown_for_modal_even_if_available() -> None:
    sidebar = _sidebar()
    sidebar.set_instability_available(True)
    sidebar.set_analysis_kind(AnalysisKind.MODAL)
    assert sidebar.sections["instability"].isHidden()


def test_instability_section_never_shown_for_buckling_even_if_available() -> None:
    sidebar = _sidebar()
    sidebar.set_instability_available(True)
    sidebar.set_analysis_kind(AnalysisKind.BUCKLING)
    assert sidebar.sections["instability"].isHidden()


def test_switching_back_to_linear_static_restores_instability_section() -> None:
    sidebar = _sidebar()
    sidebar.set_analysis_kind(AnalysisKind.LINEAR_STATIC)
    sidebar.set_instability_available(True)
    sidebar.set_analysis_kind(AnalysisKind.MODAL)
    assert sidebar.sections["instability"].isHidden()

    sidebar.set_analysis_kind(AnalysisKind.LINEAR_STATIC)
    assert not sidebar.sections["instability"].isHidden()


def test_mechanism_modes_button_selectable_once_available() -> None:
    sidebar = _sidebar()
    sidebar.set_analysis_kind(AnalysisKind.LINEAR_STATIC)
    sidebar.set_instability_available(True)

    sidebar.select_result_type("mechanism_modes")
    assert sidebar.buttons["mechanism_modes"].isChecked()
