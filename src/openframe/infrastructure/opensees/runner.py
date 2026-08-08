"""GUI-side controller for the isolated OpenSees worker process."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from openframe.core.domain import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisStatus,
    ElementResult,
    LoadDisplacementPoint,
    NodeResult,
)


def _uniform_load(values: Any) -> tuple[float, float, float, float]:
    """Real OpenSeesPy analyses only ever carry a plain constant (wx, wy) -
    OpenSees itself has no linearly-varying eleLoad type - so the pair is
    duplicated into the (wx_i, wy_i, wx_j, wy_j) shape ``ElementResult``
    expects, with i == j."""
    padded = (*values, 0.0, 0.0)
    wx, wy = float(padded[0]), float(padded[1])
    return wx, wy, wx, wy


class OpenSeesProcessRunner:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        source = request.source_path.resolve()

        with tempfile.TemporaryDirectory(prefix="openframe-analysis-") as temporary_directory:
            output = Path(temporary_directory) / "results.json"
            command = [
                sys.executable,
                "-m",
                "openframe.infrastructure.opensees.worker",
                "--source",
                str(source),
                "--output",
                str(output),
                "--mode",
                "analysis",
                "--kind",
                str(request.kind),
                "--options",
                json.dumps(request.options),
            ]
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                completed = subprocess.run(
                    command,
                    cwd=source.parent,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self._timeout_seconds,
                    creationflags=creation_flags,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[f"해석이 {self._timeout_seconds:g}초 제한을 초과했습니다."],
                )

            if not output.exists():
                detail = completed.stderr.strip() or completed.stdout.strip()
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[f"해석 worker가 결과를 만들지 못했습니다. {detail}"],
                )

            payload = json.loads(output.read_text(encoding="utf-8"))

        if not payload.get("ok"):
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[str(payload.get("error", "알 수 없는 해석 오류"))],
            )

        return self._to_domain_result(payload["results"])

    def _to_domain_result(self, payload: dict[str, Any]) -> AnalysisResult:
        node_results = {
            int(item["node_tag"]): NodeResult(
                node_tag=int(item["node_tag"]),
                displacement=tuple(float(value) for value in item.get("displacement", [])),
                reaction=tuple(float(value) for value in item.get("reaction", [])),
            )
            for item in payload.get("node_results", [])
        }
        element_results = {
            int(item["element_tag"]): ElementResult(
                element_tag=int(item["element_tag"]),
                local_forces=tuple(float(value) for value in item.get("local_forces", [])),
                length=float(item.get("length", 0.0)),
                uniform_load=_uniform_load(item.get("uniform_load", ())),
                flexural_rigidity=float(item.get("flexural_rigidity", 0.0)),
            )
            for item in payload.get("element_results", [])
        }
        curve = tuple(
            LoadDisplacementPoint(
                step=int(item["step"]),
                control_displacement=float(item["control_displacement"]),
                base_shear=float(item["base_shear"]),
            )
            for item in payload.get("load_displacement_curve", [])
        )
        return AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            node_results=node_results,
            element_results=element_results,
            messages=[str(message) for message in payload.get("messages", [])],
            load_displacement_curve=curve,
        )
