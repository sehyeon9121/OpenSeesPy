"""Safe preflight inspection for uploaded Python source files.

This module does not execute source code. Actual model collection belongs to the
OpenSees worker process under infrastructure/opensees.
"""

import ast
import tokenize
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceInspection:
    path: Path
    imports_openseespy: bool
    syntax_errors: tuple[str, ...] = ()


def inspect_python_source(path: Path) -> SourceInspection:
    source = read_python_source(path)
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


def read_python_source(path: Path) -> str:
    """Read UTF, encoding-cookie, and common legacy Korean Python sources."""
    try:
        with tokenize.open(path) as source_file:
            return source_file.read()
    except (SyntaxError, UnicodeDecodeError):
        raw_source = path.read_bytes()
        for encoding in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                return raw_source.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise
