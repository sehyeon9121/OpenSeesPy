"""Regression: a model script that wipes again at the end must still import.

Many OpenSeesPy scripts finish with ``ops.wipe()`` to free memory after running their
own (suppressed, during import) analysis. The collector used to treat that call the
same as a mid-build "start over" wipe and discard everything it had gathered, so the
import came back with zero nodes.
"""

from pathlib import Path

from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "trailing_wipe_2d.py"


def test_model_survives_a_wipe_after_the_scripts_own_analysis() -> None:
    model = OpenSeesModelImporter(timeout_seconds=15).load(EXAMPLE_MODEL)

    assert len(model.nodes) == 4
    assert len(model.elements) == 3
    assert len(model.boundaries) == 2
    assert len(model.nodal_loads) == 1
