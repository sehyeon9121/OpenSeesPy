
import openseespy.opensees as ops

OPENFRAME_LOAD_CASES = {1: "DEAD", 2: "LIVE"}

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 0.0, 0.0, 3.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)
ops.geomTransf("Linear", 1, 1.0, 0.0, 0.0)
ops.element("elasticBeamColumn", 1, 1, 2, 0.02, 2.0e8, 7.7e7,
            1.6e-4, 8.0e-5, 8.0e-5, 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(2, 0.0, 0.0, -10.0, 0.0, 0.0, 0.0)
ops.eleLoad("-ele", 1, "-type", "-beamUniform", 0.0, -2.0, 0.0)

ops.timeSeries("Linear", 2)
ops.pattern("Plain", 2, 2)
ops.load(2, 0.0, 0.0, -5.0, 0.0, 0.0, 0.0)
ops.eleLoad("-ele", 1, "-type", "-beamUniform", 0.0, -1.0, 0.0)
