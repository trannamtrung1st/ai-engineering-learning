"""Per-run path containment for the file-backed run store."""

from __future__ import annotations

from pathlib import Path

from core_tools.persistence import PersistenceError

_RUN_SCOPED_SYMLINK_CHILDREN = frozenset(
    {"run.json", "reviews", "artifacts", "capabilities", "events.jsonl"}
)


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
    """Resolve ``path`` and require it to remain under ``root``."""

    resolved = path.resolve()
    store_root = root.resolve()
    if resolved == store_root:
        return resolved
    if not resolved.is_relative_to(store_root):
        raise PersistenceError(f"path escapes run store root: {path}")
    return resolved


def assert_run_contained(run_dir: Path, path: Path) -> Path:
    """Resolve ``path`` and require it to remain under the exact run directory."""

    run_resolved = run_dir.resolve()
    resolved = path.resolve()
    if resolved == run_resolved:
        return resolved
    if not resolved.is_relative_to(run_resolved):
        raise PersistenceError(f"path escapes run directory: {path}")
    return resolved


def require_non_symlink_run_boundary(run_dir: Path) -> None:
    """Reject symlinked run directories and run-scoped children that escape the run."""

    if run_dir.is_symlink():
        raise PersistenceError("run directory must not be a symlink")
    for child_name in _RUN_SCOPED_SYMLINK_CHILDREN:
        child = run_dir / child_name
        if child.is_symlink():
            raise PersistenceError(f"run path {child_name} must not be a symlink")
