"""Formulas verified against the Master DB's own ``Sections`` sample records
wherever one exists (Rectangle/Circle/H-I/Box/Pipe) - Channel/Angle bending
inertia has no Master DB reference (those cells are empty in the seed data),
so those two are checked against a hand-derived composite-rectangle
calculation instead."""

import pytest

from openframe.core.domain.section_properties import (
    SUPPORTED_SHAPES,
    SectionDimensionError,
    angle_properties,
    box_properties,
    channel_properties,
    circle_properties,
    compute_section_properties,
    dimension_fields,
    h_section_properties,
    pipe_properties,
    rectangle_properties,
)

# Master DB seed values, read directly from
# infrastructure/material_section_db/data/material_section_database.cache.json.
_RECT_300X500 = (150_000.0, 3_125_000_000.0, 1_125_000_000.0, 2_817_370_800.0)
_CIRC_D300 = (70_685.83470577035, 397_607_820.2199582, 397_607_820.2199582, 795_215_640.4399164)
_H_300X300X10X15 = (11_700.0, 199_327_500.0, 67_522_500.0, 765_000.0)
_BOX_200X200X9 = (6_876.0, 41_900_052.0, 41_900_052.0, None)  # J: Bredt approx, checked separately
_PIPE_114_3X6 = (
    2_041.4069063026482,
    3_002_115.96223637,
    3_002_115.96223637,
    6_004_231.92447274,
)


def test_rectangle_matches_the_master_db_sample() -> None:
    result = rectangle_properties(300.0, 500.0)
    assert result.area_mm2 == pytest.approx(_RECT_300X500[0])
    assert result.Iy_mm4 == pytest.approx(_RECT_300X500[1])
    assert result.Iz_mm4 == pytest.approx(_RECT_300X500[2])
    assert result.J_mm4 == pytest.approx(_RECT_300X500[3], rel=1e-5)


def test_circle_matches_the_master_db_sample() -> None:
    result = circle_properties(300.0)
    assert result.area_mm2 == pytest.approx(_CIRC_D300[0])
    assert result.Iy_mm4 == pytest.approx(_CIRC_D300[1])
    assert result.Iz_mm4 == pytest.approx(_CIRC_D300[2])
    assert result.J_mm4 == pytest.approx(_CIRC_D300[3])
    assert result.J_mm4 == pytest.approx(2.0 * result.Iy_mm4)


def test_h_section_matches_the_master_db_sample() -> None:
    result = h_section_properties(H=300.0, B=300.0, tw=10.0, tf=15.0)
    assert result.area_mm2 == pytest.approx(_H_300X300X10X15[0])
    assert result.Iy_mm4 == pytest.approx(_H_300X300X10X15[1])
    assert result.Iz_mm4 == pytest.approx(_H_300X300X10X15[2])
    assert result.J_mm4 == pytest.approx(_H_300X300X10X15[3])


def test_box_matches_the_master_db_sample() -> None:
    result = box_properties(H=200.0, B=200.0, t=9.0)
    assert result.area_mm2 == pytest.approx(_BOX_200X200X9[0])
    assert result.Iy_mm4 == pytest.approx(_BOX_200X200X9[1])
    assert result.Iz_mm4 == pytest.approx(_BOX_200X200X9[2])
    # Bredt thin-wall approximation - close to, not bit-identical with, the
    # Master DB's own (unspecified) closed-form value.
    assert result.J_mm4 == pytest.approx(62_710_839.0, rel=1e-3)


def test_pipe_matches_the_master_db_sample() -> None:
    result = pipe_properties(D=114.3, t=6.0)
    assert result.area_mm2 == pytest.approx(_PIPE_114_3X6[0])
    assert result.Iy_mm4 == pytest.approx(_PIPE_114_3X6[1])
    assert result.Iz_mm4 == pytest.approx(_PIPE_114_3X6[2])
    assert result.J_mm4 == pytest.approx(_PIPE_114_3X6[3])


