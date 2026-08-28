"""Shared fixtures/helpers for 3D hinge buckling diagnostics (Phase 2-F.1).

Read-only with respect to product code - builds models and inspects OpenSeesPy
topology the same way the canvas exporter and buckling solver already do.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

import numpy as np
import openseespy.opensees as ops

from openframe.core.domain import BoundaryCondition, Element, Node, NodalLoad, StructuralModel
from openframe.core.domain.results import AnalysisStatus
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver
from openframe.features.analysis.statics.solver import _released_and_rigid_nodes
from openframe.infrastructure.opensees.buckling_solver import run_buckling_analysis
from openframe.infrastructure.opensees.script_execution import run_model_script

#: Same section set as test_buckling_3d_export.py - weak-axis Iy governs Euler check.
FRAME_PROPERTIES_3D = {
    "E": 200.0e6,
    "A": 0.02,
    "G": 77.0e6,
    "J": 2.0e-6,
    "Iy": 6.0e-5,
    "Iz": 8.0e-5,
}
CANTILEVER_LENGTH = 4.0
CANTILEVER_ELEMENTS = 4


class BucklingFailureStage(StrEnum):
    COMPLETED = "completed"
    K_MATERIAL = "k_material"
    MECHANISM = "mechanism"
    K_LOADED = "k_loaded"
    K_GEOMETRIC = "k_geometric"
    EIGENVALUE = "eigenvalue"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class HingeTopology:
    """Tags and zeroLength records emitted for one built model."""

    node_tags: tuple[int, ...]
    element_tags: tuple[int, ...]
    fixed_nodes: tuple[int, ...]
    zero_length_calls: tuple[str, ...]
    orphaned_rotation_fixes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BucklingAttempt:
    stage: BucklingFailureStage
    message: str
    buckling_load_factor: float | None = None


@dataclass(frozen=True, slots=True)
class StiffnessDiagnostics:
    system_size: int
    zero_eigenvalue_count: int
    min_eigenvalue: float
    zero_energy_modes: tuple[str, ...]


def vertical_cantilever(
    *,
    release_i: bool = False,
    release_j: bool = False,
    local_axis_angle: float = 0.0,
    offset_i: tuple[float, float, float] = (0.0, 0.0, 0.0),
    n_elements: int = CANTILEVER_ELEMENTS,
) -> StructuralModel:
    length = CANTILEVER_LENGTH
    nodes = {
        index + 1: Node(index + 1, 0.0, 0.0, length * index / n_elements)
        for index in range(n_elements + 1)
    }
    elements: dict[int, Element] = {}
    for index in range(n_elements):
        kwargs: dict = {"properties": FRAME_PROPERTIES_3D}
        if index == 0 and release_i:
            kwargs["moment_release_i"] = True
        if index == n_elements - 1 and release_j:
            kwargs["moment_release_j"] = True
        if index == n_elements - 1 and local_axis_angle:
            kwargs["local_axis_angle"] = local_axis_angle
        if index == 0 and any(offset_i):
            kwargs["offset_i"] = offset_i
        elements[index + 1] = Element(
            index + 1,
            index + 1,
            index + 2,
            "elasticBeamColumn",
            **kwargs,
        )
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes=nodes,
        elements=elements,
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(n_elements + 1, (0.0, 0.0, -1.0, 0.0, 0.0, 0.0))],
    )


def shared_hinge_cantilever() -> StructuralModel:
    half = CANTILEVER_LENGTH / 2
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 0.0, 0.0, half),
            3: Node(3, 0.0, 0.0, CANTILEVER_LENGTH),
        },
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties=FRAME_PROPERTIES_3D,
                moment_release_j=True,
            ),
            2: Element(
                2,
                2,
                3,
                "elasticBeamColumn",
                properties=FRAME_PROPERTIES_3D,
                moment_release_i=True,
            ),
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(3, (0.0, 0.0, -1.0, 0.0, 0.0, 0.0))],
    )


def stable_portal_shared_hinge() -> StructuralModel:
    """Two fixed columns and a two-segment beam sharing a hinge at mid-span."""
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 0.0, 0.0, CANTILEVER_LENGTH),
            3: Node(3, 6.0, 0.0, 0.0),
            4: Node(4, 6.0, 0.0, CANTILEVER_LENGTH),
            5: Node(5, 3.0, 0.0, CANTILEVER_LENGTH),
        },
        elements={
            1: Element(1, 1, 2, "elasticBeamColumn", properties=FRAME_PROPERTIES_3D),
            2: Element(2, 3, 4, "elasticBeamColumn", properties=FRAME_PROPERTIES_3D),
            3: Element(
                3,
                2,
                5,
                "elasticBeamColumn",
                properties=FRAME_PROPERTIES_3D,
                moment_release_j=True,
            ),
            4: Element(
                4,
                5,
                4,
                "elasticBeamColumn",
                properties=FRAME_PROPERTIES_3D,
                moment_release_i=True,
            ),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(3, (True,) * 6),
        ],
        nodal_loads=[
            NodalLoad(2, (0.0, 0.0, -0.5, 0.0, 0.0, 0.0)),
            NodalLoad(4, (0.0, 0.0, -0.5, 0.0, 0.0, 0.0)),
        ],
    )


def euler_cantilever_pcr() -> float:
    import math

    return (
        math.pi**2
        * FRAME_PROPERTIES_3D["E"]
        * FRAME_PROPERTIES_3D["Iy"]
        / (2.0 * CANTILEVER_LENGTH) ** 2
    )


    return export_opensees_script(model, include_mass=False, length_unit="m")


def export_script(model: StructuralModel) -> str:
    return export_opensees_script(model, include_mass=False, length_unit="m")


def topology_from_script(script: str, model: StructuralModel) -> HingeTopology:
    node_tags = tuple(sorted(int(tag) for tag in re.findall(r"ops\.node\((\d+),", script)))
    fixed_nodes = tuple(sorted(int(tag) for tag in re.findall(r"ops\.fix\((\d+),", script)))
    zero_length_calls = tuple(
        line.strip()
        for line in script.splitlines()
        if "ops.element('zeroLength'" in line or 'ops.element("zeroLength"' in line
    )
    released, rigid = _released_and_rigid_nodes(model)
    orphaned = tuple(sorted(tag for tag in released if tag not in rigid))
    element_tags = tuple(
        sorted(int(tag) for tag in re.findall(r"ops\.element\('elasticBeamColumn', (\d+),", script))
    )
    return HingeTopology(
        node_tags=node_tags,
        element_tags=element_tags,
        fixed_nodes=fixed_nodes,
        zero_length_calls=zero_length_calls,
        orphaned_rotation_fixes=orphaned,
    )


def topology_from_in_process(model: StructuralModel) -> HingeTopology:
    MaterialFreeStaticsSolver._build(model, "frame")  # noqa: SLF001 - diagnostic parity check
    node_tags = tuple(sorted(int(tag) for tag in ops.getNodeTags()))
    element_tags = tuple(sorted(int(tag) for tag in ops.getEleTags()))
    fixed_nodes = tuple(sorted(int(tag) for tag in ops.getFixedNodes()))
    zero_length_calls = tuple(
        f"tag={tag} nodes={ops.eleNodes(tag)}" for tag in element_tags if len(ops.eleNodes(tag)) >= 2
    )
    released, rigid = _released_and_rigid_nodes(model)
    orphaned = tuple(sorted(tag for tag in released if tag not in rigid))
    ops.wipe()
    return HingeTopology(
        node_tags=node_tags,
        element_tags=element_tags,
        fixed_nodes=fixed_nodes,
        zero_length_calls=zero_length_calls,
        orphaned_rotation_fixes=orphaned,
    )


def run_linear_static(model: StructuralModel) -> AnalysisStatus:
    try:
        result = MaterialFreeStaticsSolver().solve(model)
        return result.status
    finally:
        ops.wipe()


def classify_buckling_failure(message: str) -> BucklingFailureStage:
    if "기구 상태" in message:
        return BucklingFailureStage.MECHANISM
    if "무하중 상태" in message:
        return BucklingFailureStage.K_MATERIAL
    if "REFERENCE LOAD 적용 상태" in message:
        return BucklingFailureStage.K_LOADED
    if "기하강성" in message:
        return BucklingFailureStage.K_GEOMETRIC
    if "유효한 양의 실수 좌굴" in message:
        return BucklingFailureStage.EIGENVALUE
    return BucklingFailureStage.OTHER


def attempt_buckling(model: StructuralModel) -> BucklingAttempt:
    with tempfile.TemporaryDirectory() as tmp_dir:
        source = Path(tmp_dir) / "model.py"
        source.write_text(export_script(model), encoding="utf-8")
        try:
            result = run_buckling_analysis(
                source,
                geometric_transform_type="PDelta",
                num_modes=1,
            )
            factor = result["buckling_modes"][0]["buckling_load_factor"]
            return BucklingAttempt(
                stage=BucklingFailureStage.COMPLETED,
                message="completed",
                buckling_load_factor=factor,
            )
        except RuntimeError as error:
            return BucklingAttempt(stage=classify_buckling_failure(str(error)), message=str(error))
        finally:
            ops.wipe()


def stiffness_diagnostics(model: StructuralModel) -> StiffnessDiagnostics:
    """Mirror buckling_solver's FullGeneral zero-load K extraction and inspect rank."""
    run_model_script(_write_temp_script(model))
    ops.wipeAnalysis()
    ops.system("FullGeneral")
    ops.numberer("RCM")
    ops.constraints("Transformation")
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 0.0)
    ops.analysis("Static")
    ops.analyze(1)
    size = ops.systemSize()
    matrix = np.array(ops.printA("-ret"), dtype=float).reshape(size, size)
    symmetric = (matrix + matrix.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    floor = 1.0e-6 * max(float(np.max(np.abs(eigenvalues))), 1.0)
    zero_indices = [index for index, value in enumerate(eigenvalues) if abs(value) <= floor]
    dof_names = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
    modes: list[str] = []
    for index in zero_indices[:4]:
        vector = eigenvectors[:, index]
        parts: list[str] = []
        for tag in sorted(int(value) for value in ops.getNodeTags()):
            equations = [int(value) for value in ops.nodeDOFs(tag)]
            for dof_index, equation in enumerate(equations):
                if equation >= 0 and abs(vector[equation]) > 0.15:
                    parts.append(f"n{tag}:{dof_names[dof_index]}={vector[equation]:+.2f}")
        modes.append("; ".join(parts) if parts else f"mode@{index}")
    ops.wipe()
    return StiffnessDiagnostics(
        system_size=size,
        zero_eigenvalue_count=len(zero_indices),
        min_eigenvalue=float(eigenvalues.min()),
        zero_energy_modes=tuple(modes),
    )


def _write_temp_script(model: StructuralModel) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "built.py"
    tmp.write_text(export_script(model), encoding="utf-8")
    return tmp


ModelFactory = Callable[[], StructuralModel]

MINIMAL_REPRODUCTION_MODELS: dict[str, ModelFactory] = {
    "no_hinge": lambda: vertical_cantilever(),
    "top_release": lambda: vertical_cantilever(release_j=True),
    "base_release": lambda: vertical_cantilever(release_i=True),
    "both_ends": lambda: vertical_cantilever(release_i=True, release_j=True),
    "shared_hinge": shared_hinge_cantilever,
    "local_axis_angle_plus_hinge": lambda: vertical_cantilever(release_j=True, local_axis_angle=15.0),
    "offset_plus_hinge": lambda: vertical_cantilever(release_j=True, offset_i=(0.0, 0.0, 0.1)),
}
