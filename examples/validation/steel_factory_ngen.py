"""nGen 철골 공장 예제(C07_T05_P000_ST_01)를 OpenFrame 3D 캔버스로 재현한다.

.meb 는 nGen 전용 바이너리라 절점·부재를 바이트 단위로 복원하지 못했다.
대신 파일에서 확인된 강종·하중케이스·조합 이름·크레인 용량(-250 kN)과,
반복 등장한 6 m / 24 m 치수 힌트를 기준으로 문형 골조를 만든다.

하중 크기 중 .meb 에 숫자가 없던 지붕 DL/LL·풍압은 KBC 공장 지붕의 흔한
값으로 넣었고, 스크립트 상단 ASSUMED_* 상수에 모아 두었다. nGen 표가
생기면 그 숫자만 갈아 끼우면 된다. 자중은 단면·단위중량에서 결정되므로
추측이 아니다.

비교는 우선 활성 케이스 DL (자중 + 지붕 고정하중) 의 연직 반력 합이
가력 합과 맞는지부터 본다. MIDAS 변위·부재력 표가 오면 MIDAS_REFERENCE
에 채워 같은 함수로 오차를 낸다.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    LoadCaseKind,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    SelfWeightEntry,
)
from openframe.core.domain.section_properties import h_section_properties
from openframe.core.domain.units import (
    mm2_to_length_unit,
    mm3_to_length_unit,
    mm4_to_length_unit,
    mm_to_length_unit,
    mpa_to_stress_unit,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver
from openframe.features.model.drawing import PlaneKind
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage

OFSM_PATH = Path(__file__).resolve().parent / "midas_ngen_steel_factory.ofsm"

# Geometry reconstructed from MEB clues (6.0 m repeats, 24 m span hint).
BAY_X_M = 6.0
SPAN_Y_M = 24.0
N_BAYS = 5
EAVE_Z_M = 8.0
RIDGE_Z_M = 10.0
CRANE_Z_M = 6.0

# SS400 in the MEB; nGen stores E as 205000 MPa (2.05e8 kN/m² showed up 4 times).
STEEL_E_MPA = 205_000.0
STEEL_FY_MPA = 245.0
STEEL_NU = 0.3
STEEL_UNIT_WEIGHT_KN_M3 = 76.982

# Roof loads were not recoverable from the MEB. Typical KBC factory roof.
ASSUMED_ROOF_DL_KNM2 = 0.5
ASSUMED_ROOF_LL_KNM2 = 0.5
# Windward-only equivalent of OpenFrame wind defaults q0=1, Gf=0.85, Cp=1.3.
ASSUMED_WIND_Q_KNM2 = 1.0 * 0.85 * 1.3

# Crane capacity string in the MEB was "-250kN". Vertical split equally to
# both runway girders at mid-length; horizontal is KBC 10% of the lift load.
CRANE_VERTICAL_KN = 250.0
CRANE_HORIZONTAL_KN = 25.0

#: Fill these from an nGen result table to get a real MIDAS comparison.
#: Keys are node tags in this reconstructed model, so they only match after
#: the geometry is confirmed against the original. Empty means "not compared".
MIDAS_REFERENCE: dict[str, dict[int, tuple[float, float, float]]] = {
    "DL_disp_m": {},
}

ACCEPTABLE_DISP_REL_ERROR = 0.05

_X_LINES = tuple(i * BAY_X_M for i in range(N_BAYS + 1))
_Y_WALLS = (0.0, SPAN_Y_M)
_RIDGE_Y = SPAN_Y_M / 2.0


def _h_section_kwargs(
    *,
    designation: str,
    section_id: str,
    H_mm: float,
    B_mm: float,
    tw_mm: float,
    tf_mm: float,
) -> dict[str, object]:
    """Master-DB millimetre formulas, converted to this model's kN/m system."""
    props = h_section_properties(H_mm, B_mm, tw_mm, tf_mm)
    elastic = mpa_to_stress_unit(STEEL_E_MPA, "kN", "m")
    return {
        "shape": "H/I Section",
        "source": "custom",
        "dimensions": {
            "H": mm_to_length_unit(H_mm, "m"),
            "B": mm_to_length_unit(B_mm, "m"),
            "tw": mm_to_length_unit(tw_mm, "m"),
            "tf": mm_to_length_unit(tf_mm, "m"),
        },
        "area": mm2_to_length_unit(props.area_mm2, "m"),
        "iy": mm4_to_length_unit(props.Iy_mm4, "m"),
        "iz": mm4_to_length_unit(props.Iz_mm4, "m"),
        "j": mm4_to_length_unit(props.J_mm4, "m"),
        "elastic": elastic,
        "shear_modulus": elastic / (2.0 * (1.0 + STEEL_NU)),
        "density": STEEL_UNIT_WEIGHT_KN_M3,
        "section_id": section_id,
        "material_id": "MAT-001",
        "material_category": "Structural Steel",
        "material_grade": "SS400",
        "fy": mpa_to_stress_unit(STEEL_FY_MPA, "kN", "m"),
        "zy": mm3_to_length_unit(props.Zy_mm3, "m") if props.Zy_mm3 is not None else None,
        "zz": mm3_to_length_unit(props.Zz_mm3, "m") if props.Zz_mm3 is not None else None,
        "_designation": designation,
    }


