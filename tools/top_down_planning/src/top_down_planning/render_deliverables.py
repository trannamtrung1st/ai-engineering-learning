"""Workspace deliverable materialization, collection, and ledger finalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.models import OwnedArtifactsLedger, RenderBatchTransaction, RenderManifest
from top_down_planning.paths import resolve_within_workspace
from top_down_planning.persistence import (
    deliverable_manifest_path,
    save_owned_artifacts,
    write_json,
)
from top_down_planning.render_assembly import compute_assembled_digest


@dataclass(frozen=True)
class FinalizationResult:
    artifacts: list[str]
    deliverable_digest: str


@dataclass(frozen=True)
class DeliverableOutput:
    files: dict[str, str]
    digest: str


def final_destination_paths(manifest: RenderManifest) -> list[str]:
    return sorted(
        path
        for item in manifest.items
        if item.artifact_role == "final"
        for path in [item.relative_path]
        if path
    )


def materialize_final_deliverables(
    workspace: Path,
    transaction: RenderBatchTransaction,
) -> list[str]:
    """Ensure final deliverables exist at workspace destination paths."""
    workspace = workspace.resolve()
    written: list[str] = []

    for artifact in transaction.artifacts:
        if not artifact.relative_path:
            continue
        destination = resolve_within_workspace(workspace, artifact.relative_path)
        if artifact.content.strip():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(artifact.content.rstrip() + "\n", encoding="utf-8")
            written.append(artifact.relative_path)
        elif destination.is_file():
            written.append(artifact.relative_path)
        else:
            raise ValueError(
                f"deliverable missing at {artifact.relative_path!r}: "
                "write the file in the workspace or include content in the transaction"
            )

    return written


def collect_deliverable_output(
    workspace: Path,
    manifest: RenderManifest,
) -> DeliverableOutput:
    workspace = workspace.resolve()
    files: dict[str, str] = {}

    for relative_path in final_destination_paths(manifest):
        destination = resolve_within_workspace(workspace, relative_path)
        if not destination.is_file():
            raise ValueError(f"missing deliverable at {relative_path!r}")
        files[relative_path] = destination.read_text(encoding="utf-8")

    return DeliverableOutput(files=files, digest=compute_deliverable_digest(files))


def compute_deliverable_digest(files: dict[str, str]) -> str:
    return compute_assembled_digest(files)


def finalize_deliverables(
    *,
    output_dir: Path,
    workspace: Path,
    manifest: RenderManifest,
    previous_ledger: OwnedArtifactsLedger | None,
) -> FinalizationResult:
    """Record owned workspace deliverables and remove obsolete files from prior runs."""
    workspace = workspace.resolve()
    output_dir = output_dir.resolve()

    deliverable = collect_deliverable_output(workspace, manifest)
    artifacts = final_destination_paths(manifest)
    deliverable_digest = deliverable.digest

    previous_owned = set(previous_ledger.artifacts if previous_ledger else [])
    new_owned = list(artifacts)

    obsolete = previous_owned - set(new_owned)
    for relative in sorted(obsolete):
        path = workspace / relative
        if path.is_file():
            path.unlink()

    ledger = OwnedArtifactsLedger(
        output_dir=str(output_dir),
        artifacts=new_owned,
        deliverable_digest=deliverable_digest,
    )
    save_owned_artifacts(output_dir, ledger)
    write_json(
        deliverable_manifest_path(output_dir),
        {
            "deliverable_digest": deliverable_digest,
            "artifacts": new_owned,
            "deliverable_root": manifest.deliverable_root,
        },
    )

    return FinalizationResult(
        artifacts=new_owned,
        deliverable_digest=deliverable_digest,
    )
