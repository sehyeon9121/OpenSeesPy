"""
mdf_4story_test.py
==================
4층 전단건물(Shear Building) 지진응답 테스트 모델
OpenSeesPy 공식 Nonlinear MDOF 예제 코드 스타일 참고

단위계 : N  –  mm  –  sec
모델형식: 1차원 전단건물 (zeroLength 스프링 요소)
입력지진: El Centro 1940 (example/el_centro.th, g 단위)
적분법 : Newmark β  (γ=0.5, β=0.25 — 평균가속도법)
감쇠    : Rayleigh 5%  (1·2차 모드 기준)
재료    : Steel01 이선형 스프링  (현재 Py 매우 크게 설정 → 탄성 테스트)

출력
----
- outputs/mdf_4story_disp.out          전 층 변위 시계열
- outputs/mdf_4story_roof_disp.out     지붕층 변위 시계열
- outputs/mdf_4story_disp_plot.png     각 층 변위 그래프
- outputs/mdf_4story_drift_plot.png    층간변위 그래프
- outputs/mdf_4story_max_drift.png     최대값 막대 그래프

나중에 확장할 것
-----------------
- Py_floor 값을 줄이면 비선형(항복) 거동 확인 가능
- 4층 MDF 단면 후보를 실제 강성으로 교체
- 1.2g / 1.3g 스케일링, GA 최적화 연계
"""

# ================================================================
# 라이브러리 임포트 및 경로 설정
# ================================================================
from pathlib import Path
import sys

# 이 파일의 위치를 기준으로 폴더 경로 자동 계산
#   MODELS_DIR  → .../OpenSeespy/models/
#   PROJECT_DIR → .../OpenSeespy/
#   EXAMPLE_DIR → .../OpenSeespy/example/
#   OUTPUT_DIR  → .../OpenSeespy/outputs/
MODELS_DIR  = Path(__file__).resolve().parent
PROJECT_DIR = MODELS_DIR.parent
EXAMPLE_DIR = PROJECT_DIR / 'example'
OUTPUT_DIR  = PROJECT_DIR / 'outputs'

# outputs 폴더가 없으면 자동 생성
OUTPUT_DIR.mkdir(exist_ok=True)

# ================================================================
# 시작 메시지
# ================================================================
print("=" * 60)
print("4층 전단건물 테스트 모델 - OpenSeesPy 지진응답 해석")
print("단위계: N - mm - sec")
print(f"결과 저장 폴더: {OUTPUT_DIR}")

EQ_FILE = EXAMPLE_DIR / 'el_centro.th'
if not EQ_FILE.exists():
    raise FileNotFoundError(
        f"지진파 파일을 찾을 수 없습니다:\n  {EQ_FILE}\n"
        "example/ 폴더에 el_centro.th 가 있는지 확인하세요."
    )
print(f"입력 지진파  : {EQ_FILE.name}  (El Centro 1940)")
print("=" * 60)

import openseespy.opensees as ops
import numpy as np
import matplotlib.pyplot as plt

# 한글 폰트 설정 (Windows 기본 내장 폰트)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False   # 마이너스 기호 깨짐 방지

# ================================================================
# 단위계 정의  (N – mm – sec)
# ================================================================
# 모든 숫자는 이 단위계 기준으로 입력
mm  = 1.0          # 길이 기본단위 (밀리미터)
N_  = 1.0          # 힘 기본단위  (뉴턴)     ※ 내장함수 N 과 충돌 방지
sec = 1.0          # 시간 기본단위 (초)

g   = 9810.0       # 중력가속도 (mm/s²)  ← el_centro.th 는 g 단위이므로
                   #  ops.timeSeries의 -factor 에 이 값을 곱해 mm/s² 로 변환

# ================================================================
# 모델 파라미터  (임의값 — 탄성 테스트 목적)
# ================================================================
n_stories = 4                 # 층수 (자유도 수)
h_story   = 200.0 * mm        # 층고 (mm)

