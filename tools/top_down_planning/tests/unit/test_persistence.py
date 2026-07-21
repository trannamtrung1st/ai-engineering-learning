from pathlib import Path

import pytest
import yaml

from top_down_planning.models import PlanningLimits, RunActiveStatus
from top_down_planning.persistence import (
    STATE_DIRNAME,
    ensure_resume_compatible,
    load_plan,
    load_run_state,
    new_run_state,
    save_plan,
    save_run_state,
)
from top_down_planning.scheduler import initialize_root_plan
from tests.plan_factory import make_root_plan
from top_down_planning.errors import ResumeError


def test_atomic_persistence_roundtrip(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="input",
        output_goal_digest="goal-d",
    )
    run = new_run_state(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="input",
        output_goal_digest="goal-d",
        limits=PlanningLimits(),
    )
    save_plan(tmp_path, plan)
    save_run_state(tmp_path, run)

    loaded_plan = load_plan(tmp_path)
    loaded_run = load_run_state(tmp_path)
    assert loaded_plan is not None
    assert loaded_run is not None
    assert loaded_plan.plan[0].id == "item-001"
    assert loaded_run.active_status == RunActiveStatus.RUNNING

    raw = yaml.safe_load(
        (tmp_path / STATE_DIRNAME / "plan.yaml").read_text(encoding="utf-8")
    )
    assert raw["schema_version"] == 1


def test_legacy_root_state_migrates_on_save(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="input",
        output_goal_digest="goal-d",
    )
    legacy_plan = tmp_path / "plan.yaml"
    legacy_plan.write_text("schema_version: 1\n", encoding="utf-8")

    save_plan(tmp_path, plan)

    assert (tmp_path / STATE_DIRNAME / "plan.yaml").is_file()
    assert not legacy_plan.exists()
    loaded = load_plan(tmp_path)
    assert loaded is not None
    assert loaded.plan[0].id == "item-001"


def test_legacy_state_dir_is_readable(tmp_path: Path) -> None:
    from top_down_planning.persistence import LEGACY_STATE_DIRNAME
    import shutil

    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="input",
        output_goal_digest="goal-d",
    )
    save_plan(tmp_path, plan)
    shutil.move(tmp_path / STATE_DIRNAME, tmp_path / LEGACY_STATE_DIRNAME)

    loaded = load_plan(tmp_path)
    assert loaded is not None
    assert loaded.plan[0].id == "item-001"

    save_plan(tmp_path, plan)
    assert (tmp_path / STATE_DIRNAME / "plan.yaml").is_file()


def test_resume_rejects_changed_input(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="old",
        output_goal_digest="goal-d",
    )
    run = new_run_state(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="old",
        output_goal_digest="goal-d",
        limits=PlanningLimits(),
    )
    save_plan(tmp_path, plan)
    save_run_state(tmp_path, run)

    with pytest.raises(ResumeError):
        ensure_resume_compatible(
            tmp_path,
            input_digest="new",
            output_goal_digest="goal-d",
            limits=PlanningLimits(),
            resume=True,
        )


def test_resume_rejects_changed_stop_hint(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
        stop_hint_digest="old-hint",
    )
    run = new_run_state(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
        stop_hint_digest="old-hint",
        limits=PlanningLimits(),
    )
    save_plan(tmp_path, plan)
    save_run_state(tmp_path, run)

    with pytest.raises(ResumeError, match="Stop hint digest mismatch"):
        ensure_resume_compatible(
            tmp_path,
            input_digest="a",
            output_goal_digest="b",
            stop_hint_digest="new-hint",
            limits=PlanningLimits(),
            resume=True,
        )


def test_new_output_requires_resume_flag(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(tmp_path, plan)
    with pytest.raises(ResumeError):
        ensure_resume_compatible(
            tmp_path,
            input_digest="a",
            output_goal_digest="b",
            limits=PlanningLimits(),
            resume=False,
        )
