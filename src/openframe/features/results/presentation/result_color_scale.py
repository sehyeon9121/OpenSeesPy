"""Blue-to-red scale shared by the result legend and the coloured members.

Keeping one definition is what lets the legend actually mean something: a member drawn
at 60% of the scale uses exactly the colour 60% along the legend bar.
"""

from PySide6.QtGui import QColor

#: Must stay in step with the ``QProgressBar#resultLegend`` gradient in app/shell/theme.py.
_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (37, 99, 235)),  # #2563eb
    (0.5, (247, 209, 84)),  # #f7d154
    (1.0, (229, 72, 77)),  # #e5484d
)


def color_for_ratio(ratio: float) -> QColor:
    """Colour at ``ratio`` of the way along the scale, clamped to its ends."""
    position = min(1.0, max(0.0, ratio))
    for index in range(len(_STOPS) - 1):
        low_position, low_color = _STOPS[index]
        high_position, high_color = _STOPS[index + 1]
        if position > high_position:
            continue
        span = high_position - low_position
        blend = 0.0 if span <= 0.0 else (position - low_position) / span
        return QColor(
            *(
                round(low + (high - low) * blend)
                for low, high in zip(low_color, high_color, strict=True)
            )
        )
    return QColor(*_STOPS[-1][1])


def ratio_of(value: float, maximum: float) -> float:
    """Where ``value`` sits on a scale running from zero to ``maximum``."""
    if maximum <= 0.0:
        return 0.0
    return abs(value) / maximum
