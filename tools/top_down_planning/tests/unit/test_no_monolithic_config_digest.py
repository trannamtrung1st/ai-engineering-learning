"""Guard against monolithic digests.config in production code (proposal §6.1)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "top_down_planning"

# Allowed: explicit rejection of digests.config (schema validation).
_ALLOWED_LINE_MARKERS = (
    "digests.config is not supported",
    '"config" not in run["digests"]',
    'payload["digests"]["config"]',
    "monolithic `digests.config`",
    "monolithic digests.config",
)

_FORBIDDEN_PATTERNS = (
    re.compile(r'digests\.get\(\s*["\']config["\']\s*\)'),
    re.compile(r'digests\[\s*["\']config["\']\s*\]'),
    re.compile(r'["\']config["\']\s*:\s*.*digest'),
    re.compile(r'run_digests\.get\(\s*["\']config["\']'),
)


def _iter_production_files() -> list[Path]:
    return sorted(
        path
        for path in _SRC_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts and "tests" not in path.parts
    )


def test_production_code_does_not_read_or_write_digests_config() -> None:
    violations: list[str] = []
    for path in _iter_production_files():
        text = path.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                line = text.splitlines()[line_no - 1].strip()
                if any(marker in line for marker in _ALLOWED_LINE_MARKERS):
                    continue
                if "not supported" in line or "not accepted" in line:
                    continue
                rel = path.relative_to(_SRC_ROOT.parent.parent)
                violations.append(f"{rel}:{line_no}: {line}")
    assert not violations, "digests.config usage in production code:\n" + "\n".join(violations)
