import openseespy.opensees as ops

OPENFRAME_MODEL_ORIGIN = 'direct'

ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)

ops.node(1, 0.0, 0.0)
ops.node(2, 4.0, 0.0)

ops.fix(1, 1, 1, 1)

ops.geomTransf('Linear', 1)
ops.uniaxialMaterial('Elastic', 30000004, 4000000.0)
ops.uniaxialMaterial('Steel01', 30000005, 500.0, 40000.0, 0.02)
ops.section('Aggregator', 30000004, 30000004, 'P', 30000005, 'Mz')
ops.beamIntegration('Lobatto', 30000004, 30000004, 5)
ops.element('forceBeamColumn', 1, 1, 2, 1, 30000004, '-iter', 50, 1e-12)

ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 0.0, -200.0, 0.0)

