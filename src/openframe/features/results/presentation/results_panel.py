"""BMD, SFD, AFD and nodal-displacement result panel."""

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisResult, AnalysisStatus


class ResultsPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultsPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        result_header = QFrame()
        result_header.setObjectName("panelHeader")
        result_header_layout = QHBoxLayout(result_header)
        result_header_layout.setContentsMargins(14, 9, 14, 9)
        result_header_layout.addWidget(QLabel("ANALYSIS RESULTS"))
        result_header_layout.addStretch(1)
        self.status_badge = QLabel("WAITING")
        self.status_badge.setObjectName("waitingBadge")
        result_header_layout.addWidget(self.status_badge)
        layout.addWidget(result_header)

        result_content = QFrame()
        result_content.setObjectName("rightSection")
        result_layout = QVBoxLayout(result_content)
        result_layout.setContentsMargins(12, 10, 12, 12)

        self.result_tabs = QTabWidget()
        self.result_tabs.setObjectName("resultTabs")
        for label, title, unit in (
            ("BMD", "MAX. BENDING MOMENT", "kN·m"),
            ("SFD", "MAX. SHEAR FORCE", "kN"),
            ("AFD", "MAX. AXIAL FORCE", "kN"),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(8, 12, 8, 12)
            result_label = QLabel(title)
            result_label.setObjectName("resultLabel")
            value = QLabel(f"—  {unit}")
            value.setObjectName("resultValue")
            page_layout.addWidget(result_label)
            page_layout.addWidget(value)
            self.result_tabs.addTab(page, label)
        result_layout.addWidget(self.result_tabs)

        displacement_label = QLabel("NODAL DISPLACEMENTS")
        displacement_label.setObjectName("fieldLabel")
        result_layout.addWidget(displacement_label)
        self.displacement_table = QTableWidget(0, 3)
        self.displacement_table.setHorizontalHeaderLabels(("NODE", "UX", "UY"))
        self.displacement_table.verticalHeader().setVisible(False)
        self.displacement_table.setMinimumHeight(132)
        result_layout.addWidget(self.displacement_table)
        layout.addWidget(result_content, 1)

    def select_result(self, key: str) -> None:
        indexes = {"moment": 0, "shear": 1, "axial": 2}
        if key in indexes:
            self.result_tabs.setCurrentIndex(indexes[key])

    def show_result(self, result: AnalysisResult) -> None:
        self.status_badge.setText(
            "COMPLETED" if result.status == AnalysisStatus.COMPLETED else "FAILED"
        )

        nodes = sorted(result.node_results.values(), key=lambda item: item.node_tag)
        self.displacement_table.setRowCount(len(nodes))
        for row, node in enumerate(nodes):
            ux = node.displacement[0] if len(node.displacement) > 0 else 0.0
            uy = node.displacement[1] if len(node.displacement) > 1 else 0.0
            self.displacement_table.setItem(row, 0, QTableWidgetItem(str(node.node_tag)))
            self.displacement_table.setItem(row, 1, QTableWidgetItem(f"{ux:.6g}"))
            self.displacement_table.setItem(row, 2, QTableWidgetItem(f"{uy:.6g}"))

