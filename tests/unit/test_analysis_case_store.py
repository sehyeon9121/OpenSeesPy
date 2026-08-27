"""AnalysisCaseStore - CRUD, active-case tracking, and per-case isolation
(editing/switching one case must never touch another's settings)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind
from openframe.features.model.presentation.analysis_case import CaseStatus
from openframe.features.model.presentation.analysis_case_store import AnalysisCaseStore


def _store() -> AnalysisCaseStore:
    QApplication.instance() or QApplication([])
    return AnalysisCaseStore()


def test_add_case_becomes_active_when_it_is_the_first_one() -> None:
    store = _store()

    case_id = store.add_case(AnalysisKind.LINEAR_STATIC)

    assert store.active_case_id() == case_id
    assert store.case(case_id).kind == AnalysisKind.LINEAR_STATIC


def test_add_case_seeds_a_readable_default_name_and_does_not_collide() -> None:
    store = _store()

    first = store.add_case(AnalysisKind.NONLINEAR_STATIC)
    second = store.add_case(AnalysisKind.NONLINEAR_STATIC)

    assert store.case(first).name != store.case(second).name


def test_duplicate_case_copies_settings_but_gets_its_own_identity() -> None:
    store = _store()
    case_id = store.add_case(AnalysisKind.NONLINEAR_STATIC, "Pushover-X")
    store.case(case_id).settings["control_node"] = 5

    new_id = store.duplicate_case(case_id, "Pushover-Y")

    assert new_id != case_id
    assert store.case(new_id).kind == AnalysisKind.NONLINEAR_STATIC
    assert store.case(new_id).settings == {"control_node": 5}
    # Mutating the duplicate's settings must never reach back into the original.
    store.case(new_id).settings["control_node"] = 99
    assert store.case(case_id).settings["control_node"] == 5


def test_rename_case() -> None:
    store = _store()
    case_id = store.add_case(AnalysisKind.MODAL)

    assert store.rename_case(case_id, "Modal-20Modes") is True
    assert store.case(case_id).name == "Modal-20Modes"


def test_rename_rejects_empty_name_and_unknown_case() -> None:
    store = _store()
    case_id = store.add_case(AnalysisKind.MODAL)

    assert store.rename_case(case_id, "") is False
    assert store.rename_case("no-such-id", "X") is False


def test_delete_case_refuses_to_remove_the_last_one() -> None:
    store = _store()
    case_id = store.add_case(AnalysisKind.LINEAR_STATIC)

    assert store.delete_case(case_id) is False
    assert store.has_case(case_id)


def test_delete_case_falls_back_to_another_case_when_the_active_one_is_removed() -> None:
    store = _store()
    first = store.add_case(AnalysisKind.LINEAR_STATIC)
    second = store.add_case(AnalysisKind.MODAL)
    store.set_active_case(first)

    assert store.delete_case(first) is True
    assert not store.has_case(first)
    assert store.active_case_id() == second


def test_switching_active_case_never_touches_another_cases_settings() -> None:
    """The isolation guarantee the whole refactor exists for: editing case A
    then switching to case B and back must leave A exactly as it was."""
    store = _store()
    case_a = store.add_case(AnalysisKind.NONLINEAR_STATIC, "Pushover-X")
    case_b = store.add_case(AnalysisKind.MODAL, "Modal-1")
    store.case(case_a).settings["control_node"] = 7

    store.set_active_case(case_b)
    store.case(case_b).settings["num_modes"] = 20
    store.set_active_case(case_a)

    assert store.case(case_a).settings == {"control_node": 7}
    assert store.case(case_b).settings == {"num_modes": 20}


def test_set_active_case_emits_signal_only_on_real_change() -> None:
    store = _store()
    case_a = store.add_case(AnalysisKind.LINEAR_STATIC)
    case_b = store.add_case(AnalysisKind.MODAL)
    events: list[str] = []
    store.active_case_changed.connect(events.append)

    store.set_active_case(case_a)  # already active - no-op
    assert events == []

    store.set_active_case(case_b)
    assert events == [case_b]


def test_set_status_and_to_dict_round_trip() -> None:
    store = _store()
    case_id = store.add_case(AnalysisKind.LINEAR_STATIC, "LS-1")
    store.case(case_id).settings["load_factor"] = 1.5
    store.set_status(case_id, CaseStatus.RUNNABLE)

    data = store.to_dict()
    restored = AnalysisCaseStore.from_dict(data)

    restored_case = restored.case(case_id)
    assert restored_case.name == "LS-1"
    assert restored_case.kind == AnalysisKind.LINEAR_STATIC
    assert restored_case.status == CaseStatus.RUNNABLE
    assert restored_case.settings == {"load_factor": 1.5}
    assert restored.active_case_id() == case_id


def test_from_dict_on_empty_data_still_produces_a_usable_store() -> None:
    """A project saved before this feature existed has no "analysis_cases"
    key at all - loading an empty dict must not crash, and the store must
    still satisfy "always at least one case exists" once the caller seeds a
    default (this function itself does not invent one - that is the
    sidebar's job, matching the plan's "creates one default case" note)."""
    restored = AnalysisCaseStore.from_dict({})

    assert restored.list_cases() == ()
    assert restored.active_case_id() is None
