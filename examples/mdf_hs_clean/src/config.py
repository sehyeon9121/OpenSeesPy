"""
config.py
=========
역할: 전체 프로젝트 공통 설정 관리 (단위계: N, mm, kg, s)
입력: 없음 (상수 정의 파일)
출력: 각 모듈이 import해서 사용하는 설정값

금지 사항:
  - 해석 함수, 알고리즘 구현 금지
  - OpenSees import 금지
  - 다른 src 모듈 import 금지
"""

from pathlib import Path

# ── 프로젝트 루트 경로 ─────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "outputs"

OUTPUT_SINGLE_EVAL  = OUTPUT_DIR / "single_eval"
OUTPUT_HS_RUNS      = OUTPUT_DIR / "hs_runs"
OUTPUT_SUMMARIES    = OUTPUT_DIR / "summaries"
OUTPUT_FIGURES      = OUTPUT_DIR / "figures"
OUTPUT_HS_DISCRETE  = OUTPUT_DIR / "hs_discrete"

# ── 데이터 파일 경로 ────────────────────────────────────────────────────────────
COLUMN_RAW_CSV    = DATA_DIR / "column_candidates_raw.csv"     # strip-growth 전체 후보
COLUMN_CSV        = DATA_DIR / "column_candidates_strict.csv"  # 제작성 필터 통과 후보
COLUMN_HS_CSV     = DATA_DIR / "column_candidates_hs.csv"      # HS 최적화용 (dominance 제거 + 정렬)
CORE_CSV          = DATA_DIR / "core_candidates.csv"
NODE_EXCEL        = DATA_DIR / "노드 좌표.xlsx"   # MIDAS 노드/부재 엑셀 (선택)

# ── 층별 분리 HS 후보군 (build_layered_candidates.py 출력) ──────────────────────
COLUMN_HS_BROAD_UNION   = DATA_DIR / "column_hs_broad_union.csv"       # 전체 후보 합집합 (필터 없음)
COLUMN_HS_MAIN_1F3F     = DATA_DIR / "column_hs_main_1F_to_3F.csv"     # 1F~3F 기둥형 조건 필터
COLUMN_HS_UPPER_4F      = DATA_DIR / "column_hs_upper_4F.csv"          # 4F 완화 조건 필터
COLUMN_HS_LAYERED_UNION = DATA_DIR / "column_hs_layered_union.csv"     # main + upper 합집합

# ── 직사각형 외곽 보장 후보군 (build_rectangular_candidates.py 출력) ─────────────
COLUMN_RECT_RAW       = DATA_DIR / "column_rectangular_outline_raw.csv"
COLUMN_RECT_MAIN_1F3F = DATA_DIR / "column_rectangular_outline_main_1F3F.csv"
COLUMN_RECT_UPPER_4F  = DATA_DIR / "column_rectangular_outline_upper_4F.csv"

# ── 구조 형상 (단위: mm) ───────────────────────────────────────────────────────
NUM_STORIES  = 4
STORY_HEIGHT = 200.0   # mm
PLAN_X       = 150.0   # mm  (x 방향 평면 크기)
PLAN_Y       = 150.0   # mm  (y 방향 평면 크기)
TOTAL_HEIGHT = NUM_STORIES * STORY_HEIGHT  # = 800 mm
CENTER_X     = PLAN_X / 2.0  # = 75 mm
CENTER_Y     = PLAN_Y / 2.0  # = 75 mm

# 모서리 기둥 x-y 좌표 (SW, SE, NE, NW 순서)
CORNER_XY = [(0., 0.), (PLAN_X, 0.), (PLAN_X, PLAN_Y), (0., PLAN_Y)]

# 층 레벨 z 좌표 (base는 하중 위치가 아닌 경계조건 위치)
BASE_Z         = 0.     # mm  경계조건 위치 (하중 금지)
FLOOR_Z_LIST   = [200., 400., 600., 800.]   # mm  하중 및 diaphragm 위치
GRAVITY_LOAD_Z = [200., 400., 600., 800.]   # mm  중력 하중 적용 위치 (BASE_Z 제외)

