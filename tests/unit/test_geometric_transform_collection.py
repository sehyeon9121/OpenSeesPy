"""ModelCommandCollector's geomTransf/beam-column reference collection,
exercised directly against real OpenSeesPy calls - same style as
test_analysis_stage_tracker.py (real ops calls, no worker subprocess)."""

from unittest.mock import patch

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees.model_collector import ModelCommandCollector


def test_geomtransf_2d_definition_captured_without_vector() -> None:
    collector = ModelCommandCollector()
    collector.install()
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.geomTransf("Linear", 7)
    finally:
        collector.restore()
        ops.wipe()

    definition = collector.geom_transf_definitions[7]
    assert definition == {"tag": 7, "transform_type": "Linear", "arguments": []}


def test_geomtransf_3d_definition_captures_vecxz() -> None:
    collector = ModelCommandCollector()
    collector.install()
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.geomTransf("PDelta", 3, 0.0, 0.0, 1.0)
    finally:
        collector.restore()
        ops.wipe()

    definition = collector.geom_transf_definitions[3]
    assert definition["transform_type"] == "PDelta"
    assert definition["arguments"] == [0.0, 0.0, 1.0]


def test_elasticbeamcolumn_2d_records_transf_tag() -> None:
    collector = ModelCommandCollector()
    collector.install()
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 4.0, 0.0)
        ops.fix(1, 1, 1, 1)
        ops.geomTransf("Linear", 5)
        ops.element("elasticBeamColumn", 1, 1, 2, 0.01, 200000.0, 0.0002, 5)
    finally:
        collector.restore()
        ops.wipe()

    element = collector.elements[1]
    assert element["transf_tag"] == 5
    assert element["integration_tag"] is None
    assert element["properties"]["transf_tag"] == "5"
    assert 1 not in collector.unparsed_transform_references


def test_elasticbeamcolumn_3d_records_transf_tag() -> None:
    collector = ModelCommandCollector()
    collector.install()
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0.0, 0.0, 0.0)
        ops.node(2, 4.0, 0.0, 0.0)
        ops.fix(1, 1, 1, 1, 1, 1, 1)
        ops.geomTransf("Linear", 9, 0.0, 0.0, 1.0)
        ops.element(
            "elasticBeamColumn", 1, 1, 2, 0.01, 200000.0, 80000.0, 0.0001, 0.0002, 0.0002, 9
        )
    finally:
        collector.restore()
        ops.wipe()

    element = collector.elements[1]
    assert element["transf_tag"] == 9
    assert element["properties"]["transf_tag"] == "9"


def test_dispbeamcolumn_records_transf_and_integration_tags() -> None:
    collector = ModelCommandCollector()
    collector.install()
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 4.0, 0.0)
        ops.fix(1, 1, 1, 1)
        ops.geomTransf("Linear", 1)
        ops.section("Elastic", 2, 200000.0, 0.01, 0.0002)
        ops.beamIntegration("Legendre", 3, 2, 3)
        ops.element("dispBeamColumn", 1, 1, 2, 1, 3)
    finally:
        collector.restore()
        ops.wipe()

    element = collector.elements[1]
    assert element["transf_tag"] == 1
    assert element["integration_tag"] == 3
    assert element["properties"]["transf_tag"] == "1"
    assert element["properties"]["integration_tag"] == "3"


def test_forcebeamcolumn_records_transf_and_integration_tags() -> None:
    collector = ModelCommandCollector()
    collector.install()
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 4.0, 0.0)
        ops.fix(1, 1, 1, 1)
        ops.geomTransf("Linear", 1)
        ops.section("Elastic", 2, 200000.0, 0.01, 0.0002)
        ops.beamIntegration("Legendre", 4, 2, 3)
        ops.element("forceBeamColumn", 1, 1, 2, 1, 4)
    finally:
        collector.restore()
        ops.wipe()

    element = collector.elements[1]
    assert element["transf_tag"] == 1
    assert element["integration_tag"] == 4


def test_to_payload_includes_geometric_transforms_sorted_by_tag() -> None:
    collector = ModelCommandCollector()
    collector.install()
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 4.0, 0.0)
        ops.fix(1, 1, 1, 1)
        ops.geomTransf("PDelta", 8)
        ops.geomTransf("Linear", 2)
        ops.element("elasticBeamColumn", 1, 1, 2, 0.01, 200000.0, 0.0002, 2)
    finally:
        collector.restore()
        ops.wipe()

    payload = collector.to_payload()
    transforms = payload["geometric_transforms"]
    assert [item["tag"] for item in transforms] == [2, 8]
    assert transforms[0] == {"tag": 2, "transform_type": "Linear", "arguments": []}
    element_payload = next(item for item in payload["elements"] if item["tag"] == 1)
    assert element_payload["transf_tag"] == 2


def test_unknown_geom_transf_type_is_preserved_verbatim_without_override() -> None:
    """A transform type this project does not recognize (real OpenSeesPy would
    itself reject a truly made-up name at the C++ level - see the atomic
    override-rejection test below for the override path) must still be
    recorded exactly as given when no override is installed, never coerced to
    Linear."""
    collector = ModelCommandCollector()
    with patch.object(ops, "geomTransf", return_value=None):
        collector.install()
        try:
            ops.geomTransf("Corotational02", 3, 1.0, 2.0, 3.0)
        finally:
            collector.restore()

    definition = collector.geom_transf_definitions[3]
    assert definition["transform_type"] == "Corotational02"
    assert definition["arguments"] == [1.0, 2.0, 3.0]
    assert "Corotational02" in collector.geom_transf_types


def test_override_active_substitutes_an_overridable_type() -> None:
    collector = ModelCommandCollector()
    collector.install(geom_transf_override="PDelta")
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.geomTransf("Linear", 1)
    finally:
        collector.restore()
        ops.wipe()

    assert collector.geom_transf_types == {"PDelta"}
    # The original type is still what gets recorded for the model's own
    # record-keeping - only the live OpenSees domain actually receives PDelta.
    assert collector.geom_transf_definitions[1]["transform_type"] == "Linear"


def test_override_active_rejects_an_unsupported_transform_type_atomically() -> None:
    """The bogus name never reaches real OpenSeesPy at all - the guard raises
    before calling through to ``ops.geomTransf`` - so this needs no mocking."""
    collector = ModelCommandCollector()
    collector.install(geom_transf_override="PDelta")
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        with pytest.raises(RuntimeError, match="GEOMETRIC TRANSFORMATION"):
            ops.geomTransf("Corotational02", 1)
    finally:
        collector.restore()
        ops.wipe()