# --- 층별 질량 (단위: N·s²/mm = tonne = 1000 kg) ---
# 모든 층 동일한 임의값
# 예시: 1.0 N·s²/mm = 1 tonne = 1000 kg
mass_floor = 1.0

# --- 층별 횡강성 (단위: N/mm) ---
# 모든 층 동일한 임의값
# 예시: 1000 N/mm = 1 kN/mm = 1 MN/m
k_floor    = 1000.0

# --- 층별 항복강도 (단위: N) ---
# ★ 현재 매우 큰 값 → 사실상 탄성 해석
#   비선형 거동(항복)을 확인하려면 이 값을 줄인다
#   (참고: 탄성 최대 하중 ≈ mass × PGA × g ≈ 1.0 × 0.32 × 9810 ≈ 3140 N)
#   예시: Py_floor = 2000.0  → 항복 발생
Py_floor   = 1.0e8            # N  (탄성 테스트)
b_ratio    = 0.01             # 변형경화율 (post-yield stiffness ratio)

# --- Rayleigh 감쇠 ---
xi = 0.05                     # 감쇠비 5 %  (1·2차 모드 기준)

# --- 지진 시간이력 파라미터 ---
dt_eq    = 0.02 * sec         # el_centro.th 데이터 시간 간격 (0.02 s = 20 ms)
dt_out   = 0.001 * sec        # recorder 출력 시간 간격  (1 ms)
tFinal   = 30.0 * sec         # 해석 종료 시간 (El Centro 전체: 31.2 s)

# ================================================================
# OpenSees 모델 구축
# ================================================================
ops.wipe()     # 이전 모델 데이터 초기화 (재실행 시 충돌 방지)

# 1차원 공간(ndm=1), 절점당 자유도 1개(ndf=1)
# → 수평 변위 1개만 고려하는 전단건물 모델
ops.model('basic', '-ndm', 1, '-ndf', 1)

# ------------------------------------------------------------------
# 절점(Node) 생성
#   절점 0  : 지반 (고정단, 질량 없음)
#   절점 1~4: 1층~4층 (각각 질량 부여)
#   node(태그, x좌표)  또는  node(태그, x좌표, '-mass', 질량값)
# ------------------------------------------------------------------
ops.node(0, 0.0)                               # 지반 절점 (고정)
for i in range(1, n_stories + 1):
    ops.node(i, 0.0, '-mass', mass_floor)      # 각 층 절점 + 집중질량

# ------------------------------------------------------------------
# 경계조건(Boundary Condition)
#   fix(절점태그, DOF)   1 = 고정,  0 = 자유
#   지반 절점(0번)은 수평방향 완전 고정
# ------------------------------------------------------------------
ops.fix(0, 1)

# ------------------------------------------------------------------
# 재료(Material) 정의 — Steel01 이선형 재료
#
#   uniaxialMaterial('Steel01', 태그, Fy, E0, b)
#     Fy : 항복강도 (N)
#     E0 : 초기 강성 (N/mm)
#     b  : 변형경화율 (= 후기강성/초기강성)
#
#   각 층마다 별도 재료 태그 사용 (나중에 층별 값을 다르게 할 수 있도록)
# ------------------------------------------------------------------
for i in range(1, n_stories + 1):
    ops.uniaxialMaterial('Steel01', i, Py_floor, k_floor, b_ratio)

# ------------------------------------------------------------------
# 요소(Element) 정의 — zeroLength 스프링 요소
#
#   element('zeroLength', 태그, 절점i, 절점j,
#           '-mat', 재료태그, '-dir', 방향,
#           '-doRayleigh', 1)   ← Rayleigh 감쇠를 이 요소에도 적용
#
#   절점 (i-1) → 절점 i  를 연결하는 층간 스프링
#   방향 1 = x방향 (수평)
# ------------------------------------------------------------------
for i in range(1, n_stories + 1):
    ops.element('zeroLength', i, i - 1, i,
                '-mat', i, '-dir', 1, '-doRayleigh', 1)

