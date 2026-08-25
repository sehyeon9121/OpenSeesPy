"""Read-only Inspector: what is *actually stored* on the current canvas
selection, as opposed to whatever ``SectionMaterialPanel`` is mid-edit above
it. This widget never edits anything and never talks to ``SectionMaterialPanel``
directly - ``ModelingInterfacePage`` (the only thing that touches both) reads
``SectionMaterialPanel.current_edit_kwargs()`` and hands the plain result to
``refresh()`` here, so the two widgets never reach into each other's internal
state.

Two distinct update paths, matching the "상단 = 편집 중인 값, 하단 = 실제
저장된 값" requirement this was built for:

- ``refresh()`` - a full re-render from the model itself (``StaticsDrawingCanvas``).
  Every value shown comes from here, never from a live-typed field. Called on
  selection change, apply, undo/redo, and project load - never on keystroke.
- ``update_pending_status()`` - re-evaluates *only* the Applied/Pending Changes
  badge already on screen, comparing the just-typed (not yet applied) editor
  state against the *same* stored element(s) ``refresh()`` last rendered.
  Connected to ``SectionMaterialPanel.edited`` (fired on every real keystroke,
  never during a member (re)load - see that signal's docstring), so the badge
  reacts live while every other displayed number stays exactly what is really
  stored, per the "타이핑만으로는 실제 적용값이 갱신되지 않아야 한다" rule.

Deliberately does *not* draw a section shape - the existing preview stays
inside ``SectionMaterialPanel`` (top), not duplicated down here.
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    BoundaryCondition,
    Element,
    LoadCase,
    LoadEntry,
    NodalLoad,
    Node,
    SectionDimensionError,
    UnitSystem,
    dimension_fields,
)

#: Korean display label per LoadEntry.kind, for the "Load Type" row.
_LOAD_ENTRY_KIND_LABELS: dict[str, str] = {
    "nodal": "절점하중",
    "member_point": "부재 집중하중",
    "member_moment": "부재 집중모멘트",
    "member_uniform": "부재 균등분포하중",
    "member_linear": "부재 선형변화하중",
    "member_partial": "부재 부분분포하중",
    "floor": "바닥하중",
    "self_weight": "자중",
}
from openframe.features.model.presentation.model_inspector_panel import SUPPORT_LABELS
from openframe.features.model.presentation.section_material_panel import _load_database_safely


@dataclass(frozen=True, slots=True)
class _SectionSnapshot:
    """Everything about a member's section+material worth showing, read
    straight out of ``Element.properties`` (see module list in
    ``section_material_panel.py``'s ``apply_full_section_to_selection``) -
    never recomputed, never guessed for a key that is not there."""

    shape: str
    source: str  # "database" | "custom" | "" (nothing applied yet)
    section_id: str | None
    designation: str | None
    dims: dict[str, float]
    area: float | None
    iy: float | None
    iz: float | None
    j: float | None
    elastic: float | None
    density: float | None
    material_id: str | None
    material_category: str | None
    material_grade: str | None


class SelectionStatusPanel(QWidget):
    """Content only - the caller wraps this in its own ``QScrollArea`` (see
    ``ModelingInterfacePage``'s splitter), matching how ``SectionMaterialPanel``
    is wrapped externally rather than scrolling itself."""

    #: This widget "never edits anything" (see module docstring) - a Load
    #: entry's [수정]/[대상 다시 선택]/[삭제] buttons emit these instead of
    #: calling canvas mutators directly; ``ModelingInterfacePage`` (which
    #: already owns both the canvas and this panel) connects them.
    load_edit_requested = Signal(int)
    load_reselect_requested = Signal(int)
    load_delete_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("selectionStatusPanel")
        self._unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM
        self._database = _load_database_safely()
        # The element(s) the *currently shown* STATUS badge(s) refer to -
        # kept only so ``update_pending_status`` can re-evaluate Applied/
        # Pending live without re-reading the whole model or touching any
        # other displayed value.
        self._status_elements: list[Element] = []
        self._status_badges: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        title = QLabel("SELECTION STATUS")
        title.setObjectName("direct2DInspectorTitle")
        root.addWidget(title)

        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        root.addWidget(self._cards_host)
        root.addStretch(1)

        self._show_empty()

    # -- public API -----------------------------------------------------
    def refresh(
        self,
        canvas,
        *,
        pending_edit: dict[str, object] | None,
        unit_system: UnitSystem,
    ) -> None:
        """Full re-render from ``canvas`` (a ``StaticsDrawingCanvas``) - the
        single source every displayed value comes from. ``pending_edit`` is
        ``SectionMaterialPanel.current_edit_kwargs()``, used only to compute
        the Applied/Pending Changes badge for a member selection; ``None``
        wherever it does not apply (no member selected)."""
        self._unit_system = unit_system
        self._status_elements = []
        self._status_badges = []
        self._clear_cards()

        nodes = set(canvas.selected_nodes)
        elements = set(canvas.selected_elements)
        if not nodes and not elements:
            self._show_empty()
        elif nodes and elements:
            self._show_mixed_summary(len(nodes), len(elements))
        elif elements:
            if len(elements) == 1:
                self._show_single_member(canvas, next(iter(elements)), pending_edit)
            else:
                self._show_multiple_members(canvas, elements, pending_edit)
        elif len(nodes) == 1:
            self._show_single_node(canvas, next(iter(nodes)))
        else:
            self._show_multiple_nodes(canvas, nodes)

    def update_pending_status(self, pending_edit: dict[str, object] | None) -> None:
        """Re-evaluate only the Applied/Pending Changes badge(s) already on
        screen against the element(s) the last ``refresh()`` rendered -
        never touches any other displayed value, so a bare keystroke in
        ``SectionMaterialPanel`` above cannot change what this shows as
        "실제 저장된 값", only whether it currently matches."""
        if not self._status_badges or not self._status_elements:
            return
        applied = all(self._is_applied(element, pending_edit) for element in self._status_elements)
        state, text = ("applied", "Applied") if applied else ("pending", "Pending Changes")
        for badge in self._status_badges:
            badge.setText(text)
            badge.setProperty("state", state)
            badge.style().unpolish(badge)
            badge.style().polish(badge)

    def show_load_entry(
        self,
        entry: LoadEntry,
        case: LoadCase | None,
        display_id: str,
        unit_system: UnitSystem,
    ) -> None:
        """Switch to the Load properties view - called directly by the page
        (Work Tree row click / viewport glyph pick), bypassing ``refresh()``'s
        node/element dispatch entirely, since a "selected load" is not part
        of ``canvas.selected_nodes``/``selected_elements`` at all (see
        ``canvas_load_entries.py``'s own module docstring for why loads are
        their own id-keyed store)."""
        self._unit_system = unit_system
        self._status_elements = []
        self._status_badges = []
        self._clear_cards()

        _, layout = self._card("SELECTED LOAD")
        form = self._form_in(layout)
        form.addRow("ID", self._value_label(display_id))
        form.addRow("Load Case", self._value_label(case.name if case is not None else "—"))
        form.addRow("Load Type", self._value_label(_LOAD_ENTRY_KIND_LABELS.get(entry.kind, entry.kind)))
        form.addRow("Target", self._value_label(self._load_entry_target_summary(entry)))
        form.addRow(
            "Coordinate System",
            self._value_label(str(getattr(entry.payload, "coordinate_system", "—")).upper()),
        )
        form.addRow("Direction", self._value_label(self._load_entry_direction_summary(entry)))
        form.addRow("Magnitude", self._value_label(self._load_entry_magnitude_summary(entry)))
        form.addRow("Range", self._value_label(self._load_entry_range_summary(entry)))
        form.addRow("Display Status", self._value_label("숨김" if entry.hidden else "표시"))

        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        edit_button = QPushButton("수정")
        edit_button.clicked.connect(lambda: self.load_edit_requested.emit(entry.id))
        button_layout.addWidget(edit_button)
        reselect_button = QPushButton("대상 다시 선택")
        reselect_button.clicked.connect(lambda: self.load_reselect_requested.emit(entry.id))
        button_layout.addWidget(reselect_button)
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(lambda: self.load_delete_requested.emit(entry.id))
        button_layout.addWidget(delete_button)
        button_layout.addStretch(1)
        layout.addWidget(button_row)

    # -- load entry summaries ---------------------------------------------
    @staticmethod
    def _load_entry_target_summary(entry: LoadEntry) -> str:
        if entry.kind == "nodal":
            return ", ".join(f"N{tag}" for tag in entry.target) or "—"
        if entry.kind == "floor":
            return f"경계 노드 {len(entry.target)}개" if entry.target else "—"
        if entry.kind == "self_weight":
            if entry.payload.apply_to_all:
                return "전체 부재"
            return ", ".join(f"M{tag}" for tag in entry.target) or "—"
        return ", ".join(f"M{tag}" for tag in entry.target) or "—"

    @staticmethod
    def _load_entry_direction_summary(entry: LoadEntry) -> str:
        payload = entry.payload
        if hasattr(payload, "direction"):
            return str(payload.direction).upper()
        if entry.kind == "nodal":
            names = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")
            values = (payload.fx, payload.fy, payload.fz, payload.mx, payload.my, payload.mz)
            active = [name for name, value in zip(names, values, strict=True) if value != 0.0]
            return ", ".join(active) if active else "—"
        return "—"

    def _load_entry_magnitude_summary(self, entry: LoadEntry) -> str:
        payload = entry.payload
        unit = self._unit_system
        if entry.kind == "nodal":
            names = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")
            values = (payload.fx, payload.fy, payload.fz, payload.mx, payload.my, payload.mz)
            parts = [
                f"{name} {value:g} {unit.moment if name[0] == 'M' else unit.force}"
                for name, value in zip(names, values, strict=True)
                if value != 0.0
            ]
            return ", ".join(parts) if parts else "0"
        if entry.kind in ("member_point", "member_moment"):
            component_unit = unit.moment if entry.kind == "member_moment" else unit.force
            return f"{payload.value:g} {component_unit}"
        if entry.kind in ("member_uniform", "member_linear", "member_partial"):
            distributed_unit = f"{unit.force}/{unit.length}"
            if payload.start_value == payload.end_value:
                return f"{payload.start_value:g} {distributed_unit}"
            return f"{payload.start_value:g} → {payload.end_value:g} {distributed_unit}"
        if entry.kind == "floor":
            return f"{payload.magnitude:g} {unit.force}/{unit.length}²"
        if entry.kind == "self_weight":
            return f"x {payload.factor_x:g}, y {payload.factor_y:g}, z {payload.factor_z:g}"
        return "—"

    def _load_entry_range_summary(self, entry: LoadEntry) -> str:
        payload = entry.payload
        if entry.kind in ("member_point", "member_moment"):
            unit = "" if payload.position_unit == "ratio" else f" {self._unit_system.length}"
            return f"{payload.position:g}{unit}"
        if entry.kind in ("member_uniform", "member_linear", "member_partial"):
            unit = "" if payload.position_unit == "ratio" else f" {self._unit_system.length}"
            return f"{payload.start_position:g}{unit} ~ {payload.end_position:g}{unit}"
        return "—"

    # -- card/row builders ------------------------------------------------
    def _clear_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("propertySectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("setupSectionTitle")
        layout.addWidget(label)
        self._cards_layout.addWidget(card)
        return card, layout

    @staticmethod
    def _form_in(layout: QVBoxLayout) -> QFormLayout:
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addLayout(form)
        return form

    @staticmethod
    def _value_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _badge_row(state: str, text: str) -> tuple[QWidget, QLabel]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        badge = QLabel(text)
        badge.setObjectName("selectionStatusBadge")
        badge.setProperty("state", state)
        layout.addWidget(badge)
        layout.addStretch(1)
        return row, badge

    @staticmethod
    def _format_or_dash(value: float | None, unit: str) -> str:
        return "—" if value is None else f"{value:.6g} {unit}"

    # -- empty / mixed ------------------------------------------------------
    def _show_empty(self) -> None:
        label = QLabel(
            "선택된 대상이 없습니다.\n"
            "캔버스에서 노드 또는 부재를 선택하면\n"
            "현재 적용된 설정을 확인할 수 있습니다."
        )
        label.setObjectName("setupSectionHint")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        self._cards_layout.addWidget(label)

    def _show_mixed_summary(self, node_count: int, element_count: int) -> None:
        label = QLabel(
            f"노드 {node_count}개 · 부재 {element_count}개가 함께 선택되었습니다.\n"
            "노드나 부재만 선택하면 상세 정보를 확인할 수 있습니다."
        )
        label.setObjectName("setupSectionHint")
        label.setWordWrap(True)
        self._cards_layout.addWidget(label)

    # -- node -----------------------------------------------------------
    @staticmethod
    def _dof_names(ndm: int) -> tuple[str, ...]:
        return ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz") if ndm == 3 else ("Ux", "Uy", "Rz")

    @staticmethod
    def _support_summary(boundary: BoundaryCondition | None) -> str:
        return SUPPORT_LABELS[boundary.support_kind] if boundary is not None else "Free"

    def _load_component_names(self, ndm: int) -> tuple[str, ...]:
        return ("Fx", "Fy", "Fz", "Mx", "My", "Mz") if ndm == 3 else ("Fx", "Fy", "Mz")

    def _load_summary(self, load: NodalLoad | None, ndm: int) -> str:
        if load is None:
            return "—"
        unit = self._unit_system
        names = self._load_component_names(ndm)
        parts = [
            f"{name} {value:g} {unit.moment if name[0] == 'M' else unit.force}"
            for name, value in zip(names, load.values, strict=False)
            if value != 0.0
        ]
        return ", ".join(parts) if parts else "0"

    def _load_direction(self, load: NodalLoad, ndm: int) -> str:
        names = self._load_component_names(ndm)
        active = [name for name, value in zip(names, load.values, strict=False) if value != 0.0]
        return ", ".join(active) if active else "—"

    def _show_single_node(self, canvas, tag: int) -> None:
        node: Node | None = canvas.nodes.get(tag)
        if node is None:
            return
        unit = self._unit_system
        boundary = canvas.boundaries.get(tag)
        load = canvas.nodal_loads.get(tag)
        connected = sorted(
            element.tag
            for element in canvas.elements.values()
            if tag in (element.node_i, element.node_j)
        )

        _, layout = self._card("SELECTED NODE")
        form = self._form_in(layout)
        form.addRow("Node ID", self._value_label(f"N{tag}"))
        form.addRow("Coordinate X", self._value_label(f"{node.x:g} {unit.length}"))
        form.addRow("Coordinate Y", self._value_label(f"{node.y:g} {unit.length}"))
        if canvas.ndm == 3:
            form.addRow("Coordinate Z", self._value_label(f"{node.z:g} {unit.length}"))
        form.addRow(
            "Connected Members",
            self._value_label(", ".join(f"M{t}" for t in connected) if connected else "없음"),
        )
        form.addRow("Boundary Condition", self._value_label(self._support_summary(boundary)))
        form.addRow("Applied Nodal Load", self._value_label(self._load_summary(load, canvas.ndm)))

        if boundary is not None:
            _, support_layout = self._card("SUPPORT")
            support_form = self._form_in(support_layout)
            dof_names = self._dof_names(canvas.ndm)
            restraints = boundary.restraints
            restrained = [name for name, value in zip(dof_names, restraints, strict=False) if value]
            free = [name for name, value in zip(dof_names, restraints, strict=False) if not value]
            support_form.addRow("Restrained DOF", self._value_label(", ".join(restrained) or "—"))
            support_form.addRow("Free DOF", self._value_label(", ".join(free) or "—"))
            support_form.addRow("Support Type", self._value_label(self._support_summary(boundary)))

        if load is not None:
            _, load_layout = self._card("LOAD")
            load_form = self._form_in(load_layout)
            load_form.addRow("Load Type", self._value_label("Nodal Load"))
            load_form.addRow("Direction", self._value_label(self._load_direction(load, canvas.ndm)))
            load_form.addRow("Magnitude", self._value_label(self._load_summary(load, canvas.ndm)))
            load_form.addRow("Load Case", self._value_label(load.case_type.value))
            load_form.addRow(
                "Pattern", self._value_label(str(load.pattern_tag) if load.pattern_tag is not None else "—")
            )
            load_form.addRow("Target Node", self._value_label(f"N{tag}"))

    def _show_multiple_nodes(self, canvas, tags: set[int]) -> None:
        _, layout = self._card(f"{len(tags)} NODES SELECTED")
        form = self._form_in(layout)
        summaries = {self._support_summary(canvas.boundaries.get(tag)) for tag in tags}
        form.addRow(
            "Boundary Condition",
            self._value_label(next(iter(summaries)) if len(summaries) == 1 else "Mixed"),
        )
        form.addRow("Coordinate", self._value_label("—"))
        loaded = sorted(tag for tag in tags if tag in canvas.nodal_loads)
        form.addRow(
            "Applied Nodal Load",
            self._value_label(f"{len(loaded)}개 노드에 하중 있음" if loaded else "—"),
        )

    # -- member -----------------------------------------------------------
    def _designation_for(self, section_id: str | None) -> str | None:
        if not section_id or self._database is None:
            return None
        try:
            return self._database.get_section(section_id).designation
        except KeyError:
            return None

    def _section_snapshot(self, element: Element) -> _SectionSnapshot:
        props = element.properties
        shape = str(props.get("section_shape", "Rectangle"))
        raw_source = props.get("section_source")
        if raw_source is not None:
            source = str(raw_source)
        elif "A" in props:
            source = "custom"
        else:
            source = ""
        section_id = props.get("section_id")
        section_id = str(section_id) if section_id else None

        dims: dict[str, float] = {}
        for key, value in props.items():
            if isinstance(key, str) and key.startswith("dim_"):
                try:
                    dims[key[len("dim_") :]] = float(value)
                except (TypeError, ValueError):
                    pass
        if shape == "Rectangle" and not dims:
            width, height = props.get("width"), props.get("height")
            if width is not None:
                dims["b"] = float(width)
            if height is not None:
                dims["h"] = float(height)

        def _num(key: str) -> float | None:
            value = props.get(key)
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        def _text(key: str) -> str | None:
            value = props.get(key)
            return str(value) if value else None

        return _SectionSnapshot(
            shape=shape,
            source=source,
            section_id=section_id,
            designation=self._designation_for(section_id),
            dims=dims,
            area=_num("A"),
            iy=_num("I"),
            iz=_num("Iz"),
            j=_num("J"),
            elastic=_num("E"),
            density=_num("density"),
            material_id=_text("material_id"),
            material_category=_text("material_category"),
            material_grade=_text("material_grade"),
        )

    @staticmethod
    def _section_display_label(snapshot: _SectionSnapshot) -> str:
        if snapshot.designation:
            return snapshot.designation
        return snapshot.shape or "—"

    @staticmethod
    def _close(stored: object, edited: object) -> bool:
        if stored is None:
            return False
        try:
            return math.isclose(float(stored), float(edited), rel_tol=1.0e-9, abs_tol=1.0e-12)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    def _is_applied(self, element: Element, pending_edit: dict[str, object] | None) -> bool:
        """Compares against the *same* ``_SectionSnapshot`` the SECTION/
        MATERIAL cards render (not a second, separately-written read of
        ``element.properties``) so this can never silently disagree with
        what is actually on screen - e.g. a legacy element with no
        ``section_source``/``dim_*`` keys at all (just the old width/
        height/E/density quartet) resolves through the exact same
        Rectangle/"custom" fallback ``_section_snapshot`` already applies,
        instead of comparing a raw missing key against ``current_
        application_kwargs()``'s always-filled-in "custom" and reporting a
        false Pending Changes for a member nothing has actually edited."""
        if pending_edit is None:
            return False
        snapshot = self._section_snapshot(element)
        checks = [
            snapshot.shape == pending_edit["shape"],
            snapshot.source == pending_edit["source"],
            self._close(snapshot.area, pending_edit["area"]),
            self._close(snapshot.iy, pending_edit["iy"]),
            self._close(snapshot.iz, pending_edit["iz"]),
            self._close(snapshot.j, pending_edit["j"]),
            self._close(snapshot.elastic, pending_edit["elastic"]),
            self._close(snapshot.density, pending_edit["density"]),
            snapshot.section_id == pending_edit["section_id"],
            snapshot.material_id == pending_edit["material_id"],
            snapshot.material_category == pending_edit["material_category"],
            snapshot.material_grade == pending_edit["material_grade"],
        ]
        dimensions = pending_edit["dimensions"]
        assert isinstance(dimensions, dict)
        for key, value in dimensions.items():
            checks.append(self._close(snapshot.dims.get(key), value))
        return all(checks)

    @staticmethod
    def _sub_heading(form: QFormLayout, text: str) -> None:
        """A full-width divider label inside an existing form - groups
        related rows (dimensions, then computed properties) under one
        SECTION card instead of a separate bordered card per group, which
        is what previously turned one member's section info into three
        stacked cards for what is really one topic."""
        label = QLabel(text)
        label.setObjectName("setupSectionSubHeading")
        form.addRow(label)

    def _add_section_material_cards(self, snapshot: _SectionSnapshot, unit: UnitSystem) -> None:
        _, section_layout = self._card("SECTION")
        section_form = self._form_in(section_layout)
        section_form.addRow("Type", self._value_label(snapshot.shape or "—"))
        if snapshot.designation:
            section_form.addRow("Designation", self._value_label(snapshot.designation))
        if snapshot.source:
            source_row, _ = self._badge_row(
                "db" if snapshot.source == "database" else "custom",
                "DB" if snapshot.source == "database" else "CUSTOM",
            )
            section_form.addRow("Source", source_row)
        else:
            section_form.addRow("Source", self._value_label("—"))

        try:
            fields = dimension_fields(snapshot.shape) if snapshot.shape else ()
        except SectionDimensionError:
            fields = ()
        if fields:
            self._sub_heading(section_form, "GEOMETRY")
            for dim_field in fields:
                section_form.addRow(
                    dim_field.label,
                    self._value_label(self._format_or_dash(snapshot.dims.get(dim_field.key), unit.length)),
                )

        self._sub_heading(section_form, "PROPERTIES")
        section_form.addRow("A", self._value_label(self._format_or_dash(snapshot.area, f"{unit.length}²")))
        section_form.addRow("Iy", self._value_label(self._format_or_dash(snapshot.iy, f"{unit.length}⁴")))
        section_form.addRow("Iz", self._value_label(self._format_or_dash(snapshot.iz, f"{unit.length}⁴")))
        section_form.addRow("J", self._value_label(self._format_or_dash(snapshot.j, f"{unit.length}⁴")))

        _, material_layout = self._card("MATERIAL")
        material_form = self._form_in(material_layout)
        material_form.addRow("Category", self._value_label(snapshot.material_category or "—"))
        material_form.addRow("Grade", self._value_label(snapshot.material_grade or "—"))
        material_form.addRow("E", self._value_label(self._format_or_dash(snapshot.elastic, unit.stress)))
        material_form.addRow(
            "Unit Weight", self._value_label(self._format_or_dash(snapshot.density, unit.volumetric_force))
        )
        if snapshot.material_id:
            material_source_row, _ = self._badge_row("db", "DB")
            material_form.addRow("Material Source", material_source_row)
        elif snapshot.elastic is not None:
            material_source_row, _ = self._badge_row("custom", "CUSTOM")
            material_form.addRow("Material Source", material_source_row)
        else:
            material_form.addRow("Material Source", self._value_label("—"))

    def _show_single_member(self, canvas, tag: int, pending_edit: dict[str, object] | None) -> None:
        element = canvas.elements.get(tag)
        if element is None:
            return
        unit = self._unit_system
        node_i = canvas.nodes.get(element.node_i)
        node_j = canvas.nodes.get(element.node_j)

        _, layout = self._card("SELECTED MEMBER")
        form = self._form_in(layout)
        form.addRow("Member ID", self._value_label(f"M{tag}"))
        form.addRow("Nodes", self._value_label(f"N{element.node_i} → N{element.node_j}"))
        if node_i is not None and node_j is not None:
            length = math.dist((node_i.x, node_i.y, node_i.z), (node_j.x, node_j.y, node_j.z))
            form.addRow("Length", self._value_label(f"{length:.3f} {unit.length}"))

        applied = self._is_applied(element, pending_edit)
        state, text = ("applied", "Applied") if applied else ("pending", "Pending Changes")
        badge_row, badge = self._badge_row(state, text)
        form.addRow("Status", badge_row)

        snapshot = self._section_snapshot(element)
        self._add_section_material_cards(snapshot, unit)

        self._status_elements = [element]
        self._status_badges = [badge]

    def _show_multiple_members(self, canvas, tags: set[int], pending_edit: dict[str, object] | None) -> None:
        elements = [canvas.elements[t] for t in tags if t in canvas.elements]
        unit = self._unit_system
        snapshots = [self._section_snapshot(element) for element in elements]

        _, layout = self._card(f"{len(elements)} MEMBERS SELECTED")
        form = self._form_in(layout)

        section_labels = {self._section_display_label(s) for s in snapshots}
        form.addRow(
            "Section", self._value_label(next(iter(section_labels)) if len(section_labels) == 1 else "Mixed")
        )

        material_labels = {s.material_grade or "—" for s in snapshots}
        form.addRow(
            "Material", self._value_label(next(iter(material_labels)) if len(material_labels) == 1 else "Mixed")
        )

        elastic_values = {s.elastic for s in snapshots}
        form.addRow(
            "E",
            self._value_label(
                self._format_or_dash(next(iter(elastic_values)), unit.stress)
                if len(elastic_values) == 1
                else "Mixed"
            ),
        )

        density_values = {s.density for s in snapshots}
        form.addRow(
            "Unit Weight",
            self._value_label(
                self._format_or_dash(next(iter(density_values)), unit.volumetric_force)
                if len(density_values) == 1
                else "Mixed"
            ),
        )

        all_applied = all(self._is_applied(element, pending_edit) for element in elements)
        state, text = ("applied", "Applied") if all_applied else ("pending", "Pending Changes")
        badge_row, badge = self._badge_row(state, text)
        form.addRow("Status", badge_row)
        self._status_elements = elements
        self._status_badges = [badge]
