"""Independent regression test for MaterialFreeStaticsSolver's 3D beamPoint
argument order.

This does NOT compare against ``opensees_script_export.py``'s own output -
that comparison is exactly how the original ``position``/``pz`` swap went
undetected for as long as it did: both implementations shared the identical
wrong order, so their round-trip agreed with itself perfectly while still
being wrong. Instead this spies directly on the real ``ops.eleLoad`` call
``MaterialFreeStaticsSolver`` makes, so it fails if that call's argument
order ever drifts from OpenSeesPy's actual ``(Py, Pz, xL, N)`` signature for
``-beamPoint`` in 3D - confirmed empirically against plain OpenSeesPy,
independent of this solver, before this test was written (see the
Phase 2-A.1 session report)."""

import openseespy.opensees as ops
import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    Node,
    PointElementLoad,
    StructuralModel,
)
from openframe.features.analysis.statics import solver as solver_module
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver

_PROPERTIES_3D = {
    "E": 200.0e6,
    "A": 0.02,
    "G": 77.0e6,
    "J": 2.0e-6,
    "Iy": 6.0e-5,
    "Iz": 8.0e-5,
}


def test_solve_passes_beam_point_args_in_py_pz_xl_n_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    original_eleload = ops.eleLoad

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(args)
        return original_eleload(*args, **kwargs)

    # solver.py's own `import openseespy.opensees as ops` binds the same
    # module object this test imports directly - patching either name
    # patches the one real ``eleLoad`` both share.
    monkeypatch.setattr(solver_module.ops, "eleLoad", spy)

    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 6.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties=_PROPERTIES_3D)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        point_loads=[PointElementLoad(1, position=0.25, py=2.0, pz=7.0, n=0.5)],
    )

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    beam_point_calls = [args for args in calls if "-beamPoint" in args]
    assert len(beam_point_calls) == 1
    # ('-ele', 1, '-type', '-beamPoint', Py, Pz, xL, N)
    py, pz, xl, n = beam_point_calls[0][-4:]
    assert (py, pz, xl, n) == pytest.approx((2.0, 7.0, 0.25, 0.5))
