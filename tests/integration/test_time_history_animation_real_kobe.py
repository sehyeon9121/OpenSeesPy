"""End-to-end: a real bundled Kobe .AT2 record run through the actual
time-history solver, then loaded into the Animation panel - the scenario
Phase 3-I's spec calls out by name (Test 13 / real-app scenario)."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisStatus
from openframe.features.results.presentation.time_history_animation_panel import (
    TimeHistoryAnimationPanel,
)
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

_BUILT_IN_KOBE_AT2 = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "openframe"
    / "infrastructure"
    / "ground_motions"
    / "data"
    / "RSN1116_KOBE_SHI-UP.AT2"
)

_PORTAL_FRAME_MODEL = Path(__file__).resolve().parents[2] / "examples" / "modal_portal_frame_2d.py"


def test_a_real_kobe_run_loads_and_plays_in_the_animation_panel() -> None:
    application = QApplication.instance() or QApplication([])

    model = OpenSeesModelImporter(timeout_seconds=30).load(_PORTAL_FRAME_MODEL)
    runner = OpenSeesProcessRunner(timeout_seconds=120.0)
    request = AnalysisRequest(
        source_path=_PORTAL_FRAME_MODEL,
        kind=AnalysisKind.TIME_HISTORY,
        options={
            "directions": [
                {
                    "dof": 1,
                    "path": str(_BUILT_IN_KOBE_AT2),
                    "unit": "model",
                    "scaling_method": "factor",
                    "scale_factor": 1.0,
                }
            ],
            "damping": {
                "mode": "modal",
                "mode_i": 1,
                "mode_j": 2,
                "ratio_i": 0.05,
                "ratio_j": 0.05,
                "stiffness_term": "initial",
            },
        },
    )

    result = runner.run(request)
    assert result.status == AnalysisStatus.COMPLETED
    # One fewer step than the record's NPTS: End Time defaults to the
    # record's own Duration (dt * (npts - 1) - see GroundMotion.duration).
    assert len(result.time_history) == 4095

    panel = TimeHistoryAnimationPanel()
    panel.show()
    panel.set_model(model)
    panel.show_result(result)

    assert panel._current_step_index == 0
    assert panel._playing is False
    assert panel.slider.maximum() == 4094

    panel._go_to_last()
    assert panel._current_step_index == 4094

    panel._go_to_first()
    panel._toggle_play()
    for _ in range(30):
        panel._on_tick()
    assert 0 < panel._current_step_index < 4094

    panel.scale_selector.setCurrentIndex(0)  # Auto - full 4095-step scan
    panel._apply_step(3000)
    assert panel._current_step_index == 3000
    assert panel.time_step_label.text() != "—"
    application.processEvents()
