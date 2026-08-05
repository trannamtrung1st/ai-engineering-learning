"""Promote Sub-TDP child evidence snapshots into the parent artifact store."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from top_down_planning.persistence.interface import RunStore


def promote_child_evidence_to_parent(
    evidence: dict[str, Any],
    *,
    child_store: RunStore,
    child_run_id: str,
    parent_store: RunStore,
    parent_run_id: str,
) -> dict[str, Any]:
    """
    Copy child evidence bytes into the parent artifact store.

    Retains ``source_child_snapshot_ref`` / ``source_run_id`` for lineage while
    replacing ``snapshot_ref`` with a parent-local artifact path.
    """

    merged = dict(evidence)
    snapshot_ref = str(evidence.get("snapshot_ref") or "").strip()
    if not snapshot_ref:
        return merged
    parts = Path(snapshot_ref).parts
    if len(parts) != 3 or parts[0] != "artifacts":
        raise ValueError(
            f"malformed evidence snapshot_ref for {evidence.get('id')!r}: "
            f"{snapshot_ref!r}"
        )
    _prefix, snapshot_id, filename = parts
    child_path = child_store.artifact_path(child_run_id, snapshot_id, filename)
    if not child_path.is_file():
        raise ValueError(
            f"child evidence snapshot missing for {evidence.get('id')!r}: {snapshot_ref}"
        )
    data = child_path.read_bytes()
    new_snapshot_id = uuid.uuid4().hex
    new_ref = parent_store.write_artifact_bytes(
        parent_run_id,
        new_snapshot_id,
        filename,
        data,
    )
    merged["source_child_snapshot_ref"] = snapshot_ref
    merged["source_run_id"] = child_run_id
    merged["snapshot_ref"] = new_ref
    return merged


__all__ = ["promote_child_evidence_to_parent"]
