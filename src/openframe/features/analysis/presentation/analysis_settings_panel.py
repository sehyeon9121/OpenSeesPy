"""Analysis type and solver settings panel."""

import importlib.util
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
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
from openframe.features.analysis.presentation.time_history_direction_row import (
    TimeHistoryDirectionRow,
)
from openframe.infrastructure.ground_motions import BuiltInGroundMotionCatalog

#: DOF labels by ndm, matching the order OpenSeesPy reports node results in.
_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")

#: Sentinel GEOMETRIC TRANSFORMATION value meaning "install no override -
#: keep each element's own geomTransf exactly as the model defines it".
#: Mirrors nonlinear_static_solver.py's own ``_USE_MODEL_DEFINITION``.
_USE_MODEL_DEFINITION = "UseModelDefinition"
#: Geometrically-nonlinear transform type names (lowercased) - used both to
#: judge an explicit override choice and to summarize a model's own
#: transformations under "Use model definition".
_GEOMETRIC_NONLINEAR_TRANSFORM_TYPES = frozenset({"pdelta", "corotational"})

#: Mirrors nonlinear_static_solver.py's own `nonlinear_elements` set exactly -
#: element_type is the only element-level nonlinearity signal StructuralModel
#: carries (material/section type names are collector-internal and never
#: reach the imported StructuralModel - see model_importer.py), so this is
#: duplicated here rather than imported, matching how the solver's other
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

#: Mirrors buckling_solver.py's own ``_LARGE_SYSTEM_DOF_WARNING_THRESHOLD``.
#: The PRE-CHECK card can only estimate this (nodes x ndf, ignoring
#: constraints/restraints - the exact system DOF count is only known once the
#: solver actually builds the model), so it is always an upper bound, never
#: exact - fine for a "this may be slow" warning, which does not need to be
#: precise to be useful.
_LARGE_MODEL_ESTIMATED_DOF_THRESHOLD = 500


