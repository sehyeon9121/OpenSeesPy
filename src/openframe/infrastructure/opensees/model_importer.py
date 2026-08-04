"""Subprocess-based OpenSeesPy source importer."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
)
from openframe.core.errors import ModelImportError
from openframe.features.model.importers.python_source import inspect_python_source


class OpenSeesModelImporter:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def load(self, source: Path) -> StructuralModel:
        source = source.resolve()
        inspection = inspect_python_source(source)
        if inspection.syntax_errors:
            raise ModelImportError("Python 구문 오류: " + "; ".join(inspection.syntax_errors))
        if not inspection.imports_openseespy:
            raise ModelImportError("OpenSeesPy를 불러오는 코드가 확인되지 않았습니다.")

        with tempfile.TemporaryDirectory(prefix="openframe-model-") as temporary_directory:
            output = Path(temporary_directory) / "model.json"
            command = [
                sys.executable,
                "-m",
                "openframe.infrastructure.opensees.worker",
                "--source",
                str(source),
                "--output",
                str(output),
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
            except subprocess.TimeoutExpired as error:
                raise ModelImportError(
                    f"모델 실행이 {self._timeout_seconds:g}초 제한을 초과했습니다."
                ) from error

            if not output.exists():
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise ModelImportError(f"모델 worker가 결과를 만들지 못했습니다. {detail}")

            payload = json.loads(output.read_text(encoding="utf-8"))
            if not payload.get("ok"):
                raise ModelImportError(str(payload.get("error", "알 수 없는 모델 실행 오류")))

        return self._to_domain_model(payload["model"])

    def _to_domain_model(self, payload: dict[str, Any]) -> StructuralModel:
        nodes = {
            int(item["tag"]): Node(
                tag=int(item["tag"]),
                x=float(item["x"]),
                y=float(item["y"]),
                ndf=int(item.get("ndf", payload.get("ndf", 3))),
            )
            for item in payload.get("nodes", [])
        }
        elements = {
            int(item["tag"]): Element(
                tag=int(item["tag"]),
                node_i=int(item["node_i"]),
                node_j=int(item["node_j"]),
                element_type=str(item.get("element_type", "unknown")),
                properties=dict(item.get("properties", {})),
            )
            for item in payload.get("elements", [])
        }
        boundaries = [
            BoundaryCondition(
                node_tag=int(item["node_tag"]),
                restraints=tuple(bool(value) for value in item.get("restraints", [])),
            )
            for item in payload.get("boundaries", [])
        ]
        loads = [
            NodalLoad(
                node_tag=int(item["node_tag"]),
                values=tuple(float(value) for value in item.get("values", [])),
            )
            for item in payload.get("nodal_loads", [])
        ]
        return StructuralModel(
            ndm=int(payload.get("ndm", 2)),
            ndf=int(payload.get("ndf", 3)),
            nodes=nodes,
            elements=elements,
            boundaries=boundaries,
            nodal_loads=loads,
            metadata=dict(payload.get("metadata", {})),
        )

