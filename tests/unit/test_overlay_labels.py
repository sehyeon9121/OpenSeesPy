"""3D result-value labels: which number sits on which member, per result type."""

import math

import pytest

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    AnalysisStatus,
    BoundaryCondition,
    Element,
    ElementResult,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results import overlay_labels as overlay_labels_module
from openframe.features.results.overlay_labels import result_overlay_labels


def _cantilever(*, local_forces: tuple[float, ...]) -> tuple[StructuralModel, AnalysisResult]:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(tag=1, x=0.0, y=0.0, z=0.0, ndf=6),
            2: Node(tag=2, x=1.0, y=0.0, z=0.0, ndf=6),
        },
        elements={
            1: Element(tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn"),
        },
        boundaries=[
            BoundaryCondition(node_tag=1, restraints=(True, True, True, True, True, True)),
        ],
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        element_results={1: ElementResult(element_tag=1, local_forces=local_forces)},
        node_results={
            1: NodeResult(node_tag=1, displacement=(0.0, 0.0, 0.0), reaction=(3.0, 4.0, 12.0)),
            2: NodeResult(node_tag=2, displacement=(0.03, -0.04, 0.0)),
        },
    )
    return model, result


def _texts(result_type: str, **kwargs) -> list[str]:
    model, result = _cantilever(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )
    return [label.text for label in result_overlay_labels(model, result, result_type, DEFAULT_UNIT_SYSTEM, **kwargs)]


def test_overview_and_tables_have_no_scene_labels() -> None:
    """Summary and tables already have their own panels; stacking numbers on
    the 3D view in those modes just duplicates the sidebar.
    """
    assert _texts("overview") == []
    assert _texts("tables") == []


def test_displacement_labels_sit_on_nodes_that_moved() -> None:
    model, result = _cantilever(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )
    labels = result_overlay_labels(
        model, result, "displacement", DEFAULT_UNIT_SYSTEM, deformation_scale=2.0
    )

    assert len(labels) == 1
    assert labels[0].text == "Δ 0.05 m"
    # Follows the same deformed node the coloured member already uses.
    assert (labels[0].x, labels[0].y, labels[0].z) == pytest.approx((1.06, -0.08, 0.0))


def test_deformation_puts_peak_translation_on_the_member_midspan() -> None:
    model, result = _cantilever(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )
    labels = result_overlay_labels(model, result, "deformation", DEFAULT_UNIT_SYSTEM)

    assert len(labels) == 1
    assert labels[0].text == "Δ 0.05 m"
    assert (labels[0].x, labels[0].y, labels[0].z) == pytest.approx((0.5, 0.0, 0.0))


def test_reaction_label_is_the_resultant_at_the_support() -> None:
    labels = result_overlay_labels(*_cantilever(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    ), "reaction", DEFAULT_UNIT_SYSTEM)

    assert len(labels) == 1
    assert labels[0].text == "R 13 kN"
    assert (labels[0].x, labels[0].y, labels[0].z) == pytest.approx((0.0, 0.0, 0.0))


def test_moment_labels_sit_on_the_ribbon_ends() -> None:
    model, result = _cantilever(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )
    labels = result_overlay_labels(model, result, "moment", DEFAULT_UNIT_SYSTEM)

    assert [label.text for label in labels] == ["Mz -1 kN·m", "Mz 0 kN·m"]
    # Hogging Mz is drawn on +local y, so the fixed-end number is above the beam.
    assert labels[0].y > 0.0
    assert labels[1].y == pytest.approx(0.0)


def test_constant_axial_is_one_label_at_midspan() -> None:
    model, result = _cantilever(
        local_forces=(-10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    labels = result_overlay_labels(model, result, "axial", DEFAULT_UNIT_SYSTEM)

    assert len(labels) == 1
    assert labels[0].text == "N 10 kN"
    assert labels[0].x == pytest.approx(0.5)


def test_both_shear_planes_keep_distinct_prefixes() -> None:
    model, result = _cantilever(
        local_forces=(0.0, 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, -1.0, -2.0, 0.0, 0.0, 0.0),
    )
    texts = [label.text for label in result_overlay_labels(model, result, "shear", DEFAULT_UNIT_SYSTEM)]

    assert "Vy 1 kN" in texts
    assert "Vz 2 kN" in texts


def test_stress_label_uses_peak_fibre_stress() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(tag=1, x=0.0, y=0.0, z=0.0, ndf=6),
            2: Node(tag=2, x=1.0, y=0.0, z=0.0, ndf=6),
        },
        elements={
            1: Element(
                tag=1,
                node_i=1,
                node_j=2,
                element_type="truss",
                properties={"A": 0.01},
            ),
        },
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        element_results={1: ElementResult(element_tag=1, local_forces=(-5.0, 5.0))},
    )
    labels = result_overlay_labels(model, result, "stress", DEFAULT_UNIT_SYSTEM)

    assert len(labels) == 1
    assert labels[0].text.startswith("σ 500 ")
    assert (labels[0].x, labels[0].y, labels[0].z) == pytest.approx((0.5, 0.0, 0.0))


def test_dense_models_keep_the_largest_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overlay_labels_module, "_LABEL_CAP", 2)
    nodes = {tag: Node(tag=tag, x=float(tag), y=0.0, z=0.0, ndf=6) for tag in range(1, 6)}
    model = StructuralModel(ndm=3, ndf=6, nodes=nodes)
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            tag: NodeResult(node_tag=tag, displacement=(0.0, 0.0, float(tag)))
            for tag in nodes
        },
    )
    labels = result_overlay_labels(model, result, "displacement", DEFAULT_UNIT_SYSTEM)

    assert len(labels) == 2
    magnitudes = [math.sqrt(tag * tag) for tag in (5, 4)]
    assert [label.abs_value for label in labels] == pytest.approx(magnitudes)
