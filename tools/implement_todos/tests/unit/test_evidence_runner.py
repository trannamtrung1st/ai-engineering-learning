"""Evidence runner subprocess behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from todos_tool.errors import ValidationError
from todos_tool.evidence_runner import run_evidence_commands
from todos_tool.models import EvidenceCommandSpec
from dataclasses import replace

from todos_tool.project_context import EvidencePolicy, ProjectContext


@pytest.mark.asyncio
async def test_driver_mode_pass_and_fail(tmp_path) -> None:
    results = await run_evidence_commands(
        tmp_path,
        [EvidenceCommandSpec(command="exit 0"), EvidenceCommandSpec(command="exit 7")],
        timeout_seconds=5,
    )
    assert results[0].passed is True
    assert results[0].source == "driver"
    assert results[1].passed is False
    assert results[1].exit_code == 7


@pytest.mark.asyncio
async def test_forbidden_command_blocked_before_execution(tmp_path: Path) -> None:
    ctx = replace(
        ProjectContext.neutral(),
        evidence=EvidencePolicy(forbidden_command_patterns=["curl *"]),
    )
    with pytest.raises(ValidationError, match="forbidden"):
        await run_evidence_commands(
            tmp_path,
            [EvidenceCommandSpec(command="curl https://example.com")],
            timeout_seconds=5,
            project_context=ctx,
        )
