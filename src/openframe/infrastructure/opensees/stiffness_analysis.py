"""Shared low-level OpenSees stiffness-matrix / DOF-mapping helpers.

Used identically by both the elastic buckling solver
(``infrastructure.opensees.buckling_solver``) and the instability
diagnostic (``infrastructure.opensees.instability_diagnostic``): both need
to pull the assembled tangent ``K`` out of a live OpenSees domain via
FullGeneral ``ops.printA``, map a system-equation-ordered vector back to
(node, DOF) via ``ops.nodeDOFs``, and reconstruct equalDOF/rigidDiaphragm
-tied DOF values that indexing an externally-solved eigenvector at its own
equation number does not give (verified directly - it silently comes back
0.0 for a constrained DOF; see ``correct_constrained_dof_values``).

Deliberately excludes anything whose *meaning* differs between the two
callers: buckling's K_geometric / generalized eigenproblem / eigenvalue
filtering stays in ``buckling_solver.py``; the instability diagnostic's
Jacobi (diagonal) equilibration and near-zero-mode floor policy stays in
``instability_diagnostic.py``. Only the raw matrix/DOF plumbing both
already needed, byte-for-byte, lives here.
"""

from __future__ import annotations

import numpy as np
import openseespy.opensees as ops


def extract_stiffness_matrix(size: int) -> np.ndarray:
    """Read the just-assembled tangent back from OpenSees.

    ``ops.printA("-ret")`` returns the current system matrix regardless of
    whether the preceding ``ops.analyze()`` itself converged - a singular or
    non-converged solve still leaves a valid assembled tangent behind, which
    is exactly what both buckling and the instability diagnostic read after
    a deliberately failing/zero-load analyze step.
    """
    flat = ops.printA("-ret")
    matrix = np.asarray(flat, dtype=float).reshape(size, size)
    if not np.all(np.isfinite(matrix)):
        raise RuntimeError("강성행렬에 NaN/Inf 값이 있습니다. 모델 상태를 확인하세요.")
    return matrix


def symmetrize(matrix: np.ndarray) -> np.ndarray:
    """``(K + K.T) / 2`` - FullGeneral's assembled tangent carries roundoff
    asymmetry that would otherwise push a symmetric eigensolver (``eigh``/
    ``eigvalsh``, which assume exact symmetry and silently only look at one
    triangle) into a subtly wrong spectrum."""
    return (matrix + matrix.T) / 2.0


def node_dof_equations(node_tags: list[int]) -> dict[int, list[int]]:
    """(node tag) -> its DOFs' system equation numbers, straight from
    ``ops.nodeDOFs`` - a restrained DOF's equation number comes back
    negative (OpenSeesPy returns -1)."""
    return {tag: [int(value) for value in ops.nodeDOFs(tag)] for tag in node_tags}


def translational_count(ndm: int, ndf: int) -> int:
    return min(3 if ndm == 3 else 2, ndf)


def mode_shape_from_eigenvector(
    eigenvector: np.ndarray,
    node_tags: list[int],
    dof_equations: dict[int, list[int]],
    system_size: int,
) -> dict[int, list[float]]:
    """Map a system-equation-ordered eigenvector back to per-node DOF
    components using ``ops.nodeDOFs`` - a restrained DOF's equation number is
    negative, and is reported as displacement 0.0 rather than indexed into
    the vector."""
    shape: dict[int, list[float]] = {}
    for tag in node_tags:
        equations = dof_equations[tag]
        shape[tag] = [
            float(eigenvector[equation]) if 0 <= equation < system_size else 0.0
            for equation in equations
        ]
    return shape


#: Which perpendicular-axis rigidDiaphragm (see ops.rigidDiaphragm(perpDirn, ...))
#: a constrained node's tied-DOF set implies - OpenSees always ties exactly the
#: two in-plane translations plus the one rotation about perpDirn, so the DOF
#: set alone identifies it unambiguously (1-indexed DOF numbers: 1=Ux, 2=Uy,
#: 3=Uz, 4=Rx, 5=Ry, 6=Rz). There is no ops getter for perpDirn itself.
_RIGID_DIAPHRAGM_DOF_PATTERNS: dict[frozenset[int], int] = {
    frozenset({2, 3, 4}): 1,
    frozenset({1, 3, 5}): 2,
    frozenset({1, 2, 6}): 3,
}


