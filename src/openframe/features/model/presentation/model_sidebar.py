"""Left-side file, model summary and structural entity explorer."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import StructuralModel, SupportKind

SUPPORT_NAMES = {
    SupportKind.FIXED: "고정지점",
    SupportKind.PINNED: "회전지점(힌지)",
    SupportKind.ROLLER_VERTICAL: "이동지점(수직 반력)",
    SupportKind.ROLLER_HORIZONTAL: "이동지점(수평 반력)",
    SupportKind.CUSTOM: "사용자 구속",
}


class ModelSidebar(QFrame):
    entity_selected = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelSidebar")
        self.setMinimumWidth(230)
        self.setMaximumWidth(310)
        self._tree_items: dict[tuple[str, int], QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("ACTIVE FILE"))
        file_card = QFrame()
        file_card.setObjectName("panelCard")
        file_layout = QVBoxLayout(file_card)
        file_layout.setContentsMargins(10, 9, 10, 9)
        self.file_name = QLabel("파일이 선택되지 않았습니다")
        self.file_name.setObjectName("fileName")
        self.file_path = QLabel("UPLOAD .PY 버튼으로 시작하세요")
        self.file_path.setObjectName("secondaryText")
        self.file_path.setWordWrap(True)
        file_layout.addWidget(self.file_name)
        file_layout.addWidget(self.file_path)
        layout.addWidget(file_card)

        layout.addWidget(self._section_label("MODEL SUMMARY"))
        summary = QFrame()
        summary.setObjectName("panelCard")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(10, 9, 10, 9)
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(8)
        self.summary_values: dict[str, QLabel] = {}
        for row, (label, key, value) in enumerate(
            (
                ("TYPE", "type", "2D Structure"),
                ("NODES", "nodes", "0"),
                ("ELEMENTS", "elements", "0"),
                ("SUPPORTS", "supports", "0"),
            )
        ):
            name = QLabel(label)
            name.setObjectName("summaryLabel")
            count = QLabel(value)
            count.setObjectName("summaryValue")
            summary_layout.addWidget(name, row, 0)
            summary_layout.addWidget(count, row, 1)
            self.summary_values[key] = count
        layout.addWidget(summary)

        layout.addWidget(self._section_label("MODEL CONTENT"))
        self.tree = QTreeWidget()
        self.tree.setObjectName("modelTree")
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._tree_selection_changed)
        self._show_empty_tree()
        layout.addWidget(self.tree, 1)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("●  Model workspace"))
        footer.addStretch(1)
        dimension = QLabel("2D")
        dimension.setObjectName("smallBadge")
        footer.addWidget(dimension)
        layout.addLayout(footer)

    def set_source_file(self, source: str) -> None:
        path = Path(source)
        self.file_name.setText(path.name)
        self.file_path.setText(str(path.parent))

    def set_model(self, model: StructuralModel) -> None:
        self.summary_values["type"].setText(f"{model.ndm}D Structure")
        self.summary_values["nodes"].setText(str(len(model.nodes)))
        self.summary_values["elements"].setText(str(len(model.elements)))
        self.summary_values["supports"].setText(str(len(model.boundaries)))

        self.tree.clear()
        self._tree_items.clear()
        nodes_item = QTreeWidgetItem(self.tree, [f"NODES  ({len(model.nodes)})"])
        for node in model.nodes.values():
            item = QTreeWidgetItem(
                nodes_item, [f"Node {node.tag}   ({node.x:g}, {node.y:g})"]
            )
            self._register_item(item, "node", node.tag)

        elements_item = QTreeWidgetItem(
            self.tree,
            [f"ELEMENTS  ({len(model.elements)})"],
        )
        for element in model.elements.values():
            item = QTreeWidgetItem(
                elements_item,
                [
                    (
                        f"Element {element.tag}   {element.node_i} → {element.node_j}"
                        f"   [{element.element_type}]"
                    )
                ],
            )
            self._register_item(item, "element", element.tag)

        supports_item = QTreeWidgetItem(
            self.tree,
            [f"SUPPORTS  ({len(model.boundaries)})"],
        )
        for boundary in model.boundaries:
            restraint_text = "".join("1" if value else "0" for value in boundary.restraints)
            item = QTreeWidgetItem(
                supports_item,
                [
                    (
                        f"Node {boundary.node_tag}   {SUPPORT_NAMES[boundary.support_kind]}"
                        f"   [{restraint_text}]"
                    )
                ],
            )
            self._register_item(item, "support", boundary.node_tag)

        loads_item = QTreeWidgetItem(
            self.tree,
            [f"LOADS  ({len(model.nodal_loads) + len(model.element_loads)})"],
        )
        for load in model.nodal_loads:
            values = ", ".join(f"{value:g}" for value in load.values)
            item = QTreeWidgetItem(loads_item, [f"Node {load.node_tag}   ({values})"])
            self._register_item(item, "load", load.node_tag)

        for load in model.element_loads:
            item = QTreeWidgetItem(
                loads_item,
                [
                    (
                        f"Element {load.element_tag}   Uniform"
                        f"   (Wx={load.wx:g}, Wy={load.wy:g})"
                    )
                ],
            )
            self._register_item(item, "element_load", load.element_tag)

        self.tree.expandToDepth(0)

    def select_entity(self, kind: str, tag: int) -> None:
        item = self._tree_items.get((kind, tag))
        if item is None or item is self.tree.currentItem():
            return
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self.tree.blockSignals(False)

    def _register_item(self, item: QTreeWidgetItem, kind: str, tag: int) -> None:
        identity = (kind, tag)
        item.setData(0, Qt.ItemDataRole.UserRole, identity)
        self._tree_items[identity] = item

    def _tree_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        identity = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(identity, tuple) and len(identity) == 2:
            self.entity_selected.emit(str(identity[0]), int(identity[1]))

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _show_empty_tree(self) -> None:
        for text in ("NODES  (0)", "ELEMENTS  (0)", "SUPPORTS  (0)", "LOADS  (0)"):
            parent_item = QTreeWidgetItem(self.tree, [text])
            QTreeWidgetItem(parent_item, ["데이터 없음"])
