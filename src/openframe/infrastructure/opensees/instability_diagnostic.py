"""Diagnose why a linear-static ``ops.analyze()`` just failed, against the
live OpenSees domain that failure left behind - never a rebuild.

Promoted from the validation spike
(``tests/integration/test_instability_detection_spike.py``, now retired into
``tests/unit/test_instability_diagnostic.py`` /
``tests/integration/test_instability_diagnostic_wiring.py``), which proved
three things this module relies on:

1. **No rebuild.** In-process ``MaterialFreeStaticsSolver._build`` and
   worker/export ``export_opensees_script`` construct *different* OpenSees
   domains for the same ``StructuralModel`` (``_build`` overrides ndf for a
   pure truss - 2D truss -> 2, 3D truss -> 3 - dropping unused rotational
   DOFs and pinning orphan rotations on a mixed frame+truss joint; export
   keeps the model's own ndf and does not). Re-diagnosing with the *other*
   builder would silently diagnose a system that never actually failed. This
   module therefore only ever re-forms the *analysis object* (system/
   numberer/constraints/algorithm/integrator) against whatever domain is
   currently live in OpenSees - it never touches nodes/elements/constraints/
   releases.
2. **Diagonal (Jacobi) equilibration, not a raw relative floor.** The
   pre-existing rule elsewhere in this codebase
   (``buckling_solver._count_near_zero_stiffness_modes``:
   ``floor = max(1e-6 * max|eigenvalue|, 1e-6)``) is unit-system-sensitive -
   the *same* physical column gives a different mechanism count in m-kN vs
   N-mm units, because a raw relative floor scales with whatever units
   inflate ``max|eigenvalue|``. ``equilibrate()`` below (``Ks = D^-1 K D^-1``
   with ``D = diag(sqrt(|Kii|))``) makes every diagonal 1 and the spectrum
   dimensionless, so neither the unit system nor a penalty stiffness (e.g. a
   1e8 hinge material) can drag the floor over a genuine soft mode.
3. **Count and shape from the same equilibrated eigenpair.** A true
   mechanism's equilibrated eigenvalue sits at ~machine-eps; the softest
   observed genuine structural mode (a penalty-hinge out-of-plane mode)
   stayed >= ~1e-8 - a 6-8 order gap in every unit system, which
   ``DEFAULT_MECHANISM_TOLERANCE`` sits inside. The physical mode shape for
   a selected (near-zero) equilibrated eigenvector ``v`` is recovered as
   ``phi = Dinv * v`` (column-wise) - never a raw-K eigenvector, and never
   mixed with a differently-computed count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import openseespy.opensees as ops

from openframe.core.domain.model import StructuralModel
from openframe.core.domain.results import InstabilityDiagnosticResult, MechanismMode
from openframe.infrastructure.opensees.stiffness_analysis import (
    correct_constrained_dof_values,
    extract_stiffness_matrix,
    mode_shape_from_eigenvector,
    node_dof_equations,
    normalize_mode_shape,
    symmetrize,
)

_DOF_NAMES_3D = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
_DOF_NAMES_2D = ("Ux", "Uy", "Rz")

#: Normalized-shape magnitude a user-node DOF must exceed to be listed in a
#: MechanismMode's ``dominant_dofs`` - purely a display threshold, has no
#: bearing on mechanism classification itself.
_DOMINANT_DOF_DISPLAY_THRESHOLD = 0.15


def _diagonal_scale(matrix: np.ndarray) -> np.ndarray:
    """Dii = sqrt(|Kii|), with numerically empty diagonals replaced by 1.

    Exact 0.0 is a free mechanism DOF with no stiffness. Roundoff leftovers
    (Kii ~ n*eps*max|K|) must be treated the same: leaving Dii = sqrt(1e-20)
    makes Dinv explode and poisons the equilibrated spectrum. The floor is
    on Kii itself, not on sqrt(Kii) - otherwise 1e-20 survives as Dii=1e-10.

    A physically soft but real spring many orders above that floor is left
    alone so it does not get counted as a mechanism.
    """
    kii = np.abs(np.diag(matrix).astype(float))
    scale = float(np.max(np.abs(matrix))) if matrix.size else 1.0
    if not np.isfinite(scale) or scale == 0.0:
        scale = 1.0
    zero_floor = float(max(matrix.shape[0], 1)) * float(np.finfo(float).eps) * scale
    raw = np.sqrt(kii)
    return np.where(kii <= zero_floor, 1.0, raw)


def equilibrate(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Jacobi (diagonal) equilibration: ``Ks = D^-1 K D^-1`` with
    ``D = diag(sqrt(|Kii|))``.

    Makes the spectrum dimensionless and scale-free: every diagonal becomes
    1, so neither the unit system nor a penalty stiffness can inflate
    ``max|lambda|`` and drag a relative floor over a genuine soft mode. A
    true rigid-body/mechanism mode stays ~machine-eps; real modes become
    O(1).

    Returns ``(eigenvalues, eigenvectors, Dinv)`` from one ``eigh`` of
    ``Ks``. Physical DOF recovery for a near-zero mode is
    ``phi = Dinv * v`` (column-wise), because ``Ks v = 0 => K (Dinv . v) =
    0``. Nonzero equilibrated modes are not eigenvectors of ``K`` and must
    not be mapped that way.
    """
    diagonal = _diagonal_scale(matrix)
    dinv = 1.0 / diagonal
    scaled = (matrix * dinv[None, :]) * dinv[:, None]
    eigenvalues, eigenvectors = np.linalg.eigh(symmetrize(scaled))
    return eigenvalues, eigenvectors, dinv


