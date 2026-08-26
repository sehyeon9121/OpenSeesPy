"""UnitSystem's compound-unit label properties - moment/stress/
volumetric_force/force_per_length all derive from just force+length, so a
UI label built from one of these can never drift out of sync with the
other the way a hardcoded literal ("kN/m²") silently did."""

from openframe.core.domain.units import UnitSystem


def test_default_kN_m_system_labels() -> None:
    unit_system = UnitSystem(force="kN", length="m")
    assert unit_system.moment == "kN·m"
    assert unit_system.stress == "kN/m²"
    assert unit_system.volumetric_force == "kN/m³"
    assert unit_system.force_per_length == "kN/m"


def test_labels_track_a_different_force_and_length_choice() -> None:
    unit_system = UnitSystem(force="N", length="mm")
    assert unit_system.moment == "N·mm"
    assert unit_system.stress == "N/mm²"
    assert unit_system.force_per_length == "N/mm"
