"""Build bounded review/evidence context from Git state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from todos_tool.git_service import (
    _run,
    _split_nul_paths,
    head_sha,
    status,
)


@dataclass
class ReviewContext:
    baseline_head: str | None
    head_sha: str
    commits: list[str] = field(default_factory=list)
    staged_paths: list[str] = field(default_factory=list)
    unstaged_paths: list[str] = field(default_factory=list)
    untracked_paths: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    diff_excerpt: str = ""
    diff_total_chars: int = 0
    diff_truncated: bool = False
    status_porcelain: str = ""

    def format_summary(self) -> str:
        parts = [
            f"Baseline: {self.baseline_head or '(none)'}",
            f"HEAD: {self.head_sha}",
            "",
            "## Commits since baseline",
            *(self.commits or ["(none)"]),
            "",
            f"## Changed paths ({len(self.changed_paths)} total)",
            *(f"- {path}" for path in self.changed_paths[:100]),
        ]
        if len(self.changed_paths) > 100:
            parts.append(f"- ... and {len(self.changed_paths) - 100} more")
        parts.extend(
            [
                "",
                f"Staged: {len(self.staged_paths)} | "
                f"Unstaged: {len(self.unstaged_paths)} | "
                f"Untracked: {len(self.untracked_paths)}",
                "",
                "## Diff excerpt",
                self.diff_excerpt or "(no diff)",
            ]
        )
        if self.diff_truncated:
            parts.append(
                f"(diff truncated: showing excerpt of {self.diff_total_chars} chars total)"
            )
        return "\n".join(parts)


def _commits_since(repo: Path, baseline_head: str | None) -> list[str]:
    if baseline_head:
        result = _run(
            repo,
            ["log", "--oneline", "--no-decorate", f"{baseline_head}..HEAD"],
            check=False,
        )
    else:
        result = _run(repo, ["log", "--oneline", "--no-decorate", "-n", "20"], check=False)
    text = result.stdout.strip() if isinstance(result.stdout, str) else ""
    return [line for line in text.splitlines() if line.strip()]


def _categorize_paths(repo: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    st = status(repo)
    staged: set[str] = set()
    unstaged: set[str] = set()
    untracked: set[str] = set()

    porcelain = st.porcelain
    if porcelain:
        for line in porcelain.splitlines():
            if len(line) < 3:
                continue
            xy = line[:2]
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if xy == "??":
                untracked.add(path)
                continue
            if xy[0] != " ":
                staged.add(path)
            if xy[1] != " ":
                unstaged.add(path)

    staged_list = sorted(staged)
    unstaged_list = sorted(unstaged - staged)
    untracked_list = sorted(untracked)
    all_paths = sorted(staged | unstaged | untracked)

    if not all_paths:
        all_paths = sorted(set(st.changed_paths))

    return staged_list, unstaged_list, untracked_list, all_paths


def _full_diff_text(repo: Path, *, paths: list[str] | None) -> str:
    if paths is not None:
        if not paths:
            return "(no diff)"
        tracked_diff = _run(repo, ["diff", "HEAD", "--", *paths], check=False)
        text = tracked_diff.stdout if isinstance(tracked_diff.stdout, str) else ""
        untracked = [
            path
            for path in paths
            if _run(repo, ["ls-files", "--error-unmatch", path], check=False).returncode
            != 0
            and (repo / path).is_file()
        ]
        if untracked:
            text += "\n# Untracked files:\n" + "\n".join(untracked)
        return text or "(no diff)"

    tracked_diff = _run(repo, ["diff", "HEAD"], check=False)
    text = tracked_diff.stdout if isinstance(tracked_diff.stdout, str) else ""
    untracked_result = _run(
        repo,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        check=False,
    )
    untracked_paths = _split_nul_paths(untracked_result.stdout)
    if untracked_paths:
        text += "\n# Untracked files:\n" + "\n".join(untracked_paths)
    return text or "(no diff)"


def build_review_context(
    repo: Path,
    *,
    baseline_head: str | None = None,
    max_diff_chars: int = 12_000,
    paths: list[str] | None = None,
) -> ReviewContext:
    """Collect commits, path manifests, and a bounded diff for review prompts."""
    current_head = head_sha(repo)
    commits = _commits_since(repo, baseline_head)
    staged_paths, unstaged_paths, untracked_paths, changed_paths = _categorize_paths(repo)

    if paths is not None:
        allowed = set(paths)
        changed_paths = [path for path in changed_paths if path in allowed]
        if not changed_paths:
            changed_paths = sorted(allowed)

    full_diff = _full_diff_text(repo, paths=paths if paths is not None else None)
    total_chars = len(full_diff)
    truncated = total_chars > max_diff_chars
    if truncated:
        diff_excerpt = (
            full_diff[:max_diff_chars]
            + f"\n... truncated ({total_chars} chars total across "
            f"{len(changed_paths)} path(s))"
        )
    else:
        diff_excerpt = full_diff

    st = status(repo)
    return ReviewContext(
        baseline_head=baseline_head,
        head_sha=current_head,
        commits=commits,
        staged_paths=staged_paths,
        unstaged_paths=unstaged_paths,
        untracked_paths=untracked_paths,
        changed_paths=changed_paths,
        diff_excerpt=diff_excerpt,
        diff_total_chars=total_chars,
        diff_truncated=truncated,
        status_porcelain=st.porcelain or "(clean)",
    )
