"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers import write_todos

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_AGENT = FIXTURES / "fake_agent.py"

# Re-export for convenience
__all__ = ["write_todos"]


@pytest.fixture
def fake_agent(tmp_path: Path) -> Path:
    dest = tmp_path / "fake-agent"
    shutil.copy(FAKE_AGENT, dest)
    dest.chmod(0o755)
    return dest


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture
def sample_item() -> dict:
    return {
        "version": 1,
        "id": "TASK-001",
        "title": "Add greeting helper",
        "type": "feature",
        "status": "pending",
        "priority": 100,
        "depends_on": [],
        "description": "Add a greeting helper.",
        "acceptance_criteria": [
            "A greeting helper function exists and returns a non-empty string.",
            "Basic unit tests cover the happy path.",
        ],
        "validation": {"commands": ["pytest"]},
        "context": {"files": []},
        "result": {
            "completed_at": None,
            "commit_sha": None,
            "summary": None,
        },
    }
