"""2D portal frame with lumped nodal mass, used to verify MODAL (eigenvalue) analysis.

Same geometry as portal_frame_2d.py, but with translational mass added at the two
free top nodes so ops.eigen(...) has something to solve - a modal analysis has no
natural frequency to find without real nodal mass.
"""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

ops.node(1, 0.0, 0.0)
ops.node(2, 6.0, 0.0)
ops.node(3, 0.0, 3.0)
ops.node(4, 6.0, 3.0)

ops.fix(1, 1, 1, 1)
ops.fix(2, 1, 1, 1)

mass = 5.0
ops.mass(3, mass, mass, 0.0)
ops.mass(4, mass, mass, 0.0)

area = 0.02
elastic_modulus = 200_000_000.0
moment_of_inertia = 8.0e-5
ops.geomTransf("Linear", 1)
ops.element("elasticBeamColumn", 1, 1, 3, area, elastic_modulus, moment_of_inertia, 1)
ops.element("elasticBeamColumn", 2, 2, 4, area, elastic_modulus, moment_of_inertia, 1)
ops.element("elasticBeamColumn", 3, 3, 4, area, elastic_modulus, moment_of_inertia, 1)
