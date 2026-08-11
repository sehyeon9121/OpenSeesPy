"""Collect OpenSeesPy model-building commands while a user script runs."""

from collections.abc import Callable
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.element_load_collector import ElementLoadCollector
from openframe.infrastructure.opensees.script_execution import AnalysisStageTracker


class ModelCommandCollector:
    """Record initial 2D/3D nodes, elements, supports and loads."""

    def __init__(self) -> None:
        self.ndm = 2
        self.ndf = 3
        self.nodes: dict[int, dict[str, Any]] = {}
        self.elements: dict[int, dict[str, Any]] = {}
        self.boundaries: dict[int, tuple[bool, ...]] = {}
        self.loads: list[dict[str, Any]] = []
        self.current_pattern_tag: int | None = None
        self.pattern_definitions: dict[int, tuple[str, tuple[Any, ...]]] = {}
        self.material_types: set[str] = set()
        self.section_types: set[str] = set()
        self.geom_transf_types: set[str] = set()
        self.element_loads = ElementLoadCollector()
        self._originals: dict[str, Callable[..., Any]] = {}
        self._tracker: AnalysisStageTracker | None = None

    def install(self, tracker: AnalysisStageTracker | None = None) -> None:
        self._tracker = tracker
        self._patch("wipe", self._wrap_wipe)
        self._patch("model", self._wrap_model)
        self._patch("node", self._wrap_node)
        self._patch("element", self._wrap_element)
        self._patch("fix", self._wrap_fix)
        self._patch("pattern", self._wrap_pattern)
        self._patch("load", self._wrap_load)
        self._patch("eleLoad", self._wrap_ele_load)
        self._patch(
            "uniaxialMaterial",
            lambda original: self._wrap_typed_command(original, self.material_types),
        )
        self._patch(
            "nDMaterial",
            lambda original: self._wrap_typed_command(original, self.material_types),
        )
        self._patch(
            "section",
            lambda original: self._wrap_typed_command(original, self.section_types),
        )
        self._patch(
            "geomTransf",
            lambda original: self._wrap_typed_command(original, self.geom_transf_types),
        )

    def restore(self) -> None:
        """Put the real OpenSees commands back once the script has finished."""
        for name, original in self._originals.items():
            setattr(ops, name, original)
        self._originals.clear()

    def to_payload(self) -> dict[str, Any]:
        self._merge_runtime_state()
        return {
            "ndm": self.ndm,
            "ndf": self.ndf,
            "nodes": list(self.nodes.values()),
            "elements": list(self.elements.values()),
            "boundaries": [
                {"node_tag": tag, "restraints": list(restraints)}
                for tag, restraints in sorted(self.boundaries.items())
            ],
            "nodal_loads": self.loads,
            "element_loads": self._element_load_payload(),
            "metadata": {"source": "openseespy-worker"},
        }

    def _patch(self, name: str, wrapper_factory: Callable[..., Any]) -> None:
        original = getattr(ops, name)
        self._originals[name] = original
        setattr(ops, name, wrapper_factory(original))

    def _wrap_wipe(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            # Once the script has touched its analysis stage, the model is presumably
            # finished and a further wipe() is end-of-script cleanup, not a request to
            # discard everything collected so far.
            if self._tracker is None or not self._tracker.started:
                self.nodes.clear()
                self.elements.clear()
                self.boundaries.clear()
                self.loads.clear()
                self.current_pattern_tag = None
                self.pattern_definitions.clear()
                self.material_types.clear()
                self.section_types.clear()
                self.geom_transf_types.clear()
                self.element_loads.uniform_loads.clear()
                self.element_loads.uniform_loads_3d.clear()
                self.element_loads.uniform_load_cases.clear()
                self.element_loads.unsupported.clear()
            return original(*args, **kwargs)

        return wrapped

    def _wrap_model(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self.ndm = self._flag_value(args, "-ndm", self.ndm)
            self.ndf = self._flag_value(args, "-ndf", self.ndf)
            return original(*args, **kwargs)

        return wrapped

    def _wrap_node(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(tag: int, *coordinates: Any, **kwargs: Any) -> Any:
            result = original(tag, *coordinates, **kwargs)
            recorded = self._node_from_coordinates(tag, coordinates)
            if recorded is not None:
                self.nodes[int(tag)] = recorded
            return result

        return wrapped

    def _node_from_coordinates(
        self, tag: int, coordinates: tuple[Any, ...]
    ) -> dict[str, Any] | None:
        # ops.node() accepts trailing flag arguments after the real coordinates
        # (e.g. '-mass', m1, m2, ...), and 1D models (ndm=1) pass only a single
        # coordinate - so only the first `ndm` positional values are coordinates,
        # never a fixed count, and anything after them (including non-numeric flag
        # strings) must be ignored rather than blindly parsed as x/y/z.
        dimensions = max(self.ndm, 1)
        if len(coordinates) < dimensions:
            return None
        try:
            values = tuple(float(value) for value in coordinates[:dimensions])
        except (TypeError, ValueError):
            return None
        x, y, z = (*values, 0.0, 0.0)[:3]
        return {"tag": int(tag), "x": x, "y": y, "z": z, "ndf": self.ndf}

    def _wrap_element(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(element_type: str, tag: int, *arguments: Any, **kwargs: Any) -> Any:
            result = original(element_type, tag, *arguments, **kwargs)
            if len(arguments) >= 2:
                self.elements[int(tag)] = {
                    "tag": int(tag),
                    "node_i": int(arguments[0]),
                    "node_j": int(arguments[1]),
                    "element_type": str(element_type),
                    "properties": self._element_properties(element_type, arguments),
                }
            return result

        return wrapped

    def _element_properties(
        self,
        element_type: str,
        arguments: tuple[Any, ...],
    ) -> dict[str, float | str]:
        properties: dict[str, float | str] = {}
        element_name = element_type.lower()
        if element_name == "elasticbeamcolumn" and self.ndm == 3 and len(arguments) >= 9:
            properties.update(
                {
                    "A": float(arguments[2]),
                    "E": float(arguments[3]),
                    "G": float(arguments[4]),
                    "J": float(arguments[5]),
                    "Iy": float(arguments[6]),
                    "Iz": float(arguments[7]),
                    "transf_tag": str(arguments[8]),
                }
            )
        elif element_name == "elasticbeamcolumn" and len(arguments) >= 6:
            properties.update(
                {
                    "A": float(arguments[2]),
                    "E": float(arguments[3]),
                    "I": float(arguments[4]),
                    "transf_tag": str(arguments[5]),
                }
            )
        elif element_name in {"truss", "trusssection", "corottruss"} and len(arguments) >= 4:
            properties.update(
                {
                    "A": float(arguments[2]),
                    "material_tag": str(arguments[3]),
                }
            )
        return properties

    def _wrap_fix(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(node_tag: int, *restraints: Any, **kwargs: Any) -> Any:
            result = original(node_tag, *restraints, **kwargs)
            self.boundaries[int(node_tag)] = tuple(bool(value) for value in restraints)
            return result

        return wrapped

    def _wrap_load(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(node_tag: int, *values: Any, **kwargs: Any) -> Any:
            result = original(node_tag, *values, **kwargs)
            self.loads.append(
                {
                    "node_tag": int(node_tag),
                    "values": [float(value) for value in values],
                    "pattern_tag": self.current_pattern_tag,
                }
            )
            return result

        return wrapped

    def _wrap_pattern(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(pattern_type: str, pattern_tag: int, *arguments: Any, **kwargs: Any) -> Any:
            result = original(pattern_type, pattern_tag, *arguments, **kwargs)
            self.current_pattern_tag = int(pattern_tag)
            self.pattern_definitions[int(pattern_tag)] = (str(pattern_type), tuple(arguments))
            return result

        return wrapped

    def _wrap_ele_load(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            try:
                self.element_loads.record(args, self.ndm, self.current_pattern_tag)
            except (ValueError, IndexError, TypeError):
                pass
            return result

        return wrapped

    @staticmethod
    def _wrap_typed_command(
        original: Callable[..., Any], destination: set[str]
    ) -> Callable[..., Any]:
        def wrapped(command_type: str, *arguments: Any, **kwargs: Any) -> Any:
            result = original(command_type, *arguments, **kwargs)
            destination.add(str(command_type))
            return result

        return wrapped

    def _element_load_payload(self) -> list[dict[str, float | int]]:
        if self.element_loads.uniform_load_cases:
            return [
                {
                    "element_tag": element_tag,
                    "pattern_tag": pattern_tag,
                    "wx": values[0],
                    "wy": values[1],
                    "wz": values[2],
                }
                for (pattern_tag, element_tag), values in sorted(
                    self.element_loads.uniform_load_cases.items(),
                    key=lambda item: (-1 if item[0][0] is None else item[0][0], item[0][1]),
                )
            ]
        if self.ndm == 3:
            return [
                {
                    "element_tag": tag,
                    "wx": values[0],
                    "wy": values[1],
                    "wz": values[2],
                }
                for tag, values in sorted(self.element_loads.uniform_loads_3d.items())
            ]
        return [
            {"element_tag": tag, "wx": values[0], "wy": values[1], "wz": 0.0}
            for tag, values in sorted(self.element_loads.uniform_loads.items())
        ]

    def _merge_runtime_state(self) -> None:
        for raw_tag in ops.getNodeTags():
            tag = int(raw_tag)
            if tag in self.nodes:
                continue
            recorded = self._node_from_coordinates(tag, tuple(ops.nodeCoord(tag)))
            if recorded is not None:
                self.nodes[tag] = recorded

        for raw_tag in ops.getEleTags():
            tag = int(raw_tag)
            nodes = ops.eleNodes(tag)
            if len(nodes) >= 2 and tag not in self.elements:
                self.elements[tag] = {
                    "tag": tag,
                    "node_i": int(nodes[0]),
                    "node_j": int(nodes[1]),
                    "element_type": "unknown",
                    "properties": {},
                }

        for raw_tag in ops.getFixedNodes():
            tag = int(raw_tag)
            if tag not in self.boundaries:
                fixed_dofs = {int(value) for value in ops.getFixedDOFs(tag)}
                self.boundaries[tag] = tuple(dof in fixed_dofs for dof in range(1, self.ndf + 1))

    def _flag_value(self, arguments: tuple[Any, ...], flag: str, default: int) -> int:
        try:
            index = arguments.index(flag)
            return int(arguments[index + 1])
        except (ValueError, IndexError, TypeError):
            return default
