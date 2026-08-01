"""§17: no dormant legacy snapshot compatibility helpers in package source."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from top_down_planning.config import InvalidSnapshotBindingError, validate_context_snapshot_binding

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "top_down_planning"

# Symbols / phrases that would indicate kept compatibility conversion paths.
# Rejection messages that explicitly say "not supported" / "recreate" are allowed.
_FORBIDDEN = (
    re.compile(r"\bmigrate[_ ].*binding\b", re.I),
    re.compile(r"\bnormalize[_ ].*legacy\b", re.I),
    re.compile(r"\blegacy[_ ].*to[_ ].*compact\b", re.I),
    re.compile(r"\bconvert[_ ].*absolute[_ ].*binding\b", re.I),
    re.compile(r"\bignore_globs\b"),
    re.compile(r"sha256:[0-9a-f]{8}"),  # prefixed digest values in source
)

_ALLOWED_REJECTION_MARKERS = (
    "Unsupported context snapshot binding shape",
    "rejects absolute binding path",
    "Unsupported context snapshot binding",
    "Recreate the run",
)


def _iter_source_files() -> list[Path]:
    return sorted(
        path
        for path in _SRC_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_no_legacy_snapshot_compatibility_helpers() -> None:
    violations: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                line = text.splitlines()[line_no - 1].strip()
                if any(marker in line for marker in _ALLOWED_REJECTION_MARKERS):
                    continue
                # Skip comments that only document rejection.
                if line.startswith("#") and (
                    "reject" in line.lower() or "recreate" in line.lower()
                ):
                    continue
                violations.append(f"{path.relative_to(_SRC_ROOT)}:{line_no}: {line}")

    assert not violations, "legacy compatibility remnants:\n" + "\n".join(violations)


def test_binding_validation_rejects_without_rewriting() -> None:
    legacy = {
        "workspace": "/tmp/ws",
        "resource_digests": [{"path": "/tmp/ws/a.py", "digest": "a" * 64}],
        "skill_digests": [],
    }
    with pytest.raises(InvalidSnapshotBindingError):
        validate_context_snapshot_binding(legacy)
    assert isinstance(legacy["resource_digests"], list)
    assert legacy["workspace"] == "/tmp/ws"


def test_readme_and_example_cover_context_snapshot_excludes() -> None:
    package_root = _SRC_ROOT.parents[1]
    readme = (package_root / "README.md").read_text(encoding="utf-8")
    example = (package_root / "examples" / "top-down-planning.yaml").read_text(
        encoding="utf-8"
    )
    assert "context_snapshot:" in readme
    assert "defaults: true" in readme
    assert "schema_version" in readme
    assert "gitignore" in readme.lower()
    assert "not inherit" in readme.lower() or "does **not** inherit" in readme.lower()
    assert "context_snapshot:" in example
    assert "defaults: true" in example

    from top_down_planning.schema_docs import AGENT_README_TEXT, show_schema

    assert "context_snapshot" in AGENT_README_TEXT
    assert "schema_version" in AGENT_README_TEXT
    config_schema = show_schema("config")
    assert "context_snapshot" in config_schema["properties"]
