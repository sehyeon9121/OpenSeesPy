"""Final Beam + Truss + Wall/Shell load-pipeline integration proof."""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from openframe.core.domain import (
    AnalysisRequest,
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    SelfWeightEntry,
    StructuralModel,
    UniformElementLoad,
    WallPanel,
)
from openframe.features.analysis.loads import compile_loads
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver
from openframe.features.model.surfaces import assemble_wall_meshes
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

_G = 9.81
_BEAM_PROPERTIES = {
    "E": 200.0e6,
    "A": 0.02,
    "G": 77.0e6,
    "J": 2.0e-5,
    "Iy": 6.0e-5,
    "Iz": 8.0e-5,
    "density": 5.0,  # line-member unit weight, not mass density
}
_TRUSS_PROPERTIES = {"E": 200.0e6, "A": 0.01, "density": 4.0}


def _mixed_model() -> StructuralModel:
    """A wall cantilever sharing its top/bottom mid-nodes with beam and brace."""
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 2.0, 0.0, 3.0, 6),
            4: Node(4, 0.0, 0.0, 3.0, 6),
            5: Node(5, 1.0, 0.0, 3.0, 6),
            6: Node(6, 4.0, 0.0, 3.0, 6),
            7: Node(7, 1.0, 0.0, 0.0, 6),
        },
        elements={
            20: Element(
                20,
                5,
                6,
                "elasticBeamColumn",
                properties=dict(_BEAM_PROPERTIES),
            ),
            21: Element(21, 7, 6, "truss", properties=dict(_TRUSS_PROPERTIES)),
        },
        walls={
            1: WallPanel(
                1,
                1,
                2,
                3,
                4,
                thickness=0.2,
                nx=2,
                ny=1,
                elastic_modulus=30.0e6,
                poisson_ratio=0.2,
                density=2.5,  # shell mass density; compiler applies g once
            )
        },
        boundaries=[
            BoundaryCondition(tag, (True, True, True, True, True, True)) for tag in (1, 2, 7)
        ],
        nodal_loads=[NodalLoad(6, (0.0, 0.0, -5.0, 0.0, 0.0, 0.0))],
        element_loads=[
            # Horizontal beam local z is global z.
            UniformElementLoad(20, wz=-2.0),
            # Partial axial load on the 45-degree truss, preserving force and moment.
            UniformElementLoad(21, wx=-1.0, xL1=0.2, xL2=0.8),
        ],
    )


def _force_sum(plan, model: StructuralModel) -> tuple[float, float, float]:
    total = [0.0, 0.0, 0.0]
    for load in plan.nodal_loads:
        for index, value in enumerate(load.force):
            total[index] += value
    # This model's only native load is the full-span beam load/self-weight.
    # Convert it solely for the independent E2E balance assertion; adapters
    # still consume the native record and never recompute it.
    for load in plan.element_loads:
        assert load.kind == "uniform"
        element = model.elements[load.target.element_tag]
        start, end = model.nodes[element.node_i], model.nodes[element.node_j]
        length = math.dist((start.x, start.y, start.z), (end.x, end.y, end.z))
        # Member 20 is along global x: local z equals global z and local y equals global y.
        total[0] += load.components[0] * length
        total[1] += load.components[1] * length
        total[2] += load.components[2] * length
    return tuple(total)


def test_mixed_shell_self_weight_plan_has_exact_once_loads_and_shared_node_accumulation():
    model = assemble_wall_meshes(_mixed_model())
    plan = compile_loads(
        model,
        self_weight=SelfWeightEntry(),
        gravity_acceleration=_G,
    )

    shell_tags = set(model.shell_quads)
    shell_loads = [load for load in plan.nodal_loads if load.source.element_tag in shell_tags]
    shell_force = sum(load.force[2] for load in shell_loads)
    assert shell_force == pytest.approx(-2.5 * 0.2 * 6.0 * _G)
    # The two quads share nodes 5 and 7. Each contributes A/4 independently,
    # and the adapters accumulate both ops.load calls in the same load pattern.
    assert sum(load.node_tag == 5 for load in shell_loads) == 2
    assert sum(load.node_tag == 7 for load in shell_loads) == 2

    assert plan.required_subdivisions == ()
    assert len([load for load in plan.nodal_loads if load.source.origin == "nodal"]) == 1
    assert len([load for load in plan.element_loads if load.source.origin == "distributed"]) == 1
    assert len([load for load in plan.element_loads if load.source.origin == "self_weight"]) == 1
    expected_z = -(5.0 + 6.0 + 1.8 + 5.0 * 0.02 * 3.0 + 4.0 * 0.01 * math.sqrt(18.0) + 29.43)
    assert _force_sum(plan, model)[2] == pytest.approx(expected_z)


