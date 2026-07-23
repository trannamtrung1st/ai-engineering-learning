"""Whole-worktree finalization with provenance tracking."""

from __future__ import annotations

from pathlib import Path

from todos_tool.errors import GitError
from todos_tool.git_service import (
    _run,
    commit,
    has_staged_changes,
    head_sha,
    is_todos_metadata_path,
    status,
)
from todos_tool.models import FinalizeResult, ProvenanceKind, DEFAULT_ALLOW_EMPTY_COMMIT

MAX_STATUS_PATHS = 50


def _format_pre_stage_summary(repo: Path) -> str:
    st = status(repo)
    preview = st.changed_paths[:MAX_STATUS_PATHS]
    lines = [f"  {path}" for path in preview]
    extra = len(st.changed_paths) - len(preview)
    if extra > 0:
        lines.append(f"  ... and {extra} more path(s)")
    count_line = f"Pre-stage changed paths: {len(st.changed_paths)}"
    if not lines:
        return f"{count_line}\n(clean working tree)"
    return count_line + "\n" + "\n".join(lines)


def _trackable_changed_paths(repo: Path, *, todos_dir: str) -> list[str]:
    st = status(repo)
    return [
        path
        for path in st.changed_paths
        if not is_todos_metadata_path(path, todos_dir)
    ]


def finalize_worktree(
    repo: Path,
    *,
    commit_prefix: str,
    skip_commit: bool,
    baseline_head: str | None,
    commit_message: str | None = None,
    allow_empty_commit: bool = DEFAULT_ALLOW_EMPTY_COMMIT,
    todos_dir: str = "todos",
) -> FinalizeResult:
    """Stage the full worktree and commit, or record external/skipped provenance."""
    if skip_commit:
        sha = head_sha(repo)
        return FinalizeResult(
            commit_sha=sha,
            provenance_kind=ProvenanceKind.SKIPPED,
            message="Commit skipped (--skip-commit)",
        )

    pre_summary = _format_pre_stage_summary(repo)
    current = head_sha(repo)
    if (
        allow_empty_commit
        and baseline_head
        and current == baseline_head
        and not _trackable_changed_paths(repo, todos_dir=todos_dir)
    ):
        return FinalizeResult(
            commit_sha=current,
            provenance_kind=ProvenanceKind.UNCHANGED,
            message=(
                f"{pre_summary}\n"
                "No trackable source changes and HEAD unchanged since baseline "
                "(unchanged provenance)."
            ),
        )

    _run(repo, ["add", "-A"])

    if has_staged_changes(repo):
        if commit_message and commit_message.strip():
            message = commit_message.strip()
        else:
            prefix = commit_prefix.strip()
            if prefix and not prefix.endswith(":"):
                prefix = f"{prefix}:"
            message = f"{prefix} finalize worktree"
        sha = commit(repo, message)
        return FinalizeResult(
            commit_sha=sha,
            provenance_kind=ProvenanceKind.DRIVER,
            message=f"{pre_summary}\nCommitted as {sha[:8]}: {message}",
        )

    current = head_sha(repo)
    if baseline_head and current != baseline_head:
        return FinalizeResult(
            commit_sha=current,
            provenance_kind=ProvenanceKind.EXTERNAL,
            message=(
                f"{pre_summary}\n"
                "No staged changes; HEAD advanced since baseline (external provenance)."
            ),
        )

    if allow_empty_commit:
        return FinalizeResult(
            commit_sha=current,
            provenance_kind=ProvenanceKind.UNCHANGED,
            message=(
                f"{pre_summary}\n"
                "No trackable source changes and HEAD unchanged since baseline "
                "(unchanged provenance)."
            ),
        )

    raise GitError(
        f"{pre_summary}\n"
        "Worktree is clean and HEAD did not advance since baseline; "
        "no commit provenance available."
    )
