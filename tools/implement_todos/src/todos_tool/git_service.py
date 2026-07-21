"""Safe Git operations: dirty-tree checks, explicit staging, commits."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from todos_tool.errors import GitError, PersistenceError


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
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[str | bytes]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=input_data is None,
        input=input_data,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = (
            result.stderr.strip()
            if isinstance(result.stderr, str)
            else result.stderr.decode("utf-8", errors="replace").strip()
        )
        stdout = (
            result.stdout.strip()
            if isinstance(result.stdout, str)
            else result.stdout.decode("utf-8", errors="replace").strip()
        )
        raise GitError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{stderr or stdout}"
        )
    return result


def _split_nul_paths(raw: str | bytes) -> list[str]:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    if not text:
        return []
    return [part for part in text.split("\0") if part]


def _parse_porcelain_z(raw: str | bytes) -> list[str]:
    """Parse ``git status --porcelain -z`` into changed paths."""
    if isinstance(raw, str):
        data = raw.encode("utf-8")
    else:
        data = raw
    if not data:
        return []
    parts = data.split(b"\0")
    paths: list[str] = []
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        if not part:
            idx += 1
            continue
        line = part.decode("utf-8", errors="replace")
        if len(line) < 3:
            idx += 1
            continue
        xy = line[:2]
        path = line[3:]
        if xy[0] in "RC" and len(xy) == 2 and xy[1] in " MADRCU":
            if idx + 1 < len(parts) and parts[idx + 1]:
                paths.append(parts[idx + 1].decode("utf-8", errors="replace"))
                idx += 2
                continue
        if path:
            paths.append(path)
        idx += 1
    return paths


def ensure_git_repo(root: Path) -> None:
    result = _run(root, ["rev-parse", "--is-inside-work-tree"], check=False)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise GitError(f"Not a git repository: {root}")


def head_sha(root: Path) -> str:
    result = _run(root, ["rev-parse", "HEAD"])
    return result.stdout.strip()


def verify_git_object(root: Path, ref: str, *, expected_type: str) -> None:
    """Raise ``PersistenceError`` when ``ref`` is missing or not ``expected_type``."""
    result = _run(root, ["cat-file", "-t", ref], check=False)
    if result.returncode != 0:
        raise PersistenceError(f"Git object not found: {ref}")
    actual = result.stdout.strip()
    if actual != expected_type:
        raise PersistenceError(
            f"Expected git object type {expected_type!r} for {ref}, got {actual!r}"
        )


def verify_commit_sha(root: Path, sha: str) -> None:
    verify_git_object(root, sha, expected_type="commit")


def require_usable_baseline(root: Path, baseline: str | None, *, item_id: str) -> str:
    """Return a verified baseline ref or raise ``PersistenceError``."""
    if not baseline or not baseline.strip():
        raise PersistenceError(
            f"Run state for {item_id} is missing baseline_head; "
            "cannot resume or commit safely. Fix or remove todos/runs state."
        )
    verify_git_object(root, baseline.strip(), expected_type="commit")
    return baseline.strip()


def status(root: Path) -> GitStatus:
    porcelain_result = _run(root, ["status", "--porcelain"])
    porcelain = porcelain_result.stdout
    z_result = _run(root, ["status", "--porcelain", "-z"], check=False)
    raw = z_result.stdout
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    paths = _parse_porcelain_z(raw)
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
    result = _run(root, ["diff", "--cached", "--name-only", "-z"], check=False)
    return _split_nul_paths(result.stdout)


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


def expand_path_prefixes(paths: set[str]) -> set[str]:
    expanded = set(paths)
    for path in paths:
        parts = Path(path.replace("\\", "/")).parts
        for idx in range(1, len(parts)):
            expanded.add(str(Path(*parts[:idx])))
    return expanded


def paths_overlap(path: str, allowed: str) -> bool:
    """Return True when two repo paths refer to the same file or directory tree."""
    left = path.replace("\\", "/").rstrip("/")
    right = allowed.replace("\\", "/").rstrip("/")
    if not left or not right:
        return False
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


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
    permitted = expand_path_prefixes(permitted_paths)
    unrelated = [
        path
        for path in st.changed_paths
        if not is_todos_metadata_path(path, todos_dir)
        and path not in permitted
        and not any(paths_overlap(path, allowed) for allowed in permitted_paths)
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
    permitted = expand_path_prefixes(permitted_paths or set())
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
        and not any(paths_overlap(path, allowed) for allowed in permitted)
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
            ["diff", "--name-only", "-z", baseline],
            check=False,
        )
        names = _split_nul_paths(result.stdout)
        untracked = _run(
            root,
            ["ls-files", "--others", "--exclude-standard", "-z"],
            check=False,
        )
        for path in _split_nul_paths(untracked.stdout):
            if path not in names:
                names.append(path)
        return names
    st = status(root)
    return st.changed_paths


def diff_text(
    root: Path,
    *,
    max_chars: int = 12_000,
    paths: list[str] | None = None,
) -> str:
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
        ["ls-files", "--others", "--exclude-standard", "-z"],
        check=False,
    )
    text = result.stdout
    untracked_paths = _split_nul_paths(untracked_list.stdout)
    if untracked_paths:
        text += "\n# Untracked files:\n" + "\n".join(untracked_paths)
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... truncated ({len(text)} chars total)"
    return text


def paths_changed_since(root: Path, baseline: str, pre_existing: set[str]) -> list[str]:
    """Return paths changed since baseline excluding pre-existing dirty paths."""
    names = diff_names(root, baseline=baseline)
    return [p for p in names if p not in pre_existing]


def fingerprint_path(root: Path, path: str) -> str:
    """Return a stable content fingerprint for a working-tree path."""
    full = root / path
    if full.is_file():
        digest = hashlib.sha256()
        with full.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return f"file:{digest.hexdigest()}"
    if full.is_dir():
        return "dir"
    if full.exists():
        return "other"
    tracked = _run(root, ["ls-files", "--error-unmatch", path], check=False).returncode == 0
    if tracked:
        blob = _run(root, ["rev-parse", f":{path}"], check=False)
        if blob.returncode == 0:
            return f"index:{blob.stdout.strip()}"
    return "missing"


def capture_pre_dirty_fingerprints(root: Path, paths: set[str]) -> dict[str, str]:
    return {path: fingerprint_path(root, path) for path in sorted(paths)}


def verify_pre_dirty_unchanged(
    root: Path,
    fingerprints: dict[str, str],
    *,
    item_id: str,
) -> None:
    """Fail when any pre-existing dirty path changed during execution."""
    if not fingerprints:
        return
    changed: list[str] = []
    for path, expected in fingerprints.items():
        current = fingerprint_path(root, path)
        if current != expected:
            changed.append(path)
    if changed:
        raise GitError(
            f"{item_id}: agent modified file(s) that were already dirty before this run. "
            "Commit or stash those changes before running with --allow-dirty.\n"
            + "\n".join(changed)
        )


def require_pre_dirty_fingerprints(
    state_fingerprints: dict[str, str],
    pre_existing_dirty: set[str],
    *,
    item_id: str,
    resuming: bool,
) -> dict[str, str]:
    """Ensure persisted fingerprints exist for active runs with pre-dirty paths."""
    if not pre_existing_dirty:
        return state_fingerprints
    if state_fingerprints:
        return state_fingerprints
    if resuming:
        raise PersistenceError(
            f"Run state for {item_id} has no pre_dirty_fingerprints but the tree "
            "had unrelated dirty files. Cannot resume safely; fix or reset run state."
        )
    return {}


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
    return bool(staged_paths(root))
