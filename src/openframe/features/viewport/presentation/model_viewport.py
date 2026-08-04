"""Central structural canvas and compact display controls."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    FORCE_UNITS,
    LENGTH_UNITS,
    Element,
    Node,
    StructuralModel,
    UnitSystem,
)
from openframe.features.viewport.presentation.structural_graphics_view import (
    StructuralGraphicsView,
)
from openframe.features.viewport.scene import StructuralScene


class ModelViewport(QFrame):
    unit_system_changed = Signal(object)
    entity_selected = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelViewport")
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._sample_load_text = None
        self._model: StructuralModel | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        canvas_header = QFrame()
        canvas_header.setObjectName("canvasHeader")
        header_layout = QHBoxLayout(canvas_header)
        header_layout.setContentsMargins(12, 7, 9, 7)
        title = QLabel("STRUCTURAL WORKSPACE")
        title.setObjectName("sectionLabel")
        self.mode_label = QLabel("SAMPLE PREVIEW")
        self.mode_label.setObjectName("smallBadge")
        header_layout.addWidget(title)
        header_layout.addWidget(self.mode_label)
        support_legend = QLabel("지점  ▰ 고정   △ 회전   △○ 이동")
        support_legend.setObjectName("supportLegend")
        support_legend.setToolTip("고정지점, 회전지점(힌지), 이동지점(롤러) 기호")
        header_layout.addWidget(support_legend)
        header_layout.addStretch(1)
        self.view_selector = QComboBox()
        self.view_selector.setObjectName("projectionSelector")
        self.view_selector.addItem("ISO", "iso")
        self.view_selector.addItem("XY", "xy")
        self.view_selector.addItem("XZ", "xz")
        self.view_selector.addItem("YZ", "yz")
        self.view_selector.addItem("FREE", "free")
        self.view_selector.setToolTip("3D model projection")
        self.view_selector.setMaximumWidth(72)
        self.orbit_hint = QLabel("MMB ORBIT · SHIFT+MMB PAN · WHEEL ZOOM")
        self.orbit_hint.setObjectName("supportLegend")
        self.orbit_hint.hide()
        header_layout.addWidget(self.orbit_hint)
        header_layout.addWidget(self.view_selector)
        zoom_out = QPushButton("−")
        zoom_out.setObjectName("canvasToolButton")
        zoom_in = QPushButton("+")
        zoom_in.setObjectName("canvasToolButton")
        fit = QPushButton("FIT")
        fit.setObjectName("canvasToolButton")
        header_layout.addWidget(zoom_out)
        header_layout.addWidget(zoom_in)
        header_layout.addWidget(fit)
        layout.addWidget(canvas_header)

        self.scene = StructuralScene(self)
        self.scene.selectionChanged.connect(self._scene_selection_changed)
        self.view = StructuralGraphicsView(self.scene)
        self.view.setObjectName("structuralView")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        layout.addWidget(self.view, 1)

        controls = QFrame()
        controls.setObjectName("displayControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 6, 10, 6)
        controls_layout.setSpacing(10)
        controls_layout.addWidget(QLabel("DISPLAY FILTERS"))
        self.filter_options: dict[str, QCheckBox] = {}
        for text, item_kind in (
            ("Nodes", "node"),
            ("Node IDs", "node_label"),
            ("Elements", "element"),
            ("Supports", "support"),
            ("Loads", "load"),
        ):
            option = QCheckBox(text)
            option.setChecked(True)
            option.toggled.connect(
                lambda visible, kind=item_kind: self._set_item_kind_visible(kind, visible)
            )
            self.filter_options[item_kind] = option
            controls_layout.addWidget(option)
        controls_layout.addStretch(1)
        deformation = QCheckBox("DEFORMATION")
        controls_layout.addWidget(deformation)
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(1, 100)
        self.scale_slider.setValue(30)
        self.scale_slider.setMaximumWidth(120)
        controls_layout.addWidget(self.scale_slider)
        controls_layout.addWidget(QLabel("FORCE"))
        self.force_unit_selector = QComboBox()
        self.force_unit_selector.setObjectName("forceUnitSelector")
        self.force_unit_selector.setMaximumWidth(64)
        self.force_unit_selector.setToolTip(
            "Declare the force unit used by the OpenSees model."
        )
        self.force_unit_selector.addItems(FORCE_UNITS)
        controls_layout.addWidget(self.force_unit_selector)
        controls_layout.addWidget(QLabel("LENGTH"))
        self.length_unit_selector = QComboBox()
        self.length_unit_selector.setObjectName("lengthUnitSelector")
        self.length_unit_selector.setMaximumWidth(64)
        self.length_unit_selector.setToolTip(
            "Declare the length unit used by the OpenSees model."
        )
        self.length_unit_selector.addItems(LENGTH_UNITS)
        controls_layout.addWidget(self.length_unit_selector)
        layout.addWidget(controls)

        zoom_in.clicked.connect(lambda: self.view.scale(1.2, 1.2))
        zoom_out.clicked.connect(lambda: self.view.scale(1 / 1.2, 1 / 1.2))
        fit.clicked.connect(self.fit_model)
        self.force_unit_selector.currentIndexChanged.connect(self._change_unit_system)
        self.length_unit_selector.currentIndexChanged.connect(self._change_unit_system)
        self.view_selector.currentIndexChanged.connect(self._change_projection)
        self.view.orbit_dragged.connect(self._orbit_view)
        self._show_sample_beam()

    @property
    def unit_system(self) -> UnitSystem:
        return self._unit_system

    def fit_model(self) -> None:
        self.view.fit_content()

    def show_uploaded_file(self) -> None:
        self.mode_label.setText("MODEL LOADED")

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self._sample_load_text = None
        projection = "iso" if model.ndm == 3 else "xy"
        self.view_selector.blockSignals(True)
        self.view_selector.setCurrentIndex(self.view_selector.findData(projection))
        self.view_selector.setVisible(model.ndm == 3)
        self.orbit_hint.setVisible(model.ndm == 3)
        self.view.set_orbit_enabled(model.ndm == 3)
        self.view_selector.blockSignals(False)
        self.scene.set_projection(projection)
        self.scene.set_model(model)
        for item_kind, option in self.filter_options.items():
            self._set_item_kind_visible(item_kind, option.isChecked())
        self.mode_label.setText("MODEL LOADED")
        if not model.nodes:
            self.view.set_content_scene_rect(QRectF(-8.0, -5.0, 16.0, 9.0))
            return

        self._update_content_rect()
        self.fit_model()

    def _orbit_view(self, delta_x: float, delta_y: float) -> None:
        if self._model is None or self._model.ndm != 3:
            return
        self.scene.orbit(delta_x, delta_y)
        self.view_selector.blockSignals(True)
        self.view_selector.setCurrentIndex(self.view_selector.findData("free"))
        self.view_selector.blockSignals(False)
        for item_kind, option in self.filter_options.items():
            self._set_item_kind_visible(item_kind, option.isChecked())
        self._update_content_rect()

    def _change_projection(self, index: int) -> None:
        del index
        projection = self.view_selector.currentData()
        if projection is None or projection == "free":
            return
        self.scene.set_projection(str(projection))
        for item_kind, option in self.filter_options.items():
            self._set_item_kind_visible(item_kind, option.isChecked())
        if self.scene.items():
            self._update_content_rect()
            self.fit_model()

    def _update_content_rect(self) -> None:
        if self._model is None or not self._model.nodes:
            return
        points = [
            self.scene.project_coordinates(node.x, node.y, node.z)
            for node in self._model.nodes.values()
        ]
        x_values = [point.x() for point in points]
        y_values = [point.y() for point in points]
        x_span = max(x_values) - min(x_values)
        y_span = max(y_values) - min(y_values)
        margin = max(x_span, y_span, 1.0) * 0.18
        self.view.set_content_scene_rect(
            QRectF(
                min(x_values) - margin,
                min(y_values) - margin,
                x_span + 2 * margin,
                y_span + 2 * margin,
            )
        )

    def _set_item_kind_visible(self, item_kind: str, visible: bool) -> None:
        if item_kind == "node_label":
            visible = visible and self.filter_options["node"].isChecked()
        for item in self.scene.items():
            identity = item.data(0)
            visible_kinds = (
                {"load", "element_load"}
                if item_kind == "load"
                else {item_kind}
            )
            if isinstance(identity, tuple) and identity and identity[0] in visible_kinds:
                item.setVisible(visible)
        if item_kind == "node":
            labels_visible = visible and self.filter_options["node_label"].isChecked()
            self._set_item_kind_visible("node_label", labels_visible)

    def select_entity(self, kind: str, tag: int) -> None:
        target = None
        self.scene.blockSignals(True)
        self.scene.clearSelection()
        for item in self.scene.items():
            if item.data(0) == (kind, tag):
                item.setSelected(True)
                target = item
                break
        self.scene.blockSignals(False)
        if target is not None:
            self.view.ensureVisible(target)

    def _scene_selection_changed(self) -> None:
        selected_items = self.scene.selectedItems()
        if not selected_items:
            return
        identity = selected_items[0].data(0)
        if isinstance(identity, tuple) and len(identity) == 2:
            try:
                tag = int(identity[1])
            except (TypeError, ValueError):
                return
            self.entity_selected.emit(str(identity[0]), tag)

    def _change_unit_system(self, index: int) -> None:
        del index
        unit_system = UnitSystem(
            force=self.force_unit_selector.currentText(),
            length=self.length_unit_selector.currentText(),
        )
        self._unit_system = unit_system
        self.scene.set_unit_system(unit_system)
        if self._sample_load_text is not None:
            self._sample_load_text.setPlainText(f"10 {unit_system.force}")
        self.unit_system_changed.emit(unit_system)

    def _show_sample_beam(self) -> None:
        self.view_selector.hide()
        model = StructuralModel(
            nodes={1: Node(1, -6.0, 0.0), 2: Node(2, 6.0, 0.0)},
            elements={1: Element(1, 1, 2, "elasticBeamColumn")},
            metadata={"display": "sample"},
        )
        self.scene.set_model(model)
        load_pen = QPen(QColor("#e5484d"), 0.10)
        load_line = self.scene.addLine(0.0, -3.0, 0.0, -0.35, load_pen)
        arrow = QPolygonF(
            [QPointF(-0.20, -0.62), QPointF(0.20, -0.62), QPointF(0.0, -0.20)]
        )
        load_arrow = self.scene.addPolygon(arrow, load_pen, QColor("#e5484d"))
        load_text = self.scene.addText(f"10 {self._unit_system.force}")
        load_text.setDefaultTextColor(QColor("#d43e44"))
        load_text.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        load_text.setPos(0.35, -2.7)
        for item in (load_line, load_arrow, load_text):
            item.setData(0, ("load", "sample"))
        self._sample_load_text = load_text
        self.view.set_content_scene_rect(QRectF(-8.0, -5.0, 16.0, 9.0))
