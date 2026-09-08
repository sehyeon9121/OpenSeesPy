"""Load compiler force/moment conservation and conservative backend capabilities."""

from __future__ import annotations

import copy
import math
import subprocess
import sys
from dataclasses import replace

import pytest

from openframe.core.domain.geometric_transform import GeometricTransform
from openframe.core.domain.load_entry import (
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoadEntry,
    SelfWeightEntry,
)
from openframe.core.domain.model import (
    Element,
    LoadCaseKind,
    NodalLoad,
    Node,
    PointElementLoad,
    StructuralModel,
    UniformElementLoad,
)
from openframe.core.domain.surfaces import WallPanel
from openframe.features.analysis.loads import (
    LoadCompileError,
    LoadHandling,
    compile_loads,
    element_load_handling,
    member_local_axes,
)
from openframe.features.analysis.loads.compiler import LEGACY_BEAM_SEGMENTS
from openframe.features.model.surfaces.rectangular_mesh import assemble_wall_meshes


def line_model(ndm=2, kind="truss", end=(10.0, 0.0, 0.0), behavior="truss", angle=0.0):
    return StructuralModel(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes={1: Node(1, 0, 0, 0), 2: Node(2, *end)},
        elements={
            1: Element(
                1,
                1,
                2,
                kind,
                properties={"behavior": behavior, "A": 0.2, "density": 25.0},
                local_axis_angle=angle,
            )
        },
    )


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def resultant(model, plan):
    force, moment = [0.0] * 3, [0.0] * 3
    for load in plan.nodal_loads:
        node = model.nodes[load.node_tag]
        arm = cross((node.x, node.y, node.z), load.force)
        for k in range(3):
            force[k] += load.force[k]
            moment[k] += arm[k] + load.moment[k]
    return tuple(force), tuple(moment)


@pytest.mark.parametrize(
    "a,b,w1,w2",
    [
        (0, 1, -3, -3),
        (0, 1, -2, -8),
        (0.2, 0.7, -4, -4),
        (0.2, 0.7, -2, -8),
        (0.1, 0.8, -5, 5),
        (0, 1, 0, -6),
    ],
)
def test_truss_distributed_resultant_and_first_moment(a, b, w1, w2):
    model = line_model()
    model.element_loads = [UniformElementLoad(1, wy=w1, wy_j=w2, xL1=a, xL2=b)]
    plan = compile_loads(model)
    assert not plan.element_loads
    assert len(plan.nodal_loads) == 2
    length = 10.0
    d = (b - a) * length
    expected_force = d * (w1 + w2) / 2
    expected_moment = a * length * expected_force + d * d * (w1 + 2 * w2) / 6
    force, moment = resultant(model, plan)
    assert force == pytest.approx((0, expected_force, 0), abs=1e-12)
    assert moment == pytest.approx((0, 0, expected_moment), abs=1e-12)
    assert all(load.moment == (0, 0, 0) for load in plan.nodal_loads)
    if expected_force:
        assert moment[2] / force[1] == pytest.approx(expected_moment / expected_force)


@pytest.mark.parametrize("kind", ["elasticBeamColumn", "dispBeamColumn"])
def test_beam_subdivision_keeps_exact_full_segment_bounds(kind):
    model = line_model(kind=kind)
    model.element_loads.append(UniformElementLoad(1, wy=-2, wy_j=-6))
    plan = compile_loads(model)
    assert len(plan.element_loads) == 40
    assert all((load.start_ratio, load.end_ratio) == (0.0, 1.0) for load in plan.element_loads)
    assert sum(load.components[1] * 10 / 40 for load in plan.element_loads) == pytest.approx(-40)


def test_full_trapezoid_individual_shape_function_forces():
    model = line_model()
    model.element_loads = [UniformElementLoad(1, wy=2, wy_j=8)]
    plan = compile_loads(model)
    assert plan.nodal_loads[0].force[1] == pytest.approx(10 * (2 * 2 + 8) / 6)
    assert plan.nodal_loads[1].force[1] == pytest.approx(10 * (2 + 2 * 8) / 6)


