"""
run/validate_midas_modal_match.py
==================================
검증: mdf_hs_clean OpenSees 모델 vs MIDAS 고유치해석(모드) 비교

MIDAS 기준값: 사용자가 제공한 EIGENVALUE ANALYSIS 출력표(8모드, 참여질량 포함)
모델: modal_model_midas_sections.py (층별 단면, 마스터 노드 집중질량)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_SOURCE = Path(__file__).resolve().with_name("modal_model_midas_sections.py")

# openframe 패키지(레포 루트의 src/)를 sys.path에 추가
REPO_SRC = Path(__file__).resolve().parents[3] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from openframe.infrastructure.opensees.modal_solver import run_modal_analysis  # noqa: E402

# ─── MIDAS 기준 고유치해석 출력 (8모드, Frequency/Period) ────────────────────
MIDAS_MODES = [
    {"mode": 1, "freq_rad_s": 6.1412, "freq_hz": 0.9774, "period": 1.0231},
    {"mode": 2, "freq_rad_s": 6.8800, "freq_hz": 1.0950, "period": 0.9133},
    {"mode": 3, "freq_rad_s": 23.6085, "freq_hz": 3.7574, "period": 0.2661},
    {"mode": 4, "freq_rad_s": 25.2412, "freq_hz": 4.0173, "period": 0.2489},
    {"mode": 5, "freq_rad_s": 57.6831, "freq_hz": 9.1805, "period": 0.1089},
    {"mode": 6, "freq_rad_s": 60.5402, "freq_hz": 9.6353, "period": 0.1038},
    {"mode": 7, "freq_rad_s": 106.0273, "freq_hz": 16.8748, "period": 0.0593},
    {"mode": 8, "freq_rad_s": 110.5251, "freq_hz": 17.5906, "period": 0.0568},
]


def main() -> None:
    print()
    print("=" * 70)
    print("  MIDAS vs OpenSees 고유치(모드) 검증  (mdf_hs_clean, 층별 단면)")
    print("=" * 70)

    result = run_modal_analysis(MODEL_SOURCE, num_modes=8)
    modes = result["mode_shapes"]

    print(f"  {'Mode':<5}{'MIDAS T(s)':>12}{'OpenSees T(s)':>15}{'Ratio':>9}{'Error%':>9}")
    print(f"  {'-'*5}{'-'*12}{'-'*15}{'-'*9}{'-'*9}")

    all_ok = True
    for midas, computed in zip(MIDAS_MODES, modes, strict=False):
        midas_t = midas["period"]
        ops_t = computed["period"]
        ratio = ops_t / midas_t if midas_t else float("nan")
        error = abs(ratio - 1.0) * 100.0
        flag = "" if error <= 15.0 else "  <- 오차 초과!"
        if error > 15.0:
            all_ok = False
        print(
            f"  {midas['mode']:<5}{midas_t:>12.4f}{ops_t:>15.4f}{ratio:>9.4f}{error:>8.2f}%{flag}"
        )

    print()
    if len(modes) < len(MIDAS_MODES):
        print(f"  [주의] OpenSees는 {len(modes)}개 모드만 유효 고유치로 반환 "
              f"(MIDAS {len(MIDAS_MODES)}개 중).")
    if all_ok and len(modes) >= len(MIDAS_MODES):
        print("  [PASS] 모든 모드 오차 <= 15% -- MIDAS와 충분히 일치")
    else:
        print("  [확인 필요] 일부 모드 오차 초과 또는 모드 수 불일치")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
