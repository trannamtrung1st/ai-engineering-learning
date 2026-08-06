"""Import-boundary checks for the layered package layout."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_DOMAIN_IMPORT_ROOTS = frozenset(
    {
        "top_down_planning.cli",
        "top_down_planning.config",
        "top_down_planning.persistence",
        "top_down_planning.orchestrator",
        "core_tools",
    }
)


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "top_down_planning"


def _domain_python_files() -> list[Path]:
    domain_dir = _package_root() / "domain"
    return sorted(domain_dir.rglob("*.py"))


def _imported_roots(module: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            roots.add(node.module)
            if node.level and node.level > 0:
                continue
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_domain_does_not_import_outer_layers() -> None:
    violations: list[str] = []

    for path in _domain_python_files():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in sorted(_imported_roots(module)):
            if imported == "top_down_planning":
                continue
            for forbidden in FORBIDDEN_DOMAIN_IMPORT_ROOTS:
                if imported == forbidden or imported.startswith(f"{forbidden}."):
                    violations.append(f"{path.relative_to(_package_root())}: {imported}")

    assert not violations, "domain layer import violations:\n" + "\n".join(violations)
