"""Session capability tokens for agent mutation authorization."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core_tools.persistence import atomic_write_text_secure, RunNotFoundError, PersistenceError

from top_down_planning.persistence.interface import RunStore

CAPABILITY_TOKEN_FILE_ENV_VAR = "TDP_CAPABILITY_TOKEN_FILE"

MUTATING_OPS = frozenset(
    {
        "plan_apply",
        "production_apply",
        "production_request_amendment",
        "production_submit_completion",
        "production_report_blocked",
        "review_request",
        "review_respond",
        "review_record_finding_actions",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def hash_capability_secret(secret: str) -> str:
    """Return the persisted hash for a capability secret."""

    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_capability_secret(secret: str, secret_hash: str) -> bool:
    """Constant-time compare of a secret against its stored hash."""

    expected = hash_capability_secret(secret)
    return hmac.compare_digest(expected, secret_hash)


def ops_for_session(
    role: str,
    phase: str,
    *,
    session_kind: str = "primary",
) -> frozenset[str]:
    """Return mutating operations a session may perform."""

    normalized_role = str(role).strip()
    normalized_phase = str(phase).strip()
    if normalized_role == "reviewer" or session_kind == "reviewer":
        return frozenset({"review_respond"})

    if normalized_role == "planner":
        if normalized_phase in {"planning", "whole_plan_review", "plan_amendment"}:
            ops = {"plan_apply", "review_record_finding_actions"}
            if normalized_phase == "planning":
                ops.add("review_request")
            return frozenset(ops)

    if normalized_role == "producer":
        if normalized_phase in {"plan_validated", "production"}:
            return frozenset(
                {
                    "production_apply",
                    "production_request_amendment",
                    "production_submit_completion",
                    "production_report_blocked",
                    "review_request",
                    "review_record_finding_actions",
                }
            )
        if normalized_phase == "whole_output_review":
            return frozenset(
                {
                    "production_apply",
                    "production_submit_completion",
                    "review_record_finding_actions",
                }
            )

    return frozenset()


def new_capability_record(
    *,
    run_id: str,
    role: str,
    phase: str,
    allowed_ops: frozenset[str],
    session_id: str,
    session_kind: str = "primary",
    loop_id: str | None = None,
    session_instance_id: str | None = None,
    generation: int | None = None,
) -> tuple[str, dict[str, Any], str]:
    """Create a capability token id, persisted record, and one-time raw secret."""

    if not str(session_id).strip():
        raise ValueError("session_id is required for capability records")
    normalized_session_id = str(session_id).strip()
    normalized_role = str(role).strip()
    if normalized_role == "reviewer" or session_kind == "reviewer":
        if loop_id is None or not str(loop_id).strip():
            raise ValueError("loop_id is required for reviewer capabilities")

    token_id = f"cap-{uuid.uuid4().hex}"
    raw_secret = secrets.token_hex(32)
    record: dict[str, Any] = {
        "id": token_id,
        "secret_hash": hash_capability_secret(raw_secret),
        "run_id": run_id,
        "role": role,
        "phase": phase,
        "session_kind": session_kind,
        "session_id": normalized_session_id,
        "allowed_ops": sorted(allowed_ops),
        "created_at": _utc_now(),
        "revoked": False,
    }
    if session_instance_id is not None and str(session_instance_id).strip():
        record["session_instance_id"] = str(session_instance_id).strip()
    if generation is not None:
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation must be a positive integer")
        record["generation"] = generation
    if loop_id is not None:
        record["loop_id"] = str(loop_id).strip()
    return token_id, record, raw_secret


def capability_token_value(token_id: str, raw_secret: str) -> str:
    """Serialize a capability token for persistence or CLI authorization."""

    return f"{token_id}.{raw_secret}"


def parse_capability_token(value: str) -> tuple[str, str]:
    """Split a capability token into id and secret."""

    if "." not in value:
        raise ValueError("capability token must contain id and secret")
    token_id, secret = value.split(".", 1)
    if not token_id or not secret:
        raise ValueError("capability token must contain id and secret")
    return token_id, secret


def capability_token_file_path(store: RunStore, run_id: str) -> Path:
    """Return the orchestrator-owned path for the active session capability token."""

    active_path = getattr(store, "active_capability_token_path", None)
    if callable(active_path):
        return active_path(run_id)
    return store.capabilities_dir(run_id).parent / "capability" / "current"


def _require_safe_capability_token_path(store: RunStore, run_id: str) -> Path:
    from core_tools.persistence import PersistenceError

    path = capability_token_file_path(store, run_id)
    capability_dir = path.parent
    if capability_dir.is_symlink():
        raise PersistenceError("run path capability must not be a symlink")
    run_dir = store.run_dir(run_id)
    assert_run_contained = getattr(store, "_assert_run_contained", None)
    if callable(assert_run_contained):
        return assert_run_contained(run_dir, path)
    resolved = path.resolve()
    if not resolved.is_relative_to(run_dir.resolve()):
        raise PersistenceError(f"path escapes run directory: {path}")
    return path


def read_capability_token_file(path: Path) -> str | None:
    """Read a serialized capability token from disk when present."""

    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    return text


def write_capability_token_file(store: RunStore, run_id: str, token: str) -> Path:
    """Persist the active capability token for agent CLI reads at invocation time."""

    run_dir = store.run_dir(run_id)
    if not run_dir.is_dir() or not (run_dir / "run.json").is_file():
        raise RunNotFoundError(run_id, "run.json missing", runs_root=store.root)
    path = _require_safe_capability_token_path(store, run_id)
    atomic_write_text_secure(path, f"{str(token).strip()}\n")
    return path


def clear_capability_token_file(store: RunStore, run_id: str) -> None:
    """Remove the active capability token file when a session ends."""

    path = _require_safe_capability_token_path(store, run_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
