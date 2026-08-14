import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    BucklingMode,
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


def test_member_force_tables_split_i_and_j_ends_into_separate_stacked_tables() -> None:
    """The narrow per-diagram table this panel replaces only ever showed the
    i-end (N-i/V-i/M-i) - a real spreadsheet view needs both ends, and i/j are
    a genuinely different category so they get their own table rather than
    doubling the column count of one wide row."""
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

    assert panel.member_force_stack.currentWidget() is panel.member_force_i_table.parentWidget()

    i_table = panel.member_force_i_table
    j_table = panel.member_force_j_table
    i_headers = [i_table.horizontalHeaderItem(c).text() for c in range(i_table.columnCount())]
    j_headers = [j_table.horizontalHeaderItem(c).text() for c in range(j_table.columnCount())]
    assert i_headers == ["ELEMENT", "N (kN)", "V (kN)", "M (kN·m)"]
    assert j_headers == i_headers

    i_row = _row_texts(i_table, 0)
    j_row = _row_texts(j_table, 0)
    assert i_row[0] == j_row[0] == "1"
    assert [float(value) for value in i_row[1:]] == [10.0, 20.0, 30.0]
    assert [float(value) for value in j_row[1:]] == [-10.0, -20.0, 40.0]


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

    properties = panel.modal_properties_table
    assert properties.rowCount() == 1
    assert properties.item(0, 0).text() == "1"
    assert float(properties.item(0, 1).text()) == pytest.approx(3.141592653589793, rel=1e-5)

    participation = panel.modal_participation_table
    assert participation.item(0, 0).text() == "1"
    assert float(participation.item(0, 1).text()) == 75.0
    assert float(participation.item(0, 2).text()) == 10.0
    assert float(participation.item(0, 3).text()) == 15.0

    # A single mode's cumulative participation equals its own participation.
    cumulative = panel.modal_cumulative_table
    assert float(cumulative.item(0, 1).text()) == 75.0
    assert float(cumulative.item(0, 2).text()) == 10.0
    assert float(cumulative.item(0, 3).text()) == 15.0


def test_buckling_tab_is_hidden_without_buckling_modes_and_shown_once_present() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(AnalysisResult(status=AnalysisStatus.COMPLETED))
    assert panel.tabs.isTabVisible(panel._buckling_tab_index) is False

    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            buckling_modes=(
                BucklingMode(
                    mode_number=1,
                    buckling_load_factor=12.45,
                    raw_eigenvalue=12.45,
                    reference_load_case="Pattern 1",
                    reference_load_scale=1.0,
                ),
                BucklingMode(
                    mode_number=2,
                    buckling_load_factor=37.18,
                    raw_eigenvalue=37.18,
                    reference_load_case="Pattern 1",
                    reference_load_scale=1.0,
                ),
            ),
        )
    )
    assert panel.tabs.isTabVisible(panel._buckling_tab_index) is True

    table = panel.buckling_modes_table
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "1"
    assert float(table.item(0, 1).text()) == pytest.approx(12.45)
    assert table.item(1, 0).text() == "2"
    assert float(table.item(1, 1).text()) == pytest.approx(37.18)

    # The critical (first, lowest-factor) mode drives the summary block.
    assert panel.buckling_summary_labels["factor"].text() == "12.45"
    assert panel.buckling_summary_labels["case"].text() == "Pattern 1"
    assert "12.45" in panel.buckling_summary_labels["state"].text()
    assert "Pattern 1" in panel.buckling_summary_labels["state"].text()

    # Modal and buckling tabs never share a table - this must never populate
    # modal_properties_table (no period/frequency exists for a buckling mode).
    assert panel.modal_properties_table.rowCount() == 0


def test_buckling_summary_shows_the_reference_load_scale_when_not_one() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            buckling_modes=(
                BucklingMode(
                    mode_number=1,
                    buckling_load_factor=6.2,
                    raw_eigenvalue=6.2,
                    reference_load_case="All Patterns",
                    reference_load_scale=2.0,
                ),
            ),
        )
    )
    assert "x2" in panel.buckling_summary_labels["state"].text()


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
