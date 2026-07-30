"""Import-boundary checks for core_tools."""

from __future__ import annotations

import ast
from pathlib import Path


def _source_roots() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return [root / "src" / "core_tools", root / "tests"]


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in _source_roots():
        files.extend(sorted(root.rglob("*.py")))
    return files


def _imported_modules(module: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_core_tools_does_not_import_top_down_planning() -> None:
    violations: list[str] = []

    for path in _python_files():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in sorted(_imported_modules(module)):
            if imported == "top_down_planning" or imported.startswith("top_down_planning."):
                violations.append(f"{path.name}: {imported}")

    assert not violations, "core_tools import violations:\n" + "\n".join(violations)


def test_core_tools_imports_without_top_down_planning() -> None:
    import core_tools  # noqa: F401
    import core_tools.config  # noqa: F401
    import core_tools.persistence  # noqa: F401
    import core_tools.provider  # noqa: F401

    assert core_tools.__version__ == "0.1.0"
