"""Minimal 2D portal frame used to verify MODEL import and visualization."""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

ops.node(1, 0.0, 0.0)
ops.node(2, 6.0, 0.0)
ops.node(3, 0.0, 3.0)
ops.node(4, 6.0, 3.0)

ops.fix(1, 1, 1, 1)
ops.fix(2, 1, 1, 1)

area = 0.02
elastic_modulus = 200_000_000.0
moment_of_inertia = 8.0e-5
ops.geomTransf("Linear", 1)
ops.element("elasticBeamColumn", 1, 1, 3, area, elastic_modulus, moment_of_inertia, 1)
ops.element("elasticBeamColumn", 2, 2, 4, area, elastic_modulus, moment_of_inertia, 1)
ops.element("elasticBeamColumn", 3, 3, 4, area, elastic_modulus, moment_of_inertia, 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(4, 20.0, -30.0, 0.0)

