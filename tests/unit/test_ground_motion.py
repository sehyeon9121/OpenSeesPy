from pathlib import Path

import pytest

from openframe.infrastructure.opensees.ground_motion import (
    load_ground_motion,
    parse_ground_motion,
)

_BUILT_IN_KOBE_AT2 = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "openframe"
    / "infrastructure"
    / "ground_motions"
    # Real PEER record from the bundled catalog - see data/README.md.
    / "data"
    / "RSN1116_KOBE_SHI-UP.AT2"
)


def test_parses_a_peer_nga_style_header_and_values(tmp_path: Path) -> None:
    path = tmp_path / "motion.AT2"
    path.write_text(
        "PACIFIC EARTHQUAKE ENGINEERING RESEARCH CENTER\n"
        "SOME STATION, SOME EVENT\n"
        "ACCELERATION TIME HISTORY IN UNITS OF G\n"
        "NPTS=   6, DT=  .0200 SEC\n"
        " 0.1000  0.2000  0.3000\n"
        " 0.4000  0.5000  0.6000\n",
        encoding="utf-8",
    )

    dt, values = parse_ground_motion(path)

    assert dt == pytest.approx(0.02)
    assert values == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])


def test_npts_header_tolerates_varied_spacing_and_case(tmp_path: Path) -> None:
    path = tmp_path / "motion.txt"
    path.write_text("npts:4  dt:0.005\n1 2 3 4\n", encoding="utf-8")

    dt, values = parse_ground_motion(path)

    assert dt == pytest.approx(0.005)
    assert values == pytest.approx([1.0, 2.0, 3.0, 4.0])


def test_rejects_a_header_claiming_more_points_than_are_actually_present(tmp_path: Path) -> None:
    path = tmp_path / "motion.txt"
    path.write_text("NPTS=10, DT=0.01\n1 2 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="NPTS"):
        parse_ground_motion(path)


def test_falls_back_to_a_two_column_time_acceleration_file(tmp_path: Path) -> None:
    path = tmp_path / "motion.csv"
    path.write_text("0.00,0.10\n0.02,0.20\n0.04,-0.15\n", encoding="utf-8")

    dt, values = parse_ground_motion(path)

    assert dt == pytest.approx(0.02)
    assert values == pytest.approx([0.10, 0.20, -0.15])


def test_single_column_file_requires_an_explicit_dt(tmp_path: Path) -> None:
    path = tmp_path / "motion.txt"
    path.write_text("0.1\n0.2\n0.3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dt"):
        parse_ground_motion(path)

    dt, values = parse_ground_motion(path, dt=0.01)
    assert dt == pytest.approx(0.01)
    assert values == pytest.approx([0.1, 0.2, 0.3])


def test_rejects_a_file_with_no_numeric_data(tmp_path: Path) -> None:
    path = tmp_path / "motion.txt"
    path.write_text("this file has no numbers in it at all\n", encoding="utf-8")

    with pytest.raises(ValueError):
        parse_ground_motion(path)


def test_rejects_a_header_with_a_non_positive_dt(tmp_path: Path) -> None:
    path = tmp_path / "motion.txt"
    path.write_text("NPTS=3, DT=0 SEC\n1 2 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="DT"):
        parse_ground_motion(path)


class TestLoadGroundMotion:
    """`load_ground_motion` wraps `parse_ground_motion` as a `GroundMotion`,
    the common structure Phase 3-F introduces so the SETUP UI and the
    time-history solver both work with the same loaded-motion shape instead
    of a bare path string."""

    def test_wraps_a_peer_style_header_file_with_full_metadata(self, tmp_path: Path) -> None:
        path = tmp_path / "motion.AT2"
        path.write_text(
            "PACIFIC EARTHQUAKE ENGINEERING RESEARCH CENTER\n"
            "SOME STATION, SOME EVENT\n"
            "ACCELERATION TIME SERIES IN UNITS OF G\n"
            "NPTS=   4, DT=  0.0200 SEC\n"
            " 0.1000  -0.5000  0.3000  0.2000\n",
            encoding="utf-8",
        )

        motion = load_ground_motion(path)

        assert motion.name == "motion"
        assert motion.path == path
        assert motion.dt == pytest.approx(0.02)
        assert motion.npts == 4
        assert motion.accelerations == pytest.approx([0.1, -0.5, 0.3, 0.2])
        assert motion.duration == pytest.approx(0.02 * 3)
        assert motion.pga == pytest.approx(0.5)
        assert motion.unit == "G"

    def test_a_plain_two_column_file_has_no_detectable_unit(self, tmp_path: Path) -> None:
        path = tmp_path / "motion.csv"
        path.write_text("0.00,0.10\n0.02,-0.30\n0.04,0.20\n", encoding="utf-8")

        motion = load_ground_motion(path)

        assert motion.unit is None
        assert motion.npts == 3
        assert motion.pga == pytest.approx(0.30)

    def test_supports_dat_extension_with_a_header(self, tmp_path: Path) -> None:
        path = tmp_path / "motion.dat"
        path.write_text("NPTS=3, DT=0.01 SEC\n1.0 -2.0 0.5\n", encoding="utf-8")

        motion = load_ground_motion(path)

        assert motion.dt == pytest.approx(0.01)
        assert motion.npts == 3
        assert motion.pga == pytest.approx(2.0)

    def test_a_malformed_file_raises_instead_of_returning_a_motion(self, tmp_path: Path) -> None:
        path = tmp_path / "motion.txt"
        path.write_text("not a ground motion file\n", encoding="utf-8")

        with pytest.raises(ValueError):
            load_ground_motion(path)

    def test_loads_a_real_bundled_kobe_at2_file(self) -> None:
        motion = load_ground_motion(_BUILT_IN_KOBE_AT2)

        assert motion.npts == 4096
        assert motion.dt == pytest.approx(0.01)
        assert motion.duration == pytest.approx(0.01 * 4095)
        assert motion.unit == "G"
        assert motion.pga > 0.0