SECTIONS = {
    "column": _h_section_kwargs(
        designation="H-350x350x12x19",
        section_id="SEC-COL",
        H_mm=350,
        B_mm=350,
        tw_mm=12,
        tf_mm=19,
    ),
    "rafter": _h_section_kwargs(
        designation="H-400x200x8x13",
        section_id="SEC-RAFTER",
        H_mm=400,
        B_mm=200,
        tw_mm=8,
        tf_mm=13,
    ),
    "crane": _h_section_kwargs(
        designation="H-582x300x12x17",
        section_id="SEC-CRANE",
        H_mm=582,
        B_mm=300,
        tw_mm=12,
        tf_mm=17,
    ),
    "strut": _h_section_kwargs(
        designation="H-200x200x8x12",
        section_id="SEC-STRUT",
        H_mm=200,
        B_mm=200,
        tw_mm=8,
        tf_mm=12,
    ),
    "brace": _h_section_kwargs(
        designation="H-150x150x7x10",
        section_id="SEC-BRACE",
        H_mm=150,
        B_mm=150,
        tw_mm=7,
        tf_mm=10,
    ),
}


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _apply_section(canvas, tags: list[int], spec: dict[str, object]) -> None:
    if not tags:
        return
    kwargs = {k: v for k, v in spec.items() if not k.startswith("_") and k != "_designation"}
    canvas.selected_elements = set(tags)
    canvas.apply_full_section_to_selection(**kwargs)


def _members_with(canvas, section_id: str) -> list[int]:
    return [
        tag
        for tag, element in canvas.elements.items()
        if element.properties.get("section_id") == section_id
    ]


def _member_covers_x(canvas, tag: int, x: float) -> bool:
    element = canvas.elements[tag]
    xi = canvas.nodes[element.node_i].x
    xj = canvas.nodes[element.node_j].x
    lo, hi = (xi, xj) if xi <= xj else (xj, xi)
    return lo - 1.0e-9 <= x <= hi + 1.0e-9


def _connect(canvas, a: int, b: int, bucket: list[int]) -> int | None:
    tag = canvas.add_member(a, b)
    if tag is not None:
        bucket.append(tag)
    return tag


def _scale_payload(payload, factor: float):
    if isinstance(payload, SelfWeightEntry):
        return replace(
            payload,
            factor_x=payload.factor_x * factor,
            factor_y=payload.factor_y * factor,
            factor_z=payload.factor_z * factor,
        )
    if isinstance(payload, MemberPointLoadEntry):
        return replace(payload, value=payload.value * factor)
    if isinstance(payload, MemberDistributedLoadEntry):
        return replace(
            payload,
            start_value=payload.start_value * factor,
            end_value=payload.end_value * factor,
        )
    return payload


