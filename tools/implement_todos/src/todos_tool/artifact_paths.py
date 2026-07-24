"""Extract on-disk artifact paths from implementer work summaries."""

from __future__ import annotations

import re
from pathlib import Path

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
_ARTIFACT_MARKERS = (
    ".playwright-mcp/",
    "playwright-mcp/",
    "generated/runs/screenshots/",
    "generated/runs/playwright-mcp/",
    "generated/runs/evidence/",
)

_PATH_RE = re.compile(
    r"(?<![\w./-])"
    r"((?:\.playwright-mcp/|(?:[\w.-]+/)+)?"
    r"[\w./-]+\.(?:png|jpe?g|webp|gif|svg))"
    r"(?![\w./-])",
    re.IGNORECASE,
)
_BACKTICK_PATH_RE = re.compile(r"`([^`\n]+)`")


def _looks_like_artifact_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    suffix = Path(lowered).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return True
    return any(marker in lowered for marker in _ARTIFACT_MARKERS)


def extract_artifact_paths(text: str | None) -> list[str]:
    """Return deduplicated artifact paths mentioned in free-form text."""
    if not text or not text.strip():
        return []

    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        candidate = raw.strip().strip("'\"")
        candidate = candidate.replace("\\", "/")
        if not candidate or not _looks_like_artifact_path(candidate):
            return
        key = candidate.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(candidate)

    for match in _PATH_RE.finditer(text):
        add(match.group(1))

    for match in _BACKTICK_PATH_RE.finditer(text):
        add(match.group(1))

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        candidate = stripped.lstrip("-*").strip()
        if "/" in candidate or candidate.startswith("."):
            add(candidate)

    return found
