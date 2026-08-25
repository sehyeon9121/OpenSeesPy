"""Project-file (.ofsm) serialization methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from dataclasses import asdict

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    FloorLoadEntry,
    FloorLoadType,
    FloorLoadTypeRow,
    LoadCase,
    LoadCaseKind,
    LoadCombination,
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoad,
    NodalLoadEntry,
    Node,
    SelfWeightEntry,
    Story,
    UniformElementLoad,
)
from openframe.features.model.drawing import PlaneKind, WorkPlane

#: Which payload dataclass a ``LoadEntry.kind`` implies - both directions of
#: (de)serialization dispatch off this instead of duplicating the mapping.
_LOAD_ENTRY_PAYLOAD_TYPES: dict[str, type] = {
    "nodal": NodalLoadEntry,
    "member_point": MemberPointLoadEntry,
    "member_moment": MemberPointLoadEntry,
    "member_uniform": MemberDistributedLoadEntry,
    "member_linear": MemberDistributedLoadEntry,
    "member_partial": MemberDistributedLoadEntry,
    "floor": FloorLoadEntry,
    "self_weight": SelfWeightEntry,
}


class _SerializationMixin:
    def to_dict(self) -> dict[str, object]:
        """Serialize this canvas's raw authoring state for a project file.

        Deliberately NOT the analysis-ready ``StructuralModel`` ``build_model()``
        produces (already segmented at embedded nodes, with new tags minted for
        the pieces) — that view can always be recomputed from this one, but not
        the other way around, so reopening a saved project has to restore the
        exact editable state (original tags, embedded_nodes, hinge_nodes, work
        planes) rather than the solved/segmented one.
        """
        return {
            "format": "openframe-canvas",
            "version": 1,
            "ndm": self.ndm,
            "element_family": self.element_family,
            "include_self_weight": self.include_self_weight,
            "levels": [
                {"kind": str(plane.kind), "offset": plane.offset, "label": plane.label}
                for plane in self.levels
            ],
            "active_plane_index": (
                self.levels.index(self.work_plane) if self.work_plane in self.levels else 0
            ),
            "nodes": [
                {"tag": tag, "x": node.x, "y": node.y, "z": node.z, "ndf": node.ndf}
                for tag, node in self.nodes.items()
            ],
            "elements": [
                {
                    "tag": tag,
                    "node_i": element.node_i,
                    "node_j": element.node_j,
                    "element_type": element.element_type,
                    "properties": dict(element.properties),
                    "moment_release_i": element.moment_release_i,
                    "moment_release_j": element.moment_release_j,
                    "local_axis_angle": element.local_axis_angle,
                    "offset_i": list(element.offset_i),
                    "offset_j": list(element.offset_j),
                }
                for tag, element in self.elements.items()
            ],
            "boundaries": [
                {
                    "node_tag": tag,
                    "restraints": list(boundary.restraints),
                    "angle": boundary.angle,
                    "spring_stiffnesses": list(boundary.spring_stiffnesses),
                }
                for tag, boundary in self.boundaries.items()
            ],
            "nodal_loads": [
                {
                    "node_tag": tag,
                    "values": list(load.values),
                    "pattern_tag": load.pattern_tag,
                    "case_type": load.case_type.value,
                }
                for tag, load in self.nodal_loads.items()
            ],
            "element_loads": [
                {
                    "element_tag": tag,
                    "wx": load.wx,
                    "wy": load.wy,
                    "wz": load.wz,
                    "wx_j": load.wx_j,
                    "wy_j": load.wy_j,
                    "wz_j": load.wz_j,
                    "pattern_tag": load.pattern_tag,
                    "case_type": load.case_type.value,
                }
                for tag, load in self.element_loads.items()
            ],
            "embedded_nodes": [
                {"node_tag": tag, "host_tag": host_tag, "position": position}
                for tag, (host_tag, position) in self.embedded_nodes.items()
            ],
            "hinge_nodes": sorted(self.hinge_nodes),
            "load_cases": [
                {"id": case.id, "name": case.name, "kind": case.kind.value, "description": case.description}
                for case in self.load_cases.values()
            ],
            "active_load_case_id": self.active_load_case_id,
            "load_entries": [
                {
                    "id": entry.id,
                    "case_id": entry.case_id,
                    "kind": entry.kind,
                    "target": list(entry.target),
                    "payload": asdict(entry.payload),
                    "hidden": entry.hidden,
                }
                for entry in self.load_entries.values()
            ],
            "load_combinations": [
                {"name": combination.name, "factors": {k.value: v for k, v in combination.factors.items()}}
                for combination in self.load_combinations.values()
            ],
            "active_combination_id": self.active_combination_id,
            "floor_load_types": [
                {
                    "id": floor_type.id,
                    "name": floor_type.name,
                    "description": floor_type.description,
                    "rows": [
                        {"case_id": row.case_id, "magnitude": row.magnitude} for row in floor_type.rows
                    ],
                }
                for floor_type in self.floor_load_types.values()
            ],
            "stories": [
                {
                    "id": story.id,
                    "name": story.name,
                    "elevation": story.elevation,
                    "rigid_diaphragm": story.rigid_diaphragm,
                }
                for story in self.stories.values()
            ],
        }

    def load_dict(self, data: dict[str, object]) -> None:
        """Replace this canvas's entire state with a previously-``to_dict()``'d
        one. Routes the core entity dicts through ``_restore`` (the same path
        undo/redo already uses) instead of a parallel assignment, so a load
        gets the exact same selection-clearing/redraw/signal behaviour a
        history jump does, proven by the same tests.
        """
        self.ndm = int(data.get("ndm", 2))
        self.element_family = str(data.get("element_family", "frame"))
        self.include_self_weight = bool(data.get("include_self_weight", False))
        levels_data = data.get("levels") or [{"kind": "xy", "offset": 0.0, "label": "1F"}]
        self.levels = [
            WorkPlane(kind=PlaneKind(level["kind"]), offset=level["offset"], label=level["label"])
            for level in levels_data
        ]
        active_index = int(data.get("active_plane_index", 0))
        if not 0 <= active_index < len(self.levels):
            active_index = 0
        self.work_plane = self.levels[active_index]

        nodes = {
            int(n["tag"]): Node(int(n["tag"]), n["x"], n["y"], n.get("z", 0.0), n.get("ndf", 3))
            for n in data.get("nodes", [])
        }
        elements = {
            int(e["tag"]): Element(
                int(e["tag"]),
                int(e["node_i"]),
                int(e["node_j"]),
                e["element_type"],
                dict(e.get("properties", {})),
                bool(e.get("moment_release_i", False)),
                bool(e.get("moment_release_j", False)),
                local_axis_angle=float(e.get("local_axis_angle", 0.0)),
                offset_i=tuple(e.get("offset_i", (0.0, 0.0, 0.0))),
                offset_j=tuple(e.get("offset_j", (0.0, 0.0, 0.0))),
            )
            for e in data.get("elements", [])
        }
        boundaries = {
            int(b["node_tag"]): BoundaryCondition(
                int(b["node_tag"]),
                tuple(b["restraints"]),
                float(b.get("angle", 0.0)),
                tuple(b.get("spring_stiffnesses", ())),
            )
            for b in data.get("boundaries", [])
        }
        nodal_loads = {
            int(load["node_tag"]): NodalLoad(
                int(load["node_tag"]),
                tuple(load["values"]),
                load.get("pattern_tag"),
                LoadCaseKind(load.get("case_type", LoadCaseKind.UNCLASSIFIED.value)),
            )
            for load in data.get("nodal_loads", [])
        }
        element_loads = {
            int(load["element_tag"]): UniformElementLoad(
                int(load["element_tag"]),
                wx=load.get("wx", 0.0),
                wy=load.get("wy", 0.0),
                wz=load.get("wz", 0.0),
                wx_j=load.get("wx_j"),
                wy_j=load.get("wy_j"),
                wz_j=load.get("wz_j"),
                pattern_tag=load.get("pattern_tag"),
                case_type=LoadCaseKind(load.get("case_type", LoadCaseKind.UNCLASSIFIED.value)),
            )
            for load in data.get("element_loads", [])
        }
        embedded_nodes = {
            int(entry["node_tag"]): (int(entry["host_tag"]), float(entry["position"]))
            for entry in data.get("embedded_nodes", [])
        }
        hinge_nodes = {int(tag) for tag in data.get("hinge_nodes", [])}

        load_cases = {
            str(case["id"]): LoadCase(
                id=str(case["id"]),
                name=str(case["name"]),
                kind=LoadCaseKind(case.get("kind", LoadCaseKind.UNCLASSIFIED.value)),
                description=str(case.get("description", "")),
            )
            for case in data.get("load_cases", [])
        }
        load_entries = {
            int(entry["id"]): LoadEntry(
                id=int(entry["id"]),
                case_id=str(entry["case_id"]),
                kind=str(entry["kind"]),
                target=tuple(entry.get("target", [])),
                payload=_LOAD_ENTRY_PAYLOAD_TYPES[str(entry["kind"])](**entry.get("payload", {})),
                hidden=bool(entry.get("hidden", False)),
            )
            for entry in data.get("load_entries", [])
        }
        load_combinations = {
            str(combination["name"]): LoadCombination(
                name=str(combination["name"]),
                factors={
                    LoadCaseKind(kind): float(factor)
                    for kind, factor in combination.get("factors", {}).items()
                },
            )
            for combination in data.get("load_combinations", [])
        }
        floor_load_types = {
            str(floor_type["id"]): FloorLoadType(
                id=str(floor_type["id"]),
                name=str(floor_type["name"]),
                description=str(floor_type.get("description", "")),
                rows=tuple(
                    FloorLoadTypeRow(
                        case_id=row.get("case_id"),
                        magnitude=float(row.get("magnitude", 0.0)),
                    )
                    for row in floor_type.get("rows", [])
                ),
            )
            for floor_type in data.get("floor_load_types", [])
        }
        stories = {
            str(story["id"]): Story(
                id=str(story["id"]),
                name=str(story["name"]),
                elevation=float(story["elevation"]),
                rigid_diaphragm=bool(story.get("rigid_diaphragm", False)),
            )
            for story in data.get("stories", [])
        }

        self._restore(
            {
                "nodes": nodes,
                "elements": elements,
                "boundaries": boundaries,
                "nodal_loads": nodal_loads,
                "element_loads": element_loads,
                "hinge_nodes": hinge_nodes,
                "embedded_nodes": embedded_nodes,
                "load_cases": load_cases,
                "active_load_case_id": data.get("active_load_case_id"),
                "load_entries": load_entries,
                "load_combinations": load_combinations,
                "active_combination_id": data.get("active_combination_id"),
                "floor_load_types": floor_load_types,
                "stories": stories,
            }
        )
        self._next_load_entry_id = max(load_entries.keys(), default=0) + 1
        self._undo_stack.clear()
        self._redo_stack.clear()
