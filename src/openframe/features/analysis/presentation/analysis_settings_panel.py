"""Analysis type and solver settings panel."""

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter
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
    GroundMotion,
    GroundMotionRecord,
    StructuralModel,
    UnitSystem,
)
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
from openframe.features.results.presentation.time_history_curve_view import (
    TimeHistoryCurveView,
)
from openframe.features.analysis.presentation.ground_motion_picker_dialog import (
    GroundMotionPickerDialog,
)
from openframe.infrastructure.ground_motions import BuiltInGroundMotionCatalog
from openframe.infrastructure.opensees.ground_motion import load_ground_motion

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


class _VerticalResizeHandle(QWidget):
    """Thin drag handle that lets the user resize ``target``'s height.

    The settings panel lives in a scroll area with unbounded vertical room,
    but a plain QVBoxLayout still only ever gives ``target`` its minimum
    height - for the ACCELERATION-TIME PREVIEW plot that meant a cramped,
    barely-legible strip with no way to make it taller. This drags
    ``target``'s fixed height between ``min_height`` and ``max_height``
    instead, so the user can reclaim (or give back) that space themselves.
    """

    def __init__(
        self,
        target: QWidget,
        *,
        min_height: int,
        max_height: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._target = target
        self._min_height = min_height
        self._max_height = max_height
        self._drag_start_y: float | None = None
        self._drag_start_height = 0
        self.setFixedHeight(12)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag to resize the preview")

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor("#c3cad6"))
        mid_y = self.height() // 2
        center_x = self.width() // 2
        for offset in (-9, 0, 9):
            painter.drawLine(center_x + offset - 3, mid_y, center_x + offset + 3, mid_y)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_start_y = event.globalPosition().y()
        self._drag_start_height = self._target.height()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start_y is None:
            super().mouseMoveEvent(event)
            return
        delta = event.globalPosition().y() - self._drag_start_y
        new_height = max(
            self._min_height, min(self._max_height, round(self._drag_start_height + delta))
        )
        self._target.setFixedHeight(new_height)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_y = None
        super().mouseReleaseEvent(event)


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

        # Time history needs a ground-motion file plus three small numbers - a
        # dialog would be overkill, but it earns its own group (unlike modal's
        # one field) since a file picker is a different kind of control.
        # Time History's own 4-card structure (Phase 3-E) - self.time_history_group
        # stays the single widget whose visibility means "Time History is
        # selected" (existing tests reach through it), but internally it is
        # now a stack of separate titled cards instead of one bare, untitled
        # field list, so it no longer borrows Nonlinear Static's "1. LOAD &
        # CONTROL"/"3. SOLUTION METHOD"/"4. CONVERGENCE" cards at all (see
        # _update_nonlinear_visibility - those three are hidden outright for
        # this kind now).
        self.time_history_group = QFrame()
        time_history_outer_layout = QVBoxLayout(self.time_history_group)
        time_history_outer_layout.setContentsMargins(0, 0, 0, 0)
        time_history_outer_layout.setSpacing(16)

        self.time_history_ground_motion_card, ground_motion_layout = self._config_card(
            "1. GROUND MOTION"
        )
        self._scaling_sync_in_progress = False
        # Two independent "last picked" slots, one per source - so toggling
        # Built-in <-> Imported never shows one source's data under the
        # other's label (the Phase 3-G "no stale values on switch"
        # requirement), while still remembering each side's own last pick
        # across a toggle instead of forgetting it.
        self._builtin_catalog = BuiltInGroundMotionCatalog()
        self._builtin_record: GroundMotionRecord | None = None
        self._builtin_ground_motion: GroundMotion | None = None
        self._imported_ground_motion_path: Path | None = None
        self._imported_ground_motion: GroundMotion | None = None
        # What build_options() actually reads and what the info grid/preview
        # actually display - always a mirror of whichever source is active,
        # never a second store of its own.
        self._ground_motion_path: Path | None = None
        self._ground_motion: GroundMotion | None = None

        ground_motion_layout.addWidget(self._field_label("SOURCE"))
        source_row = QHBoxLayout()
        self.ground_motion_source_group = QButtonGroup(self)
        self.source_builtin_radio = QRadioButton("Built-in Library")
        self.source_imported_radio = QRadioButton("Imported File")
        self.source_imported_radio.setChecked(True)
        self.ground_motion_source_group.addButton(self.source_builtin_radio)
        self.ground_motion_source_group.addButton(self.source_imported_radio)
        self.source_builtin_radio.toggled.connect(self._on_ground_motion_source_changed)
        source_row.addWidget(self.source_builtin_radio)
        source_row.addWidget(self.source_imported_radio)
        source_row.addStretch(1)
        ground_motion_layout.addLayout(source_row)

        self.builtin_record_row = QWidget()
        builtin_record_layout = QVBoxLayout(self.builtin_record_row)
        builtin_record_layout.setContentsMargins(0, 0, 0, 0)
        builtin_record_layout.setSpacing(4)
        builtin_record_layout.addWidget(self._field_label("RECORD"))
        # Kept as the underlying data model/selection state (still the single
        # source of truth _on_builtin_record_selected reads), but hidden -
        # with 65+ bundled records a plain dropdown stacks them in one long
        # vertical list that's hard to scan or search, so the visible control
        # is a button that opens GroundMotionPickerDialog (search + sort +
        # scrollable list + explicit Apply/Cancel) instead.
        self.builtin_record_combo = QComboBox()
        for record in self._builtin_catalog.list_records():
            self.builtin_record_combo.addItem(
                f"{record.event} — {record.station} ({record.component})", record
            )
        self.builtin_record_combo.currentIndexChanged.connect(self._on_builtin_record_selected)
        self.builtin_record_combo.setVisible(False)
        builtin_record_layout.addWidget(self.builtin_record_combo)

        builtin_picker_row = QHBoxLayout()
        self.builtin_record_label = QLabel("(no record selected)")
        self.builtin_record_label.setWordWrap(True)
        builtin_picker_row.addWidget(self.builtin_record_label, 1)
        self.choose_builtin_record_button = QPushButton("Select…")
        self.choose_builtin_record_button.setObjectName("groundMotionPickerButton")
        self.choose_builtin_record_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_builtin_record_button.clicked.connect(self._choose_builtin_record)
        builtin_picker_row.addWidget(self.choose_builtin_record_button)
        builtin_record_layout.addLayout(builtin_picker_row)
        ground_motion_layout.addWidget(self.builtin_record_row)

        self.imported_file_row = QWidget()
        imported_file_layout = QVBoxLayout(self.imported_file_row)
        imported_file_layout.setContentsMargins(0, 0, 0, 0)
        imported_file_layout.setSpacing(4)
        imported_file_layout.addWidget(self._field_label("GROUND MOTION FILE"))
        file_row = QHBoxLayout()
        self.ground_motion_path_label = QLabel("(no file selected)")
        self.ground_motion_path_label.setWordWrap(True)
        file_row.addWidget(self.ground_motion_path_label, 1)
        self.choose_ground_motion_button = QPushButton("Browse…")
        self.choose_ground_motion_button.clicked.connect(self._choose_ground_motion_file)
        file_row.addWidget(self.choose_ground_motion_button)
        imported_file_layout.addLayout(file_row)
        ground_motion_layout.addWidget(self.imported_file_row)
        self.builtin_record_row.setVisible(False)

        gm_divider_1 = QFrame()
        gm_divider_1.setObjectName("setupGuideDivider")
        gm_divider_1.setFrameShape(QFrame.Shape.HLine)
        ground_motion_layout.addWidget(gm_divider_1)

        self.ground_motion_info_placeholder = QLabel("No ground motion selected")
        self.ground_motion_info_placeholder.setObjectName("secondaryText")
        ground_motion_layout.addWidget(self.ground_motion_info_placeholder)

        self.ground_motion_info_grid_widget = QWidget()
        info_grid = QGridLayout(self.ground_motion_info_grid_widget)
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(5)
        self.gm_name_value = QLabel("—")
        self.gm_dt_value = QLabel("—")
        self.gm_npts_value = QLabel("—")
        self.gm_duration_value = QLabel("—")
        self.gm_pga_value = QLabel("—")
        self.gm_unit_value = QLabel("—")
        for row, (name, value_label) in enumerate((
            ("Name", self.gm_name_value),
            ("dt", self.gm_dt_value),
            ("NPTS", self.gm_npts_value),
            ("Duration", self.gm_duration_value),
            ("PGA", self.gm_pga_value),
            ("Unit", self.gm_unit_value),
        )):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            value_label.setObjectName("setupMetricValue")
            value_label.setWordWrap(True)
            info_grid.addWidget(key, row, 0)
            info_grid.addWidget(value_label, row, 1)
        ground_motion_layout.addWidget(self.ground_motion_info_grid_widget)

        ground_motion_layout.addWidget(self._field_label("ACCELERATION-TIME PREVIEW"))
        self.ground_motion_preview = TimeHistoryCurveView()
        self.ground_motion_preview.setMinimumHeight(140)
        # Default height raised from the old bare 140px minimum (visibly
        # squashed at this panel's width/aspect) to something legible out of
        # the box, while the handle below still lets the user pull it taller
        # or shorter to taste.
        self.ground_motion_preview.setFixedHeight(260)
        self.ground_motion_preview.set_empty_message("No ground motion selected")
        ground_motion_layout.addWidget(self.ground_motion_preview)
        self.ground_motion_preview_resize_handle = _VerticalResizeHandle(
            self.ground_motion_preview, min_height=140, max_height=640
        )
        ground_motion_layout.addWidget(self.ground_motion_preview_resize_handle)

        ground_motion_layout.addWidget(self._field_label("DIRECTION"))
        self.time_history_direction = QComboBox()
        # Every other option widget in this file syncs on change - DIRECTION/
        # SCALE FACTOR/DAMPING RATIO were missing this (the same gap
        # num_modes had in Phase 3-C), so a value picked here was silently
        # dropped from config_store.options until an unrelated event (e.g.
        # switching AnalysisKind away and back) happened to sync it anyway.
        self.time_history_direction.currentIndexChanged.connect(self._sync_store_options)
        ground_motion_layout.addWidget(self.time_history_direction)

        gm_divider_2 = QFrame()
        gm_divider_2.setObjectName("setupGuideDivider")
        gm_divider_2.setFrameShape(QFrame.Shape.HLine)
        ground_motion_layout.addWidget(gm_divider_2)

        ground_motion_layout.addWidget(self._field_label("SCALING"))
        self.scale_mode_group = QButtonGroup(self)
        self.scale_factor_radio = QRadioButton("Scale Factor")
        self.target_pga_radio = QRadioButton("Target PGA")
        self.scale_factor_radio.setChecked(True)
        self.scale_mode_group.addButton(self.scale_factor_radio)
        self.scale_mode_group.addButton(self.target_pga_radio)
        self.scale_factor_radio.toggled.connect(self._on_scale_mode_changed)

        scale_grid = QGridLayout()
        scale_grid.setHorizontalSpacing(12)
        scale_grid.setVerticalSpacing(6)
        self.ground_motion_scale = QDoubleSpinBox()
        self.ground_motion_scale.setRange(-1.0e6, 1.0e6)
        self.ground_motion_scale.setDecimals(6)
        self.ground_motion_scale.setValue(1.0)
        self.ground_motion_scale.setToolTip(
            "Multiplies every value in the ground-motion file - e.g. 9.81 (or "
            "9810 in mm) if the file is in units of g rather than already "
            "matching this model's length unit."
        )
        self.ground_motion_scale.valueChanged.connect(self._on_ground_motion_scale_changed)
        scale_grid.addWidget(self.scale_factor_radio, 0, 0)
        scale_grid.addWidget(self.ground_motion_scale, 0, 1)
        self.target_pga_input = QDoubleSpinBox()
        self.target_pga_input.setRange(0.0, 1.0e6)
        self.target_pga_input.setDecimals(6)
        self.target_pga_input.setValue(0.0)
        self.target_pga_input.setEnabled(False)
        self.target_pga_input.setToolTip(
            "scale_factor = Target PGA / Original PGA - only available when the "
            "file's unit is known, so the two PGAs are actually comparable."
        )
        self.target_pga_input.valueChanged.connect(self._on_target_pga_changed)
        scale_grid.addWidget(self.target_pga_radio, 1, 0)
        scale_grid.addWidget(self.target_pga_input, 1, 1)
        ground_motion_layout.addLayout(scale_grid)

        self.target_pga_unit_note = QLabel(
            "Target PGA is unavailable - this file's unit was not detected, or "
            "its PGA is zero. Use Scale Factor directly instead."
        )
        self.target_pga_unit_note.setObjectName("secondaryText")
        self.target_pga_unit_note.setWordWrap(True)
        self.target_pga_unit_note.setVisible(False)
        ground_motion_layout.addWidget(self.target_pga_unit_note)

        readout_grid = QGridLayout()
        readout_grid.setHorizontalSpacing(24)
        readout_grid.setVerticalSpacing(5)
        self.original_pga_value = QLabel("—")
        self.applied_pga_value = QLabel("—")
        for row, (name, value_label) in enumerate((
            ("Original PGA", self.original_pga_value),
            ("Applied PGA", self.applied_pga_value),
        )):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            value_label.setObjectName("setupMetricValue")
            readout_grid.addWidget(key, row, 0)
            readout_grid.addWidget(value_label, row, 1)
        ground_motion_layout.addLayout(readout_grid)

        time_history_outer_layout.addWidget(self.time_history_ground_motion_card)

        self.time_history_damping_card, damping_layout = self._config_card("2. DAMPING")
        damping_layout.addWidget(self._field_label("DAMPING RATIO"))
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
        self.damping_ratio.valueChanged.connect(self._sync_store_options)
        damping_layout.addWidget(self.damping_ratio)
        damping_note = QLabel(
            "Rayleigh alpha/beta are computed automatically from the model's "
            "own first one or two natural frequencies - not entered directly."
        )
        damping_note.setObjectName("secondaryText")
        damping_note.setWordWrap(True)
        damping_layout.addWidget(damping_note)
        time_history_outer_layout.addWidget(self.time_history_damping_card)

        # Cards 3-4 are pure ANALYSIS_CAPABILITIES readouts - every value in
        # them is ENGINE_FIXED for Time History (see analysis_capabilities.py),
        # so unlike the ground motion/damping cards above they need no live
        # widget binding and are built once here, not refreshed on any event.
        self.time_history_integration_card, integration_layout = self._config_card(
            "3. TIME INTEGRATION"
        )
        th_capabilities = ANALYSIS_CAPABILITIES[AnalysisKind.TIME_HISTORY]
        integrator_details = dict(th_capabilities.dynamic_integrator.details)
        integration_grid = QGridLayout()
        integration_grid.setHorizontalSpacing(24)
        integration_grid.setVerticalSpacing(5)
        for row, (name, value) in enumerate(
            (
                (
                    "Method",
                    (
                        f"{th_capabilities.dynamic_integrator.value} "
                        "(Average Acceleration)   ·   FIXED"
                    ),
                ),
                ("Gamma", integrator_details.get("gamma", "—")),
                ("Beta", integrator_details.get("beta", "—")),
            )
        ):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            metric = QLabel(value)
            metric.setObjectName("setupMetricValue")
            integration_grid.addWidget(key, row, 0)
            integration_grid.addWidget(metric, row, 1)
        integration_layout.addLayout(integration_grid)
        integration_note = QLabel(
            "Newmark average-acceleration integration is fixed for every "
            "Time History run."
        )
        integration_note.setObjectName("secondaryText")
        integration_note.setWordWrap(True)
        integration_layout.addWidget(integration_note)
        time_history_outer_layout.addWidget(self.time_history_integration_card)

        self.time_history_solution_card, solution_layout_th = self._config_card(
            "4. SOLUTION / CONVERGENCE"
        )
        solution_subtitle = QLabel("SOLUTION")
        solution_subtitle.setObjectName("setupConfigTitle")
        solution_layout_th.addWidget(solution_subtitle)
        solution_grid_th = QGridLayout()
        solution_grid_th.setHorizontalSpacing(24)
        solution_grid_th.setVerticalSpacing(5)
        for row, (name, field) in enumerate(
            (
                ("Equation Solver", th_capabilities.equation_solver),
                ("Algorithm", th_capabilities.algorithm),
                ("Constraint Handler", th_capabilities.constraint_handler),
                ("DOF Numberer", th_capabilities.numberer),
            )
        ):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            metric = QLabel(f"{field.value}   ·   FIXED")
            metric.setObjectName("setupMetricValue")
            solution_grid_th.addWidget(key, row, 0)
            solution_grid_th.addWidget(metric, row, 1)
        solution_layout_th.addLayout(solution_grid_th)

        convergence_divider_th = QFrame()
        convergence_divider_th.setObjectName("setupGuideDivider")
        convergence_divider_th.setFrameShape(QFrame.Shape.HLine)
        solution_layout_th.addWidget(convergence_divider_th)

        convergence_subtitle = QLabel("CONVERGENCE")
        convergence_subtitle.setObjectName("setupConfigTitle")
        solution_layout_th.addWidget(convergence_subtitle)
        convergence_details_th = dict(th_capabilities.convergence_test.details)
        convergence_grid_th = QGridLayout()
        convergence_grid_th.setHorizontalSpacing(24)
        convergence_grid_th.setVerticalSpacing(5)
        for row, (name, value) in enumerate(
            (
                ("Test", f"{th_capabilities.convergence_test.value}   ·   FIXED"),
                ("Tolerance", convergence_details_th.get("tolerance", "—")),
                ("Max Iterations", convergence_details_th.get("maxIterations", "—")),
            )
        ):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            metric = QLabel(value)
            metric.setObjectName("setupMetricValue")
            convergence_grid_th.addWidget(key, row, 0)
            convergence_grid_th.addWidget(metric, row, 1)
        solution_layout_th.addLayout(convergence_grid_th)
        time_history_outer_layout.addWidget(self.time_history_solution_card)

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
        # Must run after every widget above exists - _apply_active_ground_motion()
        # ends in _sync_store_options()/build_options(), which (for whatever
        # AnalysisKind the combo defaults to) reads widgets built throughout
        # this constructor, not just the ground-motion ones.
        self._apply_active_ground_motion()

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
        if model is None:
            self._update_nonlinear_summary()
            self._update_linear_static_summary()
            self._update_nonlinear_behavior_tiles()
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
        self.nonlinear_group.setVisible(is_nonlinear_static)
        self.time_history_group.setVisible(is_time_history)
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

    def _choose_ground_motion_file(self) -> None:
        path_text, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "지진파(가속도) 파일 선택",
            "",
            "Ground motion files (*.txt *.csv *.AT2 *.dat);;All files (*.*)",
        )
        if not path_text:
            return
        path = Path(path_text)
        try:
            motion = load_ground_motion(path)
        except (ValueError, OSError) as error:
            # Validate at selection time rather than only deep inside the
            # worker subprocess at RUN time - a bad file should be obvious
            # immediately, and must not silently become "the last good file"
            # if the user already had one selected.
            self._imported_ground_motion_path = None
            self._imported_ground_motion = None
            self.ground_motion_path_label.setText(f"파일을 읽지 못했습니다: {error}")
            self.ground_motion_path_label.setToolTip(str(error))
            self._apply_active_ground_motion()
            return
        self._imported_ground_motion_path = path
        self._imported_ground_motion = motion
        self.ground_motion_path_label.setText(path.name)
        self.ground_motion_path_label.setToolTip(path_text)
        self._apply_active_ground_motion()

    def _on_ground_motion_source_changed(self, builtin_checked: bool) -> None:
        self.builtin_record_row.setVisible(builtin_checked)
        self.imported_file_row.setVisible(not builtin_checked)
        if builtin_checked and self._builtin_record is None and self.builtin_record_combo.count():
            # First time Built-in is chosen - default to whatever the combo
            # already shows (index 0), same as any other combo's default.
            self._on_builtin_record_selected()
        else:
            self._apply_active_ground_motion()

    def _on_builtin_record_selected(self) -> None:
        record = self.builtin_record_combo.currentData()
        if record is None:
            self._builtin_record = None
            self._builtin_ground_motion = None
            self.builtin_record_label.setText("(no record selected)")
        else:
            values = tuple(self._builtin_catalog.load_series(record))
            self._builtin_record = record
            self._builtin_ground_motion = GroundMotion.from_record(record, values)
            self.builtin_record_label.setText(self.builtin_record_combo.currentText())
        self._apply_active_ground_motion()

    def _choose_builtin_record(self) -> None:
        records = self._builtin_catalog.list_records()
        dialog = GroundMotionPickerDialog(records, self._builtin_record, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_record()
        if selected is None:
            return
        index = self.builtin_record_combo.findData(selected)
        if index < 0:
            return
        if index == self.builtin_record_combo.currentIndex():
            # Re-picking the same record: currentIndexChanged won't fire, but
            # the dialog itself is proof enough this is a deliberate confirm.
            return
        self.builtin_record_combo.setCurrentIndex(index)

    def _apply_active_ground_motion(self) -> None:
        """Point the single ``_ground_motion``/``_ground_motion_path`` pair -
        the only thing ``build_options()``, the info grid and the preview
        ever read - at whichever source is currently selected."""
        if self.source_builtin_radio.isChecked():
            self._ground_motion = self._builtin_ground_motion
            self._ground_motion_path = (
                self._builtin_record.path if self._builtin_record is not None else None
            )
        else:
            self._ground_motion = self._imported_ground_motion
            self._ground_motion_path = self._imported_ground_motion_path
        self._update_ground_motion_display()
        self._sync_store_options()

    def _update_ground_motion_display(self) -> None:
        motion = self._ground_motion
        has_motion = motion is not None
        self.ground_motion_info_placeholder.setVisible(not has_motion)
        self.ground_motion_info_grid_widget.setVisible(has_motion)
        if not has_motion:
            self.target_pga_radio.setEnabled(False)
            if self.target_pga_radio.isChecked():
                self.scale_factor_radio.setChecked(True)
            self.target_pga_unit_note.setVisible(False)
            self._update_ground_motion_preview()
            self._refresh_scaling_readouts()
            return
        self.gm_name_value.setText(motion.name)
        self.gm_dt_value.setText(f"{motion.dt:g} s")
        self.gm_npts_value.setText(str(motion.npts))
        self.gm_duration_value.setText(f"{motion.duration:.2f} s")
        unit_text = motion.unit if motion.unit is not None else "unit unknown"
        self.gm_pga_value.setText(f"{motion.pga:.4g} ({unit_text})")
        self.gm_unit_value.setText(motion.unit if motion.unit is not None else "Not detected")

        # Target PGA divides by the original PGA and only means anything if
        # the two PGAs share a unit - both a missing unit and a zero PGA make
        # that comparison meaningless, so the mode is simply unavailable
        # rather than guessing (see Phase 3-F's "don't fabricate unit info").
        target_pga_available = motion.unit is not None and motion.pga > 0.0
        self.target_pga_radio.setEnabled(target_pga_available)
        if not target_pga_available and self.target_pga_radio.isChecked():
            self.scale_factor_radio.setChecked(True)
        self.target_pga_unit_note.setVisible(not target_pga_available)

        self._update_ground_motion_preview()
        self._refresh_scaling_readouts()

    def _update_ground_motion_preview(self) -> None:
        motion = self._ground_motion
        if motion is None:
            self.ground_motion_preview.set_series((), (), y_label="")
            return
        scale = self.ground_motion_scale.value()
        times = tuple(index * motion.dt for index in range(motion.npts))
        values = tuple(value * scale for value in motion.accelerations)
        unit_label = motion.unit if motion.unit is not None else "unit unknown"
        self.ground_motion_preview.set_series(times, values, y_label=f"Accel [{unit_label}]")

    def _refresh_scaling_readouts(self) -> None:
        motion = self._ground_motion
        scale = self.ground_motion_scale.value()
        if motion is None:
            self.original_pga_value.setText("—")
            self.applied_pga_value.setText("—")
            return
        unit_suffix = f" {motion.unit}" if motion.unit else ""
        self.original_pga_value.setText(f"{motion.pga:.4g}{unit_suffix}")
        self.applied_pga_value.setText(f"{motion.pga * scale:.4g}{unit_suffix}")
        if self.scale_factor_radio.isChecked():
            # Mirrors what Target PGA would show for this same scale factor -
            # informative even while Scale Factor is the active input.
            self.target_pga_input.setValue(motion.pga * scale)

    def _on_scale_mode_changed(self) -> None:
        is_target_mode = self.target_pga_radio.isChecked()
        self.ground_motion_scale.setEnabled(not is_target_mode)
        self.target_pga_input.setEnabled(is_target_mode and self.target_pga_radio.isEnabled())
        self._refresh_scaling_readouts()

    def _on_ground_motion_scale_changed(self) -> None:
        if self._scaling_sync_in_progress:
            return
        self._sync_store_options()
        self._refresh_scaling_readouts()
        self._update_ground_motion_preview()

    def _on_target_pga_changed(self) -> None:
        if self._scaling_sync_in_progress or not self.target_pga_radio.isChecked():
            return
        motion = self._ground_motion
        if motion is None or motion.pga <= 0.0:
            return
        self._scaling_sync_in_progress = True
        try:
            self.ground_motion_scale.setValue(self.target_pga_input.value() / motion.pga)
        finally:
            self._scaling_sync_in_progress = False
        self._sync_store_options()
        self._refresh_scaling_readouts()
        self._update_ground_motion_preview()

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