#: Absolute floor in EQUILIBRATED space that separates a true mechanism/
#: rigid-body mode (observed ~1e-14..1e-16) from the softest genuine
#: structural mode observed (~1e-8, a penalty-hinge out-of-plane mode) - a
#: fixed value sits squarely in that 6-8 order gap and is unit-invariant
#: (equilibration already removed the scale). Deliberately NOT relative to
#: max|eigenvalue| - relative-to-max is exactly what a penalty stiffness or
#: unit-system change breaks (see this module's docstring).
#:
#: Isolated behind this name - and threaded through every public function
#: below as a ``tolerance`` parameter rather than a bare literal at each call
#: site - so a future spectrum-gap policy (classify by the largest ratio
#: jump in the sorted spectrum, instead of a fixed absolute value) can
#: replace it without touching any caller.
DEFAULT_MECHANISM_TOLERANCE = 1.0e-10


def physical_mechanism_modes(
    matrix: np.ndarray, tolerance: float = DEFAULT_MECHANISM_TOLERANCE
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Same eigenpairs for count and shape: indices, equilibrated
    eigenvalues, physical-space mode shapes (columns)."""
    eigenvalues, eigenvectors, dinv = equilibrate(matrix)
    index = np.flatnonzero(np.abs(eigenvalues) <= tolerance)
    physical = dinv[:, None] * eigenvectors[:, index]
    return index, eigenvalues[index], physical


def mechanism_count_equilibrated(
    matrix: np.ndarray, tolerance: float = DEFAULT_MECHANISM_TOLERANCE
) -> int:
    eigenvalues, _, _ = equilibrate(matrix)
    return int(np.sum(np.abs(eigenvalues) <= tolerance))


def _dominant_dofs(
    normalized_shape: dict[int, list[float]],
    user_node_tags: set[int],
    ndm: int,
    threshold: float = _DOMINANT_DOF_DISPLAY_THRESHOLD,
) -> tuple[str, ...]:
    dof_names = _DOF_NAMES_3D if ndm == 3 else _DOF_NAMES_2D
    parts: list[str] = []
    for tag in sorted(user_node_tags):
        components = normalized_shape.get(tag)
        if not components:
            continue
        for index, value in enumerate(components):
            if abs(value) <= threshold:
                continue
            name = dof_names[index] if index < len(dof_names) else f"d{index}"
            parts.append(f"n{tag}:{name}={value:+.2f}")
    return tuple(parts)


def _residual(matrix: np.ndarray, phi: np.ndarray) -> float:
    """``||K phi|| / (||K||_F ||phi||)`` - confirms ``phi`` (physical-space,
    ``Dinv * equilibrated eigenvector``) is actually in K's near-nullspace,
    i.e. that the D^-1 remap did not corrupt the mode. Not itself part of
    the near-zero classification."""
    denom = float(np.linalg.norm(matrix, ord="fro") * np.linalg.norm(phi)) or 1.0
    return float(np.linalg.norm(matrix @ phi)) / denom


class InstabilityDiagnosticService:
    """Diagnose why a linear-static ``ops.analyze()`` just failed, using the
    live OpenSees domain that failed run left behind.

    Callers are responsible for invoking this only while that domain is
    still alive - i.e. after a failed ``ops.analyze()`` and before any
    ``ops.wipe()``/``ops.wipeAnalysis()`` of their own. This service itself
    calls ``ops.wipeAnalysis()`` (analysis-object only: system/numberer/
    constraints/algorithm/integrator - never nodes/elements/constraints/
    loads) to install its own FullGeneral stack, matching the validated
    spike recipe exactly:

        failed analyze()
            -> ops.wipeAnalysis()
            -> FullGeneral / RCM / Transformation / Linear / LoadControl(0)
            -> ops.analyze(1)   # printA still returns the tangent even if
                                 # this itself fails - it is what actually
                                 # matters, not this call's return code
            -> assembled K extraction (ops.printA)

    The preferred entry point is ``diagnose_live()``, which does not require
    a ``StructuralModel`` and is therefore usable in the worker/export
    subprocess where no domain object is available. ``diagnose()`` delegates
    to it for backwards compatibility with in-process callers.
    """

    def diagnose_live(
        self,
        user_node_tags_allow_list: set[int] | None = None,
        ndm: int | None = None,
        *,
        constraint_handler: str = "Transformation",
        tolerance: float = DEFAULT_MECHANISM_TOLERANCE,
    ) -> InstabilityDiagnosticResult:
        """Diagnose the live OpenSees domain without needing a StructuralModel.

        ``user_node_tags_allow_list`` selects which node tags appear in each
        returned ``MechanismMode.mode_shape`` (user-facing projection).  Pass
        ``None`` to include all domain tags - correct only when the script
        does not add auxiliary nodes (hinge dummies, etc.) beyond the user's
        own geometry.  The full domain always participates in the stiffness
        extraction and eigenproblem; the allow-list affects only the
        projection.

        ``ndm`` is the model spatial dimension (2 or 3).  When ``None`` it is
        inferred from the first live node's coordinate vector.

        ``constraint_handler`` must match the handler the failed analysis used
        (so the condensed K is comparable); only ``system`` is changed to
        ``FullGeneral``.  Transformation is the correct default here because a
        Plain handler silently drops MP constraints from K, which would both
        miscount mechanisms and make ``correct_constrained_dof_values`` find
        nothing to correct.
        """
        node_tags = [int(tag) for tag in ops.getNodeTags()]
        if not node_tags:
            return InstabilityDiagnosticResult(
                message="진단할 절점이 live domain에 없습니다.",
                diagnostic_success=False,
            )

        if ndm is None:
            try:
                ndm = len(ops.nodeCoord(node_tags[0]))
            except Exception:  # noqa: BLE001
                ndm = 2

        try:
            ops.wipeAnalysis()
            ops.system("FullGeneral")
            ops.numberer("RCM")
            # Always use Transformation regardless of constraint_handler
            # argument - Plain silently drops MP constraints from K, which
            # would miscount mechanisms and break correct_constrained_dof_values.
            # The parameter is kept for caller documentation parity.
            ops.constraints("Transformation")
            ops.algorithm("Linear")
            ops.integrator("LoadControl", 0.0)
            ops.analysis("Static")
            ops.analyze(1)
            size = ops.systemSize()
            if size <= 0:
                return InstabilityDiagnosticResult(
                    message="진단용 시스템 자유도 수가 0입니다.",
                    diagnostic_success=False,
                )
            matrix = extract_stiffness_matrix(size)
        except Exception as error:  # noqa: BLE001 - a diagnostic must never itself crash solve()
            return InstabilityDiagnosticResult(
                message=f"불안정 진단 자체가 실패했습니다: {error}",
                diagnostic_success=False,
            )

        if not np.isfinite(matrix).all():
            return InstabilityDiagnosticResult(
                message="강성행렬에 NaN/Inf가 포함되어 있어 진단을 진행할 수 없습니다.",
                diagnostic_success=False,
            )
        if np.all(matrix == 0.0):
            return InstabilityDiagnosticResult(
                message="강성행렬이 영행렬입니다.",
                diagnostic_success=False,
            )

        user_tags: set[int] = (
            user_node_tags_allow_list if user_node_tags_allow_list is not None else set(node_tags)
        )
        dof_equations = node_dof_equations(node_tags)
        index, eigenvalues, physical = physical_mechanism_modes(matrix, tolerance)

        modes: list[MechanismMode] = []
        for order, eigenvalue in enumerate(eigenvalues, start=1):
            phi = physical[:, order - 1]
            raw_shape = mode_shape_from_eigenvector(phi, node_tags, dof_equations, size)
            correct_constrained_dof_values(node_tags, raw_shape, ndm)
            normalized = normalize_mode_shape(raw_shape, ndm)
            mode_shape = {
                tag: tuple(values) for tag, values in normalized.items() if tag in user_tags
            }
            modes.append(
                MechanismMode(
                    mode_number=order,
                    eigenvalue=float(eigenvalue),
                    mode_shape=mode_shape,
                    dominant_dofs=_dominant_dofs(normalized, user_tags, ndm),
                    residual=_residual(matrix, phi),
                )
            )

        count = len(modes)
        message = (
            f"구조가 불안정합니다 - 강성행렬에서 메커니즘 {count}개가 감지되었습니다."
            if count > 0
            else "강성행렬에서 메커니즘이 확인되지 않았습니다."
        )
        return InstabilityDiagnosticResult(
            mechanism_count=count,
            modes=tuple(modes),
            message=message,
            matrix_size=size,
            diagnostic_success=True,
        )

    def diagnose(
        self,
        model: StructuralModel,
        *,
        tolerance: float = DEFAULT_MECHANISM_TOLERANCE,
    ) -> InstabilityDiagnosticResult:
        """Diagnose using a live StructuralModel for the user-node allow-list.

        Delegates to ``diagnose_live()``; kept for in-process canvas callers
        that already hold a ``StructuralModel``.
        """
        return self.diagnose_live(
            user_node_tags_allow_list=set(model.nodes.keys()),
            ndm=model.ndm,
            tolerance=tolerance,
        )


def diagnose_instability(
    model: StructuralModel, *, tolerance: float = DEFAULT_MECHANISM_TOLERANCE
) -> InstabilityDiagnosticResult:
    return InstabilityDiagnosticService().diagnose(model, tolerance=tolerance)


# ---------------------------------------------------------------------------
# JSON codec
# ---------------------------------------------------------------------------


def mechanism_mode_to_json(mode: MechanismMode) -> dict[str, Any]:
    """Serialize a ``MechanismMode`` to a JSON-compatible dict.

    Type conversions:
    - ``mode_shape`` keys: ``int`` → ``str`` (JSON only allows string keys).
    - ``mode_shape`` values: ``tuple[float, ...]`` → ``list[float]``.
    - ``dominant_dofs``: ``tuple[str, ...]`` → ``list[str]``.
    """
    return {
        "mode_number": mode.mode_number,
        "eigenvalue": mode.eigenvalue,
        "mode_shape": {str(k): list(v) for k, v in mode.mode_shape.items()},
        "dominant_dofs": list(mode.dominant_dofs),
        "residual": mode.residual,
        "source": mode.source,
    }


def mechanism_mode_from_json(data: dict[str, Any]) -> MechanismMode:
    """Deserialize a ``MechanismMode`` from a JSON-decoded dict.

    Type conversions (inverse of ``mechanism_mode_to_json``):
    - ``mode_shape`` keys: ``str`` → ``int``.
    - ``mode_shape`` values: ``list`` → ``tuple[float, ...]``.
    - ``dominant_dofs``: ``list`` → ``tuple[str, ...]``.
    """
    return MechanismMode(
        mode_number=int(data["mode_number"]),
        eigenvalue=float(data["eigenvalue"]),
        mode_shape={
            int(k): tuple(float(x) for x in v)
            for k, v in data.get("mode_shape", {}).items()
        },
        dominant_dofs=tuple(str(x) for x in data.get("dominant_dofs", [])),
        residual=float(data.get("residual", 0.0)),
        source=str(data.get("source", "stiffness_nullspace")),
    )


def instability_diagnostic_to_json(result: InstabilityDiagnosticResult) -> dict[str, Any]:
    """Serialize an ``InstabilityDiagnosticResult`` to a JSON-compatible dict."""
    return {
        "mechanism_count": result.mechanism_count,
        "modes": [mechanism_mode_to_json(m) for m in result.modes],
        "message": result.message,
        "matrix_size": result.matrix_size,
        "diagnostic_success": result.diagnostic_success,
    }


def instability_diagnostic_from_json(
    data: dict[str, Any] | None,
) -> InstabilityDiagnosticResult | None:
    """Deserialize an ``InstabilityDiagnosticResult`` from a JSON-decoded dict.

    Returns ``None`` when ``data`` is ``None`` (field absent in older payloads).
    """
    if data is None:
        return None
    return InstabilityDiagnosticResult(
        mechanism_count=int(data.get("mechanism_count", 0)),
        modes=tuple(mechanism_mode_from_json(m) for m in data.get("modes", [])),
        message=str(data.get("message", "")),
        matrix_size=int(data.get("matrix_size", 0)),
        diagnostic_success=bool(data.get("diagnostic_success", False)),
    )