# ------------------------------------------------------------------
# 고유치(Eigenvalue) 해석 → 각진동수 계산
# ------------------------------------------------------------------
# eigenvalues 는 ω² (각진동수의 제곱) 리스트
eigenvalues = ops.eigen('-fullGenLapack', n_stories)
omega = np.array(eigenvalues) ** 0.5    # ω (rad/s)

# ------------------------------------------------------------------
# Rayleigh 감쇠 설정
#   1차(w1), 2차(w2) 모드에 동일한 감쇠비 xi 를 적용하는
#   질량비례계수 a0, 강성비례계수 a1 을 계산
#
#   a0 = 2ξ·ω1·ω2 / (ω1+ω2)   (질량 행렬 계수 αM)
#   a1 = 2ξ      / (ω1+ω2)    (현재 강성 행렬 계수 αK_comm)
#
#   rayleigh(alphaM, betaK, betaK_init, betaK_comm)
# ------------------------------------------------------------------
w1, w2 = omega[0], omega[1]
a0 = 2.0 * xi * w1 * w2 / (w1 + w2)
a1 = 2.0 * xi          / (w1 + w2)
ops.rayleigh(a0, 0.0, 0.0, a1)

# 고유주기 출력
print("\n[고유주기 및 고유진동수]")
for i, w in enumerate(omega):
    T = 2.0 * np.pi / w
    f = w / (2.0 * np.pi)
    print(f"  모드 {i+1}: T = {T:.4f} s  |  f = {f:.4f} Hz  |  ω = {w:.4f} rad/s")

# ------------------------------------------------------------------
# 지진 하중 정의
#
#   TimeSeries 'Path': 파일에서 시간이력 가속도를 읽음
#     -dt       : 데이터 시간 간격 (s)
#     -filePath : 가속도 파일 경로 (절대경로 권장)
#     -factor   : 스케일 계수  ← el_centro.th 값이 g 단위이므로
#                               × g(=9810 mm/s²) 해서 mm/s² 로 변환
#
#   UniformExcitation: 모든 고정 절점에 동일한 지반가속도 적용
#     direction 1 = x방향 (수평)
# ------------------------------------------------------------------
ts_tag    = 1
pat_tag   = 1
direction = 1

ops.timeSeries('Path', ts_tag,
               '-dt', dt_eq,
               '-filePath', EQ_FILE.as_posix(),  # 절대경로, 슬래시 구분자
               '-factor', g)                      # g → mm/s² 변환

ops.pattern('UniformExcitation', pat_tag, direction, '-accel', ts_tag)

# ------------------------------------------------------------------
# Recorder 설정  (결과 파일 경로는 절대경로 사용)
#
#   Node recorder: '-time' 옵션 → 첫 번째 열에 시간 저장
#                  '-dT'  옵션 → 출력 시간 간격 지정
# ------------------------------------------------------------------
disp_file = (OUTPUT_DIR / 'mdf_4story_disp.out').as_posix()
roof_file = (OUTPUT_DIR / 'mdf_4story_roof_disp.out').as_posix()

# 전 층 변위 저장 (열 순서: 시간, 1층, 2층, 3층, 4층)
ops.recorder('Node', '-file', disp_file,
             '-time', '-dT', dt_out,
             '-node', 1, 2, 3, 4,
             '-dof', 1, 'disp')

# 지붕층(4층) 변위 별도 저장 (열 순서: 시간, 4층 변위)
ops.recorder('Node', '-file', roof_file,
             '-time', '-dT', dt_out,
             '-node', 4,
             '-dof', 1, 'disp')

