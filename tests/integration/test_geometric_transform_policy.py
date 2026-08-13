"""End-to-end coverage for geomTransf preservation and the Direct Modeling vs.
Import GEOMETRIC TRANSFORMATION policy: Import -> internal model -> payload ->
reload -> model rebuild must never lose transformation data, and Setup's
default/override/restore behavior must match each model's own origin."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.features.analysis.presentation.analysis_settings_panel import (
    AnalysisSettingsPanel,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

_2D_FRAME_SOURCE = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 4.0, 0.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf('Linear', 1)
ops.element('elasticBeamColumn', 1, 1, 2, 0.01, 200000.0, 0.0002, 1)
"""

_3D_FRAME_WITH_DISPBEAMCOLUMN_SOURCE = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 4.0, 0.0, 0.0)
ops.node(3, 8.0, 0.0, 0.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)
ops.geomTransf('PDelta', 5, 0.0, 0.0, 1.0)
ops.element(
    'elasticBeamColumn', 1, 1, 2,
    0.01, 200000.0, 80000.0, 0.0001, 0.0002, 0.0002, 5,
)
ops.section('Elastic', 2, 200000.0, 0.01, 0.0002, 0.0002, 80000.0, 0.0001)
ops.beamIntegration('Legendre', 3, 2, 3)
ops.element('dispBeamColumn', 2, 2, 3, 5, 3)
"""


def _import(tmp_path: Path, filename: str, source: str):
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    return OpenSeesModelImporter(timeout_seconds=20).load(path)


def test_2d_elasticbeamcolumn_transform_survives_import(tmp_path: Path) -> None:
    model = _import(tmp_path, "frame2d.py", _2D_FRAME_SOURCE)

    assert model.elements[1].transf_tag == 1
    transform = model.geometric_transforms[1]
    assert transform.transform_type == "Linear"
    assert transform.vector_xz is None


def test_3d_elasticbeamcolumn_and_dispbeamcolumn_transforms_survive_import(
    tmp_path: Path,
) -> None:
    model = _import(tmp_path, "frame3d.py", _3D_FRAME_WITH_DISPBEAMCOLUMN_SOURCE)

    beam_column = model.elements[1]
    assert beam_column.transf_tag == 5
    disp_beam_column = model.elements[2]
    assert disp_beam_column.transf_tag == 5
    assert disp_beam_column.integration_tag == 3

    transform = model.geometric_transforms[5]
    assert transform.transform_type == "PDelta"
    assert transform.vector_xz == (0.0, 0.0, 1.0)


def test_payload_round_trip_preserves_geometric_transforms(tmp_path: Path) -> None:
    """Import -> internal model -> payload -> reload -> rebuild: reconstruct a
    StructuralModel purely from the JSON-shaped payload dict (as if it had
    been saved to disk and loaded back) and confirm nothing about the
    transformation data was lost."""
    importer = OpenSeesModelImporter(timeout_seconds=20)
    model = _import(tmp_path, "frame2d.py", _2D_FRAME_SOURCE)

    payload = {
        "ndm": model.ndm,
        "ndf": model.ndf,
        "nodes": [
            {"tag": node.tag, "x": node.x, "y": node.y, "z": node.z, "ndf": node.ndf}
            for node in model.nodes.values()
        ],
        "elements": [
            {
                "tag": element.tag,
                "node_i": element.node_i,
                "node_j": element.node_j,
                "element_type": element.element_type,
                "properties": element.properties,
                "transf_tag": element.transf_tag,
                "integration_tag": element.integration_tag,
            }
            for element in model.elements.values()
        ],
        "geometric_transforms": [
            {
                "tag": transform.tag,
                "transform_type": transform.transform_type,
                "arguments": list(transform.arguments),
            }
            for transform in model.geometric_transforms.values()
        ],
        "metadata": dict(model.metadata),
    }

    reloaded = importer._to_domain_model(payload)

    assert reloaded.elements[1].transf_tag == 1
    assert reloaded.geometric_transforms[1].transform_type == "Linear"


def test_payload_round_trip_is_backward_compatible_with_old_payloads() -> None:
    """A payload saved before this feature existed has neither
    "geometric_transforms" nor per-element "transf_tag"/"integration_tag"
    keys at all - must load without error, not crash on a missing key."""
    importer = OpenSeesModelImporter(timeout_seconds=20)
    old_payload = {
        "ndm": 2,
        "ndf": 3,
        "nodes": [
            {"tag": 1, "x": 0.0, "y": 0.0},
            {"tag": 2, "x": 4.0, "y": 0.0},
        ],
        "elements": [
            {
                "tag": 1,
                "node_i": 1,
                "node_j": 2,
                "element_type": "elasticBeamColumn",
                "properties": {
                    "A": 0.01,
                    "E": 200000.0,
                    "I": 0.0002,
                    "transf_tag": "1",
                },
            }
        ],
        "boundaries": [],
        "nodal_loads": [],
        "element_loads": [],
        "metadata": {},
    }

    model = importer._to_domain_model(old_payload)

    assert model.elements[1].transf_tag is None
    assert model.geometric_transforms == {}


def test_model_origin_metadata_defaults_to_import_when_undeclared(tmp_path: Path) -> None:
    model = _import(tmp_path, "frame2d.py", _2D_FRAME_SOURCE)
    assert model.metadata["model_origin"] == "import"


def test_model_origin_metadata_reads_the_direct_declaration(tmp_path: Path) -> None:
    source = "OPENFRAME_MODEL_ORIGIN = 'direct'\n" + _2D_FRAME_SOURCE
    model = _import(tmp_path, "frame2d_direct.py", source)
    assert model.metadata["model_origin"] == "direct"


def test_setup_defaults_to_use_model_definition_for_an_import(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    model = _import(tmp_path, "frame2d.py", _2D_FRAME_SOURCE)
    panel = AnalysisSettingsPanel()

    panel.set_model(model)

    assert panel.geometric_transformation.currentData() == "UseModelDefinition"


def test_setup_defaults_to_linear_for_a_direct_model(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    source = "OPENFRAME_MODEL_ORIGIN = 'direct'\n" + _2D_FRAME_SOURCE
    model = _import(tmp_path, "frame2d_direct.py", source)
    panel = AnalysisSettingsPanel()

    panel.set_model(model)

    assert panel.geometric_transformation.currentData() == "Linear"


def test_switching_back_to_use_model_definition_restores_the_original_choice(
    tmp_path: Path,
) -> None:
    """Overriding in Setup must never mutate the loaded StructuralModel -
    switching back to "Use model definition" must show the exact same
    original transform, proving nothing about the stored model changed."""
    QApplication.instance() or QApplication([])
    model = _import(tmp_path, "frame2d.py", _2D_FRAME_SOURCE)
    original_transform_type = model.geometric_transforms[1].transform_type
    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    panel.geometric_transformation.setCurrentIndex(
        panel.geometric_transformation.findData("PDelta")
    )
    assert panel.build_options()["geometric_transform_type"] == "PDelta"
    # The override never touched the model itself - PDelta was only ever
    # applied transiently to an analysis run, never persisted.
    assert model.geometric_transforms[1].transform_type == original_transform_type

    panel.geometric_transformation.setCurrentIndex(
        panel.geometric_transformation.findData("UseModelDefinition")
    )
    assert panel.build_options()["geometric_transform_type"] == "UseModelDefinition"
    assert model.geometric_transforms[1].transform_type == original_transform_type
