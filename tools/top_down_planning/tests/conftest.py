from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_agent_bin() -> str:
    return str(Path(__file__).parent / "fixtures" / "fake_agent.py")


@pytest.fixture
def example_input() -> Path:
    return Path(__file__).parent.parent / "examples" / "idea.md"
