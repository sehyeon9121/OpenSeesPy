"""LoadCombinationPanel: pure widget behaviour, no canvas/solver wiring yet
(see the module's own docstring for why that split is deliberate)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import LoadCaseKind, LoadCombination
from openframe.features.model.presentation.load_combination_panel import LoadCombinationPanel


def _panel() -> LoadCombinationPanel:
    QApplication.instance() or QApplication([])
    panel = LoadCombinationPanel()
    panel.show()
    return panel


def test_panel_starts_empty_and_shows_the_empty_hint() -> None:
    panel = _panel()

    assert panel.combinations() == []
    assert panel.empty_hint.isVisible() is True


def test_adding_a_row_hides_the_empty_hint_and_appears_in_combinations() -> None:
    panel = _panel()

    panel.add_row("1.2DL+1.6LL", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6})

    assert panel.empty_hint.isVisible() is False
    combos = panel.combinations()
    assert len(combos) == 1
    assert combos[0] == LoadCombination(
        name="1.2DL+1.6LL", factors={LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6}
    )


def test_a_zero_factor_is_left_out_of_the_resulting_combination() -> None:
    """0.0 means "this case does not participate" - LoadCombination.factor_for
    already treats an absent key the same as an explicit 0.0, so a row is
    free to just not carry the key rather than storing a meaningless zero."""
    panel = _panel()

    row = panel.add_row("DL only", {LoadCaseKind.DEAD: 1.0})
    row.factor_spinboxes[LoadCaseKind.LIVE].setValue(0.0)

    combo = panel.combinations()[0]
    assert LoadCaseKind.LIVE not in combo.factors
    assert combo.factors[LoadCaseKind.DEAD] == 1.0


def test_editing_a_rows_fields_after_it_was_added_is_reflected_live() -> None:
    panel = _panel()
    row = panel.add_row("draft")

    row.name_edit.setText("1.4DL")
    row.factor_spinboxes[LoadCaseKind.DEAD].setValue(1.4)

    combo = panel.combinations()[0]
    assert combo.name == "1.4DL"
    assert combo.factors[LoadCaseKind.DEAD] == 1.4


def test_an_empty_name_falls_back_to_a_default_rather_than_an_empty_string() -> None:
    panel = _panel()
    row = panel.add_row("")

    combo = row.to_combination()

    assert combo.name == "조합"


def test_removing_a_row_drops_it_from_combinations_and_restores_the_empty_hint() -> None:
    panel = _panel()
    row = panel.add_row("temp", {LoadCaseKind.WIND: 1.0})
    assert panel.empty_hint.isVisible() is False

    row.removed.emit(row)

    assert panel.combinations() == []
    assert panel.empty_hint.isVisible() is True


def test_removing_one_row_of_several_leaves_the_others_intact() -> None:
    panel = _panel()
    panel.add_row("A", {LoadCaseKind.DEAD: 1.0})
    row_b = panel.add_row("B", {LoadCaseKind.LIVE: 1.0})
    panel.add_row("C", {LoadCaseKind.WIND: 1.0})

    row_b.removed.emit(row_b)

    names = [combo.name for combo in panel.combinations()]
    assert names == ["A", "C"]


def test_set_combinations_replaces_whatever_rows_existed_before() -> None:
    panel = _panel()
    panel.add_row("stale", {LoadCaseKind.DEAD: 1.0})

    panel.set_combinations(
        [
            LoadCombination("1.2DL+1.6LL", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6}),
            LoadCombination("0.9DL+1.0EQ", {LoadCaseKind.DEAD: 0.9, LoadCaseKind.SEISMIC: 1.0}),
        ]
    )

    combos = panel.combinations()
    assert [combo.name for combo in combos] == ["1.2DL+1.6LL", "0.9DL+1.0EQ"]
    assert combos[1].factors[LoadCaseKind.SEISMIC] == 1.0


def test_unclassified_is_not_offered_as_a_combinable_case() -> None:
    """A load nobody tagged with a real case must never be sweepable into a
    combination just because a row happens to expose a factor field for it -
    see LoadCombination.factor_for's own docstring."""
    panel = _panel()
    row = panel.add_row("any")

    assert LoadCaseKind.UNCLASSIFIED not in row.factor_spinboxes
