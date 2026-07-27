"""Deterministic render batch schedule construction."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning.digest import compute_render_config_digest, digest_text
from top_down_planning.models import PlanState, RenderBatchSchedule, RenderConfig
from top_down_planning.render_scheduler import build_render_batch_schedule


def build_render_schedule(
    plan: PlanState,
    *,
    run_id: str,
    plan_digest: str,
    output_goal_digest: str,
    render_config: RenderConfig,
    output_dir=None,
) -> tuple[RenderBatchSchedule, list[str]]:
    batches, errors = build_render_batch_schedule(
        plan,
        render_config=render_config,
        output_dir=output_dir,
    )
    return (
        RenderBatchSchedule(
            run_id=run_id,
            plan_digest=plan_digest,
            output_goal_digest=output_goal_digest,
            render_config_digest=compute_render_config_digest(render_config),
            batches=batches,
        ),
        errors,
    )


def compute_schedule_digest(schedule: RenderBatchSchedule) -> str:
    payload = schedule.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return digest_text(canonical)


def save_render_schedule(path: Path, schedule: RenderBatchSchedule) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(schedule.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_render_schedule(path: Path) -> RenderBatchSchedule:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RenderBatchSchedule.model_validate(data)
