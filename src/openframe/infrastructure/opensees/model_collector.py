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
        self._patch("load", self._wrap_load)
        self._patch("eleLoad", self._wrap_ele_load)

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
            "element_loads": [
                {"element_tag": tag, "wx": values[0], "wy": values[1]}
                for tag, values in sorted(self.element_loads.uniform_loads.items())
            ],
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
                self.element_loads.uniform_loads.clear()
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
            if len(coordinates) >= 2:
                self.nodes[int(tag)] = {
                    "tag": int(tag),
                    "x": float(coordinates[0]),
                    "y": float(coordinates[1]),
                    "z": float(coordinates[2]) if len(coordinates) >= 3 else 0.0,
                    "ndf": self.ndf,
                }
            return result

        return wrapped

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
        elif element_name in {"truss", "trusssection", "corottruss"} and len(
            arguments
        ) >= 4:
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
                {"node_tag": int(node_tag), "values": [float(value) for value in values]}
            )
            return result

        return wrapped

    def _wrap_ele_load(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            try:
                self.element_loads.record(args)
            except (ValueError, IndexError, TypeError):
                pass
            return result

        return wrapped

    def _merge_runtime_state(self) -> None:
        for raw_tag in ops.getNodeTags():
            tag = int(raw_tag)
            coordinates = ops.nodeCoord(tag)
            if len(coordinates) >= 2 and tag not in self.nodes:
                self.nodes[tag] = {
                    "tag": tag,
                    "x": float(coordinates[0]),
                    "y": float(coordinates[1]),
                    "z": float(coordinates[2]) if len(coordinates) >= 3 else 0.0,
                    "ndf": self.ndf,
                }

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
                self.boundaries[tag] = tuple(
                    dof in fixed_dofs for dof in range(1, self.ndf + 1)
                )

    def _flag_value(self, arguments: tuple[Any, ...], flag: str, default: int) -> int:
        try:
            index = arguments.index(flag)
            return int(arguments[index + 1])
        except (ValueError, IndexError, TypeError):
            return default
