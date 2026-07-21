"""Write and discover user-facing output artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning.models import RenderResponse
from top_down_planning.persistence import STATE_DIRNAME

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        STATE_DIRNAME,
    }
)


def _workspace_key(path: Path, workspace: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()


def _iter_candidate_files(workspace: Path, *, output_dir: Path) -> list[Path]:
    workspace = workspace.resolve()
    output_dir = output_dir.resolve()
    candidates: list[Path] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(workspace)
        except ValueError:
            continue
        if any(part in _SKIP_DIR_NAMES for part in rel.parts):
            continue
        try:
            rel_to_output = path.relative_to(output_dir)
            if rel_to_output.parts and rel_to_output.parts[0] == STATE_DIRNAME:
                continue
        except ValueError:
            pass
        candidates.append(path)
    return candidates


def snapshot_deliverable_files(workspace: Path, *, output_dir: Path) -> dict[str, float]:
    """Return workspace-relative paths to mtimes for discoverable deliverable files."""
    snapshot: dict[str, float] = {}
    for path in _iter_candidate_files(workspace, output_dir=output_dir):
        snapshot[_workspace_key(path, workspace)] = path.stat().st_mtime
    return snapshot


def discover_written_artifacts(
    workspace: Path,
    *,
    output_dir: Path,
    before: dict[str, float],
) -> list[Path]:
    """Return newly created or updated deliverable files anywhere in the workspace."""
    written: list[Path] = []
    for path in _iter_candidate_files(workspace, output_dir=output_dir):
        key = _workspace_key(path, workspace)
        mtime = path.stat().st_mtime
        if key not in before or before[key] < mtime:
            written.append(path)
    return sorted(written, key=lambda item: _workspace_key(item, workspace))


def normalize_artifact_path(relative_path: str) -> str:
    path = Path(relative_path.strip())
    if path.is_absolute():
        raise ValueError(f"Artifact path must be relative: {relative_path!r}")
    if ".." in path.parts:
        raise ValueError(f"Artifact path must not contain '..': {relative_path!r}")
    if path.parts and path.parts[0] == STATE_DIRNAME:
        raise ValueError(
            f"Artifact path must not write into {STATE_DIRNAME}: {relative_path!r}"
        )
    if not path.name:
        raise ValueError(f"Artifact path must include a filename: {relative_path!r}")
    return path.as_posix()


def write_render_artifacts(base_dir: Path, response: RenderResponse) -> list[Path]:
    written: list[Path] = []
    seen: set[str] = set()
    for artifact in response.artifacts:
        relative = normalize_artifact_path(artifact.relative_path)
        if relative in seen:
            raise ValueError(f"Duplicate artifact path: {relative}")
        seen.add(relative)
        target = base_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() == ".json":
            parsed = json.loads(artifact.content)
            if not isinstance(parsed, dict):
                raise ValueError("JSON artifact content must decode to an object")
            target.write_text(
                json.dumps(parsed, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        else:
            target.write_text(artifact.content.rstrip() + "\n", encoding="utf-8")
        written.append(target)
    return written
