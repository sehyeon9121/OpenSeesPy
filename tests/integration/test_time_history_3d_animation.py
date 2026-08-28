"""3D Time History animation integration: real 3D geometry + recorded steps."""

import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisKind,
    AnalysisRequest,
    AnalysisResult,
    AnalysisStatus,
    NodeResult,
    TimeHistoryStep,
)
from openframe.features.results.deformation.deformed_3d_state import build_deformed_3d_state
from openframe.features.results.presentation.time_history_results_panel import (
    TimeHistoryResultsPanel,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

_FRAME_3D = Path(__file__).resolve().parents[2] / "examples" / "frame_4bay_4story_3d.py"
_DT = 0.02
_NUM_POINTS = 26


def _write_short_motion(path: Path) -> Path:
    lines = [f"NPTS= {_NUM_POINTS}, DT= {_DT} SEC"]
    for index in range(_NUM_POINTS):
        time = index * _DT
        value = math.sin(math.pi * time / ((_NUM_POINTS - 1) * _DT))
        lines.append(f"{value:+.6E}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.resolve()


def _write_mass_cantilever_script(path: Path) -> Path:
    """Minimal 3D cantilever with nodal mass - no bundled example has mass yet."""
    path.write_text(
        """
import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 0.0, 0.0, 3.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)
ops.mass(2, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0)
area = 0.02
ops.geomTransf("Linear", 1, 0.0, 1.0, 0.0)
ops.element(
    "elasticBeamColumn",
    1,
    1,
    2,
    area,
    200000000.0,
    76900000.0,
    1.6e-4,
    8.0e-5,
    8.0e-5,
    1,
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path.resolve()


def _synthetic_steps(model_tags: list[int], num_steps: int = 150) -> tuple[TimeHistoryStep, ...]:
    return tuple(
        TimeHistoryStep(
            time=index * 0.01,
            node_results={
                tag: NodeResult(
                    tag,
                    displacement=(
                        math.sin(index * 0.2 + tag) * 0.001,
                        math.cos(index * 0.15) * 0.0005,
                        math.sin(index * 0.1) * 0.002,
                    ),
                )
                for tag in model_tags
            },
        )
        for index in range(num_steps)
    )


def test_3d_animation_with_real_geometry_and_synthetic_history() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=30).load(_FRAME_3D)
    node_tags = sorted(model.nodes)
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        time_history=_synthetic_steps(node_tags, num_steps=150),
    )

    panel = TimeHistoryResultsPanel()
    panel.show()
    panel.set_model(model)
    panel.show_result(result)
    application.processEvents()

    animation = panel.animation_panel
    assert animation._has_playable_result()
    assert animation._canvas_stack.currentWidget() is animation._3d_view

    state0 = build_deformed_3d_state(model, result, 0, animation._active_deformation_multiplier())
    animation._apply_step(75)
    state_mid = build_deformed_3d_state(
        model, result, 75, animation._active_deformation_multiplier()
    )
    assert state0 is not None and state_mid is not None
    moved_tags = [
        tag
        for tag in node_tags[:5]
        if state0.node_lookup[tag].deformed_x != state_mid.node_lookup[tag].deformed_x
    ]
    assert moved_tags

    animation.slider.setValue(10)
    application.processEvents()
    assert panel.response_history_panel._animation_step_index == 10

    animation._toggle_play()
    for _ in range(5):
        animation._on_tick()
    animation.pause_animation()
    application.processEvents()

    panel.show_result(result)
    assert animation._current_step_index == 0
    assert animation._playing is False
    panel.close()


def test_3d_animation_torsion_markers_sync_with_slider() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=30).load(_FRAME_3D)
    node_tags = sorted(model.nodes)
    steps = tuple(
        TimeHistoryStep(
            time=index * 0.01,
            node_results={
                tag: NodeResult(
                    tag,
                    displacement=(
                        0.0,
                        0.0,
                        0.0,
                        math.sin(index * 0.3 + tag) * 0.01,
                        math.cos(index * 0.2) * 0.005,
                        index * 0.0002,
                    ),
                )
                for tag in node_tags
            },
        )
        for index in range(1, 51)
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)

    panel = TimeHistoryResultsPanel()
    panel.show()
    panel.set_model(model)
    panel.show_result(result)
    application.processEvents()

    animation = panel.animation_panel
    animation.torsion_markers_checkbox.setChecked(True)
    animation.rotation_scale_selector.setCurrentIndex(1)
    animation._apply_step(10)
    application.processEvents()

    bridge = animation._3d_adapter.viewport.bridge
    assert bridge.torsionMarkersVisible
    revision10 = bridge.torsionRevision
    marker_ref = bridge.torsionMarkers

    animation.slider.setValue(25)
    application.processEvents()
    assert bridge.torsionMarkers is marker_ref
    assert bridge.torsionRevision > revision10

    nodes_before = [(node["x"], node["y"], node["z"]) for node in bridge.nodes]
    animation.rotation_scale_selector.setCurrentIndex(3)
    animation._apply_step(25)
    application.processEvents()
    nodes_after = [(node["x"], node["y"], node["z"]) for node in bridge.nodes]
    assert nodes_before == pytest.approx(nodes_after)

    panel.close()


def test_3d_time_history_solver_result_feeds_animation(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    script = _write_mass_cantilever_script(tmp_path / "mass_cantilever_3d.py")
    motion_path = _write_short_motion(tmp_path / "short_pulse.at2")
    model = OpenSeesModelImporter(timeout_seconds=30).load(script)
    request = AnalysisRequest(
        source_path=script,
        kind=AnalysisKind.TIME_HISTORY,
        options={
            "directions": [
                {
                    "dof": 1,
                    "path": str(motion_path),
                    "unit": "model",
                    "scaling_method": "factor",
                    "scale_factor": 0.5,
                }
            ],
            "analysis_time": {
                "duration_mode": "custom",
                "end_time": (_NUM_POINTS - 1) * _DT,
                "dt": _DT,
                "max_dt": 0.0,
            },
            "damping": {"mode": "none"},
            "integrator": {"type": "Newmark", "gamma": 0.5, "beta": 0.25},
            "solution": {
                "algorithm": "ModifiedNewton",
                "test_type": "EnergyIncr",
                "tolerance": 1.0e-8,
                "max_iterations": 50,
                "constraints_type": "Plain",
                "numberer": "Plain",
                "system": "BandGeneral",
            },
        },
    )
    result = OpenSeesProcessRunner(timeout_seconds=120.0).run(request)
    assert result.status == AnalysisStatus.COMPLETED, result.messages
    assert len(result.time_history) >= 2

    panel = TimeHistoryResultsPanel()
    panel.show()
    panel.set_model(model)
    panel.show_result(result)
    application.processEvents()

    animation = panel.animation_panel
    assert animation._canvas_stack.currentWidget() is animation._3d_view
    animation._apply_step(min(5, len(result.time_history) - 1))
    application.processEvents()
    panel.close()