def build_steel_factory_page() -> ModelingInterfacePage:
    """A 3D ModelingInterfacePage whose canvas is the reconstructed factory."""
    _app()
    page = ModelingInterfacePage(start_in_3d=True)
    page._model_name = "nGen 철골 공장 (C07_T05_P000_ST_01 재현)"
    canvas = page.canvas
    canvas.enter_3d_mode()

    # Default plane is already 1F @ Z=0. Crane girder and eave get their own
    # plan planes so the 3D level bar matches the three real elevations.
    canvas.add_level(CRANE_Z_M, "크레인", PlaneKind.XY)
    canvas.add_level(EAVE_Z_M, "처마", PlaneKind.XY)
    canvas.add_level(RIDGE_Z_M, "용마루", PlaneKind.XY)
    canvas.add_story("기초", 0.0, rigid_diaphragm=False)
    canvas.add_story("크레인", CRANE_Z_M, rigid_diaphragm=False)
    canvas.add_story("처마", EAVE_Z_M, rigid_diaphragm=False)

    with canvas.pause_history():
        node_at: dict[tuple[float, float, float], int] = {}

        def node(x: float, y: float, z: float) -> int:
            key = (round(x, 9), round(y, 9), round(z, 9))
            if key not in node_at:
                node_at[key] = canvas._add_node_at((x, y, z))
            return node_at[key]

        for x in _X_LINES:
            for y in _Y_WALLS:
                node(x, y, 0.0)
                node(x, y, CRANE_Z_M)
                node(x, y, EAVE_Z_M)
            node(x, _RIDGE_Y, RIDGE_Z_M)

        columns: list[int] = []
        rafters: list[int] = []
        crane_girders: list[int] = []
        struts: list[int] = []
        braces: list[int] = []

        for x in _X_LINES:
            for y in _Y_WALLS:
                _connect(canvas, node(x, y, 0.0), node(x, y, CRANE_Z_M), columns)
                _connect(canvas, node(x, y, CRANE_Z_M), node(x, y, EAVE_Z_M), columns)
            _connect(canvas, node(x, 0.0, EAVE_Z_M), node(x, _RIDGE_Y, RIDGE_Z_M), rafters)
            _connect(canvas, node(x, SPAN_Y_M, EAVE_Z_M), node(x, _RIDGE_Y, RIDGE_Z_M), rafters)

        for i, x0 in enumerate(_X_LINES[:-1]):
            x1 = _X_LINES[i + 1]
            for y in _Y_WALLS:
                _connect(canvas, node(x0, y, CRANE_Z_M), node(x1, y, CRANE_Z_M), crane_girders)
                _connect(canvas, node(x0, y, EAVE_Z_M), node(x1, y, EAVE_Z_M), struts)
            _connect(
                canvas,
                node(x0, _RIDGE_Y, RIDGE_Z_M),
                node(x1, _RIDGE_Y, RIDGE_Z_M),
                struts,
            )

        # Stamp frame sections before braces exist. add_member splits a
        # crossing, and the split copies the host's properties - if a brace
        # later cuts a rafter, both pieces must stay rafters, not inherit
        # an empty leftover bucket that we then pin-release as braces.
        _apply_section(canvas, columns, SECTIONS["column"])
        _apply_section(canvas, rafters, SECTIONS["rafter"])
        _apply_section(canvas, crane_girders, SECTIONS["crane"])
        _apply_section(canvas, struts, SECTIONS["strut"])

        # End-bay X-bracing. add_member splits true 3D crossings, which is
        # what we want for an X-brace joint - do not pre-insert the mid node.
        for x0, x1 in ((_X_LINES[0], _X_LINES[1]), (_X_LINES[-2], _X_LINES[-1])):
            for y in _Y_WALLS:
                _connect(canvas, node(x0, y, 0.0), node(x1, y, EAVE_Z_M), braces)
                _connect(canvas, node(x1, y, 0.0), node(x0, y, EAVE_Z_M), braces)
        for x in (_X_LINES[0], _X_LINES[-1]):
            _connect(canvas, node(x, 0.0, 0.0), node(x, SPAN_Y_M, EAVE_Z_M), braces)
            _connect(canvas, node(x, SPAN_Y_M, 0.0), node(x, 0.0, EAVE_Z_M), braces)
        for x0, x1 in ((_X_LINES[0], _X_LINES[1]), (_X_LINES[-2], _X_LINES[-1])):
            _connect(
                canvas,
                node(x0, 0.0, EAVE_Z_M),
                node(x1, _RIDGE_Y, RIDGE_Z_M),
                braces,
            )
            _connect(
                canvas,
                node(x1, 0.0, EAVE_Z_M),
                node(x0, _RIDGE_Y, RIDGE_Z_M),
                braces,
            )
            _connect(
                canvas,
                node(x0, SPAN_Y_M, EAVE_Z_M),
                node(x1, _RIDGE_Y, RIDGE_Z_M),
                braces,
            )
            _connect(
                canvas,
                node(x1, SPAN_Y_M, EAVE_Z_M),
                node(x0, _RIDGE_Y, RIDGE_Z_M),
                braces,
            )

        unsectioned = [
            tag
            for tag, element in canvas.elements.items()
            if not element.properties.get("section_id")
        ]
        _apply_section(canvas, unsectioned, SECTIONS["brace"])
        # Do not pin-release brace ends. add_member splits an X-brace at its
        # crossing, and releasing both ends of every piece would leave that
        # mid-node with only axial members in one plane - it can pop out of
        # plane as a mechanism. Keep the small H as a frame so the joint has
        # bending stiffness; nGen's own brace is a truss that typically does
        # not even share a mid-node.
        rafters = _members_with(canvas, "SEC-RAFTER")
        columns = _members_with(canvas, "SEC-COL")
        crane_mid_girders = [
            tag
            for tag in _members_with(canvas, "SEC-CRANE")
            if _member_covers_x(canvas, tag, 15.0)
        ]

        bases = [tag for tag, item in canvas.nodes.items() if abs(item.z) <= 1.0e-9]
        canvas.selected_nodes = set(bases)
        canvas.apply_support_to_selection((True, True, True, False, False, False))

        page._save_user_material(
            {
                "name": "SS400",
                "category": "Structural Steel",
                "grade": "SS400",
                "elastic": mpa_to_stress_unit(STEEL_E_MPA, "kN", "m"),
                "density": STEEL_UNIT_WEIGHT_KN_M3,
                "fy": mpa_to_stress_unit(STEEL_FY_MPA, "kN", "m"),
            }
        )
        # _save_user_material always mints MAT-001 for the first row; members
        # already reference that id so we do not rename it.
        for spec in SECTIONS.values():
            page._save_user_section(
                {
                    "name": spec["_designation"],
                    "shape": spec["shape"],
                    "source": spec["source"],
                    "dimensions": spec["dimensions"],
                    "area": spec["area"],
                    "iy": spec["iy"],
                    "iz": spec["iz"],
                    "j": spec["j"],
                    "database_id": spec["section_id"],
                }
            )

        roof_w = ASSUMED_ROOF_DL_KNM2 * BAY_X_M
        roof_ll = ASSUMED_ROOF_LL_KNM2 * BAY_X_M
        gable_w = ASSUMED_WIND_Q_KNM2 * (SPAN_Y_M / 2.0)
        wall_w = ASSUMED_WIND_Q_KNM2 * BAY_X_M

        canvas.add_load_case("DL", LoadCaseKind.DEAD, "자중 + 지붕 고정하중")
        canvas.add_load_case("LL", LoadCaseKind.ROOF_LIVE, "지붕 활하중")
        canvas.add_load_case("CLV", LoadCaseKind.OTHER, "크레인 연직 250 kN")
        canvas.add_load_case("CLH", LoadCaseKind.OTHER, "크레인 수평 25 kN")
        canvas.add_load_case("WL_0", LoadCaseKind.WIND, "풍하중 0° (+X, 박공)")
        canvas.add_load_case("WL_90", LoadCaseKind.WIND, "풍하중 90° (+Y, 장변)")

        canvas.add_load_entry("DL", "self_weight", (), SelfWeightEntry(factor_z=-1.0))
        roof_payload_dl = MemberDistributedLoadEntry(
            coordinate_system="global",
            direction="z",
            start_value=-roof_w,
            end_value=-roof_w,
        )
        roof_payload_ll = MemberDistributedLoadEntry(
            coordinate_system="global",
            direction="z",
            start_value=-roof_ll,
            end_value=-roof_ll,
        )
        for tag in rafters:
            canvas.add_load_entry("DL", "member_partial", (tag,), roof_payload_dl)
            canvas.add_load_entry("LL", "member_partial", (tag,), roof_payload_ll)

        wheel = -CRANE_VERTICAL_KN / 2.0
        lateral = CRANE_HORIZONTAL_KN / 2.0
        for tag in crane_mid_girders:
            canvas.add_load_entry(
                "CLV",
                "member_point",
                (tag,),
                MemberPointLoadEntry(
                    coordinate_system="global", direction="z", value=wheel, position=0.5
                ),
            )
            canvas.add_load_entry(
                "CLH",
                "member_point",
                (tag,),
                MemberPointLoadEntry(
                    coordinate_system="global", direction="y", value=lateral, position=0.5
                ),
            )

        gable_payload = MemberDistributedLoadEntry(
            coordinate_system="global",
            direction="x",
            start_value=gable_w,
            end_value=gable_w,
        )
        wall_payload = MemberDistributedLoadEntry(
            coordinate_system="global",
            direction="y",
            start_value=wall_w,
            end_value=wall_w,
        )
        for tag, element in canvas.elements.items():
            if element.properties.get("section_id") != "SEC-COL":
                continue
            ni, nj = canvas.nodes[element.node_i], canvas.nodes[element.node_j]
            xs = {ni.x, nj.x}
            ys = {ni.y, nj.y}
            if xs <= {0.0}:
                canvas.add_load_entry("WL_0", "member_partial", (tag,), gable_payload)
            if ys <= {0.0}:
                canvas.add_load_entry("WL_90", "member_partial", (tag,), wall_payload)

        canvas.add_load_combination("1.2DL+1.0LL")
        canvas.update_load_combination(
            "1.2DL+1.0LL", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.ROOF_LIVE: 1.0}
        )
        # Named like the MEB combination strings. Factors that cannot be
        # expressed with LoadCaseKind (CLV vs CLH, WL_0 vs WL_90) are baked
        # into extra static cases below instead of the kind-keyed combination.
        canvas.add_load_combination("1.2DL+1.0LL+1.3WL")
        canvas.update_load_combination(
            "1.2DL+1.0LL+1.3WL",
            {LoadCaseKind.DEAD: 1.2, LoadCaseKind.ROOF_LIVE: 1.0, LoadCaseKind.WIND: 1.3},
        )

        def _bake(name: str, parts: list[tuple[str, float]]) -> None:
            canvas.add_load_case(name, LoadCaseKind.OTHER, "nGen 조합을 계수 적용해 복사")
            for source, factor in parts:
                for entry in list(canvas.load_entries.values()):
                    if entry.case_id != source:
                        continue
                    canvas.add_load_entry(
                        name, entry.kind, entry.target, _scale_payload(entry.payload, factor)
                    )

        _bake(
            "1.2DL+1.0LL+1.0CLV+1.0CLH",
            [("DL", 1.2), ("LL", 1.0), ("CLV", 1.0), ("CLH", 1.0)],
        )
        _bake(
            "1.2DL+1.0LL+1.3WL_0",
            [("DL", 1.2), ("LL", 1.0), ("WL_0", 1.3)],
        )
        canvas.active_load_case_id = "DL"

    return page


