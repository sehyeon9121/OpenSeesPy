from pathlib import Path

from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter


def test_imports_model_when_analysis_only_external_file_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "cantilever_with_missing_ground_motion.py"
    source.write_text(
        """
from pathlib import Path
import openseespy.opensees as ops

def run_model():
    ground_motion = Path('missing_ground_motion.dat')
    if not ground_motion.exists():
        raise FileNotFoundError(ground_motion)

    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 3)
    ops.node(1, 0.0, 0.0)
    ops.node(2, 0.0, 432.0)
    ops.fix(1, 1, 1, 1)
    ops.mass(2, 5.18, 0.0, 0.0)
    ops.geomTransf('Linear', 1)
    ops.element('elasticBeamColumn', 1, 1, 2, 3600.0, 3225.0, 1080000.0, 1)
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(2, 0.0, -2000.0, 0.0)

    ops.constraints('Plain')
    ops.analysis('Static')
    ops.analyze(10)

if __name__ == '__main__':
    run_model()
""",
        encoding="utf-8",
    )

    model = OpenSeesModelImporter(timeout_seconds=20).load(source)

    assert len(model.nodes) == 2
    assert len(model.elements) == 1
    assert model.elements[1].node_i == 1
    assert model.elements[1].node_j == 2
    assert model.boundaries[0].node_tag == 1
    assert model.nodal_loads[0].node_tag == 2
    assert model.nodal_loads[0].values == (0.0, -2000.0, 0.0)
