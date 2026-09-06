"""0-stage spike: can this venv's OpenSeesPy actually solve an ASDShellQ4 wall?

Not a product feature. WallPanel, StructuralModel, mesher, UI and the
statics solver are deliberately not imported - a failure here must mean
the engine cannot host the shell, not that OpenFrame wiring is wrong.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import openseespy.opensees as ops
import pytest

# Concrete-scale elastic wall in metres / kN (same force-length pair the 3D
# frame examples already use: E in kN/m^2).
_LW = 2.0
_H = 3.0
_THICKNESS = 0.2
_E = 30_000_000.0  # 30 GPa
_NU = 0.2
_P = 100.0  # kN, +X, in-plane, spread along the top edge


@dataclass(frozen=True, slots=True)
class _MeshSolve:
    nx: int
    ny: int
    shell_count: int
    free_dof: int
    top_ux: float
    base_rx: float
    top_disp_6: tuple[float, ...]


def _section_call() -> None:
    ops.section("ElasticMembranePlateSection", 1, _E, _NU, _THICKNESS, 0.0)


def _node_tag(ix: int, iz: int, nx: int) -> int:
    return iz * (nx + 1) + ix + 1


def _build_wall(nx: int, ny: int) -> None:
    """Structured quads in the XZ plane: width along X, height along Z.

    Node winding is n1-n2-n3-n4 CCW when looking along +Y from the origin
    (bottom-left, bottom-right, top-right, top-left) so the shell normal
    is consistent on every element. Local-x is forced along +X (the wall
    width) rather than leaving ASDShellQ4 to pick edge 1-2 per quad.
    """
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for iz in range(ny + 1):
        for ix in range(nx + 1):
            ops.node(
                _node_tag(ix, iz, nx),
                ix * _LW / nx,
                0.0,
                iz * _H / ny,
            )
    for ix in range(nx + 1):
        ops.fix(_node_tag(ix, 0, nx), 1, 1, 1, 1, 1, 1)

    _section_call()
    ele = 1
    for iz in range(ny):
        for ix in range(nx):
            n1 = _node_tag(ix, iz, nx)
            n2 = _node_tag(ix + 1, iz, nx)
            n3 = _node_tag(ix + 1, iz + 1, nx)
            n4 = _node_tag(ix, iz + 1, nx)
            ops.element("ASDShellQ4", ele, n1, n2, n3, n4, 1, "-local", 1.0, 0.0, 0.0)
            ele += 1

    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    top_nodes = [_node_tag(ix, ny, nx) for ix in range(nx + 1)]
    share = _P / len(top_nodes)
    for tag in top_nodes:
        ops.load(tag, share, 0.0, 0.0, 0.0, 0.0, 0.0)

    ops.system("BandGeneral")
    ops.numberer("RCM")
    ops.constraints("Plain")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")


def _mean_top_ux(nx: int, ny: int) -> tuple[float, tuple[float, ...]]:
    top_nodes = [_node_tag(ix, ny, nx) for ix in range(nx + 1)]
    samples = [ops.nodeDisp(tag) for tag in top_nodes]
    ux = sum(row[0] for row in samples) / len(samples)
    return ux, tuple(float(value) for value in samples[len(samples) // 2])


def _base_reaction_x(nx: int) -> float:
    ops.reactions()
    return sum(ops.nodeReaction(_node_tag(ix, 0, nx), 1) for ix in range(nx + 1))


def _solve(nx: int, ny: int) -> _MeshSolve:
    _build_wall(nx, ny)
    try:
        status = ops.analyze(1)
        assert status == 0, f"analyze returned {status} for {nx}x{ny}"
        top_ux, mid_top = _mean_top_ux(nx, ny)
        assert math.isfinite(top_ux)
        for value in mid_top:
            assert math.isfinite(value)
        n_nodes = (nx + 1) * (ny + 1)
        n_fixed = nx + 1
        return _MeshSolve(
            nx=nx,
            ny=ny,
            shell_count=nx * ny,
            free_dof=(n_nodes - n_fixed) * 6,
            top_ux=top_ux,
            base_rx=_base_reaction_x(nx),
            top_disp_6=mid_top,
        )
    finally:
        ops.wipe()


def _beam_tip_estimates() -> tuple[float, float, float]:
    """Order-of-magnitude cantilever: in-plane I = t Lw^3/12, As = 5/6 A."""
    inertia = _THICKNESS * _LW**3 / 12.0
    bending = _P * _H**3 / (3.0 * _E * inertia)
    shear_modulus = _E / (2.0 * (1.0 + _NU))
    shear_area = (5.0 / 6.0) * _LW * _THICKNESS
    shear = _P * _H / (shear_modulus * shear_area)
    return bending, shear, bending + shear


def test_asdshellq4_and_elastic_membrane_plate_section_exist() -> None:
    ops.wipe()
    try:
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0.0, 0.0, 0.0)
        ops.node(2, 1.0, 0.0, 0.0)
        ops.node(3, 1.0, 0.0, 1.0)
        ops.node(4, 0.0, 0.0, 1.0)
        _section_call()
        ops.element("ASDShellQ4", 1, 1, 2, 3, 4, 1)
    finally:
        ops.wipe()


def test_2x2_cantilever_wall_solves_in_equilibrium() -> None:
    result = _solve(2, 2)

    assert result.shell_count == 4
    assert result.top_ux > 0.0
    # Reactions oppose the applied +X load. Equality here is equilibrium,
    # not mesh accuracy - a coarse mesh that is still in balance will pass.
    assert result.base_rx == pytest.approx(-_P, rel=1e-6, abs=1e-6)
    assert len(result.top_disp_6) == 6


def test_cantilever_wall_mesh_refines_toward_a_stable_top_displacement() -> None:
    meshes = [(1, 1), (2, 2), (4, 4), (8, 8)]
    solves = [_solve(nx, ny) for nx, ny in meshes]
    bending, shear, beam_total = _beam_tip_estimates()

    print("\nASDShellQ4 cantilever spike (Lw=2 H=3 t=0.2 E=30GPa P=100kN +X)")
    print(f"beam  PH^3/3EI={bending:.6e}  PH/GAs={shear:.6e}  sum={beam_total:.6e} m")
    print(f"{'mesh':>8} {'n_ele':>6} {'freeDOF':>8} {'top UX (m)':>14} {'dUX/prev':>12}")
    previous: float | None = None
    relative_changes: list[float] = []
    for item in solves:
        if previous is None or previous == 0.0:
            change = float("nan")
        else:
            change = abs(item.top_ux - previous) / abs(previous)
            relative_changes.append(change)
        change_text = "-" if math.isnan(change) else f"{change:.4f}"
        print(
            f"{item.nx}x{item.ny} {item.shell_count:6d} {item.free_dof:8d} "
            f"{item.top_ux:14.6e} {change_text:>12}"
        )
        previous = item.top_ux

    finest = solves[-1]
    assert finest.top_ux > 0.0
    # Same order of magnitude as the Timoshenko cantilever, not a tight
    # identity: the shell has Poisson spreading and a distributed top load.
    assert 0.1 * beam_total < finest.top_ux < 10.0 * beam_total
    assert relative_changes[-1] < relative_changes[0]
    for item in solves:
        assert math.isfinite(item.top_ux)
        for value in item.top_disp_6:
            assert math.isfinite(value)
        assert len(item.top_disp_6) == 6
