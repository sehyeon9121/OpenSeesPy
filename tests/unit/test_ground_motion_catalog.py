from pathlib import Path

import pytest

from openframe.core.domain import GroundMotionSource
from openframe.infrastructure.ground_motions import (
    BuiltInGroundMotionCatalog,
    load_custom_ground_motion,
)
from openframe.infrastructure.ground_motions.peer_format import PeerFormatError, read_peer_at2

_DATA_DIR = Path(__file__).resolve().parents[2] / "src" / "openframe" / "infrastructure" / (
    "ground_motions"
) / "data"


def test_built_in_catalog_lists_every_bundled_record() -> None:
    catalog = BuiltInGroundMotionCatalog()

    records = catalog.list_records()

    assert len(records) == 8
    assert all(record.source == GroundMotionSource.BUILT_IN for record in records)
    assert all(record.npts > 0 and record.dt > 0 for record in records)
    assert len({record.record_id for record in records}) == len(records)


def test_built_in_catalog_load_series_matches_declared_npts() -> None:
    catalog = BuiltInGroundMotionCatalog()
    record = catalog.list_records()[0]

    values = catalog.load_series(record)

    assert len(values) == record.npts


def test_load_custom_ground_motion_reads_a_bundled_file_as_if_user_supplied() -> None:
    sample_path = next(_DATA_DIR.glob("*.AT2"))

    record = load_custom_ground_motion(sample_path)

    assert record.source == GroundMotionSource.CUSTOM
    assert record.path == sample_path
    assert record.npts > 0


def test_read_peer_at2_rejects_a_non_peer_file(tmp_path: Path) -> None:
    bogus = tmp_path / "not_a_record.AT2"
    bogus.write_text("just some\nrandom text\nfile contents\nnot PEER at all\n1 2 3\n")

    with pytest.raises(PeerFormatError):
        read_peer_at2(bogus)