def test_mixed_beam_truss_shell_self_weight_matches_export_and_equilibrium(tmp_path: Path):
    self_weight = SelfWeightEntry()
    in_memory_model = deepcopy(_mixed_model())
    exported_model = deepcopy(_mixed_model())

    in_memory = MaterialFreeStaticsSolver().solve(
        in_memory_model,
        self_weight=self_weight,
        gravity_acceleration=_G,
    )
    script = export_opensees_script(
        exported_model,
        self_weight=self_weight,
        gravity_acceleration=_G,
    )
    source = tmp_path / "mixed_beam_truss_shell.py"
    source.write_text(script, encoding="utf-8")
    exported = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=source))

    assert in_memory.status == AnalysisStatus.COMPLETED, in_memory.messages
    assert exported.status == AnalysisStatus.COMPLETED, exported.messages

    applied = _force_sum(
        compile_loads(
            in_memory_model,
            self_weight=self_weight,
            gravity_acceleration=_G,
        ),
        in_memory_model,
    )
    reactions = tuple(
        sum(in_memory.node_results[tag].reaction[dof] for tag in (1, 2, 7)) for dof in range(3)
    )
    assert tuple(a + r for a, r in zip(applied, reactions)) == pytest.approx(
        (0.0, 0.0, 0.0), abs=1.0e-8
    )
    assert abs(in_memory.element_results[21].local_forces[6]) > 1.0e-6

    for tag in (1, 2, 5, 6, 7):
        assert exported.node_results[tag].reaction == pytest.approx(
            in_memory.node_results[tag].reaction, rel=1.0e-8, abs=1.0e-8
        )
        assert exported.node_results[tag].displacement == pytest.approx(
            in_memory.node_results[tag].displacement, rel=1.0e-8, abs=1.0e-10
        )
    for tag in (20, 21):
        assert exported.element_results[tag].local_forces == pytest.approx(
            in_memory.element_results[tag].local_forces, rel=1.0e-8, abs=1.0e-8
        )


def test_required_subdivision_plan_is_compiled_once_per_adapter_and_applied_once():
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties={"E": 200.0e6, "A": 0.02, "I": 8.0e-5},
            )
        },
        boundaries=[BoundaryCondition(1, (True, True, True))],
        element_loads=[UniformElementLoad(1, wy=-2.0, wy_j=-6.0)],
    )

    with patch(
        "openframe.features.analysis.statics.solver.compile_loads",
        wraps=compile_loads,
    ) as in_memory_compile:
        result = MaterialFreeStaticsSolver().solve(deepcopy(model))
    assert result.status == AnalysisStatus.COMPLETED, result.messages
    assert in_memory_compile.call_count == 1

    with patch(
        "openframe.features.analysis.statics.opensees_script_export.compile_loads",
        wraps=compile_loads,
    ) as exporter_compile:
        script = export_opensees_script(deepcopy(model))
    assert exporter_compile.call_count == 1
    assert script.count("ops.eleLoad(") == 40


def _mixed_frame_truss_portal() -> StructuralModel:
    """A 3D portal (two "frame"-typed columns + a "frame" beam) braced by one
    diagonal "truss" member - the exact element_type naming
    (``"frame"``/``"truss"``, not ``"elasticBeamColumn"``) the 3D canvas
    (``canvas_geometry.py``'s ``add_member``) actually stamps on a drawn
    member, unlike ``_mixed_model()`` above which uses the raw OpenSees
    element name and also carries a wall. Regression coverage for a report
    that a canvas-drawn truss+frame mix with self-weight or a UDL on the
    frame member failed to solve at all - reproduction attempts (real
    exported project file, several hand-built ``StructuralModel`` variants,
    and canvas-drawn variants with a mid-span node on the frame member (see
    ``test_3d_free_form_modeling.py``'s
    ``test_mixed_truss_and_frame_3d_model_with_a_mid_span_node_solves_under_self_weight``
    / ``..._under_a_udl``) all completed successfully against this branch's
    load compiler, so these two tests pin that down as a regression guard.
    """
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 5.0, 0.0, 0.0),
            3: Node(3, 5.0, 0.0, 4.0),
            4: Node(4, 0.0, 0.0, 4.0),
        },
        elements={
            1: Element(1, 1, 4, "frame", properties=dict(_BEAM_PROPERTIES)),  # column
            2: Element(2, 2, 3, "frame", properties=dict(_BEAM_PROPERTIES)),  # column
            3: Element(3, 4, 3, "frame", properties=dict(_BEAM_PROPERTIES)),  # beam
            4: Element(4, 1, 3, "truss", properties=dict(_TRUSS_PROPERTIES)),  # brace
        },
        boundaries=[
            BoundaryCondition(1, (True, True, True, True, True, True)),
            BoundaryCondition(2, (True, True, True, True, True, True)),
        ],
    )


def test_mixed_truss_and_frame_3d_model_solves_with_self_weight_enabled():
    model = _mixed_frame_truss_portal()

    result = MaterialFreeStaticsSolver().solve(
        model, self_weight=SelfWeightEntry(), gravity_acceleration=_G
    )

    assert result.status == AnalysisStatus.COMPLETED, result.messages
    # Total upward reaction must balance the model's own self-weight - beam
    # unit weight (density * A) is already a force/length, so no extra g.
    column_weight = 2 * _BEAM_PROPERTIES["density"] * _BEAM_PROPERTIES["A"] * 4.0
    beam_weight = _BEAM_PROPERTIES["density"] * _BEAM_PROPERTIES["A"] * 5.0
    brace_length = math.dist((0.0, 0.0, 0.0), (5.0, 0.0, 4.0))
    brace_weight = _TRUSS_PROPERTIES["density"] * _TRUSS_PROPERTIES["A"] * brace_length
    expected_total_weight = column_weight + beam_weight + brace_weight
    total_reaction_z = sum(result.node_results[tag].reaction[2] for tag in (1, 2))
    assert total_reaction_z == pytest.approx(expected_total_weight, rel=1.0e-9)


def test_mixed_truss_and_frame_3d_model_solves_with_a_udl_on_the_frame_member():
    model = _mixed_frame_truss_portal()
    model.element_loads = [UniformElementLoad(3, wz=-5.0, wz_j=-5.0)]  # UDL on the beam

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED, result.messages
    total_reaction_z = sum(result.node_results[tag].reaction[2] for tag in (1, 2))
    assert total_reaction_z == pytest.approx(5.0 * 5.0, rel=1.0e-9)  # w * span