def expected_dl_downward_kn(page: ModelingInterfacePage) -> float:
    """Positive downward force (kN) that DL should put into the supports."""
    canvas = page.canvas
    weight = 0.0
    for element in canvas.elements.values():
        ni, nj = canvas.nodes[element.node_i], canvas.nodes[element.node_j]
        length = math.dist((ni.x, ni.y, ni.z), (nj.x, nj.y, nj.z))
        area = float(element.properties["A"])
        density = float(element.properties["density"])
        weight += density * area * length
    roof = 0.0
    for entry in canvas.load_entries.values():
        if entry.case_id != "DL" or entry.kind != "member_partial":
            continue
        payload = entry.payload
        if not isinstance(payload, MemberDistributedLoadEntry):
            continue
        element = canvas.elements[entry.target[0]]
        ni, nj = canvas.nodes[element.node_i], canvas.nodes[element.node_j]
        length = math.dist((ni.x, ni.y, ni.z), (nj.x, nj.y, nj.z))
        roof += -payload.start_value * length
    return weight + roof


def solve_active_case(page: ModelingInterfacePage):
    result = MaterialFreeStaticsSolver().solve(page.canvas.build_model())
    return result


def vertical_reaction_sum(result) -> float:
    return sum(item.reaction[2] for item in result.node_results.values() if item.reaction)


