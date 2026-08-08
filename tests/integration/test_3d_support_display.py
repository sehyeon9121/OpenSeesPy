from pathlib import Path

from openframe.core.domain import (
    BoundaryCondition,
    Node,
    StructuralModel,
    SupportKind,
)
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "cantilever_frame_3d.py"


def test_imported_3d_fixed_support_is_rendered_as_a_green_block() -> None:
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    assert bridge.supportSymbols
    assert {part["tag"] for part in bridge.supportSymbols} == {1}
    assert {part["kind"] for part in bridge.supportSymbols} == {SupportKind.FIXED.value}
    assert {part["role"] for part in bridge.supportSymbols} == {"fixed_block"}
    assert {part["color"] for part in bridge.supportSymbols} == {"#00856a"}
    assert bridge.supportSymbols[0]["y"] < bridge.nodes[0]["y"]
    support_bottom = bridge.supportSymbols[0]["y"] - bridge.supportSymbols[0]["scale_y"] / 2
    ground_top = bridge.ground_y + max(bridge.extent * 0.012, 0.01) / 2
    assert support_bottom >= ground_top

    bridge.set_supports_visible(False)
    assert bridge.supportSymbols == []
    bridge.set_supports_visible(True)
    assert bridge.supportSymbols


def test_fixed_pin_and_custom_restraints_use_distinct_midas_style_glyphs() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 4.0, 0.0, 0.0, 6),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(2, (True, True, True, False, False, False)),
            BoundaryCondition(3, (True, False, False, False, False, False)),
        ],
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    by_tag: dict[int, list[dict]] = {}
    for part in bridge.supportSymbols:
        by_tag.setdefault(int(part["tag"]), []).append(part)

    assert {part["role"] for part in by_tag[1]} == {"fixed_block"}
    assert {part["role"] for part in by_tag[2]} == {"pin_cone", "ground_plate"}
    assert {part["role"] for part in by_tag[3]} == {"custom_block"}
    assert {part["color"] for part in by_tag[1]} == {"#00856a"}
    assert {part["color"] for part in by_tag[2]} == {"#00a6a6"}
    assert {part["color"] for part in by_tag[3]} == {"#f59e0b"}
