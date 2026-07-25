"""Atomic publication of assembled render output to workspace paths from the output goal."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_text
from top_down_planning.errors import PlanningToolError
from top_down_planning.models import OwnedArtifactsLedger, RenderManifest
from top_down_planning.paths import resolve_within_workspace
from top_down_planning.persistence import (
    publication_manifest_path,
    save_owned_artifacts,
    write_json,
)
from top_down_planning.render_assembly import AssembledOutput


@dataclass(frozen=True)
class PublicationResult:
    artifacts: list[str]
    publication_digest: str


def publish_assembled_output(
    *,
    output_dir: Path,
    workspace: Path,
    assembled: AssembledOutput,
    manifest: RenderManifest,
    previous_ledger: OwnedArtifactsLedger | None,
) -> PublicationResult:
    workspace = workspace.resolve()
    output_dir = output_dir.resolve()

    staging_to_publish = _build_publish_map(assembled, manifest)
    if not staging_to_publish:
        raise PlanningToolError("No assembled artifacts matched publish paths from the output goal.")

    workspace_relative = dict(staging_to_publish)
    destinations = {
        staging_key: resolve_within_workspace(workspace, publish_path)
        for staging_key, publish_path in staging_to_publish.items()
    }

    publication_digest = digest_text(
        "\n".join(
            f"{workspace_relative[staging_key]}:{assembled.files[staging_key]}"
            for staging_key in sorted(workspace_relative)
        )
    )

    staged_root = output_dir / ".publication-staging"
    if staged_root.exists():
        _remove_tree(staged_root)
    staged_root.mkdir(parents=True, exist_ok=True)

    try:
        for staging_key, publish_path in staging_to_publish.items():
            staged_file = staged_root / publish_path
            staged_file.parent.mkdir(parents=True, exist_ok=True)
            staged_file.write_text(
                assembled.files[staging_key].rstrip() + "\n",
                encoding="utf-8",
            )

        previous_owned = set(previous_ledger.artifacts if previous_ledger else [])
        new_owned = sorted(workspace_relative.values())

        for staging_key in sorted(destinations):
            source = staged_root / workspace_relative[staging_key]
            destination = destinations[staging_key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            _atomic_replace(source, destination)

        obsolete = previous_owned - set(new_owned)
        for relative in sorted(obsolete):
            path = workspace / relative
            if path.is_file():
                path.unlink()

        ledger = OwnedArtifactsLedger(
            output_dir=str(output_dir),
            artifacts=new_owned,
            publication_digest=publication_digest,
        )
        save_owned_artifacts(output_dir, ledger)
        write_json(
            publication_manifest_path(output_dir),
            {
                "publication_digest": publication_digest,
                "artifacts": new_owned,
                "deliverable_root": manifest.deliverable_root,
            },
        )
    finally:
        _remove_tree(staged_root)

    return PublicationResult(
        artifacts=new_owned,
        publication_digest=publication_digest,
    )


def _build_publish_map(
    assembled: AssembledOutput,
    manifest: RenderManifest,
) -> dict[str, str]:
    """Map assembled staging keys to workspace-relative publish paths."""
    publish_map: dict[str, str] = {}

    for item in manifest.items:
        if item.artifact_role != "final":
            continue
        staging_path = item.relative_path
        publish_path = item.publish_relative_path or staging_path
        if not staging_path or staging_path not in assembled.files:
            continue
        publish_map[staging_path] = publish_path

    return publish_map


def _atomic_replace(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(source.read_text(encoding="utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, destination)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
