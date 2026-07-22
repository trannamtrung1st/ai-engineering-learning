"""Whole-worktree finalization with provenance tracking."""

from __future__ import annotations

from pathlib import Path

from todos_tool.errors import GitError
from todos_tool.git_service import (
    _run,
    commit,
    has_staged_changes,
    head_sha,
    status,
)
from todos_tool.models import FinalizeResult, ProvenanceKind

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


def finalize_worktree(
    repo: Path,
    *,
    commit_prefix: str,
    skip_commit: bool,
    baseline_head: str | None,
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
    _run(repo, ["add", "-A"])

    if has_staged_changes(repo):
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

    raise GitError(
        f"{pre_summary}\n"
        "Worktree is clean and HEAD did not advance since baseline; "
        "no commit provenance available."
    )
