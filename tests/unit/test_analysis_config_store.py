import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind, AnalysisRequest
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)


def test_defaults_to_linear_static_with_no_options() -> None:
    store = AnalysisConfigStore()

    assert store.kind == AnalysisKind.LINEAR_STATIC
    assert store.options == {}


def test_set_kind_emits_kind_changed_with_the_new_kind() -> None:
    QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    received: list[AnalysisKind] = []
    store.kind_changed.connect(received.append)

    store.set_kind(AnalysisKind.NONLINEAR_STATIC)

    assert store.kind == AnalysisKind.NONLINEAR_STATIC
    assert received == [AnalysisKind.NONLINEAR_STATIC]


def test_set_kind_is_a_no_op_when_unchanged() -> None:
    QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    received: list[AnalysisKind] = []
    store.kind_changed.connect(received.append)

    store.set_kind(AnalysisKind.LINEAR_STATIC)

    assert received == []


def test_set_options_emits_options_changed_and_is_readable_back() -> None:
    QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    calls = 0

    def _on_changed() -> None:
        nonlocal calls
        calls += 1

    store.options_changed.connect(_on_changed)

    store.set_options({"control_node": 2})

    assert store.options == {"control_node": 2}
    assert calls == 1


def test_options_property_returns_a_copy_not_the_live_dict() -> None:
    store = AnalysisConfigStore()
    store.set_options({"control_node": 2})

    snapshot = store.options
    snapshot["control_node"] = 999

    assert store.options == {"control_node": 2}


def test_to_request_builds_a_frozen_snapshot_from_current_state() -> None:
    store = AnalysisConfigStore(kind=AnalysisKind.NONLINEAR_STATIC)
    store.set_options({"control_node": 3})

    request = store.to_request(Path("model.py"))

    assert request == AnalysisRequest(
        source_path=Path("model.py"),
        kind=AnalysisKind.NONLINEAR_STATIC,
        options={"control_node": 3},
    )
