"""Analysis type and solver settings panel."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    ANALYSIS_CAPABILITIES,
    DEFAULT_UNIT_SYSTEM,
    AnalysisKind,
    ComponentField,
    FieldState,
    StructuralModel,
    UnitSystem,
)
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)

#: DOF labels by ndm, matching the order OpenSeesPy reports node results in.
_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")

#: Mirrors nonlinear_static_solver.py's own `nonlinear_elements` set exactly -
#: element_type is the only nonlinearity signal StructuralModel actually
#: carries (material/section/geomTransf type names are collector-internal and
#: never reach the imported StructuralModel - see model_importer.py), so this
#: is duplicated here rather than imported, matching how the solver's other
#: allowed-value lists (algorithms, tests, ...) are already duplicated as this
#: panel's combo box items.
_NONLINEAR_ELEMENT_TYPES = frozenset(
    {
        "forcebeamcolumn",
        "dispbeamcolumn",
        "displacementbeamcolumn",
        "corottruss",
        "corottrusssection",
    }
)


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
        self._unit_system = DEFAULT_UNIT_SYSTEM

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("CURRENT CONFIGURATION"))

        settings = QFrame()
        settings.setObjectName("setupSettingsSurface")
        settings.setMaximumWidth(896)
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(24, 20, 24, 24)
        settings_layout.setSpacing(16)

        kind_row = QFrame()
        kind_row.setObjectName("setupConfigBar")
        kind_layout = QHBoxLayout(kind_row)
        kind_layout.setContentsMargins(12, 7, 12, 7)
        kind_layout.addWidget(self._field_label("ANALYSIS TYPE"))
        self.analysis_type = QComboBox()
        self.analysis_type.addItem("Linear Static", AnalysisKind.LINEAR_STATIC)
        self.analysis_type.addItem("Nonlinear Static", AnalysisKind.NONLINEAR_STATIC)
        self.analysis_type.addItem("Modal (Eigenvalue)", AnalysisKind.MODAL)
        self.analysis_type.addItem("Time History", AnalysisKind.TIME_HISTORY)
        self.analysis_type.setCurrentIndex(self.analysis_type.findData(self.config_store.kind))
        self.analysis_type.currentIndexChanged.connect(self._analysis_type_changed)
        kind_layout.addWidget(self.analysis_type, 1)
        settings_layout.addWidget(kind_row)

        self.load_card, load_layout = self._config_card("1. LOAD & CONTROL")
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
        self.load_content_widget = QWidget()
        load_content = QHBoxLayout(self.load_content_widget)
        load_content.setContentsMargins(0, 0, 0, 0)
        load_content.setSpacing(28)
        load_content.addLayout(load_grid)
        load_progress = QFrame()
        load_progress.setObjectName("setupLoadProgress")
        load_progress_layout = QVBoxLayout(load_progress)
        load_progress_layout.setContentsMargins(20, 4, 0, 2)
        load_progress_layout.setSpacing(4)
        self.load_progress = QProgressBar()
        self.load_progress.setObjectName("setupLoadProgressBar")
        self.load_progress.setRange(0, 10)
        self.load_progress.setValue(10)
        self.load_progress.setTextVisible(False)
        load_progress_layout.addWidget(self.load_progress)
        progress_labels = QHBoxLayout()
        progress_labels.setContentsMargins(0, 0, 0, 0)
        zero_label = QLabel("0%")
        zero_label.setObjectName("setupProgressCaption")
        self.load_progress_caption = QLabel("100% (10 Steps)")
        self.load_progress_caption.setObjectName("setupProgressCaption")
        self.load_progress_caption.setProperty("active", True)
        progress_labels.addWidget(zero_label)
        progress_labels.addStretch(1)
        progress_labels.addWidget(self.load_progress_caption)
        load_progress_layout.addLayout(progress_labels)
        load_content.addWidget(load_progress, 1)
        load_layout.addWidget(self.load_content_widget)

        # Nonlinear Static's own row set, shown instead of load_content_widget above
        # (whose Gravity/Lateral text never updates - a real gap this phase
        # fixes) - Time History still uses load_content exactly as before,
        # unchanged, since this row set is Load/Displacement-Control-shaped
        # and that concept does not apply to it (Time History's own dedicated
        # SETUP screen is Phase 3-E's job, not this one's).
        self.nonlinear_load_summary = QWidget()
        nonlinear_load_layout = QGridLayout(self.nonlinear_load_summary)
        nonlinear_load_layout.setHorizontalSpacing(24)
        nonlinear_load_layout.setVerticalSpacing(5)
        self._nonlinear_load_rows: dict[str, tuple[QWidget, QLabel]] = {}
        for row, (key, label) in enumerate(
            (
                ("gravity_pattern", "Gravity Pattern"),
                ("lateral_pattern", "Lateral Pattern"),
                ("control_method", "Control Method"),
                ("load_steps", "Load Steps"),
                ("control_node", "Control Node"),
                ("control_dof", "Control DOF"),
                ("target_displacement", "Target Displacement"),
            )
        ):
            key_label = QLabel(f"{label}:")
            key_label.setObjectName("setupMetricLabel")
            value_label = QLabel("—")
            value_label.setObjectName("setupMetricValue")
            nonlinear_load_layout.addWidget(key_label, row, 0)
            nonlinear_load_layout.addWidget(value_label, row, 1)
            self._nonlinear_load_rows[key] = (key_label, value_label)
        load_layout.addWidget(self.nonlinear_load_summary)
        self.nonlinear_load_summary.hide()

        settings_layout.addWidget(self.load_card)

        # Linear Static's own compact card, shown instead of self.load_card
        # (whose Gravity/Lateral/Control/Steps rows are Nonlinear-Static-shaped
        # and mean nothing for a single-step linear solve) - see
        # _update_kind_specific_layout. Load pattern data reuses the same
        # _pattern_tags() helper the Nonlinear dialog's GRAVITY/LATERAL PATTERN
        # combos already read from the model, so nothing here is guessed.
        self.linear_static_group = QFrame()
        self.linear_static_group.setObjectName("setupConfigCard")
        linear_static_layout = QVBoxLayout(self.linear_static_group)
        linear_static_layout.setContentsMargins(12, 10, 12, 10)
        linear_static_layout.setSpacing(8)

        loads_title = QLabel("LOADS")
        loads_title.setObjectName("setupConfigTitle")
        linear_static_layout.addWidget(loads_title)
        loads_row = QHBoxLayout()
        loads_row.setSpacing(8)
        loads_key = QLabel("Applied Load Patterns:")
        loads_key.setObjectName("setupMetricLabel")
        self.linear_static_load_value = QLabel("—")
        self.linear_static_load_value.setObjectName("setupMetricValue")
        self.linear_static_load_value.setWordWrap(True)
        loads_row.addWidget(loads_key)
        loads_row.addWidget(self.linear_static_load_value, 1)
        linear_static_layout.addLayout(loads_row)
        loads_note = QLabel(
            "Every load pattern defined in the imported model is applied "
            "together, in a single step."
        )
        loads_note.setObjectName("secondaryText")
        loads_note.setWordWrap(True)
        linear_static_layout.addWidget(loads_note)

        method_divider = QFrame()
        method_divider.setObjectName("setupGuideDivider")
        method_divider.setFrameShape(QFrame.Shape.HLine)
        linear_static_layout.addWidget(method_divider)

        method_title = QLabel("ANALYSIS METHOD")
        method_title.setObjectName("setupConfigTitle")
        linear_static_layout.addWidget(method_title)
        method_grid = QGridLayout()
        method_grid.setHorizontalSpacing(24)
        method_grid.setVerticalSpacing(5)
        for row, (name, value) in enumerate(
            (("Analysis", "Linear Static"), ("Behavior", "Linear Elastic"))
        ):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            metric = QLabel(value)
            metric.setObjectName("setupMetricValue")
            method_grid.addWidget(key, row, 0)
            method_grid.addWidget(metric, row, 1)
        linear_static_layout.addLayout(method_grid)
        method_note = QLabel(
            "Calculates the structural response under static loading, solved "
            "in a single step without iterating for equilibrium."
        )
        method_note.setObjectName("secondaryText")
        method_note.setWordWrap(True)
        linear_static_layout.addWidget(method_note)
        settings_layout.addWidget(self.linear_static_group)

        self.nonlinear_group = QFrame()
        self.nonlinear_group.setObjectName("setupConfigCard")
        self.nonlinear_group.setProperty("highlighted", True)
        nonlinear_layout = QVBoxLayout(self.nonlinear_group)
        nonlinear_layout.setContentsMargins(12, 10, 12, 10)
        nonlinear_layout.setSpacing(8)
        nonlinear_title_row = QHBoxLayout()
        nonlinear_title_row.setContentsMargins(0, 0, 0, 0)
        nonlinear_title = QLabel("2. NONLINEAR BEHAVIOR")
        nonlinear_title.setObjectName("setupConfigTitle")
        nonlinear_title_row.addWidget(nonlinear_title)
        nonlinear_title_row.addStretch(1)
        review_badge = QLabel("REVIEW REQUIRED")
        review_badge.setObjectName("setupReviewBadge")
        nonlinear_title_row.addWidget(review_badge)
        nonlinear_layout.addLayout(nonlinear_title_row)

        behavior_row = QHBoxLayout()
        behavior_row.setSpacing(8)
        for title, default_value, default_state, attr in (
            ("MATERIAL NONLINEARITY", "—", "off", "material_nonlinearity_value"),
            ("GEOMETRIC NONLINEARITY", "—", "off", "geometric_nonlinearity_value"),
        ):
            tile = QFrame()
            tile.setObjectName("setupBehaviorTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(10, 7, 10, 7)
            tile_layout.setSpacing(2)
            tile_title = QLabel(title)
            tile_title.setObjectName("setupMetricLabel")
            tile_value = QLabel(default_value)
            tile_value.setObjectName("setupBehaviorValue")
            tile_value.setProperty("state", default_state)
            tile_layout.addWidget(tile_title)
            tile_layout.addWidget(tile_value)
            behavior_row.addWidget(tile, 1)
            setattr(self, attr, tile_value)
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

        # Modal analysis only needs how many modes to compute - no dialog needed,
        # unlike nonlinear's seven interdependent fields.
        self.modal_group = QFrame()
        self.modal_group.setObjectName("setupConfigCard")
        modal_layout = QVBoxLayout(self.modal_group)
        modal_layout.setContentsMargins(12, 10, 12, 10)
        modal_layout.setSpacing(8)
        modal_title = QLabel("MODAL PARAMETERS")
        modal_title.setObjectName("setupConfigTitle")
        modal_layout.addWidget(modal_title)
        modal_layout.addWidget(self._field_label("NUMBER OF MODES"))
        self.num_modes = QSpinBox()
        self.num_modes.setRange(1, 200)
        self.num_modes.setValue(3)
        self.num_modes.setToolTip(
            "The model's own script must define nodal mass (ops.mass(...)) - modal "
            "analysis has no natural frequency to find without it."
        )
        # Every other option widget in this file syncs on change (see self.solver
        # above, the dialog's spinners/combos below) - num_modes was missing this,
        # so a value typed here was silently dropped until some unrelated event
        # (e.g. switching AnalysisKind away and back) happened to call
        # _sync_store_options() anyway. RUN ANALYSIS reads config_store.options
        # directly (see MainWindow._run_analysis), not a fresh build_options()
        # call, so this was a real bug, not just a cosmetic one.
        self.num_modes.valueChanged.connect(self._sync_store_options)
        modal_layout.addWidget(self.num_modes)
        settings_layout.addWidget(self.modal_group)

        # Modal's own EIGEN SOLUTION card - shown instead of the shared "3.
        # SOLUTION METHOD" card (whose Newton/load-step flow diagram implies an
        # iterative equilibrium solve that has no meaning for an eigenproblem).
        # Eigen solver info is genuinely important here so it stays outside the
        # collapsed section; the underlying analysis-preparation values
        # (Equation Solver, Algorithm, ...) reuse the same collapsible-toggle
        # pattern Phase 3-B introduced for Linear Static, in a second instance
        # of that pattern rather than the same widgets, so Modal can show its
        # own extra Static Integrator row without touching Linear Static's
        # already-reviewed "3. SOLUTION METHOD" card at all.
        self.modal_engine_card = QFrame()
        self.modal_engine_card.setObjectName("setupConfigCard")
        modal_engine_layout = QVBoxLayout(self.modal_engine_card)
        modal_engine_layout.setContentsMargins(12, 10, 12, 10)
        modal_engine_layout.setSpacing(8)

        eigen_title = QLabel("EIGEN SOLUTION")
        eigen_title.setObjectName("setupConfigTitle")
        modal_engine_layout.addWidget(eigen_title)
        eigen_capability = ANALYSIS_CAPABILITIES[AnalysisKind.MODAL].eigen_solver
        eigen_details = dict(eigen_capability.details)
        eigen_grid = QGridLayout()
        eigen_grid.setHorizontalSpacing(24)
        eigen_grid.setVerticalSpacing(5)
        for row, (name, value) in enumerate((
            ("Eigen Solver", "Automatic   ·   AUTO"),
            ("Primary", eigen_details.get("primary", "—")),
            ("Fallback", eigen_details.get("fallback", "—")),
        )):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            metric = QLabel(value)
            metric.setObjectName("setupMetricValue")
            eigen_grid.addWidget(key, row, 0)
            eigen_grid.addWidget(metric, row, 1)
        modal_engine_layout.addLayout(eigen_grid)
        eigen_note = QLabel(
            "The default eigen solver is used first. FullGenLapack is used "
            "automatically if the primary solver fails."
        )
        eigen_note.setObjectName("secondaryText")
        eigen_note.setWordWrap(True)
        modal_engine_layout.addWidget(eigen_note)

        modal_engine_divider = QFrame()
        modal_engine_divider.setObjectName("setupGuideDivider")
        modal_engine_divider.setFrameShape(QFrame.Shape.HLine)
        modal_engine_layout.addWidget(modal_engine_divider)

        self.modal_engine_details_toggle = QPushButton("▸  ADVANCED ENGINE DETAILS")
        self.modal_engine_details_toggle.setObjectName("setupCollapsibleToggle")
        self.modal_engine_details_toggle.setCheckable(True)
        self.modal_engine_details_toggle.setFlat(True)
        self.modal_engine_details_toggle.toggled.connect(
            self._toggle_modal_engine_details
        )
        modal_engine_layout.addWidget(self.modal_engine_details_toggle)

        self.modal_engine_details_body = QWidget()
        modal_details_layout = QVBoxLayout(self.modal_engine_details_body)
        modal_details_layout.setContentsMargins(0, 0, 0, 0)
        modal_details_layout.setSpacing(4)
        modal_capabilities = ANALYSIS_CAPABILITIES[AnalysisKind.MODAL]
        static_integrator_details = dict(modal_capabilities.static_integrator.details)
        modal_details_grid = QGridLayout()
        modal_details_grid.setHorizontalSpacing(24)
        modal_details_grid.setVerticalSpacing(5)
        for row, (name, field) in enumerate((
            ("Equation Solver", modal_capabilities.equation_solver),
            ("Algorithm", modal_capabilities.algorithm),
            ("Constraint Handler", modal_capabilities.constraint_handler),
            ("DOF Numberer", modal_capabilities.numberer),
        )):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            metric = QLabel(f"{field.value}   ·   FIXED")
            metric.setObjectName("setupMetricValue")
            modal_details_grid.addWidget(key, row, 0)
            modal_details_grid.addWidget(metric, row, 1)
        increment = static_integrator_details.get("increment", "0.0")
        integrator_key = QLabel("Static Integrator:")
        integrator_key.setObjectName("setupMetricLabel")
        integrator_value = QLabel(
            f"{modal_capabilities.static_integrator.value} ({increment})   ·   FIXED"
        )
        integrator_value.setObjectName("setupMetricValue")
        modal_details_grid.addWidget(integrator_key, 4, 0)
        modal_details_grid.addWidget(integrator_value, 4, 1)
        modal_details_layout.addLayout(modal_details_grid)
        integrator_note = QLabel(
            "Static Integrator here only prepares the model before the eigen "
            "solve - it is not a load step."
        )
        integrator_note.setObjectName("secondaryText")
        integrator_note.setWordWrap(True)
        modal_details_layout.addWidget(integrator_note)
        self.modal_engine_details_body.setVisible(False)
        modal_engine_layout.addWidget(self.modal_engine_details_body)
        settings_layout.addWidget(self.modal_engine_card)

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

        self.solution_card, solution_layout = self._config_card("3. SOLUTION METHOD")
        # Linear Static toggles this open/closed instead of always showing it -
        # every value inside is ENGINE_FIXED for that kind (see Phase 3-A), so
        # it should not dominate the default screen. Nonlinear/Modal/Time
        # History keep it permanently expanded, unchanged from before.
        self.engine_details_toggle = QPushButton("▸  ADVANCED ENGINE DETAILS")
        self.engine_details_toggle.setObjectName("setupCollapsibleToggle")
        self.engine_details_toggle.setCheckable(True)
        self.engine_details_toggle.setFlat(True)
        self.engine_details_toggle.toggled.connect(self._toggle_engine_details)
        self.engine_details_toggle.hide()
        solution_layout.addWidget(self.engine_details_toggle)
        self.solution_body = QWidget()
        solution_layout.addWidget(self.solution_body)
        solution_body_layout = QVBoxLayout(self.solution_body)
        solution_body_layout.setContentsMargins(0, 0, 0, 0)
        solution_body_layout.setSpacing(8)
        solution_grid = QGridLayout()
        solution_grid.setHorizontalSpacing(18)
        solution_grid.setVerticalSpacing(4)
        for column, title in enumerate(("ALGORITHM", "CONSTRAINT", "NUMBERER", "SOLVER")):
            label = QLabel(title)
            label.setObjectName("setupMetricLabel")
            solution_grid.addWidget(label, 0, column)
        self.solution_algorithm = QLabel("Newton")
        self.solution_algorithm.setObjectName("setupMetricValue")
        self.constraint_value = QLabel("Plain")
        self.constraint_value.setObjectName("setupMetricValue")
        self.numberer_value = QLabel("RCM")
        self.numberer_value.setObjectName("setupMetricValue")
        # Shown instead of the editable self.solver combo when the current
        # AnalysisKind's equation solver is ENGINE_FIXED/AUTOMATIC (see
        # _apply_solver_field) - same grid cell, only one of the two is ever
        # visible, so no extra layout row is needed for the fixed case.
        self.solver_fixed_value = QLabel()
        self.solver_fixed_value.setObjectName("setupMetricValue")
        self.solver_fixed_value.hide()
        solution_grid.addWidget(self.solution_algorithm, 1, 0)
        solution_grid.addWidget(self.constraint_value, 1, 1)
        solution_grid.addWidget(self.numberer_value, 1, 2)
        solution_grid.addWidget(self.solver, 1, 3)
        solution_grid.addWidget(self.solver_fixed_value, 1, 3)
        solution_body_layout.addLayout(solution_grid)
        solution_flow = QFrame()
        solution_flow.setObjectName("setupSolutionFlow")
        flow_layout = QHBoxLayout(solution_flow)
        flow_layout.setContentsMargins(14, 9, 14, 9)
        flow_layout.setSpacing(8)
        for index, (symbol, caption) in enumerate((
            ("ΔP", "LOAD STEP"),
            ("K", "NEWTON"),
            ("ΣF=0", "EQUILIBRIUM"),
            ("P+1", "NEXT"),
        )):
            node = QFrame()
            node.setObjectName("setupSolutionNode")
            node.setProperty("active", index == 1)
            node_layout = QVBoxLayout(node)
            node_layout.setContentsMargins(6, 4, 6, 4)
            node_layout.setSpacing(2)
            symbol_label = QLabel(symbol)
            symbol_label.setObjectName("setupSolutionSymbol")
            symbol_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption_label = QLabel(caption)
            caption_label.setObjectName("setupSolutionCaption")
            caption_label.setProperty("active", index == 1)
            caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            node_layout.addWidget(symbol_label)
            node_layout.addWidget(caption_label)
            flow_layout.addWidget(node, 1)
            if index < 3:
                arrow = QLabel("→")
                arrow.setObjectName("setupSolutionArrow")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                flow_layout.addWidget(arrow)
        solution_body_layout.addWidget(solution_flow)
        settings_layout.addWidget(self.solution_card)

        self.convergence_card, convergence_layout = self._config_card("4. CONVERGENCE")
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
        chart.hide()
        visual_chart = QFrame()
        visual_chart.setObjectName("setupConvergenceChart")
        chart_layout = QHBoxLayout(visual_chart)
        chart_layout.setContentsMargins(18, 8, 8, 2)
        chart_layout.setSpacing(6)
        chart_layout.addStretch(1)
        for height, converged in ((50, False), (36, False), (16, True)):
            bar = QFrame()
            bar.setObjectName("setupConvergenceBar")
            bar.setProperty("converged", converged)
            bar.setFixedSize(18, height)
            chart_layout.addWidget(bar, 0, Qt.AlignmentFlag.AlignBottom)
        convergence_row.addWidget(visual_chart, 1)
        convergence_layout.addLayout(convergence_row)

        # Nonlinear Static only (see _apply_convergence_display) - summarizes
        # the existing algorithm-fallback + step-bisection recovery that
        # nonlinear_static_solver.py already does on a failed step, so a
        # non-converged step does not read as an unexplained dead end. The
        # recovery logic itself is untouched; this only describes it.
        self.convergence_recovery_row = QWidget()
        recovery_layout = QHBoxLayout(self.convergence_recovery_row)
        recovery_layout.setContentsMargins(0, 8, 0, 0)
        recovery_layout.setSpacing(18)
        bisections_block = QVBoxLayout()
        bisections_block.setSpacing(2)
        bisections_label = QLabel("MAX STEP BISECTIONS")
        bisections_label.setObjectName("setupMetricLabel")
        self.convergence_bisections_value = QLabel("4")
        self.convergence_bisections_value.setObjectName("setupMetricValue")
        bisections_block.addWidget(bisections_label)
        bisections_block.addWidget(self.convergence_bisections_value)
        recovery_layout.addLayout(bisections_block)
        self.convergence_recovery_summary = QLabel()
        self.convergence_recovery_summary.setObjectName("secondaryText")
        self.convergence_recovery_summary.setWordWrap(True)
        recovery_layout.addWidget(self.convergence_recovery_summary, 1)
        convergence_layout.addWidget(self.convergence_recovery_row)
        self.convergence_recovery_row.hide()

        settings_layout.addWidget(self.convergence_card)

        settings_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("setupSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(settings)
        layout.addWidget(scroll, 1)

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
            self._update_linear_static_summary()
            self._update_nonlinear_behavior_tiles()
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
        self._update_linear_static_summary()
        self._update_nonlinear_behavior_tiles()

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
        kind = self.selected_analysis_kind()
        self.config_store.set_kind(kind)
        self._sync_store_options()
        # Refreshes SOLUTION METHOD/CONVERGENCE against the new kind's
        # ANALYSIS_CAPABILITIES entry - without this, switching kinds would
        # leave the previous kind's readouts (or editable/fixed SOLVER
        # visibility) stuck on screen until some dialog field happened to
        # change and trigger it indirectly.
        self._update_nonlinear_summary()
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
        kind = self.selected_analysis_kind()
        self.nonlinear_group.setVisible(kind == AnalysisKind.NONLINEAR_STATIC)
        self.time_history_group.setVisible(kind == AnalysisKind.TIME_HISTORY)
        # Linear Static gets its own compact LOADS/ANALYSIS METHOD card instead
        # of the shared "1. LOAD & CONTROL" card (Gravity/Lateral/Control/Steps
        # describe Nonlinear Static's pushover staging, not a single-step linear
        # solve), and starts SOLUTION METHOD collapsed since every value in it
        # is ENGINE_FIXED for this kind. Modal replaces "1. LOAD & CONTROL" and
        # "3. SOLUTION METHOD" outright with its own EIGEN SOLUTION card (see
        # modal_engine_card) instead of collapsing the shared one, since Modal
        # needs an extra Static Integrator row the shared grid does not have.
        # Nonlinear Static and Time History's layout is untouched either way.
        is_linear_static = kind == AnalysisKind.LINEAR_STATIC
        is_modal = kind == AnalysisKind.MODAL
        is_nonlinear_static = kind == AnalysisKind.NONLINEAR_STATIC
        self.load_card.setVisible(not is_linear_static and not is_modal)
        # Nonlinear Static gets its own Load/Displacement-Control-aware row set
        # inside "1. LOAD & CONTROL" instead of the generic (never-updated
        # Gravity/Lateral) grid; Time History still uses the generic grid
        # exactly as before.
        self.nonlinear_load_summary.setVisible(is_nonlinear_static)
        self.load_content_widget.setVisible(not is_nonlinear_static)
        if is_nonlinear_static:
            self._update_nonlinear_load_summary()
            self._update_nonlinear_behavior_tiles()
        self.linear_static_group.setVisible(is_linear_static)
        self.modal_group.setVisible(is_modal)
        self.modal_engine_card.setVisible(is_modal)
        self.solution_card.setVisible(not is_modal)
        self.engine_details_toggle.setVisible(is_linear_static)
        if is_linear_static:
            # Always re-collapsed on entry, never remembers a previous expand -
            # switching kinds must not leave this kind's own state stale either.
            self.engine_details_toggle.setChecked(False)
            self.solution_body.setVisible(False)
            self._update_linear_static_summary()
        else:
            self.solution_body.setVisible(True)
        if is_modal:
            self.modal_engine_details_toggle.setChecked(False)
            self.modal_engine_details_body.setVisible(False)

    def _toggle_engine_details(self, expanded: bool) -> None:
        self.solution_body.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        self.engine_details_toggle.setText(f"{arrow}  ADVANCED ENGINE DETAILS")

    def _toggle_modal_engine_details(self, expanded: bool) -> None:
        self.modal_engine_details_body.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        self.modal_engine_details_toggle.setText(f"{arrow}  ADVANCED ENGINE DETAILS")

    def _update_linear_static_summary(self) -> None:
        if self._model is None:
            self.linear_static_load_value.setText("No model loaded")
            return
        patterns = self._pattern_tags(self._model)
        self.linear_static_load_value.setText(
            ", ".join(f"Pattern {tag}" for tag in patterns)
            if patterns
            else "No load patterns detected"
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
        self._sync_store_options()

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
        self.load_control_value.setText(integrator)
        self.load_steps_value.setText(str(self.num_steps.value()))
        self.load_progress.setMaximum(max(1, self.num_steps.value()))
        self.load_progress.setValue(self.num_steps.value())
        self.load_progress_caption.setText(f"100% ({self.num_steps.value()} Steps)")
        self._update_engine_capability_display()
        self._update_nonlinear_load_summary()
        self._sync_store_options()

    def _update_nonlinear_load_summary(self) -> None:
        """Populate self.nonlinear_load_summary's row set - shown instead of
        the generic load_content_widget only for Nonlinear Static (see
        _update_nonlinear_visibility). Reads the exact same dialog widgets
        build_options() already reads; no new state."""
        rows = self._nonlinear_load_rows
        gravity = self.gravity_pattern.currentText() if self.gravity_pattern.count() else "NONE"
        lateral = (
            self.lateral_pattern.currentText()
            if self.lateral_pattern.count()
            else "ALL NON-GRAVITY PATTERNS"
        )
        rows["gravity_pattern"][1].setText(gravity)
        rows["lateral_pattern"][1].setText(lateral)
        rows["control_method"][1].setText(self.integrator_type.currentText())
        is_displacement_control = self.integrator_type.currentData() == "DisplacementControl"
        for key in ("gravity_pattern", "lateral_pattern", "control_method"):
            for widget in rows[key]:
                widget.setVisible(True)
        for key in ("load_steps",):
            for widget in rows[key]:
                widget.setVisible(not is_displacement_control)
        for key in ("control_node", "control_dof", "target_displacement"):
            for widget in rows[key]:
                widget.setVisible(is_displacement_control)
        if is_displacement_control:
            rows["control_node"][1].setText(self.control_node.currentText() or "not set")
            rows["control_dof"][1].setText(self.control_dof.currentText())
            rows["target_displacement"][1].setText(
                f"{self.target_displacement.value():g} {self._unit_system.length}"
            )
        else:
            rows["load_steps"][1].setText(str(self.num_steps.value()))

    def _update_nonlinear_behavior_tiles(self) -> None:
        """MATERIAL NONLINEARITY used to always read "✓ Detected in Model"
        regardless of the actual model - a hardcoded claim, never checked.
        StructuralModel only carries element_type (not material/section/
        geomTransf type names, which live only inside the solver's own
        ModelCommandCollector and never reach the imported domain object - see
        model_importer.py), so that is the one signal checked here: real, but
        only a partial proxy for "material nonlinearity" in the fullest sense.
        GEOMETRIC NONLINEARITY is left unresolved rather than guessed - the
        imported script's own geomTransf choice is not visible from
        StructuralModel at all, and the script-import Nonlinear Static solver
        applies no P-Delta/Corotational handling of its own either way."""
        if self._model is None:
            self.material_nonlinearity_value.setText("—")
            self.material_nonlinearity_value.setProperty("state", "off")
        else:
            nonlinear_elements = [
                element
                for element in self._model.elements.values()
                if element.element_type.lower() in _NONLINEAR_ELEMENT_TYPES
            ]
            if nonlinear_elements:
                self.material_nonlinearity_value.setText(
                    f"✓  Nonlinear element type ({len(nonlinear_elements)})"
                )
                self.material_nonlinearity_value.setProperty("state", "ok")
            else:
                self.material_nonlinearity_value.setText("○  Not detected by element type")
                self.material_nonlinearity_value.setProperty("state", "off")
        self.material_nonlinearity_value.style().unpolish(self.material_nonlinearity_value)
        self.material_nonlinearity_value.style().polish(self.material_nonlinearity_value)
        self.geometric_nonlinearity_value.setText("Not tracked here")
        self.geometric_nonlinearity_value.setProperty("state", "off")

    def _update_engine_capability_display(self) -> None:
        """Make SOLUTION METHOD/CONVERGENCE show what the current AnalysisKind's
        engine actually does (ANALYSIS_CAPABILITIES) instead of always mirroring
        the Nonlinear Settings dialog regardless of kind. This is also where the
        Known Issue from the Phase 2 investigation gets fixed: CONSTRAINT/
        NUMBERER used to be two independent QLabels never wired to anything -
        they are now real readouts, EDITABLE-mirroring for Nonlinear Static and
        ENGINE_FIXED-displaying for the other three kinds."""
        capabilities = ANALYSIS_CAPABILITIES[self.selected_analysis_kind()]
        self._apply_solver_field(capabilities.equation_solver)
        self._apply_metric_field(
            self.solution_algorithm, capabilities.algorithm, self.algorithm.currentText()
        )
        self._apply_metric_field(
            self.constraint_value,
            capabilities.constraint_handler,
            self.constraints_type.currentText(),
        )
        self._apply_metric_field(
            self.numberer_value, capabilities.numberer, self.numberer.currentText()
        )
        self._apply_convergence_display(capabilities.convergence_test)

    def _apply_solver_field(self, field: ComponentField) -> None:
        """SOLVER is the one component with a real always-present editable
        widget (self.solver) rather than a read-only mirror label - so instead
        of a text swap, this toggles which of the two same-cell widgets
        (self.solver / self.solver_fixed_value) is visible."""
        editable = field.state == FieldState.EDITABLE
        self.solver.setVisible(editable)
        self.solver_fixed_value.setVisible(not editable)
        if not editable:
            badge = "AUTO" if field.state == FieldState.AUTOMATIC else "FIXED"
            self.solver_fixed_value.setText(f"{field.value}   ·   {badge}")

    @staticmethod
    def _apply_metric_field(label: QLabel, field: ComponentField, live_text: str) -> None:
        if field.state == FieldState.EDITABLE:
            label.setText(live_text)
        elif field.state == FieldState.NOT_APPLICABLE:
            label.setText("N/A")
        else:
            badge = "AUTO" if field.state == FieldState.AUTOMATIC else "FIXED"
            label.setText(f"{field.value}   ·   {badge}")

    def _apply_convergence_display(self, field: ComponentField) -> None:
        # Neither Linear Static nor Modal ever iterate to convergence - showing
        # this card for them would imply a Newton/tolerance loop that never
        # actually runs, so the whole card is hidden rather than shown with a
        # misleading N/A (the card has no single "value" cell to label N/A).
        if field.state == FieldState.NOT_APPLICABLE:
            self.convergence_card.setVisible(False)
            return
        self.convergence_card.setVisible(True)
        if field.state == FieldState.EDITABLE:
            self.convergence_test.setText(self.test_type.currentText())
            self.convergence_tolerance.setText(f"{self.tolerance.value():.1E}")
            self.convergence_iterations.setText(str(self.max_iterations.value()))
            self.convergence_recovery_row.setVisible(True)
            self.convergence_bisections_value.setText(str(self.max_bisections.value()))
            self.convergence_recovery_summary.setText(
                "Recovery Strategy: Automatic\n"
                f"Step Bisection: up to {self.max_bisections.value()} levels "
                "(a step that still does not converge is reported as partial, "
                "not a structural collapse)"
            )
            return
        self.convergence_recovery_row.setVisible(False)
        details = dict(field.details)
        badge = "AUTO" if field.state == FieldState.AUTOMATIC else "FIXED"
        self.convergence_test.setText(f"{field.value}   ·   {badge}" if field.value else "N/A")
        self.convergence_tolerance.setText(details.get("tolerance", "—"))
        self.convergence_iterations.setText(details.get("maxIterations", "—"))

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
