"""Subprocess-based OpenSeesPy source importer."""

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from openframe.core.domain import (
    FORCE_UNITS,
    LENGTH_UNITS,
    TIME_UNITS,
    BoundaryCondition,
    Element,
    GeometricTransform,
    LoadCaseKind,
    NodalLoad,
    Node,
    StructuralModel,
    UniformElementLoad,
)
from openframe.core.errors import ModelImportError
from openframe.features.model.importers.python_source import (
    inspect_python_source,
    read_python_source,
)


class OpenSeesModelImporter:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def load(self, source: Path) -> StructuralModel:
        source = source.resolve()
        inspection = inspect_python_source(source)
        if inspection.syntax_errors:
            raise ModelImportError("Python 구문 오류: " + "; ".join(inspection.syntax_errors))
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

        model_payload = payload["model"]
        self._apply_load_case_hints(source, model_payload)
        self._apply_unit_declaration(source, model_payload)
        self._apply_model_origin(source, model_payload)
        model = self._to_domain_model(model_payload)
        if not model.nodes or not model.elements:
            import_hint = (
                " 선택한 파일에서 OpenSeesPy import가 직접 확인되지 않아 "
                "같은 폴더의 보조 모듈까지 실행해 확인했습니다."
                if not inspection.imports_openseespy
                else ""
            )
            raise ModelImportError(
                "읽을 수 있는 OpenSees 절점과 요소가 생성되지 않았습니다." + import_hint
            )
        return model

    def _to_domain_model(self, payload: dict[str, Any]) -> StructuralModel:
        nodes = {
            int(item["tag"]): Node(
                tag=int(item["tag"]),
                x=float(item["x"]),
                y=float(item["y"]),
                z=float(item.get("z", 0.0)),
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
                transf_tag=self._optional_int(item.get("transf_tag")),
                integration_tag=self._optional_int(item.get("integration_tag")),
            )
            for item in payload.get("elements", [])
        }
        geometric_transforms = {
            int(item["tag"]): GeometricTransform(
                tag=int(item["tag"]),
                transform_type=str(item.get("transform_type", "Linear")),
                arguments=tuple(item.get("arguments", [])),
            )
            # Older payloads (saved before this field existed) simply have no
            # "geometric_transforms" key - .get(..., []) makes that identical
            # to an empty list instead of a KeyError, preserving backward
            # compatibility with everything already saved on disk.
            for item in payload.get("geometric_transforms", [])
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
                pattern_tag=self._optional_int(item.get("pattern_tag")),
                case_type=LoadCaseKind(str(item.get("case_type", "UNCLASSIFIED"))),
            )
            for item in payload.get("nodal_loads", [])
        ]
        element_loads = [
            UniformElementLoad(
                element_tag=int(item["element_tag"]),
                wx=float(item.get("wx", 0.0)),
                wy=float(item.get("wy", 0.0)),
                wz=float(item.get("wz", 0.0)),
                pattern_tag=self._optional_int(item.get("pattern_tag")),
                case_type=LoadCaseKind(str(item.get("case_type", "UNCLASSIFIED"))),
            )
            for item in payload.get("element_loads", [])
        ]
        return StructuralModel(
            ndm=int(payload.get("ndm", 2)),
            ndf=int(payload.get("ndf", 3)),
            nodes=nodes,
            elements=elements,
            boundaries=boundaries,
            nodal_loads=loads,
            element_loads=element_loads,
            metadata=dict(payload.get("metadata", {})),
            geometric_transforms=geometric_transforms,
        )

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return None if value is None else int(value)

    @staticmethod
    def _apply_load_case_hints(source: Path, payload: dict[str, Any]) -> None:
        """Apply an explicit ``OPENFRAME_LOAD_CASES`` mapping from user source."""
        hints: dict[int, LoadCaseKind] = {}
        try:
            source_text = read_python_source(source)
            tree = ast.parse(source_text, filename=str(source))
        except (OSError, UnicodeDecodeError, SyntaxError):
            return
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "OPENFRAME_LOAD_CASES"
                for target in targets
            ):
                continue
            try:
                raw_mapping = ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError):
                continue
            if not isinstance(raw_mapping, dict):
                continue
            for raw_tag, raw_kind in raw_mapping.items():
                try:
                    hints[int(raw_tag)] = OpenSeesModelImporter._normalize_load_case(raw_kind)
                except (TypeError, ValueError):
                    continue

        for collection_name in ("nodal_loads", "element_loads"):
            for load in payload.get(collection_name, []):
                pattern_tag = load.get("pattern_tag")
                hint = hints.get(int(pattern_tag)) if pattern_tag is not None else None
                load["case_type"] = (hint or LoadCaseKind.UNCLASSIFIED).value
        if hints:
            payload.setdefault("metadata", {})["load_case_hints"] = ", ".join(
                f"{tag}:{kind.value}" for tag, kind in sorted(hints.items())
            )

    @staticmethod
    def _normalize_load_case(value: object) -> LoadCaseKind:
        normalized = str(value).strip().upper().replace(" ", "_")
        aliases = {
            "DL": LoadCaseKind.DEAD,
            "DEAD_LOAD": LoadCaseKind.DEAD,
            "고정하중": LoadCaseKind.DEAD,
            "LL": LoadCaseKind.LIVE,
            "LIVE_LOAD": LoadCaseKind.LIVE,
            "활하중": LoadCaseKind.LIVE,
            "EQ": LoadCaseKind.SEISMIC,
            "EARTHQUAKE": LoadCaseKind.SEISMIC,
            "지진하중": LoadCaseKind.SEISMIC,
            "WL": LoadCaseKind.WIND,
            "WIND_LOAD": LoadCaseKind.WIND,
            "풍하중": LoadCaseKind.WIND,
        }
        if normalized in aliases:
            return aliases[normalized]
        return LoadCaseKind(normalized)

    @staticmethod
    def _apply_model_origin(source: Path, payload: dict[str, Any]) -> None:
        """Read a literal ``OPENFRAME_MODEL_ORIGIN = "direct"`` declaration.

        Distinguishes a script generated by this project's own canvas export
        (``opensees_script_export.py``, which writes this declaration) from an
        ordinary hand-authored/third-party import - used only to pick the
        nonlinear GEOMETRIC TRANSFORMATION default in Setup (Direct Modeling
        defaults to an explicit type; Import defaults to "Use model
        definition"). Absence of the declaration - the overwhelmingly common
        case, any script not produced by this project's own exporter - is
        always treated as an import, never guessed at from model shape.
        """
        try:
            source_text = read_python_source(source)
            tree = ast.parse(source_text, filename=str(source))
        except (OSError, UnicodeDecodeError, SyntaxError):
            payload.setdefault("metadata", {})["model_origin"] = "import"
            return

        origin = "import"
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "OPENFRAME_MODEL_ORIGIN"
                for target in targets
            ):
                continue
            try:
                declared = ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError):
                break
            if isinstance(declared, str) and declared.strip().lower() == "direct":
                origin = "direct"
            break

        payload.setdefault("metadata", {})["model_origin"] = origin

    @staticmethod
    def _apply_unit_declaration(source: Path, payload: dict[str, Any]) -> None:
        """Read a literal ``OPENFRAME_UNITS`` declaration without executing it.

        OpenSees intentionally has no built-in unit system, so dimensions cannot be
        inferred safely from coordinates or material values.  A literal declaration
        is the only unambiguous source of truth an imported script can provide.
        """
        try:
            source_text = read_python_source(source)
            tree = ast.parse(source_text, filename=str(source))
        except (OSError, UnicodeDecodeError, SyntaxError):
            return

        declaration: object | None = None
        found = False
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "OPENFRAME_UNITS"
                for target in targets
            ):
                continue
            found = True
            try:
                declaration = ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError) as error:
                raise ModelImportError(
                    "OPENFRAME_UNITS는 문자열 값으로 구성된 딕셔너리여야 합니다."
                ) from error
            break

        if not found:
            return
        if not isinstance(declaration, dict):
            raise ModelImportError("OPENFRAME_UNITS는 딕셔너리여야 합니다.")

        missing = {"force", "length"} - {str(key).strip().lower() for key in declaration}
        if missing:
            raise ModelImportError(
                "OPENFRAME_UNITS에 force와 length가 모두 필요합니다: "
                + ", ".join(sorted(missing))
            )

        normalized_keys = {str(key).strip().lower(): value for key, value in declaration.items()}
        force = OpenSeesModelImporter._normalize_declared_unit(
            normalized_keys["force"], FORCE_UNITS, {"kips": "kip"}, "force"
        )
        length = OpenSeesModelImporter._normalize_declared_unit(
            normalized_keys["length"],
            LENGTH_UNITS,
            {"inch": "in", "inches": "in", "feet": "ft", "foot": "ft"},
            "length",
        )
        time = OpenSeesModelImporter._normalize_declared_unit(
            normalized_keys.get("time", "s"),
            TIME_UNITS,
            {"sec": "s", "second": "s", "seconds": "s"},
            "time",
        )
        metadata = payload.setdefault("metadata", {})
        metadata.update(
            {
                "unit_force": force,
                "unit_length": length,
                "unit_time": time,
                "unit_source": "OPENFRAME_UNITS",
            }
        )

    @staticmethod
    def _normalize_declared_unit(
        value: object,
        supported: tuple[str, ...],
        aliases: dict[str, str],
        dimension: str,
    ) -> str:
        raw = str(value).strip()
        canonical_by_lower = {unit.lower(): unit for unit in supported}
        normalized = aliases.get(raw.lower(), canonical_by_lower.get(raw.lower()))
        if normalized is None:
            choices = ", ".join(supported)
            raise ModelImportError(
                f"지원하지 않는 OPENFRAME_UNITS {dimension} 단위입니다: {raw!r}. "
                f"지원 단위: {choices}"
            )
        return normalized
