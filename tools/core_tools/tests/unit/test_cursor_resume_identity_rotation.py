"""Cursor durable resume identity rotation (stored A, stream reports B)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_tools.provider import CursorProvider
from core_tools.provider.errors import ProviderSessionError, ProviderSessionMismatchError


def _stream_with_durable_session(
    durable_id: str,
    *,
    text: str = "working",
) -> list[str]:
    return [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": durable_id,
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "session_id": durable_id,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": durable_id,
                "is_error": False,
                "result": "done",
            }
        ),
    ]


def test_cursor_resume_allows_legitimate_durable_a_to_b_rotation(tmp_path: Path) -> None:
    durable_a = "chat-session-stored-a"
    durable_b = "chat-session-stream-b"
    resume_argv: list[str] = []

    def runner(argv: list[str], cwd: Path):
        resume_argv[:] = list(argv)
        for line in _stream_with_durable_session(durable_b):
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
    provider._ensure_durable_session(  # noqa: SLF001 — adapter rehydrate
        durable_a,
        role="producer",
        kind="primary",
    )
    provider.resume_primary_session(
        durable_a,
        {"action": "continue", "phase": "production"},
        role="producer",
    )

    list(provider.stream_events(durable_a))

    assert "--resume" in resume_argv
    resume_index = resume_argv.index("--resume")
    assert resume_argv[resume_index + 1] == durable_a

    assert provider.canonical_session_id(durable_a) == durable_b
    reference = provider.get_session_reference(durable_b)
    assert reference.get("role") == "producer"
    assert reference.get("kind") == "primary"
    assert provider.canonical_session_id(durable_a) == provider.canonical_session_id(durable_b)


def test_cursor_resume_rejects_durable_b_when_b_owned_elsewhere(tmp_path: Path) -> None:
    durable_a = "chat-session-stored-a"
    durable_b = "chat-session-owned-b"

    def runner(argv: list[str], cwd: Path):
        for line in _stream_with_durable_session(durable_b):
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
    provider._ensure_durable_session(durable_a, role="producer", kind="primary")
    provider._ensure_durable_session(durable_b, role="producer", kind="primary")

    provider.resume_primary_session(
        durable_a,
        {"action": "continue", "phase": "production"},
        role="producer",
    )

    with pytest.raises((ProviderSessionMismatchError, ProviderSessionError)):
        list(provider.stream_events(durable_a))

    assert provider.canonical_session_id(durable_a) == durable_a


def test_cursor_resume_rejects_third_durable_identity_in_same_turn(tmp_path: Path) -> None:
    durable_a = "chat-session-stored-a"
    durable_b = "chat-session-stream-b"
    durable_c = "chat-session-stream-c"

    def runner(argv: list[str], cwd: Path):
        yield json.dumps({"type": "system", "subtype": "init", "session_id": durable_b})
        yield json.dumps(
            {
                "type": "assistant",
                "session_id": durable_c,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "later id"}],
                },
            }
        )

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    provider._ensure_durable_session(durable_a, role="producer", kind="primary")
    provider.resume_primary_session(
        durable_a,
        {"action": "continue", "phase": "production"},
        role="producer",
    )

    with pytest.raises(ProviderSessionMismatchError, match="unexpected session id"):
        list(provider.stream_events(durable_a))

    assert provider.canonical_session_id(durable_a) == durable_b