# ── 벨트트러스 형상 (단위: mm) ─────────────────────────────────────────────────
BELT_TOP_Z = 594.0   # mm  top chord 위치
BELT_MID_Z = 569.0   # mm  face midpoint / X-brace 교차점
BELT_BOT_Z = 544.0   # mm  bottom chord 위치

# ── 재료 물성 (단위: N/mm², kg/mm³) ───────────────────────────────────────────
# MIDAS-validated MDF 물성 (scripts/28~30 검증 완료)
# G = E/(2(1+ν)) = 638/(2×1.25) = 255.2 N/mm²
E_MDF        = 638.0          # N/mm²  (MIDAS-validated)
NU_MDF       = 0.25           # MDF Poisson ratio (MIDAS-validated)
G_MDF        = E_MDF / (2.0 * (1.0 + NU_MDF))   # N/mm² = 255.2 N/mm²

# MDF 밀도 (중밀도 섬유판 대표값)
RHO_MDF_KG_M3 = 700.0                  # kg/m³
RHO_MDF       = RHO_MDF_KG_M3 * 1e-9  # kg/mm³

# ── 단면 특성 (MIDAS 단면표 기준, 단위: mm²/mm⁴) ──────────────────────────────
# 기둥: 10×10mm 발사목 스트립 적층 박스 단면
SECTION_COLUMN = {
    'A'  : 96.,    'J' : 864.,    'Iy': 832.,   'Iz': 832.,
    'cy' : 5.0,    'cz': 5.0,
    'member_type': 'column',
}
# 코어: 22×22mm 박스 단면
SECTION_CORE = {
    'A'  : 280.,   'J' : 23328.,  'Iy': 16320., 'Iz': 16320.,
    'cy' : 11.0,   'cz': 11.0,
    'member_type': 'core',
}
# 벨트트러스/아웃리거: 트러스 단면 (축력만 전달)
SECTION_BELT = {
    'A'  : 24.,    'J' : 0.,      'Iy': 0.,     'Iz': 0.,
    'cy' : 0.,     'cz': 0.,
    'member_type': 'belt_truss',
}

# ── 중력 하중 ──────────────────────────────────────────────────────────────────
GRAVITY_ACC       = 9.81    # m/s²
FLOOR_MASS_KG     = 6.0     # kg (층당 고정하중 환산 질량)
FLOOR_GRAVITY_N   = FLOOR_MASS_KG * GRAVITY_ACC   # 58.86 N
TOTAL_EXT_GRAV_N  = FLOOR_GRAVITY_N * NUM_STORIES  # 235.44 N  (z=0에 하중 없음)

# ── 허용응력 기준 (단위: N/mm²) ────────────────────────────────────────────────
F_ALLOW_COLUMN     = 30.0   # TODO: 공모전 기준 확인 후 수정
F_ALLOW_CORE       = 30.0
F_ALLOW_BELT_TRUSS = 30.0

# ── 제약조건 기준 ──────────────────────────────────────────────────────────────
DR_LIMIT = 1.0   # 최대 허용 DR (= σ_combined / F_allow < 1.0)

# ── Harmony Search 파라미터 ────────────────────────────────────────────────────
HS_PARAMS = {
    "HMS"      : 10,     # Harmony Memory Size
    "HMCR"     : 0.90,   # Harmony Memory Consideration Rate
    "PAR"      : 0.30,   # Pitch Adjustment Rate
    "BW"       : 1,      # Bandwidth (이산 변수: index step)
    "MAX_ITER" : 500,    # 최대 반복 횟수
    "NUM_SEEDS": 5,      # 독립 시드 실행 횟수
}

# ── 지진 하중 기준 ──────────────────────────────────────────────────────────────
SEISMIC_SA_12 = 1.2   # 1.2g 수평 스펙트럼 가속도
SEISMIC_SA_13 = 1.3   # 1.3g 수평 스펙트럼 가속도 (붕괴 윈도우 상한)
