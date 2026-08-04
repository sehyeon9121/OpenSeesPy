"""Central structural canvas and compact display controls."""

from PySide6.QtCore import QPointF, Qt, Signal
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
from openframe.features.viewport.scene import StructuralScene


class ModelViewport(QFrame):
    unit_system_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelViewport")
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._sample_load_text = None

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
        self.view = QGraphicsView(self.scene)
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
        self._show_sample_beam()

    @property
    def unit_system(self) -> UnitSystem:
        return self._unit_system

    def fit_model(self) -> None:
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def show_uploaded_file(self) -> None:
        self.mode_label.setText("MODEL LOADED")

    def set_model(self, model: StructuralModel) -> None:
        self._sample_load_text = None
        self.scene.set_model(model)
        for item_kind, option in self.filter_options.items():
            self._set_item_kind_visible(item_kind, option.isChecked())
        self.mode_label.setText("MODEL LOADED")
        if not model.nodes:
            self.scene.setSceneRect(-8.0, -5.0, 16.0, 9.0)
            return

        x_values = [node.x for node in model.nodes.values()]
        screen_y_values = [-node.y for node in model.nodes.values()]
        x_span = max(x_values) - min(x_values)
        y_span = max(screen_y_values) - min(screen_y_values)
        margin = max(x_span, y_span, 1.0) * 0.18
        self.scene.setSceneRect(
            min(x_values) - margin,
            min(screen_y_values) - margin,
            x_span + 2 * margin,
            y_span + 2 * margin,
        )
        self.fit_model()

    def _set_item_kind_visible(self, item_kind: str, visible: bool) -> None:
        if item_kind == "node_label":
            visible = visible and self.filter_options["node"].isChecked()
        for item in self.scene.items():
            identity = item.data(0)
            if isinstance(identity, tuple) and identity and identity[0] == item_kind:
                item.setVisible(visible)
        if item_kind == "node":
            labels_visible = visible and self.filter_options["node_label"].isChecked()
            self._set_item_kind_visible("node_label", labels_visible)

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
        self.scene.setSceneRect(-8.0, -5.0, 16.0, 9.0)
