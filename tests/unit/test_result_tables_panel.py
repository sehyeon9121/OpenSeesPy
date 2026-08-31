import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    UNIT_STIFFNESS_DISPLACEMENT_WARNING,
    AnalysisResult,
    AnalysisStatus,
    BucklingMode,
    DisplacementStiffnessKind,
    Element,
    ElementResult,
    ModeShape,
    NodeResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.presentation.result_tables_panel import ResultTablesPanel
from openframe.features.results.stress import fibre_stress


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
    assert i_headers == ["ELEMENT", "N (kN)", "V (kN)", "M (kN·m)", "σ (kN/m²)"]
    assert j_headers == i_headers

    i_row = _row_texts(i_table, 0)
    j_row = _row_texts(j_table, 0)
    assert i_row[0] == j_row[0] == "1"
    assert [float(value) for value in i_row[1:4]] == [10.0, 20.0, 30.0]
    assert [float(value) for value in j_row[1:4]] == [-10.0, -20.0, 40.0]
    # No section (no "A") assigned to this element - stress must read "-",
    # never a crash or a silently wrong 0.
    assert i_row[4] == "-"
    assert j_row[4] == "-"


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


def test_axial_stress_matches_hand_calculation_and_differs_between_i_and_j_ends() -> None:
    """σ = N/A, computed independently at each end from that end's own axial
    force - i and j must not accidentally share one value."""
    panel = _panel()
    model = StructuralModel(
        ndm=2,
        elements={
            1: Element(
                tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn",
                properties={"A": 0.01},
            )
        },
    )
    panel.set_model(model)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(element_tag=1, local_forces=(100.0, 0.0, 0.0, -50.0, 0.0, 0.0))
            },
        )
    )

    i_row = _row_texts(panel.member_force_i_table, 0)
    j_row = _row_texts(panel.member_force_j_table, 0)
    assert float(i_row[4]) == pytest.approx(100.0 / 0.01)  # 10,000
    assert float(j_row[4]) == pytest.approx(-50.0 / 0.01)  # -5,000
    assert float(i_row[4]) != float(j_row[4])


@pytest.mark.parametrize(
    "properties",
    [
        {},  # no "A" assigned at all
        {"A": 0.0},
        {"A": -0.005},
        {"A": "not-a-number"},
    ],
    ids=["missing", "zero", "negative", "unparseable"],
)
def test_axial_stress_reads_as_a_dash_instead_of_crashing_for_unusable_area(
    properties: dict,
) -> None:
    panel = _panel()
    model = StructuralModel(
        ndm=2,
        elements={
            1: Element(tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn", properties=properties)
        },
    )
    panel.set_model(model)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(element_tag=1, local_forces=(100.0, 0.0, 0.0, -100.0, 0.0, 0.0))
            },
        )
    )

    i_row = _row_texts(panel.member_force_i_table, 0)
    j_row = _row_texts(panel.member_force_j_table, 0)
    assert i_row[4] == "-"
    assert j_row[4] == "-"


def test_axial_stress_table_handles_a_mix_of_elements_with_and_without_a_section() -> None:
    panel = _panel()
    model = StructuralModel(
        ndm=2,
        elements={
            1: Element(
                tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn",
                properties={"A": 0.02},
            ),
            2: Element(tag=2, node_i=2, node_j=3, element_type="elasticBeamColumn"),
        },
    )
    panel.set_model(model)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(element_tag=1, local_forces=(40.0, 0.0, 0.0, -40.0, 0.0, 0.0)),
                2: ElementResult(element_tag=2, local_forces=(10.0, 0.0, 0.0, -10.0, 0.0, 0.0)),
            },
        )
    )

    table = panel.member_force_i_table
    assert table.rowCount() == 2
    rows = {table.item(row, 0).text(): _row_texts(table, row) for row in range(table.rowCount())}
    assert float(rows["1"][4]) == pytest.approx(40.0 / 0.02)
    assert rows["2"][4] == "-"


def test_changing_unit_system_updates_both_stress_header_and_recomputed_values() -> None:
    """The panel itself owns no conversion factor - it simply relabels with
    the current UnitSystem.stress and recomputes N/A from whatever model/
    result it is currently given, so a caller that re-supplies an
    already-converted model+result under a new unit system sees both the
    header and the values change together."""
    panel = _panel()
    model_kn_m = StructuralModel(
        ndm=2,
        elements={
            1: Element(
                tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn",
                properties={"A": 0.01},
            )
        },
    )
    panel.set_model(model_kn_m)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(element_tag=1, local_forces=(100.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            },
        )
    )
    header_before = panel.member_force_i_table.horizontalHeaderItem(4).text()
    value_before = float(_row_texts(panel.member_force_i_table, 0)[4])
    assert header_before == "σ (kN/m²)"
    assert value_before == pytest.approx(10000.0)

    # N -> 100,000 N (same 100 kN) and A -> 10,000 mm^2 (same 0.01 m^2),
    # as an upstream unit conversion would have already produced.
    panel.set_unit_system(UnitSystem(force="N", length="mm"))
    model_n_mm = StructuralModel(
        ndm=2,
        elements={
            1: Element(
                tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn",
                properties={"A": 10000.0},
            )
        },
    )
    panel.set_model(model_n_mm)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(element_tag=1, local_forces=(100000.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            },
        )
    )

    header_after = panel.member_force_i_table.horizontalHeaderItem(4).text()
    value_after = float(_row_texts(panel.member_force_i_table, 0)[4])
    assert header_after == "σ (N/mm²)"
    assert value_after == pytest.approx(10.0)  # 100,000 N / 10,000 mm^2
    assert value_after != value_before


