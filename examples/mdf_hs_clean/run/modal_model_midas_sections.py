"""
modal_model_midas_sections.py
==============================
모드해석 비교용 모델 (질량 포함, 층별 단면 적용).

MIDAS 고유치해석 출력(1차 T=1.0231s ~ 8차 T=0.0568s, 참여질량 X/Y 4모드씩
완전 분리)에 대응하는 OpenSees 모델. 단면은 사용자가 제공한 층별 단면
이미지(strip 적층 단면, C_1F~C_4F)에서 역산한 값 - I_min이 이미지에 적힌
값과 정확히 일치하는 것으로 기하 가정(구멍 4mm 테두리)을 검증했다.

이 파일은 모델만 만든다 (분석 블록 없음) - openframe의
run_modal_analysis(source)가 빌드 후 ops.eigen을 직접 호출한다.

단위: N, mm, kg, s (질량은 F=ma 일관성을 위해 kg/1000으로 환산해 등록)
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import openseespy.opensees as ops

from src.model.opensees_builder import (
    _get_default_node_catalog,
    _get_default_element_catalog,
    create_nodes,
    apply_boundary_conditions,
    create_rigid_diaphragms,
    create_columns_per_floor,
    create_core,
    create_belt_truss,
    create_outriggers,
    _define_transforms_and_material,
)
from src.model.materials import merge_section_overrides

# ── 층별 기둥 단면 (strip 적층 이미지에서 역산, mm/mm^4) ──────────────────────
# 각 floor의 I_min이 이미지에 적힌 값과 정확히 일치해 기하 가정(구멍 4mm 테두리)을
# 교차검증했다: C_1F 3936, C_2F 1728, C_3F 1000, C_4F 144.
# Iy/Iz 축 배정: geomTransf('Linear', 1, 1,0,0) + 수직 기둥(local x = 전역 Z) 조합에서
# local z = 전역 X, local y = 전역 Y(부호만 반대) - 즉 element의 "Iy" 인자가
# X방향 횡변위 강성을, "Iz" 인자가 Y방향 횡변위 강성을 결정한다.
COL_FLOOR_SECTIONS = {
    # C_1F: BOX_HOLLOW 18(X)x14(Y), 구멍 10x6 (4mm 테두리). A=192 (이미지 일치)
    "C_1F": {"A": 192.0, "Iy": 6304.0, "Iz": 3936.0, "J": 6533.3},
    # C_2F: RECT_SOLID 12x12 (정사각형이라 Iy=Iz). A=144 (이미지 일치)
    "C_2F": {"A": 144.0, "Iy": 1728.0, "Iz": 1728.0, "J": 2916.0},
    # C_3F: RECT_SOLID 12(X)x10(Y). A=120 (이미지 일치)
    "C_3F": {"A": 120.0, "Iy": 1440.0, "Iz": 1000.0, "J": 1984.0},
    # C_4F: RECT_SOLID 6(X)x8(Y). A=48 (이미지 일치)
    "C_4F": {"A": 48.0, "Iy": 144.0, "Iz": 256.0, "J": 311.0},
}

# ── 층 질량 (마스터 노드에만 집중질량, 병진만) ────────────────────────────────
# MIDAS 참여질량표가 X/Y 각 4모드로 완전히 분리되는 것(RZ/UZ 참여 0%)은 곧
# 4개 층 마스터 노드에만 병진질량이 있고 회전/수직 질량은 없다는 뜻과 정확히
# 일치한다. FLOOR_MASS_KG=6.0kg(config.py)를 N-mm-s 일관 단위로 환산: kg/1000.
FLOOR_MASS_KG = 6.0
CONSISTENT_MASS = FLOOR_MASS_KG / 1000.0
MASTER_NODES = [9, 14, 19, 24]

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)

node_catalog = _get_default_node_catalog()
elem_catalog = _get_default_element_catalog()
sections = merge_section_overrides(None)

create_nodes(node_catalog)
apply_boundary_conditions(fix_master_uz=True)
_define_transforms_and_material()

create_columns_per_floor(elem_catalog, COL_FLOOR_SECTIONS)
create_core(elem_catalog, sections)
create_belt_truss(elem_catalog, sections)
create_outriggers(elem_catalog, sections)
create_rigid_diaphragms()

for node_tag in MASTER_NODES:
    ops.mass(node_tag, CONSISTENT_MASS, CONSISTENT_MASS, 0.0, 0.0, 0.0, 0.0)
