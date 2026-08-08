"""
visualize_model.py
==================
4층 전단건물 OpenSeesPy 모델 형상 시각화
mdf_4story_test.py 와 동일한 파라미터를 사용

출력: outputs/model_geometry.png
실행: python models/visualize_model.py
"""

from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── 경로 설정 ──────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR  = PROJECT_DIR / 'outputs'
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 한글 폰트 ─────────────────────────────────────────────────
plt.rcParams['font.family']        = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# ================================================================
# 모델 파라미터  (mdf_4story_test.py 와 동일)
# ================================================================
n_stories  = 4
h_story    = 200.0      # mm  층고
mass_floor = 1.0        # N·s²/mm  (= 1 tonne = 1000 kg)
k_floor    = 1000.0     # N/mm

# 절점 y 좌표  [0, 200, 400, 600, 800] mm
y_nodes = [i * h_story for i in range(n_stories + 1)]

# 도형 치수 (층고 비례)
W      = h_story * 0.55   # 슬래브 반폭
GD     = h_story * 0.22   # 지반 해치 깊이
xc     = 0.0              # 중심 x 좌표
slab_h = h_story * 0.13   # 슬래브 두께

# ================================================================
# 보조 함수
# ================================================================

def draw_spring(ax, xc, y0, y1, hw=30, n_coils=6,
                color='steelblue', lw=2.0):
    """
    zeroLength 스프링 요소를 지그재그 코일 선으로 표현.
      xc      : 중심 x
      y0, y1  : 시작·끝 y
      hw      : 지그재그 반폭
      n_coils : 코일 수
    """
    margin = (y1 - y0) * 0.18
    n_pts  = n_coils * 4

    y_zz = np.linspace(y0 + margin, y1 - margin, n_pts)
    x_zz = np.zeros(n_pts)
    for k in range(n_pts):
        p = k % 4
        if   p == 0: x_zz[k] =  hw
        elif p == 1: x_zz[k] =  hw
        elif p == 2: x_zz[k] = -hw
        else:        x_zz[k] = -hw

    xs = [xc] + [xc + x for x in x_zz] + [xc]
    ys = [y0] + list(y_zz)              + [y1]
    ax.plot(xs, ys, color=color, lw=lw,
            solid_capstyle='round', solid_joinstyle='round', zorder=3)


def draw_ground_hatch(ax, xc, y_top, width, depth):
    """지반 해치 사각형 + 상단 실선"""
    rect = mpatches.Rectangle(
        (xc - width/2, y_top - depth), width, depth,
        lw=1.2, ec='k', fc='#d0d0d0', hatch='///', zorder=1
    )
    ax.add_patch(rect)
    ax.plot([xc - width/2, xc + width/2], [y_top, y_top],
            'k-', lw=2.5, zorder=2)


def draw_pin_support(ax, xc, y, size=15):
    """고정 핀 지지 기호 (역삼각형)"""
    tx = [xc - size, xc + size, xc,   xc - size]
    ty = [y - size*1.4, y - size*1.4, y, y - size*1.4]
    ax.fill(tx, ty, color='k', zorder=4)


def draw_slab(ax, xc, y, width, height, label):
    """바닥 슬래브 (질량 블록)"""
    rect = mpatches.FancyBboxPatch(
        (xc - width/2, y - height/2), width, height,
        boxstyle='round,pad=3', lw=1.8,
        ec='#8b5e3c', fc='#f5deb3', zorder=5
    )
    ax.add_patch(rect)
    ax.text(xc, y, label,
            ha='center', va='center', fontsize=9,
            fontweight='bold', color='#5c3d1e', zorder=6)


def draw_dim_line(ax, x, y0, y1, text):
    """수직 치수선 (화살표 + 텍스트)"""
    ax.annotate('', xy=(x, y1), xytext=(x, y0),
                arrowprops=dict(arrowstyle='<->',
                                color='#555555', lw=1.0, mutation_scale=8))
    ax.text(x - 12, (y0 + y1) / 2, text,
            ha='right', va='center', fontsize=8,
            color='#555555', rotation=90)


# ================================================================
# 캔버스 생성
# ================================================================
fig, ax = plt.subplots(figsize=(9, 11))
ax.set_aspect('equal')

# ── 지반 ─────────────────────────────────────────────────────
draw_ground_hatch(ax, xc, y_top=0, width=W * 2.6, depth=GD)
draw_pin_support (ax, xc, y=0)

# 절점 0 레이블
ax.text(xc + W * 1.45, 0, '절점 0  (지반, 고정)',
        va='center', ha='left', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3',
                  fc='white', ec='gray', alpha=0.9))

