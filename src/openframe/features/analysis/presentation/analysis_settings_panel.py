"""Analysis type and solver settings panel."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisKind, StructuralModel
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)

#: DOF labels by ndm, matching the order OpenSeesPy reports node results in.
_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")


class AnalysisSettingsPanel(QFrame):
    analysis_kind_changed = Signal(object)

    def __init__(
        self, parent: QWidget | None = None, store: AnalysisConfigStore | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("analysisSettingsPanel")
        self._model: StructuralModel | None = None
        # No store given -> this panel is its own source of truth, exactly like before
        # the store existed. Given one (SETUP's real usage), MODEL's AnalysisTypeSelector
        # and this panel share it, so neither can drift out of sync with the other.
        self.config_store = store if store is not None else AnalysisConfigStore()
        self.config_store.kind_changed.connect(self._on_store_kind_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("CURRENT CONFIGURATION"))

        settings = QFrame()
        settings.setObjectName("rightSection")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(16, 14, 16, 14)
        settings_layout.setSpacing(12)

        kind_row = QFrame()
        kind_row.setObjectName("setupConfigBar")
        kind_layout = QHBoxLayout(kind_row)
        kind_layout.setContentsMargins(12, 7, 12, 7)
        kind_layout.addWidget(self._field_label("ANALYSIS TYPE"))
        self.analysis_type = QComboBox()
        self.analysis_type.addItem("Linear Static", AnalysisKind.LINEAR_STATIC)
        self.analysis_type.addItem("Nonlinear Static", AnalysisKind.NONLINEAR_STATIC)
        self.analysis_type.addItem("Time History", AnalysisKind.TIME_HISTORY)
        self.analysis_type.setCurrentIndex(self.analysis_type.findData(self.config_store.kind))
        self.analysis_type.currentIndexChanged.connect(self._analysis_type_changed)
        kind_layout.addWidget(self.analysis_type, 1)
        settings_layout.addWidget(kind_row)

        load_card, load_layout = self._config_card("1. LOAD & CONTROL")
        load_grid = QGridLayout()
        load_grid.setHorizontalSpacing(24)
        load_grid.setVerticalSpacing(5)
        for row, (name, value) in enumerate((
            ("Gravity", "NONE"),
            ("Lateral", "ALL NON-GRAVITY"),
            ("Control", "Load Control"),
            ("Steps", "10"),
        )):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            metric = QLabel(value)
            metric.setObjectName("setupMetricValue")
            load_grid.addWidget(key, row, 0)
            load_grid.addWidget(metric, row, 1)
            if name == "Control":
                self.load_control_value = metric
            elif name == "Steps":
                self.load_steps_value = metric
        load_layout.addLayout(load_grid)
        settings_layout.addWidget(load_card)

        self.nonlinear_group = QFrame()
        self.nonlinear_group.setObjectName("setupConfigCard")
        self.nonlinear_group.setProperty("highlighted", True)
        nonlinear_layout = QVBoxLayout(self.nonlinear_group)
        nonlinear_layout.setContentsMargins(12, 10, 12, 10)
        nonlinear_layout.setSpacing(8)
        nonlinear_title = QLabel("2. NONLINEAR BEHAVIOR")
        nonlinear_title.setObjectName("setupConfigTitle")
        nonlinear_layout.addWidget(nonlinear_title)

        behavior_row = QHBoxLayout()
        behavior_row.setSpacing(8)
        for title, value, state in (
            ("MATERIAL NONLINEARITY", "✓  Detected in Model", "ok"),
            ("GEOMETRIC NONLINEARITY", "○  Not Enabled", "off"),
        ):
            tile = QFrame()
            tile.setObjectName("setupBehaviorTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(10, 7, 10, 7)
            tile_layout.setSpacing(2)
            tile_title = QLabel(title)
            tile_title.setObjectName("setupMetricLabel")
            tile_value = QLabel(value)
            tile_value.setObjectName("setupBehaviorValue")
            tile_value.setProperty("state", state)
            tile_layout.addWidget(tile_title)
            tile_layout.addWidget(tile_value)
            behavior_row.addWidget(tile, 1)
        nonlinear_layout.addLayout(behavior_row)

        warning = QLabel(
            "ⓘ  Geometric nonlinearity is currently disabled. P-Delta or "
            "large-displacement effects will not be considered."
        )
        warning.setObjectName("setupNotice")
        warning.setWordWrap(True)
        nonlinear_layout.addWidget(warning)
        self.solver = QComboBox()
        self.solver.addItems(("BandGeneral", "UmfPack", "ProfileSPD"))
        self.solver.currentIndexChanged.connect(self._sync_store_options)

        self.open_nonlinear_settings_button = QPushButton("Review Nonlinearity Settings")
        self.open_nonlinear_settings_button.setObjectName("nonlinearSettingsButton")
        self.open_nonlinear_settings_button.clicked.connect(self._open_nonlinear_settings)
        self.nonlinear_summary = QLabel()
        self.nonlinear_summary.setObjectName("nonlinearSettingsSummary")
        self.nonlinear_summary.setWordWrap(True)
        nonlinear_layout.addWidget(self.nonlinear_summary)
        nonlinear_layout.addWidget(
            self.open_nonlinear_settings_button, 0, Qt.AlignmentFlag.AlignRight
        )
        settings_layout.addWidget(self.nonlinear_group)

        solution_card, solution_layout = self._config_card("3. SOLUTION METHOD")
        solution_grid = QGridLayout()
        solution_grid.setHorizontalSpacing(18)
        solution_grid.setVerticalSpacing(4)
        for column, title in enumerate(("ALGORITHM", "CONSTRAINT", "NUMBERER", "SOLVER")):
            label = QLabel(title)
            label.setObjectName("setupMetricLabel")
            solution_grid.addWidget(label, 0, column)
        self.solution_algorithm = QLabel("Newton")
        self.solution_algorithm.setObjectName("setupMetricValue")
        plain = QLabel("Plain")
        plain.setObjectName("setupMetricValue")
        numberer = QLabel("RCM")
        numberer.setObjectName("setupMetricValue")
        solution_grid.addWidget(self.solution_algorithm, 1, 0)
        solution_grid.addWidget(plain, 1, 1)
        solution_grid.addWidget(numberer, 1, 2)
        solution_grid.addWidget(self.solver, 1, 3)
        solution_layout.addLayout(solution_grid)
        settings_layout.addWidget(solution_card)

        convergence_card, convergence_layout = self._config_card("4. CONVERGENCE")
        convergence_row = QHBoxLayout()
        convergence_row.setSpacing(18)
        self.convergence_test = QLabel("NormDispIncr")
        self.convergence_tolerance = QLabel("1.0E-6")
        self.convergence_iterations = QLabel("25")
        for title, value in (
            ("TEST", self.convergence_test),
            ("TOLERANCE", self.convergence_tolerance),
            ("MAX ITER", self.convergence_iterations),
        ):
            block = QVBoxLayout()
            block.setSpacing(2)
            label = QLabel(title)
            label.setObjectName("setupMetricLabel")
            value.setObjectName("setupMetricValue")
            block.addWidget(label)
            block.addWidget(value)
            convergence_row.addLayout(block)
        chart = QLabel("▇  ▅  ▂   ┄┄┄")
        chart.setObjectName("setupConvergenceChart")
        convergence_row.addWidget(chart, 1, Qt.AlignmentFlag.AlignRight)
        convergence_layout.addLayout(convergence_row)
        settings_layout.addWidget(convergence_card)
        settings_layout.addStretch(1)
        layout.addWidget(settings)

        self._build_nonlinear_dialog()
        self.solver.currentIndexChanged.connect(self._update_nonlinear_summary)
        self._update_nonlinear_visibility()
        self._update_nonlinear_summary()

    @staticmethod
    def _config_card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("setupConfigCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("setupConfigTitle")
        layout.addWidget(heading)
        return card, layout

    def _build_nonlinear_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("nonlinearSettingsDialog")
        dialog.setWindowTitle("Nonlinear Static Settings")
        dialog.setMinimumWidth(360)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(18, 16, 18, 16)
        dialog_layout.setSpacing(9)

        dialog_layout.addWidget(self._field_label("CONTROL NODE"))
        self.control_node = QComboBox()
        dialog_layout.addWidget(self.control_node)

        dialog_layout.addWidget(self._field_label("CONTROL DOF"))
        self.control_dof = QComboBox()
        dialog_layout.addWidget(self.control_dof)

        dialog_layout.addWidget(self._field_label("GRAVITY PATTERN"))
        self.gravity_pattern = QComboBox()
        self.gravity_pattern.addItem("NONE", None)
        self.gravity_pattern.setToolTip(
            "Hold this load pattern constant (applied first, then frozen) instead of "
            "ramping it up together with the rest - the standard gravity-then-push "
            "pushover procedure. Leave as NONE to scale every pattern together."
        )
        self.gravity_pattern.currentIndexChanged.connect(self._update_gravity_visibility)
        dialog_layout.addWidget(self.gravity_pattern)

        self.gravity_steps_group = QFrame()
        gravity_steps_layout = QVBoxLayout(self.gravity_steps_group)
        gravity_steps_layout.setContentsMargins(0, 0, 0, 0)
        gravity_steps_layout.setSpacing(4)
        gravity_steps_layout.addWidget(self._field_label("GRAVITY STEPS"))
        self.gravity_steps = QSpinBox()
        self.gravity_steps.setRange(1, 200)
        self.gravity_steps.setValue(5)
        gravity_steps_layout.addWidget(self.gravity_steps)
        dialog_layout.addWidget(self.gravity_steps_group)

        dialog_layout.addWidget(self._field_label("INTEGRATOR"))
        self.integrator_type = QComboBox()
        self.integrator_type.addItem("Load Control", "LoadControl")
        self.integrator_type.addItem("Displacement Control", "DisplacementControl")
        self.integrator_type.setToolTip(
            "LoadControl scales every pattern by an equal load factor each step - it "
            "cannot trace a softening/post-peak branch. DisplacementControl pushes "
            "CONTROL NODE/DOF by a fixed increment and solves for the load, so it can."
        )
        self.integrator_type.currentIndexChanged.connect(self._update_integrator_visibility)
        dialog_layout.addWidget(self.integrator_type)

        dialog_layout.addWidget(self._field_label("LOAD STEPS"))
        self.num_steps = QSpinBox()
        self.num_steps.setRange(1, 1000)
        self.num_steps.setValue(10)
        dialog_layout.addWidget(self.num_steps)

        self.target_displacement_group = QFrame()
        target_displacement_layout = QVBoxLayout(self.target_displacement_group)
        target_displacement_layout.setContentsMargins(0, 0, 0, 0)
        target_displacement_layout.setSpacing(4)
        target_displacement_layout.addWidget(self._field_label("TARGET DISPLACEMENT"))
        self.target_displacement = QDoubleSpinBox()
        self.target_displacement.setDecimals(6)
        self.target_displacement.setRange(-1.0e6, 1.0e6)
        self.target_displacement.setSingleStep(0.01)
        target_displacement_layout.addWidget(self.target_displacement)
        dialog_layout.addWidget(self.target_displacement_group)

        dialog_layout.addWidget(self._field_label("TOLERANCE"))
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setDecimals(8)
        self.tolerance.setRange(1.0e-10, 1.0)
        self.tolerance.setSingleStep(1.0e-7)
        self.tolerance.setValue(1.0e-6)
        dialog_layout.addWidget(self.tolerance)

        dialog_layout.addWidget(self._field_label("MAX ITERATIONS"))
        self.max_iterations = QSpinBox()
        self.max_iterations.setRange(1, 1000)
        self.max_iterations.setValue(25)
        dialog_layout.addWidget(self.max_iterations)

        dialog_layout.addWidget(self._field_label("ALGORITHM"))
        self.algorithm = QComboBox()
        self.algorithm.addItems(
            ("Newton", "ModifiedNewton", "KrylovNewton", "NewtonLineSearch")
        )
        dialog_layout.addWidget(self.algorithm)

        dialog_layout.addWidget(self._field_label("CONVERGENCE TEST"))
        self.test_type = QComboBox()
        self.test_type.addItems(("NormDispIncr", "EnergyIncr", "NormUnbalance"))
        dialog_layout.addWidget(self.test_type)

        dialog_layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)

        for combo in (
            self.control_node,
            self.control_dof,
            self.algorithm,
            self.test_type,
            self.gravity_pattern,
            self.integrator_type,
        ):
            combo.currentIndexChanged.connect(self._update_nonlinear_summary)
        for spinner in (
            self.num_steps,
            self.tolerance,
            self.max_iterations,
            self.gravity_steps,
            self.target_displacement,
        ):
            spinner.valueChanged.connect(self._update_nonlinear_summary)

        self._update_gravity_visibility()
        self._update_integrator_visibility()
        self._nonlinear_dialog = dialog

    def _update_gravity_visibility(self) -> None:
        self.gravity_steps_group.setVisible(self.gravity_pattern.currentData() is not None)

    def _update_integrator_visibility(self) -> None:
        self.target_displacement_group.setVisible(
            self.integrator_type.currentData() == "DisplacementControl"
        )

    def _open_nonlinear_settings(self) -> None:
        # SAVE keeps whatever is in the fields (they're the same widgets build_options()
        # reads from, so there's nothing extra to copy). CANCEL - including the dialog's
        # own [x] button, which Qt already routes to reject() - must undo any edits made
        # since opening, so a snapshot is taken up front and restored on non-acceptance.
        snapshot = self._nonlinear_snapshot()
        accepted = self._nonlinear_dialog.exec() == QDialog.DialogCode.Accepted
        if not accepted:
            self._restore_nonlinear_snapshot(snapshot)
        self._update_nonlinear_summary()

    def _nonlinear_snapshot(self) -> dict[str, int | float]:
        return {
            "control_node": self.control_node.currentIndex(),
            "control_dof": self.control_dof.currentIndex(),
            "gravity_pattern": self.gravity_pattern.currentIndex(),
            "gravity_steps": self.gravity_steps.value(),
            "integrator_type": self.integrator_type.currentIndex(),
            "num_steps": self.num_steps.value(),
            "target_displacement": self.target_displacement.value(),
            "tolerance": self.tolerance.value(),
            "max_iterations": self.max_iterations.value(),
            "algorithm": self.algorithm.currentIndex(),
            "test_type": self.test_type.currentIndex(),
        }

    def _restore_nonlinear_snapshot(self, snapshot: dict[str, int | float]) -> None:
        self.control_node.setCurrentIndex(int(snapshot["control_node"]))
        self.control_dof.setCurrentIndex(int(snapshot["control_dof"]))
        self.gravity_pattern.setCurrentIndex(int(snapshot["gravity_pattern"]))
        self.gravity_steps.setValue(int(snapshot["gravity_steps"]))
        self.integrator_type.setCurrentIndex(int(snapshot["integrator_type"]))
        self.num_steps.setValue(int(snapshot["num_steps"]))
        self.target_displacement.setValue(float(snapshot["target_displacement"]))
        self.tolerance.setValue(float(snapshot["tolerance"]))
        self.max_iterations.setValue(int(snapshot["max_iterations"]))
        self.algorithm.setCurrentIndex(int(snapshot["algorithm"]))
        self.test_type.setCurrentIndex(int(snapshot["test_type"]))

    def set_model(self, model: StructuralModel | None) -> None:
        self._model = model
        self.control_node.clear()
        if model is None:
            self._update_nonlinear_summary()
            return
        for tag, node in sorted(model.nodes.items()):
            coordinates = (
                f"({node.x:g}, {node.y:g}, {node.z:g})"
                if model.ndm == 3
                else f"({node.x:g}, {node.y:g})"
            )
            self.control_node.addItem(f"Node {tag} {coordinates}", tag)
        # Node 1 (the combo's default selection) is, by convention, very often a
        # support - pushing it produces a curve that is a flat vertical line at zero
        # displacement forever, with no error to say why. Point at the loaded node
        # instead, so the curve that first appears actually looks like a pushover.
        default_node = self._default_control_node(model)
        if default_node is not None:
            self.control_node.setCurrentIndex(self.control_node.findData(default_node))

        self.control_dof.clear()
        full_labels = _DOF_LABELS_3D if model.ndm == 3 else _DOF_LABELS_2D
        # Truss-only models declare fewer DOFs per node than a frame (e.g. ndf=2 in
        # 2D: UX/UY, no RZ) - offering a DOF the model doesn't have lets the solver
        # index past the end of OpenSeesPy's per-node result arrays and crash.
        for index, label in enumerate(full_labels[: model.ndf], start=1):
            self.control_dof.addItem(label, index)

        self.gravity_pattern.blockSignals(True)
        self.gravity_pattern.clear()
        self.gravity_pattern.addItem("NONE", None)
        for tag in self._pattern_tags(model):
            self.gravity_pattern.addItem(f"Pattern {tag}", tag)
        self.gravity_pattern.blockSignals(False)
        self._update_gravity_visibility()
        self._update_nonlinear_summary()

    @staticmethod
    def _pattern_tags(model: StructuralModel) -> list[int]:
        tags = {load.pattern_tag for load in model.nodal_loads if load.pattern_tag is not None}
        tags |= {
            load.pattern_tag for load in model.element_loads if load.pattern_tag is not None
        }
        return sorted(tags)

    @staticmethod
    def _default_control_node(model: StructuralModel) -> int | None:
        """Prefer a loaded, movable node; fall back to any movable node; otherwise
        leave the combo's own default (there's nothing better to suggest)."""
        fully_fixed = {
            boundary.node_tag
            for boundary in model.boundaries
            if boundary.restraints and all(boundary.restraints)
        }
        loaded_candidates = sorted(
            (
                (max((abs(value) for value in load.values), default=0.0), load.node_tag)
                for load in model.nodal_loads
                if load.node_tag not in fully_fixed and any(load.values)
            ),
            reverse=True,
        )
        if loaded_candidates:
            return loaded_candidates[0][1]
        movable_nodes = sorted(tag for tag in model.nodes if tag not in fully_fixed)
        return movable_nodes[0] if movable_nodes else None

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
            "integrator_type": self.integrator_type.currentData(),
        }
        control_node = self.control_node.currentData()
        if control_node is not None:
            options["control_node"] = int(control_node)
        control_dof = self.control_dof.currentData()
        if control_dof is not None:
            options["control_dof"] = int(control_dof)
        gravity_pattern = self.gravity_pattern.currentData()
        if gravity_pattern is not None:
            options["gravity_pattern"] = int(gravity_pattern)
            options["gravity_steps"] = self.gravity_steps.value()
        if self.integrator_type.currentData() == "DisplacementControl":
            options["target_displacement"] = self.target_displacement.value()
        return options

    def _analysis_type_changed(self) -> None:
        self._update_nonlinear_visibility()
        kind = self.selected_analysis_kind()
        self.config_store.set_kind(kind)
        self._sync_store_options()
        self.analysis_kind_changed.emit(kind)

    def _on_store_kind_changed(self, kind: AnalysisKind) -> None:
        """The store changed from outside this panel (e.g. MODEL's analysis-type
        selector) - mirror it into the combo. If the combo is already showing
        ``kind`` (this panel was the one that set it) Qt does not re-fire
        ``currentIndexChanged``, so this never loops back into ``config_store``."""
        self.analysis_type.setCurrentIndex(self.analysis_type.findData(kind))

    def _sync_store_options(self) -> None:
        self.config_store.set_options(self.build_options())

    def _update_nonlinear_visibility(self) -> None:
        self.nonlinear_group.setVisible(
            self.selected_analysis_kind() == AnalysisKind.NONLINEAR_STATIC
        )

    def _update_nonlinear_summary(self) -> None:
        """Keep a short readout of the dialog's current values visible in the
        sidebar, so checking them doesn't require reopening the dialog every time."""
        control_node = self.control_node.currentText() or "not set"
        gravity = self.gravity_pattern.currentText() if self.gravity_pattern.count() else "NONE"
        integrator = self.integrator_type.currentText()
        self.nonlinear_summary.setText(
            f"Control: {control_node} / {self.control_dof.currentText()}\n"
            f"Steps: {self.num_steps.value()}  ·  Algorithm: {self.algorithm.currentText()}\n"
            f"{integrator}  ·  Gravity: {gravity}"
        )
        self.load_control_value.setText(integrator)
        self.load_steps_value.setText(str(self.num_steps.value()))
        self.solution_algorithm.setText(self.algorithm.currentText())
        self.convergence_test.setText(self.test_type.currentText())
        self.convergence_tolerance.setText(f"{self.tolerance.value():.1E}")
        self.convergence_iterations.setText(str(self.max_iterations.value()))
        self._sync_store_options()

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
