"""Load Case / Load Entry / Load Combination CRUD for StaticsDrawingCanvas -
the 3D Loads tab's own state.

Deliberately parallel to, and never touching, ``self.nodal_loads``/
``self.element_loads`` (``NodalLoad``/``UniformElementLoad``, solver-facing,
exactly one per node/element tag - what the 2D canvas and every real
analysis path already depend on). ``self.load_entries`` is keyed by this
store's own auto-incrementing id instead, so many entries (different cases,
same or different targets) can coexist - that is the entire point of a Load
Tree. Nothing here feeds ``build_model()``/the solver yet; see the Loads tab
overhaul's own notes for what remains unconnected.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from dataclasses import replace

from openframe.core.domain import (
    FloorLoadEntry,
    FloorLoadType,
    LoadCase,
    LoadCaseKind,
    LoadCombination,
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoad,
    NodalLoadEntry,
    SelfWeightEntry,
    UniformElementLoad,
)
from openframe.core.domain.load_entry import LoadEntryPayload
from openframe.features.model.presentation.floor_tributary import convert_floor_entry


class _LoadEntryMixin:
    # -- load cases -----------------------------------------------------
    def add_load_case(
        self, name: str, kind: LoadCaseKind = LoadCaseKind.UNCLASSIFIED, description: str = ""
    ) -> str | None:
        """Returns the new case's id, or ``None`` if ``name`` is already
        taken - never silently overwrites an existing case's data."""
        if not name or name in self.load_cases:
            return None
        self._record_history()
        self.load_cases[name] = LoadCase(id=name, name=name, kind=kind, description=description)
        if self.active_load_case_id is None:
            self.active_load_case_id = name
        self.load_state_changed.emit()
        return name

    def duplicate_load_case(self, case_id: str, new_name: str) -> str | None:
        case = self.load_cases.get(case_id)
        if case is None or not new_name or new_name in self.load_cases:
            return None
        self._record_history()
        self.load_cases[new_name] = replace(case, id=new_name, name=new_name)
        self.load_state_changed.emit()
        return new_name

    def rename_load_case(self, case_id: str, new_name: str) -> bool:
        """Renaming changes the case's id too - every ``LoadEntry.case_id``
        pointing at it is updated in the same pass, so a rename never
        orphans its own loads."""
        case = self.load_cases.get(case_id)
        if case is None or not new_name or (new_name != case_id and new_name in self.load_cases):
            return False
        self._record_history()
        del self.load_cases[case_id]
        self.load_cases[new_name] = replace(case, id=new_name, name=new_name)
        for entry_id, entry in list(self.load_entries.items()):
            if entry.case_id == case_id:
                self.load_entries[entry_id] = replace(entry, case_id=new_name)
        if self.active_load_case_id == case_id:
            self.active_load_case_id = new_name
        self.load_state_changed.emit()
        return True

    def delete_load_case(self, case_id: str) -> None:
        """Cascades: a case's loads have nowhere meaningful to go once the
        case itself is gone, so they are deleted with it rather than left
        pointing at a case_id nothing recognizes."""
        if case_id not in self.load_cases:
            return
        self._record_history()
        del self.load_cases[case_id]
        self.load_entries = {
            entry_id: entry for entry_id, entry in self.load_entries.items() if entry.case_id != case_id
        }
        if self.active_load_case_id == case_id:
            self.active_load_case_id = next(iter(self.load_cases), None)
        self.load_state_changed.emit()

    # -- load entries -----------------------------------------------------
    def add_load_entry(
        self,
        case_id: str,
        kind: str,
        target: tuple[int, ...],
        payload: LoadEntryPayload,
    ) -> int:
        entry_id = self._next_load_entry_id
        self._next_load_entry_id += 1
        self._record_history()
        self.load_entries[entry_id] = LoadEntry(
            id=entry_id, case_id=case_id, kind=kind, target=tuple(target), payload=payload
        )
        self.load_state_changed.emit()
        return entry_id

    def update_load_entry(
        self,
        entry_id: int,
        *,
        target: tuple[int, ...] | None = None,
        payload: LoadEntryPayload | None = None,
    ) -> None:
        entry = self.load_entries.get(entry_id)
        if entry is None:
            return
        self._record_history()
        changes: dict[str, object] = {}
        if target is not None:
            changes["target"] = tuple(target)
        if payload is not None:
            changes["payload"] = payload
        self.load_entries[entry_id] = replace(entry, **changes)
        self.load_state_changed.emit()

    def delete_load_entry(self, entry_id: int) -> None:
        if entry_id not in self.load_entries:
            return
        self._record_history()
        del self.load_entries[entry_id]
        self.load_state_changed.emit()

    def duplicate_load_entry(self, entry_id: int) -> int | None:
        entry = self.load_entries.get(entry_id)
        if entry is None:
            return None
        new_id = self._next_load_entry_id
        self._next_load_entry_id += 1
        self._record_history()
        self.load_entries[new_id] = replace(entry, id=new_id)
        self.load_state_changed.emit()
        return new_id

    def set_load_entry_hidden(self, entry_id: int, hidden: bool) -> None:
        entry = self.load_entries.get(entry_id)
        if entry is None or entry.hidden == hidden:
            return
        self._record_history()
        self.load_entries[entry_id] = replace(entry, hidden=hidden)
        self.load_state_changed.emit()

    def move_load_entry_to_case(self, entry_id: int, case_id: str) -> bool:
        entry = self.load_entries.get(entry_id)
        if entry is None or case_id not in self.load_cases:
            return False
        self._record_history()
        self.load_entries[entry_id] = replace(entry, case_id=case_id)
        self.load_state_changed.emit()
        return True

    # -- load combinations -------------------------------------------------
    def add_load_combination(self, name: str) -> str | None:
        if not name or name in self.load_combinations:
            return None
        self._record_history()
        self.load_combinations[name] = LoadCombination(name=name, factors={})
        if self.active_combination_id is None:
            self.active_combination_id = name
        self.load_state_changed.emit()
        return name

    def update_load_combination(self, name: str, factors: dict[LoadCaseKind, float]) -> None:
        if name not in self.load_combinations:
            return
        self._record_history()
        self.load_combinations[name] = LoadCombination(name=name, factors=dict(factors))
        self.load_state_changed.emit()

    def duplicate_load_combination(self, name: str, new_name: str) -> str | None:
        combination = self.load_combinations.get(name)
        if combination is None or not new_name or new_name in self.load_combinations:
            return None
        self._record_history()
        self.load_combinations[new_name] = LoadCombination(
            name=new_name, factors=dict(combination.factors)
        )
        self.load_state_changed.emit()
        return new_name

    def replace_load_combinations(self, combinations: list[LoadCombination]) -> None:
        """Bulk swap for the Load Combination Manager's Save button -
        ``LoadCombinationPanel`` (its own module docstring: "layout only,
        not wired... yet" until this call site) edits its rows freely and
        hands back the whole list at once, so this replaces
        ``self.load_combinations`` wholesale in one undo step rather than
        diffing row-by-row."""
        self._record_history()
        self.load_combinations = {combination.name: combination for combination in combinations}
        if self.active_combination_id not in self.load_combinations:
            self.active_combination_id = next(iter(self.load_combinations), None)
        self.load_state_changed.emit()

    def delete_load_combination(self, name: str) -> None:
        if name not in self.load_combinations:
            return
        self._record_history()
        del self.load_combinations[name]
        if self.active_combination_id == name:
            self.active_combination_id = next(iter(self.load_combinations), None)
        self.load_state_changed.emit()

    def create_load_case_from_combination(
        self,
        combination_name: str,
        case_name: str,
        *,
        replace_existing: bool = False,
        selected_groups: set[str] | None = None,
        activate_for_analysis: bool = False,
    ) -> int | None:
        """Materialize one load combination as a new static load case.

        This mirrors MIDAS' "Create Load Cases Using Load Combinations":
        every source entry is copied to the target case after its source
        case's semantic-kind factor has been applied. ``None`` means the
        requested target name already existed and replacement was disabled.
        """
        combination = self.load_combinations.get(combination_name)
        if combination is None or not case_name:
            return None
        if case_name in self.load_cases and not replace_existing:
            return None
        groups = selected_groups or {"nodal", "member", "floor", "self_weight"}
        source_entries = [
            entry for entry in self.load_entries.values() if entry.case_id != case_name
        ]
        scaled_entries: list[tuple[str, tuple[int, ...], LoadEntryPayload]] = []
        for entry in source_entries:
            source_case = self.load_cases.get(entry.case_id)
            if source_case is None:
                continue
            factor = combination.factor_for(source_case.kind)
            if factor == 0.0:
                continue
            group = (
                "member"
                if entry.kind.startswith("member_")
                else "self_weight"
                if entry.kind == "self_weight"
                else entry.kind
            )
            if group not in groups:
                continue
            payload = entry.payload
            if isinstance(payload, NodalLoadEntry):
                scaled = replace(
                    payload,
                    fx=payload.fx * factor,
                    fy=payload.fy * factor,
                    fz=payload.fz * factor,
                    mx=payload.mx * factor,
                    my=payload.my * factor,
                    mz=payload.mz * factor,
                )
            elif isinstance(payload, MemberPointLoadEntry):
                scaled = replace(payload, value=payload.value * factor)
            elif isinstance(payload, MemberDistributedLoadEntry):
                scaled = replace(
                    payload,
                    start_value=payload.start_value * factor,
                    end_value=payload.end_value * factor,
                )
            elif isinstance(payload, FloorLoadEntry):
                scaled = replace(payload, magnitude=payload.magnitude * factor)
            elif isinstance(payload, SelfWeightEntry):
                scaled = replace(
                    payload,
                    factor_x=payload.factor_x * factor,
                    factor_y=payload.factor_y * factor,
                    factor_z=payload.factor_z * factor,
                )
            else:  # pragma: no cover - LoadEntryPayload exhaustiveness guard
                continue
            scaled_entries.append((entry.kind, entry.target, scaled))

        self._record_history()
        self.load_cases[case_name] = LoadCase(
            id=case_name,
            name=case_name,
            kind=LoadCaseKind.OTHER,
            description=f"Generated from {combination_name}",
        )
        if replace_existing:
            self.load_entries = {
                entry_id: entry
                for entry_id, entry in self.load_entries.items()
                if entry.case_id != case_name
            }
        generated_entries: list[LoadEntry] = []
        for kind, target, payload in scaled_entries:
            entry_id = self._next_load_entry_id
            self._next_load_entry_id += 1
            generated = LoadEntry(
                id=entry_id,
                case_id=case_name,
                kind=kind,
                target=target,
                payload=payload,
            )
            self.load_entries[entry_id] = generated
            generated_entries.append(generated)
        if activate_for_analysis:
            self._activate_generated_case_for_analysis(generated_entries)
        self.active_load_case_id = case_name
        self.load_state_changed.emit()
        return len(scaled_entries)

    def _activate_generated_case_for_analysis(self, entries: list[LoadEntry]) -> None:
        """Project solver-supported generated entries into the analysis store.

        The current material-free solver supports nodal loads and full-span
        uniform/linearly-varying member loads, plus floor loads (converted to
        boundary-beam member loads via ``floor_tributary.convert_floor_entry``
        - see that module for the tributary-area math and its limits). Point,
        partial and arbitrary self-weight-factor entries remain in the named
        case store until their own dedicated conversion paths exist.
        """
        nodal_totals: dict[int, list[float]] = {}
        member_totals: dict[int, list[float]] = {}
        for entry in entries:
            payload = entry.payload
            if isinstance(payload, NodalLoadEntry):
                values = [payload.fx, payload.fy, payload.fz, payload.mx, payload.my, payload.mz]
                for node_tag in entry.target:
                    total = nodal_totals.setdefault(node_tag, [0.0] * 6)
                    for index, value in enumerate(values):
                        total[index] += value
            elif entry.kind in {"member_uniform", "member_linear"} and isinstance(
                payload, MemberDistributedLoadEntry
            ):
                axis = {"x": 0, "y": 1, "z": 2}.get(payload.direction.lower())
                if axis is None:
                    continue
                for element_tag in entry.target:
                    total = member_totals.setdefault(element_tag, [0.0] * 6)
                    total[axis] += payload.start_value
                    total[axis + 3] += payload.end_value
            elif entry.kind == "floor" and isinstance(payload, FloorLoadEntry):
                for element_tag, values in convert_floor_entry(entry, self.nodes, self.elements).items():
                    total = member_totals.setdefault(element_tag, [0.0] * 6)
                    for index, value in enumerate(values):
                        total[index] += value

        self.nodal_loads = {
            node_tag: NodalLoad(
                node_tag,
                tuple(values if self.ndm == 3 else (values[0], values[1], values[5])),
                case_type=LoadCaseKind.OTHER,
            )
            for node_tag, values in nodal_totals.items()
        }
        self.element_loads = {
            element_tag: UniformElementLoad(
                element_tag,
                wx=values[0],
                wy=values[1],
                wz=values[2],
                wx_j=values[3],
                wy_j=values[4],
                wz_j=values[5],
                case_type=LoadCaseKind.OTHER,
            )
            for element_tag, values in member_totals.items()
        }

    # -- floor load types ---------------------------------------------------
    def add_floor_load_type(
        self, name: str, description: str = "", rows: tuple = ()
    ) -> str | None:
        """Returns the new type's id, or ``None`` if ``name`` is already
        taken - mirrors ``add_load_case``'s own no-silent-overwrite rule."""
        if not name or name in self.floor_load_types:
            return None
        self._record_history()
        self.floor_load_types[name] = FloorLoadType(
            id=name, name=name, description=description, rows=tuple(rows)
        )
        self.load_state_changed.emit()
        return name

    def update_floor_load_type(
        self,
        type_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        rows: tuple | None = None,
    ) -> bool:
        """Renaming changes the type's id too, same as ``rename_load_case`` -
        there is nothing else that references a FloorLoadType by id (unlike
        a LoadCase, applying one only ever reads its rows, never stores the
        type's id anywhere), so no cascade is needed."""
        floor_type = self.floor_load_types.get(type_id)
        if floor_type is None:
            return False
        new_id = name if name is not None else type_id
        if new_id != type_id and new_id in self.floor_load_types:
            return False
        self._record_history()
        del self.floor_load_types[type_id]
        self.floor_load_types[new_id] = FloorLoadType(
            id=new_id,
            name=new_id,
            description=floor_type.description if description is None else description,
            rows=floor_type.rows if rows is None else tuple(rows),
        )
        self.load_state_changed.emit()
        return True

    def duplicate_floor_load_type(self, type_id: str, new_name: str) -> str | None:
        floor_type = self.floor_load_types.get(type_id)
        if floor_type is None or not new_name or new_name in self.floor_load_types:
            return None
        self._record_history()
        self.floor_load_types[new_name] = replace(floor_type, id=new_name, name=new_name)
        self.load_state_changed.emit()
        return new_name

    def delete_floor_load_type(self, type_id: str) -> None:
        if type_id not in self.floor_load_types:
            return
        self._record_history()
        del self.floor_load_types[type_id]
        self.load_state_changed.emit()

    def apply_floor_load_type(
        self,
        type_id: str,
        target_nodes: tuple[int, ...],
        *,
        direction: str = "-z",
        distribution: str = "one_way",
        span_direction: str = "x",
    ) -> int | None:
        """Materialize every non-empty row of ``type_id`` as its own
        ``FloorLoadEntry``, all sharing ``target_nodes``/``direction``/
        ``distribution``/``span_direction`` - the MIDAS "Assign Floor Loads"
        step: pick a Floor Load Type, pick the boundary, Apply once instead
        of repeating the single-value Floor Load form per case. ``None``
        means the type does not exist; otherwise returns how many entries
        were created (a row with ``case_id=None`` or ``magnitude=0`` is
        skipped, so this can be 0 for an empty type).
        """
        floor_type = self.floor_load_types.get(type_id)
        if floor_type is None:
            return None
        rows = [
            row for row in floor_type.rows if row.case_id is not None and row.magnitude != 0.0
        ]
        if not rows:
            return 0
        self._record_history()
        for row in rows:
            entry_id = self._next_load_entry_id
            self._next_load_entry_id += 1
            self.load_entries[entry_id] = LoadEntry(
                id=entry_id,
                case_id=row.case_id,
                kind="floor",
                target=tuple(target_nodes),
                payload=FloorLoadEntry(
                    magnitude=row.magnitude,
                    direction=direction,
                    distribution=distribution,
                    span_direction=span_direction,
                    target_nodes=tuple(target_nodes),
                ),
            )
        self.load_state_changed.emit()
        return len(rows)
