"""Pure dataclass shape/default checks for the Loads tab's new domain types
(``core.domain.load_case``, ``core.domain.load_entry``) - no canvas, no Qt.
"""

from openframe.core.domain import (
    FloorLoadEntry,
    LoadCase,
    LoadCaseKind,
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoadEntry,
    SelfWeightEntry,
)


def test_load_case_defaults_to_unclassified_with_empty_description() -> None:
    case = LoadCase(id="LL_OFFICE", name="LL_OFFICE")
    assert case.kind is LoadCaseKind.UNCLASSIFIED
    assert case.description == ""


def test_load_case_kind_accepts_the_newly_added_roof_live_and_snow() -> None:
    assert LoadCase(id="RL", name="RL", kind=LoadCaseKind.ROOF_LIVE).kind is LoadCaseKind.ROOF_LIVE
    assert LoadCase(id="SL", name="SL", kind=LoadCaseKind.SNOW).kind is LoadCaseKind.SNOW


def test_member_distributed_load_entry_defaults_span_the_full_member() -> None:
    """A plain uniform load, expressed in this shared shape, is the default:
    zero magnitude and a full 0..1 span - the left panel locks start/end
    position for the Uniform/Linear sub-types rather than this dataclass
    enforcing it, but the default must still read as "full span"."""
    entry = MemberDistributedLoadEntry()
    assert entry.start_position == 0.0
    assert entry.end_position == 1.0
    assert entry.start_value == entry.end_value == 0.0


def test_member_point_load_entry_defaults_to_midspan_ratio() -> None:
    entry = MemberPointLoadEntry()
    assert entry.position == 0.5
    assert entry.position_unit == "ratio"


def test_self_weight_entry_defaults_to_downward_z_and_applies_to_all() -> None:
    entry = SelfWeightEntry()
    assert entry.apply_to_all is True
    assert entry.target_elements == ()
    assert entry.factor_z == -1.0
    assert entry.factor_x == entry.factor_y == 0.0


def test_load_entry_wraps_a_nodal_payload_with_its_own_id_and_case() -> None:
    entry = LoadEntry(
        id=1,
        case_id="LL_OFFICE",
        kind="nodal",
        target=(5,),
        payload=NodalLoadEntry(fz=-10.0),
    )
    assert entry.id == 1
    assert entry.case_id == "LL_OFFICE"
    assert entry.target == (5,)
    assert entry.hidden is False
    assert isinstance(entry.payload, NodalLoadEntry)
    assert entry.payload.fz == -10.0


def test_floor_load_entry_target_nodes_form_the_boundary_loop() -> None:
    entry = FloorLoadEntry(magnitude=5.0, target_nodes=(1, 2, 3, 4))
    assert entry.target_nodes == (1, 2, 3, 4)
    assert entry.distribution == "one_way"
