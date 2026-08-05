"""
loads.py
========
역할: 하중 케이스(Load Case) 정의
입력: 없음 (상수 기반 객체 생성)
출력:
  - GravityLoadCase dataclass   (중력 하중 전용)
  - SeismicLoadCase dataclass   (수평 지진 하중 전용)
  - get_gravity_load_case()     -> GravityLoadCase
  - get_seismic_load_case_x12() -> SeismicLoadCase
  - get_seismic_load_case_y12() -> SeismicLoadCase
  - get_all_seismic_cases()     -> list[SeismicLoadCase]

중요 원칙:
  - 중력 하중은 z=200, 400, 600, 800 에만 적용
  - base z=0 에는 하중을 절대 적용하지 않음
  - GravityLoadCase와 SeismicLoadCase는 완전히 분리

금지 사항:
  - OpenSees 모델 생성 코드 금지
  - 알고리즘 로직 금지
  - 해석 실행 금지

확장 포인트:
  - 1.3g 하중: get_seismic_load_case_x13() 추가
  - XY 조합하중: get_seismic_load_case_xy12() 추가
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import (
    FLOOR_GRAVITY_N, TOTAL_EXT_GRAV_N,
    NUM_STORIES, GRAVITY_LOAD_Z, BASE_Z,
    SEISMIC_SA_12, SEISMIC_SA_13, GRAVITY_ACC,
)


# ── 중력 하중 케이스 ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GravityLoadCase:
    """
    중력(수직) 하중 케이스.

    하중 위치: z=200, 400, 600, 800 mm (각 층 레벨)
    BASE_Z = 0 에는 하중 없음 (경계조건 위치)
    """
    label            : str   = "GRAVITY"
    floor_mass_kg    : float = 6.0    # kg, 층당 고정하중
    include_self_weight: bool = True  # 부재 자중 포함 여부

    @property
    def floor_force_n(self) -> float:
        """층당 수직 하중 [N] = mass × g."""
        return self.floor_mass_kg * GRAVITY_ACC

    @property
    def total_ext_force_n(self) -> float:
        """전체 외부 수직 하중 [N] = floor_force × 층수."""
        return self.floor_force_n * NUM_STORIES

    @property
    def load_levels_z(self) -> list[float]:
        """하중 적용 z 좌표 목록 [mm]. BASE_Z 미포함."""
        return list(GRAVITY_LOAD_Z)

    @property
    def base_load_prohibited(self) -> bool:
        """BASE_Z=0 에 하중이 없음을 명시 (항상 True)."""
        return True

    def __str__(self) -> str:
        return (f"GravityLoadCase(label={self.label!r}, "
                f"floor={self.floor_force_n:.2f}N × {NUM_STORIES}floors = "
                f"{self.total_ext_force_n:.2f}N, "
                f"levels={self.load_levels_z}mm, "
                f"base_z=0 load: NONE)")


# ── 지진 하중 케이스 ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SeismicLoadCase:
    """
    수평 지진 하중 케이스.
    수직 방향 하중(Fz=0)을 보장.
    """
    label    : str    # 예: "ST_X_12g"
    direction: str    # "X" | "Y" | "XY"
    sa       : float  # 스펙트럼 가속도 배율 (예: 1.2)

    def __post_init__(self) -> None:
        if self.direction not in ("X", "Y", "XY"):
            raise ValueError(f"direction must be X/Y/XY, got {self.direction!r}")

    def __str__(self) -> str:
        return f"SeismicLoadCase({self.label}, dir={self.direction}, sa={self.sa}g)"


# ── Factory 함수 ───────────────────────────────────────────────────────────────

def get_gravity_load_case(
    floor_mass_kg: float = 6.0,
    include_self_weight: bool = True,
) -> GravityLoadCase:
    """
    표준 중력 하중 케이스 반환.
    6kg × 4층 = 24kg → 235.44N 총 외부 수직하중.
    """
    return GravityLoadCase(
        floor_mass_kg     = floor_mass_kg,
        include_self_weight = include_self_weight,
    )


def get_seismic_load_case_x12() -> SeismicLoadCase:
    """1.2g X방향 지진 하중 케이스."""
    return SeismicLoadCase(label="ST_X_12g", direction="X", sa=SEISMIC_SA_12)


def get_seismic_load_case_y12() -> SeismicLoadCase:
    """1.2g Y방향 지진 하중 케이스."""
    return SeismicLoadCase(label="ST_Y_12g", direction="Y", sa=SEISMIC_SA_12)


def get_seismic_load_case_x13() -> SeismicLoadCase:
    """1.3g X방향 지진 하중 케이스."""
    return SeismicLoadCase(label="ST_X_13g", direction="X", sa=SEISMIC_SA_13)


def get_seismic_load_case_y13() -> SeismicLoadCase:
    """1.3g Y방향 지진 하중 케이스."""
    return SeismicLoadCase(label="ST_Y_13g", direction="Y", sa=SEISMIC_SA_13)


def get_all_seismic_cases() -> list[SeismicLoadCase]:
    """LC_12_X, LC_12_Y, LC_13_X, LC_13_Y — 4개 하중 케이스."""
    return [
        get_seismic_load_case_x12(),
        get_seismic_load_case_y12(),
        get_seismic_load_case_x13(),
        get_seismic_load_case_y13(),
    ]
