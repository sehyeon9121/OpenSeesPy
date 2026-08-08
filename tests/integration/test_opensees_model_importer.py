from pathlib import Path

import pytest

from openframe.core.domain import SupportKind
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "portal_frame_2d.py"
TEXTBOOK_PORTAL = Path(__file__).parents[2] / "examples" / "portal_frame_textbook_2d.py"


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
    assert model.elements[3].properties["A"] == 0.02
    assert model.elements[3].properties["E"] == 200_000_000.0
    assert model.elements[3].properties["I"] == 8.0e-5


def test_imports_textbook_portal_geometry_supports_and_loads() -> None:
    model = OpenSeesModelImporter(timeout_seconds=10).load(TEXTBOOK_PORTAL)

    assert len(model.nodes) == 6
    assert len(model.elements) == 5
    assert len(model.boundaries) == 2
    assert len(model.nodal_loads) == 2

    assert (model.nodes[2].x, model.nodes[2].y) == (0.0, 2.0)  # D
    assert (model.nodes[4].x, model.nodes[4].y) == (3.5, 4.0)  # C
    assert (model.nodes[5].x, model.nodes[5].y) == (7.0, 4.0)  # F

    supports = {boundary.node_tag: boundary.support_kind for boundary in model.boundaries}
    assert supports == {1: SupportKind.PINNED, 6: SupportKind.ROLLER_HORIZONTAL}

    loads = {load.node_tag: load.values for load in model.nodal_loads}
    assert loads[2] == pytest.approx((35.0, 0.0, 0.0))
    assert loads[4] == pytest.approx((0.0, -80.0, 0.0))
