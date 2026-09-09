"""Export a hand-drawn 2D or 3D canvas model as a runnable OpenSeesPy script.

The canvas's own solvers (``MaterialFreeStaticsSolver``, ``ModalStaticsSolver``)
run in-process and cover determinate statics and eigenvalue analysis, but stop
there - nonlinear static (real Newton-Raphson, incremental pushover), modal,
buckling, time history and response spectrum for the 3D canvas all live only in
the "OpenSeesPy 파일 불러오기" pipeline (``infrastructure/opensees/*_solver.py``),
which expects a plain ``.py`` script it can execute in a subprocess. This module
is the bridge: it writes the exact same model - nodes, supports (including
inclined ones in 2D or 3D, springs, 3D rigid diaphragms), sections, hinges,
rigid end offsets, loads (including trapezoidal ones in 2D), and optionally
lumped mass - as script text, reusing the already-validated techniques
``solver.py`` uses in-process (inclined-support zero-length springs, trapezoid
discretization, hinge releases, 3D ``-jntOffset``/``vecxz`` geomTransf) instead
of re-deriving them. Every 3D technique here is ported 1:1 from
``MaterialFreeStaticsSolver``'s own ``ndm == 3`` branches - see
``tests/integration/test_opensees_script_export.py``, which round-trips the
exported script through a real subprocess and checks it against that same
in-process solver's own result.

3D lumped-plasticity (pushover) hinges are deliberately NOT ported here - Pushover
keeps running entirely in-process (``MaterialFreeStaticsSolver.solve_nonlinear_
static``), so this exporter only ever emits the elastic release form of a 3D
hinge.

The generated script only *builds* the model - no analysis commands - matching
what ``run_model_script`` (script_execution.py) expects and needs: it suppresses
the analysis stage anyway, so anything here would be inert, but leaving it out
keeps the file honest about what it does.
"""

import math

