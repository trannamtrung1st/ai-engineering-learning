"""Safe Git operations: dirty-tree checks, explicit staging, commits."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from todos_tool.errors import GitError


@dataclass
class GitStatus:
    porcelain: str
    changed_paths: list[str]
    is_dirty: bool


def _run(
    root: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def ensure_git_repo(root: Path) -> None:
    result = _run(root, ["rev-parse", "--is-inside-work-tree"], check=False)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise GitError(f"Not a git repository: {root}")


def head_sha(root: Path) -> str:
    result = _run(root, ["rev-parse", "HEAD"])
    return result.stdout.strip()


def status(root: Path) -> GitStatus:
    result = _run(root, ["status", "--porcelain"])
    porcelain = result.stdout
    paths: list[str] = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        # Format: XY PATH or XY ORIG -> PATH
        entry = line[3:]
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry.strip())
    return GitStatus(
        porcelain=porcelain,
        changed_paths=paths,
        is_dirty=bool(paths),
    )


def is_todos_metadata_path(path: str, todos_dir: str = "todos") -> bool:
    """Return True for local todos workspace paths (items, runs, manifest)."""
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized == todos_dir or normalized.startswith(f"{todos_dir}/")


def refuse_if_dirty(
    root: Path,
    *,
    allow_dirty: bool,
    todos_dir: str = "todos",
) -> GitStatus:
    st = status(root)
    if not st.is_dirty or allow_dirty:
        return st
    unrelated = [p for p in st.changed_paths if not is_todos_metadata_path(p, todos_dir)]
    if unrelated:
        raise GitError(
            "Working tree has uncommitted changes unrelated to todos metadata. "
            "Commit/stash them or pass --allow-dirty.\n"
            + "\n".join(unrelated)
        )
    return st


def diff_summary(root: Path, *, staged: bool = False) -> str:
    args = ["diff", "--stat"]
    if staged:
        args.append("--cached")
    result = _run(root, args, check=False)
    return result.stdout.strip()


def diff_names(root: Path, baseline: str | None = None) -> list[str]:
    """Paths changed vs baseline (or vs HEAD working tree)."""
    if baseline:
        result = _run(
            root,
            ["diff", "--name-only", baseline],
            check=False,
        )
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        # Also include untracked
        untracked = _run(
            root,
            ["ls-files", "--others", "--exclude-standard"],
            check=False,
        )
        for line in untracked.stdout.splitlines():
            path = line.strip()
            if path and path not in names:
                names.append(path)
        return names
    st = status(root)
    return st.changed_paths


def diff_text(root: Path, *, max_chars: int = 12_000) -> str:
    result = _run(root, ["diff", "HEAD"], check=False)
    untracked_list = _run(
        root,
        ["ls-files", "--others", "--exclude-standard"],
        check=False,
    )
    text = result.stdout
    if untracked_list.stdout.strip():
        text += "\n# Untracked files:\n" + untracked_list.stdout
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... truncated ({len(text)} chars total)"
    return text


def paths_changed_since(root: Path, baseline: str, pre_existing: set[str]) -> list[str]:
    """Return paths changed since baseline excluding pre-existing dirty paths."""
    names = diff_names(root, baseline=baseline)
    return [p for p in names if p not in pre_existing]


def stage_paths(root: Path, paths: list[str]) -> None:
    if not paths:
        raise GitError("No paths to stage")
    # Explicit paths only — never git add -A / .
    _run(root, ["add", "--", *paths])


def commit(root: Path, message: str) -> str:
    _run(root, ["commit", "-m", message])
    return head_sha(root)


def staged_diff_stat(root: Path) -> str:
    return diff_summary(root, staged=True)


def has_staged_changes(root: Path) -> bool:
    result = _run(root, ["diff", "--cached", "--name-only"], check=False)
    return bool(result.stdout.strip())
