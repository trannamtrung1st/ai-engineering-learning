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


def staged_paths(root: Path) -> list[str]:
    result = _run(root, ["diff", "--cached", "--name-only"], check=False)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def unrelated_staged_paths(
    root: Path,
    *,
    todos_dir: str = "todos",
    approved_paths: set[str] | None = None,
) -> list[str]:
    """Return staged paths outside approved/todos metadata."""
    unrelated: list[str] = []
    for path in staged_paths(root):
        if is_todos_metadata_path(path, todos_dir):
            continue
        if approved_paths is not None and path in approved_paths:
            continue
        unrelated.append(path)
    return unrelated


def refuse_unrelated_staged(
    root: Path,
    *,
    todos_dir: str = "todos",
    approved_paths: set[str] | None = None,
) -> None:
    """Refuse when unrelated content is already staged.

    ``--allow-dirty`` permits unrelated working-tree changes but never unrelated
    staged content that could leak into generated commits.
    """
    unrelated = unrelated_staged_paths(
        root,
        todos_dir=todos_dir,
        approved_paths=approved_paths,
    )
    if unrelated:
        raise GitError(
            "Working tree has unrelated staged changes. Unstage them before running.\n"
            + "\n".join(unrelated)
        )


def verify_staged_paths(
    root: Path,
    expected_paths: list[str],
    *,
    todos_dir: str = "todos",
) -> None:
    """Ensure approved paths are staged and no unrelated non-metadata paths are staged."""
    expected = set(expected_paths)
    actual = set(staged_paths(root))
    missing = sorted(expected - actual)
    extra = sorted(
        path
        for path in actual - expected
        if not is_todos_metadata_path(path, todos_dir)
    )
    if missing or extra:
        raise GitError(
            "Staged paths do not match approved commit set "
            f"(missing={missing}, unexpected={extra})"
        )


def _expand_path_prefixes(paths: set[str]) -> set[str]:
    expanded = set(paths)
    for path in paths:
        parts = Path(path.replace("\\", "/")).parts
        for idx in range(1, len(parts)):
            expanded.add(str(Path(*parts[:idx])))
    return expanded


def refuse_if_dirty_only_permitted(
    root: Path,
    *,
    allow_dirty: bool,
    todos_dir: str = "todos",
    permitted_paths: set[str],
) -> GitStatus:
    """Refuse when the working tree has non-metadata changes outside ``permitted_paths``."""
    refuse_unrelated_staged(
        root,
        todos_dir=todos_dir,
        approved_paths=permitted_paths,
    )
    st = status(root)
    if not st.is_dirty or allow_dirty:
        return st
    permitted = _expand_path_prefixes(permitted_paths)
    unrelated = [
        path
        for path in st.changed_paths
        if not is_todos_metadata_path(path, todos_dir)
        and path not in permitted
        and not any(
            path.startswith(f"{allowed}/") or allowed.startswith(f"{path}/")
            for allowed in permitted
        )
    ]
    if unrelated:
        raise GitError(
            "Working tree has uncommitted changes unrelated to todos metadata. "
            "Commit/stash them or pass --allow-dirty.\n"
            + "\n".join(unrelated)
        )
    return st


def refuse_if_dirty_except(
    root: Path,
    *,
    allow_dirty: bool,
    todos_dir: str = "todos",
    permitted_paths: set[str] | None = None,
) -> GitStatus:
    """Like ``refuse_if_dirty`` but allow specific working-tree paths."""
    permitted = _expand_path_prefixes(permitted_paths or set())
    refuse_unrelated_staged(
        root,
        todos_dir=todos_dir,
        approved_paths=permitted,
    )
    st = status(root)
    if not st.is_dirty or allow_dirty:
        return st
    unrelated = [
        path
        for path in st.changed_paths
        if not is_todos_metadata_path(path, todos_dir)
        and path not in permitted
        and not any(
            path.startswith(f"{allowed}/") or allowed.startswith(f"{path}/")
            for allowed in permitted
        )
    ]
    if unrelated:
        raise GitError(
            "Working tree has uncommitted changes unrelated to todos metadata. "
            "Commit/stash them or pass --allow-dirty.\n"
            + "\n".join(unrelated)
        )
    return st


def refuse_if_dirty(
    root: Path,
    *,
    allow_dirty: bool,
    todos_dir: str = "todos",
) -> GitStatus:
    refuse_unrelated_staged(root, todos_dir=todos_dir)
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


def diff_text(root: Path, *, max_chars: int = 12_000, paths: list[str] | None = None) -> str:
    if paths is not None:
        if not paths:
            return "(no diff)"
        result = _run(root, ["diff", "HEAD", "--", *paths], check=False)
        text = result.stdout
        untracked = [
            path
            for path in paths
            if _run(root, ["ls-files", "--error-unmatch", path], check=False).returncode
            != 0
            and Path(root / path).is_file()
        ]
        if untracked:
            text += "\n# Untracked files:\n" + "\n".join(untracked)
        if len(text) > max_chars:
            return text[:max_chars] + f"\n... truncated ({len(text)} chars total)"
        return text or "(no diff)"

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


def stage_paths(root: Path, paths: list[str], *, todos_dir: str = "todos") -> None:
    if not paths:
        raise GitError("No paths to stage")
    # Explicit paths only — never git add -A / .
    _run(root, ["add", "--", *paths])
    verify_staged_paths(root, paths, todos_dir=todos_dir)


def is_ignored_path(root: Path, path: str) -> bool:
    """Return True when git would ignore ``path`` (not stageable)."""
    result = _run(root, ["check-ignore", "-q", "--", path], check=False)
    return result.returncode == 0


def filter_stageable_paths(root: Path, paths: list[str]) -> list[str]:
    """Drop gitignored paths that ``git add`` would silently skip."""
    return [path for path in paths if not is_ignored_path(root, path)]


def commit(root: Path, message: str) -> str:
    _run(root, ["commit", "-m", message])
    return head_sha(root)


def staged_diff_stat(root: Path) -> str:
    return diff_summary(root, staged=True)


def has_staged_changes(root: Path) -> bool:
    result = _run(root, ["diff", "--cached", "--name-only"], check=False)
    return bool(result.stdout.strip())
