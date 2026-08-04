"""Simply supported beam with a central point load.

Textbook solution for L=4 m, P=10 kN: reactions 5 kN each, midspan moment PL/4 = 10 kN·m
(sagging), shear +5 kN then -5 kN. Used to verify result sign conventions.
"""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

ops.node(1, 0.0, 0.0)
ops.node(2, 2.0, 0.0)
ops.node(3, 4.0, 0.0)

ops.fix(1, 1, 1, 0)
ops.fix(3, 0, 1, 0)

area = 0.01
elastic_modulus = 200_000_000.0
moment_of_inertia = 8.0e-5
ops.geomTransf("Linear", 1)
ops.element("elasticBeamColumn", 1, 1, 2, area, elastic_modulus, moment_of_inertia, 1)
ops.element("elasticBeamColumn", 2, 2, 3, area, elastic_modulus, moment_of_inertia, 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(2, 0.0, -10.0, 0.0)
