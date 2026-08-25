"""Individually-addressable, multi-per-target loads for the 3D Loads tab.

Deliberately separate from ``core.domain.model``'s ``NodalLoad``/
``UniformElementLoad`` - those two are solver-facing (``MaterialFreeStaticsSolver``
reads them directly, and both the 2D and 3D free-form canvases already store
exactly one of each per node/element tag, overwriting on re-apply). This
module's ``LoadEntry`` is a UI/state-only concept with its own integer id,
letting many loads (from different load cases, or the same case) coexist on
the same target - which is what a real Load Tree needs - without touching
anything the solver or the 2D canvas already depends on. Nothing here is
wired into ``StructuralModel``/``canvas_model_build.py`` yet; see the Loads
tab UI overhaul's own notes for what remains unconnected.
"""

from dataclasses import dataclass, field
from typing import Literal

#: What a ``LoadEntry`` actually is - drives which payload dataclass it
#: carries and which target kind (node tags vs element tags vs a floor
#: boundary) applies. ``member_point``/``member_moment`` and
#: ``member_uniform``/``member_linear``/``member_partial`` deliberately share
#: one payload shape each (``MemberPointLoadEntry``/
#: ``MemberDistributedLoadEntry``) - the difference between them is only
#: which fields the left panel shows/labels, not the data shape.
LoadEntryKind = Literal[
    "nodal",
    "member_point",
    "member_moment",
    "member_uniform",
    "member_linear",
    "member_partial",
    "floor",
    "self_weight",
]

CoordinateSystem = Literal["global", "local"]
PositionUnit = Literal["ratio", "length"]
FloorDistribution = Literal["one_way", "two_way"]


@dataclass(frozen=True, slots=True)
class NodalLoadEntry:
    coordinate_system: CoordinateSystem = "global"
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
    mx: float = 0.0
    my: float = 0.0
    mz: float = 0.0


@dataclass(frozen=True, slots=True)
class MemberPointLoadEntry:
    """A member load applied at a single station - a concentrated force
    (``kind="member_point"``) or a concentrated moment
    (``kind="member_moment"``) about ``direction``. Shared shape: only the
    left panel's field labels/visibility differ between the two kinds."""

    coordinate_system: CoordinateSystem = "local"
    direction: str = "y"
    value: float = 0.0
    position: float = 0.5
    position_unit: PositionUnit = "ratio"


@dataclass(frozen=True, slots=True)
class MemberDistributedLoadEntry:
    """Uniform (``start_value == end_value``, full span), linearly-varying
    (``start_value != end_value``, full span), or partial-span
    (``start_position``/``end_position`` inside the member) distributed
    load - one shape covers all three; the left panel just locks
    start/end position to (0, 1) for the first two."""

    coordinate_system: CoordinateSystem = "local"
    direction: str = "y"
    start_value: float = 0.0
    end_value: float = 0.0
    start_position: float = 0.0
    end_position: float = 1.0
    position_unit: PositionUnit = "ratio"


@dataclass(frozen=True, slots=True)
class FloorLoadEntry:
    """UI-only for now - no beam-load distribution is computed (see this
    module's own docstring). ``target_nodes`` is the closed boundary loop a
    student picked, in order, around the floor panel."""

    magnitude: float = 0.0
    direction: str = "-z"
    distribution: FloorDistribution = "one_way"
    span_direction: str = "x"
    target_nodes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SelfWeightEntry:
    factor_x: float = 0.0
    factor_y: float = 0.0
    factor_z: float = -1.0
    apply_to_all: bool = True
    target_elements: tuple[int, ...] = ()


LoadEntryPayload = (
    NodalLoadEntry | MemberPointLoadEntry | MemberDistributedLoadEntry | FloorLoadEntry | SelfWeightEntry
)


@dataclass(frozen=True, slots=True)
class LoadEntry:
    """One row in the Load Tree - ``id`` is this store's own key (see
    ``canvas_load_entries.py``), never a node/element tag, which is exactly
    what lets several of these coexist on the same target.

    ``target`` is a tuple of node tags (``kind="nodal"``), a single element
    tag wrapped in a 1-tuple (every member-load kind), or the floor
    boundary's node tags (``kind="floor"``) - empty for ``self_weight`` when
    ``SelfWeightEntry.apply_to_all`` is set.
    """

    id: int
    case_id: str
    kind: LoadEntryKind
    target: tuple[int, ...]
    payload: LoadEntryPayload
    hidden: bool = False
