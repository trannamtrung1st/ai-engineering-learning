"""Write and discover user-facing output artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning.models import RenderResponse
from top_down_planning.persistence import STATE_DIRNAME


def snapshot_deliverable_files(output_dir: Path) -> dict[str, float]:
    """Return relative paths to mtimes for deliverable files under output_dir."""
    snapshot: dict[str, float] = {}
    if not output_dir.is_dir():
        return snapshot
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(output_dir)
        if rel.parts and rel.parts[0] == STATE_DIRNAME:
            continue
        snapshot[rel.as_posix()] = path.stat().st_mtime
    return snapshot


def discover_written_artifacts(
    output_dir: Path,
    before: dict[str, float],
) -> list[Path]:
    """Return newly created or updated deliverable files under output_dir."""
    written: list[Path] = []
    if not output_dir.is_dir():
        return written
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(output_dir)
        if rel.parts and rel.parts[0] == STATE_DIRNAME:
            continue
        key = rel.as_posix()
        mtime = path.stat().st_mtime
        if key not in before or before[key] < mtime:
            written.append(path)
    return sorted(written, key=lambda item: item.relative_to(output_dir).as_posix())


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


def write_render_artifacts(output_dir: Path, response: RenderResponse) -> list[Path]:
    written: list[Path] = []
    seen: set[str] = set()
    for artifact in response.artifacts:
        relative = normalize_artifact_path(artifact.relative_path)
        if relative in seen:
            raise ValueError(f"Duplicate artifact path: {relative}")
        seen.add(relative)
        target = output_dir / relative
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