"""Per-run path containment for the file-backed run store."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core_tools.persistence import PersistenceError

_RUN_SCOPED_SYMLINK_CHILDREN = frozenset(
    {
        "run.json",
        "plan.json",
        "production.json",
        "resolved-config.yaml",
        "invocation.json",
        "reviews",
        "artifacts",
        "capabilities",
        "capability",
        "agent-requests",
        "events.jsonl",
    }
)


def lexical_run_dir(root: Path, run_id: str) -> Path:
    """Return the lexical run directory after store-root and symlink checks."""

    lexical = root / run_id
    if lexical.is_symlink():
        raise PersistenceError("run directory must not be a symlink")
    assert_store_root_contained(root, lexical)
    return lexical


def validate_journal_basename(name: str, *, label: str = "name") -> str:
    """Validate a single-segment journal file or backup name."""

    if not isinstance(name, str) or not name.strip():
        raise PersistenceError(f"transaction journal {label} must be a non-empty string")
    if name != name.strip():
        raise PersistenceError(f"transaction journal {label} must not contain whitespace")
    if "/" in name or "\\" in name or ".." in name:
        raise PersistenceError(f"transaction journal {label} must be a safe basename")
    if Path(name).name != name:
        raise PersistenceError(f"transaction journal {label} must be a safe basename")
    return name


def assert_store_root_contained(root: Path, path: Path) -> Path:
    """Validate ``path`` resolves under ``root`` and return the lexical path."""

    resolved = path.resolve()
    store_root = root.resolve()
    if resolved != store_root and not resolved.is_relative_to(store_root):
        raise PersistenceError(f"path escapes run store root: {path}")
    return path


def assert_run_contained(run_dir: Path, path: Path) -> Path:
    """Validate ``path`` resolves under ``run_dir`` and return the lexical path."""

    run_resolved = run_dir.resolve()
    resolved = path.resolve()
    if resolved != run_resolved and not resolved.is_relative_to(run_resolved):
        raise PersistenceError(f"path escapes run directory: {path}")
    return path


def reject_symlink_path(path: Path, *, label: str) -> None:
    """Reject a store-owned path that is itself a symlink."""

    if path.is_symlink():
        raise PersistenceError(f"{label} must not be a symlink")


def reject_symlink_components_between(base: Path, path: Path) -> None:
    """Reject when any component between ``base`` and ``path`` is a symlink."""

    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise PersistenceError(f"path escapes run directory: {path}") from exc
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PersistenceError(f"path component {part!r} must not be a symlink")


def lexical_run_owned_path(run_dir: Path, path: Path) -> Path:
    """Return a lexical run-owned path after containment and symlink checks."""

    reject_symlink_components_between(run_dir, path)
    assert_run_contained(run_dir, path)
    return path


def lexical_store_owned_path(root: Path, path: Path) -> Path:
    """Return a lexical store-owned path after containment and symlink checks."""

    lexical = assert_store_root_contained(root, path)
    reject_symlink_path(lexical, label=str(path.name or path))
    return lexical


def lexical_txn_owned_path(txn_dir: Path, path: Path) -> Path:
    """Return a lexical transaction-owned path after containment and symlink checks."""

    reject_symlink_components_between(txn_dir, path)
    txn_resolved = txn_dir.resolve()
    resolved = path.resolve()
    if resolved != txn_resolved and not resolved.is_relative_to(txn_resolved):
        raise PersistenceError(f"path escapes transaction directory: {path}")
    return path


def require_sha256_digest(value: Any, *, field_name: str) -> str:
    """Require a lowercase 64-character SHA-256 hex digest string."""

    if not isinstance(value, str) or not value.strip():
        raise PersistenceError(f"{field_name} must be a non-empty SHA-256 digest")
    digest = value.strip()
    if not re.fullmatch(r"^[a-f0-9]{64}$", digest):
        raise PersistenceError(f"{field_name} must be a 64-character lowercase hex digest")
    return digest


def require_non_symlink_run_boundary(run_dir: Path) -> None:
    """Reject symlinked run directories and run-scoped children that escape the run."""

    if run_dir.is_symlink():
        raise PersistenceError("run directory must not be a symlink")
    for child_name in _RUN_SCOPED_SYMLINK_CHILDREN:
        child = run_dir / child_name
        if child.is_symlink():
            raise PersistenceError(f"run path {child_name} must not be a symlink")
