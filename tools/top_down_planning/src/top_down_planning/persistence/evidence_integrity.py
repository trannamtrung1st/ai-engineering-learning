"""Persisted production evidence snapshot verification."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

from top_down_planning.agent_tool.artifacts import verify_evidence_snapshot
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.domain.production import live_output_evidence_entries
from top_down_planning.persistence.commit import StagedArtifact


def verify_persisted_production_evidence_snapshots(
    store: Any,
    run_id: str,
    production: dict[str, Any],
    *,
    staged_artifacts: Sequence[StagedArtifact] = (),
) -> None:
    """Fail closed when live evidence rows lack valid captured snapshot bytes."""

    staged = {
        str(Path("artifacts") / artifact.snapshot_id / artifact.filename): artifact
        for artifact in staged_artifacts
    }
    for entry in live_output_evidence_entries(production):
        snapshot_ref = str(entry.get("snapshot_ref") or "")
        staged_artifact = staged.get(snapshot_ref)
        if staged_artifact is not None:
            actual = hashlib.sha256(staged_artifact.data).hexdigest()
            expected = str(entry.get("sha256") or "")
            if actual != expected:
                from core_tools.persistence import PersistenceError

                raise PersistenceError(
                    f"staged evidence snapshot hash mismatch for {entry.get('id')!r}"
                )
            continue
        try:
            verify_evidence_snapshot(store, run_id, entry)
        except RequestError as exc:
            from core_tools.persistence import PersistenceError

            raise PersistenceError(str(exc)) from exc


__all__ = ["verify_persisted_production_evidence_snapshots"]