@pytest.mark.parametrize(
    "kind,behavior",
    [
        ("Truss", "truss"),
        ("corotTruss", "cable"),
        ("truss", "tension_only"),
        ("corotTruss", "compression_only"),
        ("trussSection", "truss"),
    ],
)
def test_all_existing_truss_families_are_nodal(kind, behavior):
    from openframe.features.analysis.statics.solver import _element_family

    model = line_model(kind=kind, behavior=behavior)
    assert _element_family(kind) == "truss"
    model.element_loads = [UniformElementLoad(1, wy=-3)]
    plan = compile_loads(model)
    assert not plan.element_loads
    assert resultant(model, plan)[0][1] == pytest.approx(-30)
    assert bool(plan.warnings) == (behavior in {"cable", "tension_only"})
    if plan.warnings:
        assert plan.warnings[0].code == "cable_sag_not_represented"
        assert plan.warnings[0].source.element_tag == 1


@pytest.mark.parametrize(
    "ndm,end,direction,axis",
    [
        (2, (6, 8, 0), "y", 1),
        (3, (3, 4, 12), "z", 2),
    ],
)
def test_global_partial_entry_preserves_spatial_resultant_and_moment(ndm, end, direction, axis):
    model = line_model(ndm=ndm, end=end, angle=37)
    length = math.dist((0, 0, 0), end)
    entry = LoadEntry(
        12,
        "G",
        "member_partial",
        (1,),
        MemberDistributedLoadEntry(
            coordinate_system="global",
            direction=direction,
            start_value=-2,
            end_value=-8,
            start_position=0.2 * length,
            end_position=0.7 * length,
            position_unit="length",
        ),
        hidden=True,
    )
    plan = compile_loads(model, entries=[entry])
    d = 0.5 * length
    total = -5 * d
    first = 0.2 * length * total + d * d * (-2 - 16) / 6
    expected_force = [0, 0, 0]
    expected_force[axis] = total
    first_vector = [0, 0, 0]
    first_vector[axis] = first
    expected_moment = cross(tuple(v / length for v in end), first_vector)
    assert resultant(model, plan)[0] == pytest.approx(expected_force, abs=1e-12)
    assert resultant(model, plan)[1] == pytest.approx(expected_moment, abs=1e-12)
    assert all(
        load.source.entry_id == 12 and load.source.case_id == "G" for load in plan.nodal_loads
    )


def test_local_rolled_direction_and_existing_axes_agree():
    from openframe.features.model.presentation.canvas_model_build import _local_axes

    for endpoint in ((4, 0, 0), (0, 0, 4), (3, 4, 12)):
        model = line_model(ndm=3, end=endpoint, angle=90)
        actual = member_local_axes(model, model.elements[1])
        expected = _local_axes(model.elements[1], model.nodes, 3)
        for a, b in zip(actual, expected):
            assert a == pytest.approx(b, abs=1e-12)
    model = line_model(ndm=3, end=(4, 0, 0), angle=90)
    model.element_loads = [UniformElementLoad(1, wy=3)]
    force, moment = resultant(model, compile_loads(model))
    assert force == pytest.approx((0, 0, 12), abs=1e-12)
    assert moment == pytest.approx((0, -24, 0), abs=1e-12)


def test_imported_reference_vector_is_reused_without_double_roll():
    model = line_model(ndm=3, end=(4, 0, 0), angle=90)
    model.elements[1] = replace(model.elements[1], transf_tag=7)
    model.geometric_transforms[7] = GeometricTransform(7, "Linear", (0, 1, 0))
    model.element_loads = [UniformElementLoad(1, wy=3)]
    assert resultant(model, compile_loads(model))[0] == pytest.approx((0, 0, -12))


@pytest.mark.parametrize(
    "ndm,end,factors",
    [
        (2, (6, 8, 0), (0, -1, 0)),
        (3, (3, 4, 12), (0.2, 0, -1)),
    ],
)
def test_truss_self_weight_uses_unit_weight_without_extra_g(ndm, end, factors):
    model = line_model(ndm=ndm, end=end)
    payload = SelfWeightEntry(*factors)
    plan = compile_loads(model, self_weight=payload, gravity_acceleration=1234)
    weight = 25 * 0.2 * math.dist((0, 0, 0), end)
    expected = tuple(weight * v for v in factors)
    assert resultant(model, plan)[0] == pytest.approx(expected)
    assert resultant(model, plan)[1] == pytest.approx(cross(tuple(v / 2 for v in end), expected))
    for load in plan.nodal_loads:
        assert load.force == pytest.approx(tuple(v / 2 for v in expected))


def wall_model(nx=1, ny=1):
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 1, 2, 3, 6),
            2: Node(2, 5, 2, 3, 6),
            3: Node(3, 5, 4, 3, 6),
            4: Node(4, 1, 4, 3, 6),
        },
        walls={1: WallPanel(1, 1, 2, 3, 4, 0.2, nx, ny, 3e7, 0.2, density=2.5)},
    )
    return assemble_wall_meshes(model)


