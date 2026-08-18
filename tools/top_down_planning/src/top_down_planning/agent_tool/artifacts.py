"""Artifact capture helpers for content-bound output evidence."""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path

from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.persistence.interface import RunStore


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _guess_media_type(path: Path) -> str:
    media_type, _encoding = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"


def prepare_output_artifact(
    *,
    workspace: Path,
    ref: str,
) -> dict[str, str | int | bytes]:
    """Resolve and hash a workspace artifact without writing store bytes."""

    from top_down_planning.config.snapshot_policy import (
        CanonicalPathError,
        canonicalize_evidence_ref,
    )

    workspace_root = workspace.resolve()
    try:
        canonical_ref = canonicalize_evidence_ref(ref, workspace=workspace_root)
    except CanonicalPathError as exc:
        raise RequestError(str(exc)) from exc

    artifact_path = (workspace_root / canonical_ref).resolve()
    if not artifact_path.is_relative_to(workspace_root):
        raise RequestError(f"artifact ref escapes workspace: {ref!r}")
    if not artifact_path.is_file():
        raise RequestError(f"artifact ref does not exist: {ref!r}")

    data = artifact_path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    filename = artifact_path.name
    snapshot_id = uuid.uuid4().hex
    snapshot_ref = str(Path("artifacts") / snapshot_id / filename)
    return {
        "ref": canonical_ref,
        "snapshot_id": snapshot_id,
        "filename": filename,
        "snapshot_ref": snapshot_ref,
        "sha256": sha256,
        "size": len(data),
        "media_type": _guess_media_type(artifact_path),
        "captured_at": _utc_now(),
        "data": data,
    }


def capture_output_artifact(
    store: RunStore,
    run_id: str,
    *,
    workspace: Path,
    ref: str,
) -> dict[str, str | int]:
    """Resolve, hash, and snapshot a workspace artifact into the run store.

    Evidence refs are canonicalized to workspace-relative POSIX paths. Absolute
    refs, unresolved ``..``, and symlink escapes fail validation explicitly.
    """

    prepared = prepare_output_artifact(workspace=workspace, ref=ref)
    snapshot_ref = store.write_artifact_bytes(
        run_id,
        str(prepared["snapshot_id"]),
        str(prepared["filename"]),
        bytes(prepared["data"]),
    )
    return {
        "ref": str(prepared["ref"]),
        "snapshot_ref": snapshot_ref,
        "sha256": str(prepared["sha256"]),
        "size": int(prepared["size"]),
        "media_type": str(prepared["media_type"]),
        "captured_at": str(prepared["captured_at"]),
    }


class EvidenceIntegrityError(RequestError):
    """Production evidence no longer matches persisted snapshot hashes."""


def validate_production_evidence_integrity(
    store: RunStore,
    run_id: str,
    production: dict[str, Any],
) -> None:
    """Verify every recorded output-evidence snapshot still matches its hash."""

    evidence_items = production.get("output_evidence") or []
    if not isinstance(evidence_items, list):
        raise EvidenceIntegrityError("production output_evidence must be a list")

    for entry in evidence_items:
        if not isinstance(entry, dict):
            raise EvidenceIntegrityError("output evidence entry must be a mapping")
        try:
            verify_evidence_snapshot(store, run_id, entry)
        except RequestError as exc:
            raise EvidenceIntegrityError(str(exc)) from exc


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
    _prefix, snapshot_id, filename = parts
    path = store.artifact_path(run_id, snapshot_id, filename)
    if not path.is_file():
        raise RequestError(f"evidence snapshot missing: {snapshot_ref}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha256:
        raise RequestError(
            f"evidence snapshot hash mismatch for {evidence.get('id')!r}: "
            "artifact content changed after capture"
        )
