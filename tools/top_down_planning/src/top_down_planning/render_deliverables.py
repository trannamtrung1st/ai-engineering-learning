"""Workspace deliverable discovery and digest computation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_file, digest_text


@dataclass(frozen=True)
class DeliverableOutput:
    files: dict[str, str]
    digest: str


def compute_deliverable_digest(files: dict[str, str]) -> str:
    payload = {path: files[path] for path in sorted(files)}
    return digest_text(
        "\n".join(f"{path}\n{payload[path]}" for path in payload)
    )


def collect_deliverable_output(
    workspace: Path,
    artifact_paths: list[str],
) -> DeliverableOutput:
    workspace = workspace.resolve()
    files: dict[str, str] = {}
    for relative_path in sorted(artifact_paths):
        destination = workspace / relative_path
        if not destination.is_file():
            raise ValueError(f"missing deliverable at {relative_path!r}")
        files[relative_path] = destination.read_text(encoding="utf-8")
    return DeliverableOutput(files=files, digest=compute_deliverable_digest(files))


def discover_workspace_artifacts(
    workspace: Path,
    *,
    exclude_dirnames: tuple[str, ...] = (".planning-output",),
) -> list[str]:
    workspace = workspace.resolve()
    artifacts: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        parts = Path(relative).parts
        if any(part in exclude_dirnames for part in parts):
            continue
        if relative.startswith("."):
            continue
        artifacts.append(relative)
    return artifacts


def snapshot_workspace_files(workspace: Path) -> dict[str, str]:
    """Return relative path -> content digest for all workspace files."""
    workspace = workspace.resolve()
    snapshots: dict[str, str] = {}
    for relative in discover_workspace_artifacts(workspace):
        snapshots[relative] = digest_file(workspace / relative)
    return snapshots


def diff_workspace_snapshots(
    before: dict[str, str],
    after: dict[str, str],
) -> list[str]:
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    return sorted(changed)
