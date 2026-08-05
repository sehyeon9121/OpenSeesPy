"""
opensees_builder.py
===================
역할: OpenSees 모델 생성 및 해석 실행 전담
단위계: N, mm, kg, s

─── 지원 해석 종류 ─────────────────────────────────────────────
  run_gravity_opensees()   : 중력 전용 해석 (이번 단계 구현 완료)
  run_opensees()           : 수평 지진 해석 (TODO: HS 단계에서 구현)

─── 모델 구성 ──────────────────────────────────────────────────
노드 구성:
  Base (z=0)     : 1–4 (corner), 101 (core)
  F1 (z=200)     : 5–8 (corner), 9  (master)
  F2 (z=400)     : 10–13(corner), 14 (master)
  F3 (z=600)     : 15–18(corner), 19 (master)
  F4 (z=800)     : 20–23(corner), 24 (master)
  Belt-bot(z=544): 201–204(corner), 221 (core)
  Belt-top(z=594): 205–208(corner), 222 (core)
  Belt-mid(z=569): 211–214 (face midpoint)

요소 그룹:
  COL_EXT   (24개) : 4각 기둥, 벨트 레벨에서 분할
  CORE       (6개) : 코어 기둥, 벨트 레벨에서 분할
  BELT_TC    (4개) : 벨트 상현재
  BELT_BC    (4개) : 벨트 하현재
  BELT_D    (16개) : 벨트 사선재
  OUTR       (8개) : 아웃리거
  합계: 62개 요소

금지 사항:
  - HS 알고리즘 import 금지
  - 목적함수·제약조건 직접 계산 금지
  - 비용 계산 금지
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import (
    BASE_Z, BELT_BOT_Z, BELT_MID_Z, BELT_TOP_Z,
    CENTER_X, CENTER_Y, CORNER_XY,
    DATA_DIR, E_MDF, G_MDF, GRAVITY_ACC, RHO_MDF,
    FLOOR_Z_LIST, FLOOR_GRAVITY_N,
)
from src.model.materials import get_section_defaults, is_truss, merge_section_overrides
from src.model.loads import GravityLoadCase

# OpenSees import (설치 여부에 따라 분기)
try:
    import openseespy.opensees as ops
    _OPS_AVAILABLE = True
except ImportError:
    _OPS_AVAILABLE = False
    ops = None

# 엑셀 fallback 안내 — 최초 1회만 출력하기 위한 플래그
_FALLBACK_LOGGED: set[str] = set()


# ══════════════════════════════════════════════════════════════════════════════
# 1.  MIDAS 검증 기준 카탈로그 (scripts/28~30 에서 MIDAS 1:1 대조 완료)
#     엑셀(data/노드 좌표.xlsx)이 없으면 이 값을 fallback으로 사용한다.
# ══════════════════════════════════════════════════════════════════════════════

def _get_default_node_catalog() -> dict[int, tuple[float, float, float]]:
    """
    MIDAS 검증 완료 노드 좌표 카탈로그 (script 28 기준).
    단위: mm  /  좌표: (x, y, z)
    """
    Lx = 150.; Ly = 150.; CX = 75.; CY = 75.
    nodes: dict[int, tuple] = {}
    # ── Base (z=0)
    for n, (x, y) in zip([1, 2, 3, 4], CORNER_XY):
        nodes[n] = (x, y, BASE_Z)
    nodes[101] = (CX, CY, BASE_Z)
    # ── Floors
    for c0, cn, z in [(5, 9, 200.), (10, 14, 400.), (15, 19, 600.), (20, 24, 800.)]:
        for k, (x, y) in enumerate(CORNER_XY):
            nodes[c0 + k] = (x, y, z)
        nodes[cn] = (CX, CY, z)
    # ── Belt bottom (z=544)
    for ops_tag, (x, y) in zip([201, 202, 203, 204], CORNER_XY):
        nodes[ops_tag] = (x, y, BELT_BOT_Z)
    nodes[221] = (CX, CY, BELT_BOT_Z)
    # ── Belt top (z=594)
    for ops_tag, (x, y) in zip([205, 206, 207, 208], CORNER_XY):
        nodes[ops_tag] = (x, y, BELT_TOP_Z)
    nodes[222] = (CX, CY, BELT_TOP_Z)
    # ── Belt mid / face midpoints (z=569)
    # S-face, E-face, N-face, W-face
    nodes[211] = (CX, 0.,  BELT_MID_Z)
    nodes[212] = (Lx, CY,  BELT_MID_Z)
    nodes[213] = (CX, Ly,  BELT_MID_Z)
    nodes[214] = (0., CY,  BELT_MID_Z)
    return nodes


def _get_default_element_catalog() -> list[tuple]:
    """
    MIDAS 검증 완료 요소 카탈로그 (scripts 28/29/30 기준).
    반환: [(elem_tag, node_i, node_j, group_label), ...]
    group_label ∈ {COL_EXT, CORE, BELT_TC, BELT_BC, BELT_D, OUTR}
    """
    elems = []
    # ── 기둥 (COL_EXT) – 24개 ──────────────────────────────────────────────────
    for et, (i, j) in zip(range(1, 5),   [(1,5),(2,6),(3,7),(4,8)]):
        elems.append((et, i, j, 'COL_EXT'))
    for et, (i, j) in zip(range(5, 9),   [(5,10),(6,11),(7,12),(8,13)]):
        elems.append((et, i, j, 'COL_EXT'))
    for et, (i, j) in zip(range(9, 13),  [(10,201),(11,202),(12,203),(13,204)]):
        elems.append((et, i, j, 'COL_EXT'))
    for et, (i, j) in zip(range(13, 17), [(201,205),(202,206),(203,207),(204,208)]):
        elems.append((et, i, j, 'COL_EXT'))
    for et, (i, j) in zip(range(17, 21), [(205,15),(206,16),(207,17),(208,18)]):
        elems.append((et, i, j, 'COL_EXT'))
    for et, (i, j) in zip(range(21, 25), [(15,20),(16,21),(17,22),(18,23)]):
        elems.append((et, i, j, 'COL_EXT'))
    # ── 코어 (CORE) – 6개 ─────────────────────────────────────────────────────
    for et, (i, j) in zip(range(25, 31),
                          [(101,9),(9,14),(14,221),(221,222),(222,19),(19,24)]):
        elems.append((et, i, j, 'CORE'))
    # ── 벨트트러스 (4면, 각 6개씩) – 24개 ─────────────────────────────────────
    belt = [
        # South face (y=0)
        (31,205,206,'BELT_TC'), (32,201,202,'BELT_BC'),
        (33,205,211,'BELT_D'),  (34,206,211,'BELT_D'),
        (35,201,211,'BELT_D'),  (36,202,211,'BELT_D'),
        # East face (x=150)
        (37,206,207,'BELT_TC'), (38,202,203,'BELT_BC'),
        (39,206,212,'BELT_D'),  (40,207,212,'BELT_D'),
        (41,202,212,'BELT_D'),  (42,203,212,'BELT_D'),
        # North face (y=150)
        (43,207,208,'BELT_TC'), (44,203,204,'BELT_BC'),
        (45,207,213,'BELT_D'),  (46,208,213,'BELT_D'),
        (47,203,213,'BELT_D'),  (48,204,213,'BELT_D'),
        # West face (x=0)
        (49,208,205,'BELT_TC'), (50,204,201,'BELT_BC'),
        (51,208,214,'BELT_D'),  (52,205,214,'BELT_D'),
        (53,204,214,'BELT_D'),  (54,201,214,'BELT_D'),
    ]
    elems.extend(belt)
    # ── 아웃리거 (OUTR) – 8개 ─────────────────────────────────────────────────
    outr = [
        (55,222,211,'OUTR'), (56,221,211,'OUTR'),
        (57,222,212,'OUTR'), (58,221,212,'OUTR'),
        (59,222,213,'OUTR'), (60,221,213,'OUTR'),
        (61,222,214,'OUTR'), (62,221,214,'OUTR'),
    ]
    elems.extend(outr)
    return elems


# ══════════════════════════════════════════════════════════════════════════════
# 2.  엑셀 읽기 (선택)
# ══════════════════════════════════════════════════════════════════════════════

def load_midas_nodes_from_excel(
    excel_path: str | Path | None = None,
) -> dict[int, tuple[float, float, float]]:
    """
    MIDAS 엑셀(노드 좌표.xlsx) Sheet1 A~D 열에서 노드 좌표 읽기.
    파일이 없거나 읽기 실패 시 MIDAS 검증 기본값으로 fallback.

    Parameters
    ----------
    excel_path : Path | None
        None이면 config.NODE_EXCEL 사용

    Returns
    -------
    dict: {node_tag: (x_mm, y_mm, z_mm)}
    """
    from src.config import NODE_EXCEL
    path = Path(excel_path) if excel_path else NODE_EXCEL

    if not path.exists():
        if 'nodes' not in _FALLBACK_LOGGED:
            _FALLBACK_LOGGED.add('nodes')
            print(f"[opensees_builder] INFO: 엑셀 없음 ({path.name}) "
                  "-- MIDAS 검증 기본값 사용 (4층 150×150mm, 이후 반복 생략)")
        return _get_default_node_catalog()

    try:
        import pandas as pd
        df = pd.read_excel(str(path), sheet_name='Sheet1',
                           header=0, usecols='A:D', engine='openpyxl')
        df.columns = ['node', 'X_mm', 'Y_mm', 'Z_mm']
        df = df.dropna(subset=['node'])
        df['node'] = df['node'].astype(int)
        catalog = {
            int(row['node']): (float(row['X_mm']), float(row['Y_mm']), float(row['Z_mm']))
            for _, row in df.iterrows()
        }
        print(f"[opensees_builder] 엑셀에서 {len(catalog)}개 노드 로드")
        return catalog
    except Exception as exc:
        if 'nodes_err' not in _FALLBACK_LOGGED:
            _FALLBACK_LOGGED.add('nodes_err')
            print(f"[opensees_builder] INFO: 엑셀 노드 읽기 실패 ({exc}) "
                  "-- MIDAS 기본값 사용 (이후 반복 생략)")
        return _get_default_node_catalog()


def load_midas_elements_from_excel(
    excel_path: str | Path | None = None,
) -> list[tuple]:
    """
    MIDAS 엑셀(노드 좌표.xlsx) Sheet1 I~AC 열에서 요소 연결 정보 읽기.
    파일이 없거나 column 매핑 불확실 시 MIDAS 검증 기본값으로 fallback.

    엑셀 열 구조 (Sheet1, I~AC):
        Element | Type | Material | Property | node1 | node2 | ...

    Returns
    -------
    list of (elem_tag, node_i, node_j, group_label)
    """
    from src.config import NODE_EXCEL
    path = Path(excel_path) if excel_path else NODE_EXCEL

    if not path.exists():
        if 'elems' not in _FALLBACK_LOGGED:
            _FALLBACK_LOGGED.add('elems')
            print(f"[opensees_builder] INFO: 엑셀 없음 ({path.name}) "
                  "-- MIDAS 검증 기본 요소 사용 (이후 반복 생략)")
        return _get_default_element_catalog()

    try:
        import pandas as pd
        df = pd.read_excel(str(path), sheet_name='Sheet1',
                           header=0, usecols='I:AC', engine='openpyxl')
        df.columns = [f'col_{i}' for i in range(len(df.columns))]
        # TODO: 실제 엑셀 열 매핑 후 _parse_midas_elements(df) 구현
        raise NotImplementedError(
            "엑셀 요소 파싱: data/노드 좌표.xlsx 열 구조 확인 후 구현 필요."
        )
    except NotImplementedError:
        if 'elems_todo' not in _FALLBACK_LOGGED:
            _FALLBACK_LOGGED.add('elems_todo')
            print("[opensees_builder] INFO: 엑셀 요소 파싱 미구현 "
                  "-- MIDAS 기본값 사용 (이후 반복 생략)")
        return _get_default_element_catalog()
    except Exception as exc:
        if 'elems_err' not in _FALLBACK_LOGGED:
            _FALLBACK_LOGGED.add('elems_err')
            print(f"[opensees_builder] INFO: 엑셀 요소 읽기 실패 ({exc}) "
                  "-- MIDAS 기본값 사용 (이후 반복 생략)")
        return _get_default_element_catalog()


# ══════════════════════════════════════════════════════════════════════════════
# 3.  OpenSees 모델 생성 함수 (중력 해석용)
# ══════════════════════════════════════════════════════════════════════════════

def create_nodes(node_catalog: dict) -> None:
    """
    node_catalog의 모든 노드를 OpenSees에 등록.
    ops.node(tag, x, y, z) 호출.
    """
    for tag, (x, y, z) in node_catalog.items():
        ops.node(tag, x, y, z)


def apply_boundary_conditions(fix_master_uz: bool = False) -> None:
    """
    경계조건 설정.

    Parameters
    ----------
    fix_master_uz : bool
        True  → 지진 해석: 마스터 노드 Uz 고정 (수직 변위 없음 가정)
        False → 중력 해석: 마스터 노드 Uz 자유 (수직 처짐 계산)

    고정 조건:
      - Base nodes (1,2,3,4,101)    : 완전 고정 [1,1,1,1,1,1]
      - Belt-mid nodes (211~214)    : 회전만 고정 [0,0,0,1,1,1]
      - 층 마스터 노드 (9,14,19,24) : fix_master_uz에 따라
    """
    BASE_NODES    = [1, 2, 3, 4, 101]
    CENTER_NODES  = [9, 14, 19, 24]
    BELT_MID_NODES = [211, 212, 213, 214]

    for n in BASE_NODES:
        ops.fix(n, 1, 1, 1, 1, 1, 1)

    for n in BELT_MID_NODES:
        ops.fix(n, 0, 0, 0, 1, 1, 1)   # 병진 자유, 회전 고정

    if fix_master_uz:
        for cn in CENTER_NODES:
            ops.fix(cn, 0, 0, 1, 0, 0, 0)   # Uz 고정 (지진 해석용)
    # 중력 해석: 마스터 노드에 fix 없음 → Uz 자유


def create_rigid_diaphragms() -> None:
    """
    층 레벨(z=200/400/600/800)에만 rigid diaphragm 적용.

    perpDirn=3 → X-Y 평면 내 강성체 (구속: Ux, Uy, Rz / 자유: Uz)

    마스터 노드: 코어 중심 9(F1), 14(F2), 19(F3), 24(F4)
    슬레이브 노드: 각 층 4모서리 기둥 노드

    벨트트러스 레벨 노드(z=544/569/594, 노드 201~208/211~214/221~222)는
    층 슬래브 레벨이 아니므로 diaphragm에 포함하지 않는다.
    지진해석 단계에서 벨트트러스 코너 노드의 수평 거동을 MIDAS와 비교 검토 예정.
    """
    ops.rigidDiaphragm(3,  9,  5,  6,  7,  8)
    ops.rigidDiaphragm(3, 14, 10, 11, 12, 13)
    ops.rigidDiaphragm(3, 19, 15, 16, 17, 18)
    ops.rigidDiaphragm(3, 24, 20, 21, 22, 23)


def _define_transforms_and_material(mat_tag: int = 1, transf_tag: int = 1) -> None:
    """
    공용 재료(uniaxial Elastic)와 기하변환(Linear) 정의.
    geomTransf vecxz=(1,0,0): 수직 기둥/코어에 적합.
    """
    ops.geomTransf('Linear', transf_tag, 1., 0., 0.)
    ops.uniaxialMaterial('Elastic', mat_tag, E_MDF)


def create_columns(
    elem_catalog: list[tuple],
    sections: dict[str, dict],
    mat_tag: int = 1,
    transf_tag: int = 1,
) -> int:
    """
    기둥 요소(COL_EXT) 생성.

    Returns
    -------
    int : 생성된 기둥 요소 수
    """
    count = 0
    for et, iN, jN, grp in elem_catalog:
        if grp != 'COL_EXT':
            continue
        s = sections[grp]
        ops.element('elasticBeamColumn', et, iN, jN,
                    s['A'], E_MDF, G_MDF, s['J'], s['Iy'], s['Iz'],
                    transf_tag)
        count += 1
    return count


def create_core(
    elem_catalog: list[tuple],
    sections: dict[str, dict],
    mat_tag: int = 1,
    transf_tag: int = 1,
) -> int:
    """
    코어 요소(CORE) 생성.

    Returns
    -------
    int : 생성된 코어 요소 수
    """
    count = 0
    for et, iN, jN, grp in elem_catalog:
        if grp != 'CORE':
            continue
        s = sections[grp]
        ops.element('elasticBeamColumn', et, iN, jN,
                    s['A'], E_MDF, G_MDF, s['J'], s['Iy'], s['Iz'],
                    transf_tag)
        count += 1
    return count


def create_belt_truss(
    elem_catalog: list[tuple],
    sections: dict[str, dict],
    mat_tag: int = 1,
) -> int:
    """
    벨트트러스 요소(BELT_TC, BELT_BC, BELT_D) 생성.
    Truss element: 축력만 전달.

    Returns
    -------
    int : 생성된 벨트트러스 요소 수
    """
    belt_groups = {'BELT_TC', 'BELT_BC', 'BELT_D'}
    count = 0
    for et, iN, jN, grp in elem_catalog:
        if grp not in belt_groups:
            continue
        A = sections[grp]['A']
        ops.element('Truss', et, iN, jN, A, mat_tag)
        count += 1
    return count


def create_outriggers(
    elem_catalog: list[tuple],
    sections: dict[str, dict],
    mat_tag: int = 1,
) -> int:
    """
    아웃리거 요소(OUTR) 생성.
    Truss element: 코어 ↔ 벨트 면중점 연결.

    Returns
    -------
    int : 생성된 아웃리거 요소 수
    """
    count = 0
    for et, iN, jN, grp in elem_catalog:
        if grp != 'OUTR':
            continue
        A = sections[grp]['A']
        ops.element('Truss', et, iN, jN, A, mat_tag)
        count += 1
    return count


# ══════════════════════════════════════════════════════════════════════════════
# 4.  중력 하중 적용
# ══════════════════════════════════════════════════════════════════════════════

# 층별 마스터+슬레이브 노드 목록 (외부 중력 하중 분배 대상)
_FLOOR_NODE_SETS = [
    (200., [5, 6, 7, 8, 9]),     # F1
    (400., [10, 11, 12, 13, 14]), # F2
    (600., [15, 16, 17, 18, 19]), # F3
    (800., [20, 21, 22, 23, 24]), # F4
]
_BASE_NODES = {1, 2, 3, 4, 101}  # 하중 금지 노드


def _compute_self_weight(
    node_catalog: dict,
    elem_catalog: list[tuple],
    sections: dict[str, dict],
) -> dict[int, float]:
    """
    요소 자중을 양 끝 노드에 균등 분배 (N, -Z 방향).
    W_elem = A × L × ρ × g
    각 노드: -W/2 (하향)

    Returns
    -------
    dict: {node_tag: Fz [N]}  (음수 = 하향)
    """
    sw: dict[int, float] = {}
    for _et, iN, jN, grp in elem_catalog:
        xi, yi, zi = node_catalog[iN]
        xj, yj, zj = node_catalog[jN]
        L = math.sqrt((xj - xi)**2 + (yj - yi)**2 + (zj - zi)**2)
        A = sections[grp]['A']
        W = A * L * RHO_MDF * GRAVITY_ACC   # [N]
        sw[iN] = sw.get(iN, 0.) - W * 0.5
        sw[jN] = sw.get(jN, 0.) - W * 0.5
    return sw


def apply_gravity_loads(
    node_catalog: dict,
    elem_catalog: list[tuple],
    sections: dict[str, dict],
    load_case: GravityLoadCase,
    ts_tag: int = 1,
    pattern_tag: int = 1,
) -> tuple[dict[int, float], dict[int, float], float]:
    """
    OpenSees에 중력 하중 패턴 등록.

    적용 원칙:
      - z=200/400/600/800 노드에만 외부 하중 적용
      - base z=0 노드(1,2,3,4,101)에 절대 하중 미적용
      - 외부 하중: 층당 FLOOR_GRAVITY_N을 5노드 균등 분배
      - 자중: 요소별 A×L×ρ×g → 양 끝 노드에 균등 분배

    Returns
    -------
    ext_loads   : {node_tag: Fz [N]}  (외부 하중, 음수)
    sw_loads    : {node_tag: Fz [N]}  (자중,     음수)
    total_fz    : 전체 적용 수직 하중 합계 [N] (음수)
    """
    floor_force = load_case.floor_force_n
    n_per_floor = 5.0
    fz_per_node = -floor_force / n_per_floor   # 음수 (하향)

    # ── 외부 층 하중 ──────────────────────────────────────────────────────────
    ext_loads: dict[int, float] = {}
    for _z, nodes in _FLOOR_NODE_SETS:
        for nd in nodes:
            assert nd not in _BASE_NODES, f"NODE {nd}는 base node -- 하중 금지!"
            ext_loads[nd] = ext_loads.get(nd, 0.) + fz_per_node

    # ── 자중 ──────────────────────────────────────────────────────────────────
    sw_loads: dict[int, float] = {}
    if load_case.include_self_weight:
        sw_loads = _compute_self_weight(node_catalog, elem_catalog, sections)

    # ── OpenSees 하중 패턴 등록 ────────────────────────────────────────────────
    ops.timeSeries('Constant', ts_tag)
    ops.pattern('Plain', pattern_tag, ts_tag)

    all_fz: dict[int, float] = {}
    for nd, fz in ext_loads.items():
        all_fz[nd] = all_fz.get(nd, 0.) + fz
    for nd, fz in sw_loads.items():
        all_fz[nd] = all_fz.get(nd, 0.) + fz

    for nd, fz in all_fz.items():
        if abs(fz) > 1e-12:
            ops.load(nd, 0., 0., fz, 0., 0., 0.)

    # 검증: base 노드에 하중이 들어가지 않았는지 확인
    base_fz = sum(all_fz.get(n, 0.) for n in _BASE_NODES)
    if abs(base_fz) > 1e-10:
        raise RuntimeError(f"BASE 노드에 하중이 잘못 적용됨: {base_fz:.4f} N")

    total_fz = sum(all_fz.values())
    return ext_loads, sw_loads, total_fz


# ══════════════════════════════════════════════════════════════════════════════
# 5.  해석 실행
# ══════════════════════════════════════════════════════════════════════════════

def run_gravity_analysis() -> bool:
    """
    정적 중력 해석 실행 (Linear Static).

    Returns
    -------
    bool : True = 수렴, False = 미수렴
    """
    ops.wipeAnalysis()   # 이전 analysis 객체 제거 (중복 핸들러 경고 방지)
    ops.constraints('Transformation')
    ops.numberer('RCM')
    ops.system('BandGeneral')
    ops.test('NormDispIncr', 1e-12, 10, 0)
    ops.algorithm('Linear')
    ops.integrator('LoadControl', 1.0)
    ops.analysis('Static')
    ok = ops.analyze(1)
    ops.reactions()
    return ok == 0


# ══════════════════════════════════════════════════════════════════════════════
# 6.  중력 해석 raw 결과 dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GravityRawResult:
    """중력 해석 raw 결과. postprocess.py 가 이 객체를 받아 가공한다."""
    converged           : bool
    node_displacements  : dict[int, list[float]]    # {tag: [ux,uy,uz,rx,ry,rz]}
    base_reactions      : dict[int, list[float]]    # {tag: [rx,ry,rz,mx,my,mz]}
    ext_loads_n         : dict[int, float]          # {tag: Fz} 외부 하중
    sw_loads_n          : dict[int, float]          # {tag: Fz} 자중
    total_applied_fz_n  : float                     # 전체 수직 하중 [N]
    n_nodes             : int
    n_elements          : int
    n_belt_elements     : int
    n_outrigger_elements: int
    load_levels_z       : list[float]               # [200, 400, 600, 800]
    base_load_applied   : bool                      # 항상 False 이어야 함
    belt_top_z          : float = BELT_TOP_Z
    belt_bot_z          : float = BELT_BOT_Z
    belt_mid_z          : float = BELT_MID_Z


# ══════════════════════════════════════════════════════════════════════════════
# 7.  중력 해석 최상위 진입점
# ══════════════════════════════════════════════════════════════════════════════

def run_gravity_opensees(
    section_overrides: dict[str, dict] | None = None,
    load_case: GravityLoadCase | None = None,
    excel_path: str | Path | None = None,
) -> GravityRawResult:
    """
    중력 전용 OpenSees 해석 실행 (전체 파이프라인).

    Parameters
    ----------
    section_overrides : {'COL_EXT': {...}, 'CORE': {...}} 형태로 단면 덮어쓰기.
                        None이면 config 기본 MIDAS 단면 사용.
    load_case         : None이면 표준 6kg×4층 중력 하중.
    excel_path        : MIDAS 엑셀 경로. None이면 data/노드 좌표.xlsx 시도 후 fallback.

    Returns
    -------
    GravityRawResult
    """
    if not _OPS_AVAILABLE:
        raise ImportError(
            "openseespy가 설치되어 있지 않습니다.\n"
            "설치: pip install openseespy"
        )

    if load_case is None:
        from src.model.loads import get_gravity_load_case
        load_case = get_gravity_load_case()

    # 1. 카탈로그 로드
    node_catalog = load_midas_nodes_from_excel(excel_path)
    elem_catalog = load_midas_elements_from_excel(excel_path)
    sections     = merge_section_overrides(section_overrides)

    n_nodes    = len(node_catalog)
    n_elements = len(elem_catalog)
    n_belt     = sum(1 for _, _, _, g in elem_catalog
                     if g in {'BELT_TC', 'BELT_BC', 'BELT_D'})
    n_outr     = sum(1 for _, _, _, g in elem_catalog if g == 'OUTR')

    # 2. OpenSees 초기화
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    # 3. 모델 생성
    create_nodes(node_catalog)
    apply_boundary_conditions(fix_master_uz=False)   # 중력: Uz 자유
    _define_transforms_and_material()
    create_columns(elem_catalog, sections)
    create_core(elem_catalog, sections)
    create_belt_truss(elem_catalog, sections)
    create_outriggers(elem_catalog, sections)
    create_rigid_diaphragms()

    # 4. 하중 적용
    ext_loads, sw_loads, total_fz = apply_gravity_loads(
        node_catalog, elem_catalog, sections, load_case
    )

    # 5. 해석
    converged = run_gravity_analysis()

    # 6. 결과 수집
    node_disps: dict[int, list[float]] = {}
    for tag in node_catalog:
        try:
            node_disps[tag] = list(ops.nodeDisp(tag))
        except Exception:
            node_disps[tag] = [0.] * 6

    fixed_nodes = [1, 2, 3, 4, 101]
    base_rxns: dict[int, list[float]] = {}
    for bn in fixed_nodes:
        try:
            base_rxns[bn] = list(ops.nodeReaction(bn))
        except Exception:
            base_rxns[bn] = [0.] * 6

    # base 노드에 하중이 적용되었는지 최종 확인
    base_load_applied = any(
        abs(ext_loads.get(n, 0.) + sw_loads.get(n, 0.)) > 1e-10
        for n in fixed_nodes
    )

    return GravityRawResult(
        converged            = converged,
        node_displacements   = node_disps,
        base_reactions       = base_rxns,
        ext_loads_n          = ext_loads,
        sw_loads_n           = sw_loads,
        total_applied_fz_n   = total_fz,
        n_nodes              = n_nodes,
        n_elements           = n_elements,
        n_belt_elements      = n_belt,
        n_outrigger_elements = n_outr,
        load_levels_z        = list(FLOOR_Z_LIST),
        base_load_applied    = base_load_applied,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 8.  수평 지진 해석 (TODO: HS 단계에서 구현)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RawAnalysisResult:
    """수평 지진 해석 raw 결과. postprocess.py 에서 StructuralResponse로 변환."""
    load_case_label     : str
    node_displacements  : dict[int, list[float]] = field(default_factory=dict)
    element_forces      : dict[int, list[float]] = field(default_factory=dict)
    base_reactions      : dict[int, list[float]] = field(default_factory=dict)
    converged           : bool = False
    log                 : str  = ""
    # DR 계산을 위해 postprocess.py에 전달하는 단면 정보
    elem_sections       : dict[int, dict] = field(default_factory=dict)  # {tag: section_dict}
    col_elem_floor      : dict[int, str]  = field(default_factory=dict)  # {tag: 'C_1F'...}
    core_elem_floor     : dict[int, str]  = field(default_factory=dict)  # {tag: 'C_1F'...}


# ── 층별 기둥/코어 요소 태그 매핑 ────────────────────────────────────────────────
#   (element catalog 순서와 일치: opensees_builder 내부 상수)
_COL_ELEM_FLOOR: dict[int, str] = {}
for _et in range(1, 5):   _COL_ELEM_FLOOR[_et] = 'C_1F'
for _et in range(5, 9):   _COL_ELEM_FLOOR[_et] = 'C_2F'
for _et in range(9, 21):  _COL_ELEM_FLOOR[_et] = 'C_3F'   # belt zone 포함
for _et in range(21, 25): _COL_ELEM_FLOOR[_et] = 'C_4F'

_CORE_ELEM_FLOOR: dict[int, str] = {
    25: 'C_1F',  # 101 → 9  (z=0→200)
    26: 'C_2F',  # 9   → 14 (z=200→400)
    27: 'C_3F',  # 14  → 221 (z=400→544)
    28: 'C_3F',  # 221 → 222 (belt zone)
    29: 'C_3F',  # 222 → 19  (z=594→600)
    30: 'C_4F',  # 19  → 24  (z=600→800)
}


def _seismic_floor_forces(
    floor_mass_kg: float,
    sa: float,
    n_floors: int = 4,
    story_height: float = 200.0,
) -> list[float]:
    """
    등가정적 지진하중 (역삼각형 분포, ASCE-7 유사).
    반환: [F_1F, F_2F, F_3F, F_4F] (N)
    """
    V_base = n_floors * floor_mass_kg * sa * GRAVITY_ACC   # 총 밑면 전단력
    heights = [story_height * (i + 1) for i in range(n_floors)]
    wh_sum = sum(floor_mass_kg * h for h in heights)
    return [V_base * (floor_mass_kg * h / wh_sum) for h in heights]


def create_columns_per_floor(
    elem_catalog: list[tuple],
    floor_sections: dict[str, dict],
    transf_tag: int = 1,
) -> tuple[int, dict[int, dict]]:
    """
    층별 단면을 사용한 기둥 요소 생성.

    Parameters
    ----------
    floor_sections : {'C_1F': {A, Iy, Iz, J, cy, cz}, 'C_2F': ..., 'C_3F': ..., 'C_4F': ...}

    Returns
    -------
    (생성 요소 수, {elem_tag: section_dict})
    """
    count = 0
    elem_sec: dict[int, dict] = {}
    for et, iN, jN, grp in elem_catalog:
        if grp != 'COL_EXT':
            continue
        floor_label = _COL_ELEM_FLOOR.get(et, 'C_1F')
        s = floor_sections.get(floor_label, floor_sections.get('C_1F'))
        ops.element('elasticBeamColumn', et, iN, jN,
                    s['A'], E_MDF, G_MDF, s['J'], s['Iy'], s['Iz'],
                    transf_tag)
        elem_sec[et] = s
        count += 1
    return count, elem_sec


def apply_seismic_loads(
    load_case: 'SeismicLoadCase',
    floor_mass_kg: float = 6.0,
    ts_tag: int = 1,
    pattern_tag: int = 1,
) -> None:
    """
    OpenSees에 수평 지진 하중 패턴 등록.
    층 마스터 노드(9, 14, 19, 24)에 수평력 적용.
    """
    from src.model.loads import SeismicLoadCase
    forces = _seismic_floor_forces(floor_mass_kg, load_case.sa)
    master_nodes = [9, 14, 19, 24]

    ops.timeSeries('Constant', ts_tag)
    ops.pattern('Plain', pattern_tag, ts_tag)

    for nd, F in zip(master_nodes, forces):
        if load_case.direction == 'X':
            ops.load(nd, F, 0., 0., 0., 0., 0.)
        elif load_case.direction == 'Y':
            ops.load(nd, 0., F, 0., 0., 0., 0.)


def run_opensees_with_rubber(
    col_floor_sections: dict[str, dict],
    load_case: Any,
    rubber_config: dict | None = None,
    floor_mass_kg: float = 6.0,
    excel_path: Path | None = None,
) -> RawAnalysisResult:
    """
    고무줄 탄성 접합부 포함 수평 지진 해석.

    rubber_config가 None이거나 enabled=False이면 기존 run_opensees()와 동일하게 동작.
    enabled=True이면 2F-3F / 3F-4F 접합부에 zeroLength 스프링 삽입.

    Parameters
    ----------
    col_floor_sections : {'C_1F': ..., 'C_2F': ..., 'C_3F': ..., 'C_4F': ...}
    load_case          : SeismicLoadCase
    rubber_config      : rubber_joint.DEFAULT_RUBBER_CONFIG 형태.
                         None이면 비활성(기존 모델).
    floor_mass_kg      : 층당 질량 [kg]

    Returns
    -------
    RawAnalysisResult
    """
    from src.model.rubber_joint import (
        DEFAULT_RUBBER_CONFIG, patch_catalogs,
        define_rubber_materials, add_rubber_upper_diaphragms,
        add_rubber_spring_elements, print_audit,
    )

    if rubber_config is None:
        rubber_config = {**DEFAULT_RUBBER_CONFIG, 'enabled': False}

    use_rubber = rubber_config.get('enabled', False)

    if not _OPS_AVAILABLE:
        raise ImportError("openseespy 설치 필요: pip install openseespy")

    node_catalog = load_midas_nodes_from_excel(excel_path)
    elem_catalog = load_midas_elements_from_excel(excel_path)
    sections     = merge_section_overrides(None)

    # 고무줄 접합 활성 시 카탈로그 수정
    active_joints: list = []
    if use_rubber:
        node_catalog, elem_catalog, active_joints = patch_catalogs(
            node_catalog, elem_catalog, rubber_config
        )

    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    create_nodes(node_catalog)
    apply_boundary_conditions(fix_master_uz=True)
    _define_transforms_and_material()

    # 고무줄 재료 정의 (기둥 요소 생성 이전)
    if use_rubber:
        define_rubber_materials(rubber_config)

    _, col_elem_sec = create_columns_per_floor(elem_catalog, col_floor_sections)

    core_elem_sec: dict[int, dict] = {}
    for et, iN, jN, grp in elem_catalog:
        if grp == 'CORE':
            s = sections['CORE']
            ops.element('elasticBeamColumn', et, iN, jN,
                        s['A'], E_MDF, G_MDF, s['J'], s['Iy'], s['Iz'], 1)
            core_elem_sec[et] = s

    create_belt_truss(elem_catalog, sections)
    create_outriggers(elem_catalog, sections)
    create_rigid_diaphragms()

    # 고무줄 상부 인터페이스 diaphragm + 스프링 요소
    n_springs = 0
    if use_rubber and active_joints:
        add_rubber_upper_diaphragms(active_joints)
        n_springs = add_rubber_spring_elements(active_joints, rubber_config)
        print_audit(active_joints, rubber_config, n_springs)

    apply_seismic_loads(load_case, floor_mass_kg)

    converged = run_gravity_analysis()

    # 결과 수집
    node_disps: dict[int, list[float]] = {}
    for tag in node_catalog:
        try:
            node_disps[tag] = list(ops.nodeDisp(tag))
        except Exception:
            node_disps[tag] = [0.] * 6

    base_nodes = [1, 2, 3, 4, 101]
    base_rxns: dict[int, list[float]] = {}
    ops.reactions()
    for bn in base_nodes:
        try:
            base_rxns[bn] = list(ops.nodeReaction(bn))
        except Exception:
            base_rxns[bn] = [0.] * 6

    elem_forces: dict[int, list[float]] = {}
    for et in list(col_elem_sec) + list(core_elem_sec):
        try:
            elem_forces[et] = list(ops.eleForce(et))
        except Exception:
            elem_forces[et] = [0.] * 12

    return RawAnalysisResult(
        load_case_label    = load_case.label,
        node_displacements = node_disps,
        element_forces     = elem_forces,
        base_reactions     = base_rxns,
        converged          = converged,
        log                = f"rubber={use_rubber} Sa={load_case.sa}g dir={load_case.direction}",
        elem_sections      = {**col_elem_sec, **core_elem_sec},
        col_elem_floor     = dict(_COL_ELEM_FLOOR),
        core_elem_floor    = dict(_CORE_ELEM_FLOOR),
    )


def run_opensees(
    col_floor_sections: dict[str, dict],
    load_case: Any,
    floor_mass_kg: float = 6.0,
    excel_path: Path | None = None,
) -> RawAnalysisResult:
    """
    수평 지진 해석 (등가정적, Linear Static).

    Parameters
    ----------
    col_floor_sections : {'C_1F': {A, Iy, Iz, J, cy, cz}, ...}  층별 기둥 단면
    load_case          : SeismicLoadCase (방향 + Sa)
    floor_mass_kg      : 층당 질량 [kg]

    Returns
    -------
    RawAnalysisResult
    """
    if not _OPS_AVAILABLE:
        raise ImportError("openseespy 설치 필요: pip install openseespy")

    node_catalog = load_midas_nodes_from_excel(excel_path)
    elem_catalog = load_midas_elements_from_excel(excel_path)
    sections     = merge_section_overrides(None)   # belt/core/outr 기본값 유지

    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    create_nodes(node_catalog)
    apply_boundary_conditions(fix_master_uz=True)   # 지진: Uz 고정
    _define_transforms_and_material()

    # 기둥: 층별 단면
    _, col_elem_sec = create_columns_per_floor(elem_catalog, col_floor_sections)

    # 코어/벨트/아웃리거: 기본 단면
    core_elem_sec: dict[int, dict] = {}
    for et, iN, jN, grp in elem_catalog:
        if grp == 'CORE':
            s = sections['CORE']
            ops.element('elasticBeamColumn', et, iN, jN,
                        s['A'], E_MDF, G_MDF, s['J'], s['Iy'], s['Iz'],
                        1)
            core_elem_sec[et] = s
    create_belt_truss(elem_catalog, sections)
    create_outriggers(elem_catalog, sections)
    create_rigid_diaphragms()

    apply_seismic_loads(load_case, floor_mass_kg)

    converged = run_gravity_analysis()   # 동일 Static solver 재사용

    # 결과 수집
    node_disps: dict[int, list[float]] = {}
    for tag in node_catalog:
        try:
            node_disps[tag] = list(ops.nodeDisp(tag))
        except Exception:
            node_disps[tag] = [0.] * 6

    base_nodes = [1, 2, 3, 4, 101]
    base_rxns: dict[int, list[float]] = {}
    ops.reactions()
    for bn in base_nodes:
        try:
            base_rxns[bn] = list(ops.nodeReaction(bn))
        except Exception:
            base_rxns[bn] = [0.] * 6

    elem_forces: dict[int, list[float]] = {}
    all_beam_tags = list(col_elem_sec.keys()) + list(core_elem_sec.keys())
    for et in all_beam_tags:
        try:
            elem_forces[et] = list(ops.eleForce(et))
        except Exception:
            elem_forces[et] = [0.] * 12

    # elem_sections: 단면 물성 (DR 계산용)
    elem_sections = {**col_elem_sec, **core_elem_sec}

    return RawAnalysisResult(
        load_case_label = load_case.label,
        node_displacements = node_disps,
        element_forces     = elem_forces,
        base_reactions     = base_rxns,
        converged          = converged,
        log                = f"Sa={load_case.sa}g dir={load_case.direction}",
        elem_sections      = elem_sections,
        col_elem_floor     = dict(_COL_ELEM_FLOOR),
        core_elem_floor    = dict(_CORE_ELEM_FLOOR),
    )
