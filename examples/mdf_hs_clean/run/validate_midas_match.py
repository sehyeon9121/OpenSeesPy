"""
run/validate_midas_match.py
===========================
검증: mdf_hs_clean OpenSees 모델 vs MIDAS 변위 비교

하중: 1.2g X방향, 높이 비례 분포
  node 9  (F1, z=200): Fx = 28.253 N
  node 14 (F2, z=400): Fx = 56.506 N
  node 19 (F3, z=600): Fx = 84.758 N
  node 24 (F4, z=800): Fx = 113.011 N

MIDAS 기준값: mdf_seismic_model_validation/scripts/29 검증 완료 모델 출력
  (E=638 N/mm², G=255.2 N/mm², MIDAS-section-matched)

단면: MIDAS 기본 단면 (A=96, J=864, Iy=832, Iz=832)
단위: N, mm
"""

import sys
import os

# 프로젝트 루트를 sys.path에 추가
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import openseespy.opensees as ops

from src.config import E_MDF, G_MDF, NU_MDF
from src.model.opensees_builder import (
    _get_default_node_catalog,
    _get_default_element_catalog,
    create_nodes,
    apply_boundary_conditions,
    create_rigid_diaphragms,
    _define_transforms_and_material,
)

# ─── MIDAS 기준 변위 (script 29 검증 완료 출력) ───────────────────────────────
MIDAS_DX = {
    'F1': 96.37874748,
    'F2': 268.31549724,
    'F3': 360.74974645,
    'F4': 430.73063483,
}

# ─── 단면 (MIDAS 기본 단면 — HS 미적용 기본 검증용) ────────────────────────────
A_col  = 96.;  J_col  = 864.;  Iy_col  = 832.;  Iz_col  = 832.
A_core = 280.; J_core = 23328.; Iy_core = 16320.; Iz_core = 16320.
A_belt = 24.

# ─── 하중 ──────────────────────────────────────────────────────────────────────
FLOOR_LOADS_12G_X = [
    (9,  28.253),
    (14, 56.506),
    (19, 84.758),
    (24, 113.011),
]
FLOOR_LABELS = ['F1', 'F2', 'F3', 'F4']
CENTER_NODES = [9, 14, 19, 24]
TRUSS_GROUPS = {'BELT_TC', 'BELT_BC', 'BELT_D', 'OUTR'}


def build_model():
    """검증용 OpenSees 모델 빌드 (MIDAS 기본 단면)."""
    node_catalog = _get_default_node_catalog()
    elem_catalog = _get_default_element_catalog()

    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    create_nodes(node_catalog)
    apply_boundary_conditions(fix_master_uz=True)
    _define_transforms_and_material()
    create_rigid_diaphragms()

    for et, iN, jN, grp in elem_catalog:
        if grp in TRUSS_GROUPS:
            ops.element('Truss', et, iN, jN, A_belt, 1)
        elif grp == 'COL_EXT':
            ops.element('elasticBeamColumn', et, iN, jN,
                        A_col, E_MDF, G_MDF, J_col, Iy_col, Iz_col, 1)
        elif grp == 'CORE':
            ops.element('elasticBeamColumn', et, iN, jN,
                        A_core, E_MDF, G_MDF, J_core, Iy_core, Iz_core, 1)


def run_seismic_x():
    """1.2g X방향 지진 하중 해석."""
    ops.timeSeries('Constant', 1)
    ops.pattern('Plain', 1, 1)
    for nd, Fx in FLOOR_LOADS_12G_X:
        ops.load(nd, Fx, 0., 0., 0., 0., 0.)

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


def main():
    print()
    print('=' * 65)
    print('  MIDAS vs OpenSees 변위 검증  (1.2g X방향, MIDAS 기본 단면)')
    print('=' * 65)
    print(f'  E = {E_MDF:.1f} N/mm²   G = {G_MDF:.1f} N/mm²   ν = {NU_MDF}')
    print()

    # 모델 빌드 + 해석
    build_model()
    converged = run_seismic_x()

    if not converged:
        print('  [ERROR] 해석 미수렴!')
        return

    # 결과 수집
    ops_dx = {}
    for fl, nd in zip(FLOOR_LABELS, CENTER_NODES):
        d = ops.nodeDisp(nd)
        ops_dx[fl] = d[0]

    # 비교 출력
    print(f'  {"층":<4}  {"z(mm)":>6}  {"MIDAS DX(mm)":>14}  {"OpenSees DX(mm)":>16}  {"Ratio":>7}  {"Error%":>7}')
    print(f'  {"-"*4}  {"-"*6}  {"-"*14}  {"-"*16}  {"-"*7}  {"-"*7}')

    z_vals = [200., 400., 600., 800.]
    all_ok = True
    for fl, z in zip(FLOOR_LABELS, z_vals):
        midas = MIDAS_DX[fl]
        ops_v = ops_dx[fl]
        ratio = ops_v / midas if midas != 0 else float('nan')
        err   = abs(ratio - 1.0) * 100.0
        flag  = '' if err <= 10.0 else '  ← 오차 초과!'
        if err > 10.0:
            all_ok = False
        print(f'  {fl:<4}  {z:>6.0f}  {midas:>14.5f}  {ops_v:>16.5f}  {ratio:>7.4f}  {err:>6.2f}%{flag}')

    print()
    if all_ok:
        print('  [PASS] 모든 층 오차 <= 10% -- MIDAS와 충분히 일치')
        print('         이 모델을 HS evaluator 기준 모델로 사용 가능합니다.')
    else:
        print('  [FAIL] 일부 층 오차 > 10% -- 추가 검토 필요')
    print('=' * 65)
    print()


if __name__ == '__main__':
    main()
