"""
materials.py
============
역할: MDF 재료 물성 및 단면 특성 정의
입력: 없음 (상수 정의)
출력:
  - get_mdf_properties()       -> dict  (탄성계수, 전단계수, 밀도)
  - get_section_defaults()     -> dict  (MIDAS 기준 단면별 특성)
  - get_section(group_label)   -> dict  (그룹 라벨로 단면 조회)

금지 사항:
  - OpenSees 모델 전체 생성 금지
  - 알고리즘 로직 금지
  - 하중 정의 금지
"""

from __future__ import annotations

from src.config import (
    E_MDF, NU_MDF, G_MDF,
    RHO_MDF, RHO_MDF_KG_M3,
    SECTION_COLUMN, SECTION_CORE, SECTION_BELT,
)


def get_mdf_properties() -> dict:
    """
    MDF 탄성 재료 물성 반환.
    단위계: N, mm

    Returns
    -------
    dict with keys:
        E   : 탄성계수 [N/mm²]  = 638.0 N/mm²
              ※ MIDAS-OpenSees 검증 완료 기준값 (scripts/28~30).
                 현재 최적화에 적용되는 유일한 E값.
                 (과거 주석에 기재된 1226.3 N/mm²는 구(舊) 실험/민감도 분석용 참고값으로,
                  현재 코드에서 사용되지 않음. config.py E_MDF = 638.0이 실제 적용값.)
        G   : 전단계수 [N/mm²]  = E / (2(1+ν)) = 638.0/(2×1.25) = 255.2 N/mm²
        nu  : 포아송비          = 0.25
        rho : 밀도 [kg/mm³]    = 700 kg/m³ × 1e-9
        rho_kg_m3 : 밀도 [kg/m³]
    """
    return {
        "E"         : E_MDF,
        "G"         : G_MDF,
        "nu"        : NU_MDF,
        "rho"       : RHO_MDF,
        "rho_kg_m3" : RHO_MDF_KG_M3,
    }


# ── 단면 그룹 라벨 ──────────────────────────────────────────────────────────────
# OpenSees element 생성 시 사용하는 그룹 식별자
TRUSS_GROUPS  = {'BELT_TC', 'BELT_BC', 'BELT_D', 'OUTR'}
BEAM_GROUPS   = {'COL_EXT', 'CORE'}
ALL_GROUPS    = BEAM_GROUPS | TRUSS_GROUPS


def get_section_defaults() -> dict[str, dict]:
    """
    전체 단면 그룹별 기본 특성 반환 (MIDAS 단면표 기준).
    단위: mm², mm⁴

    Returns
    -------
    dict: {group_label: {A, J, Iy, Iz, cy, cz, member_type}}
    """
    belt_section = dict(SECTION_BELT)
    return {
        'COL_EXT' : dict(SECTION_COLUMN),
        'CORE'    : dict(SECTION_CORE),
        'BELT_TC' : dict(belt_section),
        'BELT_BC' : dict(belt_section),
        'BELT_D'  : dict(belt_section),
        'OUTR'    : dict(belt_section),
    }


def get_section(group_label: str, overrides: dict | None = None) -> dict:
    """
    그룹 라벨로 단면 특성 반환. overrides로 특정 키만 덮어쓸 수 있음.

    Parameters
    ----------
    group_label : 'COL_EXT' | 'CORE' | 'BELT_TC' | 'BELT_BC' | 'BELT_D' | 'OUTR'
    overrides   : {key: value} 형식으로 일부 값 덮어쓰기 (HS 최적화에서 사용)

    Returns
    -------
    dict : 단면 특성

    Raises
    ------
    KeyError : 알 수 없는 group_label
    """
    defaults = get_section_defaults()
    if group_label not in defaults:
        raise KeyError(f"알 수 없는 단면 그룹: {group_label!r}. "
                       f"유효한 그룹: {list(defaults.keys())}")
    sec = dict(defaults[group_label])
    if overrides:
        sec.update(overrides)
    return sec


def merge_section_overrides(
    section_overrides: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """
    기본 단면에 override를 merge하여 최종 단면 dict 반환.
    HS 알고리즘에서 section_overrides={'COL_EXT': {...}} 형태로 호출.

    Parameters
    ----------
    section_overrides : {group_label: {key: value, ...}}  (None이면 기본값)

    Returns
    -------
    dict: {group_label: merged_section_dict}
    """
    defaults = get_section_defaults()
    result = {}
    for grp, props in defaults.items():
        merged = dict(props)
        if section_overrides and grp in section_overrides:
            merged.update(section_overrides[grp])
        result[grp] = merged
    return result


def is_truss(group_label: str) -> bool:
    """그룹이 트러스 요소이면 True."""
    return group_label in TRUSS_GROUPS