@pytest.mark.parametrize("nx,ny", [(1, 1), (2, 3)])
def test_shell_weight_force_moment_and_mesh_independence(nx, ny):
    model = wall_model(nx, ny)
    plan = compile_loads(model, self_weight=SelfWeightEntry(), gravity_acceleration=9.81)
    weight = 2.5 * 0.2 * 8 * 9.81
    assert not plan.element_loads
    assert len(plan.nodal_loads) == nx * ny * 4
    force, moment = resultant(model, plan)
    assert force == pytest.approx((0, 0, -weight))
    assert moment == pytest.approx(cross((3, 3, 3), force))
    assert all(load.force[2] == pytest.approx(-weight / (nx * ny * 4)) for load in plan.nodal_loads)


def test_shell_weight_requires_explicit_model_unit_gravity():
    with pytest.raises(LoadCompileError, match="gravity_required"):
        compile_loads(wall_model(), self_weight=SelfWeightEntry())


def test_mixed_model_weight_uses_distinct_density_conventions():
    model = wall_model()
    # Mesher's shell tag is 1; line members use distinct tags.
    model.elements = {
        10: Element(10, 1, 2, "frame", {"A": 0.3, "density": 25}),
        11: Element(11, 4, 3, "corotTruss", {"A": 0.1, "density": 78.5, "behavior": "cable"}),
    }
    plan = compile_loads(model, self_weight=SelfWeightEntry(), gravity_acceleration=9.81)
    assert len(plan.element_loads) == 1
    beam = plan.element_loads[0]
    assert beam.target.element_tag == 10
    assert beam.components == pytest.approx((0, 0, -7.5))
    shell_and_truss = resultant(model, plan)[0][2]
    assert shell_and_truss + beam.components[2] * 4 == pytest.approx(
        -(2.5 * 0.2 * 8 * 9.81 + 78.5 * 0.1 * 4 + 25 * 0.3 * 4)
    )
    selected = compile_loads(
        model, self_weight=SelfWeightEntry(apply_to_all=False, target_elements=(11, 11))
    )
    assert len(selected.nodal_loads) == 2


@pytest.mark.parametrize("ndm", [2, 3])
def test_beam_uniform_partial_and_point_match_existing_engine_call_values(ndm, monkeypatch):
    from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver, ops

    model = line_model(ndm=ndm, kind="frame")
    model.element_loads = [
        UniformElementLoad(1, wx=2, wy=-4, wz=3 if ndm == 3 else 0, xL1=0.2, xL2=0.8)
    ]
    model.point_loads = [PointElementLoad(1, position=0.3, n=2, py=-7, pz=4 if ndm == 3 else 0)]
    recorded = []
    monkeypatch.setattr(ops, "eleLoad", lambda *args: recorded.append(args))
    monkeypatch.setattr(ops, "timeSeries", lambda *args: None)
    monkeypatch.setattr(ops, "pattern", lambda *args: None)
    MaterialFreeStaticsSolver._apply_loads(model, "frame")
    plan = compile_loads(model)
    uniform, point = plan.element_loads
    wx, wy, wz = uniform.components
    n, py, pz = point.components
    assert recorded[0] == (
        "-ele",
        1,
        "-type",
        "-beamUniform",
        *((wy, wz, wx) if ndm == 3 else (wy, wx)),
        0.2,
        0.8,
    )
    assert recorded[1] == (
        "-ele",
        1,
        "-type",
        "-beamPoint",
        *((py, pz, 0.3, n) if ndm == 3 else (py, 0.3, n)),
    )
    assert (uniform.start_ratio, uniform.end_ratio) == (0.2, 0.8)
    assert point.position == 0.3
    assert not plan.required_subdivisions


