"""Atomic publication of assembled render output."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_text
from top_down_planning.models import OwnedArtifactsLedger
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
    previous_ledger: OwnedArtifactsLedger | None,
) -> PublicationResult:
    deliverable_dir = output_dir.resolve()
    deliverable_dir.mkdir(parents=True, exist_ok=True)

    new_relative_paths = sorted(assembled.files.keys())
    publication_digest = digest_text(
        "\n".join(f"{path}:{assembled.files[path]}" for path in new_relative_paths)
    )

    staged_root = deliverable_dir / ".publication-staging"
    if staged_root.exists():
        _remove_tree(staged_root)
    staged_root.mkdir(parents=True, exist_ok=True)

    try:
        for relative, content in assembled.files.items():
            target = staged_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.rstrip() + "\n", encoding="utf-8")

        previous_owned = set(previous_ledger.artifacts if previous_ledger else [])
        new_owned = set(new_relative_paths)

        for relative in new_relative_paths:
            source = staged_root / relative
            destination = deliverable_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _atomic_replace(source, destination)

        obsolete = previous_owned - new_owned
        for relative in sorted(obsolete):
            path = deliverable_dir / relative
            if path.is_file():
                path.unlink()

        ledger = OwnedArtifactsLedger(
            output_dir=str(deliverable_dir),
            artifacts=new_relative_paths,
            publication_digest=publication_digest,
        )
        save_owned_artifacts(output_dir, ledger)
        write_json(
            publication_manifest_path(output_dir),
            {
                "publication_digest": publication_digest,
                "artifacts": new_relative_paths,
            },
        )
    finally:
        _remove_tree(staged_root)

    workspace_relative = [
        _workspace_relative(deliverable_dir / rel, workspace)
        for rel in new_relative_paths
    ]
    return PublicationResult(
        artifacts=workspace_relative,
        publication_digest=publication_digest,
    )


def _workspace_relative(path: Path, workspace: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()


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
