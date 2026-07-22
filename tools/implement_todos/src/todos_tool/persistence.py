"""Atomic run-state persistence and resume helpers."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from todos_tool.errors import PersistenceError
from todos_tool.models import RunState, Transition


def state_path(runs_dir: Path) -> Path:
    return runs_dir / "state.json"


def attempts_dir(runs_dir: Path, logical_attempt: int) -> Path:
    return runs_dir / "attempts" / f"{logical_attempt:02d}"


def load_state(runs_dir: Path) -> RunState | None:
    path = state_path(runs_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunState.from_dict(data)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise PersistenceError(f"Failed to load state from {path}: {exc}") from exc


def save_state(runs_dir: Path, state: RunState) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(timezone.utc)
    path = state_path(runs_dir)
    payload = state.to_dict()
    _atomic_write_json(path, payload)


def record_transition(
    runs_dir: Path,
    state: RunState,
    transition: Transition,
    **extra: Any,
) -> RunState:
    state.last_transition = transition
    entry: dict[str, Any] = {
        "transition": transition.value,
        "at": datetime.now(timezone.utc).isoformat(),
        "logical_attempt": state.logical_attempt,
        "phase": state.phase.value,
        "session_number": state.session_number,
        "session_restart_count": state.session_restart_count,
    }
    entry.update(extra)
    state.history.append(entry)
    save_state(runs_dir, state)
    return state


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload if isinstance(payload, (dict, list)) else payload
    _atomic_write_json(path, data if isinstance(data, dict) else {"value": data})


def append_ndjson(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str) + "\n")


def new_run_state(item_id: str, baseline_head: str | None) -> RunState:
    return RunState(item_id=item_id, baseline_head=baseline_head)