def test_beam_legacy_trapezoid_and_all_companion_loads_share_subdivision():
    from openframe.features.analysis.statics.solver import _TRAPEZOID_SEGMENTS

    assert LEGACY_BEAM_SEGMENTS == _TRAPEZOID_SEGMENTS
    model = line_model(kind="frame")
    model.element_loads = [
        UniformElementLoad(1, wy=-2, wy_j=-8),
        UniformElementLoad(1, wy=-1, xL1=0.2, xL2=0.6),
    ]
    model.point_loads = [PointElementLoad(1, position=0.4, py=-9)]
    plan = compile_loads(model, self_weight=SelfWeightEntry(factor_y=-1, factor_z=0))
    assert plan.required_subdivisions == ((1, 40),)
    assert all(load.target.segment_index is not None for load in plan.element_loads)
    triangle = plan.element_loads[:40]
    for index, load in enumerate(triangle):
        assert load.components[1] == pytest.approx(-2 - 6 * (index + 0.5) / 40)
    assert sum(load.components[1] * 10 / 40 for load in triangle) == pytest.approx(-50)
    approximate_moment = sum(
        load.components[1] * (10 / 40) * (i + 0.5) * (10 / 40) for i, load in enumerate(triangle)
    )
    assert approximate_moment == pytest.approx(10**2 * (-2 + 2 * (-8)) / 6, rel=0.001)
    partial = [
        load for load in plan.element_loads if load.kind == "uniform" and load.components[1] == -1
    ]
    assert sum(
        (load.end_ratio - load.start_ratio) * 10 / 40 * load.components[1] for load in partial
    ) == pytest.approx(-4)
    point = next(load for load in plan.element_loads if load.kind == "point")
    a, b = point.target.source_span
    assert (a + point.position * (b - a)) * 10 == pytest.approx(4)
    assert any(w.code == "beam_trapezoid_midpoint_approximation" for w in plan.warnings)


def test_beam_self_weight_matches_existing_projection():
    from types import SimpleNamespace

    from openframe.features.model.presentation.canvas_model_build import _ModelBuildMixin

    model = line_model(ndm=3, kind="elasticBeamColumn", end=(3, 4, 12), angle=23)
    state = SimpleNamespace(include_self_weight=True, ndm=3, nodes=model.nodes)
    old = _ModelBuildMixin._self_weight_local(state, model.elements[1])
    plan = compile_loads(model, self_weight=SelfWeightEntry())
    assert plan.element_loads[0].components == pytest.approx(old)


def test_metadata_is_preserved_and_inputs_are_not_mutated():
    model = line_model()
    model.nodal_loads = [NodalLoad(1, (2, 3, 4), pattern_tag=8, case_type=LoadCaseKind.DEAD)]
    model.element_loads = [UniformElementLoad(1, wy=-4, pattern_tag=9, case_type=LoadCaseKind.LIVE)]
    before = copy.deepcopy(model)
    entry = LoadEntry(4, "A", "nodal", (2,), NodalLoadEntry(fx=8))
    plan = compile_loads(model, entries=[entry])
    assert model == before
    assert plan == compile_loads(model, entries=[entry])
    assert plan.nodal_loads[0].source.pattern_tag == 8
    assert plan.nodal_loads[0].moment == (0, 0, 4)
    assert plan.nodal_loads[-1].source.pattern_tag == 9
    assert any(load.source.entry_id == 4 for load in plan.nodal_loads)


@pytest.mark.parametrize("kind", ["distributed", "point"])
def test_shell_never_receives_beam_native_load(kind):
    model = wall_model()
    tag = next(iter(model.shell_quads))
    assert element_load_handling(model.shell_quads[tag], kind) == LoadHandling.UNSUPPORTED
    if kind == "distributed":
        model.element_loads = [UniformElementLoad(tag, wy=-1)]
    else:
        model.point_loads = [PointElementLoad(tag, py=-1)]
    with pytest.raises(LoadCompileError, match="unsupported_load"):
        compile_loads(model)


@pytest.mark.parametrize("a,b", [(-0.1, 1), (0, 1.1), (0.8, 0.2), (0.3, 0.3), (float("nan"), 1)])
def test_invalid_load_spans_fail_explicitly(a, b):
    model = line_model()
    model.element_loads = [UniformElementLoad(1, wy=-2, xL1=a, xL2=b)]
    with pytest.raises(LoadCompileError):
        compile_loads(model)


@pytest.mark.parametrize(
    "problem",
    ["missing_node", "zero_length", "missing_target", "nan", "unknown_element", "missing_density"],
)
def test_invalid_input_is_not_silently_omitted(problem):
    model = line_model()
    model.element_loads = [UniformElementLoad(1, wy=-2)]
    kwargs = {}
    if problem == "missing_node":
        del model.nodes[2]
    elif problem == "zero_length":
        model.nodes[2] = replace(model.nodes[2], x=0)
    elif problem == "missing_target":
        model.element_loads = [UniformElementLoad(999, wy=-2)]
    elif problem == "nan":
        model.element_loads = [UniformElementLoad(1, wy=float("nan"))]
    elif problem == "unknown_element":
        model.elements[1] = replace(model.elements[1], element_type="zeroLength")
    elif problem == "missing_density":
        model.elements[1].properties.pop("density")
        kwargs["self_weight"] = SelfWeightEntry(factor_y=-1, factor_z=0)
    with pytest.raises(LoadCompileError):
        compile_loads(model, **kwargs)