# ================================================================
# 동적 해석 실행  (Newmark β법)
#
#   γ = 0.5, β = 0.25  → 평균가속도법 (무조건 안정, 수치감쇠 없음)
# ================================================================
Gamma = 0.5
Beta  = 0.25
tol   = 1.0e-10    # 수렴 허용 오차 (NormUnbalance 기준)
itrs  = 100        # 최대 반복 횟수

ops.wipeAnalysis()
ops.algorithm('Newton')              # Newton-Raphson 반복 알고리즘
ops.system('BandGen')                # 연립방정식: 대역행렬 솔버
ops.numberer('Plain')                # DOF 번호 매기기: 단순 순서
ops.constraints('Plain')             # 구속조건 처리: 직접 치환
ops.integrator('Newmark', Gamma, Beta)
ops.analysis('Transient')            # 시간이력(동적) 해석
ops.test('NormUnbalance', tol, itrs) # 수렴 판정 기준

# 총 해석 스텝 수
num_steps = int(tFinal / dt_out) + 1

print(f"\n[동적 해석 실행 중]")
print(f"  해석 시간: {tFinal} s  |  출력 간격: {dt_out} s  |  스텝 수: {num_steps:,}")

ops.analyze(num_steps, dt_out)
ops.wipe()   # 해석 완료 후 메모리 해제, recorder 파일 닫기

# ================================================================
# 결과 파일 읽기
# ================================================================
disp_data = np.genfromtxt(disp_file)

if disp_data.ndim < 2 or disp_data.shape[1] < n_stories + 1:
    raise RuntimeError(
        f"결과 파일이 예상보다 적은 열을 가집니다: {disp_file}\n"
        "경로 또는 파일 쓰기 권한을 확인하세요."
    )

time  = disp_data[:, 0]      # 시간 배열 (s),   shape: (num_steps,)
disps = disp_data[:, 1:]     # 각 층 변위 (mm), shape: (num_steps, 4)

# ================================================================
# 후처리 계산
# ================================================================

# --- 층간변위 (Story Drift) ---
#   δ_drift[i층] = δ[i층] - δ[i-1층]   (1층은 지반 기준)
drifts = np.zeros_like(disps)
drifts[:, 0] = disps[:, 0]                          # 1층: 지반 대비
for i in range(1, n_stories):
    drifts[:, i] = disps[:, i] - disps[:, i - 1]    # i+1층: 아래층 대비

# --- 층간변위비 (Story Drift Ratio = 층간변위 / 층고) ---
drift_ratios = drifts / h_story

# ================================================================
# 결과 출력
# ================================================================
print("\n" + "=" * 60)
print("[해석 결과 요약]")
print(f"\n  최대 지붕 변위 (4층): {np.max(np.abs(disps[:, -1])):.6f} mm")
print()
print(f"  {'층':>3}  {'최대 층간변위':>14}  {'최대 층간변위비':>14}")
print(f"  {'---':>3}  {'-'*14}  {'-'*14}")
for i in range(n_stories):
    max_d = np.max(np.abs(drifts[:, i]))
    max_r = np.max(np.abs(drift_ratios[:, i])) * 100
    print(f"  {i+1}층  {max_d:>12.6f} mm  {max_r:>12.6f} %")

# ================================================================
# 그래프 생성 및 outputs/ 에 저장
# ================================================================
colors      = ['C1', 'C2', 'C3', 'C4']
floor_labels = [f'{i+1}층' for i in range(n_stories)]

# ---------------------------------------------------------------
# 그래프 1: 각 층 변위 시계열
# ---------------------------------------------------------------
fig, axs = plt.subplots(n_stories, 1, figsize=(11, 9), sharex=True)
fig.suptitle('각 층 상대변위 시계열  [mm]  —  El Centro 1940',
             fontsize=13, fontweight='bold')

