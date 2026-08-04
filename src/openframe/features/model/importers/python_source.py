"""Safe preflight inspection for uploaded Python source files.

This module does not execute source code. Actual model collection belongs to the
OpenSees worker process under infrastructure/opensees.
"""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceInspection:
    path: Path
    imports_openseespy: bool
    syntax_errors: tuple[str, ...] = ()


def inspect_python_source(path: Path) -> SourceInspection:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        location = f"{error.lineno}:{error.offset}" if error.lineno else "unknown"
        return SourceInspection(path, False, (f"{location} {error.msg}",))

    imports_openseespy = any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            any(alias.name.startswith("openseespy") for alias in node.names)
            if isinstance(node, ast.Import)
            else (node.module or "").startswith("openseespy")
        )
        for node in ast.walk(tree)
    )
    return SourceInspection(path, imports_openseespy)