@pytest.mark.parametrize(
    "case",
    [
        "3d_trapezoid",
        "partial_beam_trapezoid",
        "corotational",
        "partial_disp",
        "warped_shell",
        "unmeshed_shell",
        "bad_axis",
    ],
)
def test_unsupported_native_combinations_raise(case):
    model = line_model(kind="frame")
    kwargs = {}
    model.element_loads = [UniformElementLoad(1, wy=-2)]
    if case == "3d_trapezoid":
        model.ndm = 3
        model.element_loads = [UniformElementLoad(1, wy=-2, wy_j=-4)]
    elif case == "partial_beam_trapezoid":
        model.element_loads = [UniformElementLoad(1, wy=-2, wy_j=-4, xL1=0.2)]
    elif case == "corotational":
        model.ndm = 3
        model.elements[1] = replace(model.elements[1], transf_tag=3)
        model.geometric_transforms[3] = GeometricTransform(3, "Corotational", (0, 0, 1))
    elif case == "partial_disp":
        model.elements[1] = replace(model.elements[1], element_type="dispBeamColumn")
        model.element_loads = [UniformElementLoad(1, wy=-2, xL1=0.2)]
    elif case in {"warped_shell", "unmeshed_shell"}:
        model = wall_model()
        kwargs = {"self_weight": SelfWeightEntry(), "gravity_acceleration": 9.81}
        if case == "warped_shell":
            model.nodes[3] = replace(model.nodes[3], z=5)
        else:
            model.shell_quads = {}
    elif case == "bad_axis":
        model = line_model(ndm=3)
        model.elements[1] = replace(model.elements[1], transf_tag=3)
        model.geometric_transforms[3] = GeometricTransform(3, "Linear", (1, 0, 0))
        model.element_loads = [UniformElementLoad(1, wy=-2)]
    with pytest.raises(LoadCompileError):
        compile_loads(model, **kwargs)


def test_truss_point_load_also_avoids_native_beam_command():
    model = line_model()
    entry = LoadEntry(1, "Q", "member_point", (1,), MemberPointLoadEntry(value=-5, position=0.3))
    plan = compile_loads(model, entries=[entry])
    assert not plan.element_loads
    assert resultant(model, plan) == ((0, -5, 0), (0, 0, -15))


def test_compiler_import_does_not_import_engine_or_gui():
    code = """
import sys
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('openseespy', 'PySide6')):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from openframe.features.analysis.loads import compile_loads
from openframe.core.domain.model import StructuralModel
assert not compile_loads(StructuralModel()).element_loads
"""
    process = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize("ndm", [2, 3])
def test_beam_plan_matches_exporter_uniform_and_point_commands(ndm):
    import ast

    from openframe.features.analysis.statics.opensees_script_export import _write_loads

    model = line_model(ndm=ndm, kind="elasticBeamColumn")
    model.element_loads = [UniformElementLoad(1, wx=2, wy=-4, wz=3 if ndm == 3 else 0)]
    model.point_loads = [PointElementLoad(1, position=0.3, n=2, py=-7, pz=4 if ndm == 3 else 0)]
    lines = []
    _write_loads(lines, model)
    calls = [
        tuple(ast.literal_eval(arg) for arg in node.args)
        for node in ast.walk(ast.parse("\n".join(lines)))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "eleLoad"
    ]
    uniform, point = compile_loads(model).element_loads
    wx, wy, wz = uniform.components
    axial, py, pz = point.components
    assert calls[0][4:] == ((wy, wz, wx) if ndm == 3 else (wy, wx))
    assert calls[1][4:] == (
        (py, pz, point.position, axial) if ndm == 3 else (py, point.position, axial)
    )
    assert uniform.start_ratio == 0 and uniform.end_ratio == 1