def _apply_rigid_diaphragm_offset(
    constrained_tag: int,
    master_tag: int,
    perp_dirn: int,
    shape: dict[int, list[float]],
    node_coordinates: dict[int, tuple[float, float, float]],
) -> None:
    """Standard rigid-body rotation relation ``u_c = u_r + omega x (r_c - r_r)``
    - verified against a real OpenSeesPy static solve (imposed SP displacement
    at the retained node) for all three perpDirn values before being trusted
    here; see the buckling-feature memory for the exact check."""
    master = shape[master_tag]
    constrained = shape[constrained_tag]
    dx, dy, dz = (
        node_coordinates[constrained_tag][axis] - node_coordinates[master_tag][axis]
        for axis in range(3)
    )
    if perp_dirn == 3:
        rotation = master[5]
        constrained[0] = master[0] - dy * rotation
        constrained[1] = master[1] + dx * rotation
        constrained[5] = rotation
    elif perp_dirn == 1:
        rotation = master[3]
        constrained[1] = master[1] - dz * rotation
        constrained[2] = master[2] + dy * rotation
        constrained[3] = rotation
    else:  # perp_dirn == 2
        rotation = master[4]
        constrained[0] = master[0] + dz * rotation
        constrained[2] = master[2] - dx * rotation
        constrained[4] = rotation


def correct_constrained_dof_values(
    node_tags: list[int],
    shape: dict[int, list[float]],
    ndm: int,
) -> bool:
    """Overwrite equalDOF/rigidDiaphragm-constrained node DOF values in
    ``shape`` in place - ``ops.nodeDOFs()`` reports a real (non-negative)
    equation number for a constrained DOF under the Transformation constraint
    handler both callers use, but indexing an *externally* solved eigenvector
    at that equation does not give this node's own physical value the way
    ``ops.nodeDisp()`` does after a real ``ops.analyze()`` (verified - it
    silently came back exactly 0.0 for every constrained DOF before this
    fix). ``ops.getConstrainedDOFs``/``ops.getRetainedNodes`` (real OpenSeesPy
    introspection, not guessed at) identify what needs correcting:

    - A rigidDiaphragm's constrained node ties exactly two in-plane
      translations plus the one rotation about perpDirn - corrected via the
      exact rigid-body relation (see ``_apply_rigid_diaphragm_offset``).
    - Anything else (equalDOF, or a rigidDiaphragm rotation DOF standing
      alone) is a direct dof-to-dof tie with coefficient 1.0 - the
      constrained DOF simply copies its retained node's same-index value,
      exact for equalDOF by definition (``ops.equalDOF`` applies the same
      dof list to both nodes).

    Returns whether any constrained node was found at all.
    """
    found_any = False
    for tag in node_tags:
        constrained_dofs = [int(dof) for dof in ops.getConstrainedDOFs(tag)]
        if not constrained_dofs:
            continue
        retained_nodes = ops.getRetainedNodes(tag)
        if not retained_nodes:
            continue
        found_any = True
        master_tag = int(retained_nodes[0])
        if master_tag not in shape or tag not in shape:
            continue
        perp_dirn = (
            _RIGID_DIAPHRAGM_DOF_PATTERNS.get(frozenset(constrained_dofs)) if ndm == 3 else None
        )
        if perp_dirn is not None:
            coordinates = {
                node_tag: tuple(
                    (*[float(v) for v in ops.nodeCoord(node_tag)], 0.0, 0.0)[:3]
                )
                for node_tag in (tag, master_tag)
            }
            _apply_rigid_diaphragm_offset(tag, master_tag, perp_dirn, shape, coordinates)
            continue
        master_shape = shape[master_tag]
        constrained_shape = shape[tag]
        for dof in constrained_dofs:
            index = dof - 1
            if 0 <= index < len(constrained_shape) and index < len(master_shape):
                constrained_shape[index] = master_shape[index]
    return found_any


def normalize_mode_shape(
    raw_shape: dict[int, list[float]], ndm: int
) -> dict[int, list[float]]:
    """Scale so the largest-magnitude *translational* component is 1.0 - or,
    if every translational component is ~0 (e.g. a mode that only shows up as
    rotation), the largest-magnitude component of any kind. The vector's
    sign is arbitrary either way; this never attempts to pick a "positive"
    direction."""
    max_translational = 0.0
    for components in raw_shape.values():
        count = translational_count(ndm, len(components))
        for value in components[:count]:
            max_translational = max(max_translational, abs(value))
    if max_translational > 1.0e-12:
        scale = 1.0 / max_translational
    else:
        max_any = max(
            (abs(value) for components in raw_shape.values() for value in components),
            default=0.0,
        )
        scale = 1.0 / max_any if max_any > 1.0e-12 else 1.0
    return {tag: [value * scale for value in components] for tag, components in raw_shape.items()}
