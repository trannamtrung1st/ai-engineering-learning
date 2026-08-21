"""Detect imports of other test_* modules (Slice 9 isolation ratchet)."""

from __future__ import annotations

import ast


def sibling_test_import_modules(source: str) -> frozenset[str]:
    """Return imported modules whose basename starts with ``test_``."""

    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_test_module_name(alias.name):
                    found.add(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if _is_test_module_name(module):
            found.add(module)
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            qualified = f"{module}.{alias.name}" if module else alias.name
            if _is_test_module_name(alias.name) or _is_test_module_name(qualified):
                found.add(qualified)
    return frozenset(found)


def _is_test_module_name(name: str) -> bool:
    return any(part.startswith("test_") for part in name.split(".") if part)
