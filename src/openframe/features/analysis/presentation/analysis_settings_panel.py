"""Analysis type and solver settings panel."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisKind, StructuralModel

#: DOF labels by ndm, matching the order OpenSeesPy reports node results in.
_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")


class AnalysisSettingsPanel(QFrame):
    analysis_kind_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisSettingsPanel")
        self._model: StructuralModel | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("ANALYSIS SETTINGS"))

        settings = QFrame()
        settings.setObjectName("rightSection")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(14, 12, 14, 14)
        settings_layout.setSpacing(7)

        settings_layout.addWidget(self._field_label("ANALYSIS TYPE"))
        self.analysis_type = QComboBox()
        self.analysis_type.addItem("Linear Static", AnalysisKind.LINEAR_STATIC)
        self.analysis_type.addItem("Nonlinear Static", AnalysisKind.NONLINEAR_STATIC)
        self.analysis_type.addItem("Time History", AnalysisKind.TIME_HISTORY)
        self.analysis_type.currentIndexChanged.connect(self._analysis_type_changed)
        settings_layout.addWidget(self.analysis_type)

        settings_layout.addWidget(self._field_label("SOLVER"))
        self.solver = QComboBox()
        self.solver.addItems(("BandGeneral", "UmfPack", "ProfileSPD"))
        settings_layout.addWidget(self.solver)

        self.nonlinear_group = QFrame()
        nonlinear_layout = QVBoxLayout(self.nonlinear_group)
        nonlinear_layout.setContentsMargins(0, 0, 0, 0)
        nonlinear_layout.setSpacing(7)

        nonlinear_layout.addWidget(self._field_label("CONTROL NODE"))
        self.control_node = QComboBox()
        nonlinear_layout.addWidget(self.control_node)

        nonlinear_layout.addWidget(self._field_label("CONTROL DOF"))
        self.control_dof = QComboBox()
        nonlinear_layout.addWidget(self.control_dof)

        nonlinear_layout.addWidget(self._field_label("LOAD STEPS"))
        self.num_steps = QSpinBox()
        self.num_steps.setRange(1, 1000)
        self.num_steps.setValue(10)
        nonlinear_layout.addWidget(self.num_steps)

        nonlinear_layout.addWidget(self._field_label("TOLERANCE"))
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setDecimals(8)
        self.tolerance.setRange(1.0e-10, 1.0)
        self.tolerance.setSingleStep(1.0e-7)
        self.tolerance.setValue(1.0e-6)
        nonlinear_layout.addWidget(self.tolerance)

        nonlinear_layout.addWidget(self._field_label("MAX ITERATIONS"))
        self.max_iterations = QSpinBox()
        self.max_iterations.setRange(1, 1000)
        self.max_iterations.setValue(25)
        nonlinear_layout.addWidget(self.max_iterations)

        nonlinear_layout.addWidget(self._field_label("ALGORITHM"))
        self.algorithm = QComboBox()
        self.algorithm.addItems(
            ("Newton", "ModifiedNewton", "KrylovNewton", "NewtonLineSearch")
        )
        nonlinear_layout.addWidget(self.algorithm)

        nonlinear_layout.addWidget(self._field_label("CONVERGENCE TEST"))
        self.test_type = QComboBox()
        self.test_type.addItems(("NormDispIncr", "EnergyIncr", "NormUnbalance"))
        nonlinear_layout.addWidget(self.test_type)

        settings_layout.addWidget(self.nonlinear_group)
        settings_layout.addStretch(1)

        # The nonlinear fields push this panel's natural height well past what the
        # sidebar has room for; without a scroll area, Qt has to shrink the layout
        # below its rows' minimum sizes to fit, and labels/fields start overlapping
        # instead of the rest of the sidebar (e.g. the model inspector below it)
        # simply getting a scrollbar-bounded panel above it instead.
        scroll_area = QScrollArea()
        scroll_area.setObjectName("analysisSettingsScrollArea")
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Without a floor, the sidebar's layout (model inspector below has the only
        # stretch factor) squeezes this down to a sliver - just the header, no room
        # to actually see or use a field. This guarantees several rows stay visible
        # before the panel starts scrolling, in both linear and nonlinear modes.
        scroll_area.setMinimumHeight(230)
        scroll_area.setWidget(settings)
        layout.addWidget(scroll_area, 1)

        self._update_nonlinear_visibility()

    def set_model(self, model: StructuralModel | None) -> None:
        self._model = model
        self.control_node.clear()
        if model is None:
            return
        for tag, node in sorted(model.nodes.items()):
            coordinates = (
                f"({node.x:g}, {node.y:g}, {node.z:g})"
                if model.ndm == 3
                else f"({node.x:g}, {node.y:g})"
            )
            self.control_node.addItem(f"Node {tag} {coordinates}", tag)

        self.control_dof.clear()
        labels = _DOF_LABELS_3D if model.ndm == 3 else _DOF_LABELS_2D
        for index, label in enumerate(labels, start=1):
            self.control_dof.addItem(label, index)

    def selected_analysis_kind(self) -> AnalysisKind:
        return AnalysisKind(self.analysis_type.currentData())

    def build_options(self) -> dict[str, float | int | str | bool]:
        """Return the settings this panel controls, in the shape
        ``run_nonlinear_static_analysis`` (and its worker.py/runner.py plumbing)
        expects. Only meaningful when ``selected_analysis_kind()`` is nonlinear
        static; other analysis kinds ignore ``AnalysisRequest.options`` entirely."""
        options: dict[str, float | int | str | bool] = {
            "system": self.solver.currentText(),
            "num_steps": self.num_steps.value(),
            "tolerance": self.tolerance.value(),
            "max_iterations": self.max_iterations.value(),
            "algorithm": self.algorithm.currentText(),
            "test_type": self.test_type.currentText(),
        }
        control_node = self.control_node.currentData()
        if control_node is not None:
            options["control_node"] = int(control_node)
        control_dof = self.control_dof.currentData()
        if control_dof is not None:
            options["control_dof"] = int(control_dof)
        return options

    def _analysis_type_changed(self) -> None:
        self._update_nonlinear_visibility()
        self.analysis_kind_changed.emit(self.selected_analysis_kind())

    def _update_nonlinear_visibility(self) -> None:
        self.nonlinear_group.setVisible(
            self.selected_analysis_kind() == AnalysisKind.NONLINEAR_STATIC
        )

    def _header(self, text: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panelHeader")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.addWidget(QLabel(text))
        return frame

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label
