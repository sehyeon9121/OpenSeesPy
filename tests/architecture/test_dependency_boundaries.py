"""Protect the feature-first package boundaries from accidental coupling."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "openframe"


def test_core_does_not_depend_on_gui_engine_or_features() -> None:
    forbidden_prefixes = (
        "PySide6",
        "openseespy",
        "openframe.app",
        "openframe.features",
        "openframe.infrastructure",
    )
    violations: list[str] = []

    for path in (SOURCE_ROOT / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_names: list[str] = []
            if isinstance(node, ast.Import):
                imported_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names = [node.module]

            for imported_name in imported_names:
                if imported_name.startswith(forbidden_prefixes):
                    relative_path = path.relative_to(SOURCE_ROOT)
                    violations.append(f"{relative_path}: {imported_name}")

    assert violations == []


def _forbidden_imports(package: str, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    root = SOURCE_ROOT / package
    if not root.exists():
        return [f"missing package {package}"]
    paths = [root] if root.is_file() else list(root.rglob("*.py"))
    for path in paths:
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_names: list[str] = []
            if isinstance(node, ast.Import):
                imported_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names = [node.module]
            for imported_name in imported_names:
                if imported_name.startswith(forbidden_prefixes):
                    relative_path = path.relative_to(SOURCE_ROOT)
                    violations.append(f"{relative_path}: {imported_name}")
    return violations


def test_model_surfaces_do_not_import_gui_or_opensees() -> None:
    assert _forbidden_imports("features/model/surfaces", ("PySide6", "openseespy")) == []


def test_analysis_surface_commands_do_not_import_gui() -> None:
    """``statics/surfaces.py`` talks to OpenSees; the GUI must not come along."""
    assert _forbidden_imports("features/analysis/statics/surfaces.py", ("PySide6",)) == []


def test_removed_layer_first_packages_do_not_return() -> None:
    obsolete_packages = (
        "analysis",
        "application",
        "diagrams",
        "domain",
        "importers",
        "ui",
        "visualization",
    )

    assert [name for name in obsolete_packages if (SOURCE_ROOT / name).exists()] == []

