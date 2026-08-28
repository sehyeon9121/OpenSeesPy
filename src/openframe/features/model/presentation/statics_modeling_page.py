"""Free-form 2D editor for textbook statics problems.

``StaticsDrawingCanvas`` itself is deliberately thin: signals, constants and
``__init__`` only. Its actual behaviour lives in the mixins below, split by
concern (work planes, drawing mode, selection, property application,
transforms, geometry CRUD, model building, serialization, undo history, Qt
input events, scene rendering) - see ``canvas_work_planes.py`` for why a
mixin split rather than one ~2000-line class.
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    FloorLoadType,
    LoadCase,
    LoadCombination,
    LoadEntry,
    NodalLoad,
    Node,
    Story,
    UniformElementLoad,
)
from openframe.features.model.drawing import SnapOptions, WorkPlane
from openframe.features.model.presentation.canvas_drawing_mode import _DrawingModeMixin
from openframe.features.model.presentation.canvas_geometry import _GeometryMixin
from openframe.features.model.presentation.canvas_history import _HistoryMixin
from openframe.features.model.presentation.canvas_input_events import _InputEventsMixin
from openframe.features.model.presentation.canvas_load_entries import _LoadEntryMixin
from openframe.features.model.presentation.canvas_model_build import _ModelBuildMixin
from openframe.features.model.presentation.canvas_property_application import (
    _PropertyApplicationMixin,
)
from openframe.features.model.presentation.canvas_rendering import _RenderingMixin
from openframe.features.model.presentation.canvas_selection import _SelectionMixin
from openframe.features.model.presentation.canvas_serialization import _SerializationMixin
from openframe.features.model.presentation.canvas_stories import _StoryMixin
from openframe.features.model.presentation.canvas_transforms import _TransformMixin
from openframe.features.model.presentation.canvas_units import _UnitConversionMixin
from openframe.features.model.presentation.canvas_work_planes import _WorkPlaneMixin


class StaticsDrawingCanvas(
    # _InputEventsMixin overrides QGraphicsView virtuals (mousePressEvent,
    # wheelEvent, drawBackground, ...) - it and every other mixin must come
    # BEFORE QGraphicsView in this list, or Python's MRO finds QGraphicsView's
    # own (do-nothing-special) version first and silently shadows ours, since
    # the first base class in the list wins when both define the same name.
    _WorkPlaneMixin,
    _DrawingModeMixin,
    _SelectionMixin,
    _PropertyApplicationMixin,
    _TransformMixin,
    _GeometryMixin,
    _ModelBuildMixin,
    _SerializationMixin,
    _HistoryMixin,
    _InputEventsMixin,
    _RenderingMixin,
    _LoadEntryMixin,
    _StoryMixin,
    _UnitConversionMixin,
    QGraphicsView,
):
    model_changed = Signal()
    draw_state_changed = Signal()
    selection_changed = Signal()
    escape_requested = Signal()
    #: Fired by every ``_LoadEntryMixin`` CRUD method - separate from
    #: ``model_changed`` (geometry/material) so the 3D Loads tab's own
    #: refresh (Work Tree load groups, viewport load glyphs) never re-runs
    #: whatever the much more common geometry-changed listeners do, and
    #: vice versa.
    load_state_changed = Signal()
    #: Fired by every ``_StoryMixin`` CRUD method - Story Manager's own
    #: refresh, kept separate from ``load_state_changed`` for the same
    #: reason that one is separate from ``model_changed``.
    story_state_changed = Signal()
    _DRAW_SCALE = 40.0
    _SNAP_PIXELS = 14.0

    def __init__(self, parent: QWidget | None = None) -> None:
        self.scene_model = QGraphicsScene()
        super().__init__(self.scene_model, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSceneRect(-100_000, -100_000, 200_000, 200_000)
        self.nodes: dict[int, Node] = {}
        self.elements: dict[int, Element] = {}
        self.boundaries: dict[int, BoundaryCondition] = {}
        self.nodal_loads: dict[int, NodalLoad] = {}
        self.element_loads: dict[int, UniformElementLoad] = {}
        self.embedded_nodes: dict[int, tuple[int, float]] = {}
        # 3D Loads tab state (see canvas_load_entries.py) - entirely separate
        # from nodal_loads/element_loads above, which 2D and every real
        # solve path still own unchanged.
        self.load_cases: dict[str, LoadCase] = {}
        self.active_load_case_id: str | None = None
        self.load_entries: dict[int, LoadEntry] = {}
        self._next_load_entry_id = 1
        self.load_combinations: dict[str, LoadCombination] = {}
        self.active_combination_id: str | None = None
        #: Named (case, magnitude) row bundles applied to a floor boundary
        #: all at once - see FloorLoadType's own docstring.
        self.floor_load_types: dict[str, FloorLoadType] = {}
        #: Story Manager (see canvas_stories.py) - building floor levels,
        #: each optionally tied together as a rigid diaphragm at analysis
        #: time (canvas_model_build.py).
        self.stories: dict[str, Story] = {}
        #: "case" | "combination" | "all" | "hidden" - what the Loads tab's
        #: Display dropdown currently shows in the 3D viewport/Work Tree.
        self.load_display_mode = "case"
        self.mode = "select"
        # "frame" members carry moment/shear/axial; "truss" members are pinned at
        # both ends and carry axial force only. This governs every member drawn
        # from now on, not the members already on the canvas — matching how a
        # real truss/frame is a whole-model choice, not a per-click one.
        self.element_family = "frame"
        #: Finer-grained structural intent behind element_family's collapsed
        #: "frame"/"truss" - one of _ELEMENT_TYPE_OPTIONS's own values
        #: (general_beam/truss/tension_only/compression_only/cable), stamped
        #: onto each newly drawn member's properties["behavior"] (see
        #: add_member) so the 3D viewport can color-code by structural type
        #: instead of by whichever section happens to be assigned.
        self.element_behavior = "general_beam"
        self.selection_filter = "all"
        self.grid = 1.0
        self._member_start: int | None = None
        self._selected: tuple[str, int] | None = None
        self.selected_nodes: set[int] = set()
        self.selected_elements: set[int] = set()
        self.hinge_nodes: set[int] = set()
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._preview_point: QPointF | None = None
        self._preview_midpoint: tuple[int, QPointF, float] | None = None
        self._panning = False
        self._pan_start = QPointF()
        self.support_restraints = (True, True, False)
        self.support_angle = 0.0
        self.pending_nodal_load = (0.0, -10.0, 0.0)
        self.pending_uniform_load = (0.0, -10.0)
        # Not-yet-committed load values (from the load bar's fields) shown as
        # a dashed preview arrow while the user is still typing/dragging
        # magnitude+angle, before 적용 is clicked — see
        # ``set_pending_load_preview``.
        self._pending_load_preview: tuple[frozenset[int], tuple[float, ...]] | None = None
        # Off by default: a determinate textbook problem almost never wants its
        # own member weight mixed into a hand-picked point load, and turning it
        # on requires each member to also carry a density (see _self_weight_local).
        self.include_self_weight = False
        # On by default - a hand-drawn frame is usually meant to land on clean
        # coordinates, so every grid line crossing already acts like a node the
        # cursor snaps to without one having to exist yet. Toggled off when the
        # user wants a click to land exactly where the cursor is instead.
        self.grid_snap_enabled = True
        self.snap_options = SnapOptions()
        self.ortho = False
        self.ortho_increment = 45.0
        self._chain: list[int] = []
        #: Node tags accumulated, in click order, while ``mode == "floor_pick"``
        #: (see canvas_load_entries.py's floor-picking methods) - a separate
        #: accumulator from ``_chain`` since a floor boundary is a closed
        #: polygon of already-existing nodes, not a member-drawing path.
        self._floor_chain: list[int] = []
        self._snap = None
        self._undo_stack: list[dict[str, object]] = []
        self._redo_stack: list[dict[str, object]] = []
        self._history_group_depth = 0
        self._history_group_snapshot: dict[str, object] | None = None
        #: Set by _changed() while a history group is open, so end_history_
        #: group() can fire exactly one model_changed at the very end instead
        #: of once per node/member created mid-operation - see _changed()'s
        #: own docstring for why firing on every intermediate step is wrong.
        self._pending_change_notification = False
        # A plain 2D canvas is a 3D one whose only plane is the ground (identity
        # XY at 0): every coordinate a node ever gets is (u, v, 0), which is
        # exactly what this class always produced before it knew about planes.
        self.ndm = 2
        self.work_plane = WorkPlane()
        self.levels: list[WorkPlane] = [self.work_plane]
