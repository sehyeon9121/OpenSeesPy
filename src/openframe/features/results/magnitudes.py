"""Per-member magnitudes of the active result quantity, and the range they span.

These are the numbers the colour legend is built from, so they are kept free of Qt.
"""

import math

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.results.diagrams import member_diagrams

#: Result types that colour members by a member force.
FORCE_INDEX = {"axial": 0, "shear": 1, "moment": 2}
#: Result types that colour members by how far their nodes moved.
DISPLACEMENT_TYPES = frozenset({"overview", "deformation", "displacement"})

#: Magnitudes this far below the largest one are solver noise. Reporting them verbatim
#: would put values like 4e-14 on the legend, which reads as a defect rather than zero.
_RELATIVE_TOLERANCE = 1.0e-9


def member_magnitudes(
    model: StructuralModel, result: AnalysisResult, result_type: str
) -> dict[int, float]:
    """Peak absolute value of the active quantity, per element tag.

    An empty mapping means the active result type has nothing to colour by.
    """
    if result_type in FORCE_INDEX:
        if model.ndm == 3:
            magnitudes_3d: dict[int, float] = {}
            for element in result.element_results.values():
                values = (*element.local_forces, *((0.0,) * 12))[:12]
                if result_type == "axial":
                    value = max(abs(values[0]), abs(values[6]))
                elif result_type == "shear":
                    value = max(
                        math.hypot(values[1], values[2]),
                        math.hypot(values[7], values[8]),
                    )
                else:
                    value = max(
                        math.hypot(values[4], values[5]),
                        math.hypot(values[10], values[11]),
                    )
                magnitudes_3d[element.element_tag] = value
            return _denoise(magnitudes_3d)
        index = FORCE_INDEX[result_type]
        magnitudes: dict[int, float] = {}
        for element in result.element_results.values():
            try:
                diagram = member_diagrams(element)[index]
            except ValueError:
                continue
            magnitudes[element.element_tag] = max(
                (abs(point.value) for point in diagram.points), default=0.0
            )
        return _denoise(magnitudes)

    if result_type in DISPLACEMENT_TYPES:
        return _denoise(
            {
                element.tag: max(
                    _displacement(result, element.node_i, model.ndm),
                    _displacement(result, element.node_j, model.ndm),
                )
                for element in model.elements.values()
            }
        )

    return {}


def magnitude_range(magnitudes: dict[int, float]) -> tuple[float, float]:
    """Lowest and highest magnitude, or (0, 0) when there is nothing to show."""
    if not magnitudes:
        return 0.0, 0.0
    values = magnitudes.values()
    return min(values), max(values)


def _denoise(magnitudes: dict[int, float]) -> dict[int, float]:
    largest = max(magnitudes.values(), default=0.0)
    threshold = largest * _RELATIVE_TOLERANCE
    return {
        tag: 0.0 if value <= threshold else value for tag, value in magnitudes.items()
    }


def _displacement(result: AnalysisResult, node_tag: int, ndm: int = 2) -> float:
    node_result = result.node_results.get(node_tag)
    if node_result is None:
        return 0.0
    values = (*node_result.displacement, 0.0, 0.0)
    if ndm == 3:
        return math.hypot(float(values[0]), float(values[1]), float(values[2]))
    return math.hypot(float(values[0]), float(values[1]))
