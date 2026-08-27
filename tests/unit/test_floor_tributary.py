"""Floor tributary-area conversion (floor_tributary.py) - a FloorLoadEntry's
magnitude over its boundary polygon turned into equivalent boundary-beam
UniformElementLoad contributions. See that module's own docstring for why a
two-way edge's true triangular/trapezoidal shape is replaced by a
statically-equivalent linear ramp (exact total force + resultant location,
approximate fine shape).
"""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    Element,
    FloorLoadEntry,
    LoadCaseKind,
    LoadEntry,
    Node,
)
from openframe.features.model.presentation.floor_tributary import convert_floor_entry
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def _square_boundary(nodes: dict[int, Node], elements: dict[int, Element], lx: float, ly: float):
    nodes[1] = Node(1, 0.0, 0.0, 0.0)
    nodes[2] = Node(2, lx, 0.0, 0.0)
    nodes[3] = Node(3, lx, ly, 0.0)
    nodes[4] = Node(4, 0.0, ly, 0.0)
    elements[101] = Element(101, 1, 2, "elasticBeamColumn", {})
    elements[102] = Element(102, 2, 3, "elasticBeamColumn", {})
    elements[103] = Element(103, 3, 4, "elasticBeamColumn", {})
    elements[104] = Element(104, 4, 1, "elasticBeamColumn", {})


def _floor_entry(magnitude: float, distribution: str = "two_way", span_direction: str = "x") -> LoadEntry:
    return LoadEntry(
        id=1,
        case_id="DL",
        kind="floor",
        target=(1, 2, 3, 4),
        payload=FloorLoadEntry(
            magnitude=magnitude,
            direction="-z",
            distribution=distribution,
            span_direction=span_direction,
            target_nodes=(1, 2, 3, 4),
        ),
    )


def test_rectangle_two_way_matches_classic_45_degree_closed_form() -> None:
    nodes: dict[int, Node] = {}
    elements: dict[int, Element] = {}
    _square_boundary(nodes, elements, lx=6.0, ly=4.0)
    entry = _floor_entry(magnitude=2.0)

    contributions = convert_floor_entry(entry, nodes, elements)

    # unit-pressure closed form: short edge (Ly=4) force = Ly^2/4 = 4,
    # long edge (Lx=6) force = Ly/2*(Lx-Ly) + Ly^2/4 = 4+4 = 8 - both
    # symmetric, so each edge's equivalent ramp is a plain uniform value.
    assert contributions[101][2] == pytest.approx(-2.0 * 8.0 / 6.0)  # wz0, long edge 1-2
    assert contributions[101][5] == pytest.approx(-2.0 * 8.0 / 6.0)  # wz1
    assert contributions[102][2] == pytest.approx(-2.0 * 4.0 / 4.0)  # wz0, short edge 2-3
    assert contributions[103][2] == pytest.approx(-2.0 * 8.0 / 6.0)  # wz0, long edge 3-4
    assert contributions[104][2] == pytest.approx(-2.0 * 4.0 / 4.0)  # wz0, short edge 4-1

    total_reaction = sum(
        (values[2] + values[5]) / 2.0 * length
        for values, length in zip(
            (contributions[101], contributions[102], contributions[103], contributions[104]),
            (6.0, 4.0, 6.0, 4.0),
            strict=True,
        )
    )
    assert total_reaction == pytest.approx(-2.0 * 6.0 * 4.0)  # -magnitude * area


def test_triangle_two_way_conserves_total_load_via_incenter() -> None:
    nodes = {
        1: Node(1, 0.0, 0.0, 0.0),
        2: Node(2, 6.0, 0.0, 0.0),
        3: Node(3, 2.0, 4.0, 0.0),
    }
    elements = {
        101: Element(101, 1, 2, "elasticBeamColumn", {}),
        102: Element(102, 2, 3, "elasticBeamColumn", {}),
        103: Element(103, 3, 1, "elasticBeamColumn", {}),
    }
    entry = LoadEntry(
        id=1,
        case_id="DL",
        kind="floor",
        target=(1, 2, 3),
        payload=FloorLoadEntry(
            magnitude=3.0, direction="-z", distribution="two_way", target_nodes=(1, 2, 3)
        ),
    )

    contributions = convert_floor_entry(entry, nodes, elements)

    lengths = {101: 6.0, 102: math.hypot(4.0, 4.0), 103: math.hypot(2.0, 4.0)}
    total_reaction = sum(
        (values[2] + values[5]) / 2.0 * lengths[tag] for tag, values in contributions.items()
    )
    triangle_area = 0.5 * abs(6.0 * 4.0)  # base 6, height 4
    assert total_reaction == pytest.approx(-3.0 * triangle_area, rel=1e-6)


