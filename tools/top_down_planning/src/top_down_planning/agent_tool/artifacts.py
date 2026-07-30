"""Artifact capture helpers for content-bound output evidence."""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.persistence.interface import RunStore


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _guess_media_type(path: Path) -> str:
    media_type, _encoding = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"


def capture_output_artifact(
    store: RunStore,
    run_id: str,
    *,
    workspace: Path,
    evidence_id: str,
    ref: str,
) -> dict[str, str | int]:
    """Resolve, hash, and snapshot a workspace artifact into the run store."""

    workspace_root = workspace.resolve()
    artifact_path = (workspace_root / ref).resolve()
    if not artifact_path.is_relative_to(workspace_root):
        raise RequestError(f"artifact ref escapes workspace: {ref!r}")
    if not artifact_path.is_file():
        raise RequestError(f"artifact ref does not exist: {ref!r}")

    data = artifact_path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    filename = artifact_path.name
    snapshot_ref = store.write_artifact_bytes(
        run_id,
        evidence_id,
        filename,
        data,
    )
    return {
        "ref": ref,
        "snapshot_ref": snapshot_ref,
        "sha256": sha256,
        "size": len(data),
        "media_type": _guess_media_type(artifact_path),
        "captured_at": _utc_now(),
    }


def verify_evidence_snapshot(
    store: RunStore,
    run_id: str,
    evidence: dict[str, object],
) -> None:
    """Verify that a stored evidence snapshot still matches its recorded hash."""

    snapshot_ref = str(evidence.get("snapshot_ref") or "")
    sha256 = str(evidence.get("sha256") or "")
    if not snapshot_ref or not sha256:
        raise RequestError("output evidence requires snapshot_ref and sha256")

    parts = Path(snapshot_ref).parts
    if len(parts) != 3 or parts[0] != "artifacts":
        raise RequestError(f"invalid evidence snapshot_ref: {snapshot_ref!r}")
    _prefix, artifact_id, filename = parts
    path = store.artifact_path(run_id, artifact_id, filename)
    if not path.is_file():
        raise RequestError(f"evidence snapshot missing: {snapshot_ref}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha256:
        raise RequestError(
            f"evidence snapshot hash mismatch for {evidence.get('id')!r}: "
            "artifact content changed after capture"
        )