from openframe.core.domain.geometric_transform import boundary_local_axes
from openframe.core.domain.load_entry import SelfWeightEntry
from openframe.core.domain.model import (
    BoundaryCondition,
    Element,
    StructuralModel,
)
from openframe.features.analysis.loads import CompiledLoadPlan, ElementLoadTarget, compile_loads
from openframe.features.analysis.statics.solver import (
    _HINGE_MATERIAL_TAG,
    _HINGE_STIFFNESS,
    _INCLINED_SUPPORT_MATERIAL_TAG,
    _INCLINED_SUPPORT_STIFFNESS,
    _SPRING_TAG_OFFSET,
    _UNIDIRECTIONAL_FY_STRAIN_MULTIPLE,
    MaterialFreeStaticsSolver,
    _element_behavior,
    _element_family,
    _hinge_local_axes,
    _orphan_joint_nodes_for_rotation_pin,
    _orphan_joint_rotation_fix_pattern,
    _reference_vector,
    _released_and_rigid_nodes,
    _truss_gap_strain,
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
_TRUSS_INIT_STRAIN_TAG_OFFSET = 9_200_000


def export_opensees_script(
    model: StructuralModel,
    *,
    include_mass: bool = False,
    length_unit: str = "m",
    self_weight: SelfWeightEntry | None = None,
    gravity_acceleration: float | None = None,
    nonlinear_2d: bool = False,
) -> str:
    """Return a runnable OpenSeesPy script text for ``model``.

    Raises ``ValueError`` (Korean message, matching this codebase's other
    solver-facing errors) if the model cannot be exported meaningfully: not 2D
    or 3D, empty, missing real section/material properties anywhere, or (3D
    only) carrying a trapezoidal element load - see this module's own
    docstring for why that last one is still rejected. Unlike the canvas's own
    determinate solver, there is no unit-placeholder fallback here - a script
    meant to feed a real nonlinear/modal/time-history run is only as
    trustworthy as the stiffness values it carries.

    ``self_weight`` and ``gravity_acceleration`` have the same meaning as on
    ``MaterialFreeStaticsSolver.solve`` and are passed to the same compiler.
    """
    if model.ndm not in (2, 3):
        raise ValueError("현재 2D 또는 3D 모델만 OpenSeesPy 스크립트로 내보낼 수 있습니다.")
    if nonlinear_2d and model.ndm != 2:
        raise ValueError("2D Pushover 내보내기는 2D 모델만 지원합니다.")
    if not model.nodes or (not model.elements and not model.walls):
        raise ValueError("절점과 부재를 먼저 작성하세요.")

    if model.walls:
        from openframe.features.model.surfaces.rectangular_mesh import assemble_wall_meshes

        if model.ndm != 3:
            raise ValueError("전단벽은 3D 모델에서만 지원합니다.")
        assemble_wall_meshes(model)

    missing = sorted(
        element.tag
        for element in model.elements.values()
        if _element_properties(element, model.ndm) is None
    )
    if missing:
        listed = ", ".join(str(tag) for tag in missing)
        needs_inertia = any(
            _element_family(model.elements[tag].element_type) != "truss" for tag in missing
        )
        if needs_inertia:
            needed = "E/A/G/J/Iy/Iz" if model.ndm == 3 else "E/A/I"
        else:
            needed = "E/A"
        raise ValueError(
            f"부재 {listed}에 재료·단면({needed})이 입력되지 않았습니다. 정밀 해석으로 "
            "내보내려면 모든 부재에 실제 강성이 필요합니다."
        )

    # Compile once, before any element is written: _write_elements() needs
    # plan.required_subdivisions to decide which 2D beams get the legacy
    # 40-segment trapezoid mesh, and _write_loads() below consumes the same
    # plan - see solver.py's identical ordering (its own in-process twin of
    # this function) for why. ``self_weight`` is an alternative source for
    # callers that have not already expanded self-weight into model loads;
    # this is required for ShellQuad gravity, which is compiled only after
    # the WallPanel mesh exists above. LoadCompileError is a ValueError, so
    # it surfaces through this function's own existing
    # "raise ValueError(...)" contract unchanged - no new except needed by
    # any caller. Modal/Buckling/Time History/Response Spectrum all export
    # through this same function with no static load at all (an eigenvalue
    # problem needs none) - skip the compiler entirely rather than run it
    # over empty input on every such export.
    plan = (
        compile_loads(
            model,
            self_weight=self_weight,
            gravity_acceleration=gravity_acceleration,
        )
        if model.nodal_loads or model.element_loads or model.point_loads or self_weight is not None
        else CompiledLoadPlan()
    )

    lines: list[str] = [
        "import openseespy.opensees as ops",
        "",
        # Read literally (never executed) by OpenSeesModelImporter to tell a
        # canvas-authored model apart from a hand-authored/third-party import
        # - see model_importer.py's _apply_model_origin, which is the only
        # consumer of this declaration.
        "OPENFRAME_MODEL_ORIGIN = 'direct'",
        "",
        "ops.wipe()",
        f"ops.model('basic', '-ndm', {model.ndm}, '-ndf', {model.ndf})",
        "",
    ]

    for node in sorted(model.nodes.values(), key=lambda item: item.tag):
        coordinates = (node.x, node.y) if model.ndm == 2 else (node.x, node.y, node.z)
        lines.append(f"ops.node({node.tag}, {', '.join(_num(v) for v in coordinates)})")
    lines.append("")

    required_subdivisions = frozenset(tag for tag, _count in plan.required_subdivisions)
    _write_boundaries(lines, model)
    _write_springs(lines, model)
    if model.ndm == 3:
        _write_rigid_diaphragms(lines, model)
    _write_elements(lines, model, required_subdivisions, nonlinear_2d=nonlinear_2d)
    _write_shells(lines, model)
    if include_mass:
        _write_mass(lines, model, length_unit)
    _write_loads(lines, plan, model.ndm, model.ndf)

    return "\n".join(lines) + "\n"


def _element_properties(element: Element, ndm: int) -> tuple[float, ...] | None:
    if _element_family(element.element_type) == "truss":
        try:
            return (float(element.properties["E"]), float(element.properties["A"]))
        except (KeyError, TypeError, ValueError):
            return None
    if ndm == 3:
        return MaterialFreeStaticsSolver._element_material_3d(element)
    return MaterialFreeStaticsSolver._element_material(element)


def _num(value: float) -> str:
    """Shortest text that reads back as the exact same float - ``repr`` is the
    only builtin formatter Python guarantees round-trips (since 3.1)."""
    return repr(float(value))


def _write_boundaries(lines: list[str], model: StructuralModel) -> None:
    ndm = model.ndm
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
    angle (about ``condition.angle_axis``), so only the restrained local
    direction(s) actually resist motion. ``restraints[i]`` maps onto
    zeroLength local direction ``i + 1`` for every ``i`` up to ``ndf`` - see
    ``_fix_inclined``'s own docstring for why this is a strict
    generalisation of the original 2D-only special case."""
    node = model.nodes[condition.node_tag]
    ground_tag = 9_000_000 + condition.node_tag
    vector_x, vector_y = boundary_local_axes(condition.angle, condition.angle_axis)
    materials: list[int] = []
    directions: list[int] = []
    for index in range(min(len(condition.restraints), ndf)):
        if condition.restraints[index]:
            materials.append(_INCLINED_SUPPORT_MATERIAL_TAG)
            directions.append(index + 1)
    if not directions:
        return
    ground_coordinates = (
        (_num(node.x), _num(node.y)) if model.ndm == 2 else (_num(node.x), _num(node.y), _num(node.z))
    )
    lines.append(f"ops.node({ground_tag}, {', '.join(ground_coordinates)})")
    lines.append(f"ops.fix({ground_tag}, {', '.join('1' for _ in range(ndf))})")
    material_args = ", ".join(str(tag) for tag in materials)
    direction_args = ", ".join(str(value) for value in directions)
    orient_args = ", ".join(_num(value) for value in (*vector_x, *vector_y))
    lines.append(
        f"ops.element('zeroLength', {ground_tag}, {ground_tag}, {condition.node_tag}, "
        f"'-mat', {material_args}, '-dir', {direction_args}, '-orient', {orient_args})"
    )


def _write_springs(lines: list[str], model: StructuralModel) -> None:
    """Text form of ``MaterialFreeStaticsSolver._apply_springs``: the same
    ground-node + zeroLength trick ``_write_inclined_support`` uses, but
    axis-aligned (no ``-orient`` needed) and with a real stiffness per DOF
    instead of one shared rigid constant. Ndm-generic - matches the in-process
    solver, which calls this unconditionally for both 2D and 3D - but only
    ever emits anything for a boundary that actually carries
    ``spring_stiffnesses`` (Story Manager's own feature, 3D-only in practice
    today), so no existing 2D model's exported script changes."""
    ndm = model.ndm
    ndf = model.ndf
    material_tag = _SPRING_TAG_OFFSET
    wrote_any = False
    for condition in model.boundaries:
        active = [
            (dof_index, stiffness)
            for dof_index, stiffness in enumerate(condition.spring_stiffnesses[:ndf])
            if stiffness
            and not (dof_index < len(condition.restraints) and condition.restraints[dof_index])
        ]
        if not active:
            continue
        wrote_any = True
        node = model.nodes[condition.node_tag]
        ground_tag = _SPRING_TAG_OFFSET + condition.node_tag
        coordinates = (node.x, node.y) if ndm == 2 else (node.x, node.y, node.z)
        lines.append(f"ops.node({ground_tag}, {', '.join(_num(v) for v in coordinates)})")
        lines.append(f"ops.fix({ground_tag}, {', '.join('1' for _ in range(ndf))})")
        materials: list[int] = []
        directions: list[int] = []
        for dof_index, stiffness in active:
            material_tag += 1
            lines.append(f"ops.uniaxialMaterial('Elastic', {material_tag}, {_num(stiffness)})")
            materials.append(material_tag)
            directions.append(dof_index + 1)
        mat_args = ", ".join(str(tag) for tag in materials)
        dir_args = ", ".join(str(value) for value in directions)
        lines.append(
            f"ops.element('zeroLength', {ground_tag}, {ground_tag}, {condition.node_tag}, "
            f"'-mat', {mat_args}, '-dir', {dir_args})"
        )
    if wrote_any:
        lines.append("")


def _write_rigid_diaphragms(lines: list[str], model: StructuralModel) -> None:
    """Text form of the 3D-only ``ops.rigidDiaphragm(...)`` call
    ``MaterialFreeStaticsSolver._build`` makes for each ``RigidDiaphragm``
    (Story Manager)."""
    if not model.rigid_diaphragms:
        return
    for diaphragm in model.rigid_diaphragms:
        slave_args = ", ".join(str(tag) for tag in diaphragm.slave_tags)
        lines.append(
            f"ops.rigidDiaphragm({diaphragm.perp_dirn}, {diaphragm.master_tag}, {slave_args})"
        )
    lines.append("")


def _write_elements(
    lines: list[str], model: StructuralModel, required_subdivisions: frozenset[int] = frozenset(),
    *, nonlinear_2d: bool = False,
) -> None:
    ndm = model.ndm
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
        elastic, area = _element_properties(element, ndm)
        base_tag = _TRUSS_MATERIAL_TAG_OFFSET + element.tag
        behavior = _element_behavior(element)
        if behavior == "compression_only":
            lines.append(f"ops.uniaxialMaterial('ENT', {base_tag}, {_num(elastic)})")
        elif behavior in ("tension_only", "cable"):
            huge_fy = elastic * _UNIDIRECTIONAL_FY_STRAIN_MULTIPLE
            gap_strain = _truss_gap_strain(model, element)
            lines.append(
                f"ops.uniaxialMaterial('ElasticPPGap', {base_tag}, {_num(elastic)}, "
                f"{_num(huge_fy)}, {_num(gap_strain)})"
            )
        elif nonlinear_2d and float(element.properties.get("Fy", 0.0)) > 0:
            fy = float(element.properties["Fy"])
            hardening = float(element.properties.get("StrainHardeningRatio", 0.02))
            if not math.isfinite(fy) or not math.isfinite(hardening) or not 0 <= hardening <= 1:
                raise ValueError(f"부재 {element.tag}: 유효한 fy와 0≤b≤1이 필요합니다.")
            lines.append(
                f"ops.uniaxialMaterial('Steel01', {base_tag}, {fy!r}, {elastic!r}, {hardening!r})"
            )
        else:
            lines.append(f"ops.uniaxialMaterial('Elastic', {base_tag}, {_num(elastic)})")
        if element.prestress != 0.0 and area > 0.0:
            # Only a prestressed member needs corotTruss's geometrically
            # nonlinear formulation + InitStrainMaterial's initial-strain
            # wrapping - a plain (unprestressed) truss keeps emitting the
            # exact same 'Truss'/'Elastic' text as before this feature
            # existed, so no existing model's exported script changes. Node
            # tags are all this needs, so it is identical in 2D and 3D.
            wrapper_tag = _TRUSS_INIT_STRAIN_TAG_OFFSET + element.tag
            init_strain = element.prestress / (elastic * area)
            lines.append(
                f"ops.uniaxialMaterial('InitStrainMaterial', {wrapper_tag}, {base_tag}, "
                f"{_num(init_strain)})"
            )
            lines.append(
                f"ops.element('corotTruss', {element.tag}, {element.node_i}, {element.node_j}, "
                f"{_num(area)}, {wrapper_tag})"
            )
        else:
            lines.append(
                f"ops.element('Truss', {element.tag}, {element.node_i}, {element.node_j}, "
                f"{_num(area)}, {base_tag})"
            )
    if truss_elements:
        lines.append("")

    if not frame_elements:
        return

    if ndm == 3:
        _write_3d_frame_elements(lines, model, frame_elements)
        return

    lines.append("ops.geomTransf('Linear', 1)")
    if nonlinear_2d:
        from openframe.features.analysis.statics.solver import _mixed_orphan_rotation_nodes

        for node_tag in _mixed_orphan_rotation_nodes(model):
            lines.append(f"ops.fix({node_tag}, 0, 0, 1)")
    for element in sorted(frame_elements, key=lambda item: item.tag):
        if element.tag in required_subdivisions:
            elastic, area, inertia = _element_properties(element, ndm)
            _write_discretized_member(
                lines, model, element, area, elastic, inertia, nonlinear_2d=nonlinear_2d
            )
            continue
        if nonlinear_2d:
            from openframe.features.analysis.statics.pushover_2d import write_frame

            write_frame(lines, model, element)
            continue
        elastic, area, inertia = _element_properties(element, ndm)
        release_code = int(element.moment_release_i) + 2 * int(element.moment_release_j)
        call = (
            f"ops.element('elasticBeamColumn', {element.tag}, {element.node_i}, "
            f"{element.node_j}, {_num(area)}, {_num(elastic)}, {_num(inertia)}, 1"
        )
        if release_code:
            call += f", '-release', {release_code}"
        lines.append(call + ")")
    lines.append("")


def _write_3d_frame_elements(
    lines: list[str], model: StructuralModel, frame_elements: list[Element]
) -> None:
    """Text form of ``MaterialFreeStaticsSolver._build``'s ``ndm == 3`` branch:
    a per-element ``geomTransf('Linear', tag, *vecxz[, '-jntOffset', ...])`` +
    ``elasticBeamColumn(A, E, G, J, Iy, Iz, transf)``, with an elastic
    zeroLength hinge (``_write_hinge``) at any released end. No trapezoid
    discretization branch here - ``MaterialFreeStaticsSolver._build`` never
    discretizes a 3D member either; a 3D trapezoidal load is instead rejected
    later, when ``_write_loads`` reaches it (matching ``_apply_loads``'s own
    ordering: the model still builds, only applying the load fails)."""
    if any(element.release_count for element in frame_elements):
        lines.append(
            f"ops.uniaxialMaterial('Elastic', {_HINGE_MATERIAL_TAG}, {_num(_HINGE_STIFFNESS)})"
        )
        # A node where every touching element releases there ends up with
        # nothing giving its own bending rotations any stiffness (each
        # released element connects to its own dummy node instead - see
        # _write_hinge) - a zero-pivot unless every unused joint rotation is
        # pinned (see _orphan_joint_rotation_fix_pattern). The duplicate node
        # still carries the physical hinge via zeroLength local dofs 5-6.
        released_ends_by_node, rigid_nodes = _released_and_rigid_nodes(model)
        for node_tag in _orphan_joint_nodes_for_rotation_pin(model):
            pattern = ", ".join(str(value) for value in _orphan_joint_rotation_fix_pattern(6))
            lines.append(f"ops.fix({node_tag}, {pattern})")
        lines.append("")

    for element in sorted(frame_elements, key=lambda item: item.tag):
        node_i = model.nodes[element.node_i]
        node_j = model.nodes[element.node_j]
        transf_tag = element.tag
        vecxz = _reference_vector(node_i, node_j, element.local_axis_angle)
        call = f"ops.geomTransf('Linear', {transf_tag}, {', '.join(_num(v) for v in vecxz)}"
        if any(element.offset_i) or any(element.offset_j):
            offset_args = ", ".join(_num(v) for v in (*element.offset_i, *element.offset_j))
            call += f", '-jntOffset', {offset_args}"
        lines.append(call + ")")

        end_i_tag = element.node_i
        end_j_tag = element.node_j
        if element.moment_release_i:
            end_i_tag = _write_hinge(
                lines, element.tag, "i", node_i, node_j, element.local_axis_angle
            )
        if element.moment_release_j:
            end_j_tag = _write_hinge(
                lines, element.tag, "j", node_i, node_j, element.local_axis_angle
            )

        elastic, area, shear, torsion, inertia_y, inertia_z = _element_properties(element, 3)
        lines.append(
            f"ops.element('elasticBeamColumn', {element.tag}, {end_i_tag}, {end_j_tag}, "
            f"{_num(area)}, {_num(elastic)}, {_num(shear)}, {_num(torsion)}, "
            f"{_num(inertia_y)}, {_num(inertia_z)}, {transf_tag})"
        )
    lines.append("")


def _write_shells(lines: list[str], model: StructuralModel) -> None:
    """Text form of ``build_shell_elements`` — same section + ASDShellQ4 calls.

    Kept here rather than inlined into ``_write_elements`` so a beam-only
    export still ends at the frame/truss loop and a wall-only export can
    emit shells with no ``elasticBeamColumn`` lines at all.
    """
    from openframe.features.analysis.statics.surfaces import shell_build_plan

    sections, elements = shell_build_plan(model)
    if not sections and not elements:
        return
    for section in sections:
        lines.append(
            "ops.section('ElasticMembranePlateSection', "
            f"{section.tag}, {_num(section.elastic_modulus)}, "
            f"{_num(section.poisson_ratio)}, {_num(section.thickness)}, "
            f"{_num(section.density)})"
        )
    for element in elements:
        lx, ly, lz = element.local_x
        lines.append(
            f"ops.element('ASDShellQ4', {element.tag}, "
            f"{element.node_1}, {element.node_2}, {element.node_3}, {element.node_4}, "
            f"{element.section_tag}, '-local', {_num(lx)}, {_num(ly)}, {_num(lz)})"
        )
    lines.append("")


def _write_hinge(
    lines: list[str],
    element_tag: int,
    end: str,
    node_i,
    node_j,
    local_axis_angle: float = 0.0,
) -> int:
    """Text form of ``MaterialFreeStaticsSolver._build_hinge`` - the elastic
    (moment-release) form only, never the lumped-plasticity Steel01 one (see
    this module's own docstring for why). A duplicate node at ``end`` plus an
    ``-orient``ed zeroLength rigid in translation/torsion (local dofs 1-4) and
    left with no assigned material - therefore free - in the two local
    bending dofs (5-6). Returns the duplicate node's tag, to be used as this
    end's node in the real ``elasticBeamColumn`` call instead of the original."""
    real_node = node_i if end == "i" else node_j
    dummy_tag = MaterialFreeStaticsSolver._hinge_node_tag(element_tag, end)
    lines.append(
        f"ops.node({dummy_tag}, {_num(real_node.x)}, {_num(real_node.y)}, {_num(real_node.z)})"
    )
    vector_x, vector_y = _hinge_local_axes(node_i, node_j, local_axis_angle)
    real_tag = node_i.tag if end == "i" else node_j.tag
    orient_args = ", ".join(_num(v) for v in (*vector_x, *vector_y))
    lines.append(
        f"ops.element('zeroLength', {dummy_tag}, {real_tag}, {dummy_tag}, "
        f"'-mat', {_HINGE_MATERIAL_TAG}, {_HINGE_MATERIAL_TAG}, {_HINGE_MATERIAL_TAG}, "
        f"{_HINGE_MATERIAL_TAG}, '-dir', 1, 2, 3, 4, '-orient', {orient_args})"
    )
    return dummy_tag


def _write_discretized_member(
    lines: list[str],
    model: StructuralModel,
    element: Element,
    area: float,
    elastic: float,
    inertia: float,
    *, nonlinear_2d: bool = False,
) -> None:
    """Text form of ``MaterialFreeStaticsSolver._build_discretized_member``:
    OpenSeesPy's ``eleLoad`` has no linearly-varying transverse load, so a
    trapezoidally-loaded member is chained from many short sub-elements, each
    carrying the true w(x) sampled at its own midpoint as a constant
    -beamUniform. Segment count/offsets match the in-process solver exactly, so
    an exported run reproduces the same numbers as solving in the canvas. 2D
    only, same as the in-process solver's own discretization - a 3D
    trapezoidal load is rejected outright instead (see this module's own
    docstring)."""
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
        if nonlinear_2d:
            from openframe.features.analysis.statics.pushover_2d import write_frame

            write_frame(
                lines, model, element, tag=sub_tag,
                node_i=node_tags[segment], node_j=node_tags[segment + 1],
                release_i=element.moment_release_i and segment == 0,
                release_j=element.moment_release_j and segment == segments - 1,
            )
            continue
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
    the standard lumped-mass frame convention. 3D adds the same mass on the
    z-translation DOF (index 3, still zero for the three rotational DOFs)."""
    ndm = model.ndm
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
            if ndm == 3:
                lines.append(
                    f"ops.mass({tag}, {_num(mass)}, {_num(mass)}, {_num(mass)}, 0.0, 0.0, 0.0)"
                )
            else:
                lines.append(f"ops.mass({tag}, {_num(mass)}, {_num(mass)}, 0.0)")
    lines.append("")


def _write_loads(lines: list[str], plan: CompiledLoadPlan, ndm: int, ndf: int) -> None:
    """Text form of ``MaterialFreeStaticsSolver._apply_loads``: consumes the
    same ``plan`` (already computed by ``compile_loads()`` before elements
    were written - see ``export_opensees_script``) rather than recomputing
    load physics here. A truss/cable member's distributed or point load was
    already converted to an equivalent nodal force by the compiler, so it
    reaches this function as a plain ``CompiledNodalLoad`` - there is no
    truss-targeted ``ops.eleLoad`` left to emit here at all, so an exported
    script can no longer silently drop a truss's distributed load the way
    OpenSees' own ``Truss::addLoad - load type unknown`` warning did before.
    """
    if not plan.nodal_loads and not plan.element_loads:
        return

    lines.append("ops.timeSeries('Linear', 1)")
    lines.append("ops.pattern('Plain', 1, 1)")
    for load in plan.nodal_loads:
        # force/moment are always GLOBAL (Fx,Fy,Fz)/(Mx,My,Mz), 2D included
        # (2D's moment is (0,0,Mz) - see CompiledNodalLoad's own docstring) -
        # so a 2D engine call needs (Fx,Fy,Mz), never a blind concatenation-
        # then-truncate of the two 3-tuples (that would keep the always-zero
        # Fz/Mx/My and drop the real Mz). Truncating further to the model's
        # own ndf reproduces the exact same drop ``model.ndf`` always applied
        # before.
        full = (
            (load.force[0], load.force[1], load.moment[2])
            if ndm == 2
            else load.force + load.moment
        )
        values = full[:ndf] + (0.0,) * max(0, ndf - len(full))
        lines.append(f"ops.load({load.node_tag}, {', '.join(_num(v) for v in values)})")

    for load in plan.element_loads:
        tag = _resolve_element_load_tag(load.target)
        wx, wy, wz = load.components
        if load.kind == "uniform":
            span_args = (
                ""
                if (load.start_ratio, load.end_ratio) == (0.0, 1.0)
                else f", {_num(load.start_ratio)}, {_num(load.end_ratio)}"
            )
            if ndm == 3:
                # wy/wz are the member's own local transverse axes, wx is
                # local axial - OpenSeesPy's own 3D -beamUniform argument
                # order (matches solver.py's _apply_loads exactly).
                lines.append(
                    f"ops.eleLoad('-ele', {tag}, '-type', '-beamUniform', "
                    f"{_num(wy)}, {_num(wz)}, {_num(wx)}{span_args})"
                )
            else:
                lines.append(
                    f"ops.eleLoad('-ele', {tag}, '-type', '-beamUniform', "
                    f"{_num(wy)}, {_num(wx)}{span_args})"
                )
            continue
        if ndm == 3:
            # (Py, Pz, xL, N) - see solver.py's own comment on this same call
            # for how the correct order was confirmed independently.
            lines.append(
                f"ops.eleLoad('-ele', {tag}, '-type', '-beamPoint', "
                f"{_num(wy)}, {_num(wz)}, {_num(load.position)}, {_num(wx)})"
            )
        else:
            lines.append(
                f"ops.eleLoad('-ele', {tag}, '-type', '-beamPoint', "
                f"{_num(wy)}, {_num(load.position)}, {_num(wx)})"
            )
    lines.append("")


def _resolve_element_load_tag(target: ElementLoadTarget) -> int:
    """The real engine element tag a compiled load's abstract target maps
    onto - the source element itself, or the deterministic sub-element tag
    ``_write_discretized_member`` mints for that (element_tag, segment_index)
    (same formula, so both functions always agree on what got built)."""
    if target.segment_index is None:
        return target.element_tag
    return _TRAPEZOID_ELEMENT_TAG_OFFSET + target.element_tag * 1000 + target.segment_index