def test_one_way_rectangle_only_loads_edges_perpendicular_to_span() -> None:
    nodes: dict[int, Node] = {}
    elements: dict[int, Element] = {}
    _square_boundary(nodes, elements, lx=6.0, ly=4.0)
    entry = _floor_entry(magnitude=2.0, distribution="one_way", span_direction="x")

    contributions = convert_floor_entry(entry, nodes, elements)

    # Spans along x: the two edges roughly perpendicular to x (2-3 and 4-1,
    # each running along y) get the UDL; the two edges parallel to x (1-2,
    # 3-4) carry no force and are omitted entirely (zero contributions are
    # never emitted).
    assert 101 not in contributions
    assert 103 not in contributions
    expected_udl = -2.0 * 6.0 / 2.0  # -(magnitude * span_extent / 2)
    assert contributions[102][2] == pytest.approx(expected_udl)
    assert contributions[102][5] == pytest.approx(expected_udl)
    assert contributions[104][2] == pytest.approx(expected_udl)

    total_reaction = contributions[102][2] * 4.0 + contributions[104][2] * 4.0
    assert total_reaction == pytest.approx(-2.0 * 6.0 * 4.0)


def test_boundary_edge_missing_a_member_is_skipped_not_crashed() -> None:
    nodes: dict[int, Node] = {}
    elements: dict[int, Element] = {}
    _square_boundary(nodes, elements, lx=6.0, ly=4.0)
    del elements[103]  # remove the 3-4 edge's member
    entry = _floor_entry(magnitude=2.0)

    contributions = convert_floor_entry(entry, nodes, elements)

    assert set(contributions) == {101, 102, 104}


def test_pentagon_two_way_approximation_conserves_total_load() -> None:
    nodes = {
        1: Node(1, 0.0, 0.0, 0.0),
        2: Node(2, 4.0, 0.0, 0.0),
        3: Node(3, 5.0, 3.0, 0.0),
        4: Node(4, 2.0, 5.0, 0.0),
        5: Node(5, -1.0, 3.0, 0.0),
    }
    elements = {
        101: Element(101, 1, 2, "elasticBeamColumn", {}),
        102: Element(102, 2, 3, "elasticBeamColumn", {}),
        103: Element(103, 3, 4, "elasticBeamColumn", {}),
        104: Element(104, 4, 5, "elasticBeamColumn", {}),
        105: Element(105, 5, 1, "elasticBeamColumn", {}),
    }
    entry = LoadEntry(
        id=1,
        case_id="DL",
        kind="floor",
        target=(1, 2, 3, 4, 5),
        payload=FloorLoadEntry(
            magnitude=1.5, direction="-z", distribution="two_way", target_nodes=(1, 2, 3, 4, 5)
        ),
    )

    contributions = convert_floor_entry(entry, nodes, elements)

    def _edge_length(tag_a: int, tag_b: int) -> float:
        a, b = nodes[tag_a], nodes[tag_b]
        return math.hypot(b.x - a.x, b.y - a.y)

    edge_lengths = {
        101: _edge_length(1, 2),
        102: _edge_length(2, 3),
        103: _edge_length(3, 4),
        104: _edge_length(4, 5),
        105: _edge_length(5, 1),
    }
    total_reaction = sum(
        (values[2] + values[5]) / 2.0 * edge_lengths[tag] for tag, values in contributions.items()
    )
    # Shoelace area of the pentagon above.
    points = [(0.0, 0.0), (4.0, 0.0), (5.0, 3.0), (2.0, 5.0), (-1.0, 3.0)]
    shoelace = sum(
        points[i][0] * points[(i + 1) % 5][1] - points[(i + 1) % 5][0] * points[i][1] for i in range(5)
    )
    area = abs(shoelace) / 2.0
    assert total_reaction == pytest.approx(-1.5 * area, rel=1e-2)


def test_activating_a_combination_case_makes_build_model_reflect_its_floor_entry() -> None:
    """A generated case's floor entry no longer gets baked into
    ``canvas.element_loads`` by the combination-activation bridge itself
    (that would double it up now that ``build_model()`` reads every active
    case's floor entries live - see canvas_model_build.py) - it reaches
    analysis once ``create_load_case_from_combination(..., activate_for_
    analysis=True)`` makes the generated case active, purely through that
    live read."""
    canvas = _canvas()
    canvas.ndm = 3
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(6.0, 0.0)
    n3 = canvas.add_node(6.0, 4.0)
    n4 = canvas.add_node(0.0, 4.0)
    e_short = canvas.add_member(n2, n3)
    canvas.add_member(n1, n2)
    canvas.add_member(n3, n4)
    canvas.add_member(n4, n1)

    canvas.add_load_case("DL", kind=LoadCaseKind.DEAD)
    canvas.add_load_entry(
        "DL",
        "floor",
        (n1, n2, n3, n4),
        FloorLoadEntry(
            magnitude=2.0,
            direction="-z",
            distribution="two_way",
            target_nodes=(n1, n2, n3, n4),
        ),
    )
    canvas.add_load_combination("ULS")
    canvas.update_load_combination("ULS", {LoadCaseKind.DEAD: 1.0})

    canvas.create_load_case_from_combination("ULS", "ULS_APPLIED", activate_for_analysis=True)

    assert canvas.active_load_case_id == "ULS_APPLIED"
    model = canvas.build_model()
    element_loads = {load.element_tag: load for load in model.element_loads}
    assert e_short in element_loads
    short_edge_udl = -2.0 * 4.0 / 4.0  # same closed-form short-edge value as above
    assert element_loads[e_short].wz == pytest.approx(short_edge_udl)
    assert element_loads[e_short].wz_j == pytest.approx(short_edge_udl)
