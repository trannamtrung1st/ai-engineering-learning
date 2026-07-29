from pathlib import Path

from top_down_planning.models import PlanningLimits, RenderConfig
from top_down_planning.persistence import load_run_state, new_run_state, save_run_state
from top_down_planning.render_flow import RenderFlowDeps, _persist_render_result
from tests.helpers import render_output_goal


def test_persist_render_result_writes_generated_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    (workspace / "plan.md").write_text("# plan\n", encoding="utf-8")

    run_state = new_run_state(
        input_file="idea.md",
        output_goal="goal",
        input_digest="input",
        output_goal_digest="goal-digest",
        limits=PlanningLimits(),
    )
    save_run_state(output_dir, run_state)

    goal = render_output_goal()
    deps = RenderFlowDeps(
        workspace_root=workspace,
        output_dir=output_dir,
        loaded=None,
        output_goal=goal,
        embed_threshold=4000,
        render=RenderConfig(),
        client=None,  # type: ignore[arg-type]
        renderer=None,  # type: ignore[arg-type]
        stream=None,  # type: ignore[arg-type]
        audit=False,
        resolve_render_context=lambda: None,
        resolve_render_model=lambda: None,
        resolve_review_context=lambda: None,
        resolve_review_model=lambda: None,
        session_timeout_seconds=600,
    )

    _persist_render_result(deps, run_state, ["plan.md"])

    loaded = load_run_state(output_dir)
    assert loaded is not None
    assert loaded.generated_artifacts == ["plan.md"]
