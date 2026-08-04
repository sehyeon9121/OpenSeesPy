"""Simply supported beam carrying a uniformly distributed load, as one element.

Textbook solution for L=4 m, w=10 kN/m downward: reactions 20 kN each, midspan moment
wL^2/8 = 20 kN.m (sagging), shear +20 kN falling linearly to -20 kN.

The whole span is a single element on purpose: the moment peaks between the two ends, so
the diagram is only right if the internal forces are rebuilt along the member.
"""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

ops.node(1, 0.0, 0.0)
ops.node(2, 4.0, 0.0)

ops.fix(1, 1, 1, 0)
ops.fix(2, 0, 1, 0)

area = 0.02
elastic_modulus = 200_000_000.0
moment_of_inertia = 1.6e-4
ops.geomTransf("Linear", 1)
ops.element("elasticBeamColumn", 1, 1, 2, area, elastic_modulus, moment_of_inertia, 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.eleLoad("-ele", 1, "-type", "-beamUniform", -10.0)
