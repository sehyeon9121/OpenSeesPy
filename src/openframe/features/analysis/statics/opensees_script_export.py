"""Export a hand-drawn 2D canvas model as a runnable OpenSeesPy script.

The canvas's own solvers (``MaterialFreeStaticsSolver``, ``ModalStaticsSolver``)
run in-process and cover determinate statics and eigenvalue analysis, but stop
there - nonlinear static (real Newton-Raphson, incremental pushover) and time
history live only in the "OpenSeesPy 파일 불러오기" pipeline
(``infrastructure/opensees/nonlinear_static_solver.py``/``time_history_solver.py``),
which expects a plain ``.py`` script it can execute in a subprocess. This module
is the bridge: it writes the exact same model - nodes, supports (including
inclined ones), sections, hinges, loads (including trapezoidal ones), and
optionally lumped mass - as script text, reusing the already-validated
techniques ``solver.py``/``modal_solver.py`` use in-process (inclined-support
zero-length springs, trapezoid discretization, hinge releases) instead of
re-deriving them.

The generated script only *builds* the model - no analysis commands - matching
what ``run_model_script`` (script_execution.py) expects and needs: it suppresses
the analysis stage anyway, so anything here would be inert, but leaving it out
keeps the file honest about what it does.
"""

import math

from openframe.core.domain.model import (
    BoundaryCondition,
    Element,
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.analysis.statics.solver import (
    _INCLINED_SUPPORT_MATERIAL_TAG,
    _INCLINED_SUPPORT_STIFFNESS,
    MaterialFreeStaticsSolver,
    _element_family,
)

#: Same table `ModalStaticsSolver` uses to convert a lumped unit-weight into a
#: true mass (``m = W / g``) - duplicated rather than imported since that one is
#: module-private to modal_solver.py; kept numerically identical on purpose.
_GRAVITY_BY_LENGTH_UNIT: dict[str, float] = {
    "m": 9.81,
    "mm": 9810.0,
    "cm": 981.0,
    "ft": 32.174,
    "in": 386.09,
}

_TRAPEZOID_NODE_TAG_OFFSET = 7_000_000
_TRAPEZOID_ELEMENT_TAG_OFFSET = 7_500_000
_TRAPEZOID_SEGMENTS = 40
_TRUSS_MATERIAL_TAG_OFFSET = 9_100_000


def export_opensees_script(
    model: StructuralModel,
    *,
    include_mass: bool = False,
    length_unit: str = "m",
) -> str:
    """Return a runnable OpenSeesPy script text for ``model``.

    Raises ``ValueError`` (Korean message, matching this codebase's other
    solver-facing errors) if the model cannot be exported meaningfully: not 2D,
    empty, or missing real section/material properties anywhere. Unlike the
    canvas's own determinate solver, there is no unit-placeholder fallback here
    - a script meant to feed a real nonlinear/modal/time-history run is only as
    trustworthy as the stiffness values it carries.
    """
    if model.ndm != 2:
        raise ValueError("현재 2D 모델만 OpenSeesPy 스크립트로 내보낼 수 있습니다.")
    if not model.nodes or not model.elements:
        raise ValueError("절점과 부재를 먼저 작성하세요.")

    missing = sorted(
        element.tag
        for element in model.elements.values()
        if _element_properties(element) is None
    )
    if missing:
        listed = ", ".join(str(tag) for tag in missing)
        needs_inertia = any(
            _element_family(model.elements[tag].element_type) != "truss" for tag in missing
        )
        needed = "E/A/I" if needs_inertia else "E/A"
        raise ValueError(
            f"부재 {listed}에 재료·단면({needed})이 입력되지 않았습니다. 정밀 해석으로 "
            "내보내려면 모든 부재에 실제 강성이 필요합니다."
        )

    lines: list[str] = [
        "import openseespy.opensees as ops",
        "",
        "ops.wipe()",
        f"ops.model('basic', '-ndm', 2, '-ndf', {model.ndf})",
        "",
    ]

    for node in sorted(model.nodes.values(), key=lambda item: item.tag):
        lines.append(f"ops.node({node.tag}, {_num(node.x)}, {_num(node.y)})")
    lines.append("")

    _write_boundaries(lines, model)
    _write_elements(lines, model)
    if include_mass:
        _write_mass(lines, model, length_unit)
    _write_loads(lines, model)

    return "\n".join(lines) + "\n"


def _element_properties(element: Element) -> tuple[float, ...] | None:
    if _element_family(element.element_type) == "truss":
        try:
            return (float(element.properties["E"]), float(element.properties["A"]))
        except (KeyError, TypeError, ValueError):
            return None
    return MaterialFreeStaticsSolver._element_material(element)


def _num(value: float) -> str:
    """Shortest text that reads back as the exact same float - ``repr`` is the
    only builtin formatter Python guarantees round-trips (since 3.1)."""
    return repr(float(value))


def _write_boundaries(lines: list[str], model: StructuralModel) -> None:
    ndf = model.ndf
    inclined = [condition for condition in model.boundaries if condition.is_inclined]
    plain = [condition for condition in model.boundaries if not condition.is_inclined]
    for condition in plain:
        restraints = tuple(int(value) for value in condition.restraints[:ndf])
        restraints += (0,) * (ndf - len(restraints))
        lines.append(f"ops.fix({condition.node_tag}, {', '.join(str(v) for v in restraints)})")
    if plain:
        lines.append("")

    if inclined:
        lines.append(
            f"ops.uniaxialMaterial('Elastic', {_INCLINED_SUPPORT_MATERIAL_TAG}, "
            f"{_num(_INCLINED_SUPPORT_STIFFNESS)})"
        )
        for condition in inclined:
            _write_inclined_support(lines, condition, ndf, model)
        lines.append("")


def _write_inclined_support(
    lines: list[str], condition: BoundaryCondition, ndf: int, model: StructuralModel
) -> None:
    """Text form of ``MaterialFreeStaticsSolver._fix_inclined``: a fully-fixed
    dummy ground node plus a zero-length spring rotated to the support's own
    angle, so only the restrained local direction(s) actually resist motion."""
    node = model.nodes[condition.node_tag]
    ground_tag = 9_000_000 + condition.node_tag
    radians = math.radians(condition.angle)
    vector_x = (math.cos(radians), math.sin(radians), 0.0)
    vector_y = (-math.sin(radians), math.cos(radians), 0.0)
    materials: list[int] = []
    directions: list[int] = []
    for index in range(min(2, ndf)):
        if condition.restraints[index]:
            materials.append(_INCLINED_SUPPORT_MATERIAL_TAG)
            directions.append(index + 1)
    if ndf > 2 and len(condition.restraints) > 2 and condition.restraints[2]:
        materials.append(_INCLINED_SUPPORT_MATERIAL_TAG)
        directions.append(3)
    if not directions:
        return
    lines.append(f"ops.node({ground_tag}, {_num(node.x)}, {_num(node.y)})")
    lines.append(f"ops.fix({ground_tag}, {', '.join('1' for _ in range(ndf))})")
    material_args = ", ".join(str(tag) for tag in materials)
    direction_args = ", ".join(str(value) for value in directions)
    orient_args = ", ".join(_num(value) for value in (*vector_x, *vector_y))
    lines.append(
        f"ops.element('zeroLength', {ground_tag}, {ground_tag}, {condition.node_tag}, "
        f"'-mat', {material_args}, '-dir', {direction_args}, '-orient', {orient_args})"
    )


def _write_elements(lines: list[str], model: StructuralModel) -> None:
    trapezoid_loads = {
        load.element_tag: load for load in model.element_loads if not load.is_uniform
    }
    truss_elements = [
        element
        for element in model.elements.values()
        if _element_family(element.element_type) == "truss"
    ]
    frame_elements = [
        element
        for element in model.elements.values()
        if _element_family(element.element_type) != "truss"
    ]

    for element in sorted(truss_elements, key=lambda item: item.tag):
        elastic, area = _element_properties(element)
        material_tag = _TRUSS_MATERIAL_TAG_OFFSET + element.tag
        lines.append(f"ops.uniaxialMaterial('Elastic', {material_tag}, {_num(elastic)})")
        lines.append(
            f"ops.element('Truss', {element.tag}, {element.node_i}, {element.node_j}, "
            f"{_num(area)}, {material_tag})"
        )
    if truss_elements:
        lines.append("")

    if frame_elements:
        lines.append("ops.geomTransf('Linear', 1)")
        for element in sorted(frame_elements, key=lambda item: item.tag):
            trapezoid = trapezoid_loads.get(element.tag)
            if trapezoid is not None:
                elastic, area, inertia = _element_properties(element)
                _write_discretized_member(lines, model, element, area, elastic, inertia)
                continue
            elastic, area, inertia = _element_properties(element)
            release_code = int(element.moment_release_i) + 2 * int(element.moment_release_j)
            call = (
                f"ops.element('elasticBeamColumn', {element.tag}, {element.node_i}, "
                f"{element.node_j}, {_num(area)}, {_num(elastic)}, {_num(inertia)}, 1"
            )
            if release_code:
                call += f", '-release', {release_code}"
            lines.append(call + ")")
        lines.append("")


def _write_discretized_member(
    lines: list[str],
    model: StructuralModel,
    element: Element,
    area: float,
    elastic: float,
    inertia: float,
) -> None:
    """Text form of ``MaterialFreeStaticsSolver._build_discretized_member``:
    OpenSeesPy's ``eleLoad`` has no linearly-varying transverse load, so a
    trapezoidally-loaded member is chained from many short sub-elements, each
    carrying the true w(x) sampled at its own midpoint as a constant
    -beamUniform. Segment count/offsets match the in-process solver exactly, so
    an exported run reproduces the same numbers as solving in the canvas."""
    node_i = model.nodes[element.node_i]
    node_j = model.nodes[element.node_j]
    segments = _TRAPEZOID_SEGMENTS
    node_tags = (
        [element.node_i]
        + [
            _TRAPEZOID_NODE_TAG_OFFSET + element.tag * 1000 + segment
            for segment in range(1, segments)
        ]
        + [element.node_j]
    )
    for segment in range(1, segments):
        ratio = segment / segments
        x = node_i.x + (node_j.x - node_i.x) * ratio
        y = node_i.y + (node_j.y - node_i.y) * ratio
        lines.append(f"ops.node({node_tags[segment]}, {_num(x)}, {_num(y)})")
    for segment in range(segments):
        sub_tag = _TRAPEZOID_ELEMENT_TAG_OFFSET + element.tag * 1000 + segment
        call = (
            f"ops.element('elasticBeamColumn', {sub_tag}, {node_tags[segment]}, "
            f"{node_tags[segment + 1]}, {_num(area)}, {_num(elastic)}, {_num(inertia)}, 1"
        )
        release_i = element.moment_release_i if segment == 0 else False
        release_j = element.moment_release_j if segment == segments - 1 else False
        release_code = int(release_i) + 2 * int(release_j)
        if release_code:
            call += f", '-release', {release_code}"
        lines.append(call + ")")


def _write_mass(lines: list[str], model: StructuralModel, length_unit: str) -> None:
    """Text form of ``ModalStaticsSolver._apply_mass``: each element's own
    self-weight (density * A * length) lumped half to each end node, converted
    to a true mass via m = W / g - translational DOFs only, no rotational mass,
    the standard lumped-mass frame convention."""
    gravity = _GRAVITY_BY_LENGTH_UNIT.get(length_unit, 9.81)
    node_mass: dict[int, float] = {}
    for element in model.elements.values():
        try:
            density = float(element.properties["density"])
            area = float(element.properties["A"])
        except (KeyError, TypeError, ValueError):
            continue
        if density == 0.0 or area == 0.0:
            continue
        start = model.nodes[element.node_i]
        end = model.nodes[element.node_j]
        length = math.hypot(end.x - start.x, end.y - start.y)
        if length <= 0.0:
            continue
        half_mass = (density * area * length / 2.0) / gravity
        node_mass[element.node_i] = node_mass.get(element.node_i, 0.0) + half_mass
        node_mass[element.node_j] = node_mass.get(element.node_j, 0.0) + half_mass

    if not node_mass:
        return
    for tag in sorted(node_mass):
        mass = node_mass[tag]
        if mass > 0.0:
            lines.append(f"ops.mass({tag}, {_num(mass)}, {_num(mass)}, 0.0)")
    lines.append("")


def _write_loads(lines: list[str], model: StructuralModel) -> None:
    if not model.nodal_loads and not model.element_loads:
        return
    lines.append("ops.timeSeries('Linear', 1)")
    lines.append("ops.pattern('Plain', 1, 1)")
    ndf = model.ndf
    for load in model.nodal_loads:
        values = tuple(load.values[:ndf]) + (0.0,) * max(0, ndf - len(load.values))
        lines.append(f"ops.load({load.node_tag}, {', '.join(_num(v) for v in values)})")

    trapezoid_tags = {load.element_tag for load in model.element_loads if not load.is_uniform}
    for load in model.element_loads:
        if load.element_tag in trapezoid_tags and not load.is_uniform:
            _write_trapezoid_eleload(lines, load)
        else:
            lines.append(
                f"ops.eleLoad('-ele', {load.element_tag}, '-type', '-beamUniform', "
                f"{_num(load.wy)}, {_num(load.wx)})"
            )
    lines.append("")


def _write_trapezoid_eleload(lines: list[str], load: UniformElementLoad) -> None:
    segments = _TRAPEZOID_SEGMENTS
    for segment in range(segments):
        sub_tag = _TRAPEZOID_ELEMENT_TAG_OFFSET + load.element_tag * 1000 + segment
        midpoint = (segment + 0.5) / segments
        wy_mid = load.wy + (load.wy_j - load.wy) * midpoint
        wx_mid = load.wx + (load.wx_j - load.wx) * midpoint
        lines.append(
            f"ops.eleLoad('-ele', {sub_tag}, '-type', '-beamUniform', "
            f"{_num(wy_mid)}, {_num(wx_mid)})"
        )
