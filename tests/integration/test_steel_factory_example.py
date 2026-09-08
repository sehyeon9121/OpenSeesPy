"""The reconstructed nGen steel-factory example must open and solve DL.

MIDAS numeric comparison is gated on ``MIDAS_REFERENCE`` being filled from
an nGen result table - until then this only proves OpenFrame's own model
is in equilibrium under the DL case the example ships with.
"""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisStatus
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "validation" / "steel_factory_ngen.py"
_SPEC = importlib.util.spec_from_file_location("steel_factory_ngen", _EXAMPLE)
assert _SPEC is not None and _SPEC.loader is not None
_factory = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_factory)


def _page_from_ofsm() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.load_project_dict(json.loads(_factory.OFSM_PATH.read_text(encoding="utf-8")))
    return page


def test_steel_factory_ofsm_is_a_3d_project_with_ngen_load_cases() -> None:
    assert _factory.OFSM_PATH.is_file(), "python examples/validation/steel_factory_ngen.py 로 예제를 생성하세요"
    data = json.loads(_factory.OFSM_PATH.read_text(encoding="utf-8"))
    assert data["format"] == "openframe-canvas"
    assert data["ndm"] == 3
    case_ids = {case["id"] for case in data["load_cases"]}
    assert {"DL", "LL", "CLV", "CLH", "WL_0", "WL_90"} <= case_ids
    assert data["active_load_case_id"] == "DL"
    assert data["nodes"] and data["elements"]


def test_steel_factory_dl_reactions_match_applied_gravity() -> None:
    page = _page_from_ofsm()
    result = _factory.solve_active_case(page)

    assert result.status is AnalysisStatus.COMPLETED
    expected = _factory.expected_dl_downward_kn(page)
    rz = _factory.vertical_reaction_sum(result)
    assert expected > 100.0
    assert rz == pytest.approx(expected, rel=0.02)
    _tag, mag, disp = _factory.max_abs_displacement(result)
    assert disp[2] < 0.0
    # 24 m portal under roof DL + self-weight should sag centimetres, not metres.
    assert mag < 0.15


@pytest.mark.skipif(
    not _factory.MIDAS_REFERENCE.get("DL_disp_m"), reason="nGen 변위 표가 아직 없음"
)
def test_steel_factory_dl_matches_midas_within_tolerance() -> None:
    page = _page_from_ofsm()
    result = _factory.solve_active_case(page)
    lines = _factory.compare_with_midas(result)
    assert all("FAIL" not in line for line in lines)
    assert _factory.ACCEPTABLE_DISP_REL_ERROR == 0.05
