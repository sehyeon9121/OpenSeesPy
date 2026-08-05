import pytest

from openframe.core.domain import Element, Node
from openframe.features.model.drawing import (
    SnapKind,
    SnapOptions,
    apply_ortho,
    resolve_snap,
)

_NO_GRID = SnapOptions(grid=0.0)


def _beam() -> tuple[dict[int, Node], dict[int, Element]]:
    nodes = {1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)}
    return nodes, {1: Element(1, 1, 2, "frame")}


def test_existing_node_wins_over_the_grid() -> None:
    nodes, elements = _beam()

    result = resolve_snap(nodes, elements, (3.94, 0.04), tolerance=0.2)

    assert result.kind is SnapKind.NODE
    assert result.node_tag == 2
    assert result.point == pytest.approx((4.0, 0.0))


def test_member_midpoint_is_offered_before_an_arbitrary_point_on_the_member() -> None:
    nodes, elements = _beam()

    result = resolve_snap(nodes, elements, (2.03, 0.05), tolerance=0.2, options=_NO_GRID)

    assert result.kind is SnapKind.MIDPOINT
    assert result.element_tag == 1
    assert result.position == pytest.approx(0.5)


def test_arbitrary_position_on_a_member_is_reachable_for_an_off_grid_support() -> None:
    nodes, elements = _beam()

    result = resolve_snap(nodes, elements, (1.4, 0.06), tolerance=0.2, options=_NO_GRID)

    assert result.kind is SnapKind.MEMBER
    assert result.element_tag == 1
    assert result.position == pytest.approx(0.35)
    assert result.point == pytest.approx((1.4, 0.0))


def test_crossing_braces_expose_their_intersection() -> None:
    nodes = {
        1: Node(1, 0.0, 0.0),
        2: Node(2, 4.0, 4.0),
        3: Node(3, 0.0, 4.0),
        4: Node(4, 4.0, 0.0),
    }
    elements = {1: Element(1, 1, 2, "frame"), 2: Element(2, 3, 4, "frame")}

    result = resolve_snap(nodes, elements, (2.05, 1.95), tolerance=0.2, options=_NO_GRID)

    assert result.kind is SnapKind.INTERSECTION
    assert result.point == pytest.approx((2.0, 2.0))


def test_members_sharing_a_node_report_no_intersection_there() -> None:
    nodes = {1: Node(1, 0.0, 0.0), 2: Node(2, 0.0, 4.0), 3: Node(3, 5.0, 6.0)}
    elements = {1: Element(1, 1, 2, "frame"), 2: Element(2, 2, 3, "frame")}

    result = resolve_snap(nodes, elements, (0.05, 4.02), tolerance=0.3, options=_NO_GRID)

    assert result.kind is SnapKind.NODE
    assert result.node_tag == 2


def test_cursor_far_from_everything_keeps_its_own_point() -> None:
    nodes, elements = _beam()

    result = resolve_snap(nodes, elements, (9.37, 3.21), tolerance=0.2, options=_NO_GRID)

    assert result.kind is SnapKind.FREE
    assert result.point == pytest.approx((9.37, 3.21))


def test_grid_rounds_a_free_cursor_when_it_is_enabled() -> None:
    nodes, elements = _beam()

    result = resolve_snap(
        nodes, elements, (7.05, 2.98), tolerance=0.2, options=SnapOptions(grid=0.5)
    )

    assert result.kind is SnapKind.GRID
    assert result.point == pytest.approx((7.0, 3.0))


def test_ortho_locks_the_angle_but_keeps_the_length_the_cursor_shows() -> None:
    anchor = (0.0, 0.0)

    assert apply_ortho(anchor, (4.0, 0.3)) == pytest.approx((4.011234, 0.0), abs=1.0e-5)
    assert apply_ortho(anchor, (0.2, -3.0)) == pytest.approx((0.0, -3.006659), abs=1.0e-5)


def test_ortho_with_a_45_degree_increment_serves_diagonal_bracing() -> None:
    locked = apply_ortho((0.0, 0.0), (3.0, 3.2), increment_degrees=45.0)

    assert locked[0] == pytest.approx(locked[1])
    assert locked[0] == pytest.approx(3.1016, abs=1.0e-3)