def test_channel_area_matches_the_master_db_sample_and_iy_matches_h_section() -> None:
    """No Master DB Iy/Iz reference exists for Channel, but area does (3095
    mm^2), and Iy must equal an H-section's of the same H/B/tw/tf since a
    channel's web y-position never enters an integral over z."""
    channel = channel_properties(H=200.0, B=80.0, tw=7.5, tf=11.0)
    assert channel.area_mm2 == pytest.approx(3_095.0)
    assert channel.J_mm4 == pytest.approx(96_017.91666666667)

    h_equivalent = h_section_properties(H=200.0, B=80.0, tw=7.5, tf=11.0)
    assert channel.Iy_mm4 == pytest.approx(h_equivalent.Iy_mm4)


def test_angle_area_matches_the_master_db_sample() -> None:
    angle = angle_properties(H=100.0, B=100.0, t=10.0)
    assert angle.area_mm2 == pytest.approx(1_900.0)
    # An equal-leg angle is symmetric under swapping H and B - Iy must equal Iz.
    assert angle.Iy_mm4 == pytest.approx(angle.Iz_mm4)


@pytest.mark.parametrize(
    ("shape", "dimensions"),
    [
        ("Rectangle", {"b": 300.0, "h": 500.0}),
        ("Circle", {"D": 300.0}),
        ("H/I Section", {"H": 300.0, "B": 300.0, "tw": 10.0, "tf": 15.0}),
        ("Box", {"H": 200.0, "B": 200.0, "t": 9.0}),
        ("Pipe", {"D": 114.3, "t": 6.0}),
        ("Channel", {"H": 200.0, "B": 80.0, "tw": 7.5, "tf": 11.0}),
        ("Angle", {"H": 100.0, "B": 100.0, "t": 10.0}),
    ],
)
def test_compute_section_properties_dispatches_by_shape_name(
    shape: str, dimensions: dict[str, float]
) -> None:
    dispatched = compute_section_properties(shape, dimensions)
    assert dispatched.area_mm2 > 0.0
    assert dispatched.Iy_mm4 > 0.0
    assert dispatched.Iz_mm4 > 0.0
    assert dispatched.J_mm4 > 0.0


def test_every_supported_shape_has_dimension_fields_except_user_defined() -> None:
    assert set(SUPPORTED_SHAPES) == {
        "Rectangle",
        "Circle",
        "H/I Section",
        "Box",
        "Pipe",
        "Channel",
        "Angle",
        "User Defined",
    }
    assert dimension_fields("User Defined") == ()
    assert [field.key for field in dimension_fields("Rectangle")] == ["b", "h"]
    assert [field.key for field in dimension_fields("H/I Section")] == ["H", "B", "tw", "tf"]


@pytest.mark.parametrize(
    ("shape", "dimensions"),
    [
        ("Rectangle", {"b": 0.0, "h": 500.0}),
        ("Rectangle", {"b": -300.0, "h": 500.0}),
        ("Circle", {"D": 0.0}),
        ("H/I Section", {"H": 300.0, "B": 300.0, "tw": 10.0, "tf": 200.0}),  # 2*tf >= H
        ("H/I Section", {"H": 300.0, "B": 10.0, "tw": 20.0, "tf": 15.0}),  # tw >= B
        ("Box", {"H": 200.0, "B": 200.0, "t": 150.0}),  # 2*t >= H and B
        ("Pipe", {"D": 100.0, "t": 60.0}),  # 2*t >= D
        ("Channel", {"H": 200.0, "B": 80.0, "tw": 7.5, "tf": 150.0}),
        ("Angle", {"H": 100.0, "B": 100.0, "t": 60.0}),
    ],
)
def test_invalid_dimensions_are_rejected_immediately(
    shape: str, dimensions: dict[str, float]
) -> None:
    with pytest.raises(SectionDimensionError):
        compute_section_properties(shape, dimensions)


def test_compute_section_properties_rejects_an_unknown_shape() -> None:
    with pytest.raises(SectionDimensionError):
        compute_section_properties("Trapezoid", {"b": 1.0})


def test_compute_section_properties_reports_a_missing_dimension() -> None:
    with pytest.raises(SectionDimensionError, match="치수"):
        compute_section_properties("Rectangle", {"b": 300.0})