for i in range(n_stories):
    peak = np.max(np.abs(disps[:, i]))
    axs[i].plot(time, disps[:, i], colors[i], lw=0.8,
                label=f'{i+1}층  |  최대 = {peak:.4f} mm')
    axs[i].axhline(0, color='k', lw=0.5)
    axs[i].set_ylabel('[mm]', fontsize=9)
    axs[i].legend(loc='upper right', fontsize=9)
    axs[i].grid(True, alpha=0.35)
    axs[i].set_xlim(0, tFinal)

axs[-1].set_xlabel('시간 [s]', fontsize=10)
plt.tight_layout()
p1 = OUTPUT_DIR / 'mdf_4story_disp_plot.png'
plt.savefig(p1, dpi=200)
print(f"\n저장: {p1}")

# ---------------------------------------------------------------
# 그래프 2: 층간변위 시계열
# ---------------------------------------------------------------
fig, axs = plt.subplots(n_stories, 1, figsize=(11, 9), sharex=True)
fig.suptitle('층간변위 시계열  [mm]  —  El Centro 1940',
             fontsize=13, fontweight='bold')

for i in range(n_stories):
    peak_d = np.max(np.abs(drifts[:, i]))
    peak_r = np.max(np.abs(drift_ratios[:, i])) * 100
    axs[i].plot(time, drifts[:, i], colors[i], lw=0.8,
                label=f'{i+1}층  |  최대 = {peak_d:.4f} mm  ({peak_r:.4f} %)')
    axs[i].axhline(0, color='k', lw=0.5)
    axs[i].set_ylabel('[mm]', fontsize=9)
    axs[i].legend(loc='upper right', fontsize=9)
    axs[i].grid(True, alpha=0.35)
    axs[i].set_xlim(0, tFinal)

axs[-1].set_xlabel('시간 [s]', fontsize=10)
plt.tight_layout()
p2 = OUTPUT_DIR / 'mdf_4story_drift_plot.png'
plt.savefig(p2, dpi=200)
print(f"저장: {p2}")

# ---------------------------------------------------------------
# 그래프 3: 층별 최대값 막대 그래프
# ---------------------------------------------------------------
max_drifts = [np.max(np.abs(drifts[:, i]))           for i in range(n_stories)]
max_ratios = [np.max(np.abs(drift_ratios[:, i])) * 100 for i in range(n_stories)]

fig, axs = plt.subplots(1, 2, figsize=(11, 5))
fig.suptitle('층별 최대 층간변위 및 층간변위비  —  El Centro 1940',
             fontsize=13, fontweight='bold')

# 왼쪽: 최대 층간변위 [mm]
axs[0].barh(floor_labels, max_drifts, color=colors,
            edgecolor='k', linewidth=0.5)
axs[0].set_xlabel('최대 층간변위 [mm]', fontsize=10)
axs[0].set_title('최대 층간변위')
axs[0].grid(True, axis='x', alpha=0.4)
for j, v in enumerate(max_drifts):
    axs[0].text(v * 1.02, j, f'{v:.5f} mm', va='center', fontsize=9)

# 오른쪽: 최대 층간변위비 [%]
axs[1].barh(floor_labels, max_ratios, color=colors,
            edgecolor='k', linewidth=0.5)
axs[1].set_xlabel('최대 층간변위비 [%]', fontsize=10)
axs[1].set_title('최대 층간변위비  (= 층간변위 / 층고)')
axs[1].grid(True, axis='x', alpha=0.4)
for j, v in enumerate(max_ratios):
    axs[1].text(v * 1.02, j, f'{v:.5f} %', va='center', fontsize=9)

plt.tight_layout()
p3 = OUTPUT_DIR / 'mdf_4story_max_drift.png'
plt.savefig(p3, dpi=200)
print(f"저장: {p3}")

# 모든 그래프 표시 (창을 닫으면 스크립트 종료)
plt.show()

# ================================================================
# 완료 메시지
# ================================================================
print("\n" + "=" * 60)
print("4층 전단건물 테스트 모델 해석 완료")
print(f"결과 파일 위치: {OUTPUT_DIR}")
print("=" * 60)