class _SetupInputWheelGuard(QObject):
    """Prevent a setup value from changing merely because the pointer is over it.

    Wheel input over a field inside the main settings scroll area is converted
    into page scrolling. If a guarded field has no scrollable ancestor, its
    wheel input is simply consumed; click, keyboard, and drop-down editing are
    unaffected.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return super().eventFilter(watched, event)

        ancestor = watched.parent()
        while ancestor is not None and not isinstance(ancestor, QAbstractScrollArea):
            ancestor = ancestor.parent()

        if isinstance(ancestor, QAbstractScrollArea):
            pixel_delta = event.pixelDelta().y()
            angle_delta = event.angleDelta().y()
            delta = pixel_delta
            if not delta and angle_delta:
                step = max(1, ancestor.verticalScrollBar().singleStep())
                delta = round(angle_delta / 120 * step * 3)
            if delta:
                bar = ancestor.verticalScrollBar()
                bar.setValue(bar.value() - delta)

        event.accept()
        return True


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
        self.analysis_type.addItem("Elastic Buckling", AnalysisKind.BUCKLING)
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

        settings_layout.addWidget(self.load_card)

        # Linear Static's own compact card, shown instead of self.load_card
        # (whose Gravity/Lateral/Control/Steps rows are Nonlinear-Static-shaped
        # and mean nothing for a single-step linear solve) - see
        # _update_kind_specific_layout. Load pattern data reuses the same
        # _pattern_tags() helper the Nonlinear inline GRAVITY/LATERAL PATTERN
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
        review_badge = QLabel("EDIT INLINE")
        review_badge.setObjectName("setupReviewBadge")
        nonlinear_title_row.addWidget(review_badge)
        nonlinear_layout.addLayout(nonlinear_title_row)

        nonlinear_layout.addWidget(self._field_label("GEOMETRIC TRANSFORMATION"))
        self.geometric_transformation = QComboBox()
        # "Linear" stays index 0 - the combo's own inert default before any
        # model is loaded (nothing to derive an origin-aware default from
        # yet); set_model() below immediately re-picks the origin-aware
        # default for whatever model actually gets loaded.
        self.geometric_transformation.addItem("Linear", "Linear")
        self.geometric_transformation.addItem("P-Delta", "PDelta")
        self.geometric_transformation.addItem("Corotational", "Corotational")
        self.geometric_transformation.addItem("Use model definition", _USE_MODEL_DEFINITION)
        self.geometric_transformation.setToolTip(
            "'Use model definition' installs no override - every element keeps exactly "
            "the geomTransf its own script/import defines (the default for an imported "
            "model). Linear/P-Delta/Corotational instead override every "
            "ops.geomTransf(...) call the model makes, so the chosen type - not "
            "whatever the model itself specifies - controls the analysis; this fails "
            "atomically before the run starts if the model contains any transform type "
            "the override cannot safely replace. Linear ignores P-Delta/large-"
            "displacement effects entirely; P-Delta adds axial-load-times-displacement "
            "moments; Corotational adds full large-displacement/large-rotation "
            "kinematics on top of that."
        )
        self.geometric_transformation.currentIndexChanged.connect(
            self._update_nonlinear_behavior_tiles
        )
        self.geometric_transformation.currentIndexChanged.connect(self._update_nonlinear_summary)
        nonlinear_layout.addWidget(self.geometric_transformation)

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

        self.geometric_nonlinearity_notice = QLabel()
        self.geometric_nonlinearity_notice.setObjectName("setupNotice")
        self.geometric_nonlinearity_notice.setWordWrap(True)
        nonlinear_layout.addWidget(self.geometric_nonlinearity_notice)
        self._build_nonlinear_inline_editor(nonlinear_layout)
        settings_layout.addWidget(self.nonlinear_group)

        # Modal analysis only needs how many modes to compute, so a compact card
        # is sufficient unlike nonlinear's interdependent workflow. Extraction
        # method picks between a fixed count and an automatic count driven by
        # cumulative mass participation; only one of modal_fixed_group/
        # modal_target_group is ever visible (see _update_modal_extraction_visibility).
        self.modal_group = QFrame()
        self.modal_group.setObjectName("setupConfigCard")
        modal_layout = QVBoxLayout(self.modal_group)
        modal_layout.setContentsMargins(12, 10, 12, 10)
        modal_layout.setSpacing(8)
        modal_title = QLabel("MODAL PARAMETERS")
        modal_title.setObjectName("setupConfigTitle")
        modal_layout.addWidget(modal_title)

        modal_layout.addWidget(self._field_label("EXTRACTION METHOD"))
        self.modal_extraction_method = QComboBox()
        self.modal_extraction_method.addItem("Fixed Number of Modes", "fixed")
        self.modal_extraction_method.addItem("Target Mass Participation", "target")
        self.modal_extraction_method.setToolTip(
            "Fixed always computes exactly NUMBER OF MODES modes, even if cumulative "
            "mass participation reaches 100% earlier. Target keeps adding modes "
            "until every selected direction reaches TARGET PARTICIPATION, up to "
            "MAXIMUM MODES."
        )
        self.modal_extraction_method.currentIndexChanged.connect(
            self._update_modal_extraction_visibility
        )
        self.modal_extraction_method.currentIndexChanged.connect(self._sync_store_options)
        modal_layout.addWidget(self.modal_extraction_method)

        self.modal_fixed_group = QWidget()
        modal_fixed_layout = QVBoxLayout(self.modal_fixed_group)
        modal_fixed_layout.setContentsMargins(0, 0, 0, 0)
        modal_fixed_layout.setSpacing(8)
        modal_fixed_layout.addWidget(self._field_label("NUMBER OF MODES"))
        self.num_modes = QSpinBox()
        self.num_modes.setRange(1, 200)
        self.num_modes.setValue(10)
        self.num_modes.setToolTip(
            "The model's own script must define nodal mass (ops.mass(...)) - modal "
            "analysis has no natural frequency to find without it. Every mode up to "
            "this count is computed even if cumulative mass participation reaches "
            "100% earlier."
        )
        # Every other option widget in this file syncs on change (see self.solver
        # above, the inline spinners/combos below) - num_modes was missing this,
        # so a value typed here was silently dropped until some unrelated event
        # (e.g. switching AnalysisKind away and back) happened to call
        # _sync_store_options() anyway. RUN ANALYSIS reads config_store.options
        # directly (see MainWindow._run_analysis), not a fresh build_options()
        # call, so this was a real bug, not just a cosmetic one.
        self.num_modes.valueChanged.connect(self._sync_store_options)
        modal_fixed_layout.addWidget(self.num_modes)
        modal_layout.addWidget(self.modal_fixed_group)

        self.modal_target_group = QWidget()
        modal_target_layout = QVBoxLayout(self.modal_target_group)
        modal_target_layout.setContentsMargins(0, 0, 0, 0)
        modal_target_layout.setSpacing(8)

        modal_target_layout.addWidget(self._field_label("TARGET PARTICIPATION (%)"))
        self.modal_target_participation = QDoubleSpinBox()
        self.modal_target_participation.setRange(0.1, 100.0)
        self.modal_target_participation.setDecimals(1)
        self.modal_target_participation.setSingleStep(1.0)
        self.modal_target_participation.setValue(90.0)
        self.modal_target_participation.setToolTip(
            "Modes keep being added until every checked direction's cumulative "
            "mass participation reaches this percentage."
        )
        self.modal_target_participation.valueChanged.connect(self._sync_store_options)
        modal_target_layout.addWidget(self.modal_target_participation)

        modal_target_layout.addWidget(self._field_label("TARGET DIRECTIONS"))
        directions_row = QHBoxLayout()
        directions_row.setSpacing(10)
        self.modal_target_direction_checks: dict[str, QCheckBox] = {}
        for direction in ("X", "Y", "Z", "RX", "RY", "RZ"):
            checkbox = QCheckBox(direction)
            checkbox.setChecked(direction in ("X", "Y"))
            checkbox.toggled.connect(self._sync_store_options)
            self.modal_target_direction_checks[direction] = checkbox
            directions_row.addWidget(checkbox)
        directions_row.addStretch(1)
        modal_target_layout.addLayout(directions_row)

        modal_target_layout.addWidget(self._field_label("MAXIMUM MODES"))
        self.modal_max_modes = QSpinBox()
        self.modal_max_modes.setRange(1, 500)
        self.modal_max_modes.setValue(50)
        self.modal_max_modes.setToolTip(
            "Upper bound on how many modes Target Mass Participation will compute, "
            "so a target that is never reached (e.g. no mass in a selected "
            "direction) cannot loop indefinitely."
        )
        self.modal_max_modes.valueChanged.connect(self._sync_store_options)
        modal_target_layout.addWidget(self.modal_max_modes)
        modal_layout.addWidget(self.modal_target_group)
        self._update_modal_extraction_visibility()

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

        # Elastic Buckling - Model -> Reference Load -> Buckling Parameters ->
        # Pre-check -> Run, a short flow like Modal's (no "3. SOLUTION METHOD"/
        # "4. CONVERGENCE" cards: buckling_solver.py's engine components are all
        # ENGINE_FIXED, see ANALYSIS_CAPABILITIES[AnalysisKind.BUCKLING]).
        self.buckling_group = QFrame()
        self.buckling_group.setObjectName("setupConfigCard")
        buckling_layout = QVBoxLayout(self.buckling_group)
        buckling_layout.setContentsMargins(12, 10, 12, 10)
        buckling_layout.setSpacing(12)

        reference_load_title = QLabel("REFERENCE LOAD")
        reference_load_title.setObjectName("setupConfigTitle")
        buckling_layout.addWidget(reference_load_title)
        reference_load_grid = QGridLayout()
        reference_load_grid.setHorizontalSpacing(16)
        reference_load_grid.setVerticalSpacing(9)
        reference_load_grid.setColumnStretch(0, 1)
        reference_load_grid.setColumnStretch(1, 1)

        self.buckling_load_case = QComboBox()
        self.buckling_load_case.addItem("All Patterns (current static load)", None)
        self.buckling_load_case.setToolTip(
            "Which static load pattern(s) make up the reference load - 'All "
            "Patterns' combines every load pattern currently defined in the "
            "model, or pick one specific pattern. Only plain, static (Linear/"
            "Constant TimeSeries) patterns can be used as a reference load."
        )
        self.buckling_load_case.currentIndexChanged.connect(self._update_buckling_summary)

        self.buckling_reference_load_scale = QDoubleSpinBox()
        self.buckling_reference_load_scale.setDecimals(6)
        self.buckling_reference_load_scale.setRange(-1.0e6, 1.0e6)
        self.buckling_reference_load_scale.setSingleStep(0.1)
        self.buckling_reference_load_scale.setValue(1.0)
        self.buckling_reference_load_scale.setToolTip(
            "Scales the reference load pattern before the buckling solve - the "
            "reported Buckling Load Factor already accounts for this, so "
            "Critical Load = Buckling Load Factor x (Reference Load Case x this "
            "scale) either way. Cannot be 0."
        )
        self.buckling_reference_load_scale.valueChanged.connect(self._update_buckling_summary)

        reference_load_grid.addWidget(
            self._field_block("LOAD CASE", self.buckling_load_case), 0, 0
        )
        reference_load_grid.addWidget(
            self._field_block("REFERENCE LOAD SCALE", self.buckling_reference_load_scale), 0, 1
        )
        buckling_layout.addLayout(reference_load_grid)

        buckling_divider = QFrame()
        buckling_divider.setObjectName("setupGuideDivider")
        buckling_divider.setFrameShape(QFrame.Shape.HLine)
        buckling_layout.addWidget(buckling_divider)

        buckling_params_title = QLabel("BUCKLING PARAMETERS")
        buckling_params_title.setObjectName("setupConfigTitle")
        buckling_layout.addWidget(buckling_params_title)
        buckling_params_grid = QGridLayout()
        buckling_params_grid.setHorizontalSpacing(16)
        buckling_params_grid.setVerticalSpacing(9)
        buckling_params_grid.setColumnStretch(0, 1)
        buckling_params_grid.setColumnStretch(1, 1)

        self.buckling_num_modes = QSpinBox()
        self.buckling_num_modes.setRange(1, 100)
        self.buckling_num_modes.setValue(5)
        self.buckling_num_modes.setToolTip(
            "How many buckling modes to report, sorted by ascending Buckling Load "
            "Factor - the first is the Critical Buckling Factor. Fewer may be "
            "returned than requested if fewer valid (finite, real, positive) "
            "eigenvalues exist."
        )
        self.buckling_num_modes.valueChanged.connect(self._update_buckling_summary)

        self.buckling_geometric_transform = QComboBox()
        # Officially restricted to P-Delta for now - the Euler-column closed-
        # form validation this feature's accuracy rests on was only ever run
        # against PDelta. Corotational/"From Model" are not offered here yet
        # (buckling_solver.py rejects them with a clear "not yet supported"
        # message if ever reached some other way); Linear is never offered
        # for a separate, permanent reason - it produces no geometric
        # stiffness at all, so a buckling run against it can only ever fail
        # (buckling_solver.py's own explicit rejection is the real guard,
        # this combo is a second line of defense).
        self.buckling_geometric_transform.addItem("P-Delta", "PDelta")
        self.buckling_geometric_transform.setEnabled(False)
        self.buckling_geometric_transform.setToolTip(
            "P-Delta overrides every ops.geomTransf(...) call the model makes "
            "(same mechanism as Nonlinear Static's own GEOMETRIC "
            "TRANSFORMATION). Only P-Delta is offered for now - Corotational "
            "and 'From Model' will be added once separately validated for "
            "buckling."
        )
        self.buckling_geometric_transform.currentIndexChanged.connect(
            self._update_buckling_summary
        )

        self.buckling_eigenvalue_tolerance = QDoubleSpinBox()
        self.buckling_eigenvalue_tolerance.setDecimals(8)
        self.buckling_eigenvalue_tolerance.setRange(0.0, 1.0)
        self.buckling_eigenvalue_tolerance.setSpecialValueText("AUTO")
        self.buckling_eigenvalue_tolerance.setToolTip(
            "How large an eigenvalue's imaginary part may be (relative to its "
            "magnitude) and still be accepted as real. AUTO (0) uses 1e-6."
        )
        self.buckling_eigenvalue_tolerance.valueChanged.connect(self._update_buckling_summary)

        buckling_params_grid.addWidget(
            self._field_block("NUMBER OF MODES", self.buckling_num_modes), 0, 0
        )
        buckling_params_grid.addWidget(
            self._field_block("GEOMETRIC TRANSFORM", self.buckling_geometric_transform), 0, 1
        )
        buckling_params_grid.addWidget(
            self._field_block("EIGENVALUE TOLERANCE", self.buckling_eigenvalue_tolerance), 1, 0
        )
        buckling_layout.addLayout(buckling_params_grid)
        settings_layout.addWidget(self.buckling_group)

        self.buckling_precheck_card = QFrame()
        self.buckling_precheck_card.setObjectName("setupConfigCard")
        buckling_precheck_layout = QVBoxLayout(self.buckling_precheck_card)
        buckling_precheck_layout.setContentsMargins(12, 10, 12, 10)
        buckling_precheck_layout.setSpacing(9)
        buckling_precheck_title = QLabel("PRE-CHECK")
        buckling_precheck_title.setObjectName("setupConfigTitle")
        buckling_precheck_layout.addWidget(buckling_precheck_title)
        buckling_precheck_grid = QGridLayout()
        buckling_precheck_grid.setHorizontalSpacing(24)
        buckling_precheck_grid.setVerticalSpacing(5)
        self.buckling_precheck_value_labels: dict[str, QLabel] = {}
        for row, key in enumerate(
            (
                "Reference Load",
                "Geometric Transform",
                "Number of Modes",
                "Model Size",
                "SciPy",
            )
        ):
            key_label = QLabel(f"{key}:")
            key_label.setObjectName("setupMetricLabel")
            value_label = QLabel("—")
            value_label.setObjectName("setupMetricValue")
            buckling_precheck_grid.addWidget(key_label, row, 0)
            buckling_precheck_grid.addWidget(value_label, row, 1)
            self.buckling_precheck_value_labels[key] = value_label
        buckling_precheck_layout.addLayout(buckling_precheck_grid)
        self.buckling_precheck_note = QLabel(
            "Elastic global buckling based on the selected reference load pattern. "
            "Material yielding, imperfections and local section buckling are not "
            "included."
        )
        self.buckling_precheck_note.setObjectName("secondaryText")
        self.buckling_precheck_note.setWordWrap(True)
        buckling_precheck_layout.addWidget(self.buckling_precheck_note)
        # Non-blocking - large models still run, just slowly (see
        # buckling_solver.py's own _LARGE_SYSTEM_DOF_WARNING_THRESHOLD, mirrored
        # here as an upper-bound estimate since the exact system DOF count after
        # constraints is only known once the solver actually builds the model).
        self.buckling_large_model_note = QLabel()
        self.buckling_large_model_note.setObjectName("setupNotice")
        self.buckling_large_model_note.setWordWrap(True)
        self.buckling_large_model_note.setVisible(False)
        buckling_precheck_layout.addWidget(self.buckling_large_model_note)
        self.buckling_precheck_status = QLabel("Ready for Analysis")
        self.buckling_precheck_status.setObjectName("setupBehaviorValue")
        self.buckling_precheck_status.setProperty("state", "ok")
        self.buckling_precheck_status.setWordWrap(True)
        buckling_precheck_layout.addWidget(self.buckling_precheck_status)
        settings_layout.addWidget(self.buckling_precheck_card)

        # Time History's 8-card flow: Ground Motion -> Analysis Time -> Damping
        # -> Time Integration -> Solution Strategy -> Adaptive Recovery ->
        # Pre-check -> Run. self.time_history_group stays the single widget
        # whose visibility means "Time History is selected" (existing tests
        # reach through it); every field below is a real, solver-consumed
        # option (see build_options()'s TIME_HISTORY branch and
        # time_history_solver.py), not a read-only ENGINE_FIXED display.
        self.time_history_group = QFrame()
        time_history_outer_layout = QVBoxLayout(self.time_history_group)
        time_history_outer_layout.setContentsMargins(0, 0, 0, 0)
        time_history_outer_layout.setSpacing(16)

        self._builtin_catalog = BuiltInGroundMotionCatalog()
        self._time_history_length_unit = DEFAULT_UNIT_SYSTEM.length
        self._time_history_ndm = 2

        # -- 1. GROUND MOTION ------------------------------------------------
        self.time_history_ground_motion_card, ground_motion_layout = self._config_card(
            "1. GROUND MOTION"
        )
        relative_response_note = QLabel(
            "Each active direction below applies its own UniformExcitation "
            "pattern. Results (displacement/velocity/acceleration) are "
            "RELATIVE to the ground, not absolute/total."
        )
        relative_response_note.setObjectName("secondaryText")
        relative_response_note.setWordWrap(True)
        ground_motion_layout.addWidget(relative_response_note)
        self.time_history_direction_rows_widget = QWidget()
        self._direction_rows_layout = QVBoxLayout(self.time_history_direction_rows_widget)
        self._direction_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._direction_rows_layout.setSpacing(8)
        ground_motion_layout.addWidget(self.time_history_direction_rows_widget)
        self.time_history_direction_rows: list[TimeHistoryDirectionRow] = []
        self._rebuild_direction_rows(2)
        time_history_outer_layout.addWidget(self.time_history_ground_motion_card)

        # -- 2. ANALYSIS TIME -------------------------------------------------
        self.time_history_analysis_time_card, analysis_time_layout = self._config_card(
            "2. ANALYSIS TIME"
        )
        duration_mode_row = QHBoxLayout()
        self.duration_mode_group = QButtonGroup(self)
        self.duration_full_radio = QRadioButton("Full Record")
        self.duration_custom_radio = QRadioButton("Custom")
        self.duration_full_radio.setChecked(True)
        self.duration_mode_group.addButton(self.duration_full_radio)
        self.duration_mode_group.addButton(self.duration_custom_radio)
        self.duration_full_radio.toggled.connect(self._update_analysis_time_status)
        duration_mode_row.addWidget(self._field_label("DURATION MODE"))
        duration_mode_row.addWidget(self.duration_full_radio)
        duration_mode_row.addWidget(self.duration_custom_radio)
        duration_mode_row.addStretch(1)
        analysis_time_layout.addLayout(duration_mode_row)

        analysis_time_grid = QGridLayout()
        analysis_time_grid.setHorizontalSpacing(16)
        analysis_time_grid.setVerticalSpacing(9)
        self.analysis_end_time = QDoubleSpinBox()
        self.analysis_end_time.setRange(0.0, 1.0e6)
        self.analysis_end_time.setDecimals(4)
        self.analysis_end_time.setSpecialValueText("Auto (longest active duration)")
        self.analysis_time_step = QDoubleSpinBox()
        self.analysis_time_step.setRange(0.0, 1.0e6)
        self.analysis_time_step.setDecimals(6)
        self.analysis_time_step.setSpecialValueText("Auto (shortest active record dt)")
        self.analysis_max_time_step = QDoubleSpinBox()
        self.analysis_max_time_step.setRange(0.0, 1.0e6)
        self.analysis_max_time_step.setDecimals(6)
        self.analysis_max_time_step.setSpecialValueText("Auto (= Analysis Time Step)")
        for spin in (self.analysis_end_time, self.analysis_time_step, self.analysis_max_time_step):
            spin.valueChanged.connect(self._update_analysis_time_status)
        analysis_time_grid.addWidget(self._field_block("END TIME", self.analysis_end_time), 0, 0)
        analysis_time_grid.addWidget(
            self._field_block("ANALYSIS TIME STEP", self.analysis_time_step), 0, 1
        )
        analysis_time_grid.addWidget(
            self._field_block("MAXIMUM TIME STEP", self.analysis_max_time_step), 1, 0
        )
        analysis_time_layout.addLayout(analysis_time_grid)

        analysis_time_status_row = QHBoxLayout()
        self.analysis_time_status = QLabel("AUTO")
        self.analysis_time_status.setObjectName("setupBehaviorValue")
        self.analysis_time_status.setProperty("state", "off")
        self.reset_analysis_time_button = QPushButton("Reset to Default")
        self.reset_analysis_time_button.clicked.connect(self._reset_analysis_time)
        analysis_time_status_row.addWidget(self.analysis_time_status)
        analysis_time_status_row.addStretch(1)
        analysis_time_status_row.addWidget(self.reset_analysis_time_button)
        analysis_time_layout.addLayout(analysis_time_status_row)
        time_history_outer_layout.addWidget(self.time_history_analysis_time_card)

        # -- 3. DAMPING --------------------------------------------------------
        self.time_history_damping_card, damping_layout = self._config_card("3. DAMPING")
        damping_mode_row = QHBoxLayout()
        self.damping_mode_group = QButtonGroup(self)
        self.damping_none_radio = QRadioButton("None")
        self.damping_modal_radio = QRadioButton("Rayleigh — Modal Targets")
        self.damping_direct_radio = QRadioButton("Rayleigh — Direct Coefficients")
        self.damping_modal_radio.setChecked(True)
        for radio in (self.damping_none_radio, self.damping_modal_radio, self.damping_direct_radio):
            self.damping_mode_group.addButton(radio)
            radio.toggled.connect(self._update_damping_visibility)
        damping_mode_row.addWidget(self.damping_none_radio)
        damping_mode_row.addWidget(self.damping_modal_radio)
        damping_mode_row.addWidget(self.damping_direct_radio)
        damping_layout.addLayout(damping_mode_row)

        self.damping_modal_group = QWidget()
        modal_damping_layout = QGridLayout(self.damping_modal_group)
        modal_damping_layout.setContentsMargins(0, 8, 0, 0)
        modal_damping_layout.setHorizontalSpacing(16)
        modal_damping_layout.setVerticalSpacing(9)
        self.damping_mode_i = QSpinBox()
        self.damping_mode_i.setRange(1, 500)
        self.damping_mode_i.setValue(1)
        self.damping_mode_j = QSpinBox()
        self.damping_mode_j.setRange(1, 500)
        self.damping_mode_j.setValue(2)
        self.damping_ratio_i = QDoubleSpinBox()
        self.damping_ratio_i.setRange(0.0, 1.0)
        self.damping_ratio_i.setDecimals(4)
        self.damping_ratio_i.setSingleStep(0.01)
        self.damping_ratio_i.setValue(0.05)
        self.damping_ratio_j = QDoubleSpinBox()
        self.damping_ratio_j.setRange(0.0, 1.0)
        self.damping_ratio_j.setDecimals(4)
        self.damping_ratio_j.setSingleStep(0.01)
        self.damping_ratio_j.setValue(0.05)
        self.damping_stiffness_term = QComboBox()
        self.damping_stiffness_term.addItem("Initial Stiffness", "initial")
        self.damping_stiffness_term.addItem("Current Stiffness", "current")
        self.damping_stiffness_term.addItem("Last Committed Stiffness", "last_committed")
        for widget in (
            self.damping_mode_i,
            self.damping_mode_j,
            self.damping_ratio_i,
            self.damping_ratio_j,
        ):
            widget.valueChanged.connect(self._sync_store_options)
        self.damping_stiffness_term.currentIndexChanged.connect(self._sync_store_options)
        modal_damping_layout.addWidget(self._field_block("MODE i", self.damping_mode_i), 0, 0)
        modal_damping_layout.addWidget(self._field_block("MODE j", self.damping_mode_j), 0, 1)
        modal_damping_layout.addWidget(
            self._field_block("DAMPING RATIO AT MODE i", self.damping_ratio_i), 1, 0
        )
        modal_damping_layout.addWidget(
            self._field_block("DAMPING RATIO AT MODE j", self.damping_ratio_j), 1, 1
        )
        modal_damping_layout.addWidget(
            self._field_block("STIFFNESS TERM", self.damping_stiffness_term), 2, 0, 1, 2
        )
        modal_computed_note = QLabel(
            "alphaM/betaK (or betaKInit/betaKComm) are computed from these two "
            "modes' own natural frequencies at run time and shown read-only in "
            "the result's settings summary - not entered directly."
        )
        modal_computed_note.setObjectName("secondaryText")
        modal_computed_note.setWordWrap(True)
        modal_damping_layout.addWidget(modal_computed_note, 3, 0, 1, 2)
        damping_layout.addWidget(self.damping_modal_group)

        self.damping_direct_group = QWidget()
        direct_damping_layout = QGridLayout(self.damping_direct_group)
        direct_damping_layout.setContentsMargins(0, 8, 0, 0)
        direct_damping_layout.setHorizontalSpacing(16)
        direct_damping_layout.setVerticalSpacing(9)
        self.damping_alpha_m = QDoubleSpinBox()
        self.damping_beta_k = QDoubleSpinBox()
        self.damping_beta_k_init = QDoubleSpinBox()
        self.damping_beta_k_comm = QDoubleSpinBox()
        for widget in (
            self.damping_alpha_m,
            self.damping_beta_k,
            self.damping_beta_k_init,
            self.damping_beta_k_comm,
        ):
            widget.setRange(-1.0e6, 1.0e6)
            widget.setDecimals(8)
            widget.valueChanged.connect(self._sync_store_options)
        direct_damping_layout.addWidget(self._field_block("alphaM", self.damping_alpha_m), 0, 0)
        direct_damping_layout.addWidget(self._field_block("betaK", self.damping_beta_k), 0, 1)
        direct_damping_layout.addWidget(
            self._field_block("betaKInit", self.damping_beta_k_init), 1, 0
        )
        direct_damping_layout.addWidget(
            self._field_block("betaKComm", self.damping_beta_k_comm), 1, 1
        )
        damping_layout.addWidget(self.damping_direct_group)
        self._update_damping_visibility()
        time_history_outer_layout.addWidget(self.time_history_damping_card)

        # -- 4. TIME INTEGRATION ------------------------------------------------
        self.time_history_integration_card, integration_layout = self._config_card(
            "4. TIME INTEGRATION"
        )
        integrator_mode_row = QHBoxLayout()
        self.integrator_type_group = QButtonGroup(self)
        self.integrator_newmark_radio = QRadioButton("Newmark")
        self.integrator_hht_radio = QRadioButton("HHT")
        self.integrator_newmark_radio.setChecked(True)
        self.integrator_type_group.addButton(self.integrator_newmark_radio)
        self.integrator_type_group.addButton(self.integrator_hht_radio)
        for radio in (self.integrator_newmark_radio, self.integrator_hht_radio):
            radio.toggled.connect(self._update_integrator_type_visibility)
        integrator_mode_row.addWidget(self.integrator_newmark_radio)
        integrator_mode_row.addWidget(self.integrator_hht_radio)
        integrator_mode_row.addStretch(1)
        integration_layout.addLayout(integrator_mode_row)

        self.newmark_group = QWidget()
        newmark_grid = QGridLayout(self.newmark_group)
        newmark_grid.setContentsMargins(0, 8, 0, 0)
        newmark_grid.setHorizontalSpacing(16)
        self.newmark_gamma = QDoubleSpinBox()
        self.newmark_gamma.setRange(0.0001, 10.0)
        self.newmark_gamma.setDecimals(4)
        self.newmark_gamma.setValue(0.5)
        self.newmark_beta = QDoubleSpinBox()
        self.newmark_beta.setRange(0.0001, 10.0)
        self.newmark_beta.setDecimals(4)
        self.newmark_beta.setValue(0.25)
        for widget in (self.newmark_gamma, self.newmark_beta):
            widget.valueChanged.connect(self._sync_store_options)
        newmark_grid.addWidget(self._field_block("GAMMA", self.newmark_gamma), 0, 0)
        newmark_grid.addWidget(self._field_block("BETA", self.newmark_beta), 0, 1)
        integration_layout.addWidget(self.newmark_group)

        self.hht_group = QWidget()
        hht_layout = QVBoxLayout(self.hht_group)
        hht_layout.setContentsMargins(0, 8, 0, 0)
        hht_layout.setSpacing(9)
        hht_top_grid = QGridLayout()
        hht_top_grid.setHorizontalSpacing(16)
        self.hht_alpha = QDoubleSpinBox()
        self.hht_alpha.setRange(0.67, 1.0)
        self.hht_alpha.setDecimals(4)
        self.hht_alpha.setValue(0.9)
        self.hht_alpha.valueChanged.connect(self._sync_store_options)
        hht_top_grid.addWidget(self._field_block("ALPHA", self.hht_alpha), 0, 0)
        hht_layout.addLayout(hht_top_grid)
        hht_parameter_row = QHBoxLayout()
        self.hht_parameter_mode_group = QButtonGroup(self)
        self.hht_auto_radio = QRadioButton("Auto Gamma/Beta")
        self.hht_custom_radio = QRadioButton("Custom Gamma/Beta")
        self.hht_auto_radio.setChecked(True)
        self.hht_parameter_mode_group.addButton(self.hht_auto_radio)
        self.hht_parameter_mode_group.addButton(self.hht_custom_radio)
        for radio in (self.hht_auto_radio, self.hht_custom_radio):
            radio.toggled.connect(self._update_hht_parameter_mode_visibility)
        hht_parameter_row.addWidget(self.hht_auto_radio)
        hht_parameter_row.addWidget(self.hht_custom_radio)
        hht_parameter_row.addStretch(1)
        hht_layout.addLayout(hht_parameter_row)
        self.hht_custom_group = QWidget()
        hht_custom_grid = QGridLayout(self.hht_custom_group)
        hht_custom_grid.setContentsMargins(0, 0, 0, 0)
        hht_custom_grid.setHorizontalSpacing(16)
        self.hht_gamma = QDoubleSpinBox()
        self.hht_gamma.setRange(0.0001, 10.0)
        self.hht_gamma.setDecimals(4)
        self.hht_gamma.setValue(0.6)
        self.hht_beta = QDoubleSpinBox()
        self.hht_beta.setRange(0.0001, 10.0)
        self.hht_beta.setDecimals(4)
        self.hht_beta.setValue(0.3025)
        for widget in (self.hht_gamma, self.hht_beta):
            widget.valueChanged.connect(self._sync_store_options)
        hht_custom_grid.addWidget(self._field_block("GAMMA", self.hht_gamma), 0, 0)
        hht_custom_grid.addWidget(self._field_block("BETA", self.hht_beta), 0, 1)
        hht_layout.addWidget(self.hht_custom_group)
        integration_layout.addWidget(self.hht_group)
        self._update_integrator_type_visibility()
        self._update_hht_parameter_mode_visibility()
        time_history_outer_layout.addWidget(self.time_history_integration_card)

        # -- 5. SOLUTION STRATEGY ------------------------------------------------
        self.time_history_solution_card, solution_layout_th = self._config_card(
            "5. SOLUTION STRATEGY"
        )
        self.th_algorithm = QComboBox()
        self.th_algorithm.addItems(("Newton", "ModifiedNewton", "KrylovNewton", "NewtonLineSearch"))
        self.th_test_type = QComboBox()
        self.th_test_type.addItems(("NormDispIncr", "NormUnbalance", "EnergyIncr"))
        self.th_tolerance = QDoubleSpinBox()
        self.th_tolerance.setDecimals(10)
        self.th_tolerance.setRange(1.0e-12, 1.0)
        self.th_tolerance.setSingleStep(1.0e-8)
        self.th_tolerance.setValue(1.0e-8)
        self.th_max_iterations = QSpinBox()
        self.th_max_iterations.setRange(1, 1000)
        self.th_max_iterations.setValue(30)
        self.th_constraints_type = QComboBox()
        self.th_constraints_type.addItems(("Transformation", "Plain"))
        self.th_numberer = QComboBox()
        self.th_numberer.addItems(("RCM", "Plain", "AMD"))
        self.th_system = QComboBox()
        self.th_system.addItems(("BandGeneral", "UmfPack", "ProfileSPD"))
        solution_grid_th = QGridLayout()
        solution_grid_th.setHorizontalSpacing(16)
        solution_grid_th.setVerticalSpacing(9)
        for index, block in enumerate(
            (
                self._field_block("ALGORITHM", self.th_algorithm),
                self._field_block("CONVERGENCE TEST", self.th_test_type),
                self._field_block("TOLERANCE", self.th_tolerance),
                self._field_block("MAXIMUM ITERATIONS", self.th_max_iterations),
                self._field_block("CONSTRAINT HANDLER", self.th_constraints_type),
                self._field_block("NUMBERER", self.th_numberer),
                self._field_block("EQUATION SOLVER", self.th_system),
            )
        ):
            solution_grid_th.addWidget(block, index // 2, index % 2)
        solution_layout_th.addLayout(solution_grid_th)
        for combo in (
            self.th_algorithm,
            self.th_test_type,
            self.th_constraints_type,
            self.th_numberer,
            self.th_system,
        ):
            combo.currentIndexChanged.connect(self._update_solution_strategy_status_th)
        for spinner in (self.th_tolerance, self.th_max_iterations):
            spinner.valueChanged.connect(self._update_solution_strategy_status_th)
        solution_status_row_th = QHBoxLayout()
        self.th_solution_strategy_status = QLabel("DEFAULT")
        self.th_solution_strategy_status.setObjectName("setupBehaviorValue")
        self.th_solution_strategy_status.setProperty("state", "off")
        self.th_reset_solution_strategy_button = QPushButton("Reset to Default")
        self.th_reset_solution_strategy_button.clicked.connect(self._reset_solution_strategy_th)
        solution_status_row_th.addWidget(self.th_solution_strategy_status)
        solution_status_row_th.addStretch(1)
        solution_status_row_th.addWidget(self.th_reset_solution_strategy_button)
        solution_layout_th.addLayout(solution_status_row_th)
        time_history_outer_layout.addWidget(self.time_history_solution_card)

        # -- 6. ADAPTIVE RECOVERY ------------------------------------------------
        self.time_history_recovery_card, recovery_layout_th = self._config_card(
            "6. ADAPTIVE RECOVERY"
        )
        self.th_automatic_recovery = QCheckBox(
            "Automatic Recovery - fall back to other algorithms, then shrink the "
            "time step, before ending the run at this point"
        )
        self.th_automatic_recovery.setChecked(True)
        self.th_automatic_recovery.toggled.connect(self._update_recovery_field_states_th)
        self.th_automatic_recovery.toggled.connect(self._sync_store_options)
        recovery_layout_th.addWidget(self.th_automatic_recovery)
        self.th_algorithm_fallback = QCheckBox(
            "Algorithm Fallback - try the other standard algorithms at the same "
            "time step before shrinking it"
        )
        self.th_algorithm_fallback.setChecked(True)
        self.th_algorithm_fallback.toggled.connect(self._sync_store_options)
        recovery_layout_th.addWidget(self.th_algorithm_fallback)

        recovery_grid_th = QGridLayout()
        recovery_grid_th.setHorizontalSpacing(16)
        recovery_grid_th.setVerticalSpacing(9)
        self.th_min_time_step = QDoubleSpinBox()
        self.th_min_time_step.setRange(0.0, 1.0e6)
        self.th_min_time_step.setDecimals(8)
        self.th_min_time_step.setSpecialValueText("Auto (Analysis Time Step / 16)")
        self.th_reduction_factor = QDoubleSpinBox()
        self.th_reduction_factor.setRange(0.01, 0.99)
        self.th_reduction_factor.setDecimals(3)
        self.th_reduction_factor.setSingleStep(0.05)
        self.th_reduction_factor.setValue(0.5)
        self.th_restoration_factor = QDoubleSpinBox()
        self.th_restoration_factor.setRange(1.01, 10.0)
        self.th_restoration_factor.setDecimals(3)
        self.th_restoration_factor.setSingleStep(0.1)
        self.th_restoration_factor.setValue(1.5)
        self.th_max_reductions = QSpinBox()
        self.th_max_reductions.setRange(0, 20)
        self.th_max_reductions.setValue(4)
        self.th_clean_steps_to_restore = QSpinBox()
        self.th_clean_steps_to_restore.setRange(1, 1000)
        self.th_clean_steps_to_restore.setValue(5)
        for widget in (
            self.th_min_time_step,
            self.th_reduction_factor,
            self.th_restoration_factor,
            self.th_max_reductions,
            self.th_clean_steps_to_restore,
        ):
            widget.valueChanged.connect(self._sync_store_options)
        recovery_grid_th.addWidget(
            self._field_block("MINIMUM TIME STEP", self.th_min_time_step), 0, 0
        )
        recovery_grid_th.addWidget(
            self._field_block("TIME STEP REDUCTION", self.th_reduction_factor), 0, 1
        )
        recovery_grid_th.addWidget(
            self._field_block("TIME STEP RESTORATION", self.th_restoration_factor), 1, 0
        )
        recovery_grid_th.addWidget(
            self._field_block("MAXIMUM STEP REDUCTIONS", self.th_max_reductions), 1, 1
        )
        recovery_grid_th.addWidget(
            self._field_block("CLEAN STEPS TO RESTORE", self.th_clean_steps_to_restore), 2, 0
        )
        recovery_layout_th.addLayout(recovery_grid_th)
        recovery_note_th = QLabel(
            "Uses MAXIMUM TIME STEP from Analysis Time as the ceiling a reduced "
            "step is allowed to grow back to."
        )
        recovery_note_th.setObjectName("secondaryText")
        recovery_note_th.setWordWrap(True)
        recovery_layout_th.addWidget(recovery_note_th)
        self._update_recovery_field_states_th()
        time_history_outer_layout.addWidget(self.time_history_recovery_card)

        # -- 7. PRE-CHECK ------------------------------------------------------
        self.time_history_precheck_card, precheck_layout_th = self._config_card("7. PRE-CHECK")
        precheck_grid_th = QGridLayout()
        precheck_grid_th.setHorizontalSpacing(24)
        precheck_grid_th.setVerticalSpacing(5)
        self.th_precheck_value_labels: dict[str, QLabel] = {}
        for row, key in enumerate(
            (
                "Active Directions",
                "End Time / Analysis dt",
                "Damping",
                "Time Integration",
                "Automatic Recovery",
            )
        ):
            key_label = QLabel(f"{key}:")
            key_label.setObjectName("setupMetricLabel")
            value_label = QLabel("—")
            value_label.setObjectName("setupMetricValue")
            precheck_grid_th.addWidget(key_label, row, 0)
            precheck_grid_th.addWidget(value_label, row, 1)
            self.th_precheck_value_labels[key] = value_label
        precheck_layout_th.addLayout(precheck_grid_th)
        self.th_precheck_status = QLabel("Ready for Analysis")
        self.th_precheck_status.setObjectName("setupBehaviorValue")
        self.th_precheck_status.setProperty("state", "ok")
        self.th_precheck_status.setWordWrap(True)
        precheck_layout_th.addWidget(self.th_precheck_status)
        time_history_outer_layout.addWidget(self.time_history_precheck_card)

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

        self._setup_input_wheel_guard = _SetupInputWheelGuard(self)
        for combo in self.findChildren(QComboBox):
            combo.installEventFilter(self._setup_input_wheel_guard)
        for spinner in self.findChildren(QAbstractSpinBox):
            spinner.installEventFilter(self._setup_input_wheel_guard)
        self.solver.currentIndexChanged.connect(self._update_nonlinear_summary)
        self._update_nonlinear_visibility()
        self._update_nonlinear_summary()
        self._update_solution_strategy_status_th()
        # Must run after every widget above exists - _on_direction_row_changed()
        # ends in _sync_store_options()/build_options(), which (for whatever
        # AnalysisKind the combo defaults to) reads widgets built throughout
        # this constructor, not just the ground-motion ones.
        self._on_direction_row_changed()

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

    def _build_nonlinear_inline_editor(self, parent_layout: QVBoxLayout) -> None:
        """Build the nonlinear workflow directly in SETUP instead of a modal dialog."""
        introduction = QLabel(
            "Set how the structure is pushed below. Recommended solver defaults are "
            "already applied in Advanced Solution & Convergence; collapse it once "
            "you're happy with them."
        )
        introduction.setObjectName("secondaryText")
        introduction.setWordWrap(True)
        parent_layout.addWidget(introduction)

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
        self.integrator_type.addItem("Arc-Length Control", "ArcLength")
        self.integrator_type.setToolTip(
            "LoadControl scales every pattern by an equal load factor each step - it "
            "cannot trace a softening/post-peak branch. DisplacementControl pushes "
            "CONTROL NODE/DOF by a fixed increment and solves for the load, so it can. "
            "Arc-Length Control instead lets the equilibrium path itself decide how far "
            "each step advances (ops.integrator('ArcLength', radius, alpha)) - the only "
            "one of the three that can trace past a limit point, where the load factor "
            "decreases while displacement keeps growing."
        )
        self.integrator_type.currentIndexChanged.connect(self._update_integrator_visibility)

        self.num_steps = QSpinBox()
        # Published nonlinear benchmarks commonly need several thousand small
        # displacement increments (the official OpenSees two-story moment frame
        # uses 3,240), so the old 1,000-step ceiling prevented exact reproduction.
        self.num_steps.setRange(1, 100_000)
        self.num_steps.setValue(10)

        self.target_load_factor = QDoubleSpinBox()
        self.target_load_factor.setDecimals(4)
        self.target_load_factor.setRange(0.0001, 1000.0)
        self.target_load_factor.setSingleStep(0.1)
        self.target_load_factor.setValue(1.0)
        self.target_load_factor.setToolTip(
            "The load factor every active pattern reaches by the final step - 1.0 "
            "applies each pattern's loads exactly as defined. LOAD INCREMENT below "
            "is always TARGET LOAD FACTOR / ANALYSIS STEPS, so changing either one "
            "keeps the other consistent automatically."
        )
        self.target_load_factor_group = self._field_block(
            "TARGET LOAD FACTOR", self.target_load_factor
        )
        self.load_increment_value = QLabel("—")
        self.load_increment_value.setObjectName("setupMetricValue")
        self.load_increment_group = self._field_block(
            "LOAD INCREMENT (per step, derived)", self.load_increment_value
        )

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
        self.initial_increment_value = QLabel("—")
        self.initial_increment_value.setObjectName("setupMetricValue")
        self.initial_increment_group = self._field_block(
            "INITIAL INCREMENT (per step, derived)", self.initial_increment_value
        )

        self.control_node_group = self._field_block("CONTROL NODE", self.control_node)
        self.control_dof_group = self._field_block("CONTROL DOF", self.control_dof)
        self.num_steps_group = self._field_block("ANALYSIS STEPS", self.num_steps)

        # Arc-Length Control's own fields - shown only when INTEGRATOR is ArcLength
        # (see _update_integrator_visibility). MAX STEP BISECTIONS (further below, in
        # the advanced grid) is reused as-is for the radius-reduction retry limit - see
        # _advance_one_arc_length_step in nonlinear_static_solver.py - so no separate
        # "max reductions" field is introduced here.
        self.arc_length_radius = QDoubleSpinBox()
        self.arc_length_radius.setDecimals(6)
        self.arc_length_radius.setRange(1.0e-6, 1.0e6)
        self.arc_length_radius.setSingleStep(0.001)
        self.arc_length_radius.setValue(0.01)
        self.arc_length_radius.setToolTip(
            "The arc-length radius 's' in ops.integrator('ArcLength', s, alpha) - how "
            "far the equilibrium path advances each step, in a combined load/"
            "displacement sense. Retried at half this size (down to MINIMUM RADIUS) "
            "when a step will not converge."
        )
        self.arc_length_alpha = QDoubleSpinBox()
        self.arc_length_alpha.setDecimals(4)
        self.arc_length_alpha.setRange(0.0001, 1000.0)
        self.arc_length_alpha.setSingleStep(0.1)
        self.arc_length_alpha.setValue(1.0)
        self.arc_length_alpha.setToolTip(
            "The 'alpha' scale factor in ops.integrator('ArcLength', s, alpha), "
            "weighting the load-factor term against the displacement term in the "
            "arc-length constraint. 1.0 is the standard default."
        )
        self.arc_length_max_steps = QSpinBox()
        self.arc_length_max_steps.setRange(1, 100_000)
        self.arc_length_max_steps.setValue(200)
        self.arc_length_max_steps.setToolTip(
            "Arc-Length's own step count - independent of ANALYSIS STEPS (which "
            "LoadControl/DisplacementControl use instead). This is the default "
            "termination criterion: the run stops here unless MAXIMUM ABSOLUTE "
            "DISPLACEMENT ends it earlier."
        )
        self.arc_length_min_radius = QDoubleSpinBox()
        self.arc_length_min_radius.setDecimals(8)
        self.arc_length_min_radius.setRange(1.0e-8, 1.0e6)
        self.arc_length_min_radius.setSingleStep(0.0001)
        self.arc_length_min_radius.setValue(0.0001)
        self.arc_length_min_radius.setToolTip(
            "Stop halving the radius once the next attempt would fall below this "
            "size - a step still not converged there is reported as partial, not a "
            "structural collapse."
        )
        self.arc_length_max_radius = QDoubleSpinBox()
        self.arc_length_max_radius.setDecimals(6)
        self.arc_length_max_radius.setRange(1.0e-6, 1.0e6)
        self.arc_length_max_radius.setSingleStep(0.001)
        self.arc_length_max_radius.setValue(0.01)
        self.arc_length_max_radius.setToolTip(
            "With ADAPTIVE RADIUS on, caps how far a reduced radius may grow back "
            "after clean steps - never exceeds this even if it would otherwise grow "
            "past it."
        )
        self.arc_length_adaptive = QCheckBox(
            "Adaptive Radius - grow a reduced radius back toward ARC-LENGTH RADIUS "
            "after steps that converge cleanly"
        )
        self.arc_length_adaptive.setToolTip(
            "OFF (default): every step starts at the full ARC-LENGTH RADIUS. ON: a "
            "step that needed reduction hands its smaller working radius to the next "
            "step instead of rediscovering it from scratch, and grows back toward "
            "ARC-LENGTH RADIUS after clean steps, bounded by MAXIMUM RADIUS."
        )
        self.arc_length_adaptive.toggled.connect(self._update_nonlinear_summary)
        self.arc_length_control_node = QComboBox()
        self.arc_length_control_node.addItem("Use Control Node", None)
        self.arc_length_control_node.setToolTip(
            "Optional - which node's displacement the MAXIMUM ABSOLUTE DISPLACEMENT "
            "termination monitors. Defaults to CONTROL NODE above when left as 'Use "
            "Control Node'."
        )
        self.arc_length_control_dof = QComboBox()
        self.arc_length_control_dof.addItem("Use Control DOF", None)
        self.arc_length_control_dof.setToolTip(
            "Optional - paired with MONITOR NODE above. Defaults to CONTROL DOF "
            "when left as 'Use Control DOF'."
        )
        self.arc_length_max_displacement = QDoubleSpinBox()
        self.arc_length_max_displacement.setDecimals(6)
        self.arc_length_max_displacement.setRange(0.0, 1.0e6)
        self.arc_length_max_displacement.setSpecialValueText("None")
        self.arc_length_max_displacement.setSuffix(f" {self._unit_system.length}")
        self.arc_length_max_displacement.setToolTip(
            "Optional early termination: stop (cleanly, not as a failure) once the "
            "monitor node/DOF's absolute displacement reaches this value. 0 = None "
            "(run until MAXIMUM STEPS instead)."
        )
        self.arc_length_radius_group = self._field_block(
            "ARC-LENGTH RADIUS (s)", self.arc_length_radius
        )
        self.arc_length_alpha_group = self._field_block(
            "REFERENCE LOAD SCALE (alpha)", self.arc_length_alpha
        )
        self.arc_length_max_steps_group = self._field_block(
            "MAXIMUM STEPS", self.arc_length_max_steps
        )
        self.arc_length_min_radius_group = self._field_block(
            "MINIMUM RADIUS", self.arc_length_min_radius
        )
        self.arc_length_max_radius_group = self._field_block(
            "MAXIMUM RADIUS", self.arc_length_max_radius
        )
        self.arc_length_control_node_group = self._field_block(
            "MONITOR NODE (optional)", self.arc_length_control_node
        )
        self.arc_length_control_dof_group = self._field_block(
            "MONITOR DOF (optional)", self.arc_length_control_dof
        )
        self.arc_length_max_displacement_group = self._field_block(
            "MAXIMUM ABSOLUTE DISPLACEMENT (optional)", self.arc_length_max_displacement
        )
        #: Every widget that only makes sense for Arc-Length Control - shown/hidden as
        #: one group by _update_integrator_visibility, independent of the Load
        #: Control/Displacement Control fields above.
        self.arc_length_field_groups = [
            self.arc_length_radius_group,
            self.arc_length_alpha_group,
            self.arc_length_max_steps_group,
            self.arc_length_adaptive,
            self.arc_length_min_radius_group,
            self.arc_length_max_radius_group,
            self.arc_length_control_node_group,
            self.arc_length_control_dof_group,
            self.arc_length_max_displacement_group,
        ]

        left_column = [
            self._field_block("GRAVITY PATTERN", self.gravity_pattern),
            self.gravity_steps_group,
            self._field_block("LATERAL LOAD PATTERN", self.lateral_pattern),
            self._field_block("INTEGRATOR", self.integrator_type),
            self.num_steps_group,
            self.target_load_factor_group,
            self.load_increment_group,
            self.target_displacement_group,
            self.initial_increment_group,
            self.control_node_group,
            self.control_dof_group,
            *self.arc_length_field_groups,
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
        #: This single field/label is shared by all three INTEGRATORs - a step
        #: bisection depth for LoadControl/DisplacementControl, an Arc-Length
        #: radius-reduction count for ArcLength (see _advance_one_arc_length_step) -
        #: rather than adding a second field, per Setup's own "reuse the existing
        #: Algorithm fallback structure" instruction. _update_integrator_visibility
        #: swaps its label/tooltip text to match whichever meaning currently
        #: applies, so "bisection" wording never shows while Arc-Length is selected.
        self.max_bisections_label = self._field_label("MAX STEP BISECTIONS")

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

        self.solver = QComboBox()
        self.solver.addItems(("BandGeneral", "UmfPack", "ProfileSPD"))
        self.solver.currentIndexChanged.connect(self._sync_store_options)

        right_column = [
            self._field_block("TOLERANCE", self.tolerance),
            self._field_block("MAX ITERATIONS", self.max_iterations),
            self._field_block(None, self.max_bisections, label=self.max_bisections_label),
            self._field_block("MAX RUNTIME (SECONDS)", self.execution_timeout),
            self._field_block("CONVERGENCE TEST", self.test_type),
        ]

        essential = QFrame()
        essential.setObjectName("nonlinearSetupSection")
        essential_layout = QVBoxLayout(essential)
        essential_layout.setContentsMargins(12, 10, 12, 12)
        essential_layout.setSpacing(9)
        essential_title = QLabel("LOAD & CONTROL")
        essential_title.setObjectName("setupConfigTitle")
        essential_layout.addWidget(essential_title)
        essential_note = QLabel(
            "Choose the load patterns and the quantity that controls each analysis step."
        )
        essential_note.setObjectName("secondaryText")
        essential_layout.addWidget(essential_note)
        essential_grid = QGridLayout()
        essential_grid.setHorizontalSpacing(16)
        essential_grid.setVerticalSpacing(9)
        essential_grid.setColumnStretch(0, 1)
        essential_grid.setColumnStretch(1, 1)
        for index, block in enumerate(left_column):
            essential_grid.addWidget(block, index // 2, index % 2)
        essential_layout.addLayout(essential_grid)
        parent_layout.addWidget(essential)

        self.nonlinear_advanced_toggle = QPushButton(
            "\N{BLACK RIGHT-POINTING SMALL TRIANGLE}  ADVANCED SOLUTION && CONVERGENCE"
        )
        self.nonlinear_advanced_toggle.setObjectName("nonlinearAdvancedToggle")
        self.nonlinear_advanced_toggle.setCheckable(True)
        self.nonlinear_advanced_toggle.setFlat(True)
        self.nonlinear_advanced_toggle.toggled.connect(
            self._toggle_nonlinear_advanced_settings
        )
        parent_layout.addWidget(self.nonlinear_advanced_toggle)

        self.nonlinear_advanced_body = QFrame()
        self.nonlinear_advanced_body.setObjectName("nonlinearSetupSection")
        advanced_layout = QVBoxLayout(self.nonlinear_advanced_body)
        advanced_layout.setContentsMargins(12, 10, 12, 12)
        advanced_layout.setSpacing(9)
        advanced_title_row = QHBoxLayout()
        advanced_title_row.setContentsMargins(0, 0, 0, 0)
        advanced_title = QLabel("SOLUTION, CONVERGENCE & EXECUTION")
        advanced_title.setObjectName("setupConfigTitle")
        advanced_title_row.addWidget(advanced_title)
        advanced_title_row.addStretch(1)
        self.solution_strategy_status = QLabel("DEFAULT")
        self.solution_strategy_status.setObjectName("setupBehaviorValue")
        self.solution_strategy_status.setProperty("state", "off")
        advanced_title_row.addWidget(self.solution_strategy_status)
        self.reset_solution_strategy_button = QPushButton("Reset to Default")
        self.reset_solution_strategy_button.setObjectName("nonlinearSettingsButton")
        self.reset_solution_strategy_button.clicked.connect(self._reset_solution_strategy)
        advanced_title_row.addWidget(self.reset_solution_strategy_button)
        advanced_layout.addLayout(advanced_title_row)
        advanced_note = QLabel(
            "Defaults suit most models. Adjust these values when convergence is slow "
            "or when the imported model uses multi-point constraints."
        )
        advanced_note.setObjectName("secondaryText")
        advanced_note.setWordWrap(True)
        advanced_layout.addWidget(advanced_note)
        advanced_grid = QGridLayout()
        advanced_grid.setHorizontalSpacing(16)
        advanced_grid.setVerticalSpacing(9)
        advanced_grid.setColumnStretch(0, 1)
        advanced_grid.setColumnStretch(1, 1)
        advanced_blocks = [
            self._field_block("EQUATION SOLVER", self.solver),
            self._field_block("ALGORITHM", self.algorithm),
            self._field_block("CONSTRAINT HANDLER", self.constraints_type),
            self._field_block("DOF NUMBERER", self.numberer),
            *right_column,
        ]
        for index, block in enumerate(advanced_blocks):
            advanced_grid.addWidget(block, index // 2, index % 2)
        advanced_layout.addLayout(advanced_grid)
        self.nonlinear_advanced_body.hide()
        parent_layout.addWidget(self.nonlinear_advanced_body)
        # Expanded by default: the collapsed toggle was easy to miss entirely,
        # so start open and let the user collapse it once they know it's there.
        self.nonlinear_advanced_toggle.setChecked(True)

        recovery = QFrame()
        recovery.setObjectName("nonlinearSetupSection")
        recovery_layout = QVBoxLayout(recovery)
        recovery_layout.setContentsMargins(12, 10, 12, 12)
        recovery_layout.setSpacing(9)
        recovery_title = QLabel("ADAPTIVE RECOVERY")
        recovery_title.setObjectName("setupConfigTitle")
        recovery_layout.addWidget(recovery_title)

        self.automatic_recovery = QCheckBox(
            "Automatic Recovery - retry a non-convergent step with the other "
            "standard algorithms, then a halved increment, before failing it"
        )
        self.automatic_recovery.setChecked(True)
        self.automatic_recovery.setToolTip(
            "ON (default): a step that fails to converge is retried with "
            "ModifiedNewton/KrylovNewton/NewtonLineSearch, then with the increment "
            "halved up to MAX STEP BISECTIONS times, before the run stops there. "
            "OFF (\"Use Settings Only\"): the configured ALGORITHM gets exactly one "
            "attempt at the full increment - no fallback, no bisection."
        )
        self.automatic_recovery.toggled.connect(self._update_recovery_field_states)
        self.automatic_recovery.toggled.connect(self._update_nonlinear_summary)
        recovery_layout.addWidget(self.automatic_recovery)

        self.adaptive_step = QCheckBox(
            "Adaptive Step - start each step where the previous one last "
            "succeeded instead of always retrying from the full increment"
        )
        self.adaptive_step.setToolTip(
            "OFF (default): every reporting step starts at the full nominal "
            "increment, exactly as ANALYSIS STEPS implies. ON: a step that needed "
            "bisection hands its smaller working size to the next step instead of "
            "rediscovering it from scratch, and grows back toward the full nominal "
            "increment after steps that converge cleanly (bounded by MIN/MAX "
            "INCREMENT below). The total number of reporting steps and the final "
            "target reached are unchanged either way."
        )
        self.adaptive_step.toggled.connect(self._update_nonlinear_summary)
        recovery_layout.addWidget(self.adaptive_step)

        self.min_increment = QDoubleSpinBox()
        self.min_increment.setDecimals(8)
        self.min_increment.setRange(0.0, 1.0e6)
        self.min_increment.setSpecialValueText("Auto")
        self.min_increment.setToolTip(
            "Stop bisecting once the next smaller attempt would fall below this "
            "size, instead of continuing down to MAX STEP BISECTIONS' depth limit "
            "regardless of how physically small that has become. 0 = Auto (depth "
            "limit only, today's behavior)."
        )
        self.max_increment = QDoubleSpinBox()
        self.max_increment.setDecimals(8)
        self.max_increment.setRange(0.0, 1.0e6)
        self.max_increment.setSpecialValueText("Auto")
        self.max_increment.setToolTip(
            "With Adaptive Step ON, caps how far the starting increment may grow "
            "back after clean steps. 0 = Auto (never exceeds the nominal increment "
            "ANALYSIS STEPS/TARGET LOAD FACTOR or TARGET DISPLACEMENT implies)."
        )
        self.min_increment_group = self._field_block("MIN INCREMENT", self.min_increment)
        self.max_increment_group = self._field_block("MAX INCREMENT", self.max_increment)
        recovery_grid = QGridLayout()
        recovery_grid.setHorizontalSpacing(16)
        recovery_grid.setVerticalSpacing(9)
        recovery_grid.setColumnStretch(0, 1)
        recovery_grid.setColumnStretch(1, 1)
        recovery_grid.addWidget(self.min_increment_group, 0, 0)
        recovery_grid.addWidget(self.max_increment_group, 0, 1)
        recovery_layout.addLayout(recovery_grid)

        recovery_note = QLabel(
            "Retries are bounded either way: at most one attempt per fallback "
            "algorithm (Newton, ModifiedNewton, KrylovNewton, NewtonLineSearch) "
            "per bisection depth, and at most MAX STEP BISECTIONS halvings - a "
            "step that still cannot converge always ends the run there rather "
            "than retrying forever."
        )
        recovery_note.setObjectName("secondaryText")
        recovery_note.setWordWrap(True)
        recovery_layout.addWidget(recovery_note)
        parent_layout.addWidget(recovery)

        self.precheck_card = QFrame()
        self.precheck_card.setObjectName("nonlinearSetupSection")
        precheck_layout = QVBoxLayout(self.precheck_card)
        precheck_layout.setContentsMargins(12, 10, 12, 12)
        precheck_layout.setSpacing(9)
        precheck_title = QLabel("PRE-CHECK")
        precheck_title.setObjectName("setupConfigTitle")
        precheck_layout.addWidget(precheck_title)
        precheck_grid = QGridLayout()
        precheck_grid.setHorizontalSpacing(24)
        precheck_grid.setVerticalSpacing(5)
        self.precheck_value_labels: dict[str, QLabel] = {}
        for row, key in enumerate(
            (
                "Geometric Nonlinearity",
                "Material Nonlinearity",
                "Control Method",
                "Initial Step",
                "Algorithm",
                "Convergence",
                "Automatic Recovery",
            )
        ):
            key_label = QLabel(f"{key}:")
            key_label.setObjectName("setupMetricLabel")
            value_label = QLabel("—")
            value_label.setObjectName("setupMetricValue")
            precheck_grid.addWidget(key_label, row, 0)
            precheck_grid.addWidget(value_label, row, 1)
            self.precheck_value_labels[key] = value_label
        precheck_layout.addLayout(precheck_grid)
        self.arc_length_precheck_note = QLabel(
            "Arc-Length Control can trace the equilibrium path even without material "
            "nonlinearity (an elastic model's geometric-nonlinearity path, for "
            "example) - but it does not correct for coarse element discretization, "
            "which still limits accuracy near a limit point the same way it does for "
            "P-Delta/Corotational."
        )
        self.arc_length_precheck_note.setObjectName("secondaryText")
        self.arc_length_precheck_note.setWordWrap(True)
        self.arc_length_precheck_note.setVisible(False)
        precheck_layout.addWidget(self.arc_length_precheck_note)
        self.precheck_status = QLabel("Ready for Analysis")
        self.precheck_status.setObjectName("setupBehaviorValue")
        self.precheck_status.setProperty("state", "ok")
        self.precheck_status.setWordWrap(True)
        precheck_layout.addWidget(self.precheck_status)
        parent_layout.addWidget(self.precheck_card)

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
            self.arc_length_control_node,
            self.arc_length_control_dof,
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
            self.target_load_factor,
            self.min_increment,
            self.max_increment,
            self.arc_length_radius,
            self.arc_length_alpha,
            self.arc_length_max_steps,
            self.arc_length_min_radius,
            self.arc_length_max_radius,
            self.arc_length_max_displacement,
        ):
            spinner.valueChanged.connect(self._update_nonlinear_summary)

        self._update_gravity_visibility()
        self._update_integrator_visibility()
        self._update_recovery_field_states()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        """Show the imported model's native length beside dimensional inputs."""
        self._unit_system = unit_system
        self.target_displacement_label.setText(
            f"TARGET DISPLACEMENT ({unit_system.length})"
        )
        self.target_displacement.setSuffix(f" {unit_system.length}")
        self.arc_length_max_displacement.setSuffix(f" {unit_system.length}")
        self._time_history_length_unit = unit_system.length
        for row in self.time_history_direction_rows:
            row.set_length_unit(unit_system.length)
        self._update_precheck_th()

    def _update_gravity_visibility(self) -> None:
        self.gravity_steps_group.setVisible(self.gravity_pattern.currentData() is not None)

    def _update_integrator_visibility(self) -> None:
        method = self.integrator_type.currentData()
        displacement_control = method == "DisplacementControl"
        arc_length = method == "ArcLength"
        load_control = method == "LoadControl"
        # CONTROL NODE/DOF are also needed for Arc-Length - they still drive the
        # load-displacement curve's x-axis and are the default MONITOR NODE/DOF
        # for MAXIMUM ABSOLUTE DISPLACEMENT - not only for DisplacementControl.
        self.control_node_group.setVisible(displacement_control or arc_length)
        self.control_dof_group.setVisible(displacement_control or arc_length)
        self.target_displacement_group.setVisible(displacement_control)
        self.initial_increment_group.setVisible(displacement_control)
        self.target_load_factor_group.setVisible(load_control)
        self.load_increment_group.setVisible(load_control)
        # ANALYSIS STEPS drives LoadControl/DisplacementControl's fixed per-step
        # increment - Arc-Length has no such increment and uses its own MAXIMUM
        # STEPS instead (arc_length_max_steps_group, part of arc_length_field_groups).
        self.num_steps_group.setVisible(not arc_length)
        for group in self.arc_length_field_groups:
            group.setVisible(arc_length)
        if arc_length:
            self.max_bisections_label.setText("MAXIMUM RADIUS REDUCTIONS")
            self.max_bisections.setToolTip(
                "When a step's Arc-Length Radius does not converge, halve it this "
                "many times (down to MINIMUM RADIUS) before marking the run as "
                "partially converged."
            )
        else:
            self.max_bisections_label.setText("MAX STEP BISECTIONS")
            self.max_bisections.setToolTip(
                "When an increment does not converge, halve it this many times "
                "before marking the run as partially converged."
            )

    def _apply_geometric_transformation_default(self, model: StructuralModel) -> None:
        """Direct Modeling defaults to an explicit Linear override - its
        canvas-exported script only ever contains one Linear geomTransf (see
        opensees_script_export.py) - while an imported model defaults to "Use
        model definition" so its own per-element transformations are
        preserved until the user explicitly asks to override them. Absence of
        the ``OPENFRAME_MODEL_ORIGIN`` declaration is always read as an
        import (see ``OpenSeesModelImporter._apply_model_origin``), never
        guessed at from model shape."""
        origin = str(model.metadata.get("model_origin", "import"))
        default_value = "Linear" if origin == "direct" else _USE_MODEL_DEFINITION
        self.geometric_transformation.blockSignals(True)
        self.geometric_transformation.setCurrentIndex(
            self.geometric_transformation.findData(default_value)
        )
        self.geometric_transformation.blockSignals(False)

    def set_model(self, model: StructuralModel | None) -> None:
        self._model = model
        self.control_node.clear()
        self.arc_length_control_node.clear()
        self.arc_length_control_node.addItem("Use Control Node", None)
        self.arc_length_control_dof.clear()
        self.arc_length_control_dof.addItem("Use Control DOF", None)
        self.buckling_load_case.clear()
        self.buckling_load_case.addItem("All Patterns (current static load)", None)
        if model is None:
            self._rebuild_direction_rows(2)
            self._on_direction_row_changed()
            self._update_nonlinear_summary()
            self._update_linear_static_summary()
            self._update_nonlinear_behavior_tiles()
            self._update_buckling_summary()
            return
        self._apply_geometric_transformation_default(model)
        for tag, node in sorted(model.nodes.items()):
            coordinates = (
                f"({node.x:g}, {node.y:g}, {node.z:g})"
                if model.ndm == 3
                else f"({node.x:g}, {node.y:g})"
            )
            self.control_node.addItem(f"Node {tag} {coordinates}", tag)
            self.arc_length_control_node.addItem(f"Node {tag} {coordinates}", tag)
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
            self.arc_length_control_dof.addItem(label, index)

        self._rebuild_direction_rows(model.ndm)
        self._on_direction_row_changed()

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
        self.buckling_load_case.blockSignals(True)
        for tag in self._pattern_tags(model):
            self.buckling_load_case.addItem(f"Pattern {tag}", tag)
        self.buckling_load_case.blockSignals(False)
        self._update_gravity_visibility()
        self._update_nonlinear_summary()
        self._update_linear_static_summary()
        self._update_nonlinear_behavior_tiles()
        self._update_buckling_summary()

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

    def apply_buckling_preset(self, options: dict[str, float | int | str | bool]) -> None:
        """Pre-fills the BUCKLING card from a template's own manifest so a
        first-time user opening a precision-analysis template lands on SETUP
        with the analysis type already picked and its options already
        sensible, instead of a blank "Linear Static" default they'd have no
        way to know to change.

        Deliberately scoped to buckling only - every other kind's options
        (control node, ground motion, ...) depend on the loaded model in
        ways a fixed preset dict cannot resolve on its own, unlike
        buckling's small, model-independent card (see ``build_options``'s
        BUCKLING branch: reference_load_scale/num_modes/geometric_transform_
        type, with "All Patterns" already the correct default reference load
        for a template with exactly one load pattern).

        Setting the combo (rather than calling ``config_store.set_kind``
        directly) is what actually drives the UI: it fires the same
        ``currentIndexChanged`` -> ``_analysis_type_changed`` path a user
        picking BUCKLING by hand would, which is what makes ``buckling_group``
        visible and updates the store to match - a direct store write would
        leave the combo (and the whole card) still showing whatever kind was
        selected before.
        """
        self.analysis_type.setCurrentIndex(self.analysis_type.findData(AnalysisKind.BUCKLING))
        if "num_modes" in options:
            self.buckling_num_modes.setValue(int(options["num_modes"]))
        if "reference_load_scale" in options:
            self.buckling_reference_load_scale.setValue(float(options["reference_load_scale"]))
        if "eigenvalue_tolerance" in options:
            self.buckling_eigenvalue_tolerance.setValue(float(options["eigenvalue_tolerance"]))

    def apply_time_history_preset(self, options: dict) -> None:
        """Pre-fills the TIME_HISTORY card's Ground Motion table from a
        template's own manifest - ``options["directions"]`` is a list of
        ``{"dof", "record_id"}`` dicts, each naming a row (by DOF) and a
        bundled ``BuiltInGroundMotionCatalog`` record (by id) to select on it,
        the same "already sensible, not blank" motivation as
        ``apply_buckling_preset``.

        Only handles Built-in records, not Imported files - a template ships
        inside the package, so any ground motion it points at must already be
        one of ``BuiltInGroundMotionCatalog``'s bundled ``.AT2`` files (see
        ``TimeHistoryDirectionRow.set_builtin_record``); an imported file
        would be a path on the *template author's* machine, meaningless on
        the end user's. Unit/scaling method are deliberately left at each
        row's own defaults (Unit "g", Direct Scale Factor 1.0) since PEER
        ``.AT2`` files are already in g and a first look at a template's
        response is meant to show the record applied as-is, unscaled.

        Called after ``set_model()`` has already rebuilt
        ``time_history_direction_rows`` for the real loaded model (see
        ``MainWindow._model_loaded``) - a stale row list from before the
        model loaded would silently match nothing.
        """
        self.analysis_type.setCurrentIndex(self.analysis_type.findData(AnalysisKind.TIME_HISTORY))
        for direction in options.get("directions", []):
            dof = int(direction["dof"])
            row = next((r for r in self.time_history_direction_rows if r.dof == dof), None)
            if row is None or "record_id" not in direction:
                continue
            if row.set_builtin_record(str(direction["record_id"])):
                row.enabled_checkbox.setChecked(True)

    def build_options(self) -> dict[str, float | int | str | bool]:
        """Return the settings this panel controls, in the shape
        ``run_nonlinear_static_analysis`` (and its worker.py/runner.py plumbing)
        expects. Only meaningful when ``selected_analysis_kind()`` is nonlinear
        static; other analysis kinds ignore ``AnalysisRequest.options`` entirely -
        except modal, whose solver takes different keyword arguments and would
        raise ``TypeError`` if handed this shape, so it gets its own early return."""
        if self.selected_analysis_kind() == AnalysisKind.MODAL:
            method = self.modal_extraction_method.currentData()
            if method == "target":
                directions = ",".join(
                    direction
                    for direction, checkbox in self.modal_target_direction_checks.items()
                    if checkbox.isChecked()
                )
                return {
                    "extraction_method": "target",
                    "target_participation": self.modal_target_participation.value(),
                    "target_directions": directions,
                    "max_modes": self.modal_max_modes.value(),
                }
            return {"extraction_method": "fixed", "num_modes": self.num_modes.value()}
        if self.selected_analysis_kind() == AnalysisKind.BUCKLING:
            options: dict[str, float | int | str | bool] = {
                "reference_load_scale": self.buckling_reference_load_scale.value(),
                "num_modes": self.buckling_num_modes.value(),
                "geometric_transform_type": self.buckling_geometric_transform.currentData(),
            }
            reference_load_pattern = self.buckling_load_case.currentData()
            if reference_load_pattern is not None:
                options["reference_load_pattern"] = int(reference_load_pattern)
            # 0 is this field's "AUTO" sentinel - only send an explicit override
            # when the user actually typed one, matching MIN/MAX INCREMENT's
            # "Auto" convention elsewhere in this panel.
            if self.buckling_eigenvalue_tolerance.value() > 0:
                options["eigenvalue_tolerance"] = self.buckling_eigenvalue_tolerance.value()
            return options
        if self.selected_analysis_kind() == AnalysisKind.TIME_HISTORY:
            return self._build_time_history_options()
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
            "geometric_transform_type": self.geometric_transformation.currentData(),
            "target_load_factor": self.target_load_factor.value(),
            "automatic_recovery": self.automatic_recovery.isChecked(),
            "adaptive_step": self.adaptive_step.isChecked(),
        }
        # 0 is this panel's "not set / let the solver derive it" sentinel for
        # both fields (their spin boxes floor at 0) - only send a real override
        # when the user actually typed one, so run_nonlinear_static_analysis's
        # own defaults (derived from MAX STEP BISECTIONS) apply otherwise.
        if self.min_increment.value() > 0:
            options["min_increment"] = self.min_increment.value()
        if self.max_increment.value() > 0:
            options["max_increment"] = self.max_increment.value()
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
        if self.integrator_type.currentData() == "ArcLength":
            options["arc_length_radius"] = self.arc_length_radius.value()
            options["arc_length_alpha"] = self.arc_length_alpha.value()
            options["arc_length_max_steps"] = self.arc_length_max_steps.value()
            options["arc_length_min_radius"] = self.arc_length_min_radius.value()
            options["arc_length_max_radius"] = self.arc_length_max_radius.value()
            options["arc_length_adaptive"] = self.arc_length_adaptive.isChecked()
            arc_length_control_node = self.arc_length_control_node.currentData()
            if arc_length_control_node is not None:
                options["arc_length_control_node"] = int(arc_length_control_node)
            arc_length_control_dof = self.arc_length_control_dof.currentData()
            if arc_length_control_dof is not None:
                options["arc_length_control_dof"] = int(arc_length_control_dof)
            # 0 is this field's "None / run until MAXIMUM STEPS" sentinel, same
            # convention as MIN/MAX INCREMENT above.
            if self.arc_length_max_displacement.value() > 0:
                options["arc_length_max_displacement"] = self.arc_length_max_displacement.value()
        return options

    def _analysis_type_changed(self) -> None:
        self._update_nonlinear_visibility()
        kind = self.selected_analysis_kind()
        self.config_store.set_kind(kind)
        self._sync_store_options()
        # Refreshes SOLUTION METHOD/CONVERGENCE against the new kind's
        # ANALYSIS_CAPABILITIES entry - without this, switching kinds would
        # leave the previous kind's readouts (or editable/fixed SOLVER
        # visibility) stuck on screen until some nonlinear field happened to
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
        is_linear_static = kind == AnalysisKind.LINEAR_STATIC
        is_modal = kind == AnalysisKind.MODAL
        is_nonlinear_static = kind == AnalysisKind.NONLINEAR_STATIC
        is_time_history = kind == AnalysisKind.TIME_HISTORY
        is_buckling = kind == AnalysisKind.BUCKLING
        self.nonlinear_group.setVisible(is_nonlinear_static)
        self.time_history_group.setVisible(is_time_history)
        self.buckling_group.setVisible(is_buckling)
        self.buckling_precheck_card.setVisible(is_buckling)
        if is_buckling:
            self._update_buckling_summary()
        # Linear Static gets its own compact LOADS/ANALYSIS METHOD card instead
        # of the shared "1. LOAD & CONTROL" card (Gravity/Lateral/Control/Steps
        # describe Nonlinear Static's pushover staging, not a single-step linear
        # solve), and starts SOLUTION METHOD collapsed since every value in it
        # is ENGINE_FIXED for this kind. Modal and Time History each replace
        # "1. LOAD & CONTROL"/"3. SOLUTION METHOD"/"4. CONVERGENCE" outright
        # with their own cards (modal_engine_card / time_history_group's own
        # 4-card stack) instead of collapsing the shared ones, since both need
        # rows (Static Integrator, Newmark gamma/beta, ...) the shared grids do
        # not have. Nonlinear Static instead uses its dedicated inline editor.
        # Every analysis kind now has its own purpose-built load/configuration
        # surface. Nonlinear Static edits its values directly inside
        # ``nonlinear_group`` rather than duplicating them in this legacy card.
        self.load_card.setVisible(False)
        if is_nonlinear_static:
            self._update_nonlinear_behavior_tiles()
            self.nonlinear_advanced_toggle.setChecked(True)
        self.linear_static_group.setVisible(is_linear_static)
        self.modal_group.setVisible(is_modal)
        self.modal_engine_card.setVisible(is_modal)
        self.solution_card.setVisible(is_linear_static)
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
            self._update_modal_extraction_visibility()

    def _toggle_engine_details(self, expanded: bool) -> None:
        self.solution_body.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        self.engine_details_toggle.setText(f"{arrow}  ADVANCED ENGINE DETAILS")

    def _update_modal_extraction_visibility(self) -> None:
        is_target = self.modal_extraction_method.currentData() == "target"
        self.modal_fixed_group.setVisible(not is_target)
        self.modal_target_group.setVisible(is_target)

    def _toggle_modal_engine_details(self, expanded: bool) -> None:
        self.modal_engine_details_body.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        self.modal_engine_details_toggle.setText(f"{arrow}  ADVANCED ENGINE DETAILS")

    def _update_buckling_summary(self) -> None:
        self._update_buckling_precheck()
        self._sync_store_options()

    def _update_buckling_precheck(self) -> None:
        """Item 7's synchronous, model-shape-only pre-check - deeper checks that
        need the solver's own collector state (e.g. whether the reference
        load's TimeSeries is genuinely static) can only be judged once the
        solver actually runs; those surface as a clear RuntimeError there
        instead of being guessed at here."""
        labels = self.buckling_precheck_value_labels
        patterns = self._pattern_tags(self._model) if self._model is not None else []
        selected = self.buckling_load_case.currentData()
        load_case_text = (
            f"Pattern {selected}" if selected is not None else f"All Patterns ({len(patterns)})"
        )
        labels["Reference Load"].setText(
            f"{load_case_text}  x  {self.buckling_reference_load_scale.value():g}"
        )
        labels["Geometric Transform"].setText(self.buckling_geometric_transform.currentText())
        labels["Number of Modes"].setText(str(self.buckling_num_modes.value()))
        node_count = len(self._model.nodes) if self._model is not None else 0
        ndf = self._model.ndf if self._model is not None else 0
        estimated_dofs = node_count * ndf
        labels["Model Size"].setText(f"{node_count} nodes (~{estimated_dofs} DOFs est.)")
        is_large_model = estimated_dofs > _LARGE_MODEL_ESTIMATED_DOF_THRESHOLD
        self.buckling_large_model_note.setVisible(is_large_model)
        if is_large_model:
            self.buckling_large_model_note.setText(
                f"ⓘ  약 {estimated_dofs}개 자유도로 추정됩니다({_LARGE_MODEL_ESTIMATED_DOF_THRESHOLD}개 "
                "초과) - 밀집(Dense) FullGeneral 행렬 계산과 SciPy 일반화고유치 해석은 "
                "모델 크기에 따라 계산 시간과 메모리 사용량이 크게 늘어날 수 있습니다."
            )
        scipy_available = importlib.util.find_spec("scipy") is not None
        labels["SciPy"].setText("Available" if scipy_available else "Not Installed")

        issues: list[str] = []
        if self._model is None or not self._model.nodes or not self._model.elements:
            issues.append("모델이 비어 있습니다.")
        else:
            if not patterns:
                issues.append("REFERENCE LOAD로 사용할 정적 하중 패턴이 모델에 없습니다.")
            if not self._model.boundaries:
                issues.append(
                    "경계조건이 없습니다 - 강체운동만 가능해 좌굴해석이 성립하지 않습니다."
                )
        if self.buckling_reference_load_scale.value() == 0:
            issues.append("REFERENCE LOAD SCALE은 0이 될 수 없습니다.")
        if self.buckling_num_modes.value() <= 0:
            issues.append("NUMBER OF MODES는 1 이상이어야 합니다.")
        if not scipy_available:
            issues.append("SciPy가 설치되어 있지 않아 좌굴해석을 실행할 수 없습니다.")

        if issues:
            self.buckling_precheck_status.setText("⚠  " + "  ·  ".join(issues))
            self.buckling_precheck_status.setProperty("state", "warning")
        else:
            self.buckling_precheck_status.setText("✓  Ready for Analysis")
            self.buckling_precheck_status.setProperty("state", "ok")
        self.buckling_precheck_status.style().unpolish(self.buckling_precheck_status)
        self.buckling_precheck_status.style().polish(self.buckling_precheck_status)

    def _toggle_nonlinear_advanced_settings(self, expanded: bool) -> None:
        self.nonlinear_advanced_body.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        self.nonlinear_advanced_toggle.setText(
            f"{arrow}  ADVANCED SOLUTION && CONVERGENCE"
        )

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

    # -- Time History: multi-direction Ground Motion table -----------------

    def _rebuild_direction_rows(self, ndm: int) -> None:
        """(Re)build one row per translational DOF (X/Y for 2D, X/Y/Z for
        3D) - the Direction itself is fixed per row, so two rows can never
        activate the same direction (see time_history_direction_row.py)."""
        self._time_history_ndm = ndm
        while self._direction_rows_layout.count():
            item = self._direction_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.time_history_direction_rows = []
        axis_labels = ("X", "Y") if ndm == 2 else ("X", "Y", "Z")
        for dof, label in enumerate(axis_labels, start=1):
            row = TimeHistoryDirectionRow(dof, label, self._builtin_catalog, self)
            row.set_length_unit(self._time_history_length_unit)
            row.changed.connect(self._on_direction_row_changed)
            self._direction_rows_layout.addWidget(row)
            self.time_history_direction_rows.append(row)
        # Not calling _on_direction_row_changed() here: this runs during
        # __init__ itself (before the Analysis Time/Damping/... cards below
        # this one in the constructor exist yet) as well as later from
        # set_model() - callers refresh explicitly once every widget exists.

    def _active_direction_rows(self) -> list[TimeHistoryDirectionRow]:
        return [
            row
            for row in self.time_history_direction_rows
            if row.is_enabled_row() and row.has_valid_motion()
        ]

    def _on_direction_row_changed(self) -> None:
        self._update_analysis_time_status()
        self._update_precheck_th()
        self._sync_store_options()

    # -- Time History: Analysis Time ----------------------------------------

    def _update_analysis_time_status(self) -> None:
        is_custom = self.duration_custom_radio.isChecked()
        self.analysis_end_time.setEnabled(is_custom)
        is_default = (
            not is_custom
            and self.analysis_time_step.value() == 0.0
            and self.analysis_max_time_step.value() == 0.0
        )
        self.analysis_time_status.setText("AUTO" if is_default else "CUSTOM")
        self.analysis_time_status.setProperty("state", "off" if is_default else "ok")
        self.analysis_time_status.style().unpolish(self.analysis_time_status)
        self.analysis_time_status.style().polish(self.analysis_time_status)
        self._update_precheck_th()
        self._sync_store_options()

    def _reset_analysis_time(self) -> None:
        self.duration_full_radio.setChecked(True)
        self.analysis_end_time.setValue(0.0)
        self.analysis_time_step.setValue(0.0)
        self.analysis_max_time_step.setValue(0.0)
        self._update_analysis_time_status()

    # -- Time History: Damping ----------------------------------------------

    def _update_damping_visibility(self) -> None:
        self.damping_modal_group.setVisible(self.damping_modal_radio.isChecked())
        self.damping_direct_group.setVisible(self.damping_direct_radio.isChecked())
        self._update_precheck_th()
        self._sync_store_options()

    # -- Time History: Time Integration --------------------------------------

    def _update_integrator_type_visibility(self) -> None:
        self.newmark_group.setVisible(self.integrator_newmark_radio.isChecked())
        self.hht_group.setVisible(self.integrator_hht_radio.isChecked())
        self._update_precheck_th()
        self._sync_store_options()

    def _update_hht_parameter_mode_visibility(self) -> None:
        self.hht_custom_group.setVisible(self.hht_custom_radio.isChecked())
        self._sync_store_options()

    # -- Time History: Solution Strategy -------------------------------------

    #: (widget attribute, default value) pairs Reset to Default restores -
    #: mirrors run_time_history_analysis's own _resolve_solution() defaults
    #: (see time_history_solver.py), the same DEFAULT/CUSTOM convention
    #: Nonlinear Static's own _SOLUTION_STRATEGY_DEFAULTS uses.
    _TIME_HISTORY_SOLUTION_STRATEGY_DEFAULTS = (
        ("th_algorithm", "Newton"),
        ("th_test_type", "NormDispIncr"),
        ("th_tolerance", 1.0e-8),
        ("th_max_iterations", 30),
        ("th_constraints_type", "Transformation"),
        ("th_numberer", "RCM"),
        ("th_system", "BandGeneral"),
    )

    def _update_solution_strategy_status_th(self) -> None:
        is_default = True
        for attr, default in self._TIME_HISTORY_SOLUTION_STRATEGY_DEFAULTS:
            widget = getattr(self, attr)
            current = widget.currentText() if isinstance(widget, QComboBox) else widget.value()
            if current != default:
                is_default = False
                break
        self.th_solution_strategy_status.setText("DEFAULT" if is_default else "CUSTOM")
        self.th_solution_strategy_status.setProperty("state", "off" if is_default else "ok")
        self.th_solution_strategy_status.style().unpolish(self.th_solution_strategy_status)
        self.th_solution_strategy_status.style().polish(self.th_solution_strategy_status)
        self._update_precheck_th()
        self._sync_store_options()

    def _reset_solution_strategy_th(self) -> None:
        for attr, default in self._TIME_HISTORY_SOLUTION_STRATEGY_DEFAULTS:
            widget = getattr(self, attr)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(default)
            else:
                widget.setValue(default)
        self._update_solution_strategy_status_th()

    # -- Time History: Adaptive Recovery -------------------------------------

    def _update_recovery_field_states_th(self) -> None:
        enabled = self.th_automatic_recovery.isChecked()
        self.th_algorithm_fallback.setEnabled(enabled)
        self.th_min_time_step.setEnabled(enabled)
        self.th_reduction_factor.setEnabled(enabled)
        self.th_restoration_factor.setEnabled(enabled)
        self.th_max_reductions.setEnabled(enabled)
        self.th_clean_steps_to_restore.setEnabled(enabled)
        self._update_precheck_th()

    # -- Time History: PRE-CHECK ---------------------------------------------

    def _update_precheck_th(self) -> None:
        """Item 7's synchronous RUN-blocking + advisory check, computed
        entirely from the current model + widget state - no solver call, so
        it stays instant (mirrors _update_precheck's own nonlinear pattern)."""
        if not hasattr(self, "th_precheck_value_labels"):
            # Cards are built in Ground Motion -> ... -> Pre-check order, but
            # earlier cards' own constructor wiring (radio toggles, spinbox
            # valueChanged) fires change signals immediately as their default
            # values are set - before the Pre-check card two down the list
            # exists yet. Harmless no-op until then; the constructor's own
            # final _on_direction_row_changed() call refreshes it once every
            # widget is built.
            return
        labels = self.th_precheck_value_labels
        active_rows = self._active_direction_rows()
        labels["Active Directions"].setText(
            ", ".join(f"DOF {row.dof}" for row in active_rows) if active_rows else "None"
        )
        motions = [row.active_motion() for row in active_rows]
        default_end_time = max((motion.duration for motion in motions), default=0.0)
        default_dt = min((motion.dt for motion in motions), default=0.0)
        is_custom_duration = self.duration_custom_radio.isChecked()
        end_time = (
            self.analysis_end_time.value()
            if is_custom_duration and self.analysis_end_time.value() > 0
            else default_end_time
        )
        analysis_dt = self.analysis_time_step.value() if self.analysis_time_step.value() > 0 else default_dt
        labels["End Time / Analysis dt"].setText(f"{end_time:.4g}s / {analysis_dt:.4g}s")
        labels["Damping"].setText(
            "None"
            if self.damping_none_radio.isChecked()
            else "Rayleigh - Modal Targets"
            if self.damping_modal_radio.isChecked()
            else "Rayleigh - Direct Coefficients"
        )
        labels["Time Integration"].setText(
            "Newmark" if self.integrator_newmark_radio.isChecked() else "HHT"
        )
        labels["Automatic Recovery"].setText(
            "ON" if self.th_automatic_recovery.isChecked() else "OFF (Use Settings Only)"
        )

        issues: list[str] = []
        warnings: list[str] = []
        if not active_rows:
            issues.append("활성화된 지진파 방향이 없습니다.")
        if is_custom_duration and self.analysis_end_time.value() <= 0:
            issues.append("Custom Duration Mode에서는 END TIME을 입력해야 합니다.")
        if analysis_dt <= 0:
            issues.append("ANALYSIS TIME STEP이 0 이하입니다.")
        min_dt = self.th_min_time_step.value() if self.th_min_time_step.value() > 0 else analysis_dt * 0.0625
        max_dt = self.analysis_max_time_step.value() if self.analysis_max_time_step.value() > 0 else analysis_dt
        if analysis_dt > 0 and not min_dt <= analysis_dt <= max_dt:
            issues.append("MINIMUM ≤ ANALYSIS ≤ MAXIMUM TIME STEP 순서를 확인하세요.")
        if not 0.0 < self.th_reduction_factor.value() < 1.0:
            issues.append("TIME STEP REDUCTION은 0과 1 사이여야 합니다.")
        if self.th_restoration_factor.value() <= 1.0:
            issues.append("TIME STEP RESTORATION은 1보다 커야 합니다.")
        if self.th_tolerance.value() <= 0 or self.th_max_iterations.value() <= 0:
            issues.append("TOLERANCE/MAXIMUM ITERATIONS를 확인하세요.")
        if self.integrator_hht_radio.isChecked() and not 0.67 <= self.hht_alpha.value() <= 1.0:
            issues.append("HHT ALPHA는 0.67~1.0 범위여야 합니다.")
        if self.damping_modal_radio.isChecked() and self.damping_mode_i.value() == self.damping_mode_j.value():
            issues.append("Mode i와 Mode j는 서로 달라야 합니다.")
        for row in active_rows:
            motion = row.active_motion()
            if row.target_pga_radio.isChecked() and (motion is None or motion.pga <= 0.0):
                issues.append(f"DOF {row.dof}: TARGET PGA를 사용하려면 원본 PGA가 0보다 커야 합니다.")

        if self.damping_none_radio.isChecked():
            warnings.append("감쇠가 None입니다 - 응답이 비물리적으로 커질 수 있습니다.")
        if analysis_dt > 0 and default_dt > 0 and analysis_dt > default_dt:
            warnings.append(
                "ANALYSIS TIME STEP이 활성 지진파 중 최소 Record dt보다 큽니다 - "
                "정확도가 저하될 수 있습니다."
            )
        if is_custom_duration and self.analysis_end_time.value() > 0 and any(
            self.analysis_end_time.value() > motion.duration for motion in motions
        ):
            warnings.append(
                "Custom END TIME이 일부 Record Duration보다 깁니다 - 해당 방향은 "
                "이후 구간이 0으로 처리됩니다."
            )
        if analysis_dt > 0 and end_time > 0 and end_time / analysis_dt > 200_000:
            warnings.append("예상 해석 스텝 수가 매우 많습니다 - 실행 시간이 오래 걸릴 수 있습니다.")

        if issues:
            self.th_precheck_status.setText("⚠  " + "  ·  ".join(issues))
            self.th_precheck_status.setProperty("state", "warning")
        elif warnings:
            self.th_precheck_status.setText("⚠  " + "  ·  ".join(warnings))
            self.th_precheck_status.setProperty("state", "warning")
        else:
            self.th_precheck_status.setText("✓  Ready for Analysis")
            self.th_precheck_status.setProperty("state", "ok")
        self.th_precheck_status.style().unpolish(self.th_precheck_status)
        self.th_precheck_status.style().polish(self.th_precheck_status)

    def _build_time_history_options(self) -> dict[str, object]:
        directions = [
            options
            for row in self.time_history_direction_rows
            for options in (row.to_options(),)
            if options is not None
        ]

        damping_mode = (
            "none"
            if self.damping_none_radio.isChecked()
            else "modal"
            if self.damping_modal_radio.isChecked()
            else "direct"
        )
        damping: dict[str, object] = {"mode": damping_mode}
        if damping_mode == "modal":
            damping.update(
                {
                    "mode_i": self.damping_mode_i.value(),
                    "mode_j": self.damping_mode_j.value(),
                    "ratio_i": self.damping_ratio_i.value(),
                    "ratio_j": self.damping_ratio_j.value(),
                    "stiffness_term": self.damping_stiffness_term.currentData(),
                }
            )
        elif damping_mode == "direct":
            damping.update(
                {
                    "alpha_m": self.damping_alpha_m.value(),
                    "beta_k": self.damping_beta_k.value(),
                    "beta_k_init": self.damping_beta_k_init.value(),
                    "beta_k_comm": self.damping_beta_k_comm.value(),
                }
            )

        if self.integrator_newmark_radio.isChecked():
            integrator: dict[str, object] = {
                "type": "Newmark",
                "gamma": self.newmark_gamma.value(),
                "beta": self.newmark_beta.value(),
            }
        else:
            integrator = {
                "type": "HHT",
                "alpha": self.hht_alpha.value(),
                "parameter_mode": "custom" if self.hht_custom_radio.isChecked() else "auto",
            }
            if self.hht_custom_radio.isChecked():
                integrator["gamma"] = self.hht_gamma.value()
                integrator["beta"] = self.hht_beta.value()

        solution = {
            "algorithm": self.th_algorithm.currentText(),
            "test_type": self.th_test_type.currentText(),
            "tolerance": self.th_tolerance.value(),
            "max_iterations": self.th_max_iterations.value(),
            "constraints_type": self.th_constraints_type.currentText(),
            "numberer": self.th_numberer.currentText(),
            "system": self.th_system.currentText(),
        }

        # 0 is each of these spinboxes' own "Auto" sentinel - passed straight
        # through unchanged, since time_history_solver.py's own
        # _resolve_analysis_time()/_resolve_recovery() already treat <= 0 as
        # "compute this default", the exact same convention used here.
        analysis_time = {
            "duration_mode": "custom" if self.duration_custom_radio.isChecked() else "full",
            "end_time": self.analysis_end_time.value(),
            "dt": self.analysis_time_step.value(),
            "max_dt": self.analysis_max_time_step.value(),
        }
        recovery = {
            "automatic": self.th_automatic_recovery.isChecked(),
            "algorithm_fallback": self.th_algorithm_fallback.isChecked(),
            "min_dt": self.th_min_time_step.value(),
            "reduction_factor": self.th_reduction_factor.value(),
            "restoration_factor": self.th_restoration_factor.value(),
            "max_reductions": self.th_max_reductions.value(),
            "clean_steps_to_restore": self.th_clean_steps_to_restore.value(),
        }

        return {
            "directions": directions,
            "model_length_unit": self._time_history_length_unit,
            "analysis_time": analysis_time,
            "damping": damping,
            "integrator": integrator,
            "solution": solution,
            "recovery": recovery,
        }

    def _update_nonlinear_summary(self) -> None:
        """Synchronize inline nonlinear controls with readouts and run options."""
        integrator = self.integrator_type.currentText()
        self.load_control_value.setText(integrator)
        self.load_steps_value.setText(str(self.num_steps.value()))
        self.load_progress.setMaximum(max(1, self.num_steps.value()))
        self.load_progress.setValue(self.num_steps.value())
        self.load_progress_caption.setText(f"100% ({self.num_steps.value()} Steps)")
        self._update_engine_capability_display()
        num_steps = max(1, self.num_steps.value())
        self.load_increment_value.setText(
            f"{self.target_load_factor.value() / num_steps:.6g}"
        )
        self.initial_increment_value.setText(
            f"{self.target_displacement.value() / num_steps:.6g} {self._unit_system.length}"
        )
        self._update_solution_strategy_status()
        self._update_precheck()
        self._sync_store_options()

    #: (widget attribute, default value) pairs Reset to Default restores, and
    #: what current values are compared against for the DEFAULT/CUSTOM status -
    #: the same "recommended, stable values already in use by this program"
    #: the widgets themselves are constructed with (see _build_nonlinear_inline_editor).
    _SOLUTION_STRATEGY_DEFAULTS = (
        ("solver", "BandGeneral"),
        ("algorithm", "Newton"),
        ("constraints_type", "Plain"),
        ("numberer", "RCM"),
        ("test_type", "NormDispIncr"),
        ("tolerance", 1.0e-6),
        ("max_iterations", 25),
    )

    def _update_solution_strategy_status(self) -> None:
        is_default = True
        for attr, default in self._SOLUTION_STRATEGY_DEFAULTS:
            widget = getattr(self, attr)
            current = widget.currentText() if isinstance(widget, QComboBox) else widget.value()
            if current != default:
                is_default = False
                break
        self.solution_strategy_status.setText("DEFAULT" if is_default else "CUSTOM")
        self.solution_strategy_status.setProperty("state", "off" if is_default else "ok")
        self.solution_strategy_status.style().unpolish(self.solution_strategy_status)
        self.solution_strategy_status.style().polish(self.solution_strategy_status)

    def _reset_solution_strategy(self) -> None:
        for attr, default in self._SOLUTION_STRATEGY_DEFAULTS:
            widget = getattr(self, attr)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(default)
            else:
                widget.setValue(default)
        self._update_nonlinear_summary()

    def _update_recovery_field_states(self) -> None:
        enabled = self.automatic_recovery.isChecked()
        self.max_bisections.setEnabled(enabled)
        self.adaptive_step.setEnabled(enabled)
        self.min_increment_group.setEnabled(enabled)
        self.max_increment_group.setEnabled(enabled)
        # Arc-Length's radius reduction is itself part of Automatic Recovery (see
        # _advance_one_arc_length_step) - Adaptive Radius and its MIN/MAX RADIUS
        # bounds are just as moot without it as Adaptive Step/MIN/MAX INCREMENT are.
        self.arc_length_adaptive.setEnabled(enabled)
        self.arc_length_min_radius_group.setEnabled(enabled)
        self.arc_length_max_radius_group.setEnabled(enabled)
        if not enabled:
            self.adaptive_step.setChecked(False)
            self.arc_length_adaptive.setChecked(False)

    def _update_precheck(self) -> None:
        """Item 7's synchronous RUN-blocking check, computed entirely from the
        current model + widget state - no solver call, so it stays instant."""
        labels = self.precheck_value_labels
        transform_label = self.geometric_transformation.currentText()
        labels["Geometric Nonlinearity"].setText(transform_label)
        material_active = bool(
            self._model is not None
            and any(
                element.element_type.lower() in _NONLINEAR_ELEMENT_TYPES
                for element in self._model.elements.values()
            )
        )
        labels["Material Nonlinearity"].setText(
            "Active" if material_active else "Not Active"
        )
        labels["Control Method"].setText(self.integrator_type.currentText())
        num_steps = max(1, self.num_steps.value())
        is_arc_length = self.integrator_type.currentData() == "ArcLength"
        if is_arc_length:
            labels["Initial Step"].setText(f"{self.arc_length_radius.value():.6g} (radius)")
        elif self.integrator_type.currentData() == "DisplacementControl":
            initial_step = self.target_displacement.value() / num_steps
            labels["Initial Step"].setText(f"{initial_step:.6g} {self._unit_system.length}")
        else:
            initial_step = self.target_load_factor.value() / num_steps
            labels["Initial Step"].setText(f"{initial_step:.6g}")
        self.arc_length_precheck_note.setVisible(is_arc_length)
        labels["Algorithm"].setText(self.algorithm.currentText())
        labels["Convergence"].setText(
            f"{self.test_type.currentText()} / {self.tolerance.value():.1E} / "
            f"{self.max_iterations.value()}"
        )
        labels["Automatic Recovery"].setText(
            "ON" if self.automatic_recovery.isChecked() else "OFF (Use Settings Only)"
        )

        issues: list[str] = []
        if self._model is None or not self._model.nodes or not self._model.elements:
            issues.append("모델이 비어 있습니다.")
        else:
            if not self._pattern_tags(self._model):
                issues.append("적용된 하중 패턴이 없습니다.")
            if not self._model.boundaries:
                issues.append("경계조건이 없습니다 - 메커니즘(불안정 구조)이 될 수 있습니다.")
        if self.control_node.currentData() is None:
            issues.append("CONTROL NODE가 지정되지 않았습니다.")
        if (
            self.integrator_type.currentData() == "DisplacementControl"
            and self.target_displacement.value() == 0
        ):
            issues.append("TARGET DISPLACEMENT가 0입니다 - 0이 아닌 값을 입력하세요.")
        if (
            self.gravity_pattern.currentData() is not None
            and self.gravity_pattern.currentData() == self.lateral_pattern.currentData()
        ):
            issues.append("GRAVITY PATTERN과 LATERAL LOAD PATTERN이 같습니다.")
        if self.min_increment.value() > 0 and self.max_increment.value() > 0:
            if self.min_increment.value() > self.max_increment.value():
                issues.append("MIN INCREMENT가 MAX INCREMENT보다 큽니다.")
        if is_arc_length and not (
            self.arc_length_min_radius.value()
            <= self.arc_length_radius.value()
            <= self.arc_length_max_radius.value()
        ):
            issues.append("MINIMUM RADIUS ≤ ARC-LENGTH RADIUS ≤ MAXIMUM RADIUS 순서여야 합니다.")

        if issues:
            self.precheck_status.setText("⚠  " + "  ·  ".join(issues))
            self.precheck_status.setProperty("state", "warning")
        else:
            self.precheck_status.setText("✓  Ready for Analysis")
            self.precheck_status.setProperty("state", "ok")
        self.precheck_status.style().unpolish(self.precheck_status)
        self.precheck_status.style().polish(self.precheck_status)

    def _update_nonlinear_behavior_tiles(self) -> None:
        """MATERIAL NONLINEARITY used to always read "✓ Detected in Model"
        regardless of the actual model - a hardcoded claim, never checked.
        StructuralModel only carries element_type (not material/section names,
        which live only inside the solver's own ModelCommandCollector and never
        reach the imported domain object - see model_importer.py), so that is
        the one signal checked here: real, but only a partial proxy for
        "material nonlinearity" in the fullest sense - no Fiber Section/
        Concrete02/Steel02 material DB is wired up yet (out of scope here; see
        the module docstring), so this never claims more than element type
        alone actually supports.

        GEOMETRIC NONLINEARITY mirrors ``self.geometric_transformation``. For
        an explicit Linear/P-Delta/Corotational choice this is Setup's own
        selection, which ``run_nonlinear_static_analysis`` applies by
        overriding every ``ops.geomTransf(...)`` call the model makes (see
        ModelCommandCollector.install(geom_transf_override=...)). For "Use
        model definition" it instead summarizes the model's own
        ``StructuralModel.geometric_transforms`` (real per-element data,
        collected without any override - see model_collector.py/
        model_importer.py) - either way this tile is never a guess about what
        the model might contain."""
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

        transform = self.geometric_transformation.currentData()
        transform_label = self.geometric_transformation.currentText()
        if transform == _USE_MODEL_DEFINITION:
            self._show_model_defined_geometric_transform()
        elif transform == "Linear":
            self.geometric_nonlinearity_value.setText("○  Linear (disabled)")
            self.geometric_nonlinearity_value.setProperty("state", "off")
            self.geometric_nonlinearity_notice.setText(
                "ⓘ  Geometric nonlinearity is Linear. P-Delta or large-displacement "
                "effects will not be considered. Change GEOMETRIC TRANSFORMATION "
                "above to enable them."
            )
        else:
            self.geometric_nonlinearity_value.setText(f"✓  {transform_label} ENABLED")
            self.geometric_nonlinearity_value.setProperty("state", "ok")
            self.geometric_nonlinearity_notice.setText(
                f"ⓘ  {transform_label} is applied to every frame element, overriding "
                "whatever geomTransf the model itself defines - blocked before the run "
                "starts if the model contains a transform type this override cannot "
                "safely replace."
            )
        self.geometric_nonlinearity_value.style().unpolish(self.geometric_nonlinearity_value)
        self.geometric_nonlinearity_value.style().polish(self.geometric_nonlinearity_value)

    def _show_model_defined_geometric_transform(self) -> None:
        """"Use model definition" tile content - a real summary of
        ``StructuralModel.geometric_transforms`` rather than Setup's own
        selection, since no override is being applied at all."""
        types = sorted(
            {
                transform.transform_type
                for transform in (self._model.geometric_transforms.values() if self._model else ())
            }
        )
        if not types:
            self.geometric_nonlinearity_value.setText("—  Use model definition")
            self.geometric_nonlinearity_value.setProperty("state", "off")
            self.geometric_nonlinearity_notice.setText(
                "ⓘ  Each element keeps its own geomTransf from the model. No "
                "transformation data was found to summarize."
            )
            return
        has_geometric_nonlinearity = any(
            transform_type.lower() in _GEOMETRIC_NONLINEAR_TRANSFORM_TYPES
            for transform_type in types
        )
        listed = ", ".join(types)
        if has_geometric_nonlinearity:
            self.geometric_nonlinearity_value.setText(f"✓  Model-defined ({listed})")
            self.geometric_nonlinearity_value.setProperty("state", "ok")
        else:
            self.geometric_nonlinearity_value.setText(f"○  Model-defined ({listed})")
            self.geometric_nonlinearity_value.setProperty("state", "off")
        self.geometric_nonlinearity_notice.setText(
            f"ⓘ  Each element keeps its own geomTransf from the model - types found: "
            f"{listed}."
        )

    def _update_engine_capability_display(self) -> None:
        """Make SOLUTION METHOD/CONVERGENCE show what the current AnalysisKind's
        engine actually does (ANALYSIS_CAPABILITIES) instead of always mirroring
        the nonlinear controls regardless of kind. This is also where the
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
        # Time History's convergence_test is ENGINE_FIXED (not NOT_APPLICABLE),
        # but Phase 3-E gave it its own "4. SOLUTION / CONVERGENCE" card inside
        # time_history_group, so the shared card is hidden here too rather than
        # shown twice.
        if field.state == FieldState.NOT_APPLICABLE or self.selected_analysis_kind() in (
            AnalysisKind.NONLINEAR_STATIC,
            AnalysisKind.TIME_HISTORY,
        ):
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