# ── 각 층: 스프링 + 슬래브 + 절점 + 레이블 ──────────────────
for i in range(n_stories):
    y0 = y_nodes[i]
    y1 = y_nodes[i + 1]

    # 스프링 (zeroLength 요소 시각화)
    draw_spring(ax, xc, y0, y1, hw=W * 0.48,
                n_coils=5, color='steelblue', lw=2.0)

    # 요소 번호 + 강성 레이블 (오른쪽)
    ax.text(xc + W * 0.72, (y0 + y1) / 2,
            f'요소 {i+1}\nk = {k_floor:.0f} N/mm',
            ha='left', va='center', fontsize=8.5, color='steelblue',
            bbox=dict(boxstyle='round,pad=0.3',
                      fc='#e8f4fc', ec='steelblue', alpha=0.9))

    # 치수선 (왼쪽 외곽)
    draw_dim_line(ax,
                  x  = -(W + h_story * 0.38),
                  y0 = y0, y1 = y1,
                  text = f'h = {h_story:.0f} mm')

    # 슬래브
    draw_slab(ax, xc, y1,
              width=W * 2.0, height=slab_h,
              label=f'm = {mass_floor} N·s²/mm   ({i+1}층)')

    # 절점 원
    ax.plot(xc, y1, 'o',
            ms=9, color='k', mfc='white', mew=2, zorder=7)

    # 절점 레이블 (왼쪽)
    ax.text(xc - W * 1.45, y1,
            f'절점 {i+1}  ({i+1}층)',
            va='center', ha='right', fontsize=9,
            bbox=dict(boxstyle='round,pad=0.3',
                      fc='white', ec='gray', alpha=0.9))

# ── 지반가속도 화살표 ─────────────────────────────────────────
ay = -GD * 0.45
ax.annotate('', xy=(xc + W * 1.4, ay), xytext=(xc - W * 0.7, ay),
            arrowprops=dict(arrowstyle='->',
                            color='crimson', lw=2.2, mutation_scale=14))
ax.text(xc + W * 1.5, ay,
        'a_g  (El Centro 1940)\nUniformExcitation',
        va='center', ha='left', fontsize=8.5, color='crimson')

# ── 모델 정보 박스 (우측) ──────────────────────────────────────
info = (
    "모델 정보\n" + "─" * 16 + "\n"
    f"  층수      {n_stories} 층\n"
    f"  층고      {h_story:.0f} mm\n"
    f"  질량/층   {mass_floor} N·s2/mm\n"
    f"  강성/층   {k_floor:.0f} N/mm\n"
    f"  감쇠      Rayleigh 5%\n"
    + "─" * 16 + "\n"
    "단위계\n"
    "  힘: N  길이: mm  시간: s\n"
    "  중력: 9810 mm/s2\n"
    + "─" * 16 + "\n"
    "적분법\n"
    "  Newmark\n"
    "  (gamma=0.5, beta=0.25)"
)
ax.text(W * 3.5, y_nodes[-1] * 0.5, info,
        va='center', ha='left', fontsize=8.2, linespacing=1.55,
        bbox=dict(boxstyle='round,pad=0.6',
                  fc='#fffbe8', ec='#bba040', lw=1.2))

# ── 범례 ──────────────────────────────────────────────────────
legend_items = [
    mpatches.Patch(fc='#f5deb3', ec='#8b5e3c', lw=1.5,
                   label='슬래브 (집중질량 m)'),
    plt.Line2D([0], [0], color='steelblue', lw=2,
               label='zeroLength 스프링 (강성 k)'),
    plt.Line2D([0], [0], marker='o', color='k', lw=0,
               ms=8, mfc='white', mew=2, label='절점 (Node)'),
    mpatches.Patch(fc='#d0d0d0', ec='k', hatch='///',
                   label='지반 (고정단)'),
]
ax.legend(handles=legend_items,
          loc='upper left', fontsize=8.5,
          framealpha=0.95, edgecolor='gray',
          title='범례', title_fontsize=9)

# ── 제목 및 축 설정 ───────────────────────────────────────────
ax.set_title(
    '4층 전단건물 OpenSeesPy 모델 형상\n'
    '1D Shear Building Model  (N – mm – sec)',
    fontsize=13, fontweight='bold', pad=14
)
ax.set_xlabel('수평 방향 [mm]', fontsize=10)
ax.set_ylabel('높이 [mm]',      fontsize=10)
ax.set_xlim(-(W + h_story * 0.85),  W * 6.2)
ax.set_ylim(-GD * 1.6,              n_stories * h_story + h_story * 0.4)
ax.set_yticks(y_nodes)
ax.set_yticklabels(
    [f'지반 (0)' if i == 0 else f'{i}층  ({y_nodes[i]:.0f} mm)'
     for i in range(n_stories + 1)],
    fontsize=8.5
)
ax.grid(True, alpha=0.18, linestyle='--', color='gray')
ax.set_axisbelow(True)

plt.tight_layout()

# ── 저장 ──────────────────────────────────────────────────────
save_path = OUTPUT_DIR / 'model_geometry.png'
plt.savefig(save_path, dpi=250, bbox_inches='tight')
print(f"저장 완료: {save_path}")

plt.show()
