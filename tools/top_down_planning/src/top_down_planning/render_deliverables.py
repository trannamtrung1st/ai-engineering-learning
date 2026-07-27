"""Workspace deliverable collection from the ownership ledger."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_text
from top_down_planning.models import OwnershipLedger
from top_down_planning.paths import resolve_within_workspace
from top_down_planning.persistence import deliverable_manifest_path, write_json
from top_down_planning.render_ownership import final_paths


@dataclass(frozen=True)
class FinalizationResult:
    artifacts: list[str]
    deliverable_digest: str


@dataclass(frozen=True)
class DeliverableOutput:
    files: dict[str, str]
    digest: str


def collect_deliverable_output_from_ledger(
    workspace: Path,
    ledger: OwnershipLedger,
) -> DeliverableOutput:
    workspace = workspace.resolve()
    files: dict[str, str] = {}
    for relative_path in final_paths(ledger):
        destination = resolve_within_workspace(workspace, relative_path)
        if not destination.is_file():
            raise ValueError(f"missing deliverable at {relative_path!r}")
        files[relative_path] = destination.read_text(encoding="utf-8")
    return DeliverableOutput(files=files, digest=compute_deliverable_digest(files))


def compute_deliverable_digest(files: dict[str, str]) -> str:
    payload = {path: files[path] for path in sorted(files)}
    return digest_text(
        "\n".join(f"{path}\n{payload[path]}" for path in payload)
    )


def finalize_deliverables_from_ledger(
    *,
    output_dir: Path,
    ledger: OwnershipLedger,
    workspace: Path,
) -> FinalizationResult:
    deliverable = collect_deliverable_output_from_ledger(workspace, ledger)
    artifacts = final_paths(ledger)
    write_json(
        deliverable_manifest_path(output_dir),
        {
            "deliverable_digest": deliverable.digest,
            "artifacts": artifacts,
        },
    )
    return FinalizationResult(
        artifacts=artifacts,
        deliverable_digest=deliverable.digest,
    )
