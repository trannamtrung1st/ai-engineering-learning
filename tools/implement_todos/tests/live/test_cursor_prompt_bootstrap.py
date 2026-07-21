"""Opt-in smoke test against an authenticated live Cursor Agent CLI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from todos_tool.cursor_client import CursorClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("TODOS_TOOL_RUN_LIVE_SMOKE") != "1",
        reason="set TODOS_TOOL_RUN_LIVE_SMOKE=1 to use live Cursor",
    ),
]


@pytest.mark.asyncio
async def test_live_agent_reads_persisted_prompt_file(tmp_path: Path) -> None:
    token = "TODOS_TOOL_BOOTSTRAP_OK_7D31"
    prompt_path = tmp_path / "full-prompt.md"
    prompt_path.write_text(
        "Read this persisted prompt successfully. "
        f"Reply with exactly `{token}` and no other text.",
        encoding="utf-8",
    )

    client = CursorClient(no_color=True)
    result = await client.run_session(
        workspace=tmp_path,
        prompt="This inline prompt must be replaced by the bootstrap.",
        prompt_path=prompt_path,
        phase="review",
        timeout_seconds=120,
        events_path=tmp_path / "events.ndjson",
        log_path=tmp_path / "session.log",
    )

    assert result.assistant_text.strip() == token
