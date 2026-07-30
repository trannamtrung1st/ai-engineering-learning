"""Import-boundary checks for top_down_planning orchestrators."""

from __future__ import annotations

import ast
from pathlib import Path


def _orchestrator_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "src" / "top_down_planning" / "orchestrator"
    return sorted(root.rglob("*.py"))


def _imported_modules(module: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_orchestrators_do_not_import_presentation_layers() -> None:
    forbidden = ("rich", "core_tools.observability.console")
    violations: list[str] = []

    for path in _orchestrator_files():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in sorted(_imported_modules(module)):
            if imported in forbidden or imported.startswith("rich."):
                violations.append(f"{path.name}: {imported}")

    assert not violations, "orchestrator import violations:\n" + "\n".join(violations)
