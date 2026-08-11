import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Element,
    ElementResult,
    ModeShape,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.presentation.result_tables_panel import ResultTablesPanel


def _panel() -> ResultTablesPanel:
    QApplication.instance() or QApplication([])
    return ResultTablesPanel()


def _row_texts(table, row: int) -> list[str]:
    return [table.item(row, column).text() for column in range(table.columnCount())]


def test_member_force_table_shows_both_end_forces_unlike_the_old_i_end_only_view() -> None:
    """The narrow per-diagram table this panel replaces only ever showed the
    i-end (N-i/V-i/M-i) - a real spreadsheet view needs both ends."""
    panel = _panel()
    model = StructuralModel(
        ndm=2,
        elements={1: Element(tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn")},
    )
    panel.set_model(model)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(element_tag=1, local_forces=(10.0, 20.0, 30.0, -10.0, -20.0, 40.0))
            },
        )
    )

    table = panel.member_force_table
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers[0] == "ELEMENT"
    assert any(header.startswith("N-i") for header in headers)
    assert any(header.startswith("N-j") for header in headers)
    row = _row_texts(table, 0)
    assert row[0] == "1"
    assert [float(value) for value in row[1:]] == [10.0, 20.0, 30.0, -10.0, -20.0, 40.0]


def test_modal_tab_is_hidden_without_mode_shapes_and_shown_once_present() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(AnalysisResult(status=AnalysisStatus.COMPLETED))
    assert panel.tabs.isTabVisible(panel._modal_tab_index) is False

    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            mode_shapes=(
                ModeShape(
                    mode_number=1,
                    eigenvalue=4.0,
                    angular_frequency=2.0,
                    frequency_hz=2.0 / (2 * 3.141592653589793),
                    period=3.141592653589793,
                    mass_participation_ratio=(0.75, 0.1, 0.15),
                ),
            ),
        )
    )
    assert panel.tabs.isTabVisible(panel._modal_tab_index) is True

    table = panel.modal_table
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "1"
    # 참여율 columns come right after MODE/PERIOD/FREQUENCY (3 columns).
    assert float(table.item(0, 3).text()) == 75.0
    assert float(table.item(0, 4).text()) == 10.0
    assert float(table.item(0, 5).text()) == 15.0


def test_displacement_table_lists_every_node_regardless_of_selected_result_type() -> None:
    """Unlike the old data panel (one force diagram at a time), this table
    always shows every node - there is no per-quantity filter to forget."""
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            node_results={
                1: NodeResult(1, displacement=(0.01, -0.02, 0.0)),
                2: NodeResult(2, displacement=(0.03, 0.0, 0.001)),
            },
        )
    )

    table = panel.displacement_table
    assert table.rowCount() == 2
    node_tags = {table.item(row, 0).text() for row in range(table.rowCount())}
    assert node_tags == {"1", "2"}
