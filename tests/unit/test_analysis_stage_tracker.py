"""The analysis-stage tracker and the collector's wipe guard, exercised directly.

Faster and more isolated than going through the worker subprocess: real OpenSeesPy
calls, but no import/JSON round-trip.
"""

import openseespy.opensees as ops

from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import (
    AnalysisStageSuppressor,
    AnalysisStageTracker,
)


def test_tracker_starts_unstarted() -> None:
    assert AnalysisStageTracker().started is False


def test_tracker_flips_when_a_suppressed_command_runs() -> None:
    tracker = AnalysisStageTracker()
    suppressor = AnalysisStageSuppressor()
    suppressor.install(tracker)
    try:
        assert tracker.started is False
        ops.analyze(1)
        assert tracker.started is True
    finally:
        suppressor.restore()


def test_wipe_before_analysis_still_clears_the_collector() -> None:
    """A script rebuilding its model mid-setup (wipe, build again) must still work."""
    tracker = AnalysisStageTracker()
    collector = ModelCommandCollector()
    collector.install(tracker)
    try:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        assert 1 in collector.nodes

        ops.wipe()  # start the model over, before any analysis has happened
        assert collector.nodes == {}

        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(2, 1.0, 0.0)
        assert list(collector.nodes) == [2]
    finally:
        collector.restore()
        ops.wipe()


def test_wipe_after_analysis_does_not_clear_the_collector() -> None:
    """Regression: a cleanup wipe() following the script's own analysis must not
    discard the model the collector already gathered."""
    tracker = AnalysisStageTracker()
    collector = ModelCommandCollector()
    collector.install(tracker)
    try:
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 1.0, 0.0)
        assert set(collector.nodes) == {1, 2}

        tracker.started = True  # stand-in for a suppressed analyze() having run
        ops.wipe()  # end-of-script cleanup, not "start over"

        assert set(collector.nodes) == {1, 2}
    finally:
        collector.restore()
        ops.wipe()
