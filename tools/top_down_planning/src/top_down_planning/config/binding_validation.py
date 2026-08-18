"""Context snapshot binding validation (proposal §9)."""

from __future__ import annotations

import posixpath
import re
from typing import Any

from core_tools.persistence import PersistenceError

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LEGACY_BINDING_MESSAGE = (
    "Unsupported context snapshot binding shape. "
    "Recreate the run using the current TDP version."
)
LEGACY_SNAPSHOT_BINDING_MESSAGE = _LEGACY_BINDING_MESSAGE


class InvalidSnapshotBindingError(PersistenceError):
    """Persisted context_snapshot_binding is not the supported compact map shape."""


def _require_relative_binding_path(path: object, *, field: str) -> str:
    if not isinstance(path, str) or not path:
        raise InvalidSnapshotBindingError(
            f"{field} path must be a non-empty canonical relative string"
        )
    if path.startswith("/") or path.startswith("\\") or "\\" in path:
        raise InvalidSnapshotBindingError(
            f"{field} rejects absolute or non-POSIX binding path: {path!r}"
        )
    if re.match(r"^[A-Za-z]:(?:/|\\|$)", path):
        raise InvalidSnapshotBindingError(
            f"{field} rejects non-canonical binding path: {path!r}"
        )
    normalized = posixpath.normpath(path)
    if (
        normalized != path
        or normalized in {".", ".."}
        or normalized.startswith("../")
        or "/../" in normalized
    ):
        raise InvalidSnapshotBindingError(
            f"{field} rejects non-canonical binding path: {path!r}"
        )
    return path


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise InvalidSnapshotBindingError(
            f"{field} digest must be a 64-char lowercase SHA-256 hex string"
        )
    return value


def _validate_digest_map(value: object, *, field: str) -> None:
    if isinstance(value, list):
        raise InvalidSnapshotBindingError(_LEGACY_BINDING_MESSAGE)
    if not isinstance(value, dict):
        raise InvalidSnapshotBindingError(
            f"{field} must be a compact map of path to digest"
        )
    for raw_path, raw_digest in value.items():
        path = _require_relative_binding_path(raw_path, field=field)
        _require_digest(raw_digest, field=f"{field}[{path}]")


def validate_context_snapshot_binding(binding: object) -> dict[str, Any]:
    """Validate compact-map snapshot binding; reject legacy list/absolute shapes."""

    if not isinstance(binding, dict):
        raise InvalidSnapshotBindingError(
            "context_snapshot_binding must be a mapping"
        )
    if "workspace" in binding:
        raise InvalidSnapshotBindingError(_LEGACY_BINDING_MESSAGE)

    if "resource_digests" not in binding or "skill_digests" not in binding:
        raise InvalidSnapshotBindingError(
            "context_snapshot_binding requires resource_digests and skill_digests"
        )

    _validate_digest_map(binding.get("resource_digests"), field="resource_digests")
    _validate_digest_map(binding.get("skill_digests"), field="skill_digests")

    guidance = binding.get("guidance_digests")
    if guidance is None:
        raise InvalidSnapshotBindingError(
            "context_snapshot_binding requires guidance_digests"
        )
    if not isinstance(guidance, list):
        raise InvalidSnapshotBindingError(
            "guidance_digests must be an ordered list"
        )
    for index, entry in enumerate(guidance):
        field = f"guidance_digests[{index}]"
        if not isinstance(entry, dict):
            raise InvalidSnapshotBindingError(f"{field} must be an object")
        if "digest" not in entry:
            raise InvalidSnapshotBindingError(f"{field} requires digest")
        _require_digest(entry.get("digest"), field=field)
        if "path" in entry:
            _require_relative_binding_path(entry.get("path"), field=field)
        elif "text" not in entry:
            raise InvalidSnapshotBindingError(
                f"{field} requires text when path is omitted"
            )

    return binding


__all__ = [
    "InvalidSnapshotBindingError",
    "LEGACY_SNAPSHOT_BINDING_MESSAGE",
    "validate_context_snapshot_binding",
]
