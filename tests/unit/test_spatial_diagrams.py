"""3D force-diagram geometry: plot side and tessellation, no Qt."""

import pytest

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Element,
    ElementResult,
    GeometricTransform,
    Node,
    StructuralModel,
)
from openframe.features.results.diagrams import DiagramKind, spatial_diagram_strips


def _cantilever_along_x(*, local_forces: tuple[float, ...]) -> tuple[StructuralModel, AnalysisResult]:
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
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        element_results={1: ElementResult(element_tag=1, local_forces=local_forces)},
    )
    return model, result


def test_hogging_moment_is_drawn_on_the_positive_local_y_side() -> None:
    # Beam along +X, auto vecxz = global Z, so local y is +Y. Hogging Mz at the
    # fixed end is negative internal moment - the 2D renderer puts that ABOVE
    # the beam (opposite the tension-side sagging diagram). Same offset here.
    model, result = _cantilever_along_x(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )

    strips = spatial_diagram_strips(model, result, DiagramKind.MOMENT, 50)

    assert len(strips) == 1
    axis_i, curve_i = strips[0].axis[0], strips[0].curve[0]
    assert curve_i[1] > axis_i[1]
    assert curve_i[0] == pytest.approx(axis_i[0])
    assert curve_i[2] == pytest.approx(axis_i[2])
    # Tip moment is zero, so the curve meets the axis at end j.
    assert strips[0].curve[-1] == pytest.approx(strips[0].axis[-1])


def test_positive_shear_is_drawn_on_the_positive_local_y_side() -> None:
    model, result = _cantilever_along_x(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )

    strips = spatial_diagram_strips(model, result, DiagramKind.SHEAR, 50)

    assert len(strips) == 1
    axis_i, curve_i = strips[0].axis[0], strips[0].curve[0]
    assert curve_i[1] > axis_i[1]


def test_zero_out_of_plane_component_does_not_emit_a_second_strip() -> None:
    model, result = _cantilever_along_x(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )

    moment_strips = spatial_diagram_strips(model, result, DiagramKind.MOMENT, 50)
    shear_strips = spatial_diagram_strips(model, result, DiagramKind.SHEAR, 50)

    assert [strip.color for strip in moment_strips] == ["#7254a8"]
    assert [strip.color for strip in shear_strips] == ["#7254a8"]


def test_both_shear_planes_emit_when_vy_and_vz_are_present() -> None:
    model, result = _cantilever_along_x(
        local_forces=(0.0, 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, -1.0, -2.0, 0.0, 0.0, 0.0),
    )

    strips = spatial_diagram_strips(model, result, DiagramKind.SHEAR, 50)

    assert {strip.color for strip in strips} == {"#7254a8", "#3d7ea6"}
    y_strip = next(strip for strip in strips if strip.color == "#7254a8")
    z_strip = next(strip for strip in strips if strip.color == "#3d7ea6")
    assert y_strip.curve[0][1] != y_strip.axis[0][1]
    assert z_strip.curve[0][2] != z_strip.axis[0][2]


def test_hogging_my_is_drawn_on_the_positive_local_z_side() -> None:
    # Same cantilever along +X, tip load in -Z. Hogging in the x-z plane
    # (Z up) must sit on the +Z face - the tension side - not hang below.
    # Captured OpenSees localForce: Vz_i=+1, My_i=-1 for L=1, P=1.
    model, result = _cantilever_along_x(
        local_forces=(0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0),
    )

    strips = spatial_diagram_strips(model, result, DiagramKind.MOMENT, 50)

    assert len(strips) == 1
    axis_i, curve_i = strips[0].axis[0], strips[0].curve[0]
    assert curve_i[2] > axis_i[2]
    assert curve_i[0] == pytest.approx(axis_i[0])
    assert curve_i[1] == pytest.approx(axis_i[1])


def test_positive_vz_is_drawn_on_the_positive_local_z_side() -> None:
    model, result = _cantilever_along_x(
        local_forces=(0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0),
    )

    strips = spatial_diagram_strips(model, result, DiagramKind.SHEAR, 50)

    assert len(strips) == 1
    axis_i, curve_i = strips[0].axis[0], strips[0].curve[0]
    assert curve_i[2] > axis_i[2]


def test_imported_geomtransf_vecxz_orients_the_diagram_not_the_auto_fallback() -> None:
    """Vertical member, script vecxz = +Y (OpenSees local y = +X). Auto
    fallback for a vertical member is +X (local y = -Y). Drawing Vy along
    auto y would put the shear ribbon in the Y plane when the force is in X.
    """
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(tag=1, x=0.0, y=0.0, z=0.0, ndf=6),
            2: Node(tag=2, x=0.0, y=0.0, z=3.0, ndf=6),
        },
        elements={
            1: Element(
                tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn", transf_tag=1
            ),
        },
        geometric_transforms={
            1: GeometricTransform(1, "Linear", (0.0, 1.0, 0.0)),
        },
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        element_results={
            1: ElementResult(
                element_tag=1,
                local_forces=(0.0, -10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0),
            )
        },
    )

    strips = spatial_diagram_strips(model, result, DiagramKind.SHEAR, 50)

    assert len(strips) == 1
    offset = tuple(strips[0].curve[0][i] - strips[0].axis[0][i] for i in range(3))
    # Negative Vy, local y = +X → ribbon on -X, not on ±Y.
    assert offset[0] < 0.0
    assert offset[1] == pytest.approx(0.0)
    assert offset[2] == pytest.approx(0.0)


def test_truss_skips_shear_and_moment_strips() -> None:
    model, result = _cantilever_along_x(
        local_forces=(-10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    model.elements[1] = Element(tag=1, node_i=1, node_j=2, element_type="truss")

    assert spatial_diagram_strips(model, result, DiagramKind.SHEAR, 50) == ()
    assert spatial_diagram_strips(model, result, DiagramKind.MOMENT, 50) == ()
    axial = spatial_diagram_strips(model, result, DiagramKind.AXIAL, 50)
    assert len(axial) == 1


def test_larger_diagram_scale_grows_the_offset() -> None:
    model, result = _cantilever_along_x(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )

    small = spatial_diagram_strips(model, result, DiagramKind.MOMENT, 25)[0]
    large = spatial_diagram_strips(model, result, DiagramKind.MOMENT, 100)[0]
    small_offset = abs(small.curve[0][1] - small.axis[0][1])
    large_offset = abs(large.curve[0][1] - large.axis[0][1])
    assert large_offset == pytest.approx(small_offset * 4.0)


def test_bridge_turns_strips_into_cylinders_and_fill_cubes() -> None:
    """``zip(curve, curve[1:], strict=True)`` looks neat and is wrong: the
    sliced sequence is one shorter, so the overlay crashed the moment view.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge

    QApplication.instance() or QApplication([])
    model, result = _cantilever_along_x(
        local_forces=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    )
    strips = spatial_diagram_strips(model, result, DiagramKind.MOMENT, 50)
    payload = [
        {"color": strip.color, "axis": list(strip.axis), "curve": list(strip.curve)}
        for strip in strips
    ]

    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    bridge.set_result(model, result, 0.0, False, force_diagrams=payload)

    shapes = {part["shape"] for part in bridge.forceDiagrams}
    assert "#Cylinder" in shapes
    assert "#Cube" in shapes

