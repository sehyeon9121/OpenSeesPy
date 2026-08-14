"""Collect OpenSeesPy model-building commands while a user script runs."""

from collections.abc import Callable
from typing import Any

import openseespy.opensees as ops

from openframe.core.domain.geometric_transform import (
    ORIENTATION_ERROR_MESSAGES,
    ORIENTATION_VECTOR_MISSING,
    OVERRIDABLE_TRANSFORM_TYPES,
    GeometricTransform,
    validate_orientation_vector,
)
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
        #: Every ``ops.geomTransf(...)`` call, keyed by tag, as originally
        #: given by the script - captured before any override substitution so
        #: Import's own collection (which never installs an override) always
        #: preserves the model's real transformation data. Values:
        #: ``{"tag": int, "transform_type": str, "arguments": list[float|str]}``.
        self.geom_transf_definitions: dict[int, dict[str, Any]] = {}
        #: Beam-column element tags whose ``geomTransf``/integration argument
        #: position could not be determined from the call shape alone (not
        #: even attempted with a guess) - surfaced as a warning, never as a
        #: silently wrong tag.
        self.unparsed_transform_references: set[int] = set()
        #: ``ops.timeSeries(type, tag, ...)`` calls, keyed by tag - not needed by
        #: any static solver so far, but buckling_solver.py cross-references this
        #: against a pattern's own tsTag argument (``pattern_definitions``) to
        #: tell a genuinely static reference load (Linear/Constant series) apart
        #: from a Path/Trig one, which cannot be reduced to a single reference
        #: load state without guessing.
        self.time_series_definitions: dict[int, str] = {}
        self.element_loads = ElementLoadCollector()
        self._originals: dict[str, Callable[..., Any]] = {}
        self._tracker: AnalysisStageTracker | None = None
        self._geom_transf_override: str | None = None

    def install(
        self,
        tracker: AnalysisStageTracker | None = None,
        *,
        geom_transf_override: str | None = None,
    ) -> None:
        """``geom_transf_override``, when given, replaces the transformation type
        of every ``ops.geomTransf(...)`` call the script makes (Linear/PDelta/
        Corotational all share the same ``(tag, *transfArgs)`` signature, so the
        substitution is safe) - this is how Setup's Geometric Transformation
        selection actually reaches the analysis: a script's own choice cannot be
        changed after its elements are built (OpenSees resolves the transform
        pointer at ``ops.element(...)`` time, not lazily), so the override must
        happen at the moment ``ops.geomTransf`` itself is called, before any
        element referencing that tag exists."""
        self._tracker = tracker
        self._geom_transf_override = geom_transf_override
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
        self._patch("geomTransf", self._wrap_geom_transf)
        self._patch("timeSeries", self._wrap_time_series)

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
            "geometric_transforms": [
                dict(definition) for _tag, definition in sorted(self.geom_transf_definitions.items())
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
                self.current_pattern_tag = None
                self.pattern_definitions.clear()
                self.material_types.clear()
                self.section_types.clear()
                self.geom_transf_types.clear()
                self.geom_transf_definitions.clear()
                self.unparsed_transform_references.clear()
                self.time_series_definitions.clear()
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

    #: Beam-column element types that reference a ``geomTransf`` tag - the
    #: only ones this project parses a transformation reference out of.
    _TRANSFORM_BEAM_COLUMN_TYPES = frozenset(
        {"elasticbeamcolumn", "dispbeamcolumn", "forcebeamcolumn"}
    )

    def _wrap_element(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(element_type: str, tag: int, *arguments: Any, **kwargs: Any) -> Any:
            if len(arguments) < 2:
                return original(element_type, tag, *arguments, **kwargs)
            properties, transf_tag, integration_tag = self._element_properties(
                element_type, arguments
            )
            is_transform_element = element_type.lower() in self._TRANSFORM_BEAM_COLUMN_TYPES
            if is_transform_element and transf_tag is None:
                self.unparsed_transform_references.add(int(tag))
            if is_transform_element and transf_tag is not None and self.ndm == 3:
                # Checked - and raised, if invalid - *before* the real
                # ops.element(...) call below: OpenSeesPy's own 3D local-axis
                # computation does not raise a catchable Python exception on a
                # zero-length or member-axis-parallel orientation vector, it
                # crashes the whole process. A missing vecxz is the one case
                # OpenSeesPy already rejects cleanly on its own (at the
                # geomTransf(...) call, before this element is ever reached);
                # this still checks it defensively since nothing here can
                # assume that will always stay true.
                self._raise_if_orientation_invalid(
                    tag, arguments[0], arguments[1], transf_tag
                )
            result = original(element_type, tag, *arguments, **kwargs)
            self.elements[int(tag)] = {
                "tag": int(tag),
                "node_i": int(arguments[0]),
                "node_j": int(arguments[1]),
                "element_type": str(element_type),
                "properties": properties,
                "transf_tag": transf_tag,
                "integration_tag": integration_tag,
            }
            return result

        return wrapped

    def _raise_if_orientation_invalid(
        self, tag: int, node_i_tag: Any, node_j_tag: Any, transf_tag: int
    ) -> None:
        """Block a 3D beam-column whose ``geomTransf`` orientation vector
        cannot define local axes - missing, zero-length, parallel to the
        member's own axis, or otherwise degenerate. Only genuine parsing
        uncertainty (the transform definition or an endpoint's coordinates
        could not be resolved yet) is left unjudged here, never guessed at."""
        definition = self.geom_transf_definitions.get(int(transf_tag))
        if definition is None:
            return
        node_i = self.nodes.get(self._as_int(node_i_tag))
        node_j = self.nodes.get(self._as_int(node_j_tag))
        if node_i is None or node_j is None:
            return
        axis_vector = (
            node_j["x"] - node_i["x"],
            node_j["y"] - node_i["y"],
            node_j["z"] - node_i["z"],
        )
        transform = GeometricTransform(
            tag=int(definition["tag"]),
            transform_type=str(definition["transform_type"]),
            arguments=tuple(definition["arguments"]),
        )
        reason = validate_orientation_vector(transform.vector_xz, axis_vector)
        if reason is not None:
            raise RuntimeError(
                f"부재 {tag}(geomTransf {transf_tag}) 3D orientation 검증 실패: "
                f"{ORIENTATION_ERROR_MESSAGES[reason]}. 해석을 시작하지 않았습니다."
            )

    def _element_properties(
        self,
        element_type: str,
        arguments: tuple[Any, ...],
    ) -> tuple[dict[str, float | str], int | None, int | None]:
        """Return ``(properties, transf_tag, integration_tag)``.

        ``transf_tag``/``integration_tag`` are parsed only for the openseespy
        Python-binding argument shapes actually documented for each element
        (no legacy Tcl-only positional forms) - when a call does not match
        that shape, both come back ``None`` rather than a guessed index, and
        the caller records the element as unparsed.
        """
        properties: dict[str, float | str] = {}
        transf_tag: int | None = None
        integration_tag: int | None = None
        element_name = element_type.lower()
        if element_name == "elasticbeamcolumn" and self.ndm == 3 and len(arguments) >= 9:
            transf_tag = self._as_int(arguments[8])
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
            transf_tag = self._as_int(arguments[5])
            properties.update(
                {
                    "A": float(arguments[2]),
                    "E": float(arguments[3]),
                    "I": float(arguments[4]),
                    "transf_tag": str(arguments[5]),
                }
            )
        elif element_name in {"dispbeamcolumn", "forcebeamcolumn"} and len(arguments) >= 4:
            # openseespy's Python binding only exposes the integration-object
            # form for both: (eleTag, iNode, jNode, transfTag, integrationTag,
            # <optional flags>) - no legacy inline numIntgrPts/secTag form.
            transf_tag = self._as_int(arguments[2])
            integration_tag = self._as_int(arguments[3])
            if transf_tag is not None:
                properties["transf_tag"] = str(arguments[2])
            if integration_tag is not None:
                properties["integration_tag"] = str(arguments[3])
        elif element_name in {"truss", "trusssection", "corottruss"} and len(arguments) >= 4:
            properties.update(
                {
                    "A": float(arguments[2]),
                    "material_tag": str(arguments[3]),
                }
            )
        return properties, transf_tag, integration_tag

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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

    def _wrap_geom_transf(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(command_type: str, *arguments: Any, **kwargs: Any) -> Any:
            if (
                self._geom_transf_override is not None
                and str(command_type) not in OVERRIDABLE_TRANSFORM_TYPES
            ):
                # Setup's GEOMETRIC TRANSFORMATION override is all-or-nothing:
                # a model containing even one transform type the override
                # cannot safely substitute (unknown, or a real OpenSees type
                # this project does not support overriding) must fail the
                # entire run rather than override some elements and silently
                # leave others on their original type - raised here, before
                # the model finishes building and before any analysis
                # command runs, so nothing partial is ever reported.
                tag_text = str(arguments[0]) if arguments else "?"
                raise RuntimeError(
                    f"GEOMETRIC TRANSFORMATION 재정의({self._geom_transf_override})는 "
                    f"tag {tag_text}의 '{command_type}' 변환에 적용할 수 없습니다. "
                    "지원하지 않거나 알 수 없는 변환이 포함된 모델은 전체 재정의를 적용할 수 "
                    "없으므로 해석을 시작하지 않았습니다. GEOMETRIC TRANSFORMATION을 "
                    "'Use model definition'으로 바꾸거나 모델의 변환을 Linear/PDelta/"
                    "Corotational로 통일하세요."
                )
            if self.ndm == 3 and arguments:
                # OpenSeesPy itself already rejects a 3D geomTransf missing
                # its orientation vector (vecxz) - but with a cryptic native
                # message ("insufficient arguments for LinearCrdTransf3d"),
                # not this project's own clear one. Caught here, before that
                # call, so every orientation failure reads the same way.
                vecxz_candidate = arguments[1:4]
                if len(vecxz_candidate) < 3 or not all(
                    isinstance(value, (int, float)) for value in vecxz_candidate
                ):
                    raise RuntimeError(
                        f"geomTransf {arguments[0]}: "
                        f"{ORIENTATION_ERROR_MESSAGES[ORIENTATION_VECTOR_MISSING]}. "
                        "해석을 시작하지 않았습니다."
                    )
            effective_type = self._geom_transf_override or command_type
            result = original(effective_type, *arguments, **kwargs)
            self.geom_transf_types.add(str(effective_type))
            if arguments:
                tag = self._as_int(arguments[0])
                if tag is not None:
                    # Recorded under the script's own original type, never the
                    # (possibly overridden) effective one - Import's own
                    # collection never installs an override, so this is
                    # already the model's true definition there; when this
                    # collector *is* running with an override (an analysis
                    # run, not an import), the stored StructuralModel/payload
                    # this feeds is never touched, so the override's effect
                    # stays confined to the transient analysis-only model.
                    self.geom_transf_definitions[tag] = {
                        "tag": tag,
                        "transform_type": str(command_type),
                        "arguments": [
                            float(value) if isinstance(value, (int, float)) else str(value)
                            for value in arguments[1:]
                        ],
                    }
            return result

        return wrapped

    def _wrap_time_series(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(series_type: str, tag: int, *arguments: Any, **kwargs: Any) -> Any:
            result = original(series_type, tag, *arguments, **kwargs)
            self.time_series_definitions[int(tag)] = str(series_type)
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
                    "transf_tag": None,
                    "integration_tag": None,
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
