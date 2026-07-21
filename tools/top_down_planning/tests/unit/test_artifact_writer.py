from pathlib import Path

import pytest

from top_down_planning.artifact_writer import (
    discover_written_artifacts,
    normalize_artifact_path,
    snapshot_deliverable_files,
    write_render_artifacts,
)
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
    with pytest.raises(ValueError, match="planning-output"):
        normalize_artifact_path(".planning-output/plan.yaml")


def test_discover_written_artifacts_finds_new_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    before = snapshot_deliverable_files(tmp_path, output_dir=output_dir)
    target = tmp_path / "implementation-plan.md"
    target.write_text("# Plan\n", encoding="utf-8")
    discovered = discover_written_artifacts(
        tmp_path, output_dir=output_dir, before=before
    )
    assert discovered == [target]


def test_discover_written_artifacts_finds_nested_workspace_paths(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    before = snapshot_deliverable_files(tmp_path, output_dir=output_dir)
    target = tmp_path / "plans" / "feature" / "implementation-plan.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Plan\n", encoding="utf-8")
    discovered = discover_written_artifacts(
        tmp_path, output_dir=output_dir, before=before
    )
    assert discovered == [target]


def test_discover_written_artifacts_ignores_state_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    before = snapshot_deliverable_files(tmp_path, output_dir=output_dir)
    state_file = output_dir / ".planning-output" / "plan.yaml"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("plan: []\n", encoding="utf-8")
    discovered = discover_written_artifacts(
        tmp_path, output_dir=output_dir, before=before
    )
    assert discovered == []
