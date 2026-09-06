"""Contextual post-processing result navigation.

The active analysis kind decides which result families are visible.  Common
linear-static quantities therefore no longer compete with Modal, Buckling and
Time History entries in one long accordion list.
"""

from typing import ClassVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisKind, AnalysisResult, StructuralModel
from openframe.features.results.presentation.result_display_settings import ResultDisplaySettings


class _ResultSection(QFrame):
    """Always-open section heading plus its small set of result actions."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultTypeGroup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 5, 4, 6)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("resultTypeGroupTitle")
        layout.addWidget(self.title_label)

        self._buttons_layout = QVBoxLayout()
        self._buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._buttons_layout.setSpacing(1)
        layout.addLayout(self._buttons_layout)

    def add_button(self, button: QToolButton) -> None:
        self._buttons_layout.addWidget(button)


class ResultTypeSidebar(QFrame):
    result_type_changed = Signal(str)
    display_options_changed = Signal(object)

    _FORCE_RESULT_TYPES = frozenset({"axial", "shear", "moment"})
    _ANALYSIS_LABELS: ClassVar[dict[AnalysisKind, str]] = {
        AnalysisKind.LINEAR_STATIC: "LINEAR STATIC",
        AnalysisKind.NONLINEAR_STATIC: "NONLINEAR STATIC",
        AnalysisKind.MODAL: "MODAL",
        AnalysisKind.BUCKLING: "BUCKLING",
        AnalysisKind.TIME_HISTORY: "TIME HISTORY",
        AnalysisKind.RESPONSE_SPECTRUM: "RESPONSE SPECTRUM",
    }

    def __init__(
        self, parent: QWidget | None = None, *, compact_2d: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resultTypeSidebar")
        self._compact_2d = compact_2d
        self.setProperty("compact2d", compact_2d)
        self.setMinimumWidth(204 if compact_2d else 264)
        self.setMaximumWidth(232 if compact_2d else 300)
        self._analysis_kind = AnalysisKind.LINEAR_STATIC
        self._current_result_type = "overview"
        #: Set only by ResultsWorkspace.show_result() when a failed Linear
        #: Static result actually carries a detected mechanism - the
        #: "INSTABILITY" section stays hidden otherwise, and is never shown
        #: for any other analysis kind regardless of this flag.
        self._instability_available = False

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 8, 8)
        outer_layout.setSpacing(5)

        title = QLabel("Results")
        title.setObjectName("resultSectionTitle")
        outer_layout.addWidget(title)
        self.context_label = QLabel()
        self.context_label.setObjectName("resultContextLabel")
        outer_layout.addWidget(self.context_label)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("resultTypeScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer_layout.addWidget(self._scroll_area, 1)

        scroll_content = QWidget()
        scroll_content.setObjectName("resultTypeScrollContent")
        self._scroll_area.setWidget(scroll_content)
        self._sections_layout = QVBoxLayout(scroll_content)
        self._sections_layout.setContentsMargins(0, 2, 0, 0)
        self._sections_layout.setSpacing(4)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        self._sections_by_key: dict[str, _ResultSection] = {}
        self.sections: dict[str, _ResultSection] = {}

        self._build_sections()
        self.display_settings = ResultDisplaySettings()
        self.display_settings.set_dimension(2 if compact_2d else 3)
        self.display_settings.options_changed.connect(self.display_options_changed)
        self.display_settings.result_type_requested.connect(self.select_result_type)
        self._sections_layout.addWidget(self.display_settings)
        self._sections_layout.addStretch(1)
        self.set_analysis_kind(self._analysis_kind)

    def _build_sections(self) -> None:
        overview = self._add_section("overview", "OVERVIEW")
        self._add_button(overview, ("overview",), "Summary", "overview")

        visualization = self._add_section("visualization", "VISUALIZATION")
        self._add_button(
            visualization, ("deformation",), "Deformed Shape", "deformation"
        )
        self._add_button(
            visualization, ("displacement",), "Displacements", "displacement"
        )

        forces = self._add_section("forces", "FORCES")
        self._add_button(forces, ("reaction",), "Reactions", "reaction")
        self._add_button(
            forces,
            ("axial", "shear", "moment"),
            "Member Forces",
            "moment",
            force_diagram=True,
        )

        stress = self._add_section("stress", "STRESS")
        self._add_button(stress, ("stress",), "Stress Contour (σ)", "stress")

        nonlinear = self._add_section("nonlinear", "NONLINEAR RESPONSE")
        self._add_button(nonlinear, ("pushover",), "Pushover Curve", "pushover")

        modal = self._add_section("modal", "MODAL RESPONSE")
        self._add_button(modal, ("mode_shapes",), "Mode Shapes", "mode_shapes")

        buckling = self._add_section("buckling", "BUCKLING RESPONSE")
        self._add_button(
            buckling, ("buckling_modes",), "Buckling Modes", "buckling_modes"
        )

        time_history = self._add_section("time_history", "TIME HISTORY")
        self._add_button(
            time_history, ("time_history",), "Response History", "time_history"
        )

        data = self._add_section("data", "DATA")
        self._add_button(data, ("tables",), "Result Tables", "tables")

        instability = self._add_section("instability", "INSTABILITY")
        self._add_button(
            instability, ("mechanism_modes",), "Mechanism Shapes", "mechanism_modes"
        )

    def _add_section(self, key: str, title: str) -> _ResultSection:
        section = _ResultSection(title)
        self.sections[key] = section
        self._sections_layout.addWidget(section)
        return section

    def _add_button(
        self,
        section: _ResultSection,
        keys: tuple[str, ...],
        text: str,
        default_key: str,
        *,
        force_diagram: bool = False,
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName("resultTypeButton")
        button.setText(text)
        button.setCheckable(True)
        button.setProperty("forceDiagram", force_diagram)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(
            lambda checked=False, aliases=keys, fallback=default_key: (
                self._button_clicked(aliases, fallback)
            )
        )
        self._group.addButton(button)
        section.add_button(button)
        for key in keys:
            self.buttons[key] = button
            self._sections_by_key[key] = section
        return button

    def _button_clicked(self, aliases: tuple[str, ...], default_key: str) -> None:
        selected = (
            self._current_result_type
            if self._current_result_type in aliases
            else default_key
        )
        self._current_result_type = selected
        self.display_settings.set_result_type(selected)
        self.result_type_changed.emit(selected)

    def _visible_sections_for(self, kind: AnalysisKind) -> set[str]:
        common = {"overview", "visualization", "forces", "stress", "data"}
        visible_sections = {
            AnalysisKind.LINEAR_STATIC: common,
            AnalysisKind.RESPONSE_SPECTRUM: common,
            AnalysisKind.NONLINEAR_STATIC: common | {"nonlinear"},
            AnalysisKind.MODAL: {"modal", "data"},
            AnalysisKind.BUCKLING: {"buckling", "data"},
            AnalysisKind.TIME_HISTORY: {"time_history", "data"},
        }[kind]
        # "INSTABILITY" only ever joins the visible set for Linear Static, and
        # only once a failed result has actually diagnosed a mechanism - never
        # for Modal/Buckling/etc., regardless of the flag's value.
        if self._instability_available and kind == AnalysisKind.LINEAR_STATIC:
            visible_sections = visible_sections | {"instability"}
        return visible_sections

    def set_analysis_kind(self, kind: AnalysisKind) -> None:
        self._analysis_kind = kind
        self.context_label.setText(self._ANALYSIS_LABELS[kind])
        self._apply_visible_sections()

    def _apply_visible_sections(self) -> None:
        visible_sections = self._visible_sections_for(self._analysis_kind)
        for key, section in self.sections.items():
            section.setVisible(key in visible_sections)

        current_section = self._sections_by_key.get(self._current_result_type)
        if current_section is None or current_section.isHidden():
            default_result = {
                AnalysisKind.MODAL: "mode_shapes",
                AnalysisKind.BUCKLING: "buckling_modes",
                AnalysisKind.TIME_HISTORY: "time_history",
            }.get(self._analysis_kind, "overview")
            self.select_result_type(default_result)
        else:
            self.select_result_type(self._current_result_type)

    def set_instability_available(self, available: bool) -> None:
        """Show/hide the INSTABILITY section - called by ResultsWorkspace.show_result()
        with whether the current AnalysisResult actually diagnosed a mechanism."""
        if available == self._instability_available:
            return
        self._instability_available = available
        self._apply_visible_sections()

    def select_result_type(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is None:
            return
        self._current_result_type = key
        button.setChecked(True)
        self.display_settings.set_result_type(key)
        self.result_type_changed.emit(key)

    def set_model(self, model: StructuralModel) -> None:
        self.setMinimumWidth(264 if model.ndm == 3 else 204)
        self.setMaximumWidth(300 if model.ndm == 3 else 232)
        self.display_settings.set_model(model)

    def show_result(self, result: AnalysisResult) -> None:
        self.display_settings.show_result(result)

    def clear_result(self) -> None:
        self.display_settings.clear_result()

    def current_display_options(self):
        return self.display_settings.current_options()

    def visible_section_keys(self) -> tuple[str, ...]:
        return tuple(key for key, section in self.sections.items() if not section.isHidden())
