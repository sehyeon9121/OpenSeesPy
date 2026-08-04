from pathlib import Path

from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "portal_frame_2d.py"


def test_imports_portal_frame_in_subprocess() -> None:
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    assert model.ndm == 2
    assert model.ndf == 3
    assert len(model.nodes) == 4
    assert len(model.elements) == 3
    assert len(model.boundaries) == 2
    assert len(model.nodal_loads) == 1
    assert model.nodes[4].x == 6.0
    assert model.nodes[4].y == 3.0
    assert model.elements[3].element_type == "elasticBeamColumn"
    assert model.elements[3].node_i == 3
    assert model.elements[3].node_j == 4

