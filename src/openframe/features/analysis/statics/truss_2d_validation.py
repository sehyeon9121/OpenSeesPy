"""Reject invalid plane-truss inputs before a textbook equilibrium solve."""

import math

import numpy as np

from openframe.core.domain import StructuralModel
from openframe.core.domain.geometric_transform import boundary_local_axes


def validate_truss(model: StructuralModel) -> None:
    indexes = {tag: 2*i for i, tag in enumerate(model.nodes)}
    rows = []
    for node in model.nodes.values():
        if not all(math.isfinite(value) for value in (node.x, node.y)):
            raise ValueError(f"절점 {node.tag}: 좌표는 유한한 숫자여야 합니다.")
    for element in model.elements.values():
        if element.node_i not in indexes or element.node_j not in indexes:
            raise ValueError(f"부재 {element.tag}: 연결 절점이 없습니다.")
        a, b = model.nodes[element.node_i], model.nodes[element.node_j]
        length = math.hypot(b.x-a.x, b.y-a.y)
        if length <= 0:
            raise ValueError(f"부재 {element.tag}: 길이는 0보다 커야 합니다.")
        for key in ("E", "A"):
            if key in element.properties:
                try:
                    value = float(element.properties[key])
                except (ValueError, TypeError) as error:
                    raise ValueError(f"부재 {element.tag}: {key}는 양수여야 합니다.") from error
                if not math.isfinite(value) or value <= 0:
                    raise ValueError(f"부재 {element.tag}: {key}는 유한한 양수여야 합니다.")
        row = np.zeros(2*len(indexes))
        direction = np.array([b.x-a.x, b.y-a.y])/length
        row[indexes[a.tag]:indexes[a.tag]+2] = -direction
        row[indexes[b.tag]:indexes[b.tag]+2] = direction
        rows.append(row)
    for boundary in model.boundaries:
        if boundary.node_tag not in indexes:
            raise ValueError(f"지점 절점 {boundary.node_tag}가 없습니다.")
        if not math.isfinite(boundary.angle) or (boundary.is_inclined and boundary.angle_axis != 'z'):
            raise ValueError("2D 경사지점은 유한한 Z축 회전각만 지원합니다.")
        axes = boundary_local_axes(boundary.angle, boundary.angle_axis)
        for dof in (0, 1):
            fixed = dof < len(boundary.restraints) and boundary.restraints[dof]
            spring = boundary.spring_stiffnesses[dof] if dof < len(boundary.spring_stiffnesses) else None
            if spring is not None and (not math.isfinite(spring) or spring < 0):
                raise ValueError(f"절점 {boundary.node_tag}: 스프링 강성은 유한한 0 이상의 값이어야 합니다.")
            if fixed or spring:
                row = np.zeros(2*len(indexes))
                # Inclined rigid constraints are local; springs are global.
                vector = axes[dof][:2] if fixed else np.eye(2)[dof]
                row[indexes[boundary.node_tag]:indexes[boundary.node_tag]+2] = vector
                rows.append(row)
    # Positive stiffness magnitudes cannot change an ordinary truss mechanism.
    # Normalized compatibility rows avoid mixing E/A units into this rank test.
    # Prestressed corotational members can instead gain geometric stiffness.
    if rows and not any(element.prestress for element in model.elements.values()):
        if np.linalg.matrix_rank(np.array(rows)) < 2*len(indexes):
            raise ValueError("2D 트러스가 불안정합니다. 연결되지 않은 절점·부재 배치·지점 조건을 확인하세요.")