def max_abs_displacement(result) -> tuple[int, float, tuple[float, ...]]:
    best_tag = 0
    best = 0.0
    best_u = (0.0, 0.0, 0.0)
    for tag, item in result.node_results.items():
        disp = item.displacement
        mag = math.sqrt(disp[0] ** 2 + disp[1] ** 2 + disp[2] ** 2)
        if mag > best:
            best_tag, best, best_u = tag, mag, disp
    return best_tag, best, best_u


def compare_with_midas(result, case_key: str = "DL_disp_m") -> list[str]:
    """One line per node that has a MIDAS reference displacement."""
    lines: list[str] = []
    refs = MIDAS_REFERENCE.get(case_key, {})
    if not refs:
        lines.append("MIDAS 변위 표가 아직 없습니다. nGen 결과에서 UX/UY/UZ 를 채워 주세요.")
        return lines
    for tag, (ux, uy, uz) in sorted(refs.items()):
        item = result.node_results.get(tag)
        if item is None:
            lines.append(f"  node {tag}: OpenFrame 결과에 없음")
            continue
        ox, oy, oz = item.displacement[:3]
        for name, midas, ops in (("UX", ux, ox), ("UY", uy, oy), ("UZ", uz, oz)):
            denom = abs(midas) if abs(midas) > 1.0e-9 else 1.0
            err = abs(ops - midas) / denom
            flag = "OK" if err <= ACCEPTABLE_DISP_REL_ERROR else "FAIL"
            lines.append(
                f"  node {tag} {name}: MIDAS={midas:.5f}  OF={ops:.5f}  err={err:.2%}  {flag}"
            )
    return lines


def write_ofsm(page: ModelingInterfacePage, path: Path = OFSM_PATH) -> Path:
    path.write_text(
        json.dumps(page.to_project_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\r\n",
    )
    return path


def main() -> None:
    page = build_steel_factory_page()
    path = write_ofsm(page)
    result = solve_active_case(page)
    expected = expected_dl_downward_kn(page)
    rz = vertical_reaction_sum(result)
    tag, mag, disp = max_abs_displacement(result)
    print(f"wrote {path}")
    print(f"nodes={len(page.canvas.nodes)}  members={len(page.canvas.elements)}")
    print(f"DL status={result.status.value}")
    print(f"DL downward load={expected:.3f} kN  sum Rz={rz:.3f} kN")
    print(f"max |U| node {tag}: {mag*1000:.2f} mm  U=({disp[0]:.5f}, {disp[1]:.5f}, {disp[2]:.5f})")
    print("MIDAS comparison:")
    for line in compare_with_midas(result):
        print(line)


if __name__ == "__main__":
    main()
