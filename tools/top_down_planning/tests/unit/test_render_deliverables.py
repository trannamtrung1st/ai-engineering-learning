from pathlib import Path

from top_down_planning.render_deliverables import (
    collect_deliverable_output,
    compute_deliverable_digest,
    diff_workspace_snapshots,
    snapshot_workspace_files,
)


def test_collect_deliverable_output_and_digest(tmp_path: Path) -> None:
    artifact = tmp_path / "implementation-plan.md"
    artifact.write_text("# Plan\n", encoding="utf-8")
    deliverable = collect_deliverable_output(tmp_path, ["implementation-plan.md"])
    assert deliverable.files["implementation-plan.md"] == "# Plan\n"
    assert deliverable.digest == compute_deliverable_digest(deliverable.files)


def test_snapshot_and_diff_workspace_files(tmp_path: Path) -> None:
    before = snapshot_workspace_files(tmp_path)
    (tmp_path / "implementation-plan.md").write_text("v1", encoding="utf-8")
    after = snapshot_workspace_files(tmp_path)
    assert diff_workspace_snapshots(before, after) == ["implementation-plan.md"]