@pytest.mark.parametrize("kind", ["member_uniform", "member_linear", "member_partial"])
def test_entry_and_legacy_distributed_inputs_share_identical_integration(kind):
    model = line_model()
    entry = LoadEntry(
        1,
        "Q",
        kind,
        (1,),
        MemberDistributedLoadEntry(
            start_value=-2,
            end_value=-7,
            start_position=0.2,
            end_position=0.8,
        ),
    )
    from_entry = compile_loads(model, entries=[entry])
    model.element_loads = [UniformElementLoad(1, wy=-2, wy_j=-7, xL1=0.2, xL2=0.8)]
    from_model = compile_loads(model)
    for a, b in zip(from_entry.nodal_loads, from_model.nodal_loads):
        assert a.node_tag == b.node_tag
        assert a.force == pytest.approx(b.force)


def test_self_weight_load_entry_preserves_case_and_target_provenance():
    model = line_model()
    entry = LoadEntry(
        9,
        "DEAD",
        "self_weight",
        (),
        SelfWeightEntry(
            factor_y=-1.25,
            factor_z=0,
            apply_to_all=False,
            target_elements=(1,),
        ),
    )
    plan = compile_loads(model, entries=[entry])
    assert resultant(model, plan)[0] == pytest.approx((0, -62.5, 0))
    assert all(
        load.source.case_id == "DEAD" and load.source.entry_id == 9 for load in plan.nodal_loads
    )


def test_unit_conversion_preserves_line_and_shell_physical_weight():
    from openframe.core.domain.units import UnitSystem, unit_conversion_factors

    factors = unit_conversion_factors(UnitSystem("kN", "m"), UnitSystem("N", "mm"))
    model = line_model(ndm=3, end=(3, 4, 12))
    original = compile_loads(model, self_weight=SelfWeightEntry())
    changed = copy.deepcopy(model)
    changed.nodes = {
        tag: replace(
            node, x=node.x * factors.length, y=node.y * factors.length, z=node.z * factors.length
        )
        for tag, node in model.nodes.items()
    }
    changed.elements[1].properties["density"] *= factors.unit_weight
    changed.elements[1].properties["A"] *= factors.area
    converted = compile_loads(changed, self_weight=SelfWeightEntry())
    assert resultant(changed, converted)[0][2] == pytest.approx(
        resultant(model, original)[0][2] * factors.force
    )
    shell = wall_model()
    shell_before = compile_loads(shell, self_weight=SelfWeightEntry(), gravity_acceleration=9.81)
    shell.nodes = {
        tag: replace(
            node, x=node.x * factors.length, y=node.y * factors.length, z=node.z * factors.length
        )
        for tag, node in shell.nodes.items()
    }
    wall = shell.walls[1]
    # Mass/volume in coherent F,L,T units scales as F*T²/L⁴, unlike unit weight F/L³.
    shell.walls[1] = replace(
        wall,
        thickness=wall.thickness * factors.length,
        density=wall.density * factors.force / factors.length**4,
    )
    shell_after = compile_loads(
        shell, self_weight=SelfWeightEntry(), gravity_acceleration=9.81 * factors.length
    )
    assert resultant(shell, shell_after)[0][2] == pytest.approx(
        sum(load.force[2] for load in shell_before.nodal_loads) * factors.force
    )


@pytest.mark.parametrize(
    "field,value",
    [("direction", "north"), ("coordinate_system", "screen"), ("position_unit", "percent")],
)
def test_invalid_entry_direction_and_units_raise(field, value):
    payload = replace(MemberDistributedLoadEntry(start_value=-1, end_value=-1), **{field: value})
    with pytest.raises(LoadCompileError):
        compile_loads(line_model(), entries=[LoadEntry(1, "Q", "member_uniform", (1,), payload)])


@pytest.mark.parametrize("gravity", [0, -9.81, float("nan"), float("inf")])
def test_invalid_shell_gravity_raises(gravity):
    with pytest.raises(LoadCompileError):
        compile_loads(wall_model(), self_weight=SelfWeightEntry(), gravity_acceleration=gravity)


def test_no_silent_local_nodal_frame_or_tag_collision():
    with pytest.raises(LoadCompileError, match="nodal_local_axes"):
        compile_loads(
            line_model(),
            entries=[
                LoadEntry(1, "Q", "nodal", (1,), NodalLoadEntry(coordinate_system="local", fx=1))
            ],
        )
    model = wall_model()
    tag = next(iter(model.shell_quads))
    model.elements[tag] = Element(tag, 1, 2, "truss")
    with pytest.raises(LoadCompileError, match="element_tag_collision"):
        compile_loads(model)