def test_axial_stress_column_appears_for_a_mixed_truss_and_frame_3d_model() -> None:
    """A model mixing frame and truss element_type values falls into the
    general 3D table (never the 2D-only pure-truss table), which must also
    get the stress column - see _is_truss_model()'s all-elements gate."""
    panel = _panel()
    model = StructuralModel(
        ndm=3,
        elements={
            1: Element(
                tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn",
                properties={"A": 0.02},
            ),
            2: Element(
                tag=2, node_i=2, node_j=3, element_type="truss",
                properties={"A": 0.001},
            ),
        },
    )
    panel.set_model(model)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(
                    element_tag=1,
                    local_forces=(20.0, 0.0, 0.0, 0.0, 0.0, 0.0, -20.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                ),
                2: ElementResult(
                    element_tag=2,
                    local_forces=(-5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                ),
            },
        )
    )

    assert panel.member_force_stack.currentWidget() is panel.member_force_i_table.parentWidget()
    i_table = panel.member_force_i_table
    headers = [i_table.horizontalHeaderItem(c).text() for c in range(i_table.columnCount())]
    assert headers[-1] == "σ (kN/m²)"
    rows = {i_table.item(row, 0).text(): _row_texts(i_table, row) for row in range(i_table.rowCount())}
    assert float(rows["1"][-1]) == pytest.approx(20.0 / 0.02)
    assert float(rows["2"][-1]) == pytest.approx(-5.0 / 0.001)


def test_frame_stress_column_matches_shared_fibre_stress_helper() -> None:
    panel = _panel()
    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="elasticBeamColumn",
        properties={"A": 0.15, "I": 0.003125, "height": 0.5},
    )
    panel.set_model(StructuralModel(ndm=2, elements={1: element}))
    local_forces = (-30.0, 0.0, -10.0, 30.0, 0.0, 10.0)
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={1: ElementResult(element_tag=1, local_forces=local_forces)},
        )
    )

    i_row = _row_texts(panel.member_force_i_table, 0)
    j_row = _row_texts(panel.member_force_j_table, 0)
    expected_i = fibre_stress(element, axial_force=-30.0, moment=-10.0, ndm=2)
    expected_j = fibre_stress(element, axial_force=30.0, moment=10.0, ndm=2)
    assert expected_i is not None and expected_j is not None
    assert float(i_row[4]) == pytest.approx(expected_i)
    assert float(j_row[4]) == pytest.approx(expected_j)


def test_frame_stress_column_is_a_dash_when_moment_is_present_without_inertia() -> None:
    panel = _panel()
    panel.set_model(
        StructuralModel(
            ndm=2,
            elements={
                1: Element(
                    tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn",
                    properties={"A": 0.01},
                )
            },
        )
    )
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            element_results={
                1: ElementResult(
                    element_tag=1, local_forces=(-30.0, 0.0, -10.0, 30.0, 0.0, 10.0)
                )
            },
        )
    )

    assert _row_texts(panel.member_force_i_table, 0)[4] == "-"
    assert _row_texts(panel.member_force_j_table, 0)[4] == "-"


def test_unit_stiffness_result_relabels_displacement_units_and_shows_warning() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            displacement_stiffness=DisplacementStiffnessKind.UNIT_STIFFNESS,
            node_results={1: NodeResult(1, displacement=(0.01, -0.02, 0.0))},
        )
    )

    headers = [
        panel.displacement_table.horizontalHeaderItem(column).text()
        for column in range(panel.displacement_table.columnCount())
    ]
    assert headers[1] == "UX (상대)"
    assert headers[2] == "UY (상대)"
    assert not panel.stiffness_warning.isHidden()
    assert panel.stiffness_warning.text() == UNIT_STIFFNESS_DISPLACEMENT_WARNING
    assert panel.displacement_table.item(0, 1).text() == "0.01"

    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            displacement_stiffness=DisplacementStiffnessKind.PHYSICAL,
            node_results={1: NodeResult(1, displacement=(0.01, -0.02, 0.0))},
        )
    )
    headers_after = [
        panel.displacement_table.horizontalHeaderItem(column).text()
        for column in range(panel.displacement_table.columnCount())
    ]
    assert headers_after[1].startswith("UX (")
    assert "상대" not in headers_after[1]
    assert panel.stiffness_warning.isHidden()
