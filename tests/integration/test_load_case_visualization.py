from pathlib import Path

from openframe.core.domain import LoadCaseKind
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter


def test_declared_dead_and_live_patterns_are_collected_coloured_and_filterable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dead_and_live.py"
    source.write_text(
        """
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
""",
        encoding="utf-8",
    )

    model = OpenSeesModelImporter(timeout_seconds=20).load(source)

    assert [load.pattern_tag for load in model.nodal_loads] == [1, 2]
    assert [load.case_type for load in model.nodal_loads] == [
        LoadCaseKind.DEAD,
        LoadCaseKind.LIVE,
    ]
    assert [load.pattern_tag for load in model.element_loads] == [1, 2]
    assert [load.case_type for load in model.element_loads] == [
        LoadCaseKind.DEAD,
        LoadCaseKind.LIVE,
    ]

    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    assert {part["case_type"] for part in bridge.loadArrows} == {"DEAD", "LIVE"}

    bridge.set_load_case_filter("DEAD")
    assert {part["case_type"] for part in bridge.loadArrows} == {"DEAD"}
    assert {part["color"] for part in bridge.loadArrows} == {"#2563eb"}

    bridge.set_load_case_filter("LIVE")
    assert {part["case_type"] for part in bridge.loadArrows} == {"LIVE"}
    assert {part["color"] for part in bridge.loadArrows} == {"#16a34a"}
