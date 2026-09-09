"""2D distributed moment-curvature plasticity for the existing pushover worker.

Axial response stays elastic; each Lobatto section has a bilinear M-curvature
law with initial stiffness EI, yield moment Fy*Zy (the canvas uses I=Iy), and
post-yield stiffness b*EI. This is not a fibre/RC section or axial-moment
interaction model. All constants are in the model's current units.
"""

import math

from openframe.core.domain import Element, StructuralModel


def write_frame(
    lines: list[str], model: StructuralModel, element: Element,
    *, tag: int | None = None, node_i: int | None = None, node_j: int | None = None,
    release_i: bool | None = None, release_j: bool | None = None,
) -> None:
    tag = element.tag if tag is None else tag
    node_i = element.node_i if node_i is None else node_i
    node_j = element.node_j if node_j is None else node_j
    release_i = element.moment_release_i if release_i is None else release_i
    release_j = element.moment_release_j if release_j is None else release_j
    elastic, area, inertia = (float(element.properties[key]) for key in ("E", "A", "I"))
    if not all(math.isfinite(value) and value > 0 for value in (elastic, area, inertia)):
        raise ValueError(f"부재 {element.tag}: 유효한 E/A/I가 필요합니다.")
    fy = float(element.properties.get("Fy", 0.0))
    hardening = float(element.properties.get("StrainHardeningRatio", 0.02))
    if not math.isfinite(fy) or fy < 0 or not math.isfinite(hardening) or not 0 <= hardening <= 1:
        raise ValueError(f"부재 {element.tag}: fy≥0, 0≤b≤1이어야 합니다.")
    # Use a separate namespace from supports and legacy load subdivision tags.
    section_tag = 30_000_000 + tag * 4
    if fy > 0:
        plastic_modulus = float(element.properties.get("Zy") or 0.0)
        if not math.isfinite(plastic_modulus) or plastic_modulus <= 0:
            raise ValueError(f"부재 {element.tag}: 항복 모멘트 계산에 소성단면계수 Zy가 필요합니다.")
        category = str(element.properties.get("material_category", "")).lower()
        if "concrete" in category or "콘크리트" in category:
            raise ValueError("2D Pushover의 bilinear 단면은 RC 균열·철근 거동을 지원하지 않습니다.")
        lines.extend([
            f"ops.uniaxialMaterial('Elastic', {section_tag}, {elastic * area!r})",
            f"ops.uniaxialMaterial('Steel01', {section_tag + 1}, "
            f"{fy * plastic_modulus!r}, {elastic * inertia!r}, {hardening!r})",
            f"ops.section('Aggregator', {section_tag}, {section_tag}, 'P', "
            f"{section_tag + 1}, 'Mz')",
        ])
    else:
        lines.append(f"ops.section('Elastic', {section_tag}, {elastic!r}, {area!r}, {inertia!r})")
    ends = [node_i, node_j]
    for index, released in enumerate((release_i, release_j)):
        if not released:
            continue
        real = model.nodes[element.node_i if index == 0 else element.node_j]
        dummy = 60_000_000 + tag * 2 + index
        if dummy in model.nodes:
            raise ValueError(f"보조 절점 번호 {dummy}가 기존 절점과 중복됩니다.")
        lines.extend([
            f"ops.node({dummy}, {real.x!r}, {real.y!r})",
            f"ops.equalDOF({ends[index]}, {dummy}, 1, 2)",
        ])
        ends[index] = dummy
    lines.extend([
        f"ops.beamIntegration('Lobatto', {section_tag}, {section_tag}, 5)",
        f"ops.element('forceBeamColumn', {tag}, {ends[0]}, {ends[1]}, "
        f"1, {section_tag}, '-iter', 50, 1e-12)",
    ])
