"""Save/reload round trip for the 3D Loads tab's new state (load_cases/
load_entries/load_combinations) through StaticsDrawingCanvas.to_dict()/
load_dict() - and backward compatibility with a project file saved before
this feature existed (no such keys at all)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import LoadCaseKind, MemberDistributedLoadEntry, NodalLoadEntry
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_load_cases_entries_and_combinations_round_trip_through_to_dict() -> None:
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(a, b)
    canvas.add_load_case("DL_SELF", kind=LoadCaseKind.DEAD, description="Self weight")
    nodal_id = canvas.add_load_entry("DL_SELF", "nodal", (node,), NodalLoadEntry(fz=-5.0))
    canvas.add_load_entry(
        "DL_SELF",
        "member_uniform",
        (member,),
        MemberDistributedLoadEntry(direction="y", start_value=-2.0, end_value=-2.0),
    )
    canvas.add_load_combination("ULS-01")
    canvas.update_load_combination("ULS-01", {LoadCaseKind.DEAD: 1.2})

    data = canvas.to_dict()

    fresh = _canvas()
    fresh.load_dict(data)

    assert fresh.load_cases.keys() == {"DL_SELF"}
    assert fresh.load_cases["DL_SELF"].kind is LoadCaseKind.DEAD
    assert fresh.load_cases["DL_SELF"].description == "Self weight"
    assert len(fresh.load_entries) == 2
    assert fresh.load_entries[nodal_id].payload.fz == -5.0
    assert fresh.load_combinations["ULS-01"].factor_for(LoadCaseKind.DEAD) == 1.2
    # A new entry after reload must not collide with a restored id.
    next_id = fresh.add_load_entry("DL_SELF", "nodal", (node,), NodalLoadEntry(fz=-1.0))
    assert next_id not in (nodal_id,)


def test_load_dict_defaults_load_state_to_empty_for_a_pre_feature_project_file() -> None:
    canvas = _canvas()
    canvas.add_node(0.0, 0.0)
    legacy_data = canvas.to_dict()
    for key in ("load_cases", "active_load_case_id", "load_entries", "load_combinations", "active_combination_id"):
        legacy_data.pop(key, None)

    fresh = _canvas()
    fresh.load_dict(legacy_data)

    assert fresh.load_cases == {}
    assert fresh.load_entries == {}
    assert fresh.load_combinations == {}
    assert fresh.active_load_case_id is None


def test_floor_load_types_round_trip_through_to_dict() -> None:
    from openframe.core.domain import FloorLoadTypeRow

    canvas = _canvas()
    canvas.add_load_case("DL_CONCRETE", kind=LoadCaseKind.DEAD)
    canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)
    canvas.add_floor_load_type(
        "사무실 바닥",
        description="콘크리트+활하중",
        rows=(
            FloorLoadTypeRow(case_id="DL_CONCRETE", magnitude=2.0),
            FloorLoadTypeRow(case_id="LL_OFFICE", magnitude=2.5),
        ),
    )

    data = canvas.to_dict()
    fresh = _canvas()
    fresh.load_dict(data)

    floor_type = fresh.floor_load_types["사무실 바닥"]
    assert floor_type.description == "콘크리트+활하중"
    assert floor_type.rows[0].case_id == "DL_CONCRETE"
    assert floor_type.rows[0].magnitude == 2.0
    assert floor_type.rows[1].magnitude == 2.5


def test_load_dict_defaults_floor_load_types_to_empty_for_a_pre_feature_project_file() -> None:
    canvas = _canvas()
    canvas.add_node(0.0, 0.0)
    legacy_data = canvas.to_dict()
    legacy_data.pop("floor_load_types", None)

    fresh = _canvas()
    fresh.load_dict(legacy_data)

    assert fresh.floor_load_types == {}
