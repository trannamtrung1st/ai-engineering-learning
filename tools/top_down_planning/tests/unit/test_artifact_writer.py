from pathlib import Path

import pytest

from top_down_planning.artifact_writer import normalize_artifact_path, write_render_artifacts
from top_down_planning.models import RenderArtifact, RenderResponse


def test_write_render_artifacts(tmp_path: Path) -> None:
    response = RenderResponse(
        artifacts=[
            RenderArtifact(
                relative_path="plans/implementation-plan.md",
                content="# Plan\n",
            )
        ]
    )
    written = write_render_artifacts(tmp_path, response)
    assert written == [tmp_path / "plans" / "implementation-plan.md"]
    assert written[0].read_text(encoding="utf-8") == "# Plan\n"


def test_reject_state_dir_artifact_path() -> None:
    with pytest.raises(ValueError, match="top-down-planning"):
        normalize_artifact_path(".top-down-planning/plan.yaml")
