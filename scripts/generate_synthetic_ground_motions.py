"""Generate eight independent synthetic ground motions from engineering targets.

The bundled PEER records are read only to estimate aggregate engineering
features (smoothed spectral content, response spectrum, Arias duration and
intensity).  Their sample phases and sample sequences are never reused.

Outputs are explicitly labelled as synthetic, not observed earthquake records.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy import integrate, ndimage, signal, stats

G = 9.80665
ROOT = Path(".")
SOURCE_DIR = (
    ROOT
    / "src"
    / "openframe"
    / "infrastructure"
    / "ground_motions"
    / "reference_data_not_shipped"
)
OUTPUT_DIR = ROOT / "outputs" / "synthetic_ground_motions_8"


@dataclass(frozen=True)
class Archetype:
    code: str
    rsn: int
    label_ko: str
    characteristic_en: str
    h1: str
    h2: str
    seed: int
    pulse_period: float | None = None
    pulse_weight: float = 0.0


ARCHETYPES = (
    Archetype(
        "SYN01",
        125,
        "짧은 지속시간·광대역 충격형",
        "short-duration broadband impulsive",
        "RSN125_FRIULI.A_A-TMZ000.AT2",
        "RSN125_FRIULI.A_A-TMZ270.AT2",
        125137,
    ),
    Archetype(
        "SYN02",
        1602,
        "강한 단주기 속도펄스형",
        "short-period forward-directivity pulse",
        "RSN1602_DUZCE_BOL000.AT2",
        "RSN1602_DUZCE_BOL090.AT2",
        160203,
        pulse_period=0.882,
        pulse_weight=0.45,
    ),
    Archetype(
        "SYN03",
        767,
        "중주기 속도펄스·역단층형",
        "medium-period velocity pulse",
        "RSN767_LOMAP_G03000.AT2",
        "RSN767_LOMAP_G03090.AT2",
        767071,
        pulse_period=2.639,
        pulse_weight=0.45,
    ),
    Archetype(
        "SYN04",
        879,
        "근단층 장주기 대형 펄스형",
        "near-fault long-period large pulse",
        "RSN879_LANDERS_LCN260.AT2",
        "RSN879_LANDERS_LCN345.AT2",
        879083,
        pulse_period=5.124,
        pulse_weight=0.65,
    ),
    Archetype(
        "SYN05",
        953,
        "단지속·역단층 고강도형",
        "short-duration high-intensity reverse-fault motion",
        "RSN953_NORTHR_MUL009.AT2",
        "RSN953_NORTHR_MUL279.AT2",
        953109,
    ),
    Archetype(
        "SYN06",
        169,
        "연약지반·매우 긴 지속시간형",
        "very-long-duration soft-soil motion",
        "RSN169_IMPVALL.H_H-DLT262.AT2",
        "RSN169_IMPVALL.H_H-DLT352.AT2",
        169097,
    ),
    Archetype(
        "SYN07",
        1244,
        "장지속·장주기 역단층형",
        "long-duration reverse-oblique motion",
        "RSN1244_CHICHI_CHY101-E.AT2",
        "RSN1244_CHICHI_CHY101-N.AT2",
        1244101,
        pulse_period=5.341,
        pulse_weight=0.50,
    ),
    Archetype(
        "SYN08",
        1633,
        "장지속·고에너지 암반형",
        "long-duration high-energy firm-ground motion",
        "RSN1633_MANJIL_ABBAR--L.AT2",
        "RSN1633_MANJIL_ABBAR--T.AT2",
        1633107,
    ),
)


_NPTS_DT_RE = re.compile(
    r"NPTS\s*=\s*(\d+)\s*,\s*DT\s*=\s*([0-9.eE+-]+)", re.IGNORECASE
)


def read_peer_series(path: Path) -> tuple[float, np.ndarray]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 5:
        raise ValueError(f"Invalid PEER file: {path}")
    match = _NPTS_DT_RE.search(lines[3])
    if not match:
        raise ValueError(f"NPTS/DT not found: {path}")
    npts, dt = int(match.group(1)), float(match.group(2))
    values = np.asarray([float(token) for line in lines[4:] for token in line.split()])
    if values.size != npts:
        raise ValueError(f"{path.name}: expected {npts}, found {values.size}")
    return dt, values


def arias_intensity(acc_g: np.ndarray, dt: float) -> float:
    return float(math.pi * G / 2.0 * np.sum(np.square(acc_g)) * dt)


def arias_times(acc_g: np.ndarray, dt: float) -> tuple[float, float, float]:
    energy = np.cumsum(np.square(acc_g))
    if energy[-1] <= 0.0:
        return 0.0, 0.0, 0.0
    normalized = energy / energy[-1]
    return tuple(float(np.searchsorted(normalized, q) * dt) for q in (0.05, 0.50, 0.95))


def pgv(acc_g: np.ndarray, dt: float) -> float:
    velocity = integrate.cumulative_trapezoid(acc_g * G, dx=dt, initial=0.0)
    velocity = signal.detrend(velocity, type="linear")
    return float(np.max(np.abs(velocity)))


def response_spectrum(
    acc_g: np.ndarray, dt: float, periods: np.ndarray, damping: float = 0.05
) -> np.ndarray:
    """5%-damped pseudo-acceleration response spectrum in g.

    Each SDOF is discretized exactly under a zero-order-held ground
    acceleration, avoiding time-step-dependent Newmark tuning.
    """
    result = np.empty_like(periods)
    for index, period in enumerate(periods):
        omega = 2.0 * math.pi / float(period)
        numerator = np.asarray([-1.0])
        denominator = np.asarray([1.0, 2.0 * damping * omega, omega * omega])
        num_d, den_d, _ = signal.cont2discrete((numerator, denominator), dt, method="zoh")
        displacement = signal.lfilter(np.ravel(num_d), np.ravel(den_d), acc_g)
        result[index] = omega * omega * np.max(np.abs(displacement))
    return result


def bandpass_and_detrend(values: np.ndarray, dt: float) -> np.ndarray:
    values = signal.detrend(values, type="linear")
    nyquist = 0.5 / dt
    low = 0.06
    high = min(25.0, nyquist * 0.90)
    sos = signal.butter(4, (low, high), btype="bandpass", fs=1.0 / dt, output="sos")
    filtered = signal.sosfiltfilt(sos, values)
    return signal.detrend(filtered, type="linear")


def smoothed_fourier_amplitude(values: np.ndarray, dt: float) -> np.ndarray:
    npts = values.size
    tapered = signal.detrend(values) * signal.windows.tukey(npts, alpha=0.08)
    amplitude = np.abs(np.fft.rfft(tapered))
    floor = max(float(np.max(amplitude)) * 1.0e-8, 1.0e-12)
    smoothed = np.exp(ndimage.gaussian_filter1d(np.log(np.maximum(amplitude, floor)), 7.0))
    frequencies = np.fft.rfftfreq(npts, dt)
    smoothed[frequencies < 0.04] = 0.0
    smoothed[frequencies > min(30.0, 0.48 / dt)] = 0.0
    smoothed[0] = 0.0
    return smoothed


def independent_envelope(npts: int, dt: float, target: np.ndarray) -> np.ndarray:
    """Parametric lognormal energy envelope fitted only to t5 and t95."""
    t = np.arange(npts) * dt
    t5, _, t95 = arias_times(target, dt)
    t5 = max(t5, 3.0 * dt)
    t95 = max(t95, t5 + 20.0 * dt)
    z5, z95 = stats.norm.ppf(0.05), stats.norm.ppf(0.95)
    sigma = max(0.12, (math.log(t95) - math.log(t5)) / (z95 - z5))
    mu = math.log(t5) - sigma * z5
    shifted_t = np.maximum(t, dt * 0.25)
    energy_pdf = stats.lognorm.pdf(shifted_t, s=sigma, scale=math.exp(mu))
    envelope = np.sqrt(np.maximum(energy_pdf, 0.0))
    if np.max(envelope) > 0:
        envelope /= np.max(envelope)
    envelope *= signal.windows.tukey(npts, alpha=0.04)
    return envelope


def velocity_pulse_acceleration(
    npts: int, dt: float, period: float, center: float, rng: np.random.Generator
) -> np.ndarray:
    """A new smooth finite-duration velocity pulse, returned as acceleration/g."""
    t = np.arange(npts) * dt
    width = max(0.40 * period, 5.0 * dt)
    phase = rng.uniform(-math.pi, math.pi)
    tau = t - center
    velocity = np.exp(-0.5 * np.square(tau / width)) * np.cos(2.0 * math.pi * tau / period + phase)
    acceleration = np.gradient(velocity, dt) / G
    return bandpass_and_detrend(acceleration, dt)


def scale_to_arias(values: np.ndarray, dt: float, target_arias: float) -> np.ndarray:
    current = arias_intensity(values, dt)
    if current <= 0.0:
        raise ValueError("Cannot scale a zero-energy motion")
    return values * math.sqrt(target_arias / current)


def max_normalized_cross_correlation(left: np.ndarray, right: np.ndarray) -> float:
    left = left - np.mean(left)
    right = right - np.mean(right)
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    if denominator <= 0.0:
        return 0.0
    correlation = signal.correlate(left, right, mode="full", method="fft") / denominator
    return float(np.max(np.abs(correlation)))


def synthesize(
    archetype: Archetype, target: np.ndarray, dt: float, periods: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(archetype.seed)
    npts = target.size
    target_arias = arias_intensity(target, dt)
    target_pgv = pgv(target, dt)
    target_sa = response_spectrum(target, dt, periods)
    amplitude = smoothed_fourier_amplitude(target, dt)
    phase = rng.uniform(-math.pi, math.pi, amplitude.size)
    phase[0] = 0.0
    if npts % 2 == 0:
        phase[-1] = 0.0
    envelope = independent_envelope(npts, dt, target)
    _, t50, _ = arias_times(target, dt)
    pulse = np.zeros(npts)
    if archetype.pulse_period is not None:
        pulse_center = min(max(t50 + rng.uniform(-0.10, 0.10) * archetype.pulse_period, 0.0), (npts - 1) * dt)
        pulse = velocity_pulse_acceleration(
            npts, dt, archetype.pulse_period, pulse_center, rng
        )
        pulse_pgv = pgv(pulse, dt)
        if pulse_pgv > 0.0:
            pulse *= archetype.pulse_weight * target_pgv / pulse_pgv

    frequencies = np.fft.rfftfreq(npts, dt)
    min_frequency = 1.0 / float(periods[-1])
    max_frequency = 1.0 / float(periods[0])

    def realization(current_amplitude: np.ndarray) -> np.ndarray:
        stationary = np.fft.irfft(current_amplitude * np.exp(1j * phase), n=npts)
        stationary_std = max(float(np.std(stationary)), 1.0e-12)
        candidate = bandpass_and_detrend((stationary / stationary_std) * envelope, dt)
        if archetype.pulse_weight > 0.0:
            pulse_energy = arias_intensity(pulse, dt)
            base_energy = max(target_arias - pulse_energy, 0.30 * target_arias)
            candidate = scale_to_arias(candidate, dt, base_energy) + pulse
            candidate = bandpass_and_detrend(candidate, dt)
        return scale_to_arias(candidate, dt, target_arias)

    # Iteratively correct the smooth Fourier amplitude against the target
    # response spectrum.  The exponent below deliberately under-relaxes each
    # step so the nonstationary envelope and pulse characteristics remain.
    for _ in range(24):
        candidate = realization(amplitude)
        current_sa = response_spectrum(candidate, dt, periods)
        ratio = np.clip(target_sa / np.maximum(current_sa, 1.0e-8), 0.60, 1.65)
        spectrum_frequencies = (1.0 / periods)[::-1]
        log_ratio = np.log(ratio[::-1])
        adjustment = np.zeros_like(frequencies)
        active = (frequencies >= min_frequency) & (frequencies <= max_frequency)
        adjustment[active] = np.interp(
            np.log(frequencies[active]), np.log(spectrum_frequencies), log_ratio
        )
        amplitude *= np.exp(0.62 * adjustment)
        amplitude = np.exp(
            ndimage.gaussian_filter1d(np.log(np.maximum(amplitude, 1.0e-15)), 0.35)
        )
        amplitude[frequencies < 0.04] = 0.0
        amplitude[frequencies > min(30.0, 0.48 / dt)] = 0.0
        amplitude[0] = 0.0

    synthetic = realization(amplitude)
    synthetic_sa = response_spectrum(synthetic, dt, periods)
    return synthetic, target_sa, synthetic_sa


def write_at2(path: Path, archetype: Archetype, dt: float, values: np.ndarray) -> None:
    lines = [
        "SYNTHETIC GROUND MOTION - NOT AN OBSERVED EARTHQUAKE RECORD",
        f"SYNTHETIC {archetype.code}, 2026-08-18, CALIBRATED-RSN{archetype.rsn}, X",
        "ACCELERATION TIME SERIES IN UNITS OF G",
        f"NPTS= {values.size:7d}, DT= {dt:9.6f} SEC,",
    ]
    for start in range(0, values.size, 5):
        lines.append("".join(f"{value:16.7E}" for value in values[start : start + 5]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_time_csv(path: Path, dt: float, values: np.ndarray) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(("time_s", "acceleration_g"))
        writer.writerows((f"{index * dt:.6f}", f"{value:.9e}") for index, value in enumerate(values))


def choose_target(archetype: Archetype) -> tuple[str, float, np.ndarray]:
    candidates = []
    for name in (archetype.h1, archetype.h2):
        dt, values = read_peer_series(SOURCE_DIR / name)
        candidates.append((arias_intensity(values, dt), name, dt, values))
    _, name, dt, values = max(candidates, key=lambda item: item[0])
    return name, dt, values


def plot_motion(
    archetype: Archetype,
    dt: float,
    synthetic: np.ndarray,
    periods: np.ndarray,
    target_sa: np.ndarray,
    synthetic_sa: np.ndarray,
) -> None:
    time = np.arange(synthetic.size) * dt
    figure, axes = plt.subplots(2, 1, figsize=(10.5, 6.5), constrained_layout=True)
    axes[0].plot(time, synthetic, color="#145DA0", linewidth=0.75)
    axes[0].axhline(0.0, color="#777777", linewidth=0.5)
    axes[0].set_title(f"{archetype.code} — {archetype.characteristic_en}")
    axes[0].set_xlabel("Time (s)")
    axes[0].set_ylabel("Acceleration (g)")
    axes[0].grid(alpha=0.22)
    axes[1].loglog(periods, target_sa, color="#7F8C8D", linewidth=1.4, label="Calibration target")
    axes[1].loglog(periods, synthetic_sa, color="#D35400", linewidth=1.4, label="Synthetic")
    axes[1].set_xlabel("Period (s)")
    axes[1].set_ylabel("5% damped PSA (g)")
    axes[1].grid(which="both", alpha=0.22)
    axes[1].legend()
    figure.savefig(OUTPUT_DIR / f"{archetype.code}_verification.png", dpi=160)
    plt.close(figure)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | float | int]] = []
    overview: list[tuple[Archetype, float, np.ndarray]] = []

    for archetype in ARCHETYPES:
        source_name, dt, target = choose_target(archetype)
        periods = np.geomspace(max(0.06, 4.0 * dt), min(8.0, (target.size - 1) * dt / 4.0), 72)
        synthetic, target_sa, synthetic_sa = synthesize(archetype, target, dt, periods)
        target_t5, _, target_t95 = arias_times(target, dt)
        syn_t5, _, syn_t95 = arias_times(synthetic, dt)
        log_error = np.log(np.maximum(synthetic_sa, 1.0e-9) / np.maximum(target_sa, 1.0e-9))
        correlation = max_normalized_cross_correlation(target, synthetic)
        row = {
            "synthetic_id": archetype.code,
            "characteristic_ko": archetype.label_ko,
            "calibration_reference": f"PEER NGA-West2 RSN {archetype.rsn}",
            "selected_reference_component": source_name,
            "random_seed": archetype.seed,
            "dt_s": dt,
            "npts": synthetic.size,
            "duration_s": (synthetic.size - 1) * dt,
            "target_pga_g": float(np.max(np.abs(target))),
            "synthetic_pga_g": float(np.max(np.abs(synthetic))),
            "target_pgv_m_s": pgv(target, dt),
            "synthetic_pgv_m_s": pgv(synthetic, dt),
            "target_arias_m_s": arias_intensity(target, dt),
            "synthetic_arias_m_s": arias_intensity(synthetic, dt),
            "target_d5_95_s": target_t95 - target_t5,
            "synthetic_d5_95_s": syn_t95 - syn_t5,
            "spectrum_log_rmse": float(np.sqrt(np.mean(np.square(log_error)))),
            "spectrum_median_ratio": float(np.exp(np.median(log_error))),
            "max_normalized_cross_correlation": correlation,
            "pulse_period_s": archetype.pulse_period or "",
        }
        rows.append(row)
        write_at2(OUTPUT_DIR / f"{archetype.code}.AT2", archetype, dt, synthetic)
        write_time_csv(OUTPUT_DIR / f"{archetype.code}.csv", dt, synthetic)
        plot_motion(archetype, dt, synthetic, periods, target_sa, synthetic_sa)
        overview.append((archetype, dt, synthetic))

    summary_path = OUTPUT_DIR / "validation_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    figure, axes = plt.subplots(4, 2, figsize=(13, 13), constrained_layout=True)
    for axis, (archetype, dt, values) in zip(axes.ravel(), overview, strict=True):
        time = np.arange(values.size) * dt
        axis.plot(time, values, linewidth=0.60, color="#145DA0")
        axis.set_title(f"{archetype.code} · {archetype.characteristic_en}", fontsize=9)
        axis.set_xlabel("Time (s)")
        axis.set_ylabel("g")
        axis.grid(alpha=0.18)
    figure.suptitle("Eight independent synthetic ground motions", fontsize=15)
    figure.savefig(OUTPUT_DIR / "synthetic_ground_motions_overview.png", dpi=170)
    plt.close(figure)

    readme_lines = [
        "# 인공지진파 8종",
        "",
        "이 폴더의 파형은 실제 계측기록이 아니라 독립 생성된 인공지진파입니다.",
        "원본 가속도 샘플·위상·시간계열을 복제하지 않았으며, PEER NGA-West2 기록에서",
        "응답스펙트럼·Arias 강도·유효지속시간·평활화된 주파수 특성만 보정 목표로 사용했습니다.",
        "",
        "## 사용 파일",
        "",
        "- `SYN01.AT2`~`SYN08.AT2`: OpenFrame/OpenSeesPy 입력용, 단위 g",
        "- `SYN01.csv`~`SYN08.csv`: 시간(s), 가속도(g) 2열 파일",
        "- `validation_summary.csv`: 목표값과 생성값, 스펙트럼 오차, 원본 비유사성 지표",
        "- `*_verification.png`: 시간이력과 5% 감쇠 응답스펙트럼 비교",
        "",
        "## 파형 유형",
        "",
    ]
    for archetype in ARCHETYPES:
        readme_lines.append(
            f"- `{archetype.code}`: {archetype.label_ko} "
            f"(보정 참조: PEER NGA-West2 RSN {archetype.rsn})"
        )
    readme_lines.extend(
        [
            "",
            "## 공개 표기 권장문",
            "",
            "> 본 데이터는 PEER NGA-West2 기록의 공학적 특성을 통계적으로 참고하여",
            "> 독립 생성한 인공지진파입니다. 원본 계측 시간계열은 포함하지 않습니다.",
            "> 실제 지진 기록이 아니며 설계 적용 전 별도 검증이 필요합니다.",
            "",
            "## 주의",
            "",
            "이 파형은 프로그램 예제·연구·알고리즘 시험용 초안입니다. 설계기준 적합성이나",
            "특정 부지의 위험도를 자동으로 보장하지 않습니다. 실제 설계에는 목표 설계스펙트럼,",
            "부지조건 및 적용 기준에 대한 별도 검토가 필요합니다.",
            "",
        ]
    )
    (OUTPUT_DIR / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")

    print(f"Generated {len(rows)} synthetic motions in {OUTPUT_DIR}")
    for row in rows:
        print(
            f"{row['synthetic_id']}: PGA={row['synthetic_pga_g']:.3f} g, "
            f"D5-95={row['synthetic_d5_95_s']:.2f} s, "
            f"Sa log-RMSE={row['spectrum_log_rmse']:.3f}, "
            f"max xcorr={row['max_normalized_cross_correlation']:.3f}"
        )


if __name__ == "__main__":
    main()
