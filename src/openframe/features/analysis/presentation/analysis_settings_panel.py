"""Analysis type and solver settings panel."""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisKind,
    StructuralModel,
    UnitSystem,
)

#: DOF labels by ndm, matching the order OpenSeesPy reports node results in.
_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")


class AnalysisSettingsPanel(QFrame):
    analysis_kind_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisSettingsPanel")
        self._model: StructuralModel | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM

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
        self.analysis_type.addItem("Modal (Eigenvalue)", AnalysisKind.MODAL)
        self.analysis_type.addItem("Time History", AnalysisKind.TIME_HISTORY)
        self.analysis_type.currentIndexChanged.connect(self._analysis_type_changed)
        settings_layout.addWidget(self.analysis_type)

        settings_layout.addWidget(self._field_label("SOLVER"))
        self.solver = QComboBox()
        self.solver.addItems(("BandGeneral", "UmfPack", "ProfileSPD"))
        settings_layout.addWidget(self.solver)

        # Nonlinear static has seven extra fields - crammed into this narrow sidebar
        # they either overlapped or forced a scrollbar over everything below them.
        # They matter more than the linear settings above (they control whether the
        # analysis converges at all), so they get their own dialog instead, opened
        # on demand via the button below and pre-filled from the same widgets every
        # time - nothing here is duplicated or re-created per open.
        self.nonlinear_group = QFrame()
        nonlinear_layout = QVBoxLayout(self.nonlinear_group)
        nonlinear_layout.setContentsMargins(0, 8, 0, 0)
        nonlinear_layout.setSpacing(4)
        self.open_nonlinear_settings_button = QPushButton("NONLINEAR SETTINGS…")
        self.open_nonlinear_settings_button.setObjectName("nonlinearSettingsButton")
        self.open_nonlinear_settings_button.clicked.connect(self._open_nonlinear_settings)
        nonlinear_layout.addWidget(self.open_nonlinear_settings_button)
        self.nonlinear_summary = QLabel()
        self.nonlinear_summary.setObjectName("nonlinearSettingsSummary")
        self.nonlinear_summary.setWordWrap(True)
        nonlinear_layout.addWidget(self.nonlinear_summary)
        settings_layout.addWidget(self.nonlinear_group)

        # Modal analysis only needs how many modes to compute - no dialog needed,
        # unlike nonlinear's seven interdependent fields.
        self.modal_group = QFrame()
        modal_layout = QVBoxLayout(self.modal_group)
        modal_layout.setContentsMargins(0, 8, 0, 0)
        modal_layout.setSpacing(4)
        modal_layout.addWidget(self._field_label("NUMBER OF MODES"))
        self.num_modes = QSpinBox()
        self.num_modes.setRange(1, 200)
        self.num_modes.setValue(3)
        self.num_modes.setToolTip(
            "The model's own script must define nodal mass (ops.mass(...)) - modal "
            "analysis has no natural frequency to find without it."
        )
        modal_layout.addWidget(self.num_modes)
        settings_layout.addWidget(self.modal_group)

        # Time history needs a ground-motion file plus three small numbers - a
        # dialog would be overkill, but it earns its own group (unlike modal's
        # one field) since a file picker is a different kind of control.
        self.time_history_group = QFrame()
        time_history_layout = QVBoxLayout(self.time_history_group)
        time_history_layout.setContentsMargins(0, 8, 0, 0)
        time_history_layout.setSpacing(4)
        self._ground_motion_path: Path | None = None
        time_history_layout.addWidget(self._field_label("GROUND MOTION FILE"))
        file_row = QHBoxLayout()
        self.ground_motion_path_label = QLabel("(no file selected)")
        self.ground_motion_path_label.setWordWrap(True)
        file_row.addWidget(self.ground_motion_path_label, 1)
        self.choose_ground_motion_button = QPushButton("Browse…")
        self.choose_ground_motion_button.clicked.connect(self._choose_ground_motion_file)
        file_row.addWidget(self.choose_ground_motion_button)
        time_history_layout.addLayout(file_row)

        time_history_layout.addWidget(self._field_label("DIRECTION"))
        self.time_history_direction = QComboBox()
        time_history_layout.addWidget(self.time_history_direction)

        time_history_layout.addWidget(self._field_label("DAMPING RATIO"))
        self.damping_ratio = QDoubleSpinBox()
        self.damping_ratio.setRange(0.0, 1.0)
        self.damping_ratio.setSingleStep(0.01)
        self.damping_ratio.setDecimals(3)
        self.damping_ratio.setValue(0.05)
        self.damping_ratio.setToolTip(
            "Target damping ratio (e.g. 0.05 for 5%) - Rayleigh alpha/beta are "
            "computed automatically from the model's own first one or two natural "
            "frequencies, not entered directly."
        )
        time_history_layout.addWidget(self.damping_ratio)

        time_history_layout.addWidget(self._field_label("SCALE FACTOR"))
        self.ground_motion_scale = QDoubleSpinBox()
        self.ground_motion_scale.setRange(-1.0e6, 1.0e6)
        self.ground_motion_scale.setDecimals(6)
        self.ground_motion_scale.setValue(1.0)
        self.ground_motion_scale.setToolTip(
            "Multiplies every value in the ground-motion file - e.g. 9.81 (or "
            "9810 in mm) if the file is in units of g rather than already "
            "matching this model's length unit."
        )
        time_history_layout.addWidget(self.ground_motion_scale)
        settings_layout.addWidget(self.time_history_group)

        settings_layout.addStretch(1)
        layout.addWidget(settings)

        self._build_nonlinear_dialog()
        self._update_nonlinear_visibility()
        self._update_nonlinear_summary()

    def _build_nonlinear_dialog(self) -> None:
        # Sixteen fields stacked in one column used to push this dialog well past
        # screen height. Two columns - "how the push is applied" on the left,
        # "how the solver converges" on the right - halves that, and the two
        # groupings read as a real conceptual split rather than an arbitrary cut.
        dialog = QDialog(self)
        dialog.setObjectName("nonlinearSettingsDialog")
        dialog.setWindowTitle("Nonlinear Static Settings")
        dialog.setMinimumWidth(560)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(18, 16, 18, 16)
        dialog_layout.setSpacing(9)

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(9)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        dialog_layout.addLayout(grid)

        self.control_node = QComboBox()
        self.control_dof = QComboBox()

        self.gravity_pattern = QComboBox()
        self.gravity_pattern.addItem("NONE", None)
        self.gravity_pattern.setToolTip(
            "Hold this load pattern constant (applied first, then frozen) instead of "
            "ramping it up together with the rest - the standard gravity-then-push "
            "pushover procedure. Leave as NONE to scale every pattern together."
        )
        self.gravity_pattern.currentIndexChanged.connect(self._update_gravity_visibility)

        self.gravity_steps = QSpinBox()
        self.gravity_steps.setRange(1, 200)
        self.gravity_steps.setValue(5)
        self.gravity_steps_group = self._field_block("GRAVITY STEPS", self.gravity_steps)

        self.lateral_pattern = QComboBox()
        self.lateral_pattern.addItem("ALL NON-GRAVITY PATTERNS", None)
        self.lateral_pattern.setToolTip(
            "Choose one load pattern for the pushover. The default pushes every "
            "active pattern except the selected gravity pattern."
        )

        self.integrator_type = QComboBox()
        self.integrator_type.addItem("Load Control", "LoadControl")
        self.integrator_type.addItem("Displacement Control", "DisplacementControl")
        self.integrator_type.setToolTip(
            "LoadControl scales every pattern by an equal load factor each step - it "
            "cannot trace a softening/post-peak branch. DisplacementControl pushes "
            "CONTROL NODE/DOF by a fixed increment and solves for the load, so it can."
        )
        self.integrator_type.currentIndexChanged.connect(self._update_integrator_visibility)

        self.num_steps = QSpinBox()
        # Published nonlinear benchmarks commonly need several thousand small
        # displacement increments (the official OpenSees two-story moment frame
        # uses 3,240), so the old 1,000-step ceiling prevented exact reproduction.
        self.num_steps.setRange(1, 100_000)
        self.num_steps.setValue(10)

        self.target_displacement = QDoubleSpinBox()
        self.target_displacement.setDecimals(6)
        self.target_displacement.setRange(-1.0e6, 1.0e6)
        self.target_displacement.setSingleStep(0.01)
        self.target_displacement.setSuffix(f" {self._unit_system.length}")
        self.target_displacement_label = self._field_label(
            f"TARGET DISPLACEMENT ({self._unit_system.length})"
        )
        self.target_displacement_group = self._field_block(
            None, self.target_displacement, label=self.target_displacement_label
        )

        left_column = [
            self._field_block("CONTROL NODE", self.control_node),
            self._field_block("CONTROL DOF", self.control_dof),
            self._field_block("GRAVITY PATTERN", self.gravity_pattern),
            self.gravity_steps_group,
            self._field_block("LATERAL LOAD PATTERN", self.lateral_pattern),
            self._field_block("INTEGRATOR", self.integrator_type),
            self._field_block("LOAD STEPS", self.num_steps),
            self.target_displacement_group,
        ]

        self.tolerance = QDoubleSpinBox()
        self.tolerance.setDecimals(8)
        self.tolerance.setRange(1.0e-10, 1.0)
        self.tolerance.setSingleStep(1.0e-7)
        self.tolerance.setValue(1.0e-6)

        self.max_iterations = QSpinBox()
        self.max_iterations.setRange(1, 1000)
        self.max_iterations.setValue(25)

        self.max_bisections = QSpinBox()
        self.max_bisections.setRange(0, 10)
        self.max_bisections.setValue(4)
        self.max_bisections.setToolTip(
            "When an increment does not converge, halve it this many times before "
            "marking the run as partially converged."
        )

        self.execution_timeout = QSpinBox()
        self.execution_timeout.setRange(10, 86_400)
        self.execution_timeout.setValue(600)
        self.execution_timeout.setToolTip(
            "Maximum wall-clock time for this nonlinear run. Large models commonly "
            "need more than the 30-second linear-analysis default."
        )

        self.constraints_type = QComboBox()
        self.constraints_type.addItems(("Plain", "Transformation"))
        self.constraints_type.setToolTip(
            "Transformation is appropriate when the model contains equalDOF, "
            "rigidLink, or rigidDiaphragm multi-point constraints."
        )

        self.numberer = QComboBox()
        self.numberer.addItems(("RCM", "Plain", "AMD"))

        self.algorithm = QComboBox()
        self.algorithm.addItems(
            ("Newton", "ModifiedNewton", "KrylovNewton", "NewtonLineSearch")
        )

        self.test_type = QComboBox()
        self.test_type.addItems(("NormDispIncr", "EnergyIncr", "NormUnbalance"))

        right_column = [
            self._field_block("TOLERANCE", self.tolerance),
            self._field_block("MAX ITERATIONS", self.max_iterations),
            self._field_block("MAX STEP BISECTIONS", self.max_bisections),
            self._field_block("MAX RUNTIME (SECONDS)", self.execution_timeout),
            self._field_block("CONSTRAINT HANDLER", self.constraints_type),
            self._field_block("DOF NUMBERER", self.numberer),
            self._field_block("ALGORITHM", self.algorithm),
            self._field_block("CONVERGENCE TEST", self.test_type),
        ]

        for row, block in enumerate(left_column):
            grid.addWidget(block, row, 0)
        for row, block in enumerate(right_column):
            grid.addWidget(block, row, 1)

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
            self.lateral_pattern,
            self.integrator_type,
            self.constraints_type,
            self.numberer,
        ):
            combo.currentIndexChanged.connect(self._update_nonlinear_summary)
        for spinner in (
            self.num_steps,
            self.tolerance,
            self.max_iterations,
            self.max_bisections,
            self.execution_timeout,
            self.gravity_steps,
            self.target_displacement,
        ):
            spinner.valueChanged.connect(self._update_nonlinear_summary)

        self._update_gravity_visibility()
        self._update_integrator_visibility()
        self._nonlinear_dialog = dialog

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        """Show the imported model's native length beside dimensional inputs."""
        self._unit_system = unit_system
        self.target_displacement_label.setText(
            f"TARGET DISPLACEMENT ({unit_system.length})"
        )
        self.target_displacement.setSuffix(f" {unit_system.length}")

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
            "lateral_pattern": self.lateral_pattern.currentIndex(),
            "integrator_type": self.integrator_type.currentIndex(),
            "num_steps": self.num_steps.value(),
            "target_displacement": self.target_displacement.value(),
            "tolerance": self.tolerance.value(),
            "max_iterations": self.max_iterations.value(),
            "max_bisections": self.max_bisections.value(),
            "execution_timeout": self.execution_timeout.value(),
            "constraints_type": self.constraints_type.currentIndex(),
            "numberer": self.numberer.currentIndex(),
            "algorithm": self.algorithm.currentIndex(),
            "test_type": self.test_type.currentIndex(),
        }

    def _restore_nonlinear_snapshot(self, snapshot: dict[str, int | float]) -> None:
        self.control_node.setCurrentIndex(int(snapshot["control_node"]))
        self.control_dof.setCurrentIndex(int(snapshot["control_dof"]))
        self.gravity_pattern.setCurrentIndex(int(snapshot["gravity_pattern"]))
        self.gravity_steps.setValue(int(snapshot["gravity_steps"]))
        self.lateral_pattern.setCurrentIndex(int(snapshot["lateral_pattern"]))
        self.integrator_type.setCurrentIndex(int(snapshot["integrator_type"]))
        self.num_steps.setValue(int(snapshot["num_steps"]))
        self.target_displacement.setValue(float(snapshot["target_displacement"]))
        self.tolerance.setValue(float(snapshot["tolerance"]))
        self.max_iterations.setValue(int(snapshot["max_iterations"]))
        self.max_bisections.setValue(int(snapshot["max_bisections"]))
        self.execution_timeout.setValue(int(snapshot["execution_timeout"]))
        self.constraints_type.setCurrentIndex(int(snapshot["constraints_type"]))
        self.numberer.setCurrentIndex(int(snapshot["numberer"]))
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

        self.time_history_direction.clear()
        for index, label in enumerate(full_labels[: model.ndf], start=1):
            self.time_history_direction.addItem(label, index)

        self.gravity_pattern.blockSignals(True)
        self.gravity_pattern.clear()
        self.gravity_pattern.addItem("NONE", None)
        for tag in self._pattern_tags(model):
            self.gravity_pattern.addItem(f"Pattern {tag}", tag)
        self.gravity_pattern.blockSignals(False)
        self.lateral_pattern.blockSignals(True)
        self.lateral_pattern.clear()
        self.lateral_pattern.addItem("ALL NON-GRAVITY PATTERNS", None)
        for tag in self._pattern_tags(model):
            self.lateral_pattern.addItem(f"Pattern {tag}", tag)
        self.lateral_pattern.blockSignals(False)
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
        static; other analysis kinds ignore ``AnalysisRequest.options`` entirely -
        except modal, whose solver takes different keyword arguments and would
        raise ``TypeError`` if handed this shape, so it gets its own early return."""
        if self.selected_analysis_kind() == AnalysisKind.MODAL:
            return {"num_modes": self.num_modes.value()}
        if self.selected_analysis_kind() == AnalysisKind.TIME_HISTORY:
            direction = self.time_history_direction.currentData()
            return {
                "ground_motion_path": (
                    str(self._ground_motion_path) if self._ground_motion_path is not None else ""
                ),
                "direction": int(direction) if direction is not None else 1,
                "damping_ratio": self.damping_ratio.value(),
                "scale_factor": self.ground_motion_scale.value(),
            }
        options: dict[str, float | int | str | bool] = {
            "system": self.solver.currentText(),
            "num_steps": self.num_steps.value(),
            "tolerance": self.tolerance.value(),
            "max_iterations": self.max_iterations.value(),
            "max_bisections": self.max_bisections.value(),
            "execution_timeout_seconds": self.execution_timeout.value(),
            "constraints_type": self.constraints_type.currentText(),
            "numberer": self.numberer.currentText(),
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
        lateral_pattern = self.lateral_pattern.currentData()
        if lateral_pattern is not None:
            options["lateral_pattern"] = int(lateral_pattern)
        if self.integrator_type.currentData() == "DisplacementControl":
            options["target_displacement"] = self.target_displacement.value()
        return options

    def _analysis_type_changed(self) -> None:
        self._update_nonlinear_visibility()
        self.analysis_kind_changed.emit(self.selected_analysis_kind())

    def _update_nonlinear_visibility(self) -> None:
        self.nonlinear_group.setVisible(
            self.selected_analysis_kind() == AnalysisKind.NONLINEAR_STATIC
        )
        self.modal_group.setVisible(self.selected_analysis_kind() == AnalysisKind.MODAL)
        self.time_history_group.setVisible(
            self.selected_analysis_kind() == AnalysisKind.TIME_HISTORY
        )

    def _choose_ground_motion_file(self) -> None:
        path_text, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "지진파(가속도) 파일 선택",
            "",
            "Ground motion files (*.txt *.csv *.AT2 *.dat);;All files (*.*)",
        )
        if not path_text:
            return
        self._ground_motion_path = Path(path_text)
        self.ground_motion_path_label.setText(self._ground_motion_path.name)
        self.ground_motion_path_label.setToolTip(path_text)

    def _update_nonlinear_summary(self) -> None:
        """Keep a short readout of the dialog's current values visible in the
        sidebar, so checking them doesn't require reopening the dialog every time."""
        control_node = self.control_node.currentText() or "not set"
        gravity = self.gravity_pattern.currentText() if self.gravity_pattern.count() else "NONE"
        lateral = self.lateral_pattern.currentText() if self.lateral_pattern.count() else "ALL"
        integrator = self.integrator_type.currentText()
        self.nonlinear_summary.setText(
            f"Control: {control_node} / {self.control_dof.currentText()}\n"
            f"Steps: {self.num_steps.value()}  ·  Algorithm: {self.algorithm.currentText()}\n"
            f"{integrator}  ·  Gravity: {gravity}\n"
            f"Lateral: {lateral}"
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

    def _field_block(
        self, text: str | None, widget: QWidget, *, label: QLabel | None = None
    ) -> QFrame:
        """One label-over-input pair as a single unit, so a grid can place it in
        a column without the label and its widget ending up in separate cells."""
        block = QFrame()
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(4)
        block_layout.addWidget(label if label is not None else self._field_label(text))
        block_layout.addWidget(widget)
        return block
