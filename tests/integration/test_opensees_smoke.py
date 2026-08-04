"""Verify that the installed OpenSeesPy engine can solve a minimal 2D model."""

import openseespy.opensees as ops


def test_opensees_solves_cantilever() -> None:
    ops.wipe()
    try:
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 1.0, 0.0)
        ops.fix(1, 1, 1, 1)
        ops.geomTransf("Linear", 1)
        ops.element("elasticBeamColumn", 1, 1, 2, 1.0, 200_000.0, 1.0, 1)

        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 0.0, -1.0, 0.0)

        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Plain")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")

        assert ops.analyze(1) == 0
        assert ops.nodeDisp(2, 2) < 0.0
    finally:
        ops.wipe()

