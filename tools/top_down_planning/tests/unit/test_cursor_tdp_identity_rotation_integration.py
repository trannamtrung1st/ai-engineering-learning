"""Cursor adapter rotation persisted through TDP primary session sync."""

from __future__ import annotations

import json
from pathlib import Path

from core_tools.provider import CursorProvider
from top_down_planning.domain.session_lineage import SESSION_PROVIDER_IDENTITY_ROTATED
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.session_events import (
    commit_primary_provider_session_binding,
    sync_persisted_session_id,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
from core_tools.provider import StubProvider
from tests.support.focused_review import create_production_run_open_item_second


def test_tdp_persists_cursor_resume_identity_rotation_with_unchanged_logical_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010401-010401"
    durable_a = "chat-session-stored-a"
    durable_b = "chat-session-stream-b"

    def runner(argv: list[str], cwd: Path):
        for line in (
            json.dumps({"type": "system", "subtype": "init", "session_id": durable_b}),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "session_id": durable_b,
                    "is_error": False,
                    "result": "done",
                }
            ),
        ):
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    create_production_run_open_item_second(store, StubProvider(), run_id=run_id)
    run = store.load_run(run_id)
    binding_before = get_primary_binding(run, "producer")
    assert binding_before is not None
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id=durable_a,
        provider="cursor",
        session_provider=None,
    )
    run = store.load_run(run_id)
    binding_before = get_primary_binding(run, "producer")
    instance_id = binding_before.session_instance_id
    generation = binding_before.generation

    provider._ensure_durable_session(durable_a, role="producer", kind="primary")
    provider.resume_primary_session(
        durable_a,
        {"action": "continue", "phase": PRODUCTION},
        role="producer",
    )
    list(provider.stream_events(durable_a))

    assert provider.canonical_session_id(durable_a) == durable_b
    resolved = sync_persisted_session_id(
        provider,
        store,
        run_id,
        durable_a,
        role="producer",
    )
    assert resolved == durable_b

    run_after = store.load_run(run_id)
    binding_after = get_primary_binding(run_after, "producer")
    assert binding_after is not None
    assert binding_after.provider_session_id == durable_b
    assert binding_after.session_instance_id == instance_id
    assert binding_after.generation == generation

    rotated = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == SESSION_PROVIDER_IDENTITY_ROTATED
    ]
    assert len(rotated) == 1
    assert rotated[0]["old_provider_session_id"] == durable_a
    assert rotated[0]["new_provider_session_id"] == durable_b
